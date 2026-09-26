"""WO-1074: Meeting Finder second pass -- three rescues on top of the
WO-1024/1030 phase loop, calibration set D (2026-09-25):

1. A "second pass" before settling for `OUTCOME_YOUTUBE_LEAD_ONLY`: when a
   walk would otherwise end with only YouTube leads (no platform account,
   no meeting video anywhere), spend extra budget on a focused pass across
   every fork's own already-fetched page, following only high-value
   site-nav links (Meetings / Agendas & Minutes / Government / Council /
   Board / Watch / Video / Media / TV).
2. "One more hop" from a meetings/agenda page (or a meeting-without-video
   listing) for a link whose text/URL carries a broadcast/context word
   (video/watch/broadcast/stream/replay/TV/channel) -- the real Lake
   Oswego, OR path this targets (`citycouncil` -> `city-council-meetings`
   -> the TVCTV sentence -> `tvctv.org`).
3. "Adaptive budget": once real promising evidence appears (a meetings
   page, a recognized platform account, a meeting-without-video listing),
   raise this government's own fetch cap instead of stopping at the
   ordinary default.

Unit-level, not live -- same convention as tests/test_wo1035_meeting_
finder_keep_and_backtrack.py and test_wo1030_meeting_finder_runner.py:
every phase function is monkeypatched at the `runner` module's own names,
so these exercise the LOOP, not any adapter's real parsing. Ryan approved
building all three items together (2026-09-25, `<scratchpad>/builds/
WO1070.md`); a live before/after check against the real calibration-set-D
governments is in the PR description, per that WO's own report
instructions.
"""

from __future__ import annotations

import pytest

from app.platforms.meeting_finder import runner
from app.platforms.meeting_finder.fetch import Fetcher, FetchResult
from app.platforms.meeting_finder.hop import HopLink
from app.platforms.meeting_finder.identify import IdentifyResult
from app.platforms.meeting_finder.listing import ListResult
from app.platforms.meeting_finder.models import (
    OUTCOME_MEETING_WITHOUT_VIDEO,
    Candidate,
    FinderInput,
    ResolveResult,
)


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


