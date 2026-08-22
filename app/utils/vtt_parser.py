import html
import re
import xml.etree.ElementTree as ET
from typing import Iterable, List, Dict, Any, Optional

from langdetect import DetectorFactory, detect as _detect_language, LangDetectException

# langdetect samples n-grams at random and is non-deterministic unless seeded
# (its own README says so). That was survivable while detection was a single
# call on one decisive sample, but detect_language_from_texts() now votes
# across many chunks, and on a genuinely garbled transcript the individual
# chunks are each a coin flip -- measured on the real Fountain Valley clip
# 607 fixture, an unseeded vote came back 'en' 36 times, 'pt' 3 and 'ca' 1
# over 40 runs of identical input. Seeding makes the same transcript always
# get the same label, which is what a cache-and-republish pipeline needs.
DetectorFactory.seed = 0


def decode_vtt_bytes(raw: bytes) -> str:
    """Decode a fetched VTT file's raw bytes to text.

    Most captions are UTF-8, but some real caption files are not (confirmed
    live: Simi Valley Granicus clip 2840's Spanish-language captions.vtt is
    not valid UTF-8 and raises UnicodeDecodeError on strict decode). Fall
    back to Windows-1252 (a superset of Latin-1 that also covers the common
    Word-style punctuation vendors sometimes emit) and, failing that,
    replace undecodable bytes rather than losing the whole transcript.
    """
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("windows-1252")
    except UnicodeDecodeError:
        return raw.decode("utf-8", errors="replace")


_TIMESTAMP_LINE_RE = re.compile(
    r"(\d{2}:\d{2}:\d{2}[\.\,]\d{3}) --> ((\d{2}:\d{2}:\d{2}[\.\,]\d{3}).*)"
)


def parse_vtt(content: str) -> List[Dict[str, Any]]:
    """Parse WebVTT content into a list of cue dicts with 'start', 'end', 'text'.

    Ported from rtr-transcripts/app/utils/vtt_parser.py (unchanged — this part
    already worked correctly in testing).
    """
    content = content.lstrip("﻿")
    lines = content.splitlines()
    n = len(lines)

    cues = []
    current_cue = None

    i = 0
    while i < n:
        line = lines[i].strip()

        if not line or line == "WEBVTT":
            i += 1
            continue

        # A WebVTT NOTE (comment) block -- per the spec (section 4.3), the
        # keyword is "NOTE" alone or followed by whitespace, and the block
        # runs through any continuation lines up to the next blank line.
        # Real example: a Tavares FL CivicClerk BCC meeting stores segments
        # with literal `NOTE Confidence: 0.962116034285714` lines alternating
        # with real cue text -- without this check, parse_vtt had no
        # special-case for a NOTE line and silently absorbed it as text onto
        # whatever cue was open.
        if line == "NOTE" or line.startswith("NOTE ") or line.startswith("NOTE\t"):
            i += 1
            while i < n and lines[i].strip():
                i += 1
            continue

        timestamp_match = _TIMESTAMP_LINE_RE.match(line)

        if timestamp_match:
            if current_cue:
                cues.append(current_cue)

            start, end_line = timestamp_match.groups()[:2]
            end = end_line.split(" ", 1)[0]

            current_cue = {
                "start": _parse_timestamp(start),
                "end": _parse_timestamp(end),
                "text": "",
            }
            i += 1
            continue

        # A standalone cue-identifier line -- WebVTT's spec (section 4.1)
        # allows an optional line immediately before the timestamp line,
        # the same convention SRT uses for its numbering. Confirmed live
        # on a real Bakersfield, CA eScribe/iSiLIVE meeting: every cue was
        # numbered this way, and without this check each number was
        # silently absorbed as trailing text onto the *previous* cue
        # ("...City Council\n2", "...pleasure to\n3", ...). Detected by
        # lookahead -- only actually an identifier if the very next line
        # is a real timestamp line, not just any short line that happens
        # to be genuine cue text.
        next_line = lines[i + 1].strip() if i + 1 < n else ""
        if _TIMESTAMP_LINE_RE.match(next_line):
            i += 1
            continue

        if current_cue is not None:
            if current_cue["text"]:
                current_cue["text"] += "\n" + line
            else:
                current_cue["text"] = line
        i += 1

    if current_cue:
        cues.append(current_cue)

    # Inline WebVTT tags (voice tags like <v.Male.spk3 Speaker2>, but also
    # <c>, <b>, <i>, timestamp tags, etc.) are never valid transcript text --
    # strip them here rather than leaving that only to dedupe_rollup_cues()/
    # strip_unknown_caption_markup(), neither of which runs on this path.
    # Real example: a platform="unknown" meeting (Orange County FL, via
    # generic_fallback.py -> parse_vtt()) has raw `<v.Male.spk3 Speaker2>`
    # tags inline in its real, currently-live captions.vtt files (confirmed
    # live 2026-08-17: otv.ocfl.net's real VTT output for a July 2026 BCC
    # budget session has 1098 such tags). Reuses the same _TAG_RE already
    # defined below in this file for dedupe_rollup_cues().
    for cue in cues:
        cue["text"] = _TAG_RE.sub("", cue["text"])

    normalize_shouting_caption(cues)
    normalize_speaker_change_marker(cues)
    unescape_caption_entities(cues)
    return cues


