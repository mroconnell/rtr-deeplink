#!/usr/bin/env python3
"""Applies WO-292's school-district pilot findings (`research/
wo292_report.csv`, 996 governments, built by `wo292_build_report.py`)
onto `jurisdiction_coverage.csv`.

This WO produced ZERO real ingested Archive pages -- every genuinely
resolvable video candidate this pass found was YouTube (58 governments,
withheld from ingest per this WO's own "make no YouTube calls" brief;
see BACKLOG_DONE.md's WO-292 entry), and every non-YouTube "confirmed
platform" candidate turned out to be a hub/listing page needing a
drill-down step this pilot didn't build (14 governments). So unlike
`wo282_apply_to_jc.py` (which wrote a real ingested URL onto one row),
this script writes only what the taxonomy in ENUMERATION_METHODS.md
§23 covers: `reject_reason` for a genuine dead end
(dns-unresolvable, cloudflare-challenge-blocked, no-platform-link-found,
meeting-without-video for agenda-only BoardDocs/Simbli rows), and
`suspected_video_provider`/`suspected_calendar_provider` for a real,
confirmed (but not yet ingested) signal -- never `shares_video` or
`transcribed`, since nothing here is a live page yet. `domain` is never
touched. A government phase 2/3 could not independently confirm one way
or the other (`candidate-unconfirmed`, 566 rows) is left alone entirely
-- not a reject, and this repo's own convention is to record a
conclusion, not a maybe.

Follows ENUMERATION_METHODS.md §158's write protocol exactly (same
reference implementation as wo191_apply_to_jc.py/wo282_apply_to_jc.py):
a real `flock` around the whole read-modify-write, a fresh read taken
only after the lock is held, a row-count floor re-derived from
`git show HEAD` at run time, an atomic temp-file + os.replace() write
with explicit LF endings, and a line-based in-place edit (index built
only for O(1) lookup into the already-read row list -- never a
gov_id-keyed dict rebuild, which drops any row with a blank/duplicate
gov_id).

Usage:
    python3 wo292_apply_to_jc.py
"""

from __future__ import annotations

import csv
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
REPORT_CSV = ROOT / "wo292_report.csv"

FALLBACK_MIN_SANE_ROW_COUNT = 30000

# Only these outcomes write anything -- see module docstring.
APPLICABLE_OUTCOMES = {
    "dns-unresolvable",
    "cloudflare-challenge-blocked",
    "agenda-only",
    "no-candidate",
    "confirmed-video-platform-youtube",
    "confirmed-video-platform-other",
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


def load_findings() -> dict:
    findings = {}
    with open(REPORT_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["outcome"] in APPLICABLE_OUTCOMES:
                findings[r["gov_id"]] = r
    return findings


def main() -> None:
    findings = load_findings()
    print(f"{len(findings)} applicable findings loaded from {REPORT_CSV.name}")

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

        index_by_gov_id: dict[str, list[int]] = {}
        for i, r in enumerate(jc_rows):
            gid = r.get("gov_id") or ""
            if gid:
                index_by_gov_id.setdefault(gid, []).append(i)

        changed = 0
        not_found = []
        ambiguous = []
        for gov_id, finding in findings.items():
            idxs = index_by_gov_id.get(gov_id)
            if not idxs:
                not_found.append(gov_id)
                continue
            if len(idxs) > 1:
                ambiguous.append(gov_id)
                continue
            row = jc_rows[idxs[0]]
            before = dict(row)
            if finding["reject_reason"]:
                row["reject_reason"] = finding["reject_reason"]
            if finding["suspected_video_provider"]:
                row["suspected_video_provider"] = finding["suspected_video_provider"]
            if finding["suspected_calendar_provider"]:
                row["suspected_calendar_provider"] = finding[
                    "suspected_calendar_provider"
                ]
            if before != row:
                changed += 1

        print(f"{changed} rows changed, {len(not_found)} gov_ids not found in JC")
        if not_found:
            print(f"  not found (first 10): {not_found[:10]}")
        if ambiguous:
            print(f"  ambiguous (duplicate gov_id, skipped): {ambiguous[:10]}")

        # Re-read immediately before writing, per §158.
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
        print(f"wrote {JC_PATH} ({len(jc_rows)} rows, {changed} changed)")
    finally:
        if fcntl:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()
