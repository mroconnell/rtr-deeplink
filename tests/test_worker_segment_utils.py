import re
from pathlib import Path

import pytest

from worker.segment_utils import (
    _HALLUCINATION_ABSOLUTE_RUN_LENGTH,
    _HALLUCINATION_REPETITION_RUN_RATIO_THRESHOLD,
    _HALLUCINATION_TILED_RUN_LENGTH,
    _has_hallucinated_repetition_run,
    _longest_repetition_run,
    chunk_count,
    chunk_duration,
    chunk_start,
    count_seam_overlap_segments,
    detect_hallucination_warnings,
    merge_chunk_segments,
    shift_segments,
)


def test_shift_segments_chunk_zero_is_identity():
    segments = [{"start": 0.0, "end": 2.5, "text": "Hello."}]
    assert shift_segments(segments, 0.0) == [
        {"start": 0.0, "end": 2.5, "text": "Hello.", "speaker": None}
    ]


def test_shift_segments_offsets_later_chunks():
    # A chunk starting at real time 900s (chunk index 1 at 900s chunks):
    # a cue at 5.0-7.5s within that chunk's own audio must land at
    # 905.0-907.5s in the full-meeting timeline the video player seeks by.
    segments = [{"start": 5.0, "end": 7.5, "text": "Second chunk cue."}]
    assert shift_segments(segments, 900.0) == [
        {"start": 905.0, "end": 907.5, "text": "Second chunk cue.", "speaker": None}
    ]


def test_shift_segments_preserves_speaker_when_present():
    segments = [{"start": 1.0, "end": 2.0, "text": "Hi.", "speaker": "Speaker 1"}]
    assert shift_segments(segments, 10.0)[0]["speaker"] == "Speaker 1"


def test_shift_segments_zero_length_segment():
    segments = [{"start": 3.0, "end": 3.0, "text": ""}]
    result = shift_segments(segments, 100.0)
    assert result[0]["start"] == result[0]["end"] == 103.0


def test_chunk_count_exact_multiple():
    assert chunk_count(1800, 900) == 2


def test_chunk_count_rounds_up():
    assert chunk_count(1801, 900) == 3
    assert chunk_count(1, 900) == 1


def test_chunk_count_rejects_non_positive_size():
    import pytest

    with pytest.raises(ValueError):
        chunk_count(100, 0)


def test_chunk_start_and_duration_normal_chunk():
    assert chunk_start(2, 900) == 1800
    assert chunk_duration(2, 900, total_duration_seconds=5000) == 900


def test_chunk_duration_clamps_final_chunk():
    # 1900s total, 900s chunks -> chunk 2 starts at 1800s, only 100s remain.
    assert chunk_duration(2, 900, total_duration_seconds=1900) == 100


def test_chunk_duration_never_negative_past_the_end():
    assert chunk_duration(5, 900, total_duration_seconds=1900) == 0.0


# --- Seam-duplication dedup -------------------------------------------------
#
# Real, confirmed bug: extract_chunk_audio()'s fast/input-side ffmpeg `-ss`
# seek snaps to the nearest preceding HLS segment boundary rather than the
# exact requested second, so a chunk boundary can restate several real
# seconds of the previous chunk's tail. Found live 2026-08-16 against a real
# production meeting (Boulder County, CO -- bouldercounty-2026-02-05-
# historic-preservation-advisory-board, an eScribe/HLS meeting), root-caused
# by directly diffing real extracted audio (see worker/segment_utils.py's
# "Seam-duplication dedup" note and BACKLOG_DONE.md), not assumed. The two
# text fixtures below are both real, not invented:
#
# (1) `_REAL_PRODUCTION_*` is the exact text this bug produced on the live
#     page, quoted verbatim from that investigation.
# (2) `_REAL_WHISPER_*` is what a direct faster-whisper "tiny" transcription
#     of this same meeting's real audio produced when this fix was built --
#     extracted straight from the meeting's real HLS source (both a fast/
#     input-side extraction, matching what production actually runs, and an
#     accurate/output-side one used to confirm the fast extraction's audio
#     really did start ~17s early) -- not hand-written text standing in for
#     real transcription output.


