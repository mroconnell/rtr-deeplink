"""Give a second (or third) government its own permanent `/j/{slug}` --
WO-316, built from `docs/investigations/hub_architecture_audit.md` §8 and
BACKLOG.md's "Three `/j/` hubs still hold two real governments each" entry.

**The gap this closes.** WO-256's freeze (`archive/db/hub_slugs.py`,
`scripts/freeze_hub_slugs.py`) gives every government ONE permanent slug,
minted from whatever `crud.live_hub_slug()` computes for it. That fixes
the common case -- a rename or override no longer moves a page's URL --
but it does nothing when two DIFFERENT real governments compute the SAME
slug to begin with (two Nova Scotia municipal units sharing a bare place
name, two Census county subdivisions with an identical display name in
different counties of the same state). `freeze_hub_slugs.py` only mints
one row per already-computed slug and is a full-corpus sweep; it has no
concept of "this slug is contested, give the loser a different one."
WO-310 (2026-09-12) measured three such contested slugs live against the
production `hub_slugs` table: `middletown-township-pa` (Middletown
Township, Bucks County PA vs. Middletown Township, Delaware County PA --
two DIFFERENT real townships, not a duplicate mint), `yarmouth-ns`
(THREE real gov_ids: Yarmouth County, the Municipal District of Yarmouth,
and the Town of Yarmouth, NS -- BACKLOG.md's own entry corrects the
original WO-232 audit's "two governments" framing), and `lunenburg-ns`
(the Municipal District of Lunenburg vs. the Town of Lunenburg, NS).

**What this script does, and does not do.** For one `--gov-id`, it writes
a distinct, immediately-frozen `hub_slugs` row with the caller-supplied
`--slug` -- bypassing the normal 7-day/2-page gate, because this is a
deliberate, already-identified correction, not the ordinary settling
period the gate protects. It never touches any OTHER government's row,
never re-keys any page's `gov_id`, and never merges anything -- "moves
nothing else," per the work order. Giving two colliding governments
DISTINCT ids is a separate, prior decision (already true for all three
cases here: every gov_id involved already has its own registry or
national-table row) -- this tool only ever assigns a URL, never an
identity.

**Which government keeps the old slug.** Not automatic. The operator
names the LOSING gov_id on the command line; the tool's own job is only
to verify that choice is sound: (1) the named gov_id's current stored
slug really is shared with at least one other gov_id (refuses otherwise
without `--force` -- this tool is for a real, already-measured
collision, not a guess), and (2) warns (refuses without `--force`) if the
named gov_id has MORE pages, or an OLDER `first_seen_at`, than a sibling
still sitting on the shared slug -- the rule this work order was given
("the government that keeps the old slug is the one with more pages or
the older frozen row") flags the opposite call as likely backwards. It
does not decide FOR the operator; it catches an inversion of the stated
rule.

**The new slug must carry a real disambiguator.** `--slug` must contain
one of a small set of tokens that could plausibly separate two
governments sharing a bare name -- `county`, `municipality-of-`,
`town-of-`, `township-of-`, `borough-of-`, `village-of-`, `district-of-`,
or a state/province suffix not already present in the current slug --
refused otherwise without `--force`. This is a sanity guard against a
typo or a cosmetic rename, not a naming authority: the operator still
picks the actual word.

Dry run by default, like every other backfill/freeze script here. Prints
the pages that will render under the new slug once it exists (a page's
hub is a pure `gov_id` lookup once frozen -- no re-ingest needed).

Usage (from the repo root, with DATABASE_URL set -- see CLAUDE.md's
worktree `.env` bullet: map `ARCHIVE_DATABASE_URL` to `DATABASE_URL`
in-process to point this at the real Archive, never export it to the
shell):
    python scripts/split_hub_slug.py --gov-id us:cousub:4201749120 \\
        --slug middletown-township-bucks-county-pa
    python scripts/split_hub_slug.py --gov-id us:cousub:4201749120 \\
        --slug middletown-township-bucks-county-pa --apply
"""

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Tokens that plausibly disambiguate two governments sharing one bare
# display name. Deliberately a short, named list rather than "any word
# not in the old slug" -- the point is to catch "I forgot to change
# anything" and "I renamed the wrong part," not to enforce a vocabulary.
_DISTINGUISHER_TOKENS = (
    "county",
    "municipality-of-",
    "town-of-",
    "township-of-",
    "borough-of-",
    "village-of-",
    "district-of-",
)


def slug_has_distinguisher(
    new_slug: str, old_slug: Optional[str], state_or_province: Optional[str]
) -> bool:
    """True when `new_slug` carries a plausible disambiguator over
    `old_slug`. See the module docstring for the token list and the
    state/province fallback."""
    lowered = new_slug.lower()
    if any(tok in lowered for tok in _DISTINGUISHER_TOKENS):
        return True
    if state_or_province:
        code = state_or_province.lower()
        old_parts = (old_slug or "").lower().split("-")
        new_parts = lowered.split("-")
        # Only counts if the new slug has MORE of this token than the old
        # one did -- a state/province suffix that was already there
        # (e.g. both slugs end "-ns") disambiguates nothing.
        if new_parts.count(code) > old_parts.count(code):
            return True
    return False


