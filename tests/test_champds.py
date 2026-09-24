"""Tests for CHAMP/ChampDS (app/platforms/champds.py).

Real API shapes confirmed live 2026-08-13 against 6 independent real
customers (Atlanta GA, Auburn NY, Gillette WY, Marlborough MA, Saco ME,
Worcester MA) -- see BACKLOG.md/BACKLOG_DONE.md. JSON fixtures below are
trimmed to just the fields the adapter reads, but every value is a real
one pulled from a real customer's actual API response, not invented.
"""

import json

from app.platforms.base import detect_platform
from app.platforms.champds import _STREAM_ONLY_WARNING, ChampDSAssetFinder
from app.platforms.media_probe import transcription_media_url

from aiohttp_mock import FakeResponse, mock_session

# Real shape: Atlanta, GA (play.champds.com/atlantaga/event/1227) --
# has MediaInfo.DownloadURL, the simpler, directly-playable case.
ATLANTA_URL = "https://play.champds.com/atlantaga/event/1227"
ATLANTA_API_URL = "https://playapi.champds.com/atlantaga/event/1227"
ATLANTA_JSON = json.dumps(
    {
        "Event": {
            "EventTitle": "Committee on Council Meeting",
            "EventDateTimeCustomerLocal": "2026-08-03 10:00:00",
        },
        "Customer": {"CustomerName": "Atlanta GA"},
        "Board": {"BoardName": "Committee on Council"},
        "MediaInfo": {
            "DownloadURL": "/DOWNLOAD-MEDIA/atlantaga/eventmainmedia/1227",
            "VOD2": "/VOD/event/AtlantaGA/1227/x/y/master.m3u8",
            "Captions": [],
        },
        "ServicesAndMachineInfo": {
            "8": {"ServiceTypeID": 8, "URLBase": "https://securestream10.champds.com"},
        },
    }
)

# Real shape: Marlborough, MA (play.champds.com/marlboroughma/event/806)
# -- no DownloadURL, only VOD2 (the majority real case, confirmed across
# 4 of the 6 customers checked), plus a real agenda attachment PDF.
MARLBOROUGH_URL = "https://play.champds.com/marlboroughma/event/806"
MARLBOROUGH_API_URL = "https://playapi.champds.com/marlboroughma/event/806"
MARLBOROUGH_JSON = json.dumps(
    {
        "Event": {
            "EventTitle": "City Council",
            "EventDateTimeCustomerLocal": "2024-06-17 19:00:00",
        },
        "Customer": {"CustomerName": "Marlborough MA"},
        "Board": {"BoardName": "City Council"},
        "MediaInfo": {
            "DownloadURL": None,
            "VOD2": "/VOD/event/MarlboroughMA/806/1718783802000/D33VeG9r-BDw8BsuIwReeA/master.m3u8",
            "Captions": [],
        },
        "ServicesAndMachineInfo": {
            "8": {"ServiceTypeID": 8, "URLBase": "https://securestream10.champds.com"},
        },
        "Agenda": {
            "Attachments": [
                {
                    "MediaFileName": "6f745edb1ed716b71e167ffbfde1b7087de6a258.pdf",
                    "MediaFileLocation": "2024-06",
                    "MediaNickName": "Packet",
                }
            ],
            "AgendaItems": [{"Title": "A. Call to Order"}],
        },
    }
)


def test_detect_platform_recognizes_champds_domain():
    assert detect_platform(ATLANTA_URL) == "champds"


async def test_resolve_uses_direct_download_url_when_present():
    routes = {
        ATLANTA_API_URL: FakeResponse(
            status=200, text=ATLANTA_JSON, url=ATLANTA_API_URL
        )
    }

    with mock_session(routes):
        result = await ChampDSAssetFinder().resolve(ATLANTA_URL)

    assert result.title == "Committee on Council Meeting"
    assert result.jurisdiction == "Atlanta, GA"
    assert result.date == "2026-08-03"
    assert (
        result.video_url
        == "https://play.champds.com/DOWNLOAD-MEDIA/atlantaga/eventmainmedia/1227"
    )
    assert result.video_format == "mp4"
    assert result.video_warnings == []


