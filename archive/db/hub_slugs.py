"""The stored, eventually-frozen `/j/{slug}` for one government.

WO-256, built from `docs/investigations/hub_architecture_audit.md` §4.
See `archive/db/models.py`'s `HubSlug` docstring for *why* a hub slug is
stored at all; this module is the read and write path for it.

**The read path is synchronous, on purpose.** `crud._hub_identity()` --
the one function every hub URL in the site comes out of -- is a plain
sync function called from a template render, from a `GROUP BY` loop and
from the sitemap. It cannot await a query per call. So the frozen rows
(a few thousand short strings, one per government) are held in a
process-level cache that `refresh()` reloads at most once per
`_CACHE_TTL` from whichever async read path runs first, and
`frozen_hub_slug()` reads that cache with no I/O.

Three properties make that safe rather than clever:

  * **A cold or stale cache degrades to exactly today's behaviour.** An
    unknown `gov_id` returns None and `_hub_identity()` computes the slug
    live, which is what it always did.
  * **Every surface reads the same cache**, so `/m/{slug}`'s hub link and
    `/j/{slug}`'s own grouping cannot disagree with each other even
    mid-refresh.
  * **Only FROZEN rows are cached.** An unfrozen row is provisional by
    definition (the gate below has not passed yet), and its stored slug
    is re-derived from the live computation on every write, so caching it
    would freeze it early by accident -- the exact thing the gate exists
    to prevent.

**The write path is every path that gives a page a government**: ingest
(`crud._find_or_create_page()`), the override endpoint
(`crud.override_jurisdiction()`), and the sweep
(`scripts/freeze_hub_slugs.py`, which is also the one-time backfill).
None of them computes a slug for a URL any more -- they call
`record_government()` and the stored row is what a reader gets.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func, select, text, update

from .models import HubSlug, MeetingPage

logger = logging.getLogger(__name__)

# Ryan's gate (2026-09-12): a slug becomes permanent only once the
# government has been known for this long AND has more than one page.
# Before that it may still recompute, so the early pin/identity churn on
# a brand-new government settles on its own rather than being frozen
# wrong. Seven days is Ryan's number, not a measured one -- it is the
# window in which a fresh mint's pin, its registry row and its name
# repair have all historically landed (WO-209 through WO-221 each did
# their pin work within a day or two of the ingest that prompted it).
FREEZE_AFTER = timedelta(days=7)
# "More than one meeting", as Ryan put it: a single-page government is
# exactly the one whose identity is least settled, and its hub is below
# `crud.JURISDICTION_HUB_MIN_INDEXABLE` anyway, so nothing is indexed
# that a later recomputation could move.
FREEZE_MIN_PAGES = 2

# Long enough that the reload is negligible next to the queries around
# it, short enough that running the backfill against a live service shows
# up within a minute with no restart -- same number and same reasoning as
# `crud._BEST_EFFORT_CHECK_TTL`.
_CACHE_TTL = timedelta(seconds=60)

_state: dict = {
    # gov_id -> frozen hub slug. Frozen rows ONLY (see the docstring).
    "frozen": {},
    "loaded_at": None,
    # None = not checked yet; False = the migration has not run here.
    "available": None,
    "available_checked_at": None,
}


def frozen_hub_slug(gov_id: Optional[str]) -> Optional[str]:
    """This government's permanent hub slug, or None when it has none yet.

    None is the ordinary answer for a government whose slug is still
    provisional, and for every government at all before the backfill has
    run -- `crud._hub_identity()` then computes the slug live, exactly as
    it always has.
    """
    if not gov_id:
        return None
    return _state["frozen"].get(gov_id)


def frozen_hub_slugs() -> dict:
    """The whole frozen map, for callers that need to ask "does any
    government own this slug?" (`scripts/backfill_gov_id.py`'s retired-
    slug report). A copy -- the cache is shared process state."""
    return dict(_state["frozen"])


def reset_cache() -> None:
    """Drop the cache so the next `refresh()` reloads. For tests, and for
    a writer that has just frozen something and wants the new row visible
    to its own subsequent reads."""
    _state["frozen"] = {}
    _state["loaded_at"] = None
    _state["available"] = None
    _state["available_checked_at"] = None


async def table_available(session) -> bool:
    """True when `hub_slugs` really exists on the connected database.

    Same feature-detect discipline as `crud._fts_available()` /
    `crud._meeting_pages_column_available()`, and for the same reason:
    this module's code and its migration must be safe to deploy in either
    order (CLAUDE.md's Alembic bullet, and the 2026-08-17
    UndefinedColumnError outage behind it). On SQLite -- dev, tests -- the
    table always exists by construction, because `init_models()` builds
    it straight off today's model.
    """
    if session.bind.dialect.name != "postgresql":
        return True
    now = datetime.now(timezone.utc)
    checked_at = _state["available_checked_at"]
    if checked_at is not None and now - checked_at < _CACHE_TTL:
        return bool(_state["available"])
    row = (
        await session.execute(
            text(
                "SELECT 1 FROM information_schema.tables WHERE table_name = 'hub_slugs'"
            )
        )
    ).first()
    _state["available"] = row is not None
    _state["available_checked_at"] = now
    return bool(_state["available"])


async def refresh(session, *, force: bool = False) -> None:
    """Reload the frozen-slug cache if it is older than `_CACHE_TTL`.

    Called from the async read paths that already hold a session --
    `crud._hub_groups()` (so `/j/`, `/state/*`, the home page and
    `sitemap.xml` all go through it) and `crud.get_page_by_slug()` (so a
    `/m/` page's hub link agrees with them). Never raises: a failure here
    must cost a live-computed slug, not a 500 on a meeting page.
    """
    now = datetime.now(timezone.utc)
    loaded_at = _state["loaded_at"]
    if not force and loaded_at is not None and now - loaded_at < _CACHE_TTL:
        return
    try:
        if not await table_available(session):
            _state["frozen"] = {}
            _state["loaded_at"] = now
            return
        rows = (
            await session.execute(
                select(HubSlug.gov_id, HubSlug.hub_slug).where(
                    HubSlug.frozen_at.is_not(None)
                )
            )
        ).all()
    except Exception:  # pragma: no cover - defensive, see docstring
        logger.exception("hub_slugs cache refresh failed; computing slugs live")
        _state["loaded_at"] = now
        return
    _state["frozen"] = {gov_id: slug for gov_id, slug in rows if gov_id and slug}
    _state["loaded_at"] = now


async def page_count(session, gov_id: str) -> int:
    """How many archived pages carry this `gov_id`.

    Every page, not only the hub-eligible ones: the question the gate
    asks is "has this government settled down," and a page that is
    currently empty (no transcript, no agenda) still counts as evidence
    that the government is real and recurring.
    """
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


def _usable(gov_id: Optional[str]) -> bool:
    """Whether this id names a government that can own a hub at all.

    `rtr:unknown:<host>` is a placeholder for "we do not know whose
    meeting this is" -- it has a registry row and a display form, and it
    is deliberately not a government (see `crud._hub_identity()`'s own
    comment). It never gets a stored slug.
    """
    return bool(gov_id) and not gov_id.startswith("rtr:unknown:")


async def record_government(
    session,
    gov_id: Optional[str],
    live_slug: Optional[str],
    *,
    now: Optional[datetime] = None,
    first_seen_at: Optional[datetime] = None,
) -> None:
    """Write (or refresh) this government's hub-slug row, then apply the
    freeze gate to it.

    Called from every writer that gives a page a government. Three cases:

      * **no row yet** -- insert one, `hub_slug=live_slug`,
        `first_seen_at=now`, unfrozen. This is the clock starting.
      * **an unfrozen row** -- update `hub_slug` to the live computation,
        so whatever the gate eventually freezes is the government's
        *current* name, not its first guess.
      * **a frozen row** -- left completely alone. That is the point of
        the whole table.

    `first_seen_at` is the freeze clock's start and defaults to `now`.
    `scripts/freeze_hub_slugs.py` passes the government's OLDEST page
    instead, so the one-time backfill does not restart a clock the archive
    has already been running for months -- it is deliberately a separate
    argument from `now` (the gate's "today"), because conflating the two
    makes every backdated government look brand new and nothing ever
    freezes.

    Never raises and never fails its caller's transaction. It runs inside
    the ingest transaction, and a hub slug is not worth losing a
    transcript over (same argument, and the same SAVEPOINT mechanics, as
    `crud._refresh_meeting_highlight()`).
    """
    if not _usable(gov_id) or not live_slug:
        return
    now = now or datetime.now(timezone.utc)
    first_seen_at = first_seen_at or now
    try:
        if not await table_available(session):
            return
        async with session.begin_nested():
            if session.bind.dialect.name == "postgresql":
                from sqlalchemy.dialects.postgresql import insert as dialect_insert
            else:
                from sqlalchemy.dialects.sqlite import insert as dialect_insert
            # ON CONFLICT DO NOTHING, not a read-then-insert: two ingests
            # for the same brand-new government can race, and one of them
            # losing must not fail an ingest.
            await session.execute(
                dialect_insert(HubSlug)
                .values(gov_id=gov_id, hub_slug=live_slug, first_seen_at=first_seen_at)
                .on_conflict_do_nothing(index_elements=["gov_id"])
            )
            await session.execute(
                update(HubSlug)
                .where(HubSlug.gov_id == gov_id, HubSlug.frozen_at.is_(None))
                .values(hub_slug=live_slug)
            )
        await apply_gate(session, gov_id, now=now)
    except Exception:  # pragma: no cover - defensive, see docstring
        logger.exception("recording hub slug for %s failed", gov_id)


async def apply_gate(session, gov_id: str, *, now: Optional[datetime] = None) -> bool:
    """Freeze this government's slug if it has earned it. Returns whether
    this call froze it.

    **Why this runs on the writer path and in a sweep, rather than on a
    schedule.** The Archive service has no scheduler of its own -- it is
    a web service, and every periodic job in this repo is either the
    transcription worker's own loop or a script someone runs. Two call
    sites cover the whole population between them: a government that is
    still being ingested freezes on its next ingest the moment it is
    eligible (one extra COUNT, once, for a government that has been
    unfrozen for a week), and a government that has stopped being
    ingested freezes on the next `scripts/freeze_hub_slugs.py --apply`
    run. Putting it on a read path was rejected: a write inside a page
    render is how a slow render becomes an outage.
    """
    now = now or datetime.now(timezone.utc)
    row = (
        await session.execute(
            select(HubSlug.first_seen_at, HubSlug.frozen_at).where(
                HubSlug.gov_id == gov_id
            )
        )
    ).first()
    if row is None or row[1] is not None:
        return False
    first_seen_at = row[0]
    if first_seen_at is None:
        return False
    if first_seen_at.tzinfo is None:
        # SQLite hands back naive datetimes even for a timezone=True
        # column; treat a stored naive value as UTC, which is what every
        # writer here puts in it.
        first_seen_at = first_seen_at.replace(tzinfo=timezone.utc)
    if now - first_seen_at < FREEZE_AFTER:
        return False
    if await page_count(session, gov_id) < FREEZE_MIN_PAGES:
        return False
    await session.execute(
        update(HubSlug)
        .where(HubSlug.gov_id == gov_id, HubSlug.frozen_at.is_(None))
        .values(frozen_at=now)
    )
    # The cache holds frozen rows only, so a row that just became frozen
    # is invisible until the next reload. Add it here rather than waiting
    # out the TTL: the page this ingest just wrote should link to the same
    # hub the grouping will put it on.
    _state["frozen"][gov_id] = (
        await session.execute(select(HubSlug.hub_slug).where(HubSlug.gov_id == gov_id))
    ).scalar()
    return True
