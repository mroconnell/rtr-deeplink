"""WO-147, step 2: probe every candidate in wo147_tier3_pending.csv
(WO-144's queue_probe, merged to main after this WO's own sweep started)
and only then queue/pin the ones that survive -- Ryan's "probe before
queue" rule for this WO, and the reason wo134_confirmed_hits_ingest.py's
TIER3_HANDLER hook exists at all (see that module's own comment).

Reuses, does not reimplement:
- `app.platforms.queue_probe.probe_queue_entry()`/`append_probe_row()`
  (WO-144) for the actual duration/date/size check and its shared,
  append-only sidecar (`scripts/tier3_auto_transcription_queue_probe.csv`)
  -- the same sidecar `scripts/probe_tier3_queue.py` and
  `scripts/feed_tier3_auto_transcription.py` already write to.
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
    SAME government (rare in this WO's own output -- each government
    normally produces at most one pending row), prefer over-nine-minutes,
    then the most recent date, then the shortest duration.
  - Never reject a long meeting outright (`flag-long` still queues).

Updates, per accepted row:
  1. Appends `meeting_url[\\tsource_url]` to
     `scripts/tier3_auto_transcription_queue.txt` (skipped if already
     present -- same dedup wo134_confirmed_hits_ingest.py's own tier-3
     append already uses).
  2. Applies the row's precomputed `pin_row` (written by
     wo147_access_ladder_sweep.py's `tier3_pending_handler()`) to
     `app/utils/jurisdiction_data/tenant_overrides.csv`, if non-empty and
     not already present.
  3. Rewrites the matching row(s) in `wo147_report.csv` in place:
     outcome `queued_tier3_pending` -> `queued_tier3` (accepted) or
     `no_video_found` (rejected -- the video existed but wasn't usable;
     closest fit in the §23 taxonomy, with the real probe verdict kept
     in the `note` field for anyone who needs the specific reason).

Usage (from repo root, after `git fetch && git rebase origin/main` so
`app.platforms.queue_probe` exists):
    python scripts/wo147_finish_tier3_queue.py
    python scripts/wo147_finish_tier3_queue.py --limit 5   # smoke test
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
PENDING_CSV = RESEARCH_DIR / "wo147_tier3_pending.csv"
REPORT_CSV = RESEARCH_DIR / "wo147_report.csv"
TIER3_QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"
TENANT_OVERRIDES_CSV = (
    REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "tenant_overrides.csv"
)

HOST_DELAY_SECONDS = 2.0
MAX_CONSECUTIVE_ACCESS_ERRORS = 6

_ACCEPT_VERDICTS = {"accept", "flag-long"}

CALLER = "wo147_finish_tier3_queue"


def _rank_key(row_and_result):
    _, result = row_and_result
    over_nine = 1 if result.over_nine_minutes else 0
    date = result.date or ""
    # shorter is preferred among otherwise-tied candidates -- negate so
    # sort(reverse=True) still picks the shortest.
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

    # A CAUTION-flagged row (channel_scan_caution() in
    # wo147_access_ladder_sweep.py -- this WO's own 40-government pilot
    # found 3/8 bare-channel-scan hits were not real meetings despite
    # passing the title gate) needs a human to read the title before it
    # earns a queue line, not just a clean probe -- the probe only knows
    # duration/date/size, nothing about content. Held back here, not
    # accepted or rejected, so a human pass can revisit them.
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

        # Real, confirmed-live bug caught in this script's own smoke test:
        # the pending row's own `platform` column names whatever platform
        # the ORIGINAL hit was (e.g. "civicplus"), not the actual video
        # host after delegation (CLAUDE.md's documented "Legistar/
        # CivicPlus's delegation ends up with the delegated platform's
        # URL as source_url" quirk) -- passing that stale label forced
        # probe_queue_entry() to dispatch on the wrong platform (tried
        # "civicplus" against a youtube.com video_url, landing on "no
        # probe recipe for this media shape" for a perfectly probeable
        # YouTube video). meeting_url is always the real, resolved video
        # page (e.g. a youtube.com/watch URL even for a civicplus-hit
        # row), so detect_platform() on it is the correct source of
        # truth -- not passed explicitly at all, letting
        # probe_queue_entry() derive it the same way.
        # WO-224: a URL the shared sidecar already has a verdict for is
        # read back, not re-probed -- this script used to hit the network
        # again on every re-run, no matter how many times a candidate had
        # already been probed. cached_verdict() is also the fix for the
        # sibling bug this WO closes elsewhere (wo150/183/191/216's own
        # "already probed, skipping fetch" branch dropped a real accept
        # silently) -- here there was no such branch to begin with, but
        # reusing the one shared lookup keeps this script from drifting
        # into that same shape later.
        cached = cached_verdict(row["meeting_url"], sidecar_path=DEFAULT_SIDECAR_PATH)
        used_cache = cached is not None
        if used_cache:
            result = cached
        else:
            # Real, confirmed-live bug caught in this script's own smoke
            # test: the pending row's own `platform` column names
            # whatever platform the ORIGINAL hit was (e.g. "civicplus"),
            # not the actual video host after delegation (CLAUDE.md's
            # documented "Legistar/CivicPlus's delegation ends up with
            # the delegated platform's URL as source_url" quirk) --
            # passing that stale label forced probe_queue_entry() to
            # dispatch on the wrong platform (tried "civicplus" against a
            # youtube.com video_url, landing on "no probe recipe for
            # this media shape" for a perfectly probeable YouTube video).
            # meeting_url is always the real, resolved video page (e.g. a
            # youtube.com/watch URL even for a civicplus-hit row), so
            # detect_platform() on it is the correct source of truth --
            # not passed explicitly at all, letting probe_queue_entry()
            # derive it the same way.
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

    # Pick a winner per government, per docs/BREADTH_SWEEP_BRIEF.md's
    # preference order (over nine minutes, then most recent, then
    # shortest) -- normally a no-op since each government produced at
    # most one pending row.
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
    # file instead of the queue (WO-205/WO-212's rule) -- no point
    # queuing a long meeting today just to swap it out again later. A
    # candidate whose URL is already a deliberate deferred-file removal
    # never gets re-queued either, whatever verdict it carries now.
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

    # Rewrite the matching wo147_report.csv rows in place.
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
            rejected_row, result = rejected[r["gov_id"]]
            # WO-169: a real video existed here -- this belongs on its own
            # `rejected_by_probe` outcome, not folded into no_video_found
            # (which means no video ever existed). And meeting_url/
            # video_url must survive this rewrite, not be blanked: a real,
            # confirmed-live bug this WO fixes -- `r["meeting_url"] = ""`
            # here is exactly the gap WO-151 found (a real video address
            # silently lost on a skip/reject), just at a different stage
            # of this pipeline than wo134_confirmed_hits_ingest.py's own
            # version of the same bug. See CLAUDE.md's WO-169 entry.
            r["outcome"] = "rejected_by_probe"
            r["reject_reason"] = "rejected_by_probe"
            r["reject_class"] = "content"
            r["tier"] = ""
            r["meeting_url"] = rejected_row.get("meeting_url") or r.get(
                "meeting_url", ""
            )
            r["video_url"] = rejected_row.get("video_url") or r.get("video_url", "")
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
