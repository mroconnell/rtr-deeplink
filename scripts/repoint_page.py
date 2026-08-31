"""Repoint an already-archived page at a different, real source of video --
for the case where the page was ingested from a URL that turns out to have
no video (a Hyland/OnBase agenda system is the recurring real example, see
BACKLOG_DONE.md's "Four archived pages pointed at agenda systems with no
video" entry), while the same meeting's real recording lives at a second,
separately-discovered URL (Granicus/CivicClerk/OMP, so far).

Same method as that entry's three real repoints (2 Santa Barbara, 1
Pittsburg CA, 2026-08-23): resolve the NEW source's URL through the normal
pipeline, then POST /internal/ingest with the resolved payload but the OLD
URL's normalized form as `input_url_normalized`. `crud._find_existing_page()`
checks the alias table before `external_id`, so this updates the existing
page in place -- same slug, same public URL, `"created": false` -- rather
than creating a duplicate. That original repoint was done as a one-off,
uncommitted call; this script exists so the next tenant in that entry's
"~12 genuinely open" residual doesn't need to re-derive the same call by
hand.

Two things worth knowing before running this for real:
* `source_url_normalized` on the resulting page still points at the OLD
  (video-less) URL -- that's what makes the repoint safe (a future
  auto-re-resolve of that URL can't wipe the content this adds, since
  video_url/agenda_items/transcript updates are all truthy-gated), but it
  also means `page.platform` will flip back on a future auto re-resolve
  (cosmetic only -- see the BACKLOG_DONE entry).
* This pushes to whatever ARCHIVE_BASE_URL resolves to (almost always the
  real deployed Archive) -- there's no local/prod distinction here, unlike
  DATABASE_URL. Run with --dry-run first and read the resolved payload
  before running for real.

Usage (from the repo root, with the venv active):
    python scripts/repoint_page.py OLD_URL NEW_URL --dry-run
    python scripts/repoint_page.py OLD_URL NEW_URL

Requires ARCHIVE_BASE_URL and ARCHIVE_INGEST_TOKEN in the repo's local
.env (or already exported) -- the real Render values, not the
.env.example placeholders.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path
from typing import Optional

import certifi

# Must run before `import aiohttp` -- see scripts/bulk_ingest.py's own
# comment on this same fix (a fresh Homebrew-Python venv has an empty
# default SSL trust store, and aiohttp/connector.py builds+caches its
# default SSLContext as a module-level statement evaluated the instant
# `import aiohttp` runs).
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import (
    CalendarPageError,
    UnsupportedPlatformError,
    detect_platform,
    get_finder,
)  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402

INGEST_TIMEOUT = aiohttp.ClientTimeout(total=65)  # matches archive_client.PUSH_TIMEOUT


def _base_url() -> str:
    return os.environ.get("ARCHIVE_BASE_URL", "").strip().rstrip("/")


def _headers() -> dict:
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


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


async def repoint(old_url: str, new_url: str, *, dry_run: bool) -> dict:
    """Resolves `new_url` and, unless dry_run, pushes it to the Archive
    under `old_url`'s normalized form. Returns a summary dict either way."""
    platform = detect_platform(new_url)
    try:
        finder = get_finder(platform)
    except UnsupportedPlatformError:
        return {
            "status": "failed",
            "detail": f"unsupported platform (detected: {platform!r})",
        }

    try:
        result = await finder.resolve(new_url)
    except CalendarPageError as e:
        return {
            "status": "failed",
            "detail": f"new_url is a calendar page, not a single meeting: {e}",
        }
    except Exception as e:
        return {"status": "failed", "detail": f"resolve raised: {e}"}

    summary = {
        "platform": result.platform,
        "title": result.title,
        "date": result.date,
        "jurisdiction": result.jurisdiction,
        "video_url": result.video_url,
        "segments": len(result.segments),
        "agenda_items": len(result.agenda_items),
        "transcript_warnings": result.transcript_warnings,
        "video_warnings": result.video_warnings,
    }

    if not (
        result.segments or result.agenda_items or result.agenda_link or result.video_url
    ):
        return {"status": "skipped", "detail": "nothing worth ingesting", **summary}

    old_normalized = normalize_url(old_url)
    if dry_run:
        return {
            "status": "dry-run",
            "detail": f"would repoint {old_normalized!r} to this payload",
            **summary,
        }

    async with aiohttp.ClientSession() as session:
        try:
            response = await _ingest(session, result.model_dump(), old_normalized)
        except Exception as e:
            return {"status": "failed", "detail": f"ingest failed: {e}", **summary}

    return {
        "status": "repointed",
        "detail": (response or {}).get("url") or "(no url in response)",
        "created": (response or {}).get("created"),
        **summary,
    }


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "old_url", help="The already-archived page's original source URL"
    )
    parser.add_argument("new_url", help="The real source that actually has the video")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve new_url and report, but don't actually push to the Archive",
    )
    args = parser.parse_args()

    if not _base_url():
        print(
            "ERROR: ARCHIVE_BASE_URL is not set (check the repo's .env).",
            file=sys.stderr,
        )
        sys.exit(1)
    if not args.dry_run and not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_INGEST_TOKEN is not set (check the repo's .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    register_all_finders()

    print(
        f"{'[DRY RUN] ' if args.dry_run else ''}Resolving {args.new_url} to repoint "
        f"{args.old_url} against {_base_url()}...\n"
    )
    result = await repoint(args.old_url, args.new_url, dry_run=args.dry_run)
    for key, value in result.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    asyncio.run(main())
