import pytest

from app.platforms.base import detect_platform, register
from app.platforms.cvtv import (
    CVTV_CLIENT_ID,
    CVTVAssetFinder,
    _event_id_from_url,
    is_cvtv_video_url,
)
from app.platforms.invintus import InvintusAssetFinder

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture


@pytest.fixture(autouse=True)
def _register_delegates():
    register(InvintusAssetFinder())
    register(CVTVAssetFinder())


# CVTV (cvtv.org), WO-1189, 2026-10-11. `vancouver_city_council_
# 2026101001.html` is the real, unmodified page and `..._getDetailed.json`
# the real live Invintus API response for client 2917038973 / event
# 2026101001. That event has no captions (`captionPath` is null), so the
# result has no segments; a CVTV meeting with captions has not been seen.

PAGE_URL = "https://www.cvtv.org/video/vancouver-city-council-10-05-26-2026101001/"
API_URL = "https://api.v3.invintus.com/v2/Event/getDetailed"


def test_fixture_page_carries_the_client_id_the_adapter_hard_codes():
    html = load_fixture("cvtv", "vancouver_city_council_2026101001.html")
    assert f'"clientId":"{CVTV_CLIENT_ID}"' in html
    assert 'data-eventid="2026101001"' in html


async def test_resolve_real_vancouver_city_council_meeting():
    detail_json = load_fixture("cvtv", "vancouver_city_council_getDetailed.json")
    # The link carries the eventID, so cvtv.org is never fetched; the mock
    # raises on any unmocked call.
    post_routes = {API_URL: FakeResponse(status=200, text=detail_json, url=API_URL)}

    with mock_session({}, post_routes=post_routes):
        result = await CVTVAssetFinder().resolve(PAGE_URL)

    assert result.platform == "cvtv"
    assert result.source_url == PAGE_URL
    assert result.external_id == "cvtv:2026101001"
    assert result.title == "Vancouver City Council (10-05-26)"
    assert result.date == "2026-10-05"
    assert result.video_url.endswith(".mp4")
    assert result.video_url.startswith("https://m-download.invintus.com/2917038973/")


async def test_resolve_link_without_id_reads_the_page():
    # Synthetic link: no real cvtv.org video link without a trailing
    # eventID has been seen. The page is the real fixture.
    url = "https://www.cvtv.org/video/vancouver-city-council/"
    html = load_fixture("cvtv", "vancouver_city_council_2026101001.html")
    detail_json = load_fixture("cvtv", "vancouver_city_council_getDetailed.json")
    routes = {url: FakeResponse(status=200, text=html, url=url)}
    post_routes = {API_URL: FakeResponse(status=200, text=detail_json, url=API_URL)}

    with mock_session(routes, post_routes=post_routes):
        result = await CVTVAssetFinder().resolve(url)

    assert result.external_id == "cvtv:2026101001"
    assert result.source_url == url


async def test_resolve_link_without_id_and_no_player_raises_value_error():
    url = "https://www.cvtv.org/video/nothing-here/"
    routes = {url: FakeResponse(status=200, text="<html></html>", url=url)}
    with mock_session(routes):
        with pytest.raises(ValueError):
            await CVTVAssetFinder().resolve(url)


@pytest.mark.parametrize(
    "url,expected",
    [
        (PAGE_URL, "2026101001"),
        (
            "https://www.cvtv.org/video/regional-transportation-council-10-06-26-2026101003/",
            "2026101003",
        ),
        ("https://www.cvtv.org/video/some-slug/", None),
    ],
)
def test_event_id_from_url(url, expected):
    assert _event_id_from_url(url) == expected


def test_detect_platform_and_host_check():
    assert detect_platform(PAGE_URL) == "cvtv"
    assert is_cvtv_video_url(PAGE_URL) is True
    assert is_cvtv_video_url("https://www.cvtv.org/") is False
    assert (
        is_cvtv_video_url("https://tvw.org/video/senate-housing-2026091165/") is False
    )
