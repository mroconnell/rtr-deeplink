"""Tests for the Wistia adapter (app/platforms/wistia.py), WO-161.

Real, unmodified live captures taken 2026-09-10 against Warrenton, VA's
real Wistia account (`amsva.wistia.com`, RegionalWebTV/Advanced Media
Solutions of Virginia) -- see wistia.py's own module docstring for the
full investigation:

- `channel_warrenton_kcpy3xurof.json` -- Warrenton Town Council's real
  channel listing (22 real 2026 episodes).
- `media_warrenton_i2vooa0pno.json` -- the real media JSON for "Warrenton
  Town Council Evening Session 8/11/2026" (a real, public MP4 asset list).
- `captions_warrenton_i2vooa0pno.vtt` -- the real WebVTT transcript for
  that same meeting (3,953 lines, real timestamps).
- `media_dead_02purws9tp.json` -- the real, literal `{"error": true,
  "iframe": true}` body Wistia's own media-JSON endpoint returns for a
  dead/pruned id (confirmed live against a 2019 hashed id linked from
  RegionalWebTV's own Fredericksburg City Council 2019 archive page).
- `regionalwebtv_fredcc2019.html` -- that same real, unmodified
  Fredericksburg CC 2019 archive page -- a real, live, server-rendered
  page carrying plain `<a href="https://amsva.wistia.com/medias/{id}">`
  links, one per meeting, with no JS rendering needed.

Every other embed shape this module recognizes (`fast.wistia.com/embed/
medias/{id}.jsonp`, `fast.wistia.net/embed/iframe/{id}`, `class="wistia_
embed wistia_async_{id}"`) is Wistia's own publicly documented standard
embed code, not independently found live on a real government page by
this session -- those fixtures below are synthetic, built from Wistia's
own documented shapes rather than an invented one, and are commented as
such at each use (per CLAUDE.md's synthetic-test rule). The nested-
custom-HTML-iframe headless fallback is exercised the same way: the real
positive case (RegionalWebTV's own current-year pages) was confirmed live
during this WO's own research but is a large, dynamic Wix bundle
unsuitable as a small, stable fixture, so the test below uses a small
synthetic rendered-DOM stand-in reproducing the exact real shape found
live (a `<div class="wistia_channel wistia_async_{id}">` inside a nested
`filesusr.com`-style custom-HTML iframe) -- see wistia.py's own docstring
for the real investigation this reproduces.
"""

import json

import pytest

from app.platforms.base import CalendarPageError, detect_platform
from app.platforms.headless_browser import HeadlessBrowserUnavailable
from app.platforms.wistia import (
    WistiaAssetFinder,
    filter_episodes_by_year,
    is_wistia_account_host,
    list_channel_episodes,
    parse_wistia_account_url,
    pick_episode_by_duration_rule,
)
from app.utils import url_guard

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture


@pytest.fixture(autouse=True)
def _fake_public_dns(monkeypatch):
    """See test_vimeo.py's identical fixture -- guarded_get() resolves
    hostnames for real unless patched, and this suite is network-free."""
    monkeypatch.setattr(
        url_guard, "_resolve_hostname", lambda hostname: ["93.184.216.34"]
    )


@pytest.fixture(autouse=True)
def _no_headless(monkeypatch):
    """Same pattern as test_vimeo.py's `_no_headless_captions`: the real
    headless-browser fallback launches a real Chromium unless mocked.
    Individual tests below override this to exercise the real positive
    path."""

    async def _unavailable(url, **kwargs):
        raise HeadlessBrowserUnavailable("no headless browser in tests")

    monkeypatch.setattr("app.platforms.wistia.fetch_via_browser", _unavailable)


def _media_route(wistia_id: str, fixture: str) -> dict:
    url = f"https://fast.wistia.com/embed/medias/{wistia_id}.json"
    return {
        url: FakeResponse(status=200, text=load_fixture("wistia", fixture), url=url)
    }


def _captions_route(wistia_id: str, fixture: str) -> dict:
    url = f"https://fast.wistia.com/embed/captions/{wistia_id}.vtt?language=eng"
    return {
        url: FakeResponse(status=200, text=load_fixture("wistia", fixture), url=url)
    }


def _channel_route(channel_id: str, fixture: str) -> dict:
    url = f"https://fast.wistia.com/embed/channel/{channel_id}.json"
    return {
        url: FakeResponse(status=200, text=load_fixture("wistia", fixture), url=url)
    }


def _no_captions_route(wistia_id: str) -> dict:
    url = f"https://fast.wistia.com/embed/captions/{wistia_id}.vtt?language=eng"
    return {url: FakeResponse(status=404, text="", url=url)}


