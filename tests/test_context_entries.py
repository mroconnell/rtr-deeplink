"""Real DB integration tests for the `/context` feed's crud layer
(archive/db/crud.py's context_entries functions) and
archive/utils/context_editors.py -- against the isolated SQLite file set
up by tests/conftest.py's _archive_db_schema fixture, not mocked. Each
test uses its own unique clerk_user_id/social URL/external_id so tests
can run in any order without colliding (the fixture DB isn't reset
per-test) -- see tests/test_saved_items.py's own docstring for the same
convention.

Social URLs used here are synthetic ("other"-network example.com links,
each with a random suffix) -- what's under test in this file is the crud
layer's own logic (validation, dedup, joins, status transitions), not URL
parsing, which tests/test_context_links.py already covers against real
and schema-confirmed shapes.
"""

import uuid

from sqlalchemy import select as sa_select

from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import ContextEntry
from archive.utils.context_editors import is_context_editor
from archive.utils.context_links import CONTEXT_TITLE_MAX, SocialRef, parse_social_url


def _social(suffix: str | None = None) -> SocialRef:
    suffix = suffix or uuid.uuid4().hex[:16]
    return parse_social_url(f"https://example.com/context-entries-test/{suffix}")


def _payload(
    external_id: str,
    source_url: str,
    video_url: str = "https://example.com/v.m3u8",
    video_format: str = "m3u8",
    platform: str = "granicus",
    jurisdiction: str = "Context Test City, CA",
) -> dict:
    return {
        "platform": platform,
        "source_url": source_url,
        "external_id": external_id,
        "title": "Context Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": jurisdiction,
        "video_url": video_url,
        "video_format": video_format,
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }


async def _make_page(
    external_id: str,
    video_url: str = "https://example.com/v.m3u8",
    video_format: str = "m3u8",
    platform: str = "granicus",
) -> str:
    url = f"https://example.granicus.com/player/clip/{external_id}"
    result = await crud.ingest_resolution(
        _payload(
            external_id,
            url,
            video_url=video_url,
            video_format=video_format,
            platform=platform,
        ),
        url,
    )
    return result["slug"]


_CONTRACT_KEYS = {
    "id",
    "status",
    "summary",
    "headline",
    "social_url",
    "network",
    "network_label",
    "source_label",
    "embed",
    "match_kind",
    "match_label",
    "t_seconds",
    "timestamp_label",
    "published_at",
    "created_at",
    "updated_at",
    "has_meeting",
    "slug",
    "title",
    "jurisdiction",
    "jurisdiction_display",
    "hub_slug",
    "date",
    "date_html",
    "deep_link",
    "card_url",
}


# --- save_context_entry: validation ---------------------------------------


async def test_draft_with_no_meeting_is_accepted():
    result = await crud.save_context_entry(
        "user_ctx_draft_no_meeting",
        social=_social(),
        summary="A clip from a meeting.",
        status="draft",
    )
    assert "ok" in result
    entry = result["ok"]
    assert entry["status"] == "draft"
    assert entry["has_meeting"] is False
    assert entry["slug"] is None
    assert entry["deep_link"] is None


async def test_publish_without_meeting_is_rejected():
    result = await crud.save_context_entry(
        "user_ctx_publish_no_meeting",
        social=_social(),
        summary="A clip from a meeting.",
        status="published",
    )
    assert result["error"] == "meeting_required"


async def test_publish_without_match_kind_is_rejected():
    slug = await _make_page("ctx-no-match-kind")
    page = await crud.get_page_by_slug(slug)
    result = await crud.save_context_entry(
        "user_ctx_no_match_kind",
        social=_social(),
        summary="A clip.",
        meeting_page_id=page["id"],
        status="published",
    )
    assert result["error"] == "match_kind_required"


async def test_exact_match_kind_needs_a_timestamp():
    slug = await _make_page("ctx-exact-needs-t")
    page = await crud.get_page_by_slug(slug)
    result = await crud.save_context_entry(
        "user_ctx_exact_needs_t",
        social=_social(),
        summary="A clip.",
        meeting_page_id=page["id"],
        match_kind="exact",
        status="draft",  # even a draft can't claim "exact" with no timestamp
    )
    assert result["error"] == "timestamp_required"


