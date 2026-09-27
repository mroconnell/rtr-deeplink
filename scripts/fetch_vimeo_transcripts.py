"""Fetch missing Vimeo transcripts from a residential/office IP and push
them into the Archive.

Why this exists (WO-1147, 2026-09-27; see BACKLOG.md's "Vimeo blocks
Render" entry): as of 2026-09-26, Render's own cloud IP gets a challenge
page (HTTP 401) on every Vimeo caption fetch, the same structural problem
YouTube has always had for this service. `app/platforms/vimeo.py`'s
`VimeoAssetFinder.resolve_video_id()` still works fine from an ordinary
residential/office IP (confirmed live 2026-09-27), so this module gives
Vimeo the same "local machine reads it, pushes to the Archive" treatment
scripts/fetch_youtube_transcripts.py already gives YouTube -- consuming
GET /internal/transcript-wanted?platform=vimeo and pushing results back
through the normal POST /internal/ingest every other transcript already
goes through.

Why this is a SEPARATE, SIMPLER module rather than a Vimeo branch inside
fetch_youtube_transcripts.py, and why it has no CLI `main()`/argparse the
way that file does: fetch_youtube_transcripts.py is also run daily,
standalone, via launchd (see docs/YOUTUBE_DRIP_RUNBOOK.md and that
script's own module docstring) specifically to work around
youtube-transcript-api's own IP-block history, independent of whether
scripts/youtube_drip.py's tick loop is even running. Vimeo has no such
standalone need -- there is no separate library here with its own
block-history to chase, no permanent-failure taxonomy to classify beyond
"has captions" / "doesn't" / "the request itself was challenged", and no
reason to run this off the drip's own schedule. This module exists purely
to be imported by scripts/youtube_drip.py's `lane_vimeo` (see that file),
the same way fetch_youtube_transcripts.py's own functions are already
reused by its `lane_captions`. A minimal `if __name__ == "__main__":`
block is deliberately not included.

Vimeo's own resolve is a single local async call
(`VimeoAssetFinder.resolve_video_id()`) rather than a separate library with
its own request budget, so there is no per-request rate-limit backoff
ladder here the way fetch_youtube_transcripts.py's
RATE_LIMIT_BACKOFF_SECONDS has -- a real Vimeo challenge is detected via
`classify_vimeo_block()` below (by watching this module's own logger for
the exact log line `app/platforms/vimeo.py` already emits on a real
challenge) and reported back to the caller as `status="blocked"`, which
scripts/youtube_drip.py's `lane_vimeo` treats as a reason to pause its
whole Vimeo lane, not just skip one page.
"""

import logging
from typing import List

import aiohttp

from app.platforms.vimeo import (
    _NO_CAPTIONS_WARNING,
    VIMEO_NO_CAPTIONS_CONFIRMED_MARKER,
    VimeoAssetFinder,
    parse_vimeo_video,
)
from scripts.fetch_youtube_transcripts import (
    _base_url,
    _headers,
    _ingest,
    _promote,
    _record_video_status,
)

# The exact substring app/platforms/vimeo.py's own
# `_fetch_captions_via_player_page_directly()` logs when the plain-fetch
# route's player-page GET is met with a real challenge (401/403/429) --
# see that method's `_log_caption_fallback(video_id, f"plain-fetch route:
# player page returned a challenge (HTTP {status})")` call. Matched
# case-insensitively, as a substring, not the whole message -- the message
# also names the HTTP status, which this doesn't need to know.
_CHALLENGE_LOG_SUBSTRING = "challenge"

INGEST_TIMEOUT = aiohttp.ClientTimeout(total=65)


