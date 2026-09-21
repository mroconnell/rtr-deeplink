"""WO-935: a transcript made by OUR OWN transcription gets the same
"may end before the meeting did" warning a source-caption transcript gets.

The shared function under test is
`app.platforms.coverage_check.own_transcript_early_end_warning()`. Both
transcription paths call it: the cloud worker's finish step
(`archive/db/crud.py`, `report_chunk_result()`) and
`scripts/transcribe_backlog_locally.py`. Tests of each call site live next
to the other tests of that code (`test_transcription_jobs.py`,
`test_transcribe_backlog_locally.py`); this file pins the rule itself.

Real numbers, measured 2026-09-21 from the public site and the videos'
own playlists (header-only ffprobe), not invented:

* Leon Valley TX show 179 (page 1676, "Crime Control and Prevention Board"):
  4,541 cues, last cue at 5:34:53.18 (20,093.18 s); the video is
  23,399.666 s. Ratio 0.859, 55 minutes uncovered. This is the page
  BACKLOG.md names.
* Leon Valley TX show 185 (2026-07-21 regular meeting): our own Whisper is
  the shown version ("English (transcribed)"), 2,494 cues, last cue at
  3:16:24.4 (11,784.4 s); the video is 21,599.933 s (a round 6:00:00
  recording window). Ratio 0.546.
* Leon Valley TX 2025-06-19 special meeting: 2,139 cues, last cue at
  2:23:50.94 (8,630.94 s); the video is 8,632.648 s. Ratio 0.9998. (Its
  transcript's source, captions or Whisper, was not established: the page
  has one version and shows no label. The rule does not depend on it.)

**What is NOT confirmed, and the reason the first two are here.** Audio
sampled after the last cue of the first two (30 s samples, volume only,
nothing transcribed) is SILENT: show 179 reads -38 dB (speech) at 20,050 s
and -83 dB from 20,500 s to the end; show 185 reads -22 dB at 11,750 s and
-71 dB from 12,500 s to the end. So both flags are a recording with dead air
after the meeting, not a cut transcript. The rule cannot tell the two apart
and does not try (BACKLOG_PHASES.md, rule 3); the tests pin that behaviour so
a later change is a deliberate one.
"""

import pytest

from app.platforms.coverage_check import (
    PARTIAL_TRANSCRIPT_MARKER,
    last_cue_seconds,
    own_transcript_early_end_warning,
)
from app.platforms.models import TranscriptSegment
from archive.db import crud


@pytest.fixture(autouse=True)
def _check_on(monkeypatch):
    # tests/conftest.py switches the check off suite-wide; this file tests it.
    monkeypatch.setenv("RTR_PARTIAL_TRANSCRIPT_CHECK", "1")


def _own_cues(last_end: float) -> list[dict]:
    """The shape our own transcription stores: plain dicts."""
    return [
        {"start": 583.73, "end": 586.61, "text": "For example, I thought", "speaker": None},
        {"start": last_end - 1.6, "end": last_end, "text": "Thank you.", "speaker": None},
    ]  # fmt: skip


def test_page_1676_is_flagged_at_the_real_numbers():
    warning = own_transcript_early_end_warning(_own_cues(20_093.18), 23_399.666)
    assert warning is not None
    assert PARTIAL_TRANSCRIPT_MARKER in warning
    assert "5 hours 35 minutes" in warning
    assert "6 hour 30 minute recording" in warning


def test_leon_valley_show_185_is_flagged_and_that_is_the_known_false_positive_shape():
    # Flagged by the rule. The audio after 12,500 s is silent (-71 dB), so
    # this is trailing dead air in a fixed 6-hour window, not a cut
    # transcript -- pinned so the limitation is explicit, not rediscovered.
    warning = own_transcript_early_end_warning(_own_cues(11_784.4), 21_599.933)
    assert warning is not None and "3 hours 16 minutes" in warning


def test_a_transcript_that_reaches_the_end_of_its_video_is_not_flagged():
    assert own_transcript_early_end_warning(_own_cues(8_630.94), 8_632.648) is None


