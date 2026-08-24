"""Find transcripts that stop before the meeting did, and mark the ones
we can prove.

**Why this exists.** app/platforms/granicus.py flags a scraped caption
file with exactly 36,000 cues -- Granicus's own undocumented cap -- and
archive/db/crud.py's `_TRUNCATION_MARKERS` turns that warning into the
`truncated_transcript` audit bucket and, more importantly, into "this
page still wants a real transcription attempt"
(`_has_real_warning_free_transcript()`). But that flag is applied *at
ingest*, and it only started existing on 2026-08-23. Every page archived
before then that hit the cap carries no warning at all: it reads as a
perfectly good transcript, counts as `success` in the quality audit, and
is permanently excluded from the auto-transcription pool. Those pages are
invisible by construction -- nothing else in the codebase looks at how
many segments a stored transcript has.

**Read-only by default, and the read is the point.** The first run is not
a fix, it is a measurement: it prints the real distribution of large
segment counts across the archive, which answers two questions this repo
currently answers by assumption. (1) How many unmarked pages are sitting
on exactly 36,000? (2) Is 36,000 actually the only cap -- granicus.py's
own comment admits "doesn't catch a cap at some other round number", and
a spike at some other round value in this output would be the first
evidence either way. Do not skip straight to --apply.

**`--apply` writes one thing only**: it appends the same truncation
warning granicus.py would have written to any *default* transcript
version with exactly 36,000 segments that doesn't already carry it. That
is deliberately the narrowest possible action -- a count of exactly
36,000 is essentially impossible to hit by chance (three independent real
customers confirmed, see BACKLOG.md), whereas any threshold-based rule
would be guessing. Marking a page makes it eligible for re-transcription
again; it does not delete or replace the transcript it has.

Segment counts are computed in SQL (`json_array_length`, which both
Postgres and SQLite provide) so this never pulls a `segments` blob across
the network -- the whole-archive scan is one cheap query, not the ~1 GB
transfer that made scripts/backfill_meeting_highlights.py a six-hour run
when it was mistakenly run from a laptop. Even so, run it from the
Archive's own Render Shell like every other script here: it still holds
the production database's attention, and there is no reason to do that
over the public internet.

Usage (from the repo root, with the venv active, DATABASE_URL set):
    python scripts/scan_truncated_transcripts.py
    python scripts/scan_truncated_transcripts.py --min-count 20000
    python scripts/scan_truncated_transcripts.py --apply

Idempotent: --apply skips versions that already carry the marker, so a
re-run does nothing and an interrupted run resumes cleanly (it commits
per row, same convention as every backfill in this directory).
"""

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# The exact cue count Granicus's captions.vtt truncates at. Kept here
# rather than imported from app/platforms/granicus.py because that module
# pulls the whole resolver adapter stack in behind it, and archive/
# deliberately does not import from app/ (see crud.py's own note on the
# duplicated outcome buckets). If this ever changes, both places change.
GRANICUS_CUE_CAP = 36000

# What granicus.py writes today. Must keep containing crud.py's
# _GRANICUS_TRUNCATION_MARKER substring, which is what every downstream
# gate actually matches on.
TRUNCATION_WARNING = (
    "This transcript may be cut off — it hit exactly "
    "36,000 lines, a known limit in Granicus's own "
    "captioning for very long meetings."
)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--min-count",
        type=int,
        default=30000,
        help=(
            "Report every default transcript with at least this many "
            "segments (default: 30000). Lower it to look for a cap at some "
            "other round number."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Write the truncation warning onto unmarked versions sitting on "
            f"exactly {GRANICUS_CUE_CAP} segments. Report-only without this."
        ),
    )
    args = parser.parse_args()

    load_dotenv()

    # Imported after load_dotenv() -- archive.db.engine builds its engine
    # from DATABASE_URL at import time. Same ordering as every other
    # script here.
    from sqlalchemy import func, select

    from archive.db.crud import _GRANICUS_TRUNCATION_MARKER
    from archive.db.engine import async_session
    from archive.db.models import MeetingPage, TranscriptVersion

    segment_count = func.json_array_length(TranscriptVersion.segments)

    async with async_session() as session:
        rows = (
            await session.execute(
                select(
                    TranscriptVersion.id,
                    TranscriptVersion.transcript_warnings,
                    TranscriptVersion.source,
                    MeetingPage.slug,
                    MeetingPage.platform,
                    segment_count.label("segments"),
                )
                .join(MeetingPage, MeetingPage.id == TranscriptVersion.meeting_page_id)
                .where(
                    TranscriptVersion.is_default.is_(True),
                    segment_count >= args.min_count,
                )
                .order_by(segment_count.desc())
            )
        ).all()

    if not rows:
        print(f"No default transcript has {args.min_count}+ segments.")
        return

    # The distribution first: a cap shows up as many pages sharing one
    # exact count, which is the signal a list of slugs would bury.
    by_count = Counter(row.segments for row in rows)
    print(f"{len(rows)} default transcript(s) with {args.min_count}+ segments.\n")
    print("  segments  pages  (a repeated exact count is what a cap looks like)")
    for count, pages in sorted(by_count.items(), reverse=True):
        flag = "  <-- known Granicus cap" if count == GRANICUS_CUE_CAP else ""
        print(f"  {count:>8}  {pages:>5}{flag}")

    at_cap = [row for row in rows if row.segments == GRANICUS_CUE_CAP]
    unmarked = [
        row
        for row in at_cap
        if not any(
            _GRANICUS_TRUNCATION_MARKER in w for w in (row.transcript_warnings or [])
        )
    ]
    print(
        f"\nAt exactly {GRANICUS_CUE_CAP}: {len(at_cap)} page(s), "
        f"{len(unmarked)} of them unmarked."
    )
    for row in unmarked:
        print(f"  /m/{row.slug}  ({row.platform}, source={row.source})")

    if not unmarked:
        return
    if not args.apply:
        print("\nReport only. Re-run with --apply to mark the pages listed above.")
        return

    marked = 0
    for row in unmarked:
        # Re-read and re-check inside the write transaction rather than
        # trusting the scan above: this script is slow enough to overlap a
        # real ingest, and an ingest that just wrote the marker itself
        # must not end up with two copies of it.
        async with async_session() as session:
            version = await session.get(TranscriptVersion, row.id)
            if version is None:
                continue
            warnings = list(version.transcript_warnings or [])
            if any(_GRANICUS_TRUNCATION_MARKER in w for w in warnings):
                continue
            warnings.append(TRUNCATION_WARNING)
            # Reassigned rather than mutated in place: transcript_warnings
            # is a plain JSON column, so SQLAlchemy only sees a change when
            # the attribute is set to a new object.
            version.transcript_warnings = warnings
            await session.commit()
            marked += 1
        print(f"  marked /m/{row.slug}")

    print(
        f"\nMarked {marked} page(s). They are now eligible for re-transcription "
        "again (archive/db/crud.py's find_auto_transcription_candidate())."
    )


if __name__ == "__main__":
    asyncio.run(main())