async def test_empty_summary_is_rejected():
    result = await crud.save_context_entry(
        "user_ctx_empty_summary", social=_social(), summary="   ", status="draft"
    )
    assert result["error"] == "summary_required"


async def test_overlong_summary_is_rejected():
    from archive.utils.context_links import CONTEXT_SUMMARY_MAX

    result = await crud.save_context_entry(
        "user_ctx_long_summary",
        social=_social(),
        summary="x" * (CONTEXT_SUMMARY_MAX + 1),
        status="draft",
    )
    assert result["error"] == "summary_too_long"


async def test_unknown_meeting_id_is_rejected():
    result = await crud.save_context_entry(
        "user_ctx_unknown_meeting",
        social=_social(),
        summary="A clip.",
        meeting_page_id=999_999_999,
        status="draft",
    )
    assert result["error"] == "unknown_meeting"


async def test_updating_unknown_entry_id_returns_not_found():
    result = await crud.save_context_entry(
        "user_ctx_not_found",
        entry_id=999_999_999,
        social=_social(),
        summary="A clip.",
        status="draft",
    )
    assert result["error"] == "not_found"


# --- title / headline (WO-945) --------------------------------------------
#
# ContextEntry.title is the DB column and the API/form field name; the
# entry dict's read-side key is `headline` instead, because `title` on
# that dict already means the matched MEETING's own title (see
# archive/db/crud.py's _entry_row_to_dict()/_context_entry_dict() comments
# for why). These tests pin that split so it can't quietly drift back
# together.


async def test_title_is_saved_and_returned_as_headline():
    result = await crud.save_context_entry(
        "user_ctx_title_basic",
        social=_social(),
        summary="A clip.",
        title="A short headline",
        status="draft",
    )
    assert "ok" in result
    assert result["ok"]["headline"] == "A short headline"


async def test_title_is_stripped():
    result = await crud.save_context_entry(
        "user_ctx_title_stripped",
        social=_social(),
        summary="A clip.",
        title="   Padded headline   ",
        status="draft",
    )
    assert result["ok"]["headline"] == "Padded headline"


async def test_empty_title_becomes_none():
    result = await crud.save_context_entry(
        "user_ctx_title_empty",
        social=_social(),
        summary="A clip.",
        title="   ",
        status="draft",
    )
    assert result["ok"]["headline"] is None


async def test_missing_title_is_none():
    result = await crud.save_context_entry(
        "user_ctx_title_missing", social=_social(), summary="A clip.", status="draft"
    )
    assert result["ok"]["headline"] is None


async def test_overlong_title_is_rejected():
    result = await crud.save_context_entry(
        "user_ctx_title_long",
        social=_social(),
        summary="A clip.",
        title="x" * (CONTEXT_TITLE_MAX + 1),
        status="draft",
    )
    assert result["error"] == "title_too_long"


async def test_updating_an_entry_changes_its_title():
    social = _social()
    created = await crud.save_context_entry(
        "user_ctx_title_update",
        social=social,
        summary="Original summary.",
        title="Original headline",
        status="draft",
    )
    entry_id = created["ok"]["id"]
    assert created["ok"]["headline"] == "Original headline"

    updated = await crud.save_context_entry(
        "user_ctx_title_update",
        entry_id=entry_id,
        social=social,
        summary="Original summary.",
        title="Updated headline",
        status="draft",
    )
    assert updated["ok"]["id"] == entry_id
    assert updated["ok"]["headline"] == "Updated headline"


