import atexit
import os
import tempfile
from datetime import datetime, timedelta, timezone
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


def _remove_test_db() -> None:
    # One temp file per run, never deleted before (230 left in one cloud
    # container's /tmp by 2026-09-26, WO-1084). Removed at interpreter exit,
    # after every engine is done with it; a failure here is harmless.
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            os.remove(_test_db_path + suffix)
        except OSError:
            pass


atexit.register(_remove_test_db)

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
# Same reasoning again: app.main/archive.main each read this once, at
# import time, into templates.env.globals -- several nav tests
# (tests/test_accounts_anonymous_regression.py) assert on the
# CLERK_PUBLISHABLE_KEY-configured nav markup and never set it
# themselves, so without a guaranteed default they only pass by accident
# when the developer's local .env happens to carry a real key. Confirmed
# failing in a clean environment with no .env at all (CI's first real
# run, 2026-08-14) despite passing locally -- exactly the order/env
# dependent flake shape described above, just for a different var.
os.environ.setdefault("CLERK_PUBLISHABLE_KEY", "pk_test_fake_for_tests")
# WO-923: the partial-transcript check (app/platforms/coverage_check.py)
# would otherwise run a real ffprobe against every fixture video URL that
# passes through a registered finder. Tests of the check itself switch it
# on with monkeypatch and inject a fake probe.
os.environ.setdefault("RTR_PARTIAL_TRANSCRIPT_CHECK", "0")

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


@pytest.fixture(autouse=True)
def _no_real_card_extraction(monkeypatch):
    """Keeps meeting-card frame extraction (WO-28) from making real
    network calls during the suite.

    Necessary, not defensive. `GET /m/{slug}` and `POST /internal/ingest`
    both queue an extraction via FastAPI's BackgroundTasks when a page has
    no card yet -- and Starlette's TestClient runs background tasks
    synchronously, so without this the existing structured-data tests
    quietly started shelling out to ffprobe/ffmpeg against
    archive-media.granicus.com (confirmed: a real "Server returned 404"
    from the CDN, in a suite whose deliberate network-free property is
    what scripts/adapter_canary.py exists to complement -- see README's
    "Running tests").

    Patched at the module attribute rather than behind a new env flag, so
    production code carries no test-only branch: archive/main.py's
    _schedule_card_warm() looks the function up on the module at call
    time. Tests that need real frames in the database store bytes through
    crud.store_thumbnail() directly (tests/test_meeting_card_thumbnails.py);
    ffmpeg's own behavior was verified live against a real government mp4
    instead -- see BACKLOG_DONE.md.
    """
    from archive.utils import video_thumbnail

    async def _skip(**_kwargs):
        # Returns the real FrameOutcome shape (WO-42), skipped=True: this
        # stand-in genuinely attempts nothing, which is precisely what
        # `skipped` means, and returning the real type keeps a caller
        # that reads `.offset`/`.reason` working under the patch.
        return video_thumbnail.FrameOutcome(
            None, "skipped: card extraction is disabled in the test suite", True
        )

    monkeypatch.setattr(video_thumbnail, "extract_and_store", _skip)


@pytest.fixture(autouse=True)
def _no_real_audio_rendition_lookup(monkeypatch):
    """Keeps WO-1062's separate-audio-file lookup from making real network
    calls. `extract_chunk_audio()` runs it whenever an HLS chunk's first
    attempt fails at `start > 0`, which several faked-ffmpeg tests do on
    purpose with real-looking Cablecast URLs. Same pattern as the fixture
    above. tests/test_media_probe.py tests the real function by the name
    it imported before this patch, and opts a test into a found file by
    patching this attribute itself."""
    from app.platforms import media_probe

    async def _none(media_url, *, source_page_url):
        return None

    monkeypatch.setattr(media_probe, "single_file_audio_rendition_url", _none)


@pytest.fixture(autouse=True)
def _no_real_embedded_caption_probe(monkeypatch):
    """Keeps WO-1065's embedded-caption probe from making real network
    calls. Invintus resolve() runs it whenever an event has a stream but no
    `captionPath`, which most real Invintus fixtures do. None ("couldn't
    decide") keeps the old "No captions found" warning. Tests that need a
    probe answer patch this attribute themselves; tests/test_embedded_captions.py
    tests the real function from its own module."""
    from app.platforms import invintus

    async def _none(session, master_url):
        return None

    monkeypatch.setattr(invintus, "probe_embedded_captions", _none)


