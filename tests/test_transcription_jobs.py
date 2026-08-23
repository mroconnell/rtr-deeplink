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
        result = await crud.report_chunk_result(
            job_id, success=True, shifted_segments=[]
        )
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
        payload=_payload("granicus:tj-1", url),
        input_url_normalized=url,
        requester_email="known@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=1900,
        chunk_size_seconds=900,
        skip_confirmation=True,
    )
    assert job["status"] == "queued"
    assert job["total_chunks"] == 3  # ceil(1900 / 900)
    await _drain_job(job["job_id"], job["total_chunks"])


async def test_create_job_new_email_requires_confirmation():
    url = "https://example.granicus.com/player/clip/tj-2"
    job = await crud.create_transcription_job(
        payload=_payload("granicus:tj-2", url),
        input_url_normalized=url,
        requester_email="new@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=600,
        chunk_size_seconds=900,
        skip_confirmation=False,
    )
    assert job["status"] == "pending_confirmation"


async def test_duplicate_submit_returns_existing_job_not_a_new_one():
    url = "https://example.granicus.com/player/clip/tj-3"
    payload = _payload("granicus:tj-3", url)
    job1 = await crud.create_transcription_job(
        payload=payload,
        input_url_normalized=url,
        requester_email="a@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=600,
        chunk_size_seconds=900,
        skip_confirmation=True,
    )
    job2 = await crud.create_transcription_job(
        payload=payload,
        input_url_normalized=url,
        requester_email="b@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=600,
        chunk_size_seconds=900,
        skip_confirmation=True,
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
        payload=_payload("granicus:tj-priority-old", old_url),
        input_url_normalized=old_url,
        requester_email="old@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=600,
        chunk_size_seconds=900,
        skip_confirmation=True,
        priority=crud.PRIORITY_LOW,
    )

    new_url = "https://example.granicus.com/player/clip/tj-priority-new"
    new_job = await crud.create_transcription_job(
        payload=_payload("granicus:tj-priority-new", new_url),
        input_url_normalized=new_url,
        requester_email="new@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=600,
        chunk_size_seconds=900,
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


def test_claim_next_chunk_locks_for_update_skip_locked_on_postgres_only():
    # Real fix, 2026-08-20: claim_next_chunk() used to be a plain
    # SELECT-then-UPDATE, safe for exactly one worker process (its own
    # docstring said so) but with a real TOCTOU window if a second
    # process ever called it concurrently -- both could read the same
    # row before either committed its claim. Multi-worker concurrency is
    # now the whole point (see BACKLOG.md's "Render worker plan sizing"
    # follow-up), so the claim query must take FOR UPDATE SKIP LOCKED so
    # two concurrent transactions lock, not double-claim, the same row.
    # No live Postgres available to this suite (SQLite-only, see
    # tests/conftest.py), so this pins the compiled SQL shape instead --
    # same pattern as test_auto_candidate_and_cooldown_queries_never_
    # touch_transcript_json() above. SQLite doesn't support SKIP LOCKED
    # at all (matches _fts_available()'s dialect gate), so the gate is
    # required, not just an optimization.
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    from archive.db.models import TranscriptionJob

    base_stmt = (
        select(TranscriptionJob)
        .order_by(TranscriptionJob.priority.desc(), TranscriptionJob.created_at.asc())
        .limit(1)
    )

    locked_sql = str(
        base_stmt.with_for_update(skip_locked=True).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "FOR UPDATE SKIP LOCKED" in locked_sql, locked_sql

    unlocked_sql = str(base_stmt.compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" not in unlocked_sql, unlocked_sql


async def test_confirm_unknown_token_returns_none():
    assert await crud.confirm_transcription_job("definitely-not-a-real-token") is None


async def test_confirm_flips_status_and_clears_token():
    url = "https://example.granicus.com/player/clip/tj-4"
    await crud.create_transcription_job(
        payload=_payload("granicus:tj-4", url),
        input_url_normalized=url,
        requester_email="confirm-me@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=600,
        chunk_size_seconds=900,
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
            (
                await session.execute(
                    select(TranscriptionJob).where(
                        TranscriptionJob.requester_email == "confirm-me@example.com"
                    )
                )
            )
            .scalars()
            .first()
        )
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
        payload=payload,
        input_url_normalized=url,
        requester_email="stale@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=600,
        chunk_size_seconds=900,
        skip_confirmation=False,
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
        payload=payload,
        input_url_normalized=url,
        requester_email="fresh@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=600,
        chunk_size_seconds=900,
        skip_confirmation=True,
    )
    assert new_job["job_id"] != old_job["job_id"]
    assert new_job["status"] == "queued"

    # The old job's confirmation link should no longer work.
    assert await crud.confirm_transcription_job(token) is None

    await _drain_job(new_job["job_id"], new_job["total_chunks"])


async def test_full_chunk_lifecycle_promotes_transcribed_version():
    url = "https://example.granicus.com/player/clip/tj-5"
    job = await crud.create_transcription_job(
        payload=_payload("granicus:tj-5", url),
        input_url_normalized=url,
        requester_email="lifecycle@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=1900,
        chunk_size_seconds=900,
        skip_confirmation=True,
    )
    assert job["total_chunks"] == 3

    for i in range(3):
        claim = await crud.claim_next_chunk()
        assert claim["job_id"] == job["job_id"]
        assert claim["chunk_index"] == i
        shifted = [
            {
                "start": i * 900 + 1.0,
                "end": i * 900 + 2.0,
                "text": f"chunk {i}",
                "speaker": None,
            }
        ]
        result = await crud.report_chunk_result(
            claim["job_id"], success=True, shifted_segments=shifted
        )

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


async def test_claim_next_chunk_exposes_partial_segments_for_dedup():
    # Real bug fixed 2026-08-16 (see BACKLOG_DONE.md, and worker/segment_
    # utils.py's own "Seam-duplication dedup" note): worker/main.py needs
    # the previous chunk's already-persisted segments to detect a real
    # seam-duplicate before it ever calls report_chunk_result() for the
    # next chunk -- claim_next_chunk() has to actually return them.
    url = "https://example.granicus.com/player/clip/tj-dedup-1"
    job = await crud.create_transcription_job(
        payload=_payload("granicus:tj-dedup-1", url),
        input_url_normalized=url,
        requester_email="dedup1@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=1800,
        chunk_size_seconds=900,
        skip_confirmation=True,
    )
    claim = await crud.claim_next_chunk()
    assert claim["job_id"] == job["job_id"]
    assert claim["partial_segments"] == []  # nothing persisted yet on the first chunk

    first_chunk_segments = [
        {"start": 1.0, "end": 2.0, "text": "First chunk content.", "speaker": None}
    ]
    await crud.report_chunk_result(
        job["job_id"], success=True, shifted_segments=first_chunk_segments
    )

    claim2 = await crud.claim_next_chunk()
    assert claim2["job_id"] == job["job_id"]
    assert claim2["partial_segments"] == first_chunk_segments

    # Finish the job (frees its MAX_CONCURRENT_TRANSCRIPTION_JOBS slot for
    # later tests in this file, same reasoning as _drain_job() above).
    await crud.report_chunk_result(job["job_id"], success=True, shifted_segments=[])


async def test_report_chunk_result_drops_seam_duplicate_tail():
    # End-to-end check that drop_previous_tail actually removes the stale
    # duplicate from the DB row, not just from an in-memory list -- the
    # real mechanism worker/main.py relies on (see its own process_next_
    # chunk(), and worker/segment_utils.py's count_seam_overlap_segments()
    # for how drop_previous_tail gets computed from real content).
    url = "https://example.granicus.com/player/clip/tj-dedup-2"
    job = await crud.create_transcription_job(
        payload=_payload("granicus:tj-dedup-2", url),
        input_url_normalized=url,
        requester_email="dedup2@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=1800,
        chunk_size_seconds=900,
        skip_confirmation=True,
    )
    claim = await crud.claim_next_chunk()
    assert claim["job_id"] == job["job_id"]
    stale_and_kept = [
        {"start": 1.0, "end": 2.0, "text": "Kept, unrelated content.", "speaker": None},
        {
            "start": 895.0,
            "end": 899.0,
            "text": "This is the duplicated tail sentence.",
            "speaker": None,
        },
    ]
    await crud.report_chunk_result(
        job["job_id"], success=True, shifted_segments=stale_and_kept
    )

    claim2 = await crud.claim_next_chunk()
    assert claim2["partial_segments"] == stale_and_kept

    new_chunk_segments = [
        {
            "start": 900.0,
            "end": 903.0,
            "text": "This is the next chunk.",
            "speaker": None,
        }
    ]
    # Simulates worker/main.py dropping the one stale segment it detected.
    result = await crud.report_chunk_result(
        job["job_id"],
        success=True,
        shifted_segments=new_chunk_segments,
        drop_previous_tail=1,
    )
    assert result["status"] == "completed"

    page = await crud.get_page_by_slug(job["meeting_page_slug"])
    transcribed = next(v for v in page["versions"] if v["source"] == "transcribed")
    texts = [s["text"] for s in transcribed["segments"]]
    assert texts == ["Kept, unrelated content.", "This is the next chunk."]
    assert "This is the duplicated tail sentence." not in texts


async def test_list_completed_multichunk_transcription_jobs_filters_correctly():
    # Backs GET /internal/transcription/completed-multichunk (archive/
    # main.py), added 2026-08-16 alongside the seam-duplication fix to
    # size how many already-completed jobs are real candidates for having
    # shipped the bug before the fix existed (see worker/segment_utils.py's
    # "Seam-duplication dedup" note and BACKLOG_DONE.md).
    multi_url = "https://example.granicus.com/player/clip/tj-audit-multi"
    single_url = "https://example.granicus.com/player/clip/tj-audit-single"

    multi_job = await crud.create_transcription_job(
        payload=_payload("granicus:tj-audit-multi", multi_url),
        input_url_normalized=multi_url,
        requester_email="audit-multi@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=1800,
        chunk_size_seconds=900,
        skip_confirmation=True,
    )
    assert multi_job["total_chunks"] == 2
    await _drain_job(multi_job["job_id"], 2)

    single_job = await crud.create_transcription_job(
        payload=_payload("granicus:tj-audit-single", single_url),
        input_url_normalized=single_url,
        requester_email="audit-single@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=800,
        chunk_size_seconds=900,
        skip_confirmation=True,
    )
    assert single_job["total_chunks"] == 1
    await _drain_job(single_job["job_id"], 1)

    audited = await crud.list_completed_multichunk_transcription_jobs()
    audited_job_ids = {row["job_id"] for row in audited}
    assert multi_job["job_id"] in audited_job_ids
    assert (
        single_job["job_id"] not in audited_job_ids
    )  # total_chunks == 1, never hit a chunk boundary

    row = next(r for r in audited if r["job_id"] == multi_job["job_id"])
    assert row["total_chunks"] == 2
    assert row["slug"] == multi_job["meeting_page_slug"]


async def test_list_hallucination_candidate_transcript_versions_filters_correctly():
    # Backs GET /internal/transcription/hallucination-candidates (archive/
    # main.py), added 2026-08-16 as the retroactive-audit counterpart to
    # list_completed_multichunk_transcription_jobs() above -- same template,
    # for the phase-cancellation hallucination bug instead of the
    # seam-duplication one (see BACKLOG.md's phase-cancellation write-up,
    # which flagged this audit as still open/not yet built).
    #
    # Three real populations exercised here:
    #  1. A "cloud worker" hallucinated version, produced via the real
    #     report_chunk_result() finalize path (same real hallucination-loop
    #     fixture as test_completed_job_flags_a_real_hallucinated_transcript
    #     above) -- already carries the warning today, since that check is
    #     already wired into this path going forward. already_flagged=True.
    #  2. A "local script" hallucinated version, pushed directly via
    #     ingest_resolution(source="transcribed") with transcript_warnings=[]
    #     -- simulates a version that shipped *before* detect_hallucination_
    #     warnings() existed (scripts/transcribe_backlog_locally.py wires
    #     this in too, but a pre-fix run wouldn't have). The audit must
    #     catch this retroactively even though the stored row itself carries
    #     no warning. already_flagged=False.
    #  3. A clean "local script" version (real clean fixture from
    #     test_completed_job_does_not_flag_a_real_clean_transcript above) --
    #     must not appear in the audit at all.
    worker_url = "https://example.granicus.com/player/clip/tj-halluc-audit-worker"
    worker_job = await crud.create_transcription_job(
        payload=_payload("granicus:tj-halluc-audit-worker", worker_url),
        input_url_normalized=worker_url,
        requester_email="halluc-audit-worker@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=900,
        chunk_size_seconds=900,
        skip_confirmation=True,
    )
    claim = await crud.claim_next_chunk()
    assert claim["job_id"] == worker_job["job_id"]
    hallucinated_segments = [
        {
            "start": 0.0,
            "end": 30.0,
            "text": "Public comment, motion, second, aye, nay, abstain,",
            "speaker": None,
        },
    ] + [
        {
            "start": 240.0 + i * 10,
            "end": 250.0 + i * 10,
            "text": "So, we are going to take a look at what we are going to do.",
            "speaker": None,
        }
        for i in range(44)
    ]
    worker_result = await crud.report_chunk_result(
        worker_job["job_id"],
        success=True,
        shifted_segments=hallucinated_segments,
    )
    assert worker_result["status"] == "completed"
    worker_version_id = worker_result["transcript_version_id"]

    local_url = "https://example.granicus.com/player/clip/tj-halluc-audit-local"
    local_result = await crud.ingest_resolution(
        {
            "platform": "granicus",
            "source_url": local_url,
            "external_id": "granicus:tj-halluc-audit-local",
            "title": "T",
            "date": "2026-01-01",
            "jurisdiction": "City of Test",
            "video_url": "https://example.com/v.m3u8",
            "video_format": "m3u8",
            "segments": hallucinated_segments,
            "agenda_items": [],
            "transcript_language": "en",
            "transcript_warnings": [],  # pre-fix: no warning stored
            "source": "transcribed",
        },
        local_url,
    )
    local_version_id = local_result["version_id"]
    assert local_version_id is not None

    clean_url = "https://example.granicus.com/player/clip/tj-halluc-audit-clean"
    clean_segments = [
        {
            "start": 300.0,
            "end": 309.52,
            "text": "Councillor Garling. Sorry, I'm confused now. So there is an access point off of Ogovi, and the drawing",
            "speaker": None,
        },
        {
            "start": 309.52,
            "end": 315.36,
            "text": "it says, there's not. So there would be access for, say, if, like, someone were delivering or",
            "speaker": None,
        },
        {
            "start": 315.36,
            "end": 318.56,
            "text": "for firefighting, you know, someone could, could access through, like, you know, like,",
            "speaker": None,
        },
        {
            "start": 318.56,
            "end": 322.80,
            "text": "that's supposed to be a fence or a gate or something, but a driveway access would be off of that",
            "speaker": None,
        },
        {
            "start": 322.80,
            "end": 328.40,
            "text": "lane portion to the off of Hastings. So I'm, I'm, I'm not in favor of this at all. I,",
            "speaker": None,
        },
        {
            "start": 328.40,
            "end": 334.08,
            "text": "I just, I don't know why we would. I get it's an unopened portion, um, but if you were, if you've",
            "speaker": None,
        },
    ]
    clean_result = await crud.ingest_resolution(
        {
            "platform": "granicus",
            "source_url": clean_url,
            "external_id": "granicus:tj-halluc-audit-clean",
            "title": "T",
            "date": "2026-01-01",
            "jurisdiction": "City of Test",
            "video_url": "https://example.com/v.m3u8",
            "video_format": "m3u8",
            "segments": clean_segments,
            "agenda_items": [],
            "transcript_language": "en",
            "transcript_warnings": [],
            "source": "transcribed",
        },
        clean_url,
    )
    clean_version_id = clean_result["version_id"]
    assert clean_version_id is not None

    audited = await crud.list_hallucination_candidate_transcript_versions()
    audited_version_ids = {row["version_id"] for row in audited}

    assert worker_version_id in audited_version_ids
    assert local_version_id in audited_version_ids
    assert clean_version_id not in audited_version_ids

    worker_row = next(r for r in audited if r["version_id"] == worker_version_id)
    assert worker_row["already_flagged"] is True
    assert worker_row["produced_by"] == "cloud_worker"
    assert worker_row["job_id"] == worker_job["job_id"]
    assert worker_row["slug"] == worker_job["meeting_page_slug"]

    local_row = next(r for r in audited if r["version_id"] == local_version_id)
    assert (
        local_row["already_flagged"] is False
    )  # pre-fix row, no warning stored -- caught retroactively
    assert local_row["produced_by"] == "local_script"
    assert local_row["job_id"] is None


async def test_hallucination_candidates_limit_bounds_unflagged_scan_not_flagged():
    # Regression test for the 2026-08-21 502 fix (BACKLOG_DONE.md): the
    # previous version of list_hallucination_candidate_transcript_versions()
    # pulled every source=="transcribed" row's full `segments` in one
    # unbounded query. The rewrite bounds only the NOT-yet-flagged
    # population (limit/after_id) since that's the big, actively-growing
    # side -- the small already-flagged population is still returned in
    # full regardless of `limit`, since it's cheap and never grows fast
    # (see the function's own docstring). This exercises both halves of
    # that claim against the real DB, not just by reading the SQL.
    anchor_url = "https://example.granicus.com/player/clip/tj-halluc-page-anchor"
    anchor_result = await crud.ingest_resolution(
        {
            "platform": "granicus",
            "source_url": anchor_url,
            "external_id": "granicus:tj-halluc-page-anchor",
            "title": "T",
            "date": "2026-01-01",
            "jurisdiction": "City of Test",
            "video_url": "https://example.com/v.m3u8",
            "video_format": "m3u8",
            "segments": [{"start": 0.0, "end": 1.0, "text": "anchor", "speaker": None}],
            "agenda_items": [],
            "transcript_language": "en",
            "transcript_warnings": [],
            "source": "transcribed",
        },
        anchor_url,
    )
    after_id = anchor_result["version_id"]  # everything below is created after this

    hallucinated_segments = [
        {
            "start": 0.0,
            "end": 30.0,
            "text": "Public comment, motion, second, aye, nay, abstain,",
            "speaker": None,
        },
    ] + [
        {
            "start": 240.0 + i * 10,
            "end": 250.0 + i * 10,
            "text": "So, we are going to take a look at what we are going to do.",
            "speaker": None,
        }
        for i in range(44)
    ]

    unflagged_ids = []
    for n in range(3):
        url = f"https://example.granicus.com/player/clip/tj-halluc-page-{n}"
        result = await crud.ingest_resolution(
            {
                "platform": "granicus",
                "source_url": url,
                "external_id": f"granicus:tj-halluc-page-{n}",
                "title": "T",
                "date": "2026-01-01",
                "jurisdiction": "City of Test",
                "video_url": "https://example.com/v.m3u8",
                "video_format": "m3u8",
                "segments": hallucinated_segments,
                "agenda_items": [],
                "transcript_language": "en",
                "transcript_warnings": [],  # not yet flagged
                "source": "transcribed",
            },
            url,
        )
        unflagged_ids.append(result["version_id"])

    flagged_url = "https://example.granicus.com/player/clip/tj-halluc-page-flagged"
    flagged_job = await crud.create_transcription_job(
        payload=_payload("granicus:tj-halluc-page-flagged", flagged_url),
        input_url_normalized=flagged_url,
        requester_email="halluc-page-flagged@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=900,
        chunk_size_seconds=900,
        skip_confirmation=True,
    )
    claim = await crud.claim_next_chunk()
    assert claim["job_id"] == flagged_job["job_id"]
    flagged_result = await crud.report_chunk_result(
        flagged_job["job_id"], success=True, shifted_segments=hallucinated_segments
    )
    flagged_id = flagged_result["transcript_version_id"]  # already carries the marker

    # First page: limit=2 over the unflagged population -- only the two
    # lowest unflagged version_ids should appear, but the flagged one
    # (much cheaper, unbounded) should appear on every page regardless.
    page1 = await crud.list_hallucination_candidate_transcript_versions(
        limit=2, after_id=after_id
    )
    page1_ids = {row["version_id"] for row in page1}
    assert page1_ids == {unflagged_ids[0], unflagged_ids[1], flagged_id}

    # Second page, keyset-paginated from the first page's max unflagged id:
    # the third unflagged row now appears; the flagged one still does too.
    page2 = await crud.list_hallucination_candidate_transcript_versions(
        limit=2, after_id=unflagged_ids[1]
    )
    page2_ids = {row["version_id"] for row in page2}
    assert page2_ids == {unflagged_ids[2], flagged_id}


async def test_hallucination_candidates_null_transcript_warnings_still_scanned():
    # Regression test: transcript_warnings is a nullable column
    # (archive/db/models.py), and `NULL LIKE '...'` (and its negation) is
    # SQL NULL, not False -- a naive `~cast(...).like(...)` predicate for
    # "not yet flagged" would silently drop every NULL-warnings row out of
    # WHERE entirely, meaning a real hallucinated transcript with no
    # transcript_warnings value at all (plausible for older rows) would
    # never be scanned, let alone surfaced. Exercised here by writing NULL
    # directly (ingest_resolution/report_chunk_result both coerce a
    # missing value to [] rather than None, so this state has to be
    # constructed directly against the same test DB to reproduce it).
    from archive.db.engine import async_session
    from archive.db.models import TranscriptVersion
    from sqlalchemy import update

    url = "https://example.granicus.com/player/clip/tj-halluc-null-warnings"
    hallucinated_segments = [
        {
            "start": 0.0,
            "end": 30.0,
            "text": "Public comment, motion, second, aye, nay, abstain,",
            "speaker": None,
        },
    ] + [
        {
            "start": 240.0 + i * 10,
            "end": 250.0 + i * 10,
            "text": "So, we are going to take a look at what we are going to do.",
            "speaker": None,
        }
        for i in range(44)
    ]
    result = await crud.ingest_resolution(
        {
            "platform": "granicus",
            "source_url": url,
            "external_id": "granicus:tj-halluc-null-warnings",
            "title": "T",
            "date": "2026-01-01",
            "jurisdiction": "City of Test",
            "video_url": "https://example.com/v.m3u8",
            "video_format": "m3u8",
            "segments": hallucinated_segments,
            "agenda_items": [],
            "transcript_language": "en",
            "transcript_warnings": [],
            "source": "transcribed",
        },
        url,
    )
    version_id = result["version_id"]

    async with async_session() as session:
        await session.execute(
            update(TranscriptVersion)
            .where(TranscriptVersion.id == version_id)
            .values(transcript_warnings=None)
        )
        await session.commit()

    audited = await crud.list_hallucination_candidate_transcript_versions()
    audited_version_ids = {row["version_id"] for row in audited}
    assert version_id in audited_version_ids
    row = next(r for r in audited if r["version_id"] == version_id)
    assert row["already_flagged"] is False


async def test_completed_job_detects_language_from_transcribed_text():
    # Real gap closed alongside the search-language fix earlier this
    # session (see BACKLOG_DONE.md): a transcribed version used to always
    # get language=None. Coherent English text here, unlike the other
    # lifecycle test's placeholder "chunk N" text, specifically so
    # real detection has enough real content to work with.
    url = "https://example.granicus.com/player/clip/tj-7"
    job = await crud.create_transcription_job(
        payload=_payload("granicus:tj-7", url),
        input_url_normalized=url,
        requester_email="language@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=900,
        chunk_size_seconds=900,
        skip_confirmation=True,
    )
    assert job["total_chunks"] == 1

    claim = await crud.claim_next_chunk()
    shifted = [
        {
            "start": 1.0,
            "end": 8.0,
            "text": "Good evening and welcome to tonight's regular city council meeting.",
            "speaker": None,
        }
    ]
    await crud.report_chunk_result(
        claim["job_id"], success=True, shifted_segments=shifted
    )

    page = await crud.get_page_by_slug(job["meeting_page_slug"])
    transcribed = next(v for v in page["versions"] if v["source"] == "transcribed")
    assert transcribed["language"] == "en"


async def test_completed_job_flags_a_real_hallucinated_transcript():
    # Real bug fixed 2026-08-16 (Port Coquitlam, BC -- see BACKLOG_DONE.md
    # and archive/utils/transcription_quality.py's own docstring): a
    # Whisper-produced transcript had no equivalent of the scraped-caption
    # path's is_likely_garbled() check before going live. This exercises
    # the real DB finalize path (report_chunk_result()), not just the pure
    # detection function directly -- confirms the archive-side duplicate
    # is actually wired in, not just present in the file.
    url = "https://example.granicus.com/player/clip/tj-halluc-1"
    job = await crud.create_transcription_job(
        payload=_payload("granicus:tj-halluc-1", url),
        input_url_normalized=url,
        requester_email="halluc1@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=900,
        chunk_size_seconds=900,
        skip_confirmation=True,
    )
    claim = await crud.claim_next_chunk()
    assert claim["job_id"] == job["job_id"]

    # Directly reproduced against the real Port Coquitlam audio while
    # investigating this bug: one real distinct sentence, then the same
    # sentence repeated verbatim -- a real, confirmed hallucination-loop
    # shape (see worker/segment_utils.py's matching real fixture for the
    # full provenance note).
    hallucinated_segments = [
        {
            "start": 0.0,
            "end": 30.0,
            "text": "Public comment, motion, second, aye, nay, abstain,",
            "speaker": None,
        },
    ] + [
        {
            "start": 240.0 + i * 10,
            "end": 250.0 + i * 10,
            "text": "So, we are going to take a look at what we are going to do.",
            "speaker": None,
        }
        for i in range(44)
    ]
    result = await crud.report_chunk_result(
        job["job_id"], success=True, shifted_segments=hallucinated_segments
    )
    assert result["status"] == "completed"

    page = await crud.get_page_by_slug(job["meeting_page_slug"])
    transcribed = next(v for v in page["versions"] if v["source"] == "transcribed")
    assert transcribed["transcript_warnings"]
    assert "hallucinated" in transcribed["transcript_warnings"][0].lower()


async def test_completed_job_does_not_flag_a_real_clean_transcript():
    # False-positive check on the same real finalize path, using the real,
    # independently-confirmed-clean transcript this same investigation
    # produced from the phase-cancellation fix (left channel instead of
    # the cancelled mono downmix).
    url = "https://example.granicus.com/player/clip/tj-clean-1"
    job = await crud.create_transcription_job(
        payload=_payload("granicus:tj-clean-1", url),
        input_url_normalized=url,
        requester_email="clean1@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=900,
        chunk_size_seconds=900,
        skip_confirmation=True,
    )
    claim = await crud.claim_next_chunk()
    assert claim["job_id"] == job["job_id"]

    clean_segments = [
        {
            "start": 300.0,
            "end": 309.52,
            "text": "Councillor Garling. Sorry, I'm confused now. So there is an access point off of Ogovi, and the drawing",
            "speaker": None,
        },
        {
            "start": 309.52,
            "end": 315.36,
            "text": "it says, there's not. So there would be access for, say, if, like, someone were delivering or",
            "speaker": None,
        },
        {
            "start": 315.36,
            "end": 318.56,
            "text": "for firefighting, you know, someone could, could access through, like, you know, like,",
            "speaker": None,
        },
        {
            "start": 318.56,
            "end": 322.80,
            "text": "that's supposed to be a fence or a gate or something, but a driveway access would be off of that",
            "speaker": None,
        },
        {
            "start": 322.80,
            "end": 328.40,
            "text": "lane portion to the off of Hastings. So I'm, I'm, I'm not in favor of this at all. I,",
            "speaker": None,
        },
        {
            "start": 328.40,
            "end": 334.08,
            "text": "I just, I don't know why we would. I get it's an unopened portion, um, but if you were, if you've",
            "speaker": None,
        },
    ]
    result = await crud.report_chunk_result(
        job["job_id"], success=True, shifted_segments=clean_segments
    )
    assert result["status"] == "completed"

    page = await crud.get_page_by_slug(job["meeting_page_slug"])
    transcribed = next(v for v in page["versions"] if v["source"] == "transcribed")
    assert transcribed["transcript_warnings"] == []


async def test_chunk_failures_schedule_a_retry_for_priority_medium_job():
    # Real behavior change 2026-08-19 (see BACKLOG.md/BACKLOG_DONE.md): a
    # real user-submitted job (default priority == PRIORITY_MEDIUM) used to
    # fail outright the moment MAX_CONSECUTIVE_CHUNK_FAILURES was hit.
    # After a real case (job 256, Redwood City CA) died on one slow/
    # rate-limited chunk and a later manual re-run of the exact same
    # source succeeded outright, it no longer fails immediately -- it gets
    # rescheduled with a growing backoff instead (crud.MAX_JOB_RETRIES).
    url = "https://example.granicus.com/player/clip/tj-6"
    job = await crud.create_transcription_job(
        payload=_payload("granicus:tj-6", url),
        input_url_normalized=url,
        requester_email="fails@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=2700,
        chunk_size_seconds=900,
        skip_confirmation=True,
    )
    assert job["total_chunks"] == 3

    result = None
    for _ in range(crud.MAX_CONSECUTIVE_CHUNK_FAILURES):
        claim = await crud.claim_next_chunk()
        assert claim["job_id"] == job["job_id"]
        result = await crud.report_chunk_result(
            claim["job_id"],
            success=False,
            chunk_index=claim["chunk_index"],
            error="ffmpeg exploded",
        )

    assert result["status"] == "retry_scheduled"
    assert result["retry_count"] == 1
    assert result["next_retry_at"] is not None

    status = await crud.get_transcription_job_status(job["job_id"])
    assert status["status"] == "retry_scheduled"
    assert status["retry_count"] == 1
    # Every chunk failure recorded, with the chunk index that failed --
    # error_message alone (overwritten each time) couldn't tell this
    # apart from a job that failed the same way once.
    assert len(status["failure_history"]) == crud.MAX_CONSECUTIVE_CHUNK_FAILURES
    assert [e["chunk_index"] for e in status["failure_history"]] == [0, 0, 0]
    assert all(e["error"] == "ffmpeg exploded" for e in status["failure_history"])

    # Not claimable yet -- next_retry_at is in the future.
    assert await crud.claim_next_chunk() is None


async def test_retry_scheduled_job_is_claimed_once_next_retry_at_passes():
    from datetime import datetime, timedelta, timezone

    from archive.db.engine import async_session
    from archive.db.models import TranscriptionJob

    url = "https://example.granicus.com/player/clip/tj-retry-claim"
    job = await crud.create_transcription_job(
        payload=_payload("granicus:tj-retry-claim", url),
        input_url_normalized=url,
        requester_email="retry-claim@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=900,
        chunk_size_seconds=900,
        skip_confirmation=True,
    )
    for i in range(crud.MAX_CONSECUTIVE_CHUNK_FAILURES):
        claim = await crud.claim_next_chunk()
        result = await crud.report_chunk_result(
            claim["job_id"],
            success=False,
            chunk_index=claim["chunk_index"],
            error="boom",
        )
    assert result["status"] == "retry_scheduled"
    assert await crud.claim_next_chunk() is None  # still in the future

    async with async_session() as session:
        row = await session.get(TranscriptionJob, job["job_id"])
        row.next_retry_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await session.commit()

    claim = await crud.claim_next_chunk()
    assert claim is not None and claim["job_id"] == job["job_id"]
    # chunks_completed was never advanced by the failed attempts -- resumes
    # at chunk 0, not wherever it happened to fail.
    assert claim["chunk_index"] == 0

    status = await crud.get_transcription_job_status(job["job_id"])
    assert status["status"] == "in_progress"

    await crud.report_chunk_result(job["job_id"], success=True, shifted_segments=[])


async def test_duplicate_request_during_retry_scheduled_returns_existing_job():
    # A job waiting out its retry backoff is still "an active request for
    # this page" -- a fresh submit in that window must not race it with a
    # second job for the same page.
    url = "https://example.granicus.com/player/clip/tj-retry-duplicate"
    payload = _payload("granicus:tj-retry-duplicate", url)
    job = await crud.create_transcription_job(
        payload=payload,
        input_url_normalized=url,
        requester_email="first@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=900,
        chunk_size_seconds=900,
        skip_confirmation=True,
    )
    result = None
    for i in range(crud.MAX_CONSECUTIVE_CHUNK_FAILURES):
        claim = await crud.claim_next_chunk()
        result = await crud.report_chunk_result(
            claim["job_id"],
            success=False,
            chunk_index=claim["chunk_index"],
            error="boom",
        )
    assert result["status"] == "retry_scheduled"

    again = await crud.create_transcription_job(
        payload=payload,
        input_url_normalized=url,
        requester_email="second@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=900,
        chunk_size_seconds=900,
        skip_confirmation=True,
    )
    assert again["job_id"] == job["job_id"]
    assert again["status"] == "retry_scheduled"


async def test_job_truly_fails_after_retry_budget_exhausted():
    from datetime import datetime, timedelta, timezone

    from archive.db.engine import async_session
    from archive.db.models import TranscriptionJob

    url = "https://example.granicus.com/player/clip/tj-retry-exhausted"
    job = await crud.create_transcription_job(
        payload=_payload("granicus:tj-retry-exhausted", url),
        input_url_normalized=url,
        requester_email="exhausted@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=900,
        chunk_size_seconds=900,
        skip_confirmation=True,
    )

    result = None
    for retry_round in range(crud.MAX_JOB_RETRIES + 1):
        for i in range(crud.MAX_CONSECUTIVE_CHUNK_FAILURES):
            claim = await crud.claim_next_chunk()
            if claim is None:
                # Backoff window not elapsed yet -- force it open, same as
                # test_retry_scheduled_job_is_claimed_once_next_retry_at_passes.
                async with async_session() as session:
                    row = await session.get(TranscriptionJob, job["job_id"])
                    row.next_retry_at = datetime.now(timezone.utc) - timedelta(
                        seconds=1
                    )
                    await session.commit()
                claim = await crud.claim_next_chunk()
            assert claim["job_id"] == job["job_id"]
            result = await crud.report_chunk_result(
                claim["job_id"],
                success=False,
                chunk_index=claim["chunk_index"],
                error="still exploding",
            )

    assert result["status"] == "failed"
    assert result["retry_count"] == crud.MAX_JOB_RETRIES
    status = await crud.get_transcription_job_status(job["job_id"])
    assert status["status"] == "failed"
    assert await crud.claim_next_chunk() is None


# --- Auto-idle-time job generation (built 2026-08-09, see BACKLOG_DONE.md) ---


async def test_find_auto_transcription_candidate_skips_page_with_good_transcript():
    url = "https://example.granicus.com/player/clip/auto-good-transcript"
    await crud.ingest_resolution(
        {
            "platform": "granicus",
            "source_url": url,
            "external_id": "granicus:auto-good-transcript",
            "title": "T",
            "date": "2026-01-01",
            "jurisdiction": "City of Test",
            "video_url": "https://example.com/v.m3u8",
            "video_format": "m3u8",
            "segments": [{"start": 0, "end": 1, "text": "hello there"}],
            "agenda_items": [],
            "transcript_language": "en",
            "transcript_warnings": [],
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
            "platform": "granicus",
            "source_url": url,
            "external_id": "granicus:auto-no-transcript",
            "title": "T",
            "date": "2026-01-01",
            "jurisdiction": "City of Test",
            "video_url": "https://example.com/v.m3u8",
            "video_format": "m3u8",
            "segments": [],
            "agenda_items": [],
            "transcript_language": None,
            "transcript_warnings": [],
        },
        url,
    )
    slug = (await crud.lookup_page_for_url(url))["slug"]

    async with async_session() as session:
        page = (
            (await session.execute(select(MeetingPage).where(MeetingPage.slug == slug)))
            .scalars()
            .first()
        )
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
            "platform": "granicus",
            "source_url": url,
            "external_id": "granicus:auto-cooldown",
            "title": "T",
            "date": "2026-01-01",
            "jurisdiction": "City of Test",
            "video_url": "https://example.com/v.m3u8",
            "video_format": "m3u8",
            "segments": [],
            "agenda_items": [],
            "transcript_language": None,
            "transcript_warnings": [],
        },
        url,
    )
    slug = (await crud.lookup_page_for_url(url))["slug"]

    job = await crud.create_transcription_job(
        payload=_payload("granicus:auto-cooldown", url),
        input_url_normalized=url,
        requester_email="auto@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=900,
        chunk_size_seconds=900,
        skip_confirmation=True,
        priority=crud.PRIORITY_LOW,
    )
    for _ in range(crud.MAX_CONSECUTIVE_CHUNK_FAILURES):
        claim = await crud.claim_next_chunk()
        assert claim["job_id"] == job["job_id"]
        await crud.report_chunk_result(
            job["job_id"], success=False, error="simulated failure"
        )

    status = await crud.get_transcription_job_status(job["job_id"])
    assert status["status"] == "failed"

    # Freshly failed -- still well within the 1-day base cooldown.
    async with async_session() as session:
        page = (
            (await session.execute(select(MeetingPage).where(MeetingPage.slug == slug)))
            .scalars()
            .first()
        )
        assert await crud._in_auto_transcription_cooldown(session, page.id) is True


