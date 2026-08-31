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
900s default chunk size exists specifically to keep faster-whisper's
peak RSS under Render's 2GB ceiling -- see app/platforms/media_probe.py's
chunk_size_seconds_for_platform()) -- this Mac has real RAM to spare.
Chunking is kept anyway (CHUNK_SIZE_SECONDS below, same 900s value, for
every platform except Granicus -- see this script's own residual gap
noted at that constant's definition) for a *different* reason: app/
platforms/media_probe.py's shared `_run()` helper (used by both
probe_duration() and extract_chunk_audio(), and by the production
worker) enforces a 120-second subprocess timeout per ffmpeg/ffprobe call
-- proven safe at 900s-per-call for most platforms in production, but
NOT for Granicus specifically (24/24 real chunk-timeout failures on a
cold CDN fill, measured 2026-08-25 -- see BACKLOG_DONE.md), and untested
at multi-hour single-pass extraction against a slow/rate-limited
government source generally. Raising or removing that shared timeout
would affect the worker's own reliability boundary too, not just this
script, so it wasn't touched here on a guess. --chunk-seconds is exposed
if a larger value is ever verified safe against a real slow source, or a
smaller one is needed for a specific Granicus meeting today.

**One transient failure no longer costs a whole meeting (2026-08-22).**
Every call that reaches a live government source -- finder.resolve(),
probe_duration(), extract_chunk_audio() -- retries with backoff (see
MEDIA_ATTEMPTS below and app/utils/retry.py), and a chunk that still fails
checkpoints the chunks already transcribed so the next run resumes instead
of starting over (--no-resume opts out). Ten-plus real cases across three
sessions drove this, including four meetings recorded as permanently
unresolvable that all succeeded on an unchanged re-run minutes later, and
one 55-chunk meeting that discarded 50 finished chunks after failing on
chunk 51. See transcribe_meeting()'s own docstring and BACKLOG.md.

Usage (from the repo root, with the venv active):
    python scripts/transcribe_backlog_locally.py --dry-run
    python scripts/transcribe_backlog_locally.py --limit 3
    python scripts/transcribe_backlog_locally.py --model-size medium --limit 1
    # Manual re-transcription of one already-live page (e.g. cleaning up a
    # transcript affected by a since-fixed bug) -- --promote makes the fresh
    # version the page's default immediately instead of leaving it as a
    # non-default version nothing points to. See --promote's own --help text.
    python scripts/transcribe_backlog_locally.py --url "https://example.com/meeting" --promote

**Thermal pacing, for a real unattended run against a 1000+-meeting queue
on an older/fanless Mac (2026-08-21).** Nothing above throttles CPU usage
at all by default (fine for a --limit 1-3 spot check) -- a genuinely long
batch can run the CPU at a sustained high clock for hours at a stretch
otherwise, a real overheating risk on hardware without a lot of thermal
headroom. Two independent knobs, meant to be used together:
  --cpu-threads N        Caps CTranslate2 to N CPU threads (default: half
                          this machine's real physical core count -- see
                          _pick_default_cpu_threads()).
  --chunk-cooldown-seconds N
                          Sleeps N seconds after every ~900s chunk (see
                          _thermal_pace()) -- a real rest built into the
                          natural per-chunk boundary, not just between
                          meetings. Also checks macOS's own CPU_Speed_Limit
                          (`pmset -g therm`, no sudo needed) after each
                          cooldown and waits longer if the OS has already
                          started throttling -- see --thermal-poll-seconds.
Live-verified against a real ~5.25-hour meeting (Albemarle, NC) at
--cpu-threads 2: CPU_Speed_Limit stayed at 100% (no throttling) for the
whole run. Also worth running the whole invocation under `caffeinate -s`
(prevents sleep on AC power only -- matches this being plugged in for an
overnight run) so a display/idle sleep doesn't stall a chunk mid-extraction:
    python scripts/transcribe_backlog_locally.py --cpu-threads 2 --chunk-cooldown-seconds 30
    caffeinate -s python scripts/transcribe_backlog_locally.py --cpu-threads 2 --chunk-cooldown-seconds 30

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
import hashlib
import json
import logging
import os
import random
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

import certifi

# Must run before `import aiohttp` -- confirmed live 2026-08-21: a fresh
# Homebrew-Python venv has an empty default SSL trust store, and
# aiohttp/connector.py builds+caches its default SSLContext as a
# module-level statement, evaluated the instant `import aiohttp` runs, not
# lazily on first connection -- so this has to exist before that import
# line, not just before this script's own first network call. See
# CLAUDE.md's matching convention bullet for the full incident writeup
# (a real batch of 48 queue URLs got silently dropped the first time this
# fix was applied after the import instead of before it).
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import UnsupportedPlatformError, detect_platform, get_finder  # noqa: E402
from app.platforms.media_probe import (
    chunk_size_seconds_for_platform,
    extract_chunk_audio,
    extract_full_audio,
    is_plausible_meeting_duration,
    probe_duration,
    should_cache_whole_audio,
    slice_cached_audio,
)  # noqa: E402
from app.utils.retry import retry_async  # noqa: E402
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

# The whisper-engine fallback default when neither --chunk-seconds nor a
# platform-specific override applies -- matches app/platforms/media_probe.py's
# chunk_size_seconds_for_platform() own _DEFAULT_CHUNK_SIZE_SECONDS. As of
# WO-75 (2026-08-30) this script calls that shared function per-meeting, in
# process_one(), once each candidate's real platform is known -- the same
# per-page resolution the two real job-creation paths (app/main.py,
# worker/main.py) already do -- so a Granicus meeting run through this
# script now gets that function's smaller 300s Granicus chunk size
# automatically, closing the gap BACKLOG.md previously tracked here. This
# constant now only matters as the value shown in --chunk-seconds' own
# --help text and the "Run started" log line; the real per-meeting decision
# lives in process_one(). Kept at 900 for a different reason than the
# worker's own real one anyway (RAM headroom, irrelevant on this Mac) --
# see the module docstring above for why this exists at all.
CHUNK_SIZE_SECONDS = 900

