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
import re
from typing import List, Optional, Sequence, Tuple
from urllib.parse import parse_qs, urlparse

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
from app.platforms import passive_verify
from app.platforms.passive_verify import _confirm_not_audio_only
from app.platforms.telvue import _org_token_from_url as _telvue_org_token_from_url
from app.platforms.vimeo import EMBED_DOMAIN_RESTRICTED_WARNING
from app.utils.gov_registry.registry import Government, government_for_id
from app.utils.video_hand_check import (
    assess_meeting_evidence,
    assess_video_candidate,
    decode_filename_text,
)

from .models import (
    OUTCOME_EMBED_RESTRICTED,
    OUTCOME_MEETING_WITHOUT_VIDEO,
    OUTCOME_NO_MEETING_NOR_VIDEO,
    OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER,
    OUTCOME_VIDEO_LOW_CONFIDENCE,
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
# measured at all AND has no real meeting evidence -- see WO-1049 below).
# Lower rank wins.
# WO-1076 addendum: `finder_input.gov_id` -> the government's own
# `gov_name`/`gov_type`, looked up once per `gov_id` and cached for the
# life of the process -- so `assess_video_candidate()` can tell a school
# district's OWN board/committee meeting apart from a DIFFERENT school
# district's (see `video_hand_check._gov_kind_is_school_district()`'s own
# comment for the real false positives this fixes). Same pattern as
# `runner.py`'s own `_GOV_CACHE` (a separate cache -- `resolve.py` can't
# import from `runner.py`, which imports THIS module).
_GOV_CACHE: dict[str, Optional[Government]] = {}


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


_KEPT_DESPITE_TOO_SHORT = 0
_KEPT_DESPITE_GATE_REJECTED = 1
# WO-1049 fix 3 (Ryan's rule, 2026-09-23): this rank is now reached ONLY
# when a length-unknown video also has no real meeting evidence (and
# needed some) -- see `_needs_meeting_evidence()`. When there IS evidence
# (or the platform doesn't need any), the same "reject-dead" probe result
# is instead a clean tier-3 find, via the separate `length_unknown_finds`
# list in `_resolve_candidates_with_meeting()` -- checked right after the
# `probed` (real, accepted duration) candidates and BEFORE this whole
# `kept_despite` fallback ladder, since a length-unknown video with real
# evidence it's a meeting is a stronger, more confirmed signal than any
# of these ranks (a too-short clip or a title the gate rejected).
_KEPT_DESPITE_LENGTH_UNKNOWN = 2
# WO-1041: a direct-file/Vimeo/"undated, lister order" find with no real
# meeting evidence (see `_needs_meeting_evidence()`/`_meeting_evidence()`
# below). Ranked last -- weaker signal than any of the three above, all of
# which at least come with a measured (or attempted) duration; this one is
# purely "nothing said it WAS a meeting", tried only when nothing else
# turned up anywhere.
_KEPT_DESPITE_NO_MEETING_EVIDENCE = 3
# WO-1046: a CONFIRMED real meeting video (a dated, titled row off a
# Vimeo showcase/channel listing) that Vimeo itself refuses to serve
# outside the government's own domain -- see `models.OUTCOME_EMBED_
# RESTRICTED`'s own comment. Ranked BEFORE (stronger than) the four
# ranks above: those are all genuine uncertainty about whether a video is
# even a real meeting; this one we already know is a real meeting, we
# just can't play or transcribe it here. A negative rank keeps it
# strictly ahead of 0-3 without renumbering them.
_KEPT_DESPITE_EMBED_RESTRICTED = -1

# Same politeness spacing `scripts/wo134_confirmed_hits_ingest.py` uses
# between depth-search attempts on the same tenant (its own
# `CANDIDATE_DELAY_SECONDS`) -- Meeting Finder is a second, independent
# caller of the same adapters, so it keeps the same manners.
CANDIDATE_DELAY_SECONDS = 0.75


def _is_youtube_candidate(url: str) -> bool:
    return detect_platform(url) == "youtube"


def _is_embed_restricted(result: ResolvedMeeting) -> bool:
    """True for the exact "Vimeo owner restricted this to specific
    domains" case `vimeo.py`'s `resolve_video_id()` reports (see
    `EMBED_DOMAIN_RESTRICTED_WARNING`'s own comment) -- never for an
    ordinary "no video found"/"couldn't read details" warning, which
    aren't a confirmed real meeting the way this one is."""
    return EMBED_DOMAIN_RESTRICTED_WARNING in (result.video_warnings or [])


# WO-1041 spot-check (BACKLOG_DONE.md's WO-1041 entry): direct files and
# Vimeo finds with no per-meeting listing behind them were wrong far more
# often than any other source Resolve accepts as a clean find -- 0/10 real
# direct-file finds and 3/12 real Vimeo finds in the calibration sample,
# with every real Vimeo one carrying a meeting/body word or a date. A
# candidate picked by pick.py's weakest bucket ("picked by: undated, lister
# order") showed the same pattern regardless of platform. These three need
# a positive "meeting evidence" check (`assess_meeting_evidence()`) on top
# of the ordinary `assess_video_candidate()` gate above; every other source
# already carries its own evidence (a per-meeting listing, a dedicated
# meeting platform).
_EVIDENCE_REQUIRED_PLATFORMS = frozenset({"direct_file", "vimeo"})


def _needs_meeting_evidence(platform: Optional[str], pick_reason: str) -> bool:
    return (platform or "").lower() in _EVIDENCE_REQUIRED_PLATFORMS or (
        "picked by: undated, lister order" in (pick_reason or "")
    )


# WO-1041 build step 2: a Google Drive video link carries no title of its
# own on the candidate/adapter side -- the title lives on Drive's own file
# page (`drive.google.com/file/d/<id>/view`), so it must be read before
# grading. One plain GET, short timeout, in-process cache (a government's
# walk can hit the same Drive id more than once across forks/hops) --
# deliberately NOT routed through Fetcher's per-government fetch budget or
# host-pacing state, the same way `_confirm_not_audio_only()` above (a
# single HEAD request) stands on its own; this is the same shape of cheap,
# one-off, side-effect-free lookup, never retried and never escalated past
# a plain request.
#
# WO-1049: `drive.google.com` alone missed the two other real Drive URL
# shapes a government actually links -- a download link
# (`drive.usercontent.google.com/download?id=<id>`) and the legacy
# `drive.google.com/uc?id=<id>` form. All three carry the same file id,
# just in a different place (a path segment or a query param); the title
# always lives at the same `drive.google.com/file/d/<id>/view` page
# regardless of which shape was linked, so every shape is normalized to
# that one lookup URL. Real case: Bellerive Acres MO, id
# 1GgmbtthXToVwIcy2p6xeEyVZj7OI0erB, title "(2026-09-22) City Council
# Special Meeting".
_DRIVE_HOSTS = frozenset({"drive.google.com", "drive.usercontent.google.com"})
_DRIVE_FILE_ID_PATH_RE = re.compile(r"/file/d/([\w-]+)")
_drive_title_cache: dict[str, Optional[str]] = {}


def _extract_drive_file_id(url: Optional[str]) -> Optional[str]:
    """The file id out of any real Drive URL shape (see the block comment
    above): `drive.google.com/file/d/<id>/view`, `drive.google.com/uc?
    id=<id>` (and the older `/open?id=<id>`), or `drive.usercontent.
    google.com/download?id=<id>`. `None` for anything not a Drive host or
    with no recognizable id."""
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if (parsed.hostname or "").lower() not in _DRIVE_HOSTS:
        return None
    match = _DRIVE_FILE_ID_PATH_RE.search(parsed.path)
    if match:
        return match.group(1)
    ids = parse_qs(parsed.query).get("id")
    return ids[0] if ids else None


async def _fetch_drive_title(file_id: str) -> Optional[str]:
    if file_id in _drive_title_cache:
        return _drive_title_cache[file_id]
    title: Optional[str] = None
    url = f"https://drive.google.com/file/d/{file_id}/view"
    try:
        import aiohttp

        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    body = await resp.text(errors="ignore")
                    match = re.search(
                        r"<title[^>]*>([^<]*)</title>", body, re.IGNORECASE
                    )
                    if match:
                        # Drive's own page title is "<file title> - Google
                        # Drive" -- strip the fixed suffix.
                        title = match.group(1).rsplit(" - Google Drive", 1)[0].strip()
    except Exception:  # noqa: BLE001 -- a Drive read failing is "no title", not a crash
        title = None
    _drive_title_cache[file_id] = title
    return title


async def _meeting_evidence_texts(
    cand: Candidate, result: ResolvedMeeting
) -> List[Optional[str]]:
    """Every text WO-1041's brief names as evidence source: the resolved
    title, the candidate's own (pre-resolve) title, the candidate URL's
    filename/path, the linking page's URL (`cand.source_url`), and, for a
    Google Drive link, the file's own page title.

    WO-1049 adds two more: the DECODED filename/path of `cand.url` and of
    `result.video_url` (the adapter's own final file may differ from the
    candidate it was found from -- e.g. a listing row pointing at a Drive
    share link whose resolved `video_url` is the direct download). A raw
    URL's word-boundary matching silently fails on both percent-encoding
    and hyphen/underscore-joined filenames -- see `decode_filename_text()`
    for the two confirmed-real cases (Bellerive Acres MO, Bound Brook NJ)
    this closes.
    """
    texts: List[Optional[str]] = [result.title, cand.title, cand.url, cand.source_url]
    texts.append(decode_filename_text(cand.url))
    if result.video_url:
        texts.append(decode_filename_text(result.video_url))
    video_url = result.video_url or cand.url
    drive_file_id = _extract_drive_file_id(video_url) or _extract_drive_file_id(
        cand.source_url
    )
    if drive_file_id:
        texts.append(await _fetch_drive_title(drive_file_id))
    return texts


async def _meeting_evidence(
    cand: Candidate, result: ResolvedMeeting, duration_seconds: Optional[float]
):
    texts = await _meeting_evidence_texts(cand, result)
    return assess_meeting_evidence(
        *texts,
        duration_seconds=duration_seconds,
        is_direct_file=(result.platform or "").lower() == "direct_file",
    )


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


# --- WO-1054 rule 4 (Ryan, 2026-09-24): "broken TelVue playlist -> fall
# back to the same token's /home or /videos." Real case: College
# Township, PA's own nav link ("C-Net Meeting Broadcasts") points at
# `videoplayer.telvue.com/player/{token}/playlists/4807/media/698580`,
# which 404s -- while the SAME org token's own `/home` page (Centre
# County C-NET, shared with Bellefonte -- see `pick.filter_candidates_
# to_government()` for the SEPARATE "shared hub" rule this also needs)
# lists real, current video. `TelvueAssetFinder.resolve()` itself has no
# such fallback (a specific `/media/{id}` URL either has a real playlist
# JSON blob or it doesn't); this tries the listing ONCE, reusing
# `passive_verify._telvue_walker()` (which already reduces ANY TelVue URL
# to its own canonical `/home` entry point via `telvue.account_url_for()`
# -- WO-1038) rather than re-deriving that reduction here.
async def _telvue_broken_media_fallback(
    cand: Candidate, tried_orgs: set
) -> List[Candidate]:
    """Only fires for a TelVue candidate whose own `resolve()` call
    raised (any reason -- a 404, a dropped connection, a missing playlist
    blob) -- `tried_orgs` (one Resolve call's own local `set`) makes sure
    this only ever happens once per org token per call, even if several
    broken links from the same channel got queued. Returns fresh
    `Candidate`s from the SAME channel's real listing, minus `cand.url`
    itself (never re-offering the exact link that just failed); `[]` when
    `cand` isn't TelVue, has no recoverable org token, was already tried,
    or the listing fetch itself comes back empty."""
    if detect_platform(cand.url) != "telvue":
        return []
    org_token = _telvue_org_token_from_url(cand.url)
    if not org_token or org_token in tried_orgs:
        return []
    tried_orgs.add(org_token)
    try:
        rows = await passive_verify._telvue_walker(cand.url)
    except Exception:  # noqa: BLE001
        return []
    out: List[Candidate] = []
    for row in rows:
        url = row.get("url")
        if not url or url == cand.url:
            continue
        out.append(
            Candidate(
                url=url,
                title=row.get("title"),
                date=row.get("date"),
                platform="telvue",
                source_phase="list",
                lister="telvue_playlist_fallback",
                source_url=cand.source_url,
                has_video_hint=True,
            )
        )
    return out


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

    # WO-1049 fix 3 (Ryan's rule, 2026-09-23): a video whose length
    # couldn't be measured at all ("reject-dead") is a REAL find, not a
    # weak lead, as long as there's real meeting evidence for it (or the
    # platform doesn't need any -- see `_needs_meeting_evidence()`). Real
    # case: Bound Brook NJ's `.mp3` (ffprobe can't read the media, but the
    # URL itself names "Reorganization Meeting"). Collected here rather
    # than returned immediately, so a candidate that DOES probe with a
    # real, accepted duration (`probed` above) still wins -- "still
    # ordered after measured ones" per the brief. Only when neither
    # evidence exists (and the platform needs it) does a length-unknown
    # video stay a `_KEPT_DESPITE_LENGTH_UNKNOWN` weak lead, unchanged
    # from before this fix. (Candidate, ResolvedMeeting, audio_only).
    length_unknown_finds: List[Tuple[Candidate, ResolvedMeeting, bool]] = []

    queue: List[Candidate] = list(picked)
    tries_used = 0
    i = 0
    # WO-1054 rule 4: one org token per Resolve call gets at most one
    # `/home` listing fallback attempt (see `_telvue_broken_media_
    # fallback()` below) -- several broken links from the SAME channel
    # queued as separate candidates must not each re-fetch its listing.
    telvue_fallback_tried: set = set()
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
                    # WO-1046: prefer the ORIGINAL page this listing was
                    # found embedded on (`cand.source_url`) over the
                    # listing URL itself (`cand.url`, e.g. a Vimeo
                    # showcase) -- so a downstream "link out to the
                    # meeting page" (e.g. OUTCOME_EMBED_RESTRICTED) points
                    # at a real government page, not a bare Vimeo listing
                    # link. Falls back to `cand.url` when there's no
                    # source (e.g. a listing given directly as Resolve's
                    # own input candidate).
                    _to_candidate(
                        c,
                        lister="adapter_list",
                        source_url=cand.source_url or cand.url,
                    )
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
            # WO-1054 rule 4: a TelVue link found via Hop can itself be
            # broken (a stale `/playlists/{n}/media/{m}` link, real
            # College Township, PA case: 404) while the SAME org token's
            # own `/home`/`/videos` listing has real, current video --
            # try that once before giving up on this candidate outright.
            fallback = await _telvue_broken_media_fallback(cand, telvue_fallback_tried)
            if fallback:
                remaining = max_tries - tries_used
                if remaining > 0:
                    more, _more_reason = pick_candidates(fallback, limit=remaining)
                    if more:
                        queue[i:i] = more
                        reasons.append(
                            f"{cand.url}: resolve raised {e} -- falling back to "
                            "the same TelVue channel's own /home listing"
                        )
                        continue
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
            gov = _government_for_input(finder_input)
            gate = assess_video_candidate(
                title=result.title,
                video_url=result.video_url,
                platform=result.platform,
                structured=True,
                gov_name=gov.gov_name if gov else None,
                gov_kind=gov.gov_type if gov else None,
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
        elif _is_embed_restricted(result):
            # WO-1046: no `video_url` at all -- Vimeo's own oEmbed refused
            # to serve this video outside the government's own site (see
            # `_is_embed_restricted()`'s own comment). This is a real,
            # confirmed meeting (the candidate came off a dated showcase/
            # channel listing row) that we simply can't play or
            # transcribe here -- never worked around with a spoofed
            # domain/Referer (CLAUDE.md: an owner's explicit access
            # restriction is treated the same as a human-verification
            # gate). Kept as the strongest "kept despite" fallback rather
            # than silently dropped -- see `_KEPT_DESPITE_EMBED_RESTRICTED`.
            rule = (
                "Vimeo restricts this video's embedding/playback to the "
                "government's own site"
            )
            reasons.append(f"{cand.url}: {rule}")
            if _KEPT_DESPITE_EMBED_RESTRICTED not in kept_despite:
                kept_despite[_KEPT_DESPITE_EMBED_RESTRICTED] = (
                    cand,
                    result,
                    None,
                    rule,
                )
            continue

        if result.segments:
            if _needs_meeting_evidence(result.platform, pick_reason):
                evidence = await _meeting_evidence(
                    cand, result, result.video_duration_seconds
                )
                if not evidence.has_evidence:
                    rule = (
                        f"no meeting evidence "
                        f"({evidence.non_meeting_sign or 'nothing found'})"
                    )
                    reasons.append(f"{cand.url}: {rule}")
                    if _KEPT_DESPITE_NO_MEETING_EVIDENCE not in kept_despite:
                        kept_despite[_KEPT_DESPITE_NO_MEETING_EVIDENCE] = (
                            cand,
                            result,
                            result.video_duration_seconds,
                            rule,
                        )
                    continue
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
                if _needs_meeting_evidence(result.platform, pick_reason):
                    evidence = await _meeting_evidence(
                        cand, result, probe.duration_seconds
                    )
                    if not evidence.has_evidence:
                        rule = (
                            f"no meeting evidence "
                            f"({evidence.non_meeting_sign or 'nothing found'})"
                        )
                        reasons.append(f"{cand.url}: {rule}")
                        if _KEPT_DESPITE_NO_MEETING_EVIDENCE not in kept_despite:
                            kept_despite[_KEPT_DESPITE_NO_MEETING_EVIDENCE] = (
                                cand,
                                result,
                                probe.duration_seconds,
                                rule,
                            )
                        continue
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
                # WO-1049 fix 3: check for real meeting evidence before
                # demoting this to a weak lead -- a length-unknown video
                # is a clean tier-3 find when there's evidence it's a
                # meeting (or the platform doesn't need any), and only a
                # `_KEPT_DESPITE_LENGTH_UNKNOWN` weak lead when it needs
                # evidence and has none.
                needs_evidence = _needs_meeting_evidence(result.platform, pick_reason)
                evidence_ok = True
                non_meeting_sign = None
                if needs_evidence:
                    evidence = await _meeting_evidence(cand, result, None)
                    evidence_ok = evidence.has_evidence
                    non_meeting_sign = evidence.non_meeting_sign
                if evidence_ok:
                    length_unknown_finds.append((cand, result, audio_only))
                else:
                    rule = (
                        f"video length couldn't be measured ({probe.reason}); "
                        f"no meeting evidence "
                        f"({non_meeting_sign or 'nothing found'})"
                    )
                    reasons.append(f"{cand.url}: {rule}")
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

    # WO-1049 fix 3 (Ryan's rule, 2026-09-23): no candidate probed with a
    # real, accepted duration -- but at least one length-unknown video has
    # real meeting evidence (or didn't need any). That's a clean tier-3
    # find, "ranked after measured ones" (the `probed` check just above
    # already had first pick), NOT a weak lead -- the first one here is
    # the highest-ranked (`pick.py`'s own preferred order already tried
    # candidates in that order).
    if length_unknown_finds:
        cand, result, audio_only = length_unknown_finds[0]
        return (
            ResolveResult(
                candidate=cand,
                tier=3,
                platform=result.platform,
                video_url=result.video_url,
                has_segments=False,
                duration_seconds=None,
                outcome=None,
                note=_note("audio only" if audio_only else ""),
                audio_only=audio_only,
            ),
            result,
        )

    # WO-1035 item 2 (Ryan's rule): nothing resolved cleanly, but a video
    # was found and then would otherwise have been thrown away -- keep the
    # best-ranked one (see the module-level `_KEPT_DESPITE_*` order)
    # rather than falling through to "meeting without video" or "nothing
    # found" while a real video sits right there.
    #
    # WO-1035 follow-up (conductor live check, 2026-09-23): this is NOT a
    # clean find -- `outcome` must be OUTCOME_VIDEO_LOW_CONFIDENCE, never
    # `None`. Returning `None` here (the original bug) made runner.py's
    # `_try_resolve()` treat a "kept despite" pick from ONE candidate list
    # (e.g. a homepage banner .mp4) exactly like a real success and stop
    # the whole government walk immediately -- confirmed live on
    # champaignil.gov: a 12-second banner clip on the homepage won before
    # the walk ever reached the real Cablecast council-meeting account.
    # `runner.py` now holds this as a per-government FALLBACK (see
    # `_WalkState.low_confidence`) and keeps walking every other fork/hop;
    # only if NOTHING clean turns up anywhere is this fallback used as the
    # final result, with this same outcome and rank intact.
    for rank in (
        _KEPT_DESPITE_EMBED_RESTRICTED,
        _KEPT_DESPITE_TOO_SHORT,
        _KEPT_DESPITE_GATE_REJECTED,
        _KEPT_DESPITE_LENGTH_UNKNOWN,
        _KEPT_DESPITE_NO_MEETING_EVIDENCE,
    ):
        if rank in kept_despite:
            cand, result, duration, rule = kept_despite[rank]
            # WO-1046: embed-restricted has no `video_url` at all (Vimeo
            # refused it), so it isn't a "video, no captions" tier-3 find
            # like the other kept-despite ranks -- and it gets its own
            # outcome (`OUTCOME_EMBED_RESTRICTED`), not the generic
            # `OUTCOME_VIDEO_LOW_CONFIDENCE`, since we KNOW this is a real
            # meeting rather than merely suspecting one.
            embed_restricted = rank == _KEPT_DESPITE_EMBED_RESTRICTED
            return (
                ResolveResult(
                    candidate=cand,
                    tier=None if embed_restricted else 3,
                    platform=result.platform,
                    video_url=result.video_url,
                    has_segments=False,
                    duration_seconds=duration,
                    outcome=(
                        OUTCOME_EMBED_RESTRICTED
                        if embed_restricted
                        else OUTCOME_VIDEO_LOW_CONFIDENCE
                    ),
                    note=_note(f"kept despite: {rule}"),
                    low_confidence_reason=rule,
                    low_confidence_rank=rank,
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
