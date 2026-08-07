import re
from typing import List, Dict, Any


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

    _normalize_shouting_caption(cues)
    return cues


# Some caption sources (confirmed: San Francisco's Granicus captions) render
# entirely in ALL CAPS -- a live-caption-system convention, not an error --
# which reads as shouting when displayed as a transcript. Detected once per
# whole track (essentially zero lowercase letters across a real sample of
# alphabetic content), not per cue, so a normal transcript with a few
# capitalized acronyms is never touched.
_SHOUT_SAMPLE_MIN_LETTERS = 40
_SHOUT_LOWERCASE_RATIO_MAX = 0.02
_CUE_JOIN = "␞"  # record-separator symbol; won't appear in real captions


def _normalize_shouting_caption(cues: List[Dict[str, Any]]) -> None:
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
