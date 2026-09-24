"""WO-1035: runner.py's own share of "never lose a meeting, never repeat
work" -- Hop backtracking/vendor-tie preference (item 7), and the
per-government List/Resolve dedupe caches (item 5).

Unit-level, not live, same convention as tests/test_wo1030_meeting_finder_
runner.py: every phase function is monkeypatched at the `runner` module's
own names, so these exercise the LOOP, not any adapter's real parsing.
"""

from __future__ import annotations

import pytest

from app.platforms.meeting_finder import runner
from app.platforms.meeting_finder.fetch import FetchResult
from app.platforms.meeting_finder.hop import HopLink
from app.platforms.meeting_finder.identify import IdentifyResult
from app.platforms.meeting_finder.listing import ListResult
from app.platforms.meeting_finder.models import Candidate, FinderInput, ResolveResult


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


def _identify_blank(url: str, *, platform=None, account_url=None) -> IdentifyResult:
    return IdentifyResult(
        input_url=url,
        final_url=url,
        platform=platform,
        account_url=account_url,
        supported=None,
        web_host_hint=None,
        signals=[],
        youtube_leads=[],
        outcome=None,
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
        outcome="no-meeting-nor-video",
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


@pytest.mark.asyncio
async def test_backtracks_to_sibling_hop_when_top_ranked_one_dead_ends(monkeypatch):
    """cablecast3/swagit1/swagit2 reports (2026-09-23): Des Plaines IL,
    Niagara Falls SD NY, James Island SC and Johnson County TX all had the
    real vendor link ranked BELOW an agenda/minutes page that led nowhere.
    The old runner tried only the single best-ranked hop per page and gave
    up; WO-1035 tries the next sibling when the top one dead-ends."""
    fi = FinderInput(url="https://example.gov/", entry="identify")

    identified = []

    async def fake_identify(url, fetcher, *, platform_hint=None, page=None):
        identified.append(url)
        if url == "https://example.gov/agendas":
            return _identify_blank(url)  # dead end: no platform found
        if url == "https://example.gov/watch":
            return _identify_blank(
                url, platform="granicus", account_url="https://x.granicus.com/view"
            )
        return _identify_blank(url)

    def fake_rank_hops(page, **kwargs):
        if page.requested_url != "https://example.gov/":
            return []
        return [
            HopLink(
                url="https://example.gov/agendas",
                score=20.0,
                anchor="Agendas & Minutes",
                reason="",
            ),
            HopLink(
                url="https://example.gov/watch",
                score=12.0,
                anchor="Watch Meetings",
                reason="",
            ),
        ]

    async def fake_list_account(platform, account_url, fetcher, **kwargs):
        return ListResult(
            candidates=[Candidate(url="https://x.granicus.com/clip/1")],
            lister="passive_verify:granicus",
            outcome=None,
        )

    async def fake_resolve(candidates, finder_input, *, max_tries):
        if candidates and candidates[0].url == "https://x.granicus.com/clip/1":
            return _real_result(candidates[0].url), None
        return _no_result(), None

    monkeypatch.setattr(runner, "identify", fake_identify)
    monkeypatch.setattr(runner, "rank_hops", fake_rank_hops)
    monkeypatch.setattr(runner, "list_account", fake_list_account)
    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)

    row = await runner.run_one(fi, run_id="wo1035-backtrack", max_hops=2)

    assert row.outcome is None
    assert row.result_url == "https://x.granicus.com/clip/1"
    assert "https://example.gov/agendas" in identified
    assert "https://example.gov/watch" in identified


@pytest.mark.asyncio
async def test_near_tied_vendor_link_is_followed_before_a_higher_scored_page(
    monkeypatch,
):
    """WO-1035 item 7: a recognized video-vendor link within a small
    score margin of the top-ranked hop is followed FIRST, since
    `rank_hops()`'s own scoring has no idea which links are actually video
    platforms."""
    fi = FinderInput(url="https://example.gov/", entry="identify")

    identified = []

    async def fake_identify(url, fetcher, *, platform_hint=None, page=None):
        identified.append(url)
        return _identify_blank(url)

    def fake_rank_hops(page, **kwargs):
        if page.requested_url != "https://example.gov/":
            return []
        return [
            HopLink(
                url="https://example.gov/agendas",
                score=20.0,
                anchor="Agendas & Minutes",
                reason="",
            ),
            HopLink(
                url="https://cityx.cablecast.tv/show/1",
                score=17.0,  # within _VENDOR_TIE_MARGIN (5.0) of 20.0
                anchor="Watch",
                reason="",
            ),
        ]

    async def fake_resolve(candidates, finder_input, *, max_tries):
        return _no_result(), None

    monkeypatch.setattr(runner, "identify", fake_identify)
    monkeypatch.setattr(runner, "rank_hops", fake_rank_hops)
    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)

    await runner.run_one(fi, run_id="wo1035-vendor-tie", max_hops=1)

    # The vendor link (cablecast, a recognized platform) is tried before
    # the higher-scoring agenda page, even though it isn't the top score.
    assert identified[1] == "https://cityx.cablecast.tv/show/1"


