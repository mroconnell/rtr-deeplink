"""GET /internal/thin-page-audit (WO-58) and the SQL-vs-Python agreement
it exists to keep honest.

Shipped alongside the Soft 404 fix so that change could be *sized* rather
than assumed: dropping `agenda_link` from _is_empty_page_condition()
de-indexes real live pages, and nothing in the repo could count them.

The lockstep test at the bottom is the important one. The "is this page
empty?" rule is written twice -- once as SQL (crud._is_empty_page_condition(),
behind /meetings, sitemap.xml and feed.xml) and once as Python
(archive/main.py's `page_is_empty`, driving the template's noindex). The two
drifting apart puts a noindexed page back in the sitemap, which is the exact
Search Console contradiction the 2026-08-17 fix removed, and nothing else in
the suite would notice.

Seeded rows use a jurisdiction and external_ids no other test uses, per
this suite's shared-session-DB convention (tests/conftest.py).
"""

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud

client = TestClient(archive.main.app)

JX = "Thintest City, CA"


def _payload(external_id: str, **overrides) -> dict:
    payload = {
        "platform": "granicus",
        "source_url": f"https://example.com/thintest/{external_id}",
        "external_id": external_id,
        "title": f"Thintest {external_id}",
        "date": "2024-04-06",
        "jurisdiction": JX,
        "video_url": None,
        "video_format": None,
        "segments": [],
        "agenda_items": [],
        "agenda_link": None,
        "transcript_language": None,
        "transcript_warnings": [],
    }
    payload.update(overrides)
    return payload


async def _seed(external_id: str, **overrides) -> str:
    payload = _payload(external_id, **overrides)
    result = await crud.ingest_resolution(payload, payload["source_url"])
    return result["slug"]


# --- token gate ----------------------------------------------------------


def test_thin_page_audit_rejects_missing_token():
    response = client.get("/internal/thin-page-audit")
    assert response.status_code == 404  # not 401/403, like every /internal/* route


def test_thin_page_audit_rejects_wrong_token():
    response = client.get(
        "/internal/thin-page-audit", headers={"Authorization": "Bearer nope"}
    )
    assert response.status_code == 404


# --- buckets -------------------------------------------------------------


async def test_buckets_separate_agenda_link_only_from_genuinely_empty():
    empty = await _seed("thin:empty")
    link_only = await _seed(
        "thin:linkonly", agenda_link="https://example.com/agenda.pdf"
    )
    real = await _seed(
        "thin:real", video_url="https://example.com/v.m3u8", video_format="m3u8"
    )

    result = await crud.get_thin_page_audit(slugs={empty, link_only, real})
    by_slug = {p["slug"]: p for p in result["thin_pages"]}

    assert by_slug[empty]["bucket"] == "empty"
    assert by_slug[empty]["agenda_link"] is None
    assert by_slug[link_only]["bucket"] == "agenda_link_only"
    assert by_slug[link_only]["agenda_link"] == "https://example.com/agenda.pdf"
    # A page with real content is counted, never listed.
    assert real not in by_slug
    assert result["counts"]["has_content"] == 1
    assert result["total_pages"] == 3


async def test_agenda_link_only_rows_carry_platform_for_narrowing_later():
    """A generic_fallback agenda_link is a guess; a Granicus one is usually
    a real agenda document. If this population turns out large, that's the
    distinction it gets narrowed on -- so the platform has to be reported."""
    slug = await _seed(
        "thin:platform",
        platform="generic_fallback",
        agenda_link="https://example.com/guess.pdf",
    )

    result = await crud.get_thin_page_audit(slugs={slug})

    assert result["thin_pages"][0]["platform"] == "generic_fallback"
    assert result["agenda_link_only_by_platform"] == {"generic_fallback": 1}


async def test_agenda_text_characters_are_measured_not_guessed():
    """Ryan's framing: a real agenda's characters should exceed the apology
    text a contentless page renders anyway. The floor is measured from the
    templates (83 chars); this reports the real side of that comparison."""
    slug = await _seed(
        "thin:chars",
        agenda_items=[
            {"start": 0, "text": "Call to order"},
            {"start": 5, "text": "Adjourn"},
        ],
    )

    result = await crud.get_thin_page_audit(slugs={slug})

    assert result["apology_floor_chars"] == 83
    # Real agenda text -> has content, so it isn't thin at all.
    assert result["thin_pages"] == []
    assert result["counts"]["agenda_link_only"] == 0


async def test_audit_endpoint_returns_the_same_answer_over_http():
    slug = await _seed("thin:http", agenda_link="https://example.com/http.pdf")

    response = client.get(
        "/internal/thin-page-audit",
        params={"slugs": slug},
        headers={"Authorization": "Bearer test-token"},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["counts"]["agenda_link_only"] == 1
    assert data["thin_pages"][0]["slug"] == slug


# --- the two copies of the rule must agree -------------------------------


async def test_sql_predicate_and_python_twin_agree_on_every_shape():
    """crud._is_empty_page_condition() (SQL) vs archive/main.py's
    `page_is_empty` (Python). Exercised through their real surfaces: the
    default listing, which applies the SQL predicate, and the rendered /m/
    page, which applies the Python one. A shape they disagree on would be
    either noindexed-but-sitemapped or listed-but-noindexed."""
    shapes = {
        "agree:empty": {},
        "agree:linkonly": {"agenda_link": "https://example.com/x.pdf"},
        "agree:video": {
            "video_url": "https://example.com/x.m3u8",
            "video_format": "m3u8",
        },
        "agree:agenda": {"agenda_items": [{"start": 0, "text": "Call to order"}]},
        "agree:transcript": {
            "segments": [{"start": 0, "end": 1, "text": "hello"}],
            "transcript_language": "en",
        },
        "agree:link-plus-agenda": {
            "agenda_link": "https://example.com/y.pdf",
            "agenda_items": [{"start": 0, "text": "Roll call"}],
        },
    }

    listed = set()
    slugs = {}
    for external_id, overrides in shapes.items():
        slugs[external_id] = await _seed(external_id, **overrides)

    result = await crud.list_pages(jurisdiction=JX, page_size=100)
    listed = {p["slug"] for p in result["pages"]}

    for external_id, slug in slugs.items():
        page = client.get(f"/m/{slug}")
        assert page.status_code == 200, external_id
        python_says_empty = '<meta name="robots" content="noindex">' in page.text
        sql_says_empty = slug not in listed
        assert python_says_empty == sql_says_empty, (
            f"{external_id}: SQL says empty={sql_says_empty}, "
            f"Python says empty={python_says_empty}"
        )
