"""HTTP-level tests for GET /api/health on both services (WO-6). Render
gates deploys on this endpoint (render.yaml); before this fix both
handlers returned a static {"status": "ok"} regardless of DB state -- the
2026-08-09 incident had the app failing every query on a missing column
while this would still have reported healthy. See AUDIT_EXECUTION_BRIEF.md.
"""

from fastapi.testclient import TestClient

import app.db.engine
import app.main
import archive.db.engine
import archive.main

app_client = TestClient(app.main.app)
archive_client_ = TestClient(archive.main.app)


def test_app_health_ok_when_db_reachable():
    response = app_client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


class _BrokenEngine:
    """AsyncEngine.connect is a read-only attribute, so a broken DB can't
    be simulated by monkeypatching a method onto the real engine -- swap
    the whole module-level `engine` object instead. The health handler
    re-imports `engine` from `.db.engine` on every call, so it picks up
    whatever this module attribute currently points to."""

    def connect(self, *args, **kwargs):
        raise RuntimeError("db down")


def test_app_health_returns_503_when_db_unreachable(monkeypatch):
    monkeypatch.setattr(app.db.engine, "engine", _BrokenEngine())

    response = app_client.get("/api/health")
    assert response.status_code == 503
    assert response.json()["status"] == "error"


def test_archive_health_ok_when_db_reachable():
    response = archive_client_.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # media_tools (WO-28) reports whether ffmpeg/ffprobe are really on
    # PATH *in this service* -- the Archive shells out to ffmpeg for
    # meeting-card frames now, and nothing previously confirmed either
    # binary was present here (render.yaml's confirmed-live check covers
    # the resolver; worker/Dockerfile installs it explicitly for the
    # worker). Both keys are always present; either value may legitimately
    # be None, including on a dev machine without ffmpeg -- a missing
    # binary must never fail this endpoint, since Render gates deploys on
    # it and a service that merely can't make new thumbnails is healthy.
    assert set(body["media_tools"]) == {"ffmpeg", "ffprobe"}


def test_archive_health_returns_503_when_db_unreachable(monkeypatch):
    monkeypatch.setattr(archive.db.engine, "engine", _BrokenEngine())

    response = archive_client_.get("/api/health")
    assert response.status_code == 503
    assert response.json()["status"] == "error"
