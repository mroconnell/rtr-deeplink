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
    # PRIORITY_LOW batch work.
    old_url = "https://example.granicus.com/player/clip/tj-priority-old"
    old_job = await crud.create_transcription_job(
        payload=_payload("granicus:tj-priority-old", old_url), input_url_normalized=old_url,
        requester_email="old@example.com", media_url="https://example.com/v.m3u8",
        media_kind="video", probed_duration_seconds=600, chunk_size_seconds=900,
        skip_confirmation=True, priority=crud.PRIORITY_LOW,
    )

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
    # Real bug fixed 2026-08-11: _job_dict() never included this key, so
    # worker/main.py's completion-email excerpt lookup always got None
    # and rendered empty -- see crud.py's _job_dict() for the fix.
    assert status["transcript_version_id"] == result["transcript_version_id"]

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


# --- Auto-idle-time job generation (built 2026-08-09, see BACKLOG_DONE.md) ---


async def test_find_auto_transcription_candidate_skips_page_with_good_transcript():
    url = "https://example.granicus.com/player/clip/auto-good-transcript"
    await crud.ingest_resolution(
        {
            "platform": "granicus", "source_url": url, "external_id": "granicus:auto-good-transcript",
            "title": "T", "date": "2026-01-01", "jurisdiction": "City of Test",
            "video_url": "https://example.com/v.m3u8", "video_format": "m3u8",
            "segments": [{"start": 0, "end": 1, "text": "hello there"}], "agenda_items": [],
            "transcript_language": "en", "transcript_warnings": [],
        },
        url,
    )
    slug = (await crud.lookup_page_for_url(url))["slug"]

    candidate = await crud.find_auto_transcription_candidate()
    # Some other test's page could legitimately come back first (oldest-
    # first across the whole shared fixture DB) -- the real assertion is
    # that *this* page specifically is never returned, not that nothing is.
    assert candidate is None or candidate["slug"] != slug


async def test_find_auto_transcription_candidate_returns_page_missing_transcript():
    # The shared fixture DB (see conftest.py) accumulates pages from every
    # other test in the whole session, including plenty of other
    # transcript-less ones -- asserting *this* page comes back first would
    # be fragile against test execution order. Test the underlying
    # eligibility directly instead: the same helpers
    # find_auto_transcription_candidate() itself calls per-page.
    from archive.db.engine import async_session
    from archive.db.models import MeetingPage
    from sqlalchemy import select

    url = "https://example.granicus.com/player/clip/auto-no-transcript"
    await crud.ingest_resolution(
        {
            "platform": "granicus", "source_url": url, "external_id": "granicus:auto-no-transcript",
            "title": "T", "date": "2026-01-01", "jurisdiction": "City of Test",
            "video_url": "https://example.com/v.m3u8", "video_format": "m3u8",
            "segments": [], "agenda_items": [], "transcript_language": None, "transcript_warnings": [],
        },
        url,
    )
    slug = (await crud.lookup_page_for_url(url))["slug"]

    async with async_session() as session:
        page = (await session.execute(select(MeetingPage).where(MeetingPage.slug == slug))).scalars().first()
        assert await crud._has_good_transcript(session, page.id) is False
        assert await crud._in_auto_transcription_cooldown(session, page.id) is False

    # And a real end-to-end call returns *some* legitimate candidate, not
    # nothing -- there's at least one qualifying page in the DB right now
    # (the one just created above, if nothing else).
    assert await crud.find_auto_transcription_candidate() is not None


async def test_find_auto_transcription_candidate_skips_page_in_cooldown():
    from archive.db.engine import async_session
    from archive.db.models import MeetingPage
    from sqlalchemy import select

    url = "https://example.granicus.com/player/clip/auto-cooldown"
    await crud.ingest_resolution(
        {
            "platform": "granicus", "source_url": url, "external_id": "granicus:auto-cooldown",
            "title": "T", "date": "2026-01-01", "jurisdiction": "City of Test",
            "video_url": "https://example.com/v.m3u8", "video_format": "m3u8",
            "segments": [], "agenda_items": [], "transcript_language": None, "transcript_warnings": [],
        },
        url,
    )
    slug = (await crud.lookup_page_for_url(url))["slug"]

    job = await crud.create_transcription_job(
        payload=_payload("granicus:auto-cooldown", url), input_url_normalized=url,
        requester_email="auto@example.com", media_url="https://example.com/v.m3u8",
        media_kind="video", probed_duration_seconds=900, chunk_size_seconds=900,
        skip_confirmation=True, priority=crud.PRIORITY_LOW,
    )
    for _ in range(crud.MAX_CONSECUTIVE_CHUNK_FAILURES):
        claim = await crud.claim_next_chunk()
        assert claim["job_id"] == job["job_id"]
        await crud.report_chunk_result(job["job_id"], success=False, error="simulated failure")

    status = await crud.get_transcription_job_status(job["job_id"])
    assert status["status"] == "failed"

    # Freshly failed -- still well within the 1-day base cooldown.
    async with async_session() as session:
        page = (await session.execute(select(MeetingPage).where(MeetingPage.slug == slug))).scalars().first()
        assert await crud._in_auto_transcription_cooldown(session, page.id) is True


