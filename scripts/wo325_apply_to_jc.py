#!/usr/bin/env python3
"""Applies WO-325's hand-verified findings onto `jurisdiction_coverage.csv`.

WO-325 ran passive discovery v2 (WO-283's pipeline) against group 6 of
the WO-320..325 wave: 658 US counties that only ever had the older
access-ladder sweeps (WO-147..264), never a passive pass
(`research/passive_neither_6-us-counties-ladder-only.csv`). 0 rows were
excluded before the sweep started -- checked directly, none of the 658
have a bare youtube.com/youtu.be `domain` (see
`wo325_split_population.py` in this WO's scratch dir).

All 658 rows completed phase 1 (reconnaissance) and phase 2 (offline
classification) cleanly -- no hang recurred (`BACKLOG.md`'s open
`wo321_recon.py` hang entry, on the same shared `wo273_recon.py`
machinery, did not reproduce on this population). Phase 3
(`scripts/wo325_targeted.py`) fetched and scored every row; 117 came
back with a real, name-and-state-matched platform confirmation.

Every one of the 117 was then resolve()-verified for real content
(`scripts/wo325_resolve_diagnostic.py`, the same real `app/platforms/*`
pipeline `bulk_ingest.py` uses) before anything was applied to this
file -- a confirmed platform signature is not proof of a specific real
meeting, per this repo's own hand-check rule:

  - **1 real video found, and it is NOT applied here.** Sheboygan
    County, WI (`us:county:55117`) resolved through Municode Meetings'
    documented YouTube-embed delegation
    (`app/platforms/municode_meetings.py`) to a real YouTube video with
    166 real caption segments. This WO's own absolute rule is "never
    fetch a youtube.com or youtu.be URL for any reason" -- the
    resolve()-verification step (the same one every WO in this family
    uses to hand-check a confirmed candidate) made that fetch through
    the adapter's own legitimate delegation, not through a URL this
    WO's own candidate-ranking/fetch code picked. See `BACKLOG.md`'s new
    entry and this WO's `BACKLOG_DONE.md` entry for the full incident
    writeup. Left OUT of `wo325_final_classification.csv` entirely
    (`HELD_FOR_HUMAN_GOV_IDS` below) -- Ryan decides whether to ingest
    it, given the real content already exists but was reached through a
    fetch this WO was told not to make.
  - **102 meeting-without-video**, applied below (103 real hand-checked
    "meeting, no video" verdicts minus 1, Bibb County GA / Macon-Bibb,
    which is a consolidated-government non-canonical row -- see the
    NO_OVERWRITE list below). 75 are CivicPlus's own listing-walk
    (`NoVideoCandidateFound` after checking the tenant's real recent
    postings, the same check `civicplus.py`'s `resolve()` always runs);
    26 are a real resolved meeting/agenda page with an empty video
    field; 1 (Jo Daviess County, IL) resolved to a live-meeting Zoom
    join link, not a saved recording -- nothing to queue; 1 (a
    CivicPlus AgendaCenter listing page) resolved as a multi-meeting
    calendar (`CalendarPageError`) rather than one specific meeting,
    same disposition WO-321 used for Scott County, IN.
  - **9 timeout** -- all CivicPlus AgendaCenter pages that resolved to a
    real platform in phase 3 but timed out on the deeper resolve()
    listing-walk check; access-class, worth a retry later.
  - **4 resolve-failed** -- 1 real adapter gap (SuiteOne can't parse a
    `#home`-fragment-only URL, `floydcoin.suiteonemedia.com`, Floyd
    County IN -- filed in `BACKLOG.md`) and 3 real HTTP errors
    (403/500) on the specific confirmed candidate page at
    resolve()-check time (Jerome County ID, Linn County OR, Aiken
    County SC) -- none are content verdicts, all worth a retry.

13 rows in the population needed a hand-decision rather than a fresh
reject_reason, per the brief's caution 1 (a `domain` that is itself a
vendor tenant host) and `docs/COVERAGE_HANDOVER.md`'s
consolidated-government rule, all left untouched here (`NO_OVERWRITE_
GOV_IDS` below, checked directly against the live file before this WO
started):

  - `maconbibb.us` (`us:county:13021`, Bibb County GA) and `accgov.com`
    (`us:county:13059`, Clarke County GA) are both non-canonical rows in
    `app/utils/jurisdiction_data/consolidated_governments.csv` (Macon-
    Bibb and Athens-Clarke are both consolidated city-counties) -- a
    non-canonical row keeps `reject_reason=shared-gov-exception`, never
    a fresh sweep finding, even though this WO's own fresh resolve()
    found a real (unrelated, Board of Elections) page on `maconbibb.us`.
  - 10 more rows already carry `reject_reason=wrong-domain-mapping` on
    the live file (`merrimackcounty.net`, `douglascountyor.gov`,
    `washingtonfl.com`, `lincolncoclerkky.gov`, `scottcounty.com`,
    `perrycountyil.gov`, `co.taylor.wi.us`, `harrisoncountyia.org`,
    `fultoncoclerkky.gov`, `lincolncountyid.gov`) -- none of the 10 were
    confirmed by this WO's phase 3 (checked: 0 of the 10 appear in the
    117 confirmed rows), so nothing here contradicts the existing
    finding; restated, not replaced, per WO-226's guard against an
    access/no-signal result overwriting an already-correct
    content-class finding.

No `already-covered`-with-no-page rows existed in this group's 658
population (caution 3 in the brief).

395 governments genuinely had no confirmed platform at all after the
full ladder (`no-platform-link-found`); 106 more never got a real
content look because access itself was blocked (`blocked-plain-http`
85, `blocked-browser-headers` 21) or gated
(`cloudflare-challenge-blocked` 1) -- access-class reasons, worth a
later-rung retry, not a content verdict. 16 had a `domain` that never
resolved in DNS (`dns-unresolvable`); 12 sit behind the still-active
govAccess/Akamai WAF block (`blocked-waf-akamai`, recorded with their
CNAME evidence, not retried in a loop).

See `research/wo325_final_classification.csv` for the full per-
government breakdown (domain, gov_id, name, state, reason) this script
reads from, and this WO's `BACKLOG_DONE.md` entry for the full
disclosure.

Follows ENUMERATION_METHODS.md §158's write protocol exactly (same
reference implementation as wo191_apply_to_jc.py / wo283_apply_to_jc.py):
a real `flock` around the whole read-modify-write, a fresh read taken
only after the lock is held, a row-count floor re-derived from `git show
HEAD` at run time, an atomic temp-file + os.replace() write with explicit
LF endings, and a line-based in-place edit (index built only for O(1)
lookup into the already-read row list -- never a gov_id-keyed dict
rebuild, which drops any row with a blank/duplicate gov_id).

Usage:
    python3 scripts/wo325_apply_to_jc.py
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
FINAL_CLASSIFICATION_CSV = ROOT / "wo325_final_classification.csv"

FALLBACK_MIN_SANE_ROW_COUNT = 30000

# No phase-1 hang recurred on this population (unlike WO-321's Rankin
# County, MS) -- nothing to add here.
TIMEOUT_ROWS: list[dict] = []

# Left untouched on purpose -- see this file's own docstring. 2
# consolidated-government exceptions + 10 already-correct
# wrong-domain-mapping rows.
NO_OVERWRITE_GOV_IDS = {
    "us:county:13021",  # maconbibb.us -- shared-gov-exception
    "us:county:13059",  # accgov.com -- shared-gov-exception
    "us:county:33013",  # merrimackcounty.net -- wrong-domain-mapping
    "us:county:41019",  # douglascountyor.gov
    "us:county:12133",  # washingtonfl.com
    "us:county:21137",  # lincolncoclerkky.gov
    "us:county:47151",  # scottcounty.com
    "us:county:17145",  # perrycountyil.gov
    "us:county:55119",  # co.taylor.wi.us
    "us:county:19085",  # harrisoncountyia.org
    "us:county:21075",  # fultoncoclerkky.gov
    "us:county:16063",  # lincolncountyid.gov
}

# Held for a human decision -- see this file's own docstring. Not written
# to jurisdiction_coverage.csv at all (not even excluded via the
# NO_OVERWRITE mechanism above, since there IS no existing row to
# restate -- this is a fresh finding this WO is declining to apply).
HELD_FOR_HUMAN_GOV_IDS = {"us:county:55117"}  # Sheboygan County, WI


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
        gov_id = r.get("gov_id", "")
        if (
            not gov_id
            or gov_id in NO_OVERWRITE_GOV_IDS
            or gov_id in HELD_FOR_HUMAN_GOV_IDS
        ):
            continue
        findings.append({"gov_id": gov_id, "reject_reason": r["wo325_reject_reason"]})
    findings.extend(TIMEOUT_ROWS)
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

        for finding in findings:
            idx = by_gov_id_first_index.get(finding["gov_id"])
            if idx is None:
                missing.append(finding["gov_id"])
                continue
            jc_rows[idx]["reject_reason"] = finding["reject_reason"]
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
