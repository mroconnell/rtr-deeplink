"""Unit coverage for archive/utils/date_status.py -- the pure helper behind
the "Upcoming" / "Recent" pills on /meetings and the notice on a meeting
page. Pinned `today` throughout, so these never drift with the calendar.
"""

import subprocess
import sys
from datetime import date, timedelta

from archive.utils.date_status import (
    RECENT,
    RECENT_MEETING_WINDOW,
    UPCOMING,
    meeting_date_status,
    parse_meeting_date,
)

TODAY = date(2026, 8, 17)


def test_future_meeting_is_upcoming_regardless_of_transcript():
    assert (
        meeting_date_status("2026-08-25", has_transcript=False, today=TODAY) == UPCOMING
    )
    # A pre-posted agenda plus a stray caption file still can't make a
    # not-yet-held meeting anything other than upcoming.
    assert (
        meeting_date_status("2026-08-25", has_transcript=True, today=TODAY) == UPCOMING
    )


def test_recent_meeting_without_transcript_is_recent():
    assert (
        meeting_date_status("2026-08-11", has_transcript=False, today=TODAY) == RECENT
    )
    # Same-day counts as recent (held or being held), not upcoming.
    assert (
        meeting_date_status("2026-08-17", has_transcript=False, today=TODAY) == RECENT
    )


def test_recent_meeting_with_transcript_gets_no_label():
    # Nothing left to wait for once a transcript exists.
    assert meeting_date_status("2026-08-11", has_transcript=True, today=TODAY) is None


def test_window_boundary():
    edge = TODAY - RECENT_MEETING_WINDOW
    assert (
        meeting_date_status(edge.isoformat(), has_transcript=False, today=TODAY)
        == RECENT
    )
    past = edge - timedelta(days=1)
    assert (
        meeting_date_status(past.isoformat(), has_transcript=False, today=TODAY) is None
    )


def test_missing_or_unparseable_date_is_none():
    assert meeting_date_status(None, has_transcript=False, today=TODAY) is None
    assert meeting_date_status("", has_transcript=False, today=TODAY) is None
    assert meeting_date_status("TBD", has_transcript=False, today=TODAY) is None
    assert parse_meeting_date("not a date") is None


def test_parse_tolerates_datetime_prefix_and_whitespace():
    # The column is a free String(20); an ISO datetime or padded value
    # should still resolve to its calendar day rather than be dropped.
    assert parse_meeting_date(" 2026-08-11T19:00:00 ") == date(2026, 8, 11)
    assert parse_meeting_date("2026-08-11") == date(2026, 8, 11)


def test_defaults_today_to_now_when_not_pinned():
    # Far-future date must be upcoming under any real "today".
    assert meeting_date_status("2999-01-01", has_transcript=False) == UPCOMING
    # Far-past date with no transcript is just a gap, not "recent".
    assert meeting_date_status("2000-01-01", has_transcript=False) is None


def test_archive_db_crud_imports_without_markupsafe():
    # Real 9.3-hour worker outage, 2026-08-24 (BACKLOG_DONE.md): this
    # module used to `from markupsafe import Markup, escape` at MODULE
    # SCOPE. archive/db/crud.py imports this module at module scope too,
    # and worker/main.py imports archive.db.crud -- so a module-scope
    # markupsafe import here became a hard runtime dependency of a
    # process that renders no HTML at all and (deliberately) doesn't
    # declare markupsafe in worker/requirements.in's own dependency
    # philosophy ("No fastapi/uvicorn/jinja2/slowapi here"). markupsafe
    # is now only imported lazily inside meeting_date_html() itself.
    #
    # Run in a fresh subprocess, not in-process: archive.db.crud is
    # already cached in sys.modules by the time this test file loads (via
    # other test modules' own imports), so an in-process check would
    # trivially pass without ever re-executing the import chain.
    # sys.modules["markupsafe"] = None is the standard trick for making
    # any `import markupsafe` in the subprocess raise ImportError, without
    # needing markupsafe to be genuinely uninstalled.
    script = "import sys; sys.modules['markupsafe'] = None; import archive.db.crud"
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
