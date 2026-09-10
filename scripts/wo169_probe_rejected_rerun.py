"""WO-169: re-run the 16 governments that WO-145/147/150/151 dropped
because a WO-144 probe reject ended their whole attempt at the first
tier-3 candidate, instead of moving on to the next one (Ryan's
2026-09-10 rule -- see this repo's CLAUDE.md and BACKLOG_DONE.md's own
WO-169 entry for the full writeup).

The 16 governments (rtr-business/research/wo169_rerun_candidates.csv,
built from wo145_report.csv/wo147_report.csv/wo150_report.csv/
wo151_report.csv's own `outcome=rejected_by_probe`/probe-reject notes --
see that CSV's own header comment for exactly how each row's meeting_url/
video_url was recovered, including the two wo147 rows whose
wo147_report.csv values were blanked by a second, separate occurrence of
this same URL-dropping bug, fixed in scripts/wo147_finish_tier3_queue.py
in the same PR as this script) are re-run through the SAME shared
pipeline every other sweep uses --
scripts/wo134_confirmed_hits_ingest.py's `process_row()` -- now with
three fixes landed in this WO:

1. `wo134.PROBE_HOOK` (set below to a real WO-144 probe, wired to the
   same append-only sidecar every other probe caller uses) makes
   `resolve_seed()`'s own candidate loops probe a tier-3 candidate BEFORE
   accepting it, trying the next one on a reject instead of giving up --
   see PROBE_HOOK's own comment in wo134_confirmed_hits_ingest.py.
2. `RowSkip`/`RowResult` now carry `meeting_url`/`video_url` even on a
   skip, so this script's own wo169_report.csv never drops them the way
   the original sweeps' reports did.
3. Granicus listing now tries the cheap RSS video feed before the (up to
   8 MB) ViewPublisher.php archive table -- relevant here since 2 of the
   16 governments (Guadalupe County TX, Beltrami city MN) are Granicus.

Because probing now happens INSIDE resolve_seed() before a candidate is
ever accepted, this script does NOT set TIER3_HANDLER at all -- a
tier-3 result process_row() returns has already passed the probe, so it
goes straight to the real queue file + pin, exactly like a first-time
sweep hit would.

Rules from CLAUDE.md/docs/BREADTH_SWEEP_BRIEF.md, same as every other
sweep: video-only ingest (Ryan's standing rule -- process_row() already
enforces this), probe before queue (PROBE_HOOK, see above), pins on
shared hosts (process_row()'s own maybe_write_tenant_override(), already
wired), one government at a time with a real delay between them, stop
after 6 consecutive real (non-content) errors, HTTP only -- no headless
browsing, so a human-verification gate is never approached.

Usage (repo root, DATABASE_URL set per CLAUDE.md's worktree warning even
though this script never touches the DB directly):
    python scripts/export_meeting_inventory.py --out-dir /tmp/wo169_inventory --source export
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo169_scratch.db" \\
        python scripts/wo169_probe_rejected_rerun.py

Writes rtr-business/research/wo169_report.csv, one row per government,
resumable (a gov_id already logged there is skipped on re-run).
"""

import asyncio
import csv
import os
import sys
from pathlib import Path
from typing import Dict

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.queue_probe import (  # noqa: E402
    DEFAULT_SIDECAR_PATH,
    append_probe_row,
    probe_queue_entry,
)

import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402

RESEARCH_DIR = Path("/Users/mroconnell/Documents/rtr-business/research")
CANDIDATES_CSV = RESEARCH_DIR / "wo169_rerun_candidates.csv"
REPORT_CSV = RESEARCH_DIR / "wo169_report.csv"
DEFAULT_INVENTORY_CSV = Path("/tmp/wo169_inventory/meeting_inventory.csv")

# Stricter than wo134's own default (1.5s) -- this WO's own politeness
# rule is "2s between requests to one host," and every one of these 16
# governments is on a different host, so a flat 2s between governments
# satisfies both rules at once with no per-host bookkeeping needed.
REQUEST_DELAY_SECONDS = 2.0
MAX_CONSECUTIVE_ERRORS = 6

REPORT_FIELDS = [
    "gov_id",
    "unit_name",
    "state",
    "source_sweep",
    "platform",
    "outcome",
    "reason",
    "seed_url",
    "video_url",
    "title",
    "date",
    "page_url",
    "original_reject_note",
]


