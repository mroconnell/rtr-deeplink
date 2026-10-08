"""SWD Live (swd-live.com) adapter. Fixtures in tests/fixtures/swd_live/ are real API answers read live on 2026-10-08 (Gatineau); each file's
`_fixture_source` names the request."""

import json

import pytest

from app.platforms import swd_live
from app.platforms.base import detect_platform
from app.platforms.swd_live import SwdLiveAssetFinder, event_id_from_url, tenant_from_url
from app.utils.tenant_key import tenant_key

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

PLENARY_ID = "e96fb041-106e-4c38-9b99-d51eeddd4a38"
CLIP_ID = "e5960bb4-5a9d-46af-aef5-02581826bb1f"
PLENARY_URL = f"https://swd-live.com/fr/gatineau/archive/{PLENARY_ID}"
PLENARY_API = f"https://api.swd-live.com/api/v1/events/{PLENARY_ID}/"
LIST_API = "https://api.swd-live.com/api/v1/events/list_archived/?from_date=2026-09-01&to_date=2026-09-30"


def _route(url, fixture=None, status=200, text=None):
    body = text if text is not None else load_fixture("swd_live", fixture)
    return {url: FakeResponse(status=status, text=body, url=url)}


async def test_resolve_a_committee_meeting_gives_the_mp4_the_date_and_no_captions():
    with mock_session(_route(PLENARY_API, "event_committee_of_the_whole_2026-09-01.json")):
        result = await SwdLiveAssetFinder().resolve(PLENARY_URL)

    assert result.platform == "swd_live"
    assert result.external_id == f"swd_live:gatineau:{PLENARY_ID}"
    assert result.title == "Comité plénier public"
    assert result.date == "2026-09-01"
    assert result.video_format == "mp4"
    assert result.video_url.startswith("https://villeswd.blob.core.windows.net/media/archive/2026/09%20Septembre/")
    assert result.video_url.endswith(".mp4")
    assert result.video_channel == "swd_live:gatineau"
    # The broadcast window (4.4 h) is longer than the real file (3.9 h), so it is never offered as the length.
    assert result.video_duration_seconds is None
    assert result.segments == [] and result.video_warnings == []
    assert result.transcript_warnings == ["No captions found for this video."]


async def test_the_english_address_gives_the_english_title():
    url = f"https://www.swd-live.com/en/gatineau/archive/{PLENARY_ID}"
    with mock_session(_route(PLENARY_API, "event_committee_of_the_whole_2026-09-01.json")):
        result = await SwdLiveAssetFinder().resolve(url)
    assert result.title == "Public Committee of the Whole"


async def test_the_tenant_header_is_sent(monkeypatch):
    seen = []
    real = swd_live._api_headers
    monkeypatch.setattr(swd_live, "_api_headers", lambda tenant: seen.append(tenant) or real(tenant))
    with mock_session(_route(PLENARY_API, "event_committee_of_the_whole_2026-09-01.json")):
        await SwdLiveAssetFinder().resolve(PLENARY_URL)
    assert seen == ["gatineau"]
    assert real("gatineau")["X-Tenant-Name"] == "gatineau" and "redtaperecordings" in real("gatineau")["User-Agent"]


async def test_a_meeting_with_no_archived_video_is_a_plain_warning_not_an_error():
    event = json.loads(load_fixture("swd_live", "event_committee_of_the_whole_2026-09-01.json"))
    event["vod_blog_url"] = ""
    with mock_session(_route(PLENARY_API, text=json.dumps(event))):
        result = await SwdLiveAssetFinder().resolve(PLENARY_URL)
    assert result.video_url is None and result.video_format is None
    assert result.video_warnings and "no archived video" in result.video_warnings[0]


async def test_the_archive_list_page_is_not_a_single_meeting():
    result = await SwdLiveAssetFinder().resolve("https://swd-live.com/fr/gatineau/archive")
    assert result.video_url is None and result.external_id is None
    assert "not a single meeting" in result.video_warnings[0]


async def test_the_live_page_is_never_fetched():
    result = await SwdLiveAssetFinder().resolve("https://swd-live.com/fr/gatineau/broadcast")     # no mocked route: a request would raise
    assert result.video_url is None and result.video_warnings


async def test_a_429_stops_with_a_plain_warning():
    with mock_session(_route(PLENARY_API, status=429, text="")):
        result = await SwdLiveAssetFinder().resolve(PLENARY_URL)
    assert result.video_url is None and "HTTP 429" in result.video_warnings[0]


@pytest.mark.parametrize("status", [404, 500])
async def test_an_api_error_is_a_plain_warning(status):
    with mock_session(_route(PLENARY_API, status=status, text="")):
        result = await SwdLiveAssetFinder().resolve(PLENARY_URL)
    assert result.video_url is None and result.video_warnings == ["Could not load this swd-live.com meeting."]


async def test_list_archived_returns_the_months_meetings():
    with mock_session(_route(LIST_API, "list_archived_2026-09.json")):
        events = await swd_live.list_archived("gatineau", "2026-09-01", "2026-09-30")
    assert len(events) == 9
    assert {e["category"]["category_code"] for e in events} == {"committee-of-the-whole", "executive-committee", "preparatory-caucus"}
    assert events[0]["translations"]["fr"]["title"] == "Comité plénier public"


def test_addresses_tenants_and_routing():
    assert event_id_from_url(PLENARY_URL) == PLENARY_ID and event_id_from_url("https://swd-live.com/fr/gatineau/archive") is None
    assert tenant_from_url("https://swd-live.com/en/mont-royal") == "mont-royal"
    assert tenant_from_url("https://swd-live.com/") is None
    assert detect_platform(PLENARY_URL) == "swd_live" and detect_platform("https://www.swd-live.com/fr/gatineau/archive") == "swd_live"
    assert tenant_key("https://swd-live.com/fr/gatineau/archive") == "gatineau"
    assert tenant_key(PLENARY_URL) == tenant_key("https://www.swd-live.com/en/gatineau/broadcast") == "gatineau"
    assert tenant_key("https://swd-live.com/fr/mont-royal") == "mont-royal"
