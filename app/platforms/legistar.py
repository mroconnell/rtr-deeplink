import logging
import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import (
    AssetFinder,
    CalendarPageError,
    find_platform_link,
    get_finder,
    resolve_via_platform,
)
from .models import ResolvedMeeting
from .youtube import YouTubeAssetFinder
from . import youtube_channel
from ..utils import jurisdiction_enrich

logger = logging.getLogger("rtr_deeplink.legistar")

# Confirmed live (2026-08-09) on two real NYC MeetingDetail.aspx pages: the
# outer page's own <title> reliably gives "{jurisdiction} - Meeting of
# {body} on {M}/{D}/{YYYY} at {time}" -- e.g. "The New York City Council -
# Meeting of Committee on Finance on 12/18/2025 at 11:30 AM". Used as a
# fallback when the delegated platform's own title is bad (see
# _looks_like_raw_filename below) -- confirmed real bug: ViebitAssetFinder
# (the platform underneath NYC's Legistar instance) has no better title of
# its own to offer, since Viebit's own `video.title` field is just the
# raw uploaded filename ("NYCC-250-8-2_251218-120823.mp4"), not a human
# title -- see BACKLOG.md.
_PAGE_TITLE_RE = re.compile(
    r"^(.*?)\s*-\s*Meeting of\s+(.+?)\s+on\s+(\d{1,2})/(\d{1,2})/(\d{4})\s+at\s+.+$",
    re.IGNORECASE,
)
_RAW_FILENAME_RE = re.compile(r"\.(mp4|mov|wmv|avi|mkv|m4v)$", re.IGNORECASE)


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

    If no `a.videolink` is found at all, `_try_fallback_video_link()`
    (added 2026-08-10) tries a broader scan before giving up -- confirmed
    live on Baltimore's Legistar instance: its "Recording" link (a real
    full meeting recording on YouTube) lives in a plain attachments
    table, not the `a.videolink` shape every other case here assumes.
    Same fallback chain `generic_fallback.py` uses for the identical
    problem on a non-Legistar page (a real YouTube link anywhere on the
    page first, then `base.find_platform_link()` for any other already-
    supported platform), reused rather than duplicated.

    If that finds nothing either, `_try_known_channel_video()` (added
    2026-08-21, WO-30) is the last resort -- for the four confirmed
    instances (Phoenix, Philadelphia, Baltimore, Albuquerque) where there
    is genuinely nothing on the page to parse because the city publishes
    its recordings only to its own YouTube channel. It matches the
    meeting's own name and date against a curated, human-verified channel
    listing; see `youtube_channel.py` for the matching rules and the real
    evidence behind them, and note that a wrong match there would be
    worse than no video at all, which is why every uncertain case
    declines.
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
                fallback = await self._try_fallback_video_link(html, final_url, soup)
                if fallback:
                    fallback.source_url = url
                    return fallback
                channel_match = await self._try_known_channel_video(
                    soup, final_url, url
                )
                if channel_match:
                    return channel_match
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

            page_info = self._extract_page_meeting_info(soup, final_url)
            target_final_url, _ = await self._fetch(session, video_links[0]["url"])
            if not self._is_legistar_domain(target_final_url):
                resolved = await resolve_via_platform(target_final_url)
                if page_info and self._looks_like_raw_filename(resolved.title):
                    resolved.title = page_info["title"]
                    resolved.jurisdiction = (
                        resolved.jurisdiction or page_info["jurisdiction"]
                    )
                    resolved.date = resolved.date or page_info["date"]
                # Applied regardless of title quality, unlike the block
                # above -- Legistar's own agenda link is real, useful
                # data even when the delegated platform's title/date are
                # already fine, and it's just a fallback for whenever the
                # delegated platform (e.g. Granicus's own AgendaViewer.php
                # link) didn't already find one itself.
                if page_info:
                    resolved.agenda_link = resolved.agenda_link or page_info.get(
                        "agenda_link"
                    )
                return resolved

            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "Found a video link, but it didn't lead to a supported platform."
                ],
            )

    @staticmethod
    async def _try_fallback_video_link(
        html: str, page_url: str, soup: BeautifulSoup
    ) -> Optional[ResolvedMeeting]:
        """Real gap confirmed live 2026-08-10: Baltimore's Legistar instance
        puts its video link in an attachments table as a plain
        `<a href="https://youtu.be/...">Recording</a>`, not the
        `a.videolink[onclick="window.open(...)"]` shape `_find_video_links()`
        looks for -- that pattern is Legistar's own system-generated markup
        for the "Video" button specifically, confirmed across Maricopa AZ
        and NYC, but doesn't cover a jurisdiction manually attaching a link
        to its own separately-hosted recording.

        Tries a real YouTube link anywhere on the page first (tighter,
        video-ID-validated -- `YouTubeAssetFinder.extract_video_id()`),
        then `find_platform_link()` for any other platform this app
        already supports (same fallback chain `generic_fallback.py` uses
        for the same class of problem on a non-Legistar page). Returns
        None on no match or any resolve failure, letting the caller fall
        back to the existing honest "No video link found" message.
        """
        video_id = YouTubeAssetFinder.extract_video_id(html)
        if video_id:
            resolved = await YouTubeAssetFinder.resolve_video_id(
                video_id, source_url=page_url
            )
        else:
            # "legistar" excluded too, defense-in-depth alongside base.py's
            # own same-URL check above -- this method only ever runs when
            # LegistarAssetFinder has already claimed page_url, so a match
            # that resolved back to "legistar" could only ever mean
            # re-delegating to itself.
            match = find_platform_link(
                html, page_url, exclude=frozenset({"youtube", "legistar"})
            )
            if not match:
                return None
            candidate, platform = match
            try:
                resolved = await get_finder(platform).resolve(candidate)
            except CalendarPageError:
                logger.debug(
                    "Legistar delegation to %s hit a calendar page for %s",
                    platform,
                    candidate,
                )
                return None
            except Exception:
                logger.warning(
                    "Legistar delegation to %s failed for %s",
                    platform,
                    candidate,
                    exc_info=True,
                )
                return None

        page_info = LegistarAssetFinder._extract_page_meeting_info(soup, page_url)
        if page_info:
            if (
                LegistarAssetFinder._looks_like_raw_filename(resolved.title)
                or not resolved.title
            ):
                resolved.title = page_info["title"]
            # Prefers page_info's jurisdiction outright here, not just as a
            # fallback for an empty one (unlike the primary a.videolink
            # delegation path above, left as-is) -- real bug confirmed live
            # 2026-08-10 (Baltimore): a delegated YouTube video's own
            # `uploader` field ("CharmTV Citizens' Hub", a TV station/
            # channel name) is real data, not empty, but still the wrong
            # answer to "what jurisdiction is this" -- Legistar's own page
            # is the more authoritative source whenever it has one.
            resolved.jurisdiction = page_info["jurisdiction"] or resolved.jurisdiction
            # Real bug found live 2026-08-21 while building WO-30: for a
            # YouTube delegation specifically, `resolved.date` is the
            # video's *upload* date, not the meeting date, so
            # "keep what's already there" quietly published the wrong one
            # -- Baltimore's real 2026-08-05 Public Health & Environment
            # hearing (the one meeting on that instance that does carry
            # its own Recording link) rendered as 2026-08-17, the day
            # CharmTV got around to posting it. Publication lag is
            # confirmed to run up to a week on real uploads (see
            # youtube_channel.video_date_is_plausible), so the Legistar
            # page's own date wins outright here. Narrowed to the YouTube
            # case on purpose: the other platforms this method can
            # delegate to via find_platform_link() carry a real meeting
            # date of their own, and none has been observed getting it
            # wrong.
            if resolved.platform == YouTubeAssetFinder.platform_name:
                resolved.date = page_info["date"] or resolved.date
            else:
                resolved.date = resolved.date or page_info["date"]
            resolved.agenda_link = resolved.agenda_link or page_info.get("agenda_link")
        return resolved

    @staticmethod
    async def _try_known_channel_video(
        soup: BeautifulSoup, page_url: str, source_url: str
    ) -> Optional[ResolvedMeeting]:
        """Last resort, for the four confirmed Legistar instances whose
        video column is structurally empty while the real recordings sit
        unlinked on the city's own YouTube channel (WO-30, 2026-08-21 --
        Phoenix, Philadelphia, Baltimore, and Albuquerque's committee
        meetings; see `youtube_channel.py` for the evidence behind each).

        Runs only after `_try_fallback_video_link()` has already found
        nothing, so a tenant that *does* attach its own recording (a real
        minority of Baltimore meetings) keeps using that link and never
        reaches here -- which is also what makes those meetings usable as
        ground truth for the matcher, since the city's own answer is
        known.

        Every uncertain path returns None, landing back on the honest "No
        video link found on this Legistar page." this has always shown.
        """
        page_info = LegistarAssetFinder._extract_page_meeting_info(soup, page_url)
        if not page_info:
            return None
        netloc = urlparse(page_url).netloc
        if not youtube_channel.has_channel_fallback(netloc):
            return None
        match = await youtube_channel.find_channel_match(
            netloc, page_info["title"], page_info["date"]
        )
        if not match:
            return None

        resolved = await YouTubeAssetFinder.resolve_video_id(
            match.video_id, source_url=source_url
        )
        if not youtube_channel.video_date_is_plausible(
            page_info["date"], resolved.date
        ):
            return None

        # Legistar's own page wins outright on all four fields, not just
        # as a fallback for an empty one -- the same posture (and the same
        # real reason) as `_try_fallback_video_link()` above: a YouTube
        # `uploader` is a channel name ("CharmTV Citizens' Hub"), not a
        # jurisdiction, and a YouTube date is the *upload* date, which is
        # confirmed to run up to a week after the meeting on real
        # Philadelphia uploads. Here the page is authoritative for the
        # date too, unlike that method's `resolved.date or ...`.
        resolved.title = page_info["title"]
        resolved.jurisdiction = page_info["jurisdiction"] or resolved.jurisdiction
        resolved.date = page_info["date"]
        resolved.agenda_link = resolved.agenda_link or page_info.get("agenda_link")

        # Provenance, said plainly and up front. Deliberately NOT
        # `best_effort=True`: that flag means "this government website
        # isn't supported yet, so we're going to try our best" in the
        # frontend's own copy (player.js), which would be a false
        # statement here -- Legistar is fully supported, and this page
        # parsed cleanly; it's specifically the *video* that came from
        # somewhere else. Setting it would also mis-route
        # `_unreadable_media_message()` in main.py into claiming the
        # visitor's Legistar URL is "hosted on YouTube". A video_warning
        # is the honest, correctly-scoped signal, and renders right next
        # to the player where the claim actually applies.
        resolved.video_warnings.insert(
            0,
            "This meeting page has no video on it. We matched this recording from "
            f"{match.channel_name}'s own YouTube channel by meeting name and date "
            f'("{match.video_title}") — it is not linked from the meeting page '
            "itself, so double-check it is the meeting you expected.",
        )
        return resolved

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
        async with session.get(
            url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
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
            # Real bug fixed 2026-08-12, confirmed live on Charlotte, NC:
            # some Legistar instances render three separate a.videolink
            # anchors per real video -- Mode2=Video, Mode2=Audio, and
            # Mode2=AudioDownload -- all three sharing the same "Video.aspx"
            # substring the check above requires, so a single real meeting
            # was miscounted as multiple video links and misclassified as a
            # calendar page (CalendarPageError below). Maricopa's rows only
            # ever emit the Mode2=Video anchor, which is why this wasn't
            # caught by the original confirmed-against-Maricopa testing --
            # only Mode2=Video is a real distinct video worth a candidate.
            if "Mode2=Audio" in match.group(1):
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
    def _extract_page_meeting_info(
        soup: BeautifulSoup, page_url: str
    ) -> Optional[dict]:
        text = soup.title.get_text(" ", strip=True) if soup.title else None
        if not text or not _PAGE_TITLE_RE.match(text):
            # Real gap confirmed live 2026-08-10: Baltimore's Legistar
            # instance leaves <title> completely empty, unlike NYC's --
            # but the identical "{jurisdiction} - Meeting of {body} on
            # {date} at {time}" text is still present in the page's own
            # RSS <link> tag, a standard Legistar template element
            # (confirmed present regardless of whether <title> itself is
            # populated), not something NYC-specific.
            rss_link = soup.select_one(
                'link[rel="alternate"][type="application/rss+xml"]'
            )
            if rss_link and rss_link.get("title"):
                text = rss_link["title"]
        if not text:
            return None
        match = _PAGE_TITLE_RE.match(text)
        if not match:
            return None
        jurisdiction = match.group(1).strip()
        if jurisdiction.lower().startswith("the "):
            jurisdiction = jurisdiction[4:]
        # Real shape confirmed live: this capture is sometimes a clean
        # "City of X" (Baltimore), sometimes a body-inclusive "X City
        # Council" (NYC) -- enrich_jurisdiction_text() safely no-ops
        # (returns unchanged) rather than mismatching when the text
        # doesn't resemble a real place/county name, so it's always safe
        # to try regardless of which shape this page happened to produce.
        jurisdiction = jurisdiction_enrich.enrich_jurisdiction_text(
            jurisdiction, netloc=urlparse(page_url).netloc, page_text=text
        )
        month, day, year = int(match.group(3)), int(match.group(4)), match.group(5)
        return {
            "title": match.group(2).strip(),
            "jurisdiction": jurisdiction,
            "date": f"{year}-{month:02d}-{day:02d}",
            "agenda_link": LegistarAssetFinder._extract_agenda_link(soup, page_url),
        }

    @staticmethod
    def _extract_agenda_link(soup: BeautifulSoup, page_url: str) -> Optional[str]:
        """A direct link to the real agenda document, sitting right in
        MeetingDetail.aspx's own "Meeting Details" table -- real, easy win
        confirmed live 2026-08-12 on a real Mesa, AZ meeting
        (mesa.legistar.com), re-confirmed live 2026-08-13: `<a
        id="ctl00_ContentPlaceHolder1_hypAgenda" href="View.ashx?M=A&...">
        Agenda</a>`. Matched by ID suffix (not the full
        `ctl00_ContentPlaceHolder1_` prefix) since that prefix is an
        ASP.NET WebForms naming-container artifact that could in
        principle differ under a different master-page nesting on another
        customer's instance -- unconfirmed either way, but a suffix match
        costs nothing and is strictly safer. Absent entirely on a page
        with no published agenda yet (a real, non-error state, not
        checked further)."""
        link = soup.find("a", id=lambda x: x and x.endswith("hypAgenda"))
        if not link or not link.get("href"):
            return None
        return urljoin(page_url, link["href"])

    @staticmethod
    def _looks_like_raw_filename(title: Optional[str]) -> bool:
        return bool(title) and bool(_RAW_FILENAME_RE.search(title))

    @staticmethod
    def _parse_date(text: str) -> Optional[str]:
        try:
            return datetime.strptime(text.strip(), "%m/%d/%Y").strftime("%Y-%m-%d")
        except ValueError:
            return None
