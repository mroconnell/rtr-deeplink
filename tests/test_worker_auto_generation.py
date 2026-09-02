"""Tests for worker/main.py's auto-idle-time job generation (built
2026-08-09, see BACKLOG_DONE.md) -- the parts of the control flow that
don't require mocking a live finder.resolve()/probe_duration() call. The
underlying candidate-selection/cooldown logic itself is covered directly
in tests/test_transcription_jobs.py against the real crud layer.
"""

import worker.main


def test_auto_media_kind_matches_app_mains_own_rule():
    assert worker.main._auto_media_kind("mp3") == "audio"
    assert worker.main._auto_media_kind("wav") == "audio"
    assert worker.main._auto_media_kind("m3u8") == "video"
    assert worker.main._auto_media_kind("mp4") == "video"
    assert worker.main._auto_media_kind(None) == "video"


async def test_maybe_generate_auto_job_disabled_without_requester_email(monkeypatch):
    # AUTO_TRANSCRIPTION_REQUESTER_EMAIL is read once at module import time,
    # so this monkeypatches the resulting module attribute directly, not
    # the environment variable itself.
    monkeypatch.setattr(worker.main, "AUTO_TRANSCRIPTION_REQUESTER_EMAIL", "")

    called = False

    async def _fail_if_called(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        worker.main.crud, "find_auto_transcription_candidate", _fail_if_called
    )

    result = await worker.main.maybe_generate_auto_job()
    assert result is False
    assert called is False  # never even looked for a candidate


async def test_maybe_generate_auto_job_returns_false_with_no_candidate(monkeypatch):
    monkeypatch.setattr(
        worker.main, "AUTO_TRANSCRIPTION_REQUESTER_EMAIL", "auto@example.com"
    )

    async def _no_candidate():
        return None

    monkeypatch.setattr(
        worker.main.crud, "find_auto_transcription_candidate", _no_candidate
    )

    result = await worker.main.maybe_generate_auto_job()
    assert result is False


async def test_maybe_generate_auto_job_records_failure_for_unsupported_platform(
    monkeypatch,
):
    # get_finder() raises UnsupportedPlatformError for a platform with no
    # registered finder -- confirms that's treated as a real (recorded)
    # failure, not an unhandled exception that crashes the poll loop.
    monkeypatch.setattr(
        worker.main, "AUTO_TRANSCRIPTION_REQUESTER_EMAIL", "auto@example.com"
    )

    async def _candidate():
        return {
            "meeting_page_id": 999999,
            "slug": "fake-slug",
            "source_url": "https://example.com/meeting",
            "platform": "no_such_platform_registered",
        }

    recorded = {}

    async def _record_failure(*, meeting_page_id, requester_email, error_message):
        recorded["meeting_page_id"] = meeting_page_id
        recorded["requester_email"] = requester_email
        recorded["error_message"] = error_message
        return {"job_id": 1, "status": "failed"}

    monkeypatch.setattr(
        worker.main.crud, "find_auto_transcription_candidate", _candidate
    )
    monkeypatch.setattr(
        worker.main.crud, "create_failed_auto_transcription_job", _record_failure
    )

    result = await worker.main.maybe_generate_auto_job()
    assert result is True
    assert recorded["meeting_page_id"] == 999999
    assert recorded["requester_email"] == "auto@example.com"
    assert "Re-resolve failed" in recorded["error_message"]


# --- The feasibility check's own one-shot-no-retry gap (2026-08-22) --------
#
# Checked here as part of BACKLOG.md's "transcribe_backlog_locally.py gives
# up on a live meeting after one transient failure" -- the worker's *chunk*
# path never had that gap (crud.MAX_CONSECUTIVE_CHUNK_FAILURES gives every
# chunk three tries, job-level retries cover user-priority jobs, and
# TranscriptionJob.partial_segments already keeps everything transcribed so
# far), but this path did: one transient resolve/probe failure wrote a real
# `failed` job row, which _cooldown_active() counts, pushing a perfectly
# good page a full day out -- doubling per consecutive failure, up to 30.
#
# SYNTHETIC in the same narrow way as the matching tests in
# tests/test_transcribe_backlog_locally.py: the failure shape (a bare
# TimeoutError from an eScribe resolve, ffprobe returning None) is real and
# confirmed, "fails once then succeeds unchanged" is the behavior under
# test, and no live source can be asked to do that on cue.


