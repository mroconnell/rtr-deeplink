"""Work through the on-demand-transcription backlog locally, on this Mac,
using a bigger faster-whisper model than the cloud worker can afford.

Why this needs its own script rather than just widening worker/main.py's
own model_size: worker/transcription_engine.py's FasterWhisperEngine
docstring measures this directly -- "small" OOM-killed Render's 2GB
worker plan on a real 900s chunk, so "tiny" is the real deployed default,
not a quality choice. `"tiny"`'s real accuracy against actual meeting
audio has two confirmed, non-hypothetical failure modes (see BACKLOG.md's
"On-demand transcription" section): a meaning-changing mistranscription
("this meeting is adjourned" heard as "this meeting is a joke", a real
named official's real meeting) and a near-total transcription failure on
a genuinely-spoken stretch of a real Napa meeting (~17 repeats of
"Testing one, two, three" plus fabricated Spanish-looking text where real
English speech was happening). A local Mac isn't under Render's 2GB
ceiling, so the entire point of running this here is to use a real,
bigger model against the same real backlog.

As of this script's own first run there were ~209 archived meetings with
no transcript (https://redtaperecordings.com/meetings?has_transcript=false)
-- some genuinely untranscribable (no video, an unreadable stream, a real
recording under 5 minutes), but a real chunk of it is just transcribable
video waiting its turn in a slow, one-at-a-time cloud queue. This script
works that backlog down, off to the side, without touching the worker's
own queue at all.

Deliberately does NOT touch the `transcription_jobs` table or
claim_next_chunk()/report_chunk_result() -- those are explicitly
single-worker-process-safe only (see claim_next_chunk()'s own docstring
in archive/db/crud.py), and this script is a second, independent process
that could run at the same time as the real worker. Instead, this follows
scripts/fetch_youtube_transcripts.py's established pattern: discover
candidates via a small token-gated /internal/* endpoint
(GET /internal/transcription-backlog, the batch, any-platform counterpart
to /internal/transcript-wanted's YouTube-only queue), re-resolve each
meeting fresh via the same app/platforms/base.py adapter registry the
worker and resolver both use, transcribe locally, then push the finished
transcript back through the same idempotent, content-hash-deduped
POST /internal/ingest every other transcript source already goes
through -- so a rare race with the cloud worker picking up the same page
just gets deduped, not double-versioned. Pushes with `"source":
"transcribed"` explicitly (see IngestRequest.source and
crud.ingest_resolution()'s own docstring in archive/main.py /
archive/db/crud.py) -- omitting it would silently mislabel this as a
"scraped" (i.e. authoritative-government-caption) version, losing the
real AI-transcript disclaimer meeting_page.html already renders for
source=="transcribed" content. That disclaimer matters more here than
for the worker's own output, not less: this script deliberately favors
bigger/slower models over the worker's "tiny", but it's still Whisper,
still capable of the same hallucination failure modes documented above,
just less often.

**Model size default, chosen from real local RAM, not a guess** (see
_pick_default_model_size()'s own docstring for the reasoning and the
exact thresholds) -- override with --model-size small|medium|large-v3|...
any faster-whisper model_size string.

**No chunk-size-driven memory concern locally** (unlike the worker, whose
900s AUTO_TRANSCRIPTION_CHUNK_SIZE_SECONDS exists specifically to keep
faster-whisper's peak RSS under Render's 2GB ceiling -- see that
constant's own comment in worker/main.py) -- this Mac has real RAM to
spare. Chunking is kept anyway (CHUNK_SIZE_SECONDS below, same 900s
value) for a *different* reason: app/platforms/media_probe.py's shared
`_run()` helper (used by both probe_duration() and extract_chunk_audio(),
and by the production worker) enforces a 120-second subprocess timeout
per ffmpeg/ffprobe call -- proven safe at 900s-per-call in production,
untested at multi-hour single-pass extraction against a slow/rate-limited
government source. Raising or removing that shared timeout would affect
the worker's own reliability boundary too, not just this script, so it
wasn't touched here on a guess. --chunk-seconds is exposed if a larger
value is ever verified safe against a real slow source.

Usage (from the repo root, with the venv active):
    python scripts/transcribe_backlog_locally.py --dry-run
    python scripts/transcribe_backlog_locally.py --limit 3
    python scripts/transcribe_backlog_locally.py --model-size medium --limit 1

Requires ARCHIVE_BASE_URL and ARCHIVE_INGEST_TOKEN in the repo's local
.env (same as scripts/bulk_ingest.py / fetch_youtube_transcripts.py),
ffmpeg/ffprobe on PATH (same as the resolver/worker services need --
see media_probe.py's own docstring), and `faster-whisper` installed --
deliberately NOT added to requirements-dev.txt (a heavy, CTranslate2-
backed, CPU-inference-only dependency genuinely irrelevant to every other
dev workflow in this repo, same "local tooling only" reasoning
requirements-dev.txt already documents for youtube-transcript-api):
    pip install faster-whisper
(or `pip install -r worker/requirements.txt`, which already has it plus
this script's other imports).
"""

