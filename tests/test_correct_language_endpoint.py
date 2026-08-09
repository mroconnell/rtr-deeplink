"""HTTP-level tests for POST /internal/transcript-version/correct-language
(archive/main.py) -- the "public report, admin fixes" language-correction
flow built 2026-08-09 (see BACKLOG_DONE.md). Token gating and the
not-found path are the parts that live entirely in the route layer, not
crud.correct_transcript_version_language() itself (covered directly in
tests/test_ingest_promotion.py).
"""

import os

os.environ.setdefault("ARCHIVE_INGEST_TOKEN", "test-token")

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud

client = TestClient(archive.main.app)


def test_correct_language_rejects_missing_token():
    response = client.post(
        "/internal/transcript-version/correct-language",
        json={"slug": "whatever", "language": "en"},
    )
    assert response.status_code == 404  # not 401/403 -- matches every other /internal/* route


def test_correct_language_rejects_wrong_token():
    response = client.post(
        "/internal/transcript-version/correct-language",
        json={"slug": "whatever", "language": "en"},
        headers={"Authorization": "Bearer not-the-real-token"},
    )
    assert response.status_code == 404


def test_correct_language_404s_for_unknown_slug():
    response = client.post(
        "/internal/transcript-version/correct-language",
        json={"slug": "no-such-slug-at-all", "language": "en"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 404


async def test_correct_language_succeeds_for_real_page():
    url = "https://example.granicus.com/player/clip/promo-http-language-fix"
    await crud.ingest_resolution(
        {
            "platform": "granicus",
            "source_url": url,
            "external_id": "granicus:promo-http-language-fix",
            "title": "Test Meeting",
            "date": "2026-01-01",
            "jurisdiction": "City of Test",
            "video_url": "https://example.com/v.m3u8",
            "video_format": "m3u8",
            "segments": [{"start": 0, "end": 1, "text": "hola"}],
            "agenda_items": [],
            "transcript_language": "es",
            "transcript_warnings": [],
        },
        url,
    )
    slug = (await crud.lookup_page_for_url(url))["slug"]

    response = client.post(
        "/internal/transcript-version/correct-language",
        json={"slug": slug, "language": "en"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert response.json()["language"] == "en"
