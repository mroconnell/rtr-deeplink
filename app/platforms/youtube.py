import asyncio
import datetime
import logging
import re
from typing import List, Optional, Tuple

import yt_dlp

from .base import AssetFinder
from .models import ResolvedMeeting, TranscriptSegment
from .youtube_ids import extract_video_id
from ..utils import jurisdiction_enrich
from ..utils.vtt_parser import (
    decode_vtt_bytes,
    dedupe_rollup_cues,
    is_likely_garbled,
    parse_vtt,
)

logger = logging.getLogger("rtr_deeplink.youtube")

TARGET_LANGUAGE = "en"

# WO-285, 2026-09-12: a real, live-example already sitting in this file's
# own test fixture (REAL_TITLE in tests/test_youtube.py, "Oklahoma City
# Council Meeting - August 4, 2026") shows the meeting-date bug wasn't
# fully fixed by the 2026-08-12 release_date/upload_date change below --
# that OKC video's real title states August 4, but with no release_date
# set the old code fell back straight to upload_date (August 5, one day
# late). WO-277 found the same shape live on a real Aransas Pass, TX
# video and filed it in BACKLOG.md. A read-only audit of every archived
# YouTube page (3,764 total, 2026-09-12) confirmed this isn't rare: 2,416
# pages have a title with a parseable date, and 1,298 of those (54%)
# disagree with the *already-release_date-preferring* stored date --
# 780 of those disagreements (60%) are off by exactly +1 day, the same
# UTC-day-rollover shape as the original upload_date bug, meaning
# release_date carries it too for a meeting that starts in the evening
# US local time. The video's own stated title date is the most direct
# signal available and is preferred first now; release_date/upload_date
# stay as the fallback for the (common) case where the title has no
# parseable date at all. See BACKLOG.md's "page date = upload date" and
# "six real, confirmed cases" entries (moved to BACKLOG_DONE.md under
# WO-285) for the full audit numbers -- existing archived pages are
# *not* backfilled by this change; that's tracked as its own BACKLOG.md
# entry with the count.
_MEETING_TITLE_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_MONTH_NAME_ALTERNATION = "|".join(sorted(_MEETING_TITLE_MONTHS, key=len, reverse=True))
_MONTH_NAME_DATE_RE = re.compile(
    rf"\b({_MONTH_NAME_ALTERNATION})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b",
    re.IGNORECASE,
)
# M/D/Y or M-D-Y -- every real confirmed example so far is US-convention
# month-first (see BACKLOG.md's WO-226 six-case entry).
_NUMERIC_SLASH_DATE_RE = re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b")
# Bare "YYYY M D" / "YYYY-MM-DD" with no fixed separator width -- the
# specific shape WO-277 found ("2020 3 16") that the two patterns above
# don't match.
_BARE_YMD_DATE_RE = re.compile(r"\b(\d{4})[\s-](\d{1,2})[\s-](\d{1,2})\b")

# Real dates only -- reject a plausible-looking but nonsensical year
# (e.g. a stray "2024" budget-ordinance number that happens to sit next
# to two more small numbers) by bounding it to when this project's
# corpus could plausibly contain a video.
_MEETING_TITLE_MIN_YEAR = 2000


def _parse_meeting_date_from_title(title: Optional[str]) -> Optional[str]:
    """Best-effort ISO date parsed directly from a YouTube video's own
    title, e.g. "Oklahoma City Council Meeting - August 4, 2026" or a
    bare "2020 3 16". Returns None when no confident date is found --
    callers fall back to release_date/upload_date in that case. See the
    WO-285 comment above for why this now takes priority over both."""
    if not title:
        return None

    def _valid(year: int, month: int, day: int) -> Optional[str]:
        if year < _MEETING_TITLE_MIN_YEAR:
            return None
        try:
            return datetime.date(year, month, day).isoformat()
        except ValueError:
            return None

    m = _MONTH_NAME_DATE_RE.search(title)
    if m:
        month = _MEETING_TITLE_MONTHS.get(m.group(1).lower())
        if month:
            day, year = int(m.group(2)), int(m.group(3))
            parsed = _valid(year, month, day)
            if parsed:
                return parsed

    m = _NUMERIC_SLASH_DATE_RE.search(title)
    if m:
        a, b, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= a <= 12 and 1 <= b <= 31:
            parsed = _valid(year, a, b)
            if parsed:
                return parsed

    m = _BARE_YMD_DATE_RE.search(title)
    if m:
        year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            parsed = _valid(year, month, day)
            if parsed:
                return parsed

    return None


