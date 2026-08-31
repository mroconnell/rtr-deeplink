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


async def test_transcribe_meeting_skips_a_youtube_delegated_resolve(local_media):
    """Real, confirmed case (2026-08-23): ashlandcowi.portal.civicclerk.com
    event 395 has a real Planning Committee meeting whose CivicClerk
    externalMediaUrl is a youtu.be short link, which civicclerk.py
    correctly delegates to YouTubeAssetFinder -- so the resolve comes back
    with video_format="youtube" and a real youtube.com/embed/ video_url,
    not empty. Before this test's fix, that fell through straight to
    probe_duration() and failed with the opaque "ffprobe couldn't read the
    media" -- ffprobe genuinely cannot read a YouTube embed page -- instead
    of the clear, already-existing "needs fetch_youtube_transcripts.py"
    message process_one()'s own pre-filter gives for the same situation
    when it has stale video_format to work from (which --url mode never
    does, and which this exact page's fresh video_format didn't match
    either -- CivicClerk pages don't start out YouTube-flagged)."""

    class _YouTubeDelegated:
        async def resolve(self, url):
            return ResolvedMeeting(
                platform="civicclerk",
                source_url=url,
                video_url="https://www.youtube.com/embed/xOL1UiwcMG8",
                video_format="youtube",
            )

    local_media.setattr(tbl, "get_finder", lambda platform: _YouTubeDelegated())

    result = await tbl.transcribe_meeting(
        _FakeEngine(),
        "https://ashlandcowi.portal.civicclerk.com/event/395/media",
        "civicclerk",
        chunk_size_seconds=900,
    )
    assert result["ok"] is False
    assert "YouTube-backed" in result["reason"]


async def test_process_one_detects_platform_fresh_not_from_stale_page_field(
    local_media,
):
    """Real case, 2026-08-27: several ProudCity .gov pages (e.g.
    wilmingtonohio.gov) were ingested with platform="unknown" before
    #425-428 added ProudCity support, and that field on the candidate-list
    row never gets updated after the fact. Before this fix, process_one()
    passed that stale value straight to get_finder(), which raised
    UnsupportedPlatformError and silently hid an otherwise-resolvable
    meeting from every unattended run -- indistinguishable from a page on a
    genuinely unsupported site. It must use a fresh detect_platform() call
    on the real URL instead, the same classifier main()'s --url path
    already uses."""
    seen_platforms = []

    class _Finder:
        async def resolve(self, url):
            seen_platforms.append("resolved")
            return _resolved(video_url=None)

    def _get_finder(platform):
        seen_platforms.append(platform)
        return _Finder()

    local_media.setattr(tbl, "get_finder", _get_finder)

    page = {
        "slug": "wilmington-oh-council",
        "platform": "unknown",  # stale -- must not be trusted
        "source_url_normalized": "https://wilmingtonohio.gov/meetings/city-council-meeting-april-16-2026",
        "video_url": None,
        "video_format": None,
    }

    await tbl.process_one(
        None, _FakeEngine(), page, dry_run=True, chunk_seconds_override=900
    )
    assert seen_platforms[0] == "proudcity"


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


# --- whole-audio caching for seek-hostile progressive sources (WO-64) ------
#
# Ported from worker/main.py's WO-54 fix after the exact ChampDS symptom it
# was built for (ffmpeg timed out after 120s, per-chunk seeking on a
# progressive MP4) took out 5 of 5 real meetings in one local run on
# 2026-08-27 -- the fix existed in the cloud pipeline the whole time, but
# this script never got it. should_cache_whole_audio() is the same shared
# app/platforms/media_probe.py function the worker's own tests exercise
# (tests/test_whole_audio_cache.py) -- not re-tested here, just relied on.

_REAL_CHAMPDS_URL = (
    "https://play.champds.com/DOWNLOAD-MEDIA/oakhilltn/eventmainmedia/50"
)


