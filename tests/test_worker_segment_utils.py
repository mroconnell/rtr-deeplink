from worker.segment_utils import (
    chunk_count,
    chunk_duration,
    chunk_start,
    shift_segments,
)


def test_shift_segments_chunk_zero_is_identity():
    segments = [{"start": 0.0, "end": 2.5, "text": "Hello."}]
    assert shift_segments(segments, 0.0) == [
        {"start": 0.0, "end": 2.5, "text": "Hello.", "speaker": None}
    ]


def test_shift_segments_offsets_later_chunks():
    # A chunk starting at real time 900s (chunk index 1 at 900s chunks):
    # a cue at 5.0-7.5s within that chunk's own audio must land at
    # 905.0-907.5s in the full-meeting timeline the video player seeks by.
    segments = [{"start": 5.0, "end": 7.5, "text": "Second chunk cue."}]
    assert shift_segments(segments, 900.0) == [
        {"start": 905.0, "end": 907.5, "text": "Second chunk cue.", "speaker": None}
    ]


def test_shift_segments_preserves_speaker_when_present():
    segments = [{"start": 1.0, "end": 2.0, "text": "Hi.", "speaker": "Speaker 1"}]
    assert shift_segments(segments, 10.0)[0]["speaker"] == "Speaker 1"


def test_shift_segments_zero_length_segment():
    segments = [{"start": 3.0, "end": 3.0, "text": ""}]
    result = shift_segments(segments, 100.0)
    assert result[0]["start"] == result[0]["end"] == 103.0


def test_chunk_count_exact_multiple():
    assert chunk_count(1800, 900) == 2


def test_chunk_count_rounds_up():
    assert chunk_count(1801, 900) == 3
    assert chunk_count(1, 900) == 1


def test_chunk_count_rejects_non_positive_size():
    import pytest

    with pytest.raises(ValueError):
        chunk_count(100, 0)


def test_chunk_start_and_duration_normal_chunk():
    assert chunk_start(2, 900) == 1800
    assert chunk_duration(2, 900, total_duration_seconds=5000) == 900


def test_chunk_duration_clamps_final_chunk():
    # 1900s total, 900s chunks -> chunk 2 starts at 1800s, only 100s remain.
    assert chunk_duration(2, 900, total_duration_seconds=1900) == 100


def test_chunk_duration_never_negative_past_the_end():
    assert chunk_duration(5, 900, total_duration_seconds=1900) == 0.0
