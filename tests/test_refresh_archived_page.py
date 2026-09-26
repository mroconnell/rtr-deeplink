"""Tests for POST /api/refresh-archived-page -- WO-15 (BACKLOG.md,
2026-08-16): a public, rate-limited counterpart to the token-gated
GET /admin/recheck-archive-page, so a visitor can trigger a real re-check
of an already-archived page without needing the admin token. Mocks
archive_client.lookup/_recheck_archived_page, no real network call.
"""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import app.main
from app.utils import url_guard


@pytest.fixture(autouse=True)
def _fake_public_dns(monkeypatch):
    """app.utils.url_guard's SSRF check (WO-5) resolves each hostname for
    real before a fetch, even when the fetch itself is faked. Without this, all four
    route tests failed on a machine with no DNS (the route checks the
    submitted URL's host before anything else). Same
    fixture as tests/test_generic_fallback.py: a fixed public IP for any
    hostname. Found 2026-09-26 (WO-1082) by running the suite with DNS
    blocked."""
    monkeypatch.setattr(
        url_guard, "_resolve_hostname", lambda hostname: ["93.184.216.34"]
    )


client = TestClient(app.main.app)

URL = "https://example.granicus.com/player/clip/refresh-test"


def _archived(*, updated_at=None):
    return {
        "url": "/m/refresh-test-meeting",
        "updated_at": (updated_at or datetime.now(timezone.utc)).isoformat(),
        "has_transcript": True,
    }


async def test_not_archived_returns_404(monkeypatch):
    async def _fake_lookup(normalized):
        return None

    monkeypatch.setattr(app.main.archive_client, "lookup", _fake_lookup)

    response = client.post("/api/refresh-archived-page", json={"url": URL})
    assert response.status_code == 404
    assert response.json()["error"] == "not_archived"


async def test_recently_refreshed_page_is_cooled_down(monkeypatch):
    async def _fake_lookup(normalized):
        return _archived(updated_at=datetime.now(timezone.utc) - timedelta(minutes=5))

    called = {}

    async def _fake_recheck(url, normalized, platform, **kwargs):
        called["fired"] = True
        return {"pushed": True}

    monkeypatch.setattr(app.main.archive_client, "lookup", _fake_lookup)
    monkeypatch.setattr(app.main, "_recheck_archived_page", _fake_recheck)

    response = client.post("/api/refresh-archived-page", json={"url": URL})
    assert response.status_code == 429
    assert response.json()["error"] == "cooldown"
    assert "called" not in called


async def test_stale_page_triggers_a_real_recheck(monkeypatch):
    async def _fake_lookup(normalized):
        return _archived(updated_at=datetime.now(timezone.utc) - timedelta(hours=2))

    async def _fake_recheck(url, normalized, platform, **kwargs):
        assert url == URL
        return {"pushed": True, "jurisdiction": "Example, CA"}

    monkeypatch.setattr(app.main.archive_client, "lookup", _fake_lookup)
    monkeypatch.setattr(app.main, "_recheck_archived_page", _fake_recheck)

    response = client.post("/api/refresh-archived-page", json={"url": URL})
    assert response.status_code == 200
    assert response.json()["pushed"] is True
    assert response.json()["jurisdiction"] == "Example, CA"


async def test_page_with_no_updated_at_is_never_cooled_down(monkeypatch):
    # Real edge case: an Archive too old to send updated_at at all (or a
    # lookup response missing the field) shouldn't permanently block a
    # refresh -- same "absent means proceed" reasoning /api/resolve's own
    # ARCHIVE_RECHECK_AFTER check already uses.
    async def _fake_lookup(normalized):
        return {"url": "/m/refresh-test-meeting"}

    async def _fake_recheck(url, normalized, platform, **kwargs):
        return {"pushed": False}

    monkeypatch.setattr(app.main.archive_client, "lookup", _fake_lookup)
    monkeypatch.setattr(app.main, "_recheck_archived_page", _fake_recheck)

    response = client.post("/api/refresh-archived-page", json={"url": URL})
    assert response.status_code == 200
    assert response.json()["pushed"] is False


async def test_blocked_url_is_rejected_before_any_lookup(monkeypatch):
    async def _fail_lookup(normalized):
        raise AssertionError("should never be called for a blocked URL")

    monkeypatch.setattr(app.main.archive_client, "lookup", _fail_lookup)

    response = client.post(
        "/api/refresh-archived-page", json={"url": "http://169.254.169.254/latest"}
    )
    assert response.json()["error"] == "blocked_url"
