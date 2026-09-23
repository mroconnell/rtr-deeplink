"""Candidate routing and session isolation across the two existing services."""

import pytest
from fastapi.responses import Response
from fastapi.testclient import TestClient

import app.main


@pytest.fixture
def client():
    return TestClient(app.main.app)


@pytest.mark.parametrize("path", ["/context/candidates", "/context/candidates/12"])
def test_candidate_routes_precede_permalink_and_forward_cookie(
    monkeypatch, client, path
):
    seen = {}

    async def proxy(internal_path, query, cookie=None, **kwargs):
        seen.update(path=internal_path, query=query, cookie=cookie, kwargs=kwargs)
        return Response("private research")

    monkeypatch.setattr(app.main, "_proxy_to_archive", proxy)
    response = client.get(
        path + "?next_action=conflict", headers={"Cookie": "__session=test"}
    )
    assert response.status_code == 200
    assert seen["path"] == path.lstrip("/")
    assert seen["cookie"] == "__session=test"
    assert seen["query"] == "next_action=conflict"
    assert seen["kwargs"]["allow_redirects"] is False
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-robots-tag"] == "noindex"


def test_recheck_uses_session_not_supplied_identity(monkeypatch, client):
    monkeypatch.setattr(
        app.main, "get_clerk_user_id", lambda request: "verified_editor"
    )
    seen = {}

    async def recheck(clerk_user_id, ids):
        seen.update(clerk_user_id=clerk_user_id, ids=ids)
        return 200, {"results": []}

    monkeypatch.setattr(app.main.archive_client, "context_candidates_recheck", recheck)
    response = client.post(
        "/api/context/candidates/recheck",
        json={"ids": [1, 1, 2], "clerk_user_id": "forged_editor"},
    )
    assert response.status_code == 200
    assert seen == {"clerk_user_id": "verified_editor", "ids": [1, 2]}
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize(
    "upstream,status,error",
    [
        (None, 502, "archive_unreachable"),
        ((404, {"detail": "Not Found"}), 502, "archive_unreachable"),
        ((404, {"error": "not_editor"}), 404, None),
        (
            (503, {"error": "candidate_service_unavailable"}),
            503,
            "candidate_service_unavailable",
        ),
    ],
)
def test_recheck_preserves_failure_instead_of_reporting_missing(
    monkeypatch, client, upstream, status, error
):
    monkeypatch.setattr(
        app.main, "get_clerk_user_id", lambda request: "verified_editor"
    )

    async def recheck(*args):
        return upstream

    monkeypatch.setattr(app.main.archive_client, "context_candidates_recheck", recheck)
    response = client.post("/api/context/candidates/recheck", json={"ids": [1]})
    assert response.status_code == status
    assert response.json().get("error") == error


def test_recheck_without_session_does_not_reach_archive(monkeypatch, client):
    monkeypatch.setattr(app.main, "get_clerk_user_id", lambda request: None)

    async def forbidden(*args):
        pytest.fail("Signed-out request must never call Archive")

    monkeypatch.setattr(
        app.main.archive_client, "context_candidates_recheck", forbidden
    )
    assert (
        client.post("/api/context/candidates/recheck", json={"ids": [1]}).status_code
        == 401
    )


def test_recheck_rejects_unbounded_batch(client):
    assert (
        client.post(
            "/api/context/candidates/recheck", json={"ids": list(range(26))}
        ).status_code
        == 422
    )


@pytest.mark.parametrize("value", ["9" * 5000, "2147483648", "-1", "0", "abc"])
def test_candidate_detail_rejects_bad_id_before_proxy(monkeypatch, client, value):
    async def forbidden(*args, **kwargs):
        pytest.fail("Invalid ID must not reach Archive")

    monkeypatch.setattr(app.main, "_proxy_to_archive", forbidden)
    assert client.get("/context/candidates/" + value).status_code == 404
