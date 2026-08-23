"""Backfill the jurisdiction-bleed fix (PRs #158/#161) onto MeetingPage
rows archived before either fix existed -- see BACKLOG.md's
"Jurisdiction-bleed, confirmed cross-platform" entry.

Pure HTTP client, same ARCHIVE_BASE_URL/ARCHIVE_INGEST_TOKEN pattern as
scripts/fetch_youtube_transcripts.py -- calls the Archive's own
POST /internal/jurisdiction/backfill-apply, never touches the database
directly. That endpoint always recomputes candidates itself from each
row's stored inputs (never trusts a client-supplied jurisdiction string),
so this script's only job is: show the operator the diff, get a typed
confirmation, then flip dry_run off.

Usage (from the repo root, with the venv active, ARCHIVE_BASE_URL/
ARCHIVE_INGEST_TOKEN set in .env):
    python scripts/backfill_jurisdiction_bleed.py

Always calls with dry_run=true first and prints the full before/after
diff. If there's nothing to change, exits without prompting. Otherwise
asks for a typed "apply" confirmation before calling again with
dry_run=false and printing the real result.
"""

import asyncio
import os
import sys
from pathlib import Path

import certifi

# Must run before `import aiohttp` -- see scripts/transcribe_backlog_
# locally.py's own longer comment on this same fix (confirmed live
# 2026-08-21: a fresh Homebrew-Python venv has an empty default SSL trust
# store, and aiohttp caches its default SSLContext at import time).
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=65)  # tolerates a Render cold start


def _base_url() -> str:
    return os.environ.get("ARCHIVE_BASE_URL", "").rstrip("/")


def _headers() -> dict:
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


async def _call(session: aiohttp.ClientSession, *, dry_run: bool) -> dict:
    async with session.post(
        f"{_base_url()}/internal/jurisdiction/backfill-apply",
        params={"dry_run": "true" if dry_run else "false"},
        headers=_headers(),
        timeout=REQUEST_TIMEOUT,
    ) as response:
        if response.status != 200:
            text = await response.text()
            raise RuntimeError(
                f"backfill-apply failed ({response.status}): {text[:300]}"
            )
        return await response.json()


def _print_diff(result: dict) -> None:
    changes = result["changes"]
    print(f"{len(changes)} row(s) would change:\n")
    for change in changes:
        print(f"  [{change['meeting_page_id']}] {change['slug']}")
        print(
            f"    before: {change['before']['jurisdiction']!r} "
            f"(confidence={change['before']['jurisdiction_confidence']!r})"
        )
        print(
            f"    after:  {change['after']['jurisdiction']!r} "
            f"(confidence={change['after']['jurisdiction_confidence']!r})"
        )
        print()


async def main() -> None:
    if not _base_url():
        print("ARCHIVE_BASE_URL is not set (check the repo's .env).", file=sys.stderr)
        sys.exit(1)
    if not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ARCHIVE_INGEST_TOKEN is not set (check the repo's .env).", file=sys.stderr
        )
        sys.exit(1)

    async with aiohttp.ClientSession() as session:
        print(f"Dry-running against {_base_url()}...\n")
        dry_result = await _call(session, dry_run=True)
        _print_diff(dry_result)

        if dry_result["applied_count"] == 0:
            print("Nothing to backfill. Done.")
            return

        confirmation = input(
            f'Type "apply" to write these {dry_result["applied_count"]} change(s) '
            f"for real, or anything else to abort: "
        )
        if confirmation.strip().lower() != "apply":
            print("Aborted -- no changes written.")
            return

        print("\nApplying...\n")
        real_result = await _call(session, dry_run=False)
        _print_diff(real_result)
        print(f"Done. {real_result['applied_count']} row(s) updated.")


if __name__ == "__main__":
    # Deliberately not called at module level -- same reasoning as
    # scripts/send_search_alerts.py's matching comment.
    load_dotenv()
    asyncio.run(main())
