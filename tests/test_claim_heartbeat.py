"""A working worker keeps its own claim; a stopped one loses it.

`STALE_CLAIM_AFTER` (5 minutes) exists to recover a job from a worker
that crashed mid-chunk. But nothing distinguished "crashed" from "still
working", and it rested on an assumption nothing enforced -- that 5
minutes is "comfortably longer than a single chunk should ever
legitimately take". A slow source breaks that quietly, and then:

    worker A is still transcribing chunk 3
    worker B sees a stale claim, takes the job
    B derives chunk_index from chunks_completed -- also 3
    both report success, and report_chunk_result() APPENDS

...so the transcript carries that window twice and the job skips a real
chunk. Silent. Found by reasoning about WO-54's download budget, not from
a report, which is why these tests matter more than usual: there is no
production signal to notice a regression here.

The two properties are in tension, so both are pinned: a heartbeated job
must NOT be reclaimable however long it runs, and a job that stops being
heartbeated MUST still be reclaimable -- that second one is the whole
reason the staleness window exists, and it would be easy to break while
fixing the first.
"""

from datetime import datetime, timedelta, timezone

from archive.db import crud


def _payload(external_id: str, source_url: str) -> dict:
    return {
        "platform": "granicus",
        "source_url": source_url,
        "external_id": external_id,
        "title": "Heartbeat Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "City of Heartbeat",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }


async def _job_for(key: str, *, total_seconds: int = 2700) -> dict:
    url = f"https://example.granicus.com/player/clip/{key}"
    return await crud.create_transcription_job(
        payload=_payload(f"granicus:{key}", url),
        input_url_normalized=url,
        requester_email="hb@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=total_seconds,
        chunk_size_seconds=900,
        skip_confirmation=True,
    )


async def _set_claimed_at(job_id: int, when) -> None:
    from archive.db.engine import async_session
    from archive.db.models import TranscriptionJob

    async with async_session() as session:
        job = await session.get(TranscriptionJob, job_id)
        job.claimed_at = when
        await session.commit()


async def _claimed_at(job_id: int):
    from archive.db.engine import async_session
    from archive.db.models import TranscriptionJob

    async with async_session() as session:
        return (await session.get(TranscriptionJob, job_id)).claimed_at


async def _set_last_progress_at(job_id: int, when) -> None:
    from archive.db.engine import async_session
    from archive.db.models import TranscriptionJob

    async with async_session() as session:
        job = await session.get(TranscriptionJob, job_id)
        job.last_progress_at = when
        await session.commit()


async def _set_created_at(job_id: int, when) -> None:
    from archive.db.engine import async_session
    from archive.db.models import TranscriptionJob

    async with async_session() as session:
        job = await session.get(TranscriptionJob, job_id)
        job.created_at = when
        await session.commit()


async def test_a_heartbeat_refreshes_the_claim():
    job = await _job_for("hb-refresh")
    claim = await crud.claim_next_chunk()
    assert claim is not None and claim["job_id"] == job["job_id"]

    stale = datetime.now(timezone.utc) - timedelta(minutes=30)
    await _set_claimed_at(job["job_id"], stale)

    assert await crud.heartbeat_claim(job["job_id"]) is True
    refreshed = await _claimed_at(job["job_id"])
    assert refreshed is not None
    assert refreshed.replace(tzinfo=timezone.utc) > stale


async def test_a_long_chunk_that_heartbeats_is_never_reclaimed():
    """The bug itself. A chunk running well past STALE_CLAIM_AFTER while
    its worker is alive must stay that worker's."""
    job = await _job_for("hb-holds")
    claim = await crud.claim_next_chunk()
    assert claim is not None and claim["job_id"] == job["job_id"]

    # An hour into a very slow chunk, with heartbeats landing.
    await _set_claimed_at(
        job["job_id"], datetime.now(timezone.utc) - timedelta(hours=1)
    )
    await crud.heartbeat_claim(job["job_id"])

    # Whatever another worker picks up next, it must not be this job.
    other = await crud.claim_next_chunk()
    assert other is None or other["job_id"] != job["job_id"]


async def test_a_worker_that_stops_heartbeating_still_loses_the_claim():
    """The property the staleness window exists for, and the one most
    easily broken while fixing the other. A crashed worker leaves a claim
    nobody refreshes, and the job must come back."""
    job = await _job_for("hb-crash")
    claim = await crud.claim_next_chunk()
    assert claim is not None and claim["job_id"] == job["job_id"]

    # Claimed, then the worker died -- no heartbeat since.
    await _set_claimed_at(
        job["job_id"],
        datetime.now(timezone.utc) - crud.STALE_CLAIM_AFTER - timedelta(minutes=1),
    )

    reclaimed = await crud.claim_next_chunk()
    assert reclaimed is not None
    assert reclaimed["job_id"] == job["job_id"]
    # And it resumes at the same chunk, not a later one.
    assert reclaimed["chunk_index"] == claim["chunk_index"]


async def test_heartbeating_a_finished_job_does_nothing():
    """A job that completed or failed while a heartbeat was in flight must
    not be dragged back into looking claimed."""
    job = await _job_for("hb-finished", total_seconds=600)
    claim = await crud.claim_next_chunk()
    assert claim is not None
    await crud.report_chunk_result(job["job_id"], success=True, shifted_segments=[])

    # One chunk, so that completed the job.
    assert await crud.heartbeat_claim(job["job_id"]) is False


async def test_heartbeating_an_unknown_job_is_harmless():
    assert await crud.heartbeat_claim(987654321) is False


# --- the worker side -----------------------------------------------------


async def test_the_context_manager_beats_while_work_runs_and_stops_after(monkeypatch):
    """Covers the whole chunk, and leaves nothing running afterwards -- a
    leaked task would keep refreshing a claim this worker no longer
    holds, which is the same double-claim bug pointed the other way."""
    import asyncio

    import worker.main as worker_main

    beats: list[int] = []

    async def _fake_heartbeat(job_id):
        beats.append(job_id)
        return True

    monkeypatch.setattr(worker_main.crud, "heartbeat_claim", _fake_heartbeat)
    monkeypatch.setattr(worker_main, "CLAIM_HEARTBEAT_SECONDS", 0.01)

    async with worker_main._keeping_claim_alive(77):
        await asyncio.sleep(0.06)

    during = len(beats)
    assert during >= 2, f"heartbeat did not fire during the work (got {during})"
    assert set(beats) == {77}

    # Nothing may keep beating once the block is done.
    await asyncio.sleep(0.05)
    assert len(beats) == during


async def test_the_heartbeat_survives_a_transient_database_error(monkeypatch):
    """A failed heartbeat must not take down a chunk that is otherwise
    fine. The worst case is the claim going stale, which is a state the
    system already recovers from -- crashing the chunk instead would turn
    a blip into a real failure."""
    import asyncio

    import worker.main as worker_main

    calls = {"n": 0}

    async def _flaky(job_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("connection reset")
        return True

    monkeypatch.setattr(worker_main.crud, "heartbeat_claim", _flaky)
    monkeypatch.setattr(worker_main, "CLAIM_HEARTBEAT_SECONDS", 0.01)

    async with worker_main._keeping_claim_alive(88):
        await asyncio.sleep(0.06)

    assert calls["n"] >= 2, "heartbeat stopped after one failure"


async def test_the_heartbeat_fires_during_blocking_cpu_work(monkeypatch):
    """The property that makes wrapping transcription meaningful at all.
    Whisper is CPU-bound, and if it ran on the event loop no heartbeat
    could fire during exactly the slow part -- protection that looks real
    and is not. worker/transcription_engine.py hands it to
    asyncio.to_thread, and this pins that.
    """
    import asyncio
    import time

    import worker.main as worker_main

    beats: list[int] = []

    async def _fake_heartbeat(job_id):
        beats.append(job_id)
        return True

    monkeypatch.setattr(worker_main.crud, "heartbeat_claim", _fake_heartbeat)
    monkeypatch.setattr(worker_main, "CLAIM_HEARTBEAT_SECONDS", 0.01)

    async with worker_main._keeping_claim_alive(99):
        # Stands in for FasterWhisperEngine.transcribe_chunk()'s own
        # asyncio.to_thread(self._transcribe_sync, ...).
        await asyncio.to_thread(time.sleep, 0.06)

    assert len(beats) >= 2, "no heartbeat during off-loop CPU work"


# --- WO-936: the stuck-job detector ---------------------------------------
#
# Two real, previously-invisible failure shapes share one signature: a job
# stays "in_progress" but stops reporting real progress. An OOM-killed
# worker never gets to call report_chunk_result() at all (job 1419,
# 2026-09-02: ~40 OOMs over 3.5 hours, invisible to every check that
# existed then); a wedged transcription call keeps claimed_at fresh via
# the heartbeat above forever, so it never goes stale either. Both are
# caught the same way: last_progress_at (set only inside
# report_chunk_result(), never by the heartbeat) stops moving.


async def test_report_chunk_result_sets_last_progress_at_on_success():
    # A single chunk (total_seconds == chunk_size), so one success call
    # both proves the assertion AND finishes the job -- no leftover
    # in_progress job for later tests in this shared-DB file to trip on.
    job = await _job_for("stuck-progress-success", total_seconds=900)
    claim = await crud.claim_next_chunk()
    assert claim is not None and claim["job_id"] == job["job_id"]

    before = datetime.now(timezone.utc)
    result = await crud.report_chunk_result(
        job["job_id"], success=True, shifted_segments=[]
    )
    assert result["status"] == "completed"

    from archive.db.engine import async_session
    from archive.db.models import TranscriptionJob

    async with async_session() as session:
        row = await session.get(TranscriptionJob, job["job_id"])
        assert row.last_progress_at is not None
        assert row.last_progress_at.replace(tzinfo=timezone.utc) >= before


async def test_report_chunk_result_sets_last_progress_at_on_failure():
    job = await _job_for("stuck-progress-failure")
    claim = await crud.claim_next_chunk()
    assert claim is not None and claim["job_id"] == job["job_id"]

    before = datetime.now(timezone.utc)
    await crud.report_chunk_result(
        job["job_id"], success=False, chunk_index=0, error="ffmpeg exited 1"
    )

    from archive.db.engine import async_session
    from archive.db.models import TranscriptionJob

    async with async_session() as session:
        row = await session.get(TranscriptionJob, job["job_id"])
        assert row.last_progress_at is not None
        assert row.last_progress_at.replace(tzinfo=timezone.utc) >= before

    # Exhaust the failure budget so this job leaves the "in_progress,
    # claimable" pool (-> retry_scheduled, an hour out) instead of
    # leaking an immediately-reclaimable job for later tests in this
    # shared-DB file to collide with.
    for _ in range(crud.MAX_CONSECUTIVE_CHUNK_FAILURES - 1):
        result = await crud.report_chunk_result(
            job["job_id"], success=False, chunk_index=0, error="ffmpeg exited 1"
        )
    assert result["status"] == "retry_scheduled"


async def test_list_stuck_transcription_jobs_flags_a_stalled_in_progress_claim():
    job = await _job_for("stuck-flagged")
    claim = await crud.claim_next_chunk()
    assert claim is not None and claim["job_id"] == job["job_id"]

    # Heartbeated recently (claimed_at is fresh -- the whole point: a
    # wedged job's claim looks perfectly healthy), but no real progress
    # in well over the detector's threshold.
    stale_progress = datetime.now(timezone.utc) - timedelta(hours=4)
    await _set_last_progress_at(job["job_id"], stale_progress)
    await _set_claimed_at(job["job_id"], datetime.now(timezone.utc))

    stuck = await crud.list_stuck_transcription_jobs(threshold=timedelta(hours=3))
    stuck_ids = {j["job_id"] for j in stuck}
    assert job["job_id"] in stuck_ids

    entry = next(j for j in stuck if j["job_id"] == job["job_id"])
    assert entry["chunks_completed"] == 0
    assert entry["total_chunks"] == claim["total_chunks"]
    assert entry["platform"] == "granicus"
    assert entry["source_url"]
    assert entry["stalled_for"]

    await _drain_job_from(job["job_id"], claim, remaining=claim["total_chunks"])


async def test_list_stuck_transcription_jobs_ignores_a_job_still_progressing():
    job = await _job_for("stuck-not-flagged", total_seconds=2700)
    claim = await crud.claim_next_chunk()
    assert claim is not None and claim["job_id"] == job["job_id"]

    # A chunk finished a minute ago -- nowhere near the threshold.
    await _set_last_progress_at(
        job["job_id"], datetime.now(timezone.utc) - timedelta(minutes=1)
    )

    stuck = await crud.list_stuck_transcription_jobs(threshold=timedelta(hours=3))
    assert job["job_id"] not in {j["job_id"] for j in stuck}

    await _drain_job_from(job["job_id"], claim, remaining=claim["total_chunks"])


async def test_list_stuck_transcription_jobs_ignores_a_queued_job():
    """A job sitting queued (not claimed) a long time is the pool-wide
    "chunks flat while jobs active" warning's signal
    (archive/utils/email.py's send_worker_daily_report()), not this one --
    this detector only looks at a claim actually held right now."""
    job = await _job_for("stuck-ignores-queued")
    # Never claimed -- still "queued". Old on paper, but not "in_progress".
    await _set_created_at(
        job["job_id"], datetime.now(timezone.utc) - timedelta(hours=6)
    )

    stuck = await crud.list_stuck_transcription_jobs(threshold=timedelta(hours=3))
    assert job["job_id"] not in {j["job_id"] for j in stuck}

    # Clean up: claim and drain so this doesn't eat a concurrency slot for
    # later tests in this shared-DB file.
    claim = await crud.claim_next_chunk()
    assert claim is not None and claim["job_id"] == job["job_id"]
    await _drain_job_from(job["job_id"], claim, remaining=claim["total_chunks"])


async def test_list_stuck_transcription_jobs_falls_back_to_created_at_when_unset():
    """last_progress_at is nullable (added by migration after real jobs
    already existed) -- a row that predates it must fall back to
    created_at rather than being read as having no age at all."""
    job = await _job_for("stuck-null-fallback")
    claim = await crud.claim_next_chunk()
    assert claim is not None and claim["job_id"] == job["job_id"]

    # Simulate a pre-migration row: last_progress_at never set, but the
    # job has clearly been sitting in_progress a long time.
    await _set_last_progress_at(job["job_id"], None)
    await _set_created_at(
        job["job_id"], datetime.now(timezone.utc) - timedelta(hours=4)
    )

    stuck = await crud.list_stuck_transcription_jobs(threshold=timedelta(hours=3))
    assert job["job_id"] in {j["job_id"] for j in stuck}

    await _drain_job_from(job["job_id"], claim, remaining=claim["total_chunks"])


async def _drain_job_from(job_id: int, first_claim: dict, *, remaining: int) -> None:
    """Finishes a job whose first chunk was already claimed by the test
    itself (to set up a stuck scenario, sometimes with a manually-forced
    claimed_at that claim_next_chunk() would refuse to re-claim).
    report_chunk_result() identifies the job by id and doesn't require an
    active claim to apply progress, so this reports the rest directly
    rather than re-claiming -- just frees the job's
    MAX_CONCURRENT_TRANSCRIPTION_JOBS slot for the rest of this shared-DB
    test file."""
    done = first_claim["chunk_index"]
    while done < remaining:
        await crud.report_chunk_result(job_id, success=True, shifted_segments=[])
        done += 1


async def test_the_heartbeat_stops_after_its_stuck_job_ceiling(monkeypatch):
    """WO-936: nothing used to bound how long a live process could keep a
    claim fresh -- see worker/main.py's module comment above
    _heartbeat_loop() for why capping it at crud.STUCK_JOB_THRESHOLD is
    safe rather than a regression of WO-57's own fix."""
    import asyncio

    import worker.main as worker_main

    beats: list[int] = []

    async def _fake_heartbeat(job_id):
        beats.append(job_id)
        return True

    monkeypatch.setattr(worker_main.crud, "heartbeat_claim", _fake_heartbeat)
    monkeypatch.setattr(worker_main, "CLAIM_HEARTBEAT_SECONDS", 0.01)
    monkeypatch.setattr(
        worker_main.crud, "STUCK_JOB_THRESHOLD", timedelta(seconds=0.05)
    )

    task = asyncio.create_task(worker_main._heartbeat_loop(123))
    await asyncio.sleep(0.3)

    assert task.done(), "heartbeat loop kept running past its own ceiling"
    assert len(beats) >= 1, "no real heartbeats landed before the ceiling"
