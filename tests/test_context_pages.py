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

import json
import re
import uuid
import xml.etree.ElementTree as ET

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud
from archive.utils.context_links import parse_social_url

client = TestClient(archive.main.app)


def _payload(
    external_id: str,
    source_url: str,
    jurisdiction: str = "Context Page Test City, CA",
    title: str = "Context Page Test Meeting",
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
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }


async def _make_page(
    external_id: str,
    jurisdiction: str = "Context Page Test City, CA",
    title: str = "Context Page Test Meeting",
) -> str:
    url = f"https://example.granicus.com/player/clip/{external_id}"
    result = await crud.ingest_resolution(
        _payload(external_id, url, jurisdiction=jurisdiction, title=title), url
    )
    return result["slug"]


async def _make_youtube_page(external_id: str) -> str:
    # A YouTube-hosted MEETING (distinct from a YouTube social post) --
    # its card_url comes back already-absolute (i.ytimg.com, see
    # youtube_thumbnail_url()), the other of the two shapes
    # test_context_entry_page_og_image_absolute_for_youtube_card exists
    # to check. dQw4w9WgXcQ is a real, stable public video id, same
    # reasoning as test_context_shows_embed_attributes_for_youtube_entry
    # above -- the source_url below is synthetic (identity only comes
    # from (platform, external_id) for an ingest like this), so it need
    # not itself be a real YouTube URL.
    source_url = f"https://example.com/context-pages-youtube-test/{external_id}"
    payload = {
        **_payload(external_id, source_url),
        "video_url": "https://www.youtube.com/embed/dQw4w9WgXcQ",
        "video_format": "youtube",
        "platform": "youtube",
    }
    result = await crud.ingest_resolution(payload, source_url)
    return result["slug"]


async def _make_page_with_segments(
    external_id: str,
    segments: list,
    *,
    source: str = "sourced",
    transcript_warnings: list | None = None,
) -> str:
    # Real segment shape (start/end/text) -- app/utils/vtt_parser.py
    # produces it, archive/templates/meeting_page.html renders it
    # (id="seg-{{ loop.index0 }}"); see tests/test_context_entries.py's
    # own copy of this helper for the excerpt-window crud tests this
    # module's page-level excerpt tests build on top of.
    url = f"https://example.granicus.com/player/clip/{external_id}"
    payload = {
        **_payload(external_id, url),
        "segments": segments,
        "source": source,
        "transcript_warnings": transcript_warnings or [],
    }
    result = await crud.ingest_resolution(payload, url)
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


# --- /context/{id} permalink page (WO-945 follow-up) ------------------------
#
# Same shared-DB caution as the rest of this module: scope assertions to
# the one entry under test (there's only ever one <article> on a
# permalink page's own response, but other tests' published entries still
# populate the FEED assertions below, so those go through _entry_html()
# same as the autoload section above).


async def test_context_entry_page_404s_for_a_draft():
    result = await crud.save_context_entry(
        "user_context_pages_test",
        social=parse_social_url(_social_url()),
        summary="Still a draft.",
        status="draft",
    )
    response = client.get(f"/context/{result['ok']['id']}")
    assert response.status_code == 404


async def test_context_entry_page_404s_for_a_hidden_entry():
    entry = await _publish_entry(_social_url(), summary="Will be hidden.")
    await crud.set_context_entry_status(entry["id"], "hidden")
    response = client.get(entry["permalink"])
    assert response.status_code == 404


def test_context_entry_page_404s_for_an_unknown_id():
    response = client.get("/context/999999999")
    assert response.status_code == 404


def test_context_entry_page_404s_for_junk_refs():
    # _CONTEXT_ENTRY_REF_RE (archive/main.py) simply doesn't match any of
    # these -- each falls through to the app's own
    # StarletteHTTPException(404) handler, which renders the same
    # not_found.html, so the only thing worth pinning here is the status
    # code. "12-UPPER" specifically checks that the slug half is
    # lowercase-only, matching what context_permalink() ever actually
    # produces; a 30-digit id checks the length cap
    # (_CONTEXT_ENTRY_REF_MAX_DIGITS) never reaches int() at all.
    for ref in ("abc", "12abc", "12-UPPER", "9" * 30):
        response = client.get(f"/context/{ref}")
        assert response.status_code == 404, ref