def test_count_seam_overlap_detects_real_production_duplicate():
    # Verbatim from the real, live Boulder County page before this fix.
    previous_segments = [
        {
            "start": 896.0,
            "end": 899.5,
            "text": "...this whole question about truck caro, which may actually predate the Bracero program.",
        },
        {"start": 900.0, "end": 900.9, "text": "Um, there's an exhibit at the."},
    ]
    new_segments = [
        {
            "start": 908.0,
            "end": 918.7,
            "text": "This whole question about truck caro, which may actually predate the Bracero program, there's an exhibit at the Colorado Railroad Museum, so down in Golden...",
        },
    ]
    assert count_seam_overlap_segments(previous_segments, new_segments) == 2

    merged = merge_chunk_segments(previous_segments, new_segments)
    assert (
        merged == new_segments
    )  # both duplicate prev segments dropped, new kept in full


def test_count_seam_overlap_detects_real_whisper_output():
    # A real faster-whisper "tiny" transcription of the Boulder County
    # meeting's actual audio around this same 900s chunk boundary, produced
    # while investigating this bug: ground-truth (accurately-seeked) content
    # just before the true 900s mark, vs. what extract_chunk_audio()'s real
    # fast/input-side `-ss 900` extraction actually contained -- confirmed
    # to start ~12-17s earlier than requested. Segmented differently by the
    # two independent decodes (a real property of Whisper, not simulated),
    # which is exactly why this dedup works at word granularity, not by
    # comparing whole-segment text for equality.
    previous_segments = [
        {
            "start": 883.36,
            "end": 889.04,
            "text": "and I think there may be a tie to what Larry brought up previously, is just this whole question",
        },
        {
            "start": 889.04,
            "end": 899.5,
            "text": "about Tracero, which may actually predate the Bracero program.",
        },
    ]
    new_segments = [
        {
            "start": 900.0,
            "end": 909.04,
            "text": "whole question about Tracero, which may actually predate the Bracero program, there's an",
        },
        {
            "start": 909.04,
            "end": 918.72,
            "text": "exhibit at the Colorado Railroad Museum, so down in Golden apparently it's going to be available",
        },
        {"start": 918.72, "end": 920.72, "text": "until August, so it's..."},
    ]
    drop = count_seam_overlap_segments(previous_segments, new_segments)
    assert drop == 2  # both previous segments are inside the matched overlap

    merged = merge_chunk_segments(previous_segments, new_segments)
    assert merged == new_segments


def test_count_seam_overlap_ignores_genuinely_different_content():
    # Real chunk boundaries where consecutive chunks talk about different
    # things shouldn't lose anything -- this is the default/expected case
    # for the vast majority of chunk boundaries (a direct-file source with
    # no seek imprecision at all, or an HLS source where the boundary
    # happens to land exactly on a segment edge).
    previous_segments = [
        {
            "start": 895.0,
            "end": 900.0,
            "text": "Thank you, Commissioner, that concludes the staff report.",
        },
    ]
    new_segments = [
        {
            "start": 900.0,
            "end": 905.0,
            "text": "Moving on to item four B on tonight's agenda.",
        },
    ]
    assert count_seam_overlap_segments(previous_segments, new_segments) == 0
    assert merge_chunk_segments(previous_segments, new_segments) == [
        *previous_segments,
        *new_segments,
    ]


def test_count_seam_overlap_ignores_short_coincidental_phrases():
    # A short, ordinary shared phrase ("thank you very much") is real
    # speech, not a seam-duplicate artifact -- must not trigger a drop.
    previous_segments = [
        {"start": 895.0, "end": 900.0, "text": "Okay, thank you very much for that."},
    ]
    new_segments = [
        {
            "start": 900.0,
            "end": 905.0,
            "text": "Thank you very much, next we'll hear from the applicant.",
        },
    ]
    assert count_seam_overlap_segments(previous_segments, new_segments) == 0


def test_count_seam_overlap_empty_inputs_are_safe():
    assert count_seam_overlap_segments([], []) == 0
    assert count_seam_overlap_segments([], [{"start": 0, "end": 1, "text": "hi"}]) == 0
    assert count_seam_overlap_segments([{"start": 0, "end": 1, "text": "hi"}], []) == 0


