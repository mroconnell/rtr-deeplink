import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder, ResolveError
from .models import ResolvedMeeting, TranscriptSegment
from ..utils.vtt_parser import decode_vtt_bytes, is_likely_garbled, parse_vtt

logger = logging.getLogger("rtr_deeplink.spectrumstream")

# spectrumstream.com (Studio Spectrum) -- a small, real, multi-tenant
# government video vendor, one meeting per `https://spectrumstream.com/
# streaming/{tenant}/{filename}.cfm` page. Confirmed live 2026-09-24
# against 5 real tenants (alhambra, arcadia, south_pasadena, gusd, bgpaa
# -- LA-area CA cities/school district/joint powers authority, discovered
# via Wayback CDX by the WO-1047 conductor) before writing any parsing
# code, per this repo's "test against a real URL first" rule.
#
# **Tenancy is PATH-based on one DNS-wildcarded domain, unlike
# twelvemilesout.py's sibling vendor** (confirmed: `spectrumstream.com`
# resolves for essentially any subdomain), so the real tenant identity is
# the `/streaming/{tenant}/` path segment, never the host --
# `parse_spectrumstream_tenant()` below is the one place that extracts
# it, excluding the shared static-asset folder (`_jwplayer`) and the
# non-government tenants the WO-1047 discovery notes name explicitly
# (`gef`, `lef`, any `*_grad` graduation-ceremony tenant).
#
# **Every real per-meeting page shares one legacy ColdFusion template**
# (confirmed across all 5 tenants, spanning at least a 2017-2026 date
# range): a `class="instructions"` table cell whose first `<strong>`
# block holds the real meeting body name and date/time as free text (one
# real tenant, Arcadia, nests an extra `<h1>` inside that `<strong>` --
# `_extract_title_date()` below strips all inner markup with BeautifulSoup
# rather than assuming a fixed tag shape), a `jwplayer("myElement")
# .setup({file: "https://spectrum_streaming.s3.amazonaws.com/{tenant}/
# {tenant}_{date}.mp4", ...})` inline script (a plain, direct,
# unauthenticated S3 MP4 -- the SAME url appears twice, once per browser-
# capability branch, so only the first match is used), and a
# `<div>`/`<a href="#" onclick="jwplayer().seek({seconds})">` agenda list
# whose seek()-linked anchors are this platform's only real per-item
# timestamps (an item with no seek link carries no real start time and is
# skipped, same reasoning granicus.py's own agenda-item extraction uses).
#
# **Captions**: when present, the SAME jwplayer setup carries a `tracks:
# [{file: "https://www.spectrumstream.com/streaming/{tenant}/
# meeting_captions/{tenant}_{date}.vtt", label: "English", kind:
# "captions"}]` entry -- confirmed live returning real WebVTT text
# (Alhambra, 2026-08-24 special+regular City Council meeting). Two real
# negative shapes, both confirmed live and NOT errors: the `tracks` array
# present but its `file` an EMPTY string (Glendale USD -- a real "no
# captions yet" marker, not a broken URL) and the `tracks` key absent
# entirely from the script (South Pasadena, Burbank-Glendale-Pasadena
# Airport Authority). Every real caption label seen so far is "English"
# (a single-language vendor) -- trusted directly as TARGET_LANGUAGE
# rather than run through langdetect, the same "real, source-declared
# metadata beats a guess" reasoning as `is_likely_garbled()`'s own use
# below for a defensive garbled-at-the-source check.
#
# **South Pasadena's own tenant ROOT page is a real, confirmed exception**
# worth calling out: as of 2026-09-24 it renders a live-only Castr
# embed (`player.castr.com/live_...`) with its entire old agenda/past-
# meetings `<select>` HTML-commented out -- but its real per-meeting
# archive pages (`/streaming/south_pasadena/{date}.cfm`, found via
# Wayback CDX, no "meeting_" filename prefix unlike Alhambra) are
# unaffected and still resolve fine, and each one still embeds the SAME
# full, current past-meetings `<select>` every other tenant's meeting
# page does. See `passive_verify._spectrumstream_walker()`'s own
# docstring for how the listing walker works around this.
#
# **Jurisdiction**: a small, curated, confirmed-live tenant map
# (`TENANT_JURISDICTIONS` below), same pattern as twelvemilesout.py's own
# `TENANT_JURISDICTIONS` and proudcity.py's domain map -- this vendor's
# tenant slugs don't self-describe reliably enough to derive a
# jurisdiction from them alone (`gusd`, `bgpaa`).
TARGET_LANGUAGE = "en"

