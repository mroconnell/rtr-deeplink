"""CivicMedia -- CivicPlus's own video widget, backed by TikiLive's API.
Built WO-341, 2026-09-13, closing the gap `BACKLOG.md` logged for
Hobart, IN (`us:place:1834114`) since WO-336.

## Why this exists

`CLAUDE.md`'s own working convention is "when a platform turns out to be
a wrapper around another, delegate rather than writing a redundant
native parser" (Legistar/CivicPlus -> Granicus, PrimeGov -> YouTube).
CivicMedia is the opposite shape: it's CivicPlus's own FIRST-PARTY video
product (not a wrapper around a third-party vendor a government chose),
so -- unlike an AgendaCenter row that links out to Granicus/Swagit/a
direct file -- `civicplus.py` never had a reason to know about it until
`detect_platform()` recognized the URL shape at all. Before this WO, a
CivicMedia link in an AgendaCenter row's `td.media` cell failed
`CivicPlusAssetFinder._is_real_video_link()`'s `detect_platform() !=
"unknown"` check (see that module's own docstring) and was silently
treated as a row with no video, even on a real tenant serving a real,
captioned meeting.

## The two confirmed real URL shapes (Hobart, IN, `cityofhobart.org`)

1. **The government's own CivicMedia page** -- confirmed live 2026-09-13:
   `https://www.cityofhobart.org/CivicMedia?VID=326` and the equivalent
   `.aspx` form with a full slug, `https://www.cityofhobart.org/
   CivicMedia.aspx?VID=Board-of-Works-09022026-327`. **`VID=` is
   CivicPlus's own CivicMedia page id -- NOT the same id space as
   TikiLive's real `videoId`** (confirmed live: Hobart's `VID=326` page
   embeds `videoId=160547` -- a real, easy trap, since the trailing
   digits after a slug's last `-` LOOK like they could be reused
   directly; `civicmedia_page_id()`/`_video_id_from_url()` below are kept
   as two separate functions specifically so this can't be silently
   conflated again). The real `videoId` is only ever available by
   fetching the page and reading its iframe: `<iframe id="videoPlayer"
   title="Video - Park Board 08-10-26" src="https://civplus.tikiliveapi.
   com/embed?scheme=embedVod&videoId=160547&autoplay=yes">` -- the
   iframe's own `title` attribute is the real per-video title, no JS
   execution needed to read either. The same page also lists up to
   several *other* recent CivicMedia videos on the same tenant as plain
   `<a href="/CivicMedia.aspx?VID=...">` links with real title+duration
   text (e.g. "55:04 HSD Meeting 7-28-2026") -- see `passive_verify.py`'s
   `_civicplus_walker()`, which reuses this as a real listing.
2. **The TikiLive embed itself** -- `https://civplus.tikiliveapi.com/
   embed?scheme=embedVod&videoId={id}&autoplay=...` -- confirmed live to
   be a plain, unauthenticated `aiohttp` GET (no browser needed) whose
   HTML embeds, per real video id:
   - a real HLS master playlist:
     `https://wms.civplus.tikiliveapi.com/vodhttporigin_civplustest/
     {id}/smil:civplustest/encoded_streams/0/928/{id}.smil/playlist.m3u8
     ?...&videoId={id}&stime=...&etime=...&token=...` -- **signed and
     time-limited** (`stime`/`etime` ~24h apart at generation time,
     confirmed by comparing the two query values) -- same "goes stale
     after ingest" shape `boxcast.py`'s own docstring documents for its
     signed HLS playlist, not a new problem class. `refresh_playlist_url()`
     below re-fetches a fresh one at view time, wired into
     `archive/utils/video_refresh.py`'s `NEEDS_REFRESH` the same way
     BoxCast already is.
   - a real closed-caption VTT track, when one exists:
     `https://civplus.tikiliveapi.com/public/files/closed-captions/
     {id[:3]}/{id}_{lang}.vtt` (confirmed live on Hobart's video 160547,
     `_en.vtt`, 2,538 real bytes of genuine dialogue -- this is what
     makes CivicMedia a real tier-1 platform, not just a video host: a
     government using this widget gets captions this app can fetch
     itself, not a lead for the YouTube drip). No adapter/API call is
     needed to construct this URL -- it's a literal `<track>`/`<source>`
     src already in the embed page's own markup, same "no browser, no
     signed config we can't reach" property Wistia's captions endpoint
     has (contrast Vimeo, which cannot be fetched server-side at all --
     see vimeo.py's own module docstring). Only ONE real example is
     confirmed so far (Hobart's video 160547): whether every CivicMedia
     tenant/video carries captions, or only some, is not yet known --
     `resolve()` below reports honestly (a `transcript_warnings` entry)
     when a video has none, per CLAUDE.md's "never claim a caption path
     works without a positive example" rule.

## Which government (WO-1069, 2026-09-25)

Before this, `resolve()` returned no `jurisdiction` at all. Every one of
the Archive's 11 CivicMedia pages still has a government only because
the ingest script that filed it sent a `gov_id` (the Archive files a
caller's `gov_id` as `pinned`, see `archive/db/crud.py`'s
`_caller_pinned_match()`). Any caller that did not send one got "no
government" -- rtr-discovery's live check, 2026-09-25, and Hanover Park,
IL's nine meetings.

The page says who it belongs to. Every CivicMedia page is a CivicPlus
"CivicEngage" site, and all 10 government-hosted pages in the Archive
carry the site's own name twice, confirmed live 2026-09-25:
`<meta property="og:site_name" content="Middleton, MA">` and
`<title>CivicMedia™ • Middleton, MA • CivicEngage</title>`. `_jurisdiction_from_page()` reads the
first, falls back to the second, and runs the name through
`jurisdiction_enrich.enrich_jurisdiction_text()` -- the same path
`proudcity.py` uses for its own `og:site_name` -- so "City of Snyder"
(snydertx.gov, no state in its site name) comes back "City of Snyder,
TX". On all 10 sites the result keys to the same government the Archive
already holds, at `registry` level. Last resort, when the page names
nothing: CivicPlus's own `{state}-{name}.civicplus.com` subdomain rule,
reused from `civicplus.py`.

A bare TikiLive embed URL (Rosetown, SK is the one in the Archive) has
no government page to read -- the embed's own HTML names no tenant --
so it still returns no jurisdiction. That is the honest answer; a caller
filing one must send a `gov_id`.

## What's still unconfirmed

The adapter was built from one real tenant (Hobart, IN). By 2026-09-25
eleven tenants had Archive pages and rtr-discovery's live check resolved
real captions on 6 of 6 meetings across three more sites, so the page
shape is well confirmed; how common the widget is among CivicPlus
customers is still unknown. `detect_platform()`'s registration
of the `/civicmedia` path + `VID=` query shape means any OTHER tenant
using this widget will now be recognized and resolved the same way, so
each new one found strengthens rather than replaces this evidence.
"""

