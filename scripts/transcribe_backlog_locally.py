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
    # Manual re-transcription of one already-live page (e.g. cleaning up a
    # transcript affected by a since-fixed bug) -- --promote makes the fresh
    # version the page's default immediately instead of leaving it as a
    # non-default version nothing points to. See --promote's own --help text.
    python scripts/transcribe_backlog_locally.py --url "https://example.com/meeting" --promote

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
import json
import logging
import os
import random
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
from app.platforms.base import UnsupportedPlatformError, detect_platform, get_finder  # noqa: E402
from app.platforms.media_probe import (
    extract_chunk_audio,
    is_plausible_meeting_duration,
    probe_duration,
)  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402
from app.utils.vtt_parser import detect_language_from_texts  # noqa: E402
from worker.segment_utils import (  # noqa: E402
    chunk_count,
    chunk_duration,
    chunk_start,
    detect_hallucination_warnings,
    merge_chunk_segments,
    shift_segments,
)

# Real bug, confirmed live 2026-08-16/17: this script's own progress output
# (`print(...)`) fully buffers when stdout is redirected to a file/pipe --
# which is how it's actually run for an unattended overnight batch -- so a
# multi-hour run showed *zero* output in its log file despite being
# demonstrably alive (high CPU). The only reason anything showed up at all
# was that media_probe.py's `logger.warning()`/`logger.info()` calls happen
# to flush immediately: `logging.StreamHandler.emit()` calls `self.flush()`
# after every record, regardless of the underlying stream's buffering mode
# -- unlike bare `print()`, which just writes into libc's block buffer and
# waits. Fix: route this script's own output through the same `logging`
# module, configured the same way worker/main.py's standalone process
# already does it (`logging.basicConfig(level=logging.INFO)` at import
# time, module-level `getLogger(...)`) rather than inventing a third
# output style. `stream=sys.stdout` (matching where this script's own
# `print()` calls already went) and `force=True` (so this wins even if
# some import above it already touched logging config) are the two
# additions beyond worker/main.py's bare call. Configuring the *root*
# logger here also means media_probe.py's existing logger.* calls --
# previously the only thing visibly live in a redirected run, for reasons
# no one following this script would guess -- now share the exact same
# timestamped format as everything else instead of standing out as an
# unexplained exception.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
    force=True,
)
logger = logging.getLogger("rtr_transcribe_backlog")

INGEST_TIMEOUT = aiohttp.ClientTimeout(
    total=65
)  # matches archive_client.PUSH_TIMEOUT -- tolerates a Render cold start
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

# --- Retry/backoff for this script's own calls to the Archive API ----------
# Real incident, 2026-08-16/17: the very first HTTP call a real overnight
# run makes (GET /internal/transcription-backlog, fetching the whole 40-
# candidate list before the main loop even starts) hit a transient 502 from
# unrelated deploy activity elsewhere, and the entire script exited on the
# unhandled exception -- losing the run, not just one candidate. The
# per-meeting loop already has its own try/except (one meeting's failure is
# logged and the loop continues), but that resilience never covered this
# call, or the per-meeting ingest push either.
#
# Same exponential-backoff-with-jitter shape as
# app/platforms/granicus.py's `_fetch_page()`
# (`(2**attempt) * random.uniform(0.5, 1.5)`), scaled up with a bigger base
# delay since these calls can afford to be patient (a few minutes of
# backoff is nothing against an hours-long unattended run). The retry
# *predicate* is deliberately narrower than granicus.py's, though:
# granicus.py retries on any status >=400 because it's scraping arbitrary
# third-party government sites, where even a 403 can be a transient
# bot-block that clears up. These calls are all to *our own* Archive API
# with *our own* token -- a 4xx here (bad/missing ARCHIVE_INGEST_TOKEN, a
# malformed payload) is a real, static problem that retrying for minutes
# can't fix, so only 5xx responses and connection-level failures (timeout,
# DNS, connection reset) are treated as retryable.
MAX_RETRIES = 6
RETRY_BASE_DELAY_SECONDS = 5.0
RETRY_MAX_DELAY_SECONDS = 90.0

# How big a gap between wall-clock time and processing time counts as "the
# machine probably slept or lost network," not just "this chunk took a
# while" -- see _note_if_suspended()'s own docstring below for why the
# *skew* between the two clocks (not the absolute elapsed time) is the
# right signal, and why 120s is safely above normal scheduling jitter while
# still well below how long a real Whisper chunk can legitimately run.
SUSPEND_GAP_THRESHOLD_SECONDS = 120.0

