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
YouTube-backed page with no default transcript) and pushing results back
through the same POST /internal/ingest every other transcript already
goes through -- idempotent, deduped by content hash, and matched to the
existing page by the identity fields the queue returns.

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
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import aiohttp
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms.youtube import YouTubeAssetFinder  # noqa: E402
from app.utils.vtt_parser import normalize_shouting_caption  # noqa: E402
from archive.utils.email import send_youtube_transcript_failure, send_youtube_transcript_report  # noqa: E402

# Gentler than bulk_ingest.py's 1.5s -- every request here hits YouTube
# from the operator's own home IP, and youtube-transcript-api's docs warn
# that too many requests get even residential IPs temporarily blocked.
REQUEST_DELAY_SECONDS = 5.0
INGEST_TIMEOUT = aiohttp.ClientTimeout(total=65)  # matches archive_client.PUSH_TIMEOUT -- tolerates a Render cold start

# Not the Archive's own internal ARCHIVE_BASE_URL (its Render URL) --
# emailed links need the real public domain, same distinction
# archive/main.py's own PUBLIC_BASE_URL usage makes for confirm/canonical
# links. Reuses the Archive's existing Resend integration
# (archive/utils/email.py) rather than a second one-off implementation --
# same RESEND_API_KEY/RESEND_FROM_ADDRESS already in the repo's local
# .env for other dev-time email testing.
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://redtaperecordings.com").rstrip("/")
REPORT_EMAIL_TO = os.environ.get("YOUTUBE_FETCH_REPORT_EMAIL", "ryan@how-to-adu.com")


def _base_url() -> str:
    return os.environ.get("ARCHIVE_BASE_URL", "").rstrip("/")


def _headers() -> dict:
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


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
        cues.append({
            "start": float(snippet.start),
            "end": float(snippet.start) + float(snippet.duration or 0),
            "text": text,
        })
    normalize_shouting_caption(cues)
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
        f"{_base_url()}/internal/transcript-wanted", headers=_headers(), timeout=INGEST_TIMEOUT
    ) as response:
        if response.status != 200:
            text = await response.text()
            raise RuntimeError(f"transcript-wanted failed ({response.status}): {text[:300]}")
        data = await response.json()
        return data.get("pages", [])


async def _ingest(session: aiohttp.ClientSession, payload: dict, input_url_normalized: str) -> Optional[dict]:
    body = dict(payload)
    body["input_url_normalized"] = input_url_normalized
    async with session.post(
        f"{_base_url()}/internal/ingest", json=body, headers=_headers(), timeout=INGEST_TIMEOUT
    ) as response:
        if response.status == 200:
            return await response.json()
        text = await response.text()
        raise RuntimeError(f"ingest failed ({response.status}): {text[:300]}")


async def process_one(session: aiohttp.ClientSession, page: dict, *, dry_run: bool) -> dict:
    """Returns {"slug", "status": "ingested"|"skipped"|"failed", "detail"}."""
    slug = page.get("slug", "?")
    video_id = YouTubeAssetFinder.extract_video_id(page.get("video_url") or "")
    if not video_id:
        return {"slug": slug, "status": "failed", "detail": f"no video id in video_url={page.get('video_url')!r}"}

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
        return {"slug": slug, "status": "failed", "detail": f"{type(e).__name__}: {str(e)[:200]}"}

    if not segments:
        return {"slug": slug, "status": "skipped", "detail": "transcript fetch returned no usable segments"}

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
    return {
        "slug": slug,
        "status": "ingested",
        "detail": f"{len(segments)} segments (language={language}) -> {page_url}",
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
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Fetch and report, but don't actually push")
    parser.add_argument("--limit", type=int, default=None, help="Process at most this many pages")
    args = parser.parse_args()

    if not _base_url():
        await _notify_failure(args.dry_run, "ARCHIVE_BASE_URL is not set (check the repo's .env).")
        sys.exit(1)
    if not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        await _notify_failure(args.dry_run, "ARCHIVE_INGEST_TOKEN is not set (check the repo's .env).")
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
                    await send_youtube_transcript_report(REPORT_EMAIL_TO, ingested=[], skipped=[], failed=[])
                return

            print(f"{'[DRY RUN] ' if args.dry_run else ''}{len(pages)} page(s) wanting transcripts on {_base_url()}...\n")

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
            for i, page in enumerate(pages):
                item_start = time.monotonic()
                try:
                    result = await process_one(session, page, dry_run=args.dry_run)
                except Exception as e:
                    await _notify_failure(
                        args.dry_run,
                        f"{type(e).__name__}: {str(e)[:300]} "
                        "(An IP-level block means further requests would all fail too -- try again later.)",
                    )
                    sys.exit(1)
                elapsed = time.monotonic() - item_start
                results.append(result)
                timestamp = datetime.now().strftime("%H:%M:%S")
                print(
                    f"[{timestamp}] [{result['status'].upper():8}] {result['slug']} ({elapsed:.1f}s)\n"
                    f"           {result['detail']}"
                )
                if i < len(pages) - 1:
                    await asyncio.sleep(REQUEST_DELAY_SECONDS)

            total_elapsed = time.monotonic() - run_start
            ingested = [r for r in results if r["status"] == "ingested"]
            skipped = [r for r in results if r["status"] == "skipped"]
            failed = [r for r in results if r["status"] == "failed"]
            avg = f", {total_elapsed / len(results):.1f}s/page average" if results else ""
            print(
                f"\n{len(ingested)} ingested, {len(skipped)} skipped, {len(failed)} failed (of {len(pages)} queued) "
                f"in {total_elapsed:.1f}s{avg}."
            )

            if not args.dry_run:
                await send_youtube_transcript_report(REPORT_EMAIL_TO, ingested=ingested, skipped=skipped, failed=failed)
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
