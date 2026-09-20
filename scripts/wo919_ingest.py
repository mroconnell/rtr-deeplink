#!/usr/bin/env python3
"""WO-919: ingest the hand-read tier-1 state-legislature meetings.

Every pick below was hand-read first (title, body, chamber, caption count
via scripts/wo919_peek.py) and is one meeting per (state, chamber), the
chamber carried as `meeting_body` and the STATE's own government id in
`payload["gov_id"]` (D1: one government per state; never a chamber-level id).
`_resolve_page_government()` honours `payload["gov_id"]`, so none of these
pages depends on a pin being deployed to key correctly.

`--dry-run` resolves and prints; without it each pick is POSTed to
`/internal/ingest` via scripts.bulk_ingest._ingest (which runs WO-144's
metadata-only duration probe first). The Archive token is loaded from the
shared checkout's .env by explicit path and never printed.

    DATABASE_URL="sqlite+aiosqlite:////tmp/wo919_scratch.db" PYTHONPATH=. \\
        .venv/bin/python scripts/wo919_ingest.py [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv("/Users/mroconnell/Documents/rtr-deeplink/.env")

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import detect_platform, get_finder  # noqa: E402
from app.platforms.passive_verify import _youtube_resolve_guard  # noqa: E402
from app.utils.gov_registry.registry import government_for_id  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402
from app.utils.video_hand_check import classify_video_hand_check  # noqa: E402
from scripts.bulk_ingest import _ingest  # noqa: E402

register_all_finders()

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
OUT_CSV = RESEARCH_DIR / "wo919_ingested.csv"

# (gov_id, state, chamber, meeting_body override or None, url)
PICKS = [
    ("us:state:04", "Arizona", "Arizona House of Representatives", None,
     "https://www.azleg.gov/videoplayer/?eventID=2026031068"),
    ("us:state:04", "Arizona", "Arizona Senate", None,
     "https://www.azleg.gov/videoplayer/?eventID=2026051023"),
    ("us:state:36", "New York", "New York State Assembly",
     "New York State Assembly",
     "https://nystateassembly.granicus.com/MediaPlayer.php?view_id=9&clip_id=9656"),
    ("us:state:27", "Minnesota", "Minnesota Senate",
     "Minnesota Senate Committee on Rules and Administration",
     "https://mnsenate.granicus.com/MediaPlayer.php?view_id=1&clip_id=13872"),
    ("us:state:44", "Rhode Island", "Rhode Island House of Representatives",
     "Rhode Island House of Representatives",
     "https://capitoltvri.cablecast.tv/show/12317"),
    ("us:state:44", "Rhode Island", "Rhode Island Senate",
     "Rhode Island Senate",
     "https://capitoltvri.cablecast.tv/show/12336"),
    ("us:state:06", "California", "California State Assembly",
     "Assembly Business and Professions Committee",
     "https://www.assembly.ca.gov/media/assembly-business-and-professions-committee-20260830"),
]

FIELDS = ["gov_id", "state", "chamber", "url", "title", "date", "segments",
          "meeting_body", "hand_check", "result", "page_url"]


async def main(dry: bool, only: str) -> None:
    rows = []
    async with aiohttp.ClientSession() as session:
        for gov_id, state, chamber, body, url in PICKS:
            if only and only not in url:
                continue
            platform = detect_platform(url)
            with _youtube_resolve_guard():
                res = await get_finder(platform).resolve(url)
            hc = classify_video_hand_check(res.title, res.jurisdiction or "", state, "state")
            if body and not res.meeting_body:
                res.meeting_body = body
            if not res.jurisdiction:
                gov = government_for_id(gov_id)
                if gov and gov.gov_name and gov.state:
                    res.jurisdiction = f"{gov.gov_name}, {gov.state}"
            payload = res.model_dump()
            payload["gov_id"] = gov_id
            row = {
                "gov_id": gov_id, "state": state, "chamber": chamber, "url": url,
                "title": res.title, "date": res.date,
                "segments": len(res.segments or []),
                "meeting_body": res.meeting_body, "hand_check": hc or "",
                "result": "dry-run", "page_url": "",
            }
            print(row, flush=True)
            if hc:
                row["result"] = f"skipped: hand-check {hc}"
            elif not dry:
                resp = await _ingest(session, payload, normalize_url(res.source_url))
                if resp is None:
                    row["result"] = "ingest-failed"
                else:
                    row["result"] = "created" if resp.get("created") else "existing"
                    row["page_url"] = resp.get("url") or ""
                print("  ->", row["result"], row["page_url"], flush=True)
            rows.append(row)
            await asyncio.sleep(2)
    if not dry:
        new = not OUT_CSV.exists()
        with open(OUT_CSV, "a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerows(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default="", help="only picks whose url contains this")
    a = ap.parse_args()
    asyncio.run(main(a.dry_run, a.only))
