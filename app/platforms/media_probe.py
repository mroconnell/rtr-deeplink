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
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_SUBPROCESS_TIMEOUT_SECONDS
        )
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
            "ffprobe",
            "-v",
            "error",
            "-headers",
            realistic_headers(source_page_url),
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            "-i",
            media_url,
        )
    except (FileNotFoundError, asyncio.TimeoutError):
        logger.exception("ffprobe unavailable or timed out for %s", media_url)
        return None

    if returncode != 0:
        logger.warning(
            "ffprobe failed (%s) for %s: %s",
            returncode,
            media_url,
            stderr.decode(errors="replace")[:500],
        )
        return None

    try:
        duration = json.loads(stdout)["format"]["duration"]
        return float(duration)
    except (KeyError, ValueError, json.JSONDecodeError):
        return None


async def _mean_volume_db(path: Path) -> tuple[bool, Optional[float]]:
    """Runs ffmpeg's own `volumedetect` filter against an already-local
    file (no network involved, just decoding a small mp3 already on
    disk). Returns `(decodable, mean_volume_db)`.

    Two genuinely different outcomes, which this deliberately keeps
    apart (they were conflated into a single `None` until 2026-08-21 --
    see extract_chunk_audio()'s docstring for the real Sentry occurrence
    that cost):

    * `(False, None)` -- ffmpeg exited non-zero, i.e. it could not decode
      the file *at all*. Since this filter graph fully decodes the file
      and writes nothing (`-f null -`), a non-zero exit here means the
      bytes on disk aren't playable media, full stop.
    * `(True, x)` / `(True, None)` -- ffmpeg decoded the file fine; the
      volume was parsed, or it wasn't (an ffmpeg version that words the
      line differently, an unexpected stderr shape). "Decoded but
      unparseable" must not be mistaken for corruption, hence True.

    ffmpeg missing from PATH or timing out also yields `(True, None)`,
    on purpose: neither says anything about *the file*, and reporting a
    broken environment as a corrupt chunk would send the caller's
    retry/failure budget after the wrong thing.
    """
    try:
        returncode, _stdout, stderr = await _run(
            "ffmpeg",
            "-i",
            str(path),
            "-af",
            "volumedetect",
            "-f",
            "null",
            "-",
        )
    except (FileNotFoundError, asyncio.TimeoutError):
        return True, None

    if returncode != 0:
        logger.warning(
            "ffmpeg could not decode %s (exit %s): %s",
            path,
            returncode,
            stderr.decode(errors="replace")[-500:].strip(),
        )
        return False, None

    for line in stderr.decode(errors="replace").splitlines():
        if "mean_volume:" in line:
            try:
                return True, float(line.split("mean_volume:")[1].strip().split(" ")[0])
            except (IndexError, ValueError):
                return True, None
    return True, None


# Real, confirmed threshold, not guessed: a known-good real meeting
# (Boulder County, CO) measures ~-20dB mean_volume on its extracted mono
# audio; a real, confirmed-broken one (Port Coquitlam, BC, 2025-02-18
# Committee of Council Meeting -- see BACKLOG_DONE.md) measures ~-44 to
# -46dB after the same plain `-ac 1` mono downmix, because its source's
# left/right channels are near-exact phase-inverted copies of each other
# -- summing them (the standard stereo->mono average) destructively
# cancels the real signal into near-silence/noise, which is what fed
# faster-whisper the near-silent audio it then hallucinated wildly on
# (confirmed by transcribing that same real audio three ways: the
# standard mono downmix produced nonsense, while either individual
# channel alone -- both measuring ~-15.7dB, and their *difference*
# measuring ~-10.4dB, the signature of near-perfect phase inversion --
# produced a clean, coherent real transcript of the actual meeting).
# -38dB sits with real margin on both sides of that ~-20 vs. ~-45 gap --
# comfortably below genuinely-quiet-but-real speech (soft-spoken
# officials, a distant mic) while still well above the confirmed
# phase-cancellation case.
_SUSPICIOUSLY_QUIET_MEAN_VOLUME_DB = -38.0


