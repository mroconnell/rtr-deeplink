"""Alignment logic of scripts/align_captions_to_audio.py.

SYNTHETIC: the words are random draws from a fixed word list, with caption
times shifted from the "audio" times by a known lag. The shapes mirror what
the real probes found on 2026-10-09 (a constant lag, a one-time step as in
Coral Gables, and captions that do not match at all as in Dunnellon). No real
audio or Whisper run is involved.
"""

import random

from scripts.align_captions_to_audio import (
    align_windows,
    caption_words,
    coverage,
    label_audio_times,
    match_window,
)

VOCAB = [f"word{i}" for i in range(400)]


def _make(seconds, lag_at, seed=1, wps=2.5):
    """Return (asr_words, caption_lines). lag_at(t) = caption minus audio."""
    rnd = random.Random(seed)
    asr, caps, t = [], [], 0.0
    line, line_t = [], None
    while t < seconds:
        w = rnd.choice(VOCAB)
        asr.append((w, t, t + 0.3))
        if line_t is None:
            line_t = t + lag_at(t)
        line.append(w)
        if len(line) == 8:
            caps.append({"start": line_t, "text": " ".join(line)})
            line, line_t = [], None
        t += 1.0 / wps
    return asr, caps


def test_caption_words_skips_tags_and_markers():
    cw = caption_words([{"start": 5.0, "text": ">> [GAVEL] Thank you, (aside) Mayor"}])
    assert [w for w, _, _ in cw] == ["thank", "you", "mayor"]
    assert all(i == 0 and t == 5.0 for _, t, i in cw)


def test_match_window_finds_a_constant_lag():
    asr, caps = _make(120, lambda t: 4.0)
    r = match_window(asr, caption_words(caps))
    assert r["agree"] > 90
    assert abs(r["lag"] - 4.0) < 4.5  # caption lines start a few words in


def test_constant_lag_is_verified_everywhere():
    asr, caps = _make(900, lambda t: 5.0)
    wins, _ = align_windows(asr, caption_words(caps), 900)
    assert all(w["verified"] for w in wins[:-1])
    st = coverage(wins)
    assert len(st) == 1 and st[0]["end"] - st[0]["start"] >= 600


def test_a_one_time_step_is_followed_and_splits_the_stretch():
    # Coral Gables shape: captions 32 s off, then 4 s off after the midpoint.
    asr, caps = _make(1800, lambda t: 32.0 if t < 900 else 4.0)
    wins, _ = align_windows(asr, caption_words(caps), 1800)
    lags = [w["lag"] for w in wins if w["verified"]]
    assert any(abs(x - 32) < 5 for x in lags) and any(abs(x - 4) < 5 for x in lags)
    assert len(coverage(wins)) == 2


def test_unrelated_captions_are_never_verified():
    asr, _ = _make(600, lambda t: 0.0, seed=1)
    _, caps = _make(600, lambda t: 0.0, seed=99)  # different text
    wins, _ = align_windows(asr, caption_words(caps), 600)
    assert not any(w["verified"] for w in wins)
    assert coverage(wins) == []


def test_a_large_constant_offset_is_found_by_the_search():
    # Dunnellon shape: captions about 13 minutes later than the audio.
    asr, caps = _make(900, lambda t: 770.0)
    wins, _ = align_windows(asr, caption_words(caps), 900)
    assert sum(w["verified"] for w in wins) >= 5


def test_label_times_use_matched_words_and_stay_inside_a_stretch():
    stretches = [{"start": 100.0, "end": 700.0, "lag": 4.0}]
    line_times = {3: (130.0, 133.0), 4: (134.0, 138.0)}
    ann = {"caption_index": 3, "caption_index_end": 4, "start": 135.0, "end": 140.0}
    t = label_audio_times(ann, line_times, stretches)
    assert t["audio_start"] == 130.0 and t["audio_end"] == 138.0
    assert t["clip_start"] == 30.0 and t["time_basis"] == "matched_words"
    outside = {"caption_index": 9, "caption_index_end": 9, "start": 900.0, "end": 901.0}
    assert label_audio_times(outside, line_times, stretches) is None
