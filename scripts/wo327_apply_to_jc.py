#!/usr/bin/env python3
"""Applies WO-327's rerun findings onto `jurisdiction_coverage.csv`.

WO-327 built a measured French vocabulary for the passive-discovery hop-
link scorer (see `docs/investigations/hop_scorer_measurement.md`'s
French section) and reran phases 2-3 on WO-323's 92 Quebec rows (fully
checked) and 90 of WO-324's 258 Quebec rows (`--limit 90`, chunk 1 of a
resumable run -- 87 remain, see `BACKLOG_DONE.md`'s WO-327 entry for the
resume command).

Only ONE, high-confidence finding is applied here, deliberately
conservative: a government whose real page was fetched live, matched a
catch-all test as NOT a soft-404, and NAME-matched (the page's own text
names this government's city AND state/province) is a real, current,
identifiable government page. None of these 75 had a known video vendor
confirm (`platform_confirmed`) -- meaning a real meeting/council page
exists with no reachable video, which is exactly `reject_reason=
meeting-without-video` per this project's own taxonomy (ENUMERATION_
METHODS.md §23). Every OTHER row touched by phase 3 (a candidate
fetched but not name-matched, or WO-324's 87 not-yet-checked rows) is
left UNCHANGED -- not enough evidence to assert a specific new outcome
with confidence, so no reason to overwrite what is already there.

Input: `research/wo327_name_matched.json`, a list of
{domain, gov_id, url} built from `research/wo327_qc323_retargeted.csv`
and `research/wo327_qc324_retargeted.csv` (name_match=True rows, best
rank per government).

Follows ENUMERATION_METHODS.md §158's write protocol exactly (same
reference implementation as wo323_apply_to_jc.py): a real `flock` around
the whole read-modify-write, a fresh read taken only after the lock is
held, a row-count floor re-derived from `git show HEAD` at run time, an
atomic temp-file + os.replace() write with explicit LF endings, and a
line-based in-place edit (index built only for O(1) lookup into the
already-read row list -- never a gov_id-keyed dict rebuild, which drops
any row with a blank/duplicate gov_id).

Usage:
    python3 scripts/wo327_apply_to_jc.py <path to wo327_name_matched.json>
"""

from __future__ import annotations

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
    if len(sys.argv) < 2:
        raise SystemExit(
            "usage: wo327_apply_to_jc.py <path to wo327_name_matched.json>"
        )
    findings_path = Path(sys.argv[1])
    findings = json.loads(findings_path.read_text())
    print(f"{len(findings)} name-matched governments to apply as meeting-without-video")

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

        by_gov_id_first_index: dict[str, int] = {}
        for i, r in enumerate(jc_rows):
            gid = r.get("gov_id") or ""
            if gid and gid not in by_gov_id_first_index:
                by_gov_id_first_index[gid] = i

        changed = 0
        missing: list[str] = []

        for item in findings:
            idx = by_gov_id_first_index.get(item["gov_id"])
            if idx is None:
                missing.append(item["gov_id"])
                continue
            row = jc_rows[idx]
            row["reject_reason"] = "meeting-without-video"
            if not (row.get("example_agenda_or_calendar_url") or "").strip():
                row["example_agenda_or_calendar_url"] = item["url"]
            changed += 1

        print(f"{changed} rows updated, {len(missing)} gov_ids not found in the file")
        if missing:
            print("missing gov_ids:", missing[:20])

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
        print(f"wrote {JC_PATH} ({len(jc_rows)} rows, {changed} changed)")
    finally:
        if fcntl:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()
