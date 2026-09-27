"""WO-1134: a block-like outcome (`blocked-*`, `site-broken`) confined to
ONE own-host form must not outrank a real walk result from a DIFFERENT
own-host form that actually loaded -- see BACKLOG_DONE.md's WO-1134 entry
for the full writeup.

WO-1122 already stopped a refusal on a SECONDARY host (a guessed vendor
subdomain, an off-site link) from winning the verdict when the
government's own site was readable -- see
tests/test_wo1122_meeting_finder_secondary_block.py. But it only checked
"did a block happen on the government's OWN host" (apex or `www.`); it
never checked whether some OTHER own-host form actually loaded. Measured
real bug (2026-09-26, `nps` run): of 384 governments verdicted
`site-broken`, a separate live probe found 212 whose SAME domain works in
some form -- most often the bare apex's TLS certificate is broken while
`www.` (or plain http) loads and gets walked normally, and the apex's own
refusal (still "own host") kept outranking that real walk.

The fix: `_WalkState.own_host_page_fetched` (set the first time any
own-host starting page returns real HTML, regardless of which form) --
a block-like outcome on the own host only survives to become the verdict
when this is still `False`, i.e. no own-host form ever loaded anywhere in
the walk.

Everything here is SYNTHETIC (hand-built `FetchResult`/`IdentifyResult`
fixtures and monkeypatched phase functions), matching the exact shapes
tests/test_wo1122_meeting_finder_secondary_block.py and
tests/test_wo1086_meeting_finder_dns_false_positive.py already use for
the sibling bugs -- the real bug is already confirmed live (see the
384/212 numbers above and this repo's `docs/MEETING_FINDER.md`); this
file's job is to guard the fix, not re-discover it.
"""

from __future__ import annotations

import pytest

from app.platforms.meeting_finder import runner, start
from app.platforms.meeting_finder.fetch import Fetcher, FetchResult
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
    """Same belt-and-braces guard as the WO-1122/WO-1086 test files:
    every phase function is monkeypatched per test, so a real
    `Fetcher.fetch()` call should never actually fire."""

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


def _error_status_page(url: str, status: int) -> FetchResult:
    """A real HTML body served with an error status `fetch.py` doesn't
    treat as a failure (only 403/dropped connections trigger its own
    block-like outcome) -- `outcome` is still `None` here, matching real
    `fetch.py` behavior."""
    return FetchResult(
        requested_url=url,
        final_url=url,
        status=status,
        html="<html><title>Password Required</title></html>",
        access_mode="plain",
        outcome=None,
        challenge=False,
        wayback_timestamp=None,
        links_only=False,
        elapsed_ms=1,
    )