# `_VIDEO_ID_RE`/id extraction now live in `youtube_ids.py` (yt-dlp-free,
# WO-250) -- `extract_video_id()` above is re-exported from there, and
# `YouTubeAssetFinder.extract_video_id()` below just delegates to it. See
# youtube_ids.py's module docstring for why.

# Permanent-failure markers (WO-135, 2026-09-09) -- confirmed via a real
# yt-dlp metadata check (`_extract_info()` below) against the 96 real
# Archive YouTube pages with no transcript at the time. Unlike every other
# transcript_warnings/video_warnings message in this file, these are exact
# strings, not free text: scripts/fetch_youtube_transcripts.py and
# archive/db/crud.py's record_youtube_video_status() key on them verbatim
# (as does WO-136, the page treatment for a page carrying one), and a
# human reading either warnings list can tell "not fetched yet" apart from
# "confirmed, this will never succeed". Independently defined (not
# imported) in archive/db/crud.py and app/db/outcomes.py -- same
# duplicate-with-a-cross-reference-comment convention this file's own
# is_likely_garbled()/_GARBLED_MARKER pair already uses across the
# app/archive boundary. Keep all three in sync if the wording ever
# changes.
YOUTUBE_CAPTIONS_DISABLED_MARKER = "YouTube: captions are disabled by the channel"
YOUTUBE_EMBED_DISABLED_MARKER = (
    "YouTube: embedding is disabled by the channel; watch on YouTube"
)
YOUTUBE_VIDEO_UNAVAILABLE_MARKER = "YouTube: video is unavailable (removed or private)"

# Real yt-dlp error-message signatures. The original three (WO-135,
# 2026-09-09) came from running a metadata-only extract against all 96
# real YouTube-backed Archive pages that had no transcript at the time.
# WO-167 (2026-09-10) widened this after finding the real gap those three
# didn't close: Pacific City, MO's queued video (`XeWevpU5Kpc`) raises
# "This video is unavailable" -- a message the original signatures DID
# already match -- but `resolve_video_id()` used to just fold every
# permanently-gone case into a quiet, marker-carrying "success" (no
# title, no date, 0 segments) instead of raising. A caller that doesn't
# specifically inspect `transcript_warnings` for that marker (most
# don't -- they just check whether `resolve()` raised) saw an ordinary-
# looking empty resolve, indistinguishable from "no captions yet". See
# `YouTubeUnavailableError` below for the fix.
#
# Checked in this order -- "not yet started" first, since a scheduled
# livestream's own message ("This live event will begin in a few
# moments." / "...in 11 days.", confirmed live against real ids
# `-pNyufIO7xM`/`ESfzST-yOSM`, WO-143/WO-167) is NOT a permanent failure
# (the same video resolves fine once it airs) and must never be folded
# into "gone" -- checking it first keeps that guarantee explicit even if
# a future message shape happened to overlap both lists. A phrasing none
# of these match falls through to the existing generic "YouTube is
# blocking us" degrade (safe: costs one more retry) rather than guessing.
_NOT_YET_STARTED_SIGNATURES = ("will begin in",)

# Real, confirmed-live samples: `_RZBcYEbQr4` -> "This video has been
# removed by the uploader" (WO-135); `XeWevpU5Kpc` (Pacific City, MO) and
# `MW7uV8fohm0` -> "This video is unavailable" (WO-167, both from the
# tier-3 queue probe sidecar). "video unavailable" (no leading "this") is
# yt-dlp's own shorter synonym for the same outcome -- real, from its own
# extractor test fixtures (`extractor/youtube/_video.py`), not invented.
# The two HTTP-status shapes are yt-dlp/urllib's standard wording for a
# watch page that 404s/410s outright (an ancient deleted video/channel,
# never reaching the ordinary playability-status path above) -- not yet
# observed live against a real id in this repo, flagged here rather than
# silently assumed confirmed (see CLAUDE.md's "don't claim a data path
# works without a positive example").
_GONE_SIGNATURES = (
    "this video has been removed",
    "this video is unavailable",
    "video unavailable",
    "http error 404",
    "http error 410",
)

# Real, confirmed-live samples: `VGCR9XxsIVw`/`Eh1JO9zT_u0` -> "Private
# video. If the owner of this video has granted you access..." (WO-135).
_PRIVATE_SIGNATURES = ("private video", "this video is private")

