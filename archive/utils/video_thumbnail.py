"""Meeting-page thumbnails: the free YouTube one, and real ffmpeg frame
extraction for everything else.

**Two sources, in that order.** YouTube-backed pages have a free,
predictable thumbnail (i.ytimg.com serves hqdefault.jpg for every video
-- no API call, no extraction), and their stored `video_url` is an
iframe-embed URL ffmpeg could not read anyway, so they keep using it.
Every other page -- direct mp4/m3u8, i.e. the majority of the Archive --
now gets a real frame pulled out of its own video by ffmpeg and stored as
bytes (see archive/db/models.py's MeetingPageThumbnail), served by
GET /m/{slug}/card.jpg.

**Why this matters twice over.** A missing `thumbnailUrl` blocks video
rich-result eligibility outright, and on 2026-08-21 a real Google Search
Console URL Inspection of
/m/san-carlos-ca-2017-11-13-city-council-regular-meeting reported it as
the page's *only* remaining critical issue. Separately,
archive/utils/social.py auto-posts new pages to Bluesky and Mastodon, and
both build their link cards from OpenGraph tags -- so `og:image` coverage
is now real social reach, not only SEO.

**Which frame.** See target_offset_seconds() below -- the tiers exist
because "a few seconds in" is the one obviously wrong answer for this
content: government meeting recordings routinely open with several
minutes of dead air behind a static placeholder card, so an early frame
is frequently a literal blank slate.
"""

import asyncio
import hashlib
import logging
import re
import tempfile
from pathlib import Path
from typing import NamedTuple, Optional

from .video_formats import is_iframe_embed_format

logger = logging.getLogger("rtr_archive.video_thumbnail")

# Same 11-char video-id shape app/platforms/youtube.py matches, plus the
# /embed/ URL youtube.py itself builds as MeetingPage.video_url.
# Duplicated rather than imported across the app/archive service
# boundary, per this repo's existing convention (see
# archive/utils/clerk_auth.py's own header note).
_YOUTUBE_ID_RE = re.compile(
    r"(?:youtube(?:-nocookie)?\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/|live/)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})"
)


def youtube_thumbnail_url(video_url: Optional[str]) -> Optional[str]:
    """The predictable i.ytimg.com thumbnail for a YouTube video URL, or
    None for a missing/non-YouTube URL (m3u8/mp4 pages get no thumbnail
    today). hqdefault.jpg (480x360) exists for every video, unlike
    maxresdefault.jpg, which 404s on many older/lower-res uploads.
    """
    if not video_url:
        return None
    match = _YOUTUBE_ID_RE.search(video_url)
    if not match:
        return None
    return f"https://i.ytimg.com/vi/{match.group(1)}/hqdefault.jpg"


# --- Which frame to grab -------------------------------------------------

