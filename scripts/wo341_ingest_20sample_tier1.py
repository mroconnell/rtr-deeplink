"""WO-341, 2026-09-13: ingest the ONE real tier-1 find from the CivicPlus
20-government sample (East Baton Rouge Parish, LA, us:county:22033 --
`https://batonrougela.new.swagit.com/videos/372848`, "Jan 21, 2026
Council Zoning", real captions). Hand-checked (classify_video_hand_check
+ a direct read of the title/segments) before this ran -- see the WO-341
final report for the sample table and the Pierce County WA/Hampden
County MA rows this deliberately does NOT touch (already queued by
another concurrent WO, per jurisdiction_coverage.csv's own `queued=true`
-- see the WO-341 report for why).

Sends `gov_id` in the ingest payload per CLAUDE.md's rule (WO-210 is
live) so this page is keyed correctly with no dependency on a pin
deploy.

Run once, from the repo root, with the shared venv active:
    DATABASE_URL=sqlite+aiosqlite:////tmp/wo341_ingest.db \
        python scripts/wo341_ingest_20sample_tier1.py
(ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN loaded explicitly from the
shared checkout's .env -- see this script's own load_dotenv() call --
since a worktree has none of its own.)
"""

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

GOV_ID = "us:county:22033"
URL = "https://batonrougela.new.swagit.com/videos/372848"


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
        if resp.status == 200:
            return await resp.json()
        text = await resp.text()
        raise RuntimeError(f"ingest failed ({resp.status}): {text[:300]}")


async def main():
    result = await resolve_via_platform(URL)
    print(
        "title:",
        result.title,
        "| date:",
        result.date,
        "| jurisdiction:",
        result.jurisdiction,
    )
    print(
        "segments:", len(result.segments), "| video_url:", (result.video_url or "")[:80]
    )
    if not result.segments:
        raise SystemExit("Expected real segments -- refusing to ingest without them.")

    payload = result.model_dump()
    payload["gov_id"] = GOV_ID

    async with aiohttp.ClientSession() as session:
        response = await ingest(session, payload, normalize_url(URL))
    print("INGESTED:", response)


asyncio.run(main())
