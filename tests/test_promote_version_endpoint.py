"""HTTP-level tests for POST /internal/transcript-version/promote
(archive/main.py) -- the manual-promotion admin action built 2026-08-12
fixing a real stale ALL-CAPS transcript (see BACKLOG_DONE.md). Token
gating and the not-found path are the parts that live entirely in the
route layer, not crud.manually_promote_transcript_version() itself
(covered directly in tests/test_ingest_promotion.py).
"""

from fastapi.testclient import TestClient
from sqlalchemy import select

import archive.main
from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import TranscriptVersion

client = TestClient(archive.main.app)


def test_promote_version_rejects_missing_token():
    response = client.post(
        "/internal/transcript-version/promote",
        json={"slug": "whatever", "version_id": 1},
    )
    assert (
        response.status_code == 404
    )  # not 401/403 -- matches every other /internal/* route


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


async def _ingest_two_versions_second_carrying_a_warning(url_suffix: str):
    """Shared setup for the clear_warnings tests below: a default version
    with clean text, plus a second (non-default, since _is_real_improvement()
    is deliberately narrow -- see archive/db/crud.py) version that already
    carries a garbled warning, mirroring the real dedup-reuse scenario
    (ingest_resolution() reusing an existing version's stale warnings on a
    content-hash-identical re-push -- see manually_promote_transcript_version()'s
    docstring). Returns (slug, warned_version_id).
    """
    url = f"https://example.granicus.com/player/clip/{url_suffix}"
    external_id = f"granicus:{url_suffix}"
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
            "transcript_warnings": [
                crud._GARBLED_MARKER
                + " (not a parsing bug on our end) -- treat it as approximate."
            ],
        },
        url,
    )
    slug = (await crud.lookup_page_for_url(url))["slug"]
    page = await crud.get_page_by_slug(slug)
    warned_version_id = next(v["id"] for v in page["versions"] if not v["is_default"])
    return slug, warned_version_id


async def test_promote_version_with_clear_warnings_resets_promoted_versions_warnings():
    slug, warned_version_id = await _ingest_two_versions_second_carrying_a_warning(
        "promo-clear-warnings-true"
    )

    response = client.post(
        "/internal/transcript-version/promote",
        json={
            "slug": slug,
            "version_id": warned_version_id,
            "clear_warnings": True,
        },
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200

    async with async_session() as session:
        version = await session.get(TranscriptVersion, warned_version_id)
        assert version.is_default is True
        assert version.transcript_warnings == []


async def test_promote_version_without_clear_warnings_leaves_warnings_untouched():
    slug, warned_version_id = await _ingest_two_versions_second_carrying_a_warning(
        "promo-clear-warnings-omitted"
    )

    response = client.post(
        "/internal/transcript-version/promote",
        json={"slug": slug, "version_id": warned_version_id},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200

    async with async_session() as session:
        version = await session.get(TranscriptVersion, warned_version_id)
        assert version.is_default is True
        assert version.transcript_warnings  # still carries the stale warning
        assert crud._GARBLED_MARKER in version.transcript_warnings[0]
