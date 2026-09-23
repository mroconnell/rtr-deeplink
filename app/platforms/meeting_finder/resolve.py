"""Resolve (WO-1024): turn candidates into the first real meeting.

docs/MEETING_FINDER.md's Resolve section: one picking rule, run the real
adapter on each candidate in order, tier 1 (real captions) wins
immediately, tier 3 (video, no captions) is probed and the best one kept,
and a listing page found mid-resolve widens the search rather than
failing it.

**Reuse, not a third implementation (conductor course correction,
2026-09-23, after two rounds -- see git history for the discarded first
draft that wrapped `passive_verify.verify_hub()` as a black box).**
`app/platforms/passive_verify.py` (WO-333/355/933) already solves a
related but DIFFERENT problem: walking an unconfirmed HUB/listing URL
down to a real meeting (its own fetch, its own one-hop search, its own
platform-link ranking, no duration probe, no identity check). That's
List/Scan's job (wave 2), not Resolve's -- docs/MEETING_FINDER.md's own
entry-point table says Resolve's input is "One meeting URL"
(`antiochca.portal.civicclerk.com/event/18/media`), already a specific
candidate, not a hub to walk. So Resolve does NOT call `verify_hub()`.
What it DOES reuse from the same codebase, because re-deriving any of
these would be a real behavior fork:

- **The meeting-video gate** (`app/utils/video_hand_check.py`'s
  `assess_video_candidate()`): after a candidate resolves with a
  `video_url`, this catches what `pick.py`'s pre-fetch title filter
  can't (a decorative address, a promo/interview title,
  channel-derived "Kind A/B" phrases) -- `structured=True`, since every
  candidate reaching this point already came through `pick.py`'s "real
  per-meeting listing row" filter, same convention
  `_walk_candidates()`'s own found-video branch uses for the identical
  reason.
- **The audio-only check** (`passive_verify._confirm_not_audio_only()`):
  a real, confirmed, live failure mode (WO-347/348, e.g. a CivicClerk
  tenant whose "video" is a `.mp3`) -- one HEAD request, never a
  download. Imported directly (a private helper, but pure and
  side-effect-free) rather than copied, so a future fix to it reaches
  Resolve too.
- **The YouTube guard**: `resolve_via_platform(url, allow_youtube=False)`
  already wraps the call in `app/platforms/base.py`'s
  `youtube_resolve_guard()` -- the exact function `passive_verify.py`
  itself aliases as `_youtube_resolve_guard` for the same reason. No
  second import needed; same guard, same effect.

**What Resolve adds that neither `pick.py` nor `passive_verify.py`
has**: the tier-3 duration probe (`app/platforms/queue_probe.py`'s
`probe_queue_entry()` + `select_best_probe_result()` -- confirmed by
reading `passive_verify.py` end to end: no `queue_probe` import anywhere
in it).

**One picking rule (the conductor's other ask, decided here):** `pick.py`
-- moved from `scripts/wo134_confirmed_hits_ingest.py` this same WO,
extended with the test/demo/minutes/governing-body improvements. Applied
here as the one re-ordering/filtering step ON TOP of whatever order a
`Candidate` list arrives in, regardless of which lister produced it
(wave 2's List phase may feed candidates from `passive_verify`'s own
walker registry, from `resolve_seed()`'s readers, or from an adapter's
own `CalendarPageError` -- some of those already sort newest-first
themselves, e.g. CivicClerk's `hasMedia`-first ordering; `pick.py`'s
date-then-title-then-governing-body rule is applied uniformly regardless,
so Resolve always behaves the same way no matter which List strategy
handed it the list). `passive_verify.py`'s own walkers keep their
existing (different, no pre-fetch title filter) ordering for their own
callers -- unify only if a later wave finds a real reason to.
"""

from __future__ import annotations

import asyncio
from typing import List, Optional, Sequence, Tuple

from app.platforms import queue_probe
from app.platforms.base import (
    CalendarPageError,
    NoVideoCandidateFound,
    ResolveError,
    UnsupportedPlatformError,
    YouTubeResolveBlocked,
    detect_platform,
    resolve_via_platform,
)
from app.platforms.models import ResolvedMeeting

# A private helper, reused deliberately rather than copied -- see this
# module's own docstring. Pure (one HEAD request, no shared state), so
# importing it directly is safe; a future fix in passive_verify.py
# reaches Resolve automatically instead of two copies drifting apart.
from app.platforms.passive_verify import _confirm_not_audio_only
from app.utils.video_hand_check import assess_video_candidate

