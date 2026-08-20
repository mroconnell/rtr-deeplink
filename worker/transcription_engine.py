"""Speech-to-text engine used by the transcription worker.

A small interface (`TranscriptionEngine`) so the concrete implementation
is swappable later without touching worker/main.py's job loop. v1 default
is self-hosted `faster-whisper` (CPU, CTranslate2-based) rather than a
hosted API -- the worker is already a persistent paid process, so this
avoids a second, per-minute-metered vendor on top of it, and it's the same
base WhisperX later builds real diarization on top of (via
pyannote.audio), so this choice doesn't need revisiting to add that --
just extending. No diarization in v1: every segment's `speaker` stays
None.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List

# Whisper's initial_prompt biases decoding toward this vocabulary --
# real motivation: a live job on a Cupertino meeting (2026-08-08)
# transcribed "this meeting is adjourned" as "this meeting is a joke",
# a meaning-changing error, not a cosmetic one (see BACKLOG.md). Applied
# fresh to every chunk (not just the first), since each chunk is its own
# transcribe() call -- keeps it short and representative rather than a
# full script, since an overly long/suggestive prompt risks the model
# leaning on it past where it's actually relevant.
MEETING_VOCABULARY_PROMPT = (
    "Local government meeting. Common terms: roll call, public comment, "
    "motion, second, aye, nay, abstain, quorum, agenda item, ordinance, "
    "resolution, city council, public hearing, minutes, adjourned."
)

# How large a gap between two consecutive words' real timestamps has to be
# before it's treated as a genuine VAD-skipped silence rather than ordinary
# word-to-word spacing within one continuous utterance -- see
# _split_segment_on_word_gaps()'s own docstring for why this exists at all.
# Tuned against the real North Kingstown RI case (BACKLOG.md's "Fix
# approach prototyped and empirically validated 2026-08-18" entry):
# confirmed hidden gaps of 25s/83s/668s at real VAD-skip boundaries,
# comfortably clear of normal intra-sentence pauses.
_WORD_GAP_SPLIT_SECONDS = 2.0


def _split_segment_on_word_gaps(seg: Any) -> List[Dict[str, Any]]:
    """faster-whisper's vad_filter=True (see FasterWhisperEngine's own
    docstring for why it's on) fixes hallucination-on-silence, but has its
    own confirmed real bug: it can silently merge two genuinely separate
    real speech bursts, on either side of a VAD-skipped silent stretch,
    into one reported segment -- correct *text*, wildly wrong *timestamp
    range* (real case: a lone word ("So") at 67.5s and real content
    resuming at 732.8s reported as one [66.8s-735.9s] segment). Since this
    app's entire product is deep-linking to an exact timestamp, a wrong
    segment boundary is worse than a missing one.

    Re-splits using the model's own real per-word timestamps
    (word_timestamps=True on the transcribe() call) instead of trusting
    segment.start/segment.end, wherever two consecutive words are further
    apart than _WORD_GAP_SPLIT_SECONDS. `seg.words` is a list of Word
    objects (start, end, word -- word already carries its own leading
    space from the tokenizer, hence "".join() below rather than " ".join()
    -- matches how faster-whisper reconstructs segment.text internally).
    """
    words = list(getattr(seg, "words", None) or [])
    if not words:
        text = seg.text.strip()
        return (
            [{"start": seg.start, "end": seg.end, "text": text, "speaker": None}]
            if text
            else []
        )

    runs: List[List[Any]] = [[words[0]]]
    for prev_word, word in zip(words, words[1:]):
        if word.start - prev_word.end > _WORD_GAP_SPLIT_SECONDS:
            runs.append([])
        runs[-1].append(word)

    result = []
    for run in runs:
        text = "".join(w.word for w in run).strip()
        if text:
            result.append(
                {
                    "start": run[0].start,
                    "end": run[-1].end,
                    "text": text,
                    "speaker": None,
                }
            )
    return result


class TranscriptionEngine(ABC):
    @abstractmethod
    async def transcribe_chunk(self, audio_path: Path) -> List[Dict[str, Any]]:
        """Returns chunk-relative segments ({start, end, text}, seconds
        from 0 at this chunk's own start) -- caller shifts them to
        full-meeting-relative via segment_utils.shift_segments()."""
        raise NotImplementedError


class FasterWhisperEngine(TranscriptionEngine):
    """Loads the model once at construction (worker/main.py instantiates
    this a single time at process startup, reused across every job's every
    chunk) -- reloading a multi-GB-class model per chunk would dominate
    runtime otherwise.

    `model_size` favors speed/memory over chasing the largest/most-accurate
    model: per the product framing behind this feature, most viewers want
    to Ctrl-F to a topic in an otherwise-uncaptioned meeting, not a
    publication-grade transcript. Originally defaulted to "small", but the
    first real deploy OOM-killed on Render's `starter` worker plan (512MB)
    loading it -- confirmed live 2026-08-08, not a hypothetical concern.
    Measured peak RSS locally (isolated venv matching worker/requirements.txt
    exactly, one model per process): "tiny" ~382MB, "base" ~489MB, against a
    67MB baseline with no model loaded at all. "base" was tried first but
    rejected -- only ~23MB of headroom under 512MB locally is too close to
    trust once Render's real container overhead and a different CPU
    architecture are added on top. "tiny" is the real default, with real
    margin (~130MB). Revisit upward only alongside a plan upgrade with
    actual RAM to spare, not by guessing again. `compute_type="int8"` keeps
    CPU memory/time reasonable without a GPU, at some accuracy cost versus
    float16/float32.

    **`vad_filter=True` (Silero VAD), added 2026-08-18 after BACKLOG.md's
    "Fix approach prototyped and empirically validated" entry.** Root
    cause of a confirmed real hallucination pattern (Hermosa Beach,
    Moraine City OH, North Kingstown RI, Redwood City CA and others --
    see that entry and BACKLOG_DONE.md): decoding fixed-length windows
    over genuine dead air/pre-meeting silence with no speech-activity
    gate produces fabricated text once per window (the repeated "Local
    government meeting..."/"Music"/foreign-script loops that pattern),
    not a lower-quality-but-real transcript. `vad_filter=True` is a real
    speech-vs-non-speech classifier (not a volume threshold), so it also
    catches loud-but-non-speech audio (a musical intro), not just literal
    silence -- confirmed live to correctly return zero segments (and run
    ~7x faster, since it skips decoding non-speech at all) on clips that
    previously fabricated content. `condition_on_previous_text=False` is
    defense-in-depth against a hallucination cascading into the next
    window once it starts (confirmed live *not* the cause of the bug
    below, on its own).

    `vad_filter=True` has its own confirmed real bug, independent of the
    fix above: it can silently merge two genuinely separate real speech
    bursts either side of a VAD-skipped silent stretch into one reported
    segment -- correct text, wildly wrong timestamp span (real case: a
    lone word at 67.5s and real content resuming at 732.8s reported as
    one [66.8s-735.9s] segment). Since this app's entire product is
    deep-linking to an exact timestamp, a wrong boundary is worse than a
    missing one -- `word_timestamps=True` plus
    `_split_segment_on_word_gaps()` below fixes this by re-splitting on
    the model's own real per-word timestamps instead of trusting
    `segment.start`/`segment.end`. See that function's own docstring for
    the full validated case.
    """

    def __init__(self, model_size: str = "tiny", compute_type: str = "int8"):
        # Imported lazily so importing this module (e.g. from tests) never
        # requires the real model weights to be downloaded/available.
        from faster_whisper import WhisperModel

        self._model = WhisperModel(model_size, device="cpu", compute_type=compute_type)

    async def transcribe_chunk(self, audio_path: Path) -> List[Dict[str, Any]]:
        import asyncio

        return await asyncio.to_thread(self._transcribe_sync, audio_path)

    def _transcribe_sync(self, audio_path: Path) -> List[Dict[str, Any]]:
        segments, _info = self._model.transcribe(
            str(audio_path),
            beam_size=5,
            initial_prompt=MEETING_VOCABULARY_PROMPT,
            vad_filter=True,
            word_timestamps=True,
            condition_on_previous_text=False,
        )
        result: List[Dict[str, Any]] = []
        for seg in segments:
            result.extend(_split_segment_on_word_gaps(seg))
        return result


def build_default_engine() -> TranscriptionEngine:
    return FasterWhisperEngine()
