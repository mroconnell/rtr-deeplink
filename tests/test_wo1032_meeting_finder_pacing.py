"""WO-1032: `app/platforms/meeting_finder/pacing.py`'s process-wide
request pacing/counting hook.

Real-server tests (`aiohttp.test_utils.TestServer`) exercise the actual
behavior: an adapter's own `aiohttp.ClientSession` (never touched by
`fetch.Fetcher`) getting paced and counted the same as `Fetcher`'s own
requests, two concurrent governments sharing a host still taking turns,
and the hook being a true no-op outside an active `pace_all_requests()`
block. YouTube refusal is checked with a fake, unroutable host name
(`www.youtube.com` resolves nowhere reachable from a test process without
the guard raising first) -- this asserts the raise happens BEFORE any
connection attempt, never a real request to YouTube.
"""

from __future__ import annotations

import asyncio
import time

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from app.platforms.meeting_finder import fetch as fetch_module
from app.platforms.meeting_finder import pacing as pacing_module
from app.platforms.meeting_finder.fetch import Fetcher
from app.platforms.meeting_finder.pacing import RequestStats, pace_all_requests
from scripts.youtube_fetch_guard import YouTubeFetchRefused


@pytest.fixture(autouse=True)
def _reset_host_pacer():
    """Same reasoning as `tests/test_meeting_finder_fetch.py`'s own
    fixture: every test in this file hits `127.0.0.1`, so the process-wide
    pacer (`fetch._HOST_PACER_NEXT_AT`, shared by `pacing.py` via
    `fetch._global_wait_for_host`) must be reset between tests or a real
    delay carries over and serializes the whole file."""
    fetch_module._HOST_PACER_NEXT_AT.clear()
    yield
    fetch_module._HOST_PACER_NEXT_AT.clear()


async def _make_server(handler_map: dict) -> TestServer:
    app = web.Application()
    for path, handler in handler_map.items():
        app.router.add_get(path, handler)
    server = TestServer(app)
    await server.start_server()
    return server


# ---------------------------------------------------------------------------
# Inactive outside a pace_all_requests() block
# ---------------------------------------------------------------------------


async def test_hook_inactive_outside_pacing_block_does_not_count_or_delay():
    async def handler(request):
        return web.Response(text="ok")

    server = await _make_server({"/x": handler})
    try:
        # Installing the wrapper (via a PRIOR, already-exited
        # pace_all_requests() call elsewhere in this file/process) must
        # not linger -- a plain request outside any block is untouched:
        # no delay is reserved in the shared pacer, and nothing is
        # counted anywhere a test could observe.
        pacing_module._install_wrapper()
        before = dict(fetch_module._HOST_PACER_NEXT_AT)
        async with aiohttp.ClientSession() as session:
            async with session.get(str(server.make_url("/x"))) as resp:
                assert resp.status == 200
        assert fetch_module._HOST_PACER_NEXT_AT == before
    finally:
        await server.close()


# ---------------------------------------------------------------------------
# Counting: Fetcher's own requests AND an adapter's own separate session
# ---------------------------------------------------------------------------


async def test_counts_both_fetchers_own_requests_and_an_adapters_own_session():
    async def handler(request):
        return web.Response(text="<html><a href='/x'>x</a></html>")

    server = await _make_server({"/a": handler, "/b": handler})
    try:
        fetcher = Fetcher(per_host_delay_s=0.05, allow_headless=False)
        host = server.host
        with pace_all_requests(fetcher) as stats:
            assert isinstance(stats, RequestStats)
            await fetcher.fetch(str(server.make_url("/a")))
            # An adapter-shaped call: its OWN aiohttp session, never
            # touched by `fetcher` -- exactly how granicus.py/
            # queue_probe.py open their own sessions per call.
            async with aiohttp.ClientSession() as adapter_session:
                async with adapter_session.get(str(server.make_url("/b"))) as resp:
                    await resp.text()

        assert stats.requests_total == 2
        assert stats.requests_by_host[host] == 2
        # fetcher's own budget only ever counted its own request.
        assert fetcher.fetches_used == 1
    finally:
        await fetcher.aclose()
        await server.close()


