"""HTTP-level tests for the new /internal/account/* routes (archive/main.py)
-- bearer-token gating specifically, mirroring
tests/test_correct_language_endpoint.py's pattern. Route-level logic
beyond the token check is already covered at the crud level in
tests/test_saved_items.py.
"""

from fastapi.testclient import TestClient

import archive.main

client = TestClient(archive.main.app)

_ROUTES = [
    ("/internal/account/save-meeting", {"clerk_user_id": "u1", "slug": "whatever"}),
    ("/internal/account/unsave-meeting", {"clerk_user_id": "u1", "slug": "whatever"}),
    ("/internal/account/save-search", {"clerk_user_id": "u1", "search_params": {}}),
    ("/internal/account/unsave-search", {"clerk_user_id": "u1", "saved_item_id": 1}),
    ("/internal/account/delete-data", {"clerk_user_id": "u1"}),
]


def test_all_account_routes_404_with_no_token():
    for path, body in _ROUTES:
        response = client.post(path, json=body)
        assert response.status_code == 404, path


def test_all_account_routes_404_with_wrong_token():
    for path, body in _ROUTES:
        response = client.post(
            path, json=body, headers={"Authorization": "Bearer not-the-real-token"}
        )
        assert response.status_code == 404, path


def test_save_meeting_404s_for_unknown_slug_with_valid_token():
    response = client.post(
        "/internal/account/save-meeting",
        json={"clerk_user_id": "u1", "slug": "no-such-slug-at-all"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 404


def test_list_saved_items_route_requires_token():
    response = client.get("/internal/account/saved", params={"clerk_user_id": "u1"})
    assert response.status_code == 404


def test_list_saved_items_route_works_with_valid_token():
    response = client.get(
        "/internal/account/saved",
        params={"clerk_user_id": "u1"},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 200
    assert response.json() == {"meetings": [], "searches": []}
