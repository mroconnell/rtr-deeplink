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
- `wo134_confirmed_hits_ingest.py`'s `_existing_tier3_queue_urls()`/
  `_existing_override_keys()` for the duplicate checks against the real
  queue file and `tenant_overrides.csv`.

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
    append_probe_row,
    probe_queue_entry,
)

import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402

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


def _existing_override_keys() -> set:
    keys = set()
    if TENANT_OVERRIDES_CSV.exists():
        with TENANT_OVERRIDES_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                keys.add((r.get("tenant_host", ""), r.get("match", "")))
    return keys


def _apply_pin_row(pin_row: str, existing_keys: set) -> None:
    if not pin_row:
        return
    parts = pin_row.split("|", 5)
    if len(parts) != 6:
        print(f"WARNING: malformed pin_row, skipping: {pin_row!r}", file=sys.stderr)
        return
    tenant_host, match, gov_id, strength, source, evidence = parts
    key = (tenant_host, match)
    if key in existing_keys:
        return
    is_new = not TENANT_OVERRIDES_CSV.exists()
    with TENANT_OVERRIDES_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "tenant_host",
                "match",
                "gov_id",
                "strength",
                "source",
                "evidence",
            ],
            lineterminator="\n",
        )
        if is_new:
            writer.writeheader()
        writer.writerow(
            {
                "tenant_host": tenant_host,
                "match": match,
                "gov_id": gov_id,
                "strength": strength,
                "source": source,
                "evidence": evidence,
            }
        )
    existing_keys.add(key)


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

    existing_queue_urls = wo134._existing_tier3_queue_urls()
    existing_override_keys = _existing_override_keys()

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

        result = await probe_queue_entry(
            row["meeting_url"],
            video_url=row.get("video_url") or None,
            source_page_url=row.get("source_url") or None,
            platform=row.get("platform") or None,
        )
        append_probe_row(DEFAULT_SIDECAR_PATH, result)
        print(
            f"[{i + 1}/{len(pending_rows)}] [{result.verdict}] {row['gov_id']} "
            f"{row['meeting_url']} -- {result.reason or f'{result.duration_seconds:.1f}s'}"
        )
        by_gov[row["gov_id"]].append((row, result))

        if result.verdict == "reject-dead" and (
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
    for gov_id, candidates in by_gov.items():
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

    queue_lines_added = 0
    for gov_id, (row, result) in accepted.items():
        meeting_url = row["meeting_url"]
        source_url = row["source_url"]
        if meeting_url not in existing_queue_urls:
            line = (
                f"{meeting_url}\t{source_url}"
                if source_url and source_url != meeting_url
                else meeting_url
            )
            with TIER3_QUEUE_FILE.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            existing_queue_urls.add(meeting_url)
            queue_lines_added += 1
        _apply_pin_row(row.get("pin_row", ""), existing_override_keys)

    print(
        f"\n{len(accepted)} government(s) accepted -> {queue_lines_added} new queue "
        f"line(s), {len(rejected)} government(s) rejected (dead/short)."
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
            _, result = rejected[r["gov_id"]]
            r["outcome"] = "no_video_found"
            r["reject_reason"] = "no-video-found"
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
