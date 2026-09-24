import asyncio
import json
import logging
import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import parse_qs, urljoin, urlparse

import aiohttp

from .base import AssetFinder
from .models import AlternateTranscript, ResolvedMeeting, TranscriptSegment
from ..utils import jurisdiction_enrich
from ..utils.vtt_parser import (
    decode_vtt_bytes,
    detect_language_from_texts,
    normalize_shouting_caption,
    parse_vtt,
)

logger = logging.getLogger("rtr_deeplink.cablecast")

TARGET_LANGUAGE = "en"

# Detroit, MI's Cablecast video portal (detroit-vod.cablecast.tv) --
# confirmed live 2026-08-12, found while investigating why an earlier
# Wave 2 research pass's specific sample URL for Detroit was unreachable
# (see BACKLOG.md/BACKLOG_DONE.md for the full dead-end-that-wasn't
# investigation). Real findings this adapter is built on:
#
# - The portal's own HTTPS (port 443) hangs indefinitely for the entire
#   domain (confirmed via direct curl: HTTPS times out at 15s+, plain
#   HTTP responds in under a second) -- Detroit's own city website
#   (detroitmi.gov) links this portal with a plain http:// URL, not
#   https://, matching that reality rather than a mistake. `resolve()`
#   always fetches over HTTP regardless of what scheme was pasted, so a
#   real https:// paste (the more natural thing for someone to type/paste)
#   doesn't hang the whole resolve.
# - A show page (`/internetchannel/show/{id}?site=1`) is a Remix.js
#   (React) SSR app -- all the real data, for the requested show *and* a
#   "related shows" carousel of ~35 others, is embedded as one JSON blob
#   in `window.__remixContext = {...};`. `_find_show()` recursively
#   searches that whole tree for the object whose own `showId` matches
#   the URL's, rather than assuming a fixed key path -- Remix's loader
#   data nesting is keyed by route id, not something worth hardcoding.
# - The real video is a direct, unauthenticated `.m3u8` (HLS) URL on a
#   *different* subdomain (`reflect-detroit-vod.cablecast.tv`, confirmed
#   reachable over HTTPS just fine -- only the portal domain itself hangs)
#   -- already fully supported by this app's existing hls.js pathway
#   (`video_format="m3u8"`), no new frontend work needed.
# - `vodTranscripts` was an empty `[]` on every one of 36 Detroit shows
#   checked originally, but a real, populated, fetchable example was found
#   2026-08-12 on a real Charlotte show (`show/2451`) -- a real
#   `{languageCode, url}` entry pointing at a plain-text transcript file.
#   That file's own shape (confirmed live, not guessed): one real cue per
#   block, `HH:MM:SS,mmm<TAB>ALL CAPS TEXT`, blank-line-separated, real
#   `\r\n` line endings -- NOT SRT (no sequence-number lines, no `-->`
#   end-time range, just a single start timestamp per block) despite the
#   URL's own `.txt` extension, so it's parsed here directly
#   (`_parse_transcript()`) rather than through `vtt_parser.py`'s shared
#   extension-based dispatch -- routing a Cablecast-specific format
#   through that generic `.txt` fallback would also incorrectly capture
#   every OTHER platform's generic plain-text caption fallback. No
#   explicit end time per cue; each cue's end is the next cue's start
#   (same convention Granicus's AgendaViewer.php chapter markers already
#   use for the same "only a start time is given" shape).
#
# Deliberately scoped to this specific portal template (Remix-based
# `/internetchannel/show/{id}` pages), not a general "any *.cablecast.tv
# domain" rule. An early investigation (before Charlotte was confirmed)
# suspected Charlotte's site used a visibly different, non-Remix
# "DOWNLOADS"-tab template -- that suspicion was wrong: Charlotte's real
# `/internetchannel/show/{id}` pages (e.g. show/2451, see the
# vodTranscripts note above) use the exact same Remix template as
# Detroit's, and both are now confirmed handled by this one adapter (see
# CablecastAssetFinder's own docstring). Still scoped to this template
# specifically, not a blanket *.cablecast.tv rule, since Cablecast is a
# multi-tenant product and a still-unconfirmed customer could genuinely
# use a different portal template -- just not Charlotte.
_SHOW_ID_RE = re.compile(r"/internetchannel/show/(\d+)")

# A newer Cablecast portal template drops the "/internetchannel" prefix
# entirely -- confirmed live 2026-08-18 on satellitebeach.cablecast.tv,
# found while re-checking a research pass's "miss" list of ~211 Cablecast
# customer subdomains against this adapter. That site's real show pages
# live at bare "/show/{id}" (no "/internetchannel"); the *old*-style
# "/internetchannel/show/{id}" path 404s outright on this template. Two
# real complications, not just a URL-shape change:
#   1. "/show/{id}" itself is behind an AWS WAF JS challenge for
#      non-browser requests (confirmed: a plain GET gets a 202 with an
#      empty body and an `awsWafCookieDomainList`/challenge.js page, not
#      real content) -- this adapter does not attempt to solve or bypass
#      that challenge (out of scope/prohibited); it never even tries that
#      URL directly.
#   2. The site's ROOT page ("/") is NOT behind that WAF challenge, and
#      its own `window.__remixContext` already embeds a large "related
#      shows" catalog -- confirmed real on satellitebeach: 287 real shows
#      spanning 2019-08-24, most with populated `vodUrl`, several with
#      real `vodTranscripts` -- more than enough to find any given show by
#      id without ever touching the blocked path. So `resolve()` falls
#      back to fetching root and searching *that* page's remix data
#      whenever the direct fetch doesn't yield the requested show (see
#      `_ROOT_FALLBACK` handling below) -- covers both this WAF case and
#      an old-style URL simply 404ing on a migrated customer.
_SHOW_ID_SHORT_RE = re.compile(r"^/show/(\d+)")
_REMIX_CONTEXT_RE = re.compile(
    r"window\.__remixContext\s*=\s*(\{.*?\});</script>", re.DOTALL
)

# A gallery page (`/internetchannel/gallery/{id}`) -- Cablecast's own
# per-category/per-town LISTING view on a shared, multi-tenant Remix
# portal, found live 2026-09-23 (Ryan, hand-checking a batch of CivicPlus
# governments whose AgendaCenter has no video): reflect-vsctv.cablecast.tv
# is one shared Cablecast tenant serving FOUR distinct Connecticut towns
# by gallery id (22=Old Saybrook, 10=Haddam, 9=Deep River, 3=Clinton),
# each town's own real, current meeting videos filed under its own
# gallery rather than a per-town subdomain. Before this fix these URLs
# resolved by accident, through `generic_fallback.py`'s
# `find_platform_link()` grabbing whichever `/internetchannel/show/{id}`
# link happened to appear first in the page's raw HTML -- not necessarily
# the newest meeting, and fragile: confirmed live the same day that a
# single gallery page already lists 50 real shows with real pagination
# beyond that (Old Saybrook's alone), so "first link in the DOM" is not a
# considered choice.
#
# Confirmed live: a gallery page's `window.__remixContext` embeds the
# SAME kind of show catalog the root-page "related shows" carousel does
# (see `_SHOW_ID_SHORT_RE`'s own module note above) -- 234 distinct real
# shows for Old Saybrook's gallery/22 alone, each already carrying a real
# `title`, `eventDate` and (when ready) `vodUrl` with no extra fetch
# needed to know WHICH show is newest.
#
# WO-1036 (2026-09-23, Ryan confirmed): the prefix-dropped bare
# `/gallery/{id}` shape IS real after all -- Champaign, IL's real City
# Council hub is `champaign-cablecast.cablecast.tv/gallery/4`, linked
# from `champaignil.gov`'s own homepage nav as "Meeting Recordings". Same
# underlying Remix gallery mechanism as the `/internetchannel/gallery/`
# form above (the optional `(?:/internetchannel)?` prefix is the only
# difference) -- `_resolve_gallery()`'s own re-resolve through a show's
# canonical `/internetchannel/show/{id}` URL doesn't depend on which
# gallery-path shape was used to reach it, so no other change was needed
# there.
_GALLERY_ID_RE = re.compile(r"(?:/internetchannel)?/gallery/(\d+)")

