import base64
import binascii
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder
from .models import AlternateTranscript, ResolvedMeeting, TranscriptSegment
from ..utils.vtt_parser import decode_vtt_bytes, is_likely_garbled, parse_vtt

logger = logging.getLogger("rtr_deeplink.twelvemilesout")

# 12milesout.com -- a small, real, multi-tenant government video vendor
# (Fisher Integrated, Inc.), one meeting per `https://{tenant}.
# 12milesout.com/Video/Meeting/{guid}`-shaped page (the exact path segment
# casing/shape varies by tenant -- see below). Confirmed live 2026-09-24
# against 6 real tenants (escondido, coronado, colton, covina, bigbearlake,
# solanabeach -- all San Diego/Inland Empire, CA cities, discovered via
# Wayback CDX + DNS by the WO-1045 conductor) before writing any parsing
# code, per this repo's "test against a real URL first" rule.
#
# **Tenancy is per-subdomain, not per-path** (each tenant is its own real
# DNS CNAME onto `{tenant}-web.azurewebsites.net`) -- unlike
# spectrumstream.py's sibling vendor, which is path-based on one wildcarded
# domain. `is_twelvemilesout_tenant_host()` below is the one place that
# distinguishes a real tenant subdomain from the vendor's own bare/`www`
# marketing host and a small number of confirmed non-government subdomains
# (a radio station demo, the vendor's own CDN/media infra) that also
# resolve under `*.12milesout.com` per the WO-1045 DNS sweep.
#
# **Two real, distinct listing/template "themes" coexist across tenants,
# but the per-MEETING page shape is identical either way** (confirmed
# live across all 6 tenants): a plain server-rendered `<h2>{Title} -
# {M/D/YYYY}</h2>` heading, a direct, unauthenticated CloudFront MP4
# download link (`<a href="https://{cdn}/{slug}/videos/full/mp4/
# {slug}_720.mp4" download>`), a `#agenda-list` of `<li data-start=
# "{seconds}" data-duration="{seconds}">` chapter markers (each with a
# `.item` title and an optional `.suffix` line, e.g. "Consent Calendar
# Item 9"), and a hidden `<input type="hidden" name="_su" value="{base64}">`
# field. This adapter's `resolve()` never needs to know or care which
# listing theme a tenant uses -- the listing-only case is delegated to
# `passive_verify._twelvemilesout_walker()` (see that function's own
# docstring for the two themes), which always hands back a real per-
# meeting URL for this same parsing path.
#
# **Video**: the CloudFront MP4 download link is the video source (a
# plain, direct, unauthenticated file -- confirmed fetchable on every
# tenant checked), not the JW Player `file:`/HLS smil URL also present on
# the page (`https://lax-vod.12milesout.com/vod-cache/...smil:...` --
# `lax-vod` has no live DNS per the WO-1045 sweep, and the smil/HLS path
# would need an extra manifest fetch this vendor's own plain MP4 download
# link makes unnecessary).
#
# **Agenda timestamps**: `#agenda-list`'s `data-start`/`data-duration`
# attributes are real, source-provided chapter markers -- confirmed on
# every meeting page checked, present whether or not real captions exist.
#
# **Captions**: the hidden `_su` field is a pipe-delimited, base64-encoded
# string (`_extract_su_fields()` below mirrors the real client-side
# `parseEmbedded()` JS this vendor's own `pages_meeting_video.js` ships,
# confirmed live 2026-09-24 by fetching and reading that file) carrying
# `serverUrl|fileId|aspectRatio|videoDurationSeconds|videoId|thumbnailUrl|
# permaLink`. When the `<video>` tag's own `data-captions="{codes}"`
# attribute (a comma-separated ISO 639-1 list, e.g. "en,es" -- confirmed
# on Coronado; empty/absent when a tenant has no captions, confirmed on
# Covina/Escondido) is non-empty, the real caption text is a plain,
# unauthenticated GET to `/api/captions/{fileId}/{code}/0/
# {videoDurationSeconds * 1000}` -- confirmed live returning real WebVTT
# with real transcript text (Coronado, 2026-09-15 City Council meeting).
# The `data-captions` codes are trusted directly as the transcript's
# language rather than re-detected with langdetect -- this is real,
# source-declared metadata (the vendor's own player config), not a guess.
#
# **Jurisdiction**: every real tenant subdomain confirmed live is a
# curated entry in `TENANT_JURISDICTIONS` below, the same "small, curated,
# confirmed-live map" pattern this repo already uses for other vendors
# without a self-describing subdomain shape (see proudcity.py). A tenant
# not in that map still resolves fully -- it just gets no jurisdiction
# guess, rather than an invented one.
TARGET_LANGUAGE = "en"

