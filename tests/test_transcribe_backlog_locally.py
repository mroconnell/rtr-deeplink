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

import json
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
    monkeypatch.setattr(
        tbl, "_base_url", lambda: f"http://127.0.0.1:{counting_server.port}"
    )
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


# --- transcribe_meeting()'s live-source retries + partial-progress save ----
#
# Added 2026-08-22 with the fix for BACKLOG.md's "gives up on a live meeting
# after one transient failure". SYNTHETIC in that the finder / ffmpeg /
# whisper calls are fakes -- deliberately, and per this repo's own rule that
# a synthetic test is for a branch already confirmed against real data:
#   * the failure *shapes* are real, taken from the confirmed cases -- a
#     bare `TimeoutError` from a `pub-*.escribemeetings.com` resolve
#     (pub-abbotsford, pub-acwtownship, 2026-08-21/22) and
#     `"ffmpeg timed out after 120s (source likely slow or rate-limited)"`,
#     which is extract_chunk_audio()'s own real string for the 120s
#     _SUBPROCESS_TIMEOUT_SECONDS expiry that hit Piqua OH on chunk 1/14
#     and 4 of a new.swagit.com batch;
#   * the "transcribed most of it, then failed on a later chunk" shape is
#     the real pub-3ce.escribemeetings.com case (55 chunks, 50 done, failed
#     on 51), which is what made the partial-progress save load-bearing;
#   * ResolvedMeeting is the real model every adapter returns, not an
#     invented shape.
# What a fake buys that a live URL can't: "fails once, then succeeds
# unchanged" is precisely the behavior under test, and no real government
# source can be asked to do that on demand. Still unconfirmed and not
# claimed here: whether one retry is enough in practice -- it demonstrably
# isn't for Brookhaven NY, which failed two identical back-to-back retries
# (see MEDIA_ATTEMPTS' own comment).

from app.platforms.base import UnsupportedPlatformError  # noqa: E402
from app.platforms.models import ResolvedMeeting  # noqa: E402

_REAL_ESCRIBE_URL = "https://pub-3ce.escribemeetings.com/Meeting.aspx?Id=fake-for-test"
_REAL_FFMPEG_TIMEOUT_REASON = (
    "ffmpeg timed out after 120s (source likely slow or rate-limited)"
)


def _resolved(video_url="https://example.org/meeting.m3u8"):
    return ResolvedMeeting(
        platform="escribe",
        source_url=_REAL_ESCRIBE_URL,
        video_url=video_url,
        video_format="m3u8",
    )


class _FakeEngine:
    """Stands in for FasterWhisperEngine -- one segment per chunk, timed
    from 0 within that chunk the way the real engine's output is (it's
    shift_segments() that makes them meeting-relative)."""

    def __init__(self):
        self.chunks_transcribed = 0

    async def transcribe_chunk(self, audio_path):
        self.chunks_transcribed += 1
        return [{"start": 0.0, "end": 5.0, "text": f"chunk {self.chunks_transcribed}"}]


class _AlwaysResolves:
    async def resolve(self, url):
        return _resolved()


@pytest.fixture
def local_media(monkeypatch, tmp_path):
    """Points the script's live-source calls at fakes and its checkpoint
    directory at tmp_path, with real-but-tiny retry delays -- the real
    backoff mechanism still runs, it just doesn't spend the production
    5-15s window."""
    monkeypatch.setattr(tbl, "MEDIA_RETRY_BASE_DELAY_SECONDS", 0.001)
    monkeypatch.setattr(tbl, "MEDIA_RETRY_MAX_DELAY_SECONDS", 0.002)
    monkeypatch.setattr(tbl, "PARTIAL_PROGRESS_DIR", tmp_path / "partial")

    async def _probe(video_url, *, source_page_url):
        return 1800.0  # 2 chunks at the default 900s chunk size

    monkeypatch.setattr(tbl, "probe_duration", _probe)
    return monkeypatch


