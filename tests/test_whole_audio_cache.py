"""Pulling a whole meeting's audio once, for sources where seeking costs.

**The measurement this exists for.** ChampDS serves one progressive MP4
and charges for every seek: on two independent customers (oakhilltn/50
and largofl/240, 2026-08-25) a ranged GET's cost is almost entirely
time-to-*first*-byte and grows linearly with the offset at ~0.199 s/MB --
the server scans the file internally at ~5 MB/s before answering, while
actual transfer runs at ~4 MB/s. So per-chunk seeking is O(N^2) across a
job. Measured in the workers' own base image on oakhilltn/50 (502 MB,
6733s, 8 chunks), even the output-side path WO-53 falls back to took 138s
for chunk 1 and 162s for chunk 3 -- both over the 120s budget, climbing.

Reading the file start-to-finish once pays no scan at all, so the whole
meeting's audio is pulled once and every chunk becomes a local slice.

The two things worth guarding are the *gate* and the *degradation*:
choosing this path for HLS would download an entire video stream to save
nothing, and the cache must never be load-bearing for correctness -- two
workers can claim different chunks of the same job, so a missing cache
has to be an ordinary "download it then" and not a failure.
"""

from pathlib import Path

import pytest

import worker.main as worker_main
from app.platforms import media_probe
from app.platforms.media_probe import is_hls


# --- the gate ------------------------------------------------------------


@pytest.mark.parametrize(
    "url,expected",
    [
        # Real shapes, from the adapters that produce them.
        ("https://play.champds.com/DOWNLOAD-MEDIA/oakhilltn/eventmainmedia/50", False),
        ("https://cerritos.cablecast.tv/vod/372-x-v2/vod.m3u8", True),
        ("https://example.granicus.com/OnDemand/x/y.m3u8?token=abc", True),
        ("https://example.com/meeting.mp4", False),
        ("https://example.com/audio.m3u", True),
    ],
)
def test_is_hls_recognises_real_media_url_shapes(url, expected):
    assert is_hls(url) is expected


def test_hls_never_takes_the_whole_audio_path():
    """The expensive mistake in the other direction. ffmpeg fetches only
    the segments covering a chunk's window off a playlist, so per-chunk
    is already minimal for HLS -- pre-fetching everything would pull the
    entire video stream to save nothing."""
    assert (
        worker_main._should_cache_whole_audio(
            "https://cerritos.cablecast.tv/vod/372-x-v2/vod.m3u8", 22
        )
        is False
    )


def test_single_chunk_jobs_skip_the_cache():
    """With one chunk the whole-file read and the chunk read are the same
    read, so there is nothing to amortise."""
    assert (
        worker_main._should_cache_whole_audio(
            "https://play.champds.com/DOWNLOAD-MEDIA/oakhilltn/eventmainmedia/50", 1
        )
        is False
    )


def test_multi_chunk_progressive_source_uses_the_cache():
    assert (
        worker_main._should_cache_whole_audio(
            "https://play.champds.com/DOWNLOAD-MEDIA/oakhilltn/eventmainmedia/50", 8
        )
        is True
    )


# --- the cache itself ----------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(worker_main, "_AUDIO_CACHE_ROOT", tmp_path / "cache")


async def test_first_chunk_downloads_once_and_later_chunks_do_not(
    tmp_path, monkeypatch
):
    """The whole point: one download per job, then local slices."""
    downloads: list[str] = []
    slices: list[float] = []

    async def _fake_full(media_url, *, source_page_url, out_path):
        downloads.append(media_url)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"\xff\xfb" + b"\x00" * 5000)
        return True, None

    async def _fake_slice(cached_path, *, start, duration, out_path):
        assert cached_path.exists(), "sliced from a cache that isn't there"
        slices.append(start)
        out_path.write_bytes(b"\xff\xfb" + b"\x00" * 400)
        return True, None

    monkeypatch.setattr(worker_main, "extract_full_audio", _fake_full)
    monkeypatch.setattr(worker_main, "slice_cached_audio", _fake_slice)

    for index in range(4):
        ok, reason = await worker_main._chunk_audio_via_cache(
            job_id=4242,
            media_url="https://play.champds.com/DOWNLOAD-MEDIA/x/eventmainmedia/1",
            source_url="https://play.champds.com/x/event/1",
            start=index * 900.0,
            duration=900.0,
            out_path=tmp_path / f"chunk_{index}.mp3",
        )
        assert (ok, reason) == (True, None)

    assert len(downloads) == 1, "the meeting was downloaded more than once"
    assert slices == [0.0, 900.0, 1800.0, 2700.0]