async def test_resolve_keeps_vod2_out_of_the_player():
    # Real, confirmed-live blocker: securestream10.champds.com enforces a
    # strict Referer: https://play.champds.com/ check on the VOD2 HLS
    # playlist and its segments -- embedding it directly in this site's
    # own <video>/hls.js would 406 in the browser (this site's referer,
    # not champds.com's own, would be sent). Metadata/agenda still comes
    # through. WO-1045: the stream goes to `server_media_url` (for the
    # transcription paths only) and the reader gets the stream-only
    # warning rather than "No video found".
    routes = {
        MARLBOROUGH_API_URL: FakeResponse(
            status=200, text=MARLBOROUGH_JSON, url=MARLBOROUGH_API_URL
        )
    }

    with mock_session(routes):
        result = await ChampDSAssetFinder().resolve(MARLBOROUGH_URL)

    assert result.video_url is None
    assert result.video_format is None
    assert result.server_media_url == (
        "https://securestream10.champds.com/VOD/event/MarlboroughMA/806/"
        "1718783802000/D33VeG9r-BDw8BsuIwReeA/master.m3u8"
    )
    assert result.video_warnings == [_STREAM_ONLY_WARNING]
    assert result.title == "City Council"
    assert result.jurisdiction == "Marlborough, MA"
    assert result.date == "2024-06-17"


async def test_resolve_extracts_agenda_link_from_real_attachment():
    # Real path confirmed live via play.champds.com's own cds.event.js
    # (getAttachmentPath()): /ATT/{customer}/{MediaFileLocation}/{MediaFileName}.
    routes = {
        MARLBOROUGH_API_URL: FakeResponse(
            status=200, text=MARLBOROUGH_JSON, url=MARLBOROUGH_API_URL
        )
    }

    with mock_session(routes):
        result = await ChampDSAssetFinder().resolve(MARLBOROUGH_URL)

    assert result.agenda_link == (
        "https://play.champds.com/ATT/marlboroughma/2024-06/6f745edb1ed716b71e167ffbfde1b7087de6a258.pdf"
    )


async def test_resolve_reports_no_transcript_when_captions_list_is_empty():
    # An empty MediaInfo.Captions -- the usual case, and all 6 customers
    # checked in 2026-08 -- means no caption request is made at all (an
    # unmocked one would fail this test).
    routes = {
        ATLANTA_API_URL: FakeResponse(
            status=200, text=ATLANTA_JSON, url=ATLANTA_API_URL
        )
    }

    with mock_session(routes):
        result = await ChampDSAssetFinder().resolve(ATLANTA_URL)

    assert result.segments == []
    assert result.transcript_warnings == ["No captions found for this ChampDS meeting."]


async def test_resolve_returns_error_for_a_url_with_no_event_id():
    url = "https://play.champds.com/atlantaga/"

    result = await ChampDSAssetFinder().resolve(url)

    assert result.video_warnings == [
        "Could not find a customer/event id in this ChampDS URL."
    ]


async def test_resolve_handles_api_failure_gracefully():
    routes = {ATLANTA_API_URL: FakeResponse(status=500, text="", url=ATLANTA_API_URL)}

    with mock_session(routes):
        result = await ChampDSAssetFinder().resolve(ATLANTA_URL)

    assert result.video_warnings == [
        "Could not reach the ChampDS API for this meeting."
    ]


def test_extract_jurisdiction_splits_city_and_state():
    # Real shape: "Atlanta GA" -- space-separated, not comma-separated,
    # unlike most other adapters' free-text extraction.
    result = ChampDSAssetFinder._extract_jurisdiction("Atlanta GA", ATLANTA_URL)
    assert result == "Atlanta, GA"


def test_extract_jurisdiction_leaves_unrecognized_shapes_unchanged():
    result = ChampDSAssetFinder._extract_jurisdiction(
        "Some Regional Authority", ATLANTA_URL
    )
    assert result == "Some Regional Authority"


