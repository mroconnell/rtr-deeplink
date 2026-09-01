"""Fetch missing YouTube transcripts from a residential IP and push them
into the Archive.

Why this exists (confirmed live 2026-08-10): YouTube blocks caption
requests from cloud-provider IPs -- yt-dlp gets "Sign in to confirm you're
not a bot" from Render's shell, plain timedtext requests return 200 OK with
0 bytes, and youtube-transcript-api (a different InnerTube recipe) raises
IpBlocked from Render while working perfectly from a home connection
(1556 real segments for the same video that fails server-side, including
the human-typed CC1 track with real ">>" speaker markers, not just
auto-captions). So the server can't fetch these itself; this script runs
on a residential connection instead, consuming the Archive's own
"transcript wanted" queue (GET /internal/transcript-wanted: every
YouTube-backed page with no *good* default transcript -- missing
entirely, or present but flagged bad/garbled, see
list_youtube_pages_missing_transcripts()'s docstring) and pushing results
back through the same POST /internal/ingest every other transcript
already goes through -- idempotent, deduped by content hash, and matched
to the existing page by the identity fields the queue returns. When the
page already had a (bad) default transcript, a fresh push doesn't
automatically become the new default (archive/db/crud.py's
_is_real_improvement() is deliberately narrow), so this script always
follows up with POST /internal/transcript-version/promote -- a real
YouTube caption track is unconditionally more trustworthy than whatever
was already flagged bad, unlike scripts/transcribe_backlog_locally.py's
opt-in --promote for its own Whisper-based re-transcriptions.

Usage (from the repo root, with the venv active):
    python scripts/fetch_youtube_transcripts.py
    python scripts/fetch_youtube_transcripts.py --dry-run
    python scripts/fetch_youtube_transcripts.py --limit 5

Requires ARCHIVE_BASE_URL and ARCHIVE_INGEST_TOKEN in the repo's local
.env (same as scripts/bulk_ingest.py), plus `pip install -r
requirements-dev.txt` for youtube-transcript-api -- deliberately a dev
requirement, not a deploy one, since it's useless from the server's own
blocked IP.

On every real (non-dry-run) completion, emails a report to
YOUTUBE_FETCH_REPORT_EMAIL (default ryan@how-to-adu.com) via the
Archive's existing Resend integration (archive/utils/email.py) --
RESEND_API_KEY/RESEND_FROM_ADDRESS, same env vars the Archive service
already uses. Lists every transcript actually added, even an empty
report, so silence is itself a signal the daily launchd job stopped
firing rather than being indistinguishable from "nothing new today".
A run that fails to complete at all (an IP-level block, or any
unhandled exception) sends a different, explicitly-flagged failure
email instead of the routine report.
"""

import argparse
import asyncio
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import certifi

# Must run before `import aiohttp` -- see scripts/transcribe_backlog_
# locally.py's own longer comment on this same fix (confirmed live
# 2026-08-21: a fresh Homebrew-Python venv has an empty default SSL trust
# store, and aiohttp caches its default SSLContext at import time).
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms.youtube import YouTubeAssetFinder  # noqa: E402
from app.utils.vtt_parser import normalize_shouting_caption, unescape_caption_entities  # noqa: E402
from archive.utils.email import (
    send_youtube_transcript_failure,
    send_youtube_transcript_report,
)  # noqa: E402

# Gentler than bulk_ingest.py's 1.5s -- every request here hits YouTube
# from the operator's own home IP, and youtube-transcript-api's docs warn
# that too many requests get even residential IPs temporarily blocked.
# Jittered (see _jittered_delay()) rather than a flat sleep -- a perfectly
# uniform cadence is itself a bot signal; a small random spread is free
# politeness on top of the delay itself.
REQUEST_DELAY_SECONDS = 6.0
REQUEST_DELAY_JITTER_SECONDS = 2.0
INGEST_TIMEOUT = aiohttp.ClientTimeout(
    total=65
)  # matches archive_client.PUSH_TIMEOUT -- tolerates a Render cold start

