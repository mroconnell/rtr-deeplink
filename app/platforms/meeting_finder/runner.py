"""Runner (WO-1024, wired WO-1030): the phase loop --

    Start -> Identify -> List / Scan -> Hop -> Resolve -> Verdict

for one `FinderInput`, and the driver for a whole input file for
`scripts/meeting_finder.py`.

**Entry points** (docs/MEETING_FINDER.md's "Entry points" table): `start`
runs the full loop from a domain; `identify` runs it from a single page
URL (no Start, no forks beyond what Hop finds); `list` goes straight to
List on a known account (`platform_hint` required) then Resolve; `scan`
scans one page directly then Resolve; `resolve` is unchanged from
WO-1024 -- the input URL is treated as a single candidate and handed
straight to Resolve, no Identify/List/Scan/Hop at all, per the design
doc's own "One meeting URL" row.

**One `Fetcher` per government** (`max_fetches` is a per-government
budget, per docs/MEETING_FINDER.md's Hop "Limits" table) -- every fork
and hop for one `FinderInput` shares the same `Fetcher`, so
`fetches_used` and the per-host politeness spacing (`fetch.py`) apply
across the whole walk, not per fork.

**Forks vs hops.** A fork is one of Start's own starting points (or,
for `entry=identify`, just the one input URL) tried as an independent
path; `max_forks` bounds how many of Start's OTHER starting points (past
the first) get tried. A hop is Hop's own best-next-link choice made
*within* one fork's path; `max_hops` bounds how deep one fork goes (with
one extra hop allowed from the very first/homepage fork, per the design
doc: "one more from a homepage"). Both share one `seen` URL set for the
whole government -- a URL is never fetched twice, whether reached again
as a different fork's hop or a different hop's own link.

**Verdict's outcome choice** ("pick the most informative of the phases'
outcomes") is `_pick_outcome()` below: a real meeting found with no video
outranks "no platform found", which outranks a generic access block,
which outranks reporting nothing at all. See its own table for the exact
order.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from .fetch import BudgetExceeded, Fetcher
from .hop import rank_hops
from .identify import identify
from .identity import check_identity
from .listing import list_account
from .models import (
    OUTCOME_ACCOUNT_NOT_FOUND,
    OUTCOME_MEETING_WITHOUT_VIDEO,
    OUTCOME_NO_MEETING_NOR_VIDEO,
    OUTCOME_OFF_MISSION,
    OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER,
    Candidate,
    FinderInput,
    VerdictRow,
)
from .resolve import _resolve_candidates_with_meeting
from .scan import scan_page
from .start import start as run_start
from .verdict import append_verdict, load_done

# Phase order for VerdictRow.phase_reached -- the furthest phase any fork
# of this government's walk actually got to, regardless of which fork
# eventually produced the result (or didn't).
_PHASE_ORDER = ["start", "identify", "list", "scan", "hop", "resolve"]
_PHASE_INDEX = {name: i for i, name in enumerate(_PHASE_ORDER)}

# Verdict's "most informative outcome" ranking (docs/MEETING_FINDER.md's
# Verdict section: "e.g. a real meeting without video beats 'no
# platform'; an access block with no Wayback links beats nothing").
# Higher wins. Anything not listed here (an unrecognized/new outcome
# spelling) ranks just above the floor rather than below every known
# outcome, so a genuinely new finding is never silently outranked by
# "nothing found".
_OUTCOME_PRIORITY: Dict[str, int] = {
    OUTCOME_MEETING_WITHOUT_VIDEO: 100,
    OUTCOME_ACCOUNT_NOT_FOUND: 90,
    OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER: 80,
    OUTCOME_OFF_MISSION: 75,
    "cloudflare-challenge-blocked": 60,
    "blocked-waf-akamai": 60,
    "blocked-browser-headers": 55,
    "blocked-headless": 55,
    "timeout": 40,
    "dns-unresolvable": 35,
    "youtube-not-fetched": 20,
    OUTCOME_NO_MEETING_NOR_VIDEO: 10,
}
_UNKNOWN_OUTCOME_PRIORITY = 6
_FLOOR_PRIORITY = 0


def _pick_outcome(outcomes: List[str]) -> str:
    if not outcomes:
        return OUTCOME_NO_MEETING_NOR_VIDEO
    return max(
        outcomes,
        key=lambda o: _OUTCOME_PRIORITY.get(o, _UNKNOWN_OUTCOME_PRIORITY),
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class _WalkState:
    path: List[str] = field(default_factory=list)
    leads: List[Dict[str, Any]] = field(default_factory=list)
    outcomes: List[str] = field(default_factory=list)
    hops: int = 0
    forks: int = 0
    result: Optional[Any] = None  # ResolveResult, once one succeeds
    meeting: Optional[Any] = None  # ResolvedMeeting behind `result`
    phase_reached_index: int = -1
    budget_exhausted: bool = False

    def reach(self, phase: str) -> None:
        idx = _PHASE_INDEX[phase]
        if idx > self.phase_reached_index:
            self.phase_reached_index = idx

    @property
    def phase_reached(self) -> str:
        if self.phase_reached_index < 0:
            return "start"
        return _PHASE_ORDER[self.phase_reached_index]

    @property
    def done(self) -> bool:
        return self.result is not None or self.budget_exhausted


def _youtube_leads(urls: Iterable[str], *, found_at: str) -> List[Dict[str, Any]]:
    return [{"kind": "youtube", "url": u, "found_at": found_at} for u in urls]


async def _try_resolve(
    candidates: List[Candidate],
    finder_input: FinderInput,
    state: _WalkState,
    *,
    max_tries: int,
) -> bool:
    """Runs Resolve on `candidates`; on success, records the winner on
    `state` and returns True. On failure, records the outcome and
    returns False so the caller keeps looking (Scan/Hop, or the next
    fork)."""
    result, meeting = await _resolve_candidates_with_meeting(
        candidates, finder_input, max_tries=max_tries
    )
    state.reach("resolve")
    if result.outcome is None:
        state.result = result
        state.meeting = meeting
        return True
    state.outcomes.append(result.outcome)
    return False


async def _walk_from(
    url: str,
    fetcher: Fetcher,
    finder_input: FinderInput,
    state: _WalkState,
    *,
    hops_left: int,
    seen: Set[str],
    max_tries: int,
    prefer_vendor: Optional[str] = None,
) -> None:
    """One fork's own path: Identify -> List/Scan -> Hop, recursing into
    Hop's own best next link while `hops_left` allows and nothing has
    resolved yet. Mutates `state` in place; never raises `BudgetExceeded`
    -- caught here and turned into `state.budget_exhausted = True` so the
    caller's fork/hop loops stop cleanly."""
    if state.done or url in seen:
        return
    seen.add(url)
    state.path.append(url)

    try:
        ident = await identify(url, fetcher, platform_hint=finder_input.platform_hint)
    except BudgetExceeded:
        state.budget_exhausted = True
        return
    state.reach("identify")
    state.leads.extend(_youtube_leads(ident.youtube_leads, found_at=url))
    if ident.guess_queue_row:
        row = dict(ident.guess_queue_row)
        row["kind"] = "guess_queue"
        row["url"] = url
        state.leads.append(row)
    if ident.outcome:
        state.outcomes.append(ident.outcome)

    page = ident.page
    prefer_vendor = ident.web_host_hint or ident.platform or prefer_vendor

    if ident.platform and ident.account_url and ident.supported is not False:
        try:
            list_result = await list_account(ident.platform, ident.account_url, fetcher)
        except BudgetExceeded:
            state.budget_exhausted = True
            return
        state.reach("list")
        if list_result.outcome:
            state.outcomes.append(list_result.outcome)
        if list_result.candidates:
            if await _try_resolve(
                list_result.candidates, finder_input, state, max_tries=max_tries
            ):
                return

    if not state.done and page is not None and page.html:
        try:
            scan_result = await scan_page(page, fetcher)
        except BudgetExceeded:
            state.budget_exhausted = True
            return
        state.reach("scan")
        state.leads.extend(
            {"kind": "youtube", **lead} for lead in scan_result.youtube_leads
        )
        if scan_result.media_candidates:
            if await _try_resolve(
                scan_result.media_candidates, finder_input, state, max_tries=max_tries
            ):
                return

    if not state.done and hops_left > 0 and page is not None and page.html:
        hops = rank_hops(page, prefer_vendor=prefer_vendor)
        state.reach("hop")
        for hop in hops:
            if hop.url in seen:
                continue
            state.hops += 1
            await _walk_from(
                hop.url,
                fetcher,
                finder_input,
                state,
                hops_left=hops_left - 1,
                seen=seen,
                max_tries=max_tries,
                prefer_vendor=prefer_vendor,
            )
            # Only the single best not-yet-seen hop per level (docs/
            # MEETING_FINDER.md's Hop: "Pick the best next page to
            # open" -- singular).
            break


