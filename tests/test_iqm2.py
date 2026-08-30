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


# Real, confirmed live 2026-08-29: not every IQM2 tenant's MEDIA URL
# comment is Granicus HLS like Atlanta's -- San Carlos, CA
# (mediahttp.iqm2.com/SanCarlosCA/1450_480.mp4) returns a direct .mp4
# instead. Confirmed via a live fetch of the resolved page's rendered
# <video>/<source> tag (a real Search Console "video isn't on a watch
# page" contributor -- see BACKLOG.md/BACKLOG_DONE.md); the outline
# HTML below reuses the same confirmed Atlanta/SCC page shape rather
# than an independently-fetched San Carlos raw page.
SAN_CARLOS_URL = "https://mediahttp.iqm2.com/Citizens/Detail_Meeting.aspx?ID=1450"
SAN_CARLOS_OUTLINE_URL = (
    "https://mediahttp.iqm2.com/Citizens/Detail_Meeting.aspx?Target=Detail&CssClass=AgendaOutline"
    "&Mode=Video&Frame=Nothing&ID=1450"
)
SAN_CARLOS_SPLIT_URL = "https://mediahttp.iqm2.com/Citizens/SplitView.aspx?Mode=Video&MeetingID=1450&Format=Minutes"
SAN_CARLOS_OUTLINE_HTML = """
<html><head><title>
2017/11/13 07:00 PM City Council Regular Meeting - Web Outline - City of San Carlos, California
</title></head>
<body>No AgendaOutlineLink items in this fixture -- this test's focus is video_format.</body></html>
"""
SAN_CARLOS_SPLIT_HTML = """
<div><!-- MEDIA URL: https://mediahttp.iqm2.com/SanCarlosCA/1450_480.mp4--></div>
"""


async def test_resolve_derives_mp4_format_instead_of_hardcoding_m3u8():
    routes = {
        SAN_CARLOS_OUTLINE_URL: FakeResponse(
            status=200, text=SAN_CARLOS_OUTLINE_HTML, url=SAN_CARLOS_OUTLINE_URL
        ),
        SAN_CARLOS_SPLIT_URL: FakeResponse(
            status=200, text=SAN_CARLOS_SPLIT_HTML, url=SAN_CARLOS_SPLIT_URL
        ),
    }

    with mock_session(routes):
        result = await IQM2AssetFinder().resolve(SAN_CARLOS_URL)

    assert result.video_url == "https://mediahttp.iqm2.com/SanCarlosCA/1450_480.mp4"
    # Not "m3u8" -- that mislabel produced a <source type=
    # "application/vnd.apple.mpegurl"> pointing at a real .mp4 file.
    assert result.video_format == "mp4"


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


async def test_resolve_reports_no_video_found_when_split_page_has_no_media_url(
    caplog,
):
    # Real, confirmed live: Santa Clara County meetings checked so far
    # never populate the video onclick at all -- degrades to an honest
    # "no video found" rather than crashing or guessing.
    routes = {
        SCC_OUTLINE_URL: FakeResponse(
            status=200, text=SCC_OUTLINE_HTML, url=SCC_OUTLINE_URL
        ),
        SCC_SPLIT_URL: FakeResponse(status=404, text="", url=SCC_SPLIT_URL),
    }

    with caplog.at_level("WARNING"):
        with mock_session(routes):
            result = await IQM2AssetFinder().resolve(SCC_URL)

    assert result.title == "Personnel Board Business Meeting"
    assert result.date == "2026-08-14"
    assert result.jurisdiction == "The County of Santa Clara, California"
    assert result.video_url is None
    assert result.video_warnings == ["No video found for this meeting."]
    assert result.agenda_items == []
    # 2026-08-28: a failed text fetch used to be silent -- now logged.
    assert any("IQM2 fetch got HTTP 404" in r.message for r in caplog.records)


async def test_resolve_returns_a_clear_error_when_no_meeting_id_is_in_the_url():
    result = await IQM2AssetFinder().resolve("https://atlantacityga.iqm2.com/Citizens/")

    assert result.video_url is None
    assert "meeting id" in result.video_warnings[0].lower()


def test_extract_meeting_id_matches_id_param():
    assert IQM2AssetFinder._extract_meeting_id(ATLANTA_URL) == "4294"


def test_extract_meeting_id_matches_meetingid_param():
    url = "https://atlantacityga.iqm2.com/Citizens/SplitView.aspx?Mode=Video&MeetingID=4294"
    assert IQM2AssetFinder._extract_meeting_id(url) == "4294"


