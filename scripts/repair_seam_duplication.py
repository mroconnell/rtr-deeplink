"""Finds and repairs the already-live seam-duplication defect in stored
multi-chunk transcription segments -- see BACKLOG.md's "[JUST-DO-IT]
`[BIG]` Repair the three already-live transcript-defect populations"
entry, step 1 (the seam-duplication population specifically; repetition
loops and the two confirmed-hallucination re-transcribes are separate,
still-open work -- see that entry).

Why this exists. `worker/segment_utils.py`'s `count_seam_overlap_
segments()` (live since 2026-08-16, see BACKLOG_DONE.md) stops a NEW
multi-chunk transcription from restating a chunk's last sentence at the
start of the next chunk -- an HLS seek-accuracy artifact, not a
transcription error (see that function's own module comment for the
full root cause). It is prevention only: every page transcribed BEFORE
that fix shipped already has the duplicated segments baked into its
stored default TranscriptVersion, and `GET /internal/transcription/
completed-multichunk` audited that population at **118 completed jobs**
(job_id 1-192, completed 2026-08-08 through 2026-08-16). Ryan's explicit
call, 2026-08-22 (BACKLOG.md): repair the stored segments directly
rather than bulk re-transcribing -- the individual chunks were correct,
only the join was wrong, so everything needed to fix it is already
there. Re-running Whisper on ~190 meetings would cost 500+ hours of
audio to reproduce output that would be mostly identical to what's
already stored.

--------------------------------------------------------------------------
HOW A SEAM IS RE-FOUND WITHOUT THE ORIGINAL PER-CHUNK DATA
--------------------------------------------------------------------------
The worker never persists individual chunks separately -- only the
running merged `TranscriptionJob.partial_segments` (see that model's own
docstring), and by completion that's exactly the flat, already-duplicated
list this script has to work with. But chunking is fixed-size and the
job record keeps both numbers needed to reconstruct where each seam
fell: `total_chunks` and `chunk_size_seconds`. `worker/segment_utils.
chunk_start(i, chunk_size_seconds)` gives seam i's approximate
meeting-relative timestamp for i in 1..total_chunks-1, and this script
locates the stored segments immediately before/after that timestamp and
hands them to `count_seam_overlap_segments()` -- the exact same,
already-tested detector the live prevention path uses, just fed a
windowed slice of one flat list instead of two separate chunk results.
Nothing about the detection logic itself is new or reimplemented.

--------------------------------------------------------------------------
CANDIDATE SELECTION AND READS -- no SQL, no source fetch
--------------------------------------------------------------------------
1. `GET /internal/transcription/completed-multichunk` -- the existing
   audit endpoint, one query, no segments touched.
2. Per candidate, `GET /m/{slug}/transcript.srt` -- the page's own public
   export, parsed back by `parse_stored_srt()` (imported from
   scripts/dedupe_rollup_transcripts.py -- same reasoning as that
   script's own docstring: no re-normalization, what the export says is
   what the row holds).
3. Seam-by-seam windowed detection, in memory, against the fetched
   segments. No compute, no re-transcription, no source fetch -- this
   never contacts a government website at all, only this repo's own
   Archive.

--------------------------------------------------------------------------
APPLY -- always from a human-reviewed report, never a fresh scan
--------------------------------------------------------------------------
`--apply` requires `--from-report`, matching scripts/dedupe_rollup_
transcripts.py's own convention: the report file a human actually looked
at is the list that gets applied, not whatever a fresh scan happens to
find at apply time (the page population, chunking, and defects could all
have moved since the dry run). Each application POSTs to `/internal/
transcript-version/repair-seam-duplication` with a fresh sha256 of the
CURRENT `/m/{slug}/transcript.srt` body as `expected_srt_hash` --
optimistic concurrency computed at apply time, not carried over from the
report, so anything that changed the page since the dry run (a
re-transcription, another repair run, a manual promote) causes a clean
409 refusal rather than a silent corruption. See crud.
create_seam_repair_version()'s own docstring for the full reasoning.
Nothing is ever deleted -- the repaired page gets a new TranscriptVersion
and the old one stays reachable via `?version=`, same as every other
transcript-editing tool in this repo.

Usage (from the repo root, with the venv active):
    python scripts/repair_seam_duplication.py --dry-run
    python scripts/repair_seam_duplication.py --dry-run --limit 5
    python scripts/repair_seam_duplication.py --dry-run --slug some-slug

    # the real run: repair exactly the pages the dry-run report flagged.
    python scripts/repair_seam_duplication.py --apply \\
        --from-report scripts/seam_duplication_report.json

Dry run is the default, matching this repo's read-only-first posture
(scripts/backfill_archived_pages.py, scripts/dedupe_rollup_transcripts.py).

The token is read from the environment and only ever placed in an
Authorization header -- never logged, never echoed, per CLAUDE.md.
"""

