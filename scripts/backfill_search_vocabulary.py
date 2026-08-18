"""One-time backfill of `search_vocabulary` for pages archived before
that table existed -- see BACKLOG.md's search entry ("Step 2b") and
archive/db/models.py's SearchVocabulary docstring. crud._refresh_search_
corpus() populates the vocabulary on every new ingest and every worker
transcription-completion going forward; this script is the retroactive
sweep for everything archived before that code shipped.

Pure in-DB recompute, same DB-direct pattern as
scripts/backfill_search_corpus.py -- imports archive.db.engine/
archive.db.models/archive.db.crud directly, no HTTP, must run with
DATABASE_URL pointed at the Archive's real database from the Render
Shell (same place archive/alembic/README.md documents for
`alembic upgrade head`).

Reads each page's *already-populated* `search_corpus` (from the earlier
backfill) rather than recomputing it from transcript segments -- this
script only ever tokenizes and upserts words, it never touches
search_corpus itself.

Usage (from the repo root, with the venv active, DATABASE_URL set):
    python scripts/backfill_search_vocabulary.py --dry-run
    python scripts/backfill_search_vocabulary.py --dry-run --limit 5
    python scripts/backfill_search_vocabulary.py

Idempotency works differently here than in backfill_search_corpus.py:
`search_vocabulary` has no page association (see SearchVocabulary's
docstring), so there's no per-page "already done" flag to filter on --
every run necessarily tokenizes every page's corpus again. That's safe
(`ON CONFLICT DO NOTHING` makes a rerun a correct no-op at the database
level) but not free: a second run redoes the same cheap tokenization/
upsert work rather than skipping already-processed rows. No --force flag
for that reason -- there's no non-force mode to contrast it with.
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
        help="Tokenize and report word counts, but write nothing",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N pages (for testing)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=200,
        help="Pages fetched/committed per batch (default 200)",
    )
    args = parser.parse_args()

    # Imported here, not at module level -- archive.db.engine builds a DB
    # engine from DATABASE_URL at import time, so load_dotenv() below must
    # run first. Same import-order reasoning as scripts/send_search_alerts.py.
    from sqlalchemy import select
    from sqlalchemy.orm import undefer

    from archive.db.crud import _upsert_vocabulary_words
    from archive.db.engine import async_session
    from archive.db.models import MeetingPage
    from archive.utils.search import tokenize

    async with async_session() as session:
        stmt = select(MeetingPage.id).order_by(MeetingPage.id)
        if args.limit:
            stmt = stmt.limit(args.limit)
        page_ids = (await session.execute(stmt)).scalars().all()

    total = len(page_ids)
    if total == 0:
        print("No pages to process.")
        return

    label = "DRY RUN -- " if args.dry_run else ""
    print(f"{label}Backfilling search_vocabulary from {total} page(s)...\n")

    words_seen = 0
    for batch_start in range(0, total, args.batch_size):
        batch_ids = page_ids[batch_start : batch_start + args.batch_size]

        async with async_session() as session:
            pages = (
                (
                    await session.execute(
                        select(MeetingPage)
                        .options(undefer(MeetingPage.search_corpus))
                        .where(MeetingPage.id.in_(batch_ids))
                    )
                )
                .scalars()
                .all()
            )

            batch_words: set[str] = set()
            for page in pages:
                batch_words |= tokenize(page.search_corpus or "")
            words_seen += len(batch_words)

            if not args.dry_run and batch_words:
                await _upsert_vocabulary_words(session, batch_words)
                await session.commit()

        done = min(batch_start + args.batch_size, total)
        print(
            f"[{done}/{total}] batch committed ({len(batch_words)} distinct words)"
            if not args.dry_run
            else f"[{done}/{total}] batch computed ({len(batch_words)} distinct words, dry run)"
        )

    verb = "would be upserted" if args.dry_run else "upserted"
    print(
        f"\nDone. ~{words_seen} distinct word(s) across all batches {verb} (duplicates across batches are expected and harmless)."
    )


if __name__ == "__main__":
    # Deliberately not called at module level -- same reasoning as
    # scripts/send_search_alerts.py's matching comment.
    load_dotenv()
    asyncio.run(main())
