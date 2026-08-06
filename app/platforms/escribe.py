import re
from datetime import datetime
from typing import List, Optional
from urllib.parse import quote

import aiohttp
from bs4 import BeautifulSoup
from langdetect import detect as detect_language, LangDetectException

from .base import AssetFinder
from .models import ResolvedMeeting, TranscriptSegment
from ..utils.vtt_parser import parse_vtt

TARGET_LANGUAGE = "en"
# eScribe/iSiLIVE encodes caption language in the filename itself, unlike
# Granicus's untrustworthy srclang label -- e.g. "{file}.vtt" is English,
# "{file}.fr.vtt" is French. This is the set of suffixes actually observed
# on a real Richmond, CA meeting page (2026-08-06); none were populated for
# that specific meeting (all 404), so the *shape* is confirmed but not the
# content quality.
KNOWN_LANGUAGE_SUFFIXES = [None, "fr", "es", "zh", "zh-hant", "tl"]


class EscribeAssetFinder(AssetFinder):
    """Resolves video + transcript for an eScribe meeting page.

    Unlike CivicClerk (one consistent SPA+API) or Swagit (one consistent
    server-rendered template), eScribe is purely an agenda-management
    platform -- video integration is entirely up to each city and varies a
    lot. Confirmed cases in testing (2026-08-06):
      - Richmond, CA: real video hosted on a third video infrastructure,
        iSiLIVE (video.isilive.ca / cdn1.isilive.ca), configured via a
        `<div id="isi_player" data-client_id="..." data-stream_name="...">`
        element embedded directly in the static page HTML -- no headless
        browser needed, just BeautifulSoup.
      - Perry, GA: no video/iSiLIVE integration at all -- just a plain-text
        link to a live Vimeo stream, no archive shown anywhere on the page.
    So "no video found" is an expected, common, non-error outcome for this
    platform, not a bug to chase -- this adapter must degrade gracefully
    rather than assume video is always present the way Granicus/Swagit do.
    """

    platform_name = "escribe"

    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            ),
        }

    async def resolve(self, url: str) -> ResolvedMeeting:
        video_warnings: List[str] = []
        transcript_warnings: List[str] = []

        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=30)) as response:
                response.raise_for_status()
                html = await response.text()

            soup = BeautifulSoup(html, "html.parser")
            title, date, jurisdiction = self._extract_metadata(soup)

            player = soup.select_one("#isi_player[data-client_id][data-stream_name]")
            video_url, video_format = None, None
            segments: List[TranscriptSegment] = []
            transcript_language: Optional[str] = None

            if not player:
                video_warnings.append(
                    "No video integration found on this page -- this city's eScribe "
                    "setup may only offer a live stream (e.g. Vimeo) with no archive, "
                    "or use a video platform this adapter doesn't recognize yet."
                )
            else:
                client_id = player["data-client_id"]
                stream_name = player["data-stream_name"]
                encoded_stream = quote(stream_name, safe="")
                video_url = f"https://cdn1.isilive.ca/vod/_definst_/mp4:{client_id}/{encoded_stream}/playlist.m3u8"
                video_format = "m3u8"

                candidates = []
                for suffix in KNOWN_LANGUAGE_SUFFIXES:
                    vtt_url = f"https://video.isilive.ca/{client_id}/{encoded_stream}" + (f".{suffix}" if suffix else "") + ".vtt"
                    cues = await self._fetch_vtt(session, vtt_url)
                    if cues:
                        candidates.append((vtt_url, cues, self._detect_cue_language(cues)))

                target_match = next((c for c in candidates if c[2] == TARGET_LANGUAGE), None)
                chosen = target_match or (candidates[0] if candidates else None)

                if chosen:
                    _vtt_url, cues, lang = chosen
                    segments = [TranscriptSegment(**cue) for cue in cues]
                    transcript_language = lang
                    if lang and lang != TARGET_LANGUAGE:
                        transcript_warnings.append(
                            f"These captions appear to be in '{lang}', not '{TARGET_LANGUAGE}' -- "
                            "no matching-language track was found for this meeting."
                        )
                else:
                    transcript_warnings.append(
                        "This meeting has video but no caption file was found in any "
                        "known language -- captioning doesn't appear to have been "
                        "generated for it yet."
                    )

        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            title=title,
            date=date,
            jurisdiction=jurisdiction,
            video_url=video_url,
            video_format=video_format,
            segments=segments,
            transcript_language=transcript_language,
            video_warnings=video_warnings,
            transcript_warnings=transcript_warnings,
        )

    @staticmethod
    async def _fetch_vtt(session: aiohttp.ClientSession, vtt_url: str):
        try:
            async with session.get(vtt_url, timeout=aiohttp.ClientTimeout(total=20)) as response:
                if response.status != 200:
                    return None
                content = await response.text()
        except Exception:
            return None
        cues = parse_vtt(content)
        return cues or None

    @staticmethod
    def _detect_cue_language(cues) -> Optional[str]:
        sample = " ".join(c["text"] for c in cues if c.get("text"))[:2000]
        if len(sample.strip()) < 20:
            return None
        try:
            return detect_language(sample)
        except LangDetectException:
            return None

    @staticmethod
    def _extract_metadata(soup: BeautifulSoup):
        raw_title = soup.title.get_text(strip=True) if soup.title else ""
        title, date = raw_title or None, None
        if " - " in raw_title:
            title_part, date_part = raw_title.rsplit(" - ", 1)
            title = title_part.strip() or title
            for fmt in ("%B %d, %Y", "%b %d, %Y"):
                try:
                    date = datetime.strptime(date_part.strip(), fmt).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue

        jurisdiction = None
        city_match = re.search(r"City of ([A-Za-z .]+)", soup.get_text(" ", strip=True))
        if city_match:
            jurisdiction = city_match.group(1).strip()

        return title, date, jurisdiction
