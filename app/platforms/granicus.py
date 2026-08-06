import asyncio
import json
import random
import re
from datetime import datetime
from typing import List, Optional, Dict, Any
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup
from langdetect import detect as detect_language, LangDetectException

from .base import AssetFinder
from .models import ResolvedMeeting, TranscriptSegment
from ..utils.vtt_parser import parse_vtt

TARGET_LANGUAGE = "en"


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

    async def _fetch_page(self, session: aiohttp.ClientSession, url: str, max_retries: int = 3) -> str:
        last_error = None
        for attempt in range(max_retries):
            try:
                async with session.get(
                    url, headers=self.headers, allow_redirects=True,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as response:
                    if response.status >= 400:
                        raise aiohttp.ClientError(f"HTTP {response.status} for {url}")
                    return await response.text()
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

        jurisdiction = "Unknown Jurisdiction"
        netloc = urlparse(url).netloc
        domain_parts = netloc.split(".")
        if len(domain_parts) > 1 and domain_parts[0] not in ("www", "granicus"):
            candidate = domain_parts[0].replace("-", " ").title()
            if len(candidate) > 2:
                jurisdiction = candidate

        if not title:
            title = f"{jurisdiction} Meeting" + (f" - {date}" if date else "")

        return {"title": title[:500], "date": date, "jurisdiction": jurisdiction[:200]}

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

    def _extract_media_urls(self, html: str, page_url: str) -> List[str]:
        """Find media asset URLs on the page, resolved to absolute URLs.

        Bug fix vs. the original: every match is run through urljoin(page_url, ...)
        so relative paths (seen in testing, e.g. "/videos/5361/captions.vtt")
        become fetchable absolute URLs instead of silently failing downstream.
        """
        media_urls = set()

        video_id = None
        if "granicus.com/player/clip/" in page_url:
            video_id = page_url.split("/player/clip/")[1].split("?")[0].split("/")[0]
        elif "granicus.com/videos/" in page_url:
            video_id = page_url.split("/videos/")[1].split("/")[0]

        if video_id:
            domain = urlparse(page_url).netloc
            media_urls.add(f"https://{domain}/videos/{video_id}/captions.vtt")

        patterns = [
            r"https?://[^\"']+\.m3u8[^\"']*",
            r"https?://[^\"']+\.(?:mp4|mp3|wav|webm|ogg|vtt|srt)[^\"']*",
            r"src=[\"']([^\"']+\.(?:mp4|mp3|wav|webm|ogg|m3u8|vtt|srt))[\"'&]",
            r"data-src=[\"']([^\"']+\.(?:mp4|mp3|wav|webm|ogg|m3u8|vtt|srt))[\"'&]",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, html, re.IGNORECASE):
                raw = match.group(1) if match.groups() else match.group(0)
                if raw and not any(x in raw.lower() for x in ("placeholder", "logo", "icon")):
                    absolute = urljoin(page_url, raw.strip("\"'"))
                    media_urls.add(absolute)

        try:
            for json_str in re.findall(r'({[^}]*"sources"\s*:\s*\[[^}]*\][^}]*})', html, re.DOTALL):
                try:
                    data = json.loads(json_str)
                    for source in data.get("sources", []):
                        if isinstance(source, dict) and "src" in source:
                            media_urls.add(urljoin(page_url, source["src"]))
                except json.JSONDecodeError:
                    continue
        except Exception:
            pass

        return list(media_urls)

    @staticmethod
    def _media_type(url: str) -> str:
        path = urlparse(url).path.lower()
        if url.endswith(".m3u8"):
            return "video"
        if path.endswith((".mp4", ".mov", ".m4v")):
            return "video"
        if path.endswith((".mp3", ".wav", ".m4a")):
            return "audio"
        if path.endswith((".vtt", ".srt")):
            return "subtitle"
        return "unknown"

    async def resolve(self, url: str) -> ResolvedMeeting:
        warnings: List[str] = []
        async with aiohttp.ClientSession() as session:
            html = await self._fetch_page(session, url)
            soup = BeautifulSoup(html, "html.parser")
            metadata = self._extract_metadata(soup, url)
            media_urls = self._extract_media_urls(html, url)

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
                warnings.append("No playable video found on this page.")

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
                        warnings.append(f"Failed to fetch captions from {vtt_url}: {result}")
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
                    warnings.append(
                        "A caption file exists for this meeting but is empty — "
                        "captioning doesn't appear to have been generated for it."
                    )

                if chosen:
                    _vtt_url, cues, lang = chosen
                    segments = [TranscriptSegment(**cue) for cue in cues]
                    transcript_language = lang
                    if lang and lang != TARGET_LANGUAGE:
                        warnings.append(
                            f"These captions appear to be in '{lang}', not '{TARGET_LANGUAGE}' — "
                            "no matching-language track was found for this meeting."
                        )
                    if len(candidates) > 1 and not target_match:
                        other_langs = sorted({c[2] for c in candidates if c[2]})
                        warnings.append(f"Multiple caption tracks found ({other_langs}); none matched '{TARGET_LANGUAGE}'.")
            else:
                warnings.append("No caption/transcript file found on this page.")

            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                transcript_language=transcript_language,
                title=metadata["title"],
                date=metadata["date"],
                jurisdiction=metadata["jurisdiction"],
                video_url=video_url,
                video_format=video_format,
                segments=segments,
                warnings=warnings,
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
