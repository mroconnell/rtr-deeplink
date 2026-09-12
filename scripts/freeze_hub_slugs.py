"""Mint and freeze one permanent `/j/{slug}` per government -- WO-256.

Two jobs in one sweep, both idempotent:

  1. **Mint a missing row.** Every government with at least one archived
     page gets a `hub_slugs` row whose `hub_slug` is *exactly what the
     site computes for it today* (`crud.live_hub_slug()`), so the first
     run of this script changes zero live URLs. `first_seen_at` is
     backdated to that government's OLDEST page, not to now: the freeze
     gate asks "has this government settled down," and the archive
     already knows the answer for a government it has held for months.
  2. **Freeze what has earned it.** `hub_slugs.apply_gate()` sets
     `frozen_at` once a government has been known for
     `hub_slugs.FREEZE_AFTER` (7 days) AND has more than one page --
     Ryan's gate, 2026-09-12. An unfrozen row's `hub_slug` is refreshed to
     today's computation on every run, so churn on a brand-new government
     settles before anything becomes permanent.

Why the sweep exists at all, given that ingest records a government's row
itself: a government that has stopped being ingested would never reach
its own gate. Run this after a pin round, after a scoring run, or on any
day the hub-slug table and the archive might have drifted. See
`archive/db/models.py`'s `HubSlug` docstring for the design and
`docs/investigations/hub_architecture_audit.md` §4 for the measurements
behind it.

A frozen row is never touched by this script. Renaming a frozen slug is a
deliberate, one-at-a-time act that costs one `archive/data/
hub_slug_aliases.csv` row, exactly as a rename does today -- there is no
bulk path for it on purpose.

Dry run by DEFAULT, like `scripts/backfill_gov_id.py`: this writes the
column that decides what a reader's URL is, so a bare invocation only
reports. Two safety properties, the same two every backfill here has:
**commit per row** (a kill mid-run leaves a consistent partial state) and
**skip rows already current** (a re-run resumes rather than restarts).

Run it from the Archive service's Render Shell, never from a laptop
against the production `DATABASE_URL` -- CLAUDE.md's standing decision.
It reads three short columns and never touches `segments`, so it is
cheap, but the rule is about where a bulk workload runs, not how big it
is.

Usage (from the repo root, with DATABASE_URL set):
    python scripts/freeze_hub_slugs.py                  # dry run, full report
    python scripts/freeze_hub_slugs.py --limit 100      # dry run, first 100 govs
    python scripts/freeze_hub_slugs.py --apply          # write
    python scripts/freeze_hub_slugs.py --report /tmp/hub_slugs.csv
"""

