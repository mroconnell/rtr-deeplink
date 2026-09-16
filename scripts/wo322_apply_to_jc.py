#!/usr/bin/env python3
"""Applies WO-322's passive-discovery-v2 findings onto
`jurisdiction_coverage.csv` for its own population (`research/
passive_neither_3-us-muni-twp-under-5k.csv`, 1,266 unique domains,
1,276 rows).

WO-322 ran WO-283's pipeline (phase 1 recon -> phase 2 offline classify
-> phase 3 targeted fetch) against all 1,266 domains, then hand-checked
every one of the 223 platform-confirmed candidates through the real
resolve() pipeline before writing anything back. See this WO's final
report and `BACKLOG_DONE.md` entry for the full breakdown (a real
recon-pipeline deadlock found and fixed, a request that hung past every
timeout on 2 domains, an accidental YouTube network call found and
disclosed, one real tier-3 queue, one YouTube lead withheld pending the
drip process).

Input: `research/wo322_apply_data.json` (one row per domain: `domain`,
`category`, `reject_reason` [may be null, meaning "leave alone"],
optional `suspected_calendar_provider`/`suspected_video_provider`,
optional `queued`). Built by this WO's own
`wo322_build_apply_data.py` (kept in this WO's private scratch
directory, not committed, since its output -- this JSON file -- is the
durable artifact).

Follows ENUMERATION_METHODS.md §158's write protocol exactly (same
reference shape as `wo191_apply_to_jc.py`/`wo283_apply_to_jc.py`): a
real `flock` around the whole read-modify-write, a fresh read taken only
after the lock is held, a row-count floor re-derived from `git show
HEAD` at run time, an atomic temp-file + `os.replace()` write with
explicit LF endings, and a line-based in-place edit (index built only
for O(1) lookup into the already-read row list -- never a gov_id-keyed
dict rebuild, which drops any row with a blank/duplicate gov_id).

Reuses `apply_reject_reason()`/`has_meeting_or_agenda_url()`/
`ACCESS_REJECT_REASONS` from `wo226_apply_to_jc.py` (the reference
implementation COVERAGE_HANDOVER.md section 4 names for Ryan's two
approved guards) rather than reimplementing them.

Usage:
    python3 scripts/wo322_apply_to_jc.py
    python3 scripts/wo322_apply_to_jc.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover -- POSIX only, fine for this project
    fcntl = None

ROOT = Path.home() / "Documents" / "rtr-business" / "research"
JC_PATH = ROOT / "jurisdiction_coverage.csv"
LOCK_FILE = ROOT / "jurisdiction_coverage.csv.lock"
APPLY_DATA_JSON = ROOT / "wo322_apply_data.json"

FALLBACK_MIN_SANE_ROW_COUNT = 30000

sys.path.insert(0, str(ROOT))
from wo226_apply_to_jc import (  # noqa: E402
    ACCESS_REJECT_REASONS,  # noqa: F401  (re-exported for callers/tests)
    apply_reject_reason,
    has_meeting_or_agenda_url,  # noqa: F401  (used internally by apply_reject_reason)
)


def _min_sane_row_count() -> int:
    try:
        out = subprocess.run(
            [
                "git",
                "-C",
                str(ROOT.parent),
                "show",
                "HEAD:research/jurisdiction_coverage.csv",
            ],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        committed_lines = out.count("\n")
        floor = int(committed_lines * 0.99)
        print(
            f"committed jurisdiction_coverage.csv: {committed_lines} lines -> 99% floor {floor}"
        )
        return floor
    except Exception as e:  # noqa: BLE001
        print(
            f"WARNING: could not compute live floor from git ({e}); using fallback",
            file=sys.stderr,
        )
        return FALLBACK_MIN_SANE_ROW_COUNT


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    apply_data = json.loads(APPLY_DATA_JSON.read_text())
    print(f"{len(apply_data)} rows to apply from {APPLY_DATA_JSON}")

    min_sane_row_count = _min_sane_row_count()

    lock_fd = open(LOCK_FILE, "w")
    if fcntl:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
    try:
        with open(JC_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            jc_fieldnames = reader.fieldnames
            jc_rows = list(reader)
        starting_row_count = len(jc_rows)
        if starting_row_count < min_sane_row_count:
            raise SystemExit(
                f"{JC_PATH.name} reads as only {starting_row_count} rows (expected "
                f"at least {min_sane_row_count}) -- refusing to treat a truncated "
                "read as a legitimate new baseline. Investigate before retrying."
            )
        print(f"{starting_row_count} rows read")

        # Keyed by domain, not domain+gov_id, and not a bare gov_id dict:
        # 5 domains in WO-322's own population share a single website
        # across several small governments (e.g. co.accomack.va.us serves
        # 6 different towns in Accomack County, VA) -- since this WO's
        # whole pipeline fetched and scored each DOMAIN once, the same
        # finding genuinely applies to every government that domain
        # serves, so every jurisdiction_coverage.csv row sharing a domain
        # gets the same update, not just the first.
        by_domain_indices: dict[str, list[int]] = {}
        for i, r in enumerate(jc_rows):
            dom = (r.get("domain") or "").strip()
            if dom:
                by_domain_indices.setdefault(dom, []).append(i)

        applied = 0
        skipped_guard = 0
        missing: list[str] = []
        guard_reasons: dict[str, int] = {}

        for item in apply_data:
            domain = item["domain"]
            indices = by_domain_indices.get(domain)
            if not indices:
                missing.append(f"{domain} ({item.get('gov_id', '')})")
                continue

            for idx in indices:
                row = jc_rows[idx]

                if item.get("suspected_calendar_provider"):
                    row["suspected_calendar_provider"] = item[
                        "suspected_calendar_provider"
                    ]
                if item.get("suspected_video_provider"):
                    row["suspected_video_provider"] = item["suspected_video_provider"]
                if item.get("queued"):
                    row["queued"] = item["queued"]

                new_reason = item.get("reject_reason")
                if new_reason is None:
                    # Deliberately left alone: youtube-lead-skipped (pending
                    # the drip process) and the one real find withheld
                    # pending YouTube hand-check (Plainfield VT) -- see this
                    # WO's report.
                    applied += 1
                    continue

                ok, why = apply_reject_reason(row, new_reason, tested_domain=domain)
                if ok:
                    applied += 1
                else:
                    skipped_guard += 1
                    guard_reasons[why] = guard_reasons.get(why, 0) + 1

        print(
            f"{applied} rows updated (incl. provider-only), {skipped_guard} skipped by a guard, "
            f"{len(missing)} domains not found in the file"
        )
        if guard_reasons:
            print("guard reasons:", guard_reasons)
        if missing:
            print("missing domains (first 20):", missing[:20])

        if args.dry_run:
            print("--dry-run: not writing")
            return

        # Re-read immediately before writing, per §158 -- refuse a stale
        # write if another session's apply landed since we opened the file.
        with open(JC_PATH, newline="", encoding="utf-8") as f:
            reread_rows = list(csv.DictReader(f))
        if len(reread_rows) != starting_row_count:
            raise SystemExit(
                f"row count changed between read ({starting_row_count}) and "
                f"write ({len(reread_rows)}) -- another session wrote in between. "
                "Re-run this script rather than overwrite that work."
            )

        tmp_path = JC_PATH.with_suffix(".csv.tmp")
        with open(tmp_path, "w", newline="\n", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=jc_fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(jc_rows)
        tmp_path.replace(JC_PATH)
        print(f"wrote {JC_PATH} ({len(jc_rows)} rows, {applied} changed)")
    finally:
        if fcntl:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()