# Real YouTube wording (widely observed, not yt-dlp's own text -- it's
# read verbatim from YouTube's own API response, the same
# `playabilityStatus.errorScreen` mechanism the other messages above come
# from) -- WO-167, 2026-09-10. Not yet confirmed against a real video in
# this repo (no terminated-account id found in the tier-3 sidecar or
# BACKLOG.md's dead-video entries this round); flagged here per the same
# "don't claim a path works without a positive example" rule as the
# 404/410 shapes above, so a real one is recognised correctly the first
# time it's hit rather than falling through to the generic degrade.
_TERMINATED_SIGNATURES = ("account associated with this video has been terminated",)


def classify_unavailability(message: str) -> Optional[str]:
    """Returns "not_yet_started" | "gone" | "private" | "terminated" for a
    real yt-dlp failure message (any case), or `None` if it doesn't match
    a known shape -- meaning the caller should treat it as the existing
    generic "YouTube is blocking us" degrade rather than guessing.

    One shared classifier, not three: `resolve_video_id()` (raises
    `YouTubeUnavailableError`), `check_permanent_failure()` (returns a
    marker tuple, never raises), and `app/platforms/queue_probe.py`'s
    `_probe_youtube()` (annotates its own `reason` field) all call this,
    so a newly-confirmed message shape is one change instead of three
    independent copies silently drifting apart.
    """
    lowered = message.lower()
    if any(sig in lowered for sig in _NOT_YET_STARTED_SIGNATURES):
        return "not_yet_started"
    if any(sig in lowered for sig in _TERMINATED_SIGNATURES):
        return "terminated"
    if any(sig in lowered for sig in _PRIVATE_SIGNATURES):
        return "private"
    if any(sig in lowered for sig in _GONE_SIGNATURES):
        return "gone"
    return None


class YouTubeUnavailableError(ValueError):
    """Raised by `resolve_video_id()` -- the adapter's normal "not found"
    error (this file already raises a plain `ValueError` for "no video id
    in this URL" and "yt-dlp returned no info" above/below; this is that
    same family, just carrying yt-dlp's own message and a classified
    `reason`) -- when a metadata-only yt-dlp check confirms THIS SPECIFIC
    video can't be resolved right now, for one of the reasons
    `classify_unavailability()` recognizes.

    `reason` is one of "gone", "private", "terminated" (all PERMANENT --
    see `PERMANENT_REASONS`) or "not_yet_started" (the one TEMPORARY
    case: a scheduled livestream that hasn't aired yet -- the same video
    resolves fine once it goes live, so this must never be recorded as a
    permanent failure). `check_permanent_failure()` and
    `archive/db/crud.py`'s marker logic key off `is_permanent`, not just
    "did this raise".

    WO-167, 2026-09-10: replaces the previous behavior (WO-135) of
    quietly degrading a permanently-gone video to a "successful" empty
    `ResolvedMeeting` carrying only a `transcript_warnings` marker -- see
    `_GONE_SIGNATURES`'s own comment above for the real gap that caused.
    Raising means every existing `except Exception`/broad-catch call site
    across this app (`main.py`'s `/api/resolve`, the tier-3 ingest
    scripts' `process_row()`) already treats this the same way it treats
    every other "can't resolve this URL" failure, with no new code
    needed at any of them.
    """

    PERMANENT_REASONS = ("gone", "private", "terminated")

    def __init__(self, video_id: str, yt_dlp_message: str, reason: str):
        self.video_id = video_id
        self.yt_dlp_message = yt_dlp_message
        self.reason = reason
        super().__init__(
            f"YouTube video {video_id} is {reason.replace('_', ' ')}: {yt_dlp_message}"
        )

    @property
    def is_permanent(self) -> bool:
        return self.reason in self.PERMANENT_REASONS


