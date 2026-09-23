"""WO-1030: the phase loop wiring (`app/platforms/meeting_finder/runner.py`).

Unit-level, not live: every phase function (`identify`, `list_account`,
`scan_page`, `rank_hops`, `run_start`, `_resolve_candidates_with_meeting`)
is monkeypatched at the `runner` module's own names, so these tests
exercise the LOOP -- entry dispatch, `max_hops`/`max_forks` limits,
never-revisit, budget handling, and Verdict's outcome-priority choice --
without any real network I/O. The live, real-URL smoke test for WO-1030
is a separate manual run (see this WO's own report), per CLAUDE.md's
"test against a real URL first" rule applying to the ADAPTERS/phases
themselves (already covered by WO-1024/1027/1028/1029's own real-fixture
tests), not to this wiring layer, which has no platform-specific logic
of its own to get wrong against a real page.
"""

from __future__ import annotations

import uuid

import pytest

from app.platforms.meeting_finder import runner
from app.platforms.meeting_finder.fetch import BudgetExceeded, FetchResult
from app.platforms.meeting_finder.hop import HopLink
from app.platforms.meeting_finder.identify import IdentifyResult
from app.platforms.meeting_finder.listing import ListResult
from app.platforms.meeting_finder.models import (
    OUTCOME_ACCOUNT_NOT_FOUND,
    OUTCOME_MEETING_WITHOUT_VIDEO,
    OUTCOME_NO_MEETING_NOR_VIDEO,
    Candidate,
    FinderInput,
    ResolveResult,
)
from app.platforms.meeting_finder.scan import ScanResult
from app.platforms.meeting_finder.start import StartResult


def _page(url: str, *, html: str = "<html></html>") -> FetchResult:
    return FetchResult(
        requested_url=url,
        final_url=url,
        status=200,
        html=html,
        access_mode="plain",
        outcome=None,
        challenge=False,
        wayback_timestamp=None,
        links_only=False,
        elapsed_ms=1,
    )


def _identify_blank(url: str, outcome=None) -> IdentifyResult:
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


def _real_result(url: str) -> ResolveResult:
    return ResolveResult(
        candidate=Candidate(url=url, source_phase="list"),
        tier=1,
        platform="granicus",
        video_url=url,
        has_segments=True,
        duration_seconds=1800,
        outcome=None,
        note="",
    )


@pytest.fixture(autouse=True)
def _no_real_fetcher_io(monkeypatch):
    """Belt and braces: fail loudly if anything in these tests reaches a
    real `Fetcher.fetch()` -- every phase function is monkeypatched per
    test, so this should never actually fire."""

    async def _boom(self, url, **kwargs):  # noqa: ANN001
        raise AssertionError(f"unexpected real fetch: {url}")

    monkeypatch.setattr(runner.Fetcher, "fetch", _boom)


# --- Entry dispatch ------------------------------------------------------


@pytest.mark.asyncio
async def test_entry_resolve_unchanged(monkeypatch):
    """entry="resolve" skips Identify/List/Scan/Hop entirely -- the input
    URL goes straight to Resolve, per the design doc's own "One meeting
    URL" row."""
    called_with = {}

    async def fake_resolve(candidates, finder_input, *, max_tries):
        called_with["candidates"] = candidates
        return _real_result(finder_input.url), None

    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)

    fi = FinderInput(url="https://example.gov/event/18/media", entry="resolve")
    row = await runner.run_one(fi, run_id="r1")

    assert row.phase_reached == "resolve"
    assert row.tier == 1
    assert len(called_with["candidates"]) == 1
    assert called_with["candidates"][0].url == fi.url


