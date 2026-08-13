import re
from typing import List, Optional, Tuple
from urllib.parse import urljoin

import aiohttp
from bs4 import BeautifulSoup

from .base import AssetFinder, find_platform_link, get_finder
from .media_scan import media_type, scan_media_urls
from .models import ResolvedMeeting, TranscriptSegment
from .youtube import YouTubeAssetFinder
from ..utils.vtt_parser import decode_vtt_bytes, detect_language_from_texts, parse_captions_by_extension

_AGENDA_TEXT_RE = re.compile(r"agenda", re.IGNORECASE)

# Real page shape confirmed live 2026-08-13 across 5 real CRRMA board
# meeting URLs (crrma.org/information/meetings/board/{date}) -- see
# BACKLOG.md's "generic_fallback.py's YouTube-embed branch" entry. Only
# used as a last-resort backfill when the delegated finder's own
# metadata extraction came back completely empty (confirmed root cause:
# YouTube's yt-dlp call is blocked by anti-bot from Render's server IP,
# youtube.py's own documented gap, so `resolved.title` is None) --
# scoped to this exact shape, never assumed to generalize to other
# generic-fallback sites without their own confirmed example, same
# convention as every other adapter in this repo.
_TITLE_TAG_PIPE_RE = re.compile(r"^(.*?)\s*\|\s*(.+?)\s*$")
_URL_PATH_DATE_RE = re.compile(r"/(\d{4})-(\d{2})-(\d{2})(?:[/?]|$)")
# The notice-of-meeting body paragraph names the governing body more
# specifically ("CRRMA Board of Directors") than the bare org name in
# <title> ("Camino Real Regional Mobility Authority") -- user's own
# stated preference, 2026-08-13: "I'd expect it to have CRRMA in there
# somewhere."
_BOARD_OF_DIRECTORS_RE = re.compile(r"\b([A-Z]{2,8}\s+Board\s+of\s+Directors)\b")

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
    2. A link to any OTHER platform this app already fully supports --
       `_try_delegate_to_known_platform()` scans every `<a href>`/
       `<iframe src>`/`<video src>`/`<source src>` on the page through
       the same `detect_platform()` every URL gets classified by, and
       delegates to that adapter's real `resolve()` if one matches.
       Confirmed live 2026-08-10: Austin, TX's own council meeting pages
       (`austintexas.gov/council/{date}-reg`) don't embed video at all --
       they link out to `austintx.swagit.com/play/{id}/0/` as a plain
       `<a href>`, which `SwagitAssetFinder` already resolves correctly
       on its own. No reason to guess at a generic media-URL scan when a
       real, already-tested adapter is one link away.
    3. A direct playable media URL (`.m3u8`/`.mp4`) found by
       `media_scan.scan_media_urls()` -- the same generic scanner
       Granicus/Swagit already use, reused here rather than
       reimplemented. A caption-shaped URL (`.vtt`/`.srt`/etc.) found in
       the same scan is fetched and parsed via the same
       `parse_captions_by_extension()` dispatch every real adapter uses.
    4. Nothing found at all -- returns a real, honest "we tried and
       couldn't find anything" message, a genuinely different (more
       informative) outcome than today's blunt "we don't support this
       platform yet," which never attempted anything.

    5. A plain link to an agenda document -- any <a> tag whose visible
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
       absent. A found agenda link goes into `ResolvedMeeting.agenda_link`
       (a single raw URL) rather than forced into `agenda_items`, since
       that field implies real per-item timestamps this doesn't have --
       the user's own framing: "they don't need to be clickable
       timestamps for this fallback mode." The frontend renders it as a
       plain "we think we found an agenda here: <link>" line.

    `best_effort=True` on every result this adapter produces (see
    `ResolvedMeeting.best_effort`'s own docstring for why `platform ==
    "unknown"` alone isn't a reliable enough signal for the frontend to
    key off of) drives a dedicated, deliberately tentative UI on the
    meeting page (built 2026-08-10, live-tested against real
    never-before-seen cities -- see BACKLOG_DONE.md): a full-width "we're
    trying our best" banner, plain (non-alarmed) "we think the video/
    agenda is here: <link>" lines instead of the video/agenda_link
    fields being silently invisible or looking like a real warning, and
    a manual timestamp-entry box in place of the live-tracking playhead
    reader other platforms get (deep-linking reliability isn't confirmed
    here the way it is on a supported platform, so there's no adapter-
    driven "current time" to honestly display).

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
                best_effort=True,
            )

        agenda_link = self._find_agenda_link(html, url)

        youtube_video_id = YouTubeAssetFinder.extract_video_id(html)
        if youtube_video_id:
            resolved = await YouTubeAssetFinder.resolve_video_id(youtube_video_id, source_url=url)
            resolved.video_warnings = [_BEST_EFFORT_VIDEO_WARNING, *resolved.video_warnings]
            resolved.agenda_link = agenda_link
            # YouTubeAssetFinder.resolve_video_id() always returns
            # platform="youtube" (its own identity, unchanged, regardless
            # of caller) -- best_effort is the frontend's real signal for
            # "this came from the fallback," since checking platform ==
            # "unknown" alone would silently miss this, the *most* common
            # real outcome (a small city just embeds a YouTube video).
            resolved.best_effort = True
            self._backfill_metadata_from_page(resolved, html, url)
            return resolved

        delegated = await self._try_delegate_to_known_platform(html, url)
        if delegated:
            delegated.agenda_link = delegated.agenda_link or agenda_link
            return delegated

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

        resolved = ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            video_url=video_url,
            video_format=video_format,
            segments=segments,
            transcript_language=transcript_language,
            video_warnings=[_BEST_EFFORT_VIDEO_WARNING if video_url else _NO_VIDEO_FOUND_WARNING],
            transcript_warnings=transcript_warnings,
            agenda_link=agenda_link,
            best_effort=True,
        )
        self._backfill_metadata_from_page(resolved, html, url)
        return resolved

    @staticmethod
    def _backfill_metadata_from_page(resolved: ResolvedMeeting, html: str, url: str) -> None:
        """Last-resort title/jurisdiction/date fill-in for a still-empty
        `resolved.title` -- see the module-level regex comments above for
        the real confirmed page shape this targets. Deliberately only
        fires on a still-empty title, so it can never clobber a real
        title/jurisdiction a delegated finder (e.g. YouTube, when yt-dlp
        isn't blocked) already found.

        `resolved.jurisdiction` is intentionally stored as raw text
        ("El Paso, Texas", not "El Paso, TX") -- `normalize_state_suffix()`
        already runs on every ingest server-side
        (`archive/db/crud.py`'s `_find_or_create_page()`), so abbreviating
        it here too would just be redundant, not incorrect.
        """
        date_match = _URL_PATH_DATE_RE.search(url)
        if date_match and not resolved.date:
            resolved.date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"

        soup = BeautifulSoup(html, "html.parser")
        board_match = _BOARD_OF_DIRECTORS_RE.search(soup.get_text(" ", strip=True))

        org_name, jurisdiction = None, None
        title_tag = soup.title.get_text(strip=True) if soup.title else None
        if title_tag:
            pipe_match = _TITLE_TAG_PIPE_RE.match(title_tag)
            if pipe_match:
                org_name, jurisdiction = pipe_match.group(1), pipe_match.group(2)

        if not resolved.title:
            # Prefer the notice-block's own body-name phrase over the bare
            # <title>-derived org name when both are available -- user's
            # own stated preference, see the _BOARD_OF_DIRECTORS_RE
            # comment above.
            resolved.title = board_match.group(1) if board_match else org_name

        # Jurisdiction, unlike title, always prefers the page's own value
        # over whatever's already on `resolved` -- real bug found live
        # 2026-08-13 confirmed via a re-resolved CRRMA page
        # (/m/meeting-732f78): when yt-dlp isn't blocked,
        # `YouTubeAssetFinder.resolve_video_id()` unconditionally sets
        # `jurisdiction=info.get("uploader")` (youtube.py), a channel
        # name ("Camino Real Regional Mobility Authority"), not a real
        # jurisdiction -- the exact same class of bug already fixed for
        # PrimeGov (primegov.py's own resolve() unconditionally overrides
        # YouTube's uploader for the same reason). Since this branch's
        # only possible delegate is YouTubeAssetFinder, there's no other
        # legitimate source `resolved.jurisdiction` could hold here.
        if jurisdiction:
            resolved.jurisdiction = jurisdiction

    @staticmethod
    async def _try_delegate_to_known_platform(html: str, page_url: str) -> Optional[ResolvedMeeting]:
        """Uses `base.find_platform_link()` to look for a link to a
        platform this app already fully supports, and delegates to that
        adapter's own real resolve() -- e.g. a city page that just links
        out to its Swagit-hosted video as a plain <a href> rather than
        embedding it, confirmed live 2026-08-10 (Austin, TX: austintexas.
        gov/council/{date}-reg links to austintx.swagit.com/play/{id}/0/,
        a real, already-correctly-working SwagitAssetFinder target -- no
        reason to guess at a generic media-URL scan when a real, tested
        adapter is right there).

        Excludes "youtube" -- already handled above by
        `YouTubeAssetFinder.extract_video_id()`, a tighter, video-ID-
        validated check; see `find_platform_link()`'s own docstring for
        why its broader `detect_platform()`-based match would otherwise
        false-positive on a bare channel/user link.

        Any failure (a bad match that doesn't actually resolve, a
        CalendarPageError from e.g. a Legistar calendar link, network
        errors) is swallowed and treated as "no delegation possible" --
        this is a bonus attempt on top of the existing fallback logic, not
        allowed to replace an honest "found nothing" with a crash.
        """
        match = find_platform_link(html, page_url, exclude=frozenset({"youtube"}))
        if not match:
            return None
        candidate, platform = match
        try:
            finder = get_finder(platform)
            resolved = await finder.resolve(candidate)
        except Exception:
            # Covers CalendarPageError (e.g. a Legistar calendar link
            # rather than one specific meeting) same as any other resolve
            # failure -- see this method's own docstring.
            return None
        resolved.source_url = page_url
        resolved.video_warnings = [_BEST_EFFORT_VIDEO_WARNING, *resolved.video_warnings]
        resolved.best_effort = True
        return resolved

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
