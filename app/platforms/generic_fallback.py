import re
from typing import List, Optional, Tuple
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder
from .media_scan import media_type, scan_media_urls
from .models import ResolvedMeeting, TranscriptSegment
from .youtube import YouTubeAssetFinder
from ..utils.vtt_parser import decode_vtt_bytes, detect_language_from_texts, parse_captions_by_extension

_YOUTUBE_EMBED_RE = re.compile(r"(?:youtube\.com/(?:embed/|watch\?v=)|youtu\.be/)([\w-]{11})")
_AGENDA_TEXT_RE = re.compile(r"agenda", re.IGNORECASE)

_BEST_EFFORT_VIDEO_WARNING = (
    "This city isn't officially supported yet, so we're trying our best — we think we found the "
    "video below. Deep-linking to a specific moment might work here, or it might not — feel free "
    "to try the \"Go to time\" / \"Share video at\" tools, but if a link doesn't land right, going "
    "back to the original source is the safer bet."
)
_NO_VIDEO_FOUND_WARNING = (
    "This city isn't officially supported yet, so we're trying our best — but we couldn't find a "
    "video on this page automatically. You can try to request a transcript from the audio, or go "
    "straight to the original source."
)
_NO_TRANSCRIPT_WARNING = (
    "We didn't automatically find a transcript here — this city isn't officially supported yet — "
    "but you can try to request one from the audio instead."
)


def _agenda_link_message(agenda_link: str) -> str:
    return f"We think we also found a link to the agenda on this page: {agenda_link}"


