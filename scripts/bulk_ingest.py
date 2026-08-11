"""Bulk-ingest a list of meeting URLs into the Archive.

Reuses the exact same resolve pipeline every real adapter and /api/resolve
already go through (app/platforms/base.py's detect_platform()/get_finder()),
then POSTs directly to the Archive's own POST /internal/ingest -- the same
endpoint app/archive_client.py's push() calls, except that fire-and-forget
helper discards the response, and this script needs the real returned
{"slug", "url"} back to confirm where each meeting landed.

Deliberately calls the underlying Python functions rather than going
through the deployed resolver's HTTP /api/resolve -- that route is rate-
limited (20/minute, slowapi, app/main.py), a decorator on the FastAPI route
itself, not enforced anywhere in the call stack this script actually uses.
Appropriate here since a bulk run is a deliberate, human-approved batch
action, not the case that limit exists to guard against.

Usage (from the repo root, with the venv active):
    python scripts/bulk_ingest.py urls.txt
    python scripts/bulk_ingest.py urls.txt --dry-run
    python scripts/bulk_ingest.py --playlist "https://www.youtube.com/playlist?list=..."

urls.txt: one URL per line; blank lines and lines starting with # are
ignored. A line that's itself a YouTube playlist/watch?list= URL is
expanded to its member video URLs at run time (via yt-dlp's flat
extraction -- confirmed live 2026-08-11 against a real 66-video "Town
Council Meetings" playlist), so a playlist URL can also just be dropped
into the file directly instead of using --playlist.

Requires ARCHIVE_BASE_URL and ARCHIVE_INGEST_TOKEN in the repo's local
.env (or already exported in the environment) -- the real Render values
for the deployed Archive service, not the .env.example placeholders.
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import List, Optional
from urllib.parse import parse_qs, urlparse

import aiohttp
import yt_dlp
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()

import os  # noqa: E402 -- after load_dotenv() so ARCHIVE_* are populated by the time _base_url()/_headers() below read them

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import detect_platform, get_finder, UnsupportedPlatformError, CalendarPageError  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402

REQUEST_DELAY_SECONDS = 1.5
INGEST_TIMEOUT = aiohttp.ClientTimeout(total=65)  # matches archive_client.PUSH_TIMEOUT -- tolerates a Render cold start


def _base_url() -> str:
    return os.environ.get("ARCHIVE_BASE_URL", "").rstrip("/")


def _headers() -> dict:
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


def _read_urls(path: str) -> List[str]:
    urls = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            urls.append(line)
    return urls


def _playlist_id(url: str) -> Optional[str]:
    """Returns the `list=` query param if present -- covers both a bare
    playlist URL (youtube.com/playlist?list=...) and a single video's URL
    when it was copied from within a playlist (watch?v=...&list=...).
    Either shape means "expand this to every video in the playlist", not
    just the one video."""
    query = parse_qs(urlparse(url).query)
    values = query.get("list")
    return values[0] if values else None


def _expand_playlist(playlist_id: str) -> List[str]:
    """Flat-extracts a YouTube playlist's member video URLs via yt-dlp,
    without downloading anything. Confirmed live 2026-08-11 against a
    real 66-video "Town Council Meetings" playlist -- ordinary
    extract_flat, no special options needed the way single-video
    resolves in app/platforms/youtube.py do (that file's player_client
    workaround is for the anti-bot check on actual caption/format
    extraction, which flat playlist listing never touches)."""
    opts = {"extract_flat": True, "quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/playlist?list={playlist_id}", download=False)
    entries = (info or {}).get("entries") or []
    return [e["url"] for e in entries if e.get("url")]


def _expand_urls(urls: List[str]) -> List[str]:
    """Replaces any playlist/in-playlist URL in the list with its member
    video URLs, preserving order and leaving every other URL untouched."""
    expanded: List[str] = []
    for url in urls:
        playlist_id = _playlist_id(url)
        if not playlist_id:
            expanded.append(url)
            continue
        video_urls = _expand_playlist(playlist_id)
        print(f"[PLAYLIST] {url}\n           expanded to {len(video_urls)} video(s)")
        expanded.extend(video_urls)
    return expanded


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


async def process_one(session: aiohttp.ClientSession, url: str, *, dry_run: bool) -> dict:
    """Returns a result dict: {"url", "status": "ingested"|"skipped"|"failed", "detail"}."""
    try:
        platform = detect_platform(url)
        finder = get_finder(platform)
    except UnsupportedPlatformError:
        return {"url": url, "status": "failed", "detail": f"unsupported platform (detected: {platform!r})"}

    try:
        result = await finder.resolve(url)
    except CalendarPageError as e:
        return {"url": url, "status": "failed", "detail": f"calendar page, not a single meeting: {e}"}
    except Exception as e:
        return {"url": url, "status": "failed", "detail": f"resolve raised: {e}"}

    # Same gate app/main.py's /api/resolve already uses to decide whether a
    # resolve is worth pushing to the Archive at all.
    if not (result.segments or result.agenda_items or result.agenda_link):
        return {
            "url": url,
            "status": "skipped",
            "detail": f"platform={result.platform}, no transcript, agenda items, or agenda link found",
        }

    normalized = normalize_url(url)
    if dry_run:
        return {
            "url": url,
            "status": "skipped",
            "detail": (
                f"[dry-run] would ingest: platform={result.platform}, title={result.title!r}, "
                f"segments={len(result.segments)}, agenda_items={len(result.agenda_items)}"
            ),
        }

    try:
        response = await _ingest(session, result.model_dump(), normalized)
    except Exception as e:
        return {"url": url, "status": "failed", "detail": f"ingest failed: {e}"}

    page_url = response.get("url") if response else None
    return {"url": url, "status": "ingested", "detail": page_url or "(no url in response)"}


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "urls_file", nargs="?", help="Path to a text file with one meeting URL per line (omit if using --playlist alone)"
    )
    parser.add_argument(
        "--playlist",
        action="append",
        default=[],
        metavar="URL",
        help="A YouTube playlist (or in-playlist video) URL to expand and ingest; repeatable",
    )
    parser.add_argument("--dry-run", action="store_true", help="Resolve and report, but don't actually ingest")
    args = parser.parse_args()

    if not _base_url():
        print("ERROR: ARCHIVE_BASE_URL is not set (check the repo's .env).", file=sys.stderr)
        sys.exit(1)
    if not args.dry_run and not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print("ERROR: ARCHIVE_INGEST_TOKEN is not set (check the repo's .env).", file=sys.stderr)
        sys.exit(1)

    if not args.urls_file and not args.playlist:
        print("ERROR: pass a urls_file, --playlist, or both.", file=sys.stderr)
        sys.exit(1)

    raw_urls = (_read_urls(args.urls_file) if args.urls_file else []) + list(args.playlist)
    if not raw_urls:
        print(f"No URLs found in {args.urls_file}.", file=sys.stderr)
        sys.exit(1)

    urls = _expand_urls(raw_urls)
    if not urls:
        print("No URLs left after playlist expansion.", file=sys.stderr)
        sys.exit(1)

    register_all_finders()

    print(f"{'[DRY RUN] ' if args.dry_run else ''}Processing {len(urls)} URL(s) against {_base_url()}...\n")

    results = []
    async with aiohttp.ClientSession() as session:
        for i, url in enumerate(urls):
            result = await process_one(session, url, dry_run=args.dry_run)
            results.append(result)
            print(f"[{result['status'].upper():8}] {url}\n           {result['detail']}")
            if i < len(urls) - 1:
                await asyncio.sleep(REQUEST_DELAY_SECONDS)

    ingested = [r for r in results if r["status"] == "ingested"]
    skipped = [r for r in results if r["status"] == "skipped"]
    failed = [r for r in results if r["status"] == "failed"]
    print(f"\n{len(ingested)} ingested, {len(skipped)} skipped, {len(failed)} failed (of {len(urls)} total).")


if __name__ == "__main__":
    asyncio.run(main())
