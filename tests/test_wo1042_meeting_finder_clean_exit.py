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
        still_alive = _join_lingering_threads(timeout=0.5)
    finally:
        t.join(timeout=5.0)
    assert still_alive <= baseline
    assert finished.is_set()


def test_a_thread_still_running_past_the_grace_period_is_counted_not_blocked():
    """The real incident's shape: a thread that outlives the grace
    period. This must return promptly (not hang) and report it."""
    stop = threading.Event()

    def _hung():
        stop.wait(10.0)

    t = threading.Thread(target=_hung, daemon=True)
    t.start()
    try:
        started = time.monotonic()
        still_alive = _join_lingering_threads(timeout=0.2)
        elapsed = time.monotonic() - started
        # Other test/library threads may start or finish during the call, so
        # count only what this test owns (flaky on CI with an exact baseline).
        assert t.is_alive()
        assert still_alive >= 1
        # The whole point: this returns close to the grace period, never
        # blocks for the thread's real (10s) lifetime.
        assert elapsed < 2.0
    finally:
        stop.set()
        t.join(timeout=5.0)


def test_multiple_lingering_threads_are_all_counted():
    stop = threading.Event()
    threads = [
        threading.Thread(target=lambda: stop.wait(10.0), daemon=True) for _ in range(3)
    ]
    for t in threads:
        t.start()
    try:
        started = time.monotonic()
        still_alive = _join_lingering_threads(timeout=0.2)
        elapsed = time.monotonic() - started
        # Only this test's threads are stable; others may come and go on CI.
        assert all(t.is_alive() for t in threads)
        assert still_alive >= 3
        # One grace period in total, not one per hung thread (WO-1090):
        # three hung threads at 0.2s each would take >= 0.6s.
        assert elapsed < 0.5
    finally:
        stop.set()
        for t in threads:
            t.join(timeout=5.0)


def test_a_hung_to_thread_call_does_not_hold_the_run_open():
    """Backlog triage 2026-10-16: `asyncio.run()` waited for an abandoned
    `to_thread()` call before `main()` ever reached `os._exit()`. In a fresh
    interpreter, abandon a 60 s `to_thread(time.sleep)` the way
    `--gov-timeout-minutes` does, then exit the way `main()` does. The
    process must end in seconds, not after the 60 s sleep."""
    import subprocess
    import sys
    from pathlib import Path

    script = """
import asyncio, os, time
from scripts.meeting_finder import _join_lingering_threads, _run_without_executor_wait

async def _run():
    try:
        await asyncio.wait_for(asyncio.to_thread(time.sleep, 60), timeout=0.1)
    except asyncio.TimeoutError:
        pass
    return "rows written"

print(_run_without_executor_wait(_run()), flush=True)
_join_lingering_threads(timeout=0.1)
os._exit(0)
"""
    started = time.monotonic()
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parent.parent,
        timeout=50,
    )
    assert result.returncode == 0, result.stderr
    assert "rows written" in result.stdout
    assert time.monotonic() - started < 30