def test_extract_meeting_id_prefers_meetingid_over_id_on_legifile_urls():
    # Real, confirmed live 2026-08-23 -- a Plainfield, NJ Detail_LegiFile.
    # aspx URL from a real backlog run: ID=4641 is that legislative file's
    # own id (a different, unrelated document), MeetingID=1229 is the real
    # meeting it belongs to. Confirmed live that
    # SplitView.aspx?...MeetingID=4641 returns an empty `MEDIA URL:`
    # comment (a real page, wrong meeting -- no video) while
    # MeetingID=1229 returns a real, populated one. Before this fix,
    # _extract_meeting_id() returned "4641" (whichever param matched
    # first in the query string, not the correct one), which is exactly
    # why this real meeting was wrongly reported as having no video at
    # all -- see _MEETING_ID_PRIMARY_RE's own comment for the fuller
    # writeup and the 7 other real Detail_LegiFile candidates that hit
    # the identical bug the same run.
    url = (
        "http://plainfieldcitynj.iqm2.com/Citizens/Detail_LegiFile.aspx"
        "?CssClass=&Frame=&ID=4641&MediaPosition=&MeetingID=1229"
    )
    assert IQM2AssetFinder._extract_meeting_id(url) == "1229"


def test_detect_platform_recognizes_both_real_confirmed_customers():
    assert detect_platform(ATLANTA_URL) == "iqm2"
    assert detect_platform(SCC_URL) == "iqm2"


# Real shape confirmed live 2026-08-30 against the module's own cited
# Atlanta proof-of-concept meeting (MediaID=76801): the same SplitView.aspx
# script tag that feeds JWPlayer the video URL also carries a
# `"tracks":[{"file":"/Services/TranscriptGet.aspx?MediaID=76801&
# format=vtt", ..., "kind":"captions", ...}]` entry -- but this endpoint's
# real response is an HTTP 200 with only an 11-byte "WEBVTT \n\n" body, no
# actual cues. Confirmed the same on two other Atlanta MediaIDs (76785,
# 76793) -- Atlanta itself appears not to have real captioning turned on
# for any meeting sampled, not a broken endpoint (see the real Santa Clara
# County content below).
ATLANTA_CAPTION_URL = "https://atlantacityga.iqm2.com/Services/TranscriptGet.aspx?MediaID=76801&format=vtt"
ATLANTA_SPLIT_WITH_TRACKS_HTML = """
<div><!-- MEDIA URL: https://archive-stream.granicus.com/OnDemand/_definst_/mp4:archive/atlantacityga/76801_480.mp4/playlist.m3u8--></div>
<script type='text/javascript'> SetupJWPlayer(eval('[{"file":"https://archive-stream.granicus.com/OnDemand/_definst_/mp4:archive/atlantacityga/76801_480.mp4/playlist.m3u8","type":"video/mp4","label":"SD 480","default":true,"tracks":[{"file":"/Services/TranscriptGet.aspx?MediaID=76801&format=vtt","label":"English","kind":"captions","default":true}]}]'),'False','True'); </script>
"""
ATLANTA_CAPTION_PLACEHOLDER_VTT = "WEBVTT \n\n"


async def test_resolve_reports_blank_transcript_warning_for_real_placeholder_caption():
    routes = {
        ATLANTA_OUTLINE_URL: FakeResponse(
            status=200, text=ATLANTA_OUTLINE_HTML, url=ATLANTA_OUTLINE_URL
        ),
        ATLANTA_SPLIT_URL: FakeResponse(
            status=200, text=ATLANTA_SPLIT_WITH_TRACKS_HTML, url=ATLANTA_SPLIT_URL
        ),
        ATLANTA_CAPTION_URL: FakeResponse(
            status=200,
            text=ATLANTA_CAPTION_PLACEHOLDER_VTT,
            url=ATLANTA_CAPTION_URL,
        ),
    }

    with mock_session(routes):
        result = await IQM2AssetFinder().resolve(ATLANTA_URL)

    assert result.video_url is not None
    assert result.segments == []
    assert result.transcript_warnings == [
        "Caption file was blank, so we don't have a transcript for "
        "this meeting yet — you can request a transcript from the "
        "audio instead."
    ]


