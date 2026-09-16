#!/usr/bin/env python3
"""Applies WO-347's Part A findings onto `jurisdiction_coverage.csv`.

WO-347 reran the 281 governments WO-338 (§346) left as tier 4 ("meeting,
no video") on the five platforms that gained a listing walker (civicplus,
escribe, civicclerk, iqm2, townhallstreams), using the current
`verify_hub()`. See `research/wo347_rerun_verify.csv` for the full rerun
and this WO's `BACKLOG_DONE.md` entry for the hand-check writeup.

**259 of the 281 reconfirmed the same tier-4 verdict** -- these rows
already carry `reject_reason=meeting-without-video` in
`jurisdiction_coverage.csv` from WO-338's own apply pass, so there is
nothing to change; re-deriving the same answer is a real, positive
re-verification, not a no-op to be papered over (same reasoning as
WO-337's §347 "1,287 of 1,704 re-confirmed to the same value" finding).

**3 came back with no signal at all this time** (resolve_error/
resolved_empty -- Clinton County NY, Calmar AB, Bay Lake FL) -- per the
standing "an access/no-signal result never overwrites an already-correct
content-class finding" guard (WO-338/WO-337's own rule), these are left
untouched at `meeting-without-video`.

**19 came back with a real video (tier 1-3) or a YouTube lead (tier 2).**
Every one was hand-read (title/jurisdiction cross-check against the
target government -- see `research/wo347_rerun_verify.csv` and this WO's
`docs/investigations/` or `BACKLOG_DONE.md` writeup for the full table).
Of those 19:

1. **4 real tier-1 finds, already ingested** (`scripts/bulk_ingest.py`,
   confirmed live): Isanti County MN, Surry County VA, Markstay-Warren
   ON, Middleton town MA. Applied here: `reject_reason` cleared,
   `transcribed=True`, `example_meeting_url` set to the ingested page's
   source URL.
2. **9 real tier-3 finds, queued** (`scripts/tier3_auto_transcription_
   queue.txt`, each with its own per-tenant/per-video pin in
   `tenant_overrides.csv`): Lenawee County MI, Amherst NS, St. Stephen
   NB, Pittsboro town IN, Lac la Biche County AB, Leduc County AB, Eliot
   town ME, Boothbay town ME, Hampton Falls town NH. Applied here:
   `reject_reason=video-no-captions-queued`, `queued=true`,
   `example_meeting_url` set to the queued URL. (St. Stephen NB,
   Pittsboro IN, Lac la Biche AB and Hampton Falls NH all had a newest
   real candidate over the 90-minute defer threshold; each was looked at
   one meeting deeper on the same tenant per CLAUDE.md's "long-only
   videos" rule -- see `scripts/wo347_finish_tier3.py`'s own comments
   for the real durations checked.)
3. **1 real tier-3 find, already correctly recorded** -- Lebanon city
   MO's own CivicClerk tenant already carries
   `reject_reason=video-no-captions-queued`/`queued=true` from an
   earlier WO (a different event on the same tenant); nothing to change,
   not re-applied here.
4. **3 real YouTube leads** (Royal Palm Beach village FL, Alfred and
   Plantagenet ON, Toledo city OR) -- appended to
   `research/youtube_channel_leads.csv` only, per the standing "a
   YouTube lead never writes to jc.csv" pattern (WO-338/345's own apply
   scripts). Not touched here; these rows stay
   `reject_reason=meeting-without-video`, which is still correct (a
   video exists, just not one this app will ever fetch from a sweep).
5. **1 real video found, but NOT applied -- hand-read gate failed**:
   Larned city KS. `verify_hub()`'s CivicPlus ranking-fix found a real,
   playable Vimeo URL, but no title was obtainable even with the
   government's own domain as the oEmbed `Referer` (the WO-86 domain-
   privacy-recovery trick, confirmed harmless-but-ineffective here) --
   the hand-read gate has nothing to read, so this is held back rather
   than guessed into place. Row stays `meeting-without-video`.
6. **1 real "video" found, but genuinely NOT video -- a real data-path
   gap, not a hand-read failure**: Olmos Park city TX. `verify_hub()`'s
   CivicClerk listing walker returned a real, live `video_url`, but a
   direct HEAD request on it returns `Content-Type: audio/mp3` -- this
   is CivicClerk's own documented audio-only failure mode
   (`app/platforms/civicclerk.py`'s own module docstring already flags
   this exact shape for Highland, CA). `verify_hub()`'s `video_found`
   flag doesn't check Content-Type before declaring a populated
   `video_url` a real video -- filed as a residual gap in `BACKLOG.md`.
   Row stays `meeting-without-video` (correct: there is no video here,
   only audio).

Follows ENUMERATION_METHODS.md §158's write protocol exactly (same
reference implementation as wo338_apply_to_jc.py / wo345_apply_to_jc.py):
a real `flock` around the whole read-modify-write, a fresh read taken
only after the lock is held, a row-count floor re-derived from `git show
HEAD` at run time, an atomic temp-file + os.replace() write with explicit
LF endings, and a line-based in-place edit into the already-read row
list.

Also writes `research/wo347_jc_applied_gov_ids.txt` -- one gov_id per
line, one per row actually changed.

Usage:
    python3 scripts/wo347_apply_to_jc.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover -- POSIX only, fine for this project
    fcntl = None

import csv

ROOT = Path.home() / "Documents" / "rtr-business" / "research"
JC_PATH = ROOT / "jurisdiction_coverage.csv"
LOCK_FILE = ROOT / "jurisdiction_coverage.csv.lock"
APPLIED_GOV_IDS_TXT = ROOT / "wo347_jc_applied_gov_ids.txt"
RTR_BUSINESS_ROOT = ROOT.parent

FALLBACK_MIN_SANE_ROW_COUNT = 30000

# --- Bucket 1: real tier-1 finds, already ingested ------------------------
TIER1_INGESTED = {
    "us:county:27059": (
        "https://www.isanticountymn.gov/CivicMedia?VID=461"
    ),  # Isanti County, MN
    "us:county:51181": (
        "https://surrycountyva.new.swagit.com/videos/399985"
    ),  # Surry County, VA
    "ca:csd:3552013": (
        "https://pub-markstay-warren.escribemeetings.com/Meeting.aspx?"
        "Id=12eae58c-1ab5-4356-888b-7ac4569fda75"
    ),  # Markstay-Warren, ON
    "us:cousub:2500941095": (
        "https://www.middletonma.gov/CivicMedia?VID=814"
    ),  # Middleton town, MA
}

# --- Bucket 2: real tier-3 finds, queued ----------------------------------
TIER3_QUEUED = {
    "us:county:26091": (
        "https://lenaweecomi.portal.civicclerk.com/event/2874/media"
    ),  # Lenawee County, MI
    "ca:csd:1211011": (
        "https://pub-amherst.escribemeetings.com/Meeting.aspx?"
        "Id=a3cbb212-f269-4682-a144-654f3c2382d4"
    ),  # Amherst, NS
    "ca:csd:1302037": (
        "https://pub-chocolatetown.escribemeetings.com/Meeting.aspx?"
        "Id=2fd2d858-d945-43a6-a5d8-cd21d7e1b890"
    ),  # St. Stephen, NB (looked one meeting deeper -- see module docstring)
    "us:place:1860192": (
        "https://townhallstreams.com/stream.php?location_id=144&id=75561"
    ),  # Pittsboro town, IN (looked one meeting deeper)
    "ca:csd:4812037": (
        "https://pub-llbc.escribemeetings.com/Meeting.aspx?"
        "Id=d65f3cd3-1982-42b7-b26c-9ffc58820dad"
    ),  # Lac la Biche County, AB (98.7 min, shortest of 8 checked)
    "ca:csd:4811012": (
        "https://pub-leduc-county.escribemeetings.com/Meeting.aspx?"
        "Id=7a7ead34-c154-4b36-afa9-ac932bd7d345"
    ),  # Leduc County, AB
    "us:cousub:2303122955": (
        "https://townhallstreams.com/stream.php?location_id=36&id=76337"
    ),  # Eliot town, ME
    "us:cousub:2301506050": (
        "https://townhallstreams.com/stream.php?location_id=53&id=76669"
    ),  # Boothbay town, ME
    "us:cousub:3301533460": (
        "https://townhallstreams.com/stream.php?location_id=107&id=73429"
    ),  # Hampton Falls town, NH (looked one meeting deeper)
}


def _min_sane_row_count() -> int:
    try:
        out = subprocess.run(
            [
                "git",
                f"--git-dir={RTR_BUSINESS_ROOT / '.git'}",
                f"--work-tree={RTR_BUSINESS_ROOT}",
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


def build_findings() -> list[dict]:
    findings = []
    for gov_id, url in TIER1_INGESTED.items():
        findings.append(
            {
                "gov_id": gov_id,
                "reject_reason": "",
                "transcribed": "True",
                "example_meeting_url": url,
            }
        )
    for gov_id, url in TIER3_QUEUED.items():
        findings.append(
            {
                "gov_id": gov_id,
                "reject_reason": "video-no-captions-queued",
                "queued": "true",
                "example_meeting_url": url,
            }
        )
    return findings


def main() -> None:
    findings = build_findings()
    print(f"{len(findings)} rows to apply")

    min_sane_row_count = _min_sane_row_count()

    ROOT.mkdir(parents=True, exist_ok=True)
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
            if "queued" in finding:
                jc_rows[idx]["queued"] = finding["queued"]
            if "transcribed" in finding:
                jc_rows[idx]["transcribed"] = finding["transcribed"]
            if "example_meeting_url" in finding:
                jc_rows[idx]["example_meeting_url"] = finding["example_meeting_url"]
            changed += 1
            applied_gov_ids.append(gov_id)

        print(f"{changed} rows updated, {len(missing)} gov_ids not found in the file")
        if missing:
            print("missing gov_ids:", missing)

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
