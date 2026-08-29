"""Entry point for the transcription worker service (see render.yaml's
`type: worker` block). Loads the transcription model once, then loops:
claim the oldest pending chunk, extract its audio, transcribe it, persist
the result, repeat.

Deliberately reaches into archive.db directly (not through the token-gated
/internal/* HTTP pattern app/ uses to talk to the Archive) -- this process
IS Archive backend logic, just running in a process shape (long-lived, no
web request timeout) the Archive's own web dyno can't provide. It also
imports app.platforms (via register_all_finders()/get_finder()) purely to
re-resolve a fresh media URL before each chunk -- read-only, stateless,
no state coupling back the other way. See app/platforms/media_probe.py's
docstring for the fuller dependency-direction reasoning.
"""

import asyncio
import contextlib
import logging
import os
import shutil
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

load_dotenv()


def _init_sentry() -> None:
    """No-op when SENTRY_DSN unset, same degrade pattern as app/main.py's
    matching _init_sentry() (deliberately duplicated per service). This
    process never serves HTTP, so there's no ASGI app to auto-instrument
    -- what this buys here is the SDK's logging integration, which turns
    every existing logger.exception() call in the loop below (and in
    archive.db/archive.utils.email, which this process calls directly)
    into a Sentry event with no per-call-site changes needed."""
    dsn = os.environ.get("SENTRY_DSN", "")
    if not dsn:
        return
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT", "production"),
        traces_sample_rate=0,
    )


_init_sentry()

from app.platforms import register_all_finders
from app.platforms.base import UnsupportedPlatformError, get_finder
from app.platforms.media_probe import (
    chunk_size_seconds_for_platform,
    extract_chunk_audio,
    extract_full_audio,
    is_plausible_meeting_duration,
    probe_duration,
    should_cache_whole_audio,
    slice_cached_audio,
)
from app.utils.retry import retry_async
from archive.db import crud
from archive.utils import email as email_utils
from worker.segment_utils import (
    chunk_duration,
    chunk_start,
    count_seam_overlap_segments,
    shift_segments,
)
from worker.transcription_engine import TranscriptionEngine, build_default_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("rtr_worker")

# How often to poll when there's real work to keep chasing, vs. how long to
# back off after an empty claim (nothing queued) -- no cron/external
# trigger needed since this is a persistent process (see the plan this was
# built from for why that's the ~$/mo tradeoff already accepted).
POLL_INTERVAL_SECONDS = 5
EMPTY_POLL_BACKOFF_SECONDS = 15
# Real gap this closes: originally an empty poll logged nothing at all, so
# "no new log lines" was ambiguous between "nothing queued" and "silently
# stuck" -- confirmed confusing in practice (2026-08-08). Logged only every
# Nth empty poll (~5 min at EMPTY_POLL_BACKOFF_SECONDS=15s), not every poll,
# so this stays a liveness signal rather than log spam.
EMPTY_POLL_HEARTBEAT_EVERY = 20

# Excerpt length for the completion email -- plain character count, not
# trying to break on a sentence boundary; good enough for "here's a taste,
# click through for the rest."
EMAIL_EXCERPT_CHARS = 500

# How often to even check for an auto-generation candidate, separate from
# the much shorter poll/backoff cadence above -- checking on literally
# every empty poll (every 15s) would be wasteful (a full-table scan plus a
# live re-resolve + feasibility probe against a real source, not a cheap
# DB-only check). 5 minutes is frequent enough that a freshly-archived,
# transcript-less meeting doesn't sit idle for long once the queue is
# otherwise empty.
AUTO_GENERATION_CHECK_INTERVAL_SECONDS = 300

# Auto-generated jobs need *some* requester_email (the column is required,
# and the worker emails it on completion -- see _send_completion_email) --
# decided 2026-08-09 to use a real person's address as a lightweight
# activity digest rather than building a new "skip the email" code path or
# a dedicated no-reply mailbox. Auto-generation is simply disabled
# (maybe_generate_auto_job() always returns False) if this isn't set,
# rather than guessing at a placeholder address.
AUTO_TRANSCRIPTION_REQUESTER_EMAIL = os.environ.get(
    "AUTO_TRANSCRIPTION_REQUESTER_EMAIL", ""
)

