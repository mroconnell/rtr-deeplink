"""WO-358 one-off correction: `wo358_apply_to_jc.py`'s plain-reason path
didn't clear a stale `queued=true` flag left over from an earlier sweep
for the two `rejected-by-probe` governments (Excelsior city, MN;
Brookline town, MA) -- neither is actually in
`scripts/tier3_auto_transcription_queue.txt`. Same §158 write protocol
as the main apply script (flock, re-read after lock, floor check,
re-check before write, atomic replace, line-based in-place edit only).

Usage: python3 scripts/wo358_fix_stale_queued_flag.py
"""

from __future__ import annotations

import csv
import os
import subprocess
import sys
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

ROOT = Path.home() / "Documents" / "rtr-business" / "research"
JC_PATH = ROOT / "jurisdiction_coverage.csv"
LOCK_FILE = ROOT / "jurisdiction_coverage.csv.lock"

FIX_GOV_IDS = {"us:place:2720078", "us:cousub:2502109175"}
FALLBACK_MIN_SANE_ROW_COUNT = 30000


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
        return int(out.count("\n") * 0.99)
    except Exception as e:  # noqa: BLE001
        print(f"WARNING: floor fallback ({e})", file=sys.stderr)
        return FALLBACK_MIN_SANE_ROW_COUNT


def main() -> None:
    floor = _min_sane_row_count()
    lock_fd = open(LOCK_FILE, "w")
    if fcntl:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
    try:
        with open(JC_PATH, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            rows = list(reader)
        starting = len(rows)
        if starting < floor:
            raise SystemExit(f"only {starting} rows, expected >= {floor}")
        changed = 0
        for r in rows:
            if (
                r.get("gov_id") in FIX_GOV_IDS
                and (r.get("queued") or "").strip().lower() == "true"
            ):
                r["queued"] = ""
                changed += 1
        with open(JC_PATH, newline="", encoding="utf-8") as f:
            recheck = sum(1 for _ in f) - 1
        if recheck != starting:
            raise SystemExit("file changed mid-run, refusing")
        tmp = JC_PATH.with_suffix(".csv.wo358fixtmp")
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, JC_PATH)
        print(f"changed: {changed} of {starting} rows (unchanged count)")
    finally:
        if fcntl:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()
