"""Pure, dependency-free chunking/timestamp logic for the transcription
worker -- kept apart from media_probe.py/transcription_engine.py (both have
real I/O and heavy deps) specifically so this stays trivially unit-testable.

Duration-plausibility (MIN/MAX_PLAUSIBLE_MEETING_SECONDS) lives in
app/platforms/media_probe.py instead of here, even though it's equally pure
-- app/main.py's feasibility-check endpoint needs it too, and app/ must
never depend on worker/ (see media_probe.py's own docstring for the
dependency-direction reasoning).
"""

import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, List, Tuple


def shift_segments(
    segments: List[Dict[str, Any]], offset_seconds: float
) -> List[Dict[str, Any]]:
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
    return max(
        1, -(-int(total_duration_seconds) // chunk_size_seconds)
    )  # ceil division


def chunk_start(chunk_index: int, chunk_size_seconds: int) -> float:
    return chunk_index * chunk_size_seconds


def chunk_duration(
    chunk_index: int, chunk_size_seconds: int, total_duration_seconds: float
) -> float:
    """Actual duration to extract for this chunk index -- chunk_size_seconds
    for every chunk except the last, which is clamped to what's left."""
    start = chunk_start(chunk_index, chunk_size_seconds)
    return max(0.0, min(chunk_size_seconds, total_duration_seconds - start))


# --- Seam-duplication dedup -------------------------------------------------
#
# Real, confirmed bug (Boulder County, CO, 2026-02-05 Historic Preservation
# Advisory Board meeting, found live 2026-08-16 -- see BACKLOG_DONE.md):
# every chunk boundary of a multi-chunk transcription could restate a chunk's
# last sentence at the start of the next chunk, e.g.
#   [14:56] ...this whole question about truck caro, which may actually
#           predate the Bracero program.
#   [15:00] Um, there's an exhibit at the.
#   [15:08] This whole question about truck caro, which may actually
#           predate the Bracero program, there's an exhibit at the
#           Colorado Railroad Museum, so down in Golden...
#
# Root-caused by directly diffing real audio, not assumed: extract_chunk_
# audio()'s fast/input-side `-ss` seek (see its own docstring) is exact for
# a direct file -- ffmpeg just does an HTTP Range fetch -- but for an HLS
# source it snaps to the start of the nearest PRECEDING .ts segment rather
# than the exact requested second, since that's the only unit HLS can seek
# to without downloading and decoding everything before it (accurate/
# output-side `-ss` *does* land on the right second, confirmed by directly
# comparing both against this real meeting's actual HLS playlist, but reads
# the entire preceding stream to get there -- ~31MB vs. ~1.6MB for the fast
# path on this one chunk alone, and that cost only grows with how far into
# the meeting the chunk starts, which would silently turn every later
# chunk of a long meeting into a near-full re-download; not an acceptable
# trade for exact timestamps at a chunk seam, see this module's own design
# note above about chunk boundaries not needing frame accuracy). Confirmed
# concretely for this meeting: requesting `-ss 900` actually starts reading
# audio from ~887.8s (the real content there, verified by transcribing the
# fast extraction and a frame-accurate extraction of the same window and
# comparing) -- about 12-17 real seconds of the previous chunk's tail gets
# re-transcribed at the head of the next one.
#
# The fix is a dedup pass, not a seek-accuracy fix -- HLS segment length
# (and therefore the exact overlap size) varies per source, so trimming a
# fixed number of seconds off every chunk wouldn't be reliable, but two
# independent Whisper decodes of the same real speech reliably agree on
# the *words*, just not on exact segment boundaries, punctuation, or
# casing between the two decodes (confirmed by the real example above:
# "truck caro...program." vs "truck caro...program, there's..." -- same
# words, different sentence-boundary guess). A word-level match anchored
# at the actual seam (not just a shared phrase anywhere in the lookback
# window) is what actually generalizes here.

_WORD_RE = re.compile(r"[a-z0-9']+")

# A short shared phrase ("thank you", "okay", a repeated filler word) is
# real, ordinary speech, not a seam-duplicate artifact -- this threshold is
# tuned against the real, confirmed Boulder County case above (an 18-word
# overlapping run), not derived from a survey of many real overlaps yet.
# If a real overlap this small (or smaller) ever gets missed because of it,
# that's a real gap for BACKLOG.md, not a hypothetical one.
MIN_SEAM_OVERLAP_WORDS = 6

# Bounds the cost of the SequenceMatcher call and keeps a coincidental
# match somewhere in the middle of a long chunk out of consideration --
# only the last/first few segments are ever candidates for a seam overlap.
_LOOKBACK_SEGMENTS = 8


def _segment_words(
    segments: List[Dict[str, Any]],
) -> Tuple[List[str], List[Tuple[int, int, int]]]:
    """(flat lowercase word list, [(segment_index, first_word_pos,
    last_word_pos_exclusive), ...]) for a lookback window of segments --
    lets the caller map a word-level match position back onto whole
    segments without ever slicing a segment's text mid-sentence."""
    words: List[str] = []
    spans: List[Tuple[int, int, int]] = []
    pos = 0
    for i, seg in enumerate(segments):
        seg_words = _WORD_RE.findall(seg["text"].lower())
        spans.append((i, pos, pos + len(seg_words)))
        words.extend(seg_words)
        pos += len(seg_words)
    return words, spans


# A real overlap window, once found, is "close enough" to count as the
# same underlying speech even though it came from two independent Whisper
# decodes -- tuned against the real Boulder County case, whose true overlap
# (prev's tail literally has an extra "Um" the new chunk's decode doesn't
# have) scores ~0.89-0.92 on this scale; a coincidental short shared phrase
# ("thank you very much" appearing on both sides of an otherwise unrelated
# boundary, tested in tests/test_worker_segment_utils.py) tops out around
# 0.57-0.67, comfortably below this.
_SEAM_MATCH_RATIO_THRESHOLD = 0.7


def _find_seam_overlap_word_count(prev_words: List[str], new_words: List[str]) -> int:
    """How many trailing words of `prev_words` are a near-duplicate of
    that many leading words of `new_words` -- tried from the largest
    plausible window down to MIN_SEAM_OVERLAP_WORDS, returning the first
    (largest) one that clears _SEAM_MATCH_RATIO_THRESHOLD. Window-based
    (not SequenceMatcher.get_matching_blocks() over the *whole* word
    lists) specifically so a single non-matching filler word inside the
    real overlap -- the confirmed Boulder County case has prev's decode
    saying "...program. Um, there's an exhibit..." where the new chunk's
    independent decode of the same audio has no "Um" at all -- doesn't
    split what's really one continuous duplicate into two separate blocks
    that each individually look too small/off-position to trust.
    """
    limit = min(len(prev_words), len(new_words), _LOOKBACK_SEGMENTS * 20)
    for n in range(limit, MIN_SEAM_OVERLAP_WORDS - 1, -1):
        ratio = SequenceMatcher(
            None, prev_words[-n:], new_words[:n], autojunk=False
        ).ratio()
        if ratio >= _SEAM_MATCH_RATIO_THRESHOLD:
            return n
    return 0


def count_seam_overlap_segments(
    previous_segments: List[Dict[str, Any]], new_segments: List[Dict[str, Any]]
) -> int:
    """How many segments at the END of `previous_segments` are a real,
    near-duplicate restatement of content at the START of `new_segments`
    -- see this module's own "Seam-duplication dedup" note above for the
    confirmed root cause. Returns 0 (the safe default -- nothing gets
    dropped) whenever no confident match is found, which is also exactly
    what happens for a non-HLS source, where this seek is already
    accurate and there's nothing to deduplicate.

    Callers: worker/main.py persists `partial_segments` chunk-by-chunk via
    a DB append (report_chunk_result()), so it can't cheaply hold the
    whole accumulated list in memory to re-slice -- it calls this
    directly and asks report_chunk_result() to drop this many trailing
    entries before appending the new chunk's segments.
    scripts/transcribe_backlog_locally.py holds the full list in memory
    already, so it uses merge_chunk_segments() below instead.
    """
    if not previous_segments or not new_segments:
        return 0

    prev_tail = previous_segments[-_LOOKBACK_SEGMENTS:]
    new_head = new_segments[:_LOOKBACK_SEGMENTS]
    prev_words, prev_spans = _segment_words(prev_tail)
    new_words, _new_spans = _segment_words(new_head)
    if (
        len(prev_words) < MIN_SEAM_OVERLAP_WORDS
        or len(new_words) < MIN_SEAM_OVERLAP_WORDS
    ):
        return 0

    overlap_word_count = _find_seam_overlap_word_count(prev_words, new_words)
    if not overlap_word_count:
        return 0

    overlap_start_word = len(prev_words) - overlap_word_count
    tail_len = len(prev_tail)
    for seg_idx, _start, end in prev_spans:
        # Drop every prev-tail segment that has ANY words inside the
        # matched overlap range, not just the ones entirely inside it --
        # erring toward dropping a couple of genuinely-unique words right
        # at that segment's edge is a far smaller cost than leaving a
        # visibly duplicated sentence behind.
        if end > overlap_start_word:
            return tail_len - seg_idx
    return 0


def merge_chunk_segments(
    previous_segments: List[Dict[str, Any]], new_segments: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Convenience wrapper for a caller that already holds the full
    accumulated segment list in memory -- trims `previous_segments`' own
    duplicated tail (if any, see count_seam_overlap_segments()) and
    appends `new_segments` in full. `new_segments` is never trimmed --
    the later chunk's version of the overlapping content is consistently
    the more complete one in the real case this was built from (the
    earlier chunk's audio simply stopped mid-sentence at the chunk
    boundary; the later chunk's didn't)."""
    drop = count_seam_overlap_segments(previous_segments, new_segments)
    kept_prev = (
        previous_segments[: len(previous_segments) - drop]
        if drop
        else previous_segments
    )
    return [*kept_prev, *new_segments]


# --- Hallucinated-transcription detection -----------------------------------
#
# Real, confirmed bug (Port Coquitlam, BC, 2025-02-18 Committee of Council
# Meeting, found live 2026-08-16 -- see BACKLOG_DONE.md): a real backlog
# meeting's transcript came back as complete hallucinated gibberish -- a
# chaotic mix of Telugu, Sinhala, random Unicode symbol spam, nonsense
# English ("Did you ever see your mom will never wake up at the bus stop?"),
# and long runs of a single repeated character, with the whole transcript's
# detected language pushed as "te" (Telugu) for a Canadian English-language
# meeting. Root-caused by directly diffing real audio, not assumed: the
# source's left/right stereo channels are near-exact phase-inverted copies
# of each other, so extract_chunk_audio()'s plain mono downmix (`-ac 1`, an
# average of the two channels) destructively cancels the real signal into
# near-silent noise -- see app/platforms/media_probe.py's own docstring for
# the full writeup and its now-fixed extraction-side fallback. faster-
# whisper hallucinates on that kind of near-silent/noise input rather than
# recognizing there's nothing real to transcribe -- a well-documented
# Whisper failure mode, not unique to this one meeting, and not guaranteed
# to always be caused by (or fixed by) the same phase-cancellation mechanism
# -- a genuinely corrupted stream, wrong media entirely, or another source
# defect could trigger the same symptom. This is that second, independent
# safety net: even with the extraction-side fix, nothing previously checked
# a *Whisper-produced* transcript for exactly this kind of garbage before
# push -- the scraped-caption ingest path has had `is_likely_garbled()`
# (app/utils/vtt_parser.py) for this since early on; this Whisper-specific
# path had no equivalent at all.
#
# Reproduced directly against this same real meeting's real (pre-fix) audio
# while investigating: a "tiny"-model transcription of its second chunk
# produced one exact sentence ("So, we are going to take a look at what we
# are going to do.") repeated verbatim across 40 of 45 total segments -- a
# 0.89 repetition-run ratio. Every real clean transcript checked (this same
# meeting's own post-fix transcription, and Boulder County CO from the
# seam-duplication investigation) has no run longer than 2. That two-
# transcript sample was later widened to 304 real Archive transcripts for
# WO-36 -- see the threshold note below; the conclusion held (the longest
# run in any of them that was genuinely real speech was 4).

# The near-duplicate *matching* primitive: two consecutive segments count as
# a repeat when their normalized texts score at least this on
# SequenceMatcher. Unchanged since the original Port Coquitlam fix and
# re-confirmed against every case below -- it correctly tolerates the minor
# variation real degenerate decoding produces ("no, I don't pick anybody." ->
# "I don't pick anybody."), and it is *not* what was broken.
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

# Fraction of alphabetic characters outside the Latin script -- catches the
# real Telugu/Sinhala degeneration reported live on this same broken audio.
# Latin-script alphabetic characters include accented forms (é, ñ, ü, ...),
# so a legitimate French/Spanish transcript (real content already live on
# this Archive, e.g. a Spanish-language LA USD board meeting) isn't
# penalized -- only a substantially non-Latin transcript is.
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
    """Heuristic quality check on a Whisper-produced transcript's segments
    -- flags likely-hallucinated content so a caller can warn rather than
    presenting it at face value, the same role `is_likely_garbled()`
    (app/utils/vtt_parser.py) already plays for scraped captions. Not a
    guarantee, same honesty as that function's own docstring: a heuristic
    tuned against the real confirmed case above, not proof against every
    possible hallucination shape. Returns a list (usually empty) rather
    than a bool so a caller can fold the result straight into
    `transcript_warnings` the same way every adapter's own
    `is_likely_garbled()` check already does.
    """
    warnings: List[str] = []

    if len(segments) >= _HALLUCINATION_MIN_SEGMENTS_FOR_REPETITION_CHECK:
        if (
            _has_hallucinated_repetition_run(segments)
            or _repetition_run_ratio(segments)
            >= _HALLUCINATION_REPETITION_RUN_RATIO_THRESHOLD
        ):
            warnings.append(HALLUCINATION_WARNING)
            return (
                warnings  # one real warning is enough; no need to stack near-duplicates
            )

    if _has_long_character_run(segments):
        warnings.append(HALLUCINATION_WARNING)
        return warnings

    if _non_latin_alpha_ratio(segments) >= _HALLUCINATION_NON_LATIN_RATIO_THRESHOLD:
        warnings.append(HALLUCINATION_WARNING)

    return warnings
