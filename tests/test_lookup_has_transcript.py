"""Real DB integration tests for lookup_page_for_url()'s has_transcript
signal (archive/db/crud.py) -- used by app/main.py to pick the Archive
recheck cadence (1 hour for a page missing a good transcript, 30 days for
one that has one). Against the isolated SQLite fixture DB, not mocked,
same pattern as tests/test_transcription_jobs.py.
"""

from archive.db import crud


def _payload(
    external_id: str, source_url: str, *, segments=None, transcript_warnings=None
) -> dict:
    return {
        "platform": "granicus",
        "source_url": source_url,
        "external_id": external_id,
        "title": "Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "City of Test",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": segments or [],
        "agenda_items": [],
        "transcript_language": "en",
        "transcript_warnings": transcript_warnings or [],
    }


async def test_lookup_has_transcript_true_for_real_transcript():
    url = "https://example.granicus.com/player/clip/lookup-good"
    await crud.ingest_resolution(
        _payload(
            "granicus:lookup-good",
            url,
            segments=[{"start": 0, "end": 1, "text": "hello"}],
        ),
        url,
    )
    result = await crud.lookup_page_for_url(url)
    assert result is not None
    assert result["has_transcript"] is True


async def test_lookup_has_transcript_false_when_no_version():
    url = "https://example.granicus.com/player/clip/lookup-none"
    await crud.ingest_resolution(
        _payload("granicus:lookup-none", url, segments=[]), url
    )
    result = await crud.lookup_page_for_url(url)
    assert result is not None
    assert result["has_transcript"] is False


async def test_lookup_has_transcript_false_when_garbled():
    url = "https://example.granicus.com/player/clip/lookup-garbled"
    await crud.ingest_resolution(
        _payload(
            "granicus:lookup-garbled",
            url,
            segments=[{"start": 0, "end": 1, "text": "??? ??? ???"}],
            transcript_warnings=[
                "This transcript looks garbled at the source (not a parsing bug on our end)."
            ],
        ),
        url,
    )
    result = await crud.lookup_page_for_url(url)
    assert result is not None
    assert result["has_transcript"] is False
