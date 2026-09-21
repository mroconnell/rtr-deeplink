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
    "permalink",
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
    "meeting_page_id",
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


# --- get_public_context_entry (WO-945 permalink pages) --------------------


async def test_get_public_context_entry_returns_a_published_entry_with_a_meeting():
    slug = await _make_page("ctx-permalink-published")
    page = await crud.get_page_by_slug(slug)
    created = await crud.save_context_entry(
        "user_ctx_permalink_published",
        social=_social(),
        summary="Publicly permalinkable.",
        meeting_page_id=page["id"],
        match_kind="related",
        status="published",
    )
    entry_id = created["ok"]["id"]

    fetched = await crud.get_public_context_entry(entry_id)
    assert fetched is not None
    assert fetched["id"] == entry_id
    assert fetched["has_meeting"] is True
    assert fetched["meeting_page_id"] == page["id"]
    # No headline on this entry -- falls back to jurisdiction + meeting
    # title (WO-946), both fixed strings from _payload() above.
    assert (
        fetched["permalink"]
        == f"/context/{entry_id}-context-test-city-ca-context-test-meeting"
    )


async def test_get_public_context_entry_returns_none_for_a_draft():
    created = await crud.save_context_entry(
        "user_ctx_permalink_draft",
        social=_social(),
        summary="Still a draft.",
        status="draft",
    )
    entry_id = created["ok"]["id"]
    assert await crud.get_public_context_entry(entry_id) is None


async def test_get_public_context_entry_returns_none_for_a_hidden_entry():
    slug = await _make_page("ctx-permalink-hidden")
    page = await crud.get_page_by_slug(slug)
    created = await crud.save_context_entry(
        "user_ctx_permalink_hidden",
        social=_social(),
        summary="Was published, now hidden.",
        meeting_page_id=page["id"],
        match_kind="related",
        status="published",
    )
    entry_id = created["ok"]["id"]
    await crud.set_context_entry_status(entry_id, "hidden")
    assert await crud.get_public_context_entry(entry_id) is None


async def test_get_public_context_entry_returns_none_for_an_orphaned_entry():
    # Same hand-crafted orphan shape as
    # test_public_list_excludes_drafts_hidden_and_orphans above: "published"
    # in the DB with no real meeting joinable. Neither writer can actually
    # produce this (see that test's own comment), but the INNER JOIN must
    # exclude it regardless of how it got there.
    async with async_session() as session:
        orphan = ContextEntry(
            social_url=_social().canonical_url,
            social_url_key=f"url:https://example.com/permalink-orphan-{uuid.uuid4().hex}",
            network="other",
            summary="An orphaned published row.",
            meeting_page_id=None,
            status="published",
        )
        session.add(orphan)
        await session.commit()
        orphan_id = orphan.id

    assert await crud.get_public_context_entry(orphan_id) is None


async def test_get_public_context_entry_returns_none_for_unknown_id():
    assert await crud.get_public_context_entry(999_999_999) is None


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


# --- get_context_transcript_excerpt (WO-946) -------------------------------


async def _make_page_with_segments(
    external_id: str,
    segments: list,
    *,
    source: str = "sourced",
    transcript_warnings: list | None = None,
) -> str:
    url = f"https://example.granicus.com/player/clip/{external_id}"
    payload = {
        **_payload(external_id, url),
        "segments": segments,
        "source": source,
        "transcript_warnings": transcript_warnings or [],
    }
    result = await crud.ingest_resolution(payload, url)
    return result["slug"]


# Five real-shaped segments (start/end/text -- the shape app/utils/
# vtt_parser.py produces and archive/templates/meeting_page.html renders,
# confirmed by reading both) spanning 230 seconds, used across several
# tests below to exercise the excerpt window logic.
_FIVE_SEGMENTS = [
    {
        "start": 0.0,
        "end": 10.0,
        "text": "Good morning everyone, let's call this meeting to order.",
    },
    {
        "start": 10.0,
        "end": 40.0,
        "text": "First item on the agenda is the budget discussion for this fiscal year.",
    },
    {
        "start": 40.0,
        "end": 70.0,
        "text": "We have a motion on the floor to approve the proposed changes to the zoning code.",
    },
    {
        "start": 70.0,
        "end": 200.0,
        "text": "A long public comment segment with a lot of detail about the project's impact on residents near the affected area.",
    },
    {
        "start": 200.0,
        "end": 230.0,
        "text": "Thank you for your comment. Let's move to the next item on the agenda.",
    },
]


