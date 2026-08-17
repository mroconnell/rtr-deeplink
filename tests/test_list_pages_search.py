"""Real DB integration test for list_pages()'s keyword search covering
every TranscriptVersion for a page, not just the default one -- a demoted
version (e.g. a garbled scraped caption superseded by a later AI
transcript) should still be findable even though it's no longer what the
listing displays. Against the isolated SQLite fixture DB, same pattern as
tests/test_transcription_jobs.py.
"""

from sqlalchemy import select
from sqlalchemy.orm import undefer

from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import MeetingPage, TranscriptVersion


def _payload(
    external_id: str,
    source_url: str,
    *,
    segments,
    transcript_warnings=None,
    jurisdiction="City of Search Test",
) -> dict:
    return {
        "platform": "granicus",
        "source_url": source_url,
        "external_id": external_id,
        "title": "Demoted Version Search Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": jurisdiction,
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": segments,
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": transcript_warnings or [],
    }


async def test_search_finds_keyword_in_demoted_non_default_version():
    url = "https://example.granicus.com/player/clip/search-demoted"

    # First ingest: real content, becomes the (only, so far) default version.
    await crud.ingest_resolution(
        _payload(
            "granicus:search-demoted",
            url,
            segments=[{"start": 0, "end": 1, "text": "zzyzxquokka unique term"}],
        ),
        url,
    )

    async with async_session() as session:
        page = (
            (
                await session.execute(
                    select(MeetingPage).where(MeetingPage.source_url_normalized == url)
                )
            )
            .scalars()
            .first()
        )
        old_version = (
            (
                await session.execute(
                    select(TranscriptVersion).where(
                        TranscriptVersion.meeting_page_id == page.id
                    )
                )
            )
            .scalars()
            .first()
        )

        # Add a second version and promote it -- demotes the one with our
        # unique keyword, matching what promote_transcript_version() does
        # when a fresh AI transcript supersedes an older one.
        new_version = TranscriptVersion(
            meeting_page_id=page.id,
            language="en",
            source="transcribed",
            is_default=False,
            segments=[
                {"start": 0, "end": 1, "text": "totally different replacement content"}
            ],
            transcript_warnings=[],
            content_hash="not-a-real-hash",
        )
        session.add(new_version)
        await session.flush()
        await crud.promote_transcript_version(session, page.id, new_version.id)
        await session.commit()

        # Sanity check: the old version (with our keyword) is indeed demoted.
        await session.refresh(old_version)
        assert old_version.is_default is False

    result = await crud.list_pages(keyword="zzyzxquokka", page_size=50)
    row = next(p for p in result["pages"] if p["slug"] == page.slug)

    # Real bug fixed 2026-08-08: the page is still found (matching runs
    # across every version, demoted or not), but the search-result
    # *snippet* must never surface the demoted version's stale text --
    # a viewer clicking through would never actually see it, since the
    # page itself only ever renders the current default version.
    assert row["snippet"] is None


async def test_list_pages_surfaces_a_split_meeting_body():
    # Display-layer wiring (2026-08-15, JURISDICTION_METADATA_PLAN.md):
    # list_pages() -- the /meetings listing's own query -- didn't select
    # MeetingPage.meeting_body at all before this, so a real entity-prefix
    # split (see test_ingest_promotion.py's Housing Authority of Santa
    # Clara case) was invisible on /meetings even though the individual
    # meeting page (get_page_by_slug()) already showed it.
    url = "https://example.granicus.com/player/clip/search-meeting-body"
    await crud.ingest_resolution(
        _payload(
            "granicus:search-meeting-body",
            url,
            segments=[{"start": 0, "end": 1, "text": "quorum present"}],
            jurisdiction="Housing Authority of the County of Santa Clara",
        ),
        url,
    )

    result = await crud.list_pages(keyword="quorum", page_size=50)
    row = next(
        p for p in result["pages"] if p["jurisdiction"] == "County of Santa Clara, CA"
    )
    assert row["meeting_body"] == "Housing Authority"


async def test_search_snippet_comes_from_the_current_default_version():
    url = "https://example.granicus.com/player/clip/search-snippet-default"
    await crud.ingest_resolution(
        _payload(
            "granicus:search-snippet-default",
            url,
            segments=[
                {"start": 0, "end": 1, "text": "a real quokka sighting downtown"}
            ],
        ),
        url,
    )

    result = await crud.list_pages(keyword="quokka", page_size=50)
    slug = (await crud.lookup_page_for_url(url))["slug"]
    row = next(p for p in result["pages"] if p["slug"] == slug)
    assert row["snippet"] is not None
    assert "quokka" in row["snippet"]


