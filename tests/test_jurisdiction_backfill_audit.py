"""Tests for archive/db/crud.py's list_jurisdiction_bleed_backfill_candidates()
-- the read-only audit backing GET /internal/jurisdiction/bleed-backfill-
candidates (archive/main.py), added 2026-08-17 alongside the Canadian-data
and Title-Case-bleed fixes in app/utils/jurisdiction_enrich.py (BACKLOG.md's
"Jurisdiction-bleed, confirmed cross-platform" entry). Real DB integration
tests against the isolated SQLite file set up by tests/conftest.py's
_archive_db_schema fixture, not mocked -- same convention as
tests/test_transcription_jobs.py's hallucination-candidates tests, this
audit's own template.
"""

from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import MeetingPage


def _payload(external_id: str, source_url: str, jurisdiction: str) -> dict:
    return {
        "platform": "escribe",
        "source_url": source_url,
        "external_id": external_id,
        "title": "Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": jurisdiction,
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }


async def _seed_stale(external_id, source_url, stale_jurisdiction, stale_confidence):
    """Creates a page via the real ingest_resolution() path (so it gets a
    real slug/title/etc.), then overwrites `jurisdiction`/
    `jurisdiction_confidence` directly on the row to simulate an
    already-archived page whose value predates today's fixes --
    ingest_resolution() itself always runs the CURRENT finalize_jurisdiction(),
    so there's no way to get a genuinely stale value through the normal
    path anymore now that the fix is live (same reasoning
    tests/test_jurisdiction_hubs.py's _seed() helper already uses for
    meeting_body)."""
    result = await crud.ingest_resolution(
        _payload(external_id, source_url, "placeholder"), source_url
    )
    async with async_session() as session:
        from sqlalchemy import select

        page = (
            await session.execute(
                select(MeetingPage).where(MeetingPage.slug == result["slug"])
            )
        ).scalar_one()
        page.jurisdiction = stale_jurisdiction
        page.jurisdiction_confidence = stale_confidence
        await session.commit()
    return result["slug"]


async def test_bleed_backfill_audit_finds_a_real_canadian_bleed_case():
    # Real raw value, Guelph ON (BACKLOG.md) -- simulates the page having
    # been archived before the Canadian data table existed, so it's
    # stuck at "unverified" until a backfill re-runs finalize_jurisdiction().
    slug = await _seed_stale(
        "escribe:audit-guelph",
        "https://pub-guelph.escribemeetings.com/audit-guelph",
        "Guelph now hold a meeting that is closed to the public",
        "unverified",
    )
    audit = await crud.list_jurisdiction_bleed_backfill_candidates()
    row = next(c for c in audit["candidates"] if c["slug"] == slug)
    assert row["current_jurisdiction"] == (
        "Guelph now hold a meeting that is closed to the public"
    )
    assert row["current_confidence"] == "unverified"
    assert row["repaired_jurisdiction"] == "Guelph, ON"
    assert row["repaired_confidence"] == "repaired"


async def test_bleed_backfill_audit_skips_a_page_finalize_jurisdiction_would_not_change():
    # A clean, already-correct value must NOT appear as a candidate --
    # re-running finalize_jurisdiction() on it should be a pure no-op.
    slug = await _seed_stale(
        "escribe:audit-clean",
        "https://pub-clean.escribemeetings.com/audit-clean",
        "City of Sunnyvale, CA",
        "validated",
    )
    audit = await crud.list_jurisdiction_bleed_backfill_candidates()
    assert all(c["slug"] != slug for c in audit["candidates"])
