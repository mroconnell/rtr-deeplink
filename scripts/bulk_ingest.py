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

urls.txt: one URL per line; blank lines and lines starting with # are
ignored.

Requires ARCHIVE_BASE_URL and ARCHIVE_INGEST_TOKEN in the repo's local
.env (or already exported in the environment) -- the real Render values
for the deployed Archive service, not the .env.example placeholders.
"""

import argparse
import asyncio
import sys
from pathlib import Path
from typing import List, Optional

import aiohttp
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
    if not (result.segments or result.agenda_items):
        return {
            "url": url,
            "status": "skipped",
            "detail": f"platform={result.platform}, no transcript or agenda items found",
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
    parser.add_argument("urls_file", help="Path to a text file with one meeting URL per line")
    parser.add_argument("--dry-run", action="store_true", help="Resolve and report, but don't actually ingest")
    args = parser.parse_args()

    if not _base_url():
        print("ERROR: ARCHIVE_BASE_URL is not set (check the repo's .env).", file=sys.stderr)
        sys.exit(1)
    if not args.dry_run and not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print("ERROR: ARCHIVE_INGEST_TOKEN is not set (check the repo's .env).", file=sys.stderr)
        sys.exit(1)

    urls = _read_urls(args.urls_file)
    if not urls:
        print(f"No URLs found in {args.urls_file}.", file=sys.stderr)
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
