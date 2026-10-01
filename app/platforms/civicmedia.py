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
   iframe's own `title` attribute is the TikiLive upload's name, no JS
   execution needed to read either (the page's `og:title` is the
   government's own name for the meeting and now comes first -- see
   "Which title" below). The same page also lists up to
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
so it still returns no jurisdiction. That is the honest answer. Its
channel, below, lets a pin name the government; without a pin, a caller
filing one must send a `gov_id`.

## Which channel (2026-09-29)

TikiLive files each customer's videos under a channel number, `chid`.
The embed URL names only the video, but the signed stream address the
embed page hands out carries the channel: Hobart, IN's video 160547
streams from `...playlist.m3u8?p=vodcdn&chid=93145&...&videoId=160547`
(`tests/fixtures/civicmedia/tikilive_embed_160547.html`). `resolve()`
already fetches that page for the stream, so reading the chid costs no
extra request. It goes out as `video_channel` = `civicmedia:{chid}`, the
same pin hint BoxCast uses (`boxcast:{channel}`), and a
`tenant_overrides.csv` row `civplus.tikiliveapi.com,channel=civicmedia:
{chid},...` then names the government for a bare embed. Channel 0 is
skipped: the 2026-09-29 number walk found videos from many owners in it
(`tenant_key.CIVICMEDIA_MIXED_CHANNELS`). The pins came from that walk's
channel matches, confirmed ones only (rtr-business
`research/slug_learning_2026-09-27/civicmedia_channels/`).

## Which title (WO-1165, 2026-09-29)

Until WO-1165 the title came from the player: the iframe's `title`
attribute, "Video - {name}". That name is the TikiLive upload's name,
not the government's. The 2026-09-29 CivicMedia routing round (rtr-
business `research/slug_learning_2026-09-27/civicmedia_channels/
routing/`) read 35 government `VID=` pages. On 11 of them both titles
were present and they differed. Real cases:

| Page | Government's og:title | Player title |
|---|---|---|
| Isanti County, MN, `VID=461` | Live Stream Committee of the Whole - July 14, 2026 | Autorecord Jul 14 2026, 10:18 AM |
| Seagoville, TX, `VID=...-719` | 2025-05-19 Regular Session (Part 2) | 2025-05-19 Regular Session (Part 3) |
| Northampton, MA, `VID=BOH_011923-13` | BOH_011923 | DHHS_Amy_video060923 |
| St. Joseph, MO, `VID=...-1` | St. Joseph Stormwater Protection and Inspection Me | St. Joseph Stormwater Protection and Inspection Meeting 2025 |

So `_title_from_page()` now takes, in order:

1. The page's `og:title`. CivicPlus cuts it at 50 characters (St.
   Joseph above), so when the player title is the same words, only
   longer, the player's full version is used instead.
2. The page's `<title>`, minus the " • {site} • CivicEngage" suffix. On
   every page seen so far that leaves just "CivicMedia™", which is
   boilerplate and is skipped, so this step is a safety net only.
3. The player title, as before.

