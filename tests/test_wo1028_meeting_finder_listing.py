"""Tests for `app/platforms/meeting_finder/listing.py` (WO-1028).

Synthetic per docs/MEETING_FINDER.md's List phase and CLAUDE.md's
synthetic-test rule: this module is pure orchestration (which lister ran,
in what order, what a `Candidate` looks like) on top of already
real-verified pieces -- `passive_verify.py`'s walkers have their own real
fixture-backed tests (`tests/test_passive_verify*.py`), and rtr-discovery's
`list_tenant()` has its own (`tests/test_list_one.py` in that repo). What
listing.py adds is the five-step pipeline and the fetch-injection wiring,
so these tests fake each dependency at its own seam (a fake registered
walker, a fake `discovery.list_one` module, a scripted `AssetFinder`) and
assert ordering/stop-at-first-hit/outcome behavior -- not platform
parsing, which is out of scope here.
"""

from __future__ import annotations

from typing import List
from unittest.mock import patch

import pytest

from app.platforms import passive_verify
from app.platforms.base import (
    AssetFinder,
    CalendarPageError,
    UnsupportedPlatformError,
    register,
)
from app.platforms.meeting_finder import listing
from app.platforms.meeting_finder.fetch import Fetcher
from app.platforms.meeting_finder.models import (
    OUTCOME_NO_MEETING_NOR_VIDEO,
    OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER,
)
from app.platforms.models import ResolvedMeeting


@pytest.fixture(autouse=True)
def _clean_walker_registry():
    """`passive_verify._LISTING_WALKERS` is a module-level dict, mutated
    by tests that register a fake walker under a made-up platform name --
    isolate each test from the others, same pattern `test_passive_verify.py`
    already relies on for its own `_FakeFinder`/`register()` fixtures."""
    passive_verify._ensure_walkers_registered()
    before = dict(passive_verify._LISTING_WALKERS)
    yield
    passive_verify._LISTING_WALKERS.clear()
    passive_verify._LISTING_WALKERS.update(before)


@pytest.fixture
def fetcher():
    return Fetcher(max_fetches=12, allow_headless=False, allow_wayback=False)


# --- Lister (a): passive_verify's registered walkers -------------------


@pytest.mark.asyncio
async def test_lister_a_uses_registered_passive_verify_walker(fetcher):
    async def fake_walker(hub_url: str) -> List[dict]:
        assert hub_url == "https://example.granicus.com/ViewPublisher.php?view_id=1"
        return [
            {
                "title": "City Council",
                "date": "2026-09-08",
                "url": "https://example.granicus.com/clip/1",
            },
            {
                "title": "Planning Commission",
                "date": "2026-09-01",
                "url": "https://example.granicus.com/clip/2",
            },
        ]

    passive_verify.register_listing_walker("granicus", fake_walker)
    result = await listing.list_account(
        "granicus", "https://example.granicus.com/ViewPublisher.php?view_id=1", fetcher
    )
    assert result.lister == "passive_verify:granicus"
    assert result.outcome is None
    assert len(result.candidates) == 2
    assert result.candidates[0].url == "https://example.granicus.com/clip/1"
    assert result.candidates[0].source_phase == "list"
    assert result.candidates[0].lister == "passive_verify:granicus"