async def test_stats_is_fresh_per_pace_all_requests_call():
    async def handler(request):
        return web.Response(text="ok")

    server = await _make_server({"/x": handler})
    try:
        fetcher = Fetcher(per_host_delay_s=0.0, allow_headless=False)
        with pace_all_requests(fetcher) as stats_1:
            async with aiohttp.ClientSession() as s:
                async with s.get(str(server.make_url("/x"))):
                    pass
        assert stats_1.requests_total == 1

        with pace_all_requests(fetcher) as stats_2:
            pass
        assert stats_2.requests_total == 0
        # The first call's own stats object is untouched by the second.
        assert stats_1.requests_total == 1
    finally:
        await fetcher.aclose()
        await server.close()


# ---------------------------------------------------------------------------
# Pacing: an adapter's own session to a host `fetcher` already knows about
# waits the same as `fetcher`'s own next request would.
# ---------------------------------------------------------------------------


async def test_adapter_session_request_is_paced_against_the_same_host():
    hits = []

    async def handler(request):
        hits.append(time.monotonic())
        return web.Response(text="ok")

    server = await _make_server({"/a": handler, "/b": handler})
    try:
        delay = 0.3
        fetcher = Fetcher(per_host_delay_s=delay, allow_headless=False)
        with pace_all_requests(fetcher):
            start = time.monotonic()
            await fetcher.fetch(str(server.make_url("/a")))
            async with aiohttp.ClientSession() as adapter_session:
                async with adapter_session.get(str(server.make_url("/b"))) as resp:
                    await resp.text()
            elapsed = time.monotonic() - start
        # The adapter's own request had to wait for the same per-host
        # slot fetcher's request just reserved.
        assert elapsed >= delay * 0.8
        assert len(hits) == 2
        assert hits[1] - hits[0] >= delay * 0.8
    finally:
        await fetcher.aclose()
        await server.close()


async def test_pacing_across_two_concurrent_contexts_sharing_a_host():
    """Two governments (two `Fetcher`s, two `pace_all_requests()` calls,
    running as concurrent asyncio tasks -- the shape `runner.py`'s
    `--concurrency` flag produces) sharing one vendor host must still take
    turns, and each keeps its OWN stats (contextvars are task-local, same
    pattern as `identity.py`'s `tenant_pin_switched_off()`)."""
    hits = []

    async def handler(request):
        hits.append(time.monotonic())
        return web.Response(text="ok")

    server = await _make_server({"/a": handler, "/b": handler})
    try:
        delay = 0.3

        async def run_government(path: str, fetcher: Fetcher) -> RequestStats:
            with pace_all_requests(fetcher) as stats:
                async with aiohttp.ClientSession() as adapter_session:
                    async with adapter_session.get(str(server.make_url(path))) as resp:
                        await resp.text()
            return stats

        fetcher_a = Fetcher(per_host_delay_s=delay, allow_headless=False)
        fetcher_b = Fetcher(per_host_delay_s=delay, allow_headless=False)

        start = time.monotonic()
        stats_a, stats_b = await asyncio.gather(
            run_government("/a", fetcher_a),
            run_government("/b", fetcher_b),
        )
        elapsed = time.monotonic() - start

        assert len(hits) == 2
        assert elapsed >= delay * 0.8  # the two requests were spaced out
        # Each government's own stats only ever saw its own one request.
        assert stats_a.requests_total == 1
        assert stats_b.requests_total == 1
    finally:
        await fetcher_a.aclose()
        await fetcher_b.aclose()
        await server.close()


# ---------------------------------------------------------------------------
# YouTube: refused before any connection is attempted, even for an
# adapter's own session (belt and braces on top of the connector guard).
# ---------------------------------------------------------------------------


async def test_youtube_still_refused_for_an_adapters_own_session():
    fetcher = Fetcher(allow_headless=False)
    with pace_all_requests(fetcher):
        async with aiohttp.ClientSession() as adapter_session:
            with pytest.raises(YouTubeFetchRefused):
                async with adapter_session.get(
                    "https://www.youtube.com/watch?v=abc123"
                ):
                    pass