async def _get_wanted(session: aiohttp.ClientSession) -> List[dict]:
    """GET /internal/transcript-wanted?platform=vimeo -- the Vimeo sibling
    of fetch_youtube_transcripts._get_wanted(), same response shape (a
    list of dicts with slug/title/platform/external_id/
    source_url_normalized/video_url -- see
    crud.list_youtube_pages_missing_transcripts()'s own docstring for why
    Vimeo pages return this identically)."""
    async with session.get(
        f"{_base_url()}/internal/transcript-wanted",
        headers=_headers(),
        params={"platform": "vimeo"},
        timeout=INGEST_TIMEOUT,
    ) as response:
        if response.status != 200:
            text = await response.text()
            raise RuntimeError(
                f"transcript-wanted?platform=vimeo failed ({response.status}): {text[:300]}"
            )
        data = await response.json()
        return data.get("pages", [])


def classify_vimeo_block(log_messages: List[str]) -> bool:
    """True if any of `log_messages` (text captured off the
    "rtr_deeplink.vimeo" logger during a `resolve_video_id()` call, see
    `process_one()` below) carries a real Vimeo challenge signal --
    app/platforms/vimeo.py's own `_log_caption_fallback()` line for the
    plain-fetch route hitting a 401/403/429 challenge,
    "player page returned a challenge (HTTP {status})". Case-insensitive
    substring match, since the exact status code varies.

    Known, documented gap (do not silently paper over this): when the
    HEADLESS-BROWSER route also gets challenged -- app/platforms/vimeo.py
    falls back to it whenever the plain-fetch route can't be used, see
    that module's docstring -- it logs "no <track> element found on
    player page" today, not a message containing "challenge". That
    message looks identical whether the browser was genuinely challenged
    or the page simply had no captions at all, so this detector currently
    only catches the plain-fetch route's own challenge, not a challenged
    headless-browser fallback. A video that hits that specific gap gets
    misclassified here as "no captions" (status="skipped", a permanent
    marker recorded) rather than "blocked" -- worth fixing if it turns out
    to matter in practice, but out of scope for this change (see
    BACKLOG.md's "Vimeo blocks Render" entry, which this module's
    docstring also points at)."""
    return any(_CHALLENGE_LOG_SUBSTRING in (msg or "").lower() for msg in log_messages)


# Both routes must positively agree before a page is marked "no captions"
# for good (WO-1147 review, 2026-09-27): the plain fetch loaded the player
# page and found no text tracks, AND the headless browser loaded it and
# found no <track>. Anything else -- no browser, a timeout, an exception,
# a challenge on either route -- means we could not look, so the page is
# retried later instead of being settled wrongly. Strings are the real
# `_log_caption_fallback()` reasons in app/platforms/vimeo.py.
_PLAIN_ROUTE_NO_TRACKS = "plain-fetch route: no window.playerConfig text_tracks found"
_HEADLESS_ROUTE_NO_TRACK = "no <track> element found on player page"
_COULD_NOT_LOOK = (
    "challenge",
    "no headless browser available",
    "timed out",
    "raised",
    "returned http",
    "body was empty",
)


def confirmed_no_captions(log_messages: List[str]) -> bool:
    """True only when both caption routes looked and found nothing."""
    low = [(m or "").lower() for m in log_messages]
    if any(bad in m for m in low for bad in _COULD_NOT_LOOK):
        return False
    return any(_PLAIN_ROUTE_NO_TRACKS.lower() in m for m in low) and any(
        _HEADLESS_ROUTE_NO_TRACK.lower() in m for m in low
    )


