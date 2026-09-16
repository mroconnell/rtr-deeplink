#!/usr/bin/env python3
"""Applies WO-321's hand-verified findings onto `jurisdiction_coverage.csv`.

WO-321 ran passive discovery v2 (WO-283's pipeline) against group 2 of
the WO-320..323 "received neither pass" split: US counties with a
domain and no transcribed meeting
(`research/passive_neither_2-us-counties.csv`, 223 rows). 3 rows were
excluded before the sweep even started -- their `domain` field is
itself a bare youtube.com/youtu.be host with no path, and this WO's
absolute rule is never to fetch a youtube.com/youtu.be URL for any
reason; there is no channel/video id left to recover from a bare host,
so these three are simply untouched here (see
`wo321_split_population.py` in this WO's scratch dir).

Of the 220 rows actually swept, 1 (Rankin County, MS) hung indefinitely
partway through phase 1 reconnaissance on a step that was never isolated
in the time this WO had -- its own website answers a plain `curl`
instantly, so the hang is somewhere else in the recon pipeline, not a
dead host. Recorded `reject_reason=timeout` (an access-class reason;
worth a fresh recon pass later) rather than left blank.

That leaves 219 governments phase 3 (`scripts/wo321_targeted.py`)
actually fetched and scored. 24 came back with a real, name-and-state-
matched platform confirmation. Every one of the 24 was then
resolve()-verified for real content
(`scripts/wo321_resolve_diagnostic.py`, the same real `app/platforms/*`
pipeline `bulk_ingest.py` uses) before anything was applied to this
file -- a confirmed platform signature is not proof of a specific real
meeting, per this repo's own hand-check rule:

  - **0 real videos found.** Every one of the 24 resolve()d to either a
    real meeting/agenda page with no video, or (Brunswick County, VA)
    to an unrelated FY27 budget spreadsheet document that happened to
    name the county and state -- not a meeting page at all, corrected
    to `no-platform-link-found` rather than recorded as a real find.
  - **23 meeting-without-video**, applied below. Two are worth naming
    since the resolve() result needed a second look before accepting
    it: Isle of Wight County, VA's confirmed candidate is a "Meeting
    Live Stream" page whose HLS playlist URL 404s right now -- a
    live-only stream, not a specific archived recording, so there is
    nothing to queue even though a `video_url` briefly appeared in the
    diagnostic; Scott County, IN's candidate is a CivicPlus AgendaCenter
    listing page that resolved as a multi-meeting calendar
    (`CalendarPageError`) rather than one specific meeting -- a real
    meeting hub, just not one this pass could pick a single video from.
    Otoro County, NM's confirmed page is a real meeting -- "Keep Otero
    County Beautiful Board" -- a sub-board of the county government,
    not a different government (no Kind A concern), just not the full
    Commission.

Two rows in the population needed a hand-decision rather than a fresh
reject_reason, per the WO-320..323 brief's caution 1 (a `domain` that is
itself a vendor tenant host) and `docs/COVERAGE_HANDOVER.md`'s
consolidated-government rule, both left untouched here:

  - `sanfrancisco.granicus.com` (us:county:06075) and
    `denver.granicus.com` (us:county:08031) are both non-canonical rows
    in `app/utils/jurisdiction_data/consolidated_governments.csv` (the
    place-level id is canonical for each) -- a non-canonical row keeps
    `reject_reason=shared-gov-exception`, never a fresh sweep finding.
  - `charlestonwv.portal.civicclerk.com`, filed against "Charleston
    County, South Carolina" (us:county:45019), is a West-Virginia-named
    tenant subdomain (Charleston is WV's capital; "wv" is the same
    state-abbreviation-suffix pattern this taxonomy's other
    wrong-domain-mapping cases already use) -- the row's existing
    `reject_reason=wrong-domain-mapping` and
    `alternate_domains=charlestoncounty.org` (the real Charleston
    County, SC domain) were already correct on inspection and are
    restated, not replaced.

No `already-covered`-with-no-page rows existed in this group's 223
population (caution 3 in the brief), so no `already-covered-other-id`
findings to report.

161 governments genuinely had no confirmed platform at all
(`no-platform-link-found`); 31 more never got a real content look
because phase 1's own homepage fetch was blocked
(`blocked-plain-http` 18, `blocked-browser-headers` 13) -- access-class
reasons, worth a later-rung retry, not a content verdict.

See `research/wo321_final_classification.csv` for the full per-
government breakdown (domain, gov_id, name, state, outcome, reason) this
script reads from, and this WO's `BACKLOG_DONE.md` entry for the full
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
    python3 scripts/wo321_apply_to_jc.py
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
FINAL_CLASSIFICATION_CSV = ROOT / "wo321_final_classification.csv"

FALLBACK_MIN_SANE_ROW_COUNT = 30000

# Rankin County, MS hung indefinitely in phase 1 recon (isolated to this
# one domain, reproduced twice, never diagnosed further within this WO's
# budget -- its own website answers a plain curl instantly, so this is
# not a dead host). Not in wo321_final_classification.csv since it never
# reached phase 2/3.
TIMEOUT_ROWS = [
    {"gov_id": "us:county:28121", "reject_reason": "timeout"},  # Rankin County, MS
]

# Left untouched on purpose -- see this file's own docstring.
NO_OVERWRITE_GOV_IDS = {"us:county:06075", "us:county:08031"}


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
        if not gov_id or gov_id in NO_OVERWRITE_GOV_IDS:
            continue
        findings.append({"gov_id": gov_id, "reject_reason": r["wo321_reject_reason"]})
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
