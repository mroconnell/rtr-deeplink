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
from typing import Any, Dict, List, Tuple

_HALLUCINATION_REPETITION_MATCH_RATIO = 0.85
_HALLUCINATION_MIN_SEGMENTS_FOR_REPETITION_CHECK = 5

# --- Repetition-run scoring: why this is no longer a whole-meeting ratio ---
#
# The original check divided the longest near-duplicate run by the *total*
# segment count and flagged at >= 0.5. That worked for Port Coquitlam (a
# short 2-chunk meeting whose loop ate 44 of 45 segments) and structurally
# could not work for anything longer: a loop had to consume half the entire
# recording to trip it. Confirmed against six real, live, previously-
# unflagged Archive pages (WO-36, see BACKLOG_DONE.md) -- Cumberland County
# NJ's 41-cue loop is 3.2% of its meeting, Haines City FL's is 1.1%, and
# both are blatant. The fix is to score each *local* run on its own terms.
#
# Every threshold below was set from measurement, not taste: 304 real
# Whisper-transcribed transcripts were pulled from the live Archive
# (/m/<slug>/transcript.srt) alongside the six known-bad ones, and every
# contiguous near-duplicate run in all of them was clustered and inspected.
#
# Two distinct real signatures came out of that, and each gets its own rule.
#
# 1. A TILED BLOCK. Whisper fills a continuous stretch of dead/degenerate
#    audio with one fabricated cue repeated back-to-back, leaving no silence
#    between cues: Haines City FL 6x "You're in the process." at exactly 2.0s
#    per cue over 12s; Lincoln City OR 8x "Yn ymwneud?" over 16s; San Carlos
#    CA 10x "I do not." at exactly 1.0s each. Coverage (summed cue duration
#    over the run's wall-clock span) is ~1.0 for all of them.
#    This is what separates them from a real speech stutter, which the same
#    scan turned up and which must NOT be flagged: Troy NH's 6x "there will
#    be." spans 2.7s at 0.23s per cue (coverage 0.51), Creve Coeur MO's 9x
#    "it's mine." has coverage 0.23, Blackford County IN's 8x "mo." has 0.08
#    -- real words really said, then duplicated, with real pauses left intact.
#    The minimum run length of 6 is the smallest confirmed real case (Haines
#    City); the 10-second floor keeps a fast back-to-back roll call (the
#    highest-risk real shape) out, since the longest *real* contiguous
#    near-duplicate run found anywhere in the 304-transcript corpus was 4
#    ("aye." / "yes." bursts, all under 4 seconds).
#
# 2. A LONG SPARSE RUN. Whisper emits the same phrase over and over across a
#    recess or dead air with real silence between each, so coverage is low
#    but the sheer count is impossible for real speech: Halifax NS 28x
#    "thank you." at a mechanically exact 30.000s cadence across 13.7
#    minutes (coverage 0.34) -- immediately after the chair says "we'll
#    resume at 6 p.m. ... enjoy your meal", i.e. across a dinner recess.
#    Length alone carries this one. 12 is ~3x the longest real run measured
#    (4), and no run between 5 and 11 in the whole corpus turned out to be
#    real speech on inspection -- so the margin is deliberate slack, not a
#    fitted boundary.
_HALLUCINATION_TILED_RUN_LENGTH = 6
_HALLUCINATION_TILED_COVERAGE_RATIO = 0.9
_HALLUCINATION_TILED_MIN_SECONDS = 10.0
_HALLUCINATION_ABSOLUTE_RUN_LENGTH = 12

# Retained only as a backstop for a transcript too short for either rule
# above to apply -- e.g. a 6-segment chunk that is 5x the same line. It is no
# longer the primary signal, and nothing relies on it that the two rules
# above don't already cover (Port Coquitlam's 44-of-45 run trips
# _HALLUCINATION_ABSOLUTE_RUN_LENGTH on its own).
_HALLUCINATION_REPETITION_RUN_RATIO_THRESHOLD = 0.5

# A run of the same character repeated this many times in a row is
# essentially never real transcribed speech (the longest ordinary English
# repeated-character words -- "hmmmm", "nooo" -- top out around 4-5) --
# reported live as a real symptom of this same bug ("long runs of a single
# repeated character"), a well-documented Whisper degenerate-decoding
# failure mode.
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