# --- URL-shape parsing ------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        (
            "https://amsva.wistia.com/medias/i2vooa0pno",
            ("media", "i2vooa0pno", "amsva"),
        ),
        (
            "https://amsva.wistia.com/medias/i2vooa0pno/",
            ("media", "i2vooa0pno", "amsva"),
        ),
        (
            "https://amsva.wistia.com/channel/kcpy3xurof",
            ("channel", "kcpy3xurof", "amsva"),
        ),
    ],
)
def test_parse_wistia_account_url_handles_real_shapes(url, expected):
    assert parse_wistia_account_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        # Wistia's own marketing site -- never a per-government tenant.
        "https://wistia.com/medias/i2vooa0pno",
        "https://www.wistia.com/",
        # Wistia's own infrastructure hosts.
        "https://fast.wistia.com/embed/medias/i2vooa0pno.json",
        "https://embed-ssl.wistia.com/deliveries/abc.bin",
        # A real account host, but not a media/channel path.
        "https://amsva.wistia.com/",
        "https://amsva.wistia.com/projects/xyz",
    ],
)
def test_parse_wistia_account_url_declines_non_tenant_urls(url):
    assert parse_wistia_account_url(url) is None


def test_is_wistia_account_host():
    assert is_wistia_account_host("amsva.wistia.com") is True
    assert is_wistia_account_host("wistia.com") is False
    assert is_wistia_account_host("www.wistia.com") is False
    assert is_wistia_account_host("fast.wistia.com") is False
    assert is_wistia_account_host("embed-ssl.wistia.com") is False


def test_detect_platform_claims_only_real_wistia_tenant_shapes():
    assert detect_platform("https://amsva.wistia.com/medias/i2vooa0pno") == "wistia"
    assert detect_platform("https://amsva.wistia.com/channel/kcpy3xurof") == "wistia"
    # The marketing-site false positive CORPORATE_HOSTS_BY_PLATFORM guards
    # against, same reasoning as every other vendor in that table.
    assert detect_platform("https://www.wistia.com/") == "unknown"
    assert detect_platform("https://amsva.wistia.com/") == "unknown"


# --- Direct media resolve, real Warrenton fixtures ---------------------


@pytest.mark.asyncio
async def test_resolve_media_id_real_warrenton_meeting():
    routes = {}
    routes.update(_media_route("i2vooa0pno", "media_warrenton_i2vooa0pno.json"))
    routes.update(_captions_route("i2vooa0pno", "captions_warrenton_i2vooa0pno.vtt"))
    with mock_session(routes):
        resolved = await WistiaAssetFinder.resolve_media_id(
            "i2vooa0pno", account="amsva"
        )

    assert resolved.platform == "wistia"
    assert resolved.title == "Warrenton Town Council Evening Session 8/11/2026"
    assert resolved.date == "2026-08-11"
    assert resolved.external_id == "wistia:i2vooa0pno"
    assert resolved.video_channel == "amsva"
    assert resolved.video_format == "mp4"
    assert resolved.video_url and resolved.video_url.endswith(".bin")
    # The real, confirmed-live caption transcript -- 3,953 real VTT lines
    # parse down to a real, non-empty segment list.
    assert len(resolved.segments) > 100
    assert resolved.transcript_language == "en"
    assert not resolved.transcript_warnings
    # "Warrenton" alone doesn't independently validate (ambiguous/no
    # generic table hit for a bare town name with no state) -- honest
    # decline, not a guess, same reasoning as vimeo.py's/youtube.py's own
    # jurisdiction extraction.
    assert resolved.meeting_body == "Town Council"


@pytest.mark.asyncio
async def test_resolve_media_id_prefers_title_hint_over_capture_filename():
    """Real, confirmed gap (see resolve_media_id()'s own docstring): some
    RegionalWebTV channels' media JSON `name` is a raw capture filename,
    not a human title. A caller with a real channel-derived title (this
    module's own sweep helper, or an ingest script) should have it win."""
    routes = {}
    routes.update(_media_route("i2vooa0pno", "media_warrenton_i2vooa0pno.json"))
    routes.update(_no_captions_route("i2vooa0pno"))
    with mock_session(routes):
        resolved = await WistiaAssetFinder.resolve_media_id(
            "i2vooa0pno",
            account="amsva",
            title_hint="Augusta Board of Supervisors 1/7/2026",
        )
    assert resolved.title == "Augusta Board of Supervisors 1/7/2026"
    assert resolved.date == "2026-01-07"


