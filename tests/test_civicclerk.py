from app.platforms.civicclerk import CivicClerkAssetFinder

from aiohttp_mock import FakeResponse, mock_session
from conftest import load_fixture, load_fixture_bytes


async def test_resolve_real_event_with_video_and_agenda_bookmarks():
    # Real clovisca.api.civicclerk.com event 20, fetched live 2026-08-07 --
    # a direct mp4 (not the externalVideoUrl fallback) with 31 real agenda
    # bookmarks, the richest real CivicClerk sample found in this pass.
    url = "https://clovisca.portal.civicclerk.com/event/20/media"
    event_json = load_fixture("civicclerk", "clovisca_event20.json")
    media_json = load_fixture("civicclerk", "clovisca_media20.json")

    routes = {
        "https://clovisca.api.civicclerk.com/v1/Events/20":
            FakeResponse(status=200, text=event_json),
        "https://clovisca.api.civicclerk.com/v1/EventsMedia/20":
            FakeResponse(status=200, text=media_json),
    }

    with mock_session(routes):
        result = await CivicClerkAssetFinder().resolve(url)

    assert result.platform == "civicclerk"
    assert result.external_id == "civicclerk:20"
    assert result.title == "City Council Meeting"
    assert result.date == "2026-04-13"
    assert result.jurisdiction == "Clovis, CA"
    assert result.video_url == "https://cpmedia.azureedge.net/clovisca/f32a4ab02f.mp4"
    assert result.video_format == "mp4"
    assert len(result.agenda_items) == 31
    # Several real bookmarks share markerTimeStart=0 (category headers with
    # no real timestamp, e.g. "Presentations/Proclamations") and sort ahead
    # of the first real timed item ("Call to Order" at 855s) -- confirmed
    # against the actual live API response, not assumed from field names.
    assert result.agenda_items[0].start == 0.0
    assert "Call to Order" in [item.text for item in result.agenda_items]
    # Real sample has no populated caption/transcript fields -- confirmed
    # unverified path per BACKLOG.md, not silently treated as success.
    assert result.segments == []
    assert any("no caption" in w.lower() for w in result.transcript_warnings)


async def test_resolve_event_with_external_video_and_no_bookmarks():
    # Real event 17 -- externalVideoUrl (a YouTube live link) instead of a
    # direct videoUrl, and zero eventBookmarks/caption tracks. Fetched live
    # 2026-08-07; unlike event 20, event 17's own mediaStreamPath/
    # mediaSourcePathMp4 fields are genuinely empty, so this actually
    # exercises the externalVideoUrl fallback branch rather than shadowing
    # it with a same-event direct video field.
    url = "https://clovisca.portal.civicclerk.com/event/17/media"
    event_json = load_fixture("civicclerk", "clovisca_event17.json")
    media_json = load_fixture("civicclerk", "clovisca_media17.json")

    routes = {
        "https://clovisca.api.civicclerk.com/v1/Events/17":
            FakeResponse(status=200, text=event_json),
        "https://clovisca.api.civicclerk.com/v1/EventsMedia/17":
            FakeResponse(status=200, text=media_json),
    }

    with mock_session(routes):
        result = await CivicClerkAssetFinder().resolve(url)

    assert result.video_url == "https://www.youtube.com/live/2SkDu11i3hQ"
    assert result.agenda_items == []


