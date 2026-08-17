import re
from typing import Optional
from urllib.parse import urlparse

import aiohttp

from .base import AssetFinder
from .models import ResolvedMeeting
from ..utils import jurisdiction_enrich

# CHAMP/ChampDS -- confirmed live 2026-08-13 against 6 independent real
# customers (Atlanta GA, Auburn NY, Gillette WY, Marlborough MA, Saco ME,
# Worcester MA), found by the user via a real Atlanta example
# (play.champds.com/atlantaga/event/1227). Every customer shares the
# exact same play.champds.com domain, with the customer as a path
# segment (`/{customer}/event/{id}`), not a subdomain -- unlike most
# platforms in this repo, no per-customer domain variation to worry
# about. The real page itself is a client-side-only shell (curl'd
# directly, confirmed empty -- title/date/player all start blank in the
# markup and get filled in by cds.event.js after load); the real data
# lives behind a plain, unauthenticated JSON GET at the same path on a
# different host: play.champds.com -> playapi.champds.com (mirrors
# cds.common.js's own client-side HOST-splicing logic).
_EVENT_PATH_RE = re.compile(r"/([^/]+)/event/(\d+)")


class ChampDSAssetFinder(AssetFinder):
    """CHAMP/ChampDS (play.champds.com) -- a government meeting-video
    platform, confirmed live 2026-08-13. Doesn't need a headless browser;
    the real API (playapi.champds.com) is a plain, unauthenticated JSON
    GET.

    Two real, independently-confirmed video shapes exist, but only one
    is actually usable here today:
    - `MediaInfo.DownloadURL` (e.g. Atlanta, Auburn NY): a direct,
      unauthenticated MP4 download -- confirmed live with a plain `curl`,
      no special headers needed. Used when present.
    - `MediaInfo.VOD2` (e.g. Gillette WY, Marlborough MA, Saco ME,
      Worcester MA -- the *majority* of the 6 customers checked, not an
      edge case): a relative HLS path, combined with the
      ServiceTypeID-8 entry's `URLBase` (found consistently at
      `ServicesAndMachineInfo["8"]` on every customer checked, though
      matched here by field, not assumed to always sit at that key)
      reconstructs the exact URL the page's own player requests
      (confirmed via its console log: "USING VOD2! {clipURL:
      https://securestream10.champds.com/VOD/event/Atlan.../master.m3u8}").
      **Deliberately NOT used as `video_url` here** -- confirmed live
      that `securestream10.champds.com` enforces a strict
      `Referer: https://play.champds.com/` check on every request for
      this master playlist (a plain `curl` with no referer, or any
      referer other than champds.com's own -- including this site's real
      domain -- gets a 406). The master playlist's own sub-resources
      (`index-v1-a1.m3u8`, then real `.ts` segments) are relative URLs on
      the same host, so the same check would presumably block every one
      of them too -- confirmed the check isn't just on the master file.
      Embedding this URL directly in `<video>`/hls.js on this site would
      send *this site's* referer, not champds.com's, and 406 in the
      browser. Making this playable for real would need a genuine
      streaming reverse-proxy (fetch server-side with the right header,
      rewrite every segment URL inside the playlist to route back through
      our own proxy) -- real, scoped infrastructure work, not a quick
      fix, and not attempted in this pass. See BACKLOG.md.

    Real agenda items exist in `Agenda.AgendaItems` (confirmed live,
    e.g. Gillette's "A. Call to Order") but carry no per-item time
    offset, only ordering -- same shape mismatch as Legistar's own
    "Meeting Items" table (see BACKLOG.md), so not forced into
    `agenda_items` (which needs real timestamps). `Agenda.Attachments`
    (e.g. Marlborough's real "Packet" PDF) is a much better fit for the
    single-link `agenda_link` field instead, and is exactly what this
    adapter uses.

    `MediaInfo.Captions` was empty on every one of the 6 real customers
    checked -- no positive example of a populated one, so its real shape
    is unconfirmed and deliberately not attempted here (same "don't
    claim a caption path works without a positive example" convention as
    CivicClerk/eScribe -- see BACKLOG.md).
    """

    platform_name = "champds"

    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            ),
        }

    async def resolve(self, url: str) -> ResolvedMeeting:
        match = _EVENT_PATH_RE.search(urlparse(url).path)
        if not match:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "Could not find a customer/event id in this ChampDS URL."
                ],
            )
        customer, event_id = match.group(1), match.group(2)
        api_url = f"https://playapi.champds.com/{customer}/event/{event_id}"

        async with aiohttp.ClientSession(headers=self.headers) as session:
            data = await self._fetch_json(session, api_url)

        if not data:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=["Could not reach the ChampDS API for this meeting."],
            )

        event = data.get("Event") or {}
        title = event.get("EventTitle") or None
        date = self._extract_date(event.get("EventDateTimeCustomerLocal"))
        jurisdiction = self._extract_jurisdiction(
            (data.get("Customer") or {}).get("CustomerName"), url
        )
        video_url, video_format = self._extract_video(data)
        agenda_link = self._extract_agenda_link(data.get("Agenda") or {}, customer)

        video_warnings = (
            [] if video_url else ["No video found for this ChampDS meeting."]
        )

        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            title=title,
            date=date,
            jurisdiction=jurisdiction,
            video_url=video_url,
            video_format=video_format,
            agenda_link=agenda_link,
            video_warnings=video_warnings,
            transcript_warnings=["No captions found for this ChampDS meeting."],
        )

    @staticmethod
    def _extract_date(customer_local: Optional[str]) -> Optional[str]:
        # "2025-02-11 18:30:00" -> "2025-02-11" -- already customer-
        # timezone-adjusted server-side, no conversion needed here.
        if not customer_local or len(customer_local) < 10:
            return None
        return customer_local[:10]

    @staticmethod
    def _extract_jurisdiction(customer_name: Optional[str], url: str) -> Optional[str]:
        if not customer_name:
            return None
        # Real shape confirmed live: "Atlanta GA"/"Worcester MA" -- a
        # space-separated city + state abbreviation, not a comma. No
        # "City of"/"County" framing to preserve here, unlike most other
        # adapters' free-text extraction.
        parts = customer_name.rsplit(" ", 1)
        if len(parts) == 2 and len(parts[1]) == 2 and parts[1].isalpha():
            return jurisdiction_enrich.enrich_jurisdiction_text(
                f"{parts[0]}, {parts[1].upper()}", netloc=urlparse(url).netloc
            )
        return customer_name

    @staticmethod
    def _extract_video(data: dict):
        # Only the direct MP4 download is used -- see the module
        # docstring for why MediaInfo.VOD2's HLS URL is deliberately not
        # returned here even when present (a confirmed-live referer
        # check on securestream10.champds.com would 406 in this site's
        # own browser context).
        media_info = data.get("MediaInfo") or {}
        download_url = media_info.get("DownloadURL")
        if download_url:
            return f"https://play.champds.com{download_url}", "mp4"
        return None, None

    @staticmethod
    def _extract_agenda_link(agenda: dict, customer: str) -> Optional[str]:
        attachments = agenda.get("Attachments") or []
        if not attachments:
            return None
        # Prefers a PDF-looking one, same convention as generic_fallback's
        # own agenda-link preference -- confirmed real shape so far
        # (Marlborough's single "Packet" attachment) only ever had one,
        # but a customer with several is plausible and unconfirmed.
        for att in attachments:
            name = att.get("MediaFileName") or ""
            if name.lower().endswith(".pdf"):
                return ChampDSAssetFinder._attachment_url(customer, att)
        first = attachments[0]
        return ChampDSAssetFinder._attachment_url(customer, first)

    @staticmethod
    def _attachment_url(customer: str, att: dict) -> Optional[str]:
        location, name = att.get("MediaFileLocation"), att.get("MediaFileName")
        if not location or not name:
            return None
        # Real path confirmed live via play.champds.com's own
        # cds.event.js (getAttachmentPath()) -- a commented-out older
        # `/ATT/{customer}/...` shape sits right next to it in the same
        # file, but this is the one still actually called.
        return f"https://play.champds.com/ATT/{customer}/{location}/{name}"

    @staticmethod
    async def _fetch_json(session: aiohttp.ClientSession, url: str) -> Optional[dict]:
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status != 200:
                    return None
                return await response.json(content_type=None)
        except Exception:
            return None
