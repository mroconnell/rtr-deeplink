"""Tests for Tampa, FL City Council's transcript webapp adapter
(app/platforms/tampa.py), WO-73.

All five fixtures are real, unmodified live captures taken 2026-08-30
from apps.tampagov.net/cttv_cc_webapp/ -- see tampa.py's own module
docstring for the investigation.

- `agenda_pkey_2382.html` -- a real 4/5/2022 special meeting, the oldest-
  shape header and 24-hour "HH:MM:SS" (no AM/PM) timestamp ids
  (`id="t090416"`). 218 real timestamped utterances, real video.
- `agenda_pkey_2698.html` -- a real 8/20/2026 evening meeting, the
  newest-shape header and 12-hour "H:MM:SSAM/PM" timestamp ids
  (`id="t50414PM"`). 713 real timestamped utterances, real video, AND a
  real secondary "Pt 2" panel pointing at a *different* same-day
  meeting's video (transcript #2697's CRA meeting) -- the real case
  `_extract_primary_video()` must not be fooled by.
- `agenda_pkey_2663.html` -- a real transcript that is itself labeled
  "Part 2" of a continuation (2/19/2026's video, "Published: February 19,
  2026") but is filed under a *different* meeting date (3/3/2026, per
  its own transcript header) -- confirmed real, not a fixture artifact.
  Exercises `resolve()` preferring the transcript header's own date over
  the video card's "Published:" date when both are present but disagree.
- `agenda_pkey_100.html` -- a real, very old record with NO timestamp
  markers at all (a bare "Continued.... Part 2 Of 2" fragment) and no
  video card rendered -- the real "nothing to extract" case.
- `default_listing_page1.html` -- the real listing page
  (Default.aspx), page 1 of 53 (2,611 total real transcripts at capture
  time), used for the `CalendarPageError` candidate-list test.

`YouTubeAssetFinder._extract_info` is monkeypatched the same way
tests/test_primegov.py's own suite does it -- this adapter's own
transcript/title/date extraction is what's under test, not yt-dlp.
"""

import pytest

from app.platforms.base import CalendarPageError, detect_platform
from app.platforms.tampa import TampaAssetFinder
from app.platforms.youtube import YouTubeAssetFinder

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

BASE = "https://apps.tampagov.net/cttv_cc_webapp"
DETAIL_2382 = f"{BASE}/Agenda.aspx?pkey=2382"
DETAIL_2698 = f"{BASE}/Agenda.aspx?pkey=2698"
DETAIL_2663 = f"{BASE}/Agenda.aspx?pkey=2663"
DETAIL_100 = f"{BASE}/Agenda.aspx?pkey=100"
LISTING = f"{BASE}/Default.aspx"


def _fake_extract_info(video_id):
    # Deliberately minimal -- this adapter overrides title/date/segments
    # with its own page's own real extraction regardless of what yt-dlp
    # would have returned (see tampa.py's resolve()), so the fake doesn't
    # need to look like a real yt-dlp payload beyond not crashing
    # YouTubeAssetFinder.resolve_video_id()'s own .get() calls.
    return {"title": None, "uploader": None, "upload_date": None}


def test_detect_platform_claims_the_domain():
    assert detect_platform(DETAIL_2382) == "tampa"
    assert detect_platform(LISTING) == "tampa"


async def test_resolve_2382_real_video_and_transcript(monkeypatch):
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    routes = {
        DETAIL_2382: FakeResponse(
            status=200,
            text=load_fixture("tampa", "agenda_pkey_2382.html"),
            url=DETAIL_2382,
        )
    }
    with mock_session(routes):
        result = await TampaAssetFinder().resolve(DETAIL_2382)

    # Own identity survives the YouTube delegation (the chicago_elms
    # pattern), unlike PrimeGov's delegation which leaves "youtube".
    assert result.platform == "tampa"
    assert result.source_url == DETAIL_2382
    assert result.video_url == "https://www.youtube.com/embed/CIEG1h6UWXQ"
    assert result.video_format == "youtube"
    assert result.title == "TCC 4/5/22"
    assert result.date == "2022-04-05"
    assert result.jurisdiction == "City of Tampa, FL"
    assert len(result.segments) == 218
    assert result.segments[0].start == 0.0
    # Real opening line, confirmed live.
    assert "GOOD MORNING" in result.segments[0].text
    assert not result.video_warnings
    assert not result.transcript_warnings