# --- why the API call failed, which used to be unrecoverable -------------
#
# Every failure path collapsed into a bare `return None` with no logging,
# and the caller turned that into one fixed sentence. ChampDS's "symptom
# B" -- instant 0.2s failures -- therefore survived two separate
# investigations unexplained, because diagnosing it needed a manual
# re-curl of the API afterwards. These tests pin the distinctions that
# make it diagnosable from the logs alone.


async def _reason_for(response) -> str:
    """The `reason` _fetch_json() reports for one canned API response."""
    import aiohttp

    with mock_session({ATLANTA_API_URL: response}):
        async with aiohttp.ClientSession() as session:
            data, reason = await ChampDSAssetFinder._fetch_json(
                session, ATLANTA_API_URL
            )
    assert data is None
    return reason


async def test_a_404_is_reported_as_a_404():
    """The API answered and declined -- a meeting that no longer exists.
    Nothing like a rate limit, and it used to be indistinguishable."""
    reason = await _reason_for(FakeResponse(status=404, text="Event not found"))
    assert "404" in reason
    assert "Event not found" in reason


async def test_a_rate_limit_is_distinguishable_from_everything_else():
    """The hypothesis symptom B actually rests on. A 429 has to be
    visible as a 429, or 'is ChampDS limiting us' stays unanswerable."""
    reason = await _reason_for(FakeResponse(status=429, text="Too Many Requests"))
    assert "429" in reason


async def test_a_server_error_carries_its_body_snippet():
    reason = await _reason_for(FakeResponse(status=503, text="upstream unavailable"))
    assert "503" in reason and "upstream" in reason


async def test_a_200_that_is_not_json_says_so():
    """Confirmed-real risk here: the ChampDS API serves JSON as
    `text/html`, so a login/error page would arrive as a perfectly good
    200 and only fail at the parse. That must not read as 'unreachable'."""
    reason = await _reason_for(FakeResponse(status=200, text="<html>nope</html>"))
    assert "200" in reason
    assert "not JSON" in reason


async def test_a_timeout_is_reported_as_a_timeout():
    """A timeout and an instant non-200 are the two symptoms that were
    conflated in the first place -- 'we never got an answer' vs 'the API
    answered and said no'."""
    import asyncio

    import aiohttp

    class _TimeoutResponse(FakeResponse):
        async def __aenter__(self):
            raise asyncio.TimeoutError

    with mock_session({ATLANTA_API_URL: _TimeoutResponse()}):
        async with aiohttp.ClientSession() as session:
            data, reason = await ChampDSAssetFinder._fetch_json(
                session, ATLANTA_API_URL
            )

    assert data is None
    assert "timed out" in reason


async def test_a_successful_fetch_reports_no_reason():
    import aiohttp

    with mock_session({ATLANTA_API_URL: FakeResponse(status=200, text=ATLANTA_JSON)}):
        async with aiohttp.ClientSession() as session:
            data, reason = await ChampDSAssetFinder._fetch_json(
                session, ATLANTA_API_URL
            )

    assert reason is None
    assert data["Event"]["EventTitle"] == "Committee on Council Meeting"


async def test_the_reader_facing_warning_stays_generic(caplog):
    """A status code is not useful to someone looking for a meeting, so
    the page copy is unchanged -- the diagnosis goes to the log, which is
    where it was missing."""
    with mock_session({ATLANTA_API_URL: FakeResponse(status=429, text="slow down")}):
        with caplog.at_level("WARNING"):
            result = await ChampDSAssetFinder().resolve(ATLANTA_URL)

    assert result.video_warnings == [
        "Could not reach the ChampDS API for this meeting."
    ]
    assert "429" in caplog.text
    assert ATLANTA_API_URL in caplog.text


# WO-308 (2026-09-12): the missing "list what's on this customer" step.
# See app/platforms/champds.py's module comment above `list_archive_events`
# for the full investigation. Fixtures are the real first 5 events of a
# real 169/500-result response from Atlanta GA (`archive_id=1`, the same
# real customer the fetch-diagnostics tests above already use), trimmed
# the same way telvue's playlist-item fixture is trimmed to its first 3
# of 50 real items -- every value is real, only the row count is cut.
from app.platforms.champds import list_archive_events  # noqa: E402

CHAMPDS_FIXTURES_DIR = "champds"


