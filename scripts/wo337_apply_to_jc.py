#!/usr/bin/env python3
"""Applies WO-337's findings onto `jurisdiction_coverage.csv`.

WO-337 ran passive discovery v2 (the WO-283/wo325 pipeline, phases 1-3,
copied to `scripts/wo337_*.py`) against group 7 of the "passive neither"
wave: 2,010 US municipalities/townships that only ever had the older
access-ladder sweeps and never a passive pass
(`research/passive_neither_7-us-muni-twp-ladder-only.csv`). Per the
WO-337/338 addendum, every phase-3 platform-confirmed candidate was then
run through the shared `verify_hub()` step (`app/platforms/
passive_verify.py`, WO-333) instead of a hand-built classification file
-- `research/wo337_verify.csv` is that step's real output.

**Real structural finding specific to this population, not present in
any sibling WO's population**: 6 `domain` values are shared by more than
one distinct government -- 54 different real West Virginia towns/cities
alone share the placeholder `local.wv.gov` (no per-government website on
file). Phase 1-3 correctly fetch each unique domain once; this WO's own
`wo337_build_report.py` fix (see its module docstring) fans that ONE
fetch back out to every government sharing the domain, but marks all but
the ONE government phase 1 actually recorded evidence for as
`shared_domain_primary=False` / `outcome=shared-domain-not-verified` --
there is no way to tell, from a shared placeholder domain's content,
which of 54 towns (if any) it is actually about. **Those 59 rows
(`outcome=shared-domain-not-verified`) are NOT applied here** -- nothing
is written for them, on purpose, since writing anything would be a guess
about a specific government this WO never actually confirmed. Left as
this WO's own honest residual for a human/later pass (see
`BACKLOG.md`'s new entry and this WO's `BACKLOG_DONE.md` entry).

**What the other 1,951 rows found**, via `research/wo337_report.csv`
(phase 1-3's own per-government outcome) and `research/wo337_verify.csv`
(the 38 platform-confirmed candidates' `verify_hub()` result):

  - 385 `dns-unresolvable` -- the domain on file never resolves.
  - 10 `blocked-waf-akamai-deferred` -- the same Akamai/govAccess WAF
    block reported by every sweep this week, not government-specific.
  - 369 `no-candidate` + 1,145 `candidate-not-confirmed` + 4
    `third-party-portal-guard` (a payment-portal page the guard
    correctly declined to treat as a real platform match) -- checked, no
    real platform confirmed for this specific government.
  - 38 `platform-confirmed`, all individually re-verified through
    `verify_hub()`: 22 came back tier 4 (a real meeting listing/page,
    genuinely no video -- `meeting-without-video`), 16 came back with no
    meeting found at all on a second, deeper look
    (`no-meeting-nor-video`). **Zero came back tier 1-3** -- no real
    video was found anywhere in this population's confirmed platforms.
    That's a real, honest finding for a population whose defining trait
    is "the older ladder's own success test was a vendor link, and every
    row here already failed that test once" -- not a code gap.

Every content-class finding from this run (`meeting-without-video`,
`no-meeting-nor-video`, `no-platform-link-found`) is applied even where
the current file already carries a weaker or equivalent one, since this
run re-verified against live data. An access-class finding
(`dns-unresolvable`, `blocked-waf-akamai`) is applied ONLY when the
current `reject_reason` is blank or itself access-class/
no-platform-link-found -- never over an existing stronger content-class
finding (`meeting-without-video`, `no-meeting-nor-video`, `no-video-found`,
`video-without-meeting`, `off-mission`), per WO-226's restated-not-replaced
guard: a transient DNS/WAF miss this run says nothing about a real
finding an earlier run already made. Checked directly against this
population: 0 of the 395 dns-unresolvable/blocked-waf-akamai rows here
currently carry one of those stronger reasons, so the guard changes
nothing in practice this run, but is applied on principle (and would
matter on a re-run).

Follows ENUMERATION_METHODS.md §158's write protocol exactly (same
reference implementation as `wo191_apply_to_jc.py` / `wo325_apply_to_jc.py`):
a real `flock` around the whole read-modify-write (held continuously, so
the "re-read before writing" check only ever needs to catch a
misbehaving script that skipped the lock, not a real race against a
cooperating one), a fresh read taken only after the lock is held, a row
count floor re-derived from `git show HEAD` at run time, an atomic
temp-file + os.replace() write with explicit LF endings, and a
line-based in-place edit (index built only for O(1) lookup into the
already-read row list -- never a gov_id-keyed dict rebuild, which drops
any row with a blank/duplicate gov_id).

Also writes `research/wo337_jc_applied_gov_ids.txt` (one gov_id per
line, append mode) so a concurrent WO (WO-336, WO-338) and the conductor
can see exactly which rows this WO touched, per the conductor's own
instruction mid-run.

Usage:
    python3 scripts/wo337_apply_to_jc.py
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
REPORT_CSV = ROOT / "wo337_report.csv"
VERIFY_CSV = ROOT / "wo337_verify.csv"
APPLIED_GOV_IDS_TXT = ROOT / "wo337_jc_applied_gov_ids.txt"

FALLBACK_MIN_SANE_ROW_COUNT = 30000

# Access-class reasons this run can produce -- never allowed to
# overwrite an existing stronger content-class finding (WO-226 guard).
ACCESS_CLASS_REASONS = {"dns-unresolvable", "blocked-waf-akamai"}
# "no-platform-link-found" is content-class in the §23 taxonomy but is
# the WEAKEST content-class finding (checked, nothing there) -- also
# guarded the same way as access-class, so a fresh "checked, nothing"
# never overwrites an existing "checked, found a real meeting/listing".
WEAK_CONTENT_REASONS = {"no-platform-link-found"}
STRONGER_EXISTING_REASONS = {
    "meeting-without-video",
    "no-meeting-nor-video",
    "no-video-found",
    "video-without-meeting",
    "off-mission",
}

REPORT_OUTCOME_TO_REASON = {
    "dns-unresolvable": "dns-unresolvable",
    "blocked-waf-akamai-deferred": "blocked-waf-akamai",
    "no-candidate": "no-platform-link-found",
    "candidate-not-confirmed": "no-platform-link-found",
    "third-party-portal-guard": "no-platform-link-found",
}

# Not applied at all -- see this file's own module docstring.
SKIP_OUTCOMES = {
    "shared-domain-not-verified",
    "platform-confirmed",
    "not-yet-processed",
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
    findings: dict[str, str] = {}

    with open(REPORT_CSV, newline="", encoding="utf-8") as f:
        report_rows = list(csv.DictReader(f))
    for r in report_rows:
        gov_id = r.get("gov_id", "")
        outcome = r.get("outcome", "")
        if not gov_id or outcome in SKIP_OUTCOMES:
            continue
        reason = REPORT_OUTCOME_TO_REASON.get(outcome)
        if reason:
            findings[gov_id] = reason

    with open(VERIFY_CSV, newline="", encoding="utf-8") as f:
        verify_rows = list(csv.DictReader(f))
    for r in verify_rows:
        gov_id = r.get("gov_id", "")
        reason = r.get("reject_reason", "")
        tier = r.get("tier", "")
        if not gov_id:
            continue
        if tier in ("1", "2", "3"):
            # A real video-bearing candidate -- never reached in this
            # run (0 of 38), but if it ever is, this script must NOT
            # silently record a reject reason for it; the hand-read gate
            # and ingest/queue path handle it, not this apply step.
            continue
        if reason:
            findings[gov_id] = reason

    return [
        {"gov_id": gid, "reject_reason": reason} for gid, reason in findings.items()
    ]


def main() -> None:
    findings = load_findings()
    print(f"{len(findings)} candidate rows to apply")

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
        skipped_guard = 0
        missing: list[str] = []
        applied_gov_ids: list[str] = []

        for finding in findings:
            gov_id = finding["gov_id"]
            new_reason = finding["reject_reason"]
            idx = by_gov_id_first_index.get(gov_id)
            if idx is None:
                missing.append(gov_id)
                continue

            current_reason = (jc_rows[idx].get("reject_reason") or "").strip()
            is_weak_new = (
                new_reason in ACCESS_CLASS_REASONS or new_reason in WEAK_CONTENT_REASONS
            )
            if is_weak_new and current_reason in STRONGER_EXISTING_REASONS:
                skipped_guard += 1
                continue

            jc_rows[idx]["reject_reason"] = new_reason
            changed += 1
            applied_gov_ids.append(gov_id)

        print(
            f"{changed} rows updated, {skipped_guard} skipped (WO-226 guard: "
            f"existing stronger content-class finding kept), "
            f"{len(missing)} gov_ids not found in the file"
        )
        if missing:
            print("missing gov_ids:", missing[:20])

        # Re-read immediately before writing, per §158 -- refuse a stale
        # write if another session's apply landed since we opened the
        # file. Held under the SAME continuous flock as the read above,
        # so this only ever catches a script that skipped the lock.
        with open(JC_PATH, newline="", encoding="utf-8") as f:
            reread_rows = list(csv.DictReader(f))
        if len(reread_rows) != starting_row_count:
            raise SystemExit(
                f"row count changed between read ({starting_row_count}) and "
                f"write ({len(reread_rows)}) -- another session wrote in between "
                "without holding this file's lock. Re-run this script rather than "
                "overwrite that work."
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
