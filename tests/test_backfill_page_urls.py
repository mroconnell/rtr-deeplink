"""Tests for the backfill sweep's data source: crud.list_all_page_urls()
(real DB integration, isolated SQLite fixture -- same pattern as
tests/test_transcript_wanted.py) and the token-gated
GET /internal/pages/all-urls route on top of it. Consumed by
scripts/backfill_archived_pages.py -- see that script's own docstring and
BACKLOG.md's "archived pages don't self-heal" entry for why this exists.

The `video_channel` field (WO-295) is what
scripts/backfill_archived_pages.py's --missing-channel-only flag filters
on -- see tests/test_backfill_missing_channel_only.py for the flag's own
filtering-logic tests against plain dicts; the tests below cover the
real data source those dicts are shaped after.
"""

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud

client = TestClient(archive.main.app)


def _payload(
    external_id: str, source_url: str, *, platform="granicus", video_channel=None
) -> dict:
    payload = {
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
    if video_channel is not None:
        payload["video_channel"] = video_channel
    return payload


async def test_list_all_page_urls_includes_a_real_page():
    url = "https://example.granicus.com/player/clip/backfill-1"
    await crud.ingest_resolution(_payload("backfill:1", url), url)

    pages = await crud.list_all_page_urls()
    match = [p for p in pages if p["source_url_normalized"] == url]
    assert len(match) == 1
    assert match[0]["platform"] == "granicus"
    assert match[0]["slug"]


async def test_list_all_page_urls_carries_the_ingest_date():
    """Added 2026-08-22 for scripts/dedupe_rollup_transcripts.py, whose whole
    affected population is "archived before WO-34 shipped" -- without a real
    ingest date the only bound left is platform, and that is 1,377 of the
    Archive's 2,389 pages. Asserted as a real ISO-8601 string because the
    consumer compares it lexicographically against a date literal."""
    url = "https://example.granicus.com/player/clip/backfill-created-at"
    await crud.ingest_resolution(_payload("backfill:created-at", url), url)

    pages = await crud.list_all_page_urls()
    match = [p for p in pages if p["source_url_normalized"] == url][0]
    assert match["created_at"]
    # "YYYY-MM-DDT..." -- the shape select_candidates()'s string comparison
    # against "2026-08-21" depends on.
    assert match["created_at"][4] == "-" and match["created_at"][10] == "T"
    from datetime import datetime

    datetime.fromisoformat(match["created_at"])


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


async def test_list_all_page_urls_carries_video_channel_when_set():
    url = "https://www.youtube.com/watch?v=backfillchannel1"
    payload = _payload(
        "backfill:channel-1",
        url,
        platform="youtube",
        video_channel="@TestTownCouncil",
    )
    await crud.ingest_resolution(payload, url)

    pages = await crud.list_all_page_urls()
    match = [p for p in pages if p["source_url_normalized"] == url][0]
    assert match["video_channel"] == "@TestTownCouncil"


async def test_list_all_page_urls_carries_video_channel_as_none_when_unset():
    # This is the shape --missing-channel-only filters on -- a page
    # ingested before PR #999 has no video_channel at all, not a blank
    # string, so the key must still come back (as None), not be omitted.
    url = "https://www.youtube.com/watch?v=backfillchannel2"
    payload = _payload("backfill:channel-2", url, platform="youtube")

    await crud.ingest_resolution(payload, url)

    pages = await crud.list_all_page_urls()
    match = [p for p in pages if p["source_url_normalized"] == url][0]
    assert match["video_channel"] is None


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
