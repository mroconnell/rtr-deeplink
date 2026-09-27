"""WO-1122: a block found on a SECONDARY fetch must not become the
government's verdict when its own site was actually readable -- see
BACKLOG_DONE.md's WO-1122 entry and this repo's own measured finding
(2026-09-26, `nps` calibration run): all 1,134 governments with a block
outcome had fetched 3+ pages first, none was blocked on its first page,
and 805 reached the Hop phase. Real example: primeroschool.org's homepage
loaded fine; a Start-GUESSED vendor subdomain
(`agenda.primeroschool.org`) was refused; the whole government still came
back `blocked-browser-headers`.

Everything here is SYNTHETIC (hand-built `FetchResult`/`IdentifyResult`
fixtures and monkeypatched phase functions, matching the exact shapes
`tests/test_wo1086_meeting_finder_dns_false_positive.py` already uses for
the sibling DNS-false-positive bug) -- the real bug is already confirmed
live; this file's job is to guard the fix, not re-discover it.
"""

from __future__ import annotations

import pytest

from app.platforms.meeting_finder import runner
from app.platforms.meeting_finder.fetch import FetchResult
from app.platforms.meeting_finder.identify import IdentifyResult
from app.platforms.meeting_finder.models import (
    OUTCOME_NO_MEETING_NOR_VIDEO,
    OUTCOME_SITE_BROKEN,
    FinderInput,
    ResolveResult,
)
from app.platforms.meeting_finder.start import StartResult


@pytest.fixture(autouse=True)
def _no_real_fetcher_io(monkeypatch):
    """Same belt-and-braces guard as WO-1086's own test file: every phase
    function is monkeypatched per test, so a real `Fetcher.fetch()` call
    should never actually fire."""

    async def _boom(self, url, **kwargs):  # noqa: ANN001
        raise AssertionError(f"unexpected real fetch: {url}")

    monkeypatch.setattr(runner.Fetcher, "fetch", _boom)


def _no_result() -> ResolveResult:
    return ResolveResult(
        candidate=None,
        tier=None,
        platform=None,
        video_url=None,
        has_segments=False,
        duration_seconds=None,
        outcome=OUTCOME_NO_MEETING_NOR_VIDEO,
        note="nothing found",
    )


def _page(url: str, *, outcome=None) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        status=200 if outcome is None else None,
        html="<html></html>" if outcome is None else None,
        access_mode="plain",
        outcome=outcome,
        challenge=False,
        wayback_timestamp=None,
        links_only=False,
        elapsed_ms=1,
    )


def _identify_with_outcome(url: str, outcome) -> IdentifyResult:
    return IdentifyResult(
        input_url=url,
        final_url=url,
        platform=None,
        account_url=None,
        supported=None,
        web_host_hint=None,
        signals=[],
        youtube_leads=[],
        outcome=outcome,
        guess_queue_row=None,
        page=_page(url, outcome=outcome),
    )


def _fake_run(monkeypatch, points, identify_by_url, *, resolve_outcome=None):
    async def fake_start(domain_or_url, fetcher, **kwargs):
        return StartResult(starting_points=points, outcome=None)

    async def fake_identify(url, fetcher, *, platform_hint=None, page=None):
        return identify_by_url(url)

    async def fake_resolve(candidates, finder_input, *, max_tries):
        return resolve_outcome or _no_result(), None

    monkeypatch.setattr(runner, "run_start", fake_start)
    monkeypatch.setattr(runner, "identify", fake_identify)
    monkeypatch.setattr(runner, "rank_hops", lambda page, **kwargs: [])
    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)


# --- Rule 2: a secondary-host block must not override a readable own site


@pytest.mark.asyncio
async def test_secondary_host_block_does_not_override_real_finding(monkeypatch):
    """The measured primeroschool.org shape: the homepage (own host) reads
    fine and finds nothing meeting-shaped; a Start-guessed vendor
    subdomain (a DIFFERENT host) is blocked. The verdict must be the real
    (if empty) finding from the own-host fork, not the secondary block --
    with the refused URL still recorded in the note so it isn't lost."""
    fi = FinderInput(url="https://primeroschool.org/", entry="start")
    points = [
        "https://primeroschool.org/",
        "https://agenda.primeroschool.org/",
    ]

    def identify_by_url(url):
        if url == points[1]:
            return _identify_with_outcome(url, "blocked-browser-headers")
        return _identify_with_outcome(url, None)

    _fake_run(monkeypatch, points, identify_by_url)

    row = await runner.run_one(fi, run_id="wo1122-a", max_forks=3, max_hops=0)

    assert row.outcome == OUTCOME_NO_MEETING_NOR_VIDEO
    assert row.blocked_url == ""
    assert "agenda.primeroschool.org" in (row.note or "")
    assert "secondary" in (row.note or "")


# --- Rule 3: a block on the government's OWN host still wins -------------


@pytest.mark.asyncio
async def test_own_homepage_block_still_wins(monkeypatch):
    """The opposite case: the government's OWN homepage itself is
    blocked. This is real, useful evidence and must still be the
    verdict."""
    fi = FinderInput(url="https://blocked-city.example.gov/", entry="start")
    points = ["https://blocked-city.example.gov/"]

    def identify_by_url(url):
        return _identify_with_outcome(url, "cloudflare-challenge-blocked")

    _fake_run(monkeypatch, points, identify_by_url)

    row = await runner.run_one(fi, run_id="wo1122-b", max_forks=3, max_hops=0)

    assert row.outcome == "cloudflare-challenge-blocked"
    assert row.blocked_url == "https://blocked-city.example.gov/"


