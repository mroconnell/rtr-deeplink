"""WO-278 Part B: hand-read + ingest pass over the corrected WO-273
confirmation list (`research/wo278_confirmed_hits.csv`, built by
`wo278_build_input.py` from `research/wo273_targeted_corrected.csv`'s
governments with `platform_confirmed` set after WO-278's Part A fix).

Deliberately does NOT reimplement resolve/discovery/ingest -- it imports
`scripts/wo134_confirmed_hits_ingest.py`'s already-built pipeline
(`process_row()`: locate_platform_url() -> resolve_seed() ->
resolve_via_platform()/get_finder(), MEETING_ALLOWLIST/PROMO_BLOCKLIST
pre-filtering, WO-144/WO-170 tier-3 probe-and-select, shared-host pin
writer, tenant-override application) and points its already-covered
check and log file at this WO's own files instead. Same reasoning as
every other confirmed-hits batch in this repo: a real live meeting page
still needs a human to read its title/channel before trusting it (see
CLAUDE.md's "hand-check every found video" rule) -- this script performs
the automated discovery half, and every row it actually ingests or
queues still needs a human to read the logged `title`/`date`/`page_url`
before trusting it (the WO-278 report hand-verified the page this run
actually created by fetching it and reading its real content, the same
way the adapter's own `classify_video_hand_check()` pre-filter is
always followed by an actual read, per CLAUDE.md).

**Why a confirmed government's hit_source_urls are often NOT a meeting
page.** WO-273's phase 2 flagged URLs by vocabulary score (a "hub"/
"meeting" word in the path), and Part A's fix only tightened WHICH
platform match counts as confirmed -- it says nothing about whether the
specific flagged URL is itself a meetings calendar. A vendor like
Granicus or CivicClerk hosts a government's ENTIRE public website, not
just its meeting videos, so a real, correctly-identified Granicus/
CivicClerk government can still have its highest-scoring flagged URL be
a "Senior Citizens Center Board" page or a news post -- genuinely on
that vendor's platform, genuinely not a meeting listing. `locate_
platform_url()` already tolerates this safely: when the confirmed
hit_url resolves to a non-listing page, `resolve_via_platform()` either
raises `CalendarPageError` (handled -- depth-searches the real listing
candidates it returns) or comes back with no video/agenda (handled --
`RowSkip`, never a wrong ingest). This is why a real, positive
`platform_confirmed` answer still yields a `skipped`/`no_video_found`
outcome on many rows here -- that is the pipeline correctly declining to
guess, not a bug in this script.

Usage (from the repo root, venv active, DATABASE_URL set):
    python scripts/wo278_build_input.py    # writes research/wo278_confirmed_hits.csv
    python scripts/export_meeting_inventory.py --out-dir /tmp/wo278_inventory --source export
    python scripts/wo278_confirmed_hits_ingest.py
    python scripts/wo278_confirmed_hits_ingest.py --limit 10
"""

import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path

import aiohttp
import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402
from app.platforms import register_all_finders  # noqa: E402
from scripts.wo134_confirmed_hits_ingest import (  # noqa: E402
    RowError,
    RowResult,
    _already_logged_gov_ids,
    _load_covered_gov_ids,
    _log_writer,
    build_probe_select_hook,
    process_row,
)

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
INPUT_CSV = RESEARCH_DIR / "wo278_confirmed_hits.csv"
LOG_CSV = RESEARCH_DIR / "wo278_confirmed_hits_ingest_log.csv"
DEFAULT_INVENTORY_CSV = Path("/tmp/wo278_inventory/meeting_inventory.csv")
REQUEST_DELAY_SECONDS = 1.5


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--inventory-csv", type=Path, default=DEFAULT_INVENTORY_CSV)
    args = parser.parse_args()

    if not wo134._base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (check .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    register_all_finders()
    wo134.PROBE_SELECT_HOOK = build_probe_select_hook()

    covered_gov_ids = _load_covered_gov_ids(args.inventory_csv)
    print(f"{len(covered_gov_ids)} gov_ids already have an archived page.")

    if not INPUT_CSV.exists():
        print(f"ERROR: {INPUT_CSV} missing -- run wo278_build_input.py first.")
        sys.exit(1)
    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))
    print(f"{len(all_rows)} rows in {INPUT_CSV.name}")

    already_done = _already_logged_gov_ids(LOG_CSV)
    print(f"{len(already_done)} gov_ids already logged from a prior run -- skipping.")

    to_process = [r for r in all_rows if r["gov_id"] not in already_done]
    if args.limit:
        to_process = to_process[: args.limit]
    print(f"Processing {len(to_process)} row(s) against {wo134._base_url()}...\n")

    log_f, log_writer = _log_writer(LOG_CSV)
    tally: dict = {}
    consecutive_errors = 0
    MAX_CONSECUTIVE_ERRORS = 6
    try:
        async with aiohttp.ClientSession() as session:
            for i, row in enumerate(to_process):
                try:
                    result = await process_row(
                        session, row, covered_gov_ids, "wo278_confirmed_hits"
                    )
                    consecutive_errors = 0
                except RowError as e:
                    result = RowResult(
                        row["gov_id"], row["unit_name"], "", "error", str(e)
                    )
                    consecutive_errors += 1
                except Exception as e:  # noqa: BLE001
                    result = RowResult(
                        row["gov_id"],
                        row["unit_name"],
                        "",
                        "error",
                        f"unhandled exception: {e}",
                    )
                    consecutive_errors += 1
                tally[result.outcome] = tally.get(result.outcome, 0) + 1
                print(
                    f"[{result.outcome:20}] {result.gov_id} {result.unit_name!r} "
                    f"platform={result.platform!r} -- {result.reason}"
                )
                log_writer.writerow(result.__dict__)
                log_f.flush()
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(
                        f"\nABORTING: {consecutive_errors} consecutive real errors -- "
                        "stopping per Ryan's politeness rule. Re-run to resume.",
                        file=sys.stderr,
                    )
                    break
                if i < len(to_process) - 1:
                    await asyncio.sleep(REQUEST_DELAY_SECONDS)
    finally:
        log_f.close()

    print("\n--- Tally (this run) ---")
    for outcome, count in sorted(tally.items()):
        print(f"{outcome:20} {count}")
    print(f"\nFull log: {LOG_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