# Curated, confirmed-live tenant -> jurisdiction map (2026-09-24, WO-1045
# discovery). Every one of these is a real DNS CNAME resolving today, per
# the conductor's Wayback CDX + DNS sweep -- all San Diego/Inland Empire,
# CA cities. `sdcwa` (San Diego County Water Authority) is a real,
# resolving tenant too, but the WO-1045 discovery notes flag it as
# "live only" (no confirmed video archive) -- deliberately left out of
# this map rather than guessed at.
TENANT_JURISDICTIONS: Dict[str, str] = {
    "escondido": "Escondido, CA",
    "coronado": "Coronado, CA",
    "colton": "Colton, CA",
    "covina": "Covina, CA",
    "delmar": "Del Mar, CA",
    "bigbearlake": "Big Bear Lake, CA",
    "solanabeach": "Solana Beach, CA",
}

# Subdomains confirmed by the WO-1045 DNS sweep to resolve under
# `*.12milesout.com` but NOT be a per-government meeting archive: the
# vendor's own bare marketing host (`www`), its CDN/media infrastructure
# (`lax-vod`, `media-h264`), and radio-station demo content (`radio`,
# `bcaradio`, `mighty1090`). Excluded so `detect_platform()` never
# misclassifies one of these as a resolvable government meeting archive.
_NON_TENANT_SUBDOMAINS = frozenset(
    {"www", "lax-vod", "media-h264", "radio", "bcaradio", "mighty1090"}
)

_SUFFIX = ".12milesout.com"

# Real hidden-field shape, decoded from `pages_meeting_video.js`'s own
# `parseEmbedded()` (confirmed live 2026-09-24 on Escondido/Coronado):
# `serverUrl|fileId|aspectRatio|videoDurationSeconds|videoId|
# playerImageUrl|permaLink`.
_SU_FIELD_RE = re.compile(r'name="_su"\s+value="([A-Za-z0-9+/=]+)"', re.IGNORECASE)
_MP4_LINK_RE = re.compile(
    r'<a\s+href="(https?://[^"]+\.mp4)"\s+download=""', re.IGNORECASE
)
_H2_TITLE_RE = re.compile(r"<h2>(.*?)</h2>", re.IGNORECASE | re.DOTALL)
_VIDEO_DATA_CAPTIONS_RE = re.compile(
    r'<video\b[^>]*\bdata-captions="([^"]*)"', re.IGNORECASE
)

# Bounded retry across a listing's real candidates -- same reasoning
# townhallstreams.py's own `_LISTING_MAX_TRIED` already documents: the
# single newest listed meeting isn't always the one with a real video
# (e.g. same-day, not yet processed).
_LISTING_MAX_TRIED = 6


def is_twelvemilesout_tenant_host(netloc: str) -> bool:
    """True for a real per-government tenant subdomain of 12milesout.com
    -- false for the bare/`www` marketing host and the confirmed non-
    tenant subdomains above. See this module's own docstring."""
    netloc = netloc.lower().rstrip(".")
    if not netloc.endswith(_SUFFIX):
        return False
    subdomain = netloc[: -len(_SUFFIX)]
    return bool(subdomain) and subdomain not in _NON_TENANT_SUBDOMAINS


