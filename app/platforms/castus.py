import re
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from urllib.parse import quote, unquote, urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder
from .models import ResolvedMeeting, TranscriptSegment
from ..utils import jurisdiction_enrich
from ..utils.video_hand_check import looks_like_real_meeting
from ..utils.vtt_parser import (
    decode_vtt_bytes,
    detect_language_from_texts,
    is_likely_garbled,
    parse_vtt,
)

TARGET_LANGUAGE = "en"

# Castus (cloud.castus.tv) -- a real PEG/government-access video platform
# (WO-19, 2026-08-21), first sighted via a national dotgov coverage-map
# crawl (see BACKLOG.md), with a real customer URL confirmed via
# destinyhosted.com's own agenda-hyperlink enumeration: Billings, MT's
# City Council/Yellowstone County channel, "comm7tv"
# (https://cloud.castus.tv/vod/comm7tv/video/6a83b3f9d94c83000226f83d).
#
# **The static page is a pure JS-redirect shell into a client-rendered
# React SPA behind a hash router** (`/vod/#/{tenant}/video/{id}`) --
# confirmed live: a plain `curl`/`aiohttp` GET of the page URL only ever
# sees a tiny `redirect()` script, never the real title/video/agenda.
# Unlike Minneapolis LIMS/Salt Lake City (`headless_browser.py`), this
# does NOT need a real browser at resolve time -- the SPA's own webpack
# bundles (`/vod/static/js/main.*.chunk.js`, fetched once by hand and
# read directly, not executed) turned out to embed the real API calls
# in plain, unminified-enough JS, all plain unauthenticated HTTP:
#
# - `POST https://imd0mxanj2.execute-api.us-west-2.amazonaws.com/upload/info`
#   `{"file": "{videoId}"}` -- a GLOBAL endpoint (same constant for every
#   tenant, confirmed by reading the SPA's own hardcoded base-URL table;
#   not per-customer) that returns the single source of truth for one
#   video: `response.payload.file`, including `metadata.filename` (real
#   human title, often "{title} - {Month DD, YYYY}"), `transcoded`/
#   `captioned` (bool/bool-list readiness flags -- checked here instead
#   of guessing HLS/caption existence from the id alone), `user` (the
#   internal channel id -- see the tenant-slug note below), and, useful
#   enough that the separate `ccs/v1/agenda` endpoint below is redundant
#   for this adapter's purposes, an embedded `agenda` array identical in
#   shape to that endpoint's own response. NOT the file's own `date`/
#   `original_date` fields -- both are upload/ingestion timestamps
#   (confirmed live: this real video's `date` is 2026-08-19, two days
#   after the real meeting date of 2026-08-17 in its own title), so
#   never used as the meeting date here.
# - HLS video: `https://dlttx48mxf9m3.cloudfront.net/outputs/{videoId}/Default/HLS/out.m3u8`
# - Captions: `https://dlttx48mxf9m3.cloudfront.net/captions/{videoId}.vtt`
#   -- real, populated AWS-Transcribe-style VTT with per-word confidence/
#   speaker inline tags (`<v.Male.spk1.Speaker1><c.CONF_HIGH>word</c>`).
#   Confirmed `parse_vtt()`'s existing generic `_TAG_RE` (built for a
#   different platform's similar tag shape) already strips these cleanly
#   with no Castus-specific tag handling needed -- unlike TelVue's
#   `<v Speaker N>` tags, which needed their own strip.
#   Both CloudFront hosts above are hardcoded constants in the SPA
#   bundle too, confirmed the SAME for every tenant (not derived from the
#   tenant slug or channel id) -- one shared CDN across all Castus
#   customers.
# - A second, real, unauthenticated JSON API,
#   `https://api.castus.tv/ccs/v1/agenda/{videoId}`, returns the same
#   per-item agenda array independently (confirmed live, byte-identical
#   in shape to `/upload/info`'s embedded `agenda` field on this sample)
#   -- not called by this adapter since the embedded field already covers
#   it in one fewer request, but worth knowing about if a future real
#   example ever has one without the other.
#
# **The tenant-slug -> internal-channel-id mapping this platform's first
# investigation pass (BACKLOG.md) flagged as unsolved is now solved**:
# `GET https://837sc3bew0.execute-api.us-west-2.amazonaws.com/{tenantSlug}`
# (also a global, hardcoded-in-the-bundle constant; the SPA calls this
# once per page load, keyed off the URL's own first path segment after
# `/vod` -- see the bundle's own `Qt()` helper) returns real per-tenant
# config: `user` (the SAME internal channel id `/upload/info` returns on
# a video from that tenant -- confirmed live: both point at
# "5fb29792d339f4000892b300" for comm7tv), `company`, `title` (channel
# branding, e.g. "Comm7 TV" -- NOT reliably a place name), `frontPage`
# (category list for that tenant's home page). NOT called by this
# adapter -- `/upload/info` already returns the channel id directly for
# whatever video was actually requested, so a tenant-config round trip
# buys nothing for resolving one video by id -- but documented here in
# full since solving this mapping was this work order's main ask, and a
# future feature (e.g. browsing/enumerating a whole tenant's library)
# would need exactly this endpoint.
#
# **Jurisdiction**: the tenant slug itself is opaque channel branding
# ("comm7tv"), not a place name -- unlike eScribe's `pub-{city}`
# subdomain convention. The real, confirmed-reliable signal instead is
# each agenda item's own `hyperlinks`, which on real government
# customers point out to that jurisdiction's actual agenda system (here,
# `public.destinyhosted.com/{tenant_id}/...` -- Destiny Software's
# AgendaQuick, see destinyhosted.py). Fetching that one linked page and
# running it through the same `jurisdiction_enrich.extract_jurisdiction_chain()`
# every other free-text adapter already uses confirms "City of Billings"
# live. Its own page text couldn't fill in the state automatically
# (`enrich_jurisdiction_text()`'s ZIP-anchored fallback needs a real
# Census ZCTA match, and the one ZIP on this real page, 59103, is a
# City-Clerk PO Box not covered by the Census place-level ZCTA table) --
# resolved with a small known-tenant map instead
# (`_KNOWN_DESTINYHOSTED_TENANT_JURISDICTIONS`), the same pattern
# telvue.py's own `_KNOWN_ORG_TOKEN_JURISDICTIONS` already established,
# seeded with the one real tenant id (24568) confirmed here. This also
# corrects BACKLOG.md's earlier unverified "bilmt" folder-name guess --
# the real jurisdiction is Billings, MT, independently confirmed via
# this real destinyhosted page's own address block ("Billings, MT
# 59103") and its "City of Billings" phrasing, not the destinyhosted
# folder-name convention. If no destinyhosted (or otherwise-recognized)
# hyperlink is found on a future customer, falls back to a best-effort
# guess parsed from the tenant slug itself -- unconfirmed against any
# real second example, since "comm7tv" itself doesn't parse as a place
# name (see `_jurisdiction_from_tenant_slug()`'s own docstring).
#
# **Listing walk (2026-09-23)**: a CivicPlus homepage-link sweep the same
# day found 5 real Castus tenants (Lincoln MA, Tyngsborough MA, Durham NH,
# Blackstone MA on cloud.castus.tv; Millbury MA on its own subdomain, see
# below) by their HUB or PLAYLIST URLs only -- `/vod/{tenant}/?page=HOME`,
# `/vod/{tenant}/?page=PLAYLIST`, `/vod/{tenant}/playlist/{name}?page=PLAYLIST`
# -- none of which carry a `/video/{id}` segment, so the adapter rejected
# all five. Re-reading the current SPA bundle
# (`https://cloud.castus.tv/vod/static/js/main.d92574e1.chunk.js`, fetched
# once by hand, read, not executed -- note the bundle lives under the
# SPA's own `/vod/` root, NOT under `/vod/{tenant}/`, which is only ever
# the redirect shell) found the SPA's real listing calls, all plain
# unauthenticated GETs, all confirmed live the same day:
#
# - `GET https://imd0mxanj2.execute-api.us-west-2.amazonaws.com/playlist/{tenantSlug}/{playlistName}`
#   -- the SPA's own playlist page (its `Zt` component) calls this, keyed
#   by the URL's tenant slug and the URL's own last path segment (the
#   playlist name, percent-encoded exactly as it appears in the URL) --
#   NO channel-id lookup needed. Returns `{"response": {"success": true,
#   "payload": [video, ...]}}` where each video is the same object shape
#   `/upload/info` returns (`_id`, `metadata.filename`, `transcoded`,
#   `captioned`, `date`, plus a `sort` integer = its curated position in
#   the playlist, 0 first). Confirmed live on two tenants: Lincoln's
#   "Town Meeting" (49 videos; `sort` 0 = `69cbe826f23ec40002de421d`,
#   "Annual Town Meeting  03.28.26" -- the exact video a human had
#   already found by hand on that page) and Tyngsborough's "Town Meeting
#   Videos" (4 videos; `sort` 0 = `69f242ed3ff9ab0002693bb9`, "Pre Town
#   Meeting 2026 | Info Session | April 28, 2026", again the hand-found
#   one). An unknown playlist name returns HTTP 500 with a plain-text
#   body ("Error getting playlist: Playlist ... does not exist for
#   lincoln"), not a JSON envelope.
# - `GET https://2kbyogxrg4.execute-api.us-west-2.amazonaws.com/{channelId}/home/{section}`
#   -- the SPA's home page (its `Na` component's `gatherAllVodData()`)
#   calls this once per entry in the tenant config's `frontPage` list
#   (`["recent", "playlists", "live", "popular", "featured",
#   "subscriptions"]` on Lincoln; same six in a different order on
#   Blackstone), keyed by the internal channel id from the
#   `837sc3bew0.../{tenantSlug}` tenant-config call already documented
#   above (its `user` field -- this is the first real use of that
#   round trip in this adapter). `home/recent` returns a bare JSON list
#   of the same video objects, newest upload first (32 on Lincoln, ~30 on
#   Blackstone). That earlier docstring's description of `frontPage` as
#   a "category list" was right but incomplete: it is a list of home-page
#   SECTION names, not of videos or playlists.
# - `GET https://2kbyogxrg4.execute-api.us-west-2.amazonaws.com/{channelId}/playlist`
#   -- lists the tenant's playlists as `[{_id, name, date}]` (19 on
#   Lincoln: "Select Board", "School Committee", "Planning Board", "Town
#   Meeting", but also "Local", "Seniors", "Historical", "Bemis Free
#   Lecture Series"). Names only, no videos; `.../playlist/{name}` on the
#   same host returns one playlist WITH its `videos` list (the SPA's own
#   `goToPlaylist()` plays `videos[0]`). Not called here -- the
#   slug-keyed `imd0mxanj2` form above is one request instead of two.
# - Also present but NOT used: `POST .../upload/search` (needs a channel
#   id and a search string), `POST 8o1rav21mb.../production/search-videos`
#   and `POST tf4pr3wftk.../default/api/all` (paginated "All Videos" tab,
#   `{_id, page, results}`). Search-shaped, so left alone.
#
# **Why a PLAYLIST URL is the better input (Ryan's hypothesis, confirmed
# live)**: a tenant's `recent` feed is its whole PEG channel, so it mixes
# real meetings with everything else the station airs -- Blackstone's
# real `recent` list on 2026-09-23 had "9:11 Memorial 2026.mov" and
# " Senior Radio Hour 08-31-26.mp4" between "Board of Selectmen
# 09-15-26.mp4" and "BMR School Committee 09-10-26.mp4"; Lincoln's
# playlists include "Seniors" and "Bemis Free Lecture Series". A named
# playlist ("Town Meeting") is curated by the tenant to one body's
# content. So: a playlist URL walks that playlist with only the shared
# promo blocklist applied (the tenant already chose what belongs); a
# bare hub URL walks `home/recent` behind the STRICT title gate
# (`looks_like_real_meeting(require_allowlist=True)` -- the same
# "generic scan of a mixed channel" risk class that gate's own docstring
# names). Checked against every real title seen: the strict gate passes
# all four hand-confirmed videos and rejects the memorial, the radio
# hour and the lecture series. One known false negative it also
# produces: Blackstone's "Parks and Recreation 09-21-26.mp4" (a real
# board meeting whose title has no governing-body word) is skipped for
# "Zoning Board 09-16-26.mp4" five days older. Reported here, not
# patched -- the gate is shared and its allowlist is curated elsewhere.
#
# **"Newest"** is the largest upload `date` among candidates (ISO
# timestamps, present on every real item seen), with the playlist's own
# `sort` position as the tiebreak. The upload date is deliberately NOT
# reported as the meeting date (see the `/upload/info` note above); it is
# only used to order candidates. Items whose `premiereDate` is still in
# the future are skipped the same way the SPA itself renders them as
# "coming soon" tiles (its `Te()` helper); none of the ~120 real items
# seen across four tenants had one set. Items with `transcoded` false
# are skipped too -- `/upload/info` would only report "hasn't finished
# processing" for them.
#
# After picking, the walk resolves the video exactly as if its own
# `/vod/{tenant}/video/{id}` URL had been pasted, and reports that
# canonical URL as `source_url` (the shape both the SPA's own
# post-payment redirect and every hand-found video URL use) rather than
# the hub/playlist URL -- same reasoning as boxcast.py's channel scan: a
# later re-resolve of the hub can pick a different newest video; the
# video's own URL never does.
#
# **Millbury, MA is a different product.** Its URL
# (`https://millbury-public-access.vod.castus.tv/vod/`) is a self-hosted
# "Castus VOD Widget" (its own `<title>`), a real React app served from
# the tenant's own box with a separate bundle
# (`/vod/static/js/main.2508cb65.chunk.js`, fetched once and read) and
# relative, host-local APIs -- `GET /api/v1/api/assets?page=1&pagesize=N`
# (newest first; confirmed live: item 0 was "Board of Selectmen
# 09-22-26", guid `{56af3108-2000-4c8b-bbe6-e0bfef952292}`, the exact
# video a human found by hand as `/vod/?video=56af3108-...`), `GET
# /api/v1/api/playlist` (m3u8-backed playlists like "2025 Sewer
# Commission"), `/api/v1/api/agenda/{rpath}`, `/vod/dl.php/{rpath}` for
# playback and `/caption/{rpath}` for captions. None of the cloud
# endpoints above apply (UUID guids, not 24-hex ids; no CloudFront; no
# Lambda hosts), which is why the hand-found Millbury video URL never
# resolved through this adapter. Out of scope for this listing walk:
# `resolve()` now names it as a separate platform instead of failing
# with the generic "no tenant/video id" message. Building it is a real
# second adapter (confirmed shapes above are enough to start from).
_URL_RE = re.compile(r"/vod/([^/?#]+)/video/([^/?#]+)")
_PLAYLIST_URL_RE = re.compile(r"/vod/([^/?#]+)/playlist/([^/?#]+)")
_HUB_URL_RE = re.compile(r"/vod/([^/?#]+)/?(?:[?#]|$)")
_TITLE_DATE_RE = re.compile(r"^(.*?)\s*-\s*([A-Za-z]+ \d{1,2},? \d{4})$")
_DESTINYHOSTED_TENANT_ID_RE = re.compile(r"destinyhosted\.com/(\d+)/")

