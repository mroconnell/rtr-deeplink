from datetime import datetime
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder, CalendarPageError, detect_platform, resolve_via_platform
from .granicus import US_STATE_ABBREVIATIONS
from .models import ResolvedMeeting
from .youtube import YouTubeAssetFinder
from ..utils import jurisdiction_enrich


class MunicodeMeetingsAssetFinder(AssetFinder):
    """Resolves a Municode Meetings (`{tenant}.municodemeetings.com`) URL --
    like Legistar/CivicPlus/CivicWeb, this is an agenda/minutes CMS
    (Drupal-based, "MCC Portal"), not a video host of its own; it links out
    to whatever real video platform a tenant already uses.

    Real page structure, confirmed live 2026-09-01 against several real
    tenants (bristol-ri, hamburg-mi, fairoaksranch-tx; see
    `tests/fixtures/municode_meetings/README.md`):

    1. **Tenant homepage** (`https://{tenant}.municodemeetings.com/`, not a
       subpath) is a Drupal Views meetings table
       (`table.views-table`, one `tr` per meeting inside `tbody`). A row
       with real video has a populated
       `<td class="views-field views-field-field-video-link">` cell
       holding an `<a href=...>`. That href comes in two different real
       shapes, both confirmed live: an **absolute** link straight to the
       real video platform (fairoaksranch-tx: bare
       `https://www.youtube.com/live/{id}?si=...` links right in the
       table cell -- no second hop needed), or a **relative** link to a
       same-tenant meeting **detail** page (bristol-ri, hamburg-mi:
       `/bc-towncouncil/page/town-council-meeting-278`) that itself embeds
       the real video one hop further in.
    2. **Meeting detail page**: video is embedded via
       `<iframe id="mcc_agenda_video" src="...">` -- confirmed YouTube
       (bristol-ri, `//www.youtube.com/embed/{id}?rel=0`, protocol-
       relative) and confirmed **Vimeo** (hamburg-mi,
       `https://player.vimeo.com/video/1221763469`) -- so the delegated
       platform is genuinely not YouTube-only, this always routes through
       `resolve_via_platform()` rather than assuming a destination.

    **Real, confirmed false positive** (2026-08-31, found while scoping
    this adapter): a video-link href -- either in the homepage cell or in
    a detail page's own `mcc_agenda_video` iframe -- can be a bare Google
    account login wall (`accounts.google.com/ServiceLogin?...&service=
    youtube...`) rather than a real video. A naive substring match on
    "youtube" in that URL is a false positive (the domain is
    accounts.google.com, not youtube.com). Guarded against the same way
    `civicplus.py`'s `_is_real_video_link()` already does: `detect_platform()`
    is a real *domain* check (so the login-wall URL is correctly
    "unknown", not "youtube"), and a genuine youtube.com-domain link is
    additionally required to carry a real, parseable video id via
    `YouTubeAssetFinder.extract_video_id()` -- filters out a bare channel/
    `@handle`/user link the same way it does for CivicPlus.

    **Multi-candidate homepages are real and common** -- confirmed live,
    not assumed: bristol-ri has 4 populated video-link rows out of 25 on
    one fetch, hamburg-mi has 11, fairoaksranch-tx has 14. So this follows
    `CivicPlusAssetFinder`'s pick-list pattern (`CalendarPageError` with
    per-row `CalendarCandidate`s) rather than always grabbing the first/
    newest row the way the throwaway research script did.

    Candidate `url` values are NOT pre-validated against the false-positive
    class above at list-building time -- doing so would mean fetching every
    populated row's own detail page before the list can even be shown
    (Municode's cell often only has a same-tenant page link, not the final
    video URL, unlike CivicPlus's `td.media`). Real-video validation still
    happens, just deferred to whenever a candidate is actually resolved: a
    same-tenant detail-page candidate URL is still `municodemeetings.com`,
    so `resolve_via_platform()` re-dispatches it back through this same
    registered finder, which re-fetches that one page and applies the
    iframe-src validation above -- a login-walled pick degrades to "no
    video found" for that one meeting, not a crash, same honest-gap
    philosophy as every other adapter here.

    Agenda/packet links are only threaded through from a homepage listing
    row's own `views-field-field-agendas`/`views-field-field-packets`
    cells (mirrors CivicPlus: these come from the row that pointed at the
    video, not from whatever the delegated video platform's own page
    finds) -- confirmed real HTML+PDF pair per cell, distinguished by the
    `ip=True`/`ip=False` query flag on the `adaHtmlDocument` viewer link
    (`ip=True` = packet rendition) with the parallel PDF blob link as
    fallback. A meeting detail page fetched directly (no homepage row in
    hand) has its own, structurally different agenda/packet UI (JS-toggle
    buttons, not confirmed to reliably expose both renditions) -- not
    parsed, so `agenda_link`/`packet_link` are simply None in that case,
    an honest gap rather than a guess.
    """

    platform_name = "municode_meetings"

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

        subdomain_jurisdiction = self._jurisdiction_from_subdomain(url)
        soup = BeautifulSoup(html, "html.parser")

        table = soup.find("table", class_="views-table")
        if table is None:
            # Not a listing page -- treat as a single meeting detail page
            # (or a page with neither shape, which just falls through to
            # "no video found" below).
            return await self._resolve_detail_soup(
                soup, final_url, url, subdomain_jurisdiction
            )

        candidates = self._find_video_rows(table, final_url)

        if not candidates:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                jurisdiction=subdomain_jurisdiction,
                video_warnings=["No video link found on this Municode Meetings page."],
            )

        if len(candidates) > 1:
            raise CalendarPageError(
                message=(
                    "This looks like a meetings listing page with multiple "
                    "meetings, not a link to one specific meeting."
                ),
                candidates=[
                    {
                        "title": c["title"],
                        "date": c["date"],
                        "url": c["url"],
                        "agenda_link": c.get("agenda_link"),
                        "packet_link": c.get("packet_link"),
                    }
                    for c in candidates
                ],
                jurisdiction_hint=subdomain_jurisdiction,
            )

        row = candidates[0]
        result = await resolve_via_platform(row["url"])
        if subdomain_jurisdiction:
            result.jurisdiction = subdomain_jurisdiction
        result.agenda_link = result.agenda_link or row.get("agenda_link")
        result.packet_link = result.packet_link or row.get("packet_link")
        return result

    async def _resolve_detail_soup(
        self,
        soup: BeautifulSoup,
        final_url: str,
        original_url: str,
        subdomain_jurisdiction: Optional[str],
    ) -> ResolvedMeeting:
        """Handles a fetch already known not to be a listing page --
        called both from `resolve()` directly (a user pasted a detail-page
        URL) and, via `resolve_via_platform()`'s re-dispatch, when a
        listing row's candidate URL is itself a same-tenant detail page
        (see class docstring)."""
        iframe = soup.find("iframe", id="mcc_agenda_video")
        video_url = self._real_video_url(iframe, final_url) if iframe else None

        if not video_url:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=original_url,
                jurisdiction=subdomain_jurisdiction,
                video_warnings=[
                    "No video found on this Municode Meetings meeting page."
                ],
            )

        result = await resolve_via_platform(video_url)
        if subdomain_jurisdiction:
            result.jurisdiction = subdomain_jurisdiction
        return result

    @staticmethod
    def _real_video_url(iframe, page_url: str) -> Optional[str]:
        """Same false-positive discipline as `_is_real_video_link()` below,
        applied to a detail page's own `mcc_agenda_video` iframe src."""
        src = (iframe.get("src") or "").strip()
        if not src:
            return None
        absolute = urljoin(page_url, src)
        if not MunicodeMeetingsAssetFinder._is_real_video_link(absolute):
            return None
        return absolute

    @staticmethod
    def _is_real_video_link(href: str) -> bool:
        """See class docstring's "Real, confirmed false positive" section.
        Reuses `YouTubeAssetFinder.extract_video_id()` the same way
        `civicplus.py`'s `_is_real_video_link()` does, rather than a
        second, possibly-inconsistent regex."""
        platform = detect_platform(href)
        if platform == "unknown":
            return False
        if platform == "youtube":
            return YouTubeAssetFinder.extract_video_id(href) is not None
        return True

    def _find_video_rows(self, table, page_url: str) -> List[dict]:
        candidates = []
        tbody = table.find("tbody") or table
        page_netloc = urlparse(page_url).netloc.lower()
        for row in tbody.find_all("tr"):
            video_cell = row.find("td", class_="views-field-field-video-link")
            if not video_cell:
                continue
            link = video_cell.find("a", href=True)
            href = link["href"].strip() if link else ""
            if not href or href.startswith(("#", "javascript:")):
                continue

            absolute = urljoin(page_url, href)
            # An absolute link to a genuinely different host is validated
            # right away (no extra fetch needed, and it's the class of
            # false positive that's cheap to catch here -- see class
            # docstring). A same-tenant page link is accepted as a
            # candidate optimistically; its own real-video-ness is
            # verified lazily when it's actually resolved (either as the
            # sole candidate below, or later if picked from a pick-list),
            # via _resolve_detail_soup()'s iframe check.
            if urlparse(absolute).netloc.lower() != page_netloc:
                if not self._is_real_video_link(absolute):
                    continue

            title_cell = row.find("td", class_="views-field-title")
            title = (
                title_cell.get_text(strip=True) if title_cell else "Untitled meeting"
            )

            date = ""
            date_cell = row.find("td", attrs={"data-th": "Date"})
            if date_cell:
                span = date_cell.find("span", class_="date-display-single")
                if span and span.get("content"):
                    date = self._parse_iso_date(span["content"]) or ""
                if not date and span:
                    date = span.get_text(" ", strip=True)

            agenda_link, packet_link = self._extract_agenda_and_packet_links(
                row, page_url
            )

            candidates.append(
                {
                    "title": title or "Untitled meeting",
                    "date": date,
                    "url": absolute,
                    "agenda_link": agenda_link,
                    "packet_link": packet_link,
                }
            )
        return candidates

    @staticmethod
    def _extract_agenda_and_packet_links(row, page_url: str) -> tuple:
        """Real, confirmed shape (bristol-ri, 2026-09-01): a
        `views-field-field-agendas` cell holds the plain agenda's PDF and
        HTML (`adaHtmlDocument/index?...&ip=False`) renditions; a separate
        `views-field-field-packets` cell holds the packet's PDF and HTML
        (`...&ip=True`) renditions -- the `ip` flag is what actually
        distinguishes packet from plain agenda (not cell/class alone, in
        case a future tenant's markup omits one cell)."""

        def pick(cell) -> Optional[str]:
            if not cell:
                return None
            html_link = None
            pdf_link = None
            for a in cell.find_all("a", href=True):
                href = a["href"]
                if href.lower().endswith(".pdf"):
                    pdf_link = pdf_link or urljoin(page_url, href)
                else:
                    html_link = html_link or urljoin(page_url, href)
            return html_link or pdf_link

        agenda_cell = row.find("td", class_="views-field-field-agendas")
        packet_cell = row.find("td", class_="views-field-field-packets")
        return pick(agenda_cell), pick(packet_cell)

    @staticmethod
    def _parse_iso_date(content: str) -> Optional[str]:
        try:
            # e.g. "2026-08-19T19:00:00-04:00"
            return datetime.fromisoformat(content).strftime("%Y-%m-%d")
        except ValueError:
            return None

    @staticmethod
    def _jurisdiction_from_subdomain(url: str) -> Optional[str]:
        """Municode Meetings' own tenant subdomains follow a real, stable
        `{name}-{state abbr}.municodemeetings.com` convention -- confirmed
        across the full known population (e.g. `bristol-ri`,
        `columbus-wi`, `highlands-nj`, `uppermarlboro-md`). Note this is
        the REVERSE order from `CivicPlusAssetFinder.
        _jurisdiction_from_subdomain()`'s `{state}-{name}` convention --
        the state is a *suffix* here, not a prefix, so the split direction
        is deliberately backwards from that adapter's logic, not a copy
        of it. The state is still authoritative (the tenant's own
        registered subdomain, not guessed); only the name half needs
        `jurisdiction_enrich.validated_label_extract()` to confirm it's a
        real place, declining (returning None) rather than guessing for
        anything that doesn't validate -- same discipline as every other
        adapter here.
        """
        netloc = urlparse(url).netloc.lower()
        label = netloc.split(".")[0]
        rest, sep, suffix = label.rpartition("-")
        if not sep or suffix not in US_STATE_ABBREVIATIONS or not rest:
            return None
        name = jurisdiction_enrich.validated_label_extract(rest)
        if not name:
            return None
        return f"{name}, {suffix.upper()}"