@pytest.mark.asyncio
async def test_own_meetings_page_block_still_wins(monkeypatch):
    """A block on the government's own host wins when EVERY own-host form
    Start tried was refused -- `www.` counts as the same "own host" as the
    bare apex. Both forms blocked here (unlike the WO-1134 test below,
    where one own-host form succeeds), so there is no real walk result to
    prefer over the block."""
    fi = FinderInput(url="https://example.gov/", entry="start")
    points = ["https://example.gov/", "https://www.example.gov/"]

    def identify_by_url(url):
        return _identify_with_outcome(url, "blocked-waf-akamai")

    _fake_run(monkeypatch, points, identify_by_url)

    row = await runner.run_one(fi, run_id="wo1122-c", max_forks=3, max_hops=0)

    assert row.outcome == "blocked-waf-akamai"
    assert row.blocked_url in points


@pytest.mark.asyncio
async def test_own_host_block_demoted_when_another_own_host_form_worked(monkeypatch):
    """WO-1134: this is the shape that used to be `test_own_meetings_page_
    block_still_wins` above, before the fix -- the apex loads fine
    (nothing meeting-shaped found) and `www.` is blocked. Both are the
    government's own host per `_own_host_set()`, so WO-1122's own-host
    check alone let the `www.` block win. That's the measured bug
    (BACKLOG_DONE.md's WO-1134 entry, 212 of 384 `site-broken`
    governments had a working sibling form): the government's site IS
    readable (via the apex), so the real walk result must win, with the
    `www.` refusal demoted to the note."""
    fi = FinderInput(url="https://example.gov/", entry="start")
    points = ["https://example.gov/", "https://www.example.gov/"]

    def identify_by_url(url):
        if url == points[1]:
            return _identify_with_outcome(url, "blocked-waf-akamai")
        return _identify_with_outcome(url, None)

    _fake_run(monkeypatch, points, identify_by_url)

    row = await runner.run_one(fi, run_id="wo1134-a", max_forks=3, max_hops=0)

    assert row.outcome == OUTCOME_NO_MEETING_NOR_VIDEO
    assert row.blocked_url == ""
    assert "www.example.gov" in (row.note or "")
    assert "secondary" in (row.note or "")


# --- Rule 4: site-broken classification -----------------------------------


@pytest.mark.asyncio
async def test_own_site_broken_reports_site_broken_not_dns_unresolvable(monkeypatch):
    """A TLS certificate/handshake failure or a refused connection on the
    government's own starting page is a DIFFERENT, more actionable finding
    than `dns-unresolvable` -- the domain resolves, the site itself is
    broken. `fetch.py`'s own unit tests (test_meeting_finder_fetch.py)
    cover the exception -> outcome mapping directly; this guards that the
    outcome survives runner.py's own-host override intact."""
    fi = FinderInput(url="https://broken-site.example.gov/", entry="start")
    points = ["https://broken-site.example.gov/"]

    def identify_by_url(url):
        return _identify_with_outcome(url, OUTCOME_SITE_BROKEN)

    _fake_run(monkeypatch, points, identify_by_url)

    row = await runner.run_one(fi, run_id="wo1122-d", max_forks=3, max_hops=0)

    assert row.outcome == OUTCOME_SITE_BROKEN
    assert row.blocked_url == "https://broken-site.example.gov/"
    assert "current domain" in (row.try_next or "")


@pytest.mark.asyncio
async def test_secondary_site_broken_does_not_override_real_finding(monkeypatch):
    """Same secondary-host override as the block-outcome case above, for
    `site-broken` specifically -- a guessed vendor subdomain with a
    broken certificate is not evidence the government's OWN site is
    broken."""
    fi = FinderInput(url="https://primeroschool.org/", entry="start")
    points = [
        "https://primeroschool.org/",
        "https://video.primeroschool.org/",
    ]

    def identify_by_url(url):
        if url == points[1]:
            return _identify_with_outcome(url, OUTCOME_SITE_BROKEN)
        return _identify_with_outcome(url, None)

    _fake_run(monkeypatch, points, identify_by_url)

    row = await runner.run_one(fi, run_id="wo1122-e", max_forks=3, max_hops=0)

    assert row.outcome == OUTCOME_NO_MEETING_NOR_VIDEO
    assert row.blocked_url == ""
    assert "video.primeroschool.org" in (row.note or "")


# --- Rule 1: the refused URL is recorded even for the own-host case ------


@pytest.mark.asyncio
async def test_blocked_url_field_matches_the_refused_url(monkeypatch):
    fi = FinderInput(url="https://onlyblocked.example.gov/", entry="start")
    points = ["https://onlyblocked.example.gov/"]

    def identify_by_url(url):
        return _identify_with_outcome(url, "blocked-headless")

    _fake_run(monkeypatch, points, identify_by_url)

    row = await runner.run_one(fi, run_id="wo1122-f", max_forks=3, max_hops=0)

    assert row.outcome == "blocked-headless"
    assert row.blocked_url == "https://onlyblocked.example.gov/"
