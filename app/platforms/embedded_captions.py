"""Reads CEA-608 captions embedded directly in an HLS video stream (no
separate WebVTT/SRT caption track declared at all).

Built for Invintus (WO-1065, 2026-09-25), but written host-agnostic since
the same shape can recur on other platforms whose captions never left the
video's own picture data. Real facts confirmed live against Invintus's
own HLS output before writing any of this:

* A meeting with `captionPath` empty but a real, watchable video can
  still have real captions -- they're CEA-608 data carried inside the
  H.264 stream itself (SEI messages), not a WebVTT/SRT sidecar. ffmpeg
  reads them straight out of the video with no extra tooling:
  `ffmpeg -v error -f lavfi -i "movie=<path>[out0+subcc]" -map 0:s -f srt -`
  prints real SRT text. Confirmed live on a real Oregon Legislature HLS
  piece (2026-09-25): the extracted line "a little bit of a protest" is
  real spoken text from that meeting, not a parsing artifact.
* ffmpeg's SRT output wraps text in `<font face="Monospace">...</font>`
  and a `{\\an7}` position tag on every cue -- both stripped before the
  text goes through the shared `parse_srt()`/`dedupe_rollup_cues()` path.
* A caption-presence marker ("GA94" in the raw stream) is on EVERY frame
  even during total silence, so it proves nothing by itself -- only real
  extracted words count. One 6-second piece can land entirely in a silent
  stretch of an otherwise-captioned meeting, so a presence probe checks
  up to three pieces spread through the file (not just the first) before
  concluding "no captions" (Ryan's rule, 2026-09-25).
* The master `.m3u8` lists several `#EXT-X-STREAM-INF:...BANDWIDTH=n...`
  variants, each followed by an absolute variant-playlist URL (plus
  `#EXT-X-I-FRAME-STREAM-INF` lines, which are I-frame-only trick-play
  playlists, not real video, and are skipped). The lowest-bandwidth
  (160p) variant is picked deliberately -- it carries the captions (confirmed on
  all five captioned test meetings) and is far smaller to fetch (confirmed live: ~350 KB
  per 6-second piece). That variant playlist then lists relative `.ts`
  segment filenames with `#EXTINF` durations.
* Measured live (2026-09-25) on a real 1h52m Oregon meeting: 1,117 pieces
  at 160p, 391 MB total, 233s to fetch sequentially (one request at a
  time -- see CLAUDE.md's politeness rule), and ffmpeg reads the whole
  concatenated file in about 14s. Concatenating the raw `.ts` bytes
  end-to-end into a single file (no remuxing) is enough for ffmpeg's
  demuxer to read the CEA-608 track straight through.
"""

import asyncio
import logging
import os
import re
import tempfile
from typing import Any, Dict, List, Optional

import aiohttp

from ..utils.vtt_parser import dedupe_rollup_cues, parse_srt

logger = logging.getLogger("rtr_deeplink.embedded_captions")

# Shown on the page when a video has real, unextracted embedded captions
# instead of the plain "No captions found" warning -- the Archive/worker
# recognize this exact prefix (EMBEDDED_CAPTIONS_MARKER) to know a page is
# in this specific state, not just captionless.
EMBEDDED_CAPTIONS_MARKER = "Captions are embedded in this video"
EMBEDDED_CAPTIONS_WARNING = (
    f"{EMBEDDED_CAPTIONS_MARKER} but aren't text yet. We'll add them to "
    "this page once they're extracted."
)

# An honest User-Agent that names us (Ryan's WO-1065 brief; the same
# string app/platforms/sliq_harmony.py sends). Invintus's HLS hosts served
# every request with it on 2026-09-25, no 403 or 429.
_USER_AGENT = (
    "Mozilla/5.0 (compatible; RedTapeRecordings/1.0; +https://redtaperecordings.com)"
)
_HEADERS = {"User-Agent": _USER_AGENT}

_REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)
_FFMPEG_TIMEOUT_SECONDS = 600
_CHUNK_SIZE = 1 << 16  # 64 KiB, streamed to disk -- never held whole in memory

_STREAM_INF_RE = re.compile(r"#EXT-X-STREAM-INF:[^\n]*BANDWIDTH=(\d+)[^\n]*\n(\S+)")
_EXTINF_URI_RE = re.compile(r"#EXTINF:[^\n]*\n(\S+)")
_FONT_TAG_RE = re.compile(r"</?font[^>]*>", re.IGNORECASE)
_ASS_POSITION_TAG_RE = re.compile(r"\{\\an\d+\}")

# Up to 3 pieces, spread through the file at roughly these fractions, are
# checked before giving up on "does this meeting have real captions at
# all" -- a single silent piece (confirmed live) is not enough evidence.
_PROBE_FRACTIONS = (0.25, 0.5, 0.75)

_WORD_RE = re.compile(r"[A-Za-z]{2,}")


class EmbeddedCaptionsBlocked(Exception):
    """Raised when the host answers a request with 403 or 429 -- callers
    stop immediately rather than trying another piece or retrying."""


