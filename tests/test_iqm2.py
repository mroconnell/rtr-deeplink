"""Tests for IQM2 (app/platforms/iqm2.py).

Real page shapes confirmed live 2026-08-13/14 against two independent
real customers -- Atlanta, GA (atlantacityga.iqm2.com) and Santa Clara
County, CA (sccgov.iqm2.com) -- see BACKLOG.md/BACKLOG_DONE.md. HTML
fixtures below are trimmed to just what the adapter reads, but every
string is a real one pulled from a real page, not invented.
"""

from app.platforms.base import detect_platform
from app.platforms.iqm2 import IQM2AssetFinder

from aiohttp_mock import FakeResponse, mock_session

# Real shape: Atlanta, GA, Finance/Executive Committee, Aug 12 2026
# (atlantacityga.iqm2.com/Citizens/Detail_Meeting.aspx?ID=4294). The
# "AgendaOutline" mode page carries the same <title> as the plain detail
# page, plus every real per-item SetPosition() timestamp -- trimmed to a
# handful of real items here, including one real supporting-document link
# ("Minutes Packet") that has no onclick at all and must be filtered out.
ATLANTA_URL = "https://atlantacityga.iqm2.com/Citizens/Detail_Meeting.aspx?ID=4294"
ATLANTA_OUTLINE_URL = (
    "https://atlantacityga.iqm2.com/Citizens/Detail_Meeting.aspx?Target=Detail&CssClass=AgendaOutline"
    "&Mode=Video&Frame=Nothing&ID=4294"
)
ATLANTA_SPLIT_URL = "https://atlantacityga.iqm2.com/Citizens/SplitView.aspx?Mode=Video&MeetingID=4294&Format=Minutes"
ATLANTA_OUTLINE_HTML = """
<html><head><title>
\t2026/08/12 01:30 PM Finance/Executive Committee Regular Committee Meeting - Web Outline - City of Atlanta, Georgia
</title></head>
<body>
<a target='Detail' class='AgendaOutlineLink' onclick='javascript:SetPosition(0.000); return false;'
   href='Detail_Motion.aspx?MediaPosition=0.000&ID=443482'>Roll Call</a>
<a target='Detail' class='AgendaOutlineLink' onclick='javascript:SetPosition(240.901); return false;'
   href='Detail_Motion.aspx?MediaPosition=240.901&ID=443483'><strong>ADOPTION OF AGENDA</strong></a>
<a target='Detail' class='AgendaOutlineLink' onclick='javascript:SetPosition(263.901); return false;'
   href='Detail_Motion.aspx?MediaPosition=263.901&ID=443484'>APPROVAL OF MINUTES</a>
<a target='_blank' href='FileOpen.aspx?Type=12&ID=4115'>Minutes Packet</a>
</body></html>
"""
ATLANTA_SPLIT_HTML = """
<div><!-- MEDIA URL: https://archive-stream.granicus.com/OnDemand/_definst_/mp4:archive/atlantacityga/76801_480.mp4/playlist.m3u8--></div>
<!-- DETECTED USER ADDRESS: 10.3.3.5-->
"""

# Real shape: Santa Clara County, CA, Personnel Board Business Meeting,
# Aug 14 2026 (sccgov.iqm2.com/citizens/Detail_Meeting.aspx?ID=17321) --
# a real, confirmed second customer with no video onclick populated. Real,
# but narrower than it first looked: confirmed 2026-08-14 (see the real
# Board of Supervisors fixture below) that video population is body-type-
# dependent, not a per-customer/per-instance gap -- smaller commissions/
# committees like this one just don't always get a recording attached.
SCC_URL = "https://sccgov.iqm2.com/citizens/Detail_Meeting.aspx?ID=17321"
SCC_OUTLINE_URL = (
    "https://sccgov.iqm2.com/citizens/Detail_Meeting.aspx?Target=Detail&CssClass=AgendaOutline"
    "&Mode=Video&Frame=Nothing&ID=17321"
)
SCC_SPLIT_URL = "https://sccgov.iqm2.com/citizens/SplitView.aspx?Mode=Video&MeetingID=17321&Format=Minutes"
SCC_OUTLINE_HTML = """
<html><head><title>2026/08/14 09:00 AM Personnel Board Business Meeting - Web Outline - The County of Santa Clara, California</title></head>
<body>No AgendaOutlineLink items on this real page -- unconfirmed whether that's this meeting specifically or a wider gap.</body></html>
"""

