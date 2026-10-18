"""A4 (WO-1960): scripts/align_page_timing.py's pure parts. Synthetic
windows in align_captions_to_audio.align_windows()'s real output shape; the
offsets mirror the audit's real cases (Port Moody +244 s constant; County
of Orange +868 s early, then +5 s)."""

from scripts.align_page_timing import (
    decide,
    good_line_offsets,
    keep_order,
    line_offsets,
    segment_offsets,
    shift_segments,
)


def _w(start, lag, verified=True, words=40):
    return {
        "audio_start": float(start),
        "audio_end": float(start + 120),
        "asr_words": words,
        "lag": lag,
        "verified": verified,
    }


def test_constant_offset_moves_every_segment_by_it():
    windows = [_w(t, 244.0) for t in range(0, 1200, 120)]
    segs = [{"start": 300.0, "end": 303.0, "text": "a", "speaker": None}]
    offs = segment_offsets(segs, windows)
    assert offs == [244.0]
    assert shift_segments(segs, offs) == [
        {"start": 56.0, "end": 59.0, "text": "a", "speaker": None}
    ]


def test_a_step_uses_the_window_that_covers_each_segment():
    # Captions run 868 s ahead for the first 20 minutes, then 5 s.
    windows = [_w(t, 868.0) for t in range(0, 1200, 120)]
    windows += [_w(t, 5.0) for t in range(2400, 3600, 120)]
    segs = [{"start": 900.0, "text": "early"}, {"start": 3000.0, "text": "late"}]
    assert segment_offsets(segs, windows) == [868.0, 5.0]


def test_unverified_windows_are_ignored_and_none_means_no_offset():
    windows = [_w(0, 50.0, verified=False)]
    assert segment_offsets([{"start": 10.0}], windows) == [None]
    assert shift_segments([{"start": 10.0, "end": 12.0}], [None]) == [
        {"start": 10.0, "end": 12.0}
    ]


def test_never_below_zero():
    out = shift_segments([{"start": 3.0, "end": 4.0}], [10.0])
    assert out == [{"start": 0.0, "end": 0.0}]


def test_decide_skips_aligned_and_unmatched_pages():
    windows = [_w(t, 2.0) for t in range(0, 600, 120)]
    aligned = {i: 2.0 for i in range(10)}
    assert decide(windows, 10, aligned)[0] == "skip: already aligned"
    unmatched = [_w(t, None, verified=False) for t in range(0, 600, 120)]
    assert decide(unmatched, 10, {})[0] == "skip: too few windows match the audio"
    assert decide(windows, 100, aligned)[0] == (
        "skip: too few caption lines match the audio"
    )


def test_decide_needs_a_clean_residual():
    windows = [_w(t, 244.0) for t in range(0, 600, 120)]
    before = {i: 244.0 for i in range(10)}
    assert decide(windows, 10, before)[0] == "correct"
    assert decide(windows, 10, before, {i: 0.4 for i in range(10)})[0] == "correct"
    assert decide(windows, 10, before, {i: 9.0 for i in range(10)})[0] == (
        "skip: still off after correcting"
    )
    assert decide(windows, 10, before, {0: 0.1, 1: 0.2})[0] == (
        "skip: the corrected times no longer match as well"
    )


def test_line_offsets_follow_each_line_and_drop_a_false_match():
    # Real shape of Cambridge MA 2026-06-18: lines start on time, so the
    # offsets are near 0 even though window lags read up to -304 s.
    segs = [{"start": float(t), "text": str(t)} for t in range(0, 100, 10)]
    times = {i: (float(i * 10) - 1.0, float(i * 10) + 5) for i in range(10)}
    times[5] = (500.0, 505.0)  # a phrase matched somewhere else entirely
    good = good_line_offsets(segs, times)
    assert 5 not in good and good[0] == 1.0
    offs = line_offsets(segs, times)
    assert offs[5] == 1.0  # interpolated from its neighbours


def test_a_cut_recording_shifts_lines_by_their_own_offsets():
    # Captions recorded live; the video lost 60 s after line 4.
    segs = [{"start": float(t), "text": str(t)} for t in range(0, 200, 20)]
    times = {i: (float(i * 20) - (0 if i < 5 else 60), 0.0) for i in range(10)}
    new = keep_order(shift_segments(segs, line_offsets(segs, times)))
    assert [s["start"] for s in new[:5]] == [0.0, 20.0, 40.0, 60.0, 80.0]
    assert new[5]["start"] == 80.0  # 100 - 60 = 40 would go backwards: held
    assert new[9]["start"] == 120.0


def test_keep_order_never_goes_backwards():
    segs = [{"start": 10.0, "end": 12.0}, {"start": 5.0, "end": 6.0}]
    assert keep_order(segs) == [
        {"start": 10.0, "end": 12.0},
        {"start": 10.0, "end": 10.0},
    ]