@pytest.mark.asyncio
async def test_lister_a_routes_through_meeting_finder_fetcher(fetcher):
    """The walker calls passive_verify._fetch() itself -- with
    fetch_override() active, that must reach the Fetcher, not a real
    aiohttp GET, proving the injection point actually wires up."""
    calls: List[str] = []

    async def fake_fetch_via_fetcher(url: str, *, need_links: bool = True):
        calls.append(url)
        from app.platforms.meeting_finder.fetch import FetchResult

        return FetchResult(
            requested_url=url,
            final_url=url,
            status=200,
            html='<a href="/meeting/42">Council 2026-09-08</a>',
            access_mode="plain",
            outcome=None,
            challenge=False,
            wayback_timestamp=None,
            links_only=False,
            elapsed_ms=1,
        )

    async def walker_using_fetch(hub_url: str) -> List[dict]:
        html, final_url, err = await passive_verify._fetch(hub_url)
        assert err is None
        assert "meeting/42" in html
        return [
            {"title": "Council", "date": "2026-09-08", "url": final_url + "/meeting/42"}
        ]

    passive_verify.register_listing_walker("granicus", walker_using_fetch)
    with patch.object(fetcher, "fetch", side_effect=fake_fetch_via_fetcher):
        # `?view_id=1` -- WO-1030 added a Granicus-specific pre-step
        # (`_granicus_discover_view_id()`) that probes for a populated
        # view_id when the account URL doesn't already carry one (a real
        # Granicus hub root has no listing without it); a URL that
        # already has `view_id` skips that probe, so this test stays
        # focused on what it actually tests -- that lister (a) routes
        # through Meeting Finder's own Fetcher, not a real Granicus
        # semantics test.
        result = await listing.list_account(
            "granicus", "https://example.granicus.com/hub?view_id=1", fetcher
        )
    assert calls == ["https://example.granicus.com/hub?view_id=1"]
    assert result.candidates


@pytest.mark.asyncio
async def test_existing_passive_verify_caller_unaffected_by_override(fetcher):
    """docs/MEETING_FINDER.md's own promise: a caller that never sets the
    override (verify_hub()/every wo3xx sweep script) sees identical
    behavior. Simulates a concurrent plain call by NOT going through
    listing.py at all and confirming _fetch() falls through to the real
    default (mocked at the aiohttp layer, same as test_passive_verify.py)."""
    from aiohttp_mock import FakeResponse, mock_session

    with mock_session(
        {"https://plain.example.com/": FakeResponse(200, "<html>hi</html>")}
    ):
        html, final_url, err = await passive_verify._fetch("https://plain.example.com/")
    assert err is None
    assert html == "<html>hi</html>"


# --- Lister (b): rtr-discovery ------------------------------------------


class _FakeDiscoveryCandidate:
    def __init__(self, url, title, date, platform, has_video_hint):
        self.url = url
        self.title = title
        self.date = date
        self.platform = platform
        self.has_video_hint = has_video_hint


class _FakeListResult:
    def __init__(self, status, candidates=None, reason=None, params=None):
        self.status = status
        self.candidates = candidates or []
        self.reason = reason
        self.params = params or {}


class _FakeDiscoveryModule:
    STATUS_OK = "ok"
    STATUS_NOT_ENUMERABLE = "not-enumerable"
    STATUS_NO_ENUMERATOR = "no-enumerator"
    STATUS_ERROR = "error"

    def __init__(self, result):
        self._result = result
        self.calls = []

    async def list_tenant(self, platform, netloc, *, limit, params=None):
        self.calls.append((platform, netloc, limit, params))
        return self._result


@pytest.mark.asyncio
async def test_lister_b_used_when_no_passive_verify_walker(fetcher, monkeypatch):
    fake_result = _FakeListResult(
        "ok",
        candidates=[
            _FakeDiscoveryCandidate(
                "https://lacity.primegov.com/Portal/Meeting?meetingTemplateId=1",
                "City Council",
                "2026-09-10",
                "primegov",
                True,
            )
        ],
        params={"template_id": 1},
    )
    fake_module = _FakeDiscoveryModule(fake_result)
    monkeypatch.setattr(listing, "_load_discovery_module", lambda: fake_module)

    result = await listing.list_account(
        "primegov", "https://lacity.primegov.com/", fetcher
    )
    assert result.lister == "discovery:primegov"
    assert result.outcome is None
    assert len(result.candidates) == 1
    assert result.candidates[0].has_video_hint is True
    assert result.params == {"template_id": 1}
    assert fake_module.calls == [("primegov", "lacity.primegov.com", 15, None)]


