"""Pure, dependency-free chunking/timestamp logic for the transcription
worker -- kept apart from media_probe.py/transcription_engine.py (both have
real I/O and heavy deps) specifically so this stays trivially unit-testable.

Duration-plausibility (MIN/MAX_PLAUSIBLE_MEETING_SECONDS) lives in
app/platforms/media_probe.py instead of here, even though it's equally pure
-- app/main.py's feasibility-check endpoint needs it too, and app/ must
never depend on worker/ (see media_probe.py's own docstring for the
dependency-direction reasoning).
"""

from typing import Any, Dict, List


def shift_segments(segments: List[Dict[str, Any]], offset_seconds: float) -> List[Dict[str, Any]]:
    """Rewrite chunk-relative transcript segments (as returned by the
    transcription engine, timed from 0 at the start of that chunk's audio)
    into full-meeting-relative seconds, by adding the chunk's own start
    offset -- the same convention every adapter's real segments already
    use (see TranscriptSegment in app/platforms/models.py), so the
    frontend's existing seek-by-timestamp logic works unmodified on a
    transcribed transcript.
    """
    return [
        {
            "start": seg["start"] + offset_seconds,
            "end": seg["end"] + offset_seconds,
            "text": seg["text"],
            "speaker": seg.get("speaker"),
        }
        for seg in segments
    ]


def chunk_count(total_duration_seconds: float, chunk_size_seconds: int) -> int:
    """How many fixed-size chunks cover a meeting of this duration -- the
    last chunk is naturally shorter than chunk_size_seconds, callers must
    clamp ffmpeg's -t to the remaining duration on that final chunk."""
    if chunk_size_seconds <= 0:
        raise ValueError("chunk_size_seconds must be positive")
    return max(1, -(-int(total_duration_seconds) // chunk_size_seconds))  # ceil division


def chunk_start(chunk_index: int, chunk_size_seconds: int) -> float:
    return chunk_index * chunk_size_seconds


def chunk_duration(chunk_index: int, chunk_size_seconds: int, total_duration_seconds: float) -> float:
    """Actual duration to extract for this chunk index -- chunk_size_seconds
    for every chunk except the last, which is clamped to what's left."""
    start = chunk_start(chunk_index, chunk_size_seconds)
    return max(0.0, min(chunk_size_seconds, total_duration_seconds - start))
