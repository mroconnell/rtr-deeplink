import json
import logging
import re
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder
from .models import ResolvedMeeting, TranscriptSegment
from ..utils.vtt_parser import (
    decode_vtt_bytes,
    detect_language_from_texts,
    parse_captions_by_extension,
)

logger = logging.getLogger("rtr_deeplink.aurora")

# Aurora, CO's own Drupal-built video site (auroratv.org) -- found during a
# Wave 2 platform-coverage pass (see BACKLOG.md), confirmed live 2026-08-12.
# Every video page embeds its JW Player config as a plain top-level object
# inside Drupal's own `drupalSettings` JSON blob
# (`<script type="application/json" data-drupal-selector="drupal-settings-
# json">`), server-rendered -- no JS execution needed, unlike most other
# JW-Player-based sites this app has encountered. That blob's "mp4_url" is a
# real, direct, unauthenticated file served via CloudFront in front of
# Cablecast's storage (Aurora happens to use Cablecast as its underlying
# video host, the same vendor found independently on Charlotte/Detroit/
# Columbus, OH -- see BACKLOG.md), and "video_caption" is a real populated
# VTT hosted on auroratv.org's own domain, not Cablecast's -- a different,
# simpler shape than Charlotte's own `transcript.en.txt` convention, so
# this is its own adapter rather than a shared "Cablecast" one.
#
# Genuinely unconfirmed: whether auroratv.org or the CloudFront-fronted
# Cablecast storage block requests from Render's cloud IP the way several
# other sources in this app do (YouTube, Riverside County, Minneapolis
# LIMS/SLC) -- no Cloudflare/WAF signature was found in either host's
# response headers during development (plain Apache + CloudFront, same
# shape confirmed working for Charlotte's own Cablecast files), but that's
# not proof against an IP-based block specifically, which doesn't show up
# in headers at all. Needs a real live-production check before trusting
# this fully -- see BACKLOG.md.
_DRUPAL_SETTINGS_RE = re.compile(
    r'<script type="application/json" data-drupal-selector="drupal-settings-json">(.*?)</script>',
    re.DOTALL,
)
_TITLE_DATE_RE = re.compile(
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


class AuroraTvAssetFinder(AssetFinder):
    """Aurora, CO's own council meeting video site (auroratv.org)."""

    platform_name = "aurora_tv"

    async def resolve(self, url: str) -> ResolvedMeeting:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                html = await response.text()

        soup = BeautifulSoup(html, "html.parser")
        settings = self._extract_drupal_settings(html)
        title, date = self._extract_title_and_date(soup)

        mp4_url = settings.get("mp4_url") if settings else None
        if not mp4_url:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                title=title,
                date=date,
                jurisdiction="Aurora, CO",
                video_warnings=["No video found on this page."],
            )

        segments = []
        transcript_language = None
        transcript_warnings = []
        # Real gap found live 2026-08-12: the top-level "video_caption" key
        # is a server filesystem path ("/home/atowntv/public_html/..."),
        # not a fetchable URL -- only jw_data.caption_file_path is the real
        # https:// URL.
        caption_url = (settings.get("jw_data") or {}).get("caption_file_path")
        if caption_url:
            cues = await self._fetch_captions(caption_url)
            if cues:
                segments = [TranscriptSegment(**cue) for cue in cues]
                transcript_language = detect_language_from_texts(
                    c["text"] for c in cues
                )
        if not segments:
            transcript_warnings.append("No transcript found for this event.")

        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            title=title,
            date=date,
            jurisdiction="Aurora, CO",
            video_url=mp4_url,
            video_format="mp4",
            segments=segments,
            transcript_language=transcript_language,
            transcript_warnings=transcript_warnings,
        )

    @staticmethod
    def _extract_drupal_settings(html: str) -> Optional[dict]:
        match = _DRUPAL_SETTINGS_RE.search(html)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def _extract_title_and_date(soup: BeautifulSoup):
        if not soup.title:
            return None, None
        raw_title = soup.title.get_text(" ", strip=True)
        title = raw_title.split("|")[0].strip() or None
        date_match = _TITLE_DATE_RE.search(raw_title)
        date = None
        if date_match:
            month = _MONTHS.index(date_match.group(1)) + 1
            day = int(date_match.group(2))
            year = date_match.group(3)
            date = f"{year}-{month:02d}-{int(day):02d}"
        return title, date

    @staticmethod
    async def _fetch_captions(caption_url: str):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    caption_url, timeout=aiohttp.ClientTimeout(total=20)
                ) as response:
                    if response.status != 200:
                        logger.warning(
                            "Aurora caption fetch got HTTP %s for %s",
                            response.status,
                            caption_url,
                        )
                        return None
                    raw = await response.read()
        except Exception:
            logger.warning(
                "Aurora caption fetch failed for %s", caption_url, exc_info=True
            )
            return None
        content = decode_vtt_bytes(raw)
        cues, _ = parse_captions_by_extension(caption_url, content)
        return cues
