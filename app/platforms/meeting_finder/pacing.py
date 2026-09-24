"""Process-wide request pacing and counting for one Meeting Finder
government run (WO-1032).

**The gap this closes.** `fetch.py`'s `Fetcher` paces and counts only the
requests it makes itself -- up to `max_fetches` (12 by default) real
fetches of the target site. Tracing `dublin.ca.gov` through
`runner.run_one()` with aiohttp's own `ClientSession._request` wrapped
(conductor trace, 2026-09-23) found **55 real HTTP requests, only 12
counted by `Fetcher`**. The other 43 came from adapters and helpers that
open their own `aiohttp.ClientSession` -- `app/platforms/granicus.py`
(`_fetch_page`, `_fetch_channel_info`, `_fetch_caption_file`,
`_fetch_agenda_html`), `app/platforms/queue_probe.py` (`_probe_hls`), and
the passive-verify walkers -- so those requests skip `Fetcher`'s per-host
pacer entirely, including any robots.txt `Crawl-delay` a caller already
recorded via `note_crawl_delay()`. At Meeting Finder's planned
concurrency (32+ governments, many sharing a `*.granicus.com`/CivicClerk
host) that is exactly the kind of impoliteness CLAUDE.md's "we query
sites politely" rule warns about, and a real path to getting rate-limited
site-wide.

**Approach: one permanent, scoped hook on `aiohttp.ClientSession._request`
itself**, rather than editing every adapter to accept a shared session or
pacer. `pace_all_requests(fetcher)` is a context manager the runner
activates around one government's whole walk (every fork/hop/adapter call
that government makes, including any it fans out concurrently via
`asyncio.gather`). While active, every `aiohttp.ClientSession._request`
call process-wide -- not just `fetcher`'s own -- is:

  - refused outright if it targets a YouTube host (belt and braces on top
    of `scripts/youtube_fetch_guard.py`'s existing connector-level guard,
    which already blocks this; see `_paced_request()`'s own comment for
    why this module checks again directly rather than relying solely on
    that);
  - paced against the SAME process-wide per-host pacer `fetch.py` already
    has (`fetch._global_wait_for_host`), using the same delay rules
    (`fetcher.per_host_delay_s`, or a longer robots.txt `Crawl-delay`
    already recorded on `fetcher` via `note_crawl_delay()`) -- so an
    adapter's own request to a host `fetcher` already knows about waits
    exactly as long as `fetcher`'s own next request to that host would;
  - counted into `RequestStats.requests_total` and
    `RequestStats.requests_by_host`, a separate tally from
    `fetcher.fetches_used`/`fetcher.max_fetches` (see "Two counters, not
    one" below).

**Not touching `fetcher`'s own requests' pacing a second time.** `Fetcher`
already calls `fetch._global_wait_for_host()` itself for every request it
makes (that is how it stays polite across concurrent `Fetcher` instances
today). If this hook paced `fetcher`'s own session's requests too, each of
`fetcher`'s 12 budgeted fetches would reserve TWO slots in the shared
per-host pacer instead of one, silently doubling the effective spacing for
every OTHER request to that host for the rest of the run -- a real
slowdown with no politeness benefit, since the request was already paced
once. So `_paced_request()` recognizes `fetcher`'s own session (`self is
ctx.fetcher._session`) and only counts it, skipping the redundant wait.
Every other session -- an adapter's own, opened fresh per call, the way
`granicus.py`/`queue_probe.py` already do -- gets both paced and counted,
since nothing else in the process paces those today.

**Two counters, not one -- `max_fetches` is not widened.**
`fetcher.max_fetches`/`fetcher.fetches_used` keep meaning exactly what
they mean today: a budget on real fetches of the *target site itself*
(the page the walk is actually trying to read), spent by Resolve's own
ladder logic in `fetch.py`. If adapter requests counted against that same
budget, a single Granicus caption fetch (four to six requests per clip;
see `granicus.py`'s own helpers above) would starve the walk's remaining
`Fetcher.fetch()` budget before Resolve ever got a turn -- the same
"whole budget spent before the real candidate got a look" failure
`runner.py`'s own `_shallow_step()`-before-`Scan`/`Hop` ordering (WO-1030)
was built to avoid, just at a different layer. `RequestStats.requests_total`
is reported *alongside* `fetcher.fetches_used`, not folded into it -- a
government's true request cost is both numbers together, not one.

**Concurrency-safe across simultaneous governments, same pattern as
`identity.py`'s `tenant_pin_switched_off()`.** `runner.py`'s
`--concurrency` flag runs more than one government at once via
`asyncio.gather()`/`create_task()`; each government constructs its own
`Fetcher` and should get its own `RequestStats`. A plain module-level
variable would let two concurrent `pace_all_requests()` calls stomp on
each other exactly the way `identity.py`'s docstring describes for its
own earlier, broken version of the same problem. `_ACTIVE` is a
`contextvars.ContextVar` holding the current government's `_PacingContext`
(its `Fetcher` plus its own `RequestStats`); each `asyncio.Task` gets its
own copy of the context at creation, so one government's active context is
invisible to a sibling task. The underlying per-host pacer
(`fetch._global_wait_for_host`, backed by `fetch._HOST_PACER_NEXT_AT` and
its `asyncio.Lock`) stays process-wide and shared on purpose -- two
concurrent governments hitting the same vendor host must still take turns,
which is the entire point of this hook.

**No global patch left installed when inactive.** `_install_wrapper()`
replaces `aiohttp.ClientSession._request` exactly once (idempotent, same
guard shape as `scripts/youtube_fetch_guard.py`'s `install()`), but the
wrapper itself checks `_ACTIVE.get()` first and, outside any
`pace_all_requests()` block, delegates straight to the real `_request`
with no pacing, no counting and no YouTube re-check beyond what
`youtube_fetch_guard` already does process-wide. So importing this module
-- or even calling `pace_all_requests()` once and letting the context
manager exit -- changes nothing for any other caller of aiohttp in this
process, including tests that never touch Meeting Finder at all.
"""

