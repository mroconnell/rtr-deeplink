import pytest

from app.platforms.base import register
from app.platforms.invintus import InvintusAssetFinder
from app.platforms.tvw import TVWAssetFinder, is_tvw_video_url

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture


@pytest.fixture(autouse=True)
def _register_delegates():
    # resolve() delegates to InvintusAssetFinder via resolve_via_platform()
    # -- same pattern test_az_legislature.py's own `_register_delegates`
    # fixture uses for the same delegation shape.
    register(InvintusAssetFinder())
    register(TVWAssetFinder())


# TVW (tvw.org) -- Washington State's public-affairs network, found via
# WO-1009's recon and built by WO-1010 (2026-09-22). `senate_housing_
# 2026091165.html` is the real, live, unmodified `tvw.org/video/senate-
# housing-2026091165/` wrapper page; `senate_housing_getDetailed.json` is
# the real live Invintus API response for the same event (clientID
# 9375922947, added to invintus.py's LEGISLATURE_CLIENTS); `senate_
# housing_captions_trimmed.vtt` is trimmed to its first 30 real cue blocks
# (29 parse into real segments) -- same "trimmed real VTT fixture"
# convention test_az_legislature.py/test_invintus.py use -- a real,
# coherent Senate Housing committee transcript, not placeholder text. See
# tvw.py's own module docstring for the full investigation.

PAGE_URL = "https://tvw.org/video/senate-housing-2026091165/"
API_URL = "https://api.v3.invintus.com/v2/Event/getDetailed"
CAPTIONS_URL = (
    "https://m-download.invintus.com/9375922947/"
    "8f41283b91cc8d15b98592980cb82c4eed78c099.vtt"
)


async def test_resolve_real_senate_housing_meeting():
    wrapper_html = load_fixture("tvw", "senate_housing_2026091165.html")
    detail_json = load_fixture("tvw", "senate_housing_getDetailed.json")
    captions_vtt = load_fixture("tvw", "senate_housing_captions_trimmed.vtt")

    routes = {
        PAGE_URL: FakeResponse(status=200, text=wrapper_html, url=PAGE_URL),
        CAPTIONS_URL: FakeResponse(status=200, text=captions_vtt, url=CAPTIONS_URL),
    }
    post_routes = {
        API_URL: FakeResponse(status=200, text=detail_json, url=API_URL),
    }

    with mock_session(routes, post_routes=post_routes):
        result = await TVWAssetFinder().resolve(PAGE_URL)

    assert result.platform == "tvw"
    assert result.source_url == PAGE_URL
    assert result.external_id == "tvw:2026091165"
    assert result.title == "Senate Housing"
    assert result.date == "2026-09-17"
    # Corrected from Invintus's own raw categories via LEGISLATURE_CLIENTS
    # -- see invintus.py's module docstring.
    assert result.jurisdiction == "Washington State Legislature"
    assert result.meeting_body == "Senate Housing"
    assert (
        result.video_url == "https://m-download.invintus.com/9375922947/"
        "d3634e1d5284c35551921bcfc50b77a47aa6f9d4.mp4"
    )
    assert result.video_format == "mp4"
    assert len(result.segments) == 29
    assert "Senate housing" in result.segments[1].text
    assert result.transcript_warnings == []


async def test_resolve_missing_client_event_ids_raises_value_error():
    routes = {
        PAGE_URL: FakeResponse(
            status=200, text="<html><body>no player here</body></html>", url=PAGE_URL
        ),
    }
    with mock_session(routes):
        with pytest.raises(ValueError):
            await TVWAssetFinder().resolve(PAGE_URL)


def test_is_tvw_video_url_requires_video_path_and_host():
    assert is_tvw_video_url(PAGE_URL) is True
    assert is_tvw_video_url("https://tvw.org/") is False
    assert is_tvw_video_url("https://tvw.org/schedule/") is False
    assert (
        is_tvw_video_url("https://player.invintus.com/?clientID=1&eventID=2") is False
    )