def _load_champds_fixture(name: str) -> str:
    import pathlib

    return (
        pathlib.Path(__file__).parent / "fixtures" / CHAMPDS_FIXTURES_DIR / name
    ).read_text(encoding="utf-8")


ATLANTA_COUNCIL_SEARCH_URL = (
    "https://playapi.champds.com/atlantaga/archive/1/search/council"
)
ATLANTA_MEETING_SEARCH_URL = (
    "https://playapi.champds.com/atlantaga/archive/1/search/meeting"
)
ATLANTA_BOARD_SEARCH_URL = (
    "https://playapi.champds.com/atlantaga/archive/1/search/board"
)


async def test_list_archive_events_real_atlanta_fixture():
    """A single real search term returns real events, newest first, with
    `event_url` ready to feed into `ChampDSAssetFinder.resolve()`."""
    fixture = _load_champds_fixture("atlantaga_archive1_search_council.json")
    routes = {
        ATLANTA_COUNCIL_SEARCH_URL: FakeResponse(status=200, text=fixture),
    }

    with mock_session(routes):
        items = await list_archive_events("atlantaga", search_terms=("council",))

    assert len(items) == 5  # the trimmed real fixture's event count
    assert items[0]["event_id"] == 1261
    assert items[0]["title"] == "Atlanta City Council Meeting"
    assert items[0]["date"] == "2026-09-08"
    assert items[0]["event_url"] == "https://play.champds.com/atlantaga/event/1261"


async def test_list_archive_events_sorts_by_date_not_api_order():
    """Real, confirmed-live quirk: Atlanta's own "meeting" search does not
    come back in date order -- event 1249 (2026-08-17) sits ahead of 1259
    (2026-09-03) and 1257 (2026-09-01) in the raw fixture. This function
    must always re-sort by EventDateTimeLocal, never trust API order."""
    fixture = _load_champds_fixture("atlantaga_archive1_search_meeting.json")
    raw = json.loads(fixture)
    raw_ids_in_api_order = [e["CustomerEventID"] for e in raw["SearchResult"]["Events"]]
    assert raw_ids_in_api_order == [1261, 1260, 1249, 1259, 1257]  # confirms the quirk

    routes = {
        ATLANTA_MEETING_SEARCH_URL: FakeResponse(status=200, text=fixture),
    }

    with mock_session(routes):
        items = await list_archive_events("atlantaga", search_terms=("meeting",))

    dates = [item["event_datetime_local"] for item in items]
    assert dates == sorted(dates, reverse=True)
    assert [item["event_id"] for item in items] == [1261, 1260, 1259, 1257, 1249]


async def test_list_archive_events_dedupes_across_search_terms():
    """Events 1261/1260 appear in both the real "council" and "meeting"
    fixtures (both are real city-council meetings) -- a customer's
    events must come back once each, not once per matching term."""
    council_fixture = _load_champds_fixture("atlantaga_archive1_search_council.json")
    meeting_fixture = _load_champds_fixture("atlantaga_archive1_search_meeting.json")
    routes = {
        ATLANTA_COUNCIL_SEARCH_URL: FakeResponse(status=200, text=council_fixture),
        ATLANTA_MEETING_SEARCH_URL: FakeResponse(status=200, text=meeting_fixture),
    }

    with mock_session(routes):
        items = await list_archive_events(
            "atlantaga", search_terms=("council", "meeting")
        )

    event_ids = [item["event_id"] for item in items]
    assert len(event_ids) == len(set(event_ids))  # no duplicates
    assert 1261 in event_ids and event_ids.count(1261) == 1


async def test_list_archive_events_skips_a_too_short_search_term():
    """Confirmed live: a search term under 4 characters (or blank) comes
    back as HTTP 200 with `{"Error": "SEARCH_TOO_SHORT"}`, not a 4xx --
    this must be skipped, not raise or get treated as zero real events
    from an otherwise-working term."""
    error_fixture = _load_champds_fixture(
        "atlantaga_archive1_search_too_short_error.json"
    )
    council_fixture = _load_champds_fixture("atlantaga_archive1_search_council.json")
    routes = {
        ATLANTA_BOARD_SEARCH_URL: FakeResponse(status=200, text=error_fixture),
        ATLANTA_COUNCIL_SEARCH_URL: FakeResponse(status=200, text=council_fixture),
    }

    with mock_session(routes):
        items = await list_archive_events(
            "atlantaga", search_terms=("board", "council")
        )

    assert len(items) == 5  # only the council fixture's real events came through


