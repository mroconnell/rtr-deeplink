"""GET /internal/export/pages + crud.list_pages_for_export() (WO-93): the
read-only, keyset-paginated bulk export behind the data-product sample
scripts in rtr-business. Real DB integration against the isolated SQLite
fixture (same pattern as tests/test_backfill_page_urls.py); the test DB is
shared across modules, so every assertion finds its own rows by
source_url_normalized rather than assuming the table is empty.
"""

from fastapi.testclient import TestClient

import archive.main
from archive.db import crud

client = TestClient(archive.main.app)
AUTH = {"Authorization": "Bearer test-token"}

_SEGMENTS = [
    {"start": 0.0, "end": 4.5, "text": "Call to order."},
    {"start": 4.5, "end": 9.0, "text": "Roll call."},
]


def _payload(
    external_id: str, source_url: str, *, segments=None, platform="granicus"
) -> dict:
    return {
        "platform": platform,
        "source_url": source_url,
        "external_id": external_id,
        "title": "Export Test Meeting",
        "date": "2026-08-20",
        # Deliberately no ", ST" suffix: the shared test DB is never reset,
        # and tests/test_state_pages.py asserts on which states have pages
        # (Wyoming is reserved as the empty one), so a stateful fixture
        # here would leak into that module's counts.
        "jurisdiction": "Export Test Authority",
        "meeting_body": "City Council",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": _SEGMENTS if segments is None else segments,
        "agenda_items": [{"start": 0.0, "end": 60.0, "text": "1. Consent calendar"}],
        "transcript_language": "en",
        "transcript_warnings": [],
        "agenda_link": "https://example.com/agenda.pdf",
    }


def _walk(**params) -> list[dict]:
    """Every page the endpoint returns, following next_after_id to the end."""
    pages: list[dict] = []
    after_id = 0
    while True:
        r = client.get(
            "/internal/export/pages",
            params={**params, "after_id": after_id},
            headers=AUTH,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        pages.extend(body["pages"])
        if body["next_after_id"] is None:
            return pages
        assert body["next_after_id"] > after_id
        after_id = body["next_after_id"]


def _find(pages: list[dict], url: str) -> dict:
    match = [p for p in pages if p["source_url_normalized"] == url]
    assert len(match) == 1, f"expected exactly one page for {url}, got {len(match)}"
    return match[0]


def test_export_requires_token_and_hides_itself():
    assert client.get("/internal/export/pages").status_code == 404
    assert (
        client.get(
            "/internal/export/pages", headers={"Authorization": "Bearer wrong"}
        ).status_code
        == 404
    )


async def test_export_returns_metadata_and_light_versions_without_segments():
    url = "https://example.granicus.com/player/clip/export-1"
    await crud.ingest_resolution(_payload("export:1", url), url)

    page = _find(_walk(limit=500), url)
    assert page["platform"] == "granicus"
    assert "Export Test" in page["jurisdiction"]
    assert page["meeting_body"] == "City Council"
    assert page["agenda_items"] == [
        {"start": 0.0, "end": 60.0, "text": "1. Consent calendar"}
    ]
    assert page["agenda_link"] == "https://example.com/agenda.pdf"
    assert page["created_at"][4] == "-" and page["created_at"][10] == "T"
    # Light shape: version summaries with a SQL-side count, no blob.
    assert "default_version_segments" not in page
    assert len(page["versions"]) == 1
    version = page["versions"][0]
    assert version["is_default"] is True
    assert version["source"] == "sourced"
    assert version["segment_count"] == 2
    assert version["language"] == "en"
    assert "segments" not in version


async def test_export_include_segments_returns_the_default_versions_segments():
    url = "https://example.granicus.com/player/clip/export-2"
    await crud.ingest_resolution(_payload("export:2", url), url)

    page = _find(_walk(limit=100, include_segments="true"), url)
    assert page["default_version_segments"] == _SEGMENTS


async def test_export_paginates_by_id_without_gaps_or_duplicates():
    for i in range(3):
        url = f"https://example.granicus.com/player/clip/export-page-{i}"
        await crud.ingest_resolution(_payload(f"export:page:{i}", url), url)

    pages = _walk(limit=2)
    ids = [p["id"] for p in pages]
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))
    for i in range(3):
        _find(pages, f"https://example.granicus.com/player/clip/export-page-{i}")

    # A single request honours limit and reports a cursor when full.
    r = client.get("/internal/export/pages", params={"limit": 2}, headers=AUTH)
    body = r.json()
    assert len(body["pages"]) == 2
    assert body["next_after_id"] == body["pages"][-1]["id"]