@pytest.mark.asyncio
async def test_lister_b_skipped_when_passive_verify_has_a_walker(fetcher, monkeypatch):
    """docs/MEETING_FINDER.md's List (b) row: rtr-discovery is only for a
    platform passive_verify has NO walker for. civicclerk has one, so (b)
    must never even be consulted, even if (a) itself found nothing."""

    async def empty_walker(hub_url: str) -> List[dict]:
        return []

    passive_verify.register_listing_walker("civicclerk", empty_walker)

    called = {"n": 0}

    def fail_if_called():
        called["n"] += 1
        raise AssertionError("rtr-discovery should not be reached for civicclerk")

    monkeypatch.setattr(listing, "_load_discovery_module", fail_if_called)
    result = await listing.list_account(
        "civicclerk", "https://example.portal.civicclerk.com/", fetcher
    )
    assert called["n"] == 0
    assert result.outcome == OUTCOME_NO_MEETING_NOR_VIDEO


@pytest.mark.asyncio
async def test_lister_b_never_called_for_youtube_channel(fetcher, monkeypatch):
    called = {"n": 0}

    def fail_if_called():
        called["n"] += 1
        raise AssertionError("must never reach rtr-discovery for youtube_channel")

    monkeypatch.setattr(listing, "_load_discovery_module", fail_if_called)
    result = await listing.list_account(
        "youtube_channel", "https://www.youtube.com/@town", fetcher
    )
    assert called["n"] == 0
    assert result.outcome in (
        OUTCOME_NO_MEETING_NOR_VIDEO,
        OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER,
    )


@pytest.mark.asyncio
async def test_lister_b_degrades_with_a_note_when_rtr_discovery_unavailable(
    fetcher, monkeypatch
):
    monkeypatch.setattr(listing, "_load_discovery_module", lambda: None)
    monkeypatch.setattr(listing, "_discovery_import_failed", "no such directory")
    result = await listing.list_account(
        "primegov", "https://lacity.primegov.com/", fetcher
    )
    assert result.outcome in (
        OUTCOME_NO_MEETING_NOR_VIDEO,
        OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER,
    )
    assert "rtr-discovery unavailable" in result.note


# --- Lister (b), WO-1088: keyed-website tenant names --------------------
#
# A keyed website is one host shared by many customers, with a key in the
# address naming the customer (`app/utils/tenant_key.py`). Before WO-1088,
# `_list_via_discovery()` passed rtr-discovery's `list_tenant()` only
# `urlparse(account_url).netloc` -- the bare host, with the customer key
# thrown away. Every keyed platform's own rtr-discovery walker reads the
# key from `TenantRecord.tenant_key` and refuses (`TenantNotEnumerable`)
# when it's missing, so lister (b) always came back empty for a keyed
# tenant. These tests assert `_list_via_discovery()` now hands
# `list_tenant()` the full `host#key` tenant name for each of the five
# platforms whose rtr-discovery enumerator sets `tenant_keyed = True`
# (`~/Documents/rtr-discovery/discovery/enumerators/{champds,invintus,
# telvue,sliq_harmony,boxcast}.py`).
#
# ChampDS, Invintus and TelVue also each have their own passive_verify
# listing walker (lister a) -- `_list_via_discovery()`'s own early-return
# a few lines above the fix means lister (b) is never reached for them in
# production, walker registered or not. These three tests remove that
# platform's registration first, purely to exercise `_list_via_
# discovery()`'s own netloc-building in isolation; see the "kept, not
# redundant" reasoning in this module's own docstring update (WO-1088)
# and this PR's description for why those walkers stay.
#
# Every URL below is a real customer address, sourced from
# `app/utils/jurisdiction_data/tenant_overrides.csv` (cited per test).


