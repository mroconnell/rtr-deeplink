import re
from typing import Optional
from urllib.parse import urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder
from .models import ResolvedMeeting
from .youtube import YouTubeAssetFinder
from ..utils import jurisdiction_enrich

_VIDEO_URL_VAR_RE = re.compile(r'var\s+videoUrl\s*=\s*"([A-Za-z0-9_-]{11})"')

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
            jurisdiction, netloc=urlparse(url).netloc, page_text=text
        )
