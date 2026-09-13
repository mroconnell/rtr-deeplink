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
  a removed/private/terminated video both come back as the same yt-dlp
  exception and both still count as `reject-dead` here -- a queue probe
  just needs to know "not usable right now" either way, unlike
  youtube.py's own resolve_video_id(), which must raise a different,
  classified error to decide whether a caller should ever retry. WO-167
  (2026-09-10) does tag the `reason` column with that same classification
  (`youtube.py`'s `classify_unavailability()`) so a human reading the
  sidecar CSV can still tell them apart without changing the verdict.
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
    is_multi_gov_host,
)
from .suiteone import SuiteOneAssetFinder
from .telvue import TelvueAssetFinder
from .viebit import ViebitAssetFinder
from .vimeo import VimeoAssetFinder, parse_vimeo_video
from .wistia import (
    WistiaAssetFinder,
    _date_from_title as _wistia_date_from_title,
    _date_from_unix as _wistia_date_from_unix,
    parse_wistia_account_url,
)
from .youtube import YouTubeAssetFinder, classify_unavailability

logger = logging.getLogger("rtr_deeplink.queue_probe")

# Same real desktop UA media_probe.py already uses for ffmpeg/ffprobe's
# `-headers` (see that module's own docstring on why a bare request to a
# CDN like archive-stream.granicus.com can 403 a naive client) -- reused
# here, not duplicated as a second literal, so the two stay in sync.
_POLITE_UA = media_probe._DESKTOP_USER_AGENT

# Direct-file extensions probed via `_probe_direct_file()` (one HEAD +
# ffprobe) -- `.m4v`/`.mp3` added WO-166 (2026-09-10) alongside the
# `video_format` fallback in `probe_queue_entry()` below: a real Zoom-style
# recording or a bare `.mp3` is probed the exact same way as CivicClerk's
# `.mp4`/`.mov`. `.mp3` is audio-only, still a real queueable tier-3
# candidate -- the worker transcribes audio whether or not a video stream
# exists, same reasoning utah_pmn.py's own module docstring gives for its
# bare-file case. `.m4a` added WO-205 (2026-09-11): Utah PMN's own
# uploaded recordings are `https://www.utah.gov/pmn/files/<id>.m4a`, and
# 277 real queue lines were being rejected "no probe recipe" for that
# extension alone.
_DIRECT_FILE_EXTENSIONS = (".mp4", ".mov", ".m4v", ".mp3", ".m4a")

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

