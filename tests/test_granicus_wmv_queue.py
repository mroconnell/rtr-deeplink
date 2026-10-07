"""A Granicus feed's own video file (DownloadFile.php, a .wmv) in the tier 3
queue. Synthetic ASF header bytes only; no live requests."""

import struct
from pathlib import Path

import pytest

import scripts.feed_tier3_auto_transcription as feed_mod
from app.platforms import media_probe, queue_probe, register_all_finders
from app.platforms.base import detect_platform, get_finder
from app.platforms.queue_probe import parse_asf_duration, parse_queue_line

register_all_finders()

ENCLOSURE = "https://evansville.granicus.com/DownloadFile.php?view_id=1&clip_id=8744"
FEED_ITEM = "https://evansville.granicus.com/ViewPublisherRSS.php?view_id=1&mode=vod"

ASF_HEADER_GUID = bytes.fromhex("3026b2758e66cf11a6d900aa0062ce6c")
FILE_PROPS_GUID = bytes.fromhex("a1dcab8c47a9cf118ee400c00c205365")
OTHER_GUID = bytes.fromhex("b503bf5f2ea9cf118ee300c00c205365")


def asf_header(seconds: float, preroll_ms: int = 3000) -> bytes:
    """Synthetic ASF header: one unrelated object, then File Properties."""
    play = int((seconds + preroll_ms / 1000) * 10_000_000)
    other = OTHER_GUID + struct.pack("<Q", 24 + 10) + b"\x00" * 10
    body = (
        b"\x00" * 16  # file id
        + struct.pack("<Q", 123456789)  # file size
        + struct.pack("<Q", 0)  # creation date
        + struct.pack("<Q", 100)  # data packets
        + struct.pack("<Q", play)  # play duration (100 ns)
        + struct.pack("<Q", play)  # send duration
        + struct.pack("<Q", preroll_ms)  # preroll (ms)
        + struct.pack("<I", 2)  # flags
        + struct.pack("<II", 3200, 3200)  # packet sizes
        + struct.pack("<I", 0)  # max bitrate
    )
    props = FILE_PROPS_GUID + struct.pack("<Q", 24 + len(body)) + body
    objects = other + props
    header = ASF_HEADER_GUID + struct.pack("<QIBB", 30 + len(objects), 2, 1, 2)
    return header + objects + b"\x00" * 500


# --- detect_platform --------------------------------------------------------


def test_downloadfile_is_a_direct_file_not_a_granicus_page():
    assert detect_platform(ENCLOSURE) == "direct_file"
    assert detect_platform("https://x.granicus.com/downloadfile.php?clip_id=1") == (
        "direct_file"
    )


def test_wmv_and_asf_extensions_are_direct_files():
    assert detect_platform("https://example.gov/video/council.wmv") == "direct_file"
    assert detect_platform("https://example.gov/video/council.ASF") == "direct_file"


def test_other_granicus_urls_are_unchanged():
    for url in (
        "https://evansville.granicus.com/MediaPlayer.php?view_id=1&clip_id=8744",
        "https://evansville.granicus.com/player/clip/8744?view_id=1",
        "https://evansville.granicus.com/ViewPublisher.php?view_id=1",
        "https://evansville.granicus.com/other/DownloadFile.php?clip_id=1",
    ):
        assert detect_platform(url) == "granicus"


async def test_resolving_the_enclosure_makes_no_request(monkeypatch):
    import aiohttp

    def boom(*a, **k):
        raise AssertionError("resolve must not touch the network")

    monkeypatch.setattr(aiohttp, "ClientSession", boom)
    finder = get_finder(detect_platform(ENCLOSURE))
    result = await finder.resolve(ENCLOSURE)
    assert result.video_url == ENCLOSURE
    assert result.video_format == "wmv"


# --- queue line --------------------------------------------------------------


def test_queue_line_keeps_the_feed_link_as_source_url():
    line = f"{ENCLOSURE}\t{FEED_ITEM}\tgov-123"
    assert parse_queue_line(line) == (ENCLOSURE, FEED_ITEM, "gov-123")


# --- ASF duration parse --------------------------------------------------------


def test_parse_asf_duration_subtracts_preroll():
    assert parse_asf_duration(asf_header(3600.0)) == pytest.approx(3600.0)


def test_parse_asf_duration_rejects_non_asf_and_truncated():
    assert parse_asf_duration(b"<html>not asf</html>" * 10) is None
    assert parse_asf_duration(asf_header(3600.0)[:80]) is None
    assert parse_asf_duration(b"") is None


# --- the probe (fake HTTP session) -------------------------------------------


class _Content:
    def __init__(self, data):
        self._data = data

    async def read(self, n):
        out, self._data = self._data[:n], self._data[n:]
        return out


class _Response:
    def __init__(self, status, headers, data):
        self.status = status
        self.headers = headers
        self.content = _Content(data)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


def _fake_session_class(response, seen):
    class _Session:
        def __init__(self, *a, **k):
            seen["session_headers"] = k.get("headers")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        def get(self, url, **k):
            seen["url"] = url
            seen["request_headers"] = k.get("headers")
            seen["timeout"] = k.get("timeout")
            return response

    return _Session