import argparse
import asyncio
import bisect
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import certifi

# Same reasoning as scripts/transcribe_backlog_locally.py's own fix
# (CLAUDE.md): a fresh Homebrew-Python venv has an empty default SSL
# trust store, and aiohttp/connector.py builds its default SSLContext at
# `import aiohttp` time, not lazily -- so this has to run before that
# import, not just before this script's first network call.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.utils.rate_limit import looks_rate_limited  # noqa: E402
from scripts.dedupe_rollup_transcripts import parse_stored_srt  # noqa: E402
from worker.segment_utils import chunk_start, count_seam_overlap_segments  # noqa: E402

# How many segments on either side of a seam are candidates for overlap --
# matches count_seam_overlap_segments()'s own _LOOKBACK_SEGMENTS, so the
# windows handed to it here are the same size its live caller would give
# it (a smaller window here would just silently make some real overlaps
# unreachable; a larger one is wasted work, since the function itself
# never looks further than its own constant).
LOOKBACK_SEGMENTS = 8

DEFAULT_PROBE_DELAY_SECONDS = 0.25
DEFAULT_APPLY_DELAY_SECONDS = 1.0
PROBE_TIMEOUT = aiohttp.ClientTimeout(total=60)
LIST_TIMEOUT = aiohttp.ClientTimeout(total=60)
APPLY_TIMEOUT = aiohttp.ClientTimeout(total=60)

# Same hair-trigger-on-rate-limit, else-consecutive-count circuit breaker
# as scripts/dedupe_rollup_transcripts.py's _should_abort() -- see that
# function's own comment for why the rate-limit check can't wait for the
# threshold.
MAX_CONSECUTIVE_FAILURES = 5

DEFAULT_REPORT_FILE = REPO_ROOT / "scripts" / "seam_duplication_report.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
    force=True,
)
logger = logging.getLogger("rtr_repair_seam_duplication")


def _base_url() -> str:
    return os.environ.get("ARCHIVE_BASE_URL", "").rstrip("/")


def _headers() -> dict:
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


async def list_multichunk_candidates(session: aiohttp.ClientSession) -> list[dict]:
    async with session.get(
        f"{_base_url()}/internal/transcription/completed-multichunk",
        headers=_headers(),
        timeout=LIST_TIMEOUT,
    ) as response:
        if response.status != 200:
            raise RuntimeError(f"candidate list fetch failed ({response.status})")
        data = await response.json()
        return data.get("jobs", [])


async def fetch_stored_srt(
    session: aiohttp.ClientSession, slug: str
) -> Optional[tuple[str, list[dict]]]:
    """(raw SRT body, parsed segments), or None if the page has no
    transcript at all (404) -- not a failure, just nothing to check.
    Returns the raw body too because that's what expected_srt_hash is
    computed from, not a re-serialization of the parsed segments (see
    crud.create_seam_repair_version()'s own docstring for why those two
    must not be conflated)."""
    async with session.get(
        f"{_base_url()}/m/{slug}/transcript.srt", timeout=PROBE_TIMEOUT
    ) as response:
        if response.status == 404:
            return None
        if response.status != 200:
            raise RuntimeError(
                f"transcript probe for {slug} failed ({response.status})"
            )
        body = await response.text()
        return body, parse_stored_srt(body)


# How far (in segment count) either side of the estimated boundary index
# to also try as the prev/new split point -- see find_seam_duplicates()'s
# own comment for why the naive "first segment at/after the boundary
# timestamp" split isn't reliable on its own: a chunk's own transcription
# can produce a segment starting right at (or a hair past) the nominal
# boundary, which is exactly what the real, confirmed Boulder County case
# does (tests/test_worker_segment_utils.py's
# test_count_seam_overlap_detects_real_production_duplicate -- its
# "Um, there's an exhibit at the." segment starts at exactly the 900s
# boundary and belongs on the PREVIOUS chunk's side, not the new one).
SPLIT_SEARCH_RADIUS = 2


