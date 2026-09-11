"""WO-206 one-off: correct the gov_id on the six live pages the
blank-match `vimeo.com` tenant-override wildcard mislabeled "Oak Bluffs,
MA" (`us:cousub:2500750390`) -- see BACKLOG.md's "Oak Bluffs" entry and
BACKLOG_DONE.md's WO-183/WO-187 writeups for the root cause (fixed on
main, but the already-mislabeled pages needed a direct correction).

Each government below was identified from the video's own Vimeo oEmbed
(`https://vimeo.com/api/oembed.json?url=...`) `author_name`/`author_url`
plus, for four of the six, an existing `tenant_overrides.csv` pin already
confirmed by WO-183/WO-187 the same night. All six target gov_ids are
national/derivable ids already resolvable against the currently-deployed
registry (US county/cousub/place tables, not a new curated row) --
unlike WO-201's three re-keys, no deploy is needed before this script's
`--apply` run actually takes effect. See `research/wo206_report.csv` for
the full evidence trail.

Uses the existing POST /internal/jurisdiction/override endpoint, a
narrow, id-scoped write (never a bulk DB sweep). Never prints
ARCHIVE_INGEST_TOKEN.

Usage: python scripts/wo206_override.py [--apply]
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
        7097,
        "us:county:42071",
        "Lancaster County PA Commissioner meeting -> Lancaster County, PA",
    ),
    (
        7863,
        "us:cousub:3301101300",
        "Planning Board Sept 2 2026 video -> Amherst town, NH",
    ),
    (
        8192,
        "us:cousub:4209532432",
        "Board of Supervisors 4.14.26 video -> Hanover township, PA",
    ),
    (
        8309,
        "us:place:4126050",
        "Florence Urban Renewal Agency video -> Florence city, OR",
    ),
    (
        8483,
        "us:county:27147",
        "SC Board Meeting video -> Steele County, MN",
    ),
    (
        8494,
        "us:cousub:4204549136",
        "Sept 2 2026 Council Meeting video -> Middletown township, PA",
    ),
]

# NOTE on the seventh case (Spring Township, PA / Pennsylvania Public
# Utility Commission): that page (id 8466) was already deleted by a
# concurrent WO-183 hand-check before this WO started (confirmed live --
# a full corpus scan of /internal/export/pages found no page under that
# slug or with this video). The new `rtr:us:pa:pennsylvania-public-
# utility-commission` government (minted by this WO in
# curated_governments.csv) and its youtube.com/@PennsylvaniaPUC pins
# exist so a FUTURE re-discovery of this or similar PA PUC content
# routes correctly -- there is no live page left to override, so no
# correction is queued here for it. If that curated row has not deployed
# yet and a future session needs to key a page to this government, the
# override call will fail with "unknown gov_id" until the next deploy,
# same shape as WO-201's PennDOT/UDC/SPC re-keys.


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
