from app.platforms.primegov import PrimeGovAssetFinder
from app.platforms.youtube import YouTubeAssetFinder

from aiohttp_mock import FakeResponse, mock_session

# No fixture-based tests existed for this adapter before this file (see
# BACKLOG.md's "zero test coverage" note). The `var videoUrl = "..."`
# extraction pattern and the real video id below come from the actual
# Oklahoma City sample resolved live 2026-08-08 -- see BACKLOG.md's
# PrimeGov date/jurisdiction entry -- and the Thousand Oaks video id
# comes from the earlier YouTube-removed/blocked bug entry in
# BACKLOG_DONE.md. YouTubeAssetFinder._extract_info is monkeypatched the
# same way tests/test_youtube.py does it, so these tests exercise
# PrimeGovAssetFinder's own page-scraping/delegation logic without making
# a real yt-dlp call.

PAGE_URL = "https://okc.primegov.com/Portal/Meeting?meetingTemplateId=68482"
REAL_VIDEO_ID = "uNDJRR3ywVo"

# Trimmed real page shape: the actual OKC page is ~790KB, but the only
# part PrimeGovAssetFinder reads is this one <script> variable, right
# next to the iframe_api script tag per the adapter's own docstring.
PAGE_HTML_WITH_VIDEO = f"""
<html><head><title>Meeting</title></head>
<body>
<script src="https://www.youtube.com/iframe_api"></script>
<script>
var videoUrl = "{REAL_VIDEO_ID}";
</script>
</body></html>
"""

PAGE_HTML_NO_VIDEO = "<html><head><title>Meeting</title></head><body>No player here.</body></html>"

# Trimmed real page shape for the agenda header, confirmed live 2026-08-09
# against both meetingTemplateId pages -- see BACKLOG_DONE.md's PrimeGov
# date/jurisdiction entry. Real bug this fixes: YouTube's own upload_date
# was one day late for both samples (uploaded the day after the meeting),
# and the uploader channel name gave no usable jurisdiction at all for
# Thousand Oaks ("CTO Meetings").
OKC_HEADER_HTML = """
<table><tbody>
<tr><td><span><strong>THE CITY OF OKLAHOMA CITY</strong></span></td></tr>
<tr><td><span><strong>FORMAL AGENDA</strong></span></td></tr>
<tr><td><span><strong>CITY COUNCIL</strong></span></td></tr>
<tr><td><span><strong>August 4, 2026</strong></span></td></tr>
</tbody></table>
"""

TOAKS_HEADER_HTML = """
<p>POSTED 11:15 AM, 7/3/2026, to move Item No. 15A to Consent Calendar</p>
<span><b>City Council</b><br>
<b>REGULAR MEETING </b></span>
<span><strong>Tuesday, July 07, 2026</strong><br>
<b>Andrew P. Fox City Council Chambers<br>
2100 E. Thousand Oaks Blvd., Thousand Oaks, CA 91362</b></span>
<p>It is the mission of the City of Thousand Oaks that all employees are
treated with respect and dignity.</p>
"""

PAGE_HTML_OKC_FULL = f"""
<html><head><title>Meeting</title></head>
<body>
{OKC_HEADER_HTML}
<script src="https://www.youtube.com/iframe_api"></script>
<script>
var videoUrl = "{REAL_VIDEO_ID}";
</script>
</body></html>
"""

TOAKS_VIDEO_ID = "VNMQYICdQvs"

PAGE_HTML_TOAKS_FULL = f"""
<html><head><title>Meeting</title></head>
<body>
{TOAKS_HEADER_HTML}
<script src="https://www.youtube.com/iframe_api"></script>
<script>
var videoUrl = "{TOAKS_VIDEO_ID}";
</script>
</body></html>
"""


def _fake_extract_info(video_id):
    return {
        "title": "Oklahoma City Council Meeting - August 4, 2026",
        "uploader": "cityofokc",
        "upload_date": "20260805",
    }


async def test_resolve_extracts_video_id_and_delegates_to_youtube(monkeypatch):
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    routes = {PAGE_URL: FakeResponse(status=200, text=PAGE_HTML_WITH_VIDEO, url=PAGE_URL)}

    with mock_session(routes):
        result = await PrimeGovAssetFinder().resolve(PAGE_URL)

    assert result.platform == "youtube"  # delegated finder's own platform name, unchanged
    assert result.video_url == f"https://www.youtube.com/embed/{REAL_VIDEO_ID}"
    assert result.external_id == f"youtube:{REAL_VIDEO_ID}"
    assert result.title == "Oklahoma City Council Meeting - August 4, 2026"


async def test_resolve_keeps_original_primegov_url_as_source_url(monkeypatch):
    # The documented quirk (PrimeGovAssetFinder's own class docstring):
    # unlike Legistar/CivicPlus's delegation, source_url stays the
    # original PrimeGov page, not the delegated platform's URL, so "View
    # original source" keeps pointing back to the real PrimeGov meeting
    # page rather than a bare YouTube link.
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    routes = {PAGE_URL: FakeResponse(status=200, text=PAGE_HTML_WITH_VIDEO, url=PAGE_URL)}

    with mock_session(routes):
        result = await PrimeGovAssetFinder().resolve(PAGE_URL)

    assert result.source_url == PAGE_URL


