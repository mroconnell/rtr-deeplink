"""The "may end before the meeting did" warning on a transcript WE made, and
the tail-silence check built with it (Ryan's yes, 2026-10-16).

The shared function under test is
`app.platforms.coverage_check.own_transcript_early_end_warning()`. The
cloud worker (`worker/main.py`), `scripts/transcribe_backlog_locally.py` and
`scripts/retranscribe_first_chunk.py` all call it. Tests of each call site
live next to the other tests of that code; this file pins the rule itself.

Real numbers, measured 2026-09-21 from the public site and the videos' own
playlists (header-only ffprobe), not invented (BACKLOG_DONE.md, WO-935):

* Leon Valley TX show 179 (page 1676): 4,541 own-Whisper cues, last cue at
  5:34:53.18 (20,093.18 s) of a 23,399.666 s video. Ratio 0.859, 55 minutes
  uncovered. 30-second samples, volume only: -38 dB (speech) at 20,050 s,
  -83 dB from 20,500 s to the end.
* Leon Valley TX show 185: last cue at 3:16:24.4 (11,784.4 s) of a
  21,599.933 s video (a fixed 6:00:00 window). Ratio 0.546. -22 dB at
  11,750 s, -71 dB from 12,500 s to the end.
* Leon Valley TX 2025-06-19: last cue at 8,630.94 s of an 8,632.648 s video.
  Ratio 0.9998.

ffmpeg is never run here: `media_probe._run` is replaced by a fake that
answers with real-shaped ffmpeg stderr (the volumedetect lines and the
`time=` progress field, as in tests/test_media_probe.py). The dB values fed
in are the measured ones above. Cue text is synthetic scaffolding.
"""

import pytest

from app.platforms import media_probe
from app.platforms.coverage_check import (
    PARTIAL_TRANSCRIPT_MARKER,
    last_cue_seconds,
    own_transcript_early_end_text,
    own_transcript_early_end_warning,
    own_transcript_tail_sample_start,
)
from app.platforms.models import TranscriptSegment
from archive.db import crud

_URL = "https://leonvalleytx.new.swagit.com/videos/179"  # shape only, never fetched
_MEDIA = (
    "https://archive-stream.granicus.com/OnDemand/_definst_/mp4:x/y.mp4/playlist.m3u8"
)


@pytest.fixture(autouse=True)
def _check_on(monkeypatch):
    # tests/conftest.py switches the check off suite-wide; this file tests it.
    monkeypatch.setenv("RTR_PARTIAL_TRANSCRIPT_CHECK", "1")


def _volumedetect_stderr(mean_db) -> bytes:
    mean = "-inf" if mean_db == float("-inf") else f"{mean_db:.1f}"
    return (
        b"size=N/A time=00:00:30.00 bitrate=N/A speed= 812x\n"
        b"[Parsed_volumedetect_0 @ 0xc9e800e40] n_samples: 480000\n"
        + f"[Parsed_volumedetect_0 @ 0xc9e800e40] mean_volume: {mean} dB\n".encode()
        + b"[Parsed_volumedetect_0 @ 0xc9e800e40] max_volume: -3.0 dB\n"
    )


class _FakeFfmpeg:
    """Stands in for media_probe._run(). An extraction writes a small file
    whose bytes say which channel it holds; volumedetect answers with the
    mean volume set for that channel. Records every call."""

    def __init__(self, mono_db, left_db=None, extraction_exit=0):
        self.mono_db = mono_db
        self.left_db = mono_db if left_db is None else left_db
        self.extraction_exit = extraction_exit
        self.calls = []

    async def __call__(self, *args, timeout=None):
        self.calls.append(args)
        if "volumedetect" in args:
            path = args[args.index("-i") + 1]
            with open(path, "rb") as f:
                channel = f.read()
            db = self.left_db if channel == b"left" else self.mono_db
            if db is None:  # decodes, but ffmpeg printed no volume line
                return 0, b"", b"size=N/A time=00:00:30.00 bitrate=N/A\n"
            return 0, b"", _volumedetect_stderr(db)
        if self.extraction_exit:
            return self.extraction_exit, b"", b"Server returned 404 Not Found\n"
        out = args[-1]
        with open(out, "wb") as f:
            f.write(b"left" if out.endswith(".left.mp3") else b"mono")
        return 0, b"", b""

    def extraction_calls(self):
        return [a for a in self.calls if "volumedetect" not in a]


