"""Re-transcribe just the FIRST chunk of an already-live, already-transcribed
Archive page, when the rest of the transcript is fine but chunk 0 hallucinated
(the confirmed real failure mode written up in BACKLOG.md's "On-demand
transcription" section -- e.g. Sacramento County's "Thank you for your
attention... I'll see you in the next video" stock hallucination on
quiet/no-speech audio, or this script's own first real use, Redwood City
CA 2026-06-08, where chunk 0 produced "Local government meeting." placeholder
loops then garbled Welsh-script gibberish before chunk 1 recovered into a
genuinely clean transcript at the chunk boundary).

Doing a full scripts/transcribe_backlog_locally.py --url --promote re-run
would work too, but re-transcribes the *entire* meeting -- wasteful and slow
for a multi-hour meeting when only the first ~15 minutes is bad, and this is
real, non-hypothetical: Redwood City's own source meeting is 6.6 hours long.
This script instead:

  1. Fetches the page's current default transcript via its public
     /m/{slug}/transcript.srt export (no internal endpoint returns raw
     segments JSON today -- see this repo's own "don't build a path that
     doesn't exist yet" convention; scraping the public SRT is an honest,
     visible dependency on that page rendering correctly, not a hidden one).
  2. Drops every existing segment starting before `--keep-from` seconds
     (default: --chunk-seconds + --overlap-buffer-seconds, i.e. 920s for the
     default 900s chunk size) -- this is deliberately a few seconds *past*
     the nominal chunk boundary, not exactly at it: the real Redwood City
     case had chunk 0's hallucination overrun the nominal 900s boundary by
     several seconds (garbled segments reported up to ~908s), interleaved
     with chunk 1's first few genuine segments once sorted by start time.
     Confirmed by hand for that meeting via its rendered HTML
     (data-start attributes); --keep-from lets a caller override the cutoff
     after doing the same manual check against a different meeting instead
     of assuming this default generalizes blindly.
  3. Re-resolves the source fresh, extracts [0, keep_from) as one audio
     chunk (deliberately overlapping a little past the nominal chunk-0/
     chunk-1 boundary, so the *same* real speech that used to open chunk 1
     gets re-decoded here too), and transcribes it locally with
     faster-whisper (same engine/vocabulary-prompt worker/main.py and
     scripts/transcribe_backlog_locally.py already use).
  4. Splices: worker/segment_utils.merge_chunk_segments(new_chunk_segments,
     kept_old_segments) -- its existing word-overlap seam dedup (built for
     the HLS seek-imprecision case, see that module's own docstring) trims
     any real duplicate between this fresh decode's tail and the kept
     content's head, since both sides are now genuine decodes of the same
     real speech rather than one garbled/one real like the original bug.
  5. Pushes the full spliced segment list through the same
     POST /internal/ingest path every other transcript source uses
     (source="transcribed", never silently omitted -- see
     archive/db/crud.py's ingest_resolution() docstring for why), and
     --promote makes it the page's default the same way
     transcribe_backlog_locally.py's own --promote does.

Requires ARCHIVE_BASE_URL/ARCHIVE_INGEST_TOKEN in .env, ffmpeg/ffprobe on
PATH, faster-whisper installed -- exactly transcribe_backlog_locally.py's
own requirements, see that script's module docstring.

Usage:
    python scripts/retranscribe_first_chunk.py \\
        --archive-url "https://redtaperecordings.com/m/<slug>" \\
        --source-url "https://<original-government-site-clip-url>" \\
        --dry-run

    # After reviewing the dry-run output:
    python scripts/retranscribe_first_chunk.py \\
        --archive-url "https://redtaperecordings.com/m/<slug>" \\
        --source-url "https://<original-government-site-clip-url>" \\
        --promote
"""

import argparse
import asyncio
import logging
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import certifi

# Must run before `import aiohttp` -- see scripts/transcribe_backlog_
# locally.py's own longer comment on this same fix (confirmed live
# 2026-08-21: a fresh Homebrew-Python venv has an empty default SSL trust
# store, and aiohttp caches its default SSLContext at import time).
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import UnsupportedPlatformError, detect_platform, get_finder  # noqa: E402
from app.platforms.media_probe import extract_chunk_audio  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402
from app.utils.vtt_parser import detect_language_from_texts  # noqa: E402
from worker.segment_utils import (  # noqa: E402
    detect_hallucination_warnings,
    merge_chunk_segments,
    shift_segments,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
    force=True,
)
logger = logging.getLogger("rtr_retranscribe_first_chunk")

INGEST_TIMEOUT = aiohttp.ClientTimeout(total=65)

_SRT_TIME_RE = re.compile(
    r"(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})"
)


def _srt_ts_to_seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0