async def test_list_archive_events_a_failed_term_does_not_lose_the_others():
    """A term whose request 500s (or times out, or connection-errors)
    must not take down the whole listing -- the other terms still run."""
    council_fixture = _load_champds_fixture("atlantaga_archive1_search_council.json")
    routes = {
        ATLANTA_BOARD_SEARCH_URL: FakeResponse(status=500, text="server error"),
        ATLANTA_COUNCIL_SEARCH_URL: FakeResponse(status=200, text=council_fixture),
    }

    with mock_session(routes):
        items = await list_archive_events(
            "atlantaga", search_terms=("board", "council")
        )

    assert len(items) == 5


async def test_list_archive_events_no_matches_returns_empty_list():
    fixture = _load_champds_fixture("atlantaga_archive1_search_no_matches.json")
    routes = {
        ATLANTA_COUNCIL_SEARCH_URL: FakeResponse(status=200, text=fixture),
    }

    with mock_session(routes):
        items = await list_archive_events("atlantaga", search_terms=("council",))

    assert items == []


async def test_list_archive_events_respects_limit():
    fixture = _load_champds_fixture("atlantaga_archive1_search_council.json")
    routes = {
        ATLANTA_COUNCIL_SEARCH_URL: FakeResponse(status=200, text=fixture),
    }

    with mock_session(routes):
        items = await list_archive_events(
            "atlantaga", search_terms=("council",), limit=2
        )

    assert len(items) == 2
    assert items[0]["event_id"] == 1261
    assert items[1]["event_id"] == 1260


# WO-1045 (2026-09-24): the two gaps found live that day. Fixtures are the
# real playapi.champds.com responses for these three meetings, trimmed to
# the fields the adapter reads (Event title/date, CustomerName, BoardName,
# Agenda.Attachments, MediaInfo and ServicesAndMachineInfo whole). The
# caption fixture is the first 40 cues of El Paso's real 101 KB VTT file,
# fetched from the /CAPTION/ path the adapter builds.
COBB_URL = "https://play.champds.com/cobbcoga/event/155"
GWINNETT_URL = "https://play.champds.com/gwinnettcoga/event/356"
EL_PASO_URL = "https://play.champds.com/elpasococo/event/164"
EL_PASO_CAPTION_URL = (
    "https://play.champds.com/CAPTION/elpasococo/2026-09/"
    "e6ceecf86eb48b6c349cb46adb72b3fd73862d46.vtt"
)


def _api_route(customer: str, event_id: int, fixture: str) -> dict:
    api_url = f"https://playapi.champds.com/{customer}/event/{event_id}"
    return {
        api_url: FakeResponse(
            status=200, text=_load_champds_fixture(fixture), url=api_url
        )
    }


async def test_download_disabled_customer_gets_stream_for_transcription_only():
    # Cobb County GA: no DownloadURL, only VOD2 + an .mp4 MediaPath. The
    # MediaPath 404s on every host tried; VOD2 plays server-side with
    # ChampDS's own Referer (ffprobe read 6,197 s live). So: nothing in
    # the player, the stream in server_media_url, and a warning that says
    # the video exists.
    with mock_session(_api_route("cobbcoga", 155, "cobbcoga_event_155.json")):
        result = await ChampDSAssetFinder().resolve(COBB_URL)

    assert result.video_url is None
    assert result.video_format is None
    assert result.server_media_url == (
        "https://securestream10.champds.com/VOD/event/CobbCoGA/155/"
        "1788977097000/1o3BB_6OF2yCFDiWWL9CXA/master.m3u8"
    )
    assert result.video_warnings == [_STREAM_ONLY_WARNING]
    assert "No video found" not in " ".join(result.video_warnings)
    assert result.title == "Board of Commissioners"
    assert result.date == "2026-09-08"
    # The transcription paths pick the stream up through the shared helper.
    assert transcription_media_url(result) == result.server_media_url