async def test_entry_title_does_not_affect_the_meetings_own_title_key():
    slug = await _make_page("ctx-title-vs-meeting-title")
    page = await crud.get_page_by_slug(slug)
    result = await crud.save_context_entry(
        "user_ctx_title_vs_meeting",
        social=_social(),
        summary="A clip.",
        title="Editor's own headline",
        meeting_page_id=page["id"],
        match_kind="related",
        status="draft",
    )
    entry = result["ok"]
    # The meeting's own title (from MeetingPage.title) is unaffected by
    # the entry's headline -- the two are separate fields under separate
    # keys ("title" vs. "headline") on purpose.
    assert entry["title"] == "Context Test Meeting"
    assert entry["headline"] == "Editor's own headline"


# --- duplicate detection ----------------------------------------------


async def test_duplicate_social_url_returns_existing_id_and_status():
    social = _social()
    first = await crud.save_context_entry(
        "user_ctx_dup_1", social=social, summary="First entry.", status="draft"
    )
    assert "ok" in first

    second = await crud.save_context_entry(
        "user_ctx_dup_2", social=social, summary="Second entry, same post."
    )
    assert second["error"] == "duplicate"
    assert second["existing_id"] == first["ok"]["id"]
    assert second["existing_status"] == "draft"


async def test_updating_an_entry_does_not_trip_its_own_duplicate_check():
    social = _social()
    created = await crud.save_context_entry(
        "user_ctx_update_self", social=social, summary="Original summary."
    )
    entry_id = created["ok"]["id"]

    updated = await crud.save_context_entry(
        "user_ctx_update_self",
        entry_id=entry_id,
        social=social,
        summary="Updated summary.",
    )
    assert "ok" in updated
    assert updated["ok"]["id"] == entry_id
    assert updated["ok"]["summary"] == "Updated summary."


# --- published_at stickiness -------------------------------------------


async def test_published_at_is_sticky_across_hide_and_republish():
    slug = await _make_page("ctx-sticky-published-at")
    page = await crud.get_page_by_slug(slug)

    created = await crud.save_context_entry(
        "user_ctx_sticky",
        social=_social(),
        summary="A clip.",
        meeting_page_id=page["id"],
        match_kind="related",
        status="published",
    )
    entry_id = created["ok"]["id"]
    first_published_at = created["ok"]["published_at"]
    assert first_published_at is not None

    hidden = await crud.set_context_entry_status(entry_id, "hidden")
    assert hidden["ok"]["status"] == "hidden"
    assert hidden["ok"]["published_at"] == first_published_at

    republished = await crud.set_context_entry_status(entry_id, "published")
    assert republished["ok"]["status"] == "published"
    assert republished["ok"]["published_at"] == first_published_at


async def test_set_context_entry_status_enforces_the_same_publish_rules():
    created = await crud.save_context_entry(
        "user_ctx_status_rules", social=_social(), summary="No meeting.", status="draft"
    )
    entry_id = created["ok"]["id"]

    result = await crud.set_context_entry_status(entry_id, "published")
    assert result["error"] == "meeting_required"


# --- list_context_entries: public vs editor ------------------------------


async def test_public_list_excludes_drafts_hidden_and_orphans():
    slug = await _make_page("ctx-public-list")
    page = await crud.get_page_by_slug(slug)

    published = await crud.save_context_entry(
        "user_ctx_public_list",
        social=_social(),
        summary="Published entry.",
        meeting_page_id=page["id"],
        match_kind="related",
        status="published",
    )
    draft = await crud.save_context_entry(
        "user_ctx_public_list",
        social=_social(),
        summary="Draft entry.",
        status="draft",
    )
    to_hide = await crud.save_context_entry(
        "user_ctx_public_list",
        social=_social(),
        summary="Soon hidden.",
        meeting_page_id=page["id"],
        match_kind="related",
        status="published",
    )
    await crud.set_context_entry_status(to_hide["ok"]["id"], "hidden")

    # A hand-crafted orphan: "published" in the DB with no meeting at all.
    # Neither save_context_entry() nor set_context_entry_status() can ever
    # produce this (publishing always requires a meeting) -- written
    # directly to the table to prove the public feed's INNER JOIN excludes
    # a row in this state regardless of how it got there, independent of
    # the delete_meeting_pages_by_slug() demotion tested separately below.
    async with async_session() as session:
        orphan = ContextEntry(
            social_url=_social().canonical_url,
            social_url_key=f"url:https://example.com/orphan-{uuid.uuid4().hex}",
            network="other",
            summary="An orphaned published row.",
            meeting_page_id=None,
            status="published",
        )
        session.add(orphan)
        await session.commit()
        orphan_id = orphan.id

    result = await crud.list_context_entries(public=True, page=1, page_size=200)
    ids = {e["id"] for e in result["entries"]}
    assert published["ok"]["id"] in ids
    assert draft["ok"]["id"] not in ids
    assert to_hide["ok"]["id"] not in ids
    assert orphan_id not in ids


