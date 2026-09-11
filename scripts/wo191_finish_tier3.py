#!/usr/bin/env python3
"""WO-191: probe every tier-3 candidate `wo191_access_ladder_sweep.py`
found (real video, no reachable captions) before it becomes a real queue
entry, per Ryan's "probe before queue" rule and WO-144's probe helper.

Same shape as `wo150_finish_tier3.py`/`wo147_finish_tier3.py`, pointed at
this WO's own files. Reads
`rtr-business/research/wo191_tier3_pending.csv` (one row per candidate:
gov_id, platform, meeting_url, video_url, source_url, jurisdiction,
pin_row). For each row not already probed (checked against
`app/platforms/queue_probe.py`'s shared sidecar,
`scripts/tier3_auto_transcription_queue_probe.csv`):

  1. Normalize a YouTube `/embed/` URL to `watch?v=` first.
  2. Call `probe_queue_entry()` directly with the already-known
     `meeting_url`/`video_url`/`platform`.
  3. Append the ProbeResult to the shared sidecar.
  4. On verdict == "accept": append the meeting URL to the real
     `scripts/tier3_auto_transcription_queue.txt` (dedupe-checked) and
     write the row's pin (if any) to `tenant_overrides.csv`
     (dedupe-checked).
  5. On "reject-dead"/"reject-short": never touch the real queue file.

Writes `rtr-business/research/wo191_tier3_finish_log.csv` -- one row per
candidate with the probe verdict, so `wo191_apply_to_jc.py` can tell
"queued for real" (probe accept) apart from "found, but rejected by the
probe" (reject-dead/reject-short).

Politeness: reuses `probe_tier3_queue.py`'s own host-gate pattern (one
host at a time, a real delay) and stops after 6 consecutive access-shaped
probe failures.

Usage:
    python scripts/wo191_finish_tier3.py
    python scripts/wo191_finish_tier3.py --limit 25
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
    DEFAULT_SIDECAR_PATH,
    append_probe_row,
    probe_queue_entry,
)
from scripts.wo134_confirmed_hits_ingest import (  # noqa: E402
    TENANT_OVERRIDES_CSV,
    TIER3_QUEUE_FILE,
    _existing_tier3_queue_urls,
)

register_all_finders()

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
PENDING_CSV = RESEARCH_DIR / "wo191_tier3_pending.csv"
FINISH_LOG_CSV = RESEARCH_DIR / "wo191_tier3_finish_log.csv"
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


def _normalize_youtube_embed(url: str) -> str:
    m = _YT_EMBED_RE.search(url or "")
    if m:
        return f"https://www.youtube.com/watch?v={m.group(1)}"
    return url


def _load_probed_urls() -> set:
    if not DEFAULT_SIDECAR_PATH.exists():
        return set()
    with DEFAULT_SIDECAR_PATH.open(newline="", encoding="utf-8") as f:
        return {r["url"] for r in csv.DictReader(f) if r.get("url")}


def _write_pin(pin_row: str) -> bool:
    """pin_row is 'host|match|gov_id|strength|source|evidence'."""
    if not pin_row:
        return False
    parts = pin_row.split("|")
    if len(parts) < 6:
        return False
    host, match, gov_id, strength, source, evidence = (
        parts[0],
        parts[1],
        parts[2],
        parts[3],
        parts[4],
        "|".join(parts[5:]),
    )
    if not host or not match or not gov_id:
        return False
    existing = set()
    if TENANT_OVERRIDES_CSV.exists():
        with TENANT_OVERRIDES_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                existing.add((r.get("tenant_host", ""), r.get("match", "")))
    key = (host, match)
    if key in existing:
        return False
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
                "tenant_host": host,
                "match": match,
                "gov_id": gov_id,
                "strength": strength or "fallback",
                "source": source or "wo191_access_ladder_sweep",
                "evidence": evidence or f"WO-191 tier-3 probe accept, gov_id={gov_id}",
            }
        )
    return True


async def main_async(limit):
    if not PENDING_CSV.exists():
        print(f"No {PENDING_CSV.name} -- nothing to probe.")
        return

    with PENDING_CSV.open(newline="", encoding="utf-8") as f:
        pending_rows = list(csv.DictReader(f))
    print(f"{len(pending_rows)} rows in {PENDING_CSV.name}")

    already_probed = _load_probed_urls()
    already_queued = _existing_tier3_queue_urls()
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

            if meeting_url in already_probed:
                print(
                    f"[{i + 1}/{len(to_process)}] already probed, skipping fetch: {meeting_url}"
                )
                log_w.writerow(
                    {
                        "gov_id": row["gov_id"],
                        "platform": platform,
                        "meeting_url": meeting_url,
                        "video_url": video_url,
                        "probe_verdict": "already-probed",
                        "probe_reason": "",
                        "duration_seconds": "",
                        "queued": "",
                        "pinned": "",
                    }
                )
                log_f.flush()
                continue

            host = urlparse(meeting_url).netloc
            if host == last_host:
                time.sleep(HOST_DELAY_SECONDS)
            last_host = host

            result = await probe_queue_entry(
                meeting_url, video_url=video_url or None, platform=platform
            )
            append_probe_row(DEFAULT_SIDECAR_PATH, result)
            already_probed.add(meeting_url)

            queued = False
            pinned = False
            if result.verdict == "accept":
                if meeting_url not in already_queued:
                    hit = row.get("source_url") or ""
                    line = (
                        f"{meeting_url}\t{hit}"
                        if hit and hit != meeting_url
                        else meeting_url
                    )
                    with TIER3_QUEUE_FILE.open("a", encoding="utf-8") as qf:
                        qf.write(line + "\n")
                    already_queued.add(meeting_url)
                    queued = True
                pinned = _write_pin(row.get("pin_row", ""))

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
            consecutive_errors = consecutive_errors + 1 if is_access_fail else 0

            log_w.writerow(
                {
                    "gov_id": row["gov_id"],
                    "platform": platform,
                    "meeting_url": meeting_url,
                    "video_url": video_url,
                    "probe_verdict": result.verdict,
                    "probe_reason": result.reason or "",
                    "duration_seconds": result.duration_seconds,
                    "queued": queued,
                    "pinned": pinned,
                }
            )
            log_f.flush()
            print(
                f"[{i + 1}/{len(to_process)}] [{result.verdict}] {row['gov_id']} "
                f"{meeting_url} queued={queued} pinned={pinned} -- {result.reason or ''}"
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