def decide_keeper(target: tuple, sibling: tuple) -> tuple[str, str]:
    """(gov_id, page_count, first_seen_at) for the target and one sibling
    sharing the old slug. Returns (keeper_gov_id, reason) using the
    work order's rule: more pages wins; a tie falls to the OLDER
    first_seen_at (the row that has been sitting under the slug longer).
    A further tie (identical page count and first_seen_at) resolves to
    the sibling, arbitrarily, and says so -- there is no sound rule left
    to apply and the operator's own choice should stand unless the target
    is a CLEAR loser under the stated rule.
    """
    t_id, t_pages, t_seen = target
    s_id, s_pages, s_seen = sibling
    if t_pages != s_pages:
        winner = t_id if t_pages > s_pages else s_id
        return winner, f"more pages ({t_pages} vs {s_pages})"
    if t_seen and s_seen and t_seen != s_seen:
        winner = t_id if t_seen < s_seen else s_id
        return winner, f"older first_seen_at ({t_seen} vs {s_seen})"
    return s_id, "page counts and first_seen_at tied -- no rule to prefer the target"


def overall_keeper(contenders: list) -> tuple[str, str]:
    """Which ONE of several governments sharing a slug keeps it, per the
    work order's rule, folded across the whole group -- not a pairwise
    check against a single sibling.

    Two real shapes this exists for, both hit live running this tool for
    WO-316's three actual collisions: (1) **three or more** real gov_ids
    can share one slug (Yarmouth NS: county + 2 subdivisions) -- a target
    can lose a pairwise check against a co-loser while still being the
    correct one to keep the slug against the TRUE dominant government, so
    the decision has to be made once, over the whole group, not once per
    sibling. (2) **A dead sibling with zero pages** (a retired/redundant
    minted id, e.g. Middletown Township PA's old `rtr:us:pa:middletown-
    township`) is excluded from contention entirely -- it renders
    nothing, so "it has fewer pages" is not a reason to let it block a
    real split. Contenders with pages > 0 are preferred as a group; a
    zero-page contender only enters the fold if EVERY contender has zero
    pages (nothing has ever settled the question, so the stated rule
    still applies to whatever is there).
    """
    with_pages = [c for c in contenders if c[1] > 0]
    pool = with_pages or contenders
    keeper, reason = pool[0][0], "only contender"
    current = pool[0]
    for other in pool[1:]:
        winner_id, reason = decide_keeper(current, other)
        current = current if winner_id == current[0] else other
        keeper = current[0]
    return keeper, reason


