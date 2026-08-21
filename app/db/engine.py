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

_engine_kwargs = {"pool_pre_ping": True}
if not DATABASE_URL.startswith("sqlite"):
    # Neon/Render free-tier Postgres cap concurrent connections low; keep
    # our pool small rather than relying on the driver's defaults.
    _engine_kwargs["pool_size"] = 5
    _engine_kwargs["max_overflow"] = 2

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
