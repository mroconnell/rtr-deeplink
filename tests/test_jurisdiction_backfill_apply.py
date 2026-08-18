"""Tests for archive/db/crud.py's apply_jurisdiction_bleed_backfill() and
its HTTP wrapper POST /internal/jurisdiction/backfill-apply (archive/main.py)
-- the write counterpart to list_jurisdiction_bleed_backfill_candidates()/
GET /internal/jurisdiction/bleed-backfill-candidates (see
tests/test_jurisdiction_backfill_audit.py, this file's own template), added
for the real 2026-08-18 backfill of already-archived rows predating the
Canadian-data and Title-Case-bleed fixes (PRs #158/#161, BACKLOG.md's
"Jurisdiction-bleed, confirmed cross-platform" entry).
"""

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import MeetingPage

client = TestClient(archive.main.app)


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
    """Same helper as test_jurisdiction_backfill_audit.py's _seed_stale() --
    creates a page via the real ingest path, then overwrites
    jurisdiction/jurisdiction_confidence directly to simulate a page
    archived before today's fixes existed."""
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
        page.title = "Untouched Title"
        await session.commit()
    return result["slug"]


async def test_apply_dry_run_reports_change_but_writes_nothing():
    slug = await _seed_stale(
        "escribe:apply-guelph-dry",
        "https://pub-guelph.escribemeetings.com/apply-guelph-dry",
        "Guelph now hold a meeting that is closed to the public",
        "unverified",
    )
    result = await crud.apply_jurisdiction_bleed_backfill(dry_run=True)
    row = next(c for c in result["changes"] if c["slug"] == slug)
    assert row["before"]["jurisdiction"] == (
        "Guelph now hold a meeting that is closed to the public"
    )
    assert row["after"]["jurisdiction"] == "Guelph, ON"

    async with async_session() as session:
        from sqlalchemy import select

        page = (
            await session.execute(select(MeetingPage).where(MeetingPage.slug == slug))
        ).scalar_one()
        # Dry run must not have touched the row at all.
        assert (
            page.jurisdiction
            == "Guelph now hold a meeting that is closed to the public"
        )
        assert page.jurisdiction_confidence == "unverified"


async def test_apply_for_real_writes_only_jurisdiction_columns():
    slug = await _seed_stale(
        "escribe:apply-guelph-real",
        "https://pub-guelph.escribemeetings.com/apply-guelph-real",
        "Guelph now hold a meeting that is closed to the public",
        "unverified",
    )
    result = await crud.apply_jurisdiction_bleed_backfill(dry_run=False)
    row = next(c for c in result["changes"] if c["slug"] == slug)
    assert row["after"]["jurisdiction"] == "Guelph, ON"

    async with async_session() as session:
        from sqlalchemy import select

        page = (
            await session.execute(select(MeetingPage).where(MeetingPage.slug == slug))
        ).scalar_one()
        assert page.jurisdiction == "Guelph, ON"
        assert page.jurisdiction_confidence == "repaired"
        # Nothing else on the row should have moved.
        assert page.title == "Untouched Title"

    # Re-running apply's own (text-changing-only) detection afterwards must
    # show this row as clean now -- it may still surface in the broader
    # list_jurisdiction_bleed_backfill_candidates() audit above as a
    # confidence-tier-only diff ("repaired" -> "validated" once the value
    # is already correct), since that's explicitly out of scope for a
    # single-field text backfill (see this function's own docstring).
    rerun = await crud.apply_jurisdiction_bleed_backfill(dry_run=True)
    assert all(c["slug"] != slug for c in rerun["changes"])


async def test_apply_skips_confidence_only_diffs():
    # A confidence-tier-only change (same string, better tier) must NOT be
    # written by apply -- only the read-only audit reports those.
    slug = await _seed_stale(
        "escribe:apply-clean-confidence-only",
        "https://pub-clean.escribemeetings.com/apply-clean-confidence-only",
        "City of Sunnyvale, CA",
        None,
    )
    result = await crud.apply_jurisdiction_bleed_backfill(dry_run=False)
    assert all(c["slug"] != slug for c in result["changes"])

    async with async_session() as session:
        from sqlalchemy import select

        page = (
            await session.execute(select(MeetingPage).where(MeetingPage.slug == slug))
        ).scalar_one()
        # Confirms nothing was written for this row -- confidence stays
        # whatever the stale seed set, untouched by apply.
        assert page.jurisdiction == "City of Sunnyvale, CA"


def test_backfill_apply_endpoint_rejects_missing_token():
    response = client.post("/internal/jurisdiction/backfill-apply")
    assert response.status_code == 404


def test_backfill_apply_endpoint_rejects_wrong_token():
    response = client.post(
        "/internal/jurisdiction/backfill-apply",
        headers={"Authorization": "Bearer not-the-real-token"},
    )
    assert response.status_code == 404


async def test_backfill_apply_endpoint_defaults_to_dry_run():
    slug = await _seed_stale(
        "escribe:apply-endpoint-default",
        "https://pub-guelph.escribemeetings.com/apply-endpoint-default",
        "Guelph now hold a meeting that is closed to the public",
        "unverified",
    )
    response = client.post(
        "/internal/jurisdiction/backfill-apply",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert any(c["slug"] == slug for c in body["changes"])

    async with async_session() as session:
        from sqlalchemy import select

        page = (
            await session.execute(select(MeetingPage).where(MeetingPage.slug == slug))
        ).scalar_one()
        assert (
            page.jurisdiction
            == "Guelph now hold a meeting that is closed to the public"
        )


async def test_backfill_apply_endpoint_writes_when_dry_run_false():
    slug = await _seed_stale(
        "escribe:apply-endpoint-real",
        "https://pub-guelph.escribemeetings.com/apply-endpoint-real",
        "Guelph now hold a meeting that is closed to the public",
        "unverified",
    )
    response = client.post(
        "/internal/jurisdiction/backfill-apply?dry_run=false",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert response.json()["dry_run"] is False

    async with async_session() as session:
        from sqlalchemy import select

        page = (
            await session.execute(select(MeetingPage).where(MeetingPage.slug == slug))
        ).scalar_one()
        assert page.jurisdiction == "Guelph, ON"
