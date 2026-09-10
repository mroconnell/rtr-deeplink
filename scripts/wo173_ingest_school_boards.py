"""WO-173: ingest one picked meeting each for the three Virginia school
boards found by WO-172's Wistia discovery list (rtr-business/research/
wo172_wistia_candidates.csv), through the WO-161 adapter. Reuses the same
resolve/probe/ingest pieces scripts/wo134_confirmed_hits_ingest.py already
established (WistiaAssetFinder.resolve_media_id, queue_probe.probe_queue_entry,
scripts/bulk_ingest._ingest/_base_url), rather than a parallel
reimplementation.

Not a general-purpose sweep script -- this is a short, one-off driver for
three known (gov_id, channel_id, hashed_id) tuples, picked by hand per
today's selection rule (newest complete regular meeting 9-40 minutes,
else the shortest available; documented in scripts/wo173_scratch_pick*.py
this run, not committed).
"""

import asyncio
import json
import os
import sys
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.wistia import WistiaAssetFinder  # noqa: E402
from app.platforms import queue_probe  # noqa: E402

register_all_finders()
from app.utils.gov_registry.registry import government_for_id  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402
from scripts.bulk_ingest import _base_url, _ingest  # noqa: E402

PICKS = [
    {
        "gov_id": "us:sd:5102360",
        "unit_name": "Manassas City Public Schools",
        "account": "amsva",
        "hashed_id": "ggqadf98sn",
        "title_hint": "Manassas School Board 6/23/2026",
    },
    {
        "gov_id": "us:sd:5101510",
        "unit_name": "Fredericksburg City Public Schools",
        "account": "amsva",
        "hashed_id": "4kg48o0zte",
        "title_hint": "Special Fredericksburg School Board 8/3/2026",
    },
    {
        "gov_id": "us:sd:5103660",
        "unit_name": "Stafford County Public Schools",
        "account": "amsva",
        "hashed_id": "pnx2vhdqq1",
        "title_hint": "Stafford School Board 2/26/2026",
    },
]

TENANT_OVERRIDES_CSV = (
    REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "tenant_overrides.csv"
)


async def main():
    print(f"ARCHIVE_BASE_URL={_base_url()!r}")
    async with aiohttp.ClientSession() as session:
        for pick in PICKS:
            gov_id = pick["gov_id"]
            unit_name = pick["unit_name"]
            hashed_id = pick["hashed_id"]
            account = pick["account"]
            print(f"\n=== {unit_name} ({gov_id}) media={hashed_id} ===")

            canonical_url = f"https://{account}.wistia.com/medias/{hashed_id}"

            probe = await queue_probe.probe_queue_entry(
                canonical_url, platform="wistia"
            )
            print(
                f"  probe verdict={probe.verdict} reason={probe.reason} duration={probe.duration_seconds}"
            )
            if probe.verdict not in ("accept", "flag-long"):
                print(f"  REJECTED by probe, skipping {unit_name}")
                continue

            result = await WistiaAssetFinder.resolve_media_id(
                hashed_id,
                account=account,
                title_hint=pick["title_hint"],
            )
            print(
                f"  title={result.title!r} date={result.date} segments={len(result.segments or [])}"
            )
            print(f"  video_url={'yes' if result.video_url else 'NONE'}")
            print(f"  transcript_warnings={result.transcript_warnings}")

            if not result.segments:
                print(
                    f"  NO CAPTIONS -- would be tier-3, not tier-1. Skipping ingest for {unit_name}."
                )
                continue

            gov = government_for_id(gov_id)
            if not (gov and gov.gov_name and gov.state):
                print(
                    f"  ERROR: government_for_id({gov_id!r}) did not resolve -- aborting this row"
                )
                continue
            result.jurisdiction = f"{gov.gov_name}, {gov.state}"
            result.source_url = canonical_url

            normalized = normalize_url(canonical_url)
            response = await _ingest(session, result.model_dump(), normalized)
            print(f"  INGEST RESPONSE: {json.dumps(response)}")

            # Fallback per-media pin -- shared amsva.wistia.com account.
            row = {
                "tenant_host": f"{account}.wistia.com",
                "match": f"external_id={result.external_id}",
                "gov_id": gov_id,
                "strength": "fallback",
                "source": "wo173_wistia_candidates",
                "evidence": (
                    f"{unit_name} -- WO-173 (from WO-172's discovery list), "
                    f"{pick['title_hint']}, real segments+video live; shared "
                    f"{account}.wistia.com account, pinned per-media"
                ),
            }
            existing = set()
            if TENANT_OVERRIDES_CSV.exists():
                import csv

                with TENANT_OVERRIDES_CSV.open(newline="", encoding="utf-8") as f:
                    for r in csv.DictReader(f):
                        existing.add((r.get("tenant_host", ""), r.get("match", "")))
            key = (row["tenant_host"], row["match"])
            if key in existing:
                print(
                    f"  tenant_overrides.csv row already present for {key}, skipping append"
                )
            else:
                import csv

                is_new = not TENANT_OVERRIDES_CSV.exists()
                with TENANT_OVERRIDES_CSV.open("a", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(
                        f,
                        fieldnames=[
                            "tenant_host",
                            "match",
                            "gov_id",
                            "strength",
                            "source",
                            "evidence",
                        ],
                        lineterminator="\n",
                    )
                    if is_new:
                        writer.writeheader()
                    writer.writerow(row)
                print(f"  appended tenant_overrides.csv row for {key}")

            await asyncio.sleep(2)


asyncio.run(main())
