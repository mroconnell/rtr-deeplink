import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional
from urllib.parse import parse_qs, urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder, detect_platform, get_finder
from .models import ResolvedMeeting
from .youtube import YouTubeAssetFinder
from ..utils import jurisdiction_enrich

logger = logging.getLogger("rtr_deeplink.primegov")

_VIDEO_URL_VAR_RE = re.compile(r'var\s+videoUrl\s*=\s*"([A-Za-z0-9_-]{11})"')

# Real, confirmed-live gap (2026-08-19): not every PrimeGov tenant's real
# video is a YouTube embed -- some (e.g. cambridgema, baycountyfl,
# calabasas) actually host on Swagit or Granicus instead, and the page
# itself never surfaces that (no `var videoUrl = "..."` at all, since that
# variable is only ever populated for the YouTube-embed case). But
# PrimeGov's own per-tenant JSON API *does* know the real location:
#   GET https://{tenant}.primegov.com/api/v2/PublicPortal/ListArchivedMeetings?year={YYYY}
# returns every archived meeting for that year, and a meeting whose
# `documentList[].templateId` matches this page's own `meetingTemplateId`
# query-string value carries a top-level `videoUrl` field with the real
# swagit.com/granicus.com URL when one exists (confirmed live against all
# three examples above, and cross-checked against
# ~/Documents/rtr-business/research/primegov_swagit_granicus_undetected.txt,
# 53 real meetings sourced this same way). `GetArchivedMeetingYears` lists
# every year the tenant has archives for, but querying all of them per
# resolve would be wasteful -- almost every real case needs only the
# current year, so this tries (in order) the year parsed from the page's
# own header text via `_extract_date`, then the current calendar year,
# then the year before, stopping at the first year whose archive actually
# contains this meetingTemplateId. A meeting older than that is a real,
# unaddressed gap -- see BACKLOG.md.

# The PrimeGov page's own agenda header ("FORMAL AGENDA / CITY COUNCIL /
# August 4, 2026", "REGULAR MEETING / Tuesday, July 07, 2026") -- confirmed
# live (OKC meetingTemplateId=68482, Thousand Oaks meetingTemplateId=9446)
# to give the *correct* meeting date in both raw static HTML (no headless
# browser needed) and to be the first full-month-name date in the page's
# visible text. This replaces YouTube's own upload_date/uploader, which are
# both unreliable here: confirmed live, both samples were uploaded to
# YouTube the day *after* the meeting (upload_date off by one), and
# Thousand Oaks's uploader channel name ("CTO Meetings") carries no
# identifiable city name at all. A prior fix attempt used an embedded
# sub-document's own <title> tag instead and was reverted after it picked
# up an unrelated "Closed Session" sub-document's date for Thousand Oaks --
# this is a different, more prominent signal, not a retry of that one.
_MONTH_DATE_RE = re.compile(
    r"(?:(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?\s+)?"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2}),?\s+(\d{4})"
)
_MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]

# Bounded by an HTML tag or punctuation so this doesn't run away mid-sentence
# on pages that phrase it in flowing prose (confirmed live: Thousand Oaks's
# "It is the mission of the City of Thousand Oaks that all employees...").
# The capitalized-word cap in _extract_jurisdiction() below is the second
# line of defense for the same problem when no tag/punctuation follows
# closely (confirmed live: OKC's header has no punctuation between adjacent
# table-cell headings once tags are stripped, e.g. "OKLAHOMA CITY FORMAL
# AGENDA CITY COUNCIL" would otherwise merge into one match).
_JURISDICTION_RE = re.compile(
    r"\b(city|county|town) of\s+([^<>]{1,80}?)(?=<|[,.])", re.IGNORECASE
)

