"""Pure YouTube video-id extraction -- no `yt_dlp` import, no network calls.

Why this module exists (WO-250, 2026-09-12): `app/platforms/youtube.py`
imports `yt_dlp` at module level (line 6), so merely importing that module
-- even just to reach the one pure regex method,
`YouTubeAssetFinder.extract_video_id()` -- requires `yt_dlp` to be
installed. The resolver (`app/`) and the transcription `worker/` both
carry `yt-dlp` in their requirements; the Archive service
(`archive/requirements.txt`) deliberately does not, since Archive never
calls YouTube itself. `scripts/backfill_video_channel.py` is meant to run
from the Archive's Render shell (see CLAUDE.md's standing decision on
running bulk DB writes local to the database) and crashed there with
`ModuleNotFoundError: No module named 'yt_dlp'` at the
`from app.platforms.youtube import YouTubeAssetFinder` line, even though
it only ever calls `extract_video_id()`.

`_VIDEO_ID_RE`/`extract_video_id()` live here now; `youtube.py` imports
and re-exports both (`YouTubeAssetFinder.extract_video_id` delegates to
the function below) so every existing caller and test keeps working
unchanged. Anything that only needs id extraction -- like the backfill
script -- should import from here instead of `app.platforms.youtube`, to
stay free of the `yt_dlp` dependency.
"""

import re
from typing import Optional

# WO-296, 2026-09-12: the id group used to have no end boundary, so a
# longer id-shaped path segment was silently truncated into a fake
# 11-char id instead of correctly finding no real id -- confirmed live
# (WO-195, 2026-09-11) on three real pages: `/embed/livestreaming`
# (Mount Vernon, TX) truncated to "livestreami", `/embed/videoseries?
# list=...` (a playlist embed, Daviess County, KY) read as "videoseries",
# and a Severn ON CivicWeb page produced a 20-character non-YouTube id
# through an unrelated path. The `(?![A-Za-z0-9_-])` negative lookahead
# below requires the id to be exactly 11 characters -- the next
# character (end of string, `?`, `&`, etc.) must not itself be a valid
# id character, or there's no match at that position.
# WO-303, 2026-09-12: `youtube-nocookie.com` added to the host
# alternation so `archive/db/crud.py` and `archive/utils/video_thumbnail.py`
# (both switched from their own duplicate regex to importing this module,
# BACKLOG.md's "Archive's two own copies" entry) don't lose coverage for
# it -- it's YouTube's real privacy-enhanced embed domain, already
# recognized separately by `app/platforms/generic_fallback.py`'s
# `_NOCOOKIE_EMBED_RE` and by both Archive regexes before this change.
_VIDEO_ID_RE = re.compile(
    r"(?:youtube(?:-nocookie)?\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/|live/|v/)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])"
)

# Real YouTube reserved literals that happen to also be exactly 11
# characters, so the end-boundary lookahead above doesn't catch them on
# its own (the character right after "videoseries"/"live_stream" is
# always a query-string separator like "?", never an id character).
# `videoseries` marks a playlist-only embed (`/embed/videoseries?
# list=...`, no single video id present); `live_stream` marks a
# not-yet-known live embed (`/embed/live_stream?channel=...`). Neither
# is a real video id -- both must return None, the same "no video id in
# this URL" signal a non-YouTube link already produces, not a fake id.
_RESERVED_NON_IDS = frozenset({"videoseries", "live_stream"})


def extract_video_id(url: str) -> Optional[str]:
    match = _VIDEO_ID_RE.search(url)
    if not match:
        return None
    video_id = match.group(1)
    if video_id in _RESERVED_NON_IDS:
        return None
    return video_id
