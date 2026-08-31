"""Tests for GET /internal/jurisdiction/missing (archive/main.py) and the
crud.get_missing_jurisdiction_summary() audit behind it -- added
2026-08-31 to close a real gap: every other jurisdiction endpoint in
this file queries `WHERE jurisdiction IS NOT NULL` by construction, so
"which pages have no jurisdiction at all" had no repeatable answer
short of a one-off DB query.

Real DB integration against the isolated SQLite file from
tests/conftest.py's _archive_db_schema fixture, driven through the real
POST /internal/ingest HTTP surface, same convention as
tests/test_low_trust_pages.py. That shared session-scoped DB is never
reset between tests, so assertions look up a specific platform's sample
by its own unique slug rather than asserting on totals.
"""

from fastapi.testclient import TestClient

import archive.main

client = TestClient(archive.main.app)

_AUTH = {"Authorization": "Bearer test-token"}


def _payload(**overrides) -> dict:
    payload = {
        "platform": "granicus",
        "source_url": "https://example.granicus.com/player/clip/missing-jurisdiction",
        "external_id": None,
        "title": "City Council Regular Meeting",
        "date": "2026-08-01",
        "jurisdiction": None,
        "video_url": "https://example.com/video.m3u8",
        "video_format": "m3u8",
        "segments": [{"start": 0.0, "end": 1.0, "text": "Call to order"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }
    payload.update(overrides)
    return payload


def _ingest(payload: dict) -> dict:
    body = dict(payload)
    body["input_url_normalized"] = payload["source_url"]
    response = client.post("/internal/ingest", json=body, headers=_AUTH)
    assert response.status_code == 200, response.text
    return response.json()


def _fetch(**params) -> dict:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = "/internal/jurisdiction/missing"
    if query:
        url += f"?{query}"
    response = client.get(url, headers=_AUTH)
    assert response.status_code == 200, response.text
    return response.json()


def _platform_row(data: dict, platform: str) -> dict | None:
    for row in data["by_platform"]:
        if row["platform"] == platform:
            return row
    return None


# --- auth -----------------------------------------------------------------


def test_rejects_missing_token():
    assert client.get("/internal/jurisdiction/missing").status_code == 404


def test_rejects_wrong_token():
    response = client.get(
        "/internal/jurisdiction/missing", headers={"Authorization": "Bearer nope"}
    )
    assert response.status_code == 404


# --- grouping and sampling --------------------------------------------------


def test_page_with_no_jurisdiction_appears_grouped_by_platform():
    slug = _ingest(
        _payload(
            platform="__test_missing_jur_platform_a",
            source_url="https://example.granicus.com/player/clip/missing-a",
        )
    )["slug"]

    data = _fetch()
    row = _platform_row(data, "__test_missing_jur_platform_a")
    assert row is not None
    assert row["count"] >= 1
    assert slug in row["sample_slugs"]


def test_page_with_a_real_jurisdiction_is_excluded():
    # Deliberately NOT a real place name like "Dublin, CA" -- the shared
    # session-scoped DB means any real jurisdiction string used elsewhere
    # (test_state_pages.py's own fixtures, in this case) would inflate a
    # count or ranking a different, unrelated test depends on being
    # exact (confirmed live: this exact collision broke
    # test_state_page_lists_states_jurisdictions). Only non-null-ness
    # matters here, not real-place validity.
    slug = _ingest(
        _payload(
            platform="__test_missing_jur_platform_b",
            source_url="https://example.granicus.com/player/clip/has-jurisdiction",
            jurisdiction="__Test Jurisdiction Not A Real Place__",
        )
    )["slug"]

    data = _fetch()
    row = _platform_row(data, "__test_missing_jur_platform_b")
    # This platform has zero missing-jurisdiction rows, so it shouldn't
    # appear in the grouping at all -- the group-by only ever surfaces
    # platforms that actually have a match.
    assert row is None or slug not in row["sample_slugs"]


def test_sample_size_is_honored_and_capped():
    for i in range(3):
        _ingest(
            _payload(
                platform="__test_missing_jur_platform_c",
                source_url=f"https://example.granicus.com/player/clip/missing-c-{i}",
            )
        )

    data = _fetch(sample_size=2)
    row = _platform_row(data, "__test_missing_jur_platform_c")
    assert row is not None
    assert row["count"] >= 3
    assert len(row["sample_slugs"]) == 2

    # Way over the cap collapses to the documented max, not an error.
    data = _fetch(sample_size=99999)
    assert data["sample_size"] == 50


def test_total_missing_and_response_shape():
    data = _fetch()
    assert isinstance(data["total_missing"], int)
    assert data["total_missing"] >= 1
    assert isinstance(data["by_platform"], list)
    for row in data["by_platform"]:
        assert set(row.keys()) == {"platform", "count", "sample_slugs"}
