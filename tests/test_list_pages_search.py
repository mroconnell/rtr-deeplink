"""Real DB integration test for list_pages()'s keyword search covering
every TranscriptVersion for a page, not just the default one -- a demoted
version (e.g. a garbled scraped caption superseded by a later AI
transcript) should still be findable even though it's no longer what the
listing displays. Against the isolated SQLite fixture DB, same pattern as
tests/test_transcription_jobs.py.
"""

from sqlalchemy import select

from archive.db import crud
from archive.db.engine import async_session
from archive.db.models import MeetingPage, TranscriptVersion


def _payload(external_id: str, source_url: str, *, segments, transcript_warnings=None) -> dict:
    return {
        "platform": "granicus",
        "source_url": source_url,
        "external_id": external_id,
        "title": "Demoted Version Search Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "City of Search Test",
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
        _payload("granicus:search-demoted", url, segments=[{"start": 0, "end": 1, "text": "zzyzxquokka unique term"}]),
        url,
    )

    async with async_session() as session:
        page = (await session.execute(select(MeetingPage).where(MeetingPage.source_url_normalized == url))).scalars().first()
        old_version = (
            await session.execute(select(TranscriptVersion).where(TranscriptVersion.meeting_page_id == page.id))
        ).scalars().first()

        # Add a second version and promote it -- demotes the one with our
        # unique keyword, matching what promote_transcript_version() does
        # when a fresh AI transcript supersedes an older one.
        new_version = TranscriptVersion(
            meeting_page_id=page.id, language="en", source="transcribed", is_default=False,
            segments=[{"start": 0, "end": 1, "text": "totally different replacement content"}],
            transcript_warnings=[], content_hash="not-a-real-hash",
        )
        session.add(new_version)
        await session.flush()
        await crud.promote_transcript_version(session, page.id, new_version.id)
        await session.commit()

        # Sanity check: the old version (with our keyword) is indeed demoted.
        await session.refresh(old_version)
        assert old_version.is_default is False

    result = await crud.list_pages(keyword="zzyzxquokka", page_size=50)
    assert any(p["slug"] == page.slug for p in result["pages"])


async def test_has_transcript_badge_is_quality_aware_not_just_presence():
    # A garbled default version shouldn't earn the same "Transcript"
    # badge on /meetings as a real one -- has_transcript must check
    # quality (the same _GARBLED_MARKER signal _has_good_transcript()
    # uses), not just "a TranscriptVersion row exists."
    garbled_url = "https://example.granicus.com/player/clip/list-garbled"
    await crud.ingest_resolution(
        _payload(
            "granicus:list-garbled", garbled_url,
            segments=[{"start": 0, "end": 1, "text": "??? garbled nonsense ???"}],
            transcript_warnings=["This transcript looks garbled at the source (not a parsing bug on our end)."],
        ),
        garbled_url,
    )

    good_url = "https://example.granicus.com/player/clip/list-good"
    await crud.ingest_resolution(_payload("granicus:list-good", good_url, segments=[{"start": 0, "end": 1, "text": "a real clean transcript"}]), good_url)

    result = await crud.list_pages(page_size=200)
    garbled_slug = (await crud.lookup_page_for_url(garbled_url))["slug"]
    good_slug = (await crud.lookup_page_for_url(good_url))["slug"]

    garbled_row = next(p for p in result["pages"] if p["slug"] == garbled_slug)
    good_row = next(p for p in result["pages"] if p["slug"] == good_slug)
    assert garbled_row["has_transcript"] is False
    assert good_row["has_transcript"] is True
