import shutil

import asyncio
import pytest

from app.platforms import media_probe
from app.platforms.media_probe import (
    _mean_volume_db,
    chunk_size_seconds_for_platform,
    extract_chunk_audio,
    is_plausible_meeting_duration,
    probe_has_video_stream,
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


async def test_input_side_timeout_still_gets_the_output_side_retry(
    tmp_path, monkeypatch
):
    """WO-53, and the bug this whole test file's fallback existed to fix
    but didn't reach: an input-side attempt that TIMES OUT is the same
    "this approach cannot work on this source" signal as an undecodable
    file, not a "we ran out of budget" signal.

    Real case (job 863, cerritos.cablecast.tv/show/372). Measured on the
    workers' own ffmpeg 7.1.5: input-side seek to 900s takes **1084s**
    because it pulls the entire 1080p stream just to discard it with
    `-vn`, so it always hits the 120s timeout -- while the output-side
    seek that the fallback would have run finishes the same chunk in
    ~13s. WO-45 classified a timeout as not-worth-retrying, so the
    working path was never tried and the job died at chunk 1 every time.
    """
    out_path = tmp_path / "chunk_1.mp3"
    calls: list[list] = []
    pending_volumedetect = {"result": None}

    async def _run(*args):
        if "volumedetect" in args:
            return pending_volumedetect["result"]
        calls.append(list(args))
        if _seek_is_input_side(args):
            raise asyncio.TimeoutError
        pending_volumedetect["result"] = (0, b"", _REAL_VOLUMEDETECT_STDERR)
        out_path.write_bytes(b"\xff\xfb" + b"\x00" * 4000)
        return 0, b"", b""

    monkeypatch.setattr(media_probe, "_run", _run)

    assert await extract_chunk_audio(
        "https://cerritos.cablecast.tv/vod/372-x-v2/vod.m3u8",
        start=900.0,
        duration=900.0,
        source_page_url="https://cerritos.cablecast.tv/show/372?site=1",
        out_path=out_path,
    ) == (True, None)

    assert len(calls) == 2
    assert _seek_is_input_side(calls[0]) is True
    assert _seek_is_input_side(calls[1]) is False


async def test_a_timeout_on_the_output_side_attempt_does_not_loop(
    tmp_path, monkeypatch
):
    """The other half of WO-53's condition. If BOTH attempts time out the
    source really is too slow, and re-running the identical output-side
    command would burn another full budget for nothing. Exactly two
    attempts, and the reported reason is the original one."""
    out_path = tmp_path / "chunk_1.mp3"
    calls: list[list] = []

    async def _run(*args):
        if "volumedetect" in args:
            raise AssertionError("no file was ever produced to check")
        calls.append(list(args))
        raise asyncio.TimeoutError

    monkeypatch.setattr(media_probe, "_run", _run)

    ok, reason = await extract_chunk_audio(
        "https://play.champds.com/DOWNLOAD-MEDIA/oakhilltn/eventmainmedia/50",
        start=900.0,
        duration=900.0,
        source_page_url="https://play.champds.com/oakhilltn/event/50",
        out_path=out_path,
    )

    assert (ok, len(calls)) == (False, 2)
    assert reason and "timed out" in reason


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


# --- chunk_size_seconds_for_platform(): two separate constraints ---------
# Granicus's 300s is a TIMEOUT constraint, real and measured 2026-08-25
# (BACKLOG_DONE.md): 24/24 real Granicus chunk failures over 3 days were
# ffmpeg timeouts on cold CDN fill, the only platform at 100%. 300s was
# chosen against the worst observed cold rate (0.29 s/s) so a chunk still
# fits under the shared 120s subprocess timeout.
#
# The non-Granicus default is a MEMORY constraint, real and measured
# 2026-09-01 (WO-94, see that function's own comment): 450s for a caller
# running Whisper under the cloud worker's 2GB Render plan, still 900s for
# one that isn't. The two must not collapse back into a single value --
# that's what these tests pin.


def test_granicus_gets_the_smaller_chunk_size():
    assert chunk_size_seconds_for_platform("granicus") == 300


def test_granicus_timeout_constraint_ignores_memory_constrained():
    """Granicus's 300s is about the 120s ffmpeg subprocess timeout, which
    binds wherever the fetch runs -- so opting out of the memory
    constraint must not widen it back to a size that times out."""
    assert chunk_size_seconds_for_platform("granicus", memory_constrained=False) == 300


def test_other_platforms_get_the_worker_safe_default():
    for platform in ("civicclerk", "escribe", "youtube", "unknown", ""):
        assert chunk_size_seconds_for_platform(platform) == 450


def test_memory_constrained_defaults_to_true():
    """The default has to be the SAFE one: every job-creation path that
    feeds the cloud worker (app/main.py, worker/main.py, and
    scripts/bulk_queue_transcription_backlog.py, which only writes queue
    rows the worker later executes) relies on not having to pass this."""
    assert chunk_size_seconds_for_platform(
        "civicclerk"
    ) == chunk_size_seconds_for_platform("civicclerk", memory_constrained=True)


def test_unconstrained_callers_keep_the_larger_default():
    """scripts/transcribe_backlog_locally.py runs Whisper on a Mac, not
    under the 2GB ceiling, so it keeps 900s and its original ffmpeg call
    count per meeting."""
    for platform in ("civicclerk", "escribe", "youtube", "unknown", ""):
        assert (
            chunk_size_seconds_for_platform(platform, memory_constrained=False) == 900
        )


# --- probe_multi_clip_chunk_plan() (WO-79) ----------------------------------
#
# Real, confirmed shape (Yolo County CA clip 324107, White Plains NY clip
# 292830, Apple Valley MN): some Swagit meetings publish N separate real
# per-agenda-item video files with no single combined recording. This
# builds the per-clip chunk plan (cumulative meeting-relative offsets) the
# transcription pipeline stitches from -- see app/platforms/swagit.py and
# worker/main.py's process_next_chunk(). Probing itself is just probe_duration()
# per clip, already covered above -- these tests are synthetic over a fake
# probe_duration, exercising only the ordering/cumulative-offset/
# all-or-nothing logic that's new here.


def _video_segment(url, *, seq, title=None):
    from app.platforms.models import VideoSegment

    return VideoSegment(url=url, title=title, seq=seq)


async def test_probe_multi_clip_chunk_plan_orders_by_seq_and_accumulates_offsets(
    monkeypatch,
):
    segments = [
        _video_segment("https://x/c.m3u8", seq=51, title="Third"),
        _video_segment("https://x/a.m3u8", seq=6, title="First"),
        _video_segment("https://x/b.m3u8", seq=13, title="Second"),
    ]
    durations = {
        "https://x/a.m3u8": 120.0,
        "https://x/b.m3u8": 300.0,
        "https://x/c.m3u8": 45.0,
    }

    async def _probe(url, *, source_page_url):
        assert source_page_url == "https://example.new.swagit.com/videos/1"
        return durations[url]

    monkeypatch.setattr(media_probe, "probe_duration", _probe)

    plan = await media_probe.probe_multi_clip_chunk_plan(
        segments, source_page_url="https://example.new.swagit.com/videos/1"
    )

    assert plan == [
        {
            "media_url": "https://x/a.m3u8",
            "start": 0.0,
            "duration": 120.0,
            "title": "First",
            "seq": 6,
        },
        {
            "media_url": "https://x/b.m3u8",
            "start": 120.0,
            "duration": 300.0,
            "title": "Second",
            "seq": 13,
        },
        {
            "media_url": "https://x/c.m3u8",
            "start": 420.0,
            "duration": 45.0,
            "title": "Third",
            "seq": 51,
        },
    ]


async def test_probe_multi_clip_chunk_plan_is_all_or_nothing_on_a_failed_clip(
    monkeypatch,
):
    """A partial plan would silently understate the meeting's real
    duration with no way to tell which clip went missing -- see the
    function's own docstring. One bad clip abandons the whole plan."""
    from app.platforms.media_probe import probe_multi_clip_chunk_plan

    segments = [
        _video_segment("https://x/a.m3u8", seq=1),
        _video_segment("https://x/b.m3u8", seq=2),
    ]

    async def _probe(url, *, source_page_url):
        return 120.0 if url == "https://x/a.m3u8" else None

    monkeypatch.setattr(media_probe, "probe_duration", _probe)

    plan = await probe_multi_clip_chunk_plan(segments, source_page_url="https://x/")
    assert plan is None


async def test_probe_multi_clip_chunk_plan_returns_none_for_a_single_segment():
    from app.platforms.media_probe import probe_multi_clip_chunk_plan

    plan = await probe_multi_clip_chunk_plan(
        [_video_segment("https://x/a.m3u8", seq=1)], source_page_url="https://x/"
    )
    assert plan is None


# --- probe_has_video_stream() (WO-85) ---------------------------------------
#
# Built for BACKLOG_DONE.md's 2026-08-30 "19 audio-only meetings can never
# have a card" entry: archive/utils/video_thumbnail.is_extractable() can
# already tell a URL-detectable audio-only source apart (video_format ==
# "mp3"/"wav") with no probe at all, but the rest -- audio hiding *inside*
# an mp4/m3u8 container on Granicus/IQM2 -- looks identical to a real
# video file by URL/format alone. This is the probe that tells the two
# apart, run once by video_thumbnail.extract_and_store() after a first
# failed frame extraction. `-select_streams v -show_entries
# stream=codec_type -of json -i <url>` returns a `streams` array with one
# entry per matching stream -- empty when there is no video stream at
# all, which is the real, documented ffprobe behavior this mirrors (not
# invented: the same flag shape probe_duration() above already uses for
# `format=duration`, just selecting stream entries instead of the
# container-level field).


async def test_probe_has_video_stream_true_for_a_real_video_stream(monkeypatch):
    async def _run(*args):
        return 0, b'{"streams": [{"codec_type": "video"}]}', b""

    monkeypatch.setattr(media_probe, "_run", _run)

    result = await probe_has_video_stream(
        "https://MediaHTTP.IQM2.com/SanCarlosCA/1450_480.mp4",
        source_page_url="https://sancarlosca.iqm2.com/Citizens/",
    )
    assert result is True


async def test_probe_has_video_stream_false_for_an_audio_only_source(monkeypatch):
    # An empty `streams` array is exactly what `-select_streams v` reports
    # when the container has no video stream at all -- audio hiding
    # inside an mp4/m3u8 on Granicus/IQM2, the exact shape that made 19
    # pages fail thumbnail extraction on every sweep forever before this.
    async def _run(*args):
        return 0, b'{"streams": []}', b""

    monkeypatch.setattr(media_probe, "_run", _run)

    result = await probe_has_video_stream(
        "https://archive-stream.granicus.com/x/audio-only.m3u8",
        source_page_url="https://example.granicus.com/player/clip/1",
    )
    assert result is False


async def test_probe_has_video_stream_none_on_ffprobe_failure(monkeypatch):
    # A probe failure (timeout, unreachable host, malformed output) must
    # not be read as "confirmed audio-only" -- that would permanently
    # blacklist a page over a transient CDN problem, not a real fact
    # about the source. None is the honest "don't know."
    async def _run(*args):
        return 1, b"", b"Connection timed out"

    monkeypatch.setattr(media_probe, "_run", _run)

    result = await probe_has_video_stream(
        "https://archive-stream.granicus.com/x/y.m3u8",
        source_page_url="https://example.granicus.com/player/clip/1",
    )
    assert result is None


async def test_probe_has_video_stream_none_when_ffprobe_missing(monkeypatch):
    async def _run(*args):
        raise FileNotFoundError()

    monkeypatch.setattr(media_probe, "_run", _run)

    result = await probe_has_video_stream(
        "https://archive-stream.granicus.com/x/y.m3u8",
        source_page_url="https://example.granicus.com/player/clip/1",
    )
    assert result is None
