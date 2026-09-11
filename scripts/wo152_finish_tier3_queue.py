"""WO-152, step 2: probe every candidate in wo152_tier3_pending.csv
(WO-144's queue_probe) and only then queue/pin the ones that survive --
Ryan's "probe before queue" rule, the same shape as
scripts/wo147_finish_tier3_queue.py (copied and adapted, not
reimplemented -- see that file's own docstring for the full reasoning
behind each rule below).

Reuses, does not reimplement:
- `app.platforms.queue_probe.probe_queue_entry()`/`append_probe_row()`
  (WO-144) for the actual duration/date/size check and its shared,
  append-only sidecar (`scripts/tier3_auto_transcription_queue_probe.csv`).
- `app.platforms.queue_probe.cached_verdict()` (WO-224): a candidate the
  sidecar already has a verdict for is read back, not re-probed -- this
  script used to re-probe every row on every re-run regardless.
- `app.platforms.queue_probe.append_queue_line()`/`append_deferred_line()`/
  `write_pin_row()`/`parse_pin_row()` (WO-224) for the actual queue/
  deferred-file/pin writes and their duplicate checks, replacing this
  script's own former `_apply_pin_row()`/`_existing_override_keys()`. A
  winning candidate over 90 minutes now goes to
  `tier3_long_meetings_deferred.txt` instead of the queue
  (WO-205/WO-212's rule) -- this script never did that before.

Rules (docs/BREADTH_SWEEP_BRIEF.md's "probe before queuing"):
  - Refuse a dead link (verdict `reject-dead`) or a clip under the
    meeting-plausibility floor (verdict `reject-short`).
  - Prefer a meeting over nine minutes; among several candidates for the
    SAME government, prefer over-nine-minutes, then the most recent
    date, then the shortest duration.
  - Never reject a long meeting outright (`flag-long` still queues).

Updates, per accepted row:
  1. Appends `meeting_url[\\tsource_url]` to
     `scripts/tier3_auto_transcription_queue.txt` (skipped if already
     present).
  2. Applies the row's precomputed `pin_row` to
     `app/utils/jurisdiction_data/tenant_overrides.csv`, if non-empty and
     not already present.
  3. Rewrites the matching row(s) in `wo152_report.csv` in place: outcome
     `queued_tier3` (already the pending-row outcome the sweep wrote) is
     confirmed, or downgraded to `rejected_by_probe` (video existed but
     the probe refused it -- the real verdict kept in `note`).

Usage:
    python scripts/wo152_finish_tier3_queue.py
    python scripts/wo152_finish_tier3_queue.py --limit 5   # smoke test
"""

import argparse
import asyncio
import csv
import os
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.queue_probe import (  # noqa: E402
    DEFAULT_SIDECAR_PATH,
    DEFER_OVER_SECONDS,
    TIER3_LONG_MEETINGS_DEFERRED_FILE,
    append_deferred_line,
    append_probe_row,
    append_queue_line,
    cached_verdict,
    is_deferred,
    parse_pin_row,
    probe_queue_entry,
    write_pin_row,
)

RESEARCH_DIR = Path("/Users/mroconnell/Documents/rtr-business/research")
PENDING_CSV = RESEARCH_DIR / "wo152_tier3_pending.csv"
REPORT_CSV = RESEARCH_DIR / "wo152_report.csv"
TIER3_QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"
TENANT_OVERRIDES_CSV = (
    REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "tenant_overrides.csv"
)

HOST_DELAY_SECONDS = 2.0
MAX_CONSECUTIVE_ACCESS_ERRORS = 6

_ACCEPT_VERDICTS = {"accept", "flag-long"}

CALLER = "wo152_finish_tier3_queue"


