"""Meeting Finder lists ChampDS accounts (2026-10-02).

Live finding this covers: Meeting Finder said `no-meeting-nor-video` on
ChampDS accounts full of meetings -- Largo FL (every entry shape), and it
missed the downloadable video on Signal Mountain TN, Thompson's Station
TN and Yuba County CA. See BACKLOG_DONE.md's "ChampDS listing" entry.

Every fixture under tests/fixtures/champds/ named for those customers is
a real `playapi.champds.com` response captured 2026-10-02, trimmed to a
few rows (search results) or to the fields the code reads (event
records). Values are untouched. The search terms other than "meeting"
are routed to the real Atlanta "no matches" response, so each test's
event list is exactly the trimmed real rows.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from aiohttp_mock import FakeResponse, mock_session
from app.platforms import passive_verify
from app.platforms.base import register
from app.platforms.champds import (
    _DEFAULT_LISTING_SEARCH_TERMS,
    ChampDSAssetFinder,
    MEDIA_CLASS_RECORDED,
    event_has_download,
    list_archive_events,
    parse_account_url,
)
from app.platforms.meeting_finder import listing
from app.platforms.meeting_finder.fetch import Fetcher
from app.platforms.meeting_finder.models import (
    OUTCOME_MEETING_WITHOUT_VIDEO,
    OUTCOME_NO_MEETING_NOR_VIDEO,
    FinderInput,
)
from app.platforms.meeting_finder.resolve import resolve_candidates

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "champds"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _search_routes(customer: str, fixtures: dict, archive_id: int = 1) -> dict:
    """`fixtures` maps a search term to its real (trimmed) response; every
    other default term gets the real "no matches" response."""
    no_matches = _fixture("atlantaga_archive1_search_no_matches.json")
    base = f"https://playapi.champds.com/{customer}/archive/{archive_id}/search/"
    routes = {
        base + term: FakeResponse(status=200, text=no_matches)
        for term in _DEFAULT_LISTING_SEARCH_TERMS
    }
    for term, name in fixtures.items():
        routes[base + term] = FakeResponse(status=200, text=_fixture(name))
    return routes


SIGNAL_MOUNTAIN_SEARCH = {
    "meeting": "signalmountaintn_archive1_search_meeting_trimmed.json"
}
# Largo's real "meeting" search holds 341 (City Commission Meeting); its
# real "board" search holds 342 (Code Board) and 340 (Planning Board).
LARGO_SEARCH = {
    "meeting": "largofl_archive1_search_meeting_trimmed.json",
    "board": "largofl_archive1_search_board_trimmed.json",
}


def _event_route(customer: str, event_id: int, fixture: str) -> dict:
    return {
        f"https://playapi.champds.com/{customer}/event/{event_id}": FakeResponse(
            status=200, text=_fixture(fixture)
        )
    }


# --- parse_account_url: every real shape seen 2026-10-02 -------------


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://play.champds.com/largofl", ("largofl", 1)),
        ("https://play.champds.com/largofl/", ("largofl", 1)),
        (
            "https://play.champds.com/thompsonsstationtn/archive/1",
            ("thompsonsstationtn", 1),
        ),
        ("https://play.champds.com/fultoncoga/archive/2", ("fultoncoga", 2)),
        ("https://play.champds.com/signalmountaintn/live/5", ("signalmountaintn", 1)),
        ("https://play.champds.com/yubacoca/event/31", ("yubacoca", 1)),
        (
            "https://playapi.champds.com/LargoFL/archive/1/search/meeting",
            ("largofl", 1),
        ),
        ("https://play.champds.com/CAPTION/elpasococo/2026-09/x.vtt", None),
        ("https://play.champds.com/DOWNLOAD-MEDIA/yubacoca/eventmainmedia/31", None),
        ("https://play.champds.com/", None),
        ("https://example.com/largofl", None),
    ],
)
def test_parse_account_url_shapes(url, expected):
    assert parse_account_url(url) == expected


# --- champds.py: media class and the download check -------------------


async def test_list_archive_events_carries_the_media_class():
    routes = _search_routes("signalmountaintn", SIGNAL_MOUNTAIN_SEARCH)
    with mock_session(routes):
        items = await list_archive_events("signalmountaintn", limit=400)
    by_id = {i["event_id"]: i["media_class_id"] for i in items}
    # Real values: 366 is on live channel 5 (class 1), 363 has no media
    # (class 0), 365/152/151 are recordings (class 2).
    assert by_id == {366: 1, 365: 2, 363: 0, 152: 2, 151: 2}
    assert [i["event_id"] for i in items] == [366, 365, 363, 152, 151]


async def test_event_has_download_true_false_and_unknown():
    routes = {
        **_event_route("signalmountaintn", 152, "signalmountaintn_event_152.json"),
        **_event_route("signalmountaintn", 151, "signalmountaintn_event_151.json"),
        "https://playapi.champds.com/signalmountaintn/event/9": FakeResponse(
            status=500, text="server error"
        ),
    }
    with mock_session(routes):
        assert await event_has_download("signalmountaintn", 152) is True
        assert await event_has_download("signalmountaintn", 151) is False
        assert await event_has_download("signalmountaintn", 9) is None


# --- Listing ---------------------------------------------------------


async def test_download_event_is_found_past_newer_stream_only_ones():
    """Signal Mountain's real shape: its newest recording (365) and 151
    are VOD2-only; 152 has the download link. Only 152 comes back, marked
    as video, even though two events are newer."""
    routes = {
        **_search_routes("signalmountaintn", SIGNAL_MOUNTAIN_SEARCH),
        **_event_route("signalmountaintn", 365, "signalmountaintn_event_365.json"),
        **_event_route("signalmountaintn", 152, "signalmountaintn_event_152.json"),
        **_event_route("signalmountaintn", 151, "signalmountaintn_event_151.json"),
    }
    with mock_session(routes):
        result = await listing._list_via_champds(
            "champds", "https://play.champds.com/signalmountaintn/live/5", 15
        )
    assert result.lister == "champds_archive"
    assert [c.url for c in result.candidates] == [
        "https://play.champds.com/signalmountaintn/event/152"
    ]
    assert result.candidates[0].has_video_hint is True
    assert result.candidates[0].title == "Regular Meeting"
    assert result.candidates[0].date == "2024-07-15"
    assert "5 events listed, 3 with a recording" in result.note
    assert "found 1" in result.note


async def test_no_download_returns_real_meeting_rows():
    """Largo FL's real shape: every event is a VOD2-only recording. Every
    listed event comes back as a real meeting row, newest first, marked
    no-video."""
    routes = {
        **_search_routes("largofl", LARGO_SEARCH),
        **_event_route("largofl", 342, "largofl_event_342.json"),
        **_event_route("largofl", 341, "largofl_event_341.json"),
        **_event_route("largofl", 340, "largofl_event_340.json"),
    }
    with mock_session(routes):
        result = await listing._list_via_champds(
            "champds", "https://play.champds.com/largofl", 15
        )
    assert [c.url.rsplit("/", 1)[-1] for c in result.candidates] == [
        "342",
        "341",
        "340",
    ]
    assert all(c.has_video_hint is False for c in result.candidates)
    assert result.candidates[0].title == "Largo Code Board"
    assert result.candidates[0].date == "2026-09-24"
    assert "found 0" in result.note


async def test_events_past_the_check_limit_stay_unknown(monkeypatch):
    """A recording the lister never checked is not claimed to be
    no-video -- its hint stays None."""
    monkeypatch.setattr(listing, "_CHAMPDS_DOWNLOAD_CHECK_LIMIT", 1)
    routes = {
        **_search_routes("largofl", LARGO_SEARCH),
        **_event_route("largofl", 342, "largofl_event_342.json"),
    }
    with mock_session(routes):
        result = await listing._list_via_champds(
            "champds", "https://play.champds.com/largofl", 15
        )
    assert [c.has_video_hint for c in result.candidates] == [False, None, None]


async def test_archive_page_lists_its_own_archive_id():
    """`/archive/2` searches archive 2, not archive 1. Real case: Fulton
    County GA's archive 2 ("Board of Commissioners"). Caution, measured
    live 2026-10-02: its archive-2 search returned the same 154 events as
    archive 1, so the id is passed through but changed nothing on the one
    real customer checked. Atlanta's `/archive/2` and `/archive/3`, linked
    from older data, now answer `{}`."""
    fixture = "fultoncoga_archive2_search_meeting_trimmed.json"
    routes = _search_routes("fultoncoga", {"meeting": fixture}, archive_id=2)
    raw = json.loads(_fixture(fixture))
    event_ids = {e["CustomerEventID"] for e in raw["SearchResult"]["Events"]}
    for event in raw["SearchResult"]["Events"]:
        if event["EventMediaClassID"] == MEDIA_CLASS_RECORDED:
            routes[
                f"https://playapi.champds.com/fultoncoga/event/{event['CustomerEventID']}"
            ] = FakeResponse(status=500, text="not captured")
    with mock_session(routes):
        result = await listing._list_via_champds(
            "champds", "https://play.champds.com/fultoncoga/archive/2", 15
        )
    assert "fultoncoga archive 2" in result.note
    assert {int(c.url.rsplit("/", 1)[-1]) for c in result.candidates} == event_ids
    # An unreadable event record is "unknown", never "no video".
    assert all(c.has_video_hint is None for c in result.candidates)


@pytest.fixture
def fetcher():
    return Fetcher(max_fetches=0, per_host_delay_s=0)


async def test_list_account_bare_slug_with_no_events_is_a_true_no_meeting(fetcher):
    """An account whose archive search finds nothing is a real
    `no-meeting-nor-video`, said with the reason -- and no other lister
    runs (the account page itself is a JavaScript shell)."""
    no_matches = _fixture("atlantaga_archive1_search_no_matches.json")
    routes = {
        f"https://playapi.champds.com/largofl/archive/1/search/{t}": FakeResponse(
            status=200, text=no_matches
        )
        for t in _DEFAULT_LISTING_SEARCH_TERMS
    }
    with mock_session(routes):
        result = await listing.list_account(
            "champds", "https://play.champds.com/largofl", fetcher
        )
    assert result.candidates == []
    assert result.outcome == OUTCOME_NO_MEETING_NOR_VIDEO
    assert "the archive search found no events" in result.note
    assert fetcher.fetches_used == 0


async def test_passive_verify_walker_lists_the_bare_account_page():
    """The walker's old pattern needed a slash after the customer, so
    `play.champds.com/largofl` listed nothing (confirmed live)."""
    passive_verify._ensure_walkers_registered()
    walker = passive_verify._LISTING_WALKERS["champds"]
    routes = _search_routes("largofl", LARGO_SEARCH)
    with mock_session(routes):
        rows = await walker("https://play.champds.com/largofl")
    assert [r["url"] for r in rows][:1] == [
        "https://play.champds.com/largofl/event/342"
    ]


# --- Resolve: a listed no-video row is a meeting-without-video --------


async def test_listed_no_video_rows_resolve_to_meeting_without_video():
    """Largo's real event 342 resolves with a title and date, a VOD2
    stream, and no agenda attachment. Before 2026-10-02 Resolve kept
    nothing and said `no-meeting-nor-video`; a lister-confirmed row now
    gives `meeting-without-video` with that real row."""
    routes = {
        **_search_routes("largofl", LARGO_SEARCH),
        **_event_route("largofl", 342, "largofl_event_342.json"),
        **_event_route("largofl", 341, "largofl_event_341.json"),
        **_event_route("largofl", 340, "largofl_event_340.json"),
    }
    register(ChampDSAssetFinder())
    with mock_session(routes):
        listed = await listing._list_via_champds(
            "champds", "https://play.champds.com/largofl", 15
        )
        result = await resolve_candidates(
            listed.candidates,
            FinderInput(url="https://play.champds.com/largofl", entry="list"),
        )
    assert result.outcome == OUTCOME_MEETING_WITHOUT_VIDEO
    assert result.candidate.url == "https://play.champds.com/largofl/event/342"
    assert result.candidate.title == "Largo Code Board"
    assert result.platform == "champds"
    assert "stream-only recording (VOD2)" in result.note


async def test_run_one_list_entry_names_the_meeting_row():
    """End to end at `entry=list` on Largo's real shape: the verdict is
    `meeting-without-video` and names the real row (url, title, date) --
    before 2026-10-02 these fields stayed blank for this outcome."""
    from app.platforms.meeting_finder.runner import run_one

    routes = {
        **_search_routes("largofl", LARGO_SEARCH),
        **_event_route("largofl", 342, "largofl_event_342.json"),
        **_event_route("largofl", 341, "largofl_event_341.json"),
        **_event_route("largofl", 340, "largofl_event_340.json"),
    }
    register(ChampDSAssetFinder())
    with mock_session(routes):
        row = await run_one(
            FinderInput(
                url="https://play.champds.com/largofl",
                entry="list",
                platform_hint="champds",
            ),
            run_id="test",
        )
    assert row.outcome == OUTCOME_MEETING_WITHOUT_VIDEO
    assert row.meeting_url == "https://play.champds.com/largofl/event/342"
    assert row.meeting_title == "Largo Code Board"
    assert row.meeting_date == "2026-09-24"
    assert row.platform == "champds"


async def test_the_given_event_page_is_checked_first(monkeypatch):
    """Yuba County CA's live shape: the event page handed in (here Signal
    Mountain's real download event 152) is checked before any newer
    recording, so a check limit of 1 still finds it."""
    monkeypatch.setattr(listing, "_CHAMPDS_DOWNLOAD_CHECK_LIMIT", 1)
    routes = {
        **_search_routes("signalmountaintn", SIGNAL_MOUNTAIN_SEARCH),
        **_event_route("signalmountaintn", 152, "signalmountaintn_event_152.json"),
    }
    with mock_session(routes):
        result = await listing._list_via_champds(
            "champds", "https://play.champds.com/signalmountaintn/event/152", 15
        )
    assert [c.url for c in result.candidates] == [
        "https://play.champds.com/signalmountaintn/event/152"
    ]
    assert result.candidates[0].has_video_hint is True
    assert "checked 1 recordings" in result.note
