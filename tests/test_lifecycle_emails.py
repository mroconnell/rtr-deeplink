"""Tests for the lifecycle-triggered transactional emails added 2026-08-11
from rtr-business's marketing/LIFECYCLE_EMAILS.md (approved copy/voice):
"Thanks" (account created), "Welcome" (newsletter signup), "Goodbye for
now" (unsubscribed) in app/main.py, and "Your transcript's ready"
(rewritten copy) / "We couldn't cook this one" (new) in
archive/utils/email.py. Resend's HTTP API is faked via the same
_FakeSession/_FakeResponse pattern tests/test_email_unsubscribe.py and
tests/test_unsubscribe_route.py already use -- no real network call.
"""

import json
import time
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from svix.webhooks import Webhook

import app.main
import archive.utils.email as email_module

client = TestClient(app.main.app)


class _FakeResponse:
    status = 200

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def text(self):
        return ""


class _FakeSession:
    def __init__(self, captured):
        self._captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def post(self, url, *, headers, json, timeout):
        self._captured["url"] = url
        self._captured["json"] = json
        return _FakeResponse()


# --- archive/utils/email.py -------------------------------------------


async def test_send_completion_email_uses_new_subject_and_greeting(monkeypatch):
    monkeypatch.setattr(email_module, "_api_key", lambda: "test-key")
    monkeypatch.setenv("RESEND_FROM_ADDRESS", "Ryan <ryan@ally.redtaperecordings.com>")

    captured = {}
    monkeypatch.setattr(
        email_module.aiohttp, "ClientSession", lambda: _FakeSession(captured)
    )

    ok = await email_module.send_completion_email(
        "ryan@example.com",
        meeting_title="City Council Meeting",
        excerpt="They discussed the budget.",
        page_url="https://redtaperecordings.com/m/city-council",
    )
    assert ok is True
    assert captured["json"]["subject"] == "Your transcript's ready"
    assert "Hi there," in captured["json"]["html"]
    assert "City Council Meeting" in captured["json"]["html"]
    assert "Open it up" in captured["json"]["html"]
    # The AI-transcript disclaimer is kept deliberately (user's explicit
    # decision), even though the approved copy doc doesn't mention it.
    assert "AI transcript" in captured["json"]["html"]


async def test_send_completion_email_uses_first_name_when_given(monkeypatch):
    monkeypatch.setattr(email_module, "_api_key", lambda: "test-key")
    monkeypatch.setenv("RESEND_FROM_ADDRESS", "Ryan <ryan@ally.redtaperecordings.com>")

    captured = {}
    monkeypatch.setattr(
        email_module.aiohttp, "ClientSession", lambda: _FakeSession(captured)
    )

    await email_module.send_completion_email(
        "ryan@example.com",
        meeting_title="City Council Meeting",
        excerpt="They discussed the budget.",
        page_url="https://redtaperecordings.com/m/city-council",
        first_name="Ryan",
    )
    assert "Hi Ryan," in captured["json"]["html"]


async def test_send_transcription_failed_email_ccs_reply_to(monkeypatch):
    monkeypatch.setattr(email_module, "_api_key", lambda: "test-key")
    monkeypatch.setenv("RESEND_FROM_ADDRESS", "Ryan <ryan@ally.redtaperecordings.com>")
    monkeypatch.setenv("RESEND_REPLY_TO_ADDRESS", "ryan@redtaperecordings.com")

    captured = {}
    monkeypatch.setattr(
        email_module.aiohttp, "ClientSession", lambda: _FakeSession(captured)
    )

    ok = await email_module.send_transcription_failed_email(
        "ryan@example.com",
        meeting_title="City Council Meeting",
        page_url="https://redtaperecordings.com/m/city-council",
    )
    assert ok is True
    assert captured["json"]["subject"] == "We hit a snag on your transcript"
    assert captured["json"]["cc"] == ["ryan@redtaperecordings.com"]
    assert "couldn't get it done" in captured["json"]["html"]


async def test_send_transcription_failed_email_omits_cc_when_reply_to_unset(
    monkeypatch,
):
    monkeypatch.setattr(email_module, "_api_key", lambda: "test-key")
    monkeypatch.setenv("RESEND_FROM_ADDRESS", "Ryan <ryan@ally.redtaperecordings.com>")
    monkeypatch.delenv("RESEND_REPLY_TO_ADDRESS", raising=False)

    captured = {}
    monkeypatch.setattr(
        email_module.aiohttp, "ClientSession", lambda: _FakeSession(captured)
    )

    await email_module.send_transcription_failed_email(
        "ryan@example.com",
        meeting_title="City Council Meeting",
        page_url="https://redtaperecordings.com/m/x",
    )
    assert "cc" not in captured["json"]


# --- app/main.py: "Thanks" (Clerk user.created webhook) ----------------

_TEST_SECRET = "whsec_C2FVsBQIhrscChlQIMV+b5sSYspob7oD"


def _signed_request(event: dict, secret: str = _TEST_SECRET):
    body = json.dumps(event)
    msg_id = f"msg_{int(time.time() * 1000)}"
    ts = datetime.now(timezone.utc)
    sig = Webhook(secret).sign(msg_id, ts, body)
    headers = {
        "svix-id": msg_id,
        "svix-timestamp": str(int(ts.timestamp())),
        "svix-signature": sig,
        "content-type": "application/json",
    }
    return body, headers


