"""Tests for admin route auth (`_admin_token_ok`) -- `Authorization: Bearer`
only. The legacy `?token=` query-param fallback (WO-8) was removed
2026-08-24: both cron workflows (daily-report.yml, send-search-alerts.yml)
had run green on header auth for a week straight (8/8 consecutive
successes each, confirmed via `gh run list`), so its one reason to exist
-- not breaking anything still calling the old way -- no longer applied.
A token in the URL leaked into Render's request logs on every call, which
the header form doesn't. /admin/stats is used here as the representative
route, matching how tests/test_404_handling.py already treats it as a
network-free example of the shared _admin_token_ok gating every
/admin/* route uses.
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


def test_admin_stats_no_longer_accepts_legacy_query_param():
    # The whole point of removing the fallback: a correct token in the
    # query string alone must no longer authenticate.
    response = resolver_client.get("/admin/stats", params={"token": "test-admin-token"})
    assert response.status_code == 404


def test_malformed_authorization_header_is_rejected_even_with_query_param():
    # A header present but not shaped like "Bearer <token>" is a hard
    # rejection now -- there's no query-param fallback left to fall
    # through to.
    response = resolver_client.get(
        "/admin/stats",
        params={"token": "test-admin-token"},
        headers={"Authorization": "test-admin-token"},
    )
    assert response.status_code == 404
