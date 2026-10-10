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

**HEAD refused, or unusable (WO-1048, 2026-09-24)** -- two real hosts
found walking county meeting pages, each confirmed live:

1. **Jefferson County, TX** (`jeffersoncountytx.gov/blobs/agenda/video_pl/
   JCCC092226.mp4`, the file behind its `jcagenda/CourtVideo.aspx?f=...`
   player page). IIS answers HEAD with `405` and `Allow: GET` -- no
   Content-Type at all, so the old HEAD-only check gave up. A ranged GET
   (`Range: bytes=0-1023`) answers `206`, `Content-Type: video/mp4`, a
   real `Content-Range: bytes 0-1023/1131384015`, and `ftypisom` at
   byte 4. So a HEAD that answers 403/405/501 now falls back to one
   ranged GET.
2. **Dropbox** (Ingham County, MI's `9.22.26-BOC.mp4` share link). The
   `dl=1` link 302s to a `*.dl.dropboxusercontent.com` host whose HEAD
   answers `Content-Type: application/json` and, over aiohttp's HTTP/1.1,
   sends a gzip body after the HEAD response -- aiohttp fails with "Bad
   status line". A ranged GET on the same link answers `206`,
   `Content-Type: application/binary`, and `ftypmp42` at byte 4. So a
   Dropbox link skips HEAD entirely and uses the ranged GET.

Neither host sends a useful Content-Type on every path, so the ranged
GET also reads the first bytes and accepts a real container signature
(the same `_classify_laserfiche_media()` check Laserfiche already uses).
Only the first 1 KB is ever read, even if a host ignores `Range` and
starts sending the whole file.

iSiLIVE files and their caption file (WO-1155, 2026-09-28)
----------------------------------------------------------
iSiLIVE (ISI Live) hosts meeting video for eScribe customers and others.
It keeps each recording's captions next to the file:
`video.isilive.ca/{client}/{file}.vtt` (English) or `.{lang}.vtt`.
`escribe.py` already read that file, but only when it reached the video
through an eScribe meeting page. A bare iSiLIVE URL came here and got
video with no captions. `parse_isilive_file_url()` now recognises five
real shapes (all checked live 2026-09-28 on Miramichi NB's
`miramichi/2026-05-19.mp4`, except the `.html` page, which Miramichi
lacks and Whitehorse YT has):

* `video.isilive.ca/download/{client}/{file}` -- the plain file.
* `video.isilive.ca/{client}/{file}` -- the same file.
* `video.isilive.ca/play/{client}/{file}` -- a small player page (HTML),
  not the file. Before WO-1155 this failed the media check.
* `video.isilive.ca/{client}/{file}.html` -- a per-file player page.
* `cdn1.isilive.ca/vod/_definst_/mp4:{client}/{file}/playlist.m3u8` --
  the HLS stream `escribe.py` itself builds.

Every shape resolves to the `/download/` file as `video_url` (it answers
HEAD with `Content-Type: video/mp4`), then the caption lookup runs with
`escribe.py`'s own rule (`find_isilive_captions()`). When no caption
file exists (Whitehorse YT, Nunavut: 404), the result is exactly the
old plain-file result. `{file}` may hold subfolders (Nunavut's
`2026/2026-05-22-eng.mp4`).

The `{client}` folder is iSiLIVE's customer name. It is never used to
name a government: `jurisdiction` stays unset, and the gov_id comes from
the caller's research row.

SharePoint anonymous share links and DNN LinkClick links (2026-09-30)
---------------------------------------------------------------------
Two more share-link shapes, each confirmed live 2026-09-30 by HEAD.

1. **SharePoint** `https://<tenant>.sharepoint.com/:v:/s/<site>/<token>?e=<code>`
   (Yakima County, WA's BOCC Work Session). The share page itself is
   HTML. Adding `&download=1` (SharePoint's own flag, same idea as
   Dropbox's `dl=1`) makes the first request answer 302, and that
   response sets a guest cookie. Following the redirect WITH that cookie
   reaches `/sites/<site>/<folder>/<file>.mp4?ga=1`, which answers 200
   `video/mp4` (136 MB on the Yakima file). Without the cookie, SharePoint
   redirects to Microsoft's sign-in page. The final `.mp4` URL on its own
   is no use either: a cookie-less HEAD of it also redirects to sign-in.
   **aiohttp's built-in cookie jar cannot do this.** The guest cookie
   (`FedAuth`) holds base64 characters (`/`, `=`, `+`); aiohttp re-sends
   such a value wrapped in quotes, SharePoint rejects it, and the chain
   ends at Microsoft sign-in (confirmed 2026-09-30). `follow_with_cookies()`
   below follows the redirects by hand and sends each cookie back
   exactly as received.
   So `video_url` is the share URL with `download=1`, never the final
   file URL. Every reader of `video_url` must keep cookies across the
   redirect: this module and `queue_probe.py` use `follow_with_cookies()`,
   and ffmpeg/ffprobe (what the transcription worker and
   `media_probe.py` run) also keep cookies across an HTTP redirect --
   confirmed 2026-09-30: `ffprobe` on the share URL + `download=1` read
   the real 4,079-second duration with no extra options. Limitation: the
   guest cookie is per request chain, so a plain cookie-less download
   tool (curl without a cookie jar, a browser `<video>` tag on another
   origin) will land on the sign-in page. `stream.aspx` links and
   `/:v:/r/` links need an organisation sign-in and stay unsupported
   (only the anonymous `/:v:/s/` shape is recognised).

2. **DNN LinkClick** `https://<host>/LinkClick.aspx?fileticket=<ticket>&portalid=0`
   (Sangamon County, IL's County Board Special Meeting recording). DNN
   (DotNetNuke) sites serve uploaded files through this link. It answers
   302 to the real file (`/Portals/0/TempAudio/SoundFile/...mp3`,
   `Content-Type: audio/mpeg`). The URL has no media extension, so the
   format comes from the Content-Type. The ordinary HEAD check below
   already follows redirects; only the URL-shape recognition was missing.
   A LinkClick ticket for a PDF or other non-media file fails the same
   video/audio Content-Type check and is reported as unconfirmed.
"""

import re
from typing import List, Optional, Tuple
from urllib.parse import (
    parse_qsl,
    quote,
    unquote,
    urlencode,
    urljoin,
    urlparse,
    urlunparse,
)

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

# WO-1048: HEAD statuses that mean "this host won't answer HEAD", not "this
# file isn't there" -- Jefferson County, TX's IIS answers 405 (see module
# docstring). 403 and 501 are the other two ways a server refuses a method
# it doesn't allow; each costs one extra small ranged GET, never a guess.
_HEAD_REFUSED_STATUSES = (403, 405, 501)

# How much of the file the ranged-GET fallback reads (WO-1048). Enough
# for any container signature `_classify_laserfiche_media()` checks.
_PROBE_BYTES = 1024

# A Google Drive single-file "view" link -- `drive.google.com/file/d/<id>/
# view...` -- confirmed real shape against both of Kemmerer, WY's files.
# Deliberately NOT matching `drive.google.com/drive/folders/...` (a
# folder listing, out of scope -- see module docstring) or `/open?id=...`
# (not seen live yet).
_DRIVE_FILE_ID_RE = re.compile(r"drive\.google\.com/file/d/([\w-]+)")

# WO-1042: the other two real shapes the SAME Drive file shows up under.
# `drive.usercontent.google.com/download?id=<id>&export=download&confirm=t`
# is what `_resolve_direct_media_url()` below already REWRITES a
# `file/d/<id>` link into -- so it's the exact URL Meeting Finder's own
# Resolve step hands back as `video_url`/`meeting_url` for a Drive find,
# and a government whose site links straight to a `...usercontent...`
# download URL (12 real rows confirmed live 2026-09-24 in WO-1040's
# dry-run summary -- martin.k12.mn.us, peacham.net, alamosacounty.org and
# nine more, all school/town sites that paste the already-rewritten
# download link rather than the `/file/d/` share page) hit exactly the
# same "detect_platform() returns 'unknown'" gap. `drive.google.com/uc?
# id=<id>` is Drive's other long-standing direct-download alias for the
# same file (not yet seen live on a real government site, but the same
# shape Drive itself documents and the shape `gdown`/other tooling
# produces) -- recognized here too so a pasted link in that form doesn't
# hit the same gap the moment one turns up.
_DRIVE_DOWNLOAD_ID_RE = re.compile(
    r"drive\.usercontent\.google\.com/download\?[^\s\"'<>]*\bid=([\w-]+)"
)
_DRIVE_UC_ID_RE = re.compile(r"drive\.google\.com/uc\?[^\s\"'<>]*\bid=([\w-]+)")


# WO-1155: iSiLIVE hosts -- see module docstring's "iSiLIVE files" section.
_ISILIVE_VIDEO_HOST = "video.isilive.ca"
_ISILIVE_CDN_HOST_RE = re.compile(r"^cdn\d*\.isilive\.ca$")
_ISILIVE_CDN_PATH_RE = re.compile(r"^/vod/_definst_/mp4:([^/]+)/(.+)/playlist\.m3u8$")
# First path folders on video.isilive.ca that are not a customer: the
# player's own assets, and the two prefixes that come before a customer.
_ISILIVE_NON_CLIENT_FOLDERS = frozenset({"cdn"})
_ISILIVE_PREFIX_FOLDERS = frozenset({"download", "play"})
_ISILIVE_MEDIA_EXTENSIONS = (".mp4", ".m4v", ".mov", ".mp3", ".m4a", ".wav")

# 2026-09-30: SharePoint anonymous video share link -- see module
# docstring's "SharePoint anonymous share links" section. Only the
# `/:v:/s/<site>/<token>` shape confirmed live (Yakima County, WA).
_SHAREPOINT_VIDEO_SHARE_RE = re.compile(r"^/:v:/s/[^/]+/[^/]+/?$", re.IGNORECASE)

# 2026-09-30: DNN (DotNetNuke) file link -- see module docstring's "DNN
# LinkClick" section (Sangamon County, IL).
_DNN_LINKCLICK_PATH_RE = re.compile(r"/LinkClick\.aspx$", re.IGNORECASE)


def parse_isilive_file_url(url: str) -> Optional[Tuple[str, str]]:
    """`(client, encoded_file)` for a recognised iSiLIVE file URL, else
    None. `encoded_file` is the file path, percent-encoded one folder at
    a time (a space becomes `%20`), the form iSiLIVE's own caption URLs
    use. A live-stream player (`play/{client}/live`) has no media file
    and returns None. See module docstring's "iSiLIVE files" section."""
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    if netloc == _ISILIVE_VIDEO_HOST:
        parts = [p for p in parsed.path.split("/") if p]
        if parts and parts[0].lower() in _ISILIVE_PREFIX_FOLDERS:
            parts = parts[1:]
        if len(parts) < 2 or parts[0].lower() in _ISILIVE_NON_CLIENT_FOLDERS:
            return None
        client, file_parts = parts[0], parts[1:]
        if file_parts[-1].lower().endswith(".html"):
            file_parts[-1] = file_parts[-1][: -len(".html")]
    elif _ISILIVE_CDN_HOST_RE.match(netloc):
        match = _ISILIVE_CDN_PATH_RE.match(parsed.path)
        if not match:
            return None
        client, file_parts = match.group(1), match.group(2).split("/")
    else:
        return None
    decoded = [unquote(p) for p in file_parts]
    if not decoded[-1].lower().endswith(_ISILIVE_MEDIA_EXTENSIONS):
        return None
    return unquote(client), "/".join(quote(p, safe="") for p in decoded)


def _isilive_download_url(client: str, encoded_file: str) -> str:
    """The plain file behind any recognised iSiLIVE shape."""
    return f"https://{_ISILIVE_VIDEO_HOST}/download/{client}/{encoded_file}"


_MAX_COOKIE_REDIRECTS = 8


async def follow_with_cookies(
    url: str, *, method: str = "HEAD"
) -> Tuple[int, Optional[str], Optional[int]]:
    """`(status, content_type, content_length)` of the final response
    after following redirects by hand, sending back every cookie the
    chain sets, byte for byte. Needed for a SharePoint share link (module
    docstring): aiohttp's own jar re-quotes the `FedAuth` value and
    SharePoint then refuses it. Raises `aiohttp.ClientError` /
    `TimeoutError` like any other probe; the caller decides what a
    failure means."""
    jar: dict = {}
    current = url
    async with aiohttp.ClientSession(
        headers={"User-Agent": _UA}, cookie_jar=aiohttp.DummyCookieJar()
    ) as session:
        for _hop in range(_MAX_COOKIE_REDIRECTS + 1):
            headers = {}
            if jar:
                headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in jar.items())
            async with session.request(
                method,
                current,
                headers=headers,
                allow_redirects=False,
                timeout=aiohttp.ClientTimeout(total=_HEAD_TIMEOUT_SECONDS),
            ) as resp:
                for raw in resp.headers.getall("Set-Cookie", []):
                    name, _sep, rest = raw.partition("=")
                    jar[name.strip()] = rest.split(";", 1)[0]
                location = resp.headers.get("Location")
                if resp.status in (301, 302, 303, 307, 308) and location:
                    current = urljoin(current, location)
                    continue
                length = resp.headers.get("Content-Length")
                return (
                    resp.status,
                    resp.headers.get("Content-Type"),
                    int(length) if length and length.isdigit() else None,
                )
    raise aiohttp.ClientError("too many redirects")


def is_sharepoint_share_url(url: str) -> bool:
    """True for a SharePoint anonymous video share link,
    `https://<tenant>.sharepoint.com/:v:/s/<site>/<token>` -- see module
    docstring's "SharePoint anonymous share links" section. Callers that
    fetch such a link themselves must keep cookies across redirects."""
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    if not netloc.endswith(".sharepoint.com"):
        return False
    return bool(_SHAREPOINT_VIDEO_SHARE_RE.match(parsed.path))


def is_dnn_linkclick_url(url: str) -> bool:
    """True for a DNN `LinkClick.aspx?fileticket=...` file link -- see
    module docstring's "DNN LinkClick" section."""
    parsed = urlparse(url)
    if not _DNN_LINKCLICK_PATH_RE.search(parsed.path):
        return False
    return any(k.lower() == "fileticket" for k, _v in parse_qsl(parsed.query))


def _drive_file_id(url: str) -> Optional[str]:
    """The Drive file id behind any of the three recognized share/download
    shapes, or `None` when `url` isn't a Google Drive link at all. A
    single choke point so `is_direct_file_url()` and
    `_resolve_direct_media_url()` can't drift out of sync on which shapes
    count as "the same file" (WO-1042)."""
    for pattern in (_DRIVE_FILE_ID_RE, _DRIVE_DOWNLOAD_ID_RE, _DRIVE_UC_ID_RE):
        match = pattern.search(url)
        if match:
            return match.group(1)
    return None


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

# South Carolina's legislature (WO-1005, 2026-09-22): every real
# `video.scstatehouse.gov/mp4/<date><H|S|J><committee><id>_1.mp4` file
# answers BOTH a plain HEAD and a ranged GET with `Content-Type:
# application/octet-stream`, confirmed live against two real, small
# meetings listed on `scstatehouse.gov/meetings.php?...op=vid` -- an
# 11-minute Senate Judiciary full committee (2026-08-11,
# `20260811SJudiciaryFullCommittee16632_1.mp4`, 251,172,111 bytes) and a
# 14-minute House Government Efficiency and Legislative Oversight
# subcommittee the same day
# (`20260811HGovtEfficiencyandLegOversightLawEnforcementCriminal16624_1.mp4`,
# 305,067,141 bytes). Both also answered `Accept-Ranges: bytes` with a
# real `Content-Length`/`Content-Range`, so this is a real, playable
# video file the host just labels generically -- not an error page.
# `_HTML_ERROR_SNIFF_MARKERS` below is the deliberately narrow guard
# that keeps this from turning into "accept anything that isn't
# video/*": an octet-stream response is only accepted when the URL's
# own extension already says "video" or "audio" (`media_type()`), so a
# generic error page served as octet-stream (not observed on this host,
# but not ruled out either) would still need a real video/audio
# extension in its URL to slip through, and this repo's own "don't
# weaken the content-type check generally" instruction is why this
# stays scoped to the specific octet-stream value rather than "anything
# not text/html".
_OCTET_STREAM_CONTENT_TYPE = "application/octet-stream"

# Audio-only own-domain recordings (Ryan, 2026-09-22: audio-only is in
# scope) -- confirmed live against two real, independent governments the
# same day: Allouez village, WI (`allouez.s3.amazonaws.com/media/.../
# Village-Board-9-15-2026.mp3`, Content-Type `audio/mpeg`) and Farmington
# city, UT's Planning Commission (`farmington.utah.gov/wp-content/
# uploads/.../09.03.26-PC-General-Session-Q-SYS.mp3`, also
# `audio/mpeg`). Both are bare, unauthenticated files on the
# government's own domain, the exact shape this adapter already resolves
# for video -- the only gap was `resolve()`'s content-type gate requiring
# a `video/` prefix. `media_probe.py`'s duration probe and `player.js`'s
# native `<audio>`/`<video>` fallback are already format-agnostic (the
# same fact WO-317's Laserfiche audio branch already relies on), so no
# new playback or transcription code is needed here, only recognizing
# the format.
_URL_EXTENSION_FORMATS = {
    ".mp3": "mp3",
    ".wav": "wav",
    ".m4a": "m4a",
    ".mp4": "mp4",
    ".mov": "mp4",
    ".m4v": "mp4",
    ".webm": "webm",
    ".wmv": "wmv",
    ".asf": "asf",
}


def _media_format(media_url: str, content_type: Optional[str]) -> str:
    """The real format to record -- the URL's own extension when it has
    one of the recognized ones (precise), else a guess from the
    Content-Type prefix (covers the octet-stream branch, which carries
    no useful Content-Type of its own)."""
    path = urlparse(media_url).path.lower()
    for ext, fmt in _URL_EXTENSION_FORMATS.items():
        if path.endswith(ext):
            return fmt
    if content_type and content_type.startswith("audio/"):
        subtype = content_type.split("/", 1)[1].split(";")[0].strip()
        return {
            "mpeg": "mp3",
            "mp3": "mp3",
            "x-m4a": "m4a",
            "mp4": "m4a",
            "wav": "wav",
            "x-wav": "wav",
            "ogg": "ogg",
        }.get(subtype, "audio")
    return "mp4"


def is_dropbox_url(url: str) -> bool:
    """True for a Dropbox share link -- see module docstring's "HEAD
    refused, or unusable" section (WO-1048) for why these skip HEAD."""
    netloc = urlparse(url).netloc.lower()
    return netloc == "dropbox.com" or netloc.endswith(".dropbox.com")


_ASF_EXTENSIONS = (".wmv", ".asf")


def _is_granicus_host(url: str) -> bool:
    host = urlparse(url).netloc.lower().split(":")[0]
    return host == "granicus.com" or host.endswith(".granicus.com")


def is_granicus_feed_url(url: str) -> bool:
    """A Granicus RSS feed address (`ViewPublisherRSS.php`). It is a queue
    line's identity, never something a stored-entry re-resolve fetches."""
    return _is_granicus_host(url) and ("viewpublisherrss" in urlparse(url).path.lower())


def is_granicus_download_file_url(url: str) -> bool:
    """True only for a Granicus feed enclosure: the `/DownloadFile.php`
    path on a granicus.com host (`https://<tenant>.granicus.com/
    DownloadFile.php?view_id=N&clip_id=M`, a .wmv). It is the meeting's
    own video file, taken from the subscribed RSS feed, never a Granicus
    page. Deliberately narrow: no other Granicus path matches (the
    MediaPlayer.php and /player/clip pages are robots-disallowed and are
    never fetched)."""
    parsed = urlparse(url)
    host = parsed.netloc.lower().split(":")[0]
    if not (host == "granicus.com" or host.endswith(".granicus.com")):
        return False
    return parsed.path.lower() == "/downloadfile.php"


def is_asf_media_url(url: str) -> bool:
    """True for a URL whose path ends .wmv or .asf (any host)."""
    return urlparse(url).path.lower().endswith(_ASF_EXTENSIONS)


_GRANICUS_ARCHIVE_VIDEO_HOST = "archive-video.granicus.com"


def is_granicus_archive_video_url(url: str) -> bool:
    """True for `https://archive-video.granicus.com/<tenant>/<guid>.mp4`
    (or .wmv), the file DownloadFile.php redirects to. Only that host and
    only a media extension; every other Granicus URL stays a page."""
    parsed = urlparse(url)
    host = parsed.netloc.lower().split(":")[0]
    return host == _GRANICUS_ARCHIVE_VIDEO_HOST and parsed.path.lower().endswith(
        (".mp4", ".wmv")
    )


def is_asf_direct_media_url(url: str) -> bool:
    """A Granicus DownloadFile.php enclosure, the archive-video.granicus.com
    file it redirects to, or any .wmv/.asf URL: a media file fetched as a
    file (header-only probe, frozen on re-resolve), never resolved as a
    page. The name predates the archive-video mp4 case."""
    return (
        is_granicus_download_file_url(url)
        or is_granicus_archive_video_url(url)
        or is_asf_media_url(url)
    )


def is_direct_file_url(url: str) -> bool:
    """True for a bare first-party/file-sharing video URL this adapter
    can resolve -- called from `detect_platform()` as the LAST check,
    after every known vendor platform, so a video URL that's actually
    served BY a recognized platform never reaches here."""
    if _drive_file_id(url) is not None:
        return True
    if is_asf_direct_media_url(url):
        return True
    if is_laserfiche_url(url):
        return True
    if parse_isilive_file_url(url) is not None:
        # WO-1155: includes iSiLIVE's player pages, which carry no media
        # extension of their own (see module docstring).
        return True
    if is_sharepoint_share_url(url) or is_dnn_linkclick_url(url):
        # 2026-09-30: neither carries a media extension in its URL.
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


# WO-1171 (2026-09-30): CivicPlus keeps meeting recordings in its file
# library, `https://{tenant}.civicplus.com/DocumentCenter/View/{id}/{name}`
# (and sometimes `Archive.aspx?ADID=`/`AMID=`). The URL never carries a
# media extension, and HEAD answers a generic 404 HTML page, so the only
# way to tell a recording from a PDF or page is one GET that reads the
# response headers and closes the stream. Confirmed live on six real
# tenants (Woodford IL, Park CO, White Pine NV, New Scotland NY,
# Montville NJ, Preble OH): a recording answers 200 with
# `application/octet-stream` and `Content-Disposition: inline;filename=
# ....m4a` (or `audio/x-ms-wma`); the Preble `Archive.aspx?AMID=` link is
# an ordinary HTML page.
_CIVICPLUS_FILE_PATH_RE = re.compile(
    r"^/(documentcenter/(view|download)/\d+|archive\.aspx$)", re.IGNORECASE
)
_FILE_LIBRARY_MEDIA_EXTENSIONS = {
    "mp4": "mp4",
    "m4v": "mp4",
    "mov": "mp4",
    "webm": "webm",
    "mp3": "mp3",
    "m4a": "m4a",
    "wav": "wav",
    "wma": "wma",
    "aac": "aac",
    "ogg": "ogg",
}
_FILE_LIBRARY_AUDIO_FORMATS = ("mp3", "m4a", "wav", "wma", "aac", "ogg")
_DISPOSITION_FILENAME_RE = re.compile(
    r"""filename\*?=(?:UTF-8'')?"?([^";\r\n]+)"?""", re.IGNORECASE
)


def is_civicplus_file_library_url(url: str) -> bool:
    """True for a CivicPlus file-library link that might be a recording
    -- `/DocumentCenter/View|Download/{id}/...` or `/Archive.aspx?ADID=|
    AMID=` on a `*.civicplus.com` tenant. Only says the link COULD be a
    file; `probe_civicplus_file()` reads the headers to find out."""
    parsed = urlparse(url)
    if not parsed.netloc.lower().endswith("civicplus.com"):
        return False
    if not _CIVICPLUS_FILE_PATH_RE.match(parsed.path):
        return False
    if parsed.path.lower().startswith("/archive.aspx"):
        return any(k.lower() in ("adid", "amid") for k, _v in parse_qsl(parsed.query))
    return True


def classify_file_library_media(
    content_type: Optional[str], content_disposition: Optional[str], url: str
) -> Optional[str]:
    """The media `video_format` ("mp4", "m4a", "wma", ...) when these
    response headers say the file is audio or video, else `None`. An
    `audio/` or `video/` content type counts. A generic
    `application/octet-stream` counts only when the download filename (or,
    failing that, the URL path) carries a real media extension. An HTML
    page, a PDF and anything else return `None`."""
    main_type = (content_type or "").split(";", 1)[0].strip().lower()
    filename = None
    match = _DISPOSITION_FILENAME_RE.search(content_disposition or "")
    if match:
        filename = unquote(match.group(1).strip())
    ext = None
    for candidate in (filename, urlparse(url).path):
        if candidate and "." in candidate:
            tail = candidate.rsplit(".", 1)[-1].lower()
            if tail in _FILE_LIBRARY_MEDIA_EXTENSIONS:
                ext = tail
                break
    if main_type.startswith(("audio/", "video/")):
        if ext:
            return _FILE_LIBRARY_MEDIA_EXTENSIONS[ext]
        if main_type.startswith("video/"):
            return "mp4"
        return _media_format(url, main_type)
    if main_type in ("application/octet-stream", "application/binary") and ext:
        return _FILE_LIBRARY_MEDIA_EXTENSIONS[ext]
    return None


async def probe_civicplus_file(url: str) -> Optional[ResolvedMeeting]:
    """A direct-file `ResolvedMeeting` when a CivicPlus file-library link
    is a recording, else `None` (so the caller keeps treating it as a
    page). One GET that reads the headers only and closes the stream --
    the body is never read, so a 200 MB recording that ignores `Range`
    costs a few hundred bytes. HEAD is not used: these servers answer it
    with a 404 HTML page (see the WO-1171 note above). The duration is
    left to the existing ffprobe step (`media_probe`/`queue_probe`).
    Audio-only files resolve too; `video_format` ("m4a", "mp3", "wma")
    is what marks them, as for any other direct audio file. No captions,
    so tier 3."""
    if not is_civicplus_file_library_url(url):
        return None
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": _UA}) as session:
            async with guarded_get(
                session,
                url,
                timeout=aiohttp.ClientTimeout(total=_HEAD_TIMEOUT_SECONDS),
            ) as resp:
                if resp.status != 200:
                    return None
                media_url = str(resp.url)
                fmt = classify_file_library_media(
                    resp.headers.get("Content-Type"),
                    resp.headers.get("Content-Disposition"),
                    media_url,
                )
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return None
    if fmt is None:
        return None
    return ResolvedMeeting(
        platform="direct_file",
        source_url=url,
        video_url=media_url,
        video_format=fmt,
    )


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


def is_laserfiche_url(url: str) -> bool:
    """True for either recognized Laserfiche WebLink download shape (the
    docid-query `ElectronicFile.aspx` link, or WebLink 9's older `/edoc/`
    path) -- see this module's docstring, "Laserfiche WebLink" and
    "Audio-only Laserfiche" sections. Used internally (`is_direct_file_url()`,
    `resolve()`) and, since WO-937, by `queue_probe.py`'s
    `_probe_direct_file()`: that probe skips a HEAD request entirely for
    this shape rather than trusting one -- confirmed live on THREE
    independent real governments (Jefferson County WA/WO-304, Deschutes
    County OR and Ramsey city MN/WO-317) that a HEAD here always 302s to
    a generic `Error.aspx` page which itself answers 200 with the error
    page's own small HTML body, never the real file's, so a HEAD-derived
    `size_bytes` is always wrong for this host shape even though it looks
    like a normal successful response."""
    return bool(_is_laserfiche_weblink_url(url) or _is_laserfiche_edoc_url(url))


# RCCD (Riverside Community College District, CA) posts each Citizens'
# Bond Oversight Committee meeting as a pair on one host and folder:
# `.../{MM}_{DD}_{YYYY}_video.mp4` and `.../{MM}_{DD}_{YYYY}_transcript.vtt`
# (2026-10-10: the 2026-07-09 pair both answer 200/206). Scoped to this one
# host on purpose: the caption URL is only a candidate, and is kept only if
# the fetched body really starts with WEBVTT. rccd.edu also serves an
# incomplete certificate chain (see the PR that added this); nothing here
# turns certificate checking off.
_RCCD_VIDEO_RE = re.compile(
    r"^(?P<dir>/.*/)(?P<mm>\d{2})_(?P<dd>\d{2})_(?P<yyyy>\d{4})_video\.mp4$",
    re.IGNORECASE,
)


def _rccd_sibling(url: str) -> Optional[Tuple[str, str]]:
    """`(caption_url, iso_date)` for an rccd.edu `{MM}_{DD}_{YYYY}_video.mp4`
    link, else None. The date is read from the file name of the link given,
    never built from a calendar."""
    parts = urlparse(url)
    if (parts.hostname or "").lower() not in ("rccd.edu", "www.rccd.edu"):
        return None
    match = _RCCD_VIDEO_RE.match(parts.path)
    if not match:
        return None
    stem = f"{match['mm']}_{match['dd']}_{match['yyyy']}"
    caption_url = parts._replace(
        path=f"{match['dir']}{stem}_transcript.vtt", query="", fragment=""
    ).geturl()
    return caption_url, f"{match['yyyy']}-{match['mm']}-{match['dd']}"


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
    file_id = _drive_file_id(url)
    if file_id is not None:
        return (
            "https://drive.usercontent.google.com/download"
            f"?id={file_id}&export=download&confirm=t"
        )
    isilive = parse_isilive_file_url(url)
    if isilive is not None:
        return _isilive_download_url(*isilive)
    parsed = urlparse(url)
    if is_sharepoint_share_url(url):
        # SharePoint's own download flag; the guest cookie the first 302
        # sets must be kept across the redirect by whoever fetches this
        # (module docstring). Any existing `download` param is replaced.
        query_pairs = [
            (k, v) for k, v in parse_qsl(parsed.query) if k.lower() != "download"
        ]
        query_pairs.append(("download", "1"))
        return urlunparse(parsed._replace(query=urlencode(query_pairs)))
    if is_dropbox_url(url):
        # Dropbox's own documented direct-download flag -- confirmed live
        # 2026-09-12 to change a share page's response from its ordinary
        # HTML preview to a real download when the rest of the link
        # (notably `rlkey=`) is present. See module docstring's caution
        # for the one real fixture this couldn't fully verify. `raw=1` is
        # Dropbox's other documented flag for the same file; it is
        # dropped so a pasted `raw=1` link lands on the one form the
        # ranged-GET check was confirmed against (WO-1048).
        query_pairs = [
            (k, v) for k, v in parse_qsl(parsed.query) if k not in ("dl", "raw")
        ]
        query_pairs.append(("dl", "1"))
        return urlunparse(parsed._replace(query=urlencode(query_pairs)))
    return url


class DirectFileAssetFinder(AssetFinder):
    platform_name = "direct_file"

    async def resolve(self, url: str) -> ResolvedMeeting:
        media_url = _resolve_direct_media_url(url)
        if _is_granicus_host(media_url) and not is_asf_direct_media_url(media_url):
            # Any other Granicus URL is a page (robots.txt-disallowed for
            # bots): make no request.
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "direct_file: not fetching a Granicus page; only a "
                    "DownloadFile.php enclosure is read"
                ],
            )
        if is_asf_direct_media_url(media_url):
            # A Granicus feed enclosure (or any .wmv/.asf): the URL is the
            # media file itself and Granicus answers bots on pages only
            # by robots.txt, so make no request here. The length probe in
            # queue_probe reads the first 256 KB of the file with a Range
            # request and rejects a dead or non-ASF link there.
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_url=media_url,
                video_format=(
                    "mp4"
                    if urlparse(media_url).path.lower().endswith(".mp4")
                    else _media_format(media_url, None)
                    if is_asf_media_url(media_url)
                    else "wmv"
                ),
            )
        if is_laserfiche_url(media_url):
            # A distinct sub-path -- see module docstring -- since this
            # host answers HEAD with a redirect and GET with a generic
            # Content-Type, neither of which the check below can use.
            return await self._resolve_laserfiche(url, media_url)
        content_type, media_kind = await self._probe_media(media_url)
        is_media_content_type = bool(
            content_type and content_type.startswith(("video/", "audio/"))
        )
        # South Carolina's legislature (WO-1005, see module docstring's
        # `_OCTET_STREAM_CONTENT_TYPE` comment): this host answers a real,
        # playable .mp4 with a generic octet-stream Content-Type on every
        # meeting, confirmed live -- accept it ONLY when the URL's own
        # extension already says video/audio, so this stays a narrow,
        # host-shape-specific accept path rather than a general weakening
        # of the content-type check.
        is_octet_stream_media_file = (
            content_type == _OCTET_STREAM_CONTENT_TYPE
            and media_type(media_url) in ("video", "audio")
        )
        # WO-1048: when the ranged-GET fallback ran, a real container
        # signature in the first bytes counts even under a generic
        # Content-Type (Dropbox's `application/binary`).
        if not (is_media_content_type or is_octet_stream_media_file or media_kind):
            # Graceful degradation, not a raised error -- same convention
            # as every other adapter's "found something video-shaped but
            # couldn't confirm it" path (CLAUDE.md's "politely" bullet):
            # surface a plain warning rather than fail the whole resolve.
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "direct_file: could not confirm this URL serves a "
                    f"playable video or audio file (Content-Type: {content_type!r})"
                ],
            )
        resolved = ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            video_url=media_url,
            video_format=(
                media_kind
                if media_kind in ("mp3", "m4a")
                else _media_format(media_url, content_type)
            ),
        )
        rccd = _rccd_sibling(media_url)
        if rccd is not None:
            caption_url, iso_date = rccd
            resolved.date = iso_date
            cues, language = await self._fetch_laserfiche_captions(caption_url)
            if cues:
                resolved.segments = [TranscriptSegment(**cue) for cue in cues]
                resolved.transcript_language = language
                if language and language != "en":
                    resolved.transcript_warnings = [
                        f"These captions appear to be in '{language}', not 'en'."
                    ]
            else:
                resolved.transcript_warnings = [
                    "We couldn't find a caption file next to this rccd.edu video."
                ]
        isilive = parse_isilive_file_url(url)
        if isilive is not None:
            await self._add_isilive_captions(resolved, *isilive)
        return resolved

    @staticmethod
    async def _add_isilive_captions(
        resolved: ResolvedMeeting, client: str, encoded_file: str
    ) -> None:
        """Attach the caption file iSiLIVE keeps next to this recording,
        by `escribe.py`'s own rule (WO-1155). No caption file leaves
        `resolved` exactly as the plain-file result."""
        # Function-level: escribe.py pulls in bs4 and several adapters,
        # none of which a plain-file resolve otherwise needs.
        from .escribe import find_isilive_captions, isilive_caption_warnings

        async with aiohttp.ClientSession(headers={"User-Agent": _UA}) as session:
            chosen = await find_isilive_captions(session, client, encoded_file)
        if not chosen:
            return
        _vtt_url, cues, language = chosen
        resolved.segments = [TranscriptSegment(**cue) for cue in cues]
        resolved.transcript_language = language
        resolved.transcript_warnings = isilive_caption_warnings(cues, language)

    @staticmethod
    async def _probe_media(media_url: str) -> Tuple[Optional[str], Optional[str]]:
        """`(content_type, media_kind)` for `media_url`. HEAD first, as
        before; `media_kind` is only ever set by the ranged-GET fallback
        (see module docstring's "HEAD refused, or unusable" section), which
        runs for a Dropbox link, a HEAD answering 403/405/501, or a HEAD
        the client can't even parse. A SharePoint share link uses
        `follow_with_cookies()` instead (module docstring)."""
        if is_sharepoint_share_url(media_url):
            try:
                status, content_type, _length = await follow_with_cookies(media_url)
            except (aiohttp.ClientError, TimeoutError):
                return None, None
            return (content_type if status == 200 else None), None
        if not is_dropbox_url(media_url):
            try:
                async with aiohttp.ClientSession(
                    headers={"User-Agent": _UA}
                ) as session:
                    async with session.head(
                        media_url,
                        allow_redirects=True,
                        timeout=aiohttp.ClientTimeout(total=_HEAD_TIMEOUT_SECONDS),
                    ) as resp:
                        if resp.status not in _HEAD_REFUSED_STATUSES:
                            return resp.headers.get("Content-Type"), None
            except aiohttp.ClientResponseError:
                # A malformed HEAD response (Dropbox's shape, see module
                # docstring) -- the ranged GET below is the same test.
                pass
        return await DirectFileAssetFinder._ranged_get_probe(media_url)

    @staticmethod
    async def _ranged_get_probe(
        media_url: str,
    ) -> Tuple[Optional[str], Optional[str]]:
        """`(content_type, media_kind)` from one small ranged GET. Reads
        at most `_PROBE_BYTES` from the stream, so a host that ignores
        `Range` and answers 200 with the whole file never gets downloaded.
        `Accept-Encoding: identity` for the same reason as
        `_laserfiche_classify_media()`: a compressed byte range is a real
        server bug on some hosts."""
        try:
            async with aiohttp.ClientSession(headers={"User-Agent": _UA}) as session:
                async with session.get(
                    media_url,
                    headers={
                        "Range": f"bytes=0-{_PROBE_BYTES - 1}",
                        "Accept-Encoding": "identity",
                    },
                    timeout=aiohttp.ClientTimeout(total=_HEAD_TIMEOUT_SECONDS),
                ) as resp:
                    content_type = resp.headers.get("Content-Type")
                    if resp.status not in (200, 206):
                        return content_type, None
                    chunk = await resp.content.read(_PROBE_BYTES)
        except (aiohttp.ClientError, TimeoutError):
            return None, None
        return content_type, _classify_laserfiche_media(chunk)

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
