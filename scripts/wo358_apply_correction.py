"""WO-358 correction pass: the first `wo358_apply_to_jc.py` run treated 6
of the 9 tier-3 candidates as newly queued, but a closer check of
`scripts/tier3_auto_transcription_queue.txt` against each tenant host
(not just the exact candidate URL) showed all 6 tenants already had a
DIFFERENT meeting from the same government queued by an earlier WO --
duplicates, not new queue additions (see this WO's BACKLOG_DONE entry).
This script fixes those 6 `jurisdiction_coverage.csv` rows to their
correct state (`duplicate-queued` where WO-358 found a genuinely new
duplicate, or reverted to the pre-existing correct value where WO-358's
own write had clobbered an already-correct row). Same §158 protocol as
the main apply script.

Usage: python3 scripts/wo358_apply_correction.py
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
FALLBACK_MIN_SANE_ROW_COUNT = 30000

# gov_id -> (queued, reject_reason, example_meeting_url)
CORRECTIONS = {
    # Reverted to the pre-existing correct value -- WO-358's own write
    # had overwritten these with a duplicate candidate URL.
    "us:place:4875236": (
        "True",
        "video-no-captions-queued",
        "https://venustx.portal.civicclerk.com/event/295/media",
    ),
    "us:place:1829358": (
        "True",
        "video-no-captions-queued",
        "https://greencastlein.portal.civicclerk.com/event/1585/media",
    ),
    "us:county:23023": (
        "True",
        "",
        "https://townhallstreams.com/stream.php?location_id=154&id=75643",
    ),
    # Genuinely new duplicate findings this WO.
    "us:place:4866416": (
        "True",
        "duplicate-queued",
        "https://seadrifttx.portal.civicclerk.com/event/20/media",
    ),
    "us:place:4858280": (
        "True",
        "duplicate-queued",
        "https://pleasantontx.iqm2.com/Citizens/Detail_Meeting.aspx?ID=1371",
    ),
    # Petersburgh: the queue's OWN prior candidate (id=72646, "Medicare
    # Seminar") was a real bug -- removed from the queue file by this WO;
    # id=75784 ("Planning Board", already queued) is the government's
    # real queued meeting.
    "us:cousub:3608357441": (
        "True",
        "",
        "https://townhallstreams.com/stream.php?location_id=152&id=75784",
    ),
}


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
            gid = r.get("gov_id")
            if gid in CORRECTIONS:
                queued, reason, url = CORRECTIONS[gid]
                r["queued"] = queued
                r["reject_reason"] = reason
                r["example_meeting_url"] = url
                changed += 1

        with open(JC_PATH, newline="", encoding="utf-8") as f:
            recheck = sum(1 for _ in f) - 1
        if recheck != starting:
            raise SystemExit("file changed mid-run, refusing")

        tmp = JC_PATH.with_suffix(".csv.wo358corrtmp")
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, JC_PATH)
        print(
            f"corrected {changed} of {len(CORRECTIONS)} rows ({starting} rows total, unchanged count)"
        )
    finally:
        if fcntl:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()