# Where a finished-but-not-yet-ingested transcription gets saved if
# /internal/ingest fails even after _request_json()'s own retries are
# exhausted -- see _save_local_backup()'s docstring. Gitignored (local-only
# scratch output, never meant to be committed).
FAILED_INGEST_DIR = (
    Path(__file__).resolve().parent.parent / "local_transcription_backups"
)


class _RetryableHTTPError(Exception):
    """Raised internally by _request_json() for a 5xx response, so the same
    except clause that already catches aiohttp's own connection-level
    errors (timeout, DNS, reset) also catches this -- one retry loop, one
    backoff policy, for both failure shapes."""


async def _request_json(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    *,
    label: str,
    max_retries: int = MAX_RETRIES,
    **kwargs,
) -> dict:
    """Shared retrying request helper for every call this script makes to
    its own Archive API (candidate list fetch, ingest push, promote). See
    the module-level comment above for the retry policy and why 4xx
    responses fail immediately instead of retrying. `label` is a short
    plain-English description of the call, used only in the retry/failure
    log lines (e.g. "candidate list fetch", "ingest push for
    https://..."), so a retry shows up as a legible, specific log line
    instead of looking like the process silently hanging.
    """
    last_error: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            async with session.request(method, url, **kwargs) as response:
                if response.status >= 500:
                    text = await response.text()
                    raise _RetryableHTTPError(
                        f"HTTP {response.status} for {label}: {text[:200]}"
                    )
                if response.status >= 400:
                    text = await response.text()
                    raise RuntimeError(
                        f"{label} failed ({response.status}) -- not retrying, this looks "
                        f"like a real config/request problem rather than a transient one: "
                        f"{text[:300]}"
                    )
                return await response.json()
        except (_RetryableHTTPError, aiohttp.ClientError, asyncio.TimeoutError) as e:
            last_error = e
            if attempt == max_retries - 1:
                break
            delay = min(
                RETRY_MAX_DELAY_SECONDS,
                RETRY_BASE_DELAY_SECONDS * (2**attempt) * random.uniform(0.5, 1.5),
            )
            logger.warning(
                "%s failed (attempt %d/%d): %s -- retrying in %.0fs "
                "(this is an automatic retry, not the process hanging)",
                label,
                attempt + 1,
                max_retries,
                str(e)[:200],
                delay,
            )
            await asyncio.sleep(delay)
    raise RuntimeError(f"{label} failed after {max_retries} attempts: {last_error}")


def _note_if_suspended(wall_before: float, mono_before: float, context: str) -> None:
    """Makes "the machine slept or lost network mid-run" a visible log line
    instead of a silent, unexplained gap -- the real, non-developer-facing
    ask this run's brief called out: someone watching an overnight run
    shouldn't have to infer a suspend from CPU-usage graphs or a stack
    trace.

    Can't prevent macOS from sleeping from inside a Python script, and
    doesn't try to; this only makes what already happened legible.

    The signal: `time.monotonic()` stops advancing while the machine is
    asleep, but `time.time()` (wall clock) jumps forward by the real
    elapsed time on wake, since it's kept in sync with the real-time clock.
    So the *skew* between the two -- not the absolute elapsed time, which a
    single real Whisper chunk can legitimately spend 10-20+ minutes of
    continuous CPU work on -- is what actually indicates a suspend.
    Ordinary scheduling jitter is nowhere near
    SUSPEND_GAP_THRESHOLD_SECONDS (120s); an actual sleep or a long dropped
    connection produces a skew equal to however long that lasted, easily
    minutes to hours.
    """
    wall_elapsed = time.time() - wall_before
    mono_elapsed = time.monotonic() - mono_before
    gap = wall_elapsed - mono_elapsed
    if gap > SUSPEND_GAP_THRESHOLD_SECONDS:
        logger.warning(
            "Detected a ~%.0f-minute gap during %s where real time passed far faster than "
            "processing time -- the machine most likely went to sleep, or lost network long "
            "enough to stall a request, partway through. The run is continuing on its own; "
            "no action needed unless this keeps happening.",
            gap / 60.0,
            context,
        )


