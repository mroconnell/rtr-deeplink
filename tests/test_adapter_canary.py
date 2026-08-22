"""Tests for scripts/adapter_canary.py (WO-13) -- pure decision-logic
coverage using fixture-based fake finders, no real network calls (this
script's whole point is live per-platform re-verification, which by
definition can't be part of the hermetic pytest suite -- see the script's
own module docstring and AUDIT_EXECUTION_BRIEF.md's WO-2 entry on why this
suite stays network-free). The acceptance criterion this satisfies:
deliberately breaking one adapter's parsing (here, a fake finder returning
an empty ResolvedMeeting) must produce a real reported failure, not a
silent pass.

Plus a second, different kind of check added 2026-08-21 (WO-26): the
canary's *coverage* itself, asserting every platform `register_all_finders()`
registers has an explicit canary decision (a URL, or a documented
exclusion). That one needs no fakes or network either -- it only compares
two in-process sets.
"""

from app.platforms.base import CalendarPageError
from app.platforms.models import ResolvedMeeting
from conftest import registered_platforms
from scripts.adapter_canary import (
    CANARY_EXCLUSIONS,
    CANARY_URLS,
    check_platform,
    format_report,
    has_real_content,
    run_canary,
)


def test_every_registered_platform_is_canaried_or_explicitly_excluded():
    """The canary is only as good as its coverage, and nothing used to
    enforce that: three of the four adapters added between 2026-08-19 and
    2026-08-21 (destinyhosted, suiteone, open_media) shipped with no
    CANARY_URLS entry at all and went unmonitored until this test was
    written. This is the `alembic check` of adapter monitoring -- a new
    platform without a canary decision fails CI at PR time.

    Adding a platform means adding either a real, live-verified URL to
    CANARY_URLS or an entry to CANARY_EXCLUSIONS explaining why one can't
    exist -- never a guessed URL, which would just become a daily false
    alarm (see scripts/adapter_canary.py's own comments).
    """
    uncovered = registered_platforms() - set(CANARY_URLS) - set(CANARY_EXCLUSIONS)

    assert not uncovered, (
        f"Platform(s) {sorted(uncovered)} are registered in "
        "register_all_finders() but have no adapter-canary decision. Add a "
        "real, live-verified meeting URL to CANARY_URLS in "
        "scripts/adapter_canary.py, or add the platform to "
        "CANARY_EXCLUSIONS there with the reason no such URL exists."
    )


def test_canary_keys_are_real_registered_platform_names():
    # Keys must be the registered `AssetFinder.platform_name`, not a
    # prettier label -- otherwise the coverage test above would pass while
    # actually monitoring nothing under that name. Three real keys are
    # non-obvious ("aurora_tv", "seattle_channel", "unknown"), and this
    # also catches a platform being renamed or dropped out from under a
    # stale canary entry.
    registered = registered_platforms()

    assert not set(CANARY_URLS) - registered
    assert not set(CANARY_EXCLUSIONS) - registered


def test_no_platform_is_both_canaried_and_excluded():
    assert not set(CANARY_URLS) & set(CANARY_EXCLUSIONS)


def test_every_exclusion_states_a_reason():
    # The reason is the whole point of the exclusion set: it's what lets a
    # later session tell "deliberately can't be canaried" apart from
    # "somebody silenced a failing entry."
    for platform, reason in CANARY_EXCLUSIONS.items():
        assert reason.strip(), f"{platform} is excluded with no reason given"


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