# "Cablecast Connect" -- a WordPress plugin some PEG-access nonprofits use
# to embed a Cablecast tenant's player on their own site (WO-1036,
# 2026-09-23). Real hosts confirmed live: `reflect-tst-mn.cablecast.tv/
# watch-vod-embed?showId=5964&site=8` (Mendota Heights, MN's real video,
# wrapped via townsquare.tv) and the same shape on
# `reflect-dakotamediaaccess.cablecast.tv` (Bismarck, ND). The plugin's
# iframe `src` already carries `showId`/`site` directly -- no separate
# `/show/{id}` page exists to derive them from -- so this is resolved
# through the same FastBoot `/embed/vod?show=&site=` endpoint
# `_resolve_fastboot_embed()` already knows how to read, not a new
# scraping path.
_WATCH_VOD_EMBED_PATH_RE = re.compile(r"/watch-vod-embed\b", re.I)

# The SAME show's `eventDate` is formatted completely differently between
# a gallery listing and that show's own dedicated page -- confirmed live
# 2026-09-23 on Old Saybrook show 7413, present on both:
#   gallery/22's embedded catalog: "7/14/2026 12:00:00 AM"
#   show/7413's own page:          "2026-07-14T00:00:00-04:00" (real ISO,
#                                   what `_format_date()` above expects)
# So a gallery's own `eventDate` is only ever used here to pick the
# NEWEST show for sorting -- `_resolve_gallery()` always re-resolves
# through the winning show's own canonical `/internetchannel/show/{id}`
# URL afterward (reusing the existing, already-correct show path in
# full, transcript fetch included) rather than trying to build a
# `ResolvedMeeting` directly from the gallery's own differently-shaped
# data.
_GALLERY_EVENT_DATE_FORMAT = "%m/%d/%Y %I:%M:%S %p"

# A third, genuinely different real Cablecast portal template --
# "CablecastPublicSite" (an Ember.js app, not Remix) -- found via a
# 2026-08-29 wildcard-free DNS sweep and confirmed live on two independent
# tenants (urbana.cablecast.tv, smyrna.cablecast.tv, both real government
# meetings: Cunningham Township Board/City Council and a Smyrna Beer Board
# meeting respectively). Real show pages live at
# "/CablecastPublicSite/show/{id}?site=1". Deliberately NOT scraped the
# way the Remix templates are -- this template's real content is
# JS-rendered client-side (confirmed: the raw HTML has no video/vod data
# anywhere), but a plain, open, unauthenticated JSON API sits underneath
# it and is what the app itself calls:
#   GET {netloc}/cablecastapi/v1/shows/{id}  -> title, eventDate, vods[]
#   GET {netloc}/cablecastapi/v1/vods/{id}   -> direct .../vod.mp4 url
# Confirmed this same API also answers identically on an existing
# Remix-template tenant (Charlotte) -- it looks like a universal Cablecast
# backend API, not something specific to this template -- but that's a
# separate refactor question, deliberately not pursued here; this stays
# scoped to giving the CablecastPublicSite template a working path.
# No captions available via this API even when a show's own record says
# `hasCaptions: true` (confirmed on Charlotte's known-transcript show:
# the API's own `webVtt` field points at a real but empty
# "WEBVTT FILE" response) -- unlike the Remix template's `vodTranscripts`
# mechanism, there is no confirmed transcript source for this template at
# all yet, so `resolve()` degrades to no-transcript honestly rather than
# guessing at one.
_PUBLICSITE_SHOW_ID_RE = re.compile(r"/CablecastPublicSite/show/(\d+)")

# WO-344: a THIRD, genuinely different real shape -- not a different
# vendor product, the same "cablecast-public-site" Ember/FastBoot app as
# above, but mounted at a custom domain's own ROOT (bare `/show/{id}
# ?site=N`, no `/CablecastPublicSite/` prefix) with its own subdomain's
# JSON API 404ing, so `_resolve_publicsite()`'s own API calls can't reach
# it -- confirmed live 2026-09-13 on Dyersville, IA
# (`city-dyersville-ia.cablecast.tv/show/3660?site=1`, real "City Council
# Meeting 2026-09-08" content, filed as an adapter gap in WO-309 (resume),
# BACKLOG.md). The SAME bare `/show/{id}` URL shape is also what the
# newer Remix template uses (satellitebeach.cablecast.tv, see
# `_SHOW_ID_SHORT_RE` above) and what Huron charter Township, MI's tenant
# uses -- Huron already resolves fine via the plain Remix path despite
# the identical URL, so this is a FALLBACK, tried only once the Remix
# path (including its own root-fallback retry) has already failed to
# find the show, never a first choice.
#
# Two real things make this template's own video/captions reachable with
# no headless browser at all, confirmed live via
# `mcp__Claude_Browser__read_network_requests` on Dyersville's real show
# page (the raw HTML has no video/caption data anywhere -- Ember renders
# client-side, same as CablecastPublicSite):
#
# 1. `GET {origin}/embed/vod?show={id}&site={site}` -- a plain,
#    unauthenticated, non-JS HTML fragment (confirmed fetches fine via a
#    bare `curl`/`aiohttp` GET, not just via the browser) that the site's
#    own video-js player iframe loads. It embeds a
#    `window.TRMS = {siteId, showTitle, showId, ...}` object and a
#    `<source src="{vod_base}/vod.m3u8">` tag -- everything needed for
#    title and video. No `eventDate` field of its own; Dyersville's real
#    `showTitle` already carries the date as literal text ("City Council
#    Meeting 2026-09-08"), extracted separately below rather than assumed
#    to always be the last word of the title (kept honest as best-effort:
#    if no `YYYY-MM-DD` is found in the title, date stays `None`, the same
#    "don't guess" posture as `_format_date()`'s own ValueError handling).
# 2. The `vod.m3u8` HLS master playlist itself declares a real subtitle
#    track inline -- `#EXT-X-MEDIA:TYPE=SUBTITLES,...,URI="captions.en.
#    m3u8",LANGUAGE="en"` -- confirmed real and populated on the same
#    Dyersville show (221 ten-second `.vtt` segments, real spoken-word
#    content, e.g. "Does anyone have any questions on the bills as
#    presented?"). Each segment's own WEBVTT cue timestamps are already
#    ABSOLUTE (segment 10 of 10s each starts its cues at 00:01:40, i.e.
#    10*10s), not segment-relative -- confirmed by comparing a segment's
#    own `#EXTINF` position in the subtitle playlist against its cues'
#    timestamps -- so no per-segment time offset is needed, only
#    concatenation (`_fetch_fastboot_captions()` still dedupes identical
#    (start, text) pairs defensively, in case a future tenant's segments
#    do overlap at the boundary; unconfirmed on Dyersville's own real
#    track, which showed no such overlap).
#
# This is the SAME underlying Ember app ("cablecast-public-site", visible
# in the root page's own `<meta name="cablecast-public-site/config/
# environment">` tag) as `_resolve_publicsite()` targets -- just mounted
# differently, with its data reached through the embed/HLS path instead
# of the `cablecastapi/v1/` JSON API. Kept as a separate resolve branch
# rather than merged into `_resolve_publicsite()`, since that function's
# whole contract is "no HTML scraping, two JSON calls" and this one is
# the opposite.
_FASTBOOT_EMBED_SHOW_TITLE_RE = re.compile(r"showTitle:\s*'((?:[^'\\]|\\.)*)'")
_FASTBOOT_EMBED_SOURCE_RE = re.compile(r'<source\s+src="([^"]+\.m3u8[^"]*)"')
_FASTBOOT_TITLE_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_FASTBOOT_SUBTITLE_URI_RE = re.compile(
    r'#EXT-X-MEDIA:TYPE=SUBTITLES,[^\n]*URI="([^"]+)"[^\n]*LANGUAGE="([a-zA-Z-]+)"'
)
_FASTBOOT_SEGMENT_URI_RE = re.compile(r"^(?!#)(\S+\.vtt(?:\?\S*)?)\s*$", re.MULTILINE)
# Real, confirmed cost of this shape: a ~37-minute Dyersville meeting
# (show 3660) is already 221 ten-second caption segments -- a 90-minute
# meeting could be ~540. Fetched with bounded concurrency, not serially,
# same "walk cost is real, bound it" posture as this module's other
# network loops (`asyncio.gather()` over `vodTranscripts` above).
_FASTBOOT_CAPTION_CONCURRENCY = 10
# A FastBoot root page's own real show listing (see the listing-walker
# note in `passive_verify.py`) is server-rendered newest-first -- capped
# here too so a resolve() call on a single already-known show URL never
# needs it; this constant exists for the listing walker, kept next to the
# rest of this template's constants since it's part of the same real
# investigation.
_FASTBOOT_SHOW_LINK_RE = re.compile(r'href="(/show/\d+(?:\?[^"]*)?)"')