def load_fixture(*parts: str) -> str:
    """Read a text fixture file relative to tests/fixtures/."""
    return (FIXTURES_DIR.joinpath(*parts)).read_text(encoding="utf-8")


def load_fixture_bytes(*parts: str) -> bytes:
    return (FIXTURES_DIR.joinpath(*parts)).read_bytes()


def registered_platforms() -> set[str]:
    """The platform names `register_all_finders()` actually registers.

    Reads `base._REGISTRY` directly on purpose: its keys *are* the
    `AssetFinder.platform_name` values `get_finder()` resolves against,
    which is exactly what a coverage guard (scripts/adapter_canary.py's
    CANARY_URLS, and any later registry-based check) has to be keyed by.
    Deriving the list any other way (parsing __init__.py, listing
    app/platforms/*.py) could drift from what's actually registered,
    which is the whole thing those guards exist to prevent.

    The clear/restore dance is the load-bearing part. `_REGISTRY` is
    process-global and `register()` never removes anything, so a test
    that registers a throwaway finder (tests/test_base.py's
    "fake_test_platform") leaks it into every later read of the registry
    in the same pytest process. Reading the registry naively passed only
    because test_adapter_canary.py happens to sort before test_base.py
    -- an accident that adding, renaming, or randomizing the order of a
    test file would silently turn into a failure. Snapshotting, clearing,
    re-registering and then re-applying the snapshot gives the real
    answer regardless of collection order, while leaving the registry
    exactly as it was found (snapshot applied last, so a
    monkeypatched-in finder survives too).
    """
    from app.platforms import base, register_all_finders

    snapshot = dict(base._REGISTRY)
    base._REGISTRY.clear()
    try:
        register_all_finders()
        return set(base._REGISTRY)
    finally:
        base._REGISTRY.update(snapshot)


# The local meeting export two WO-934 tests were built from
# (tests/test_repair_wrong_pages.py, tests/test_wrong_page_screen.py). They
# assert real rows of THAT export, so they must never run on another one.
# /tmp/rtr_meeting_inventory/meeting_inventory.csv is rewritten by every
# dashboard refresh (2026-09-23 and 2026-09-25 07:08), and the old
# `skipif(not EXPORT.exists())` then ran them on the newer export and failed
# on pages the repairs had since fixed. The CSV carries no export date, so
# the file is recognised by two facts about the 2026-09-21 export instead:
# its row count (10,280 pages, recorded in two BACKLOG.md entries measured
# from it) and its newest page's created_at (no page after 2026-09-21; one
# day of slack because created_at is UTC and the export ran in Pacific
# time). A dated copy is preferred when present, since nothing overwrites it.
WRONG_PAGE_EXPORT_DIR = Path("/tmp/rtr_meeting_inventory")
_WRONG_PAGE_EXPORT_ROWS = 10_280
_WRONG_PAGE_EXPORT_LAST_CREATED = "2026-09-22"


def _export_fingerprint(path: Path) -> tuple[int, str]:
    import csv

    rows, newest = 0, ""
    with open(path, newline="", encoding="utf-8") as fh:
        for raw in csv.DictReader(fh):
            rows += 1
            newest = max(newest, (raw.get("created_at") or "")[:10])
    return rows, newest


def wrong_page_export_2026_09_21() -> tuple[Path | None, str]:
    """The 2026-09-21 export if one is on disk, else (None, why not)."""
    found = []
    for path in (
        WRONG_PAGE_EXPORT_DIR / "meeting_inventory_2026-09-21.csv",
        WRONG_PAGE_EXPORT_DIR / "meeting_inventory.csv",
    ):
        if not path.exists():
            continue
        rows, newest = _export_fingerprint(path)
        if (
            rows == _WRONG_PAGE_EXPORT_ROWS
            and newest <= _WRONG_PAGE_EXPORT_LAST_CREATED
        ):
            return path, ""
        found.append(f"{path.name}: {rows:,} rows, newest page {newest or '(none)'}")
    if not found:
        return None, "the local 2026-09-21 export is not here"
    return None, (
        "the local export is not the 2026-09-21 one "
        f"({_WRONG_PAGE_EXPORT_ROWS:,} rows, no page after "
        f"{_WRONG_PAGE_EXPORT_LAST_CREATED}): " + "; ".join(found)
    )


