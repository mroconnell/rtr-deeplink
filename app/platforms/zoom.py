"""Zoom cloud recordings shared by a government (`*.zoom.us/rec/share/...`).

Read live from the office Mac on 2026-10-16/17 (A7, `reports/wo-a7_zoom_pilot.md`): 7 of 8 government share links played without sign-in or a
passcode, each with a real MP4. Plain HTTP is enough; no browser:

1. `GET /rec/share/{token}` answers the player shell. Its `window.__data__` block names a one-time `meetingId`, and the response sets Zoom's
   session cookies (`_zm_ssid`, `cred`, `__cf_bm` and others).
2. `GET /nws/recording/1.0/play/share-info/{meetingId}?originDomain={sub}` answers `{"result": {"redirectUrl": "/rec/play/..."}}`.
3. `GET {redirectUrl}` answers the play shell, whose `window.__data__` names the `fileId`. A pasted `/rec/play/` link starts here.
4. `GET /nws/recording/1.0/play/info/{fileId}` answers the recording: `meet.topic` (the host's meeting name), `meet.meetingStartTimeStr`
   ("Jul 1, 2026 11:20 AM"), `fileStartTime` (epoch ms), `duration` (seconds), `mp4Url` (a signed `ssrweb.zoom.us` address) and, when Zoom
   made one, `transcriptUrl` (`/rec/play/vtt?type=transcript&fid=...`, a WebVTT file a plain request reads). 2 of the 8 pilot links had one.

**The video does not play on our page.** The MP4 answers 403 to a request without Zoom's session cookies, even with a Referer, and 206 with
the cookies step 1 set (checked 2026-10-17). A reader's browser has no such cookies for `ssrweb.zoom.us`, so the MP4 goes to
`server_media_url` (our transcription only, like ChampDS's VOD2) and the reader is pointed to Zoom's page. The cookies for each MP4 are kept
in-process (`media_cookie_header()`), and `media_probe._ffmpeg_input_header_args()` sends them with that MP4 only. They are short-lived
(`__cf_bm` lasts about 30 minutes; the signed address about an hour), so a transcription re-resolves first, as every path already does.

**robots.txt.** Zoom's own disallows `/rec/*` for every user agent. Ryan accepted the A7 recommendation on 2026-10-18 knowing this, on the
condition that we only ever open a recording link a government itself published, one at a time, and never discover or crawl Zoom. That
is the standing decision "The tier-3 queue is hand-approved meetings, not crawling" (BACKLOG.md): a pasted link or a queue line is a
person's approval, while Meeting Finder crawls and still honours robots.txt. Nothing here lists or walks recordings. Four or five requests
per resolve, a realistic browser User-Agent (the house rule's "compliance" case), no retries. Only `*.zoom.us`; Zoom for Government
(`zoomgov.com`, Brookline MA) has not been checked.

Not yet checked from Render. Zoom sits behind Cloudflare, which answered this Mac with no challenge; a server may be treated differently.
The government is never read from Zoom (the topic often does not name it, 3 of 8 in the pilot): it comes from the page that linked the
recording, or a pin.
"""

from __future__ import annotations

import logging
import re
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

import aiohttp

from .base import AssetFinder
from .media_probe import _DESKTOP_USER_AGENT
from .models import ResolvedMeeting, TranscriptSegment
from ..utils.vtt_parser import decode_vtt_bytes, dedupe_rollup_cues, parse_vtt

logger = logging.getLogger("rtr_deeplink.zoom")

_PATH_RE = re.compile(r"^/rec/(share|play)/([A-Za-z0-9_.\-]+)")
_DATA_FIELD_RE = r"{name}:\s*'([^']*)'"
_STREAM_ONLY_WARNING = (
    "Zoom only plays this recording on its own page, so open it there with "
    '"View original source". We read its audio for the transcript.'
)
_MEDIA_COOKIES: "OrderedDict[str, str]" = OrderedDict()
_MEDIA_COOKIES_MAX = 200


def is_zoom_recording_url(url: str) -> bool:
    """A Zoom cloud-recording share or play link (`*.zoom.us/rec/share/...`
    or `/rec/play/...`). Join links (`/j/...`) are not recordings."""
    p = urlparse(url or "")
    host = (p.hostname or "").lower()
    return (host == "zoom.us" or host.endswith(".zoom.us")) and bool(
        _PATH_RE.match(p.path or "")
    )


def media_cookie_header(media_url: str) -> Optional[str]:
    """The `Cookie` value a resolve in this process got for `media_url`, or
    None. Read by media_probe._ffmpeg_input_header_args()."""
    return _MEDIA_COOKIES.get(media_url)


def _remember_cookies(media_url: str, cookie: str) -> None:
    _MEDIA_COOKIES[media_url] = cookie
    _MEDIA_COOKIES.move_to_end(media_url)
    while len(_MEDIA_COOKIES) > _MEDIA_COOKIES_MAX:
        _MEDIA_COOKIES.popitem(last=False)


def _data_field(html: str, name: str) -> Optional[str]:
    m = re.search(_DATA_FIELD_RE.format(name=name), html or "")
    return m.group(1) if m and m.group(1) else None


