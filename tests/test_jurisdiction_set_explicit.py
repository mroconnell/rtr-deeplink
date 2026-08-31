"""Tests for archive/db/crud.py's set_explicit_jurisdiction()/
validate_explicit_jurisdiction() and their HTTP wrapper POST
/internal/jurisdiction/set-explicit (archive/main.py) -- the missing
"no write path exists" capability BACKLOG.md's Santa Clara canonical-form
entry needed: `County of Santa Clara, CA` / `The County of Santa Clara, CA`
/ `Santa Clara County, CA` / `County of Santa Clara Office` all
independently validate today, so apply_jurisdiction_bleed_backfill()'s
recompute-only write makes zero changes to any of them. This is the
explicit-string write path that was missing, same admin-token/dry_run
pattern as every other /internal/* write in this file (see
test_jurisdiction_backfill_apply.py, this file's own template).
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


async def _seed_page(external_id: str, source_url: str, jurisdiction: str) -> dict:
    result = await crud.ingest_resolution(
        _payload(external_id, source_url, jurisdiction), source_url
    )
    async with async_session() as session:
        from sqlalchemy import select

        page = (
            await session.execute(
                select(MeetingPage).where(MeetingPage.slug == result["slug"])
            )
        ).scalar_one()
        return {"id": page.id, "slug": page.slug}


# --- crud.validate_explicit_jurisdiction() --------------------------------


def test_validate_explicit_jurisdiction_strips_whitespace():
    assert (
        crud.validate_explicit_jurisdiction("  Santa Clara County, CA  ")
        == "Santa Clara County, CA"
    )


def test_validate_explicit_jurisdiction_rejects_empty():
    import pytest

    with pytest.raises(ValueError):
        crud.validate_explicit_jurisdiction("   ")


def test_validate_explicit_jurisdiction_rejects_too_long():
    import pytest

    with pytest.raises(ValueError):
        crud.validate_explicit_jurisdiction("x" * 201)


def test_validate_explicit_jurisdiction_accepts_max_length():
    # Boundary check -- exactly the cap should still pass.
    assert crud.validate_explicit_jurisdiction("x" * 200) == "x" * 200


# --- crud.set_explicit_jurisdiction() --------------------------------------


async def test_set_explicit_dry_run_reports_change_but_writes_nothing():
    page = await _seed_page(
        "escribe:set-explicit-dry",
        "https://pub-santaclara.escribemeetings.com/set-explicit-dry",
        "County of Santa Clara Office",
    )
    result = await crud.set_explicit_jurisdiction(
        meeting_page_id=page["id"],
        jurisdiction="Santa Clara County, CA",
        dry_run=True,
    )
    assert result["changed"] is True
    assert result["before"]["jurisdiction"] == "County of Santa Clara Office"
    assert result["after"]["jurisdiction"] == "Santa Clara County, CA"
    assert result["after"]["jurisdiction_confidence"] == "manual_override"

    async with async_session() as session:
        row = await session.get(MeetingPage, page["id"])
        # Untouched -- dry_run never writes.
        assert row.jurisdiction == "County of Santa Clara Office"
        assert row.jurisdiction_confidence != "manual_override"


async def test_set_explicit_real_run_writes_and_tags_manual_override():
    page = await _seed_page(
        "escribe:set-explicit-real",
        "https://pub-santaclara.escribemeetings.com/set-explicit-real",
        "The County of Santa Clara, CA",
    )
    result = await crud.set_explicit_jurisdiction(
        meeting_page_id=page["id"],
        jurisdiction="Santa Clara County, CA",
        dry_run=False,
    )
    assert result["changed"] is True

    async with async_session() as session:
        row = await session.get(MeetingPage, page["id"])
        assert row.jurisdiction == "Santa Clara County, CA"
        assert row.jurisdiction_confidence == "manual_override"


async def test_set_explicit_is_idempotent_on_second_call():
    page = await _seed_page(
        "escribe:set-explicit-idempotent",
        "https://pub-santaclara.escribemeetings.com/set-explicit-idempotent",
        "County of Santa Clara, CA",
    )
    await crud.set_explicit_jurisdiction(
        meeting_page_id=page["id"],
        jurisdiction="Santa Clara County, CA",
        dry_run=False,
    )
    second = await crud.set_explicit_jurisdiction(
        meeting_page_id=page["id"],
        jurisdiction="Santa Clara County, CA",
        dry_run=False,
    )
    assert second["changed"] is False


async def test_set_explicit_missing_page_returns_not_found():
    result = await crud.set_explicit_jurisdiction(
        meeting_page_id=99999999,
        jurisdiction="Santa Clara County, CA",
        dry_run=True,
    )
    assert result["error"] == "not_found"


async def test_manual_override_survives_a_later_reingest():
    # The real risk a bare write-path would have: _find_or_create_page()
    # refreshes jurisdiction on every re-ingest (a passive
    # ARCHIVE_RECHECK_AFTER hit, "Refresh this page", an admin recheck, a
    # corpus-wide backfill sweep) whenever the fresh resolve produces a
    # truthy jurisdiction -- which real adapters always do. Without an
    # explicit guard, a manual_override write would be silently reverted
    # on the very next re-ingest. Confirms the guard in
    # _find_or_create_page() holds.
    url = "https://pub-santaclara.escribemeetings.com/set-explicit-reingest"
    page = await _seed_page(
        "escribe:set-explicit-reingest", url, "County of Santa Clara Office"
    )
    await crud.set_explicit_jurisdiction(
        meeting_page_id=page["id"],
        jurisdiction="Santa Clara County, CA",
        dry_run=False,
    )

    # A later re-ingest with a DIFFERENT extracted jurisdiction string --
    # simulating the adapter deriving its usual (still independently
    # "valid" but not the decided canonical) value again.
    await crud.ingest_resolution(
        _payload("escribe:set-explicit-reingest", url, "The County of Santa Clara, CA"),
        url,
    )

    async with async_session() as session:
        row = await session.get(MeetingPage, page["id"])
        assert row.jurisdiction == "Santa Clara County, CA"
        assert row.jurisdiction_confidence == "manual_override"


# --- POST /internal/jurisdiction/set-explicit -------------------------------


def test_set_explicit_route_rejects_missing_token():
    response = client.post(
        "/internal/jurisdiction/set-explicit",
        json={"meeting_page_id": 1, "jurisdiction": "Santa Clara County, CA"},
    )
    assert response.status_code == 404


def test_set_explicit_route_rejects_wrong_token():
    response = client.post(
        "/internal/jurisdiction/set-explicit",
        json={"meeting_page_id": 1, "jurisdiction": "Santa Clara County, CA"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 404


async def test_set_explicit_route_dry_run_default_writes_nothing():
    page = await _seed_page(
        "escribe:set-explicit-route-dry",
        "https://pub-santaclara.escribemeetings.com/set-explicit-route-dry",
        "County of Santa Clara Office",
    )
    response = client.post(
        "/internal/jurisdiction/set-explicit",
        json={
            "meeting_page_id": page["id"],
            "jurisdiction": "Santa Clara County, CA",
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is True
    assert body["changed"] is True

    async with async_session() as session:
        row = await session.get(MeetingPage, page["id"])
        assert row.jurisdiction == "County of Santa Clara Office"


async def test_set_explicit_route_real_run_commits():
    page = await _seed_page(
        "escribe:set-explicit-route-real",
        "https://pub-santaclara.escribemeetings.com/set-explicit-route-real",
        "County of Santa Clara Office",
    )
    response = client.post(
        "/internal/jurisdiction/set-explicit?dry_run=false",
        json={
            "meeting_page_id": page["id"],
            "jurisdiction": "Santa Clara County, CA",
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["dry_run"] is False
    assert body["changed"] is True

    async with async_session() as session:
        row = await session.get(MeetingPage, page["id"])
        assert row.jurisdiction == "Santa Clara County, CA"
        assert row.jurisdiction_confidence == "manual_override"


def test_set_explicit_route_rejects_empty_jurisdiction():
    response = client.post(
        "/internal/jurisdiction/set-explicit",
        json={"meeting_page_id": 1, "jurisdiction": "   "},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 400


def test_set_explicit_route_returns_404_for_missing_page():
    response = client.post(
        "/internal/jurisdiction/set-explicit",
        json={"meeting_page_id": 99999999, "jurisdiction": "Santa Clara County, CA"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 404


# --- GET /internal/jurisdiction/search -------------------------------------
# The read-only companion set-explicit needed: it takes a meeting_page_id,
# and nothing else in this file could answer "what id is the row whose
# jurisdiction reads X" without direct DB access.


async def test_jurisdiction_search_finds_by_substring():
    page = await _seed_page(
        "escribe:search-substring",
        "https://pub-santaclara.escribemeetings.com/search-substring",
        "County of Santa Clara Office",
    )
    response = client.get(
        "/internal/jurisdiction/search",
        params={"q": "Santa Clara Office"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    matches = response.json()["matches"]
    ids = [m["id"] for m in matches]
    assert page["id"] in ids
    hit = next(m for m in matches if m["id"] == page["id"])
    assert hit["jurisdiction"] == "County of Santa Clara Office"
    assert hit["slug"] == page["slug"]
    assert hit["source_url_normalized"]


async def test_jurisdiction_search_is_case_insensitive():
    page = await _seed_page(
        "escribe:search-case",
        "https://pub-santaclara.escribemeetings.com/search-case",
        "Santa Clara County, CA",
    )
    response = client.get(
        "/internal/jurisdiction/search",
        params={"q": "santa clara county"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    ids = [m["id"] for m in response.json()["matches"]]
    assert page["id"] in ids


def test_jurisdiction_search_rejects_missing_token():
    response = client.get("/internal/jurisdiction/search", params={"q": "santa clara"})
    assert response.status_code == 404


def test_jurisdiction_search_rejects_wrong_token():
    response = client.get(
        "/internal/jurisdiction/search",
        params={"q": "santa clara"},
        headers={"Authorization": "Bearer wrong"},
    )
    assert response.status_code == 404


def test_jurisdiction_search_requires_q():
    response = client.get(
        "/internal/jurisdiction/search", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code in (400, 422)


async def test_jurisdiction_search_respects_limit():
    for i in range(5):
        await _seed_page(
            f"escribe:search-limit-{i}",
            f"https://pub-somecity.escribemeetings.com/search-limit-{i}",
            "City of Some Limit Town, CA",
        )
    response = client.get(
        "/internal/jurisdiction/search",
        params={"q": "Some Limit Town", "limit": 2},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert len(response.json()["matches"]) == 2
