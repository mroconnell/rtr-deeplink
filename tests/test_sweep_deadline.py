"""WO-939 (2026-09-21): scripts/sweep_deadline.py's run_with_deadline().

Built to fix a real, confirmed hang shape: a blocking call bounded only by
its own per-read timeout can still hang a sweep indefinitely if the remote
side trickles bytes slowly enough (`requests`' own `timeout=` resets on
every partial socket read -- WO-322 hit this live, two real domains hung
250-290+ seconds despite `wo273_recon.py`'s own `timeout=6`; see
BACKLOG_DONE.md's WO-939 entry and this module's own docstring).

These tests are synthetic (a local slow-trickling HTTP server, not a real
government host) per this repo's own "synthetic tests exercise one
specific logic branch already confirmed against real data" convention --
the SHAPE of the bug (a `timeout=` kwarg that doesn't bound total request
time) is independently confirmed live in WO-322's incident; what's
synthetic here is only the reproduction harness, not the underlying fact
being tested.
"""

import time

import pytest

from scripts.sweep_deadline import DeadlineExceeded, run_with_deadline


def test_run_with_deadline_returns_normally_within_budget():
    def fast(x):
        return x * 2

    start = time.monotonic()
    result = run_with_deadline(fast, 21, deadline_seconds=5)
    elapsed = time.monotonic() - start

    assert result == 42
    assert elapsed < 1  # nowhere near the 5s deadline


def test_run_with_deadline_propagates_the_real_exception():
    def raises():
        raise ValueError("boom")

    with pytest.raises(ValueError, match="boom"):
        run_with_deadline(raises, deadline_seconds=5)


def test_run_with_deadline_raises_deadline_exceeded_on_a_true_hang():
    def hangs_forever():
        # Simulates a call requests' own per-read timeout would never
        # trip (each individual step is instant -- there's just no
        # total-time bound), the same shape a slow-trickling response
        # produces in production.
        time.sleep(30)

    start = time.monotonic()
    with pytest.raises(DeadlineExceeded, match="0.3s wall-clock deadline"):
        run_with_deadline(hangs_forever, deadline_seconds=0.3)
    elapsed = time.monotonic() - start

    # The whole point: the CALLER stops waiting at the deadline, not at
    # whatever the hung call itself would eventually do (30s here).
    assert elapsed < 5


def test_run_with_deadline_does_not_block_process_exit_on_a_leaked_thread():
    """Real, confirmed bug found building this module: an earlier version
    used a `ThreadPoolExecutor`, whose own worker threads are NOT daemon
    threads by default -- so a leaked, still-hung call kept the whole
    Python PROCESS alive at exit, waiting on a thread that would never
    finish (confirmed live against a real slow-trickling local server: the
    deadline fired correctly, but the process still wouldn't exit for
    minutes). This test reproduces that exact scenario as a subprocess, so
    a regression back to a non-daemon-thread implementation would show up
    as a timeout here, not just as a slow individual call."""
    import subprocess
    import sys

    # A plain 60s sleep stands in for the hung request: what decides
    # whether the process can exit is the KIND of thread the leaked call
    # runs on, not what it is waiting for. The original repro used a local
    # slow-trickle HTTP server and `requests` (~1s more per run); a
    # ThreadPoolExecutor-based `run_with_deadline` still hangs this script
    # until the timeout below kills it (checked when this was simplified,
    # WO-1084).
    script = """
import sys, time
sys.path.insert(0, "scripts")
from sweep_deadline import DeadlineExceeded, run_with_deadline

try:
    run_with_deadline(time.sleep, 60, deadline_seconds=0.1)
except DeadlineExceeded:
    print("deadline-fired", flush=True)
print("process-about-to-exit", flush=True)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=10,  # generous, but must NOT need anywhere near the
        # leaked call's own 60s -- a regression to non-daemon threads
        # would time out here.
        cwd=".",
    )
    assert "deadline-fired" in result.stdout
    assert "process-about-to-exit" in result.stdout
    assert result.returncode == 0