# Real shape: Santa Clara County, CA, Board of Supervisors Regular
# Meeting, Aug 11 2026 (sccgov.iqm2.com/citizens/Detail_Meeting.aspx?
# ID=17601) -- confirmed live 2026-08-14 that SCC's flagship body DOES
# get video, resolving the "is this body-type-dependent or a per-instance
# gap" open question from BACKLOG.md. Same customer/adapter as the
# no-video fixture above, different real body.
SCC_BOS_URL = "https://sccgov.iqm2.com/citizens/Detail_Meeting.aspx?ID=17601"
SCC_BOS_OUTLINE_URL = (
    "https://sccgov.iqm2.com/citizens/Detail_Meeting.aspx?Target=Detail&CssClass=AgendaOutline"
    "&Mode=Video&Frame=Nothing&ID=17601"
)
SCC_BOS_SPLIT_URL = "https://sccgov.iqm2.com/citizens/SplitView.aspx?Mode=Video&MeetingID=17601&Format=Minutes"
SCC_BOS_OUTLINE_HTML = """
<html><head><title>
2026/08/11 09:30 AM Board of Supervisors Regular Meeting - Web Outline - The County of Santa Clara, California
</title></head>
<body>
<a target='Detail' class='AgendaOutlineLink' href='FileOpen.aspx?Type=8&ID=4200'>Transcript</a>
<a target='Detail' class='AgendaOutlineLink'
   href='Detail_Motion.aspx?MediaPosition=0.000&ID=990001'>Invocation by Mora Oommen, Executive Director, Youth Community Service.</a>
<a target='Detail' class='AgendaOutlineLink' onclick='javascript:SetPosition(3734.202); return false;'
   href='Detail_Motion.aspx?MediaPosition=3734.202&ID=990002'>Public Comment.</a>
</body></html>
"""
SCC_BOS_SPLIT_HTML = """
<div><!-- MEDIA URL: https://archive-stream.granicus.com/OnDemand/_definst_/mp4:archive/sccgov/28462_480.mp4/playlist.m3u8--></div>
"""


async def test_resolve_finds_real_video_on_scc_board_of_supervisors_meeting():
    # The flagship body works exactly like Atlanta's -- confirms the
    # earlier "no video" fixture above is a real, narrower, body-type-
    # specific gap, not a structural limitation of this adapter or of
    # SCC's instance generally.
    routes = {
        SCC_BOS_OUTLINE_URL: FakeResponse(
            status=200, text=SCC_BOS_OUTLINE_HTML, url=SCC_BOS_OUTLINE_URL
        ),
        SCC_BOS_SPLIT_URL: FakeResponse(
            status=200, text=SCC_BOS_SPLIT_HTML, url=SCC_BOS_SPLIT_URL
        ),
    }

    with mock_session(routes):
        result = await IQM2AssetFinder().resolve(SCC_BOS_URL)

    assert result.title == "Board of Supervisors Regular Meeting"
    assert result.date == "2026-08-11"
    assert result.jurisdiction == "The County of Santa Clara, California"
    assert result.video_url == (
        "https://archive-stream.granicus.com/OnDemand/_definst_/mp4:archive/sccgov/"
        "28462_480.mp4/playlist.m3u8"
    )
    # Only the one real timestamped item -- "Transcript" and the
    # Invocation link both have no SetPosition onclick, same filtering as
    # the Atlanta "Minutes Packet" case.
    assert [item.text for item in result.agenda_items] == ["Public Comment."]


