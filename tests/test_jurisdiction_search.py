"""Tests for archive/db/crud.py's search_pages_by_jurisdiction_text() and
its HTTP wrapper GET /internal/jurisdiction/search (archive/main.py) --
the read companion POST /internal/jurisdiction/override needed: that
write endpoint takes comma-separated `ids`, but nothing in this file
could answer "what id is the row whose jurisdiction reads X" without
direct DB access. Same admin-token pattern as every other /internal/*
route (see test_jurisdiction_override.py, this file's own template).
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
