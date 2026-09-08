import logging
from datetime import datetime
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import aiohttp

from .base import AssetFinder
from .models import ResolvedMeeting, TranscriptSegment

logger = logging.getLogger("rtr_deeplink.invintus")
from ..utils.vtt_parser import decode_vtt_bytes, detect_language_from_texts, is_likely_garbled, parse_vtt

# Invintus Media (player.invintus.com) -- a general-purpose government
# webcasting platform (state legislatures, county boards, city councils),
# not tied to any one agenda/CMS vendor. Found 2026-09-08 via a real gap:
# University Place, WA's CivicPlus AgendaCenter page links 14 real
# per-meeting videos here, and CivicPlusAssetFinder had no way to
# recognize them (they were silently counted as "no video"). See
# `rtr-business/research/ENUMERATION_METHODS.md` §102 for the full
# investigation this was built from, per this repo's "never build a
# platform adapter from assumption" rule.
#
# **Every meeting URL is the same shape**: `player.invintus.com/?
# clientID={N}&eventID={M}` (also seen as `/index.html?clientID=...`),
# with no per-tenant subdomain at all -- one client is distinguished from
# another purely by `clientID`. `detect_platform()` claims a URL here
# only when BOTH ids are present, the same scoping Vimeo's own
# `is_vimeo_host()`/`parse_vimeo_video()` pair uses, so an unrelated page
# on the same apex domain (e.g. `hostedevents.invintus.com`'s one-off
# branded landing pages, confirmed live to carry neither param) is never
# claimed here.
#
# **The API, reverse-engineered from the player's own `app.js` (its `Po()`
# request-builder), confirmed live against real, independently-verified
# tenants in three different states**: University Place, WA (a city
# council, still active in 2026, the original gap); Clark County, WA (a
# Planning Commission, identified from its own Zoom name-tag overlay);
# Leon County, FL (a Tourism Development Council, identified from its own
# county-seal video thumbnail); and, historically, Des Moines, WA
# (confirmed via its own archived agenda PDF letterhead -- no longer a
# live Invintus customer, `jurisdiction_coverage.csv` already shows it on
# CivicWeb today). `streamlink` (an unrelated, well-known open-source
# project) independently ships its own `invintus.py` plugin against this
# exact same endpoint/auth shape, a useful outside cross-check that this
# reverse-engineering is right, not a fluke of one sample.
#
#   POST https://api.v3.invintus.com/v2/Event/getDetailed
#   Headers: Content-Type: application/json,
#            authorization: "embedder", wsc-api-key: "<see below>"
#   Body: {"clientID": ..., "eventID": ..., "showEncoder": true,
#          "showStreams": true, "includePrivate": false, "VAST": true,
#          "checkRecentBreak": true, "showDownloadLinks": true,
#          "showMediaAssets": true, "showDocumentAssets": true,
#          "getAudioDescriptionProjectID": true}
#
# The auth header pair is a fixed, public "embedder" credential baked
# into the player's own client-side JS bundle -- shipped to every browser
# that loads ANY Invintus embed, not a per-tenant or per-session secret,
# so calling it directly from a plain HTTP client is the same trust
# boundary as reading any other platform's public client-side API key
# already used elsewhere in this repo (e.g. ChampDS, Castus).
_API_URL = "https://api.v3.invintus.com/v2/Event/getDetailed"
_AUTH_HEADERS = {
    "Content-Type": "application/json",
    "authorization": "embedder",
    "wsc-api-key": "7WhiEBzijpritypp8bqcU7pfU9uicDR",
}

# **Video**: `downloadLinks.videoDownloadURI` (host `m-download.invintus.
# com`) is a direct, unauthenticated MP4 -- confirmed live with a HEAD
# request returning a real `content-length`/`content-type`. Preferred
# over `streamingURIs.main` (an HLS `.m3u8`, also unauthenticated and
# confirmed live) since a plain MP4 needs no HLS.js support and is what
# this adapter falls back to only when no direct download link exists.
# NOT the same as `mediaAssets[].fileUrl`, which points at
# `invintus-client-media.s3.amazonaws.com` directly -- confirmed live to
# 403 (a private bucket); `downloadLinks`/`captionPath`'s
# `m-download.invintus.com` host is the one that's actually public.
#
# **Captions**: `captionPath`, same `m-download.invintus.com` host, real
# populated WebVTT confirmed live on University Place (a full, coherent
# meeting transcript, not placeholder text). `None` on plenty of real
# events (confirmed on both Des Moines, WA and Leon County, FL samples,
# whose PRE-recording-only fixtures never generated captions) -- a real
# per-meeting negative, not a parse failure.
#
# **Jurisdiction**: `categories`/`categoriesDetail` carries a real
# `[jurisdiction, governing body]`-shaped list on SOME events (confirmed
# on University Place: `["University Place", "University Place City
# Council"]`) but is `null` on others (confirmed on both Des Moines and
# Leon County samples) -- this is a per-tenant configuration choice on
# Invintus's own dashboard, not something every client sets. Only ever
# confirmed populated on one real tenant, so this is used when present
# and left `None` otherwise rather than guessed at further.
TARGET_LANGUAGE = "en"


