#!/usr/bin/env python3
"""Applies WO-320's hand-verified findings onto `jurisdiction_coverage.csv`.

WO-320 ran WO-283's passive discovery v2 pipeline (phase 1 recon -> phase
2 offline classification -> phase 3 targeted fetch) against group 1 of
the "neither pass" population: 194 US municipalities/townships with
population 5,000+ (`research/passive_neither_1-us-muni-twp-5k-plus.csv`).
Phase 3 confirmed a real platform on 46 of them (all fetched, name+state
verified, not a catch-all, body over 800 bytes).

`scripts/wo320_resolve_diagnostic.py` (read-only, never POSTs) then
resolve()-verified all 46 confirmed candidates. **Zero carried a real
video_url** -- every one is a real meeting/agenda page with no video at
all, or a CivicPlus AgendaCenter listing the adapter's own
`NoVideoCandidateFound` drill-down checked and confirmed empty. One
(cityofmarkham.net) hit a transient TimeoutError and is left unrecorded
for a retry, not applied here. That leaves 45 governments applied below:

  - 30 meeting-without-video: a real meeting/agenda page with
    `agenda_items` or `agenda_link` present, confirmed no video. 22 from
    a direct resolve(); 8 more are CivicPlus AgendaCenter pages where
    the adapter's drill-down checked >=1 recent listing and found no
    video (`Checked N of the most recent listing(s)... found no real
    video link`, N>=1).
  - 15 no-meeting-nor-video: the confirmed page resolved with NO agenda
    evidence at all (agenda_items=0 AND agenda_link=False) -- a real
    page, but no meeting content and no video. 11 from a direct
    resolve(); 4 more are CivicPlus AgendaCenter pages where the
    drill-down found and checked ZERO recent listings (an agenda center
    that exists but currently has nothing posted).

No YouTube network call was made anywhere in this WO (see the final
report's disclosure): 113 youtube.com/youtu.be candidate URLs were
recorded to `research/youtube_channel_leads.csv` (54 channel, 59
single_video) and never fetched, per the launch instructions' literal
no-YouTube-calls rule -- none of those are applied here.

Two vendor-tenant-host rows (caution 1 in this WO's brief) resolved
cleanly via the domain-root-as-candidate fix in `wo320_classify.py`:
`doylestownpa.iqm2.com` (Doylestown borough, PA -> no-meeting-nor-video)
and `vt-shelburne.civicplus.com` (Shelburne town, VT -> no-meeting-nor-
video, 0 AgendaCenter listings).

None of the 8 rows carrying `prior_reject_reason=already-covered`
(caution 3) are among the 46 confirmed candidates, and a live
`/internal/jurisdiction/search` check against the Archive found NO
existing page for any of the 8 under their own or any other gov_id (the
name matches that endpoint returns are all different, same-named
governments in other states/provinces) -- so `already-covered` was
stale/wrong for all 8, and none of them get an `already-covered-other-id`
row here.

Follows ENUMERATION_METHODS.md §158's write protocol exactly (same
reference implementation as wo191_apply_to_jc.py / wo282_apply_to_jc.py /
wo283_apply_to_jc.py): a real `flock` around the whole read-modify-write,
a fresh read taken only after the lock is held, a row-count floor
re-derived from `git show HEAD` at run time, an atomic temp-file +
os.replace() write with explicit LF endings, and a line-based in-place
edit (index built only for O(1) lookup into the already-read row list --
never a gov_id-keyed dict rebuild, which drops any row with a blank/
duplicate gov_id).

Usage:
    python3 scripts/wo320_apply_to_jc.py <path to wo320_findings.json>
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
        raise SystemExit("usage: wo320_apply_to_jc.py <path to wo320_findings.json>")
    findings_path = Path(sys.argv[1])
    findings = json.loads(findings_path.read_text())
    mwv = findings.get("meeting_without_video", [])
    nmnv = findings.get("no_meeting_nor_video", [])
    print(
        f"{len(mwv)} meeting-without-video, {len(nmnv)} no-meeting-nor-video to apply"
    )

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

        def apply_one(gov_id: str, url: str, platform: str, reject_reason: str):
            nonlocal changed
            idx = by_gov_id_first_index.get(gov_id)
            if idx is None:
                missing.append(gov_id)
                return
            row = jc_rows[idx]
            row["reject_reason"] = reject_reason
            if not (row.get("example_agenda_or_calendar_url") or "").strip():
                row["example_agenda_or_calendar_url"] = url
            if not (row.get("suspected_calendar_provider") or "").strip():
                row["suspected_calendar_provider"] = platform
            changed += 1

        for item in mwv:
            apply_one(
                item["gov_id"], item["url"], item["platform"], "meeting-without-video"
            )

        for item in nmnv:
            apply_one(
                item["gov_id"], item["url"], item["platform"], "no-meeting-nor-video"
            )

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