async def test_user_created_sends_thanks_email_with_first_name(monkeypatch):
    monkeypatch.setenv("CLERK_WEBHOOK_SIGNING_SECRET", _TEST_SECRET)

    async def _fake_upsert(email, *, unsubscribed):
        return True

    monkeypatch.setattr(app.main, "_resend_audience_upsert", _fake_upsert)

    captured = {}

    async def _fake_thanks(to, *, first_name):
        captured["to"] = to
        captured["first_name"] = first_name
        return True

    monkeypatch.setattr(app.main, "_send_account_created_email", _fake_thanks)

    event = {
        "type": "user.created",
        "data": {
            "id": "user_abc",
            "first_name": "Ryan",
            "primary_email_address_id": "idn_1",
            "email_addresses": [{"id": "idn_1", "email_address": "ryan@example.com"}],
        },
    }
    body, headers = _signed_request(event)
    response = client.post("/api/clerk/webhook", content=body, headers=headers)
    assert response.status_code == 200
    assert captured == {"to": "ryan@example.com", "first_name": "Ryan"}


async def test_user_created_with_no_email_does_not_send_thanks(monkeypatch):
    monkeypatch.setenv("CLERK_WEBHOOK_SIGNING_SECRET", _TEST_SECRET)

    async def _fail_if_called(*args, **kwargs):
        raise AssertionError("should not send Thanks with no resolvable email")

    monkeypatch.setattr(app.main, "_send_account_created_email", _fail_if_called)

    event = {
        "type": "user.created",
        "data": {"id": "user_no_email", "email_addresses": []},
    }
    body, headers = _signed_request(event)
    response = client.post("/api/clerk/webhook", content=body, headers=headers)
    assert response.status_code == 200


# --- app/main.py: "Welcome" (newsletter signup) -------------------------


def test_newsletter_signup_sends_welcome_email_on_success(monkeypatch):
    async def _fake_upsert(email, *, unsubscribed):
        return True

    monkeypatch.setattr(app.main, "_resend_audience_upsert", _fake_upsert)

    captured = {}

    async def _fake_welcome(to):
        captured["to"] = to
        return True

    monkeypatch.setattr(app.main, "_send_newsletter_welcome_email", _fake_welcome)

    response = client.post("/api/newsletter/signup", json={"email": "ryan@example.com"})
    assert response.status_code == 200
    assert captured == {"to": "ryan@example.com"}


def test_newsletter_signup_does_not_send_welcome_on_upsert_failure(monkeypatch):
    async def _fake_upsert(email, *, unsubscribed):
        return False

    monkeypatch.setattr(app.main, "_resend_audience_upsert", _fake_upsert)

    async def _fail_if_called(to):
        raise AssertionError("should not send Welcome when the audience upsert failed")

    monkeypatch.setattr(app.main, "_send_newsletter_welcome_email", _fail_if_called)

    response = client.post("/api/newsletter/signup", json={"email": "ryan@example.com"})
    assert response.status_code == 502


# --- app/main.py: "Goodbye for now" (/unsubscribe) -----------------------


def test_unsubscribe_sends_goodbye_email_on_success(monkeypatch):
    async def _fake_upsert(email, *, unsubscribed):
        return True

    monkeypatch.setattr(app.main, "_resend_audience_upsert", _fake_upsert)

    captured = {}

    async def _fake_goodbye(to):
        captured["to"] = to
        return True

    monkeypatch.setattr(app.main, "_send_unsubscribed_email", _fake_goodbye)

    response = client.get("/unsubscribe?email=ryan@example.com")
    assert response.status_code == 200
    assert captured == {"to": "ryan@example.com"}


def test_unsubscribe_does_not_send_goodbye_on_upsert_failure(monkeypatch):
    async def _fake_upsert(email, *, unsubscribed):
        return False

    monkeypatch.setattr(app.main, "_resend_audience_upsert", _fake_upsert)

    async def _fail_if_called(to):
        raise AssertionError(
            "should not send Goodbye when the unsubscribe upsert failed"
        )

    monkeypatch.setattr(app.main, "_send_unsubscribed_email", _fail_if_called)

    response = client.get("/unsubscribe?email=ryan@example.com")
    assert response.status_code == 200


# --- app/main.py: _resend_send() (the resolver's transactional helper) --


async def test_resend_send_returns_false_when_unconfigured(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("RESEND_FROM_ADDRESS", raising=False)
    ok = await app.main._resend_send("ryan@example.com", "Subject", "<p>Body</p>")
    assert ok is False


async def test_resend_send_includes_cc_when_given(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("RESEND_FROM_ADDRESS", "Ryan <ryan@ally.redtaperecordings.com>")

    captured = {}
    monkeypatch.setattr(
        app.main.aiohttp, "ClientSession", lambda: _FakeSession(captured)
    )

    ok = await app.main._resend_send(
        "ryan@example.com", "Subject", "<p>Body</p>", cc="other@example.com"
    )
    assert ok is True
    assert captured["json"]["cc"] == ["other@example.com"]


async def test_resend_send_skip_unsubscribe_footer_omits_footer_link(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("RESEND_FROM_ADDRESS", "Ryan <ryan@ally.redtaperecordings.com>")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")

    captured = {}
    monkeypatch.setattr(
        app.main.aiohttp, "ClientSession", lambda: _FakeSession(captured)
    )

    await app.main._resend_send(
        "ryan@example.com", "Subject", "<p>Body</p>", skip_unsubscribe_footer=True
    )
    assert "Unsubscribe" not in captured["json"]["html"]


async def test_resend_send_includes_unsubscribe_footer_by_default(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("RESEND_FROM_ADDRESS", "Ryan <ryan@ally.redtaperecordings.com>")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")

    captured = {}
    monkeypatch.setattr(
        app.main.aiohttp, "ClientSession", lambda: _FakeSession(captured)
    )

    await app.main._resend_send("ryan@example.com", "Subject", "<p>Body</p>")
    assert "Unsubscribe" in captured["json"]["html"]
    assert "email=ryan%40example.com" in captured["json"]["html"]
