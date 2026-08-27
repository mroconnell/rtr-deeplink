from datetime import datetime
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder, CalendarPageError, detect_platform, resolve_via_platform
from .granicus import US_STATE_ABBREVIATIONS
from .models import ResolvedMeeting
from ..utils import jurisdiction_enrich


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
            async with session.get(
                url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response.raise_for_status()
                final_url = str(response.url)
                html = await response.text()

        # Real, confirmed-live signal-loss fix, 2026-08-27: a delegated
        # video's own jurisdiction guess (`resolve_via_platform()`'s own
        # result) depends entirely on whatever that platform's own page/
        # channel data says -- for YouTube specifically, a real government
        # channel name can be a genuine multi-state collision ("City of
        # Westminster, Maryland" declines to validate on its own, since
        # Westminster is also real in CA/CO/SC/VT -- see BACKLOG_DONE.md).
        # CivicPlus's own subdomain is a stronger, authoritative,
        # per-tenant signal that already disambiguates this for free
        # ("md-westminster.civicplus.com" -- the state is right there),
        # so it's preferred outright over the delegated platform's own
        # guess, not just used as a fallback when that guess is empty --
        # same "the subdomain's own validated identity wins outright"
        # precedent `jurisdiction_enrich.finalize_jurisdiction()` already
        # documents for platforms that never leave their own domain.
        subdomain_jurisdiction = self._jurisdiction_from_subdomain(url)

        if "civicplus.com" not in urlparse(final_url).netloc.lower():
            result = await resolve_via_platform(final_url)
            if subdomain_jurisdiction:
                result.jurisdiction = subdomain_jurisdiction
            return result

        soup = BeautifulSoup(html, "html.parser")
        candidates = self._find_video_rows(soup, final_url)

        if not candidates:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                jurisdiction=subdomain_jurisdiction,
                video_warnings=["No video link found on this CivicPlus page."],
            )

        if len(candidates) > 1:
            raise CalendarPageError(
                message=(
                    "This looks like an agenda listing page with multiple meetings, "
                    "not a link to one specific meeting."
                ),
                candidates=candidates,
                jurisdiction_hint=subdomain_jurisdiction,
            )

        result = await resolve_via_platform(candidates[0]["url"])
        if subdomain_jurisdiction:
            result.jurisdiction = subdomain_jurisdiction
        return result

    @staticmethod
    def _jurisdiction_from_subdomain(url: str) -> Optional[str]:
        """CivicPlus's own AgendaCenter subdomains follow a real, stable
        `{2-letter state code}-{name}.civicplus.com` convention (confirmed
        across hundreds of real tenants, e.g. `md-westminster`,
        `ca-ventura`, `ri-eastgreenwich`). The state is authoritative --
        given directly by the tenant's own registered subdomain, not
        guessed -- so this only needs to confirm the `name` half is a real
        place, never resolve a state ambiguity the way a bare-name lookup
        does (`lookup_city_state()` alone declines "Westminster": real in
        five different states). Declines (returns None) rather than
        guessing when the name half doesn't validate -- real for
        acronym-heavy tenants wordninja can't split correctly (confirmed:
        "hamiltoncountywwta", "fultoncountymagistratecourt" both decline)
        -- same honest-gap philosophy as every other adapter here.
        """
        netloc = urlparse(url).netloc.lower()
        label = netloc.split(".")[0]
        prefix, sep, rest = label.partition("-")
        if not sep or prefix not in US_STATE_ABBREVIATIONS or not rest:
            return None
        name = jurisdiction_enrich.validated_label_extract(rest)
        if not name:
            return None
        return f"{name}, {prefix.upper()}"

    def _find_video_rows(self, soup: BeautifulSoup, page_url: str) -> List[dict]:
        candidates = []
        for row in soup.find_all("tr", class_="catAgendaRow"):
            media_cell = row.find("td", class_="media")
            if not media_cell:
                continue
            video_link = next(
                (
                    a
                    for a in media_cell.find_all("a", href=True)
                    if detect_platform(a["href"]) != "unknown"
                ),
                None,
            )
            if not video_link:
                continue

            title = "Untitled meeting"
            first_td = row.find("td")
            title_link = (
                first_td.find("p").find("a")
                if first_td and first_td.find("p")
                else None
            )
            if title_link and title_link.get_text(strip=True):
                title = title_link.get_text(strip=True)

            date = ""
            strong = row.find("h3").find("strong") if row.find("h3") else None
            if strong:
                date = self._parse_date(
                    strong.get_text(" ", strip=True)
                ) or strong.get_text(" ", strip=True)

            candidates.append(
                {
                    "title": title,
                    "date": date,
                    "url": urljoin(page_url, video_link["href"]),
                }
            )
        return candidates

    @staticmethod
    def _parse_date(text: str) -> Optional[str]:
        for fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                return datetime.strptime(text.strip(), fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None