def _identify_blank(url: str, *, platform=None, account_url=None, youtube_leads=None):
    return IdentifyResult(
        input_url=url,
        final_url=url,
        platform=platform,
        account_url=account_url,
        supported=None,
        web_host_hint=None,
        signals=[],
        youtube_leads=list(youtube_leads or []),
        outcome=None,
        guess_queue_row=None,
        page=_page(url),
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


# --- Item 3: `_maybe_raise_budget()`, direct unit tests -----------------


def test_maybe_raise_budget_raises_once_and_logs_a_note():
    fetcher = Fetcher(max_fetches=12)
    state = runner._WalkState(adaptive_max_fetches=24)

    runner._maybe_raise_budget(fetcher, state, reason="recognized platform account")

    assert fetcher.max_fetches == 24
    assert state.adaptive_budget_used is True
    assert len(state.budget_notes) == 1
    assert "raised to 24 fetches" in state.budget_notes[0]
    assert "recognized platform account" in state.budget_notes[0]

    # Idempotent: a second call (different reason) doesn't raise it again
    # or add a second note.
    runner._maybe_raise_budget(fetcher, state, reason="meetings page")
    assert fetcher.max_fetches == 24
    assert len(state.budget_notes) == 1


def test_maybe_raise_budget_respects_the_disabled_flag():
    fetcher = Fetcher(max_fetches=12)
    state = runner._WalkState(adaptive_budget_enabled=False, adaptive_max_fetches=24)

    runner._maybe_raise_budget(fetcher, state, reason="meetings page")

    assert fetcher.max_fetches == 12
    assert state.budget_notes == []


def test_maybe_raise_budget_never_lowers_an_already_bigger_budget():
    fetcher = Fetcher(max_fetches=30)
    state = runner._WalkState(adaptive_max_fetches=24)

    runner._maybe_raise_budget(fetcher, state, reason="meetings page")

    assert fetcher.max_fetches == 30
    assert state.budget_notes == []


# --- Item 1: `_would_end_youtube_lead_only()`, direct unit tests --------


def test_would_end_youtube_lead_only_true_with_no_other_evidence():
    state = runner._WalkState()
    state.leads.append({"kind": "youtube", "url": "https://youtube.com/x"})
    assert runner._would_end_youtube_lead_only(state) is True


def test_would_end_youtube_lead_only_false_with_no_youtube_lead():
    state = runner._WalkState()
    assert runner._would_end_youtube_lead_only(state) is False


def test_would_end_youtube_lead_only_false_when_meeting_without_video_found():
    """A meeting-without-video listing is real, non-YouTube evidence --
    item 2's own "one more hop" is the rescue for that case, not item 1's
    second pass."""
    state = runner._WalkState()
    state.leads.append({"kind": "youtube", "url": "https://youtube.com/x"})
    state.outcomes.append(OUTCOME_MEETING_WITHOUT_VIDEO)
    assert runner._would_end_youtube_lead_only(state) is False


def test_would_end_youtube_lead_only_false_once_a_clean_result_exists():
    state = runner._WalkState()
    state.leads.append({"kind": "youtube", "url": "https://youtube.com/x"})
    state.result = object()
    assert runner._would_end_youtube_lead_only(state) is False


# --- Item 1: full-walk integration ---------------------------------------


@pytest.mark.asyncio
async def test_second_pass_rescues_a_youtube_lead_only_walk(monkeypatch):
    """Calibration set D (2026-09-25): 380 governments ended
    `youtube-lead-only`, ~190 with a known non-YouTube video platform on
    file. The homepage carries only a YouTube channel link plus an
    ordinary "Meetings" nav link that the normal (budget-exhausted, 0
    hops left) walk never gets to try -- the second pass raises the
    budget and follows exactly that nav link, reaching a real Granicus
    account one hop further."""
    fi = FinderInput(url="https://example.gov/", entry="identify")
    identified = []

    async def fake_identify(url, fetcher, *, platform_hint=None):
        identified.append(url)
        if url == "https://example.gov/meetings":
            return _identify_blank(
                url, platform="granicus", account_url="https://x.granicus.com/view"
            )
        return _identify_blank(url, youtube_leads=["https://youtube.com/c/ExampleGov"])

    def fake_rank_hops(page, **kwargs):
        return [
            HopLink(
                url="https://example.gov/meetings",
                score=10.0,
                anchor="Meetings",
                reason="",
            )
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

    row = await runner.run_one(fi, run_id="wo1070-second-pass", max_hops=0, max_forks=0)

    assert row.outcome is None
    assert row.result_url == "https://x.granicus.com/clip/1"
    assert "https://example.gov/meetings" in identified
    # The YouTube lead found along the way is kept regardless of the
    # eventual clean find.
    assert any(lead.get("kind") == "youtube" for lead in row.leads)
    assert "second pass" in row.note


@pytest.mark.asyncio
async def test_no_second_pass_when_real_evidence_already_found(monkeypatch):
    """The second pass is specifically for "YouTube is literally all
    there is" -- a meeting-without-video outcome is real, non-YouTube
    evidence, so the walk reports that instead, and the nav-link-only
    page (which would otherwise be reachable by the rescue) is never
    visited."""
    fi = FinderInput(url="https://example.gov/", entry="identify")
    identified = []

    async def fake_identify(url, fetcher, *, platform_hint=None):
        identified.append(url)
        if url == "https://example.gov/":
            return _identify_blank(
                url,
                platform="civicclerk",
                account_url="https://example.civicclerk.com",
                youtube_leads=["https://youtube.com/c/ExampleGov"],
            )
        return _identify_blank(url)

    async def fake_list_account(platform, account_url, fetcher, **kwargs):
        return ListResult(
            candidates=[Candidate(url="https://example.civicclerk.com/event/1")],
            lister="discovery:civicclerk",
            outcome=None,
        )

    async def fake_resolve(candidates, finder_input, *, max_tries):
        return (
            ResolveResult(
                candidate=None,
                tier=None,
                platform=None,
                video_url=None,
                has_segments=False,
                duration_seconds=None,
                outcome=OUTCOME_MEETING_WITHOUT_VIDEO,
                note="agenda-only",
            ),
            None,
        )

    monkeypatch.setattr(runner, "identify", fake_identify)
    monkeypatch.setattr(runner, "list_account", fake_list_account)
    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)
    # No hops off the homepage at all (empty every time) -- the real
    # assertion is that `_would_end_youtube_lead_only()` is false here, so
    # `_second_pass_for_youtube_only()` (and its own "second pass" note)
    # never runs, regardless of what hops would otherwise be available.
    monkeypatch.setattr(runner, "rank_hops", lambda page, **kwargs: [])

    row = await runner.run_one(
        fi, run_id="wo1070-no-second-pass", max_hops=0, max_forks=0
    )

    assert row.outcome == OUTCOME_MEETING_WITHOUT_VIDEO
    assert "second pass" not in row.note


# --- Item 2: full-walk integration (Lake Oswego, OR shape) --------------


@pytest.mark.asyncio
async def test_one_more_hop_from_a_meetings_page_reaches_a_context_word_link(
    monkeypatch,
):
    """Real Lake Oswego, OR path: `citycouncil` -> `city-council-meetings`
    (a real meetings/agenda page, `is_document_hub()` true) -> the TVCTV
    sentence ("Tualatin Valley Community Television (TVCTV) streams the
    meetings and airs replays. Check their website.") -> `tvctv.org`, one
    hop past the ordinary `max_hops=0` budget used here. The link's own
    anchor carries a context word ("replay")."""
    fi = FinderInput(url="https://example.gov/", entry="identify")
    identified = []

    async def fake_identify(url, fetcher, *, platform_hint=None):
        identified.append(url)
        if url == "https://tvctv.org":
            return _identify_blank(
                url, platform="cablecast", account_url="https://tvctv.org/lake-oswego"
            )
        return _identify_blank(url)

    def fake_is_document_hub(page):
        return page.requested_url == "https://example.gov/"

    def fake_rank_hops(page, **kwargs):
        if page.requested_url != "https://example.gov/":
            return []
        return [
            HopLink(
                url="https://tvctv.org",
                score=5.0,
                anchor="Check their website for replays",
                reason="",
            )
        ]

    async def fake_list_account(platform, account_url, fetcher, **kwargs):
        return ListResult(
            candidates=[Candidate(url="https://tvctv.org/show/1")],
            lister="cablecast_gallery",
            outcome=None,
        )

    async def fake_resolve(candidates, finder_input, *, max_tries):
        if candidates and candidates[0].url == "https://tvctv.org/show/1":
            return _real_result(candidates[0].url), None
        return _no_result(), None

    monkeypatch.setattr(runner, "identify", fake_identify)
    monkeypatch.setattr(runner, "is_document_hub", fake_is_document_hub)
    monkeypatch.setattr(runner, "rank_hops", fake_rank_hops)
    monkeypatch.setattr(runner, "list_account", fake_list_account)
    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)

    row = await runner.run_one(
        fi, run_id="wo1070-one-more-hop", max_hops=0, max_forks=0
    )

    assert row.outcome is None
    assert row.result_url == "https://tvctv.org/show/1"
    assert "https://tvctv.org" in identified


