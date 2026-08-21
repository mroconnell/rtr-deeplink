"""Real DB integration tests for app/db/crud.py's durable Archive-push
tracking (archive_pushed_at/archive_push_attempts on MeetingResolution) --
against the isolated SQLite fixture DB conftest.py sets up, same pattern
as tests/test_lookup_has_transcript.py. Built alongside the fix for a
real bug: a fire-and-forget BackgroundTasks push to the Archive could be
silently lost if the resolver process restarted mid-flight, with zero log
trace -- see BACKLOG_DONE.md.
"""

from datetime import datetime, timedelta, timezone

from app.db import crud


async def _log(
    url_suffix: str,
    *,
    status: str = "success",
    transcript_found: bool = False,
    video_found: bool = False,
    resolved_payload: dict | None = None,
) -> int:
    return await crud.log_resolution(
        input_url=f"https://example.granicus.com/player/clip/{url_suffix}",
        input_url_normalized=f"https://example.granicus.com/player/clip/{url_suffix}",
        input_platform="granicus",
        status=status,
        video_found=video_found,
        transcript_found=transcript_found,
        segment_count=1 if transcript_found else 0,
        resolved_payload=resolved_payload
        if resolved_payload is not None
        else {"segments": [], "agenda_items": []},
    )


async def test_log_resolution_returns_a_real_row_id():
    resolution_id = await _log("row-id")
    assert isinstance(resolution_id, int)
    assert resolution_id > 0


async def test_mark_archive_pushed_sets_timestamp():
    resolution_id = await _log("mark-pushed", transcript_found=True)
    pending_before = await crud.get_pending_archive_pushes(min_age_minutes=0)
    assert resolution_id in [p["resolution_id"] for p in pending_before]

    await crud.mark_archive_pushed(resolution_id)

    pending_after = await crud.get_pending_archive_pushes(min_age_minutes=0)
    assert resolution_id not in [p["resolution_id"] for p in pending_after]


async def test_record_archive_push_failure_increments_attempts():
    resolution_id = await _log("push-failure", transcript_found=True)
    await crud.record_archive_push_failure(resolution_id)
    await crud.record_archive_push_failure(resolution_id)

    pending = await crud.get_pending_archive_pushes(min_age_minutes=0)
    match = [p for p in pending if p["resolution_id"] == resolution_id]
    assert len(match) == 1
    assert match[0]["attempts"] == 2


async def test_pending_pushes_excludes_rows_still_within_grace_period():
    # Real gap this guards: a fresh resolve's fast BackgroundTasks push is
    # still very likely in flight seconds after the response returns --
    # the sweep must not race it and double-push.
    resolution_id = await _log("grace-period", transcript_found=True)
    pending = await crud.get_pending_archive_pushes(min_age_minutes=5)
    assert resolution_id not in [p["resolution_id"] for p in pending]
    # But it's a real candidate once the grace period is ignored (min_age_minutes=0).
    pending_now = await crud.get_pending_archive_pushes(min_age_minutes=0)
    assert resolution_id in [p["resolution_id"] for p in pending_now]


async def test_pending_pushes_excludes_content_free_resolutions():
    # status="success" with no real segments/agenda_items -- a resolve
    # that genuinely found nothing worth archiving. Never pushed, never
    # should be.
    resolution_id = await _log(
        "no-content",
        transcript_found=False,
        resolved_payload={"segments": [], "agenda_items": []},
    )
    pending = await crud.get_pending_archive_pushes(min_age_minutes=0)
    assert resolution_id not in [p["resolution_id"] for p in pending]


async def test_pending_pushes_includes_agenda_only_resolutions():
    # No transcript, but real agenda_items -- still worth pushing (same
    # "segments or agenda_items or video_url" gate /api/resolve itself uses).
    resolution_id = await _log(
        "agenda-only",
        transcript_found=False,
        resolved_payload={
            "segments": [],
            "agenda_items": [{"start": 0, "end": 0, "text": "Call to order"}],
        },
    )
    pending = await crud.get_pending_archive_pushes(min_age_minutes=0)
    assert resolution_id in [p["resolution_id"] for p in pending]


async def test_pending_pushes_includes_video_only_resolutions():
    # No transcript, no agenda_items, but a real video_url -- still worth
    # pushing. Regression test for a real bug (BACKLOG_DONE.md): several
    # adapters (Cablecast, ChampDS, PrimeGov's YouTube-delegated path) can
    # resolve a real video with segments/agenda_items/agenda_link all empty,
    # and this gate previously dropped those resolutions silently.
    resolution_id = await _log(
        "video-only",
        transcript_found=False,
        resolved_payload={
            "segments": [],
            "agenda_items": [],
            "video_url": "https://example.cablecast.tv/videos/1234",
        },
    )
    pending = await crud.get_pending_archive_pushes(min_age_minutes=0)
    assert resolution_id in [p["resolution_id"] for p in pending]


