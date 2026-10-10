"""Labels from scripts/build_speech_annotations.py.

Text shapes copied from real transcripts read 2026-10-09: Weston
(`>> mayor:`, `[ OFF MIC ]`), Azusa ("numbers-- our numbers"), Kauai
(`>>` inside a caption line) and Placer (`[INDISCERNIBLE]`, `[SPEAKER OFF MIC]`).
"""

from scripts.build_speech_annotations import annotate, redact


def _segs(*pairs):
    return [{"start": float(t), "text": x} for t, x in pairs]


def _kinds(ann):
    return [a["kind"] for a in ann]


def test_typed_name_and_marker_make_turns():
    ann = annotate(_segs((0, ">> mayor: please stand"), (5, "ok"), (9, ">> thanks")))
    turns = [a for a in ann if a["kind"] == "turn"]
    assert len(turns) == 2
    assert turns[0]["speaker"] == "mayor"
    assert turns[1]["speaker"] is None
    assert turns[0]["end"] == 9.0


def test_marker_inside_a_line_is_flagged_within_cue():
    ann = annotate(_segs((0, "motion carried. >> Madam chair, one more")))
    turn = [a for a in ann if a["kind"] == "turn"][0]
    assert turn["within_cue"] is True


def test_dash_cut_by_another_speaker_is_an_interruption():
    ann = annotate(_segs((0, "our numbers--"), (3, ">> thank you"), (6, "end")))
    assert "interruption" in _kinds(ann)


def test_dash_cut_then_same_speaker_is_a_self_repair():
    ann = annotate(_segs((0, "our numbers--"), (3, "our numbers go up"), (6, "end")))
    assert "self_repair" in _kinds(ann)
    assert "interruption" not in _kinds(ann)


def test_tag_kinds_are_split_by_meaning():
    ann = annotate(
        _segs(
            (0, "[CROSSTALK]"),
            (2, "[INAUDIBLE]"),
            (4, "[SPEAKER OFF MIC]"),
            (6, "[ GAVEL ]"),
            (8, "(whispering)"),
        )
    )
    k = _kinds(ann)
    assert "overlap" in k
    assert k.count("lost_speech") == 2
    assert "sound_event" in k
    assert "whisper_or_side_talk" in k


def test_caption_gaps_no_longer_make_pauses():
    # 2026-10-10: caption gaps are not silence (6 of 8 sampled were wrong).
    ann = annotate(_segs((0, "hello there"), (30, "back again"), (33, "end")))
    assert "pause" not in _kinds(ann)


def test_long_turn_then_time_limit_words_is_a_cut_off():
    ann = annotate(
        _segs(
            (0, "Speaker One: and another thing"),
            (200, ">> Thank you, your time is up."),
            (205, "next"),
        )
    )
    assert "speaker_cut_off" in _kinds(ann)


def test_every_label_has_an_id_source_and_rule():
    ann = annotate(_segs((0, ">> a"), (10, "[GAVEL]")))
    assert all(a["source"] == "heuristic" and a["rule"] and a["id"] for a in ann)


def test_redact_emails_and_phones():
    text, n = redact("write bob@example.com or call (415) 555-1212 today")
    assert n == 2
    assert "example.com" not in text and "555" not in text


def test_dash_cut_then_time_is_up_is_a_cut_off():
    # Virginia House 2018-04-18: "...about having this vote -- >> Mr. Speaker.
    # >> I would say that time is up."
    ann = annotate(
        _segs(
            (0, "strongly about it, about having this vote --"),
            (4, ">> Mr. Speaker."),
            (6, ">> I would say that time is up."),
            (9, "next"),
        )
    )
    cut = [a for a in ann if a["kind"] == "speaker_cut_off"]
    assert len(cut) == 1 and cut[0]["confidence"] == "medium"


def test_announcing_the_limit_is_not_a_cut_off():
    ann = annotate(
        _segs((0, "Speaker: and so on"), (100, ">> you have three minutes"), (110, "x"))
    )
    assert "speaker_cut_off" not in _kinds(ann)


def test_thanking_someone_for_their_time_is_not_a_cut_off():
    ann = annotate(
        _segs(
            (0, "Speaker: long remarks"),
            (100, "I thank you for your time. >> thank you"),
            (110, "x"),
        )
    )
    assert "speaker_cut_off" not in _kinds(ann)