# Retry/backoff for maybe_generate_auto_job()'s live feasibility check --
# the one place in this process that had the same one-shot-no-retry gap
# scripts/transcribe_backlog_locally.py had (BACKLOG.md's entry on that
# script; checked here as part of the same fix, 2026-08-22).
#
# Why this path specifically and not the chunk-processing path below: a
# chunk failure already gets three tries (crud.MAX_CONSECUTIVE_CHUNK_
# FAILURES) plus job-level retries for user-priority jobs, and everything
# transcribed so far is already persisted in TranscriptionJob.
# partial_segments -- the worker never discards finished chunks. The
# feasibility check had neither: one transient resolve/probe failure wrote
# a real `failed` TranscriptionJob row via
# create_failed_auto_transcription_job(), which is what
# _cooldown_active() counts, so a single flaky moment pushed that page a
# full day out (doubling per consecutive failure, up to 30 days) even
# though nothing was wrong with it.
#
# Same MEDIA_ATTEMPTS=2 default and short backoff as the local script, for
# the same reason and with the same honest limit (one retry demonstrably
# isn't enough for every real case -- see that script's own constant
# comment). Sleeping a few seconds here is free: this only ever runs when
# this worker found nothing claimable, gated behind
# AUTO_GENERATION_CHECK_INTERVAL_SECONDS.
AUTO_GENERATION_ATTEMPTS = 2
AUTO_GENERATION_RETRY_BASE_DELAY_SECONDS = 10.0
AUTO_GENERATION_RETRY_MAX_DELAY_SECONDS = 60.0


def _auto_media_kind(video_format) -> str:
    return "audio" if (video_format or "") in ("mp3", "wav") else "video"


async def maybe_generate_auto_job() -> bool:
    """Looks for a MeetingPage missing a good transcript and, if one
    exists and isn't in cooldown, creates a low-priority self-generated
    transcription job for it -- see BACKLOG_DONE.md's auto-idle-time entry.
    Caller (run_forever()) is responsible for only calling this when the
    job queue is confirmed empty and the check interval has elapsed.
    Returns True if a job (real or feasibility-failed) was created, so the
    caller can treat that the same as "did work" for polling-cadence
    purposes -- False means there was nothing to do (or auto-generation
    isn't configured), not that something went wrong.
    """
    if not AUTO_TRANSCRIPTION_REQUESTER_EMAIL:
        return False

    candidate = await crud.find_auto_transcription_candidate()
    if candidate is None:
        return False

    slug = candidate["slug"]
    source_url = candidate["source_url"]
    platform = candidate["platform"]
    logger.info("Auto-generation: trying candidate %s (%s)", slug, source_url)

    async def _fail(reason: str) -> None:
        logger.info("Auto-generation: %s not feasible (%s)", slug, reason)
        await crud.create_failed_auto_transcription_job(
            meeting_page_id=candidate["meeting_page_id"],
            requester_email=AUTO_TRANSCRIPTION_REQUESTER_EMAIL,
            error_message=reason,
        )

    try:
        finder = get_finder(platform)
        # get_finder() stays outside the retry on purpose: an unregistered
        # platform is a permanent answer, and its failure message shape
        # ("Re-resolve failed: ...") is unchanged from before this retry
        # existed.
        result = await retry_async(
            lambda: finder.resolve(source_url),
            label=f"auto-generation re-resolve of {source_url}",
            attempts=AUTO_GENERATION_ATTEMPTS,
            base_delay=AUTO_GENERATION_RETRY_BASE_DELAY_SECONDS,
            max_delay=AUTO_GENERATION_RETRY_MAX_DELAY_SECONDS,
            logger=logger,
            permanent_exceptions=(UnsupportedPlatformError,),
        )
    except Exception as e:
        await _fail(f"Re-resolve failed: {e}")
        return True

    if not result.video_url:
        # A resolve that succeeded and found no media is a real answer
        # about this page, not a transient failure -- recorded immediately,
        # no retry, exactly as before.
        await _fail("No usable audio or video source was found.")
        return True

    duration = await retry_async(
        lambda: probe_duration(result.video_url, source_page_url=source_url),
        label=f"auto-generation ffprobe of {result.video_url}",
        attempts=AUTO_GENERATION_ATTEMPTS,
        base_delay=AUTO_GENERATION_RETRY_BASE_DELAY_SECONDS,
        max_delay=AUTO_GENERATION_RETRY_MAX_DELAY_SECONDS,
        logger=logger,
        # probe_duration() never raises -- None covers every failure,
        # including the 120s subprocess timeout this retry is aimed at.
        retryable_failure=lambda d: None if d is not None else "ffprobe read nothing",
    )
    if duration is None:
        await _fail("Found a media source but couldn't read it.")
        return True
    if not is_plausible_meeting_duration(duration):
        await _fail("Media duration doesn't look like a full meeting recording.")
        return True

    job = await crud.create_transcription_job(
        payload=result.model_dump(),
        input_url_normalized=source_url,
        requester_email=AUTO_TRANSCRIPTION_REQUESTER_EMAIL,
        media_url=result.video_url,
        media_kind=_auto_media_kind(result.video_format),
        probed_duration_seconds=duration,
        chunk_size_seconds=chunk_size_seconds_for_platform(result.platform),
        skip_confirmation=True,
        priority=crud.PRIORITY_LOW,
    )
    logger.info("Auto-generation: created job %s for %s", job.get("job_id"), slug)
    return True


