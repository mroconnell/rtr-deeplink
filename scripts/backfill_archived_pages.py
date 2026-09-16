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

`--missing-channel-only` restricts the sweep to pages whose
`video_channel` is still NULL or blank (WO-295). Why this exists: until
PR #999 (2026-09-11) the YouTube adapter dropped the video's channel, so
~3,464 archived YouTube pages ended up with `video_channel` NULL.
`scripts/backfill_video_channel.py` (WO-246) fills ~1,903 of those for
free from per-video records already in this repo -- no YouTube call at
all. The remaining ~1,676 have no channel on record anywhere and need a
real re-resolve, which is this script -- but without this flag it would
re-touch all 3,464 pages, most of which need no re-resolve at all. Run
`backfill_video_channel.py --apply` first so this flag's candidate set is
already down to the genuinely-unfilled remainder. Every page this flag
selects is (as of WO-295) a YouTube page, so combine it with
`--platform youtube`:
    python scripts/backfill_archived_pages.py --platform youtube --missing-channel-only --dry-run --limit 20
    python scripts/backfill_archived_pages.py --platform youtube --missing-channel-only --delay 3

This script's YouTube calls must be paced and run only from the drip
Mac (see CLAUDE.md's "YouTube drip ownership" note) -- never against
production from a laptop, and always with a real `--delay` (3s is the
convention used elsewhere in this repo for YouTube-calling scripts).

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


def filter_pages(
    pages: list[dict],
    *,
    platform: str | None = None,
    url_contains: str | None = None,
    missing_channel_only: bool = False,
    limit: int | None = None,
) -> list[dict]:
    """Applies this script's four candidate-selection flags, in the same
    order `main()` always has, to a raw `list_all_page_urls()`-shaped list.
    Pulled out as its own function (WO-295) so --missing-channel-only's
    filtering logic -- and its combination with the pre-existing flags --
    is unit-testable against plain dicts, without a live Archive or a real
    resolve. `missing_channel_only` treats both a NULL `video_channel`
    (the key absent or None) and a blank string the same way; a stray
    empty string shouldn't count as "has a channel" any more than NULL
    does.
    """
    if platform:
        pages = [p for p in pages if p["platform"] == platform]
    if url_contains:
        pages = [p for p in pages if url_contains in p["source_url_normalized"]]
    if missing_channel_only:
        pages = [p for p in pages if not (p.get("video_channel") or "").strip()]
    if limit:
        pages = pages[:limit]
    return pages


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve every page for real, but never push",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only process the first N pages (for testing)",
    )
    parser.add_argument(
        "--platform",
        type=str,
        default=None,
        help="Only process pages on this platform (e.g. swagit)",
    )
    parser.add_argument(
        "--url-contains",
        type=str,
        default=None,
        help="Only process pages whose source URL contains this substring (e.g. longbeachca)",
    )
    parser.add_argument(
        "--missing-channel-only",
        action="store_true",
        help=(
            "Only process pages whose video_channel is still NULL or blank "
            "(WO-295) -- combine with --platform youtube to restrict the "
            "post-PR-999/WO-246 re-resolve sweep to the pages that "
            "actually still need one, instead of every archived YouTube page"
        ),
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=2.0,
        help="Seconds to wait between each page (default 2.0)",
    )
    args = parser.parse_args()

    # Imported here, not at module level -- app.main builds a real FastAPI
    # app (route registration etc.) and app.archive_client reads env vars
    # at call time, so load_dotenv() below must run first, same
    # import-order reasoning as this repo's other CLI scripts.
    from app import archive_client
    from app.main import _recheck_archived_page
    from app.platforms.base import detect_platform
    from app.utils.rate_limit import looks_rate_limited

    pages = await archive_client.list_all_page_urls()
    if pages is None:
        print(
            "ABORTING: could not reach the Archive (check ARCHIVE_BASE_URL/ARCHIVE_INGEST_TOKEN).",
            file=sys.stderr,
        )
        sys.exit(1)

    pages = filter_pages(
        pages,
        platform=args.platform,
        url_contains=args.url_contains,
        missing_channel_only=args.missing_channel_only,
        limit=args.limit,
    )

    if not pages:
        print("No matching pages to process.")
        return

    label = "DRY RUN -- " if args.dry_run else ""
    print(f"{label}Rechecking {len(pages)} archived page(s), {args.delay}s apart...\n")

    changed = 0
    failed = 0
    # This script had no circuit breaker at all until 2026-08-22. Its
    # sibling scripts/dedupe_rollup_transcripts.py had one whose
    # threshold was only checked on one of two failure paths, and a real
    # run sent ten consecutive requests into a live 429 block because of
    # it. Same driver shape here -- many re-resolves against a handful of
    # hosts -- so the same protection applies, plus the hair-trigger
    # rate-limit stop: a 429 means the far end is refusing this caller,
    # so continuing both cannot succeed and plausibly extends the block.
    MAX_CONSECUTIVE_FAILURES = 5
    consecutive_failures = 0
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
            consecutive_failures += 1
            detail = f"{result['error']}: {str(result.get('message', ''))[:150]}"
            print(
                f"[{i}/{len(pages)}] {slug}: FAILED ({detail}) "
                f"[{consecutive_failures}/{MAX_CONSECUTIVE_FAILURES} consecutive]"
            )
            if looks_rate_limited(detail):
                print(
                    "\nStopping: that looks like a rate limit or block, not "
                    "a broken page. Every further request is both certain to "
                    "fail and likely to extend it. Wait hours, not minutes, "
                    "then re-run."
                )
                break
            if consecutive_failures >= MAX_CONSECUTIVE_FAILURES:
                print(
                    f"\nStopping after {consecutive_failures} consecutive "
                    "failures -- something systemic is wrong, not one bad page."
                )
                break
        elif result["pushed"]:
            consecutive_failures = 0
            changed += 1
            verb = "would push" if args.dry_run else "pushed"
            print(
                f"[{i}/{len(pages)}] {slug}: {verb} -- jurisdiction={result['jurisdiction']!r}"
            )
        else:
            consecutive_failures = 0
            print(f"[{i}/{len(pages)}] {slug}: no real content found, skipped")

        if i < len(pages):
            await asyncio.sleep(args.delay)

    skipped = len(pages) - changed - failed
    verb = "would be updated" if args.dry_run else "updated"
    print(
        f"\nDone. {changed} page(s) {verb}, {failed} failed, {skipped} had nothing new to push."
    )


if __name__ == "__main__":
    # Deliberately not called at module level -- same reasoning as this
    # repo's other CLI scripts.
    load_dotenv()
    asyncio.run(main())
