"""HTTP-level tests for the /internal/context/* routes (archive/main.py) --
the WO-942 Full Context feed's write path. Bearer-token gating mirrors
tests/test_account_internal_routes.py's pattern; is_context_editor()
gating (CONTEXT_EDITOR_CLERK_IDS) is exercised directly here since this is
the first Archive feature to use it. Each test uses its own unique social
URL/external_id so tests can run in any order without colliding (the
fixture DB isn't reset per-test) -- same convention as
tests/test_context_entries.py.
"""

import uuid

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud

client = TestClient(archive.main.app)

_TOKEN = {"Authorization": "Bearer test-token"}
_EDITOR = "user_context_editor_1"


def _social_url(suffix: str | None = None) -> str:
    suffix = suffix or uuid.uuid4().hex[:16]
    return f"https://example.com/context-route-test/{suffix}"


def _payload(external_id: str, source_url: str) -> dict:
    return {
        "platform": "granicus",
        "source_url": source_url,
        "external_id": external_id,
        "title": "Context Route Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "Context Route Test City, CA",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }


async def _make_page(external_id: str) -> str:
    url = f"https://example.granicus.com/player/clip/{external_id}"
    result = await crud.ingest_resolution(_payload(external_id, url), url)
    return result["slug"]


def _allow(monkeypatch, clerk_user_id: str = _EDITOR) -> None:
    monkeypatch.setenv("CONTEXT_EDITOR_CLERK_IDS", clerk_user_id)


def test_save_and_set_status_404_with_no_token():
    response = client.post(
        "/internal/context/save",
        json={"clerk_user_id": _EDITOR, "social_url": _social_url(), "summary": "x"},
    )
    assert response.status_code == 404
    response = client.post(
        "/internal/context/set-status",
        json={"clerk_user_id": _EDITOR, "id": 1, "status": "hidden"},
    )
    assert response.status_code == 404


def test_save_and_set_status_404_with_wrong_token():
    headers = {"Authorization": "Bearer not-the-real-token"}
    response = client.post(
        "/internal/context/save",
        json={"clerk_user_id": _EDITOR, "social_url": _social_url(), "summary": "x"},
        headers=headers,
    )
    assert response.status_code == 404
    response = client.post(
        "/internal/context/set-status",
        json={"clerk_user_id": _EDITOR, "id": 1, "status": "hidden"},
        headers=headers,
    )
    assert response.status_code == 404


def test_save_403s_for_a_non_editor(monkeypatch):
    _allow(monkeypatch, "user_someone_else")
    response = client.post(
        "/internal/context/save",
        json={
            "clerk_user_id": "user_not_an_editor",
            "social_url": _social_url(),
            "summary": "x",
        },
        headers=_TOKEN,
    )
    assert response.status_code == 403
    assert response.json()["error"] == "not_editor"


def test_save_403s_when_allowlist_is_unset(monkeypatch):
    # Fail closed: an unset CONTEXT_EDITOR_CLERK_IDS must mean "nobody is
    # an editor," never "everybody is."
    monkeypatch.delenv("CONTEXT_EDITOR_CLERK_IDS", raising=False)
    response = client.post(
        "/internal/context/save",
        json={"clerk_user_id": _EDITOR, "social_url": _social_url(), "summary": "x"},
        headers=_TOKEN,
    )
    assert response.status_code == 403
    assert response.json()["error"] == "not_editor"


def test_save_happy_path_draft_with_no_meeting(monkeypatch):
    _allow(monkeypatch)
    response = client.post(
        "/internal/context/save",
        json={
            "clerk_user_id": _EDITOR,
            "social_url": _social_url(),
            "summary": "A clip with no matched meeting yet.",
        },
        headers=_TOKEN,
    )
    assert response.status_code == 200
    entry = response.json()["entry"]
    assert entry["status"] == "draft"
    assert entry["has_meeting"] is False
    assert entry["slug"] is None


async def test_save_happy_path_with_full_share_link(monkeypatch):
    _allow(monkeypatch)
    slug = await _make_page(f"save-share-link-{uuid.uuid4().hex[:8]}")
    response = client.post(
        "/internal/context/save",
        json={
            "clerk_user_id": _EDITOR,
            "social_url": _social_url(),
            "summary": "Exact moment clipped from the meeting.",
            "rtr_link": f"https://redtaperecordings.com/m/{slug}?t=754&line=seg-4&version=7",
            "match_kind": "exact",
            "status": "published",
        },
        headers=_TOKEN,
    )
    assert response.status_code == 200
    entry = response.json()["entry"]
    assert entry["slug"] == slug
    assert entry["t_seconds"] == 754
    assert entry["deep_link"] == f"/m/{slug}?t=754"
    assert entry["has_meeting"] is True


async def test_save_applies_slug_redirects(monkeypatch):
    _allow(monkeypatch)
    real_slug = await _make_page(f"redirect-target-{uuid.uuid4().hex[:8]}")
    old_slug = f"old-slug-{uuid.uuid4().hex[:8]}"
    monkeypatch.setitem(archive.main._SLUG_REDIRECTS, old_slug, real_slug)

    response = client.post(
        "/internal/context/save",
        json={
            "clerk_user_id": _EDITOR,
            "social_url": _social_url(),
            "summary": "Points at a since-reslugged permalink.",
            "rtr_link": f"/m/{old_slug}?t=12",
        },
        headers=_TOKEN,
    )
    assert response.status_code == 200
    entry = response.json()["entry"]
    assert entry["slug"] == real_slug


def test_save_400s_for_unknown_meeting_slug(monkeypatch):
    _allow(monkeypatch)
    response = client.post(
        "/internal/context/save",
        json={
            "clerk_user_id": _EDITOR,
            "social_url": _social_url(),
            "summary": "Points nowhere real.",
            "rtr_link": "/m/no-such-slug-at-all-context-route-test",
        },
        headers=_TOKEN,
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "unknown_meeting"
    assert "message" in body


def test_save_400s_for_an_insecure_social_url(monkeypatch):
    _allow(monkeypatch)
    response = client.post(
        "/internal/context/save",
        json={
            "clerk_user_id": _EDITOR,
            "social_url": "http://example.com/not-https",
            "summary": "x",
        },
        headers=_TOKEN,
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "insecure_url"
    assert "message" in body


def test_save_409s_for_a_duplicate_social_url(monkeypatch):
    _allow(monkeypatch)
    url = _social_url()
    first = client.post(
        "/internal/context/save",
        json={"clerk_user_id": _EDITOR, "social_url": url, "summary": "First save."},
        headers=_TOKEN,
    )
    assert first.status_code == 200
    existing_id = first.json()["entry"]["id"]

    second = client.post(
        "/internal/context/save",
        json={
            "clerk_user_id": _EDITOR,
            "social_url": url,
            "summary": "Same post, second entry.",
        },
        headers=_TOKEN,
    )
    assert second.status_code == 409
    body = second.json()
    assert body["error"] == "duplicate"
    assert body["existing_id"] == existing_id


def test_save_400s_publishing_without_a_meeting(monkeypatch):
    _allow(monkeypatch)
    response = client.post(
        "/internal/context/save",
        json={
            "clerk_user_id": _EDITOR,
            "social_url": _social_url(),
            "summary": "Trying to publish with nothing matched.",
            "status": "published",
        },
        headers=_TOKEN,
    )
    assert response.status_code == 400
    assert response.json()["error"] == "meeting_required"


async def test_set_status_publish_hide_republish(monkeypatch):
    _allow(monkeypatch)
    slug = await _make_page(f"set-status-{uuid.uuid4().hex[:8]}")
    save = client.post(
        "/internal/context/save",
        json={
            "clerk_user_id": _EDITOR,
            "social_url": _social_url(),
            "summary": "For set-status transitions.",
            "rtr_link": f"/m/{slug}",
            "match_kind": "related",
        },
        headers=_TOKEN,
    )
    assert save.status_code == 200
    entry_id = save.json()["entry"]["id"]

    published = client.post(
        "/internal/context/set-status",
        json={"clerk_user_id": _EDITOR, "id": entry_id, "status": "published"},
        headers=_TOKEN,
    )
    assert published.status_code == 200
    assert published.json()["entry"]["status"] == "published"

    hidden = client.post(
        "/internal/context/set-status",
        json={"clerk_user_id": _EDITOR, "id": entry_id, "status": "hidden"},
        headers=_TOKEN,
    )
    assert hidden.status_code == 200
    assert hidden.json()["entry"]["status"] == "hidden"

    republished = client.post(
        "/internal/context/set-status",
        json={"clerk_user_id": _EDITOR, "id": entry_id, "status": "published"},
        headers=_TOKEN,
    )
    assert republished.status_code == 200
    assert republished.json()["entry"]["status"] == "published"


async def test_response_json_round_trips_for_an_entry_with_a_meeting(monkeypatch):
    # Pins that the entry dict's datetimes (published_at/created_at/
    # updated_at) and Markup date_html all serialize cleanly through
    # FastAPI's default JSON encoder -- a real risk since Markup is a str
    # subclass and this is the first route to hand one back as JSON
    # rather than rendering it into a template.
    _allow(monkeypatch)
    slug = await _make_page(f"json-round-trip-{uuid.uuid4().hex[:8]}")
    response = client.post(
        "/internal/context/save",
        json={
            "clerk_user_id": _EDITOR,
            "social_url": _social_url(),
            "summary": "Round-trips through JSON cleanly.",
            "rtr_link": f"/m/{slug}?t=5",
            "match_kind": "exact",
            "status": "published",
        },
        headers=_TOKEN,
    )
    assert response.status_code == 200
    entry = response.json()["entry"]
    assert isinstance(entry["date_html"], str)
    assert isinstance(entry["published_at"], str)
    assert isinstance(entry["created_at"], str)
    assert isinstance(entry["updated_at"], str)