async def test_resolve_real_event_with_populated_srt_captions():
    # Real emporiaks.api.civicclerk.com event 585 (user-supplied example,
    # 2026-08-08) -- the first real CivicClerk sample found with actually
    # populated closedCaptionTracks, after three earlier sample cities
    # (Clovis CA, Highland CA, Lino Lakes MN) all had these null/empty.
    # The real file is .srt, not .vtt -- confirms the format this schema
    # actually uses in practice, previously only assumed from field names.
    url = "https://emporiaks.portal.civicclerk.com/event/585/media"
    event_json = load_fixture("civicclerk", "emporiaks_event585.json")
    media_json = load_fixture("civicclerk", "emporiaks_media585.json")
    captions_srt = load_fixture_bytes("civicclerk", "emporiaks_585_captions.srt")

    caption_url = "https://cpmedia.azureedge.net/emporiaks/ClosedCaption/07222026172024531-585.srt"
    routes = {
        "https://emporiaks.api.civicclerk.com/v1/Events/585":
            FakeResponse(status=200, text=event_json),
        "https://emporiaks.api.civicclerk.com/v1/EventsMedia/585":
            FakeResponse(status=200, text=media_json),
        caption_url: FakeResponse(status=200, raw=captions_srt),
    }

    with mock_session(routes):
        result = await CivicClerkAssetFinder().resolve(url)

    assert result.external_id == "civicclerk:585"
    assert result.title == "Commission Meeting"
    assert result.date == "2026-07-22"
    assert result.jurisdiction == "Emporia, KS"
    assert result.video_url == "https://cpmedia.azureedge.net/emporiaks/ab8f5fbb5f.mp4"
    # Real file has 3677 real cues once SRT sequence-number lines are
    # correctly stripped (see test_vtt_parser.py's parse_srt tests for the
    # corruption this guards against) -- confirmed against the live API.
    assert len(result.segments) == 3677
    assert result.transcript_language == "en"
    assert result.transcript_warnings == []
    assert len(result.agenda_items) == 26
    # Spot-check real content, not just counts.
    assert result.segments[3].text == "Meeting to order."


async def test_resolve_fills_in_missing_state_via_shared_lookup():
    # Synthetic -- every real CivicClerk sample found so far (Clovis CA,
    # Emporia KS, Highland CA, Lino Lakes MN) already has eventLocation.state
    # populated, so this exact gap is unconfirmed in the wild (see
    # BACKLOG.md's "no-state jurisdiction audit"). Exercises the fallback
    # in case a real customer with a blank state ever shows up: an
    # unambiguous city name should still resolve a real state via the same
    # shared gazetteer lookup every free-text adapter uses.
    url = "https://example.portal.civicclerk.com/event/2/media"
    event_json = (
        '{"id": 2, "eventName": "Test Meeting", "eventDate": "2026-01-01T00:00:00Z", '
        '"eventLocation": {"city": "Fresno", "state": ""}}'
    )
    media_json = '{"id": 2, "videoUrl": "https://cpmedia.azureedge.net/example/b.mp4", "eventBookmarks": []}'

    routes = {
        "https://example.api.civicclerk.com/v1/Events/2": FakeResponse(status=200, text=event_json),
        "https://example.api.civicclerk.com/v1/EventsMedia/2": FakeResponse(status=200, text=media_json),
    }

    with mock_session(routes):
        result = await CivicClerkAssetFinder().resolve(url)

    assert result.jurisdiction == "Fresno, CA"


async def test_resolve_text_fallback_for_unstructured_caption_format():
    # Synthetic, not real -- only .srt has ever been observed live on this
    # platform (event 585 above). Exercises the new fallback path in case
    # a future CivicClerk city serves a different format via
    # closedCaptionTracks; see BACKLOG.md.
    url = "https://example.portal.civicclerk.com/event/1/media"
    event_json = '{"id": 1, "eventName": "Test Meeting", "eventDate": "2026-01-01T00:00:00Z", "eventLocation": {}}'
    media_json = (
        '{"id": 1, "videoUrl": "https://cpmedia.azureedge.net/example/a.mp4", '
        '"closedCaptionTracks": [{"file": "https://cpmedia.azureedge.net/example/cc.sbv", '
        '"label": "English", "kind": "captions", "default": true}], "eventBookmarks": []}'
    )
    sbv_content = "0:00:01.000,0:00:02.000\nHello there."

    routes = {
        "https://example.api.civicclerk.com/v1/Events/1": FakeResponse(status=200, text=event_json),
        "https://example.api.civicclerk.com/v1/EventsMedia/1": FakeResponse(status=200, text=media_json),
        "https://cpmedia.azureedge.net/example/cc.sbv": FakeResponse(status=200, text=sbv_content),
    }

    with mock_session(routes):
        result = await CivicClerkAssetFinder().resolve(url)

    assert [s.text for s in result.segments] == ["Hello there."]
    assert any("plain text" in w for w in result.transcript_warnings)