@pytest.mark.parametrize(
    "last, duration, expected",
    [
        (20_093.18, 23_399.666, True),  # Leon Valley show 179, ratio 0.859
        (11_784.4, 21_599.933, True),  # Leon Valley show 185, ratio 0.546
        (8_630.94, 8_632.648, False),  # Leon Valley 2025-06-19, ratio 0.9998
        (0.9598 * 4692.0, 4692.0, False),  # real Swagit case (WO-923): 3 min gap
        (0.8945 * 3600.0, 3600.0, False),  # WO-923's real ratio 0.8945, 6.3 min gap
        (54.0, 66.0, False),  # short clip: 82% but only a 12 s gap
        (3000.0, 3300.0, False),  # 90.9%: above the ratio line
        (3600.0 - 599.0, 3600.0, False),  # 83.4% but 599 s: one second under the floor
        (3600.0 - 601.0, 3600.0, True),  # 83.3% and 601 s uncovered
    ],
)
def test_same_threshold_as_wo923_both_conditions_needed(last, duration, expected):
    assert (
        own_transcript_early_end_warning(_own_cues(last), duration) is not None
    ) is expected


@pytest.mark.parametrize("duration", [None, 0, 0.0, -5.0])
def test_a_missing_or_nonsense_length_is_unmeasurable_not_flagged(duration):
    assert own_transcript_early_end_warning(_own_cues(1000.0), duration) is None


def test_an_implausibly_long_length_is_not_flagged():
    # Over the 14 hour ceiling a "duration" is more likely a garbage stream
    # than a real recording -- WO-923's own guard, inherited.
    assert own_transcript_early_end_warning(_own_cues(10.0), 30 * 3600.0) is None


def test_no_cues_is_not_flagged():
    assert own_transcript_early_end_warning([], 23_399.666) is None


def test_only_the_last_cue_is_compared_never_gaps_inside_the_transcript():
    # A 3-hour silence in the MIDDLE (skipped by the voice filter) with the
    # last cue at the very end must not be flagged.
    cues = [
        {"start": 10.0, "end": 20.0, "text": "Call to order."},
        {"start": 11_000.0, "end": 11_010.0, "text": "Back on the record."},
        {"start": 14_390.0, "end": 14_398.0, "text": "Adjourned."},
    ]
    assert own_transcript_early_end_warning(cues, 14_400.0) is None


def test_cue_objects_and_plain_dicts_read_the_same():
    as_objects = [TranscriptSegment(start=1.0, end=20_093.18, text="x")]
    as_dicts = [{"start": 1.0, "end": 20_093.18, "text": "x"}]
    assert last_cue_seconds(as_objects) == last_cue_seconds(as_dicts) == 20_093.18
    assert own_transcript_early_end_warning(
        as_objects, 23_399.666
    ) == own_transcript_early_end_warning(as_dicts, 23_399.666)


def test_the_check_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("RTR_PARTIAL_TRANSCRIPT_CHECK", "0")
    assert own_transcript_early_end_warning(_own_cues(20_093.18), 23_399.666) is None


# -- it reuses the existing marker; nothing new is wired anywhere ----------


def test_the_warning_uses_the_archives_existing_marker_and_wording():
    last, duration = 20_093.18, 23_399.666
    warning = own_transcript_early_end_warning(_own_cues(last), duration)
    assert crud._EARLY_TRUNCATION_MARKER in warning
    # The Archive's own job-creation wording, character for character:
    # crud._flag_default_transcript_if_truncated_early() writes this.
    assert warning == (
        "This transcript may end before the meeting did — it covers "
        f"about {crud._duration_words(last)} of what looks like a "
        f"{crud._duration_words(duration, attributive=True)} recording."
    )
    # And it must not claim the captions stop "at the source": these are
    # our own cues.
    assert "at the source" not in warning


def test_the_warning_makes_the_archive_treat_the_page_as_truncated():
    warnings = [own_transcript_early_end_warning(_own_cues(20_093.18), 23_399.666)]
    # Not a "good transcript" any more (the Python check)...
    assert crud._has_real_warning_free_transcript(warnings) is False
    # ...and reported as truncated, not lumped into another bucket.
    assert (
        crud._classify_page_outcome(
            video_url="https://example.com/v.m3u8",
            agenda_items=[],
            default_content_hash="x",
            default_transcript_warnings=warnings,
            default_transcript_language="en",
        )
        == "truncated_transcript"
    )


def test_both_transcription_paths_use_the_one_shared_function():
    """The point of putting the check in one place: the cloud path and the
    local script cannot drift, as the two copies of
    detect_hallucination_warnings() already can."""
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import transcribe_backlog_locally as tbl

    assert crud.own_transcript_early_end_warning is own_transcript_early_end_warning
    assert tbl.own_transcript_early_end_warning is own_transcript_early_end_warning