async def test_pending_pushes_finds_a_real_candidate_behind_many_content_free_rows():
    # Real bug found live 2026-08-10 against production: an earlier
    # version over-fetched with an arbitrary multiplier (.limit(limit*3))
    # before filtering by _worth_pushing() in Python. Production had many
    # "success" rows with no real content (blank_transcript/no_video
    # outcomes) mixed in with real ones -- if the oldest fetched batch was
    # mostly content-free, a real candidate further down the
    # created_at-ascending order was silently never found, even though
    # /admin/stats' unfiltered pending count still showed it. This
    # reproduces that shape directly: 15 content-free rows (comfortably
    # more than a small limit*multiplier would have over-fetched) logged
    # before one real candidate.
    for i in range(15):
        await _log(
            f"content-free-{i}",
            transcript_found=False,
            resolved_payload={"segments": [], "agenda_items": []},
        )
    resolution_id = await _log("real-candidate-behind-the-noise", transcript_found=True)

    pending = await crud.get_pending_archive_pushes(min_age_minutes=0, limit=5)
    assert resolution_id in [p["resolution_id"] for p in pending]


async def test_pending_pushes_excludes_non_success_status():
    resolution_id = await _log(
        "resolve-failed", status="resolve_failed", transcript_found=False
    )
    pending = await crud.get_pending_archive_pushes(min_age_minutes=0)
    assert resolution_id not in [p["resolution_id"] for p in pending]


async def test_pending_pushes_stops_after_max_attempts():
    resolution_id = await _log("max-attempts", transcript_found=True)
    for _ in range(crud.MAX_ARCHIVE_PUSH_ATTEMPTS):
        await crud.record_archive_push_failure(resolution_id)

    pending = await crud.get_pending_archive_pushes(min_age_minutes=0)
    assert resolution_id not in [p["resolution_id"] for p in pending]


async def test_get_cached_resolution_returns_id_alongside_payload():
    url = "https://example.granicus.com/player/clip/cached-shape"
    await crud.log_resolution(
        input_url=url,
        input_url_normalized=url,
        input_platform="granicus",
        status="success",
        transcript_found=True,
        segment_count=1,
        resolved_payload={
            "segments": [{"start": 0, "end": 1, "text": "hi"}],
            "agenda_items": [],
        },
    )
    cached = await crud.get_cached_resolution(url)
    assert cached is not None
    assert isinstance(cached["resolution_id"], int)
    assert cached["payload"]["segments"] == [{"start": 0, "end": 1, "text": "hi"}]


async def test_stats_pending_archive_pushes_count():
    before = (await crud.get_stats())["pending_archive_pushes"]
    resolution_id = await _log("stats-count", transcript_found=True)
    after_add = (await crud.get_stats())["pending_archive_pushes"]
    assert after_add == before + 1

    await crud.mark_archive_pushed(resolution_id)
    after_mark = (await crud.get_stats())["pending_archive_pushes"]
    assert after_mark == before


async def test_get_cached_resolution_ignores_a_stale_no_video_row():
    # Real bug fixed 2026-08-12: get_cached_resolution() previously had no
    # age check at all, so a one-time bad resolve (a generic_fallback
    # miss on a page that genuinely has a real video, confirmed live on a
    # real www.portland.gov URL) got served to every future visitor
    # forever, with no automatic path back to a fresh resolve.
    from app.db.engine import async_session
    from app.db.models import MeetingResolution

    url = "https://example.granicus.com/player/clip/stale-no-video"
    resolution_id = await _log(
        "stale-no-video",
        video_found=False,
        resolved_payload={"video_url": None, "segments": [], "agenda_items": []},
    )

    async with async_session() as session:
        row = await session.get(MeetingResolution, resolution_id)
        row.created_at = datetime.now(timezone.utc) - timedelta(hours=2)
        await session.commit()

    assert await crud.get_cached_resolution(url) is None


async def test_get_cached_resolution_keeps_a_fresh_no_video_row():
    # Same shape as above, but still within the TTL -- confirms this is a
    # real age check, not an unconditional exclusion of video_found=False
    # rows.
    from app.db.engine import async_session
    from app.db.models import MeetingResolution

    url = "https://example.granicus.com/player/clip/fresh-no-video"
    resolution_id = await _log(
        "fresh-no-video",
        video_found=False,
        resolved_payload={"video_url": None, "segments": [], "agenda_items": []},
    )

    async with async_session() as session:
        row = await session.get(MeetingResolution, resolution_id)
        row.created_at = datetime.now(timezone.utc) - timedelta(minutes=30)
        await session.commit()

    cached = await crud.get_cached_resolution(url)
    assert cached is not None
    assert cached["resolution_id"] == resolution_id


async def test_get_cached_resolution_never_expires_a_row_with_video_found():
    # A row that DID find a video keeps no TTL at all -- only a
    # video_found=False row is subject to the new staleness check.
    from app.db.engine import async_session
    from app.db.models import MeetingResolution

    url = "https://example.granicus.com/player/clip/old-but-video-found"
    resolution_id = await _log(
        "old-but-video-found",
        video_found=True,
        resolved_payload={
            "video_url": "https://example.com/v.m3u8",
            "segments": [],
            "agenda_items": [],
        },
    )

    async with async_session() as session:
        row = await session.get(MeetingResolution, resolution_id)
        row.created_at = datetime.now(timezone.utc) - timedelta(days=30)
        await session.commit()

    cached = await crud.get_cached_resolution(url)
    assert cached is not None
    assert cached["resolution_id"] == resolution_id