@pytest.mark.asyncio
async def test_one_more_hop_does_not_fire_off_a_non_meetings_page(monkeypatch):
    """Guard rail: the bonus hop only applies to a real meetings/agenda
    hub (or a meeting-without-video outcome) -- an ordinary page with no
    such evidence gets no extra hop, however good the link looks."""
    fi = FinderInput(url="https://example.gov/", entry="identify")

    async def fake_identify(url, fetcher, *, platform_hint=None):
        return _identify_blank(url)

    def fake_is_document_hub(page):
        return False

    def fake_rank_hops(page, **kwargs):
        pytest.fail("no bonus hop should be attempted off a non-meetings page")

    monkeypatch.setattr(runner, "identify", fake_identify)
    monkeypatch.setattr(runner, "is_document_hub", fake_is_document_hub)
    monkeypatch.setattr(runner, "rank_hops", fake_rank_hops)

    row = await runner.run_one(
        fi, run_id="wo1070-no-bonus-hop", max_hops=0, max_forks=0
    )

    # No crash, and no false "second pass"/bonus-hop note either -- the
    # real assertion is `fake_rank_hops` never being called (see above).
    assert "second pass" not in row.note


# --- Item 3: full-walk integration ---------------------------------------


@pytest.mark.asyncio
async def test_adaptive_budget_raises_the_fetcher_cap_on_a_recognized_account(
    monkeypatch,
):
    fi = FinderInput(url="https://example.gov/", entry="identify")

    async def fake_identify(url, fetcher, *, platform_hint=None):
        return _identify_blank(
            url, platform="granicus", account_url="https://x.granicus.com/view"
        )

    async def fake_list_account(platform, account_url, fetcher, **kwargs):
        return ListResult(candidates=[], lister="passive_verify:granicus", outcome=None)

    async def fake_resolve(candidates, finder_input, *, max_tries):
        return _no_result(), None

    monkeypatch.setattr(runner, "identify", fake_identify)
    monkeypatch.setattr(runner, "list_account", fake_list_account)
    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)

    progress: dict = {}
    row = await runner.run_one(
        fi,
        run_id="wo1070-adaptive",
        max_hops=0,
        max_forks=0,
        max_fetches=6,
        adaptive_max_fetches=24,
        progress=progress,
    )

    assert progress["fetcher"].max_fetches == 24
    assert "adaptive budget: raised to 24 fetches" in row.note


@pytest.mark.asyncio
async def test_adaptive_budget_disabled_when_ceiling_not_above_max_fetches(
    monkeypatch,
):
    fi = FinderInput(url="https://example.gov/", entry="identify")

    async def fake_identify(url, fetcher, *, platform_hint=None):
        return _identify_blank(
            url, platform="granicus", account_url="https://x.granicus.com/view"
        )

    async def fake_list_account(platform, account_url, fetcher, **kwargs):
        return ListResult(candidates=[], lister="passive_verify:granicus", outcome=None)

    async def fake_resolve(candidates, finder_input, *, max_tries):
        return _no_result(), None

    monkeypatch.setattr(runner, "identify", fake_identify)
    monkeypatch.setattr(runner, "list_account", fake_list_account)
    monkeypatch.setattr(runner, "_resolve_candidates_with_meeting", fake_resolve)

    progress: dict = {}
    await runner.run_one(
        fi,
        run_id="wo1070-adaptive-disabled",
        max_hops=0,
        max_forks=0,
        max_fetches=12,
        adaptive_max_fetches=12,  # not > max_fetches -- disabled
        progress=progress,
    )

    assert progress["fetcher"].max_fetches == 12