VIDEO_INFO_URL = "https://imd0mxanj2.execute-api.us-west-2.amazonaws.com/upload/info"
PLAYLIST_URL = "https://imd0mxanj2.execute-api.us-west-2.amazonaws.com/playlist"
TENANT_CONFIG_URL = "https://837sc3bew0.execute-api.us-west-2.amazonaws.com"
HOME_LISTING_URL = "https://2kbyogxrg4.execute-api.us-west-2.amazonaws.com"
CLOUDFRONT_BASE = "https://dlttx48mxf9m3.cloudfront.net"
CANONICAL_VIDEO_URL = "https://cloud.castus.tv/vod/{tenant}/video/{video_id}?page=HOME"

# The self-hosted "Castus VOD Widget" product (module docstring, Millbury
# MA) lives on `{tenant}.vod.castus.tv`; the cloud SPA this adapter
# handles lives on `cloud.castus.tv`.
_SELF_HOSTED_HOST_RE = re.compile(r"(^|\.)vod\.castus\.tv$", re.I)

# See module docstring's jurisdiction note -- one real confirmed entry so
# far, added only after a live cross-check (destinyhosted page text +
# ZIP), not guessed from the destinyhosted tenant id alone.
_KNOWN_DESTINYHOSTED_TENANT_JURISDICTIONS = {
    "24568": "Billings, MT",
}

