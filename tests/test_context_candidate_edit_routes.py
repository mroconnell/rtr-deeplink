"""Synthetic transport cases for editor saves and saved-review form handoff."""

from bs4 import BeautifulSoup
import pytest
from fastapi.testclient import TestClient

import app.main
import archive.main
from archive.context import store
from archive.context.schemas import CandidateReviewFields

EDITOR = "user_candidate_review_transport"
TOKEN = "Bearer test-token"


def fields(**changes):
    return {**dict.fromkeys(CandidateReviewFields.model_fields), **changes}


@pytest.fixture
def archive_client(monkeypatch):
    monkeypatch.setenv("CONTEXT_EDITOR_CLERK_IDS", EDITOR)
    monkeypatch.setenv("ARCHIVE_INGEST_TOKEN", "test-token")
    monkeypatch.setattr(archive.main, "get_clerk_user_id", lambda request: EDITOR)
    return TestClient(archive.main.app)


def test_save_requires_service_token_and_editor(archive_client, monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("unauthorized save reached storage")

    monkeypatch.setattr(store, "save_candidate_review", forbidden, raising=False)
    payload = dict(id=1, expected_version=2, fields=fields(), clerk_user_id=EDITOR)
    assert (
        archive_client.post(
            "/internal/context/candidates/save", json=payload
        ).status_code
        == 404
    )
    payload["clerk_user_id"] = "not-an-editor"
    response = archive_client.post(
        "/internal/context/candidates/save",
        json=payload,
        headers={"Authorization": TOKEN},
    )
    assert response.status_code == 404
    assert response.json()["error"] == "not_editor"
    assert response.headers["cache-control"] == "private, no-store"


@pytest.mark.parametrize(
    "bad_fields",
    [{"notes": "only notes"}, fields(t_seconds=True), fields(t_seconds=1.0)],
)
def test_save_rejects_partial_snapshot_and_coerced_timestamps(
    archive_client, monkeypatch, bad_fields
):
    async def forbidden(*args, **kwargs):
        pytest.fail("invalid review reached storage")

    monkeypatch.setattr(store, "save_candidate_review", forbidden, raising=False)
    response = archive_client.post(
        "/internal/context/candidates/save",
        json=dict(id=1, expected_version=2, fields=bad_fields, clerk_user_id=EDITOR),
        headers={"Authorization": TOKEN},
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    "outcome,status",
    [("saved", 200), ("stale", 409), ("not_found", 404), ("invalid", 422)],
)
def test_save_maps_storage_outcome(archive_client, monkeypatch, outcome, status):
    seen = {}

    async def save(candidate_id, **kwargs):
        seen.update(id=candidate_id, **kwargs)
        return {"outcome": outcome, "message": "result"}

    monkeypatch.setattr(store, "save_candidate_review", save, raising=False)
    response = archive_client.post(
        "/internal/context/candidates/save",
        json=dict(
            id=1,
            expected_version=2,
            fields=fields(t_seconds=0),
            clear_conflicts=["meeting_date"],
            clerk_user_id=EDITOR,
        ),
        headers={"Authorization": TOKEN},
    )
    assert response.status_code == status
    assert seen["clerk_user_id"] == EDITOR
    assert seen["fields"]["t_seconds"] == 0
    assert seen["expected_version"] == 2
    assert seen["clear_conflicts"] == ["meeting_date"]
    assert response.headers["x-robots-tag"] == "noindex"


def test_public_save_uses_verified_session(monkeypatch):
    monkeypatch.setattr(app.main, "get_clerk_user_id", lambda request: EDITOR)
    monkeypatch.setattr(app.main.limiter, "enabled", False)
    seen = {}

    async def save(editor_id, payload):
        seen.update(editor_id=editor_id, payload=payload)
        return 200, {"outcome": "saved"}

    monkeypatch.setattr(app.main.archive_client, "context_candidate_save", save)
    response = TestClient(app.main.app).post(
        "/api/context/candidates/save",
        json=dict(id=1, expected_version=2, fields=fields(), clerk_user_id="forged"),
    )
    assert response.status_code == 200
    assert seen["editor_id"] == EDITOR
    assert "clerk_user_id" not in seen["payload"]
    assert response.headers["cache-control"] == "private, no-store"


def test_public_save_requires_session(monkeypatch):
    monkeypatch.setattr(app.main, "get_clerk_user_id", lambda request: None)

    async def forbidden(*args):
        pytest.fail("anonymous save reached Archive")

    monkeypatch.setattr(app.main.archive_client, "context_candidate_save", forbidden)
    assert (
        TestClient(app.main.app)
        .post(
            "/api/context/candidates/save",
            json=dict(id=1, expected_version=2, fields=fields()),
        )
        .status_code
        == 401
    )


def _prefill_stub(monkeypatch, outcome="ready"):
    async def entry_list(**kwargs):
        return {"entries": []}

    async def prefill(candidate_id, review_id):
        assert (candidate_id, review_id) == (1, 7)
        return {
            "outcome": outcome,
            "prefill": dict(
                social_url="https://www.instagram.com/reel/DdF8tEDMtZs/",
                headline="<script>reviewed title</script>",
                summary="Saved review summary",
                source_label="Saved source",
                deep_link="/m/demo?t=0",
                match_kind="exact",
            ),
            "warnings": ["Review the proposed time."],
        }

    async def forbidden(*args, **kwargs):
        pytest.fail("opening a form must not save a Context entry")

    monkeypatch.setattr(archive.main.crud, "list_context_entries", entry_list)
    monkeypatch.setattr(archive.main.crud, "save_context_entry", forbidden)
    monkeypatch.setattr(store, "get_candidate_prefill", prefill, raising=False)


def test_prefill_is_escaped_unsaved_form(archive_client, monkeypatch):
    _prefill_stub(monkeypatch)
    response = archive_client.get("/context/new?candidate=1&review=7")
    assert response.status_code == 200
    assert "<script>reviewed title</script>" not in response.text
    form = BeautifulSoup(response.text, "html.parser").select_one("#contextEntryForm")
    assert form.select_one("[name=id]")["value"] == ""
    assert form.select_one("[name=title]")["value"] == "<script>reviewed title</script>"
    assert form.select_one("[name=rtr_link]")["value"] == "/m/demo?t=0"
    assert form.select_one("[name=summary]").text == "Saved review summary"
    assert form.select_one("[name=match_kind] option[selected]")["value"] == "exact"
    assert "Nothing has been saved as an entry yet" in response.text
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-robots-tag"] == "noindex"


@pytest.mark.parametrize(
    "outcome,status", [("stale", 409), ("review_required", 409), ("not_found", 404)]
)
def test_prefill_unavailable_review_does_not_show_blank_publish_form(
    archive_client, monkeypatch, outcome, status
):
    _prefill_stub(monkeypatch, outcome)
    response = archive_client.get("/context/new?candidate=1&review=7")
    assert response.status_code == status
    assert 'id="contextEntryForm"' not in response.text


@pytest.mark.parametrize(
    "query",
    [
        "candidate=1",
        "review=7",
        "id=2&candidate=1&review=7",
        "candidate=" + ("9" * 5000) + "&review=7",
    ],
)
def test_prefill_rejects_invalid_or_mixed_identifiers(
    archive_client, monkeypatch, query
):
    _prefill_stub(monkeypatch)
    response = archive_client.get("/context/new?" + query)
    assert response.status_code == 400
    assert 'id="contextEntryForm"' not in response.text


def test_prefill_authorization_runs_before_research_read(archive_client, monkeypatch):
    monkeypatch.setattr(archive.main, "get_clerk_user_id", lambda request: None)

    async def forbidden(*args):
        pytest.fail("private research read before authorization")

    monkeypatch.setattr(store, "get_candidate_prefill", forbidden, raising=False)
    assert archive_client.get("/context/new?candidate=1&review=7").status_code == 404


def test_prefill_missing_summary_stays_blank(archive_client, monkeypatch):
    _prefill_stub(monkeypatch)

    async def prefill(*args):
        return {
            "outcome": "ready",
            "prefill": {
                "social_url": "https://www.instagram.com/reel/DdF8tEDMtZs/",
                "summary": None,
            },
        }

    monkeypatch.setattr(store, "get_candidate_prefill", prefill, raising=False)
    response = archive_client.get("/context/new?candidate=1&review=7")
    form = BeautifulSoup(response.text, "html.parser").select_one("#contextEntryForm")
    assert form.select_one("[name=summary]").text == ""
