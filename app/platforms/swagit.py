import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder
from .media_scan import scan_media_urls, media_type
from .models import ResolvedMeeting, TranscriptSegment


class SwagitAssetFinder(AssetFinder):
    """Resolves video + chapter markers for a Swagit meeting page.

    Swagit pages are server-rendered (unlike CivicClerk's SPA), so this
    reuses the Granicus-style "fetch HTML, scan it" approach rather than an
    API client — but the page structure itself is Swagit-specific:

      - Video: a jwplayer `playlist: [{...,"file":"https://archive-stream.
        granicus.com/.../playlist.m3u8"}]` JSON blob embedded in an inline
        <script> tag. Notably the actual video FILE is served from
        Granicus's own archive-stream CDN (confirmed 2026-08-06 against a
        real League City, TX meeting) — Swagit runs on Granicus's streaming
        infrastructure — but the page around it is entirely different from
        a Granicus page, so it still needs this separate parser. The
        shared `media_scan.scan_media_urls()` regex scan (also used by
        GranicusAssetFinder) picks up the .m3u8/.mp4 URLs from the raw HTML
        without needing to understand the jwplayer JSON structure.
      - Metadata: the <title> tag reliably follows "{Date}, {Title} - {City},
        {State}", e.g. "Jul 28, 2026 Regular Meetings - League City, TX" —
        cleaner and more reliable than Granicus's scraped/guessed metadata.
      - Chapters: `a.playerControl[data-ts][data-title]` elements, server-
        rendered with real agenda-item titles and second-offsets on
        meetings that have them populated (confirmed on a real regular
        meeting; a candidate-forum sample had these present but empty —
        chapter population appears to vary per meeting, same as everywhere
        else in this space). Used as the deep-link fallback exactly like
        CivicClerk's eventBookmarks, since deep-linking to a moment matters
        more here than a full transcript.
      - Real free-text transcript: the page's JS references
        `#transcript-fragments a[data-ts]`, but that container was never
        present in the static HTML for any sample checked — unverified
        whether it's ever server-rendered or requires a separate call; see
        BACKLOG.md. Attempted defensively below and simply yields nothing
        when absent.
    """

    platform_name = "swagit"

    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            ),
        }

    async def resolve(self, url: str) -> ResolvedMeeting:
        video_warnings: List[str] = []
        transcript_warnings: List[str] = []

        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=self.headers, allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                response.raise_for_status()
                final_url = str(response.url)
                html = await response.text()

        soup = BeautifulSoup(html, "html.parser")
        title, date, jurisdiction = self._extract_metadata(soup)

        media_urls = scan_media_urls(html, final_url)
        video_url, video_format = None, None
        for candidate in media_urls:
            if media_type(candidate) == "video" and candidate.lower().endswith(".m3u8"):
                video_url, video_format = candidate, "m3u8"
                break
        if not video_url:
            for candidate in media_urls:
                if media_type(candidate) == "video":
                    video_url, video_format = candidate, "mp4"
                    break
        if not video_url:
            video_warnings.append("No playable video found on this page.")

        segments: List[TranscriptSegment] = []

        fragments = soup.select("#transcript-fragments a[data-ts]")
        if fragments:
            # Unverified path: never observed populated in testing (see
            # class docstring). Handled in case some Swagit deployment has
            # this enabled with real transcript text.
            for a in fragments:
                try:
                    start = float(a.get("data-ts") or 0)
                except ValueError:
                    continue
                text = a.get_text(strip=True)
                if text:
                    segments.append(TranscriptSegment(start=start, end=start, text=text))

        if not segments:
            transcript_warnings.append("No transcript found for this event.")

        # Chapter markers are fetched independently of whether a real
        # transcript was found -- useful navigation context either way,
        # not just a fallback. Kept in its own field, never folded into
        # `segments`.
        #
        # Swagit's page renders each agenda-item marker in two separate
        # DOM copies (a compact video-index list + a detailed agenda
        # list), both matching this selector with identical (ts, title)
        # -- confirmed on a real League City meeting, which without
        # dedup rendered every chapter twice. Dedup on (start, text).
        agenda_items: List[TranscriptSegment] = []
        chapters = soup.select("a.playerControl[data-ts][data-title]")
        seen = set()
        marks = []
        for a in chapters:
            ts = a.get("data-ts")
            title_attr = a.get("data-title")
            if not ts or not title_attr:
                continue
            try:
                start = float(ts)
            except ValueError:
                continue
            text = title_attr.strip()
            key = (start, text)
            if key in seen:
                continue
            seen.add(key)
            marks.append((start, text))
        marks.sort(key=lambda m: m[0])
        for i, (start, text) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else start
            agenda_items.append(TranscriptSegment(start=start, end=max(end, start), text=text))

        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            title=title,
            date=date,
            jurisdiction=jurisdiction,
            video_url=video_url,
            video_format=video_format,
            segments=segments,
            agenda_items=agenda_items,
            video_warnings=video_warnings,
            transcript_warnings=transcript_warnings,
        )

    @staticmethod
    def _extract_metadata(soup: BeautifulSoup):
        raw_title = soup.title.get_text(strip=True) if soup.title else ""
        # "{Date}, {Meeting Title} - {City}, {State}"
        match = re.match(r"^(.*?)\s*-\s*([^,]+),\s*([A-Za-z]{2})\s*$", raw_title)
        title, jurisdiction = raw_title or None, None
        date = None
        if match:
            title_part, city, state = match.groups()
            title = title_part.strip() or None
            jurisdiction = f"{city.strip()}, {state.strip()}"
            date_match = re.match(
                r"^([A-Za-z]{3,9}\.?\s+\d{1,2},\s*\d{4})", title_part.strip()
            )
            if date_match:
                for fmt in ("%b %d, %Y", "%B %d, %Y"):
                    try:
                        date = datetime.strptime(date_match.group(1).replace(".", ""), fmt).strftime("%Y-%m-%d")
                        break
                    except ValueError:
                        continue
        return title, date, jurisdiction
