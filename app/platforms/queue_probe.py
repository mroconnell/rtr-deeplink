"""Learn a queued video's duration/date/size cheaply, without downloading
it, and refuse a dead link -- so a tier-3 queue can be filtered *before*
a URL becomes a real Archive page (see BACKLOG_DONE.md's WO-143
investigation for the full per-platform measurement this was built from,
and BACKLOG.md's matching entry for the decision to build it).

Lives beside media_probe.py (not inside it -- WO-144 is deliberately not
a refactor of that module) so both the feed scripts
(scripts/feed_tier3_auto_transcription.py,
scripts/feed_granicus_auto_transcription.py) and
scripts/probe_tier3_queue.py can import one shared definition, the same
"one definition, not one per caller" reasoning CLAUDE.md already gives
for media_probe.probe_duration_and_chunk_plan().

Five real recipes, one per platform shape (WO-143's own measurements):

* **YouTube** -- `yt_dlp.YoutubeDL(skip_download=True).extract_info(...)`,
  reusing youtube.py's own android/ios/tv/web `player_client` fallback
  order. Metadata only -- this never calls `_pick_caption_track()`, so no
  caption track is ever fetched here. A "live event will begin" error and
  a removed/private video both come back as the same yt-dlp exception and
  both count as `reject-dead` here -- unlike youtube.py's own
  resolve_video_id(), which must tell them apart to decide whether to
  degrade gracefully, a queue probe just needs to know "not usable right
  now" either way.
* **HLS** (`.m3u8` -- Granicus, Swagit, Cablecast) -- one GET on the
  master playlist, one GET on the variant it names, `#EXTINF` summed.
  Confirmed live (WO-143): the master alone always reports zero segments.
* **Direct file** (`.mp4`/`.mov` -- CivicClerk) -- one HEAD for
  `Content-Length`/`Last-Modified`, plus the existing
  `media_probe.probe_duration()` (ffprobe).
* **Vimeo** -- the adapter's own public oEmbed call
  (`vimeo.com/api/oembed.json`), reused via `VimeoAssetFinder._fetch_oembed()`
  rather than a second implementation of the same request. No size signal
  exists on Vimeo at all (the real media file 403s to a non-browser
  client -- see vimeo.py's own module docstring), so `size_bytes` stays
  None here, not a guess.
* **TelVue** -- the page's own embedded `Player.setupData` JSON, read via
  `TelvueAssetFinder._extract_playlist_entry()` (same reasoning as Vimeo
  above: reuse the real parser rather than a second regex that could
  silently drift from it, the exact failure CLAUDE.md's WO-34 roll-up-
  caption note warns about for a *different* per-platform parsing task).
  `duration == 0`, or a `livestream.telvue.com` stream host, means a live
  placeholder rather than an archived recording (WO-143 hit this on both
  real TelVue samples probed) -- `reject-dead`, not a real zero-length
  meeting.

Duration is the primary signal on every platform above; size is filled in
only where a platform hands it over for free (CivicClerk's real
Content-Length, YouTube's occasional `filesize`) and is never used as a
parallel accept/reject check of its own -- WO-143 found no case where it
needed to be.
"""

import asyncio
import csv
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import aiohttp
import yt_dlp

from . import media_probe
from .base import (
    CalendarPageError,
    UnsupportedPlatformError,
    detect_platform,
    get_finder,
)
from .telvue import TelvueAssetFinder
from .vimeo import VimeoAssetFinder, parse_vimeo_video
from .youtube import YouTubeAssetFinder

logger = logging.getLogger("rtr_deeplink.queue_probe")

# Same real desktop UA media_probe.py already uses for ffmpeg/ffprobe's
# `-headers` (see that module's own docstring on why a bare request to a
# CDN like archive-stream.granicus.com can 403 a naive client) -- reused
# here, not duplicated as a second literal, so the two stay in sync.
_POLITE_UA = media_probe._DESKTOP_USER_AGENT

