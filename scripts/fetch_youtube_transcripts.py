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

# Gentler than bulk_ingest.py's 1.5s -- every request here hits YouTube
# from the operator's own home IP, and youtube-transcript-api's docs warn
# that too many requests get even residential IPs temporarily blocked.
REQUEST_DELAY_SECONDS = 5.0
INGEST_TIMEOUT = aiohttp.ClientTimeout(total=65)  # matches archive_client.PUSH_TIMEOUT -- tolerates a Render cold start


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
    return {
        "slug": slug,
        "status": "ingested",
        "detail": f"{len(segments)} segments (language={language}) -> {response.get('url', '?')}",
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Fetch and report, but don't actually push")
    parser.add_argument("--limit", type=int, default=None, help="Process at most this many pages")
    args = parser.parse_args()

    if not _base_url():
        print("ERROR: ARCHIVE_BASE_URL is not set (check the repo's .env).", file=sys.stderr)
        sys.exit(1)
    if not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print("ERROR: ARCHIVE_INGEST_TOKEN is not set (check the repo's .env).", file=sys.stderr)
        sys.exit(1)

    async with aiohttp.ClientSession() as session:
        pages = await _get_wanted(session)
        if args.limit is not None:
            pages = pages[: args.limit]
        if not pages:
            print("Transcript-wanted queue is empty -- nothing to do.")
            return

        print(f"{'[DRY RUN] ' if args.dry_run else ''}{len(pages)} page(s) wanting transcripts on {_base_url()}...\n")

        # Wall-clock timestamps on each line matter here specifically
        # because this is meant to run unattended (see the launchd job in
        # scripts/com.redtaperecordings.fetch-youtube-transcripts.plist) --
        # the only way to see *when* something happened is the log file,
        # not someone watching the terminal live. Per-item timing exists
        # to answer a real question asked before this was built: fetching
        # an already-generated caption track is one API call, not audio
        # processing, so run time is independent of the meeting's actual
        # length -- these numbers are the actual proof of that, not an
        # estimate.
        run_start = time.monotonic()
        results = []
        for i, page in enumerate(pages):
            item_start = time.monotonic()
            try:
                result = await process_one(session, page, dry_run=args.dry_run)
            except Exception as e:
                print(f"\nABORTING: {type(e).__name__}: {str(e)[:300]}", file=sys.stderr)
                print("(An IP-level block means further requests would all fail too -- try again later.)", file=sys.stderr)
                break
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


if __name__ == "__main__":
    # Deliberately not called at module level -- this file is also
    # imported for snippets_to_segments() alone (tests/test_fetch_
    # youtube_transcripts.py), and load_dotenv() firing as an import side
    # effect raced against other test files' own os.environ.setdefault()
    # calls for ARCHIVE_INGEST_TOKEN, depending on pytest's collection
    # order -- a real, confirmed flake (see BACKLOG_DONE.md).
    load_dotenv()
    asyncio.run(main())
