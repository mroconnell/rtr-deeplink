"""Route-contract tests for the private Context candidate queue.

The candidate records are synthetic route fixtures. Their fields use the
frozen Milestone 1 schema; they do not claim to come from the pending source
Sheet. Storage and import are faked here because those packages are developed
independently and have their own database tests.
"""

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.testclient import TestClient

from archive.context import routes

_TOKEN = "Bearer queue-test-token"
_EDITOR = "user_context_queue_editor"


def _candidate(candidate_id: int = 7) -> dict:
    return {
        "id": candidate_id,
        "social_url": "https://www.youtube.com/shorts/zJKrMk-uuSw",
        "social_url_key": "youtube:zJKrMk-uuSw",
        "network": "youtube",
        "claims": {
            "jurisdiction": "San Diego, CA",
            "meeting_date": "2026-08-19",
            "meeting_body": "Public Safety <script>alert(1)</script>",
            "recording_url": "javascript:alert(1)",
        },
        "source_conflicts": [],
        "version": 1,
        "lookup_outcome": "matched",
        "next_action": "moment_needed",
        "lookup_result": {
            "outcome": "matched",
            "next_action": "moment_needed",
            "reason": "One exact Archive URL matched.",
            "possible_pages": [],
            "evidence": [{"kind": "rtr_link", "text": "<b>untrusted</b>"}],
        },
        "checked_at": "2026-09-23T10:00:00Z",
        "meeting": {
            "id": 3,
            "slug": "city-of-san-diego-ca-2026-08-19-public-safety",
            "title": "Public Safety Committee",
            "url": "/m/city-of-san-diego-ca-2026-08-19-public-safety",
        },
        "existing_entry": {"id": 2, "status": "published", "url": "/context/2"},
        "observations": [
            {
                "id": 11,
                "provider": "research-test",
                "source_record_key": "row-1",
                "source_location": "https://example.com/source",
                "content_hash": "abc",
                "raw_payload": {"notes": "<script>raw()</script>"},
                "normalized_payload": {"jurisdiction": "San Diego, CA"},
                "received_at": "2026-09-23T09:00:00Z",
                "active": True,
            }
        ],
    }


def _client(monkeypatch, *, user_id=_EDITOR, store=None, importer=None):
    monkeypatch.setenv("CONTEXT_EDITOR_CLERK_IDS", _EDITOR)
    templates = Jinja2Templates(
        directory=Path(__file__).parents[1] / "archive/templates"
    )
    templates.env.globals.update(
        CLERK_PUBLISHABLE_KEY="",
        CLERK_FRONTEND_API_URL="",
        GA_MEASUREMENT_ID="",
    )
    fake_store = store or SimpleNamespace()
    fake_importer = importer or SimpleNamespace()
    monkeypatch.setattr(routes, "_store_module", lambda: fake_store)
    monkeypatch.setattr(routes, "_importer_module", lambda: fake_importer)
    monkeypatch.setattr(
        routes,
        "_next_action_labels",
        lambda: {
            "new": "Not checked yet",
            "check_failed": "Check failed — retry",
            "conflict": "Review conflicting evidence",
            "resolve_needed": "Identify the meeting",
            "recording_needed": "Find the full recording",
            "ingest_needed": "Review recording for ingestion",
            "moment_needed": "Review the moment and explanation",
        },
    )
    app = FastAPI()
    app.include_router(
        routes.build_router(
            templates=templates,
            token_ok=lambda authorization: authorization == _TOKEN,
            clerk_user_id=lambda request: user_id,
        )
    )
    return TestClient(app)


def _assert_private(response):
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["x-robots-tag"] == "noindex"


def test_queue_rejects_anonymous_and_non_editor_without_touching_store(monkeypatch):
    class Store:
        async def list_candidates(self, **kwargs):
            raise AssertionError("authorization must run before storage")

    for user_id in (None, "user_not_allowed"):
        response = _client(monkeypatch, user_id=user_id, store=Store()).get(
            "/context/candidates"
        )
        assert response.status_code == 404
        _assert_private(response)