# yt-dlp's android/ios/tv internal clients have historically not enforced
# the "web" client's PO-token anti-bot check -- same order, same
# reasoning, as app/platforms/youtube.py's own `_extract_info()`.
_YT_PLAYER_CLIENT_ORDER = ["android", "ios", "tv", "web"]

# "Prefer meetings over nine minutes" (docs/BREADTH_SWEEP_BRIEF.md) --
# exposed as a field so a caller can rank candidates, never as a
# rejection on its own.
_OVER_NINE_MINUTES_SECONDS = 9 * 60

# Anaheim's real 8.45-hour Granicus meeting (WO-143) is the confirmed
# counterexample to a hard multi-hour ceiling -- so this flags, and still
# accepts, rather than rejecting. Matches media_probe.py's own comment
# against raising MIN_PLAUSIBLE_MEETING_SECONDS's sibling ceiling for the
# same reason.
_FLAG_LONG_SECONDS = 6 * 3600


# The append-only sidecar CSV both scripts/probe_tier3_queue.py (the
# standalone CLI) and scripts/feed_tier3_auto_transcription.py's
# _push_if_has_video() write rows to -- shared here, not defined in
# either script, specifically so neither script has to import the other
# (which would be a real circular import: probe_tier3_queue.py already
# needs feed_tier3_auto_transcription.py's QUEUE_FILE/_parse_queue_line).
DEFAULT_SIDECAR_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts"
    / "tier3_auto_transcription_queue_probe.csv"
)
SIDECAR_CSV_HEADER = [
    "url",
    "platform",
    "probe_method",
    "duration_seconds",
    "date",
    "size_bytes",
    "over_nine_minutes",
    "verdict",
    "reason",
    "probe_seconds",
    "probed_at",
    # WO-156: which code path ran this probe -- "bulk_ingest" for the
    # shared _ingest() gate (scripts/bulk_ingest.py), or the tier-3
    # feed/sweep script names that already wrote rows here before WO-156
    # existed (those keep passing no caller, which lands here as "" --
    # appended at the end, and every existing reader uses csv.DictReader
    # keyed by column name (wo150_finish_tier3.py's _load_probed_urls()),
    # so an old row with no "caller" value just reads back as an empty
    # string, not a missing column).
    "caller",
]


@dataclass
class ProbeResult:
    url: str
    platform: Optional[str]
    probe_method: Optional[str]
    duration_seconds: Optional[float]
    date: Optional[str]
    size_bytes: Optional[int]
    verdict: str  # "accept" | "reject-dead" | "reject-short" | "flag-long"
    reason: Optional[str]
    probe_seconds: float
    over_nine_minutes: bool = False


def _dead(
    url: str, platform: Optional[str], method: Optional[str], start: float, reason: str
) -> ProbeResult:
    return ProbeResult(
        url=url,
        platform=platform,
        probe_method=method,
        duration_seconds=None,
        date=None,
        size_bytes=None,
        verdict="reject-dead",
        reason=reason,
        probe_seconds=time.monotonic() - start,
        over_nine_minutes=False,
    )