def test_merge_chunk_segments_no_overlap_is_plain_concatenation():
    previous_segments = [{"start": 0.0, "end": 2.0, "text": "First chunk."}]
    new_segments = [{"start": 900.0, "end": 902.0, "text": "Second chunk."}]
    assert merge_chunk_segments(previous_segments, new_segments) == [
        *previous_segments,
        *new_segments,
    ]


# --- Hallucinated-transcription detection -----------------------------------
#
# Real, confirmed bug: Port Coquitlam, BC, 2025-02-18 Committee of Council
# Meeting, found live 2026-08-16 (see BACKLOG_DONE.md and this module's own
# "Hallucinated-transcription detection" note above). Root cause: the
# source's near-exact phase-inverted stereo channels destructively cancel
# under extract_chunk_audio()'s plain mono downmix, feeding faster-whisper
# near-silent noise it then hallucinates on.


def _repeated_segment(start: float, text: str, *, step: float = 10.0) -> dict:
    return {"start": start, "end": start + step, "text": text}


# Directly reproduced against this real meeting's real (pre-fix) audio while
# investigating this bug: a "tiny"-model transcription of chunk 2 (900-1572s)
# returned exactly 45 segments -- one real, distinct opening segment, then
# the same sentence verbatim 44 times in a row through the rest of the
# chunk. First 10 and last 10 segments were individually captured and are
# reproduced verbatim below; the ones between (same text, same ~10s
# cadence, not separately re-printed at the time) are reconstructed at the
# same cadence -- the run length (44 of 45) is what was directly observed,
# not estimated.
_REAL_HALLUCINATED_REPETITION_SEGMENTS = [
    {
        "start": 0.0,
        "end": 30.0,
        "text": "Public comment, motion, second, aye, nay, abstain,",
    },
] + [
    _repeated_segment(
        start, "So, we are going to take a look at what we are going to do."
    )
    for start in [240.0, 250.0, 260.0, *range(270, 665, 10)]
][:44]

# Real, directly quoted from the coordinator's own real production run
# (a bigger model against this same broken audio) -- semantic-nonsense
# hallucination this heuristic doesn't try to catch (that would need a
# real language-model judge, out of scope for a cheap structural check);
# included so a reader can see what this detector deliberately does *not*
# claim to catch, not as a expected-positive fixture.
_REAL_QUOTED_NONSENSE_ENGLISH = [
    {
        "start": 0.0,
        "end": 4.0,
        "text": "Did you ever see your mom will never wake up at the bus stop?",
    },
    {
        "start": 4.0,
        "end": 8.0,
        "text": "Lord of Evil, saint of heaven, Lord God of peace!",
    },
]

# Real, from directly re-transcribing this same meeting's real audio after
# the phase-cancellation fix (left channel instead of the cancelled mono
# downmix) -- a genuinely clean, coherent real transcript, used as a
# false-positive check.
_REAL_CLEAN_PORT_COQUITLAM_SEGMENTS = [
    {
        "start": 300.0,
        "end": 309.52,
        "text": "Councillor Garling. Sorry, I'm confused now. So there is an access point off of Ogovi, and the drawing",
    },
    {
        "start": 309.52,
        "end": 315.36,
        "text": "it says, there's not. So there would be access for, say, if, like, someone were delivering or",
    },
    {
        "start": 315.36,
        "end": 318.56,
        "text": "for firefighting, you know, someone could, could access through, like, you know, like,",
    },
    {
        "start": 318.56,
        "end": 322.80,
        "text": "that's supposed to be a fence or a gate or something, but a driveway access would be off of that",
    },
    {
        "start": 322.80,
        "end": 328.40,
        "text": "lane portion to the off of Hastings. So I'm, I'm, I'm not in favor of this at all. I,",
    },
    {
        "start": 328.40,
        "end": 334.08,
        "text": "I just, I don't know why we would. I get it's an unopened portion, um, but if you were, if you've",
    },
    {
        "start": 334.08,
        "end": 338.72,
        "text": "walked that, which I just did on the weekend, it literally is in between two houses, and it",
    },
    {
        "start": 338.72,
        "end": 343.12,
        "text": "goes onto a super busy area, which including a telephone pole, right in the middle. We'd have",
    },
    {
        "start": 343.12,
        "end": 348.96,
        "text": "to move the telephone over the end with. That's one thing. But it, it, it, that lane when, in essence,",
    },
    {
        "start": 348.96,
        "end": 354.40,
        "text": "go right between two people and dump onto what is already a busy Hastings street. So, um,",
    },
    {
        "start": 354.40,
        "end": 359.84,
        "text": "I'm not sure why we would put it to a point where we would access that lane.",
    },
]

