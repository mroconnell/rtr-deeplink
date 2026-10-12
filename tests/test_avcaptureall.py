"""AV Capture All (media.avcaptureall.cloud) adapter, WO-1190.

Fixtures in tests/fixtures/avcaptureall/ are real answers read on 2026-10-11 by a headless Chromium page load: the Ocean Shores WA record of
2026-09-22 (captions, agenda, a doubled-path caption URL), the Suisun City CA record of 2026-07-28 (no captions key at all), and the first lines of
two real WebVTT files. The headless step is MOCKED here (the record call needs a browser-minted AWS WAF token, so there is no plain-HTTP way to
fetch it); everything after it is parsed for real. Synthetic cases are marked: a `hasRecording: false` record and a no-date file name are the
Ocean Shores record with that one field changed (no real example of either was saved).
"""

import copy
import json

import pytest

from app.platforms import avcaptureall as avc
from app.platforms.avcaptureall import (
    AVCaptureAllAssetFinder,
    clean_caption_url,
    local_date_from_file_url,
    meeting_guid_from_url,
)
from app.platforms.base import detect_platform
from app.platforms.headless_browser import HeadlessBrowserUnavailable
from app.platforms.queue_probe import has_owner
from app.utils.gov_registry.resolver import page_hints_for, resolve_government
from app.utils.tenant_key import pin_tenant_key, tenant_key

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture

OS_GUID = "809abb94-6a6b-474b-83ae-7ed17c067971"
OS_CUSTOMER = "98620b8a-5c16-41d6-a5eb-81729bd49cd0"
OS_URL = f"https://media.avcaptureall.cloud/meeting/{OS_GUID}"
SUISUN_GUID = "c9d1a041-ed11-4e78-a1b3-fbd6c56b33da"
SUISUN_URL = f"https://media.avcaptureall.cloud/meeting/{SUISUN_GUID}"
OS_RECORD = "meetings_id_ocean_shores_809abb94_2026-09-22.json"
SUISUN_RECORD = "meetings_id_suisun_city_c9d1a041_2026-07-28_no_captions.json"


def _record(name: str) -> dict:
    return json.loads(load_fixture("avcaptureall", name))


def _patch_browser(monkeypatch, reply):
    """Replace the headless step. `reply` is `(status, body_text)`, None, or an exception to raise."""
    calls = []

    async def fake(page_url, *, reply_url_contains, timeout_ms=30000):
        calls.append((page_url, reply_url_contains))
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(avc, "fetch_api_reply_via_browser", fake)
    return calls


def _ok(record: dict):
    return 200, json.dumps(record)


async def test_detect_platform_routes_a_meeting_and_a_viewer_url(monkeypatch):
    assert detect_platform(OS_URL) == "avcaptureall"
    assert detect_platform(OS_URL + "?customerGuid=" + OS_CUSTOMER) == "avcaptureall"
    viewer = f"https://media.avcaptureall.cloud/?customerGuid={OS_CUSTOMER}"
    assert detect_platform(viewer) == "avcaptureall"
    # The customer viewer is not a meeting: a plain warning, and the browser is never started.
    calls = _patch_browser(monkeypatch, HeadlessBrowserUnavailable("should not run"))
    result = await AVCaptureAllAssetFinder().resolve(viewer)
    assert result.video_url is None
    assert "not a single meeting" in result.video_warnings[0]
    assert calls == []
    # A direct file on the download host is not this adapter's page.
    assert (
        detect_platform("https://download.avcaptureall.cloud/x/y.mp4") != "avcaptureall"
    )


async def test_ocean_shores_record_maps_to_title_local_date_length_video_and_links(
    monkeypatch,
):
    calls = _patch_browser(monkeypatch, _ok(_record(OS_RECORD)))
    vtt_url = _record(OS_RECORD)["videoSubtitlesUrl"]
    routes = {
        vtt_url: FakeResponse(
            text=load_fixture("avcaptureall", "vtt_head_ocean_shores_809abb94.vtt"),
            url=vtt_url,
        )
    }
    with mock_session(routes):
        # A customer-viewer query string is dropped from the page identity.
        result = await AVCaptureAllAssetFinder().resolve(
            f"https://media.avcaptureall.cloud/meeting/{OS_GUID.upper()}"
            f"?customerGuid={OS_CUSTOMER}"
        )
    assert calls == [(OS_URL, f"/V1_0/meetings/id/{OS_GUID}")]
    assert result.platform == "avcaptureall"
    assert result.source_url == OS_URL
    assert result.external_id == f"avcaptureall:{OS_GUID}"
    assert result.title == "Regular City Council Meeting"
    assert result.jurisdiction == "City of Ocean Shores, WA"
    assert result.meeting_body == "Legislative"
    assert result.meeting_location == "Ocean Shores Convention Center"
    # The local date from the file name, not the UTC 2026-09-23.
    assert result.date == "2026-09-22"
    assert result.video_url.endswith("06-00-56%20PM.mp4")
    assert result.video_format == "mp4"
    assert result.video_duration_seconds == 5139
    assert result.video_channel == f"avcapture:{OS_CUSTOMER}"
    assert result.agenda_link.endswith("Agenda%20-%20AMENDED.pdf")
    assert result.packet_link.endswith("/packet.pdf")
    assert result.agenda_items == []
    assert result.video_warnings == []