from .models import (
    OUTCOME_MEETING_WITHOUT_VIDEO,
    OUTCOME_NO_MEETING_NOR_VIDEO,
    OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER,
    Candidate,
    FinderInput,
    ResolveResult,
)
from .pick import pick_candidates

# Same politeness spacing `scripts/wo134_confirmed_hits_ingest.py` uses
# between depth-search attempts on the same tenant (its own
# `CANDIDATE_DELAY_SECONDS`) -- Meeting Finder is a second, independent
# caller of the same adapters, so it keeps the same manners.
CANDIDATE_DELAY_SECONDS = 0.75


def _is_youtube_candidate(url: str) -> bool:
    return detect_platform(url) == "youtube"


def _to_candidate(raw: dict, *, lister: str, source_url: Optional[str]) -> Candidate:
    """A `CalendarPageError`/`pick_calendar_candidates()` dict -> a real
    `Candidate`, for the "a listing page found mid-resolve widens the
    search" path below."""
    return Candidate(
        url=raw["url"],
        title=raw.get("title"),
        date=raw.get("date"),
        platform=None,
        source_phase="list",
        lister=lister,
        source_url=source_url,
    )


async def resolve_candidates(
    candidates: Sequence[Candidate],
    finder_input: FinderInput,
    *,
    max_tries: int = 6,
) -> ResolveResult:
    """Public contract per WO-1024's brief: the small, typed
    `ResolveResult`. `runner.py` calls `_resolve_candidates_with_meeting()`
    below for the one extra value `identity.check_identity()` needs (the
    full `ResolvedMeeting` behind the winning candidate) -- see that
    function's own docstring for why `ResolveResult` doesn't carry it."""
    result, _meeting = await _resolve_candidates_with_meeting(
        candidates, finder_input, max_tries=max_tries
    )
    return result


