import re
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder
from .models import ResolvedMeeting
from .youtube import YouTubeAssetFinder

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
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]

# Bounded by an HTML tag or punctuation so this doesn't run away mid-sentence
# on pages that phrase it in flowing prose (confirmed live: Thousand Oaks's
# "It is the mission of the City of Thousand Oaks that all employees...").
# The capitalized-word cap in _extract_jurisdiction() below is the second
# line of defense for the same problem when no tag/punctuation follows
# closely (confirmed live: OKC's header has no punctuation between adjacent
# table-cell headings once tags are stripped, e.g. "OKLAHOMA CITY FORMAL
# AGENDA CITY COUNCIL" would otherwise merge into one match).
_JURISDICTION_RE = re.compile(r"\b(city|county|town) of\s+([^<>]{1,80}?)(?=<|[,.])", re.IGNORECASE)


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

        # Prefer the PrimeGov page's own date/jurisdiction over whatever
        # YouTube's resolve_video_id already set -- see the module-level
        # comment on _MONTH_DATE_RE for why those are unreliable here. Only
        # override when a real match is found; otherwise leave YouTube's
        # (possibly wrong, but better-than-nothing) values in place.
        page_date = self._extract_date(html)
        if page_date:
            resolved.date = page_date
        page_jurisdiction = self._extract_jurisdiction(html)
        if page_jurisdiction:
            resolved.jurisdiction = page_jurisdiction

        return resolved

    @staticmethod
    def _extract_video_id(html: str) -> Optional[str]:
        match = _VIDEO_URL_VAR_RE.search(html)
        return match.group(1) if match else None

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
    def _extract_jurisdiction(html: str) -> Optional[str]:
        match = _JURISDICTION_RE.search(html)
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
        return f"{match.group(1).capitalize()} of {' '.join(kept)}"
