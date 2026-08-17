from worker.segment_utils import (
    chunk_count,
    chunk_duration,
    chunk_start,
    count_seam_overlap_segments,
    merge_chunk_segments,
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


# --- Seam-duplication dedup -------------------------------------------------
#
# Real, confirmed bug: extract_chunk_audio()'s fast/input-side ffmpeg `-ss`
# seek snaps to the nearest preceding HLS segment boundary rather than the
# exact requested second, so a chunk boundary can restate several real
# seconds of the previous chunk's tail. Found live 2026-08-16 against a real
# production meeting (Boulder County, CO -- bouldercounty-2026-02-05-
# historic-preservation-advisory-board, an eScribe/HLS meeting), root-caused
# by directly diffing real extracted audio (see worker/segment_utils.py's
# "Seam-duplication dedup" note and BACKLOG_DONE.md), not assumed. The two
# text fixtures below are both real, not invented:
#
# (1) `_REAL_PRODUCTION_*` is the exact text this bug produced on the live
#     page, quoted verbatim from that investigation.
# (2) `_REAL_WHISPER_*` is what a direct faster-whisper "tiny" transcription
#     of this same meeting's real audio produced when this fix was built --
#     extracted straight from the meeting's real HLS source (both a fast/
#     input-side extraction, matching what production actually runs, and an
#     accurate/output-side one used to confirm the fast extraction's audio
#     really did start ~17s early) -- not hand-written text standing in for
#     real transcription output.


def test_count_seam_overlap_detects_real_production_duplicate():
    # Verbatim from the real, live Boulder County page before this fix.
    previous_segments = [
        {"start": 896.0, "end": 899.5, "text": "...this whole question about truck caro, which may actually predate the Bracero program."},
        {"start": 900.0, "end": 900.9, "text": "Um, there's an exhibit at the."},
    ]
    new_segments = [
        {"start": 908.0, "end": 918.7, "text": "This whole question about truck caro, which may actually predate the Bracero program, there's an exhibit at the Colorado Railroad Museum, so down in Golden..."},
    ]
    assert count_seam_overlap_segments(previous_segments, new_segments) == 2

    merged = merge_chunk_segments(previous_segments, new_segments)
    assert merged == new_segments  # both duplicate prev segments dropped, new kept in full


def test_count_seam_overlap_detects_real_whisper_output():
    # A real faster-whisper "tiny" transcription of the Boulder County
    # meeting's actual audio around this same 900s chunk boundary, produced
    # while investigating this bug: ground-truth (accurately-seeked) content
    # just before the true 900s mark, vs. what extract_chunk_audio()'s real
    # fast/input-side `-ss 900` extraction actually contained -- confirmed
    # to start ~12-17s earlier than requested. Segmented differently by the
    # two independent decodes (a real property of Whisper, not simulated),
    # which is exactly why this dedup works at word granularity, not by
    # comparing whole-segment text for equality.
    previous_segments = [
        {"start": 883.36, "end": 889.04, "text": "and I think there may be a tie to what Larry brought up previously, is just this whole question"},
        {"start": 889.04, "end": 899.5, "text": "about Tracero, which may actually predate the Bracero program."},
    ]
    new_segments = [
        {"start": 900.0, "end": 909.04, "text": "whole question about Tracero, which may actually predate the Bracero program, there's an"},
        {"start": 909.04, "end": 918.72, "text": "exhibit at the Colorado Railroad Museum, so down in Golden apparently it's going to be available"},
        {"start": 918.72, "end": 920.72, "text": "until August, so it's..."},
    ]
    drop = count_seam_overlap_segments(previous_segments, new_segments)
    assert drop == 2  # both previous segments are inside the matched overlap

    merged = merge_chunk_segments(previous_segments, new_segments)
    assert merged == new_segments


def test_count_seam_overlap_ignores_genuinely_different_content():
    # Real chunk boundaries where consecutive chunks talk about different
    # things shouldn't lose anything -- this is the default/expected case
    # for the vast majority of chunk boundaries (a direct-file source with
    # no seek imprecision at all, or an HLS source where the boundary
    # happens to land exactly on a segment edge).
    previous_segments = [
        {"start": 895.0, "end": 900.0, "text": "Thank you, Commissioner, that concludes the staff report."},
    ]
    new_segments = [
        {"start": 900.0, "end": 905.0, "text": "Moving on to item four B on tonight's agenda."},
    ]
    assert count_seam_overlap_segments(previous_segments, new_segments) == 0
    assert merge_chunk_segments(previous_segments, new_segments) == [*previous_segments, *new_segments]


def test_count_seam_overlap_ignores_short_coincidental_phrases():
    # A short, ordinary shared phrase ("thank you very much") is real
    # speech, not a seam-duplicate artifact -- must not trigger a drop.
    previous_segments = [
        {"start": 895.0, "end": 900.0, "text": "Okay, thank you very much for that."},
    ]
    new_segments = [
        {"start": 900.0, "end": 905.0, "text": "Thank you very much, next we'll hear from the applicant."},
    ]
    assert count_seam_overlap_segments(previous_segments, new_segments) == 0


def test_count_seam_overlap_empty_inputs_are_safe():
    assert count_seam_overlap_segments([], []) == 0
    assert count_seam_overlap_segments([], [{"start": 0, "end": 1, "text": "hi"}]) == 0
    assert count_seam_overlap_segments([{"start": 0, "end": 1, "text": "hi"}], []) == 0


def test_merge_chunk_segments_no_overlap_is_plain_concatenation():
    previous_segments = [{"start": 0.0, "end": 2.0, "text": "First chunk."}]
    new_segments = [{"start": 900.0, "end": 902.0, "text": "Second chunk."}]
    assert merge_chunk_segments(previous_segments, new_segments) == [*previous_segments, *new_segments]
