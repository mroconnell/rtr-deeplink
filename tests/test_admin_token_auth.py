"""Tests for WO-8: admin routes now accept `Authorization: Bearer` in
addition to the legacy `?token=` query param. Render's request logs don't
mask a query param the way GitHub Actions masks its own secrets, so a
token in the URL leaked into Render's logs on every cron call -- see
AUDIT_EXECUTION_BRIEF.md's WO-8 entry. The query-param path is kept
deliberately, so this isn't a flag day for anything still calling the old
way; /admin/stats is used here as the representative route, matching how
tests/test_404_handling.py already treats it as a network-free example of
the shared _admin_token_ok gating every /admin/* route uses.
"""

from fastapi.testclient import TestClient

import app.main

resolver_client = TestClient(app.main.app)


def test_admin_stats_rejects_no_credentials():
    response = resolver_client.get("/admin/stats")
    assert response.status_code == 404


def test_admin_stats_accepts_correct_bearer_header():
    response = resolver_client.get(
        "/admin/stats", headers={"Authorization": "Bearer test-admin-token"}
    )
    assert response.status_code == 200


def test_admin_stats_rejects_wrong_bearer_header():
    response = resolver_client.get(
        "/admin/stats", headers={"Authorization": "Bearer not-the-real-token"}
    )
    assert response.status_code == 404


def test_admin_stats_still_accepts_legacy_query_param():
    # Deliberately not removed yet -- both cron workflows need to run
    # green on header auth first (see WO-8's own acceptance criteria).
    response = resolver_client.get("/admin/stats", params={"token": "test-admin-token"})
    assert response.status_code == 200


def test_admin_stats_rejects_wrong_legacy_query_param():
    response = resolver_client.get(
        "/admin/stats", params={"token": "not-the-real-token"}
    )
    assert response.status_code == 404


def test_bearer_header_takes_priority_over_query_param():
    # A correct header should authenticate even if a stale/wrong token is
    # also present in the query string.
    response = resolver_client.get(
        "/admin/stats",
        params={"token": "not-the-real-token"},
        headers={"Authorization": "Bearer test-admin-token"},
    )
    assert response.status_code == 200


def test_malformed_authorization_header_falls_back_to_query_param():
    # A header present but not shaped like "Bearer <token>" shouldn't be
    # treated as a hard rejection -- it should just fall through to
    # whatever the query param says, same as no header at all.
    response = resolver_client.get(
        "/admin/stats",
        params={"token": "test-admin-token"},
        headers={"Authorization": "test-admin-token"},
    )
    assert response.status_code == 200
