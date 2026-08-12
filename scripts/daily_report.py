"""CLI wrapper for the once-a-day operator digest (see app/reporting.py
for what it actually gathers/sends and why). Production runs go through
GET /admin/daily-report instead (app/main.py, triggered by a GitHub
Actions cron workflow, .github/workflows/daily-report.yml) -- this script
exists for local ad-hoc runs and --dry-run verification against real
credentials without needing a request to the running service.

Usage (from the repo root, with the venv active):
    python scripts/daily_report.py
    python scripts/daily_report.py --dry-run

Requires CLERK_SECRET_KEY, RESEND_API_KEY, RESEND_AUDIENCE_ID,
RESEND_FROM_ADDRESS (all already used elsewhere in this repo) plus
DATABASE_URL pointed at the *resolver's* database (meeting_resolutions
lives there, not in the Archive's separate database). Sends to
DAILY_REPORT_EMAIL_TO (default ryan@how-to-adu.com).
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Compose and print the report, but don't send it")
    args = parser.parse_args()

    # Imported here, not at module level -- app/reporting.py imports
    # app.db.crud, whose app/db/engine.py builds a DB engine from
    # DATABASE_URL at import time. load_dotenv() below only runs once
    # this __main__ guard is reached, so importing app.reporting any
    # earlier would read DATABASE_URL before .env is loaded -- same
    # flakiness fetch_youtube_transcripts.py's own comment documents for
    # a different env var.
    from app import reporting

    to = os.environ.get("DAILY_REPORT_EMAIL_TO", "ryan@how-to-adu.com")

    try:
        result = await reporting.run_daily_report(to=to, dry_run=args.dry_run)
    except Exception as e:
        print(f"ABORTING: {type(e).__name__}: {str(e)[:300]}", file=sys.stderr)
        sys.exit(1)

    if args.dry_run:
        print(f"Subject: {result['subject']}\n")
        print(result["body"])
        return

    if not result["sent"]:
        print("Send failed -- check RESEND_API_KEY/RESEND_FROM_ADDRESS and the log above.", file=sys.stderr)
        sys.exit(1)
    print(f"Sent: {result['subject']}")


if __name__ == "__main__":
    # Deliberately not called at module level -- same reasoning as
    # fetch_youtube_transcripts.py's matching comment.
    load_dotenv()
    asyncio.run(main())
