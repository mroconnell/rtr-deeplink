"""An email send with no recipient must never reach Resend, and the one
route that takes its recipient as a query param must say so.

Real occurrence: Sentry PYTHON-FASTAPI-11 (2026-08-24, production) --
Resend returning 422 "Invalid `to` field" on
/internal/send-worker-daily-report. An empty recipient reaches Resend as
`"to": [""]`, which it rejects outright rather than bouncing. Two
separate gaps made that reachable and then invisible:

1. `_send()` built its payload unconditionally, so any of the four
   send_*() call sites could hand it an empty string.
2. The route returns 200 whether or not the send succeeded, so its
   GitHub Actions caller showed a green run either way -- which is
   exactly what the triage of this alert found when it went looking for
   a failed workflow run and couldn't find one.
"""

import archive.main
import archive.utils.email as email_module
from fastapi.testclient import TestClient

client = TestClient(archive.main.app)


async def _assert_never_calls_resend(monkeypatch, to):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")
    monkeypatch.setattr(email_module, "_api_key", lambda: "test-key")
    monkeypatch.setenv("RESEND_FROM_ADDRESS", "Ryan <ryan@ally.redtaperecordings.com>")

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("Resend must not be called with an empty recipient.")

    monkeypatch.setattr(email_module.aiohttp, "ClientSession", _fail_if_called)

    assert await email_module._send(to, "Subject", "<p>body</p>") is False


async def test_send_refuses_an_empty_recipient(monkeypatch):
    await _assert_never_calls_resend(monkeypatch, "")


async def test_send_refuses_a_whitespace_only_recipient(monkeypatch):
    # `?to=%20` is just as reachable as `?to=` through the route below.
    await _assert_never_calls_resend(monkeypatch, "   ")


async def test_send_refuses_a_none_recipient(monkeypatch):
    await _assert_never_calls_resend(monkeypatch, None)


def test_worker_daily_report_route_rejects_an_empty_recipient():
    """400, not a 200 that reports {"sent": false} -- the route's own 200
    is why the failing production call looked like a success."""
    response = client.get(
        "/internal/send-worker-daily-report",
        params={"to": ""},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 400
    assert "`to`" in response.json()["detail"]


def test_worker_daily_report_route_rejects_a_whitespace_only_recipient():
    response = client.get(
        "/internal/send-worker-daily-report",
        params={"to": "   "},
        headers={"Authorization": "Bearer test-token"},
    )
    assert response.status_code == 400


def test_worker_daily_report_route_still_checks_the_token_first():
    """A bad token must not be able to tell an empty `to` from a real one
    -- every /internal/* route answers 404 before anything else."""
    response = client.get(
        "/internal/send-worker-daily-report",
        params={"to": ""},
        headers={"Authorization": "Bearer not-the-real-token"},
    )
    assert response.status_code == 404