def test_queue_filters_paginates_and_escapes_imported_text(monkeypatch):
    captured = {}

    class Store:
        async def list_candidates(self, **kwargs):
            captured.update(kwargs)
            candidate = _candidate()
            candidate.pop("observations")
            return {
                "candidates": [candidate],
                "total": 51,
                "page": 2,
                "page_size": 25,
                "total_pages": 3,
                "counts": {"moment_needed": 51},
            }

    response = _client(monkeypatch, store=Store()).get(
        "/context/candidates?page=2&next_action=moment_needed"
    )
    assert response.status_code == 200
    _assert_private(response)
    assert captured == {"page": 2, "next_action": "moment_needed"}
    assert "Page 2 of 3" in response.text
    assert "next_action=moment_needed" in response.text
    assert "Public Safety &lt;script&gt;alert(1)&lt;/script&gt;" in response.text
    assert 'href="javascript:alert(1)"' not in response.text
    assert '<meta name="robots" content="noindex,nofollow">' in response.text


def test_detail_shows_observations_without_rendering_markup(monkeypatch):
    class Store:
        async def get_candidate(self, candidate_id):
            assert candidate_id == 7
            return _candidate()

    response = _client(monkeypatch, store=Store()).get("/context/candidates/7")
    assert response.status_code == 200
    _assert_private(response)
    assert "research-test / row-1" in response.text
    assert "\\u003cscript\\u003eraw()\\u003c/script\\u003e" in response.text
    assert "<script>raw()</script>" not in response.text
    assert 'href="/m/city-of-san-diego-ca-2026-08-19-public-safety"' in response.text
    assert "data-refresh-queue hidden" in response.text


def test_detail_renders_each_conflicting_research_value(monkeypatch):
    class Store:
        async def get_candidate(self, candidate_id):
            candidate = _candidate(candidate_id)
            candidate["source_conflicts"] = [
                {
                    "field": "meeting_date",
                    "values": [
                        {
                            "value": "2026-08-19",
                            "sources": [
                                {
                                    "provider": "provider-one",
                                    "source_record_key": "row-one",
                                }
                            ],
                        },
                        {
                            "value": "2026-08-20",
                            "sources": [
                                {
                                    "provider": "provider-two",
                                    "source_record_key": "row-two",
                                }
                            ],
                        },
                    ],
                }
            ]
            return candidate

    response = _client(monkeypatch, store=Store()).get("/context/candidates/7")
    assert response.status_code == 200
    assert "2026-08-19" in response.text
    assert "provider-one / row-one" in response.text
    assert "2026-08-20" in response.text
    assert "provider-two / row-two" in response.text


def test_detail_rejects_huge_numeric_id_before_calling_store(monkeypatch):
    class Store:
        async def get_candidate(self, candidate_id):
            raise AssertionError("oversized id must not reach storage")

    response = _client(monkeypatch, store=Store()).get(
        "/context/candidates/" + "9" * 5_000
    )
    assert response.status_code == 404
    _assert_private(response)


def test_deleted_meeting_recheck_reason_appears_in_list_and_detail(monkeypatch):
    message = "The linked meeting was deleted. Recheck this candidate. <not markup>"
    candidate = _candidate()
    candidate.update(
        meeting=None,
        lookup_outcome=None,
        lookup_result=None,
        next_action="new",
        needs_recheck=True,
        recheck_reason=message,
    )

    class Store:
        async def list_candidates(self, **kwargs):
            list_item = {
                key: value for key, value in candidate.items() if key != "observations"
            }
            return {
                "candidates": [list_item],
                "total": 1,
                "page": 1,
                "page_size": 25,
                "total_pages": 1,
                "counts": {"new": 1},
            }

        async def get_candidate(self, candidate_id):
            return candidate

    client = _client(monkeypatch, store=Store())
    for path in ("/context/candidates", "/context/candidates/7"):
        response = client.get(path)
        assert response.status_code == 200
        assert (
            "The linked meeting was deleted. Recheck this candidate." in response.text
        )
        assert "&lt;not markup&gt;" in response.text
        assert "<not markup>" not in response.text


