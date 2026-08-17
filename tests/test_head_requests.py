"""HTTP HEAD support, added to both services via a small per-service
`@app.middleware("http")` (app/main.py, archive/main.py) -- FastAPI/
Starlette doesn't automatically answer a bare HEAD for a GET-only route,
so before this fix every one of this app's routes 405'd on HEAD (used by
uptime checks like UptimeRobot, some crawlers, `curl -I`). The middleware
dispatches a HEAD internally as a GET and returns the real response's
status/headers with the body stripped, rather than annotating every route
individually.
"""

from fastapi.testclient import TestClient

import app.main
import archive.main

app_client = TestClient(app.main.app)
archive_client_ = TestClient(archive.main.app)


def test_resolver_head_homepage_returns_200_with_empty_body():
    get_response = app_client.get("/")
    head_response = app_client.request("HEAD", "/")

    assert head_response.status_code == 200
    assert head_response.content == b""
    # Per RFC 9110 4.2, a HEAD response carries the same headers a GET
    # would (including Content-Length) -- just no body.
    assert head_response.headers["content-length"] == str(len(get_response.content))


def test_resolver_head_api_health_returns_200_with_empty_body():
    response = app_client.request("HEAD", "/api/health")
    assert response.status_code == 200
    assert response.content == b""


def test_resolver_head_unmatched_route_still_404s_with_empty_body():
    # Confirms the internal GET-dispatch still goes through the branded
    # 404 handler (not_found_handler in app/main.py) rather than bypassing
    # it -- status/behavior stays consistent between GET and HEAD.
    response = app_client.request("HEAD", "/this-page-does-not-exist")
    assert response.status_code == 404
    assert response.content == b""


def test_archive_head_api_health_returns_200_with_empty_body():
    get_response = archive_client_.get("/api/health")
    head_response = archive_client_.request("HEAD", "/api/health")

    assert head_response.status_code == 200
    assert head_response.content == b""
    assert head_response.headers["content-length"] == str(len(get_response.content))


def test_archive_head_unmatched_route_still_404s_with_empty_body():
    response = archive_client_.request("HEAD", "/this-page-does-not-exist")
    assert response.status_code == 404
    assert response.content == b""


def test_resolver_get_still_returns_a_real_body_unaffected():
    # Regression guard: the middleware only rewrites method/strips body
    # for HEAD -- a plain GET must be completely unaffected.
    response = app_client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
