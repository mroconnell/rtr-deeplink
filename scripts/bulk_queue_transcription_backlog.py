"""Bulk-creates several low-priority TranscriptionJob rows at once for the
on-demand-transcription backlog, so two (or more) cloud workers have real
concurrent work to chew through during a backlog catch-up window (see
render.yaml's `rtr-transcription-worker-2` and BACKLOG.md's matching
entry).

Why this exists -- the gap it closes: worker/main.py's own idle-time
auto-generation (maybe_generate_auto_job()) only ever creates ONE job at
a time, because it's only invoked once claim_next_chunk() finds the
*entire* active job table empty. A single TranscriptionJob's chunks are
inherently serial (claim_next_chunk() claims one job's next
chunks_completed index at a time -- see its own docstring), so a second
worker process only gets real parallel throughput once >= 2 *different*
jobs are concurrently queued/in_progress at once, which the existing
one-job-at-a-time trickle essentially never produces on its own. This
script closes that gap directly: pull several backlog candidates from the
existing GET /internal/transcription-backlog (the same endpoint
scripts/transcribe_backlog_locally.py already uses) and create a real
TranscriptionJob for each via POST /internal/transcription/create-job, at
the newly-exposed priority=PRIORITY_LOW (archive/main.py's
TranscriptionCreateJobRequest -- previously only worker/main.py's own
direct in-process call could ever use that tier; see crud.PRIORITY_LOW's
own "reserved for future self-generated/idle-time batch work" comment).

Reuses the exact same feasibility gate worker/main.py's own
maybe_generate_auto_job() already applies before creating a job --
re-resolve fresh (never trust a stored video_url, which can go stale),
probe_duration(), is_plausible_meeting_duration() -- so an infeasible
candidate is skipped cheaply here too, before ever reaching
create-job. Does NOT do any local transcription itself (unlike
scripts/transcribe_backlog_locally.py) -- the actual Whisper work happens
on whichever cloud worker claims the chunk later; this script only ever
creates queue rows.

Deliberately capped well under archive/db/crud.py's global
MAX_CONCURRENT_TRANSCRIPTION_JOBS=15 (default --limit BATCH_SIZE below,
override with --limit) -- that cap is shared across every priority tier,
so filling it entirely with backlog work would make a real live
visitor's own transcription request fail outright with
"too_many_active_jobs" during the catch-up window. BATCH_SIZE leaves real
headroom free for that, and PRIORITY_LOW means a real request still
jumps ahead of whatever this script queued at the very next
claim_next_chunk() call regardless of how full the batch is
(claim_next_chunk() orders priority.desc() first, created_at.asc()
second). Also stops the run early (not an error) the moment a response
comes back {"error": "too_many_active_jobs", ...} -- defensive, in case
real concurrent usage has already used up headroom since the run started.

skip_confirmation is achieved via clerk_verified=True, not by relying on
AUTO_TRANSCRIPTION_REQUESTER_EMAIL already being a Resend audience
member: archive/main.py's own TranscriptionCreateJobRequest.clerk_verified
docstring already establishes the trust boundary as "a bearer-token-gated
internal call, not a client-asserted flag" -- this script holds
ARCHIVE_INGEST_TOKEN, the same trusted-internal-caller position the
resolver itself is in after its own real Clerk check. Without this, a job
would land in pending_confirmation and need a manual confirmation-email
click before it's ever claimable, defeating the entire point of this
script.

Manually re-run, not cron'd -- the two-worker setup this feeds is meant
as a temporary catch-up measure, so this stays a hand-run tool to top the
queue back up whenever it drains, not a new scheduled GitHub Actions
workflow. A scheduled version is a natural follow-up if the backlog turns
out to need sustained automated feeding beyond this catch-up window --
not built now, see BACKLOG.md.

Usage (from the repo root, with the venv active):
    python scripts/bulk_queue_transcription_backlog.py --dry-run
    python scripts/bulk_queue_transcription_backlog.py
    python scripts/bulk_queue_transcription_backlog.py --limit 4

Requires ARCHIVE_BASE_URL, ARCHIVE_INGEST_TOKEN, and
AUTO_TRANSCRIPTION_REQUESTER_EMAIL in the repo's local .env (same vars
scripts/transcribe_backlog_locally.py / worker/main.py already use -- the
email is reused for the same "real person's address as a lightweight
activity digest, not a dedicated no-reply mailbox" reasoning
worker/main.py's own AUTO_TRANSCRIPTION_REQUESTER_EMAIL comment already
documents, not a new convention).
"""

import argparse
import asyncio
import logging
import os
import random
import sys
from pathlib import Path
from typing import Optional

import aiohttp
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import UnsupportedPlatformError, get_finder  # noqa: E402
from app.platforms.media_probe import (  # noqa: E402
    is_plausible_meeting_duration,
    probe_duration,
)

# Same "flushes immediately even when piped to a log file" reasoning as
# worker/main.py / scripts/transcribe_backlog_locally.py -- see the
# latter's own module comment for the real incident that established this
# convention (a redirected multi-hour run showed zero output despite
# being alive, since bare print() fully buffers on a redirected stream).
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
    force=True,
)
logger = logging.getLogger("rtr_bulk_queue_backlog")

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=65)  # matches archive_client.PUSH_TIMEOUT

