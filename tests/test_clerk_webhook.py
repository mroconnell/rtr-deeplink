"""Tests for POST /api/clerk/webhook (app/main.py) -- real Svix signature
sign/verify round trips (not mocked out), since that's the actual security
boundary this route depends on. _resend_audience_upsert and
archive_client.delete_account_data are monkeypatched to check side
effects without a real Resend/Archive call.
"""

import json
import time
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from svix.webhooks import Webhook

import app.main

client = TestClient(app.main.app)

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


def test_webhook_returns_503_when_signing_secret_unconfigured(monkeypatch):
    monkeypatch.delenv("CLERK_WEBHOOK_SIGNING_SECRET", raising=False)
    body, headers = _signed_request({"type": "user.created", "data": {"id": "user_1"}})
    response = client.post("/api/clerk/webhook", content=body, headers=headers)
    assert response.status_code == 503


def test_webhook_rejects_invalid_signature(monkeypatch):
    monkeypatch.setenv("CLERK_WEBHOOK_SIGNING_SECRET", _TEST_SECRET)
    body, headers = _signed_request({"type": "user.created", "data": {"id": "user_1"}}, secret="whsec_wrong_secret_entirely")
    response = client.post("/api/clerk/webhook", content=body, headers=headers)
    assert response.status_code == 400


def test_webhook_rejects_missing_signature_headers(monkeypatch):
    monkeypatch.setenv("CLERK_WEBHOOK_SIGNING_SECRET", _TEST_SECRET)
    response = client.post(
        "/api/clerk/webhook",
        content=json.dumps({"type": "user.created", "data": {"id": "user_1"}}),
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 400


async def test_user_created_upserts_the_primary_email(monkeypatch):
    monkeypatch.setenv("CLERK_WEBHOOK_SIGNING_SECRET", _TEST_SECRET)
    captured = {}

    async def _fake_upsert(email, *, unsubscribed):
        captured["email"] = email
        captured["unsubscribed"] = unsubscribed
        return True

    monkeypatch.setattr(app.main, "_resend_audience_upsert", _fake_upsert)

    event = {
        "type": "user.created",
        "data": {
            "id": "user_abc",
            "primary_email_address_id": "idn_1",
            "email_addresses": [
                {"id": "idn_0", "email_address": "not-primary@example.com"},
                {"id": "idn_1", "email_address": "primary@example.com"},
            ],
        },
    }
    body, headers = _signed_request(event)
    response = client.post("/api/clerk/webhook", content=body, headers=headers)
    assert response.status_code == 200
    assert captured == {"email": "primary@example.com", "unsubscribed": False}


async def test_user_created_with_no_resolvable_email_does_not_crash(monkeypatch):
    monkeypatch.setenv("CLERK_WEBHOOK_SIGNING_SECRET", _TEST_SECRET)

    async def _fake_upsert(email, *, unsubscribed):
        raise AssertionError("should not be called when no primary email resolves")

    monkeypatch.setattr(app.main, "_resend_audience_upsert", _fake_upsert)

    event = {"type": "user.created", "data": {"id": "user_no_email", "email_addresses": []}}
    body, headers = _signed_request(event)
    response = client.post("/api/clerk/webhook", content=body, headers=headers)
    assert response.status_code == 200


async def test_user_deleted_calls_delete_account_data(monkeypatch):
    monkeypatch.setenv("CLERK_WEBHOOK_SIGNING_SECRET", _TEST_SECRET)
    captured = {}

    async def _fake_delete(clerk_user_id):
        captured["clerk_user_id"] = clerk_user_id
        return {"deleted": 3}

    monkeypatch.setattr(app.main.archive_client, "delete_account_data", _fake_delete)

    event = {"type": "user.deleted", "data": {"id": "user_to_delete", "deleted": True}}
    body, headers = _signed_request(event)
    response = client.post("/api/clerk/webhook", content=body, headers=headers)
    assert response.status_code == 200
    assert captured == {"clerk_user_id": "user_to_delete"}


async def test_unrecognized_event_type_is_a_harmless_noop(monkeypatch):
    monkeypatch.setenv("CLERK_WEBHOOK_SIGNING_SECRET", _TEST_SECRET)
    event = {"type": "session.created", "data": {"id": "sess_1"}}
    body, headers = _signed_request(event)
    response = client.post("/api/clerk/webhook", content=body, headers=headers)
    assert response.status_code == 200
