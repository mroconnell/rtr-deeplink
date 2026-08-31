import logging
import re
from datetime import datetime
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder, CalendarCandidate, CalendarPageError
from .models import ResolvedMeeting, TranscriptSegment
from .youtube import YouTubeAssetFinder
from ..utils import jurisdiction_enrich

logger = logging.getLogger("rtr_deeplink.tampa")

# Tampa, FL City Council's own "CTTV" closed-captioning transcript webapp
# (apps.tampagov.net/cttv_cc_webapp/) -- WO-73, 2026-08-30. BACKLOG.md's
# original framing ("transcripts posted separately at apps.tampagov.net,
# need matching back to the meeting") undersold this: confirmed live
# 2026-08-30 that every individual transcript detail page
# (Agenda.aspx?pkey={N}) *already* embeds its own paired YouTube video
# directly in a sidebar "Meeting Video" card --
#   <div id="ag-video-embed"><iframe src="https://www.youtube.com/embed/{id}"
#     title="{...}" ...></iframe></div>
#   <div id="ag-video-meta">...<a href="https://www.youtube.com/watch?v={id}">
#     Watch on YouTube</a></div>
# -- so no cross-referencing against the paginated Default.aspx listing
# grid is needed at all. (That listing grid *does* independently confirm
# the pairing -- each row there carries both the transcript link and a
# plain, un-JS'd `<a href="https://www.youtube.com/watch?v=...">` -- but
# it's a 2,611-row ASP.NET RadGrid with server-side-postback-only
# pagination (`__doPostBack`, Telerik page-number-recycled control ids per
# 10-page pager window -- confirmed live it CAN be walked with plain
# aiohttp POSTs, no headless browser needed, but it's real per-page-group
# round-trip work for no benefit once the detail page's own video card was
# found). Confirmed across 3 real, differently-dated pkeys before writing
# this adapter: 2382 (4/5/2022, oldest-shape header, 24h "HH:MM:SS"
# timestamp ids), 2698 (8/20/2026, newest, 12h "H:MM:SSAM/PM" timestamp
# ids -- see `_seconds_of_day()`), 2663 (2/19/2026, a transcript that is
# itself a "Part 2" continuation -- its own video card still carries its
# own real video, confirmed distinct from any neighboring meeting's).
#
# Some pkeys have no video at all (confirmed live, pkey=100: no
# `ag-video-embed` div rendered, `MainContent_pnlVideo` panel empty) --
# older meetings that predate the vendor's own YouTube archive, presumably.
# Treated as a normal "no video found" outcome, same as every other
# adapter in this repo, not a parse failure.
#
# **Transcript quality**: real, per-utterance HH:MM:SS-timestamped closed
# captioning, not auto-generated -- confirmed by reading actual dialogue
# (roll calls, real council-member names, procedural language) on all 3
# samples above. This is genuinely a better source than YouTube's own
# auto-captions would be for the same video (no ASR errors, real speaker
# labels via bold `<b>NAME</b>:` prefixes on the ones that have them), so
# `segments` is built from this page directly rather than from whatever
# YouTube's own caption track has -- see `resolve()`'s override of
# `resolved.segments` below.
#
# A row's "▶ Pt 2" video link on the *listing* page (Default.aspx) is
# NOT a second half of the same recording -- confirmed live on pkey=2698
# (8/20/2026 evening session): its own video card's primary embed is its
# own meeting's video, and a *separate*, clearly-labeled secondary panel
# (`MainContent_pnlVideoPt2` / `ag-video-embed-pt2`) links to a
# *different*, same-day meeting's video (that day's separate CRA meeting,
# transcript #2697, which independently has its own primary video card
# pointing at the identical id). This adapter only ever uses the primary
# `ag-video-embed` video -- the pt2 panel is a same-day cross-reference
# convenience the source site adds, not part of this meeting's own
# recording, and is deliberately ignored here.
#
# **Video delegation**: like PrimeGov (see primegov.py) and Chicago's City
# Clerk ELMS (see chicago_elms.py), this hands the extracted video id to
# `YouTubeAssetFinder.resolve_video_id()` -- the shared "wrapper platform"
# pattern in this repo -- with the *original* apps.tampagov.net URL kept
# as `source_url` (not the youtube.com URL, same choice PrimeGov makes).
# Unlike PrimeGov (whose own page has no reliable date/transcript of its
# own), Tampa's own page IS the better source for title/date/transcript,
# so those are always overridden with this page's own extraction
# afterward -- same override-after-delegate shape as primegov.py, and
# `resolved.platform` is reset back to "tampa" afterward the way
# chicago_elms.py does (not left as "youtube"), since this page's own
# identity should survive on a real pushed row.
_PKEY_RE = re.compile(r"[?&]pkey=(\d+)", re.IGNORECASE)