# --- Keeping a live claim alive ------------------------------------------

# How often a working worker refreshes its claim. Well under
# archive/db/crud.py's STALE_CLAIM_AFTER (5 minutes), so several
# heartbeats have to be missed before another worker considers the job
# abandoned -- one slow query or a brief hiccup must not hand the job to
# somebody else while this process is still working on it.
CLAIM_HEARTBEAT_SECONDS = 60


async def _heartbeat_loop(job_id: int) -> None:
    """Refresh this job's claim until cancelled. Never raises out: a
    failed heartbeat is worth a log line, but it must not take down the
    chunk that is otherwise going fine -- the worst case is the claim
    going stale, which is a recoverable state the system already
    handles."""
    while True:
        await asyncio.sleep(CLAIM_HEARTBEAT_SECONDS)
        try:
            if not await crud.heartbeat_claim(job_id):
                logger.info(
                    "Job %s: claim no longer in_progress, stopping heartbeat", job_id
                )
                return
        except Exception:
            logger.warning("Job %s: claim heartbeat failed", job_id, exc_info=True)


@asynccontextmanager
async def _keeping_claim_alive(job_id: int):
    """Hold a job's claim for as long as this block genuinely runs.

    Without this, a chunk slower than STALE_CLAIM_AFTER looked exactly
    like a crashed worker: the other replica claimed the same job, derived
    the same chunk_index from an unchanged chunks_completed, and both
    reported success -- appending the same window twice and skipping a
    real chunk, silently. See STALE_CLAIM_AFTER's own comment.

    Safe to wrap the whole chunk in because neither half blocks the event
    loop: extraction is subprocess I/O, and transcription goes through
    asyncio.to_thread (worker/transcription_engine.py). A heartbeat that
    could not actually fire during the slow part would be worse than
    none, since it would look like protection while providing none.
    """
    task = asyncio.create_task(_heartbeat_loop(job_id))
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


# --- Whole-meeting audio cache, for seek-hostile progressive sources ----

# Where a job's once-downloaded audio lives between chunks. Deliberately
# the worker's own local disk and NOT shared storage: it is a cache, not
# state. Two workers can claim different chunks of the same job, so a
# second worker simply finds no cache and downloads its own copy -- worst
# case two downloads instead of one per chunk, which is still an order of
# magnitude better than the per-chunk seeking this replaces. Nothing is
# ever *correct* only because the cache was there.
_AUDIO_CACHE_ROOT = Path(tempfile.gettempdir()) / "rtr_job_audio"


