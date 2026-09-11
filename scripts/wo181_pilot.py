"""WO-181 (2026-09-10) Part A, step 3: read-mostly pilot of
`ladder_with_alternates()` (scripts/coverage_alternates.py) against the
research file's rows that carry an alternate domain AND an ACCESS-class
reject on their primary domain.

Candidate list: every row in
`~/Documents/rtr-business/research/jurisdiction_coverage.csv` with a
non-blank `alternate_domains` and a `reject_reason` in
`coverage_alternates.ACCESS_REASONS` -- computed fresh at run time, not
a fixed list, since the file is live. WO-181's own brief cites 273 such
rows as of the evening of 2026-09-10; a run against this repo's copy the
same evening found 265 (see the run's own printed count) -- a small,
expected drift given the file is written by other concurrent sweeps, not
a data-quality problem to chase.

Rungs 2 and 3 ONLY, per the brief: plain honest HTTP, then browser
headers once after a 403 or a dropped connection, never after a 404. NO
headless in this pilot -- see coverage_alternates.rungs_2_3_ladder_fn's
own docstring for why a restricted ladder_fn was built rather than
reusing wo147_access_ladder_sweep.run_access_ladder directly (that
function's own fallback path can reach headless).

Politeness: one request in flight at a time (plain asyncio, no
concurrency), 2 seconds between every request -- both within a
government (between its candidate domains) and between governments.
Honest User-Agent (HONEST_HEADERS, same constant every other sweep
script in this repo uses). Stops at any human-verification challenge
marker and records it as `cloudflare-challenge-blocked`, never retries
past it.

This script is READ-MOSTLY: it never writes jurisdiction_coverage.csv
itself. It only appends to wo181_report.csv (resumable -- a re-run skips
gov_ids already present). Applying the report's outcomes back onto the
research file, and any ingest, is a separate, deliberate step (see
BACKLOG_DONE.md's WO-181 entry and the PR description) -- keeping this
script read-mostly means a run can be killed and re-run freely with zero
risk to the shared research file.

Usage:
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo181_pilot.db" \\
        python3 scripts/wo181_pilot.py [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Set

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.coverage_alternates import (  # noqa: E402
    ACCESS_REASONS,
    FOUND,
    ladder_with_alternates,
    rungs_2_3_ladder_fn,
)

# Pure primitives reused unchanged from wo147 -- see
# coverage_alternates.rungs_2_3_ladder_fn's docstring for why importing
# them (rather than copying) is safe for a caller like this one that
# never calls wo134_confirmed_hits_ingest.process_row() itself (one real
# import-time side effect DOES exist in that module -- see the same
# docstring -- but it's inert here).
from scripts.wo147_access_ladder_sweep import (  # noqa: E402
    BROWSER_HEADERS,
    HONEST_HEADERS,
    fetch_one,
    find_platform_link,
    is_challenge,
)

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
RESEARCH_CSV = RESEARCH_DIR / "jurisdiction_coverage.csv"
REPORT_CSV = RESEARCH_DIR / "wo181_report.csv"

GOV_DELAY_SECONDS = 2.0
HOST_DELAY_SECONDS = 2.0

REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "population",
    "prior_reason",
    "primary_domain",
    "alternates_tried",
    "answered_domain",
    "rung_answered",
    "access_mode",
    "platform_found",
    "hit_url",
    "outcome",
    "reject_reason",
]


def gov_kind_from_id(gov_id: str) -> str:
    """Mechanical parse of the gov_id's own prefix (e.g. 'us:place:0627000'
    -> 'us:place') -- not a guess, just the leading colon-separated
    segments with the trailing numeric/slug id dropped."""
    gov_id = (gov_id or "").strip()
    if not gov_id:
        return ""
    parts = gov_id.split(":")
    if len(parts) <= 1:
        return gov_id
    return ":".join(parts[:-1])


def load_candidates() -> List[Dict[str, str]]:
    with RESEARCH_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = [
        r
        for r in rows
        if (r.get("alternate_domains") or "").strip()
        and (r.get("reject_reason") or "").strip() in ACCESS_REASONS
    ]
    return out


def already_done_gov_ids() -> Set[str]:
    if not REPORT_CSV.exists():
        return set()
    with REPORT_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f) if r.get("gov_id")}


def report_writer():
    is_new = not REPORT_CSV.exists()
    f = REPORT_CSV.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=REPORT_FIELDS)
    if is_new:
        w.writeheader()
        f.flush()
    return f, w


async def process_row(
    session: aiohttp.ClientSession, row: Dict[str, str]
) -> Dict[str, str]:
    ladder_fn = rungs_2_3_ladder_fn(
        session,
        HONEST_HEADERS,
        BROWSER_HEADERS,
        fetch_one,
        is_challenge,
        find_platform_link,
        host_delay_seconds=HOST_DELAY_SECONDS,
    )
    result = await ladder_with_alternates(
        row, ladder_fn, between_candidates_seconds=HOST_DELAY_SECONDS
    )
    outcome = result.outcome

    if outcome.reason == FOUND:
        classification = "found"
        new_reject_reason = ""
    elif outcome.reason in ACCESS_REASONS:
        classification = "still-access-blocked"
        new_reject_reason = outcome.reason
    else:
        # a content-class answer surfaced on one of the alternates (the
        # primary was access-class, an alternate resolved but had no
        # platform link / no video etc). Recorded, not retried further --
        # per scope, this pilot doesn't chase content rejects.
        classification = "content-reject-on-alternate"
        new_reject_reason = outcome.reason

    return {
        "gov_id": row.get("gov_id", ""),
        "name": row.get("city_name", ""),
        "state": row.get("state_or_province", ""),
        "gov_kind": gov_kind_from_id(row.get("gov_id", "")),
        "population": row.get("population_estimate", ""),
        "prior_reason": row.get("reject_reason", ""),
        "primary_domain": row.get("domain", ""),
        "alternates_tried": result.alternates_tried,
        "answered_domain": result.answered_domain,
        "rung_answered": outcome.rung,
        "access_mode": outcome.rung,
        "platform_found": outcome.platform or "",
        "hit_url": outcome.hit_url or "",
        "outcome": classification,
        "reject_reason": new_reject_reason,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--dry-run", action="store_true", help="print candidate count and exit"
    )
    args = parser.parse_args()

    candidates = load_candidates()
    print(
        f"{len(candidates)} candidate rows (alternate_domains set, ACCESS-class reject)."
    )

    if args.dry_run:
        return

    done = already_done_gov_ids()
    print(f"{len(done)} gov_ids already in {REPORT_CSV.name} -- skipping those.")

    to_process = [r for r in candidates if r.get("gov_id", "") not in done]
    if args.limit:
        to_process = to_process[: args.limit]
    print(f"Processing {len(to_process)} rows this run.")

    tally: Dict[str, int] = {}
    report_f, writer = report_writer()
    try:
        async with aiohttp.ClientSession() as session:
            for i, row in enumerate(to_process):
                started = time.monotonic()
                try:
                    result_row = await process_row(session, row)
                except Exception as e:  # noqa: BLE001 -- log and keep going
                    result_row = {
                        "gov_id": row.get("gov_id", ""),
                        "name": row.get("city_name", ""),
                        "state": row.get("state_or_province", ""),
                        "gov_kind": gov_kind_from_id(row.get("gov_id", "")),
                        "population": row.get("population_estimate", ""),
                        "prior_reason": row.get("reject_reason", ""),
                        "primary_domain": row.get("domain", ""),
                        "alternates_tried": "",
                        "answered_domain": "",
                        "rung_answered": "",
                        "access_mode": "",
                        "platform_found": "",
                        "hit_url": "",
                        "outcome": "error",
                        "reject_reason": f"pilot-error: {e}"[:200],
                    }
                writer.writerow(result_row)
                report_f.flush()
                tally[result_row["outcome"]] = tally.get(result_row["outcome"], 0) + 1
                elapsed = time.monotonic() - started
                print(
                    f"[{i + 1}/{len(to_process)}] {result_row['name']}, {result_row['state']}: "
                    f"{result_row['outcome']} ({elapsed:.1f}s)"
                )
                if i < len(to_process) - 1:
                    await asyncio.sleep(GOV_DELAY_SECONDS)
    finally:
        report_f.close()

    print("\n--- Tally (this run) ---")
    for k, v in sorted(tally.items()):
        print(f"{k:28} {v}")
    print(f"\nFull report: {REPORT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
