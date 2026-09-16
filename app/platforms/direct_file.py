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

**Laserfiche WebLink (WO-304, 2026-09-12)** -- a third, structurally
different shape, added for the one real example on file:
`test.co.jefferson.wa.us/WeblinkExternal/`, Jefferson County, WA's own
self-hosted document repository, where the Board of County Commissioners'
weekly Zoom cloud recording (video + a real WebVTT caption file) lives
alongside its agendas and minutes (see BACKLOG_DONE.md's WO-233 entry --
the study that found this one example real among 20 repositories checked
-- and WO-304's own entry for the ingest this closes). Two things make
this its own case rather than falling under the checks above:

1. **No file extension anywhere in the URL.** The real download link is
   `ElectronicFile.aspx?docid=<id>&dbid=<id>&repo=<name>` -- the filename
   (and its real extension) only ever appears in the response's
   `Content-Disposition` header, so `media_type()`'s extension-based
   check can't recognize it; `_is_laserfiche_weblink_url()` matches the
   URL shape directly instead.
2. **HEAD doesn't work, and a successful GET answers with a generic
   Content-Type.** Confirmed live 2026-09-12, with ZERO cookies and no
   session of any kind (settling a real disagreement between two earlier
   notes -- WO-233 said no login was needed, a separate spot-check note
   guessed a session token was required; WO-233 was right): a plain HEAD
   302s to `Error.aspx` every time, but a plain GET -- with or without a
   `Range` header -- answers 200/206 with the real bytes, real
   `Content-Length`/`Content-Range`, and `Accept-Ranges: bytes`, just
   under `Content-Type: application/octet-stream` rather than
   `video/mp4`. So confirmation here reads the first bytes of a small
   ranged GET for a real ISO-BMFF box marker (`ftyp`/`moov`/`mdat` --
   the MP4 container signature) instead of trusting a header this host
   never sends usefully.

**The caption file is a sibling docid, not a sibling URL path.** Since
there's no filename in the URL to swap an extension on, the caption
file is found the way Laserfiche/Zoom's own upload actually lays it out:
each Zoom cloud-recording sync batch writes the caption file at
`docid - 1` and the chat transcript at `docid + 1`, immediately
surrounding the video's own docid -- confirmed live on TWO independent
real meetings (2026-08-24: vtt 10549042 / video 10549043 / chat
10549044; 2026-09-08: vtt 10559482 / video 10559483 / chat 10559484),
not assumed from one. `_laserfiche_sibling_caption_url()` only ever
computes `docid - 1`; it does not scan a folder listing (that needs a
separate, session-bearing API call -- see BACKLOG_DONE.md's WO-233
entry -- deliberately out of scope for this "minimum" adapter), so a
caption file at any other offset, or in a folder whose batch didn't
follow this order, is a real, expected miss (surfaced as a plain
`transcript_warnings` entry, not an error).

**Audio-only Laserfiche (WO-317, 2026-09-12)** -- BACKLOG.md's Laserfiche
entry named two real, independently-confirmed audio-only sources (WO-305/
WO-315's census of all 79 named-government WebLink repositories): Ramsey
city, MN's Council Work Session recordings and Deschutes County, OR's
Historic Landmarks Commission audio minutes. Re-derived live against both
before building (per CLAUDE.md's "a backlog entry is a lead, not a spec"
rule) and found TWO distinct real URL shapes, not one:

1. **Deschutes** uses the same extension-less `ElectronicFile.aspx?docid=`
   shape as Jefferson County's video (confirmed live 2026-09-12: docid
   94746, zero cookies, ranged GET returns 206 with a real ID3 tag
   (`49 44 33`) at byte 0 -- an MP3, not the ISO-BMFF video this branch
   used to assume).
2. **Ramsey** is an OLDER WebLink 9 install that exposes a DIFFERENT,
   friendlier download path -- `/WebLink/<n>/edoc/<docid>/<filename>.mp3`
   -- with a real extension already in the URL. Confirmed live 2026-09-12
   (docid 813049): a HEAD still 302s to the same `Error.aspx
   ?aspxerrorpath=/WebLink/ElectronicFile.aspx` this module's HEAD-doesn't-
   work note already documents (so this IS the same underlying
   ElectronicFile.aspx serving path under the hood, just a different
   public URL alias), and a plain ranged GET with ZERO cookies -- no
   session bootstrap needed, despite this repository's own reject reason
   being `weblink9-postback-login-gated` (that gate is on the folder
   BROWSE UI needing a real browser's postback, not on the file download
   itself) -- returns 206 with a real ID3 tag at byte 0.

Both shapes are routed through the same `_resolve_laserfiche()` ranged-GET
classification below. `_classify_laserfiche_media()` extends the existing
ISO-BMFF check with an MP3 branch (ID3 tag or a raw MPEG frame sync at
byte 0) and an M4A branch (ISO-BMFF carrying the `M4A ` brand instead of
a video brand like `mp42`/`isom`) so a bare Laserfiche audio recording
gets `video_format` set to its real format ("mp3"/"m4a") the same way
`utah_pmn.py`'s own bare-file case already does for OTHER platforms --
`media_probe.py`'s ffprobe-based duration probe and `player.js`'s native
`<video>` fallback are already format-agnostic, so no new transcription
or playback code is needed, only the confirmation + classification here.
Caption-sibling lookup (`_laserfiche_sibling_caption_url()`) is skipped
entirely for the edoc shape -- it has no known Zoom-sibling-docid
convention, and neither government's file is a Zoom cloud recording.
"""

import re
from typing import List, Optional, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import aiohttp

from .base import AssetFinder
from .media_scan import media_type
from .models import ResolvedMeeting, TranscriptSegment
from ..utils.url_guard import guarded_get, read_capped_text
from ..utils.vtt_parser import (
    detect_language_from_texts,
    is_likely_garbled,
    parse_captions_by_extension,
)

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

# Laserfiche WebLink's own document-download endpoint -- confirmed real
# shape live 2026-09-12 against `test.co.jefferson.wa.us/WeblinkExternal/`
# (see module docstring). Captures the numeric docid so
# `_laserfiche_sibling_caption_url()` can compute the caption file's own
# docid from it.
_LASERFICHE_ELECTRONIC_FILE_RE = re.compile(
    r"ElectronicFile\.aspx\?docid=(?P<docid>\d+)&dbid=\d+&repo=[^&]+",
    re.IGNORECASE,
)

# Laserfiche WebLink 9's older "friendly" download path -- confirmed real
# live 2026-09-12 against Ramsey city, MN's `weblink.cityoframsey.com`
# (WO-317; see module docstring's "Audio-only Laserfiche" section). A
# HEAD on this path 302s to the exact same `Error.aspx?aspxerrorpath=
# /WebLink/ElectronicFile.aspx` a HEAD on the docid-query shape above
# does, confirming this is the same underlying serving path under a
# different public URL, not a new host behavior to handle separately.
_LASERFICHE_EDOC_RE = re.compile(
    r"/WebLink/(?:\d+/)?edoc/(?P<docid>\d+)/",
    re.IGNORECASE,
)

# The real ISO-BMFF ("MP4 family") container box markers -- confirmed
# live 2026-09-12 in the first bytes of Jefferson County, WA's real
# `ElectronicFile.aspx` video response. Used to confirm a Laserfiche
# WebLink download is actually a video without trusting its
# `Content-Type` header, which this host always answers with a generic
# `application/octet-stream` regardless of what the file actually is.
_VIDEO_MAGIC_MARKERS = (b"ftyp", b"moov", b"mdat")

# WO-317, 2026-09-12: an ISO-BMFF file carrying this brand instead of a
# video brand (`mp42`/`isom`/etc) is Apple's own audio-only container --
# no real .m4a fixture was on hand to confirm the exact brand string
# against, so this is Apple's documented brand value, not (yet) checked
# against a live Laserfiche .m4a byte-for-byte; both of WO-317's real
# fixtures (Ramsey, Deschutes) are MP3, not M4A. Flagged in BACKLOG.md.
_M4A_BRAND_MARKER = b"M4A "

# MP3's own two real on-disk shapes: an ID3v2 tag at byte 0 (confirmed
# live 2026-09-12 on both Ramsey's and Deschutes' real files -- `49 44
# 33` at the very start of a ranged GET's first 64 bytes), or -- for an
# MP3 with no ID3 tag at all -- a raw MPEG frame sync byte pair at byte
# 0. Checked with `.startswith()`, not `in`, since a frame-sync-shaped
# byte pair appearing later in an arbitrary binary blob would be a false
# positive; neither real fixture on file needed the frame-sync branch,
# so it's here for completeness (matching queue_probe.py's own bare
# `.mp3` handling), not itself independently confirmed live.
_MP3_FRAME_SYNC_PREFIXES = (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2")


def is_direct_file_url(url: str) -> bool:
    """True for a bare first-party/file-sharing video URL this adapter
    can resolve -- called from `detect_platform()` as the LAST check,
    after every known vendor platform, so a video URL that's actually
    served BY a recognized platform never reaches here."""
    if _DRIVE_FILE_ID_RE.search(url):
        return True
    if _is_laserfiche_weblink_url(url) or _is_laserfiche_edoc_url(url):
        return True
    # A real video OR audio extension in the URL's own path -- covers a
    # bare first-party file (Palisade/Dundee/Cayuga Heights), Dropbox's
    # `/scl/fi/<id>/<filename>.mp4` shape (whose filename segment already
    # carries the real extension), and a bare hosted audio file (WO-317)
    # such as Ramsey, MN's `.mp3` recordings served OFF the edoc path
    # above -- "audio" added alongside the original "video"-only check so
    # an audio-only direct file is recognized the same way utah_pmn.py's
    # own bare-file case already is for a different platform.
    return media_type(url) in ("video", "audio")


def _is_laserfiche_weblink_url(url: str) -> bool:
    """True for a Laserfiche WebLink `ElectronicFile.aspx` download link
    -- see module docstring's "Laserfiche WebLink" section for why this
    needs its own check rather than `media_type()`'s extension-based
    one (no extension ever appears in the URL itself)."""
    return bool(_LASERFICHE_ELECTRONIC_FILE_RE.search(url))


def _is_laserfiche_edoc_url(url: str) -> bool:
    """True for Laserfiche WebLink 9's older `/edoc/<docid>/<filename>`
    download path (WO-317) -- see module docstring's "Audio-only
    Laserfiche" section. Unlike `_is_laserfiche_weblink_url()`'s shape,
    this one DOES carry a real filename/extension, but still needs its
    own check (rather than relying on `media_type()` alone) so
    `_resolve_laserfiche()`'s ranged-GET + magic-byte confirmation runs
    for it too -- a plain HEAD 302s to the same generic `Error.aspx` the
    other shape's HEAD does, so the generic own-domain HEAD-only check
    below would misclassify a real file as unconfirmed."""
    return bool(_LASERFICHE_EDOC_RE.search(url))


def _laserfiche_sibling_caption_url(url: str) -> Optional[str]:
    """The WebVTT caption file Laserfiche WebLink stores next to a Zoom
    cloud-recording video, or None if `url` isn't a recognized
    Laserfiche WebLink link at all. See module docstring's "caption file
    is a sibling docid" section for the confirmed `docid - 1` pattern
    this computes -- not a folder scan."""
    match = _LASERFICHE_ELECTRONIC_FILE_RE.search(url)
    if not match:
        return None
    docid = int(match.group("docid"))
    return url.replace(f"docid={docid}&", f"docid={docid - 1}&", 1)


def _classify_laserfiche_media(chunk: bytes) -> Optional[str]:
    """`"video"`/`"m4a"`/`"mp3"` from the first bytes of a Laserfiche
    WebLink download, or `None` when nothing recognized matched -- see
    module docstring's "Audio-only Laserfiche" section (WO-317) for the
    two real confirmed sources (Ramsey city, MN; Deschutes County, OR)
    this extends the original video-only check to cover."""
    if chunk.startswith(b"ID3") or chunk.startswith(_MP3_FRAME_SYNC_PREFIXES):
        return "mp3"
    if any(marker in chunk for marker in _VIDEO_MAGIC_MARKERS):
        return "m4a" if _M4A_BRAND_MARKER in chunk else "video"
    return None


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
        if _is_laserfiche_weblink_url(media_url) or _is_laserfiche_edoc_url(media_url):
            # A distinct sub-path -- see module docstring -- since this
            # host answers HEAD with a redirect and GET with a generic
            # Content-Type, neither of which the check below can use.
            return await self._resolve_laserfiche(url, media_url)
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

    async def _resolve_laserfiche(self, url: str, media_url: str) -> ResolvedMeeting:
        media_kind = await self._laserfiche_classify_media(media_url)
        if media_kind is None:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "direct_file: could not confirm this Laserfiche WebLink "
                    "URL serves a playable video or audio file."
                ],
            )
        resolved = ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            video_url=media_url,
            # "video" classifies as a real ISO-BMFF video brand -> "mp4"
            # (same convention as before WO-317); "m4a"/"mp3" pass their
            # own real format straight through, same as utah_pmn.py's own
            # bare-file case -- see module docstring's "Audio-only
            # Laserfiche" section.
            video_format="mp4" if media_kind == "video" else media_kind,
        )
        # Zoom's sibling-docid caption convention (docid - 1) only applies
        # to the docid-query shape -- `_laserfiche_sibling_caption_url()`
        # already returns None for the edoc shape (its regex doesn't
        # match), and neither of WO-317's real audio fixtures is a Zoom
        # cloud recording, so this is the correct, expected no-op for them.
        caption_url = _laserfiche_sibling_caption_url(media_url)
        cues, language = (
            await self._fetch_laserfiche_captions(caption_url)
            if caption_url
            else (None, None)
        )
        if cues:
            resolved.segments = [TranscriptSegment(**cue) for cue in cues]
            resolved.transcript_language = language
            if language and language != "en":
                resolved.transcript_warnings = [
                    f"These captions appear to be in '{language}', not 'en' -- "
                    "no matching-language track was found for this meeting."
                ]
            if is_likely_garbled(cues):
                resolved.transcript_warnings = (resolved.transcript_warnings or []) + [
                    "This transcript looks garbled at the source (not a "
                    "parsing bug on our end) -- treat it as approximate."
                ]
        elif caption_url:
            # A sibling-docid lookup was actually attempted (the docid
            # shape) and missed -- the original, still-accurate wording.
            resolved.transcript_warnings = [
                "We couldn't find a caption file next to this Laserfiche "
                "WebLink video (checked the docid immediately before it, "
                "the confirmed real pattern -- see direct_file.py's own "
                "module docstring)."
            ]
        else:
            # WO-317: the edoc shape has no known Zoom-sibling-docid
            # convention to check at all (see module docstring's
            # "Audio-only Laserfiche" section) -- a plain miss, not a
            # failed lookup, so the wording shouldn't claim one was tried.
            resolved.transcript_warnings = [
                "We couldn't find a caption file for this Laserfiche "
                "WebLink recording (no known caption convention exists "
                "for this download-link shape)."
            ]
        return resolved

    @staticmethod
    async def _laserfiche_classify_media(media_url: str) -> Optional[str]:
        """`"video"`/`"m4a"`/`"mp3"` from a small ranged GET's first bytes
        (not HEAD -- this host 302s on HEAD, see module docstring), or
        `None` if nothing recognized matched. Reads the actual bytes
        rather than trusting `Content-Type`, since this host's own header
        is a generic `application/octet-stream` on every real file
        regardless of what it actually is.

        `Accept-Encoding: identity` (WO-317, 2026-09-12) -- confirmed live
        against Ramsey city, MN's older WebLink 9 install: its IIS
        dynamic-compression module gzip-encodes a 64-byte RANGED response
        on its own (aiohttp sends `Accept-Encoding: gzip` by default),
        producing a truncated gzip stream that fails to decompress
        (`zlib.error: invalid code lengths set`) -- a real server bug on
        a byte-range response, not a network error. `curl` never hits
        this because it doesn't request compression unless `--compressed`
        is passed. Jefferson County, WA's newer WebLink install does NOT
        do this (confirmed live, `curl --compressed` returns no
        `Content-Encoding` at all) -- host-specific, not a general
        Laserfiche WebLink behavior, but harmless to send everywhere."""
        try:
            async with aiohttp.ClientSession(headers={"User-Agent": _UA}) as session:
                async with session.get(
                    media_url,
                    headers={"Range": "bytes=0-63", "Accept-Encoding": "identity"},
                    timeout=aiohttp.ClientTimeout(total=_HEAD_TIMEOUT_SECONDS),
                ) as resp:
                    if resp.status not in (200, 206):
                        return None
                    chunk = await resp.read()
        except aiohttp.ClientError:
            return None
        return _classify_laserfiche_media(chunk)

    @staticmethod
    async def _fetch_laserfiche_captions(
        caption_url: str,
    ) -> Tuple[Optional[List[dict]], Optional[str]]:
        """`(cues, language)` from the sibling-docid caption URL, or
        `(None, None)` if it's not real captions -- the confirmed real
        outcome when the `docid - 1` guess misses (see module
        docstring), not a bug."""
        try:
            async with aiohttp.ClientSession(headers={"User-Agent": _UA}) as session:
                async with guarded_get(
                    session,
                    caption_url,
                    timeout=aiohttp.ClientTimeout(total=_HEAD_TIMEOUT_SECONDS),
                ) as resp:
                    if resp.status != 200:
                        return None, None
                    body = await read_capped_text(resp)
        except aiohttp.ClientError:
            return None, None
        if not body or not body.strip().upper().startswith("WEBVTT"):
            return None, None
        cues, _fallback_text = parse_captions_by_extension("captions.vtt", body)
        if not cues:
            return None, None
        language = detect_language_from_texts(c.get("text") for c in cues) or "en"
        return cues, language
