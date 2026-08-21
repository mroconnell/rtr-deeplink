import asyncio
import random
import re
from datetime import datetime
from typing import List, Optional, Dict, Tuple
from urllib.parse import urlparse, parse_qs

import aiohttp
import wordninja
from bs4 import BeautifulSoup

from .base import AssetFinder
from .media_scan import is_hls_url, scan_media_urls, media_type
from .models import AlternateTranscript, ResolvedMeeting, TranscriptSegment
from ..utils import jurisdiction_enrich
from ..utils.vtt_parser import (
    STRUCTURED_CAPTION_PARSERS,
    decode_vtt_bytes,
    detect_language_from_texts,
    is_likely_garbled,
    parse_captions_by_extension,
)

TARGET_LANGUAGE = "en"

# Real bug confirmed live 2026-08-10 (Memphis, TN, clip 9789): the page's
# own body text has no date for *this* meeting anywhere, but does have
# "V. APPROVAL OF PREVIOUS MEETING MINUTES (December 5, 2023)" -- a
# standard agenda item referencing the *prior* meeting's date, which the
# body-text date scan below previously grabbed as if it were this
# meeting's own date (wrong by 14 days: the real date was December 19,
# 2023). A wrong date is worse than a missing one, so this is stripped
# out before date-parsing gets a chance to match inside it -- confirmed
# via the same real page that no OTHER date-shaped text exists there at
# all, so the fix correctly turns a wrong date into an honest missing one
# (matching how a different real Memphis clip with no date-shaped text
# anywhere, 10031, already came through with date=None), not a different
# wrong guess. Deliberately scoped to a parenthetical right after
# "previous/prior/last meeting" (the exact real shape confirmed) rather
# than a loose N-character window -- a wider window risks eating a real,
# unrelated date that happens to follow shortly after on some other
# page's differently-worded text.
_PREVIOUS_MEETING_DATE_RE = re.compile(
    r"(?:previous|prior|last)\s+meeting[^()]{0,40}\([^)]{0,40}\)", re.IGNORECASE
)

# Governing-body keywords used to decide whether the RSS channel title's
# second half ("City Council", "New View", "All City Dockets", ...) is
# worth appending to a page-scraped title that doesn't already name a body,
# versus a generic/unhelpful channel label not worth adding as noise.
GOVERNING_BODY_KEYWORDS = ("council", "commission", "board", "committee", "hearing")

US_STATE_ABBREVIATIONS = {
    "al",
    "ak",
    "az",
    "ar",
    "ca",
    "co",
    "ct",
    "de",
    "fl",
    "ga",
    "hi",
    "id",
    "il",
    "in",
    "ia",
    "ks",
    "ky",
    "la",
    "me",
    "md",
    "ma",
    "mi",
    "mn",
    "ms",
    "mo",
    "mt",
    "ne",
    "nv",
    "nh",
    "nj",
    "nm",
    "ny",
    "nc",
    "nd",
    "oh",
    "ok",
    "or",
    "pa",
    "ri",
    "sc",
    "sd",
    "tn",
    "tx",
    "ut",
    "vt",
    "va",
    "wa",
    "wv",
    "wi",
    "wy",
    "dc",
}


