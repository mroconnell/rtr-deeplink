"""Backfill `meeting_highlights` for pages archived before that table
existed -- see archive/db/models.py's MeetingHighlight docstring and
archive/utils/highlights.py for what a highlight is and why it is
stored rather than computed per request.

crud._refresh_search_corpus() populates this for every new ingest and
every completed transcription going forward (it is the same choke point
that keeps search_corpus and search_vocabulary in sync); this script is
the retroactive sweep, and the way to re-run everything after a change
to the heuristic or to archive/topics.py.

Like scripts/backfill_search_corpus.py this is a pure in-DB recompute
with no external calls, so it must run with DATABASE_URL pointed at the
Archive's real database -- from the Archive service's Render Shell, the
same place archive/alembic/README.md documents for `alembic upgrade
head`.

Usage (from the repo root, with the venv active, DATABASE_URL set):
    python scripts/backfill_meeting_highlights.py --dry-run --limit 20
    python scripts/backfill_meeting_highlights.py
    python scripts/backfill_meeting_highlights.py --force

Idempotent by default: skips any page that already has a highlight row
computed under the *current* archive/topics.py TOPICS_VERSION, so a
crash mid-run resumes where it stopped, and a run after a topic-list
change re-does exactly the stale rows and nothing else. --force
recomputes every page regardless, for a change to the scoring heuristic
itself (which TOPICS_VERSION does not track).

Memory note: segments are the largest JSON in the schema (a long meeting
runs to thousands of them), so this loads one page's transcripts at a
time rather than a batch of them -- the 2026-08-17 OOM crash came from
dragging large per-page blobs into memory in bulk.
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
        "--force",
        action="store_true",
        help="Recompute every page's highlight, not just missing/stale ones",
    )
    args = parser.parse_args()

    load_dotenv()

    # Imported after load_dotenv() -- archive.db.engine builds its engine
    # from DATABASE_URL at import time. Same ordering as
    # scripts/backfill_search_corpus.py.
    from sqlalchemy import select

    from archive.db.engine import async_session
    from archive.db.models import MeetingHighlight, MeetingPage, TranscriptVersion
    from archive.topics import TOPICS_VERSION
    from archive.utils.highlights import compute_highlight_payload

    async with async_session() as session:
        page_ids = (
            (
                await session.execute(
                    select(MeetingPage.id)
                    .where(MeetingPage.platform != "unknown")
                    .order_by(MeetingPage.id)
                )
            )
            .scalars()
            .all()
        )
        existing = {
            page_id: version
            for page_id, version in (
                await session.execute(
                    select(
                        MeetingHighlight.meeting_page_id,
                        MeetingHighlight.topics_version,
                    )
                )
            ).all()
        }

    if not args.force:
        page_ids = [
            page_id
            for page_id in page_ids
            if existing.get(page_id) != TOPICS_VERSION
        ]
    if args.limit:
        page_ids = page_ids[: args.limit]

    total = len(page_ids)
    if total == 0:
        print("Nothing to do -- every page has a current highlight.")
        return
    print(
        f"{total} page(s) to process "
        f"({'dry run' if args.dry_run else 'writing'}, TOPICS_VERSION={TOPICS_VERSION})"
    )

    written = skipped = 0
    for index, page_id in enumerate(page_ids, start=1):
        async with async_session() as session:
            page = await session.get(MeetingPage, page_id)
            if page is None:
                continue
            all_segments = (
                (
                    await session.execute(
                        select(TranscriptVersion.segments).where(
                            TranscriptVersion.meeting_page_id == page_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            payload = compute_highlight_payload(all_segments)
            if payload["highlight"] is None:
                skipped += 1
            else:
                written += 1
            if args.dry_run:
                if payload["highlight"]:
                    quote = payload["highlight"]["text"][:110]
                    topics = ",".join(payload["topic_moments"]) or "-"
                    print(f"  [{page_id}] t={int(payload['highlight']['start'])}s "
                          f"topics={topics}\n      {quote}")
            else:
                # Reuse the exact code path ingest uses, so a backfilled
                # row and a freshly-ingested one can never disagree.
                from archive.db import crud

                await crud._refresh_meeting_highlight(session, page, all_segments)
                await session.commit()
        if index % 100 == 0:
            print(f"  ...{index}/{total}")

    print(
        f"Done. {written} highlight(s) {'would be ' if args.dry_run else ''}written, "
        f"{skipped} page(s) had nothing quotable."
    )


if __name__ == "__main__":
    asyncio.run(main())
