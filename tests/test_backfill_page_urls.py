"""Tests for the backfill sweep's data source: crud.list_all_page_urls()
(real DB integration, isolated SQLite fixture -- same pattern as
tests/test_transcript_wanted.py) and the token-gated
GET /internal/pages/all-urls route on top of it. Consumed by
scripts/backfill_archived_pages.py -- see that script's own docstring and
BACKLOG.md's "archived pages don't self-heal" entry for why this exists.
"""

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud

client = TestClient(archive.main.app)


def _payload(external_id: str, source_url: str, *, platform="granicus") -> dict:
    return {
        "platform": platform,
        "source_url": source_url,
        "external_id": external_id,
        "title": "Backfill Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "City of Test",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }


async def test_list_all_page_urls_includes_a_real_page():
    url = "https://example.granicus.com/player/clip/backfill-1"
    await crud.ingest_resolution(_payload("backfill:1", url), url)

    pages = await crud.list_all_page_urls()
    match = [p for p in pages if p["source_url_normalized"] == url]
    assert len(match) == 1
    assert match[0]["platform"] == "granicus"
    assert match[0]["slug"]


async def test_list_all_page_urls_includes_every_platform_not_just_youtube():
    # Unlike the transcript-wanted queue (YouTube-only, a different real
    # gap), this backfill sweep exists to fix any adapter's stale data --
    # a Swagit or PrimeGov page belongs in this list just as much.
    url = "https://example.new.swagit.com/videos/backfill-2"
    payload = _payload("backfill:2", url, platform="swagit")
    await crud.ingest_resolution(payload, url)

    pages = await crud.list_all_page_urls()
    assert [
        p
        for p in pages
        if p["source_url_normalized"] == url and p["platform"] == "swagit"
    ]


def test_all_page_urls_route_rejects_missing_token():
    response = client.get("/internal/pages/all-urls")
    assert response.status_code == 404


def test_all_page_urls_route_rejects_wrong_token():
    response = client.get(
        "/internal/pages/all-urls", headers={"Authorization": "Bearer wrong"}
    )
    assert response.status_code == 404


async def test_all_page_urls_route_returns_real_pages():
    url = "https://example.granicus.com/player/clip/backfill-route-1"
    await crud.ingest_resolution(_payload("backfill:route-1", url), url)

    response = client.get(
        "/internal/pages/all-urls", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 200
    pages = response.json()["pages"]
    assert [p for p in pages if p["source_url_normalized"] == url]
