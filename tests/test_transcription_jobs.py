"""Real DB integration tests for the on-demand-transcription job lifecycle
(archive/db/crud.py's TranscriptionJob functions) -- against the isolated
SQLite file set up by tests/conftest.py's _archive_db_schema fixture, not
mocked. Each test uses its own unique external_id/source_url so tests can
run in any order without colliding (the fixture DB isn't reset per-test).
"""

from archive.db import crud


async def _drain_job(job_id: int, total_chunks: int) -> dict:
    """Runs a job's remaining chunks to completion -- tests that only care
    about a job's *initial* state still need to free its concurrency-cap
    slot (MAX_CONCURRENT_TRANSCRIPTION_JOBS) before later tests run, since
    the fixture DB is shared across the whole file, not reset per test."""
    result = {}
    for _ in range(total_chunks):
        claim = await crud.claim_next_chunk()
        assert claim is not None and claim["job_id"] == job_id
        result = await crud.report_chunk_result(job_id, success=True, shifted_segments=[])
    return result


def _payload(external_id: str, source_url: str) -> dict:
    return {
        "platform": "granicus",
        "source_url": source_url,
        "external_id": external_id,
        "title": "Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "City of Test",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }


async def test_create_job_known_email_skips_confirmation():
    url = "https://example.granicus.com/player/clip/tj-1"
    job = await crud.create_transcription_job(
        payload=_payload("granicus:tj-1", url), input_url_normalized=url,
        requester_email="known@example.com", media_url="https://example.com/v.m3u8",
        media_kind="video", probed_duration_seconds=1900, chunk_size_seconds=900,
        skip_confirmation=True,
    )
    assert job["status"] == "queued"
    assert job["total_chunks"] == 3  # ceil(1900 / 900)
    await _drain_job(job["job_id"], job["total_chunks"])


async def test_create_job_new_email_requires_confirmation():
    url = "https://example.granicus.com/player/clip/tj-2"
    job = await crud.create_transcription_job(
        payload=_payload("granicus:tj-2", url), input_url_normalized=url,
        requester_email="new@example.com", media_url="https://example.com/v.m3u8",
        media_kind="video", probed_duration_seconds=600, chunk_size_seconds=900,
        skip_confirmation=False,
    )
    assert job["status"] == "pending_confirmation"


async def test_duplicate_submit_returns_existing_job_not_a_new_one():
    url = "https://example.granicus.com/player/clip/tj-3"
    payload = _payload("granicus:tj-3", url)
    job1 = await crud.create_transcription_job(
        payload=payload, input_url_normalized=url, requester_email="a@example.com",
        media_url="https://example.com/v.m3u8", media_kind="video",
        probed_duration_seconds=600, chunk_size_seconds=900, skip_confirmation=True,
    )
    job2 = await crud.create_transcription_job(
        payload=payload, input_url_normalized=url, requester_email="b@example.com",
        media_url="https://example.com/v.m3u8", media_kind="video",
        probed_duration_seconds=600, chunk_size_seconds=900, skip_confirmation=True,
    )
    assert job1["job_id"] == job2["job_id"]
    await _drain_job(job1["job_id"], job1["total_chunks"])


async def test_claim_next_chunk_prefers_higher_priority_over_older_job():
    # Real feature built 2026-08-09 once Alembic unblocked adding the
    # column (see BACKLOG_DONE.md): claim_next_chunk() must order by
    # priority first, not just created_at -- a real visitor's own request
    # (PRIORITY_MEDIUM) should never sit behind older self-generated
    # PRIORITY_LOW batch work (not built yet, but the ordering needs to
    # be correct now regardless). create_transcription_job() itself
    # always sets PRIORITY_MEDIUM (the only real call site today), so the
    # low-priority job here is inserted directly, mirroring how
    # test_list_pages_search.py reaches into the DB directly for a
    # scenario the public API doesn't expose on its own.
    from archive.db.engine import async_session
    from archive.db.models import TranscriptionJob

    old_url = "https://example.granicus.com/player/clip/tj-priority-old"
    old_job = await crud.create_transcription_job(
        payload=_payload("granicus:tj-priority-old", old_url), input_url_normalized=old_url,
        requester_email="old@example.com", media_url="https://example.com/v.m3u8",
        media_kind="video", probed_duration_seconds=600, chunk_size_seconds=900,
        skip_confirmation=True,
    )
    async with async_session() as session:
        job = await session.get(TranscriptionJob, old_job["job_id"])
        job.priority = crud.PRIORITY_LOW
        await session.commit()

    new_url = "https://example.granicus.com/player/clip/tj-priority-new"
    new_job = await crud.create_transcription_job(
        payload=_payload("granicus:tj-priority-new", new_url), input_url_normalized=new_url,
        requester_email="new@example.com", media_url="https://example.com/v.m3u8",
        media_kind="video", probed_duration_seconds=600, chunk_size_seconds=900,
        skip_confirmation=True,
    )

    # The older, low-priority job was created first, so a naive
    # created_at-only ordering would claim it first -- priority must win.
    # Both jobs have exactly one chunk (ceil(600 / 900) == 1), so this one
    # claim_next_chunk() call already claimed new_job's only chunk --
    # report it directly rather than re-claiming via _drain_job.
    assert old_job["total_chunks"] == 1 and new_job["total_chunks"] == 1
    claim = await crud.claim_next_chunk()
    assert claim["job_id"] == new_job["job_id"]
    await crud.report_chunk_result(new_job["job_id"], success=True, shifted_segments=[])

    await _drain_job(old_job["job_id"], old_job["total_chunks"])


async def test_confirm_unknown_token_returns_none():
    assert await crud.confirm_transcription_job("definitely-not-a-real-token") is None


async def test_confirm_flips_status_and_clears_token():
    url = "https://example.granicus.com/player/clip/tj-4"
    await crud.create_transcription_job(
        payload=_payload("granicus:tj-4", url), input_url_normalized=url,
        requester_email="confirm-me@example.com", media_url="https://example.com/v.m3u8",
        media_kind="video", probed_duration_seconds=600, chunk_size_seconds=900,
        skip_confirmation=False,
    )
    # Fetch the token directly via a fresh claim attempt is indirect --
    # instead, look the job up through the DB session the same way the
    # confirmation endpoint's caller would: by re-deriving it from a second
    # create_transcription_job call (which returns the *same* existing job,
    # per the dedup test above), then confirm via a raw query for the token.
    from sqlalchemy import select

    from archive.db.engine import async_session
    from archive.db.models import TranscriptionJob

    async with async_session() as session:
        job_row = (
            await session.execute(
                select(TranscriptionJob).where(TranscriptionJob.requester_email == "confirm-me@example.com")
            )
        ).scalars().first()
        token = job_row.confirmation_token
    assert token is not None

    confirmed = await crud.confirm_transcription_job(token)
    assert confirmed["status"] == "queued"

    # a second confirm with the same (now-cleared) token must fail
    assert await crud.confirm_transcription_job(token) is None

    await _drain_job(confirmed["job_id"], confirmed["total_chunks"])


async def test_expired_pending_confirmation_is_superseded_and_unconfirmable():
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from archive.db.engine import async_session
    from archive.db.models import TranscriptionJob

    url = "https://example.granicus.com/player/clip/tj-expiry"
    payload = _payload("granicus:tj-expiry", url)
    old_job = await crud.create_transcription_job(
        payload=payload, input_url_normalized=url, requester_email="stale@example.com",
        media_url="https://example.com/v.m3u8", media_kind="video",
        probed_duration_seconds=600, chunk_size_seconds=900, skip_confirmation=False,
    )
    assert old_job["status"] == "pending_confirmation"

    async with async_session() as session:
        job_row = await session.get(TranscriptionJob, old_job["job_id"])
        token = job_row.confirmation_token
        job_row.created_at = datetime.now(timezone.utc) - timedelta(hours=49)
        await session.commit()

    # A fresh request for the same page should NOT see the expired job as
    # blocking -- it should create a brand new one instead of returning it.
    new_job = await crud.create_transcription_job(
        payload=payload, input_url_normalized=url, requester_email="fresh@example.com",
        media_url="https://example.com/v.m3u8", media_kind="video",
        probed_duration_seconds=600, chunk_size_seconds=900, skip_confirmation=True,
    )
    assert new_job["job_id"] != old_job["job_id"]
    assert new_job["status"] == "queued"

    # The old job's confirmation link should no longer work.
    assert await crud.confirm_transcription_job(token) is None

    await _drain_job(new_job["job_id"], new_job["total_chunks"])


async def test_full_chunk_lifecycle_promotes_transcribed_version():
    url = "https://example.granicus.com/player/clip/tj-5"
    job = await crud.create_transcription_job(
        payload=_payload("granicus:tj-5", url), input_url_normalized=url,
        requester_email="lifecycle@example.com", media_url="https://example.com/v.m3u8",
        media_kind="video", probed_duration_seconds=1900, chunk_size_seconds=900,
        skip_confirmation=True,
    )
    assert job["total_chunks"] == 3

    for i in range(3):
        claim = await crud.claim_next_chunk()
        assert claim["job_id"] == job["job_id"]
        assert claim["chunk_index"] == i
        shifted = [{"start": i * 900 + 1.0, "end": i * 900 + 2.0, "text": f"chunk {i}", "speaker": None}]
        result = await crud.report_chunk_result(claim["job_id"], success=True, shifted_segments=shifted)

    assert result["status"] == "completed"
    assert result["transcript_version_id"] is not None

    status = await crud.get_transcription_job_status(job["job_id"])
    assert status["status"] == "completed"
    assert status["chunks_completed"] == 3

    page = await crud.get_page_by_slug(job["meeting_page_slug"])
    transcribed = [v for v in page["versions"] if v["source"] == "transcribed"]
    assert len(transcribed) == 1
    assert transcribed[0]["is_default"] is True
    assert [s["start"] for s in transcribed[0]["segments"]] == [1.0, 901.0, 1801.0]


async def test_completed_job_detects_language_from_transcribed_text():
    # Real gap closed alongside the search-language fix earlier this
    # session (see BACKLOG_DONE.md): a transcribed version used to always
    # get language=None. Coherent English text here, unlike the other
    # lifecycle test's placeholder "chunk N" text, specifically so
    # real detection has enough real content to work with.
    url = "https://example.granicus.com/player/clip/tj-7"
    job = await crud.create_transcription_job(
        payload=_payload("granicus:tj-7", url), input_url_normalized=url,
        requester_email="language@example.com", media_url="https://example.com/v.m3u8",
        media_kind="video", probed_duration_seconds=900, chunk_size_seconds=900,
        skip_confirmation=True,
    )
    assert job["total_chunks"] == 1

    claim = await crud.claim_next_chunk()
    shifted = [{
        "start": 1.0, "end": 8.0,
        "text": "Good evening and welcome to tonight's regular city council meeting.",
        "speaker": None,
    }]
    await crud.report_chunk_result(claim["job_id"], success=True, shifted_segments=shifted)

    page = await crud.get_page_by_slug(job["meeting_page_slug"])
    transcribed = next(v for v in page["versions"] if v["source"] == "transcribed")
    assert transcribed["language"] == "en"


async def test_chunk_failures_fail_the_job_after_budget_exhausted():
    url = "https://example.granicus.com/player/clip/tj-6"
    job = await crud.create_transcription_job(
        payload=_payload("granicus:tj-6", url), input_url_normalized=url,
        requester_email="fails@example.com", media_url="https://example.com/v.m3u8",
        media_kind="video", probed_duration_seconds=2700, chunk_size_seconds=900,
        skip_confirmation=True,
    )
    assert job["total_chunks"] == 3

    result = None
    for _ in range(crud.MAX_CONSECUTIVE_CHUNK_FAILURES):
        claim = await crud.claim_next_chunk()
        assert claim["job_id"] == job["job_id"]
        result = await crud.report_chunk_result(claim["job_id"], success=False, error="ffmpeg exploded")

    assert result["status"] == "failed"
    status = await crud.get_transcription_job_status(job["job_id"])
    assert status["status"] == "failed"

    # a failed job no longer shows up to claim_next_chunk
    assert await crud.claim_next_chunk() is None