async def _run_phase_loop(
    finder_input: FinderInput,
    fetcher: Fetcher,
    *,
    max_tries: int,
    max_hops: int,
    max_forks: int,
) -> _WalkState:
    state = _WalkState()
    seen: Set[str] = set()

    if finder_input.entry == "list":
        if not finder_input.platform_hint:
            state.outcomes.append(OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER)
            return state
        try:
            list_result = await list_account(
                finder_input.platform_hint, finder_input.url, fetcher
            )
        except BudgetExceeded:
            state.budget_exhausted = True
            return state
        state.reach("list")
        state.path.append(finder_input.url)
        if list_result.outcome:
            state.outcomes.append(list_result.outcome)
        if list_result.candidates:
            await _try_resolve(
                list_result.candidates, finder_input, state, max_tries=max_tries
            )
        return state

    if finder_input.entry == "scan":
        state.path.append(finder_input.url)
        try:
            page = await fetcher.fetch(finder_input.url)
        except BudgetExceeded:
            state.budget_exhausted = True
            return state
        state.reach("scan")
        if page.outcome:
            state.outcomes.append(page.outcome)
        if page.html:
            scan_result = await scan_page(page, fetcher)
            state.leads.extend(
                {"kind": "youtube", **lead} for lead in scan_result.youtube_leads
            )
            if scan_result.media_candidates:
                await _try_resolve(
                    scan_result.media_candidates,
                    finder_input,
                    state,
                    max_tries=max_tries,
                )
        return state

    if finder_input.entry == "start":
        try:
            start_result = await run_start(finder_input.url, fetcher)
        except BudgetExceeded:
            state.budget_exhausted = True
            return state
        state.reach("start")
        if start_result.outcome:
            state.outcomes.append(start_result.outcome)
            return state
        starting_points = start_result.starting_points or [finder_input.url]
        # "one more [hop] from a homepage" -- Start's own first starting
        # point (its own homepage variant) gets one extra hop of depth.
        first_hops_budget = max_hops + 1
    else:  # "identify" -- a single page URL, no Start, no forks.
        starting_points = [finder_input.url]
        first_hops_budget = max_hops

    forks_tried = 0
    for i, point in enumerate(starting_points):
        if state.done:
            break
        if point in seen:
            continue
        if i > 0:
            if forks_tried >= max_forks:
                break
            forks_tried += 1
            state.forks += 1
        await _walk_from(
            point,
            fetcher,
            finder_input,
            state,
            hops_left=first_hops_budget if i == 0 else max_hops,
            seen=seen,
            max_tries=max_tries,
        )

    return state