# WO-170 (2026-09-10): Ryan's rule for picking among several tier-3
# candidates from the same government, once a probe rejects the first
# one -- "check the size of that video file or its duration to ensure
# that it was at least 9 minutes long but not longer than 40 minutes...
# if all the videos were over 40 minutes, then select the shortest
# available video in the list." The lower bound reuses the existing
# "prefer meetings over nine minutes" constant above rather than a
# second literal that could drift from it.
IN_WINDOW_MIN_SECONDS = _OVER_NINE_MINUTES_SECONDS  # 540 (9 minutes)
IN_WINDOW_MAX_SECONDS = 40 * 60  # 2400 (40 minutes)


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
    # WO-170: see ProbeResult.chosen's own comment. Appended last so
    # WO-156's "caller" column above keeps its position for any reader
    # already keyed on it by name.
    "chosen",
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
    # WO-170: set by a caller AFTER select_best_probe_result() has picked
    # among several probed candidates for the same government -- True on
    # the one it picked, False (the default) on every rejected sibling
    # and on an ordinary single-candidate probe with nothing to choose
    # among. Recorded in the sidecar CSV so the funnel can show "chose
    # shorter alternative" without a second file.
    chosen: bool = False


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
        # in...") and a genuinely removed/private/terminated video raise
        # the same exception family here -- both are "not usable right
        # now" for a queue probe, so both still become reject-dead. WO-167
        # (2026-09-10) added the classified-reason prefix below (reusing
        # youtube.py's own classify_unavailability(), the same one
        # resolve_video_id()/check_permanent_failure() use, so this can
        # never drift into a second, silently-different signature list)
        # purely so a human or script reading this sidecar CSV's `reason`
        # column can tell "not yet started" apart from "gone" at a glance,
        # without parsing yt-dlp's own free-text message -- the verdict
        # itself is unchanged, still reject-dead either way. See this
        # module's own docstring.
        reason_kind = classify_unavailability(str(e))
        prefix = f"{reason_kind}: " if reason_kind else ""
        return _dead(
            url,
            "youtube",
            "yt-dlp-metadata",
            start,
            f"yt-dlp: {prefix}{str(e)[:200]}",
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


# --- SuiteOne Media ----------------------------------------------------


async def _probe_suiteone(
    url: str, page_url: str, source_page_url: Optional[str], start: float
) -> ProbeResult:
    """WO-285, 2026-09-12: `queue_probe.py` had no SuiteOne recipe at
    all, so every CivicClerk-delegated SuiteOne line (`.../web/
    Player.aspx?id=...`) was `no probe recipe for this media shape` --
    confirmed live, all 16 of Vineyard, UT's real CivicClerk lines
    (BACKLOG.md's matching entry). `SuiteOneAssetFinder` already knows
    how to turn this page into the real direct-file S3 mp4 URL (and
    duration is unknown from the page itself); reuse its `resolve()` for
    that, then hand the result to the same direct-file/ffprobe recipe
    the CivicClerk `.mp4` case already uses.

    `suiteone.py`'s `resolve()` can still raise a raw `ValueError` for a
    URL shape it can't parse at all (a separate, narrower BACKLOG.md
    entry than the one this function closes) -- caught here as
    `reject-dead` with the reason, exactly per that entry's own
    constraint, rather than letting it abort the whole probe run."""
    method = "suiteone-resolve"
    try:
        result = await SuiteOneAssetFinder().resolve(page_url)
    except Exception as e:
        return _dead(url, "suiteone", method, start, f"SuiteOne resolve raised: {e}")

    if not result.video_url:
        return _dead(
            url,
            "suiteone",
            method,
            start,
            "SuiteOne resolve found no playable video (likely a "
            "not-yet-recorded event -- var src='' on the page)",
        )

    return await _probe_direct_file(
        url, "suiteone", result.video_url, source_page_url or page_url, start
    )


# --- Wistia ----------------------------------------------------------


async def _probe_wistia(
    url: str, external_id: Optional[str], start: float
) -> ProbeResult:
    """Reads Wistia's own media JSON directly (`fast.wistia.com/embed/
    medias/{id}.json`) rather than HEAD+ffprobe-ing the real public MP4 --
    the JSON already carries a real `duration` for free (see wistia.py's
    own docstring), and it's the same request that also catches a dead/
    pruned id (`{"error": true}`, a real HTTP 200 -- confirmed live on
    several 2019/2021 RegionalWebTV archive links) before anything more
    expensive runs.

    `external_id` (`"wistia:{hashedId}"`, `ResolvedMeeting.external_id`)
    is how the hashedId reaches here when a fresh resolve just ran --
    `wistia.py`'s own `video_url` is a direct asset-delivery URL (an
    opaque content hash, `embed-ssl.wistia.com/deliveries/{hash}.bin`,
    confirmed live to carry no hashedId of its own), so unlike Vimeo's
    `video_url` (which IS the id-bearing embed URL, see `_probe_vimeo`
    above), Wistia can't recover the hashedId from `video_url` alone.
    When no fresh resolve ran (a caller passing a pre-known `video_url`
    directly), fall back to parsing `url` itself as a direct Wistia
    media URL."""
    method = "wistia-media-json"
    hashed_id = None
    if external_id and external_id.startswith("wistia:"):
        hashed_id = external_id.split(":", 1)[1]
    if not hashed_id:
        parsed = parse_wistia_account_url(url)
        if parsed and parsed[0] == "media":
            hashed_id = parsed[1]
    if not hashed_id:
        return _dead(
            url, "wistia", method, start, "could not find a Wistia media id to probe"
        )

    payload = await WistiaAssetFinder._fetch_media_json(hashed_id)
    if not payload or payload.get("error"):
        return _dead(
            url,
            "wistia",
            method,
            start,
            "Wistia media JSON reported this id as dead/pruned",
        )

    media = payload.get("media") or {}
    duration = media.get("duration")
    if not duration:
        return _dead(
            url, "wistia", method, start, "Wistia media JSON carried no duration"
        )

    date = _wistia_date_from_title(media.get("name")) or _wistia_date_from_unix(
        media.get("createdAt")
    )

    size_bytes = None
    for asset in media.get("assets") or []:
        if asset.get("public") and asset.get("size"):
            size_bytes = max(size_bytes or 0, int(asset["size"]))

    return _finish(url, "wistia", method, float(duration), date, size_bytes, start)


# --- Viebit --------------------------------------------------------------


async def _probe_viebit(
    url: str, source_page_url: Optional[str], start: float
) -> ProbeResult:
    """WO-306 (2026-09-12): the one real, confirmed gap this platform has
    had since it was built (2026-08-08) -- `viebit.py`'s own `resolve()`
    always rebuilds `video_url` as the safe-to-iframe `/embed/vod?v={id}`
    page (see that module's docstring), never the raw HLS
    `master.m3u8` its pageConfig JSON also carries, so this function's
    dispatch never sees anything HLS-shaped to hand to `_probe_hls()`
    above -- every Viebit candidate died here as "no probe recipe" even
    when the video is real and playable.

    **No duration recipe exists, and none is being added.** Confirmed
    live: the raw `master.m3u8` URL 403s even with a matching Referer/
    Origin/realistic User-Agent (the same CDN gate `viebit.py`'s own
    docstring already documents for playback) -- not merely unbuilt, a
    real wall this probe can't get past without a browser. Viebit's own
    `pageConfig` JSON carries no duration field of its own either
    (confirmed against a real sample, Delano, MN). So this probe accepts
    with `duration_seconds=None` (unknown) rather than reject-dead --
    `finish_candidate()`'s `duration = result.duration_seconds or 0.0`
    already treats an unknown duration as "never defer", which is the
    honest answer here: we genuinely don't know, not that it's short.
    The real, available signal instead is `pageConfig.hasAccess` --
    Viebit's own gate for whether this viewer can actually play the
    video -- and a JSON parse failure or an empty `video.src` catches a
    genuinely dead/removed video the same way `_probe_telvue()`'s
    "no playlist found" does.
    """
    method = "viebit-page-config"
    page_url = source_page_url or url
    try:
        async with aiohttp.ClientSession(headers={"User-Agent": _POLITE_UA}) as session:
            async with session.get(
                page_url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status >= 400:
                    return _dead(
                        url,
                        "viebit",
                        method,
                        start,
                        f"Viebit page returned HTTP {response.status}",
                    )
                html = await response.text(errors="replace")
    except asyncio.TimeoutError:
        return _dead(url, "viebit", method, start, "Viebit page fetch timed out")
    except aiohttp.ClientError as e:
        return _dead(url, "viebit", method, start, f"Viebit page fetch failed: {e}")

    config = ViebitAssetFinder._extract_page_config(html)
    if not config:
        return _dead(
            url,
            "viebit",
            method,
            start,
            "no Viebit pageConfig found on this page",
        )
    if config.get("hasAccess") is False:
        return _dead(
            url,
            "viebit",
            method,
            start,
            "Viebit pageConfig reports hasAccess=false -- not publicly playable",
        )
    video = config.get("video") or {}
    if not video.get("src"):
        return _dead(
            url,
            "viebit",
            method,
            start,
            "Viebit pageConfig has no video.src -- nothing to play",
        )

    return ProbeResult(
        url=url,
        platform="viebit",
        probe_method=method,
        duration_seconds=None,
        date=None,
        size_bytes=None,
        verdict="accept",
        reason="duration unknown -- Viebit's raw stream is CDN-gated, no duration recipe exists",
        probe_seconds=time.monotonic() - start,
        over_nine_minutes=False,
    )


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


def _size_from_headers(headers) -> Optional[int]:
    """Prefers the real total size out of `Content-Range` (a 206 partial
    response's own `Content-Length` is just the range's size, e.g. "2" for
    a 1-byte range, not the file's real size) -- falls back to
    `Content-Length` directly for a plain 200 (a HEAD response, or a GET
    whose server ignored the Range header entirely and served the whole
    file's real headers -- see `_probe_direct_file()`'s own docstring)."""
    content_range = headers.get("Content-Range")
    if content_range and "/" in content_range:
        total = content_range.rsplit("/", 1)[-1].strip()
        if total.isdigit():
            return int(total)
    content_length = headers.get("Content-Length")
    if content_length and str(content_length).isdigit():
        return int(content_length)
    return None


async def _probe_direct_file(
    url: str,
    platform: Optional[str],
    video_url: str,
    source_page_url: Optional[str],
    start: float,
) -> ProbeResult:
    """One HEAD, falling back to one ranged GET (headers read only --
    `.read()`/`.text()` never called, so no body bytes transfer even when
    the fallback fires) when HEAD fails. Confirmed live 2026-09-10
    (WO-166): a real CivicPlus DocumentCenter link (e.g. Hudson, CO's own
    `/DocumentCenter/View/6698/PC-Recording-09092026`) answers a plain
    HEAD with a genuine 404 (a real `text/html` ASP.NET error page,
    confirmed via a direct `curl -I`) while the SAME URL answers a GET --
    with or without a `Range` header, this server ignores Range entirely
    and always serves the real file's full headers (`Content-Type:
    application/octet-stream`, the real `Content-Length`, `Content-
    Disposition`) with status 200, never 206. Without this fallback, 6 of
    this WO's own 7 confirmed direct-media governments would misprobe as
    `reject-dead` even though `resolve()` correctly found real, playable
    video on every one of them."""
    method = "head+ffprobe"
    size_bytes = None
    date = None
    headers = _aiohttp_headers(source_page_url)
    try:
        async with aiohttp.ClientSession(headers=headers) as session:
            async with session.head(
                video_url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                status = response.status
                response_headers = response.headers

            if status >= 400:
                method = "ranged-get+ffprobe"
                async with session.get(
                    video_url,
                    allow_redirects=True,
                    headers={"Range": "bytes=0-0"},
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as response:
                    status = response.status
                    response_headers = response.headers

            if status >= 400:
                return _dead(
                    url,
                    platform,
                    method,
                    start,
                    f"HEAD/ranged-GET on the media file returned HTTP {status}",
                )
            size_bytes = _size_from_headers(response_headers)
            last_modified = response_headers.get("Last-Modified")
            if last_modified:
                date = _date_from_http_date(last_modified)
    except asyncio.TimeoutError:
        return _dead(
            url, platform, method, start, "HEAD/ranged-GET on the media file timed out"
        )
    except aiohttp.ClientError as e:
        return _dead(
            url,
            platform,
            method,
            start,
            f"HEAD/ranged-GET on the media file failed: {e}",
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
    video_format: Optional[str] = None,
) -> ProbeResult:
    """Learn `url`'s duration/date/size without downloading media, and
    return a verdict on whether it's worth queuing.

    `video_format`, when a caller already has a resolved ResolvedMeeting
    (and so also passes `video_url=` explicitly, skipping the resolve
    step below), is the same WO-166 fallback signal the internal-resolve
    path already fills in from `result.video_format` -- needed because a
    direct-media URL (e.g. a CivicPlus DocumentCenter link whose real
    filename only ever showed up in the response's Content-Disposition
    header) commonly carries no extension in the URL itself. Without this,
    a caller like `scripts/wo169_probe_rejected_rerun.py`'s
    `_real_probe_hook()` -- which already has `result.video_url` and calls
    this with it, skipping the internal resolve -- would never learn the
    format and this WO's own real, confirmed cases would misprobe as
    `reject-dead` ("no probe recipe for this media shape") even though
    `resolve()` correctly found them.

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
    external_id = None
    # A bare direct-media URL (WO-166, 2026-09-10) commonly carries no
    # extension of its own at all -- e.g. a CivicPlus DocumentCenter link
    # whose real filename only ever showed up in the response's
    # Content-Disposition header, not the URL path (see generic_fallback.
    # py's own `_classify_direct_media()` for where this is first
    # detected). `video_format`, when the adapter set one, is the fallback
    # signal the URL-suffix check below can't provide on its own -- a
    # caller-supplied value (see this function's own docstring) always
    # wins over the resolve step's, though in practice no caller passes
    # both `video_url=` and `video_format=` together today.

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
        external_id = getattr(result, "external_id", None)
        video_format = video_format or getattr(result, "video_format", None)
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

    # WO-205 (2026-09-11): dispatch on what the video IS, not only on the
    # page's platform -- a CivicWeb or PrimeGov page resolves to a YouTube
    # embed, and 41 real CivicWeb queue lines were rejected "no probe
    # recipe" for exactly that shape.
    if (
        resolved_platform == "youtube"
        or video_format == "youtube"
        or YouTubeAssetFinder.extract_video_id(video_url or "")
    ):
        return await _probe_youtube(url, video_url, start)
    if resolved_platform == "vimeo" or video_format == "vimeo":
        return await _probe_vimeo(url, video_url, start)
    if resolved_platform == "telvue":
        return await _probe_telvue(url, video_url, source_page_url, start)
    if resolved_platform == "wistia":
        return await _probe_wistia(url, external_id, start)
    if resolved_platform == "viebit" or video_format == "viebit":
        return await _probe_viebit(url, source_page_url, start)
    # WO-205's own "dispatch on what the video IS" reasoning above
    # applies here too -- a CivicClerk event delegates to a SuiteOne
    # player page (`.../web/Player.aspx?id=...`), so `video_url` carries
    # a suiteonemedia.com host even though `resolved_platform` is
    # "civicclerk", not "suiteone".
    if (
        resolved_platform == "suiteone"
        or "suiteonemedia.com" in urlparse(video_url or "").netloc.lower()
    ):
        return await _probe_suiteone(url, video_url, source_page_url, start)

    media_path = urlparse(video_url).path.lower()
    if media_probe.is_hls(video_url):
        return await _probe_hls(
            url, resolved_platform, video_url, source_page_url, start
        )
    if media_path.endswith(_DIRECT_FILE_EXTENSIONS) or (
        video_format and f".{video_format.lower()}" in _DIRECT_FILE_EXTENSIONS
    ):
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
                "1" if result.chosen else "0",
            ]
        )


# --- WO-170 selection among several probed candidates ---------------------


def is_plausible(result: ProbeResult) -> bool:
    """True for a verdict that WO-170's selection can choose from at all.
    `reject-dead`/`reject-short` are never selectable -- the standing
    dead-link rule and the 60-second meeting-plausibility floor both stay
    absolute. `flag-long` (WO-143's real 8.45-hour Anaheim meeting) stays
    selectable, same as it's always been accepted outright."""
    return result.verdict in ("accept", "flag-long")


def select_best_probe_result(
    candidates: list[ProbeResult],
) -> Optional[ProbeResult]:
    """Ryan's 2026-09-10 rule (BACKLOG_DONE.md's WO-170 entry): given
    several tier-3 candidates already probed for one government, in the
    same newest-first order every resolve_seed() candidate loop already
    searches in (`candidates[i].url` is that candidate's own address --
    every probe_queue_entry() call already sets `.url` to the url it was
    asked to probe), prefer the newest one whose duration falls in
    [IN_WINDOW_MIN_SECONDS, IN_WINDOW_MAX_SECONDS] (9 to 40 minutes). If
    none does -- every plausible candidate is either under that window or
    over 40 minutes -- fall back to the single shortest plausible
    candidate ("if all the videos were over 40 minutes, then select the
    shortest available video in the list," Ryan's own words, applied to
    the whole plausible set rather than only the over-40-minutes case, so
    a mix of too-short and too-long candidates still resolves to one
    answer instead of none).

    Returns None when nothing here is selectable at all (every candidate
    dead or below the floor) -- the caller reports rejected_by_probe.
    `candidates` may be empty (no tier-3 candidate needed probing, e.g.
    every one had real captions) -- also returns None then.
    """
    plausible = [
        r for r in candidates if is_plausible(r) and r.duration_seconds is not None
    ]
    if not plausible:
        return None
    for r in plausible:
        if IN_WINDOW_MIN_SECONDS <= r.duration_seconds <= IN_WINDOW_MAX_SECONDS:
            return r
    return min(plausible, key=lambda r: r.duration_seconds)


# --- WO-224 shared finish step ---------------------------------------------
#
# Every wo1XX_finish_tier3*.py script (WO-147, WO-149, WO-150, WO-152,
# WO-183, WO-191, WO-216) takes an already-probed-or-probeable tier-3
# candidate and decides: queue it, pin it, defer it, or drop it. Four of
# those seven (WO-150/183/191/216) share one real bug (WO-216's own
# BACKLOG.md entry, "Ship next", moved to BACKLOG_DONE.md by WO-224): when
# a candidate's URL was already sitting in the shared probe sidecar
# (DEFAULT_SIDECAR_PATH), the per-script "already probed, skipping fetch"
# branch skipped the row entirely -- it never looked at what the cached
# verdict actually WAS, so a real accept sitting in the sidecar from an
# earlier/parallel run was silently dropped: never queued, never pinned.
# Confirmed live on WO-216's own run: 38 of 63 candidates hit this branch,
# 4 real accept-verdict videos and 5 pins were lost and had to be added by
# hand afterward.
#
# The fix is this module, not seven per-script patches: cached_verdict()
# reads what the sidecar already knows (and logs it, so a caller can see
# WHY a candidate skipped the network), and finish_candidate() is the one
# place a probe verdict (fresh or cached) turns into a queue line, a pin,
# or a deferred-file line. Every finish script should route its per-row
# decision through this, not reimplement it -- see docs/COVERAGE_HANDOVER.
# md §4's sweep-pattern paragraph.

TIER3_QUEUE_FILE = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts"
    / "tier3_auto_transcription_queue.txt"
)
TENANT_OVERRIDES_CSV = (
    Path(__file__).resolve().parent.parent.parent
    / "app"
    / "utils"
    / "jurisdiction_data"
    / "tenant_overrides.csv"
)
TIER3_LONG_MEETINGS_DEFERRED_FILE = (
    Path(__file__).resolve().parent.parent.parent
    / "scripts"
    / "tier3_long_meetings_deferred.txt"
)
DEFERRED_FILE_HEADER = (
    "# Long tier-3 meetings (>90 min) swapped out of the queue for a "
    "shorter meeting from the same government; re-queue later for depth.\n"
    "# url<TAB>source_url<TAB>gov_id<TAB>jurisdiction<TAB>duration<TAB>title "
    "-- gov_id blank when the identity ladder declined; probe rows stay in "
    "tier3_auto_transcription_queue_probe.csv.\n"
)

# WO-205/WO-212's rule: a tier-3 candidate whose duration is over 90
# minutes never earns a queue line at all -- it goes straight to the
# deferred file instead of being queued and swapped out again later (the
# original WO-205 pass had to do exactly that swap-back-out after the
# fact; this constant lets a finish step skip the round trip). Distinct
# from `_FLAG_LONG_SECONDS` (6 hours) above, which is `probe_queue_entry`'s
# own "still accept, but flag it" ceiling -- a `flag-long` verdict is
# always also over this lower, 90-minute threshold, so it always lands in
# the deferred file, never the queue.
DEFER_OVER_SECONDS = 90 * 60

_ACCEPT_VERDICTS = ("accept", "flag-long")

PIN_CSV_FIELDS = ["tenant_host", "match", "gov_id", "strength", "source", "evidence"]


def _format_hms(seconds: float) -> str:
    """`3:36:14` / `9:07` -- the exact shape
    `tier3_long_meetings_deferred.txt` already carries (confirmed against
    the real file's own rows), reusing
    `find_tier3_short_meeting_substitutes.py`'s own `hms()` logic rather
    than a second implementation that could drift from it."""
    total = int(round(seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _first_field_urls(path: Path) -> set[str]:
    """The set of URLs already present as the first TAB-field of every
    non-blank, non-comment line in a plain queue/deferred text file --
    the same key `tests/test_transcription_queue_files.py`'s own `_rows()`
    and `wo134_confirmed_hits_ingest.py`'s `_existing_tier3_queue_urls()`
    read."""
    urls: set[str] = set()
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.add(line.split("\t", 1)[0])
    return urls


def is_queued(meeting_url: str, *, queue_path: Path = TIER3_QUEUE_FILE) -> bool:
    return meeting_url in _first_field_urls(queue_path)


def is_deferred(
    meeting_url: str, *, deferred_path: Path = TIER3_LONG_MEETINGS_DEFERRED_FILE
) -> bool:
    return meeting_url in _first_field_urls(deferred_path)


def append_queue_line(
    meeting_url: str,
    source_url: Optional[str] = None,
    *,
    queue_path: Path = TIER3_QUEUE_FILE,
) -> bool:
    """Appends `meeting_url[\\tsource_url]` to the tier-3 queue file --
    the exact line shape every wo1XX_finish_tier3*.py script already
    writes (`url<TAB>source_url` when the source page differs from the
    video URL itself, a bare `url` otherwise). Dedupe-checked against the
    file's current contents first (same rule
    `wo134_confirmed_hits_ingest.py`'s `_existing_tier3_queue_urls()`
    enforces). Returns True only when a new line was actually written --
    never rewrites or reorders an existing line, append-only throughout."""
    if meeting_url in _first_field_urls(queue_path):
        return False
    line = (
        f"{meeting_url}\t{source_url}"
        if source_url and source_url != meeting_url
        else meeting_url
    )
    queue_path.parent.mkdir(parents=True, exist_ok=True)
    with queue_path.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    return True


def append_deferred_line(
    meeting_url: str,
    *,
    source_url: str = "",
    gov_id: str = "",
    jurisdiction: str = "",
    duration_seconds: Optional[float] = None,
    title: str = "",
    deferred_path: Path = TIER3_LONG_MEETINGS_DEFERRED_FILE,
) -> bool:
    """Parks a long (over DEFER_OVER_SECONDS) tier-3 candidate in
    `tier3_long_meetings_deferred.txt` instead of the real queue, in the
    file's own real column order (confirmed against its current rows):
    `url\\tsource_url\\tgov_id\\tjurisdiction\\tduration\\ttitle`, blanks
    allowed for any column but the url and duration. Dedupe-checked
    against the file's current URLs, append-only, writes the file's own
    header comment only when the file doesn't exist yet. Returns True
    only when a new line was actually written."""
    if meeting_url in _first_field_urls(deferred_path):
        return False
    duration = _format_hms(duration_seconds) if duration_seconds is not None else ""
    line = "\t".join(
        [
            meeting_url,
            source_url or "",
            gov_id or "",
            jurisdiction or "",
            duration,
            (title or "").replace("\t", " "),
        ]
    )
    is_new = not deferred_path.exists()
    deferred_path.parent.mkdir(parents=True, exist_ok=True)
    with deferred_path.open("a", encoding="utf-8") as f:
        if is_new:
            f.write(DEFERRED_FILE_HEADER)
        f.write(line + "\n")
    return True


def _read_pin_keys(pins_path: Path) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    if pins_path.exists():
        with pins_path.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                keys.add((r.get("tenant_host", ""), r.get("match", "")))
    return keys


def write_pin_row(
    *,
    host: str,
    match: str,
    gov_id: str,
    strength: str = "fallback",
    source: str = "",
    evidence: str = "",
    pins_path: Path = TENANT_OVERRIDES_CSV,
) -> bool:
    """Appends one `tenant_overrides.csv` pin, deduped against the file's
    current (tenant_host, match) pairs -- the same key every existing
    finish script's own `_apply_pin_row()`/`_write_pin()` already checks.
    Returns True only when a new row was actually written. A blank
    `host`/`gov_id` is refused outright. A blank `match` is refused only
    on a `MULTI_GOV_HOSTS` host (WO-210's rule -- a blank match there
    keys every unidentified video on the whole host to one government);
    on an ordinary single-tenant host (a Viebit/Cablecast/TelVue
    subdomain, one government per tenant) a blank match is exactly what
    the loader (`registry._load_tenant_overrides()`) already accepts and
    every existing single-tenant pin in the committed file already uses
    (`delano.viebit.com,,us:place:2715454,...`) -- found live 2026-09-12
    (WO-307) when this function silently refused to pin a real
    already-queued single-tenant Viebit government (buffalo.viebit.com)
    for exactly this reason."""
    if not host or not gov_id:
        return False
    if not match and is_multi_gov_host(host):
        return False
    existing = _read_pin_keys(pins_path)
    if (host, match) in existing:
        return False
    is_new = not pins_path.exists()
    pins_path.parent.mkdir(parents=True, exist_ok=True)
    with pins_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=PIN_CSV_FIELDS, lineterminator="\n")
        if is_new:
            writer.writeheader()
        writer.writerow(
            {
                "tenant_host": host,
                "match": match,
                "gov_id": gov_id,
                "strength": strength or "fallback",
                "source": source or "",
                "evidence": evidence or f"tier-3 probe accept, gov_id={gov_id}",
            }
        )
    return True


def parse_pin_row(pin_row: Optional[str]) -> Optional[dict]:
    """Parses the pipe-delimited `host|match|gov_id|strength|source|
    evidence` shape the newer access-ladder sweeps write (WO-183/WO-191/
    WO-216's own `pin_row` CSV column) into the field names
    `write_pin_row()` takes. Returns None for a blank/malformed row (fewer
    than 6 fields, or a blank host/gov_id) rather than raising -- same
    tolerance every existing `_apply_pin_row()`/`_write_pin()` copy
    already has for a malformed row.

    A blank `match` is NOT rejected here (WO-321, 2026-09-12): it is
    exactly the shape a single-tenant host's pin_row legitimately has
    (`bedfordoh.primegov.com||us:county:39035|...` -- one government per
    tenant, no discriminator needed), and `write_pin_row()` already
    accepts a blank match for anything that isn't a `MULTI_GOV_HOSTS`
    host (fixed WO-307 after `buffalo.viebit.com` hit the same gap this
    function still had). Before this fix, a caller going through
    `parse_pin_row()` (unlike one calling `write_pin_row()` directly)
    silently dropped every single-tenant pin with a blank match instead
    of writing it -- `write_pin_row()`'s own multi-gov-host check still
    applies downstream, so a blank match on an actual shared host is
    still refused, just one level down from here.

    WO-150's own pending rows use a different, older
    `key=value;key=value` shape -- not handled here; a caller still
    producing that shape parses it itself and calls `write_pin_row()`
    directly with the parsed fields (see `wo150_finish_tier3.py`)."""
    if not pin_row:
        return None
    parts = pin_row.split("|", 5)
    if len(parts) < 6:
        return None
    host, match, gov_id, strength, source, evidence = parts
    if not host or not gov_id:
        return None
    return {
        "host": host,
        "match": match,
        "gov_id": gov_id,
        "strength": strength,
        "source": source,
        "evidence": evidence,
    }


def cached_verdict(
    meeting_url: str, *, sidecar_path: Path = DEFAULT_SIDECAR_PATH
) -> Optional[ProbeResult]:
    """The most recently-written sidecar row for `meeting_url`, as a
    `ProbeResult`, or None if this URL has never been probed.

    "Most recent" matters because a URL can legitimately appear more than
    once in the append-only sidecar (a re-probe after a platform fix --
    WO-166/WO-205's own extension additions are two real examples) -- the
    last row written is the current understanding, the same way a human
    skimming the CSV from the bottom would read it.

    This is the fix for the bug WO-224 exists to close: every
    `wo1XX_finish_tier3*.py` copy's own "already probed, skipping fetch"
    branch checked only THAT a row existed for this URL, never what its
    verdict WAS -- so a real `accept` sitting in the sidecar from an
    earlier run got treated exactly like a `reject-dead`, silently. Logs
    the cached verdict/reason/duration/probed_at at INFO so a caller (or
    a human reading its output) can see why a candidate skipped the
    network, instead of a bare "skipping fetch"."""
    if not sidecar_path.exists():
        return None
    match = None
    with sidecar_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("url") == meeting_url:
                match = row
    if match is None:
        return None

    duration_raw = match.get("duration_seconds")
    size_raw = match.get("size_bytes")
    result = ProbeResult(
        url=match["url"],
        platform=match.get("platform") or None,
        probe_method=match.get("probe_method") or None,
        duration_seconds=float(duration_raw)
        if duration_raw not in (None, "")
        else None,
        date=match.get("date") or None,
        size_bytes=int(size_raw) if size_raw not in (None, "") else None,
        verdict=match.get("verdict", ""),
        reason=match.get("reason") or None,
        probe_seconds=float(match.get("probe_seconds") or 0.0),
        over_nine_minutes=match.get("over_nine_minutes") == "1",
        chosen=match.get("chosen") == "1",
    )
    logger.info(
        "cached_verdict: %s -- verdict=%s reason=%r duration=%ss probed_at=%s (sidecar=%s)",
        meeting_url,
        result.verdict,
        result.reason,
        result.duration_seconds,
        match.get("probed_at", ""),
        sidecar_path.name,
    )
    return result


@dataclass
class FinishOutcome:
    """What `finish_candidate()` actually did with one tier-3 candidate."""

    probe: ProbeResult
    used_cache: bool
    # "queued" | "already-queued" | "deferred" | "already-deferred" |
    # "skipped-deferred" (an accept verdict, but the URL is a deliberate
    # deferred-file removal -- never re-added) | "rejected"
    action: str
    queued: bool = False
    deferred: bool = False
    pinned: bool = False


async def finish_candidate(
    meeting_url: str,
    *,
    video_url: Optional[str] = None,
    source_url: Optional[str] = None,
    platform: Optional[str] = None,
    video_format: Optional[str] = None,
    gov_id: str = "",
    jurisdiction: str = "",
    title: str = "",
    pin: Optional[dict] = None,
    sidecar_path: Path = DEFAULT_SIDECAR_PATH,
    queue_path: Path = TIER3_QUEUE_FILE,
    deferred_path: Path = TIER3_LONG_MEETINGS_DEFERRED_FILE,
    pins_path: Path = TENANT_OVERRIDES_CSV,
    caller: str = "",
) -> FinishOutcome:
    """The one place a tier-3 finish step should turn a probe verdict --
    fresh or cached -- into a queue line, a deferred-file line, or
    nothing. See this module's "WO-224 shared finish step" section
    docstring above for the bug this replaces.

    1. Uses `cached_verdict()` when the sidecar already has a row for
       `meeting_url`, instead of re-probing (and re-spending a real
       network request against a host we've already learned the answer
       for -- the same "politely" reasoning CLAUDE.md gives for host
       delays). Otherwise probes fresh via `probe_queue_entry()` and
       appends the result to the sidecar, exactly like every existing
       finish script already does on a cache miss.
    2. `reject-dead`/`reject-short`: nothing queued, pinned, or deferred.
       `probe.reason` already carries why.
    3. `accept`/`flag-long`:
       - `meeting_url` already sits in the deferred file -> stays out of
         the queue entirely (`action="skipped-deferred"`) -- a line
         removed there on purpose stays removed (WO-212's rule), even if
         a fresh/cached verdict would otherwise queue it.
       - `probe.duration_seconds` is over `DEFER_OVER_SECONDS` (90
         minutes) -> parked in the deferred file instead of the queue
         (WO-205/WO-212's rule) rather than queued now and swapped out
         later.
       - otherwise -> queued (`append_queue_line()`, no-op if already
         queued) and, if `pin` was given, pinned (`write_pin_row()`,
         no-op if that (host, match) is already pinned).
    """
    cached = cached_verdict(meeting_url, sidecar_path=sidecar_path)
    used_cache = cached is not None
    if cached is not None:
        result = cached
    else:
        result = await probe_queue_entry(
            meeting_url,
            video_url=video_url,
            source_page_url=source_url,
            platform=platform,
            video_format=video_format,
        )
        append_probe_row(sidecar_path, result, caller=caller)

    if result.verdict not in _ACCEPT_VERDICTS:
        return FinishOutcome(probe=result, used_cache=used_cache, action="rejected")

    if is_deferred(meeting_url, deferred_path=deferred_path):
        return FinishOutcome(
            probe=result, used_cache=used_cache, action="skipped-deferred"
        )

    duration = result.duration_seconds or 0.0
    if duration > DEFER_OVER_SECONDS:
        deferred = append_deferred_line(
            meeting_url,
            source_url=source_url or "",
            gov_id=gov_id,
            jurisdiction=jurisdiction,
            duration_seconds=result.duration_seconds,
            title=title,
            deferred_path=deferred_path,
        )
        return FinishOutcome(
            probe=result,
            used_cache=used_cache,
            action="deferred" if deferred else "already-deferred",
            deferred=deferred,
        )

    queued = append_queue_line(meeting_url, source_url, queue_path=queue_path)
    pinned = False
    if pin:
        pinned = write_pin_row(
            host=pin.get("host", ""),
            match=pin.get("match", ""),
            gov_id=pin.get("gov_id") or gov_id,
            strength=pin.get("strength") or "fallback",
            source=pin.get("source") or caller,
            evidence=pin.get("evidence") or "",
            pins_path=pins_path,
        )
    return FinishOutcome(
        probe=result,
        used_cache=used_cache,
        action="queued" if queued else "already-queued",
        queued=queued,
        pinned=pinned,
    )
