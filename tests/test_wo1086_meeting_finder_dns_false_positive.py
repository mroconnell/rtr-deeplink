"""WO-1086: Meeting Finder was reporting `dns-unresolvable` for real
governments whose site resolves and serves fine -- see BACKLOG_DONE.md's
WO-1086 entry for the full writeup. Two real, live-confirmed shapes of
the underlying bug (2026-09-26), covered here with SYNTHETIC fixtures
(hand-built `dns_lookup()`-shaped dicts and monkeypatched phase
functions, not fetched from a real page) since both shapes are already
confirmed against real domains -- this file's job is to guard the fix,
not to re-discover it:

  1. `start.py` used to add BOTH `https://{domain}/` and
     `https://www.{domain}/` as starting points unconditionally, even
     when `dns_lookup()` itself already knew only one of the two
     actually resolves. Confirmed live in both directions: a subdomain
     host (streaming.easdpa.org) has no `www.` sibling at all; several
     real districts (ppps.org, hartisd.net, ...) have the OPPOSITE
     asymmetry -- no bare-apex A/CNAME record, only `www.` resolves.
     Either doomed variant raised a DNS error that `fetch.py` reported
     as that FORK's own `dns-unresolvable` outcome.
  2. `runner.py`'s `_pick_outcome()` ranks `dns-unresolvable` (35) above
     `no-meeting-nor-video` (10), so that one doomed fork's outcome could
     win the whole government's verdict even though another fork (or the
     same fork, via a later real page) found real content. Confirmed
     live even on a fork whose OWN homepage fetch succeeded and then
     Hop followed a real link to some unrelated third-party host that
     happened to be dead (jsd117.org -> jsd117.on.spiceworks.com).

The fix: (a) `start()` only adds whichever of apex/`www.` `dns_lookup()`
says actually resolves; (b) once `start()` has confirmed at least one
real host resolves (`_WalkState.dns_gate_passed`), `run_one()` drops any
`dns-unresolvable` collected later from the verdict pick -- it can only
be a secondary/downstream failure, never a sign THIS government's own
site is unreachable, since that already would have short-circuited the
walk before any fork ran (`start()`'s own DNS gate, unchanged, still
returns `dns-unresolvable` directly for a domain where neither apex nor
`www.` resolves -- see `test_entry_start_dns_dead_reports_outcome` in
tests/test_wo1030_meeting_finder_runner.py, which this file doesn't
duplicate).
"""

from __future__ import annotations

import pytest

from app.platforms.meeting_finder import runner, start
from app.platforms.meeting_finder.fetch import Fetcher, FetchResult
from app.platforms.meeting_finder.identify import IdentifyResult
from app.platforms.meeting_finder.models import (
    OUTCOME_DNS_UNRESOLVABLE,
    OUTCOME_NO_MEETING_NOR_VIDEO,
    FinderInput,
    ResolveResult,
)
from app.platforms.meeting_finder.start import StartResult


@pytest.fixture(autouse=True)
def _no_real_fetcher_io(monkeypatch):
    """Belt and braces for the `runner.py` tests below: fail loudly if
    anything reaches a real `Fetcher.fetch()` -- every phase function is
    monkeypatched per test, so this should never actually fire. (The
    `start.py` tests above don't go through `runner.run_one()` at all,
    so this fixture never applies to them.)"""

    async def _boom(self, url, **kwargs):  # noqa: ANN001
        raise AssertionError(f"unexpected real fetch: {url}")

    monkeypatch.setattr(runner.Fetcher, "fetch", _boom)


# --- start.py: which homepage variants get added --------------------------


def _dns_info(*, apex_resolves: bool, www_resolves: bool) -> dict:
    """A SYNTHETIC `dns_lookup()`-shaped dict -- the real function
    (`scripts/wo282_recon.py`) returns exactly these keys; only the two
    that matter to `start()`'s own homepage-variant logic are varied
    here, matching the real shape confirmed live for both asymmetries
    (see this module's own docstring)."""
    return {
        "apex_a": ["203.0.113.10"] if apex_resolves else [],
        "apex_cname": "",
        "www_a": ["203.0.113.10"] if www_resolves else [],
        "www_cname": "",
        "resolving_subdomains": [],
        "resolving_vendor_labels": [],
    }