def test_context_new_and_feed_xml_are_not_captured_by_the_entry_ref_route():
    # /context/new and /context/feed.xml must keep resolving to their own
    # routes, not fall through to context_entry_page() -- registration
    # order plus _CONTEXT_ENTRY_REF_RE (neither "new" nor "feed.xml"
    # matches `^(\d+)...`) should already guarantee this; this is the
    # outside-in check.
    new_response = client.get("/context/new")
    assert new_response.status_code in (200, 404)  # 404 only if not an editor
    assert new_response.headers.get("content-type", "").startswith("text/html")

    feed_response = client.get("/context/feed.xml")
    assert feed_response.status_code == 200
    assert feed_response.headers["content-type"].startswith("application/rss+xml")


async def test_context_entry_page_200_headline_is_the_only_h1(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    entry = await _publish_entry(
        _social_url(),
        summary="Body text.",
        title="The one and only heading",
    )
    response = client.get(entry["permalink"])
    assert response.status_code == 200
    assert response.text.count("<h1") == 1
    assert '<h1 class="context-headline">The one and only heading</h1>' in response.text
    # Not a link to itself.
    assert (
        f'<h1 class="context-headline"><a href="/context/{entry["id"]}">'
        not in response.text
    )


async def test_context_entry_page_escapes_the_summary(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    entry = await _publish_entry(
        _social_url(),
        summary="Innocent text <script>alert(1)</script> more text.",
        title="Escaping check",
    )
    response = client.get(entry["permalink"])
    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text


async def test_context_entry_page_no_headline_uses_meeting_title_as_h1(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    entry = await _publish_entry(_social_url(), summary="No title on this one.")
    response = client.get(entry["permalink"])
    assert response.status_code == 200
    assert response.text.count("<h1") == 1
    assert f'<h1 class="context-headline">{entry["title"]}</h1>' in response.text


async def test_context_entry_page_noindex_follows_the_feed_threshold(monkeypatch):
    entry = await _publish_entry(_social_url(), summary="Threshold check.")

    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 1_000_000)
    response = client.get(entry["permalink"])
    assert response.status_code == 200
    assert '<meta name="robots" content="noindex">' in response.text

    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    response = client.get(entry["permalink"])
    assert response.status_code == 200
    assert '<meta name="robots" content="noindex">' not in response.text


async def test_context_entry_page_canonical_and_og_tags(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    monkeypatch.setitem(
        archive.main.templates.env.globals,
        "public_base_url",
        "https://redtaperecordings.com",
    )
    entry = await _publish_entry(
        _social_url(),
        summary="Canonical and OG tag check.",
        title="Canonical check headline",
    )
    response = client.get(entry["permalink"])
    assert response.status_code == 200
    permalink = f"https://redtaperecordings.com{entry['permalink']}"
    assert f'<link rel="canonical" href="{permalink}">' in response.text
    assert f'<meta property="og:url" content="{permalink}">' in response.text
    assert (
        '<meta property="og:title" content="Canonical check headline">' in response.text
    )
    assert 'property="og:description" content="Canonical and OG tag check.">' in (
        response.text
    )
    assert '<meta property="og:type" content="article">' in response.text


async def test_context_entry_page_og_image_absolute_for_youtube_card(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    monkeypatch.setitem(
        archive.main.templates.env.globals,
        "public_base_url",
        "https://redtaperecordings.com",
    )
    slug = await _make_youtube_page(f"ctx-permalink-ytpage-{uuid.uuid4().hex[:10]}")
    page = await crud.get_page_by_slug(slug)
    result = await crud.save_context_entry(
        "user_context_pages_test",
        social=parse_social_url(_social_url()),
        summary="YouTube-backed og:image check.",
        meeting_page_id=page["id"],
        match_kind="related",
        status="published",
    )
    entry = result["ok"]
    assert entry["card_url"] is not None
    assert entry["card_url"].startswith("https://i.ytimg.com/")

    response = client.get(entry["permalink"])
    assert response.status_code == 200
    # Already absolute -- must NOT be double-prefixed with public_base_url.
    assert f'<meta property="og:image" content="{entry["card_url"]}">' in response.text
    assert (
        f'content="https://redtaperecordings.com{entry["card_url"]}"'
        not in response.text
    )


async def test_context_entry_page_og_image_absolute_for_relative_card_url(
    monkeypatch,
):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    monkeypatch.setitem(
        archive.main.templates.env.globals,
        "public_base_url",
        "https://redtaperecordings.com",
    )
    slug = await _make_page(f"ctx-permalink-thumb-{uuid.uuid4().hex[:10]}")
    page = await crud.get_page_by_slug(slug)
    stored = await crud.store_thumbnail(
        page["id"],
        offset_seconds=30,
        image_bytes=b"fake-jpeg-bytes",
        etag="deadbeef-permalink",
        is_default=True,
    )
    assert stored is True
    result = await crud.save_context_entry(
        "user_context_pages_test",
        social=parse_social_url(_social_url()),
        summary="Relative card_url og:image check.",
        meeting_page_id=page["id"],
        match_kind="related",
        status="published",
    )
    entry = result["ok"]
    assert entry["card_url"] == f"/m/{slug}/card.jpg"

    response = client.get(entry["permalink"])
    assert response.status_code == 200
    assert (
        f'<meta property="og:image" content="https://redtaperecordings.com{entry["card_url"]}">'
        in response.text
    )


async def test_context_entry_page_og_image_falls_back_to_generic(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    monkeypatch.setitem(
        archive.main.templates.env.globals,
        "public_base_url",
        "https://redtaperecordings.com",
    )
    monkeypatch.setitem(
        archive.main.templates.env.globals,
        "generic_card_image_url",
        "https://redtaperecordings.com/m/some-generic/card.jpg",
    )
    slug = await _make_page(f"ctx-permalink-nocard-{uuid.uuid4().hex[:10]}")
    page = await crud.get_page_by_slug(slug)
    result = await crud.save_context_entry(
        "user_context_pages_test",
        social=parse_social_url(_social_url()),
        summary="No card_url at all -- falls back to the generic image.",
        meeting_page_id=page["id"],
        match_kind="related",
        status="published",
    )
    entry = result["ok"]
    assert entry["card_url"] is None

    response = client.get(entry["permalink"])
    assert response.status_code == 200
    assert (
        '<meta property="og:image" content="https://redtaperecordings.com/m/some-generic/card.jpg">'
        in response.text
    )


async def test_context_entry_page_embed_autoloads(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    entry = await _publish_entry(_yt_url(), summary="Embed should autoload here.")
    response = client.get(entry["permalink"])
    assert response.status_code == 200
    assert "data-embed-autoload" in response.text
    assert 'data-embed-kind="youtube"' in response.text


async def test_feed_headline_links_to_the_permalink(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    entry = await _publish_entry(
        _social_url(),
        summary="Headline should link to the permalink on the feed.",
        title="Linked headline",
    )
    response = client.get("/context")
    assert response.status_code == 200
    html = _entry_html(response.text, entry["id"])
    assert html is not None
    assert (
        f'<h2 class="context-headline"><a href="{entry["permalink"]}">Linked headline</a></h2>'
        in html
    )


async def test_feed_no_headline_entry_still_has_a_permalink_link(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    entry = await _publish_entry(
        _social_url(), summary="No headline, but still linkable."
    )
    response = client.get("/context")
    assert response.status_code == 200
    html = _entry_html(response.text, entry["id"])
    assert html is not None
    assert "context-headline" not in html
    assert (
        f'<a href="{entry["permalink"]}" class="context-permalink-quiet">Link to this post</a>'
        in html
    )


async def test_editor_list_draft_headline_is_not_a_link(monkeypatch):
    monkeypatch.setenv("CONTEXT_EDITOR_CLERK_IDS", "user_ctx_permalink_editor")
    monkeypatch.setattr(
        archive.main, "get_clerk_user_id", lambda request: "user_ctx_permalink_editor"
    )
    unique_title = f"Draft headline {uuid.uuid4().hex[:10]}"
    created = await crud.save_context_entry(
        "user_ctx_permalink_editor",
        social=parse_social_url(_social_url()),
        summary="A draft with a headline.",
        title=unique_title,
        status="draft",
    )
    entry_id = created["ok"]["id"]
    permalink = created["ok"]["permalink"]

    response = client.get("/context/new")
    assert response.status_code == 200
    html = _entry_html(response.text, entry_id)
    assert html is not None
    assert f'<h2 class="context-headline">{unique_title}</h2>' in html
    assert f'<a href="{permalink}">{unique_title}</a>' not in html


async def test_editor_list_published_entry_headline_links_to_permalink(monkeypatch):
    monkeypatch.setenv("CONTEXT_EDITOR_CLERK_IDS", "user_ctx_permalink_editor2")
    monkeypatch.setattr(
        archive.main, "get_clerk_user_id", lambda request: "user_ctx_permalink_editor2"
    )
    unique_title = f"Published headline {uuid.uuid4().hex[:10]}"
    entry = await _publish_entry(
        _social_url(), summary="A published entry with a headline.", title=unique_title
    )

    response = client.get("/context/new")
    assert response.status_code == 200
    html = _entry_html(response.text, entry["id"])
    assert html is not None
    assert (
        f'<h2 class="context-headline"><a href="{entry["permalink"]}">{unique_title}</a></h2>'
        in html
    )
    assert (
        f'<a href="{entry["permalink"]}" class="cassette-btn-outline">View post</a>'
        in html
    )


# --- slugged permalinks + 301s (WO-946) -------------------------------------


async def test_context_entry_page_301s_from_the_bare_id(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    entry = await _publish_entry(
        _social_url(), summary="Bare id redirect check.", title="Bare Id Redirect Check"
    )
    bare = f"/context/{entry['id']}"
    assert bare != entry["permalink"]  # this entry really does have a slug

    response = client.get(bare, follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == entry["permalink"]


async def test_context_entry_page_301_preserves_the_query_string(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    entry = await _publish_entry(
        _social_url(),
        summary="Query string redirect check.",
        title="Query String Check",
    )
    bare = f"/context/{entry['id']}"
    response = client.get(f"{bare}?utm_source=test&x=1", follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == f"{entry['permalink']}?utm_source=test&x=1"


async def test_context_entry_page_301s_from_a_stale_slug_after_a_title_edit(
    monkeypatch,
):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    entry = await _publish_entry(
        _social_url(), summary="Stale slug check.", title="Original Title Here"
    )
    stale_permalink = entry["permalink"]

    updated = await crud.save_context_entry(
        "user_context_pages_test",
        entry_id=entry["id"],
        social=parse_social_url(entry["social_url"]),
        summary=entry["summary"],
        title="Updated Title Entirely",
        meeting_page_id=entry["meeting_page_id"],
        t_seconds=entry["t_seconds"],
        match_kind=entry["match_kind"],
        status="published",
    )
    new_entry = updated["ok"]
    assert new_entry["permalink"] != stale_permalink

    response = client.get(stale_permalink, follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == new_entry["permalink"]


async def test_context_entry_page_301s_from_a_wrong_slug(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    entry = await _publish_entry(
        _social_url(), summary="Wrong slug check.", title="The Real Title"
    )
    wrong = f"/context/{entry['id']}-totally-the-wrong-slug"
    assert wrong != entry["permalink"]

    response = client.get(wrong, follow_redirects=False)
    assert response.status_code == 301
    assert response.headers["location"] == entry["permalink"]


# --- title tag (WO-946) -----------------------------------------------------


def _expected_title(headline: str, jurisdiction_display: str | None) -> str:
    """Mirrors context_entry_page.html's own <title> rule (WO-946) --
    used here because effective_jurisdiction() (archive/db/crud.py) can
    enrich a plain jurisdiction string at ingest time (e.g. a real,
    recognized government gets its registry display name, "(city)"
    disambiguators and all), so a test can't safely assume its own raw
    input string is what ends up in entry["jurisdiction_display"]. Tests
    below always read that field back from the real entry rather than
    guessing, then use this to compute what the page SHOULD show."""
    named = bool(jurisdiction_display) and (
        jurisdiction_display.lower() in headline.lower()
    )
    with_gov = headline + (
        f" — {jurisdiction_display}" if (jurisdiction_display and not named) else ""
    )
    # The place is what people search for, so it is never what gets
    # dropped: past ~65 characters only the site suffix goes.
    full = f"{with_gov} | Red Tape Recordings"
    if len(full) <= 65:
        return full
    return with_gov


async def test_context_entry_page_title_includes_jurisdiction_when_it_fits(
    monkeypatch,
):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    # A short, clearly-synthetic jurisdiction (per CLAUDE.md's synthetic-
    # test convention -- not a real place, so no registry enrichment can
    # apply) with a short headline that omits it, so the full "headline —
    # jurisdiction | Red Tape Recordings" line should fit under 65 chars.
    slug = await _make_page(
        f"ctx-title-short-{uuid.uuid4().hex[:8]}", jurisdiction="Testville, ZZ"
    )
    entry = await _publish_entry(
        _social_url(),
        summary="Short title tag check.",
        title="Council votes on zoning",
        slug=slug,
    )
    response = client.get(entry["permalink"])
    assert response.status_code == 200
    expected = _expected_title("Council votes on zoning", entry["jurisdiction_display"])
    assert len(expected) <= 65  # sanity: this test's premise is "it fits"
    assert f"<title>{expected}</title>" in response.text
    assert entry["jurisdiction_display"] in expected  # the jurisdiction really is there


async def test_context_entry_page_title_omits_jurisdiction_already_named(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    slug = await _make_page(
        f"ctx-title-named-{uuid.uuid4().hex[:8]}", jurisdiction="Testville, ZZ"
    )
    entry = await _publish_entry(
        _social_url(),
        summary="Jurisdiction-already-named title tag check.",
        title="Testville, ZZ council votes on zoning",
        slug=slug,
    )
    response = client.get(entry["permalink"])
    assert response.status_code == 200
    expected = _expected_title(
        "Testville, ZZ council votes on zoning", entry["jurisdiction_display"]
    )
    assert f"<title>{expected}</title>" in response.text
    # Never doubled -- the jurisdiction appears once (inside the headline
    # itself), not appended a second time.
    title_text = response.text.split("<title>")[1].split("</title>")[0]
    assert title_text.lower().count(entry["jurisdiction_display"].lower()) == 1


async def test_context_entry_page_title_keeps_jurisdiction_and_drops_the_site_suffix(
    monkeypatch,
):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    # Deliberately verbose and obviously synthetic -- long enough that
    # "headline — jurisdiction | Red Tape Recordings" can't fit in 65
    # characters, however the real jurisdiction_display ends up reading.
    long_jurisdiction = (
        "Zzznonexistent Testing Placeholder Municipality Number Twelve, ZZ"
    )
    slug = await _make_page(
        f"ctx-title-long-gov-{uuid.uuid4().hex[:8]}", jurisdiction=long_jurisdiction
    )
    entry = await _publish_entry(
        _social_url(),
        summary="Long jurisdiction title tag check.",
        title="Budget vote",
        slug=slug,
    )
    response = client.get(entry["permalink"])
    assert response.status_code == 200
    expected = _expected_title("Budget vote", entry["jurisdiction_display"])
    # This test's premise: the full line really was too long to fit. The
    # first draft dropped the JURISDICTION here; an ordinary 56-character
    # headline came out with no place name at all (seen in the browser).
    assert len(f"{expected} | Red Tape Recordings") > 65
    assert entry["jurisdiction_display"] in expected
    assert "Red Tape Recordings" not in expected
    assert f"<title>{expected}</title>" in response.text


async def test_context_entry_page_title_never_shortens_the_headline_itself(
    monkeypatch,
):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    long_headline = (
        "A very long headline that exceeds the sixty five character budget on its own"
    )
    entry = await _publish_entry(
        _social_url(),
        summary="Headline-never-shortened title tag check.",
        title=long_headline,
    )
    response = client.get(entry["permalink"])
    assert response.status_code == 200
    expected = _expected_title(long_headline, entry["jurisdiction_display"])
    assert expected.startswith(long_headline)
    assert f"<title>{expected}</title>" in response.text


# --- JSON-LD (WO-946) --------------------------------------------------------

_JSON_LD_RE = re.compile(
    r'<script type="application/ld\+json">\s*(\{.*?\})\s*</script>', re.DOTALL
)


async def test_context_entry_page_json_ld_parses_and_resists_script_breakout(
    monkeypatch,
):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    monkeypatch.setitem(
        archive.main.templates.env.globals,
        "public_base_url",
        "https://redtaperecordings.com",
    )
    evil_headline = "Evil headline </script><script>alert(1)</script>"
    entry = await _publish_entry(
        _social_url(), summary="JSON-LD breakout check.", title=evil_headline
    )
    response = client.get(entry["permalink"])
    assert response.status_code == 200
    # The literal breakout string must never appear unescaped anywhere on
    # the page -- tojson's \u-escaping is what prevents this.
    assert "</script><script>alert(1)</script>" not in response.text

    blocks = _JSON_LD_RE.findall(response.text)
    assert len(blocks) == 2
    blog_posting = json.loads(blocks[0])  # raises if it doesn't parse
    assert blog_posting["@type"] == "BlogPosting"
    assert blog_posting["headline"] == evil_headline
    assert (
        blog_posting["isBasedOn"] == f"https://redtaperecordings.com/m/{entry['slug']}"
    )
    assert blog_posting["citation"] == entry["social_url"]
    assert blog_posting["publisher"] == {
        "@type": "Organization",
        "name": "Red Tape Recordings",
    }
    assert blog_posting["author"] == {
        "@type": "Organization",
        "name": "Red Tape Recordings",
    }

    breadcrumbs = json.loads(blocks[1])  # raises if it doesn't parse
    assert breadcrumbs["@type"] == "BreadcrumbList"
    names = [item["name"] for item in breadcrumbs["itemListElement"]]
    assert names == ["Home", "Full Context", evil_headline]


# --- visible publish date (WO-946) ------------------------------------------


async def test_context_entry_page_has_a_visible_time_element(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    entry = await _publish_entry(
        _social_url(), summary="Time element check.", title="Time element headline"
    )
    response = client.get(entry["permalink"])
    assert response.status_code == 200
    assert '<time datetime="' in response.text
    assert '<meta property="article:published_time" content="' in response.text


# --- sitemap (WO-946) --------------------------------------------------------


async def test_sitemap_lists_slugged_context_entry_permalinks_at_threshold(
    monkeypatch,
):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    entry = await _publish_entry(
        _social_url(),
        summary="Sitemap presence check.",
        title="Sitemap Presence Headline",
    )
    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    assert (
        f"<loc>https://redtaperecordings.com{entry['permalink']}</loc>" in response.text
    )


async def test_sitemap_omits_context_entries_below_threshold(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 1_000_000)
    entry = await _publish_entry(
        _social_url(),
        summary="Sitemap absence check.",
        title="Sitemap Absence Headline",
    )
    response = client.get("/sitemap.xml")
    assert response.status_code == 200
    assert (
        f"<loc>https://redtaperecordings.com{entry['permalink']}</loc>"
        not in response.text
    )


# --- transcript excerpt (WO-946) --------------------------------------------

_EXCERPT_PAGE_SEGMENTS = [
    {
        "start": 0.0,
        "end": 10.0,
        "text": "Good morning, let's call this meeting to order.",
    },
    {
        "start": 10.0,
        "end": 40.0,
        "text": "First item on the agenda is the budget discussion.",
    },
    {
        "start": 40.0,
        "end": 70.0,
        "text": "We have a motion to approve the zoning changes.",
    },
]


async def test_context_entry_page_renders_a_transcript_excerpt(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    slug = await _make_page_with_segments(
        f"ctx-excerpt-render-{uuid.uuid4().hex[:8]}", _EXCERPT_PAGE_SEGMENTS
    )
    page = await crud.get_page_by_slug(slug)
    result = await crud.save_context_entry(
        "user_context_pages_test",
        social=parse_social_url(_social_url()),
        summary="Excerpt render check.",
        title="Excerpt render headline",
        meeting_page_id=page["id"],
        t_seconds=10,
        match_kind="exact",
        status="published",
    )
    entry = result["ok"]
    response = client.get(entry["permalink"])
    assert response.status_code == 200
    assert "What was said at this moment" in response.text
    assert _EXCERPT_PAGE_SEGMENTS[1]["text"] in response.text
    # Jinja autoescape turns "&" into "&amp;" inside the href attribute.
    assert f"/m/{slug}?t=10&amp;line=seg-1&amp;version=" in response.text
    assert "Keep reading in the full transcript" in response.text


async def test_context_entry_page_excerpt_heading_matches_match_kind(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    slug = await _make_page_with_segments(
        f"ctx-excerpt-approx-{uuid.uuid4().hex[:8]}", _EXCERPT_PAGE_SEGMENTS
    )
    page = await crud.get_page_by_slug(slug)
    result = await crud.save_context_entry(
        "user_context_pages_test",
        social=parse_social_url(_social_url()),
        summary="Approximate match excerpt heading check.",
        title="Approximate excerpt headline",
        meeting_page_id=page["id"],
        t_seconds=10,
        match_kind="approximate",
        status="published",
    )
    entry = result["ok"]
    response = client.get(entry["permalink"])
    assert response.status_code == 200
    assert "Around this moment in the meeting" in response.text


async def test_context_entry_page_excerpt_text_is_escaped(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    evil_segments = [
        {
            "start": 0.0,
            "end": 10.0,
            "text": "Innocent text <script>alert(1)</script> more.",
        },
        {
            "start": 10.0,
            "end": 40.0,
            "text": "Second line to satisfy the 2-segment floor.",
        },
    ]
    slug = await _make_page_with_segments(
        f"ctx-excerpt-xss-{uuid.uuid4().hex[:8]}", evil_segments
    )
    page = await crud.get_page_by_slug(slug)
    result = await crud.save_context_entry(
        "user_context_pages_test",
        social=parse_social_url(_social_url()),
        summary="XSS excerpt check.",
        title="XSS excerpt headline",
        meeting_page_id=page["id"],
        t_seconds=0,
        match_kind="exact",
        status="published",
    )
    entry = result["ok"]
    response = client.get(entry["permalink"])
    assert response.status_code == 200
    assert "<script>alert(1)</script>" not in response.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in response.text


async def test_context_entry_page_no_excerpt_without_t_seconds(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    slug = await _make_page_with_segments(
        f"ctx-excerpt-no-t-{uuid.uuid4().hex[:8]}", _EXCERPT_PAGE_SEGMENTS
    )
    page = await crud.get_page_by_slug(slug)
    result = await crud.save_context_entry(
        "user_context_pages_test",
        social=parse_social_url(_social_url()),
        summary="No t_seconds at all.",
        title="No t seconds headline",
        meeting_page_id=page["id"],
        match_kind="related",
        status="published",
    )
    entry = result["ok"]
    assert entry["t_seconds"] is None
    response = client.get(entry["permalink"])
    assert response.status_code == 200
    assert "context-excerpt" not in response.text


async def test_context_entry_page_no_excerpt_without_segments(monkeypatch):
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    entry = await _publish_entry(
        _social_url(), summary="No segments at all.", title="No segments headline"
    )
    response = client.get(entry["permalink"])
    assert response.status_code == 200
    assert "context-excerpt" not in response.text


async def test_context_entry_page_no_excerpt_with_a_quality_marker_warning(
    monkeypatch,
):
    from archive.db.crud import _GARBLED_MARKER

    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    slug = await _make_page_with_segments(
        f"ctx-excerpt-garbled-{uuid.uuid4().hex[:8]}",
        _EXCERPT_PAGE_SEGMENTS,
        transcript_warnings=[f"This transcript {_GARBLED_MARKER}."],
    )
    page = await crud.get_page_by_slug(slug)
    result = await crud.save_context_entry(
        "user_context_pages_test",
        social=parse_social_url(_social_url()),
        summary="Garbled transcript excerpt check.",
        title="Garbled excerpt headline",
        meeting_page_id=page["id"],
        t_seconds=10,
        match_kind="exact",
        status="published",
    )
    entry = result["ok"]
    response = client.get(entry["permalink"])
    assert response.status_code == 200
    assert "context-excerpt" not in response.text


async def test_context_feed_never_loads_transcript_excerpts(monkeypatch):
    # The feed must never pay for a segments-JSON read -- see
    # get_context_transcript_excerpt()'s own docstring on why (six-figure
    # bytes per meeting, times 20 entries on a page). Monkeypatched to
    # raise so this fails loudly if the feed route is ever changed to
    # call it.
    async def _must_not_be_called(*args, **kwargs):
        raise AssertionError("the feed must never load a transcript excerpt")

    monkeypatch.setattr(crud, "get_context_transcript_excerpt", _must_not_be_called)
    monkeypatch.setattr(crud, "CONTEXT_MIN_INDEXABLE", 0)
    await _publish_entry(
        _yt_url(), summary="Feed must never load excerpts.", title="Feed excerpt guard"
    )
    response = client.get("/context")
    assert response.status_code == 200
