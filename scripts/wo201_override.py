"""WO-201 one-off: re-key three pages to the three governments this WO
minted (Pennsylvania Department of Transportation, Upper Delaware
Council, Southwestern Pennsylvania Commission), once those curated rows
have actually deployed.

- 8434: the Solebury Township, PA page WO-199 keyed to us:state:42 as a
  stopgap -- its video is a PennDOT public meeting, not a state
  legislative/executive meeting.
- 8501: the Upper Delaware Council video ingested by WO-201, currently
  gov_id=rtr:unknown:www.youtube.com (no pin matched yet).
- 8502: the Southwestern Pennsylvania Commission video ingested by
  WO-201, currently gov_id=us:cousub:4212966376 (Rostraver Township, PA)
  -- the OLD wrong per-video pin WO-199 says it removed is still live on
  the deployed Archive (same deploy-lag shape as the other two).

Same shape as scripts/wo199_override.py -- uses the existing
POST /internal/jurisdiction/override endpoint, a narrow, id-scoped write
(never a bulk DB sweep). Never prints ARCHIVE_INGEST_TOKEN.

As of 2026-09-11 all three fail with a 400 ("unknown gov_id") because the
Archive service's own deployed copy of curated_governments.csv does not
yet have the three new rows -- that only happens after this PR merges
AND the Archive is redeployed (see CLAUDE.md's "Deploys are manual"
bullet). Re-run this (--apply once dry run looks right) after that
deploy.

Usage: python scripts/wo201_override.py [--apply]
"""

import argparse
import os

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import asyncio  # noqa: E402
import json  # noqa: E402

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

# (page_id, correct gov_id, label)
CORRECTIONS = [
    (
        8434,
        "rtr:us:pa:pennsylvania-department-of-transportation",
        "Solebury video -> PennDOT (new curated gov)",
    ),
    (
        8501,
        "rtr:us:ny:upper-delaware-council",
        "UDC video -> Upper Delaware Council (new curated gov)",
    ),
    (
        8502,
        "rtr:us:pa:southwestern-pennsylvania-commission",
        "SPC video -> Southwestern PA Commission (new curated gov)",
    ),
]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    base = os.environ["ARCHIVE_BASE_URL"].rstrip("/")
    token = os.environ["ARCHIVE_INGEST_TOKEN"]
    headers = {"Authorization": f"Bearer {token}"}
    async with aiohttp.ClientSession(headers=headers) as sess:
        for page_id, gov_id, label in CORRECTIONS:
            params = {
                "ids": str(page_id),
                "gov_id": gov_id,
                "dry_run": "false" if args.apply else "true",
            }
            async with sess.post(
                f"{base}/internal/jurisdiction/override", params=params
            ) as resp:
                data = await resp.json()
            print(f"--- {label} (id={page_id} -> {gov_id}) ---")
            print(json.dumps(data, indent=2)[:2000])


if __name__ == "__main__":
    asyncio.run(main())
