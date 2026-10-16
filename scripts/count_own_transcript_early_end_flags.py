"""Count our own transcripts that carry the "may end before the meeting did"
warning (read-only).

    python scripts/count_own_transcript_early_end_flags.py [--list]

Run it from the Archive service's Render shell, where DATABASE_URL is the
Archive's own database. It reads only ids, timestamps and the small
`transcript_warnings` list of each own ("transcribed") version, never the
`segments` blob, and changes nothing.

What it counts. Every TranscriptVersion whose `source` is "transcribed"
(our own Whisper: the cloud worker, scripts/transcribe_backlog_locally.py,
scripts/retranscribe_first_chunk.py). A version is "flagged" when its
warnings contain the early-end marker. Since 2026-10-16 our own
transcription adds that warning only after sampling the audio after the
last cue and finding sound there (app/platforms/coverage_check.py,
own_transcript_early_end_warning()). Older own versions were never
checked, so a low count on them means "not checked", not "complete".

Output: one table with three rows (all own versions, flagged, flagged and
shown as the page's default), then, with --list, one line per flagged
version: page slug, version id, whether it is the default, and when it was
made.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


async def run(args: argparse.Namespace) -> int:
    from sqlalchemy import Text, cast, func, select

    from archive.db.crud import _EARLY_TRUNCATION_MARKER
    from archive.db.engine import async_session
    from archive.db.models import MeetingPage, TranscriptVersion

    own = TranscriptVersion.source == "transcribed"
    flagged = cast(TranscriptVersion.transcript_warnings, Text).like(
        f"%{_EARLY_TRUNCATION_MARKER}%"
    )
    async with async_session() as db:
        total = (
            await db.execute(select(func.count(TranscriptVersion.id)).where(own))
        ).scalar_one()
        rows = (
            await db.execute(
                select(
                    MeetingPage.slug,
                    TranscriptVersion.id,
                    TranscriptVersion.is_default,
                    TranscriptVersion.created_at,
                )
                .join(MeetingPage, MeetingPage.id == TranscriptVersion.meeting_page_id)
                .where(own, flagged)
                .order_by(TranscriptVersion.created_at.desc())
            )
        ).all()

    shown = sum(1 for r in rows if r.is_default)
    print("Own transcripts (source = transcribed)        Count")
    print(f"All own versions                             {total}")
    print(f"Flagged 'may end before the meeting did'     {len(rows)}")
    print(f"Flagged and shown as the page's default      {shown}")
    if args.list:
        print()
        for r in rows:
            made = r.created_at.isoformat() if r.created_at else "unknown"
            default = "default" if r.is_default else "hidden"
            print(f"{r.slug}\tversion {r.id}\t{default}\t{made}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--list", action="store_true", help="also print one line per flagged version"
    )
    return asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
