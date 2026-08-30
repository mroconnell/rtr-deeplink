"""Tests for archive/db/crud.py's list_http_scheme_backfill_candidates()/
apply_http_scheme_backfill() and their HTTP wrappers
(GET /internal/pages/http-scheme-candidates, POST /internal/pages/
http-scheme-backfill-apply, archive/main.py) -- the real 2026-08-30 gap
found auditing two Cablecast pages a manual refresh couldn't reach:
normalize_url() was fixed (commit 6b47794) to always collapse to
https://, but that fix was never backfilled onto already-archived rows,
so any row still carrying a literal "http://" source_url_normalized is
now permanently unreachable by archive_client.lookup(). Same
dry-run-first, only_ids/exclude_ids-narrowing template as
tests/test_jurisdiction_backfill_apply.py.
"""

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import MeetingPage

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


async def _seed(external_id: str, stored_url: str) -> str:
    """Seeds a page with `stored_url` written verbatim to
    source_url_normalized. ingest_resolution() always recomputes
    source_url_normalized itself via normalize_url(payload["source_url"])
    -- it can't be handed a raw "http://" value directly any more than a
    real new ingest could, which is exactly the fix already working
    correctly for NEW rows. To reproduce a real pre-fix row (one archived
    before that fix existed), ingest via a unique placeholder URL (so a
    "http://" and "https://" pair for the SAME real URL don't collapse
    into one page at ingest time, before either override runs) then
    overwrite source_url_normalized directly -- same "ingest via the
    real path, then hand-edit the one field under test" shape as
    tests/test_jurisdiction_backfill_apply.py's own _seed_stale()."""
    placeholder = f"https://placeholder.example.com/{external_id}"
    result = await crud.ingest_resolution(
        _payload(external_id, placeholder), placeholder
    )
    async with async_session() as session:
        from sqlalchemy import select

        page = (
            await session.execute(
                select(MeetingPage).where(MeetingPage.slug == result["slug"])
            )
        ).scalar_one()
        page.source_url_normalized = stored_url
        await session.commit()
    return result["slug"]


async def _page_for(slug: str) -> MeetingPage:
    from sqlalchemy import select

    async with async_session() as session:
        return (
            await session.execute(select(MeetingPage).where(MeetingPage.slug == slug))
        ).scalar_one()


async def test_list_candidates_reports_a_safe_http_row():
    slug = await _seed(
        "escribe:http-safe", "http://pub-guelph.escribemeetings.com/http-safe"
    )
    result = await crud.list_http_scheme_backfill_candidates()
    row = next(r for r in result["safe"] if r["slug"] == slug)
    assert row["current_url"] == "http://pub-guelph.escribemeetings.com/http-safe"
    assert row["renamed_url"] == "https://pub-guelph.escribemeetings.com/http-safe"
    assert all(m["http_page"]["slug"] != slug for m in result["needs_merge"])


async def test_list_candidates_flags_a_real_collision_as_needs_merge():
    # Real shape confirmed live 2026-08-30: a stale http:// row AND a
    # separate https:// row already exist for the identical URL --
    # exactly the case renaming must never touch.
    http_slug = await _seed(
        "escribe:http-collide-http",
        "http://pub-guelph.escribemeetings.com/http-collide",
    )
    https_slug = await _seed(
        "escribe:http-collide-https",
        "https://pub-guelph.escribemeetings.com/http-collide",
    )
    result = await crud.list_http_scheme_backfill_candidates()
    pair = next(m for m in result["needs_merge"] if m["http_page"]["slug"] == http_slug)
    assert pair["https_page"]["slug"] == https_slug
    assert all(r["slug"] != http_slug for r in result["safe"])


async def test_apply_dry_run_renames_nothing():
    slug = await _seed(
        "escribe:http-apply-dry", "http://pub-guelph.escribemeetings.com/apply-dry"
    )
    result = await crud.apply_http_scheme_backfill(dry_run=True)
    row = next(c for c in result["changes"] if c["slug"] == slug)
    assert row["before"] == "http://pub-guelph.escribemeetings.com/apply-dry"
    assert row["after"] == "https://pub-guelph.escribemeetings.com/apply-dry"

    page = await _page_for(slug)
    assert (
        page.source_url_normalized == "http://pub-guelph.escribemeetings.com/apply-dry"
    )


