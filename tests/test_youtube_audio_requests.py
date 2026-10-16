"""WO-1969: readers' "Request Transcript from Audio" presses on YouTube
meetings are recorded for the drip Mac instead of failing.

Three layers:
  * the Archive's crud functions and token-gated routes (real DB, the
    isolated SQLite fixture from conftest.py, same pattern as
    tests/test_transcript_wanted.py);
  * the resolver's /api/transcription/check-feasibility route, with the
    Archive client and the platform finders replaced by fakes, to prove a
    YouTube meeting is recorded without any resolve or probe (a resolve or
    probe of a YouTube URL is a YouTube request from the server);
  * the per-IP rate limit, which must still apply.

The meetings below are synthetic (hand-made ids and URLs). They exercise
the record/dedupe/link logic only; the page shapes reuse the ingest payload
the real tests in test_transcript_wanted.py already use.
"""

import pytest
from fastapi.testclient import TestClient

import app.main
import archive.main
from archive.db import crud

archive_client = TestClient(archive.main.app)
AUTH = {"Authorization": "Bearer test-token"}


def _payload(video_id: str, source_url: str, *, platform="youtube", segments=None):
    return {
        "platform": platform,
        "source_url": source_url,
        "external_id": f"youtube:{video_id}" if platform == "youtube" else video_id,
        "title": "Audio Request Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "City of Test",
        "video_url": f"https://www.youtube.com/embed/{video_id}",
        "video_format": "youtube",
        "segments": segments or [],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }


async def _open_slugs() -> dict:
    return {p["video_id"]: p for p in await crud.list_open_youtube_audio_requests()}


# --- Archive: crud --------------------------------------------------------


async def test_request_on_existing_youtube_page_is_recorded_and_listed():
    url = "https://www.youtube.com/watch?v=AReqAAAAAA1"
    await crud.ingest_resolution(_payload("AReqAAAAAA1", url), url)

    first = await crud.record_youtube_audio_request(url_normalized=url)
    assert first == {"youtube": True, "recorded": True, "new": True}

    open_ = await _open_slugs()
    item = open_["AReqAAAAAA1"]
    # The fields transcribe_backlog_locally.process_one() needs.
    assert item["slug"]
    assert item["source_url_normalized"]
    assert item["video_url"] == "https://www.youtube.com/embed/AReqAAAAAA1"
    assert item["video_format"] == "youtube"
    assert item["request_count"] == 1


async def test_repeat_request_for_same_video_is_deduped():
    url = "https://www.youtube.com/watch?v=AReqAAAAAA2"
    await crud.ingest_resolution(_payload("AReqAAAAAA2", url), url)

    await crud.record_youtube_audio_request(url_normalized=url)
    second = await crud.record_youtube_audio_request(url_normalized=url)
    # Same video by a different URL (no page alias for it): still one row.
    third = await crud.record_youtube_audio_request(
        url_normalized="https://youtu.be/AReqAAAAAA2", video_id="AReqAAAAAA2"
    )
    assert second["new"] is False and third["new"] is False

    items = [
        p
        for p in await crud.list_open_youtube_audio_requests()
        if p["video_id"] == "AReqAAAAAA2"
    ]
    assert len(items) == 1
    assert items[0]["request_count"] == 3


async def test_non_youtube_page_is_not_recorded():
    url = "https://example.granicus.com/player/clip/9990001"
    payload = _payload("AReqAAAAAA3", url, platform="granicus")
    payload["video_format"] = "mp4"
    payload["video_url"] = "https://example.granicus.com/media/9990001.mp4"
    await crud.ingest_resolution(payload, url)

    got = await crud.record_youtube_audio_request(url_normalized=url)
    assert got["youtube"] is False and got["recorded"] is False


async def test_request_before_page_exists_is_linked_later():
    url = "https://www.youtube.com/watch?v=AReqAAAAAA4"
    got = await crud.record_youtube_audio_request(
        url_normalized=url, video_id="AReqAAAAAA4"
    )
    assert got["recorded"] is True
    # No page yet: nothing the drip could transcribe onto.
    assert "AReqAAAAAA4" not in await _open_slugs()

    await crud.ingest_resolution(_payload("AReqAAAAAA4", url), url)
    assert "AReqAAAAAA4" in await _open_slugs()


async def test_no_page_and_no_video_id_is_not_recorded():
    got = await crud.record_youtube_audio_request(
        url_normalized="https://example.com/not-a-meeting-wo1969"
    )
    assert got == {"youtube": False, "recorded": False, "new": False}


