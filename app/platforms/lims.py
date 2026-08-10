import html
import json
import re
from typing import List, Optional

from .base import AssetFinder
from .headless_browser import fetch_via_browser
from .models import ResolvedMeeting, TranscriptSegment
from .youtube import YouTubeAssetFinder

_ID_RE = re.compile(r"/MarkedAgenda/[A-Za-z]+/(\d+)")
_PRE_RE = re.compile(r"<pre[^>]*>(.*?)</pre>", re.S)
_TITLE_RE = re.compile(r"^(.+?)\s+Agenda\s+\d{1,2}/\d{1,2}/\d{4}\s+.+?-\s*(.+)$")
_TITLE_DATE_RE = re.compile(r"Agenda\s+(\d{1,2})/(\d{1,2})/(\d{4})")


class LimsAssetFinder(AssetFinder):
    """Minneapolis's own "LIMS" (Legislative Information Management
    System), `lims.minneapolismn.gov/MarkedAgenda/{body}/{id}` -- `{body}`
    is a per-committee code (e.g. "CI" for City Council, "BHZ" for
    Business, Housing & Zoning -- real bug found 2026-08-10: `_ID_RE` used
    to hardcode `CI` literally, so any other committee's URL failed with
    "Could not find a meeting id in this LIMS URL" before even reaching
    the real resolve logic below). The numeric id is what actually
    matters -- it's the only part reused downstream (the
    `/MeetingYoutubeVideo/{id}` JSON endpoint takes just the number, no
    body code at all) -- so the fix is a general `[A-Za-z]+` match on that
    segment rather than trying to enumerate every real committee code.

    Confirmed live 2026-08-09: both the agenda page and its
    `/MeetingYoutubeVideo/{id}` JSON endpoint (same numeric id) return a
    genuine Cloudflare "Just a moment..." JS challenge to a plain HTTP
    request -- every other adapter's plain aiohttp fetch would fail here.
    Uses `headless_browser.fetch_via_browser()` instead -- see that
    module's own docstring for the fuller investigation (what was tried
    and ruled out before landing on a real headless Chromium fetch).

    Two headless fetches per resolve (the agenda page for title/date/
    jurisdiction, the JSON endpoint for the real video + per-item
    timestamps) -- confirmed the JSON data isn't embedded in the agenda
    page's own HTML (it's loaded via a separate AJAX call only when a
    visitor opens the "Meeting Video" modal), so there's no way to get
    both from one fetch. Real, accepted cost: a headless-browser fetch is
    meaningfully slower than this repo's usual plain-HTTP adapters.

    `SerializedVideoTimestamps` is a category -> item tree, not a flat
    list -- e.g. a "Discussion" category can itself have a real
    timestamp *and* contain several individually-timestamped items.
    `_flatten_timestamps()` below surfaces every entry that has a real
    timestamp, at any nesting level, as its own agenda_items entry,
    rather than only the leaves -- confirmed live this matters (a real
    sample has an untitled-file "Consent" category whose own timestamp
    would otherwise be dropped entirely).
    """

    platform_name = "lims"

    async def resolve(self, url: str) -> ResolvedMeeting:
        match = _ID_RE.search(url)
        if not match:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=["Could not find a meeting id in this LIMS URL."],
            )
        meeting_id = match.group(1)

        agenda_html = await fetch_via_browser(url)
        title, date, jurisdiction = self._extract_page_meta(agenda_html)

        json_url = f"https://lims.minneapolismn.gov/MeetingYoutubeVideo/{meeting_id}"
        json_html = await fetch_via_browser(json_url)
        video_id, agenda_items = self._extract_video_and_timestamps(json_html)

        if not video_id:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                title=title,
                date=date,
                jurisdiction=jurisdiction,
                video_warnings=["No video found for this LIMS meeting."],
            )

        resolved = await YouTubeAssetFinder.resolve_video_id(video_id, source_url=url)
        if title:
            resolved.title = title
        if date:
            resolved.date = date
        if jurisdiction:
            resolved.jurisdiction = jurisdiction
        resolved.agenda_items = agenda_items
        return resolved

    @staticmethod
    def _extract_page_meta(page_html: str):
        title_match = re.search(r"<title>([^<]*)</title>", page_html)
        if not title_match:
            return None, None, None
        raw_title = html.unescape(title_match.group(1)).strip()

        date = None
        date_match = _TITLE_DATE_RE.search(raw_title)
        if date_match:
            month, day, year = date_match.groups()
            date = f"{year}-{int(month):02d}-{int(day):02d}"

        title = jurisdiction = None
        split_match = _TITLE_RE.match(raw_title)
        if split_match:
            title = split_match.group(1).strip()
            jurisdiction = split_match.group(2).strip()

        return title, date, jurisdiction

    @staticmethod
    def _extract_video_and_timestamps(json_page_html: str):
        pre_match = _PRE_RE.search(json_page_html)
        if not pre_match:
            return None, []
        try:
            data = json.loads(html.unescape(pre_match.group(1)))
        except json.JSONDecodeError:
            return None, []

        video_url = data.get("url") or ""
        video_id_match = re.search(r"[?&]v=([\w-]{11})", video_url)
        video_id = video_id_match.group(1) if video_id_match else None

        agenda_items = LimsAssetFinder._flatten_timestamps(data.get("SerializedVideoTimestamps") or [])
        agenda_items.sort(key=lambda seg: seg.start)
        return video_id, agenda_items

    @staticmethod
    def _flatten_timestamps(entries: list) -> List[TranscriptSegment]:
        segments: List[TranscriptSegment] = []
        for entry in entries:
            seconds = LimsAssetFinder._as_seconds(entry.get("timeInSeconds"))
            title = entry.get("title")
            if seconds is not None and title:
                segments.append(TranscriptSegment(start=seconds, end=seconds, text=title))
            for file_entry in entry.get("files") or []:
                file_seconds = LimsAssetFinder._as_seconds(file_entry.get("timeInSeconds"))
                file_title = file_entry.get("title")
                if file_seconds is not None and file_title:
                    segments.append(TranscriptSegment(start=file_seconds, end=file_seconds, text=file_title))
        return segments

    @staticmethod
    def _as_seconds(value) -> Optional[float]:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