import argparse
import asyncio
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import aiohttp
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import UnsupportedPlatformError, get_finder  # noqa: E402
from app.platforms.media_probe import extract_chunk_audio, is_plausible_meeting_duration, probe_duration  # noqa: E402
from app.utils.vtt_parser import detect_language_from_texts  # noqa: E402
from worker.segment_utils import chunk_count, chunk_duration, chunk_start, shift_segments  # noqa: E402

INGEST_TIMEOUT = aiohttp.ClientTimeout(total=65)  # matches archive_client.PUSH_TIMEOUT -- tolerates a Render cold start
# Gentler than bulk_ingest.py's 1.5s isn't needed here -- this script hits
# each government source once per meeting (a fresh resolve), not a whole
# playlist worth of rapid requests, so REQUEST_DELAY_SECONDS only paces
# the loop between *meetings*, not within one. Kept modest anyway as a
# basic courtesy to the source sites.
REQUEST_DELAY_SECONDS = 2.0

# Must match worker/main.py's AUTO_TRANSCRIPTION_CHUNK_SIZE_SECONDS --
# duplicated rather than imported across the script/worker boundary, same
# convention worker/main.py itself uses for the matching constant it
# duplicates from app/main.py (see that constant's own comment). Kept at
# the same value here for a different reason than the worker's real one
# (RAM headroom, irrelevant on this Mac) -- see the module docstring above
# for why this exists at all.
CHUNK_SIZE_SECONDS = 900


def _base_url() -> str:
    return os.environ.get("ARCHIVE_BASE_URL", "").rstrip("/")


def _headers() -> dict:
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _pick_default_model_size() -> str:
    """Picks a --model-size default from this machine's real total RAM,
    rather than guessing -- the whole reason to run this locally instead
    of just widening worker/main.py's own model_size is that a normal Mac
    isn't under Render's 2GB ceiling, so the default here should actually
    use that headroom, not just replicate the cloud worker's constrained
    choice. Reads `sysctl -n hw.memsize` (macOS-specific -- this script is
    explicitly Mac-only per its own task brief, run from a residential
    connection the same way fetch_youtube_transcripts.py is).

    Thresholds against *total* system RAM (not "currently free" -- this
    script doesn't try to detect what else is running, same
    conservatism as leaving real headroom for macOS itself and a normal
    desktop session on top of the model):
      - >= 32GB total -> "medium" (faster-whisper's own published
        guidance: roughly ~5GB peak RSS, int8, CPU)
      - >= 16GB total -> "small" (roughly ~1-2GB peak RSS) -- this
        session's own dev Mac (16GB) lands here
      - otherwise     -> "base" -- matches worker/transcription_engine.py's
        own real-measured, vetted-safe number (~489MB peak RSS at a real
        900s chunk) rather than defaulting all the way down to "tiny";
        even a RAM-constrained Mac has far more headroom than Render's
        2GB worker plan, so there's no reason to match its most
        conservative tier specifically.
    Falls back to "base" if RAM can't be read at all (sysctl missing, not
    macOS) -- refuses to guess upward on a machine this couldn't actually
    check.
    """
    try:
        total_bytes = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], timeout=5))
    except Exception:
        return "base"
    total_gb = total_bytes / (1024**3)
    if total_gb >= 32:
        return "medium"
    if total_gb >= 16:
        return "small"
    return "base"


async def _get_candidates(session: aiohttp.ClientSession, limit: Optional[int]) -> List[dict]:
    params = {}
    if limit is not None:
        params["limit"] = str(limit)
    async with session.get(
        f"{_base_url()}/internal/transcription-backlog", headers=_headers(), params=params, timeout=INGEST_TIMEOUT
    ) as response:
        if response.status != 200:
            text = await response.text()
            raise RuntimeError(f"transcription-backlog failed ({response.status}): {text[:300]}")
        data = await response.json()
        return data.get("pages", [])


