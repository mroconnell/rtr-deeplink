#!/usr/bin/env python3
"""WO-323: harvest YouTube channel/video candidate URLs seen during phase 1
recon and phase 2 classification of the Canada "neither pass" population
(`passive_neither_4-canada.csv`), WITHOUT ever fetching any of them --
per the launch instructions' literal no-YouTube-calls rule.

Scans, for every government in `wo323_recon.jsonl`: `all_urls_from_record()`
(sitemap/Wayback/Common Crawl URLs, same helper `wo323_classify.py` imports
from `wo273_classify.py`) plus every raw homepage link
(`homepage.links[].href`) phase 1 cached -- both scanned as plain strings,
no network call. Any `youtube.com`/`youtu.be` URL found is classified
channel (`/channel/`, `/c/`, `/@`, `/user/`) or single_video (`/watch`,
`/embed/`, a bare `youtu.be/<id>`) and appended to the shared
`research/youtube_channel_leads.csv`, deduplicated against what's already
in that file (by exact URL) and against duplicates within this run.

Locked (flock on a sibling `.lock`) because WO-321/322/324/325 may be
appending to the same shared file concurrently; this script only ever
appends new rows, never rewrites existing ones.

Usage:
    .venv/bin/python scripts/wo323_youtube_leads.py
"""

from __future__ import annotations

import csv
import fcntl
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from wo273_classify import all_urls_from_record  # noqa: E402

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
RECON_JSONL = RESEARCH_DIR / "wo323_recon.jsonl"
LEADS_CSV = RESEARCH_DIR / "youtube_channel_leads.csv"
LEADS_LOCK = RESEARCH_DIR / "youtube_channel_leads.csv.lock"

FIELDNAMES = [
    "channel_url",
    "gov_id",
    "government",
    "state",
    "source_wo",
    "kind",
    "verified",
    "note",
]

CHANNEL_RE = re.compile(r"/(channel/|c/|@|user/)")
VIDEO_RE = re.compile(r"(/watch|/embed/|/v/)")


def is_youtube_url(url: str) -> bool:
    try:
        netloc = urlparse(url).netloc.lower()
    except ValueError:
        return False
    return "youtube.com" in netloc or "youtu.be" in netloc


def classify_kind(url: str) -> str:
    if CHANNEL_RE.search(url):
        return "channel"
    if VIDEO_RE.search(url) or "youtu.be/" in url:
        return "single_video"
    return "single_video"  # bare youtube.com URL with no recognizable shape


def main() -> None:
    if not RECON_JSONL.exists():
        print(f"missing {RECON_JSONL}", file=sys.stderr)
        sys.exit(1)

    # Collect existing URLs to dedupe against (read outside the lock --
    # this script only appends, and a concurrent appender only adds rows,
    # never removes, so a slightly-stale read only risks a rare duplicate
    # row rather than data loss).
    existing_urls: set[str] = set()
    if LEADS_CSV.exists():
        with open(LEADS_CSV, encoding="utf-8") as f:
            for line in f:
                if line.startswith("#") or line.startswith("channel_url,"):
                    continue
                first_field = line.split(",", 1)[0].strip()
                if first_field:
                    existing_urls.add(first_field)

    new_rows = []
    seen_this_run: set[str] = set()
    n_channel = 0
    n_video = 0

    with open(RECON_JSONL, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            gov_id = rec.get("gov_id", "")
            name = rec.get("name", "")
            state = rec.get("state", "")

            candidate_urls: list[str] = []
            candidate_urls.extend(all_urls_from_record(rec))
            for link in (rec.get("homepage") or {}).get("links") or []:
                href = link.get("href")
                if href:
                    candidate_urls.append(href)

            for u in candidate_urls:
                if not is_youtube_url(u):
                    continue
                if u in existing_urls or u in seen_this_run:
                    continue
                seen_this_run.add(u)
                kind = classify_kind(u)
                if kind == "channel":
                    n_channel += 1
                else:
                    n_video += 1
                new_rows.append(
                    {
                        "channel_url": u,
                        "gov_id": gov_id,
                        "government": name,
                        "state": state,
                        "source_wo": "WO-323",
                        "kind": kind,
                        "verified": "false",
                        "note": "recon/homepage link, not hand-verified, never fetched",
                    }
                )

    if not new_rows:
        print("no new youtube.com/youtu.be leads found (0 channel, 0 single_video)")
        return

    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    lock_fd = open(LEADS_LOCK, "w")
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        # Re-check existing URLs under the lock in case a sibling WO
        # appended between our read above and now.
        existing_urls2: set[str] = set()
        if LEADS_CSV.exists():
            with open(LEADS_CSV, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("#") or line.startswith("channel_url,"):
                        continue
                    first_field = line.split(",", 1)[0].strip()
                    if first_field:
                        existing_urls2.add(first_field)

        rows_to_write = [r for r in new_rows if r["channel_url"] not in existing_urls2]
        if not rows_to_write:
            print("all candidate leads were already present (race with a sibling WO)")
            return

        file_exists = LEADS_CSV.exists()
        with open(LEADS_CSV, "a", newline="", encoding="utf-8") as out:
            writer = csv.DictWriter(out, fieldnames=FIELDNAMES)
            if not file_exists:
                writer.writeheader()
            for r in rows_to_write:
                writer.writerow(r)

        actual_channel = sum(1 for r in rows_to_write if r["kind"] == "channel")
        actual_video = sum(1 for r in rows_to_write if r["kind"] == "single_video")
        print(
            f"appended {len(rows_to_write)} new leads to {LEADS_CSV} "
            f"({actual_channel} channel, {actual_video} single_video); "
            f"never fetched any of them"
        )
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


if __name__ == "__main__":
    main()
