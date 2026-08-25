#!/usr/bin/env python3
"""Analyze PostgreSQL database storage usage and identify optimization opportunities.

Run this from the Render shell for production analysis:
  render-shell
  cd /app
  python scripts/analyze_db_storage.py
"""

import asyncio
import os
from sqlalchemy import text
from archive.db.engine import get_async_engine


async def main():
    engine = get_async_engine()

    async with engine.connect() as conn:
        print("=" * 80)
        print("DATABASE STORAGE ANALYSIS")
        print("=" * 80)

        # 1. Total database size
        result = await conn.execute(
            text(
                "SELECT pg_size_pretty(pg_database_size(current_database())) as total_size;"
            )
        )
        total = result.scalar()
        print(f"\nTotal Database Size: {total}")

        # 2. Table sizes (top 15)
        result = await conn.execute(
            text("""
            SELECT
                schemaname,
                tablename,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) as total_size,
                pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) as table_only,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename) -
                    pg_relation_size(schemaname||'.'||tablename)) as indexes_and_toast
            FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC
            LIMIT 15;
            """)
        )

        print("\n" + "=" * 80)
        print("TABLE SIZES (largest first)")
        print("=" * 80)
        rows = result.fetchall()
        for schema, table, total_sz, table_sz, idx_sz in rows:
            print(f"\n{table}")
            print(f"  Total:    {total_sz:>15}  (table: {table_sz}, indexes+TOAST: {idx_sz})")

        # 3. Detailed analysis of large tables
        print("\n" + "=" * 80)
        print("DETAILED TABLE ANALYSIS")
        print("=" * 80)

        # meeting_page_thumbnails - likely the biggest
        print("\n--- meeting_page_thumbnails (image storage) ---")
        result = await conn.execute(
            text("""
            SELECT
                COUNT(*) as total_thumbnails,
                pg_size_pretty(SUM(byte_size)) as total_image_bytes,
                AVG(byte_size) as avg_size_bytes,
                MAX(byte_size) as max_size_bytes,
                MIN(byte_size) as min_size_bytes
            FROM meeting_page_thumbnails;
            """)
        )
        row = result.fetchone()
        total_th, total_img, avg_sz, max_sz, min_sz = row
        print(f"  Total thumbnails: {total_th:,}")
        print(f"  Total image bytes: {total_img}")
        print(f"  Avg size: {avg_sz:,.0f} bytes")
        print(f"  Range: {min_sz:,.0f} - {max_sz:,.0f} bytes")

        # Duplicate images (same etag across multiple offsets)
        print("\n--- Duplicate images (same content, different offsets) ---")
        result = await conn.execute(
            text("""
            SELECT
                etag,
                COUNT(*) as count,
                pg_size_pretty(byte_size) as size,
                COUNT(*) * byte_size as total_wasted
            FROM meeting_page_thumbnails
            GROUP BY etag, byte_size
            HAVING COUNT(*) > 1
            ORDER BY COUNT(*) * byte_size DESC
            LIMIT 10;
            """)
        )
        rows = result.fetchall()
        if rows:
            total_waste = 0
            for etag, count, size, waste in rows:
                print(f"  {count} copies of {size}: {waste:,} bytes total wasted")
                total_waste += waste
            print(f"  Total potential savings: {total_waste:,} bytes")
        else:
            print("  No duplicates found")

        # transcript_versions - segments and warnings
        print("\n--- transcript_versions (segment storage) ---")
        result = await conn.execute(
            text("""
            SELECT
                COUNT(*) as total_versions,
                pg_size_pretty(SUM(pg_column_size(segments)::bigint)) as segment_json_size,
                AVG(jsonb_array_length(segments)::int) as avg_segments_per_version,
                MAX(jsonb_array_length(segments)::int) as max_segments,
                pg_size_pretty(MAX(pg_column_size(segments)::bigint)) as largest_segment_json
            FROM transcript_versions;
            """)
        )
        row = result.fetchone()
        total_v, seg_sz, avg_seg, max_seg, max_sz = row
        print(f"  Total versions: {total_v:,}")
        print(f"  Total segment JSON size: {seg_sz}")
        print(f"  Avg segments per version: {avg_seg:,.0f}")
        print(f"  Max segments in one version: {max_seg:,}")
        print(f"  Largest single segment JSON: {max_sz}")

        # meeting_page.search_corpus
        print("\n--- meeting_page.search_corpus (full-text search data) ---")
        result = await conn.execute(
            text("""
            SELECT
                COUNT(*) as pages_with_corpus,
                pg_size_pretty(SUM(pg_column_size(search_corpus)::bigint)) as total_corpus_size,
                AVG(length(search_corpus)) as avg_corpus_length,
                MAX(length(search_corpus)) as max_corpus_length,
                pg_size_pretty(MAX(pg_column_size(search_corpus)::bigint)) as largest_corpus
            FROM meeting_pages
            WHERE search_corpus IS NOT NULL;
            """)
        )
        row = result.fetchone()
        pages_w_corpus, corpus_sz, avg_len, max_len, max_sz = row
        print(f"  Pages with corpus: {pages_w_corpus:,}")
        print(f"  Total corpus size: {corpus_sz}")
        print(f"  Avg corpus length: {avg_len:,.0f} chars")
        print(f"  Max corpus length: {max_len:,} chars")
        print(f"  Largest single corpus: {max_sz}")

        # Unused/old data
        print("\n--- Potentially unused/old data ---")

        # Failed resolutions taking space
        result = await conn.execute(
            text("""
            SELECT
                COUNT(*) as failed_resolutions,
                pg_size_pretty(SUM(pg_column_size(resolved_payload)::bigint)) as payload_size
            FROM meeting_resolutions
            WHERE status IN ('failed', 'unsupported');
            """)
        )
        row = result.fetchone()
        failed_count, payload_sz = row
        print(f"\n  Failed/unsupported resolutions: {failed_count:,} ({payload_sz})")
        print(f"    Consider: Archive only pushes successful resolutions, so this is")
        print(f"    resolver-only diagnostic data. Truncating old failures is safe.")

        # Stale transcription jobs
        result = await conn.execute(
            text("""
            SELECT
                COUNT(*) as completed_jobs,
                pg_size_pretty(SUM(pg_column_size(partial_segments)::bigint)) as segments_size,
                MIN(updated_at) as oldest_completed
            FROM transcription_jobs
            WHERE status = 'completed'
            AND updated_at < CURRENT_TIMESTAMP - INTERVAL '30 days';
            """)
        )
        row = result.fetchone()
        completed, segments_sz, oldest = row
        if completed and completed > 0:
            print(f"\n  Completed jobs >30 days old: {completed:,} ({segments_sz})")
            print(f"    Oldest: {oldest}")

        # Indexes
        print("\n" + "=" * 80)
        print("INDEX ANALYSIS")
        print("=" * 80)

        result = await conn.execute(
            text("""
            SELECT
                tablename,
                indexname,
                pg_size_pretty(pg_relation_size(indexrelid)) as index_size
            FROM pg_indexes
            JOIN pg_class ON pg_indexes.indexname = pg_class.relname
            WHERE schemaname = 'public'
            ORDER BY pg_relation_size(indexrelid) DESC
            LIMIT 10;
            """)
        )

        print("\nLargest indexes:")
        rows = result.fetchall()
        for table, index, size in rows:
            print(f"  {index:40} {size:>15}  (on {table})")

        # Unused indexes (if any)
        print("\n" + "=" * 80)
        print("RECOMMENDATIONS")
        print("=" * 80)
        print("""
1. IMAGE THUMBNAILS (meeting_page_thumbnails)
   - Each page stores multiple thumbnail offsets as separate JPEG bytes
   - Consider: Archive only the most recent/highest-quality thumbnail per page
   - Or: Use object storage (S3/R2) instead of Postgres for images
   - Cost: Each 30-120KB JPEG × ~1200 pages = ~30GB+ if not pruned

2. SEARCH CORPUS
   - The search_corpus column holds the entire transcript text per page
   - It's deferred (not loaded on list queries), so it's not causing memory issues
   - To reclaim space: Keep it for live pages, but don't backfill deleted pages

3. TRANSCRIPT SEGMENTS (JSON)
   - Multiple versions per page (different languages, manual vs auto)
   - Only mark is_default=true for the version you want to display
   - Archive only keeps versions that are actually used

4. RESOLVER DIAGNOSTICS (meeting_resolutions)
   - Failed/unsupported records in resolver DB have resolved_payload
   - Resolver never pushes these to Archive (Archive only gets successes)
   - Safe to truncate old failed resolutions (>90 days?) to free space

5. TRANSCRIPTION JOB DATA
   - partial_segments accumulates as jobs run
   - Completed jobs >30 days old can have partial_segments cleared

IMMEDIATE ACTION:
   Run this to see exact breakdown:
   - Render shell on the Archive service
   - Connect via psql and run the queries above
   - Identify which table is actually the problem (thumbnails most likely)
   - Consider: move thumbnails to object storage, or limit to 1 per page
        """)


if __name__ == "__main__":
    asyncio.run(main())
