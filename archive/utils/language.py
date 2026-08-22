"""Deliberate duplicate of app/utils/vtt_parser.py's detect_language_from_texts()
-- kept in sync manually, same reasoning as archive/utils/url_normalize.py's
own duplicate-of-app's-version docstring: the Archive is an independently
deployed service and shouldn't gain a dependency on app/'s codebase just for
one small pure function. Used by archive/db/crud.py's report_chunk_result()
to detect a transcribed version's language from its own finished text,
matching every scraped-caption adapter's existing "never trust a label,
detect from real content" behavior (there's no label to distrust here --
self-transcribed audio has no source-provided language at all -- but the
detection logic itself is identical).

Sync note (WO-34, 2026-08-21): the head-only `[:2000]` sample was replaced
with a length-weighted vote over the whole transcript, and langdetect is now
seeded. Both real pages that surfaced the bug (`/m/meeting-00bbd1`,
`/m/meeting-d09fc0`, each labelled Welsh off a quiet opening chunk) came
through *this* copy, not app/'s -- they were locally-transcribed backlog
meetings ingested via report_chunk_result(). See the app/ docstring for the
full reasoning; keep the two in step.
"""

from typing import Dict, Iterable, List, Optional

from langdetect import DetectorFactory, LangDetectException, detect as _detect_language

DetectorFactory.seed = 0

_LANG_MIN_SAMPLE_CHARS = 20
_LANG_CHUNK_CHARS = 2000
_LANG_MAX_CHUNKS = 40


def _language_sample_chunks(text: str) -> List[str]:
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
    return max(weights, key=lambda code: weights[code])


# User-facing names for the version picker (meeting_page.html) -- raw
# langdetect/source-provided codes aren't self-explanatory to a reader.
# Only the two codes actually seen in practice so far; an unrecognized
# code falls back to displaying itself rather than guessing.
LANGUAGE_DISPLAY_NAMES = {"en": "English", "es": "Español"}


def language_display_name(code: Optional[str]) -> str:
    if not code:
        return "unknown"
    return LANGUAGE_DISPLAY_NAMES.get(code, code)