class _ResolvesToChampds:
    """Unlike _AlwaysResolves (hard-coded to the default HLS-shaped
    _resolved()), returns the real, non-HLS ChampDS media shape that
    should_cache_whole_audio() must gate on."""

    async def resolve(self, url):
        return _resolved(video_url=_REAL_CHAMPDS_URL)


async def test_transcribe_meeting_caches_whole_audio_once_for_champds(local_media):
    """The whole point of WO-54/WO-64: one download for the whole meeting,
    then every chunk is a local slice -- extract_chunk_audio() (the old
    per-chunk seek path) must never be called at all."""
    local_media.setattr(tbl, "get_finder", lambda platform: _ResolvesToChampds())

    full_pulls = []
    slices = []

    async def _fake_full(media_url, *, source_page_url, out_path):
        full_pulls.append(media_url)
        out_path.write_bytes(b"\xff\xfb" + b"\x00" * 5000)
        return True, None

    async def _fake_slice(cached_path, *, start, duration, out_path):
        assert cached_path.exists()
        slices.append(start)
        out_path.write_bytes(b"\xff\xfb" + b"\x00" * 400)
        return True, None

    async def _fail_if_called(*a, **k):
        raise AssertionError(
            "per-chunk extraction must not run when the whole-audio cache succeeded"
        )

    local_media.setattr(tbl, "extract_full_audio", _fake_full)
    local_media.setattr(tbl, "slice_cached_audio", _fake_slice)
    local_media.setattr(tbl, "extract_chunk_audio", _fail_if_called)

    result = await tbl.transcribe_meeting(
        _FakeEngine(), _REAL_CHAMPDS_URL, "champds", chunk_size_seconds=900
    )
    assert result["ok"] is True
    assert full_pulls == [_REAL_CHAMPDS_URL]  # downloaded exactly once
    assert slices == [0.0, 900.0]  # both chunks sliced locally


async def test_transcribe_meeting_falls_back_to_per_chunk_after_a_failed_whole_audio_pull(
    local_media,
):
    """A failed whole-file pull (e.g. a file too large for the download's
    own budget) must not be retried on every remaining chunk -- that would
    burn a full timeout per chunk for no gain. Confirms exactly one
    whole-audio attempt for the entire meeting, with every chunk (including
    the one that triggered the failure) falling back to per-chunk
    extraction."""
    local_media.setattr(tbl, "get_finder", lambda platform: _ResolvesToChampds())

    full_pull_attempts = []
    per_chunk_calls = []

    async def _fake_full(media_url, *, source_page_url, out_path):
        full_pull_attempts.append(media_url)
        return False, "full-audio download timed out after 360s"

    async def _fake_per_chunk(media_url, *, start, duration, source_page_url, out_path):
        per_chunk_calls.append(start)
        out_path.write_bytes(b"\xff\xfb" + b"\x00" * 400)
        return True, None

    local_media.setattr(tbl, "extract_full_audio", _fake_full)
    local_media.setattr(tbl, "extract_chunk_audio", _fake_per_chunk)

    result = await tbl.transcribe_meeting(
        _FakeEngine(), _REAL_CHAMPDS_URL, "champds", chunk_size_seconds=900
    )
    assert result["ok"] is True
    assert len(full_pull_attempts) == 1  # not retried on chunk 2
    assert per_chunk_calls == [0.0, 900.0]  # every chunk still got transcribed


