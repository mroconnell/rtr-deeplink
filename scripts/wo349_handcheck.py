"""WO-349: hand-check driver for the 32 tier1/tier3 candidates from
`research/wo349_verify.csv`. Resolves each candidate's own meeting_url
via `resolve_via_platform()` (never a youtube.com/youtu.be URL -- none of
these 32 rows are YouTube), runs `classify_video_hand_check()` as the
automatic pre-filter, and prints title/date/jurisdiction/segments for a
human read against the government's own name+state.

Usage:
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo349_handcheck.db" \\
        .venv/bin/python scripts/wo349_handcheck.py
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

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import resolve_via_platform  # noqa: E402
from app.utils.video_hand_check import classify_video_hand_check  # noqa: E402

register_all_finders()

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
VERIFY_CSV = RESEARCH_DIR / "wo349_verify.csv"
OUT_CSV = RESEARCH_DIR / "wo349_handcheck.csv"


def load_candidates():
    rows = []
    with open(VERIFY_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("tier") in ("1", "3"):
                rows.append(row)
    return rows


async def check_one(row):
    url = row["meeting_url"]
    out = dict(row)
    out["resolved_title"] = ""
    out["resolved_date"] = ""
    out["resolved_jurisdiction"] = ""
    out["segments"] = 0
    out["hand_check_verdict"] = ""
    out["hand_check_owner"] = ""
    out["resolve_error"] = ""
    try:
        result = await resolve_via_platform(url)
    except Exception as e:  # noqa: BLE001
        out["resolve_error"] = f"{type(e).__name__}: {str(e)[:250]}"
        return out
    out["resolved_title"] = result.title or ""
    out["resolved_date"] = str(result.date or "")
    out["resolved_jurisdiction"] = result.jurisdiction or ""
    out["segments"] = len(result.segments or [])
    verdict = classify_video_hand_check(
        result.title or "", result.jurisdiction or "", row.get("name", ""), "place"
    )
    if verdict is None:
        out["hand_check_verdict"] = "none"
        out["hand_check_owner"] = ""
    else:
        kind, reason = verdict
        out["hand_check_verdict"] = kind
        out["hand_check_owner"] = reason
    return out


async def main():
    candidates = load_candidates()
    print(f"{len(candidates)} tier1/tier3 candidates to hand-check")
    fieldnames = list(candidates[0].keys()) + [
        "resolved_title",
        "resolved_date",
        "resolved_jurisdiction",
        "segments",
        "hand_check_verdict",
        "hand_check_owner",
        "resolve_error",
    ]
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader()
        for i, row in enumerate(candidates, 1):
            result = await check_one(row)
            writer.writerow(result)
            out.flush()
            print(
                f"[{i}/{len(candidates)}] {row['gov_id']} {row['name']} {row['state']} "
                f"tier={row['tier']} | title={result['resolved_title'][:70]!r} "
                f"date={result['resolved_date']} segs={result['segments']} "
                f"handcheck={result['hand_check_verdict']} err={result['resolve_error'][:80]}"
            )


asyncio.run(main())