A title that looks like a file name is skipped at each step
(`looks_like_file_name()`): it has an underscore, has no space, carries a
video or audio extension (".m4v", Irwindale's player title), or starts
with "Autorecord" (a recorder's default name: Isanti, Fort Madison,
Corsicana, St. Clair Shores, Phillipsburg). If every step looks like a
file name, the first non-empty one is kept anyway. A weak title beats
none: a page with no title gets a slug that is just the place name.

A bare TikiLive embed has no government page, so its title is unchanged:
none. The embed page itself names no video. Getting the government's
title for one would need the government's `VID=` page, and `VID=` is not
derivable from TikiLive's `videoId` (see above), so there is no cheap
lookup. `BACKLOG.md` carries this as a follow-up.

## Which title (video page, WO-1172, 2026-09-30)

TikiLive's own video page, `https://civplus.tikiliveapi.com/video/{id}`,
has the title the embed page lacks. Checked live 2026-09-30 on video
144112: `<title>260 - City Council Meeting 12.17.20.</title>`, repeated in
`og:title`. The page also holds the HLS stream, `chid=146` and
`videoId=144112` in its address (fixtures `tikilive_video_144112.html`
and `tikilive_embed_144112.html`). The CivicMedia number walk collected
`/video/{id}` links, so this form must resolve.

- A `/video/{id}` URL is accepted and gives the same `videoId` as the
  embed form. Stream and captions still come from the embed page.
- For either TikiLive form, one extra request reads the video page for
  its title. If that request fails, the title stays None and nothing
  else changes. A government `VID=` page keeps its own title rules above.
- The leading "260 - " upload counter is stripped from the title (WO-1174,
  `strip_upload_counter()`); the rest is kept as the page has it.
- The channel comes from the embed stream's `chid`; when the embed has no
  stream, the video page's stream is tried.

## Category pages (`?CID=`, WO-1173, 2026-09-30)

`https://{tenant}.civicplus.com/CivicMedia?CID={n-or-slug}` is a CATEGORY
page: a list of videos in one channel, not one video. Until WO-1173 it
was not recognised as CivicMedia at all, fell through to the CivicPlus
AgendaCenter adapter and failed with "found no real video link".

The page embeds ONE player (whichever video is "Now Playing") and lists
the rest as `div.video` blocks: an `<a href="/CivicMedia.aspx?VID=...">`
with the title in an `<h3>`. The "Now Playing" block has no link; its own
`VID=` is the page's `og:url`. Real trap, confirmed live 2026-09-30:
Evergreen Park, IL's `CID=3` is a parks-and-recreation channel, and the
video its player loads is "Preschool Welcome Video". So `resolve()` never
reads the player on a category page. It lists the videos, keeps only
those whose title looks like a meeting (`looks_like_real_meeting()` with
the allowlist, plus Meeting Finder's own weak-title check), and raises
`CalendarPageError` with those as the pick-list. When none qualifies the
error carries no candidates and says "category lists N videos, none looks
like a meeting". Hobart, IN's `CID=City-of-Hobart-Public-Meetings-4`
lists council, commission and board meetings (8 videos on the first
page; the page goes further back through a postback this adapter does not
follow). The page gives no dates; the order is newest first by `VID` id.

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

from .base import AssetFinder, CalendarCandidate, CalendarPageError
from .models import ResolvedMeeting, TranscriptSegment
from ..utils import jurisdiction_enrich
from ..utils.tenant_key import civicmedia_chid
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

# Title rules -- see "Which title" in the module docstring.
_FILE_EXTENSION_RE = re.compile(
    r"\.(?:mp4|m4v|mov|wmv|avi|mpe?g|flv|mkv|webm|mp3|wav|m4a)\b", re.IGNORECASE
)
_AUTORECORD_RE = re.compile(r"auto\s*-?\s*record", re.IGNORECASE)
_BOILERPLATE_PAGE_TITLE_RE = re.compile(r"^CivicMedia\W*$", re.IGNORECASE)

# TikiLive's own video page: /video/{id}. Same videoId as the embed form.
_VIDEO_PAGE_PATH_RE = re.compile(r"^/video/(\d+)/?$")
_OG_TITLE_RE = re.compile(
    r"<meta\s+[^>]*property=[\"']og:title[\"'][^>]*content=[\"']([^\"']*)[\"']",
    re.IGNORECASE,
)
_HTML_TITLE_RE = re.compile(r"<title>([^<]*)</title>", re.IGNORECASE)

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


def is_civicmedia_category_url(url: str) -> bool:
    """A `/CivicMedia` or `/CivicMedia.aspx` CATEGORY page (`?CID=`) with
    no `VID=`: a list of videos, not one video. See "Category pages" in
    the module docstring. `CID=` with an empty value still counts (real:
    `CivicMedia?CID=` on several tenants)."""
    parsed = urlparse(url)
    if parsed.path.lower() not in ("/civicmedia", "/civicmedia.aspx"):
        return False
    query = {k.lower() for k in parse_qs(parsed.query, keep_blank_values=True)}
    return "cid" in query and "vid" not in query


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
    fetch the page and read its iframe `src` instead. Two TikiLive forms
    carry it: the embed's `videoId=` and the video page's `/video/{id}`
    path (WO-1172)."""
    if not is_tikilive_embed_url(url):
        return None
    parsed = urlparse(url)
    page_match = _VIDEO_PAGE_PATH_RE.match(parsed.path)
    if page_match:
        return page_match.group(1)
    return (parse_qs(parsed.query).get("videoId") or [None])[0]


def _video_page_url(video_id: str) -> str:
    return f"https://{_TIKILIVE_HOST}/video/{video_id}"


_UPLOAD_COUNTER_RE = re.compile(r"^\s*\d+\s*-\s+")


def strip_upload_counter(title: Optional[str]) -> Optional[str]:
    """Drop the leading "NNN - " upload counter from a TikiLive title
    (WO-1174). TikiLive numbers each channel's uploads and puts the number
    first: "260 - City Council Meeting 12.17.20.", "1009 - 2026 Proposed
    Budget Presentation". The number says nothing about the meeting.

    Only the first "NNN - " goes, so a year that follows the counter stays
    ("1009 - 2026 Proposed Budget Presentation" -> "2026 Proposed Budget
    Presentation"). A 4-digit number such as "2026" or "1999" in the
    counter position is still a counter and is stripped: counters pass
    1000 on busy channels, so a year-shaped number cannot be told apart
    from one, and treating all digits the same keeps the rule consistent
    ("2026 - Budget" -> "Budget"). A number inside the title ("Budget 2026
    - Draft") is not leading, so it stays. A title with no counter, or one
    that would be empty after stripping ("12 - "), is returned unchanged.
    File-name titles ("BudgetHearing_11292022") are left alone on purpose.
    Used for TikiLive titles only; a government `VID=` page's title rules
    (WO-1165) never call this."""
    if not title:
        return title
    stripped = _UPLOAD_COUNTER_RE.sub("", title, count=1).strip()
    return stripped or title


def _title_from_video_page(html: str) -> Optional[str]:
    """The title on TikiLive's own `/video/{id}` page -- see "Which title
    (video page)" in the module docstring. `og:title`, else `<title>`,
    with the leading upload counter stripped (`strip_upload_counter`)."""
    match = _OG_TITLE_RE.search(html) or _HTML_TITLE_RE.search(html)
    return strip_upload_counter(_clean_title(match.group(1))) if match else None


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


def _clean_title(text: Optional[str]) -> Optional[str]:
    """Unescaped, whitespace collapsed, None when empty. Real case: St.
    Clair Shores' og:title is "City Council Meeting -  Sep. 21, 2026",
    with two spaces."""
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", html_module.unescape(text)).strip()
    return cleaned or None


def looks_like_file_name(title: Optional[str]) -> bool:
    """True for a title that is really an upload's file name or a
    recorder's default name -- see "Which title" in the module docstring
    for the real cases behind each rule. An empty title counts too."""
    if not title:
        return True
    if "_" in title or not re.search(r"\s", title):
        return True
    if _FILE_EXTENSION_RE.search(title):
        return True
    return bool(_AUTORECORD_RE.match(title))


def _title_from_page(soup: BeautifulSoup, iframe) -> Optional[str]:
    """The meeting's title on a government's own CivicMedia page -- see
    "Which title" in the module docstring for the order and why."""
    og = soup.find("meta", attrs={"property": "og:title"})
    og_title = _clean_title(og.get("content") if og else None)

    page_title = None
    head_title = soup.head.find("title") if soup.head else soup.find("title")
    if head_title is not None:
        # "{page} • {site name} • CivicEngage" -- keep only the page part.
        first = _clean_title(head_title.get_text().split("•")[0])
        if first and not _BOILERPLATE_PAGE_TITLE_RE.match(first):
            page_title = first

    player_title = _clean_title(
        re.sub(r"^\s*Video\s*-\s*", "", iframe.get("title") or "")
    )

    # CivicPlus cuts og:title at 50 characters. When the player's title
    # is the same words, only longer, the player's is the full version.
    if (
        og_title
        and player_title
        and len(player_title) > len(og_title)
        and player_title.casefold().startswith(og_title.casefold())
    ):
        og_title = player_title

    candidates = [og_title, page_title, player_title]
    for candidate in candidates:
        if not looks_like_file_name(candidate):
            return candidate
    # Every candidate looks like a file name: keep the first one anyway.
    # A weak title still beats none, because a page with no title gets a
    # slug that is just the place name.
    return next((c for c in candidates if c), None)


def _category_videos(html: str, page_url: str) -> List[Tuple[str, str]]:
    """`(title, url)` for every video a category page lists, newest first
    (by `VID` page id, the order the page itself uses). Includes the
    "Now Playing" block, which has no link: its URL is the page's
    `og:url`. Never reads the embedded player -- see "Category pages"."""
    soup = BeautifulSoup(html, "html.parser")
    og_url = soup.find("meta", attrs={"property": "og:url"})
    now_playing_url = og_url.get("content") if og_url else None
    videos: List[Tuple[str, str]] = []
    seen: set = set()
    for block in soup.select("div.video"):
        heading = block.find("h3")
        title = _clean_title(heading.get_text() if heading else None)
        link = block.find("a", href=re.compile(r"VID=", re.IGNORECASE))
        if link is not None:
            url = urljoin(page_url, link["href"].split("#")[0])
        elif now_playing_url and is_civicmedia_page_url(now_playing_url):
            url = now_playing_url
        else:
            continue
        if not title or url in seen:
            continue
        seen.add(url)
        videos.append((title, url))
    videos.sort(key=lambda v: -int(civicmedia_page_id(v[1]) or 0))
    return videos


def _looks_like_meeting_title(title: str) -> bool:
    """Meeting Finder's own title rules, not new ones: a governing-body
    word (`looks_like_real_meeting(..., require_allowlist=True)`, the same
    strict check used for a generic scan of a video host) and not a
    minutes link or a demo row (`pick._looks_like_a_real_meeting_candidate`).
    Strict on purpose: a category is a channel of anything the government
    films (parades, graduations), so no governing-body word means no."""
    # Local import: meeting_finder pulls in most of the platform package.
    from .meeting_finder.pick import _looks_like_a_real_meeting_candidate
    from ..utils.video_hand_check import looks_like_real_meeting

    return looks_like_real_meeting(
        title, require_allowlist=True
    ) and _looks_like_a_real_meeting_candidate(title)


def category_candidates(
    html: str, page_url: str
) -> Tuple[int, List[CalendarCandidate]]:
    """`(how many videos the category lists, the meeting-like ones)`."""
    videos = _category_videos(html, page_url)
    meetings = [
        CalendarCandidate(title=title, date="", url=url)
        for title, url in videos
        if _looks_like_meeting_title(title)
    ]
    return len(videos), meetings


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
        if is_civicmedia_category_url(url):
            await self._raise_category_listing(url)
        title: Optional[str] = None
        jurisdiction: Optional[str] = None
        video_id = _video_id_from_url(url)

        if not is_tikilive_embed_url(url):
            # The government's own CivicMedia page -- fetch it for the
            # meeting's title ("Which title" in the module docstring) and
            # the player iframe before following through to TikiLive.
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
            title = _title_from_page(soup, iframe)
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

        # TikiLive's own video page carries the title the embed lacks
        # (WO-1172). A failed fetch just leaves the title as it was.
        page_html: Optional[str] = None
        if is_tikilive_embed_url(url):
            page_html, _page_err = await _fetch(_video_page_url(video_id))
            if page_html:
                title = _title_from_video_page(page_html)

        embed_html, embed_err = await _fetch(_embed_url_for_video_id(video_id))
        video_url: Optional[str] = None
        if not embed_err and embed_html:
            m3u8_match = _M3U8_RE.search(embed_html)
            if m3u8_match:
                video_url = m3u8_match.group(0)

        # The customer's channel, from the stream address's own `chid=` --
        # see "Which channel" in the module docstring. A pin hint only,
        # never page identity, same as BoxCast's `video_channel`.
        chid = civicmedia_chid(video_url) if video_url else None
        if not chid and page_html:
            page_m3u8 = _M3U8_RE.search(page_html)
            chid = civicmedia_chid(page_m3u8.group(0)) if page_m3u8 else None
        resolved = ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            external_id=f"civicmedia:{video_id}",
            title=title,
            jurisdiction=jurisdiction,
            video_url=video_url,
            video_format="m3u8" if video_url else None,
            video_channel=f"civicmedia:{chid}" if chid else None,
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
    async def _raise_category_listing(url: str) -> None:
        """A `?CID=` category page lists videos; it is never one video.
        Always raises `CalendarPageError` (see "Category pages")."""
        html, err = await _fetch(url)
        if err or html is None:
            raise CalendarPageError(
                f"We couldn't read this CivicMedia category page ({err}).", []
            )
        total, meetings = category_candidates(html, url)
        hint = _jurisdiction_from_page(html, url)
        if not meetings:
            raise CalendarPageError(
                f"This CivicMedia category lists {total} videos, none looks "
                "like a meeting.",
                [],
                jurisdiction_hint=hint,
            )
        raise CalendarPageError(
            f"This CivicMedia category lists {total} videos, "
            f"{len(meetings)} look like meetings. Pick one.",
            meetings,
            jurisdiction_hint=hint,
        )

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
