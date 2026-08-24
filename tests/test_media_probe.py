import shutil

import pytest

from app.platforms import media_probe
from app.platforms.media_probe import (
    _mean_volume_db,
    extract_chunk_audio,
    is_plausible_meeting_duration,
)


# --- _stderr_tail(): the version banner must not crowd out the error -----
#
# Real, live-captured stderr (2026-08-22): the exact extraction command
# extract_chunk_audio() runs, pointed at a real 404 on cpmedia.azureedge.net
# -- the same CDN host as the Brookhaven NY failures in BACKLOG.md -- under
# real ffmpeg 8.1.2. 1,101 bytes total, of which the first ~630 are the
# version banner, which is how a chunk failure came to be reported as
# `ffmpeg exited 196: ibavformat 62.12.102 / 62.12.102`: a `[-500:]` tail
# landed mid-word inside the banner's libavformat line. Only the addresses
# in the ffmpeg log prefixes are shortened here, for line width; nothing
# else is edited.
_REAL_BANNER_HEAVY_STDERR = b"""ffmpeg version 8.1.2 Copyright (c) 2000-2026 the FFmpeg developers
  built with Apple clang version 21.0.0 (clang-2100.0.123.102)
  configuration: --prefix=/opt/homebrew/Cellar/ffmpeg/8.1.2_1 --enable-shared --enable-pthreads --enable-gpl --enable-libmp3lame --enable-openssl
  libavutil      60. 26.102 / 60. 26.102
  libavcodec     62. 28.102 / 62. 28.102
  libavformat    62. 12.102 / 62. 12.102
  libavdevice    62.  3.102 / 62.  3.102
  libavfilter    11. 14.102 / 11. 14.102
  libswscale      9.  5.102 /  9.  5.102
  libswresample   6.  3.102 /  6.  3.102
[https @ 0x953003520] HTTP error 404 The specified resource does not exist.
[in#0 @ 0x952c20000] Error opening input: Server returned 404 Not Found
Error opening input file https://cpmedia.azureedge.net/nonexistent-thing.mp4.
Error opening input files: Server returned 404 Not Found
"""


def test_stderr_tail_drops_the_version_banner_and_keeps_the_real_error():
    tail = media_probe._stderr_tail(_REAL_BANNER_HEAVY_STDERR, 500)
    assert tail.startswith("[https @ ")
    assert "HTTP error 404" in tail
    assert tail.endswith("Error opening input files: Server returned 404 Not Found")
    # The whole point: no banner line survives, so none of the 500-character
    # budget is spent on one -- and the reported error can't begin mid-word
    # inside `libavformat` the way the real pub-3ce failure's did.
    assert "libavformat" not in tail
    assert "ffmpeg version" not in tail
    assert "configuration:" not in tail


def test_stderr_tail_still_truncates_from_the_end():
    """ffmpeg's real diagnosis is its *last* lines, so a genuinely long
    stderr must keep the end, not the beginning."""
    long_stderr = ("\n".join(f"line {i}" for i in range(500))).encode()
    tail = media_probe._stderr_tail(long_stderr, 40)
    assert len(tail) <= 40
    assert tail.endswith("line 499")


def test_plausible_duration_bounds():
    # WO-46 (2026-08-23): the floor moved 300s -> 60s off real measured
    # meetings Ryan confirmed were being skipped -- see
    # MIN_PLAUSIBLE_MEETING_SECONDS' own comment for the full table.
    assert not is_plausible_meeting_duration(50)  # a real gnat.cablecast ad
    assert not is_plausible_meeting_duration(39)  # a real Santee community event
    assert is_plausible_meeting_duration(86)  # a real Butte cemetery district mtg
    assert is_plausible_meeting_duration(265)  # a real Bluffton IN meeting
    assert is_plausible_meeting_duration(30 * 60)  # 30 min, plausible
    assert is_plausible_meeting_duration(4 * 3600)  # 4 hours, plausible
    assert not is_plausible_meeting_duration(20 * 3600)  # 20 hours, implausible