def has_real_words(cues: List[Dict[str, Any]], minimum: int = 1) -> bool:
    """True once at least `minimum` alphabetic words of 2+ letters have
    been seen across all cues -- a caption-presence marker (e.g. CEA-608's
    GA94 header) proves nothing on its own; only real extracted text does."""
    count = 0
    for cue in cues:
        count += len(_WORD_RE.findall(cue.get("text") or ""))
        if count >= minimum:
            return True
    return False


def _strip_ffmpeg_srt_markup(content: str) -> str:
    """ffmpeg's `-f srt` subcc output wraps every cue in a Monospace
    `<font>` tag and an ASS `{\\an7}` (bottom-center) position tag --
    confirmed live on a real Oregon HLS piece. Neither is real transcript
    text, and parse_srt() has no reason to know about ffmpeg's own output
    conventions, so it's stripped here before handing off to the shared
    parser."""
    content = _FONT_TAG_RE.sub("", content)
    content = _ASS_POSITION_TAG_RE.sub("", content)
    return content


def cues_from_ts_file(path: str) -> List[Dict[str, Any]]:
    """Runs ffmpeg's CEA-608 (`subcc`) extraction over a concatenated
    `.ts` file and returns cues in the same `{start, end, text}` shape
    every other adapter's caption parsing uses, after the roll-up dedupe
    every other embedded/live-caption source in this repo also needs.

    Synchronous and blocking (ffmpeg is a subprocess) -- callers run this
    in a thread so it doesn't block the event loop.
    """
    import subprocess

    result = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"movie={path}[out0+subcc]",
            "-map",
            "0:s",
            "-f",
            "srt",
            "-",
        ],
        capture_output=True,
        timeout=_FFMPEG_TIMEOUT_SECONDS,
    )
    if result.returncode != 0 or not result.stdout:
        return []
    srt_text = result.stdout.decode("utf-8", errors="replace")
    srt_text = _strip_ffmpeg_srt_markup(srt_text)
    cues = parse_srt(srt_text)
    return dedupe_rollup_cues(cues)


def _pick_smallest_variant(master_text: str) -> Optional[str]:
    """The lowest-BANDWIDTH `#EXT-X-STREAM-INF` variant URL in a master
    playlist. `#EXT-X-I-FRAME-STREAM-INF` lines (trick-play, no real
    frames) use a `URI=` attribute on the same line rather than a
    following URL line, so the `#EXT-X-STREAM-INF` regex never matches
    them -- they're skipped for free, not specially excluded."""
    variants = [
        (int(bandwidth), uri) for bandwidth, uri in _STREAM_INF_RE.findall(master_text)
    ]
    if not variants:
        return None
    variants.sort(key=lambda pair: pair[0])
    return variants[0][1]


def _variant_pieces(variant_text: str) -> List[str]:
    """Relative `.ts` segment filenames from a variant playlist, in
    order, from each `#EXTINF` line's following URI line."""
    return _EXTINF_URI_RE.findall(variant_text)


