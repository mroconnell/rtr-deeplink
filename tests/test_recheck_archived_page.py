"""Tests for app.main._recheck_archived_page() -- the shared resolve+push
logic behind the opportunistic stale-page recheck, GET /admin/
recheck-archive-page, and (new) scripts/backfill_archived_pages.py. Never
tested directly before this pass. Mocks the adapter's resolve() and the
Archive push, no real network call.
"""

from app.main import _recheck_archived_page
from app.platforms.models import ResolvedMeeting, TranscriptSegment


class _FakeFinder:
    def __init__(self, result):
        self._result = result

    async def resolve(self, url):
        return self._result


def _real_result(**overrides):
    defaults = dict(
        platform="swagit",
        source_url="https://example.new.swagit.com/videos/1",
        title="Recheck Test Meeting",
        jurisdiction="Long Beach, CA",
        segments=[TranscriptSegment(start=0.0, end=1.0, text="hello")],
        agenda_items=[],
        transcript_warnings=[],
        video_warnings=[],
    )
    defaults.update(overrides)
    return ResolvedMeeting(**defaults)


async def test_dry_run_resolves_but_never_pushes(monkeypatch):
    pushed = {}

    async def _fake_push(payload, normalized):
        pushed["called"] = True
        return True

    monkeypatch.setattr("app.main.get_finder", lambda platform: _FakeFinder(_real_result()))
    monkeypatch.setattr("app.main.archive_client.push", _fake_push)

    result = await _recheck_archived_page(
        "https://example.new.swagit.com/videos/1", "https://example.new.swagit.com/videos/1", "swagit", dry_run=True
    )

    assert result["pushed"] is True  # real content *was* found...
    assert "called" not in pushed  # ...but nothing was actually sent to the Archive
    assert result["jurisdiction"] == "Long Beach, CA"


async def test_real_run_pushes_when_content_found(monkeypatch):
    pushed = {}

    async def _fake_push(payload, normalized):
        pushed["called"] = True
        pushed["payload"] = payload
        return True

    monkeypatch.setattr("app.main.get_finder", lambda platform: _FakeFinder(_real_result()))
    monkeypatch.setattr("app.main.archive_client.push", _fake_push)

    result = await _recheck_archived_page(
        "https://example.new.swagit.com/videos/1", "https://example.new.swagit.com/videos/1", "swagit"
    )

    assert result["pushed"] is True
    assert pushed["called"] is True
    assert pushed["payload"]["jurisdiction"] == "Long Beach, CA"


async def test_no_real_content_never_pushes_even_without_dry_run(monkeypatch):
    empty_result = _real_result(segments=[], agenda_items=[], agenda_link=None)
    pushed = {}

    async def _fake_push(payload, normalized):
        pushed["called"] = True
        return True

    monkeypatch.setattr("app.main.get_finder", lambda platform: _FakeFinder(empty_result))
    monkeypatch.setattr("app.main.archive_client.push", _fake_push)

    result = await _recheck_archived_page(
        "https://example.new.swagit.com/videos/2", "https://example.new.swagit.com/videos/2", "swagit"
    )

    assert result["pushed"] is False
    assert "called" not in pushed


async def test_unsupported_platform_returns_an_error_not_a_crash(monkeypatch):
    result = await _recheck_archived_page("https://example.com/x", "https://example.com/x", "not-a-real-platform")
    assert result["error"] == "unsupported_platform"


async def test_resolve_exception_returns_an_error_not_a_crash(monkeypatch):
    class _RaisingFinder:
        async def resolve(self, url):
            raise RuntimeError("boom")

    monkeypatch.setattr("app.main.get_finder", lambda platform: _RaisingFinder())

    result = await _recheck_archived_page("https://example.com/x", "https://example.com/x", "swagit")
    assert result["error"] == "resolve_failed"