class YouTubeAssetFinder(AssetFinder):
    """Resolves a standalone YouTube URL -- or a video id handed to it
    directly by a delegating platform (PrimeGov) -- into video + transcript.

    Real, confirmed constraints from live investigation (2026-08-07):
    - There's no direct playable video file URL for YouTube, unlike every
      other platform here. Playback needs an embedded iframe + the
      YouTube IFrame Player API (see player.js's "youtube" video_format
      branch), not the native <video>/hls.js pathway.
    - Caption *content* download is blocked for plain HTTP requests --
      every caption URL YouTube hands out returned 200 OK with 0 bytes
      across 5 different request shapes tried live (aiohttp/curl, with a
      real browser User-Agent, cross-origin fetch, same-origin fetch from
      youtube.com itself, freshly-signed same-session URLs). yt-dlp's own
      request handling works reliably (confirmed against a real
      5985-second LA City Council meeting, 570KB of real captions) -- it
      evidently works around whatever's blocking bare HTTP clients, so
      caption fetching goes through yt-dlp's `urlopen()`, not our own
      aiohttp session.
    - yt-dlp needs to stay reasonably current or extraction may silently
      break -- it's under active, frequent maintenance specifically
      because YouTube keeps changing things to block scraping. Left
      unpinned (latest) in requirements.txt for this reason.
    - YouTube's auto-generated (and, per a real sample, also its manual/
      CC-sourced) VTT uses a "roll-up" cue style, not one cue per line --
      see `dedupe_rollup_cues()` in vtt_parser.py.
    - **yt-dlp can fail entirely** (confirmed live 2026-08-09: YouTube's
      anti-bot check blocking Render's server IP outright, independent
      of which internal client is used) **without losing the video
      itself** -- `resolve_video_id()` degrades to a playable-but-no-
      metadata/no-captions `ResolvedMeeting` rather than raising, since
      embedding only ever needed the video id (a plain string, no
      network call), never yt-dlp. This is also why a delegating
      adapter with its own metadata (`lims.py` parses Minneapolis's own
      agenda page for title/date/jurisdiction, and its own JSON endpoint
      for the video id and real per-item timestamps -- none of that
      touches YouTube at all) still works close to fully even when
      yt-dlp itself is completely blocked -- only the transcript is
      genuinely unavailable in that case.
    """

    platform_name = "youtube"

    @staticmethod
    def extract_video_id(url: str) -> Optional[str]:
        return extract_video_id(url)

    async def resolve(self, url: str) -> ResolvedMeeting:
        video_id = self.extract_video_id(url)
        if not video_id:
            raise ValueError(f"Could not find a YouTube video ID in {url}")
        return await self.resolve_video_id(video_id, source_url=url)

    @classmethod
    async def resolve_video_id(cls, video_id: str, source_url: str) -> ResolvedMeeting:
        """Shared entry point for both a direct YouTube URL and a
        delegating platform that already extracted the video id."""
        video_url = f"https://www.youtube.com/embed/{video_id}"

        try:
            info = await asyncio.to_thread(cls._extract_info, video_id)
        except yt_dlp.utils.YoutubeDLError as e:
            reason = classify_unavailability(str(e))
            if reason:
                # WO-167, 2026-09-10: a real, confirmed-classified failure
                # (gone/private/terminated -- permanent; not_yet_started --
                # temporary) is a different, specific answer from "YouTube
                # is blocking us right now" below -- see
                # classify_unavailability()'s own docstring for the real
                # yt-dlp message shapes this was verified against. Raising
                # here (rather than WO-135's original "degrade to a
                # quiet, marker-carrying empty success") means a caller
                # that only checks "did resolve() raise" -- which is most
                # of them -- can no longer mistake a genuinely-gone video
                # for "no captions yet". Callers that specifically need
                # the permanent-vs-temporary marker distinction
                # (scripts/fetch_youtube_transcripts.py, archive/db/
                # crud.py) use check_permanent_failure() instead, which
                # never raises and still returns the exact
                # YOUTUBE_VIDEO_UNAVAILABLE_MARKER text unchanged.
                logger.info(
                    "YouTube video %s is %s: %s", video_id, reason, str(e)[:200]
                )
                raise YouTubeUnavailableError(video_id, str(e), reason) from e
            # Real production incident, 2026-08-09: YouTube's anti-bot
            # check ("Sign in to confirm you're not a bot") blocks
            # Render's server IP outright, regardless of which internal
            # yt-dlp client is used (confirmed live -- see BACKLOG.md,
            # the player_client workaround in _extract_info() below
            # didn't help). Previously this raised and killed the whole
            # resolve -- but playback itself needs *nothing* from yt-dlp,
            # just this video id (the embed URL above is pure string
            # formatting, no network call) -- the same insight behind
            # this repo's whole "no direct video file URL, playback is
            # always an iframe embed" design. Degrade instead: return a
            # real, playable ResolvedMeeting with no title/date/captions
            # rather than no meeting at all. This also means a delegating
            # adapter with its own metadata (e.g. lims.py's own agenda-
            # page parsing) still gets to use it -- resolve_video_id()
            # failing outright previously threw that away too, even when
            # the caller already had it in hand.
            #
            # Widened from the original bare `yt_dlp.utils.DownloadError`
            # to its base `YoutubeDLError` 2026-08-29, after live-
            # reproducing a second, distinct real failure this shape
            # applies to: `_pick_caption_track()`'s own `ydl.urlopen(...)
            # .read()` call for the caption track file raises a plain
            # `yt_dlp.networking.exceptions.HTTPError` (429 Too Many
            # Requests) on its own, uncaught by `extract_info()`'s own
            # error handling since it's a direct network call the
            # extractor makes afterward, not part of extraction itself --
            # confirmed live against two real videos, a week after the
            # 2026-08-22 bulk-resolve IP-block incident (BACKLOG.md),
            # meaning the caption endpoint is still (or newly) blocking
            # this session's IP regardless of request pacing. Both
            # `DownloadError` and `HTTPError` share this common base, and
            # any other yt_dlp-raised failure mode does too -- catching
            # the base class means a future one degrades the same way
            # instead of crashing the whole resolve again.
            return ResolvedMeeting(
                platform=cls.platform_name,
                source_url=source_url,
                external_id=f"youtube:{video_id}",
                video_url=video_url,
                video_format="youtube",
                video_warnings=[
                    "YouTube is currently blocking automated caption requests from our server, so "
                    "no transcript is available for this video — but it should still play fine "
                    "above."
                ],
                transcript_warnings=[
                    "No transcript available — YouTube is currently blocking caption requests from "
                    "our server."
                ],
            )
        if not info:
            raise ValueError(
                f"YouTube video {video_id} could not be resolved (no info returned by yt-dlp)."
            )

        video_warnings: List[str] = []
        transcript_warnings: List[str] = []

        # Real bug fixed 2026-08-12: yt-dlp's "upload_date" is consistently
        # one day late for a government meeting streamed live and archived
        # (confirmed on two independent real samples -- Columbus, OH and
        # Oklahoma City, both was_live=True -- see BACKLOG_DONE.md) since it
        # reflects when the VOD finished processing, not when the meeting
        # actually happened. "release_date" (the live broadcast's own start
        # date) matched the real meeting date on both samples instead --
        # preferred here, falling back to upload_date for a plain
        # never-live upload where release_date isn't set at all. This was
        # previously worked around per-adapter (see primegov.py's own page-
        # text date extraction) rather than fixed at the root; this fix
        # benefits every adapter that delegates to YouTubeAssetFinder
        # (direct YouTube URLs, SLC, LIMS, Mesa/Albuquerque's Legistar
        # delegation), not just PrimeGov.
        #
        # WO-285, 2026-09-12: neither of the two above is actually
        # reliable for a video whose own title states the real date --
        # see the module-level comment above _parse_meeting_date_from_
        # title() for the audit that found this at scale (54% of pages
        # with a parseable title date disagreed with the release_date-
        # preferring result this block used to compute on its own). The
        # title's own stated date now wins first; release_date/
        # upload_date remain the fallback, unchanged, for the common case
        # where the title carries no parseable date at all.
        raw_date = info.get("release_date") or info.get(
            "upload_date"
        )  # YYYYMMDD or None
        date = _parse_meeting_date_from_title(info.get("title"))
        if not date and raw_date and len(raw_date) == 8:
            date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"

        segments: List[TranscriptSegment] = []
        transcript_language: Optional[str] = None

        track = info.get("_chosen_track")
        if track:
            raw_bytes, lang, is_manual = track
            content = decode_vtt_bytes(raw_bytes)
            cues = dedupe_rollup_cues(parse_vtt(content))
            if cues:
                segments = [TranscriptSegment(**c) for c in cues]
                transcript_language = lang
                if lang and lang != TARGET_LANGUAGE:
                    transcript_warnings.append(
                        f"These captions appear to be in '{lang}', not '{TARGET_LANGUAGE}' — "
                        "no matching-language track was found for this video."
                    )
                if not is_manual:
                    transcript_warnings.append(
                        "These are YouTube's auto-generated captions, not a human "
                        "transcript — expect occasional errors, especially with names "
                        "and technical terms."
                    )
                if is_likely_garbled(cues, lang=lang):
                    transcript_warnings.append(
                        "This transcript looks garbled at the source (not a parsing "
                        "bug on our end) — treat it as approximate."
                    )
        if not segments:
            # WO-135, 2026-09-09: `info["no_captions_at_all"]` (set in
            # _extract_info() below) is True only when yt-dlp's raw
            # `subtitles`/`automatic_captions` are BOTH completely empty --
            # no caption track in ANY language, not just none in
            # TARGET_LANGUAGE. That is the real, channel-level "captions
            # are disabled" signal (matching youtube-transcript-api's own
            # TranscriptsDisabled, confirmed by scripts/
            # fetch_youtube_transcripts.py's own precheck); a video with
            # captions in some other language only still hits the more
            # generic message below, since captions clearly aren't
            # disabled there.
            if info.get("no_captions_at_all"):
                transcript_warnings.append(YOUTUBE_CAPTIONS_DISABLED_MARKER)
            else:
                transcript_warnings.append("No captions found on this video.")

        # WO-135, 2026-09-09: `playable_in_embed` is yt-dlp's own signal for
        # whether the uploader has restricted this video to be unplayable
        # inside a third-party iframe -- exactly what our own player.js
        # embed does. Explicitly `False`, not falsy/missing: yt-dlp omits
        # the key entirely for some extractions rather than asserting True,
        # and "unknown" must not be treated as "disabled".
        if info.get("playable_in_embed") is False:
            video_warnings.append(YOUTUBE_EMBED_DISABLED_MARKER)

        return ResolvedMeeting(
            platform=cls.platform_name,
            source_url=source_url,
            external_id=f"youtube:{video_id}",
            title=info.get("title"),
            date=date,
            jurisdiction=cls._jurisdiction(info.get("uploader")),
            video_channel=cls._channel_handle(info),
            video_channel_id=(info.get("channel_id") or None),
            video_url=video_url,
            video_format="youtube",
            segments=segments,
            transcript_language=transcript_language,
            video_warnings=video_warnings,
            transcript_warnings=transcript_warnings,
        )

    @classmethod
    def check_permanent_failure(
        cls, video_id: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Returns (transcript_marker, video_marker) -- either or both
        `None` when nothing permanent is confirmed. WO-135, 2026-09-09:
        lets a caller check BEFORE attempting a real transcript fetch
        (scripts/fetch_youtube_transcripts.py) whether a video is a known
        permanent failure, reusing the exact same metadata-only yt-dlp
        extraction (`_extract_info()`, `skip_download=True`) and
        classification (`classify_unavailability()`) resolve_video_id()
        itself uses above -- one source of truth for what counts as
        "permanent", and zero extra request/rate-limit cost beyond the
        single metadata call already needed either way (no captions are
        actually downloaded here).

        Unlike resolve_video_id(), this never raises `YouTubeUnavailableError`
        -- it keeps its original (marker_or_None, marker_or_None) contract
        so its one caller (fetch_youtube_transcripts.py) doesn't need a
        try/except added for a check that's explicitly meant to run
        before any real fetch is attempted.

        Synchronous, like `_extract_info()` -- callers already running
        inside an event loop should wrap this in `asyncio.to_thread()`
        (resolve_video_id() does; a plain sequential script like
        fetch_youtube_transcripts.py can call it directly, same as it
        already does for the synchronous youtube-transcript-api calls).
        """
        try:
            info = cls._extract_info(video_id)
        except yt_dlp.utils.YoutubeDLError as e:
            reason = classify_unavailability(str(e))
            if reason in YouTubeUnavailableError.PERMANENT_REASONS:
                return YOUTUBE_VIDEO_UNAVAILABLE_MARKER, None
            # Not-yet-started (temporary, never a permanent marker),
            # ambiguous, or a server-IP block signal -- let the real
            # fetch attempt (or the resolver's own resolve()) make the
            # call rather than guessing here.
            return None, None
        if not info:
            return None, None
        transcript_marker = (
            YOUTUBE_CAPTIONS_DISABLED_MARKER if info.get("no_captions_at_all") else None
        )
        video_marker = (
            YOUTUBE_EMBED_DISABLED_MARKER
            if info.get("playable_in_embed") is False
            else None
        )
        return transcript_marker, video_marker

    @staticmethod
    def _channel_handle(info: dict) -> Optional[str]:
        """The channel's public handle ("@TownofWoodside"), the key a
        `tenant_overrides.csv` `match=channel=@Handle` row is written
        against -- the same value YouTube's oEmbed `author_url` ends in,
        which is what `scripts/study_shared_host_discriminators.py` learned
        the 635 channel rules from. yt-dlp spells it two ways depending on
        version: `uploader_id` is the bare handle on current releases, and
        `uploader_url` / `channel_url` carry it as the last path segment.
        None when neither is handle-shaped (an old numeric uploader id, or
        a channel with no handle) -- `video_channel_id` still carries the
        permanent UC id in that case."""
        uploader_id = (info.get("uploader_id") or "").strip()
        if uploader_id.startswith("@"):
            return uploader_id
        for key in ("uploader_url", "channel_url"):
            tail = (info.get(key) or "").rstrip("/").rsplit("/", 1)[-1].strip()
            if tail.startswith("@"):
                return tail
        return None

    @staticmethod
    def _jurisdiction(uploader: Optional[str]) -> Optional[str]:
        """yt-dlp's `uploader` is a YouTube *channel* name, not a
        jurisdiction -- real values range from "Roosevelt City" (usable
        as-is) through "cityofokc" (glued, needs splitting) to "CivicPlus"
        or "Hamden Action NOW" (a vendor's own channel or an unrelated
        community org, not the government at all -- real, confirmed-live
        examples of a tenant's page linking the wrong video entirely, see
        BACKLOG_DONE.md's 2026-08-27 CivicPlus entry). Every other
        adapter here that reads a bare account/channel name
        (`vimeo.py`'s `_jurisdiction()` is the direct model this mirrors)
        runs it through `validated_label_extract()` before trusting it;
        this one didn't, so a channel name flowed straight onto the page
        with zero validation -- confirmed live: the CivicPlus incident's
        page would have shown "jurisdiction: CivicPlus" verbatim had it
        not been caught and removed by hand.

        `validated_label_extract()` alone isn't quite enough here, unlike
        Vimeo: real YouTube channel names for small governments are often
        already a full, well-formed "Village of X, State" string (e.g.
        "Village of Angel Fire, New Mexico"), which that function -- built
        for a single glued subdomain-shaped token, never a comma or a
        multi-word state name -- rejects outright. So a name that already
        looks like "X, State" is checked directly instead: real only if
        the part before the comma independently validates as a real place
        or county on its own (`lookup_city_state()`/`lookup_county_state()`,
        both of which already strip a leading "City of"/"Village of"/etc.
        internally), OR the part AFTER the comma is itself a real state/
        province that genuinely lists the name (`resolve_claimed_state()`,
        added WO-70 2026-08-30 for BACKLOG.md's "already 'X, State'-shaped"
        entry) -- e.g. "Village of Angel Fire, New Mexico" validates via
        the first path (Angel Fire is nationally unambiguous), while
        "City of Medina, Minnesota" needed the second (Medina alone is
        ambiguous across 6 states, but the source text already names the
        real one). Everything else goes through the glued-label path,
        same as Vimeo -- including the same confirmed-real institutional-
        suffix strip (`jurisdiction_enrich.strip_institutional_suffix()`,
        added 2026-08-29 for Vimeo's "Hopkins Public Schools"-shaped
        channel names), since a YouTube channel name is the identical kind
        of free-text account display name and the suffix is a national
        naming convention, not a Vimeo-specific quirk. Either path
        declines (returns None) rather than guessing -- most YouTube-
        direct resolves legitimately carry no jurisdiction at all, which
        is the honest outcome, not a bug (see vimeo.py's own docstring for
        the same reasoning).
        """
        name = (uploader or "").strip()
        if not name:
            return None
        if "," in name:
            base = name.split(",", 1)[0].strip()
            claimed_state = name.split(",", 1)[1].strip()
            if (
                jurisdiction_enrich.lookup_city_state(base)
                or jurisdiction_enrich.lookup_county_state(base)
                or jurisdiction_enrich.is_literal_known_place(base)
                or jurisdiction_enrich.resolve_claimed_state(base, claimed_state)
            ):
                return jurisdiction_enrich.enrich_jurisdiction_text(
                    name, netloc="youtube.com"
                )
            return None
        name = jurisdiction_enrich.strip_institutional_suffix(name)
        label = jurisdiction_enrich.validated_label_extract(name)
        if not label:
            return None
        # Keep the channel's own casing when it already validated as-is
        # (validated_label_extract() title-cases what it returns, built
        # for glued subdomain labels -- see that function's own docstring).
        if label.lower() == name.lower():
            label = name
        return jurisdiction_enrich.enrich_jurisdiction_text(label, netloc="youtube.com")

    @staticmethod
    def _extract_info(video_id: str) -> Optional[dict]:
        """Runs in a thread (yt-dlp is synchronous/blocking). Fetches
        metadata and picks the best available caption track, without
        downloading any video/audio."""
        ydl_opts = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            # Confirmed live 2026-08-09: YouTube's "Sign in to confirm
            # you're not a bot" anti-bot check hit our Render server IP
            # (yt-dlp was already current at the time, 2026.7.4 -- not a
            # stale-extractor issue). That check is tied to yt-dlp's
            # default "web" internal client, which requires a PO token we
            # don't have. android/ios/tv are yt-dlp's other internal
            # clients and have historically not enforced that same check
            # -- try them first, falling back to web only if none of them
            # returns anything usable. Not a guaranteed permanent fix
            # (YouTube tightens this periodically) -- see BACKLOG.md.
            "extractor_args": {
                "youtube": {"player_client": ["android", "ios", "tv", "web"]}
            },
            # False (not the original True) so a real failure raises a
            # real yt_dlp.utils.DownloadError instead of silently
            # returning None -- see resolve_video_id's try/except, and
            # BACKLOG.md for why "always guess removed/private/blocked"
            # was wrong.
            "ignoreerrors": False,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(
                f"https://www.youtube.com/watch?v={video_id}", download=False
            )
            if not info:
                return None

            result = {
                "title": info.get("title"),
                "uploader": info.get("uploader"),
                # WO-244 (2026-09-11): the four keys `_channel_handle()` and
                # `resolve_video_id()`'s `video_channel_id` read. #822 added
                # both readers but never added the keys to this trimmed
                # dict, so every YouTube page ingested since carried no
                # channel and every `channel=@handle` pin was inert for
                # YouTube (0 of 3,580 archived YouTube pages had a channel
                # in the 2026-09-11 export; Vimeo's 23 did).
                "uploader_id": info.get("uploader_id"),
                "uploader_url": info.get("uploader_url"),
                "channel_url": info.get("channel_url"),
                "channel_id": info.get("channel_id"),
                "upload_date": info.get("upload_date"),
                "release_date": info.get("release_date"),
                # Both read at zero extra request cost (WO-135) -- this is
                # the same metadata-only extract_info() call already made
                # for title/date/captions above, not a second network hit.
                "playable_in_embed": info.get("playable_in_embed"),
                # True only when NEITHER manual nor auto-generated captions
                # exist in ANY language -- see resolve_video_id()'s own
                # comment on why that's the real "channel disabled
                # captions" signal, distinct from "no TARGET_LANGUAGE
                # track".
                "no_captions_at_all": not (info.get("subtitles") or {})
                and not (info.get("automatic_captions") or {}),
            }
            chosen = YouTubeAssetFinder._pick_caption_track(ydl, info)
            if chosen:
                result["_chosen_track"] = chosen
            return result

    @staticmethod
    def _pick_caption_track(ydl, info: dict) -> Optional[Tuple[bytes, str, bool]]:
        """Returns (raw_bytes, language_code, is_manual) for the best
        available caption track, or None.

        Prefers a manual (non-ASR) track over auto-generated, but only
        when its coverage is comparable to the auto-generated one --
        confirmed live on a real meeting (LA City Council, 5/19/2021)
        where the "manual" CC track only starts at 18:49 into the video
        (likely a government CART feed that skips pre-meeting dead air),
        while the auto-generated track covers the full video from :01. A
        transcript with a 19-minute unlinkable gap at the start is a
        worse outcome for a deep-link tool than a slightly lower-quality
        but complete one, so manual is only used when it starts within
        60s of the auto-generated track's start.
        """
        manual = info.get("subtitles") or {}
        auto = info.get("automatic_captions") or {}

        auto_entry = YouTubeAssetFinder._vtt_entry(auto.get(TARGET_LANGUAGE, []))
        manual_key = next((k for k in manual if k.startswith(TARGET_LANGUAGE)), None)
        manual_entry = (
            YouTubeAssetFinder._vtt_entry(manual.get(manual_key, []))
            if manual_key
            else None
        )

        auto_bytes = ydl.urlopen(auto_entry["url"]).read() if auto_entry else None

        if manual_entry:
            manual_bytes = ydl.urlopen(manual_entry["url"]).read()
            if auto_bytes:
                auto_start = YouTubeAssetFinder._first_cue_start(auto_bytes)
                manual_start = YouTubeAssetFinder._first_cue_start(manual_bytes)
                if (
                    auto_start is not None
                    and manual_start is not None
                    and manual_start - auto_start > 60
                ):
                    return auto_bytes, TARGET_LANGUAGE, False
            return manual_bytes, TARGET_LANGUAGE, True

        if auto_bytes:
            return auto_bytes, TARGET_LANGUAGE, False

        # No target-language track at all -- fall back to any language,
        # preferring manual.
        for key, entries in manual.items():
            entry = YouTubeAssetFinder._vtt_entry(entries)
            if entry:
                return ydl.urlopen(entry["url"]).read(), key, True
        for key, entries in auto.items():
            entry = YouTubeAssetFinder._vtt_entry(entries)
            if entry:
                return ydl.urlopen(entry["url"]).read(), key, False

        return None

    @staticmethod
    def _vtt_entry(entries: list) -> Optional[dict]:
        return next((e for e in entries if e.get("ext") == "vtt"), None)

    @staticmethod
    def _first_cue_start(raw_bytes: bytes) -> Optional[float]:
        try:
            cues = parse_vtt(decode_vtt_bytes(raw_bytes))
            return cues[0]["start"] if cues else None
        except Exception:
            logger.warning(
                "YouTube first-cue-start parse failed on %d bytes",
                len(raw_bytes),
                exc_info=True,
            )
            return None