async def _resolve_candidates_with_meeting(
    candidates: Sequence[Candidate],
    finder_input: FinderInput,
    *,
    max_tries: int = 6,
) -> Tuple[ResolveResult, Optional[ResolvedMeeting]]:
    """The real implementation. Try `candidates` in `pick.py`'s order,
    real adapter each time, until one has a transcript or a probed video
    of reasonable length.

    `max_tries` bounds how many candidates are actually resolved (real
    network calls) -- a `CalendarPageError` hit mid-way can hand back more
    candidates than fit in the remaining budget; those are picked over
    with the same rule and only as many as remain get tried.
    """
    picked, pick_reason = pick_candidates(list(candidates), limit=max_tries)
    if not picked:
        return (
            ResolveResult(
                candidate=None,
                tier=None,
                platform=None,
                video_url=None,
                has_segments=False,
                duration_seconds=None,
                outcome=OUTCOME_NO_MEETING_NOR_VIDEO,
                note=pick_reason or "no candidates to try",
            ),
            None,
        )

    youtube_leads: List[Candidate] = []
    # (Candidate, ResolvedMeeting, queue_probe.ProbeResult) for every
    # tier-3 candidate actually probed -- select_best_probe_result() picks
    # among these at the end, same rule resolve_seed() uses (prefer a
    # duration in queue_probe.IN_WINDOW_*, else the shortest plausible
    # one -- the concrete form of "over 90 minutes, keep looking for a
    # shorter one" the design doc describes).
    probed: List[Tuple[Candidate, ResolvedMeeting, "queue_probe.ProbeResult"]] = []
    best_no_video: Optional[Tuple[Candidate, ResolvedMeeting]] = None
    reasons: List[str] = [pick_reason] if pick_reason else []

    queue: List[Candidate] = list(picked)
    tries_used = 0
    i = 0
    while i < len(queue) and tries_used < max_tries:
        cand = queue[i]
        i += 1

        if _is_youtube_candidate(cand.url):
            youtube_leads.append(cand)
            continue

        if tries_used:
            await asyncio.sleep(CANDIDATE_DELAY_SECONDS)
        tries_used += 1

        try:
            result = await resolve_via_platform(cand.url, allow_youtube=False)
        except YouTubeResolveBlocked:
            # This candidate's own page isn't on YouTube, but everything
            # it has to offer delegates to one (a PrimeGov/CivicPlus/
            # Legistar embed) -- same disposition as a candidate that was
            # a youtube.com URL to begin with.
            youtube_leads.append(cand)
            continue
        except UnsupportedPlatformError as e:
            reasons.append(f"unsupported platform for {cand.url}: {e}")
            continue
        except CalendarPageError as e:
            # A listing page found mid-resolve, not an error -- widen the
            # search with the SAME picking rule, spending only the
            # remaining try budget on what it hands back (design doc:
            # "Handle CalendarPageError by returning its candidates to
            # the caller (a listing page is List's job, not an error)").
            remaining = max_tries - tries_used
            if remaining <= 0:
                reasons.append(f"{cand.url}: calendar page, no budget left to try it")
                continue
            more, more_reason = pick_candidates(
                [
                    _to_candidate(c, lister="adapter_list", source_url=cand.url)
                    for c in e.candidates
                ],
                limit=remaining,
            )
            if not more:
                reasons.append(
                    f"{cand.url}: calendar page, {more_reason or 'no clean candidate'}"
                )
                continue
            queue[i:i] = more
            continue
        except (ResolveError, NoVideoCandidateFound) as e:
            reasons.append(f"{cand.url}: {e}")
            continue
        except Exception as e:  # noqa: BLE001
            # One bad candidate shouldn't abort the whole walk -- same
            # posture app/platforms/base.py's resolve_newest_candidate()
            # already takes.
            reasons.append(f"{cand.url}: resolve raised {e}")
            continue

        if result.video_url:
            gate = assess_video_candidate(
                title=result.title,
                video_url=result.video_url,
                platform=result.platform,
                structured=True,
            )
            if gate.rejected:
                reasons.append(f"{cand.url}: {gate.tag} -- {gate.detail}")
                continue
            if not await _confirm_not_audio_only(result.video_url):
                reasons.append(f"{cand.url}: resolved video is audio-only")
                continue

        if result.segments:
            return (
                ResolveResult(
                    candidate=cand,
                    tier=1,
                    platform=result.platform,
                    video_url=result.video_url,
                    has_segments=True,
                    duration_seconds=result.video_duration_seconds,
                    outcome=None,
                    note="",
                ),
                result,
            )

        if result.video_url:
            probe = await queue_probe.probe_queue_entry(
                cand.url,
                video_url=result.video_url,
                source_page_url=result.source_url or cand.url,
                platform=result.platform,
                video_format=result.video_format,
            )
            if queue_probe.is_plausible(probe):
                probed.append((cand, result, probe))
                if (
                    probe.duration_seconds is not None
                    and queue_probe.IN_WINDOW_MIN_SECONDS
                    <= probe.duration_seconds
                    <= queue_probe.IN_WINDOW_MAX_SECONDS
                ):
                    break
                continue
            reasons.append(f"{cand.url}: {probe.reason or 'probe rejected'}")
            continue

        if best_no_video is None and (result.agenda_items or result.agenda_link):
            best_no_video = (cand, result)

    if probed:
        chosen_probe = queue_probe.select_best_probe_result([p for (_, _, p) in probed])
        if chosen_probe is not None:
            for cand, result, probe in probed:
                if probe is chosen_probe:
                    return (
                        ResolveResult(
                            candidate=cand,
                            tier=3,
                            platform=result.platform,
                            video_url=result.video_url,
                            has_segments=False,
                            duration_seconds=probe.duration_seconds,
                            outcome=None,
                            note=(
                                "over 90 minutes, no shorter alternative found"
                                if probe.duration_seconds
                                and probe.duration_seconds > 90 * 60
                                else ""
                            ),
                        ),
                        result,
                    )

    if best_no_video:
        cand, result = best_no_video
        return (
            ResolveResult(
                candidate=cand,
                tier=None,
                platform=result.platform,
                video_url=None,
                has_segments=False,
                duration_seconds=None,
                outcome=OUTCOME_MEETING_WITHOUT_VIDEO,
                note="; ".join(reasons),
            ),
            result,
        )

    if youtube_leads:
        lead = youtube_leads[0]
        return (
            ResolveResult(
                candidate=lead,
                tier=2,
                platform="youtube",
                video_url=lead.url,
                has_segments=False,
                duration_seconds=None,
                outcome=None,
                note=(
                    f"{len(youtube_leads)} YouTube candidate(s) found, saved as a "
                    "drip lead, never fetched"
                ),
            ),
            None,
        )

    outcome = (
        OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER
        if reasons and all("unsupported platform" in r for r in reasons)
        else OUTCOME_NO_MEETING_NOR_VIDEO
    )
    return (
        ResolveResult(
            candidate=None,
            tier=None,
            platform=None,
            video_url=None,
            has_segments=False,
            duration_seconds=None,
            outcome=outcome,
            note="; ".join(reasons) or "nothing resolved",
        ),
        None,
    )
