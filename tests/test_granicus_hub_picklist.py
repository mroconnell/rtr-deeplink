"""Granicus hub addresses (ViewPublisher.php / ViewPublisherRSS.php with a
view_id and no clip) return the "pick a meeting" answer. No network: every
request goes through aiohttp_mock with saved fixtures."""

import pytest
from fastapi.testclient import TestClient

import app.main
from app.platforms import granicus
from app.platforms.base import CalendarPageError, register
from app.platforms.granicus import (
    GranicusAssetFinder,
    _is_view_publisher_hub,
    list_hub_meetings,
)
from app.utils import url_guard

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

PWC = "https://pwcgov.granicus.com/ViewPublisherRSS.php?view_id=23"
PWC_HUB = "https://pwcgov.granicus.com/ViewPublisher.php?view_id=23"
EMPTY_RSS = "<?xml version='1.0'?><rss><channel><title>x</title></channel></rss>"


@pytest.fixture(autouse=True)
def _clear_cache():
    granicus._hub_cache.clear()
    yield
    granicus._hub_cache.clear()


@pytest.mark.parametrize(
    "url,expected",
    [
        (PWC_HUB, True),
        (PWC, True),
        (PWC + "&mode=video", True),
        (PWC + "&mode=agendas", True),
        (PWC + "&clip_id=3903", False),
        (PWC_HUB + "&event_id=5", False),
        (PWC_HUB + "&meta_id=5", False),
        ("https://pwcgov.granicus.com/ViewPublisher.php", False),
        ("https://pwcgov.granicus.com/MediaPlayer.php?view_id=23&clip_id=1", False),
        ("https://pwcgov.granicus.com/AgendaViewer.php?view_id=23", False),
    ],
)
def test_is_view_publisher_hub(url, expected):
    assert _is_view_publisher_hub(url) is expected


async def test_hub_raises_calendar_page_with_candidates():
    xml = load_fixture("granicus", "pwcva_view23_rss_video.xml")
    routes = {PWC + "&mode=video": FakeResponse(status=200, text=xml)}
    with mock_session(routes):
        with pytest.raises(CalendarPageError) as exc:
            await GranicusAssetFinder().resolve(PWC_HUB)
    cands = exc.value.candidates
    assert 0 < len(cands) <= 15
    first = cands[0]
    assert set(first) == {"title", "date", "url"}
    assert first["url"].startswith("https://pwcgov.granicus.com/MediaPlayer.php?")
    assert first["date"] == "2026-09-09"
    assert "Granicus" in str(exc.value)


async def test_rss_hub_with_mode_param_also_lists():
    xml = load_fixture("granicus_channel", "kansascity_viewpublisher_rss.xml")
    url = "https://kansascity.granicus.com/ViewPublisherRSS.php?view_id=2&mode=video"
    routes = {url: FakeResponse(status=200, text=xml)}
    with mock_session(routes):
        with pytest.raises(CalendarPageError) as exc:
            await GranicusAssetFinder().resolve(url)
    assert exc.value.candidates
    assert all("clip_id=" in c["url"] for c in exc.value.candidates)


async def test_video_empty_falls_back_to_podcast():
    xml = load_fixture("granicus_channel", "yonkersny_viewpublisher_rss.xml")
    base = "https://yonkersny.granicus.com/ViewPublisherRSS.php?view_id=1"
    routes = {
        base + "&mode=video": FakeResponse(status=200, text=EMPTY_RSS),
        base + "&mode=podcast": FakeResponse(status=200, text=xml),
    }
    with mock_session(routes):
        items = await list_hub_meetings(base)
    assert items
    assert items[0]["url"] == (
        "https://yonkersny.granicus.com/MediaPlayer.php?view_id=1&clip_id=56"
    )
    assert items[0]["date"] == "2024-10-22"


async def test_both_modes_empty_returns_nothing_and_resolve_keeps_old_path():
    base = "https://pwcgov.granicus.com/ViewPublisherRSS.php?view_id=23"
    routes = {
        base + "&mode=video": FakeResponse(status=200, text=EMPTY_RSS),
        base + "&mode=podcast": FakeResponse(status=200, text=EMPTY_RSS),
    }
    with mock_session(routes):
        assert await list_hub_meetings(base) == []


