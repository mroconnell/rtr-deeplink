"""WO-1981: auto-generation must not keep making jobs on a page that is
not the candidate it picked.

Real case (Render worker log, 2026-11-12): the candidate search offered
Portage MI's "2026-08-11-city-council-meeting-8-11-2026" again and again
while job 12555 was live, and each create call handed back job 12555.
The candidate search skips a page with a live job (WO-1169), so job
12555 sat on a different page: the re-resolve lands on another page for
the same meeting. Failures then counted against that other page, the
candidate never cooled down, and a new job was made as soon as the last
one was retired (WO-1980). The job's last chunk ran the worker out of
memory every time, so both workers crash-looped.

Synthetic: the two pages are built by hand. The shape is the same
create_transcription_job() payload the real auto-generation path sends.
"""

from datetime import datetime, timedelta, timezone

from archive.db import crud


def _payload(key: str) -> dict:
    url = f"https://example.cablecast.tv/show/{key}?site=1"
    return {
        "platform": "cablecast",
        "source_url": url,
        "external_id": f"cablecast:example.cablecast.tv:{key}",
        "title": "Other Page Test Meeting",
        "date": "2026-08-11",
        "jurisdiction": "City of Heartbeat",
        "video_url": "https://example.com/v.mp4",
        "video_format": "mp4",
        "segments": [],
        "agenda_items": [],
        "transcript_language": None,
        "transcript_warnings": [],
    }


async def _create(key: str, **kwargs) -> dict:
    payload = _payload(key)
    return await crud.create_transcription_job(
        payload=payload,
        input_url_normalized=payload["source_url"],
        requester_email="auto@example.com",
        media_url="https://example.com/v.mp4",
        media_kind="video",
        probed_duration_seconds=2700,
        chunk_size_seconds=900,
        skip_confirmation=True,
        priority=crud.PRIORITY_LOW,
        **kwargs,
    )


async def _page_id(slug: str) -> int:
    page = await crud.get_page_by_slug(slug)
    return page["id"]


async def _jobs_on(page_id: int) -> list:
    from sqlalchemy import select

    from archive.db.engine import async_session
    from archive.db.models import TranscriptionJob

    async with async_session() as session:
        return (
            (
                await session.execute(
                    select(TranscriptionJob)
                    .where(TranscriptionJob.meeting_page_id == page_id)
                    .order_by(TranscriptionJob.id.desc())
                )
            )
            .scalars()
            .all()
        )


async def _set_status(job_id: int, status: str) -> None:
    from archive.db.engine import async_session
    from archive.db.models import TranscriptionJob

    async with async_session() as session:
        job = await session.get(TranscriptionJob, job_id)
        job.status = status
        job.updated_at = datetime.now(timezone.utc)
        await session.commit()


async def test_live_job_on_other_page_makes_candidate_cool_down():
    landed = await _create("wo1981a")
    landed_page = await _page_id(landed["meeting_page_slug"])
    candidate_page = await _page_id((await _create("wo1981b"))["meeting_page_slug"])
    # Clear the candidate's own job so only the redirect matters.
    for job in await _jobs_on(candidate_page):
        await _set_status(job.id, "completed")

    result = await _create("wo1981a", auto_candidate_page_id=candidate_page)

    assert result["error"] == "resolved_page_cooling_down"
    assert result["meeting_page_id"] == landed_page
    # No second job on the landed-on page...
    assert len(await _jobs_on(landed_page)) == 1
    # ...and the candidate now carries a failed job, so the candidate
    # search's cooldown holds it back.
    newest = (await _jobs_on(candidate_page))[0]
    assert newest.status == "failed"
    history = [(j.status, j.updated_at) for j in await _jobs_on(candidate_page)]
    assert crud._cooldown_active(history, datetime.now(timezone.utc))
    await _set_status(landed["job_id"], "completed")


async def test_failed_job_on_other_page_blocks_a_new_one():
    landed = await _create("wo1981c")
    landed_page = await _page_id(landed["meeting_page_slug"])
    await _set_status(landed["job_id"], "failed")
    candidate = await _create("wo1981d")
    await _set_status(candidate["job_id"], "completed")
    candidate_page = await _page_id(candidate["meeting_page_slug"])

    result = await _create("wo1981c", auto_candidate_page_id=candidate_page)

    assert result["error"] == "resolved_page_cooling_down"
    assert [j.status for j in await _jobs_on(landed_page)] == ["failed"]


async def test_other_page_not_cooling_down_still_gets_a_job():
    candidate = await _create("wo1981f")
    await _set_status(candidate["job_id"], "completed")
    candidate_page = await _page_id(candidate["meeting_page_slug"])
    # A page with no job history at all is not cooling down.
    result = await _create("wo1981e", auto_candidate_page_id=candidate_page)

    assert "error" not in result
    assert result["status"] == "queued"
    await _set_status(result["job_id"], "completed")


async def test_same_page_behaves_as_before():
    first = await _create("wo1981g")
    page = await _page_id(first["meeting_page_slug"])

    again = await _create("wo1981g", auto_candidate_page_id=page)

    # The existing live job comes back, as it always did.
    assert again["job_id"] == first["job_id"]
    await _set_status(first["job_id"], "completed")


def test_cooldown_window_used_is_the_shared_rule():
    # Guard: the redirect check reuses _cooldown_active() rather than its
    # own copy, so one failure an hour ago still blocks.
    now = datetime.now(timezone.utc)
    assert crud._cooldown_active([("failed", now - timedelta(hours=1))], now)
