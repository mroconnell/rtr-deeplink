"""WO-79: worker/main.py's process_next_chunk() consuming a per-clip
chunk_plan (some Swagit meetings split into several real video files with
no single combined recording -- see app/platforms/swagit.py,
archive/db/models.py's TranscriptionJob.chunk_plan). These mock crud/
extraction/transcription directly (unlike tests/test_transcription_jobs.py's
real-DB integration tests) since the thing under test here is specifically
process_next_chunk()'s own branching -- which fields it reads from a claim,
and what it does with them -- not the DB layer that produced them.
"""

import pytest

import worker.main as wm


def _chunk_plan():
    return [
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
    ]


class _Engine:
    def __init__(self, segments):
        self._segments = segments

    async def transcribe_chunk(self, path):
        return self._segments


async def test_process_next_chunk_extracts_the_right_clip_and_shifts_by_its_own_offset(
    monkeypatch,
):
    """chunk_index maps directly onto chunk_plan[chunk_index] -- extraction
    uses THAT entry's own media_url with start=0/duration=the clip's own
    full length (never the usual fixed chunk_size_seconds window), and the
    transcribed segments get shifted by the entry's cumulative MEETING-
    relative `start` (120.0 here for the second clip), not by the
    extraction's own start (always 0.0 for a whole-clip chunk)."""
    chunk_plan = _chunk_plan()

    async def _claim():
        return {
            "job_id": 555,
            "chunk_index": 1,  # the SECOND clip
            "source_url": "https://yolocountyca.new.swagit.com/videos/324107",
            "platform": "swagit",
            # Frozen first-clip URL, same field every ordinary job carries
            # -- must NOT be what gets extracted for chunk_index 1.
            "media_url": "https://x/a.m3u8",
            "total_chunks": 2,
            "chunk_size_seconds": 900,
            "probed_duration_seconds": 420.0,
            "chunk_plan": chunk_plan,
            "partial_segments": [],
        }

    monkeypatch.setattr(wm.crud, "claim_next_chunk", _claim)

    extract_calls = []

    async def _extract(media_url, *, start, duration, source_page_url, out_path):
        extract_calls.append(
            {"media_url": media_url, "start": start, "duration": duration}
        )
        out_path.write_bytes(b"fake-audio")
        return True, None

    monkeypatch.setattr(wm, "extract_chunk_audio", _extract)

    def _fail_get_finder(platform):
        raise AssertionError(
            "a chunk_plan job must not re-resolve the whole meeting per chunk -- "
            "it uses the frozen per-clip URL from the plan directly"
        )

    monkeypatch.setattr(wm, "get_finder", _fail_get_finder)

    report_calls = {}

    async def _report(
        job_id,
        *,
        success,
        shifted_segments=None,
        drop_previous_tail=0,
        error=None,
        chunk_index=None,
    ):
        report_calls.update(
            job_id=job_id, success=success, shifted_segments=shifted_segments
        )
        return {"status": "completed", "transcript_version_id": 42}

    monkeypatch.setattr(wm.crud, "report_chunk_result", _report)

    async def _noop(job_id):
        pass

    monkeypatch.setattr(wm, "_send_completion_email", _noop)

    engine = _Engine([{"start": 1.0, "end": 2.0, "text": "hello", "speaker": None}])
    processed = await wm.process_next_chunk(engine)

    assert processed is True
    # The SECOND clip's own URL/duration, extracted from its own start
    # (0.0) -- not the frozen first-clip media_url, and not a
    # chunk_size_seconds-windowed start/duration.
    assert extract_calls == [
        {"media_url": "https://x/b.m3u8", "start": 0.0, "duration": 300.0}
    ]
    # Shifted by the clip's own cumulative MEETING-relative offset (120.0),
    # not by the extraction start (0.0) -- these are deliberately different
    # numbers for a chunk_plan job, unlike the ordinary fixed-window case
    # where they're the same value.
    assert report_calls["shifted_segments"] == [
        {"start": 121.0, "end": 122.0, "text": "hello", "speaker": None}
    ]
    assert report_calls["success"] is True


