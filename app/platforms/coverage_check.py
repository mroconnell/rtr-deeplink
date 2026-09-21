"""WO-923: warn the reader when a transcript covers only part of the video.

The problem: a caption feed can simply stop partway through a meeting and
nothing on the page says so. Measured example (2026-09-20): the Rhode Island
Senate page from Capitol TV (Cablecast) has cues from 22 seconds to about
81 minutes, while its video runs about 149 minutes. The transcript reads as
complete. Before this module nothing compared the last caption time to the
video's own length, except a Granicus-only cue-count check and the Archive's
opportunistic check that only runs when a transcription job is requested
(`archive/db/crud.py`, `_flag_default_transcript_if_truncated_early`).

What this does: after any adapter resolves, if the video's real duration is
known (an adapter set `video_duration_seconds`, or a header-only probe of an
HLS/progressive file answers) and the transcript has cues, compare the last
cue to the duration. If the transcript stops well short, add one plain
warning to `transcript_warnings`.

**The warning reuses the Archive's existing marker on purpose.** The text
contains "may end before the meeting did", which is
`archive/db/crud.py`'s `_EARLY_TRUNCATION_MARKER`. That marker is already
wired into every place a quality marker needs to be (the Python "good
transcript" check, the raw-SQL twin, and the `truncated_transcript`
reporting bucket), so a page carrying this warning is automatically not
counted as having a good transcript and stays eligible for re-transcription.
`tests/test_partial_transcript_marker.py` pins the substring on both sides.
The wording is the same as the Archive's own, so a page flagged here and a
page flagged there read identically.

Threshold, from a measured sample (BACKLOG_DONE.md, WO-923): a transcript is
"partial" only when it covers under 90% of the video AND the uncovered tail
is at least 10 minutes. Real meetings end a little before the video does
(measured gaps of 0 to 5 minutes on 30-minute to 4-hour videos), and a
one-minute clip can be 10% short by a few seconds. Both conditions are
needed: the ratio protects long meetings, the gap protects short clips.

Never guesses a duration. No duration means no check and no warning.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Awaitable, Callable, Optional, Sequence

from .media_probe import is_plausible_meeting_duration, probe_duration
from .models import ResolvedMeeting

logger = logging.getLogger(__name__)

# Must stay a substring of the warning below AND equal to
# archive/db/crud.py's _EARLY_TRUNCATION_MARKER (the resolver cannot import
# from archive/, so tests/test_partial_transcript_marker.py checks the two
# are identical).
PARTIAL_TRANSCRIPT_MARKER = "may end before the meeting did"

PARTIAL_COVERAGE_MAX_RATIO = 0.90
PARTIAL_COVERAGE_MIN_GAP_SECONDS = 600.0

# Header-only probes finish in a second or two; a slow host must never hold
# up a resolve. On timeout there is simply no check.
PROBE_TIMEOUT_SECONDS = 25.0

# Formats a header-only ffprobe can answer for. YouTube/Vimeo/Viebit are
# iframes (no media file to read) and YouTube is never fetched from here.
_PROBEABLE_FORMATS = {"m3u8", "mp4", "mp3", "m4a", "wav"}


def check_enabled() -> bool:
    return os.environ.get("RTR_PARTIAL_TRANSCRIPT_CHECK", "1") != "0"


def last_cue_seconds(segments: Sequence) -> float:
    """Latest cue end (falling back to start) across all cues; 0.0 if none."""
    latest = 0.0
    for s in segments:
        end = getattr(s, "end", None) or getattr(s, "start", None) or 0.0
        latest = max(latest, float(end))
    return latest


def looks_partial(last_cue_s: float, duration_s: Optional[float]) -> bool:
    if not duration_s or duration_s <= 0 or last_cue_s <= 0:
        return False
    if not is_plausible_meeting_duration(duration_s):
        return False
    gap = duration_s - last_cue_s
    return (
        last_cue_s / duration_s < PARTIAL_COVERAGE_MAX_RATIO
        and gap >= PARTIAL_COVERAGE_MIN_GAP_SECONDS
    )


def duration_words(seconds: float, *, attributive: bool = False) -> str:
    """Reads "3 hours 40 minutes", or "3 hour 40 minute" before a noun. Same
    wording as archive/db/crud.py's _duration_words (duplicated because
    the resolver does not import from archive/)."""
    total_minutes = max(1, round(max(0.0, seconds) / 60))
    hours, minutes = divmod(total_minutes, 60)

    def unit(value: int, word: str) -> str:
        if attributive or value == 1:
            return f"{value} {word}"
        return f"{value} {word}s"

    if not hours:
        return unit(minutes, "minute")
    if not minutes:
        return unit(hours, "hour")
    return f"{unit(hours, 'hour')} {unit(minutes, 'minute')}"


def partial_transcript_warning(last_cue_s: float, duration_s: float) -> str:
    return (
        f"This transcript {PARTIAL_TRANSCRIPT_MARKER} — it covers "
        f"about {duration_words(last_cue_s)} of what looks like a "
        f"{duration_words(duration_s, attributive=True)} recording. "
        "The captions stop early at the source."
    )


DurationProbe = Callable[[str, str], Awaitable[Optional[float]]]


async def _default_probe(media_url: str, source_url: str) -> Optional[float]:
    return await asyncio.wait_for(
        probe_duration(media_url, source_page_url=source_url),
        timeout=PROBE_TIMEOUT_SECONDS,
    )


async def flag_partial_transcript(
    result: ResolvedMeeting, *, probe: Optional[DurationProbe] = None
) -> ResolvedMeeting:
    """Add the partial-transcript warning to `result` when warranted.
    Idempotent and never raises: any failure just means no check."""
    try:
        if not check_enabled() or not result.segments or not result.video_url:
            return result
        if any(PARTIAL_TRANSCRIPT_MARKER in w for w in result.transcript_warnings):
            return result
        duration = result.video_duration_seconds
        if duration is None:
            if result.video_format not in _PROBEABLE_FORMATS:
                return result
            duration = await (probe or _default_probe)(
                result.video_url, result.source_url
            )
            if duration is None:
                return result
            result.video_duration_seconds = float(duration)
        last = last_cue_seconds(result.segments)
        if looks_partial(last, duration):
            result.transcript_warnings = [
                *result.transcript_warnings,
                partial_transcript_warning(last, duration),
            ]
    except Exception:  # noqa: BLE001 -- a quality check must never break a resolve
        logger.exception("partial-transcript check failed for %s", result.source_url)
    return result
