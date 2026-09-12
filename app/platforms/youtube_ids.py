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

_VIDEO_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/|live/|v/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)


def extract_video_id(url: str) -> Optional[str]:
    match = _VIDEO_ID_RE.search(url)
    return match.group(1) if match else None