async def test_apply_for_real_renames_the_url_and_nothing_else():
    slug = await _seed(
        "escribe:http-apply-real", "http://pub-guelph.escribemeetings.com/apply-real"
    )
    result = await crud.apply_http_scheme_backfill(dry_run=False)
    assert any(c["slug"] == slug for c in result["changes"])

    page = await _page_for(slug)
    assert (
        page.source_url_normalized
        == "https://pub-guelph.escribemeetings.com/apply-real"
    )
    assert page.title == "Test Meeting"
    assert page.jurisdiction == "Guelph, ON"


async def test_apply_never_writes_a_colliding_row_even_with_only_ids():
    # The whole reason this function exists: a colliding pair must never
    # be silently overwritten, not even if the caller explicitly names
    # the http row's id via only_ids.
    http_slug = await _seed(
        "escribe:http-collide-apply-http",
        "http://pub-guelph.escribemeetings.com/http-collide-apply",
    )
    await _seed(
        "escribe:http-collide-apply-https",
        "https://pub-guelph.escribemeetings.com/http-collide-apply",
    )
    http_id = (await _page_for(http_slug)).id

    result = await crud.apply_http_scheme_backfill(dry_run=False, only_ids={http_id})
    assert result["changes"] == []
    assert result["skipped_as_collision"] >= 1

    page = await _page_for(http_slug)
    assert (
        page.source_url_normalized
        == "http://pub-guelph.escribemeetings.com/http-collide-apply"
    )


async def test_apply_only_ids_writes_just_that_row():
    keep_slug = await _seed(
        "escribe:http-only-ids-keep",
        "http://pub-guelph.escribemeetings.com/only-ids-keep",
    )
    skip_slug = await _seed(
        "escribe:http-only-ids-skip",
        "http://pub-guelph.escribemeetings.com/only-ids-skip",
    )
    keep_id = (await _page_for(keep_slug)).id

    result = await crud.apply_http_scheme_backfill(dry_run=False, only_ids={keep_id})
    assert [c["slug"] for c in result["changes"]] == [keep_slug]
    assert result["skipped_by_filter"] >= 1

    assert (await _page_for(keep_slug)).source_url_normalized == (
        "https://pub-guelph.escribemeetings.com/only-ids-keep"
    )
    assert (await _page_for(skip_slug)).source_url_normalized == (
        "http://pub-guelph.escribemeetings.com/only-ids-skip"
    )


def test_candidates_endpoint_rejects_missing_token():
    response = client.get("/internal/pages/http-scheme-candidates")
    assert response.status_code == 404


def test_apply_endpoint_rejects_missing_token():
    response = client.post("/internal/pages/http-scheme-backfill-apply")
    assert response.status_code == 404


async def test_candidates_endpoint_returns_the_seeded_row():
    slug = await _seed(
        "escribe:http-endpoint-list",
        "http://pub-guelph.escribemeetings.com/endpoint-list",
    )
    response = client.get(
        "/internal/pages/http-scheme-candidates",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert any(r["slug"] == slug for r in body["safe"])


async def test_apply_endpoint_defaults_to_dry_run():
    slug = await _seed(
        "escribe:http-endpoint-dry",
        "http://pub-guelph.escribemeetings.com/endpoint-dry",
    )
    response = client.post(
        "/internal/pages/http-scheme-backfill-apply",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert response.json()["dry_run"] is True

    page = await _page_for(slug)
    assert page.source_url_normalized == (
        "http://pub-guelph.escribemeetings.com/endpoint-dry"
    )


async def test_apply_endpoint_writes_when_dry_run_false():
    slug = await _seed(
        "escribe:http-endpoint-real",
        "http://pub-guelph.escribemeetings.com/endpoint-real",
    )
    response = client.post(
        "/internal/pages/http-scheme-backfill-apply?dry_run=false",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert response.json()["dry_run"] is False

    page = await _page_for(slug)
    assert page.source_url_normalized == (
        "https://pub-guelph.escribemeetings.com/endpoint-real"
    )


def test_apply_endpoint_rejects_non_integer_id_filter():
    response = client.post(
        "/internal/pages/http-scheme-backfill-apply?exclude_ids=12,not-an-id",
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 400