# --- extract_chunk_audio()'s undecodable-output guard (WO-25, 2026-08-21) ---
#
# SYNTHETIC in that the ffmpeg subprocess is faked rather than run against a
# real government media URL -- but the *branch* is confirmed against a real
# production occurrence, not hypothesized: Sentry PYTHON-FASTAPI-R,
# 2026-08-19 15:57:32 UTC on the transcription worker, `InvalidDataError:
# [Errno 1094995529] Invalid data found when processing input:
# '/tmp/rtr_transcribe_hwou97hq/chunk_1.mp3'`, alongside the app log
# "Job 287: transcription failed for chunk 2/21 (will retry on next poll)".
# ffmpeg exited 0 and wrote a non-empty file; faster-whisper's PyAV open of
# that same file then raised. The real facts baked in below are likewise
# observed, not invented (verified with real ffmpeg 2026-08-21, see
# test_mean_volume_db_matches_real_ffmpeg for the live half):
#   * exit 183 is what real ffmpeg returns for an undecodable input -- the
#     low byte of AVERROR_INVALIDDATA, the same error code PyAV surfaces as
#     errno 1094995529 in the Sentry event above;
#   * the stderr lines are real ffmpeg output, verbatim in shape;
#   * -21.5 dB is the real mean_volume of a real 3s 16kHz mono 32kbps mp3.
# What is still unconfirmed: *why* the production chunk was corrupt (an
# interrupted read from the source stream is the leading theory, per the
# BACKLOG_DONE.md entry) and whether job 287's own retry then succeeded --
# neither of which this guard depends on.

_REAL_UNDECODABLE_STDERR = (
    b"[in#0 @ 0xaa4c1c000] Error opening input: Invalid data found when "
    b"processing input\nError opening input file /tmp/rtr_transcribe_x/"
    b"chunk_1.mp3.\nError opening input files: Invalid data found when "
    b"processing input\n"
)
_REAL_VOLUMEDETECT_STDERR = (
    b"[Parsed_volumedetect_0 @ 0xc9e800e40] mean_volume: -21.5 dB\n"
    b"[Parsed_volumedetect_0 @ 0xc9e800e40] max_volume: -3.0 dB\n"
)


def _fake_run(out_path, *, volumedetect_result, extraction_bytes):
    """Stand in for media_probe._run(): the extraction call reports success
    and writes `extraction_bytes` to out_path (exactly the production
    situation -- exit 0, non-empty file), and the volumedetect call returns
    whatever verdict the test is exercising."""

    async def _run(*args):
        if "volumedetect" in args:
            return volumedetect_result
        out_path.write_bytes(extraction_bytes)
        return 0, b"", b""

    return _run


async def test_extract_chunk_audio_rejects_undecodable_output(tmp_path, monkeypatch):
    out_path = tmp_path / "chunk_1.mp3"
    monkeypatch.setattr(
        media_probe,
        "_run",
        _fake_run(
            out_path,
            volumedetect_result=(183, b"", _REAL_UNDECODABLE_STDERR),
            extraction_bytes=b"ID3\x04\x00\x00\x00\x00\x00\x00" + b"\x9f" * 400,
        ),
    )

    ok, reason = await extract_chunk_audio(
        "https://example.org/meeting.m3u8",
        start=900.0,
        duration=900.0,
        source_page_url="https://example.org/meeting",
        out_path=out_path,
    )

    # The file is present and non-empty -- the pre-existing size check passes,
    # which is exactly why the production occurrence got through to whisper.
    assert out_path.exists() and out_path.stat().st_size > 0
    assert ok is False
    assert reason and "decodable" in reason


async def test_extract_chunk_audio_accepts_decodable_output(tmp_path, monkeypatch):
    """Positive control: a chunk ffmpeg *can* decode must still succeed --
    the guard above must not start failing every healthy chunk."""
    out_path = tmp_path / "chunk_0.mp3"
    monkeypatch.setattr(
        media_probe,
        "_run",
        _fake_run(
            out_path,
            volumedetect_result=(0, b"", _REAL_VOLUMEDETECT_STDERR),
            extraction_bytes=b"\xff\xfb" + b"\x00" * 4000,
        ),
    )

    assert await extract_chunk_audio(
        "https://example.org/meeting.m3u8",
        start=0.0,
        duration=900.0,
        source_page_url="https://example.org/meeting",
        out_path=out_path,
    ) == (True, None)


