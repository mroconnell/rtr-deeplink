"""WO-349: ingest the 8 hand-checked tier-1 CivicPlus-population finds
(video + real captions), out of 9 tier1 candidates from
`research/wo349_verify.csv` / `research/wo349_handcheck.csv`. Seward
city KS (us:place:2064100) is deliberately excluded: its own confirmed
tenant (`sewardcountyks.new.swagit.com`) and the resolved title ("Sep 08,
2026 County Commission-Work Session") both name Seward COUNTY, KS -- a
different real government from Seward CITY, KS -- Kind A, recorded in
`research/wo349_owner_bodies.csv` instead of ingested.

Sends `gov_id` in every ingest payload per CLAUDE.md's rule (WO-210 is
live).

Usage (repo root, shared venv):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo349_finish_tier1.db" \\
        .venv/bin/python scripts/wo349_finish_tier1.py
"""

from __future__ import annotations

import asyncio
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
        gov_id="us:place:5356695",
        name="Puyallup city, WA",
        url="https://cityofpuyallup.granicus.com/MediaPlayer.php?view_id=5&clip_id=2942",
    ),
    dict(
        gov_id="us:place:1834114",
        name="Hobart city, IN",
        url="https://cityofhobart.org/CivicMedia?VID=326",
    ),
    dict(
        gov_id="us:county:27047",
        name="Freeborn County, MN",
        url="https://freeborncomn.portal.civicclerk.com/event/555/media",
    ),
    dict(
        gov_id="us:place:1714065",
        name="Chicago Ridge village, IL",
        url="https://chicagoridge.org/CivicMedia?VID=265",
    ),
    dict(
        gov_id="us:place:4868624",
        name="Snyder city, TX",
        url="https://snydertx.gov/CivicMedia?VID=133",
    ),
    dict(
        gov_id="us:place:2012500",
        name="Chanute city, KS",
        url="https://chanute.org/CivicMedia?VID=698",
    ),
    dict(
        gov_id="us:place:0482740",
        name="Wickenburg town, AZ",
        url="https://public.destinyhosted.com/agenda_publish.cfm?id=94253",
    ),
    dict(
        gov_id="us:county:06091",
        name="Sierra County, CA",
        url="https://sierracounty.ca.gov/CivicMedia?VID=437",
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
            import json

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
            results.append((c["gov_id"], "ingested", response.get("page_id")))
            await asyncio.sleep(1.5)

    print("\n=== summary ===")
    for r in results:
        print(r)


asyncio.run(main())