@pytest.mark.asyncio
async def test_lister_b_champds_customer_reaches_list_tenant_with_key(
    fetcher, monkeypatch
):
    """Atlanta, GA on ChampDS -- tenant_overrides.csv's
    `play.champds.com,/atlantaga/,us:place:1304000,...` row (also the
    worked example in tenant_key.py's own module docstring)."""
    passive_verify._ensure_walkers_registered()
    passive_verify._LISTING_WALKERS.pop("champds", None)
    fake_module = _FakeDiscoveryModule(_FakeListResult("ok", candidates=[]))
    monkeypatch.setattr(listing, "_load_discovery_module", lambda: fake_module)

    await listing._list_via_discovery(
        "champds", "https://play.champds.com/atlantaga/", 15, None
    )
    assert fake_module.calls == [("champds", "play.champds.com#atlantaga", 15, None)]


@pytest.mark.asyncio
async def test_lister_b_invintus_customer_reaches_list_tenant_with_key(
    fetcher, monkeypatch
):
    """Leon County, FL on Invintus -- tenant_overrides.csv's
    `player.invintus.com,clientID=4853176732,us:county:12073,...` row
    (WO-1066)."""
    passive_verify._ensure_walkers_registered()
    passive_verify._LISTING_WALKERS.pop("invintus", None)
    fake_module = _FakeDiscoveryModule(_FakeListResult("ok", candidates=[]))
    monkeypatch.setattr(listing, "_load_discovery_module", lambda: fake_module)

    await listing._list_via_discovery(
        "invintus",
        "https://player.invintus.com/?clientID=4853176732",
        15,
        None,
    )
    assert fake_module.calls == [
        ("invintus", "player.invintus.com#4853176732", 15, None)
    ]


@pytest.mark.asyncio
async def test_lister_b_telvue_customer_reaches_list_tenant_with_key(
    fetcher, monkeypatch
):
    """City of Kalamazoo, MI on TelVue -- tenant_overrides.csv's
    `videoplayer.telvue.com,player/2bm0gzQWeVRzdCgvjXziXKwO3icSKh05/
    media/1041369,us:place:2642160,...` row (WO-1060). The org token
    keeps its exact case (`telvue_org_token()`'s own docstring)."""
    passive_verify._ensure_walkers_registered()
    passive_verify._LISTING_WALKERS.pop("telvue", None)
    fake_module = _FakeDiscoveryModule(_FakeListResult("ok", candidates=[]))
    monkeypatch.setattr(listing, "_load_discovery_module", lambda: fake_module)

    await listing._list_via_discovery(
        "telvue",
        "https://videoplayer.telvue.com/player/2bm0gzQWeVRzdCgvjXziXKwO3icSKh05/media/1041369",
        15,
        None,
    )
    assert fake_module.calls == [
        (
            "telvue",
            "videoplayer.telvue.com#2bm0gzQWeVRzdCgvjXziXKwO3icSKh05",
            15,
            None,
        )
    ]


@pytest.mark.asyncio
async def test_lister_b_sliq_harmony_customer_reaches_list_tenant_with_key(
    fetcher, monkeypatch
):
    """Arkansas Legislature on Sliq Harmony -- tenant_overrides.csv's
    `sg001-harmony.sliq.net,/00284/,us:state:05,...` row (WO-921). Sliq
    Harmony has no passive_verify walker, so this is the real production
    path, not just an isolation test -- lister (b) is the only lister
    that can list a Sliq Harmony tenant at all."""
    fake_module = _FakeDiscoveryModule(_FakeListResult("ok", candidates=[]))
    monkeypatch.setattr(listing, "_load_discovery_module", lambda: fake_module)

    await listing._list_via_discovery(
        "sliq_harmony", "https://sg001-harmony.sliq.net/00284/", 15, None
    )
    assert fake_module.calls == [
        ("sliq_harmony", "sg001-harmony.sliq.net#00284", 15, None)
    ]