async def test_resolve_returns_no_video_warning_when_page_has_no_player():
    # Confirmed live: an agenda-only PrimeGov page (meetingTemplateId with
    # no matching recording) has no videoUrl variable at all -- see the
    # class docstring's LA City sample note.
    routes = {PAGE_URL: FakeResponse(status=200, text=PAGE_HTML_NO_VIDEO, url=PAGE_URL)}

    with mock_session(routes):
        result = await PrimeGovAssetFinder().resolve(PAGE_URL)

    assert result.platform == "primegov"
    assert result.video_url is None
    assert result.segments == []
    assert any("no video found" in w.lower() for w in result.video_warnings)


def test_extract_video_id_matches_real_page_variable_shape():
    assert PrimeGovAssetFinder._extract_video_id(PAGE_HTML_WITH_VIDEO) == REAL_VIDEO_ID


def test_extract_video_id_returns_none_when_absent():
    assert PrimeGovAssetFinder._extract_video_id(PAGE_HTML_NO_VIDEO) is None


def test_extract_date_reads_all_caps_okc_header():
    assert PrimeGovAssetFinder._extract_date(OKC_HEADER_HTML) == "2026-08-04"


def test_extract_date_reads_weekday_prefixed_toaks_header():
    # The "POSTED 11:15 AM, 7/3/2026" line above the real header uses
    # numeric slash format, not a full month name, so it doesn't false-match
    # ahead of the real "Tuesday, July 07, 2026" meeting date.
    assert PrimeGovAssetFinder._extract_date(TOAKS_HEADER_HTML) == "2026-07-07"


def test_extract_date_returns_none_without_a_month_name_date():
    assert PrimeGovAssetFinder._extract_date(PAGE_HTML_NO_VIDEO) is None


def test_extract_jurisdiction_normalizes_all_caps_header():
    assert PrimeGovAssetFinder._extract_jurisdiction(OKC_HEADER_HTML) == "City of Oklahoma City"


def test_extract_jurisdiction_stops_at_lowercase_word_in_flowing_prose():
    # Real bug this guards against: a naive "city of X" regex run against
    # Thousand Oaks's real page grabbed "Thousand Oaks that all employees
    # are to be treated with respect and dignity" from unrelated mission-
    # statement text elsewhere on the page, since nothing but a lowercase
    # word follows the real city name there.
    prose = "It is the mission of the City of Thousand Oaks that all employees are treated well."
    assert PrimeGovAssetFinder._extract_jurisdiction(prose) == "City of Thousand Oaks"


def test_extract_jurisdiction_reads_toaks_header():
    assert PrimeGovAssetFinder._extract_jurisdiction(TOAKS_HEADER_HTML) == "City of Thousand Oaks"


def test_extract_jurisdiction_returns_none_when_absent():
    assert PrimeGovAssetFinder._extract_jurisdiction(PAGE_HTML_NO_VIDEO) is None


async def test_resolve_overrides_wrong_youtube_date_and_jurisdiction_with_page_header(monkeypatch):
    # The real bug: YouTube's upload_date was one day late for both real
    # samples (uploaded the day after the meeting), and Thousand Oaks's
    # uploader ("CTO Meetings") carries no usable city name -- the page's
    # own agenda header is correct for both, confirmed live 2026-08-09.
    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: {
            "title": "Oklahoma City Council Meeting - August 4, 2026",
            "uploader": "cityofokc",
            "upload_date": "20260805",  # wrong: one day after the real meeting
        },
    )
    routes = {PAGE_URL: FakeResponse(status=200, text=PAGE_HTML_OKC_FULL, url=PAGE_URL)}

    with mock_session(routes):
        result = await PrimeGovAssetFinder().resolve(PAGE_URL)

    assert result.date == "2026-08-04"
    assert result.jurisdiction == "City of Oklahoma City"


async def test_resolve_overrides_uninformative_youtube_uploader(monkeypatch):
    toaks_url = "https://toaks.primegov.com/Portal/Meeting?meetingTemplateId=9446"
    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: {
            "title": "Thousand Oaks City Council Meeting - July 7, 2026",
            "uploader": "CTO Meetings",  # real value: no usable city name
            "upload_date": "20260708",  # wrong: one day after the real meeting
        },
    )
    routes = {toaks_url: FakeResponse(status=200, text=PAGE_HTML_TOAKS_FULL, url=toaks_url)}

    with mock_session(routes):
        result = await PrimeGovAssetFinder().resolve(toaks_url)

    assert result.date == "2026-07-07"
    assert result.jurisdiction == "City of Thousand Oaks"


async def test_resolve_falls_back_to_youtube_values_when_page_has_no_header(monkeypatch):
    # Existing behavior preserved for pages without the agenda header (e.g.
    # a stripped-down/unusual PrimeGov template) -- better-than-nothing
    # YouTube values still come through unchanged rather than being
    # silently overwritten with None.
    monkeypatch.setattr(YouTubeAssetFinder, "_extract_info", _fake_extract_info)
    routes = {PAGE_URL: FakeResponse(status=200, text=PAGE_HTML_WITH_VIDEO, url=PAGE_URL)}

    with mock_session(routes):
        result = await PrimeGovAssetFinder().resolve(PAGE_URL)

    assert result.date == "2026-08-05"
    assert result.jurisdiction == "cityofokc"
