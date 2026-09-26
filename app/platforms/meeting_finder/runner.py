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
import dataclasses
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlparse

from app.platforms.base import detect_platform
from app.platforms.telvue import account_url_for as telvue_account_url_for
from app.utils.gov_registry.registry import Government, government_for_id
from app.utils.video_hand_check import has_non_meeting_sign
from scripts.youtube_fetch_guard import is_youtube_host

from .fetch import BudgetExceeded, Fetcher, SoftBudgetExceeded
from .hop import _SOCIAL_LEAD_PLATFORMS, canonical_page_key, is_document_hub, rank_hops
from .identify import IdentifyResult, _classify_url, identify
from .identity import check_identity
from .listing import ListResult, list_account
from .pacing import pace_all_requests
from .models import (
    OUTCOME_ACCOUNT_NOT_FOUND,
    OUTCOME_EMBED_RESTRICTED,
    OUTCOME_ERROR,
    OUTCOME_HUB_OTHER_GOVERNMENT,
    OUTCOME_YOUTUBE_LEAD_ONLY,
    OUTCOME_MEETING_WITHOUT_VIDEO,
    OUTCOME_NO_MEETING_NOR_VIDEO,
    OUTCOME_OFF_MISSION,
    OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER,
    OUTCOME_VIDEO_LOW_CONFIDENCE,
    Candidate,
    FinderInput,
    VerdictRow,
)
from .resolve import _resolve_candidates_with_meeting
from .scan import scan_page
from .start import start as run_start
from .verdict import append_verdict, load_done

logger = logging.getLogger("rtr_deeplink.meeting_finder.runner")

# Phase order for VerdictRow.phase_reached -- the furthest phase any fork
# of this government's walk actually got to, regardless of which fork
# eventually produced the result (or didn't).
_PHASE_ORDER = ["start", "identify", "list", "scan", "hop", "resolve"]
_PHASE_INDEX = {name: i for i, name in enumerate(_PHASE_ORDER)}

# WO-1038 addendum (Ryan, 2026-09-23): a hard per-government wall-clock
# cap. Real incident: run B had two governments (villageofallouezwi.gov,
# athenslibrary.org) hang 30+ minutes each -- well past `max_fetches`
# ever mattering, because the hang sits inside a SYNCHRONOUS call
# (`fetch.py`'s headless-browser helper, run via `asyncio.to_thread()`),
# not in an ordinary awaited network request. See
# `_run_one_with_timeout()`'s own docstring for why this is built on
# `asyncio.wait(timeout=...)` (which returns the instant the deadline
# passes, full stop) rather than `asyncio.wait_for()` (whose own
# cancel-and-wait can itself block past the deadline if the thing it's
# cancelling swallows -- or simply can't honor -- the `CancelledError`).
DEFAULT_GOV_TIMEOUT_MINUTES = 15.0
OUTCOME_INTERNAL_TIMEOUT = "internal-timeout"