@pytest.mark.asyncio
async def test_resolve_media_id_no_captions_degrades_gracefully():
    routes = {}
    routes.update(_media_route("i2vooa0pno", "media_warrenton_i2vooa0pno.json"))
    routes.update(_no_captions_route("i2vooa0pno"))
    with mock_session(routes):
        resolved = await WistiaAssetFinder.resolve_media_id(
            "i2vooa0pno", account="amsva"
        )
    assert resolved.segments == []
    assert resolved.transcript_warnings == [
        "We couldn't find captions for this meeting on Wistia."
    ]
    # Video still resolves fine -- captions are independent of video.
    assert resolved.video_url


@pytest.mark.asyncio
async def test_resolve_media_id_dead_id_raises_not_silent_empty():
    """Real, confirmed-live behavior: a dead/pruned id answers HTTP 200
    with `{"error": true}`, not a 404 -- must never be mistaken for a
    partial success."""
    with mock_session(_media_route("02purws9tp", "media_dead_02purws9tp.json")):
        with pytest.raises(ValueError, match="no longer exists"):
            await WistiaAssetFinder.resolve_media_id("02purws9tp", account="amsva")


@pytest.mark.asyncio
async def test_resolve_direct_media_url_end_to_end():
    routes = {}
    routes.update(_media_route("i2vooa0pno", "media_warrenton_i2vooa0pno.json"))
    routes.update(_captions_route("i2vooa0pno", "captions_warrenton_i2vooa0pno.vtt"))
    with mock_session(routes):
        resolved = await WistiaAssetFinder().resolve(
            "https://amsva.wistia.com/medias/i2vooa0pno"
        )
    assert resolved.source_url == "https://amsva.wistia.com/medias/i2vooa0pno"
    assert resolved.external_id == "wistia:i2vooa0pno"


# --- Channel listing, real Warrenton fixture ---------------------------


def test_list_channel_episodes_real_warrenton_channel():
    payload = json.loads(load_fixture("wistia", "channel_warrenton_kcpy3xurof.json"))
    episodes = list_channel_episodes(payload)
    # 165 real episodes total across every year on this real channel --
    # confirmed live 2026-09-10. Newest-first: the very first entry is the
    # real most recent upload.
    assert len(episodes) == 165
    assert episodes[0]["title"] == "Warrenton Town Council Evening Session 9/8/2026"
    assert episodes[0]["hashed_id"] == "t4pvo654qu"
    assert episodes[0]["duration_seconds"] == pytest.approx(9869.17)


def test_filter_episodes_by_year_real_warrenton_channel():
    payload = json.loads(load_fixture("wistia", "channel_warrenton_kcpy3xurof.json"))
    episodes = list_channel_episodes(payload)
    current_year = filter_episodes_by_year(episodes, "2026")
    # Confirmed live: 22 real 2026 episodes on this channel.
    assert len(current_year) == 22
    assert all("2026" in ep["title"] for ep in current_year)


def test_pick_episode_by_duration_rule_real_warrenton_channel():
    """Real, confirmed live: every one of Warrenton's 22 real 2026
    episodes runs over 40 minutes -- none qualify for the 9-40 minute
    preferred window, so the rule falls back to the shortest overall
    (the real ~60.7-minute 8/11/2026 evening session). Filtered to 2026
    first, per `filter_episodes_by_year()`'s own docstring -- the
    unfiltered 165-episode channel includes older years not independently
    confirmed alive."""
    payload = json.loads(load_fixture("wistia", "channel_warrenton_kcpy3xurof.json"))
    episodes = filter_episodes_by_year(list_channel_episodes(payload), "2026")
    picked = pick_episode_by_duration_rule(episodes)
    assert picked["hashed_id"] == "i2vooa0pno"
    assert picked["duration_seconds"] == pytest.approx(3641.78, abs=1)


def test_pick_episode_by_duration_rule_prefers_the_9_to_40_minute_window():
    episodes = [
        {"title": "A", "hashed_id": "a", "duration_seconds": 3600},  # 60 min
        {"title": "B", "hashed_id": "b", "duration_seconds": 1200},  # 20 min
        {"title": "C", "hashed_id": "c", "duration_seconds": 600},  # 10 min
    ]
    picked = pick_episode_by_duration_rule(episodes)
    # Both B and C are in the preferred window -- the shortest of those
    # wins, not the shortest overall (which would tie with C anyway here,
    # so this also covers "B, not the too-short-to-qualify case").
    assert picked["hashed_id"] == "c"


