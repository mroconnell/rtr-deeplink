import html
import re
from typing import List, Optional
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder
from .models import ResolvedMeeting, TranscriptSegment
from ..utils.vtt_parser import (
    decode_vtt_bytes,
    detect_language_from_texts,
    parse_captions_by_extension,
)

# Seattle Channel's own video site (seattlechannel.org) -- confirmed live
# 2026-08-14 against two independent real meetings on the
# `/videos?videoid={id}` page shape (BACKLOG.md): x189286 ("City Council
# 8/11/2026") and x184865 ("City Council 3/3/2026"). Scoped to that exact
# shape, not the whole domain -- the older `/mayor-and-council/city-council/
# city-council-all-videos-index?videoid=...` feed page (many *other*
# meetings' videos below the requested one) and a bare `/videos` with no
# `videoid` are both already handled reasonably by generic_fallback.py's
# own JW-config scan (see BACKLOG.md's 2026-08-14 update), so this dedicated
# adapter only claims the shape it's actually been verified against.
#
# The primary video's JW Player instance is always literally
# `jwplayer('vidPlayer')` -- a fixed, hardcoded element id, confirmed
# identical across both real samples -- while any *other* video embedded
# further down the same page (a "related"/other-story clip, confirmed
# present on the x184865 sample) uses a different, per-video numeric id
# (`jw4052508`). Slicing the HTML to the "vidPlayer" block specifically,
# bounded by the `playerInstance.on('complete', ...)` call that immediately
# follows every real setup() call in this template, is what keeps this
# adapter from ever picking up an unrelated video's file/caption/title.
_VIDPLAYER_START_RE = re.compile(
    r"var\s+playerInstance\s*=\s*jwplayer\(['\"]vidPlayer['\"]\)\s*;"
)
_FILE_RE = re.compile(r"file:\s*[\"']([^\"']+\.mp4)[\"']")
_TRACK_FILE_RE = re.compile(r"tracks:\s*\[\s*\{\s*file:\s*[\"']([^\"']+)[\"']")
_GA_IDSTRING_RE = re.compile(r"idstring:\s*['\"]([^'\"]+)['\"]")
_SEEK_ITEM_RE = re.compile(
    r'<a class="seekItem"[^>]*data-seek="(\d+)"[^>]*>(.*?)</a>', re.DOTALL
)
_TRAILING_TIME_RE = re.compile(r"\s*-\s*\d{1,2}:\d{2}(?::\d{2})?$")


class SeattleChannelAssetFinder(AssetFinder):
    """Seattle Channel's own council meeting video site (seattlechannel.org).

    Single-jurisdiction platform (only Seattle, WA) -- same hardcoded-
    jurisdiction convention as slc.py, no per-customer variation to derive.
    """

    platform_name = "seattle_channel"

    async def resolve(self, url: str) -> ResolvedMeeting:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                page_html = await response.text()

        soup = BeautifulSoup(page_html, "html.parser")
        title = self._extract_title(soup)
        date = self._extract_date(soup)
        agenda_items = self._extract_agenda_items(page_html)

        block = self._vidplayer_block(page_html)
        mp4_match = _FILE_RE.search(block) if block else None
        if not mp4_match:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                title=title,
                date=date,
                jurisdiction="Seattle, WA",
                agenda_items=agenda_items,
                video_warnings=["No video found on this page."],
            )

        video_url = mp4_match.group(1)
        if video_url.startswith("//"):
            video_url = "https:" + video_url

        segments: List[TranscriptSegment] = []
        transcript_language = None
        transcript_warnings: List[str] = []
        track_match = _TRACK_FILE_RE.search(block)
        if track_match:
            caption_url = urljoin(url, track_match.group(1))
            cues = await self._fetch_captions(caption_url)
            if cues:
                segments = [TranscriptSegment(**cue) for cue in cues]
                transcript_language = detect_language_from_texts(
                    c["text"] for c in cues
                )
        if not segments:
            transcript_warnings.append("No transcript found for this event.")

        if not title:
            ga_match = _GA_IDSTRING_RE.search(block)
            title = ga_match.group(1) if ga_match else None

        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            title=title,
            date=date,
            jurisdiction="Seattle, WA",
            video_url=video_url,
            video_format="mp4",
            segments=segments,
            transcript_language=transcript_language,
            transcript_warnings=transcript_warnings,
            agenda_items=agenda_items,
        )

    @staticmethod
    def _vidplayer_block(page_html: str) -> Optional[str]:
        start = _VIDPLAYER_START_RE.search(page_html)
        if not start:
            return None
        end = page_html.find("playerInstance.on('complete'", start.end())
        if end == -1:
            end = start.end() + 4000
        return page_html[start.end() : end]

    @staticmethod
    def _extract_title(soup: BeautifulSoup) -> Optional[str]:
        if not soup.title:
            return None
        raw = soup.title.get_text(" ", strip=True)
        title = raw.split("|")[0].strip()
        return title or None

    @staticmethod
    def _extract_date(soup: BeautifulSoup) -> Optional[str]:
        meta = soup.find("meta", attrs={"name": "video_date"})
        content = meta.get("content") if meta else None
        return content.strip() if content else None

    @staticmethod
    def _extract_agenda_items(page_html: str) -> List[TranscriptSegment]:
        raw_items = []
        for match in _SEEK_ITEM_RE.finditer(page_html):
            seconds = float(match.group(1))
            text = html.unescape(
                BeautifulSoup(match.group(2), "html.parser").get_text(" ", strip=True)
            )
            text = _TRAILING_TIME_RE.sub("", text).strip()
            if text:
                raw_items.append((seconds, text))
        raw_items.sort(key=lambda item: item[0])

        agenda_items: List[TranscriptSegment] = []
        for i, (seconds, text) in enumerate(raw_items):
            end = raw_items[i + 1][0] if i + 1 < len(raw_items) else seconds
            agenda_items.append(
                TranscriptSegment(start=seconds, end=max(end, seconds), text=text)
            )
        return agenda_items

    @staticmethod
    async def _fetch_captions(caption_url: str):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    caption_url, timeout=aiohttp.ClientTimeout(total=20)
                ) as response:
                    if response.status != 200:
                        return None
                    raw = await response.read()
        except Exception:
            return None
        content = decode_vtt_bytes(raw)
        cues, _ = parse_captions_by_extension(caption_url, content)
        return cues
