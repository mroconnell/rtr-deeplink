#!/usr/bin/env python3
"""Applies WO-282's one real, hand-verified, ingested finding onto
`jurisdiction_coverage.csv`: Saco city, Maine (us:place:2364675) --
found via the passive-discovery-v2 pipeline's homepage-link scan
(`townofmayodan.com`-style hub link on sacomaine.org led to a real
YouTube meeting video with 1,888 real caption segments), hand-checked
(title "Saco City Council Meeting - July 8, 2024" names the right
government), and ingested for real:
/m/saco-me-2024-07-08-saco-city-council-meeting-july-8-2024.

Deliberately narrow -- WO-282's own pipeline confirmed 128 governments'
platforms in total (research/wo282_classified.csv,
research/wo282_targeted.csv), but only this one cleared the FULL bar
this script requires before touching the shared research file: a real
ingested Archive page. The other 127 are real leads (YouTube channels
needing the youtube_drip channel-scan process per this repo's own
"YouTube drip ownership" convention; CivicClerk/first-party hub pages
with an agenda but no video; two Kind-B wrong-video and two unrelated-
third-party-video false positives caught and rejected by the hand-check
gate) -- listed in this WO's own investigation doc and BACKLOG.md rather
than half-applied here without a real ingest behind them.

Follows ENUMERATION_METHODS.md §158's write protocol exactly (same
reference implementation as wo191_apply_to_jc.py): a real `flock` around
the whole read-modify-write, a fresh read taken only after the lock is
held, a row-count floor re-derived from `git show HEAD` at run time, an
atomic temp-file + os.replace() write with explicit LF endings, and a
line-based in-place edit (index built only for O(1) lookup into the
already-read row list -- never a gov_id-keyed dict rebuild, which drops
any row with a blank/duplicate gov_id).

Usage:
    python3 wo282_apply_to_jc.py
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

FALLBACK_MIN_SANE_ROW_COUNT = 30000

FINDING = {
    "gov_id": "us:place:2364675",
    "example_meeting_url": "https://rtr-deeplink-archive.onrender.com/m/saco-me-2024-07-08-saco-city-council-meeting-july-8-2024",
    "suspected_video_provider": "youtube",
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


def main() -> None:
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

        idx = next(
            (i for i, r in enumerate(jc_rows) if r.get("gov_id") == FINDING["gov_id"]),
            None,
        )
        if idx is None:
            raise SystemExit(
                f"gov_id {FINDING['gov_id']} not found in {JC_PATH.name} -- nothing applied"
            )

        row = jc_rows[idx]
        before = dict(row)
        row["shares_video"] = "True"
        row["transcribed"] = "True"
        row["example_meeting_url"] = FINDING["example_meeting_url"]
        row["suspected_video_provider"] = FINDING["suspected_video_provider"]
        row["reject_reason"] = ""
        print(f"row {idx} ({row.get('city_name')}, {row.get('state_or_province')}):")
        for k in (
            "shares_video",
            "transcribed",
            "example_meeting_url",
            "suspected_video_provider",
            "reject_reason",
        ):
            if before.get(k, "") != row.get(k, ""):
                print(f"  {k}: {before.get(k, '')!r} -> {row.get(k, '')!r}")

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
        print(f"wrote {JC_PATH} ({len(jc_rows)} rows, 1 changed)")
    finally:
        if fcntl:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()
