"""Scoring for scripts/find_named_speaker_transcripts.py.

Synthetic lines in the exact shapes seen in real caption files read
2026-10-09: Venice (`[SOUNDING GAVEL]`), Kauai (`[ GAVEL ]`), Dubuque
(`(bright music)`), Virginia (`[HOUSE AT EASE]`) and Rosetown
(`[paper rustling]`, `[chair\\nscraping]`).
"""

from scripts.find_named_speaker_transcripts import (
    classify_tag,
    is_lead,
    is_youtube,
    score_segments,
)


def _segs(*texts):
    return [{"start": i, "end": i + 1, "text": t} for i, t in enumerate(texts)]


def test_room_event_tags_are_counted():
    s = score_segments(
        _segs("[SOUNDING GAVEL]", "[ GAVEL ]", "[HOUSE AT EASE]", "[OFF MIC]")
    )
    assert s["room_event_tags"] == 4
    assert s["noise_tags"] == 0


def test_parenthesised_and_lowercase_tags_count():
    s = score_segments(_segs("(bright music)", "(gavel banging)"))
    assert s["common_tags"] == 1
    assert s["room_event_tags"] == 1


def test_tag_split_over_a_line_break_still_matches():
    s = score_segments(_segs("I'll make that correction. [chair\nscraping]"))
    assert s["noise_tags"] == 1


def test_noise_tags_do_not_make_a_lead_alone():
    s = score_segments(_segs(*["[paper rustling]"] * 10))
    assert s["noise_tags"] == 10
    assert not is_lead(s, 3)


def test_rosetown_style_page_is_a_lead_but_shows_noise():
    s = score_segments(
        _segs("[gavel strike]", "[laughter]", "[laughter]", "[paper rustling]")
    )
    assert is_lead(s, 3)
    assert s["noise_tags"] == 1


def test_two_room_event_tags_are_enough():
    # Kauai 2026-04-15 had exactly two [ GAVEL ] tags and nothing else.
    assert is_lead(score_segments(_segs("[ GAVEL ]", "[ GAVEL ]")), 3)
    assert not is_lead(score_segments(_segs("[ APPLAUSE ]", "[ APPLAUSE ]")), 3)


def test_names_alone_no_longer_flag():
    s = score_segments(
        _segs(*[f"El Cerrito Council Chamber: line {i}" for i in range(20)])
    )
    assert s["named_share"] == 1.0
    assert not is_lead(s, 3)


def test_machine_labels_are_not_names():
    s = score_segments(_segs("Speaker 1: hello there", "S2: and again", "s4: more"))
    assert s["distinct_names"] == 0
    assert s["generic_label_lines"] == 3


def test_ordinary_bracketed_words_are_ignored():
    assert classify_tag("see attachment B") is None
    assert classify_tag("GAVEL POUNDS") == "room"
    assert classify_tag("INAUDIBLE") == "common"


def test_is_youtube():
    assert is_youtube("https://www.youtube.com/watch?v=DJD_5jUOmLc")
    assert not is_youtube("https://cityoftampa.granicus.com/x.mp4")
    assert not is_youtube(None)
