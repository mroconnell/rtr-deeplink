import json
import re
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlparse

import aiohttp

from .base import AssetFinder
from .models import ResolvedMeeting, TranscriptSegment
from ..utils.vtt_parser import (
    decode_vtt_bytes,
    dedupe_rollup_cues,
    is_likely_garbled,
    parse_vtt,
)

TARGET_LANGUAGE = "en"

_PAGE_CONFIG_RE = re.compile(r"var\s+pageConfig\s*=\s*(\{.*?\});", re.S)


class ViebitAssetFinder(AssetFinder):
    """Resolves a Viebit-hosted meeting video + transcript.

    Confirmed live (2026-08-08) as the real video platform underneath NYC
    Council's Legistar instance (legistar.council.nyc.gov). NYC's video
    links use a Telerik JS modal (`onclick="OpenTelerikWindow('Video.aspx
    ?Mode=Auto&URL={base64}&Mode2=Video', ...)"`) instead of every other
    Legistar city's plain `window.open('Video.aspx?Mode=Granicus...')` --
    but that `Video.aspx` endpoint itself does a real server-side 302
    redirect chain straight through to a Viebit `/embed/vod?v={id}` URL, no
    base64-decoding or headless browser needed. `LegistarAssetFinder`'s
    existing `allow_redirects=True` fetch already lands here directly once
    it recognizes the `OpenTelerikWindow` onclick shape (see that file).

    The embed page's plain HTML (confirmed both the outer `/vod/?v=...`
    URL the base64 decodes to, and the `/embed/vod?v=...` URL it redirects
    to, serve this identically) contains a `var pageConfig = {...};` JS
    object with everything needed, no JS execution required:
    `video.src[0].storage` + `.url` (an HLS master.m3u8), `video.
    textTracks[0].src` (a real, populated VTT caption URL -- 1748 real
    cues confirmed on a real NYC Council meeting), and `video.title`.

    **Video playback: iframe-embedded, not native `<video>`/hls.js --
    confirmed 2026-08-09 that the raw `master.m3u8` is CDN-gated and 403s
    even with realistic Referer/Origin/User-Agent headers (confirmed live
    against production too, not just this dev sandbox -- see
    BACKLOG_DONE.md), unlike Granicus's simpler, already-solved
    Referer-only 403.** Real fix, 2026-08-12: Viebit's own embed page
    (`{origin}/embed/vod?v={id}`) has no `X-Frame-Options`/
    `frame-ancestors` restricting it from being iframed, and its real
    player bundle (confirmed by pulling `lgx-videojs-plugins-*.js` and
    `vod-embedded-*.js` directly) reads a `?t={seconds}` query param on
    load and seeks there once playback starts -- the same mechanism
    YouTube's own `?start=` uses, just load-time-only (no live
    `postMessage` seek API exists in either bundle at all). `video_url`
    here is always rebuilt as that confirmed-safe `/embed/vod?v={id}`
    path (not whatever URL the fetch happened to land on, which the
    redirect chain from a Legistar delegation may or may not already be),
    and `video_format="viebit"` tells the frontend to iframe it with
    reload-based seeking rather than attempt native/hls.js playback --
    see `player.js`'s/`meeting_page.js`'s `createViebitAdapter()`. Real
    consequence of "load-time-only, no live API": there's no way to read
    the iframe's actual current playback position from outside it, so
    "currently playing" transcript highlighting and "copy link to
    current time" are deliberately disabled for this platform
    specifically (`wireSharedControls(adapter, { liveTracking: false })`)
    rather than showing a stale/wrong position -- click-to-seek (which
    only ever needs a known target time, not a read) still works fully,
    via an iframe reload.

    Captions are ALL-CAPS, two-line rolling/roll-up style (each spoken
    phrase appears in two consecutive cues -- once as the new bottom line,
    once repeated as the promoted top line in the next cue). Confirmed the
    existing `dedupe_rollup_cues()` (built for YouTube's differently-shaped
    growing-word-by-word rollup) already collapses this correctly too,
    since an exact-duplicate-text cue is just the trivial case of its
    prefix-matching merge logic -- no new dedup logic needed.
    `normalize_shouting_caption` (already called inside `parse_vtt`)
    handles the ALL-CAPS de-shouting.

    Viebit's own metadata has no city/agency field to read a jurisdiction
    from (Legistar's calendar row has it, but this adapter never sees that
    page). Rather than leave it blank or let a Legistar-delegated resolve
    fall back to the calendar row's legislative-body name ("New York City
    Council" -- a real body name, not the city+state format other
    platforms use, e.g. Swagit's `f"{city}, {state}"`), hardcode
    `_JURISDICTION` below: Viebit is confirmed used only by NYC Council
    (see ViebitAssetFinder's own class name/history), so there's no other
    real jurisdiction this could be yet. Matches this repo's "narrow fix
    until real examples exist" convention -- revisit if a second,
    non-NYC Viebit sample ever turns up. `date` comes from `dateCreated`,
    a Unix upload timestamp like YouTube's `upload_date` -- same real
    caveat: it's when the file was processed, not necessarily the exact
    meeting date.
    """

    platform_name = "viebit"
    # See the jurisdiction paragraph above -- confirmed single-jurisdiction
    # platform, not a generalizable "extract the city" rule.
    _JURISDICTION = "New York City, NY"

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

            config = self._extract_page_config(html)
            if not config:
                return ResolvedMeeting(
                    platform=self.platform_name,
                    source_url=url,
                    video_warnings=[
                        "Could not find Viebit's video configuration on this page."
                    ],
                )

            video = config.get("video") or {}
            video_url = self._build_embed_url(str(response.url), video.get("id"))
            title = video.get("title")
            date = self._format_date(video.get("dateCreated"))

            segments: List[TranscriptSegment] = []
            transcript_language: Optional[str] = None
            transcript_warnings: List[str] = []

            track = next(
                (
                    t
                    for t in (video.get("textTracks") or [])
                    if t.get("kind") == "captions" and t.get("src")
                ),
                None,
            )
            if track:
                cues = await self._fetch_vtt(session, track["src"])
                if cues:
                    segments = [TranscriptSegment(**c) for c in cues]
                    transcript_language = track.get("srclang") or TARGET_LANGUAGE
                    if transcript_language != TARGET_LANGUAGE:
                        transcript_warnings.append(
                            f"These captions appear to be in '{transcript_language}', not "
                            f"'{TARGET_LANGUAGE}'."
                        )
                    if is_likely_garbled(cues):
                        transcript_warnings.append(
                            "This transcript looks garbled at the source (not a parsing "
                            "bug on our end) -- treat it as approximate."
                        )
            if not segments:
                transcript_warnings.append("No captions found for this video.")

        return ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            title=title,
            jurisdiction=self._JURISDICTION,
            date=date,
            video_url=video_url,
            video_format="viebit" if video_url else None,
            segments=segments,
            transcript_language=transcript_language,
            transcript_warnings=transcript_warnings,
        )

    @staticmethod
    def _extract_page_config(html: str) -> Optional[dict]:
        match = _PAGE_CONFIG_RE.search(html)
        if not match:
            return None
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _build_embed_url(fetched_url: str, video_id: Optional[str]) -> Optional[str]:
        """Always rebuilds the confirmed-safe-to-iframe `/embed/vod?v={id}`
        path from the fetched page's own origin, rather than reusing
        `fetched_url` as-is -- a Legistar delegation's redirect chain may
        land on either the outer `/vod/?v=...` page or `/embed/vod?v=...`
        directly (both serve the same `pageConfig`, but only the latter is
        confirmed to have no X-Frame-Options restriction)."""
        if not video_id:
            return None
        parsed = urlparse(fetched_url)
        if not parsed.scheme or not parsed.netloc:
            return None
        return f"{parsed.scheme}://{parsed.netloc}/embed/vod?v={video_id}"

    @staticmethod
    def _format_date(unix_ts) -> Optional[str]:
        if not unix_ts:
            return None
        try:
            return datetime.fromtimestamp(int(unix_ts), tz=timezone.utc).strftime(
                "%Y-%m-%d"
            )
        except (ValueError, TypeError, OSError):
            return None

    @staticmethod
    async def _fetch_vtt(session: aiohttp.ClientSession, vtt_url: str):
        try:
            async with session.get(
                vtt_url, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status != 200:
                    return None
                raw = await response.read()
        except Exception:
            return None
        content = decode_vtt_bytes(raw)
        cues = dedupe_rollup_cues(parse_vtt(content))
        return cues or None
