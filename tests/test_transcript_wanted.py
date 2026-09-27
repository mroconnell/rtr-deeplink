"""Tests for the "transcript wanted" queue: crud.list_youtube_pages_
missing_transcripts() (real DB integration, isolated SQLite fixture --
same pattern as tests/test_lookup_has_transcript.py) and the token-gated
GET /internal/transcript-wanted route on top of it. Consumed by
scripts/fetch_youtube_transcripts.py, which fetches captions from a
residential IP because Render's cloud IP is confirmed blocked by YouTube
(see BACKLOG_DONE.md's 2026-08-10 experiment entry).
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

import archive.main
from archive.db import crud

client = TestClient(archive.main.app)


def _payload(
    external_id: str,
    source_url: str,
    *,
    video_format="youtube",
    platform="youtube",
    video_url="https://www.youtube.com/embed/AAAAAAAAAAA",
    segments=None,
) -> dict:
    return {
        "platform": platform,
        "source_url": source_url,
        "external_id": external_id,
        "title": "Wanted-Queue Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "City of Test",
        "video_url": video_url,
        "video_format": video_format,
        "segments": segments or [],
        "agenda_items": [{"start": 0, "end": 0, "text": "Call to order"}],
        "transcript_language": "en",
        "transcript_warnings": [],
    }


async def test_wanted_lists_youtube_page_without_transcript():
    url = "https://www.youtube.com/watch?v=wanted-yes"
    await crud.ingest_resolution(_payload("youtube:wanted-yes", url), url)

    wanted = await crud.list_youtube_pages_missing_transcripts()
    match = [p for p in wanted if p["external_id"] == "youtube:wanted-yes"]
    assert len(match) == 1
    # Exactly the identity fields a push needs to land on the same page.
    assert match[0]["platform"] == "youtube"
    assert match[0]["source_url_normalized"]
    assert match[0]["video_url"] == "https://www.youtube.com/embed/AAAAAAAAAAA"


async def test_wanted_excludes_youtube_page_with_transcript():
    url = "https://www.youtube.com/watch?v=wanted-no-has-transcript"
    await crud.ingest_resolution(
        _payload(
            "youtube:wanted-no-has-transcript",
            url,
            segments=[{"start": 0, "end": 1, "text": "we have a transcript"}],
        ),
        url,
    )

    wanted = await crud.list_youtube_pages_missing_transcripts()
    assert not [
        p for p in wanted if p["external_id"] == "youtube:wanted-no-has-transcript"
    ]


async def test_wanted_includes_youtube_page_with_garbled_transcript():
    # WO-15 (BACKLOG.md, 2026-08-16): real gap fixed -- a page with a
    # *present but garbled* transcript (e.g. a Whisper audio-fallback
    # transcript that never got real captions) used to never resurface
    # here at all, even though a real YouTube caption fetch would fix it.
    url = "https://www.youtube.com/watch?v=wanted-garbled"
    payload = _payload(
        "youtube:wanted-garbled",
        url,
        segments=[{"start": 0, "end": 1, "text": "garbled nonsense"}],
    )
    payload["transcript_warnings"] = ["This transcript looks garbled at the source."]
    await crud.ingest_resolution(payload, url)

    wanted = await crud.list_youtube_pages_missing_transcripts()
    assert [p for p in wanted if p["external_id"] == "youtube:wanted-garbled"]


async def test_wanted_excludes_non_youtube_page_without_transcript():
    # A Granicus page missing its transcript is a real gap, but not one
    # this queue can help with -- the whole point is YouTube's cloud-IP
    # block, which doesn't apply to other platforms' caption fetching.
    url = "https://example.granicus.com/player/clip/wanted-not-youtube"
    payload = _payload("granicus:wanted-not-youtube", url, video_format="m3u8")
    payload["platform"] = "granicus"
    await crud.ingest_resolution(payload, url)

    wanted = await crud.list_youtube_pages_missing_transcripts()
    assert not [p for p in wanted if p["external_id"] == "granicus:wanted-not-youtube"]


async def test_wanted_lists_vimeo_page_without_transcript():
    # WO-1147: the Vimeo sibling of test_wanted_lists_youtube_page_without_
    # transcript above -- platform="vimeo" filters on video_format="vimeo"
    # and uses the Vimeo permanent-failure check instead.
    url = "https://vimeo.com/wanted-yes"
    await crud.ingest_resolution(
        _payload(
            "vimeo:wanted-yes",
            url,
            platform="vimeo",
            video_format="vimeo",
            video_url="https://player.vimeo.com/video/wanted-yes",
        ),
        url,
    )

    wanted = await crud.list_youtube_pages_missing_transcripts(platform="vimeo")
    match = [p for p in wanted if p["external_id"] == "vimeo:wanted-yes"]
    assert len(match) == 1
    assert match[0]["platform"] == "vimeo"
    assert match[0]["source_url_normalized"]
    assert match[0]["video_url"] == "https://player.vimeo.com/video/wanted-yes"


async def test_wanted_excludes_vimeo_page_with_transcript():
    url = "https://vimeo.com/wanted-no-has-transcript"
    await crud.ingest_resolution(
        _payload(
            "vimeo:wanted-no-has-transcript",
            url,
            platform="vimeo",
            video_format="vimeo",
            segments=[{"start": 0, "end": 1, "text": "we have a transcript"}],
        ),
        url,
    )

    wanted = await crud.list_youtube_pages_missing_transcripts(platform="vimeo")
    assert not [
        p for p in wanted if p["external_id"] == "vimeo:wanted-no-has-transcript"
    ]


async def test_wanted_excludes_vimeo_page_with_permanent_no_captions_marker():
    # Mirrors WO-135's YouTube permanent-failure exclusion -- a Vimeo page
    # scripts/fetch_vimeo_transcripts.py already confirmed has no captions
    # (crud._VIMEO_NO_CAPTIONS_CONFIRMED_MARKER) must not be re-queued.
    url = "https://vimeo.com/wanted-vimeo-permanent"
    await crud.ingest_resolution(
        _payload(
            "vimeo:wanted-permanent",
            url,
            platform="vimeo",
            video_format="vimeo",
        ),
        url,
    )
    page = await crud.lookup_page_for_url(url)
    assert page is not None
    await crud.record_youtube_video_status(
        slug=page["slug"],
        transcript_marker=crud._VIMEO_NO_CAPTIONS_CONFIRMED_MARKER,
    )

    wanted = await crud.list_youtube_pages_missing_transcripts(platform="vimeo")
    assert not [p for p in wanted if p["external_id"] == "vimeo:wanted-permanent"]


async def test_wanted_zero_args_call_unchanged_by_the_platform_parameter():
    # CRITICAL per WO-1147: every existing caller (this file's own
    # zero-arg tests above, plus tests/test_transcription_jobs.py) calls
    # list_youtube_pages_missing_transcripts() with NO arguments and must
    # keep behaving byte-for-byte identically now that `platform` exists.
    # This asserts the zero-arg call and the explicit platform="youtube"
    # call return the exact same result for the same data.
    url = "https://www.youtube.com/watch?v=wanted-zero-args"
    await crud.ingest_resolution(_payload("youtube:wanted-zero-args", url), url)

    zero_args = await crud.list_youtube_pages_missing_transcripts()
    explicit_youtube = await crud.list_youtube_pages_missing_transcripts(
        platform="youtube"
    )
    assert zero_args == explicit_youtube
    assert [p for p in zero_args if p["external_id"] == "youtube:wanted-zero-args"]
    # And a Vimeo page must never leak into the YouTube (zero-arg) queue.
    vimeo_url = "https://vimeo.com/wanted-zero-args-vimeo"
    await crud.ingest_resolution(
        _payload(
            "vimeo:wanted-zero-args",
            vimeo_url,
            platform="vimeo",
            video_format="vimeo",
        ),
        vimeo_url,
    )
    zero_args_again = await crud.list_youtube_pages_missing_transcripts()
    assert not [
        p for p in zero_args_again if p["external_id"] == "vimeo:wanted-zero-args"
    ]


def test_list_youtube_pages_missing_transcripts_rejects_unsupported_platform():
    with pytest.raises(ValueError):
        asyncio.run(crud.list_youtube_pages_missing_transcripts(platform="bogus"))


def test_transcript_wanted_route_rejects_missing_token():
    response = client.get("/internal/transcript-wanted")
    assert (
        response.status_code == 404
    )  # not 401/403 -- matches every other /internal/* route


def test_transcript_wanted_route_rejects_wrong_token():
    response = client.get(
        "/internal/transcript-wanted", headers={"Authorization": "Bearer wrong"}
    )
    assert response.status_code == 404


async def test_transcript_wanted_route_returns_queue():
    url = "https://www.youtube.com/watch?v=wanted-route"
    await crud.ingest_resolution(_payload("youtube:wanted-route", url), url)

    response = client.get(
        "/internal/transcript-wanted", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 200
    pages = response.json()["pages"]
    assert [p for p in pages if p["external_id"] == "youtube:wanted-route"]


async def test_transcript_wanted_route_explicit_youtube_param_unchanged():
    # ?platform=youtube (or omitted) must return the same queue.
    url = "https://www.youtube.com/watch?v=wanted-route-explicit"
    await crud.ingest_resolution(_payload("youtube:wanted-route-explicit", url), url)

    no_param = client.get(
        "/internal/transcript-wanted", headers={"Authorization": "Bearer test-token"}
    )
    explicit = client.get(
        "/internal/transcript-wanted",
        params={"platform": "youtube"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert no_param.status_code == explicit.status_code == 200
    assert no_param.json() == explicit.json()
    assert [
        p
        for p in explicit.json()["pages"]
        if p["external_id"] == "youtube:wanted-route-explicit"
    ]


async def test_transcript_wanted_route_platform_vimeo_returns_vimeo_queue():
    url = "https://vimeo.com/wanted-route-vimeo"
    await crud.ingest_resolution(
        _payload(
            "vimeo:wanted-route",
            url,
            platform="vimeo",
            video_format="vimeo",
        ),
        url,
    )

    response = client.get(
        "/internal/transcript-wanted",
        params={"platform": "vimeo"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    pages = response.json()["pages"]
    assert [p for p in pages if p["external_id"] == "vimeo:wanted-route"]
    # And the youtube-only route must not carry this Vimeo page.
    youtube_response = client.get(
        "/internal/transcript-wanted", headers={"Authorization": "Bearer test-token"}
    )
    assert not [
        p
        for p in youtube_response.json()["pages"]
        if p["external_id"] == "vimeo:wanted-route"
    ]


def test_transcript_wanted_route_rejects_invalid_platform_with_422():
    response = client.get(
        "/internal/transcript-wanted",
        params={"platform": "bogus"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 422