class GranicusAssetFinder(AssetFinder):
    """Resolves video + transcript for a Granicus meeting page.

    Ported from rtr-transcripts/app/services/granicus.py, which we validated
    against 12 real Granicus-hosted cities (San Diego, Oakland, Berkeley,
    Alexandria VA, Boston, San Francisco, etc.) — the fetch/parse/media-URL
    logic works. Stripped of MongoDB/Beanie/job-queue/websocket dependencies,
    since this app has no database. Two real bugs found during that testing
    are fixed here:
      1. extract_media_urls no longer returns relative paths (e.g.
         "/videos/5361/captions.vtt") unresolved — everything is run through
         urljoin() against the page URL before being treated as fetchable.
      2. Caption text is parsed and returned directly in the response
         (as `segments`), instead of only being persisted to a database and
         never surfaced to the caller.
    """

    platform_name = "granicus"

    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    async def _fetch_page(
        self, session: aiohttp.ClientSession, url: str, max_retries: int = 3
    ) -> Tuple[str, str]:
        """Returns (html, final_url) -- final_url is the post-redirect URL,
        which matters because a real MediaPlayer.php?clip_id=... URL (how
        Granicus's own UI shares links) always redirects to /player/clip/{id}
        before we ever see it. Callers that pattern-match on URL shape (see
        _extract_clip_id) must use final_url, not the originally-submitted
        one, or that matching silently never fires -- confirmed via a real
        Mountain View meeting submitted as a MediaPlayer.php URL, where the
        old code (matching against the pre-redirect url) never guessed the
        captions.vtt path at all.
        """
        last_error = None
        for attempt in range(max_retries):
            try:
                async with session.get(
                    url,
                    headers=self.headers,
                    allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status >= 400:
                        raise aiohttp.ClientError(f"HTTP {response.status} for {url}")
                    return await response.text(), str(response.url)
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = e
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep((2**attempt) * random.uniform(0.5, 1.5))
        raise aiohttp.ClientError(f"Failed to fetch {url}: {last_error}")

    def _extract_metadata(
        self, soup: BeautifulSoup, url: str, html: str
    ) -> Dict[str, Optional[str]]:
        def text_of(selector) -> Optional[str]:
            el = soup.select_one(selector)
            if el:
                content = el.get_text(" ", strip=True)
                return content.strip() or None
            return None

        def meta_content(selector) -> Optional[str]:
            el = soup.select_one(selector)
            if el:
                content = el.get("content")
                return content.strip() if content else None
            return None

        title = (
            meta_content('meta[property="og:title"]')
            or text_of("h1")
            or (soup.title.get_text(strip=True) if soup.title else None)
        )

        date = None
        date_str = meta_content('meta[property="article:published_time"]')
        if date_str:
            date = self._parse_date_string(date_str)
        if not date and title:
            date = self._parse_date_string(title)
        if not date:
            body_text = soup.get_text(" ", strip=True)[:2000]
            body_text = _PREVIOUS_MEETING_DATE_RE.sub("", body_text)
            date = self._parse_date_string(body_text)

        # "City of San Diego" in the page body is a more reliable jurisdiction
        # source than guessing from the subdomain -- confirmed present on
        # multiple real Granicus pages (San Diego, Richmond via eScribe/
        # iSiLIVE). Preferred over subdomain segmentation; itself overridden
        # later in resolve() by the RSS channel title when available (see
        # _fetch_channel_info), which is the most reliable source of all.
        jurisdiction = None
        # Include the meta description, not just visible body text -- found
        # a real case (sdcounty.granicus.com) where "San Diego County" only
        # appears inside <meta name="description" content="...">, which
        # soup.get_text() never sees since it only walks text nodes, not
        # attribute values.
        page_text = (
            soup.get_text(" ", strip=True)
            + " "
            + (meta_content('meta[name="description"]') or "")
        )
        # Real bug fixed 2026-08-16 (WO-14, BACKLOG.md): this used to be a
        # bare `re.search(r"\b(City|County|Town) of ([A-Z][A-Za-z .]{1,40})",
        # ...)` with no sentence/tag boundary, so once "City of X" matched it
        # kept consuming letters/spaces/periods for up to 40 more characters
        # regardless of whether that text was still the city name --
        # confirmed live on 9 real customers (Sarasota, Punta Gorda,
        # Huntsville, Fort Worth, Edgewater, Castle Rock, Castle Pines,
        # Boston, Milwaukee), e.g. hercules.granicus.com/player/clip/1306
        # producing 'City of Hercules. XIV. PUBLIC COMMUNICATIONS XV. '
        # character for character. extract_jurisdiction_chain() is the same
        # bounded stop-rule/capitalization-walk chain already shipped for
        # swagit/civicclerk/generic_fallback -- every candidate it returns
        # is validated against the Census tables (directly or via
        # trim-repair) before being accepted, so it declines instead of
        # guessing when nothing cleanly bounds the match.
        jurisdiction = jurisdiction_enrich.extract_jurisdiction_chain(
            page_text=page_text, html=html, url=url
        )
        if not jurisdiction:
            # Some counties are phrased the other way round on their own
            # pages ("San Diego County" rather than "County of San Diego") --
            # confirmed on a real sdcounty.granicus.com page, where the
            # City-of/County-of pattern above doesn't match at all. Not
            # covered by extract_jurisdiction_chain(), which only handles
            # "X of Y" phrasing.
            reversed_match = re.search(
                r"\b([A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+){0,2}) (County|Parish)\b",
                page_text,
            )
            if reversed_match:
                jurisdiction = (
                    f"{reversed_match.group(1).strip()} {reversed_match.group(2)}"
                )

        netloc = urlparse(url).netloc
        domain_parts = netloc.split(".")
        if (
            not jurisdiction
            and len(domain_parts) > 1
            and domain_parts[0] not in ("www", "granicus")
        ):
            candidate = self._humanize_subdomain(domain_parts[0], url)
            if candidate:
                jurisdiction = candidate

        jurisdiction = jurisdiction or "Unknown Jurisdiction"

        if not title:
            title = f"{jurisdiction} Meeting" + (f" - {date}" if date else "")

        return {
            "title": title[:500],
            "date": date,
            "jurisdiction": jurisdiction[:200],
            "page_text": page_text,
        }

    @staticmethod
    def _humanize_subdomain(subdomain: str, url: str) -> Optional[str]:
        """Turn a concatenated subdomain like "sandiego" or "leaguecitytx"
        into "San Diego" / "League City, TX". The name itself comes from
        `jurisdiction_enrich.validated_subdomain_extract()` -- Census-
        table-validated (raw label tried first, then a wordninja split),
        declining (returning None) rather than guessing when neither form
        is a real place name. Real bug this replaced: a bare
        wordninja-always-guess produced confident garbage on acronym
        subdomains, e.g. "sfwmd" -> "S Fw, MD" (South Florida Water
        Management District's trailing "md" misread as a Maryland state
        suffix), "psrc2" -> "Psr C 2", "rideuta" -> "Ride Uta" -- see
        BACKLOG.md. A trailing US state abbreviation is still stripped and
        reattached as a ", ST" suffix independently of validation, same as
        before -- some subdomains encode it specifically to disambiguate a
        nationally-ambiguous city name (e.g. "leaguecitytx").
        """
        words = wordninja.split(subdomain)
        state_suffix = None
        if words and len(words) > 1 and words[-1].lower() in US_STATE_ABBREVIATIONS:
            state_suffix = words[-1].upper()

        name = jurisdiction_enrich.validated_subdomain_extract(url)
        if not name:
            return None

        return f"{name}, {state_suffix}" if state_suffix else name

    @staticmethod
    def _parse_date_string(text: str) -> Optional[str]:
        if not text:
            return None
        patterns = [
            r"\b(20\d{2})-(0?[1-9]|1[0-2])-(0?[1-9]|[12]\d|3[01])\b",
            r"\b(0?[1-9]|1[0-2])[/-](0?[1-9]|[12]\d|3[01])[/-](20\d{2})\b",
            r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* "
            r"(0?[1-9]|[12]\d|3[01]),? (20\d{2})\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                for fmt in (
                    "%Y-%m-%d",
                    "%m-%d-%Y",
                    "%m/%d/%Y",
                    "%B %d, %Y",
                    "%b %d, %Y",
                ):
                    try:
                        return datetime.strptime(match.group(0), fmt).strftime(
                            "%Y-%m-%d"
                        )
                    except ValueError:
                        continue
        return None

    _DOCKET_DATE_RE = re.compile(r"_(\d{2})-(\d{2})-(\d{2})_")

    @staticmethod
    def _extract_date_from_document_links(soup: BeautifulSoup) -> Optional[str]:
        """Last-resort date fallback, tried only after both page text and
        the RSS feed have failed -- confirmed real and needed on
        Alexandria, VA's Granicus pages (clip 6490), which are thin
        client-rendered shells with almost no static visible text (no
        og:title, no h1, under 700 characters of body text total) and no
        view_id to cross-reference against an RSS feed either.

        Agenda/Minutes document links are still server-rendered as plain
        `data-url="...pdf"` attributes even on a page this thin -- missed
        by every text-based source above since attribute values aren't
        visible text -- and Legistar-hosted Granicus cities name those
        files with a "_YY-MM-DD_" fragment, e.g.
        "..._25-04-02_Docket.pdf" for an April 2, 2025 meeting (confirmed
        consistent across that same real meeting's Agenda and Minutes
        links both).
        """
        for el in soup.select("[data-url]"):
            match = GranicusAssetFinder._DOCKET_DATE_RE.search(el.get("data-url") or "")
            if not match:
                continue
            yy, mm, dd = match.groups()
            try:
                return datetime.strptime(f"20{yy}-{mm}-{dd}", "%Y-%m-%d").strftime(
                    "%Y-%m-%d"
                )
            except ValueError:
                continue
        return None

    @staticmethod
    def _extract_clip_id(page_url: str) -> Optional[str]:
        """Pull the numeric clip id out of any of Granicus's three
        *archived-clip* URL shapes: path-based /player/clip/{id},
        path-based /videos/{id}/, or query-based ?clip_id={id}
        (MediaPlayer.php). Must be called with the post-redirect URL --
        see _fetch_page's docstring.

        Deliberately does NOT also match the fourth known shape,
        ?event_id={id} (MediaPlayer.php, redirecting to /player/event/{id})
        -- see _extract_event_id() below for why that id is a genuinely
        different, non-interchangeable namespace and must never be
        returned from here.
        """
        if "granicus.com/player/clip/" in page_url:
            return page_url.split("/player/clip/")[1].split("?")[0].split("/")[0]
        if "granicus.com/videos/" in page_url:
            return page_url.split("/videos/")[1].split("/")[0]
        query = parse_qs(urlparse(page_url).query)
        return query.get("clip_id", [None])[0]

    @staticmethod
    def _extract_event_id(page_url: str) -> Optional[str]:
        """Pull the numeric event id out of Granicus's fourth URL shape --
        query-based ?event_id={id} (MediaPlayer.php), which 302-redirects
        to path-based /player/event/{id}?redirect=true. Confirmed live
        2026-08-21 across 4 real cities discovered via PrimeGov's own
        video delegation (Calabasas CA, Elk Grove CA, Emeryville CA --
        real Granicus subdomain "emeryville.granicus.com", NOT
        "emeryvilleca.granicus.com" as the PrimeGov tenant name would
        suggest; that subdomain 404s -- and Nassau County FL, real
        Granicus subdomain "nassaufl.granicus.com"), one directly fetched
        (both plain HTTP and, for Calabasas, a real rendered-browser
        check) per tenant, plus 11 more historical event_id examples
        (15 total) surfaced from the same 4 tenants' own PrimeGov
        ListArchivedMeetings history.

        Deliberately kept as a fully separate id namespace from clip_id,
        never merged into it or passed to any clip_id-shaped endpoint
        (video URL guess, AgendaViewer.php, MinutesViewer.php, the
        /videos/{id}/player fallback) -- confirmed real and necessary,
        not a hypothetical caution: every one of the 15 confirmed
        examples above has an event_id far outside that same tenant's
        real clip_id range (e.g. Calabasas event_id=1525 vs. real
        clip_ids in the 7000s-8000s), so treating them as
        interchangeable risks either a wasted request or -- worse -- a
        coincidental collision with a real, unrelated clip_id on the
        same tenant, silently producing a wrong meeting's video.

        Every one of the 15 confirmed examples also corresponds, per
        PrimeGov's own ListArchivedMeetings API, to a meeting with
        streamCompleted=False and mediaManagerClipPubliclyAvailable=False
        -- i.e. genuinely not yet archived, not merely a shape this
        scanner failed to detect. Confirmed by fetching the real
        post-redirect /player/event/{id} page directly (all 4 tenants,
        both via plain HTTP and a real rendered-browser check on
        Calabasas): no video-player library is even loaded, no video
        element or media URL of any kind appears anywhere in the page,
        and the page's own static, server-rendered
        `<div id="player-error">` reads "The event you selected is not
        currently in progress." -- see _extract_live_status_message(),
        which surfaces that exact real message as the video warning
        instead of guessing at a nonexistent video.
        """
        if "granicus.com/player/event/" in page_url:
            return page_url.split("/player/event/")[1].split("?")[0].split("/")[0]
        query = parse_qs(urlparse(page_url).query)
        return query.get("event_id", [None])[0]

    @staticmethod
    def _extract_live_status_message(soup: BeautifulSoup) -> Optional[str]:
        """Granicus's /player/event/{id} page (the event_id URL shape --
        see _extract_event_id()) renders a real, specific, server-side
        status message in a static `#player-error` div when there's no
        video to show -- confirmed verbatim identical across 4 real
        cities (Calabasas CA, Elk Grove CA, Emeryville CA, Nassau County
        FL, 2026-08-21): "The event you selected is not currently in
        progress." Surfaced directly as the video warning when present
        (see resolve()) since it's Granicus's own accurate explanation,
        more honest than a generic "no playable video found" that implies
        we merely failed to find one that exists. Not limited to the
        event_id case specifically -- if this div shows up on any other
        Granicus page shape, its message is equally real and worth
        surfacing the same way.
        """
        el = soup.select_one("#player-error")
        if not el:
            return None
        text = el.get_text(" ", strip=True)
        return text or None

    def _extract_media_urls(self, html: str, page_url: str) -> List[str]:
        """Find media asset URLs on the page: Granicus's own guessed-VTT-path
        heuristic (its player/clip URLs don't always embed the caption URL
        directly in HTML) plus the shared generic regex scan.
        """
        media_urls = set()

        video_id = self._extract_clip_id(page_url)
        if video_id:
            domain = urlparse(page_url).netloc
            media_urls.add(f"https://{domain}/videos/{video_id}/captions.vtt")

        media_urls.update(scan_media_urls(html, page_url))

        return list(media_urls)

    _media_type = staticmethod(media_type)

    @staticmethod
    def _pick_video_url(media_urls: List[str]) -> Tuple[Optional[str], Optional[str]]:
        """m3u8 preferred over a bare mp4 when both are present -- HLS gets
        adaptive bitrate via hls.js, a direct mp4 doesn't."""
        for candidate in media_urls:
            if media_type(candidate) == "video" and is_hls_url(candidate):
                return candidate, "m3u8"
        for candidate in media_urls:
            if media_type(candidate) == "video":
                return candidate, "mp4"
        return None, None

    @staticmethod
    async def _fetch_video_from_player_page(
        session: aiohttp.ClientSession, domain: str, clip_id: str
    ) -> Tuple[Optional[str], Optional[str]]:
        """Fallback video discovery for cities whose MediaPlayer.php still
        embeds the legacy Flash player object (a `stream_type=rtmp` URL --
        unplayable in any modern browser, Flash is gone) instead of a
        scannable HLS/mp4 reference. Confirmed real via Fountain Valley CA
        (clip 607, user-reported 2026-08-08): MediaPlayer.php's HTML has
        zero .m3u8/.mp4 anywhere, only that Flash embed -- but Granicus's
        newer `/videos/{id}/player` page for the same clip loads hls.js
        against a real, working .m3u8 stream. Only called when the main
        page scan already found nothing, so cities where the video's
        already on the main page (the common case) pay no extra request.
        Single-attempt, not `_fetch_page`'s retry-with-backoff -- this is an
        opportunistic probe on top of an already-successful resolve, not
        the one request the whole resolve depends on, so it fails cheap
        and fast the same way `_fetch_caption_file` does.
        """
        player_url = f"https://{domain}/videos/{clip_id}/player"
        try:
            async with session.get(
                player_url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status != 200:
                    return None, None
                html = await response.text()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None, None
        return GranicusAssetFinder._pick_video_url(scan_media_urls(html, player_url))

    async def resolve(self, url: str) -> ResolvedMeeting:
        video_warnings: List[str] = []
        transcript_warnings: List[str] = []
        async with aiohttp.ClientSession() as session:
            html, final_url = await self._fetch_page(session, url)
            soup = BeautifulSoup(html, "html.parser")
            metadata = self._extract_metadata(soup, final_url, html)
            media_urls = self._extract_media_urls(html, final_url)
            clip_id = self._extract_clip_id(final_url)
            # Only looked up when there's no real clip_id -- a meeting
            # that hasn't been streamed/archived yet (see
            # _extract_event_id's docstring). Never treated as
            # interchangeable with clip_id anywhere below.
            event_id = None if clip_id else self._extract_event_id(final_url)

            # The RSS channel title (constant per view_id, distinct from each
            # meeting's own often-poor-quality title -- confirmed real
            # examples like San Diego's "Tuesday Agenda Revised Added
            # S500-S511") is the most reliable source of both jurisdiction
            # and governing-body name, when it's available at all. The RSS
            # item matched by clip_id is likewise the most reliable date
            # source when the page itself has none -- confirmed real (San
            # Francisco Board of Supervisors, clip 52945: no date anywhere
            # on the page, but a real RSS pubDate).
            (
                channel_jurisdiction,
                channel_body,
                item_date,
            ) = await self._fetch_channel_info(session, final_url, clip_id)
            if channel_jurisdiction:
                metadata["jurisdiction"] = channel_jurisdiction
            # Neither source above (body-text match or the RSS channel
            # title that can just override it) ever includes a state --
            # fill one in via the shared jurisdiction_enrich module once
            # whichever of the two has won, reusing the same page_text
            # _extract_metadata() already built (visible text + meta
            # description, since a real address has been found living in
            # only one or the other on different real pages).
            metadata["jurisdiction"] = jurisdiction_enrich.enrich_jurisdiction_text(
                metadata["jurisdiction"],
                netloc=urlparse(final_url).netloc,
                page_text=metadata["page_text"],
                placeholder="Unknown Jurisdiction",
            )
            if not metadata["date"] and item_date:
                metadata["date"] = item_date
            if not metadata["date"] and clip_id:
                # Real gap confirmed live 2026-08-10 (Memphis, TN clip
                # 10031, "Parks & Environment"): no date anywhere on the
                # page itself and not in the RSS feed either (an old-
                # enough or otherwise-excluded item), but Granicus's own
                # published Minutes document has the real date right at
                # the top. Tried before the document-link-filename last
                # resort below since this is real structured content, not
                # a filename guess.
                metadata["date"] = await self._fetch_minutes_date(
                    session, final_url, clip_id
                )
            if not metadata["date"]:
                # True last resort, tried only once page text, RSS, and
                # published minutes have all failed -- confirmed real and
                # needed on Alexandria, VA's Granicus pages (clip 6490),
                # thin client-rendered shells with almost no static
                # visible text and no view_id to cross-reference against
                # an RSS feed either.
                metadata["date"] = self._extract_date_from_document_links(soup)
            title_has_body = metadata["title"] and any(
                kw in metadata["title"].lower() for kw in GOVERNING_BODY_KEYWORDS
            )
            body_is_meaningful = channel_body and any(
                kw in channel_body.lower() for kw in GOVERNING_BODY_KEYWORDS
            )
            if body_is_meaningful and not title_has_body and metadata["title"]:
                metadata["title"] = f"{channel_body} — {metadata['title']}"

            video_url, video_format = self._pick_video_url(media_urls)
            if not video_url and clip_id:
                domain = urlparse(final_url).netloc
                video_url, video_format = await self._fetch_video_from_player_page(
                    session, domain, clip_id
                )
            if not video_url:
                # Prefer Granicus's own real, specific explanation when the
                # page has one (confirmed real on every event_id case --
                # see _extract_live_status_message()) over the generic
                # message, which implies a video exists somewhere we
                # merely failed to find.
                video_warnings.append(
                    self._extract_live_status_message(soup)
                    or "No playable video found on this page."
                )

            # No longer .vtt-only: media_type() now classifies a wider set
            # of caption-shaped extensions as "subtitle" (see
            # media_scan.CAPTION_EXTENSIONS) -- .srt is structurally
            # parseable the same way .vtt is (see parse_captions_by_extension),
            # and the rest at least get a best-effort text fallback or a
            # direct link instead of being silently invisible.
            caption_urls = [u for u in media_urls if self._media_type(u) == "subtitle"]

            segments: List[TranscriptSegment] = []
            transcript_language: Optional[str] = None
            alternate_transcripts: List[AlternateTranscript] = []
            if caption_urls:
                fetched = await asyncio.gather(
                    *(self._fetch_caption_file(session, u) for u in caption_urls),
                    return_exceptions=True,
                )

                # Evaluate every successfully-fetched track's *actual content*
                # language rather than trusting the page's srclang label —
                # confirmed via a real Simi Valley meeting (clip 2840) that
                # a track labeled srclang="en" was actually Spanish content.
                candidates = []  # (url, cues, detected_language) -- structured formats only
                text_fallback_candidates = []  # (url, text) -- no real timing available
                unreadable_urls = []  # fetched fine, but format has no extractable content at all
                empty_or_failed_count = 0
                for caption_url, result in zip(caption_urls, fetched):
                    if isinstance(result, Exception):
                        transcript_warnings.append(
                            f"Failed to fetch captions from {caption_url}: {result}"
                        )
                        continue
                    cues, fallback_text = result
                    if cues:
                        candidates.append(
                            (
                                caption_url,
                                cues,
                                detect_language_from_texts(c.get("text") for c in cues),
                            )
                        )
                    elif fallback_text:
                        text_fallback_candidates.append((caption_url, fallback_text))
                    elif (
                        caption_url.lower().split("?")[0].rsplit(".", 1)[-1]
                        in STRUCTURED_CAPTION_PARSERS
                    ):
                        # A real, fetchable file in a format we DO understand
                        # structurally, but it came back with zero cues --
                        # Granicus's own real placeholder case for .vtt
                        # (confirmed: an 8-byte "WEBVTT\n\n" every meeting
                        # gets whether or not captioning was ever generated),
                        # not an unsupported-format problem.
                        empty_or_failed_count += 1
                    else:
                        # A format with no structured parser and nothing
                        # extractable even as best-effort text (binary
                        # formats like .scc/.stl, or a text-based one that
                        # happened to come back empty) -- surface the link
                        # directly rather than silently dropping it, same
                        # reasoning as the AgendaViewer fallback-link case
                        # below.
                        unreadable_urls.append(caption_url)

                target_match = next(
                    (c for c in candidates if c[2] == TARGET_LANGUAGE), None
                )
                chosen = target_match or (candidates[0] if candidates else None)

                if (
                    not chosen
                    and not text_fallback_candidates
                    and empty_or_failed_count
                ):
                    transcript_warnings.append(
                        "Caption file was blank, so we don't have a transcript for "
                        "this meeting yet — you can request one be generated from "
                        "the audio below."
                    )

                if chosen:
                    _vtt_url, cues, lang = chosen
                    segments = [TranscriptSegment(**cue) for cue in cues]
                    transcript_language = lang
                    if len(segments) == 36000:
                        # Granicus's own captions.vtt appears to hard-cap at
                        # exactly 36,000 cues on very long meetings, cutting
                        # off mid-sentence with no warning of its own --
                        # confirmed live on 3 independent real customers
                        # (College Park GA, Coral Gables FL, Marion County
                        # FL), see BACKLOG.md. A real meeting landing on
                        # this exact count by chance is essentially
                        # impossible, so flag it rather than silently
                        # presenting a truncated transcript as complete.
                        # First heuristic, not a full fix -- doesn't catch
                        # a cap at some other round number.
                        transcript_warnings.append(
                            "This transcript may be cut off — it hit exactly "
                            "36,000 lines, a known limit in Granicus's own "
                            "captioning for very long meetings."
                        )
                    if lang and lang != TARGET_LANGUAGE:
                        transcript_warnings.append(
                            f"These captions appear to be in '{lang}', not '{TARGET_LANGUAGE}' — "
                            "no matching-language track was found for this meeting."
                        )
                    if len(candidates) > 1 and not target_match:
                        other_langs = sorted({c[2] for c in candidates if c[2]})
                        transcript_warnings.append(
                            f"Multiple caption tracks found ({other_langs}); none matched '{TARGET_LANGUAGE}'."
                        )
                    if is_likely_garbled(cues):
                        transcript_warnings.append(
                            "This transcript looks garbled at the source (not a parsing "
                            "bug on our end) — treat it as approximate. You can request "
                            "a transcript from the audio instead."
                        )
                    # Every other real (non-blank) track that was fetched but
                    # not chosen -- carried through with full segments (not
                    # just a language label) so the frontend can offer a
                    # switcher without a second round-trip.
                    alternate_transcripts = [
                        AlternateTranscript(
                            language=lang,
                            segments=[
                                TranscriptSegment(**cue) for cue in candidate_cues
                            ],
                        )
                        for candidate_vtt_url, candidate_cues, lang in candidates
                        if candidate_vtt_url != _vtt_url
                    ]
                elif text_fallback_candidates:
                    # No structured (timed) transcript available anywhere,
                    # but real caption text exists in a format with no
                    # parser here (e.g. SBV/SUB/SMI) -- shown as a single
                    # untimed block rather than discarded. Deep-linking to
                    # the video's playhead via `t=` never depended on
                    # transcript timing (works with zero transcript at
                    # all), so this is still real added value even without
                    # per-line clickability. Never verified against a real
                    # sample from any platform this app supports -- see
                    # BACKLOG.md.
                    fallback_url, fallback_text = text_fallback_candidates[0]
                    segments = [
                        TranscriptSegment(start=0.0, end=0.0, text=line)
                        for line in fallback_text.split("\n")
                        if line.strip()
                    ]
                    transcript_warnings.append(
                        "This meeting has captions, but in a format we can only show "
                        "as plain text, not a clickable per-line transcript."
                    )
                elif unreadable_urls:
                    transcript_warnings.append(
                        "This meeting has a caption file, but in a format we can't "
                        f"read at all yet — you can view it directly: {unreadable_urls[0]}"
                    )
            else:
                transcript_warnings.append(
                    "No caption/transcript file found on this page."
                )

            # Agenda is fetched independently of whether a real transcript
            # was found -- it's useful navigation context either way, not
            # just a fallback for when there's nothing else. Kept in its
            # own field (never folded into `segments`) so it's never
            # mistaken for real transcript content.
            agenda_items: List[TranscriptSegment] = []
            agenda_link: Optional[str] = None
            if clip_id:
                raw_items, agenda_fallback_url = await self._fetch_agenda_items(
                    session, final_url, clip_id
                )
                if raw_items:
                    raw_items.sort(key=lambda item: item[0])
                    for i, (start, item_title) in enumerate(raw_items):
                        end = raw_items[i + 1][0] if i + 1 < len(raw_items) else start
                        agenda_items.append(
                            TranscriptSegment(
                                start=start, end=max(end, start), text=item_title
                            )
                        )
                elif agenda_fallback_url:
                    # No timestamped chapter data (e.g. Berkeley/Paradise Valley AZ,
                    # which redirect AgendaViewer.php to their own external site or a
                    # PDF instead of Granicus's native structure) -- still a real,
                    # fetchable agenda, just not one we can parse into clickable
                    # moments. `agenda_link` (not a transcript_warnings sentence --
                    # matches generic_fallback.py's own best-effort agenda link, same
                    # field, same "we think we found an agenda here: <link>" frontend
                    # treatment in player.js/meeting_page.html) so it renders as real
                    # structured content rather than being buried in a warning string.
                    agenda_link = agenda_fallback_url

            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                # Namespaced by host, not just the bare clip_id -- Granicus
                # is multi-tenant and every customer numbers clips from near
                # 1 independently, so two different cities routinely share
                # the same clip_id. Real bug, confirmed live 2026-08-18: an
                # unnamespaced external_id let _find_existing_page()
                # (archive/db/crud.py) match e.g. "granicus:453" across 3
                # unrelated counties and silently overwrite each other's
                # title/date/jurisdiction on one shared row. See BACKLOG.md.
                external_id=(
                    f"granicus:{urlparse(final_url).netloc}:{clip_id}"
                    if clip_id
                    else (
                        # "event:" infix keeps this permanently distinct
                        # from a real clip_id-based id above (always a
                        # bare number) -- event_id and clip_id are
                        # separate number spaces on the same tenant (see
                        # _extract_event_id's docstring), so this must
                        # never collide with or be mistaken for a real
                        # archived clip's external_id.
                        f"granicus:{urlparse(final_url).netloc}:event:{event_id}"
                        if event_id
                        else None
                    )
                ),
                transcript_language=transcript_language,
                title=metadata["title"],
                date=metadata["date"],
                jurisdiction=metadata["jurisdiction"],
                video_url=video_url,
                video_format=video_format,
                segments=segments,
                agenda_items=agenda_items,
                agenda_link=agenda_link,
                alternate_transcripts=alternate_transcripts,
                video_warnings=video_warnings,
                transcript_warnings=transcript_warnings,
            )

    @staticmethod
    async def _fetch_caption_file(session: aiohttp.ClientSession, caption_url: str):
        """Returns (cues, fallback_text) via parse_captions_by_extension --
        (None, None) on a fetch failure or a genuinely unparseable format."""
        async with session.get(
            caption_url, timeout=aiohttp.ClientTimeout(total=20)
        ) as response:
            if response.status != 200:
                return None, None
            raw = await response.read()
        content = decode_vtt_bytes(raw)
        return parse_captions_by_extension(caption_url, content)

    @staticmethod
    async def _fetch_agenda_items(
        session: aiohttp.ClientSession, page_url: str, clip_id: str
    ) -> Tuple[List[Tuple[float, str]], Optional[str]]:
        """Best-effort fallback chapter markers for meetings with no usable
        transcript: Granicus's own agenda-index feature (AgendaViewer.php),
        when a customer has it turned on, renders each agenda item as
        `<a name="agenda{id}" onclick="top.SetPlayerPosition('0:{seconds}',
        null)">{title}</a>` -- confirmed live on Simi Valley and San
        Francisco (case/whitespace vary by customer template, matched
        case-insensitively via html.parser's own attribute normalization).

        Returns (items, fallback_url). Not every customer has the native
        structure on: confirmed Berkeley redirects AgendaViewer.php to its
        own external site instead (empty cuepoints too), and Paradise
        Valley AZ redirects it to a Google Docs PDF preview (HTML, still
        text-decodable). Napa (confirmed live 2026-08-11, City Council/
        Housing Authority/Measure G clips) redirects straight to a *raw*
        binary PDF instead -- `response.text()` raises `UnicodeDecodeError`
        on that, which must be caught separately from real request
        failures (bad status/connection error): those still return
        `fallback_url=None` (nothing real to link to), but a 200 response
        that simply isn't decodable as text is exactly the "real,
        fetchable agenda, just not parseable" case this fallback exists
        for, so `final_url` -- captured before the read, since the read
        itself is what can fail -- is still returned as `fallback_url`.

        Note SetPlayerPosition's argument isn't real H:MM:SS -- Granicus's
        own JS does `time.replace(':', '')` and parses the result as an
        integer, so '0:638' means 638 seconds, not 6 minutes 38 seconds.
        """
        domain = urlparse(page_url).netloc
        agenda_url = f"https://{domain}/AgendaViewer.php?clip_id={clip_id}&embedded=1"
        try:
            async with session.get(
                agenda_url, timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                if response.status != 200:
                    return [], None
                final_url = str(response.url)
                try:
                    html = await response.text()
                except (UnicodeDecodeError, LookupError):
                    return [], final_url
        except Exception:
            return [], None

        soup = BeautifulSoup(html, "html.parser")
        items = []
        for a in soup.find_all("a", attrs={"name": re.compile(r"^agenda\d+$")}):
            match = re.search(r"SetPlayerPosition\('0:(\d+)'", a.get("onclick") or "")
            title = a.get_text(" ", strip=True)
            if match and title:
                items.append((float(match.group(1)), title))

        return items, (None if items else final_url)

    @staticmethod
    async def _fetch_minutes_date(
        session: aiohttp.ClientSession, page_url: str, clip_id: str
    ) -> Optional[str]:
        """Granicus's own Minutes-viewer feature (MinutesViewer.php), when a
        customer has published minutes for this specific meeting, is a
        real, plain HTTP-fetchable page (no headless browser needed --
        unlike the player page's own "Minutes" tab, which loads this same
        content into an iframe via JS the user has to click, confirmed
        live 2026-08-10) with the real meeting date right at the top.
        Confirmed on a real Memphis, TN clip (10031, "Parks & Environment")
        that had no date-shaped text anywhere else at all: MinutesViewer.
        php's own text opens with "MINUTES / COUNCIL COMMITTEE MEETING /
        CITY OF MEMPHIS / July 23, 2024".

        Requires both clip_id and view_id (unlike AgendaViewer.php, which
        only needs clip_id) -- matches the query string Granicus's own
        player page uses to embed this content.

        `allow_redirects=False` deliberately -- confirmed live on a
        second real Memphis clip (9789) with no published minutes: this
        endpoint 302-redirects to a raw scanned PDF (binary content, not
        real HTML text) rather than 404ing. Treating a redirect the same
        as any other failure (no minutes available) avoids ever handing
        binary PDF bytes to BeautifulSoup.
        """
        query = parse_qs(urlparse(page_url).query)
        view_id = query.get("view_id", [None])[0]
        if not view_id:
            return None
        domain = urlparse(page_url).netloc
        minutes_url = f"https://{domain}/MinutesViewer.php?clip_id={clip_id}&view_id={view_id}&embedded=1"
        try:
            async with session.get(
                minutes_url,
                timeout=aiohttp.ClientTimeout(total=15),
                allow_redirects=False,
            ) as response:
                if response.status != 200:
                    return None
                html = await response.text()
        except Exception:
            return None

        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)[:1000]
        text = _PREVIOUS_MEETING_DATE_RE.sub("", text)
        return GranicusAssetFinder._parse_date_string(text)

    @staticmethod
    async def _fetch_channel_info(
        session: aiohttp.ClientSession, url: str, clip_id: Optional[str]
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Fetch the Granicus RSS feed for this page's view_id and pull:
        (1) the channel-level title, which reliably follows "{Jurisdiction}:
        {Body} (Videos Feed)" -- e.g. "City of San Diego: City Council
        Meetings (Videos Feed)". Confirmed across 6 real cities (2026-08-06).
        Unlike each meeting's own item-level title (which can be as
        unhelpful as "Tuesday Agenda Revised Added S500-S511" -- the literal
        title San Diego staff gave one real meeting), the channel title is
        constant per view_id and doesn't depend on how well that specific
        meeting was labeled.
        (2) this specific meeting's date, by matching clip_id against the
        feed's <item> entries and reading <gran:pubDateParts yr= mo= day=>
        -- confirmed via a real San Francisco Board of Supervisors meeting
        (clip_id=52945) where the page itself has no parseable date
        anywhere (title "Board of Supervisors - Regular Meeting", no
        article:published_time meta) but the RSS item has an exact
        structured date. Falls back to parsing the item's free-text
        <pubDate> if pubDateParts is missing.
        Returns (None, None, None) if there's no view_id, the feed is
        unreachable, or nothing matches -- callers must treat every part of
        this as a best-effort enhancement, not a guaranteed source.
        """
        query = parse_qs(urlparse(url).query)
        view_id = query.get("view_id", [None])[0]
        if not view_id:
            return None, None, None

        domain = urlparse(url).netloc
        rss_url = f"https://{domain}/ViewPublisherRSS.php?view_id={view_id}&mode=video"
        try:
            async with session.get(
                rss_url, timeout=aiohttp.ClientTimeout(total=10)
            ) as response:
                if response.status != 200:
                    return None, None, None
                xml = await response.text()
        except Exception:
            return None, None, None

        jurisdiction = body = None
        title_match = re.search(r"<title>([^<]+)</title>", xml)
        if title_match:
            parts = title_match.group(1).strip().split(":", 1)
            if len(parts) == 2:
                jurisdiction = parts[0].strip() or None
                body = re.sub(r"\s*\(.*?Feed\)\s*$", "", parts[1]).strip() or None

        item_date = None
        if clip_id:
            # The RSS <link> HTML-entity-encodes its query string ("&amp;
            # clip_id=..."), so match on "clip_id=" directly rather than
            # requiring a raw "?"/"&" separator before it.
            item_match = re.search(
                rf"<item>(?:(?!</item>).)*?clip_id={re.escape(clip_id)}\b(?:(?!</item>).)*?</item>",
                xml,
                re.DOTALL,
            )
            if item_match:
                item_xml = item_match.group(0)
                parts_tag = re.search(r"<gran:pubDateParts\b[^>]*/?>", item_xml)
                if parts_tag:
                    tag = parts_tag.group(0)
                    yr = re.search(r"yr=['\"](\d{4})['\"]", tag)
                    mo = re.search(r"mo=['\"](\d{1,2})['\"]", tag)
                    day = re.search(r"day=['\"](\d{1,2})['\"]", tag)
                    if yr and mo and day:
                        item_date = f"{int(yr.group(1)):04d}-{int(mo.group(1)):02d}-{int(day.group(1)):02d}"
                if not item_date:
                    pubdate_match = re.search(r"<pubDate>([^<]+)</pubDate>", item_xml)
                    if pubdate_match:
                        item_date = GranicusAssetFinder._parse_date_string(
                            pubdate_match.group(1)
                        )

        return jurisdiction, body, item_date
