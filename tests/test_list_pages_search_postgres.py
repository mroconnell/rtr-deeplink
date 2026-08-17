"""Postgres-only coverage for list_pages()'s indexed keyword-search path
(archive/db/crud.py's _keyword_conditions(), née _keyword_conditions_postgres
-- as of the 2026-08-17 Step 1 rewrite the same SQL runs on SQLite too, so
tests/test_list_pages_search.py, tests/test_list_pages_sql_authoritative.py
and tests/test_archive_search.py already exercise the query shape in every
normal session; this file exists to run it against a real Postgres, i.e.
with the pg_trgm GIN index and Postgres's own ILIKE/JSON semantics, which
CI (SQLite-only, see .github/workflows/test.yml) doesn't provide.

Skipped entirely unless DATABASE_URL points at a real Postgres instance.
The target database must already have `alembic upgrade head` applied
(this repo's migration set, including the one that adds
MeetingPage.search_corpus + the pg_trgm extension/GIN index) -- this file
doesn't run migrations itself, same assumption tests/conftest.py's
_archive_db_schema fixture already makes for the SQLite case (it only
ever calls create_all(), never Alembic).

Usage:
    DATABASE_URL=postgresql+asyncpg://... python -m pytest tests/test_list_pages_search_postgres.py -v

Manually verified 2026-08-17 against a real postgres:16 container with
this repo's full migration chain applied -- all four cases below passed.
"""

import os

import pytest

from archive.db import crud

pytestmark = [
    pytest.mark.skipif(
        not os.environ.get("DATABASE_URL", "").startswith(
            ("postgres://", "postgresql")
        ),
        reason="requires a real Postgres DATABASE_URL with the search_corpus "
        "migration applied -- not run in CI (SQLite-only, see "
        ".github/workflows/test.yml)",
    ),
    # Real bug hit writing this file (2026-08-17): pytest.ini's
    # `asyncio_mode = auto` gives every test function its own event loop
    # by default, but archive.db.engine builds one asyncpg connection
    # pool at *module import* time, shared across the whole session (same
    # pool tests/conftest.py's session-scoped _archive_db_schema fixture
    # already relies on). asyncpg connections are bound to the loop that
    # created them -- reusing a pooled connection from a previous test's
    # now-closed loop threw "Event loop is closed"/"attached to a
    # different loop" errors here, non-deterministically depending on
    # pool reuse order. SQLite/aiosqlite never hits this (no loop-bound
    # connection objects), which is exactly why nothing surfaced it until
    # this repo's first real Postgres-backed test file. loop_scope
    # matches every test in this file to one event loop for the whole
    # session, same as the engine's own connection pool.
    pytest.mark.asyncio(loop_scope="session"),
]


def _payload(external_id: str, source_url: str, *, segments, jurisdiction: str) -> dict:
    # jurisdiction is required (not defaulted) and must be unique per test
    # -- slugs are built from jurisdiction+date+title (build_base_slug),
    # NOT from external_id/source_url, so reusing a jurisdiction across
    # these tests would make lookup_page_for_url() the only reliable way
    # to find a specific page back (which we use anyway, but distinct
    # jurisdictions keep failure output readable).
    return {
        "platform": "granicus",
        "source_url": source_url,
        "external_id": external_id,
        "title": "Postgres Search Path Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": jurisdiction,
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": segments,
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }


async def _slug_for(url: str) -> str:
    return (await crud.lookup_page_for_url(url))["slug"]


async def test_exact_keyword_search_uses_indexed_ilike_narrowing():
    url = "https://example.granicus.com/player/clip/pg-search-exact"
    await crud.ingest_resolution(
        _payload(
            "granicus:pg-search-exact",
            url,
            segments=[
                {"start": 0, "end": 1, "text": "zzyzxpelican traffic discussion"}
            ],
            jurisdiction="PG Exact Search City",
        ),
        url,
    )
    slug = await _slug_for(url)

    matched = await crud.list_pages(keyword="zzyzxpelican", page_size=50)
    assert any(p["slug"] == slug for p in matched["pages"])

    unmatched = await crud.list_pages(keyword="zzyzxnonexistentterm", page_size=50)
    assert not any(p["slug"] == slug for p in unmatched["pages"])


async def test_excluded_word_is_filtered_out_in_sql():
    url = "https://example.granicus.com/player/clip/pg-search-exclude"
    await crud.ingest_resolution(
        _payload(
            "granicus:pg-search-exclude",
            url,
            segments=[{"start": 0, "end": 1, "text": "zzyzxheron budget discussion"}],
            jurisdiction="PG Exclude Search City",
        ),
        url,
    )
    slug = await _slug_for(url)

    excluded = await crud.list_pages(keyword="zzyzxheron -budget", page_size=50)
    assert not any(p["slug"] == slug for p in excluded["pages"])

    not_excluded = await crud.list_pages(keyword="zzyzxheron -parking", page_size=50)
    assert any(p["slug"] == slug for p in not_excluded["pages"])


async def test_quoted_phrase_requires_adjacent_match():
    url = "https://example.granicus.com/player/clip/pg-search-phrase"
    await crud.ingest_resolution(
        _payload(
            "granicus:pg-search-phrase",
            url,
            segments=[
                {"start": 0, "end": 1, "text": "zzyzxotter calming measures downtown"}
            ],
            jurisdiction="PG Phrase Search City",
        ),
        url,
    )
    slug = await _slug_for(url)

    adjacent = await crud.list_pages(keyword='"zzyzxotter calming"', page_size=50)
    assert any(p["slug"] == slug for p in adjacent["pages"])

    reversed_order = await crud.list_pages(keyword='"calming zzyzxotter"', page_size=50)
    assert not any(p["slug"] == slug for p in reversed_order["pages"])


async def test_fuzzy_word_similarity_narrowing_catches_a_real_typo():
    # The regression risk word_similarity() (not similarity()) exists to
    # avoid: comparing the whole corpus against a short word with plain
    # similarity() is dominated by corpus length and matches almost
    # nothing. This confirms the SQL narrowing step doesn't strip out a
    # genuine typo'd match before matches(fuzzy=True) ever sees it.
    url = "https://example.granicus.com/player/clip/pg-search-fuzzy"
    await crud.ingest_resolution(
        _payload(
            "granicus:pg-search-fuzzy",
            url,
            segments=[
                {
                    "start": 0,
                    "end": 1,
                    "text": "the council discussed zzyzxtrafic calming near the school",
                }
            ],
            jurisdiction="PG Fuzzy Search City",
        ),
        url,
    )
    slug = await _slug_for(url)

    exact = await crud.list_pages(keyword="zzyzxtraffic", fuzzy=False, page_size=50)
    assert not any(p["slug"] == slug for p in exact["pages"])

    fuzzy = await crud.list_pages(keyword="zzyzxtraffic", fuzzy=True, page_size=50)
    assert any(p["slug"] == slug for p in fuzzy["pages"])
