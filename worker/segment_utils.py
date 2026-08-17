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
from difflib import SequenceMatcher
from typing import Any, Dict, List, Tuple


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


def _segment_words(segments: List[Dict[str, Any]]) -> Tuple[List[str], List[Tuple[int, int, int]]]:
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
        ratio = SequenceMatcher(None, prev_words[-n:], new_words[:n], autojunk=False).ratio()
        if ratio >= _SEAM_MATCH_RATIO_THRESHOLD:
            return n
    return 0


def count_seam_overlap_segments(previous_segments: List[Dict[str, Any]], new_segments: List[Dict[str, Any]]) -> int:
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
    if len(prev_words) < MIN_SEAM_OVERLAP_WORDS or len(new_words) < MIN_SEAM_OVERLAP_WORDS:
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
    kept_prev = previous_segments[: len(previous_segments) - drop] if drop else previous_segments
    return [*kept_prev, *new_segments]
