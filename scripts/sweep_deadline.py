"""Shared wall-clock deadline wrapper for sweep scripts.

WO-939 (2026-09-21): a blocking call bounded only by its own per-read
timeout can still hang a sweep indefinitely if the remote side trickles
bytes slowly enough. `requests`' own `timeout=` kwarg resets on every
partial socket read, not the whole request -- confirmed live, WO-322,
2026-09-12: two real domains (`cityofclaycenter.com`, `roselandgov.org`)
hung 250-290+ seconds on every retry despite `wo273_recon.py`'s own
`polite_request()` passing an explicit `timeout=6`. The same shape is the
best-supported explanation for `scripts/wo321_recon.py`'s real, twice-
reproduced hang on `rankincounty.org` (WO-321, 2026-09-12): the DNS step's
own `dig()` call is already bounded by a real, killable subprocess
timeout, but the live robots.txt fetch (`polite_request()`) and the CDX/
wayback archive calls (`cdx_get()`/`wayback_id_read()`) all shared this
same gap until this WO.

`run_with_deadline()` runs `func(*args, **kwargs)` in a fresh, dedicated
worker thread and waits at most `deadline_seconds` for it to finish -- a
REAL elapsed-time cutoff around the *whole* call, not a per-read timeout a
slow trickle can defeat.

Honest, documented limitation (the same one BACKLOG.md's own "a sweep
script's per-government wall-clock cap can't truly preempt a synchronous
hang" entry, WO-179, already makes about a different mechanism):
`Future.result(timeout=...)` does not kill the underlying thread. A call
that genuinely never returns leaks one thread, running forever in the
background -- this bounds how long the CALLER waits, not how long the
call itself runs. This is the same accepted trade-off `scripts/
wo337_targeted.py`'s own `call_headless_with_deadline()` already shipped
with for headless-browser launches (its own comment: "a deadline via
Future.result(timeout=...) doesn't actually kill the underlying thread/
browser process in Python -- it just stops waiting on it"). Two things
are deliberate here on top of that, both confirmed while building this
module, not assumed: (1) the leaked thread is a plain `daemon=True`
`threading.Thread`, not a `ThreadPoolExecutor` worker -- an executor's own
threads are NOT daemon threads by default, so a leaked, still-hung call
would otherwise keep the whole Python process alive at exit, waiting on a
thread that will never finish (confirmed live: an early version of this
module using `ThreadPoolExecutor` reproduced exactly that against a real
slow-trickling local server -- the deadline fired correctly, but the
*process* still wouldn't exit). (2) a fresh thread per call, not one
shared, fixed-size pool: a shared pool means a handful of recurring hangs
can eventually exhaust every worker and silently stall every OTHER,
unrelated call queued behind them -- a real risk once this wrapper is
called from many sites across a sweep (as it is here), not just one
narrow call site the way wo337's own 4-worker headless pool is. The
complete fix for a hang that must be genuinely killed, not just stopped
waiting on, is a subprocess (killable by PID) -- out of scope here, the
same conclusion BACKLOG.md's own WO-179 entry already reached for a
CPU-bound hang inside an asyncio coroutine (a fundamentally different
shape this thread-based wrapper does NOT fix -- see that entry, and
`wo179_family_scale.py`'s own `asyncio.wait_for()`-based cap, which stays
untouched by this WO for exactly that reason: it bounds a cooperating
coroutine, which is the correct tool there, and a thread-based deadline
would require replacing its whole aiohttp/asyncio concurrency model to
even apply).

Usage:
    from scripts.sweep_deadline import DeadlineExceeded, run_with_deadline

    try:
        resp = run_with_deadline(
            requests.request, "GET", url, timeout=6, deadline_seconds=25,
        )
    except DeadlineExceeded:
        ...  # treat like any other fetch failure
"""

from __future__ import annotations

import concurrent.futures as _cf
import threading as _threading
from typing import Callable, TypeVar

T = TypeVar("T")


class DeadlineExceeded(Exception):
    """Raised by `run_with_deadline()` when `func()` didn't return within
    `deadline_seconds`. The underlying call may still be running in the
    background -- see this module's own docstring."""

    def __init__(self, label: str, deadline_seconds: float):
        self.label = label
        self.deadline_seconds = deadline_seconds
        super().__init__(f"{label} exceeded {deadline_seconds}s wall-clock deadline")


def run_with_deadline(
    func: Callable[..., T], *args, deadline_seconds: float, **kwargs
) -> T:
    """Runs `func(*args, **kwargs)` with a real wall-clock deadline.

    Raises `DeadlineExceeded` if `func` hasn't returned within
    `deadline_seconds`; otherwise returns `func`'s result, or propagates
    whatever exception `func` itself raised. `deadline_seconds` is
    keyword-only and required -- there's no sane default across the very
    different calls this wraps (a DNS/robots fetch vs. a headless browser
    launch), so every caller states its own.

    Runs `func` on a plain `daemon=True` `threading.Thread`, not a
    `ThreadPoolExecutor` -- confirmed live while building this module: a
    `ThreadPoolExecutor`'s own worker threads are NOT daemon threads by
    default, so a leaked, still-hung call (the exact case this wrapper
    exists to survive) would keep the whole Python process alive at exit,
    waiting for a thread that will never finish -- turning "one sweep
    government hung" into "the whole sweep process never exits," which is
    a worse failure than the one this module is fixing. A plain daemon
    thread has no such effect: the interpreter can exit with it still
    running, exactly what "stop waiting on a possibly-wedged call" should
    mean in a long-running sweep."""
    label = getattr(func, "__name__", repr(func))
    future: _cf.Future = _cf.Future()

    def _target() -> None:
        try:
            result = func(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001
            if not future.done():
                future.set_exception(exc)
        else:
            if not future.done():
                future.set_result(result)

    _threading.Thread(target=_target, daemon=True).start()
    try:
        return future.result(timeout=deadline_seconds)
    except _cf.TimeoutError:
        raise DeadlineExceeded(label, deadline_seconds) from None