@pytest.mark.asyncio
async def test_lister_b_boxcast_customer_reaches_list_tenant_with_key(
    fetcher, monkeypatch
):
    """City of Wilmington, OH on BoxCast -- tenant_overrides.csv's
    `boxcast.tv,channel=boxcast:x1jps4n28nlgtaozsv5y,us:place:3985792,...`
    row (WO-227), also cited in `app/platforms/boxcast.py`'s own module
    docstring and `tests/test_boxcast.py`. BoxCast has no passive_verify
    walker either, so this is also the real production path."""
    fake_module = _FakeDiscoveryModule(_FakeListResult("ok", candidates=[]))
    monkeypatch.setattr(listing, "_load_discovery_module", lambda: fake_module)

    await listing._list_via_discovery(
        "boxcast", "https://boxcast.tv/channel/x1jps4n28nlgtaozsv5y", 15, None
    )
    assert fake_module.calls == [
        ("boxcast", "boxcast.tv#x1jps4n28nlgtaozsv5y", 15, None)
    ]


# --- Lister (c): adapter's own CalendarPageError -----------------------


class _CalendarPageErrorFinder(AssetFinder):
    platform_name = "fake_calendar"

    async def resolve(self, url: str) -> ResolvedMeeting:
        raise CalendarPageError(
            "pick one",
            candidates=[
                {
                    "title": "Council 9/8",
                    "date": "2026-09-08",
                    "url": "https://fake.example.com/m/1",
                },
                {
                    "title": "Council 9/1",
                    "date": "2026-09-01",
                    "url": "https://fake.example.com/m/2",
                },
            ],
        )


@pytest.mark.asyncio
async def test_lister_c_reads_calendar_page_error_candidates(fetcher, monkeypatch):
    register(_CalendarPageErrorFinder())
    monkeypatch.setattr(
        listing, "_CALENDAR_PAGE_ERROR_PLATFORMS", frozenset({"fake_calendar"})
    )
    result = await listing.list_account(
        "fake_calendar", "https://fake.example.com/Calendar.aspx", fetcher
    )
    assert result.lister == "adapter_list"
    assert len(result.candidates) == 2
    assert result.candidates[0].url == "https://fake.example.com/m/1"


# --- Lister (d): adapter walks its own hub ------------------------------


class _HubResolvingFinder(AssetFinder):
    platform_name = "fake_hub"

    async def resolve(self, url: str) -> ResolvedMeeting:
        return ResolvedMeeting(
            platform="fake_hub",
            source_url="https://fake.example.com/newest-show",
            title="Newest Show",
            date="2026-09-08",
            video_url="https://fake.example.com/newest-show.mp4",
        )


@pytest.mark.asyncio
async def test_lister_d_wraps_adapter_hub_resolve_as_one_candidate(
    fetcher, monkeypatch
):
    register(_HubResolvingFinder())
    monkeypatch.setattr(listing, "_ADAPTER_HUB_PLATFORMS", frozenset({"fake_hub"}))
    result = await listing.list_account(
        "fake_hub", "https://fake.example.com/", fetcher
    )
    assert result.lister == "adapter_hub"
    assert len(result.candidates) == 1
    assert result.candidates[0].url == "https://fake.example.com/newest-show"
    assert result.candidates[0].has_video_hint is True


# --- Lister (e): generic same-platform link scan ------------------------


@pytest.mark.asyncio
async def test_lister_e_falls_back_to_generic_link_scan(fetcher):
    from app.platforms.meeting_finder.fetch import FetchResult

    async def fake_fetch(url: str, *, need_links: bool = True):
        return FetchResult(
            requested_url=url,
            final_url=url,
            status=200,
            html='<a href="/meeting/2026-09-08-council">Council</a>',
            access_mode="plain",
            outcome=None,
            challenge=False,
            wayback_timestamp=None,
            links_only=False,
            elapsed_ms=1,
        )

    with patch.object(fetcher, "fetch", side_effect=fake_fetch):
        result = await listing.list_account(
            "generic_platform_with_no_adapter_but_reachable",
            "https://town.example.gov/meetings",
            fetcher,
        )
    assert result.lister == "generic_link_scan"
    assert len(result.candidates) == 1
    assert "meeting/2026-09-08-council" in result.candidates[0].url


