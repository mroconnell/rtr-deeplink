"""Audio-measured pauses (scripts/add_audio_pauses.py). SYNTHETIC word times
shaped like the model output [word, start, end] in words.json."""

from scripts.add_audio_pauses import audio_pauses


def test_a_gap_of_a_second_or_more_between_words_is_a_pause():
    words = [["a", 10.0, 10.3], ["b", 10.4, 10.7], ["c", 12.0, 12.4]]
    st = [{"start": 0.0, "end": 100.0}]
    p = audio_pauses(words, st)
    assert len(p) == 1
    assert p[0]["seconds"] == 1.3 and p[0]["long"] is False
    assert p[0]["clip_start"] == 10.7 and p[0]["source"] == "audio_word_gaps"


def test_long_gaps_are_flagged():
    words = [["a", 10.0, 10.3], ["b", 20.0, 20.4]]
    assert audio_pauses(words, [{"start": 0.0, "end": 100.0}])[0]["long"] is True


def test_gaps_across_a_stretch_boundary_are_ignored():
    words = [["a", 10.0, 10.3], ["b", 50.0, 50.4]]
    st = [{"start": 0.0, "end": 20.0}, {"start": 40.0, "end": 60.0}]
    assert audio_pauses(words, st) == []


def test_clip_times_are_relative_to_the_stretch():
    words = [["a", 110.0, 110.3], ["b", 115.0, 115.2]]
    p = audio_pauses(words, [{"start": 100.0, "end": 200.0}])
    assert p[0]["clip_start"] == 10.3 and p[0]["audio_start"] == 110.3
