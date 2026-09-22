#!/usr/bin/env python3
"""WO-1010: Task 2 (Invintus) real picks.

1. Washington/TVW (tvw.org) -- a genuinely new Invintus tenant (clientID
   9375922947), found by WO-1009's recon and adapted here (see tvw.py's
   own module docstring): a real Senate Housing committee meeting, real
   coherent captions confirmed live. Ingested as a page.

2. Vancouver, WA City Council and Clark County, WA Council -- a
   THIRD real government pair found on the SAME clientID
   (2917038973) already referenced (but never given a number) in
   invintus.py's own module docstring as "Clark County, WA (a Planning
   Commission...)". `Search/general` against that clientID shows it's a
   shared regional media system (CVTV, Clark/Vancouver Television)
   serving several distinct real bodies: Vancouver City Council, City
   Council Workshops, Clark County Council, Clark County Land Use
   Hearings, the Planning Commission, and more. Neither Vancouver city
   (currently CivicClerk with `meeting-without-video`) nor Clark County
   (currently `no-platform-link-found`, YouTube fallback only) has any
   real video coverage in jurisdiction_coverage.csv today, so both are a
   real, first-ever gap close. No captions on either (captionPath null,
   consistent with every non-legislature Invintus tenant found so far --
   University Place, Des Moines, Leon County) -> tier-3 queue. Picks are
   both under the 90-minute tier-3 defer threshold on purpose, so they
   land in the real queue immediately rather than the deferred file:
   Vancouver's "City Council Workshops (09-21-26)" (57 min) and Clark
   County's "Clark County Council (08-18-26)" (60 min) -- confirmed via
   a real `Event/getDetailed` read before picking, not guessed from
   `runtimeMinutes` alone.

    DATABASE_URL="sqlite+aiosqlite:////tmp/wo1010_scratch.db" PYTHONPATH=. \\
        .venv/bin/python scripts/wo1010_invintus_finish.py --dry-run
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo1010_scratch.db" PYTHONPATH=. \\
        .venv/bin/python scripts/wo1010_invintus_finish.py
"""

from __future__ import annotations

import argparse
import asyncio
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
from app.platforms.queue_probe import finish_candidate  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402
from scripts.bulk_ingest import _ingest  # noqa: E402

register_all_finders()

INGEST_PICKS = [
    (
        "us:state:53",
        "Washington (TVW)",
        "https://tvw.org/video/senate-housing-2026091165/",
    ),
]

QUEUE_PICKS = [
    (
        "us:place:5374060",
        "Vancouver, WA",
        "https://player.invintus.com/?clientID=2917038973&eventID=2026091015",
    ),
    (
        "us:county:53011",
        "Clark County, WA",
        "https://player.invintus.com/?clientID=2917038973&eventID=2026081016",
    ),
]


async def _do_ingest_pick(
    session: aiohttp.ClientSession, gov_id: str, label: str, url: str, dry: bool
) -> None:
    platform = detect_platform(url)
    res = await get_finder(platform).resolve(url)
    print(f"[{label}] {url}")
    print(f"  title={res.title!r} date={res.date} video_url={res.video_url!r}")
    print(
        f"  segments={len(res.segments or [])} transcript_warnings={res.transcript_warnings}"
    )
    if not res.segments:
        print("  ** no real captions -- should be a QUEUE pick, not an ingest pick **")
        return
    if dry:
        print("  -> dry-run: would POST this to /internal/ingest")
        return
    payload = res.model_dump()
    payload["gov_id"] = gov_id
    resp = await _ingest(session, payload, normalize_url(res.source_url or url))
    if resp is None:
        print("  -> ingest-failed")
    else:
        print(
            f"  -> {'created' if resp.get('created') else 'existing'} {resp.get('url') or ''}"
        )


async def _do_queue_pick(gov_id: str, label: str, url: str, dry: bool) -> None:
    platform = detect_platform(url)
    res = await get_finder(platform).resolve(url)
    print(f"[{label}] {url}")
    print(f"  title={res.title!r} date={res.date} video_url={res.video_url!r}")
    print(
        f"  segments={len(res.segments or [])} transcript_warnings={res.transcript_warnings}"
    )
    if res.segments:
        print("  ** has real captions -- should be an INGEST pick, not a queue pick **")
        return
    if not res.video_url:
        print("  -> SKIP: no video_url resolved")
        return
    if dry:
        print("  -> dry-run: would call finish_candidate() to queue this")
        return
    outcome = await finish_candidate(
        url,
        video_url=res.video_url,
        source_url=res.source_url or url,
        platform=platform,
        video_format=res.video_format,
        gov_id=gov_id,
        jurisdiction=res.jurisdiction or label,
        title=res.title or "",
        caller="wo1010_invintus_finish",
    )
    print(f"  -> action={outcome.action} probe_verdict={outcome.probe.verdict}")


async def main(dry: bool) -> None:
    async with aiohttp.ClientSession() as session:
        for gov_id, label, url in INGEST_PICKS:
            await _do_ingest_pick(session, gov_id, label, url, dry)
            await asyncio.sleep(2)

    for gov_id, label, url in QUEUE_PICKS:
        await _do_queue_pick(gov_id, label, url, dry)
        await asyncio.sleep(2)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    asyncio.run(main(args.dry_run))
