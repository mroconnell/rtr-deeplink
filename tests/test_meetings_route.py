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


async def test_pagination_link_preserves_explicit_has_transcript_false():
    # Real bug fixed 2026-09-01, reported live in production: has_transcript
    # is tri-state (None/True/False -- see _parse_optional_bool), but the
    # pagination link builder used to gate on truthiness, so an explicit
    # "?has_transcript=false" (meetings WITHOUT a transcript) looked
    # identical to "unset" and silently dropped off the "Next" link,
    # reverting page 2+ to the unfiltered list. The pagination nav only
    # renders at all when `pages` is non-empty, and "Next" only when
    # total_pages > 1, so this needs enough real, transcript-less rows in
    # the test DB to actually produce a page-2 link -- 21 to exceed
    # list_pages()'s default page_size of 20.
    from archive.db.engine import async_session
    from archive.db.models import MeetingPage

    async with async_session() as session:
        for i in range(21):
            session.add(
                MeetingPage(
                    slug=f"pagination-has-transcript-false-{i}",
                    platform="youtube",
                    external_id=f"pagination-has-transcript-false-{i}",
                    source_url_normalized=(
                        f"https://example.test/pagination-has-transcript-false-{i}"
                    ),
                    title="Pagination has_transcript=false probe",
                    jurisdiction="Probeville, CA",
                )
            )
        await session.commit()

    response = client.get("/meetings?page=1&has_transcript=false")
    assert response.status_code == 200
    assert "has_transcript=false" in response.text
