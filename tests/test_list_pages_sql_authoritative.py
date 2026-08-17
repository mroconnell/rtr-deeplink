"""list_pages() after the 2026-08-17 rewrite (see its docstring and
BACKLOG_DONE.md): every filter incl. exact keyword search runs in SQL
against MeetingPage.search_corpus, pagination is LIMIT/OFFSET + COUNT(*),
transcript JSON is loaded only for the returned page's snippets, and the
worker's transcription-completion path now refreshes the corpus. Real DB
integration against the shared SQLite fixture (tests/conftest.py) -- the
SQL path is dialect-agnostic now, so what passes here is the same code
prod runs, just unindexed. Every seed uses a unique jurisdiction/
external_id/source_url so the shared session DB can't collide (slugs
derive from jurisdiction+date+title, not external_id).
"""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import undefer

from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import MeetingPage

# One event loop for the whole file: archive.db.engine's asyncpg pool is
# created once at import and its connections are loop-bound, so per-test
# loops (pytest.ini's asyncio_mode=auto default) throw "attached to a
# different loop" when this file is run against a real Postgres -- see
# tests/test_list_pages_search_postgres.py's docstring for the full
# story. Harmless on SQLite/aiosqlite (CI), required for the manual
# Postgres verification run this file is also meant for.
pytestmark = pytest.mark.asyncio(loop_scope="session")

_TAG = "sqlauth"  # unique-token prefix so nothing else in the suite matches


def _payload(external_id: str, url: str, **overrides) -> dict:
    p = {
        "platform": "granicus",
        "source_url": url,
        "external_id": external_id,
        "title": f"{_TAG} Meeting",
        "date": "2026-02-01",
        "jurisdiction": f"City of {external_id.title()}",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": [{"start": 0, "end": 1, "text": f"{_TAG} default text"}],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": [],
    }
    p.update(overrides)
    return p


async def _seed(external_id: str, **overrides) -> str:
    url = f"https://example.granicus.com/player/clip/{external_id}"
    result = await crud.ingest_resolution(_payload(external_id, url, **overrides), url)
    return result["slug"]


async def _set_agenda_raw(slug: str, value) -> None:
    """Write agenda_items directly so we can produce every storage shape
    _has_agenda_condition() must treat as 'no agenda' (SQL NULL / JSON null /
    []) -- ingest itself only ever writes `[]` for an empty one."""
    async with async_session() as session:
        page = (
            (await session.execute(select(MeetingPage).where(MeetingPage.slug == slug)))
            .scalars()
            .one()
        )
        page.agenda_items = value
        await session.commit()


async def _slugs(**kwargs) -> list[str]:
    result = await crud.list_pages(page_size=100, **kwargs)
    return [p["slug"] for p in result["pages"]]


# --- exact keyword search is SQL-authoritative and matches every version ---


async def test_exact_search_matches_via_search_corpus_only():
    slug = await _seed(
        "sqlauth-exact",
        segments=[{"start": 0, "end": 1, "text": f"{_TAG}zebra unique word"}],
    )
    assert slug in await _slugs(keyword=f"{_TAG}zebra")
    assert slug not in await _slugs(keyword=f"{_TAG}zebrx")  # exact, not fuzzy


async def test_exact_search_still_finds_text_only_in_a_demoted_version():
    # First ingest carries the unique term; a second, different transcript
    # then becomes default and demotes it. The corpus spans every version,
    # so the page is still found -- and the snippet is None, never the
    # demoted text (real bug fixed 2026-08-08, preserved by the rewrite).
    eid = "sqlauth-demoted"
    url = f"https://example.granicus.com/player/clip/{eid}"
    slug = (
        await crud.ingest_resolution(
            _payload(
                eid,
                url,
                segments=[{"start": 0, "end": 1, "text": f"{_TAG}oldterm buried"}],
                transcript_warnings=["This transcript looks garbled at the source."],
            ),
            url,
        )
    )["slug"]
    second = await crud.ingest_resolution(
        _payload(
            eid,
            url,
            segments=[{"start": 0, "end": 1, "text": f"{_TAG}newterm replacement"}],
        ),
        url,
    )
    # Promote the second version explicitly (auto-promotion has its own
    # rules, not under test here) so the first one is definitely demoted.
    page = await crud.get_page_by_slug(slug)
    async with async_session() as session:
        await crud.promote_transcript_version(session, page["id"], second["version_id"])
        await session.commit()
    result = await crud.list_pages(keyword=f"{_TAG}oldterm", page_size=100)
    row = next(p for p in result["pages"] if p["slug"] == slug)
    assert row["snippet"] is None
    result2 = await crud.list_pages(keyword=f"{_TAG}newterm", page_size=100)
    row2 = next(p for p in result2["pages"] if p["slug"] == slug)
    assert row2["snippet"] is not None and f"{_TAG}newterm" in row2["snippet"]


async def test_exclusion_and_phrase_are_applied_in_sql():
    a = await _seed(
        "sqlauth-excl-a",
        segments=[{"start": 0, "end": 1, "text": f"{_TAG}alpha {_TAG}beta together"}],
    )
    b = await _seed(
        "sqlauth-excl-b",
        segments=[{"start": 0, "end": 1, "text": f"{_TAG}alpha alone here"}],
    )
    found = await _slugs(keyword=f"{_TAG}alpha -{_TAG}beta")
    assert b in found and a not in found
    phrase = await _slugs(keyword=f'"{_TAG}alpha {_TAG}beta"')
    assert a in phrase and b not in phrase