def _retrying_worker(monkeypatch):
    monkeypatch.setattr(
        worker.main, "AUTO_TRANSCRIPTION_REQUESTER_EMAIL", "auto@example.com"
    )
    monkeypatch.setattr(worker.main, "AUTO_GENERATION_RETRY_BASE_DELAY_SECONDS", 0.001)
    monkeypatch.setattr(worker.main, "AUTO_GENERATION_RETRY_MAX_DELAY_SECONDS", 0.002)

    async def _candidate():
        return {
            "meeting_page_id": 999999,
            "slug": "fake-slug",
            "source_url": "https://pub-3ce.escribemeetings.com/Meeting.aspx?Id=fake",
            "platform": "escribe",
        }

    async def _fail_if_called(*args, **kwargs):
        raise AssertionError(
            "a transient failure must not be recorded as a failed job -- that is "
            "what burns the page's escalating auto-transcription cooldown"
        )

    monkeypatch.setattr(
        worker.main.crud, "find_auto_transcription_candidate", _candidate
    )
    monkeypatch.setattr(
        worker.main.crud, "create_failed_auto_transcription_job", _fail_if_called
    )

    created = {}

    async def _create_job(**kwargs):
        created.update(kwargs)
        return {"job_id": 4242}

    monkeypatch.setattr(worker.main.crud, "create_transcription_job", _create_job)
    return created


async def test_auto_generation_retries_a_resolve_that_fails_once(monkeypatch):
    created = _retrying_worker(monkeypatch)
    from app.platforms.models import ResolvedMeeting

    calls = []

    class _Finder:
        async def resolve(self, url):
            calls.append(url)
            if len(calls) == 1:
                raise TimeoutError()
            return ResolvedMeeting(
                platform="escribe",
                source_url=url,
                video_url="https://example.org/meeting.m3u8",
                video_format="m3u8",
            )

    monkeypatch.setattr(worker.main, "get_finder", lambda platform: _Finder())

    async def _probe(video_url, *, source_page_url):
        return 3600.0

    monkeypatch.setattr(worker.main, "probe_duration", _probe)

    assert await worker.main.maybe_generate_auto_job() is True
    assert len(calls) == 2  # one real failure, one real success
    assert created["probed_duration_seconds"] == 3600.0
    assert created["priority"] == worker.main.crud.PRIORITY_LOW


async def test_auto_generation_retries_a_probe_that_fails_once(monkeypatch):
    """probe_duration() reports every failure -- including its 120s
    subprocess timeout -- as None rather than raising, so it needs the
    returned-failure branch of the retry, not the exception one."""
    created = _retrying_worker(monkeypatch)
    from app.platforms.models import ResolvedMeeting

    class _Finder:
        async def resolve(self, url):
            return ResolvedMeeting(
                platform="escribe",
                source_url=url,
                video_url="https://example.org/meeting.m3u8",
                video_format="m3u8",
            )

    monkeypatch.setattr(worker.main, "get_finder", lambda platform: _Finder())

    probes = []

    async def _probe(video_url, *, source_page_url):
        probes.append(video_url)
        return None if len(probes) == 1 else 3600.0

    monkeypatch.setattr(worker.main, "probe_duration", _probe)

    assert await worker.main.maybe_generate_auto_job() is True
    assert len(probes) == 2
    assert created["probed_duration_seconds"] == 3600.0


async def test_auto_generation_gives_granicus_the_smaller_chunk_size(monkeypatch):
    # Real, measured 2026-08-25 (BACKLOG_DONE.md): 24/24 real Granicus
    # chunk failures were ffmpeg timeouts on cold CDN fill. Auto-generated
    # jobs must get Granicus's 300s chunk size, not the 450s every other
    # platform gets under the worker's own memory constraint (WO-94) --
    # see app/platforms/media_probe.py's chunk_size_seconds_for_platform().
    created = _retrying_worker(monkeypatch)
    from app.platforms.models import ResolvedMeeting

    class _Finder:
        async def resolve(self, url):
            return ResolvedMeeting(
                platform="granicus",
                source_url=url,
                video_url="https://example.org/meeting.m3u8",
                video_format="m3u8",
            )

    monkeypatch.setattr(worker.main, "get_finder", lambda platform: _Finder())

    async def _probe(video_url, *, source_page_url):
        return 3600.0

    monkeypatch.setattr(worker.main, "probe_duration", _probe)

    assert await worker.main.maybe_generate_auto_job() is True
    assert created["chunk_size_seconds"] == 300


