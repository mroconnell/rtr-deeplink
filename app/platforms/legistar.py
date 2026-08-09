import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder, CalendarPageError, resolve_via_platform
from .models import ResolvedMeeting


class LegistarAssetFinder(AssetFinder):
    """Resolves a Legistar URL by finding and delegating to the real video
    platform underneath -- Legistar itself is a calendar/agenda system, not
    a video host.

    Confirmed on a real Legistar site (maricopa.legistar.com, 2026-08-06):
    every "Video" link on a calendar or meeting-detail page is
    `Video.aspx?Mode=Granicus&ID1={id}&Mode2=Video`, a server-side redirect
    straight to a `*.granicus.com/player/clip/{id}` URL -- confirmed via
    Paradise Valley AZ's sample URL, which redirects exactly that way. The
    onclick handler containing that link (`a.videolink[onclick]`) is present
    in static server-rendered HTML, so no headless browser is needed to find
    it.

    Three cases, all confirmed against real Maricopa, AZ pages:
      1. The given URL itself already redirects off legistar.com (e.g. a
         direct Video.aspx link) -- delegate to whatever platform it landed
         on via `resolve_via_platform`.
      2. The page is a single meeting (MeetingDetail.aspx) -- confirmed
         these have exactly one `a.videolink` with a real onclick. Follow
         that link, then delegate the same way.
      3. The page is a calendar/listing (Calendar.aspx) with more than one
         video link -- confirmed Maricopa's calendar had 20 across 47 rows.
         Raise CalendarPageError with per-meeting title/date/url pulled
         from each row, so the frontend can offer a pick-list instead of
         guessing which meeting the user meant.
    """

    platform_name = "legistar"

    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            ),
        }

    async def resolve(self, url: str) -> ResolvedMeeting:
        async with aiohttp.ClientSession(headers=self.headers) as session:
            final_url, html = await self._fetch(session, url)

            if not self._is_legistar_domain(final_url):
                return await resolve_via_platform(final_url)

            soup = BeautifulSoup(html, "html.parser")
            video_links = self._find_video_links(soup, final_url)

            if not video_links:
                return ResolvedMeeting(
                    platform=self.platform_name,
                    source_url=url,
                    video_warnings=["No video link found on this Legistar page."],
                )

            if len(video_links) > 1:
                raise CalendarPageError(
                    message=(
                        "This looks like a calendar page listing multiple meetings, "
                        "not a link to one specific meeting."
                    ),
                    candidates=video_links,
                )

            target_final_url, _ = await self._fetch(session, video_links[0]["url"])
            if not self._is_legistar_domain(target_final_url):
                return await resolve_via_platform(target_final_url)

            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=["Found a video link, but it didn't lead to a supported platform."],
            )

    @staticmethod
    def _is_legistar_domain(url: str) -> bool:
        # Real bug fixed 2026-08-08: this used to be a bare "legistar.com"
        # substring check, which -- for NYC's custom nyc.gov domain --
        # incorrectly evaluated False even on NYC's own Legistar pages,
        # sending final_url straight back into resolve_via_platform()
        # (detect_platform() maps it to "legistar" again, so this would
        # have recursed on the exact same URL rather than ever reaching
        # _find_video_links). Kept in one place, matching detect_platform()
        # (base.py)'s own hardcoded domain list, rather than drifting.
        netloc = urlparse(url).netloc.lower()
        return "legistar.com" in netloc or "legistar.council.nyc.gov" in netloc

    @staticmethod
    async def _fetch(session: aiohttp.ClientSession, url: str):
        async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=30)) as response:
            response.raise_for_status()
            return str(response.url), await response.text()

    def _find_video_links(self, soup: BeautifulSoup, page_url: str) -> List[dict]:
        candidates = []
        for a in soup.select("a.videolink"):
            onclick = a.get("onclick") or ""
            # Two real onclick shapes seen so far, both on a.videolink:
            # plain window.open(...) (Maricopa AZ and every other Legistar
            # city checked), and NYC's OpenTelerikWindow(...) Telerik modal
            # -- confirmed live 2026-08-08, same a.videolink selector and
            # Video.aspx target underneath, just a different JS call
            # wrapping it.
            match = re.search(r"(?:window\.open|OpenTelerikWindow)\('([^']+)'", onclick)
            if not match or "Video.aspx" not in match.group(1):
                continue
            absolute = urljoin(page_url, match.group(1).replace("&amp;", "&"))
            title, date = self._extract_row_info(a)
            candidates.append({"title": title, "date": date, "url": absolute})
        return candidates

    @staticmethod
    def _extract_row_info(a):
        tr = a.find_parent("tr")
        title = "Untitled meeting"
        date = ""
        if tr:
            cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            if cells and cells[0]:
                title = cells[0]
            if len(cells) > 1 and cells[1]:
                date = LegistarAssetFinder._parse_date(cells[1]) or cells[1]
        return title, date

    @staticmethod
    def _parse_date(text: str) -> Optional[str]:
        try:
            return datetime.strptime(text.strip(), "%m/%d/%Y").strftime("%Y-%m-%d")
        except ValueError:
            return None