@pytest.mark.asyncio
async def test_same_account_is_listed_only_once_per_government(monkeypatch):
    """WO-1035 item 5 (Des Plaines IL, cablecast3 report): two different
    forks/hops landing on the SAME real account must not call
    `list_account()` twice."""
    fi = FinderInput(url="https://example.gov/", entry="identify")

    list_calls = []

    async def fake_identify(url, fetcher, *, platform_hint=None, page=None):
        return _identify_blank(
            url, platform="champds", account_url="https://x.champds.com/browse"
        )

    async def fake_list_account(platform, account_url, fetcher, **kwargs):
        list_calls.append(account_url)
        return ListResult(candidates=[], lister="passive_verify:champds", outcome=None)

    def fake_rank_hops(page, **kwargs):
        if page.requested_url != "https://example.gov/":
            return []
        return [
            HopLink(
                url="https://example.gov/other-page",
                score=10.0,
                anchor="Other",
                reason="",
            )
        ]

    async def fake_resolve(candidates, finder_input, *, max_tries):
        return _no_result(), None

    monkeypatch.setattr(runner, "identify", fake_identify)
    monkeypatch.setattr(runner, "list_account", fake_list_account)
    monkeypatch.setattr(runner, "rank_hops", fake_rank_hops)
    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)

    await runner.run_one(fi, run_id="wo1035-list-once", max_hops=1)

    # Both the start page and the hop page resolve to the SAME champds
    # account -- list_account() must only really run once.
    assert list_calls == ["https://x.champds.com/browse"]


@pytest.mark.asyncio
async def test_same_meeting_is_resolved_only_once_per_government(monkeypatch):
    """WO-1035 item 5 (Upper Providence PA, swagit2 report): the same
    meeting, found twice (once via List, once via a hop's own List call),
    is only ever handed to Resolve once."""
    fi = FinderInput(url="https://example.gov/", entry="identify")

    resolve_calls = []

    async def fake_identify(url, fetcher, *, platform_hint=None, page=None):
        return _identify_blank(
            url, platform="civicclerk", account_url="https://x.civicclerk.com/events"
        )

    async def fake_list_account(platform, account_url, fetcher, **kwargs):
        # Same real event, reached again on a second call -- caching (item
        # 5's OTHER rule, "accounts listed once") already prevents this in
        # practice, but this test's own point is the Resolve-side dedupe,
        # so it monkeypatches list_account directly per call.
        return ListResult(
            candidates=[Candidate(url="https://x.civicclerk.com/event/123/media")],
            lister="passive_verify:civicclerk",
            outcome=None,
        )

    def fake_rank_hops(page, **kwargs):
        return []

    async def fake_resolve(candidates, finder_input, *, max_tries):
        resolve_calls.append([c.url for c in candidates])
        return _no_result(), None

    monkeypatch.setattr(runner, "identify", fake_identify)
    monkeypatch.setattr(runner, "list_account", fake_list_account)
    monkeypatch.setattr(runner, "rank_hops", fake_rank_hops)
    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)

    # Two starting points both land on the same CivicClerk account/event.
    from app.platforms.meeting_finder.start import StartResult

    async def fake_start(domain_or_url, fetcher, **kwargs):
        return StartResult(
            starting_points=["https://example.gov/", "https://example.gov/alt"],
            outcome=None,
        )

    monkeypatch.setattr(runner, "run_start", fake_start)
    fi = FinderInput(url="https://example.gov/", entry="start")

    await runner.run_one(fi, run_id="wo1035-resolve-once", max_forks=3)

    # Resolve is only ever actually called with the (deduped) event once --
    # the second fork's identical candidate is filtered out before
    # `_resolve_candidates_with_meeting()` is reached at all.
    assert resolve_calls == [["https://x.civicclerk.com/event/123/media"]]
