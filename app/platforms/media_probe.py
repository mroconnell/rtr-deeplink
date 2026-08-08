"""ffmpeg/ffprobe wrappers for on-demand transcription: probing a source
media URL's real duration, and extracting one chunk's audio at a time.

Lives under app/platforms/ (not worker/) even though only the transcription
feature uses it today, specifically so BOTH app/main.py's synchronous
feasibility check (probe_duration only -- needs to run inline in a normal
request/response) and worker/main.py's chunk processing (both functions)
can import it without app/ ever depending on worker/ -- the dependency
direction stays one-way (worker -> app/platforms), matching every other
adapter here. Real, concrete deploy implication: the resolver service now
needs ffmpeg/ffprobe available too, not just the worker (see render.yaml).

Real, confirmed risk this works around: a bare `curl` to Granicus's own
media CDN (archive-stream.granicus.com) returned a 403 this session (see
BACKLOG_DONE.md's Fountain Valley entry) while a real browser succeeded --
almost certainly bot/hotlink protection, not a broken stream. `_realistic_
headers()` sends a real desktop User-Agent plus a Referer pointing at the
source page's own origin, which ffmpeg/ffprobe support natively via
`-headers`. Verify this actually clears that specific known-403 URL before
trusting it against any other platform's CDN -- unconfirmed whether
CivicClerk/eScribe/CA Legislature enforce anything similar.
"""

import asyncio
import json
import logging
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger("rtr_deeplink.media_probe")

_SUBPROCESS_TIMEOUT_SECONDS = 120

# Below this, a "meeting" is almost certainly the wrong asset (a preview
# clip, a trailer, a misidentified short recording) rather than a real
# government meeting -- arbitrary/tunable, not derived from real data yet,
# same honesty as ARCHIVE_RECHECK_AFTER's 30-day pick (see app/main.py).
MIN_PLAUSIBLE_MEETING_SECONDS = 5 * 60
# Sanity ceiling against a garbage/looping stream reporting a nonsense
# duration -- also arbitrary/tunable.
MAX_PLAUSIBLE_MEETING_SECONDS = 14 * 3600


def is_plausible_meeting_duration(seconds: float) -> bool:
    return MIN_PLAUSIBLE_MEETING_SECONDS <= seconds <= MAX_PLAUSIBLE_MEETING_SECONDS

_DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
)


def realistic_headers(source_page_url: str) -> str:
    """ffmpeg/ffprobe's -headers value: a single CRLF-joined string, not a
    dict -- their own format, not an HTTP library's."""
    origin = f"{urlparse(source_page_url).scheme}://{urlparse(source_page_url).netloc}"
    return f"User-Agent: {_DESKTOP_USER_AGENT}\r\nReferer: {origin}/\r\n"


async def _run(*args: str) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=_SUBPROCESS_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode, stdout, stderr


async def probe_duration(media_url: str, *, source_page_url: str) -> Optional[float]:
    """Real duration of the source media in seconds, or None on any
    failure (unreachable, not real media, ffprobe not installed, etc) --
    callers treat None as "feasibility check failed," never raise past
    this function into a user-facing request."""
    try:
        returncode, stdout, stderr = await _run(
            "ffprobe", "-v", "error",
            "-headers", realistic_headers(source_page_url),
            "-show_entries", "format=duration",
            "-of", "json",
            "-i", media_url,
        )
    except (FileNotFoundError, asyncio.TimeoutError):
        logger.exception("ffprobe unavailable or timed out for %s", media_url)
        return None

    if returncode != 0:
        logger.warning("ffprobe failed (%s) for %s: %s", returncode, media_url, stderr.decode(errors="replace")[:500])
        return None

    try:
        duration = json.loads(stdout)["format"]["duration"]
        return float(duration)
    except (KeyError, ValueError, json.JSONDecodeError):
        return None


async def extract_chunk_audio(
    media_url: str, *, start: float, duration: float, source_page_url: str, out_path: Path
) -> bool:
    """Extract just [start, start+duration) as small mono 16kHz mp3 audio.
    For a direct file this is an HTTP Range fetch of just that slice; for
    HLS, ffmpeg only pulls the .ts segments covering that window off the
    playlist -- not a full re-download per chunk either way. `-ss` before
    `-i` (fast, input-side seeking) rather than after -- chunk boundaries
    don't need frame accuracy, and HLS segment granularity makes
    frame-accurate seeking moot regardless. Returns True on success; the
    caller is responsible for treating a False/exception as a retryable
    per-chunk failure, not a fatal job error (see archive/db/crud.py's
    consecutive_chunk_failures budget).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        returncode, _stdout, stderr = await _run(
            "ffmpeg", "-y",
            "-headers", realistic_headers(source_page_url),
            "-ss", str(start),
            "-i", media_url,
            "-t", str(duration),
            "-vn", "-ac", "1", "-ar", "16000",
            "-c:a", "libmp3lame", "-b:a", "32k",
            str(out_path),
        )
    except (FileNotFoundError, asyncio.TimeoutError):
        logger.exception("ffmpeg unavailable or timed out extracting %s @ %ss", media_url, start)
        return False

    if returncode != 0:
        logger.warning(
            "ffmpeg extraction failed (%s) for %s @ %ss: %s",
            returncode, media_url, start, stderr.decode(errors="replace")[:500],
        )
        return False
    return out_path.exists() and out_path.stat().st_size > 0