async def test_resolve_2698_twelve_hour_timestamps_and_ignores_pt2_panel(monkeypatch):
    """pkey=2698 is the 12-hour "H:MM:SSAM/PM" timestamp-id shape
    (id="t50414PM"), a structurally different real shape from 2382's
    24-hour ids -- both must parse to the same kind of correct, zero-
    based elapsed-second segments. Also carries a real secondary
    "Pt 2" video panel pointing at a DIFFERENT meeting (transcript
    #2697's CRA meeting, not a second half of this one) -- confirmed via
    _extract_primary_video() returning this meeting's own video id, not
    the pt2 panel's.
    """
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    routes = {
        DETAIL_2698: FakeResponse(
            status=200,
            text=load_fixture("tampa", "agenda_pkey_2698.html"),
            url=DETAIL_2698,
        )
    }
    with mock_session(routes):
        result = await TampaAssetFinder().resolve(DETAIL_2698)

    assert result.platform == "tampa"
    # This meeting's own video -- NOT d-1Eu9rdXRI, the pt2 panel's
    # different (CRA meeting) video id also present on this same page.
    assert result.video_url == "https://www.youtube.com/embed/DJD_5jUOmLc"
    assert result.date == "2026-08-20"
    assert len(result.segments) == 713
    assert result.segments[0].start == 0.0
    assert result.segments[0].end > 0.0
    # Monotonically non-decreasing elapsed offsets -- the 12-hour ->
    # seconds-of-day conversion must not silently wrap or go backwards
    # across the whole real transcript.
    for prev, cur in zip(result.segments, result.segments[1:]):
        assert cur.start >= prev.start


async def test_resolve_2663_prefers_header_date_over_video_published_date(monkeypatch):
    """Real, confirmed-live data quirk: this transcript's own header date
    (3/3/2026) disagrees with its embedded video's "Published: February
    19, 2026" date -- the transcript header is this page's own stated
    meeting date and must win (see tampa.py's `_extract_header_date`
    docstring)."""
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    routes = {
        DETAIL_2663: FakeResponse(
            status=200,
            text=load_fixture("tampa", "agenda_pkey_2663.html"),
            url=DETAIL_2663,
        )
    }
    with mock_session(routes):
        result = await TampaAssetFinder().resolve(DETAIL_2663)

    assert result.date == "2026-03-03"
    assert result.video_url == "https://www.youtube.com/embed/MX841CT2Fhc"
    assert len(result.segments) == 255


async def test_resolve_100_no_video_no_transcript_degrades_honestly():
    """A real, very old record with no video card rendered and no
    timestamp markers at all -- must degrade to real warnings, not a
    crash or fabricated content."""
    routes = {
        DETAIL_100: FakeResponse(
            status=200,
            text=load_fixture("tampa", "agenda_pkey_100.html"),
            url=DETAIL_100,
        )
    }
    with mock_session(routes):
        result = await TampaAssetFinder().resolve(DETAIL_100)

    assert result.platform == "tampa"
    assert result.video_url is None
    assert result.segments == []
    assert result.video_warnings == [
        "No video found for this Tampa City Council meeting."
    ]
    assert result.transcript_warnings == [
        "No timestamped transcript found for this Tampa City Council meeting."
    ]


async def test_resolve_listing_page_raises_calendar_page_error_with_real_candidates():
    routes = {
        LISTING: FakeResponse(
            status=200,
            text=load_fixture("tampa", "default_listing_page1.html"),
            url=LISTING,
        )
    }
    with mock_session(routes):
        with pytest.raises(CalendarPageError) as exc_info:
            await TampaAssetFinder().resolve(LISTING)

    error = exc_info.value
    assert error.jurisdiction_hint == "City of Tampa, FL"
    assert len(error.candidates) == 50
    first = error.candidates[0]
    assert first["url"] == f"{BASE}/Agenda.aspx?pkey=2698"
    assert first["date"] == "2026-08-20"
    assert "Tampa City Council" in first["title"]


def test_extract_transcript_strips_trailing_disclaimer_boilerplate():
    """Real, confirmed-live shape: the DISCLAIMER paragraph appears both
    before the first real timestamp (harmless -- never captured) and
    after the last one (would glue onto the final segment's text without
    the strip tampa.py's `_DISCLAIMER_CUT_RE` applies)."""
    html = load_fixture("tampa", "agenda_pkey_2382.html")
    segments, warnings = TampaAssetFinder._extract_transcript(html)
    assert warnings == []
    assert "DISCLAIMER" not in segments[-1].text.upper()


def test_extract_primary_video_ignores_pt2_panel():
    html = load_fixture("tampa", "agenda_pkey_2698.html")
    video_id, title = TampaAssetFinder._extract_primary_video(html)
    assert video_id == "DJD_5jUOmLc"
    assert title == "Tampa City Council PM - 08/20/26"
