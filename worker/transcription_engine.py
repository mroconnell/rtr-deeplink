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
            str(audio_path), beam_size=5, initial_prompt=MEETING_VOCABULARY_PROMPT
        )
        return [
            {"start": seg.start, "end": seg.end, "text": seg.text.strip(), "speaker": None}
            for seg in segments
            if seg.text.strip()
        ]


def build_default_engine() -> TranscriptionEngine:
    return FasterWhisperEngine()