async def _get_text(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    """GET url, returning the response text, or None on any non-200
    (except raising EmbeddedCaptionsBlocked on 403/429). Never raises on
    an ordinary transport error either -- returns None so callers can
    treat "couldn't decide" the same everywhere probing is meant to be
    tolerant."""
    try:
        async with session.get(
            url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT
        ) as response:
            if response.status in (403, 429):
                raise EmbeddedCaptionsBlocked(f"HTTP {response.status} fetching {url}")
            if response.status != 200:
                logger.warning(
                    "Embedded-captions fetch got HTTP %s for %s",
                    response.status,
                    url,
                )
                return None
            return await response.text()
    except EmbeddedCaptionsBlocked:
        raise
    except (aiohttp.ClientError, TimeoutError):
        logger.warning("Embedded-captions fetch failed for %s", url, exc_info=True)
        return None


async def _resolve_variant_pieces(
    session: aiohttp.ClientSession, master_url: str
) -> Optional[tuple]:
    """Returns (variant_base_url, [piece_urls]) for the smallest variant
    of `master_url`, or None if the master/variant couldn't be read.
    Raises EmbeddedCaptionsBlocked straight through from the master or
    variant fetch."""
    from urllib.parse import urljoin

    master_text = await _get_text(session, master_url)
    if master_text is None:
        return None
    variant_rel = _pick_smallest_variant(master_text)
    if not variant_rel:
        logger.warning("No HLS variant found in master playlist %s", master_url)
        return None
    variant_url = urljoin(master_url, variant_rel)
    variant_text = await _get_text(session, variant_url)
    if variant_text is None:
        return None
    piece_names = _variant_pieces(variant_text)
    if not piece_names:
        logger.warning("No pieces found in HLS variant playlist %s", variant_url)
        return None
    piece_urls = [urljoin(variant_url, name) for name in piece_names]
    return variant_url, piece_urls


async def _fetch_piece_bytes(
    session: aiohttp.ClientSession, piece_url: str
) -> Optional[bytes]:
    try:
        async with session.get(
            piece_url, headers=_HEADERS, timeout=_REQUEST_TIMEOUT
        ) as response:
            if response.status in (403, 429):
                raise EmbeddedCaptionsBlocked(
                    f"HTTP {response.status} fetching {piece_url}"
                )
            if response.status != 200:
                logger.warning(
                    "Embedded-captions piece fetch got HTTP %s for %s",
                    response.status,
                    piece_url,
                )
                return None
            # Streamed in chunks so a real ~350 KB (or larger) piece is
            # never held whole in memory beyond one chunk at a time.
            # `iter_chunked` is real aiohttp's own streaming API; the
            # fallback to a single `.read()` covers the test double in
            # tests/aiohttp_mock.py, which only implements `.read()`.
            if hasattr(response.content, "iter_chunked"):
                chunks = []
                async for chunk in response.content.iter_chunked(_CHUNK_SIZE):
                    chunks.append(chunk)
                return b"".join(chunks)
            return await response.read()
    except EmbeddedCaptionsBlocked:
        raise
    except (aiohttp.ClientError, TimeoutError):
        logger.warning(
            "Embedded-captions piece fetch failed for %s", piece_url, exc_info=True
        )
        return None


async def probe_embedded_captions(
    session: aiohttp.ClientSession, master_url: str
) -> Optional[bool]:
    """Fetches up to 3 pieces (at ~25%/50%/75% through the smallest HLS
    variant, one request at a time) and checks each for real extracted
    words, stopping at the first one that has any.

    Returns True if a piece with real words was found, False if all
    checked pieces fetched fine but had none, and None if this couldn't
    be decided at all (master/variant/piece fetch failure, no ffmpeg,
    or a 403/429 -- which surfaces as None here rather than raising,
    since a probe result feeds a warning message, not a hard failure).
    Never raises -- a probe result feeds a reader-facing warning choice,
    not a hard failure, so any unexpected error here degrades to "can't
    decide" (None) rather than taking resolve() down with it.
    """
    try:
        return await _probe_embedded_captions_impl(session, master_url)
    except EmbeddedCaptionsBlocked:
        logger.info("Embedded-captions probe blocked (403/429) for %s", master_url)
        return None
    except Exception:
        logger.warning(
            "Embedded-captions probe failed unexpectedly for %s",
            master_url,
            exc_info=True,
        )
        return None


async def _probe_embedded_captions_impl(
    session: aiohttp.ClientSession, master_url: str
) -> Optional[bool]:
    resolved = await _resolve_variant_pieces(session, master_url)
    if resolved is None:
        return None
    _variant_url, piece_urls = resolved
    if not piece_urls:
        return None

    indices = sorted(
        {
            min(len(piece_urls) - 1, max(0, int(len(piece_urls) * frac)))
            for frac in _PROBE_FRACTIONS
        }
    )

    with tempfile.TemporaryDirectory() as work_dir:
        for index in indices:
            piece_url = piece_urls[index]
            piece_bytes = await _fetch_piece_bytes(session, piece_url)
            if piece_bytes is None:
                return None
            piece_path = os.path.join(work_dir, "probe_piece.ts")
            with open(piece_path, "wb") as fh:
                fh.write(piece_bytes)
            try:
                cues = await asyncio.to_thread(cues_from_ts_file, piece_path)
            except Exception:
                logger.warning(
                    "Embedded-captions probe: ffmpeg failed for %s",
                    piece_url,
                    exc_info=True,
                )
                return None
            if has_real_words(cues):
                return True
    return False


async def extract_embedded_captions(
    session: aiohttp.ClientSession,
    master_url: str,
    *,
    work_dir: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetches every piece of the smallest HLS variant sequentially (one
    request at a time, per CLAUDE.md's politeness rule), concatenates
    them into a single temp file, runs ffmpeg's CEA-608 extraction over
    it, and returns real cues (or [] if none). The temp file is always
    removed, even on failure.

    Raises EmbeddedCaptionsBlocked on a 403/429 from any request (no
    further pieces are fetched once that happens), and RuntimeError when a
    playlist or piece can't be fetched. [] means the whole video was read
    and no real words came out.
    """
    resolved = await _resolve_variant_pieces(session, master_url)
    if resolved is None:
        # A playlist we couldn't read is a failure to report, not "no
        # words" -- the worker falls back to Whisper only on a real "no".
        raise RuntimeError(f"Couldn't read the HLS playlists for {master_url}")
    _variant_url, piece_urls = resolved

    fd, temp_path = tempfile.mkstemp(suffix=".ts", dir=work_dir)
    os.close(fd)
    try:
        with open(temp_path, "wb") as out_fh:
            for piece_url in piece_urls:
                piece_bytes = await _fetch_piece_bytes(session, piece_url)
                if piece_bytes is None:
                    raise RuntimeError(f"Couldn't fetch video piece {piece_url}")
                out_fh.write(piece_bytes)
        cues = await asyncio.to_thread(cues_from_ts_file, temp_path)
        if not has_real_words(cues):
            return []
        return cues
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass
