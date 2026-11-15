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
