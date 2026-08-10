import os
import tempfile
from pathlib import Path

import pytest

# archive.db.engine reads DATABASE_URL once, at import time -- set this
# before any test module can trigger that import, so archive/db tests run
# against an isolated, real (file-based, not shared-cache-tricky :memory:)
# SQLite file instead of accidentally touching a real dev/prod database.
# setdefault, not a hard overwrite: running tests against a real Postgres
# DATABASE_URL on purpose should still be possible.
_test_db_fd, _test_db_path = tempfile.mkstemp(suffix=".db", prefix="rtr_archive_test_")
os.close(_test_db_fd)
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_test_db_path}")

# Same reasoning as DATABASE_URL above -- app.main/archive.main both call
# load_dotenv() at import time, which (override=False) is a no-op once
# these are already set, but only if this setdefault runs *first*. A
# real, confirmed flake without it: whichever test module happens to be
# collected first ends up loading the repo's real local .env, and any
# later test file's own `os.environ.setdefault("ARCHIVE_INGEST_TOKEN",
# "test-token")` line becomes a no-op against the real token instead --
# order-dependent, so it passed in isolation and failed in the full
# suite. Setting these here, guaranteed to run before any test module
# import (conftest.py always loads first), fixes it for every test file
# at once rather than patching each one's import order individually. See
# BACKLOG_DONE.md for the first occurrence of this exact bug.
os.environ.setdefault("ARCHIVE_INGEST_TOKEN", "test-token")
os.environ.setdefault("ADMIN_STATS_TOKEN", "test-admin-token")

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session", autouse=True)
async def _archive_db_schema():
    """Creates the archive/db AND app/db tables once for the whole test
    session -- both read the same DATABASE_URL (set above), so they share
    this one isolated SQLite file. Not reset per-test -- tests that write
    to it should use unique identifiers (e.g. a distinct external_id/
    source_url per test) rather than relying on isolation the fixture
    doesn't provide."""
    from app.db.engine import init_models as init_app_models
    from archive.db.engine import init_models as init_archive_models

    await init_archive_models()
    await init_app_models()


def load_fixture(*parts: str) -> str:
    """Read a text fixture file relative to tests/fixtures/."""
    return (FIXTURES_DIR.joinpath(*parts)).read_text(encoding="utf-8")


def load_fixture_bytes(*parts: str) -> bytes:
    return (FIXTURES_DIR.joinpath(*parts)).read_bytes()
