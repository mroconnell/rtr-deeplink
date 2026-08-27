import html as html_module
import re
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp

from .base import AssetFinder
from .models import ResolvedMeeting, TranscriptSegment
from .youtube import YouTubeAssetFinder
from ..utils import jurisdiction_enrich

# ProudCity (WordPress-based government CMS, `wp-proud-meeting` plugin +
# `wp-proud-theme` theme -- github.com/proudcity/wp-proud-meeting,
# github.com/proudcity/wp-proud-theme). Full evidence trail this was built
# from -- source-verified against the actual plugin/theme code, not
# inferred, plus a real live tenant enumeration round -- is in
# BACKLOG_DONE.md's 2026-08-26 entry.
#
# No shared apex domain: every tenant is white-labeled onto its own
# .gov/.org domain, so detect_platform() can't key on domain shape the way
# every other adapter here does (same problem Hyland had). PROUDCITY_KNOWN_DOMAINS
# is a curated, human-verified set -- same convention as Hyland's own
# _KNOWN_DOMAINS dict -- not a general rule; a domain not in this set falls
# through to generic_fallback.py, which already finds the video (see below)
# just without jurisdiction reliability, agenda_items, or a trusted (non
# best_effort) result.
#
# Video is a plain, static, server-rendered `<iframe src="youtube.com/
# embed/{id}">` -- confirmed from `wp-proud-theme/templates/
# content-single-meeting.php` -- so this already half-resolves via
# generic_fallback.py's own YouTube-embed detection today. What this
# adapter adds: (1) `data-youtube-seek="{seconds}"` bookmark anchors into
# real `agenda_items` (generic_fallback has no way to find these), (2) a
# reliable jurisdiction from `og:site_name` rather than best-effort page
# scanning, (3) the agenda/agenda_packet PDF (WP-Stateless/GCS-hosted,
# `storage.googleapis.com/proudcity/{tenant}/...`) as `agenda_link`, and
# (4) promotion out of `best_effort` status.
#
# `video_style === 'external'` is a second, real video field (a plain
# outbound `<a href>` link, not an embed) -- confirmed to exist in the
# theme template but not yet confirmed populated on any real tenant
# checked. Treated as a `video_link` pointer, never `video_url`, per this
# repo's convention that `video_url` must always be directly playable.
PROUDCITY_KNOWN_DOMAINS = frozenset(
    {
        # Live-verified 2026-08-26 with a real, current `meeting` post
        # type and a real resolved video -- see BACKLOG_DONE.md.
        "townoffairfaxca.gov",
        "www.cityofbelvedere.org",
        "www.cityofsanrafael.org",
        "www.somervillenj.org",
        "www.holyoke.org",
        "cityofmiamisburg.com",
        "santa-ana.gov",
        "www.colma.ca.gov",
        # Added the same day, second enumeration/push round -- real video
        # confirmed and pushed:
        "delawarecounty.in.gov",
        "www.cityofmontclair.org",
        "elatownship.gov",
        "cityofpalmview.gov",
        "www.westhamptonbeach.gov",
        # Confirmed real (agenda content pushed) but no video found on the
        # meeting checked -- included so a re-resolve gets the reliable
        # jurisdiction/agenda_items treatment rather than generic_fallback's
        # best-effort one, not because video is expected here.
        "www.johnsoncitytx.org",
        "wilmingtonohio.gov",
        "www.hellamtownship.gov",
        "mckenziecountynd.gov",
        "alvordtx.gov",
        "cherrytownship.com",
        "franklin-twp.org",
    }
)

_MEETING_TITLE_RE = re.compile(
    r'<h1 class="entry-title">\s*([^<]+?)\s*</h1>', re.IGNORECASE
)
_SITE_NAME_RE = re.compile(
    r'<meta property="og:site_name" content="([^"]+)"', re.IGNORECASE
)
_DATE_RE = re.compile(r"Date and time:\s*(\d{4}-\d{2}-\d{2})")
_GCS_DOC_RE = re.compile(
    r"https://storage\.googleapis\.com/proudcity/[^\s\"'<>]+\.(?:pdf|doc|docx)",
    re.IGNORECASE,
)
# Real per-item deep-link bookmarks (`wp-proud-theme/templates/
# content-single-meeting.php`'s `youtube-list` markup): a label, then a
# `data-youtube-seek="{seconds}"` anchor. Not yet confirmed populated on
# any real tenant checked this session -- every real meeting page fetched
# had an empty bookmark list -- so this is schema-verified against the
# real template source, not content-verified against a positive real
# example. See this repo's "don't claim a data path works without a
# positive example" convention; kept in rather than held back because the
# markup itself, and the field it targets, are both already real and
# proven (agenda_items/TranscriptSegment), unlike a guessed API shape.
_BOOKMARK_RE = re.compile(
    r'data-youtube-seek="(\d+)">\s*([^<]+?)\s*<span', re.IGNORECASE
)
# `videoStyle === 'external'` case -- a plain outbound link, not an embed.
# Schema-verified against the theme source, not yet confirmed populated on
# a real tenant either.
_EXTERNAL_VIDEO_RE = re.compile(
    r'<a href="([^"]+)"[^>]*title="View video on external website"',
    re.IGNORECASE,
)

