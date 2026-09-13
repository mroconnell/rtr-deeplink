#!/usr/bin/env python3
"""Applies WO-324's findings onto `jurisdiction_coverage.csv`.

WO-324 ran passive discovery v2 (WO-283's pipeline, most recently copied
from WO-321's own working set) against group 5 of the WO-320..325 split:
Canadian governments that only ever had the access ladder
(`research/passive_neither_5-canada-ladder-only.csv`, 493 rows).

Phase 1 (recon) ran against all 493. Mid-run, the conductor relayed a
finding from the parallel WO-323 run: this pipeline's hop-link/meeting
vocabulary is English-only (0 of 92 confirmed on Quebec sites whose own
navigation reads "Conseil municipal"/"Séances du conseil"), so phase 3
was stopped for the 258 Quebec rows in this population (107 never
reached it; 151 had already been swept before the instruction arrived
and found nothing, consistent with the same English-vocabulary bias, so
their negative result isn't trustworthy either). All 258 are recorded
`deferred-french-vocab` here, for WO-327's French-vocabulary rerun --
not a fresh finding, an honest "not measured by this method."

Of the 235 non-Quebec governments phase 3 actually swept, 51 came back
with a real, name-and-state-matched platform confirmation. Every one of
the 51 was then resolve()-verified for real content
(`scripts/wo324_resolve_diagnostic.py`, the same real `app/platforms/*`
pipeline `bulk_ingest.py` uses) before anything was applied here -- a
confirmed platform signature is not proof of a specific real meeting,
per this repo's own hand-check rule. 0 real videos: 48 resolved to a
real meeting/agenda page with no video, 2 more (both CivicPlus
AgendaCenter listings -- Corman Park No. 344 SK, Stettler County No. 6
AB) raised `NoVideoCandidateFound` from the adapter itself, the same
real "no video" outcome via a different code path. All 50 are
`meeting-without-video`.

**1 real YouTube-embed catch, left untouched.** Claresholm, AB's
confirmed page (a real CivicWeb-fingerprinted council-meetings page)
embeds a youtube.com video directly. Per the conductor's mid-run
instruction (added after WO-323's own verification pass fetched real
YouTube captions once through a Tweed ON page), this WO's
`resolve_diagnostic.py` pre-screens every confirmed candidate's HTML for
a youtube.com/youtu.be link BEFORE calling `resolve()` -- Claresholm hit
that screen, was recorded to `youtube_channel_leads.csv` instead
(verified=false, for a later drip-Mac pass), and was never resolve()'d.
Its `jurisdiction_coverage.csv` row is left exactly as it already stood;
no reject_reason is written for it here.

184 of the 235 swept non-Quebec governments confirmed no real platform.
7 never resolved in DNS, 1 sits behind the govAccess/Akamai WAF block,
20 were blocked at the plain-HTTP rung and 3 more at the browser-header
rung (both access-class; a site that never answered isn't a content
verdict), 15 hit a real Cloudflare challenge gate, and the remaining 138
answered normally in phase 1 but phase 3 (candidate scoring or the
fallback ladder) found no real, name-matched platform on them --
`no-platform-link-found`.

**A real bug found and worked around, not fixed at its source.**
`wo273_recon.py`'s `registrable_label()` (shared by every WO-27x/28x/32x
sweep script that copies this recon step) takes a domain's second-to-
last label as the "government slug" to guess a shared-vendor tenant host
from (`{label}.primegov.com`, `{label}.civicweb.net`). For a Canadian
`*.qc.ca` domain that label is literally `qc` (Quebec's own province
code), not the government's name -- and `qc.primegov.com` genuinely
resolves, to PrimeGov's own regional "OneMeeting Quebec" landing page,
not any one government's tenant. This produced a false `platform=
primegov, confidence=high` on up to 70 Quebec rows in
`wo324_classified.csv`. It never reached a real HTTP fetch (phase 3
scores off real ranked candidate URLs, never off this bare DNS-guess
string) and it never reached this file, since every Quebec row is
`deferred-french-vocab` regardless of what phase 2 classified -- but the
bug is real, reproducible, and will corrupt any other Canadian
`*.qc.ca`/`*.on.ca`/etc. sweep that reuses `wo273_recon.py` unpatched.
Filed to `BACKLOG.md`, not fixed here (out of this WO's scope -- the
shared script is used by sibling WOs already in flight).

**No `already-covered`-with-no-page rows existed in this group's 493
population** (caution 3 in the brief) -- no `already-covered-other-id`
findings to report. **No vendor-tenant-host domain rows** (caution 1;
11 of 493 had an eScribe/IQM2 host as their own `domain`) needed special
handling beyond what `wo324_classify.py`'s existing domain-is-tenant-
host bypass (carried from WO-321) already does.

**A WO-226-style guard applied on every write here**: 74 of the 493
rows already carried a real `example_meeting_url` or
`example_agenda_or_calendar_url` on file. None of this WO's outcomes
(including `deferred-french-vocab`) are allowed to overwrite a row that
already has real evidence -- an access-class or deferral finding must
never downgrade a row a previous, real look already recorded content
for. Those rows are left untouched and counted separately below.

Follows ENUMERATION_METHODS.md §158's write protocol exactly (same
reference implementation as wo191_apply_to_jc.py / wo321_apply_to_jc.py):
a real `flock` around the whole read-modify-write, a fresh read taken
only after the lock is held, a row-count floor re-derived from `git show
HEAD` at run time, an atomic temp-file + os.replace() write with explicit
LF endings, and a line-based in-place edit (index built only for O(1)
lookup into the already-read row list -- never a gov_id-keyed dict
rebuild, which drops any row with a blank/duplicate gov_id).

Per the 2026-09-12 tightened rule, this script WRITES the file but never
COMMITS it -- the conductor commits with explicit paths.

Usage:
    python3 scripts/wo324_apply_to_jc.py
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
REPORT_CSV = ROOT / "wo324_report.csv"

FALLBACK_MIN_SANE_ROW_COUNT = 30000

# Claresholm, AB -- real YouTube embed caught by the pre-screen guard,
# never resolve()'d, left untouched on purpose. See this file's own
# docstring.
SKIP_GOV_IDS = {"ca:csd:4803022"}


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
    with open(REPORT_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    findings = []
    for r in rows:
        gov_id = r.get("gov_id", "")
        outcome = r.get("outcome", "")
        if not gov_id or gov_id in SKIP_GOV_IDS or outcome == "PENDING_YOUTUBE_LEAD":
            continue
        findings.append(
            {
                "gov_id": gov_id,
                "reject_reason": outcome,
                "evidence_url": r.get("evidence_url", ""),
            }
        )
    return findings


def has_real_evidence(jc_row: dict) -> bool:
    return bool(
        (jc_row.get("example_meeting_url") or "").strip()
        or (jc_row.get("example_agenda_or_calendar_url") or "").strip()
    )


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
        skipped_real_evidence = 0
        missing: list[str] = []

        for finding in findings:
            idx = by_gov_id_first_index.get(finding["gov_id"])
            if idx is None:
                missing.append(finding["gov_id"])
                continue
            jc_row = jc_rows[idx]
            if has_real_evidence(jc_row):
                skipped_real_evidence += 1
                continue
            jc_row["reject_reason"] = finding["reject_reason"]
            if (
                finding["reject_reason"] == "meeting-without-video"
                and finding["evidence_url"]
                and not (jc_row.get("example_agenda_or_calendar_url") or "").strip()
            ):
                jc_row["example_agenda_or_calendar_url"] = finding["evidence_url"]
            changed += 1

        print(
            f"{changed} rows updated, {skipped_real_evidence} skipped (already had "
            f"real evidence on file), {len(missing)} gov_ids not found in the file"
        )
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
