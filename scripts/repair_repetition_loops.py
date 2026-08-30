"""Finds and repairs the already-live repetition-loop defect in stored
Whisper-transcribed segments -- see BACKLOG.md's "[JUST-DO-IT] `[BIG]`
Repair the three already-live transcript-defect populations" entry,
step 1b (the repetition-loop population; scripts/repair_seam_
duplication.py is the sibling script for step 1, the seam-duplication
population -- see that entry, and that script's own module docstring
for the shared `/internal/transcript-version/drop-segments` write path
both scripts use).

Why this exists. WO-36's `detect_hallucination_warnings()` (`worker/
segment_utils.py` / `archive/utils/transcription_quality.py`) catches a
Whisper transcript that degenerates into a repeated cue over silence,
music, or a recess -- confirmed real on 6 live pages, and on 74 of 304
(24%) real `source=="transcribed"` transcripts audited when this was
measured (see BACKLOG_DONE.md). But that function only *flags* a
transcript; nothing collapses the repeated cues themselves in stored
segments, so a reader still sees the actual repeated garbage text, just
with a warning banner above it. Ryan's 2026-08-22 decision (BACKLOG.md):
repair stored segments directly rather than re-running Whisper on the
same audio -- a loop comes from the audio itself (silence/music/recess),
so re-transcribing the same audio reproduces the same loop.

--------------------------------------------------------------------------
THE COLLAPSE DESIGN -- keep the first cue, drop the rest, touch nothing else
--------------------------------------------------------------------------
For each run WO-36's own detector would flag (see find_repetition_loops()
below -- it reuses that detector's exact rules, not a new one), this
script keeps the run's FIRST segment and drops every other segment in
the run. Two deliberate choices, made explicit here because they're real
design decisions, not something to leave implicit:

1. **Keep one representative cue, not zero.** A completely empty gap
   would look like a transcription failure; one cue marks that
   *something* (however degenerate) sat in this span, honestly.
2. **Never shift surrounding timestamps.** The dropped segments' own
   time span reverts to unlabeled silence -- which is what it almost
   always factually was (see the module docstring above: loops come
   from silence, music, or a recess). Shifting every later segment to
   close the gap would touch far more of the transcript than the defect
   itself, for no real benefit to a reader following along by timestamp.

--------------------------------------------------------------------------
CANDIDATE SELECTION AND READS -- no SQL, no source fetch, no compute
--------------------------------------------------------------------------
1. `GET /internal/transcription/hallucination-candidates` (paginated via
   `after_id`, same keyset shape as the endpoint's own docstring) --
   the existing WO-36 retroactive audit, already re-running
   detect_hallucination_warnings() against stored segments server-side.
   Filtered here to `is_default` rows only: a non-default version isn't
   shown to any reader and isn't reachable by this script's apply step
   either (create_segment_drop_version() always targets the current
   default).
2. Per candidate, `GET /m/{slug}/transcript.srt` -- the page's own
   public export, parsed back by `parse_stored_srt()` (imported from
   scripts/dedupe_rollup_transcripts.py, same reasoning as that script's
   own docstring and scripts/repair_seam_duplication.py's).
3. In-memory run detection against the fetched segments. Never contacts
   a government website, never re-transcribes.

--------------------------------------------------------------------------
APPLY -- always from a human-reviewed report, never a fresh scan
--------------------------------------------------------------------------
Same convention as scripts/repair_seam_duplication.py and scripts/
dedupe_rollup_transcripts.py before it: `--apply` requires
`--from-report`, and every write re-fetches and re-hashes the page
immediately before writing, refusing on a stale `expected_srt_hash`
(computed from the raw `/m/{slug}/transcript.srt` body, see
crud.create_segment_drop_version()'s own docstring) rather than risking
a silent overwrite of a page that changed since the dry run. Nothing is
ever deleted -- the old version stays reachable via `?version=`.

Usage (from the repo root, with the venv active):
    python scripts/repair_repetition_loops.py --dry-run
    python scripts/repair_repetition_loops.py --dry-run --limit 5
    python scripts/repair_repetition_loops.py --dry-run --slug some-slug

    # the real run: repair exactly the pages the dry-run report flagged.
    python scripts/repair_repetition_loops.py --apply \\
        --from-report scripts/repetition_loop_report.json

Dry run is the default, matching this repo's read-only-first posture.

The token is read from the environment and only ever placed in an
Authorization header -- never logged, never echoed, per CLAUDE.md.
"""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import certifi

# Same reasoning as scripts/repair_seam_duplication.py's own fix
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
from worker.segment_utils import (  # noqa: E402
    _HALLUCINATION_ABSOLUTE_RUN_LENGTH,
    _HALLUCINATION_TILED_COVERAGE_RATIO,
    _HALLUCINATION_TILED_MIN_SECONDS,
    _HALLUCINATION_TILED_RUN_LENGTH,
    _repetition_runs,
    _run_span_and_coverage,
)

CANDIDATE_PAGE_SIZE = 500
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

DEFAULT_REPORT_FILE = REPO_ROOT / "scripts" / "repetition_loop_report.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
    force=True,
)
logger = logging.getLogger("rtr_repair_repetition_loops")