# --- Outcomes ------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_adapter_at_all_is_unsupported_platform_outcome(fetcher):
    async def fake_fetch(url: str, *, need_links: bool = True):
        from app.platforms.meeting_finder.fetch import FetchResult

        return FetchResult(
            requested_url=url,
            final_url=url,
            status=200,
            html="<html>nothing meeting-shaped here</html>",
            access_mode="plain",
            outcome=None,
            challenge=False,
            wayback_timestamp=None,
            links_only=False,
            elapsed_ms=1,
        )

    with patch.object(fetcher, "fetch", side_effect=fake_fetch):
        result = await listing.list_account(
            "totally_unregistered_platform_xyz", "https://nowhere.example.com/", fetcher
        )
    assert result.outcome == OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER
    assert result.candidates == []


@pytest.mark.asyncio
async def test_known_adapter_but_nothing_found_is_no_meeting_outcome(
    fetcher, monkeypatch
):
    class _EmptyFinder(AssetFinder):
        platform_name = "fake_empty"

        async def resolve(self, url: str) -> ResolvedMeeting:
            raise UnsupportedPlatformError(url=url, detected="fake_empty")

    register(_EmptyFinder())

    async def fake_fetch(url: str, *, need_links: bool = True):
        from app.platforms.meeting_finder.fetch import FetchResult

        return FetchResult(
            requested_url=url,
            final_url=url,
            status=200,
            html="<html>no links at all</html>",
            access_mode="plain",
            outcome=None,
            challenge=False,
            wayback_timestamp=None,
            links_only=False,
            elapsed_ms=1,
        )

    with patch.object(fetcher, "fetch", side_effect=fake_fetch):
        result = await listing.list_account(
            "fake_empty", "https://fake.example.com/", fetcher
        )
    assert result.outcome == OUTCOME_NO_MEETING_NOR_VIDEO


# --- Agenda-only fallback (conductor follow-up, 2026-09-23) -------------


@pytest.mark.asyncio
async def test_civicplus_agenda_only_fallback_uses_real_desoto_fixture(fetcher):
    """`tests/fixtures/civicplus/ks_desoto_agendacenter.html` is a real,
    raw-saved AgendaCenter page (already used by other civicplus tests) --
    33 real `tr.catAgendaRow` rows, none of which carries a real (i.e.
    `_is_real_video_link()`-qualifying) video link in its own `td.media`
    cell, confirmed by calling `CivicPlusAssetFinder()._find_candidate_
    rows()` on it directly. This exercises `_civicplus_agenda_only_
    fallback()` against that real, agenda-only-shaped page and checks it
    returns real rows with `has_video_hint=False` and a real agenda/
    packet link as `url`."""
    from tests.conftest import load_fixture

    html = load_fixture("civicplus", "ks_desoto_agendacenter.html")

    async def fake_fetch(url: str, *, need_links: bool = True):
        from app.platforms.meeting_finder.fetch import FetchResult

        return FetchResult(
            requested_url=url,
            final_url=url,
            status=200,
            html=html,
            access_mode="plain",
            outcome=None,
            challenge=False,
            wayback_timestamp=None,
            links_only=False,
            elapsed_ms=1,
        )

    with patch.object(fetcher, "fetch", side_effect=fake_fetch):
        rows = await listing._civicplus_agenda_only_fallback(
            "https://ks-desoto.civicplus.com/AgendaCenter", fetcher, limit=50
        )

    assert rows, "expected real agenda-only rows from the DeSoto fixture"
    assert all(row["has_video_hint"] is False for row in rows)
    assert all(row["url"] for row in rows)
    assert all("/AgendaCenter/" in row["url"] for row in rows)