# Boulder County CO, from the seam-duplication investigation -- another
# real, independently-confirmed clean transcript from a different meeting
# entirely, a second false-positive check.
_REAL_CLEAN_BOULDER_COUNTY_SEGMENTS = [
    {"start": 862.12, "end": 864.12, "text": "Of a mental health inquiry."},
    {
        "start": 864.12,
        "end": 869.12,
        "text": "And just how difficult it can be to be away from home to be without a.",
    },
    {"start": 869.12, "end": 871.12, "text": "A social network to support you."},
    {
        "start": 871.12,
        "end": 873.12,
        "text": "And it was a it was a fascinating presentation.",
    },
    {"start": 873.12, "end": 874.12, "text": "And I."},
    {
        "start": 874.12,
        "end": 878.12,
        "text": "And you know, kiddos to her and her effort.",
    },
    {
        "start": 900.00,
        "end": 908.96,
        "text": "This whole question about tricharro, which may actually predate the preserro program, there's",
    },
    {
        "start": 908.96,
        "end": 918.12,
        "text": "an exhibit at the Colorado Railroad Museum, so down in Golden. Apparently, it's going to be",
    },
]

# Synthetic (real script, not real production output -- the coordinator's
# report described this symptom categorically, "Telugu, Sinhala, random
# Unicode symbol spam," but the literal characters produced weren't quoted
# verbatim) -- real Telugu and Sinhala words, not fabricated glyphs, to
# verify the non-Latin-script signal actually trips on the reported shape
# of the real symptom. Marked synthetic per this repo's own convention:
# what's unconfirmed is whether *this exact text* is what Whisper produced,
# not whether Telugu/Sinhala script triggers the check.
_SYNTHETIC_NON_LATIN_SEGMENTS = [
    {"start": 0.0, "end": 5.0, "text": "నమస్కారం మీరు ఎలా ఉన్నారు ఈ రోజు వాతావరణం చాలా బాగుంది"},
    {"start": 5.0, "end": 10.0, "text": "ආයුබෝවන් ඔබට කොහොමද අද කාලගුණය ඉතා හොඳයි ස්තූතියි"},
    {
        "start": 10.0,
        "end": 15.0,
        "text": "ఇది నిజంగా ఒక అద్భుతమైన సమావేశం మరియు మేము చాలా సంతోషిస్తున్నాము",
    },
]

# Synthetic (a plausible shape for the reported "long runs of a single
# repeated character" symptom, not the literal reported output) -- marked
# synthetic for the same reason as above.
_SYNTHETIC_CHAR_RUN_SEGMENTS = [
    {
        "start": 0.0,
        "end": 5.0,
        "text": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    },
]


def test_detect_hallucination_warnings_flags_real_repetition_loop():
    warnings = detect_hallucination_warnings(_REAL_HALLUCINATED_REPETITION_SEGMENTS)
    assert warnings


def test_detect_hallucination_warnings_flags_synthetic_non_latin_script():
    warnings = detect_hallucination_warnings(_SYNTHETIC_NON_LATIN_SEGMENTS)
    assert warnings


def test_detect_hallucination_warnings_flags_synthetic_long_character_run():
    warnings = detect_hallucination_warnings(_SYNTHETIC_CHAR_RUN_SEGMENTS)
    assert warnings


def test_detect_hallucination_warnings_no_false_positive_on_real_clean_transcripts():
    assert detect_hallucination_warnings(_REAL_CLEAN_PORT_COQUITLAM_SEGMENTS) == []
    assert detect_hallucination_warnings(_REAL_CLEAN_BOULDER_COUNTY_SEGMENTS) == []


