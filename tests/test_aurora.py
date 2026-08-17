"""Tests for Aurora, CO's own council video site (app/platforms/aurora.py).

Real fixtures fetched live 2026-08-12 (see BACKLOG.md's Wave 2 platform-
coverage entry): a real video page and its real, populated VTT captions.
"""

from app.platforms.aurora import AuroraTvAssetFinder
from app.platforms.base import detect_platform

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

MEETING_URL = (
    "https://www.auroratv.org/video/regular-meeting-aurora-city-council-june-22-2026"
)
CAPTION_URL = "https://www.auroratv.org/sites/default/files/video-captions-70037.vtt"
REAL_MP4_URL = "https://reflect-aurora.cablecast.tv/store-4/13040-EDITED-Regular-Meeting-of-v2/vod.mp4"


def test_detect_platform_recognizes_auroratv_domain():
    assert detect_platform(MEETING_URL) == "aurora_tv"


async def test_resolve_real_page_returns_direct_mp4_and_captions():
    html = load_fixture("aurora", "regular_meeting_june_22_2026.html")
    vtt = load_fixture("aurora", "video-captions-70037.vtt")

    routes = {
        MEETING_URL: FakeResponse(status=200, text=html, url=MEETING_URL),
        CAPTION_URL: FakeResponse(status=200, text=vtt, url=CAPTION_URL),
    }

    with mock_session(routes):
        result = await AuroraTvAssetFinder().resolve(MEETING_URL)

    assert result.platform == "aurora_tv"
    assert result.video_url == REAL_MP4_URL
    assert result.video_format == "mp4"
    assert result.jurisdiction == "Aurora, CO"
    assert result.date == "2026-06-22"
    assert result.title == "Regular Meeting of the Aurora City Council, June 22, 2026"
    assert len(result.segments) > 5000
    assert result.transcript_language == "en"
    assert not result.video_warnings
    assert not result.transcript_warnings


async def test_video_caption_field_is_a_filesystem_path_not_a_url():
    # Real gap found live 2026-08-12: the top-level "video_caption" key in
    # Drupal's settings blob is a server filesystem path
    # ("/home/atowntv/public_html/..."), not a fetchable URL -- only
    # jw_data.caption_file_path is the real https:// one. A regression
    # here would silently try (and fail) to fetch the filesystem path.
    html = load_fixture("aurora", "regular_meeting_june_22_2026.html")
    settings = AuroraTvAssetFinder._extract_drupal_settings(html)
    assert settings["video_caption"].startswith("/home/")
    assert settings["jw_data"]["caption_file_path"] == CAPTION_URL


async def test_resolve_missing_mp4_url_reports_no_video():
    html = (
        "<html><head><title>Some Page</title></head><body>No video here.</body></html>"
    )
    url = "https://www.auroratv.org/video/no-video-page"

    with mock_session({url: FakeResponse(status=200, text=html, url=url)}):
        result = await AuroraTvAssetFinder().resolve(url)

    assert result.video_url is None
    assert result.video_warnings == ["No video found on this page."]


async def test_resolve_caption_fetch_failure_reports_no_transcript():
    html = load_fixture("aurora", "regular_meeting_june_22_2026.html")

    routes = {
        MEETING_URL: FakeResponse(status=200, text=html, url=MEETING_URL),
        CAPTION_URL: FakeResponse(status=404),
    }

    with mock_session(routes):
        result = await AuroraTvAssetFinder().resolve(MEETING_URL)

    assert result.video_url == REAL_MP4_URL
    assert result.segments == []
    assert result.transcript_warnings == ["No transcript found for this event."]
