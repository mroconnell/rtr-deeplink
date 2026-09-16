"""Corrects `meeting_pages.date` on already-archived YouTube pages whose
video title states a date that disagrees with the stored date -- WO-288.

Why (see BACKLOG_DONE.md's WO-285 entry and BACKLOG.md's matching
"[NEEDS-AUDIT] 1,298 already-archived YouTube pages" entry): WO-285 fixed
`app/platforms/youtube.py`'s `_parse_meeting_date_from_title()` to prefer
a date parsed straight from the video's own title over `release_date`/
`upload_date`, for any NEW resolve. Pages archived before that fix are
still wrong, and readers see them. That entry's own next action was to
re-run the audit with the real production parser (not the audit's own
looser one) to get an honest count before writing anything -- this
script's dry run IS that re-run, against the live Archive DB, right
before it proposes a value.

**Population and buckets, re-derived live (2026-09-12), not assumed from
the WO-285 report.** A candidate page has `video_format="youtube"`, a
title, a stored `date`, and a date parseable from that title by the
real, unmodified `_parse_meeting_date_from_title()` -- the exact
function `app/platforms/youtube.py` uses on every new resolve, not a
looser audit-only regex. Of 4,032 such pages (live count, up from
WO-285's 3,764 a few hours earlier the same day -- the corpus keeps
growing): 1,528 have no production-parseable title date (left alone,
out of scope -- upload date is still the only signal for those), 1,151
already agree with the stored date (left alone), and 1,353 disagree,
split into the same two buckets Ryan's rule works from:

  * **off_by_one** (814 rows): the stored date is exactly one calendar
    day off from the title date -- the UTC-day-rollover shape (an
    evening US meeting, timestamped after midnight UTC) that the
    original `release_date`/`upload_date` fix from 2026-08-12 never
    fully closed. 813 of the 814 are the expected direction (stored =
    title + 1 day); the title date is taken directly for all of them.
    Rule 1's "otherwise, shift the stored date back one day only if the
    upload time is before 08:00 UTC" branch is for a row whose title
    carries NO production-parseable date -- by definition every row in
    this population already has one, so that branch covers zero rows
    here (reported, not assumed).
  * **off_by_more** (539 rows): more than a day off. A 20-row hand spot
    check (title + description + first archived caption lines, chosen
    with `random.seed(288)` over the live population for
    reproducibility -- see BACKLOG_DONE.md's WO-288 entry for the full
    per-row table) found the title date directly confirmed by an
    on-screen timestamp, a spoken roll-call date, or the video's own
    description in most rows, and named exactly one real exception
    (channel mislabeling, not a batch-upload gap) -- 19/20, clearing
    Ryan's own >=18/20 bar for "apply corpus-wide."

**Two safety exclusions apply on top of both buckets, found while
building this script, not anticipated in the brief:**

  1. **A title date in the future (relative to when this script runs)
     is never applied.** Three real rows had one, and a live check
     confirmed all three are title-authoring errors, not real dates: two
     ("July 13 2027" -- Smiths Falls, ON; "August 27, 2027" -- City of
     Bronson, MI) are a wrong year typed into an otherwise-correct
     title, confirmed by the same channel's other uploads all being
     2026; the third ("2026-09-17 City Council" -- Vermillion, SD) is
     confirmed wrong by the VIDEO'S OWN on-screen title card, which
     reads "September 8, 2026" -- exactly the already-stored date. All
     three are left unchanged, flagged `date-unverified`.
  2. **A title date pulled out of what is actually a raw upload
     timestamp embedded in the title, not a stated meeting date, is
     never applied.** One row ("Planning Commission - 8/12/2026
     1:00:00 AM", Las Vegas item planning commission) is the only
     off_by_one row in the WRONG direction (title = stored + 1 day,
     not stored = title + 1 day) out of 814, and its title carries a
     clock-shaped timestamp (`H:MM:SS AM/PM`) immediately after the
     date -- the signature of an auto-generated title, not a human
     stating "the meeting was on this date." Left unchanged, flagged
     `date-unverified`.

**Slugs are not touched.** A slug like
`aransas-pass-tx-2020-10-05-...` carries the date it was minted with
(WO-256's freeze/aliases; the hub and existing links depend on it) --
this script only ever changes `MeetingPage.date`, never `MeetingPage.
slug`. After this runs, a page's slug date and its corrected `date`
column can legitimately disagree; that is by design, not a bug.

**Old date preserved for revert.** Before writing, the row's previous
`date` is appended to `video_warnings` as
`"WO-288: date corrected from <old> to <new> (<reason>)"` -- the same
additive, deduped marker convention `archive/db/crud.py`'s
`video_marker` already uses -- so any single page can be reverted by
hand from that marker without needing a separate audit table.

Dry run by default (writes nothing) like every other backfill in this
directory; `--apply` writes. Two safety properties preserved from
`scripts/backfill_video_channel.py` / `scripts/backfill_gov_id.py`:
**commit per row** (a kill mid-run leaves a consistent partial state)
and **skip rows already matching the proposed value** (a re-run only
touches what's left, so it resumes rather than restarts).

Run this from the Archive service's Render Shell, not from a laptop
against the production `DATABASE_URL` -- CLAUDE.md's standing decision.
It touches only `meeting_pages.date`/`.video_warnings` (never
`segments`), so it is cheap, but the rule is about where a bulk write
runs, not how big it is.

Usage (from the repo root, with DATABASE_URL set to the Archive's own
database):
    python scripts/wo288_youtube_date_backfill.py                 # dry run
    python scripts/wo288_youtube_date_backfill.py --limit 50       # dry run, first 50
    python scripts/wo288_youtube_date_backfill.py --report /tmp/wo288_report.csv
    python scripts/wo288_youtube_date_backfill.py --apply
"""