def _finish(
    url: str,
    platform: Optional[str],
    method: Optional[str],
    duration: float,
    date: Optional[str],
    size_bytes: Optional[int],
    start: float,
) -> ProbeResult:
    probe_seconds = time.monotonic() - start
    over_nine = duration > _OVER_NINE_MINUTES_SECONDS
    if duration < media_probe.MIN_PLAUSIBLE_MEETING_SECONDS:
        return ProbeResult(
            url=url,
            platform=platform,
            probe_method=method,
            duration_seconds=duration,
            date=date,
            size_bytes=size_bytes,
            verdict="reject-short",
            reason=(
                f"duration {duration:.1f}s is below the "
                f"{media_probe.MIN_PLAUSIBLE_MEETING_SECONDS}s meeting-plausibility floor"
            ),
            probe_seconds=probe_seconds,
            over_nine_minutes=over_nine,
        )
    if duration > _FLAG_LONG_SECONDS:
        return ProbeResult(
            url=url,
            platform=platform,
            probe_method=method,
            duration_seconds=duration,
            date=date,
            size_bytes=size_bytes,
            verdict="flag-long",
            reason=(
                f"duration {duration / 3600:.2f}h is over the "
                f"{_FLAG_LONG_SECONDS / 3600:.0f}h flag threshold -- still accepted, "
                "a long meeting can be real (Anaheim, BACKLOG_DONE.md's WO-143 entry)"
            ),
            probe_seconds=probe_seconds,
            over_nine_minutes=over_nine,
        )
    return ProbeResult(
        url=url,
        platform=platform,
        probe_method=method,
        duration_seconds=duration,
        date=date,
        size_bytes=size_bytes,
        verdict="accept",
        reason=None,
        probe_seconds=probe_seconds,
        over_nine_minutes=over_nine,
    )


def _aiohttp_headers(source_page_url: Optional[str]) -> dict:
    if not source_page_url:
        return {"User-Agent": _POLITE_UA}
    parsed = urlparse(source_page_url)
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.netloc else None
    headers = {"User-Agent": _POLITE_UA}
    if origin:
        headers["Referer"] = f"{origin}/"
    return headers


def _date_from_http_date(value: str) -> Optional[str]:
    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    return dt.date().isoformat()


# --- YouTube ---------------------------------------------------------------


def _yt_dlp_probe(video_id: str) -> Optional[dict]:
    """Runs in a thread -- yt-dlp is synchronous. Metadata only: this
    never calls youtube.py's `_pick_caption_track()`, so no caption track
    is fetched here, matching this module's own "never the caption
    tracks" rule."""
    ydl_opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "extractor_args": {"youtube": {"player_client": _YT_PLAYER_CLIENT_ORDER}},
        "ignoreerrors": False,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(
            f"https://www.youtube.com/watch?v={video_id}", download=False
        )
        if not info:
            return None
        return {
            "duration": info.get("duration"),
            "upload_date": info.get("upload_date"),
            "release_date": info.get("release_date"),
            # Populated only for the specific low-quality progressive
            # format the android/ios/tv clients return, and only
            # sometimes -- see BACKLOG_DONE.md's WO-143 entry. A real
            # bonus when present, never something to depend on.
            "filesize": info.get("filesize"),
            "filesize_approx": info.get("filesize_approx"),
        }


def _yt_date(info: dict) -> Optional[str]:
    for key in ("upload_date", "release_date"):
        raw = info.get(key)
        if raw and len(raw) == 8 and raw.isdigit():
            return f"{raw[0:4]}-{raw[4:6]}-{raw[6:8]}"
    return None


async def _probe_youtube(
    url: str, video_url: Optional[str], start: float
) -> ProbeResult:
    video_id = YouTubeAssetFinder.extract_video_id(
        video_url or ""
    ) or YouTubeAssetFinder.extract_video_id(url)
    if not video_id:
        return _dead(
            url,
            "youtube",
            "yt-dlp-metadata",
            start,
            "could not find a YouTube video id in this URL",
        )
    try:
        info = await asyncio.to_thread(_yt_dlp_probe, video_id)
    except yt_dlp.utils.YoutubeDLError as e:
        # A scheduled-but-not-yet-live event ("This live event will begin
        # in...") and a genuinely removed/private video raise the same
        # exception family here -- both are "not usable right now" for a
        # queue probe, so both become reject-dead with the real yt-dlp
        # message as the reason. See this module's own docstring.
        return _dead(
            url, "youtube", "yt-dlp-metadata", start, f"yt-dlp: {str(e)[:200]}"
        )

    if not info or info.get("duration") is None:
        return _dead(
            url,
            "youtube",
            "yt-dlp-metadata",
            start,
            "yt-dlp returned no usable metadata (no duration)",
        )

    size = info.get("filesize") or info.get("filesize_approx")
    return _finish(
        url,
        "youtube",
        "yt-dlp-metadata",
        float(info["duration"]),
        _yt_date(info),
        int(size) if size else None,
        start,
    )