# Pending Archive pushes (app/db/crud.get_pending_archive_pushes) come back
# oldest first and capped (limit=10 by default, and the sweep always uses
# the default). The suite's SQLite file is shared and never reset, so a
# test's freshly logged row sits BEHIND every pending row other modules
# left earlier -- tests/test_archive_push_tracking.py failed whenever enough
# of those ran first (WO-1083, found running the suite in shuffled order).
# Tests where the cap applies backdate their own rows to put them first,
# and delete what they logged afterwards so a backdated leftover can't
# crowd out a later test.
PENDING_PUSH_BACKDATE = datetime(2000, 1, 1, tzinfo=timezone.utc)


async def backdate_resolutions(resolution_ids, *, start=PENDING_PUSH_BACKDATE):
    """Give each row an old created_at, in the order given, one second
    apart, so they sort before any row logged at the real current time."""
    from sqlalchemy import update

    from app.db.engine import async_session
    from app.db.models import MeetingResolution

    async with async_session() as session:
        for i, resolution_id in enumerate(resolution_ids):
            await session.execute(
                update(MeetingResolution)
                .where(MeetingResolution.id == resolution_id)
                .values(created_at=start + timedelta(seconds=i))
            )
        await session.commit()


async def delete_resolutions(resolution_ids):
    from sqlalchemy import delete

    from app.db.engine import async_session
    from app.db.models import MeetingResolution

    if not resolution_ids:
        return
    async with async_session() as session:
        await session.execute(
            delete(MeetingResolution).where(
                MeetingResolution.id.in_(list(resolution_ids))
            )
        )
        await session.commit()


# Politeness waits between requests to one host. They protect real
# government servers, not anything a test checks, and the fakes these tests
# talk to need no protecting -- yet each one was paid for real, adding ~45s
# to every CI run (WO-1084). Zeroed here for every test, but only in
# modules a test has already imported, so this costs nothing and imports
# nothing. Some scripts are imported both as `scripts.X` and as a bare `X`
# (a test that puts scripts/ on sys.path), so both names are listed. Add a
# constant here when a new one turns up in `pytest --durations`. A test
# about the real value can call `monkeypatch.undo()` first, as
# tests/test_meeting_finder_fetch.py's pin test does.
_POLITENESS_DELAYS = (
    ("app.platforms.meeting_finder.fetch", "DEFAULT_PER_HOST_DELAY_S"),
    ("app.platforms.meeting_finder.resolve", "CANDIDATE_DELAY_SECONDS"),
    ("scripts.wo147_access_ladder_sweep", "HOST_DELAY_SECONDS"),
    ("scripts.wo134_confirmed_hits_ingest", "CANDIDATE_DELAY_SECONDS"),
    # Imported BY NAME from scripts.bulk_ingest, so its own copy is the one
    # its loop sleeps on -- patch both.
    ("scripts.feed_tier3_auto_transcription", "REQUEST_DELAY_SECONDS"),
    ("scripts.bulk_ingest", "REQUEST_DELAY_SECONDS"),
    ("scripts.pmn_utah_pilot", "PMN_REQUEST_DELAY_SECONDS"),
    ("pmn_utah_pilot", "PMN_REQUEST_DELAY_SECONDS"),
    ("scripts.build_pin_worklist", "SWAGIT_DELAY_SECONDS"),
    ("build_pin_worklist", "SWAGIT_DELAY_SECONDS"),
)


@pytest.fixture(autouse=True)
def _no_politeness_delays(monkeypatch):
    import sys

    for module_name, attr in _POLITENESS_DELAYS:
        module = sys.modules.get(module_name)
        if module is not None and hasattr(module, attr):
            monkeypatch.setattr(module, attr, 0)


@pytest.fixture(autouse=True)
def _no_real_youtube_metadata_calls(monkeypatch, request):
    """No test may reach YouTube (CLAUDE.md: only the drip Mac fetches
    YouTube; the suite is network-free). Three resolve tests did, through
    yt-dlp, on every run -- they passed only because the failed call was
    caught, and cost 2-5s each (WO-1084). The real `extract_info` now
    refuses at once in every test. A test that fakes yt-dlp itself (e.g.
    tests/test_youtube.py replaces `YoutubeDL`) is unaffected; a test that
    needs the real call opts out with `@pytest.mark.real_yt_dlp`. Only
    patched when yt_dlp is already imported, so this imports nothing."""
    import sys

    yt_dlp = sys.modules.get("yt_dlp")
    if yt_dlp is None or request.node.get_closest_marker("real_yt_dlp"):
        return

    def _refuse(self, url, *args, **kwargs):
        raise yt_dlp.utils.DownloadError(
            f"test suite: real yt-dlp call refused for {url!r} -- fake "
            "YouTubeAssetFinder._extract_info (see tests/test_civicweb.py)"
        )

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", _refuse)