def test_detect_hallucination_warnings_empty_and_short_input_are_safe():
    assert detect_hallucination_warnings([]) == []
    assert (
        detect_hallucination_warnings([{"start": 0.0, "end": 1.0, "text": "Hi."}]) == []
    )


def test_detect_hallucination_warnings_does_not_claim_to_catch_semantic_nonsense():
    # Honest documentation of a real limit, not a bug: coherent-looking but
    # semantically nonsensical English (the coordinator's own real quoted
    # example) needs a language-model judge to catch, not a cheap
    # structural heuristic -- this test exists so that limitation is
    # explicit and intentional, not silently assumed to be covered.
    assert detect_hallucination_warnings(_REAL_QUOTED_NONSENSE_ENGLISH) == []


# --- Repetition dilution (WO-36) ---------------------------------------------
#
# The repetition check used to divide the longest near-duplicate run by the
# *whole meeting's* segment count and flag at >= 0.5, so a real, blatant
# hallucination loop inside a long meeting mathematically could not be
# caught. Fixtures below are real fetched Archive transcript exports, sliced
# to the loop plus real surrounding cues -- see
# tests/fixtures/hallucination_runs/README.md for provenance.

_HALLUCINATION_FIXTURES = Path(__file__).parent / "fixtures" / "hallucination_runs"

_SRT_TIMING_RE = re.compile(
    r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)"
)


def _load_srt_fixture(name: str) -> list:
    blocks = re.split(
        r"\n\s*\n", (_HALLUCINATION_FIXTURES / name).read_text(encoding="utf-8").strip()
    )
    segments = []
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if len(lines) < 3:
            continue
        match = _SRT_TIMING_RE.match(lines[1])
        assert match, lines[1]
        h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(g) for g in match.groups())
        segments.append(
            {
                "start": h1 * 3600 + m1 * 60 + s1 + ms1 / 1000,
                "end": h2 * 3600 + m2 * 60 + s2 + ms2 / 1000,
                "text": " ".join(lines[2:]),
            }
        )
    assert segments, name
    return segments


# (fixture, longest run, that meeting's real total cue count). The run/total
# figures were measured against the full live exports, not these excerpts --
# every one is far below the old 0.5 threshold, which is the bug.
_REAL_UNDETECTED_LOOPS = [
    ("loop_hermosa_beach_ca.srt", 176, 3764),
    ("loop_moraine_city_oh.srt", 93, 241),
    ("loop_north_kingstown_ri.srt", 80, 210),
    ("loop_cumberland_county_nj.srt", 41, 1291),
    ("loop_haines_city_fl.srt", 6, 525),
    ("loop_lincoln_city_or.srt", 8, 637),
]


@pytest.mark.parametrize("name,run_length,meeting_cues", _REAL_UNDETECTED_LOOPS)
def test_old_whole_meeting_ratio_could_not_have_caught_these(
    name, run_length, meeting_cues
):
    # The regression itself, stated as arithmetic on the real meetings' real
    # cue counts: none of the six could ever reach 0.5, no matter how blatant
    # the loop, because the divisor was the entire meeting.
    assert run_length / meeting_cues < _HALLUCINATION_REPETITION_RUN_RATIO_THRESHOLD


@pytest.mark.parametrize("name,run_length,meeting_cues", _REAL_UNDETECTED_LOOPS)
def test_detect_hallucination_warnings_flags_real_local_loops(
    name, run_length, meeting_cues
):
    segments = _load_srt_fixture(name)
    assert _longest_repetition_run(segments) == run_length
    assert detect_hallucination_warnings(segments)


# Real speech from real meetings that must stay clean. The first three are
# genuine decoder stutters -- words that really were said, then duplicated,
# with real pauses left between the cues -- and the last two are real roll
# calls. Note two of the stutters have runs of 8 and 9, longer than Haines
# City's flagged 6: run length alone cannot separate these, which is why the
# short-run rule also requires the run to tile its own span.
_REAL_CLEAN_REPETITION_FIXTURES = [
    "stutter_troy_nh.srt",
    "stutter_creve_coeur_mo.srt",
    "stutter_blackford_county_in.srt",
    "rollcall_coweta_county_ga.srt",
    "rollcall_bentonville_ar.srt",
]


