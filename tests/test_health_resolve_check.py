"""Tests for GET /api/health/resolve-check (WO-7) -- an external uptime
monitor's target, distinct from /api/health: this proves the resolve
pipeline itself (routing, adapter dispatch, DB read) completes a request,
not just that the DB is reachable. Mocks the cache lookup and the
adapter's resolve(), same pattern as tests/test_recheck_archived_page.py.
"""

from fastapi.testclient import TestClient

import app.main

client = TestClient(app.main.app)


class _FakeFinder:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error

    async def resolve(self, url):
        if self._error:
            raise self._error
        return self._result


class _FakeResolvedMeeting:
    def __init__(self, **fields):
        self._fields = fields

    def model_dump(self):
        return self._fields


def test_not_configured_when_env_var_unset(monkeypatch):
    monkeypatch.delenv("UPTIME_CHECK_URL", raising=False)

    response = client.get("/api/health/resolve-check")

    assert response.status_code == 200
    assert response.json()["status"] == "not_configured"


def test_ok_on_cache_hit_with_real_content(monkeypatch):
    monkeypatch.setenv("UPTIME_CHECK_URL", "https://example.new.swagit.com/videos/1")

    async def fake_get_cached_resolution(normalized):
        return {"resolution_id": 1, "payload": {"segments": [{"start": 0, "end": 1, "text": "hi"}]}}

    monkeypatch.setattr(app.main.crud, "get_cached_resolution", fake_get_cached_resolution)

    response = client.get("/api/health/resolve-check")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_503_on_cache_hit_with_no_content(monkeypatch):
    monkeypatch.setenv("UPTIME_CHECK_URL", "https://example.new.swagit.com/videos/1")

    async def fake_get_cached_resolution(normalized):
        return {"resolution_id": 1, "payload": {"segments": [], "agenda_items": [], "video_url": None, "agenda_link": None}}

    monkeypatch.setattr(app.main.crud, "get_cached_resolution", fake_get_cached_resolution)

    response = client.get("/api/health/resolve-check")

    assert response.status_code == 503
    assert response.json()["status"] == "error"


def test_ok_on_cache_miss_with_successful_live_resolve(monkeypatch):
    monkeypatch.setenv("UPTIME_CHECK_URL", "https://example.new.swagit.com/videos/1")

    async def fake_get_cached_resolution(normalized):
        return None

    monkeypatch.setattr(app.main.crud, "get_cached_resolution", fake_get_cached_resolution)
    monkeypatch.setattr(
        "app.main.get_finder",
        lambda platform: _FakeFinder(result=_FakeResolvedMeeting(segments=[{"start": 0, "end": 1, "text": "hi"}])),
    )

    response = client.get("/api/health/resolve-check")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_503_on_cache_miss_with_resolve_exception(monkeypatch):
    monkeypatch.setenv("UPTIME_CHECK_URL", "https://example.new.swagit.com/videos/1")

    async def fake_get_cached_resolution(normalized):
        return None

    monkeypatch.setattr(app.main.crud, "get_cached_resolution", fake_get_cached_resolution)
    monkeypatch.setattr("app.main.get_finder", lambda platform: _FakeFinder(error=RuntimeError("boom")))

    response = client.get("/api/health/resolve-check")

    assert response.status_code == 503
    assert response.json()["status"] == "error"
