"""Tests for scripts/transcribe_backlog_locally.py's retry/resilience/
visibility helpers -- added alongside the 2026-08-17 fix for a real
overnight-run failure: the script's very first HTTP call (GET
/internal/transcription-backlog) hit a transient 502 and crashed the
entire batch before the main loop even started (see BACKLOG_DONE.md).

`_request_json()`'s retry loop is tested against a *real* aiohttp server
on a loopback port (`_CountingServer` below), not a mocked
aiohttp.ClientSession -- per this repo's own "synthetic tests are for one
already-real-verified logic branch, never a substitute for testing
against something real" convention (CLAUDE.md). There's no live
government site to test an HTTP retry loop against the way a platform
adapter would be, so a real local TCP server standing in for the Archive
API is the equivalent here: genuine sockets, a genuine HTTP
request/response cycle, no aiohttp internals mocked away.
"""

import sys
from pathlib import Path

import aiohttp
import pytest
from aiohttp import web

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import transcribe_backlog_locally as tbl  # noqa: E402


class _CountingServer:
    """A real aiohttp server bound to an OS-assigned loopback port. `statuses`
    is a queue of HTTP statuses to return, one per request received (a 200
    with a canned JSON body once the queue is empty) -- lets a test script
    "fail N times, then succeed" against a real socket."""

    def __init__(self):
        self.request_count = 0
        self.statuses: list = []
        self.runner: web.AppRunner | None = None
        self.port: int | None = None

    async def _handler(self, request: web.Request) -> web.Response:
        self.request_count += 1
        status = self.statuses.pop(0) if self.statuses else 200
        if status >= 400:
            return web.Response(status=status, text=f"synthetic error {status}")
        return web.json_response({"ok": True, "pages": []})

    async def start(self) -> None:
        app = web.Application()
        app.router.add_route("*", "/{tail:.*}", self._handler)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.port = site._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        await self.runner.cleanup()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/internal/transcription-backlog"


@pytest.fixture
async def counting_server():
    server = _CountingServer()
    await server.start()
    yield server
    await server.stop()


@pytest.fixture(autouse=True)
def fast_retries(monkeypatch):
    """Keeps the real exponential-backoff-with-jitter *mechanism* in
    _request_json() intact (still real asyncio.sleep() calls between real
    HTTP attempts) but shrinks the delays so this suite runs in well under
    a second instead of exercising the real ~5-90s production backoff
    window."""
    monkeypatch.setattr(tbl, "RETRY_BASE_DELAY_SECONDS", 0.01)
    monkeypatch.setattr(tbl, "RETRY_MAX_DELAY_SECONDS", 0.05)


async def test_request_json_retries_a_real_502_then_succeeds(counting_server):
    """The exact real-world shape from the 2026-08-16/17 incident: the
    first attempt(s) at the candidate-list fetch hit a transient 5xx, and
    a later attempt succeeds. Confirms the retry loop keeps going past a
    real failed HTTP response and returns the real parsed JSON body once
    the server recovers -- not just that it doesn't crash."""
    counting_server.statuses = [502, 502]
    async with aiohttp.ClientSession() as session:
        data = await tbl._request_json(
            session, "GET", counting_server.url, label="test fetch", max_retries=5
        )
    assert data == {"ok": True, "pages": []}
    assert counting_server.request_count == 3  # 2 real failures + 1 real success


async def test_request_json_does_not_retry_a_4xx(counting_server):
    """A 4xx from our own Archive API (bad token, malformed request) is a
    real, static problem -- retrying it for minutes wastes an unattended
    run's time for no benefit. Confirms it fails on the very first
    attempt, with a message that says so rather than looking identical to
    a retryable failure."""
    counting_server.statuses = [404]
    async with aiohttp.ClientSession() as session:
        with pytest.raises(RuntimeError, match="not retrying"):
            await tbl._request_json(
                session, "GET", counting_server.url, label="test fetch", max_retries=5
            )
    assert counting_server.request_count == 1


