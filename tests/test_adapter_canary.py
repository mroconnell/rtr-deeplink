"""Tests for scripts/adapter_canary.py (WO-13) -- pure decision-logic
coverage using fixture-based fake finders, no real network calls (this
script's whole point is live per-platform re-verification, which by
definition can't be part of the hermetic pytest suite -- see the script's
own module docstring and AUDIT_EXECUTION_BRIEF.md's WO-2 entry on why this
suite stays network-free). The acceptance criterion this satisfies:
deliberately breaking one adapter's parsing (here, a fake finder returning
an empty ResolvedMeeting) must produce a real reported failure, not a
silent pass.
"""

from app.platforms.base import CalendarPageError
from app.platforms.models import ResolvedMeeting
from scripts.adapter_canary import (
    check_platform,
    format_report,
    has_real_content,
    run_canary,
)


def _meeting(**overrides) -> ResolvedMeeting:
    base = {"platform": "test", "source_url": "https://example.com/1"}
    base.update(overrides)
    return ResolvedMeeting(**base)


def test_has_real_content_true_with_segments():
    assert (
        has_real_content(_meeting(segments=[{"start": 0, "end": 1, "text": "hi"}]))
        is True
    )


def test_has_real_content_true_with_video_url_only():
    assert (
        has_real_content(_meeting(video_url="https://example.com/video.m3u8")) is True
    )


def test_has_real_content_false_when_empty():
    assert has_real_content(_meeting()) is False


class _FakeFinder:
    def __init__(self, result=None, error=None):
        self._result = result
        self._error = error

    async def resolve(self, url):
        if self._error:
            raise self._error
        return self._result


async def test_check_platform_ok_when_finder_returns_real_content(monkeypatch):
    monkeypatch.setattr("scripts.adapter_canary.detect_platform", lambda url: "fake")
    monkeypatch.setattr(
        "scripts.adapter_canary.get_finder",
        lambda platform: _FakeFinder(
            result=_meeting(segments=[{"start": 0, "end": 1, "text": "hi"}])
        ),
    )

    result = await check_platform("fake", "https://example.com/1")

    assert result == {
        "platform": "fake",
        "url": "https://example.com/1",
        "ok": True,
        "reason": None,
    }


async def test_check_platform_fails_when_finder_returns_empty_content(monkeypatch):
    # This is the "deliberately break one adapter's parsing" acceptance
    # case -- a finder that runs without raising but produces nothing
    # real must still be reported as a failure, not a silent pass.
    monkeypatch.setattr("scripts.adapter_canary.detect_platform", lambda url: "fake")
    monkeypatch.setattr(
        "scripts.adapter_canary.get_finder",
        lambda platform: _FakeFinder(result=_meeting()),
    )

    result = await check_platform("fake", "https://example.com/1")

    assert result["ok"] is False
    assert result["reason"] == "resolve returned no real content"


async def test_check_platform_fails_when_finder_raises(monkeypatch):
    monkeypatch.setattr("scripts.adapter_canary.detect_platform", lambda url: "fake")
    monkeypatch.setattr(
        "scripts.adapter_canary.get_finder",
        lambda platform: _FakeFinder(error=RuntimeError("site returned 500")),
    )

    result = await check_platform("fake", "https://example.com/1")

    assert result["ok"] is False
    assert "RuntimeError" in result["reason"]
    assert "site returned 500" in result["reason"]


async def test_check_platform_ok_when_calendar_page_has_candidates(monkeypatch):
    # CivicPlus's real canary URL is a listing page with no single-meeting
    # URL shape at all -- a CalendarPageError with real rows found is the
    # correct, expected outcome, not a failure.
    monkeypatch.setattr("scripts.adapter_canary.detect_platform", lambda url: "fake")
    monkeypatch.setattr(
        "scripts.adapter_canary.get_finder",
        lambda platform: _FakeFinder(
            error=CalendarPageError(
                "multiple meetings",
                candidates=[{"title": "t", "date": "d", "url": "u"}],
            )
        ),
    )

    result = await check_platform("fake", "https://example.com/1")

    assert result == {
        "platform": "fake",
        "url": "https://example.com/1",
        "ok": True,
        "reason": None,
    }


async def test_check_platform_fails_when_calendar_page_has_no_candidates(monkeypatch):
    # This IS a real regression signal -- a listing page that used to have
    # rows and now has none.
    monkeypatch.setattr("scripts.adapter_canary.detect_platform", lambda url: "fake")
    monkeypatch.setattr(
        "scripts.adapter_canary.get_finder",
        lambda platform: _FakeFinder(
            error=CalendarPageError("no meetings found", candidates=[])
        ),
    )

    result = await check_platform("fake", "https://example.com/1")

    assert result["ok"] is False
    assert result["reason"] == "calendar page returned zero candidates"


async def test_run_canary_reports_each_platform_independently(monkeypatch):
    finders = {
        "good": _FakeFinder(
            result=_meeting(segments=[{"start": 0, "end": 1, "text": "hi"}])
        ),
        "broken": _FakeFinder(result=_meeting()),
    }
    monkeypatch.setattr("scripts.adapter_canary.detect_platform", lambda url: url)
    monkeypatch.setattr(
        "scripts.adapter_canary.get_finder", lambda platform: finders[platform]
    )

    results = await run_canary({"good": "good", "broken": "broken"})

    by_platform = {r["platform"]: r["ok"] for r in results}
    assert by_platform == {"good": True, "broken": False}


def test_format_report_lists_only_failures():
    results = [
        {"platform": "good", "url": "u1", "ok": True, "reason": None},
        {
            "platform": "broken",
            "url": "u2",
            "ok": False,
            "reason": "resolve returned no real content",
        },
    ]

    report = format_report(results)

    assert "1/2 platforms OK" in report
    assert "FAIL broken: resolve returned no real content (u2)" in report
    assert "FAIL good" not in report
