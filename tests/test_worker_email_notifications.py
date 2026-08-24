"""Tests for worker/main.py's completion/failure email wiring --
_send_completion_email (existing) and _send_failure_email (new, the
"We couldn't cook this one" bonus email from LIFECYCLE_EMAILS.md,
2026-08-11). crud and email_utils are monkeypatched directly, matching
tests/test_worker_auto_generation.py's existing style for this module --
no real DB, no real Resend call.
"""

import worker.main


async def test_send_completion_email_noops_without_job_status(monkeypatch):
    async def _no_status(job_id):
        return None

    monkeypatch.setattr(worker.main.crud, "get_transcription_job_status", _no_status)

    called = False

    async def _fail_if_called(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        worker.main.email_utils, "send_completion_email", _fail_if_called
    )

    await worker.main._send_completion_email(1)
    assert called is False


async def test_send_completion_email_sends_with_excerpt_and_page_url(monkeypatch):
    async def _status(job_id):
        return {
            "meeting_page_slug": "some-meeting",
            "meeting_page_title": "Some Meeting",
            "transcript_version_id": 7,
            "requester_email": "requester@example.com",
        }

    async def _page(slug):
        return {
            "slug": slug,
            "versions": [{"id": 7, "segments": [{"text": "Hello"}, {"text": "world"}]}],
        }

    monkeypatch.setattr(worker.main.crud, "get_transcription_job_status", _status)
    monkeypatch.setattr(worker.main.crud, "get_page_by_slug", _page)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")

    captured = {}

    async def _fake_send(to, *, meeting_title, excerpt, page_url):
        captured["to"] = to
        captured["meeting_title"] = meeting_title
        captured["excerpt"] = excerpt
        captured["page_url"] = page_url
        return True

    monkeypatch.setattr(worker.main.email_utils, "send_completion_email", _fake_send)

    await worker.main._send_completion_email(1)
    assert captured["to"] == "requester@example.com"
    assert captured["meeting_title"] == "Some Meeting"
    assert captured["excerpt"] == "Hello world"
    assert captured["page_url"] == "https://redtaperecordings.com/m/some-meeting"