_MONTHS = {
    name: i + 1
    for i, name in enumerate(
        [
            "JANUARY",
            "FEBRUARY",
            "MARCH",
            "APRIL",
            "MAY",
            "JUNE",
            "JULY",
            "AUGUST",
            "SEPTEMBER",
            "OCTOBER",
            "NOVEMBER",
            "DECEMBER",
        ]
    )
}
# Real confirmed shape: "TUESDAY, APRIL 5, 2022" / "THURSDAY, AUGUST 20,
# 2026, 5:01 P.M." -- the weekday+comma is always present, a trailing time
# is not (ignored here; the AM/PM session time isn't needed for the date
# itself). Matched against the transcript's own header text, not the
# video card's "Published:" date, since the header is this page's own
# stated meeting date and the video's publish date can lag by a day (the
# same real gap this repo's youtube.py already documents for
# upload_date -- see that module's own comment on release_date vs.
# upload_date).
_HEADER_DATE_RE = re.compile(
    r"\b(?:MONDAY|TUESDAY|WEDNESDAY|THURSDAY|FRIDAY|SATURDAY|SUNDAY),?\s+"
    r"(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|"
    r"NOVEMBER|DECEMBER)\s+(\d{1,2}),\s*(\d{4})",
    re.IGNORECASE,
)
# "Published: April 5, 2022" -- the video card's own fallback date,
# confirmed real on every sample checked. Used only when the transcript's
# own header date (above) didn't parse.
_PUBLISHED_DATE_RE = re.compile(
    r"Published:\s*(January|February|March|April|May|June|July|August|"
    r"September|October|November|December)\s+(\d{1,2}),\s*(\d{4})",
    re.IGNORECASE,
)
# Each real utterance marker -- confirmed two distinct real timestamp id
# shapes across the 3 samples above: 24-hour zero-padded with no AM/PM
# suffix (id="t090416", displayed "09:04:16  >>") and 12-hour with an
# AM/PM suffix (id="t50414PM", displayed "5:04:14PM   >>"). Matched
# against the displayed `<b>...</b>` text, not the id attribute, since the
# id's own digit-run length is ambiguous on its own (a bare "50414" could
# be a 5-digit 12-hour timestamp or -- if it were 6 digits -- read as
# 24-hour; the *displayed* text always carries the disambiguating colons
# and, when present, the AM/PM suffix).
_TS_ANCHOR_RE = re.compile(
    r'<a class="ts-link"[^>]*>.*?<b>\s*(\d{1,2}):(\d{2}):(\d{2})\s*(AM|PM)?[^<]*</b>.*?</a>',
    re.IGNORECASE | re.DOTALL,
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
# The disclaimer boilerplate that appears BOTH before the first real
# timestamp (harmless, never captured as segment text since segment
# extraction only starts at the first match) AND after the last one
# (confirmed live, pkey=2382 -- glues onto the final real segment's text
# otherwise). Stripped from every segment defensively rather than only
# the last one, since a legitimate utterance would never contain this
# exact phrase.
_DISCLAIMER_CUT_RE = re.compile(r"\bDISCLAIMER\s*:.*$", re.IGNORECASE | re.DOTALL)

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
)


