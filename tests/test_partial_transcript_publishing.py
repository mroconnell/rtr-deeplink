"""A terminally-failed transcription job publishes the chunks it finished.

Before 2026-08-24 it published nothing: `report_chunk_result()` only wrote
a TranscriptVersion once `chunks_completed >= total_chunks`, so a job that
died at 18 of 20 left eighteen chunks of real, correctly-timestamped
transcript stranded in `TranscriptionJob.partial_segments` while the page
it belonged to showed nothing at all and got re-queued to redo work
already done.

Publishing it is only safe because of three properties, and each of these
tests guards one of them -- get any wrong and this feature becomes a bug
worse than the gap it closes:

* the version is **marked**, so the page still reports as a problem and
  stays eligible for a real retry (rather than looking finished forever);
* the job stays **failed**, so `_cooldown_active()`'s escalating backoff
  still applies -- the only thing stopping a page that reliably dies at
  chunk 18 from republishing the same 18 chunks on a loop, which is
  exactly the infinite re-queue shape fixed for blank transcripts the day
  before this;
* it **never displaces a better transcript** that is already there.

Real-DB integration against the isolated SQLite fixture (same pattern and
same unique-external_id discipline as tests/test_transcription_jobs.py).
"""

from archive.db import crud

_SEGMENTS = [
    {"start": 0.0, "end": 6.0, "text": "Calling the meeting to order."},
    {"start": 6.0, "end": 14.0, "text": "First item is the budget amendment."},
]


def _payload(external_id: str, source_url: str, *, segments=None) -> dict:
    return {
        "platform": "granicus",
        "source_url": source_url,
        "external_id": external_id,
        "title": "Partial Publishing Test Meeting",
        "date": "2026-01-01",
        "jurisdiction": "City of Partialtest",
        "video_url": "https://example.com/v.m3u8",
        "video_format": "m3u8",
        "segments": segments or [],
        "agenda_items": [],
        "transcript_language": "en" if segments else None,
        "transcript_warnings": [],
    }


async def _job_that_dies_after(
    slug_key: str,
    *,
    good_chunks: int,
    total_seconds: int = 2700,
    chunk_seconds: int = 900,
    priority: int = crud.PRIORITY_LOW,
    existing_segments=None,
) -> dict:
    """Run `good_chunks` real chunks, then fail the next one until the job
    gives up. PRIORITY_LOW by default because a low-priority job goes
    straight to terminal `failed` -- a user-priority one burns three
    reschedules first, which is a different code path (covered below)."""
    url = f"https://example.granicus.com/player/clip/{slug_key}"
    if existing_segments:
        # create_transcription_job() only finds-or-creates the MeetingPage
        # (_find_or_create_page); it never writes TranscriptVersions. So a
        # page that is supposed to *already* have real captions has to be
        # ingested properly first, or the "don't displace" test would pass
        # vacuously against a page with no transcript at all.
        await crud.ingest_resolution(
            _payload(f"granicus:{slug_key}", url, segments=existing_segments), url
        )
    job = await crud.create_transcription_job(
        payload=_payload(f"granicus:{slug_key}", url, segments=existing_segments),
        input_url_normalized=url,
        requester_email="partial@example.com",
        media_url="https://example.com/v.m3u8",
        media_kind="video",
        probed_duration_seconds=total_seconds,
        chunk_size_seconds=chunk_seconds,
        skip_confirmation=True,
        priority=priority,
    )
    job_id = job["job_id"]
    for index in range(good_chunks):
        assert await crud.claim_next_chunk() is not None
        await crud.report_chunk_result(
            job_id,
            success=True,
            shifted_segments=[
                {
                    "start": index * chunk_seconds + seg["start"],
                    "end": index * chunk_seconds + seg["end"],
                    "text": seg["text"],
                }
                for seg in _SEGMENTS
            ],
        )
    result = {}
    for _ in range(crud.MAX_CONSECUTIVE_CHUNK_FAILURES):
        assert await crud.claim_next_chunk() is not None
        result = await crud.report_chunk_result(
            job_id, success=False, error="ffmpeg timed out after 120s"
        )
    return {"job_id": job_id, "page_id": await _page_id(job_id), **result}


async def _page_id(job_id: int) -> int:
    from archive.db.engine import async_session
    from archive.db.models import TranscriptionJob

    async with async_session() as session:
        return (await session.get(TranscriptionJob, job_id)).meeting_page_id


async def _default_version(page_id: int):
    from sqlalchemy import select

    from archive.db.engine import async_session
    from archive.db.models import TranscriptVersion

    async with async_session() as session:
        return (
            await session.execute(
                select(TranscriptVersion).where(
                    TranscriptVersion.meeting_page_id == page_id,
                    TranscriptVersion.is_default.is_(True),
                )
            )
        ).scalar_one_or_none()


async def _version_count(page_id: int) -> int:
    from sqlalchemy import func, select

    from archive.db.engine import async_session
    from archive.db.models import TranscriptVersion

    async with async_session() as session:
        return int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(TranscriptVersion)
                    .where(TranscriptVersion.meeting_page_id == page_id)
                )
            ).scalar_one()
        )


# --- the happy path this whole change exists for -------------------------


async def test_a_dead_job_publishes_the_chunks_it_finished():
    outcome = await _job_that_dies_after("pp-publishes", good_chunks=2)

    assert outcome["status"] == "failed"
    assert outcome["partial_transcript_version_id"] is not None

    version = await _default_version(outcome["page_id"])
    assert version is not None
    # Two chunks x two segments, timestamps already full-meeting-relative.
    assert len(version.segments) == 4
    assert version.segments[-1]["start"] == 900 + 6.0
    assert version.source == "transcribed"


