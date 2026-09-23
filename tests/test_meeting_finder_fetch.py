"""WO-1025: Meeting Finder's fetch helper (`app/platforms/meeting_finder/
fetch.py`).

Two kinds of coverage, per CLAUDE.md's own rule about synthetic tests:

- Real-server tests (`aiohttp.test_utils.TestServer`, a real loopback HTTP
  server this process actually talks to over a real socket) exercise the
  ladder logic itself: rung order, the 403/404 distinction, per-host
  header memory, and the no-links -> headless trigger.
- A handful of narrow branch tests inject a fake `aiohttp.ClientSession`
  that raises a specific real aiohttp exception class (`ClientConnectorDNSError`,
  `ServerDisconnectedError`) to exercise the dns/timeout/dropped
  classification -- these are synthetic (there's no real flaky host wired
  into the test suite), commented as such, and only cover the branch a
  live host can't be relied on to reproduce on demand.
- `tests/fixtures/generic_fallback/wayne_akamai_403.html` is a REAL,
  captured Akamai "Access Denied" body (see that module's own comment) --
  reused here rather than hand-building an Akamai-shaped fixture.

The headless and Wayback rungs monkeypatch `fetch_headless_sync`/
`cdx_get`/`wayback_id_read` at the names `fetch.py` imported them under --
a real headless Chromium launch and a real archive.org round-trip are
covered separately by this WO's live check (see the PR description) and
by `tests/test_wo909_headless_chromium_path.py` for the underlying
Playwright helper itself.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from app.platforms.meeting_finder import fetch as fetch_module
from app.platforms.meeting_finder.fetch import BudgetExceeded, Fetcher
from scripts.wo147_access_ladder_sweep import BROWSER_HEADERS, HONEST_HEADERS
from tests.conftest import load_fixture

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _reset_host_pacer():
    """WO-1030 added a process-wide per-host pacer (`_HOST_PACER_NEXT_AT`)
    shared by every `Fetcher` instance, so two concurrent governments
    sharing a vendor host still get spaced out (see that module's own
    comment). Every test in this file hits `127.0.0.1` (the loopback
    `TestServer`), so without a reset the pacer would carry a real delay
    over from one test to the next and make this whole suite serialize
    at `per_host_delay_s` per test -- reset before and after each test so
    the pacer's own cross-instance behavior is tested deliberately (see
    `test_shared_host_pacer_spaces_two_fetcher_instances`) without
    silently taxing every other test in this file."""
    fetch_module._HOST_PACER_NEXT_AT.clear()
    yield
    fetch_module._HOST_PACER_NEXT_AT.clear()


# No `pytestmark = pytest.mark.asyncio` here: `pytest.ini` sets
# `asyncio_mode = auto`, which already collects every `async def test_*`
# below as an asyncio test on its own. A blanket module-level mark would
# also apply (harmlessly, but with a warning -- see other test files that
# do this) to this file's two plain synchronous subprocess tests below.


# ---------------------------------------------------------------------------
# Real loopback server helpers
# ---------------------------------------------------------------------------


async def _make_server(handler_map: dict) -> TestServer:
    """handler_map: {path: async def handler(request) -> web.Response}"""
    app = web.Application()
    for path, handler in handler_map.items():
        app.router.add_get(path, handler)
    server = TestServer(app)
    await server.start_server()
    return server


# ---------------------------------------------------------------------------
# YouTube refusal -- rung 0, no request at all
# ---------------------------------------------------------------------------


async def test_youtube_host_refused_without_a_request():
    fetcher = Fetcher()
    result = await fetcher.fetch("https://www.youtube.com/watch?v=abc123")
    assert result.access_mode == "dead"
    assert result.outcome == "youtube-not-fetched"
    assert result.html is None
    assert fetcher.fetches_used == 0


async def test_youtu_be_short_link_also_refused():
    fetcher = Fetcher()
    result = await fetcher.fetch("https://youtu.be/abc123")
    assert result.outcome == "youtube-not-fetched"
    assert fetcher.fetches_used == 0


# ---------------------------------------------------------------------------
# Conductor review (WO-1025): `youtube_fetch_guard.install()` makes ANY
# YouTube hostname lookup raise for the rest of the PROCESS -- installing
# it merely by importing this module would break YouTube for every other
# caller sharing that process. It must only be installed once a Fetcher is
# actually constructed. `scripts.youtube_fetch_guard._installed` is
# process-global and never reset, so these run in fresh subprocesses
# rather than sharing this test file's own process (every other test
# above already constructs a Fetcher, which would make the guard look
# permanently installed from here on).
# ---------------------------------------------------------------------------


def _run_in_fresh_subprocess(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=30,
    )


def test_importing_fetch_module_does_not_install_the_youtube_guard():
    script = (
        "import scripts.youtube_fetch_guard as guard\n"
        "import app.platforms.meeting_finder.fetch  # noqa: F401\n"
        "assert guard._installed is False, "
        "'importing fetch.py alone installed the process-wide YouTube guard'\n"
        "print('ok')\n"
    )
    result = _run_in_fresh_subprocess(script)
    assert result.returncode == 0, result.stdout + result.stderr


def test_constructing_a_fetcher_installs_the_youtube_guard():
    script = (
        "import scripts.youtube_fetch_guard as guard\n"
        "from app.platforms.meeting_finder.fetch import Fetcher\n"
        "assert guard._installed is False\n"
        "Fetcher()\n"
        "assert guard._installed is True\n"
        "print('ok')\n"
    )
    result = _run_in_fresh_subprocess(script)
    assert result.returncode == 0, result.stdout + result.stderr


# ---------------------------------------------------------------------------
# Plain rung: success, and the 404-never-escalates rule
# ---------------------------------------------------------------------------


async def test_plain_request_succeeds_with_links():
    async def homepage(request):
        return web.Response(
            text='<html><body><a href="/agendas">Agendas</a></body></html>',
            content_type="text/html",
        )

    server = await _make_server({"/": homepage})
    try:
        fetcher = Fetcher()
        result = await fetcher.fetch(str(server.make_url("/")))
        assert result.status == 200
        assert result.access_mode == "plain"
        assert result.outcome is None
        assert not result.challenge
        assert "agendas" in (result.html or "").lower()
        assert fetcher.fetches_used == 1
    finally:
        await fetcher.aclose()
        await server.close()


async def test_404_is_final_and_never_escalates_to_browser_headers():
    request_count = {"n": 0}

    async def missing(request):
        request_count["n"] += 1
        return web.Response(status=404, text="not found")

    server = await _make_server({"/gone": missing})
    try:
        fetcher = Fetcher()
        result = await fetcher.fetch(str(server.make_url("/gone")))
        assert result.status == 404
        assert result.access_mode == "plain"
        assert result.outcome is None
        # CLAUDE.md's "politely" rule / docs/MEETING_FINDER.md: never
        # retry with browser headers after a 404.
        assert request_count["n"] == 1
        assert fetcher.fetches_used == 1
    finally:
        await fetcher.aclose()
        await server.close()


# ---------------------------------------------------------------------------
# 403 -> browser headers, and per-host header memory
# (rtr-upcoming UPCOMING_AGENDAS_FIELD_GUIDE.md "Blocked hosts", Marin
# County/Municode-shaped: a host that 403s the honest UA but serves the
# browser header set, remembered for the rest of the run.)
# ---------------------------------------------------------------------------


async def test_403_on_honest_headers_retries_with_browser_headers():
    seen_user_agents = []

    async def gate(request):
        ua = request.headers.get("User-Agent", "")
        seen_user_agents.append(ua)
        if ua == HONEST_HEADERS["user-agent"]:
            return web.Response(status=403, text="forbidden")
        return web.Response(
            text='<html><body><a href="/x">x</a></body></html>',
            content_type="text/html",
        )

    server = await _make_server({"/page": gate})
    try:
        fetcher = Fetcher()
        result = await fetcher.fetch(str(server.make_url("/page")))
        assert result.status == 200
        assert result.access_mode == "browser-headers"
        assert result.outcome is None
        assert seen_user_agents == [
            HONEST_HEADERS["user-agent"],
            BROWSER_HEADERS["user-agent"],
        ]
        # Two real fetches for this one logical fetch() call (honest,
        # then browser).
        assert fetcher.fetches_used == 2

        host = server.make_url("/").host
        assert fetcher._host_header_mode[host] == "browser"

        # A second fetch() to the SAME host goes straight to browser
        # headers -- only one more real request, not two.
        seen_user_agents.clear()
        result2 = await fetcher.fetch(str(server.make_url("/page")))
        assert result2.access_mode == "browser-headers"
        assert result2.status == 200
        assert seen_user_agents == [BROWSER_HEADERS["user-agent"]]
        assert fetcher.fetches_used == 3
    finally:
        await fetcher.aclose()
        await server.close()


async def test_plain_headers_remembered_when_they_already_work():
    async def homepage(request):
        # A link, so this fetch() never escalates to headless -- keeps
        # this test isolated to header-memory, not the headless rung
        # (and doesn't depend on a real Chromium binary being installed).
        return web.Response(text='<html><body><a href="/x">hi</a></body></html>')

    server = await _make_server({"/": homepage})
    try:
        fetcher = Fetcher()
        await fetcher.fetch(str(server.make_url("/")))
        host = server.make_url("/").host
        assert fetcher._host_header_mode[host] == "plain"
    finally:
        await fetcher.aclose()
        await server.close()


async def test_403_on_both_header_sets_is_blocked_browser_headers_not_a_challenge():
    async def always_403(request):
        return web.Response(status=403, text="<html>forbidden, plain and simple</html>")

    server = await _make_server({"/nope": always_403})
    try:
        fetcher = Fetcher()
        result = await fetcher.fetch(str(server.make_url("/nope")))
        # rtr-upcoming field guide point 4: a bare 403 is not a challenge
        # page by itself.
        assert result.outcome == "blocked-browser-headers"
        assert not result.challenge
        assert result.access_mode == "browser-headers"
    finally:
        await fetcher.aclose()
        await server.close()


# ---------------------------------------------------------------------------
# Challenge detection -> Wayback fallback (links only)
# ---------------------------------------------------------------------------


async def test_cloudflare_challenge_on_plain_200_falls_back_to_wayback_links_only():
    async def challenge_page(request):
        return web.Response(text="<title>Just a moment...</title>", status=200)

    server = await _make_server({"/gated": challenge_page})

    canned_cdx = json.dumps(
        [
            ["original", "timestamp"],
            ["https://example.gov/gated", "20260101000000"],
        ]
    ).encode()

    class _FakeCdxResponse:
        text = canned_cdx.decode()

    def fake_cdx_get(url):
        assert "web.archive.org/cdx/search/cdx" in url
        return _FakeCdxResponse()

    def fake_wayback_id_read(url, timestamp):
        assert timestamp == "20260101000000"
        return b'<html><body><a href="/archived-agenda">old agenda</a></body></html>'

    try:
        import scripts.wo282_recon as wo282_recon

        orig_cdx_get = wo282_recon.cdx_get
        orig_wayback_id_read = wo282_recon.wayback_id_read
        fetch_module.cdx_get = fake_cdx_get
        fetch_module.wayback_id_read = fake_wayback_id_read

        fetcher = Fetcher()
        result = await fetcher.fetch(str(server.make_url("/gated")))
        assert result.challenge is True
        assert result.outcome == "cloudflare-challenge-blocked"
        assert result.access_mode == "wayback"
        assert result.links_only is True
        assert result.wayback_timestamp == "20260101000000"
        assert "archived-agenda" in (result.html or "")
    finally:
        fetch_module.cdx_get = orig_cdx_get
        fetch_module.wayback_id_read = orig_wayback_id_read
        await fetcher.aclose()
        await server.close()


async def test_akamai_access_denied_fixture_classified_as_waf_akamai():
    # Real, captured Akamai block body (tests/fixtures/generic_fallback/
    # wayne_akamai_403.html) -- see that module's own comment for
    # provenance. Reused here instead of a hand-built fixture.
    body = load_fixture("generic_fallback", "wayne_akamai_403.html")

    async def akamai_block(request):
        return web.Response(text=body, status=403, content_type="text/html")

    server = await _make_server({"/blocked": akamai_block})
    try:
        fetcher = Fetcher(allow_wayback=False)
        result = await fetcher.fetch(str(server.make_url("/blocked")))
        assert result.challenge is True
        assert result.outcome == "blocked-waf-akamai"
    finally:
        await fetcher.aclose()
        await server.close()


async def test_challenge_without_wayback_allowed_has_no_link_only_fallback():
    async def challenge_page(request):
        return web.Response(text="<title>Just a moment...</title>")

    server = await _make_server({"/gated": challenge_page})
    try:
        fetcher = Fetcher(allow_wayback=False)
        result = await fetcher.fetch(str(server.make_url("/gated")))
        assert result.challenge is True
        assert result.outcome == "cloudflare-challenge-blocked"
        assert result.html is None
        assert result.links_only is False
    finally:
        await fetcher.aclose()
        await server.close()


# ---------------------------------------------------------------------------
# Headless rung: only when 200 + no links + need_links
# ---------------------------------------------------------------------------


async def test_no_links_on_200_triggers_headless_when_links_needed():
    async def js_shell(request):
        return web.Response(text="<html><body><div id='app'></div></body></html>")

    server = await _make_server({"/spa": js_shell})

    def fake_fetch_headless_sync(url):
        return (
            '<html><body><a href="/rendered">rendered</a></body></html>',
            url,
            None,
        )

    orig = fetch_module.fetch_headless_sync
    fetch_module.fetch_headless_sync = fake_fetch_headless_sync
    try:
        fetcher = Fetcher()
        result = await fetcher.fetch(str(server.make_url("/spa")), need_links=True)
        assert result.access_mode == "headless"
        assert result.outcome is None
        assert "rendered" in (result.html or "")
        # One plain fetch + one headless fetch.
        assert fetcher.fetches_used == 2
    finally:
        fetch_module.fetch_headless_sync = orig
        await fetcher.aclose()
        await server.close()


async def test_no_links_on_200_skips_headless_when_need_links_is_false():
    async def js_shell(request):
        return web.Response(text="<html><body><div id='app'></div></body></html>")

    server = await _make_server({"/spa": js_shell})
    calls = {"n": 0}

    def fake_fetch_headless_sync(url):
        calls["n"] += 1
        return "<html></html>", url, None

    orig = fetch_module.fetch_headless_sync
    fetch_module.fetch_headless_sync = fake_fetch_headless_sync
    try:
        fetcher = Fetcher()
        result = await fetcher.fetch(str(server.make_url("/spa")), need_links=False)
        assert result.access_mode == "plain"
        assert calls["n"] == 0
        assert fetcher.fetches_used == 1
    finally:
        fetch_module.fetch_headless_sync = orig
        await fetcher.aclose()
        await server.close()


async def test_headless_failure_is_blocked_headless_outcome():
    async def js_shell(request):
        return web.Response(text="<html><body><div id='app'></div></body></html>")

    server = await _make_server({"/spa": js_shell})

    def fake_fetch_headless_sync(url):
        return None, url, "playwright not installed"

    orig = fetch_module.fetch_headless_sync
    fetch_module.fetch_headless_sync = fake_fetch_headless_sync
    try:
        fetcher = Fetcher()
        result = await fetcher.fetch(str(server.make_url("/spa")))
        assert result.access_mode == "headless"
        assert result.outcome == "blocked-headless"
    finally:
        fetch_module.fetch_headless_sync = orig
        await fetcher.aclose()
        await server.close()


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------


async def test_budget_exceeded_raises_before_the_request():
    async def homepage(request):
        # Has a link, so this single fetch() call never escalates to
        # headless -- keeps this test isolated to the budget check itself.
        return web.Response(text='<html><body><a href="/x">x</a></body></html>')

    server = await _make_server({"/": homepage})
    try:
        fetcher = Fetcher(max_fetches=1)
        await fetcher.fetch(str(server.make_url("/")))
        assert fetcher.fetches_used == 1
        with pytest.raises(BudgetExceeded):
            await fetcher.fetch(str(server.make_url("/")))
    finally:
        await fetcher.aclose()
        await server.close()


# ---------------------------------------------------------------------------
# Synthetic exception-classification tests (see module docstring: no real
# flaky host is wired into this suite, so a DNS failure and a dropped
# connection are injected via a fake session that raises the real aiohttp
# exception class a live host would produce).
# ---------------------------------------------------------------------------


class _RaisingContextManager:
    def __init__(self, exc: Exception):
        self._exc = exc

    async def __aenter__(self):
        raise self._exc

    async def __aexit__(self, *exc_info):
        return False


class _RaisingSession:
    """Synthetic stand-in for aiohttp.ClientSession: raises a given
    exception on every .get(), used only to exercise Fetcher._plain_get's
    own classification of that exception -- never a substitute for the
    real-server tests above."""

    def __init__(self, exc: Exception):
        self._exc = exc
        self.closed = False

    def get(self, url, headers=None, allow_redirects=True):
        return _RaisingContextManager(self._exc)

    async def close(self):
        self.closed = True


async def test_dns_unresolvable_is_classified_from_a_real_aiohttp_exception():
    fetcher = Fetcher()
    fetcher._session = _RaisingSession(
        aiohttp.ClientConnectorDNSError(None, OSError("nodename nor servname known"))
    )
    result = await fetcher.fetch("https://this-host-does-not-resolve.example/")
    assert result.outcome == "dns-unresolvable"
    assert result.access_mode == "plain"


async def test_dropped_connection_retries_with_browser_headers():
    # rtr-upcoming field guide: a RemoteDisconnected-shaped reset (no
    # status line) must retry with browser headers, same as a 403.
    fetcher = Fetcher()
    fetcher._session = _RaisingSession(aiohttp.ServerDisconnectedError())
    result = await fetcher.fetch("https://example.invalid/")
    assert result.access_mode == "browser-headers"
    assert result.outcome == "blocked-browser-headers"


# ---------------------------------------------------------------------------
# WO-1030: the shared per-host pacer -- politeness across CONCURRENT
# Fetcher instances (one per government under runner.py's --concurrency),
# not just within one instance.
# ---------------------------------------------------------------------------


async def test_shared_host_pacer_spaces_two_fetcher_instances():
    import asyncio
    import time

    hits = []

    async def handler(request):
        hits.append(time.monotonic())
        return web.Response(text="<html><a href='/x'>x</a></html>")

    server = await _make_server({"/a": handler, "/b": handler})
    try:
        base = f"http://{server.host}:{server.port}"
        delay = 0.4
        fetcher_a = Fetcher(per_host_delay_s=delay, allow_headless=False)
        fetcher_b = Fetcher(per_host_delay_s=delay, allow_headless=False)

        start = time.monotonic()
        await asyncio.gather(
            fetcher_a.fetch(f"{base}/a"),
            fetcher_b.fetch(f"{base}/b"),
        )
        elapsed = time.monotonic() - start

        # Two DIFFERENT Fetcher instances, same host -- without the
        # shared pacer, both requests fire back-to-back (near-zero
        # elapsed); with it, the second one waits out the first's own
        # per_host_delay_s.
        assert elapsed >= delay * 0.9
        assert len(hits) == 2
        assert (hits[1] - hits[0]) >= delay * 0.9
    finally:
        await server.close()
