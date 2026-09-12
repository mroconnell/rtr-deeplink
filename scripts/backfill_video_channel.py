"""Backfill `meeting_pages.video_channel` (and `video_channel_id` where
known) for archived YouTube pages, from per-video channel maps this repo
already holds -- no YouTube calls of any kind.

Why (WO-246, 2026-09-11): until PR #999 (commit c592fa8, deployed
2026-09-11 as f7df68a), `app/platforms/youtube.py`'s `_extract_info()`
dropped the `uploader_id`/`uploader_url`/`channel_url`/`channel_id` keys
`_channel_handle()` and `resolve_video_id()` read, so every YouTube page
the resolver ever ingested carries `video_channel = NULL` (confirmed:
0 of 3,580 in the 2026-09-11 `/internal/export/pages` export). A
`tenant_overrides.csv` row shaped `www.youtube.com,channel=@Handle,...`
matches through `page_hints_for(channel=page.video_channel)`
(`app/utils/gov_registry/resolver.py`), so with every channel NULL, all
1,138 YouTube `channel=` pins in that file are inert for every already-
archived page -- they only fire for a page ingested by a client running
the fixed adapter.

This script does not call YouTube. It joins two files this repo already
has, both keyed by YouTube video id and built entirely from earlier work
(oEmbed lookups already made by `scripts/study_shared_host_discriminators.
py`, and a hand-worked pin worklist) -- see WO-246's report for the exact
counts:

  * `reports/pin_worklist_youtube.csv`   (video_id, channel, channel_title)
  * `reports/shared_host_lookups.csv`    (video_key, channel, channel_title)
                                          -- filtered to the `youtube:`
                                          prefix; also covers Vimeo, not
                                          used here.

Neither file carries a numeric YouTube channel id (only the `@handle`),
so `video_channel_id` is left NULL by this script -- nothing here claims
to know it. About half of the archived YouTube video ids (1,887 of 3,562
as of the 2026-09-11 export) have a channel in one of these two files;
the rest have no channel on record anywhere in the repo and need a real
oEmbed/yt-dlp lookup, which is `scripts/backfill_archived_pages.py
--platform youtube` -- a YouTube-calling script that must run from a
different machine (see BACKLOG.md/CLAUDE.md: this Mac's office
connection has no YouTube budget of its own while the drip owns it).

Like `scripts/backfill_gov_id.py`, this is a pure in-DB write with two
safety properties worth keeping: **commit per row** (a kill mid-run
leaves a consistent partial state) and **skip rows already set** (a
re-run only touches what's still NULL, so adding a channel to the map
files and re-running fills in exactly the newly-covered rows). Dry run
by default, matching every write endpoint/backfill in this repo's
"read-only-first" convention -- `--apply` writes.

Run it from the Archive service's Render Shell, not from a laptop
against the production `DATABASE_URL` -- CLAUDE.md's standing decision.
This script never touches `segments` (only `video_url`/`video_channel`/
`video_channel_id`), so it is cheap, but the rule is about where a bulk
write runs, not how big it is.

Usage (from the repo root, with DATABASE_URL set):
    python scripts/backfill_video_channel.py                  # dry run
    python scripts/backfill_video_channel.py --limit 50        # dry run, first 50
    python scripts/backfill_video_channel.py --apply
    python scripts/backfill_video_channel.py --apply --report /tmp/video_channel_backfill.csv

After this, `scripts/backfill_gov_id.py --apply` re-keys any page whose
new channel now matches a `tenant_overrides.csv` `channel=` pin.
"""

import argparse
import asyncio
import csv
import sys
from pathlib import Path
from typing import Dict, Optional, Tuple

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MAP_FILES = (
    REPO_ROOT / "reports" / "pin_worklist_youtube.csv",
    REPO_ROOT / "reports" / "shared_host_lookups.csv",
)


