"""HTTP-level tests for POST /internal/transcript-version/promote
(archive/main.py) -- the manual-promotion admin action built 2026-08-12
fixing a real stale ALL-CAPS transcript (see BACKLOG_DONE.md). Token
gating and the not-found path are the parts that live entirely in the
route layer, not crud.manually_promote_transcript_version() itself
(covered directly in tests/test_ingest_promotion.py).
"""

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud

client = TestClient(archive.main.app)


def test_promote_version_rejects_missing_token():
    response = client.post(
        "/internal/transcript-version/promote",
        json={"slug": "whatever", "version_id": 1},
    )
    assert response.status_code == 404  # not 401/403 -- matches every other /internal/* route


def test_promote_version_rejects_wrong_token():
    response = client.post(
        "/internal/transcript-version/promote",
        json={"slug": "whatever", "version_id": 1},
        headers={"Authorization": "Bearer not-the-real-token"},
    )
    assert response.status_code == 404


def test_promote_version_404s_for_unknown_slug():
    response = client.post(
        "/internal/transcript-version/promote",
        json={"slug": "no-such-slug-at-all", "version_id": 1},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 404


async def test_promote_version_succeeds_for_real_page():
    url = "https://example.granicus.com/player/clip/promo-http-promote"
    external_id = "granicus:promo-http-promote"
    await crud.ingest_resolution(
        {
            "platform": "granicus",
            "source_url": url,
            "external_id": external_id,
            "title": "Test Meeting",
            "date": "2026-01-01",
            "jurisdiction": "City of Test",
            "video_url": "https://example.com/v.m3u8",
            "video_format": "m3u8",
            "segments": [{"start": 0, "end": 1, "text": "OLD BAD TEXT"}],
            "agenda_items": [],
            "transcript_language": "en",
            "transcript_warnings": [],
        },
        url,
    )
    await crud.ingest_resolution(
        {
            "platform": "granicus",
            "source_url": url,
            "external_id": external_id,
            "video_url": "https://example.com/v.m3u8",
            "video_format": "m3u8",
            "segments": [{"start": 0, "end": 1, "text": "New good text"}],
            "agenda_items": [],
            "transcript_language": "en",
            "transcript_warnings": [],
        },
        url,
    )
    slug = (await crud.lookup_page_for_url(url))["slug"]
    page = await crud.get_page_by_slug(slug)
    replacement_id = next(v["id"] for v in page["versions"] if not v["is_default"])

    response = client.post(
        "/internal/transcript-version/promote",
        json={"slug": slug, "version_id": replacement_id},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert response.json()["promoted_version_id"] == replacement_id

    page = await crud.get_page_by_slug(slug)
    now_default = next(v for v in page["versions"] if v["is_default"])
    assert now_default["id"] == replacement_id
