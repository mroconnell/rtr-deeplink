import asyncio
import logging
import re
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import aiohttp

from .base import AssetFinder
from .models import ResolvedMeeting, TranscriptSegment

logger = logging.getLogger("rtr_deeplink.invintus")
from ..utils.vtt_parser import (
    decode_vtt_bytes,
    detect_language_from_texts,
    is_likely_garbled,
    parse_vtt,
)

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


# --- Hub listing (WO-922) ---------------------------------------------
#
# Everything above resolves ONE known event. Nothing listed a tenant's
# events until WO-922 (2026-09-20), which found the listing API by reading
# the `eventlisting.invintus.com/app.js` widget that the Oregon
# Legislature's own video page embeds (`InvintusEventListing.launch(
# {"clientID":"4879615486", ...})`), then confirmed it live against both
# state-legislature tenants:
#
#   POST https://api.v3.invintus.com/v2/Search/general
#   (same public "embedder" headers as getDetailed above)
#   Body: {"clientID": ..., "resultMax": 50, "resultPage": 1,
#          "sortBy": "DESC", "status": "published",
#          "startDateTime": "YYYY-MM-DD", "stopDateTime": "YYYY-MM-DD",
#          "terms": "*", "showMediaAssets": true, "showRuntime": true,
#          "showDocumentAssets": false}
#
# Three real facts worth knowing before touching it (all measured live):
#   * `startDateTime`/`stopDateTime` are REQUIRED in practice. Without
#     them the API answers 200 with an empty `data` list, which looks
#     exactly like a tenant with no events.
#   * `sortBy` is "DESC"/"ASC" (the widget maps its own "descending"),
#     newest first with "DESC".
#   * Each row carries `eventID`, `title`, `startDateTime` ("YYYY-MM-DD
#     HH:MM:SS"), `runtimeMinutes`, `categories`, `videoDownload`
#     (a public m-download.invintus.com mp4), but never `captionPath`;
#     captions exist only on `Event/getDetailed`, which `resolve()`
#     already calls.
#
# Real tenants recorded here (the `clientID` is the only thing that tells
# one Invintus customer from another; `player.invintus.com` is shared):
#   4879615486  Oregon Legislature (oregonlegislature.gov video page)
#   2789595964  WisconsinEye (wiseye.org; a nonprofit that also covers
#               courts, the governor, campaigns and news conferences, so a
#               legislative filter is needed, see below)
#   6361162879  Arizona Legislature (already handled by az_legislature.py)
_SEARCH_URL = "https://api.v3.invintus.com/v2/Search/general"
_PLAYER_URL = "https://player.invintus.com/?clientID={client_id}&eventID={event_id}"
_HUB_WINDOW_DAYS = 120
_HUB_PAGE_SIZE = 50

# clientID -> (state gov_id, government display name). One government per
# state, the chamber or committee is the meeting body (architecture
# decision D1); never a chamber-level id.
LEGISLATURE_CLIENTS = {
    "4879615486": ("us:state:41", "Oregon Legislative Assembly"),
    "2789595964": ("us:state:55", "Wisconsin State Legislature"),
}

_CLIENT_ID_IN_PAGE_RE = re.compile(r"""["']?clientID["']?\s*[:=]\s*["']?(\d{6,})""")
_TRAILING_DATE_TIME_RE = re.compile(
    r"\s+\d{1,2}/\d{1,2}/\d{2,4}(?:\s+\d{1,2}:\d{2}\s*[AP]M)?\s*$", re.IGNORECASE
)


def is_invintus_hub_url(url: str) -> bool:
    """A player.invintus.com (or other invintus.com) URL that names a
    tenant (`clientID`) but no single event: a hub, not a meeting."""
    netloc = urlparse(url).netloc.lower()
    if not netloc.endswith("invintus.com"):
        return False
    client_id, event_id = parse_invintus_ids(url)
    return bool(client_id and not event_id)


def extract_invintus_client_id(html: str) -> Optional[str]:
    """The Invintus `clientID` a government page embeds, from an
    `InvintusEventListing.launch({"clientID":"N"...})` widget, an
    `Invintus.launch({'clientID':'N'...})` player, a `wisEyeConfig`
    object or a `player.invintus.com/?clientID=N` link. None unless the
    page also loads Invintus's own script or names an invintus.com host,
    so an unrelated `clientID` (an OAuth client id, say) is not taken."""
    lowered = html.lower()
    if "invintus" not in lowered:
        return None
    match = _CLIENT_ID_IN_PAGE_RE.search(html.replace("&amp;", "&"))
    return match.group(1) if match else None