async def test_create_failed_auto_transcription_job_is_immediately_failed():
    url = "https://example.granicus.com/player/clip/auto-fail-direct"
    await crud.ingest_resolution(
        {
            "platform": "granicus", "source_url": url, "external_id": "granicus:auto-fail-direct",
            "title": "T", "date": "2026-01-01", "jurisdiction": "City of Test",
            "video_url": "https://example.com/v.m3u8", "video_format": "m3u8",
            "segments": [], "agenda_items": [], "transcript_language": None, "transcript_warnings": [],
        },
        url,
    )
    slug = (await crud.lookup_page_for_url(url))["slug"]

    # get_page_by_slug()'s dict doesn't carry the raw MeetingPage.id, so
    # look it up the same way find_auto_transcription_candidate() would.
    from archive.db.engine import async_session
    from archive.db.models import MeetingPage
    from sqlalchemy import select

    async with async_session() as session:
        row = (await session.execute(select(MeetingPage).where(MeetingPage.slug == slug))).scalars().first()
        page_id = row.id

    result = await crud.create_failed_auto_transcription_job(
        meeting_page_id=page_id, requester_email="auto@example.com", error_message="No usable media source found.",
    )
    status = await crud.get_transcription_job_status(result["job_id"])
    assert status["status"] == "failed"
    assert status["error_message"] == "No usable media source found."
    # Never claimable -- it was never queued in the first place.
    assert await crud.claim_next_chunk() is None or (await crud.claim_next_chunk())["job_id"] != result["job_id"]


async def test_in_auto_transcription_cooldown_escalates_with_consecutive_failures():
    # Directly exercises the escalation math (crud._in_auto_transcription_
    # cooldown) rather than waiting on real time to pass: a page with two
    # consecutive failed jobs, the most recent one 36 hours ago, must still
    # be in cooldown under the doubling rule (2nd failure => 2-day cooldown)
    # even though 36 hours would already clear a flat 1-day cooldown.
    from datetime import datetime, timedelta, timezone

    from archive.db.engine import async_session
    from archive.db.models import MeetingPage, TranscriptionJob
    from sqlalchemy import select

    url = "https://example.granicus.com/player/clip/auto-escalation"
    await crud.ingest_resolution(
        {
            "platform": "granicus", "source_url": url, "external_id": "granicus:auto-escalation",
            "title": "T", "date": "2026-01-01", "jurisdiction": "City of Test",
            "video_url": "https://example.com/v.m3u8", "video_format": "m3u8",
            "segments": [], "agenda_items": [], "transcript_language": None, "transcript_warnings": [],
        },
        url,
    )
    slug = (await crud.lookup_page_for_url(url))["slug"]

    async with async_session() as session:
        page = (await session.execute(select(MeetingPage).where(MeetingPage.slug == slug))).scalars().first()
        page_id = page.id

        old_failure = TranscriptionJob(
            meeting_page_id=page_id, requester_email="auto@example.com", status="failed",
            media_url="", media_kind="video", probed_duration_seconds=0, chunk_size_seconds=1, total_chunks=1,
        )
        session.add(old_failure)
        await session.commit()

        recent_failure = TranscriptionJob(
            meeting_page_id=page_id, requester_email="auto@example.com", status="failed",
            media_url="", media_kind="video", probed_duration_seconds=0, chunk_size_seconds=1, total_chunks=1,
        )
        session.add(recent_failure)
        await session.commit()
        # Backdate both -- created_at ordering must put recent_failure last
        # (it's the one _in_auto_transcription_cooldown should key off of).
        old_failure.created_at = datetime.now(timezone.utc) - timedelta(hours=48)
        old_failure.updated_at = old_failure.created_at
        recent_failure.created_at = datetime.now(timezone.utc) - timedelta(hours=36)
        recent_failure.updated_at = recent_failure.created_at
        await session.commit()

        in_cooldown = await crud._in_auto_transcription_cooldown(session, page_id)

    assert in_cooldown is True  # 2 consecutive failures => 2-day cooldown, 36h in is still inside it
