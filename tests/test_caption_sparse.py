"""app/utils/vtt_parser.py caption_text_is_sparse: label-only or near-empty captions
(Ryan, 2026-10-02)."""

from app.utils.vtt_parser import caption_text_is_sparse


def _cues(texts, step=120.0):
    return [
        {"start": i * step, "end": (i + 1) * step, "text": t}
        for i, t in enumerate(texts)
    ]


def test_speaker_tags_alone_are_sparse_over_a_long_meeting():
    sparse, words, minutes = caption_text_is_sparse(_cues(["S1:", "s2:", "S3:"] * 10))
    assert sparse is True and words == 0 and minutes > 50


def test_a_few_words_among_many_tags_is_still_sparse():
    cues = _cues(["Yay! S1:", "S2:", "Any other questions? S7:"] + ["S1:"] * 27)
    sparse, words, _ = caption_text_is_sparse(cues)
    assert sparse is True and words == 4


def test_a_normal_meeting_is_not_sparse():
    """A cue every six seconds, a real caption feed's pace: about 60 words a minute here,
    well under real speech but far above the threshold."""
    cues = _cues(
        ["Good evening and welcome to the regular meeting of the council"] * 500,
        step=6.0,
    )
    assert caption_text_is_sparse(cues)[0] is False


def test_a_short_span_is_never_sparse():
    """A two-minute clip can be mostly silent."""
    assert caption_text_is_sparse(_cues(["S1:", "S2:"], step=30.0))[0] is False


def test_no_cues_is_not_sparse():
    assert caption_text_is_sparse([]) == (False, 0, 0.0)