def _base_url() -> str:
    return os.environ.get("ARCHIVE_BASE_URL", "").rstrip("/")


def _headers() -> dict:
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


async def list_hallucination_candidates(session: aiohttp.ClientSession) -> list[dict]:
    """Every page through the existing WO-36 audit endpoint, keyset-paged
    by version_id (same shape its own docstring describes) -- default
    versions only, see this script's own module docstring for why."""
    all_candidates: list[dict] = []
    after_id = None
    while True:
        params = {"limit": str(CANDIDATE_PAGE_SIZE)}
        if after_id is not None:
            params["after_id"] = str(after_id)
        async with session.get(
            f"{_base_url()}/internal/transcription/hallucination-candidates",
            params=params,
            headers=_headers(),
            timeout=LIST_TIMEOUT,
        ) as response:
            if response.status != 200:
                raise RuntimeError(f"candidate list fetch failed ({response.status})")
            data = await response.json()
        batch = data.get("candidates", [])
        all_candidates.extend(batch)
        if len(batch) < CANDIDATE_PAGE_SIZE:
            break
        after_id = batch[-1]["version_id"]
    return [c for c in all_candidates if c.get("is_default")]


async def fetch_stored_srt(
    session: aiohttp.ClientSession, slug: str
) -> Optional[tuple[str, list[dict]]]:
    """(raw SRT body, parsed segments), or None if the page has no
    transcript at all (404). Returns the raw body too because that's
    what expected_srt_hash is computed from, not a re-serialization of
    the parsed segments (see crud.create_segment_drop_version()'s own
    docstring for why those two must not be conflated)."""
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


def find_repetition_loops(segments: list[dict]) -> list[dict]:
    """Every run of consecutive near-duplicate segments that WO-36's own
    detector would flag -- same two rules `_has_hallucinated_repetition_
    run()` (worker/segment_utils.py) uses, applied per-run here instead
    of short-circuiting on the first qualifying run in the transcript,
    so a page with more than one loop gets all of them. Each finding's
    `drop_segment_indices` is every index in the run EXCEPT the first --
    see this module's own docstring for why the first cue is kept and
    why nothing else in the transcript is touched.
    """
    findings = []
    for start, length in _repetition_runs(segments):
        qualifies = False
        if length >= _HALLUCINATION_ABSOLUTE_RUN_LENGTH:
            qualifies = True
        elif length >= _HALLUCINATION_TILED_RUN_LENGTH:
            span, coverage = _run_span_and_coverage(segments[start : start + length])
            qualifies = (
                span >= _HALLUCINATION_TILED_MIN_SECONDS
                and coverage >= _HALLUCINATION_TILED_COVERAGE_RATIO
            )
        if not qualifies:
            continue

        run = segments[start : start + length]
        drop_indices = list(range(start + 1, start + length))
        findings.append(
            {
                "run_start_index": start,
                "run_length": length,
                "kept_segment_index": start,
                "drop_segment_indices": drop_indices,
                "sample_text": run[0]["text"][:200],
                "run_start_seconds": run[0]["start"],
                "run_end_seconds": run[-1]["end"],
            }
        )
    return findings


async def scan(
    session: aiohttp.ClientSession, *, limit: Optional[int], only_slugs: list[str]
) -> list[dict]:
    candidates = await list_hallucination_candidates(session)
    if only_slugs:
        wanted = set(only_slugs)
        candidates = [c for c in candidates if c["slug"] in wanted]
    if limit:
        candidates = candidates[:limit]

    logger.info(
        "Scanning %d default-version candidate(s) for repetition loops...",
        len(candidates),
    )

    reports = []
    for index, candidate in enumerate(candidates, 1):
        slug = candidate["slug"]
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
        findings = find_repetition_loops(segments)
        if findings:
            srt_hash = hashlib.sha256(srt_body.encode("utf-8")).hexdigest()
            logger.info(
                "[%d/%d] %s: %d loop(s) found",
                index,
                len(candidates),
                slug,
                len(findings),
            )
            for f in findings:
                logger.info(
                    "    run @ %.0f-%.0fs: keep 1, drop %d segment(s) -- %r",
                    f["run_start_seconds"],
                    f["run_end_seconds"],
                    len(f["drop_segment_indices"]),
                    f["sample_text"],
                )
            reports.append(
                {
                    "version_id": candidate["version_id"],
                    "slug": slug,
                    "title": candidate.get("title"),
                    "already_flagged": candidate.get("already_flagged"),
                    "expected_srt_hash": srt_hash,
                    "findings": findings,
                }
            )
        else:
            logger.info(
                "[%d/%d] %s: clean, no repetition loop found",
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
                f"{_base_url()}/internal/transcript-version/drop-segments",
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
        help="Scan only this page (repeatable).",
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
            "\n%d page(s) with confirmed repetition loops. Report written to %s.",
            len(reports),
            args.report_file,
        )
        return 0


if __name__ == "__main__":
    # Deliberately not called at module level -- same reasoning as this
    # repo's other CLI scripts.
    load_dotenv()
    sys.exit(asyncio.run(main()))
