import re
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from .base import AssetFinder
from .headless_browser import fetch_via_browser
from .models import ResolvedMeeting, TranscriptSegment
from .youtube import YouTubeAssetFinder

_VIDEO_ID_RE = re.compile(
    r"(?:youtube\.com/live/|youtube\.com/watch\?v=|youtu\.be/)([\w-]{11})"
)
_MONTH_DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2}),?\s+(\d{4})"
)
_MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


class SlcAssetFinder(AssetFinder):
    """Salt Lake City's own council meeting-recap pages
    (`slc.gov/council/{date}-meeting-recap/`).

    Confirmed live 2026-08-09: also behind a Cloudflare "Just a moment..."
    JS challenge (same class of blocker as Minneapolis LIMS, see
    headless_browser.py) -- uses fetch_via_browser() instead of the plain
    aiohttp GET every other adapter here uses.

    **Real, corrected finding this adapter is built on** (see BACKLOG.md
    and BACKLOG_DONE.md for the full investigation): these pages were
    originally assumed to embed *several distinct videos*. Checked live
    across four real pages instead of guessing from one -- every single
    one has exactly *one* video, with several manually-curated `t=`
    timestamp links into that one video for different agenda topics
    (e.g. 5 "(Watch)" links on the March 3, 2026 page, all pointing at
    the same `youtube.com/live/{id}`, just different `t=` values). So
    this delegates to YouTubeAssetFinder for one video + real captions,
    and turns every "(Watch)" link's timestamp + surrounding topic text
    into an agenda_items entry -- the same shape Minneapolis LIMS's own
    adapter produces from its structured JSON, confirmed to need zero
    frontend changes (see BACKLOG_DONE.md's mockup verification).
    """

    platform_name = "slc"

    async def resolve(self, url: str) -> ResolvedMeeting:
        page_html = await fetch_via_browser(url)
        soup = BeautifulSoup(page_html, "html.parser")

        video_id = self._extract_video_id(soup)
        agenda_items = self._extract_agenda_items(soup)
        date = self._extract_date(soup)

        if not video_id:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                date=date,
                jurisdiction="Salt Lake City, UT",
                video_warnings=["No video found on this meeting recap page."],
            )

        resolved = await YouTubeAssetFinder.resolve_video_id(video_id, source_url=url)
        resolved.title = "Salt Lake City Council Meeting"
        if date:
            resolved.date = date
        resolved.jurisdiction = "Salt Lake City, UT"
        resolved.agenda_items = agenda_items
        return resolved

    @staticmethod
    def _extract_video_id(soup: BeautifulSoup) -> Optional[str]:
        for a in soup.find_all("a", href=True):
            match = _VIDEO_ID_RE.search(a["href"])
            if match:
                return match.group(1)
        return None

    @staticmethod
    def _extract_agenda_items(soup: BeautifulSoup) -> List[TranscriptSegment]:
        segments: List[TranscriptSegment] = []
        for a in soup.find_all("a", href=True):
            if not _VIDEO_ID_RE.search(a["href"]):
                continue
            timestamp = SlcAssetFinder._extract_timestamp(a["href"])
            if timestamp is None:
                continue
            topic = SlcAssetFinder._nearest_topic_text(a)
            if topic:
                segments.append(
                    TranscriptSegment(start=timestamp, end=timestamp, text=topic)
                )
        segments.sort(key=lambda seg: seg.start)
        return segments

    @staticmethod
    def _extract_timestamp(href: str) -> Optional[float]:
        query = parse_qs(urlparse(href).query)
        raw = (query.get("t") or [None])[0]
        if raw is None:
            return None
        raw = raw.rstrip(
            "s"
        )  # "3034s" (plain youtube.com/watch links) vs "3034" (youtube.com/live links)
        try:
            return float(raw)
        except ValueError:
            return None

    @staticmethod
    def _nearest_topic_text(a) -> Optional[str]:
        container = a.find_parent(["p", "li", "div"])
        if container is None:
            return None
        # get_text(" ", strip=True)'s separator only applies between
        # separate tags -- a single text node's own internal newlines
        # (real word-wrapped source HTML, confirmed on real SLC pages)
        # survive as literal "\n" otherwise. Collapse all internal
        # whitespace runs to one space.
        text = " ".join(container.get_text(" ", strip=True).split())
        # Strip the link's own visible text ("Watch"/"Watch the Briefing")
        # and the parenthesized wrapper real pages use ("...(Watch)").
        text = re.sub(r"\(?\s*Watch(?:\s+the\s+Briefing)?\s*\)?\s*$", "", text).strip()
        return text or None

    @staticmethod
    def _extract_date(soup: BeautifulSoup) -> Optional[str]:
        if not soup.title:
            return None
        match = _MONTH_DATE_RE.search(soup.title.get_text())
        if not match:
            return None
        month = _MONTHS.index(match.group(1)) + 1
        day = int(match.group(2))
        year = match.group(3)
        return f"{year}-{month:02d}-{int(day):02d}"