TENANT_JURISDICTIONS: Dict[str, str] = {
    "alhambra": "Alhambra, CA",
    "arcadia": "Arcadia, CA",
    "south_pasadena": "South Pasadena, CA",
    # South Pasadena's own committees/commissions -- real path segments
    # named in the WO-1047 discovery notes, sharing the same city.
    "south_pasadena_pc": "South Pasadena, CA",
    "south_pasadena_chc": "South Pasadena, CA",
    "south_pasadena_psc": "South Pasadena, CA",
    "south_pasadena_drb": "South Pasadena, CA",
    "south_pasadena_fc": "South Pasadena, CA",
    "south_pasadena_lbt": "South Pasadena, CA",
    "south_pasadena_nrec": "South Pasadena, CA",
    "south_pasadena_pac": "South Pasadena, CA",
    "south_pasadena_prc": "South Pasadena, CA",
    "south_pasadena_pwc": "South Pasadena, CA",
    "south_pasadena_scc": "South Pasadena, CA",
    "south_pasadena_mtic": "South Pasadena, CA",
    "south_pasadena_dpac": "South Pasadena, CA",
    "south_pasadena_ot": "South Pasadena, CA",
    "gusd": "Glendale Unified School District, CA",
    "bgpaa": "Burbank-Glendale-Pasadena Airport Authority, CA",
}

# Confirmed non-government tenants (WO-1047 discovery notes) -- a
# graduation-ceremony webcast or an unrelated foundation, never a real
# government meeting archive.
_NON_GOV_TENANTS = frozenset({"gef", "lef"})
_NON_GOV_SUFFIXES = ("_grad",)

# The vendor's own shared static-asset path segment -- never a tenant.
_NON_TENANT_PATH_SEGMENTS = frozenset({"_jwplayer"})

_TENANT_PATH_RE = re.compile(r"^/streaming/([^/]+)/?", re.IGNORECASE)

_JWPLAYER_FILE_RE = re.compile(
    r'jwplayer\(\s*"myElement"\s*\)\s*\.setup\(\s*\{\s*file:\s*"([^"]+)"',
    re.IGNORECASE,
)
_TRACKS_FILE_RE = re.compile(r'tracks:\s*\[\s*\{\s*file:\s*"([^"]*)"', re.IGNORECASE)

# The bucket name has an underscore (`spectrum_streaming`), and a
# virtual-hosted S3 address (`spectrum_streaming.s3.amazonaws.com`) fails
# TLS hostname verification for any client that checks certificates
# (confirmed live 2026-09-24: Glendale USD's ingest probe failed with
# "Hostname mismatch"). The path-style address serves the same object.
_VHOST_S3_RE = re.compile(
    r"^https?://([^./]+_[^./]*)\.s3\.amazonaws\.com/", re.IGNORECASE
)


def _path_style_s3(url: str) -> str:
    """Rewrite `https://<bucket_with_underscore>.s3.amazonaws.com/key` to
    `https://s3.amazonaws.com/<bucket>/key`; any other URL is unchanged."""
    return _VHOST_S3_RE.sub(lambda m: f"https://s3.amazonaws.com/{m.group(1)}/", url)


_SEEK_RE = re.compile(r"jwplayer\(\)\.seek\((\d+)\)")

