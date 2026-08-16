"""Tests for each service's _init_sentry() (WO-7) -- no-op when SENTRY_DSN
is unset (same degrade pattern as Clerk/ARCHIVE_INGEST_TOKEN elsewhere),
real init call when it's set. Doesn't touch a real Sentry account -- just
confirms the env-var gate and that sentry_sdk.init() is called with the
right dsn when configured.
"""

import sentry_sdk

import app.main
import archive.main
import worker.main


def test_app_init_sentry_noop_when_unset(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    calls = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))

    app.main._init_sentry()

    assert calls == []


def test_app_init_sentry_calls_init_when_set(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://fake@sentry.example/1")
    calls = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))

    app.main._init_sentry()

    assert len(calls) == 1
    assert calls[0]["dsn"] == "https://fake@sentry.example/1"


def test_archive_init_sentry_noop_when_unset(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    calls = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))

    archive.main._init_sentry()

    assert calls == []


def test_worker_init_sentry_noop_when_unset(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    calls = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kwargs: calls.append(kwargs))

    worker.main._init_sentry()

    assert calls == []