import html as html_module
import re
from typing import List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder
from .models import ResolvedMeeting, TranscriptSegment
from ..utils import jurisdiction_enrich
from ..utils.url_guard import read_capped_text
from ..utils.vtt_parser import (
    detect_language_from_texts,
    is_likely_garbled,
    parse_captions_by_extension,
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    ),
}

_TIKILIVE_HOST = "civplus.tikiliveapi.com"

# The `VID=` value is either a bare numeric id ("326") or a full slug
# ending in one ("Board-of-Works-09022026-327") -- both confirmed live,
# see module docstring. Either way, the trailing run of digits is the
# real id `?VID=` (bare) and the TikiLive embed's own `videoId=` share.
_TRAILING_DIGITS_RE = re.compile(r"(\d+)$")

# The CivicEngage site's own name -- see "Which government" in the module
# docstring. The <title> shape is "{page} • {site name} • CivicEngage".
_SITE_NAME_RE = re.compile(
    r"<meta\s+property=[\"']og:site_name[\"']\s+content=[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
_CIVICENGAGE_TITLE_RE = re.compile(
    r"<title>[^<]*?\u2022\s*([^<\u2022]+?)\s*\u2022\s*CivicEngage\s*</title>",
    re.IGNORECASE,
)

_M3U8_RE = re.compile(r"https?://[^\"'\s]*\.m3u8[^\"'\s]*")
_CAPTION_TRACK_RE = re.compile(r"https?://[^\"'\s]*/closed-captions/[^\"'\s]*\.vtt")


def is_civicmedia_page_url(url: str) -> bool:
    """A government's own `/CivicMedia` or `/CivicMedia.aspx` page with a
    real `VID=` -- the shape `detect_platform()` routes here. Path-based,
    same reasoning as `civicplus.py`'s own `/agendacenter` check: most
    real CivicPlus tenants are white-labeled onto the government's own
    domain, so this can't be a netloc check."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    if not (path == "/civicmedia" or path == "/civicmedia.aspx"):
        return False
    return bool(parse_qs(parsed.query).get("VID") or parse_qs(parsed.query).get("vid"))


def is_tikilive_embed_url(url: str) -> bool:
    return urlparse(url).netloc.lower() == _TIKILIVE_HOST


def civicmedia_page_id(url: str) -> Optional[str]:
    """The `VID=` value's own trailing numeric id (e.g. "327" from either
    a bare `VID=327` or a full slug `VID=Board-of-Works-09022026-327") --
    CivicPlus's own CivicMedia PAGE id. NOT the same id space as
    TikiLive's `videoId` (confirmed live: Hobart's `VID=326` page embeds
    `videoId=160547`) -- kept as its own function so that confusion can't
    silently creep back in; only used for `_civicmedia_walker()`'s own
    de-duplication/sort, never passed to `_embed_url_for_video_id()`."""
    parsed = urlparse(url)
    vid = (
        parse_qs(parsed.query).get("VID") or parse_qs(parsed.query).get("vid") or [None]
    )[0]
    if not vid:
        return None
    match = _TRAILING_DIGITS_RE.search(vid)
    return match.group(1) if match else None


def _video_id_from_url(url: str) -> Optional[str]:
    """TikiLive's own real `videoId` -- only ever present in the TikiLive
    embed URL's own `videoId=` query param (see `civicmedia_page_id()`'s
    docstring for why a CivicMedia page's `VID=` can't be used as a
    shortcut for this). None for a CivicMedia page URL -- the caller must
    fetch the page and read its iframe `src` instead."""
    if not is_tikilive_embed_url(url):
        return None
    return (parse_qs(urlparse(url).query).get("videoId") or [None])[0]


async def _fetch(url: str) -> Tuple[Optional[str], Optional[str]]:
    """`(html, error)` -- error is None on success. Mirrors
    `passive_verify.py`'s own `_fetch()` shape (never raises)."""
    try:
        async with aiohttp.ClientSession(headers=_HEADERS) as session:
            async with session.get(
                url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status != 200:
                    return None, f"HTTP {response.status}"
                return await read_capped_text(response), None
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def _jurisdiction_from_page(html: str, url: str) -> Optional[str]:
    """The government a CivicMedia page belongs to, from the page's own
    site name -- see "Which government" in the module docstring. None
    when the page names nothing and the host isn't a
    `{state}-{name}.civicplus.com` subdomain."""
    match = _SITE_NAME_RE.search(html) or _CIVICENGAGE_TITLE_RE.search(html)
    name = html_module.unescape(match.group(1)).strip() if match else ""
    if name:
        return jurisdiction_enrich.enrich_jurisdiction_text(
            name, netloc=urlparse(url).netloc, page_text=html
        )
    # Imported here: civicplus.py is the bigger module and pulls in the
    # platform registry through base.py; nothing else here needs it.
    from .civicplus import CivicPlusAssetFinder

    return CivicPlusAssetFinder._jurisdiction_from_subdomain(url)


def _embed_url_for_video_id(video_id: str) -> str:
    return (
        f"https://{_TIKILIVE_HOST}/embed?scheme=embedVod&videoId={video_id}&autoplay=no"
    )


class CivicMediaAssetFinder(AssetFinder):
    """Resolves a CivicPlus CivicMedia page (or a bare TikiLive embed URL)
    to its real video + captions. See module docstring for the two real
    URL shapes and how each field is found.
    """

    platform_name = "civicmedia"

    async def resolve(self, url: str) -> ResolvedMeeting:
        title: Optional[str] = None
        jurisdiction: Optional[str] = None
        video_id = _video_id_from_url(url)

        if not is_tikilive_embed_url(url):
            # The government's own CivicMedia page -- fetch it for the
            # real per-video title (the iframe's own `title` attribute,
            # see module docstring) before following through to TikiLive.
            html, err = await _fetch(url)
            if err or html is None:
                return ResolvedMeeting(
                    platform=self.platform_name,
                    source_url=url,
                    video_warnings=[f"We couldn't read this CivicMedia page ({err})."],
                )
            jurisdiction = _jurisdiction_from_page(html, url)
            soup = BeautifulSoup(html, "html.parser")
            iframe = soup.find("iframe", id="videoPlayer") or soup.find(
                "iframe", src=re.compile(re.escape(_TIKILIVE_HOST))
            )
            if iframe is None:
                return ResolvedMeeting(
                    platform=self.platform_name,
                    source_url=url,
                    jurisdiction=jurisdiction,
                    video_warnings=[
                        "This looks like a CivicMedia page, but we couldn't find "
                        "its video player."
                    ],
                )
            raw_title = (iframe.get("title") or "").strip()
            # Confirmed real shape: "Video - Park Board 08-10-26" -- the
            # "Video - " prefix is TikiLive's own boilerplate, not part of
            # the meeting's real title.
            title = re.sub(r"^Video\s*-\s*", "", raw_title).strip() or None
            embed_src = iframe.get("src")
            if not video_id and embed_src:
                video_id = _video_id_from_url(urljoin(url, embed_src))

        if not video_id:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                jurisdiction=jurisdiction,
                video_warnings=[
                    "This looks like a CivicMedia/TikiLive link, but we couldn't "
                    "find a real video id on it."
                ],
            )

        embed_html, embed_err = await _fetch(_embed_url_for_video_id(video_id))
        video_url: Optional[str] = None
        if not embed_err and embed_html:
            m3u8_match = _M3U8_RE.search(embed_html)
            if m3u8_match:
                video_url = m3u8_match.group(0)

        resolved = ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            external_id=f"civicmedia:{video_id}",
            title=title,
            jurisdiction=jurisdiction,
            video_url=video_url,
            video_format="m3u8" if video_url else None,
        )
        if video_url is None:
            resolved.video_warnings = [
                "We found this meeting on CivicMedia, but couldn't find a "
                "playable video stream for it."
            ]

        if not embed_err and embed_html:
            caption_match = _CAPTION_TRACK_RE.search(embed_html)
            if caption_match:
                cues, language = await self._fetch_captions(caption_match.group(0))
                if cues:
                    resolved.segments = [TranscriptSegment(**cue) for cue in cues]
                    resolved.transcript_language = language
                    if language and language != "en":
                        resolved.transcript_warnings = [
                            f"These captions appear to be in '{language}', not "
                            "'en' -- no matching-language track was found for "
                            "this meeting."
                        ]
                    if is_likely_garbled(cues):
                        resolved.transcript_warnings = (
                            resolved.transcript_warnings or []
                        ) + [
                            "This transcript looks garbled at the source (not a "
                            "parsing bug on our end) -- treat it as approximate."
                        ]
        if not resolved.segments and video_url is not None:
            resolved.transcript_warnings = [
                "We couldn't find captions for this meeting on CivicMedia."
            ]
        return resolved

    @staticmethod
    async def _fetch_captions(
        caption_url: str,
    ) -> Tuple[Optional[List[dict]], Optional[str]]:
        body, err = await _fetch(caption_url)
        if err or not body or not body.strip().upper().startswith("WEBVTT"):
            return None, None
        cues, _fallback_text = parse_captions_by_extension("captions.vtt", body)
        if not cues:
            return None, None
        language = detect_language_from_texts(c.get("text") for c in cues) or "en"
        return cues, language


async def refresh_playlist_url(source_url: str) -> Optional[str]:
    """A freshly-signed HLS playlist URL for the video `source_url`
    already names -- WO-341, same "signed and expiring" shape
    `boxcast.py`'s `refresh_playlist_url()` handles (see this module's
    own docstring). Used by `archive/utils/video_refresh.py`'s
    `/m/{slug}/video` redirect so a CivicMedia page keeps playing after
    its stored `video_url`'s signed `etime=` passes. Returns None on any
    failure (no video id found, TikiLive fetch failed, no m3u8 in the
    fresh embed) -- never raises -- so a caller falls back to the page's
    last-known stored `video_url`, same graceful-degradation posture as
    every other signed-URL platform here.
    """
    video_id = _video_id_from_url(source_url)
    if not video_id and not is_tikilive_embed_url(source_url):
        html, err = await _fetch(source_url)
        if err or html is None:
            return None
        soup = BeautifulSoup(html, "html.parser")
        iframe = soup.find("iframe", id="videoPlayer") or soup.find(
            "iframe", src=re.compile(re.escape(_TIKILIVE_HOST))
        )
        if iframe is None or not iframe.get("src"):
            return None
        video_id = _video_id_from_url(urljoin(source_url, iframe["src"]))
    if not video_id:
        return None
    embed_html, err = await _fetch(_embed_url_for_video_id(video_id))
    if err or not embed_html:
        return None
    match = _M3U8_RE.search(embed_html)
    return match.group(0) if match else None
