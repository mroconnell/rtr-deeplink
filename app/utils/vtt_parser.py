import re
import xml.etree.ElementTree as ET
from typing import Iterable, List, Dict, Any, Optional

from langdetect import detect as _detect_language, LangDetectException


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


def parse_vtt(content: str) -> List[Dict[str, Any]]:
    """Parse WebVTT content into a list of cue dicts with 'start', 'end', 'text'.

    Ported from rtr-transcripts/app/utils/vtt_parser.py (unchanged — this part
    already worked correctly in testing).
    """
    content = content.lstrip("﻿")
    lines = content.splitlines()

    cues = []
    current_cue = None

    for line in lines:
        line = line.strip()

        if not line or line == "WEBVTT":
            continue

        timestamp_match = re.match(
            r"(\d{2}:\d{2}:\d{2}[\.\,]\d{3}) --> ((\d{2}:\d{2}:\d{2}[\.\,]\d{3}).*)",
            line,
        )

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
        elif current_cue is not None:
            if current_cue["text"]:
                current_cue["text"] += "\n" + line
            else:
                current_cue["text"] = line

    if current_cue:
        cues.append(current_cue)

    normalize_shouting_caption(cues)
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
    return "\n".join(lines).strip()


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
    """
    ext = url.lower().split("?")[0].rsplit(".", 1)[-1]
    parser = STRUCTURED_CAPTION_PARSERS.get(ext)
    if parser:
        cues = parser(content)
        if cues:
            return cues, None
    elif ext == "xml":
        # A bare ".xml" extension doesn't say which schema -- some vendors
        # export real TTML/DFXP with a plain .xml extension rather than
        # .ttml/.dfxp. Try structured TTML parsing first (parse_ttml
        # returns [] cleanly on non-TTML-shaped XML or a parse error, so
        # this is a safe probe, not a guess that corrupts anything) before
        # falling through to the generic text fallback below.
        cues = parse_ttml(content)
        if cues:
            return cues, None
    if ext in TEXT_FALLBACK_CAPTION_EXTENSIONS:
        text = strip_unknown_caption_markup(content)
        return None, (text or None)
    return None, None


_TAG_RE = re.compile(r"<[^>]+>")


def dedupe_rollup_cues(cues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse YouTube auto-caption "roll-up" cues into real segments.

    YouTube's auto-generated VTT (confirmed live, a real LA City Council
    meeting via yt-dlp) doesn't give each line its own cue -- every cue
    repeats the previous settled line as line 1 and grows the *next* line
    word-by-word as line 2 (each word individually timestamped via <c>
    tags), so treating each cue as its own segment produces massive
    overlapping duplicate text. Confirmed structure from a real sample:

        00:00:01.199 --> 00:00:03.750
        <blank>
        most<...>permanent<...>supportive<...>housing<...>takes

        00:00:03.750 --> 00:00:03.760
        most permanent supportive housing takes
        <blank>

        00:00:03.760 --> 00:00:05.749
        most permanent supportive housing takes
        five<...>to<...>seven<...>years

    This takes each cue's last non-blank line (stripped of <c> tags), and
    merges it into the running segment whenever it's a growing/settling
    version of the previous line (one is a prefix of the other) rather
    than appending a new one -- otherwise it starts a new segment.
    Verified against a real 4035-cue/570KB sample: collapses to 2004
    segments with no visible duplication and coherent reconstructed text.
    """
    result: List[Dict[str, Any]] = []
    prev_line = ""
    for cue in cues:
        text = _TAG_RE.sub("", cue["text"])
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        line = lines[-1] if lines else ""
        if not line:
            continue

        if result and (line.startswith(prev_line) or prev_line.startswith(line)):
            result[-1]["end"] = cue["end"]
            if len(line) > len(prev_line):
                result[-1]["text"] = line
                prev_line = line
        else:
            result.append({"start": cue["start"], "end": cue["end"], "text": line})
            prev_line = line

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


def normalize_shouting_caption(cues: List[Dict[str, Any]]) -> None:
    if not cues:
        return

    # Join with a placeholder rather than casing each cue independently, so
    # sentence-boundary detection sees the real punctuation flow across cue
    # breaks instead of treating every cue as its own sentence start.
    joined = _CUE_JOIN.join(c["text"] for c in cues)
    letters = [ch for ch in joined if ch.isalpha()]
    if len(letters) < _SHOUT_SAMPLE_MIN_LETTERS:
        return
    lowercase_ratio = sum(1 for ch in letters if ch.islower()) / len(letters)
    if lowercase_ratio > _SHOUT_LOWERCASE_RATIO_MAX:
        return

    normalized = _sentence_case(joined)
    for cue, text in zip(cues, normalized.split(_CUE_JOIN)):
        cue["text"] = text


def _sentence_case(text: str) -> str:
    text = text.lower()
    text = re.sub(r"(^|[.!?]\s+|\n)([a-z])", lambda m: m.group(1) + m.group(2).upper(), text)
    text = re.sub(r"\bi\b", "I", text)
    return text


# Words genuinely fine at length <= 2 -- everything else that short (e.g.
# Alexandria VA's real garbled captions: "tm", "Oa", "sd") is junk, not a
# real short word.
_COMMON_SHORT_WORDS = {
    "a", "i", "to", "of", "in", "on", "is", "it", "be", "at", "as", "an",
    "or", "if", "so", "no", "we", "he", "she", "do", "my", "up", "us",
    "by", "am", "ok",
}
_GARBLED_MIN_SAMPLE_WORDS = 40
_GARBLED_JUNK_RATIO_MAX = 0.06


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
    """
    sample = " ".join(c["text"] for c in cues)[:4000]
    words = re.findall(r"[A-Za-z0-9']+", sample)
    alpha_words = [w for w in words if re.search(r"[A-Za-z]", w)]
    if len(alpha_words) < _GARBLED_MIN_SAMPLE_WORDS:
        return False

    junk = sum(1 for w in alpha_words if len(w) <= 2 and w.lower() not in _COMMON_SHORT_WORDS)
    return (junk / len(alpha_words)) > _GARBLED_JUNK_RATIO_MAX


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
    """
    sample = " ".join(t for t in texts if t)[:2000]
    if len(sample.strip()) < 20:
        return None
    try:
        return _detect_language(sample)
    except LangDetectException:
        return None


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