# --- has_agenda moved into SQL: all three "no agenda" storage shapes ---


async def test_has_agenda_sql_predicate_treats_null_jsonnull_and_empty_as_no_agenda():
    with_agenda = await _seed(
        "sqlauth-agenda-yes",
        agenda_items=[{"text": f"{_TAG} item one", "start": 0}],
    )
    empty = await _seed("sqlauth-agenda-empty")  # ingest writes []
    sql_null = await _seed("sqlauth-agenda-sqlnull")
    await _set_agenda_raw(sql_null, None)
    # A JSON `null` literal: SQLAlchemy stores Python None as JSON null by
    # default -- but _set_agenda_raw(None) above may land as SQL NULL
    # depending on dialect/flush path, so force the JSON literal explicitly.
    json_null = await _seed("sqlauth-agenda-jsonnull")
    from sqlalchemy import JSON

    await _set_agenda_raw(json_null, JSON.NULL)

    yes = await _slugs(has_agenda=True, keyword=_TAG)
    no = await _slugs(has_agenda=False, keyword=_TAG)
    assert with_agenda in yes
    for s in (empty, sql_null, json_null):
        assert s not in yes, s
        assert s in no, s
    assert with_agenda not in no


# --- pagination is SQL LIMIT/OFFSET with a real total ---


async def test_pagination_total_and_pages_are_consistent_across_pages():
    tag = f"{_TAG}paginate"
    slugs = [
        await _seed(
            f"sqlauth-page-{i}",
            date=f"2026-03-{i + 1:02d}",
            segments=[{"start": 0, "end": 1, "text": f"{tag} row {i}"}],
        )
        for i in range(7)
    ]
    p1 = await crud.list_pages(keyword=tag, page_size=3, page=1)
    p2 = await crud.list_pages(keyword=tag, page_size=3, page=2)
    p3 = await crud.list_pages(keyword=tag, page_size=3, page=3)
    assert p1["total"] == 7 and p1["total_pages"] == 3
    seen = [p["slug"] for r in (p1, p2, p3) for p in r["pages"]]
    assert len(seen) == 7 and len(set(seen)) == 7
    assert set(seen) == set(slugs)
    # Past the end: empty page, same total.
    p4 = await crud.list_pages(keyword=tag, page_size=3, page=4)
    assert p4["pages"] == [] and p4["total"] == 7


# --- fuzzy mode: Python over streamed corpus text, still tolerant ---


async def test_fuzzy_search_streams_corpus_and_still_tolerates_a_typo():
    slug = await _seed(
        "sqlauth-fuzzy",
        segments=[{"start": 0, "end": 1, "text": f"{_TAG} trafic calming measures"}],
    )
    # 'traffic' vs stored 'trafic' -- one edit on a 7-letter word.
    found = await _slugs(keyword=f"{_TAG} traffic", fuzzy=True)
    assert slug in found
    result = await crud.list_pages(keyword=f"{_TAG} traffic", fuzzy=True, page_size=100)
    row = next(p for p in result["pages"] if p["slug"] == slug)
    # Snippet quotes the real word from the source, not the query term.
    assert row["snippet"] is not None and "trafic" in row["snippet"]
    # Exact mode must NOT find it (that's the whole point of the flag).
    assert slug not in await _slugs(keyword=f"{_TAG} traffic", fuzzy=False)


async def test_fuzzy_mode_still_applies_exclusions_in_sql():
    a = await _seed(
        "sqlauth-fuzzy-excl-a",
        segments=[{"start": 0, "end": 1, "text": f"{_TAG}fzalpha {_TAG}fzbeta"}],
    )
    b = await _seed(
        "sqlauth-fuzzy-excl-b",
        segments=[{"start": 0, "end": 1, "text": f"{_TAG}fzalpha only"}],
    )
    found = await _slugs(keyword=f"{_TAG}fzalpha -{_TAG}fzbeta", fuzzy=True)
    assert b in found and a not in found


# --- the worker's completion path now refreshes the corpus ---


async def test_transcription_completion_refreshes_search_corpus():
    eid = "sqlauth-worker"
    url = f"https://example.granicus.com/player/clip/{eid}"
    job = await crud.create_transcription_job(
        payload=_payload(eid, url, segments=[]),
        input_url_normalized=url,
        requester_email="known@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=100,
        chunk_size_seconds=900,
        skip_confirmation=True,
    )
    claim = await crud.claim_next_chunk()
    assert claim is not None and claim["job_id"] == job["job_id"]
    unique = f"{_TAG}whisperword"
    done = await crud.report_chunk_result(
        job["job_id"],
        success=True,
        shifted_segments=[{"start": 0.0, "end": 2.0, "text": f"{unique} spoken"}],
    )
    assert done["status"] == "completed"
    slug = done["meeting_page_slug"]

    async with async_session() as session:
        page = (
            (
                await session.execute(
                    select(MeetingPage)
                    .options(undefer(MeetingPage.search_corpus))
                    .where(MeetingPage.slug == slug)
                )
            )
            .scalars()
            .one()
        )
        assert unique in (page.search_corpus or "")
    # ...and it's actually searchable, which is what the corpus is for.
    assert slug in await _slugs(keyword=unique)