# Confirmed live 2026-08-29: this API answers over HTTPS on some tenants
# (urbana) and only over plain HTTP on others (smyrna -- HTTPS times out
# outright on port 443, the same asymmetry the Remix template's own
# portal domain already has, see _force_http() above). Tries HTTPS first
# since it's the more common real case, falls back to HTTP on any
# failure rather than assuming either scheme for an unconfirmed tenant.
_PUBLICSITE_SCHEMES = ("https", "http")

# Confirmed live 2026-08-29 on both CablecastPublicSite tenants checked:
# no jurisdiction-bearing text anywhere -- og:title/twitter:title/meta
# description are all just channel branding ("Urbana Public Television"),
# on both the site root and a real show page. No text-extraction attempt
# here at all (unlike the Remix path's _JURISDICTION_RE), since there is
# no confirmed signal to extract -- jurisdiction for this template comes
# only from jurisdiction_enrich's known-domain registry (see
# jurisdiction_enrich.py's own comment on the two entries added for this).

# Real bug fixed 2026-08-12: this used to be a single hardcoded
# "Detroit, MI" constant applied to *every* Cablecast customer, confirmed
# wrong live on a real Charlotte, NC meeting (resolved everything else
# correctly -- title, date, video -- but jurisdiction was Detroit's).
# site.title turns out to be plain TV-channel branding, not reliably
# city-shaped -- confirmed live on Detroit's real site ("Channel 10", no
# "Detroit" anywhere in it) -- but site.pageDescription's prose names the
# real city on both real customers checked so far: Detroit's opens "The
# City of Detroit's Channel 10 features...", Charlotte's includes "The
# City of Charlotte is committed to...". Tried first; falls back to
# title for a customer whose description doesn't follow this shape.
#
# Single word only, deliberately -- both real customers confirmed so far
# (Detroit, Charlotte) are one-word city names, and title's own trailing
# branding words ("... GOV Channel") would otherwise get greedily pulled
# in as if they were part of a real multi-word city name. Revisit if a
# real multi-word-city customer (e.g. "City of Fountain Valley") turns up.
_JURISDICTION_RE = re.compile(r"\b(?:City|County|Town) of ([A-Z][a-zA-Z]+)\b")

# Cablecast's own page data has no state field anywhere, and no reliable
# domain-based signal either (neither "charlotte.cablecast.tv" nor
# "detroit-vod.cablecast.tv" encodes a state) -- state is filled in via
# jurisdiction_enrich.resolve_state() below, which tries (1) the shared
# confirmed-domain registry (real, necessary here: both "Detroit" and
# "Charlotte" are genuinely ambiguous nationally -- real cities named
# Detroit exist in MI/OR/AL/TX, and Charlotte in NC/MI/IA/TX/TN -- so
# only a confirmed domain, not the bare city name, can safely resolve
# either), then (2) an unambiguous city-name lookup against real US
# Census data, which a future not-yet-confirmed Cablecast customer with a
# nationally-unique city name would get for free with no allowlist entry
# needed at all.

# CCX Media (reflect-ccx.cablecast.tv) is one Cablecast host shared by 9
# real, distinct Minnesota cities, keyed apart only by a `site=` query
# param -- confirmed live 2026-08-30 by fetching real show pages for 3 of
# the 9 (Brooklyn Park site=8, Maple Grove site=16, New Hope site=17):
# each page's own embedded site catalog names all 9 real siteIds
# consistently (Brooklyn Center=7, Brooklyn Park=8, Crystal=10, Golden
# Valley=15, Maple Grove=16, New Hope=17, Osseo=18, Plymouth=19,
# Robbinsdale=20). This host can't go in jurisdiction_enrich's
# `_KNOWN_DOMAINS` table (that's one host -> one jurisdiction, and this
# host serves 9), and none of `_extract_jurisdiction()`'s existing tiers
# can tell the 9 apart either: `_find_site()` does happen to land on the
# right site object (its own `title` field is the bare real city name,
# e.g. "Maple Grove"), but with no "City of"/"County of" phrase anywhere
# on the page -- pageDescription is generic CCX Media+ app-download text,
# identical across all 9 -- so both `extract_jurisdiction_chain()` and
# `_JURISDICTION_RE` come back empty, and this shared host obviously
# can't validate as any one city's subdomain either. Several of these 9
# names are also nationally ambiguous (e.g. "Plymouth", "New Hope"), so a
# generic gazetteer lookup on the bare title wouldn't reliably supply MN
# for all of them -- an explicit table, keyed on the real, confirmed
# siteId, is the only tier that gets every one of the 9 right.
_CCX_MEDIA_HOST = "reflect-ccx.cablecast.tv"
_CCX_MEDIA_SITES = {
    "7": jurisdiction_enrich.KnownJurisdiction("Brooklyn Center", "city", "MN"),
    "8": jurisdiction_enrich.KnownJurisdiction("Brooklyn Park", "city", "MN"),
    "10": jurisdiction_enrich.KnownJurisdiction("Crystal", "city", "MN"),
    "15": jurisdiction_enrich.KnownJurisdiction("Golden Valley", "city", "MN"),
    "16": jurisdiction_enrich.KnownJurisdiction("Maple Grove", "city", "MN"),
    "17": jurisdiction_enrich.KnownJurisdiction("New Hope", "city", "MN"),
    "18": jurisdiction_enrich.KnownJurisdiction("Osseo", "city", "MN"),
    "19": jurisdiction_enrich.KnownJurisdiction("Plymouth", "city", "MN"),
    "20": jurisdiction_enrich.KnownJurisdiction("Robbinsdale", "city", "MN"),
}

# Cablecast's own vendor demo/sales tenant -- confirmed live 2026-08-30:
# yourtown.cablecast.tv's real site object's own pageDescription says
# outright "YourTownTV is the live streaming video channel of Cablecast
# Community Media... If you would like to demo Cablecast and see how we
# can improve your workflow, send an email to sales@cablecast.tv." Its
# real catalog is deliberately built to *look* like ordinary local-
# government content -- confirmed real, present shows include "Pasadena
# City Council Meeting 3-31-23" (show 32, real vodUrl) and "YourTown
# School Board Meeting with Agenda" (show 97) -- neither a real
# government's own channel, so nothing in the page's own structure
# (title/pageDescription shape, show titles) distinguishes this tenant
# from a genuine one the way every other check in this file does.
# Excluded by hostname outright rather than content-sniffed: this one
# host is the only confirmed instance of this pattern, so a hostname
# check is exact with no false-positive risk, unlike guessing at a text
# pattern that might or might not recur across other Cablecast demo/sales
# infrastructure this session hasn't seen.
_VENDOR_DEMO_HOST = "yourtown.cablecast.tv"