async def test_transcribe_meeting_retries_a_resolve_that_fails_once(local_media):
    """The confirmed 4/4 case: meetings recorded as permanently
    unresolvable that resolved fine on an unchanged re-run minutes later.
    One transient TimeoutError must no longer end the meeting."""
    calls = []

    class _Finder:
        async def resolve(self, url):
            calls.append(url)
            if len(calls) == 1:
                raise TimeoutError()
            return _resolved()

    local_media.setattr(tbl, "get_finder", lambda platform: _Finder())

    async def _extract(*args, **kwargs):
        return True, None

    local_media.setattr(tbl, "extract_chunk_audio", _extract)

    result = await tbl.transcribe_meeting(
        _FakeEngine(), _REAL_ESCRIBE_URL, "escribe", chunk_size_seconds=900
    )
    assert result["ok"] is True
    assert len(calls) == 2  # one real failure, one real success


async def test_transcribe_meeting_does_not_retry_an_unsupported_platform(local_media):
    """A permanent failure must stay fast and clearly labelled -- the retry
    must not turn "no adapter for this platform" into a slower path to the
    same answer."""

    def _no_finder(platform):
        raise UnsupportedPlatformError(platform)

    local_media.setattr(tbl, "get_finder", _no_finder)

    result = await tbl.transcribe_meeting(
        _FakeEngine(), _REAL_ESCRIBE_URL, "nope", chunk_size_seconds=900
    )
    assert result["ok"] is False
    assert "unsupported platform" in result["reason"]


async def test_transcribe_meeting_retries_a_chunk_extraction_that_fails_once(
    local_media,
):
    """The new.swagit.com case: 3 of 4 failed extractions succeeded on an
    immediate retry, and a manual ffmpeg against the exact failed URL
    finished in ~12s both times -- the source was never the problem."""
    attempts = []
    local_media.setattr(tbl, "get_finder", lambda platform: _AlwaysResolves())

    async def _extract(video_url, *, start, duration, source_page_url, out_path):
        attempts.append(start)
        if len(attempts) == 1:
            return False, _REAL_FFMPEG_TIMEOUT_REASON
        return True, None

    local_media.setattr(tbl, "extract_chunk_audio", _extract)

    engine = _FakeEngine()
    result = await tbl.transcribe_meeting(
        engine, _REAL_ESCRIBE_URL, "escribe", chunk_size_seconds=900
    )
    assert result["ok"] is True
    assert attempts == [0.0, 0.0, 900.0]  # chunk 1 twice (one retry), chunk 2 once
    assert engine.chunks_transcribed == 2


async def test_transcribe_meeting_does_not_retry_a_missing_ffmpeg(local_media):
    """ffmpeg absent from PATH is a broken machine, not a flaky CDN --
    retrying it only makes an unattended run slower at reaching the same
    answer, the same reason _request_json() fails a 4xx immediately."""
    attempts = []
    local_media.setattr(tbl, "get_finder", lambda platform: _AlwaysResolves())

    async def _extract(*args, **kwargs):
        attempts.append(1)
        return False, "ffmpeg not found on PATH"

    local_media.setattr(tbl, "extract_chunk_audio", _extract)

    result = await tbl.transcribe_meeting(
        _FakeEngine(), _REAL_ESCRIBE_URL, "escribe", chunk_size_seconds=900
    )
    assert result["ok"] is False
    assert len(attempts) == 1


async def test_a_late_chunk_failure_keeps_the_chunks_already_transcribed(local_media):
    """The pub-3ce.escribemeetings.com case in miniature: several chunks
    succeed, then one fails even after its retries. The finished chunks
    must survive on disk instead of the whole run being discarded."""
    local_media.setattr(tbl, "get_finder", lambda platform: _AlwaysResolves())

    async def _probe(video_url, *, source_page_url):
        return 4500.0  # 5 chunks

    local_media.setattr(tbl, "probe_duration", _probe)

    async def _extract(video_url, *, start, duration, source_page_url, out_path):
        if start >= 2700.0:  # chunk 4 of 5 and beyond
            return False, _REAL_FFMPEG_TIMEOUT_REASON
        return True, None

    local_media.setattr(tbl, "extract_chunk_audio", _extract)

    result = await tbl.transcribe_meeting(
        _FakeEngine(), _REAL_ESCRIBE_URL, "escribe", chunk_size_seconds=900
    )
    assert result["ok"] is False
    assert "chunk 4/5" in result["reason"]
    assert "resumes from there" in result["reason"]

    saved = json.loads(tbl._partial_progress_path(_REAL_ESCRIBE_URL).read_text())
    assert saved["chunks_done"] == 3
    assert saved["failed_on_chunk"] == 4
    assert saved["total_chunks"] == 5
    assert len(saved["segments"]) == 3
    # Stored whole-meeting-relative, not chunk-relative -- otherwise a
    # resumed run would splice in segments with wrong timestamps, and the
    # deep links are the product.
    assert [s["start"] for s in saved["segments"]] == [0.0, 900.0, 1800.0]


