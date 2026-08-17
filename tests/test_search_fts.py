"""Search Step 2a -- Postgres full-text search in list_pages()
(archive/db/crud.py: _fts_available / _fts_condition / _fts_rank, Alembic
revision c1d2e3f4a5b6). Two layers:

1. Dialect-agnostic shape tests that run in every session (SQLite CI):
   the compiled SQL uses `@@ websearch_to_tsquery(...)` and never LIKE
   when FTS is available, and falls back to the LIKE path when it isn't
   -- with _fts_available() monkeypatched, since SQLite can never have
   the column.
2. Real-Postgres integration tests, skipped unless DATABASE_URL points at
   a Postgres with the full migration chain (incl. c1d2e3f4a5b6) applied
   -- same convention and same loop_scope reasoning as
   tests/test_list_pages_search_postgres.py. Verified 2026-08-17 against
   `docker run postgres:16` + `alembic upgrade head`.
"""

import os

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from archive.db import crud

pytestmark = pytest.mark.asyncio(loop_scope="session")

_PG = os.environ.get("DATABASE_URL", "").startswith(("postgres://", "postgresql"))


# --- 1. shape tests, any dialect ------------------------------------------


def test_fts_condition_compiles_to_websearch_tsquery_match():
    sql = str(
        select(crud.MeetingPage.id)
        .where(crud._fts_condition('budget "public comment" -flock'))
        .compile(dialect=postgresql.dialect())
    )
    assert "meeting_pages.search_tsv @@ websearch_to_tsquery" in sql, sql
    assert "LIKE" not in sql, sql
    assert "search_corpus" not in sql, sql  # never touches the corpus


def test_fts_rank_compiles_to_ts_rank_cd():
    sql = str(select(crud._fts_rank("budget")).compile(dialect=postgresql.dialect()))
    assert "ts_rank_cd(meeting_pages.search_tsv, websearch_to_tsquery" in sql, sql


async def test_list_pages_uses_like_path_when_fts_unavailable(monkeypatch):
    # On SQLite _fts_available() is always False; make that explicit and
    # confirm the LIKE fallback still finds a real ingested page.
    async def _no(_session):
        return False

    monkeypatch.setattr(crud, "_fts_available", _no)
    url = "https://example.granicus.com/player/clip/fts-fallback"
    await crud.ingest_resolution(
        {
            "platform": "granicus",
            "source_url": url,
            "external_id": "granicus:fts-fallback",
            "title": "FTS fallback",
            "date": "2026-01-01",
            "jurisdiction": "City of Ftsfallback",
            "video_url": "https://example.com/v.m3u8",
            "video_format": "m3u8",
            "segments": [{"start": 0, "end": 1, "text": "zzyzxfallback unique"}],
            "agenda_items": [],
            "transcript_language": "en",
            "transcript_warnings": [],
        },
        url,
    )
    slug = (await crud.lookup_page_for_url(url))["slug"]
    result = await crud.list_pages(keyword="zzyzxfallback", page_size=100)
    assert slug in [p["slug"] for p in result["pages"]]


async def test_fts_available_is_false_on_non_postgres_without_querying():
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

    assert await crud._fts_available(_Session()) is False


# --- 2. real Postgres -----------------------------------------------------

pg_only = pytest.mark.skipif(
    not _PG,
    reason="requires a real Postgres DATABASE_URL with revision c1d2e3f4a5b6 applied",
)


def _payload(eid: str, url: str, text: str, title: str = "FTS Meeting") -> dict:
    return {
        "platform": "granicus",
        "source_url": url,
        "external_id": f"granicus:{eid}",
        "title": title,
        "date": "2026-04-01",
        "jurisdiction": f"City of {eid.title()}",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [{"start": 0, "end": 1, "text": text}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }


async def _seed(eid: str, text: str, **kw) -> str:
    url = f"https://example.granicus.com/player/clip/{eid}"
    await crud.ingest_resolution(_payload(eid, url, text, **kw), url)
    return (await crud.lookup_page_for_url(url))["slug"]


async def _slugs(**kwargs) -> list[str]:
    return [
        p["slug"] for p in (await crud.list_pages(page_size=100, **kwargs))["pages"]
    ]


@pg_only
async def test_fts_column_is_detected_on_postgres():
    from archive.db.engine import async_session

    crud._fts_state.update({"available": None, "checked_at": None})
    async with async_session() as session:
        assert await crud._fts_available(session) is True


@pg_only
async def test_fts_stems_and_matches_words_not_substrings():
    a = await _seed(
        "fts-stem-a", "the council discussed budgets and budgeting at length"
    )
    b = await _seed("fts-stem-b", "we will concatenate the reports")  # contains 'cat'
    found = await _slugs(keyword="budget")
    assert a in found  # stemming: budget matches budgets/budgeting
    assert b not in await _slugs(keyword="cat")  # word match, not substring


@pg_only
async def test_fts_phrase_exclusion_and_or():
    a = await _seed("fts-ops-a", "public comment period opened at noon zqalpha")
    b = await _seed("fts-ops-b", "comment from the public arrived by mail zqbeta")
    phrase = await _slugs(keyword='"public comment"')
    assert a in phrase and b not in phrase
    excl = await _slugs(keyword="comment -noon")
    assert b in excl and a not in excl
    either = await _slugs(keyword="zqalpha OR zqbeta")
    assert a in either and b in either


@pg_only
async def test_fts_pagination_total_and_relevance_order():
    tag = "zqpaginate"
    heavy = await _seed("fts-rank-heavy", " ".join([tag] * 30) + " dense mention")
    light = await _seed("fts-rank-light", f"one {tag} mention only")
    for i in range(3):
        await _seed(f"fts-rank-{i}", f"{tag} row {i}")
    p1 = await crud.list_pages(keyword=tag, page_size=2, page=1)
    assert p1["total"] == 5 and p1["total_pages"] == 3
    ranked = await crud.list_pages(keyword=tag, page_size=10, sort="relevance")
    slugs = [p["slug"] for p in ranked["pages"]]
    assert slugs.index(heavy) < slugs.index(
        light
    )  # ts_rank_cd puts the dense doc first
    newest = await crud.list_pages(keyword=tag, page_size=10)  # default: newest first
    assert set(p["slug"] for p in newest["pages"]) == set(slugs)


@pg_only
async def test_fts_snippet_still_comes_from_default_segments():
    slug = await _seed("fts-snip", "the zqsnippet word appears in the transcript body")
    result = await crud.list_pages(keyword="zqsnippet", page_size=100)
    row = next(p for p in result["pages"] if p["slug"] == slug)
    assert row["snippet"] and "zqsnippet" in row["snippet"]