def _install(monkeypatch, **kwargs) -> _FakeFfmpeg:
    fake = _FakeFfmpeg(**kwargs)
    monkeypatch.setattr(media_probe, "_run", fake)
    return fake


def _own_cues(last_end: float) -> list[dict]:
    """The shape our own transcription stores: plain dicts."""
    return [
        {"start": 583.73, "end": 586.61, "text": "For example, I thought", "speaker": None},
        {"start": last_end - 1.6, "end": last_end, "text": "Thank you.", "speaker": None},
    ]  # fmt: skip


async def _warn(last, duration, **kwargs):
    return await own_transcript_early_end_warning(
        _own_cues(last),
        duration,
        media_url=kwargs.pop("media_url", _MEDIA),
        source_page_url=_URL,
        **kwargs,
    )


# --- the two real flagged pages: silent tails, so no warning ---------------


async def test_page_1676_tail_reads_minus_83_db_so_no_warning(monkeypatch):
    fake = _install(monkeypatch, mono_db=-83.0)
    assert await _warn(20_093.18, 23_399.666) is None
    # It did sample (the rule flagged it): the mono cut, then, because the
    # mono reads quiet, extract_chunk_audio()'s left-channel check -- which
    # also reads -83 dB here, so the tail stays silent.
    mono, left = fake.extraction_calls()
    assert left[-1].endswith(".left.mp3") and not mono[-1].endswith(".left.mp3")


async def test_leon_valley_show_185_tail_reads_minus_71_db_so_no_warning(monkeypatch):
    _install(monkeypatch, mono_db=-71.0)
    assert await _warn(11_784.4, 21_599.933) is None


async def test_digital_silence_reading_minus_inf_is_silent(monkeypatch):
    _install(monkeypatch, mono_db=float("-inf"))
    assert await _warn(20_093.18, 23_399.666) is None


# --- the same pages with speech in the tail: a real early end -------------


@pytest.mark.parametrize("speech_db", [-38.0, -22.0, -41.0])
async def test_speech_after_the_last_cue_gives_the_warning(monkeypatch, speech_db):
    # The measured speech levels on those two pages, placed in the tail: a
    # transcript that stops while people are still talking.
    _install(monkeypatch, mono_db=speech_db)
    warning = await _warn(20_093.18, 23_399.666)
    assert warning is not None
    assert PARTIAL_TRANSCRIPT_MARKER in warning
    assert "5 hours 35 minutes" in warning
    assert "6 hour 30 minute recording" in warning


@pytest.mark.parametrize(
    "mean_db, warned",
    [(-59.9, True), (-60.0, True), (-60.1, False)],
)
async def test_silence_line_is_a_mean_under_minus_60_db(monkeypatch, mean_db, warned):
    _install(monkeypatch, mono_db=mean_db)
    assert (await _warn(20_093.18, 23_399.666) is not None) is warned


async def test_a_phase_cancelled_tail_is_not_read_as_silence(monkeypatch):
    # The mono mix of a stereo source whose channels are phase-inverted
    # reads near-silent (Port Coquitlam, media_probe.py). The sample goes
    # through extract_chunk_audio(), whose left-channel retry finds the real
    # signal, so the tail counts as sound and the warning stands.
    fake = _install(monkeypatch, mono_db=-83.0, left_db=-20.0)
    assert await _warn(20_093.18, 23_399.666) is not None
    assert any(a[-1].endswith(".left.mp3") for a in fake.extraction_calls())


# --- where the sample is taken --------------------------------------------


def test_the_sample_is_centred_halfway_between_the_last_cue_and_the_end():
    start = own_transcript_tail_sample_start(_own_cues(20_093.18), 23_399.666)
    midpoint = 20_093.18 + (23_399.666 - 20_093.18) / 2
    assert start == pytest.approx(midpoint - 15.0)
    # Page 1676: about 21,731 s, inside the measured -83 dB stretch.
    assert 20_500 < start < 23_399.666 - 30