async def test_editor_list_includes_every_status():
    slug = await _make_page("ctx-editor-list")
    page = await crud.get_page_by_slug(slug)

    draft = await crud.save_context_entry(
        "user_ctx_editor_list", social=_social(), summary="Draft.", status="draft"
    )
    published = await crud.save_context_entry(
        "user_ctx_editor_list",
        social=_social(),
        summary="Published.",
        meeting_page_id=page["id"],
        match_kind="related",
        status="published",
    )
    to_hide = await crud.save_context_entry(
        "user_ctx_editor_list",
        social=_social(),
        summary="Hidden.",
        meeting_page_id=page["id"],
        match_kind="related",
        status="published",
    )
    hidden = await crud.set_context_entry_status(to_hide["ok"]["id"], "hidden")

    result = await crud.list_context_entries(public=False, page=1, page_size=200)
    ids = {e["id"] for e in result["entries"]}
    assert draft["ok"]["id"] in ids
    assert published["ok"]["id"] in ids
    assert hidden["ok"]["id"] in ids


# --- the entry-dict contract ---------------------------------------------


async def test_entry_dict_has_every_contract_key_without_a_meeting():
    result = await crud.save_context_entry(
        "user_ctx_contract_no_meeting",
        social=_social(),
        summary="No meeting yet.",
        status="draft",
    )
    assert set(result["ok"].keys()) == _CONTRACT_KEYS
    assert result["ok"]["has_meeting"] is False
    for key in (
        "slug",
        "title",
        "jurisdiction",
        "jurisdiction_display",
        "hub_slug",
        "date",
        "date_html",
        "deep_link",
        "card_url",
    ):
        assert result["ok"][key] is None


async def test_entry_dict_has_every_contract_key_with_a_meeting():
    slug = await _make_page("ctx-contract-with-meeting")
    page = await crud.get_page_by_slug(slug)
    result = await crud.save_context_entry(
        "user_ctx_contract_with_meeting",
        social=_social(),
        summary="Has a meeting.",
        meeting_page_id=page["id"],
        match_kind="exact",
        t_seconds=42,
        status="published",
    )
    assert set(result["ok"].keys()) == _CONTRACT_KEYS
    assert result["ok"]["has_meeting"] is True
    assert result["ok"]["slug"] == slug
    assert result["ok"]["deep_link"] == f"/m/{slug}?t=42"
    assert result["ok"]["timestamp_label"] == "0:42"
    assert result["ok"]["match_label"] == "Exact moment"
    assert result["ok"]["network_label"] == "the original site"


async def test_get_context_entry_round_trips_a_saved_entry():
    created = await crud.save_context_entry(
        "user_ctx_get_entry", social=_social(), summary="Round trip.", status="draft"
    )
    entry_id = created["ok"]["id"]
    fetched = await crud.get_context_entry(entry_id)
    assert fetched is not None
    assert fetched["id"] == entry_id
    assert fetched["summary"] == "Round trip."


async def test_get_context_entry_returns_none_for_unknown_id():
    assert await crud.get_context_entry(999_999_999) is None


# --- card_url: YouTube vs a real stored thumbnail vs neither --------------


