"""Tests for archive/db/crud.py's delete_meeting_pages_by_slug() and its
HTTP wrapper (POST /internal/admin/delete-pages, archive/main.py).

Real gap found 2026-08-30 merging 3 http/https duplicate-page pairs (see
BACKLOG_DONE.md): every one of the 3 pages being deleted had thumbnail
rows, and delete_meeting_pages_by_slug() didn't clean up
MeetingPageThumbnail or SocialPost before deleting the page -- neither FK
has an ON DELETE CASCADE, so the call would have failed with a real FK
violation rather than silently succeeding or silently leaving orphans.
"""

from fastapi.testclient import TestClient
from sqlalchemy import select

import archive.main
from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import MeetingPage, MeetingPageThumbnail, SocialPost

client = TestClient(archive.main.app)


def _payload(external_id: str, source_url: str) -> dict:
    return {
        "platform": "escribe",
        "source_url": source_url,
        "external_id": external_id,
        "title": "Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "Guelph, ON",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }


async def _seed_page(external_id: str) -> tuple[int, str]:
    url = f"https://placeholder.example.com/{external_id}"
    result = await crud.ingest_resolution(_payload(external_id, url), url)
    async with async_session() as session:
        page = (
            await session.execute(
                select(MeetingPage).where(MeetingPage.slug == result["slug"])
            )
        ).scalar_one()
        return page.id, page.slug


async def test_delete_removes_a_page_with_no_extra_references():
    page_id, slug = await _seed_page("escribe:delete-plain")
    result = await crud.delete_meeting_pages_by_slug([slug], dry_run=False)
    assert result["deleted"] == 1
    async with async_session() as session:
        assert await session.get(MeetingPage, page_id) is None


async def test_delete_cleans_up_thumbnail_rows():
    page_id, slug = await _seed_page("escribe:delete-thumb")
    stored = await crud.store_thumbnail(
        page_id,
        offset_seconds=30,
        image_bytes=b"fake-jpeg-bytes",
        etag="deadbeef",
        is_default=True,
    )
    assert stored is True

    result = await crud.delete_meeting_pages_by_slug([slug], dry_run=False)
    assert result["deleted"] == 1

    async with async_session() as session:
        assert await session.get(MeetingPage, page_id) is None
        remaining = (
            await session.execute(
                select(MeetingPageThumbnail).where(
                    MeetingPageThumbnail.meeting_page_id == page_id
                )
            )
        ).first()
        assert remaining is None


async def test_delete_cleans_up_social_post_rows():
    page_id, slug = await _seed_page("escribe:delete-social")
    post_id = await crud.claim_social_post(page_id, "mastodon")
    assert post_id is not None

    result = await crud.delete_meeting_pages_by_slug([slug], dry_run=False)
    assert result["deleted"] == 1

    async with async_session() as session:
        assert await session.get(MeetingPage, page_id) is None
        remaining = (
            await session.execute(
                select(SocialPost).where(SocialPost.meeting_page_id == page_id)
            )
        ).first()
        assert remaining is None


async def test_dry_run_leaves_thumbnails_and_page_untouched():
    page_id, slug = await _seed_page("escribe:delete-dryrun")
    await crud.store_thumbnail(
        page_id,
        offset_seconds=15,
        image_bytes=b"fake-jpeg-bytes",
        etag="cafef00d",
        is_default=True,
    )

    result = await crud.delete_meeting_pages_by_slug([slug], dry_run=True)
    assert result["dry_run"] is True
    assert result["found"][0]["slug"] == slug

    async with async_session() as session:
        assert await session.get(MeetingPage, page_id) is not None
        still_there = (
            await session.execute(
                select(MeetingPageThumbnail).where(
                    MeetingPageThumbnail.meeting_page_id == page_id
                )
            )
        ).first()
        assert still_there is not None


def test_delete_pages_endpoint_requires_auth():
    resp = client.post("/internal/admin/delete-pages", json={"slugs": ["nope"]})
    assert resp.status_code == 404