@pytest.mark.asyncio
async def test_entry_identify_walks_to_list_then_resolve(monkeypatch):
    fi = FinderInput(url="https://example.gov/watch", entry="identify")

    async def fake_identify(url, fetcher, *, platform_hint=None, page=None):
        return IdentifyResult(
            input_url=url,
            final_url=url,
            platform="granicus",
            account_url="https://city.granicus.com/ViewPublisher.php?view_id=1",
            supported=True,
            web_host_hint=None,
            signals=[],
            youtube_leads=[],
            outcome=None,
            guess_queue_row=None,
            page=_page(url),
        )

    async def fake_list_account(platform, account_url, fetcher, **kwargs):
        assert platform == "granicus"
        return ListResult(
            candidates=[
                Candidate(url="https://city.granicus.com/clip/1", source_phase="list")
            ],
            lister="passive_verify:granicus",
            outcome=None,
        )

    async def fake_resolve(candidates, finder_input, *, max_tries):
        return _real_result(candidates[0].url), None

    monkeypatch.setattr(runner, "identify", fake_identify)
    monkeypatch.setattr(runner, "list_account", fake_list_account)
    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)

    row = await runner.run_one(fi, run_id="r2")

    assert row.phase_reached == "resolve"
    assert row.tier == 1
    assert row.outcome is None
    assert fi.url in row.path


@pytest.mark.asyncio
async def test_entry_list_requires_platform_hint(monkeypatch):
    fi = FinderInput(
        url="https://city.granicus.com/ViewPublisher.php?view_id=1", entry="list"
    )
    row = await runner.run_one(fi, run_id="r3")
    assert row.outcome == "unsupported-platform-no-adapter"


@pytest.mark.asyncio
async def test_entry_list_success(monkeypatch):
    fi = FinderInput(
        url="https://city.granicus.com/ViewPublisher.php?view_id=1",
        entry="list",
        platform_hint="granicus",
    )

    async def fake_list_account(platform, account_url, fetcher, **kwargs):
        return ListResult(
            candidates=[
                Candidate(url="https://city.granicus.com/clip/9", source_phase="list")
            ],
            lister="passive_verify:granicus",
            outcome=None,
        )

    async def fake_resolve(candidates, finder_input, *, max_tries):
        return _real_result(candidates[0].url), None

    monkeypatch.setattr(runner, "list_account", fake_list_account)
    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)

    row = await runner.run_one(fi, run_id="r4")
    assert row.tier == 1
    assert row.phase_reached == "resolve"


@pytest.mark.asyncio
async def test_entry_scan_success(monkeypatch):
    fi = FinderInput(url="https://example.gov/meetings/2026-09-08", entry="scan")

    async def fake_fetch(self, url, **kwargs):
        return _page(url)

    async def fake_scan_page(page, fetcher, **kwargs):
        return ScanResult(
            media_candidates=[
                Candidate(url="https://example.gov/video.mp4", source_phase="scan")
            ],
            meeting_page_links=[],
            youtube_leads=[],
            opened_pages=0,
        )

    async def fake_resolve(candidates, finder_input, *, max_tries):
        return _real_result(candidates[0].url), None

    monkeypatch.setattr(runner.Fetcher, "fetch", fake_fetch)
    monkeypatch.setattr(runner, "scan_page", fake_scan_page)
    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)

    row = await runner.run_one(fi, run_id="r5")
    assert row.phase_reached == "resolve"
    assert row.tier == 1


@pytest.mark.asyncio
async def test_entry_start_dns_dead_reports_outcome(monkeypatch):
    fi = FinderInput(url="nonexistent-domain-xyz.example", entry="start")

    async def fake_start(domain_or_url, fetcher, **kwargs):
        return StartResult(starting_points=[], outcome="dns-unresolvable", note="dead")

    monkeypatch.setattr(runner, "run_start", fake_start)

    row = await runner.run_one(fi, run_id="r6")
    assert row.outcome == "dns-unresolvable"
    assert row.phase_reached == "start"


# --- Limits: max_hops, max_forks, never-revisit --------------------------


@pytest.mark.asyncio
async def test_max_hops_enforced(monkeypatch):
    """A chase of hop links (a1 -> a2 -> a3 -> ...) longer than
    `max_hops` stops at the cap -- identify() is called once for the
    start page plus at most `max_hops` hop pages (a homepage's own first
    fork gets +1, per the design doc)."""
    fi = FinderInput(url="https://example.gov/", entry="identify")
    identify_calls = []

    async def fake_identify(url, fetcher, *, platform_hint=None, page=None):
        identify_calls.append(url)
        return _identify_blank(url)

    def fake_rank_hops(page, **kwargs):
        n = len(identify_calls)
        return [
            HopLink(url=f"https://example.gov/hop{n}", score=10.0, anchor="", reason="")
        ]

    async def fake_resolve(candidates, finder_input, *, max_tries):
        return _no_result(), None

    monkeypatch.setattr(runner, "identify", fake_identify)
    monkeypatch.setattr(runner, "rank_hops", fake_rank_hops)
    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)

    row = await runner.run_one(fi, run_id="r7", max_hops=2)

    # entry=identify -> hops budget is exactly max_hops (no homepage
    # bonus -- that only applies to entry=start's own first fork).
    assert len(identify_calls) == 1 + 2
    assert row.hops == 2