async def test_the_warning_names_its_own_coverage():
    # 2 of 3 chunks at 900s each, on a 2700s meeting -> "30 minutes of a
    # 45 minute meeting". The point of the sentence is that a transcript
    # which just stops reads as broken; one that says where it stops does
    # not.
    outcome = await _job_that_dies_after("pp-coverage", good_chunks=2)
    version = await _default_version(outcome["page_id"])
    warning = version.transcript_warnings[0]

    assert warning == (
        "This transcript covers 30 minutes of a 45 minute meeting — "
        "the transcription was interrupted before we could finish it. "
        # Deliberately no "soon" -- see the constant's own comment: the
        # retry backoff reaches 30 days on exactly the pages that fail
        # most, and this string is stored once and never revised.
        "We'll try to finish it again."
    )


# --- the three properties that keep this from being a bug ----------------


async def test_the_published_partial_is_not_treated_as_a_good_transcript():
    """The load-bearing one. A marked version must keep the page reporting
    as a problem and keep it eligible for another real attempt -- if this
    regresses, every partially-transcribed page silently becomes
    permanently un-fixable."""
    outcome = await _job_that_dies_after("pp-still-wanted", good_chunks=1)
    version = await _default_version(outcome["page_id"])

    assert not crud._has_real_warning_free_transcript(version.transcript_warnings)
    assert (
        crud._classify_page_outcome(
            video_url="https://example.com/v.m3u8",
            agenda_items=[],
            default_content_hash=version.content_hash,
            default_transcript_warnings=version.transcript_warnings,
            default_transcript_language=version.language,
        )
        == "truncated_transcript"
    )


async def test_the_job_stays_failed_so_the_cooldown_still_applies():
    """Marking the job `completed` would look tidier and would rebuild the
    infinite re-queue loop: `_cooldown_active()` counts consecutive
    *failed* jobs, and that backoff is the only brake on a page that dies
    at the same chunk every time."""
    from archive.db.engine import async_session
    from archive.db.models import TranscriptionJob

    outcome = await _job_that_dies_after("pp-status", good_chunks=1)
    async with async_session() as session:
        job = await session.get(TranscriptionJob, outcome["job_id"])
    assert job.status == "failed"
    assert job.transcript_version_id == outcome["partial_transcript_version_id"]


async def test_a_partial_never_displaces_an_existing_good_transcript():
    """A page that already has real scraped captions keeps them as the
    default; the partial lands alongside, reachable via ?version=."""
    scraped = [{"start": 0.0, "end": 5.0, "text": "The real full transcript."}]
    outcome = await _job_that_dies_after(
        "pp-no-displace", good_chunks=1, existing_segments=scraped
    )

    version = await _default_version(outcome["page_id"])
    assert version.segments == scraped
    assert version.id != outcome["partial_transcript_version_id"]
    assert await _version_count(outcome["page_id"]) == 2


# --- the cases that must publish nothing ---------------------------------


async def test_a_rescheduled_job_publishes_nothing_yet():
    """A user-priority job with retries left is coming back to finish the
    work -- publishing a partial mid-flight would show a reader a truncated
    transcript for a job that is about to succeed."""
    outcome = await _job_that_dies_after(
        "pp-retry", good_chunks=1, priority=crud.PRIORITY_MEDIUM
    )
    assert outcome["status"] == "retry_scheduled"
    assert outcome["partial_transcript_version_id"] is None
    assert await _version_count(outcome["page_id"]) == 0


async def test_a_job_that_died_on_its_first_chunk_publishes_nothing():
    outcome = await _job_that_dies_after("pp-nothing", good_chunks=0)
    assert outcome["status"] == "failed"
    assert outcome["partial_transcript_version_id"] is None
    assert await _version_count(outcome["page_id"]) == 0


async def test_a_second_identical_failure_reuses_the_existing_version():
    """Content-hash dedup, on top of the cooldown: a retry that dies at the
    same chunk reproduces the same segments, and stacking identical
    versions is how the blank-transcript loop looked from the outside."""
    first = await _job_that_dies_after("pp-dedupe", good_chunks=2)
    assert await _version_count(first["page_id"]) == 1

    # A second job on the same page, dying the same way.
    second = await _job_that_dies_after("pp-dedupe", good_chunks=2)
    assert second["page_id"] == first["page_id"]
    assert (
        second["partial_transcript_version_id"]
        == first["partial_transcript_version_id"]
    )
    assert await _version_count(first["page_id"]) == 1


# --- the sentence itself -------------------------------------------------


def test_duration_words_reads_like_a_person_wrote_it():
    assert crud._duration_words(60) == "1 minute"
    assert crud._duration_words(1800) == "30 minutes"
    assert crud._duration_words(3600) == "1 hour"
    assert crud._duration_words(13200) == "3 hours 40 minutes"
    # Attributive form drops the plural, because English does:
    # "a 3 hour 40 minute meeting".
    assert crud._duration_words(13200, attributive=True) == "3 hour 40 minute"
    # Never "0 minutes" -- a reader learns nothing from it.
    assert crud._duration_words(5) == "1 minute"
    assert crud._duration_words(0) == "1 minute"


def test_the_warning_falls_back_when_the_duration_is_unusable():
    # A probed duration that isn't longer than what we transcribed can't be
    # right, and a wrong number is worse than no number.
    for total in (None, 0, 900):
        warning = crud._partial_transcription_warning(
            covered_seconds=900, total_seconds=total
        )
        assert warning.startswith("This transcript is incomplete")
        # The marker must survive both forms, or the gates diverge.
        assert crud._PARTIAL_TRANSCRIPTION_MARKER in warning
