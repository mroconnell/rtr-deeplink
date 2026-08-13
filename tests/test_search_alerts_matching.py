"""Real DB integration tests for the saved-search alert sweep's core
query (archive/db/crud.py's find_new_matches_for_saved_search() and the
created_after param it added to list_pages()) -- against the isolated
SQLite fixture from tests/conftest.py, same pattern tests/test_saved_items.py
already uses.
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import MeetingPage


def _payload(external_id: str, source_url: str, title: str = "Test Meeting", jurisdiction: str = "City of Test") -> dict:
    return {
        "platform": "granicus",
        "source_url": source_url,
        "external_id": external_id,
        "title": title,
        "date": "2026-01-01",
        "jurisdiction": jurisdiction,
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [{"start": 0.0, "end": 5.0, "text": "discussion of traffic calming measures"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }


async def _make_page(external_id: str, **kwargs) -> str:
    url = f"https://example.granicus.com/player/clip/{external_id}"
    result = await crud.ingest_resolution(_payload(external_id, url, **kwargs), url)
    return result["slug"]


async def _set_created_at(slug: str, when: datetime) -> None:
    async with async_session() as session:
        page = (await session.execute(select(MeetingPage).where(MeetingPage.slug == slug))).scalars().first()
        page.created_at = when
        await session.commit()


async def test_find_new_matches_respects_the_since_cursor():
    now = datetime.now(timezone.utc)
    old_slug = await _make_page("alert-cursor-old", title="Old Meeting")
    new_slug = await _make_page("alert-cursor-new", title="New Meeting")
    await _set_created_at(old_slug, now - timedelta(days=2))
    await _set_created_at(new_slug, now)

    matches = await crud.find_new_matches_for_saved_search({}, since=now - timedelta(hours=1))
    slugs = {m["slug"] for m in matches}
    assert new_slug in slugs
    assert old_slug not in slugs


async def test_find_new_matches_with_no_cursor_returns_everything():
    slug = await _make_page("alert-cursor-none", title="Any Meeting")
    matches = await crud.find_new_matches_for_saved_search({}, since=None)
    assert slug in {m["slug"] for m in matches}


async def test_q_translates_to_keyword_and_actually_matches():
    now = datetime.now(timezone.utc)
    slug = await _make_page("alert-keyword-1", title="Budget Meeting")
    await _set_created_at(slug, now)

    matches = await crud.find_new_matches_for_saved_search(
        {"q": "traffic"}, since=now - timedelta(hours=1)
    )
    assert slug in {m["slug"] for m in matches}

    # A keyword that doesn't appear anywhere finds nothing.
    no_matches = await crud.find_new_matches_for_saved_search(
        {"q": "zoning-word-that-never-appears"}, since=now - timedelta(hours=1)
    )
    assert slug not in {m["slug"] for m in no_matches}


async def test_keyword_less_filter_search_matches_on_jurisdiction_alone():
    now = datetime.now(timezone.utc)
    slug = await _make_page("alert-filter-1", jurisdiction="City of Filtertown, CA")
    await _set_created_at(slug, now)

    matches = await crud.find_new_matches_for_saved_search(
        {"jurisdiction": "Filtertown"}, since=now - timedelta(hours=1)
    )
    assert slug in {m["slug"] for m in matches}


async def test_save_search_sets_last_alerted_at_to_now_not_none():
    item = await crud.save_search("user_alert_cursor_1", {"q": "cursor-init-test"})
    async with async_session() as session:
        from archive.db.models import SavedItem

        row = await session.get(SavedItem, item["id"])
        assert row.last_alerted_at is not None


async def test_resaving_same_search_does_not_reset_cursor():
    user = "user_alert_cursor_2"
    params = {"q": "dedup-cursor-test"}
    first = await crud.save_search(user, params)

    async with async_session() as session:
        from archive.db.models import SavedItem

        row = await session.get(SavedItem, first["id"])
        row.last_alerted_at = datetime.now(timezone.utc) - timedelta(days=30)
        await session.commit()

    second = await crud.save_search(user, dict(params))
    assert second["id"] == first["id"]

    async with async_session() as session:
        from archive.db.models import SavedItem

        row = await session.get(SavedItem, first["id"])
        # SQLite doesn't round-trip tz-awareness (unlike Postgres in
        # production) -- normalize before comparing, same pattern
        # app/main.py's _parse_updated_at() already documents.
        stored = row.last_alerted_at.replace(tzinfo=timezone.utc)
        # Still the backdated value -- re-saving an identical search must
        # never reset an existing cursor forward.
        assert stored < datetime.now(timezone.utc) - timedelta(days=1)


async def test_mark_saved_searches_alerted_advances_cursor():
    item = await crud.save_search("user_alert_cursor_3", {"q": "advance-test"})
    checked_at = datetime.now(timezone.utc)

    await crud.mark_saved_searches_alerted([item["id"]], checked_at)

    async with async_session() as session:
        from archive.db.models import SavedItem

        row = await session.get(SavedItem, item["id"])
        assert row.last_alerted_at.replace(tzinfo=timezone.utc) == checked_at


async def test_list_all_saved_searches_only_returns_saved_search_type():
    user = "user_alert_list_1"
    slug = await _make_page("alert-list-meeting-1")
    await crud.save_meeting(user, slug)
    await crud.save_search(user, {"q": "should-appear"})

    all_searches = await crud.list_all_saved_searches()
    assert all(s["clerk_user_id"] != user or "q" in s["search_params"] for s in all_searches)
    matching = [s for s in all_searches if s["clerk_user_id"] == user]
    assert len(matching) == 1
    assert matching[0]["search_params"] == {"q": "should-appear"}