def find_seam_duplicates(
    segments: list[dict], *, total_chunks: int, chunk_size_seconds: int
) -> list[dict]:
    """Every seam (1..total_chunks-1) where the stored segments show a
    real, confirmed near-duplicate restatement -- each finding names the
    exact segment indices (into `segments`, 0-based) that
    count_seam_overlap_segments() says to drop. Segments are assumed
    sorted by `start`, same invariant TranscriptVersion.segments already
    carries (workers always append/merge in order).

    For each seam, tries a small neighborhood of candidate split points
    around the estimated boundary index and keeps whichever split
    produces the LARGEST confirmed overlap (0 if none clear the
    detector's own threshold) -- see SPLIT_SEARCH_RADIUS's comment for
    why a single rigid split isn't safe to trust here. This is a handful
    of cheap, pure-Python calls per seam, not a new detector: every
    candidate still goes through the exact same, already-tested
    count_seam_overlap_segments().
    """
    if total_chunks < 2 or not segments:
        return []

    starts = [seg["start"] for seg in segments]
    findings = []
    for seam_index in range(1, total_chunks):
        boundary = chunk_start(seam_index, chunk_size_seconds)
        estimate = bisect.bisect_left(starts, boundary)

        # Neither window may reach past the ADJACENT seam's own boundary
        # -- otherwise, on a page whose segments are sparse enough that
        # fewer than LOOKBACK_SEGMENTS fall between two consecutive
        # seams, this seam's window would swallow the previous or next
        # seam's unrelated content too, and a real duplicate found there
        # could make count_seam_overlap_segments() over-drop into content
        # that has nothing to do with THIS seam. Confirmed by a synthetic
        # regression case in tests/test_repair_seam_duplication.py --
        # without this bound it drops ordinary speech from a full
        # 900-second chunk earlier for a duplicate that only touches the
        # boundary two chunks later.
        prev_floor = (
            chunk_start(seam_index - 1, chunk_size_seconds) if seam_index > 1 else None
        )
        next_ceiling = (
            chunk_start(seam_index + 1, chunk_size_seconds)
            if seam_index < total_chunks - 1
            else None
        )

        best_drop = 0
        best_split = None
        lo = max(1, estimate - SPLIT_SEARCH_RADIUS)
        hi = min(len(segments), estimate + SPLIT_SEARCH_RADIUS + 1)
        for split in range(lo, hi):
            prev_window = segments[max(0, split - LOOKBACK_SEGMENTS) : split]
            new_window = segments[split : split + LOOKBACK_SEGMENTS]
            if prev_floor is not None:
                prev_window = [s for s in prev_window if s["start"] >= prev_floor]
            if next_ceiling is not None:
                new_window = [s for s in new_window if s["start"] < next_ceiling]
            drop = count_seam_overlap_segments(prev_window, new_window)
            if drop > best_drop:
                best_drop = drop
                best_split = split

        if not best_drop:
            continue

        drop_start = best_split - best_drop
        dropped = segments[drop_start:best_split]
        findings.append(
            {
                "seam_index": seam_index,
                "boundary_seconds": boundary,
                "drop_segment_indices": list(range(drop_start, best_split)),
                "dropped_text": " / ".join(seg["text"] for seg in dropped),
            }
        )
    return findings


async def scan(
    session: aiohttp.ClientSession, *, limit: Optional[int], only_slugs: list[str]
) -> list[dict]:
    candidates = await list_multichunk_candidates(session)
    if only_slugs:
        wanted = set(only_slugs)
        candidates = [c for c in candidates if c["slug"] in wanted]
    if limit:
        candidates = candidates[:limit]

    logger.info("Scanning %d candidate job(s) for seam duplication...", len(candidates))

    reports = []
    for index, job in enumerate(candidates, 1):
        slug = job["slug"]
        try:
            fetched = await fetch_stored_srt(session, slug)
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as e:
            logger.warning(
                "[%d/%d] %s: probe failed -- %s", index, len(candidates), slug, e
            )
            continue

        if fetched is None:
            logger.info(
                "[%d/%d] %s: no transcript, skipped", index, len(candidates), slug
            )
            continue

        srt_body, segments = fetched
        findings = find_seam_duplicates(
            segments,
            total_chunks=job["total_chunks"],
            chunk_size_seconds=job["chunk_size_seconds"],
        )
        if findings:
            srt_hash = hashlib.sha256(srt_body.encode("utf-8")).hexdigest()
            logger.info(
                "[%d/%d] %s: %d seam(s) with duplicated segments",
                index,
                len(candidates),
                slug,
                len(findings),
            )
            for f in findings:
                logger.info(
                    "    seam %d @ %.0fs: drop %d segment(s) -- %r",
                    f["seam_index"],
                    f["boundary_seconds"],
                    len(f["drop_segment_indices"]),
                    f["dropped_text"][:200],
                )
            reports.append(
                {
                    "job_id": job["job_id"],
                    "slug": slug,
                    "title": job.get("title"),
                    "total_chunks": job["total_chunks"],
                    "expected_srt_hash": srt_hash,
                    "findings": findings,
                }
            )
        else:
            logger.info(
                "[%d/%d] %s: clean, no seam duplication found",
                index,
                len(candidates),
                slug,
            )

    return reports