def _save_local_backup(payload: dict, slug: str) -> Path:
    """Writes a finished-but-not-yet-ingested transcription payload to disk.

    Only called when /internal/ingest fails even after _request_json()'s
    own retries are exhausted. At that point the expensive part -- local
    Whisper compute, realistically minutes to well over an hour for a long
    meeting -- is already done; the only thing actually lost by just
    logging FAILED and moving on to the next candidate would be that
    finished work, which is a much bigger loss than the network call that
    failed. This is the exact same JSON body _ingest() POSTs (before
    `input_url_normalized`/`source` are added -- see _ingest() -- so
    recovering it later is a plain
    `curl -X POST $ARCHIVE_BASE_URL/internal/ingest -H "Authorization: Bearer $ARCHIVE_INGEST_TOKEN" -d @<path>`,
    not a re-transcription.
    """
    FAILED_INGEST_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_slug = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(slug))[:100]
    path = FAILED_INGEST_DIR / f"{ts}_{safe_slug}.json"
    path.write_text(json.dumps(payload, indent=2))
    return path


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
        total_bytes = int(
            subprocess.check_output(["sysctl", "-n", "hw.memsize"], timeout=5)
        )
    except Exception:
        return "base"
    total_gb = total_bytes / (1024**3)
    if total_gb >= 32:
        return "medium"
    if total_gb >= 16:
        return "small"
    return "base"


async def _get_candidates(
    session: aiohttp.ClientSession, limit: Optional[int]
) -> List[dict]:
    params = {}
    if limit is not None:
        params["limit"] = str(limit)
    data = await _request_json(
        session,
        "GET",
        f"{_base_url()}/internal/transcription-backlog",
        label="candidate list fetch",
        headers=_headers(),
        params=params,
        timeout=INGEST_TIMEOUT,
    )
    return data.get("pages", [])


async def _ingest(
    session: aiohttp.ClientSession, payload: dict, input_url_normalized: str
) -> dict:
    body = dict(payload)
    body["input_url_normalized"] = input_url_normalized
    body["source"] = "transcribed"  # see module docstring -- never omit this
    return await _request_json(
        session,
        "POST",
        f"{_base_url()}/internal/ingest",
        label=f"ingest push for {input_url_normalized}",
        json=body,
        headers=_headers(),
        timeout=INGEST_TIMEOUT,
    )


async def _promote(session: aiohttp.ClientSession, slug: str, version_id: int) -> dict:
    """POST /internal/transcript-version/promote -- makes `version_id` the
    page's default TranscriptVersion. Added 2026-08-16 alongside
    ingest_resolution()'s new `version_id` return field, for --promote
    below: a fresh push here does NOT automatically become the page's
    default when the page already has a default with segments+language
    (see archive/db/crud.py's _is_real_improvement()), which is exactly the
    normal case for a manual re-transcription of an already-live page (the
    whole reason to re-run this script on it). Never demotes the old
    version out of existence -- promote_transcript_version()'s own
    docstring: it stays reachable via `?version=`, this only flips which
    one is_default.
    """
    return await _request_json(
        session,
        "POST",
        f"{_base_url()}/internal/transcript-version/promote",
        label=f"promote for {slug}",
        json={"slug": slug, "version_id": version_id},
        headers=_headers(),
        timeout=INGEST_TIMEOUT,
    )


