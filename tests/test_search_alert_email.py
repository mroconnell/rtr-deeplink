"""Tests for the saved-search alert digest email
(archive/utils/email.py's send_search_alert_digest). Resend's HTTP API is
faked via the same _FakeSession/_FakeResponse pattern
tests/test_lifecycle_emails.py already uses -- no real network call, and
no real email is ever sent by this suite.
"""

import archive.utils.email as email_module


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


def _setup(monkeypatch, captured):
    monkeypatch.setattr(email_module, "_api_key", lambda: "test-key")
    monkeypatch.setenv("RESEND_FROM_ADDRESS", "Ryan <ryan@ally.redtaperecordings.com>")
    monkeypatch.setattr(email_module.aiohttp, "ClientSession", lambda: _FakeSession(captured))


async def test_single_match_subject_matches_approved_shape(monkeypatch):
    captured = {}
    _setup(monkeypatch, captured)

    ok = await email_module.send_search_alert_digest(
        "ryan@example.com",
        first_name="Ryan",
        groups=[
            {
                "keyword": "traffic",
                "unsubscribe_url": "https://redtaperecordings.com/alerts/unsubscribe?token=abc",
                "matches": [
                    {
                        "title": "City Council Meeting",
                        "date": "2026-08-01",
                        "jurisdiction": "Napa, CA",
                        "page_url": "https://redtaperecordings.com/m/napa-city-council?t=120",
                        "quote_html": 'discussion of <mark class="search-match">traffic</mark> calming',
                    }
                ],
            }
        ],
    )
    assert ok is True
    # Approved single-match subject shape, no "(+N more)" suffix for exactly one match.
    assert captured["json"]["subject"] == 'Somebody said "traffic"'
    assert "Hi Ryan," in captured["json"]["html"]
    assert "City Council Meeting" in captured["json"]["html"]
    assert "Hear it in context" in captured["json"]["html"]
    assert "Unsubscribe from this alert" in captured["json"]["html"]
    assert "alerts/unsubscribe?token=abc" in captured["json"]["html"]


async def test_multiple_matches_subject_shows_plus_n_more(monkeypatch):
    captured = {}
    _setup(monkeypatch, captured)

    await email_module.send_search_alert_digest(
        "ryan@example.com",
        first_name=None,
        groups=[
            {
                "keyword": "traffic",
                "unsubscribe_url": "https://redtaperecordings.com/alerts/unsubscribe?token=a",
                "matches": [
                    {"title": "A", "date": None, "jurisdiction": None, "page_url": "https://x/1", "quote_html": None},
                    {"title": "B", "date": None, "jurisdiction": None, "page_url": "https://x/2", "quote_html": None},
                ],
            }
        ],
    )
    assert captured["json"]["subject"] == 'Somebody said "traffic" (+1 more)'
    assert "Hi there," in captured["json"]["html"]


async def test_keyword_less_saved_search_uses_fallback_subject(monkeypatch):
    captured = {}
    _setup(monkeypatch, captured)

    await email_module.send_search_alert_digest(
        "ryan@example.com",
        first_name=None,
        groups=[
            {
                "keyword": None,
                "unsubscribe_url": "https://redtaperecordings.com/alerts/unsubscribe?token=a",
                "matches": [
                    {"title": "A", "date": "2026-08-01", "jurisdiction": "Napa, CA", "page_url": "https://x/1", "quote_html": None},
                ],
            }
        ],
    )
    assert captured["json"]["subject"] == "1 new meeting matches your saved searches"
    # No quote block for a match with no locatable segment -- still shows
    # the plain title/date/link line, per find_matching_segment()'s None case.
    assert "A" in captured["json"]["html"]
    assert "Hear it in context" in captured["json"]["html"]


async def test_multiple_groups_each_get_their_own_unsubscribe_link(monkeypatch):
    captured = {}
    _setup(monkeypatch, captured)

    await email_module.send_search_alert_digest(
        "ryan@example.com",
        first_name=None,
        groups=[
            {
                "keyword": "traffic",
                "unsubscribe_url": "https://redtaperecordings.com/alerts/unsubscribe?token=first",
                "matches": [{"title": "A", "date": None, "jurisdiction": None, "page_url": "https://x/1", "quote_html": None}],
            },
            {
                "keyword": "flock",
                "unsubscribe_url": "https://redtaperecordings.com/alerts/unsubscribe?token=second",
                "matches": [{"title": "B", "date": None, "jurisdiction": None, "page_url": "https://x/2", "quote_html": None}],
            },
        ],
    )
    assert "token=first" in captured["json"]["html"]
    assert "token=second" in captured["json"]["html"]


async def test_sitewide_unsubscribe_footer_still_appended(monkeypatch):
    captured = {}
    _setup(monkeypatch, captured)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://redtaperecordings.com")

    await email_module.send_search_alert_digest(
        "ryan@example.com",
        first_name=None,
        groups=[
            {
                "keyword": "traffic",
                "unsubscribe_url": "https://redtaperecordings.com/alerts/unsubscribe?token=a",
                "matches": [{"title": "A", "date": None, "jurisdiction": None, "page_url": "https://x/1", "quote_html": None}],
            }
        ],
    )
    # The existing sitewide footer link (email= query param) is a separate,
    # additional link, not replaced by the per-alert one.
    assert "email=ryan%40example.com" in captured["json"]["html"]