@pytest.mark.asyncio
async def test_start_homepage_gets_one_extra_hop(monkeypatch):
    fi = FinderInput(url="https://example.gov/", entry="start")
    identify_calls = []

    async def fake_start(domain_or_url, fetcher, **kwargs):
        return StartResult(starting_points=["https://example.gov/"], outcome=None)

    async def fake_identify(url, fetcher, *, platform_hint=None, page=None):
        identify_calls.append(url)
        return _identify_blank(url)

    def fake_rank_hops(page, **kwargs):
        n = len(identify_calls)
        return [
            HopLink(url=f"https://example.gov/hop{n}", score=10.0, anchor="", reason="")
        ]

    async def fake_resolve(candidates, finder_input, *, max_tries):
        return _no_result(), None

    monkeypatch.setattr(runner, "run_start", fake_start)
    monkeypatch.setattr(runner, "identify", fake_identify)
    monkeypatch.setattr(runner, "rank_hops", fake_rank_hops)
    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)

    row = await runner.run_one(fi, run_id="r8", max_hops=2)

    # Homepage fork: max_hops + 1 = 3 hops beyond the start page itself.
    assert len(identify_calls) == 1 + 3
    assert row.hops == 3


@pytest.mark.asyncio
async def test_max_forks_enforced(monkeypatch):
    fi = FinderInput(url="https://example.gov/", entry="start")
    starting_points = [f"https://example.gov/p{i}" for i in range(6)]

    async def fake_start(domain_or_url, fetcher, **kwargs):
        return StartResult(starting_points=starting_points, outcome=None)

    identify_calls = []

    async def fake_identify(url, fetcher, *, platform_hint=None, page=None):
        identify_calls.append(url)
        return _identify_blank(url)

    async def fake_resolve(candidates, finder_input, *, max_tries):
        return _no_result(), None

    monkeypatch.setattr(runner, "run_start", fake_start)
    monkeypatch.setattr(runner, "identify", fake_identify)
    monkeypatch.setattr(runner, "rank_hops", lambda page, **kwargs: [])
    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)

    row = await runner.run_one(fi, run_id="r9", max_forks=3, max_hops=0)

    # The first starting point, plus at most max_forks=3 more.
    assert len(identify_calls) == 1 + 3
    assert row.forks == 3


@pytest.mark.asyncio
async def test_never_revisit_a_url(monkeypatch):
    """A hop link that loops back to a URL already on the path is not
    fetched a second time."""
    fi = FinderInput(url="https://example.gov/a", entry="identify")
    identify_calls = []

    async def fake_identify(url, fetcher, *, platform_hint=None, page=None):
        identify_calls.append(url)
        return _identify_blank(url)

    def fake_rank_hops(page, **kwargs):
        # Always points back to the start URL -- a real loop.
        return [HopLink(url="https://example.gov/a", score=10.0, anchor="", reason="")]

    async def fake_resolve(candidates, finder_input, *, max_tries):
        return _no_result(), None

    monkeypatch.setattr(runner, "identify", fake_identify)
    monkeypatch.setattr(runner, "rank_hops", fake_rank_hops)
    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)

    await runner.run_one(fi, run_id="r10", max_hops=3)

    assert identify_calls == ["https://example.gov/a"]


# --- Budget exhaustion -----------------------------------------------


