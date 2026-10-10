"""Scoring for scripts/shortlist_human_captions.py.

Text shapes copied from real stored transcripts read 2026-10-09: the public
transcript.txt format (`[m:ss] text`, wrapped lines), Weston's `>> mayor:`
and `[ OFF MIC ]`, and Placer's `>>` turns with `[INDISCERNIBLE]`.
"""

from scripts.shortlist_human_captions import (
    eligible,
    features,
    fingerprint,
    parse_txt,
    pick,
    score,
)

SAMPLE = """[0:00] Madam clerk, will you please
call the roll?
[0:03] >> : good evening.
[roll called]
[0:14] >> mayor: could everybody please
stand?
[1:05:00] [ OFF MIC ]
[1:05:02] >> [GAVEL]
"""


def test_parse_keeps_wrapped_lines_and_hours():
    segs = parse_txt(SAMPLE)
    assert [s["start"] for s in segs] == [0.0, 3.0, 14.0, 3900.0, 3902.0]
    assert segs[0]["text"] == "Madam clerk, will you please\ncall the roll?"
    assert "[roll called]" in segs[1]["text"]


def test_features_count_turns_tags_and_hours():
    f = features(parse_txt(SAMPLE))
    assert f["hours"] == round(3902 / 3600, 2)
    assert f["room_kinds"] == 3  # roll called, off mic, gavel
    assert f["turn_share"] >= 0.6


def test_overlap_and_lost_speech_are_counted():
    segs = [
        {"start": 0.0, "text": "[CROSSTALK]"},
        {"start": 10.0, "text": "[INAUDIBLE]"},
        {"start": 3600.0, "text": ">> [SPEAKER OFF MIC]"},
    ]
    f = features(segs)
    assert f["overlap_tags"] == 1
    assert f["lost_speech_tags"] == 2


def test_long_silence_counts_as_a_pause_but_a_long_line_does_not():
    segs = [
        {"start": 0.0, "text": "short"},
        {"start": 20.0, "text": " ".join(["word"] * 60)},
        {"start": 42.0, "text": "end"},
    ]
    assert features(segs)["pauses_per_hour"] > 0
    # 60 words take about 22 seconds to say, so the second gap is no pause
    assert features(segs[1:])["pauses_per_hour"] == 0


def test_a_turn_marker_in_the_middle_of_a_line_counts():
    segs = [
        {"start": 0.0, "text": "thank you. >> Why is it inconsistent? >> Because."},
        {"start": 60.0, "text": "plain line"},
    ]
    f = features(segs)
    assert f["turn_share"] == 1.0  # 2 turns over 2 lines, capped at 1


def test_cutoffs_and_whisper_tags_are_counted():
    segs = [
        {"start": 0.0, "text": "our numbers--"},
        {"start": 5.0, "text": "our numbers go up"},
        {"start": 9.0, "text": "[SIDE CONVERSATION]"},
        {"start": 12.0, "text": "(whispering)"},
        {"start": 3600.0, "text": "end"},
    ]
    f = features(segs)
    assert f["cutoffs"] == 1
    assert f["whisper_tags"] == 2


def test_machine_style_pages_are_not_eligible():
    segs = [{"start": float(i * 60), "text": f"Speaker {i}: hello"} for i in range(30)]
    assert not eligible(features(segs))


def test_noise_tags_lower_the_score():
    base = {
        "room_kinds": 3, "overlap_tags": 0, "turn_share": 0.3, "cutoffs": 0, "whisper_tags": 0,
        "lost_per_hour": 0, "noise_tags": 0,
    }  # fmt: skip
    assert score(base) > score({**base, "noise_tags": 9})


def test_pick_skips_duplicates_and_stops_at_target():
    rows = [
        {"slug": "a", "hours": 3.0, "score": 9, "eligible": True, "fingerprint": "x"},
        {"slug": "b", "hours": 3.0, "score": 8, "eligible": True, "fingerprint": "x"},
        {"slug": "c", "hours": 3.0, "score": 7, "eligible": True, "fingerprint": "y"},
        {"slug": "d", "hours": 3.0, "score": 6, "eligible": True, "fingerprint": "z"},
    ]
    assert [r["slug"] for r in pick(rows, 5.0)] == ["a", "c"]


def test_same_text_same_fingerprint():
    a = parse_txt("[0:00] one two\n[0:05] three")
    b = parse_txt("[0:00] one  two\n[0:05] three")
    assert fingerprint(a) == fingerprint(b)