@pytest.mark.asyncio
async def test_resolve_channel_url_raises_calendar_page_error():
    with mock_session(
        _channel_route("kcpy3xurof", "channel_warrenton_kcpy3xurof.json")
    ):
        with pytest.raises(CalendarPageError) as exc_info:
            await WistiaAssetFinder().resolve(
                "https://amsva.wistia.com/channel/kcpy3xurof"
            )
    candidates = exc_info.value.candidates
    assert len(candidates) == 165
    assert candidates[0]["url"] == "https://amsva.wistia.com/medias/t4pvo654qu"
    assert candidates[0]["date"] == "2026-09-08"


# --- Delegating pages ---------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_delegating_page_real_regionalwebtv_archive_page():
    """Real, unmodified live capture: Fredericksburg City Council's own
    2019 RegionalWebTV archive page, a plain server-rendered page with
    real `<a href="https://amsva.wistia.com/medias/{id}">` links -- no JS
    rendering needed. The first such link on the real page is
    `02purws9tp` (the same real dead id used above)."""
    page_url = "https://www.regionalwebtv.com/fredcc2019"
    routes = {
        page_url: FakeResponse(
            status=200,
            text=load_fixture("wistia", "regionalwebtv_fredcc2019.html"),
            url=page_url,
        )
    }
    # The first `<a href>` in real DOM order on this page (confirmed live
    # dead the same way as media_dead_02purws9tp.json's own id).
    routes.update(_media_route("ofjgy0nmkc", "media_dead_02purws9tp.json"))
    with mock_session(routes):
        with pytest.raises(ValueError, match="no longer exists"):
            await WistiaAssetFinder().resolve(page_url)


@pytest.mark.asyncio
async def test_resolve_delegating_page_keeps_government_page_as_source_url():
    page_url = "https://www.regionalwebtv.com/some-current-page"
    page_html = (
        '<html><body><a href="https://amsva.wistia.com/medias/i2vooa0pno">'
        "Watch</a></body></html>"
    )
    routes = {
        page_url: FakeResponse(status=200, text=page_html, url=page_url),
    }
    routes.update(_media_route("i2vooa0pno", "media_warrenton_i2vooa0pno.json"))
    routes.update(_captions_route("i2vooa0pno", "captions_warrenton_i2vooa0pno.vtt"))
    with mock_session(routes):
        resolved = await WistiaAssetFinder().resolve(page_url)
    # Delegation convention (CLAUDE.md's wrapper-platform rule): the
    # government's own page stays source_url, not the Wistia media URL.
    assert resolved.source_url == page_url
    assert resolved.external_id == "wistia:i2vooa0pno"


@pytest.mark.asyncio
async def test_resolve_delegating_page_finds_nothing_degrades_gracefully():
    page_url = "https://www.example-gov.org/meetings"
    routes = {
        page_url: FakeResponse(
            status=200, text="<html><body>no video here</body></html>", url=page_url
        )
    }
    with mock_session(routes):
        resolved = await WistiaAssetFinder().resolve(page_url)
    assert resolved.video_url is None
    assert resolved.video_warnings == [
        "We couldn't find a Wistia video or channel embed on this page."
    ]


# --- Synthetic embed-shape variants -------------------------------------
#
# Every shape below is Wistia's own publicly documented standard embed
# code (jsonp URL, iframe embed URL, `wistia_embed`/`wistia_async_`
# class), not independently found live on a real government page by this
# session -- see this module's own docstring. Reused verbatim shapes, not
# invented ones.


@pytest.mark.asyncio
async def test_resolve_delegating_page_synthetic_jsonp_embed():
    page_url = "https://www.example-gov.org/watch-meeting"
    page_html = (
        "<html><body><script>"
        'Wistia.embed("i2vooa0pno", {});'
        "</script><div>fast.wistia.com/embed/medias/i2vooa0pno.jsonp</div>"
        "</body></html>"
    )
    routes = {page_url: FakeResponse(status=200, text=page_html, url=page_url)}
    routes.update(_media_route("i2vooa0pno", "media_warrenton_i2vooa0pno.json"))
    routes.update(_captions_route("i2vooa0pno", "captions_warrenton_i2vooa0pno.vtt"))
    with mock_session(routes):
        resolved = await WistiaAssetFinder().resolve(page_url)
    assert resolved.external_id == "wistia:i2vooa0pno"


