"""CATS (catstv.net) adapter. Fixtures in tests/fixtures/catstv/ are real answers read live on 2026-10-10: the Bloomington City Council page of 2026-10-07
(m.php?q=16544) with the first 6 KB of its real WebVTT file, and a Lake Lemon Conservancy District page (m.php?q=11618) that has a video and no captions."""

from app.platforms.base import detect_platform
from app.platforms.catstv import (
    CatsTvAssetFinder,
    body_code_from_video_url,
    meeting_id_from_url,
)
from app.utils.tenant_key import pin_tenant_key, tenant_key

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

PAGE_URL = "https://catstv.net/m.php?q=16544"
VIDEO_URL = "https://catstv.blob.core.windows.net/videoarchive/B_CC_261007.m4v"
VTT_URL = "https://catstv.blob.core.windows.net/videoarchive/B_CC_261007_subtitles.vtt"
NO_CAPTION_URL = "https://catstv.net/m.php?q=11618"


async def test_resolve_a_captioned_meeting_gives_video_title_date_length_and_cues():
    routes = {
        PAGE_URL: FakeResponse(
            text=load_fixture(
                "catstv", "m16544_bloomington_city_council_2026-10-07.html"
            ),
            url=PAGE_URL,
        ),
        VTT_URL: FakeResponse(
            text=load_fixture("catstv", "B_CC_261007_subtitles_head.vtt"), url=VTT_URL
        ),
    }
    with mock_session(routes):
        result = await CatsTvAssetFinder().resolve(PAGE_URL)

    assert result.platform == "catstv"
    assert result.external_id == "catstv:16544"
    assert result.title == "Bloomington City Council 10/7"
    assert result.date == "2026-10-07"
    assert result.video_url == VIDEO_URL
    assert result.video_format == "mp4"
    assert result.video_channel == "cats:b_cc"
    assert result.video_duration_seconds == 3 * 3600 + 18 * 60 + 18
    assert len(result.segments) > 10
    assert result.transcript_warnings == []
    assert result.video_warnings == []


async def test_a_meeting_with_a_video_and_no_captions_says_so():
    routes = {
        NO_CAPTION_URL: FakeResponse(
            text=load_fixture("catstv", "m11618_lake_lemon_no_captions.html"),
            url=NO_CAPTION_URL,
        )
    }
    with mock_session(routes):
        result = await CatsTvAssetFinder().resolve(NO_CAPTION_URL)
    assert result.video_url.endswith("M_LLCD_220901.m4v")
    assert result.video_channel == "cats:m_llcd"
    assert result.segments == []
    assert result.transcript_warnings == ["No captions found for this video."]


async def test_a_vtt_that_will_not_load_leaves_the_video_and_a_warning():
    routes = {
        PAGE_URL: FakeResponse(
            text=load_fixture(
                "catstv", "m16544_bloomington_city_council_2026-10-07.html"
            ),
            url=PAGE_URL,
        ),
        VTT_URL: FakeResponse(status=404, text="", url=VTT_URL),
    }
    with mock_session(routes):
        result = await CatsTvAssetFinder().resolve(PAGE_URL)
    assert result.video_url == VIDEO_URL
    assert result.segments == []
    assert result.transcript_warnings == ["No captions found for this video."]


async def test_a_page_that_does_not_load_gives_a_plain_warning():
    routes = {PAGE_URL: FakeResponse(status=500, text="", url=PAGE_URL)}
    with mock_session(routes):
        result = await CatsTvAssetFinder().resolve(PAGE_URL)
    assert result.video_url is None
    assert result.video_warnings == ["Could not load this catstv.net meeting."]


async def test_a_listing_page_is_not_a_meeting():
    result = await CatsTvAssetFinder().resolve("https://catstv.net/government.php")
    assert result.video_url is None
    assert "not a single meeting" in result.video_warnings[0]


def test_meeting_id_and_body_code_readers():
    assert meeting_id_from_url(PAGE_URL) == "16544"
    assert meeting_id_from_url("https://www.catstv.net/m.php?q=16544&x=1") == "16544"
    assert meeting_id_from_url("https://catstv.net/government.php") is None
    assert meeting_id_from_url("https://catstv.net/m.php?q=abc") is None
    assert body_code_from_video_url(VIDEO_URL) == "B_CC"
    assert (
        body_code_from_video_url(
            "https://catstv.blob.core.windows.net/videoarchive/M_CS_WS_261008.m4v"
        )
        == "M_CS_WS"
    )
    assert body_code_from_video_url("https://x.example/odd-name.m4v") is None


def test_the_host_is_detected_with_and_without_www():
    assert detect_platform(PAGE_URL) == "catstv"
    assert detect_platform("https://www.catstv.net/m.php?q=1") == "catstv"


def test_the_address_names_no_body_but_a_pin_matches_the_page_hint():
    assert tenant_key(PAGE_URL) is None
    assert pin_tenant_key("catstv.net", "channel=cats:B_CC") == "b_cc"
    assert pin_tenant_key("www.catstv.net", "channel=cats:m_cs_ws") == "m_cs_ws"