# Reported by the user with two real examples on slc.primegov.com:
# _JURISDICTION_RE's plain, unscoped .search() over the entire page HTML
# let a "City/Town of X" phrase anywhere in the agenda BODY (e.g. "Central
# Wasatch Commission... City of Holladay") win over the page's real
# header, since it just matches the first occurrence anywhere.
#
# A same-day fix capped the search to the first ~2000 characters after
# stripping <script>/<style> blocks, on the theory that the real header
# always appears "early" and body text always appears "later." **Real
# character offsets from all three known real examples, fetched live
# 2026-08-12 to actually check that theory rather than trust the earlier
# synthetic test that seemed to confirm it, proved it wrong**: OKC's real
# header sits at offset ~4,753 (already past a 2,000-char window);
# Thousand Oaks's only real match is a "City of Thousand Oaks" mention
# buried in mission-statement prose at offset ~264,423, nowhere near the
# top at all; SLC's false-positive Holladay match sits at ~374,844 --
# *farther* into the page than Thousand Oaks's real one, so no window
# size can separate "real match" from "false positive" by position alone
# without either missing Thousand Oaks or capturing SLC's false
# positive (a window between ~265k-374k would happen to thread this
# specific needle, but that's tuned to three examples, not a real rule).
# Confirmed directly: re-running the *original* unscoped search against
# all three real pages finds OKC's and Thousand Oaks's real matches
# correctly (both are genuinely the first "X of Y"-shaped match on their
# respective pages) and only gets SLC wrong -- i.e. the windowed "fix"
# traded two correct, originally-confirmed real cities for one, a net
# regression. Reverted back to an unscoped search (still boilerplate-
# stripped, harmless) until a real, non-positional way to tell a genuine
# header from an agenda-item mention is found and verified against more
# than three examples -- see BACKLOG.md.
_BOILERPLATE_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL
)

# A 4th real false-positive case, confirmed live 2026-08-18/21:
# bedfordoh.primegov.com/Portal/Meeting?meetingTemplateId=518 resolves
# `jurisdiction` as "County of Cuyahoga, OH" instead of "City of Bedford,
# OH". Root cause, fetched and checked directly: the page's letterhead is
# a small header table with "Bedford City Council" and "County of
# Cuyahoga" in adjacent rows of the SAME 3-column table (identical
# styling -- confirmed via the real raw HTML, both `<td>` cells share the
# same `color:#999999; font-weight:bold; font-family:Times New Roman`
# span). _JURISDICTION_RE only ever matches the literal "(city|county|
# town) of ..." shape, so "Bedford City Council" (no "of") never matches
# while "County of Cuyahoga" does, and wins via unscoped first-match --
# same root cause as the OKC/Thousand Oaks/SLC false positives, but here
# (unlike those) the false positive is ALSO a genuine letterhead mention,
# just the wrong entity within it (the parent county, not the specific
# city), so no position-based or "prefer the header" heuristic would have
# separated them.
#
# This regex targets that bare "{Name} City/Town/Village Council" header
# shape specifically, tried BEFORE _JURISDICTION_RE (see
# `_extract_jurisdiction()` below) so the meeting's own governing body
# wins over an adjacent parent-jurisdiction mention. Scoped narrowly, per
# the explicit lesson the 3 earlier incidents already taught (an unscoped
# body-text search recreates this exact bug in a new shape): the
# `[A-Za-z.'-]`/`[ \t]` character classes never cross a `<`/`>` tag
# boundary or a newline, so a match only fires when the name and "City/
# Town/Village Council" sit in ONE unbroken run of text -- confirmed this
# does NOT match OKC's "CITY COUNCIL" (its own separate `<td>`, no name in
# the same cell) or Thousand Oaks's bare "City Council" (no name precedes
# it at all), via both real fixtures in tests/test_primegov.py. A match is
# also required to validate against the real Census places/counties table
# before `_extract_jurisdiction()` accepts it (see
# `_extract_council_header_jurisdiction()` below) -- a stray body-prose
# mention ("addressed the Springfield City Council last month") is
# discarded unless "Springfield" itself is real, so this can't silently
# store confident garbage the way an unvalidated regex could.
_COUNCIL_HEADER_RE = re.compile(
    r"\b([A-Z][A-Za-z.'-]{1,30}(?:[ \t]+[A-Z][A-Za-z.'-]{1,30}){0,2})"
    r"[ \t]+(City|Town|Village)[ \t]+Council\b"
)


@dataclass
class _TenantMeetingLookup:
    """Result of one `_fetch_tenant_video_url()` call -- see that
    method's own docstring for what each field means."""

    matched: bool
    video_url: Optional[str] = None
    has_video_icon: bool = False
    title: Optional[str] = None
    date: Optional[str] = None


