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


# --- clear_future_meeting_dates() (POST /internal/pages/clear-future-dates,
# 2026-08-23) -- the repair half of the Granicus body-text future-date bug.


async def _seed_with_date(external_id: str, date_value: str) -> int:
    url = f"https://example.com/future-date/{external_id}"
    payload = _payload(external_id, url, "City of Sunnyvale, CA")
    payload["date"] = "2026-01-01"
    result = await crud.ingest_resolution(payload, url)
    async with async_session() as session:
        from sqlalchemy import select

        page = (
            await session.execute(
                select(MeetingPage).where(MeetingPage.slug == result["slug"])
            )
        ).scalar_one()
        page.date = date_value
        await session.commit()
        return page.id


async def test_clear_future_dates_dry_run_flags_far_future_only():
    # Shapes drawn from the three real production rows (Mission Viejo
    # 2026-11-03, Tulsa 2026-12-31, Tarrant 2026-08-31 -- all mined out
    # of agenda body text) vs. a genuinely-scheduled near-future agenda
    # page (the real Sarasota County shape: 2 days out).
    from datetime import date, timedelta

    today = date.today()
    far = (today + timedelta(days=60)).isoformat()
    near = (today + timedelta(days=2)).isoformat()
    past = (today - timedelta(days=10)).isoformat()
    far_id = await _seed_with_date("escribe:future-far", far)
    near_id = await _seed_with_date("escribe:future-near", near)
    past_id = await _seed_with_date("escribe:future-past", past)

    result = await crud.clear_future_meeting_dates(dry_run=True)
    cleared_ids = {c["meeting_page_id"] for c in result["cleared"]}
    kept_ids = {c["meeting_page_id"] for c in result["kept_in_grace_window"]}
    assert far_id in cleared_ids
    assert near_id in kept_ids and near_id not in cleared_ids
    assert past_id not in cleared_ids and past_id not in kept_ids

    # Dry run must not write.
    async with async_session() as session:
        page = await session.get(MeetingPage, far_id)
        assert page.date == far


async def test_clear_future_dates_apply_nulls_only_selected_rows():
    from datetime import date, timedelta

    far = (date.today() + timedelta(days=90)).isoformat()
    a_id = await _seed_with_date("escribe:future-a", far)
    b_id = await _seed_with_date("escribe:future-b", far)

    result = await crud.clear_future_meeting_dates(dry_run=False, only_ids={a_id})
    assert {c["meeting_page_id"] for c in result["cleared"]} == {a_id}
    assert result["skipped_by_filter"] >= 1

    async with async_session() as session:
        assert (await session.get(MeetingPage, a_id)).date is None
        assert (await session.get(MeetingPage, b_id)).date == far
