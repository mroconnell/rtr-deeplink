"""A bare video file -- served straight from a government's own domain,
or from a file-sharing host (Dropbox, Google Drive) -- with no vendor
civic-meeting platform in front of it at all.

Built minimum, per WO-303 (2026-09-12), for two real, confirmed
BACKLOG.md gaps this repo's "test against a real URL first" rule already
required real samples for:

* **Own-domain / Dropbox** (WO-284's entry): `bulk_ingest.py --dry-run`
  resolved 5 real, clearly-labeled meeting recordings as
  `platform=unknown, segments=0` -- Palisade town, CO
  (`Zoom-Video_Board-of-Trustees_*.mp4` files on its own domain), Dundee
  city, OR (`GMT20221129-023258_Recording_1280x720.mp4`, a Zoom-export
  filename), Cayuga Heights village, NY, and Enterprise city, OR
  (Dropbox-hosted `2025-09-09-City-Council-Recording.mp4`). Confirmed
  live 2026-09-12: Palisade's, Dundee's and Cayuga Heights' own-domain
  URLs all answer a plain HEAD with `Content-Type: video/mp4` and a real
  `Content-Length` -- no adapter needed beyond a content-type check.

* **Google Drive** (WO-264 close-out's entry, previously filed `[BIG]`
  as needing Drive's API or headless/JS handling): Kemmerer city, WY
  shares three real Drive files (`City Council Meeting - .../Recording`)
  from its own site. The entry assumed Drive's viewer page never exposes
  a direct media URL without sign-in -- checked live 2026-09-12 and that
  assumption was WRONG for the confirm=t shape below: Drive's own
  documented direct-download endpoint
  (`https://drive.usercontent.google.com/download?id=<id>&export=download`)
  serves a "can't scan this file for viruses" HTML interstitial for any
  file too large to scan (confirmed on both of Kemmerer's real files,
  ~2GB each) -- appending `&confirm=t` (Drive's own long-standing
  documented bypass for exactly this interstitial, not a guess) returns
  a real `Content-Type: video/mp4`, `Accept-Ranges: bytes`, correct
  `Content-Length` response with NO sign-in. This closes the "no adapter
  without sign-in" half of that BACKLOG entry; a Drive FOLDER listing
  (Walbridge village, OH's "Meeting Recordings" folder) still renders via
  JavaScript and is out of scope here -- see BACKLOG.md's residual entry.

**What "minimum" means here, deliberately**: no upload/API auth, no
folder-listing enumeration, no special handling for a small file that
skips the virus-scan interstitial entirely (Drive's own behavior, not
this adapter's) -- just: recognize the URL shape, rewrite it to its real
media URL, and confirm by HEAD that the result is actually a video before
handing it back. Duration comes from the existing, already-generic
`app/platforms/media_probe.py` probe against `video_url` -- no
platform-specific duration code needed here.

**Enterprise, OR's Dropbox link could not be verified end to end.** The
URL captured in `research/wo284_hopa_decisions.csv`
(`https://www.dropbox.com/scl/fi/jf8u7cx0atqmkirxzw6ec/2025-09-09-City-
Council-Recording.mp4`) has no `rlkey=` token -- Dropbox's newer
`/scl/fi/` share-link shape requires one to serve the file at all, with
or without `dl=1`; checked live 2026-09-12, this exact stored URL
returns Dropbox's own HTML page either way. The `dl=1` rewrite below is
Dropbox's own documented direct-download flag (unrelated to `rlkey`) and
is still correct for a complete share link -- this is a data-capture gap
in that one stored URL, not a reason to doubt the rewrite itself. Flagged
in BACKLOG.md for a re-capture of the full link rather than silently
assumed to work.
"""

import re
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import aiohttp

from .base import AssetFinder
from .media_scan import media_type
from .models import ResolvedMeeting

# Same realistic-desktop-UA convention as vimeo.py/wistia.py's own scoped
# `_UA` -- CLAUDE.md's "politely" bullet (a realistic header so a naive
# check doesn't false-positive us as a bot), not an attempt to evade
# anything.
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_HEAD_TIMEOUT_SECONDS = 20

# A Google Drive single-file "view" link -- `drive.google.com/file/d/<id>/
# view...` -- confirmed real shape against both of Kemmerer, WY's files.
# Deliberately NOT matching `drive.google.com/drive/folders/...` (a
# folder listing, out of scope -- see module docstring) or `/open?id=...`
# (not seen live yet).
_DRIVE_FILE_ID_RE = re.compile(r"drive\.google\.com/file/d/([\w-]+)")


def is_direct_file_url(url: str) -> bool:
    """True for a bare first-party/file-sharing video URL this adapter
    can resolve -- called from `detect_platform()` as the LAST check,
    after every known vendor platform, so a video URL that's actually
    served BY a recognized platform never reaches here."""
    if _DRIVE_FILE_ID_RE.search(url):
        return True
    # A real video extension in the URL's own path -- covers a bare
    # first-party file (Palisade/Dundee/Cayuga Heights) AND Dropbox's
    # `/scl/fi/<id>/<filename>.mp4` shape, whose filename segment already
    # carries the real extension.
    return media_type(url) == "video"


def _resolve_direct_media_url(url: str) -> str:
    """The real, fetchable media URL behind a share link, or the URL
    itself when it's already a bare, playable first-party file."""
    drive_match = _DRIVE_FILE_ID_RE.search(url)
    if drive_match:
        file_id = drive_match.group(1)
        return (
            "https://drive.usercontent.google.com/download"
            f"?id={file_id}&export=download&confirm=t"
        )
    parsed = urlparse(url)
    if "dropbox.com" in parsed.netloc:
        # Dropbox's own documented direct-download flag -- confirmed live
        # 2026-09-12 to change a share page's response from its ordinary
        # HTML preview to a real download when the rest of the link
        # (notably `rlkey=`) is present. See module docstring's caution
        # for the one real fixture this couldn't fully verify.
        query_pairs = [(k, v) for k, v in parse_qsl(parsed.query) if k != "dl"]
        query_pairs.append(("dl", "1"))
        return urlunparse(parsed._replace(query=urlencode(query_pairs)))
    return url


class DirectFileAssetFinder(AssetFinder):
    platform_name = "direct_file"

    async def resolve(self, url: str) -> ResolvedMeeting:
        media_url = _resolve_direct_media_url(url)
        content_type = await self._head_content_type(media_url)
        if not content_type or not content_type.startswith("video/"):
            # Graceful degradation, not a raised error -- same convention
            # as every other adapter's "found something video-shaped but
            # couldn't confirm it" path (CLAUDE.md's "politely" bullet):
            # surface a plain warning rather than fail the whole resolve.
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "direct_file: could not confirm this URL serves a "
                    f"playable video (Content-Type: {content_type!r})"
                ],
            )
        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            video_url=media_url,
            video_format="mp4",
        )

    @staticmethod
    async def _head_content_type(media_url: str) -> Optional[str]:
        async with aiohttp.ClientSession(headers={"User-Agent": _UA}) as session:
            async with session.head(
                media_url,
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=_HEAD_TIMEOUT_SECONDS),
            ) as resp:
                return resp.headers.get("Content-Type")
