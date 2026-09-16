#!/usr/bin/env python3
"""Applies WO-345's findings onto `jurisdiction_coverage.csv`.

WO-345 (= WO-338b) reran WO-338's 108-row "confirmed platform, walk came
back empty" residual (civicplus/civicclerk/escribe/iqm2/townhallstreams/
cablecast) through the current `verify_hub()`, which now carries the
CivicPlus (WO-341), CivicClerk (WO-342), eScribe (WO-343), iQM2-second-
shape/Town Hall Streams/Cablecast-third-template (WO-344) listing
walkers WO-338 didn't have. See this WO's `BACKLOG_DONE.md` entry for
the full numbers and hand-check writeup.

Three buckets applied here, all built from `wo345_verify.csv` plus this
WO's own hand-check (title/jurisdiction cross-check against the target
government, duration probing via `probe_tier3_queue.py`, and a dedupe
check against the tracked tier-3 queue/deferred files for "one meeting
per government"):

1. **30 tier-4 rows** (`meeting_found=True, video_found=False`) --
   `reject_reason` set to `meeting-without-video`, same upgrade WO-338
   itself made for its own "nothing found -> meeting, no video" rows.
2. **25 tier-3 rows** (real video, no reachable captions) --
   `reject_reason=video-no-captions-queued`, `queued=true`,
   `example_meeting_url` set. Of these, 9 are genuinely new tier-3 queue
   additions this WO made (see `scripts/tier3_auto_transcription_queue.
   txt`'s new lines); 13 were ALREADY sitting in the tracked queue file
   from an earlier WO (mostly WO-344's own Town Hall Streams sample) but
   `jurisdiction_coverage.csv` was never updated to say so -- this
   closes that stale-metadata gap using the URL already in the queue
   file, not a new one. (3 more of the original 26 hand-checked-correct
   finds -- Davidson NC, Venus TX, Greencastle IN -- already carried the
   correct `video-no-captions-queued`/`queued=true` state from an
   earlier WO and are NOT re-applied here, since there is nothing to
   change. 1 more, New Boston NH, is excluded entirely: its newest
   candidate's own HLS media 404s on a live re-probe, so nothing was
   queued or applied for it -- see the BACKLOG_DONE entry.)
3. **1 wrong-domain-mapping row** (Melvern city, KS) -- `verify_hub()`'s
   walk found a real video, but hand-checking its own AgendaCenter row
   title ("Osage County Commission Meeting") against the candidate's own
   hub URL (`ks-osagecounty.civicplus.com`, Osage County's own CivicPlus
   tenant, not Melvern's) showed the underlying WO-338 population row had
   Melvern's domain tied to the COUNTY's tenant -- a real data error, not
   a shared-host ambiguity. Per CLAUDE.md's "Kind A" rule: not keyed to
   Melvern; the real owner body (Osage County, KS, `us:county:20139`) is
   recorded separately in `research/wo345_owner_bodies.csv`, and
   Melvern's own row gets `reject_reason=wrong-domain-mapping` here.

**Cochise County, AZ's YouTube lead (tier 2, hand-checked correct --
"Regular Board of Health Meeting Agenda" genuinely belongs to the
county) is NOT applied here** -- same "youtube_lead rows go to
`youtube_channel_leads.csv` only, never `jc.csv`" pattern WO-338's own
apply script (and `scripts/wo320_targeted.py`'s `record_youtube_lead()`)
already establish; this WO calls that same helper directly rather than
duplicating the write.

**The other 50 rows of the 108-row population are left alone on
purpose** -- the walk came back empty again on a platform/URL this
rerun's own code changes (WO-344) didn't touch (civicplus 38, civicclerk
9, iqm2 2, townhallstreams 1) -- a failed re-check is not evidence the
earlier finding was wrong, the same standing guard WO-338's own apply
script documents.

Follows ENUMERATION_METHODS.md §158's write protocol exactly (same
reference implementation as wo191_apply_to_jc.py / wo338_apply_to_jc.py):
a real `flock` around the whole read-modify-write, a fresh read taken
only after the lock is held, a row-count floor re-derived from `git show
HEAD` at run time, an atomic temp-file + os.replace() write with explicit
LF endings, and a line-based in-place edit (index built only for O(1)
lookup into the already-read row list -- never a gov_id-keyed dict
rebuild, which drops any row with a blank/duplicate gov_id).

Also writes `research/wo345_jc_applied_gov_ids.txt` -- one gov_id per
line, one per row actually changed.

Usage:
    python3 scripts/wo345_apply_to_jc.py
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
APPLIED_GOV_IDS_TXT = ROOT / "wo345_jc_applied_gov_ids.txt"
RTR_BUSINESS_ROOT = ROOT.parent

FALLBACK_MIN_SANE_ROW_COUNT = 30000

# --- Bucket 1: tier-4, meeting found, no video ---------------------------
TIER4_GOV_IDS = [
    "us:place:2573405",  # Watertown city, MA
    "us:place:3956966",  # North Ridgeville city, OH
    "us:place:2862520",  # Ridgeland city, MS
    "us:place:3126385",  # La Vista city, NE
    "us:county:53001",  # Adams County, WA
    "ca:csd:5919021",  # Ladysmith, BC
    "us:county:51169",  # Scott County, VA
    "us:county:35035",  # Otero County, NM
    "us:county:06105",  # Trinity County, CA
    "us:county:13133",  # Greene County, GA
    "ca:csd:3512030",  # Tweed, ON
    "us:place:2060825",  # Roeland Park city, KS
    "us:county:13049",  # Charlton County, GA
    "us:county:13131",  # Grady County, GA
    "us:county:27101",  # Murray County, MN
    "us:county:13035",  # Butts County, GA
    "us:county:08055",  # Huerfano County, CO
    "us:place:5456020",  # Moundsville city, WV
    "us:place:5587200",  # Williams Bay village, WI
    "us:place:5541300",  # Lake Delton village, WI
    "us:place:5310565",  # Castle Rock city, WA
    "us:cousub:2500549970",  # Norton town, MA
    "us:county:40125",  # Pottawatomie County, OK
    "us:place:5365765",  # South Cle Elum town, WA
    "us:cousub:0915009190",  # Brooklyn town, CT
    "us:place:3851900",  # Medora city, ND
    "us:cousub:2609936820",  # Harrison charter township, MI
    "us:cousub:3608715968",  # Clarkstown town, NY
    "us:cousub:3608760510",  # Ramapo town, NY
    "us:cousub:0914014160",  # Cheshire town, CT
]

# --- Bucket 2: tier-3, real video, no reachable captions -> queued -------
# gov_id -> example_meeting_url (the URL actually sitting in
# scripts/tier3_auto_transcription_queue.txt for this government -- a
# freshly-probed one for the 9 this WO added, or the already-existing
# one for the 13 this WO found already queued but never reflected here).
TIER3_QUEUED = {
    # 9 new this WO:
    "us:county:27035": (
        "http://www.crowwingcountymn.iqm2.com/Citizens/Detail_Meeting.aspx?ID=21876"
    ),  # Crow Wing County, MN
    "us:cousub:5000764300": (
        "https://drive.google.com/file/d/1h7Pfp4UKVEGE5UV36IQQLr0oqjzrlmOa/view?usp=sharing"
    ),  # Shelburne town, VT
    "us:place:4879624": (
        "https://wimberleytx.portal.civicclerk.com/event/1510/media"
    ),  # Wimberley city, TX
    "us:cousub:2303136745": (
        "https://townhallstreams.com/stream.php?location_id=57&id=76598"
    ),  # Kennebunkport town, ME
    "us:cousub:2502160785": (
        "https://tv.sharontv.com/internetchannel/show/15269"
    ),  # Sharon town, MA
    "us:cousub:3301108100": (
        "https://townhallstreams.com/stream.php?location_id=54&id=76609"
    ),  # Brookline town, NH
    "us:cousub:3301137940": (
        "https://www.hudsonctv.com/internetchannel/show/20916?site=3"
    ),  # Hudson town, NH
    "us:cousub:3608365013": (
        "https://townhallstreams.com/stream.php?location_id=33&id=73862"
    ),  # Sand Lake town, NY
    "us:cousub:3605953000": (
        "https://northhempsteadny.portal.civicclerk.com/event/2364/media"
    ),  # North Hempstead town, NY
    # 13 already in the tracked queue from an earlier WO -- jc.csv never
    # reflected it until now:
    "us:cousub:2303187985": (
        "https://townhallstreams.com/stream.php?location_id=77&id=75043"
    ),  # York town, ME
    "us:place:3144245": (
        "https://scottsbluffne.portal.civicclerk.com/event/951/media"
    ),  # Scottsbluff city, NE
    "us:place:2466000": (
        "https://townhallstreams.com/stream.php?location_id=177&id=75919"
    ),  # Ridgely town, MD
    "us:cousub:2302766635": (
        "https://townhallstreams.com/stream.php?location_id=175&id=76135"
    ),  # Searsport town, ME
    "us:cousub:2301376365": (
        "https://townhallstreams.com/stream.php?location_id=141&id=76028"
    ),  # Thomaston town, ME
    "us:cousub:2303167475": (
        "https://townhallstreams.com/stream.php?location_id=148&id=75896"
    ),  # Shapleigh town, ME
    "us:cousub:3300582660": (
        "https://townhallstreams.com/stream.php?location_id=176&id=76043"
    ),  # Westmoreland town, NH
    "us:cousub:3301185220": (
        "https://townhallstreams.com/stream.php?location_id=100&id=74869"
    ),  # Wilton town, NH
    "us:cousub:3300761780": (
        "https://townhallstreams.com/stream.php?location_id=151&id=75888"
    ),  # Pittsburg town, NH
    "us:cousub:3301306980": (
        "https://townhallstreams.com/stream.php?location_id=110&id=76127"
    ),  # Bradford town, NH
    "us:cousub:3402938550": (
        "https://townhallstreams.com/stream.php?location_id=88&id=75491"
    ),  # Lakewood township, NJ
    "us:cousub:3608371102": (
        "https://townhallstreams.com/stream.php?location_id=150&id=73956"
    ),  # Stephentown town, NY
    "us:cousub:3602150452": (
        "https://townhallstreams.com/stream.php?location_id=138&id=76117"
    ),  # New Lebanon town, NY
}

# --- Bucket 3: wrong-domain-mapping (Kind A shared-tenant mis-key) -------
WRONG_DOMAIN_MAPPING_GOV_IDS = [
    "us:place:2045700",  # Melvern city, KS
]


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
    for gov_id in TIER4_GOV_IDS:
        findings.append({"gov_id": gov_id, "reject_reason": "meeting-without-video"})
    for gov_id, url in TIER3_QUEUED.items():
        findings.append(
            {
                "gov_id": gov_id,
                "reject_reason": "video-no-captions-queued",
                "queued": "true",
                "example_meeting_url": url,
            }
        )
    for gov_id in WRONG_DOMAIN_MAPPING_GOV_IDS:
        findings.append({"gov_id": gov_id, "reject_reason": "wrong-domain-mapping"})
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
