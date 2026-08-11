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

    monkeypatch.setattr(worker.main.email_utils, "send_completion_email", _fail_if_called)

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

    monkeypatch.setattr(worker.main.email_utils, "send_transcription_failed_email", _fail_if_called)

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

    async def _fake_send(to, *, meeting_title, page_url):
        captured["to"] = to
        captured["meeting_title"] = meeting_title
        captured["page_url"] = page_url
        return True

    monkeypatch.setattr(worker.main.email_utils, "send_transcription_failed_email", _fake_send)

    await worker.main._send_failure_email(1)
    assert captured == {
        "to": "requester@example.com",
        "meeting_title": "Some Meeting",
        "page_url": "https://redtaperecordings.com/m/some-meeting",
    }


async def test_send_failure_email_falls_back_to_generic_title(monkeypatch):
    async def _status(job_id):
        return {"meeting_page_slug": "some-meeting", "meeting_page_title": None, "requester_email": "r@example.com"}

    monkeypatch.setattr(worker.main.crud, "get_transcription_job_status", _status)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")

    captured = {}

    async def _fake_send(to, *, meeting_title, page_url):
        captured["meeting_title"] = meeting_title
        return True

    monkeypatch.setattr(worker.main.email_utils, "send_transcription_failed_email", _fake_send)

    await worker.main._send_failure_email(1)
    assert captured["meeting_title"] == "your meeting"