@pytest.mark.asyncio
async def test_budget_exceeded_ends_walk_cleanly(monkeypatch):
    fi = FinderInput(url="https://example.gov/", entry="identify")

    async def fake_identify(url, fetcher, *, platform_hint=None, page=None):
        raise BudgetExceeded("max_fetches reached")

    monkeypatch.setattr(runner, "identify", fake_identify)

    row = await runner.run_one(fi, run_id="r11", max_fetches=1)

    assert row.outcome == OUTCOME_NO_MEETING_NOR_VIDEO
    assert "budget exhausted" in row.note


# --- Outcome priority --------------------------------------------------


def test_pick_outcome_prioritizes_meeting_without_video():
    outcomes = [
        OUTCOME_NO_MEETING_NOR_VIDEO,
        OUTCOME_ACCOUNT_NOT_FOUND,
        OUTCOME_MEETING_WITHOUT_VIDEO,
    ]
    assert runner._pick_outcome(outcomes) == OUTCOME_MEETING_WITHOUT_VIDEO


def test_pick_outcome_account_not_found_beats_generic_no_meeting():
    outcomes = [OUTCOME_NO_MEETING_NOR_VIDEO, OUTCOME_ACCOUNT_NOT_FOUND]
    assert runner._pick_outcome(outcomes) == OUTCOME_ACCOUNT_NOT_FOUND


def test_pick_outcome_access_block_beats_nothing():
    outcomes = [OUTCOME_NO_MEETING_NOR_VIDEO, "cloudflare-challenge-blocked"]
    assert runner._pick_outcome(outcomes) == "cloudflare-challenge-blocked"


def test_pick_outcome_empty_defaults_to_no_meeting_nor_video():
    assert runner._pick_outcome([]) == OUTCOME_NO_MEETING_NOR_VIDEO


@pytest.mark.asyncio
async def test_meeting_without_video_outcome_surfaces_from_list(monkeypatch):
    """Gap (b) from this WO's brief: an agenda-only candidate
    (`has_video_hint=False`, e.g. CivicPlus's own agenda-only fallback)
    flows through to Resolve, and a real meeting-without-video finding
    outranks a later, less informative outcome collected along the same
    walk."""
    fi = FinderInput(url="https://example.gov/watch", entry="identify")

    async def fake_identify(url, fetcher, *, platform_hint=None, page=None):
        return IdentifyResult(
            input_url=url,
            final_url=url,
            platform="civicplus",
            account_url="https://example.civicplus.com/AgendaCenter",
            supported=True,
            web_host_hint=None,
            signals=[],
            youtube_leads=[],
            outcome=None,
            guess_queue_row=None,
            page=_page(url),
        )

    async def fake_list_account(platform, account_url, fetcher, **kwargs):
        return ListResult(
            candidates=[
                Candidate(
                    url="https://example.civicplus.com/AgendaCenter/ViewFile/Agenda/1",
                    source_phase="list",
                    has_video_hint=False,
                )
            ],
            lister="civicplus_agenda_only",
            outcome=None,
        )

    async def fake_resolve(candidates, finder_input, *, max_tries):
        return (
            ResolveResult(
                candidate=candidates[0],
                tier=None,
                platform="civicplus",
                video_url=None,
                has_segments=False,
                duration_seconds=None,
                outcome=OUTCOME_MEETING_WITHOUT_VIDEO,
                note="agenda only, no video link",
            ),
            None,
        )

    monkeypatch.setattr(runner, "identify", fake_identify)
    monkeypatch.setattr(runner, "list_account", fake_list_account)
    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)

    row = await runner.run_one(fi, run_id="r12")
    assert row.outcome == OUTCOME_MEETING_WITHOUT_VIDEO


@pytest.mark.asyncio
async def test_run_inputs_resumes_and_dedupes(tmp_path, monkeypatch):
    out = tmp_path / "verdicts.csv"

    async def fake_resolve(candidates, finder_input, *, max_tries):
        return _real_result(candidates[0].url), None

    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)

    inputs = [FinderInput(url="https://a.gov/event/1", entry="resolve")]
    rows = await runner.run_inputs(inputs, out, run_id=uuid.uuid4().hex[:8])
    assert len(rows) == 1

    # A rerun with the same URL already in `out` produces nothing new.
    rows2 = await runner.run_inputs(inputs, out, run_id=uuid.uuid4().hex[:8])
    assert rows2 == []
