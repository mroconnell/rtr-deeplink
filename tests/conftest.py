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

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session", autouse=True)
async def _archive_db_schema():
    """Creates the archive/db tables once for the whole test session. This
    is a shared, file-based DB across every test that uses it (not reset
    per-test) -- tests that write to it should use unique identifiers
    (e.g. a distinct external_id/source_url per test) rather than relying
    on isolation the fixture doesn't provide."""
    from archive.db.engine import init_models

    await init_models()


def load_fixture(*parts: str) -> str:
    """Read a text fixture file relative to tests/fixtures/."""
    return (FIXTURES_DIR.joinpath(*parts)).read_text(encoding="utf-8")


def load_fixture_bytes(*parts: str) -> bytes:
    return (FIXTURES_DIR.joinpath(*parts)).read_bytes()