async def test_has_transcript_badge_is_quality_aware_not_just_presence():
    # A garbled default version shouldn't earn the same "Transcript"
    # badge on /meetings as a real one -- has_transcript must check
    # quality (the same _GARBLED_MARKER signal _has_good_transcript()
    # uses), not just "a TranscriptVersion row exists."
    garbled_url = "https://example.granicus.com/player/clip/list-garbled"
    await crud.ingest_resolution(
        _payload(
            "granicus:list-garbled",
            garbled_url,
            segments=[{"start": 0, "end": 1, "text": "??? garbled nonsense ???"}],
            transcript_warnings=[
                "This transcript looks garbled at the source (not a parsing bug on our end)."
            ],
        ),
        garbled_url,
    )

    good_url = "https://example.granicus.com/player/clip/list-good"
    await crud.ingest_resolution(
        _payload(
            "granicus:list-good",
            good_url,
            segments=[{"start": 0, "end": 1, "text": "a real clean transcript"}],
        ),
        good_url,
    )

    result = await crud.list_pages(page_size=200)
    garbled_slug = (await crud.lookup_page_for_url(garbled_url))["slug"]
    good_slug = (await crud.lookup_page_for_url(good_url))["slug"]

    garbled_row = next(p for p in result["pages"] if p["slug"] == garbled_slug)
    good_row = next(p for p in result["pages"] if p["slug"] == good_slug)
    assert garbled_row["has_transcript"] is False
    assert good_row["has_transcript"] is True


async def test_ingest_resolution_populates_search_corpus():
    # ingest_resolution() must write MeetingPage.search_corpus on every
    # ingest -- the write path is dialect-agnostic (unlike list_pages()'s
    # read path, which only uses this column on Postgres), so it's safe
    # and meaningful to assert against the SQLite test DB.
    url = "https://example.granicus.com/player/clip/search-corpus-write"
    await crud.ingest_resolution(
        _payload(
            "granicus:search-corpus-write",
            url,
            segments=[{"start": 0, "end": 1, "text": "zzyzxbanana unique corpus term"}],
            jurisdiction="City of Corpus Test",
        ),
        url,
    )

    async with async_session() as session:
        page = (
            (
                await session.execute(
                    select(MeetingPage)
                    .options(undefer(MeetingPage.search_corpus))
                    .where(MeetingPage.source_url_normalized == url)
                )
            )
            .scalars()
            .first()
        )
        assert page.search_corpus is not None
        assert "zzyzxbanana" in page.search_corpus
        assert "corpus test" in page.search_corpus.lower()


async def test_ingest_resolution_search_corpus_includes_every_version():
    # A second, later push (e.g. a re-transcription) that demotes the
    # first version must still leave the first version's text in
    # search_corpus -- same "every version counts" rule list_pages()'s
    # own keyword matching already relies on.
    url = "https://example.granicus.com/player/clip/search-corpus-multi-version"
    await crud.ingest_resolution(
        _payload(
            "granicus:search-corpus-multi-version",
            url,
            segments=[{"start": 0, "end": 1, "text": "zzyzxaardvark original term"}],
        ),
        url,
    )
    await crud.ingest_resolution(
        _payload(
            "granicus:search-corpus-multi-version",
            url,
            segments=[{"start": 0, "end": 1, "text": "zzyzxcapybara replacement term"}],
            transcript_warnings=[],
        ),
        url,
    )

    async with async_session() as session:
        page = (
            (
                await session.execute(
                    select(MeetingPage)
                    .options(undefer(MeetingPage.search_corpus))
                    .where(MeetingPage.source_url_normalized == url)
                )
            )
            .scalars()
            .first()
        )
        assert "zzyzxaardvark" in page.search_corpus
        assert "zzyzxcapybara" in page.search_corpus


def test_search_corpus_is_deferred_and_never_in_a_plain_meeting_page_select():
    # Load-bearing, not an optimization (see the column's comment in
    # archive/db/models.py): search_corpus holds every meeting's full
    # transcript text, and every `select(MeetingPage)` in crud.py -- incl.
    # list_pages()'s plain no-keyword browse behind /meetings -- would drag
    # all of it into memory just to list 20 titles. That is exactly what
    # OOM-crashed the production Archive on 2026-08-17 the moment the
    # backfill populated the column. Pin it at the SQL level: the compiled
    # default SELECT must not name the column at all.
    compiled = str(select(MeetingPage).compile())
    assert "search_corpus" not in compiled
    # ...while an explicit WHERE against it (list_pages()'s Postgres
    # pre-filter shape) still works -- deferral only affects the SELECT
    # list, never the column's usability in a predicate.
    filtered = str(
        select(MeetingPage.id).where(MeetingPage.search_corpus.ilike("%x%")).compile()
    )
    assert "search_corpus" in filtered
