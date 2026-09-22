"""Full Context entries on the meeting page itself (`/m/{slug}`) --
WO-1002, BACKLOG.md's "this moment was clipped on social media" backlink.
WO-947 (see tests/test_context_on_hubs.py) already added the same kind
of backlink to `/j/{hub_slug}` and `/state/{state_slug}`; this is the
third and last surface an entry cites without linking back.

Covers crud.list_context_entries_for_meeting() and its wiring into the
`meeting_page()` route (archive/main.py), plus the rendered "This
moment/meeting on social media" section in meeting_page.html (via the
shared _context_mentions.html partial's new meeting_view flag).

Real DB integration against the shared SQLite fixture, same pattern as
tests/test_context_on_hubs.py / tests/test_meeting_page_structured_data.py
(read first). Every seeded page uses a fresh uuid4-suffixed external_id/
source_url, so this file's counts stay stable regardless of test order.
"""

import uuid

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import ContextEntry
from archive.utils.context_links import parse_social_url

client = TestClient(archive.main.app)


def _payload(external_id, url, *, title, platform="granicus"):
    return {
        "platform": platform,
        "source_url": url,
        "external_id": external_id,
        "title": title,
        "date": "2016-03-01",
        "jurisdiction": "Walnut Creek, CA",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }


async def _seed_page(external_id, url, **kwargs) -> dict:
    return await crud.ingest_resolution(_payload(external_id, url, **kwargs), url)


async def _publish_entry_for(
    page_id: int,
    *,
    title=None,
    status="published",
    match_kind="exact",
    t_seconds=5,
) -> dict:
    suffix = uuid.uuid4().hex[:16]
    result = await crud.save_context_entry(
        "user_ctx_meeting_page_test",
        social=parse_social_url(
            f"https://example.com/context-on-meeting-test/{suffix}"
        ),
        summary="A clip cited on a meeting-page test.",
        title=title,
        meeting_page_id=page_id,
        t_seconds=t_seconds,
        match_kind=match_kind,
        status=status,
    )
    assert "ok" in result, result
    return result["ok"]


async def _new_page(prefix: str, title: str) -> dict:
    """Seeds a fresh, uniquely-slugged meeting page."""
    suffix = uuid.uuid4().hex[:8]
    return await _seed_page(
        f"granicus:{prefix}-{suffix}",
        f"https://walnutcreekca.granicus.com/{prefix}/{suffix}",
        title=title,
    )


def _section_html(page_text: str) -> str | None:
    marker = 'class="context-mentions context-mentions-meeting"'
    start = page_text.find(marker)
    if start == -1:
        return None
    section_start = page_text.rfind("<section", 0, start)
    section_end = page_text.find("</section>", start)
    return page_text[section_start : section_end + len("</section>")]


# --- crud: list_context_entries_for_meeting() ------------------------------


async def test_entry_shows_on_its_own_meeting_not_a_different_one():
    a = await _new_page("meetingctx-a", "Meeting A")
    b = await _new_page("meetingctx-b", "Meeting B")
    entry = await _publish_entry_for(a["page_id"], title="A's clip")

    entries_a = await crud.list_context_entries_for_meeting(a["page_id"])
    assert entry["id"] in {e["id"] for e in entries_a}

    entries_b = await crud.list_context_entries_for_meeting(b["page_id"])
    assert entry["id"] not in {e["id"] for e in entries_b}


async def test_draft_entry_never_shows_on_meeting_page_crud():
    page = await _new_page("meetingctx-draft", "Draft test meeting")
    entry = await _publish_entry_for(
        page["page_id"], title="Draft clip", status="draft"
    )

    entries = await crud.list_context_entries_for_meeting(page["page_id"])
    assert entry["id"] not in {e["id"] for e in entries}


async def test_hidden_entry_never_shows_on_meeting_page_crud():
    page = await _new_page("meetingctx-hidden", "Hidden test meeting")
    entry = await _publish_entry_for(page["page_id"], title="Hidden clip")
    await crud.set_context_entry_status(entry["id"], "hidden")

    entries = await crud.list_context_entries_for_meeting(page["page_id"])
    assert entry["id"] not in {e["id"] for e in entries}


async def test_orphaned_entry_never_shows_on_meeting_page_crud():
    # Same hand-crafted-orphan shape test_context_on_hubs.py's own
    # test_orphaned_entry_never_shows_on_a_hub uses: "published" in the DB
    # with no real meeting joinable -- neither writer can actually
    # produce this, so the INNER JOIN inside list_context_entries_for_
    # pages() must exclude it regardless of how it got there.
    page = await _new_page("meetingctx-orphanhost", "Orphan host meeting")

    async with async_session() as session:
        orphan = ContextEntry(
            social_url=f"https://example.com/orphan-meeting-{uuid.uuid4().hex}",
            social_url_key=f"url:https://example.com/orphan-meeting-{uuid.uuid4().hex}",
            network="other",
            summary="An orphaned published row.",
            meeting_page_id=None,
            status="published",
        )
        session.add(orphan)
        await session.commit()
        orphan_id = orphan.id

    entries = await crud.list_context_entries_for_meeting(page["page_id"])
    assert orphan_id not in {e["id"] for e in entries}


