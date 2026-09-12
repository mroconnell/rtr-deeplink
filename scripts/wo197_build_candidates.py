#!/usr/bin/env python3
"""WO-197 (2026-09-11): build the candidate list for the listing-pages
media scan.

Ryan's doubt this WO tests: WO-179 recorded 2,517 governments as
`listing_found == yes` with a blank `platform_found` -- a real agenda
or meeting listing, but no recognised video-platform link on it -- and
those were treated as agenda-only. Ryan doubts a listing page never
carries direct video/audio links, an embedded player, or a one-hop link
to a page that does, and wants those checked properly, plus a check for
RSS/Atom/ICS feeds. This script only builds the candidate list; the scan
itself is `scripts/wo197_media_scan.py`.

Filters applied, in order:
1. `wo179_report.csv` rows with `listing_found == "yes"` and
   `platform_found` blank (about 2,517 expected).
2. Skip any gov_id that already has an Archive page today -- a fresh
   `scripts/export_meeting_inventory.py --source export` run, not a
   stale file, since other sessions ingest continuously.
3. Skip any gov_id present in `research/wo196_report.csv` (WO-190's
   leftovers, owned by a different concurrent session) -- if that file
   doesn't exist yet at run time, skip nothing and say so; don't guess.
4. Order by population descending (largest governments first, per the
   work order -- these are also the ones most likely to have a
   dedicated web presence worth a deeper look).

Usage (repo root, worktree venv):
    python scripts/wo197_build_candidates.py \\
        --wo179-report ~/Documents/rtr-business/research/wo179_report.csv \\
        --inventory-csv /tmp/wo197_inventory/meeting_inventory.csv \\
        --wo196-report ~/Documents/rtr-business/research/wo196_report.csv \\
        --out ~/Documents/rtr-business/research/wo197_candidates.csv
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "population",
    "domain",
    "family",
    "family_evidence",
    "path_that_answered",
    "meeting_url",
    "note",
]


def _pop_key(row: dict) -> int:
    try:
        return int(float(row.get("population") or 0))
    except (TypeError, ValueError):
        return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wo179-report", type=Path, required=True)
    ap.add_argument(
        "--inventory-csv",
        type=Path,
        required=True,
        help="fresh export_meeting_inventory.py --source export output",
    )
    ap.add_argument("--wo196-report", type=Path, required=False)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    with args.wo179_report.open(newline="", encoding="utf-8") as f:
        wo179_rows = list(csv.DictReader(f))

    base = [
        r
        for r in wo179_rows
        if (r.get("listing_found") or "").strip().lower() == "yes"
        and not (r.get("platform_found") or "").strip()
    ]
    print(f"wo179 listing-yes/platform-blank rows: {len(base)}", file=sys.stderr)

    with args.inventory_csv.open(newline="", encoding="utf-8") as f:
        already_covered = {
            (r.get("gov_id") or "").strip()
            for r in csv.DictReader(f)
            if (r.get("gov_id") or "").strip()
        }
    print(
        f"gov_ids already covered in Archive (fresh export): {len(already_covered)}",
        file=sys.stderr,
    )

    wo196_gov_ids: set[str] = set()
    if args.wo196_report and args.wo196_report.exists():
        with args.wo196_report.open(newline="", encoding="utf-8") as f:
            wo196_gov_ids = {
                (r.get("gov_id") or "").strip()
                for r in csv.DictReader(f)
                if (r.get("gov_id") or "").strip()
            }
        print(
            f"gov_ids in wo196_report.csv (owned by that session): {len(wo196_gov_ids)}",
            file=sys.stderr,
        )
    else:
        print(
            "wo196_report.csv not found at run time -- skipping 0 gov_ids for that "
            "reason (not a guess: the file simply doesn't exist yet)",
            file=sys.stderr,
        )

    skip_covered = 0
    skip_wo196 = 0
    kept = []
    for r in base:
        gov_id = (r.get("gov_id") or "").strip()
        if gov_id and gov_id in already_covered:
            skip_covered += 1
            continue
        if gov_id and gov_id in wo196_gov_ids:
            skip_wo196 += 1
            continue
        kept.append(r)

    kept.sort(key=_pop_key, reverse=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        for r in kept:
            w.writerow({k: r.get(k, "") for k in FIELDS})

    print(
        f"candidates written: {len(kept)} "
        f"(skipped {skip_covered} already-covered, {skip_wo196} owned by wo196) "
        f"-> {args.out}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