# Deliberately well under archive/db/crud.py's global
# MAX_CONCURRENT_TRANSCRIPTION_JOBS=15 -- see module docstring for why.
BATCH_SIZE = 8

# Must match app/main.py's TRANSCRIPTION_CHUNK_SIZE_SECONDS / worker/
# main.py's AUTO_TRANSCRIPTION_CHUNK_SIZE_SECONDS -- duplicated rather
# than imported across the script/worker boundary, same convention
# worker/main.py itself already uses for this exact constant.
CHUNK_SIZE_SECONDS = 900

# Same retry policy as scripts/transcribe_backlog_locally.py's
# _request_json() -- see that function's own comment for the full
# reasoning (5xx/connection-level errors are retryable, 4xx is a real,
# static problem that retrying can't fix).
MAX_RETRIES = 6
RETRY_BASE_DELAY_SECONDS = 5.0
RETRY_MAX_DELAY_SECONDS = 90.0


class _RetryableHTTPError(Exception):
    pass


async def _request_json(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    *,
    label: str,
    max_retries: int = MAX_RETRIES,
    **kwargs,
) -> dict:
    """Copied from scripts/transcribe_backlog_locally.py's own
    _request_json() verbatim (same retry policy, same reasoning) rather
    than importing it -- that script is a standalone entry point, not a
    shared library, same "duplicated across scripts" convention this
    repo already uses elsewhere (e.g. worker/main.py's own
    AUTO_TRANSCRIPTION_CHUNK_SIZE_SECONDS).
    """
    last_error: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            async with session.request(method, url, **kwargs) as response:
                if response.status >= 500:
                    text = await response.text()
                    raise _RetryableHTTPError(
                        f"HTTP {response.status} for {label}: {text[:200]}"
                    )
                if response.status >= 400:
                    text = await response.text()
                    raise RuntimeError(
                        f"{label} failed ({response.status}) -- not retrying, this looks "
                        f"like a real config/request problem rather than a transient one: "
                        f"{text[:300]}"
                    )
                return await response.json()
        except (_RetryableHTTPError, aiohttp.ClientError, asyncio.TimeoutError) as e:
            last_error = e
            if attempt == max_retries - 1:
                break
            delay = min(
                RETRY_MAX_DELAY_SECONDS,
                RETRY_BASE_DELAY_SECONDS * (2**attempt) * random.uniform(0.5, 1.5),
            )
            logger.warning(
                "%s failed (attempt %d/%d): %s -- retrying in %.0fs",
                label,
                attempt + 1,
                max_retries,
                str(e)[:200],
                delay,
            )
            await asyncio.sleep(delay)
    raise RuntimeError(f"{label} failed after {max_retries} attempts: {last_error}")


def _base_url() -> str:
    return os.environ.get("ARCHIVE_BASE_URL", "").rstrip("/")


def _headers() -> dict:
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _auto_media_kind(video_format) -> str:
    # Copied from worker/main.py's own _auto_media_kind() -- a private
    # module-level function there, not exported API, so duplicated here
    # rather than imported (same reasoning as this module's other
    # constant duplications).
    return "audio" if (video_format or "") in ("mp3", "wav") else "video"


async def _get_candidates(session: aiohttp.ClientSession, limit: int) -> list:
    data = await _request_json(
        session,
        "GET",
        f"{_base_url()}/internal/transcription-backlog",
        label="candidate list fetch",
        headers=_headers(),
        params={"limit": str(limit)},
        timeout=REQUEST_TIMEOUT,
    )
    return data.get("pages", [])


async def _create_job(
    session: aiohttp.ClientSession,
    *,
    payload: dict,
    source_url: str,
    requester_email: str,
    media_url: str,
    media_kind: str,
    duration: float,
) -> dict:
    body = {
        "payload": payload,
        "input_url_normalized": source_url,
        "requester_email": requester_email,
        "media_url": media_url,
        "media_kind": media_kind,
        "probed_duration_seconds": duration,
        "chunk_size_seconds": CHUNK_SIZE_SECONDS,
        "clerk_verified": True,  # see module docstring -- trusted internal caller
        "priority": 0,  # crud.PRIORITY_LOW -- see module docstring
    }
    return await _request_json(
        session,
        "POST",
        f"{_base_url()}/internal/transcription/create-job",
        label=f"create-job for {source_url}",
        json=body,
        headers=_headers(),
        timeout=REQUEST_TIMEOUT,
    )