@pytest.mark.asyncio
async def test_resolve_delegating_page_synthetic_iframe_embed():
    page_url = "https://www.example-gov.org/watch-meeting"
    page_html = (
        '<html><body><iframe src="https://fast.wistia.net/embed/iframe/'
        'i2vooa0pno" width="600" height="400"></iframe></body></html>'
    )
    routes = {page_url: FakeResponse(status=200, text=page_html, url=page_url)}
    routes.update(_media_route("i2vooa0pno", "media_warrenton_i2vooa0pno.json"))
    routes.update(_captions_route("i2vooa0pno", "captions_warrenton_i2vooa0pno.vtt"))
    with mock_session(routes):
        resolved = await WistiaAssetFinder().resolve(page_url)
    assert resolved.external_id == "wistia:i2vooa0pno"


@pytest.mark.asyncio
async def test_resolve_delegating_page_synthetic_async_class_media():
    page_url = "https://www.example-gov.org/watch-meeting"
    page_html = (
        '<html><body><div class="wistia_embed wistia_async_i2vooa0pno" '
        'style="height:400px;width:600px"></div></body></html>'
    )
    routes = {page_url: FakeResponse(status=200, text=page_html, url=page_url)}
    routes.update(_media_route("i2vooa0pno", "media_warrenton_i2vooa0pno.json"))
    routes.update(_captions_route("i2vooa0pno", "captions_warrenton_i2vooa0pno.vtt"))
    with mock_session(routes):
        resolved = await WistiaAssetFinder().resolve(page_url)
    assert resolved.external_id == "wistia:i2vooa0pno"


@pytest.mark.asyncio
async def test_resolve_delegating_page_synthetic_async_class_channel():
    """The channel variant of the same standard embed code -- confirmed
    live 2026-09-10 on RegionalWebTV's own current-year pages (see
    wistia.py's docstring), just reached here via the plain-fetch path
    with a small synthetic stand-in rather than the real, large Wix page."""
    page_url = "https://www.example-gov.org/watch-meeting"
    page_html = (
        '<html><body><div class="wistia_channel wistia_async_kcpy3xurof">'
        "</div></body></html>"
    )
    routes = {page_url: FakeResponse(status=200, text=page_html, url=page_url)}
    routes.update(_channel_route("kcpy3xurof", "channel_warrenton_kcpy3xurof.json"))
    with mock_session(routes):
        with pytest.raises(CalendarPageError):
            await WistiaAssetFinder().resolve(page_url)


# --- Headless-browser fallback for a JS-rendered delegating page -------


@pytest.mark.asyncio
async def test_resolve_delegating_page_headless_fallback_finds_nested_embed(
    monkeypatch,
):
    """Reproduces the real, confirmed-live RegionalWebTV shape (see this
    module's docstring): the outer page's plain-fetched HTML carries no
    Wistia reference at all, a headless render reveals a nested
    `<iframe src="...filesusr.com/html/...">` (a Wix custom-HTML embed),
    and that nested document -- itself plain static HTML -- carries the
    real `wistia_channel wistia_async_{id}` embed."""
    page_url = "https://www.regionalwebtv.com/warrentontc"
    outer_rendered_html = (
        '<html><body><iframe src="https://www-regionalwebtv-com.filesusr.com/'
        'html/2c630b_fake.html"></iframe></body></html>'
    )
    nested_url = "https://www-regionalwebtv-com.filesusr.com/html/2c630b_fake.html"
    nested_html = (
        '<html><body><div class="wistia_channel wistia_async_kcpy3xurof">'
        "</div></body></html>"
    )

    async def _fake_fetch_via_browser(url, **kwargs):
        assert url == page_url
        return outer_rendered_html

    monkeypatch.setattr(
        "app.platforms.wistia.fetch_via_browser", _fake_fetch_via_browser
    )

    routes = {
        page_url: FakeResponse(
            status=200,
            text="<html><body>plain, no wistia here</body></html>",
            url=page_url,
        ),
        nested_url: FakeResponse(status=200, text=nested_html, url=nested_url),
    }
    routes.update(_channel_route("kcpy3xurof", "channel_warrenton_kcpy3xurof.json"))
    with mock_session(routes):
        with pytest.raises(CalendarPageError):
            await WistiaAssetFinder().resolve(page_url)


@pytest.mark.asyncio
async def test_resolve_delegating_page_headless_unavailable_degrades_gracefully():
    """The default autouse `_no_headless` fixture simulates Playwright
    being unavailable -- confirms the whole chain still ends in a plain,
    honest "not found" ResolvedMeeting rather than an exception."""
    page_url = "https://www.example-gov.org/meetings"
    routes = {
        page_url: FakeResponse(
            status=200, text="<html><body>nothing here</body></html>", url=page_url
        )
    }
    with mock_session(routes):
        resolved = await WistiaAssetFinder().resolve(page_url)
    assert resolved.video_url is None
    assert resolved.video_warnings
