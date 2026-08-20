from dataclasses import dataclass, field
from typing import List, Optional

from worker.transcription_engine import _split_segment_on_word_gaps


@dataclass
class _FakeWord:
    start: float
    end: float
    word: str


@dataclass
class _FakeSegment:
    start: float
    end: float
    text: str
    words: Optional[List[_FakeWord]] = field(default=None)


def test_no_gap_stays_one_segment():
    seg = _FakeSegment(
        start=0.0,
        end=1.2,
        text=" Hi there.",
        words=[_FakeWord(0.0, 0.3, " Hi"), _FakeWord(0.3, 1.2, " there.")],
    )
    result = _split_segment_on_word_gaps(seg)
    assert result == [{"start": 0.0, "end": 1.2, "text": "Hi there.", "speaker": None}]


def test_real_gap_splits_into_two_segments():
    # Real confirmed case (BACKLOG.md's North Kingstown RI entry): vad_filter=True
    # merged a lone word at 67.5s with real content resuming at 732.8s into one
    # [66.8-735.9] segment. word_timestamps + this gap-split should recover both
    # real, independent timestamp ranges.
    seg = _FakeSegment(
        start=66.8,
        end=735.9,
        text=" So folks, just a quick reminder.",
        words=[
            _FakeWord(67.5, 67.9, " So"),
            _FakeWord(732.8, 733.1, " folks,"),
            _FakeWord(733.1, 733.5, " just"),
            _FakeWord(733.5, 733.8, " a"),
            _FakeWord(733.8, 734.2, " quick"),
            _FakeWord(734.2, 736.2, " reminder."),
        ],
    )
    result = _split_segment_on_word_gaps(seg)
    assert result == [
        {"start": 67.5, "end": 67.9, "text": "So", "speaker": None},
        {
            "start": 732.8,
            "end": 736.2,
            "text": "folks, just a quick reminder.",
            "speaker": None,
        },
    ]


def test_multiple_gaps_produce_multiple_runs():
    seg = _FakeSegment(
        start=0.0,
        end=100.0,
        text=" One. Two. Three.",
        words=[
            _FakeWord(0.0, 1.0, " One."),
            _FakeWord(50.0, 51.0, " Two."),
            _FakeWord(99.0, 100.0, " Three."),
        ],
    )
    result = _split_segment_on_word_gaps(seg)
    assert [r["text"] for r in result] == ["One.", "Two.", "Three."]
    assert [(r["start"], r["end"]) for r in result] == [
        (0.0, 1.0),
        (50.0, 51.0),
        (99.0, 100.0),
    ]


def test_gap_at_or_under_threshold_does_not_split():
    seg = _FakeSegment(
        start=0.0,
        end=5.0,
        text=" Pause... continuing.",
        words=[
            _FakeWord(0.0, 1.0, " Pause..."),
            # Exactly at the 2.0s threshold -- not > threshold, so no split.
            _FakeWord(3.0, 5.0, " continuing."),
        ],
    )
    result = _split_segment_on_word_gaps(seg)
    assert len(result) == 1
    assert result[0]["text"] == "Pause... continuing."


def test_no_words_falls_back_to_segment_span():
    seg = _FakeSegment(start=10.0, end=12.0, text=" Fallback text.", words=None)
    result = _split_segment_on_word_gaps(seg)
    assert result == [
        {"start": 10.0, "end": 12.0, "text": "Fallback text.", "speaker": None}
    ]


def test_blank_text_produces_no_segments():
    seg = _FakeSegment(start=0.0, end=1.0, text="   ", words=[])
    assert _split_segment_on_word_gaps(seg) == []