class GenericFallbackAssetFinder(AssetFinder):
    """Best-effort handling for any URL `detect_platform()` doesn't
    recognize -- registered under `platform_name = "unknown"`, the exact
    string `detect_platform()` already returns for anything unmatched, so
    `get_finder("unknown")` finds this instead of every unrecognized URL
    raising `UnsupportedPlatformError` with zero attempt made. Built
    2026-08-09 directly from the user's own request: "try our best"
    instead of a flat "we don't support this yet."

    Deliberately narrow in what it attempts, in priority order:
    1. An embedded/linked YouTube video (`<iframe src="youtube.com/
       embed/...">`, or a plain `youtube.com/watch?v=...`/`youtu.be/...`
       link anywhere in the page) -- delegates to `YouTubeAssetFinder`
       for real video + real captions, the best possible outcome here
       since a huge share of small-city sites just embed a YouTube
       video with no dedicated platform at all.
    2. A direct playable media URL (`.m3u8`/`.mp4`) found by
       `media_scan.scan_media_urls()` -- the same generic scanner
       Granicus/Swagit already use, reused here rather than
       reimplemented. A caption-shaped URL (`.vtt`/`.srt`/etc.) found in
       the same scan is fetched and parsed via the same
       `parse_captions_by_extension()` dispatch every real adapter uses.
    3. Nothing found at all -- returns a real, honest "we tried and
       couldn't find anything" message, a genuinely different (more
       informative) outcome than today's blunt "we don't support this
       platform yet," which never attempted anything.

    4. A plain link to an agenda document -- any <a> tag whose visible
       text or href contains "agenda" (case-insensitive), preferring one
       that looks like a PDF if more than one matches (per the user's
       real experience triaging many small-city sites, an agenda is very
       often a standalone PDF download rather than part of the page
       itself). Deliberately NOT attempted: structured agenda-ITEM
       detection (per-topic entries with real timestamps). Every other
       adapter's item-level agenda parsing is tied to that platform's own
       known page structure (Granicus's AgendaViewer.php, CivicClerk's
       eventBookmarks, ...) -- there's no reliable generic pattern to
       reuse the way there is for media URLs or a single link, and
       guessing badly at *items* would be worse than them just being
       absent. A found agenda link is surfaced as a plain message (with
       the URL, auto-linkified by player.js's existing linkifyWarning())
       rather than forced into the `agenda_items` field, since that field
       implies real per-item timestamps this doesn't have -- the user's
       own framing: "they don't need to be clickable timestamps for this
       fallback mode."

    No frontend changes needed for any of this -- `initVideo()` already
    handles any `video_url`/`video_format` combo generically, and the
    no-transcript live-playhead deep-link tracker (built earlier, see
    BACKLOG_DONE.md) already covers "no transcript, but you can still
    link to a moment" for any video, not just ones from known platforms.

    Real, deliberate architecture note: this makes the `unsupported_
    platform` error branch in `app/main.py`'s `/api/resolve` (and its
    matching `unsupported_platform` outcome bucket in `app/db/
    outcomes.py`) effectively unreachable going forward -- every URL now
    resolves to *something*, even if that something is "no video found."
    Left in place rather than removed (a safe, conservative choice, not
    dead-code bloat) since `get_finder()` could still raise for a
    genuinely different reason in the future.
    """

    platform_name = "unknown"

    def __init__(self):
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            ),
        }

    async def resolve(self, url: str) -> ResolvedMeeting:
        try:
            async with aiohttp.ClientSession(headers=self.headers) as session:
                async with session.get(
                    url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=20)
                ) as response:
                    response.raise_for_status()
                    html = await response.text()
        except Exception:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "We don't recognize this website's platform, and couldn't even load the page "
                    "to look for a video."
                ],
            )

        agenda_link = self._find_agenda_link(html, url)

        agenda_warnings = [_agenda_link_message(agenda_link)] if agenda_link else []

        youtube_match = _YOUTUBE_EMBED_RE.search(html)
        if youtube_match:
            resolved = await YouTubeAssetFinder.resolve_video_id(youtube_match.group(1), source_url=url)
            resolved.video_warnings = [_BEST_EFFORT_VIDEO_WARNING, *resolved.video_warnings]
            resolved.agenda_warnings = agenda_warnings
            return resolved

        media_urls = scan_media_urls(html, url)
        video_url, video_format = self._pick_video_url(media_urls)

        segments: List[TranscriptSegment] = []
        transcript_language: Optional[str] = None
        caption_urls = [u for u in media_urls if media_type(u) == "subtitle"]
        if caption_urls:
            cues = await self._try_fetch_caption(caption_urls[0])
            if cues:
                segments = [TranscriptSegment(**c) for c in cues]
                transcript_language = detect_language_from_texts(c["text"] for c in cues)

        transcript_warnings = [] if segments else [_NO_TRANSCRIPT_WARNING]

        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            video_url=video_url,
            video_format=video_format,
            segments=segments,
            transcript_language=transcript_language,
            video_warnings=[_BEST_EFFORT_VIDEO_WARNING if video_url else _NO_VIDEO_FOUND_WARNING],
            transcript_warnings=transcript_warnings,
            agenda_warnings=agenda_warnings,
        )

    @staticmethod
    def _find_agenda_link(html: str, page_url: str) -> Optional[str]:
        """Best-effort: a single <a> tag whose visible text or href
        contains "agenda" (case-insensitive). Doesn't attempt to extract
        agenda *items* -- see class docstring. Prefers a PDF-looking href
        (the common real-world shape) over an HTML page, since a PDF is
        the more specific, less-likely-to-be-a-false-positive signal."""
        soup = BeautifulSoup(html, "html.parser")
        candidates = []
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not href or href.startswith("#") or href.lower().startswith("javascript:"):
                continue
            text = a.get_text(" ", strip=True)
            if _AGENDA_TEXT_RE.search(text) or _AGENDA_TEXT_RE.search(href):
                candidates.append(urljoin(page_url, href))
        if not candidates:
            return None
        for candidate in candidates:
            if candidate.lower().split("?")[0].endswith(".pdf"):
                return candidate
        return candidates[0]

    @staticmethod
    def _pick_video_url(media_urls: List[str]) -> Tuple[Optional[str], Optional[str]]:
        for candidate in media_urls:
            if media_type(candidate) == "video" and candidate.lower().endswith(".m3u8"):
                return candidate, "m3u8"
        for candidate in media_urls:
            if media_type(candidate) == "video":
                return candidate, "mp4"
        return None, None

    @staticmethod
    async def _try_fetch_caption(caption_url: str):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(caption_url, timeout=aiohttp.ClientTimeout(total=15)) as response:
                    if response.status != 200:
                        return None
                    raw = await response.read()
        except Exception:
            return None
        content = decode_vtt_bytes(raw)
        cues, _fallback_text = parse_captions_by_extension(caption_url, content)
        return cues