def parse_invintus_ids(url: str) -> Tuple[Optional[str], Optional[str]]:
    """Pulls `clientID`/`eventID` out of a player.invintus.com URL.
    `&amp;` (the literal HTML-entity form seen in raw, un-decoded
    AgendaCenter markup) is normalized to a real `&` first -- confirmed
    necessary against University Place's own page source, which emits
    exactly that form."""
    normalized = url.replace("&amp;", "&")
    query = parse_qs(urlparse(normalized).query)
    client_id = (query.get("clientID") or [None])[0]
    event_id = (query.get("eventID") or [None])[0]
    return client_id, event_id


def is_invintus_meeting_url(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    if not netloc.endswith("invintus.com"):
        return False
    client_id, event_id = parse_invintus_ids(url)
    return bool(client_id and event_id)


class InvintusAssetFinder(AssetFinder):
    """Resolves video + captions for an Invintus (player.invintus.com)
    meeting page. See the module docstring above for the real
    investigation this was built against."""

    platform_name = "invintus"

    async def resolve(self, url: str) -> ResolvedMeeting:
        client_id, event_id = parse_invintus_ids(url)
        if not client_id or not event_id:
            raise ValueError(
                f"Could not find an Invintus clientID/eventID in URL: {url}"
            )

        async with aiohttp.ClientSession() as session:
            data = await self._fetch_event_detail(session, client_id, event_id)
            if not data:
                return ResolvedMeeting(
                    platform=self.platform_name,
                    source_url=url,
                    external_id=f"invintus:{client_id}:{event_id}",
                    video_warnings=["No event found for this Invintus meeting."],
                )

            title = data.get("title")
            date = self._parse_date(data.get("startDateTime"))
            jurisdiction, meeting_body = self._extract_categories(data.get("categories"))

            video_warnings: List[str] = []
            download_links = data.get("downloadLinks") or {}
            video_url = download_links.get("videoDownloadURI")
            video_format = "mp4" if video_url else None
            if not video_url:
                video_url = (data.get("streamingURIs") or {}).get("main")
                video_format = "m3u8" if video_url else None
            if not video_url:
                video_warnings.append("No playable video found for this event.")

            segments: List[TranscriptSegment] = []
            transcript_language: Optional[str] = None
            transcript_warnings: List[str] = []
            caption_url = data.get("captionPath")
            if caption_url:
                cues = await self._fetch_vtt(session, caption_url)
                if cues:
                    segments = [TranscriptSegment(**cue) for cue in cues]
                    transcript_language = detect_language_from_texts(
                        c["text"] for c in cues
                    )
                    if is_likely_garbled(cues, lang=transcript_language):
                        transcript_warnings.append(
                            "This transcript looks garbled at the source (not "
                            "a parsing bug on our end) -- treat it as "
                            "approximate. You can request a transcript from "
                            "the audio instead."
                        )
                else:
                    transcript_warnings.append(
                        "A caption file is referenced for this event but "
                        "couldn't be fetched or parsed."
                    )
            else:
                transcript_warnings.append("No captions found for this video.")

        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            external_id=f"invintus:{client_id}:{event_id}",
            title=title,
            date=date,
            jurisdiction=jurisdiction,
            meeting_body=meeting_body,
            video_url=video_url,
            video_format=video_format,
            segments=segments,
            transcript_language=transcript_language,
            video_warnings=video_warnings,
            transcript_warnings=transcript_warnings,
        )

    @staticmethod
    async def _fetch_event_detail(
        session: aiohttp.ClientSession, client_id: str, event_id: str
    ) -> Optional[dict]:
        body = {
            "clientID": client_id,
            "eventID": event_id,
            "showEncoder": True,
            "showStreams": True,
            "includePrivate": False,
            "VAST": True,
            "checkRecentBreak": True,
            "showDownloadLinks": True,
            "showMediaAssets": True,
            "showDocumentAssets": True,
            "getAudioDescriptionProjectID": True,
        }
        try:
            async with session.post(
                _API_URL,
                json=body,
                headers=_AUTH_HEADERS,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "Invintus getDetailed got HTTP %s for client %s event %s",
                        response.status,
                        client_id,
                        event_id,
                    )
                    return None
                payload = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError):
            logger.warning(
                "Invintus getDetailed request failed for client %s event %s",
                client_id,
                event_id,
                exc_info=True,
            )
            return None
        if (payload.get("errors") or {}).get("hasError"):
            logger.warning(
                "Invintus getDetailed returned an error for client %s event %s: %s",
                client_id,
                event_id,
                payload["errors"].get("message"),
            )
            return None
        return payload.get("data") or None

    @staticmethod
    async def _fetch_vtt(session: aiohttp.ClientSession, vtt_url: str):
        try:
            async with session.get(
                vtt_url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "Invintus caption fetch got HTTP %s for %s",
                        response.status,
                        vtt_url,
                    )
                    return None
                raw = await response.read()
        except Exception:
            logger.warning(
                "Invintus caption fetch failed for %s", vtt_url, exc_info=True
            )
            return None
        content = decode_vtt_bytes(raw)
        return parse_vtt(content) or None

    @staticmethod
    def _parse_date(raw: Optional[str]) -> Optional[str]:
        if not raw:
            return None
        try:
            return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").strftime("%Y-%m-%d")
        except ValueError:
            return None

    @staticmethod
    def _extract_categories(
        categories: Optional[List[str]],
    ) -> Tuple[Optional[str], Optional[str]]:
        if not categories:
            return None, None
        jurisdiction = categories[0]
        meeting_body = categories[-1] if len(categories) > 1 else None
        return jurisdiction, meeting_body