async def _ingest(session: aiohttp.ClientSession, payload: dict, input_url_normalized: str) -> dict:
    body = dict(payload)
    body["input_url_normalized"] = input_url_normalized
    body["source"] = "transcribed"  # see module docstring -- never omit this
    async with session.post(
        f"{_base_url()}/internal/ingest", json=body, headers=_headers(), timeout=INGEST_TIMEOUT
    ) as response:
        if response.status == 200:
            return await response.json()
        text = await response.text()
        raise RuntimeError(f"ingest failed ({response.status}): {text[:300]}")


async def transcribe_meeting(engine, source_url: str, platform: str, *, chunk_size_seconds: int) -> dict:
    """Re-resolves `source_url` fresh (HLS/signed URLs can go stale, same
    reasoning as worker/main.py's own re-resolve-before-each-chunk), probes
    its real duration, and transcribes it locally chunk by chunk (each
    chunk independently extracted/transcribed/offset -- see
    worker/segment_utils.py's shift_segments()), collecting every chunk's
    segments into one full-meeting-relative list. No DB job/checkpoint
    involved -- this whole function either finishes a meeting in one
    process lifetime or doesn't; a crash mid-meeting just means re-running
    this script tries that meeting again from scratch next time (this
    queue isn't drained by marking anything in-progress), which is fine
    for a manually-invoked local batch tool with no concurrent worker
    fighting over the same row.

    Returns {"ok": True, "segments": [...], "language": ..., "video_url":
    ..., "video_format": ..., "platform": ..., "external_id": ...} on
    success, or {"ok": False, "reason": "..."} -- callers treat every
    False the same way (skip and move on), matching the "skip infeasible
    candidates cheaply" brief: a re-resolve failure, an implausible
    duration, and an outright transcription failure are all just reasons
    this particular meeting isn't ready yet, not fatal errors for the run.
    """
    try:
        finder = get_finder(platform)
    except UnsupportedPlatformError as e:
        return {"ok": False, "reason": f"unsupported platform: {e}"}

    try:
        result = await finder.resolve(source_url)
    except Exception as e:
        return {"ok": False, "reason": f"re-resolve failed: {type(e).__name__}: {str(e)[:200]}"}

    if not result.video_url:
        return {"ok": False, "reason": "no usable audio/video source on re-resolve"}

    duration = await probe_duration(result.video_url, source_page_url=source_url)
    if duration is None:
        return {"ok": False, "reason": "ffprobe couldn't read the media (unreachable, or not real media)"}
    if not is_plausible_meeting_duration(duration):
        return {"ok": False, "reason": f"implausible duration ({duration:.0f}s) -- not a real meeting recording"}

    total_chunks = chunk_count(duration, chunk_size_seconds)
    all_segments: list = []
    with tempfile.TemporaryDirectory(prefix="rtr_local_transcribe_") as tmpdir:
        for idx in range(total_chunks):
            start = chunk_start(idx, chunk_size_seconds)
            dur = chunk_duration(idx, chunk_size_seconds, duration)
            audio_path = Path(tmpdir) / f"chunk_{idx}.mp3"
            extracted = await extract_chunk_audio(
                result.video_url, start=start, duration=dur, source_page_url=source_url, out_path=audio_path,
            )
            if not extracted:
                return {"ok": False, "reason": f"ffmpeg extraction failed on chunk {idx + 1}/{total_chunks}"}

            raw_segments = await engine.transcribe_chunk(audio_path)
            all_segments.extend(shift_segments(raw_segments, start))
            audio_path.unlink(missing_ok=True)
            print(f"      chunk {idx + 1}/{total_chunks} transcribed ({len(raw_segments)} segments)")

    if not all_segments:
        return {"ok": False, "reason": "transcription produced no usable segments"}

    language = detect_language_from_texts(s["text"] for s in all_segments)
    return {
        "ok": True,
        "segments": sorted(all_segments, key=lambda s: s["start"]),
        "language": language,
        "video_url": result.video_url,
        "video_format": result.video_format,
        "platform": result.platform,
        "external_id": result.external_id,
    }


