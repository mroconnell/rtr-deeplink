"""WO-356 item 5: finish the deeper-walk finds for Hamburg village, NY
(tier 1, real captions -- ingest) and Del Mar city, CA (tier 3, real
video no captions, 185.1 min with no shorter on-mission alternative on
the same tenant's 2-candidate listing -- queue directly per CLAUDE.md's
"long-only videos" rule, don't defer for length alone)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import aiohttp
import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from dotenv import load_dotenv  # noqa: E402

load_dotenv("/Users/mroconnell/Documents/rtr-deeplink/.env")

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import resolve_via_platform  # noqa: E402
from app.platforms.queue_probe import (  # noqa: E402
    TENANT_OVERRIDES_CSV,
    TIER3_QUEUE_FILE,
    append_queue_line,
    write_pin_row,
)
from app.utils.url_normalize import normalize_url  # noqa: E402

register_all_finders()


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
    # --- Hamburg village, NY: tier 1, ingest ---
    hamburg_url = "https://hamburgny.new.swagit.com/videos/398870"
    pinned = write_pin_row(
        host="hamburgny.new.swagit.com",
        match="",
        gov_id="us:place:3631643",
        strength="fallback",
        source="wo356",
        evidence=(
            "Hamburg village, NY -- WO-349 rejected this government's "
            "recorded hub_url as a decorative site-builder header clip "
            "(hellonation.com/media/hn_hdr26.mp4, shared across many "
            "elocallink.tv-powered small-town sites). WO-356 (2026-09-13) "
            "walked deeper on the government's own real CivicPlus "
            "AgendaCenter listing per Ryan's rule (keep walking a "
            "rejected off-mission/decorative candidate until a real "
            "meeting is seen) and found a real, current, on-mission Town "
            "Board meeting with real captions ('Aug 24, 2026 8-24-2026 TB "
            "Meeting', 2026-08-24) on the town's own Swagit tenant."
        ),
        pins_path=TENANT_OVERRIDES_CSV,
    )
    print(f"hamburg pin written: {pinned}")

    result = await resolve_via_platform(hamburg_url)
    print(
        "hamburg resolve -- title:",
        result.title,
        "| date:",
        result.date,
        "| jurisdiction:",
        result.jurisdiction,
        "| segments:",
        len(result.segments or []),
    )
    if not result.segments:
        print("SKIP hamburg: no segments at ingest time -- refusing")
    else:
        payload = result.model_dump()
        payload["gov_id"] = "us:place:3631643"
        async with aiohttp.ClientSession() as session:
            response = await ingest(session, payload, normalize_url(hamburg_url))
        print("HAMBURG INGESTED:", response.get("page_id"), response.get("slug", ""))

    await asyncio.sleep(1.5)

    # --- Del Mar city, CA: tier 3, queue directly (long, no shorter alt) ---
    delmar_url = (
        "https://d2vr3rrbtycvrt.cloudfront.net/delmar-ccm-20260908/videos/"
        "full/mp4/delmar-ccm-20260908_720.mp4"
    )
    pinned2 = write_pin_row(
        host="d2vr3rrbtycvrt.cloudfront.net",
        match="",
        gov_id="us:place:0618506",
        strength="fallback",
        source="wo356",
        evidence=(
            "Del Mar city, CA -- WO-349 rejected this government's "
            "recorded video (vimeo.com/1103304495) as an unrelated "
            "'Trekking to Mt. Everest Base Camp' video ranked ahead of "
            "the real meeting on the same AgendaCenter listing. WO-356 "
            "(2026-09-13) walked the listing one candidate deeper "
            "(2 of 2 real candidates total) and found the real meeting "
            "video, a direct CloudFront MP4 named for the government and "
            "date (delmar-ccm-20260908 -- 'Del Mar CCM', 2026-09-08), "
            "185.1 min. No shorter on-mission alternative exists on this "
            "2-candidate listing, so per CLAUDE.md's long-only-videos "
            "rule this is queued directly rather than deferred."
        ),
        pins_path=TENANT_OVERRIDES_CSV,
    )
    print(f"delmar pin written: {pinned2}")
    queued = append_queue_line(delmar_url, delmar_url, queue_path=TIER3_QUEUE_FILE)
    print(f"delmar queued: {queued}")


if __name__ == "__main__":
    asyncio.run(main())