class TampaAssetFinder(AssetFinder):
    """Tampa, FL City Council's own real-time-captioning transcript webapp
    (apps.tampagov.net/cttv_cc_webapp/). See the module docstring above
    for the real page structure this was built against.
    """

    platform_name = "tampa"

    def __init__(self):
        self.headers = {"User-Agent": _UA}

    async def resolve(self, url: str) -> ResolvedMeeting:
        pkey = self._extract_pkey(url)
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        base_path = parsed.path.rsplit("/", 1)[0] or "/cttv_cc_webapp"

        if not pkey:
            # A bare Default.aspx (or any apps.tampagov.net URL with no
            # ?pkey=) is the 2,611-row listing page, not one meeting --
            # same "hand back real candidates" shape as Legistar's
            # Calendar.aspx (see base.py's CalendarPageError). Only the
            # first page (the 50 most recent meetings) is offered, same
            # as every other calendar-style adapter here -- a visitor
            # pasting the bare listing page almost always wants something
            # recent, not a picker across all 2,611 rows.
            listing_url = f"{origin}{base_path}/Default.aspx"
            async with aiohttp.ClientSession(headers=self.headers) as session:
                html = await self._fetch_text(session, listing_url)
            candidates = (
                self._extract_candidates(html, origin, base_path) if html else []
            )
            raise CalendarPageError(
                "Tampa City Council transcript listing page -- pick a specific meeting.",
                candidates=candidates,
                jurisdiction_hint=jurisdiction_enrich.known_jurisdiction_display(
                    parsed.netloc
                ),
            )

        detail_url = f"{origin}{base_path}/Agenda.aspx?pkey={pkey}"
        async with aiohttp.ClientSession(headers=self.headers) as session:
            html = await self._fetch_text(session, detail_url)

        if not html:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "Could not reach Tampa's transcript page for this meeting."
                ],
            )

        header_date = self._extract_header_date(html)
        published_date = self._extract_published_date(html)
        date = header_date or published_date

        video_id, video_title = self._extract_primary_video(html)
        segments, transcript_warnings = self._extract_transcript(html)
        jurisdiction = jurisdiction_enrich.known_jurisdiction_display(parsed.netloc)

        if not video_id:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                title=video_title or "Tampa City Council Meeting",
                date=date,
                jurisdiction=jurisdiction,
                segments=segments,
                video_warnings=["No video found for this Tampa City Council meeting."],
                transcript_warnings=transcript_warnings,
            )

        resolved = await YouTubeAssetFinder.resolve_video_id(video_id, source_url=url)
        # Same override-after-delegate shape as primegov.py: this page's
        # own real title/date beat YouTube's (own metadata is often just
        # generic "Tampa City Council PM - 08/20/26" boilerplate, but it's
        # still a real, confirmed-live value -- prefer it as a backfill
        # only when yt-dlp's own extraction came back empty).
        resolved.title = video_title or resolved.title or "Tampa City Council Meeting"
        if date:
            resolved.date = date
        resolved.jurisdiction = jurisdiction or resolved.jurisdiction
        # This page's own real-time captioning is a materially better
        # transcript than YouTube's auto-captions (see module docstring)
        # -- always used when found, regardless of what YouTube's own
        # track had.
        if segments:
            resolved.segments = segments
            resolved.transcript_warnings = transcript_warnings
        elif not resolved.segments:
            resolved.transcript_warnings = (
                transcript_warnings or resolved.transcript_warnings
            )
        # Same reset-after-delegate as chicago_elms.py -- this page's own
        # identity should survive on a real pushed row, not read
        # "youtube" the way PrimeGov's delegation deliberately leaves it.
        resolved.platform = self.platform_name
        return resolved

    @staticmethod
    def _extract_pkey(url: str) -> Optional[str]:
        match = _PKEY_RE.search(url)
        if match:
            return match.group(1)
        value = parse_qs(urlparse(url).query).get("pkey", [None])[0]
        return value if value and value.isdigit() else None

    @staticmethod
    def _extract_candidates(
        html: str, origin: str, base_path: str
    ) -> List[CalendarCandidate]:
        soup = BeautifulSoup(html, "html.parser")
        candidates: List[CalendarCandidate] = []
        for row in soup.find_all("tr", class_=("rgRow", "rgAltRow")):
            cells = row.find_all("td")
            if len(cells) < 3:
                continue
            link = cells[0].find("a", href=True)
            if not link or "pkey=" not in link["href"]:
                continue
            date_text = cells[1].get_text(strip=True)
            date = TampaAssetFinder._parse_slash_date(date_text)
            meeting_type = cells[2].get_text(strip=True)
            # Real confirmed shape: this cell's own text is already a full
            # meeting name ("Tampa City Council Evening Meeting", "Tampa
            # City Council CRA Meeting") -- not a bare type/tag that needs
            # a prefix, unlike most other adapters' listing rows.
            title = meeting_type or "Tampa City Council Meeting"
            candidates.append(
                CalendarCandidate(
                    title=title,
                    date=date or date_text,
                    url=f"{origin}{base_path}/{link['href']}",
                )
            )
        return candidates

    @staticmethod
    def _parse_slash_date(text: str) -> Optional[str]:
        # Real confirmed shape: "8/20/2026" (no leading zeros).
        try:
            return datetime.strptime(text.strip(), "%m/%d/%Y").date().isoformat()
        except ValueError:
            return None

    @staticmethod
    def _extract_header_date(html: str) -> Optional[str]:
        transcript_start = html.find('id="MainContent_transcript"')
        # Scoped to (roughly) the first 2KB of the transcript body -- the
        # real header always sits at the very top, before any real
        # utterance; searching the whole (often 500KB+) transcript risks
        # a false match inside quoted dialogue later on.
        window = (
            html[transcript_start : transcript_start + 2000]
            if transcript_start != -1
            else html[:2000]
        )
        match = _HEADER_DATE_RE.search(window)
        if not match:
            return None
        month = _MONTHS.get(match.group(1).upper())
        if not month:
            return None
        day, year = int(match.group(2)), match.group(3)
        return f"{year}-{month:02d}-{day:02d}"

    @staticmethod
    def _extract_published_date(html: str) -> Optional[str]:
        match = _PUBLISHED_DATE_RE.search(html)
        if not match:
            return None
        month = _MONTHS.get(match.group(1).upper())
        if not month:
            return None
        day, year = int(match.group(2)), match.group(3)
        return f"{year}-{month:02d}-{day:02d}"

    @staticmethod
    def _extract_primary_video(html: str) -> Tuple[Optional[str], Optional[str]]:
        """The PRIMARY meeting's own video only -- deliberately excludes
        the secondary same-day "Pt 2" cross-reference panel
        (`MainContent_pnlVideoPt2`), which links to a *different*
        meeting's video (see module docstring). Scoped by cutting the
        search window off at that panel's own id when present.
        """
        card_start = html.find('id="ag-video-card-body"')
        if card_start == -1:
            return None, None
        pt2_start = html.find('id="MainContent_pnlVideoPt2"', card_start)
        window = html[card_start : pt2_start if pt2_start != -1 else card_start + 3000]
        iframe_match = re.search(
            r'<iframe src="https://www\.youtube\.com/embed/([A-Za-z0-9_-]{11})"'
            r'(?:\s+title="([^"]*)")?',
            window,
        )
        if iframe_match:
            return iframe_match.group(1), (iframe_match.group(2) or None)
        watch_match = re.search(
            r'href="https://www\.youtube\.com/watch\?v=([A-Za-z0-9_-]{11})"', window
        )
        if watch_match:
            return watch_match.group(1), None
        return None, None

    @staticmethod
    def _seconds_of_day(
        hour: int, minute: int, second: int, ampm: Optional[str]
    ) -> int:
        if ampm:
            hour = hour % 12
            if ampm.upper() == "PM":
                hour += 12
        return hour * 3600 + minute * 60 + second

    @staticmethod
    def _extract_transcript(
        html: str,
    ) -> Tuple[List[TranscriptSegment], List[str]]:
        transcript_start = html.find('id="MainContent_transcript"')
        if transcript_start == -1:
            return [], ["No transcript found for this Tampa City Council meeting."]
        transcript_end = html.find("</div>", transcript_start)
        # The transcript div's own content is one long run of <br />-
        # separated lines with no nested divs, so the first </div> after
        # the opening tag is a safe, confirmed-live boundary across all 3
        # real samples checked -- if that assumption ever breaks, this
        # just falls back to scanning further, not to garbage.
        body = html[transcript_start : transcript_end if transcript_end != -1 else None]

        matches = list(_TS_ANCHOR_RE.finditer(body))
        if not matches:
            return [], [
                "No timestamped transcript found for this Tampa City Council meeting."
            ]

        raw_entries: List[Tuple[int, str]] = []
        for i, match in enumerate(matches):
            seconds = TampaAssetFinder._seconds_of_day(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
                match.group(4),
            )
            text_start = match.end()
            text_end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
            raw_text = body[text_start:text_end]
            raw_text = _DISCLAIMER_CUT_RE.sub("", raw_text)
            text = _TAG_RE.sub(" ", raw_text)
            text = (
                text.replace("&amp;", "&")
                .replace("&nbsp;", " ")
                .replace("&#39;", "'")
                .replace("&quot;", '"')
            )
            text = _WS_RE.sub(" ", text).strip()
            if text:
                raw_entries.append((seconds, text))

        if not raw_entries:
            return [], [
                "No timestamped transcript found for this Tampa City Council meeting."
            ]

        t0 = raw_entries[0][0]
        segments: List[TranscriptSegment] = []
        for i, (seconds, text) in enumerate(raw_entries):
            start = max(0, seconds - t0)
            end = (
                max(0, raw_entries[i + 1][0] - t0)
                if i + 1 < len(raw_entries)
                else start
            )
            segments.append(
                TranscriptSegment(
                    start=float(start), end=float(max(end, start)), text=text
                )
            )
        return segments, []

    @staticmethod
    async def _fetch_text(session: aiohttp.ClientSession, url: str) -> Optional[str]:
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "Tampa fetch got HTTP %s for %s", response.status, url
                    )
                    return None
                return await response.text()
        except Exception:
            logger.warning("Tampa fetch failed for %s", url, exc_info=True)
            return None
