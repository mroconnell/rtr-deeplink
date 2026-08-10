"""Tests for the branded 404 page + broken-inbound-link logging added
2026-08-10 to both services -- previously an unmatched route just got
FastAPI's default plain-JSON 404, with no signal anywhere that it happened.
"""

import logging

from fastapi.testclient import TestClient

import app.main
import archive.main

resolver_client = TestClient(app.main.app)
archive_client_ = TestClient(archive.main.app)


def test_resolver_unmatched_route_renders_branded_page():
    response = resolver_client.get("/this-page-does-not-exist")
    assert response.status_code == 404
    assert "Page not found" in response.text


def test_resolver_unmatched_route_logs_a_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="rtr_deeplink.db"):
        resolver_client.get("/this-page-does-not-exist", headers={"referer": "https://example.com/old-link"})
    assert any("404" in r.message and "/this-page-does-not-exist" in r.message for r in caplog.records)
    assert any("example.com/old-link" in r.message for r in caplog.records)


def test_resolver_api_404s_are_unaffected():
    # Deliberate JSONResponse 404s (not raised exceptions) never hit the
    # new handler -- confirms it doesn't accidentally reshape existing API
    # error bodies into the branded HTML page. /admin/stats without a valid
    # token is a real, network-free example of this pattern.
    response = resolver_client.get("/admin/stats")
    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")


def test_archive_unmatched_route_renders_branded_page():
    response = archive_client_.get("/this-page-does-not-exist")
    assert response.status_code == 404
    assert "Page not found" in response.text


def test_archive_unknown_slug_still_renders_not_found_and_now_logs(caplog):
    with caplog.at_level(logging.WARNING, logger="rtr_archive"):
        response = archive_client_.get("/m/no-such-meeting-slug-at-all")
    assert response.status_code == 404
    assert "Page not found" in response.text
    assert any("no-such-meeting-slug-at-all" in r.message for r in caplog.records)
