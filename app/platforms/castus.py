import re
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder
from .models import ResolvedMeeting, TranscriptSegment
from ..utils import jurisdiction_enrich
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
_URL_RE = re.compile(r"/vod/([^/?#]+)/video/([^/?#]+)")
_TITLE_DATE_RE = re.compile(r"^(.*?)\s*-\s*([A-Za-z]+ \d{1,2},? \d{4})$")
_DESTINYHOSTED_TENANT_ID_RE = re.compile(r"destinyhosted\.com/(\d+)/")

VIDEO_INFO_URL = "https://imd0mxanj2.execute-api.us-west-2.amazonaws.com/upload/info"
CLOUDFRONT_BASE = "https://dlttx48mxf9m3.cloudfront.net"

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
_KNOWN_TENANT_SLUG_JURISDICTIONS = {
    "westfordcat": "Westford, MA",
}


class CastusAssetFinder(AssetFinder):
    """Resolves video + transcript for a Castus (cloud.castus.tv) meeting
    page -- see this module's own docstring above for the full
    investigation (every endpoint here is plain, unauthenticated HTTP,
    reverse-engineered from the SPA's own webpack bundles, not a
    headless-browser fetch)."""

    platform_name = "castus"

    async def resolve(self, url: str) -> ResolvedMeeting:
        match = _URL_RE.search(url)
        if not match:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=["Could not find a tenant/video id in this Castus URL."],
            )
        tenant, video_id = match.group(1), match.group(2)

        async with aiohttp.ClientSession() as session:
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
                    if is_likely_garbled(cues):
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