# --- Vimeo -------------------------------------------------------------


async def _probe_vimeo(url: str, video_url: Optional[str], start: float) -> ProbeResult:
    parsed = parse_vimeo_video(video_url or "") or parse_vimeo_video(url)
    if not parsed:
        return _dead(
            url, "vimeo", "vimeo-oembed", start, "could not parse a Vimeo video id"
        )
    video_id, privacy_hash = parsed

    oembed = await VimeoAssetFinder._fetch_oembed(video_id, privacy_hash)
    if not oembed:
        return _dead(
            url,
            "vimeo",
            "vimeo-oembed",
            start,
            "Vimeo oEmbed returned nothing -- likely a dead, private, or removed video",
        )

    duration = oembed.get("duration")
    if duration is None:
        return _dead(
            url, "vimeo", "vimeo-oembed", start, "Vimeo oEmbed carried no duration"
        )

    # Vimeo's own "2026-07-22 10:01:23" -- same shape vimeo.py's own
    # _upload_date() reads, reused here as a regex rather than a second
    # implementation to drift from.
    raw_upload = oembed.get("upload_date") or ""
    date = raw_upload[:10] if re.match(r"^\d{4}-\d{2}-\d{2}", raw_upload) else None

    # No size signal exists on Vimeo at all -- see this module's own
    # docstring and vimeo.py's -- so size_bytes is left blank, not guessed.
    return _finish(url, "vimeo", "vimeo-oembed", float(duration), date, None, start)


# --- TelVue --------------------------------------------------------------


async def _probe_telvue(
    url: str, video_url: Optional[str], source_page_url: Optional[str], start: float
) -> ProbeResult:
    page_url = source_page_url or url
    method = "telvue-page-json"
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": _POLITE_UA}) as session:
            async with session.get(
                page_url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status >= 400:
                    return _dead(
                        url,
                        "telvue",
                        method,
                        start,
                        f"TelVue page returned HTTP {response.status}",
                    )
                html = await response.text(errors="replace")
    except asyncio.TimeoutError:
        return _dead(url, "telvue", method, start, "TelVue page fetch timed out")
    except aiohttp.ClientError as e:
        return _dead(url, "telvue", method, start, f"TelVue page fetch failed: {e}")

    entry = TelvueAssetFinder._extract_playlist_entry(html)
    if not entry:
        return _dead(
            url,
            "telvue",
            method,
            start,
            "no Player.setupData playlist found on the TelVue page",
        )

    duration = entry.get("duration")
    file_url = entry.get("file") or video_url or ""
    host = urlparse(file_url).netloc.lower()

    if not duration or float(duration) <= 0:
        return _dead(
            url,
            "telvue",
            method,
            start,
            "TelVue duration is 0 -- a live placeholder, not an archived recording",
        )
    if "livestream.telvue.com" in host:
        return _dead(
            url,
            "telvue",
            method,
            start,
            "TelVue stream host is livestream.telvue.com -- a live placeholder, "
            "not an archived recording",
        )

    return _finish(url, "telvue", method, float(duration), None, None, start)


# --- HLS (Granicus, Swagit, Cablecast) --------------------------------


async def _get_text(
    session: aiohttp.ClientSession, url: str
) -> tuple[Optional[str], int]:
    """(text, status) -- status 0 means the request never got an HTTP
    response at all (timeout/connection error), distinct from a real
    4xx/5xx, so callers can report which one happened."""
    try:
        async with session.get(
            url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=20)
        ) as response:
            if response.status >= 400:
                return None, response.status
            return await response.text(errors="replace"), response.status
    except asyncio.TimeoutError:
        return None, 0
    except aiohttp.ClientError:
        return None, 0