async def test_a_resumed_run_only_transcribes_the_remaining_chunks(local_media):
    """The payoff: the next run picks up where the failed one stopped
    rather than re-spending the Whisper compute (~44 minutes, in the real
    case) that already succeeded."""
    local_media.setattr(tbl, "get_finder", lambda platform: _AlwaysResolves())

    async def _probe(video_url, *, source_page_url):
        return 4500.0  # 5 chunks

    local_media.setattr(tbl, "probe_duration", _probe)

    failing_from = {"start": 2700.0}

    async def _extract(video_url, *, start, duration, source_page_url, out_path):
        if start >= failing_from["start"]:
            return False, _REAL_FFMPEG_TIMEOUT_REASON
        return True, None

    local_media.setattr(tbl, "extract_chunk_audio", _extract)

    first = await tbl.transcribe_meeting(
        _FakeEngine(), _REAL_ESCRIBE_URL, "escribe", chunk_size_seconds=900
    )
    assert first["ok"] is False

    # Second run, source now healthy -- as in every confirmed case, where an
    # unchanged re-run minutes later succeeded.
    failing_from["start"] = 99999.0
    engine = _FakeEngine()
    second = await tbl.transcribe_meeting(
        engine, _REAL_ESCRIBE_URL, "escribe", chunk_size_seconds=900
    )
    assert second["ok"] is True
    assert engine.chunks_transcribed == 2  # only chunks 4 and 5, not all 5
    assert [s["start"] for s in second["segments"]] == [
        0.0,
        900.0,
        1800.0,
        2700.0,
        3600.0,
    ]
    # Finished -- the checkpoint must be gone, or a later --url re-run of
    # this same page would silently resume from it instead of transcribing.
    assert not tbl._partial_progress_path(_REAL_ESCRIBE_URL).exists()


async def test_no_resume_ignores_an_existing_checkpoint(local_media):
    """--no-resume: a checkpoint is only validated for *chunking*, never
    for which model produced its text, so there has to be a way to discard
    one deliberately."""
    local_media.setattr(tbl, "get_finder", lambda platform: _AlwaysResolves())
    tbl._save_partial_progress(
        _REAL_ESCRIBE_URL,
        segments=[{"start": 0.0, "end": 5.0, "text": "stale"}],
        chunks_done=1,
        total_chunks=2,
        chunk_size_seconds=900,
        duration=1800.0,
        reason="test",
    )

    async def _extract(*args, **kwargs):
        return True, None

    local_media.setattr(tbl, "extract_chunk_audio", _extract)

    engine = _FakeEngine()
    result = await tbl.transcribe_meeting(
        engine, _REAL_ESCRIBE_URL, "escribe", chunk_size_seconds=900, resume=False
    )
    assert result["ok"] is True
    assert engine.chunks_transcribed == 2  # both chunks, checkpoint ignored
    assert not any(s["text"] == "stale" for s in result["segments"])


def test_a_checkpoint_from_a_different_chunking_is_refused(local_media):
    """A checkpoint written with a different --chunk-seconds (or against a
    source whose duration has since changed) describes segment offsets that
    no longer line up. Refusing it costs a re-transcription; accepting it
    would publish a transcript whose timestamps are quietly wrong."""
    tbl._save_partial_progress(
        _REAL_ESCRIBE_URL,
        segments=[{"start": 0.0, "end": 5.0, "text": "hello"}],
        chunks_done=1,
        total_chunks=2,
        chunk_size_seconds=900,
        duration=1800.0,
        reason="test",
    )
    assert tbl._load_partial_progress(
        _REAL_ESCRIBE_URL, chunk_size_seconds=900, total_chunks=2, duration=1800.0
    ) == (1, [{"start": 0.0, "end": 5.0, "text": "hello"}])
    assert tbl._load_partial_progress(
        _REAL_ESCRIBE_URL, chunk_size_seconds=600, total_chunks=3, duration=1800.0
    ) == (0, [])
    assert tbl._load_partial_progress(
        _REAL_ESCRIBE_URL, chunk_size_seconds=900, total_chunks=2, duration=2400.0
    ) == (0, [])
