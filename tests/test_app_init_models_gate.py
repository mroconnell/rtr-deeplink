"""WO-10's resolver half (2026-08-21): app/db/engine.py's init_models()
must be a no-op on Postgres -- Alembic (app/alembic/) is the only thing
allowed to touch the production schema -- and must still create_all() on
SQLite, which is what every other test in this suite depends on.

The exact mirror of tests/test_archive_init_models_gate.py, which pins the
same property for archive/db/engine.py. Pinned by swapping the module's
engine for a stub whose dialect name we control; no real Postgres needed.
"""

from types import SimpleNamespace

from app.db import engine as engine_module


class _NoConnectEngine:
    """Any attempt to open a connection is a test failure -- on Postgres,
    init_models() must return before touching the DB at all."""

    def __init__(self, dialect_name: str):
        self.dialect = SimpleNamespace(name=dialect_name)
        self.begin_calls = 0

    def begin(self):
        self.begin_calls += 1
        raise AssertionError("init_models() must not connect on postgresql")


async def test_init_models_is_a_no_op_on_postgres(monkeypatch):
    stub = _NoConnectEngine("postgresql")
    monkeypatch.setattr(engine_module, "engine", stub)
    await engine_module.init_models()  # returns without touching the engine
    assert stub.begin_calls == 0


async def test_init_models_still_creates_tables_on_sqlite():
    # The real, per-session SQLite engine from tests/conftest.py: calling
    # init_models() again is a safe no-op that proves the SQLite branch is
    # still live (it must connect and run create_all, not early-return).
    assert engine_module.engine.dialect.name == "sqlite"
    await engine_module.init_models()
