"""HTTP-level tests for the resolver's /api/account/* save/unsave routes
(app/main.py). get_clerk_user_id and the archive_client wrappers are
monkeypatched directly (mirroring tests/test_archive_push_tracking.py's
pattern of monkeypatching archive_client functions) rather than mocking
raw HTTP -- these routes' own logic (auth gate, response shaping) is what's
under test here, not archive_client's internals (covered by
tests/test_account_internal_routes.py / tests/test_saved_items.py against
the real Archive routes/crud).
"""

from fastapi.testclient import TestClient

import app.main

client = TestClient(app.main.app)


def test_save_meeting_401s_when_logged_out(monkeypatch):
    monkeypatch.setattr(app.main, "get_clerk_user_id", lambda request: None)
    response = client.post("/api/account/save-meeting", json={"slug": "whatever"})
    assert response.status_code == 401
    assert response.json()["error"] == "not_logged_in"


def test_unsave_meeting_401s_when_logged_out(monkeypatch):
    monkeypatch.setattr(app.main, "get_clerk_user_id", lambda request: None)
    response = client.post("/api/account/unsave-meeting", json={"slug": "whatever"})
    assert response.status_code == 401


def test_save_search_401s_when_logged_out(monkeypatch):
    monkeypatch.setattr(app.main, "get_clerk_user_id", lambda request: None)
    response = client.post("/api/account/save-search", json={"search_params": {}})
    assert response.status_code == 401


def test_unsave_search_401s_when_logged_out(monkeypatch):
    monkeypatch.setattr(app.main, "get_clerk_user_id", lambda request: None)
    response = client.post("/api/account/unsave-search", json={"saved_item_id": 1})
    assert response.status_code == 401


async def test_save_meeting_round_trips_when_logged_in(monkeypatch):
    monkeypatch.setattr(app.main, "get_clerk_user_id", lambda request: "user_test_123")

    captured = {}

    async def _fake_save_meeting(clerk_user_id, slug):
        captured["clerk_user_id"] = clerk_user_id
        captured["slug"] = slug
        return {"id": 1, "item_type": "saved_meeting", "meeting_page_id": 5}

    monkeypatch.setattr(app.main.archive_client, "save_meeting", _fake_save_meeting)

    response = client.post("/api/account/save-meeting", json={"slug": "some-real-slug"})
    assert response.status_code == 200
    assert response.json()["id"] == 1
    assert captured == {"clerk_user_id": "user_test_123", "slug": "some-real-slug"}


async def test_save_meeting_404s_when_archive_reports_unknown_slug(monkeypatch):
    monkeypatch.setattr(app.main, "get_clerk_user_id", lambda request: "user_test_123")

    async def _fake_save_meeting(clerk_user_id, slug):
        return None

    monkeypatch.setattr(app.main.archive_client, "save_meeting", _fake_save_meeting)

    response = client.post("/api/account/save-meeting", json={"slug": "no-such-slug"})
    assert response.status_code == 404


async def test_save_search_round_trips_when_logged_in(monkeypatch):
    monkeypatch.setattr(app.main, "get_clerk_user_id", lambda request: "user_test_456")

    captured = {}

    async def _fake_save_search(clerk_user_id, search_params):
        captured["clerk_user_id"] = clerk_user_id
        captured["search_params"] = search_params
        return {"id": 2, "item_type": "saved_search", "search_params": search_params}

    monkeypatch.setattr(app.main.archive_client, "save_search", _fake_save_search)

    response = client.post(
        "/api/account/save-search", json={"search_params": {"q": "budget"}}
    )
    assert response.status_code == 200
    assert captured == {
        "clerk_user_id": "user_test_456",
        "search_params": {"q": "budget"},
    }


async def test_unsave_search_round_trips_when_logged_in(monkeypatch):
    monkeypatch.setattr(app.main, "get_clerk_user_id", lambda request: "user_test_789")

    captured = {}

    async def _fake_unsave_search(clerk_user_id, saved_item_id):
        captured["clerk_user_id"] = clerk_user_id
        captured["saved_item_id"] = saved_item_id
        return {"removed": True}

    monkeypatch.setattr(app.main.archive_client, "unsave_search", _fake_unsave_search)

    response = client.post("/api/account/unsave-search", json={"saved_item_id": 42})
    assert response.status_code == 200
    assert response.json() == {"removed": True}
    assert captured == {"clerk_user_id": "user_test_789", "saved_item_id": 42}


async def test_save_meeting_returns_502_on_archive_failure(monkeypatch):
    monkeypatch.setattr(app.main, "get_clerk_user_id", lambda request: "user_test_err")

    async def _fake_save_search(clerk_user_id, search_params):
        return None

    monkeypatch.setattr(app.main.archive_client, "save_search", _fake_save_search)

    response = client.post(
        "/api/account/save-search", json={"search_params": {"q": "x"}}
    )
    assert response.status_code == 502