def parse_srt(content: str) -> List[Dict[str, Any]]:
    """Parse SRT content into the same cue-dict shape as parse_vtt.

    SRT differs from WebVTT only in that each cue is preceded by a
    standalone sequence-number line (e.g. "1", "2", ...) and has no
    "WEBVTT" header -- feeding raw SRT text into parse_vtt directly is
    unsafe, not just formally wrong: once the first cue is open,
    parse_vtt's loop has no way to recognize a later sequence-number line
    as anything other than more cue text (it only recognizes timestamp
    lines and blank lines specially), so every cue after the first ends up
    with the next cue's index number silently appended to its end.
    Confirmed via a real caption file (Emporia, KS, CivicClerk event 585,
    3677 real cues) -- stripping sequence-number lines first, then
    reusing parse_vtt, produces clean output with no corruption.
    """
    stripped = re.sub(r"(?m)^\d+\r?\n(?=\d{2}:\d{2}:\d{2}[,.]\d{3} -->)", "", content)
    return parse_vtt(stripped)


def _ttml_time_to_seconds(value: Optional[str]) -> Optional[float]:
    """Convert a TTML/DFXP timeExpression to seconds.

    Only handles the two forms an actual web captioning vendor is likely
    to emit: clock-time ("HH:MM:SS.mmm", comma decimal tolerated too) and
    offset-time in seconds/milliseconds ("1.5s" / "1500ms") -- these are
    what professional captioning vendors (3Play, Rev, Verbit, etc.)
    typically use for web delivery, per the TTML spec's own examples.
    Frame-based ("40f") or tick-based ("2t") expressions need a frame
    rate/tick rate this function has no way to know, so those return None
    -- callers skip a cue it can't time rather than guess a rate.
    """
    if not value:
        return None
    value = value.strip()
    match = re.match(r"^(\d{2,}):(\d{2}):(\d{2})[.,](\d+)$", value)
    if match:
        h, m, s, frac = match.groups()
        frac = (frac + "000")[:3]
        return int(h) * 3600 + int(m) * 60 + int(s) + int(frac) / 1000
    match = re.match(r"^(\d{2,}):(\d{2}):(\d{2})$", value)
    if match:
        h, m, s = match.groups()
        return int(h) * 3600 + int(m) * 60 + int(s)
    match = re.match(r"^([\d.]+)ms$", value)
    if match:
        return float(match.group(1)) / 1000
    match = re.match(r"^([\d.]+)s$", value)
    if match:
        return float(match.group(1))
    return None


