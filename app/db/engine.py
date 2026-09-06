import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

DEFAULT_LOCAL_URL = "sqlite+aiosqlite:///./dev.db"


def _resolve_database_url() -> str:
    raw = os.environ.get("DATABASE_URL", "").strip()
    if not raw:
        return DEFAULT_LOCAL_URL

    # Render (and most Postgres hosts) hand out plain postgres:// / postgresql://
    # URLs, but the async engine needs the asyncpg driver spelled out.
    if raw.startswith("postgres://"):
        raw = "postgresql+asyncpg://" + raw[len("postgres://") :]
    elif raw.startswith("postgresql://"):
        raw = "postgresql+asyncpg://" + raw[len("postgresql://") :]

    return raw


DATABASE_URL = _resolve_database_url()


# WO-111. Postgres invalidates a cached query PLAN when a column that
# query selects changes type -- and asyncpg keeps server-side prepared
# statements per connection, so a live pool goes on using plans that the
# server has just rejected. SQLAlchemy's asyncpg dialect surfaces that as
# `InvalidCachedStatementError: cached plan must not change result type`
# and the request 500s.
#
# Two confirmed user-facing failures, 2026-09-03 (Sentry
# PYTHON-FASTAPI-1D / -1E): `/j/rancho-cordova-ca` and one `/m/` page,
# both within 8 minutes of WO-101's `ALTER COLUMN meeting_pages.gov_id
# TYPE VARCHAR(320)`. Both failing queries select `gov_id` --
# `get_page_by_slug()` and `_hub_groups()`, the two hottest read paths in
# this service.
#
# **The timing is the part worth understanding.** `render.yaml`'s
# `preDeployCommand` runs the migration after the build and BEFORE the
# new instance is switched live, so the build serving traffic during the
# ALTER is the OLD one, with the OLD pool. A fix deployed alongside a
# migration therefore does nothing for that migration -- it protects the
# NEXT one, because by then the running build is the one carrying this
# setting. That is why this ships on its own rather than being bundled
# with whatever schema change comes next.
#
# Both caches are turned off -- see the two comments below for which is
# which. The cost is re-planning each query; these are indexed
# single-table selects and a `GROUP BY` over a few thousand rows, where
# planning is microseconds and nowhere near the dominant term. The
# alternative -- retrying once on `InvalidCachedStatementError` -- keeps
# the cache but only covers the call sites it wraps, and the failure
# class is "any query touching an altered column", which is not a set
# anyone can enumerate in advance. Same reasoning, same value, as the
# standard pgbouncer-in-transaction-mode setting.
# Deliberately duplicated in archive/db/engine.py -- the two services
# are deploy-independent and both run `alembic upgrade head` in their own
# preDeployCommand, so both have exactly this exposure. Same convention
# as url_normalize.py and clerk_auth.py.


def _engine_options(url: str) -> dict:
    """Engine kwargs for `url`. A function rather than a literal so a test
    can ask for the Postgres options without a Postgres URL in the env."""
    options = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        return options
    options["connect_args"] = {
        # SQLAlchemy's own cache of prepared-statement objects. This is
        # the one that matters and the one its docs name for exactly this
        # failure: the asyncpg dialect calls `connection.prepare()` for
        # ALL statements and caches the results per pooled connection,
        # and its docstring says outright that when "DDL changes are made
        # from other database engines and/or processes" -- which is
        # precisely `alembic upgrade head` in the preDeploy container --
        # "a running application may encounter asyncpg exceptions
        # InvalidCachedStatementError". Despite the name it is a DBAPI
        # argument, not a dialect one, so it goes here rather than in the
        # URL.
        "prepared_statement_cache_size": 0,
        # asyncpg's own server-side statement cache, underneath
        # SQLAlchemy's. Disabled too, because a fresh `prepare()` of the
        # same SQL can still be served from it. Same setting the pgbouncer
        # transaction-mode guidance uses.
        "statement_cache_size": 0,
    }

    # Neon/Render free-tier Postgres cap concurrent connections low; keep
    # our pool small rather than relying on the driver's defaults.
    options["pool_size"] = 5
    options["max_overflow"] = 2
    return options


_engine_kwargs = _engine_options(DATABASE_URL)

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_models() -> None:
    """`create_all()` for local dev/tests only -- a fresh SQLite file with
    no migration history just works, zero config.

    **On Postgres (production) this is now a deliberate no-op** (WO-10's
    resolver half, 2026-08-21), matching `archive/db/engine.py` exactly.
    Alembic (`app/alembic/`) is the one source of truth for the
    production schema. Until this change `create_all()` also ran
    unconditionally on every prod startup, which is the exact mechanism
    that let the Archive's `alembic_version` silently fall behind: a new
    table quietly appeared via `create_all()`, nobody noticed no
    migration existed for it, and the next migration that *altered*
    something arrived with a human in the loop -- three documented
    incidents (2026-08-09/10/13, `archive/alembic/README.md`) plus the
    2026-08-17 UndefinedColumnError outage from a model column deploying
    ahead of its migration (BACKLOG_DONE.md). This service had its own
    version of that on 2026-08-10 (`/admin/stats` 500ing on two columns
    `create_all()` couldn't add to an existing table -- fixed by a live
    `ALTER TABLE`, see `app/alembic/README.md`). Now a model change
    without a migration fails loudly on Postgres (the table/column just
    isn't there) instead of half-working, and CI runs `alembic check` on
    a fresh SQLite to catch that before merge (.github/workflows/test.yml).
    Gated on the dialect, not an env var, so nothing has to be configured
    for the safe path to be the default.

    Note this gate is safe to deploy on its own, ahead of the one-time
    `alembic stamp` step and `render.yaml`'s `preDeployCommand` (see
    `app/alembic/README.md`): production's tables already exist, so
    skipping `create_all()` changes nothing at runtime today -- it only
    removes the silent-drift mechanism going forward.
    """
    if engine.dialect.name == "postgresql":
        return
    from .models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
