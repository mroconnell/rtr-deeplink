"""One-time backfill of MeetingPage.search_corpus for pages archived
before that column existed -- see BACKLOG.md's "Search: move to a
materialized/indexed column" entry and archive/db/models.py's
search_corpus docstring. crud.ingest_resolution() populates this column
on every new ingest going forward; this script is the retroactive sweep
for everything archived before that code shipped.

Unlike scripts/backfill_archived_pages.py (which re-resolves live
government sites through app.archive_client/HTTP, hence that script's
politeness delay), this is a pure in-DB recompute with no external calls
-- it imports archive.db.engine/archive.db.models/
archive.utils.search.compute_search_corpus directly, the same
DB-direct pattern scripts/send_search_alerts.py already uses. That means
it must run with DATABASE_URL pointed at the Archive's real database --
from the Archive service's Render Shell, the same place
archive/alembic/README.md already documents for `alembic upgrade head`/
`alembic current`. It does not go through the Archive's HTTP ingest
endpoint at all.

Usage (from the repo root, with the venv active, DATABASE_URL set):
    python scripts/backfill_search_corpus.py --dry-run
    python scripts/backfill_search_corpus.py --dry-run --limit 5
    python scripts/backfill_search_corpus.py
    python scripts/backfill_search_corpus.py --force

Idempotent by default: only touches rows where search_corpus IS NULL, so
a crash mid-run (or a second run against the same DB) just picks up
wherever the first run left off, no state to track. --force recomputes
every row regardless -- for re-running after a fix to
compute_search_corpus() itself, not needed for the initial backfill.
"""

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute and report what would change, but write nothing",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N matching pages (for testing)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Pages fetched/committed per batch (default 200)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Recompute every page's search_corpus, not just NULL ones",
    )
    args = parser.parse_args()

    # Imported here, not at module level -- archive.db.engine builds a DB
    # engine from DATABASE_URL at import time, so load_dotenv() below must
    # run first. Same import-order reasoning as scripts/send_search_alerts.py.
    from sqlalchemy import select

    from archive.db.engine import async_session
    from archive.db.models import MeetingPage, TranscriptVersion
    from archive.utils.search import compute_search_corpus

    async with async_session() as session:
        stmt = select(MeetingPage.id).order_by(MeetingPage.id)
        if not args.force:
            stmt = stmt.where(MeetingPage.search_corpus.is_(None))
        if args.limit:
            stmt = stmt.limit(args.limit)
        page_ids = (await session.execute(stmt)).scalars().all()

    total = len(page_ids)
    if total == 0:
        print("Nothing to do -- every page already has a search_corpus.")
        return

    label = "DRY RUN -- " if args.dry_run else ""
    print(f"{label}Backfilling search_corpus for {total} page(s)...\n")

    updated = 0
    for batch_start in range(0, total, args.batch_size):
        batch_ids = page_ids[batch_start : batch_start + args.batch_size]

        async with async_session() as session:
            pages = (
                (
                    await session.execute(
                        select(MeetingPage).where(MeetingPage.id.in_(batch_ids))
                    )
                )
                .scalars()
                .all()
            )

            # One query for the whole batch's segments, keyed by page id --
            # avoids an N+1 round trip per page, same batching instinct as
            # list_pages()'s own keyword-search segment fetch.
            version_rows = await session.execute(
                select(
                    TranscriptVersion.meeting_page_id, TranscriptVersion.segments
                ).where(TranscriptVersion.meeting_page_id.in_(batch_ids))
            )
            segments_by_page: dict[int, list] = {}
            for page_id, segments in version_rows:
                segments_by_page.setdefault(page_id, []).append(segments)

            for page in pages:
                corpus = compute_search_corpus(
                    page.title,
                    page.jurisdiction,
                    page.agenda_items,
                    segments_by_page.get(page.id, []),
                )
                if not args.dry_run:
                    page.search_corpus = corpus
                updated += 1

            if not args.dry_run:
                await session.commit()

        done = min(batch_start + args.batch_size, total)
        print(
            f"[{done}/{total}] batch committed"
            if not args.dry_run
            else f"[{done}/{total}] batch computed (dry run)"
        )

    verb = "would be updated" if args.dry_run else "updated"
    print(f"\nDone. {updated} page(s) {verb}.")


if __name__ == "__main__":
    # Deliberately not called at module level -- same reasoning as
    # scripts/send_search_alerts.py's matching comment.
    load_dotenv()
    asyncio.run(main())
