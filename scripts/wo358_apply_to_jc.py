#!/usr/bin/env python3
"""Applies WO-358's findings onto `jurisdiction_coverage.csv`.

WO-358 ran the 136-government (re-derived from BACKLOG.md's 148 --
see this WO's BACKLOG_DONE entry) "stale label" bucket -- CivicClerk/
eScribe/iQM2/Town Hall Streams governments whose registry row names the
platform but had no confirmed tenant URL on file -- through
`verify_hub()` starting from each government's own `hub_url` (a
first-party agenda page, when on file) or bare domain homepage, using
the module's own "unknown hub" one-hop-deeper fallback
(`research/wo358_verify.csv`), then hand-checked every tier-1/tier-3
candidate a second time (`research/wo358_handcheck.csv`) before queuing.

Per-government mapping:
  - 6 tier-3 governments queued (video, no captions, hand-checked real
    and current; 3 were initially auto-deferred by the shared
    `finish_candidate()` helper's 90-minute duration gate and moved to
    the queue by hand per Ryan's 2026-09-13 evening standing rule --
    "over 90 minutes is QUEUED, never parked, the deferred file is only
    for WO-266-style government-level parking") -> queued=True,
    reject_reason=video-no-captions-queued, example_meeting_url set.
  - 2 tier-3 governments (real, hand-confirmed video the automated
    duration prober can't read -- a Cablecast "show" landing page, a
    Zoom cloud-recording share link) -> reject_reason=rejected-by-probe.
  - 1 tier-3 government (Godley city, TX) -> a DIFFERENT meeting from
    the same government was already queued under an earlier WO;
    `finish_candidate()`'s own "a deferred/queued line stays out"
    guard correctly declined a second meeting for one government ->
    reject_reason=duplicate-queued (queued=True already reflects the
    other meeting).
  - Every tier-2 (YouTube lead) candidate -> left alone (recorded in
    `research/youtube_channel_leads.csv` instead, never fetched).
  - 64 tier-4 governments (a real meeting/listing found, no video) ->
    reject_reason=meeting-without-video.
  - 8 governments where the walk found nothing at all
    (`resolved_empty`) -> reject_reason=no-meetings-found.
  - 49 governments where the walk itself errored (`resolve_error`/
    `fetch_failed`) or had no domain on file -> left alone (an error is
    not a finding; see BACKLOG.md).

WO-226 restated-not-replaced guard: `meeting-without-video` and
`no-meetings-found` (this run's two weaker/re-derivable findings) never
overwrite an existing STRONGER reason -- except
`meeting-without-video-unverified` (WO-351), explicitly excluded from
that stronger set: any fresh verdict from this run replaces it outright.
Also never downgrades a row that already carries `transcribed=True`.

Follows ENUMERATION_METHODS.md §158's write protocol exactly: a real
`flock` held around the whole read-modify-write, a fresh read taken only
after the lock is acquired, a row-count floor re-derived from
`git show HEAD` at run time, a re-check immediately before writing, and
an atomic temp-file + `os.replace()` write with explicit LF endings,
line-based in-place edit only (never a gov_id-keyed dict rebuild).

Also writes `research/wo358_jc_applied_gov_ids.txt` (one gov_id per
line).

Usage:
    python3 scripts/wo358_apply_to_jc.py
"""

from __future__ import annotations

import csv
import os
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
VERIFY_CSV = ROOT / "wo358_verify.csv"
APPLIED_GOV_IDS_TXT = ROOT / "wo358_jc_applied_gov_ids.txt"

FALLBACK_MIN_SANE_ROW_COUNT = 30000

# --- hand-check outcomes (see this script's own docstring) ---

TIER3_QUEUED = {
    "us:place:4875236",  # Venus town, TX
    "us:place:1829358",  # Greencastle city, IN
    "us:place:4866416",  # Seadrift city, TX
    "us:place:4858280",  # Pleasanton city, TX
    "us:county:23023",  # Sagadahoc County, ME
    "us:cousub:3608357441",  # Petersburgh town, NY
}
TIER3_REJECTED_BY_PROBE = {
    "us:place:2720078",  # Excelsior city, MN
    "us:cousub:2502109175",  # Brookline town, MA
}
TIER3_DUPLICATE_QUEUED = {"us:place:4829972"}  # Godley city, TX

INGEST_URL = {
    "us:place:4875236": "https://venustx.portal.civicclerk.com/event/361/media",
    "us:place:1829358": "https://greencastlein.portal.civicclerk.com/event/1699/media",
    "us:place:4866416": "https://seadrifttx.portal.civicclerk.com/event/21/files",
    "us:place:4858280": "http://pleasantontx.iqm2.com/Citizens/Detail_Meeting.aspx?ID=1372",
    "us:county:23023": "https://townhallstreams.com/stream.php?location_id=154&id=76623",
    "us:cousub:3608357441": "https://townhallstreams.com/stream.php?location_id=152&id=76437",
}