# --- Rate-limit / IP-block backoff -----------------------------------------
# See docs/investigations/youtube_429_block.md (open as of 2026-08-31) before
# changing any of this. That investigation found something materially
# different from an ordinary rate limit: a burst of YouTube caption-fetch
# calls earned a *sustained* IP-level block that outlived at least 9 minutes
# of idling in one case, and took over a week to clear in another -- with a
# separate isolated, cold, unhurried single request also 429ing on a
# different day. In other words, this is not confirmed to be "wait a few
# minutes and it clears" -- it might be, but nobody has verified that, and
# the same doc explicitly warns: "Do not re-run a bulk YouTube sweep to test
# this... running more only risks extending whatever is causing it."
#
# So the backoff here is deliberately short and bounded, not a long
# retry-forever cooldown loop: two escalating retries of the *same* page
# (30s, then 120s -- roughly 5x and 20x the base per-request delay), and if
# a real block signal (see _is_rate_limit_signal() below) is still happening
# after that, this stops the ENTIRE run and sends the existing failure-email
# alert rather than parking on what might be a multi-day block. A human
# checking that alert can decide whether/when to re-run -- this script
# deliberately does not try to self-heal past this point, since more
# automatic retrying is exactly the behavior the investigation above warns
# against.
#
# Note this is a different code path (youtube-transcript-api, run from a
# residential IP) than the yt-dlp-based 429s the investigation doc's
# original 2026-08-22 finding hit (app/platforms/youtube.py's video
# resolve()) -- this script's own module docstring already establishes that
# youtube-transcript-api has worked reliably from a home connection since
# 2026-08-10. But both ultimately talk to the same YouTube backend, so an
# IP-level block triggered one way plausibly affects the other -- worth
# real caution here even though no block has been confirmed via this
# specific script yet.
RATE_LIMIT_BACKOFF_SECONDS = [30.0, 120.0]

# Not the Archive's own internal ARCHIVE_BASE_URL (its Render URL) --
# emailed links need the real public domain, same distinction
# archive/main.py's own PUBLIC_BASE_URL usage makes for confirm/canonical
# links. Reuses the Archive's existing Resend integration
# (archive/utils/email.py) rather than a second one-off implementation --
# same RESEND_API_KEY/RESEND_FROM_ADDRESS already in the repo's local
# .env for other dev-time email testing.
PUBLIC_BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL", "https://redtaperecordings.com"
).rstrip("/")
REPORT_EMAIL_TO = os.environ.get("YOUTUBE_FETCH_REPORT_EMAIL", "ryan@how-to-adu.com")


def _base_url() -> str:
    return os.environ.get("ARCHIVE_BASE_URL", "").rstrip("/")


def _headers() -> dict:
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _jittered_delay(base: float = REQUEST_DELAY_SECONDS) -> float:
    """`base` plus up to REQUEST_DELAY_JITTER_SECONDS of random spread, so
    consecutive requests don't land at a perfectly uniform cadence."""
    return base + random.uniform(0.0, REQUEST_DELAY_JITTER_SECONDS)


def _progress_note(results: List[dict]) -> str:
    """Short 'N ingested, M skipped, K failed so far' string for the abort
    email when a rate-limit backoff exhausts mid-run -- so the alert says
    how much of the run actually completed before it had to stop, not just
    that it stopped."""
    if not results:
        return "No pages were processed before this."
    ingested = sum(1 for r in results if r["status"] == "ingested")
    skipped = sum(1 for r in results if r["status"] == "skipped")
    failed = sum(1 for r in results if r["status"] == "failed")
    return (
        f"{ingested} ingested, {skipped} skipped, {failed} failed "
        f"({len(results)} page(s) processed before stopping)."
    )


