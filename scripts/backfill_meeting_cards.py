"""Drives POST /internal/thumbnails/backfill across the whole Archive, so
every already-archived meeting page ends up with a real `og:image` /
`VideoObject.thumbnailUrl` instead of only the ones somebody happened to
load (WO-37, the operator half of WO-28's residual).

Why a script and not a curl loop: the endpoint runs extractions *inline*
with a small `limit` on purpose (each item is one `ffprobe` plus one
`ffmpeg` against a government CDN), so clearing the backlog by hand is
hundreds of identical calls with no record of what already happened --
a real dry run on 2026-08-21 measured that backlog at **1705 pages**, not
the ~1200 the WO-28 residual estimated. Confirmed live the same day that
the underlying path works in
production -- `GET /api/health` reports a real `ffmpeg` version on the
Archive service, and a cold page gains a real ~57KB `/m/{slug}/card.jpg`
after one view -- so what was missing was only something to reach the
pages nobody views.

**Resumability is mostly free, and the one place it isn't is the whole
design here.** `crud.list_pages_missing_default_thumbnail()` returns
pages that have no default frame yet, newest first, so a page extracted
successfully simply leaves the queue and a restart never redoes it. A
page whose extraction *fails* leaves no trace in the database, though, so
it stays a candidate forever -- and since a sweep walks newest to oldest,
those failures accumulate as a contiguous prefix of every later response.
A driver calling with a fixed `limit` and no offset would therefore stall
outright once enough failures pile up to fill one window, which on a
1700-page corpus that is 59% Granicus -- the platform whose timeouts this
repo already documents as routine -- is a matter of when, not if. Hence `offset` on the endpoint (added with this script)
and `leading_known_failures()` below: each round this re-reads the real
head of the queue with a cheap `dry_run` call and skips only the run of
slugs it already knows are stuck. It measures rather than counts, so a
stuck page that later succeeds (someone loaded it, a CDN came back) just
drops out and the window corrects itself.

Failure detail: the endpoint reports a stored offset or `null` per slug,
not *why* an extraction failed -- that reason (`ffmpeg timed out after
45s`, `Server returned 404`, ...) is logged Archive-side by
`video_thumbnail.extract_and_store()`. This script therefore groups
failures by media host, which is the signal that actually matters at 2am
(one CDN rate-limiting everything is a different problem from scattered
dead links), and points at the Archive logs for the rest.

Usage (from the repo root, with the venv active, ARCHIVE_BASE_URL/
ARCHIVE_INGEST_TOKEN set in .env):

    # read-only: how big is the backlog, which hosts, how long will it take
    python scripts/backfill_meeting_cards.py

    # the real sweep -- resumable, safe to Ctrl-C and re-run
    python scripts/backfill_meeting_cards.py --apply

    # a bounded first taste before committing to the whole thing
    python scripts/backfill_meeting_cards.py --apply --max-batches 3

Dry run is the default, matching the endpoint's own `dry_run=true`
default and this repo's read-only-first posture (see
scripts/backfill_jurisdiction_bleed.py). The token is read from the
environment and only ever placed in an Authorization header -- never
logged, never echoed, per CLAUDE.md.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import aiohttp
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

# Small on purpose. The endpoint's own loop is *sequential* (one
# `await extract_and_store()` per candidate), so a batch costs the sum of
# its pages, not the max: measured during WO-28 that's ~4s for a healthy
# source (3.1s ffprobe + 0.7-0.9s ffmpeg on the real San Carlos mp4) but
# up to 165s for a stubborn one (120s ffprobe timeout + 45s ffmpeg
# timeout). Five keeps a bad batch's worst case inside a timeout a client
# can plausibly hold open; fifty does not.
DEFAULT_BATCH_SIZE = 5
# Between batches, not between items -- the Archive is also serving real
# traffic, and every extraction pulls real bytes off a government CDN.
DEFAULT_SLEEP_SECONDS = 10.0
# Scaled per page rather than fixed, so raising --batch-size doesn't
# silently start abandoning batches the Archive is still working through.
# 180s covers one page's own worst case (165s) with room to spare.
BATCH_TIMEOUT_PER_PAGE_SECONDS = 180
BATCH_TIMEOUT_FLOOR_SECONDS = 60
# The survey/probe calls are one indexed DB query; only a Render cold
# start makes them slow.
PROBE_TIMEOUT_SECONDS = 90
# Ceiling for the opening survey's `limit`. Comfortably above the 1705
# pages the real Archive reported on 2026-08-21, so the backlog this
# prints is a real total rather than a truncated one.
SURVEY_LIMIT = 20000
# Consecutive batch-level (HTTP/network) failures before giving up. A
# single Granicus timeout is routine; three failed *calls* in a row means
# the Archive itself is unhappy and hammering it further is wrong.
MAX_CONSECUTIVE_ERRORS = 3
RETRY_DELAY_SECONDS = 30.0

DEFAULT_STATE_FILE = REPO_ROOT / "scripts" / "meeting_card_backfill_state.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
    force=True,
)
logger = logging.getLogger("rtr_backfill_meeting_cards")


def _base_url() -> str:
    return os.environ.get("ARCHIVE_BASE_URL", "").rstrip("/")


def _headers() -> dict:
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


# --- pure helpers (unit-tested) ------------------------------------------


def media_host(video_url: Optional[str]) -> str:
    """Hostname of a media URL, for grouping. Never raises -- a malformed
    stored video_url is exactly the kind of row this sweep runs into."""
    if not video_url:
        return "(none)"
    try:
        return urlsplit(video_url).hostname or "(unparseable)"
    except ValueError:
        return "(unparseable)"


def host_breakdown(candidates: list[dict]) -> Counter:
    return Counter(media_host(c.get("video_url")) for c in candidates)


def leading_known_failures(candidates: list[dict], failed_slugs) -> int:
    """How many slugs at the head of this window are already known-stuck.

    The whole resume/no-stall mechanism (see the module docstring). Only
    the *leading* run counts: previously-attempted pages form a
    contiguous prefix of the newest-first queue because the sweep walks
    it in that order, so the first slug that isn't a known failure is the
    real frontier -- and anything past it is new work, not something to
    skip over.
    """
    seen = 0
    for candidate in candidates:
        if candidate.get("slug") in failed_slugs:
            seen += 1
        else:
            break
    return seen


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def estimate_remaining(
    *, elapsed_seconds: float, done: int, remaining: int
) -> Optional[str]:
    """ETA from *observed* throughput, not from a guessed per-page cost --
    real extraction time varies by an order of magnitude between a fast
    mp4 and a Granicus source about to time out, so anything else would
    be fiction. None until there's something real to divide by."""
    if done <= 0 or elapsed_seconds <= 0 or remaining <= 0:
        return None
    return format_duration(elapsed_seconds / done * remaining)