def _job_audio_cache_path(job_id: int) -> Path:
    return _AUDIO_CACHE_ROOT / f"job_{job_id}.mp3"


def _clear_job_audio_cache(job_id: int) -> None:
    """Drop a finished job's cached audio. Called on every terminal
    outcome; a missed one costs disk, not correctness, and
    _reset_audio_cache_root() sweeps those on the next restart."""
    try:
        _job_audio_cache_path(job_id).unlink(missing_ok=True)
    except OSError:
        logger.warning(
            "Could not remove cached audio for job %s", job_id, exc_info=True
        )


def _reset_audio_cache_root() -> None:
    """Wipe the cache directory at startup. A worker that crashed or was
    redeployed mid-job leaves files nothing will ever ask for again, and
    Render's disk is not large."""
    try:
        if _AUDIO_CACHE_ROOT.exists():
            shutil.rmtree(_AUDIO_CACHE_ROOT, ignore_errors=True)
        _AUDIO_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    except OSError:
        logger.warning("Could not reset the job audio cache", exc_info=True)


async def _chunk_audio_via_cache(
    *,
    job_id: int,
    media_url: str,
    source_url: str,
    start: float,
    duration: float,
    out_path: Path,
) -> tuple[bool, Optional[str]]:
    """Slice this chunk out of the job's cached audio, downloading that
    cache first if this worker does not have it yet."""
    cached = _job_audio_cache_path(job_id)
    if not cached.exists():
        logger.info(
            "Job %s: pulling whole-meeting audio once (seek-hostile source)", job_id
        )
        ok, reason = await extract_full_audio(
            media_url, source_page_url=source_url, out_path=cached
        )
        if not ok:
            # Leave nothing half-written behind for the next chunk to
            # mistake for a good cache.
            cached.unlink(missing_ok=True)
            return False, reason
        logger.info(
            "Job %s: cached %s bytes of audio; every later chunk of this job "
            "is now a local slice with no network at all",
            job_id,
            cached.stat().st_size,
        )
    return await slice_cached_audio(
        cached, start=start, duration=duration, out_path=out_path
    )


