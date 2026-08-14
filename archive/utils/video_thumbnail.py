"""YouTube thumbnail derivation for meeting pages.

YouTube-backed pages are the one video source with a free, predictable
thumbnail (i.ytimg.com serves hqdefault.jpg for every video -- no API
call, no image generation). That makes them the cheapest first slice of
the missing-thumbnailUrl gap flagged by Google Search Console (see
BACKLOG.md's "Videos structured-data issues" entry -- a missing
thumbnailUrl blocks video rich-result eligibility outright). Direct
mp4/m3u8 sources would need real ffmpeg frame extraction and are
deliberately not handled here yet.
"""

import re
from typing import Optional

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