async def run_split(gov_id: str, new_slug: str, *, apply: bool, force: bool) -> dict:
    """The whole check-then-write flow, importable and awaitable directly
    -- what `main()` below drives from argv, and what
    `tests/test_split_hub_slug.py` calls directly against the shared test
    database, the same way `tests/test_hub_slug_freeze.py` exercises
    `archive/db/hub_slugs.py`'s functions without a subprocess.

    Returns a small result dict (`written`, `ok_to_write`, `siblings`,
    `pages`) rather than an exit code, so a test can assert on the
    decision without scraping printed output. Every line this prints at
    the CLI is also in that dict's shape, one way or another.
    """
    from sqlalchemy import func, select

    from archive.db import hub_slugs
    from archive.db.crud import registry_governments
    from archive.db.engine import async_session
    from archive.db.models import HubSlug, MeetingPage

    mode = "APPLY" if apply else "DRY RUN"
    print(f"hub slug split -- {mode}")
    print(f"  gov_id: {gov_id}")
    print(f"  new slug: {new_slug}")

    async def page_count(session, gov_id: str) -> int:
        return int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(MeetingPage)
                    .where(MeetingPage.gov_id == gov_id)
                )
            ).scalar()
            or 0
        )

    async with async_session() as session:
        if not await hub_slugs.table_available(session):
            print(
                "  hub_slugs table does not exist on this database yet -- run "
                "`cd archive && alembic upgrade head` first. Nothing done."
            )
            return {
                "gov_id": gov_id,
                "new_slug": new_slug,
                "written": False,
                "ok_to_write": False,
                "siblings": [],
                "pages": 0,
            }

        target_row = (
            await session.execute(
                select(
                    HubSlug.hub_slug, HubSlug.first_seen_at, HubSlug.frozen_at
                ).where(HubSlug.gov_id == gov_id)
            )
        ).first()

        result: dict = {
            "gov_id": gov_id,
            "new_slug": new_slug,
            "written": False,
            "ok_to_write": True,
            "siblings": [],
            "pages": 0,
        }

        if target_row is None:
            print(
                f"  ERROR: no hub_slugs row exists yet for {gov_id} -- it has "
                "no page/slug to split off of. A government needs at least one "
                "ingested page first."
            )
            result["ok_to_write"] = False
            current_slug: Optional[str] = None
            target_first_seen = None
        else:
            current_slug, target_first_seen, target_frozen_at = target_row
            print(
                f"  current stored slug: {current_slug!r} "
                f"(frozen: {target_frozen_at is not None})"
            )
        result["current_slug"] = current_slug

        if current_slug == new_slug:
            print("  ERROR: new slug is identical to the current stored slug.")
            result["ok_to_write"] = False

        target_pages = await page_count(session, gov_id)
        result["pages"] = target_pages
        print(f"  pages currently keyed to {gov_id}: {target_pages}")

        siblings = []
        if current_slug:
            siblings = (
                await session.execute(
                    select(
                        HubSlug.gov_id, HubSlug.first_seen_at, HubSlug.frozen_at
                    ).where(HubSlug.hub_slug == current_slug, HubSlug.gov_id != gov_id)
                )
            ).all()

        if not siblings:
            print(
                f"  VERIFY FAILED: no other gov_id currently shares slug "
                f"{current_slug!r} in hub_slugs. This tool is for a real, "
                "already-measured collision."
            )
            result["ok_to_write"] = False
        else:
            print(f"  sibling gov_id(s) sharing {current_slug!r}:")
            contenders = [(gov_id, target_pages, target_first_seen)]
            for gid, first_seen, frozen_at in siblings:
                pages = await page_count(session, gid)
                result["siblings"].append(
                    {
                        "gov_id": gid,
                        "pages": pages,
                        "first_seen_at": first_seen,
                        "frozen": frozen_at is not None,
                    }
                )
                print(
                    f"    {gid}: {pages} page(s), first_seen_at={first_seen}, "
                    f"frozen={frozen_at is not None}"
                )
                contenders.append((gid, pages, first_seen))

            # One decision over the WHOLE group sharing this slug, not a
            # pairwise check per sibling -- see overall_keeper()'s
            # docstring for why a pairwise check is wrong once 3+
            # governments (Yarmouth NS) or a dead zero-page sibling
            # (Middletown Township PA's retired minted id) are involved.
            keeper, reason = overall_keeper(contenders)
            if keeper == gov_id:
                print(
                    f"    WARNING: by the more-pages/older-row rule, "
                    f"{gov_id} should KEEP {current_slug!r} ({reason}), not move "
                    "to a new one. You may be splitting the wrong side."
                )
                result["ok_to_write"] = False
            else:
                print(
                    f"    rule applied over the whole group: {keeper} keeps "
                    f"{current_slug!r} ({reason})"
                )

        registry_gov = registry_governments().get(gov_id)
        state = registry_gov.state if registry_gov else None
        if not slug_has_distinguisher(new_slug, current_slug, state):
            print(
                f"  ERROR: new slug {new_slug!r} carries no recognized "
                f"disambiguator (one of {', '.join(_DISTINGUISHER_TOKENS)}, or a "
                f"state/province suffix not already in {current_slug!r})."
            )
            result["ok_to_write"] = False

        page_rows = (
            await session.execute(
                select(MeetingPage.id, MeetingPage.jurisdiction, MeetingPage.title)
                .where(MeetingPage.gov_id == gov_id)
                .order_by(MeetingPage.id)
            )
        ).all()
        print(f"  {len(page_rows)} page(s) will render under /j/{new_slug}:")
        for pid, jurisdiction, title in page_rows[:20]:
            print(f"    page {pid}: {jurisdiction} -- {title}")
        if len(page_rows) > 20:
            print(f"    ... and {len(page_rows) - 20} more")

        if not result["ok_to_write"] and not force:
            print(
                "\n  Refusing to proceed (a check above failed). Re-run with "
                "--force to override, or fix the arguments."
            )
            return result

        if not apply:
            print("\n  DRY RUN -- nothing written. Re-run with --apply.")
            return result

    async with async_session() as write_session:
        from sqlalchemy.dialects import postgresql, sqlite

        now = datetime.now(timezone.utc)
        first_seen_at = target_first_seen or now
        dialect_insert = (
            postgresql.insert
            if write_session.bind.dialect.name == "postgresql"
            else sqlite.insert
        )
        await write_session.execute(
            dialect_insert(HubSlug)
            .values(
                gov_id=gov_id,
                hub_slug=new_slug,
                first_seen_at=first_seen_at,
                frozen_at=now,
            )
            .on_conflict_do_update(
                index_elements=["gov_id"],
                set_={"hub_slug": new_slug, "frozen_at": now},
            )
        )
        await write_session.commit()
    hub_slugs.reset_cache()
    result["written"] = True
    print(f"\n  WROTE: {gov_id} -> frozen slug {new_slug!r}")
    return result


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--gov-id", required=True, help="the government to give a NEW frozen slug to"
    )
    parser.add_argument(
        "--slug", required=True, help="the new, distinct frozen slug for this gov_id"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write. Without it this only reports (the default).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip the collision/keeper/distinguisher safety checks.",
    )
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv()

    await run_split(args.gov_id, args.slug, apply=args.apply, force=args.force)


if __name__ == "__main__":
    asyncio.run(main())