def _http_dead_reason(what: str, status: int) -> str:
    if status:
        return f"{what} returned HTTP {status}"
    return f"{what} was unreachable (timeout or connection error)"


def _first_variant_url(master_text: str, master_url: str) -> Optional[str]:
    """The first rendition an `#EXT-X-STREAM-INF` master playlist names --
    confirmed live (WO-143) that the master alone carries zero `#EXTINF`
    entries on every HLS platform this queue serves; the real segment
    list lives one level down, in the variant playlist this points at."""
    lines = [line.strip() for line in master_text.splitlines()]
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF"):
            for candidate in lines[i + 1 :]:
                if candidate and not candidate.startswith("#"):
                    return urljoin(master_url, candidate)
    return None


_EXTINF_PREFIX = "#EXTINF:"


def _sum_extinf(variant_text: str) -> float:
    total = 0.0
    for line in variant_text.splitlines():
        line = line.strip()
        if not line.startswith(_EXTINF_PREFIX):
            continue
        value = line[len(_EXTINF_PREFIX) :].split(",", 1)[0].strip()
        try:
            total += float(value)
        except ValueError:
            continue
    return total


async def _probe_hls(
    url: str,
    platform: Optional[str],
    video_url: str,
    source_page_url: Optional[str],
    start: float,
) -> ProbeResult:
    method = "hls-master+variant"
    headers = _aiohttp_headers(source_page_url)
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            master_text, master_status = await _get_text(session, video_url)
            if master_text is None:
                return _dead(
                    url,
                    platform,
                    method,
                    start,
                    _http_dead_reason("HLS master playlist", master_status),
                )
            variant_url = _first_variant_url(master_text, video_url)
            if not variant_url:
                return _dead(
                    url,
                    platform,
                    method,
                    start,
                    "HLS master playlist named no variant rendition",
                )
            variant_text, variant_status = await _get_text(session, variant_url)
            if variant_text is None:
                return _dead(
                    url,
                    platform,
                    method,
                    start,
                    _http_dead_reason("HLS variant playlist", variant_status),
                )
    except aiohttp.ClientError as e:
        return _dead(url, platform, method, start, f"HLS fetch failed: {e}")

    duration = _sum_extinf(variant_text)
    if duration <= 0:
        return _dead(
            url,
            platform,
            method,
            start,
            "HLS variant playlist carried zero segments",
        )
    return _finish(url, platform, method, duration, None, None, start)


# --- Direct file (CivicClerk mp4/mov) -----------------------------------


