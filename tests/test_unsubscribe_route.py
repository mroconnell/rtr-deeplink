"""HTTP-level tests for GET /unsubscribe (app/main.py) -- the CAN-SPAM
one-click unsubscribe landing page every archive/utils/email.py send now
links to in its footer (see tests/test_email_unsubscribe.py for the
footer-generation side). _resend_audience_upsert() is monkeypatched
directly rather than mocking aiohttp -- it's the one function both this
route and /api/newsletter/signup share, so patching it exercises the
route's own logic (email validation, template context) without
re-testing the HTTP call itself.
"""

from fastapi.testclient import TestClient

import app.main

client = TestClient(app.main.app)


async def test_resend_audience_upsert_returns_none_when_unconfigured(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.delenv("RESEND_AUDIENCE_ID", raising=False)
    result = await app.main._resend_audience_upsert(
        "ryan@example.com", unsubscribed=True
    )
    assert result is None


async def test_resend_audience_upsert_posts_unsubscribed_true(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "test-key")
    monkeypatch.setenv("RESEND_AUDIENCE_ID", "test-audience")

    captured = {}

    class _FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def text(self):
            return ""

    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        def post(self, url, *, headers, json, timeout):
            captured["url"] = url
            captured["json"] = json
            return _FakeResponse()

    monkeypatch.setattr(app.main.aiohttp, "ClientSession", lambda: _FakeSession())

    result = await app.main._resend_audience_upsert(
        "ryan@example.com", unsubscribed=True
    )
    assert result is True
    assert captured["json"] == {"email": "ryan@example.com", "unsubscribed": True}
    assert "test-audience" in captured["url"]


def test_unsubscribe_rejects_missing_email():
    response = client.get("/unsubscribe")
    assert response.status_code == 200
    assert "Something went wrong" in response.text


def test_unsubscribe_rejects_malformed_email(monkeypatch):
    async def _fake_upsert(email, *, unsubscribed):
        raise AssertionError("should not call Resend for an invalid email")

    monkeypatch.setattr(app.main, "_resend_audience_upsert", _fake_upsert)
    response = client.get("/unsubscribe?email=not-an-email")
    assert response.status_code == 200
    assert "Something went wrong" in response.text


def test_unsubscribe_success_shows_confirmation(monkeypatch):
    captured = {}

    async def _fake_upsert(email, *, unsubscribed):
        captured["email"] = email
        captured["unsubscribed"] = unsubscribed
        return True

    monkeypatch.setattr(app.main, "_resend_audience_upsert", _fake_upsert)
    response = client.get("/unsubscribe?email=ryan@example.com")
    assert response.status_code == 200
    assert (
        "You&#39;re unsubscribed" in response.text
        or "You're unsubscribed" in response.text
    )
    assert "ryan@example.com" in response.text
    assert captured == {"email": "ryan@example.com", "unsubscribed": True}


def test_unsubscribe_resend_failure_shows_error_not_success(monkeypatch):
    async def _fake_upsert(email, *, unsubscribed):
        return False

    monkeypatch.setattr(app.main, "_resend_audience_upsert", _fake_upsert)
    response = client.get("/unsubscribe?email=ryan@example.com")
    assert response.status_code == 200
    assert "Something went wrong" in response.text


def test_unsubscribe_resend_unconfigured_shows_error_not_success(monkeypatch):
    async def _fake_upsert(email, *, unsubscribed):
        return None

    monkeypatch.setattr(app.main, "_resend_audience_upsert", _fake_upsert)
    response = client.get("/unsubscribe?email=ryan@example.com")
    assert response.status_code == 200
    assert "Something went wrong" in response.text
