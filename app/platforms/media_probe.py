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
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

logger = logging.getLogger("rtr_deeplink.media_probe")

_SUBPROCESS_TIMEOUT_SECONDS = 120

# ffmpeg prints its version banner -- version line, `built with`,
# `configuration:`, and one line per lib -- to *stderr* before it does
# anything, and none of it says a word about why a run failed. Real,
# confirmed cost (BACKLOG.md): a chunk failure on a real 55-chunk
# escribemeetings.com meeting was reported as
# `ffmpeg exited 196: ibavformat 62.12.102 / 62.12.102` -- a truncated
# version-banner line surfacing *as* the error, with the actual cause
# pushed out of the window. Reproduced here 2026-08-22 with the real
# ffmpeg on this machine (8.1.2, whose `libavformat 62. 12.102 / 62.
# 12.102` line matches that string exactly): a failing extraction wrote
# 1,101 bytes of stderr, of which ~630 were banner, so a `[-500:]` tail
# spent nearly half its budget on it and started mid-word.
#
# So: drop banner lines before taking the tail. The tail (not the head) is
# still the right end to keep -- ffmpeg's real diagnosis is its last few
# lines ("HTTP error 404 ...", "Error opening input: Server returned 404
# Not Found") -- there just shouldn't be a version listing competing for
# the space.
#
# Worth recording alongside it, since it makes these reports readable:
# **ffmpeg exit 196 is a network timeout on macOS.** ffmpeg returns
# `-errno` for a failed input, truncated to a byte -- 256 - 196 = 60, and
# errno 60 on Darwin is ETIMEDOUT ("Operation timed out"). Same class of
# transient failure as the explicit 120s subprocess timeout below, just
# reported by ffmpeg itself instead of by asyncio.
_FFMPEG_BANNER_LINE = re.compile(
    r"^\s*(?:ffmpeg|ffprobe) version |^\s*built with |^\s*configuration: |"
    r"^\s*lib(?:avutil|avcodec|avformat|avdevice|avfilter|swscale|swresample|postproc)\s+\d"
)


def _stderr_tail(stderr: bytes, limit: int) -> str:
    """The last `limit` characters of ffmpeg/ffprobe stderr that actually
    carry information -- see _FFMPEG_BANNER_LINE's comment above for why
    the banner is stripped first."""
    lines = [
        line
        for line in stderr.decode(errors="replace").splitlines()
        if line.strip() and not _FFMPEG_BANNER_LINE.match(line)
    ]
    return "\n".join(lines)[-limit:].strip()


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