# Default --chunk-seconds for --engine gemini, deliberately much smaller
# than CHUNK_SIZE_SECONDS above -- see --chunk-seconds' own --help text
# for the arithmetic (a 900s chunk alone is ~22500 estimated input tokens,
# more than double the free tier's entire 10000-tokens/minute budget in
# one call). 180s is ~4500 estimated tokens -- comfortably under budget
# with real margin for GeminiTranscriptionEngine's own rate-limiter pacing
# to work with across a multi-chunk meeting, rather than every single
# chunk needing its own wait.
GEMINI_DEFAULT_CHUNK_SECONDS = 180

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

# --- Retry/backoff for the *live media* calls (a different target) ---------
# The constants above cover this script's calls to our own Archive API. These
# cover the two calls that go out to a real government source instead:
# finder.resolve() (and the probe_duration() that immediately follows it) and
# extract_chunk_audio(). Same policy shape, via the shared helper in
# app/utils/retry.py -- see its docstring for why the "which failures are
# retryable" discipline is the part being reused, not the arithmetic.
#
# Ten-plus confirmed real cases motivated this (BACKLOG.md's own entry has
# them all); the two that shape these numbers:
#   * 4/4 meetings recorded as permanently unresolvable -- Diamond Bar CA,
#     Genesee County MI, Sullivan County NY, Brookhaven NY -- all succeeded
#     on an unchanged re-run minutes later, and Diamond Bar's stored
#     video_url was still live and reachable the whole time. And 3 of 4
#     failed `new.swagit.com` extractions succeeded on an *immediate* retry,
#     with a manual ffmpeg against the exact same URL finishing in ~12s both
#     times -- i.e. the hang was in this script's own long sequential run,
#     not the source.
#   * The honest limit, also confirmed: Odessa needed a *third* attempt, and
#     Brookhaven NY later failed two immediate back-to-back retries
#     identically (same `ffmpeg timed out ... @ 0s`, same CDN host
#     cpmedia.azureedge.net). MEDIA_ATTEMPTS=2 is the settled default, not a
#     claim that one retry is enough for every case -- it's a named constant
#     specifically so it's tunable when a run says otherwise.
# Short backoff on purpose (~5-15s for the first retry, given the 0.5-1.5x
# jitter): the failures above cleared in seconds-to-minutes, and unlike the
# Archive-API retries this one sits inside a per-meeting budget an operator
# is watching.
MEDIA_ATTEMPTS = 2
MEDIA_RETRY_BASE_DELAY_SECONDS = 10.0
MEDIA_RETRY_MAX_DELAY_SECONDS = 60.0

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

# Where a *partially* transcribed meeting is checkpointed when a chunk fails
# after earlier chunks already succeeded -- see _save_partial_progress().
# Under FAILED_INGEST_DIR (same gitignored local-scratch tree) but its own
# subdirectory, because the two hold genuinely different things: a file in
# FAILED_INGEST_DIR is a *finished* transcript that only failed to push and
# can be re-pushed with a plain curl, while one of these is an *unfinished*
# meeting that this script picks back up on the next run.
PARTIAL_PROGRESS_DIR = FAILED_INGEST_DIR / "partial"


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


def _partial_progress_path(source_url: str) -> Path:
    """Deterministic per-meeting checkpoint filename. Keyed by a hash of the
    source URL rather than the slug: the --url path has no real slug (it
    passes the normalized URL through as one), and a URL can contain
    anything a filename can't."""
    digest = hashlib.sha1(source_url.encode("utf-8")).hexdigest()[:16]
    return PARTIAL_PROGRESS_DIR / f"partial_{digest}.json"


def _save_partial_progress(
    source_url: str,
    *,
    segments: list,
    chunks_done: int,
    total_chunks: int,
    chunk_size_seconds: int,
    duration: float,
    reason: str,
) -> Path:
    """Checkpoints the chunks transcribed so far when a meeting fails
    partway through, so the next run resumes instead of starting over.

    The real case this exists for (BACKLOG.md): a
    `pub-3ce.escribemeetings.com` meeting of 55 chunks (~13.75 hours)
    transcribed **50 chunks successfully**, then failed on chunk 51/55 --
    and the entire ~44-minute run was discarded, not just the bad chunk.
    Whisper compute is by far the most expensive thing this script does;
    one transient ffmpeg failure at 91% complete should cost the failed
    chunk, not the other fifty.

    Segments are stored already shifted to whole-meeting-relative times
    (see transcribe_meeting()), so a resume just continues appending. The
    `chunk_size_seconds`/`total_chunks`/`duration` fields are recorded
    specifically so _load_partial_progress() can refuse a checkpoint that
    no longer describes the same meeting -- a re-run with a different
    --chunk-seconds, or a source whose real duration changed, must start
    over rather than splice mismatched offsets together.
    """
    PARTIAL_PROGRESS_DIR.mkdir(parents=True, exist_ok=True)
    path = _partial_progress_path(source_url)
    path.write_text(
        json.dumps(
            {
                "source_url": source_url,
                "chunk_size_seconds": chunk_size_seconds,
                "total_chunks": total_chunks,
                "duration": duration,
                "chunks_done": chunks_done,
                "failed_on_chunk": chunks_done + 1,
                "reason": reason,
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "segments": segments,
            },
            indent=2,
        )
    )
    return path


def _load_partial_progress(
    source_url: str,
    *,
    chunk_size_seconds: int,
    total_chunks: int,
    duration: float,
) -> Tuple[int, list]:
    """`(chunks_already_done, their_segments)` from a previous run's
    checkpoint, or `(0, [])` if there isn't a usable one.

    Refuses (and says so) any checkpoint whose recorded chunking doesn't
    match this run's: a different --chunk-seconds, a different total chunk
    count, or a source duration that has moved by more than a second all
    mean the stored segment offsets no longer line up with the chunks about
    to be transcribed. Starting over is cheap compared to publishing a
    transcript with spliced, wrong timestamps -- the deep links are the
    whole product.
    """
    path = _partial_progress_path(source_url)
    if not path.exists():
        return 0, []
    try:
        saved = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        logger.warning("Ignoring an unreadable partial-progress file at %s", path)
        return 0, []

    mismatch = None
    if saved.get("chunk_size_seconds") != chunk_size_seconds:
        mismatch = "a different --chunk-seconds"
    elif saved.get("total_chunks") != total_chunks:
        mismatch = "a different total chunk count"
    elif abs(float(saved.get("duration") or 0) - duration) > 1.0:
        mismatch = "a different source duration"
    if mismatch:
        logger.info(
            "Ignoring the partial-progress file at %s (%s) -- transcribing this "
            "meeting from the start instead",
            path,
            mismatch,
        )
        return 0, []

    chunks_done = int(saved.get("chunks_done") or 0)
    segments = saved.get("segments") or []
    if chunks_done <= 0 or not segments or chunks_done >= total_chunks:
        return 0, []
    return chunks_done, segments


def _clear_partial_progress(source_url: str) -> None:
    """Drops a meeting's checkpoint once it finishes -- otherwise a stale
    file would sit in the local scratch tree forever, and (worse) a later
    re-transcription of the same URL via --url would silently resume from
    it instead of transcribing fresh."""
    _partial_progress_path(source_url).unlink(missing_ok=True)


def _retryable_extraction_failure(outcome: tuple) -> Optional[str]:
    """What counts as a retryable `extract_chunk_audio()` failure -- the
    same "don't paper over a permanently-broken target" discipline
    _request_json() applies to a 4xx (see app/utils/retry.py's docstring).

    Retryable: a 120s timeout, a non-zero ffmpeg exit, an empty or
    undecodable output file -- every confirmed real case so far has been
    one of these, and 3 of 4 real `new.swagit.com` failures cleared on an
    immediate retry.

    Not retryable: ffmpeg missing from PATH. That's a broken machine, not a
    flaky CDN, and it would fail identically for every chunk of every
    meeting -- waiting 15 seconds to confirm that wastes an unattended
    run's time exactly the way retrying a bad token would.
    """
    extracted, error = outcome
    if extracted:
        return None
    if error and "not found on PATH" in error:
        return None
    return error or "ffmpeg extraction failed"


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


