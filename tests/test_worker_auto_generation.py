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

    monkeypatch.setattr(worker.main.crud, "find_auto_transcription_candidate", _fail_if_called)

    result = await worker.main.maybe_generate_auto_job()
    assert result is False
    assert called is False  # never even looked for a candidate


async def test_maybe_generate_auto_job_returns_false_with_no_candidate(monkeypatch):
    monkeypatch.setattr(worker.main, "AUTO_TRANSCRIPTION_REQUESTER_EMAIL", "auto@example.com")

    async def _no_candidate():
        return None

    monkeypatch.setattr(worker.main.crud, "find_auto_transcription_candidate", _no_candidate)

    result = await worker.main.maybe_generate_auto_job()
    assert result is False


async def test_maybe_generate_auto_job_records_failure_for_unsupported_platform(monkeypatch):
    # get_finder() raises UnsupportedPlatformError for a platform with no
    # registered finder -- confirms that's treated as a real (recorded)
    # failure, not an unhandled exception that crashes the poll loop.
    monkeypatch.setattr(worker.main, "AUTO_TRANSCRIPTION_REQUESTER_EMAIL", "auto@example.com")

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

    monkeypatch.setattr(worker.main.crud, "find_auto_transcription_candidate", _candidate)
    monkeypatch.setattr(worker.main.crud, "create_failed_auto_transcription_job", _record_failure)

    result = await worker.main.maybe_generate_auto_job()
    assert result is True
    assert recorded["meeting_page_id"] == 999999
    assert recorded["requester_email"] == "auto@example.com"
    assert "Re-resolve failed" in recorded["error_message"]