async def test_excerpt_starts_at_the_segment_containing_t_seconds():
    slug = await _make_page_with_segments("ctx-excerpt-basic", _FIVE_SEGMENTS)
    page = await crud.get_page_by_slug(slug)

    excerpt = await crud.get_context_transcript_excerpt(page["id"], 40)
    assert excerpt is not None
    # Segment index 2 ("start": 40.0) is where 40 lands; the window then
    # grows to the minimum of 2 segments (index 3 makes the window's
    # elapsed time exceed the 90s budget on its own, but the floor still
    # requires at least 2), then stops before index 4 because by then
    # both the time and segment-count floor are satisfied.
    assert [line["index"] for line in excerpt["lines"]] == [2, 3]
    assert excerpt["continues"] is True
    assert excerpt["lines"][0]["text"] == _FIVE_SEGMENTS[2]["text"]
    assert excerpt["lines"][0]["timestamp_label"] == "0:40"


async def test_excerpt_deep_links_use_the_segments_real_index_and_version():
    slug = await _make_page_with_segments("ctx-excerpt-deeplink", _FIVE_SEGMENTS)
    page = await crud.get_page_by_slug(slug)

    excerpt = await crud.get_context_transcript_excerpt(page["id"], 40)
    assert excerpt is not None
    version_id = excerpt["version_id"]
    # index 2, not 0 -- the real position in the FULL segments array, so a
    # reader who clicks through highlights the same line meeting_page.html
    # itself would highlight (id="seg-2").
    assert (
        excerpt["lines"][0]["deep_link"]
        == f"/m/{slug}?t=40&line=seg-2&version={version_id}"
    )
    assert (
        excerpt["lines"][1]["deep_link"]
        == f"/m/{slug}?t=70&line=seg-3&version={version_id}"
    )


async def test_excerpt_stops_before_the_transcripts_real_end_reports_continues_false():
    # t_seconds near the very end -- only 1 real segment left after the
    # start, so the excerpt is just that final segment and there's
    # nothing more to read.
    slug = await _make_page_with_segments("ctx-excerpt-tail", _FIVE_SEGMENTS)
    page = await crud.get_page_by_slug(slug)

    excerpt = await crud.get_context_transcript_excerpt(page["id"], 200)
    assert excerpt is not None
    assert [line["index"] for line in excerpt["lines"]] == [4]
    assert excerpt["continues"] is False


async def test_excerpt_falls_back_to_lookback_when_t_is_before_the_first_segment():
    # The transcript's first real line starts at 100s (e.g. silence
    # trimmed at the front) and the clip's own t is 97 -- no segment's
    # start is <= 97, so this falls back to the first segment starting
    # within the 5s lookback window.
    segments = [
        {"start": 100.0, "end": 130.0, "text": "The meeting is now in session."},
        {"start": 130.0, "end": 160.0, "text": "Moving to the first agenda item."},
    ]
    slug = await _make_page_with_segments("ctx-excerpt-lookback", segments)
    page = await crud.get_page_by_slug(slug)

    excerpt = await crud.get_context_transcript_excerpt(page["id"], 97)
    assert excerpt is not None
    assert excerpt["lines"][0]["index"] == 0


async def test_excerpt_is_none_when_the_transcript_stops_long_before_t():
    """Found in review (WO-946): "the last segment starting at or before
    t" is always satisfiable, so a transcript that stops early handed back
    its final line as the context for a moment an hour later. Unrelated
    speech presented as what was said is worse than no excerpt."""
    segments = [
        {"start": 0.0, "end": 30.0, "text": "Call to order."},
        {"start": 30.0, "end": 60.0, "text": "Roll call."},
    ]
    slug = await _make_page_with_segments("ctx-excerpt-stops-early", segments)
    page = await crud.get_page_by_slug(slug)

    assert await crud.get_context_transcript_excerpt(page["id"], 3600) is None
    # Just past the end is still the same moment (a pause, a vote).
    assert await crud.get_context_transcript_excerpt(page["id"], 90) is not None


async def test_excerpt_is_none_when_the_transcript_starts_long_after_t():
    """The mirror case: the fallback took the FIRST line however many
    minutes after `t` it began."""
    segments = [
        {"start": 1800.0, "end": 1830.0, "text": "We are back from recess."},
        {"start": 1830.0, "end": 1860.0, "text": "Item seven."},
    ]
    slug = await _make_page_with_segments("ctx-excerpt-starts-late", segments)
    page = await crud.get_page_by_slug(slug)

    assert await crud.get_context_transcript_excerpt(page["id"], 10) is None


async def test_excerpt_returns_none_with_no_segments():
    slug = await _make_page_with_segments("ctx-excerpt-empty", [])
    page = await crud.get_page_by_slug(slug)
    assert await crud.get_context_transcript_excerpt(page["id"], 10) is None


