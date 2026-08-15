"""Real DB integration tests for saved meetings/searches (archive/db/
crud.py's Saved* functions) -- against the isolated SQLite file set up by
tests/conftest.py's _archive_db_schema fixture, not mocked. Each test uses
its own unique external_id/source_url/clerk_user_id so tests can run in
any order without colliding (the fixture DB isn't reset per-test).
"""

from archive.db import crud


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
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }


async def _make_page(external_id: str, jurisdiction: str = "City of Test") -> str:
    url = f"https://example.granicus.com/player/clip/{external_id}"
    result = await crud.ingest_resolution(_payload(external_id, url, jurisdiction=jurisdiction), url)
    return result["slug"]


async def test_save_and_unsave_meeting():
    slug = await _make_page("save-item-1")
    user = "user_save_test_1"

    item = await crud.save_meeting(user, slug)
    assert item is not None
    assert item["item_type"] == "saved_meeting"

    assert await crud.is_meeting_saved(user, item["meeting_page_id"]) is True

    removed = await crud.unsave_meeting(user, slug)
    assert removed is True
    assert await crud.is_meeting_saved(user, item["meeting_page_id"]) is False


async def test_save_meeting_unknown_slug_returns_none():
    assert await crud.save_meeting("user_save_test_2", "no-such-slug-at-all") is None


async def test_unsave_meeting_thats_not_saved_is_a_noop():
    slug = await _make_page("save-item-3")
    removed = await crud.unsave_meeting("user_save_test_3", slug)
    assert removed is False


async def test_save_meeting_is_idempotent_not_a_second_row():
    slug = await _make_page("save-item-4")
    user = "user_save_test_4"

    first = await crud.save_meeting(user, slug)
    second = await crud.save_meeting(user, slug)
    assert first["id"] == second["id"]

    items = await crud.list_saved_items(user)
    assert len(items["meetings"]) == 1


async def test_save_and_unsave_search():
    user = "user_save_test_5"
    params = {"q": "traffic", "jurisdiction": "Testville"}

    item = await crud.save_search(user, params)
    assert item["item_type"] == "saved_search"
    assert item["search_params"] == params

    removed = await crud.unsave_item(user, item["id"])
    assert removed is True


async def test_save_search_dedups_by_exact_params():
    user = "user_save_test_6"
    params = {"q": "budget"}

    first = await crud.save_search(user, params)
    second = await crud.save_search(user, dict(params))  # a different dict, same contents
    assert first["id"] == second["id"]

    # A genuinely different search is a separate row.
    third = await crud.save_search(user, {"q": "budget", "jurisdiction": "Elsewhere"})
    assert third["id"] != first["id"]

    items = await crud.list_saved_items(user)
    assert len(items["searches"]) == 2


async def test_unsave_item_scoped_to_owner():
    user_a = "user_save_test_7a"
    user_b = "user_save_test_7b"
    item = await crud.save_search(user_a, {"q": "only-a-owns-this"})

    # user_b can't unsave user_a's row, even knowing its real id.
    removed = await crud.unsave_item(user_b, item["id"])
    assert removed is False

    removed = await crud.unsave_item(user_a, item["id"])
    assert removed is True


async def test_list_saved_items_returns_both_types_and_scoped_to_owner():
    user = "user_save_test_8"
    other = "user_save_test_8_other"

    slug1 = await _make_page("save-item-8a")
    slug2 = await _make_page("save-item-8b")
    await crud.save_meeting(user, slug1)
    await crud.save_search(other, {"q": "not this users search"})
    await crud.save_meeting(user, slug2)
    await crud.save_search(user, {"q": "mine"})

    items = await crud.list_saved_items(user)
    assert len(items["meetings"]) == 2
    assert len(items["searches"]) == 1
    assert {m["slug"] for m in items["meetings"]} == {slug1, slug2}


async def test_list_saved_items_surfaces_a_split_meeting_body():
    # Display-layer wiring (2026-08-15, JURISDICTION_METADATA_PLAN.md):
    # list_saved_items() used to only join MeetingPage.jurisdiction, so a
    # real entity-prefix split (see test_ingest_promotion.py's Housing
    # Authority of Santa Clara case) was silently dropped on the saved-
    # items page even though get_page_by_slug() already carried it.
    user = "user_save_test_9"
    slug = await _make_page("save-item-9", jurisdiction="Housing Authority of the County of Santa Clara")
    await crud.save_meeting(user, slug)

    items = await crud.list_saved_items(user)
    saved = next(m for m in items["meetings"] if m["slug"] == slug)
    assert saved["jurisdiction"] == "County of Santa Clara, CA"
    assert saved["meeting_body"] == "Housing Authority"


async def test_list_saved_items_is_newest_first():
    # SQLite's server_default=func.now() only has second-level precision,
    # so two saves in the same test tick can't be reliably ordered by real
    # wall-clock timing -- set created_at explicitly instead, same pattern
    # already used in tests/test_transcription_jobs.py for the same reason.
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from archive.db.engine import async_session
    from archive.db.models import SavedItem

    user = "user_save_test_order"
    slug_older = await _make_page("save-item-order-a")
    slug_newer = await _make_page("save-item-order-b")
    await crud.save_meeting(user, slug_older)
    await crud.save_meeting(user, slug_newer)

    async with async_session() as session:
        # Ordered by id -- guaranteed insertion order, unlike created_at.
        rows = (
            await session.execute(
                select(SavedItem).where(SavedItem.clerk_user_id == user).order_by(SavedItem.id.asc())
            )
        ).scalars().all()
        older_row, newer_row = rows
        now = datetime.now(timezone.utc)
        older_row.created_at = now - timedelta(minutes=10)
        newer_row.created_at = now
        await session.commit()

    items = await crud.list_saved_items(user)
    assert items["meetings"][0]["slug"] == slug_newer
    assert items["meetings"][1]["slug"] == slug_older


async def test_delete_account_data_purges_only_that_user():
    user = "user_save_test_9"
    other = "user_save_test_9_other"
    slug = await _make_page("save-item-9")

    await crud.save_meeting(user, slug)
    await crud.save_search(user, {"q": "to be deleted"})
    await crud.save_search(other, {"q": "should survive"})

    count = await crud.delete_account_data(user)
    assert count == 2

    assert await crud.list_saved_items(user) == {"meetings": [], "searches": []}
    other_items = await crud.list_saved_items(other)
    assert len(other_items["searches"]) == 1