async def extract_chunk_audio(
    media_url: str,
    *,
    start: float,
    duration: float,
    source_page_url: str,
    out_path: Path,
) -> tuple[bool, Optional[str]]:
    """Extract just [start, start+duration) as small mono 16kHz mp3 audio.
    For a direct file this is an HTTP Range fetch of just that slice; for
    HLS, ffmpeg only pulls the .ts segments covering that window off the
    playlist -- not a full re-download per chunk either way. `-ss` before
    `-i` (fast, input-side seeking) rather than after -- chunk boundaries
    don't need frame accuracy, and HLS segment granularity makes
    frame-accurate seeking moot regardless. Returns (True, None) on
    success, or (False, reason) on failure -- the caller is responsible
    for treating a failure as a retryable per-chunk failure, not a fatal
    job error (see archive/db/crud.py's consecutive_chunk_failures
    budget). `reason` is a short, real diagnostic (timeout, ffmpeg's own
    stderr tail, an empty-output-file note) rather than a fixed generic
    string -- real gap closed 2026-08-19: every chunk failure previously
    stored the same static "ffmpeg extraction failed" in
    TranscriptionJob.error_message regardless of *why*, which made a
    genuinely-broken source indistinguishable from a slow/rate-limited one
    from the DB row alone (see BACKLOG.md).

    **ffmpeg's exit code alone is not proof the output is usable.** Real,
    confirmed occurrence (Sentry PYTHON-FASTAPI-R, 2026-08-19 15:57:32
    UTC, job 287 chunk 2/21): ffmpeg exited 0 and wrote a non-empty
    chunk_1.mp3, then faster-whisper's PyAV open of that same file raised
    `InvalidDataError: [Errno 1094995529] Invalid data found when
    processing input` -- almost certainly an interrupted read from the
    source stream mid-extraction. The corruption was in fact already
    being observed one line later, by the `volumedetect` pass below
    (which fully decodes the file): ffmpeg exits non-zero on an
    undecodable input, and that exit code was simply discarded. So the
    guard costs no extra subprocess -- `_mean_volume_db()` now reports
    decodability alongside the volume, and an undecodable file becomes a
    normal retryable `(False, reason)` here instead of an exception
    thrown from deep inside whisper. Verified against real ffmpeg
    2026-08-21: a severely truncated/garbage mp3 exits 183 (= the low
    byte of AVERROR_INVALIDDATA, the *same* error code PyAV surfaces as
    errno 1094995529), while a valid file exits 0. Honest limit: a file
    truncated only at its *tail* still decodes cleanly (confirmed -- the
    first 1000 bytes of a real 12.6KB mp3 exit 0 with a correct
    mean_volume), and PyAV opens those too, so this catches
    "not playable at all," not "shorter than requested."

    A stereo source whose left/right channels are (near-)phase-inverted
    is a real, confirmed failure mode of the plain `-ac 1` downmix below
    (see `_SUSPICIOUSLY_QUIET_MEAN_VOLUME_DB`'s own comment for the full
    real-data writeup) -- destructive cancellation leaves faster-whisper
    almost nothing real to transcribe, and it hallucinates on the
    near-silent result instead of failing loudly. After the normal
    downmix, this checks the *already-extracted* file's own mean volume
    (cheap -- no network, just decoding the small file already on disk)
    and, only when it looks suspiciously quiet, re-extracts using the
    left channel alone instead of an averaged downmix -- avoiding the
    cancellation outright rather than just detecting its symptom
    downstream (see worker/segment_utils.py's separate hallucination-
    warning check, the defense-in-depth layer for whatever this doesn't
    catch -- e.g. a source that's *genuinely* bad/corrupted audio, not a
    phase-inversion artifact this can actually fix).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        returncode, _stdout, stderr = await _run(
            "ffmpeg",
            "-y",
            "-headers",
            realistic_headers(source_page_url),
            "-ss",
            str(start),
            "-i",
            media_url,
            "-t",
            str(duration),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "libmp3lame",
            "-b:a",
            "32k",
            str(out_path),
        )
    except FileNotFoundError:
        logger.exception("ffmpeg not found extracting %s @ %ss", media_url, start)
        return False, "ffmpeg not found on PATH"
    except asyncio.TimeoutError:
        logger.exception("ffmpeg timed out extracting %s @ %ss", media_url, start)
        return (
            False,
            f"ffmpeg timed out after {_SUBPROCESS_TIMEOUT_SECONDS}s (source likely slow or rate-limited)",
        )

    if returncode != 0:
        stderr_tail = stderr.decode(errors="replace")[-500:].strip()
        logger.warning(
            "ffmpeg extraction failed (%s) for %s @ %ss: %s",
            returncode,
            media_url,
            start,
            stderr_tail,
        )
        return (
            False,
            f"ffmpeg exited {returncode}: {stderr_tail}"
            if stderr_tail
            else f"ffmpeg exited {returncode}",
        )
    if not (out_path.exists() and out_path.stat().st_size > 0):
        return False, "ffmpeg reported success but produced no audio output"

    decodable, mean_volume = await _mean_volume_db(out_path)
    if not decodable:
        logger.warning(
            "Chunk audio at %ss for %s exists (%s bytes) but isn't decodable -- "
            "reporting a retryable chunk failure rather than handing it to whisper",
            start,
            media_url,
            out_path.stat().st_size,
        )
        return (
            False,
            "ffmpeg reported success but the output file isn't decodable "
            "(likely truncated/corrupt)",
        )

    if mean_volume is not None and mean_volume < _SUSPICIOUSLY_QUIET_MEAN_VOLUME_DB:
        logger.warning(
            "Chunk audio at %ss looks suspiciously quiet after mono downmix (%.1fdB) -- "
            "retrying with the left channel alone in case this is stereo phase "
            "cancellation (see media_probe.py's own docstring)",
            start,
            mean_volume,
        )
        left_path = out_path.with_suffix(".left.mp3")
        try:
            returncode2, _stdout2, stderr2 = await _run(
                "ffmpeg",
                "-y",
                "-headers",
                realistic_headers(source_page_url),
                "-ss",
                str(start),
                "-i",
                media_url,
                "-t",
                str(duration),
                "-vn",
                "-af",
                "pan=mono|c0=c0",
                "-ar",
                "16000",
                "-c:a",
                "libmp3lame",
                "-b:a",
                "32k",
                str(left_path),
            )
        except (FileNotFoundError, asyncio.TimeoutError):
            logger.exception(
                "Left-channel fallback extraction failed for %s @ %ss", media_url, start
            )
            return True, None  # keep the original (quiet, but present) mono result
        if returncode2 == 0 and left_path.exists() and left_path.stat().st_size > 0:
            # An undecodable *fallback* extraction isn't worth failing the
            # chunk over -- the already-verified original mono file below is
            # still usable, so this only cares whether a real, louder volume
            # came back.
            _left_decodable, left_volume = await _mean_volume_db(left_path)
            if left_volume is not None and left_volume > mean_volume + 10:
                # A real, meaningfully louder single channel -- confirms this
                # was cancellation, not a genuinely quiet source (where a
                # single channel wouldn't be any louder than the mix). Use it.
                left_path.replace(out_path)
                logger.info(
                    "Chunk audio at %ss: left channel (%.1fdB) is real signal the mono "
                    "downmix had cancelled (%.1fdB) -- using it instead",
                    start,
                    left_volume,
                    mean_volume,
                )
            else:
                left_path.unlink(missing_ok=True)
        else:
            logger.warning(
                "Left-channel fallback extraction failed (%s) for %s @ %ss: %s",
                returncode2,
                media_url,
                start,
                stderr2.decode(errors="replace")[:500],
            )
    return True, None