def test_export_caps_limit_lower_when_segments_are_included():
    assert (
        client.get(
            "/internal/export/pages", params={"limit": 5000}, headers=AUTH
        ).json()["limit"]
        == 500
    )
    assert (
        client.get(
            "/internal/export/pages",
            params={"limit": 5000, "include_segments": "true"},
            headers=AUTH,
        ).json()["limit"]
        == 100
    )


async def test_export_created_after_filters_on_ingest_time():
    url = "https://example.granicus.com/player/clip/export-created-after"
    await crud.ingest_resolution(_payload("export:created-after", url), url)

    assert _walk(limit=500, created_after="2000-01-01") and _find(
        _walk(limit=500, created_after="2000-01-01"), url
    )
    assert not [
        p
        for p in _walk(limit=500, created_after="2999-01-01T00:00:00+00:00")
        if p["source_url_normalized"] == url
    ]
    r = client.get(
        "/internal/export/pages", params={"created_after": "not-a-date"}, headers=AUTH
    )
    assert r.status_code == 400


async def test_export_has_transcript_filter_uses_the_default_version():
    with_url = "https://example.granicus.com/player/clip/export-has-transcript"
    without_url = "https://example.granicus.com/player/clip/export-no-transcript"
    await crud.ingest_resolution(_payload("export:has", with_url), with_url)
    await crud.ingest_resolution(
        _payload("export:has-not", without_url, segments=[]), without_url
    )

    with_pages = _walk(limit=500, has_transcript="true")
    _find(with_pages, with_url)
    assert not [p for p in with_pages if p["source_url_normalized"] == without_url]

    without_pages = _walk(limit=500, has_transcript="false")
    _find(without_pages, without_url)
    assert not [p for p in without_pages if p["source_url_normalized"] == with_url]


async def test_export_never_exposes_account_or_derived_fields():
    url = "https://example.granicus.com/player/clip/export-fields"
    await crud.ingest_resolution(_payload("export:fields", url), url)
    page = _find(_walk(limit=500), url)
    forbidden = {
        "search_corpus",
        "requester_email",
        "clerk_user_id",
        "email",
        "reviewed_at",
        "confirmation_token",
    }
    assert not forbidden & set(page)
    assert set(page) == {
        "id",
        "slug",
        "platform",
        "external_id",
        "source_url_normalized",
        "title",
        "date",
        "jurisdiction",
        "meeting_body",
        "jurisdiction_confidence",
        # WO-99: the identity, its type, and what kind of event the page
        # is. Asserted here on purpose -- this test exists to catch a
        # column being added to the model and left out of the hand-built
        # export dict, which has happened before.
        "gov_id",
        "gov_type",
        "meeting_kind",
        "video_url",
        "video_format",
        "agenda_items",
        "video_warnings",
        "agenda_link",
        "packet_link",
        "best_effort",
        "created_at",
        "updated_at",
        "versions",
    }


async def test_export_ids_restricts_to_the_requested_pages():
    urls = [
        f"https://example.granicus.com/player/clip/export-ids-{i}" for i in range(3)
    ]
    for i, url in enumerate(urls):
        await crud.ingest_resolution(_payload(f"export:ids:{i}", url), url)
    everything = _walk(limit=500)
    wanted = [_find(everything, urls[0])["id"], _find(everything, urls[2])["id"]]

    r = client.get(
        "/internal/export/pages",
        params={"ids": ",".join(map(str, wanted)), "include_segments": "true"},
        headers=AUTH,
    )
    assert r.status_code == 200
    got = r.json()["pages"]
    assert [p["id"] for p in got] == sorted(wanted)
    assert all(p["default_version_segments"] == _SEGMENTS for p in got)
    assert r.json()["next_after_id"] is None

    assert (
        client.get(
            "/internal/export/pages", params={"ids": "1,x"}, headers=AUTH
        ).status_code
        == 400
    )
    too_many = ",".join(str(i) for i in range(1, 102))
    assert (
        client.get(
            "/internal/export/pages", params={"ids": too_many}, headers=AUTH
        ).status_code
        == 400
    )