async def test_the_real_vtt_head_parses_to_real_cues(monkeypatch):
    _patch_browser(monkeypatch, _ok(_record(OS_RECORD)))
    vtt_url = _record(OS_RECORD)["videoSubtitlesUrl"]
    routes = {
        vtt_url: FakeResponse(
            text=load_fixture("avcaptureall", "vtt_head_ocean_shores_809abb94.vtt"),
            url=vtt_url,
        )
    }
    with mock_session(routes):
        result = await AVCaptureAllAssetFinder().resolve(OS_URL)
    assert len(result.segments) >= 5
    first = result.segments[0]
    assert first.start == pytest.approx(6.044)
    assert first.text.startswith("This is a regular city council meeting")
    assert result.transcript_warnings == []


async def test_a_403_on_the_doubled_caption_path_retries_once_in_the_clean_form(
    monkeypatch,
):
    record = _record(OS_RECORD)
    _patch_browser(monkeypatch, _ok(record))
    doubled = record["videoSubtitlesUrl"]
    clean = clean_caption_url(doubled, OS_CUSTOMER, OS_GUID)
    assert clean != doubled
    assert clean.count(f"customer-{OS_CUSTOMER}") == 1
    routes = {
        doubled: FakeResponse(status=403, text="", url=doubled),
        clean: FakeResponse(
            text=load_fixture("avcaptureall", "vtt_head_ocean_shores_809abb94.vtt"),
            url=clean,
        ),
    }
    with mock_session(routes):
        result = await AVCaptureAllAssetFinder().resolve(OS_URL)
    assert len(result.segments) >= 5


def test_clean_caption_url_leaves_an_undoubled_url_alone():
    url = f"https://download.avcaptureall.cloud/customer-{OS_CUSTOMER}/meetings/{OS_GUID}/x.vtt"
    assert clean_caption_url(url, OS_CUSTOMER, OS_GUID) == url


async def test_suisun_record_has_no_captions_and_says_so(monkeypatch):
    record = _record(SUISUN_RECORD)
    assert "videoSubtitlesUrl" not in record
    _patch_browser(monkeypatch, _ok(record))
    # No VTT route: any caption request would fail the mock, so none may be made.
    with mock_session({}):
        result = await AVCaptureAllAssetFinder().resolve(SUISUN_URL)
    assert result.source_url == SUISUN_URL
    assert result.title == "City Council"
    assert result.jurisdiction == "City of Suisun City, CA"
    assert result.date == "2026-07-28"
    assert result.video_duration_seconds == 1331
    assert result.video_url.endswith("05-00-27%20PM.mp4")
    assert result.video_channel == "avcapture:da3d7a7a-b84a-4efc-9bc7-52cf47eeee3d"
    assert result.agenda_link.endswith(".pdf")
    assert result.packet_link.endswith("/packet.pdf")
    assert result.segments == []
    assert result.transcript_warnings == ["No captions found for this video."]


async def test_synthetic_no_recording_gives_a_warning_and_no_video(monkeypatch):
    # Synthetic: the real Suisun record with `hasRecording` false and no `viewUrl` (the shape the scope found on about 220 live or upcoming rows).
    record = copy.deepcopy(_record(SUISUN_RECORD))
    record.update({"hasRecording": False, "viewUrl": "", "duration": 0})
    _patch_browser(monkeypatch, _ok(record))
    result = await AVCaptureAllAssetFinder().resolve(SUISUN_URL)
    assert result.video_url is None
    assert result.title == "City Council"
    assert "This AV Capture All meeting has no recording yet." in result.video_warnings
    # The date still comes from the record (UTC, and the result says so); there is no file name to read.
    assert result.date == "2026-07-29"
    assert any("UTC" in w for w in result.video_warnings)


async def test_synthetic_file_name_without_a_date_falls_back_to_utc_and_says_so(
    monkeypatch,
):
    record = copy.deepcopy(_record(SUISUN_RECORD))
    record["viewUrl"] = record["viewUrl"].replace(
        "City%20Council_2026-07-28_05-00-27%20PM.mp4", "recording.mp4"
    )
    _patch_browser(monkeypatch, _ok(record))
    result = await AVCaptureAllAssetFinder().resolve(SUISUN_URL)
    assert result.date == "2026-07-29"
    assert len(result.video_warnings) == 1
    assert "UTC" in result.video_warnings[0]


