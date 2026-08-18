"""Search Step 2b -- trigram-indexed vocabulary for fast fuzzy search in
list_pages() (archive/db/crud.py: _vocab_available / _vocab_candidate_stmt
/ _fuzzy_keyword_conditions_via_vocabulary, Alembic revision
c684908ce5ff). Same two-layer structure as tests/test_search_fts.py:

1. Dialect-agnostic shape/unit tests that run in every session (SQLite
   CI): the compiled candidate-lookup SQL uses the `%` trigram operator
   (never a bare, unindexed `similarity() > threshold`), _vocab_available()
   is a pure dialect gate on non-Postgres, and list_pages() falls back to
   the Python-streamed fuzzy path when the vocabulary table isn't
   available -- with _vocab_available() monkeypatched, since SQLite can
   never have the table queried.
2. Real-Postgres integration tests, skipped unless DATABASE_URL points at
   a Postgres with the full migration chain (incl. c684908ce5ff) applied
   -- same convention and loop_scope reasoning as
   tests/test_search_fts.py / tests/test_list_pages_search_postgres.py.
"""

import os

import pytest
from sqlalchemy import text
from sqlalchemy.dialects import postgresql

from archive.db import crud

pytestmark = pytest.mark.asyncio(loop_scope="session")

_PG = os.environ.get("DATABASE_URL", "").startswith(("postgres://", "postgresql"))


# --- 1. shape/unit tests, any dialect --------------------------------------


def test_vocab_candidate_stmt_compiles_to_trigram_similarity_operator():
    sql = str(
        crud._vocab_candidate_stmt("trafic", 50).compile(dialect=postgresql.dialect())
    )
    assert "search_vocabulary.word %%" in sql or "search_vocabulary.word %" in sql, sql
    assert "similarity(search_vocabulary.word" in sql, sql
    assert "ORDER BY" in sql, sql
    # Never a bare, unindexed threshold comparison -- the `%` operator
    # (reading pg_trgm.similarity_threshold) is what the GIN index
    # actually accelerates.
    assert "> " not in sql.split("ORDER BY")[0], sql


async def test_vocab_available_is_false_on_non_postgres_without_querying():
    # Pure dialect gate: a fake session whose bind says sqlite must return
    # False immediately (no execute call at all).
    class _Dialect:
        name = "sqlite"

    class _Bind:
        dialect = _Dialect()

    class _Session:
        bind = _Bind()

        async def execute(self, *_a, **_k):  # pragma: no cover - must not run
            raise AssertionError("must not query on sqlite")

    assert await crud._vocab_available(_Session()) is False


async def test_list_pages_uses_streamed_fuzzy_when_vocab_unavailable(monkeypatch):
    # On SQLite _vocab_available() is always False; make that explicit
    # and confirm the Python-streamed fuzzy fallback still finds a real
    # typo'd match, exactly as it did before this table existed.
    async def _no(_session):
        return False

    monkeypatch.setattr(crud, "_vocab_available", _no)
    url = "https://example.granicus.com/player/clip/vocab-fallback"
    await crud.ingest_resolution(
        {
            "platform": "granicus",
            "source_url": url,
            "external_id": "granicus:vocab-fallback",
            "title": "Vocab fallback",
            "date": "2026-01-01",
            "jurisdiction": "City of Vocabfallback",
            "video_url": "https://example.com/v.m3u8",
            "video_format": "m3u8",
            "segments": [
                {
                    "start": 0,
                    "end": 1,
                    "text": "the council discussed zzyzxtrafic today",
                }
            ],
            "agenda_items": [],
            "transcript_language": "en",
            "transcript_warnings": [],
        },
        url,
    )
    slug = (await crud.lookup_page_for_url(url))["slug"]
    result = await crud.list_pages(keyword="zzyzxtraffic", fuzzy=True, page_size=100)
    assert slug in [p["slug"] for p in result["pages"]]


# --- 2. real Postgres -------------------------------------------------------

pg_only = pytest.mark.skipif(
    not _PG,
    reason="requires a real Postgres DATABASE_URL with revision c684908ce5ff applied",
)