class _CapturingHandler(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.WARNING)
        self.messages: List[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


async def process_one(
    session: aiohttp.ClientSession, page: dict, *, dry_run: bool
) -> dict:
    """Returns {"slug", "status": "ingested"|"skipped"|"blocked"|"failed",
    "detail"}. The extra "blocked" status (vs fetch_youtube_transcripts.
    process_one()'s three) is what tells the caller (scripts/youtube_drip.
    py's `lane_vimeo`) to pause the whole Vimeo lane rather than moving on
    to the next page -- a challenge is transient, not a permanent
    per-video fact, so nothing is marked on the page itself."""
    slug = page.get("slug", "?")
    parsed = parse_vimeo_video(page.get("video_url") or "")
    if parsed is None:
        return {
            "slug": slug,
            "status": "failed",
            "detail": f"no Vimeo video id in video_url={page.get('video_url')!r}",
        }
    video_id, privacy_hash = parsed

    logger = logging.getLogger("rtr_deeplink.vimeo")
    handler = _CapturingHandler()
    logger.addHandler(handler)
    try:
        try:
            resolved = await VimeoAssetFinder.resolve_video_id(
                video_id,
                privacy_hash=privacy_hash,
                source_url=page.get("source_url_normalized"),
            )
        except Exception as e:
            # resolve_video_id() itself shouldn't normally raise (its own
            # docstring), but a network error at the oEmbed-fetch layer
            # (plain aiohttp) is still a real possibility worth not
            # trusting blindly.
            return {
                "slug": slug,
                "status": "failed",
                "detail": f"{type(e).__name__}: {str(e)[:200]}",
            }
    finally:
        logger.removeHandler(handler)

    if classify_vimeo_block(handler.messages):
        first_match = next(
            (
                m
                for m in handler.messages
                if _CHALLENGE_LOG_SUBSTRING in (m or "").lower()
            ),
            "",
        )
        return {"slug": slug, "status": "blocked", "detail": first_match}

    if resolved.segments:
        if dry_run:
            return {
                "slug": slug,
                "status": "skipped",
                "detail": f"[dry-run] would push {len(resolved.segments)} segments",
            }
        payload = {
            "platform": page["platform"],
            "source_url": page["source_url_normalized"],
            "external_id": page.get("external_id"),
            "video_url": page.get("video_url"),
            "video_format": "vimeo",
            "segments": [s.model_dump() for s in resolved.segments],
            "transcript_language": resolved.transcript_language,
        }
        response = await _ingest(session, payload, page["source_url_normalized"])
        page_url = response.get("url", "")
        version_id = response.get("version_id")
        promote_detail = ""
        if version_id is not None:
            # A fresh, genuinely-fetched real Vimeo caption track is
            # unconditionally more trustworthy than whatever's already
            # flagged bad on the page (the same reasoning
            # fetch_youtube_transcripts._promote()'s own docstring gives
            # for YouTube) -- always promote and clear stale warnings,
            # never gate this behind a flag.
            await _promote(session, response.get("slug", slug), version_id)
            promote_detail = " (promoted to default)"
        return {
            "slug": slug,
            "status": "ingested",
            "detail": (
                f"{len(resolved.segments)} segments "
                f"(language={resolved.transcript_language}) -> {page_url}{promote_detail}"
            ),
        }

    # No segments, and not blocked -- a confirmed real "this video has no
    # captions" outcome (resolve_video_id() sets its own _NO_CAPTIONS_
    # WARNING onto transcript_warnings in exactly this case; checked via
    # membership rather than re-deriving the string).
    no_captions = _NO_CAPTIONS_WARNING in (
        resolved.transcript_warnings or []
    ) and confirmed_no_captions(handler.messages)
    if not no_captions:
        # Some other warning path (e.g. the domain-restricted-embed case)
        # -- not a confirmed no-captions outcome, so don't record a
        # permanent marker for it.
        return {
            "slug": slug,
            "status": "failed",
            "detail": f"no segments and not a confirmed no-captions outcome "
            f"(retried later): {resolved.transcript_warnings!r}; "
            f"routes: {handler.messages!r}",
        }

    if dry_run:
        return {
            "slug": slug,
            "status": "skipped",
            "detail": "[dry-run] would record permanent no-captions marker",
        }
    recorded = await _record_video_status(
        session, slug, transcript_marker=VIMEO_NO_CAPTIONS_CONFIRMED_MARKER
    )
    outcome = (
        "will never be re-queued"
        if recorded
        else "FAILED TO RECORD marker, will be retried tomorrow"
    )
    return {
        "slug": slug,
        "status": "skipped",
        "detail": f"recorded permanent no-captions marker -- {outcome}",
    }
