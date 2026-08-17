"""Tests for the "transcript wanted" queue: crud.list_youtube_pages_
missing_transcripts() (real DB integration, isolated SQLite fixture --
same pattern as tests/test_lookup_has_transcript.py) and the token-gated
GET /internal/transcript-wanted route on top of it. Consumed by
scripts/fetch_youtube_transcripts.py, which fetches captions from a
residential IP because Render's cloud IP is confirmed blocked by YouTube
(see BACKLOG_DONE.md's 2026-08-10 experiment entry).
"""

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud

client = TestClient(archive.main.app)


def _payload(
    external_id: str, source_url: str, *, video_format="youtube", segments=None
) -> dict:
    return {
        "platform": "youtube",
        "source_url": source_url,
        "external_id": external_id,
        "title": "Wanted-Queue Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "City of Test",
        "video_url": "https://www.youtube.com/embed/AAAAAAAAAAA",
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