# --- resume state --------------------------------------------------------


class State:
    """What survives a Ctrl-C. Deliberately tiny: which slugs are known
    stuck (so a restart doesn't re-probe the same dead sources) plus
    running totals for the closing report. Everything else -- what's left
    to do, where the frontier is -- is re-read from the Archive each run,
    because the Archive is the truth and a stale local cursor is how a
    resumable script silently skips work."""

    VERSION = 1

    def __init__(self, path: Path, base_url: str):
        self.path = path
        self.base_url = base_url
        self.failed: dict[str, dict] = {}
        self.stored_total = 0
        self.attempted_total = 0

    @classmethod
    def load(cls, path: Path, base_url: str) -> "State":
        state = cls(path, base_url)
        if not path.exists():
            return state
        try:
            raw = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Ignoring unreadable state file %s: %s", path, e)
            return state
        if raw.get("version") != cls.VERSION:
            logger.warning("Ignoring state file %s (unknown version).", path)
            return state
        if raw.get("base_url") and raw["base_url"] != base_url:
            # Guard, not paranoia: slugs from a staging Archive would
            # silently mark real production pages as stuck.
            logger.warning(
                "Ignoring state file %s -- it was written against %s, not %s.",
                path,
                raw["base_url"],
                base_url,
            )
            return state
        state.failed = dict(raw.get("failed") or {})
        state.stored_total = int(raw.get("stored_total") or 0)
        state.attempted_total = int(raw.get("attempted_total") or 0)
        return state

    def save(self) -> None:
        payload = {
            "version": self.VERSION,
            "base_url": self.base_url,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "stored_total": self.stored_total,
            "attempted_total": self.attempted_total,
            "failed": self.failed,
        }
        try:
            self.path.write_text(json.dumps(payload, indent=2) + "\n")
        except OSError as e:
            logger.warning("Could not write state file %s: %s", self.path, e)

    def record_failure(self, slug: str, video_url: Optional[str]) -> None:
        entry = self.failed.setdefault(
            slug, {"video_url": video_url, "attempts": 0, "host": media_host(video_url)}
        )
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        entry["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    def record_success(self, slug: str) -> None:
        # A slug that failed on an earlier run and succeeded now must stop
        # being skipped, or the frontier drifts past real work.
        self.failed.pop(slug, None)


# --- HTTP ----------------------------------------------------------------


async def probe(
    session: aiohttp.ClientSession, *, offset: int, limit: int
) -> list[dict]:
    """One read-only look at the queue: which pages sit at [offset,
    offset+limit) right now."""
    async with session.post(
        f"{_base_url()}/internal/thumbnails/backfill",
        params={"limit": str(limit), "offset": str(offset), "dry_run": "true"},
        headers=_headers(),
        timeout=aiohttp.ClientTimeout(total=PROBE_TIMEOUT_SECONDS),
    ) as response:
        body = await response.text()
        if response.status != 200:
            raise RuntimeError(f"probe failed ({response.status}): {body[:300]}")
        return json.loads(body).get("candidates", [])


async def run_batch(session: aiohttp.ClientSession, *, offset: int, limit: int) -> dict:
    """One real batch. Slow by nature -- every item shells out to ffprobe
    and ffmpeg inline before the response comes back."""
    async with session.post(
        f"{_base_url()}/internal/thumbnails/backfill",
        params={"limit": str(limit), "offset": str(offset), "dry_run": "false"},
        headers=_headers(),
        timeout=aiohttp.ClientTimeout(
            total=BATCH_TIMEOUT_FLOOR_SECONDS + limit * BATCH_TIMEOUT_PER_PAGE_SECONDS
        ),
    ) as response:
        body = await response.text()
        if response.status != 200:
            raise RuntimeError(f"backfill failed ({response.status}): {body[:300]}")
        return json.loads(body)


# --- the two modes -------------------------------------------------------


async def survey(
    session: aiohttp.ClientSession, *, batch_size: int, sleep_seconds: float
) -> list[dict]:
    """Read-only: the real backlog, what it's made of, and what a real run
    would cost."""
    logger.info("Surveying %s ...", _base_url())
    candidates = await probe(session, offset=0, limit=SURVEY_LIMIT)
    total = len(candidates)
    logger.info("%s page(s) have an extractable video and no card yet.", total)
    if not total:
        logger.info("Nothing to back-fill. Done.")
        return candidates

    logger.info("By media host:")
    for host, count in host_breakdown(candidates).most_common():
        logger.info("  %6d  %s", count, host)

    logger.info("First few in queue order (newest first):")
    for candidate in candidates[:5]:
        logger.info("  %s", candidate.get("slug"))

    batches = (total + batch_size - 1) // batch_size
    # Bracketed from real measurements rather than one made-up number:
    # WO-28 timed a healthy page at ~4s end to end (3.1s ffprobe + 0.8s
    # ffmpeg on the real San Carlos mp4), and the endpoint's own timeouts
    # cap a stubborn one at 165s. The truth is somewhere between, and only
    # a real run can say where -- which is what the live ETA is for.
    fast = batches * (batch_size * 4 + sleep_seconds)
    slow = batches * (batch_size * 30 + sleep_seconds)
    logger.info(
        "A real run at --batch-size %s is %s batch(es) -- somewhere around "
        "%s if sources behave, %s if a lot of them are slow. Extraction is "
        "sequential Archive-side, one ffprobe plus one ffmpeg per page, so "
        "trust the live ETA this prints after the first few batches over "
        "either of those.",
        batch_size,
        batches,
        format_duration(fast),
        format_duration(slow),
    )
    logger.info("Re-run with --apply to do it for real.")
    return candidates


async def sweep(
    session: aiohttp.ClientSession,
    *,
    batch_size: int,
    sleep_seconds: float,
    max_batches: Optional[int],
    state: State,
) -> int:
    """The real sweep. Returns a process exit code."""
    queued = len(await probe(session, offset=0, limit=SURVEY_LIMIT))
    # "Left to do" means pages nobody has tried yet -- a known-stuck page
    # is still in the queue and always will be, and counting it as
    # pending work would make every ETA a lie.
    remaining = max(0, queued - len(state.failed))
    logger.info(
        "Starting: %s page(s) currently without a card, %s already known stuck "
        "from an earlier run -> ~%s to attempt.",
        queued,
        len(state.failed),
        remaining,
    )

    started = time.monotonic()
    batches_run = 0
    stored_run = 0
    attempted_run = 0
    consecutive_errors = 0
    empty_rounds = 0
    cursor = 0

    try:
        while max_batches is None or batches_run < max_batches:
            # Re-read the head every round rather than trusting a counter:
            # successes leave the queue, new ingests join it at the top,
            # and a previously-stuck page can come back to life. Advance
            # past the run of known-stuck slugs at the front -- cheap (one
            # indexed query per look) and the only thing standing between
            # this script and an infinite loop over the same dead sources.
            previous_head = None
            while True:
                window = await probe(session, offset=cursor, limit=batch_size)
                head = window[0].get("slug") if window else None
                if head is not None and head == previous_head:
                    # Advancing the cursor changed nothing, so the Archive
                    # is ignoring `offset` -- exactly what an Archive
                    # deployed *before* this PR does, since FastAPI
                    # silently drops unknown query params. Continuing
                    # would re-probe the same stuck head forever.
                    logger.error(
                        "The Archive at %s does not honour `offset` on "
                        "/internal/thumbnails/backfill -- it is running a build "
                        "older than WO-37. Nothing has been changed; wait for "
                        "the deploy and re-run.",
                        _base_url(),
                    )
                    return 1
                skip = leading_known_failures(window, state.failed)
                if not skip:
                    break
                previous_head = head
                cursor += skip
            if not window:
                logger.info("Queue exhausted at offset %s.", cursor)
                break

            batches_run += 1
            logger.info(
                "Batch %s: %s page(s) at offset %s -- %s ...",
                batches_run,
                len(window),
                cursor,
                window[0].get("slug"),
            )
            batch_started = time.monotonic()
            try:
                result = await run_batch(
                    session, offset=cursor, limit=min(batch_size, len(window))
                )
            except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as e:
                consecutive_errors += 1
                logger.error(
                    "Batch %s failed at offset %s (%s/%s consecutive): %s",
                    batches_run,
                    cursor,
                    consecutive_errors,
                    MAX_CONSECUTIVE_ERRORS,
                    str(e)[:300],
                )
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.error(
                        "Giving up after %s consecutive batch failures. Nothing "
                        "is lost -- pages already extracted have left the queue; "
                        "re-run the same command to resume from here.",
                        consecutive_errors,
                    )
                    return 1
                # Deliberately no cursor advance: a timed-out batch may
                # well have stored some frames server-side, and whatever
                # it stored has already left the queue.
                await asyncio.sleep(RETRY_DELAY_SECONDS)
                continue

            consecutive_errors = 0
            results = result.get("results", [])
            if not results:
                # Only reachable as a race (every page in the window
                # gained a card between the probe and the call). Counted
                # so it can never become a silent hot loop.
                empty_rounds += 1
                logger.warning(
                    "Batch %s came back empty at offset %s (%s/%s).",
                    batches_run,
                    cursor,
                    empty_rounds,
                    MAX_CONSECUTIVE_ERRORS,
                )
                if empty_rounds >= MAX_CONSECUTIVE_ERRORS:
                    logger.error("Nothing is being attempted -- stopping.")
                    return 1
                await asyncio.sleep(RETRY_DELAY_SECONDS)
                continue
            empty_rounds = 0
            known_urls = {c.get("slug"): c.get("video_url") for c in window}
            stored, failed = [], []
            for item in results:
                slug = item.get("slug")
                video_url = item.get("video_url") or known_urls.get(slug)
                if item.get("offset_seconds") is None:
                    failed.append((slug, video_url))
                    state.record_failure(slug, video_url)
                else:
                    stored.append(slug)
                    state.record_success(slug)

            attempted_run += len(results)
            stored_run += len(stored)
            state.attempted_total += len(results)
            state.stored_total += len(stored)
            state.save()

            batch_seconds = time.monotonic() - batch_started
            logger.info(
                "  attempted %s, stored %s, failed %s in %s",
                len(results),
                len(stored),
                len(failed),
                format_duration(batch_seconds),
            )
            for slug, video_url in failed:
                logger.warning(
                    "  no frame: %s (%s) -- reason is in the Archive's own logs "
                    "(video_thumbnail: 'No card frame for page ...')",
                    slug,
                    media_host(video_url),
                )

            remaining = max(0, remaining - len(results))
            eta = estimate_remaining(
                elapsed_seconds=time.monotonic() - started,
                done=attempted_run,
                remaining=remaining,
            )
            logger.info(
                "  running total: %s stored / %s attempted; ~%s page(s) left%s",
                stored_run,
                attempted_run,
                remaining,
                f", ETA ~{eta}" if eta else "",
            )

            # Failures never leave the queue, so the frontier has to step
            # over the ones this batch just produced.
            cursor += len(failed)
            if sleep_seconds > 0:
                await asyncio.sleep(sleep_seconds)
        else:
            logger.info("Stopped after --max-batches %s.", max_batches)
    except (KeyboardInterrupt, asyncio.CancelledError):
        # Ctrl-C mid-batch is an expected way to run this -- the summary
        # below is the whole point, so it must not be skipped.
        logger.warning("Interrupted.")
    finally:
        state.save()
        _final_report(
            state=state,
            started=started,
            batches_run=batches_run,
            stored_run=stored_run,
            attempted_run=attempted_run,
            cursor=cursor,
        )
    return 0


def _final_report(
    *,
    state: State,
    started: float,
    batches_run: int,
    stored_run: int,
    attempted_run: int,
    cursor: int,
) -> None:
    logger.info("--- run summary ---")
    logger.info(
        "%s batch(es), %s attempted, %s stored, %s failed, %s elapsed.",
        batches_run,
        attempted_run,
        stored_run,
        attempted_run - stored_run,
        format_duration(time.monotonic() - started),
    )
    logger.info(
        "Stopped with the frontier at offset %s. Re-running the same command "
        "resumes from here -- extracted pages have left the queue, and the %s "
        "known-stuck slug(s) in %s are skipped rather than re-probed.",
        cursor,
        len(state.failed),
        state.path,
    )
    if state.failed:
        logger.info("Stuck pages by media host:")
        for host, count in Counter(
            entry.get("host") or "(none)" for entry in state.failed.values()
        ).most_common(10):
            logger.info("  %6d  %s", count, host)
        logger.info(
            "Delete %s to give every stuck page another chance (worth doing "
            "once, days later -- a CDN timeout is often transient).",
            state.path,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually extract frames. Without this the script only surveys "
        "the backlog (read-only), matching the endpoint's own dry_run default.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Pages per request (default {DEFAULT_BATCH_SIZE}). Each one is an "
        "inline ffprobe + ffmpeg against a government CDN, so bigger is not better.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=DEFAULT_SLEEP_SECONDS,
        dest="sleep_seconds",
        help=f"Seconds to pause between batches (default {DEFAULT_SLEEP_SECONDS}).",
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        default=None,
        help="Stop after this many batches (default: run until the queue is "
        "empty). Useful for a bounded first run.",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_STATE_FILE,
        help=f"Where the known-stuck slugs are remembered (default {DEFAULT_STATE_FILE}).",
    )
    parser.add_argument(
        "--reset-state",
        action="store_true",
        help="Forget previously-stuck pages and retry every one of them.",
    )
    return parser


async def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if not _base_url():
        logger.error("ARCHIVE_BASE_URL is not set (check the repo's .env). Stopping.")
        return 1
    if not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        logger.error(
            "ARCHIVE_INGEST_TOKEN is not set (check the repo's .env). Stopping."
        )
        return 1
    if args.batch_size < 1:
        logger.error("--batch-size must be at least 1.")
        return 1

    if args.reset_state and args.state_file.exists():
        args.state_file.unlink()
        logger.info(
            "Cleared %s -- every previously-stuck page gets another try.",
            args.state_file,
        )

    async with aiohttp.ClientSession() as session:
        if not args.apply:
            await survey(
                session,
                batch_size=args.batch_size,
                sleep_seconds=args.sleep_seconds,
            )
            return 0
        state = State.load(args.state_file, _base_url())
        return await sweep(
            session,
            batch_size=args.batch_size,
            sleep_seconds=args.sleep_seconds,
            max_batches=args.max_batches,
            state=state,
        )


if __name__ == "__main__":
    # Deliberately not called at module level -- same reasoning as
    # scripts/send_search_alerts.py's matching comment.
    load_dotenv()
    sys.exit(asyncio.run(main()))
