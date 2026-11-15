"""Page visits on the Render address move to the public domain (2026-11-15).

Traffic on rtr-deeplink.onrender.com skipped Cloudflare entirely. The
middleware 301s GET/HEAD page loads there to PUBLIC_BASE_URL, and leaves
/api/* and /admin/* (health checks, webhooks, GitHub Actions) alone.
"""

import pytest
from fastapi.testclient import TestClient

import app.main

RENDER = "https://rtr-deeplink.onrender.com"
PUBLIC = "https://redtaperecordings.com"


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", PUBLIC)
    return TestClient(app.main.app, follow_redirects=False)


def test_page_on_render_host_redirects_with_path_and_query(client):
    r = client.get(f"{RENDER}/meetings?q=budget&page=2")
    assert r.status_code == 301
    assert r.headers["location"] == f"{PUBLIC}/meetings?q=budget&page=2"


def test_head_on_render_host_redirects(client):
    r = client.head(f"{RENDER}/about")
    assert r.status_code == 301
    assert r.headers["location"] == f"{PUBLIC}/about"


@pytest.mark.parametrize("path", ["/api/health", "/admin/version"])
def test_api_and_admin_stay_on_render_host(client, path):
    r = client.get(f"{RENDER}{path}")
    assert r.status_code != 301


def test_post_on_render_host_is_not_redirected(client):
    r = client.post(f"{RENDER}/api/log-invalid-query", json={})
    assert r.status_code != 301


def test_public_host_is_untouched(client):
    r = client.get(f"{PUBLIC}/robots.txt")
    assert r.status_code == 200


def test_no_redirect_without_public_base_url(monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    c = TestClient(app.main.app, follow_redirects=False)
    assert c.get(f"{RENDER}/robots.txt").status_code == 200


def test_no_redirect_loop_when_public_base_url_is_render(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", RENDER)
    c = TestClient(app.main.app, follow_redirects=False)
    assert c.get(f"{RENDER}/robots.txt").status_code == 200


# --- Origin lock: the public domain must arrive through Cloudflare ---


@pytest.fixture
def locked(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", PUBLIC)
    monkeypatch.setenv("ORIGIN_SHARED_SECRET", "s3cret")
    monkeypatch.setenv("ORIGIN_LOCK_MODE", "enforce")
    return TestClient(app.main.app, follow_redirects=False)


def test_public_host_without_header_is_refused(locked):
    assert locked.get(f"{PUBLIC}/robots.txt").status_code == 403


def test_public_host_with_wrong_header_is_refused(locked):
    r = locked.get(f"{PUBLIC}/robots.txt", headers={"X-Origin-Auth": "nope"})
    assert r.status_code == 403


def test_public_host_with_header_is_served(locked):
    r = locked.get(f"{PUBLIC}/robots.txt", headers={"X-Origin-Auth": "s3cret"})
    assert r.status_code == 200


def test_health_check_needs_no_header(locked):
    assert locked.get(f"{PUBLIC}/api/health").status_code != 403


def test_render_host_admin_and_api_need_no_header(locked):
    assert locked.get(f"{RENDER}/admin/version").status_code != 403
    assert locked.get(f"{RENDER}/api/health").status_code != 403


def test_render_host_pages_still_redirect_when_locked(locked):
    r = locked.get(f"{RENDER}/about")
    assert r.status_code == 301
    assert r.headers["location"] == f"{PUBLIC}/about"


def test_no_lock_without_secret(client):
    assert client.get(f"{PUBLIC}/robots.txt").status_code == 200


def test_stray_whitespace_on_either_side_still_matches(monkeypatch, locked):
    monkeypatch.setenv("ORIGIN_SHARED_SECRET", "s3cret\n")
    r = locked.get(f"{PUBLIC}/robots.txt", headers={"X-Origin-Auth": " s3cret "})
    assert r.status_code == 200


@pytest.fixture
def check_only(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", PUBLIC)
    monkeypatch.setenv("ORIGIN_SHARED_SECRET", "s3cret")
    monkeypatch.delenv("ORIGIN_LOCK_MODE", raising=False)
    monkeypatch.setenv("ADMIN_STATS_TOKEN", "admintok")
    for key in list(app.main._origin_lock_counts):
        monkeypatch.setitem(app.main._origin_lock_counts, key, 0)
    return TestClient(app.main.app, follow_redirects=False)


def test_check_only_mode_serves_and_counts(check_only):
    assert check_only.get(f"{PUBLIC}/robots.txt").status_code == 200
    r = check_only.get(f"{PUBLIC}/robots.txt", headers={"X-Origin-Auth": "nope"})
    assert r.status_code == 200
    r = check_only.get(f"{PUBLIC}/robots.txt", headers={"X-Origin-Auth": "s3cret"})
    assert r.status_code == 200
    report = check_only.get(
        f"{RENDER}/admin/origin-lock-check",
        headers={"Authorization": "Bearer admintok"},
    ).json()
    assert report["mode"] == "check-only"
    assert report["secret_set"] is True
    assert report["counts"] == {
        "match": 1,
        "missing": 1,
        "mismatch": 1,
        "last_mismatch_length": 4,
    }
    assert "s3cret" not in str(report)


def test_lock_check_needs_admin_token(check_only):
    assert check_only.get(f"{RENDER}/admin/origin-lock-check").status_code == 404


def test_request_headers_reports_names_and_only_safe_values(check_only):
    r = check_only.get(
        f"{PUBLIC}/admin/request-headers",
        headers={
            "Authorization": "Bearer admintok",
            "CDN-Loop": "cloudflare; loops=1, cloudflare; loops=1",
            "X-Forwarded-For": "203.0.113.5, 198.51.100.7",
            "X-Origin-Auth": "s3cret",
            "Cookie": "session=abc",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["host"] == "redtaperecordings.com"
    assert {"cdn-loop", "cookie", "x-origin-auth", "authorization"} <= set(
        body["header_names"]
    )
    assert body["values"] == {"cdn-loop": ["cloudflare; loops=1, cloudflare; loops=1"]}
    assert body["x_forwarded_for_hops"] == 2
    text = r.text
    for secret in ("admintok", "s3cret", "session=abc", "203.0.113.5"):
        assert secret not in text


def test_request_headers_needs_admin_token(check_only):
    assert check_only.get(f"{RENDER}/admin/request-headers").status_code == 404
