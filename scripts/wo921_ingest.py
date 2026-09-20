#!/usr/bin/env python3
"""WO-921: ingest the hand-read Sliq Harmony state-legislature candidates.

RUN THIS ONLY AFTER the resolver deploy that carries `app/platforms/
sliq_harmony.py` and the seven per-tenant pins (the deploy is Ryan's; nothing
here was ingested by WO-921 itself). It is one meeting per state, chosen and
hand-read in `rtr-business/research/wo921_handread.csv`. Each payload carries
the state's own `gov_id` (D1: one government per state, the chamber or
committee is `meeting_body`), so a page keys correctly even before its pin is
live: `archive/db/crud.py`'s `_resolve_page_government()` honours
`payload["gov_id"]`.

A pick with real captions (`segments`) is ingested as a page. A pick with no
captions (Kansas) is NOT ingested here: a page for a captionless meeting comes
from the tier-3 transcription queue, and its queue line goes in
`scripts/tier3_auto_transcription_queue.txt` after `scripts/probe_tier3_queue.py`
accepts it (the probe result is in the hand-read file). The script prints that
line and skips the pick.

`--dry-run` resolves through the real adapter and prints; without it each
captioned pick is POSTed to `/internal/ingest` through
`scripts.bulk_ingest._ingest`. The Archive token is loaded from the shared
checkout's .env by explicit path and never printed.

    DATABASE_URL="sqlite+aiosqlite:////tmp/wo921_scratch.db" PYTHONPATH=. \\
        .venv/bin/python scripts/wo921_ingest.py --dry-run
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo921_scratch.db" PYTHONPATH=. \\
        .venv/bin/python scripts/wo921_ingest.py

Afterwards, for each created page, confirm it is keyed with a backfill dry run
(never `--apply`), and re-read any page with
`GET /admin/recheck-archive-page?url=<the meeting url>` (admin token header, see
that route in app/main.py; never print the token).
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

from scripts.youtube_fetch_guard import install as install_youtube_guard  # noqa: E402

install_youtube_guard()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import detect_platform, get_finder  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402
from app.utils.video_hand_check import classify_video_hand_check  # noqa: E402
from scripts.bulk_ingest import _ingest  # noqa: E402

register_all_finders()

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
OUT_CSV = RESEARCH_DIR / "wo921_ingested.csv"

_H = "https://sg001-harmony.sliq.net"
_P = "Harmony/en/PowerBrowser/PowerBrowserV3"

# (gov_id, state, url) -- one hand-read meeting per state; see
# rtr-business/research/wo921_handread.csv for the title/room/duration read.
PICKS = [
    ("us:state:05", "Arkansas", f"{_H}/00284/{_P}/20260917/-1/34484"),
    ("us:state:08", "Colorado", f"{_H}/00327/{_P}/20260903/-1/17848"),
    ("us:state:10", "Delaware", f"{_H}/00329/{_P}/20260831/-1/6719"),
    ("us:state:20", "Kansas", f"{_H}/00287/{_P}/20260831/-1/22675"),
    ("us:state:35", "New Mexico", f"{_H}/00293/{_P}/20260911/-1/81073"),
    ("us:state:40", "Oklahoma", f"{_H}/00283/{_P}/20260916/-1/56256"),
    ("us:state:54", "West Virginia", f"{_H}/00289/{_P}/20260914/-1/59070"),
]

FIELDS = [
    "gov_id",
    "state",
    "url",
    "title",
    "date",
    "segments",
    "meeting_body",
    "hand_check",
    "result",
    "page_url",
]


async def main(dry: bool, only: str) -> None:
    rows = []
    async with aiohttp.ClientSession() as session:
        for gov_id, state, url in PICKS:
            if only and only not in url:
                continue
            platform = detect_platform(url)
            res = await get_finder(platform).resolve(url)
            hc = classify_video_hand_check(
                res.title, res.jurisdiction or "", state, "state"
            )
            payload = res.model_dump()
            payload["gov_id"] = gov_id
            row = {
                "gov_id": gov_id,
                "state": state,
                "url": url,
                "title": res.title,
                "date": res.date,
                "segments": len(res.segments or []),
                "meeting_body": res.meeting_body,
                "hand_check": hc or "",
                "result": "dry-run",
                "page_url": "",
            }
            print(row, flush=True)
            if hc:
                row["result"] = f"skipped: hand-check {hc}"
            elif not res.video_url:
                row["result"] = "skipped: no video (agenda-only is never ingested)"
            elif not res.segments:
                row["result"] = (
                    "skipped: video, no captions -> tier-3 queue line "
                    f"{normalize_url(res.source_url)}"
                )
                print("  ->", row["result"], flush=True)
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