async def apply_repairs(
    session: aiohttp.ClientSession, reports: list[dict], *, delay: float
) -> int:
    """Applies exactly the pages in `reports` (a human-reviewed dry-run
    report, see --from-report). Re-fetches and re-hashes each page
    immediately before writing -- see module docstring's "APPLY" section
    for why the report's own expected_srt_hash isn't reused directly."""
    applied = failed = 0
    consecutive_failures = 0

    for index, entry in enumerate(reports, 1):
        slug = entry["slug"]
        drop_indices = sorted(
            {i for f in entry["findings"] for i in f["drop_segment_indices"]}
        )

        try:
            fetched = await fetch_stored_srt(session, slug)
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as e:
            failed += 1
            consecutive_failures += 1
            logger.error(
                "[%d/%d] %s: re-probe failed -- %s", index, len(reports), slug, e
            )
            if (
                looks_rate_limited(str(e))
                or consecutive_failures >= MAX_CONSECUTIVE_FAILURES
            ):
                logger.error("Stopping -- re-run the same command to resume.")
                return 1
            continue

        if fetched is None:
            failed += 1
            logger.warning(
                "[%d/%d] %s: page now has no transcript at all, skipped",
                index,
                len(reports),
                slug,
            )
            continue

        srt_body, _segments = fetched
        fresh_hash = hashlib.sha256(srt_body.encode("utf-8")).hexdigest()

        try:
            async with session.post(
                f"{_base_url()}/internal/transcript-version/repair-seam-duplication",
                json={
                    "slug": slug,
                    "expected_srt_hash": fresh_hash,
                    "drop_segment_indices": drop_indices,
                },
                headers=_headers(),
                timeout=APPLY_TIMEOUT,
            ) as response:
                body = await response.json()
                if response.status == 200:
                    consecutive_failures = 0
                    applied += 1
                    logger.info(
                        "[%d/%d] %s: repaired -- version %s (%d dropped, %d kept)",
                        index,
                        len(reports),
                        slug,
                        body["version_id"],
                        body["dropped"],
                        body["kept"],
                    )
                elif response.status == 409:
                    failed += 1
                    logger.warning(
                        "[%d/%d] %s: stale (%s) -- re-scan and retry",
                        index,
                        len(reports),
                        slug,
                        body.get("message"),
                    )
                else:
                    failed += 1
                    consecutive_failures += 1
                    logger.error(
                        "[%d/%d] %s: apply failed (%s): %s",
                        index,
                        len(reports),
                        slug,
                        response.status,
                        body,
                    )
                    if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                        logger.error("Stopping -- re-run the same command to resume.")
                        return 1
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            failed += 1
            consecutive_failures += 1
            logger.error(
                "[%d/%d] %s: apply request failed -- %s", index, len(reports), slug, e
            )
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                logger.error("Stopping -- re-run the same command to resume.")
                return 1

        if delay > 0 and index < len(reports):
            await asyncio.sleep(delay)

    logger.info("Done. %d repaired, %d failed/skipped.", applied, failed)
    return 0 if failed == 0 else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually repair the pages in --from-report. Without this the "
        "script only scans and reports (read-only).",
    )
    parser.add_argument(
        "--slug",
        action="append",
        default=[],
        dest="slugs",
        help="Scan only this page (repeatable). Useful for spot-checking one "
        "job_id's slug from a prior report.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Scan at most this many candidates.",
    )
    parser.add_argument(
        "--report-file",
        type=Path,
        default=DEFAULT_REPORT_FILE,
        help=f"Where the dry run writes its findings (default {DEFAULT_REPORT_FILE}).",
    )
    parser.add_argument(
        "--from-report",
        type=Path,
        default=None,
        help="With --apply: repair exactly the pages in this report file "
        "(required for --apply) -- the list a human actually reviewed, not "
        "a fresh scan.",
    )
    parser.add_argument(
        "--apply-delay",
        type=float,
        default=DEFAULT_APPLY_DELAY_SECONDS,
        dest="apply_delay",
        help=f"Seconds between repairs during --apply (default "
        f"{DEFAULT_APPLY_DELAY_SECONDS}). These hit our own Archive, not a "
        "government website, so this is much smaller than a resolve delay.",
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

    if args.apply and not args.from_report:
        logger.error(
            "--apply requires --from-report <file> -- repair exactly the "
            "pages a human reviewed, not a fresh scan. Run a dry run first."
        )
        return 1

    async with aiohttp.ClientSession() as session:
        if args.apply:
            reports = json.loads(args.from_report.read_text())
            return await apply_repairs(session, reports, delay=args.apply_delay)

        reports = await scan(session, limit=args.limit, only_slugs=args.slugs)
        args.report_file.write_text(json.dumps(reports, indent=2))
        logger.info(
            "\n%d page(s) with confirmed seam duplication. Report written to %s.",
            len(reports),
            args.report_file,
        )
        return 0


if __name__ == "__main__":
    # Deliberately not called at module level -- same reasoning as this
    # repo's other CLI scripts.
    load_dotenv()
    sys.exit(asyncio.run(main()))