def _pick_default_cpu_threads() -> int:
    """Picks a --cpu-threads default from this machine's real physical core
    count, same "read the real machine, don't guess" approach as
    _pick_default_model_size(). Reads `sysctl -n hw.physicalcpu`.

    Defaults to half the physical cores (minimum 1) -- deliberately leaves
    real headroom rather than letting CTranslate2's own default (0 -- "use
    every visible core") peg the whole machine for however many hours a
    1000+-meeting backlog run takes. This is the actual, direct lever on
    how much heat this generates per unit time: fewer busy cores means a
    lower sustained power draw, at the direct cost of a proportionally
    slower transcription -- see --chunk-cooldown-seconds below for the
    other half of the thermal-pacing story. Not independently measured
    against a real multi-day run on every possible machine -- watch
    Activity Monitor / fan noise / `pmset -g therm` on a first real run
    and raise or lower via --cpu-threads if this default is wrong for the
    machine it's actually running on.

    Falls back to 2 (safe on anything from a dual-core machine up) if
    hw.physicalcpu can't be read at all.
    """
    try:
        physical = int(
            subprocess.check_output(["sysctl", "-n", "hw.physicalcpu"], timeout=5)
        )
    except Exception:
        return 2
    return max(1, physical // 2)


# Regex for CPU_Speed_Limit's line in `pmset -g therm` output, e.g.
# "\tCPU_Speed_Limit \t= 100". macOS sets this below 100 once its own
# thermal management has already decided to throttle the CPU -- a real,
# no-sudo-required signal that this machine is currently running hot,
# distinct from (and a backstop for) the fixed --chunk-cooldown-seconds
# pacing below. See _read_cpu_speed_limit()'s own docstring.
_CPU_SPEED_LIMIT_RE = re.compile(r"CPU_Speed_Limit\s*=\s*(\d+)")


def _read_cpu_speed_limit() -> Optional[int]:
    """Reads macOS's own current CPU_Speed_Limit (0-100) from `pmset -g
    therm` -- the same figure Activity Monitor's "CPU" thermal indicator
    and the Energy tab's "CPU may be throttled" state are driven by. 100
    means unrestricted; anything lower means macOS has already decided to
    slow the CPU down for thermal (or power) reasons.

    This is a real, kernel-reported figure, not a heuristic -- no sudo
    required (`powermetrics --samplers smc`, the only way to read an actual
    die temperature, does need it, and isn't scriptable non-interactively
    without a stored password this repo has no business holding).

    Returns None (not 100) if `pmset` isn't available at all (non-macOS) or
    its output doesn't parse -- callers treat None as "no thermal signal on
    this machine," not "everything's fine," so they fall back to the fixed
    cooldown alone rather than silently skipping pacing.
    """
    try:
        output = subprocess.check_output(["pmset", "-g", "therm"], timeout=5, text=True)
    except Exception:
        return None
    match = _CPU_SPEED_LIMIT_RE.search(output)
    return int(match.group(1)) if match else None


async def _thermal_pace(
    *, cooldown_seconds: float, poll_seconds: float, context: str
) -> None:
    """Rests the CPU between chunks of sustained Whisper work -- the actual
    mechanism behind --chunk-cooldown-seconds / --thermal-poll-seconds.

    Two layers, always both applied when cooldown_seconds > 0:
      1. A fixed sleep (cooldown_seconds) after every chunk, unconditional
         -- the primary defense, a real duty-cycle rest baked into the loop
         rather than only reacting once the machine is already hot.
      2. A CPU_Speed_Limit check (see _read_cpu_speed_limit()) after that
         fixed sleep: if macOS itself is already throttling (limit < 100),
         keeps sleeping in poll_seconds increments -- logging at most once
         per check so an unattended overnight run stays legible without
         spamming -- until it recovers to 100. This is a backstop, not the
         primary mechanism: by the time macOS is visibly throttling, the
         machine is already running hotter than intended.
    Skips layer 2 entirely (only the fixed sleep applies) on a machine
    where _read_cpu_speed_limit() returns None (non-macOS, or pmset
    unavailable).
    """
    if cooldown_seconds <= 0:
        return
    await asyncio.sleep(cooldown_seconds)
    speed_limit = _read_cpu_speed_limit()
    if speed_limit is None or speed_limit >= 100:
        return
    logger.warning(
        "macOS reports CPU_Speed_Limit=%d%% after %s -- this machine is already "
        "being thermally throttled by the OS. Pausing in %.0fs increments until it "
        "recovers to 100%% before starting more Whisper work (this is expected "
        "behavior on a long run, not an error; no action needed).",
        speed_limit,
        context,
        poll_seconds,
    )
    while speed_limit is not None and speed_limit < 100:
        await asyncio.sleep(poll_seconds)
        speed_limit = _read_cpu_speed_limit()
    logger.info("CPU_Speed_Limit back to 100%% -- resuming after %s.", context)


async def _get_candidates(
    session: aiohttp.ClientSession, limit: Optional[int], *, newest_first: bool = False
) -> List[dict]:
    """`/internal/transcription-backlog` itself only ever returns oldest-
    first (crud.list_transcription_backlog_candidates()'s own ORDER BY,
    no other option server-side) -- the same ordering the cloud workers'
    own idle-time auto-generation (find_auto_transcription_candidate())
    independently uses. With ~650 candidates and three independent
    consumers (two cloud workers plus this script) all reaching for the
    same end of the queue, a real overlap-in-progress risk exists: this
    script and a worker both picking the same meeting at nearly the same
    time, each transcribing it independently (wasted duplicate compute,
    not a correctness bug -- see the module docstring's dedup-by-source
    note -- but still real waste on a long run).

    `newest_first`, added 2026-08-23 at the user's own suggestion:
    deliberately reaches for the *opposite* end of the queue instead, so
    a long local run and the cloud workers' own oldest-first sweep stay
    mostly out of each other's way. No server-side "give me newest first"
    option exists, so this fetches the FULL current backlog (limit=None
    on the server call -- cheap at today's ~650-row scale, this script
    already does an unbounded fetch by default whenever --limit itself
    isn't passed) and slices the last `limit` entries off the end
    client-side instead, then reverses that slice so processing still
    proceeds newest-to-less-new within the selected batch, mirroring the
    normal oldest-first mode's own left-to-right order.
    """
    params = {}
    if limit is not None and not newest_first:
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
    pages = data.get("pages", [])
    if newest_first:
        pages = list(reversed(pages[-limit:] if limit is not None else pages))
    return pages


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
    engine,
    source_url: str,
    platform: str,
    *,
    chunk_size_seconds: int,
    resume: bool = True,
    chunk_cooldown_seconds: float = 0.0,
    thermal_poll_seconds: float = 30.0,
) -> dict:
    """Re-resolves `source_url` fresh (HLS/signed URLs can go stale, same
    reasoning as worker/main.py's own re-resolve-before-each-chunk), probes
    its real duration, and transcribes it locally chunk by chunk (each
    chunk independently extracted/transcribed/offset -- see
    worker/segment_utils.py's shift_segments() -- then merged onto the
    running list via that module's merge_chunk_segments(), which drops a
    real seam-duplicate at the chunk boundary if one is detected -- see
    its own docstring), collecting every chunk's segments into one
    full-meeting-relative list.

    **Two kinds of resilience, both added 2026-08-22 after ten-plus
    confirmed real cases** (BACKLOG.md's own entry, and MEDIA_ATTEMPTS'
    comment above, have the specifics):

    * Each of the three calls that reaches a live government source --
      finder.resolve(), probe_duration(), extract_chunk_audio() -- gets
      MEDIA_ATTEMPTS tries with backoff via app/utils/retry.py, rather than
      recording a meeting as unusable on one transient failure. Genuinely
      permanent failures (an unregistered platform, ffmpeg missing from
      PATH) still fail on the first attempt with no delay -- retrying them
      would just make an unattended run slower at reaching the same answer.
    * A chunk that still fails after those retries **checkpoints the chunks
      already transcribed** to PARTIAL_PROGRESS_DIR (see
      _save_partial_progress()) instead of discarding them, and `resume`
      (default True, `--no-resume` turns it off) picks that checkpoint back
      up on the next run. This replaces the previous behavior, documented
      here until this change: "this whole function either finishes a
      meeting in one process lifetime or doesn't; a crash mid-meeting just
      means re-running this script tries that meeting again from scratch."
      That was fine in principle and expensive in practice -- one real
      55-chunk meeting lost 50 finished chunks (~44 minutes of Whisper
      compute) to a single failure on chunk 51.

    Still no DB job/checkpoint involved: the checkpoint is a local file, and
    this script continues to leave `transcription_jobs` alone entirely (see
    the module docstring).

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
        result = await retry_async(
            lambda: finder.resolve(source_url),
            label=f"re-resolve of {source_url}",
            attempts=MEDIA_ATTEMPTS,
            base_delay=MEDIA_RETRY_BASE_DELAY_SECONDS,
            max_delay=MEDIA_RETRY_MAX_DELAY_SECONDS,
            logger=logger,
            # A platform with no registered finder can't start working
            # mid-run; anything else (a bare TimeoutError from eScribe, a
            # connection reset) is exactly the shape that cleared on an
            # unchanged re-run minutes later.
            permanent_exceptions=(UnsupportedPlatformError,),
        )
    except Exception as e:
        return {
            "ok": False,
            "reason": f"re-resolve failed after {MEDIA_ATTEMPTS} attempt(s): "
            f"{type(e).__name__}: {str(e)[:200]}",
        }

    if not result.video_url:
        # A resolve that *succeeded* and found no video is a real answer
        # about this meeting, not a transient failure -- no retry.
        return {"ok": False, "reason": "no usable audio/video source on re-resolve"}

    if result.video_format == "youtube":
        # Real, confirmed gap (2026-08-23): process_one()'s own pre-filter
        # below only catches this using the *stale* video_format on the
        # original candidate dict -- which --url mode leaves unset on
        # purpose (see main()'s own comment) and which the backlog-list
        # path can't guarantee still matches after this fresh re-resolve
        # either. Without this check, a page whose video delegates to
        # YouTube (e.g. CivicClerk's own externalMediaUrl-is-a-youtu.be-
        # link delegation) falls straight through to probe_duration()
        # below, where ffprobe can't read a youtube.com/embed/ page at
        # all -- confirmed live on ashlandcowi event 395, which resolved
        # video_format="youtube" correctly but then failed with the
        # opaque "ffprobe couldn't read the media" rather than this clear
        # message.
        return {
            "ok": False,
            "reason": "YouTube-backed video -- needs fetch_youtube_transcripts.py's caption-fetch "
            "path (or a future yt-dlp-audio fallback, see BACKLOG.md), not direct URL audio "
            "extraction",
        }

    duration = await retry_async(
        lambda: probe_duration(result.video_url, source_page_url=source_url),
        label=f"ffprobe of {result.video_url}",
        attempts=MEDIA_ATTEMPTS,
        base_delay=MEDIA_RETRY_BASE_DELAY_SECONDS,
        max_delay=MEDIA_RETRY_MAX_DELAY_SECONDS,
        logger=logger,
        # probe_duration() never raises -- it returns None for every
        # failure, including the 120s subprocess timeout that is the whole
        # reason this retry exists.
        retryable_failure=lambda d: None if d is not None else "ffprobe read nothing",
    )
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
    first_chunk = 0
    if resume:
        first_chunk, all_segments = _load_partial_progress(
            source_url,
            chunk_size_seconds=chunk_size_seconds,
            total_chunks=total_chunks,
            duration=duration,
        )
        if first_chunk:
            logger.info(
                "    resuming from a previous run's checkpoint: %d/%d chunk(s) "
                "already transcribed (%d segments), starting at chunk %d",
                first_chunk,
                total_chunks,
                len(all_segments),
                first_chunk + 1,
            )

    def _checkpoint(reason: str) -> str:
        """Saves what's been transcribed so far (reading `chunks_done`/
        `all_segments` as they stand at call time) and returns a note for
        the caller-facing reason string. No checkpoint (and no note) when
        nothing has actually been transcribed yet -- an empty file would
        just be litter the next run has to ignore."""
        if not all_segments or chunks_done <= 0:
            return ""
        path = _save_partial_progress(
            source_url,
            segments=all_segments,
            chunks_done=chunks_done,
            total_chunks=total_chunks,
            chunk_size_seconds=chunk_size_seconds,
            duration=duration,
            reason=reason,
        )
        logger.warning(
            "    saved %d/%d already-transcribed chunk(s) (%d segments) to %s -- "
            "re-running this script picks up from chunk %d instead of starting over",
            chunks_done,
            total_chunks,
            len(all_segments),
            path,
            chunks_done + 1,
        )
        return (
            f" -- kept {chunks_done}/{total_chunks} already-transcribed chunk(s) "
            f"in {path}, a re-run resumes from there"
        )

    # A progressive multi-chunk source (ChampDS above all -- see
    # media_probe.extract_full_audio()'s own docstring for the
    # measurements) pays a server-side seek scan per chunk that grows
    # with the offset, so the whole meeting's audio is pulled once here
    # and every chunk becomes a local slice instead. Same gate and same
    # functions worker/main.py's cloud pipeline already uses (WO-54);
    # ported here 2026-08-27 (WO-64) after this exact ChampDS timeout
    # took out 5 of 5 meetings in one local run that the cloud fix would
    # have carried through -- see BACKLOG_DONE.md's WO-64 entry. Unlike
    # the worker (which re-checks the gate on every poll, since each
    # chunk can be claimed by a different worker process), this script
    # processes one meeting sequentially in one process, so a failed
    # whole-file pull is remembered for the rest of THIS meeting's chunks
    # rather than being retried every chunk (that would burn a full
    # _FULL_AUDIO_TIMEOUT_SECONDS on every remaining chunk for no gain --
    # the worker only avoids that cost by luck, since a fresh poll after
    # a failure typically lands on the same still-failing state anyway).
    use_whole_audio_cache = should_cache_whole_audio(result.video_url, total_chunks)
    whole_audio_cache_failed = False

    async def _extract_chunk(
        cache_path: Path, start: float, dur: float, out_path: Path
    ):
        nonlocal whole_audio_cache_failed
        if use_whole_audio_cache and not whole_audio_cache_failed:
            if not cache_path.exists():
                logger.info(
                    "    pulling whole-meeting audio once (seek-hostile source) "
                    "instead of seeking per chunk"
                )
                ok, reason = await extract_full_audio(
                    result.video_url, source_page_url=source_url, out_path=cache_path
                )
                if not ok:
                    cache_path.unlink(missing_ok=True)
                    whole_audio_cache_failed = True
                    logger.info(
                        "    whole-audio pull failed (%s) -- falling back to "
                        "per-chunk extraction for the rest of this meeting",
                        reason,
                    )
                    return await extract_chunk_audio(
                        result.video_url,
                        start=start,
                        duration=dur,
                        source_page_url=source_url,
                        out_path=out_path,
                    )
                logger.info(
                    "    cached %s bytes of audio -- every remaining chunk of "
                    "this meeting is now a local slice with no network at all",
                    cache_path.stat().st_size,
                )
            return await slice_cached_audio(
                cache_path, start=start, duration=dur, out_path=out_path
            )
        return await extract_chunk_audio(
            result.video_url,
            start=start,
            duration=dur,
            source_page_url=source_url,
            out_path=out_path,
        )

    chunks_done = first_chunk
    with tempfile.TemporaryDirectory(prefix="rtr_local_transcribe_") as tmpdir:
        whole_audio_path = Path(tmpdir) / "full_audio.mp3"
        try:
            for idx in range(first_chunk, total_chunks):
                chunk_wall_start = time.time()
                chunk_mono_start = time.monotonic()
                start = chunk_start(idx, chunk_size_seconds)
                dur = chunk_duration(idx, chunk_size_seconds, duration)
                audio_path = Path(tmpdir) / f"chunk_{idx}.mp3"
                extracted, extraction_error = await retry_async(
                    lambda: _extract_chunk(whole_audio_path, start, dur, audio_path),
                    label=f"chunk {idx + 1}/{total_chunks} extraction for {source_url}",
                    attempts=MEDIA_ATTEMPTS,
                    base_delay=MEDIA_RETRY_BASE_DELAY_SECONDS,
                    max_delay=MEDIA_RETRY_MAX_DELAY_SECONDS,
                    logger=logger,
                    retryable_failure=_retryable_extraction_failure,
                )
                if not extracted:
                    reason = (
                        f"ffmpeg extraction failed on chunk {idx + 1}/{total_chunks}"
                        + (f": {extraction_error}" if extraction_error else "")
                    )
                    return {"ok": False, "reason": reason + _checkpoint(reason)}

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
                chunks_done = idx + 1
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
                await _thermal_pace(
                    cooldown_seconds=chunk_cooldown_seconds,
                    poll_seconds=thermal_poll_seconds,
                    context=f"chunk {idx + 1}/{total_chunks} of {source_url}",
                )
        except BaseException as e:
            # Deliberately BaseException, not Exception: a Ctrl-C or an
            # asyncio cancellation three hours into an overnight run is
            # exactly as expensive to discard as a failed chunk is, and the
            # checkpoint costs nothing on the way out. Re-raised unchanged
            # -- this only saves the work, it never swallows the failure
            # (main()'s own per-meeting except still records it, and a real
            # interrupt still stops the run).
            _checkpoint(f"{type(e).__name__}: {str(e)[:200]}")
            raise

    # Every chunk is done -- drop any checkpoint from an earlier partial run
    # of this same meeting, so it can't be resumed from later (a --url
    # re-transcription of an already-finished page must start fresh).
    _clear_partial_progress(source_url)

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
        "title": result.title,
        "date": result.date,
        "jurisdiction": result.jurisdiction,
    }


def _resolve_chunk_seconds(
    *, override: Optional[int], engine_kind: str, platform: str
) -> int:
    """Decides the chunk size (seconds) for one specific meeting, now that
    its real platform is known -- the per-page hook WO-75 (2026-08-30)
    added so this script's chunking finally matches the two real
    job-creation paths (app/main.py, worker/main.py), both of which call
    chunk_size_seconds_for_platform() once the resolved platform is known
    rather than picking one value for a whole run. See CHUNK_SIZE_SECONDS'
    own comment above for what this replaces.

    Precedence, highest first:
      1. `override` (--chunk-seconds) -- an explicit operator choice always
         wins, whatever the platform turns out to be. Preserves this flag's
         original behavior exactly; it was already the top precedence
         before this change, just applied once globally instead of per-page.
      2. `engine_kind == "gemini"` -- GEMINI_DEFAULT_CHUNK_SECONDS. Gemini's
         small default is about the free-tier tokens-per-minute budget (see
         that constant's own comment), a concern that has nothing to do
         with Granicus's cold-CDN-fill timeout, so it stays a flat default
         rather than going through chunk_size_seconds_for_platform().
      3. Otherwise -- chunk_size_seconds_for_platform(platform), the same
         shared function app/main.py and worker/main.py already call.
    """
    if override is not None:
        return override
    if engine_kind == "gemini":
        return GEMINI_DEFAULT_CHUNK_SECONDS
    return chunk_size_seconds_for_platform(platform)


async def process_one(
    session: aiohttp.ClientSession,
    engine,
    page: dict,
    *,
    dry_run: bool,
    chunk_seconds_override: Optional[int],
    engine_kind: str = "whisper",
    promote: bool = False,
    resume: bool = True,
    chunk_cooldown_seconds: float = 0.0,
    thermal_poll_seconds: float = 30.0,
) -> dict:
    """Returns {"slug", "status": "ingested"|"skipped"|"failed", "detail"}.

    `chunk_seconds_override`/`engine_kind`: see _resolve_chunk_seconds() --
    the actual chunk size used is decided here, per meeting, once this
    page's real platform is known (via the same fresh detect_platform()
    call already made below), not once for the whole run.

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
    # one -- ffprobe/ffmpeg can't extract audio from it at all. Only an
    # optimization now, not the sole defense -- it uses the *stale*
    # video_format on this candidate dict (accurate for the normal
    # backlog-list path, deliberately left unset for --url, see main()'s
    # own comment), so it can skip a network round-trip when it already
    # knows the answer, but transcribe_meeting() below re-checks against
    # the fresh re-resolve's own video_format regardless -- see that
    # check's own comment for the real incident (ashlandcowi event 395)
    # this pre-filter alone didn't catch. See crud.list_transcription_backlog_
    # candidates()'s own docstring for why these are still returned by the
    # endpoint rather than filtered server-side.
    if (page.get("video_format") or "") == "youtube":
        return {
            "slug": slug,
            "status": "skipped",
            "detail": "YouTube-backed page -- needs fetch_youtube_transcripts.py's caption-fetch path "
            "(or a future yt-dlp-audio fallback, see BACKLOG.md), not direct URL audio extraction",
        }

    # detect_platform() fresh, not page["platform"] -- that field is whatever
    # was true at original ingest time, and a domain added to an adapter's
    # known-domains list *after* a page was ingested (real case, 2026-08-27:
    # several ProudCity .gov domains ingested as "unknown" before #425-428
    # added ProudCity support) leaves it stale forever. get_finder() on a
    # stale "unknown" raises UnsupportedPlatformError, which reads identically
    # to a genuinely-unsupported site -- silently hiding now-resolvable
    # meetings from every unattended (non --url) run. main()'s --url path
    # already does this fresh lookup; this brings the default candidate-list
    # path in line with it.
    platform = detect_platform(page["source_url_normalized"])
    chunk_size_seconds = _resolve_chunk_seconds(
        override=chunk_seconds_override, engine_kind=engine_kind, platform=platform
    )
    result = await transcribe_meeting(
        engine,
        page["source_url_normalized"],
        platform,
        chunk_size_seconds=chunk_size_seconds,
        resume=resume,
        chunk_cooldown_seconds=chunk_cooldown_seconds,
        thermal_poll_seconds=thermal_poll_seconds,
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
        "title": result.get("title"),
        "date": result.get("date"),
        "jurisdiction": result.get("jurisdiction"),
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
        "--newest-first",
        action="store_true",
        help="Target the newest end of the backlog queue instead of the oldest. Both the two "
        "cloud workers' own idle-time auto-generation and this script's default ordering reach "
        "for the oldest candidates first -- with ~650 candidates and three independent "
        "consumers, that's a real (if rare-per-meeting) risk of this script and a worker "
        "transcribing the same meeting independently around the same time. This flag has this "
        "script work the opposite end instead, so a long local run and the workers' own sweep "
        "mostly stay out of each other's way. See _get_candidates()'s own docstring for the "
        "mechanics (fetches the full current backlog and slices client-side -- no server-side "
        "'newest first' option exists). Ignored when --url is set.",
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
        "--engine",
        choices=["whisper", "gemini"],
        default="whisper",
        help="Which TranscriptionEngine to use (worker/transcription_engine.py). "
        "'whisper' (default): self-hosted faster-whisper, same as the cloud worker's engine "
        "but with real RAM to use a bigger model (see --model-size). "
        "'gemini': Gemini 3.5 Transcribe via the Google API -- evaluated 2026-08-26 against a "
        "real, live Whisper `tiny` bug (see CLAUDE_BACKLOG.md's 'On-demand transcription "
        "follow-ups' entry) and requires GEMINI_API_KEY (or GOOGLE_API_KEY) in .env. Free-tier "
        "rate-limited (see GeminiTranscriptionEngine's own docstring) -- fine for this script's "
        "occasional manual runs, NOT sized for the cloud pipeline's continuous volume. "
        "--model-size/--cpu-threads are ignored (and warned about) when this is 'gemini'.",
    )
    parser.add_argument(
        "--gemini-tokens-per-minute",
        type=int,
        default=None,
        help="Override GeminiTranscriptionEngine's token-per-minute rate-limit pacing budget "
        "(default: the real observed free-tier ceiling, 10000). Raise this if using a paid-tier "
        "key, where that ceiling doesn't apply. Ignored for --engine whisper.",
    )
    parser.add_argument(
        "--model-size",
        default=None,
        help="faster-whisper model size (tiny|base|small|medium|large-v3|...). "
        "Defaults based on this Mac's real total RAM -- see _pick_default_model_size(). "
        "Ignored for --engine gemini.",
    )
    parser.add_argument(
        "--language",
        default=None,
        help="Force Whisper to transcribe in this language (ISO 639-1 code, e.g. 'en') instead "
        "of auto-detecting per chunk. Auto-detection decides from each chunk's first seconds "
        "and can lock a whole chunk into the wrong language when a real meeting opens with "
        "silence/music -- the confirmed Kitchener case (BACKLOG_DONE.md's WO-36 audit entry): "
        "an English meeting transcribed end-to-end as Welsh-script gibberish. Default None "
        "(auto-detect) preserves the original behavior; only force a code when the meeting's "
        "real spoken language is known, since forcing the wrong one produces exactly the "
        "failure this flag exists to fix. Ignored (with a warning) for --engine gemini, whose "
        "engine already pins en-US in its own request config.",
    )
    parser.add_argument(
        "--chunk-seconds",
        type=int,
        default=None,
        help="Seconds of audio per extraction call, applied to every meeting this run "
        "processes regardless of its platform -- an explicit override that always wins over "
        "the defaults below (see _resolve_chunk_seconds()). Without this flag, --engine whisper "
        f"now picks a per-meeting default via the same chunk_size_seconds_for_platform() "
        f"app/main.py and worker/main.py already use: {CHUNK_SIZE_SECONDS}s for most platforms, "
        "300s for Granicus specifically (a cold-CDN-fill timeout risk at 900s, see that "
        "function's own comment -- WO-75, 2026-08-30). --engine gemini ignores platform "
        f"entirely and always defaults to {GEMINI_DEFAULT_CHUNK_SECONDS}s -- a "
        f"{CHUNK_SIZE_SECONDS}s chunk alone is {CHUNK_SIZE_SECONDS * 25} estimated input tokens, "
        "well over the free tier's entire 10000-tokens/minute budget in one call, a concern "
        "unrelated to Granicus's CDN timeout so it isn't platform-dependent.",
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
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore any partial-progress checkpoint left by an earlier run and transcribe every "
        "meeting from chunk 1. By default a meeting that failed partway through (see "
        "transcribe_meeting()) resumes from the chunks it already finished, which is the whole "
        "point of the checkpoint -- one real 55-chunk meeting lost 50 finished chunks to a single "
        "failure on chunk 51. Use this when you suspect the saved chunks themselves are bad (e.g. "
        "they were transcribed with a smaller --model-size, or before a transcription-quality fix "
        "shipped), since the checkpoint only validates the chunking, not the model that produced "
        "the text.",
    )
    parser.add_argument(
        "--cpu-threads",
        type=int,
        default=None,
        help="Cap faster-whisper/CTranslate2 to this many CPU threads. Defaults to half this "
        "Mac's real physical core count (minimum 1) -- see _pick_default_cpu_threads(). Fewer "
        "threads means slower transcription but a lower sustained power draw / less heat, the "
        "direct lever for running a long unattended batch without overheating an older machine. "
        "Pass 0 to use CTranslate2's own default (every visible core -- the worker's own "
        "behavior) if this machine has real thermal headroom to spare.",
    )
    parser.add_argument(
        "--chunk-cooldown-seconds",
        type=float,
        default=0.0,
        help="Rest this many seconds after every ~--chunk-seconds of Whisper work, before "
        "starting the next chunk -- the thermal duty-cycle knob for a long unattended run on "
        "older/fanless hardware. 0 (default) preserves the original back-to-back-chunks "
        "behavior. Combined with a CPU_Speed_Limit check via `pmset -g therm`: if macOS is "
        "already throttling after this sleep, the script waits longer (see "
        "--thermal-poll-seconds) instead of piling more work onto an already-hot CPU.",
    )
    parser.add_argument(
        "--thermal-poll-seconds",
        type=float,
        default=30.0,
        help="When --chunk-cooldown-seconds is set and macOS reports CPU_Speed_Limit < 100 "
        "(pmset -g therm) after a cooldown, re-check every this-many seconds until it recovers "
        "to 100 before resuming (default 30). No effect if --chunk-cooldown-seconds is 0, or on "
        "a non-Mac where pmset isn't available.",
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

    # No longer resolved to one value here -- as of WO-75 (2026-08-30) each
    # meeting gets its own chunk size in process_one(), via
    # _resolve_chunk_seconds(), once that meeting's real platform is known.
    # args.chunk_seconds (None unless --chunk-seconds was passed) is just
    # passed through as the override every meeting checks first.
    chunk_seconds_display = (
        f"{args.chunk_seconds} (explicit --chunk-seconds override)"
        if args.chunk_seconds is not None
        else (
            f"{GEMINI_DEFAULT_CHUNK_SECONDS} (--engine gemini default)"
            if args.engine == "gemini"
            else f"per-platform default via chunk_size_seconds_for_platform() "
            f"(usually {CHUNK_SIZE_SECONDS}, 300 for Granicus)"
        )
    )

    if args.engine == "gemini":
        if args.model_size is not None:
            logger.warning("--model-size is ignored with --engine gemini")
        if args.cpu_threads is not None:
            logger.warning("--cpu-threads is ignored with --engine gemini")
        if args.language is not None:
            logger.warning(
                "--language is ignored with --engine gemini (its request config already pins en-US)"
            )
        model_size = cpu_threads = None
    else:
        if args.gemini_tokens_per_minute is not None:
            logger.warning(
                "--gemini-tokens-per-minute is ignored with --engine whisper"
            )
        model_size = args.model_size or _pick_default_model_size()
        cpu_threads = (
            args.cpu_threads
            if args.cpu_threads is not None
            else _pick_default_cpu_threads()
        )

    # A real, plain-English "what is this run actually doing" line up front
    # -- someone checking on an unattended overnight run should be able to
    # see the real config (engine, model size, whether it's a dry run, how
    # many meetings it's targeting) from the top of the log without reading
    # Python source.
    logger.info(
        "Run started: engine=%s, language=%s, model_size=%s (%s), cpu_threads=%s (%s), "
        "chunk_cooldown_seconds=%s, limit=%s, newest_first=%s, dry_run=%s, chunk_seconds=%s, "
        "promote=%s, resume=%s, target=%s",
        args.engine,
        args.language or "(auto-detect)",
        model_size,
        "explicit --model-size" if args.model_size else "auto-picked from local RAM",
        cpu_threads,
        "explicit --cpu-threads"
        if args.cpu_threads is not None
        else "auto-picked from local core count",
        args.chunk_cooldown_seconds,
        args.limit if args.limit is not None else "(none -- full backlog)",
        args.newest_first,
        args.dry_run,
        chunk_seconds_display,
        args.promote,
        not args.no_resume,
        args.url or "(oldest-first backlog queue)",
    )

    register_all_finders()

    if args.engine == "gemini":
        from worker.transcription_engine import GeminiTranscriptionEngine

        gemini_kwargs = {}
        if args.gemini_tokens_per_minute is not None:
            gemini_kwargs["tokens_per_minute"] = args.gemini_tokens_per_minute
        try:
            engine = GeminiTranscriptionEngine(**gemini_kwargs)
        except RuntimeError as e:
            logger.error(str(e))
            sys.exit(1)
        logger.info("Gemini 3.5 Transcribe engine ready.")
    else:
        logger.info(
            "Loading faster-whisper model (this can take a while on first run, while weights download)..."
        )
        from worker.transcription_engine import FasterWhisperEngine

        engine = FasterWhisperEngine(
            model_size=model_size, cpu_threads=cpu_threads, language=args.language
        )
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
                pages = await _get_candidates(
                    session, args.limit, newest_first=args.newest_first
                )
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
                    chunk_seconds_override=args.chunk_seconds,
                    engine_kind=args.engine,
                    promote=args.promote,
                    resume=not args.no_resume,
                    chunk_cooldown_seconds=args.chunk_cooldown_seconds,
                    thermal_poll_seconds=args.thermal_poll_seconds,
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
