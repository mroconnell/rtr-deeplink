"""Tests for the real one-click unsubscribe link added to every email
archive/utils/email.py sends (2026-08-10), per Resend's own deliverability
guidance flagging a missing opt-out path as a real sender-reputation risk
-- prompted directly by the user linking that guidance and asking for it.
"""

import os

from archive.utils.email import _unsubscribe_footer_html


def test_footer_empty_when_public_base_url_unset(monkeypatch):
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)
    assert _unsubscribe_footer_html("ryan@example.com") == ""


def test_footer_contains_a_real_unsubscribe_link(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")
    footer = _unsubscribe_footer_html("ryan@example.com")
    assert (
        'href="https://redtaperecordings.com/unsubscribe?email=ryan%40example.com"'
        in footer
    )
    assert "Unsubscribe" in footer


def test_footer_strips_trailing_slash_from_base_url(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com/")
    footer = _unsubscribe_footer_html("ryan@example.com")
    assert "//unsubscribe" not in footer.replace("https://", "")


def test_footer_url_encodes_special_characters_in_the_email(monkeypatch):
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")
    footer = _unsubscribe_footer_html("first+test@example.com")
    assert "email=first%2Btest%40example.com" in footer


async def test_send_appends_the_footer_to_every_email(monkeypatch):
    # Real property this guards: the footer must be guaranteed for every
    # send_*() call, not something each one has to remember to add --
    # verified here at the _send() level, the one place all of them
    # funnel through.
    import archive.utils.email as email_module

    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")
    monkeypatch.setattr(email_module, "_api_key", lambda: "test-key")
    os.environ["RESEND_FROM_ADDRESS"] = "Ryan <ryan@ally.redtaperecordings.com>"

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
            captured["json"] = json
            return _FakeResponse()

    monkeypatch.setattr(email_module.aiohttp, "ClientSession", lambda: _FakeSession())

    ok = await email_module.send_confirmation_email(
        "ryan@example.com", "https://example.com/confirm?token=abc"
    )
    assert ok is True
    assert "Unsubscribe" in captured["json"]["html"]
    assert "email=ryan%40example.com" in captured["json"]["html"]


async def test_send_includes_reply_to_when_configured(monkeypatch):
    # RESEND_FROM_ADDRESS lives on a subdomain dedicated to Resend's own
    # sending DNS with no real inbox behind it -- reply_to is what lets
    # a real reply land somewhere that forwards, without touching that
    # subdomain's DNS at all.
    import archive.utils.email as email_module

    monkeypatch.setattr(email_module, "_api_key", lambda: "test-key")
    monkeypatch.setenv("RESEND_FROM_ADDRESS", "Ryan <ryan@ally.redtaperecordings.com>")
    monkeypatch.setenv("RESEND_REPLY_TO_ADDRESS", "ryan@redtaperecordings.com")

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
            captured["json"] = json
            return _FakeResponse()

    monkeypatch.setattr(email_module.aiohttp, "ClientSession", lambda: _FakeSession())

    ok = await email_module.send_confirmation_email(
        "ryan@example.com", "https://example.com/confirm?token=abc"
    )
    assert ok is True
    assert captured["json"]["reply_to"] == "ryan@redtaperecordings.com"


async def test_send_omits_reply_to_when_unconfigured(monkeypatch):
    import archive.utils.email as email_module

    monkeypatch.setattr(email_module, "_api_key", lambda: "test-key")
    monkeypatch.setenv("RESEND_FROM_ADDRESS", "Ryan <ryan@ally.redtaperecordings.com>")
    monkeypatch.delenv("RESEND_REPLY_TO_ADDRESS", raising=False)

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
            captured["json"] = json
            return _FakeResponse()

    monkeypatch.setattr(email_module.aiohttp, "ClientSession", lambda: _FakeSession())

    ok = await email_module.send_confirmation_email(
        "ryan@example.com", "https://example.com/confirm?token=abc"
    )
    assert ok is True
    assert "reply_to" not in captured["json"]
