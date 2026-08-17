"""End-to-end tests for archive/search_alerts.py's run_search_alerts() --
real seeded DB rows (same isolated SQLite fixture as
tests/test_search_alerts_matching.py), Clerk mocked directly at the
get_user_contact() call site (no existing precedent in this repo mocks
the Clerk SDK's transport layer, and none is needed here -- same idiom
tests/test_saved_items_routes.py already uses for archive_client
functions), Resend mocked via the same _FakeSession/_FakeResponse pattern
tests/test_lifecycle_emails.py uses. No real email is ever sent by this
suite.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

import archive.utils.email as email_module
from archive import search_alerts
from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import MeetingPage, SavedItem


class _FakeResponse:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def text(self):
        return ""


class _FakeSession:
    def __init__(self, captured):
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def post(self, url, *, headers, json, timeout):
        self._captured.setdefault("posts", []).append({"url": url, "json": json})
        return _FakeResponse()


def _payload(
    external_id: str, source_url: str, title: str, keyword: str, jurisdiction: str
) -> dict:
    return {
        "platform": "granicus",
        "source_url": source_url,
        "external_id": external_id,
        "title": title,
        "date": "2026-01-01",
        "jurisdiction": jurisdiction,
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [
            {
                "start": 42.0,
                "end": 48.0,
                "text": f"discussion of {keyword} calming measures downtown",
            }
        ],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }


async def _make_page(
    external_id: str,
    title: str,
    *,
    keyword: str = "traffic",
    jurisdiction: str = "City of Alerttown, CA",
) -> str:
    # keyword/jurisdiction default to shared values for tests that don't
    # care, but every test in this file that actually asserts on match
    # counts uses its own unique keyword -- run_search_alerts() sweeps
    # the *entire* saved_items table, not scoped to one test, so shared
    # generic fixture text (e.g. every page mentioning "traffic") would
    # cause real, correct-but-confusing cross-test matches.
    url = f"https://example.granicus.com/player/clip/{external_id}"
    result = await crud.ingest_resolution(
        _payload(external_id, url, title, keyword, jurisdiction), url
    )
    return result["slug"]


async def _set_created_at(slug: str, when: datetime) -> None:
    async with async_session() as session:
        page = (
            (await session.execute(select(MeetingPage).where(MeetingPage.slug == slug)))
            .scalars()
            .first()
        )
        page.created_at = when
        await session.commit()


async def _get_cursor(saved_item_id: int):
    async with async_session() as session:
        row = await session.get(SavedItem, saved_item_id)
        return row.last_alerted_at


def _fake_contact(email="ryan@example.com", first_name="Ryan"):
    async def _get(clerk_user_id):
        return {"email": email, "first_name": first_name}

    return _get


async def test_dry_run_composes_but_does_not_advance_cursor_or_send(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")
    monkeypatch.setenv("ALERT_UNSUBSCRIBE_SECRET", "test-alert-secret")
    monkeypatch.setattr(search_alerts, "get_user_contact", _fake_contact())

    captured = {}
    monkeypatch.setattr(
        email_module.aiohttp, "ClientSession", lambda: _FakeSession(captured)
    )

    now = datetime.now(timezone.utc)
    slug = await _make_page("dryrun-1", "Dry Run Meeting", keyword="trafficdryrun")
    await _set_created_at(slug, now)
    item = await crud.save_search("user_dryrun_1", {"q": "trafficdryrun"})
    # Backdate the cursor to before the meeting was archived, so it's a
    # real "new" match -- save_search() itself sets it to "now".
    async with async_session() as session:
        row = await session.get(SavedItem, item["id"])
        row.last_alerted_at = now - timedelta(hours=1)
        await session.commit()

    result = await search_alerts.run_search_alerts(dry_run=True)

    entry = next(e for e in result["sent"] if e["clerk_user_id"] == "user_dryrun_1")
    assert entry["subject"] == 'Somebody said "trafficdryrun"'
    assert "Dry Run Meeting" in entry["body"]

    # No real send happened...
    assert "posts" not in captured
    # ...and the cursor was not advanced -- a dry run must never eat the
    # very match it just showed.
    cursor = await _get_cursor(item["id"])
    assert cursor.replace(tzinfo=timezone.utc) < now


async def test_real_send_advances_cursor_only_on_success(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")
    monkeypatch.setenv("ALERT_UNSUBSCRIBE_SECRET", "test-alert-secret")
    monkeypatch.setattr(search_alerts, "get_user_contact", _fake_contact())
    monkeypatch.setattr(email_module, "_api_key", lambda: "test-key")
    monkeypatch.setenv("RESEND_FROM_ADDRESS", "Ryan <ryan@ally.redtaperecordings.com>")

    captured = {}
    monkeypatch.setattr(
        email_module.aiohttp, "ClientSession", lambda: _FakeSession(captured)
    )

    now = datetime.now(timezone.utc)
    slug = await _make_page(
        "realsend-1", "Real Send Meeting", keyword="trafficrealsend"
    )
    await _set_created_at(slug, now)
    item = await crud.save_search("user_realsend_1", {"q": "trafficrealsend"})
    async with async_session() as session:
        row = await session.get(SavedItem, item["id"])
        row.last_alerted_at = now - timedelta(hours=1)
        await session.commit()

    result = await search_alerts.run_search_alerts(dry_run=False)

    entry = next(e for e in result["sent"] if e["clerk_user_id"] == "user_realsend_1")
    assert entry["subject"] == 'Somebody said "trafficrealsend"'
    assert any(
        p["json"]["subject"] == 'Somebody said "trafficrealsend"'
        for p in captured["posts"]
    )

    cursor = await _get_cursor(item["id"])
    # Advanced to (at least) the run's start time, not left behind.
    assert cursor.replace(tzinfo=timezone.utc) >= now


async def test_missing_email_skips_user_without_crashing_the_run(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")
    monkeypatch.setenv("ALERT_UNSUBSCRIBE_SECRET", "test-alert-secret")

    async def _no_contact(clerk_user_id):
        return None

    monkeypatch.setattr(search_alerts, "get_user_contact", _no_contact)

    now = datetime.now(timezone.utc)
    slug = await _make_page("noemail-1", "No Email Meeting", keyword="trafficnoemail")
    await _set_created_at(slug, now)
    item = await crud.save_search("user_noemail_1", {"q": "trafficnoemail"})
    async with async_session() as session:
        row = await session.get(SavedItem, item["id"])
        row.last_alerted_at = now - timedelta(hours=1)
        await session.commit()

    result = await search_alerts.run_search_alerts(dry_run=True)

    assert not any(e["clerk_user_id"] == "user_noemail_1" for e in result["sent"])
    # Cursor untouched -- this user will be retried on the next run.
    cursor = await _get_cursor(item["id"])
    assert cursor.replace(tzinfo=timezone.utc) < now


async def test_multiple_saved_searches_for_one_user_become_one_digest(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")
    monkeypatch.setenv("ALERT_UNSUBSCRIBE_SECRET", "test-alert-secret")
    monkeypatch.setattr(search_alerts, "get_user_contact", _fake_contact())

    captured = {}
    monkeypatch.setattr(
        email_module.aiohttp, "ClientSession", lambda: _FakeSession(captured)
    )

    now = datetime.now(timezone.utc)
    slug_a = await _make_page(
        "digest-a",
        "Digest Meeting A",
        keyword="trafficdigesta",
        jurisdiction="City of Digesttown, CA",
    )
    slug_b = await _make_page(
        "digest-b",
        "Digest Meeting B",
        keyword="trafficdigestb",
        jurisdiction="City of Digesttown, CA",
    )
    await _set_created_at(slug_a, now)
    await _set_created_at(slug_b, now)

    item_a = await crud.save_search("user_digest_1", {"q": "trafficdigesta"})
    item_b = await crud.save_search("user_digest_1", {"jurisdiction": "Digesttown"})
    for item in (item_a, item_b):
        async with async_session() as session:
            row = await session.get(SavedItem, item["id"])
            row.last_alerted_at = now - timedelta(hours=1)
            await session.commit()

    result = await search_alerts.run_search_alerts(dry_run=True)

    matching_entries = [
        e for e in result["sent"] if e["clerk_user_id"] == "user_digest_1"
    ]
    # One email, not two -- both saved searches' matches bundled together.
    assert len(matching_entries) == 1
