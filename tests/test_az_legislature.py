import pytest

from app.platforms.az_legislature import (
    ArizonaLegislatureAssetFinder,
    is_az_legislature_video_url,
)
from app.platforms.base import register
from app.platforms.invintus import InvintusAssetFinder

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture


@pytest.fixture(autouse=True)
def _register_delegates():
    # resolve() delegates to InvintusAssetFinder via resolve_via_platform()
    # -- same pattern test_municode_meetings.py's own `_register_delegates`
    # fixture uses for its YouTube/Vimeo delegates.
    register(InvintusAssetFinder())
    register(ArizonaLegislatureAssetFinder())

# Arizona State Legislature (azleg.gov) -- found 2026-09-09 chasing the
# Invintus prevalence sweep (WO-102): clientID 6361162879 turned out to
# belong to azleg.gov's own `/videoplayer/?eventID=` wrapper pages. See
# az_legislature.py's own module docstring for the full investigation.
# `videoplayer_2025011041.html` is the real, live, unmodified wrapper
# page (House Commerce Committee, 2026-09-09); `house_commerce_
# getDetailed.json` is the real live Invintus API response for the same
# event; `house_commerce_captions.vtt` is trimmed to its first 30 real
# cues (same "trimmed real VTT fixture" convention test_castus.py/
# test_invintus.py use) -- also the real fixture that caught a genuine
# shared vtt_parser.py bug (MM:SS.mmm timestamps, no hours component,
# silently produced zero cues before that fix).

PAGE_URL = "https://www.azleg.gov/videoplayer/?eventID=2025011041"
API_URL = "https://api.v3.invintus.com/v2/Event/getDetailed"
CAPTIONS_URL = (
    "https://m-download.invintus.com/6361162879/"
    "92111f8ea53ae0742647aea72309ee4b9bc304ca.vtt"
)


async def test_resolve_real_house_commerce_committee_meeting():
    wrapper_html = load_fixture("az_legislature", "videoplayer_2025011041.html")
    detail_json = load_fixture("az_legislature", "house_commerce_getDetailed.json")
    captions_vtt = load_fixture("az_legislature", "house_commerce_captions.vtt")

    routes = {
        PAGE_URL: FakeResponse(status=200, text=wrapper_html, url=PAGE_URL),
        CAPTIONS_URL: FakeResponse(status=200, text=captions_vtt, url=CAPTIONS_URL),
    }
    post_routes = {
        API_URL: FakeResponse(status=200, text=detail_json, url=API_URL),
    }

    with mock_session(routes, post_routes=post_routes):
        result = await ArizonaLegislatureAssetFinder().resolve(PAGE_URL)

    assert result.platform == "az_legislature"
    assert result.source_url == PAGE_URL
    assert result.external_id == "az_legislature:2025011041"
    assert result.title == "01/21/2025 - House Commerce"
    assert result.date == "2025-01-21"
    # Corrected from Invintus's own raw categories ("57,1R", a session
    # code, not a jurisdiction) -- see module docstring.
    assert result.jurisdiction == "Arizona State House of Representatives"
    assert (
        result.video_url
        == "https://m-download.invintus.com/6361162879/"
        "991291670a0bf1ecb083ecfb3697d6b97da2d510.mp4"
    )
    assert result.video_format == "mp4"
    # Regression coverage for the shared vtt_parser.py MM:SS.mmm fix --
    # this file's real captions have no hours component at all.
    assert len(result.segments) == 30
    assert result.segments[0].text == "Committee on Commerce is called to order."
    assert result.transcript_warnings == []


async def test_resolve_missing_client_event_ids_raises_value_error():
    routes = {
        PAGE_URL: FakeResponse(
            status=200, text="<html><body>no player here</body></html>", url=PAGE_URL
        ),
    }
    with mock_session(routes):
        with pytest.raises(ValueError):
            await ArizonaLegislatureAssetFinder().resolve(PAGE_URL)


def test_derive_jurisdiction_from_senate_signal():
    assert (
        ArizonaLegislatureAssetFinder._derive_jurisdiction(
            "Joint Legislative Oversight Committee -- Senate Interim Committee 2025"
        )
        == "Arizona State Senate"
    )


def test_derive_jurisdiction_falls_back_when_no_chamber_signal():
    assert (
        ArizonaLegislatureAssetFinder._derive_jurisdiction("Rewind: Your Week in Review")
        == "Arizona State Legislature"
    )


def test_is_az_legislature_video_url_requires_eventid_and_host():
    assert is_az_legislature_video_url(PAGE_URL) is True
    assert is_az_legislature_video_url("https://www.azleg.gov/videoplayer/") is False
    assert is_az_legislature_video_url("https://www.azleg.gov/archivedmeetings/") is False
    assert (
        is_az_legislature_video_url("https://player.invintus.com/?clientID=1&eventID=2")
        is False
    )