async def test_the_sample_reads_30_seconds_from_that_point(monkeypatch):
    fake = _install(monkeypatch, mono_db=-83.0)
    await _warn(20_093.18, 23_399.666)
    args = fake.extraction_calls()[0]
    assert args[args.index("-ss") + 1] == str(
        own_transcript_tail_sample_start(_own_cues(20_093.18), 23_399.666)
    )
    assert args[args.index("-t") + 1] == "30.0"
    assert args[args.index("-i") + 1] == _MEDIA
    assert "-headers" in args  # a remote source gets the browser-like headers


async def test_a_local_cache_file_is_sampled_with_no_network_headers(
    monkeypatch, tmp_path
):
    cached = tmp_path / "job_42.mp3"
    cached.write_bytes(b"mono")
    fake = _install(monkeypatch, mono_db=-83.0)
    await _warn(20_093.18, 23_399.666, media_url=str(cached))
    args = fake.extraction_calls()[0]
    assert args[args.index("-i") + 1] == str(cached)
    assert "-headers" not in args


async def test_a_multi_clip_meeting_samples_the_clip_that_holds_the_point(
    monkeypatch,
):
    # WO-79 plan shape (cumulative meeting-relative `start`, per-clip
    # `media_url`, WO-95 `media_start`). Two clips; the sample point falls
    # 1,000 s into the second one's window, which starts 600 s into its file.
    plan = [
        {"start": 0.0, "duration": 12_000.0, "media_url": "https://x/clip1.mp4"},
        {
            "start": 12_000.0,
            "duration": 11_399.666,
            "media_url": "https://x/clip2.mp4",
            "media_start": 600.0,
        },
    ]
    fake = _install(monkeypatch, mono_db=-30.0)
    warning = await _warn(20_093.18, 23_399.666, media_url=None, chunk_plan=plan)
    assert warning is not None
    (args,) = fake.extraction_calls()
    assert args[args.index("-i") + 1] == "https://x/clip2.mp4"
    sample_start = own_transcript_tail_sample_start(_own_cues(20_093.18), 23_399.666)
    assert float(args[args.index("-ss") + 1]) == pytest.approx(
        600.0 + sample_start - 12_000.0
    )


def test_media_position_in_chunk_plan_outside_every_clip_is_none():
    plan = [{"start": 0.0, "duration": 100.0, "media_url": "https://x/a.mp4"}]
    assert media_probe.media_position_in_chunk_plan(plan, 150.0) is None
    assert media_probe.media_position_in_chunk_plan(plan, 50.0) == (
        "https://x/a.mp4",
        50.0,
    )


# --- no reading means no warning ------------------------------------------


async def test_an_unreachable_tail_gives_no_warning(monkeypatch):
    _install(monkeypatch, mono_db=-30.0, extraction_exit=8)
    assert await _warn(20_093.18, 23_399.666) is None


async def test_a_tail_with_no_volume_line_gives_no_warning(monkeypatch):
    _install(monkeypatch, mono_db=None)
    assert await _warn(20_093.18, 23_399.666) is None


async def test_no_media_to_sample_gives_no_warning(monkeypatch):
    fake = _install(monkeypatch, mono_db=-30.0)
    assert await _warn(20_093.18, 23_399.666, media_url=None) is None
    assert fake.calls == []


async def test_a_sampler_that_raises_gives_no_warning(monkeypatch):
    async def _boom(*args, **kwargs):
        raise RuntimeError("ffmpeg vanished")

    monkeypatch.setattr(media_probe, "sample_mean_volume_db", _boom)
    assert await _warn(20_093.18, 23_399.666) is None


# --- threshold: unchanged from WO-923, and nothing is sampled below it -----


