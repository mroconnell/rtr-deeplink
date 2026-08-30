import html as html_module
import json
import logging
import re
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlparse

import aiohttp

from .base import AssetFinder, UnsupportedPlatformError, resolve_via_platform
from .models import ResolvedMeeting, TranscriptSegment
from .youtube import YouTubeAssetFinder
from ..utils import jurisdiction_enrich

logger = logging.getLogger("rtr_deeplink.civicweb")

# CivicWeb (iCompass, a Diligent brand -- footer-confirmed, a genuinely
# different vendor from eScribe despite both being Canadian civic-meeting
# platforms) doesn't host video itself -- confirmed live 2026-08-12 against
# a real Dallas County, TX meeting (dallascounty.civicweb.net): the "Video"
# tab's real network call is a plain, unauthenticated JSON API,
# `{origin}/api/videolink/{meetingId}`, returning a `YouTubeEventId` field
# directly -- CivicWeb is a YouTube-delegating platform, the same shape as
# Legistar/CivicPlus/PrimeGov, not a new video host to build playback for.
# Same "wrapper platform" delegation pattern as PrimeGov: calls
# YouTubeAssetFinder.resolve_video_id() directly with the original CivicWeb
# URL as source_url (not the Legistar/CivicPlus pattern, where source_url
# ends up being the delegated platform's own URL -- a known quirk, see
# BACKLOG.md), so "View original source" keeps pointing back to the real
# CivicWeb meeting page.
#
# Real per-item deep-linking data exists in this same schema
# (IndexPoints/LocalIndexPoints -- confirmed via the page's own camera-icon
# UI seeking the embedded player to each agenda item's timestamp) but was
# empty on the one real meeting checked -- not built here, per this repo's
# "don't claim a data path works without a positive example" convention;
# see BACKLOG.md.
#
# A second, genuinely different real CivicWeb URL shape -- confirmed live
# 2026-08-30, found via a Wayback Machine CDX search (Common Crawl doesn't
# index civicweb.net past robots.txt/homepage -- confirmed empirically,
# not assumed) for the "iCompass"-branded splitscreen video widget's own
# `media=true` query flag: a direct `{tenant}.civicweb.net/document/{id}/`
# link (also reachable via a `/filepro/document/{id}/{title}.html` alias
# on some tenants -- confirmed byte-identical content on achdidaho, so
# this adapter only needs to handle the shorter canonical form). Unlike
# the `Portal/MeetingInformation.aspx?Id=` shape above, the real meeting
# id here is NOT in the URL at all -- it's the page's own inline JS config
# (`"meetingId":{N}`), a different numeric value from the document id in
# the URL path (confirmed live: achdidaho document 36574 -> meetingId
# 702). That meetingId is the same identifier space `/api/videolink/`
# already keys on above (confirmed live: dallascounty meetingId 1957
# resolves the identical real "Commissioners Court - Oct 01 2024" meeting
# both via `Portal/MeetingInformation.aspx?Id=1957` and via a `/document/`
# page whose own config names meetingId 1957) -- just reached from a
# different real link shape CivicWeb's own UI generates. 108 distinct
# real government tenants confirmed carrying this exact `media=true` URL
# shape in the Wayback CDX index (a lower bound -- only what's been
# archived); 3 independently verified live end-to-end (Ada County
# Highway District ID, Des Moines WA, Dallas County TX) -- each a real,
# playable YouTube video confirmed via YouTube's own oEmbed endpoint,
# title matching exactly.
#
# Uses a real, richer, unauthenticated sibling API for this shape --
# `/api/geteventwithindexpoints/{meetingId}` -- confirmed to return
# everything `/api/videolink/` does (same `YouTube`/event-id fields,
# nested one level deeper under `Event`) PLUS real, populated
# `LocalIndexPoints` (confirmed live on both Des Moines and Dallas
# County's real meetings -- genuine per-agenda-item video timestamps,
# `{RelatedItem, ItemId, Value (seconds)}`) where `/api/videolink/`'s own
# `LocalIndexPoints` field came back empty on the one meeting originally
# checked (see this file's own comment above) -- not just a different
# meeting, the richer field is real and reachable, this app just wasn't
# calling the endpoint that populates it.
#
# `LocalIndexPoints` -> `agenda_items`, built 2026-08-30: the real
# mapping is `RelatedItem` (NOT `ItemId`, which turned out to be a
# secondary/duplicate reference -- confirmed by cross-checking every
# `RelatedItem` value against the document's own real anchor ids and
# finding a clean 1:1 match, while several `ItemId` values didn't
# correspond to any real anchor at all) against the document's own real
# HTML body -- confirmed the SAME `{numeric id}` used in `RelatedItem`
# is the literal suffix of an `<a name="AgendaHeadingN">` or
# `<a name="AgendaItemN">` anchor already embedded in
# `{origin}/document/{docId}/?record=false` (the plain agenda content,
# separate from the splitscreen wrapper page). Only `RelationshipTypeId
# == 6` entries match an anchor directly -- the `== 7` entries (also
# real, also present) point at a different, not-yet-understood
# relationship and were excluded rather than guessed at, since every
# `RelationshipTypeId == 6` entry checked (33 across the two verified
# tenants below) matched a real anchor exactly, and no `== 7` entry ever
# did.
#
# The anchor's own title text needs its own real, tenant-varying
# extraction: confirmed live on two independently-templated tenants --
# Des Moines puts the real heading text directly in the first non-empty
# `<span>` after the anchor ("CALL TO ORDER"), but a bare "Item N."
# label sits in that same first-span position for some (not all) of its
# own items, requiring a skip-and-continue; Dallas County's template
# puts an outline marker ("G.", "(5)") in that first span instead, with
# the real title one `<span>` further in ("INVOCATION"). Both skipped by
# `_AGENDA_LABEL_RE` so the walk continues to the real text -- confirmed
# correct on every one of 20 Dallas County items and 14 Des Moines items
# checked, not a guess extrapolated from one shape.
_DOCUMENT_PATH_ID_RE = re.compile(r"/document/(\d+)")
_CONFIG_MEETING_ID_RE = re.compile(r'"meetingId":(\d+)')
_AGENDA_ANCHOR_RE = re.compile(
    r'<a[^>]*name="(?:AgendaHeading|AgendaItem)(\d+)"[^>]*></a>'
)
_AGENDA_SPAN_RE = re.compile(r"<span[^>]*>([^<]*)</span>")
# A bare outline marker ("Item 3.", "G.", "(5)") -- real, confirmed-live
# filler text CivicWeb's own template puts ahead of the real title on
# some (not all) items; see module docstring.
_AGENDA_LABEL_RE = re.compile(r"^(?:Item\s+\d+\.?|[A-Za-z]\.|\(\d+\))$", re.IGNORECASE)
# Case-insensitive as of 2026-08-27: confirmed live that "Diligent
# Community" (community.diligentoneplatform.com), a real, currently-live
# second domain for the exact same underlying software -- same
# Portal/MeetingInformation.aspx path, same Services/MeetingsService.svc
# backend API, confirmed byte-identical live on a real tenant
# (winthropminnesota) -- uses a lowercase `id=` query param where classic
# civicweb.net tenants use `Id=`. Both real, both live; a case-sensitive
# match silently missed every Diligent Community tenant, real video and
# all (confirmed: MeetingExternalMinutesLinkUrl populated with a real
# youtu.be link on the same meeting this was found from).
_MEETING_ID_RE = re.compile(r"[?&][Ii]d=(\d+)")
_TITLE_JURISDICTION_RE = re.compile(
    r"<title>\s*([^<]+?)\s*-\s*Meeting Information\s*</title>", re.IGNORECASE
)