async def _real_probe_hook(result, candidate_url: str) -> bool:
    """The real WO-144 probe, wired to wo134.PROBE_HOOK below so
    resolve_seed()'s own candidate loops probe before accepting a tier-3
    candidate -- see that hook's own comment in
    wo134_confirmed_hits_ingest.py. Logs to the same append-only sidecar
    (tier3_auto_transcription_queue_probe.csv) every other probe caller
    in this repo already writes to."""
    probe = await probe_queue_entry(
        candidate_url,
        video_url=result.video_url,
        source_page_url=result.source_url or candidate_url,
    )
    append_probe_row(DEFAULT_SIDECAR_PATH, probe)
    return probe.verdict not in ("reject-dead", "reject-short")


def _already_logged_gov_ids(path: Path) -> set:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {row["gov_id"] for row in csv.DictReader(f) if row.get("gov_id")}


def _log_writer(path: Path):
    is_new = not path.exists()
    f = path.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=REPORT_FIELDS, lineterminator="\n")
    if is_new:
        writer.writeheader()
        f.flush()
    return f, writer


async def main() -> None:
    if not wo134._base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (check .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    if not CANDIDATES_CSV.exists():
        print(f"ERROR: {CANDIDATES_CSV} not found.", file=sys.stderr)
        sys.exit(1)

    register_all_finders()
    covered_gov_ids = wo134._load_covered_gov_ids(DEFAULT_INVENTORY_CSV)
    print(f"{len(covered_gov_ids)} gov_ids already have an archived page.")

    with CANDIDATES_CSV.open(newline="", encoding="utf-8") as f:
        candidates = list(csv.DictReader(f))
    print(f"{len(candidates)} probe-rejected government(s) to re-run.")

    already_done = _already_logged_gov_ids(REPORT_CSV)
    todo = [c for c in candidates if c["gov_id"] not in already_done]
    print(f"{len(already_done)} already logged from a prior run -- {len(todo)} left.")

    # Probing happens INSIDE resolve_seed()'s own candidate loops now --
    # see this module's own docstring for why TIER3_HANDLER is
    # deliberately left unset (None, its default) for this script.
    wo134.PROBE_HOOK = _real_probe_hook

    log_f, log_writer = _log_writer(REPORT_CSV)
    tally: Dict[str, int] = {}
    consecutive_errors = 0
    try:
        async with aiohttp.ClientSession() as session:
            for i, cand in enumerate(todo):
                row = {
                    "gov_id": cand["gov_id"],
                    "unit_name": f"{cand['unit_name']}, {cand['state']}",
                    "homepage": cand.get("homepage") or "",
                    "hop2_urls": cand.get("hop2_urls") or "",
                    "hit_source_urls": cand["hit_source_urls"],
                }
                try:
                    result = await wo134.process_row(
                        session, row, covered_gov_ids, "wo169_probe_rejected_rerun"
                    )
                    consecutive_errors = 0
                    report_row = {
                        "gov_id": cand["gov_id"],
                        "unit_name": cand["unit_name"],
                        "state": cand["state"],
                        "source_sweep": cand["source_sweep"],
                        "platform": result.platform or cand["platform"],
                        "outcome": result.outcome,
                        "reason": result.reason,
                        "seed_url": result.seed_url,
                        "video_url": result.video_url,
                        "title": result.title,
                        "date": result.date,
                        "page_url": result.page_url,
                        "original_reject_note": cand.get("original_reject_note", ""),
                    }
                except Exception as e:  # noqa: BLE001
                    consecutive_errors += 1
                    report_row = {
                        "gov_id": cand["gov_id"],
                        "unit_name": cand["unit_name"],
                        "state": cand["state"],
                        "source_sweep": cand["source_sweep"],
                        "platform": cand["platform"],
                        "outcome": "error",
                        "reason": f"unhandled: {type(e).__name__}: {e}",
                        "seed_url": "",
                        "video_url": "",
                        "title": "",
                        "date": "",
                        "page_url": "",
                        "original_reject_note": cand.get("original_reject_note", ""),
                    }
                tally[report_row["outcome"]] = tally.get(report_row["outcome"], 0) + 1
                print(
                    f"[{report_row['outcome']:20}] {cand['gov_id']} "
                    f"{cand['unit_name']!r} ({cand['source_sweep']}) -- "
                    f"{report_row['reason']}"
                )
                log_writer.writerow(report_row)
                log_f.flush()
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(
                        f"\nABORTING: {consecutive_errors} consecutive real errors -- "
                        "stopping per Ryan's politeness rule. Re-run to resume "
                        "(already-logged rows are skipped).",
                        file=sys.stderr,
                    )
                    break
                if i < len(todo) - 1:
                    await asyncio.sleep(REQUEST_DELAY_SECONDS)
    finally:
        log_f.close()
        wo134.PROBE_HOOK = None

    print("\n--- Tally (this run) ---")
    for outcome, count in sorted(tally.items()):
        print(f"{outcome:20} {count}")
    print(f"\nFull report: {REPORT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