import argparse
import asyncio
import csv
import datetime
import re
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Same shape as the one real off_by_one exception found live: a raw
# upload-system clock stamp riding along in the title text (not a human
# stating a meeting date). See the module docstring's exclusion #2.
_CLOCK_STAMP_RE = re.compile(r"\d{1,2}:\d{2}:\d{2}\s*(AM|PM)", re.IGNORECASE)

REASON_OFF_BY_ONE = "off_by_one_utc_rollover"
REASON_OFF_BY_MORE = "off_by_more_spot_checked_19_of_20"
REASON_EXC_FUTURE_TITLE_YEAR = "exception_future_title_date"
REASON_EXC_REVERSE_CLOCK_STAMP = "exception_reverse_direction_clock_stamp_title"


def classify_row(title: str, stored_date: str, today: datetime.date) -> Optional[dict]:
    """Returns None if this page isn't a candidate at all (no
    production-parseable title date, or title already agrees with
    stored). Otherwise returns a dict with bucket/proposed_date/reason/
    apply (apply=False means "report only, flagged date-unverified,
    never written even under --apply").
    """
    from app.platforms.youtube import _parse_meeting_date_from_title

    title_date = _parse_meeting_date_from_title(title)
    if title_date is None:
        return None

    try:
        stored_d = datetime.date.fromisoformat(stored_date[:10])
    except ValueError:
        return None
    title_d = datetime.date.fromisoformat(title_date)

    if stored_d == title_d:
        return None

    diff_days = (stored_d - title_d).days
    bucket = "off_by_one" if abs(diff_days) == 1 else "off_by_more"

    # Exclusion 1: a title date in the future relative to "today" (the
    # date this script actually runs) is a title-authoring error, not a
    # real date -- confirmed live on all 3 real rows this found (see
    # module docstring).
    if title_d > today:
        return {
            "title_date": title_date,
            "diff_days": diff_days,
            "bucket": bucket,
            "proposed_date": None,
            "apply": False,
            "reason": REASON_EXC_FUTURE_TITLE_YEAR,
        }

    # Exclusion 2: off_by_one in the wrong direction (title = stored + 1,
    # not stored = title + 1) with a raw clock timestamp in the title --
    # the one real case found live (see module docstring).
    if bucket == "off_by_one" and diff_days == -1 and _CLOCK_STAMP_RE.search(title):
        return {
            "title_date": title_date,
            "diff_days": diff_days,
            "bucket": bucket,
            "proposed_date": None,
            "apply": False,
            "reason": REASON_EXC_REVERSE_CLOCK_STAMP,
        }

    reason = REASON_OFF_BY_ONE if bucket == "off_by_one" else REASON_OFF_BY_MORE
    return {
        "title_date": title_date,
        "diff_days": diff_days,
        "bucket": bucket,
        "proposed_date": title_date,
        "apply": True,
        "reason": reason,
    }


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
        help="Write the full per-row dry-run diff to this CSV",
    )
    args = parser.parse_args()

    from sqlalchemy import select

    from archive.db.engine import async_session
    from archive.db.models import MeetingPage

    today = datetime.date.today()
    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"WO-288 YouTube page-date backfill -- {mode} (today={today.isoformat()})")

    async with async_session() as session:
        stmt = (
            select(
                MeetingPage.id,
                MeetingPage.slug,
                MeetingPage.title,
                MeetingPage.date,
            )
            .where(MeetingPage.video_format == "youtube")
            .where(MeetingPage.title.isnot(None))
            .where(MeetingPage.date.isnot(None))
            .order_by(MeetingPage.id.asc())
        )
        if args.limit:
            stmt = stmt.limit(args.limit)
        rows = (await session.execute(stmt)).all()

    print(f"  {len(rows)} youtube pages with a title and a stored date considered")

    counts = {
        "no_title_date": 0,
        "already_correct": 0,
        "off_by_one_applied": 0,
        "off_by_more_applied": 0,
        "exception_future_title_date": 0,
        "exception_reverse_clock_stamp": 0,
    }
    report_rows = []

    for page_id, slug, title, stored in rows:
        result = classify_row(title, stored, today)
        if result is None:
            # Distinguish "no title date at all" from "already correct"
            # only for the summary counts -- classify_row already does
            # both checks, re-derive cheaply for the label.
            from app.platforms.youtube import _parse_meeting_date_from_title

            if _parse_meeting_date_from_title(title) is None:
                counts["no_title_date"] += 1
            else:
                counts["already_correct"] += 1
            continue

        report_rows.append(
            {
                "page_id": page_id,
                "slug": slug,
                "title": title,
                "stored_date": stored,
                # Left blank on purpose, not omitted: the brief's report
                # shape names an "upload time" column so a reader can
                # judge rule 1's 08:00 UTC branch. That branch is never
                # reached here -- every candidate row already has a
                # production-parseable title date (see module docstring)
                # -- so no row ever needed a live re-fetch for it. Kept
                # as a real column rather than dropped, so that stays
                # visible in the CSV rather than silently assumed.
                "upload_time": "",
                "title_date": result["title_date"],
                "diff_days": result["diff_days"],
                "bucket": result["bucket"],
                "proposed_date": result["proposed_date"] or "",
                "reason": result["reason"],
            }
        )

        if result["reason"] == REASON_EXC_FUTURE_TITLE_YEAR:
            counts["exception_future_title_date"] += 1
        elif result["reason"] == REASON_EXC_REVERSE_CLOCK_STAMP:
            counts["exception_reverse_clock_stamp"] += 1
        elif result["bucket"] == "off_by_one":
            counts["off_by_one_applied"] += 1
        else:
            counts["off_by_more_applied"] += 1

        if args.apply and result["apply"]:
            async with async_session() as write_session:
                page = await write_session.get(MeetingPage, page_id)
                if page is None:
                    continue
                if page.date == result["proposed_date"]:
                    # Already matches (another writer/re-run got here
                    # first) -- nothing to do, matches the "skip rows
                    # already current" convention.
                    continue
                old_date = page.date
                marker = (
                    f"WO-288: date corrected from {old_date} to "
                    f"{result['proposed_date']} ({result['reason']})"
                )
                existing = page.video_warnings or []
                if marker not in existing:
                    page.video_warnings = [*existing, marker]
                page.date = result["proposed_date"]
                await write_session.commit()

    print("")
    print(f"  no production-parseable title date : {counts['no_title_date']}")
    print(f"  already correct (title == stored)  : {counts['already_correct']}")
    print(f"  off-by-one, title date applied     : {counts['off_by_one_applied']}")
    print(f"  off-by-more, title date applied    : {counts['off_by_more_applied']}")
    print(
        f"  exception: future title date       : {counts['exception_future_title_date']}"
    )
    print(
        f"  exception: reverse clock-stamp     : {counts['exception_reverse_clock_stamp']}"
    )

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        with open(args.report, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh,
                fieldnames=[
                    "page_id",
                    "slug",
                    "title",
                    "stored_date",
                    "upload_time",
                    "title_date",
                    "diff_days",
                    "bucket",
                    "proposed_date",
                    "reason",
                ],
            )
            writer.writeheader()
            writer.writerows(report_rows)
        print("")
        print(f"  per-row diff written to {args.report}")

    if not args.apply:
        print("")
        print("  DRY RUN -- nothing written. Re-run with --apply to commit.")


if __name__ == "__main__":
    asyncio.run(main())