# Real, confirmed incident, 2026-08-26: `/meetings/example-city-council-
# meeting/` is a shared WordPress seed/demo post every ProudCity install
# ships with and evidently never removes -- confirmed on three unrelated
# tenants (Santa Ana CA, Palmview TX, Cambridge Township PA), two of which
# carry one of ProudCity's own marketing/demo YouTube videos
# (uploader "ProudCity", one literally titled "San Rafael + ProudCity")
# rather than any real meeting. Two real pages were accidentally ingested
# from this before it was caught and deleted (BACKLOG_DONE.md). Never
# treat this slug as a real meeting, regardless of what it resolves to.
#
# A systemic backstop for this same failure shape now also exists at
# ingest time (archive/utils/suspicious_source.py, wired into
# crud.ingest_resolution()) -- this check stays here anyway since it's
# strictly stronger (a known-zero-false-positive exact match refusing
# the resolve outright, vs. the ingest-time backstop's lower-confidence
# heuristic that only flags for review).
_DEMO_SLUG_RE = re.compile(r"/example-city-council-meeting/?(?:[?#]|$)")


class ProudCityAssetFinder(AssetFinder):
    """ProudCity (WordPress `wp-proud-meeting` plugin). See module
    docstring above for the full delegation/known-domain reasoning."""

    platform_name = "proudcity"

    async def resolve(self, url: str) -> ResolvedMeeting:
        if _DEMO_SLUG_RE.search(urlparse(url).path):
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "This is ProudCity's own shared demo meeting page, not a "
                    "real one -- see proudcity.py's _DEMO_SLUG_RE."
                ],
            )

        async with aiohttp.ClientSession() as session:
            page_html = await self._fetch_text(session, url)

        if not page_html:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=["Could not fetch this ProudCity meeting page."],
            )

        title = self._extract_title(page_html)
        jurisdiction = self._extract_jurisdiction(page_html, url)
        date = self._extract_date(page_html)
        agenda_link = self._extract_agenda_link(page_html)
        agenda_items = self._extract_bookmarks(page_html)

        video_id = YouTubeAssetFinder.extract_video_id(page_html)
        if not video_id:
            video_id = YouTubeAssetFinder.extract_video_id(
                html_module.unescape(page_html)
            )

        if video_id:
            resolved = await YouTubeAssetFinder.resolve_video_id(
                video_id, source_url=url
            )
            resolved.title = title or resolved.title
            resolved.date = date or resolved.date
            resolved.jurisdiction = jurisdiction
            resolved.agenda_items = agenda_items
            resolved.agenda_link = agenda_link
            return resolved

        video_link = None
        external_match = _EXTERNAL_VIDEO_RE.search(page_html)
        if external_match:
            video_link = external_match.group(1)

        warnings = (
            ["We think the video is here, but can't play it directly: " + video_link]
            if video_link
            else ["No video found for this meeting."]
        )
        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            title=title,
            date=date,
            jurisdiction=jurisdiction,
            agenda_items=agenda_items,
            agenda_link=agenda_link,
            video_link=video_link,
            video_warnings=warnings,
        )

    @staticmethod
    def _extract_title(html: str) -> Optional[str]:
        match = _MEETING_TITLE_RE.search(html)
        return html_module.unescape(match.group(1)).strip() if match else None

    @staticmethod
    def _extract_jurisdiction(html: str, url: str) -> Optional[str]:
        match = _SITE_NAME_RE.search(html)
        if not match:
            return jurisdiction_enrich.known_jurisdiction_display(urlparse(url).netloc)
        name = html_module.unescape(match.group(1)).strip()
        return jurisdiction_enrich.enrich_jurisdiction_text(
            name, netloc=urlparse(url).netloc, page_text=html
        )

    @staticmethod
    def _extract_date(html: str) -> Optional[str]:
        match = _DATE_RE.search(html)
        return match.group(1) if match else None

    @staticmethod
    def _extract_agenda_link(html: str) -> Optional[str]:
        match = _GCS_DOC_RE.search(html)
        return html_module.unescape(match.group(0)) if match else None

    @staticmethod
    def _extract_bookmarks(html: str) -> List[TranscriptSegment]:
        raw: List[Tuple[float, str]] = []
        for match in _BOOKMARK_RE.finditer(html):
            seconds = float(match.group(1))
            text = html_module.unescape(match.group(2)).strip()
            if text:
                raw.append((seconds, text))
        raw.sort(key=lambda item: item[0])

        items: List[TranscriptSegment] = []
        for i, (seconds, text) in enumerate(raw):
            end = raw[i + 1][0] if i + 1 < len(raw) else seconds
            items.append(
                TranscriptSegment(start=seconds, end=max(end, seconds), text=text)
            )
        return items

    @staticmethod
    async def _fetch_text(session: aiohttp.ClientSession, url: str) -> Optional[str]:
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status != 200:
                    return None
                return await response.text()
        except Exception:
            return None