def _empty_robots() -> dict:
    return {"crawl_delay_seconds": None, "error": None}


def _empty_sitemap() -> dict:
    return {"found": False, "error": None, "urls": []}


@pytest.mark.asyncio
async def test_subdomain_host_does_not_get_a_doomed_www_sibling(monkeypatch):
    """A host that's already a subdomain (streaming.easdpa.org-shaped:
    the apex resolves, `www.` does not -- confirmed live 2026-09-26 for
    5 real governments, none of which has a `www.` sibling) must not get
    `https://www.<host>/` added as a starting point."""

    async def fake_dns_resolves(domain):
        return _dns_info(apex_resolves=True, www_resolves=False)

    monkeypatch.setattr(start, "_dns_resolves", fake_dns_resolves)
    monkeypatch.setattr(start, "fetch_live_robots_v2", lambda domain: _empty_robots())
    monkeypatch.setattr(
        start, "fetch_live_sitemap_v2", lambda domain, robots: _empty_sitemap()
    )

    fetcher = Fetcher(max_fetches=12)
    result = await start.start("streaming.example.org", fetcher, guess_subdomains=False)

    assert "https://www.streaming.example.org/" not in result.starting_points
    assert "https://streaming.example.org/" in result.starting_points


@pytest.mark.asyncio
async def test_bare_apex_without_a_record_does_not_get_a_doomed_fetch(monkeypatch):
    """The OPPOSITE asymmetry -- confirmed live for ppps.org,
    hartisd.net and 21 more real districts 2026-09-26: no bare-apex A/
    CNAME record at all, only `www.` resolves (mostly Apptegy-hosted).
    `https://{domain}/` and `http://{domain}/` must not be added when
    the apex itself doesn't resolve."""

    async def fake_dns_resolves(domain):
        return _dns_info(apex_resolves=False, www_resolves=True)

    monkeypatch.setattr(start, "_dns_resolves", fake_dns_resolves)
    monkeypatch.setattr(start, "fetch_live_robots_v2", lambda domain: _empty_robots())
    monkeypatch.setattr(
        start, "fetch_live_sitemap_v2", lambda domain, robots: _empty_sitemap()
    )

    fetcher = Fetcher(max_fetches=12)
    result = await start.start("apexless.example.org", fetcher, guess_subdomains=False)

    assert "https://apexless.example.org/" not in result.starting_points
    assert "http://apexless.example.org/" not in result.starting_points
    assert "https://www.apexless.example.org/" in result.starting_points


@pytest.mark.asyncio
async def test_both_resolving_keeps_all_three_homepage_variants(monkeypatch):
    """Regression guard: an ordinary government where both the apex and
    `www.` resolve keeps getting all three homepage variants, in the
    same order docs/MEETING_FINDER.md documents."""

    async def fake_dns_resolves(domain):
        return _dns_info(apex_resolves=True, www_resolves=True)

    monkeypatch.setattr(start, "_dns_resolves", fake_dns_resolves)
    monkeypatch.setattr(start, "fetch_live_robots_v2", lambda domain: _empty_robots())
    monkeypatch.setattr(
        start, "fetch_live_sitemap_v2", lambda domain, robots: _empty_sitemap()
    )

    fetcher = Fetcher(max_fetches=12)
    result = await start.start("ordinary.example.org", fetcher, guess_subdomains=False)

    assert result.starting_points[:3] == [
        "https://ordinary.example.org/",
        "https://www.ordinary.example.org/",
        "http://ordinary.example.org/",
    ]


# --- runner.py: a secondary fork's DNS failure must not win the verdict ---


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


def _page(url: str) -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        status=200,
        html="<html></html>",
        access_mode="plain",
        outcome=None,
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
        page=_page(url),
    )


