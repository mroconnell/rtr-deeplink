import re
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder
from .models import ResolvedMeeting, TranscriptSegment
from ..utils import jurisdiction_enrich

# IQM2 (a Granicus-family product -- footer/support address confirmed,
# distinct UI/URL shape from the classic ViewPublisher/MediaPlayer this
# app already parses natively) doesn't host video itself: confirmed live
# 2026-08-13 against a real Atlanta, GA meeting
# (atlantacityga.iqm2.com/Citizens/Detail_Meeting.aspx?ID=4294) that its
# real "Video" link is a plain, static `OnClick="javascript:OpenWindow(
# '/Citizens/SplitView.aspx?Mode=Video&MeetingID={id}&...')"` attribute --
# present only on meetings that actually have a recording (a future/
# no-recording meeting's Video link stays a bare `href="#"` with no
# onclick at all, the reliable signal this adapter uses to tell the two
# cases apart). That SplitView.aspx page's own raw static HTML (a plain
# fetch, no JS/browser execution needed) carries a literal
# `<!-- MEDIA URL: https://archive-stream.granicus.com/... .m3u8-->`
# comment -- a real, direct Granicus HLS URL. Unlike Legistar/CivicPlus's
# page-link delegation (which hands off to GranicusAssetFinder's own
# resolve()), this app has no adapter for a *bare* Granicus stream URL, so
# this adapter sets video_url/video_format directly rather than
# delegating -- there's no Granicus *page* to delegate to here, just a
# stream. Confirmed the stream URL itself needs a real (non-default) User-
# Agent -- CloudFront 403s a plain `curl` default UA, 200s with a normal
# browser UA, and has no Referer restriction (unlike ChampDS's VOD2 path,
# see champds.py) -- this adapter's own headers use a current Chrome UA
# for every fetch, not the stale Chrome/91 string most other adapters in
# this repo still carry.
#
# Real per-item timestamps also exist, confirmed live on the same Atlanta
# example (65 real items: procedural entries like "Roll Call" alongside
# full ordinance/resolution text with real council-member names) -- a
# second page, reached by adding `Target=Detail&CssClass=AgendaOutline&
# Mode=Video&Frame=Nothing` to the *same* Detail_Meeting.aspx?ID={id} URL,
# renders every agenda item as an `<a class="AgendaOutlineLink"
# onclick="javascript:SetPosition({seconds});">{item text}</a>` -- reused
# here for both title/date/jurisdiction (that page carries the same
# `<title>` as the plain Detail_Meeting.aspx page) and agenda_items, so
# this adapter only ever needs two fetches total, not three.
#
# Santa Clara County, CA (sccgov.iqm2.com) is IQM2's other real confirmed
# customer -- title/date/jurisdiction extraction is confirmed to work the
# same way there (its own real <title>: "2026/08/14 09:00 AM Personnel
# Board Business Meeting - Web Outline - The County of Santa Clara,
# California"), but every "Video" link checked across several real past
# committee meetings there was still a bare, unpopulated placeholder,
# unlike Atlanta's -- unconfirmed whether that's because those specific
# meetings genuinely have no recording, or a real per-customer gap in this
# adapter. Not yet checked against a real past Board of Supervisors
# meeting specifically -- see BACKLOG.md.
# Real, confirmed bug (2026-08-23): a bare `[?&](?:ID|MeetingID)=(\d+)`
# regex just returns whichever of the two params happens to appear first
# in the URL's own query-string order -- fine for the two page shapes this
# adapter was originally built against (Detail_Meeting.aspx?ID={id} and
# SplitView.aspx?...MeetingID={id}, each carrying only ONE of the two
# params, confirmed live against Atlanta/Santa Clara -- see module
# docstring), but silently wrong on Detail_LegiFile.aspx URLs, a THIRD
# real IQM2 page shape (a single legislative file/agenda item's own detail
# page, e.g. `Detail_LegiFile.aspx?...&ID={file_id}&...&MeetingID=
# {meeting_id}`) where `ID` and `MeetingID` are two genuinely different
# numbers -- the file's own id, and the meeting it belongs to -- with `ID`
# appearing first in the query string. Confirmed live against a real
# Plainfield, NJ meeting during a 2026-08-23 backlog run: `Detail_LegiFile.
# aspx?...&ID=4641&...&MeetingID=1229` was extracting meeting_id=4641 (the
# LegiFile's own id), building `SplitView.aspx?...MeetingID=4641`, and
# getting back an empty `<!-- MEDIA URL: -->` (a real page, just for the
# wrong meeting) -- silently reported as "no usable audio/video source" on
# a meeting that in fact had a real, populated video (`MeetingID=1229`
# does return one). Confirmed the same shape (both params present, `ID`
# first) across every other Detail_LegiFile.aspx candidate skipped that
# same run (Genesee County MI, Prescott AZ, Roanoke County VA, Sullivan
# County NY, Teaneck NJ, and two CA water districts) -- not a one-off.
# Fix: try MeetingID first (the actually-correct identifier whenever it's
# present at all, on any of the three page shapes), fall back to bare ID
# only when MeetingID is genuinely absent (Detail_Meeting.aspx's own
# confirmed shape).
_MEETING_ID_PRIMARY_RE = re.compile(r"[?&]MeetingID=(\d+)", re.IGNORECASE)
_MEETING_ID_FALLBACK_RE = re.compile(r"[?&]ID=(\d+)", re.IGNORECASE)
# The literal "Web Outline" string is IQM2's own generic vendor branding
# (confirmed identical across both real customers), not a per-city
# variable -- a reliable fixed separator, unlike generic_fallback.py's
# looser pipe/dash guessing.
_TITLE_RE = re.compile(
    r"^(\d{4})/(\d{2})/(\d{2})\s+\d{1,2}:\d{2}\s*[AP]M\s+(.+?)\s*-\s*Web Outline\s*-\s*(.+?)\s*$",
    re.IGNORECASE,
)
_MEDIA_URL_RE = re.compile(r"MEDIA URL:\s*(\S+?)-->")
_SEEK_RE = re.compile(r"SetPosition\((\d+(?:\.\d+)?)\)")


