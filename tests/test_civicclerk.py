from app.platforms.civicclerk import CivicClerkAssetFinder
from app.platforms.youtube import YouTubeAssetFinder

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


async def test_resolve_event_with_external_video_and_no_bookmarks(monkeypatch):
    # Real event 17 -- externalVideoUrl (a YouTube live link) instead of a
    # direct videoUrl, and zero eventBookmarks/caption tracks. Fetched live
    # 2026-08-07; unlike event 20, event 17's own mediaStreamPath/
    # mediaSourcePathMp4 fields are genuinely empty, so this actually
    # exercises the externalVideoUrl fallback branch rather than shadowing
    # it with a same-event direct video field.
    #
    # Real gap found + fixed 2026-08-16: video_format used to come back
    # None for this exact shape (a youtube.com URL has no recognized file
    # extension), which meant the frontend's iframe+Player-API playback
    # path never triggered -- not just a missing-captions gap, the video
    # may not have played at all. Now delegates to
    # YouTubeAssetFinder.resolve_video_id() the same way escribe.py/
    # primegov.py/civicweb.py/clerkbase.py already do.
    monkeypatch.setattr(
        YouTubeAssetFinder,
        "_extract_info",
        lambda video_id: {
            "title": "Clovis City Council — YouTube live stream",
            "uploader": "cityofclovis",
            "upload_date": "20260107",
            "_chosen_track": (
                "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nCall to order.\n".encode("utf-8"),
                "en",
                True,
            ),
        },
    )
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

    assert result.platform == "civicclerk"
    # Canonical embed-URL form, same as every other delegating adapter --
    # not the raw watch/live URL CivicClerk's own API happened to store.
    assert result.video_url == "https://www.youtube.com/embed/2SkDu11i3hQ"
    assert result.video_format == "youtube"
    assert result.agenda_items == []
    # CivicClerk's own caption fields were empty for this event -- real
    # captions now come from the YouTube delegation fallback instead of
    # segments staying empty forever.
    assert len(result.segments) == 1
    assert result.segments[0].text == "Call to order."


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


async def test_resolve_falls_back_to_jurisdiction_chain_when_location_is_fully_blank():
    # Real gap found live 2026-08-15 on Los Altos Hills, CA (event 4567):
    # eventLocation.city AND .state both null, not just a missing state,
    # so the state-only fallback above never fires and jurisdiction used
    # to come back None. `extract_jurisdiction_chain()`'s validated-
    # subdomain tier resolves this correctly from the URL alone --
    # "losaltoshillsca" -> wordninja -> "Los Altos Hills" -- confirmed
    # live in BACKLOG.md, no page_text/html needed.
    url = "https://losaltoshillsca.portal.civicclerk.com/event/4567/media"
    event_json = (
        '{"id": 4567, "eventName": "City Council Regular Meeting", '
        '"eventDate": "2026-06-18T00:00:00Z", "eventLocation": {"city": null, "state": null}}'
    )
    media_json = '{"id": 4567, "videoUrl": "https://cpmedia.azureedge.net/example/c.mp4", "eventBookmarks": []}'

    routes = {
        "https://losaltoshillsca.api.civicclerk.com/v1/Events/4567": FakeResponse(status=200, text=event_json),
        "https://losaltoshillsca.api.civicclerk.com/v1/EventsMedia/4567": FakeResponse(status=200, text=media_json),
    }

    with mock_session(routes):
        result = await CivicClerkAssetFinder().resolve(url)

    assert result.jurisdiction == "Los Altos Hills, CA"


async def test_resolve_falls_back_to_agenda_plaintext_when_subdomain_also_fails():
    # Path 2 of the same source entry as the test above (BACKLOG.md):
    # when eventLocation is blank AND the URL-only chain (subdomain alone)
    # also fails to validate -- unlike Los Altos Hills, where the
    # subdomain tier alone was already enough -- CivicClerk's own agenda
    # file is fetchable as plain text and is a richer, independent signal.
    # Real shape confirmed live on Los Altos Hills' actual agenda blob
    # ("Town of Los Altos Hills / City Council Regular Meeting Agenda /
    # Thursday, ..."); synthetic subdomain/place name here so this test
    # doesn't depend on the free tier above also failing to fire.
    url = "https://testgov123.portal.civicclerk.com/event/9/media"
    event_json = (
        '{"id": 9, "eventName": "City Council Meeting", '
        '"eventDate": "2026-06-18T00:00:00Z", "eventLocation": {"city": null, "state": null}, '
        '"publishedFiles": [{"type": "Agenda", "fileId": 8983, '
        '"url": "https://testgov123.api.civicclerk.com/v1/Meetings/GetMeetingFile(fileId=8983,plainText=false)"}]}'
    )
    media_json = '{"id": 9, "videoUrl": "https://cpmedia.azureedge.net/example/d.mp4", "eventBookmarks": []}'
    blob_url = "https://sasblob.example.com/agenda-8983.txt?sig=abc123"
    agenda_text = "Town of Galesburg / City Council Regular Meeting Agenda / Thursday, June 18, 2026"

    routes = {
        "https://testgov123.api.civicclerk.com/v1/Events/9": FakeResponse(status=200, text=event_json),
        "https://testgov123.api.civicclerk.com/v1/EventsMedia/9": FakeResponse(status=200, text=media_json),
        "https://testgov123.api.civicclerk.com/v1/Meetings/GetMeetingFile(fileId=8983,plainText=true)":
            FakeResponse(status=200, text=f'{{"blobUri": "{blob_url}"}}'),
        blob_url: FakeResponse(status=200, text=agenda_text),
    }

    with mock_session(routes):
        result = await CivicClerkAssetFinder().resolve(url)

    assert result.jurisdiction == "Town of Galesburg"


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