async def test_mean_volume_db_treats_missing_ffmpeg_as_unknown(tmp_path, monkeypatch):
    """A broken *environment* must not be reported as a corrupt *file* --
    otherwise an ffmpeg missing from PATH would burn a job's chunk-failure
    budget blaming the source media."""

    async def _run(*args):
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(media_probe, "_run", _run)
    assert await _mean_volume_db(tmp_path / "chunk_0.mp3") == (True, None)


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed on this machine"
)
async def test_mean_volume_db_matches_real_ffmpeg(tmp_path):
    """The live half of the pair above: no mocking at all, real ffmpeg
    against a real mp3 and a real truncation of it. This is what pins the
    synthetic constants used in the mocked tests to actual behavior. Skipped
    where ffmpeg is absent (it is installed on the worker, which is where
    this code runs) -- the mocked tests carry the branch coverage there."""
    good = tmp_path / "good.mp3"
    returncode, _stdout, _stderr = await media_probe._run(
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=3",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "32k",
        str(good),
    )
    assert returncode == 0

    decodable, mean_volume = await _mean_volume_db(good)
    assert decodable is True
    assert mean_volume is not None and -40 < mean_volume < 0

    # Truncated hard enough that ffmpeg can't establish a stream at all --
    # the shape of the Sentry occurrence. (A *tail* truncation still decodes
    # fine, and PyAV opens those too, so this guard deliberately doesn't
    # claim to catch short-but-valid output; see extract_chunk_audio's
    # docstring.)
    truncated = tmp_path / "truncated.mp3"
    truncated.write_bytes(good.read_bytes()[:200])
    assert await _mean_volume_db(truncated) == (False, None)


# --- WO-45: the output-side-seek fallback (2026-08-23) ----------------------
#
# SYNTHETIC in the same sense as the WO-25 tests above -- ffmpeg is faked --
# but the branch is confirmed against a real production cluster, not
# hypothesized. On 2026-08-23, 33+ transcription jobs died at chunk 1 with
# "ffmpeg reported success but the output file isn't decodable", every one of
# them a Cablecast tenant serving a separate fMP4 audio rendition. Reproduced
# by hand against job 692's real media
# (portagemi.cablecast.tv/internetchannel/show/304) inside the worker's own
# base image: under ffmpeg 7.1.5 an input-side `-ss 900` writes a 224-byte
# undecodable file and exits 0, while moving `-ss` after `-i` writes a valid
# 3,600,512-byte chunk. See _extract_chunk_once()'s block comment for the
# full version matrix and the alternatives that were tested and rejected.


def _seek_is_input_side(args) -> bool:
    """True when `-ss` precedes `-i` in an ffmpeg argv -- the fast,
    input-side seek. This is the whole difference between the two attempts,
    so the tests assert on it directly rather than on call ordering alone."""
    args = list(args)
    return args.index("-ss") < args.index("-i")


def _fake_run_recording(out_path, *, attempts):
    """Stand in for media_probe._run() across MULTIPLE extraction attempts.

    `attempts` is a list of (extraction_bytes, volumedetect_result) consumed
    in order, one per extraction call; every extraction reports exit 0 with a
    non-empty file, which is exactly the shape of the real bug. The returned
    `calls` list records each extraction's argv so a test can assert which
    seek form was used.
    """
    calls: list[list] = []
    state = {"i": 0}
    pending_volumedetect = {"result": None}

    async def _run(*args):
        if "volumedetect" in args:
            return pending_volumedetect["result"]
        calls.append(list(args))
        extraction_bytes, volumedetect_result = attempts[state["i"]]
        state["i"] += 1
        pending_volumedetect["result"] = volumedetect_result
        out_path.write_bytes(extraction_bytes)
        return 0, b"", b""

    return _run, calls


