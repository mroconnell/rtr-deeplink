"""Tests for Utah's Public Notice Website (app/platforms/utah_pmn.py).

Fixture HTML below is trimmed real page structure, not a fabricated
shape -- confirmed live 2026-09-08 against two real notices: a real
Alpine, UT City Council meeting linking a YouTube recording
(`utah.gov/pmn/sitemap/notice/1103751.html`) and a real Grand County, UT
Planning Commission meeting whose media is a bare `.m4a` file attached
directly on utah.gov (`utah.gov/pmn/sitemap/notice/1100143.html`, found
via the full pilot run -- see ENUMERATION_METHODS.md §105). Only these
two real customers checked so far; the NO_MEDIA fixture is the Alpine
page with its Audio File Address section and media attachment removed,
same "modified real page" pattern this repo's other adapter tests
already use for the negative case (see test_clerkbase.py's
CONTENT_HTML_NO_VIDEO).
"""

import pytest

from app.platforms.base import detect_platform, register
from app.platforms.utah_pmn import UtahPMNAssetFinder
from app.platforms.youtube import YouTubeAssetFinder

from aiohttp_mock import FakeResponse, mock_session


@pytest.fixture(autouse=True)
def _register_delegates():
    # This adapter's delegation branch goes through the real
    # detect_platform()/get_finder() registry (it accepts any known
    # platform, not just YouTube) -- same pattern test_municode_meetings.py
    # already established for the same reason.
    register(YouTubeAssetFinder())


ALPINE_URL = "https://www.utah.gov/pmn/sitemap/notice/1103751.html"
GRAND_COUNTY_URL = "https://www.utah.gov/pmn/sitemap/notice/1100143.html"
REAL_VIDEO_ID = "svq4oCHX0BA"

ALPINE_HTML = """
<html><body>
<h3>General Information</h3>
<dl>
    <dt>Government Type</dt>
    <dd>Municipality</dd>
    <dt>Entity</dt>
    <dd>Alpine</dd>
    <dt>Public Body</dt>
    <dd><a href="/pmn/sitemap/publicbody/872.html">City Council</a></dd>
</dl>
<h3>Notice Information</h3>
<dl>
    <dt>Notice Title</dt>
    <dd>8.25.26 City Council Meeting Work Session Packet and Audio</dd>
    <dt>Notice Type(s)</dt>
    <dd>Meeting</dd>
    <dt>Event Start Date &amp; Time</dt>
    <dd>August 25, 2026 06:00 PM</dd>
</dl>
<section>
    <h3>Audio File Address</h3>
    <dl>
        <dt>Audio File Location</dt>
        <dd><a target="_blank" href="https://www.youtube.com/watch?v=svq4oCHX0BA" aria-label="Audio File Location (opens in new window)">https://www.youtube.com/watch?v=svq4oCHX0BA</a></dd>
    </dl>
</section>
<h3>Download Attachments</h3>
<table>
    <caption>Download Attachments</caption>
    <thead><tr><th>File Name</th><th>Category</th><th>Date Added</th></tr></thead>
    <tbody>
        <tr>
            <td><a href="/pmn/files/1479195.pdf">CC 8-25-26 Packet.pdf</a></td>
            <td>Public Information Handout</td>
            <td>2026/08/24 03:18 PM</td>
        </tr>
    </tbody>
</table>
</body></html>
"""

NO_MEDIA_HTML = """
<html><body>
<h3>General Information</h3>
<dl>
    <dt>Government Type</dt>
    <dd>Municipality</dd>
    <dt>Entity</dt>
    <dd>Alpine</dd>
    <dt>Public Body</dt>
    <dd><a href="/pmn/sitemap/publicbody/872.html">City Council</a></dd>
</dl>
<h3>Notice Information</h3>
<dl>
    <dt>Notice Title</dt>
    <dd>8.25.26 City Council Meeting Work Session Packet and Audio</dd>
    <dt>Event Start Date &amp; Time</dt>
    <dd>August 25, 2026 06:00 PM</dd>
</dl>
<h3>Download Attachments</h3>
<table>
    <caption>Download Attachments</caption>
    <thead><tr><th>File Name</th><th>Category</th><th>Date Added</th></tr></thead>
    <tbody>
        <tr>
            <td><a href="/pmn/files/1479195.pdf">CC 8-25-26 Packet.pdf</a></td>
            <td>Public Information Handout</td>
            <td>2026/08/24 03:18 PM</td>
        </tr>
    </tbody>
</table>
</body></html>
"""

GRAND_COUNTY_HTML = """
<html><body>
<h3>General Information</h3>
<dl>
    <dt>Government Type</dt>
    <dd>County</dd>
    <dt>Entity</dt>
    <dd>Grand County</dd>
    <dt>Public Body</dt>
    <dd><a href="/pmn/sitemap/publicbody/1.html">Planning Commission</a></dd>
</dl>
<h3>Notice Information</h3>
<dl>
    <dt>Notice Title</dt>
    <dd>Planning Commission Regular Meeting - August 10, 2026</dd>
    <dt>Event Start Date &amp; Time</dt>
    <dd>August 10, 2026 04:00 PM</dd>
</dl>
<h3>Download Attachments</h3>
<table>
    <caption>Download Attachments</caption>
    <thead><tr><th>File Name</th><th>Category</th><th>Date Added</th></tr></thead>
    <tbody>
        <tr>
            <td><a href="/pmn/files/1472703.m4a">Planning Comm 8.10.26.m4a</a></td>
            <td>Audio Recording</td>
            <td>2026/08/11 11:16 AM</td>
        </tr>
        <tr>
            <td><a href="/pmn/files/1471454.pdf">packet PC 8.10.pdf</a></td>
            <td>Public Information Handout</td>
            <td>2026/08/11 11:16 AM</td>
        </tr>
    </tbody>
</table>
</body></html>
"""


