#!/usr/bin/env python3
"""WO-323: probe every tier-3 candidate `wo323_targeted.py`
found (real video, no reachable captions) before it becomes a real queue
entry, per Ryan's "probe before queue" rule and WO-144's probe helper.

Same shape as `wo191_finish_tier3.py`/`wo147_finish_tier3.py`, pointed at
this WO's own files. Reads
`rtr-business/research/wo323_tier3_pending.csv` (one row per candidate:
gov_id, platform, meeting_url, video_url, source_url, jurisdiction,
pin_row). For each row, `app/platforms/queue_probe.py`'s shared
`finish_candidate()` (WO-224) does the actual work: uses the sidecar's
cached verdict when one already exists for this URL (never re-probes,
but -- unlike every pre-WO-224 copy of this script -- actually checks
what that cached verdict WAS before deciding whether to queue), otherwise
probes fresh via `probe_queue_entry()` and appends the result to the
shared sidecar (`scripts/tier3_auto_transcription_queue_probe.csv`).

  1. Normalize a YouTube `/embed/` URL to `watch?v=` first.
  2. Call `finish_candidate()` with the already-known
     `meeting_url`/`video_url`/`platform`/`pin_row`.
  3. On verdict "accept"/"flag-long": queues (unless already queued or
     the URL is a deliberate `tier3_long_meetings_deferred.txt` removal)
     and pins (unless already pinned). A duration over 90 minutes goes to
     the deferred file instead of the queue (WO-205/WO-212's rule).
  4. On "reject-dead"/"reject-short": never touches the real queue file.

Writes `rtr-business/research/wo323_tier3_finish_log.csv` -- one row per
candidate with the probe verdict, so `wo323_apply_to_jc.py` can tell
"queued for real" (probe accept) apart from "found, but rejected by the
probe" (reject-dead/reject-short).

Politeness: reuses `probe_tier3_queue.py`'s own host-gate pattern (one
host at a time, a real delay) and stops after 6 consecutive access-shaped
probe failures. A cache hit (finish_candidate's `used_cache=True`) skips
the network entirely, so it never counts toward the host delay or the
error streak.

Usage:
    python scripts/wo323_finish_tier3.py
    python scripts/wo323_finish_tier3.py --limit 25
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import certifi  # noqa: E402

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.queue_probe import (  # noqa: E402
    finish_candidate,
    parse_pin_row,
)

register_all_finders()

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
PENDING_CSV = RESEARCH_DIR / "wo323_tier3_pending.csv"
FINISH_LOG_CSV = RESEARCH_DIR / "wo323_tier3_finish_log.csv"
FINISH_LOG_FIELDS = [
    "gov_id",
    "platform",
    "meeting_url",
    "video_url",
    "probe_verdict",
    "probe_reason",
    "duration_seconds",
    "queued",
    "pinned",
]

HOST_DELAY_SECONDS = 2.0
MAX_CONSECUTIVE_ERRORS = 6

_YT_EMBED_RE = re.compile(r"youtube\.com/embed/([\w-]+)", re.I)

CALLER = "wo323_finish_tier3"


def _normalize_youtube_embed(url: str) -> str:
    m = _YT_EMBED_RE.search(url or "")
    if m:
        return f"https://www.youtube.com/watch?v={m.group(1)}"
    return url


async def main_async(limit):
    if not PENDING_CSV.exists():
        print(f"No {PENDING_CSV.name} -- nothing to probe.")
        return

    with PENDING_CSV.open(newline="", encoding="utf-8") as f:
        pending_rows = list(csv.DictReader(f))
    print(f"{len(pending_rows)} rows in {PENDING_CSV.name}")

    done_gov_ids = set()
    if FINISH_LOG_CSV.exists():
        with FINISH_LOG_CSV.open(newline="", encoding="utf-8") as f:
            done_gov_ids = {r["gov_id"] for r in csv.DictReader(f) if r.get("gov_id")}

    to_process = [r for r in pending_rows if r["gov_id"] not in done_gov_ids]
    if limit:
        to_process = to_process[:limit]
    print(f"Probing {len(to_process)} not-yet-finished row(s)...")

    is_new_log = not FINISH_LOG_CSV.exists()
    log_f = FINISH_LOG_CSV.open("a", newline="", encoding="utf-8")
    log_w = csv.DictWriter(log_f, fieldnames=FINISH_LOG_FIELDS, lineterminator="\n")
    if is_new_log:
        log_w.writeheader()
        log_f.flush()

    consecutive_errors = 0
    last_host = None
    try:
        for i, row in enumerate(to_process):
            meeting_url = _normalize_youtube_embed(row.get("meeting_url", ""))
            video_url = _normalize_youtube_embed(row.get("video_url", ""))
            platform = row.get("platform") or None
            pin = parse_pin_row(row.get("pin_row", ""))

            outcome = await finish_candidate(
                meeting_url,
                video_url=video_url or None,
                source_url=row.get("source_url") or None,
                platform=platform,
                gov_id=row.get("gov_id", ""),
                jurisdiction=row.get("jurisdiction", ""),
                pin=pin,
                caller=CALLER,
            )
            result = outcome.probe

            if not outcome.used_cache:
                host = urlparse(meeting_url).netloc
                if host == last_host:
                    time.sleep(HOST_DELAY_SECONDS)
                last_host = host

            is_access_fail = result.verdict == "reject-dead" and any(
                m in (result.reason or "").lower()
                for m in (
                    "timeout",
                    "unreachable",
                    "http 403",
                    "http 404",
                    "http 5",
                    "connection",
                )
            )
            consecutive_errors = (
                consecutive_errors + 1
                if (is_access_fail and not outcome.used_cache)
                else 0
            )

            log_w.writerow(
                {
                    "gov_id": row["gov_id"],
                    "platform": platform,
                    "meeting_url": meeting_url,
                    "video_url": video_url,
                    "probe_verdict": result.verdict,
                    "probe_reason": result.reason or "",
                    "duration_seconds": result.duration_seconds,
                    "queued": outcome.queued,
                    "pinned": outcome.pinned,
                }
            )
            log_f.flush()
            cache_tag = " (cached)" if outcome.used_cache else ""
            print(
                f"[{i + 1}/{len(to_process)}] [{result.verdict}{cache_tag}] {row['gov_id']} "
                f"{meeting_url} action={outcome.action} queued={outcome.queued} "
                f"pinned={outcome.pinned} -- {result.reason or ''}"
            )

            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                print(
                    f"ABORTING: {consecutive_errors} consecutive access failures.",
                    file=sys.stderr,
                )
                break
    finally:
        log_f.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(main_async(args.limit))


if __name__ == "__main__":
    main()
