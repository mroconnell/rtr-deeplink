"""HTTP-level tests for POST /internal/transcript-version/correct-text
(archive/main.py, WO-1964): fix a wrong word or name in one stored
segment. The motivating real case is "Grotten Hill" for Groton Hill on
a Whisper transcript (BACKLOG_DONE.md WO-1964); the pages below are
built through the ordinary ingest path, the same way the neighbouring
correct-language/correct-warnings tests build theirs.
"""

from fastapi.testclient import TestClient
from sqlalchemy import select

import archive.main
from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import MeetingPage, TranscriptVersion

client = TestClient(archive.main.app)
AUTH = {"Authorization": "Bearer test-token"}
ROUTE = "/internal/transcript-version/correct-text"


async def _make_page(key: str, segments: list) -> str:
    url = f"https://example.granicus.com/player/clip/{key}"
    await crud.ingest_resolution(
        {
            "platform": "granicus",
            "source_url": url,
            "external_id": f"granicus:{key}",
            "title": "Test Meeting",
            "date": "2026-01-01",
            "jurisdiction": "City of Test",
            "video_url": "https://example.com/v.m3u8",
            "video_format": "m3u8",
            "segments": segments,
            "agenda_items": [],
            "transcript_language": "en",
            "transcript_warnings": [],
        },
        url,
    )
    return (await crud.lookup_page_for_url(url))["slug"]


async def _corpus(session, page_id: int) -> str:
    corpus = (
        await session.execute(
            select(MeetingPage.search_corpus).where(MeetingPage.id == page_id)
        )
    ).scalar_one()
    return (corpus or "").lower()


def _body(slug, **kw):
    return {
        "slug": slug,
        "segment_index": 1,
        "old_text": "Grotten Hill",
        "new_text": "Groton Hill",
        **kw,
    }


def test_correct_text_rejects_missing_token():
    response = client.post(ROUTE, json=_body("whatever"))
    assert response.status_code == 404  # matches every other /internal/* route


def test_correct_text_404s_for_unknown_slug():
    response = client.post(ROUTE, json=_body("no-such-slug-at-all"), headers=AUTH)
    assert response.status_code == 404


async def test_correct_text_fixes_one_segment_and_records_the_change():
    slug = await _make_page(
        "wo1964-fix",
        [
            {"start": 0, "end": 1, "text": "Good evening."},
            {"start": 1, "end": 2, "text": "The Grotten Hill Music Center item."},
            {"start": 2, "end": 3, "text": "Next item."},
        ],
    )
    page = await crud.get_page_by_slug(slug)
    default_id = next(v["id"] for v in page["versions"] if v["is_default"])
    async with async_session() as session:
        v = await session.get(TranscriptVersion, default_id)
        hash_before = v.content_hash
        assert "grotten" in await _corpus(session, v.meeting_page_id)

    response = client.post(ROUTE, json=_body(slug), headers=AUTH)
    assert response.status_code == 200
    data = response.json()
    assert data["version_id"] == default_id
    assert data["text"] == "The Groton Hill Music Center item."
    assert len(data["corrections"]) == 1
    assert data["corrections"][0]["old"] == "Grotten Hill"
    assert data["corrections"][0]["new"] == "Groton Hill"
    assert data["corrections"][0]["at"]

    async with async_session() as session:
        version = await session.get(TranscriptVersion, default_id)
        assert version.segments[1]["text"] == "The Groton Hill Music Center item."
        assert version.segments[0] == {"start": 0, "end": 1, "text": "Good evening."}
        # Kept as ingested, so a re-push of the old text dedups here.
        assert version.content_hash == hash_before
        corpus = await _corpus(session, version.meeting_page_id)
        assert "groton" in corpus
        assert "grotten" not in corpus

    # A second change on the same segment appends to the record.
    response = client.post(
        ROUTE,
        json=_body(slug, old_text="Music Center", new_text="Music Centre"),
        headers=AUTH,
    )
    assert response.status_code == 200
    assert [c["new"] for c in response.json()["corrections"]] == [
        "Groton Hill",
        "Music Centre",
    ]


async def test_correct_text_refuses_when_old_text_is_missing_or_repeated():
    slug = await _make_page(
        "wo1964-refuse",
        [
            {"start": 0, "end": 1, "text": "Intro."},
            {"start": 1, "end": 2, "text": "Smith said Smith would."},
        ],
    )
    missing = client.post(ROUTE, json=_body(slug), headers=AUTH)
    assert missing.status_code == 409
    assert missing.json()["error"] == "old_text_not_found"

    repeated = client.post(
        ROUTE, json=_body(slug, old_text="Smith", new_text="Smyth"), headers=AUTH
    )
    assert repeated.status_code == 409
    assert repeated.json()["error"] == "old_text_not_unique"

    bad_index = client.post(
        ROUTE,
        json=_body(slug, segment_index=5, old_text="Intro", new_text="Opening"),
        headers=AUTH,
    )
    assert bad_index.status_code == 400

    empty = client.post(
        ROUTE, json=_body(slug, old_text="", new_text="x"), headers=AUTH
    )
    assert empty.status_code == 400

    page = await crud.get_page_by_slug(slug)
    default_id = next(v["id"] for v in page["versions"] if v["is_default"])
    async with async_session() as session:
        version = await session.get(TranscriptVersion, default_id)
        assert version.segments[1]["text"] == "Smith said Smith would."
        assert "corrections" not in version.segments[1]


async def test_correct_text_404s_for_version_of_another_page():
    slug_a = await _make_page(
        "wo1964-a", [{"start": 0, "end": 1, "text": "Grotten Hill"}]
    )
    slug_b = await _make_page(
        "wo1964-b", [{"start": 0, "end": 1, "text": "Grotten Hill"}]
    )
    page_b = await crud.get_page_by_slug(slug_b)
    other_id = page_b["versions"][0]["id"]
    response = client.post(
        ROUTE,
        json=_body(slug_a, segment_index=0, version_id=other_id),
        headers=AUTH,
    )
    assert response.status_code == 404
