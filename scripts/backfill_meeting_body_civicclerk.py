"""Fill `meeting_body` on CivicClerk pages archived before WO-904 (WO-1977).

WO-904 taught the CivicClerk adapter to read the meeting body ("City
Council", "Planning Commission") from the API's own `categoryName` field.
The Archive only stores it when a page is ingested, so pages archived
before that never got it. The 2026-10-17 recount found 66 of 791 CivicClerk
pages with a body.

This script re-reads `categoryName` for each CivicClerk page with a blank
body and stores it, using the same rule as the adapter (a non-informative
name such as "General" is skipped). It reads one real field per page. It
never guesses a body from the title (BACKLOG.md's meeting-body entry).

One request per page, to `{tenant}.api.civicclerk.com/v1/Events/{id}` only.
That endpoint never touches YouTube, so the script is safe off the drip Mac.
Requests run one at a time with a pause between them. The run stops after
too many errors in a row, or at once on a 429.

Run it from the Archive service's Render shell, never from a laptop against
the production database (CLAUDE.md). Dry run by default.

Usage, from the repo root:
    python scripts/backfill_meeting_body_civicclerk.py --report /tmp/body.csv
    python scripts/backfill_meeting_body_civicclerk.py --limit 50
    python scripts/backfill_meeting_body_civicclerk.py --apply

It saves each page as it goes, and it only reads pages whose body is still
blank, so a stopped run can simply be started again.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

USER_AGENT = (
    "rtr-deeplink/1.0 (Red Tape Recordings meeting archive; "
    "+https://redtaperecordings.com/about)"
)
PAUSE_SECONDS = 1.0
MAX_CONSECUTIVE_ERRORS = 10
_EVENT_ID = re.compile(r"/event/(\d+)")
# A copy of app/platforms/civicclerk.py's _NON_INFORMATIVE_CATEGORY_NAMES.
# Importing that module pulls in yt_dlp (through the YouTube finder), which
# the Archive service does not install, so the script crashed in the
# Archive shell on 2026-10-17. A test keeps the two copies equal.
NON_INFORMATIVE_CATEGORY_NAMES = frozenset({"general"})


def event_api_url(source_url: str) -> str | None:
    """The Events API URL for a CivicClerk event page, or None.

    Built the same way `CivicClerkAssetFinder.resolve()` builds it: the
    first label of the portal host is the tenant, and the path carries
    `/event/{id}`.
    """
    parsed = urlparse(source_url or "")
    host = (parsed.netloc or "").lower().split(":")[0]
    if not host.endswith("civicclerk.com"):
        return None
    match = _EVENT_ID.search(parsed.path)
    if not match:
        return None
    tenant = host.split(".")[0]
    return f"https://{tenant}.api.civicclerk.com/v1/Events/{match.group(1)}"


def body_from_event(event: dict) -> tuple[str | None, str]:
    """(body, outcome) from an Events API record, by the adapter's own rule."""
    name = (event.get("categoryName") or "").strip()
    if not name:
        return None, "no_category"
    if name.lower() in NON_INFORMATIVE_CATEGORY_NAMES:
        return None, "non_informative_category"
    return name, "filled"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true", help="write the bodies")
    parser.add_argument("--limit", type=int, default=0, help="first N pages only")
    parser.add_argument("--report", type=Path, default=None, help="per-page CSV")
    args = parser.parse_args()

    load_dotenv()

    import aiohttp
    from sqlalchemy import or_, select

    from archive.db.engine import async_session
    from archive.db.models import MeetingPage

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"CivicClerk meeting_body refill -- {mode}")

    async with async_session() as session:
        stmt = (
            select(MeetingPage.id, MeetingPage.source_url_normalized)
            .where(MeetingPage.platform == "civicclerk")
            .where(
                or_(MeetingPage.meeting_body.is_(None), MeetingPage.meeting_body == "")
            )
            .order_by(MeetingPage.id.asc())
        )
        if args.limit:
            stmt = stmt.limit(args.limit)
        rows = (await session.execute(stmt)).all()
    print(f"  {len(rows)} CivicClerk pages with a blank body")

    outcomes: Counter = Counter()
    bodies: Counter = Counter()
    report_rows = []
    errors_in_a_row = 0
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    timeout = aiohttp.ClientTimeout(total=20)

    async with aiohttp.ClientSession(headers=headers, timeout=timeout) as http:
        for n, (page_id, source_url) in enumerate(rows, 1):
            api_url = event_api_url(source_url)
            body, outcome = None, "not_an_event_url"
            if api_url:
                try:
                    async with http.get(api_url) as resp:
                        if resp.status == 429:
                            print("  429 from CivicClerk -- stopping. Rerun later.")
                            break
                        if resp.status != 200:
                            outcome = f"http_{resp.status}"
                        else:
                            body, outcome = body_from_event(await resp.json())
                except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
                    outcome = f"error_{type(exc).__name__}"
                await asyncio.sleep(PAUSE_SECONDS)

            if outcome.startswith(("http_", "error_")):
                errors_in_a_row += 1
                if errors_in_a_row >= MAX_CONSECUTIVE_ERRORS:
                    print(f"  {errors_in_a_row} errors in a row -- stopping.")
                    outcomes[outcome] += 1
                    break
            else:
                errors_in_a_row = 0

            outcomes[outcome] += 1
            if body:
                bodies[body] += 1
            report_rows.append(
                {
                    "page_id": page_id,
                    "source_url": source_url,
                    "outcome": outcome,
                    "meeting_body": body or "",
                }
            )

            if body and args.apply:
                async with async_session() as write_session:
                    page = await write_session.get(MeetingPage, page_id)
                    if page is not None and not (page.meeting_body or "").strip():
                        page.meeting_body = body
                        await write_session.commit()

            if n % 50 == 0:
                print(f"  ... {n} of {len(rows)} checked")

    print("")
    print("  outcome counts:")
    for outcome, count in outcomes.most_common():
        print(f"    {outcome:28} {count}")
    print("")
    print("  most common bodies found:")
    for body, count in bodies.most_common(15):
        print(f"    {body:40} {count}")

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with open(args.report, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=["page_id", "source_url", "outcome", "meeting_body"]
            )
            writer.writeheader()
            writer.writerows(report_rows)
        print("")
        print(f"  per-page results written to {args.report}")

    if not args.apply:
        print("")
        print("  DRY RUN -- nothing written. Re-run with --apply to save the bodies.")


if __name__ == "__main__":
    asyncio.run(main())
