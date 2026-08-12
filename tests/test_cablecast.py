"""Tests for Detroit, MI's Cablecast video portal (app/platforms/cablecast.py).

Real fixture fetched live 2026-08-12 (see BACKLOG.md/BACKLOG_DONE.md) --
a real show page, a Remix.js SSR app embedding the target show plus a
~35-item "related shows" carousel in one window.__remixContext JSON blob.
"""

from app.platforms.base import detect_platform
from app.platforms.cablecast import CablecastAssetFinder

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

PORTAL_URL = "http://detroit-vod.cablecast.tv/internetchannel/show/15323?site=1"
REAL_VOD_URL = (
    "https://reflect-detroit-vod.cablecast.tv/store-8/"
    "15323-Detroit-City-Council-Formal-Session-07-28-2026-v3/vod.m3u8"
)


def test_detect_platform_recognizes_cablecast_show_url():
    assert detect_platform(PORTAL_URL) == "cablecast"
    # Charlotte, NC's confirmed Cablecast site uses a different template
    # (no /internetchannel/show/ path) -- deliberately not matched here,
    # see cablecast.py's module docstring.
    assert detect_platform("https://charlotte.cablecast.tv/internetchannel/?site=1") == "unknown"


async def test_resolve_real_detroit_show():
    html = load_fixture("cablecast", "detroit_show_15323.html")
    # Real gap confirmed live: the portal's HTTPS hangs indefinitely for
    # the whole domain, so resolve() always fetches over plain HTTP --
    # the mocked route reflects that (only the http:// URL is registered).
    fetch_url = "http://detroit-vod.cablecast.tv/internetchannel/show/15323?site=1"

    routes = {fetch_url: FakeResponse(status=200, text=html, url=fetch_url)}

    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(PORTAL_URL)

    assert result.platform == "cablecast"
    assert result.title == "Detroit City Council Formal Session 07-28-2026"
    assert result.date == "2026-07-28"
    assert result.jurisdiction == "Detroit, MI"
    assert result.video_url == REAL_VOD_URL
    assert result.video_format == "m3u8"
    # Real gap: vodTranscripts is a real field in the schema but was an
    # empty [] on every one of 36 real shows checked on this fixture page
    # -- no positive example to extract from yet.
    assert result.transcript_warnings == ["No transcript found for this event."]


async def test_resolve_forces_http_even_when_https_is_pasted():
    # The more natural thing for someone to paste/type -- resolve() must
    # never actually attempt the hanging HTTPS request.
    html = load_fixture("cablecast", "detroit_show_15323.html")
    fetch_url = "http://detroit-vod.cablecast.tv/internetchannel/show/15323?site=1"
    https_url = "https://detroit-vod.cablecast.tv/internetchannel/show/15323?site=1"

    routes = {fetch_url: FakeResponse(status=200, text=html, url=fetch_url)}

    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(https_url)

    assert result.source_url == https_url  # what the user actually pasted is preserved
    assert result.video_url == REAL_VOD_URL


async def test_resolve_missing_show_id_reports_error():
    url = "http://detroit-vod.cablecast.tv/internetchannel/watch-now?site=1"

    result = await CablecastAssetFinder().resolve(url)

    assert result.video_warnings == ["Could not find a show id in this Cablecast URL."]


async def test_resolve_show_not_found_in_page_reports_no_video():
    # A real page shape (has __remixContext) but the requested showId
    # genuinely isn't in it -- distinct from the missing-show-id case
    # above.
    url = "http://detroit-vod.cablecast.tv/internetchannel/show/999999999?site=1"
    html = load_fixture("cablecast", "detroit_show_15323.html")

    routes = {url: FakeResponse(status=200, text=html, url=url)}

    with mock_session(routes):
        result = await CablecastAssetFinder().resolve(url)

    assert result.video_url is None
    assert result.video_warnings == ["No video found for this meeting."]


def test_extract_show_id():
    assert CablecastAssetFinder._extract_show_id(PORTAL_URL) == 15323
    assert CablecastAssetFinder._extract_show_id("http://detroit-vod.cablecast.tv/internetchannel/watch-now") is None


def test_force_http():
    assert (
        CablecastAssetFinder._force_http("https://detroit-vod.cablecast.tv/internetchannel/show/1?site=1")
        == "http://detroit-vod.cablecast.tv/internetchannel/show/1?site=1"
    )
    assert (
        CablecastAssetFinder._force_http("http://detroit-vod.cablecast.tv/internetchannel/show/1?site=1")
        == "http://detroit-vod.cablecast.tv/internetchannel/show/1?site=1"
    )


def test_find_show_recursively_searches_nested_structure():
    tree = {"a": {"b": [{"showId": 1, "title": "wrong"}, {"showId": 2, "title": "right"}]}}
    found = CablecastAssetFinder._find_show(tree, 2)
    assert found == {"showId": 2, "title": "right"}
    assert CablecastAssetFinder._find_show(tree, 999) is None


def test_format_date_handles_iso_with_offset_and_invalid():
    assert CablecastAssetFinder._format_date("2026-07-28T00:00:00-04:00") == "2026-07-28"
    assert CablecastAssetFinder._format_date(None) is None
    assert CablecastAssetFinder._format_date("not-a-date") is None