def _repetition_runs(segments: List[Dict[str, Any]]) -> List[Tuple[int, int]]:
    """Every maximal run of consecutive segments whose normalized texts are
    near-identical, as (start_index, length) pairs. Runs of length 1 are
    included so callers can reason about the whole partition; every run in a
    transcript is returned, not just the longest, because a short *tiled* run
    (see the threshold note above) can sit anywhere inside an otherwise
    healthy meeting and is exactly the case the old longest-run-only scoring
    missed."""
    if not segments:
        return []
    runs: List[Tuple[int, int]] = []
    run_start = 0
    for index in range(1, len(segments)):
        prev_text = _normalize_for_repetition(segments[index - 1].get("text") or "")
        cur_text = _normalize_for_repetition(segments[index].get("text") or "")
        matches = bool(prev_text) and (
            SequenceMatcher(None, prev_text, cur_text).ratio()
            >= _HALLUCINATION_REPETITION_MATCH_RATIO
        )
        if not matches:
            runs.append((run_start, index - run_start))
            run_start = index
    runs.append((run_start, len(segments) - run_start))
    return runs


def _longest_repetition_run(segments: List[Dict[str, Any]]) -> int:
    if len(segments) < 2:
        return 0
    return max(length for _start, length in _repetition_runs(segments))


def _repetition_run_ratio(segments: List[Dict[str, Any]]) -> float:
    """Longest near-duplicate run as a fraction of the total segment count.
    Kept only as the small-transcript backstop described above -- it is no
    longer how a real loop inside a long meeting gets caught."""
    if len(segments) < 2:
        return 0.0
    return _longest_repetition_run(segments) / len(segments)


def _run_span_and_coverage(run: List[Dict[str, Any]]) -> Tuple[float, float]:
    """(wall-clock span, fraction of that span actually covered by the run's
    own cues). Coverage near 1.0 means the cues are laid end-to-end with no
    silence between them -- Whisper tiling a continuous stretch of audio with
    one fabricated line. Returns (0.0, 0.0) when timings are missing or
    non-monotonic, so a caller falls back to length-only reasoning rather
    than trusting a fabricated ratio."""
    try:
        starts = [float(seg["start"]) for seg in run]
        ends = [float(seg["end"]) for seg in run]
    except (KeyError, TypeError, ValueError):
        return (0.0, 0.0)
    span = ends[-1] - starts[0]
    if span <= 0:
        return (0.0, 0.0)
    covered = sum(max(0.0, end - start) for start, end in zip(starts, ends))
    return (span, covered / span)


def _has_hallucinated_repetition_run(segments: List[Dict[str, Any]]) -> bool:
    """True when any single local run of near-identical segments matches one
    of the two real degenerate-decoding signatures documented above -- an
    absolutely long run, or a shorter run that tiles its own span with no
    real silence in it. Deliberately independent of total meeting length:
    that dependence was the bug (WO-36)."""
    for start, length in _repetition_runs(segments):
        if length >= _HALLUCINATION_ABSOLUTE_RUN_LENGTH:
            return True
        if length < _HALLUCINATION_TILED_RUN_LENGTH:
            continue
        span, coverage = _run_span_and_coverage(segments[start : start + length])
        if (
            span >= _HALLUCINATION_TILED_MIN_SECONDS
            and coverage >= _HALLUCINATION_TILED_COVERAGE_RATIO
        ):
            return True
    return False


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
        if (
            _has_hallucinated_repetition_run(segments)
            or _repetition_run_ratio(segments)
            >= _HALLUCINATION_REPETITION_RUN_RATIO_THRESHOLD
        ):
            warnings.append(HALLUCINATION_WARNING)
            return warnings

    if _has_long_character_run(segments):
        warnings.append(HALLUCINATION_WARNING)
        return warnings

    if _non_latin_alpha_ratio(segments) >= _HALLUCINATION_NON_LATIN_RATIO_THRESHOLD:
        warnings.append(HALLUCINATION_WARNING)

    return warnings
