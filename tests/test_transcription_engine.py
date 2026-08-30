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


# --- FasterWhisperEngine language passthrough -------------------------------
#
# Synthetic (a faked faster_whisper module, since the real one downloads
# model weights on construction): exercises only the plumbing between
# FasterWhisperEngine(language=...) and model.transcribe(language=...),
# added for scripts/transcribe_backlog_locally.py's --language flag (the
# Kitchener misdetection re-run -- see BACKLOG_DONE.md's WO-36 audit
# entry). The real transcription behavior of forcing a language is
# faster-whisper's own, not covered here.


class _FakeWhisperModel:
    def __init__(self, *args, **kwargs):
        self.transcribe_kwargs: List[dict] = []

    def transcribe(self, path, **kwargs):
        self.transcribe_kwargs.append(kwargs)
        return iter([]), None


def _engine_with_fake_model(monkeypatch, **engine_kwargs):
    import sys
    import types

    from worker.transcription_engine import FasterWhisperEngine

    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel = _FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    return FasterWhisperEngine(**engine_kwargs)


def test_forced_language_reaches_the_transcribe_call(monkeypatch, tmp_path):
    engine = _engine_with_fake_model(monkeypatch, language="en")
    engine._transcribe_sync(tmp_path / "chunk.wav")
    assert engine._model.transcribe_kwargs[0]["language"] == "en"


def test_default_stays_auto_detect(monkeypatch, tmp_path):
    # worker/main.py never passes language= -- the cloud worker must keep
    # faster-whisper's own auto-detection (language=None) unchanged.
    engine = _engine_with_fake_model(monkeypatch)
    engine._transcribe_sync(tmp_path / "chunk.wav")
    assert engine._model.transcribe_kwargs[0]["language"] is None
