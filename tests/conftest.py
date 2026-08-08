from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(*parts: str) -> str:
    """Read a text fixture file relative to tests/fixtures/."""
    return (FIXTURES_DIR.joinpath(*parts)).read_text(encoding="utf-8")


def load_fixture_bytes(*parts: str) -> bytes:
    return (FIXTURES_DIR.joinpath(*parts)).read_bytes()