async def test_probe_reads_only_the_first_256kb_header(monkeypatch):
    seen = {}
    # A server that ignores Range and would send 10 MB: only 256 KB is read.
    big = asf_header(5400.0) + b"\x01" * (10 * 1024 * 1024)
    resp = _Response(
        200,
        {
            "Content-Length": str(len(big)),
            "Last-Modified": "Tue, 06 Oct 2026 12:00:00 GMT",
        },
        big,
    )
    monkeypatch.setattr(
        queue_probe.aiohttp, "ClientSession", _fake_session_class(resp, seen)
    )
    result = await queue_probe.probe_queue_entry(
        FEED_ITEM,
        video_url=ENCLOSURE,
        source_page_url=FEED_ITEM,
        platform="direct_file",
        video_format="wmv",
    )
    assert result.verdict == "accept"
    assert result.duration_seconds == pytest.approx(5400.0)
    assert result.probe_method == "range-asf-header"
    assert result.size_bytes == len(big)
    assert result.date == "2026-10-06"
    assert seen["url"] == ENCLOSURE
    assert seen["request_headers"]["Range"] == "bytes=0-262143"
    assert seen["session_headers"]["User-Agent"] == (
        "Mozilla/5.0 (compatible; civic-research-bot)"
    )
    assert "Referer" not in seen["session_headers"]
    assert seen["timeout"].total is not None
    # Only the 256 KB header was pulled off the stream.
    assert len(resp.content._data) == len(big) - 256 * 1024


async def test_probe_dead_link_and_non_asf_body(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        queue_probe.aiohttp,
        "ClientSession",
        _fake_session_class(_Response(404, {}, b""), seen),
    )
    dead = await queue_probe.probe_queue_entry(
        FEED_ITEM, video_url=ENCLOSURE, platform="direct_file", video_format="wmv"
    )
    assert dead.verdict == "reject-dead" and "404" in dead.reason

    async def no_ffprobe(data):
        return None

    monkeypatch.setattr(queue_probe, "_ffprobe_partial_file", no_ffprobe)
    monkeypatch.setattr(
        queue_probe.aiohttp,
        "ClientSession",
        _fake_session_class(_Response(200, {}, b"<html>sign in</html>"), seen),
    )
    html = await queue_probe.probe_queue_entry(
        FEED_ITEM, video_url=ENCLOSURE, platform="direct_file", video_format="wmv"
    )
    assert html.verdict == "reject-dead"


# --- consumer path ---------------------------------------------------------------


async def test_consumer_uses_the_enclosure_and_never_fetches_source_url(monkeypatch):
    import aiohttp

    fetched = []
    seen_probe = {}

    def boom(*a, **k):
        raise AssertionError("no HTTP session may be opened in this path")

    monkeypatch.setattr(aiohttp, "ClientSession", boom)

    async def fake_probe(url, **kwargs):
        seen_probe.update(kwargs)
        fetched.append(kwargs.get("video_url"))
        return queue_probe._finish(
            url, kwargs.get("platform"), "range-asf-header", 3600.0, None, None, 0.0
        )

    captured = {}

    async def fake_ingest(
        session, payload, normalized, *, already_probed=False, caller=""
    ):
        captured["payload"] = payload
        return {"url": "/m/x"}

    monkeypatch.setattr(feed_mod, "probe_queue_entry", fake_probe)
    monkeypatch.setattr(feed_mod, "append_probe_row", lambda *a, **k: None)
    monkeypatch.setattr(feed_mod, "_ingest", fake_ingest)
    monkeypatch.setattr(feed_mod, "_append_feed_log_row", lambda *a, **k: None)

    outcome = await feed_mod._push_if_has_video(None, ENCLOSURE, FEED_ITEM, "gov-123")
    assert "[OK]" in outcome, outcome
    assert fetched == [ENCLOSURE]
    assert seen_probe["platform"] == "direct_file"
    assert captured["payload"]["video_url"] == ENCLOSURE
    assert captured["payload"]["source_url"] == FEED_ITEM
    assert captured["payload"]["gov_id"] == "gov-123"


# --- worker media path -------------------------------------------------------------


async def test_worker_extraction_hands_a_wmv_url_to_ffmpeg_unchanged(
    monkeypatch, tmp_path
):
    calls = []

    async def fake_run(*args, timeout=None):
        calls.append(args)
        Path(args[-1]).write_bytes(b"x" * 2048)
        return 0, b"", b""

    monkeypatch.setattr(media_probe, "_run", fake_run)
    out = tmp_path / "chunk_0.mp3"
    await media_probe.extract_chunk_audio(
        ENCLOSURE,
        start=0,
        duration=60,
        source_page_url=FEED_ITEM,
        out_path=out,
        is_final_chunk=False,
    )
    assert calls, "ffmpeg was never called"
    first = next(c for c in calls if c[0] == "ffmpeg")
    assert ENCLOSURE in first
    assert "-vn" in first and "libmp3lame" in first