async def test_request_json_gives_up_after_max_retries_on_persistent_5xx(
    counting_server,
):
    """A genuinely down dependency (not just a blip) should eventually stop
    retrying and raise -- confirms it tries exactly `max_retries` times
    against the real server (not fewer, not forever) before giving up."""
    counting_server.statuses = [503] * 10  # more than max_retries below
    async with aiohttp.ClientSession() as session:
        with pytest.raises(RuntimeError, match=r"failed after 3 attempts"):
            await tbl._request_json(
                session, "GET", counting_server.url, label="test fetch", max_retries=3
            )
    assert counting_server.request_count == 3


async def test_request_json_retries_a_real_connection_error(unused_tcp_port):
    """Distinct failure mode from an HTTP 5xx: nothing listening on the
    port at all (a real aiohttp.ClientConnectorError from a real refused
    connection, not an HTTP response). Confirms the same retry loop
    catches connection-level failures too, since a machine losing network
    mid-run looks like this, not like a 5xx."""
    url = f"http://127.0.0.1:{unused_tcp_port}/internal/transcription-backlog"
    async with aiohttp.ClientSession() as session:
        with pytest.raises(RuntimeError, match=r"failed after 3 attempts"):
            await tbl._request_json(
                session, "GET", url, label="test fetch", max_retries=3
            )


async def test_get_candidates_survives_a_transient_502(counting_server, monkeypatch):
    """End-to-end through the real function the script's main() calls for
    its very first network request -- not just the shared helper."""
    counting_server.statuses = [502]
    monkeypatch.setattr(tbl, "_base_url", lambda: f"http://127.0.0.1:{counting_server.port}")
    monkeypatch.setattr(tbl, "_headers", lambda: {})
    async with aiohttp.ClientSession() as session:
        pages = await tbl._get_candidates(session, limit=5)
    assert pages == []
    assert counting_server.request_count == 2


def test_note_if_suspended_warns_on_a_real_wall_vs_monotonic_skew(caplog):
    """Backdating wall_before/mono_before simulates what a real machine
    sleep looks like from these two clocks' perspective: time.time()
    (wall clock) shows several minutes elapsed, time.monotonic() shows
    almost none, because monotonic doesn't advance while macOS is
    suspended. Confirms the gap is actually detected and logged, not just
    that the function exists."""
    import time

    now_wall = time.time()
    now_mono = time.monotonic()
    with caplog.at_level("WARNING", logger="rtr_transcribe_backlog"):
        tbl._note_if_suspended(
            now_wall - 300, now_mono - 2, "test context"
        )  # 300s wall, ~2s processing -> ~298s skew
    assert any("gap" in record.message.lower() for record in caplog.records)


def test_note_if_suspended_silent_when_clocks_agree(caplog):
    """The common case -- real continuous work, no suspend -- must not log
    anything; otherwise every normal chunk would spam a false warning."""
    import time

    now_wall = time.time()
    now_mono = time.monotonic()
    with caplog.at_level("WARNING", logger="rtr_transcribe_backlog"):
        tbl._note_if_suspended(now_wall, now_mono, "test context")
    assert caplog.records == []


def test_save_local_backup_writes_recoverable_json(tmp_path, monkeypatch):
    """Confirms a failed ingest's payload actually lands on disk, readable
    back as the same JSON body _ingest() would have POSTed -- this is what
    stands between a transient outage and silently losing real, completed
    local Whisper compute."""
    import json

    monkeypatch.setattr(tbl, "FAILED_INGEST_DIR", tmp_path / "backups")
    payload = {"platform": "granicus", "segments": [{"start": 0, "text": "hello"}]}
    path = tbl._save_local_backup(payload, "some/weird slug!!")
    assert path.exists()
    assert json.loads(path.read_text()) == payload
    assert path.parent == tmp_path / "backups"
