"""Video URLs that expire after ingest, and how to get a fresh one at
view time (WO-229).

Most platforms this app stores a `video_url` for are either a stable
iframe-embed page (see `video_formats.py`) or a stable, never-expiring
direct media URL. BoxCast is the first confirmed exception: its signed
HLS master playlist (`GET https://rest.boxcast.com/broadcasts/{id}/view`)
carries a real `Expires=`/`Signature=` query string and stops playing
once that time passes -- confirmed live on the two BoxCast pages
ingested 2026-09-11 (Livermore Falls ME, Bartow FL), whose stored
playlist expires 2026-09-13. See `app/platforms/boxcast.py`'s module
docstring for the full investigation.

Rather than re-ingesting a page every few days to refresh its stored
`video_url` (a standing sweep with no natural trigger and no way to know
ahead of time which pages need it), the meeting page route
(`archive/main.py`'s `/m/{slug}` and the `/m/{slug}/video` redirect it
points the player at) asks the platform for a fresh URL AT VIEW TIME,
for any page whose platform is in `NEEDS_REFRESH` below -- cached
briefly so a burst of views on one page costs at most one upstream call
per cache window, not one per view. A page whose platform isn't in this
set is completely untouched: its stored `video_url` is served directly,
exactly as before this WO.

**Why a redirect endpoint (design (b)) rather than resolving inline on
`/m/{slug}` (design (a)):** either works for BoxCast alone, but a
redirect the player always points at means a *future* expiring platform
needs no template change and no new route -- only a new entry in
`NEEDS_REFRESH`/`_REFRESHERS` below, plus its own `refresh(source_url)`
function on that platform's adapter. Resolving inline on `/m/{slug}`
would need that same dispatch repeated at both the page-render call site
and (for search-engine crawlers hitting the video URL directly rather
than the page) nowhere else, since a crawler never re-renders the page
template. A dedicated URL is also what a `<video>`/`<source src>`
element, `hls.js`, and a schema.org `contentUrl` can all point at
identically -- one target, not a value threaded through three render
paths.

Adding a future expiring platform means: add its platform name to
`NEEDS_REFRESH`, and give it a `refresh(source_url) -> Optional[str]`
entry in `_REFRESHERS`. Neither `archive/main.py`'s route nor
`meeting_page.html` needs to change.
"""

import time
from typing import Awaitable, Callable, Dict, Optional, Tuple

# Platforms whose stored `MeetingPage.video_url` can go stale after
# ingest -- checked by `archive/main.py` to decide whether the player
# should point at `/m/{slug}/video` (this module's redirect) instead of
# the raw stored URL. Every other platform's stored `video_url` is
# either an iframe-embed page or a plain, non-expiring media URL, so
# this set is deliberately small and additive.
NEEDS_REFRESH: frozenset = frozenset({"boxcast"})

# Keyed by the page's slug (stable across a refresh, unlike the signed
# URL itself) -- a few minutes is enough to collapse a burst of views on
# one page into one upstream BoxCast call, and short enough that a
# genuinely broken/rotated broadcast doesn't stay wrong for long.
_CACHE_TTL_SECONDS = 180.0
_cache: Dict[str, Tuple[float, str]] = {}


async def _refresh_boxcast(source_url: str) -> Optional[str]:
    # Lazy import, same convention as this file's siblings
    # (archive/main.py's own `from app.platforms.media_probe import
    # binary_versions`, archive/utils/meeting_inventory.py's
    # `from app.platforms.base import detect_platform`) -- the Archive
    # doesn't import the resolver's platform package at module load
    # time, only where a specific route actually needs it.
    from app.platforms.boxcast import refresh_playlist_url

    return await refresh_playlist_url(source_url)


_REFRESHERS: Dict[str, Callable[[str], Awaitable[Optional[str]]]] = {
    "boxcast": _refresh_boxcast,
}


async def fresh_video_url(
    platform: str, source_url: Optional[str], cache_key: str
) -> Optional[str]:
    """A freshly-resolved video URL for `platform`/`source_url`, or None
    immediately when `platform` isn't in `NEEDS_REFRESH` (nothing to
    refresh) or `source_url` is missing. Never raises -- a refresh
    failure (unknown broadcast, BoxCast API down, etc.) is just another
    None, and every caller here already treats None as "fall back to the
    page's last stored `video_url`", the same graceful-degradation
    posture the rest of this codebase uses for a source that's
    temporarily unreachable.
    """
    if platform not in NEEDS_REFRESH or not source_url:
        return None
    refresher = _REFRESHERS.get(platform)
    if refresher is None:
        return None

    now = time.monotonic()
    hit = _cache.get(cache_key)
    if hit and (now - hit[0]) < _CACHE_TTL_SECONDS:
        return hit[1]

    fresh = await refresher(source_url)
    if fresh:
        _cache[cache_key] = (now, fresh)
    return fresh