async def test_second_download_disabled_customer_same_shape():
    # Gwinnett County GA: an independent second real customer with the
    # same shape, so the rule isn't fitted to one tenant.
    with mock_session(_api_route("gwinnettcoga", 356, "gwinnettcoga_event_356.json")):
        result = await ChampDSAssetFinder().resolve(GWINNETT_URL)

    assert result.video_url is None
    assert result.server_media_url == (
        "https://securestream10.champds.com/VOD/event/GwinnettCoGA/356/"
        "1789498072000/MJOFEzzY9p_9uNdXuCNheA/master.m3u8"
    )
    assert result.video_warnings == [_STREAM_ONLY_WARNING]


async def test_vod2_without_a_stream_host_is_still_no_video():
    # Synthetic, built on the real Cobb response: with ServicesAndMachine
    # Info removed there is no URLBase to join VOD2 to. No host is
    # guessed, so this stays an honest "No video found". No real customer
    # missing that block has been seen.
    raw = json.loads(_load_champds_fixture("cobbcoga_event_155.json"))
    del raw["ServicesAndMachineInfo"]
    api_url = "https://playapi.champds.com/cobbcoga/event/155"
    routes = {api_url: FakeResponse(status=200, text=json.dumps(raw), url=api_url)}

    with mock_session(routes):
        result = await ChampDSAssetFinder().resolve(COBB_URL)

    assert result.server_media_url is None
    assert result.video_warnings == ["No video found for this ChampDS meeting."]
    assert transcription_media_url(result) is None


async def test_populated_captions_become_transcript_segments():
    # El Paso County CO: MediaInfo.Captions lists one English VTT. It
    # used to be ignored (0 segments); it is now read.
    routes = _api_route("elpasococo", 164, "elpasococo_event_164.json")
    routes[EL_PASO_CAPTION_URL] = FakeResponse(
        status=200,
        text=_load_champds_fixture("elpasococo_event_164_captions_first40.vtt"),
        url=EL_PASO_CAPTION_URL,
    )

    with mock_session(routes):
        result = await ChampDSAssetFinder().resolve(EL_PASO_URL)

    assert len(result.segments) == 40
    first = result.segments[0]
    assert first.start == 358.099
    assert first.end == 362.355
    assert first.text.startswith("Good morning and welcome to the Board of")
    assert result.transcript_language == "en"
    assert result.transcript_warnings == []
    # El Paso also has a DownloadURL, so the player gets the plain MP4 and
    # no server-only stream is set.
    assert result.video_url == (
        "https://play.champds.com/DOWNLOAD-MEDIA/elpasococo/eventmainmedia/164"
    )
    assert result.server_media_url is None
    assert transcription_media_url(result) == result.video_url


async def test_a_failed_caption_fetch_keeps_the_video_and_says_so():
    # Synthetic failure on the real El Paso response: the caption file
    # 404s. The video must still come through, and the warning must say
    # captions exist but couldn't be read -- not "No captions found".
    routes = _api_route("elpasococo", 164, "elpasococo_event_164.json")
    routes[EL_PASO_CAPTION_URL] = FakeResponse(
        status=404, text="Not Found", url=EL_PASO_CAPTION_URL
    )

    with mock_session(routes):
        result = await ChampDSAssetFinder().resolve(EL_PASO_URL)

    assert result.segments == []
    assert result.video_url is not None
    assert result.transcript_warnings == [
        "ChampDS lists captions for this meeting, but we couldn't read them."
    ]


def test_caption_url_prefers_english_when_several_are_listed():
    # Synthetic: no real customer with two caption languages has been
    # seen. Shape copied from El Paso's real single-entry list.
    data = {
        "MediaInfo": {
            "Captions": [
                {"LanguageID": "es", "MediaPath": "/2026-09/es.vtt"},
                {"LanguageID": "en", "MediaPath": "/2026-09/en.vtt"},
            ]
        }
    }
    assert (
        ChampDSAssetFinder._caption_url(data, "elpasococo")
        == "https://play.champds.com/CAPTION/elpasococo/2026-09/en.vtt"
    )
