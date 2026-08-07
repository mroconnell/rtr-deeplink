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
        raw = "postgresql+asyncpg://" + raw[len("postgres://"):]
    elif raw.startswith("postgresql://"):
        raw = "postgresql+asyncpg://" + raw[len("postgresql://"):]

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
    from .models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
