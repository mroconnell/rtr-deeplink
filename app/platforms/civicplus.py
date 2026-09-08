from datetime import datetime
from typing import List, Optional
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import (
    AssetFinder,
    CalendarPageError,
    NoVideoCandidateFound,
    detect_platform,
    resolve_via_platform,
)
from .granicus import US_STATE_ABBREVIATIONS
from .models import ResolvedMeeting
from .youtube import YouTubeAssetFinder
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

    That original sample site has since gone DNS-dead (see
    `tests/fixtures/civicplus/README.md`), which for a while left this
    adapter with no live-verified sample at all --
    `scripts/adapter_canary.py` excluded civicplus as a result. Re-verified
    on a fresh real site 2026-08-30: nc-durham.civicplus.com/AgendaCenter/
    City-Council-4, 31 `tr.catAgendaRow` rows, 22 with real video links in
    `td.media` (21 Granicus + 1 YouTube) -- the exact same structure
    described above, confirmed independently on a second live tenant, not
    just carried forward from the first. One link spot-checked live:
    `durham.granicus.com/player/clip/3313`. See
    `tests/fixtures/civicplus/durham_agendacenter_citycouncil.html` (a
    real, raw-saved page) and its matching test in `tests/test_civicplus.py`.

    CivicPlus doesn't appear to have a "single meeting" URL shape the way
    Legistar's MeetingDetail.aspx does -- every AgendaCenter URL observed
    is a category listing with multiple dated rows. So: exactly 1 real
    video-bearing row -> resolve it directly; more than 1 -> CalendarPageError
    with a pick-list, same UX as Legistar's calendar case.

    Real bug fixed 2026-09-07: the old `_find_video_rows()` dropped every
    row without a real video link before `resolve()` ever saw it, so "0
    candidates" conflated two very different real cases -- "this page has
    no meetings at all" (e.g. City of Azle, TX) and "this page has real
    meetings, just none with video yet" (e.g. City of Brownfield, TX) --
    and the zero-candidates branch fabricated a `ResolvedMeeting` keyed to
    the bare AgendaCenter URL either way, which
    `scripts/adhoc_civicplus_pipeline.py` then ingested as if it were a
    real meeting (garbage pages titled "Agenda Center"/"Meeting" in
    production). `_find_candidate_rows()` now returns every real
    (title+date) row regardless of video, and `resolve()` walks them
    newest-first for a real video link, up to `_RETRY_LIMIT` rows, before
    raising `NoVideoCandidateFound` -- a distinct, typed, non-error signal
    (same shape as `CalendarPageError`, see base.py) instead of ever
    fabricating a candidate.

    Separate real bug fixed 2026-09-07: `resolve()` used to divert to
    `resolve_via_platform(final_url)` for anything whose netloc didn't
    literally contain "civicplus.com" -- but most real CivicPlus tenants
    are white-labeled onto the government's own domain and never touch
    civicplus.com at all (confirmed live: www.trentonnj.org,
    www.cityofazle.org, www.cityoflagunaniguel.org, www.cityofanderson.com,
    www.saginaw-mi.com, www.ci.brownfield.tx.us). For every one of those,
    the old gate assumed "not civicplus.com" meant "must have redirected
    to some other real platform," diverting into `detect_platform()`
    (-> "unknown" for a plain gov domain) -> generic_fallback.py, which
    has no idea what a `tr.catAgendaRow` is -- silently skipping every
    fix above for the majority of real tenants. Since
    `_find_candidate_rows()` only reads the page's own DOM structure, not
    its domain, the gate is now keyed on
    `detect_platform(final_url)` instead: only a genuinely different
    known platform (not "unknown", and not "civicplus" itself --
    otherwise a real *.civicplus.com final_url would recurse into this
    same class forever) is worth deferring to `resolve_via_platform()`
    for. See `scripts/nationwide_395_ingest.py`'s own incident note (now
    resolved) for the same bug caught live in production.
    """

    platform_name = "civicplus"
    # How many of the most recent real (title+date) candidate rows to
    # check for a real video link before giving up -- matches this
    # project's "try several most-recent candidates" precedent
    # (adhoc_cdx_iqm2_pipeline.py's MAX_CANDIDATES, used there because a
    # newer meeting often just hasn't had video posted yet), kept small
    # since -- unlike IQM2 -- every row here already came from the one
    # page fetch already in hand, so this bounds *how far back* a stale
    # video is worth surfacing, not network cost.
    _RETRY_LIMIT = 5

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

        # Real bug, confirmed live 2026-09-07: most real CivicPlus tenants
        # are white-labeled onto the government's OWN domain (e.g.
        # www.trentonnj.org, www.cityofazle.org -- confirmed live, direct
        # fetch, never redirecting to any *.civicplus.com host), so the
        # old "netloc doesn't contain civicplus.com" check treated every
        # one of those as if it must have redirected to some other real
        # platform, diverting to `resolve_via_platform(final_url)` --
        # `detect_platform()` on a plain government domain returns
        # "unknown", which dispatches to generic_fallback.py and never
        # reaches this class's own (real, domain-agnostic) row-parsing at
        # all. `_find_candidate_rows()` only cares about the page's own
        # `tr.catAgendaRow` markup (confirmed live on trentonnj.org, which
        # carries the identical structure) -- it doesn't care what domain
        # served the HTML, so there's no reason to gate on the domain
        # either. Deferring is only actually correct when the final URL
        # really did land on a DIFFERENT real platform's own page (e.g. an
        # AgendaCenter link that 301-redirects straight to a Granicus/
        # Legistar URL, bypassing CivicPlus's HTML entirely) --
        # `detect_platform(final_url)` returning anything other than
        # "unknown" is exactly that signal. "civicplus" itself is excluded
        # from that set too, since it's also what a genuine
        # *.civicplus.com final_url detects as -- deferring on that would
        # call `resolve_via_platform()` -> `get_finder("civicplus")` ->
        # this same class's own `resolve()` on the same URL, recursing
        # without bound.
        final_platform = detect_platform(final_url)
        if final_platform not in ("unknown", "civicplus"):
            result = await resolve_via_platform(final_url)
            if subdomain_jurisdiction:
                result.jurisdiction = subdomain_jurisdiction
            return result

        soup = BeautifulSoup(html, "html.parser")
        all_candidates = self._find_candidate_rows(soup, final_url)

        # Walk the real (title+date) candidates newest-first -- same
        # rendering order this page already uses, per the class docstring
        # -- checking up to `_RETRY_LIMIT` of them for a real video link.
        # This is the "retry" for a newer meeting that just hasn't had
        # video posted yet (same idea as adhoc_cdx_iqm2_pipeline.py trying
        # several of the most recent meeting ids): stop as soon as ANY
        # checked row has real video, since that's confirmation this page
        # does carry video and the full, unbounded video-bearing set
        # (computed below, exactly as before) is what actually matters for
        # the single-vs-multiple-candidate decision -- older rows further
        # down the page than `_RETRY_LIMIT` are never worth walking to
        # JUST to confirm presence.
        candidates_checked = 0
        found_video = False
        for candidate in all_candidates[: self._RETRY_LIMIT]:
            candidates_checked += 1
            if candidate["url"]:
                found_video = True
                break

        if not found_video:
            # Confirmed real, 2026-09-07: this is NOT the same as "no
            # candidates at all" (a genuinely empty listing page, e.g.
            # City of Azle, TX -- candidates_checked is 0 there) -- it also
            # covers real meetings with no video posted yet (e.g. City of
            # Brownfield, TX). Either way, CivicPlus is never the video
            # host itself (see module docstring), so there is no
            # `ResolvedMeeting` to fabricate here -- a typed, non-error
            # negative signal is the honest result.
            raise NoVideoCandidateFound(
                message=(
                    f"Checked {candidates_checked} of the most recent listing(s) "
                    "on this CivicPlus page and found no real video link."
                ),
                candidates_checked=candidates_checked,
                jurisdiction_hint=subdomain_jurisdiction,
            )

        video_candidates = [c for c in all_candidates if c["url"]]

        if len(video_candidates) > 1:
            raise CalendarPageError(
                message=(
                    "This looks like an agenda listing page with multiple meetings, "
                    "not a link to one specific meeting."
                ),
                candidates=video_candidates,
                jurisdiction_hint=subdomain_jurisdiction,
            )

        result = await resolve_via_platform(video_candidates[0]["url"])
        if subdomain_jurisdiction:
            result.jurisdiction = subdomain_jurisdiction
        # agenda_link/packet_link come from this row's OWN td.downloads,
        # not from whatever resolve_via_platform() found on the delegated
        # video platform's page -- Granicus/YouTube know nothing about
        # CivicPlus's own agenda documents. Truthy-gated the same way
        # legistar.py's delegation already threads its own agenda_link
        # through, in case a future resolve_via_platform() target ever
        # sets one of its own.
        result.agenda_link = result.agenda_link or video_candidates[0].get("agenda_link")
        result.packet_link = result.packet_link or video_candidates[0].get("packet_link")
        # Same fallback legistar.py's own `page_info["title"]` already
        # provides for the identical class of gap (see that module's
        # `resolve()`): a delegated platform's own title/date extraction
        # can come back empty (confirmed live 2026-09-07, via
        # scripts/nationwide_395_ingest.py's own smoke test: 6 CivicPlus
        # rows delegated to a YouTube video whose title came back None,
        # yt-dlp blocked by anti-bot on this host -- every one confirmed a
        # real meeting only after the fact, by re-fetching the AgendaCenter
        # page directly) even though this row's own title/date -- real,
        # structured data straight from the AgendaCenter listing, not a
        # guess -- was already sitting right here. Newly load-bearing now
        # that the domain-gate fix above means this path is reached by
        # most real (self-hosted) CivicPlus tenants, not routed around it.
        result.title = result.title or video_candidates[0]["title"]
        result.date = result.date or video_candidates[0]["date"]
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

    def _find_candidate_rows(self, soup: BeautifulSoup, page_url: str) -> List[dict]:
        """Every REAL `tr.catAgendaRow` on this AgendaCenter listing page --
        a real title and a real date required, a real video link
        optional -- in the page's own newest-first DOM order (per the
        class docstring). `url` is the real delegate-video link
        (validated by `_is_real_video_link()`, unchanged) when this row
        has one, or None otherwise -- callers decide what "no video"
        means for a given row, this only reports what's actually on the
        page.

        Generalized 2026-09-07 from the old `_find_video_rows()`, which
        silently dropped every row without a real video link before ever
        returning it -- collapsing "no meetings at all" and "real
        meetings, just no video yet" into the same empty result (see the
        class docstring for the real production bug this caused). A row
        with no title link or no parseable date isn't a real candidate
        either way (nothing to show a human or a report), so it's still
        excluded here regardless of video.
        """
        candidates = []
        for row in soup.find_all("tr", class_="catAgendaRow"):
            first_td = row.find("td")
            title_link = (
                first_td.find("p").find("a")
                if first_td and first_td.find("p")
                else None
            )
            title = title_link.get_text(strip=True) if title_link else ""

            strong = row.find("h3").find("strong") if row.find("h3") else None
            raw_date = strong.get_text(" ", strip=True) if strong else ""
            date = (self._parse_date(raw_date) or raw_date) if raw_date else ""

            if not title or not date:
                continue

            video_url = None
            media_cell = row.find("td", class_="media")
            if media_cell:
                video_link = next(
                    (
                        a
                        for a in media_cell.find_all("a", href=True)
                        if self._is_real_video_link(a["href"])
                    ),
                    None,
                )
                if video_link:
                    video_url = urljoin(page_url, video_link["href"])

            agenda_link, packet_link = self._extract_agenda_and_packet_links(
                row, page_url
            )
            candidates.append(
                {
                    "title": title,
                    "date": date,
                    "url": video_url,
                    "agenda_link": agenda_link,
                    "packet_link": packet_link,
                }
            )
        return candidates

    @staticmethod
    def _is_real_video_link(href: str) -> bool:
        """`detect_platform() != "unknown"` alone isn't tight enough for a
        `td.media` link: a YouTube-domain link passes it even when it's a
        channel/playlist/`@handle`/`/user/` page, not a specific single
        meeting video -- `resolve_via_platform()` only finds out later, via
        `YouTubeAssetFinder` raising `ValueError('Could not find a YouTube
        video ID in ...')`, which used to kill the whole pick even when
        other real candidates existed on the same page.

        Real, confirmed at scale, not just South Fulton GA's single
        `/channel/...` instance noted in `rtr-business/research/
        CIVICPLUS_FIRST_RUN.md`: a 2026-08-31 DNS enumeration dry run
        against 1,118 fresh CivicPlus tenants found 28 real jurisdictions
        where picking the newest multi-candidate row failed with exactly
        this error -- every one YouTube-shaped (`playlist?list=`,
        `/channel/UC...`, `@handle`, `/user/...`). ks-desoto.civicplus.com
        is the starkest real case: all 12 of its `td.media` YouTube links
        are `/user/DeSotoKansas/live.` or `@DeSotoKansas` -- zero real
        single-video links on the whole page (see
        `tests/fixtures/civicplus/ks_desoto_agendacenter.html`, a real,
        raw-saved page, and `test_real_desoto_listing_page_finds_zero_
        video_candidates` in `tests/test_civicplus.py`).

        Reuses `YouTubeAssetFinder.extract_video_id()` (the same tighter,
        video-ID-validated check `generic_fallback.py` and `legistar.py`
        already use for this identical class of false positive -- see
        `find_platform_link()`'s own docstring in `base.py`) rather than
        writing a second, possibly-inconsistent regex here. A non-YouTube
        link that already passed `detect_platform()` is trusted as-is --
        this gap is specific to YouTube being a general-purpose host with
        non-video URL shapes on the same domain, not a property every
        platform shares.
        """
        platform = detect_platform(href)
        if platform == "unknown":
            return False
        if platform == "youtube":
            return YouTubeAssetFinder.extract_video_id(href) is not None
        return True

    @staticmethod
    def _extract_agenda_and_packet_links(
        row, page_url: str
    ) -> tuple[Optional[str], Optional[str]]:
        """A `td.downloads` cell offers the same agenda in up to three
        non-interchangeable renditions -- confirmed live on
        nc-durham.civicplus.com, 2026-08-31 (`tests/fixtures/civicplus/
        durham_agendacenter_citycouncil.html`): `?html=true` (an HTML
        rendition of the plain agenda), a bare PDF link with no query
        string (the same plain agenda as a PDF), and `?packet=true` (the
        agenda plus every staff report -- a much larger, different
        document). Distinguished by the href's own query string, not the
        `a.pdf`/`a.html` class alone, since two different links both
        carry `class="pdf"`.

        Prefers the HTML rendition for `agenda_link` when present (same
        size, no PDF-plugin dependency for the inline viewer) with the
        bare-PDF link as fallback; `packet_link` is a separate field
        entirely, never conflated with the plain agenda -- a packet can
        run into the tens of megabytes and is not a drop-in replacement.
        Returns (None, None) for a row with no downloads cell at all
        (confirmed real: minutes-only rows, not every row has one).
        """
        downloads_cell = row.find("td", class_="downloads")
        if not downloads_cell:
            return None, None
        html_link = None
        pdf_link = None
        packet_link = None
        for a in downloads_cell.find_all("a", href=True):
            href = a["href"]
            if "packet=true" in href:
                packet_link = urljoin(page_url, href)
            elif "html=true" in href:
                html_link = urljoin(page_url, href)
            else:
                pdf_link = urljoin(page_url, href)
        return html_link or pdf_link, packet_link

    @staticmethod
    def _parse_date(text: str) -> Optional[str]:
        for fmt in ("%b %d, %Y", "%B %d, %Y"):
            try:
                return datetime.strptime(text.strip(), fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None
