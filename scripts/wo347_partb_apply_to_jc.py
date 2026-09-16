#!/usr/bin/env python3
"""Applies WO-347 Part B's audit findings onto `jurisdiction_coverage.csv`.

Part B hand-read a stratified 60-government sample (research/
wo347_audit_sample.csv) of the passive pipeline's own recorded verdicts,
using the real access ladder (scripts/wo147_access_ladder_sweep.py's
run_access_ladder(): plain -> browser headers -> headless) against each
government's OWN website -- never a youtube.com/youtu.be URL.

**16 real false-negative meeting pages found** -- a real, live
agendas/minutes page exists (confirmed by direct fetch: real dated PDF
agendas, a real CivicPlus/CivicWeb/CivicClerk/IQM2 listing, or a first-
party page) where `jurisdiction_coverage.csv` currently says no meeting
was found at all (`no-meeting-nor-video`/`no-platform-link-found`).
Applied: `reject_reason=meeting-without-video`, `example_meeting_url` set
to the real page found. Six more governments in the sample (fernie.ca,
centralvalleytownut.com, hinckleytown.org, woodruff.utah.gov,
lowersaucontownship.org, eatwp.org) turned out to ALREADY carry
`meeting-without-video` in the live file -- a different, concurrent WO
this week already caught and fixed those; not re-applied here (nothing
to change).

**1 real false-negative video** -- Upper Providence township, PA
(`us:cousub:4204579248`), queued via `scripts/wo347_finish_partb.py`
(see that script's own docstring for the CivicClerk-jurisdiction-field
postal-address quirk and the Swagit-adapter confirmation). Applied:
`reject_reason=video-no-captions-queued`, `queued=true`,
`example_meeting_url` set to the queued Swagit page.

**6 wrong-domain findings are deliberately NOT applied here** (Ryan's
"never delete or blank a domain" rule, and three of the six have no
confirmed better domain to record yet) -- see
`research/wo347_wrong_domain_findings.csv` and this WO's `BACKLOG.md`
entry for the follow-up.

Follows ENUMERATION_METHODS.md §158's write protocol exactly (same
reference implementation as wo347_apply_to_jc.py / wo345_apply_to_jc.py):
a real `flock` around the whole read-modify-write, a fresh read taken
only after the lock is held, a row-count floor re-derived from `git show
HEAD` at run time, an atomic temp-file + os.replace() write with explicit
LF endings, and a line-based in-place edit into the already-read row
list.

Appends to `research/wo347_jc_applied_gov_ids.txt` (the same file Part A
wrote to) -- one gov_id per line, one per row actually changed.

Usage:
    python3 scripts/wo347_partb_apply_to_jc.py
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

# --- 16 real false-negative meeting pages found -----------------------
FALSE_NEG_MEETING_PAGE = {
    "us:place:4825752": (
        "https://ferris-texas.community.diligentoneplatform.com/Portal/"
        "MeetingSchedule.aspx"
    ),  # Ferris city, TX
    "ca:csd:4811009": "https://www.silverbeach.ca/council/minutes",  # Silver Beach, AB
    "ca:csd:4811020": "https://www.sundancebeach.ca/council/minutes",  # Sundance Beach, AB
    "us:cousub:0918055500": (
        "https://www.northstoningtonct.gov/agendacenter"
    ),  # North Stonington town, CT
    "us:cousub:3402359280": (
        "https://www.plainsboronj.com/AgendaCenter"
    ),  # Plainsboro township, NJ
    "us:place:4219784": (
        "https://doylestownpa.iqm2.com/Citizens/default.aspx"
    ),  # Doylestown borough, PA
    "us:cousub:4207932416": (
        "https://hanovertownship.org/meetings.html"
    ),  # Hanover township, PA
    "us:cousub:4207123840": "https://ephratatownship.org/index.php",  # Ephrata township, PA
    "us:cousub:4205571912": (
        "https://www.southamptontownship.org/information/meeting-minutes/"
    ),  # Southampton township, PA
    "us:cousub:3915742182": (
        "https://www.lawrencetownship.org/zoning/zoning-minutes/"
    ),  # Lawrence township, OH
    "us:place:5125408": (
        "https://elktonva.gov/government/council/agendas,_meetings,_and_minutes/index.php"
    ),  # Elkton town, VA
    "us:place:2015075": (
        "https://columbusks.gov/city-administrator/agendas-and-minutes/"
    ),  # Columbus city, KS
    "us:place:2655100": (
        "https://cityofmontague.org/about/city-council-boards-commissions/"
    ),  # Montague city, MI
    "us:place:2607860": (
        "https://www.villageofberriensprings.com/agendas-minutes/"
    ),  # Berrien Springs village, MI
    "us:cousub:4204385232": "https://wmstwp.org/minutes.php",  # Williams township, PA
    "us:cousub:3608958266": (
        "https://www.townofpitcairn.com/meeting-agendas.html"
    ),  # Pitcairn town, NY
}

# --- 1 real false-negative video, queued -------------------------------
FALSE_NEG_VIDEO_QUEUED = {
    "us:cousub:4204579248": (
        "https://uprovmontco.new.swagit.com/videos/399867"
    ),  # Upper Providence township, PA
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
    for gov_id, url in FALSE_NEG_MEETING_PAGE.items():
        findings.append(
            {
                "gov_id": gov_id,
                "reject_reason": "meeting-without-video",
                "example_meeting_url": url,
            }
        )
    for gov_id, url in FALSE_NEG_VIDEO_QUEUED.items():
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
        skipped_already_correct = 0
        missing: list[str] = []
        applied_gov_ids: list[str] = []

        for finding in findings:
            gov_id = finding["gov_id"]
            idx = by_gov_id_first_index.get(gov_id)
            if idx is None:
                missing.append(gov_id)
                continue
            if jc_rows[idx].get("reject_reason") == finding["reject_reason"]:
                skipped_already_correct += 1
                continue
            jc_rows[idx]["reject_reason"] = finding["reject_reason"]
            if "queued" in finding:
                jc_rows[idx]["queued"] = finding["queued"]
            if "example_meeting_url" in finding:
                jc_rows[idx]["example_meeting_url"] = finding["example_meeting_url"]
            changed += 1
            applied_gov_ids.append(gov_id)

        print(
            f"{changed} rows updated, {skipped_already_correct} already correct "
            f"(fixed by a different concurrent WO), {len(missing)} gov_ids not found"
        )
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