def legislative_chamber(
    client_id: str, title: Optional[str], categories: Optional[List[str]]
) -> Optional[str]:
    """For a known state-legislature tenant, the chamber an event belongs
    to ("House", "Assembly", "Senate", "Joint"), or None when the event
    is not a legislative meeting (a news conference, a court hearing, a
    campaign interview, a podcast). Only meaningful for the tenants in
    `LEGISLATURE_CLIENTS`; any other tenant returns None for everything.

    Reads the event's own title first (Oregon and Wisconsin both name
    committees and floor sessions in it), then the WisconsinEye
    categories. Real, live-measured shapes: Oregon "House Interim
    Committee On Higher Education 09/10/2026 12:30 PM", "Senate Chamber
    Convenes ...", "Joint Task Force On ..."; Wisconsin "Senate Committee
    on Health", "Assembly Committee on Environment", "Joint Committee on
    Finance", "Wisconsin State Assembly Floor Session", "2026 Legislative
    Council Study Committee on Cemeteries". Oregon's "News Conferences &
    Non-Legislative Videos" and WisconsinEye's News Conference / Circuit
    Court / WisPolitics / Campaign / Rewind rows are deliberately not
    matched."""
    if client_id not in LEGISLATURE_CLIENTS:
        return None
    text = (title or "").strip()
    lowered = text.lower()
    cats = [c.lower() for c in (categories or [])]
    if client_id == "4879615486":
        first = lowered.split(" ", 1)[0] if lowered else ""
        return {"house": "House", "senate": "Senate", "joint": "Joint"}.get(first)
    # Wisconsin (WisconsinEye): exclude non-legislative program types first.
    blocked_prefixes = (
        "news conference",
        "campaign",
        "rewind",
        "wispolitics",
        "circuit court",
        "dane county circuit",
    )
    if lowered.startswith(blocked_prefixes) or "circuit court" in cats:
        return None
    if "legislative council" in lowered or "study committee" in cats:
        return "Joint"
    if lowered.startswith(("joint ", "joint-")):
        return "Joint"
    if "assembly" in lowered and "senate" in lowered:
        return "Joint"
    if "assembly" in lowered:
        return "Assembly"
    if "senate" in lowered:
        return "Senate"
    if "committees" in cats:
        if "state assembly" in cats and "state senate" in cats:
            return "Joint"
        if "state assembly" in cats:
            return "Assembly"
        if "state senate" in cats:
            return "Senate"
    return None


def legislative_meeting_body(title: Optional[str]) -> Optional[str]:
    """The committee or chamber name with a trailing "MM/DD/YYYY H:MM PM"
    (Oregon puts one on every title) removed."""
    if not title:
        return None
    return _TRAILING_DATE_TIME_RE.sub("", title).strip() or None


async def list_recent_events(
    client_id: str,
    *,
    days: int = _HUB_WINDOW_DAYS,
    limit: int = 50,
    legislative_only: Optional[bool] = None,
    today: Optional[date] = None,
    session: Optional[aiohttp.ClientSession] = None,
) -> List[dict]:
    """Recent published events for an Invintus tenant, newest first, as
    `{"title", "date", "url", "event_id", "client_id", "duration",
    "chamber", "categories"}` dicts (`url` is the player URL
    `InvintusAssetFinder.resolve()` reads, `duration` is seconds).

    `legislative_only` defaults to True for a tenant in
    `LEGISLATURE_CLIENTS` (so WisconsinEye's court and news rows are
    dropped) and False otherwise. An unknown or empty tenant returns [].
    One request per page, 2 seconds apart."""
    if legislative_only is None:
        legislative_only = client_id in LEGISLATURE_CLIENTS
    end = today or date.today()
    start = end - timedelta(days=days)
    own_session = session is None
    if own_session:
        session = aiohttp.ClientSession()
    out: List[dict] = []
    try:
        page = 1
        while len(out) < limit and page <= 8:
            body = {
                "clientID": client_id,
                "resultMax": _HUB_PAGE_SIZE,
                "resultPage": page,
                "sortBy": "DESC",
                "status": "published",
                "startDateTime": start.isoformat(),
                "stopDateTime": end.isoformat(),
                "terms": "*",
                "showMediaAssets": True,
                "showRuntime": True,
                "showDocumentAssets": False,
            }
            try:
                async with session.post(
                    _SEARCH_URL,
                    json=body,
                    headers=_AUTH_HEADERS,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status != 200:
                        logger.warning(
                            "Invintus Search/general got HTTP %s for client %s",
                            response.status,
                            client_id,
                        )
                        break
                    payload = await response.json(content_type=None)
            except (aiohttp.ClientError, TimeoutError, ValueError):
                logger.warning(
                    "Invintus Search/general failed for client %s",
                    client_id,
                    exc_info=True,
                )
                break
            if (payload.get("errors") or {}).get("hasError"):
                break
            rows = payload.get("data") or []
            for row in rows:
                event_id = str(row.get("eventID") or row.get("id") or "")
                if not event_id:
                    continue
                title = row.get("title")
                categories = row.get("categories") or []
                chamber = legislative_chamber(client_id, title, categories)
                if legislative_only and not chamber:
                    continue
                minutes = row.get("runtimeMinutes")
                out.append(
                    {
                        "title": title,
                        "date": (row.get("startDateTime") or "")[:10] or None,
                        "url": _PLAYER_URL.format(
                            client_id=client_id, event_id=event_id
                        ),
                        "event_id": event_id,
                        "client_id": client_id,
                        "duration": minutes * 60 if minutes else None,
                        "chamber": chamber,
                        "categories": categories,
                    }
                )
                if len(out) >= limit:
                    break
            total_pages = (payload.get("meta") or {}).get("totalPages") or 0
            if len(rows) < _HUB_PAGE_SIZE or page >= total_pages:
                break
            page += 1
            await asyncio.sleep(2)
    finally:
        if own_session:
            await session.close()
    return out


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
            jurisdiction, meeting_body = self._extract_categories(
                data.get("categories")
            )
            if client_id in LEGISLATURE_CLIENTS and legislative_chamber(
                client_id, title, data.get("categories")
            ):
                # WO-922: a state-legislature tenant's `categories` are a
                # session code or a program type, not a jurisdiction
                # ("2025-2026 Interim", "Committees"), which would file
                # the page under a nonsense government. One government
                # per state; the committee or chamber is the meeting body.
                # Only for a legislative event: WisconsinEye's courts,
                # governor and news conferences keep their own categories.
                jurisdiction = LEGISLATURE_CLIENTS[client_id][1]
                meeting_body = legislative_meeting_body(title)

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
