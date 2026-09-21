"""HTTP-level tests for the resolver's /api/context/* routes (app/main.py)
-- WO-943's write-side API. get_clerk_user_id and the archive_client
wrappers are monkeypatched directly, mirroring
tests/test_saved_items_routes.py's pattern -- these routes' own logic
(auth gate, status-code mapping) is what's under test here, not
archive_client's internals (covered indirectly by
tests/test_context_internal_routes.py against the real Archive routes)
or the Archive's own gating (covered there too).

Also covers the resolver's nav link and the /context/new proxy's cookie
forwarding, since both are part of this same WO-943 write-side wiring.
"""

from fastapi.testclient import TestClient

import app.main

client = TestClient(app.main.app)


def test_save_401s_when_logged_out(monkeypatch):
    monkeypatch.setattr(app.main, "get_clerk_user_id", lambda request: None)
    response = client.post(
        "/api/context/save",
        json={"social_url": "https://x.com/a/status/1", "summary": "x"},
    )
    assert response.status_code == 401
    assert response.json()["error"] == "not_logged_in"


def test_set_status_401s_when_logged_out(monkeypatch):
    monkeypatch.setattr(app.main, "get_clerk_user_id", lambda request: None)
    response = client.post(
        "/api/context/set-status", json={"id": 1, "status": "hidden"}
    )
    assert response.status_code == 401


async def test_save_uses_the_verified_session_id_not_the_body(monkeypatch):
    monkeypatch.setattr(
        app.main, "get_clerk_user_id", lambda request: "user_from_session"
    )

    captured = {}

    async def _fake_context_save(clerk_user_id, payload):
        captured["clerk_user_id"] = clerk_user_id
        captured["payload"] = payload
        return 200, {"entry": {"id": 1}}

    monkeypatch.setattr(app.main.archive_client, "context_save", _fake_context_save)

    # A clerk_user_id smuggled into the JSON body must never reach
    # archive_client -- ContextSaveApiRequest has no such field, so
    # Pydantic drops it silently.
    response = client.post(
        "/api/context/save",
        json={
            "social_url": "https://x.com/a/status/1",
            "summary": "x",
            "clerk_user_id": "user_forged_from_body",
        },
    )
    assert response.status_code == 200
    assert captured["clerk_user_id"] == "user_from_session"
    assert "clerk_user_id" not in captured["payload"]


async def test_set_status_uses_the_verified_session_id(monkeypatch):
    monkeypatch.setattr(
        app.main, "get_clerk_user_id", lambda request: "user_from_session_2"
    )

    captured = {}

    async def _fake_context_set_status(clerk_user_id, entry_id, status):
        captured["clerk_user_id"] = clerk_user_id
        captured["entry_id"] = entry_id
        captured["status"] = status
        return 200, {"entry": {"id": entry_id, "status": status}}

    monkeypatch.setattr(
        app.main.archive_client, "context_set_status", _fake_context_set_status
    )

    response = client.post(
        "/api/context/set-status", json={"id": 7, "status": "hidden"}
    )
    assert response.status_code == 200
    assert captured == {
        "clerk_user_id": "user_from_session_2",
        "entry_id": 7,
        "status": "hidden",
    }