# Verdict's "most informative outcome" ranking (docs/MEETING_FINDER.md's
# Verdict section: "e.g. a real meeting without video beats 'no
# platform'; an access block with no Wayback links beats nothing").
# Higher wins. Anything not listed here (an unrecognized/new outcome
# spelling) ranks just above the floor rather than below every known
# outcome, so a genuinely new finding is never silently outranked by
# "nothing found".
_OUTCOME_PRIORITY: Dict[str, int] = {
    OUTCOME_MEETING_WITHOUT_VIDEO: 100,
    # WO-1035 follow-up: defensive only -- `run_one()` always handles a
    # `state.low_confidence` fallback directly, before `_pick_outcome()`
    # is ever consulted, so this priority normally never matters. Kept
    # here so a future caller of `_pick_outcome()` on a raw outcome list
    # still ranks a real (if low-confidence) video above a bare access
    # block or "nothing found".
    # WO-1046: a CONFIRMED real meeting, just access-restricted by its
    # owner -- see `models.OUTCOME_EMBED_RESTRICTED`'s own comment. Same
    # defensive-only note as OUTCOME_VIDEO_LOW_CONFIDENCE above applies:
    # `run_one()` handles `state.low_confidence` directly. Ranked one above
    # it (we KNOW this is a real meeting, not just suspect one).
    OUTCOME_EMBED_RESTRICTED: 96,
    OUTCOME_VIDEO_LOW_CONFIDENCE: 95,
    OUTCOME_ACCOUNT_NOT_FOUND: 90,
    # WO-1054 rule 5: a real account was found and it really does list
    # real meetings -- just not this government's own (a shared TelVue
    # org token/Cablecast tenant). As informative as "account not found"
    # (a human knows exactly what to check next: the SAME vendor, a
    # different token), so ranked alongside it.
    OUTCOME_HUB_OTHER_GOVERNMENT: 90,
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

# WO-1035 item 7: backtrack within one page's own hop ranking instead of
# committing to a single best-ranked link and moving on for good. Real
# governments this fixes (cablecast3/swagit1/swagit2 reports, 2026-09-23):
# Des Plaines IL, Niagara Falls SD NY, James Island SC, Johnson County TX
# all had the REAL vendor link ranked 2nd-6th on a page whose top-ranked
# link dead-ended (an agenda/minutes page with no video). Bounded small --
# this is a safety net for when the top pick doesn't pan out, not a
# license to explore every hop on every page.
_MAX_SIBLING_HOPS_PER_PAGE = 3
# A recognized video-vendor link (`detect_platform()` resolves it) within
# this many points of the top-ranked hop's own score is followed FIRST,
# even when it isn't the literal top score -- `rank_hops()`'s own path/
# anchor-vocabulary scoring has no idea which links are actual video
# platforms, so a near-tied vendor link is strictly better evidence than a
# marginally higher-scoring agenda/minutes page.
_VENDOR_TIE_MARGIN = 5.0

# WO-1031: watch/video links followed from a page whose platform had
# meetings but no video (see `_shallow_step()`).
_VIDEO_FOLLOW_LIMIT = 2
_VIDEO_WORDS_RE = re.compile(
    r"watch|video|stream|on[- ]demand|livestream|broadcast", re.I
)

# WO-1076 item 2 ("one more hop from a meetings page"): Ryan's own context
# words for a link that isn't itself a known platform but whose text/URL
# names how the meeting is broadcast -- widens the vocabulary
# `hop.py`'s `_LINK_CONTEXT_BROADCAST_RE` already rescues by SCORE (a
# nearby paragraph mentioning "streams the meetings"/"airs replays") to
# also cover the plainer case of the link's OWN anchor text/URL, so a
# link like "TVCTV" or "Replays" is recognized even with no surrounding
# sentence at all. Test case: Lake Oswego, OR
# (`ci.oswego.or.us/citycouncil` -> `.../city-council-meetings` -> the
# TVCTV sentence -> `tvctv.org`) -- three real hops from the homepage,
# one more than the ordinary `max_hops=2` (+1 for the first fork) reaches
# once the homepage itself already cost a hop to get past.
_CONTEXT_HOP_WORDS_RE = re.compile(
    r"watch|video|broadcast|stream|replay|\btv\b|channel", re.I
)

# WO-1039 item 2: fetches held back from Pass 1 (Identify->List->Resolve,
# across every fork) for Pass 2 (Scan/Hop) -- real, confirmed problem:
# Ashland, OR's own CivicPlus AgendaCenter listing walk alone used the
# WHOLE 12-fetch government budget in Pass 1, so Hop never got a single
# real fetch to spend (`hops=0` the entire run, per the calibration
# case). Small on purpose -- this is a floor under Pass 2, not a cap
# meant to starve Pass 1's own (usually cheap) work; see `Fetcher.
# reserve()`/`SoftBudgetExceeded` for how it's enforced without marking
# the whole government's walk as budget-exhausted.
_PASS1_BUDGET_RESERVE = 3

# WO-1076 item 1 ("second pass before settling for youtube-lead-only"):
# calibration set D (2026-09-25) found 380 governments ending
# `youtube-lead-only`, ~190 of them with a KNOWN non-YouTube video
# platform on file -- real evidence the site has more to find than the
# ordinary 12-fetch budget reached. When a walk would otherwise end there
# with no platform account and no meeting video ever found
# (`_would_end_youtube_lead_only()`), this many extra fetches are spent on
# one focused pass across every fork's own already-fetched page, following
# only high-value site-nav links (Meetings / Agendas & Minutes /
# Government / Council / Board / Watch / Video / Media / TV --
# `rank_hops()`'s own site-nav scoring already favors these; this only
# narrows which of its ranked hops get followed). Configurable via
# `run_one()`/`run_inputs()`'s `second_pass_extra_fetches` (0 disables it)
# and `scripts/meeting_finder.py --second-pass-extra-fetches`.
_DEFAULT_SECOND_PASS_EXTRA_FETCHES = 8
_SECOND_PASS_NAV_WORDS_RE = re.compile(
    r"\bmeetings?\b|\bagendas?\b|\bminutes\b|\bgovernment\b|\bcouncil\b|\bboard\b"
    r"|\bwatch\b|\bvideos?\b|\bmedia\b|\btv\b",
    re.I,
)
# Each rescued fork gets its own short hop chain (Hop's ordinary sibling-
# hop safety net still applies within it) rather than one bare fetch --
# real governments this targets (calibration set D) often need one more
# click past the nav link itself (e.g. a "Watch Meetings" landing page
# that itself links out to the real vendor).
_SECOND_PASS_HOPS = 2
# Per fork's own already-fetched page, not a total -- bounded small so
# this stays a focused rescue, not a second full breadth pass.
_SECOND_PASS_LINKS_PER_PAGE = 4

# WO-1076 item 3 ("adaptive budget"): once a government's walk turns up
# real promising evidence -- a meetings/agenda page, a recognized video-
# platform account, or a meeting-without-video listing -- raise ITS OWN
# fetch budget instead of stopping at the ordinary default. Configurable
# via `run_one()`/`run_inputs()`'s `adaptive_max_fetches` (<= the ordinary
# `max_fetches` disables it) and `scripts/meeting_finder.py
# --adaptive-max-fetches`.
_DEFAULT_ADAPTIVE_MAX_FETCHES = 24


# WO-1031 (Ryan, 2026-09-23): "a good discovery rate and some well-marked
# failures which we will return to". Each failure outcome maps to the next
# thing a person (or a later pass) should try. Plain words, one line each.
_TRY_NEXT: Dict[str, str] = {
    OUTCOME_ERROR: "unexpected error (see note): fix the cause and rerun",
    OUTCOME_MEETING_WITHOUT_VIDEO: (
        "meetings found but no video: follow the meetings page's watch/video "
        "links, or check another video host by hand"
    ),
    OUTCOME_ACCOUNT_NOT_FOUND: "vendor known, account not found: guess-ladder queue",
    OUTCOME_HUB_OTHER_GOVERNMENT: (
        "hub found, but it only lists other governments: look for this "
        "government's own account/token on the same vendor, or hand-check"
    ),
    OUTCOME_YOUTUBE_LEAD_ONLY: "YouTube only: send to the drip",
    OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER: (
        "platform has no adapter: record in UNSUPPORTED_PLATFORMS.md"
    ),
    OUTCOME_OFF_MISSION: "video found but not a meeting: hand-check 3+ videos deeper",
    OUTCOME_VIDEO_LOW_CONFIDENCE: (
        "video found but low confidence (see note): hand-check it, or look for a "
        "cleaner candidate on the same account"
    ),
    # WO-1046 (Ryan, 2026-09-24): exact wording asked for.
    OUTCOME_EMBED_RESTRICTED: (
        "video plays only on the government's own site: link out, can't "
        "embed or transcribe"
    ),
    "cloudflare-challenge-blocked": "blocked: try another network, or Wayback by hand",
    "blocked-waf-akamai": "blocked: try another network, or Wayback by hand",
    "blocked-browser-headers": "blocked: try another network, or Wayback by hand",
    "blocked-headless": "blocked: try another network, or Wayback by hand",
    "timeout": "site timed out: retry later",
    "dns-unresolvable": "domain dead: find the current website (alternate domains)",
}


# WO-1054 rule 5: the government's own plain name, looked up once per
# `gov_id` and cached for the life of the process -- used only to filter
# List's candidates on a shared multi-government hub down to this
# government's own meetings (`pick.filter_candidates_to_government()`).
# `FinderInput` itself carries only `gov_id` (docs/MEETING_FINDER.md's
# "Input rows" table); `government_for_id()` derives the real name from
# the national tables the same way `identity.py`'s own resolver check
# already does for a different purpose. A `gov_id` with no registry row
# (or none given at all) just means the filter never fires -- see that
# function's own "ambiguous -> keep" default -- not an error.
#
# WO-1060: caches the whole `Government` row (not just the name) so the
# same lookup also answers `_gov_state_for_input()` -- the searched
# government's own state, used by `pick.describe_foreign_candidate()` to
# never record a lead that's just that government's own state name/code
# resurfacing (the real Galesburg, IL regression this WO fixes).
_GOV_CACHE: Dict[str, Optional[Government]] = {}


def _government_for_input(finder_input: FinderInput) -> Optional[Government]:
    gov_id = finder_input.gov_id
    if not gov_id:
        return None
    if gov_id in _GOV_CACHE:
        return _GOV_CACHE[gov_id]
    try:
        gov = government_for_id(gov_id)
    except Exception:  # noqa: BLE001
        gov = None
    _GOV_CACHE[gov_id] = gov
    return gov


def _gov_name_for_input(finder_input: FinderInput) -> Optional[str]:
    gov = _government_for_input(finder_input)
    return gov.gov_name if gov else None


def _gov_state_for_input(finder_input: FinderInput) -> Optional[str]:
    gov = _government_for_input(finder_input)
    return (gov.state or None) if gov else None


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
    # WO-1035 follow-up (conductor live check, 2026-09-23): a "kept
    # despite" (OUTCOME_VIDEO_LOW_CONFIDENCE) pick from ANY resolve call
    # in this government's walk, held here rather than ending the walk --
    # see `_try_resolve()`'s own comment for the real bug this fixes
    # (champaignil.gov: a 12s homepage banner .mp4 stopped the whole walk
    # before it ever reached the real Cablecast council-meeting account).
    # (rank, ResolveResult, ResolvedMeeting-or-None); only the best-ranked
    # one seen across the whole walk is kept (lower rank wins, first-found
    # breaks a tie -- same order resolve.py itself already applies within
    # one call). Used as the FINAL result only if nothing clean ever
    # resolves anywhere in the walk (see run_one()).
    low_confidence: Optional[tuple] = None
    # WO-1035 item 5: per-government "don't re-try the same thing" caches.
    # `listed_accounts` keys are (platform, normalized account url) --
    # List is never run twice for the same account across forks/hops
    # (real case: Des Plaines IL's ChampDS account, listed once per fork
    # before this). `tried_meeting_keys` holds `_meeting_key()` for every
    # candidate ever handed to `_try_resolve()`, so the same meeting
    # (however it was found) is never resolved twice.
    listed_accounts: Dict[Tuple[str, str], ListResult] = field(default_factory=dict)
    tried_meeting_keys: Set[str] = field(default_factory=set)
    # WO-1035 item 6: a failed Resolve call's own `ResolveResult.note`
    # (the real per-candidate reasons, e.g. "https://.../videos/399892:
    # reject_dead -- ...") used to be dropped on the floor here -- only
    # `result.outcome` (a short code like "no-meeting-nor-video") was kept
    # on `state.outcomes`, so a government where Resolve genuinely found
    # and rejected real candidates read identically to one where nothing
    # was ever found at all (the real bug behind the Greenburgh NY /
    # Upper Providence PA reports: "resolve found real videos but
    # returned nothing", traced to exactly this -- the detail was there,
    # just never surfaced). Collected here and folded into the final
    # VerdictRow.note (see run_one()) whenever the walk ends without a
    # clean success.
    resolve_notes: List[str] = field(default_factory=list)
    # WO-1058: every foreign-government lead any List call in this walk
    # turned up (`pick.describe_foreign_candidate()`'s shape, plus
    # `hub_host`) -- gathered here regardless of whether this government's
    # OWN walk ever finds a clean result, and folded into the final
    # `VerdictRow.other_gov_leads`.
    other_gov_leads: List[Dict[str, Any]] = field(default_factory=list)
    # WO-1076: adaptive-budget/second-pass configuration for this walk
    # (set once, from `run_one()`'s own params, before the phase loop
    # starts) plus the bookkeeping each feature needs to fire at most
    # once and to say so in the final VerdictRow.note (item 1/3: "log
    # when it's used").
    adaptive_budget_enabled: bool = True
    adaptive_max_fetches: int = _DEFAULT_ADAPTIVE_MAX_FETCHES
    adaptive_budget_used: bool = False
    second_pass_used: bool = False
    budget_notes: List[str] = field(default_factory=list)
    # WO-1076 item 2: consumed the first time the "one more hop" rescue
    # fires anywhere in this government's walk -- one extra hop total per
    # government, not per fork, so this stays a narrow rescue rather than
    # a second `max_hops`.
    bonus_hop_available: bool = True

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


def _maybe_raise_budget(fetcher: Fetcher, state: _WalkState, *, reason: str) -> None:
    """WO-1076 item 3 ("adaptive budget"): once real promising evidence
    turns up for this government, raise ITS OWN fetch budget instead of
    stopping at the ordinary default -- these are the governments where
    extra budget actually pays off (a meetings/agenda page, a recognized
    video-platform account, a meeting-without-video listing), not a
    blanket increase for every government. Only ever raises (never
    lowers) and only once per walk (`state.adaptive_budget_used`), so a
    government that keeps finding "promising" evidence doesn't keep
    getting new budget forever. Logged on `state.budget_notes` (folded
    into the final VerdictRow.note either way -- see `run_one()`) and
    counted for free in `VerdictRow.requests_total`, since that already
    wraps the whole `Fetcher` for the life of the walk
    (`pace_all_requests()`)."""
    if not state.adaptive_budget_enabled or state.adaptive_budget_used:
        return
    if fetcher.max_fetches >= state.adaptive_max_fetches:
        return
    fetcher.max_fetches = state.adaptive_max_fetches
    state.adaptive_budget_used = True
    state.budget_notes.append(
        f"adaptive budget: raised to {state.adaptive_max_fetches} fetches ({reason})"
    )


_CALENDAR_PATH_RE = re.compile(r"calendar\.aspx|/calendar/|/events?/", re.I)

# WO-1035 item 5 (Ryan's rule: "don't re-try the same thing"). A real
# meeting id, when the URL carries one -- CivicClerk/ChampDS's `event/<id>`,
# an `EventId=`/`eventID=` query param, Cablecast's `/show/<id>`, Swagit's
# `/views/<id>`/`/videos/<id>`, Granicus's `clip_id=`/`MediaID=`. Checked in
# order; the first match wins. Falls back to the normalized URL
# (`_norm_url()`, below) when nothing matches -- still "tried once", just
# keyed on the whole address rather than a parsed id.
_MEETING_ID_PATTERNS = (
    re.compile(r"/event/(\d+)", re.I),
    re.compile(r"[?&]eventid=(\d+)", re.I),
    re.compile(r"/show/(\d+)", re.I),
    re.compile(r"/views?/(\d+)", re.I),
    re.compile(r"/videos/(\d+)", re.I),
    re.compile(r"[?&]clip_?id=(\d+)", re.I),
    re.compile(r"[?&]mediaid=(\d+)", re.I),
    re.compile(r"[?&]meetingid=([0-9a-f-]+)", re.I),
)


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


async def _cached_list_account(
    platform: str,
    account_url: str,
    fetcher: Fetcher,
    state: _WalkState,
    *,
    page_url: Optional[str] = None,
    gov_name: Optional[str] = None,
    gov_state: Optional[str] = None,
) -> ListResult:
    """WO-1035 item 5: "accounts listed once" -- `_shallow_step()` runs on
    every fork AND every hop, and more than one of those can land on the
    same real account (Des Plaines IL's ChampDS account, listed once per
    fork before this fix -- cablecast3 report, 2026-09-23). Caches by
    (platform, normalized account url) for the life of one government's
    walk; a `BudgetExceeded` is never cached (it isn't a real answer).

    `page_url` (WO-1046): forwarded to `list_account()`, not part of the
    cache key -- it's decorative context for Vimeo's candidate
    `source_url` (see `listing.py`'s own docstring), not a different
    account, so the first page that reaches a given account "wins" that
    context for the life of this government's walk.

    `gov_name` (WO-1054 rule 5): also forwarded, also not part of the
    cache key -- constant for the whole life of one government's walk
    (one `FinderInput`), so every call for the same account already gets
    the same value."""
    key = (platform, _norm_url(account_url))
    cached = state.listed_accounts.get(key)
    if cached is not None:
        return cached
    result = await list_account(
        platform,
        account_url,
        fetcher,
        page_url=page_url,
        gov_name=gov_name,
        gov_state=gov_state,
    )
    state.listed_accounts[key] = result
    return result


def _meeting_key(url: str) -> str:
    """WO-1035 item 5: "each meeting is tried once (same platform meeting
    id = same meeting)". `platform + id` when the URL carries a
    recognizable one (see `_MEETING_ID_PATTERNS`), else `platform +
    normalized URL` -- either way, two different candidate rows that both
    point at the same real meeting collapse to the same key."""
    platform = detect_platform(url) or ""
    for pattern in _MEETING_ID_PATTERNS:
        m = pattern.search(url)
        if m:
            return f"{platform}:{m.group(1).lower()}"
    return f"{platform}:{_norm_url(url)}"


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


# WO-1058: a "keep at least one" foreign-gov lead (`Candidate.
# foreign_gov_hint`) is real evidence -- just not proven to be THIS
# government's meeting -- so it's ranked below every other "kept despite"
# fallback (see `_KEPT_DESPITE_*` in resolve.py): a genuine same-government
# low-confidence pick, if the walk finds one anywhere else, always wins.
_FOREIGN_GOV_LEAD_RANK = 1000

# WO-1058 (Ryan, 2026-09-25): unambiguous decorative-asset words -- no
# real meeting recording is ever titled with one of these, even a long
# one, so they're the only `NON_MEETING_SIGNS` that still veto a video at
# the 80+ minute "strong indicator" length (see `_handcheck_lead()`).
_STRONG_DURATION_VETO_SIGNS = frozenset(
    {"banner", "hero", "drone", "doodle", "welcome"}
)
_STRONG_DURATION_SECONDS = 80 * 60


def _handcheck_lead(
    title: Optional[str], duration_seconds: Optional[float]
) -> Tuple[str, Optional[str]]:
    """WO-1058 ("wider hand-check leads... go big, hand-check after the
    run"): `("yes"|"no", flag_note_or_None)` for one weak-lead row.

    Base rule (Ryan, 2026-09-25): "yes" unless the video runs under 60
    seconds or its title carries a `NON_MEETING_SIGNS` word (a banner,
    hero clip, drone flyover, training, webinar...) -- every video that is
    >= 10 minutes, carries a meeting word/date, or whose length simply
    isn't known, is a "yes" under this, so the rule is written as its own
    "no only when..." rather than listing every case that reads "yes".

    A later addition (Ryan, same day): >= 80 minutes is a STRONG meeting
    indicator on its own -- hand-checks found every direct file that long
    (6 of 6) was a real meeting, against three webinars/trainings all
    under 63 minutes. At that length this always reads "yes" (with a flag
    note, so a report can sort it first), EXCEPT for the handful of
    decorative-asset words (`_STRONG_DURATION_VETO_SIGNS`) no real meeting
    is ever titled with -- length never overrides those. This never turns
    a video into a clean same-government find on length alone; it only
    decides whether an already-weak lead is worth a human's time."""
    combined = title or ""
    non_meeting = has_non_meeting_sign(combined)
    if duration_seconds is not None and duration_seconds >= _STRONG_DURATION_SECONDS:
        if non_meeting in _STRONG_DURATION_VETO_SIGNS:
            return "no", None
        return "yes", "80+ min: strong meeting indicator"
    if non_meeting:
        return "no", None
    if duration_seconds is not None and duration_seconds < 60:
        return "no", None
    return "yes", None


async def _try_resolve(
    candidates: List[Candidate],
    finder_input: FinderInput,
    state: _WalkState,
    *,
    max_tries: int,
    fetcher: Optional[Fetcher] = None,
) -> bool:
    """Runs Resolve on `candidates`; on success, records the winner on
    `state` and returns True. On failure, records the outcome and
    returns False so the caller keeps looking (Scan/Hop, or the next
    fork).

    WO-1035 item 5: filters out any candidate whose `_meeting_key()` has
    already been offered to Resolve earlier in THIS government's walk
    (from an earlier fork/hop) before doing anything else -- "each
    meeting is tried once". If everything here has already been tried,
    this is a no-op (no fetch, no outcome recorded) rather than a wasted
    Resolve call."""
    fresh: List[Candidate] = []
    for cand in candidates:
        key = _meeting_key(cand.url)
        if key in state.tried_meeting_keys:
            continue
        state.tried_meeting_keys.add(key)
        fresh.append(cand)
    if not fresh:
        return False
    candidates = fresh

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
    # WO-1058: a candidate kept only as a "possibly another government's
    # meeting on a shared hub" lead (`listing._apply_gov_filter()`'s "keep
    # at least one") must never become THIS government's own clean find,
    # however cleanly it resolves -- it's real video, just not proven to
    # belong here. Force it into the same low-confidence "kept despite"
    # bucket every other fallback uses, ranked last (`_FOREIGN_GOV_LEAD_
    # RANK`) so a genuine same-government find, clean or low-confidence,
    # always wins over it.
    foreign_hint = getattr(result.candidate, "foreign_gov_hint", None)
    if foreign_hint and result.outcome is None:
        result = dataclasses.replace(
            result,
            outcome=OUTCOME_HUB_OTHER_GOVERNMENT,
            low_confidence_reason=foreign_hint,
            low_confidence_rank=_FOREIGN_GOV_LEAD_RANK,
        )
    if result.outcome is None:
        state.result = result
        state.meeting = meeting
        return True
    # WO-1035 follow-up (conductor live check, 2026-09-23): a "kept
    # despite" pick (OUTCOME_VIDEO_LOW_CONFIDENCE) is real evidence, but
    # NOT a clean success -- it must not end the walk (the original bug:
    # a 12s homepage banner .mp4 on champaignil.gov stopped the walk
    # before it ever reached the real Cablecast council-meeting account).
    # Stash it as a per-government fallback (best rank wins, first-found
    # breaks a tie) and keep walking every other fork/hop; `run_one()`
    # only reaches for it if nothing clean ever resolves anywhere.
    # WO-1046: OUTCOME_EMBED_RESTRICTED is the same "kept despite"
    # fallback shape as OUTCOME_VIDEO_LOW_CONFIDENCE (real evidence, not a
    # clean success) -- its own rank (`_KEPT_DESPITE_EMBED_RESTRICTED`,
    # negative) already sorts ahead of every video-low-confidence rank, so
    # sharing this one stash naturally prefers a confirmed-but-restricted
    # meeting over a merely-uncertain one found elsewhere in the walk.
    # WO-1058: `OUTCOME_HUB_OTHER_GOVERNMENT` joins this same stash for the
    # foreign-lead case just above.
    if result.outcome in (
        OUTCOME_VIDEO_LOW_CONFIDENCE,
        OUTCOME_EMBED_RESTRICTED,
        OUTCOME_HUB_OTHER_GOVERNMENT,
    ):
        rank = (
            result.low_confidence_rank if result.low_confidence_rank is not None else 99
        )
        if state.low_confidence is None or rank < state.low_confidence[0]:
            state.low_confidence = (rank, result, meeting)
    state.outcomes.append(result.outcome)
    if result.note:
        state.resolve_notes.append(result.note)
    # WO-1076 item 3: a meeting-without-video listing is exactly the
    # "promising evidence" this rule is for -- a real meeting body, just
    # no video yet found; give this government's own walk more room to
    # keep looking (item 2's own extra hop) rather than stopping at the
    # ordinary default.
    if fetcher is not None and result.outcome == OUTCOME_MEETING_WITHOUT_VIDEO:
        _maybe_raise_budget(fetcher, state, reason="meeting-without-video listing")
    return False


async def _shallow_step(
    url: str,
    fetcher: Fetcher,
    finder_input: FinderInput,
    state: _WalkState,
    *,
    seen: Set[str],
    max_tries: int,
    follow_video: bool = True,
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
    except SoftBudgetExceeded:
        # WO-1039 item 2: a RESERVED-budget stop during Pass 1, not real
        # exhaustion -- see `SoftBudgetExceeded`'s own docstring. Never
        # sets `state.budget_exhausted`, so Pass 2 (Scan/Hop) still gets
        # its turn with the reserved fetches once Pass 1 finishes.
        return None
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
        # WO-1076 item 3: a recognized video-platform account is real
        # promising evidence for this government -- give the rest of its
        # own walk more room before stopping at the ordinary budget.
        _maybe_raise_budget(fetcher, state, reason="recognized platform account")
        account_url = ident.account_url
        if ident.platform == "telvue":
            # WO-1038: `identify.py`'s generic account-url reduction
            # (`_account_base_url()`/`_account_url_for_platform()`, a file
            # this WO doesn't own) collapses ANY recognized-platform URL
            # to its bare `scheme://netloc/` -- for TelVue that throws
            # away the `/player/{org_token}/` path that's the ONLY thing
            # identifying which customer's channel this is (every real
            # TelVue customer shares the same `videoplayer.telvue.com`
            # host). `telvue.account_url_for()` recovers the real
            # per-token listing URL from whatever TelVue URL Identify
            # actually landed on (`ident.final_url`, falling back to the
            # input `url` for the rule-1 no-fetch case where `final_url`
            # is just the input url itself).
            account_url = telvue_account_url_for(ident.final_url or url) or account_url
        try:
            list_result = await _cached_list_account(
                ident.platform,
                account_url,
                fetcher,
                state,
                page_url=ident.final_url or url,
                gov_name=_gov_name_for_input(finder_input),
                gov_state=_gov_state_for_input(finder_input),
            )
        except SoftBudgetExceeded:
            # WO-1039 item 2: see the identical comment above.
            return None
        except BudgetExceeded:
            state.budget_exhausted = True
            return None
        state.reach("list")
        if list_result.outcome:
            state.outcomes.append(list_result.outcome)
        if list_result.foreign_leads:
            state.other_gov_leads.extend(list_result.foreign_leads)
        if list_result.candidates:
            if await _try_resolve(
                list_result.candidates,
                finder_input,
                state,
                max_tries=max_tries,
                fetcher=fetcher,
            ):
                return None  # resolved -- no deep pass needed for this fork

    # WO-1031: a platform with meetings but no video is often an agenda
    # system, with the video somewhere else linked from the same page.
    # Real case (Ryan's ground truth, 2026-09-23): Dublin, CA's
    # `/1604/Meetings-Agendas-Minutes-Video-on-Demand` led to Granicus
    # agendas with no playable video, while the same page links
    # `/2875/Watch-Meetings` -> Swagit. Follow up to 2 watch/video links
    # from this page (ranked with `prefer_video`) before giving up here.
    if (
        follow_video
        and not state.done
        and ident.page is not None
        and OUTCOME_MEETING_WITHOUT_VIDEO in state.outcomes
    ):
        followed = 0
        for hop in rank_hops(ident.page, prefer_video=True, limit=_HOP_CANDIDATE_LIMIT):
            if followed >= _VIDEO_FOLLOW_LIMIT or state.done:
                break
            if not _VIDEO_WORDS_RE.search(f"{hop.anchor} {hop.url}"):
                continue
            if is_youtube_host(urlparse(hop.url).hostname or ""):
                continue
            if _norm_url(hop.url) in seen:
                continue
            followed += 1
            state.hops += 1
            await _shallow_step(
                hop.url,
                fetcher,
                finder_input,
                state,
                seen=seen,
                max_tries=max_tries,
                follow_video=False,
            )

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
    # WO-1076 item 3: a real document/meeting hub (a document link, an
    # event permalink, or a known platform link anywhere on the page) is
    # promising evidence for this government too, even before Scan/Hop
    # finds anything specific on it -- give the rest of this walk more
    # room before stopping at the ordinary budget.
    if page is not None and is_document_hub(page):
        _maybe_raise_budget(fetcher, state, reason="meetings page")
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
                scan_result.media_candidates,
                finder_input,
                state,
                max_tries=max_tries,
                fetcher=fetcher,
            ):
                return

        # WO-1038 (Ryan's principle): a direct link to a known meeting/
        # video platform on THIS page is tried BEFORE Scan's own
        # `meeting_page_links` -- `rank_hops()` already scores such a
        # link above a generic nav/agenda/news page (see hop.py's
        # `_KNOWN_PLATFORM_BONUS`). Real governments this fixes: Yarmouth,
        # ME's "Meetings on Demand" TelVue link and Medina, SD's "Medina
        # TV" link were both Hop's own #1 pick but never visited, because
        # the old order let Scan exhaust its own meeting-page links
        # first. Only the single best-ranked platform link gets this
        # early try -- anything else still goes through the ordinary hop
        # loop below (or the meeting-page-links loop right after this).
        if not state.done and hops_left > 0:
            for hop in rank_hops(page, prefer_vendor=prefer_vendor, limit=3):
                if _norm_url(hop.url) in seen:
                    continue
                if is_youtube_host(urlparse(hop.url).hostname or ""):
                    continue
                if _meeting_key(hop.url) in state.tried_meeting_keys:
                    # WO-1046: Scan's own `_try_resolve()` call just above
                    # already tried this EXACT link (it's one of THIS
                    # page's media candidates -- a Vimeo/CivicWeb/
                    # Cablecast/direct-file embed Scan's narrower
                    # `_anchor_media_candidates()` already recognizes).
                    # Confirmed live on Suffolk County NY: without this,
                    # a Vimeo showcase link scored as a "known platform"
                    # hop got re-Identified/re-Listed as a bare account
                    # URL with NO page context, producing a worse,
                    # source-url-less duplicate of the SAME resolve Scan
                    # already did with the real page in hand -- and since
                    # `_try_resolve()`'s cross-fork "first found wins" tie-
                    # break ran on this WORSE duplicate first, it silently
                    # beat Scan's own better-contextualized attempt.
                    continue
                platform = detect_platform(hop.url)
                if (
                    not platform
                    or platform == "unknown"
                    or platform in _SOCIAL_LEAD_PLATFORMS
                ):
                    continue
                # Not pre-marked `seen` here (unlike the youtube-lead/
                # already-known-platform skip cases elsewhere in this
                # function) -- `_shallow_step()` itself marks a url seen
                # only once it actually visits it; pre-marking it here
                # would make `_shallow_step()`'s own `already seen` guard
                # bail out before ever calling `identify()`.
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
                break

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

        # WO-1035 item 7: a recognized video-vendor link within a small
        # margin of the top-ranked hop is followed FIRST -- `rank_hops()`
        # scores path/anchor vocabulary, not "is this actually a video
        # platform", so a near-tied vendor link is stronger evidence than
        # a marginally higher-scoring agenda/minutes page. Only reorders
        # when there IS a top hop to compare against and the vendor link
        # isn't already it.
        if hops:
            top_score = hops[0].score
            for idx, hop in enumerate(hops[1:], start=1):
                if top_score - hop.score > _VENDOR_TIE_MARGIN:
                    break  # hops are score-sorted; nothing further ties
                platform = detect_platform(hop.url)
                if platform and platform != "unknown":
                    hops.insert(0, hops.pop(idx))
                    break

        siblings_tried = 0
        for hop in hops:
            if _norm_url(hop.url) in seen:
                continue
            if _meeting_key(hop.url) in state.tried_meeting_keys:
                # WO-1046: same reasoning as the early-platform-link loop
                # above -- this exact link is one of THIS page's own media
                # candidates, and Scan's `_try_resolve()` call already
                # tried it (with the real page as context) before this
                # loop ever runs. Confirmed live on Suffolk County NY: a
                # Vimeo showcase Scan already resolved (embed-restricted)
                # got re-walked here as a plain "sibling hop" -- via
                # `_walk_from()`'s own Identify->List path, which has no
                # page to derive a real source/context from -- producing
                # a worse duplicate `state.low_confidence` entry that (on
                # a rank tie) won the "first found" race over Scan's own
                # better-contextualized one.
                seen.add(_norm_url(hop.url))
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
            siblings_tried += 1
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
            # WO-1035 item 7: if the best-ranked hop dead-ended (nothing
            # resolved, budget not exhausted), try the next sibling hop on
            # THIS page before giving up on it -- real governments this
            # fixes (Des Plaines IL, Niagara Falls SD NY, James Island SC,
            # Johnson County TX) had the real vendor link ranked 2nd-6th
            # behind an agenda/minutes page that scored higher but led
            # nowhere. Bounded by `_MAX_SIBLING_HOPS_PER_PAGE` and by
            # `hops_left` (each sibling still spends one hop of budget) so
            # this stays a safety net, not unbounded exploration.
            if state.done or siblings_tried >= _MAX_SIBLING_HOPS_PER_PAGE:
                break

    elif (
        not state.done
        and state.bonus_hop_available
        and page is not None
        and page.html
        and (is_document_hub(page) or OUTCOME_MEETING_WITHOUT_VIDEO in state.outcomes)
    ):
        # WO-1076 item 2 ("one more hop from a meetings page"): the
        # ordinary hop budget for this fork is spent (`hops_left <= 0`,
        # the `if` above didn't run), but the page in hand is itself a
        # real meetings/agenda hub (or this walk already found meetings
        # with no video) -- allow ONE extra hop, and only for a link whose
        # own anchor text or URL carries a broadcast/context word
        # (`_CONTEXT_HOP_WORDS_RE`; see the Lake Oswego, OR test case in
        # that constant's own comment). `state.bonus_hop_available` makes
        # this a one-time rescue for the whole government, not a second
        # `max_hops`; the nested `_walk_from()` call gets `hops_left=0` so
        # it can't chain into a second bonus hop of its own.
        for hop in rank_hops(page, prefer_video=True, limit=_HOP_CANDIDATE_LIMIT):
            if _norm_url(hop.url) in seen:
                continue
            if is_youtube_host(urlparse(hop.url).hostname or ""):
                continue
            if not _CONTEXT_HOP_WORDS_RE.search(f"{hop.anchor} {hop.url}"):
                continue
            state.bonus_hop_available = False
            state.hops += 1
            await _walk_from(
                hop.url,
                fetcher,
                finder_input,
                state,
                hops_left=0,
                seen=seen,
                max_tries=max_tries,
                prefer_vendor=prefer_vendor,
            )
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


# WO-1076 item 1: "no platform account, no meeting video" -- these two
# outcomes mean real, non-YouTube evidence was already found somewhere in
# the walk, so the second pass (a rescue specifically for the "YouTube is
# literally all there is" case) doesn't apply -- item 2's own "one more
# hop" already covers the meeting-without-video case, and a foreign-hub
# lead is real evidence of an account, just not this government's own.
_NON_YOUTUBE_EVIDENCE_OUTCOMES = frozenset(
    {OUTCOME_MEETING_WITHOUT_VIDEO, OUTCOME_HUB_OTHER_GOVERNMENT}
)


def _would_end_youtube_lead_only(state: _WalkState) -> bool:
    """True when this government's walk, as it stands after Pass 1/2,
    would settle for `OUTCOME_YOUTUBE_LEAD_ONLY`: nothing clean resolved,
    no "kept despite" fallback either, no other real evidence recorded,
    and at least one YouTube lead was found along the way (the same check
    `run_one()` itself makes at the very end to decide whether to append
    that outcome -- see its own final `else` branch)."""
    if state.result is not None or state.low_confidence is not None:
        return False
    if not any(lead.get("kind") == "youtube" for lead in state.leads):
        return False
    return not any(o in _NON_YOUTUBE_EVIDENCE_OUTCOMES for o in state.outcomes)


async def _second_pass_for_youtube_only(
    pending_deep: List[Tuple[str, IdentifyResult, int]],
    fetcher: Fetcher,
    finder_input: FinderInput,
    state: _WalkState,
    *,
    seen: Set[str],
    max_tries: int,
    extra_fetches: int,
) -> None:
    """WO-1076 item 1: before settling for `OUTCOME_YOUTUBE_LEAD_ONLY`,
    spend `extra_fetches` more on a focused pass across every fork's own
    already-fetched page (`pending_deep`, from Pass 1 above), following
    only its highest-value site-nav links -- restricted to
    `_SECOND_PASS_NAV_WORDS_RE`'s vocabulary (Meetings / Agendas & Minutes
    / Government / Council / Board / Watch / Video / Media / TV).
    `rank_hops()` itself already scores this vocabulary highly (its own
    nav-hub/video-hub label bonuses); this only narrows which of its
    ranked hops get followed, so the pass stays a small, targeted rescue
    rather than a second full breadth pass. The YouTube leads already
    found are kept on `state.leads` regardless -- this only ever REPLACES
    the final outcome if a real, non-YouTube find turns up."""
    if state.done or not pending_deep:
        return
    fetcher.max_fetches += extra_fetches
    state.second_pass_used = True
    state.budget_notes.append(
        f"second pass: youtube-lead-only rescue, +{extra_fetches} fetches"
    )
    for _point, ident, _hops_budget in pending_deep:
        if state.done:
            break
        page = ident.page
        if page is None or not page.html:
            continue
        followed = 0
        for hop in rank_hops(page, limit=_HOP_CANDIDATE_LIMIT):
            if state.done or followed >= _SECOND_PASS_LINKS_PER_PAGE:
                break
            if _norm_url(hop.url) in seen:
                continue
            if is_youtube_host(urlparse(hop.url).hostname or ""):
                continue
            if not _SECOND_PASS_NAV_WORDS_RE.search(f"{hop.anchor} {hop.url}"):
                continue
            followed += 1
            state.hops += 1
            await _walk_from(
                hop.url,
                fetcher,
                finder_input,
                state,
                hops_left=_SECOND_PASS_HOPS,
                seen=seen,
                max_tries=max_tries,
            )


async def _run_phase_loop(
    finder_input: FinderInput,
    fetcher: Fetcher,
    *,
    max_tries: int,
    max_hops: int,
    max_forks: int,
    state: Optional[_WalkState] = None,
    second_pass_extra_fetches: int = _DEFAULT_SECOND_PASS_EXTRA_FETCHES,
) -> _WalkState:
    # WO-1038 addendum: a caller (`run_one()`, for `_run_one_with_timeout()`'s
    # benefit) may hand in an already-created `_WalkState` it kept a
    # reference to, so it can still read `state.path`/`state.phase_reached()`
    # after abandoning a government that hit the wall-clock cap -- see that
    # function's own docstring. Every existing caller passes nothing and
    # gets today's fresh-state behavior, unchanged.
    state = state if state is not None else _WalkState()
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
        if list_result.foreign_leads:
            state.other_gov_leads.extend(list_result.foreign_leads)
        if list_result.candidates:
            await _try_resolve(
                list_result.candidates,
                finder_input,
                state,
                max_tries=max_tries,
                fetcher=fetcher,
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
                    fetcher=fetcher,
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
    #
    # WO-1039 item 2: a few fetches are held in reserve for Pass 2 for the
    # DURATION of this whole pass (see `_PASS1_BUDGET_RESERVE`'s own
    # comment) -- released again right before Pass 2 starts, so Pass 2
    # gets the full remaining budget, reserve included. Skipped for a
    # small `max_fetches` (an explicit small budget, e.g. a test, should
    # behave exactly as it always has -- reserving fetches out of an
    # already-tiny budget would only ever hurt, never help).
    reserve = (
        _PASS1_BUDGET_RESERVE if fetcher.max_fetches > 2 * _PASS1_BUDGET_RESERVE else 0
    )
    if reserve:
        fetcher.reserve(reserve)
    forks_tried = 0
    pending_deep: List[tuple[str, IdentifyResult, int]] = []
    try:
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
    finally:
        if reserve:
            fetcher.release_reserve()

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

    # Pass 3 (WO-1076 item 1): a focused, budget-extended rescue, but only
    # when the walk would otherwise settle for OUTCOME_YOUTUBE_LEAD_ONLY --
    # see `_would_end_youtube_lead_only()`'s own docstring.
    if (
        not state.done
        and second_pass_extra_fetches > 0
        and _would_end_youtube_lead_only(state)
    ):
        await _second_pass_for_youtube_only(
            pending_deep,
            fetcher,
            finder_input,
            state,
            seen=seen,
            max_tries=max_tries,
            extra_fetches=second_pass_extra_fetches,
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
    second_pass_extra_fetches: int = _DEFAULT_SECOND_PASS_EXTRA_FETCHES,
    adaptive_max_fetches: int = _DEFAULT_ADAPTIVE_MAX_FETCHES,
    progress: Optional[Dict[str, Any]] = None,
) -> VerdictRow:
    """Runs the whole pipe for one input and returns its `VerdictRow`.
    Never raises for an ordinary resolve/access failure -- those come
    back as a named outcome; a genuinely unexpected exception is left to
    propagate, since Verdict should never silently swallow a real bug.

    `progress`, when given (only `_run_one_with_timeout()` passes one),
    is a plain shared dict this function populates with its own live
    `state`/`fetcher` objects as soon as they exist -- so a caller that
    gives up WAITING for this coroutine (the wall-clock cap) can still
    read `state.path`/`fetcher.fetches_used` for a best-effort report,
    even though the coroutine itself is never awaited to completion."""
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
            meeting_url=result.candidate.url if result.candidate else None,
            meeting_title=result.candidate.title if result.candidate else None,
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
            low_confidence_reason=result.low_confidence_reason or "",
            audio_only=result.audio_only,
            finished_at=_now_iso(),
        )

    fetcher = Fetcher(max_fetches=max_fetches)
    walk_state = _WalkState(
        # WO-1076 item 3: `adaptive_max_fetches <= max_fetches` disables
        # the feature outright (there's nothing left to raise TO) --
        # `_maybe_raise_budget()`'s own `>=` check already no-ops in that
        # case, this just avoids logging a "raise" that doesn't happen.
        adaptive_budget_enabled=adaptive_max_fetches > max_fetches,
        adaptive_max_fetches=adaptive_max_fetches,
    )
    if progress is not None:
        progress["state"] = walk_state
        progress["fetcher"] = fetcher
    try:
        # WO-1032/1031: pace and count EVERY request this government's walk
        # makes, adapters' own sessions included (Dublin made 55 requests
        # against a 12-fetch budget before this).
        with pace_all_requests(fetcher) as request_stats:
            state = await _run_phase_loop(
                finder_input,
                fetcher,
                max_tries=max_tries,
                max_hops=max_hops,
                max_forks=max_forks,
                state=walk_state,
                second_pass_extra_fetches=second_pass_extra_fetches,
            )
    finally:
        await fetcher.aclose()

    result = state.result

    # WO-1035 follow-up (conductor live check, 2026-09-23): only reach for
    # the per-government low-confidence fallback once nothing clean ever
    # resolved anywhere in the walk -- a clean `state.result` always wins.
    low_confidence_meeting = None
    if result is None and state.low_confidence is not None:
        _rank, lc_result, lc_meeting = state.low_confidence
        low_confidence_meeting = lc_meeting
    else:
        lc_result = None

    identity = check_identity(
        state.meeting if result is not None else low_confidence_meeting, finder_input
    )

    low_confidence_reason = ""
    audio_only = False
    handcheck_lead = ""
    meeting_url: Optional[str] = None
    meeting_title: Optional[str] = None
    if result is not None:
        outcome = None
        result_url = result.video_url
        platform = result.platform
        tier = result.tier
        duration_seconds = result.duration_seconds
        note = result.note
        audio_only = result.audio_only
        if result.candidate is not None:
            meeting_url = result.candidate.url
            meeting_title = result.candidate.title
        if result.tier == 2 and result.candidate is not None:
            state.leads.append({"kind": "youtube", "url": result.candidate.url})
    elif lc_result is not None:
        # A real video was found somewhere in the walk, but every one of
        # them was a "keep at least one" fallback (a rejected title, a
        # too-short probe, an unmeasurable length, or -- WO-1046 -- a
        # confirmed meeting Vimeo refuses to serve outside the
        # government's own site) -- report it as whatever specific
        # outcome resolve.py already decided (never as a clean find, so
        # it is never confused with a real tier-1/tier-3 success
        # downstream). Falls back to OUTCOME_VIDEO_LOW_CONFIDENCE only if
        # `lc_result.outcome` is somehow unset, which shouldn't happen --
        # resolve.py's own kept-despite loop always sets one.
        outcome = lc_result.outcome or OUTCOME_VIDEO_LOW_CONFIDENCE
        result_url = lc_result.video_url
        platform = lc_result.platform
        tier = lc_result.tier
        duration_seconds = lc_result.duration_seconds
        note = lc_result.note or "kept despite: low confidence"
        low_confidence_reason = lc_result.low_confidence_reason or ""
        if lc_result.candidate is not None:
            if outcome == OUTCOME_EMBED_RESTRICTED:
                # WO-1046 (Ryan): the video itself can't play here --
                # point the verdict at the government's own page that
                # embeds it (where the video DOES play), not the Vimeo
                # video URL, so "link out" in the try_next message above
                # actually leads somewhere useful.
                meeting_url = lc_result.candidate.source_url or lc_result.candidate.url
            else:
                meeting_url = lc_result.candidate.url
            meeting_title = lc_result.candidate.title
        # WO-1058 item 3: every weak-lead row gets a hand-check verdict --
        # see `_handcheck_lead()`'s own docstring for the rule.
        lead_flag, lead_note = _handcheck_lead(meeting_title, duration_seconds)
        handcheck_lead = lead_flag
        if lead_note:
            low_confidence_reason = (
                f"{low_confidence_reason}; {lead_note}"
                if low_confidence_reason
                else lead_note
            )
    else:
        if any(lead.get("kind") == "youtube" for lead in state.leads):
            state.outcomes.append(OUTCOME_YOUTUBE_LEAD_ONLY)
        outcome = _pick_outcome(state.outcomes)
        result_url = None
        platform = None
        tier = None
        duration_seconds = None
        # WO-1035 item 6: surface Resolve's own per-candidate detail (real
        # videos it actually looked at and why each was rejected), not
        # just the short outcome code -- see `_WalkState.resolve_notes`'s
        # own comment for the real Greenburgh NY / Upper Providence PA
        # reports this fixes.
        note_parts = list(dict.fromkeys(state.outcomes)) + list(
            dict.fromkeys(state.resolve_notes)
        )
        note = "; ".join(note_parts) or (
            "budget exhausted before anything resolved"
            if state.budget_exhausted
            else "nothing found"
        )

    # WO-1076 items 1/3: "log when it's used" -- append regardless of
    # which branch above produced `note`, a clean find included (the
    # adaptive budget can fire on the same walk that then finds a real
    # video off the extra fetches it bought).
    if state.budget_notes:
        note = (
            f"{note}; {'; '.join(state.budget_notes)}"
            if note
            else "; ".join(state.budget_notes)
        )

    return VerdictRow(
        run_id=run_id,
        input_url=finder_input.url,
        entry_phase=finder_input.entry,
        path=state.path,
        phase_reached=state.phase_reached,
        result_url=result_url,
        meeting_url=meeting_url,
        meeting_title=meeting_title,
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
        requests_total=request_stats.requests_total,
        note=note,
        low_confidence_reason=low_confidence_reason,
        audio_only=audio_only,
        handcheck_lead=handcheck_lead,
        other_gov_leads=state.other_gov_leads,
        try_next=_try_next(outcome, state.budget_exhausted),
        finished_at=_now_iso(),
    )


def _timeout_verdict_row(
    finder_input: FinderInput,
    run_id: str,
    progress: Dict[str, Any],
    gov_timeout_minutes: float,
) -> VerdictRow:
    state = progress.get("state")
    fetcher = progress.get("fetcher")
    path = list(state.path) if state is not None else [finder_input.url]
    phase_reached = state.phase_reached if state is not None else ""
    fetches = fetcher.fetches_used if fetcher is not None else 0
    minutes_text = (
        f"{gov_timeout_minutes:g}"
        if gov_timeout_minutes == int(gov_timeout_minutes)
        else f"{gov_timeout_minutes:.1f}"
    )
    return VerdictRow(
        run_id=run_id,
        input_url=finder_input.url,
        entry_phase=finder_input.entry,
        path=path,
        phase_reached=phase_reached,
        outcome=OUTCOME_INTERNAL_TIMEOUT,
        identity_expected_gov_id=finder_input.gov_id,
        fetches=fetches,
        other_gov_leads=list(state.other_gov_leads) if state is not None else [],
        note=(
            f"internal-timeout: this government's walk was still running past "
            f"{minutes_text} minute(s) wall-clock and was abandoned (not "
            f"cancelled cleanly -- see `_run_one_with_timeout()`'s docstring) "
            f"so the rest of the batch could finish"
        ),
        try_next=f"took over {minutes_text} minutes: rerun alone later",
        finished_at=_now_iso(),
    )


async def _run_one_with_timeout(
    finder_input: FinderInput,
    *,
    run_id: str,
    max_tries: int,
    max_hops: int,
    max_forks: int,
    max_fetches: int,
    gov_timeout_minutes: float,
    second_pass_extra_fetches: int = _DEFAULT_SECOND_PASS_EXTRA_FETCHES,
    adaptive_max_fetches: int = _DEFAULT_ADAPTIVE_MAX_FETCHES,
) -> VerdictRow:
    """Runs `run_one()` under a hard wall-clock cap per government (Ryan,
    2026-09-23 -- see `DEFAULT_GOV_TIMEOUT_MINUTES`'s own comment for the
    real incident this addresses: two real governments hung 30+ minutes
    in a batch run, inside a SYNCHRONOUS call (`fetch.py`'s headless-
    browser helper, dispatched via `asyncio.to_thread()`) that this WO
    doesn't own and can't fix at the source.

    Deliberately built on `asyncio.wait({task}, timeout=...)`, NOT
    `asyncio.wait_for()`. `wait_for()`'s own timeout path calls
    `task.cancel()` and then `await`s the task again to let the
    cancellation land before raising -- which can itself block past the
    deadline if whatever is running inside the task can't honor (or
    somewhere swallows) the resulting `CancelledError`, exactly the
    failure mode already confirmed live. `asyncio.wait(timeout=...)`
    carries no such obligation: it returns the instant the deadline
    passes, full stop, whether or not the task the caller stopped waiting
    for ever actually finishes. This function still calls `task.cancel()`
    as a courtesy (it usually does let a merely-slow task unwind and
    release whatever it's holding -- e.g. `_Lanes.resolve_slots` -- a
    moment later), but never waits around to find out; a done-callback
    just logs anything the abandoned task eventually raises, so asyncio
    never complains about an unretrieved exception.

    The abandoned task keeps running in the background with its own
    private `Fetcher`/session -- harmless to every OTHER government's
    walk (CLAUDE.md's "query politely" pacing is per-HOST, not per-task),
    though see this function's own report if it ever needs tightening
    (a resolve slot the abandoned task was holding stays held until/unless
    its own cancellation actually lands)."""
    progress: Dict[str, Any] = {}
    task: asyncio.Task = asyncio.ensure_future(
        run_one(
            finder_input,
            run_id=run_id,
            max_tries=max_tries,
            max_hops=max_hops,
            max_forks=max_forks,
            max_fetches=max_fetches,
            second_pass_extra_fetches=second_pass_extra_fetches,
            adaptive_max_fetches=adaptive_max_fetches,
            progress=progress,
        )
    )
    deadline_seconds = max(0.0, gov_timeout_minutes * 60)
    done, _pending = await asyncio.wait({task}, timeout=deadline_seconds)
    if task in done:
        return task.result()

    logger.warning(
        "meeting_finder: %s exceeded the %.1f minute internal timeout -- "
        "abandoning its walk and moving on",
        finder_input.url,
        gov_timeout_minutes,
    )
    task.cancel()

    def _log_abandoned_task_outcome(t: "asyncio.Task") -> None:
        if t.cancelled():
            return
        exc = t.exception()
        if exc is not None:
            logger.warning(
                "meeting_finder: abandoned (internal-timeout) task for %s "
                "later raised %s: %s",
                finder_input.url,
                type(exc).__name__,
                exc,
            )

    task.add_done_callback(_log_abandoned_task_outcome)
    return _timeout_verdict_row(finder_input, run_id, progress, gov_timeout_minutes)


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
    gov_timeout_minutes: float = DEFAULT_GOV_TIMEOUT_MINUTES,
    second_pass_extra_fetches: int = _DEFAULT_SECOND_PASS_EXTRA_FETCHES,
    adaptive_max_fetches: int = _DEFAULT_ADAPTIVE_MAX_FETCHES,
) -> List[VerdictRow]:
    """Drive every input in `inputs`, appending a `VerdictRow` to
    `out_path` (+ its JSONL twin) as each one finishes so a rerun resumes
    (`load_done()` skips an `input_url` already in `out_path`).

    `concurrency=1` (the default) runs one input at a time -- CLAUDE.md's
    "we query sites politely" rule; a `--concurrency` above 1 is a
    deliberate opt-in the CLI exposes. Each input gets its own `Fetcher`
    (own `max_fetches` budget), but `fetch.py`'s own process-wide
    per-host pacer (WO-1030) still spaces out two concurrent governments
    that share a vendor host.

    `gov_timeout_minutes` (default `DEFAULT_GOV_TIMEOUT_MINUTES`) is the
    hard wall-clock cap per government -- see `_run_one_with_timeout()`'s
    own docstring for why this exists and how it can give up waiting on a
    government without needing its walk to actually stop."""
    run_id = run_id or uuid.uuid4().hex[:12]
    done = load_done(out_path)
    todo = [i for i in inputs if i.url not in done]

    rows: List[VerdictRow] = []

    async def _run(finder_input: FinderInput) -> None:
        try:
            row = await _run_one_with_timeout(
                finder_input,
                run_id=run_id,
                max_tries=max_tries,
                max_hops=max_hops,
                max_forks=max_forks,
                max_fetches=max_fetches,
                gov_timeout_minutes=gov_timeout_minutes,
                second_pass_extra_fetches=second_pass_extra_fetches,
                adaptive_max_fetches=adaptive_max_fetches,
            )
        except Exception as exc:  # noqa: BLE001
            # WO-1034: a government must never vanish from the results.
            # Calibration run A (2026-09-23) lost 34 of 200 rows to one
            # unhandled error (Brotli-encoded responses). Record it as a
            # named outcome with the error text, so it's counted and
            # revisited, and keep going.
            row = VerdictRow(
                run_id=run_id,
                input_url=finder_input.url,
                entry_phase=finder_input.entry,
                outcome=OUTCOME_ERROR,
                identity_expected_gov_id=finder_input.gov_id,
                note=f"{type(exc).__name__}: {exc}"[:500],
                try_next=_TRY_NEXT[OUTCOME_ERROR],
                finished_at=_now_iso(),
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