@pytest.mark.parametrize("name", _REAL_CLEAN_REPETITION_FIXTURES)
def test_detect_hallucination_warnings_ignores_real_repetition(name):
    assert detect_hallucination_warnings(_load_srt_fixture(name)) == []


def test_halifax_recess_is_a_real_loop_not_the_false_positive_backlog_claimed():
    # BACKLOG.md's false-positive caution named Halifax's 28 repeated "thank
    # you"s as legitimate -- "a chair thanking distinct public commenters over
    # a real 13-minute comment period". Pulling the real export disproved that
    # (WO-36): the 28 cues are consecutive with no other content between them,
    # on an exact 30.000s cadence, and the cue immediately before them is the
    # chair announcing a dinner recess. This test pins the evidence so the
    # claim doesn't get re-adopted.
    segments = _load_srt_fixture("recess_halifax_ns.srt")
    assert "enjoy your meal" in segments[7]["text"].lower()
    assert {seg["text"].strip().lower() for seg in segments[8:36]} == {"thank you."}
    cadence = {
        round(b["start"] - a["start"], 3)
        for a, b in zip(segments[8:36], segments[9:36])
    }
    assert cadence == {30.0}
    assert detect_hallucination_warnings(segments)


def test_tiled_short_run_needs_both_length_and_gapless_timing():
    # Synthetic, deliberately: it isolates the two halves of the short-run
    # rule one at a time, which no single real transcript does. The shape (one
    # repeated line every 2.0s) is taken from the real Haines City fixture
    # above -- that is where the cadence and the phrasing come from; only the
    # coverage and the run length are varied here.
    text = "You're in the process."
    tiled = [
        {"start": 2.0 * i, "end": 2.0 * i + 2.0, "text": text}
        for i in range(_HALLUCINATION_TILED_RUN_LENGTH)
    ]
    assert _has_hallucinated_repetition_run(tiled)

    # Same run length, same span, but each cue is a short utterance with real
    # silence after it -- the real-stutter shape, which must not flag.
    sparse = [
        {"start": 2.0 * i, "end": 2.0 * i + 0.3, "text": text}
        for i in range(_HALLUCINATION_TILED_RUN_LENGTH)
    ]
    assert not _has_hallucinated_repetition_run(sparse)

    # Gapless, but one cue short of the minimum run length.
    assert not _has_hallucinated_repetition_run(
        tiled[: _HALLUCINATION_TILED_RUN_LENGTH - 1]
    )


def test_long_run_flags_even_when_sparse_and_untimed():
    # Synthetic: the Halifax fixture above is the real instance of a long
    # sparse run, and this covers the degenerate variant of it -- segments
    # carrying no usable timings at all, where coverage is unknowable and only
    # run length is left to reason from. Not yet seen in real worker output
    # (every real path fills start/end), so this pins the intended fallback
    # rather than a confirmed case.
    untimed = [
        {"text": "Thank you."} for _ in range(_HALLUCINATION_ABSOLUTE_RUN_LENGTH)
    ]
    assert _has_hallucinated_repetition_run(untimed)
    assert not _has_hallucinated_repetition_run(
        untimed[: _HALLUCINATION_ABSOLUTE_RUN_LENGTH - 1]
    )


@pytest.mark.parametrize(
    "name",
    [name for name, _run, _total in _REAL_UNDETECTED_LOOPS]
    + _REAL_CLEAN_REPETITION_FIXTURES
    + ["recess_halifax_ns.srt"],
)
def test_archive_duplicate_agrees_with_worker_on_every_real_fixture(name):
    # archive/utils/transcription_quality.py is a deliberate hand-synced copy
    # of this logic (see its own docstring for why the Archive must not depend
    # on worker/). Nothing enforced that they stayed identical; a hand-synced
    # duplicate that silently drifts is the whole risk of the pattern, so pin
    # it against every real fixture rather than trusting the convention.
    from archive.utils.transcription_quality import (
        detect_hallucination_warnings as archive_detect,
    )

    segments = _load_srt_fixture(name)
    assert archive_detect(segments) == detect_hallucination_warnings(segments)
