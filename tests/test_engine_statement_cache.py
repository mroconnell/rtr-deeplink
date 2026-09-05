"""Both services disable asyncpg's server-side prepared-statement cache
on Postgres (WO-111).

Postgres invalidates a cached query PLAN when a column that query selects
changes type, and asyncpg holds prepared statements per connection -- so
a live pool keeps using plans the server has just rejected, and the
request 500s with `InvalidCachedStatementError: cached plan must not
change result type`.

Two confirmed user-facing failures on 2026-09-03 (Sentry
PYTHON-FASTAPI-1D / -1E): `/j/rancho-cordova-ca` and one `/m/` page,
both within 8 minutes of WO-101's `ALTER COLUMN meeting_pages.gov_id
TYPE VARCHAR(320)`. Both failing queries select `gov_id` --
`get_page_by_slug()` and `_hub_groups()`.

Tested on the options FUNCTION rather than on the live engine, because
the live one is built from whatever `DATABASE_URL` the test run happens
to have (SQLite), which is exactly the branch that must NOT carry the
setting.
"""

import pytest

from app.db import engine as resolver_engine
from archive.db import engine as archive_engine

_MODULES = pytest.mark.parametrize(
    "module",
    [archive_engine, resolver_engine],
    ids=["archive", "resolver"],
)


@_MODULES
def test_postgres_disables_both_prepared_statement_caches(module):
    """Two caches sit on top of each other and BOTH have to go.

    `prepared_statement_cache_size` is SQLAlchemy's own -- the asyncpg
    dialect calls `connection.prepare()` for every statement and caches
    the objects per pooled connection -- and it is the one SQLAlchemy's
    documentation names for this failure. `statement_cache_size` is
    asyncpg's underneath it, which can still serve a fresh `prepare()` of
    the same SQL from cache. Setting only the second (the first thing
    tried here) would have left the actual cause in place."""
    options = module._engine_options("postgresql+asyncpg://u:p@h/db")
    assert options["connect_args"]["prepared_statement_cache_size"] == 0
    assert options["connect_args"]["statement_cache_size"] == 0


@_MODULES
def test_sqlite_gets_no_asyncpg_only_options(module):
    """`statement_cache_size` is an asyncpg connect argument; handing it
    to aiosqlite is a TypeError at connect time, so the local and test
    path must not carry it."""
    options = module._engine_options("sqlite+aiosqlite:///./x.db")
    assert "connect_args" not in options
    assert "pool_size" not in options


@_MODULES
def test_the_pool_settings_still_apply(module):
    """The change must not drop the small-pool sizing it was inserted
    beside -- both services share one Postgres server by design."""
    options = module._engine_options("postgresql+asyncpg://u:p@h/db")
    assert options["pool_size"] == 5
    assert options["max_overflow"] == 2
    assert options["pool_pre_ping"] is True


@_MODULES
def test_the_live_engine_uses_these_options(module):
    """Guards the wiring, not just the function: a refactor that computes
    the options and forgets to pass them would leave every test above
    passing while production kept the cache."""
    assert module._engine_kwargs == module._engine_options(module.DATABASE_URL)
