"""app/utils/robots_check.py and its staged hook in meeting_finder/pacing.py
(Ryan, 2026-10-02): log-only by default, enforce with ROBOTS_ENFORCE=1."""

import aiohttp
import pytest

from app.platforms.meeting_finder import fetch as fetch_module
from app.platforms.meeting_finder import pacing as pacing_module
from app.platforms.meeting_finder.fetch import Fetcher
from app.platforms.meeting_finder.pacing import pace_all_requests
from app.utils import robots_check
from app.utils.robots_rules import Rule


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    fetch_module._HOST_PACER_NEXT_AT.clear()
    robots_check.clear_cache()
    monkeypatch.delenv("ROBOTS_ENFORCE", raising=False)
    yield
    fetch_module._HOST_PACER_NEXT_AT.clear()
    robots_check.clear_cache()


async def test_check_url_uses_the_cached_rules_and_names_the_rule(monkeypatch):
    calls = []

    async def fake_fetch(origin):
        calls.append(origin)
        from app.utils.robots_rules import parse_rules

        return parse_rules("User-agent: *\nDisallow: /*.mp4$\n")

    monkeypatch.setattr(robots_check, "_fetch_rules", fake_fetch)
    allowed, rule = await robots_check.check_url("https://a.example.gov/x/vod.mp4")
    assert allowed is False and rule.pattern == "/*.mp4$"
    assert await robots_check.check_url("https://a.example.gov/page") == (True, None)
    assert calls == ["https://a.example.gov"]  # one read per host


async def test_loopback_and_robots_txt_itself_are_never_checked(monkeypatch):
    async def boom(origin):
        raise AssertionError("must not read robots.txt")

    monkeypatch.setattr(robots_check, "_fetch_rules", boom)
    assert await robots_check.check_url("http://127.0.0.1:8000/a.mp4") == (True, None)
    assert await robots_check.check_url("https://a.example.gov/robots.txt") == (
        True,
        None,
    )


async def test_unreadable_robots_is_not_a_block(monkeypatch):
    class Boom:
        def __init__(self, *a, **k):
            raise aiohttp.ClientError("boom")

    monkeypatch.setattr(robots_check.aiohttp, "ClientSession", Boom)
    assert await robots_check.check_url("https://down.example.gov/a.mp4") == (
        True,
        None,
    )
    assert "https://down.example.gov" in robots_check._UNREACHABLE


class _FakeSession:
    """Stands in for aiohttp's real network call under the pacing hook."""


async def _walk_one_request(monkeypatch, url):
    """Run one request through the pacing hook with the real network call stubbed out."""
    reached = []

    async def real_request(self, method, str_or_url, **kwargs):
        reached.append(str(str_or_url))

        class R:
            status = 200

        return R()

    monkeypatch.setattr(pacing_module, "_installed", False)
    monkeypatch.setattr(aiohttp.ClientSession, "_request", real_request)
    fetcher = Fetcher(per_host_delay_s=0.0, allow_headless=False)
    try:
        with pace_all_requests(fetcher) as stats:
            async with aiohttp.ClientSession() as session:
                try:
                    await session._request("GET", url)
                    refused = None
                except robots_check.RobotsDisallowedError as e:
                    refused = e
        return stats, reached, refused
    finally:
        await fetcher.close() if hasattr(fetcher, "close") else None


async def test_pacing_hook_is_log_only_by_default(monkeypatch):
    async def blocked(url):
        return False, Rule(False, "/*.mp4$")

    monkeypatch.setattr(robots_check, "check_url", blocked)
    stats, reached, refused = await _walk_one_request(
        monkeypatch, "https://a.example.gov/x/vod.mp4"
    )
    assert refused is None
    assert reached == ["https://a.example.gov/x/vod.mp4"]  # the request still happened
    assert stats.robots_would_skip == [("a.example.gov", "/x/vod.mp4", "/*.mp4$")]


async def test_pacing_hook_refuses_before_any_request_when_enforcing(monkeypatch):
    async def blocked(url):
        return False, Rule(False, "/*.mp4$")

    monkeypatch.setattr(robots_check, "check_url", blocked)
    monkeypatch.setenv("ROBOTS_ENFORCE", "1")
    stats, reached, refused = await _walk_one_request(
        monkeypatch, "https://a.example.gov/x/vod.mp4"
    )
    assert isinstance(refused, aiohttp.ClientError)
    assert reached == []  # no request made
    assert stats.robots_would_skip == [("a.example.gov", "/x/vod.mp4", "/*.mp4$")]


def test_verdict_rows_carry_the_robots_log_only_results(tmp_path):
    """The staging step is only useful if the results are kept: a count in the CSV, the
    full list in the JSONL."""
    import json

    from app.platforms.meeting_finder import verdict as verdict_module
    from app.platforms.meeting_finder.models import VerdictRow

    assert "robots_would_skip_count" in verdict_module.CSV_FIELDS
    row = VerdictRow(
        run_id="r",
        input_url="https://a.example.gov",
        entry_phase="start",
        path=[],
        phase_reached="start",
        robots_would_skip=[["a.example.gov", "/x/vod.mp4", "/*.mp4$"]],
    )
    out = tmp_path / "v.csv"
    verdict_module.append_verdict(out, row)
    header, line = out.read_text().splitlines()[:2]
    assert "robots_would_skip_count" in header
    detail = json.loads((tmp_path / "v.csv.jsonl").read_text().splitlines()[0])
    assert detail["robots_would_skip"] == [["a.example.gov", "/x/vod.mp4", "/*.mp4$"]]