async def run_one(
    finder_input: FinderInput,
    *,
    run_id: str,
    max_tries: int = 6,
    max_hops: int = 2,
    max_forks: int = 3,
    max_fetches: int = 12,
) -> VerdictRow:
    """Runs the whole pipe for one input and returns its `VerdictRow`.
    Never raises for an ordinary resolve/access failure -- those come
    back as a named outcome; a genuinely unexpected exception is left to
    propagate, since Verdict should never silently swallow a real bug."""
    if finder_input.entry == "resolve":
        candidates = [Candidate(url=finder_input.url, source_phase="input")]
        result, meeting = await _resolve_candidates_with_meeting(
            candidates, finder_input, max_tries=max_tries
        )
        identity = check_identity(meeting, finder_input)
        leads = []
        if result.tier == 2 and result.candidate is not None:
            leads.append({"kind": "youtube", "url": result.candidate.url})
        return VerdictRow(
            run_id=run_id,
            input_url=finder_input.url,
            entry_phase=finder_input.entry,
            path=[finder_input.url]
            + (
                [result.candidate.url]
                if result.candidate and result.candidate.url != finder_input.url
                else []
            ),
            phase_reached="resolve",
            result_url=result.video_url,
            platform=result.platform,
            tier=result.tier,
            duration_seconds=result.duration_seconds,
            outcome=result.outcome,
            identity_verdict=identity.verdict,
            identity_expected_gov_id=identity.expected_gov_id,
            identity_resolved_gov_id=identity.resolved_gov_id,
            identity_points_to=identity.points_to,
            leads=leads,
            hops=0,
            forks=0,
            fetches=1,
            note=result.note,
            finished_at=_now_iso(),
        )

    fetcher = Fetcher(max_fetches=max_fetches)
    try:
        state = await _run_phase_loop(
            finder_input,
            fetcher,
            max_tries=max_tries,
            max_hops=max_hops,
            max_forks=max_forks,
        )
    finally:
        await fetcher.aclose()

    identity = check_identity(state.meeting, finder_input)
    result = state.result

    if result is not None:
        outcome = None
        result_url = result.video_url
        platform = result.platform
        tier = result.tier
        duration_seconds = result.duration_seconds
        note = result.note
        if result.tier == 2 and result.candidate is not None:
            state.leads.append({"kind": "youtube", "url": result.candidate.url})
    else:
        outcome = _pick_outcome(state.outcomes)
        result_url = None
        platform = None
        tier = None
        duration_seconds = None
        note = "; ".join(dict.fromkeys(state.outcomes)) or (
            "budget exhausted before anything resolved"
            if state.budget_exhausted
            else "nothing found"
        )

    return VerdictRow(
        run_id=run_id,
        input_url=finder_input.url,
        entry_phase=finder_input.entry,
        path=state.path,
        phase_reached=state.phase_reached,
        result_url=result_url,
        platform=platform,
        tier=tier,
        duration_seconds=duration_seconds,
        outcome=outcome,
        identity_verdict=identity.verdict,
        identity_expected_gov_id=identity.expected_gov_id,
        identity_resolved_gov_id=identity.resolved_gov_id,
        identity_points_to=identity.points_to,
        leads=state.leads,
        hops=state.hops,
        forks=state.forks,
        fetches=fetcher.fetches_used,
        note=note,
        finished_at=_now_iso(),
    )


