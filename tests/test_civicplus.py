import pytest

from app.platforms.base import CalendarPageError, register
from app.platforms.civicplus import CivicPlusAssetFinder
from app.platforms.granicus import GranicusAssetFinder

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture


@pytest.fixture(autouse=True)
def _register_granicus():
    register(GranicusAssetFinder())


async def test_listing_with_multiple_videos_raises_pick_list():
    # Reconstructed from the exact real markup shape confirmed on
    # ca-westlakevillage.civicplus.com 2026-08-06 -- see
    # tests/fixtures/civicplus/README.md for why this isn't a raw-saved
    # live page (the original site has since been restructured).
    url = "https://example.civicplus.com/AgendaCenter"
    html = load_fixture("civicplus", "agendacenter_listing.html")

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        with pytest.raises(CalendarPageError) as exc_info:
            await CivicPlusAssetFinder().resolve(url)

    candidates = exc_info.value.candidates
    assert len(candidates) == 2
    assert all("granicus.com" in c["url"] for c in candidates)
    assert candidates[0]["date"] == "2026-04-08"
    assert candidates[0]["title"] == "City Council Regular Meeting"


async def test_listing_with_single_video_delegates_to_granicus():
    url = "https://example.civicplus.com/AgendaCenter"
    html = load_fixture("civicplus", "agendacenter_single.html")
    granicus_url = "https://westlakevillage.granicus.com/player/clip/1201?view_id=1"
    granicus_html = load_fixture("granicus", "napacity_clip3450.html")

    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        granicus_url: FakeResponse(status=200, text=granicus_html, url=granicus_url),
        "https://westlakevillage.granicus.com/videos/1201/captions.vtt": FakeResponse(
            status=404
        ),
        "https://westlakevillage.granicus.com/AgendaViewer.php?clip_id=1201&embedded=1": FakeResponse(
            status=404
        ),
    }

    with mock_session(routes):
        result = await CivicPlusAssetFinder().resolve(url)

    assert result.platform == "granicus"
    assert result.external_id == "granicus:westlakevillage.granicus.com:1201"


async def test_no_video_rows_returns_warning():
    url = "https://example.civicplus.com/AgendaCenter"
    html = "<html><body><table></table></body></html>"

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await CivicPlusAssetFinder().resolve(url)

    assert result.platform == "civicplus"
    assert any("no video" in w.lower() for w in result.video_warnings)
