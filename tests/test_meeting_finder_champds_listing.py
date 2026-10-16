"""Meeting Finder lists ChampDS accounts (2026-10-02).

Live finding this covers: Meeting Finder said `no-meeting-nor-video` on
ChampDS accounts full of meetings -- Largo FL (every entry shape), and it
missed the downloadable video on Signal Mountain TN, Thompson's Station
TN and Yuba County CA. See BACKLOG_DONE.md's "ChampDS listing" entry.

Ryan, 2026-10-16: a VOD2-only recording (no download link) counts as
video and is a tier-3 find -- a transcript with no player that links back
to ChampDS. The lister no longer searches for a download link.

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
from app.platforms import passive_verify, queue_probe
from app.platforms.base import register
from app.platforms.champds import (
    _DEFAULT_LISTING_SEARCH_TERMS,
    ChampDSAssetFinder,
    MEDIA_CLASS_RECORDED,
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
from app.platforms.meeting_finder.resolve import (
    STREAM_ONLY_NOTE,
    _resolve_candidates_with_meeting,
    resolve_candidates,
)

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


# --- champds.py: the media class ----------------------------------------


async def test_list_archive_events_carries_the_media_class():
    routes = _search_routes("signalmountaintn", SIGNAL_MOUNTAIN_SEARCH)
    with mock_session(routes):
        items = await list_archive_events("signalmountaintn", limit=400)
    by_id = {i["event_id"]: i["media_class_id"] for i in items}
    # Real values: 366 is on live channel 5 (class 1), 363 has no media
    # (class 0), 365/152/151 are recordings (class 2).
    assert by_id == {366: 1, 365: 2, 363: 0, 152: 2, 151: 2}
    assert [i["event_id"] for i in items] == [366, 365, 363, 152, 151]


# --- Listing ---------------------------------------------------------


async def test_every_recording_is_a_video_candidate():
    """Signal Mountain's real shape: 365 and 151 are VOD2-only, 152 has a
    download link. All three recordings come back as video, newest first
    as listed, with no event call; 366 (live channel) and 363 (no media)
    are left out."""
    routes = _search_routes("signalmountaintn", SIGNAL_MOUNTAIN_SEARCH)
    with mock_session(routes):
        result = await listing._list_via_champds(
            "champds", "https://play.champds.com/signalmountaintn/live/5", 15
        )
    assert result.lister == "champds_archive"
    assert [c.url.rsplit("/", 1)[-1] for c in result.candidates] == [
        "365",
        "152",
        "151",
    ]
    assert all(c.has_video_hint is True for c in result.candidates)
    by_id = {c.url.rsplit("/", 1)[-1]: c for c in result.candidates}
    assert by_id["152"].title == "Regular Meeting"
    assert by_id["152"].date == "2024-07-15"
    assert result.note.endswith("5 events listed, 3 with a recording")


async def test_vod2_only_account_lists_its_recordings_as_video():
    """Largo FL's real shape: every event is a VOD2-only recording. Before
    2026-10-16 they came back as no-video meeting rows; now as video."""
    routes = _search_routes("largofl", LARGO_SEARCH)
    with mock_session(routes):
        result = await listing._list_via_champds(
            "champds", "https://play.champds.com/largofl", 15
        )
    assert [c.url.rsplit("/", 1)[-1] for c in result.candidates] == [
        "342",
        "341",
        "340",
    ]
    assert all(c.has_video_hint is True for c in result.candidates)
    assert result.candidates[0].title == "Largo Code Board"
    assert result.candidates[0].date == "2026-09-24"


async def test_account_with_no_recording_returns_no_video_meeting_rows():
    """Synthetic: Signal Mountain's real search response with its three
    recordings removed, leaving the real live-channel (366) and no-media
    (363) rows. No real ChampDS account with no recording at all has been
    captured. Every event goes back as a no-video meeting row."""
    raw = json.loads(_fixture("signalmountaintn_archive1_search_meeting_trimmed.json"))
    raw["SearchResult"]["Events"] = [
        e
        for e in raw["SearchResult"]["Events"]
        if e["EventMediaClassID"] != MEDIA_CLASS_RECORDED
    ]
    routes = _search_routes("signalmountaintn", {})
    routes["https://playapi.champds.com/signalmountaintn/archive/1/search/meeting"] = (
        FakeResponse(status=200, text=json.dumps(raw))
    )
    with mock_session(routes):
        result = await listing._list_via_champds(
            "champds", "https://play.champds.com/signalmountaintn", 15
        )
    assert [c.url.rsplit("/", 1)[-1] for c in result.candidates] == ["366", "363"]
    assert all(c.has_video_hint is False for c in result.candidates)
    assert result.note.endswith("2 events listed, 0 with a recording")


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
    with mock_session(routes):
        result = await listing._list_via_champds(
            "champds", "https://play.champds.com/fultoncoga/archive/2", 15
        )
    assert "fultoncoga archive 2" in result.note
    assert {int(c.url.rsplit("/", 1)[-1]) for c in result.candidates} == event_ids
    assert all(c.has_video_hint is True for c in result.candidates)


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


# --- Resolve: a VOD2-only recording is a tier-3 find (Ryan, 2026-10-16) --


def _accept_probe(seen):
    async def _probe(url, *, video_url=None, source_page_url=None, **kwargs):
        seen.append((url, video_url, source_page_url))
        return queue_probe.ProbeResult(
            url=url,
            platform="champds",
            probe_method="stub",
            duration_seconds=3600.0,
            date=None,
            size_bytes=None,
            verdict="accept",
            reason="",
            probe_seconds=0.0,
        )

    return _probe


LARGO_342_VOD2 = (
    "https://securestream10.champds.com"
    "/VOD/event/LargoFL/342/1790279417000/mFLut4YnLAfdp73IIs1o-Q/master.m3u8"
)


async def test_vod2_only_recording_resolves_as_tier_3(monkeypatch):
    """Largo's real event 342: a title and date, a VOD2 stream, no
    download link and no agenda. Before 2026-10-16 this was
    `meeting-without-video`; now the stream is probed (with the ChampDS
    page as the source, so the probe sends ChampDS's Referer) and the
    find is tier 3. The candidate is the ChampDS event page, which is the
    page's source link back to ChampDS."""
    seen = []
    monkeypatch.setattr(queue_probe, "probe_queue_entry", _accept_probe(seen))
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
        result, meeting = await _resolve_candidates_with_meeting(
            listed.candidates,
            FinderInput(url="https://play.champds.com/largofl", entry="list"),
        )
    assert result.outcome is None
    assert result.tier == 3
    assert result.platform == "champds"
    assert result.candidate.url == "https://play.champds.com/largofl/event/342"
    assert result.video_url == LARGO_342_VOD2
    assert STREAM_ONLY_NOTE in result.note
    assert seen[0] == (
        "https://play.champds.com/largofl/event/342",
        LARGO_342_VOD2,
        "https://play.champds.com/largofl/event/342",
    )
    # The page itself still has no player, and says where to watch.
    assert meeting.video_url is None
    assert meeting.source_url == "https://play.champds.com/largofl/event/342"
    assert meeting.server_media_url == LARGO_342_VOD2


async def test_listed_no_video_row_resolves_to_meeting_without_video():
    """Synthetic: Largo's real event 342 with its `MediaInfo` emptied (no
    stream, no download), as a row the lister marked no-video. It still
    gives `meeting-without-video` with that real row, the 2026-10-02 rule."""
    raw = json.loads(_fixture("largofl_event_342.json"))
    raw["MediaInfo"] = {"Captions": []}
    routes = {
        "https://playapi.champds.com/largofl/event/342": FakeResponse(
            status=200, text=json.dumps(raw)
        )
    }
    candidate = listing._champds_candidate(
        {
            "event_id": 342,
            "title": "Largo Code Board",
            "date": "2026-09-24",
            "event_url": "https://play.champds.com/largofl/event/342",
        },
        account_url="https://play.champds.com/largofl",
        has_video_hint=False,
    )
    register(ChampDSAssetFinder())
    with mock_session(routes):
        result = await resolve_candidates(
            [candidate],
            FinderInput(url="https://play.champds.com/largofl", entry="list"),
        )
    assert result.outcome == OUTCOME_MEETING_WITHOUT_VIDEO
    assert result.candidate.url == "https://play.champds.com/largofl/event/342"
    assert result.platform == "champds"


async def test_run_one_list_entry_finds_the_vod2_recording(monkeypatch):
    """End to end at `entry=list` on Largo's real shape: tier 3, naming
    the real row (url, title, date)."""
    from app.platforms.meeting_finder.runner import run_one

    monkeypatch.setattr(queue_probe, "probe_queue_entry", _accept_probe([]))
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
    assert row.outcome is None
    assert row.tier == 3
    assert row.meeting_url == "https://play.champds.com/largofl/event/342"
    assert row.meeting_title == "Largo Code Board"
    assert row.meeting_date == "2026-09-24"
    assert row.result_url == LARGO_342_VOD2
    assert row.platform == "champds"


async def test_the_given_event_page_comes_first():
    """Yuba County CA's live shape: the event page handed in (here Signal
    Mountain's real event 152, older than 365) is listed first, so a
    small limit still keeps it."""
    routes = _search_routes("signalmountaintn", SIGNAL_MOUNTAIN_SEARCH)
    with mock_session(routes):
        result = await listing._list_via_champds(
            "champds", "https://play.champds.com/signalmountaintn/event/152", 1
        )
    assert [c.url for c in result.candidates] == [
        "https://play.champds.com/signalmountaintn/event/152"
    ]
    assert result.candidates[0].has_video_hint is True


async def test_a_given_event_the_search_missed_is_unknown_not_no_video():
    """Synthetic id: an `/event/{id}` page whose event the search did not
    list keeps an unknown hint, never "no video"."""
    routes = _search_routes("signalmountaintn", SIGNAL_MOUNTAIN_SEARCH)
    with mock_session(routes):
        result = await listing._list_via_champds(
            "champds", "https://play.champds.com/signalmountaintn/event/9", 15
        )
    assert result.candidates[0].url.endswith("/event/9")
    assert result.candidates[0].has_video_hint is None
    assert [c.has_video_hint for c in result.candidates[1:]] == [True, True, True]
