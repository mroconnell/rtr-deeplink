"""Shared data shapes for Meeting Finder (WO-1024). Frozen dataclasses,
not pydantic models like `app/platforms/models.py`'s `ResolvedMeeting` --
these are Meeting Finder's own internal contract between phases, not
something an adapter returns or the Archive ingests, and every wave-2
phase (List, Identify, Scan, Hop, Start) builds on exactly these shapes,
so they're kept small, typed and stable rather than pulled in from
elsewhere.

Named outcomes reuse the spellings already in use across this repo and
in rtr-business `research/ENUMERATION_METHODS.md` section 23 (read
2026-09-23 for this WO) -- see `OUTCOME_*` below for the source of each
one, and don't invent a new spelling for something that already has one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# --- Named outcomes -----------------------------------------------------
# Every value below is either already written by another script in this
# repo (see the citation on each) or, for the two Meeting Finder adds,
# used nowhere else, so no collision is possible.

# Content reasons, ENUMERATION_METHODS.md section 23 / scripts/coverage_alternates.py
OUTCOME_MEETING_WITHOUT_VIDEO = "meeting-without-video"
OUTCOME_NO_MEETING_NOR_VIDEO = "no-meeting-nor-video"
OUTCOME_OFF_MISSION = "off-mission"
OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER = "unsupported-platform-no-adapter"

# Access reasons, same source
OUTCOME_DNS_UNRESOLVABLE = "dns-unresolvable"
OUTCOME_CLOUDFLARE_CHALLENGE_BLOCKED = "cloudflare-challenge-blocked"
OUTCOME_BLOCKED_PLAIN_HTTP = "blocked-plain-http"
OUTCOME_BLOCKED_BROWSER_HEADERS = "blocked-browser-headers"
OUTCOME_TIMEOUT = "timeout"

# Meeting Finder's own, per docs/MEETING_FINDER.md's Identify/Follow-ups
# sections -- new spellings, not reused from elsewhere, since neither
# situation had a name before this WO.
OUTCOME_ACCOUNT_NOT_FOUND = "account-not-found"
# Nothing resolved, but a YouTube channel or video tied to this government
# was found along the way (WO-1031, 2026-09-23). A real find -- video very
# likely exists -- routed to the drip as a lead, since this Mac never
# fetches YouTube. First seen on Essex, ON (`youtube.com/user/EssexOntario`),
# which Verdict had reported as a bare access block.
OUTCOME_YOUTUBE_LEAD_ONLY = "youtube-lead-only"
# WO-1034: an unexpected exception while walking one government. Written
# as a row (with the error in `note`) so no government ever goes missing.
OUTCOME_ERROR = "error"
# WO-1035 (Ryan's rule, 2026-09-23): a video the video-quality gate would
# have rejected outright (promo/hero/test title), a probed video below
# the meeting-plausibility floor, or a video whose length couldn't be
# measured at all -- kept as a last-resort FIND (not a failure: `outcome`
# on the winning `ResolveResult` stays `None`, same as any other real
# find) rather than reporting `no-meeting-nor-video` while a real video
# sits right there. `ResolveResult.low_confidence_reason` names which
# rule it was kept despite; this constant exists only so a report can
# count how often that fallback fired, separately from a clean find.
OUTCOME_VIDEO_LOW_CONFIDENCE = "video-low-confidence"
# An entry point wave 2 hasn't built yet (List, Identify, Scan, Hop,
# Start) was asked for. Never a real finding -- a placeholder so the CLI
# accepts every `--entry` value from day one and wave 2 can fill each
# one in without changing the Verdict schema.
OUTCOME_PHASE_NOT_BUILT = "phase-not-built"

# All valid entry points, in pipe order (docs/MEETING_FINDER.md "The
# phases"). Only "resolve" is implemented by WO-1024; the rest return
# OUTCOME_PHASE_NOT_BUILT.
ENTRY_PHASES = ("start", "identify", "list", "scan", "resolve")


@dataclass(frozen=True)
class FinderInput:
    """One row of Meeting Finder input -- see docs/MEETING_FINDER.md's
    "Input rows" table for the field meanings."""

    url: str
    gov_id: Optional[str] = None
    platform_hint: Optional[str] = None
    # "own-site" | "guessed" | "directory" -- see the design doc's Pin/
    # audit section: identity only carries over along a path that started
    # on the government's own site.
    url_source: Optional[str] = None
    mode: str = "pin"  # "pin" | "audit"
    entry: str = "start"  # one of ENTRY_PHASES

    def __post_init__(self) -> None:
        if self.mode not in ("pin", "audit"):
            raise ValueError(
                f"FinderInput.mode must be 'pin' or 'audit', got {self.mode!r}"
            )
        if self.entry not in ENTRY_PHASES:
            raise ValueError(
                f"FinderInput.entry must be one of {ENTRY_PHASES}, got {self.entry!r}"
            )


@dataclass(frozen=True)
class Candidate:
    """One candidate meeting URL, from List, Scan, or a bare input.

    `lister` names which of docs/MEETING_FINDER.md's List (a-d) or Scan
    strategies produced this candidate, e.g. `discovery:civicclerk`,
    `resolve_seed:granicus_rss`, `adapter_list` (a `CalendarPageError`
    listing), `generic`, `media_scan`. `source_phase` is the coarser
    phase name Verdict groups by."""

    url: str
    title: Optional[str] = None
    date: Optional[str] = None  # ISO string, e.g. "2026-09-08"
    platform: Optional[str] = None
    source_phase: str = "input"  # "list" | "scan" | "input"
    lister: Optional[str] = None
    source_url: Optional[str] = None
    has_video_hint: Optional[bool] = None

    def __post_init__(self) -> None:
        if self.source_phase not in ("list", "scan", "input"):
            raise ValueError(
                "Candidate.source_phase must be 'list', 'scan' or 'input', "
                f"got {self.source_phase!r}"
            )


@dataclass(frozen=True)
class ResolveResult:
    """The outcome of running Resolve on one `FinderInput`/candidate set.

    `tier` is 1 (real captions), 2 (a YouTube lead, never fetched -- see
    resolve.py's own docstring for why), 3 (video, no captions, probed),
    or None (nothing resolved). `outcome` is one of the `OUTCOME_*`
    constants above, or None when `candidate` carries a real result."""

    candidate: Optional[Candidate]
    tier: Optional[int]
    platform: Optional[str]
    video_url: Optional[str]
    has_segments: bool
    duration_seconds: Optional[float]
    outcome: Optional[str]
    note: str = ""
    # WO-1035: set on a "keep at least one" fallback pick (see
    # OUTCOME_VIDEO_LOW_CONFIDENCE above) -- plain words naming the rule
    # this candidate failed ("video gate rejected it (promo_title: ...)",
    # "too short (42s, floor is 60s)", "video length couldn't be
    # measured (...)"). `None` for a clean find.
    low_confidence_reason: Optional[str] = None
    # WO-1035 item 3: a resolved video that failed the audio-only check is
    # no longer a reject -- it's a real find, just labelled. `False` for
    # an ordinary video (or when `video_url` is None).
    audio_only: bool = False


@dataclass(frozen=True)
class IdentityCheck:
    """docs/MEETING_FINDER.md's Verdict "Identity" field, structured.

    `verdict` is "agrees" (pin mode: the meeting's own government matches
    `gov_id`; audit mode: the resolver, pin switched off, lands on the
    same government the pin names), "disagrees" (names a different real
    government -- see `points_to`), "silent" (the resolver ends at a
    blank/unknown tier -- the page says nothing usable), or "not-checked"
    (no `gov_id`/no meeting to check against)."""

    mode: str  # "pin" | "audit"
    expected_gov_id: Optional[str]
    resolved_gov_id: Optional[str]
    resolved_tier: Optional[str]
    verdict: str  # "agrees" | "disagrees" | "silent" | "not-checked"
    points_to: Optional[str] = None


@dataclass(frozen=True)
class VerdictRow:
    """One read-only result row, written by verdict.py as each input
    finishes. Every field from docs/MEETING_FINDER.md's Verdict table,
    plus run bookkeeping."""

    run_id: str
    input_url: str
    entry_phase: str
    path: List[str] = field(default_factory=list)
    phase_reached: str = "resolve"
    result_url: Optional[str] = None
    platform: Optional[str] = None
    tier: Optional[int] = None
    duration_seconds: Optional[float] = None
    outcome: Optional[str] = None
    identity_verdict: Optional[str] = None
    identity_expected_gov_id: Optional[str] = None
    identity_resolved_gov_id: Optional[str] = None
    identity_points_to: Optional[str] = None
    leads: List[Dict[str, Any]] = field(default_factory=list)
    hops: int = 0
    forks: int = 0
    fetches: int = 0
    # WO-1031: every HTTP request the walk made, adapters' own included
    # (pacing.py's RequestStats). `fetches` counts only the 12-fetch budget.
    requests_total: int = 0
    note: str = ""
    # WO-1031 (Ryan, 2026-09-23): every failure says what to try next, so
    # misses are easy to revisit. Empty when something resolved.
    try_next: str = ""
    # WO-1035: mirrors ResolveResult's own fields of the same name (see
    # OUTCOME_VIDEO_LOW_CONFIDENCE above) -- carried into the Verdict row
    # so a report can count "kept despite"/"audio only" finds separately
    # from a clean one without re-reading the JSONL's nested detail.
    low_confidence_reason: str = ""
    audio_only: bool = False
    finished_at: str = ""