def _is_rate_limit_signal(exc: BaseException) -> bool:
    """True for a real YouTube rate-limit/block signal, not an ordinary
    per-video failure (private video, live-not-started, disabled captions,
    removed) -- those are expected noise this queue surfaces regardless and
    must NOT trigger backoff.

    youtube-transcript-api's own `RequestBlocked` (parent of `IpBlocked`)
    already covers every real case confirmed in its source
    (_transcripts.py, this venv's installed copy): an HTTP 429 from
    YouTube's own InnerTube endpoint, a recaptcha challenge page, and the
    "Sign in to confirm you're not a bot" playability status all raise one
    of these two -- so isinstance is a precise check here, not a guess, and
    no separate string-matching (e.g. on "429" or "too many requests") is
    needed on top of it. Matched by class name rather than a top-level
    import so this module stays importable (and its pure functions
    testable, per this file's own __main__ guard comment) without
    youtube-transcript-api installed.
    """
    exc_type = type(exc)
    return any(c.__name__ in ("RequestBlocked", "IpBlocked") for c in exc_type.__mro__)


def snippets_to_segments(snippets) -> List[dict]:
    """Convert youtube-transcript-api snippets (.text/.start/.duration) to
    this app's segment dicts. Pure function, no library import needed --
    also what the tests exercise.

    - Blank/whitespace-only snippets are dropped (real CC1 tracks contain
      them as timing padding, confirmed on a real Minneapolis video).
    - A leading ">>" (a real character here, unlike the literal
      "&gt;&gt;" text normalize_speaker_change_marker() handles in raw
      VTT files) becomes the same "»" marker the rest of the site
      uses for speaker changes.
    - The whole track is then de-shouted via the existing
      normalize_shouting_caption() -- human-typed CC tracks are commonly
      ALL CAPS, same as the Granicus case that function was built for.
    """
    cues = []
    for snippet in snippets:
        text = (snippet.text or "").strip()
        if not text:
            continue
        if text.startswith(">>"):
            text = "» " + text[2:].lstrip()
        cues.append(
            {
                "start": float(snippet.start),
                "end": float(snippet.start) + float(snippet.duration or 0),
                "text": text,
            }
        )
    normalize_shouting_caption(cues)
    # Real gap fixed 2026-08-12: this conversion bypasses parse_vtt()
    # entirely (works from youtube-transcript-api snippets, not raw VTT
    # text), so it never picked up unescape_caption_entities() when that
    # was added there -- if a fetched snippet ever legitimately contains a
    # pre-escaped entity, this closes that gap here too. See its
    # docstring in app/utils/vtt_parser.py for why this is safe to run
    # unconditionally.
    unescape_caption_entities(cues)
    # normalize_shouting_caption()'s sentence-casing only capitalizes at
    # the start of the string or after sentence punctuation -- a leading
    # "» " marker hides the first letter from both. A speaker change
    # genuinely starts a new utterance, so capitalize it explicitly.
    for cue in cues:
        if cue["text"].startswith("» ") and len(cue["text"]) > 2:
            cue["text"] = "» " + cue["text"][2].upper() + cue["text"][3:]
    return cues


def fetch_transcript(video_id: str):
    """Returns (segments, language_code). Lazy-imports the library so the
    conversion logic above stays testable without it installed."""
    from youtube_transcript_api import YouTubeTranscriptApi

    transcript = YouTubeTranscriptApi().fetch(video_id)
    return snippets_to_segments(transcript.snippets), transcript.language_code


async def _get_wanted(session: aiohttp.ClientSession) -> List[dict]:
    async with session.get(
        f"{_base_url()}/internal/transcript-wanted",
        headers=_headers(),
        timeout=INGEST_TIMEOUT,
    ) as response:
        if response.status != 200:
            text = await response.text()
            raise RuntimeError(
                f"transcript-wanted failed ({response.status}): {text[:300]}"
            )
        data = await response.json()
        return data.get("pages", [])


async def _ingest(
    session: aiohttp.ClientSession, payload: dict, input_url_normalized: str
) -> Optional[dict]:
    body = dict(payload)
    body["input_url_normalized"] = input_url_normalized
    async with session.post(
        f"{_base_url()}/internal/ingest",
        json=body,
        headers=_headers(),
        timeout=INGEST_TIMEOUT,
    ) as response:
        if response.status == 200:
            return await response.json()
        text = await response.text()
        raise RuntimeError(f"ingest failed ({response.status}): {text[:300]}")