import argparse
import asyncio
import csv
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


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
        help="Only consider the first N governments, by gov_id (for a smoke test)",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Write the per-government decision to this CSV as well as summarizing it",
    )
    args = parser.parse_args()

    load_dotenv()

    from sqlalchemy import func, select

    from archive.db import hub_slugs
    from archive.db.crud import live_hub_slug
    from archive.db.engine import async_session
    from archive.db.models import HubSlug, MeetingPage

    mode = "APPLY" if args.apply else "DRY RUN"
    print(f"hub slug freeze -- {mode}")

    async with async_session() as session:
        if not await hub_slugs.table_available(session):
            print(
                "  hub_slugs table does not exist on this database yet -- run "
                "`cd archive && alembic upgrade head` first. Nothing done."
            )
            return
        # One row per government: its oldest page (the freeze clock), its
        # page count (the gate's other half) and one jurisdiction string
        # (the fallback the slug comes from for a minted id the registry
        # has not scored yet). MIN(jurisdiction) rather than "the most
        # common one": for a government WITH a registry row the string is
        # not consulted at all, and for one without it, every page's
        # string is the same cleaned minted name by construction.
        rows = (
            await session.execute(
                select(
                    MeetingPage.gov_id,
                    func.count(),
                    func.min(MeetingPage.created_at),
                    func.min(MeetingPage.jurisdiction),
                )
                .where(MeetingPage.gov_id.is_not(None))
                .group_by(MeetingPage.gov_id)
                .order_by(MeetingPage.gov_id.asc())
            )
        ).all()
        existing = {
            gov_id: (slug, first_seen_at, frozen_at)
            for gov_id, slug, first_seen_at, frozen_at in (
                await session.execute(
                    select(
                        HubSlug.gov_id,
                        HubSlug.hub_slug,
                        HubSlug.first_seen_at,
                        HubSlug.frozen_at,
                    )
                )
            ).all()
        }

    governments = [r for r in rows if hub_slugs._usable(r[0])]
    if args.limit:
        governments = governments[: args.limit]
    print(
        f"  {len(rows)} governments with pages, {len(governments)} of them hub-eligible"
    )
    print(f"  {len(existing)} hub_slugs rows already exist")

    outcomes: Counter = Counter()
    decisions = []

    for gov_id, count, oldest, jurisdiction in governments:
        slug = live_hub_slug(gov_id, jurisdiction)
        if not slug:
            # No registry row AND no usable jurisdiction text -- nothing to
            # mint. Counted, never guessed at.
            outcomes["no_slug_derivable"] += 1
            decisions.append(
                {
                    "gov_id": gov_id,
                    "pages": count,
                    "hub_slug": "",
                    "outcome": "no_slug_derivable",
                }
            )
            continue
        row = existing.get(gov_id)
        if row and row[2] is not None:
            outcomes["already_frozen"] += 1
            decisions.append(
                {
                    "gov_id": gov_id,
                    "pages": count,
                    "hub_slug": row[0],
                    "outcome": (
                        "already_frozen"
                        if row[0] == slug
                        # A frozen slug that no longer matches what the
                        # site would compute is the whole point of the
                        # freeze working -- reported, never "fixed" here.
                        else "already_frozen_name_since_changed"
                    ),
                }
            )
            continue

        if args.apply:
            # Commit per government -- same reasoning as every other
            # backfill here: a kill mid-run leaves a consistent partial
            # state, and a re-run resumes (an already-frozen row is
            # skipped above).
            async with async_session() as write_session:
                await hub_slugs.record_government(
                    write_session, gov_id, slug, first_seen_at=oldest
                )
                await write_session.commit()
                frozen = (
                    await write_session.execute(
                        select(HubSlug.frozen_at).where(HubSlug.gov_id == gov_id)
                    )
                ).scalar()
            outcome = "frozen" if frozen is not None else "recorded_not_yet_eligible"
        else:
            # The same two questions apply_gate() asks, without writing.
            first_seen = (row[1] if row else None) or oldest
            if first_seen is not None and first_seen.tzinfo is None:
                first_seen = first_seen.replace(tzinfo=timezone.utc)
            old_enough = (
                first_seen is not None
                and datetime.now(timezone.utc) - first_seen >= hub_slugs.FREEZE_AFTER
            )
            if old_enough and count >= hub_slugs.FREEZE_MIN_PAGES:
                outcome = "frozen"
            else:
                outcome = "recorded_not_yet_eligible"
        outcomes[outcome] += 1
        decisions.append(
            {
                "gov_id": gov_id,
                "pages": count,
                "hub_slug": slug,
                "outcome": outcome,
            }
        )

    print()
    print(f"  {'Outcome':<38} Count of {len(governments)}")
    for outcome, n in outcomes.most_common():
        print(f"  {outcome:<38} {n}")

    if args.report:
        with open(args.report, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(
                fh, fieldnames=["gov_id", "pages", "hub_slug", "outcome"]
            )
            writer.writeheader()
            writer.writerows(decisions)
        print(f"\n  per-government decisions written to {args.report}")

    if not args.apply:
        print("\n  DRY RUN -- nothing written. Re-run with --apply.")


if __name__ == "__main__":
    asyncio.run(main())