async def _check_feasible(page: dict) -> dict:
    """Same feasibility gate worker/main.py's own maybe_generate_auto_job()
    already applies -- re-resolve fresh, probe real duration, reject an
    implausible one -- before this script ever spends a create-job call on
    a candidate that's just going to fail immediately once claimed anyway.
    Returns {"ok": True, "result": <ResolvedMeeting>, "duration": float} or
    {"ok": False, "reason": "..."}.
    """
    source_url = page["source_url_normalized"]
    platform = page["platform"]

    # Cheap pre-filter before any real work -- a YouTube-backed page's
    # video_url is a youtube.com watch/embed URL, not a direct-streamable
    # one ffprobe can read; this would just fail probe_duration() a few
    # seconds later anyway, but skipping it up front avoids a wasted
    # network round-trip and keeps this run's "skipped" reasons
    # meaningful, same as scripts/transcribe_backlog_locally.py's own
    # identical pre-filter (see that script's process_one() comment).
    if (page.get("video_format") or "") == "youtube":
        return {
            "ok": False,
            "reason": "YouTube-backed page -- not ffprobe/ffmpeg-extractable directly "
            "(needs fetch_youtube_transcripts.py's caption-fetch path instead)",
        }

    try:
        finder = get_finder(platform)
    except UnsupportedPlatformError as e:
        return {"ok": False, "reason": f"unsupported platform: {e}"}

    try:
        result = await finder.resolve(source_url)
    except Exception as e:
        return {
            "ok": False,
            "reason": f"re-resolve failed: {type(e).__name__}: {str(e)[:200]}",
        }

    if not result.video_url:
        return {"ok": False, "reason": "no usable audio/video source on re-resolve"}

    duration = await probe_duration(result.video_url, source_page_url=source_url)
    if duration is None:
        return {"ok": False, "reason": "ffprobe couldn't read the media"}
    if not is_plausible_meeting_duration(duration):
        return {
            "ok": False,
            "reason": f"implausible duration ({duration:.0f}s) -- not a real meeting recording",
        }

    return {"ok": True, "result": result, "duration": duration}


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check feasibility and report, but don't create any jobs",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=BATCH_SIZE,
        help=f"Create at most this many jobs this run (default {BATCH_SIZE} -- "
        "see module docstring for why this stays well under "
        "MAX_CONCURRENT_TRANSCRIPTION_JOBS=15)",
    )
    args = parser.parse_args()

    if not _base_url():
        logger.error("ARCHIVE_BASE_URL is not set (check the repo's .env). Stopping.")
        sys.exit(1)
    if not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        logger.error(
            "ARCHIVE_INGEST_TOKEN is not set (check the repo's .env). Stopping."
        )
        sys.exit(1)
    requester_email = os.environ.get("AUTO_TRANSCRIPTION_REQUESTER_EMAIL", "")
    if not requester_email:
        logger.error(
            "AUTO_TRANSCRIPTION_REQUESTER_EMAIL is not set (check the repo's .env) -- "
            "every job this script creates needs a requester_email (the column is "
            "required, and it's also who gets the completion-email activity digest, "
            "same as worker/main.py's own auto-generation path). Stopping."
        )
        sys.exit(1)

    logger.info(
        "Run started: limit=%s, dry_run=%s, requester_email=%s",
        args.limit,
        args.dry_run,
        requester_email,
    )

    register_all_finders()

    async with aiohttp.ClientSession() as session:
        try:
            pages = await _get_candidates(session, args.limit)
        except Exception as e:
            logger.error(
                "Could not fetch the candidate list from %s, even after retrying: %s "
                "-- nothing was queued this run.",
                _base_url(),
                e,
            )
            sys.exit(1)

        if not pages:
            logger.info("Transcription backlog is empty -- nothing to do.")
            return

        logger.info(
            "%s%d candidate meeting(s) from %s",
            "[DRY RUN] " if args.dry_run else "",
            len(pages),
            _base_url(),
        )

        created = skipped = capped = 0
        for i, page in enumerate(pages):
            slug = page.get("slug", "?")
            logger.info("Candidate %d/%d: %s", i + 1, len(pages), slug)

            feasible = await _check_feasible(page)
            if not feasible["ok"]:
                skipped += 1
                logger.info("  SKIPPED: %s", feasible["reason"])
                continue

            if args.dry_run:
                logger.info(
                    "  [dry-run] would create a PRIORITY_LOW job (duration=%.0fs)",
                    feasible["duration"],
                )
                continue

            result = feasible["result"]
            try:
                response = await _create_job(
                    session,
                    payload=result.model_dump(),
                    source_url=page["source_url_normalized"],
                    requester_email=requester_email,
                    media_url=result.video_url,
                    media_kind=_auto_media_kind(result.video_format),
                    duration=feasible["duration"],
                )
            except Exception as e:
                logger.error("  FAILED to create job: %s", e)
                continue

            if response.get("error") == "too_many_active_jobs":
                capped += 1
                logger.info(
                    "  STOPPING: too_many_active_jobs -- headroom under "
                    "MAX_CONCURRENT_TRANSCRIPTION_JOBS is already used up "
                    "(real concurrent usage, or a previous run's jobs still in flight)."
                )
                break

            created += 1
            logger.info("  CREATED job %s for %s", response.get("job_id"), slug)
            logger.info(
                "Progress so far: %d created, %d skipped (of %d candidates)",
                created,
                skipped,
                len(pages),
            )

        logger.info(
            "RUN COMPLETE: %d created, %d skipped, capped=%s (of %d candidates).",
            created,
            skipped,
            bool(capped),
            len(pages),
        )


if __name__ == "__main__":
    load_dotenv()
    asyncio.run(main())
