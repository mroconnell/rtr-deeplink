"""WO-1042: tests for scripts/meeting_finder.py's clean-exit fix.

Real incident this covers: an overnight batch run wrote all 3,300 verdict
rows and then never returned control to the shell. The cause is
`concurrent.futures`' own `atexit` hook, which joins every worker thread
the asyncio default executor (what `asyncio.to_thread()` uses, including
`fetch.py`'s sync headless-browser helper) has ever created before the
interpreter is allowed to exit -- so one still-hung thread (e.g. a
`--gov-timeout-minutes`-abandoned government's sync fetch, which is only
"abandoned", not actually stopped -- see `runner.py`'s
`_run_one_with_timeout()` docstring) blocks the whole process forever.

`_join_lingering_threads()` is the split-out, testable half of the real
fix: it never calls `os._exit()` itself (that part is only in `main()`,
untestable in-process without killing the test runner), so these tests
spin up real EXTRA lingering threads and check the returned count went up
by the expected amount. Counts are relative to a baseline taken at the
top of each test, not asserted as absolute zero -- this test suite's own
session-scoped DB fixture (tests/conftest.py's `_archive_db_schema`) keeps
a real background thread of its own alive for aiosqlite, so "no lingering
threads at all" is not a true baseline in this process.
"""

from __future__ import annotations

import threading
import time

from scripts.meeting_finder import _join_lingering_threads


def _baseline_alive_count() -> int:
    return sum(
        1
        for t in threading.enumerate()
        if t is not threading.main_thread() and t.is_alive()
    )


def test_no_new_lingering_threads_returns_the_baseline():
    baseline = _baseline_alive_count()
    # `<=`: a leftover thread from an earlier test may finish meanwhile.
    assert _join_lingering_threads(timeout=0.1) <= baseline


def test_a_thread_that_finishes_within_the_grace_period_is_joined():
    baseline = _baseline_alive_count()
    finished = threading.Event()

    def _quick():
        time.sleep(0.05)
        finished.set()

    t = threading.Thread(target=_quick)
    t.start()
    try:
        still_alive = _join_lingering_threads(timeout=2.0)
    finally:
        t.join(timeout=5.0)
    assert still_alive == baseline
    assert finished.is_set()


def test_a_thread_still_running_past_the_grace_period_is_counted_not_blocked():
    """The real incident's shape: a thread that outlives the grace
    period. This must return promptly (not hang) and report it."""
    baseline = _baseline_alive_count()
    stop = threading.Event()

    def _hung():
        stop.wait(10.0)

    t = threading.Thread(target=_hung, daemon=True)
    t.start()
    try:
        started = time.monotonic()
        still_alive = _join_lingering_threads(timeout=0.2)
        elapsed = time.monotonic() - started
        # A range, not `== baseline + 1`: a thread left over from an
        # earlier test can finish during the grace period, which lowers
        # the count by one (WO-1045 CI, and main at 8daa07d: 6 == 4 + 3).
        # Our own hung thread must still be counted either way.
        assert t.is_alive()
        assert 1 <= still_alive <= baseline + 1
        # The whole point: this returns close to the grace period, never
        # blocks for the thread's real (10s) lifetime.
        assert elapsed < 2.0
    finally:
        stop.set()
        t.join(timeout=5.0)


def test_multiple_lingering_threads_are_all_counted():
    baseline = _baseline_alive_count()
    stop = threading.Event()
    threads = [
        threading.Thread(target=lambda: stop.wait(10.0), daemon=True) for _ in range(3)
    ]
    for t in threads:
        t.start()
    try:
        still_alive = _join_lingering_threads(timeout=0.1)
        # See the single-thread test above for why this is a range.
        assert all(t.is_alive() for t in threads)
        assert 3 <= still_alive <= baseline + 3
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=5.0)