async def test_process_next_chunk_does_not_cache_whole_audio_for_a_chunk_plan_job(
    monkeypatch,
):
    """should_cache_whole_audio()'s cache is keyed only by job_id and
    assumes every chunk of a job is a different OFFSET into the SAME
    file -- a chunk_plan job's chunks are different CLIPS (different
    media_url each), so that cache must never be used here even if a
    future clip's media_url weren't HLS (see process_next_chunk()'s own
    comment)."""
    chunk_plan = _chunk_plan()

    async def _claim():
        return {
            "job_id": 556,
            "chunk_index": 0,
            "source_url": "https://yolocountyca.new.swagit.com/videos/324107",
            "platform": "swagit",
            "media_url": "https://x/a.m3u8",
            "total_chunks": 2,
            "chunk_size_seconds": 900,
            "probed_duration_seconds": 420.0,
            "chunk_plan": chunk_plan,
            "partial_segments": [],
        }

    monkeypatch.setattr(wm.crud, "claim_next_chunk", _claim)

    def _fail_should_cache(media_url, total_chunks):
        raise AssertionError(
            "should_cache_whole_audio must never be consulted for a chunk_plan job"
        )

    monkeypatch.setattr(wm, "should_cache_whole_audio", _fail_should_cache)

    async def _extract(media_url, *, start, duration, source_page_url, out_path):
        out_path.write_bytes(b"fake-audio")
        return True, None

    monkeypatch.setattr(wm, "extract_chunk_audio", _extract)
    monkeypatch.setattr(
        wm, "get_finder", lambda platform: (_ for _ in ()).throw(AssertionError)
    )

    async def _report(job_id, **kwargs):
        return {"status": "in_progress"}

    monkeypatch.setattr(wm.crud, "report_chunk_result", _report)

    engine = _Engine([])
    processed = await wm.process_next_chunk(engine)
    assert processed is True


# --- WO-95: a long clip must be sub-split, not become one huge chunk -------
#
# Real, confirmed production failure (2026-09-02), not a hypothetical: Alamo
# Area MPO (alamoareampo.new.swagit.com/videos/149390) is a real multi-clip
# Swagit meeting whose job 1419 carried a single 2,519.69-second clip as
# chunk 6 of 9. That chunk OOM-killed the 2GB Render worker on every claim
# (~3.6GB projected peak RSS against the measured duration/RSS curve), and
# because an OOM-killed process reports no failure, the claim went stale and
# the same chunk was re-claimed ~40 times over 3.5 hours.
#
# The durations below are the real probed values from that job: its total
# was 5003.458s across 9 clips, which is what makes it the useful fixture --
# ceil(5003.458/900) is 6, so the 9 proves it was the chunk_plan path, and
# no chunk_size_seconds value could have capped it.

from app.platforms.media_probe import _clip_pieces  # noqa: E402


def test_clip_shorter_than_the_cap_is_left_as_one_whole_piece():
    assert _clip_pieces(556.0, 900) == [(0.0, 556.0)]


def test_clip_exactly_at_the_cap_is_not_split():
    assert _clip_pieces(900.0, 900) == [(0.0, 900.0)]


def test_the_real_alamo_area_mpo_clip_is_split_under_the_cap():
    """The 42-minute clip that OOM-killed production."""
    pieces = _clip_pieces(2519.69, 450)
    assert len(pieces) == 6
    assert all(dur <= 450 for _off, dur in pieces)
    # Contiguous, no gap and no overlap, and the whole clip is covered.
    assert pieces[0][0] == 0.0
    for (off, dur), (next_off, _) in zip(pieces, pieces[1:]):
        assert off + dur == next_off
    assert sum(dur for _off, dur in pieces) == pytest.approx(2519.69)


