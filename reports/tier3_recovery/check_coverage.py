"""Step 3: for each resolved gov_id in resolved_257.jsonl, check the live
Archive for an existing hub page and its newest page date. Appends to
coverage_257.jsonl (resumable). One host (redtaperecordings.com), so a
flat 3s-apart rate limit applies to every request against it.
"""
import os
import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import sys
import json
import re
import time
import asyncio
from pathlib import Path
from datetime import date, timedelta
from urllib.parse import quote

import aiohttp

sys.path.insert(0, ".")
from app.utils.gov_registry.registry import government_for_id

REPORTS = Path("reports/tier3_recovery")
RESOLVED = REPORTS / "resolved_257.jsonl"
OUT = REPORTS / "coverage_257.jsonl"
BASE = "https://redtaperecordings.com"
HOST_MIN_INTERVAL = 3.0
STALE_AFTER = timedelta(days=365 * 2)

_last_request_at = 0.0


async def polite_wait():
    global _last_request_at
    elapsed = time.monotonic() - _last_request_at
    if elapsed < HOST_MIN_INTERVAL:
        await asyncio.sleep(HOST_MIN_INTERVAL - elapsed)
    _last_request_at = time.monotonic()


def norm_label(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


async def check_one(session: aiohttp.ClientSession, gov_id: str) -> dict:
    gov = government_for_id(gov_id)
    out = {"gov_id": gov_id}
    if gov is None:
        out["error"] = "government_for_id returned None"
        return out
    out["gov_name"] = gov.gov_name
    out["state"] = gov.state
    query = f"{gov.gov_name}, {gov.state}" if gov.state else gov.gov_name

    await polite_wait()
    try:
        async with session.get(f"{BASE}/api/jurisdictions", params={"q": query}, timeout=20) as resp:
            data = await resp.json()
    except Exception as e:
        out["error"] = f"jurisdictions search failed: {type(e).__name__}: {e}"
        return out

    target = norm_label(query)
    match = None
    for m in data.get("matches", []):
        if norm_label(m.get("label", "")) == target:
            match = m
            break
    if match is None:
        out["has_page"] = False
        out["hub_link"] = None
        return out

    out["has_page"] = True
    out["hub_link"] = match["link"]

    await polite_wait()
    try:
        async with session.get(f"{BASE}{match['link']}", timeout=20) as resp:
            html = await resp.text()
    except Exception as e:
        out["error"] = f"hub fetch failed: {type(e).__name__}: {e}"
        return out

    dates = re.findall(r'datetime="(\d{4}-\d{2}-\d{2})"', html)
    if not dates:
        out["newest_page_date"] = None
        out["stale"] = None
        return out
    newest = max(dates)
    out["newest_page_date"] = newest
    y, mo, d = map(int, newest.split("-"))
    out["stale"] = (date.today() - date(y, mo, d)) > STALE_AFTER
    return out


async def main():
    rows = [json.loads(l) for l in RESOLVED.read_text().splitlines()]
    gov_ids = sorted({r["gov_id"] for r in rows if r.get("gov_id")})
    print(f"{len(gov_ids)} distinct resolved governments to check", flush=True)

    done = set()
    if OUT.exists():
        for l in OUT.read_text().splitlines():
            if l.strip():
                done.add(json.loads(l)["gov_id"])

    async with aiohttp.ClientSession(headers={"User-Agent": "Mozilla/5.0 (compatible; rtr-deeplink-tier3-recovery/1.0)"}) as session:
        with open(OUT, "a") as f:
            for i, gov_id in enumerate(gov_ids, 1):
                if gov_id in done:
                    continue
                result = await check_one(session, gov_id)
                f.write(json.dumps(result) + "\n")
                f.flush()
                print(f"[{i}/{len(gov_ids)}] {gov_id} -> has_page={result.get('has_page')} "
                      f"newest={result.get('newest_page_date')} stale={result.get('stale')}", flush=True)

    print("DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
