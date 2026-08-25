"""HTTP-level tests for GET /internal/db-size (archive/main.py) -- a
read-only storage report for the Postgres server this service shares with
the resolver's database.

Built after a 2026-08-24 Render alert said `rtr-deeplink-db` was over 90%
of its storage limit and nothing in this repo could size that against
anything: render.yaml's `basic-1gb` plan comment is entirely a
RAM/shared_buffers argument and names no storage cap. Same reasoning as
tests/test_schema_info_endpoint.py's endpoint -- when a doc asserts a
fact about production that nothing in the repo can verify, build the read
that answers it.

The suite runs on SQLite (see conftest.py), so what's testable here is the
token gate and the unsupported-dialect branch. The Postgres path is
deliberately a plain catalog read (pg_database_size / pg_total_relation_
size) with no application logic to get wrong, and faking a Postgres
dialect to assert against invented catalog rows would test the fake, not
the query -- exactly the "synthetic payload with an invented shape"
this repo's conventions warn against.
"""

from fastapi.testclient import TestClient

import archive.main

client = TestClient(archive.main.app)


def test_db_size_rejects_missing_token():
    response = client.get("/internal/db-size")
    assert (
        response.status_code == 404
    )  # not 401/403 -- matches every other /internal/* route


def test_db_size_rejects_wrong_token():
    response = client.get(
        "/internal/db-size", headers={"Authorization": "Bearer not-the-real-token"}
    )
    assert response.status_code == 404


def test_db_size_reports_unsupported_rather_than_erroring_on_sqlite():
    """The local/test path is SQLite, which has none of these functions.
    Reported rather than raised, so hitting this locally says why instead
    of 500ing -- the same posture crud.py's Postgres-only helpers take."""
    response = client.get(
        "/internal/db-size", headers={"Authorization": "Bearer test-token"}
    )
    assert response.status_code == 200
    data = response.json()

    assert data["supported"] is False
    assert data["dialect"] == "sqlite"
    assert "Postgres" in data["detail"]
    # No size keys at all on the unsupported path -- a caller must not be
    # able to read a zero and mistake it for a real measurement.
    assert "databases" not in data
    assert "server_total_bytes" not in data
