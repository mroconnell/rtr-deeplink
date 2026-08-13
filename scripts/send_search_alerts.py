"""CLI wrapper for the saved-search alert sweep (see archive/search_alerts.py
for what it actually gathers/sends and why). Production runs go through
GET /admin/send-search-alerts instead (app/main.py, triggered by a GitHub
Actions cron workflow, .github/workflows/send-search-alerts.yml) -- this
script exists for local ad-hoc runs and --dry-run verification against
real credentials without needing a request to the running service.

Usage (from the repo root, with the venv active):
    python scripts/send_search_alerts.py
    python scripts/send_search_alerts.py --dry-run

Requires CLERK_SECRET_KEY, RESEND_API_KEY, RESEND_FROM_ADDRESS,
PUBLIC_BASE_URL, ALERT_UNSUBSCRIBE_SECRET (all already used elsewhere in
this repo, ALERT_UNSUBSCRIBE_SECRET new for this feature) plus
DATABASE_URL pointed at the **Archive's** database -- SavedItem/
MeetingPage/TranscriptVersion all live there, the opposite of
scripts/daily_report.py's own note (that one needs the *resolver's*
database instead). An easy copy-paste trap between the two scripts.

--dry-run composes every digest and prints it, but never calls Resend
and never advances any saved search's last_alerted_at cursor -- the only
way to eyeball real copy/matching against real data before a real send
ever happens.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Compose and print each digest, but don't send anything")
    args = parser.parse_args()

    # Imported here, not at module level -- archive/search_alerts.py
    # imports archive.db.crud, whose archive/db/engine.py builds a DB
    # engine from DATABASE_URL at import time. load_dotenv() below only
    # runs once this __main__ guard is reached, so importing any earlier
    # would read DATABASE_URL before .env is loaded -- same flakiness
    # scripts/daily_report.py's own comment documents for the resolver
    # side.
    from archive import search_alerts

    try:
        result = await search_alerts.run_search_alerts(dry_run=args.dry_run)
    except Exception as e:
        print(f"ABORTING: {type(e).__name__}: {str(e)[:300]}", file=sys.stderr)
        sys.exit(1)

    print(
        f"Checked {result['saved_searches_checked']} saved search(es), "
        f"found {result['matches_found']} new match(es), "
        f"{'would email' if args.dry_run else 'emailed'} {result['users_emailed']} user(s).\n"
    )
    for entry in result["sent"]:
        print(f"--- {entry['email']} ---")
        print(f"Subject: {entry['subject']}")
        if args.dry_run:
            print(entry["body"])
        print()


if __name__ == "__main__":
    # Deliberately not called at module level -- same reasoning as
    # scripts/daily_report.py's matching comment.
    load_dotenv()
    asyncio.run(main())
