import json
import logging
import re
from typing import Optional
from urllib.parse import parse_qs, urlparse

import aiohttp

from .base import AssetFinder, UnsupportedPlatformError, resolve_via_platform
from .models import ResolvedMeeting
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
    YouTube via a real, unauthenticated JSON API. See module docstring
    above.
    """

    platform_name = "civicweb"

    async def resolve(self, url: str) -> ResolvedMeeting:
        meeting_id = self._extract_meeting_id(url)
        if not meeting_id:
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