@pytest.mark.asyncio
async def test_list_account_falls_back_to_agenda_only_when_civicplus_walker_finds_nothing(
    fetcher,
):
    """End-to-end: when the real `_civicplus_walker()` (lister a) finds no
    video-bearing candidates -- the real Cass County, MN shape confirmed
    live 2026-09-23 -- `list_account()` must not report
    `no-meeting-nor-video` for an account that plainly has real meetings.
    Fakes lister (a) empty (isolating this test from `_civicplus_walker()`'s
    own real-fixture coverage in test_passive_verify.py) and serves the
    real DeSoto fixture to the agenda-only fallback's own fetch."""
    from tests.conftest import load_fixture

    html = load_fixture("civicplus", "ks_desoto_agendacenter.html")

    async def empty_walker(hub_url: str) -> List[dict]:
        return []

    passive_verify.register_listing_walker("civicplus", empty_walker)

    async def fake_fetch(url: str, *, need_links: bool = True):
        from app.platforms.meeting_finder.fetch import FetchResult

        return FetchResult(
            requested_url=url,
            final_url=url,
            status=200,
            html=html,
            access_mode="plain",
            outcome=None,
            challenge=False,
            wayback_timestamp=None,
            links_only=False,
            elapsed_ms=1,
        )

    with patch.object(fetcher, "fetch", side_effect=fake_fetch):
        result = await listing.list_account(
            "civicplus",
            "https://ks-desoto.civicplus.com/AgendaCenter",
            fetcher,
            limit=5,
        )

    assert result.lister == "civicplus_agenda_only"
    assert result.outcome is None
    assert len(result.candidates) == 5
    assert all(c.has_video_hint is False for c in result.candidates)


# --- WO-1036: Swagit /views/{id} listed directly, not via bare-host discovery


@pytest.mark.asyncio
async def test_swagit_views_page_listed_directly(fetcher):
    # Real shape (rtr-discovery's SwagitEnumerator, confirmed live): a
    # /views/{id} page's own #video-table is server-rendered, unlike the
    # tab-slug pages (empty JS shells on *.new.swagit.com).
    from app.platforms.meeting_finder.fetch import FetchResult

    html = (
        '<table id="video-table">'
        '<tr><td><a href="/videos/1001">Commissioners Court<br>Sep 24, 2026</a></td></tr>'
        '<tr><td><a href="/videos/1000">Commissioners Court<br>Sep 10, 2026</a></td></tr>'
        "</table>"
    )

    async def fake_fetch(url: str, *, need_links: bool = True):
        assert url == "https://wisecountytx.new.swagit.com/views/908/"
        return FetchResult(
            requested_url=url,
            final_url=url,
            status=200,
            html=html,
            access_mode="plain",
            outcome=None,
            challenge=False,
            wayback_timestamp=None,
            links_only=False,
            elapsed_ms=1,
        )

    with patch.object(fetcher, "fetch", side_effect=fake_fetch):
        result = await listing.list_account(
            "swagit",
            "https://wisecountytx.new.swagit.com/views/908/",
            fetcher,
        )

    assert result.lister == "swagit_views_page"
    assert [c.url for c in result.candidates] == [
        "https://wisecountytx.new.swagit.com/videos/1001",
        "https://wisecountytx.new.swagit.com/videos/1000",
    ]
    assert result.candidates[0].date == "2026-09-24"
    assert all(c.has_video_hint for c in result.candidates)


@pytest.mark.asyncio
async def test_swagit_videos_url_is_its_own_single_candidate(fetcher):
    # A /videos/{id} URL is itself a specific video -- nothing to list.

    async def fail_if_called(*args, **kwargs):  # pragma: no cover
        raise AssertionError("should not fetch a bare /videos/{id} URL to list it")

    with patch.object(fetcher, "fetch", side_effect=fail_if_called):
        result = await listing.list_account(
            "swagit",
            "https://ferndalesd.new.swagit.com/videos/12",
            fetcher,
        )

    assert result.lister == "swagit_views_page"
    assert len(result.candidates) == 1
    assert result.candidates[0].url == "https://ferndalesd.new.swagit.com/videos/12"
    assert result.candidates[0].has_video_hint is True


