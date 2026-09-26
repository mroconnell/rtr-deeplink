"""One shared "re-resolve for transcription" step, used by all three real
transcription re-resolve callers (worker/main.py, scripts/bulk_queue_
transcription_backlog.py, scripts/transcribe_backlog_locally.py) -- see
CLAUDE.md's "two independent transcription paths" convention for why a
fix belongs in a shared module rather than three copies.

WO-1073 (2026-09-25): every one of those callers re-resolves a
MeetingPage from its OWN stored `source_url_normalized`, via
`get_finder(page.platform).resolve(source_url)`, before creating a
transcription job. For some real pages that stored URL is not something
the page's own platform adapter can actually parse, so the re-resolve
fails FOREVER -- the page just cycles through the auto-transcription
cooldown, never transcribed. Real case, confirmed live 2026-09-25:
Mary Esther, FL (Archive page id 11151, slug
mary-esther-fl-2026-09-08-regular-city-council-meeting, platform
civicclerk). Its `source_url_normalized` is the bare portal root
`https://maryestherfl.portal.civicclerk.com` (no event id in the path at
all), so `civicclerk.py`'s adapter raises "Could not find an event ID in
URL path: " on every single re-resolve. The page's stored `video_url`
(`https://cpmedia.azureedge.net/maryestherfl/1a1a01e3-6195-4f33-be2c-
4f0c7c235deb.mp4`) is real and playable, and it is exactly the media a
transcription job needs -- there was never anything wrong with the
MEDIA, only with re-deriving it from the stored source_url.

Root cause upstream (see scripts/feed_tier3_auto_transcription.py's own
WO-1073 fix): a tier-3 queue line paired a real CivicClerk event URL
with a bare-portal-root `source_url` override, and `_push_if_has_video()`
applied that override unconditionally, discarding the one URL its own
platform adapter could actually re-resolve.

**The fix here is the fallback half, not the upstream half**: even after
the upstream bug is fixed for new queue lines, ~46 already-ingested pages
(per the conductor's 2026-09-25 shape check over the full Archive corpus)
still carry a bad stored source_url today, and re-ingesting all of them
by hand isn't the point -- the transcription path should recover on its
own from a page whose stored URL its own adapter can't parse, as long as
a real, resolvable `video_url` is still sitting on the same row.
"""

import logging
from typing import Optional

from .base import detect_platform, get_finder
from .media_probe import transcription_media_url
from .models import ResolvedMeeting

logger = logging.getLogger("rtr_deeplink.reresolve")

# detect_platform() returns "youtube" for any youtube.com/youtu.be host --
# per CLAUDE.md's "YouTube is fetched only by the drip Mac" rule, this
# fallback must NEVER reach a YouTube URL, on any of the three callers
# (none of which run on the drip Mac). A YouTube-backed page is already
# excluded from the cloud worker's own candidate search
# (crud._youtube_permanent_transcript_failure_exists() /
# find_auto_transcription_candidate()'s docstring) -- this is a second,
# independent guard against the narrower case where a NON-YouTube page's
# stored `video_url` happens to itself be a YouTube link (which would
# otherwise look like a perfectly good fallback target).
_NEVER_FALL_BACK_TO = frozenset({"youtube", "unknown"})