class IQM2AssetFinder(AssetFinder):
    """IQM2 -- doesn't host video itself, delegates to a real Granicus HLS
    stream URL found in an HTML comment on a real, unauthenticated
    SplitView.aspx page. See module docstring above.
    """

    platform_name = "iqm2"

    def __init__(self):
        self.headers = {
            # A modern UA, not the Chrome/91 (2021) string most other
            # adapters here still use -- confirmed live 2026-08-13 that
            # the real Granicus stream URL this adapter fetches 403s a
            # plain default UA and needs a current one. See module
            # docstring.
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
        }

    async def resolve(self, url: str) -> ResolvedMeeting:
        meeting_id = self._extract_meeting_id(url)
        if not meeting_id:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=["Could not find a meeting id in this IQM2 URL."],
            )

        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        base_path = parsed.path.rsplit("/", 1)[0] or "/Citizens"

        outline_url = (
            f"{origin}{base_path}/Detail_Meeting.aspx?Target=Detail&CssClass=AgendaOutline"
            f"&Mode=Video&Frame=Nothing&ID={meeting_id}"
        )
        split_url = f"{origin}{base_path}/SplitView.aspx?Mode=Video&MeetingID={meeting_id}&Format=Minutes"

        async with aiohttp.ClientSession(headers=self.headers) as session:
            outline_html = await self._fetch_text(session, outline_url)
            split_html = await self._fetch_text(session, split_url)

        title, date, jurisdiction, agenda_items = None, None, None, []
        if outline_html:
            title, date, jurisdiction = self._extract_title_date_jurisdiction(
                outline_html
            )
            agenda_items = self._extract_agenda_items(outline_html)
            if jurisdiction:
                jurisdiction = jurisdiction_enrich.enrich_jurisdiction_text(
                    jurisdiction, netloc=parsed.netloc, page_text=outline_html
                )

        video_url = self._extract_video_url(split_html) if split_html else None

        if not video_url:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                title=title,
                date=date,
                jurisdiction=jurisdiction,
                agenda_items=agenda_items,
                video_warnings=["No video found for this meeting."],
            )

        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            title=title,
            date=date,
            jurisdiction=jurisdiction,
            video_url=video_url,
            video_format="m3u8",
            agenda_items=agenda_items,
        )

    @staticmethod
    def _extract_meeting_id(url: str) -> Optional[str]:
        match = _MEETING_ID_PRIMARY_RE.search(url) or _MEETING_ID_FALLBACK_RE.search(url)
        return match.group(1) if match else None

    @staticmethod
    def _extract_title_date_jurisdiction(
        html: str,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        soup = BeautifulSoup(html, "html.parser")
        title_tag = soup.title.get_text(strip=True) if soup.title else None
        if not title_tag:
            return None, None, None
        match = _TITLE_RE.match(title_tag)
        if not match:
            return None, None, None
        year, month, day, meeting_name, jurisdiction = match.groups()
        return meeting_name, f"{year}-{month}-{day}", jurisdiction

    @staticmethod
    def _extract_agenda_items(html: str) -> List[TranscriptSegment]:
        soup = BeautifulSoup(html, "html.parser")
        raw_items: List[Tuple[float, str]] = []
        for a in soup.find_all("a", class_="AgendaOutlineLink"):
            onclick = a.get("onclick") or ""
            seek_match = _SEEK_RE.search(onclick)
            if not seek_match:
                # Real, common case -- a supporting-document link (e.g.
                # "Minutes Packet", an appointment letter, a bio PDF)
                # rendered with the same CSS class but no SetPosition
                # onclick at all, since it isn't a real video moment.
                continue
            text = a.get_text(" ", strip=True)
            if not text:
                continue
            raw_items.append((float(seek_match.group(1)), text))

        raw_items.sort(key=lambda item: item[0])
        agenda_items: List[TranscriptSegment] = []
        for i, (start, text) in enumerate(raw_items):
            end = raw_items[i + 1][0] if i + 1 < len(raw_items) else start
            agenda_items.append(
                TranscriptSegment(start=start, end=max(end, start), text=text)
            )
        return agenda_items

    @staticmethod
    def _extract_video_url(html: str) -> Optional[str]:
        match = _MEDIA_URL_RE.search(html)
        return match.group(1) if match else None

    async def _fetch_text(
        self, session: aiohttp.ClientSession, url: str
    ) -> Optional[str]:
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status != 200:
                    return None
                return await response.text()
        except Exception:
            return None
