"""Tests for scripts/fetch_youtube_transcripts.py's snippet-to-segment
conversion -- the pure part of the local fetcher (the YouTube fetch itself
is lazy-imported and only ever runs from a residential IP, see the
script's own docstring).
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from fetch_youtube_transcripts import snippets_to_segments  # noqa: E402


def _snippet(text, start, duration=2.0):
    return SimpleNamespace(text=text, start=start, duration=duration)


def test_converts_start_duration_to_start_end():
    segments = snippets_to_segments([_snippet("Hello there, everyone.", 10.0, 3.5)])
    assert segments == [{"start": 10.0, "end": 13.5, "text": "Hello there, everyone."}]


def test_drops_blank_padding_snippets():
    # Real CC1 tracks contain whitespace-only snippets as timing padding
    # (confirmed on a real Minneapolis video: the first snippet is ' ').
    segments = snippets_to_segments([
        _snippet(" ", 17.9),
        _snippet("Real text here.", 18.1),
    ])
    assert len(segments) == 1
    assert segments[0]["text"] == "Real text here."


def test_replaces_leading_speaker_marker_with_site_convention():
    # A real ">>" character here, unlike the literal "&gt;&gt;" entity
    # text normalize_speaker_change_marker() handles in raw VTT files.
    segments = snippets_to_segments([_snippet(">> All right. It is 1:35 and we are ready to begin.", 18.1)])
    assert segments[0]["text"].startswith("» All right.")


def test_mid_text_marker_left_alone():
    segments = snippets_to_segments([_snippet("He said >> pointing at the sign.", 5.0)])
    assert segments[0]["text"] == "He said >> pointing at the sign."


def test_all_caps_track_gets_deshouted():
    # Human-typed CC tracks are commonly ALL CAPS -- reuses the existing
    # normalize_shouting_caption() (needs a real sample of letters to
    # trigger, so give it enough text).
    segments = snippets_to_segments([
        _snippet(">> ALL RIGHT. IT IS ONE THIRTY FIVE AND WE ARE READY TO GET STARTED.", 18.1),
        _snippet("MADAM CLERK PLEASE CALL THE ROLL FOR ALL MEMBERS PRESENT TODAY.", 23.1),
    ])
    joined = " ".join(seg["text"] for seg in segments)
    assert joined != joined.upper()
    assert "» All right." in segments[0]["text"]


def test_normal_case_track_left_alone():
    segments = snippets_to_segments([
        _snippet("The meeting will now come to order, please stand for the pledge of allegiance.", 0.0),
    ])
    assert segments[0]["text"] == "The meeting will now come to order, please stand for the pledge of allegiance."