def parse_ttml(content: str) -> List[Dict[str, Any]]:
    """Parse TTML/DFXP/ITT (all XML, "<p begin=... end=...>text</p>" cues
    under the covers) into the same cue-dict shape as parse_vtt.

    Not yet verified against a real captured file from any platform this
    app supports -- no CivicClerk/Granicus/etc. sample has ever used this
    format, unlike SRT (see parse_srt's real Emporia, KS fixture). Built
    against the W3C TTML spec's own documented shape instead, and
    deliberately conservative: an element that isn't well-formed XML, or a
    cue whose begin/end can't be confidently converted to seconds
    (_ttml_time_to_seconds), is skipped rather than guessed at. ITT
    (Apple's iTunes Timed Text) is TTML-profiled closely enough that this
    is expected to work for it too, but that's an inference from the
    spec, not something confirmed live either.
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []

    cues = []
    for el in root.iter():
        # Namespace-agnostic tag match -- ElementTree renders a namespaced
        # tag as "{uri}p", and different vendors use different TTML
        # namespace URIs/prefixes for the same "p" (paragraph/cue) element.
        if el.tag.rsplit("}", 1)[-1] != "p":
            continue
        start = _ttml_time_to_seconds(el.get("begin"))
        end = _ttml_time_to_seconds(el.get("end"))
        if start is None or end is None:
            continue
        text = re.sub(r"\s+", " ", "".join(el.itertext())).strip()
        if text:
            cues.append({"start": start, "end": end, "text": text})

    normalize_shouting_caption(cues)
    return cues


_MARKUP_TAG_RE = re.compile(r"<[^>]+>")
_TIMING_LINE_RE = re.compile(
    r"^\d{1,2}:\d{2}(:\d{2})?[.,]\d{1,3}\s*(-->|,)\s*\d{1,2}:\d{2}(:\d{2})?[.,]\d{1,3}$"
)
_MICRODVD_FRAME_RE = re.compile(r"^\{\d+\}\{\d+\}")


def strip_unknown_caption_markup(content: str) -> str:
    """Best-effort, format-agnostic text extraction for a caption file in
    a format with no real structured parser here (SBV, SUB, SMI/SAMI, or
    a plain .txt a city is calling captions). Deliberately not trying to
    be a real per-format parser -- these formats are detected but not
    individually implemented (see BACKLOG.md), and precise per-line
    timing isn't required: `t=` deep-linking to the video's playhead has
    never depended on transcript timing (confirmed working with zero
    transcript at all, see the no-transcript-playhead feature), so an
    unstructured wall of real caption text is still strictly better than
    silence. Strips XML/HTML-ish tags (SAMI's <SYNC>/<P>), MicroDVD-style
    "{123}{456}" frame markers, and SRT/SBV-style timing lines, then
    drops blank lines and bare sequence numbers.
    """
    text = _MARKUP_TAG_RE.sub(" ", content)
    lines = []
    for raw_line in text.splitlines():
        line = _MICRODVD_FRAME_RE.sub("", raw_line).strip()
        if not line:
            continue
        if re.fullmatch(r"\d+", line):
            continue
        if _TIMING_LINE_RE.match(line):
            continue
        lines.append(line)
    # Real gap fixed 2026-08-11: this fallback path never applied the
    # same ALL-CAPS re-casing every structured-format parser already
    # does (see _normalize_shouting_text()'s docstring), so an ALL-CAPS
    # SBV/SUB/SMI/plain-.txt track stayed ALL CAPS unconditionally.
    normalized = _normalize_shouting_text("\n".join(lines).strip())
    # Also fixed 2026-08-11: unescape_caption_entities()'s general
    # double-escaping fix (see its own docstring), applied here last
    # (after tag-stripping above) so an already-escaped fake tag some
    # source legitimately meant as literal text (e.g. "&lt;i&gt;") can't
    # unescape into something _MARKUP_TAG_RE would then wrongly strip.
    return html.unescape(normalized)


# Extensions with a real structured (start/end/text) parser above.
STRUCTURED_CAPTION_PARSERS = {
    "vtt": parse_vtt,
    "srt": parse_srt,
    "ttml": parse_ttml,
    "dfxp": parse_ttml,
    "itt": parse_ttml,
}
# Text-based formats with no structured parser -- strip_unknown_caption_markup
# gives real (if unstructured/untimed) text instead of nothing.
TEXT_FALLBACK_CAPTION_EXTENSIONS = {"sbv", "sub", "smi", "sami", "txt", "xml"}
# Binary/encoded formats (EIA-608, EBU STL) -- no text can be extracted
# without real codec-level decoding, so these are link-only; callers
# should surface the URL itself rather than attempt to display "content".


def parse_captions_by_extension(url: str, content: str):
    """Single dispatch point every adapter should go through once it has
    a caption URL + its already-decoded text content, instead of each
    adapter re-implementing its own extension-sniffing. Returns
    (cues, fallback_text): exactly one is populated on success (`cues` a
    real structured transcript, `fallback_text` an unstructured text
    block for a format with no structured parser), or both are
    empty/None for a format this can't extract anything from at all
    (binary formats like .scc/.stl -- caller should fall back to linking
    the URL directly rather than trying to display "content").

    Structured cues go through dedupe_rollup_cues() here rather than in each
    adapter: roll-up captioning is a property of how a *city* captions its
    meetings, not of which platform hosts the video, so wiring it per-adapter
    is what left Granicus/CivicClerk/eScribe serving visibly duplicated
    transcripts while YouTube and Viebit were fine (see BACKLOG_DONE.md,
    WO-34). That function no-ops on a non-roll-up track, so this is safe for
    the ordinary one-cue-per-line captions most sources here emit.
    """
    ext = url.lower().split("?")[0].rsplit(".", 1)[-1]
    parser = STRUCTURED_CAPTION_PARSERS.get(ext)
    if parser:
        cues = parser(content)
        if cues:
            return dedupe_rollup_cues(cues), None
    elif ext == "xml":
        # A bare ".xml" extension doesn't say which schema -- some vendors
        # export real TTML/DFXP with a plain .xml extension rather than
        # .ttml/.dfxp. Try structured TTML parsing first (parse_ttml
        # returns [] cleanly on non-TTML-shaped XML or a parse error, so
        # this is a safe probe, not a guess that corrupts anything) before
        # falling through to the generic text fallback below.
        cues = parse_ttml(content)
        if cues:
            return dedupe_rollup_cues(cues), None
    if ext in TEXT_FALLBACK_CAPTION_EXTENSIONS:
        text = strip_unknown_caption_markup(content)
        return None, (text or None)
    return None, None


_TAG_RE = re.compile(r"<[^>]+>")

# --- Roll-up ("scrolling ticker") caption reconstruction -------------------
#
# Four independently-real cue shapes produce the same user-visible defect
# (duplicated, near-unreadable transcript text, every deep link landing on a
# fragment), so one function handles all of them. Every number below was
# measured on a real fetched caption file -- see dedupe_rollup_cues's
# docstring for which.
#
#  * A track is treated as roll-up only if a real fraction of its adjacent
#    caption *lines* overlap, where "overlap" means at least one shared word
#    of at least _ROLLUP_MIN_OVERLAP_CHARS characters. Measured across 18
#    real caption files from 7 platforms, that ratio is <= 0.048 on every
#    non-roll-up track (the worst being Fountain Valley's garbled noise) and
#    >= 0.401 on every roll-up one, so the 0.20 threshold sits with real
#    margin on both sides of the gap (same shape of calibration as
#    is_likely_garbled's 6%). The gate is what makes this safe to call from
#    the shared parse_captions_by_extension() dispatch, where most real
#    tracks are ordinary captions that must not be reshaped at all.
#  * The character floor is doing real work in both directions. Requiring
#    *two* shared words instead would be tidier but misses eScribe's shape
#    entirely: the real Essex County ON track previews only the next line's
#    first word ('...CALL THE   DECEMBER' / 'DECEMBER THIRD 2025 ESSEX
#    COUNTY'), which scores 0.155 on a two-word rule -- under the gate --
#    against 0.401 on this one. Dropping the floor and accepting any
#    one-word overlap goes wrong the other way: Fountain Valley's garbled
#    two-character junk fragments ('b8', 'c8') then score 0.352 and get
#    treated as roll-up.
#  * The unit is one caption *line*, not one cue. Two of the four real
#    shapes put the previous line and the new line in the same cue, and a
#    cue-level comparison misses the overlap entirely between them.
#  * Merging compares the incoming line against a rolling tail of the text
#    reconstructed so far, at word level, rather than doing a whole-string
#    prefix test. A prefix test is what YouTube's shape happens to need, but
#    it breaks on Granicus's: there the window is a fixed ~63-char ticker
#    that drops words off the *front* as it scrolls, so a repeated speaker
#    label ('>> Councilmember Hines: ') disappears mid-run and every cue
#    after that point fails the prefix comparison and starts a bogus new
#    segment carrying duplicated text.
#  * _ROLLUP_CONTEXT_WORDS looks further back than just the previous line,
#    because a real ticker is not strictly monotone: Tacoma's own track emits
#    a transient scrolled window ('HAVE ONE.') and then reverts to the fuller
#    one ('>> Councilmember Sadalge: I HAVE ONE.') on the very next cue.
#  * Comparison is case-folded, and '»' folds to '>>'. Not cosmetic: two
#    normalizations that already ran inside parse_vtt() re-spell the *same*
#    words between one cue and the next. _sentence_case() (the ALL-CAPS
#    de-shouting) capitalises after every '\n', so a line reads 'Good evening
#    everyone and' as cue N's second line and 'good evening everyone and' as
#    cue N+1's first; and normalize_speaker_change_marker() only rewrites a
#    '&gt;&gt;' anchored at the start of a cue, so the same speaker marker is
#    '»' in one cue and '>>' in the next. Case-sensitive comparison drops the
#    real Antioch CivicClerk track's roll-up ratio from 0.451 to 0.111 --
#    under the gate, i.e. the bug silently stays unfixed.
_ROLLUP_MIN_OVERLAP_CHARS = 4
_ROLLUP_MIN_PAIRS = 2
_ROLLUP_PAIR_RATIO_MIN = 0.20
_ROLLUP_CONTEXT_WORDS = 40
# Segment boundaries. This is a deep-link product: merging a whole roll-up
# run into one segment (what an unbounded "extend the last segment's end
# time" merge does) would make every timestamp on the page point at the top
# of a 30+ second blob. Sentence-final punctuation is the natural boundary
# and the one these sources actually emit; the char cap is the fallback for
# a stretch with no punctuation at all. Measured on the real full Tacoma
# track: 21,240 cues -> 1,168 segments, median 4.8s / 65 chars, longest
# 250 chars / 28.3s.
_ROLLUP_MAX_SEGMENT_CHARS = 240
_ROLLUP_SENTENCE_END_RE = re.compile(r"[.!?][\"')\]]*$")


def _rollup_lines(cues: List[Dict[str, Any]]) -> List[tuple]:
    """(cue, line, is_last_line_of_cue) for every non-blank line, tags stripped.

    is_last_line_of_cue matters for timing only: in a two-line roll-up cue
    the first line is text the viewer has already seen, so it must not
    stretch the previous segment's end time over the new cue's span.
    """
    out = []
    for cue in cues:
        text = _TAG_RE.sub("", cue.get("text", ""))
        parts = [part.strip() for part in text.split("\n") if part.strip()]
        for index, part in enumerate(parts):
            out.append((cue, part, index == len(parts) - 1))
    return out


# Trailing punctuation is stripped before comparing, because a real roll-up
# source re-emits the same word with and without it. eScribe's stub cues do
# this constantly ("   REFLECTION" then "REFLECTION."), and without the strip
# every sentence-final word comes out twice.
_FOLD_TRAILING_PUNCTUATION = ".,;:!?\"')]"


def _fold_words(words: List[str]) -> List[str]:
    return [
        word.casefold().replace("»", ">>").rstrip(_FOLD_TRAILING_PUNCTUATION)
        for word in words
    ]


def _word_overlap(context: List[str], words: List[str]) -> int:
    """Longest k where context's last k words equal words' first k words."""
    folded_context = _fold_words(context)
    folded_words = _fold_words(words)
    for k in range(min(len(folded_context), len(folded_words)), 0, -1):
        if folded_context[-k:] == folded_words[:k]:
            return k
    return 0


def _is_rollup_pair(previous: List[str], words: List[str]) -> bool:
    """Does `words` re-say enough of `previous`'s tail to be a roll-up repeat?

    Deliberately stricter than the merge test below, which accepts any
    overlap at all once a track is already known to be roll-up. This one has
    to tell roll-up apart from ordinary captions and from garbled noise --
    see the character-floor bullet in the comment block above.
    """
    overlap = _word_overlap(previous, words)
    if not overlap:
        return False
    return len(" ".join(words[:overlap])) >= _ROLLUP_MIN_OVERLAP_CHARS


def _looks_like_rollup(lines: List[tuple]) -> bool:
    previous: Optional[List[str]] = None
    pairs = hits = 0
    for _cue, line, _is_last in lines:
        words = line.split()
        if previous is not None:
            pairs += 1
            if _is_rollup_pair(previous, words):
                hits += 1
        previous = words
    if pairs < _ROLLUP_MIN_PAIRS:
        return False
    return (hits / pairs) >= _ROLLUP_PAIR_RATIO_MIN


def dedupe_rollup_cues(cues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Reconstruct real segments from "roll-up" (scrolling) caption cues.

    Roll-up captioning doesn't give each line of speech its own cue -- it
    re-emits a growing/scrolling *window* over the same speech again and
    again, so treating each cue as a segment produces massively duplicated
    text. Four real shapes, all confirmed against live fetched files:

    1. YouTube auto-captions (real Philadelphia City Council "Committee on
       Education" 08-06-26, 13,111 cues, fetched via yt-dlp) repeat the
       previous settled line as line 1 and grow the next line word-by-word
       as line 2, each word individually timestamped via <c> tags:

           00:00:01.199 --> 00:00:03.750
           <blank>
           most<...>permanent<...>supportive<...>housing<...>takes

           00:00:03.750 --> 00:00:03.760
           most permanent supportive housing takes
           <blank>

           00:00:03.760 --> 00:00:05.749
           most permanent supportive housing takes
           five<...>to<...>seven<...>years

    2. Granicus live captions (real Tacoma WA city council 2026-01-06, clip
       7460, 21,240 cues -- the meeting BACKLOG.md named) emit a single
       fixed-width (~63 char) ticker line that grows word-by-word and then
       drops words off the *front* to make room, so a repeated speaker label
       vanishes mid-run:

           >> Councilmember Hines: WE WILL GET EVERYONE SWORN IN SO WE CAN
           GET EVERYONE SWORN IN SO WE CAN
           GET EVERYONE SWORN IN SO WE CAN BEGIN

    3. CivicClerk (real Antioch CA council 2026-03-10, event 18, 5,481 SRT
       cues -- also named in BACKLOG.md) promote the previous line to the
       top of a two-line cue, with no blank-line alternation:

           >> Mayor Bernal:   ALL RIGHT,
           GOOD EVENING EVERYONE AND

           GOOD EVENING EVERYONE AND
           WELCOME TO OUR REGULAR CITY

    4. eScribe/iSiLIVE (real Essex County ON council 2025-12-03, 11,627
       cues -- also named in BACKLOG.md) preview only the *next* line's
       first word at the end of the current one, sometimes as a standalone
       stub cue of its own, so the overlap is a single word:

           I WOULD LIKE TO CALL THE   DECEMBER
           DECEMBER THIRD 2025 ESSEX COUNTY
              COUNCIL
           COUNCIL MEETING TO ORDER.

    Real measured effect: Tacoma 21,240 cues -> 1,168 segments (859KB of
    duplicated cue text down to 100KB); Antioch 275KB -> 135KB; Essex 298KB ->
    216KB; Philadelphia 242KB -> 230KB. Viebit's NYC Council track is
    byte-for-byte unchanged from the previous implementation.

    Non-roll-up tracks are returned unchanged (tags stripped) rather than
    reshaped -- see _looks_like_rollup and the ratios in the comment block
    above it.
    """
    lines = _rollup_lines(cues)
    if not lines:
        return []

    if not _looks_like_rollup(lines):
        return [
            {
                "start": cue["start"],
                "end": cue["end"],
                "text": _TAG_RE.sub("", cue["text"]),
            }
            for cue in cues
        ]

    result: List[Dict[str, Any]] = []
    open_segment: Optional[Dict[str, Any]] = None
    context: List[str] = []

    def close_segment() -> None:
        nonlocal open_segment
        if open_segment is None:
            return
        # Real Granicus tracks contain cues whose end precedes their start
        # (1,338 of Tacoma's 21,240) -- don't let one produce a
        # negative-length segment.
        open_segment["end"] = max(open_segment["end"], open_segment["start"])
        result.append(open_segment)
        open_segment = None

    def upgrade_tail(segment: Optional[Dict[str, Any]], words: List[str]) -> None:
        """Keep the more complete spelling when a line only re-says the tail.

        Folded comparison ignores trailing punctuation, so "REFLECTION." and
        the stub "   REFLECTION" before it match as the same word -- but the
        punctuated one is the real end of the sentence and is what should
        survive into the transcript.
        """
        if segment is None or not words:
            return
        tail = segment["words"][-len(words) :]
        if len(tail) != len(words) or _fold_words(tail) != _fold_words(words):
            return
        if len(" ".join(words)) > len(" ".join(tail)):
            segment["words"][-len(words) :] = list(words)

    for cue, line, is_last_line in lines:
        words = line.split()
        overlap = _word_overlap(context, words)
        fresh = words[overlap:]
        context = (context + fresh)[-_ROLLUP_CONTEXT_WORDS:]

        if not fresh:
            # The window re-settled without adding anything. Extend whatever
            # segment that speech already belongs to rather than emitting a
            # duplicate of it -- but only from the cue's *last* line, since
            # an earlier line is text the viewer already saw and its cue's
            # span belongs to the newer line below it.
            target = (
                open_segment
                if open_segment is not None
                else (result[-1] if result else None)
            )
            if target is not None:
                if is_last_line:
                    target["end"] = max(target["end"], cue["end"])
                upgrade_tail(target, words)
                if open_segment is not None and _ROLLUP_SENTENCE_END_RE.search(
                    " ".join(open_segment["words"])
                ):
                    close_segment()
            continue

        if overlap == 0:
            close_segment()

        if open_segment is None:
            open_segment = {
                "start": cue["start"],
                "end": cue["end"],
                "words": list(fresh),
            }
        else:
            open_segment["words"].extend(fresh)
            open_segment["end"] = max(open_segment["end"], cue["end"])

        text_so_far = " ".join(open_segment["words"])
        if (
            _ROLLUP_SENTENCE_END_RE.search(text_so_far)
            or len(text_so_far) >= _ROLLUP_MAX_SEGMENT_CHARS
        ):
            close_segment()

    close_segment()
    for segment in result:
        segment["text"] = " ".join(segment.pop("words"))
    return result


# Some caption sources (confirmed: San Francisco's Granicus captions) render
# entirely in ALL CAPS -- a live-caption-system convention, not an error --
# which reads as shouting when displayed as a transcript. Detected once per
# whole track (essentially zero lowercase letters across a real sample of
# alphabetic content), not per cue, so a normal transcript with a few
# capitalized acronyms is never touched.
_SHOUT_SAMPLE_MIN_LETTERS = 40
_SHOUT_LOWERCASE_RATIO_MAX = 0.02
_CUE_JOIN = "␞"  # record-separator symbol; won't appear in real captions


def _normalize_shouting_text(text: str) -> str:
    """Shared shouting-detection/re-casing check behind both
    normalize_shouting_caption() (structured cue-list callers) and
    strip_unknown_caption_markup()'s own plain-text fallback path (real
    gap fixed 2026-08-11 -- the fallback path never called this at all,
    so an ALL-CAPS SBV/SUB/SMI/plain-.txt track stayed ALL CAPS
    unconditionally, unlike every VTT/SRT/TTML track). Returns `text`
    unchanged when the shouting heuristic doesn't trigger.
    """
    letters = [ch for ch in text if ch.isalpha()]
    if len(letters) < _SHOUT_SAMPLE_MIN_LETTERS:
        return text
    lowercase_ratio = sum(1 for ch in letters if ch.islower()) / len(letters)
    if lowercase_ratio > _SHOUT_LOWERCASE_RATIO_MAX:
        return text
    return _sentence_case(text)


def normalize_shouting_caption(cues: List[Dict[str, Any]]) -> None:
    if not cues:
        return

    # Join with a placeholder rather than casing each cue independently, so
    # sentence-boundary detection sees the real punctuation flow across cue
    # breaks instead of treating every cue as its own sentence start.
    joined = _CUE_JOIN.join(c["text"] for c in cues)
    normalized = _normalize_shouting_text(joined)
    if normalized == joined:
        return
    for cue, text in zip(cues, normalized.split(_CUE_JOIN)):
        cue["text"] = text


def _sentence_case(text: str) -> str:
    text = text.lower()
    text = re.sub(
        r"(^|[.!?]\s+|\n)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text
    )
    text = re.sub(r"\bi\b", "I", text)
    return text


# YouTube's own raw auto-caption VTT source contains the literal 8-character
# string "&gt;&gt;" as real cue text at the start of a new speaker's first
# cue (confirmed live -- not an actual ">" character this app is
# mis-escaping). HTML-escaping that literal text for safe display is
# technically correct but renders as a raw entity artifact, so swap it for
# a real, inert Unicode marker instead. Deliberately narrow: matches only
# this exact literal prefix, not a general entity-decoding pass -- broadly
# unescaping transcript text would be a real risk if a caption ever
# legitimately contains "&" or literal angle-bracket text (e.g. someone
# reading a web address aloud), which must reach the page as plain,
# un-reinterpreted text.
_SPEAKER_CHANGE_MARKER_RE = re.compile(r"^&gt;&gt;\s*")


def normalize_speaker_change_marker(cues: List[Dict[str, Any]]) -> None:
    for cue in cues:
        cue["text"] = _SPEAKER_CHANGE_MARKER_RE.sub("» ", cue["text"])


def unescape_caption_entities(cues: List[Dict[str, Any]]) -> None:
    """General fix for the double-escaping bug the narrow marker fix above
    only partly covers (see BACKLOG.md): a caption source's *raw* text can
    already contain literal HTML entities (`&amp;`, `&lt;`, `&#39;`,
    `&nbsp;`, or a mid-cue `&gt;&gt;` the start-anchored marker regex above
    never touches) baked in as plain text, not real `<`/`>`/`&` characters
    -- an extraction artifact from a source that was itself HTML. Left
    alone, Jinja's autoescape then escapes the leading `&` a second time
    (`&` -> `&amp;`), producing a visible `&gt;&gt;`-style artifact on the
    page instead of the real character.

    Safe to run unconditionally, run once, last (after the tag-stripping
    fallback paths that call this have already done their own
    processing): `html.unescape()` only ever converts text that already
    matches a real entity pattern (`&name;`, `&#NNN;`, or the handful of
    legacy semicolon-less named entities the HTML5 spec still recognizes)
    -- a caption that legitimately contains a bare `&`/`<`/`>` character
    (e.g. someone reading "Bed & Breakfast" or a URL aloud) doesn't match
    that shape and passes through completely unchanged. Whatever comes out
    still goes through Jinja's normal autoescape before reaching the page,
    so a real `<`/`>`/`&` this surfaces is displayed as safe literal text,
    never interpreted as markup.
    """
    for cue in cues:
        cue["text"] = html.unescape(cue["text"])


# Words genuinely fine at length <= 2 -- everything else that short (e.g.
# Alexandria VA's real garbled captions: "tm", "Oa", "sd") is junk, not a
# real short word.
_COMMON_SHORT_WORDS = {
    "a",
    "i",
    "to",
    "of",
    "in",
    "on",
    "is",
    "it",
    "be",
    "at",
    "as",
    "an",
    "or",
    "if",
    "so",
    "no",
    "we",
    "he",
    "she",
    "do",
    "my",
    "up",
    "us",
    "by",
    "am",
    "ok",
}
_GARBLED_MIN_SAMPLE_WORDS = 40
_GARBLED_JUNK_RATIO_MAX = 0.06
# Four offsets across the transcript rather than just its start -- see the
# is_likely_garbled docstring for why a single leading prefix isn't enough.
_GARBLED_SAMPLE_OFFSETS = (0.0, 0.25, 0.5, 0.75)
_GARBLED_SAMPLE_SLICE_CHARS = 1000


def is_likely_garbled(cues: List[Dict[str, Any]]) -> bool:
    """Heuristic quality check, not a guarantee -- flags a transcript as
    likely garbled at the source (as opposed to a parsing bug) so callers
    can warn the user rather than presenting it at face value.

    Calibrated against real confirmed samples: Alexandria VA's genuinely
    garbled captions (clip 6490 -- fragments like "test meele first item on
    t", "last meeting.Oa") have ~17% of words as short junk fragments,
    while four independently-confirmed clean real sources (Boston, San
    Diego, DC, San Francisco) all sit under 2%. The 6% threshold sits with
    real margin on both sides of that gap.

    Sampled at four offsets (start, ~25%, ~50%, ~75%) instead of a single
    leading prefix -- a real confirmed case (Cincinnati OH, "budget and
    finance committee" 2023-02-13, 98,449 chars of joined cue text) stays
    clean through roughly the first quarter of the transcript and then
    degrades into binary-looking junk for most of what follows. A fixed
    4000-char prefix (~4% of that transcript) never got far enough to see
    it: sampling just the old prefix on this real transcript's text gives a
    ~1.3% junk ratio (well under threshold, so it went unflagged), while
    sampling all four offsets gives ~42% (correctly flagged). Verified
    directly against this real transcript's text (fetched from the live,
    public `/m/{slug}/transcript.txt` export) while building this fix.
    """
    full_text = " ".join(c["text"] for c in cues)
    sample = "".join(
        full_text[
            int(len(full_text) * offset) : int(len(full_text) * offset)
            + _GARBLED_SAMPLE_SLICE_CHARS
        ]
        for offset in _GARBLED_SAMPLE_OFFSETS
    )
    words = re.findall(r"[A-Za-z0-9']+", sample)
    alpha_words = [w for w in words if re.search(r"[A-Za-z]", w)]
    if len(alpha_words) < _GARBLED_MIN_SAMPLE_WORDS:
        return False

    junk = sum(
        1 for w in alpha_words if len(w) <= 2 and w.lower() not in _COMMON_SHORT_WORDS
    )
    return (junk / len(alpha_words)) > _GARBLED_JUNK_RATIO_MAX


_LANG_MIN_SAMPLE_CHARS = 20
# Roughly the old whole-transcript sample size, reused as the per-chunk size
# so a short track's behaviour is bit-for-bit what it was before this change
# (one chunk, one langdetect call). Capped at 40 chunks, chosen evenly across
# the transcript rather than truncated to its head: that keeps the cost of a
# multi-hour meeting bounded while still sampling the whole thing end to end.
# Measured on the three largest real transcripts to hand: 177-347ms, the
# worst being Essex County's 231KB one -- against seconds of network I/O in
# the resolve that calls this.
_LANG_CHUNK_CHARS = 2000
_LANG_MAX_CHUNKS = 40


def _language_sample_chunks(text: str) -> List[str]:
    """Split on word boundaries into ~_LANG_CHUNK_CHARS chunks, then thin to
    at most _LANG_MAX_CHUNKS evenly spaced across the whole transcript."""
    chunks: List[str] = []
    current: List[str] = []
    size = 0
    for word in text.split():
        current.append(word)
        size += len(word) + 1
        if size >= _LANG_CHUNK_CHARS:
            chunks.append(" ".join(current))
            current, size = [], 0
    if current:
        chunks.append(" ".join(current))
    if len(chunks) > _LANG_MAX_CHUNKS:
        step = len(chunks) / _LANG_MAX_CHUNKS
        chunks = [chunks[int(i * step)] for i in range(_LANG_MAX_CHUNKS)]
    return chunks


def detect_language_from_texts(texts: Iterable[str]) -> Optional[str]:
    """Best-effort language detection from real transcript content -- never
    trust a source-provided language label (a Granicus track labeled
    srclang="en" turned out to genuinely be Spanish content on a real Simi
    Valley meeting, clip 2840). Shared by every adapter that fetches real
    caption/transcript text (Granicus, CivicClerk originally; Swagit and CA
    Legislature added 2026-08-08 after a missing 'en' tag on the /meetings
    listing for real English transcripts on both surfaced the gap -- see
    BACKLOG_DONE.md). Requires at least 20 non-whitespace characters before
    attempting detection, since langdetect guesses wildly on tiny samples.

    Votes across the *whole* transcript, weighted by how much text each
    chunk contributes, rather than reading the first 2000 characters and
    stopping (WO-34). That head-only sample let a bad opening stretch decide
    a whole multi-hour meeting's label: two real live pages,
    /m/meeting-00bbd1 (Lincoln City OR) and /m/meeting-d09fc0 (Moraine City
    OH), were both labelled Welsh ('cy') off a quiet/low-confidence opening
    chunk while the rest of each meeting was confidently English. Since
    segments reach here sorted by start time, "first 2000 characters" always
    means "the start of the meeting" -- exactly where dead air, music before
    the gavel, and non-English invocations/proclamations live.

    A genuinely non-English transcript still resolves correctly, because the
    vote is over real text volume, not chunk count: the real Simi Valley
    Spanish track (clip 2840) votes 'es' unanimously across all 8 of its
    chunks. A genuinely short one is unaffected by construction -- under
    _LANG_CHUNK_CHARS there is exactly one chunk and this is the old
    single-sample behaviour.
    """
    sample = " ".join(t for t in texts if t)
    if len(sample.strip()) < _LANG_MIN_SAMPLE_CHARS:
        return None

    weights: Dict[str, int] = {}
    for chunk in _language_sample_chunks(sample):
        if len(chunk.strip()) < _LANG_MIN_SAMPLE_CHARS:
            continue
        try:
            code = _detect_language(chunk)
        except LangDetectException:
            continue
        weights[code] = weights.get(code, 0) + len(chunk)
    if not weights:
        return None
    # max() over insertion order keeps ties resolved by first appearance
    # rather than by dict/hash ordering.
    return max(weights, key=lambda code: weights[code])


def _parse_timestamp(timestamp: str) -> float:
    parts = timestamp.replace(",", ".").split(":")

    if len(parts) == 3:
        hours, minutes, seconds = parts
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    elif len(parts) == 2:
        minutes, seconds = parts
        return int(minutes) * 60 + float(seconds)
    else:
        return float(parts[0])