@pytest.mark.asyncio
async def test_secondary_fork_dns_failure_does_not_override_real_finding(monkeypatch):
    """Two starting points from `start()` (meaning the DNS gate already
    confirmed at least one real host resolves): the FIRST fork resolves
    fine and finds nothing meeting-shaped (`no-meeting-nor-video`); the
    SECOND (a doomed `www.` sibling or a downstream dead link -- the
    mechanism doesn't matter here) reports `dns-unresolvable`. The final
    verdict must be the real finding, not the secondary DNS failure --
    this is the exact shape confirmed live for ppps.org and 22 more real
    districts 2026-09-26 (BACKLOG_DONE.md's WO-1086 entry)."""
    fi = FinderInput(url="https://example.gov/", entry="start")
    points = ["https://example.gov/", "https://www.example.gov/"]

    async def fake_start(domain_or_url, fetcher, **kwargs):
        return StartResult(starting_points=points, outcome=None)

    async def fake_identify(url, fetcher, *, platform_hint=None, page=None):
        if url == points[1]:
            return _identify_with_outcome(url, OUTCOME_DNS_UNRESOLVABLE)
        return _identify_with_outcome(url, None)

    async def fake_resolve(candidates, finder_input, *, max_tries):
        return _no_result(), None

    monkeypatch.setattr(runner, "run_start", fake_start)
    monkeypatch.setattr(runner, "identify", fake_identify)
    monkeypatch.setattr(runner, "rank_hops", lambda page, **kwargs: [])
    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)

    row = await runner.run_one(fi, run_id="wo1084-a", max_forks=3, max_hops=0)

    assert row.outcome == OUTCOME_NO_MEETING_NOR_VIDEO
    assert OUTCOME_DNS_UNRESOLVABLE not in (row.note or "")


@pytest.mark.asyncio
async def test_all_forks_dns_dead_after_gate_passed_falls_back_to_no_meeting(
    monkeypatch,
):
    """Degenerate case: the DNS gate passed (so this government's own
    site is confirmed reachable), but every fork this walk actually
    tried happened to hit a `dns-unresolvable` fetch (e.g. every one was
    a downstream dead link). The verdict must still fall back to
    `no-meeting-nor-video`, not report the whole government as DNS-dead
    -- that would be factually wrong given the gate already passed."""
    fi = FinderInput(url="https://example.gov/", entry="start")
    points = ["https://example.gov/", "https://www.example.gov/"]

    async def fake_start(domain_or_url, fetcher, **kwargs):
        return StartResult(starting_points=points, outcome=None)

    async def fake_identify(url, fetcher, *, platform_hint=None, page=None):
        return _identify_with_outcome(url, OUTCOME_DNS_UNRESOLVABLE)

    async def fake_resolve(candidates, finder_input, *, max_tries):
        return _no_result(), None

    monkeypatch.setattr(runner, "run_start", fake_start)
    monkeypatch.setattr(runner, "identify", fake_identify)
    monkeypatch.setattr(runner, "rank_hops", lambda page, **kwargs: [])
    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)

    row = await runner.run_one(fi, run_id="wo1084-b", max_forks=3, max_hops=0)

    assert row.outcome == OUTCOME_NO_MEETING_NOR_VIDEO


@pytest.mark.asyncio
async def test_genuinely_dead_domain_still_reports_dns_unresolvable(monkeypatch):
    """Negative control, same shape as
    `test_entry_start_dns_dead_reports_outcome`
    (tests/test_wo1030_meeting_finder_runner.py) -- kept here too so this
    file alone documents all three outcomes WO-1086 had to get right.
    When neither apex nor `www.` resolves, `start()` itself never returns
    real starting points (`_WalkState.dns_gate_passed` never gets set),
    so the true `dns-unresolvable` verdict for a real dead domain is
    unaffected by this fix."""
    fi = FinderInput(url="https://truly-dead.example.org/", entry="start")

    async def fake_start(domain_or_url, fetcher, **kwargs):
        return StartResult(
            starting_points=[],
            outcome=OUTCOME_DNS_UNRESOLVABLE,
            note="neither apex nor www. resolved",
        )

    monkeypatch.setattr(runner, "run_start", fake_start)

    row = await runner.run_one(fi, run_id="wo1084-c")

    assert row.outcome == OUTCOME_DNS_UNRESOLVABLE
    assert row.phase_reached == "start"