async def test_excerpt_returns_none_for_a_garbled_transcript():
    from archive.db.crud import _GARBLED_MARKER

    slug = await _make_page_with_segments(
        "ctx-excerpt-garbled",
        _FIVE_SEGMENTS,
        transcript_warnings=[f"This transcript {_GARBLED_MARKER}."],
    )
    page = await crud.get_page_by_slug(slug)
    assert await crud.get_context_transcript_excerpt(page["id"], 40) is None


async def test_excerpt_returns_none_for_a_hallucination_flagged_transcript():
    from archive.db.crud import _HALLUCINATION_MARKER

    slug = await _make_page_with_segments(
        "ctx-excerpt-hallucinated",
        _FIVE_SEGMENTS,
        source="transcribed",
        transcript_warnings=[f"Some lines may have been {_HALLUCINATION_MARKER}."],
    )
    page = await crud.get_page_by_slug(slug)
    assert await crud.get_context_transcript_excerpt(page["id"], 40) is None


async def test_excerpt_returns_none_for_a_truncated_granicus_transcript():
    from archive.db.crud import _GRANICUS_TRUNCATION_MARKER

    slug = await _make_page_with_segments(
        "ctx-excerpt-truncated",
        _FIVE_SEGMENTS,
        transcript_warnings=[f"Stopped at {_GRANICUS_TRUNCATION_MARKER}."],
    )
    page = await crud.get_page_by_slug(slug)
    assert await crud.get_context_transcript_excerpt(page["id"], 40) is None


async def test_excerpt_returns_none_for_unknown_page_id():
    assert await crud.get_context_transcript_excerpt(999_999_999, 10) is None


async def test_excerpt_carries_language_and_source():
    slug = await _make_page_with_segments(
        "ctx-excerpt-source",
        _FIVE_SEGMENTS,
        source="transcribed",
    )
    page = await crud.get_page_by_slug(slug)
    excerpt = await crud.get_context_transcript_excerpt(page["id"], 0)
    assert excerpt is not None
    assert excerpt["source"] == "transcribed"


def _raw_line(index, start, text):
    return {
        "index": index,
        "start": start,
        "timestamp_label": crud.format_timestamp_label(start),
        "deep_link": f"/m/some-slug?t={int(start)}&line=seg-{index}&version=1",
        "text": text,
    }


def test_excerpt_paragraphs_group_caption_fragments_by_speaker():
    """The text is REAL: the first lines of the Jacksonville FL excerpt
    (Granicus clip 7447, t=754) exactly as the browser showed them --
    34 fragments like "[12:34] yourself.", one timestamp each. Garbled
    words and all; this is what government captions look like."""
    lines = [
        _raw_line(332, 751.0, "no rent at this time."),
        _raw_line(333, 754.0, ">> What do do introduce"),
        _raw_line(334, 754.9, "yourself."),
        _raw_line(335, 755.5, ">> So sorry, new Dr shuttle"),
        _raw_line(336, 756.8, "commander Jessell sheriff's"),
        _raw_line(337, 762.0, "office. Ok, thank you."),
        _raw_line(338, 762.5, ">> Understood arts of this is"),
    ]
    paragraphs = crud._excerpt_paragraphs(lines)

    assert [p["text"] for p in paragraphs] == [
        "no rent at this time.",
        "What do do introduce yourself.",
        "So sorry, new Dr shuttle commander Jessell sheriff's office. Ok, thank you.",
        "Understood arts of this is",
    ]
    # Each paragraph keeps its FIRST line's identity, so its timestamp
    # link still lands on the transcript row it opens with.
    assert [p["index"] for p in paragraphs] == [332, 333, 335, 338]
    assert paragraphs[2]["deep_link"].endswith("t=755&line=seg-335&version=1")
    assert not any(">>" in p["text"] for p in paragraphs)


def test_excerpt_paragraphs_split_a_speaker_change_in_the_middle_of_a_line():
    # Synthetic: the mid-line shape, which the real sample above did not
    # happen to contain.
    paragraphs = crud._excerpt_paragraphs(
        [_raw_line(10, 100.0, "Thank you, chair. >> Any questions from the board?")]
    )
    assert [p["text"] for p in paragraphs] == [
        "Thank you, chair.",
        "Any questions from the board?",
    ]


def test_excerpt_paragraphs_break_long_unmarked_speech_at_a_sentence_end():
    # Synthetic: our own audio transcriptions carry no ">>" at all, so the
    # size rule has to do the work alone.
    sentence = "This sentence is here to take up room in the paragraph."
    lines = [_raw_line(i, float(i * 5), sentence) for i in range(12)]
    paragraphs = crud._excerpt_paragraphs(lines)

    assert len(paragraphs) > 1
    assert all(p["text"].endswith(".") for p in paragraphs)
    # Nothing lost, nothing duplicated.
    assert " ".join(p["text"] for p in paragraphs) == " ".join([sentence] * 12)


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
