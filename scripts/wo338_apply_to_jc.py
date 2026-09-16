#!/usr/bin/env python3
"""Applies WO-338's findings onto `jurisdiction_coverage.csv`.

WO-338 is the rerun, with WO-333's fixed `verify_hub()` verification, of
the 2,825-row population (`research/passive_rerun_1-verifier-fix.csv`,
filtered to `prior_reject_reason != no-platform-link-found` -- 1,750
meeting-without-video + 1,075 no-meeting-nor-video) that the broken
verification had mislabelled. See `scripts/wo338_finish.py`'s own
docstring for how `research/wo338_final_classification.csv` (one row
per government: tier, prior/new reject_reason, should_apply, a note)
was derived, and this WO's `BACKLOG_DONE.md` entry for the full
numbers.

**44 rows are applied here.** All but 4 are a reject_reason-only update
(a stronger or hand-corrected content-class verdict -- see
`wo338_finish.py`'s `HAND_OVERRIDES`/tier-4-upgrade logic): 34 rows
where `verify_hub()` actually walked a confirmed platform and found a
real meeting/listing this time (no-meeting-nor-video -> meeting-
without-video), 6 rows where a hand-check corrected a verify_hub false
positive down to no-meeting-nor-video, 1 augusta-area row explicitly
excluded (see below), and 3 governments that get the full treatment
(`transcribed`, `queued`, `example_meeting_url`) because a real video
was found, hand-checked, and already ingested/queued by hand during
this WO:

  - `ca:csd:5901006` (Sparwood, BC) -- tier 1, real captions (1,614
    segments via CivicWeb -> Vimeo), already ingested:
    `/m/sparwood-bc-2026-08-04-informal-public-hearing-04-aug-2026`.
  - `us:place:2747690` (Oak Grove city, MN), `us:cousub:0911012270`
    (Canton town, CT), `us:sd:0611280` (Dixon Unified School District,
    CA) -- tier 3, real video no captions, queued to
    `scripts/tier3_auto_transcription_queue.txt` after
    `probe_tier3_queue.py` accepted each (Oak Grove's own first find was
    108.5 minutes, over the 90-minute cutoff -- re-probed against 5 more
    candidates from the same Granicus listing per Ryan's long-only-
    videos rule and requeued on a real 29.1-minute Council Work Session
    instead; see this WO's `BACKLOG_DONE.md` entry).

**2,102 rows are explicitly NOT applied even though `verify_hub()`
reconfirmed a real platform this run and came back empty
(`resolved_empty`/`empty_listing`).** Per the standing guard ("an
access/no-signal result never overwrites an already-correct
content-class finding") and this WO's own live check: of the 105
would-be downgrades from meeting-without-video, at least 17 were on
platforms the WO-337/338 addendum explicitly flags as still hand-step
(no real listing walker yet -- townhallstreams, civicclerk, escribe),
where an empty result just reflects the walker's own gap, not a real
absence of a meeting. The other ~85 (civicweb/utah_pmn/civicplus/iqm2/
...) can't be told apart from those without a per-platform hand check
this WO's budget didn't cover, so none of the 105 are applied -- left
for a future WO with budget to hand-check platform by platform (see
`BACKLOG.md`'s new entry). Likewise, 2,411 governments where no
platform was reconfirmed at all this run keep their prior finding
untouched, for the same reason -- failing to RE-find a platform this
run is not evidence the prior finding was wrong.

**1 row explicitly excluded**: `augustaga.gov` / `us:county:13245`
("Richmond County" -- a non-canonical id for the Augusta-Richmond
County Consolidated Government, canonical `us:place:1304204`) already
carries `reject_reason=video-no-captions-queued, queued=true` from a
different, real YouTube find. `verify_hub()` found a second real
ChampDS video for the same government -- not applied, "one meeting per
government."

Follows ENUMERATION_METHODS.md §158's write protocol exactly (same
reference implementation as wo191_apply_to_jc.py / wo283_apply_to_jc.py):
a real `flock` around the whole read-modify-write, a fresh read taken
only after the lock is held, a row-count floor re-derived from `git show
HEAD` at run time, an atomic temp-file + os.replace() write with explicit
LF endings, and a line-based in-place edit (index built only for O(1)
lookup into the already-read row list -- never a gov_id-keyed dict
rebuild, which drops any row with a blank/duplicate gov_id).

Also writes `research/wo338_jc_applied_gov_ids.txt` -- one gov_id per
line, one per row actually changed -- since WO-337 runs concurrently
against a different (non-overlapping) population and also writes
research rows; the conductor asked for this so the two WOs' actual
jc.csv writes are each independently auditable against their own
population.

Usage:
    python3 scripts/wo338_apply_to_jc.py
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
FINAL_CLASSIFICATION_CSV = ROOT / "wo338_final_classification.csv"
APPLIED_GOV_IDS_TXT = ROOT / "wo338_jc_applied_gov_ids.txt"

FALLBACK_MIN_SANE_ROW_COUNT = 30000

# The 3 real, hand-checked, queued tier-3 finds -- get example_meeting_url
# + queued=true alongside the reject_reason update.
REAL_TIER3_QUEUED = {
    "us:place:2747690": "https://oakgrove.granicus.com/MediaPlayer.php?view_id=2&clip_id=737",
    "us:cousub:0911012270": (
        "https://townmeetings.s3.us-east-2.amazonaws.com/Board+of+Finance/2026/"
        "Board+of+Finance+Regular+Meeting+8.17.2026-20260817_190208-Meeting+Recording.mp4"
    ),
    "us:sd:0611280": "https://dixon-ca.granicus.com/MediaPlayer.php?view_id=3&clip_id=1917",
}

# The 1 real, hand-checked, ingested tier-1 find -- gets transcribed=True,
# a blank reject_reason, and example_meeting_url.
REAL_TIER1_INGESTED = {
    "ca:csd:5901006": "https://sparwood.civicweb.net/Portal/MeetingInformation.aspx?Id=1153",
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


def load_findings() -> list[dict]:
    with open(FINAL_CLASSIFICATION_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    findings = []
    for r in rows:
        if r.get("should_apply") != "True":
            continue
        gov_id = r.get("gov_id", "")
        if not gov_id:
            continue
        findings.append(
            {
                "gov_id": gov_id,
                "reject_reason": r["new_reject_reason"],
            }
        )
    return findings


def main() -> None:
    findings = load_findings()
    print(f"{len(findings)} rows to apply")

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
        applied_gov_ids: list[str] = []

        for finding in findings:
            gov_id = finding["gov_id"]
            idx = by_gov_id_first_index.get(gov_id)
            if idx is None:
                missing.append(gov_id)
                continue
            jc_rows[idx]["reject_reason"] = finding["reject_reason"]
            if gov_id in REAL_TIER3_QUEUED:
                jc_rows[idx]["queued"] = "true"
                jc_rows[idx]["example_meeting_url"] = REAL_TIER3_QUEUED[gov_id]
            if gov_id in REAL_TIER1_INGESTED:
                jc_rows[idx]["transcribed"] = "True"
                jc_rows[idx]["example_meeting_url"] = REAL_TIER1_INGESTED[gov_id]
            changed += 1
            applied_gov_ids.append(gov_id)

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

        with open(APPLIED_GOV_IDS_TXT, "a", encoding="utf-8") as f:
            for gid in applied_gov_ids:
                f.write(gid + "\n")
        print(f"appended {len(applied_gov_ids)} gov_ids to {APPLIED_GOV_IDS_TXT}")
    finally:
        if fcntl:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()