async def _promote(session: aiohttp.ClientSession, slug: str, version_id: int) -> dict:
    """POST /internal/transcript-version/promote -- makes `version_id` the
    page's default TranscriptVersion. Real gap fixed 2026-08-16 (WO-15,
    BACKLOG.md): since the transcript-wanted queue now also surfaces pages
    whose default is present-but-garbled (not just missing entirely -- see
    list_youtube_pages_missing_transcripts()'s docstring), a fresh push for
    those does NOT automatically become the page's default -- the current
    default already has segments+language, so archive/db/crud.py's
    _is_real_improvement() declines to auto-promote (deliberately narrow,
    to avoid unpredictably flip-flopping the default). Unlike
    scripts/transcribe_backlog_locally.py's opt-in --promote (a Whisper
    audio re-transcription, quality varies, worth a human's say-so), a
    genuinely-fetched real YouTube caption track is unconditionally more
    trustworthy than whatever's already flagged bad, so this script always
    promotes rather than gating it behind a flag. Never demotes the old
    version out of existence -- promote_transcript_version()'s own
    docstring: it stays reachable via `?version=`, this only flips which
    one is_default. A no-op (not an error) when the pushed version was
    already the default (e.g. the original "no transcript at all" case,
    where ingest_resolution() already made it the default at creation).

    Passes clear_warnings=True: real gap fixed 2026-08-20 -- ingest_resolution()
    dedupes by content hash, so when this script re-fetches the same
    underlying caption track (via youtube-transcript-api, a different
    library than whatever originally resolved the page), it reuses the
    existing version row rather than creating a fresh one -- meaning any
    stale garbled/hallucination warning on it survived promotion until
    now, despite that being exactly the "trust this over whatever's
    already there" case described above. See
    manually_promote_transcript_version()'s docstring for the confirmed
    example (nashua-2025-05-28-committee-on-infrastructure).
    """
    async with session.post(
        f"{_base_url()}/internal/transcript-version/promote",
        json={"slug": slug, "version_id": version_id, "clear_warnings": True},
        headers=_headers(),
        timeout=INGEST_TIMEOUT,
    ) as response:
        if response.status == 200:
            return await response.json()
        text = await response.text()
        raise RuntimeError(f"promote failed ({response.status}): {text[:300]}")


async def process_one(
    session: aiohttp.ClientSession, page: dict, *, dry_run: bool
) -> dict:
    """Returns {"slug", "status": "ingested"|"skipped"|"failed", "detail"}."""
    slug = page.get("slug", "?")
    video_id = YouTubeAssetFinder.extract_video_id(page.get("video_url") or "")
    if not video_id:
        return {
            "slug": slug,
            "status": "failed",
            "detail": f"no video id in video_url={page.get('video_url')!r}",
        }

    try:
        # fetch_transcript is synchronous (the library has no async API);
        # fine for a sequential local batch script.
        segments, language = fetch_transcript(video_id)
    except Exception as e:
        # IpBlocked/RequestBlocked mean every further request will fail
        # too -- let the caller abort the whole run rather than burning
        # through the queue generating identical failures.
        if type(e).__name__ in ("IpBlocked", "RequestBlocked"):
            raise
        return {
            "slug": slug,
            "status": "failed",
            "detail": f"{type(e).__name__}: {str(e)[:200]}",
        }

    if not segments:
        return {
            "slug": slug,
            "status": "skipped",
            "detail": "transcript fetch returned no usable segments",
        }

    if dry_run:
        return {
            "slug": slug,
            "status": "skipped",
            "detail": f"[dry-run] would push {len(segments)} segments (language={language}) for video {video_id}",
        }

    payload = {
        # Identity fields exactly as the queue returned them, so
        # _find_or_create_page() matches the existing page instead of
        # creating a duplicate. title/date/jurisdiction/agenda_items are
        # deliberately omitted -- ingest keeps the page's existing values
        # for anything the payload doesn't provide.
        "platform": page["platform"],
        "source_url": page["source_url_normalized"],
        "external_id": page.get("external_id"),
        "video_url": page.get("video_url"),
        "video_format": "youtube",
        "segments": segments,
        "transcript_language": language,
    }
    response = await _ingest(session, payload, page["source_url_normalized"])
    page_url = response.get("url", "")
    version_id = response.get("version_id")
    promote_detail = ""
    if version_id is not None:
        await _promote(session, response.get("slug", slug), version_id)
        promote_detail = " (promoted to default)"
    return {
        "slug": slug,
        "status": "ingested",
        "detail": f"{len(segments)} segments (language={language}) -> {page_url}{promote_detail}",
        # Only meaningful for status=="ingested" -- consumed by
        # send_youtube_transcript_report() to build the email's list,
        # kept out of "detail" (the console/log string) since a plain
        # string is all that needs.
        "title": page.get("title") or slug,
        "page_url": f"{PUBLIC_BASE_URL}{page_url}" if page_url else PUBLIC_BASE_URL,
        "segment_count": len(segments),
    }


