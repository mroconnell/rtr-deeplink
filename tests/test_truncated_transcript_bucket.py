"""The `truncated_transcript` reporting bucket and its markers.

The bucket shipped 2026-08-23 with no coverage at all. It is worth some,
because it is load-bearing in two directions at once: a warning listed in
`_TRUNCATION_MARKERS` decides how a page is *reported* on /coverage
(`_classify_page_outcome`) **and** whether the page is still eligible for
a real transcription attempt (`_has_real_warning_free_transcript`, whose
raw-SQL twin is covered in tests/test_transcription_jobs.py). A marker
wired into one and not the other produces the worst outcome available:
a page that reports as a known problem and is permanently excluded from
ever being fixed.

The label wording is asserted too. It named Granicus until 2026-08-24,
which was wrong for a bucket that is meant to hold every form of
truncation -- a reader seeing a platform in the label reasonably assumes
every page under it is that platform's.
"""

from archive.db.crud import (
    _GRANICUS_TRUNCATION_MARKER,
    _OUTCOME_LABELS,
    _OUTCOME_RANK,
    _TRUNCATION_MARKERS,
    _classify_page_outcome,
)

# The real wording app/platforms/granicus.py emits, copied rather than
# imported (archive/ does not import from app/ -- see crud.py's own note
# on the deliberately duplicated outcome buckets). If the adapter's
# wording drifts away from the marker substring, this is what catches it.
_REAL_GRANICUS_WARNING = (
    "This transcript may be cut off — it hit exactly "
    "36,000 lines, a known limit in Granicus's own "
    "captioning for very long meetings."
)


def _classify(warnings):
    return _classify_page_outcome(
        video_url="https://example.com/v.m3u8",
        agenda_items=[],
        default_content_hash="a" * 64,
        default_transcript_warnings=warnings,
        default_transcript_language="en",
    )


def test_the_real_granicus_warning_lands_in_the_truncated_bucket():
    assert _classify([_REAL_GRANICUS_WARNING]) == "truncated_transcript"


def test_every_truncation_marker_classifies_and_gates():
    """The invariant a new marker must not break: listed in
    _TRUNCATION_MARKERS means both 'reported as truncated' and 'not a
    good transcript'."""
    from archive.db.crud import _has_real_warning_free_transcript

    for marker in _TRUNCATION_MARKERS:
        warning = f"Heads up: {marker} and so on."
        assert _classify([warning]) == "truncated_transcript", marker
        assert not _has_real_warning_free_transcript([warning]), marker


def test_the_granicus_marker_is_a_substring_of_what_the_adapter_writes():
    assert _GRANICUS_TRUNCATION_MARKER in _REAL_GRANICUS_WARNING


def test_the_label_names_no_platform():
    # Renamed 2026-08-24: the Granicus 36,000-cue cap is the first
    # detected form of truncation, not the only one that exists.
    label = _OUTCOME_LABELS["truncated_transcript"]
    assert label == "Truncated transcript"
    assert "granicus" not in label.lower()


def test_every_bucket_has_a_label_and_a_rank():
    # Cheap guard on the pairing: a bucket added to one dict and not the
    # other either renders as a raw key or sorts unpredictably.
    assert set(_OUTCOME_LABELS) == set(_OUTCOME_RANK)


def test_a_garbled_warning_still_outranks_truncation():
    # Both markers on one page: garbled wins, because "the content is
    # wrong" is a worse answer for a reader than "some content is
    # missing" -- the ordering the two buckets were split over.
    outcome = _classify([_REAL_GRANICUS_WARNING, "looks garbled at the source"])
    assert outcome == "garbled_transcript"


def test_the_backfill_script_writes_a_warning_the_classifier_recognises():
    """scripts/scan_truncated_transcripts.py marks legacy pages that hit
    the cap before the adapter started flagging it. A mark the gate can't
    see would be worse than no mark -- the page would look handled and
    stay excluded from re-transcription anyway."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "scripts"
    spec = importlib.util.spec_from_file_location(
        "scan_truncated_transcripts", path / "scan_truncated_transcripts.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert module.TRUNCATION_WARNING == _REAL_GRANICUS_WARNING
    assert _classify([module.TRUNCATION_WARNING]) == "truncated_transcript"
    assert module.GRANICUS_CUE_CAP == 36000