async def process_next_chunk(engine: TranscriptionEngine) -> bool:
    """Claims and processes one chunk. Returns True if a chunk was claimed
    (regardless of whether it succeeded), False if there was nothing to do
    -- the caller uses that to decide how long to sleep before polling
    again.
    """
    claim = await crud.claim_next_chunk()
    if claim is None:
        return False

    job_id = claim["job_id"]
    chunk_index = claim["chunk_index"]
    source_url = claim["source_url"]
    platform = claim["platform"]
    chunk_size = claim["chunk_size_seconds"]
    total_duration = claim["probed_duration_seconds"]
    total_chunks = claim["total_chunks"]

    logger.info("Claimed job %s: chunk %s/%s", job_id, chunk_index + 1, total_chunks)

    start = chunk_start(chunk_index, chunk_size)
    duration = chunk_duration(chunk_index, chunk_size, total_duration)

    # Re-resolve fresh rather than trusting the media_url frozen at submit
    # time -- HLS/signed URLs can go stale over a job that sits queued a
    # while or runs long. Falls back to the frozen URL if the re-resolve
    # itself fails (still worth trying the extraction rather than giving
    # up the chunk outright).
    media_url = claim["media_url"]
    try:
        finder = get_finder(platform)
        result = await finder.resolve(source_url)
        if result.video_url:
            media_url = result.video_url
    except UnsupportedPlatformError:
        pass
    except Exception:
        logger.warning(
            "Fresh re-resolve failed for job %s chunk %s, falling back to the frozen media_url",
            job_id,
            chunk_index,
            exc_info=True,
        )

    # Both halves below can legitimately outlast STALE_CLAIM_AFTER on a
    # slow source -- WO-54's whole-file pull alone gets its own 360s
    # budget -- so the claim is refreshed for as long as this genuinely
    # runs. Wraps extraction AND transcription: either can be the slow
    # one, and a heartbeat covering only the first would be protection
    # exactly where it is not needed.
    async with _keeping_claim_alive(job_id):
        # TemporaryDirectory is a *sync* context manager -- it has no
        # __aenter__, so it cannot join the `async with` above. Nested
        # deliberately rather than combined.
        with tempfile.TemporaryDirectory(prefix="rtr_transcribe_") as tmpdir:
            audio_path = Path(tmpdir) / f"chunk_{chunk_index}.mp3"
            # A progressive multi-chunk source pays a server-side seek scan
            # per chunk that grows with the offset (see
            # media_probe.extract_full_audio()'s measurements), so the whole
            # meeting's audio is pulled once and every chunk is then a local
            # slice. HLS keeps the per-chunk path, where fetching is already
            # minimal.
            if should_cache_whole_audio(media_url, total_chunks):
                extracted, extraction_error = await _chunk_audio_via_cache(
                    job_id=job_id,
                    media_url=media_url,
                    source_url=source_url,
                    start=start,
                    duration=duration,
                    out_path=audio_path,
                )
                if not extracted:
                    # Fall back to the per-chunk path rather than failing
                    # the chunk outright (WO-58). The whole-file pull is
                    # an optimisation for sources where seeking is
                    # expensive; on a source where it is NOT -- IQM2,
                    # measured 2026-08-25 -- per-chunk extraction works
                    # fine and is what this gate would otherwise have
                    # taken away. Without this, a file too large to pull
                    # inside _FULL_AUDIO_TIMEOUT_SECONDS turns a job that
                    # used to work into one that fails.
                    logger.info(
                        "Job %s: whole-audio path failed (%s), falling back "
                        "to per-chunk extraction for chunk %s",
                        job_id,
                        extraction_error,
                        chunk_index,
                    )
                    extracted, extraction_error = await extract_chunk_audio(
                        media_url,
                        start=start,
                        duration=duration,
                        source_page_url=source_url,
                        out_path=audio_path,
                    )
            else:
                extracted, extraction_error = await extract_chunk_audio(
                    media_url,
                    start=start,
                    duration=duration,
                    source_page_url=source_url,
                    out_path=audio_path,
                )
            if not extracted:
                logger.warning(
                    "Job %s: ffmpeg extraction failed for chunk %s/%s (%s) (will retry on next poll)",
                    job_id,
                    chunk_index + 1,
                    total_chunks,
                    extraction_error,
                )
                failure_result = await crud.report_chunk_result(
                    job_id,
                    success=False,
                    chunk_index=chunk_index,
                    error=extraction_error or "ffmpeg extraction failed",
                )
                await _handle_job_failure_result(job_id, failure_result)
                return True

            try:
                raw_segments = await engine.transcribe_chunk(audio_path)
            except Exception as e:
                logger.exception(
                    "Job %s: transcription failed for chunk %s/%s (will retry on next poll)",
                    job_id,
                    chunk_index + 1,
                    total_chunks,
                )
                failure_result = await crud.report_chunk_result(
                    job_id, success=False, chunk_index=chunk_index, error=str(e)
                )
                await _handle_job_failure_result(job_id, failure_result)
                return True

    shifted = shift_segments(raw_segments, start)
    # Detect a real seam-duplicate against what the previous chunk already
    # persisted -- confirmed live 2026-08-16 (Boulder County, CO, see
    # worker/segment_utils.py's own "Seam-duplication dedup" note and
    # BACKLOG_DONE.md): extract_chunk_audio()'s fast HLS seek can land
    # several real seconds before this chunk's requested start, so its
    # transcript can restate the end of the previous chunk's own segments.
    drop_previous_tail = count_seam_overlap_segments(
        claim.get("partial_segments") or [], shifted
    )
    result = await crud.report_chunk_result(
        job_id,
        success=True,
        shifted_segments=shifted,
        drop_previous_tail=drop_previous_tail,
    )
    if drop_previous_tail:
        logger.info(
            "Job %s: dropped %s seam-duplicate segment(s) from the previous chunk's tail",
            job_id,
            drop_previous_tail,
        )
    logger.info(
        "Job %s: chunk %s/%s done (%s segments), job status now %s",
        job_id,
        chunk_index + 1,
        total_chunks,
        len(shifted),
        result.get("status"),
    )

    if result.get("status") == "completed":
        logger.info(
            "Job %s completed -> transcript_version %s",
            job_id,
            result.get("transcript_version_id"),
        )
        _clear_job_audio_cache(job_id)
        await _send_completion_email(job_id)
    # A success=True report_chunk_result() call can only ever return
    # "completed" or "in_progress" -- a "failed"/"retry_scheduled" status
    # only comes back from the success=False call sites above, handled by
    # _handle_job_failure_result() there. No branch for it needed here.

    return True