class CivicWebAssetFinder(AssetFinder):
    """iCompass/CivicWeb (Diligent) -- doesn't host video, delegates to
    YouTube via a real, unauthenticated JSON API. Two real URL shapes:
    `Portal/MeetingInformation.aspx?Id={id}` (`resolve()`'s main path) and
    a direct `/document/{id}/` splitscreen-widget link
    (`_resolve_document_shape()`) -- see module docstring above for both.
    """

    platform_name = "civicweb"

    async def resolve(self, url: str) -> ResolvedMeeting:
        meeting_id = self._extract_meeting_id(url)
        if not meeting_id:
            # A `/document/{id}/` (or `/filepro/document/{id}/...`) link --
            # see module docstring for the real second URL shape this
            # covers -- has no `Id=` query param at all, only checked once
            # the primary shape's own extraction has already declined.
            if _DOCUMENT_PATH_ID_RE.search(urlparse(url).path):
                return await self._resolve_document_shape(url)
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=["Could not find a meeting id in this CivicWeb URL."],
            )

        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"

        async with aiohttp.ClientSession() as session:
            html = await self._fetch_text(session, url)
            videolink = await self._fetch_json(
                session, f"{origin}/api/videolink/{meeting_id}"
            )
            meeting_data = await self._fetch_json(
                session,
                f"{origin}/Services/MeetingsService.svc/meetings/{meeting_id}/meetingData",
            )

        jurisdiction = self._extract_jurisdiction(html, url) if html else None
        title = meeting_data.get("Name") if meeting_data else None

        entry = videolink[0] if videolink else None
        video_id = entry.get("YouTubeEventId") if entry else None
        date = None
        if entry and entry.get("MeetingDate"):
            date = entry["MeetingDate"][:10]  # "2026-08-04T00:00:00" -> "2026-08-04"

        # Real, confirmed-live second video source, 2026-08-27: `/api/
        # videolink/{id}` (the only one previously checked) can come back
        # genuinely empty (`[]`) even when the meetingData service's own
        # MeetingExternalLinkUrl/MeetingExternalMinutesLinkUrl pair
        # carries a real video link -- confirmed on a real Winthrop, MN
        # meeting (winthropminnesota.community.diligentoneplatform.com,
        # a "Diligent Community"-branded second domain for the exact same
        # underlying software, see _MEETING_ID_RE's own comment): a real,
        # populated `youtu.be` URL sat in `MeetingExternalMinutesLinkUrl`
        # while `/api/videolink/` returned nothing. Each of these two
        # fields is a generic "external link" slot, not video-specific --
        # only trusted here when its own paired `...LinkName` field says
        # so, and delegated through `resolve_via_platform()` rather than
        # assumed to always be YouTube, since nothing here confirms that
        # for every tenant.
        external_video_url = None
        if meeting_data:
            for link_field, name_field in (
                ("MeetingExternalMinutesLinkUrl", "MeetingExternalMinutesLinkName"),
                ("MeetingExternalLinkUrl", "MeetingExternalLinkName"),
            ):
                link_url = meeting_data.get(link_field)
                link_name = meeting_data.get(name_field) or ""
                if link_url and "video" in link_name.lower():
                    external_video_url = link_url
                    break

        if not video_id and not external_video_url:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                title=title,
                date=date,
                jurisdiction=jurisdiction,
                video_warnings=["No video found for this meeting."],
            )

        if video_id:
            resolved = await YouTubeAssetFinder.resolve_video_id(
                video_id, source_url=url
            )
        else:
            try:
                resolved = await resolve_via_platform(external_video_url)
                resolved.source_url = url
            except UnsupportedPlatformError:
                # A real, live "video" link that isn't one this app can
                # play -- not confirmed to ever happen, but the field is
                # generic ("external link"), not guaranteed video, so
                # degrade to the same "no video" outcome rather than
                # letting an unhandled exception break the whole resolve.
                return ResolvedMeeting(
                    platform=self.platform_name,
                    source_url=url,
                    title=title,
                    date=date,
                    jurisdiction=jurisdiction,
                    video_warnings=["No video found for this meeting."],
                )
        if title:
            resolved.title = title
        if date:
            resolved.date = date
        if jurisdiction:
            resolved.jurisdiction = jurisdiction
        else:
            # Applying the same fix already confirmed live for lims.py and
            # generic_fallback.py (see BACKLOG_DONE.md): when this page's
            # own <title> extraction doesn't match (page shape varies more
            # than the one Dallas County example confirmed so far), this
            # used to silently keep whatever YouTubeAssetFinder set
            # jurisdiction to -- the channel's own uploader name, not a
            # jurisdiction. Unlike LIMS (single-tenant), CivicWeb is
            # multi-customer, so this only fires for a domain already
            # confirmed in jurisdiction_enrich's registry (e.g.
            # dallascounty.civicweb.net) rather than assuming any
            # civicweb.net subdomain is safe to guess at. Uses
            # known_jurisdiction_display() rather than LIMS's own
            # `f"{known.name}, {known.state}"` shortcut -- that shortcut
            # only works because LIMS's one confirmed domain is a *city*;
            # CivicWeb's confirmed domain is Dallas *County*, and dropping
            # the "County" distinction the same way would misleadingly
            # read as if this were a city named Dallas.
            resolved.jurisdiction = jurisdiction_enrich.known_jurisdiction_display(
                urlparse(url).netloc
            )
        return resolved

    @classmethod
    async def _resolve_document_shape(cls, url: str) -> ResolvedMeeting:
        """A `/document/{id}/` (or `/filepro/document/{id}/...`) link --
        see module docstring for the real second URL shape, evidence, and
        the richer `/api/geteventwithindexpoints/` API this uses. The
        numeric id in the URL is a *document* id, not the meeting id the
        API needs -- that only exists in this page's own inline config,
        so (unlike the `Id=` shape above) the page has to be fetched
        before any API call can be made at all.
        """
        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        doc_id_match = _DOCUMENT_PATH_ID_RE.search(parsed.path)

        async with aiohttp.ClientSession() as session:
            html = await cls._fetch_text(session, url)
            config_match = _CONFIG_MEETING_ID_RE.search(html) if html else None
            if not config_match:
                return ResolvedMeeting(
                    platform=cls.platform_name,
                    source_url=url,
                    video_warnings=[
                        "Could not find a meeting id in this CivicWeb URL."
                    ],
                )
            meeting_id = config_match.group(1)
            event_payload = await cls._fetch_json(
                session, f"{origin}/api/geteventwithindexpoints/{meeting_id}"
            )
            meeting_data = await cls._fetch_json(
                session,
                f"{origin}/Services/MeetingsService.svc/meetings/{meeting_id}/meetingData",
            )

            entry = event_payload[0] if event_payload else None
            event = (entry.get("Event") or {}) if entry else {}
            video_id = event.get("eventId") if entry and entry.get("YouTube") else None
            local_index_points = (entry.get("LocalIndexPoints") or []) if entry else []
            agenda_items: List[TranscriptSegment] = []
            # Only worth the extra fetch when there's both a video to seek
            # within and real per-item timestamps to place on it.
            if video_id and local_index_points and doc_id_match:
                body_html = await cls._fetch_text(
                    session, f"{origin}/document/{doc_id_match.group(1)}/?record=false"
                )
                if body_html:
                    agenda_items = cls._build_agenda_items(
                        body_html, local_index_points
                    )

        title = event.get("eventTitle") or (
            meeting_data.get("Name") if meeting_data else None
        )
        date = None
        if entry and entry.get("MeetingDate"):
            date = entry["MeetingDate"][:10]  # "2026-08-04T00:00:00" -> "2026-08-04"
        # This page's own HTML carries no jurisdiction-bearing text at all
        # (confirmed live on all 3 verified tenants -- no title, no
        # og:site_name, no visible chrome, just the split-screen widget
        # frame) -- only a confirmed known-domain gets one here, same
        # honest-decline posture as the Id= shape's own fallback above.
        jurisdiction = jurisdiction_enrich.known_jurisdiction_display(parsed.netloc)

        if not video_id:
            return ResolvedMeeting(
                platform=cls.platform_name,
                source_url=url,
                title=title,
                date=date,
                jurisdiction=jurisdiction,
                video_warnings=["No video found for this meeting."],
            )

        resolved = await YouTubeAssetFinder.resolve_video_id(video_id, source_url=url)
        if title:
            resolved.title = title
        if date:
            resolved.date = date
        resolved.jurisdiction = jurisdiction
        resolved.agenda_items = agenda_items
        return resolved

    @staticmethod
    def _build_agenda_items(
        body_html: str, local_index_points: List[dict]
    ) -> List[TranscriptSegment]:
        """Turns this meeting's real `LocalIndexPoints` into deep-link
        bookmarks -- see module docstring for the real mapping (matched
        by `RelatedItem` against the document's own real anchor ids,
        `RelationshipTypeId == 6` only) and the title-extraction shape
        confirmed across two independently-templated real tenants.
        """
        anchor_titles: Dict[int, str] = {}
        for anchor_match in _AGENDA_ANCHOR_RE.finditer(body_html):
            anchor_id = int(anchor_match.group(1))
            if anchor_id in anchor_titles:
                continue
            window = body_html[anchor_match.end() : anchor_match.end() + 2000]
            for span_match in _AGENDA_SPAN_RE.finditer(window):
                text = html_module.unescape(span_match.group(1))
                text = text.replace("\xa0", " ").strip()
                if text and not _AGENDA_LABEL_RE.match(text):
                    anchor_titles[anchor_id] = text
                    break

        raw: List[tuple] = []
        for point in local_index_points:
            if not isinstance(point, dict) or point.get("RelationshipTypeId") != 6:
                continue
            related_item = point.get("RelatedItem")
            value = point.get("Value")
            title = anchor_titles.get(related_item)
            if title and isinstance(value, (int, float)):
                raw.append((float(value), title))
        raw.sort(key=lambda pair: pair[0])

        items: List[TranscriptSegment] = []
        for i, (seconds, text) in enumerate(raw):
            end = raw[i + 1][0] if i + 1 < len(raw) else seconds
            items.append(
                TranscriptSegment(start=seconds, end=max(end, seconds), text=text)
            )
        return items

    @staticmethod
    def _extract_meeting_id(url: str) -> Optional[str]:
        query = parse_qs(urlparse(url).query)
        ids = query.get("Id")
        if ids and ids[0].isdigit():
            return ids[0]
        match = _MEETING_ID_RE.search(url)
        return match.group(1) if match else None

    @staticmethod
    def _extract_jurisdiction(html: str, url: str) -> Optional[str]:
        match = _TITLE_JURISDICTION_RE.search(html)
        if not match:
            return None
        jurisdiction = match.group(1).strip()
        # No state anywhere in this shape -- confirmed real, e.g. real
        # "Dallas County" (see module docstring). See BACKLOG.md's
        # "no-state jurisdiction audit".
        return jurisdiction_enrich.enrich_jurisdiction_text(
            jurisdiction, netloc=urlparse(url).netloc, page_text=html
        )

    @staticmethod
    async def _fetch_text(session: aiohttp.ClientSession, url: str) -> Optional[str]:
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "CivicWeb text fetch got HTTP %s for %s",
                        response.status,
                        url,
                    )
                    return None
                return await response.text()
        except Exception:
            logger.warning("CivicWeb text fetch failed for %s", url, exc_info=True)
            return None

    @staticmethod
    async def _fetch_json(session: aiohttp.ClientSession, url: str):
        """Real gap found live 2026-08-12: /api/videolink/{id} specifically
        (a WCF/.svc-family quirk, unlike the plain .svc meetingData
        endpoint) double-encodes its JSON -- the raw body is a JSON string
        literal ("[{...}]", quotes included) that itself contains the real
        JSON, not the array/object directly. A single response.json() call
        here returns a Python str, not the parsed structure -- confirmed
        live, .json() on the real response yields '[{"MeetingDate":...' as
        a string, not a list. Parses again whenever the first pass still
        yields a string, so this same helper is safe for both this
        endpoint and meetingData's normal single-encoded shape.
        """
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "CivicWeb JSON fetch got HTTP %s for %s",
                        response.status,
                        url,
                    )
                    return None
                data = await response.json()
        except Exception:
            logger.warning("CivicWeb JSON fetch failed for %s", url, exc_info=True)
            return None
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, ValueError):
                return None
        return data