class TwelveMilesOutAssetFinder(AssetFinder):
    """Resolves a 12milesout.com meeting's video, agenda chapters, and
    (when the tenant has them) real captions. See this module's own
    docstring for the real investigation this was built against."""

    platform_name = "twelvemilesout"

    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        }

    async def resolve(self, url: str) -> ResolvedMeeting:
        parsed = urlparse(url)
        tenant = parsed.netloc.split(".")[0].lower()

        if parsed.path in ("", "/"):
            return await self._resolve_listing(url)

        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response.raise_for_status()
                html = await response.text()

            return await self._resolve_meeting_html(session, url, tenant, html)

    async def _resolve_listing(self, url: str) -> ResolvedMeeting:
        """A tenant's own root/listing page -- delegates enumeration to the
        shared `_twelvemilesout_walker()` (passive_verify.py), then re-
        resolves through each real candidate's own meeting URL, newest
        first, same bounded-retry pattern as
        `TownHallStreamsAssetFinder._resolve_town_listing()`."""
        from .passive_verify import _twelvemilesout_walker

        candidates = await _twelvemilesout_walker(url)
        if not candidates:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "No past meeting found in this government's video archive."
                ],
            )
        last_result: Optional[ResolvedMeeting] = None
        for candidate in candidates[:_LISTING_MAX_TRIED]:
            last_result = await self.resolve(candidate["url"])
            if last_result.video_url:
                return last_result
        return last_result

    async def _resolve_meeting_html(
        self,
        session: aiohttp.ClientSession,
        url: str,
        tenant: str,
        html: str,
    ) -> ResolvedMeeting:
        title, date = self._extract_title_date(html)
        video_url = self._extract_video_url(html)
        video_warnings: List[str] = []
        if not video_url:
            video_warnings.append(
                "Could not find a playable video on this meeting page."
            )

        agenda_items = self._extract_agenda_items(html)

        su = self._extract_su_fields(html)
        video_duration_seconds = su.get("duration_seconds") if su else None

        segments: List[TranscriptSegment] = []
        transcript_language: Optional[str] = None
        alternate_transcripts: List[AlternateTranscript] = []
        transcript_warnings: List[str] = ["No captions found for this video."]

        caption_langs = self._extract_caption_languages(html)
        netloc = urlparse(url).netloc
        if caption_langs and su and su.get("file_id") and video_duration_seconds:
            duration_ms = int(video_duration_seconds * 1000)
            fetched: List[Tuple[str, list]] = []
            for lang in caption_langs:
                cues = await self._fetch_captions(
                    session, netloc, su["file_id"], lang, duration_ms
                )
                if cues:
                    fetched.append((lang, cues))

            target = next((c for c in fetched if c[0] == TARGET_LANGUAGE), None)
            chosen = target or (fetched[0] if fetched else None)

            if chosen:
                lang, cues = chosen
                segments = [TranscriptSegment(**cue) for cue in cues]
                transcript_language = lang
                transcript_warnings = []
                if lang != TARGET_LANGUAGE:
                    transcript_warnings.append(
                        f"These captions appear to be in '{lang}', not "
                        f"'{TARGET_LANGUAGE}' — no matching-language track "
                        "was found for this meeting."
                    )
                if is_likely_garbled(cues, lang=lang):
                    transcript_warnings.append(
                        "This transcript looks garbled at the source (not "
                        "a parsing bug on our end) — treat it as "
                        "approximate."
                    )
                alternate_transcripts = [
                    AlternateTranscript(
                        language=alt_lang,
                        segments=[TranscriptSegment(**cue) for cue in alt_cues],
                    )
                    for alt_lang, alt_cues in fetched
                    if alt_lang != lang
                ]
            else:
                transcript_warnings = [
                    "A caption track is listed for this meeting but "
                    "couldn't be fetched or parsed."
                ]

        jurisdiction = TENANT_JURISDICTIONS.get(tenant)
        external_id = (
            f"twelvemilesout:{tenant}:{su['video_id']}"
            if su and su.get("video_id")
            else None
        )

        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            external_id=external_id,
            title=title,
            date=date,
            jurisdiction=jurisdiction,
            video_url=video_url,
            video_format="mp4" if video_url else None,
            video_duration_seconds=video_duration_seconds,
            segments=segments,
            transcript_language=transcript_language,
            alternate_transcripts=alternate_transcripts,
            agenda_items=agenda_items,
            video_warnings=video_warnings,
            transcript_warnings=transcript_warnings,
        )

    @staticmethod
    def _extract_title_date(html: str) -> Tuple[Optional[str], Optional[str]]:
        """The `<h2>` heading is always `"{Title} - {M/D/YYYY}"` on a real
        meeting page (confirmed across all 6 tenants) -- split on the
        LAST " - " so a title that itself contains a hyphen (none seen
        yet, but titles are free text) doesn't break the split."""
        match = _H2_TITLE_RE.search(html)
        if not match:
            return None, None
        text = BeautifulSoup(match.group(1), "html.parser").get_text(" ", strip=True)
        if " - " not in text:
            return text or None, None
        title, _, date_text = text.rpartition(" - ")
        date_iso = None
        try:
            date_iso = datetime.strptime(date_text.strip(), "%m/%d/%Y").strftime(
                "%Y-%m-%d"
            )
        except ValueError:
            pass
        return title.strip() or None, date_iso

    @staticmethod
    def _extract_video_url(html: str) -> Optional[str]:
        match = _MP4_LINK_RE.search(html)
        return match.group(1) if match else None

    @staticmethod
    def _extract_agenda_items(html: str) -> List[TranscriptSegment]:
        soup = BeautifulSoup(html, "html.parser")
        agenda_list = soup.find(id="agenda-list")
        if not agenda_list:
            return []
        items: List[TranscriptSegment] = []
        for li in agenda_list.find_all("li"):
            start_raw = li.get("data-start")
            duration_raw = li.get("data-duration")
            if start_raw is None or duration_raw is None:
                continue
            try:
                start = float(start_raw)
                duration = float(duration_raw)
            except ValueError:
                continue
            item_tag = li.find("p", class_="item")
            suffix_tag = li.find("p", class_="suffix")
            item_text = item_tag.get_text(" ", strip=True) if item_tag else ""
            if not item_text:
                continue
            if suffix_tag:
                suffix_text = suffix_tag.get_text(" ", strip=True)
                if suffix_text:
                    item_text = f"{item_text} — {suffix_text}"
            items.append(
                TranscriptSegment(
                    start=start, end=max(start + duration, start), text=item_text
                )
            )
        return items

    @staticmethod
    def _extract_su_fields(html: str) -> Optional[dict]:
        match = _SU_FIELD_RE.search(html)
        if not match:
            return None
        try:
            decoded = base64.b64decode(match.group(1)).decode("utf-8", errors="replace")
        except (binascii.Error, ValueError):
            return None
        parts = decoded.split("|")
        if len(parts) < 5:
            return None
        try:
            duration_seconds = float(parts[3])
        except ValueError:
            duration_seconds = None
        return {
            "server_url": parts[0] or None,
            "file_id": parts[1] or None,
            "aspect_ratio": parts[2] or None,
            "duration_seconds": duration_seconds,
            "video_id": parts[4] or None,
        }

    @staticmethod
    def _extract_caption_languages(html: str) -> List[str]:
        match = _VIDEO_DATA_CAPTIONS_RE.search(html)
        if not match:
            return []
        return [code.strip() for code in match.group(1).split(",") if code.strip()]

    @staticmethod
    async def _fetch_captions(
        session: aiohttp.ClientSession,
        netloc: str,
        file_id: str,
        lang: str,
        duration_ms: int,
    ):
        caption_url = f"https://{netloc}/api/captions/{file_id}/{lang}/0/{duration_ms}"
        try:
            async with session.get(
                caption_url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "12milesout caption fetch got HTTP %s for %s",
                        response.status,
                        caption_url,
                    )
                    return None
                raw = await response.read()
        except Exception:
            logger.warning(
                "12milesout caption fetch failed for %s", caption_url, exc_info=True
            )
            return None
        content = decode_vtt_bytes(raw)
        return parse_vtt(content) or None