# --- WO-79 port: a real multi-clip Swagit meeting (2026-08-31) -------------
#
# BACKLOG.md's "Swagit multi-clip meetings" entry: worker/main.py's
# process_next_chunk() got a WO-79 fix (2026-08-30) for Swagit tenants that
# publish several real per-agenda-item video files with no single combined
# recording at the source (confirmed: Yolo County CA, White Plains NY,
# Apple Valley MN -- see app/platforms/swagit.py). Per this repo's own "two
# independent transcription paths" convention (CLAUDE.md), that fix did not
# reach this script on its own -- this ports the same
# ResolvedMeeting.video_segments -> probe_multi_clip_chunk_plan() ->
# per-clip-chunk -> shift_segments() approach into transcribe_meeting()'s
# own chunking loop.
#
# Reuses the SAME real fixture as tests/test_swagit.py's
# test_resolve_warns_when_meeting_has_multiple_playlist_segments() (a real
# jwplayer playlist independently fetched live from Yolo County CA clip
# 324107, 2026-08-29 -- 3 real clips, real seq numbers 6/13/51, real
# archive-stream.granicus.com URLs) rather than inventing new multi-clip
# data, per this repo's own "synthetic test, real fixture shape" rule.
# Per-clip *durations* are still synthetic (a real ffprobe against each of
# these URLs is a separate, live network call this test suite doesn't make)
# -- same approach tests/test_media_probe.py's own
# probe_multi_clip_chunk_plan() tests and
# tests/test_worker_multi_clip_chunk_plan.py's chunk_plan fixture both take.

from app.platforms import media_probe as _media_probe  # noqa: E402
from app.platforms.swagit import SwagitAssetFinder  # noqa: E402
from aiohttp_mock import FakeResponse, mock_session  # noqa: E402
from test_swagit import YOLO_MULTI_SEGMENT_HTML, YOLO_URL  # noqa: E402


async def _resolve_real_yolo_multi_clip_meeting():
    """The real ResolvedMeeting SwagitAssetFinder.resolve() produces for
    the Yolo County CA fixture -- 3 real video_segments (seq 6/13/51),
    same object shape a live production resolve of this exact page
    builds."""
    with mock_session(
        {YOLO_URL: FakeResponse(status=200, text=YOLO_MULTI_SEGMENT_HTML, url=YOLO_URL)}
    ):
        return await SwagitAssetFinder().resolve(YOLO_URL)


class _ResolvesToYoloMultiClip:
    def __init__(self, resolved):
        self._resolved = resolved

    async def resolve(self, url):
        return self._resolved


async def test_transcribe_meeting_stitches_a_real_multi_clip_swagit_meeting(
    local_media,
):
    """WO-79 port: transcribe_meeting() builds and consumes the same
    per-clip chunk plan the cloud worker's process_next_chunk() does (see
    tests/test_worker_multi_clip_chunk_plan.py) -- one chunk per real clip,
    extracted from THAT clip's own URL at start=0.0/duration=the clip's own
    full length, shifted by its own cumulative meeting-relative offset
    rather than a fixed chunk_size_seconds window. Also confirms the
    whole-audio cache (WO-64) never gets consulted for a chunk-plan
    meeting -- identical reasoning to the worker's own
    test_process_next_chunk_does_not_cache_whole_audio_for_a_chunk_plan_job."""
    resolved = await _resolve_real_yolo_multi_clip_meeting()
    assert len(resolved.video_segments) == 3  # sanity: the real fixture

    local_media.setattr(
        tbl, "get_finder", lambda platform: _ResolvesToYoloMultiClip(resolved)
    )

    clip_urls = [seg.url for seg in resolved.video_segments]
    durations = {clip_urls[0]: 120.0, clip_urls[1]: 300.0, clip_urls[2]: 45.0}

    async def _probe(url, *, source_page_url):
        assert source_page_url == resolved.source_url
        return durations[url]

    # probe_multi_clip_chunk_plan() (imported by reference into tbl's own
    # namespace) calls probe_duration() via ITS OWN module's globals, not
    # tbl's -- patching tbl.probe_duration alone (as `local_media` already
    # does, for the single-clip fallback path) would not reach it.
    local_media.setattr(_media_probe, "probe_duration", _probe)

    def _fail_should_cache(media_url, total_chunks):
        raise AssertionError(
            "should_cache_whole_audio must never be consulted for a "
            "chunk-plan meeting -- different clips are different files, "
            "not offsets into the same one"
        )

    local_media.setattr(tbl, "should_cache_whole_audio", _fail_should_cache)

    async def _fail_extract_full(*args, **kwargs):
        raise AssertionError(
            "whole-audio caching must never run for a chunk-plan meeting"
        )

    local_media.setattr(tbl, "extract_full_audio", _fail_extract_full)

    extract_calls = []

    async def _extract(media_url, *, start, duration, source_page_url, out_path):
        extract_calls.append(
            {"media_url": media_url, "start": start, "duration": duration}
        )
        out_path.write_bytes(b"fake-audio")
        return True, None

    local_media.setattr(tbl, "extract_chunk_audio", _extract)

    engine = _FakeEngine()
    result = await tbl.transcribe_meeting(
        engine, resolved.source_url, "swagit", chunk_size_seconds=900
    )

    assert result["ok"] is True
    # Each of the 3 real clips extracted from its OWN url, at start=0.0
    # with that clip's own full duration -- never the first clip's URL
    # reused, never a chunk_size_seconds-windowed start/duration.
    assert extract_calls == [
        {"media_url": clip_urls[0], "start": 0.0, "duration": 120.0},
        {"media_url": clip_urls[1], "start": 0.0, "duration": 300.0},
        {"media_url": clip_urls[2], "start": 0.0, "duration": 45.0},
    ]
    assert engine.chunks_transcribed == 3
    # Stitched onto one meeting-relative timeline: each chunk's own segment
    # (start=0.0 within that chunk, per _FakeEngine) shifted by that
    # clip's own cumulative offset (0, 120, 420) -- deliberately different
    # from the extraction start (always 0.0 for a whole-clip chunk).
    assert [s["start"] for s in result["segments"]] == [0.0, 120.0, 420.0]
    assert [s["text"] for s in result["segments"]] == [
        "chunk 1",
        "chunk 2",
        "chunk 3",
    ]


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