# A real second Castus customer confirmed 2026-08-30 with no destinyhosted
# link at all ("westfordcat", real content: "Select Board Meeting -
# 8/25/2026", confirmed via the same VIDEO_INFO_URL call resolve() makes,
# a distinct internal channel id from Billings' -- a genuinely separate
# tenant, not a duplicate). This is the first real exercise of the
# tenant-slug fallback path (_jurisdiction_from_tenant_slug()), and it
# fails there for two independently-confirmed reasons: (1) "cat"
# (Community Access Television branding) isn't one of the branding
# suffixes _jurisdiction_from_tenant_slug() strips, so "westfordcat" never
# reduces to "westford"; (2) even stripped, "Westford" is a genuine
# 6-state collision (MA/NY/VT/WI/MN/ND per jurisdiction_enrich's own
# subdivision table), so the lookup correctly declines rather than
# guessing wrong -- the fallback's own design already gets this right,
# it just needs a curated answer for this specific tenant, the same
# pattern _KNOWN_DESTINYHOSTED_TENANT_JURISDICTIONS above already
# established for the destinyhosted-linked case.
#
# Three more real tenants added 2026-09-23 with the listing walk (module
# docstring), each found by a CivicPlus homepage-link sweep that already
# named the government behind the link, and each cross-checked against
# the tenant's own real content:
# - "blackstone": the generic path returned "Blackstone, VA" -- WRONG.
#   This is Blackstone, MA (its own `recent` feed has "BMR School
#   Committee 09-10-26" -- Blackstone-Millville Regional, MA -- and the
#   sweep found it from the town's own site). Real wrong guess, so a
#   curated entry is required, not optional. (Why the generic lookup
#   didn't decline the MA/VA collision the way it declines Westford's is
#   a jurisdiction_enrich question, not fixed here.)
# - "lincoln": the generic path declines (many-state collision). Lincoln,
#   MA -- its playlists include "Hanscom Field Advisory Commission"
#   (Hanscom Field is in Lincoln/Bedford, MA) and the sweep found it from
#   the town's own site.
# - "durham": the generic path declines (many-state collision). Durham,
#   NH per the sweep; its hand-confirmed video is "Town Council Meeting
#   6/15/26" (Durham, NH has a Town Council; Durham, NC has a City
#   Council).
# "tyngsborough" is deliberately NOT curated: the generic path already
# returns "Tyngsborough, MA" (nationally unique name), which its own
# playlist confirms ("Tyngsborough, MA Pre-Town Meeting Informational
# Session | April 29, 2025") -- the first real positive for that path.
_KNOWN_TENANT_SLUG_JURISDICTIONS = {
    "westfordcat": "Westford, MA",
    "blackstone": "Blackstone, MA",
    "lincoln": "Lincoln, MA",
    "durham": "Durham, NH",
}