class CablecastAssetFinder(AssetFinder):
    """Detroit, MI and Charlotte, NC's Cablecast video portals (Remix.js
    template -- see module docstring above and `_extract_jurisdiction()`
    for how the two are told apart), plus Urbana, IL and Smyrna, TN's
    (the separate CablecastPublicSite/Ember.js template -- see the
    `_PUBLICSITE_SHOW_ID_RE` module note above for how that one works),
    plus Dyersville, IA's (WO-344: the same Ember app mounted at a custom
    domain root -- see `_FASTBOOT_EMBED_SHOW_TITLE_RE`'s module note)."""

    platform_name = "cablecast"

    async def resolve(self, url: str) -> ResolvedMeeting:
        if urlparse(url).netloc.lower() == _VENDOR_DEMO_HOST:
            # See the `_VENDOR_DEMO_HOST` module comment -- this tenant's
            # own real content is Cablecast's sales demo catalog, not a
            # real government, however real-looking a given show's title
            # is. Declined outright rather than resolved.
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "yourtown.cablecast.tv is Cablecast's own vendor demo/sales "
                    "tenant, not a real government -- not resolved as a real "
                    "meeting."
                ],
            )

        publicsite_match = _PUBLICSITE_SHOW_ID_RE.search(urlparse(url).path)
        if publicsite_match:
            return await self._resolve_publicsite(url, int(publicsite_match.group(1)))

        gallery_match = _GALLERY_ID_RE.search(urlparse(url).path)
        if gallery_match:
            return await self._resolve_gallery(url)

        if _WATCH_VOD_EMBED_PATH_RE.search(urlparse(url).path):
            watch_vod_result = await self._resolve_watch_vod_embed(url)
            if watch_vod_result is not None:
                return watch_vod_result

        show_id = self._extract_show_id(url)
        if show_id is None:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=["Could not find a show id in this Cablecast URL."],
            )

        fetch_url = self._force_http(url)
        html = await self._fetch_html(fetch_url)

        remix_data = self._extract_remix_context(html) if html else None
        show = self._find_show(remix_data, show_id) if remix_data else None
        site = self._find_site(remix_data) if remix_data else None

        if not show:
            # See the module-level note above `_SHOW_ID_SHORT_RE`: retry
            # against the site root, which isn't WAF-protected and embeds
            # its own real show catalog, rather than giving up after one
            # blocked/404'd fetch of the specific show path.
            parsed = urlparse(fetch_url)
            root_url = f"{parsed.scheme}://{parsed.netloc}/"
            if root_url != fetch_url:
                root_html = await self._fetch_html(root_url)
                root_remix = (
                    self._extract_remix_context(root_html) if root_html else None
                )
                if root_remix:
                    show = self._find_show(root_remix, show_id)
                    site = site or self._find_site(root_remix)

        jurisdiction = self._extract_jurisdiction(site, url) if site else None

        if not show and _SHOW_ID_SHORT_RE.search(urlparse(fetch_url).path):
            # Neither the direct fetch nor the root-fallback retry above
            # found a Remix show for this bare "/show/{id}" URL -- try the
            # third, FastBoot/Ember template before concluding "no video"
            # (see `_FASTBOOT_EMBED_SHOW_TITLE_RE`'s module docstring).
            # Only tried for the bare-"/show/" shape, matching the one
            # real confirmed customer (Dyersville, IA) -- the older
            # "/internetchannel/show/{id}" shape has no confirmed FastBoot
            # example.
            fastboot_result = await self._resolve_fastboot_embed(
                fetch_url, show_id, jurisdiction
            )
            if fastboot_result is not None:
                return fastboot_result

        if not show or not show.get("vodUrl"):
            # Real bug found 2026-08-29 investigating a user report on
            # Detroit: a genuinely video-less show (`isWatchable: false`,
            # e.g. a short "Council Corner" segment, show 13797) still
            # carries a real title/eventDate in the same JSON this
            # method already has in hand -- this used to come back
            # completely bare (no title, no date) instead of surfacing
            # what's actually known, the same "always show what you have"
            # convention every other adapter here follows for its own
            # no-video case. external_id is set here too (not just on the
            # video-found path below) for the same host-namespaced dedup
            # reason -- a video-less show is just as reachable at
            # multiple scheme/query URL variants as one with video.
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                external_id=(
                    f"cablecast:{urlparse(fetch_url).netloc.lower()}:{show_id}"
                    if show
                    else None
                ),
                title=show.get("title") if show else None,
                date=self._format_date(show.get("eventDate")) if show else None,
                jurisdiction=jurisdiction,
                video_warnings=["No video found for this meeting."],
            )

        segments: List[TranscriptSegment] = []
        transcript_language: Optional[str] = None
        alternate_transcripts: List[AlternateTranscript] = []
        transcript_warnings = []

        vod_transcripts = show.get("vodTranscripts") or []
        if vod_transcripts:
            async with aiohttp.ClientSession() as session:
                fetched = await asyncio.gather(
                    *(
                        self._fetch_transcript(session, t.get("url"))
                        for t in vod_transcripts
                        if t.get("url")
                    ),
                    return_exceptions=True,
                )
            # Same "never trust the source-provided language label" stance
            # every other adapter here takes -- language is re-derived from
            # each track's own real cue text, not the entry's own
            # `languageCode` field.
            candidates = []  # (cues, detected_language)
            for result in fetched:
                if isinstance(result, Exception) or not result:
                    continue
                normalize_shouting_caption(result)
                lang = detect_language_from_texts(c["text"] for c in result)
                candidates.append((result, lang))

            target_match = next(
                (c for c in candidates if c[1] == TARGET_LANGUAGE), None
            )
            chosen = target_match or (candidates[0] if candidates else None)
            if chosen:
                cues, transcript_language = chosen
                segments = [TranscriptSegment(**cue) for cue in cues]
                if transcript_language and transcript_language != TARGET_LANGUAGE:
                    transcript_warnings.append(
                        f"These captions appear to be in '{transcript_language}', not "
                        f"'{TARGET_LANGUAGE}' — no matching-language track was found for this meeting."
                    )
                alternate_transcripts = [
                    AlternateTranscript(
                        language=lang,
                        segments=[TranscriptSegment(**cue) for cue in cues],
                    )
                    for cues, lang in candidates
                    if cues is not chosen[0]
                ]

        if not segments:
            transcript_warnings.append("No transcript found for this event.")

        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            # Namespaced by host, not just the bare show_id -- confirmed
            # live 2026-08-29 that the same Cablecast show is routinely
            # reachable at 2-3 literal URLs (old "/internetchannel/show/"
            # template vs. new bare "/show/" template, http vs. https,
            # a trailing "?site=1" or not) with no id in common between
            # them except this one, so an unnamespaced/absent external_id
            # let _find_existing_page() (archive/db/crud.py) fall through
            # to exact source_url string equality and create a separate
            # page per URL variant for one real meeting (Coralville, IA
            # show 2907 landed as 3 rows). See BACKLOG.md/BACKLOG_DONE.md.
            # This only collapses same-host scheme/query variants, not a
            # genuine cross-host domain migration (old vs. new hostname
            # for the same tenant) -- that half still needs a confirmed
            # domain-alias table entry.
            external_id=f"cablecast:{urlparse(fetch_url).netloc.lower()}:{show_id}",
            title=show.get("title"),
            date=self._format_date(show.get("eventDate")),
            jurisdiction=jurisdiction,
            video_url=show["vodUrl"],
            video_format="m3u8",
            segments=segments,
            transcript_language=transcript_language,
            alternate_transcripts=alternate_transcripts,
            transcript_warnings=transcript_warnings,
        )

    @staticmethod
    async def _resolve_publicsite(url: str, show_id: int) -> ResolvedMeeting:
        """The CablecastPublicSite template's resolve path -- see the
        `_PUBLICSITE_SHOW_ID_RE` module note above for the real API shape
        this is built on. Entirely separate from the Remix path above: no
        HTML scraping at all, just two JSON API calls."""
        netloc = urlparse(url).netloc
        payload = await CablecastAssetFinder._fetch_publicsite_json(
            netloc, f"/cablecastapi/v1/shows/{show_id}"
        )
        show = (payload or {}).get("show")
        # CCX Media's own real links use exactly this "/CablecastPublicSite/
        # show/{id}?site=X" shape (confirmed live 2026-08-30 -- e.g.
        # https://reflect-ccx.cablecast.tv/CablecastPublicSite/show/36986
        # ?site=16), even though the host itself 301s that path to the
        # Remix template server-side -- this branch is the one that
        # actually runs for those real pasted URLs, so the `site=`
        # lookup has to be checked here too, not just in
        # `_extract_jurisdiction()`. See `_CCX_MEDIA_HOST`'s module
        # comment for the full investigation.
        jurisdiction = CablecastAssetFinder._ccx_media_jurisdiction(url)
        if not jurisdiction:
            known = jurisdiction_enrich.lookup_by_domain(netloc)
            if known:
                jurisdiction = f"{known.name}, {known.state}"

        if not show:
            return ResolvedMeeting(
                platform=CablecastAssetFinder.platform_name,
                source_url=url,
                jurisdiction=jurisdiction,
                video_warnings=[
                    "Could not find this show on the CablecastPublicSite API."
                ],
            )

        video_url = None
        video_format = None
        vod_ids = show.get("vods") or []
        if vod_ids:
            vod_payload = await CablecastAssetFinder._fetch_publicsite_json(
                netloc, f"/cablecastapi/v1/vods/{vod_ids[0]}"
            )
            vod = (vod_payload or {}).get("vod") or {}
            raw_url = vod.get("url")
            if raw_url:
                video_url = raw_url
                ext = raw_url.rsplit(".", 1)[-1].split("?")[0].lower()
                # Both real examples confirmed so far end in .mp4; the
                # extension is still checked rather than hardcoded in
                # case a future tenant's vod is HLS instead, matching the
                # Remix path's own video_format handling.
                video_format = ext if ext in ("mp4", "m3u8", "mov", "m4v") else "mp4"

        if not video_url:
            # Same real gap as the Remix path's own no-video branch (see
            # its comment) -- `show` already has a real title/eventDate
            # even when there's no vod to play.
            return ResolvedMeeting(
                platform=CablecastAssetFinder.platform_name,
                source_url=url,
                external_id=f"cablecast:{netloc.lower()}:{show_id}",
                title=show.get("title"),
                date=CablecastAssetFinder._format_date(show.get("eventDate")),
                jurisdiction=jurisdiction,
                video_warnings=["No video found for this meeting."],
            )

        return ResolvedMeeting(
            platform=CablecastAssetFinder.platform_name,
            source_url=url,
            # Same host-namespacing fix as the Remix path above -- see its
            # external_id comment for the real duplicate-page bug this
            # closes.
            external_id=f"cablecast:{netloc.lower()}:{show_id}",
            title=show.get("title"),
            date=CablecastAssetFinder._format_date(show.get("eventDate")),
            jurisdiction=jurisdiction,
            video_url=video_url,
            video_format=video_format,
            # No confirmed transcript source for this template yet -- see
            # the module-level note above _PUBLICSITE_SHOW_ID_RE.
            transcript_warnings=["No transcript found for this event."],
        )

    async def _resolve_watch_vod_embed(self, url: str) -> Optional[ResolvedMeeting]:
        """WO-1036 (2026-09-23): the "Cablecast Connect" WordPress plugin's
        own `/watch-vod-embed?showId=&site=` shape -- see
        `_WATCH_VOD_EMBED_PATH_RE`'s own comment. `showId` is required;
        `site` defaults to "1" the same way `_resolve_fastboot_embed()`'s
        own bare-`/show/` path already does. Returns `None` (not a
        video-less `ResolvedMeeting`) for a URL that matches the path but
        carries no usable `showId` -- lets `resolve()`'s caller fall
        through to `_extract_show_id()`'s own generic handling rather than
        this function inventing a warning for a shape it never actually
        confirmed."""
        parsed = urlparse(url)
        query = {k.lower(): v for k, v in parse_qs(parsed.query).items()}
        show_id_values = query.get("showid")
        if not show_id_values or not show_id_values[0].isdigit():
            return None
        show_id = int(show_id_values[0])
        site = (query.get("site") or ["1"])[0]

        jurisdiction = None
        known = jurisdiction_enrich.lookup_by_domain(parsed.netloc.lower())
        if known:
            jurisdiction = f"{known.name}, {known.state}"

        origin = f"{parsed.scheme}://{parsed.netloc}"
        return await self._resolve_fastboot_embed(
            f"{origin}/show/{show_id}",
            show_id,
            jurisdiction,
            record_url=url,
            site_override=site,
        )

    @staticmethod
    async def _resolve_fastboot_embed(
        fetch_url: str,
        show_id: int,
        jurisdiction: Optional[str],
        *,
        record_url: Optional[str] = None,
        site_override: Optional[str] = None,
    ) -> Optional[ResolvedMeeting]:
        """WO-344: the third real Cablecast template's own resolve path --
        see `_FASTBOOT_EMBED_SHOW_TITLE_RE`'s module docstring for the
        real investigation this is built on. Returns `None` (not a
        video-less `ResolvedMeeting`) when the embed endpoint itself
        doesn't answer with the expected shape, so `resolve()`'s caller
        falls through to its own standard "no video found" response
        rather than this function inventing one -- this only returns a
        real `ResolvedMeeting` once it has confirmed this tenant really is
        this template.

        `record_url`/`site_override` (WO-1036, 2026-09-23): the "Cablecast
        Connect" WordPress plugin's own `/watch-vod-embed?showId=&site=`
        iframe URL already carries a real `showId`/`site` pair directly --
        there's no separate `/show/{id}` page to derive them from the way
        the bare-`/show/` caller below has. `record_url` keeps the ORIGINAL
        URL as `source_url` (the plugin's iframe URL, not a synthesized
        `/show/{id}` one this app never actually resolved) so Archive
        dedup keys off the real URL a caller gave; `site_override` supplies
        `site` directly instead of parsing it out of `fetch_url`'s own
        query (which a synthesized `/show/{id}` URL might not carry)."""
        parsed = urlparse(fetch_url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        site = site_override or (parse_qs(parsed.query).get("site") or ["1"])[0]
        embed_url = f"{origin}/embed/vod?show={show_id}&site={site}"
        embed_html = await CablecastAssetFinder._fetch_html(embed_url)
        if embed_html is None:
            return None

        title_match = _FASTBOOT_EMBED_SHOW_TITLE_RE.search(embed_html)
        source_match = _FASTBOOT_EMBED_SOURCE_RE.search(embed_html)
        if not source_match:
            # Real embed page found, but no video source -- not this
            # template's shape after all, or a genuinely video-less show
            # (no confirmed real example of the latter yet). Let the
            # caller's standard no-video response handle it.
            return None

        raw_title = title_match.group(1).replace("\\'", "'") if title_match else None
        date = None
        if raw_title:
            date_match = _FASTBOOT_TITLE_DATE_RE.search(raw_title)
            if date_match:
                date = "-".join(date_match.groups())

        if not jurisdiction:
            # No Remix `site` object exists on this template (the whole
            # reason this branch runs at all), so fall back to the same
            # known-domain / validated-subdomain tiers `_extract_jurisdiction()`
            # itself falls back to -- confirmed live 2026-09-13:
            # `validated_subdomain_extract()` already correctly reads
            # "Dyersville" off `city-dyersville-ia.cablecast.tv`'s own
            # subdomain (its "city-...-ia" shape is exactly the "concatenated
            # slug, maybe with a trailing state abbreviation" pattern that
            # helper already handles), and `resolve_state()` resolves "IA"
            # for it via the Census-unambiguous-name lookup with no
            # allowlist entry needed.
            known = jurisdiction_enrich.lookup_by_domain(parsed.netloc.lower())
            if known:
                jurisdiction = f"{known.name}, {known.state}"
            else:
                subdomain_name = jurisdiction_enrich.validated_subdomain_extract(
                    fetch_url
                )
                if subdomain_name:
                    state = jurisdiction_enrich.resolve_state(
                        subdomain_name, "city", netloc=parsed.netloc
                    )
                    jurisdiction = (
                        f"{subdomain_name}, {state}" if state else subdomain_name
                    )

        video_url = urljoin(embed_url, source_match.group(1))
        segments: List[TranscriptSegment] = []
        transcript_warnings: List[str] = []
        cues = await CablecastAssetFinder._fetch_fastboot_captions(video_url)
        if cues:
            segments = [TranscriptSegment(**cue) for cue in cues]
        else:
            transcript_warnings.append("No transcript found for this event.")

        return ResolvedMeeting(
            platform=CablecastAssetFinder.platform_name,
            source_url=record_url or fetch_url,
            # Same host-namespaced external_id shape as the Remix/
            # PublicSite paths above -- see their own comments for the
            # real duplicate-page bug this avoids.
            external_id=f"cablecast:{parsed.netloc.lower()}:{show_id}",
            title=raw_title,
            date=date,
            jurisdiction=jurisdiction,
            video_url=video_url,
            video_format="m3u8",
            segments=segments,
            transcript_warnings=transcript_warnings,
        )

    @staticmethod
    async def _fetch_fastboot_captions(vod_m3u8_url: str) -> List[dict]:
        """Given the FastBoot template's real `vod.m3u8` HLS master
        playlist URL, finds and fetches its real English subtitle track
        (see the module docstring's point 2) -- confirmed real cue text
        on Dyersville's own show 3660. Returns `[]` on any failure or when
        no subtitle track is declared (no confirmed real example of a
        FastBoot-template show with zero captions yet -- treated the same
        as "no transcript" either way, matching every other adapter's
        degrade-honestly posture here)."""
        playlist = await CablecastAssetFinder._fetch_html(vod_m3u8_url)
        if not playlist:
            return []
        subtitle_match = _FASTBOOT_SUBTITLE_URI_RE.search(playlist)
        if not subtitle_match or subtitle_match.group(2).lower() != TARGET_LANGUAGE:
            return []
        subtitle_playlist_url = urljoin(vod_m3u8_url, subtitle_match.group(1))
        subtitle_playlist = await CablecastAssetFinder._fetch_html(
            subtitle_playlist_url
        )
        if not subtitle_playlist:
            return []
        segment_paths = _FASTBOOT_SEGMENT_URI_RE.findall(subtitle_playlist)
        if not segment_paths:
            return []

        semaphore = asyncio.Semaphore(_FASTBOOT_CAPTION_CONCURRENCY)

        async def _fetch_segment(
            session: aiohttp.ClientSession, segment_url: str
        ) -> List[dict]:
            async with semaphore:
                try:
                    async with session.get(
                        segment_url, timeout=aiohttp.ClientTimeout(total=15)
                    ) as response:
                        if response.status != 200:
                            return []
                        raw = await response.read()
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "Cablecast FastBoot caption segment fetch failed for %s",
                        segment_url,
                        exc_info=True,
                    )
                    return []
            try:
                return parse_vtt(decode_vtt_bytes(raw))
            except Exception:  # noqa: BLE001
                return []

        async with aiohttp.ClientSession() as session:
            results = await asyncio.gather(
                *(
                    _fetch_segment(session, urljoin(subtitle_playlist_url, path))
                    for path in segment_paths
                )
            )

        seen: set = set()
        cues: List[dict] = []
        for segment_cues in results:
            for cue in segment_cues:
                key = (cue.get("start"), cue.get("text"))
                if key in seen:
                    continue
                seen.add(key)
                cues.append(cue)
        cues.sort(key=lambda c: c.get("start") or 0.0)
        return cues

    @staticmethod
    async def _fetch_publicsite_json(netloc: str, path: str) -> Optional[dict]:
        for scheme in _PUBLICSITE_SCHEMES:
            target = f"{scheme}://{netloc}{path}"
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        target, timeout=aiohttp.ClientTimeout(total=15)
                    ) as response:
                        if response.status != 200:
                            continue
                        try:
                            return await response.json(content_type=None)
                        except (json.JSONDecodeError, aiohttp.ContentTypeError):
                            continue
            except (aiohttp.ClientError, TimeoutError):
                continue
        return None

    async def _resolve_gallery(self, url: str) -> ResolvedMeeting:
        """A gallery URL (`_GALLERY_ID_RE`, see module note) is a listing,
        not one meeting -- picks the newest real (has a `vodUrl`) show in
        THIS gallery's own scoped show list, then re-resolves through
        that show's own canonical `/internetchannel/show/{id}` URL,
        reusing `resolve()`'s own already-correct show path (transcript
        fetch, jurisdiction, everything) rather than duplicating it here.

        Real bug caught live 2026-09-23 building this: an earlier version
        walked the WHOLE remix tree for any object shaped like a show,
        which also picks up content that has nothing to do with this
        gallery -- confirmed live on Old Saybrook's gallery/22: the site
        homepage's own `slideShow` carousel (unrelated site-wide featured
        content, "Arts & Entertainment with Deborah Gilbert") and a
        SEPARATE gallery's own sample shows (`site.galleries[8]`, a
        different category) are both reachable from that same page's
        tree and were both wrongly returned as if they belonged to gallery
        22. `_find_gallery_shows()` instead finds the one object in the
        tree that's actually THIS gallery -- verified by its own
        `cablecastGalleryId` matching the id in the URL, not by tree
        position -- and reads only its own `shows` list."""
        gallery_match = _GALLERY_ID_RE.search(urlparse(url).path)
        gallery_id = int(gallery_match.group(1))

        fetch_url = self._force_http(url)
        html = await self._fetch_html(fetch_url)
        if not html:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=["Could not fetch this Cablecast gallery page."],
            )

        remix_data = self._extract_remix_context(html)
        shows = self._find_gallery_shows(remix_data, gallery_id) if remix_data else None
        if shows is None:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    f"Could not find gallery {gallery_id}'s own show list."
                ],
            )
        ready = [s for s in shows if s.get("vodUrl")]
        if not ready:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    f"No video-ready show found in this gallery ({len(shows)} "
                    "show(s) checked -- only the newest page of a paginated "
                    "gallery is checked, an older page may still have one)."
                ],
            )

        newest = max(
            ready,
            key=lambda s: (
                self._parse_gallery_event_date(s.get("eventDate")) or datetime.min
            ),
        )
        show_id = newest.get("showId")
        parsed = urlparse(fetch_url)
        canonical = f"{parsed.scheme}://{parsed.netloc}/internetchannel/show/{show_id}"
        if parsed.query:
            canonical = f"{canonical}?{parsed.query}"
        return await self.resolve(canonical)

    @staticmethod
    def _find_gallery_shows(obj, gallery_id: int) -> Optional[List[dict]]:
        """Same recursive-search shape as `_find_show()`/`_find_site()`
        (Remix's loader data nesting is keyed by route id, not a fixed
        path worth hardcoding -- confirmed live 2026-09-23 the real key
        is `routes/_shell.gallery.$galleryId`, but matched here by the
        gallery OBJECT's own identity instead, the same reasoning
        `_find_site()`'s own docstring already gives for matching
        `siteId`+`pageDescription` together rather than trusting tree
        position). Returns the one gallery object's own `shows` list
        whose `cablecastGalleryId` equals the id from the URL -- not
        every show-shaped object anywhere on the page (see
        `_resolve_gallery()`'s own docstring for the real bug that
        distinction fixes)."""
        if isinstance(obj, dict):
            if obj.get("cablecastGalleryId") == gallery_id and isinstance(
                obj.get("shows"), list
            ):
                return obj["shows"]
            for value in obj.values():
                found = CablecastAssetFinder._find_gallery_shows(value, gallery_id)
                if found is not None:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = CablecastAssetFinder._find_gallery_shows(item, gallery_id)
                if found is not None:
                    return found
        return None

    @staticmethod
    def _parse_gallery_event_date(event_date: Optional[str]) -> Optional[datetime]:
        """A gallery's own `eventDate` string -- see `_GALLERY_EVENT_DATE_
        FORMAT`'s module note for why this is usually a different format
        from `_format_date()` above and only ever used for sorting, never
        shown to a user.

        Real bug found live 2026-09-23 picking the newest Haddam, CT
        show: the SAME show (id 5167) appears twice in one gallery page's
        own catalog with its `eventDate` in BOTH formats at once
        ("7/10/2024 12:00:00 AM" in one copy, the ISO "2024-07-10T00:00:
        00-04:00" `_format_date()` expects in the other) -- `_find_all_
        shows()`'s dedup keeps whichever copy it meets first in the tree,
        so trying only the gallery format here let that show's real,
        correct date silently fail to parse on the ISO-format copy
        (treated as `datetime.min` -- effectively "no date"), which
        wrongly lost the newest-show comparison to a real but older show
        (Feb 2024) that happened to parse. Tries both formats now,
        whichever copy survives dedup."""
        if not event_date:
            return None
        try:
            return datetime.strptime(event_date, _GALLERY_EVENT_DATE_FORMAT)
        except ValueError:
            pass
        try:
            # Stripped to naive (`max()` below compares across shows that
            # may have landed on either format after dedup -- comparing a
            # naive and a timezone-aware datetime raises TypeError, and
            # every real example seen so far is midnight in the same
            # local offset either way, so this loses no real precision).
            return datetime.fromisoformat(event_date).replace(tzinfo=None)
        except ValueError:
            return None

    @staticmethod
    def _extract_show_id(url: str) -> Optional[int]:
        path = urlparse(url).path
        match = _SHOW_ID_RE.search(path) or _SHOW_ID_SHORT_RE.search(path)
        return int(match.group(1)) if match else None

    @staticmethod
    def _force_http(url: str) -> str:
        parsed = urlparse(url)
        return parsed._replace(scheme="http").geturl()

    @staticmethod
    async def _fetch_html(url: str) -> Optional[str]:
        """Same "fetch and return None on any failure" shape as
        champds.py's `_fetch_json()` -- covers a genuine 404 (an
        old-style URL on a migrated customer), a WAF challenge response
        (see the `_SHOW_ID_SHORT_RE` module note), and an outright
        network failure alike, so `resolve()`'s root-fallback logic can
        treat all three the same way instead of one of them raising.

        Real gap found 2026-08-18 running this against a large batch of
        real hosts: a slow/unresponsive host's `aiohttp.ClientTimeout`
        raises `TimeoutError` (Python 3.11+ makes `asyncio.TimeoutError`
        an alias of the builtin), which is NOT a subclass of
        `aiohttp.ClientError` -- the one exception type this used to
        catch. A single slow host used to escape this function's own
        documented "return None on any failure" contract and propagate
        all the way up, taking down an `asyncio.gather()`-based batch
        caller with it (confirmed live: one timeout among ~200 real
        hosts aborted the whole run). Caught explicitly now, alongside
        `aiohttp.ClientError`.
        """
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=30)
                ) as response:
                    if response.status >= 400:
                        return None
                    return await response.text()
        except (aiohttp.ClientError, TimeoutError):
            return None

    @staticmethod
    def _extract_remix_context(html: str) -> Optional[dict]:
        match = _REMIX_CONTEXT_RE.search(html)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def _find_show(obj, show_id: int) -> Optional[dict]:
        """`showId` is an `int` in the payload on old-template customers
        (Detroit, Charlotte, villageofuniversitypark -- all confirmed
        live) but a `str` on the newer template (confirmed live on
        satellitebeach, e.g. `"showId": "540"`) -- compared as strings on
        both sides so neither template silently fails to match.
        """
        if isinstance(obj, dict):
            if "showId" in obj and str(obj.get("showId")) == str(show_id):
                return obj
            for value in obj.values():
                found = CablecastAssetFinder._find_show(value, show_id)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = CablecastAssetFinder._find_show(item, show_id)
                if found:
                    return found
        return None

    @staticmethod
    def _find_site(obj) -> Optional[dict]:
        """Same recursive-search shape as `_find_show()` (Remix's loader
        data nesting is keyed by route id, not a fixed path -- see
        `_find_show()`'s own docstring). Matched on `siteId` *and*
        `pageDescription` together, not `siteId` alone -- confirmed real
        pages also carry many small `{siteId, title: None}` decoys nested
        under each show's own `upcomingRuns` list, which would otherwise
        match first and never reach the real top-level site object.
        """
        if isinstance(obj, dict):
            if "siteId" in obj and "pageDescription" in obj:
                return obj
            for value in obj.values():
                found = CablecastAssetFinder._find_site(value)
                if found:
                    return found
        elif isinstance(obj, list):
            for item in obj:
                found = CablecastAssetFinder._find_site(item)
                if found:
                    return found
        return None

    @staticmethod
    def _ccx_media_jurisdiction(url: str) -> Optional[str]:
        """See the `_CCX_MEDIA_HOST`/`_CCX_MEDIA_SITES` module comment.
        Shared between both real URL shapes this host answers to -- the
        Remix "/internetchannel/show/{id}?site=X" path (via
        `_extract_jurisdiction()` below) and the real, commonly-linked
        "/CablecastPublicSite/show/{id}?site=X" path (via
        `_resolve_publicsite()`), which 301s to the Remix template
        server-side but is itself a real, pasteable URL that routes
        through this adapter's *other* resolve branch."""
        netloc = urlparse(url).netloc.lower()
        if netloc != _CCX_MEDIA_HOST:
            return None
        site_ids = parse_qs(urlparse(url).query).get("site") or []
        known = _CCX_MEDIA_SITES.get(site_ids[0]) if site_ids else None
        return f"{known.name}, {known.state}" if known else None

    @staticmethod
    def _extract_jurisdiction(site: dict, url: str) -> Optional[str]:
        # CCX Media's shared host -- tried first and independent of
        # `site`'s own text: neither pageDescription (generic app-
        # download text, identical on all 9 cities) nor a bare title
        # ("Maple Grove", no "City of" prefix) ever resolves through the
        # tiers below.
        ccx_jurisdiction = CablecastAssetFinder._ccx_media_jurisdiction(url)
        if ccx_jurisdiction:
            return ccx_jurisdiction

        netloc = urlparse(url).netloc.lower()
        page_description = site.get("pageDescription")
        # Real gap found 2026-08-29 auditing stored (not missing --
        # confidently WRONG) jurisdictions via /coverage: the narrower
        # `_JURISDICTION_RE` regex below is deliberately single-word only
        # (see its own module comment), so a real multi-word "City of X"
        # name gets truncated at the first word -- confirmed live on two
        # real customers, "City of Virginia Beach" -> "Virginia"
        # (virginiabeach.cablecast.tv), "City of La Quinta" -> "La"
        # (laquinta.cablecast.tv). Tried FIRST, ahead of the narrower
        # regex, precisely because the narrower regex would otherwise
        # match its own truncated prefix and return before this ever
        # runs -- `_JURISDICTION_RE`'s own module comment anticipated
        # this ("revisit if a real multi-word-city customer... turns up")
        # -- it has, twice now. `extract_jurisdiction_chain()`'s
        # capitalization-bounded walk already handles this correctly
        # (validated against the Census table, so it can't repeat the
        # single-word regex's own mistake in the other direction by
        # over-capturing trailing branding words like "GOV Channel" --
        # confirmed it still resolves Charlotte's real "City of Charlotte
        # GOV Channel" text correctly), same shared logic Swagit/
        # Granicus/CivicClerk already use for exactly this reason.
        for text in (page_description, site.get("title")):
            if not text:
                continue
            chained = jurisdiction_enrich.extract_jurisdiction_chain(
                page_text=text, html="", url=url
            )
            if chained:
                return chained
        for text in (page_description, site.get("title")):
            if not text:
                continue
            match = _JURISDICTION_RE.search(text)
            if match:
                city = match.group(1).strip()
                state = jurisdiction_enrich.resolve_state(
                    city,
                    "city",
                    netloc=urlparse(url).netloc,
                    page_text=page_description,
                )
                return f"{city}, {state}" if state else city
        # Some customers' Cablecast branding (title/pageDescription) is
        # generic ("Channel 8") with no "City of"/"County of" phrase
        # anywhere for the regex above to find -- confirmed live on
        # Broomfield, CO 2026-08-19, same class of gap Detroit/Charlotte
        # already hit. Falls back to the known-domain table (same pattern
        # as lims.py/hyland.py) rather than dropping jurisdiction entirely.
        known = jurisdiction_enrich.lookup_by_domain(netloc)
        if known:
            return f"{known.name}, {known.state}"
        # Last resort: the subdomain itself, run through the same
        # validated-subdomain-label machinery eScribe/CivicPlus/
        # TownHallStreams already share. The module comment above (written
        # against only Detroit/Charlotte) says "no reliable domain-based
        # signal" -- true for a STATE, but wrong for a NAME: confirmed live
        # 2026-08-29 auditing 101 archived Cablecast pages with no
        # jurisdiction, 23 of 62 distinct real customer subdomains checked
        # validate cleanly this way (e.g. "champaign.cablecast.tv" ->
        # Champaign, "fargo.cablecast.tv" -> Fargo, "cerritos.cablecast.tv"
        # -> Cerritos) -- this adapter just never tried. Same safety
        # property as every other tier here: declines rather than
        # guessing on a made-up/unvalidatable subdomain, and only adds a
        # state when the bare name is unambiguous or the domain is
        # separately confirmed above.
        subdomain_name = jurisdiction_enrich.validated_subdomain_extract(url)
        if subdomain_name:
            state = jurisdiction_enrich.resolve_state(
                subdomain_name, "city", netloc=netloc, page_text=page_description
            )
            return f"{subdomain_name}, {state}" if state else subdomain_name
        return None

    @staticmethod
    async def _fetch_transcript(
        session: aiohttp.ClientSession, transcript_url: str
    ) -> Optional[List[dict]]:
        try:
            async with session.get(
                transcript_url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "Cablecast transcript fetch got HTTP %s for %s",
                        response.status,
                        transcript_url,
                    )
                    return None
                raw = await response.read()
        except Exception:
            logger.warning(
                "Cablecast transcript fetch failed for %s",
                transcript_url,
                exc_info=True,
            )
            return None
        cues = CablecastAssetFinder._parse_transcript(decode_vtt_bytes(raw))
        return cues or None

    _CUE_RE = re.compile(r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})\t(.+)$")

    # Real, confirmed second cue shape (WO-309 resume, 2026-09-12) --
    # independently confirmed live on three unrelated tenants (Wilder KY
    # /reflect-campbellcounty, Cape Elizabeth ME /reflect-cetv, Huron
    # charter Township MI /huron-township): the timestamp line itself
    # carries only a bare speaker label ("S1:", "s4:", ...), and the real
    # spoken text is on the FOLLOWING line(s), not the same line. Before
    # this fix, `_parse_transcript()` only ever matched `_CUE_RE`, whose
    # `(.+)$` group happily captured "S1:" as if it were the cue's real
    # text -- every cue on an affected tenant came back as just a speaker
    # label, with the real sentence silently dropped, and nothing
    # detected this as a warning (transcript_warnings stayed empty, so an
    # affected page looked like a normal, healthy tier-1/2 ingest). This
    # is a distinct real shape from the original Charlotte-confirmed one
    # (`HH:MM:SS,mmm<TAB>TEXT` on one line, no speaker) -- both are
    # handled here now.
    _SPEAKER_LABEL_ONLY_RE = re.compile(r"^[Ss]\d+:$")

    @staticmethod
    def _parse_transcript(content: str) -> List[dict]:
        """See the module docstring's `vodTranscripts` note for the real
        confirmed shape this parses -- one real cue per line
        (`HH:MM:SS,mmm<TAB>TEXT`), blank-line-separated, no explicit end
        time -- or, on some tenants (see `_SPEAKER_LABEL_ONLY_RE` above),
        `HH:MM:SS,mmm<TAB>SPEAKER:` on its own line followed by the real
        text on the next line(s), up to a blank line or the next
        timestamp line. Each cue's end is the next cue's start; the last
        cue's end equals its own start (same "no better answer available"
        fallback Granicus's AgendaViewer.php chapter markers already
        use).
        """
        lines = content.splitlines()
        n = len(lines)
        raw_cues = []
        i = 0
        while i < n:
            match = CablecastAssetFinder._CUE_RE.match(lines[i].strip())
            if not match:
                i += 1
                continue
            h, m, s, ms, rest = match.groups()
            start = int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000
            rest = rest.strip()
            if CablecastAssetFinder._SPEAKER_LABEL_ONLY_RE.match(rest):
                text_parts = []
                j = i + 1
                while j < n:
                    next_line = lines[j].strip()
                    if not next_line or CablecastAssetFinder._CUE_RE.match(next_line):
                        break
                    text_parts.append(next_line)
                    j += 1
                text = " ".join(text_parts).strip()
                i = j
            else:
                text = rest
                i += 1
            if text:
                raw_cues.append((start, text))

        cues = []
        for idx, (start, text) in enumerate(raw_cues):
            end = raw_cues[idx + 1][0] if idx + 1 < len(raw_cues) else start
            cues.append({"start": start, "end": max(end, start), "text": text})
        return cues

    @staticmethod
    def _format_date(event_date: Optional[str]) -> Optional[str]:
        if not event_date:
            return None
        try:
            return datetime.fromisoformat(event_date).strftime("%Y-%m-%d")
        except ValueError:
            return None