_HEADER_DATE_RE = re.compile(
    r"(?:(?:Sun|Mon|Tues?|Wed(?:nes)?|Thurs?|Fri|Sat(?:ur)?)[a-z]*,?\s*)?"
    r"([A-Z][a-z]+\s+\d{1,2},?\s*\d{4})"
    r"(?:,?\s*\d{1,2}:\d{2}\s*[ap]\.?\s*m\.?)?",
)

_LISTING_MAX_TRIED = 6


def is_spectrumstream_non_gov_tenant(tenant: str) -> bool:
    tenant_lower = tenant.lower()
    if tenant_lower in _NON_GOV_TENANTS:
        return True
    return any(tenant_lower.endswith(suffix) for suffix in _NON_GOV_SUFFIXES)


def parse_spectrumstream_tenant(url: str) -> Optional[str]:
    """The real tenant slug from a `/streaming/{tenant}/...` URL on
    spectrumstream.com (any host -- see this module's own docstring for
    why the domain is DNS-wildcarded), or `None` when the URL isn't this
    vendor's shape, is the shared static-asset folder, or is a confirmed
    non-government tenant."""
    netloc = urlparse(url).netloc.lower()
    if not (netloc == "spectrumstream.com" or netloc.endswith(".spectrumstream.com")):
        return None
    match = _TENANT_PATH_RE.match(urlparse(url).path)
    if not match:
        return None
    tenant = match.group(1)
    if tenant.lower() in _NON_TENANT_PATH_SEGMENTS:
        return None
    if is_spectrumstream_non_gov_tenant(tenant):
        return None
    return tenant