# How far *after* a shared `?t=` to grab the frame. A share link points at
# the moment someone cared about; the frame reads better a beat later,
# inside the relevant content, rather than on the transition into it (a
# gavel, a name being read, a slide still changing).
#
# Raised 20 -> 30 on 2026-08-24, from a real card. A San Diego public
# comment landed on the speaker while the camera was still refocusing
# from the dais, and the reason is structural rather than bad luck: a
# search snippet deliberately starts a beat *before* the interesting
# line (see _context_window() in crud.py), and a chamber operator needs
# a few seconds to find and focus a new speaker after they start
# talking. Both push the same direction, so the lead has to clear both.
#
# Interacts with OFFSET_BUCKET_SECONDS below: the frame actually lands
# in (t + LEAD - 20, t + LEAD], so 20 meant "0-20s after" (~10s on
# average) and 30 means "10-30s after" (~20s). Any value >= the bucket
# still guarantees the frame is never taken *before* the shared moment,
# which is the property that matters.
#
# Applied uniformly rather than tuned per meeting on purpose: there is
# no per-page override anywhere in this module, a card is derived from
# `?t=` alone, and hand-shifting individual meetings would need storage,
# an editing surface, and someone to look at every card. A single
# constant is the only lever that scales -- if it is wrong it is wrong
# everywhere at once, which is also the cheapest kind of wrong to fix.
#
# Changing it re-maps which bucket a given `?t=` resolves to, so already-
# stored frames stop being the answer for those timestamps and get
# re-extracted once each. That degrades safely -- the card route serves
# the page's default frame and queues the precise one (see
# meeting_card_image()) -- but a page already at MAX_FRAMES_PER_PAGE
# simply keeps serving its default frame for new timestamps. Worth
# knowing before treating this as a free dial.
TIMESTAMP_LEAD_SECONDS = 30
# How far before the END of the video the default (no-timestamp) frame is
# taken from. Ryan's call, and the reasoning is specific to this content:
# meetings routinely open behind a static "meeting will begin shortly"
# placeholder for several minutes, so any early offset is often a literal
# blank slate, whereas near the end there is reliably a real chamber with
# real people in it.
TAIL_LEAD_SECONDS = 300
# Below this, "300s before the end" stops meaning "near the end of a long
# meeting" and starts meaning "somewhere near the beginning" (or a
# negative offset outright), so the halfway tier takes over.
MIN_DURATION_FOR_TAIL_SECONDS = 600
# Used only when ffprobe could not tell us a duration at all (unreachable
# source, a stream that reports none). "Halfway" is not computable without
# one, so this is the honest floor: 10 minutes in, past the placeholder
# dead air the tail rule exists to avoid, and safely inside any recording
# long enough to be a real meeting (media_probe.MIN_PLAUSIBLE_MEETING_
# SECONDS is 5 minutes).
UNKNOWN_DURATION_OFFSET_SECONDS = 600
# `?t=` comes from a public URL, so its distinct values are unbounded --
# and each distinct resolved offset is one stored row and one ffmpeg run.
# Quantizing the timestamp tier to 20s buckets collapses a crawl over many
# near-identical deep links into a handful of real extractions. 20 rather
# than a rounder 30 for an exact reason: bucket(t + 20) always lands in
# (t, t + 20], i.e. never *before* the moment that was shared, which a
# coarser bucket would sometimes do.
OFFSET_BUCKET_SECONDS = 20