def parse_srt(text: str) -> List[Dict[str, Any]]:
    """Parses a standard .srt file into [{start, end, text}, ...] (seconds,
    text with internal newlines joined by a space). Millisecond precision --
    a small, harmless rounding loss versus the float-second precision the
    Archive stores internally (its /m/{slug} HTML renders that fuller
    precision via each segment's data-start attribute, but only start, never
    end -- see this script's module docstring for why the public SRT export
    is used as the source of truth here instead)."""
    segments: List[Dict[str, Any]] = []
    blocks = re.split(r"\n\s*\n", text.strip())
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue
        time_line_idx = 1 if lines[0].strip().isdigit() else 0
        m = _SRT_TIME_RE.search(lines[time_line_idx])
        if not m:
            continue
        start = _srt_ts_to_seconds(*m.groups()[0:4])
        end = _srt_ts_to_seconds(*m.groups()[4:8])
        seg_text = " ".join(lines[time_line_idx + 1 :]).strip()
        if seg_text:
            segments.append(
                {"start": start, "end": end, "text": seg_text, "speaker": None}
            )
    return segments


def _base_url() -> str:
    return os.environ.get("ARCHIVE_BASE_URL", "").rstrip("/")


def _headers() -> dict:
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _archive_slug(archive_url: str) -> str:
    path = urlparse(archive_url).path
    return path.rstrip("/").split("/")[-1]