async def test_youtube_backed_page_gets_an_ytimg_card_url():
    slug = await _make_page(
        "ctx-youtube-card",
        video_url="https://www.youtube.com/embed/dQw4w9WgXcQ",
        video_format="youtube",
        platform="youtube",
    )
    page = await crud.get_page_by_slug(slug)
    result = await crud.save_context_entry(
        "user_ctx_youtube_card",
        social=_social(),
        summary="A youtube clip.",
        meeting_page_id=page["id"],
        match_kind="related",
        status="draft",
    )
    assert (
        result["ok"]["card_url"] == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    )


async def test_non_youtube_page_without_a_stored_thumbnail_gets_no_card_url():
    slug = await _make_page("ctx-no-thumbnail")
    page = await crud.get_page_by_slug(slug)
    result = await crud.save_context_entry(
        "user_ctx_no_thumbnail",
        social=_social(),
        summary="No thumbnail stored for this page.",
        meeting_page_id=page["id"],
        match_kind="related",
        status="draft",
    )
    assert result["ok"]["card_url"] is None


async def test_non_youtube_page_with_a_stored_thumbnail_gets_a_card_url():
    slug = await _make_page("ctx-with-thumbnail")
    page = await crud.get_page_by_slug(slug)
    stored = await crud.store_thumbnail(
        page["id"],
        offset_seconds=30,
        image_bytes=b"fake-jpeg-bytes",
        etag="deadbeef",
        is_default=True,
    )
    assert stored is True

    result = await crud.save_context_entry(
        "user_ctx_with_thumbnail",
        social=_social(),
        summary="This page has a stored default frame.",
        meeting_page_id=page["id"],
        match_kind="related",
        status="draft",
    )
    assert result["ok"]["card_url"] == f"/m/{slug}/card.jpg"


async def test_stored_frames_but_none_the_card_route_would_serve_gets_no_card_url():
    """WO-945, found in the browser: five entries on one meeting used up
    MAX_FRAMES_PER_PAGE with three timestamp frames before any default
    frame existed, and entries four and five rendered broken images.

    /m/{slug}/card.jpg serves the exact frame, else the page's DEFAULT
    frame, else 404. "This page has some stored frame" is therefore not
    enough to advertise a card for an arbitrary `?t=`. Synthetic frames
    (fake bytes), real route rule."""
    from archive.utils.video_thumbnail import target_offset_seconds

    slug = await _make_page("ctx-capped-no-default")
    page = await crud.get_page_by_slug(slug)
    # A frame for some OTHER moment, and deliberately not the default.
    assert await crud.store_thumbnail(
        page["id"],
        offset_seconds=target_offset_seconds(timestamp=100),
        image_bytes=b"fake-jpeg-bytes",
        etag="frame-at-100",
        is_default=False,
    )

    miss = await crud.save_context_entry(
        "user_ctx_capped",
        social=_social(),
        summary="No exact frame for t=4000, and no default frame either.",
        meeting_page_id=page["id"],
        t_seconds=4000,
        match_kind="exact",
        status="draft",
    )
    assert miss["ok"]["card_url"] is None

    hit = await crud.save_context_entry(
        "user_ctx_capped",
        social=_social(),
        summary="The exact frame for t=100 is stored.",
        meeting_page_id=page["id"],
        t_seconds=100,
        match_kind="exact",
        status="draft",
    )
    assert hit["ok"]["card_url"] == f"/m/{slug}/card.jpg?t=100"


async def test_default_frame_covers_any_timestamp():
    """The other half of the route's rule: with a default frame stored,
    any `?t=` is servable (the route falls back to the default)."""
    slug = await _make_page("ctx-default-covers-any-t")
    page = await crud.get_page_by_slug(slug)
    assert await crud.store_thumbnail(
        page["id"],
        offset_seconds=30,
        image_bytes=b"fake-jpeg-bytes",
        etag="the-default",
        is_default=True,
    )
    result = await crud.save_context_entry(
        "user_ctx_default_any_t",
        social=_social(),
        summary="No exact frame for t=4000, but the default exists.",
        meeting_page_id=page["id"],
        t_seconds=4000,
        match_kind="exact",
        status="draft",
    )
    assert result["ok"]["card_url"] == f"/m/{slug}/card.jpg?t=4000"


# --- interaction with delete_meeting_pages_by_slug / delete_account_data --


async def test_delete_meeting_pages_by_slug_demotes_a_published_entry_to_draft():
    slug = await _make_page("ctx-delete-demote")
    page = await crud.get_page_by_slug(slug)
    created = await crud.save_context_entry(
        "user_ctx_delete_demote",
        social=_social(),
        summary="Cites this meeting.",
        meeting_page_id=page["id"],
        match_kind="related",
        status="published",
    )
    entry_id = created["ok"]["id"]
    assert created["ok"]["status"] == "published"

    result = await crud.delete_meeting_pages_by_slug([slug], dry_run=False)
    assert result["deleted"] == 1

    entry = await crud.get_context_entry(entry_id)
    assert entry is not None
    assert entry["status"] == "draft"
    assert entry["has_meeting"] is False
    assert entry["slug"] is None

    async with async_session() as session:
        row = (
            await session.execute(
                sa_select(ContextEntry.meeting_page_id).where(
                    ContextEntry.id == entry_id
                )
            )
        ).scalar_one()
        assert row is None


async def test_delete_meeting_pages_by_slug_dry_run_leaves_context_entry_untouched():
    slug = await _make_page("ctx-delete-dry-run")
    page = await crud.get_page_by_slug(slug)
    created = await crud.save_context_entry(
        "user_ctx_delete_dry_run",
        social=_social(),
        summary="Cites this meeting.",
        meeting_page_id=page["id"],
        match_kind="related",
        status="published",
    )
    entry_id = created["ok"]["id"]

    result = await crud.delete_meeting_pages_by_slug([slug], dry_run=True)
    assert result["dry_run"] is True

    entry = await crud.get_context_entry(entry_id)
    assert entry["status"] == "published"
    assert entry["has_meeting"] is True


async def test_delete_account_data_nulls_context_entry_author_and_keeps_the_entry():
    user = "user_ctx_delete_account"
    created = await crud.save_context_entry(
        user, social=_social(), summary="Authored by this user.", status="draft"
    )
    entry_id = created["ok"]["id"]

    # This user has no SavedItem rows at all -- only a ContextEntry -- so
    # the SavedItem count this function returns is 0, same meaning as
    # before ContextEntry existed (see delete_account_data()'s docstring).
    count = await crud.delete_account_data(user)
    assert count == 0

    entry = await crud.get_context_entry(entry_id)
    assert entry is not None
    assert entry["summary"] == "Authored by this user."

    async with async_session() as session:
        author = (
            await session.execute(
                sa_select(ContextEntry.created_by_clerk_user_id).where(
                    ContextEntry.id == entry_id
                )
            )
        ).scalar_one()
        assert author is None


# --- context_editors.is_context_editor ------------------------------------


def test_is_context_editor_fails_closed_with_no_env_var(monkeypatch):
    monkeypatch.delenv("CONTEXT_EDITOR_CLERK_IDS", raising=False)
    assert is_context_editor("user_abc") is False
    assert is_context_editor(None) is False
    assert is_context_editor("") is False


def test_is_context_editor_fails_closed_with_empty_env_var(monkeypatch):
    monkeypatch.setenv("CONTEXT_EDITOR_CLERK_IDS", "")
    assert is_context_editor("user_abc") is False


def test_is_context_editor_parses_comma_separated_ids(monkeypatch):
    monkeypatch.setenv("CONTEXT_EDITOR_CLERK_IDS", "user_a, user_b ,,user_c")
    assert is_context_editor("user_a") is True
    assert is_context_editor("user_b") is True
    assert is_context_editor("user_c") is True
    assert is_context_editor("user_d") is False


def test_is_context_editor_reads_env_on_every_call(monkeypatch):
    monkeypatch.delenv("CONTEXT_EDITOR_CLERK_IDS", raising=False)
    assert is_context_editor("user_live") is False
    monkeypatch.setenv("CONTEXT_EDITOR_CLERK_IDS", "user_live")
    assert is_context_editor("user_live") is True
