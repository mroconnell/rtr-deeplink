from datetime import datetime
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder, CalendarPageError, detect_platform, resolve_via_platform
from .models import ResolvedMeeting


class CivicPlusAssetFinder(AssetFinder):
    """Resolves a CivicPlus AgendaCenter URL by finding and delegating to the
    real video platform underneath -- like Legistar, CivicPlus is a
    document/agenda system, not a video host.

    Confirmed on a real CivicPlus site (ca-westlakevillage.civicplus.com,
    2026-08-06): an AgendaCenter category listing page (e.g.
    /AgendaCenter/City-Council-Meetings-3) is a table of `tr.catAgendaRow`
    rows, one per meeting, each with a date (`h3 > strong[aria-label]`), a
    title (`td > p > a`), and -- when video exists for that meeting -- a
    direct link in `td.media` to the real video platform (confirmed:
    `https://westlakevillage.granicus.com/player/clip/{id}...`, a real
    per-meeting Granicus URL, not just a general "browse the archive" link).
    16 such per-meeting video links were found on one real listing page.
    Unlike Legistar's onclick-based links, these are plain <a href> --
    server-rendered, no JS execution needed to find them.

    CivicPlus doesn't appear to have a "single meeting" URL shape the way
    Legistar's MeetingDetail.aspx does -- every AgendaCenter URL observed
    is a category listing with multiple dated rows. So: 0 video-bearing
    rows -> no video found; exactly 1 -> resolve it directly; more than 1
    -> CalendarPageError with a pick-list, same UX as Legistar's calendar
    case.
    """

    platform_name = "civicplus"

    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            ),
        }

    async def resolve(self, url: str) -> ResolvedMeeting:
        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=30)) as response:
                response.raise_for_status()
                final_url = str(response.url)
                html = await response.text()

        if "civicplus.com" not in urlparse(final_url).netloc.lower():
            return await resolve_via_platform(final_url)

        soup = BeautifulSoup(html, "html.parser")
        candidates = self._find_video_rows(soup, final_url)

        if not candidates:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=["No video link found on this CivicPlus page."],
            )

        if len(candidates) > 1:
            raise CalendarPageError(
                message=(
                    "This looks like an agenda listing page with multiple meetings, "
                    "not a link to one specific meeting."
                ),
                candidates=candidates,
            )

        return await resolve_via_platform(candidates[0]["url"])

    def _find_video_rows(self, soup: BeautifulSoup, page_url: str) -> List[dict]:
        candidates = []
        for row in soup.find_all("tr", class_="catAgendaRow"):
            media_cell = row.find("td", class_="media")
            if not media_cell:
                continue
            video_link = next(
                (a for a in media_cell.find_all("a", href=True) if detect_platform(a["href"]) != "unknown"),
                None,
            )
            if not video_link:
                continue

            title = "Untitled meeting"
            first_td = row.find("td")
            title_link = first_td.find("p").find("a") if first_td and first_td.find("p") else None
            if title_link and title_link.get_text(strip=True):
                title = title_link.get_text(strip=True)

            date = ""
            strong = row.find("h3").find("strong") if row.find("h3") else None
            if strong:
                date = self._parse_date(strong.get_text(" ", strip=True)) or strong.get_text(" ", strip=True)

            candidates.append({
                "title": title,
                "date": date,
                "url": urljoin(page_url, video_link["href"]),
            })
        return candidates

    @staticmethod
    def _parse_date(text: str) -> Optional[str]:
        for fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                return datetime.strptime(text.strip(), fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None