async def test_create_failed_auto_transcription_job_is_immediately_failed():
    url = "https://example.granicus.com/player/clip/auto-fail-direct"
    await crud.ingest_resolution(
        {
            "platform": "granicus",
            "source_url": url,
            "external_id": "granicus:auto-fail-direct",
            "title": "T",
            "date": "2026-01-01",
            "jurisdiction": "City of Test",
            "video_url": "https://example.com/v.m3u8",
            "video_format": "m3u8",
            "segments": [],
            "agenda_items": [],
            "transcript_language": None,
            "transcript_warnings": [],
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
        row = (
            (await session.execute(select(MeetingPage).where(MeetingPage.slug == slug)))
            .scalars()
            .first()
        )
        page_id = row.id

    result = await crud.create_failed_auto_transcription_job(
        meeting_page_id=page_id,
        requester_email="auto@example.com",
        error_message="No usable media source found.",
    )
    status = await crud.get_transcription_job_status(result["job_id"])
    assert status["status"] == "failed"
    assert status["error_message"] == "No usable media source found."
    # Never claimable -- it was never queued in the first place.
    assert (
        await crud.claim_next_chunk() is None
        or (await crud.claim_next_chunk())["job_id"] != result["job_id"]
    )


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
            "platform": "granicus",
            "source_url": url,
            "external_id": "granicus:auto-escalation",
            "title": "T",
            "date": "2026-01-01",
            "jurisdiction": "City of Test",
            "video_url": "https://example.com/v.m3u8",
            "video_format": "m3u8",
            "segments": [],
            "agenda_items": [],
            "transcript_language": None,
            "transcript_warnings": [],
        },
        url,
    )
    slug = (await crud.lookup_page_for_url(url))["slug"]

    async with async_session() as session:
        page = (
            (await session.execute(select(MeetingPage).where(MeetingPage.slug == slug)))
            .scalars()
            .first()
        )
        page_id = page.id

        old_failure = TranscriptionJob(
            meeting_page_id=page_id,
            requester_email="auto@example.com",
            status="failed",
            media_url="",
            media_kind="video",
            probed_duration_seconds=0,
            chunk_size_seconds=1,
            total_chunks=1,
        )
        session.add(old_failure)
        await session.commit()

        recent_failure = TranscriptionJob(
            meeting_page_id=page_id,
            requester_email="auto@example.com",
            status="failed",
            media_url="",
            media_kind="video",
            probed_duration_seconds=0,
            chunk_size_seconds=1,
            total_chunks=1,
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

    assert (
        in_cooldown is True
    )  # 2 consecutive failures => 2-day cooldown, 36h in is still inside it


def test_auto_candidate_and_cooldown_queries_never_touch_transcript_json():
    # 2026-08-17: pg_stat_statements showed the old find_auto_transcription_
    # candidate() (per-page _has_good_transcript() selecting the whole
    # TranscriptVersion incl. segments) as the #1 consumer of prod DB time
    # -- 218,480 calls, 47 min, all 102MB of transcript JSON every 5 idle
    # minutes. Pin at the SQL level that neither the good-transcript
    # predicate nor the cooldown query names a JSON blob column.
    from sqlalchemy import select
    from sqlalchemy.dialects import postgresql

    from archive.db.models import MeetingPage, TranscriptionJob

    sql = str(
        select(MeetingPage.id)
        .where(~crud._good_default_transcript_exists())
        .compile(dialect=postgresql.dialect())
    )
    assert "segments" not in sql, sql
    assert "content_hash" in sql and "transcript_warnings" in sql
    # The cooldown history query shape (status/updated_at only).
    cooldown_sql = str(
        select(TranscriptionJob.status, TranscriptionJob.updated_at).compile(
            dialect=postgresql.dialect()
        )
    )
    assert "partial_segments" not in cooldown_sql


async def test_has_good_transcript_treats_garbled_and_hallucinated_as_not_good():
    # The SQL predicate and the per-page helper must agree: a default
    # version carrying either quality marker in transcript_warnings is NOT
    # a good transcript, so the page stays an auto-transcription candidate.
    from archive.db.engine import async_session
    from archive.db.models import MeetingPage
    from sqlalchemy import select

    async def _page_with_warning(eid: str, warning: str):
        url = f"https://example.granicus.com/player/clip/{eid}"
        await crud.ingest_resolution(
            {
                "platform": "granicus",
                "source_url": url,
                "external_id": f"granicus:{eid}",
                "title": "T",
                "date": "2026-01-01",
                "jurisdiction": f"City of {eid}",
                "video_url": "https://example.com/v.m3u8",
                "video_format": "m3u8",
                "segments": [{"start": 0, "end": 1, "text": "words words words"}],
                "agenda_items": [],
                "transcript_language": "en",
                "transcript_warnings": [warning] if warning else [],
            },
            url,
        )
        return (await crud.lookup_page_for_url(url))["slug"]

    garbled = await _page_with_warning(
        "auto-garbled", "This transcript looks garbled at the source."
    )
    halluc = await _page_with_warning(
        "auto-halluc",
        "Parts of this transcript may have been hallucinated by the transcription model.",
    )
    clean = await _page_with_warning("auto-clean", "")

    async with async_session() as session:
        rows = (
            await session.execute(
                select(MeetingPage.slug, crud._good_default_transcript_exists()).where(
                    MeetingPage.slug.in_([garbled, halluc, clean])
                )
            )
        ).all()
        by_slug = {slug: bool(good) for slug, good in rows}
        assert by_slug == {garbled: False, halluc: False, clean: True}
        # ...and the per-page helper agrees, row for row.
        for slug, expected in by_slug.items():
            page_id = (
                await session.execute(
                    select(MeetingPage.id).where(MeetingPage.slug == slug)
                )
            ).scalar_one()
            assert await crud._has_good_transcript(session, page_id) is expected, slug


async def test_has_good_transcript_treats_granicus_36k_truncation_as_not_good():
    # Added 2026-08-23 alongside _GRANICUS_TRUNCATION_MARKER -- same
    # "SQL predicate and per-page helper must agree" shape as the
    # garbled/hallucinated test above. Real warning wording from
    # app/platforms/granicus.py's own 36,000-cue truncation heuristic, not
    # invented text -- confirms a page stuck at that cap stays eligible
    # for re-transcription instead of silently counting as done forever.
    from archive.db.engine import async_session
    from archive.db.models import MeetingPage
    from sqlalchemy import select

    async def _page_with_warning(eid: str, warning: str):
        url = f"https://example.granicus.com/player/clip/{eid}"
        await crud.ingest_resolution(
            {
                "platform": "granicus",
                "source_url": url,
                "external_id": f"granicus:{eid}",
                "title": "T",
                "date": "2026-01-01",
                "jurisdiction": f"City of {eid}",
                "video_url": "https://example.com/v.m3u8",
                "video_format": "m3u8",
                "segments": [{"start": 0, "end": 1, "text": "words words words"}],
                "agenda_items": [],
                "transcript_language": "en",
                "transcript_warnings": [warning] if warning else [],
            },
            url,
        )
        return (await crud.lookup_page_for_url(url))["slug"]

    truncated = await _page_with_warning(
        "auto-truncated",
        "This transcript may be cut off — it hit exactly 36,000 lines, "
        "a known limit in Granicus's own captioning for very long meetings.",
    )
    clean = await _page_with_warning("auto-clean3", "")

    async with async_session() as session:
        rows = (
            await session.execute(
                select(MeetingPage.slug, crud._good_default_transcript_exists()).where(
                    MeetingPage.slug.in_([truncated, clean])
                )
            )
        ).all()
        by_slug = {slug: bool(good) for slug, good in rows}
        assert by_slug == {truncated: False, clean: True}
        for slug, expected in by_slug.items():
            page_id = (
                await session.execute(
                    select(MeetingPage.id).where(MeetingPage.slug == slug)
                )
            ).scalar_one()
            assert await crud._has_good_transcript(session, page_id) is expected, slug


# --- WO-45: a completed job is a cooldown, not a free pass -----------------
#
# _cooldown_active() is pure by design (see its docstring), so these drive it
# directly with the (status, updated_at) tuples both callers build, rather
# than staging five real jobs in the DB.
#
# The real occurrence these pin: jobs 732-736 on 2026-08-23 were five
# separate COMPLETED jobs, 5/5 chunks each, on the identical page
# (st-louis-park-high-school-wind-ensemble-concert) inside 17 minutes,
# producing TranscriptVersions 2058-2062. The page is a music concert, so an
# empty transcript is the correct final answer -- but an empty transcript
# never satisfies _has_good_transcript(), so the page stayed in the candidate
# pool, and a "completed" newest job applied no cooldown at all. There was no
# test covering the completed-newest case before this one, which is how it
# shipped.


def test_cooldown_active_treats_a_completed_newest_job_as_cooldown():
    from datetime import datetime, timedelta, timezone

    from archive.db import crud as _crud

    now = datetime.now(timezone.utc)
    jobs = [("completed", now - timedelta(minutes=5))]
    assert _crud._cooldown_active(jobs, now) is True


def test_cooldown_active_releases_a_completed_page_after_the_max_cooldown():
    """The page must still come back eventually -- a government source's own
    captions really can catch up later, which is why these pages stay
    candidates at all. Monthly, not every idle poll."""
    from datetime import datetime, timedelta, timezone

    from archive.db import crud as _crud

    now = datetime.now(timezone.utc)
    just_inside = [("completed", now - _crud.AUTO_TRANSCRIPTION_MAX_COOLDOWN)]
    assert _crud._cooldown_active(just_inside, now) is False

    well_past = [
        ("completed", now - _crud.AUTO_TRANSCRIPTION_MAX_COOLDOWN - timedelta(days=1))
    ]
    assert _crud._cooldown_active(well_past, now) is False


def test_cooldown_active_still_ignores_failures_older_than_a_completed_job():
    """Pre-existing behaviour that must survive: a failure streak *before* a
    completed job is stale history, not part of the current streak. Here the
    completed job is what sets the cooldown, and the two older failures must
    not escalate it."""
    from datetime import datetime, timedelta, timezone

    from archive.db import crud as _crud

    now = datetime.now(timezone.utc)
    jobs = [
        ("completed", now - _crud.AUTO_TRANSCRIPTION_MAX_COOLDOWN - timedelta(days=1)),
        ("failed", now - timedelta(days=400)),
        ("failed", now - timedelta(days=401)),
    ]
    assert _crud._cooldown_active(jobs, now) is False


def test_cooldown_active_still_escalates_on_consecutive_failures():
    """Negative control: the failure path this function existed for is
    untouched -- 2 consecutive failures is a 2-day cooldown."""
    from datetime import datetime, timedelta, timezone

    from archive.db import crud as _crud

    now = datetime.now(timezone.utc)
    jobs = [
        ("failed", now - timedelta(hours=36)),
        ("failed", now - timedelta(hours=48)),
    ]
    assert _crud._cooldown_active(jobs, now) is True

    jobs_past = [
        ("failed", now - timedelta(hours=60)),
        ("failed", now - timedelta(hours=72)),
    ]
    assert _crud._cooldown_active(jobs_past, now) is False


def test_cooldown_active_is_false_with_no_job_history():
    from datetime import datetime, timezone

    from archive.db import crud as _crud

    assert _crud._cooldown_active([], datetime.now(timezone.utc)) is False