@pytest.mark.asyncio
async def test_swagit_bare_tenant_root_falls_through_to_discovery(fetcher, monkeypatch):
    # No /views|videos/{id} path and no known view number -- lister (a2)
    # declines, falls through to lister (b) (rtr-discovery), same as before
    # this WO. (WO-1081: a tenant WITH a row in `swagit_views.csv` now lists
    # its known view instead -- Wise County TX has one, so this uses a
    # tenant that doesn't.)
    called = {}

    class _FakeCandidate:
        def __init__(self, url):
            self.url = url
            self.title = "Meeting"
            self.date = "2026-09-01"
            self.platform = "swagit"
            self.has_video_hint = True

    class _FakeResult:
        status = "ok"
        reason = None
        candidates = [
            _FakeCandidate("https://montgomerycountytx.new.swagit.com/videos/1")
        ]
        params = None

    class _FakeModule:
        STATUS_OK = "ok"

        @staticmethod
        async def list_tenant(platform, netloc, *, limit, params):
            called["netloc"] = netloc
            return _FakeResult()

    monkeypatch.setattr(listing, "_load_discovery_module", lambda: _FakeModule())

    result = await listing.list_account(
        "swagit", "https://montgomerycountytx.new.swagit.com/", fetcher
    )
    assert called["netloc"] == "montgomerycountytx.new.swagit.com"
    assert result.lister == "discovery:swagit"


# --- WO-1036 (Ryan confirmed): Cablecast gallery listed directly, before
# the tenant-root walker


@pytest.mark.asyncio
async def test_cablecast_gallery_listed_directly_before_tenant_root_walker(fetcher):
    # Real fixture (Old Saybrook's gallery/22, see test_cablecast.py's own
    # gallery tests) -- proves the gallery-scoped lister runs BEFORE
    # passive_verify's own tenant-root `_cablecast_walker`, which would
    # otherwise be tried first (lister a) and never see the gallery's own
    # scoping at all.
    from tests.conftest import load_fixture

    gallery_html = load_fixture("cablecast", "oldsaybrook_gallery_22.html")

    async def fail_if_called(hub_url: str):  # pragma: no cover
        raise AssertionError(
            "tenant-root _cablecast_walker should not run when the gallery "
            "lister already found candidates"
        )

    passive_verify.register_listing_walker("cablecast", fail_if_called)

    async def fake_fetch(url: str, *, need_links: bool = True):
        from app.platforms.meeting_finder.fetch import FetchResult

        assert (
            url == "http://reflect-vsctv.cablecast.tv/internetchannel/gallery/22?site=1"
        )
        return FetchResult(
            requested_url=url,
            final_url=url,
            status=200,
            html=gallery_html,
            access_mode="plain",
            outcome=None,
            challenge=False,
            wayback_timestamp=None,
            links_only=False,
            elapsed_ms=1,
        )

    with patch.object(fetcher, "fetch", side_effect=fake_fetch):
        result = await listing.list_account(
            "cablecast",
            "https://reflect-vsctv.cablecast.tv/internetchannel/gallery/22?site=1",
            fetcher,
        )

    assert result.lister == "cablecast_gallery"
    assert len(result.candidates) == 4
    assert all(c.has_video_hint for c in result.candidates)
    assert result.candidates[0].date == "2026-08-19"


@pytest.mark.asyncio
async def test_cablecast_non_gallery_url_falls_through_to_tenant_root_walker(fetcher):
    # A bare tenant URL (no /gallery/{id}) -- the new lister declines,
    # lister (a)'s own tenant-root walker still runs as before.
    async def fake_walker(hub_url: str):
        return [
            {
                "title": "City Council",
                "date": "2026-09-08",
                "url": "https://example.cablecast.tv/show/1",
            }
        ]

    passive_verify.register_listing_walker("cablecast", fake_walker)

    result = await listing.list_account(
        "cablecast", "https://example.cablecast.tv/", fetcher
    )
    assert result.lister == "passive_verify:cablecast"