def _identify_with_page(url: str, page: FetchResult) -> IdentifyResult:
    return IdentifyResult(
        input_url=url,
        final_url=url,
        platform=None,
        account_url=None,
        supported=None,
        web_host_hint=None,
        signals=[],
        youtube_leads=[],
        outcome=page.outcome,
        guess_queue_row=None,
        page=page,
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


# --- Rule 1: apex TLS-broken + www loads -> walk result wins --------------


@pytest.mark.asyncio
async def test_apex_site_broken_www_loads_walk_result_wins(monkeypatch):
    """The measured shape: the bare apex has a bad TLS certificate
    (`site-broken`), but `www.` loads fine and the walk finds nothing
    meeting-shaped. The real (if empty) walk result must win, not the
    apex's own refusal -- even though the apex IS the government's own
    host per `_own_host_set()`."""
    fi = FinderInput(url="https://brokencert.example.gov/", entry="start")
    points = [
        "https://brokencert.example.gov/",
        "https://www.brokencert.example.gov/",
    ]

    def identify_by_url(url):
        if url == points[0]:
            return _identify_with_outcome(url, OUTCOME_SITE_BROKEN)
        return _identify_with_outcome(url, None)

    _fake_run(monkeypatch, points, identify_by_url)

    row = await runner.run_one(fi, run_id="wo1134-1", max_forks=3, max_hops=0)

    assert row.outcome == OUTCOME_NO_MEETING_NOR_VIDEO
    assert row.blocked_url == ""
    assert "brokencert.example.gov" in (row.note or "")
    assert "secondary" in (row.note or "")


# --- Rule 2: both forms broken -> site-broken still wins ------------------


@pytest.mark.asyncio
async def test_both_own_host_forms_broken_site_broken_still_wins(monkeypatch):
    """Neither the apex nor `www.` ever loads -- there is no real walk
    result to prefer, so `site-broken` (a genuinely useful finding: the
    domain resolves, the site itself is broken) must still be the
    verdict, exactly as WO-1122 already established for the single-point
    case."""
    fi = FinderInput(url="https://allbroken.example.gov/", entry="start")
    points = [
        "https://allbroken.example.gov/",
        "https://www.allbroken.example.gov/",
    ]

    def identify_by_url(url):
        return _identify_with_outcome(url, OUTCOME_SITE_BROKEN)

    _fake_run(monkeypatch, points, identify_by_url)

    row = await runner.run_one(fi, run_id="wo1134-2", max_forks=3, max_hops=0)

    assert row.outcome == OUTCOME_SITE_BROKEN
    assert row.blocked_url in points


# --- Rule 3: own-host block only on a deep page while homepage loaded -----


@pytest.mark.asyncio
async def test_own_host_deep_page_block_demoted_when_homepage_loaded(monkeypatch):
    """A block on a DEEPER own-host page (found via a hop, still the same
    registrable host as the input) is demoted the same way a second
    starting-point form is, once the homepage itself is confirmed
    readable -- `own_host_page_fetched` cares about ANY successful
    own-host fetch, not just Start's own starting points."""
    fi = FinderInput(url="https://example.gov/", entry="start")
    points = ["https://example.gov/"]

    async def fake_start(domain_or_url, fetcher, **kwargs):
        return StartResult(starting_points=points, outcome=None)

    async def fake_identify(url, fetcher, *, platform_hint=None, page=None):
        return _identify_with_outcome(url, None)  # homepage loads fine

    async def fake_deep_step(point, ident, fetcher, finder_input, state, **kwargs):
        # Simulate Hop reaching a deeper own-host page that gets blocked --
        # recorded the same way `_shallow_step`/`identify` calls do.
        deep_url = "https://example.gov/agendas/"
        runner._record_outcome(state, "blocked-headless", deep_url)

    monkeypatch.setattr(runner, "run_start", fake_start)
    monkeypatch.setattr(runner, "identify", fake_identify)
    monkeypatch.setattr(runner, "rank_hops", lambda page, **kwargs: [])
    monkeypatch.setattr(
        runner, "_resolve_candidates_with_meeting", lambda *a, **k: (_no_result(), None)
    )
    monkeypatch.setattr(runner, "_deep_step", fake_deep_step)

    row = await runner.run_one(fi, run_id="wo1134-3", max_forks=3, max_hops=1)

    assert row.outcome == OUTCOME_NO_MEETING_NOR_VIDEO
    assert row.blocked_url == ""
    assert "agendas" in (row.note or "")
    assert "secondary" in (row.note or "")


# --- Rule 4: an auth-walled/error-status page never counts as "reachable" -


@pytest.mark.asyncio
async def test_hosting_provider_password_wall_does_not_count_as_reachable(monkeypatch):
    """Real, measured false positive found while live-verifying this fix
    (BACKLOG_DONE.md's WO-1134 entry): carrollton-ga.gov's plain-http form
    serves a hosting provider's own "Flywheel - Password Required" staging
    page over HTTP 401 -- real HTML, but not the government's actual site.
    `fetch.py` only raises a block-like outcome off a 403/challenge, so a
    401 status still comes back as `outcome=None` with a real body. This
    must NOT count as `own_host_page_fetched` -- the apex's own TLS
    failure (`site-broken`) is the only real signal here and must still
    win."""
    fi = FinderInput(url="https://authwalled.example.gov/", entry="start")
    points = [
        "https://authwalled.example.gov/",
        "http://authwalled.example.gov/",
    ]

    def identify_by_url(url):
        if url == points[0]:
            return _identify_with_outcome(url, OUTCOME_SITE_BROKEN)
        return _identify_with_page(url, _error_status_page(url, 401))

    _fake_run(monkeypatch, points, identify_by_url)

    row = await runner.run_one(fi, run_id="wo1134-4", max_forks=3, max_hops=0)

    assert row.outcome == OUTCOME_SITE_BROKEN
    assert row.blocked_url == "https://authwalled.example.gov/"


# --- start.py: plain-http fallback on the `www.` form too -----------------


def _dns_info(*, apex_resolves: bool, www_resolves: bool) -> dict:
    """Same SYNTHETIC `dns_lookup()`-shaped dict as
    tests/test_wo1086_meeting_finder_dns_false_positive.py's own helper."""
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
async def test_www_gets_a_plain_http_fallback_too(monkeypatch):
    """WO-1134: a live probe of the 384 `site-broken`/blocked-* governments
    (2026-09-26, see BACKLOG_DONE.md's WO-1134 entry) found 15 (of 212
    whose domain works in some form) that only load over plain http on
    the `www.` host specifically -- a form `start()` never tried before
    this fix: only the apex got an http fallback. Both https forks are
    still tried first (fork order), so this is "after https failed for
    this form," never "instead of" -- see `test_both_resolving_keeps_
    all_three_homepage_variants` in test_wo1086_meeting_finder_dns_false_
    positive.py for the pre-existing apex-only ordering this extends."""

    async def fake_dns_resolves(domain):
        return _dns_info(apex_resolves=True, www_resolves=True)

    monkeypatch.setattr(start, "_dns_resolves", fake_dns_resolves)
    monkeypatch.setattr(start, "fetch_live_robots_v2", lambda domain: _empty_robots())
    monkeypatch.setattr(
        start, "fetch_live_sitemap_v2", lambda domain, robots: _empty_sitemap()
    )

    fetcher = Fetcher(max_fetches=12)
    result = await start.start("ordinary.example.org", fetcher, guess_subdomains=False)

    assert result.starting_points == [
        "https://ordinary.example.org/",
        "https://www.ordinary.example.org/",
        "http://ordinary.example.org/",
        "http://www.ordinary.example.org/",
    ]


@pytest.mark.asyncio
async def test_www_http_fallback_skipped_when_www_does_not_resolve(monkeypatch):
    """The subdomain-host asymmetry WO-1086 already guards (no `www.`
    sibling at all) must not get a doomed `http://www.<host>/` fork
    either -- same DNS gate as the https `www.` variant."""

    async def fake_dns_resolves(domain):
        return _dns_info(apex_resolves=True, www_resolves=False)

    monkeypatch.setattr(start, "_dns_resolves", fake_dns_resolves)
    monkeypatch.setattr(start, "fetch_live_robots_v2", lambda domain: _empty_robots())
    monkeypatch.setattr(
        start, "fetch_live_sitemap_v2", lambda domain, robots: _empty_sitemap()
    )

    fetcher = Fetcher(max_fetches=12)
    result = await start.start("streaming.example.org", fetcher, guess_subdomains=False)

    assert "http://www.streaming.example.org/" not in result.starting_points
