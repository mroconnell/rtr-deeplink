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

Runs hourly via .github/workflows/bulk-queue-transcription-backlog.yml
(added 2026-08-21, after a live run confirmed both workers genuinely idle
between manual runs -- see BACKLOG.md's matching entry) -- also safe to
run by hand any time the queue needs an immediate top-up rather than
waiting for the next scheduled run. Server-side dedup
(create_transcription_job() returns the existing job for a page instead
of creating a duplicate) plus the too_many_active_jobs early-stop above
are what make hourly safe: a page that already has an active job is a
no-op here, and the run stops on its own once real headroom under
MAX_CONCURRENT_TRANSCRIPTION_JOBS is used up, so this doesn't pile up an
ever-growing queue between runs. Tied to the backlog catch-up window this
second worker exists for -- revisit the cadence (or disable the workflow)
once BACKLOG.md's backlog figure is worked down and a single worker's own
idle-time trickle is enough again.

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

WO-83 (2026-08-30): a candidate whose feasibility check below fails now
has that failure RECORDED via /internal/transcription/record-probe-
failure (crud.create_failed_auto_transcription_job() under the hood),
not just skipped and forgotten. Root cause of BACKLOG.md's "hourly
transcription top-up driver has been creating zero jobs" entry: this
script's own client-side ffprobe-feasibility skip happens BEFORE any
TranscriptionJob row exists for the candidate, so
crud._in_auto_transcription_cooldown() (which only ever looks at
TranscriptionJob history) never engaged -- the same 8
archive-stream.granicus.com candidates, all hitting the platform's known
origin 504 ("ffprobe couldn't read the media"), got re-selected and
re-skipped identically on every single hourly run, forever, blocking
this driver from ever reaching further into the backlog to find real
probeable work. Recording the failure the same way worker/main.py's own
maybe_generate_auto_job() already does for its single-candidate idle-time
path lets the escalating cooldown (1 day, doubling to a 30-day cap --
see AUTO_TRANSCRIPTION_BASE_COOLDOWN) actually apply, so each hourly run
now grinds a little further into a dense bad-host band instead of
grinding the same 8 candidates in place. Not done in --dry-run mode,
consistent with --dry-run creating no other rows either.
"""

import argparse
import asyncio
import logging
import os
import random
import sys
from pathlib import Path
from typing import Optional

import certifi

# Must run before `import aiohttp` -- see scripts/transcribe_backlog_
# locally.py's own longer comment on this same fix (confirmed live
# 2026-08-21: a fresh Homebrew-Python venv has an empty default SSL trust
# store, and aiohttp caches its default SSLContext at import time).
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import UnsupportedPlatformError, get_finder  # noqa: E402
from app.platforms.media_probe import (  # noqa: E402
    chunk_size_seconds_for_platform,
    probe_duration_and_chunk_plan,
    is_plausible_meeting_duration,
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
    shared library.
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
    chunk_plan: Optional[list] = None,
) -> dict:
    body = {
        "payload": payload,
        "input_url_normalized": source_url,
        "requester_email": requester_email,
        "media_url": media_url,
        "media_kind": media_kind,
        "probed_duration_seconds": duration,
        "chunk_size_seconds": chunk_size_seconds_for_platform(
            payload.get("platform", "")
        ),
        "clerk_verified": True,  # see module docstring -- trusted internal caller
        "priority": 0,  # crud.PRIORITY_LOW -- see module docstring
        # WO-98. None for an ordinary single-video meeting, which is the
        # overwhelming majority and exactly what this key's absence used to
        # mean; set for a multi-clip one, where omitting it silently queued
        # a first-clip-only job.
        "chunk_plan": chunk_plan,
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


async def _record_probe_failure(
    session: aiohttp.ClientSession, page: dict, reason: str, requester_email: str
) -> None:
    """Records this candidate's client-side feasibility-probe failure as a
    real 'failed' TranscriptionJob row, via the new
    /internal/transcription/record-probe-failure route (crud.
    create_failed_auto_transcription_job() under the hood) -- see this
    module's own docstring (WO-83) for why this matters: without it,
    crud._in_auto_transcription_cooldown() never engages for a candidate
    whose probe fails here, and it gets re-selected identically forever.

    `meeting_page_id` comes from the candidate dict GET
    /internal/transcription-backlog already returns (see
    list_transcription_backlog_candidates()'s docstring) -- no separate
    lookup needed. Missing it (an older Archive deploy that hasn't picked
    up that field yet) is treated as a no-op rather than a malformed
    request; a deploy-ordering gap here just means this run's candidate
    gets retried next run instead of entering cooldown a run early, not a
    crash.

    Best-effort: any failure recording the failure is logged and
    swallowed rather than raised. The downside of losing one record-
    probe-failure call (this candidate just gets re-tried next run
    instead of resting in cooldown until tomorrow) is far smaller than
    aborting the whole batch over a bookkeeping call that was never the
    actual point of this run.
    """
    meeting_page_id = page.get("meeting_page_id")
    if meeting_page_id is None:
        return
    try:
        await _request_json(
            session,
            "POST",
            f"{_base_url()}/internal/transcription/record-probe-failure",
            label=f"record probe failure for {page.get('slug', '?')}",
            json={
                "meeting_page_id": meeting_page_id,
                "requester_email": requester_email,
                "error_message": reason,
            },
            headers=_headers(),
            timeout=REQUEST_TIMEOUT,
        )
    except Exception as e:
        logger.warning(
            "  Could not record probe failure for %s (will just be retried "
            "next run instead of entering a cooldown): %s",
            page.get("slug", "?"),
            str(e)[:200],
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

    # WO-98: probe_duration(result.video_url) alone was a real bug here --
    # for a multi-clip meeting that URL is only the FIRST clip, so this
    # script queued jobs covering a fraction of the meeting, silently and
    # without failing. The shared helper makes the same multi-clip decision
    # app/main.py and worker/main.py already made; see its docstring.
    duration, chunk_plan = await probe_duration_and_chunk_plan(
        result,
        source_page_url=source_url,
        max_chunk_seconds=chunk_size_seconds_for_platform(result.platform),
    )
    if duration is None:
        return {"ok": False, "reason": "ffprobe couldn't read the media"}
    if not is_plausible_meeting_duration(duration):
        return {
            "ok": False,
            "reason": f"implausible duration ({duration:.0f}s) -- not a real meeting recording",
        }

    return {
        "ok": True,
        "result": result,
        "duration": duration,
        "chunk_plan": chunk_plan,
    }


_OUTCOME_CREATED = "created"
_OUTCOME_SKIPPED = "skipped"
_OUTCOME_CAPPED = "capped"
# The create-job HTTP call itself failed (network/5xx after retries, or a
# real 4xx) -- distinct from _OUTCOME_SKIPPED (an infeasible candidate)
# so main() can keep its pre-existing behavior of not counting this
# against either counter, same as before this function was split out.
_OUTCOME_CREATE_FAILED = "create_failed"


async def _process_candidate(
    session: aiohttp.ClientSession,
    page: dict,
    *,
    requester_email: str,
    dry_run: bool,
) -> str:
    """Runs the feasibility check for one candidate and, depending on the
    result, either creates a real PRIORITY_LOW job, records a probe
    failure (see _record_probe_failure()'s docstring -- WO-83), or (dry
    run) just reports what it would have done. Returns one of the
    _OUTCOME_* constants above for main()'s counters and stop-the-batch
    decision.

    Split out from main()'s loop specifically so this per-candidate
    decision is unit-testable without a real aiohttp session, env vars,
    or a running Archive -- see tests/test_bulk_queue_transcription_
    backlog.py.
    """
    slug = page.get("slug", "?")
    feasible = await _check_feasible(page)
    if not feasible["ok"]:
        logger.info("  SKIPPED: %s", feasible["reason"])
        if not dry_run:
            await _record_probe_failure(
                session, page, feasible["reason"], requester_email
            )
        return _OUTCOME_SKIPPED

    if dry_run:
        logger.info(
            "  [dry-run] would create a PRIORITY_LOW job (duration=%.0fs)",
            feasible["duration"],
        )
        return _OUTCOME_SKIPPED

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
            chunk_plan=feasible.get("chunk_plan"),
        )
    except Exception as e:
        logger.error("  FAILED to create job: %s", e)
        return _OUTCOME_CREATE_FAILED

    if response.get("error") == "too_many_active_jobs":
        logger.info(
            "  STOPPING: too_many_active_jobs -- headroom under "
            "MAX_CONCURRENT_TRANSCRIPTION_JOBS is already used up "
            "(real concurrent usage, or a previous run's jobs still in flight)."
        )
        return _OUTCOME_CAPPED

    logger.info("  CREATED job %s for %s", response.get("job_id"), slug)
    return _OUTCOME_CREATED


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

            outcome = await _process_candidate(
                session, page, requester_email=requester_email, dry_run=args.dry_run
            )

            if outcome == _OUTCOME_CREATED:
                created += 1
                logger.info(
                    "Progress so far: %d created, %d skipped (of %d candidates)",
                    created,
                    skipped,
                    len(pages),
                )
            elif outcome == _OUTCOME_CAPPED:
                capped += 1
                break
            elif outcome == _OUTCOME_SKIPPED:
                skipped += 1
            # _OUTCOME_CREATE_FAILED: matches the pre-refactor behavior of
            # not counting a create-job HTTP failure against either
            # counter -- it's a real error already logged by
            # _process_candidate, not a feasibility skip.

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
