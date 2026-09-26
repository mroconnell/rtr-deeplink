"""In-process TTL cache for `crud._hub_groups()`, with single-flight.

**Why this exists (2026-09-26 incident).** `_hub_groups()` runs a GROUP BY
over every indexable row in `meeting_pages` -- cheap when the Archive was
small, but its own docstring's "a few hundred rows -- cheap enough to run
per request" claim was already stale by the time this cache was added.
At ~6:56-7:02 AM PDT a crawler hit dozens of `/j/<slug>` hub pages per
second (mostly Utah bodies). Every one of those requests ran this GROUP
BY fresh, with no cache. The pool is 5 connections + 2 overflow per
uvicorn worker (2 workers, `archive/db/engine.py`) -- the burst held every
connection, every other route (`/m/`, `/context`, `/state/*`,
`/api/health`) started failing with `sqlalchemy.exc.TimeoutError:
QueuePool limit ... timeout 30.00`, and Render killed the instance on a
failed health check. Traceback: `archive/main.py::jurisdiction_page` ->
`crud.get_jurisdiction_hub_data` -> `crud._hub_groups` -> `session.execute`.

**What this module does.** A short-lived, process-level cache of
`_hub_groups()`'s result, plus single-flight: if ten requests miss the
cache in the same instant, only one of them runs the real query -- the
other nine `await` that same in-flight call and share its answer, so a
burst can no longer fan out into N identical GROUP BY queries. This is
exactly the failure mode above: even a cache with a reasonable TTL does
nothing for the first wave of a burst unless concurrent misses are
coalesced too.

**Staleness this introduces, and why it's an acceptable trade.** A page
that gets a government (via ingest, an override, or the freeze sweep)
less than `HUB_GROUPS_CACHE_TTL_SECONDS` seconds ago may not yet show up
on its `/j/{slug}` hub, on `sitemap.xml`, or in `/state/*`'s and the home
page's counts (the same comment in `_hub_groups()` names these as the
callers that route through it). Default TTL is 60 seconds -- the same
number `archive/db/hub_slugs.py`'s own frozen-slug cache already uses,
for the same reasoning ("negligible next to the queries around it, short
enough that a live change shows up within a minute with no restart").
Configurable via the `HUB_GROUPS_CACHE_TTL_SECONDS` env var; set it to 0
to disable caching outright (every call recomputes, single-flight still
applies).

**What must NOT wait out the TTL.** `crud._find_or_create_page()` (every
ingest) and `crud.override_jurisdiction()` both call
`hub_slugs.record_government()` right after writing a page's identity --
this module's `invalidate()` is called from the same two call sites, so a
freshly-ingested or freshly-overridden page's hub reflects it on the very
next request, not up to a minute later. `crud.delete_meeting_pages_by_slug()`
calls it too, so a deleted page doesn't linger on its old hub. Tests that
need a clean read after seeding data should call `invalidate()` directly
(mirrors `hub_slugs.reset_cache()`'s existing role in
`tests/test_hub_slug_freeze.py`), or pass `bypass_cache=True` to
`crud._hub_groups()`.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Awaitable, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

_DEFAULT_TTL_SECONDS = 60.0


def _ttl_seconds() -> float:
    """Read the env var live (not once at import time) so tests can change
    it with `monkeypatch.setenv` / `os.environ` without a process restart."""
    raw = os.environ.get("HUB_GROUPS_CACHE_TTL_SECONDS")
    if raw is None or raw == "":
        return _DEFAULT_TTL_SECONDS
    try:
        return max(0.0, float(raw))
    except ValueError:
        logger.warning(
            "HUB_GROUPS_CACHE_TTL_SECONDS=%r is not a number; using the %ss default.",
            raw,
            _DEFAULT_TTL_SECONDS,
        )
        return _DEFAULT_TTL_SECONDS


class _Entry:
    __slots__ = ("value", "stored_at")

    def __init__(self, value, stored_at: float):
        self.value = value
        self.stored_at = stored_at


# One cache, one key ("hub_groups" is the only thing cached here today).
# A dict-by-key shape is kept anyway so a second whole-table computation
# (see the module docstring's "and anything else on the /j/ path" ask) can
# reuse this same machinery without inventing a second cache module.
_entries: dict[str, _Entry] = {}
# One in-flight asyncio.Future per key, so concurrent misses on the same
# key share one real computation instead of each starting their own.
_inflight: dict[str, "asyncio.Future"] = {}
# Guards _inflight (not _entries -- reading/writing a dict entry is atomic
# enough between the awaits below; what's NOT safe without a lock is two
# coroutines both seeing "no future yet" and both creating one).
_lock = asyncio.Lock()


async def get_or_compute(
    key: str,
    compute: Callable[[], Awaitable[T]],
    *,
    bypass_cache: bool = False,
) -> T:
    """Return the cached value for `key` if it's fresh, else compute it
    once and cache it -- sharing that one computation with every other
    caller that misses at the same time.

    `bypass_cache=True` skips the cache entirely (still doesn't duplicate
    an already-in-flight computation for the same key, since that would
    defeat the single-flight guarantee for everyone else calling
    concurrently without bypass): it always awaits a fresh `compute()`
    and does not read `_entries`, but it DOES store the fresh result, so a
    bypass also refreshes the cache other callers see.
    """
    ttl = _ttl_seconds()
    now = time.monotonic()

    if not bypass_cache and ttl > 0:
        entry = _entries.get(key)
        if entry is not None and now - entry.stored_at < ttl:
            return entry.value

    # Join an in-flight computation if one is already running for this key.
    async with _lock:
        future = _inflight.get(key)
        if future is None:
            future = asyncio.get_event_loop().create_future()
            _inflight[key] = future
            is_owner = True
        else:
            is_owner = False

    if not is_owner:
        return await future

    try:
        value = await compute()
    except BaseException as exc:  # noqa: BLE001 - propagate after cleanup
        async with _lock:
            _inflight.pop(key, None)
        if not future.done():
            future.set_exception(exc)
        raise
    else:
        _entries[key] = _Entry(value, time.monotonic())
        async with _lock:
            _inflight.pop(key, None)
        if not future.done():
            future.set_result(value)
        return value


def invalidate(key: Optional[str] = None) -> None:
    """Drop a cached entry (or every entry, if `key` is None) so the next
    call recomputes. Never touches an in-flight computation -- a writer
    that invalidates mid-request just means the request already in flight
    finishes with whatever it started with, and the NEXT call sees fresh
    data, which is the same "cold cache degrades to live computation"
    property `hub_slugs.py` relies on.

    Called from `crud._find_or_create_page()`, `crud.override_jurisdiction()`
    and `crud.delete_meeting_pages_by_slug()` right after they write --
    see the module docstring. Also used directly by tests that need a
    guaranteed-fresh read after seeding data outside those paths.
    """
    if key is None:
        _entries.clear()
    else:
        _entries.pop(key, None)