async def reresolve_for_transcription(
    *, finder, platform: str, source_url: str, video_url: Optional[str] = None
) -> ResolvedMeeting:
    """Re-resolves a MeetingPage for transcription, the same way every
    caller already did (`finder.resolve(source_url)`, where `finder` is
    already `get_finder(platform)` -- callers keep doing that lookup
    themselves, outside this function, exactly as before, both because
    `get_finder()` raising is meant to stay a permanent, un-retried
    failure and because at least one caller (worker/main.py) still needs
    that same `finder` object afterward for the embedded-captions check,
    which is about the page's ORIGINAL platform, never this function's
    video_url fallback), but falls back to re-resolving the page's own
    stored `video_url` when that primary resolve either raises or comes
    back with no usable media (see `media_probe.transcription_media_url()`).

    The fallback re-resolves `video_url` through `detect_platform()` +
    that platform's own finder -- so a direct video/audio file or an HLS
    playlist (`app/platforms/direct_file.py`) works the same way a real
    platform page would, without a second, separate media-fetch code
    path. Never falls back to a YouTube video_url (see
    `_NEVER_FALL_BACK_TO` above) or to no video_url at all.

    On a successful fallback, the returned `ResolvedMeeting` has its
    `source_url` and `platform` fields reset back to this call's own
    `source_url`/`platform` arguments (the page's real, original values)
    before being returned -- **not** left as the fallback resolve's own
    `video_url`/its detected platform. This matters for two real,
    load-bearing reasons, not just tidiness:

    1. `archive/db/crud.py`'s `_find_or_create_page()`/`ingest_resolution()`
       match an existing page primarily by `source_url_normalized` (falling
       back from an external_id+platform match) -- if the fallback result's
       `source_url` were left pointing at the video file instead, the next
       ingest/job-creation call would fail to match this page and quietly
       create a DUPLICATE one instead of attaching to it.
    2. That same code path unconditionally trusts a fresh payload's
       `platform` on re-ingest ("Safe to always trust the fresh payload's
       platform" -- see that function's own 2026-08-16 comment) -- so
       leaving `platform` as the fallback's detected platform (e.g.
       "direct_file") would silently overwrite the page's real platform
       column, breaking every FUTURE re-resolve of this exact page for the
       same reason WO-1073 exists in the first place.

    Raises whatever the primary resolve raised (or, if the primary
    resolve returned successfully with no usable media and the fallback
    also found none, returns that no-media result) when no usable
    fallback exists -- callers see the exact same failure shape as before
    this function existed for a page with no working fallback.
    """
    primary_exc: Optional[Exception] = None
    result: Optional[ResolvedMeeting] = None
    try:
        result = await finder.resolve(source_url)
        if transcription_media_url(result):
            return result
        logger.info(
            "reresolve_for_transcription: primary resolve of %s (platform=%s) "
            "found no usable media, checking video_url fallback",
            source_url,
            platform,
        )
    except Exception as e:  # noqa: BLE001 -- re-raised below if no fallback works
        primary_exc = e
        logger.info(
            "reresolve_for_transcription: primary resolve of %s (platform=%s) "
            "raised %s: %s, checking video_url fallback",
            source_url,
            platform,
            type(e).__name__,
            e,
        )

    if not video_url:
        if primary_exc is not None:
            raise primary_exc
        return result  # the original no-media result -- same shape as before

    fallback_platform = detect_platform(video_url)
    if fallback_platform in _NEVER_FALL_BACK_TO:
        logger.info(
            "reresolve_for_transcription: not falling back to video_url %s for "
            "%s -- detected platform %r is never used as a fallback target",
            video_url,
            source_url,
            fallback_platform,
        )
        if primary_exc is not None:
            raise primary_exc
        return result

    try:
        fallback_finder = get_finder(fallback_platform)
        fallback_result = await fallback_finder.resolve(video_url)
    except Exception as e:  # noqa: BLE001
        logger.info(
            "reresolve_for_transcription: video_url fallback resolve of %s "
            "(platform=%s) also failed: %s: %s",
            video_url,
            fallback_platform,
            type(e).__name__,
            e,
        )
        if primary_exc is not None:
            raise primary_exc
        return result

    if not transcription_media_url(fallback_result):
        logger.info(
            "reresolve_for_transcription: video_url fallback resolve of %s "
            "(platform=%s) found no usable media either",
            video_url,
            fallback_platform,
        )
        if primary_exc is not None:
            raise primary_exc
        return result

    logger.info(
        "reresolve_for_transcription: %s (platform=%s) could not be re-resolved "
        "from its own stored source_url -- falling back to its stored video_url "
        "%s (platform=%s), restoring source_url/platform back to the page's own "
        "values before returning",
        source_url,
        platform,
        video_url,
        fallback_platform,
    )
    fallback_result.source_url = source_url
    fallback_result.platform = platform
    return fallback_result
