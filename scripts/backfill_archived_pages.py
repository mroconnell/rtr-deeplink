"""Re-resolve every archived meeting page and push whatever's found, so
already-shipped adapter/jurisdiction fixes reach pages that were archived
*before* those fixes existed -- not just new resolves going forward.

Why this exists (confirmed live 2026-08-13): `MeetingPage.jurisdiction`
(and every other field) is set once at ingest and never re-checked on its
own -- visiting an archived `/m/*` page never triggers a recheck, only
resubmitting its exact original URL through `/api/resolve` does, and only
past its recheck window. Seven separate, already-fixed jurisdiction bugs
were confirmed still showing their old wrong value on already-archived
pages purely because nobody had resubmitted those URLs since the fix
shipped -- see `BACKLOG.md`'s "archived pages don't self-heal" entry for
the full list (Long Beach, San Francisco/Denver, Fresno, Napa and other
CA cities, Memphis, Jacksonville, a PrimeGov page, a Viebit/NYCC page).
This script is the bulk version of the existing one-URL-at-a-time
`GET /admin/recheck-archive-page` -- reuses that exact same resolve+push
logic (`app.main._recheck_archived_page()`), just looped over every page.

This hits potentially hundreds of different real government websites, not
one server -- real politeness matters here, more than raw speed. Runs
strictly sequentially (never concurrently) with a configurable delay
between every single page, regardless of which site it's on (several
pages can share the same source domain -- e.g. many different Long Beach
meetings all live on the same `longbeachca.new.swagit.com`).

Usage (from the repo root, with the venv active):
    python scripts/backfill_archived_pages.py --dry-run
    python scripts/backfill_archived_pages.py --dry-run --limit 5
    python scripts/backfill_archived_pages.py --dry-run --platform swagit
    python scripts/backfill_archived_pages.py --dry-run --url-contains longbeachca
    python scripts/backfill_archived_pages.py --delay 3

`--dry-run` re-resolves every page for real (so you can see exactly what
would change) but never pushes anything to the Archive -- the only way to
safely preview a real run against real production data before ever
letting it write anything. Always run `--dry-run` first, and probably
scoped with `--limit`/`--platform` first too, before a full unscoped run.

Requires `ARCHIVE_BASE_URL` and `ARCHIVE_INGEST_TOKEN` (same as this
repo's other batch scripts, e.g. `scripts/fetch_youtube_transcripts.py`)
-- this imports `app.main` directly to reuse its exact resolve+push
logic, so it needs whatever env `app.main` itself needs at import time
(the adapters' own network calls, no extra credentials beyond the above
for this script's own purposes).
"""

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Resolve every page for real, but never push")
    parser.add_argument("--limit", type=int, default=None, help="Only process the first N pages (for testing)")
    parser.add_argument("--platform", type=str, default=None, help="Only process pages on this platform (e.g. swagit)")
    parser.add_argument(
        "--url-contains", type=str, default=None,
        help="Only process pages whose source URL contains this substring (e.g. longbeachca)",
    )
    parser.add_argument("--delay", type=float, default=2.0, help="Seconds to wait between each page (default 2.0)")
    args = parser.parse_args()

    # Imported here, not at module level -- app.main builds a real FastAPI
    # app (route registration etc.) and app.archive_client reads env vars
    # at call time, so load_dotenv() below must run first, same
    # import-order reasoning as this repo's other CLI scripts.
    from app import archive_client
    from app.main import _recheck_archived_page
    from app.platforms.base import detect_platform

    pages = await archive_client.list_all_page_urls()
    if pages is None:
        print(
            "ABORTING: could not reach the Archive (check ARCHIVE_BASE_URL/ARCHIVE_INGEST_TOKEN).",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.platform:
        pages = [p for p in pages if p["platform"] == args.platform]
    if args.url_contains:
        pages = [p for p in pages if args.url_contains in p["source_url_normalized"]]
    if args.limit:
        pages = pages[: args.limit]

    if not pages:
        print("No matching pages to process.")
        return

    label = "DRY RUN -- " if args.dry_run else ""
    print(f"{label}Rechecking {len(pages)} archived page(s), {args.delay}s apart...\n")

    changed = 0
    failed = 0
    for i, page in enumerate(pages, 1):
        slug = page["slug"]
        url = page["source_url_normalized"]
        # Re-detect from the URL rather than trusting the stored platform
        # field -- MeetingPage.platform records the *delegated* finder's
        # name (e.g. "youtube"), not the original one, for platforms that
        # delegate (PrimeGov, LIMS, CivicWeb, generic_fallback's YouTube
        # branch). Those deliberately keep the *original* source URL
        # stored (not the delegated YouTube URL) specifically so a
        # re-resolve goes through their own scraping logic again -- same
        # reasoning /admin/recheck-archive-page (app/main.py) already
        # uses. Passing the stored "youtube" platform straight to
        # get_finder() here would hand a LIMS/PrimeGov URL to
        # YouTubeAssetFinder directly, which can't find a video ID in a
        # non-YouTube URL -- confirmed live 2026-08-13: every LIMS and
        # PrimeGov page in a first backfill dry-run failed exactly this
        # way before this fix.
        platform = detect_platform(url)

        result = await _recheck_archived_page(url, url, platform, dry_run=args.dry_run)

        if "error" in result:
            failed += 1
            print(f"[{i}/{len(pages)}] {slug}: FAILED ({result['error']}: {str(result.get('message', ''))[:150]})")
        elif result["pushed"]:
            changed += 1
            verb = "would push" if args.dry_run else "pushed"
            print(f"[{i}/{len(pages)}] {slug}: {verb} -- jurisdiction={result['jurisdiction']!r}")
        else:
            print(f"[{i}/{len(pages)}] {slug}: no real content found, skipped")

        if i < len(pages):
            await asyncio.sleep(args.delay)

    skipped = len(pages) - changed - failed
    verb = "would be updated" if args.dry_run else "updated"
    print(f"\nDone. {changed} page(s) {verb}, {failed} failed, {skipped} had nothing new to push.")


if __name__ == "__main__":
    # Deliberately not called at module level -- same reasoning as this
    # repo's other CLI scripts.
    load_dotenv()
    asyncio.run(main())
