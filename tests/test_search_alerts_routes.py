"""HTTP-level tests for the saved-search alert feature's routes
(archive/main.py): the token-gated internal sweep trigger and the public
per-alert unsubscribe link. Mirrors tests/test_account_internal_routes.py's
gating pattern; sweep logic itself is covered separately in
tests/test_search_alerts_matching.py (crud) and
tests/test_search_alerts_run.py (archive/search_alerts.py, mocked
Clerk/Resend).
"""

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud
from archive.utils import link_tokens

client = TestClient(archive.main.app)


def test_send_search_alerts_404s_with_no_token():
    response = client.post("/internal/account/send-search-alerts")
    assert response.status_code == 404


def test_send_search_alerts_404s_with_wrong_token():
    response = client.post(
        "/internal/account/send-search-alerts",
        headers={"Authorization": "Bearer not-the-real-token"},
    )
    assert response.status_code == 404


def test_send_search_alerts_dry_run_works_with_valid_token():
    response = client.post(
        "/internal/account/send-search-alerts",
        params={"dry_run": "true"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    body = response.json()
    assert "saved_searches_checked" in body
    assert "users_emailed" in body


async def test_unsubscribe_route_deletes_saved_search_with_valid_token(monkeypatch):
    monkeypatch.setenv("ALERT_UNSUBSCRIBE_SECRET", "test-alert-secret")
    item = await crud.save_search("user_unsub_route_2", {"q": "delete-me-via-route-2"})
    token = link_tokens.sign_saved_item_id(item["id"])

    response = client.get("/alerts/unsubscribe", params={"token": token})
    assert response.status_code == 200
    assert "unsubscribed" in response.text.lower()

    removed_again = await crud.unsave_item_by_id(item["id"])
    assert removed_again is False  # already gone


async def test_unsubscribe_route_with_tampered_token_deletes_nothing(monkeypatch):
    monkeypatch.setenv("ALERT_UNSUBSCRIBE_SECRET", "test-alert-secret")
    item = await crud.save_search(
        "user_unsub_route_3", {"q": "should-survive-tampering"}
    )
    token = link_tokens.sign_saved_item_id(item["id"])
    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")

    response = client.get("/alerts/unsubscribe", params={"token": tampered})
    assert response.status_code == 200
    assert "went wrong" in response.text.lower()

    removed = await crud.unsave_item_by_id(item["id"])
    assert removed is True  # still there, this cleans it up


async def test_unsubscribe_route_with_missing_token_shows_error_state():
    response = client.get("/alerts/unsubscribe")
    assert response.status_code == 200
    assert "went wrong" in response.text.lower()
