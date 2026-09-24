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
import contextvars
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set
from urllib.parse import urlparse

from app.platforms.base import detect_platform
from scripts.youtube_fetch_guard import is_youtube_host

from .fetch import BudgetExceeded, Fetcher
from .hop import canonical_page_key, rank_hops
from .identify import IdentifyResult, _classify_url, identify
from .identity import check_identity
from .listing import list_account
from .models import (
    OUTCOME_ACCOUNT_NOT_FOUND,
    OUTCOME_YOUTUBE_LEAD_ONLY,
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
    # WO-1031: a YouTube lead beats an access block (Essex, ON) but never a
    # real meeting-without-video finding -- almost every government site has
    # a YouTube icon in its footer, so ranking it higher would hide findings.
    OUTCOME_YOUTUBE_LEAD_ONLY: 85,
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

# See the call site's own comment: `rank_hops()`'s ranked list is
# filtered AFTER the fact (YouTube, already-known-platform links), so it
# needs to hand back more than its own small default limit or a real
# candidate further down the list never gets a chance.
_HOP_CANDIDATE_LIMIT = 25

# How many of Scan's own found (not opened) meeting-page links get a
# full Identify+List pass in `_deep_step()`, per fork. Small on purpose
# -- each one costs a real fetch, and this runs on every fork.
_SCAN_LINK_FOLLOW_LIMIT = 3


# WO-1031 (Ryan, 2026-09-23): "a good discovery rate and some well-marked
# failures which we will return to". Each failure outcome maps to the next
# thing a person (or a later pass) should try. Plain words, one line each.
_TRY_NEXT: Dict[str, str] = {
    OUTCOME_MEETING_WITHOUT_VIDEO: (
        "meetings found but no video: follow the meetings page's watch/video "
        "links, or check another video host by hand"
    ),
    OUTCOME_ACCOUNT_NOT_FOUND: "vendor known, account not found: guess-ladder queue",
    OUTCOME_YOUTUBE_LEAD_ONLY: "YouTube only: send to the drip",
    OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER: (
        "platform has no adapter: record in UNSUPPORTED_PLATFORMS.md"
    ),
    OUTCOME_OFF_MISSION: "video found but not a meeting: hand-check 3+ videos deeper",
    "cloudflare-challenge-blocked": "blocked: try another network, or Wayback by hand",
    "blocked-waf-akamai": "blocked: try another network, or Wayback by hand",
    "blocked-browser-headers": "blocked: try another network, or Wayback by hand",
    "blocked-headless": "blocked: try another network, or Wayback by hand",
    "timeout": "site timed out: retry later",
    "dns-unresolvable": "domain dead: find the current website (alternate domains)",
}


def _try_next(outcome: Optional[str], budget_exhausted: bool) -> str:
    if outcome is None:
        return ""
    if outcome in _TRY_NEXT:
        return _TRY_NEXT[outcome]
    if budget_exhausted:
        return (
            "budget ran out: hand-check the site nav (Meetings / Agendas & "
            "Minutes), or rerun with a bigger budget"
        )
    return "nothing found: hand-check the site nav (Meetings / Agendas & Minutes)"


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


_CALENDAR_PATH_RE = re.compile(r"calendar\.aspx|/calendar/|/events?/", re.I)


def _norm_url(url: str) -> str:
    """Trailing-slash and fragment normalization for the `seen` set only
    (display/reporting always uses the raw url). Confirmed live necessary
    on Piedmont, CA (conductor review, 2026-09-23): `rank_hops()` ranked
    a page's own canonical self-link (identical URL, trailing slash
    added) above the real next hop -- without this, that self-link isn't
    recognized as already visited, and a hop budget slot is wasted
    re-fetching a page already in hand."""
    parsed = urlparse(url)
    # WO-1031: a calendar page fetched with different display parameters
    # (`Calendar.aspx?EID=2662`, `?PREVIEW=YES&EID=2662`,
    # `?EID=2662&month=9&year=2026&day=23&calType=0` -- Emporia, KS, all
    # opened in one run) is ONE page. Only calendar-shaped addresses are
    # collapsed: `hop.canonical_page_key()` drops month/year/view from every
    # URL, and a meeting archive filtered by `?year=2024` vs `?year=2025`
    # is a genuinely different list.
    if _CALENDAR_PATH_RE.search(parsed.path):
        return canonical_page_key(url)
    path = parsed.path
    if len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return parsed._replace(path=path, fragment="").geturl()


def _youtube_leads(urls: Iterable[str], *, found_at: str) -> List[Dict[str, Any]]:
    return [{"kind": "youtube", "url": u, "found_at": found_at} for u in urls]


@dataclass
class _Lanes:
    """WO-1031 back-pressure (Ryan, 2026-09-23): many governments run the
    cheap phases (Start/Identify/Scan/Hop) at once, but Resolve -- the
    expensive phase (adapters, length probe, sometimes a headless
    browser) -- takes a slot from a small shared pool. `waiting` counts
    governments queued for a Resolve slot; run_inputs() stops admitting new
    governments while it is above `max_waiting`, so the top of the funnel
    eases off as leads pile up in the slow part and opens again as they
    convert."""

    resolve_slots: asyncio.Semaphore
    max_waiting: int
    waiting: int = 0
    resolving: int = 0


# Task-local (each government's asyncio task inherits the run's lanes);
# None outside run_inputs(), so a bare run_one() call is unaffected.
_LANES: "contextvars.ContextVar[Optional[_Lanes]]" = contextvars.ContextVar(
    "meeting_finder_lanes", default=None
)


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
    lanes = _LANES.get()
    if lanes is None:
        result, meeting = await _resolve_candidates_with_meeting(
            candidates, finder_input, max_tries=max_tries
        )
    else:
        lanes.waiting += 1
        try:
            await lanes.resolve_slots.acquire()
        finally:
            lanes.waiting -= 1
        lanes.resolving += 1
        try:
            result, meeting = await _resolve_candidates_with_meeting(
                candidates, finder_input, max_tries=max_tries
            )
        finally:
            lanes.resolving -= 1
            lanes.resolve_slots.release()
    state.reach("resolve")
    if result.outcome is None:
        state.result = result
        state.meeting = meeting
        return True
    state.outcomes.append(result.outcome)
    return False


async def _shallow_step(
    url: str,
    fetcher: Fetcher,
    finder_input: FinderInput,
    state: _WalkState,
    *,
    seen: Set[str],
    max_tries: int,
) -> Optional[IdentifyResult]:
    """Identify, then List (if a platform+account was found), then
    Resolve on whatever List handed back. Cheap relative to Scan/Hop --
    usually 1-3 fetches. Returns the `IdentifyResult` (its own fetched
    `page` reused by a later `_deep_step()` call), or `None` when the
    walk is already done (resolved, or budget exhausted) or `url` was
    already seen.

    **Why this is split from Scan/Hop (conductor review, WO-1030,
    2026-09-23):** the phase loop used to run Identify->List->Scan->Hop
    on ONE starting point all the way through before trying the next
    fork. Confirmed live on Pomona, CA (`pomonaca.gov`): the homepage
    fork found a real Legistar account (correctly resolved to zero video
    -- Pomona's Legistar tenant genuinely has none in its newest
    meetings) and then Scan (which opens several meeting-page links,
    itself several fetches) plus a Hop chain spent the ENTIRE 12-fetch
    government budget before `live.pomonaca.gov` -- Start's own guessed-
    subdomain starting point, a real Cablecast account with a real video
    one fetch away -- ever got a turn. `_run_phase_loop()` now runs this
    cheap shallow step across every fork FIRST (see its own docstring),
    and only spends the more expensive Scan/Hop budget once none of them
    resolved on their own."""
    if state.done or _norm_url(url) in seen:
        return None
    seen.add(_norm_url(url))
    state.path.append(url)

    try:
        ident = await identify(url, fetcher, platform_hint=finder_input.platform_hint)
    except BudgetExceeded:
        state.budget_exhausted = True
        return None
    state.reach("identify")
    # A later fork/hop landing on the SAME final page (e.g. a plain-http
    # homepage variant that just redirects to the https one already
    # tried) is marked seen too, so it's skipped before spending a fetch
    # on a page already in hand -- real, confirmed savings on Piedmont,
    # CA (`http://piedmont.ca.gov/` redirects straight to
    # `https://piedmont.ca.gov/`, itself already tried as the first
    # fork).
    if ident.final_url:
        seen.add(_norm_url(ident.final_url))
    state.leads.extend(_youtube_leads(ident.youtube_leads, found_at=url))
    if ident.guess_queue_row:
        row = dict(ident.guess_queue_row)
        row["kind"] = "guess_queue"
        row["url"] = url
        state.leads.append(row)
    if ident.outcome:
        state.outcomes.append(ident.outcome)

    if ident.platform and ident.account_url and ident.supported is not False:
        try:
            list_result = await list_account(ident.platform, ident.account_url, fetcher)
        except BudgetExceeded:
            state.budget_exhausted = True
            return None
        state.reach("list")
        if list_result.outcome:
            state.outcomes.append(list_result.outcome)
        if list_result.candidates:
            if await _try_resolve(
                list_result.candidates, finder_input, state, max_tries=max_tries
            ):
                return None  # resolved -- no deep pass needed for this fork

    return ident


async def _deep_step(
    url: str,
    ident: IdentifyResult,
    fetcher: Fetcher,
    finder_input: FinderInput,
    state: _WalkState,
    *,
    hops_left: int,
    seen: Set[str],
    max_tries: int,
    prefer_vendor: Optional[str] = None,
) -> None:
    """Scan, then Hop (recursing into Hop's own best next link -- via
    `_walk_from()`, shallow+deep together -- while `hops_left` allows and
    nothing has resolved yet). Mutates `state` in place; never raises
    `BudgetExceeded`."""
    if state.done:
        return
    page = ident.page
    # `ident.platform` only belongs here as a hop preference in
    # docs/MEETING_FINDER.md's "platform known, account unknown" case
    # (`ident.account_url is None`) -- weighting Hop toward MORE of a
    # platform we already have a real account for is never useful and,
    # confirmed live on Piedmont, CA (conductor review, 2026-09-23),
    # actively harmful: Identify found `civiclive` (the city's own
    # website CMS, not a meeting platform) with a real account, and the
    # old blanket `prefer_vendor = ... or ident.platform or ...` pushed
    # Hop even harder toward more CivicLive navigation pages instead of
    # the real Granicus meeting-video hub two hops away.
    known_platform = ident.platform if ident.account_url is None else None
    prefer_vendor = ident.web_host_hint or known_platform or prefer_vendor

    if page is not None and page.html:
        try:
            # `max_meeting_pages` capped at 3, not `scan_page()`'s own
            # default of 6 -- conductor review, 2026-09-23, found live on
            # Piedmont, CA: opening 6 meeting-page links against one
            # fork's own government budget left too little for Hop to
            # ever reach a real vendor found 2 hops deep (Granicus,
            # `view_id=9`, behind a `meeting_videos` nav page). Breadth
            # across forks/hops matters more here than one fork's own
            # deep meeting-page scan -- this module's own docstring calls
            # that out as the whole reason for the two-pass shallow/deep
            # split.
            # `max_meeting_pages=0`: find meeting-page links (a free scan
            # of html already in hand -- see this call's own `note`
            # below), but don't have Scan open them itself. Its own
            # `_anchor_media_candidates()` only recognizes vimeo/civicweb/
            # direct-file media on an opened sub-page -- confirmed live on
            # Piedmont, CA (conductor review, 2026-09-23) that this misses
            # a real Granicus tenant embedded on `/government/
            # meeting_videos`: Scan opened it, found no *media* by its own
            # narrow definition, and the fetch was wasted. Running the
            # full `identify()`/`list_account()` pass below on the SAME
            # links instead catches a vendor PLATFORM one click down, not
            # just a bare media file -- the more common real shape.
            scan_result = await scan_page(page, fetcher, max_meeting_pages=0)
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

        for link in scan_result.meeting_page_links[:_SCAN_LINK_FOLLOW_LIMIT]:
            if state.done:
                return
            await _shallow_step(
                link, fetcher, finder_input, state, seen=seen, max_tries=max_tries
            )

    if not state.done and hops_left > 0 and page is not None and page.html:
        # `limit` well above `rank_hops()`'s own default (8): this loop
        # below excludes YouTube and already-known-platform links AFTER
        # ranking, and both can legitimately fill most or all of the top
        # 8 (confirmed live on Piedmont, CA, conductor review 2026-09-23
        # -- 3 CivicLive CMS nav links + 6 YouTube links outrank the real
        # own-site meeting-agendas page, which would never even appear in
        # the returned list at the default limit, let alone survive the
        # exclusion filter below).
        hops = rank_hops(page, prefer_vendor=prefer_vendor, limit=_HOP_CANDIDATE_LIMIT)
        state.reach("hop")
        for hop in hops:
            if _norm_url(hop.url) in seen:
                continue
            if is_youtube_host(urlparse(hop.url).hostname or ""):
                # Conductor review (2026-09-23), found live on Boston,
                # MA: `rank_hops()` (a generic link scorer, not YouTube-
                # aware) can rank a homepage's own YouTube channel/video
                # link above a real Legistar link -- Meeting Finder never
                # fetches YouTube (fetch.py's own guard would just refuse
                # it anyway), so a hop here would silently burn a hop slot
                # on a dead end. Record it as a lead instead and keep
                # looking at the next-ranked hop, without spending
                # `hops_left` or `state.hops` on it.
                seen.add(_norm_url(hop.url))
                state.leads.append(
                    {"kind": "youtube", "url": hop.url, "found_at": "hop"}
                )
                continue
            if (
                ident.platform
                and ident.account_url is not None
                and detect_platform(hop.url) == ident.platform
            ):
                # Conductor review (2026-09-23), found live on Piedmont,
                # CA: we already have a real account for `ident.platform`
                # (List already tried it, above) -- another link to the
                # SAME platform (CivicLive's own generic CMS navigation
                # pages, all scoring above the real Granicus meeting-video
                # hub two hops away) adds nothing new and only burns hop
                # budget re-exploring a platform Resolve already looked
                # at. Skip it, without spending `hops_left`/`state.hops`.
                seen.add(_norm_url(hop.url))
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
            # Only the single best not-yet-seen, non-YouTube hop per
            # level (docs/MEETING_FINDER.md's Hop: "Pick the best next
            # page to open" -- singular).
            break


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
    """Shallow then deep, immediately, for ONE url -- used for a Hop
    target (a hop is a sequential "next thing to try", not a fork
    competing with siblings for budget, so it gets the full
    Identify->List->Scan->Hop treatment in one go). The top-level fork
    loop in `_run_phase_loop()` calls `_shallow_step()`/`_deep_step()`
    directly instead, in two separate passes across every fork -- see
    `_shallow_step()`'s own docstring for why."""
    ident = await _shallow_step(
        url, fetcher, finder_input, state, seen=seen, max_tries=max_tries
    )
    if ident is None:
        return
    await _deep_step(
        url,
        ident,
        fetcher,
        finder_input,
        state,
        hops_left=hops_left,
        seen=seen,
        max_tries=max_tries,
        prefer_vendor=prefer_vendor,
    )


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
        # Conductor review (2026-09-23): a vendor account URL entered at
        # `start` (e.g. `cityoftacoma.granicus.com`, already a real
        # Granicus tenant host) must not be treated as a government
        # domain to DNS-guess homepages around -- `_classify_url()` is
        # the same rule-1 "URL/host match, no fetch" check `identify()`
        # itself runs first; if it already recognizes a platform, skip
        # `start()` entirely and go straight to the shallow (Identify->
        # List) step on the URL as given, exactly like `entry=identify`.
        normalized = finder_input.url
        if "://" not in normalized:
            normalized = f"https://{normalized}"
        direct_platform, _ = _classify_url(normalized)
        if direct_platform is not None:
            starting_points = [normalized]
            first_hops_budget = max_hops
        else:
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
            # "one more [hop] from a homepage" -- Start's own first
            # starting point (its own homepage variant) gets one extra
            # hop of depth.
            first_hops_budget = max_hops + 1
    else:  # "identify" -- a single page URL, no Start, no forks.
        starting_points = [finder_input.url]
        first_hops_budget = max_hops

    # Pass 1 (breadth, cheap): Identify -> List -> Resolve on every fork
    # BEFORE any fork spends budget on Scan/Hop -- see `_shallow_step()`'s
    # own docstring for the real government (Pomona, CA) this fixes.
    forks_tried = 0
    pending_deep: List[tuple[str, IdentifyResult, int]] = []
    for i, point in enumerate(starting_points):
        if state.done:
            break
        if _norm_url(point) in seen:
            continue
        if i > 0:
            if forks_tried >= max_forks:
                break
            forks_tried += 1
            state.forks += 1
        hops_budget = first_hops_budget if i == 0 else max_hops
        ident = await _shallow_step(
            point, fetcher, finder_input, state, seen=seen, max_tries=max_tries
        )
        if ident is not None:
            pending_deep.append((point, ident, hops_budget))

    # Pass 2 (depth): Scan + Hop, fork by fork in the same order, only
    # for forks that didn't already resolve in pass 1 -- stops at the
    # first success or when the shared fetch budget runs out.
    if not state.done:
        for point, ident, hops_budget in pending_deep:
            if state.done:
                break
            await _deep_step(
                point,
                ident,
                fetcher,
                finder_input,
                state,
                hops_left=hops_budget,
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
        if any(lead.get("kind") == "youtube" for lead in state.leads):
            state.outcomes.append(OUTCOME_YOUTUBE_LEAD_ONLY)
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
        try_next=_try_next(outcome, state.budget_exhausted),
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
    resolve_slots: Optional[int] = None,
    max_waiting: Optional[int] = None,
    lanes_log: Optional[Path] = None,
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

    async def _run(finder_input: FinderInput) -> None:
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
            await _run(finder_input)
        return rows

    # WO-1031 back-pressure: `concurrency` is the INTAKE (governments in
    # flight at once); `resolve_slots` bounds the expensive Resolve phase;
    # no new government is admitted while more than `max_waiting` are
    # queued for a Resolve slot. Defaults keep Resolve at a quarter of
    # intake (min 1) and let the queue hold two rounds of slots.
    slots = resolve_slots or max(1, concurrency // 4)
    lanes = _Lanes(
        resolve_slots=asyncio.Semaphore(slots),
        max_waiting=max_waiting if max_waiting is not None else 2 * slots,
    )
    token = _LANES.set(lanes)
    intake = asyncio.Semaphore(concurrency)
    active = 0
    finished = 0
    started_at = time.monotonic()

    def _log(event: str) -> None:
        if lanes_log is None:
            return
        with Path(lanes_log).open("a", encoding="utf-8") as f:
            f.write(
                f"{time.monotonic() - started_at:.1f}\t{event}\tactive={active}"
                f"\twaiting={lanes.waiting}\tresolving={lanes.resolving}"
                f"\tfinished={finished}/{len(todo)}\n"
            )

    async def _admitted(finder_input: FinderInput) -> None:
        nonlocal active, finished
        try:
            await _run(finder_input)
        finally:
            active -= 1
            finished += 1
            intake.release()
            _log("done")

    tasks = []
    try:
        for finder_input in todo:
            await intake.acquire()
            while lanes.waiting > lanes.max_waiting:
                await asyncio.sleep(0.5)
            active += 1
            _log("admit")
            tasks.append(asyncio.create_task(_admitted(finder_input)))
        await asyncio.gather(*tasks)
    finally:
        _LANES.reset(token)
    return rows
