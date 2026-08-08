"""One-off maintenance: force a fresh CivicClerk resolve + Archive push for
a permanent page that predates an adapter fix (e.g. the SRT caption parser
added 2026-08-08 -- see BACKLOG.md's "permanent Archive page can be stuck
showing no transcript" entry for why this exists). Mirrors exactly what
app/main.py's `_recheck_archived_page()` does on a 30-day-stale lookup hit,
just triggered on demand instead of waiting for that window. Superseded
once the on-demand admin recheck endpoint from that BACKLOG.md entry is
built.

Run from the repo root on the resolver's deployed environment (so
ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN are already set, same as any other
env var app/main.py relies on):

    python -m scripts.refresh_archive_page <source_url>              # dry run
    python -m scripts.refresh_archive_page <source_url> --push        # actually push

Dry run only resolves and prints what was found -- confirm the segment
count looks right before rerunning with --push.
"""
import argparse
import asyncio
import os
import sys

from app.archive_client import push
from app.platforms.civicclerk import CivicClerkAssetFinder
from app.utils.url_normalize import normalize_url


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("url", help="Source meeting URL, e.g. https://emporiaks.portal.civicclerk.com/event/585/media")
    parser.add_argument("--push", action="store_true", help="Actually push to the Archive (default: dry run)")
    args = parser.parse_args()

    finder = CivicClerkAssetFinder()
    result = await finder.resolve(args.url)

    print(f"platform:            {result.platform}")
    print(f"title:               {result.title}")
    print(f"date:                {result.date}")
    print(f"jurisdiction:        {result.jurisdiction}")
    print(f"video_url:           {result.video_url}")
    print(f"segments:            {len(result.segments)}")
    print(f"agenda_items:        {len(result.agenda_items)}")
    print(f"transcript_language: {result.transcript_language}")
    print(f"transcript_warnings: {result.transcript_warnings}")
    print(f"video_warnings:      {result.video_warnings}")

    if not result.segments and not result.agenda_items:
        print("\nNo segments or agenda items found -- nothing would be pushed (matches app/main.py's push guard).")
        return

    if not args.push:
        print("\nDry run only -- rerun with --push to actually send this to the Archive.")
        return

    if not os.environ.get("ARCHIVE_BASE_URL") or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "\nARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN aren't set in this environment -- refusing to push.",
            file=sys.stderr,
        )
        sys.exit(1)

    normalized = normalize_url(args.url)
    await push(result.model_dump(), normalized)
    print(f"\nPushed to {os.environ['ARCHIVE_BASE_URL']} for {normalized}.")
    print("Check the permanent page to confirm the new transcript shows up.")


if __name__ == "__main__":
    asyncio.run(main())
