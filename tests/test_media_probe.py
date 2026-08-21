import shutil

import pytest

from app.platforms import media_probe
from app.platforms.media_probe import (
    _mean_volume_db,
    extract_chunk_audio,
    is_plausible_meeting_duration,
)


def test_plausible_duration_bounds():
    assert not is_plausible_meeting_duration(60)  # 1 min, too short
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
