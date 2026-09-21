"""HTTP-level tests for the public `/context` feed and `/context/feed.xml`
(archive/main.py) -- WO-943. Entries are seeded directly through
archive/db/crud.py's save_context_entry()/set_context_entry_status()
(already covered on their own terms by tests/test_context_entries.py),
the same way tests/test_sitemap.py seeds pages through crud.ingest_
resolution() rather than a route, so what's under test here is the
route/template layer, not the crud layer underneath it. Each test uses
its own unique social URL/external_id -- the fixture DB isn't reset
per-test (see tests/test_context_entries.py's own docstring).

/context/new (editor-only) and the sitemap/nav-link wiring are WO-943's
write-side pieces and are covered in this same file's later additions,
not here.
"""

import uuid
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud
from archive.utils.context_links import parse_social_url

client = TestClient(archive.main.app)


def _payload(external_id: str, source_url: str) -> dict:
    return {
        "platform": "granicus",
        "source_url": source_url,
        "external_id": external_id,
        "title": "Context Page Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "Context Page Test City, CA",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }


async def _make_page(external_id: str) -> str:
    url = f"https://example.granicus.com/player/clip/{external_id}"
    result = await crud.ingest_resolution(_payload(external_id, url), url)
    return result["slug"]


async def _publish_entry(
    social_url: str,
    *,
    summary: str = "A published clip for a route test.",
    match_kind: str = "exact",
    t_seconds: int = 42,
    status: str = "published",
    slug: str | None = None,
) -> dict:
    if slug is None:
        slug = await _make_page(f"ctx-page-{uuid.uuid4().hex[:10]}")
    page = await crud.get_page_by_slug(slug)
    result = await crud.save_context_entry(
        "user_context_pages_test",
        social=parse_social_url(social_url),
        summary=summary,
        meeting_page_id=page["id"],
        t_seconds=t_seconds,
        match_kind=match_kind,
        status=status,
    )
    assert "ok" in result, result
    return result["ok"]


def _social_url(suffix: str | None = None) -> str:
    suffix = suffix or uuid.uuid4().hex[:16]
    return f"https://example.com/context-pages-test/{suffix}"


def _entry_html(page_text: str, entry_id: int) -> str | None:
    """Slices out one entry's <article>...</article> block by id -- the
    test DB is shared across this whole module (see this file's own
    docstring), so a page-1 assertion must scope to the entry under test
    rather than the page's full text, which can carry other tests'
    published entries too."""
    marker = f'id="context-{entry_id}"'
    start = page_text.find(marker)
    if start == -1:
        return None
    end = page_text.find("</article>", start)
    return page_text[start:end]


async def test_context_renders_a_published_entry(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)

    entry = await _publish_entry(
        _social_url(),
        summary="Watch this clip from the council meeting.",
    )

    response = client.get("/context")
    assert response.status_code == 200
    assert "Watch this clip from the council meeting." in response.text
    assert 'rel="noopener nofollow ugc"' in response.text
    assert f'href="{entry["deep_link"]}"' in response.text
    assert entry["match_label"] in response.text


async def test_context_escapes_a_malicious_summary():
    slug = await _make_page(f"ctx-xss-{uuid.uuid4().hex[:10]}")
    await _publish_entry(
        _social_url(),
        summary="Innocent text <script>alert(1)</script> more text.",
        slug=slug,
    )
    response = client.get("/context")
    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text


async def test_context_shows_embed_attributes_for_youtube_entry():
    # dQw4w9WgXcQ is a real, stable public YouTube video id -- the point
    # under test is context_links.embed_for()'s data-embed-* wiring, not
    # this specific video, so any real 11-char id works; using a known
    # one avoids inventing a fake-but-plausible shape (see CLAUDE.md's
    # "synthetic tests" convention).
    await _publish_entry(
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        summary="A YouTube clip of the meeting.",
    )
    response = client.get("/context")
    assert response.status_code == 200
    assert 'data-embed-kind="youtube"' in response.text
    assert 'data-embed-id="dQw4w9WgXcQ"' in response.text


async def test_context_omits_embed_attributes_for_x_entry():
    # The shared test DB (tests/conftest.py) means page 1 also carries
    # entries other tests in this module published (including a YouTube
    # one, which DOES have data-embed-kind) -- so this asserts on just
    # this entry's own <article>, not the whole page's text.
    entry = await _publish_entry(
        f"https://x.com/someuser/status/{uuid.uuid4().int % 10_000_000_000}",
        summary="A link-out post with no embed shape.",
    )
    response = client.get("/context")
    assert response.status_code == 200
    assert _entry_html(response.text, entry["id"]) is not None
    assert "data-embed-kind=" not in _entry_html(response.text, entry["id"])


async def test_context_never_shows_drafts_or_hidden_entries(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    draft_summary = f"Draft entry {uuid.uuid4().hex[:10]} should never render."
    slug = await _make_page(f"ctx-draft-hidden-{uuid.uuid4().hex[:10]}")
    page = await crud.get_page_by_slug(slug)
    draft = await crud.save_context_entry(
        "user_context_pages_test",
        social=parse_social_url(_social_url()),
        summary=draft_summary,
        meeting_page_id=page["id"],
        status="draft",
    )
    assert "ok" in draft

    hidden_summary = f"Hidden entry {uuid.uuid4().hex[:10]} should never render."
    hidden_entry = await _publish_entry(_social_url(), summary=hidden_summary)
    await crud.set_context_entry_status(hidden_entry["id"], "hidden")

    response = client.get("/context")
    assert draft_summary not in response.text
    assert hidden_summary not in response.text


def test_context_noindex_below_threshold(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 1_000_000)
    response = client.get("/context")
    assert response.status_code == 200
    assert '<meta name="robots" content="noindex">' in response.text


def test_context_no_noindex_at_or_above_threshold(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    response = client.get("/context")
    assert response.status_code == 200
    assert '<meta name="robots" content="noindex">' not in response.text


def test_context_page_2_always_noindexed(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    response = client.get("/context?page=2")
    assert response.status_code == 200
    assert '<meta name="robots" content="noindex">' in response.text


def test_context_new_entry_link_shown_only_for_editor(monkeypatch):
    monkeypatch.setenv("CONTEXT_EDITOR_CLERK_IDS", "user_ctx_page_editor")
    monkeypatch.setattr(
        archive.main, "get_clerk_user_id", lambda request: "user_ctx_page_editor"
    )
    response = client.get("/context")
    assert 'href="/context/new"' in response.text

    monkeypatch.setattr(
        archive.main, "get_clerk_user_id", lambda request: "user_someone_else"
    )
    response = client.get("/context")
    assert 'href="/context/new"' not in response.text

    monkeypatch.setattr(archive.main, "get_clerk_user_id", lambda request: None)
    response = client.get("/context")
    assert 'href="/context/new"' not in response.text


def test_context_feed_xml_content_type_and_headers():
    response = client.get("/context/feed.xml")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/rss+xml")
    assert response.headers.get("x-robots-tag") == "noindex"


async def test_context_feed_xml_parses_with_ampersand_and_angle_bracket():
    await _publish_entry(
        _social_url(),
        summary="Budget & Zoning <Special Session> discussion.",
    )
    response = client.get("/context/feed.xml")
    root = ET.fromstring(response.text)  # raises if invalid
    descriptions = [
        item.find("description").text for item in root.findall("./channel/item")
    ]
    assert any(
        d is not None and "Budget & Zoning <Special Session>" in d for d in descriptions
    )


async def test_context_feed_xml_link_is_absolute_deep_link(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")
    entry = await _publish_entry(_social_url(), summary="Absolute link check.")
    response = client.get("/context/feed.xml")
    root = ET.fromstring(response.text)
    links = [item.find("link").text for item in root.findall("./channel/item")]
    assert f"https://redtaperecordings.com{entry['deep_link']}" in links


# --- /context/new (editor-only, phase 2) -----------------------------------


def test_context_new_404s_when_signed_out(monkeypatch):
    monkeypatch.setattr(archive.main, "get_clerk_user_id", lambda request: None)
    response = client.get("/context/new")
    assert response.status_code == 404


def test_context_new_404s_when_signed_in_but_not_an_editor(monkeypatch):
    monkeypatch.setenv("CONTEXT_EDITOR_CLERK_IDS", "user_ctx_new_real_editor")
    monkeypatch.setattr(
        archive.main, "get_clerk_user_id", lambda request: "user_ctx_new_intruder"
    )
    response = client.get("/context/new")
    assert response.status_code == 404


def test_context_new_200s_for_an_editor_with_no_store_and_noindex(monkeypatch):
    monkeypatch.setenv("CONTEXT_EDITOR_CLERK_IDS", "user_ctx_new_real_editor")
    monkeypatch.setattr(
        archive.main, "get_clerk_user_id", lambda request: "user_ctx_new_real_editor"
    )
    response = client.get("/context/new")
    assert response.status_code == 200
    assert response.headers.get("cache-control") == "private, no-store"
    assert '<meta name="robots" content="noindex">' in response.text


async def test_context_new_prefills_from_id(monkeypatch):
    monkeypatch.setenv("CONTEXT_EDITOR_CLERK_IDS", "user_ctx_new_real_editor")
    monkeypatch.setattr(
        archive.main, "get_clerk_user_id", lambda request: "user_ctx_new_real_editor"
    )
    unique_summary = f"Prefill check summary {uuid.uuid4().hex[:12]}."
    entry = await _publish_entry(_social_url(), summary=unique_summary)

    response = client.get(f"/context/new?id={entry['id']}")
    assert response.status_code == 200
    assert unique_summary in response.text


async def test_context_new_editor_list_renders_a_draft_with_no_meeting(monkeypatch):
    monkeypatch.setenv("CONTEXT_EDITOR_CLERK_IDS", "user_ctx_new_real_editor")
    monkeypatch.setattr(
        archive.main, "get_clerk_user_id", lambda request: "user_ctx_new_real_editor"
    )
    draft_summary = f"Editor-list draft {uuid.uuid4().hex[:12]}, no meeting yet."
    result = await crud.save_context_entry(
        "user_ctx_new_draft_author",
        social=parse_social_url(_social_url()),
        summary=draft_summary,
        status="draft",
    )
    assert "ok" in result

    response = client.get("/context/new")
    assert response.status_code == 200
    assert draft_summary in response.text
    assert "No meeting matched yet" in response.text


# --- sitemap / nav link (phase 2) -------------------------------------------


def test_sitemap_includes_context_only_at_or_above_threshold(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 1_000_000)
    response = client.get("/sitemap.xml")
    assert "<loc>/context</loc>" not in response.text

    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    response = client.get("/sitemap.xml")
    assert "<loc>/context</loc>" in response.text


def test_archive_page_nav_has_full_context_link():
    response = client.get("/coverage")
    assert response.status_code == 200
    assert '<a class="nav-link" href="/context">Full Context</a>' in response.text
