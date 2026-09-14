#!/usr/bin/env python3
"""Applies WO-352 chunk 1's findings onto `jurisdiction_coverage.csv`.

Reads `research/wo352_final_classification.csv` (should_apply=True rows
only -- 21 in chunk 1: 9 no-meeting-nor-video -> meeting-without-video
genuine upgrades, and 12 meeting-without-video -> no-meeting-nor-video,
5 of which are this chunk's own hand-confirmed decorative-video finds).
No tier 1-3 government was queued/ingested in chunk 1 (Alamosa County
CO's real candidate failed a real ffprobe read; York County ME's
candidate duplicates York town ME's own already-queued meeting; Cochise
County AZ's YouTube lead was already recorded by WO-345/WO-349) -- so
this script only ever touches `reject_reason`, never `transcribed`/
`queued`/`example_meeting_url`.

Protocol per CLAUDE.md/ENUMERATION_METHODS.md Sec158: flock the sibling
`.lock`, re-read immediately before writing, refuse to write below 99%
of HEAD's line count, temp file + os.replace, LF endings. Matches rows
by gov_id (exact field match), line-based in the sense that every row
not being changed is carried through byte-for-byte unchanged (only the
reject_reason field of a matched row is replaced) -- never a gov_id-
keyed dict rebuild (per the jurisdiction_coverage.csv rewrite-incident
rule: ~1,700 rows share a blank/duplicate gov_id).

Usage:
    .venv/bin/python scripts/wo352_apply_to_jc.py
    .venv/bin/python scripts/wo352_apply_to_jc.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import fcntl
import os
import subprocess
from pathlib import Path

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
FINAL_CSV = RESEARCH_DIR / "wo352_final_classification.csv"
JC_CSV = RESEARCH_DIR / "jurisdiction_coverage.csv"
JC_LOCK = RESEARCH_DIR / "jurisdiction_coverage.csv.lock"
APPLIED_IDS_TXT = RESEARCH_DIR / "wo352_jc_applied_gov_ids.txt"

GOV_ID_COL = "gov_id"
REJECT_REASON_COL = "reject_reason"


def load_targets() -> dict:
    targets = {}
    with open(FINAL_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("should_apply") == "True":
                targets[row["gov_id"]] = row["new_reject_reason"]
    return targets


def head_line_count() -> int:
    out = subprocess.run(
        [
            "git",
            "-C",
            str(RESEARCH_DIR.parent),
            "show",
            "HEAD:research/jurisdiction_coverage.csv",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return len(out.stdout.splitlines())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    targets = load_targets()
    print(f"{len(targets)} gov_ids to apply from {FINAL_CSV.name}")

    already_applied = set()
    if APPLIED_IDS_TXT.exists():
        already_applied = {
            line.strip() for line in open(APPLIED_IDS_TXT) if line.strip()
        }
    targets = {k: v for k, v in targets.items() if k not in already_applied}
    print(f"{len(targets)} not yet applied by a prior wo352 run")

    baseline = head_line_count()
    floor = int(baseline * 0.99)

    lock_f = open(JC_LOCK, "w")
    fcntl.flock(lock_f, fcntl.LOCK_EX)
    try:
        with open(JC_CSV, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = list(reader)

        gov_id_idx = header.index(GOV_ID_COL)
        reject_idx = header.index(REJECT_REASON_COL)

        changed = []
        matched_gov_ids = set()
        for row in rows:
            if len(row) <= max(gov_id_idx, reject_idx):
                continue
            gid = row[gov_id_idx]
            if gid in targets and gid not in matched_gov_ids:
                old = row[reject_idx]
                new = targets[gid]
                matched_gov_ids.add(gid)
                if old == new:
                    # jc.csv already moved to this value since our
                    # population snapshot was built (real drift under a
                    # concurrent wave) -- nothing to change.
                    continue
                row[reject_idx] = new
                changed.append((gid, old, new))

        unmatched = set(targets) - matched_gov_ids
        if unmatched:
            print(
                f"WARNING: {len(unmatched)} gov_ids not found in jc.csv: {sorted(unmatched)[:10]}"
            )

        print(f"{len(changed)} rows changed")
        for gid, old, new in changed:
            print(f"  {gid}: {old!r} -> {new!r}")

        if args.dry_run:
            print("dry-run: not writing")
            return

        if len(rows) + 1 < floor:
            raise SystemExit(
                f"REFUSING to write: {len(rows) + 1} lines < 99% of HEAD's {baseline}"
            )

        tmp_path = JC_CSV.with_suffix(".csv.wo352tmp")
        with open(tmp_path, "w", newline="\n", encoding="utf-8") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(header)
            writer.writerows(rows)
        os.replace(tmp_path, JC_CSV)

        with open(APPLIED_IDS_TXT, "a", encoding="utf-8") as f:
            for gid in matched_gov_ids:
                f.write(gid + "\n")

        print(f"wrote {JC_CSV}, appended {len(changed)} ids to {APPLIED_IDS_TXT}")
    finally:
        fcntl.flock(lock_f, fcntl.LOCK_UN)
        lock_f.close()


if __name__ == "__main__":
    main()