def _payload(eid: str, url: str, text: str, jurisdiction: str) -> dict:
    return {
        "platform": "granicus",
        "source_url": url,
        "external_id": f"granicus:{eid}",
        "title": "Vocab Fuzzy Test Meeting",
        "date": "2026-04-01",
        "jurisdiction": jurisdiction,
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [{"start": 0, "end": 1, "text": text}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }


async def _seed(eid: str, text: str, jurisdiction: str) -> str:
    url = f"https://example.granicus.com/player/clip/{eid}"
    await crud.ingest_resolution(_payload(eid, url, text, jurisdiction), url)
    return (await crud.lookup_page_for_url(url))["slug"]


@pg_only
async def test_vocab_table_is_detected_on_postgres():
    from archive.db.engine import async_session

    crud._vocab_state.update({"available": None, "checked_at": None})
    async with async_session() as session:
        assert await crud._vocab_available(session) is True


@pg_only
async def test_fuzzy_typo_matches_via_vocabulary_path():
    slug = await _seed(
        "vocab-typo",
        "the council discussed zzyzxtrafic calming near the school",
        "PG Vocab Typo City",
    )
    exact = await crud.list_pages(keyword="zzyzxtraffic", fuzzy=False, page_size=100)
    assert slug not in [p["slug"] for p in exact["pages"]]

    fuzzy = await crud.list_pages(keyword="zzyzxtraffic", fuzzy=True, page_size=100)
    assert slug in [p["slug"] for p in fuzzy["pages"]]


@pg_only
async def test_fuzzy_term_with_no_real_match_returns_zero_results():
    await _seed(
        "vocab-noise",
        "routine budget discussion nothing unusual",
        "PG Vocab Noise City",
    )
    # A term with no plausible real-word match anywhere in the archive --
    # the sql_false() branch in _fuzzy_keyword_conditions_via_vocabulary().
    result = await crud.list_pages(
        keyword="zzyzxqqqqqqqqqqnonexistentgibberish", fuzzy=True, page_size=100
    )
    assert result["total"] == 0
    assert result["pages"] == []


@pg_only
async def test_short_fuzzy_word_requires_exact_match_no_loose_expansion():
    # _fuzzy_threshold() gives <=4 char words zero tolerance -- confirms
    # the short-word branch skips vocabulary lookup and stays exact,
    # rather than loosely expanding into unrelated short words.
    slug = await _seed(
        "vocab-short", "the cars were parked near city hall", "PG Vocab Short City"
    )
    result = await crud.list_pages(keyword="cat", fuzzy=True, page_size=100)
    assert slug not in [p["slug"] for p in result["pages"]]

    exact_match = await crud.list_pages(keyword="cars", fuzzy=True, page_size=100)
    assert slug in [p["slug"] for p in exact_match["pages"]]


@pg_only
async def test_fuzzy_combined_with_phrase_and_exclusion():
    a = await _seed(
        "vocab-combo-a",
        "zzyzxbudgett review and public comment period",
        "PG Vocab Combo City A",
    )
    b = await _seed(
        "vocab-combo-b",
        "zzyzxbudgett review with no comment period at all",
        "PG Vocab Combo City B",
    )
    # Real budget-like vocabulary word must exist for the fuzzy expansion
    # to have something to find -- seed the correctly-spelled word too.
    await _seed(
        "vocab-combo-vocab-seed",
        "zzyzxbudget approved unanimously",
        "PG Vocab Combo City C",
    )

    found = await crud.list_pages(
        keyword='zzyzxbudgett "public comment"', fuzzy=True, page_size=100
    )
    slugs = [p["slug"] for p in found["pages"]]
    assert a in slugs
    assert b not in slugs


@pg_only
async def test_vocab_lookup_stays_fast_with_a_realistic_vocabulary_size():
    # Deliberately a timing check, not an EXPLAIN-plan-shape assertion --
    # this project already learned that lesson the hard way with
    # search_corpus (BACKLOG.md, 2026-08-17: "EXPLAIN (ANALYZE) said
    # 4.7s but pg_stat_statements under real load said 33s... trust real
    # measured behavior, not a single EXPLAIN"). A bare EXPLAIN run via a
    # bound parameter (asyncpg's extended protocol) can get a different,
    # more conservative *generic* plan than an ad-hoc literal query gets
    # -- confirmed manually while writing this test: the identical query
    # used the GIN index (ix_search_vocabulary_word_trgm, <1ms) when run
    # as a literal via psql, but showed a plan not naming the index when
    # run parameterized. What actually matters for this feature -- and
    # what's structurally different from search_corpus's own problem --
    # is that search_vocabulary holds distinct *words*, not per-meeting
    # transcript text, so even its worst-case fallback plan scans a small,
    # bounded table (thousands of short strings), not gigabytes of TOASTed
    # transcript JSON. Confirm that directly: a real fuzzy search through
    # the actual list_pages() path stays fast with a realistic-sized
    # vocabulary, regardless of which specific plan Postgres picks.
    import time

    from archive.db.engine import async_session

    async with async_session() as session:
        await crud._upsert_vocabulary_words(
            session, {f"zzyzxsynthetic{i}word" for i in range(5000)}
        )
        await session.commit()
        await session.execute(text("ANALYZE search_vocabulary"))
        await session.commit()

    slug = await _seed(
        "vocab-timing",
        "the council discussed zzyzxtimingword calming",
        "PG Vocab Timing City",
    )

    # Correctness (no real match vs. a real typo'd match) is already
    # covered by the two dedicated tests above -- this is purely a timing
    # check, run twice to rule out a one-off cold-cache fluke.
    for _ in range(2):
        start = time.monotonic()
        result = await crud.list_pages(
            keyword="zzyzxtimingwrod", fuzzy=True, page_size=100
        )
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, (
            f"fuzzy search took {elapsed:.3f}s against a 5000+ word vocabulary"
        )
        assert slug in [p["slug"] for p in result["pages"]]