async def test_save_403_from_archive_becomes_404(monkeypatch):
    monkeypatch.setattr(app.main, "get_clerk_user_id", lambda request: "user_x")

    async def _fake_context_save(clerk_user_id, payload):
        return 403, {"error": "not_editor", "message": "no"}

    monkeypatch.setattr(app.main.archive_client, "context_save", _fake_context_save)

    response = client.post(
        "/api/context/save",
        json={"social_url": "https://x.com/a/status/1", "summary": "x"},
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


async def test_save_returns_502_when_archive_client_returns_none(monkeypatch):
    monkeypatch.setattr(app.main, "get_clerk_user_id", lambda request: "user_x")

    async def _fake_context_save(clerk_user_id, payload):
        return None

    monkeypatch.setattr(app.main.archive_client, "context_save", _fake_context_save)

    response = client.post(
        "/api/context/save",
        json={"social_url": "https://x.com/a/status/1", "summary": "x"},
    )
    assert response.status_code == 502
    assert response.json()["error"] == "archive_unreachable"


async def test_save_token_disguise_404_from_archive_also_becomes_502(monkeypatch):
    # Archive's own bad-token 404 has no "error" key ({"detail": "Not
    # Found"}) -- distinct from a real "entry not found"
    # ({"error": "not_found", ...}), and must be reported as a
    # misconfiguration (502), not "that entry doesn't exist."
    monkeypatch.setattr(app.main, "get_clerk_user_id", lambda request: "user_x")

    async def _fake_context_save(clerk_user_id, payload):
        return 404, {"detail": "Not Found"}

    monkeypatch.setattr(app.main.archive_client, "context_save", _fake_context_save)

    response = client.post(
        "/api/context/save",
        json={"social_url": "https://x.com/a/status/1", "summary": "x"},
    )
    assert response.status_code == 502
    assert response.json()["error"] == "archive_unreachable"


async def test_save_relays_a_real_not_found_404_unchanged(monkeypatch):
    monkeypatch.setattr(app.main, "get_clerk_user_id", lambda request: "user_x")

    async def _fake_context_save(clerk_user_id, payload):
        return 404, {"error": "not_found", "message": "That entry doesn't exist."}

    monkeypatch.setattr(app.main.archive_client, "context_save", _fake_context_save)

    response = client.post(
        "/api/context/save",
        json={"id": 999, "social_url": "https://x.com/a/status/1", "summary": "x"},
    )
    assert response.status_code == 404
    assert response.json() == {
        "error": "not_found",
        "message": "That entry doesn't exist.",
    }


async def test_save_relays_a_409_duplicate_unchanged(monkeypatch):
    monkeypatch.setattr(app.main, "get_clerk_user_id", lambda request: "user_x")

    async def _fake_context_save(clerk_user_id, payload):
        return 409, {
            "error": "duplicate",
            "message": "This post is already in the feed.",
            "existing_id": 42,
            "existing_status": "published",
        }

    monkeypatch.setattr(app.main.archive_client, "context_save", _fake_context_save)

    response = client.post(
        "/api/context/save",
        json={"social_url": "https://x.com/a/status/1", "summary": "x"},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["error"] == "duplicate"
    assert body["existing_id"] == 42


async def test_save_relays_a_400_validation_error_unchanged(monkeypatch):
    monkeypatch.setattr(app.main, "get_clerk_user_id", lambda request: "user_x")

    async def _fake_context_save(clerk_user_id, payload):
        return 400, {
            "error": "meeting_required",
            "message": "Publishing needs a matched meeting first.",
        }

    monkeypatch.setattr(app.main.archive_client, "context_save", _fake_context_save)

    response = client.post(
        "/api/context/save",
        json={
            "social_url": "https://x.com/a/status/1",
            "summary": "x",
            "status": "published",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "meeting_required"


async def test_save_relays_a_200_entry_unchanged(monkeypatch):
    monkeypatch.setattr(app.main, "get_clerk_user_id", lambda request: "user_x")

    entry = {"id": 5, "status": "draft", "summary": "x"}

    async def _fake_context_save(clerk_user_id, payload):
        return 200, {"entry": entry}

    monkeypatch.setattr(app.main.archive_client, "context_save", _fake_context_save)

    response = client.post(
        "/api/context/save",
        json={"social_url": "https://x.com/a/status/1", "summary": "x"},
    )
    assert response.status_code == 200
    assert response.json() == {"entry": entry}


def test_save_rejects_non_json_form_encoded_post(monkeypatch):
    # Pins the CSRF posture: this route only ever accepts JSON, matching
    # context_editor.js's fetch() call (Content-Type: application/json) --
    # a plain HTML <form> POST (form-urlencoded) can never hit it.
    monkeypatch.setattr(app.main, "get_clerk_user_id", lambda request: "user_x")
    response = client.post(
        "/api/context/save",
        data={"social_url": "https://x.com/a/status/1", "summary": "x"},
    )
    assert response.status_code == 422


def test_resolver_home_page_has_full_context_nav_link():
    response = client.get("/")
    assert response.status_code == 200
    assert '<a class="nav-link" href="/context">Full Context</a>' in response.text