def _rank_key(row_and_result):
    _, result = row_and_result
    over_nine = 1 if result.over_nine_minutes else 0
    date = result.date or ""
    duration = -(result.duration_seconds or 0)
    return (over_nine, date, duration)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    register_all_finders()

    if not PENDING_CSV.exists():
        print(f"No {PENDING_CSV} -- nothing to do.")
        return

    with PENDING_CSV.open(newline="", encoding="utf-8") as f:
        pending_rows = list(csv.DictReader(f))
    if args.limit:
        pending_rows = pending_rows[: args.limit]
    print(f"{len(pending_rows)} pending row(s) to probe.")

    # Same caution as wo147_finish_tier3_queue.py: a bare-YouTube-channel-
    # scan hit (channel_scan_caution() in wo152_dead_domain_recheck.py,
    # reused from wo147) needs a human to read the title before it earns
    # a queue line -- the probe only knows duration/date/size, nothing
    # about content.
    caution_gov_ids = set()
    if REPORT_CSV.exists():
        with REPORT_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if "CAUTION" in r.get("note", ""):
                    caution_gov_ids.add(r["gov_id"])
    print(
        f"{len(caution_gov_ids)} pending gov_id(s) are CAUTION-flagged "
        "(bare YouTube channel scan) -- held back from auto-accept regardless "
        "of probe verdict."
    )

    by_gov: Dict[str, List[tuple]] = defaultdict(list)
    consecutive_access_errors = 0
    last_call_by_host: Dict[str, float] = {}

    for i, row in enumerate(pending_rows):
        host = urlparse(row["meeting_url"]).netloc
        last = last_call_by_host.get(host)
        if last is not None:
            remaining = HOST_DELAY_SECONDS - (time.monotonic() - last)
            if remaining > 0:
                await asyncio.sleep(remaining)
        last_call_by_host[host] = time.monotonic()

        # WO-224: a URL the shared sidecar already has a verdict for is
        # read back, not re-probed (see wo147_finish_tier3_queue.py's own
        # matching comment for the full reasoning).
        cached = cached_verdict(row["meeting_url"], sidecar_path=DEFAULT_SIDECAR_PATH)
        used_cache = cached is not None
        if used_cache:
            result = cached
        else:
            result = await probe_queue_entry(
                row["meeting_url"],
                video_url=row.get("video_url") or None,
                source_page_url=row.get("source_url") or None,
            )
            append_probe_row(DEFAULT_SIDECAR_PATH, result, caller=CALLER)
        cache_tag = " (cached)" if used_cache else ""
        print(
            f"[{i + 1}/{len(pending_rows)}] [{result.verdict}{cache_tag}] {row['gov_id']} "
            f"{row['meeting_url']} -- {result.reason or f'{result.duration_seconds:.1f}s'}"
        )
        by_gov[row["gov_id"]].append((row, result))

        if used_cache:
            consecutive_access_errors = 0
        elif result.verdict == "reject-dead" and (
            "timeout" in (result.reason or "").lower()
            or "http" in (result.reason or "").lower()
            or "fetch" in (result.reason or "").lower()
        ):
            consecutive_access_errors += 1
        else:
            consecutive_access_errors = 0
        if consecutive_access_errors >= MAX_CONSECUTIVE_ACCESS_ERRORS:
            print(
                f"ABORTING: {consecutive_access_errors} consecutive access-shaped "
                "probe failures. Re-run to resume (the shared sidecar dedupes).",
                file=sys.stderr,
            )
            break

    accepted: Dict[str, tuple] = {}
    rejected: Dict[str, tuple] = {}
    held_for_review: Dict[str, tuple] = {}
    for gov_id, candidates in by_gov.items():
        if gov_id in caution_gov_ids:
            held_for_review[gov_id] = candidates[0]
            continue
        accepted_candidates = [
            (row, result)
            for row, result in candidates
            if result.verdict in _ACCEPT_VERDICTS
        ]
        if accepted_candidates:
            accepted_candidates.sort(key=_rank_key, reverse=True)
            accepted[gov_id] = accepted_candidates[0]
        else:
            rejected[gov_id] = candidates[0]

    if held_for_review:
        print(f"\n{len(held_for_review)} government(s) held for manual title review:")
        for gov_id, (row, result) in held_for_review.items():
            print(
                f"  {gov_id} {row['meeting_url']} -- probe: "
                f"{result.verdict}, {result.reason or f'{result.duration_seconds:.1f}s'}"
            )

    # WO-224: a duration over 90 minutes goes straight to the deferred
    # file instead of the queue (WO-205/WO-212's rule), and a candidate
    # already sitting in the deferred file (a deliberate removal) never
    # gets re-queued, whatever verdict it carries now.
    queue_lines_added = 0
    deferred_lines_added = 0
    for gov_id, (row, result) in accepted.items():
        meeting_url = row["meeting_url"]
        source_url = row["source_url"]
        pin = parse_pin_row(row.get("pin_row", ""))
        if is_deferred(meeting_url, deferred_path=TIER3_LONG_MEETINGS_DEFERRED_FILE):
            continue
        duration = result.duration_seconds or 0.0
        if duration > DEFER_OVER_SECONDS:
            if append_deferred_line(
                meeting_url,
                source_url=source_url or "",
                gov_id=gov_id,
                duration_seconds=result.duration_seconds,
                deferred_path=TIER3_LONG_MEETINGS_DEFERRED_FILE,
            ):
                deferred_lines_added += 1
            continue
        if append_queue_line(meeting_url, source_url, queue_path=TIER3_QUEUE_FILE):
            queue_lines_added += 1
        if pin:
            write_pin_row(
                host=pin["host"],
                match=pin["match"],
                gov_id=pin["gov_id"],
                strength=pin["strength"],
                source=pin["source"],
                evidence=pin["evidence"],
                pins_path=TENANT_OVERRIDES_CSV,
            )

    print(
        f"\n{len(accepted)} government(s) accepted -> {queue_lines_added} new queue "
        f"line(s), {deferred_lines_added} deferred (over 90 min), "
        f"{len(rejected)} government(s) rejected (dead/short), "
        f"{len(held_for_review)} held for manual title review."
    )

    if not REPORT_CSV.exists():
        print(f"WARNING: {REPORT_CSV} not found -- report rows not updated.")
        return
    with REPORT_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        report_rows = list(reader)

    updated = 0
    for r in report_rows:
        if r["gov_id"] in accepted:
            _, result = accepted[r["gov_id"]]
            r["outcome"] = "queued_tier3"
            r["tier"] = "tier3"
            r["reject_reason"] = ""
            r["reject_class"] = ""
            r["note"] = (
                r["note"] + f"; WO-144 probe: {result.verdict}, "
                f"{result.duration_seconds:.1f}s, date={result.date}"
            ).strip("; ")
            updated += 1
        elif r["gov_id"] in rejected:
            _, result = rejected[r["gov_id"]]
            r["outcome"] = "rejected_by_probe"
            r["reject_reason"] = result.verdict  # reject-dead | reject-short
            r["reject_class"] = "content"
            r["tier"] = ""
            r["meeting_url"] = ""
            r["note"] = (
                r["note"]
                + f"; WO-144 probe rejected: {result.verdict} -- {result.reason}"
            ).strip("; ")
            updated += 1

    tmp_path = REPORT_CSV.with_suffix(".csv.tmp")
    with tmp_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(report_rows)
    os.replace(tmp_path, REPORT_CSV)
    print(f"Updated {updated} row(s) in {REPORT_CSV.name}.")


if __name__ == "__main__":
    asyncio.run(main())