def target_offset_seconds(
    *, timestamp: Optional[int] = None, duration: Optional[float] = None
) -> int:
    """Which second of the video the card frame should come from.

    Three tiers, in priority order:

    1. **A shared timestamp wins.** `?t=N` on the share URL means someone
       chose that moment, so the card shows `N + TIMESTAMP_LEAD_SECONDS`
       (bucketed -- see OFFSET_BUCKET_SECONDS).
    2. **Otherwise, near the end**: `duration - TAIL_LEAD_SECONDS`, for
       the dead-air reason in TAIL_LEAD_SECONDS' comment.
    3. **Otherwise halfway**, when the video is too short for (2) to mean
       anything -- or a fixed UNKNOWN_DURATION_OFFSET_SECONDS when there
       is no duration at all, since "halfway" is not a computable answer
       without one.

    Pure and total: always returns a non-negative int, never probes,
    never raises. Frame-accuracy is irrelevant to all three tiers, which
    is what lets the extractor use ffmpeg's fast input-side `-ss` (see
    media_probe.extract_frame()).
    """
    if timestamp is not None and timestamp >= 0:
        raw = int(timestamp) + TIMESTAMP_LEAD_SECONDS
        return (raw // OFFSET_BUCKET_SECONDS) * OFFSET_BUCKET_SECONDS
    if duration is not None and duration >= MIN_DURATION_FOR_TAIL_SECONDS:
        return int(duration) - TAIL_LEAD_SECONDS
    if duration is not None and duration > 0:
        return int(duration // 2)
    return UNKNOWN_DURATION_OFFSET_SECONDS


def is_extractable(video_url: Optional[str], video_format: Optional[str]) -> bool:
    """True when there is a real media file ffmpeg could open. False for a
    page with no video, and for every iframe-embed platform -- their
    stored `video_url` is a player *page*, not media (the same structural
    reasoning app/main.py's _unreadable_media_message() uses to say such a
    meeting can't be self-transcribed).

    Gated on IFRAME_EMBED_VIDEO_FORMATS rather than "youtube" alone since
    2026-08-22. The YouTube-only form was written when YouTube was the
    only embed platform and never revisited when vimeo.py (WO-29) and
    viebit.py landed, so this returned True for both -- verified live --
    and ffmpeg was handed an HTML page. That can only ever fail, and each
    failure landed in the meeting-card sweep's failure set, which is
    exactly what WO-42's per-page failure reasons exist to make readable.

    The URL-shape check stays as a second line of defence: a page whose
    video_format was never set (or set wrong) but whose URL is plainly a
    YouTube link is still not extractable.
    """
    if not video_url:
        return False
    if is_iframe_embed_format(video_format) or _YOUTUBE_ID_RE.search(video_url):
        return False
    return True


# --- Extraction, off the render path ------------------------------------

# Every extraction shells out to ffmpeg and pulls real bytes off a
# government CDN. Two independent limits keep a crawl over the whole
# archive from turning into a stampede on a single Render instance:
# at most _MAX_CONCURRENT_EXTRACTIONS running at once, and at most
# _MAX_QUEUED_EXTRACTIONS claimed-but-unfinished overall (beyond which
# new requests are simply dropped -- a page without a card yet is a
# normal, self-healing state, not an error worth queueing for).
_MAX_CONCURRENT_EXTRACTIONS = 2
_MAX_QUEUED_EXTRACTIONS = 40
_extraction_semaphore: Optional[asyncio.Semaphore] = None
# (page_id, offset) pairs currently claimed by a running task -- so N
# simultaneous requests for the same uncached card cost one ffmpeg run,
# not N.
_inflight: set[tuple[int, int]] = set()
# (page_id, offset) -> loop time of the last failure. A source that 403s,
# times out, or has been taken down would otherwise be retried on every
# single page render, forever.
_failed_at: dict[tuple[int, int], float] = {}
_FAILURE_COOLDOWN_SECONDS = 6 * 60 * 60
# Hard ceiling on stored frames per page, so an adversarial (or merely
# enthusiastic) crawl over many distinct `?t=` values can't grow one
# page's storage without bound. Past this, per-timestamp requests fall
# back to the page's default frame.
# Lowered 2026-08-25 (WO-60) from 12 to 3 to control database storage growth:
# 1200 pages × 3 thumbnails × ~75KB average = ~270MB vs ~1.4GB at the old limit.
MAX_FRAMES_PER_PAGE = 3


def _semaphore() -> asyncio.Semaphore:
    """Created lazily rather than at import: a module-level
    asyncio.Semaphore binds to whatever loop is current when it is
    constructed, and this module is imported by archive.main at import
    time -- before uvicorn's loop exists."""
    global _extraction_semaphore
    if _extraction_semaphore is None:
        _extraction_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_EXTRACTIONS)
    return _extraction_semaphore


def _now() -> float:
    return asyncio.get_running_loop().time()


def _cooling_down(key: tuple[int, int]) -> bool:
    failed_at = _failed_at.get(key)
    if failed_at is None:
        return False
    if _now() - failed_at < _FAILURE_COOLDOWN_SECONDS:
        return True
    _failed_at.pop(key, None)
    return False


class FrameOutcome(NamedTuple):
    """What one extract_and_store() call did, and -- when it produced no
    frame -- why (WO-42).

    A plain `(offset, reason)` tuple in the same shape as
    media_probe.extract_frame()'s own `(ok, reason)`, so the reason it
    already computes stops being logged-and-discarded and reaches the
    operator running a sweep. Before this, every failure path here
    returned a bare `None` and the only record of *why* was an Archive
    log line nobody correlates with a slug -- which is precisely what
    made the first production sweep's 179 failures undiagnosable (see
    BACKLOG_DONE.md's WO-37 residual).

    Three states, and `skipped` is what separates the two that look
    alike from the outside:

    * **stored** -- `offset` is the second the frame came from, `reason`
      is None.
    * **failed** -- `offset` is None, `reason` says what went wrong
      (usually straight from `extract_frame()`: an ffmpeg timeout, a
      non-zero exit with the CDN's own error in the stderr tail, ...).
      Something was really attempted against the source.
    * **skipped** -- `offset` is None, `skipped` is True, and *no work
      was done at all*: the frame is already being extracted by another
      task, this (page, offset) is inside its failure cooldown, or the
      process-wide queue is full. A caller must not treat these as
      evidence the source is bad -- scripts/backfill_meeting_cards.py
      would otherwise permanently blacklist a page it never tried.

    Being a tuple, `stored_offset, reason = await extract_and_store(...)`
    still reads naturally; `skipped` has a default so the two-field form
    is enough to construct either of the first two states.
    """

    offset: Optional[int]
    reason: Optional[str] = None
    skipped: bool = False

    @property
    def stored(self) -> bool:
        return self.offset is not None


# The exact reason strings this module produces on its own (everything
# else is passed through verbatim from media_probe.extract_frame()).
# Named constants rather than inline literals because two other places
# match on them: the backfill endpoint's response and
# scripts/backfill_meeting_cards.py's reason bucketing.
SKIP_IN_FLIGHT = "skipped: an extraction for this frame is already in flight"
SKIP_QUEUE_FULL = "skipped: extraction queue full"
STORE_REJECTED = (
    "storage rejected the frame (already stored, per-page frame cap, "
    "or no thumbnails table)"
)
UNREPORTED_FAILURE = "extraction failed without reporting a reason"


def _skip_cooldown_reason() -> str:
    hours = _FAILURE_COOLDOWN_SECONDS // 3600
    return f"skipped: cooling down after an earlier failure (retried after {hours}h)"


async def extract_and_store(
    *,
    page_id: int,
    video_url: str,
    source_page_url: str,
    timestamp: Optional[int] = None,
) -> FrameOutcome:
    """Grab one frame for `page_id` and store it. Returns a FrameOutcome:
    the resolved offset on success, or a reason string on any failure or
    skip (see FrameOutcome for how those two differ and why it matters).

    **Never called from the template render path**, and that constraint
    is the whole shape of this function: it can run ffprobe *and* ffmpeg
    against a government CDN where a timeout is a routine outcome, not an
    exceptional one (see BACKLOG.md). Every caller is a FastAPI
    BackgroundTask (archive/main.py's ingest, meeting-page and card
    routes) or the /internal/thumbnails/backfill sweep -- all of which
    have already returned a response to the client by the time this runs.

    With no `timestamp` this produces the page's *default* frame (tier 2
    or 3), which needs the video's real duration and therefore one
    ffprobe call. With a `timestamp` no probe is needed at all -- tier 1
    is pure arithmetic on the shared offset, and an offset past the end
    of the video simply fails the extraction and degrades to the already-
    stored default frame, which is cheaper than probing up front to avoid.
    """
    from app.platforms import media_probe

    from ..db import crud

    if timestamp is None:
        duration = await media_probe.probe_duration(
            video_url, source_page_url=source_page_url
        )
        offset = target_offset_seconds(duration=duration)
    else:
        offset = target_offset_seconds(timestamp=timestamp)

    key = (page_id, offset)
    if key in _inflight:
        return FrameOutcome(None, SKIP_IN_FLIGHT, skipped=True)
    if _cooling_down(key):
        return FrameOutcome(None, _skip_cooldown_reason(), skipped=True)
    if len(_inflight) >= _MAX_QUEUED_EXTRACTIONS:
        logger.warning(
            "Thumbnail extraction queue full (%s in flight) -- skipping page %s @ %ss",
            len(_inflight),
            page_id,
            offset,
        )
        return FrameOutcome(
            None, f"{SKIP_QUEUE_FULL} ({len(_inflight)} in flight)", skipped=True
        )
    _inflight.add(key)
    try:
        async with _semaphore():
            # Re-check inside the semaphore: a task can wait here a while,
            # and a concurrent request (or the ingest warm) may have
            # stored this exact frame in the meantime.
            if await crud.get_thumbnail_meta(page_id, offset_seconds=offset):
                return FrameOutcome(offset)
            with tempfile.TemporaryDirectory(prefix="rtr-card-") as tmpdir:
                out_path = Path(tmpdir) / "card.jpg"
                ok, reason = await media_probe.extract_frame(
                    video_url,
                    offset=offset,
                    source_page_url=source_page_url,
                    out_path=out_path,
                )
                if not ok:
                    logger.info(
                        "No card frame for page %s @ %ss: %s", page_id, offset, reason
                    )
                    _failed_at[key] = _now()
                    # extract_frame() always supplies a reason today; the
                    # fallback keeps a future (False, None) from turning
                    # back into the bare, undiagnosable None this whole
                    # change exists to remove.
                    return FrameOutcome(None, reason or UNREPORTED_FAILURE)
                data = out_path.read_bytes()
        stored = await crud.store_thumbnail(
            page_id,
            offset_seconds=offset,
            image_bytes=data,
            etag=hashlib.sha256(data).hexdigest(),
            is_default=timestamp is None,
        )
        if not stored:
            return FrameOutcome(None, STORE_REJECTED)
        logger.info(
            "Stored card frame for page %s @ %ss (%s bytes)", page_id, offset, len(data)
        )
        return FrameOutcome(offset)
    except Exception as exc:
        # A thumbnail is decoration. Nothing here may ever escape into a
        # BackgroundTask and take down a request's response cycle.
        logger.exception("Card frame extraction blew up for page %s", page_id)
        _failed_at[key] = _now()
        return FrameOutcome(None, f"extraction raised {type(exc).__name__}: {exc}")
    finally:
        _inflight.discard(key)
