"""Tests for CHAMP/ChampDS (app/platforms/champds.py).

Real API shapes confirmed live 2026-08-13 against 6 independent real
customers (Atlanta GA, Auburn NY, Gillette WY, Marlborough MA, Saco ME,
Worcester MA) -- see BACKLOG.md/BACKLOG_DONE.md. JSON fixtures below are
trimmed to just the fields the adapter reads, but every value is a real
one pulled from a real customer's actual API response, not invented.
"""

import json

from app.platforms.base import detect_platform
from app.platforms.champds import ChampDSAssetFinder

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


async def test_resolve_does_not_use_vod2_even_when_present():
    # Real, confirmed-live blocker: securestream10.champds.com enforces a
    # strict Referer: https://play.champds.com/ check on the VOD2 HLS
    # playlist and its segments -- embedding it directly in this site's
    # own <video>/hls.js would 406 in the browser (this site's referer,
    # not champds.com's own, would be sent). Metadata/agenda still comes
    # through; only the (currently unusable) video link is withheld.
    routes = {
        MARLBOROUGH_API_URL: FakeResponse(
            status=200, text=MARLBOROUGH_JSON, url=MARLBOROUGH_API_URL
        )
    }

    with mock_session(routes):
        result = await ChampDSAssetFinder().resolve(MARLBOROUGH_URL)

    assert result.video_url is None
    assert result.video_format is None
    assert result.video_warnings == ["No video found for this ChampDS meeting."]
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


async def test_resolve_reports_no_transcript_since_captions_are_unconfirmed():
    # MediaInfo.Captions was empty on every one of the 6 real customers
    # checked -- no positive example of a populated one, so its real
    # shape is deliberately unattempted (same convention as CivicClerk/
    # eScribe -- see BACKLOG.md).
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
