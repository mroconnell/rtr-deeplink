"""Tests for BoxCast channel-broadcast matching (app/platforms/boxcast.py).

Real shapes confirmed live 2026-08-29 via direct `curl` against three
independent real government BoxCast tenants (Wilmington OH, St. Louis
County MO, City of Hondo TX) -- see boxcast.py's own module docstring.
Wilmington's real data is used throughout: channel `x1jps4n28nlgtaozsv5y`,
broadcast `afjvqrnty4auvtywkunc` ("Wilmington City Council Regular
Meeting 8/6/2026", `starts_at` "2026-08-06T23:00:00Z",
`time_zone_offset` -240 -- i.e. 7pm Eastern on 2026-08-06, confirmed via
a real `/view` fetch returning a working signed HLS playlist).
"""

import json

from app.platforms import boxcast

from aiohttp_mock import FakeResponse, mock_session

CHANNEL_ID = "x1jps4n28nlgtaozsv5y"
SEARCH_URL = f"https://rest.boxcast.com/channels/{CHANNEL_ID}/broadcasts/_search?l=50"

# Real (trimmed) shape from a live `_search` response.
WILMINGTON_BROADCAST = {
    "id": "afjvqrnty4auvtywkunc",
    "name": "Wilmington City Council Regular Meeting 8/6/2026",
    "starts_at": "2026-08-06T23:00:00Z",
    "stops_at": "2026-08-07T00:25:00Z",
    "timeframe": "past",
    "time_zone_offset": -240,
    "recording_duration_seconds": 5043.23,
}
FUTURE_BROADCAST = {
    "id": "zzzfuture000000000000",
    "name": "Wilmington City Council Regular Meeting 12/1/2026",
    "starts_at": "2026-12-01T21:30:00Z",
    "stops_at": "2026-12-01T23:30:00Z",
    "timeframe": "future",
    "time_zone_offset": -240,
    "recording_duration_seconds": 0,
}
REAL_PLAYLIST_URL = (
    "https://play.boxcast.com/p/skd3evxqqhli7timl3qw/r/157.601s/5200.83s/"
    "v/all.m3u8?Expires=1788149760&Signature=abc&Key-Pair-Id=xyz"
)
VIEW_URL = f"https://rest.boxcast.com/broadcasts/{WILMINGTON_BROADCAST['id']}/view"


def _search_response(broadcasts):
    return FakeResponse(status=200, text=json.dumps({"results": broadcasts}))


async def test_find_channel_match_matches_by_local_calendar_date():
    routes = {
        SEARCH_URL: _search_response([WILMINGTON_BROADCAST, FUTURE_BROADCAST]),
        VIEW_URL: FakeResponse(
            status=200,
            text=json.dumps({"status": "recorded", "playlist": REAL_PLAYLIST_URL}),
        ),
    }
    with mock_session(routes):
        match = await boxcast.find_channel_match(
            CHANNEL_ID, "Wilmington City Council Regular Meeting", "2026-08-06"
        )

    assert match is not None
    assert match.broadcast_id == "afjvqrnty4auvtywkunc"
    assert match.video_url == REAL_PLAYLIST_URL


async def test_find_channel_match_uses_local_time_zone_not_bare_utc_date():
    # Real case this guards against: starts_at is already 11pm UTC on the
    # 6th (7pm Eastern) -- a bare UTC-date comparison against "2026-08-06"
    # would still happen to work here, but this pins the local-shift math
    # directly rather than relying on the search test above alone (see
    # _broadcast_local_date's own comment on why a later-starting meeting
    # would actually roll over).
    assert boxcast._broadcast_local_date(WILMINGTON_BROADCAST) == "2026-08-06"


async def test_find_channel_match_ignores_future_broadcasts():
    routes = {SEARCH_URL: _search_response([FUTURE_BROADCAST])}
    with mock_session(routes):
        match = await boxcast.find_channel_match(
            CHANNEL_ID, "Wilmington City Council Regular Meeting", "2026-12-01"
        )
    assert match is None


async def test_find_channel_match_disambiguates_same_day_meetings_by_title():
    budget = {
        **WILMINGTON_BROADCAST,
        "id": "budgetmeetingid00000000",
        "name": "Wilmington Budget Committee Meeting",
    }
    routes = {
        SEARCH_URL: _search_response([WILMINGTON_BROADCAST, budget]),
        VIEW_URL: FakeResponse(
            status=200,
            text=json.dumps({"status": "recorded", "playlist": REAL_PLAYLIST_URL}),
        ),
    }
    with mock_session(routes):
        match = await boxcast.find_channel_match(
            CHANNEL_ID, "Wilmington City Council Regular Meeting", "2026-08-06"
        )
    assert match is not None
    assert match.broadcast_id == "afjvqrnty4auvtywkunc"


async def test_find_channel_match_declines_an_unresolvable_same_day_tie():
    other = {
        **WILMINGTON_BROADCAST,
        "id": "othermeetingid000000000",
        "name": "Wilmington Regular Meeting",
    }
    routes = {SEARCH_URL: _search_response([WILMINGTON_BROADCAST, other])}
    with mock_session(routes):
        # "Special Session" shares no meaningful token with either real
        # broadcast name -- both score 0, a genuine tie, so this must
        # decline rather than guess.
        match = await boxcast.find_channel_match(
            CHANNEL_ID, "Special Session", "2026-08-06"
        )
    assert match is None


async def test_find_channel_match_declines_when_recording_not_yet_available():
    routes = {
        SEARCH_URL: _search_response([WILMINGTON_BROADCAST]),
        VIEW_URL: FakeResponse(status=200, text=json.dumps({"status": "processing"})),
    }
    with mock_session(routes):
        match = await boxcast.find_channel_match(
            CHANNEL_ID, "Wilmington City Council Regular Meeting", "2026-08-06"
        )
    assert match is None


async def test_find_channel_match_returns_none_on_search_failure():
    routes = {SEARCH_URL: FakeResponse(status=500)}
    with mock_session(routes):
        match = await boxcast.find_channel_match(
            CHANNEL_ID, "Wilmington City Council Regular Meeting", "2026-08-06"
        )
    assert match is None


async def test_find_channel_match_returns_none_without_meeting_date():
    match = await boxcast.find_channel_match(CHANNEL_ID, "Some Meeting", None)
    assert match is None