def load_channel_map(map_files) -> Dict[str, Tuple[str, Optional[str]]]:
    """Builds video_id -> (channel, channel_title) from every file in
    `map_files`, in order -- earlier files win a conflict (so
    `pin_worklist_youtube.csv`, the hand-worked one, is checked before
    `shared_host_lookups.csv`, the bulk oEmbed one). Understands two
    shapes: a plain `video_id` column (`pin_worklist_youtube.csv`), and a
    `video_key` column prefixed `youtube:` (`shared_host_lookups.csv`,
    shared with Vimeo's `vimeo:` rows -- anything else is skipped). Rows
    with a blank channel are skipped; `scripts/study_shared_host_
    discriminators.py` records those (oEmbed reachable but no channel
    found) rather than omitting the video entirely, so a blank isn't rare
    and isn't a bug in the source file.
    """
    mapping: Dict[str, Tuple[str, Optional[str]]] = {}
    for path in map_files:
        if not path.exists():
            continue
        with open(path, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if "video_id" in row:
                    video_id = (row.get("video_id") or "").strip()
                elif "video_key" in row:
                    key = (row.get("video_key") or "").strip()
                    if not key.startswith("youtube:"):
                        continue
                    video_id = key[len("youtube:") :]
                else:
                    continue
                channel = (row.get("channel") or "").strip()
                if not video_id or not channel:
                    continue
                if video_id in mapping:
                    continue
                mapping[video_id] = (
                    channel,
                    (row.get("channel_title") or "").strip() or None,
                )
    return mapping


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write. Without it this only reports (the default).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only consider the first N candidate pages, by id (for a smoke test)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Write the per-row diff to this CSV as well as summarizing it",
    )
    parser.add_argument(
        "--map-file",
        type=Path,
        action="append",
        default=None,
        help=(
            "Per-video channel map CSV (video_id or video_key + channel "
            "columns). Repeatable; earlier wins a conflict. Defaults to "
            "reports/pin_worklist_youtube.csv and "
            "reports/shared_host_lookups.csv."
        ),
    )
    args = parser.parse_args()

    map_files = args.map_file or list(DEFAULT_MAP_FILES)
    channel_map = load_channel_map(map_files)

    load_dotenv()

    from sqlalchemy import select

    from app.platforms.youtube_ids import extract_video_id
    from archive.db.engine import async_session
    from archive.db.models import MeetingPage

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"video_channel backfill -- {mode}")
    print(f"  {len(channel_map)} distinct video ids with a known channel, from:")
    for path in map_files:
        try:
            shown = path.relative_to(REPO_ROOT)
        except ValueError:
            shown = path
        print(f"    {shown}")

    async with async_session() as session:
        stmt = (
            select(
                MeetingPage.id,
                MeetingPage.slug,
                MeetingPage.video_url,
                MeetingPage.video_channel,
            )
            .where(MeetingPage.video_format == "youtube")
            .where(MeetingPage.video_channel.is_(None))
            .order_by(MeetingPage.id.asc())
        )
        if args.limit:
            stmt = stmt.limit(args.limit)
        rows = (await session.execute(stmt)).all()

    print(f"  {len(rows)} YouTube pages with no video_channel yet")

    changes = []
    no_video_id = 0
    not_in_map = 0

    for page_id, slug, video_url, _current_channel in rows:
        video_id = extract_video_id(video_url or "")
        if not video_id:
            no_video_id += 1
            continue
        found = channel_map.get(video_id)
        if not found:
            not_in_map += 1
            continue
        channel, channel_title = found

        changes.append(
            {
                "page_id": page_id,
                "slug": slug,
                "video_id": video_id,
                "channel": channel,
                "channel_title": channel_title or "",
            }
        )

        if args.apply:
            # Commit per row -- same reasoning as
            # scripts/backfill_gov_id.py: a kill mid-run leaves a
            # consistent partial state, and a re-run resumes rather than
            # restarts (video_channel.is_(None) above already skips
            # every row this has already touched).
            async with async_session() as write_session:
                page = await write_session.get(MeetingPage, page_id)
                if page is None or page.video_channel is not None:
                    # Set by another writer since the read above (or by
                    # the ordinary ingest path, if a fresh resolve of the
                    # same page raced this backfill) -- leave it alone
                    # rather than overwrite a value that is, if anything,
                    # more current than this script's static map.
                    continue
                page.video_channel = channel
                await write_session.commit()

    print("")
    label = "set    " if args.apply else "would set"
    print(f"  {label} : {len(changes)}")
    print(f"  no video id extractable from video_url : {no_video_id}")
    print(f"  video id not in any channel map        : {not_in_map}")

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with open(args.report, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=["page_id", "slug", "video_id", "channel", "channel_title"],
            )
            writer.writeheader()
            writer.writerows(changes)
        print("")
        print(f"  per-row diff written to {args.report}")

    if not args.apply:
        print("")
        print("  DRY RUN -- nothing written. Re-run with --apply to commit.")


if __name__ == "__main__":
    asyncio.run(main())