async def test_send_failure_email_noops_without_job_status(monkeypatch):
    async def _no_status(job_id):
        return None

    monkeypatch.setattr(worker.main.crud, "get_transcription_job_status", _no_status)

    called = False

    async def _fail_if_called(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(
        worker.main.email_utils, "send_transcription_failed_email", _fail_if_called
    )

    await worker.main._send_failure_email(1)
    assert called is False


async def test_send_failure_email_sends_with_meeting_title_and_page_url(monkeypatch):
    async def _status(job_id):
        return {
            "meeting_page_slug": "some-meeting",
            "meeting_page_title": "Some Meeting",
            "requester_email": "requester@example.com",
            "error_message": "ffmpeg extraction failed",
        }

    monkeypatch.setattr(worker.main.crud, "get_transcription_job_status", _status)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")

    captured = {}

    async def _fake_send(to, *, meeting_title, page_url, **kwargs):
        captured["to"] = to
        captured["meeting_title"] = meeting_title
        captured["page_url"] = page_url
        return True

    async def _fake_admin_send(**kwargs):
        return True

    monkeypatch.setattr(
        worker.main.email_utils, "send_transcription_failed_email", _fake_send
    )
    monkeypatch.setattr(
        worker.main.email_utils, "send_admin_job_failure_alert", _fake_admin_send
    )

    await worker.main._send_failure_email(1)
    assert captured == {
        "to": "requester@example.com",
        "meeting_title": "Some Meeting",
        "page_url": "https://redtaperecordings.com/m/some-meeting",
    }


async def test_failure_email_reports_the_partial_when_one_was_published(monkeypatch):
    """A terminally-failed job that salvaged chunks
    (crud._publish_partial_transcript()) has a transcript_version_id, and
    the requester should be told what they *got* -- being emailed "we
    failed" while three hours of their meeting sits transcribed on the
    page is the outcome that change exists to remove."""

    async def _status(job_id):
        return {
            "meeting_page_slug": "some-meeting",
            "meeting_page_title": "Some Meeting",
            "requester_email": "requester@example.com",
            "transcript_version_id": 4242,
            "transcribed_seconds": 11520.0,
            "probed_duration_seconds": 13200.0,
        }

    monkeypatch.setattr(worker.main.crud, "get_transcription_job_status", _status)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")

    captured = {}

    async def _fake_send(to, *, meeting_title, page_url, **kwargs):
        captured.update(kwargs)
        return True

    async def _fake_admin_send(**kwargs):
        return True

    monkeypatch.setattr(
        worker.main.email_utils, "send_transcription_failed_email", _fake_send
    )
    monkeypatch.setattr(
        worker.main.email_utils, "send_admin_job_failure_alert", _fake_admin_send
    )

    await worker.main._send_failure_email(1)
    assert captured["partial_coverage"] == "3 hours 12 minutes"


async def test_failure_email_stays_a_plain_failure_when_nothing_was_saved(monkeypatch):
    """A job that died on its first chunk publishes nothing, so the
    original couldn't-do-it copy must still be what goes out."""

    async def _status(job_id):
        return {
            "meeting_page_slug": "some-meeting",
            "meeting_page_title": "Some Meeting",
            "requester_email": "requester@example.com",
            "transcript_version_id": None,
            "transcribed_seconds": 0.0,
        }

    monkeypatch.setattr(worker.main.crud, "get_transcription_job_status", _status)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")

    captured = {}

    async def _fake_send(to, *, meeting_title, page_url, **kwargs):
        captured.update(kwargs)
        return True

    async def _fake_admin_send(**kwargs):
        return True

    monkeypatch.setattr(
        worker.main.email_utils, "send_transcription_failed_email", _fake_send
    )
    monkeypatch.setattr(
        worker.main.email_utils, "send_admin_job_failure_alert", _fake_admin_send
    )

    await worker.main._send_failure_email(1)
    assert captured["partial_coverage"] is None


async def test_send_failure_email_falls_back_to_generic_title(monkeypatch):
    async def _status(job_id):
        return {
            "meeting_page_slug": "some-meeting",
            "meeting_page_title": None,
            "requester_email": "r@example.com",
        }

    monkeypatch.setattr(worker.main.crud, "get_transcription_job_status", _status)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")

    captured = {}

    async def _fake_send(to, *, meeting_title, page_url, **kwargs):
        captured["meeting_title"] = meeting_title
        return True

    async def _fake_admin_send(**kwargs):
        return True

    monkeypatch.setattr(
        worker.main.email_utils, "send_transcription_failed_email", _fake_send
    )
    monkeypatch.setattr(
        worker.main.email_utils, "send_admin_job_failure_alert", _fake_admin_send
    )

    await worker.main._send_failure_email(1)
    assert captured["meeting_title"] == "your meeting"


async def test_send_failure_email_also_sends_admin_alert_with_diagnostics(monkeypatch):
    # Real gap closed 2026-08-19: the requester-facing "sorry, try again"
    # email carries no diagnostics an operator could act on -- this checks
    # the separate admin alert gets the real job id, source URL, chunk
    # progress, and retry history, not just a repeat of the branded copy.
    async def _status(job_id):
        return {
            "meeting_page_slug": "some-meeting",
            "meeting_page_title": "Some Meeting",
            "requester_email": "requester@example.com",
            "error_message": "ffmpeg exited 1: timed out",
            "source_url": "https://example.granicus.com/player/clip/1",
            "chunks_completed": 1,
            "total_chunks": 27,
            "retry_count": 3,
            "failure_history": [
                {
                    "chunk_index": 1,
                    "error": "ffmpeg timed out",
                    "at": "2026-08-18T18:10:00+00:00",
                }
            ],
            "created_at": "2026-08-18T18:03:48+00:00",
        }

    monkeypatch.setattr(worker.main.crud, "get_transcription_job_status", _status)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")

    async def _fake_send(to, *, meeting_title, page_url, **kwargs):
        return True

    captured = {}

    async def _fake_admin_send(**kwargs):
        captured.update(kwargs)
        return True

    monkeypatch.setattr(
        worker.main.email_utils, "send_transcription_failed_email", _fake_send
    )
    monkeypatch.setattr(
        worker.main.email_utils, "send_admin_job_failure_alert", _fake_admin_send
    )

    await worker.main._send_failure_email(42)
    assert captured["job_id"] == 42
    assert captured["requester_email"] == "requester@example.com"
    assert captured["source_url"] == "https://example.granicus.com/player/clip/1"
    assert captured["chunks_completed"] == 1
    assert captured["total_chunks"] == 27
    assert captured["retry_count"] == 3
    assert captured["failure_history"][0]["chunk_index"] == 1
    assert captured["page_url"] == "https://redtaperecordings.com/m/some-meeting"
