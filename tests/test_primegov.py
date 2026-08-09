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
