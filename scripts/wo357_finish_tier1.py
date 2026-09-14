"""WO-357: ingest the 2 hand-checked tier-1 finds from the CivicPlus
label-only bucket (`research/wo357_verify.csv` / `wo357_handcheck.csv`).

Both hand-confirmed real, current, correctly-named meetings of the
government itself:
  - Englewood city, OH (us:place:3925396): CivicMedia VID=106 on the
    government's own domain (englewood.oh.us), title "20260908 Council
    Meeting", 583 segments.
  - Rosetown, SK (ca:csd:4712006): CivicPlus/TikiLive embed on the
    government's own domain (www.rosetown.ca) -- the embed itself
    carries no title, but the source listing page
    (www.rosetown.ca/CivicMedia) names videoId=160396 explicitly as
    "June 1, 2026 Council Meeting" under a "Council Meetings" channel,
    1411 segments.

Sends `gov_id` in every ingest payload per CLAUDE.md's rule (WO-210 is
live).

Usage (repo root, shared venv):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo357_finish_tier1.db" \\
        .venv/bin/python scripts/wo357_finish_tier1.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import aiohttp
import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from dotenv import load_dotenv  # noqa: E402

load_dotenv("/Users/mroconnell/Documents/rtr-deeplink/.env")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.platforms.base import resolve_via_platform  # noqa: E402
from app.platforms import register_all_finders  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402

register_all_finders()

CANDIDATES = [
    dict(
        gov_id="us:place:3925396",
        name="Englewood city, OH",
        url="https://englewood.oh.us/CivicMedia?VID=106",
    ),
    dict(
        gov_id="ca:csd:4712006",
        name="Rosetown, SK",
        url="https://civplus.tikiliveapi.com/embed?scheme=embedVod&videoId=160396&autoplay=no",
    ),
]


def base_url():
    return os.environ.get("ARCHIVE_BASE_URL", "").rstrip("/")


def headers():
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


async def ingest(session, payload, input_url_normalized):
    body = dict(payload)
    body["input_url_normalized"] = input_url_normalized
    async with session.post(
        f"{base_url()}/internal/ingest",
        json=body,
        headers=headers(),
        timeout=aiohttp.ClientTimeout(total=65),
    ) as resp:
        text = await resp.text()
        if resp.status == 200:
            return json.loads(text)
        raise RuntimeError(f"ingest failed ({resp.status}): {text[:300]}")


async def main():
    results = []
    async with aiohttp.ClientSession() as session:
        for c in CANDIDATES:
            print(f"--- {c['gov_id']} {c['name']} ---")
            result = await resolve_via_platform(c["url"])
            print(
                "title:",
                result.title,
                "| date:",
                result.date,
                "| jurisdiction:",
                result.jurisdiction,
                "| segments:",
                len(result.segments),
                "| video_url:",
                (result.video_url or "")[:90],
            )
            if not result.segments:
                print("SKIP: no segments at ingest time (expected some) -- refusing")
                results.append((c["gov_id"], "skipped-no-segments"))
                continue
            payload = result.model_dump()
            payload["gov_id"] = c["gov_id"]
            response = await ingest(session, payload, normalize_url(c["url"]))
            print("INGESTED:", response.get("page_id"), response.get("slug", ""))
            results.append(
                (
                    c["gov_id"],
                    "ingested",
                    response.get("page_id"),
                    response.get("slug", ""),
                )
            )
            await asyncio.sleep(1.5)

    print("\n=== summary ===")
    for r in results:
        print(r)


asyncio.run(main())
