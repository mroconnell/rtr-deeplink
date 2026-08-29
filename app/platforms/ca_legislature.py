import logging
import re
from typing import List, Optional

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder
from .media_scan import is_hls_url, scan_media_urls, media_type
from .models import ResolvedMeeting, TranscriptSegment
from ..utils.vtt_parser import (
    STRUCTURED_CAPTION_PARSERS,
    decode_vtt_bytes,
    detect_language_from_texts,
    is_likely_garbled,
    parse_captions_by_extension,
)

logger = logging.getLogger("rtr_deeplink.ca_legislature")


class CaliforniaLegislatureAssetFinder(AssetFinder):
    """Resolves video + captions for a California State Assembly or Senate
    media page (assembly.ca.gov/media/... or senate.ca.gov/media/...).

    Unlike every other adapter so far, both chambers self-host their own
    video infrastructure rather than using a third-party vendor: video on
    `stream.{assembly,senate}.ca.gov` (HLS, Wowza-style
    `/vod/_definst_/mp4:{path}/playlist.m3u8` URL shape -- notably the same
    URL pattern Granicus/Swagit use, just self-hosted rather than via a
    shared CDN) and captions/files on `vod.{assembly,senate}.ca.gov`. Both
    URLs are plain strings embedded directly in server-rendered HTML, so the
    shared `media_scan.scan_media_urls()` regex scan finds them without any
    chamber-specific parsing.

    Confirmed 2026-08-06 on a real Senate joint hearing (clip
    20260805_Non_Profit): captions are genuinely populated with clean,
    coherent, high-quality text -- the best signal seen across every
    platform tested this session except a couple of the cleanest Granicus
    samples. Assembly's caption host (vod.assembly.ca.gov) could not be
    reached from the dev environment used to build this (consistent DNS
    resolution failure, separate from stream.assembly.ca.gov which resolved
    fine) -- so the Assembly path is shape-verified via the identical naming
    convention, not content-verified. Should work once actually deployed
    somewhere with normal DNS.

    One caption-adjacent trap: each video also has a `masterVTT.vtt` under a
    `/thumbnails/` path -- that's a scrubber-thumbnail sprite sheet (maps
    timestamps to preview images for the seek bar), not a transcript.
    Explicitly excluded below.
    """

    platform_name = "ca_legislature"

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

        chamber = "Senate" if "senate.ca.gov" in url else "Assembly"
        jurisdiction = f"California State {chamber}"

        async with aiohttp.ClientSession(headers=self.headers) as session:
            async with session.get(
                url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response.raise_for_status()
                final_url = str(response.url)
                html = await response.text()

            soup = BeautifulSoup(html, "html.parser")
            title, date = self._extract_metadata(soup)

            media_urls = scan_media_urls(html, final_url)

            video_url, video_format = None, None
            for candidate in media_urls:
                if media_type(candidate) == "video" and is_hls_url(candidate):
                    video_url, video_format = candidate, "m3u8"
                    break
            if not video_url:
                for candidate in media_urls:
                    if media_type(candidate) == "video":
                        video_url, video_format = candidate, "mp4"
                        break
            if not video_url:
                video_warnings.append("No playable video found on this page.")

            # No longer .vtt-only (see media_scan.CAPTION_EXTENSIONS); still
            # excludes the scrubber-thumbnail sprite VTT -- see class docstring.
            caption_urls = [
                u
                for u in media_urls
                if media_type(u) == "subtitle" and "/thumbnails/" not in u.lower()
            ]

            segments: List[TranscriptSegment] = []
            transcript_language: Optional[str] = None
            if caption_urls:
                cues, fallback_text = await self._fetch_captions(
                    session, caption_urls[0]
                )
                if cues:
                    segments = [TranscriptSegment(**cue) for cue in cues]
                    transcript_language = detect_language_from_texts(
                        c.get("text") for c in cues
                    )
                    if is_likely_garbled(cues):
                        transcript_warnings.append(
                            "This transcript looks garbled at the source (not a parsing "
                            "bug on our end) -- treat it as approximate."
                        )
                elif fallback_text:
                    # No real timing available for this format -- see
                    # Granicus's resolve() for the same fallback reasoning.
                    # Never verified against a real CA Legislature sample
                    # (both chambers have only ever been observed using
                    # .vtt); see BACKLOG.md.
                    segments = [
                        TranscriptSegment(start=0.0, end=0.0, text=line)
                        for line in fallback_text.split("\n")
                        if line.strip()
                    ]
                    transcript_language = detect_language_from_texts(
                        s.text for s in segments
                    )
                    transcript_warnings.append(
                        "This meeting has captions, but in a format we can only show "
                        "as plain text, not a clickable per-line transcript."
                    )
                elif (
                    caption_urls[0].lower().split("?")[0].rsplit(".", 1)[-1]
                    in STRUCTURED_CAPTION_PARSERS
                ):
                    transcript_warnings.append(
                        "A caption file is referenced for this meeting but could not "
                        "be fetched or was empty."
                    )
                else:
                    transcript_warnings.append(
                        "This meeting has a caption file, but in a format we can't "
                        f"read at all yet — you can view it directly: {caption_urls[0]}"
                    )
            else:
                transcript_warnings.append("No caption file found for this meeting.")

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
    async def _fetch_captions(session: aiohttp.ClientSession, caption_url: str):
        """Returns (cues, fallback_text) via parse_captions_by_extension."""
        try:
            async with session.get(
                caption_url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status != 200:
                    logger.warning(
                        "CA Legislature caption fetch got HTTP %s for %s",
                        response.status,
                        caption_url,
                    )
                    return None, None
                raw = await response.read()
        except Exception:
            logger.warning(
                "CA Legislature caption fetch failed for %s",
                caption_url,
                exc_info=True,
            )
            return None, None
        content = decode_vtt_bytes(raw)
        return parse_captions_by_extension(caption_url, content)

    @staticmethod
    def _extract_metadata(soup: BeautifulSoup):
        """Handles two observed heading shapes:
        Assembly: separate <h1>Committee Name</h1> + <h2>Month D, YYYY</h2>.
        Senate:   one combined <h2>Meeting Name, Weekday, Month D, YYYY</h2>.
        Falls back to <title> if neither heading shape is found.
        """
        date_pattern = re.compile(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s*(\d{4})")

        def visible_headings(tag_name):
            return [
                h
                for h in soup.find_all(tag_name)
                if "visually-hidden" not in (h.get("class") or [])
                and h.get_text(strip=True)
            ]

        title, date = None, None
        combined_pattern = re.compile(
            r",\s*[A-Za-z]+day,\s*[A-Za-z]{3,9}\.?\s+\d{1,2},?\s*\d{4}\s*$"
        )

        # Check for the Senate-style "Title, Weekday, Month D, YYYY" combined
        # h2 first -- it's a more specific signal than any h1, and matters
        # because Senate pages have a generic page-level <h1>Media on
        # Demand</h1> that isn't the real per-meeting title (confirmed on a
        # real joint-hearing page: naively preferring h1 picked "Media on
        # Demand" instead of the actual hearing name).
        for h2 in visible_headings("h2"):
            text = h2.get_text(strip=True)
            if combined_pattern.search(text):
                title, date = CaliforniaLegislatureAssetFinder._split_title_date(text)
                break

        # Assembly-style: separate <h1>Committee Name</h1> + <h2>Month D,
        # YYYY</h2> (no combined pattern, so the above won't have matched).
        if not title:
            h1s = visible_headings("h1")
            if h1s:
                title = h1s[0].get_text(strip=True)
                for h2 in visible_headings("h2"):
                    if date_pattern.search(h2.get_text(strip=True)):
                        date = CaliforniaLegislatureAssetFinder._parse_date(
                            h2.get_text(strip=True)
                        )
                        break

        if not title:
            raw_title = soup.title.get_text(strip=True) if soup.title else None
            if raw_title:
                title = re.split(r"\s*\|\s*", raw_title)[0].strip() or None
                date = CaliforniaLegislatureAssetFinder._parse_date(raw_title)

        return title, date

    @staticmethod
    def _split_title_date(text: str):
        # "Meeting Name, Weekday, Month D, YYYY" -> split off the trailing
        # "Weekday, Month D, YYYY" as the date, keep the rest as title.
        match = re.search(
            r",\s*[A-Za-z]+day,\s*([A-Za-z]{3,9}\.?\s+\d{1,2},?\s*\d{4})\s*$", text
        )
        if match:
            title = text[: match.start()].strip().rstrip(",")
            date = CaliforniaLegislatureAssetFinder._parse_date(match.group(1))
            return title, date
        return text, CaliforniaLegislatureAssetFinder._parse_date(text)

    @staticmethod
    def _parse_date(text: str) -> Optional[str]:
        from datetime import datetime

        match = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s*(\d{4})", text)
        if not match:
            return None
        for fmt in ("%B %d %Y", "%b %d %Y"):
            try:
                return datetime.strptime(
                    f"{match.group(1)} {match.group(2)} {match.group(3)}", fmt
                ).strftime("%Y-%m-%d")
            except ValueError:
                continue
        return None