async def test_extract_chunk_audio_recovers_via_output_side_seek(tmp_path, monkeypatch):
    """The production case: input-side seek returns an undecodable file, the
    output-side retry returns a good one, and the chunk succeeds."""
    out_path = tmp_path / "chunk_1.mp3"
    _run, calls = _fake_run_recording(
        out_path,
        attempts=[
            # Attempt 1 -- the 224-byte exit-0 file the real bug produces.
            (b"\xff\xfb" + b"\x00" * 222, (183, b"", _REAL_UNDECODABLE_STDERR)),
            # Attempt 2 -- output-side seek, a real decodable chunk.
            (b"\xff\xfb" + b"\x00" * 4000, (0, b"", _REAL_VOLUMEDETECT_STDERR)),
        ],
    )
    monkeypatch.setattr(media_probe, "_run", _run)

    assert await extract_chunk_audio(
        "https://portagemi.cablecast.tv/store-3/304-x-v2/vod.m3u8",
        start=900.0,
        duration=900.0,
        source_page_url="http://portagemi.cablecast.tv/internetchannel/show/304",
        out_path=out_path,
    ) == (True, None)

    assert len(calls) == 2
    assert _seek_is_input_side(calls[0]) is True
    assert _seek_is_input_side(calls[1]) is False
    # The retry must still ask for the same window, not a different one.
    assert "900.0" in calls[1]


async def test_extract_chunk_audio_does_not_retry_the_first_chunk(
    tmp_path, monkeypatch
):
    """At start=0 there is no seek to get wrong, so the fallback would just
    be a slower rerun of the identical command. One attempt, then fail."""
    out_path = tmp_path / "chunk_0.mp3"
    _run, calls = _fake_run_recording(
        out_path,
        attempts=[(b"\xff\xfb" + b"\x00" * 222, (183, b"", _REAL_UNDECODABLE_STDERR))],
    )
    monkeypatch.setattr(media_probe, "_run", _run)

    ok, reason = await extract_chunk_audio(
        "https://portagemi.cablecast.tv/store-3/304-x-v2/vod.m3u8",
        start=0.0,
        duration=900.0,
        source_page_url="http://portagemi.cablecast.tv/internetchannel/show/304",
        out_path=out_path,
    )

    assert (ok, len(calls)) == (False, 1)
    assert reason and "decodable" in reason


async def test_extract_chunk_audio_keeps_the_original_reason_when_fallback_fails(
    tmp_path, monkeypatch
):
    """A source that is genuinely broken (rather than merely unseekable by
    this ffmpeg) must still report what the NORMAL path saw. The retry
    failing too is a detail of the recovery attempt, not a better diagnosis
    -- and reporting the retry's reason instead would make every such
    failure look like whatever the fallback happened to hit."""
    out_path = tmp_path / "chunk_1.mp3"
    _run, calls = _fake_run_recording(
        out_path,
        attempts=[
            (b"\xff\xfb" + b"\x00" * 222, (183, b"", _REAL_UNDECODABLE_STDERR)),
            (b"\xff\xfb" + b"\x00" * 222, (183, b"", _REAL_UNDECODABLE_STDERR)),
        ],
    )
    monkeypatch.setattr(media_probe, "_run", _run)

    ok, reason = await extract_chunk_audio(
        "https://example.org/meeting.m3u8",
        start=1800.0,
        duration=900.0,
        source_page_url="https://example.org/meeting",
        out_path=out_path,
    )

    assert (ok, len(calls)) == (False, 2)
    assert reason and "decodable" in reason


async def test_extract_chunk_audio_does_not_retry_a_missing_ffmpeg(
    tmp_path, monkeypatch
):
    """A broken environment is not a seek problem -- retrying it differently
    can only waste a second subprocess spawn and blame the source media."""
    calls = []

    async def _run(*args):
        calls.append(list(args))
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(media_probe, "_run", _run)

    ok, reason = await extract_chunk_audio(
        "https://example.org/meeting.m3u8",
        start=900.0,
        duration=900.0,
        source_page_url="https://example.org/meeting",
        out_path=tmp_path / "chunk_1.mp3",
    )

    assert (ok, reason, len(calls)) == (False, "ffmpeg not found on PATH", 1)
