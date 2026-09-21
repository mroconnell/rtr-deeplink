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
    title: str | None = None,
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
        title=title,
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


def _yt_url(suffix: str | None = None) -> str:
    # A syntactically real-shaped (11-char) but not-a-real-video id --
    # what's under test with these is context_links.embed_for()'s own
    # data-embed-* wiring and the autoload counting logic, not any actual
    # video, so a fake-but-correctly-shaped id is fine here (unlike
    # test_context_shows_embed_attributes_for_youtube_entry above, which
    # deliberately uses a real one -- see that test's own comment).
    vid = (suffix or uuid.uuid4().hex)[:11]
    return f"https://www.youtube.com/watch?v={vid}"


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


async def test_context_headline_renders_as_a_heading_and_is_escaped(monkeypatch):
    # WO-945: same UNTRUSTED/plain-escape posture as summary above, on
    # the entry's own optional title.
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    entry = await _publish_entry(
        _social_url(),
        summary="Body text for the headline test.",
        title="Breaking <script>alert(1)</script> news",
    )
    response = client.get("/context")
    assert response.status_code == 200
    html = _entry_html(response.text, entry["id"])
    assert html is not None
    assert '<h2 class="context-headline">' in html
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


async def test_context_absent_headline_renders_no_heading_element(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    entry = await _publish_entry(
        _social_url(),
        summary="No headline set for this one.",
    )
    response = client.get("/context")
    assert response.status_code == 200
    html = _entry_html(response.text, entry["id"])
    assert html is not None
    assert "context-headline" not in html


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


async def test_context_feed_xml_title_uses_headline_when_present():
    unique = uuid.uuid4().hex[:10]
    await _publish_entry(
        _social_url(),
        summary="Body text.",
        title=f"A real headline & more {unique}",
    )
    response = client.get("/context/feed.xml")
    root = ET.fromstring(response.text)  # raises if invalid -- pins the & escapes
    titles = [item.find("title").text for item in root.findall("./channel/item")]
    assert any(
        t is not None and f"A real headline & more {unique}" in t for t in titles
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


def test_context_new_has_a_title_input(monkeypatch):
    monkeypatch.setenv("CONTEXT_EDITOR_CLERK_IDS", "user_ctx_new_real_editor")
    monkeypatch.setattr(
        archive.main, "get_clerk_user_id", lambda request: "user_ctx_new_real_editor"
    )
    response = client.get("/context/new")
    assert response.status_code == 200
    assert 'name="title"' in response.text


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


async def test_context_new_prefills_title_from_headline(monkeypatch):
    monkeypatch.setenv("CONTEXT_EDITOR_CLERK_IDS", "user_ctx_new_real_editor")
    monkeypatch.setattr(
        archive.main, "get_clerk_user_id", lambda request: "user_ctx_new_real_editor"
    )
    unique_title = f"Prefill title check {uuid.uuid4().hex[:12]}"
    entry = await _publish_entry(
        _social_url(), summary="Body text.", title=unique_title
    )

    response = client.get(f"/context/new?id={entry['id']}")
    assert response.status_code == 200
    assert f'value="{unique_title}"' in response.text


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


# --- autoload embeds (WO-945) -----------------------------------------------
#
# The test DB is shared across this whole module (see this file's own
# docstring), so these assert on the entries THIS test itself just
# published -- by id, via _entry_html() -- never on a page's full text or
# a raw count of every `data-embed-autoload` on it, which other tests'
# published entries could also contribute to.


async def test_context_autoloads_first_three_of_five_embeddable_entries(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    slug = await _make_page(f"ctx-autoload-five-{uuid.uuid4().hex[:10]}")

    # Published oldest-to-newest below; the feed orders newest-first (see
    # list_context_entries()'s own docstring), so the on-page order ends
    # up e5, e4, e3, e2, e1 -- e5/e4/e3 land in the first three embed
    # slots and e2/e1 (a 4th and 5th embeddable entry) fall past the cap.
    e1 = await _publish_entry(_yt_url(), summary="Autoload one.", slug=slug)
    e2 = await _publish_entry(_yt_url(), summary="Autoload two.", slug=slug)
    e3 = await _publish_entry(_yt_url(), summary="Autoload three.", slug=slug)
    e4 = await _publish_entry(_yt_url(), summary="Autoload four.", slug=slug)
    e5 = await _publish_entry(_yt_url(), summary="Autoload five.", slug=slug)

    response = client.get("/context")
    assert response.status_code == 200
    for entry in (e5, e4, e3):
        html = _entry_html(response.text, entry["id"])
        assert html is not None
        assert "data-embed-autoload" in html
    for entry in (e2, e1):
        html = _entry_html(response.text, entry["id"])
        assert html is not None
        assert "data-embed-kind=" in html  # still has an embed...
        assert "data-embed-autoload" not in html  # ...just not autoloaded


async def test_context_non_embeddable_entry_does_not_use_an_autoload_slot(
    monkeypatch,
):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    slug = await _make_page(f"ctx-autoload-skip-{uuid.uuid4().hex[:10]}")

    # Published oldest-to-newest (e1, e2, e3, then non_embed last), so the
    # on-page order ends up (newest first): non_embed, e3, e2, e1. If the
    # non-embeddable entry wrongly consumed one of the three autoload
    # slots just by taking up a position ahead of the real embeds, the
    # oldest one (e1, third in the *real* count but fourth in raw
    # position) would fall past the cap. It shouldn't -- only entries
    # that actually have an embed count.
    e1 = await _publish_entry(_yt_url(), summary="Skip-slot one.", slug=slug)
    e2 = await _publish_entry(_yt_url(), summary="Skip-slot two.", slug=slug)
    e3 = await _publish_entry(_yt_url(), summary="Skip-slot three.", slug=slug)
    non_embed = await _publish_entry(
        f"https://x.com/someuser/status/{uuid.uuid4().int % 10_000_000_000}",
        summary="Skip-slot non-embed.",
        slug=slug,
    )

    response = client.get("/context")
    assert response.status_code == 200
    non_embed_html = _entry_html(response.text, non_embed["id"])
    assert non_embed_html is not None
    assert "data-embed-kind=" not in non_embed_html
    for entry in (e1, e2, e3):
        html = _entry_html(response.text, entry["id"])
        assert html is not None
        assert "data-embed-autoload" in html


def test_context_page_two_never_autoloads(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    # Page-level, not per-entry: context_feed() passes autoload_embeds=0
    # for every page past the first (see its own comment), so no entry on
    # page 2 can ever carry the attribute -- true regardless of which
    # entries land there, so this checks the whole response.
    response = client.get("/context?page=2")
    assert response.status_code == 200
    assert "data-embed-autoload" not in response.text


def test_context_autoload_embeds_zero_disables_it(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    monkeypatch.setattr(crud, "CONTEXT_AUTOLOAD_EMBEDS", 0)
    response = client.get("/context")
    assert response.status_code == 200
    assert "data-embed-autoload" not in response.text


def test_context_new_never_autoloads(monkeypatch):
    monkeypatch.setenv("CONTEXT_EDITOR_CLERK_IDS", "user_ctx_new_real_editor")
    monkeypatch.setattr(
        archive.main, "get_clerk_user_id", lambda request: "user_ctx_new_real_editor"
    )
    response = client.get("/context/new")
    assert response.status_code == 200
    assert "data-embed-autoload" not in response.text


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
