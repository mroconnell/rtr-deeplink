"""WO-347 Part A hand-check helper: resolves every tier 1-3 candidate
`wo347_rerun_verify.csv` found and prints its real title/jurisdiction so
the hand-read gate has real evidence to read, not just a verdict string.

Never fetches a youtube.com/youtu.be URL directly -- the 3 youtube_lead
rows are printed with a note instead, and hand-verified separately via
YouTube's public oEmbed endpoint (title only, no captions/media, the
same "no API key or yt-dlp needed for a title-only check" method
ENUMERATION_METHODS.md §230 already uses).

Usage: DATABASE_URL=sqlite+aiosqlite:////tmp/wo347_handcheck.db \
    .venv/bin/python scripts/wo347_handcheck.py
"""

from __future__ import annotations

import asyncio
import csv
import os
import sys
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms.base import detect_platform, get_finder  # noqa: E402
from app.platforms import register_all_finders  # noqa: E402

register_all_finders()

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
VERIFY_CSV = RESEARCH_DIR / "wo347_rerun_verify.csv"


async def main():
    with open(VERIFY_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    candidates = [r for r in rows if r["tier"] in ("1", "2", "3")]
    print(f"{len(candidates)} tier 1-3 candidates to hand-check\n")

    for r in candidates:
        url = r["meeting_url"]
        print("=" * 100)
        print(
            f"{r['domain']} | {r['name']}, {r['state']} | tier={r['tier']} platform_hint={r['platform_hint']} resolved={r['resolved_platform']}"
        )
        print(f"  meeting_url: {url}")
        if "youtube.com" in url or "youtu.be" in url:
            print(
                "  -> YouTube-hosted. NOT fetched here. Hand-checked separately via oEmbed title."
            )
            continue
        try:
            platform = detect_platform(url)
            finder = get_finder(platform)
            result = await finder.resolve(url)
            print(f"  RESOLVED title: {result.title!r}")
            print(f"  RESOLVED jurisdiction: {result.jurisdiction!r}")
            print(f"  RESOLVED date: {result.date!r}")
            print(f"  RESOLVED meeting_body: {getattr(result, 'meeting_body', None)!r}")
            print(f"  RESOLVED video_url: {result.video_url}")
        except Exception as e:  # noqa: BLE001
            print(f"  RESOLVE FAILED: {type(e).__name__}: {str(e)[:300]}")


if __name__ == "__main__":
    asyncio.run(main())
