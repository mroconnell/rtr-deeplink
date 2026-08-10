"""HTTP-level tests for GET /internal/schema-info (archive/main.py) --
read-only DB introspection so confirming production's real schema state
doesn't require someone with DATABASE_URL access to run psql/alembic
commands and paste output back by hand. See BACKLOG_DONE.md's 2026-08-10
Alembic incident for why this exists.
"""

import os

os.environ.setdefault("ARCHIVE_INGEST_TOKEN", "test-token")

from fastapi.testclient import TestClient

import archive.main

client = TestClient(archive.main.app)


def test_schema_info_rejects_missing_token():
    response = client.get("/internal/schema-info")
    assert response.status_code == 404  # not 401/403 -- matches every other /internal/* route


def test_schema_info_rejects_wrong_token():
    response = client.get("/internal/schema-info", headers={"Authorization": "Bearer not-the-real-token"})
    assert response.status_code == 404


def test_schema_info_reports_real_columns_matching_models():
    response = client.get("/internal/schema-info", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    data = response.json()

    assert "meeting_pages" in data["expected_columns"]
    assert "meeting_pages" in data["actual_columns"]
    # The whole point of this endpoint: the test DB is built via
    # create_all() (see conftest.py), same as this always matches in a
    # correctly-migrated environment -- a real mismatch (the exact
    # scenario this endpoint exists to catch) would show up here as a
    # non-empty mismatched_tables list.
    assert data["mismatched_tables"] == []
    assert data["schema_matches_models"] is True
    assert set(data["expected_columns"]["meeting_pages"]) == set(data["actual_columns"]["meeting_pages"])