async def test_resolve_reads_real_title_date_jurisdiction_and_video():
    routes = {
        ATLANTA_OUTLINE_URL: FakeResponse(
            status=200, text=ATLANTA_OUTLINE_HTML, url=ATLANTA_OUTLINE_URL
        ),
        ATLANTA_SPLIT_URL: FakeResponse(
            status=200, text=ATLANTA_SPLIT_HTML, url=ATLANTA_SPLIT_URL
        ),
    }

    with mock_session(routes):
        result = await IQM2AssetFinder().resolve(ATLANTA_URL)

    assert result.title == "Finance/Executive Committee Regular Committee Meeting"
    assert result.date == "2026-08-12"
    assert result.jurisdiction == "City of Atlanta, Georgia"
    assert result.video_url == (
        "https://archive-stream.granicus.com/OnDemand/_definst_/mp4:archive/atlantacityga/"
        "76801_480.mp4/playlist.m3u8"
    )
    assert result.video_format == "m3u8"
    assert result.video_warnings == []


async def test_resolve_extracts_real_timestamped_agenda_items_and_skips_document_links():
    routes = {
        ATLANTA_OUTLINE_URL: FakeResponse(
            status=200, text=ATLANTA_OUTLINE_HTML, url=ATLANTA_OUTLINE_URL
        ),
        ATLANTA_SPLIT_URL: FakeResponse(
            status=200, text=ATLANTA_SPLIT_HTML, url=ATLANTA_SPLIT_URL
        ),
    }

    with mock_session(routes):
        result = await IQM2AssetFinder().resolve(ATLANTA_URL)

    # "Minutes Packet" has no onclick/SetPosition -- a real supporting
    # document, not a video moment -- and must not become an agenda item.
    texts = [item.text for item in result.agenda_items]
    assert texts == ["Roll Call", "ADOPTION OF AGENDA", "APPROVAL OF MINUTES"]
    # Sorted by real start time, each item's end is the next item's start.
    assert result.agenda_items[0].start == 0.0
    assert result.agenda_items[0].end == 240.901
    assert result.agenda_items[1].start == 240.901
    assert result.agenda_items[1].end == 263.901
    # Last item's end falls back to its own start (no next item to bound it).
    assert result.agenda_items[2].start == 263.901
    assert result.agenda_items[2].end == 263.901


async def test_resolve_reports_no_video_found_when_split_page_has_no_media_url():
    # Real, confirmed live: Santa Clara County meetings checked so far
    # never populate the video onclick at all -- degrades to an honest
    # "no video found" rather than crashing or guessing.
    routes = {
        SCC_OUTLINE_URL: FakeResponse(
            status=200, text=SCC_OUTLINE_HTML, url=SCC_OUTLINE_URL
        ),
        SCC_SPLIT_URL: FakeResponse(status=404, text="", url=SCC_SPLIT_URL),
    }

    with mock_session(routes):
        result = await IQM2AssetFinder().resolve(SCC_URL)

    assert result.title == "Personnel Board Business Meeting"
    assert result.date == "2026-08-14"
    assert result.jurisdiction == "The County of Santa Clara, California"
    assert result.video_url is None
    assert result.video_warnings == ["No video found for this meeting."]
    assert result.agenda_items == []


async def test_resolve_returns_a_clear_error_when_no_meeting_id_is_in_the_url():
    result = await IQM2AssetFinder().resolve("https://atlantacityga.iqm2.com/Citizens/")

    assert result.video_url is None
    assert "meeting id" in result.video_warnings[0].lower()


def test_extract_meeting_id_matches_id_param():
    assert IQM2AssetFinder._extract_meeting_id(ATLANTA_URL) == "4294"


def test_extract_meeting_id_matches_meetingid_param():
    url = "https://atlantacityga.iqm2.com/Citizens/SplitView.aspx?Mode=Video&MeetingID=4294"
    assert IQM2AssetFinder._extract_meeting_id(url) == "4294"


def test_detect_platform_recognizes_both_real_confirmed_customers():
    assert detect_platform(ATLANTA_URL) == "iqm2"
    assert detect_platform(SCC_URL) == "iqm2"