async def _notify_failure(dry_run: bool, error_message: str) -> None:
    print(f"\nABORTING: {error_message}", file=sys.stderr)
    if dry_run:
        return
    # Best-effort -- send_youtube_transcript_failure() already catches and
    # logs its own errors rather than raising (see archive/utils/email.py's
    # _send()), so a Resend outage on top of everything else still just
    # falls through to the log file, not a second crash.
    await send_youtube_transcript_failure(REPORT_EMAIL_TO, error_message=error_message)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and report, but don't actually push",
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Process at most this many pages"
    )
    args = parser.parse_args()

    if not _base_url():
        await _notify_failure(
            args.dry_run, "ARCHIVE_BASE_URL is not set (check the repo's .env)."
        )
        sys.exit(1)
    if not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        await _notify_failure(
            args.dry_run, "ARCHIVE_INGEST_TOKEN is not set (check the repo's .env)."
        )
        sys.exit(1)

    # Everything past this point can fail in ways worth a real alert --
    # the Archive being unreachable, an unexpected exception, or (via the
    # `raise` in process_one() below) an IP-level block -- so the whole
    # body runs under one try/except rather than letting any of those
    # surface only as a silent non-zero exit in a log file nobody's
    # watching live.
    try:
        async with aiohttp.ClientSession() as session:
            pages = await _get_wanted(session)
            if args.limit is not None:
                pages = pages[: args.limit]
            if not pages:
                print("Transcript-wanted queue is empty -- nothing to do.")
                if not args.dry_run:
                    await send_youtube_transcript_report(
                        REPORT_EMAIL_TO, ingested=[], skipped=[], failed=[]
                    )
                return

            print(
                f"{'[DRY RUN] ' if args.dry_run else ''}{len(pages)} page(s) wanting transcripts on {_base_url()}...\n"
            )

            # Wall-clock timestamps on each line matter here specifically
            # because this is meant to run unattended (see the launchd job
            # in scripts/com.redtaperecordings.fetch-youtube-transcripts.plist)
            # -- the only way to see *when* something happened is the log
            # file, not someone watching the terminal live. Per-item timing
            # exists to answer a real question asked before this was
            # built: fetching an already-generated caption track is one
            # API call, not audio processing, so run time is independent
            # of the meeting's actual length -- these numbers are the
            # actual proof of that, not an estimate.
            run_start = time.monotonic()
            results = []
            backoff_events = 0
            for i, page in enumerate(pages):
                item_start = time.monotonic()
                # Bounded retry of THIS SAME page on a real rate-limit/block
                # signal -- see RATE_LIMIT_BACKOFF_SECONDS's own comment for
                # why this is short and bounded rather than a long
                # retry-forever cooldown loop (docs/investigations/
                # youtube_429_block.md). block_attempt indexes into
                # RATE_LIMIT_BACKOFF_SECONDS; once it runs out, the whole
                # run stops (same as the previous unconditional-abort
                # behavior this replaces), it just isn't the FIRST block
                # signal that triggers it anymore.
                block_attempt = 0
                while True:
                    try:
                        result = await process_one(session, page, dry_run=args.dry_run)
                        break
                    except Exception as e:
                        if not _is_rate_limit_signal(e):
                            await _notify_failure(
                                args.dry_run,
                                f"{type(e).__name__}: {str(e)[:300]} "
                                "(not a recognized rate-limit signal -- aborting rather than "
                                "guessing at a backoff)",
                            )
                            sys.exit(1)
                        if block_attempt >= len(RATE_LIMIT_BACKOFF_SECONDS):
                            await _notify_failure(
                                args.dry_run,
                                f"{type(e).__name__}: {str(e)[:300]} -- still hitting a YouTube "
                                f"rate-limit/block signal after {block_attempt} backoff retr"
                                f"{'y' if block_attempt == 1 else 'ies'} on {page.get('slug', '?')}. "
                                "Stopping the whole run here rather than continuing to retry -- "
                                "see docs/investigations/youtube_429_block.md, this may be a "
                                "sustained IP-level block that outlasts minutes (one confirmed "
                                "case took over a week to clear), so keeping this run alive to "
                                "poll it would itself be the kind of repeated hammering that "
                                f"investigation warns against. {_progress_note(results)}",
                            )
                            sys.exit(1)
                        delay = RATE_LIMIT_BACKOFF_SECONDS[block_attempt]
                        block_attempt += 1
                        backoff_events += 1
                        print(
                            f"[{datetime.now().strftime('%H:%M:%S')}] [BACKOFF ] "
                            f"{page.get('slug', '?')}: {type(e).__name__} looks like a real "
                            f"YouTube rate-limit/block signal (not an ordinary per-video "
                            f"failure) -- backing off {delay:.0f}s before retrying this same "
                            f"page (attempt {block_attempt}/{len(RATE_LIMIT_BACKOFF_SECONDS)})"
                        )
                        await asyncio.sleep(delay)
                elapsed = time.monotonic() - item_start
                results.append(result)
                timestamp = datetime.now().strftime("%H:%M:%S")
                print(
                    f"[{timestamp}] [{result['status'].upper():8}] {result['slug']} ({elapsed:.1f}s)\n"
                    f"           {result['detail']}"
                )
                if i < len(pages) - 1:
                    await asyncio.sleep(_jittered_delay())

            total_elapsed = time.monotonic() - run_start
            if backoff_events:
                print(
                    f"\n{backoff_events} rate-limit backoff event(s) occurred during this run "
                    "(see BACKOFF lines above) -- the run still completed, but this is worth "
                    "noting in docs/investigations/youtube_429_block.md if it happens again."
                )
            ingested = [r for r in results if r["status"] == "ingested"]
            skipped = [r for r in results if r["status"] == "skipped"]
            failed = [r for r in results if r["status"] == "failed"]
            avg = (
                f", {total_elapsed / len(results):.1f}s/page average" if results else ""
            )
            print(
                f"\n{len(ingested)} ingested, {len(skipped)} skipped, {len(failed)} failed (of {len(pages)} queued) "
                f"in {total_elapsed:.1f}s{avg}."
            )

            if not args.dry_run:
                await send_youtube_transcript_report(
                    REPORT_EMAIL_TO, ingested=ingested, skipped=skipped, failed=failed
                )
    except Exception as e:
        await _notify_failure(args.dry_run, f"{type(e).__name__}: {str(e)[:300]}")
        sys.exit(1)


if __name__ == "__main__":
    # Deliberately not called at module level -- this file is also
    # imported for snippets_to_segments() alone (tests/test_fetch_
    # youtube_transcripts.py), and load_dotenv() firing as an import side
    # effect raced against other test files' own os.environ.setdefault()
    # calls for ARCHIVE_INGEST_TOKEN, depending on pytest's collection
    # order -- a real, confirmed flake (see BACKLOG_DONE.md).
    load_dotenv()
    asyncio.run(main())