def list_gallery_shows(url: str, html: str) -> List[dict]:
    """WO-1036 (2026-09-23, Ryan confirmed): given a Cablecast gallery URL
    (`_GALLERY_ID_RE`) and its already-fetched HTML, return EVERY video-
    ready show in THIS gallery, newest first, as plain dict rows
    (`title`/`date`/`url`/`has_video_hint`) --
    `app/platforms/meeting_finder/listing.py`'s own Cablecast gallery
    lister uses this to list a known specific gallery before falling back
    to the whole tenant root. A gallery is one governing body's own list;
    the tenant root mixes in unrelated programming (confirmed live,
    Virginia Beach VA's tenant root mixes a live-stream embed with
    unrelated PEG content). Reuses the exact same real Remix-tree gallery
    lookup `CablecastAssetFinder._resolve_gallery()` uses to pick ONE
    show, just returning every ready one instead of only the newest --
    each row's `url` is already the show's own canonical
    `/internetchannel/show/{id}` URL, the same one `_resolve_gallery()`
    re-resolves through, so a caller of this function still gets a real,
    directly-resolvable meeting URL per row, not the gallery URL itself.
    Returns `[]` when the URL isn't a gallery shape, the gallery can't be
    found in the page, or it has no video-ready show yet."""
    gallery_match = _GALLERY_ID_RE.search(urlparse(url).path)
    if not gallery_match:
        return []
    gallery_id = int(gallery_match.group(1))
    remix_data = CablecastAssetFinder._extract_remix_context(html)
    shows = (
        CablecastAssetFinder._find_gallery_shows(remix_data, gallery_id)
        if remix_data
        else None
    )
    if not shows:
        return []
    parsed = urlparse(url)
    rows: List[dict] = []
    for show in shows:
        if not show.get("vodUrl"):
            continue
        show_id = show.get("showId")
        if show_id is None:
            continue
        canonical = f"{parsed.scheme}://{parsed.netloc}/internetchannel/show/{show_id}"
        if parsed.query:
            canonical = f"{canonical}?{parsed.query}"
        event_date = CablecastAssetFinder._parse_gallery_event_date(
            show.get("eventDate")
        )
        rows.append(
            {
                "title": show.get("title"),
                "date": event_date.strftime("%Y-%m-%d") if event_date else None,
                "url": canonical,
                "has_video_hint": True,
            }
        )
    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    return rows