def test_no_cap_preserves_the_pre_wo95_whole_clip_behavior():
    """max_chunk_seconds=None is the old shape exactly -- what an existing
    caller that hasn't been updated still gets."""
    assert _clip_pieces(2519.69, None) == [(0.0, 2519.69)]


async def test_process_next_chunk_extracts_a_sub_split_window_from_its_intra_clip_offset(
    monkeypatch,
):
    """WO-95: an entry may be a window WITHIN a long clip, so extraction has
    to start at that entry's own `media_start` -- not 0.0, which before WO-95
    was hardcoded and is what made a 42-minute clip a 42-minute chunk.

    The two offsets are deliberately different numbers here and must not be
    swapped: `media_start` (450.0) is where ffmpeg seeks INTO THE CLIP FILE,
    while `start` (1370.0) is the MEETING-relative offset the transcribed
    segments get shifted by. The clip itself begins 920s into the meeting, so
    a bug that used `start` for extraction would seek past the clip's end and
    a bug that used `media_start` for shifting would misplace every timestamp
    by 920 seconds.
    """
    chunk_plan = [
        {
            "media_url": "https://x/a.m3u8",
            "start": 0.0,
            "media_start": 0.0,
            "duration": 920.0,
            "title": "First",
            "seq": 6,
        },
        # One long clip, sub-split into two 450s windows + a remainder.
        {
            "media_url": "https://x/long.m3u8",
            "start": 920.0,
            "media_start": 0.0,
            "duration": 450.0,
            "title": "Long",
            "seq": 13,
        },
        {
            "media_url": "https://x/long.m3u8",
            "start": 1370.0,
            "media_start": 450.0,
            "duration": 450.0,
            "title": "Long",
            "seq": 13,
        },
    ]

    async def _claim():
        return {
            "job_id": 556,
            "chunk_index": 2,  # the SECOND window of the long clip
            "source_url": "https://alamoareampo.new.swagit.com/videos/149390",
            "platform": "swagit",
            "media_url": "https://x/a.m3u8",
            "total_chunks": 3,
            "chunk_size_seconds": 450,
            "probed_duration_seconds": 1820.0,
            "chunk_plan": chunk_plan,
            "partial_segments": [],
        }

    monkeypatch.setattr(wm.crud, "claim_next_chunk", _claim)

    extract_calls = []

    async def _extract(media_url, *, start, duration, source_page_url, out_path):
        extract_calls.append(
            {"media_url": media_url, "start": start, "duration": duration}
        )
        out_path.write_bytes(b"fake-audio")
        return True, None

    monkeypatch.setattr(wm, "extract_chunk_audio", _extract)

    def _fail_get_finder(platform):
        raise AssertionError("a chunk_plan job must not re-resolve per chunk")

    monkeypatch.setattr(wm, "get_finder", _fail_get_finder)

    report_calls = {}

    async def _report(
        job_id,
        *,
        success,
        shifted_segments=None,
        drop_previous_tail=0,
        error=None,
        chunk_index=None,
    ):
        report_calls.update(shifted_segments=shifted_segments, success=success)
        return {"status": "completed", "transcript_version_id": 43}

    monkeypatch.setattr(wm.crud, "report_chunk_result", _report)

    async def _noop(job_id):
        pass

    monkeypatch.setattr(wm, "_send_completion_email", _noop)

    engine = _Engine([{"start": 1.0, "end": 2.0, "text": "hello", "speaker": None}])
    assert await wm.process_next_chunk(engine) is True

    # Seeks 450s INTO the long clip's own file, for 450s -- capped, not the
    # whole clip.
    assert extract_calls == [
        {"media_url": "https://x/long.m3u8", "start": 450.0, "duration": 450.0}
    ]
    # Shifted by the MEETING-relative offset (1370.0), not the intra-clip one.
    assert report_calls["shifted_segments"] == [
        {"start": 1371.0, "end": 1372.0, "text": "hello", "speaker": None}
    ]