class CastusAssetFinder(AssetFinder):
    """Resolves video + transcript for a Castus (cloud.castus.tv) meeting
    page -- see this module's own docstring above for the full
    investigation (every endpoint here is plain, unauthenticated HTTP,
    reverse-engineered from the SPA's own webpack bundles, not a
    headless-browser fetch)."""

    platform_name = "castus"

    async def resolve(self, url: str) -> ResolvedMeeting:
        if _SELF_HOSTED_HOST_RE.search(urlparse(url).netloc or ""):
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "This is a self-hosted Castus VOD Widget site (a different "
                    "product from cloud.castus.tv) -- not supported yet."
                ],
            )
        # The redirect shell (module docstring) rewrites `/vod/{tenant}/...`
        # to the hash-router form `/vod/#/{tenant}/...`, which is what a
        # browser's address bar shows afterwards -- accept either.
        path_url = url.replace("/vod/#/", "/vod/", 1)

        match = _URL_RE.search(path_url)
        if match:
            tenant, video_id = match.group(1), match.group(2)
            async with aiohttp.ClientSession() as session:
                return await self._resolve_video(session, url, tenant, video_id)

        playlist_match = _PLAYLIST_URL_RE.search(path_url)
        hub_match = None if playlist_match else _HUB_URL_RE.search(path_url)
        if not playlist_match and not hub_match:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=["Could not find a tenant/video id in this Castus URL."],
            )

        async with aiohttp.ClientSession() as session:
            if playlist_match:
                tenant = playlist_match.group(1)
                playlist_name = unquote(playlist_match.group(2))
                candidates, warning = await self._playlist_videos(
                    session, tenant, playlist_name
                )
                picked = self._pick_newest(candidates, require_allowlist=False)
                if not picked and not warning:
                    warning = (
                        f'No finished, meeting-shaped video found in the "{playlist_name}" '
                        "playlist on this Castus channel."
                    )
            else:
                tenant = hub_match.group(1)
                candidates, warning = await self._recent_videos(session, tenant)
                picked = self._pick_newest(candidates, require_allowlist=True)
                if not picked and not warning:
                    warning = (
                        "No finished, meeting-shaped video found in this Castus "
                        "channel's recent videos. Try one of its playlist pages instead."
                    )
            if not picked:
                return ResolvedMeeting(
                    platform=self.platform_name,
                    source_url=url,
                    video_warnings=[warning],
                )
            video_id = picked["_id"]
            canonical = CANONICAL_VIDEO_URL.format(tenant=tenant, video_id=video_id)
            return await self._resolve_video(session, canonical, tenant, video_id)

    async def _resolve_video(
        self,
        session: aiohttp.ClientSession,
        url: str,
        tenant: str,
        video_id: str,
    ) -> ResolvedMeeting:
        """The original one-video resolve, unchanged in behavior; the
        listing walk above lands here with the picked video's own
        canonical URL as `url`."""
        file_info = await self._fetch_video_info(session, video_id)
        if not file_info:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=["No video found for this Castus meeting."],
            )

        title, date = self._split_title_date(
            (file_info.get("metadata") or {}).get("filename")
        )

        video_warnings: List[str] = []
        transcript_warnings: List[str] = []

        video_url: Optional[str] = None
        video_format: Optional[str] = None
        if file_info.get("transcoded"):
            video_url = f"{CLOUDFRONT_BASE}/outputs/{video_id}/Default/HLS/out.m3u8"
            video_format = "m3u8"
        else:
            video_warnings.append(
                "This meeting's video hasn't finished processing on Castus yet."
            )

        segments: List[TranscriptSegment] = []
        transcript_language: Optional[str] = None
        if file_info.get("captioned"):
            cues = await self._fetch_vtt(
                session, f"{CLOUDFRONT_BASE}/captions/{video_id}.vtt"
            )
            if cues:
                segments = [TranscriptSegment(**cue) for cue in cues]
                transcript_language = detect_language_from_texts(
                    c["text"] for c in cues
                )
                if is_likely_garbled(cues, lang=transcript_language):
                    transcript_warnings.append(
                        "This transcript looks garbled at the source (not a "
                        "parsing bug on our end) -- treat it as approximate. "
                        "You can request a transcript from the audio instead."
                    )
            else:
                transcript_warnings.append(
                    "This meeting has video but no caption file was found -- "
                    "captioning doesn't appear to have been generated for it yet."
                )
        else:
            transcript_warnings.append("No transcript found for this event.")

        agenda_items, jurisdiction = await self._agenda_and_jurisdiction(
            session, file_info.get("agenda") or [], tenant
        )

        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            external_id=f"castus:{tenant}:{video_id}",
            title=title,
            date=date,
            jurisdiction=jurisdiction,
            video_url=video_url,
            video_format=video_format,
            segments=segments,
            agenda_items=agenda_items,
            transcript_language=transcript_language,
            video_warnings=video_warnings,
            transcript_warnings=transcript_warnings,
        )

    @staticmethod
    async def _fetch_video_info(
        session: aiohttp.ClientSession, video_id: str
    ) -> Optional[dict]:
        try:
            async with session.post(
                VIDEO_INFO_URL,
                json={"file": video_id},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as response:
                if response.status != 200:
                    return None
                data = await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError):
            return None
        try:
            return data["response"]["payload"]["file"]
        except (KeyError, TypeError):
            return None

    @staticmethod
    async def _get_json(session: aiohttp.ClientSession, url: str):
        """One GET, JSON or None -- every listing endpoint (module
        docstring) is a plain unauthenticated GET; the failure shapes
        seen live are a 404 with a plain-text body for an unknown tenant
        and a 500 with a plain-text body for an unknown playlist name,
        both of which land as None here."""
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status != 200:
                    return None
                return await response.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError):
            return None

    @staticmethod
    async def _playlist_videos(
        session: aiohttp.ClientSession, tenant: str, playlist_name: str
    ) -> Tuple[List[dict], Optional[str]]:
        """`GET {PLAYLIST_URL}/{tenant}/{name}` -- the SPA's own
        slug-keyed playlist call (module docstring), one request, no
        channel-id lookup. Returns (videos, warning)."""
        url = f"{PLAYLIST_URL}/{quote(tenant, safe='')}/{quote(playlist_name, safe='')}"
        data = await CastusAssetFinder._get_json(session, url)
        if not isinstance(data, dict):
            return [], (
                f'Could not find a playlist named "{playlist_name}" on this '
                "Castus channel."
            )
        response = data.get("response") or {}
        videos = response.get("payload")
        if not response.get("success") or not isinstance(videos, list):
            return [], (
                f'Could not find a playlist named "{playlist_name}" on this '
                "Castus channel."
            )
        return [v for v in videos if isinstance(v, dict)], None

    @staticmethod
    async def _recent_videos(
        session: aiohttp.ClientSession, tenant: str
    ) -> Tuple[List[dict], Optional[str]]:
        """Two requests, both the SPA's own (module docstring): the
        tenant config for the internal channel id, then that channel's
        `home/recent` list. Returns (videos, warning)."""
        config = await CastusAssetFinder._get_json(
            session, f"{TENANT_CONFIG_URL}/{quote(tenant, safe='')}"
        )
        channel_id = (config or {}).get("user") if isinstance(config, dict) else None
        if not channel_id:
            return [], "Could not find this Castus channel's configuration."
        recent = await CastusAssetFinder._get_json(
            session, f"{HOME_LISTING_URL}/{quote(str(channel_id), safe='')}/home/recent"
        )
        if not isinstance(recent, list):
            return [], "Could not load this Castus channel's recent videos."
        return [v for v in recent if isinstance(v, dict)], None

    @staticmethod
    def _pick_newest(
        videos: List[dict], *, require_allowlist: bool
    ) -> Optional[dict]:
        """Newest finished, non-premiere, meeting-shaped video (module
        docstring's "Newest" and "Why a PLAYLIST URL" notes): ordered by
        upload `date` descending, then the playlist's own `sort`
        position ascending. `require_allowlist` is True for a hub walk
        (mixed channel feed), False for a curated playlist."""
        now = datetime.now(timezone.utc)
        candidates = []
        for video in videos:
            if not video.get("_id") or not video.get("transcoded"):
                continue
            premiere = CastusAssetFinder._parse_iso(video.get("premiereDate"))
            if premiere and premiere > now:
                continue
            title = ((video.get("metadata") or {}).get("filename") or "").strip()
            if not looks_like_real_meeting(title, require_allowlist=require_allowlist):
                continue
            uploaded = CastusAssetFinder._parse_iso(video.get("date"))
            sort_pos = video.get("sort")
            candidates.append(
                (
                    uploaded or datetime.min.replace(tzinfo=timezone.utc),
                    -(sort_pos if isinstance(sort_pos, (int, float)) else float("inf")),
                    video,
                )
            )
        if not candidates:
            return None
        candidates.sort(key=lambda c: (c[0], c[1]), reverse=True)
        return candidates[0][2]

    @staticmethod
    def _parse_iso(value) -> Optional[datetime]:
        if not value or not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    @staticmethod
    async def _fetch_vtt(session: aiohttp.ClientSession, vtt_url: str):
        try:
            async with session.get(
                vtt_url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status != 200:
                    return None
                raw = await response.read()
        except (aiohttp.ClientError, TimeoutError):
            return None
        cues = parse_vtt(decode_vtt_bytes(raw))
        return cues or None

    @staticmethod
    def _split_title_date(
        raw_title: Optional[str],
    ) -> Tuple[Optional[str], Optional[str]]:
        if not raw_title:
            return None, None
        raw_title = raw_title.strip()
        match = _TITLE_DATE_RE.match(raw_title)
        if not match:
            return raw_title or None, None
        title, date_text = match.groups()
        for fmt_text in (date_text, date_text.replace(",", "")):
            for fmt in ("%B %d %Y", "%b %d %Y"):
                try:
                    from datetime import datetime

                    return title.strip() or None, datetime.strptime(
                        fmt_text, fmt
                    ).strftime("%Y-%m-%d")
                except ValueError:
                    continue
        return title.strip() or None, None

    @staticmethod
    async def _agenda_and_jurisdiction(
        session: aiohttp.ClientSession, raw_agenda: list, tenant: str
    ) -> Tuple[List[TranscriptSegment], Optional[str]]:
        agenda_items: List[TranscriptSegment] = []
        destinyhosted_link: Optional[str] = None

        for item in raw_agenda:
            start = item.get("time")
            duration = item.get("duration") or 0
            text = " ".join(
                part.strip()
                for part in (item.get("title"), item.get("text"))
                if part and part.strip()
            )
            if start is not None and text:
                agenda_items.append(
                    TranscriptSegment(
                        start=float(start),
                        end=max(float(start) + float(duration), float(start)),
                        text=text,
                    )
                )
            if destinyhosted_link is None:
                for link in item.get("hyperlinks") or []:
                    href = link.get("link") or ""
                    if "destinyhosted.com" in urlparse(href).netloc:
                        destinyhosted_link = href
                        break

        jurisdiction = None
        if destinyhosted_link:
            jurisdiction = await CastusAssetFinder._jurisdiction_from_destinyhosted(
                session, destinyhosted_link
            )
        if not jurisdiction:
            jurisdiction = CastusAssetFinder._jurisdiction_from_tenant_slug(tenant)
        return agenda_items, jurisdiction

    @staticmethod
    async def _jurisdiction_from_destinyhosted(
        session: aiohttp.ClientSession, link_url: str
    ) -> Optional[str]:
        try:
            async with session.get(
                link_url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status != 200:
                    return None
                html = await response.text()
        except (aiohttp.ClientError, TimeoutError, UnicodeDecodeError):
            return None

        soup = BeautifulSoup(html, "html.parser")
        page_text = soup.get_text(" ", strip=True)
        jurisdiction = jurisdiction_enrich.extract_jurisdiction_chain(
            page_text=page_text, html=html, url=link_url
        )
        if not jurisdiction:
            return None

        jurisdiction = jurisdiction_enrich.enrich_jurisdiction_text(
            jurisdiction, netloc=urlparse(link_url).netloc, page_text=page_text
        )
        if jurisdiction and "," not in jurisdiction:
            # See module docstring -- this real page's own ZIP (a PO Box,
            # not a Census-covered ZCTA) can't fill in the state
            # automatically, so fall back to the known-tenant map for a
            # confirmed destinyhosted tenant id.
            tenant_id_match = _DESTINYHOSTED_TENANT_ID_RE.search(link_url)
            if tenant_id_match:
                known = _KNOWN_DESTINYHOSTED_TENANT_JURISDICTIONS.get(
                    tenant_id_match.group(1)
                )
                if known:
                    return known
        return jurisdiction

    @staticmethod
    def _jurisdiction_from_tenant_slug(tenant: str) -> Optional[str]:
        """Confirmed live 2026-08-30 against a real second customer,
        "westfordcat" (Westford, MA) -- Billings' own "comm7tv" doesn't
        parse as a place name (its jurisdiction comes from the
        destinyhosted hyperlink path above instead), so this path was
        previously unexercised. First checks
        `_KNOWN_TENANT_SLUG_JURISDICTIONS` for a curated answer (needed
        for westfordcat: "cat" -- Community Access Television branding --
        isn't a suffix this strips, and even stripped, "Westford" is a
        genuine 6-state collision the generic lookup correctly declines
        rather than guessing). Falls back to stripping a handful of
        common channel-branding suffixes, then deferring entirely to
        jurisdiction_enrich's own Census-backed name tables for a future
        tenant whose slug is place-shaped and nationally unambiguous.
        """
        known = _KNOWN_TENANT_SLUG_JURISDICTIONS.get(tenant.lower())
        if known:
            return known
        candidate = re.sub(
            r"(tv|gov|access|media|county|city)$", "", tenant, flags=re.I
        )
        candidate = re.sub(r"[^a-zA-Z]+", " ", candidate).strip()
        if len(candidate) < 3:
            return None
        state = jurisdiction_enrich.lookup_city_state(
            candidate
        ) or jurisdiction_enrich.lookup_county_state(candidate)
        return f"{candidate.title()}, {state}" if state else None