async def test_request_drops_off_once_page_has_our_audio_transcript():
    url = "https://www.youtube.com/watch?v=AReqAAAAAA5"
    await crud.ingest_resolution(_payload("AReqAAAAAA5", url), url)
    await crud.record_youtube_audio_request(url_normalized=url)
    assert "AReqAAAAAA5" in await _open_slugs()

    # The drip's audio transcript lands as the default "transcribed" version.
    from archive.db.engine import async_session
    from archive.db.models import TranscriptVersion
    from sqlalchemy import update

    async with async_session() as session:
        mp = await crud._page_for_url(session, url)
        await session.execute(
            update(TranscriptVersion)
            .where(TranscriptVersion.meeting_page_id == mp.id)
            .values(is_default=False)
        )
        session.add(
            TranscriptVersion(
                meeting_page_id=mp.id,
                language="en",
                source="transcribed",
                is_default=True,
                segments=[{"start": 0, "end": 1, "text": "from the audio"}],
                content_hash="wo1969-test-hash",
            )
        )
        await session.commit()

    assert "AReqAAAAAA5" not in await _open_slugs()
    again = await crud.record_youtube_audio_request(url_normalized=url)
    assert again["reason"] == "already_transcribed"


# --- Archive: routes ------------------------------------------------------


def test_routes_need_the_token():
    assert archive_client.get("/internal/youtube-audio-requests").status_code == 404
    assert (
        archive_client.post(
            "/internal/youtube-audio-requests",
            json={"url_normalized": "https://www.youtube.com/watch?v=AReqAAAAAA6"},
        ).status_code
        == 404
    )


async def test_routes_record_and_list():
    url = "https://www.youtube.com/watch?v=AReqAAAAAA7"
    await crud.ingest_resolution(_payload("AReqAAAAAA7", url), url)
    r = archive_client.post(
        "/internal/youtube-audio-requests",
        json={"url_normalized": url, "video_id": "AReqAAAAAA7"},
        headers=AUTH,
    )
    assert r.status_code == 200 and r.json()["recorded"] is True
    listed = archive_client.get("/internal/youtube-audio-requests", headers=AUTH)
    assert listed.status_code == 200
    assert [p for p in listed.json()["pages"] if p["video_id"] == "AReqAAAAAA7"]


# --- resolver: check-feasibility ------------------------------------------


@pytest.fixture
def resolver(monkeypatch):
    """The resolver app with the rate limiter off, the Archive client faked,
    and every finder/probe made to fail loudly if reached."""
    monkeypatch.setattr(app.main.limiter, "enabled", False)
    calls = []

    async def fake_record(url_normalized, video_id=None):
        calls.append((url_normalized, video_id))
        return fake_record.answer

    fake_record.answer = {"youtube": True, "recorded": True, "new": True}
    monkeypatch.setattr(
        app.main.archive_client, "record_youtube_audio_request", fake_record
    )

    def no_finder(platform):
        raise AssertionError(f"resolved {platform}: that would be a network request")

    monkeypatch.setattr(app.main, "get_finder", no_finder)
    return TestClient(app.main.app), calls, fake_record


def _check(client, url):
    return client.post("/api/transcription/check-feasibility", json={"url": url})


def test_youtube_request_is_noted_without_resolving(resolver):
    client, calls, _ = resolver
    r = _check(client, "https://www.youtube.com/watch?v=AReqAAAAAA8")
    body = r.json()
    assert body["ok"] is False and body["queued"] is True
    assert "noted" in body["message"]
    assert "can't promise a date" in body["message"]
    assert calls and calls[0][1] == "AReqAAAAAA8"


def test_youtube_request_with_archive_down_still_never_resolves(resolver):
    client, _, fake = resolver
    fake.answer = None
    body = _check(client, "https://www.youtube.com/watch?v=AReqAAAAAA9").json()
    assert body["ok"] is False and "queued" not in body
    assert "try again later" in body["message"]


def test_wrapper_page_archive_knows_is_youtube_is_not_resolved(resolver):
    client, calls, _ = resolver
    body = _check(
        client, "https://example.primegov.com/Portal/Meeting?meetingTemplateId=1"
    ).json()
    assert body["queued"] is True
    assert calls[0][1] is None  # not a youtube.com URL: the Archive decides


def test_non_youtube_meeting_goes_on_to_the_normal_check(resolver):
    client, _, fake = resolver
    fake.answer = {"youtube": False, "recorded": False, "new": False}
    with pytest.raises(AssertionError, match="resolved"):
        _check(client, "https://example.granicus.com/player/clip/9990002")


def test_submit_refuses_youtube_without_resolving(resolver):
    client, _, _ = resolver
    r = client.post(
        "/api/transcription/submit",
        json={
            "url": "https://www.youtube.com/watch?v=AReqAAAAAB1",
            "email": "reader@example.com",
        },
    )
    assert r.status_code == 400


def test_check_feasibility_keeps_its_per_ip_rate_limit(monkeypatch):
    async def fake_record(url_normalized, video_id=None):
        return {"youtube": True, "recorded": True, "new": False}

    monkeypatch.setattr(
        app.main.archive_client, "record_youtube_audio_request", fake_record
    )
    app.main.limiter.reset()
    client = TestClient(app.main.app)
    codes = [
        _check(client, "https://www.youtube.com/watch?v=AReqAAAAAB2").status_code
        for _ in range(6)
    ]
    app.main.limiter.reset()
    assert codes[:5] == [200] * 5
    assert codes[5] == 429
