#!/usr/bin/env python3
"""WO-1010 recon: list each Sliq Harmony tenant's recent-events listing
(title/date only, one request per tenant) so the picks in
scripts/wo1010_sweep.py can be hand-chosen from real data. Read-only,
never resolves an individual event page."""

import asyncio
import os
import sys
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv  # noqa: E402

load_dotenv("/Users/mroconnell/Documents/rtr-deeplink/.env")

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import CalendarPageError, get_finder  # noqa: E402

register_all_finders()

_H = "https://sg001-harmony.sliq.net"

TENANTS = [
    ("Arkansas", "00284", {"34484"}),
    ("Colorado", "00327", {"17848"}),
    ("Delaware", "00329", {"6719"}),
    ("Kansas", "00287", {"22675"}),
    ("New Mexico", "00293", {"81073"}),
    ("Oklahoma (House)", "00283", {"56256"}),
    ("Oklahoma (Senate)", "00282", {"82385"}),
    ("West Virginia", "00289", {"59070"}),
    ("Maine", "00281", {"28467"}),
    ("Iowa", "00285", {"38038"}),
    ("Nevada", "00324", {"18430"}),
    ("Missouri", "00325", {"15581"}),
    ("Virginia", "00304", {"21654"}),
    ("Pennsylvania", "00328", {"1043"}),
]


async def main():
    finder = get_finder("sliq_harmony")
    for state, tenant, used in TENANTS:
        url = f"{_H}/{tenant}/Harmony/en/View/RecentEnded/"
        try:
            await finder.resolve(url)
            print(f"=== {state} ({tenant}): resolve() did not raise?! ===")
        except CalendarPageError as e:
            candidates = e.candidates
            print(f"=== {state} ({tenant}): {len(candidates)} events ===")
            for c in candidates[:16]:
                eid = c["url"].rstrip("/").rsplit("/", 1)[-1]
                mark = " [ALREADY USED]" if eid in used else ""
                print(f"  {eid}\t{c['date']}\t{c['title']}{mark}")
        except Exception as e:
            print(f"=== {state} ({tenant}): ERROR {e} ===")
        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
