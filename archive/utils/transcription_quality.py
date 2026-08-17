"""Deliberate duplicate of worker/segment_utils.py's hallucination-detection
logic -- kept in sync manually, same reasoning as archive/utils/language.py's
own duplicate-of-app's-version docstring: the Archive is an independently
deployed service and shouldn't gain a dependency on worker/'s codebase (a
different service, with its own heavy faster-whisper dependency tree) just
for a few small pure functions. Used by archive/db/crud.py's
report_chunk_result() at the point a TranscriptionJob's segments are
finalized into a real TranscriptVersion -- covers both a real user-submitted
transcription and the worker's own idle-time auto-generated jobs in the one
place they both actually finish, without worker/main.py needing to compute
this itself. See worker/segment_utils.py's own "Hallucinated-transcription
detection" note for the full real-data root-cause writeup (Port Coquitlam,
BC, 2025-02-18 Committee of Council Meeting, found live 2026-08-16 -- see
BACKLOG_DONE.md) this was built and tuned against; the logic and thresholds
here must match that copy exactly.
"""

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, List

_HALLUCINATION_REPETITION_RUN_RATIO_THRESHOLD = 0.5
_HALLUCINATION_REPETITION_MATCH_RATIO = 0.85
_HALLUCINATION_MIN_SEGMENTS_FOR_REPETITION_CHECK = 5

_HALLUCINATION_CHAR_RUN_LENGTH = 10
_CHAR_RUN_RE = re.compile(r"(.)\1{" + str(_HALLUCINATION_CHAR_RUN_LENGTH - 1) + r",}")

_HALLUCINATION_NON_LATIN_RATIO_THRESHOLD = 0.15
_HALLUCINATION_MIN_ALPHA_CHARS_FOR_SCRIPT_CHECK = 40

HALLUCINATION_WARNING = (
    "This transcript looks like it may be hallucinated by the transcription "
    "model (not a real transcript of what was said) -- treat it as unreliable. "
    "This can happen when the source audio is unusually quiet, corrupted, or "
    "otherwise hard to transcribe."
)


def _normalize_for_repetition(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _repetition_run_ratio(segments: List[Dict[str, Any]]) -> float:
    if len(segments) < 2:
        return 0.0
    best_run = 1
    current_run = 1
    for prev_seg, cur_seg in zip(segments, segments[1:]):
        prev_text = _normalize_for_repetition(prev_seg["text"])
        cur_text = _normalize_for_repetition(cur_seg["text"])
        if prev_text and SequenceMatcher(None, prev_text, cur_text).ratio() >= _HALLUCINATION_REPETITION_MATCH_RATIO:
            current_run += 1
            best_run = max(best_run, current_run)
        else:
            current_run = 1
    return best_run / len(segments)


def _has_long_character_run(segments: List[Dict[str, Any]]) -> bool:
    sample = "".join(seg["text"] for seg in segments)
    return bool(_CHAR_RUN_RE.search(sample))


def _non_latin_alpha_ratio(segments: List[Dict[str, Any]]) -> float:
    sample = "".join(seg["text"] for seg in segments)
    alpha_chars = [c for c in sample if c.isalpha()]
    if len(alpha_chars) < _HALLUCINATION_MIN_ALPHA_CHARS_FOR_SCRIPT_CHECK:
        return 0.0
    non_latin = sum(1 for c in alpha_chars if "LATIN" not in unicodedata.name(c, ""))
    return non_latin / len(alpha_chars)


def detect_hallucination_warnings(segments: List[Dict[str, Any]]) -> List[str]:
    """See worker/segment_utils.py's identically-named function for the full
    docstring -- this copy must stay logically identical to that one."""
    warnings: List[str] = []

    if len(segments) >= _HALLUCINATION_MIN_SEGMENTS_FOR_REPETITION_CHECK:
        if _repetition_run_ratio(segments) >= _HALLUCINATION_REPETITION_RUN_RATIO_THRESHOLD:
            warnings.append(HALLUCINATION_WARNING)
            return warnings

    if _has_long_character_run(segments):
        warnings.append(HALLUCINATION_WARNING)
        return warnings

    if _non_latin_alpha_ratio(segments) >= _HALLUCINATION_NON_LATIN_RATIO_THRESHOLD:
        warnings.append(HALLUCINATION_WARNING)

    return warnings