@pytest.mark.parametrize(
    "last, duration, expected",
    [
        (20_093.18, 23_399.666, True),  # Leon Valley show 179, ratio 0.859
        (11_784.4, 21_599.933, True),  # Leon Valley show 185, ratio 0.546
        (8_630.94, 8_632.648, False),  # Leon Valley 2025-06-19, ratio 0.9998
        (0.9598 * 4692.0, 4692.0, False),  # real Swagit case (WO-923): 3 min gap
        (0.8945 * 3600.0, 3600.0, False),  # WO-923's real ratio 0.8945, 6.3 min gap
        (54.0, 66.0, False),  # short clip: 82% but only a 12 s gap
        (3000.0, 3300.0, False),  # 90.9%: above the ratio line
        (3600.0 - 599.0, 3600.0, False),  # 83.4% but 599 s: one second under the floor
        (3600.0 - 601.0, 3600.0, True),  # 83.3% and 601 s uncovered
    ],
)
async def test_same_threshold_as_wo923_and_only_flagged_ones_are_sampled(
    monkeypatch, last, duration, expected
):
    # Tail has speech, so the threshold alone decides.
    fake = _install(monkeypatch, mono_db=-30.0)
    assert (await _warn(last, duration) is not None) is expected
    assert bool(fake.calls) is expected


@pytest.mark.parametrize("duration", [None, 0, 0.0, -5.0])
async def test_a_missing_or_nonsense_length_is_unmeasurable_not_flagged(
    monkeypatch, duration
):
    fake = _install(monkeypatch, mono_db=-30.0)
    assert await _warn(1000.0, duration) is None
    assert fake.calls == []


async def test_an_implausibly_long_length_is_not_flagged(monkeypatch):
    # Over the 14 hour ceiling a "duration" is more likely a garbage stream
    # than a real recording -- WO-923's own guard, inherited.
    _install(monkeypatch, mono_db=-30.0)
    assert await _warn(10.0, 30 * 3600.0) is None


async def test_no_cues_is_not_flagged(monkeypatch):
    _install(monkeypatch, mono_db=-30.0)
    assert (
        await own_transcript_early_end_warning(
            [], 23_399.666, media_url=_MEDIA, source_page_url=_URL
        )
        is None
    )


async def test_only_the_last_cue_is_compared_never_gaps_inside(monkeypatch):
    # A 3-hour silence in the MIDDLE (skipped by the voice filter) with the
    # last cue at the very end is not flagged, and nothing is sampled.
    fake = _install(monkeypatch, mono_db=-30.0)
    cues = [
        {"start": 10.0, "end": 20.0, "text": "Call to order."},
        {"start": 11_000.0, "end": 11_010.0, "text": "Back on the record."},
        {"start": 14_390.0, "end": 14_398.0, "text": "Adjourned."},
    ]
    assert (
        await own_transcript_early_end_warning(
            cues, 14_400.0, media_url=_MEDIA, source_page_url=_URL
        )
        is None
    )
    assert fake.calls == []


def test_cue_objects_and_plain_dicts_read_the_same():
    as_objects = [TranscriptSegment(start=1.0, end=20_093.18, text="x")]
    as_dicts = [{"start": 1.0, "end": 20_093.18, "text": "x"}]
    assert last_cue_seconds(as_objects) == last_cue_seconds(as_dicts) == 20_093.18


async def test_the_check_can_be_switched_off(monkeypatch):
    fake = _install(monkeypatch, mono_db=-30.0)
    monkeypatch.setenv("RTR_PARTIAL_TRANSCRIPT_CHECK", "0")
    assert await _warn(20_093.18, 23_399.666) is None
    assert fake.calls == []


# --- it reuses the existing marker; the Archive treats it as truncated ----


def test_the_warning_uses_the_archives_existing_marker_and_wording():
    last, duration = 20_093.18, 23_399.666
    warning = own_transcript_early_end_text(last, duration)
    assert crud._EARLY_TRUNCATION_MARKER in warning
    # The Archive's own job-creation wording, character for character
    # (crud._flag_default_transcript_if_truncated_early()).
    assert warning == (
        "This transcript may end before the meeting did — it covers "
        f"about {crud._duration_words(last)} of what looks like a "
        f"{crud._duration_words(duration, attributive=True)} recording."
    )
    # It must not claim the captions stop "at the source": these are our
    # own cues.
    assert "at the source" not in warning


