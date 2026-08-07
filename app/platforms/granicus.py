import asyncio
import random
import re
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple
from urllib.parse import urlparse, parse_qs

import aiohttp
import wordninja
from bs4 import BeautifulSoup
from langdetect import detect as detect_language, LangDetectException

from .base import AssetFinder
from .media_scan import scan_media_urls, media_type
from .models import ResolvedMeeting, TranscriptSegment
from ..utils.vtt_parser import parse_vtt, is_likely_garbled

TARGET_LANGUAGE = "en"

# Governing-body keywords used to decide whether the RSS channel title's
# second half ("City Council", "New View", "All City Dockets", ...) is
# worth appending to a page-scraped title that doesn't already name a body,
# versus a generic/unhelpful channel label not worth adding as noise.
GOVERNING_BODY_KEYWORDS = ("council", "commission", "board", "committee", "hearing")

US_STATE_ABBREVIATIONS = {
    "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id", "il", "in",
    "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms", "mo", "mt", "ne", "nv",
    "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn",
    "tx", "ut", "vt", "va", "wa", "wv", "wi", "wy", "dc",
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

    async def _fetch_page(self, session: aiohttp.ClientSession, url: str, max_retries: int = 3) -> Tuple[str, str]:
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
                    url, headers=self.headers, allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status >= 400:
                        raise aiohttp.ClientError(f"HTTP {response.status} for {url}")
                    return await response.text(), str(response.url)
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = e
                if attempt == max_retries - 1:
                    raise
                await asyncio.sleep((2 ** attempt) * random.uniform(0.5, 1.5))
        raise aiohttp.ClientError(f"Failed to fetch {url}: {last_error}")

    def _extract_metadata(self, soup: BeautifulSoup, url: str) -> Dict[str, Optional[str]]:
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
        page_text = soup.get_text(" ", strip=True) + " " + (meta_content('meta[name="description"]') or "")
        body_match = re.search(r"\b(City|County|Town) of ([A-Z][A-Za-z .]{1,40})", page_text)
        if body_match:
            jurisdiction = f"{body_match.group(1)} of {body_match.group(2).strip()}"
        else:
            # Some counties are phrased the other way round on their own
            # pages ("San Diego County" rather than "County of San Diego") --
            # confirmed on a real sdcounty.granicus.com page, where the
            # City-of/County-of pattern above doesn't match at all.
            reversed_match = re.search(r"\b([A-Z][A-Za-z]+(?: [A-Z][A-Za-z]+){0,2}) (County|Parish)\b", page_text)
            if reversed_match:
                jurisdiction = f"{reversed_match.group(1).strip()} {reversed_match.group(2)}"

        netloc = urlparse(url).netloc
        domain_parts = netloc.split(".")
        if not jurisdiction and len(domain_parts) > 1 and domain_parts[0] not in ("www", "granicus"):
            candidate = self._humanize_subdomain(domain_parts[0])
            if candidate:
                jurisdiction = candidate

        jurisdiction = jurisdiction or "Unknown Jurisdiction"

        if not title:
            title = f"{jurisdiction} Meeting" + (f" - {date}" if date else "")

        return {"title": title[:500], "date": date, "jurisdiction": jurisdiction[:200]}

    @staticmethod
    def _humanize_subdomain(subdomain: str) -> Optional[str]:
        """Turn a concatenated subdomain like "sandiego" or "leaguecitytx"
        into "San Diego" / "League City, TX" -- word-segmented via wordninja
        (a lightweight, offline word-frequency segmenter) rather than the
        previous naive .title() call, which left multi-word city names
        unreadable (e.g. "sandiego" -> "Sandiego"). Strips a trailing US
        state abbreviation into a ", ST" suffix, and drops a leading
        "city of"/"county of"/"town of" since that's redundant once we're
        about to label this as the jurisdiction.
        """
        words = wordninja.split(subdomain)
        if not words:
            return None

        state_suffix = None
        if len(words) > 1 and words[-1].lower() in US_STATE_ABBREVIATIONS:
            state_suffix = words[-1].upper()
            words = words[:-1]

        while len(words) > 1 and words[0].lower() in ("city", "county", "town", "of"):
            words = words[1:]

        if not words:
            return None

        name = " ".join(w.capitalize() for w in words)
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
                for fmt in ("%Y-%m-%d", "%m-%d-%Y", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
                    try:
                        return datetime.strptime(match.group(0), fmt).strftime("%Y-%m-%d")
                    except ValueError:
                        continue
        return None

    @staticmethod
    def _extract_clip_id(page_url: str) -> Optional[str]:
        """Pull the numeric clip id out of any of Granicus's URL shapes:
        path-based /player/clip/{id}, path-based /videos/{id}/, or
        query-based ?clip_id={id} (MediaPlayer.php). Must be called with the
        post-redirect URL -- see _fetch_page's docstring.
        """
        if "granicus.com/player/clip/" in page_url:
            return page_url.split("/player/clip/")[1].split("?")[0].split("/")[0]
        if "granicus.com/videos/" in page_url:
            return page_url.split("/videos/")[1].split("/")[0]
        query = parse_qs(urlparse(page_url).query)
        return query.get("clip_id", [None])[0]

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

    async def resolve(self, url: str) -> ResolvedMeeting:
        video_warnings: List[str] = []
        transcript_warnings: List[str] = []
        async with aiohttp.ClientSession() as session:
            html, final_url = await self._fetch_page(session, url)
            soup = BeautifulSoup(html, "html.parser")
            metadata = self._extract_metadata(soup, final_url)
            media_urls = self._extract_media_urls(html, final_url)
            clip_id = self._extract_clip_id(final_url)

            # The RSS channel title (constant per view_id, distinct from each
            # meeting's own often-poor-quality title -- confirmed real
            # examples like San Diego's "Tuesday Agenda Revised Added
            # S500-S511") is the most reliable source of both jurisdiction
            # and governing-body name, when it's available at all. The RSS
            # item matched by clip_id is likewise the most reliable date
            # source when the page itself has none -- confirmed real (San
            # Francisco Board of Supervisors, clip 52945: no date anywhere
            # on the page, but a real RSS pubDate).
            channel_jurisdiction, channel_body, item_date = await self._fetch_channel_info(session, final_url, clip_id)
            if channel_jurisdiction:
                metadata["jurisdiction"] = channel_jurisdiction
            if not metadata["date"] and item_date:
                metadata["date"] = item_date
            title_has_body = metadata["title"] and any(
                kw in metadata["title"].lower() for kw in GOVERNING_BODY_KEYWORDS
            )
            body_is_meaningful = channel_body and any(
                kw in channel_body.lower() for kw in GOVERNING_BODY_KEYWORDS
            )
            if body_is_meaningful and not title_has_body and metadata["title"]:
                metadata["title"] = f"{channel_body} — {metadata['title']}"

            video_url, video_format = None, None
            for candidate in media_urls:
                if self._media_type(candidate) == "video" and candidate.lower().endswith(".m3u8"):
                    video_url, video_format = candidate, "m3u8"
                    break
            if not video_url:
                for candidate in media_urls:
                    if self._media_type(candidate) == "video":
                        video_url, video_format = candidate, "mp4"
                        break
            if not video_url:
                video_warnings.append("No playable video found on this page.")

            vtt_urls = [u for u in media_urls if self._media_type(u) == "subtitle" and u.lower().endswith(".vtt")]

            segments: List[TranscriptSegment] = []
            transcript_language: Optional[str] = None
            if vtt_urls:
                fetched = await asyncio.gather(
                    *(self._fetch_vtt(session, u) for u in vtt_urls),
                    return_exceptions=True,
                )

                # Evaluate every successfully-fetched track's *actual content*
                # language rather than trusting the page's srclang label —
                # confirmed via a real Simi Valley meeting (clip 2840) that
                # a track labeled srclang="en" was actually Spanish content.
                candidates = []  # (vtt_url, cues, detected_language)
                empty_vtt_count = 0
                for vtt_url, result in zip(vtt_urls, fetched):
                    if isinstance(result, Exception):
                        transcript_warnings.append(f"Failed to fetch captions from {vtt_url}: {result}")
                        continue
                    if not result:
                        # A real, fetchable VTT file that Granicus creates as a
                        # placeholder for every meeting page regardless of
                        # whether captioning was ever generated — confirmed by
                        # fetching several directly and finding just "WEBVTT\n\n"
                        # (8 bytes, zero cues). Distinct from no VTT reference
                        # existing on the page at all.
                        empty_vtt_count += 1
                        continue
                    candidates.append((vtt_url, result, self._detect_cue_language(result)))

                target_match = next((c for c in candidates if c[2] == TARGET_LANGUAGE), None)
                chosen = target_match or (candidates[0] if candidates else None)

                if not chosen and empty_vtt_count:
                    transcript_warnings.append(
                        "Caption file was blank, so we'll have to run this manually "
                        "for a transcript. We can run batches of meetings for "
                        "subscribed users — contact ryan@how-to-adu.com for details."
                    )

                if chosen:
                    _vtt_url, cues, lang = chosen
                    segments = [TranscriptSegment(**cue) for cue in cues]
                    transcript_language = lang
                    if lang and lang != TARGET_LANGUAGE:
                        transcript_warnings.append(
                            f"These captions appear to be in '{lang}', not '{TARGET_LANGUAGE}' — "
                            "no matching-language track was found for this meeting."
                        )
                    if len(candidates) > 1 and not target_match:
                        other_langs = sorted({c[2] for c in candidates if c[2]})
                        transcript_warnings.append(f"Multiple caption tracks found ({other_langs}); none matched '{TARGET_LANGUAGE}'.")
                    if is_likely_garbled(cues):
                        transcript_warnings.append(
                            "This transcript looks garbled at the source (not a parsing "
                            "bug on our end) — treat it as approximate. We can run a "
                            "higher-quality manual transcription for subscribed users — "
                            "contact ryan@how-to-adu.com for details."
                        )
            else:
                transcript_warnings.append("No caption/transcript file found on this page.")

            if not segments and clip_id:
                agenda_items = await self._fetch_agenda_items(session, final_url, clip_id)
                if agenda_items:
                    agenda_items.sort(key=lambda item: item[0])
                    for i, (start, title) in enumerate(agenda_items):
                        end = agenda_items[i + 1][0] if i + 1 < len(agenda_items) else start
                        segments.append(TranscriptSegment(start=start, end=max(end, start), text=title))
                    transcript_warnings.append(
                        "No transcript/captions available for this meeting — showing "
                        "agenda-item chapter markers instead, which still deep-link to "
                        "the right moment."
                    )

            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                external_id=f"granicus:{clip_id}" if clip_id else None,
                transcript_language=transcript_language,
                title=metadata["title"],
                date=metadata["date"],
                jurisdiction=metadata["jurisdiction"],
                video_url=video_url,
                video_format=video_format,
                segments=segments,
                video_warnings=video_warnings,
                transcript_warnings=transcript_warnings,
            )

    @staticmethod
    def _detect_cue_language(cues: List[Dict[str, Any]]) -> Optional[str]:
        """Detect the actual language of caption text — never trust the
        page's srclang label (it can be wrong; see the resolve() docstring
        note on Simi Valley clip 2840)."""
        sample = " ".join(c["text"] for c in cues if c.get("text"))[:2000]
        if len(sample.strip()) < 20:
            return None
        try:
            return detect_language(sample)
        except LangDetectException:
            return None

    async def _fetch_vtt(self, session: aiohttp.ClientSession, vtt_url: str) -> Optional[List[Dict[str, Any]]]:
        async with session.get(vtt_url, timeout=aiohttp.ClientTimeout(total=20)) as response:
            if response.status != 200:
                return None
            content = await response.text()
        return parse_vtt(content)

    @staticmethod
    async def _fetch_agenda_items(
        session: aiohttp.ClientSession, page_url: str, clip_id: str
    ) -> List[Tuple[float, str]]:
        """Best-effort fallback chapter markers for meetings with no usable
        transcript: Granicus's own agenda-index feature (AgendaViewer.php),
        when a customer has it turned on, renders each agenda item as
        `<a name="agenda{id}" onclick="top.SetPlayerPosition('0:{seconds}',
        null)">{title}</a>` -- confirmed live on Simi Valley and San
        Francisco (case/whitespace vary by customer template, matched
        case-insensitively via html.parser's own attribute normalization).

        Not every customer has this on: confirmed Berkeley redirects
        AgendaViewer.php to their own external site instead (empty
        cuepoints, no matches here), and Paradise Valley AZ redirects it
        to a Google Docs PDF preview (also no matches). Both simply
        return an empty list and the caller keeps its existing "no
        transcript" warning -- this is purely additive, never worse than
        not trying.

        Note SetPlayerPosition's argument isn't real H:MM:SS -- Granicus's
        own JS does `time.replace(':', '')` and parses the result as an
        integer, so '0:638' means 638 seconds, not 6 minutes 38 seconds.
        """
        domain = urlparse(page_url).netloc
        agenda_url = f"https://{domain}/AgendaViewer.php?clip_id={clip_id}&embedded=1"
        try:
            async with session.get(agenda_url, timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status != 200:
                    return []
                html = await response.text()
        except Exception:
            return []

        soup = BeautifulSoup(html, "html.parser")
        items = []
        for a in soup.find_all("a", attrs={"name": re.compile(r"^agenda\d+$")}):
            match = re.search(r"SetPlayerPosition\('0:(\d+)'", a.get("onclick") or "")
            title = a.get_text(" ", strip=True)
            if match and title:
                items.append((float(match.group(1)), title))
        return items

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
            async with session.get(rss_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
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
                xml, re.DOTALL,
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
                        item_date = GranicusAssetFinder._parse_date_string(pubdate_match.group(1))

        return jurisdiction, body, item_date