def test_missing_candidate_and_store_error_are_distinct(monkeypatch):
    class MissingStore:
        async def get_candidate(self, candidate_id):
            return None

    response = _client(monkeypatch, store=MissingStore()).get("/context/candidates/999")
    assert response.status_code == 404
    _assert_private(response)

    class BrokenStore:
        async def get_candidate(self, candidate_id):
            raise RuntimeError("database password must not be exposed")

    response = _client(monkeypatch, store=BrokenStore()).get("/context/candidates/999")
    assert response.status_code == 503
    _assert_private(response)
    assert "database password" not in response.text
    assert "temporarily unavailable" in response.text


def test_import_is_token_only_and_forwards_the_frozen_request(monkeypatch):
    captured = {}

    class Importer:
        async def import_rows(self, rows, **kwargs):
            captured.update(rows=rows, **kwargs)
            return {"input_rows": 1, "created": 1}

    client = _client(monkeypatch, user_id=None, importer=Importer())
    payload = {
        "schema_version": 1,
        "provider": "research-test",
        "source_location": "https://example.com/sheet",
        "rows": [{"social_url": "https://example.com/post/1"}],
        "apply": True,
    }
    denied = client.post("/internal/context/candidates/import", json=payload)
    assert denied.status_code == 404
    _assert_private(denied)
    response = client.post(
        "/internal/context/candidates/import",
        json=payload,
        headers={"Authorization": _TOKEN},
    )
    assert response.status_code == 200
    _assert_private(response)
    assert captured == {
        "rows": payload["rows"],
        "provider": "research-test",
        "source_location": "https://example.com/sheet",
        "apply": True,
    }


def test_import_bounds_rows_and_body_without_calling_importer(monkeypatch):
    class Importer:
        async def import_rows(self, *args, **kwargs):
            raise AssertionError("invalid input must not reach importer")

    client = _client(monkeypatch, importer=Importer())
    response = client.post(
        "/internal/context/candidates/import",
        json={"provider": "x", "rows": [{}] * 101},
        headers={"Authorization": _TOKEN},
    )
    assert response.status_code == 422
    _assert_private(response)
    response = client.post(
        "/internal/context/candidates/import",
        content=b"x" * 1_000_001,
        headers={"Authorization": _TOKEN},
    )
    assert response.status_code == 422
    _assert_private(response)


def test_internal_recheck_requires_editor_and_deduplicates_ids(monkeypatch):
    calls = []

    class Store:
        async def recheck_candidate(self, candidate_id):
            calls.append(candidate_id)
            return {
                "id": candidate_id,
                "outcome": "checked",
                "next_action": "moment_needed",
            }

    client = _client(monkeypatch, store=Store())
    denied = client.post(
        "/internal/context/candidates/recheck",
        json={"clerk_user_id": "forged", "ids": [7]},
        headers={"Authorization": _TOKEN},
    )
    assert denied.status_code == 404
    assert denied.json() == {"error": "not_editor"}
    _assert_private(denied)

    response = client.post(
        "/internal/context/candidates/recheck",
        json={"clerk_user_id": _EDITOR, "ids": [7, 7, 8]},
        headers={"Authorization": _TOKEN},
    )
    assert response.status_code == 200
    assert calls == [7, 8]
    assert [item["id"] for item in response.json()["results"]] == [7, 8]
    _assert_private(response)


def test_internal_recheck_hides_store_exception(monkeypatch):
    class Store:
        async def recheck_candidate(self, candidate_id):
            raise RuntimeError("secret database details")

    response = _client(monkeypatch, store=Store()).post(
        "/internal/context/candidates/recheck",
        json={"clerk_user_id": _EDITOR, "ids": [7]},
        headers={"Authorization": _TOKEN},
    )
    assert response.status_code == 503
    assert response.json() == {"error": "candidate_service_unavailable"}
    _assert_private(response)