async def test_a_failed_download_leaves_no_half_written_cache(tmp_path, monkeypatch):
    """A truncated file left behind would be silently mistaken for a good
    cache by the next chunk, which is far worse than downloading again --
    it would transcribe whatever partial audio happened to land."""

    async def _fake_full(media_url, *, source_page_url, out_path):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"partial garbage")  # what a timeout leaves
        return False, "full-audio download timed out after 180s"

    async def _fail_if_called(*a, **k):
        raise AssertionError("sliced from a cache that was never valid")

    monkeypatch.setattr(worker_main, "extract_full_audio", _fake_full)
    monkeypatch.setattr(worker_main, "slice_cached_audio", _fail_if_called)

    ok, reason = await worker_main._chunk_audio_via_cache(
        job_id=99,
        media_url="https://play.champds.com/DOWNLOAD-MEDIA/x/eventmainmedia/1",
        source_url="https://play.champds.com/x/event/1",
        start=900.0,
        duration=900.0,
        out_path=tmp_path / "chunk_1.mp3",
    )

    assert ok is False
    assert reason and "timed out" in reason
    assert not worker_main._job_audio_cache_path(99).exists()


def test_clearing_is_safe_when_there_is_no_cache():
    """Called on every terminal outcome, including jobs that never used
    the cache path at all."""
    worker_main._clear_job_audio_cache(31337)  # must not raise


def test_startup_sweep_removes_orphans_from_a_crashed_run():
    path = worker_main._job_audio_cache_path(7)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"orphan")
    worker_main._reset_audio_cache_root()
    assert not path.exists()
    assert worker_main._AUDIO_CACHE_ROOT.exists()


# --- the ffmpeg argv -----------------------------------------------------


async def test_full_audio_uses_its_own_longer_budget(monkeypatch, tmp_path):
    """One sequential read of a whole meeting cannot fit the per-chunk
    budget -- 502 MB at the measured ~4 MB/s is ~125s against a 120s
    limit. It gets its own constant rather than raising that one
    (BACKLOG.md has a standing decision against raising it)."""
    seen = {}

    async def _run(*args, timeout=None):
        seen["args"] = list(args)
        seen["timeout"] = timeout
        Path(args[-1]).write_bytes(b"\xff\xfb" + b"\x00" * 100)
        return 0, b"", b""

    monkeypatch.setattr(media_probe, "_run", _run)

    ok, reason = await media_probe.extract_full_audio(
        "https://play.champds.com/DOWNLOAD-MEDIA/x/eventmainmedia/1",
        source_page_url="https://play.champds.com/x/event/1",
        out_path=tmp_path / "full.mp3",
    )

    assert (ok, reason) == (True, None)
    assert seen["timeout"] == media_probe._FULL_AUDIO_TIMEOUT_SECONDS
    assert seen["timeout"] > media_probe._SUBPROCESS_TIMEOUT_SECONDS
    # No -ss anywhere: not seeking is the entire point.
    assert "-ss" not in seen["args"]


async def test_slicing_never_re_encodes(monkeypatch, tmp_path):
    """The cached file is already mono 16 kHz 32 kbps mp3, so a chunk is a
    copy, not a transcode -- and it reads local disk, so input-side -ss is
    both correct and free here."""
    seen = {}

    async def _run(*args, timeout=None):
        seen["args"] = list(args)
        Path(args[-1]).write_bytes(b"\xff\xfb" + b"\x00" * 100)
        return 0, b"", b""

    monkeypatch.setattr(media_probe, "_run", _run)
    cached = tmp_path / "full.mp3"
    cached.write_bytes(b"\xff\xfb" + b"\x00" * 5000)

    ok, _ = await media_probe.slice_cached_audio(
        cached, start=900.0, duration=900.0, out_path=tmp_path / "chunk_1.mp3"
    )

    assert ok is True
    args = seen["args"]
    assert "copy" in args
    assert args.index("-ss") < args.index("-i")