async def fetch_existing_segments(
    session: aiohttp.ClientSession, archive_url: str, version: int | None
) -> List[Dict[str, Any]]:
    slug = _archive_slug(archive_url)
    base = archive_url.split("/m/")[0] if "/m/" in archive_url else _base_url()
    srt_url = f"{base}/m/{slug}/transcript.srt"
    params = {"version": str(version)} if version else {}
    async with session.get(srt_url, params=params, timeout=INGEST_TIMEOUT) as resp:
        resp.raise_for_status()
        text = await resp.text()
    return parse_srt(text)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--archive-url",
        required=True,
        help="The live /m/{slug} page (redtaperecordings.com), optionally with ?version=N "
        "to target a specific non-default version. Used to fetch the current transcript "
        "and, on --promote, as the page to promote against.",
    )
    parser.add_argument(
        "--source-url",
        required=True,
        help="The ORIGINAL government-site meeting URL (e.g. the page's own 'View original "
        "source' link) -- needed to re-resolve fresh video/audio, same as "
        "transcribe_backlog_locally.py's --url.",
    )
    parser.add_argument(
        "--chunk-seconds",
        type=int,
        default=900,
        help="Nominal chunk size the original transcription used (default 900, "
        "the default every platform except Granicus gets -- see app/platforms/"
        "media_probe.py's chunk_size_seconds_for_platform(). Pass 300 for a job "
        "that was created against a Granicus source.",
    )
    parser.add_argument(
        "--overlap-buffer-seconds",
        type=int,
        default=20,
        help="Extra seconds past --chunk-seconds to both re-extract and use as "
        "the keep-from cutoff on old segments, so the fresh decode and the kept "
        "old content genuinely overlap and merge_chunk_segments() can dedup the "
        "seam automatically instead of leaving a gap or a hard cut mid-sentence.",
    )
    parser.add_argument(
        "--keep-from",
        type=float,
        default=None,
        help="Override the auto-computed (chunk-seconds + overlap-buffer-seconds) "
        "cutoff directly, e.g. after manually inspecting the page's rendered HTML "
        "the way this script's own module docstring describes for Redwood City.",
    )
    parser.add_argument(
        "--model-size",
        default=None,
        help="faster-whisper model size. Defaults to transcribe_backlog_locally.py's "
        "own RAM-based pick if unset.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Transcribe and report the spliced result, but don't push.",
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help="After a successful push, promote the resulting version to default.",
    )
    args = parser.parse_args()

    if not _base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        logger.error(
            "ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set in .env. Stopping."
        )
        sys.exit(1)

    keep_from = args.keep_from
    if keep_from is None:
        keep_from = args.chunk_seconds + args.overlap_buffer_seconds

    register_all_finders()
    version = None
    if "version=" in args.archive_url:
        from urllib.parse import parse_qs

        qs = parse_qs(urlparse(args.archive_url).query)
        if qs.get("version"):
            version = int(qs["version"][0])

    async with aiohttp.ClientSession() as session:
        logger.info(
            "Fetching existing transcript from %s (version=%s)...",
            args.archive_url,
            version,
        )
        existing = await fetch_existing_segments(session, args.archive_url, version)
        logger.info(
            "Existing transcript: %d segments, spanning %.1fs - %.1fs",
            len(existing),
            existing[0]["start"] if existing else 0,
            existing[-1]["end"] if existing else 0,
        )

        kept_old = [s for s in existing if s["start"] >= keep_from]
        dropped_count = len(existing) - len(kept_old)
        logger.info(
            "Dropping %d segment(s) starting before %.1fs; keeping %d segment(s) from %.1fs onward.",
            dropped_count,
            keep_from,
            len(kept_old),
            kept_old[0]["start"] if kept_old else -1,
        )

        platform = detect_platform(args.source_url)
        try:
            finder = get_finder(platform)
        except UnsupportedPlatformError as e:
            logger.error("Unsupported platform: %s", e)
            sys.exit(1)

        logger.info(
            "Re-resolving %s (platform=%s) for a fresh video URL...",
            args.source_url,
            platform,
        )
        result = await finder.resolve(args.source_url)
        if not result.video_url:
            logger.error("No usable audio/video source on re-resolve. Stopping.")
            sys.exit(1)

        model_size = args.model_size
        if model_size is None:
            from scripts.transcribe_backlog_locally import _pick_default_model_size

            model_size = _pick_default_model_size()
        logger.info("Loading faster-whisper model %s...", model_size)
        from worker.transcription_engine import FasterWhisperEngine

        engine = FasterWhisperEngine(model_size=model_size)

        with tempfile.TemporaryDirectory(prefix="rtr_retranscribe_chunk0_") as tmpdir:
            audio_path = Path(tmpdir) / "chunk0.mp3"
            logger.info("Extracting [0, %.1fs) of audio...", keep_from)
            extracted, extraction_error = await extract_chunk_audio(
                result.video_url,
                start=0.0,
                duration=keep_from,
                source_page_url=args.source_url,
                out_path=audio_path,
            )
            if not extracted:
                logger.error(
                    "ffmpeg extraction failed: %s. Stopping.", extraction_error
                )
                sys.exit(1)
            logger.info("Transcribing (this can take a few minutes)...")
            raw_segments = await engine.transcribe_chunk(audio_path)
            new_chunk_segments = shift_segments(raw_segments, 0.0)
            logger.info(
                "New chunk-0 transcription: %d segments.", len(new_chunk_segments)
            )

        merged = merge_chunk_segments(new_chunk_segments, kept_old)
        merged.sort(key=lambda s: s["start"])
        logger.info(
            "Merged transcript: %d segments (was %d).", len(merged), len(existing)
        )

        language = detect_language_from_texts(s["text"] for s in merged)
        warnings = detect_hallucination_warnings(merged)
        logger.info(
            "Language: %s. Hallucination warnings: %s", language, warnings or "none"
        )

        logger.info("--- New chunk-0 segments (preview, first 15) ---")
        for seg in new_chunk_segments[:15]:
            logger.info("  [%.1f-%.1f] %s", seg["start"], seg["end"], seg["text"][:100])
        logger.info(
            "--- Seam region in merged output (around keep_from=%.1fs) ---", keep_from
        )
        for seg in merged:
            if keep_from - 30 <= seg["start"] <= keep_from + 30:
                logger.info(
                    "  [%.1f-%.1f] %s", seg["start"], seg["end"], seg["text"][:100]
                )

        if args.dry_run:
            logger.info("[DRY RUN] Not pushing.")
            return

        payload = {
            "platform": result.platform,
            "source_url": normalize_url(args.source_url),
            "external_id": result.external_id,
            "title": result.title,
            "date": result.date,
            "jurisdiction": result.jurisdiction,
            "video_url": result.video_url,
            "video_format": result.video_format,
            "segments": merged,
            "transcript_language": language,
            "transcript_warnings": warnings,
            "input_url_normalized": normalize_url(args.source_url),
            "source": "transcribed",
        }
        logger.info("Pushing to %s/internal/ingest ...", _base_url())
        async with session.post(
            f"{_base_url()}/internal/ingest",
            json=payload,
            headers=_headers(),
            timeout=INGEST_TIMEOUT,
        ) as resp:
            resp.raise_for_status()
            response = await resp.json()
        logger.info("Ingest response: %s", response)

        if args.promote:
            version_id = response.get("version_id")
            slug = response.get("slug") or _archive_slug(args.archive_url)
            if version_id is None:
                logger.warning("No version_id returned -- skipping promote.")
            else:
                async with session.post(
                    f"{_base_url()}/internal/transcript-version/promote",
                    json={"slug": slug, "version_id": version_id},
                    headers=_headers(),
                    timeout=INGEST_TIMEOUT,
                ) as resp:
                    resp.raise_for_status()
                    promote_response = await resp.json()
                logger.info("Promoted version %s: %s", version_id, promote_response)


if __name__ == "__main__":
    load_dotenv()
    asyncio.run(main())
