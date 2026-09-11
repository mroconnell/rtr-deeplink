"""WO-199 one-off: correct the gov_id on the 5 pages this WO just
ingested via bulk_ingest.py, which resolve against the currently-DEPLOYED
Archive (not this worktree's corrected tenant_overrides.csv -- pins only
reach new ingests after a deploy, see COVERAGE_HANDOVER.md section 3).
Uses the existing POST /internal/jurisdiction/override endpoint, a
narrow, id-scoped write (never a bulk DB sweep). Never prints
ARCHIVE_INGEST_TOKEN.

Usage: python scripts/wo199_override.py [--apply]
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
    (8431, "us:county:17031", "Lemont Township video -> Cook County Assessor"),
    (8432, "us:sd:5000402", "Middlebury ACSD video -> Addison Central USD"),
    (8434, "us:state:42", "Solebury video -> Pennsylvania (PennDOT)"),
    (8436, "us:cousub:5000144350", "Middlebury Selectboard -> Middlebury town"),
    (8438, "ca:csd:4811034", "Parkland County council meeting -> Parkland County"),
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