async def _run(*args: str, timeout: Optional[float] = None) -> tuple[int, bytes, bytes]:
    """`timeout` defaults to _SUBPROCESS_TIMEOUT_SECONDS (120s, sized for
    pulling a real multi-minute audio chunk off a slow government CDN).
    Callers doing something much smaller can pass their own -- see
    extract_frame(), which grabs a single JPEG and has no business
    holding a subprocess for two minutes."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=timeout or _SUBPROCESS_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode, stdout, stderr


async def binary_versions() -> dict[str, Optional[str]]:
    """`{"ffmpeg": "<first line of -version>" | None, "ffprobe": ...}` --
    None meaning "not on PATH here".

    Exists because "is ffmpeg actually installed on service X?" was a real
    open question this repo could only answer for one of its three
    services: render.yaml records a confirmed-live 2026-08-08 ffprobe
    check on the *resolver*, and worker/Dockerfile installs ffmpeg
    explicitly, but the Archive is a plain `runtime: python` service that
    shelled out to no binary at all until the meeting-card frames landed.
    Wired into the Archive's GET /api/health (archive/main.py) so one
    curl against the deployed service settles it, rather than needing a
    Render shell or an inference from "same buildpack, probably".
    """
    out: dict[str, Optional[str]] = {}
    for binary in ("ffmpeg", "ffprobe"):
        try:
            returncode, stdout, _stderr = await _run(binary, "-version", timeout=10)
        except (FileNotFoundError, asyncio.TimeoutError, OSError):
            out[binary] = None
            continue
        if returncode != 0:
            out[binary] = None
            continue
        first_line = stdout.decode(errors="replace").splitlines()[:1]
        out[binary] = first_line[0].strip() if first_line else "present"
    return out


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
            _stderr_tail(stderr, 500),
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


# Real, confirmed ffmpeg bug (WO-45, 2026-08-23): on an HLS master
# playlist whose audio is a SEPARATE fMP4 rendition addressed by
# `#EXT-X-MAP` + `#EXT-X-BYTERANGE` (Cablecast's newer "store-N"
# packaging -- `#EXT-X-MEDIA:TYPE=AUDIO,URI="1080p_audio.m3u8"`), an
# input-side `-ss` lands ffmpeg somewhere it then reads nothing from.
# It still exits 0 and writes a ~224-byte file with no decodable audio
# frame in it. Measured against a real failing production source
# (job 692, portagemi.cablecast.tv/internetchannel/show/304), running
# this module's own argv:
#
#   ffmpeg        -ss 0        -ss 900         -ss 1800
#   5.1.9  (Archive)  225B bad     225B bad        --
#   7.1.5  (workers)  3.6MB ok     224B bad        224B bad
#   8.1.2             3.6MB ok     3.6MB ok        --
#
# 7.1.5 is what the workers actually run today, and it matches
# production exactly: chunk 0 (which needs no seek) always succeeds and
# every later chunk fails, three times, until the job's consecutive-
# failure budget is spent. 33+ jobs died this way on 2026-08-23 alone.
#
# Only ffmpeg 8.x fixes it, and Debian trixie ships 7.1.5 with nothing
# newer in trixie-backports -- so this is not something a base-image
# bump can currently resolve (an earlier version of BACKLOG.md's
# thumbnail entry proposed exactly that; it would not have worked).
#
# What DOES work, measured on 7.1.5 against the same source: moving
# `-ss` to AFTER `-i` (output-side seek). It decodes and discards
# everything up to the target rather than seeking, so it costs real
# time -- ~22s to reach 3600s, i.e. roughly 164x realtime -- but it
# produces a correct, decodable chunk. At that rate the existing 120s
# _SUBPROCESS_TIMEOUT_SECONDS covers a skip of ~5 hours before the
# retry simply times out and we report the original failure, which
# makes this self-limiting rather than something needing its own budget
# (and BACKLOG.md has a standing decision against raising that timeout).
#
# Two cheaper alternatives were tested on the same source and rejected:
# pointing ffmpeg at the audio rendition playlist directly still yields
# 224 bytes, and `-noaccurate_seek` still yields 224 bytes. Pointing it
# at the underlying `1080p_audio.mp4` *does* work and is fast (4s at
# 900s), but requires walking master -> audio rendition -> EXT-X-MAP to
# discover that filename, which is specific to how Cablecast packages
# its VOD. The output-side retry is packaging-agnostic and costs
# nothing on the happy path, so it wins.
async def _extract_chunk_once(
    media_url: str,
    *,
    start: float,
    duration: float,
    source_page_url: str,
    out_path: Path,
    output_side_seek: bool = False,
) -> tuple[bool, Optional[str], bool]:
    """One audio-chunk extraction attempt. Returns
    (ok, reason, worth_seek_retry).

    `output_side_seek` moves `-ss` after `-i`; see the block comment
    above for why that is the fallback and what it costs.

    `worth_seek_retry` marks a failure whose shape is consistent with a
    broken seek (a non-zero exit, or an exit-0 file that's empty), as
    opposed to one where retrying differently is pointless -- a missing
    binary, or a timeout that already spent the whole budget. The
    caller adds one more such case that only it can see: an exit-0,
    non-empty file that turns out to be undecodable, which is the exact
    shape this bug produces.
    """
    seek_before = () if output_side_seek else ("-ss", str(start))
    seek_after = ("-ss", str(start)) if output_side_seek else ()
    try:
        returncode, _stdout, stderr = await _run(
            "ffmpeg",
            "-y",
            "-headers",
            realistic_headers(source_page_url),
            *seek_before,
            "-i",
            media_url,
            *seek_after,
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
        return False, "ffmpeg not found on PATH", False
    except asyncio.TimeoutError:
        logger.exception("ffmpeg timed out extracting %s @ %ss", media_url, start)
        return (
            False,
            f"ffmpeg timed out after {_SUBPROCESS_TIMEOUT_SECONDS}s (source likely slow or rate-limited)",
            False,
        )

    if returncode != 0:
        stderr_tail = _stderr_tail(stderr, 500)
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
            True,
        )
    if not (out_path.exists() and out_path.stat().st_size > 0):
        return False, "ffmpeg reported success but produced no audio output", True
    return True, None, False


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

    **A failed seek gets one output-side-seek retry before giving up
    (WO-45).** The extraction below is a fast input-side `-ss`, which on
    some real HLS packagings returns an exit-0 file with nothing
    decodable in it -- so a failure whose shape fits that (non-zero
    exit, empty output, or the undecodable case above) is retried once
    with `-ss` moved after `-i`, at any `start > 0`. See
    _extract_chunk_once()'s own block comment for the measured evidence,
    what it costs, and the cheaper alternatives that were tested and
    don't work. The retry only ever runs on the failure path; a
    successful extraction is exactly as cheap as it was before.

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

    ok, reason, worth_seek_retry = await _extract_chunk_once(
        media_url,
        start=start,
        duration=duration,
        source_page_url=source_page_url,
        out_path=out_path,
    )
    decodable, mean_volume = (False, None)
    if ok:
        decodable, mean_volume = await _mean_volume_db(out_path)
        if not decodable:
            # The signature of the WO-45 seek bug: exit 0, a real file on
            # disk, nothing decodable in it.
            reason = (
                "ffmpeg reported success but the output file isn't decodable "
                "(likely truncated/corrupt)"
            )
            logger.warning(
                "Chunk audio at %ss for %s exists (%s bytes) but isn't decodable -- "
                "retrying with an output-side seek before giving up",
                start,
                media_url,
                out_path.stat().st_size,
            )
            ok, worth_seek_retry = False, True

    # `start > 0` because at 0 there is no seek to get wrong -- the
    # fallback would be an identical, slower run of the same command.
    if not ok and worth_seek_retry and start > 0:
        retry_ok, retry_reason, _ = await _extract_chunk_once(
            media_url,
            start=start,
            duration=duration,
            source_page_url=source_page_url,
            out_path=out_path,
            output_side_seek=True,
        )
        retry_decodable = False
        if retry_ok:
            retry_decodable, retry_volume = await _mean_volume_db(out_path)
        if retry_ok and retry_decodable:
            logger.info(
                "Chunk audio at %ss for %s recovered by an output-side seek after the "
                "input-side seek returned %s -- see media_probe.py's WO-45 note",
                start,
                media_url,
                reason,
            )
            ok, reason, decodable, mean_volume = True, None, True, retry_volume
        else:
            # Deliberately keep the ORIGINAL reason, not the retry's. The
            # first attempt is what the normal path does; the retry
            # failing too (commonly by timing out on a long skip) is a
            # detail of the recovery attempt, not a better description of
            # what is wrong with this chunk.
            logger.warning(
                "Output-side-seek fallback for %s @ %ss did not recover the chunk (%s)",
                media_url,
                start,
                retry_reason or "still undecodable",
            )

    if not ok:
        # `reason` is always set on the failure path -- either by
        # _extract_chunk_once() or by the undecodable branch above -- and
        # a recovered retry resets it to None along with ok=True.
        return False, reason

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
                _stderr_tail(stderr2, 500),
            )
    return True, None


# A meeting-card frame is a social/OG image, not a still anyone studies:
# 1280px wide is the largest size Twitter/Bluesky/Mastodon/Google actually
# use for a large summary card, and JPEG quality 4 keeps a real 1280x720
# council-chamber frame around 60-120KB -- small enough to live as bytes
# in Postgres (see archive/db/models.py's MeetingPageThumbnail) without a
# vendor object store.
_FRAME_MAX_WIDTH = 1280
_FRAME_JPEG_QUALITY = "4"
# Deliberately far below _SUBPROCESS_TIMEOUT_SECONDS' 120s. With
# input-side `-ss` this reads ~1-2MB before it has a frame; anything
# still running at 45s is a stalled/rate-limited CDN, and the caller
# (a background warm task behind a semaphore) is better off giving the
# slot back than holding it for two minutes. Granicus timeouts are
# routine here, not exceptional -- see BACKLOG.md.
_FRAME_TIMEOUT_SECONDS = 45


async def extract_frame(
    media_url: str,
    *,
    offset: float,
    source_page_url: str,
    out_path: Path,
) -> tuple[bool, Optional[str]]:
    """Grab a single JPEG frame at `offset` seconds. Returns (True, None)
    on success or (False, reason) on any failure -- never raises, since
    every caller is a best-effort thumbnail warm whose correct response
    to failure is "this page has no card yet," not an error.

    **`-ss` before `-i` (input-side/fast seeking), deliberately.** Measured
    in this repo against a real HLS source: reaching the 900s mark costs
    ~1.6MB read input-side versus ~31.7MB for accurate output-side
    seeking, because output-side decodes everything up to the target.
    Fast seeking can land up to ~36s early on HLS (it snaps to the
    nearest segment/keyframe), which is irrelevant for a thumbnail --
    the targeting tiers in archive/utils/video_thumbnail.py are all
    "somewhere in this stretch of the meeting," never a specific frame.

    Same `-headers` treatment as every other function here: a bare
    request to archive-stream.granicus.com returns 403 where a
    browser-shaped one succeeds (see this module's own docstring).
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        returncode, _stdout, stderr = await _run(
            "ffmpeg",
            "-y",
            "-headers",
            realistic_headers(source_page_url),
            "-ss",
            str(max(0, int(offset))),
            "-i",
            media_url,
            "-frames:v",
            "1",
            # Downscale wide sources, never upscale a small one: `-2`
            # keeps the height even (required by the JPEG encoder's
            # chroma subsampling) and preserves the aspect ratio.
            "-vf",
            f"scale='min({_FRAME_MAX_WIDTH},iw)':-2",
            "-q:v",
            _FRAME_JPEG_QUALITY,
            "-an",
            "-sn",
            # `-update 1` is the documented-correct way to write ONE image
            # to a fixed filename; without it the image2 muxer expects a
            # sequence pattern like %03d. ffmpeg 8.x warns and writes the
            # file anyway, but the Archive runs 5.1.9 (confirmed via
            # /api/health's media_tools block, 2026-08-22) and older
            # builds are not guaranteed to. Harmless either way, and it
            # removes one candidate explanation for the exit-0/no-file
            # case below.
            "-update",
            "1",
            "-f",
            "image2",
            str(out_path),
            timeout=_FRAME_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        logger.warning("ffmpeg not found extracting a frame from %s", media_url)
        return False, "ffmpeg not found on PATH"
    except asyncio.TimeoutError:
        logger.warning(
            "ffmpeg timed out extracting a frame from %s @ %ss", media_url, offset
        )
        return False, f"ffmpeg timed out after {_FRAME_TIMEOUT_SECONDS}s"
    except OSError as exc:
        return False, f"ffmpeg could not be started: {exc}"

    if returncode != 0:
        stderr_tail = _stderr_tail(stderr, 300)
        logger.warning(
            "ffmpeg frame extraction failed (%s) for %s @ %ss: %s",
            returncode,
            media_url,
            offset,
            stderr_tail,
        )
        return False, f"ffmpeg exited {returncode}: {stderr_tail}"
    # ffmpeg can exit 0 having written nothing at all, so this has to be
    # caught by looking at the file rather than the exit code -- the same
    # "exit code alone is not proof the output is usable" lesson
    # extract_chunk_audio() above learned from a real Sentry occurrence.
    #
    # This used to report "(offset past end?)" and throw `stderr` away.
    # Both were wrong. The guess was measured false on 2026-08-22: four
    # Cablecast pages that failed this way on the Archive each extracted a
    # real JPEG locally at the exact same offset, so the offset was fine.
    # And discarding stderr meant 68 failures in one sweep had already
    # explained themselves and we deleted the explanation -- the nonzero
    # branch above keeps its tail, this one did not. So: state only what
    # is actually known (exit 0, no file, at this offset) and hand back
    # ffmpeg's own complaint.
    if not (out_path.exists() and out_path.stat().st_size > 0):
        stderr_tail = _stderr_tail(stderr, 300)
        logger.warning(
            "ffmpeg wrote no frame despite exit 0 for %s @ %ss: %s",
            media_url,
            offset,
            stderr_tail,
        )
        return False, (
            f"ffmpeg exited 0 but wrote no frame @ {int(max(0, offset))}s"
            + (f": {stderr_tail}" if stderr_tail else " (no stderr)")
        )
    return True, None
