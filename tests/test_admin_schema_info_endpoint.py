"""HTTP-level tests for GET /admin/schema-info (app/main.py) -- read-only
DB introspection so confirming the resolver's real production schema
state doesn't require someone with DATABASE_URL access to run psql/
alembic commands on Render's shell and paste output back by hand.

The resolver's port of the Archive's own /internal/schema-info (see
tests/test_schema_info_endpoint.py, the model for this file). It exists
specifically so the one-time `alembic stamp` step in app/alembic/README.md
can be decided from a checked fact -- does production really have
meeting_resolutions.jurisdiction_confidence, and what does alembic_version
actually say -- rather than from a doc's possibly-stale account of
production's state, which is the exact mistake BACKLOG_DONE.md's
2026-08-09/08-10 Alembic incidents record.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import create_async_engine

import app.main

client = TestClient(app.main.app)


def test_schema_info_rejects_missing_token():
    response = client.get("/admin/schema-info")
    assert (
        response.status_code == 404
    )  # not 401/403 -- matches every other /admin/* route


def test_schema_info_rejects_wrong_token():
    response = client.get(
        "/admin/schema-info", headers={"Authorization": "Bearer not-the-real-token"}
    )
    assert response.status_code == 404


def test_schema_info_rejects_legacy_query_param_token():
    """_admin_token_ok() is Authorization-header-only as of 2026-08-24
    (see its own docstring) -- this route inherits that, same as
    /admin/stats. The ?token= query-param fallback (WO-8) was removed
    once both admin cron workflows had run green on header auth for a
    while."""
    response = client.get("/admin/schema-info", params={"token": "test-admin-token"})
    assert response.status_code == 404


def test_schema_info_reports_real_columns_matching_models():
    response = client.get(
        "/admin/schema-info", headers={"Authorization": "Bearer test-admin-token"}
    )
    assert response.status_code == 200
    data = response.json()

    assert "meeting_resolutions" in data["expected_columns"]
    assert "meeting_resolutions" in data["actual_columns"]
    assert "problem_reports" in data["expected_columns"]
    # The whole point of this endpoint: the test DB is built via
    # create_all() (see conftest.py), so this always matches in a
    # correctly-migrated environment -- a real mismatch (the exact
    # scenario this endpoint exists to catch) would show up here as a
    # non-empty mismatched_tables list.
    assert data["mismatched_tables"] == []
    assert data["schema_matches_models"] is True
    assert set(data["expected_columns"]["meeting_resolutions"]) == set(
        data["actual_columns"]["meeting_resolutions"]
    )


def test_schema_info_reports_jurisdiction_confidence_column():
    """The specific question this endpoint was built to answer against
    production: migration a9207c0eb761 (2026-08-15) adds
    jurisdiction_confidence, and app/db/crud.py writes it on every
    resolve inside a swallow-everything safe() wrapper -- so if
    production is missing the column the failure is silent. Asserting on
    the column by name here means a model change that drops it can't
    quietly make this endpoint stop reporting the thing it exists for.
    """
    response = client.get(
        "/admin/schema-info", headers={"Authorization": "Bearer test-admin-token"}
    )
    data = response.json()
    assert "jurisdiction_confidence" in data["expected_columns"]["meeting_resolutions"]
    assert "jurisdiction_confidence" in data["actual_columns"]["meeting_resolutions"]


@pytest.fixture
def own_shared_database(tmp_path, monkeypatch):
    """A fresh SQLite file holding both services' tables, used by the
    endpoint in place of the suite-wide one.

    The suite-wide file (conftest.py) is shared by every test module, and
    what it holds at this test's turn depended on everything collected
    before it: this test passed alone and failed in some full local runs
    (BACKLOG.md, 2026-09-10 and 2026-09-26), while CI passed. Building the
    exact state the test asserts about -- one database, the resolver's
    tables plus an Archive-owned one -- makes it depend on nothing else.
    The endpoint imports `engine` and `Base` from app.db at call time, so
    patching the module attribute is what it reads.
    """
    import app.db.engine as resolver_engine
    import app.db.models as resolver_models
    import archive.db.models as archive_models

    path = tmp_path / "shared.db"
    sync_engine = create_engine(f"sqlite:///{path}")
    resolver_models.Base.metadata.create_all(sync_engine)
    archive_models.Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}")
    monkeypatch.setattr(resolver_engine, "engine", engine)
    yield
    asyncio.run(engine.dispose())


def test_schema_info_ignores_tables_this_service_does_not_own(own_shared_database):
    """The resolver and the Archive share one Postgres database.
    actual_columns is a whole-database reflection, so the Archive's tables
    appear here; they must not count as a mismatch, since app/db/models.py
    says nothing about them.
    """
    response = client.get(
        "/admin/schema-info", headers={"Authorization": "Bearer test-admin-token"}
    )
    data = response.json()
    assert "meeting_pages" in data["actual_columns"]  # archive-owned
    assert "meeting_pages" not in data["expected_columns"]
    assert data["mismatched_tables"] == []
