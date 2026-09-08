import pytest

from app.platforms.invintus import InvintusAssetFinder, is_invintus_meeting_url, parse_invintus_ids

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

# Invintus (player.invintus.com) -- found 2026-09-08 via a real gap on
# University Place, WA's CivicPlus AgendaCenter page (14 real per-meeting
# video links this repo had no adapter for). See invintus.py's own module
# docstring and `rtr-business/research/ENUMERATION_METHODS.md` §102 for
# the full investigation. `university_place_getDetailed.json` is a real,
# live `Event/getDetailed` response (clientID 1872740071, eventID
# 2026081000) fetched 2026-09-08, unmodified. `university_place_captions.
# vtt` is trimmed to its first 30 real cues (same "trimmed real VTT
# fixture" convention test_castus.py/test_telvue.py use for a long real
# transcript).

PAGE_URL = "https://player.invintus.com/?clientID=1872740071&eventID=2026081000"
API_URL = "https://api.v3.invintus.com/v2/Event/getDetailed"
CAPTIONS_URL = (
    "https://m-download.invintus.com/1872740071/"
    "6ee20a1b6e41803e5e16810439a5c84076f78509.vtt"
)


async def test_resolve_real_university_place_city_council():
    detail_json = load_fixture("invintus", "university_place_getDetailed.json")
    captions_vtt = load_fixture("invintus", "university_place_captions.vtt")

    routes = {
        CAPTIONS_URL: FakeResponse(status=200, text=captions_vtt, url=CAPTIONS_URL),
    }
    post_routes = {
        API_URL: FakeResponse(status=200, text=detail_json, url=API_URL),
    }

    with mock_session(routes, post_routes=post_routes):
        result = await InvintusAssetFinder().resolve(PAGE_URL)

    assert result.platform == "invintus"
    assert result.external_id == "invintus:1872740071:2026081000"
    assert result.title == "University Place City Council 8/3/2026"
    assert result.date == "2026-08-03"
    assert result.jurisdiction == "University Place"
    assert result.meeting_body == "University Place City Council"
    assert (
        result.video_url
        == "https://m-download.invintus.com/1872740071/"
        "096f7a9a4fefe5971b5f2b04b34c444fba43a5ee.mp4"
    )
    assert result.video_format == "mp4"
    assert result.video_warnings == []
    assert len(result.segments) == 30
    assert result.segments[0].text == "All right, all right good evening ladies and gentlemen."
    assert result.transcript_language == "en"
    assert result.transcript_warnings == []


async def test_resolve_falls_back_to_hls_when_no_direct_download_link():
    # Real shape confirmed live is always `downloadLinks.videoDownloadURI`
    # -- this covers the documented `streamingURIs.main` fallback in case
    # a future tenant's event ever omits it.
    import json

    data = json.loads(load_fixture("invintus", "university_place_getDetailed.json"))
    data["data"]["downloadLinks"] = {}
    data["data"]["captionPath"] = None

    post_routes = {
        API_URL: FakeResponse(status=200, text=json.dumps(data), url=API_URL),
    }

    with mock_session({}, post_routes=post_routes):
        result = await InvintusAssetFinder().resolve(PAGE_URL)

    assert (
        result.video_url
        == "https://api.v3.invintus.com/StreamURI/hls/1872740071/2026081000/media.m3u8"
    )
    assert result.video_format == "m3u8"
    assert result.segments == []
    assert result.transcript_warnings == ["No captions found for this video."]


async def test_resolve_degrades_when_categories_and_captions_are_null():
    # Real shape confirmed live on Des Moines, WA (a historical, now-
    # churned Invintus customer) and Leon County, FL's Tourism
    # Development Council: `categories`/`captionPath` are `null`, not
    # every tenant sets them.
    import json

    data = json.loads(load_fixture("invintus", "university_place_getDetailed.json"))
    data["data"]["categories"] = None
    data["data"]["captionPath"] = None
    data["data"]["title"] = "City Council, September 17, 2020"

    post_routes = {
        API_URL: FakeResponse(status=200, text=json.dumps(data), url=API_URL),
    }

    with mock_session({}, post_routes=post_routes):
        result = await InvintusAssetFinder().resolve(PAGE_URL)

    assert result.title == "City Council, September 17, 2020"
    assert result.jurisdiction is None
    assert result.meeting_body is None
    assert result.segments == []
    assert result.transcript_warnings == ["No captions found for this video."]
    # Video is unaffected -- this only exercises the categories/captions gap.
    assert result.video_url is not None


async def test_resolve_no_event_found_degrades_to_warning_not_exception():
    post_routes = {
        API_URL: FakeResponse(
            status=200,
            text='{"errors": {"hasError": true, "message": "Event not found"}, "data": null}',
            url=API_URL,
        ),
    }

    with mock_session({}, post_routes=post_routes):
        result = await InvintusAssetFinder().resolve(PAGE_URL)

    assert result.platform == "invintus"
    assert result.external_id == "invintus:1872740071:2026081000"
    assert result.video_url is None
    assert result.video_warnings == ["No event found for this Invintus meeting."]


async def test_resolve_missing_ids_raises_value_error():
    with pytest.raises(ValueError):
        await InvintusAssetFinder().resolve("https://player.invintus.com/")


def test_parse_invintus_ids_normalizes_html_entity_ampersand():
    # Real shape confirmed live in University Place's own raw AgendaCenter
    # page source (un-decoded `&amp;` between params).
    url = "https://player.invintus.com/?clientID=1872740071&amp;eventID=2026081000"
    assert parse_invintus_ids(url) == ("1872740071", "2026081000")


def test_is_invintus_meeting_url_requires_both_ids():
    assert is_invintus_meeting_url(PAGE_URL) is True
    assert is_invintus_meeting_url("https://player.invintus.com/?clientID=123") is False
    assert (
        is_invintus_meeting_url("https://hostedevents.invintus.com/equitysummit/")
        is False
    )
    assert is_invintus_meeting_url("https://example.gov/agendacenter") is False