# --- per-meeting chunk-size decision (WO-75, 2026-08-30) -------------------
#
# Closes BACKLOG.md's "[NEEDS-AUDIT] scripts/transcribe_backlog_locally.py
# doesn't get the [Granicus 300s-chunk fix] automatically" entry: this
# script previously picked one chunk_seconds value once in main(), before
# any candidate page (or its platform) was known, so a Granicus meeting run
# through it never got app/platforms/media_probe.py's
# chunk_size_seconds_for_platform()'s smaller 300s Granicus default the way
# app/main.py and worker/main.py's real job-creation paths already do.
# _resolve_chunk_seconds() is the new per-page hook -- these tests are
# SYNTHETIC (no live source involved, just the decision function and
# process_one()'s wiring to it) since chunk_size_seconds_for_platform()
# itself already has real-measured backing (see its own module comment in
# media_probe.py) -- what's actually new and worth testing here is only the
# *per-meeting* plumbing, not the underlying 300s/900s values.

_REAL_GRANICUS_URL = "https://cityoftacoma.granicus.com/player/clip/7460"


def test_resolve_chunk_seconds_uses_granicus_default_for_whisper():
    """No --chunk-seconds override, whisper engine, Granicus platform -->
    the smaller 300s default from chunk_size_seconds_for_platform(), same
    as app/main.py and worker/main.py already get."""
    assert (
        tbl._resolve_chunk_seconds(
            override=None, engine_kind="whisper", platform="granicus"
        )
        == 300
    )


def test_resolve_chunk_seconds_uses_900_default_for_other_platforms():
    """Every non-Granicus platform still gets the ordinary 900s default via
    the same shared function -- confirms this isn't a Granicus-only special
    case bolted on beside chunk_size_seconds_for_platform() instead of
    calling it."""
    assert (
        tbl._resolve_chunk_seconds(
            override=None, engine_kind="whisper", platform="escribe"
        )
        == tbl.CHUNK_SIZE_SECONDS
        == 900
    )


def test_resolve_chunk_seconds_explicit_override_wins_even_for_granicus():
    """--chunk-seconds must still be able to force a specific value that
    takes precedence over the per-platform default -- the exact behavior
    this change was told to preserve, exercised against the one platform
    where the default now differs from the flat 900s constant."""
    assert (
        tbl._resolve_chunk_seconds(
            override=123, engine_kind="whisper", platform="granicus"
        )
        == 123
    )


