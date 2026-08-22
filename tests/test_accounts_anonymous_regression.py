"""Direct tests of this feature's core guarantee (see the plan's own
"Non-goal: nothing existing gets gated behind login" section): an
anonymous visitor with no Clerk session sees every existing element
unchanged, and the resolver's proxy only forwards the Cookie header on
the specific routes that need it for Clerk verification.
"""

from fastapi.testclient import TestClient

import app.main
import archive.main
from archive.db import crud

resolver_client = TestClient(app.main.app)
archive_client_ = TestClient(archive.main.app)


def _payload(external_id: str, source_url: str) -> dict:
    return {
        "platform": "granicus",
        "source_url": source_url,
        "external_id": external_id,
        "title": "Anonymous Regression Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "City of Test",
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


async def test_meeting_page_anonymous_has_no_save_button_and_renders_normally(
    monkeypatch,
):
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_fake_for_this_test")
    slug = await _make_page("anon-regress-1")

    response = archive_client_.get(f"/m/{slug}")
    assert response.status_code == 200
    assert "Anonymous Regression Test Meeting" in response.text
    assert "Report a problem with this meeting" in response.text
    assert 'id="saveMeetingBtn"' not in response.text


def test_meetings_index_anonymous_has_no_save_search_button(monkeypatch):
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_fake_for_this_test")
    response = archive_client_.get("/meetings")
    assert response.status_code == 200
    assert 'id="saveSearchBtn"' not in response.text
    # The rest of the page is unaffected -- search box/filters still there.
    assert "Search title, jurisdiction" in response.text


def test_saved_items_page_anonymous_shows_sign_in_prompt_not_an_error(monkeypatch):
    monkeypatch.setenv("CLERK_SECRET_KEY", "sk_test_fake_for_this_test")
    response = archive_client_.get("/account/saved")
    assert response.status_code == 200
    assert "Sign in to save meetings" in response.text


def test_nav_has_no_clerk_elements_when_unconfigured(monkeypatch):
    # CLERK_PUBLISHABLE_KEY is read into templates.env.globals once at
    # import time (same pattern as GA_MEASUREMENT_ID) -- monkeypatching
    # the env var has no effect on an already-running process, so this
    # patches the Jinja global directly instead, matching how a real
    # deploy with no key configured behaves. Confirms the resolver's own
    # base.html gates the whole nav block, not just the save buttons.
    monkeypatch.setitem(app.main.templates.env.globals, "CLERK_PUBLISHABLE_KEY", "")
    response = resolver_client.get("/")
    assert response.status_code == 200
    assert "My Saved Items" not in response.text
    assert 'id="clerk-sign-in-link"' not in response.text


def test_nav_shows_signed_in_state_immediately_when_active_account_present(monkeypatch):
    # Real bug fixed 2026-08-11, reported by the user against
    # /account/saved: the nav used to always server-render "Sign in"
    # regardless of a real server-side session, flashing it on every full
    # page load before shared_static/clerk_nav.js corrected it client-side.
    # active_account is already computed by every route base.html's nav
    # now reads it from -- confirms the *initial* HTML picks the right
    # state without needing any client-side JS to run first.
    monkeypatch.setattr(
        archive.main, "get_clerk_user_id", lambda request: "user_test_nav"
    )
    response = archive_client_.get("/account/saved")
    assert response.status_code == 200
    assert (
        '<a class="nav-link" href="#" id="clerk-sign-in-link" hidden>Sign in</a>'
        in response.text
    )
    assert '<span id="clerk-user-button"></span>' in response.text
    # Real bug fixed 2026-08-11, reported right after the above: Get
    # Updates had the exact same flash (a signed-in visitor briefly saw a
    # newsletter-signup link they already don't need), just less
    # noticeable until the Sign in flash stopped competing with it.
    assert 'id="nav-get-updates" hidden' in response.text
    assert (
        'id="nav-get-updates-divider" style="display: none !important;"'
        in response.text
    )


def test_nav_shows_signed_out_state_when_no_active_account(monkeypatch):
    monkeypatch.setattr(archive.main, "get_clerk_user_id", lambda request: None)
    response = archive_client_.get("/account/saved")
    assert response.status_code == 200
    assert (
        '<a class="nav-link" href="#" id="clerk-sign-in-link">Sign in</a>'
        in response.text
    )
    assert '<span id="clerk-user-button" hidden></span>' in response.text
    assert 'id="nav-get-updates">' in response.text
    assert 'id="nav-get-updates-divider">' in response.text


def test_proxy_forwards_cookie_only_to_auth_aware_routes(monkeypatch):
    """The resolver's reverse proxy must pass the visitor's Cookie header
    through to Archive on /meetings and /m/{slug} (so Archive can verify
    the Clerk session with one local check, per this feature's whole
    architecture) but NOT on static-asset/sitemap/feed routes, which
    never need it."""
    captured = []

    async def _fake_proxy_get(
        path, query_string, cookie_header=None, extra_headers=None
    ):
        captured.append((path, cookie_header))

        class _FakeResponse:
            status = 200
            headers = {}
            content = _EmptyAsyncIter()

        class _FakeSession:
            async def close(self):
                pass

        return _FakeSession(), _FakeResponse()

    monkeypatch.setattr(app.main.archive_client, "proxy_get", _fake_proxy_get)

    resolver_client.get("/meetings", headers={"Cookie": "__session=abc123"})
    resolver_client.get("/m/some-slug", headers={"Cookie": "__session=abc123"})
    resolver_client.get(
        "/archive-static/style.css", headers={"Cookie": "__session=abc123"}
    )

    by_path = {path.split("/")[0]: cookie for path, cookie in captured}
    assert by_path["meetings"] == "__session=abc123"
    assert captured[1][1] == "__session=abc123"  # the m/{slug} call
    assert by_path["static"] is None


class _EmptyAsyncIter:
    async def iter_chunked(self, n):
        return
        yield  # pragma: no cover -- makes this an async generator