from __future__ import annotations

import contextlib
import contextvars
from dataclasses import dataclass, field
from typing import Dict, Iterator, Optional
from urllib.parse import urlparse

import aiohttp

from scripts.youtube_fetch_guard import YouTubeFetchRefused, is_youtube_host

from . import fetch as fetch_module
from .fetch import Fetcher


@dataclass
class RequestStats:
    """What `pace_all_requests()` hands back: every real aiohttp request
    made while it was active, process-wide -- `fetcher`'s own budgeted
    fetches included, since those are real requests too (see this
    module's docstring, "Two counters, not one"). `requests_by_host` keys
    are lowercased hostnames with no port, matching `fetch.py`'s own
    `urlparse(url).hostname` convention."""

    requests_total: int = 0
    requests_by_host: Dict[str, int] = field(default_factory=dict)

    def record(self, host: str) -> None:
        self.requests_total += 1
        self.requests_by_host[host] = self.requests_by_host.get(host, 0) + 1


@dataclass
class _PacingContext:
    fetcher: Fetcher
    stats: RequestStats


# Task-local (asyncio) -- see this module's docstring, "Concurrency-safe
# across simultaneous governments". `None` (the default) means "no
# Meeting Finder government run is currently active on this task", which
# is also the steady state for every OTHER caller of aiohttp in this
# process.
_ACTIVE: "contextvars.ContextVar[Optional[_PacingContext]]" = contextvars.ContextVar(
    "meeting_finder_pacing_active", default=None
)

_installed = False


def _resolve_host(str_or_url: object) -> str:
    return (urlparse(str(str_or_url)).hostname or "").lower()


def _install_wrapper() -> None:
    """Idempotent, permanent, process-wide -- same shape as
    `scripts/youtube_fetch_guard.py`'s `install()`. Safe to call
    unconditionally from `pace_all_requests()`'s own `__enter__`: the
    wrapper it installs is a no-op for every request made while
    `_ACTIVE.get()` is `None`, so installing it once and leaving it
    installed forever changes nothing outside an active
    `pace_all_requests()` block."""
    global _installed
    if _installed:
        return
    _installed = True

    real_request = aiohttp.ClientSession._request

    async def _paced_request(self, method, str_or_url, **kwargs):
        ctx = _ACTIVE.get()
        if ctx is None:
            return await real_request(self, method, str_or_url, **kwargs)

        host = _resolve_host(str_or_url)

        # Belt and braces on top of `scripts/youtube_fetch_guard.py`'s
        # connector-level guard (already installed by `Fetcher.__init__`
        # for any process running Meeting Finder): that guard blocks the
        # DNS lookup a real connection attempt would trigger, but this
        # check refuses BEFORE even reserving a per-host pacer slot for a
        # request that must never happen at all, and gives a clear,
        # directly-testable failure at the exact call site adapters use
        # (`session.get(...)`) rather than relying on a lower layer.
        if is_youtube_host(host):
            raise YouTubeFetchRefused(
                f"refused: {host} is a YouTube host; YouTube is fetched only by "
                "the drip Mac (CLAUDE.md)"
            )

        # `fetcher`'s own session already paces (and budgets) its own
        # requests via `Fetcher._wait_for_host()` -- see this module's
        # docstring, "Not touching fetcher's own requests' pacing a
        # second time". Every other session (an adapter's own) gets
        # paced here, since nothing else in the process does.
        if self is not ctx.fetcher._session:
            delay = max(
                ctx.fetcher.per_host_delay_s,
                ctx.fetcher._crawl_delays.get(host, 0.0),
            )
            await fetch_module._global_wait_for_host(host, delay)

        ctx.stats.record(host)
        return await real_request(self, method, str_or_url, **kwargs)

    aiohttp.ClientSession._request = _paced_request


@contextlib.contextmanager
def pace_all_requests(fetcher: Fetcher) -> Iterator[RequestStats]:
    """Activate process-wide pacing/counting (see this module's docstring)
    for the duration of one government's walk. Usage (`runner.py`,
    WO-1031):

        fetcher = Fetcher(...)
        with pace_all_requests(fetcher) as stats:
            ...  # the whole Start/Identify/List/Scan/Hop/Resolve walk
        verdict_row.requests_total = stats.requests_total
        verdict_row.requests_by_host = dict(stats.requests_by_host)

    Yields a fresh `RequestStats` for THIS call -- a nested or concurrent
    call (a different government, on a different `asyncio.Task`) gets its
    own, per `_ACTIVE` being a `ContextVar`. Restores whatever was active
    before on exit, so nesting (should a caller ever do it) unwinds
    cleanly rather than leaking the inner government's context to code
    that runs after the `with` block on the same task.
    """
    _install_wrapper()
    stats = RequestStats()
    token = _ACTIVE.set(_PacingContext(fetcher=fetcher, stats=stats))
    try:
        yield stats
    finally:
        _ACTIVE.reset(token)