def test_resolve_chunk_seconds_gemini_default_ignores_platform():
    """Gemini's small default is about the free-tier tokens/minute budget,
    not Granicus's CDN-timeout risk -- it must stay flat across platforms,
    including Granicus, rather than going through
    chunk_size_seconds_for_platform()."""
    assert (
        tbl._resolve_chunk_seconds(
            override=None, engine_kind="gemini", platform="granicus"
        )
        == tbl.GEMINI_DEFAULT_CHUNK_SECONDS
        == 180
    )


def test_resolve_chunk_seconds_explicit_override_wins_for_gemini_too():
    assert (
        tbl._resolve_chunk_seconds(
            override=42, engine_kind="gemini", platform="granicus"
        )
        == 42
    )


async def test_process_one_picks_the_granicus_chunk_size_per_page(local_media):
    """End-to-end through process_one(): a real Granicus URL (Tacoma WA,
    from CLAUDE.md's own sample list), no --chunk-seconds passed, must
    reach transcribe_meeting() with chunk_size_seconds=300 -- the actual
    fix, not just the helper function in isolation. Captures the call
    instead of letting a real chunked transcription run."""
    captured = {}

    async def _fake_transcribe_meeting(engine, source_url, platform, **kwargs):
        captured["platform"] = platform
        captured["chunk_size_seconds"] = kwargs.get("chunk_size_seconds")
        return {"ok": False, "reason": "captured before any real work"}

    local_media.setattr(tbl, "transcribe_meeting", _fake_transcribe_meeting)

    page = {
        "slug": "tacoma-wa-council",
        "platform": "granicus",
        "source_url_normalized": _REAL_GRANICUS_URL,
        "video_url": None,
        "video_format": None,
    }
    result = await tbl.process_one(
        None, _FakeEngine(), page, dry_run=True, chunk_seconds_override=None
    )
    assert captured["platform"] == "granicus"
    assert captured["chunk_size_seconds"] == 300
    assert result["status"] == "skipped"


async def test_process_one_override_beats_the_granicus_default(local_media):
    """--chunk-seconds must still win over the new per-platform default,
    even on the one platform where that default is no longer 900."""
    captured = {}

    async def _fake_transcribe_meeting(engine, source_url, platform, **kwargs):
        captured["chunk_size_seconds"] = kwargs.get("chunk_size_seconds")
        return {"ok": False, "reason": "captured before any real work"}

    local_media.setattr(tbl, "transcribe_meeting", _fake_transcribe_meeting)

    page = {
        "slug": "tacoma-wa-council",
        "platform": "granicus",
        "source_url_normalized": _REAL_GRANICUS_URL,
        "video_url": None,
        "video_format": None,
    }
    await tbl.process_one(
        None, _FakeEngine(), page, dry_run=True, chunk_seconds_override=77
    )
    assert captured["chunk_size_seconds"] == 77


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


# --- WO-82 (2026-08-30, see BACKLOG.md): the two gaps found recovering a
# real stuck local-transcription payload --------------------------------
#
# chino-valley-az-2026-02-10-town-council-meeting finished a full local
# Whisper transcription but /internal/ingest 500'd on every retry, so the
# finished payload was written to local_transcription_backups/. Recovering
# it manually surfaced two real, small gaps: (1) the payload
# _save_local_backup() wrote was missing input_url_normalized/source
# (added only to _ingest()'s own local copy at the time), so the
# docstring's plain `curl -X POST ... -d @<path>` recovery command 422'd
# against a real saved file; (2) nothing surfaced that the file was
# sitting there at all -- it sat unrecovered for 2 real days.