# Guarded: never let these two weaker findings overwrite a stronger
# existing reason. "meeting-without-video-unverified" (WO-351) is
# deliberately excluded -- always replaceable, per the conductor.
STRONGER_EXISTING_REASONS = {
    "meeting-without-video",
    "no-meeting-nor-video",
    "no-video-found",
    "video-without-meeting",
    "off-mission",
    "video-no-captions-queued",
    "wrong-domain-mapping",
    "rejected-by-probe",
    "duplicate-queued",
}
WEAK_NEW_REASONS = {"meeting-without-video", "no-meetings-found"}


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


def load_findings() -> dict[str, str]:
    """gov_id -> reject_reason for every row this script will TOUCH.
    A gov_id absent from this dict is left completely alone."""
    findings: dict[str, str] = {}
    with open(VERIFY_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for r in rows:
        gid = r.get("gov_id", "")
        tier = r.get("tier", "")
        verdict = r.get("verdict", "")
        if not gid:
            continue

        if gid in TIER3_QUEUED:
            findings[gid] = "__QUEUED__"
        elif gid in TIER3_REJECTED_BY_PROBE:
            findings[gid] = "rejected-by-probe"
        elif gid in TIER3_DUPLICATE_QUEUED:
            findings[gid] = "duplicate-queued"
        elif tier == "2":
            continue  # every YouTube lead: left alone, recorded as a lead instead
        elif tier == "4":
            findings[gid] = "meeting-without-video"
        elif tier == "" and verdict == "resolved_empty":
            findings[gid] = "no-meetings-found"
        elif tier == "" and verdict in ("resolve_error", "fetch_failed", "no_domain"):
            continue  # an error is not a finding
        else:
            print(f"UNHANDLED row, left alone: {gid} tier={tier!r} verdict={verdict!r}")

    return findings


def main() -> None:
    findings = load_findings()
    print(f"{len(findings)} governments to apply")

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
        skipped_transcribed = 0
        missing: list[str] = []
        applied_gov_ids: list[str] = []

        for gov_id, action in findings.items():
            idx = by_gov_id_first_index.get(gov_id)
            if idx is None:
                missing.append(gov_id)
                continue
            jc_row = jc_rows[idx]
            current_reason = (jc_row.get("reject_reason") or "").strip()
            already_transcribed = (jc_row.get("transcribed") or "").strip().lower() in (
                "true",
                "1",
            )

            if action == "__QUEUED__":
                if already_transcribed:
                    skipped_transcribed += 1
                    continue
                jc_row["queued"] = "True"
                jc_row["reject_reason"] = "video-no-captions-queued"
                jc_row["example_meeting_url"] = INGEST_URL.get(
                    gov_id, jc_row.get("example_meeting_url", "")
                )
                changed += 1
                applied_gov_ids.append(gov_id)
                continue

            # Plain reject_reason value.
            new_reason = action
            if already_transcribed:
                skipped_transcribed += 1
                continue
            if (
                new_reason in WEAK_NEW_REASONS
                and current_reason in STRONGER_EXISTING_REASONS
            ):
                skipped_guard += 1
                continue
            jc_row["reject_reason"] = new_reason
            if new_reason == "duplicate-queued":
                jc_row["queued"] = "True"
            changed += 1
            applied_gov_ids.append(gov_id)

        # Re-check immediately before writing (per §158).
        with open(JC_PATH, newline="", encoding="utf-8") as f:
            recheck_count = sum(1 for _ in f) - 1
        if recheck_count != starting_row_count:
            raise SystemExit(
                f"{JC_PATH.name} changed from {starting_row_count} to {recheck_count} "
                "rows while this script was running -- another writer is active. "
                "Refusing to write; re-run."
            )

        tmp_path = JC_PATH.with_suffix(".csv.wo358tmp")
        with open(tmp_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=jc_fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(jc_rows)
        os.replace(tmp_path, JC_PATH)

        print(
            f"\nDone: {changed} changed, {skipped_guard} skipped (WO-226 guard), "
            f"{skipped_transcribed} skipped (already transcribed), "
            f"{len(missing)} no jc match. {len(jc_rows)} rows written "
            "(unchanged count, in-place edit only)."
        )
        if missing:
            print("no jc match:", missing[:20], "..." if len(missing) > 20 else "")
    finally:
        if fcntl:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()

    if applied_gov_ids:
        with APPLIED_GOV_IDS_TXT.open("a", encoding="utf-8") as f:
            for gid in applied_gov_ids:
                f.write(gid + "\n")


if __name__ == "__main__":
    main()