async def _handle_job_failure_result(job_id: int, result: dict) -> None:
    """Real gap closed 2026-08-19: this is the only place a chunk failure's
    outcome (from either success=False report_chunk_result() call site
    above) was ever inspected -- previously neither call site looked at
    what it got back, so a job reaching "failed" never triggered
    _send_failure_email() at all despite that function existing and being
    tested in isolation (see BACKLOG.md). Now also handles
    "retry_scheduled" (crud.report_chunk_result()'s escalating-backoff
    retry for real user-priority jobs) -- logged, not emailed, since a
    scheduled retry isn't a final outcome yet.
    """
    status = result.get("status")
    if status == "retry_scheduled":
        logger.info(
            "Job %s: chunk failure budget exhausted, scheduled retry #%s for %s",
            job_id,
            result.get("retry_count"),
            result.get("next_retry_at"),
        )
    elif status == "failed":
        logger.info(
            "Job %s gave up for good after %s retr%s",
            job_id,
            result.get("retry_count", 0),
            "y" if result.get("retry_count") == 1 else "ies",
        )
        # Terminal, so nothing will ask for this job's cached audio again.
        # Deliberately NOT cleared on "retry_scheduled" above: that job is
        # coming back, and keeping the cache is exactly what makes the
        # retry cheap.
        _clear_job_audio_cache(job_id)
        await _send_failure_email(job_id)


async def _send_completion_email(job_id: int) -> None:
    status = await crud.get_transcription_job_status(job_id)
    if status is None or not status.get("meeting_page_slug"):
        return

    excerpt = ""
    page = await crud.get_page_by_slug(status["meeting_page_slug"])
    if page:
        version = next(
            (
                v
                for v in page["versions"]
                if v["id"] == status.get("transcript_version_id")
            ),
            None,
        )
        if version:
            excerpt = " ".join(s["text"] for s in version["segments"])[
                :EMAIL_EXCERPT_CHARS
            ]

    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    page_url = f"{base}/m/{status['meeting_page_slug']}"
    sent = await email_utils.send_completion_email(
        status["requester_email"],
        meeting_title=status.get("meeting_page_title") or "your meeting",
        excerpt=excerpt,
        page_url=page_url,
    )
    logger.info(
        "Job %s: completion email to Resend %s",
        job_id,
        "accepted" if sent else "FAILED (see prior log line)",
    )