class SpectrumStreamAssetFinder(AssetFinder):
    """Resolves a spectrumstream.com meeting's video, agenda chapters, and
    (when the tenant has them) real captions. See this module's own
    docstring for the real investigation this was built against."""

    platform_name = "spectrumstream"

    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        }

    async def resolve(self, url: str) -> ResolvedMeeting:
        tenant = parse_spectrumstream_tenant(url)
        if tenant is None:
            raise ResolveError(f"Could not find a Spectrum Stream tenant in URL: {url}")

        path = urlparse(url).path
        match = _TENANT_PATH_RE.match(path)
        remainder = path[match.end() :].lstrip("/") if match else ""

        if not remainder:
            return await self._resolve_listing(url, tenant)

        if remainder.lower().startswith("live.cfm"):
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                jurisdiction=TENANT_JURISDICTIONS.get(tenant),
                video_warnings=[
                    "This is a live-broadcast page, not a recorded meeting."
                ],
            )

        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response.raise_for_status()
                html = await response.text()

            return await self._resolve_meeting_html(session, url, tenant, html)

    async def _resolve_listing(self, url: str, tenant: str) -> ResolvedMeeting:
        """A tenant's own root (`/streaming/{tenant}/`) -- delegates
        enumeration to `_spectrumstream_walker()` (passive_verify.py),
        then re-resolves through each real candidate's own meeting URL,
        newest first."""
        from .passive_verify import _spectrumstream_walker

        candidates = await _spectrumstream_walker(url)
        if not candidates:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                jurisdiction=TENANT_JURISDICTIONS.get(tenant),
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

        segments: List[TranscriptSegment] = []
        transcript_language: Optional[str] = None
        transcript_warnings: List[str] = ["No captions found for this video."]

        caption_url = self._extract_caption_url(html)
        if caption_url:
            cues = await self._fetch_captions(session, caption_url)
            if cues:
                segments = [TranscriptSegment(**cue) for cue in cues]
                transcript_language = TARGET_LANGUAGE
                transcript_warnings = []
                if is_likely_garbled(cues, lang=TARGET_LANGUAGE):
                    transcript_warnings.append(
                        "This transcript looks garbled at the source (not "
                        "a parsing bug on our end) — treat it as "
                        "approximate."
                    )
            else:
                transcript_warnings = [
                    "A caption track is listed for this meeting but "
                    "couldn't be fetched or parsed."
                ]

        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            title=title,
            date=date,
            jurisdiction=TENANT_JURISDICTIONS.get(tenant),
            video_url=video_url,
            video_format="mp4" if video_url else None,
            segments=segments,
            transcript_language=transcript_language,
            agenda_items=agenda_items,
            video_warnings=video_warnings,
            transcript_warnings=transcript_warnings,
        )

    @staticmethod
    def _extract_title_date(html: str) -> Tuple[Optional[str], Optional[str]]:
        """The `class="instructions"` cell's first `<strong>` block holds
        the real meeting body name and date/time as free text, in one of
        several confirmed real shapes -- see this module's own docstring.
        Extracts the date substring with a regex (handles a leading
        weekday name and a trailing time-of-day) and treats everything
        else in the block as the title, rather than assuming a fixed
        line/tag structure (one real tenant, Arcadia, nests an extra
        `<h1>` inside the `<strong>`)."""
        idx = html.lower().find('class="instructions"')
        if idx == -1:
            return None, None
        strong_start = html.lower().find("<strong>", idx)
        if strong_start == -1:
            return None, None
        strong_end = html.lower().find("</strong>", strong_start)
        if strong_end == -1:
            return None, None
        fragment = html[strong_start + len("<strong>") : strong_end]
        text = BeautifulSoup(fragment, "html.parser").get_text(" ", strip=True)
        if not text:
            return None, None

        date_match = _HEADER_DATE_RE.search(text)
        date_iso = None
        title = text
        if date_match:
            title = (text[: date_match.start()] + text[date_match.end() :]).strip(" ,-")
            try:
                date_iso = datetime.strptime(
                    date_match.group(1).replace(",", ""), "%B %d %Y"
                ).strftime("%Y-%m-%d")
            except ValueError:
                date_iso = None
        return title.strip(" ,-<>br/") or None, date_iso

    @staticmethod
    def _extract_video_url(html: str) -> Optional[str]:
        match = _JWPLAYER_FILE_RE.search(html)
        return _path_style_s3(match.group(1)) if match else None

    @staticmethod
    def _extract_caption_url(html: str) -> Optional[str]:
        match = _TRACKS_FILE_RE.search(html)
        if not match:
            return None
        caption_url = match.group(1).strip()
        if not caption_url or not caption_url.lower().endswith(".vtt"):
            # A real, confirmed "no captions yet" shape (Glendale USD): the
            # `tracks` array is present but its `file` is an empty string.
            return None
        return caption_url

    @staticmethod
    def _extract_agenda_items(html: str) -> List[TranscriptSegment]:
        soup = BeautifulSoup(html, "html.parser")
        raw_items: List[Tuple[int, str]] = []
        for a in soup.find_all("a", onclick=True):
            onclick = a.get("onclick", "")
            match = _SEEK_RE.search(onclick)
            if not match:
                continue
            text = a.get_text(" ", strip=True)
            if not text:
                continue
            raw_items.append((int(match.group(1)), text))
        if not raw_items:
            return []
        raw_items.sort(key=lambda pair: pair[0])
        items: List[TranscriptSegment] = []
        for i, (start, text) in enumerate(raw_items):
            end = raw_items[i + 1][0] if i + 1 < len(raw_items) else start
            items.append(TranscriptSegment(start=start, end=max(end, start), text=text))
        return items

    @staticmethod
    async def _fetch_captions(session: aiohttp.ClientSession, caption_url: str):
        try:
            async with session.get(
                caption_url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "Spectrum Stream caption fetch got HTTP %s for %s",
                        response.status,
                        caption_url,
                    )
                    return None
                raw = await response.read()
        except Exception:
            logger.warning(
                "Spectrum Stream caption fetch failed for %s",
                caption_url,
                exc_info=True,
            )
            return None
        content = decode_vtt_bytes(raw)
        return parse_vtt(content) or None
