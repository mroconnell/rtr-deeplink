import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Never share the resolver's dev.db -- a separate local file so the two
# services' local schemas can't collide or bleed into each other.
DEFAULT_LOCAL_URL = "sqlite+aiosqlite:///./archive_dev.db"


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


def _assert_expected_db_host(url: str) -> None:
    """WO-4 (AUDIT_EXECUTION_BRIEF.md, 2026-08-16): render.yaml's own
    comment on the worker's DATABASE_URL says it "MUST be the exact same
    value as rtr-deeplink-archive's" -- but each is a separately
    dashboard-set env var on two different Render services, with nothing
    enforcing that at deploy time. A copy-paste mistake (worker pointed at
    a stale or staging database) would otherwise only surface as
    confusing missing/duplicate data, not a startup failure.

    Gated on `EXPECTED_DB_HOST` (a real Render internal Postgres hostname
    like "dpg-xxxxxxxxxxxxxxxxxxxx-a", not a secret) being set at all --
    same optional, no-op-when-unset degrade pattern as GA_MEASUREMENT_ID/
    SENTRY_DSN/CLERK_PUBLISHABLE_KEY elsewhere in this codebase.
    Deliberately NOT hardcoded: this module is imported by both the
    Archive service and the worker (via archive.db.crud) *and* by any
    dashboard-cloned staging/test service running the same code from the
    same branch -- a bare hardcoded production hostname would hard-crash
    a staging deploy the moment it redeployed with this check in place.
    Set `EXPECTED_DB_HOST` only on the two production services in
    render.yaml; staging/test services simply never set it and this
    stays a no-op there, exactly as intended.
    """
    expected = os.environ.get("EXPECTED_DB_HOST", "").strip()
    if not expected or url.startswith("sqlite"):
        return
    from urllib.parse import urlparse

    host = urlparse(url).hostname or ""
    if expected not in host:
        raise RuntimeError(
            f"DATABASE_URL hostname mismatch: EXPECTED_DB_HOST={expected!r} "
            f"not found in the configured DATABASE_URL's host ({host!r}). "
            "This almost certainly means DATABASE_URL is pointed at the "
            "wrong database -- refusing to start rather than silently "
            "running against unexpected data."
        )


_assert_expected_db_host(DATABASE_URL)

_engine_kwargs = {"pool_pre_ping": True}
if not DATABASE_URL.startswith("sqlite"):
    # Same free-tier connection-cap reasoning as the resolver's engine.py --
    # this service shares a Postgres *server* with the resolver (per design),
    # so keeping both pools small matters even more here.
    _engine_kwargs["pool_size"] = 5
    _engine_kwargs["max_overflow"] = 2

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_models() -> None:
    """Still the whole story for local dev/tests -- a fresh SQLite file
    with no migration history just works, zero config. Adopted Alembic
    2026-08-09 (`archive/alembic/`) as the real source of truth for
    *production* schema changes going forward, since `create_all()`
    can only ever add new tables, never alter an existing one (the wall
    this repo hit three separate times before adopting real migration
    tooling -- see BACKLOG_DONE.md). This still runs unconditionally on
    every startup (`create_all` is a safe no-op against tables that
    already exist, whichever way they got created), so an Alembic
    migration that only adds a new table doesn't strictly need
    `init_models()` touched at all -- but any migration that *alters* an
    existing table (the actual reason Alembic exists now) needs a real
    `alembic upgrade head` run, this function can't do that part.
    """
    from .models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