async def transcribe_meeting(
    engine, source_url: str, platform: str, *, chunk_size_seconds: int
) -> dict:
    """Re-resolves `source_url` fresh (HLS/signed URLs can go stale, same
    reasoning as worker/main.py's own re-resolve-before-each-chunk), probes
    its real duration, and transcribes it locally chunk by chunk (each
    chunk independently extracted/transcribed/offset -- see
    worker/segment_utils.py's shift_segments() -- then merged onto the
    running list via that module's merge_chunk_segments(), which drops a
    real seam-duplicate at the chunk boundary if one is detected -- see
    its own docstring), collecting every chunk's segments into one
    full-meeting-relative list. No DB job/checkpoint
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
        return {
            "ok": False,
            "reason": f"re-resolve failed: {type(e).__name__}: {str(e)[:200]}",
        }

    if not result.video_url:
        return {"ok": False, "reason": "no usable audio/video source on re-resolve"}

    duration = await probe_duration(result.video_url, source_page_url=source_url)
    if duration is None:
        return {
            "ok": False,
            "reason": "ffprobe couldn't read the media (unreachable, or not real media)",
        }
    if not is_plausible_meeting_duration(duration):
        return {
            "ok": False,
            "reason": f"implausible duration ({duration:.0f}s) -- not a real meeting recording",
        }

    total_chunks = chunk_count(duration, chunk_size_seconds)
    all_segments: list = []
    with tempfile.TemporaryDirectory(prefix="rtr_local_transcribe_") as tmpdir:
        for idx in range(total_chunks):
            chunk_wall_start = time.time()
            chunk_mono_start = time.monotonic()
            start = chunk_start(idx, chunk_size_seconds)
            dur = chunk_duration(idx, chunk_size_seconds, duration)
            audio_path = Path(tmpdir) / f"chunk_{idx}.mp3"
            extracted = await extract_chunk_audio(
                result.video_url,
                start=start,
                duration=dur,
                source_page_url=source_url,
                out_path=audio_path,
            )
            if not extracted:
                return {
                    "ok": False,
                    "reason": f"ffmpeg extraction failed on chunk {idx + 1}/{total_chunks}",
                }

            raw_segments = await engine.transcribe_chunk(audio_path)
            # merge_chunk_segments() (not a plain .extend()) -- HLS sources
            # can restate the previous chunk's last sentence at the head of
            # this one (extract_chunk_audio()'s fast seek lands on the
            # nearest preceding HLS segment boundary, not the exact
            # requested second; confirmed live 2026-08-16 against this same
            # backlog, Boulder County CO -- see worker/segment_utils.py's
            # "Seam-duplication dedup" note and BACKLOG_DONE.md).
            before = len(all_segments)
            all_segments = merge_chunk_segments(
                all_segments, shift_segments(raw_segments, start)
            )
            dropped = before + len(raw_segments) - len(all_segments)
            audio_path.unlink(missing_ok=True)
            dedup_note = (
                f", dropped {dropped} seam-duplicate segment(s)" if dropped else ""
            )
            logger.info(
                "    chunk %d/%d transcribed (%d segments%s)",
                idx + 1,
                total_chunks,
                len(raw_segments),
                dedup_note,
            )
            _note_if_suspended(
                chunk_wall_start,
                chunk_mono_start,
                f"chunk {idx + 1}/{total_chunks} of {source_url}",
            )

    if not all_segments:
        return {"ok": False, "reason": "transcription produced no usable segments"}

    sorted_segments = sorted(all_segments, key=lambda s: s["start"])
    language = detect_language_from_texts(s["text"] for s in sorted_segments)
    # Real, confirmed gap closed 2026-08-16 (Port Coquitlam, BC -- see
    # worker/segment_utils.py's own "Hallucinated-transcription detection"
    # note and BACKLOG_DONE.md): nothing previously checked a Whisper-
    # produced transcript for garbled/hallucinated content before this
    # script pushed it live, unlike the scraped-caption path's existing
    # is_likely_garbled() check.
    warnings = detect_hallucination_warnings(sorted_segments)
    return {
        "ok": True,
        "segments": sorted_segments,
        "language": language,
        "transcript_warnings": warnings,
        "video_url": result.video_url,
        "video_format": result.video_format,
        "platform": result.platform,
        "external_id": result.external_id,
    }


async def process_one(
    session: aiohttp.ClientSession,
    engine,
    page: dict,
    *,
    dry_run: bool,
    chunk_size_seconds: int,
    promote: bool = False,
) -> dict:
    """Returns {"slug", "status": "ingested"|"skipped"|"failed", "detail"}.

    `promote`: after a successful ingest, if response["version_id"] is not
    None (it's None only when this push produced literally no segments --
    see ingest_resolution()'s own docstring for why it's still set even
    when the push's content matched an already-existing version by content
    hash, not just a freshly-created one), calls POST /internal/
    transcript-version/promote to make that version the page's default
    immediately. Without this, a manual re-transcription of an already-live
    page (e.g. after a real transcription-quality fix ships) sits as a
    non-default version until someone promotes it by hand -- see
    _promote()'s own docstring for why ingest alone usually isn't enough to
    auto-promote in that case.
    """
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
        engine,
        page["source_url_normalized"],
        page["platform"],
        chunk_size_seconds=chunk_size_seconds,
    )
    if not result["ok"]:
        return {"slug": slug, "status": "skipped", "detail": result["reason"]}

    hallucinated_note = (
        " -- LOOKS HALLUCINATED" if result["transcript_warnings"] else ""
    )

    if dry_run:
        return {
            "slug": slug,
            "status": "skipped",
            "detail": f"[dry-run] would push {len(result['segments'])} segments "
            f"(language={result['language']}){hallucinated_note}",
        }

    payload = {
        "platform": result["platform"],
        "source_url": page["source_url_normalized"],
        "external_id": result.get("external_id") or page.get("external_id"),
        "video_url": result["video_url"],
        "video_format": result["video_format"],
        "segments": result["segments"],
        "transcript_language": result["language"],
        "transcript_warnings": result["transcript_warnings"],
    }
    try:
        response = await _ingest(session, payload, page["source_url_normalized"])
    except Exception as e:
        # _ingest() already retried transient failures inside _request_json()
        # -- this only fires once those retries are exhausted, meaning the
        # push is genuinely not going through right now. The transcription
        # itself (the expensive part) already succeeded, so save it to disk
        # rather than just discarding it along with the "failed" result --
        # see _save_local_backup()'s docstring for how to recover it later.
        backup_path = _save_local_backup(payload, slug)
        raise RuntimeError(
            f"{e} -- transcription itself succeeded ({len(result['segments'])} segments, "
            f"language={result['language']}); saved locally to {backup_path} so it isn't "
            f"lost, re-push it manually once /internal/ingest is reachable again"
        ) from e
    page_url = response.get("url", "")
    version_id = response.get("version_id")
    detail = f"{len(result['segments'])} segments (language={result['language']}){hallucinated_note} -> {page_url}"

    promote_note = ""
    if promote:
        if version_id is None:
            promote_note = " (--promote: skipped, push produced no segments)"
        else:
            await _promote(session, response.get("slug", slug), version_id)
            promote_note = f" (promoted version {version_id} to default)"

    return {
        "slug": slug,
        "status": "ingested",
        "detail": f"{detail}{promote_note}",
        "segment_count": len(result["segments"]),
        "version_id": version_id,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Transcribe and report, but don't push"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Process at most this many meetings"
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Transcribe one specific meeting URL directly, bypassing the oldest-first backlog "
        "queue entirely (e.g. to target one known page, or re-try one that previously failed, "
        "without waiting for it to come up in queue order). Same "
        "GET /internal/transcription-backlog "
        "-vs- '/admin/recheck-archive-page?url=' pattern app/main.py already offers for a live "
        "resolve. Ignores --limit when set.",
    )
    parser.add_argument(
        "--model-size",
        default=None,
        help="faster-whisper model size (tiny|base|small|medium|large-v3|...). "
        "Defaults based on this Mac's real total RAM -- see _pick_default_model_size().",
    )
    parser.add_argument(
        "--chunk-seconds",
        type=int,
        default=CHUNK_SIZE_SECONDS,
        help=f"Seconds of audio per ffmpeg extraction call (default {CHUNK_SIZE_SECONDS} -- "
        "see module docstring for why this isn't just 'the whole meeting at once' locally).",
    )
    parser.add_argument(
        "--promote",
        action="store_true",
        help="After a successful ingest, automatically promote the TranscriptVersion this push "
        "corresponds to (freshly created, or an existing content-hash duplicate if re-running an "
        "identical transcription) to be the page's default (POST /internal/transcript-version/"
        "promote). Off by default -- a plain re-run of the normal backlog queue pushes brand-new "
        "pages, where the very first version is already is_default=True on creation and this is a "
        "no-op; it matters specifically for --url against an already-live page whose existing "
        "default already has segments+language, where ingest_resolution()'s automatic promotion "
        "won't fire on its own (see _promote()'s own docstring). Skipped only if the push produced "
        "no segments at all.",
    )
    args = parser.parse_args()

    if not _base_url():
        logger.error("ARCHIVE_BASE_URL is not set (check the repo's .env). Stopping.")
        sys.exit(1)
    if not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        logger.error(
            "ARCHIVE_INGEST_TOKEN is not set (check the repo's .env). Stopping."
        )
        sys.exit(1)

    model_size = args.model_size or _pick_default_model_size()

    # A real, plain-English "what is this run actually doing" line up front
    # -- someone checking on an unattended overnight run should be able to
    # see the real config (model size, whether it's a dry run, how many
    # meetings it's targeting) from the top of the log without reading
    # Python source.
    logger.info(
        "Run started: model_size=%s (%s), limit=%s, dry_run=%s, chunk_seconds=%s, "
        "promote=%s, target=%s",
        model_size,
        "explicit --model-size" if args.model_size else "auto-picked from local RAM",
        args.limit if args.limit is not None else "(none -- full backlog)",
        args.dry_run,
        args.chunk_seconds,
        args.promote,
        args.url or "(oldest-first backlog queue)",
    )

    register_all_finders()

    logger.info(
        "Loading faster-whisper model (this can take a while on first run, while weights download)..."
    )
    from worker.transcription_engine import FasterWhisperEngine

    engine = FasterWhisperEngine(model_size=model_size)
    logger.info("Model loaded.")

    async with aiohttp.ClientSession() as session:
        if args.url:
            # Bypasses the discovery queue entirely -- doesn't need to be a
            # page crud.list_transcription_backlog_candidates() would even
            # return (e.g. it's fine to target a page that already has a
            # transcript, to force a re-transcription). detect_platform()
            # is the same classifier /api/resolve itself uses; process_one()
            # re-resolves fresh regardless, so no other field here needs to
            # be real -- video_format is deliberately left unset (not
            # "youtube") so the cheap pre-filter in process_one() never
            # blocks an explicit, operator-chosen target.
            normalized = normalize_url(args.url)
            pages = [
                {
                    "slug": normalized,
                    "platform": detect_platform(args.url),
                    "external_id": None,
                    "source_url_normalized": normalized,
                    "video_url": None,
                    "video_format": None,
                }
            ]
        else:
            # Retries transient failures internally (see _request_json());
            # if it still fails after those retries, this is a real outage
            # or a bad token, not something more retrying would fix -- fail
            # clearly and immediately rather than an unhandled traceback,
            # since this is the very first thing a real overnight run does
            # and losing it here means losing the whole run before it even
            # starts (the real incident this whole change responds to).
            try:
                pages = await _get_candidates(session, args.limit)
            except Exception as e:
                logger.error(
                    "Could not fetch the candidate list from %s, even after retrying: %s "
                    "-- nothing was transcribed this run. This is usually a real Archive "
                    "outage or a bad ARCHIVE_INGEST_TOKEN, not a bug in this script; check "
                    "the Archive service and .env before restarting.",
                    _base_url(),
                    e,
                )
                sys.exit(1)
        if not pages:
            logger.info("Transcription backlog is empty -- nothing to do.")
            return

        logger.info(
            "%s%d candidate meeting(s) from %s",
            "[DRY RUN] " if args.dry_run else "",
            len(pages),
            _base_url(),
        )

        run_start = time.monotonic()
        results = []
        ingested_count = skipped_count = failed_count = 0
        for i, page in enumerate(pages):
            item_wall_start = time.time()
            item_start = time.monotonic()
            logger.info(
                "Meeting %d/%d starting: %s -- %s",
                i + 1,
                len(pages),
                page.get("slug", "?"),
                page.get("source_url_normalized", ""),
            )
            try:
                result = await process_one(
                    session,
                    engine,
                    page,
                    dry_run=args.dry_run,
                    chunk_size_seconds=args.chunk_seconds,
                    promote=args.promote,
                )
            except Exception as e:
                result = {
                    "slug": page.get("slug", "?"),
                    "status": "failed",
                    "detail": f"{type(e).__name__}: {str(e)[:300]}",
                }
            elapsed = time.monotonic() - item_start
            results.append(result)

            if result["status"] == "ingested":
                ingested_count += 1
                log_fn = logger.info
            elif result["status"] == "skipped":
                skipped_count += 1
                log_fn = logger.info
            else:
                failed_count += 1
                log_fn = logger.error
            log_fn(
                "Meeting %d/%d finished in %.1fs: %s -- %s",
                i + 1,
                len(pages),
                elapsed,
                result["status"].upper(),
                result["detail"],
            )
            # Running totals after every meeting, not just at the very end --
            # the whole point of this is a run that might not make it to the
            # end unattended, so whoever checks the log partway through
            # should see real progress, not just individual meeting lines.
            logger.info(
                "Progress so far: %d ingested, %d skipped, %d failed (of %d total)",
                ingested_count,
                skipped_count,
                failed_count,
                len(pages),
            )
            _note_if_suspended(
                item_wall_start, item_start, f"meeting {page.get('slug', '?')}"
            )
            if i < len(pages) - 1:
                await asyncio.sleep(REQUEST_DELAY_SECONDS)

        total_elapsed = time.monotonic() - run_start
        logger.info(
            "RUN COMPLETE: %d ingested, %d skipped, %d failed (of %d candidates) in %.1fs.",
            ingested_count,
            skipped_count,
            failed_count,
            len(pages),
            total_elapsed,
        )


if __name__ == "__main__":
    load_dotenv()
    asyncio.run(main())