def test_the_warning_makes_the_archive_treat_the_page_as_truncated():
    warnings = [own_transcript_early_end_text(20_093.18, 23_399.666)]
    assert crud._has_real_warning_free_transcript(warnings) is False
    assert (
        crud._classify_page_outcome(
            video_url="https://example.com/v.m3u8",
            agenda_items=[],
            default_content_hash="x",
            default_transcript_warnings=warnings,
            default_transcript_language="en",
        )
        == "truncated_transcript"
    )


def test_every_transcription_path_uses_the_one_shared_function():
    """The point of one function: the cloud path and the local scripts
    cannot drift, as the two copies of detect_hallucination_warnings()
    already can."""
    import sys
    from pathlib import Path

    scripts = str(Path(__file__).resolve().parent.parent / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import retranscribe_first_chunk as rfc
    import transcribe_backlog_locally as tbl
    from worker import main as worker_main

    assert (
        worker_main.own_transcript_early_end_warning is own_transcript_early_end_warning
    )
    assert tbl.own_transcript_early_end_warning is own_transcript_early_end_warning
    assert rfc.own_transcript_early_end_warning is own_transcript_early_end_warning


# --- call site: the cloud worker, before it reports the LAST chunk ---------
#
# worker/main.py's process_next_chunk() with crud, the re-resolve and the
# chunk extraction mocked (the same approach as
# tests/test_worker_multi_clip_chunk_plan.py); only media_probe._run is
# faked for the tail sample, so the real shared check runs. Page 1676's
# numbers, as a two-chunk job: chunk 0 holds the early cues, chunk 1 (the
# last) ends at 20,093.18 s.


class _Engine:
    def __init__(self, segments):
        self._segments = segments

    async def transcribe_chunk(self, path):
        return self._segments


async def _run_worker_chunk(monkeypatch, *, chunk_index):
    import worker.main as wm
    from app.platforms.base import UnsupportedPlatformError

    async def _claim():
        return {
            "job_id": 935,
            "chunk_index": chunk_index,
            "source_url": _URL,
            "platform": "swagit",
            "media_url": _MEDIA,
            "total_chunks": 2,
            "chunk_size_seconds": 12_000,
            "probed_duration_seconds": 23_399.666,
            "chunk_plan": None,
            "partial_segments": [
                {"start": 583.73, "end": 586.61, "text": "For example, I thought"}
            ],
        }

    def _no_finder(platform):
        raise UnsupportedPlatformError("not re-resolved in this test")

    async def _extract(media_url, *, start, duration, source_page_url, out_path, **kw):
        out_path.write_bytes(b"chunk")
        return True, None

    reports = []

    async def _report(job_id, **kwargs):
        reports.append(kwargs)
        return {"status": "completed", "transcript_version_id": 1}

    async def _noop(job_id):
        pass

    monkeypatch.setattr(wm.crud, "claim_next_chunk", _claim)
    monkeypatch.setattr(wm, "get_finder", _no_finder)
    monkeypatch.setattr(wm, "extract_chunk_audio", _extract)
    monkeypatch.setattr(wm.crud, "report_chunk_result", _report)
    monkeypatch.setattr(wm, "_send_completion_email", _noop)

    # Chunk 1 starts at 12,000 s; its last cue ends 8,093.18 s in.
    engine = _Engine([{"start": 8_091.58, "end": 8_093.18, "text": "Thank you."}])
    assert await wm.process_next_chunk(engine) is True
    (report,) = reports
    return report


async def test_worker_last_chunk_with_speech_in_the_tail_reports_the_warning(
    monkeypatch,
):
    fake = _install(monkeypatch, mono_db=-38.0)
    report = await _run_worker_chunk(monkeypatch, chunk_index=1)
    (warning,) = report["finished_transcript_warnings"]
    assert PARTIAL_TRANSCRIPT_MARKER in warning and "5 hours 35 minutes" in warning
    # Sampled from the job's media URL (no whole-audio cache for HLS).
    assert (
        fake.extraction_calls()[0][fake.extraction_calls()[0].index("-i") + 1] == _MEDIA
    )


async def test_worker_last_chunk_with_a_silent_tail_reports_no_warning(monkeypatch):
    _install(monkeypatch, mono_db=-83.0)
    report = await _run_worker_chunk(monkeypatch, chunk_index=1)
    assert report["finished_transcript_warnings"] is None


async def test_worker_does_not_check_before_the_last_chunk(monkeypatch):
    fake = _install(monkeypatch, mono_db=-38.0)
    report = await _run_worker_chunk(monkeypatch, chunk_index=0)
    assert report["finished_transcript_warnings"] is None
    assert fake.calls == []


async def test_worker_samples_its_whole_audio_cache_when_it_has_one(
    monkeypatch, tmp_path
):
    import worker.main as wm

    cached = tmp_path / "job_935.mp3"
    cached.write_bytes(b"mono")
    monkeypatch.setattr(wm, "_job_audio_cache_path", lambda job_id: cached)
    fake = _install(monkeypatch, mono_db=-38.0)
    warnings = await wm._finished_transcript_warnings(
        job_id=935,
        previous_segments=_own_cues(20_093.18)[:1],
        drop_previous_tail=0,
        shifted=_own_cues(20_093.18)[1:],
        total_duration=23_399.666,
        media_url=_MEDIA,
        source_url=_URL,
        chunk_plan=None,
    )
    assert warnings and PARTIAL_TRANSCRIPT_MARKER in warnings[0]
    args = fake.extraction_calls()[0]
    assert args[args.index("-i") + 1] == str(cached)


async def test_worker_check_failure_never_loses_the_transcript(monkeypatch):
    import worker.main as wm

    async def _boom(*args, **kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(wm, "own_transcript_early_end_warning", _boom)
    assert (
        await wm._finished_transcript_warnings(
            job_id=935,
            previous_segments=[],
            drop_previous_tail=0,
            shifted=_own_cues(20_093.18),
            total_duration=23_399.666,
            media_url=_MEDIA,
            source_url=_URL,
            chunk_plan=None,
        )
        is None
    )


# --- call site: scripts/retranscribe_first_chunk.py -----------------------
#
# It splices a fresh first chunk onto an existing transcript and pushes the
# result. Before this it pushed hallucination warnings only, so splicing
# onto a transcript that stops early would drop the early-end flag.


def _rfc():
    import sys
    from pathlib import Path

    scripts = str(Path(__file__).resolve().parent.parent / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import retranscribe_first_chunk

    return retranscribe_first_chunk


async def test_retranscribe_first_chunk_keeps_the_early_end_flag(monkeypatch):
    rfc = _rfc()

    async def _probe(video_url, *, source_page_url):
        return 23_399.666

    monkeypatch.setattr(rfc, "probe_duration", _probe)
    _install(monkeypatch, mono_db=-38.0)
    warnings = await rfc.finished_transcript_warnings(
        _own_cues(20_093.18), video_url=_MEDIA, video_format="m3u8", source_url=_URL
    )
    (warning,) = warnings
    assert PARTIAL_TRANSCRIPT_MARKER in warning


async def test_retranscribe_first_chunk_silent_tail_gives_no_flag(monkeypatch):
    rfc = _rfc()

    async def _probe(video_url, *, source_page_url):
        return 23_399.666

    monkeypatch.setattr(rfc, "probe_duration", _probe)
    _install(monkeypatch, mono_db=-83.0)
    assert (
        await rfc.finished_transcript_warnings(
            _own_cues(20_093.18), video_url=_MEDIA, video_format="m3u8", source_url=_URL
        )
        == []
    )


async def test_retranscribe_first_chunk_never_probes_a_youtube_source(monkeypatch):
    rfc = _rfc()

    async def _probe(video_url, *, source_page_url):
        raise AssertionError("a YouTube source must not be probed off the drip Mac")

    monkeypatch.setattr(rfc, "probe_duration", _probe)
    fake = _install(monkeypatch, mono_db=-38.0)
    assert (
        await rfc.finished_transcript_warnings(
            _own_cues(20_093.18),
            video_url="https://www.youtube.com/embed/5LZqoNDRMYk",
            video_format="youtube",
            source_url=_URL,
        )
        == []
    )
    assert fake.calls == []