def _fake_extract_info(video_id):
    return {
        "title": "Alpine City Council",
        "uploader": "Alpine City",
        "release_date": "20260825",
    }


def test_detect_platform_recognizes_pmn_notice_pages():
    assert detect_platform(ALPINE_URL) == "utah_pmn"
    assert detect_platform(GRAND_COUNTY_URL) == "utah_pmn"
    # The rest of utah.gov is unrelated state-government content, not in
    # scope -- only the specific notice-detail-page shape is claimed.
    assert detect_platform("https://www.utah.gov/government/index.html") == "unknown"


async def test_resolve_delegates_to_youtube_when_audio_file_location_is_a_known_platform(
    monkeypatch,
):
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)

    routes = {ALPINE_URL: FakeResponse(status=200, text=ALPINE_HTML, url=ALPINE_URL)}

    with mock_session(routes):
        result = await UtahPMNAssetFinder().resolve(ALPINE_URL)

    assert result.platform == "youtube"  # same delegation convention as clerkbase.py
    assert result.source_url == ALPINE_URL
    assert result.external_id == f"youtube:{REAL_VIDEO_ID}"
    # PMN's own ground-truth fields win over YouTube's/generic guesses --
    # the known-identity-override pattern (ENUMERATION_METHODS.md §98).
    assert result.jurisdiction == "Alpine, Utah"
    assert result.meeting_body == "City Council"
    assert result.title == "8.25.26 City Council Meeting Work Session Packet and Audio"
    # Short "YYYY-MM-DD" form, not PMN's own long raw text -- real,
    # confirmed-live production bug (2026-09-09): the Archive's `date`
    # column is VARCHAR(20), and PMN's raw "August 25, 2026 06:00 PM"
    # (24 chars) crashed a real ingest with StringDataRightTruncationError.
    assert result.date == "2026-08-25"
    assert result.video_url == f"https://www.youtube.com/embed/{REAL_VIDEO_ID}"


async def test_resolve_bare_hosted_audio_file_with_no_platform_wrapper():
    routes = {
        GRAND_COUNTY_URL: FakeResponse(
            status=200, text=GRAND_COUNTY_HTML, url=GRAND_COUNTY_URL
        )
    }

    with mock_session(routes):
        result = await UtahPMNAssetFinder().resolve(GRAND_COUNTY_URL)

    # No delegation possible -- utah.gov/pmn/files/* isn't a platform this
    # repo resolves, so this adapter itself is the platform of record.
    assert result.platform == "utah_pmn"
    assert result.external_id == "utah_pmn:1100143"
    assert result.jurisdiction == "Grand County, Utah"
    assert result.meeting_body == "Planning Commission"
    assert result.title == "Planning Commission Regular Meeting - August 10, 2026"
    assert result.date == "2026-08-10"  # see the sibling test's own comment
    assert result.video_url == "https://www.utah.gov/pmn/files/1472703.m4a"
    assert result.video_format == "m4a"
    assert result.segments == []  # needs the tier-3 Whisper pipeline, not resolved here


async def test_resolve_no_media_reports_no_video_but_keeps_real_metadata():
    routes = {ALPINE_URL: FakeResponse(status=200, text=NO_MEDIA_HTML, url=ALPINE_URL)}

    with mock_session(routes):
        result = await UtahPMNAssetFinder().resolve(ALPINE_URL)

    assert result.video_url is None
    assert result.video_warnings == [
        "No Audio File Location and no Audio/Video Recording attachment on this PMN notice."
    ]
    # Real page metadata is still surfaced even without media.
    assert result.jurisdiction == "Alpine, Utah"
    assert result.meeting_body == "City Council"
    assert result.title == "8.25.26 City Council Meeting Work Session Packet and Audio"


def test_short_date_never_exceeds_the_archive_varchar20_column():
    """Real, confirmed-live production bug (2026-09-09): PMN's raw
    "Event Start Date & Time" text is up to 24 characters, but the
    Archive's `date` column is VARCHAR(20) -- passing the raw text
    through crashed a real ingest with StringDataRightTruncationError.
    This is the direct regression test for that fix, independent of the
    two end-to-end resolve() tests above that also exercise it."""
    from app.platforms.utah_pmn import _short_date

    short = _short_date("August 10, 2026 05:30 PM")
    assert short == "2026-08-10"
    assert len(short) <= 20

    # A format PMN hasn't been confirmed to use falls back to None --
    # never the original long text, which is the one outcome that
    # crashes the database.
    assert _short_date("not a real date shape") is None
    assert _short_date(None) is None
    assert _short_date("") is None
