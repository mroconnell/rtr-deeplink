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

# WO-1035 item 2 (Ryan's rule): a "kept despite" fallback candidate, in
# the priority order they're preferred at the end of the walk when
# nothing clean resolved -- rank 0 (a measured-but-too-short video) beats
# rank 1 (a video the quality gate rejected on title alone -- no duration
# evidence either way) beats rank 2 (a video whose length couldn't be
# measured at all: "video, length unknown", tried only after every
# candidate with SOME known-length evidence). Lower rank wins.
_KEPT_DESPITE_TOO_SHORT = 0
_KEPT_DESPITE_GATE_REJECTED = 1
_KEPT_DESPITE_LENGTH_UNKNOWN = 2

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
    # WO-1035 item 4: pick over the FULL candidate list, not just the top
    # `max_tries` -- a YouTube candidate never spends a try (see the loop
    # below, which routes it to `youtube_leads` before `tries_used` is
    # incremented), so truncating to `max_tries` here, before that split
    # happens, could silently drop a real non-YouTube candidate ranked
    # just below a run of YouTube ones. The loop's own `tries_used`
    # bound is what actually limits real resolve attempts.
    candidates_list = list(candidates)
    picked, pick_reason = pick_candidates(
        candidates_list, limit=max(len(candidates_list), max_tries)
    )

    def _note(extra: str) -> str:
        """WO-1035 item 1: "note in the verdict which rule picked" -- a
        non-empty `pick_reason` (pick.py only sets one for a non-obvious
        pick: undated/future-dated bucket, or a demoted/weak title kept as
        a last resort) is carried into whichever `ResolveResult.note`
        this call ultimately returns, success or failure alike."""
        return "; ".join(p for p in (pick_reason, extra) if p)

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
    # The trailing `bool` is `audio_only` (WO-1035 item 3).
    probed: List[
        Tuple[Candidate, ResolvedMeeting, "queue_probe.ProbeResult", bool]
    ] = []
    # `ResolvedMeeting` is `None` specifically for the "lister already
    # confirmed this is a real no-video row" case above (no adapter
    # `resolve()` call ever succeeded for it).
    best_no_video: Optional[Tuple[Candidate, Optional[ResolvedMeeting]]] = None
    reasons: List[str] = [pick_reason] if pick_reason else []

    # WO-1035 item 2: the best "kept despite" candidate seen so far, one
    # slot per rank (see the module-level `_KEPT_DESPITE_*` constants) --
    # (Candidate, ResolvedMeeting, duration_or_None, rule_text). Only the
    # first (highest-ranked) real find per rank is kept, since these are
    # already tried in `pick.py`'s preferred order.
    kept_despite: dict[
        int, Tuple[Candidate, ResolvedMeeting, Optional[float], str]
    ] = {}

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
            # A candidate a LISTER already marked `has_video_hint=False`
            # (e.g. `listing.py`'s CivicPlus agenda-only fallback) is
            # already confirmed to be a real meeting row -- the lister
            # read the government's own listing page and found a real
            # title/date/agenda link, just no video. The adapter's own
            # `resolve()` raising here (rather than returning a
            # `ResolvedMeeting` with `agenda_items`/`agenda_link` set, the
            # path the check below normally takes) doesn't change that
            # fact -- confirmed live on Cass County, MN (conductor review,
            # 2026-09-23): `CivicPlusAssetFinder.resolve()` on one
            # specific `ViewFile/Agenda` URL raises `NoVideoCandidateFound`
            # outright rather than returning agenda info. Trust the
            # lister's own finding instead of losing it here -- this is
            # the only place `best_no_video`'s own `ResolvedMeeting` can
            # be `None` (see the `if best_no_video:` branch below, which
            # already tolerates that).
            if cand.has_video_hint is False and best_no_video is None:
                best_no_video = (cand, None)
            reasons.append(f"{cand.url}: {e}")
            continue
        except Exception as e:  # noqa: BLE001
            # One bad candidate shouldn't abort the whole walk -- same
            # posture app/platforms/base.py's resolve_newest_candidate()
            # already takes.
            reasons.append(f"{cand.url}: resolve raised {e}")
            continue

        # WO-1035 item 3: audio-only is no longer a reject -- it's a real
        # find, just labelled. Fall through to the normal tier-1/tier-3
        # checks below instead of discarding the candidate.
        audio_only = False
        if result.video_url:
            gate = assess_video_candidate(
                title=result.title,
                video_url=result.video_url,
                platform=result.platform,
                structured=True,
            )
            if gate.rejected:
                # WO-1035 item 2: kept as a last resort instead of lost --
                # a promo/hero/test-shaped title the gate rejected, but a
                # real video URL still came back from the adapter.
                rule = f"video gate rejected it ({gate.tag}: {gate.detail})"
                reasons.append(f"{cand.url}: {gate.tag} -- {gate.detail}")
                if _KEPT_DESPITE_GATE_REJECTED not in kept_despite:
                    kept_despite[_KEPT_DESPITE_GATE_REJECTED] = (
                        cand,
                        result,
                        None,
                        rule,
                    )
                continue
            if not await _confirm_not_audio_only(result.video_url):
                audio_only = True

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
                    note=_note("audio only" if audio_only else ""),
                    audio_only=audio_only,
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
                probed.append((cand, result, probe, audio_only))
                if (
                    probe.duration_seconds is not None
                    and queue_probe.IN_WINDOW_MIN_SECONDS
                    <= probe.duration_seconds
                    <= queue_probe.IN_WINDOW_MAX_SECONDS
                ):
                    break
                continue
            reasons.append(f"{cand.url}: {probe.reason or 'probe rejected'}")
            # WO-1035 item 2: keep a too-short or unmeasurable video as a
            # last resort too. `reject-short` still has a real measured
            # duration (the strongest of the three kept-despite ranks);
            # `reject-dead` here means "no probe recipe/timeout/error",
            # never "the adapter never returned a video_url" (that path
            # doesn't reach `probe_queue_entry()` at all) -- see this
            # module's own `_KEPT_DESPITE_*` ranking.
            if probe.verdict == "reject-short" and probe.duration_seconds is not None:
                rule = f"too short ({probe.duration_seconds:.0f}s): {probe.reason}"
                if _KEPT_DESPITE_TOO_SHORT not in kept_despite:
                    kept_despite[_KEPT_DESPITE_TOO_SHORT] = (
                        cand,
                        result,
                        probe.duration_seconds,
                        rule,
                    )
            elif probe.verdict == "reject-dead":
                rule = f"video length couldn't be measured ({probe.reason})"
                if _KEPT_DESPITE_LENGTH_UNKNOWN not in kept_despite:
                    kept_despite[_KEPT_DESPITE_LENGTH_UNKNOWN] = (
                        cand,
                        result,
                        None,
                        rule,
                    )
            continue

        if best_no_video is None and (result.agenda_items or result.agenda_link):
            best_no_video = (cand, result)

    if probed:
        chosen_probe = queue_probe.select_best_probe_result(
            [p for (_, _, p, _) in probed]
        )
        if chosen_probe is not None:
            for cand, result, probe, audio_only in probed:
                if probe is chosen_probe:
                    note = (
                        "over 90 minutes, no shorter alternative found"
                        if probe.duration_seconds and probe.duration_seconds > 90 * 60
                        else ""
                    )
                    if audio_only:
                        note = "; ".join(p for p in (note, "audio only") if p)
                    return (
                        ResolveResult(
                            candidate=cand,
                            tier=3,
                            platform=result.platform,
                            video_url=result.video_url,
                            has_segments=False,
                            duration_seconds=probe.duration_seconds,
                            outcome=None,
                            note=_note(note),
                            audio_only=audio_only,
                        ),
                        result,
                    )

    # WO-1035 item 2 (Ryan's rule): nothing resolved cleanly, but a video
    # was found and then would otherwise have been thrown away -- keep the
    # best-ranked one (see the module-level `_KEPT_DESPITE_*` order)
    # rather than falling through to "meeting without video" or "nothing
    # found" while a real video sits right there.
    for rank in (
        _KEPT_DESPITE_TOO_SHORT,
        _KEPT_DESPITE_GATE_REJECTED,
        _KEPT_DESPITE_LENGTH_UNKNOWN,
    ):
        if rank in kept_despite:
            cand, result, duration, rule = kept_despite[rank]
            return (
                ResolveResult(
                    candidate=cand,
                    tier=3,
                    platform=result.platform,
                    video_url=result.video_url,
                    has_segments=False,
                    duration_seconds=duration,
                    outcome=None,
                    note=_note(f"kept despite: {rule}"),
                    low_confidence_reason=rule,
                ),
                result,
            )

    if best_no_video:
        cand, result = best_no_video
        return (
            ResolveResult(
                candidate=cand,
                tier=None,
                # `result` is `None` for a lister-confirmed no-video row
                # whose own `resolve()` call raised rather than returning
                # a `ResolvedMeeting` -- fall back to the candidate's own
                # `platform` (set by `listing.py`) so Verdict still names
                # the real platform in that case.
                platform=result.platform if result is not None else cand.platform,
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