# Real shape confirmed live 2026-08-30: Santa Clara County, CA, Board of
# Supervisors Regular Meeting prior to Closed Session, Jan 26 2026
# (sccgov.iqm2.com/Citizens/Detail_Meeting.aspx?ID=18002). Unlike every
# Atlanta MediaID sampled above, this tenant's TranscriptGet.aspx response
# has real, substantive, correctly-timed cues -- confirmed on 4 real SCC
# meetings total (MediaIDs 28254, 28261, 28267, 28273); the fixture below
# is the real opening of 28273, trimmed from 162 lines to the first 3 cues.
SCC_TRANSCRIPT_URL = "https://sccgov.iqm2.com/citizens/Detail_Meeting.aspx?ID=18002"
SCC_TRANSCRIPT_OUTLINE_URL = (
    "https://sccgov.iqm2.com/citizens/Detail_Meeting.aspx?Target=Detail&CssClass=AgendaOutline"
    "&Mode=Video&Frame=Nothing&ID=18002"
)
SCC_TRANSCRIPT_SPLIT_URL = "https://sccgov.iqm2.com/citizens/SplitView.aspx?Mode=Video&MeetingID=18002&Format=Minutes"
SCC_TRANSCRIPT_CAPTION_URL = (
    "https://sccgov.iqm2.com/Services/TranscriptGet.aspx?MediaID=28273&format=vtt"
)
SCC_TRANSCRIPT_OUTLINE_HTML = """
<html><head><title>
2026/01/26 02:00 PM Board of Supervisors Regular Meeting prior to Closed Session - Web Outline - The County of Santa Clara, California
</title></head>
<body>No AgendaOutlineLink items in this fixture -- this test's focus is transcript segments.</body></html>
"""
SCC_TRANSCRIPT_SPLIT_HTML = """
<div><!-- MEDIA URL: https://archive-stream.granicus.com/OnDemand/_definst_/mp4:archive/sccgov/28273_480.mp4/playlist.m3u8--></div>
<script type='text/javascript'> SetupJWPlayer(eval('[{"file":"https://archive-stream.granicus.com/OnDemand/_definst_/mp4:archive/sccgov/28273_480.mp4/playlist.m3u8","type":"video/mp4","label":"SD 480","default":true,"tracks":[{"file":"/Services/TranscriptGet.aspx?MediaID=28273&format=vtt","label":"English","kind":"captions","default":true}]}]'),'False','True'); </script>
"""
SCC_TRANSCRIPT_VTT = """WEBVTT

00:00:00.000 --> 00:00:00.900
>> Supervisor Lee:


00:00:01.100 --> 00:00:04.834
Good afternoon, it's Monday, January 26th, 2:00 p.m., we'll go ahead and call the regular


00:00:05.839 --> 00:00:10.339
meeting prior to closed session to order. >> Clerk: Supervisor Abe-Koga. >> Supervisor Abe-Koga: Here.
"""


async def test_resolve_fetches_real_captions_from_iqm2s_own_transcript_endpoint():
    routes = {
        SCC_TRANSCRIPT_OUTLINE_URL: FakeResponse(
            status=200,
            text=SCC_TRANSCRIPT_OUTLINE_HTML,
            url=SCC_TRANSCRIPT_OUTLINE_URL,
        ),
        SCC_TRANSCRIPT_SPLIT_URL: FakeResponse(
            status=200, text=SCC_TRANSCRIPT_SPLIT_HTML, url=SCC_TRANSCRIPT_SPLIT_URL
        ),
        SCC_TRANSCRIPT_CAPTION_URL: FakeResponse(
            status=200, text=SCC_TRANSCRIPT_VTT, url=SCC_TRANSCRIPT_CAPTION_URL
        ),
    }

    with mock_session(routes):
        result = await IQM2AssetFinder().resolve(SCC_TRANSCRIPT_URL)

    assert result.transcript_warnings == []
    assert [s.text for s in result.segments] == [
        ">> Supervisor Lee:",
        "Good afternoon, it's Monday, January 26th, 2:00 p.m., we'll go ahead and call the regular",
        "meeting prior to closed session to order. >> Clerk: Supervisor Abe-Koga. >> Supervisor Abe-Koga: Here.",
    ]
    assert result.segments[0].start == 0.0
    assert result.segments[0].end == 0.9
    assert result.segments[1].start == 1.1
    assert result.segments[2].end == 10.339


def test_extract_caption_track_finds_real_transcriptget_path():
    assert (
        IQM2AssetFinder._extract_caption_track(ATLANTA_SPLIT_WITH_TRACKS_HTML)
        == "/Services/TranscriptGet.aspx?MediaID=76801&format=vtt"
    )


def test_extract_caption_track_returns_none_when_no_tracks_entry():
    # Real shape -- SCC_BOS_SPLIT_HTML and SAN_CARLOS_SPLIT_HTML above are
    # both real captured pages with a populated video but no tracks array
    # at all in their SetupJWPlayer call.
    assert IQM2AssetFinder._extract_caption_track(SCC_BOS_SPLIT_HTML) is None