class PrimeGovAssetFinder(AssetFinder):
    """PrimeGov doesn't host video itself -- confirmed live (LA City's
    portal, lacity.primegov.com) that meeting pages embed a YouTube video
    via the IFrame Player API, with the video id set server-side as a
    plain JS variable: `var videoUrl = "{11-char-YouTube-id}";`, right
    next to a `youtube.com/iframe_api` script tag. Delegates to
    YouTubeAssetFinder once that id is extracted -- same "wrapper
    platform" pattern as Legistar/CivicPlus delegating to Granicus.

    Confirmed the video id is only present on meeting pages that actually
    have a recording (`Portal/Meeting?compiledMeetingDocumentFileId=...`
    URLs, the shape a real shared/indexed meeting link uses) -- an
    agenda-only page reached via `Portal/Meeting?meetingTemplateId=...`
    may have no matching videoUrl at all.

    Unlike Legistar/CivicPlus's delegation (where the final
    ResolvedMeeting.source_url ends up being the delegated platform's
    URL, not what the user pasted -- a known quirk, see BACKLOG.md), this
    calls YouTubeAssetFinder.resolve_video_id() directly with the
    original PrimeGov URL as source_url, so "View original source" keeps
    pointing back to the actual PrimeGov meeting page.

    Not every PrimeGov tenant's real video is a YouTube embed, though --
    see the module-level comment above `_VIDEO_URL_VAR_RE`'s sibling
    constants for the confirmed-live gap this class also covers: when no
    YouTube id is on the page, `resolve()` falls back to checking the
    tenant's own ListArchivedMeetings API for a real Swagit/Granicus
    videoUrl before giving up. Same source_url-preserving pattern as the
    YouTube case -- the delegated finder's own `resolve()` is called
    directly (not via `resolve_via_platform()`, which would leave
    source_url pointing at swagit.com/granicus.com instead).
    """

    platform_name = "primegov"

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
                html = await response.text()

        video_id = self._extract_video_id(html)
        if not video_id:
            # No YouTube embed on the page -- checked first since it's
            # free (already-fetched HTML, no extra request). Before
            # concluding there's really no video, check whether this
            # tenant's own API says otherwise (see the module-level
            # comment on the real, confirmed gap this covers).
            delegated = await self._resolve_via_tenant_video_url(html, url)
            if delegated:
                return delegated
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=["No video found on this PrimeGov page."],
            )

        resolved = await YouTubeAssetFinder.resolve_video_id(video_id, source_url=url)

        # Only fires when YouTube's own title extraction came back empty
        # (yt-dlp blocked from Render's IP, the documented gap this whole
        # module's docstring already covers) -- a real title from YouTube
        # is never overridden. Real gap found live 2026-08-13 on a real
        # LA City Council meeting: with yt-dlp blocked, this page used to
        # come through with no title at all even though the page has a
        # perfectly good one sitting right there.
        if not resolved.title:
            resolved.title = self._extract_title(html)

        # Prefer the PrimeGov page's own date/jurisdiction over whatever
        # YouTube's resolve_video_id already set -- see the module-level
        # comment on _MONTH_DATE_RE for why those are unreliable here. Only
        # override when a real match is found; otherwise leave YouTube's
        # (possibly wrong, but better-than-nothing) values in place.
        page_date = self._extract_date(html)
        if page_date:
            resolved.date = page_date
        # Unconditional, not "only override if truthy" -- YouTube's own
        # `uploader` (a channel name, e.g. "SLC Live Meetings") is not a
        # jurisdiction, so it must never be left in place just because
        # this page's own extraction found nothing. Real bug fixed
        # 2026-08-12: a page whose header doesn't happen to contain a
        # "City/County/Town of X" phrase now correctly comes through with
        # no jurisdiction at all, rather than a wrong-looking channel name.
        #
        # A known-domain full override (e.g. slc.primegov.com) always wins
        # over `_extract_jurisdiction()`'s own page-text search -- see
        # `jurisdiction_enrich.known_jurisdiction_display()`'s docstring
        # for why: on this specific domain, that search is confirmed to
        # sometimes pick up an unrelated city mentioned in agenda body
        # text (BACKLOG.md's open PrimeGov jurisdiction-extraction entry),
        # so the domain itself is the more trustworthy signal here, not
        # just a fallback for when the text search finds nothing.
        resolved.jurisdiction = jurisdiction_enrich.known_jurisdiction_display(
            urlparse(url).netloc
        ) or self._extract_jurisdiction(html, url)

        return resolved

    @staticmethod
    def _extract_video_id(html: str) -> Optional[str]:
        match = _VIDEO_URL_VAR_RE.search(html)
        return match.group(1) if match else None

    async def _resolve_via_tenant_video_url(
        self, html: str, url: str
    ) -> Optional[ResolvedMeeting]:
        """Checks this tenant's own ListArchivedMeetings API for a real
        Swagit/Granicus video when the page itself has no YouTube embed --
        see the module-level comment for the confirmed-live gap and API
        shape this covers. Returns None (not an error) whenever there's
        nothing to delegate to, so the caller can fall through to its own
        honest "no video found" response.
        """
        meeting_template_id = self._extract_meeting_template_id(url)
        if not meeting_template_id:
            return None

        netloc = urlparse(url).netloc
        tried_years = self._candidate_years(self._extract_date(html))
        lookup = _TenantMeetingLookup(matched=False)
        async with aiohttp.ClientSession(headers=self.headers) as session:
            for year in tried_years:
                lookup = await self._fetch_tenant_video_url(
                    session, netloc, meeting_template_id, year
                )
                if lookup.matched:
                    # A real meeting matching this URL's meetingTemplateId
                    # was found in this year's archive -- stop here even
                    # if it turns out to have no video (an honest
                    # agenda-only meeting), rather than risk a same-id
                    # collision by continuing to search other years.
                    break

            if not lookup.matched:
                # None of the likely-recent years matched at all (not
                # "matched with no video" -- genuinely never found this
                # meetingTemplateId) -- confirmed live 2026-08-19 on two
                # real older meetings (liveoakcity, sanjoseca, both from
                # Jan 2024) that the current/current-1-year guess above
                # misses. Fall back to the tenant's own full year list
                # (GetArchivedMeetingYears) and try whatever wasn't
                # already covered -- costs extra requests, but only ever
                # in this already-slow "not found yet" path, not the
                # common case.
                for year in await self._fetch_archived_years(session, netloc):
                    if year in tried_years:
                        continue
                    lookup = await self._fetch_tenant_video_url(
                        session, netloc, meeting_template_id, year
                    )
                    if lookup.matched:
                        break
        if not lookup.video_url:
            if lookup.has_video_icon:
                # Real gap found 2026-08-28 (BACKLOG.md's Midpen Media
                # Center entry): `isShowVideoIcon` is this tenant's own
                # confirmation that a recording genuinely exists for this
                # meeting, even when videoUrl itself is blank -- seen live
                # on Palo Alto meetings whose real video sits on
                # midpenmedia.org, a host this API's videoUrl field never
                # names and no adapter here resolves yet. Surfacing this
                # distinguishes "PrimeGov says there's no recording" from
                # "there is one, we just can't find where" -- the caller
                # (resolve()) uses this instead of its generic fallback
                # warning.
                return ResolvedMeeting(
                    platform=self.platform_name,
                    source_url=url,
                    video_warnings=[
                        "This meeting's own listing shows it has a recording, "
                        "but we could not find a playable link for it."
                    ],
                )
            return None

        # video_url is sometimes protocol-relative ("//brookhavenga.
        # granicus.com/MediaPlayer.php?clip_id=76" -- confirmed live) --
        # urljoin against the original https:// PrimeGov page URL
        # resolves that the same way a browser would.
        normalized_url = urljoin(url, lookup.video_url)
        platform = detect_platform(normalized_url)
        if platform not in ("swagit", "granicus"):
            # Confirmed live videoUrl values are always swagit.com or
            # granicus.com -- an unrecognized shape here means either a
            # third real host not seen yet or a malformed value, and
            # either way there's no adapter to safely hand it to.
            return None

        # A Swagit `/events/{id}` URL -- the shape PrimeGov's own API
        # returns for some tenants, as opposed to the `/videos/{id}` shape
        # SwagitAssetFinder was originally built and tested against -- used
        # to make this delegation silently hand back a specific WRONG video
        # (a bogus "abilenetx" demo placeholder byte-identical across every
        # real tenant checked, confirmed live via direct `curl` against
        # petalumaca/norwalkca/westjordan) with no warning at all: a real,
        # confirmed-live SwagitAssetFinder bug found 2026-08-19 while
        # building this delegation, previously worked around here with an
        # early decline (`return None`, same as this method's other honest
        # "nothing found" cases) rather than risk shipping it. Root-caused
        # and fixed at the source 2026-08-21 (see swagit.py's
        # `_is_swagit_events_template_dead_candidate` and BACKLOG_DONE.md):
        # `/events/{id}` is Swagit's own live-event page template, not an
        # archived on-demand recording, and SwagitAssetFinder now detects
        # and declines both of its non-viable candidates (the dead
        # placeholder and the tenant's real but always-404-once-the-
        # meeting's-over live-channel stream) with a specific warning
        # instead of guessing. Delegating unconditionally is now safe --
        # the guard that used to live here is no longer needed, since the
        # fix lives in the finder actually doing the parsing rather than
        # in every caller that might reach it (generic_fallback.py's page
        # scan and a future new delegation path both had the same exposure
        # this guard never protected).
        resolved = await get_finder(platform).resolve(normalized_url)
        # Same source_url-preserving choice as the YouTube delegation
        # above -- "View original source" should keep pointing at the
        # PrimeGov page the user actually pasted, not the Swagit/Granicus
        # URL discovered behind the scenes. Deliberately does NOT also
        # apply this class's own title/date/jurisdiction overrides below
        # (those exist specifically because YouTube's metadata is known
        # unreliable here) -- Swagit/Granicus's own resolve() already
        # extracts real title/date/jurisdiction from their own pages, a
        # better source than PrimeGov's own header-scraping fallback.
        resolved.source_url = url
        # Backfill ONLY -- never overrides a real value Swagit/Granicus's
        # own resolve() already found (see the comment above this one).
        # Real gap this closes (2026-08-21, see BACKLOG_DONE.md's
        # MediaPlayer.php `event_id` writeup): a Granicus `event_id`-
        # shaped page (a scheduled-but-not-yet-archived meeting slot, a
        # separate id namespace from a real `clip_id`) has no date-shaped
        # text anywhere on it, so `GranicusAssetFinder` correctly returns
        # title=None/date=None for it -- but this tenant's own already-
        # fetched API record (`lookup`, above) usually has both. Confirmed
        # live on Calabasas `event_id=1525`: PrimeGov's API gives "City
        # Council Regular Meeting - Closed Session (Amended Agenda)"/
        # "Jan 28, 2026" where the delegated Granicus page has neither.
        if not resolved.title and lookup.title:
            resolved.title = lookup.title
        if not resolved.date and lookup.date:
            parsed_date = self._parse_api_date(lookup.date)
            if parsed_date:
                resolved.date = parsed_date
        return resolved

    @staticmethod
    def _parse_api_date(raw: str) -> Optional[str]:
        """PrimeGov's ListArchivedMeetings API's own `date` field -- real
        confirmed shape `"Jan 12, 2026"` (abbreviated month, comma) --
        parsed to this app's own `YYYY-MM-DD` convention. Returns None
        (never raises) on anything that doesn't match, same as every
        other best-effort date parse in this file."""
        try:
            return datetime.strptime(raw, "%b %d, %Y").date().isoformat()
        except ValueError:
            return None

    @staticmethod
    def _extract_meeting_template_id(url: str) -> Optional[str]:
        value = parse_qs(urlparse(url).query).get("meetingTemplateId", [None])[0]
        return value if value and value.isdigit() else None

    @staticmethod
    def _candidate_years(page_date: Optional[str]) -> List[int]:
        """Years to try against ListArchivedMeetings, in priority order:
        the year parsed from the page's own header text (most likely
        correct when available), then the current calendar year, then the
        year before -- covers the common case (a recently-archived
        meeting) in one request without querying every year the tenant
        has ever had archives for. See the module-level comment on the
        known limitation this leaves for older meetings.
        """
        years: List[int] = []
        if page_date:
            try:
                years.append(int(page_date[:4]))
            except ValueError:
                pass
        current_year = datetime.now().year
        for year in (current_year, current_year - 1):
            if year not in years:
                years.append(year)
        return years

    @staticmethod
    async def _fetch_archived_years(
        session: aiohttp.ClientSession, netloc: str
    ) -> List[int]:
        """The tenant's own full list of years it has any archive for --
        `GET .../api/v2/PublicPortal/GetArchivedMeetingYears`, confirmed
        live to return a plain descending list (e.g.
        `[2026,2025,2024,...,2015]`). Only called as a last-resort
        fallback (see `_resolve_via_tenant_video_url`) once the
        recent-years guess in `_candidate_years` has already come back
        empty -- not worth the extra request otherwise.
        """
        api_url = f"https://{netloc}/api/v2/PublicPortal/GetArchivedMeetingYears"
        try:
            async with session.get(
                api_url, timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "PrimeGov archived-years fetch got HTTP %s for %s",
                        response.status,
                        api_url,
                    )
                    return []
                years = await response.json(content_type=None)
        except Exception:
            logger.warning(
                "PrimeGov archived-years fetch failed for %s", api_url, exc_info=True
            )
            return []
        if not isinstance(years, list):
            return []
        return [year for year in years if isinstance(year, int)]

    @staticmethod
    async def _fetch_tenant_video_url(
        session: aiohttp.ClientSession,
        netloc: str,
        meeting_template_id: str,
        year: int,
    ) -> "_TenantMeetingLookup":
        """Looks up this URL's meetingTemplateId in one year's worth of
        this tenant's archived meetings -- `matched=True` as soon as a
        meeting whose documentList carries it is found, with `video_url`
        being that meeting's own `videoUrl` field (real confirmed shape:
        "https://{tenant}.new.swagit.com/videos/{id}", "https://{tenant}.
        v3.swagit.com/events/{id}", or a swagit/granicus URL, possibly
        protocol-relative). `video_url` is None (matched still True) for a
        genuine agenda-only meeting with no recording -- `has_video_icon`
        (from the meeting's own real `isShowVideoIcon` field, confirmed
        live 2026-08-28 on Palo Alto) distinguishes that from a meeting
        the tenant itself says has video that videoUrl just doesn't name
        (e.g. hosted on Midpen Media Center -- see BACKLOG.md). `title`/
        `date` are the meeting's own real API fields (confirmed live
        shape: `"date": "Jan 12, 2026"`, abbreviated month) -- used by the
        caller only to backfill a delegated Granicus/Swagit resolve that
        came back with nothing of its own (see `_resolve_via_tenant_
        video_url`'s own comment on the `event_id` sub-case this covers).
        Best-effort like every other adapter's opportunistic API probe
        here -- any failure just means "nothing found," not a raised
        exception.
        """
        api_url = (
            f"https://{netloc}/api/v2/PublicPortal/ListArchivedMeetings?year={year}"
        )
        try:
            async with session.get(
                api_url, timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "PrimeGov archived-meetings fetch got HTTP %s for %s",
                        response.status,
                        api_url,
                    )
                    return _TenantMeetingLookup(matched=False)
                meetings = await response.json(content_type=None)
        except Exception:
            logger.warning(
                "PrimeGov archived-meetings fetch failed for %s",
                api_url,
                exc_info=True,
            )
            return _TenantMeetingLookup(matched=False)

        if not isinstance(meetings, list):
            return _TenantMeetingLookup(matched=False)

        template_id = int(meeting_template_id)
        for meeting in meetings:
            if not isinstance(meeting, dict):
                continue
            for document in meeting.get("documentList") or []:
                if (
                    isinstance(document, dict)
                    and document.get("templateId") == template_id
                ):
                    return _TenantMeetingLookup(
                        matched=True,
                        video_url=meeting.get("videoUrl") or None,
                        has_video_icon=bool(meeting.get("isShowVideoIcon")),
                        title=meeting.get("title") or None,
                        date=meeting.get("date") or None,
                    )
        return _TenantMeetingLookup(matched=False)

    @staticmethod
    def _extract_title(html: str) -> Optional[str]:
        """PrimeGov's Portal/Meeting pages always carry TWO <title> tags
        -- confirmed live 2026-08-13 across all 3 real customers checked
        so far (OKC, Thousand Oaks, LA), not a one-off: an outer,
        generic, useless "<title>Meeting</title>" followed by a real one
        further into the response ("City Council - 8/4/2026 1:30:00 PM",
        "Thousand Oaks City Council Regular Meeting (Closed Session) -
        7/8/2026 12:00:00 AM", "City Council Meeting - 8/12/2026
        5:00:00 PM"). Returns the first one that isn't the exact generic
        placeholder text.
        """
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all("title"):
            text = tag.get_text(strip=True)
            if text and text.lower() != "meeting":
                return text
        return None

    @staticmethod
    def _extract_date(html: str) -> Optional[str]:
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)[:2000]
        match = _MONTH_DATE_RE.search(text)
        if not match:
            return None
        month = _MONTHS.index(match.group(1)) + 1
        day = int(match.group(2))
        year = match.group(3)
        return f"{year}-{month:02d}-{day:02d}"

    @staticmethod
    def _extract_jurisdiction(html: str, url: str) -> Optional[str]:
        text = _BOILERPLATE_RE.sub("", html)
        netloc = urlparse(url).netloc
        council_jurisdiction = PrimeGovAssetFinder._extract_council_header_jurisdiction(
            text, netloc
        )
        if council_jurisdiction:
            return council_jurisdiction
        match = _JURISDICTION_RE.search(text)
        if not match:
            return None
        kept = []
        for word in match.group(2).split():
            core = word.strip(".,;:")
            if not core or not core[0].isupper():
                break
            # Normalize all-caps header text ("OKLAHOMA CITY") to title case
            # without touching text that's already properly cased
            # ("Thousand Oaks") -- confirmed live both styles occur.
            kept.append(core.title() if core.isupper() else core)
            if len(kept) >= 4:
                break
        if not kept:
            return None
        jurisdiction = f"{match.group(1).capitalize()} of {' '.join(kept)}"
        # No state anywhere in this shape -- confirmed real, e.g. "City of
        # Oklahoma City"/"City of Thousand Oaks". Reuses the same full
        # boilerplate-stripped text for the ZIP-address fallback, since a
        # real address (e.g. Thousand Oaks's own "2100 E. Thousand Oaks
        # Blvd., Thousand Oaks, CA 91362") could in principle appear
        # anywhere the jurisdiction match itself is now allowed to.
        return jurisdiction_enrich.enrich_jurisdiction_text(
            jurisdiction, netloc=netloc, page_text=text
        )

    @staticmethod
    def _extract_council_header_jurisdiction(text: str, netloc: str) -> Optional[str]:
        """Tried BEFORE `_JURISDICTION_RE` -- see `_COUNCIL_HEADER_RE`'s own
        module comment for the real Bedford/Cuyahoga bug this exists for.

        The captured words before "Council" are genuinely ambiguous on
        their own: "Oklahoma City Council" needs "City" kept as part of
        the real proper name ("Oklahoma City"), while "Bedford City
        Council" needs it dropped (there's no real place called "Bedford
        City" -- only "Bedford"). Rather than guess, both readings are
        built and `jurisdiction_enrich.is_literal_known_place()` -- a
        literal, un-stripped table lookup -- decides which one is real:
        confirmed live, "oklahoma city" is a real table key on its own,
        "bedford city" is not (only "bedford" is, via a trailing-word
        strip that isn't safe to assume here). Whichever name is chosen
        still has to pass the normal validate-or-repair pipeline
        (`jurisdiction_enrich.finalize_jurisdiction()`) before this
        returns anything, so a stray body-prose "X City Council" mention
        is discarded unless X is itself a real, known place.
        """
        match = _COUNCIL_HEADER_RE.search(text)
        if not match:
            return None
        words, type_word = match.group(1), match.group(2)
        full_run = f"{words} {type_word}"
        name = (
            full_run if jurisdiction_enrich.is_literal_known_place(full_run) else words
        )
        candidate = f"{type_word.capitalize()} of {name}"
        enriched = jurisdiction_enrich.enrich_jurisdiction_text(
            candidate, netloc=netloc, page_text=text
        )
        result = jurisdiction_enrich.finalize_jurisdiction(enriched, netloc=netloc)
        if result.confidence in ("validated", "repaired", "authoritative"):
            return result.jurisdiction
        return None