async def _probe_direct_file(
    url: str,
    platform: Optional[str],
    video_url: str,
    source_page_url: Optional[str],
    start: float,
) -> ProbeResult:
    method = "head+ffprobe"
    size_bytes = None
    date = None
    headers = _aiohttp_headers(source_page_url)
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.head(
                video_url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status >= 400:
                    return _dead(
                        url,
                        platform,
                        method,
                        start,
                        f"HEAD on the media file returned HTTP {response.status}",
                    )
                content_length = response.headers.get("Content-Length")
                if content_length and str(content_length).isdigit():
                    size_bytes = int(content_length)
                last_modified = response.headers.get("Last-Modified")
                if last_modified:
                    date = _date_from_http_date(last_modified)
    except asyncio.TimeoutError:
        return _dead(url, platform, method, start, "HEAD on the media file timed out")
    except aiohttp.ClientError as e:
        return _dead(
            url, platform, method, start, f"HEAD on the media file failed: {e}"
        )

    duration = await media_probe.probe_duration(
        video_url, source_page_url=source_page_url or url
    )
    if duration is None or duration <= 0:
        return _dead(
            url,
            platform,
            method,
            start,
            "ffprobe could not read a duration from the media file",
        )

    return _finish(url, platform, method, duration, date, size_bytes, start)


# --- Entry point ---------------------------------------------------------


async def probe_queue_entry(
    url: str,
    *,
    video_url: Optional[str] = None,
    source_page_url: Optional[str] = None,
    platform: Optional[str] = None,
) -> ProbeResult:
    """Learn `url`'s duration/date/size without downloading media, and
    return a verdict on whether it's worth queuing.

    If `video_url` isn't given, resolves `url` through the real adapter
    first -- the same detect_platform()+get_finder()+finder.resolve()
    path scripts/feed_tier3_auto_transcription.py's `_push_if_has_video()`
    already takes -- and probes whatever `video_url` comes back. A
    resolve with no `video_url` is `reject-dead`, same as a probe that
    finds nothing to play.

    `probe_seconds` covers the whole call, including a resolve step when
    one runs -- so a resolve timeout (a real WO-143 case, Bainbridge
    Island WA) shows up honestly as this field, not hidden inside a
    separate, unrecorded step.
    """
    start = time.monotonic()
    resolved_platform = platform

    if video_url is None:
        try:
            resolved_platform = resolved_platform or detect_platform(url)
            finder = get_finder(resolved_platform)
        except UnsupportedPlatformError as e:
            return _dead(
                url, resolved_platform, "resolve", start, f"unsupported platform: {e}"
            )
        try:
            result = await finder.resolve(url)
        except CalendarPageError as e:
            return _dead(
                url,
                resolved_platform,
                "resolve",
                start,
                f"calendar page, not a single meeting: {e}",
            )
        except Exception as e:
            return _dead(
                url, resolved_platform, "resolve", start, f"resolve raised: {e}"
            )

        video_url = result.video_url
        if not source_page_url:
            source_page_url = getattr(result, "source_url", None) or url
        if not video_url:
            return _dead(
                url,
                resolved_platform,
                "resolve",
                start,
                "resolve returned no video_url",
            )

    resolved_platform = resolved_platform or detect_platform(url)
    source_page_url = source_page_url or url

    if resolved_platform == "youtube":
        return await _probe_youtube(url, video_url, start)
    if resolved_platform == "vimeo":
        return await _probe_vimeo(url, video_url, start)
    if resolved_platform == "telvue":
        return await _probe_telvue(url, video_url, source_page_url, start)

    media_path = urlparse(video_url).path.lower()
    if media_probe.is_hls(video_url):
        return await _probe_hls(
            url, resolved_platform, video_url, source_page_url, start
        )
    if media_path.endswith((".mp4", ".mov")):
        return await _probe_direct_file(
            url, resolved_platform, video_url, source_page_url, start
        )

    return _dead(
        url,
        resolved_platform,
        None,
        start,
        f"no probe recipe for this media shape: {video_url}",
    )


def append_probe_row(
    sidecar_path: Path, result: ProbeResult, *, caller: str = ""
) -> None:
    """Append one ProbeResult to the append-only sidecar CSV, writing the
    header first if the file doesn't exist yet. Shared by
    scripts/probe_tier3_queue.py and scripts/feed_tier3_auto_transcription.py
    (see DEFAULT_SIDECAR_PATH's own comment on why this lives here rather
    than in either script).

    `caller` (WO-156) names which code path ran this probe -- e.g.
    "bulk_ingest" for the shared _ingest() gate in scripts/bulk_ingest.py.
    Optional and defaults to "" so every pre-WO-156 call site (which
    passes only `sidecar_path`/`result`) keeps working unchanged."""
    is_new = not sidecar_path.exists()
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    with sidecar_path.open("a", newline="") as f:
        writer = csv.writer(f)
        if is_new:
            writer.writerow(SIDECAR_CSV_HEADER)
        writer.writerow(
            [
                result.url,
                result.platform or "",
                result.probe_method or "",
                f"{result.duration_seconds:.2f}"
                if result.duration_seconds is not None
                else "",
                result.date or "",
                result.size_bytes if result.size_bytes is not None else "",
                "1" if result.over_nine_minutes else "0",
                result.verdict,
                result.reason or "",
                f"{result.probe_seconds:.2f}",
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                caller,
            ]
        )