async def test_meeting_context_entries_limit_and_order():
    page = await _new_page("meetingctx-limit", "Limit test meeting")
    entries = [
        await _publish_entry_for(page["page_id"], title=f"Limit clip {i}")
        for i in range(crud.MEETING_CONTEXT_ENTRIES + 2)
    ]
    shown = await crud.list_context_entries_for_meeting(page["page_id"])
    assert len(shown) <= crud.MEETING_CONTEXT_ENTRIES
    assert shown == sorted(
        shown, key=lambda e: (e["published_at"], e["id"]), reverse=True
    )
    newest_ids = [e["id"] for e in entries[::-1][: crud.MEETING_CONTEXT_ENTRIES]]
    assert {e["id"] for e in shown} == set(newest_ids)


async def test_meeting_context_check_raising_returns_empty_list():
    # list_context_entries_for_meeting() runs list_context_entries_for_
    # pages() through _context_entries_isolated(), which never raises --
    # same guarantee the hub/state callers already rely on, and for the
    # same reason: a try/except in the caller's OWN session doesn't
    # protect it on Postgres (see _context_entries_isolated()'s
    # docstring).
    page = await _new_page("meetingctx-crudraise", "Crud raise-guard meeting")
    await _publish_entry_for(page["page_id"], title="Raise guard clip")

    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated context_entries failure")

    import archive.db.crud as crud_module

    original = crud_module.list_context_entries_for_pages
    crud_module.list_context_entries_for_pages = _boom
    try:
        entries = await crud.list_context_entries_for_meeting(page["page_id"])
    finally:
        crud_module.list_context_entries_for_pages = original
    assert entries == []


# --- pages: /m/{slug} HTML -------------------------------------------------


async def test_meeting_page_renders_section_with_headline_and_timestamp_link():
    page = await _new_page("meetingpage-render", "Meeting page render test")
    entry = await _publish_entry_for(
        page["page_id"], title="Meeting page render headline", t_seconds=94
    )

    response = client.get(f"/m/{page['slug']}")
    assert response.status_code == 200
    assert "This moment on social media" in response.text
    section = _section_html(response.text)
    assert section is not None
    assert (
        f'<a href="{entry["permalink"]}" class="context-mentions-title">Meeting page render headline</a>'
        in section
    )
    assert 'class="context-match-badge context-match-exact"' in section
    assert (
        f'<a href="{entry["deep_link"]}" class="context-mentions-timestamp">at 1:34</a>'
        in section
    )
    # No outbound social link inside the section -- one outbound link
    # lives on the entry page itself, not here.
    assert f'href="{entry["social_url"]}"' not in section
    # The redundant meeting title/date line is dropped in meeting_view.
    assert "Meeting page render test" not in section


async def test_meeting_page_heading_falls_back_when_no_timestamp():
    page = await _new_page("meetingpage-notime", "No timestamp meeting")
    await _publish_entry_for(
        page["page_id"],
        title="Related, no timestamp",
        match_kind="related",
        t_seconds=None,
    )

    response = client.get(f"/m/{page['slug']}")
    assert response.status_code == 200
    assert "This meeting on social media" in response.text
    assert "This moment on social media" not in response.text
    section = _section_html(response.text)
    assert section is not None
    assert "context-mentions-timestamp" not in section


async def test_meeting_page_omits_section_with_zero_entries():
    page = await _new_page("meetingpage-zero", "Zero entry meeting")

    response = client.get(f"/m/{page['slug']}")
    assert response.status_code == 200
    assert "on social media" not in response.text
    assert "context-mentions" not in response.text


async def test_meeting_page_draft_and_hidden_never_show():
    page = await _new_page("meetingpage-draftonly", "Draft-only meeting")
    await _publish_entry_for(page["page_id"], title="Draft clip", status="draft")
    hidden_entry = await _publish_entry_for(page["page_id"], title="Hidden clip")
    await crud.set_context_entry_status(hidden_entry["id"], "hidden")

    response = client.get(f"/m/{page['slug']}")
    assert response.status_code == 200
    assert "on social media" not in response.text
    assert "context-mentions" not in response.text


async def test_meeting_page_never_shows_a_different_meetings_entry():
    a = await _new_page("meetingpage-a", "Meeting page A")
    b = await _new_page("meetingpage-b", "Meeting page B")
    entry = await _publish_entry_for(a["page_id"], title="Only on A")

    response_a = client.get(f"/m/{a['slug']}")
    assert response_a.status_code == 200
    assert entry["permalink"] in response_a.text

    response_b = client.get(f"/m/{b['slug']}")
    assert response_b.status_code == 200
    assert entry["permalink"] not in response_b.text
    assert "context-mentions" not in response_b.text


async def test_meeting_page_limit_respected_in_html():
    page = await _new_page("meetingpage-limit", "Limit meeting page")
    for i in range(crud.MEETING_CONTEXT_ENTRIES + 2):
        await _publish_entry_for(page["page_id"], title=f"HTML limit clip {i}")

    response = client.get(f"/m/{page['slug']}")
    assert response.status_code == 200
    section = _section_html(response.text)
    assert section is not None
    assert (
        section.count('class="context-mentions-item"') <= crud.MEETING_CONTEXT_ENTRIES
    )


async def test_meeting_page_still_200s_when_context_check_raises(monkeypatch):
    async def _boom(*args, **kwargs):
        raise RuntimeError("simulated context_entries failure")

    monkeypatch.setattr(crud, "list_context_entries_for_pages", _boom)

    page = await _new_page("meetingpage-raise", "Raise guard meeting page")
    await _publish_entry_for(page["page_id"], title="Raise guard headline")

    response = client.get(f"/m/{page['slug']}")
    assert response.status_code == 200
    assert "on social media" not in response.text
