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
import logging
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv

from app.platforms import register_all_finders
from app.platforms.base import UnsupportedPlatformError, get_finder
from app.platforms.media_probe import extract_chunk_audio
from archive.db import crud
from archive.utils import email as email_utils
from worker.segment_utils import chunk_duration, chunk_start, shift_segments
from worker.transcription_engine import TranscriptionEngine, build_default_engine

load_dotenv()
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
            job_id, chunk_index, exc_info=True,
        )

    with tempfile.TemporaryDirectory(prefix="rtr_transcribe_") as tmpdir:
        audio_path = Path(tmpdir) / f"chunk_{chunk_index}.mp3"
        extracted = await extract_chunk_audio(
            media_url, start=start, duration=duration, source_page_url=source_url, out_path=audio_path,
        )
        if not extracted:
            logger.warning(
                "Job %s: ffmpeg extraction failed for chunk %s/%s (will retry on next poll)",
                job_id, chunk_index + 1, total_chunks,
            )
            await crud.report_chunk_result(job_id, success=False, error="ffmpeg extraction failed")
            return True

        try:
            raw_segments = await engine.transcribe_chunk(audio_path)
        except Exception as e:
            logger.exception(
                "Job %s: transcription failed for chunk %s/%s (will retry on next poll)",
                job_id, chunk_index + 1, total_chunks,
            )
            await crud.report_chunk_result(job_id, success=False, error=str(e))
            return True

    shifted = shift_segments(raw_segments, start)
    result = await crud.report_chunk_result(job_id, success=True, shifted_segments=shifted)
    logger.info(
        "Job %s: chunk %s/%s done (%s segments), job status now %s",
        job_id, chunk_index + 1, total_chunks, len(shifted), result.get("status"),
    )

    if result.get("status") == "completed":
        logger.info("Job %s completed -> transcript_version %s", job_id, result.get("transcript_version_id"))
        await _send_completion_email(job_id)

    return True


async def _send_completion_email(job_id: int) -> None:
    status = await crud.get_transcription_job_status(job_id)
    if status is None or not status.get("meeting_page_slug"):
        return

    excerpt = ""
    page = await crud.get_page_by_slug(status["meeting_page_slug"])
    if page:
        version = next(
            (v for v in page["versions"] if v["id"] == status.get("transcript_version_id")),
            None,
        )
        if version:
            excerpt = " ".join(s["text"] for s in version["segments"])[:EMAIL_EXCERPT_CHARS]

    base = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")
    page_url = f"{base}/m/{status['meeting_page_slug']}"
    sent = await email_utils.send_completion_email(
        status["requester_email"],
        meeting_title=status.get("meeting_page_title") or "your meeting",
        excerpt=excerpt,
        page_url=page_url,
    )
    logger.info("Job %s: completion email to Resend %s", job_id, "accepted" if sent else "FAILED (see prior log line)")


async def run_forever() -> None:
    register_all_finders()
    logger.info("Loading transcription model (this can take a while on first run)...")
    engine = build_default_engine()
    logger.info("Model loaded. Entering poll loop.")

    empty_polls = 0
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
                logger.info("Still polling, nothing queued (checked %s times since last job).", empty_polls)

        await asyncio.sleep(POLL_INTERVAL_SECONDS if processed else EMPTY_POLL_BACKOFF_SECONDS)


if __name__ == "__main__":
    asyncio.run(run_forever())