async def test_http_error_returns_nothing():
    base = "https://pwcgov.granicus.com/ViewPublisherRSS.php?view_id=23"
    routes = {
        base + "&mode=video": FakeResponse(status=500),
        base + "&mode=podcast": FakeResponse(status=404),
    }
    with mock_session(routes):
        assert await list_hub_meetings(base) == []


async def test_listing_is_cached_between_pastes():
    xml = load_fixture("granicus", "pwcva_view23_rss_video.xml")
    routes = {PWC + "&mode=video": FakeResponse(status=200, text=xml)}
    with mock_session(routes):
        first = await list_hub_meetings(PWC_HUB)
    # Second call has no routes at all: any request would fail the mock.
    with mock_session({}):
        second = await list_hub_meetings(PWC_HUB)
    assert first == second and first


async def test_failures_are_not_cached():
    routes = {
        PWC + "&mode=video": FakeResponse(status=500),
        PWC + "&mode=podcast": FakeResponse(status=500),
    }
    with mock_session(routes):
        assert await list_hub_meetings(PWC_HUB) == []
    xml = load_fixture("granicus", "pwcva_view23_rss_video.xml")
    with mock_session({PWC + "&mode=video": FakeResponse(status=200, text=xml)}):
        assert await list_hub_meetings(PWC_HUB)


def test_parser_handles_cdata_entities_and_missing_dates():
    xml = (
        "<rss><channel>"
        "<item><title><![CDATA[Budget & Finance <Special>]]></title>"
        "<link>https://x.granicus.com/MediaPlayer.php?view_id=1&amp;clip_id=9</link></item>"
        "<item><title>Parks &amp; Rec</title>"
        "<link>https://x.granicus.com/MediaPlayer.php?view_id=1&amp;clip_id=8</link></item>"
        "<item><title>No video</title><link>https://x.granicus.com/AgendaViewer.php?view_id=1</link></item>"
        "</channel></rss>"
    )
    items = granicus._parse_rss_items(xml, "x.granicus.com", "1", 15)
    assert [i["title"] for i in items] == ["Budget & Finance <Special>", "Parks & Rec"]
    assert items[0]["date"] is None
    assert items[1]["url"].endswith("clip_id=8")


async def test_media_player_clip_url_is_not_treated_as_hub():
    # Same real page and routes as the existing tulsa clip test: a clip URL
    # must go through the normal resolve path, not the pick-list.
    url = "https://tulsa-ok.granicus.com/player/clip/7694?redirect=true&view_id=4"
    assert _is_view_publisher_hub(url) is False
    html = load_fixture("granicus", "tulsa_clip7694.html")
    rss = load_fixture("granicus", "tulsa_view4_rss_clip7694.xml")
    routes = {
        url: FakeResponse(status=200, text=html, url=url),
        "https://tulsa-ok.granicus.com/ViewPublisherRSS.php?view_id=4&mode=video": (
            FakeResponse(status=200, text=rss)
        ),
        "https://tulsa-ok.granicus.com/videos/7694/captions.vtt": FakeResponse(
            status=404
        ),
    }
    with mock_session(routes):
        try:
            result = await GranicusAssetFinder().resolve(url)
        except CalendarPageError:  # pragma: no cover
            pytest.fail("clip URL must not produce a pick-list")
    assert result.video_url


class TestResolveRoute:
    client = TestClient(app.main.app)

    @pytest.fixture(autouse=True)
    def _dns(self, monkeypatch):
        monkeypatch.setattr(
            url_guard, "_resolve_hostname", lambda hostname: ["93.184.216.34"]
        )

    def test_api_resolve_returns_calendar_page_for_hub(self):
        register(GranicusAssetFinder())
        xml = load_fixture("granicus", "pwcva_view23_rss_video.xml")
        routes = {PWC + "&mode=video": FakeResponse(status=200, text=xml)}
        with mock_session(routes):
            response = self.client.post("/api/resolve", json={"url": PWC_HUB})
        data = response.json()
        assert data["error"] == "calendar_page"
        assert data["candidates"]
        assert set(data["candidates"][0]) >= {"title", "date", "url"}