async def test_a_reply_that_is_not_a_record_gives_a_plain_warning(monkeypatch):
    for reply in (
        None,
        (403, '{"message":"Forbidden"}'),
        (200, "not json"),
        (200, "{}"),
    ):
        _patch_browser(monkeypatch, reply)
        result = await AVCaptureAllAssetFinder().resolve(OS_URL)
        assert result.video_url is None
        assert result.video_warnings == ["Could not load this AV Capture All meeting."]


async def test_no_headless_browser_raises_the_plain_unavailable_error(monkeypatch):
    _patch_browser(
        monkeypatch,
        HeadlessBrowserUnavailable(
            "This meeting needs a real browser to load, and it isn't available right now."
        ),
    )
    with pytest.raises(HeadlessBrowserUnavailable):
        await AVCaptureAllAssetFinder().resolve(OS_URL)


def test_readers():
    assert meeting_guid_from_url(OS_URL) == OS_GUID
    assert (
        meeting_guid_from_url(
            f"https://media.avcaptureall.cloud/meeting/{OS_GUID.upper()}"
        )
        == OS_GUID
    )
    assert meeting_guid_from_url("https://media.avcaptureall.cloud/") is None
    assert meeting_guid_from_url("https://media.avcaptureall.cloud/meeting/xyz") is None
    assert meeting_guid_from_url("https://example.com/meeting/" + OS_GUID) is None
    assert local_date_from_file_url(_record(OS_RECORD)["viewUrl"]) == "2026-09-22"
    assert local_date_from_file_url("https://x.example/odd.mp4") is None


# --- Identity: the address names no customer; a pin on `video_channel` does.
def test_the_address_names_no_customer_but_a_pin_matches_the_page_hint():
    assert tenant_key(OS_URL) is None
    assert (
        pin_tenant_key(
            "media.avcaptureall.cloud", f"channel=avcapture:{OS_CUSTOMER.upper()}"
        )
        == OS_CUSTOMER
    )
    assert (
        pin_tenant_key("media.avcaptureall.cloud", "channel=avcapture:not-a-guid")
        is None
    )


def _ladder(channel):
    return resolve_government(
        "City of Somewhere",
        tenant_host="media.avcaptureall.cloud",
        path=f"/meeting/{OS_GUID}",
        page_hints=page_hints_for(
            "avcaptureall", f"avcaptureall:{OS_GUID}", channel=channel
        ),
    )


def test_a_pinned_customer_resolves_to_its_government_and_an_unpinned_one_does_not():
    pinned = _ladder(f"avcapture:{OS_CUSTOMER}")
    assert pinned.gov_id == "us:place:5350570"  # City of Ocean Shores, WA
    unpinned = _ladder("avcapture:00000000-0000-4000-8000-000000000000")
    assert unpinned.gov_id != "us:place:5350570"
    assert unpinned.gov_id.startswith("rtr:unknown")


def test_a_court_calendar_customer_and_monroe_wa_are_not_pinned():
    # Marysville WA Municipal Court, Spokane County District Court (court-only) and City of Monroe WA (75 of 75 Judicial): Ryan, 2026-10-11.
    for guid in (
        "6b13da77-5942-438c-b0f7-b6450d1a7cce",
        "7d64c729-a9c4-466e-9572-0cb2a1bd430a",
        "53caa49f-349e-4482-a55b-8d8c8138e9d0",
    ):
        assert _ladder(f"avcapture:{guid}").gov_id.startswith("rtr:unknown")


def test_the_feeders_owner_check_never_calls_a_bare_avc_meeting_owned():
    # `has_owner()` passes no page hints, and the pin matches only the adapter's `video_channel`, so a queue line must carry its `gov_id` (CLAUDE.md).
    for url in (OS_URL, SUISUN_URL):
        owned, gov_id, reason = has_owner(url)
        assert owned is False
        assert gov_id is None
        assert "media.avcaptureall.cloud" in reason


# --- The new headless helper (headless_browser.fetch_api_reply_via_browser): its YouTube stop. The page load itself is live-checked, not CI.
async def test_the_api_capture_route_never_lets_a_youtube_host_through():
    from app.platforms import headless_browser as hb

    class _Req:
        def __init__(self, url):
            self.url = url

    class _Route:
        def __init__(self, url):
            self.request = _Req(url)
            self.aborted = False
            self.continued = False

        async def abort(self):
            self.aborted = True

        async def continue_(self):
            self.continued = True

    for url in (
        "https://www.youtube.com/embed/x",
        "https://youtu.be/x",
        "https://r1---sn.googlevideo.com/videoplayback",
        "https://i.ytimg.com/vi/x/0.jpg",
    ):
        route = _Route(url)
        await hb._guard_route_api_capture(route)
        assert route.aborted and not route.continued, url
