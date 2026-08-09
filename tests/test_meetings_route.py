"""HTTP-level test for the /meetings route -- real bug fixed 2026-08-09,
reported live in production: clicking "Next" built a pagination link like
"...&fuzzy=&has_agenda=&has_transcript=" (every optional filter present
with an empty value, not omitted), which FastAPI's then-bool-typed query
params rejected with a 422 (bool_parsing expects a real boolean, not "").

Every other test in this suite exercises crud.list_pages()/pure functions
directly, which never touches FastAPI's own query-param parsing -- this is
the first route-level test in the suite, added specifically because this
exact bug lived entirely in that parsing layer and was invisible to
lower-level tests.
"""

from fastapi.testclient import TestClient

import archive.main

client = TestClient(archive.main.app)


def test_meetings_page_tolerates_empty_bool_query_params():
    # The exact malformed URL shape reported live in production.
    response = client.get(
        "/meetings?page=2&q=&jurisdiction=&date_from=&date_to=&fuzzy=&has_agenda=&has_transcript="
    )
    assert response.status_code == 200


def test_meetings_page_still_accepts_real_true_values():
    response = client.get("/meetings?fuzzy=true&has_agenda=true&has_transcript=true")
    assert response.status_code == 200


def test_meetings_page_works_with_no_query_params_at_all():
    response = client.get("/meetings")
    assert response.status_code == 200