def _date(result: dict) -> Optional[str]:
    """The meeting's own local date ("Jul 1, 2026 11:20 AM"), else the
    file's start time in UTC."""
    text = ((result.get("meet") or {}).get("meetingStartTimeStr") or "").strip()
    for fmt in ("%b %d, %Y %I:%M %p", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    try:
        ms = int(result.get("fileStartTime") or 0)
    except (TypeError, ValueError):
        return None
    if ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).date().isoformat()


def _duration(result: dict) -> Optional[float]:
    try:
        seconds = float(result.get("duration") or 0)
    except (TypeError, ValueError):
        return None
    return seconds if seconds > 0 else None


class ZoomAssetFinder(AssetFinder):
    platform_name = "zoom"

    async def resolve(self, url: str) -> ResolvedMeeting:
        p = urlparse(url)
        match = _PATH_RE.match(p.path or "")
        if not is_zoom_recording_url(url) or not match:
            return ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                video_warnings=[
                    "This is a Zoom link, but not a cloud recording. Paste the "
                    "recording's share link (an address with /rec/share/)."
                ],
            )
        kind, token = match.group(1), match.group(2)
        base = f"https://{p.hostname}"
        external_id = f"zoom:{token}" if kind == "share" else None
        failed = ResolvedMeeting(
            platform=self.platform_name,
            source_url=url,
            external_id=external_id,
            video_warnings=["Could not load this Zoom recording."],
        )
        async with aiohttp.ClientSession(
            headers={"User-Agent": _DESKTOP_USER_AGENT}
        ) as session:
            play_url = url
            if kind == "share":
                page = await self._text(session, url)
                meeting_id = _data_field(page or "", "meetingId")
                if not meeting_id:
                    return failed
                info = await self._json(
                    session,
                    f"{base}/nws/recording/1.0/play/share-info/{meeting_id}",
                    params={"originDomain": (p.hostname or "").split(".")[0]},
                    referer=url,
                )
                redirect = ((info or {}).get("result") or {}).get("redirectUrl")
                if not redirect:
                    return failed
                play_url = base + redirect if redirect.startswith("/") else redirect
            play_page = await self._text(session, play_url)
            file_id = _data_field(play_page or "", "fileId")
            if not file_id:
                return failed
            data = await self._json(
                session,
                f"{base}/nws/recording/1.0/play/info/{file_id}",
                params={
                    "canPlayFromShare": "true",
                    "from": "share_recording_detail",
                    "continueMode": "true",
                    "componentName": "rec-play",
                    "originRequestUrl": url,
                },
                referer=play_url,
            )
            result = (data or {}).get("result") or {}
            if not result:
                return failed
            mp4_url = result.get("mp4Url") or result.get("viewMp4Url")
            resolved = ResolvedMeeting(
                platform=self.platform_name,
                source_url=url,
                external_id=external_id or f"zoom:file:{file_id}",
                title=((result.get("meet") or {}).get("topic") or "").strip() or None,
                date=_date(result),
                server_media_url=mp4_url,
                video_duration_seconds=_duration(result),
                video_warnings=[_STREAM_ONLY_WARNING]
                if mp4_url
                else ["We found this Zoom recording but no video file in it."],
            )
            if mp4_url:
                cookie = "; ".join(
                    f"{k}={m.value}"
                    for k, m in session.cookie_jar.filter_cookies(mp4_url).items()
                )
                if cookie:
                    _remember_cookies(mp4_url, cookie)
            vtt_path = result.get("transcriptUrl") or result.get("ccUrl")
            if vtt_path:
                cues = await self._cues(
                    session,
                    base + vtt_path if vtt_path.startswith("/") else vtt_path,
                    play_url,
                )
                if cues:
                    resolved.segments = [TranscriptSegment(**c) for c in cues]
                    resolved.transcript_language = "en"
            if not resolved.segments:
                resolved.transcript_warnings.append("No captions found for this video.")
        return resolved

    @staticmethod
    async def _text(session: aiohttp.ClientSession, url: str) -> Optional[str]:
        try:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as r:
                if r.status != 200:
                    logger.warning("zoom HTTP %s for %s", r.status, url)
                    return None
                return await r.text()
        except Exception:
            logger.warning("zoom fetch failed for %s", url, exc_info=True)
            return None

    @staticmethod
    async def _json(
        session: aiohttp.ClientSession, url: str, *, params: dict, referer: str
    ) -> Optional[dict]:
        try:
            async with session.get(
                url,
                params=params,
                headers={"Referer": referer, "Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as r:
                if r.status != 200:
                    logger.warning("zoom API HTTP %s for %s", r.status, url)
                    return None
                return await r.json(content_type=None)
        except Exception:
            logger.warning("zoom API fetch failed for %s", url, exc_info=True)
            return None

    @staticmethod
    async def _cues(session: aiohttp.ClientSession, vtt_url: str, referer: str):
        try:
            async with session.get(
                vtt_url,
                headers={"Referer": referer},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as r:
                if r.status != 200:
                    logger.warning("zoom VTT HTTP %s for %s", r.status, vtt_url)
                    return None
                raw = await r.read()
        except Exception:
            logger.warning("zoom VTT fetch failed for %s", vtt_url, exc_info=True)
            return None
        return dedupe_rollup_cues(parse_vtt(decode_vtt_bytes(raw))) or None
