"""Tests for archive/db/engine.py's _assert_expected_db_host() -- WO-4
(AUDIT_EXECUTION_BRIEF.md, 2026-08-16). Real gap this closes: the worker's
DATABASE_URL must be the exact same value as the Archive's own
(render.yaml's own "MUST be the exact same value" comment), but each is a
separately dashboard-set env var on two different Render services with
nothing enforcing that at deploy time.
"""

from archive.db.engine import _assert_expected_db_host


def test_noop_when_expected_db_host_unset(monkeypatch):
    # This module is also imported by dashboard-cloned staging/test
    # services running the same code -- EXPECTED_DB_HOST must default to
    # a no-op so pushing this check doesn't hard-crash a staging deploy
    # that never set it.
    monkeypatch.delenv("EXPECTED_DB_HOST", raising=False)
    _assert_expected_db_host("postgresql+asyncpg://user:pass@anything/db")


def test_noop_for_sqlite_regardless_of_expected_host(monkeypatch):
    monkeypatch.setenv("EXPECTED_DB_HOST", "dpg-real-prod-host-a")
    _assert_expected_db_host("sqlite+aiosqlite:///./archive_dev.db")


def test_matching_host_does_not_raise(monkeypatch):
    monkeypatch.setenv("EXPECTED_DB_HOST", "dpg-real-prod-host-a")
    _assert_expected_db_host(
        "postgresql+asyncpg://user:pass@dpg-real-prod-host-a/dbname"
    )


def test_mismatched_host_raises_clearly(monkeypatch):
    monkeypatch.setenv("EXPECTED_DB_HOST", "dpg-real-prod-host-a")
    try:
        _assert_expected_db_host(
            "postgresql+asyncpg://user:pass@dpg-wrong-staging-host-a/dbname"
        )
        assert False, "expected a RuntimeError"
    except RuntimeError as e:
        assert "dpg-real-prod-host-a" in str(e)
        assert "dpg-wrong-staging-host-a" in str(e)
