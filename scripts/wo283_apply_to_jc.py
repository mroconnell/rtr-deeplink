#!/usr/bin/env python3
"""Applies WO-283's hand-verified findings onto `jurisdiction_coverage.csv`.

WO-283 ran passive discovery v2 at full scale against the ~7,746
governments left over after WO-264 and WO-282 (`research/wo283_
population.csv`). Phase 3 (`scripts/wo283_targeted.py`) confirmed a
platform on 414 of them; of those, 245 were YouTube CHANNEL links (not
touched here -- handed to the youtube_drip.py process per this repo's
"YouTube drip ownership" convention, see `research/wo283_confirmed_
youtube_channels.txt`) and 46 more were single-video YouTube URLs this
WO chose not to make further network calls against once it caught its
own launch instruction ("make no YouTube calls") mid-run -- see this
WO's final report for the full disclosure. Those 46 are listed in
`research/wo283_youtube_single_video_leads.txt` for a human/the drip
process to hand-check, not applied here.

That leaves 123 governments this WO actually resolve()-verified without
any YouTube call, all applied below:

  - 1 real ingest: Solebury Township, PA (us:cousub:4201771752) --
    "Housing Forum 06-04-26" on Vimeo, 2,113 real caption segments,
    found via a homepage-body link on soleburytwp.org's own domain.
  - 3 real tier-3 queues (video confirmed, no captions, probed and
    accepted, added to `scripts/tier3_auto_transcription_queue.txt`):
    Clermont town, NY (townhallstreams), Mantua town, UT (Utah PMN
    audio-only recording -- a real, already-supported media shape per
    `app/platforms/utah_pmn.py`'s own docstring), and Capital Regional
    District, BC (Granicus) -- CRD's own flagged candidate ran 2:48:38,
    over the 90-minute cutoff, so this WO looked deeper on the same
    board/committees hub per Ryan's "long-only videos" rule and found a
    21-minute Capital Region Housing Corporation Board meeting instead,
    which is what got queued; the 168-minute one is recorded in
    `scripts/tier3_long_meetings_deferred.txt` only.
  - 1 real video, not a meeting: Searsmont, ME's confirmed Vimeo
    candidate is "WasteHub - Reduce - Reuse - Recycle", a recycling
    program video, not a meeting recording.
  - 110 meeting-without-video: 104 governments whose confirmed candidate
    resolved to a real meeting/agenda page with agenda_items or an
    agenda_link but no video_url at all, plus 6 CivicPlus AgendaCenter
    listings the adapter's own `NoVideoCandidateFound` drill-down (already
    built into `app/platforms/civicplus.py`, not something this WO had to
    add -- see this WO's report on BACKLOG.md's stale "AgendaCenter
    drill-down" entry) checked and confirmed empty.

Follows ENUMERATION_METHODS.md §158's write protocol exactly (same
reference implementation as wo191_apply_to_jc.py / wo282_apply_to_jc.py):
a real `flock` around the whole read-modify-write, a fresh read taken
only after the lock is held, a row-count floor re-derived from `git show
HEAD` at run time, an atomic temp-file + os.replace() write with explicit
LF endings, and a line-based in-place edit (index built only for O(1)
lookup into the already-read row list -- never a gov_id-keyed dict
rebuild, which drops any row with a blank/duplicate gov_id).

Usage:
    python3 scripts/wo283_apply_to_jc.py
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
MEETING_WITHOUT_VIDEO_JSON = Path(__file__).resolve().parent.parent.parent / (
    "wo283_meeting_without_video.json"
)
# The scratch file lives in this agent's private scratchpad, not the repo --
# resolved at run time via an explicit absolute path passed on the CLI
# instead (see `main()`), so this constant is unused; kept only so a reader
# sees at a glance what shape of input this script expects.

FALLBACK_MIN_SANE_ROW_COUNT = 30000

INGESTED = {
    "gov_id": "us:cousub:4201771752",
    "example_meeting_url": (
        "https://rtr-deeplink-archive.onrender.com/m/"
        "solebury-township-pa-2026-06-05-housing-forum-06-04-26"
    ),
    "suspected_video_provider": "vimeo",
}

QUEUED = [
    {
        "gov_id": "us:cousub:3602116177",
        "example_meeting_url": (
            "https://clermontny.gov/category/resources-documents/board-meeting-videos/"
        ),
        "suspected_video_provider": "townhallstreams",
    },
    {
        "gov_id": "us:place:4947840",
        "example_meeting_url": "https://www.mantuautah.gov/town-council-3",
        "suspected_video_provider": "utah_pmn",
    },
    {
        "gov_id": "ca:cd:5917",
        "example_meeting_url": (
            "https://www.crd.ca/government-administration/boards-committees/"
            "committees-commissions/capital-region-housing"
        ),
        "suspected_video_provider": "granicus",
    },
]

VIDEO_WITHOUT_MEETING = [
    {
        "gov_id": "us:cousub:2302766565",  # Searsmont town, ME
        "example_meeting_url": "https://vimeo.com/1096629835",
        "suspected_video_provider": "vimeo",
    },
]


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
            "usage: wo283_apply_to_jc.py <path to wo283_meeting_without_video.json>"
        )
    mwv_path = Path(sys.argv[1])
    meeting_without_video = json.loads(mwv_path.read_text())
    print(f"{len(meeting_without_video)} meeting-without-video rows to apply")

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

        def apply_one(gov_id: str, fields: dict, reject_reason: str, queued: str = ""):
            nonlocal changed
            idx = by_gov_id_first_index.get(gov_id)
            if idx is None:
                missing.append(gov_id)
                return
            row = jc_rows[idx]
            for k, v in fields.items():
                row[k] = v
            row["reject_reason"] = reject_reason
            if queued:
                row["queued"] = queued
            changed += 1

        apply_one(
            INGESTED["gov_id"],
            {
                "shares_video": "True",
                "transcribed": "True",
                "example_meeting_url": INGESTED["example_meeting_url"],
                "suspected_video_provider": INGESTED["suspected_video_provider"],
            },
            reject_reason="",
        )

        for row_data in QUEUED:
            apply_one(
                row_data["gov_id"],
                {
                    "example_meeting_url": row_data["example_meeting_url"],
                    "suspected_video_provider": row_data["suspected_video_provider"],
                },
                reject_reason="video-no-captions-queued",
                queued="true",
            )

        for row_data in VIDEO_WITHOUT_MEETING:
            apply_one(
                row_data["gov_id"],
                {
                    "suspected_video_provider": row_data["suspected_video_provider"],
                },
                reject_reason="video-without-meeting",
            )

        for row_data in meeting_without_video:
            apply_one(
                row_data["gov_id"],
                {},
                reject_reason="meeting-without-video",
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