async def process_one(
    session: aiohttp.ClientSession, engine, page: dict, *, dry_run: bool, chunk_size_seconds: int
) -> dict:
    """Returns {"slug", "status": "ingested"|"skipped"|"failed", "detail"}."""
    slug = page.get("slug", "?")

    # Cheap pre-filter before any real work: a YouTube-backed page's
    # video_url is a youtube.com/embed/{id} URL, not a direct-streamable
    # one -- ffprobe/ffmpeg can't extract audio from it at all (this would
    # just fail probe_duration() a few seconds later anyway, but skipping
    # it up front avoids a wasted network round-trip and keeps this run's
    # "skipped" reasons meaningful). See crud.list_transcription_backlog_
    # candidates()'s own docstring for why these are still returned by the
    # endpoint rather than filtered server-side.
    if (page.get("video_format") or "") == "youtube":
        return {
            "slug": slug,
            "status": "skipped",
            "detail": "YouTube-backed page -- needs fetch_youtube_transcripts.py's caption-fetch path "
            "(or a future yt-dlp-audio fallback, see BACKLOG.md), not direct URL audio extraction",
        }

    result = await transcribe_meeting(
        engine, page["source_url_normalized"], page["platform"], chunk_size_seconds=chunk_size_seconds
    )
    if not result["ok"]:
        return {"slug": slug, "status": "skipped", "detail": result["reason"]}

    if dry_run:
        return {
            "slug": slug,
            "status": "skipped",
            "detail": f"[dry-run] would push {len(result['segments'])} segments (language={result['language']})",
        }

    payload = {
        "platform": result["platform"],
        "source_url": page["source_url_normalized"],
        "external_id": result.get("external_id") or page.get("external_id"),
        "video_url": result["video_url"],
        "video_format": result["video_format"],
        "segments": result["segments"],
        "transcript_language": result["language"],
    }
    response = await _ingest(session, payload, page["source_url_normalized"])
    page_url = response.get("url", "")
    return {
        "slug": slug,
        "status": "ingested",
        "detail": f"{len(result['segments'])} segments (language={result['language']}) -> {page_url}",
        "segment_count": len(result["segments"]),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Transcribe and report, but don't push")
    parser.add_argument("--limit", type=int, default=None, help="Process at most this many meetings")
    parser.add_argument(
        "--model-size", default=None,
        help="faster-whisper model size (tiny|base|small|medium|large-v3|...). "
        "Defaults based on this Mac's real total RAM -- see _pick_default_model_size().",
    )
    parser.add_argument(
        "--chunk-seconds", type=int, default=CHUNK_SIZE_SECONDS,
        help=f"Seconds of audio per ffmpeg extraction call (default {CHUNK_SIZE_SECONDS} -- "
        "see module docstring for why this isn't just 'the whole meeting at once' locally).",
    )
    args = parser.parse_args()

    if not _base_url():
        print("ARCHIVE_BASE_URL is not set (check the repo's .env).", file=sys.stderr)
        sys.exit(1)
    if not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print("ARCHIVE_INGEST_TOKEN is not set (check the repo's .env).", file=sys.stderr)
        sys.exit(1)

    model_size = args.model_size or _pick_default_model_size()
    print(f"Model size: {model_size} ({'explicit --model-size' if args.model_size else 'auto-picked from local RAM'})")

    register_all_finders()

    print("Loading faster-whisper model (this can take a while on first run, while weights download)...")
    from worker.transcription_engine import FasterWhisperEngine

    engine = FasterWhisperEngine(model_size=model_size)
    print("Model loaded.\n")

    async with aiohttp.ClientSession() as session:
        pages = await _get_candidates(session, args.limit)
        if not pages:
            print("Transcription backlog is empty -- nothing to do.")
            return

        print(f"{'[DRY RUN] ' if args.dry_run else ''}{len(pages)} candidate meeting(s) from {_base_url()}...\n")

        run_start = time.monotonic()
        results = []
        for i, page in enumerate(pages):
            item_start = time.monotonic()
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] ({i + 1}/{len(pages)}) {page.get('slug', '?')} -- {page.get('source_url_normalized', '')}")
            try:
                result = await process_one(session, engine, page, dry_run=args.dry_run, chunk_size_seconds=args.chunk_seconds)
            except Exception as e:
                result = {"slug": page.get("slug", "?"), "status": "failed", "detail": f"{type(e).__name__}: {str(e)[:300]}"}
            elapsed = time.monotonic() - item_start
            results.append(result)
            print(f"    [{result['status'].upper()}] ({elapsed:.1f}s) {result['detail']}")
            if i < len(pages) - 1:
                await asyncio.sleep(REQUEST_DELAY_SECONDS)

        total_elapsed = time.monotonic() - run_start
        ingested = [r for r in results if r["status"] == "ingested"]
        skipped = [r for r in results if r["status"] == "skipped"]
        failed = [r for r in results if r["status"] == "failed"]
        print(
            f"\n{len(ingested)} ingested, {len(skipped)} skipped, {len(failed)} failed (of {len(pages)} candidates) "
            f"in {total_elapsed:.1f}s."
        )


if __name__ == "__main__":
    load_dotenv()
    asyncio.run(main())