async def run_inputs(
    inputs: Iterable[FinderInput],
    out_path: Path,
    *,
    max_tries: int = 6,
    max_hops: int = 2,
    max_forks: int = 3,
    max_fetches: int = 12,
    concurrency: int = 1,
    run_id: Optional[str] = None,
) -> List[VerdictRow]:
    """Drive every input in `inputs`, appending a `VerdictRow` to
    `out_path` (+ its JSONL twin) as each one finishes so a rerun resumes
    (`load_done()` skips an `input_url` already in `out_path`).

    `concurrency=1` (the default) runs one input at a time -- CLAUDE.md's
    "we query sites politely" rule; a `--concurrency` above 1 is a
    deliberate opt-in the CLI exposes. Each input gets its own `Fetcher`
    (own `max_fetches` budget), but `fetch.py`'s own process-wide
    per-host pacer (WO-1030) still spaces out two concurrent governments
    that share a vendor host."""
    run_id = run_id or uuid.uuid4().hex[:12]
    done = load_done(out_path)
    todo = [i for i in inputs if i.url not in done]

    rows: List[VerdictRow] = []
    sem = asyncio.Semaphore(max(1, concurrency))

    async def _one(finder_input: FinderInput) -> None:
        async with sem:
            row = await run_one(
                finder_input,
                run_id=run_id,
                max_tries=max_tries,
                max_hops=max_hops,
                max_forks=max_forks,
                max_fetches=max_fetches,
            )
            append_verdict(out_path, row)
            rows.append(row)

    if concurrency <= 1:
        for finder_input in todo:
            await _one(finder_input)
    else:
        await asyncio.gather(*(_one(fi) for fi in todo))

    return rows