async def _send_failure_email(job_id: int) -> None:
    # Mirrors _send_completion_email()'s shape exactly -- same status
    # lookup, same "no resolvable meeting page, nothing to email" bail-out
    # (shouldn't happen in practice: a job always belongs to an existing
    # MeetingPage, but matches the defensive style already used above).
    # Deliberately no auto-transcription filtering here, same as the
    # completion path: AUTO_TRANSCRIPTION_REQUESTER_EMAIL jobs already
    # get treated as a real "requester" throughout this module (see that
    # constant's own docstring -- it doubles as Ryan's activity digest
    # address), so a failed auto-job reaching him as this same branded
    # email is existing behavior, not a new side effect of adding this.
    status = await crud.get_transcription_job_status(job_id)
    if status is None or not status.get("meeting_page_slug"):
        return

    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    page_url = f"{base}/m/{status['meeting_page_slug']}"
    # A terminally-failed job now publishes the chunks it did finish
    # (crud._publish_partial_transcript()), so `transcript_version_id`
    # being set on a *failed* job means there is real transcript waiting
    # on the page. That flips the email from "we couldn't do it" to
    # "here's what we got", which is the whole point of publishing the
    # partial in the first place.
    partial_coverage = None
    if status.get("transcript_version_id") and status.get("transcribed_seconds"):
        partial_coverage = crud._duration_words(status["transcribed_seconds"])
    sent = await email_utils.send_transcription_failed_email(
        status["requester_email"],
        meeting_title=status.get("meeting_page_title") or "your meeting",
        page_url=page_url,
        partial_coverage=partial_coverage,
    )
    logger.info(
        "Job %s: failure email to Resend %s",
        job_id,
        "accepted" if sent else "FAILED (see prior log line)",
    )

    # Separate operator-facing alert with the real diagnostics (job id,
    # source URL, requester, chunk progress, retry history) the branded
    # requester-facing email above deliberately doesn't carry -- real gap
    # flagged 2026-08-19 after job 256 (Redwood City, CA) failed with no
    # one noticing until asked directly. See BACKLOG.md.
    admin_sent = await email_utils.send_admin_job_failure_alert(
        job_id=job_id,
        requester_email=status["requester_email"],
        meeting_title=status.get("meeting_page_title") or "(untitled)",
        page_url=page_url,
        source_url=status.get("source_url"),
        chunks_completed=status.get("chunks_completed"),
        total_chunks=status.get("total_chunks"),
        retry_count=status.get("retry_count", 0),
        error_message=status.get("error_message"),
        failure_history=status.get("failure_history") or [],
        created_at=status.get("created_at"),
    )
    logger.info(
        "Job %s: admin failure alert to Resend %s",
        job_id,
        "accepted" if admin_sent else "FAILED or not configured (see prior log line)",
    )


async def run_forever() -> None:
    register_all_finders()
    # A crash or redeploy mid-job leaves cached audio nothing will ever
    # ask for again, and Render's ephemeral disk is not large.
    _reset_audio_cache_root()
    logger.info("Loading transcription model (this can take a while on first run)...")
    engine = build_default_engine()
    logger.info("Model loaded. Entering poll loop.")

    empty_polls = 0
    last_auto_check = 0.0
    while True:
        try:
            processed = await process_next_chunk(engine)
        except Exception:
            logger.exception("Unhandled error in worker loop iteration.")
            processed = False

        if processed:
            empty_polls = 0
        else:
            empty_polls += 1
            if empty_polls % EMPTY_POLL_HEARTBEAT_EVERY == 0:
                logger.info(
                    "Still polling, nothing queued (checked %s times since last job).",
                    empty_polls,
                )

            # process_next_chunk() returning False means *this* worker's
            # own claim_next_chunk() call found nothing claimable right
            # now -- with a second worker process now possible (see
            # render.yaml's rtr-transcription-worker-2), that's no longer
            # proof the queue is globally empty, just that nothing was
            # available to this process at this instant (the other worker
            # could be mid-claim on the last row, or claim something a
            # moment later). claim_next_chunk()'s SKIP LOCKED already makes
            # an auto-generation check firing here harmless even if that
            # happens -- create_transcription_job() only ever adds a job,
            # it never steps on one already in flight. Gated separately by
            # AUTO_GENERATION_CHECK_INTERVAL_SECONDS so this doesn't run on
            # every single empty poll.
            now = time.monotonic()
            if now - last_auto_check >= AUTO_GENERATION_CHECK_INTERVAL_SECONDS:
                last_auto_check = now
                try:
                    if await maybe_generate_auto_job():
                        empty_polls = 0
                except Exception:
                    logger.exception("Unhandled error in auto-generation check.")

        await asyncio.sleep(
            POLL_INTERVAL_SECONDS if processed else EMPTY_POLL_BACKOFF_SECONDS
        )


if __name__ == "__main__":
    asyncio.run(run_forever())
