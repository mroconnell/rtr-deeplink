#!/usr/bin/env python3
"""Delete old/excess thumbnails per page, keeping only the most recent N.

This reclaims storage after MAX_FRAMES_PER_PAGE has been lowered or to
trim unbounded growth from high-traffic pages.

Run from the Render shell (repo root, venv active, DATABASE_URL set by
the environment already):
  python scripts/cleanup_old_thumbnails.py --keep 3
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main(keep_per_page: int = 3, dry_run: bool = False):
    """Keep only the most recent N thumbnails per page, delete older ones.

    Args:
        keep_per_page: How many thumbnails to keep per page (1-12)
        dry_run: If True, show what would be deleted without deleting
    """
    load_dotenv()

    # Imported after load_dotenv() -- archive.db.engine builds its engine
    # from DATABASE_URL at import time. Same ordering as
    # scripts/backfill_meeting_highlights.py.
    from sqlalchemy import text

    from archive.db.engine import engine

    async with engine.begin() as conn:
        # Find pages with more than keep_per_page thumbnails
        result = await conn.execute(
            text("""
            SELECT
                meeting_page_id,
                COUNT(*) as total,
                SUM(byte_size) as total_bytes
            FROM meeting_page_thumbnails
            GROUP BY meeting_page_id
            HAVING COUNT(*) > :keep
            ORDER BY total DESC;
            """),
            {"keep": keep_per_page},
        )

        excess_pages = result.fetchall()
        if not excess_pages:
            logger.info(f"✓ No pages with more than {keep_per_page} thumbnails found")
            return

        logger.info(
            f"Found {len(excess_pages)} pages with excess thumbnails (>{keep_per_page})"
        )

        # Calculate total bytes we can reclaim
        total_to_reclaim = 0
        pages_to_clean = 0

        for page_id, total_count, total_bytes in excess_pages:
            to_delete = total_count - keep_per_page
            pages_to_clean += 1
            total_to_reclaim += int(total_bytes) * (to_delete / total_count)
            logger.info(
                f"  Page {page_id}: {total_count} thumbnails "
                f"({total_bytes:,} bytes) → delete {to_delete} frames"
            )

        logger.info(
            f"\nWould reclaim: {total_to_reclaim:,.0f} bytes "
            f"({total_to_reclaim / 1024 / 1024:.1f} MB)"
        )

        if dry_run:
            logger.info("DRY RUN: no changes made")
            return

        # Delete oldest non-default frames, keeping most recent N per page
        logger.info("\nDeleting old thumbnails...")

        for page_id, _, _ in excess_pages:
            # Delete old frames, but always keep the default one
            result = await conn.execute(
                text("""
                DELETE FROM meeting_page_thumbnails
                WHERE meeting_page_id = :page_id
                AND id NOT IN (
                    -- Keep: the default frame (if one exists)
                    SELECT id FROM meeting_page_thumbnails
                    WHERE meeting_page_id = :page_id
                    AND is_default = true
                    UNION ALL
                    -- Keep: the most recent N non-default frames.
                    -- The ORDER BY/LIMIT has to live in its own wrapped
                    -- subquery -- SQLite (and standard SQL generally)
                    -- rejects an ORDER BY directly on a UNION ALL member.
                    SELECT id FROM (
                        SELECT id, created_at FROM meeting_page_thumbnails
                        WHERE meeting_page_id = :page_id
                        AND is_default = false
                        ORDER BY created_at DESC
                        LIMIT :keep_minus_one
                    ) AS recent
                );
                """),
                {"page_id": page_id, "keep_minus_one": keep_per_page - 1},
            )
            deleted = result.rowcount
            if deleted > 0:
                logger.info(f"  Page {page_id}: deleted {deleted} thumbnails")

        # No explicit commit here -- `engine.begin()` already wraps this
        # whole block in one transaction and commits on clean exit; an
        # explicit conn.commit() mid-block closes that transaction early
        # and the next query on the same connection then raises
        # InvalidRequestError (confirmed by actually running this against
        # a seeded local SQLite database, not just read).

        # Check final state -- byte_size is a plain int column (see
        # MeetingPageThumbnail in archive/db/models.py), so the total is
        # formatted in Python rather than via a Postgres-only
        # pg_size_pretty/pg_column_size call, keeping this final report
        # portable across the Postgres/SQLite dialects the rest of this
        # script's DELETE logic already works on.
        result = await conn.execute(
            text("""
            SELECT
                COUNT(DISTINCT meeting_page_id) as pages_with_thumbnails,
                COUNT(*) as total_thumbnails,
                SUM(byte_size) as total_bytes
            FROM meeting_page_thumbnails;
            """)
        )

        final = result.fetchone()
        total_bytes = final[2] or 0
        logger.info(
            f"\n✓ Cleanup complete:\n"
            f"  Pages with thumbnails: {final[0]:,}\n"
            f"  Total thumbnail rows: {final[1]:,}\n"
            f"  Total size: {total_bytes:,} bytes ({total_bytes / 1024 / 1024:.1f} MB)"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep",
        type=int,
        default=3,
        help="How many thumbnails to keep per page (default: 3)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting",
    )
    args = parser.parse_args()

    if args.keep < 1 or args.keep > 12:
        print("Error: --keep must be between 1 and 12")
        exit(1)

    asyncio.run(main(keep_per_page=args.keep, dry_run=args.dry_run))
