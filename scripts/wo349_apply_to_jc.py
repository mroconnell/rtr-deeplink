#!/usr/bin/env python3
"""Applies WO-349's findings onto `jurisdiction_coverage.csv`.

WO-349 ran the full CivicPlus open-government population (892 governments
with a confirmed tenant hub_url, `research/wo349_population.csv` bucket
A_confirmed_hub) through `verify_hub()` (`research/wo349_verify.csv`),
then hand-checked every tier1/tier3 candidate
(`research/wo349_handcheck.csv`) before ingesting/queuing.

Per-government mapping:
  - 8 tier-1 governments ingested (real video + real captions) ->
    shares_video=True, transcribed=True, example_meeting_url set,
    suspected_video_provider set, reject_reason cleared.
  - 1 tier-1 government (Seward city KS -- Kind A, its confirmed tenant
    is really Seward COUNTY's) -> reject_reason=wrong-domain-mapping.
  - 7 tier-3 governments queued (video, no captions, hand-checked real
    and current) -> queued=True, reject_reason=video-no-captions-queued.
  - 2 tier-3 governments deferred (same, but over the 90-minute cutoff)
    -> parked=True, reject_reason=video-no-captions-queued.
  - 3 tier-3 governments (real, hand-confirmed video that the automated
    duration prober can't read -- a Vimeo query-string shape, one
    apparently-corrupted CivicClerk file) -> reject_reason=rejected-by-probe.
  - 4 tier-3 governments (hand-check rejected a wrong/decorative video:
    3 identical `hellonation.com` site-builder placeholder videos, 1
    unrelated travel video) -> reject_reason=video-without-meeting.
  - 6 tier-3 governments (hand-check found the video's own title too
    ambiguous to confirm, or genuinely stale) -> left alone, NOT applied
    (see `BACKLOG.md`'s WO-349 entry -- these need a human call, not a
    guess).
  - 1 tier-2 candidate (Bossier Parish LA -- its whole confirmed hub is
    really Bossier City's own site) -> reject_reason=wrong-domain-mapping.
  - Every other tier-2 (YouTube lead) candidate -> left alone (recorded
    in `research/youtube_channel_leads.csv` instead, never fetched, per
    the standing no-YouTube-calls rule and WO-341's own precedent of not
    writing jc rows for unconfirmed leads).
  - 703 tier-4 governments (a real meeting/listing found, no video) ->
    reject_reason=meeting-without-video.
  - 91 governments where the walk found nothing at all (`empty_listing`/
    `resolved_empty`) -> reject_reason=no-meetings-found.
  - 22 governments where the walk itself errored (`resolve_error`/
    `fetch_failed`) -> left alone (an error is not a finding; see
    BACKLOG.md).

**WO-226 restated-not-replaced guard, with the WO-351 exception the
conductor gave mid-run**: `meeting-without-video` and `no-meetings-found`
(this run's two weaker/re-derivable findings) never overwrite an
existing STRONGER reason (`video-no-captions-queued`,
`wrong-domain-mapping`, `video-without-meeting`, `off-mission`,
`no-video-found`) -- except `meeting-without-video-unverified` (WO-351,
landed under this WO), which is explicitly EXCLUDED from that stronger
set on the conductor's instruction: it is an old, never-re-verified
verdict, not a stronger finding, so any fresh verdict from this run
(including the plain `meeting-without-video`) replaces it outright.
Also never downgrades a row that already carries `transcribed=True`.

Follows ENUMERATION_METHODS.md §158's write protocol exactly (same
reference implementation as `wo191_apply_to_jc.py` / `wo337_apply_to_jc.py`
/ `wo341_apply_to_jc.py`): a real `flock` held around the whole
read-modify-write, a fresh read taken only after the lock is acquired, a
row-count floor re-derived from `git show HEAD` at run time, a re-check
immediately before writing, and an atomic temp-file + `os.replace()`
write with explicit LF endings, line-based in-place edit only (never a
gov_id-keyed dict rebuild).

Also writes `research/wo349_jc_applied_gov_ids.txt` (one gov_id per
line, append mode).

Usage:
    python3 scripts/wo349_apply_to_jc.py
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
VERIFY_CSV = ROOT / "wo349_verify.csv"
APPLIED_GOV_IDS_TXT = ROOT / "wo349_jc_applied_gov_ids.txt"

FALLBACK_MIN_SANE_ROW_COUNT = 30000

# --- hand-check outcomes (see this script's own docstring) ---

TIER1_INGESTED = {
    "us:place:5356695",
    "us:place:1834114",
    "us:county:27047",
    "us:place:1714065",
    "us:place:4868624",
    "us:place:2012500",
    "us:place:0482740",
    "us:county:06091",
}
TIER1_WRONG_DOMAIN = {"us:place:2064100"}  # Seward city KS

TIER3_QUEUED = {
    "us:place:0667056",
    "us:place:2815380",
    "us:place:5379590",
    "us:place:5511200",
    "us:place:3576200",
    "us:cousub:2502167945",
    "us:cousub:3402500070",
}
TIER3_DEFERRED = {"us:place:0617498", "us:place:5355785"}
TIER3_REJECTED_BY_PROBE = {"us:place:0908420", "us:place:1780242", "us:place:5320645"}
TIER3_VIDEO_WITHOUT_MEETING = {
    "us:place:4741200",
    "us:place:4741340",
    "us:place:3631643",
    "us:place:0618506",
}
TIER3_SKIP_AMBIGUOUS_OR_STALE = {
    "us:place:2964550",
    "us:county:08003",
    "us:place:2038700",
    "us:place:1933105",
    "us:place:3632710",
    "us:cousub:0912023890",
}
TIER3_RECLASSIFIED_YOUTUBE_LEAD = {"us:place:2756950"}  # St. Francis city MN

TIER2_WRONG_DOMAIN = {"us:county:22015"}  # Bossier Parish LA

INGEST_PLATFORM = {
    "us:place:5356695": "granicus",
    "us:place:1834114": "civicmedia",
    "us:county:27047": "civicclerk",
    "us:place:1714065": "civicmedia",
    "us:place:4868624": "civicmedia",
    "us:place:2012500": "civicmedia",
    "us:place:0482740": "suiteone",
    "us:county:06091": "civicmedia",
}
INGEST_URL = {
    "us:place:5356695": "https://cityofpuyallup.granicus.com/MediaPlayer.php?view_id=5&clip_id=2942",
    "us:place:1834114": "https://cityofhobart.org/CivicMedia?VID=326",
    "us:county:27047": "https://freeborncomn.portal.civicclerk.com/event/555/media",
    "us:place:1714065": "https://chicagoridge.org/CivicMedia?VID=265",
    "us:place:4868624": "https://snydertx.gov/CivicMedia?VID=133",
    "us:place:2012500": "https://chanute.org/CivicMedia?VID=698",
    "us:place:0482740": "https://public.destinyhosted.com/agenda_publish.cfm?id=94253",
    "us:county:06091": "https://sierracounty.ca.gov/CivicMedia?VID=437",
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

        if gid in TIER1_INGESTED:
            findings[gid] = "__INGESTED__"
        elif gid in TIER1_WRONG_DOMAIN:
            findings[gid] = "wrong-domain-mapping"
        elif gid in TIER3_QUEUED:
            findings[gid] = "__QUEUED__"
        elif gid in TIER3_DEFERRED:
            findings[gid] = "__DEFERRED__"
        elif gid in TIER3_REJECTED_BY_PROBE:
            findings[gid] = "rejected-by-probe"
        elif gid in TIER3_VIDEO_WITHOUT_MEETING:
            findings[gid] = "video-without-meeting"
        elif gid in TIER3_SKIP_AMBIGUOUS_OR_STALE:
            continue  # left alone on purpose
        elif gid in TIER3_RECLASSIFIED_YOUTUBE_LEAD:
            continue  # now a tier-2 lead, left alone
        elif gid in TIER2_WRONG_DOMAIN:
            findings[gid] = "wrong-domain-mapping"
        elif tier == "2":
            continue  # every other YouTube lead: left alone
        elif tier == "4":
            findings[gid] = "meeting-without-video"
        elif tier == "" and verdict in ("empty_listing", "resolved_empty"):
            findings[gid] = "no-meetings-found"
        elif tier == "" and verdict in ("resolve_error", "fetch_failed", "exception"):
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
            already_transcribed = (jc_row.get("transcribed") or "").strip() == "True"

            if action == "__INGESTED__":
                if already_transcribed:
                    skipped_transcribed += 1
                    continue
                jc_row["shares_video"] = "True"
                jc_row["transcribed"] = "True"
                jc_row["example_meeting_url"] = INGEST_URL[gov_id]
                jc_row["suspected_video_provider"] = INGEST_PLATFORM[gov_id]
                jc_row["reject_reason"] = ""
                changed += 1
                applied_gov_ids.append(gov_id)
                continue

            if action == "__QUEUED__":
                if already_transcribed:
                    skipped_transcribed += 1
                    continue
                jc_row["queued"] = "True"
                jc_row["reject_reason"] = "video-no-captions-queued"
                changed += 1
                applied_gov_ids.append(gov_id)
                continue

            if action == "__DEFERRED__":
                if already_transcribed:
                    skipped_transcribed += 1
                    continue
                jc_row["parked"] = "True"
                jc_row["reject_reason"] = "video-no-captions-queued"
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

        tmp_path = JC_PATH.with_suffix(".csv.wo349tmp")
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
