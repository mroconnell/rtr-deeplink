#!/usr/bin/env python3
"""Applies WO-356's findings onto `jurisdiction_coverage.csv`.

WO-356 is a set of follow-ups to WO-349, all under Ryan's 2026-09-13
decisions (see `scripts/wo356_*.py` and this WO's `BACKLOG_DONE.md`
entry for the full reasoning per item):

  Item 1 -- alternate-hub pass on the 91 "no meeting found" governments
    (`research/wo356_verify.csv`, source_item=item1_alt_hub). 85 now
    resolve to a real meeting listing with no video (tier 4) ->
    reject_reason=meeting-without-video. 1 (Greensboro town, MD) found a
    real tier-3 video -> queued. 5 still find nothing -> left alone.
  Item 2 -- retry of the 22 errors (source_item=item2_retry, also via
    the bare-homepage re-verify, since most were a wrong-hub_url problem
    like item 1, not a transient blip). 20 now tier 4 -> meeting-
    without-video. 2 still nothing -> left alone.
  Item 3 -- Seward city, KS: confirmed negative (swagit tenant carries
    only two County Commission categories, no city content) -> no jc
    change, WO-349's wrong-domain-mapping stands.
  Item 4 -- Cudahy city, CA and Port Orchard city, WA: moved from
    tier3_long_meetings_deferred.txt to the queue (Ryan's standing rule:
    over 90 min is queued, never parked for length alone) -> parked
    cleared, queued=True.
  Item 5 -- deeper walk on 4 rejected candidates: La Vergne city, TN and
    Lawrenceburg city, TN (real meeting found, no video, on their own
    real CivicPlus AgendaCenter listing -- the elocallink.tv "video"
    WO-349 found was a decorative header clip) -> meeting-without-video,
    replacing video-without-meeting (this is a different, newer, hand-
    verified finding, not the same claim restated -- see script comment
    for why the usual weak/strong guard doesn't apply here). Hamburg
    village, NY (real video + real captions found on the town's own
    Swagit tenant) -> INGESTED. Del Mar city, CA (real video found, a
    direct CloudFront MP4 named for the government and date) -> queued.
  Item 6 -- "historic archive" pages/queue lines for 3 real-but-old
    finds: Grinnell city, IA; Hastings-on-Hudson village, NY (on-mission
    checked); Easton town, CT -> all queued. St. Joseph city, MO;
    Alamosa County, CO; Larned city, KS -- no title obtained on retry,
    left alone per the rule ("stay open unless you can get a title").

Follows ENUMERATION_METHODS.md §158's write protocol exactly (same
reference implementation as `wo191_apply_to_jc.py` / `wo349_apply_to_jc.py`):
a real `flock` held around the whole read-modify-write, a fresh read
taken only after the lock is acquired, a row-count floor re-derived from
`git show HEAD` at run time, a re-check immediately before writing, and
an atomic temp-file + `os.replace()` write with explicit LF endings,
line-based in-place edit only (never a gov_id-keyed dict rebuild).

Also writes `research/wo356_jc_applied_gov_ids.txt` (one gov_id per
line, append mode).

Usage:
    python3 scripts/wo356_apply_to_jc.py
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
VERIFY_CSV = ROOT / "wo356_verify.csv"
APPLIED_GOV_IDS_TXT = ROOT / "wo356_jc_applied_gov_ids.txt"

FALLBACK_MIN_SANE_ROW_COUNT = 30000

# Same guard as wo349_apply_to_jc.py: a weak new reason never overwrites
# an existing stronger one, for the bulk item1/item2 tier-4 rows.
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

# --- items 4/5/6: hand-verified, per-government dispositions (not run
# through the weak/strong guard -- each of these is a specific, fresh,
# hand-checked finding from this WO's own live re-investigation, meant
# to REPLACE whatever WO-349 recorded, not merely restate it) ---

GREENSBORO_MD = "us:place:2435200"  # item 1 tier-3 find

QUEUE_DIRECT = {
    # gov_id: (example_meeting_url, suspected_video_provider)
    "us:place:0617498": (
        "https://townhallstreams.com/stream.php?location_id=115&id=76435",
        "townhallstreams",
    ),  # Cudahy city, CA -- item 4
    "us:place:5355785": (
        "https://portorchardwa.portal.civicclerk.com/event/2506/media",
        "civicclerk",
    ),  # Port Orchard city, WA -- item 4
    "us:place:0618506": (
        "https://d2vr3rrbtycvrt.cloudfront.net/delmar-ccm-20260908/videos/full/mp4/delmar-ccm-20260908_720.mp4",
        "direct_file",
    ),  # Del Mar city, CA -- item 5
    "us:place:1933105": (
        "https://grinnell.granicus.com/MediaPlayer.php?view_id=1&clip_id=614",
        "granicus",
    ),  # Grinnell city, IA -- item 6
    "us:place:3632710": (
        "https://hastingsonhudsonny.swagit.com/play/10102024-509",
        "swagit",
    ),  # Hastings-on-Hudson village, NY -- item 6
    "us:cousub:0912023890": (
        "https://vimeo.com/697711522/afbcc0c15d",
        "vimeo",
    ),  # Easton town, CT -- item 6
}
# Cudahy/Port Orchard were already parked=True from WO-349 -- clear that
# and set queued instead. Everyone else in QUEUE_DIRECT is a fresh queue.
WAS_PARKED = {"us:place:0617498", "us:place:5355785"}

INGESTED = {
    "us:place:3631643": (
        "https://hamburgny.new.swagit.com/videos/398870",
        "swagit",
    ),  # Hamburg village, NY -- item 5
}

MEETING_WITHOUT_VIDEO_DIRECT = {
    "us:place:4741200",  # La Vergne city, TN -- item 5
    "us:place:4741340",  # Lawrenceburg city, TN -- item 5
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


def load_item12_findings() -> dict[str, str]:
    """gov_id -> reject_reason (or __QUEUED__) for wo356_verify.csv
    (items 1 and 2), same shape as wo349_apply_to_jc.py's load_findings.
    A gov_id already handled by items 4/5/6 above is skipped here."""
    findings: dict[str, str] = {}
    handled_elsewhere = set(QUEUE_DIRECT) | set(INGESTED) | MEETING_WITHOUT_VIDEO_DIRECT
    seen: set[str] = set()
    with open(VERIFY_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    for r in rows:
        gid = r.get("gov_id", "")
        if not gid or gid in seen:
            continue  # dedupe the one known Beaver Dam double-write
        seen.add(gid)
        if gid in handled_elsewhere:
            continue
        tier = r.get("tier", "")

        if gid == GREENSBORO_MD:
            findings[gid] = "__QUEUED__"
        elif tier == "4":
            findings[gid] = "meeting-without-video"
        else:
            continue  # still nothing (no_platform_detected / fetch_failed
            # / resolve_error / empty_listing) -- verdict unchanged, left
            # alone

    return findings


def main() -> None:
    item12_findings = load_item12_findings()
    print(f"{len(item12_findings)} item1/2 governments to apply")
    print(
        f"{len(QUEUE_DIRECT)} item4/5/6 direct-queue, {len(INGESTED)} ingested, "
        f"{len(MEETING_WITHOUT_VIDEO_DIRECT)} item5 direct meeting-without-video"
    )

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

        def get_row(gov_id: str):
            idx = by_gov_id_first_index.get(gov_id)
            if idx is None:
                missing.append(gov_id)
                return None
            return jc_rows[idx]

        # --- items 4/5/6: direct queue ---
        for gov_id, (url, provider) in QUEUE_DIRECT.items():
            jc_row = get_row(gov_id)
            if jc_row is None:
                continue
            if (jc_row.get("transcribed") or "").strip() == "True":
                skipped_transcribed += 1
                continue
            if gov_id in WAS_PARKED:
                jc_row["parked"] = ""
            jc_row["queued"] = "True"
            jc_row["reject_reason"] = "video-no-captions-queued"
            if not (jc_row.get("example_meeting_url") or "").strip():
                jc_row["example_meeting_url"] = url
            if not (jc_row.get("suspected_video_provider") or "").strip():
                jc_row["suspected_video_provider"] = provider
            changed += 1
            applied_gov_ids.append(gov_id)

        # --- item 5: Hamburg NY ingested ---
        for gov_id, (url, provider) in INGESTED.items():
            jc_row = get_row(gov_id)
            if jc_row is None:
                continue
            if (jc_row.get("transcribed") or "").strip() == "True":
                skipped_transcribed += 1
                continue
            jc_row["shares_video"] = "True"
            jc_row["transcribed"] = "True"
            jc_row["example_meeting_url"] = url
            jc_row["suspected_video_provider"] = provider
            jc_row["reject_reason"] = ""
            changed += 1
            applied_gov_ids.append(gov_id)

        # --- item 5: La Vergne / Lawrenceburg direct meeting-without-video ---
        for gov_id in MEETING_WITHOUT_VIDEO_DIRECT:
            jc_row = get_row(gov_id)
            if jc_row is None:
                continue
            if (jc_row.get("transcribed") or "").strip() == "True":
                skipped_transcribed += 1
                continue
            jc_row["reject_reason"] = "meeting-without-video"
            changed += 1
            applied_gov_ids.append(gov_id)

        # --- items 1/2: bulk tier-4 / Greensboro queue, weak/strong guarded ---
        for gov_id, action in item12_findings.items():
            jc_row = get_row(gov_id)
            if jc_row is None:
                continue
            current_reason = (jc_row.get("reject_reason") or "").strip()
            if (jc_row.get("transcribed") or "").strip() == "True":
                skipped_transcribed += 1
                continue

            if action == "__QUEUED__":
                jc_row["queued"] = "True"
                jc_row["reject_reason"] = "video-no-captions-queued"
                if not (jc_row.get("example_meeting_url") or "").strip():
                    jc_row["example_meeting_url"] = (
                        "https://townhallstreams.com/stream.php?location_id=172&id=76081"
                    )
                if not (jc_row.get("suspected_video_provider") or "").strip():
                    jc_row["suspected_video_provider"] = "townhallstreams"
                changed += 1
                applied_gov_ids.append(gov_id)
                continue

            new_reason = action
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

        tmp_path = JC_PATH.with_suffix(".csv.wo356tmp")
        with open(tmp_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=jc_fieldnames, lineterminator="\n")
            writer.writeheader()
            writer.writerows(jc_rows)
        os.replace(tmp_path, JC_PATH)

        print(
            f"\nDone: {changed} changed, {skipped_guard} skipped (weak/strong guard), "
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