async def test_process_one_backup_on_ingest_failure_is_actually_recoverable(
    local_media, counting_server, tmp_path
):
    """Gap 1. Confirms the JSON _save_local_backup() writes when
    /internal/ingest fails is the *complete* POST body -- including
    input_url_normalized and source -- not the pre-those-fields payload
    _ingest() used to build internally. That's the difference between the
    documented recovery curl command actually working and 422ing, which is
    exactly what happened recovering the real chino-valley-az backup."""
    counting_server.statuses = [500] * 10  # exhaust every retry attempt
    local_media.setattr(
        tbl, "_base_url", lambda: f"http://127.0.0.1:{counting_server.port}"
    )
    local_media.setattr(tbl, "_headers", lambda: {})
    local_media.setattr(tbl, "FAILED_INGEST_DIR", tmp_path / "backups")
    local_media.setattr(tbl, "get_finder", lambda platform: _AlwaysResolves())

    async def _extract(*args, **kwargs):
        return True, None

    local_media.setattr(tbl, "extract_chunk_audio", _extract)

    page = {
        "slug": "chino-valley-az-2026-02-10-town-council-meeting",
        "platform": "civicclerk",
        "source_url_normalized": "https://chinovalleyaz.portal.civicclerk.com/event/6568/media",
        "video_url": None,
        "video_format": None,
    }

    async with aiohttp.ClientSession() as session:
        with pytest.raises(RuntimeError, match="saved locally"):
            await tbl.process_one(
                session,
                _FakeEngine(),
                page,
                dry_run=False,
                chunk_seconds_override=900,
            )

    backups = list((tmp_path / "backups").glob("*.json"))
    assert len(backups) == 1
    saved = json.loads(backups[0].read_text())
    # The two fields that were missing before WO-82's fix -- their presence
    # is what makes `curl -X POST ... -d @<path>` recoverable as documented,
    # instead of 422ing on a request FastAPI's IngestRequest model would
    # reject as incomplete.
    assert saved["input_url_normalized"] == page["source_url_normalized"]
    assert saved["source"] == "transcribed"
    # And it's still the real transcription content, not a stub.
    assert saved["segments"]
    assert saved["platform"] == "escribe"  # from _resolved()'s ResolvedMeeting


def test_warn_about_stale_backups_flags_old_files(tmp_path, monkeypatch, caplog):
    """Gap 2. A backup file older than STALE_BACKUP_THRESHOLD_SECONDS must
    be named in a clear warning at startup -- the real chino-valley-az
    backup sat unrecovered for 2 days precisely because nothing surfaced
    it, and someone happened to go looking."""
    import os
    import time

    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    old_file = backups_dir / "20260825_091547_chino-valley-az-town-council.json"
    old_file.write_text("{}")
    old_mtime = time.time() - 3 * 24 * 60 * 60  # 3 days old
    os.utime(old_file, (old_mtime, old_mtime))

    monkeypatch.setattr(tbl, "FAILED_INGEST_DIR", backups_dir)
    with caplog.at_level("WARNING", logger="rtr_transcribe_backlog"):
        tbl._warn_about_stale_backups()

    assert any(
        "chino-valley-az-town-council" in record.message for record in caplog.records
    )
    assert any("1 finished-but-unpushed" in record.message for record in caplog.records)


def test_warn_about_stale_backups_silent_when_none_are_old(
    tmp_path, monkeypatch, caplog
):
    """A backup written moments ago (the normal, just-happened-once case)
    must not spam a warning on every run -- only ones that have genuinely
    sat past the threshold."""
    backups_dir = tmp_path / "backups"
    backups_dir.mkdir()
    (backups_dir / "20260830_100000_some-meeting.json").write_text("{}")

    monkeypatch.setattr(tbl, "FAILED_INGEST_DIR", backups_dir)
    with caplog.at_level("WARNING", logger="rtr_transcribe_backlog"):
        tbl._warn_about_stale_backups()
    assert caplog.records == []


def test_warn_about_stale_backups_handles_a_missing_directory(
    tmp_path, monkeypatch, caplog
):
    """The common case -- this Mac has never had a failed ingest, so the
    directory doesn't exist at all -- must not raise."""
    monkeypatch.setattr(tbl, "FAILED_INGEST_DIR", tmp_path / "never-created")
    with caplog.at_level("WARNING", logger="rtr_transcribe_backlog"):
        tbl._warn_about_stale_backups()
    assert caplog.records == []