async def test_auto_generation_still_records_a_permanently_unreadable_source(
    monkeypatch,
):
    """The retry must not stop a genuinely-broken page from being recorded
    as infeasible -- otherwise every unusable candidate would be re-probed
    on every idle check forever, which is exactly what the cooldown
    exists to prevent."""
    monkeypatch.setattr(
        worker.main, "AUTO_TRANSCRIPTION_REQUESTER_EMAIL", "auto@example.com"
    )
    monkeypatch.setattr(worker.main, "AUTO_GENERATION_RETRY_BASE_DELAY_SECONDS", 0.001)
    monkeypatch.setattr(worker.main, "AUTO_GENERATION_RETRY_MAX_DELAY_SECONDS", 0.002)
    from app.platforms.models import ResolvedMeeting

    async def _candidate():
        return {
            "meeting_page_id": 999999,
            "slug": "fake-slug",
            "source_url": "https://pub-3ce.escribemeetings.com/Meeting.aspx?Id=fake",
            "platform": "escribe",
        }

    class _Finder:
        async def resolve(self, url):
            return ResolvedMeeting(
                platform="escribe",
                source_url=url,
                video_url="https://example.org/meeting.m3u8",
                video_format="m3u8",
            )

    probes = []

    async def _probe(video_url, *, source_page_url):
        probes.append(video_url)
        return None

    recorded = {}

    async def _record_failure(*, meeting_page_id, requester_email, error_message):
        recorded["error_message"] = error_message
        return {"job_id": 1, "status": "failed"}

    monkeypatch.setattr(
        worker.main.crud, "find_auto_transcription_candidate", _candidate
    )
    monkeypatch.setattr(worker.main, "get_finder", lambda platform: _Finder())
    monkeypatch.setattr(worker.main, "probe_duration", _probe)
    monkeypatch.setattr(
        worker.main.crud, "create_failed_auto_transcription_job", _record_failure
    )

    assert await worker.main.maybe_generate_auto_job() is True
    assert len(probes) == worker.main.AUTO_GENERATION_ATTEMPTS
    assert "couldn't read it" in recorded["error_message"]


# --- WO-79: a multi-clip Swagit meeting gets a real per-clip chunk plan ----


async def test_auto_generation_builds_a_chunk_plan_for_a_multi_clip_meeting(
    monkeypatch,
):
    """A meeting with more than one real video_segment (some Swagit
    tenants -- no single combined recording, see swagit.py) must probe
    EVERY clip and submit the real summed total duration, not just the
    first clip's -- the whole point of WO-79 being that the auto-
    generated transcript covers the whole meeting."""
    created = _retrying_worker(monkeypatch)
    from app.platforms.models import ResolvedMeeting, VideoSegment

    class _Finder:
        async def resolve(self, url):
            return ResolvedMeeting(
                platform="swagit",
                source_url=url,
                video_url="https://x/a.m3u8",
                video_format="m3u8",
                video_segments=[
                    VideoSegment(url="https://x/a.m3u8", seq=6, title="First"),
                    VideoSegment(url="https://x/b.m3u8", seq=13, title="Second"),
                ],
            )

    monkeypatch.setattr(worker.main, "get_finder", lambda platform: _Finder())

    async def _plan(video_segments, *, source_page_url):
        return [
            {
                "media_url": "https://x/a.m3u8",
                "start": 0.0,
                "duration": 120.0,
                "title": "First",
                "seq": 6,
            },
            {
                "media_url": "https://x/b.m3u8",
                "start": 120.0,
                "duration": 300.0,
                "title": "Second",
                "seq": 13,
            },
        ]

    monkeypatch.setattr(worker.main, "probe_multi_clip_chunk_plan", _plan)

    async def _fail_if_called(video_url, *, source_page_url):
        raise AssertionError(
            "a successful multi-clip plan must skip the single-clip probe_duration() "
            "fallback entirely"
        )

    monkeypatch.setattr(worker.main, "probe_duration", _fail_if_called)

    assert await worker.main.maybe_generate_auto_job() is True
    assert created["probed_duration_seconds"] == 420.0  # 120 + 300, not just 120
    assert created["chunk_plan"][0]["media_url"] == "https://x/a.m3u8"
    assert created["chunk_plan"][1]["start"] == 120.0


async def test_auto_generation_falls_back_to_single_clip_when_plan_probe_fails(
    monkeypatch,
):
    """probe_multi_clip_chunk_plan() is all-or-nothing (see its own
    docstring) -- when it returns None (one clip failed to probe), this
    must fall back to the ordinary single-first-clip path rather than
    treating the whole candidate as infeasible."""
    created = _retrying_worker(monkeypatch)
    from app.platforms.models import ResolvedMeeting, VideoSegment

    class _Finder:
        async def resolve(self, url):
            return ResolvedMeeting(
                platform="swagit",
                source_url=url,
                video_url="https://x/a.m3u8",
                video_format="m3u8",
                video_segments=[
                    VideoSegment(url="https://x/a.m3u8", seq=6),
                    VideoSegment(url="https://x/b.m3u8", seq=13),
                ],
            )

    monkeypatch.setattr(worker.main, "get_finder", lambda platform: _Finder())

    async def _plan(video_segments, *, source_page_url):
        return None

    monkeypatch.setattr(worker.main, "probe_multi_clip_chunk_plan", _plan)

    async def _probe(video_url, *, source_page_url):
        assert video_url == "https://x/a.m3u8"
        return 120.0

    monkeypatch.setattr(worker.main, "probe_duration", _probe)

    assert await worker.main.maybe_generate_auto_job() is True
    assert created["probed_duration_seconds"] == 120.0
    assert created["chunk_plan"] is None
