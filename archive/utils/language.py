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
"""

from typing import Iterable, Optional

from langdetect import LangDetectException, detect as _detect_language


def detect_language_from_texts(texts: Iterable[str]) -> Optional[str]:
    sample = " ".join(t for t in texts if t)[:2000]
    if len(sample.strip()) < 20:
        return None
    try:
        return _detect_language(sample)
    except LangDetectException:
        return None


# User-facing names for the version picker (meeting_page.html) -- raw
# langdetect/source-provided codes aren't self-explanatory to a reader.
# Only the two codes actually seen in practice so far; an unrecognized
# code falls back to displaying itself rather than guessing.
LANGUAGE_DISPLAY_NAMES = {"en": "English", "es": "Español"}


def language_display_name(code: Optional[str]) -> str:
    if not code:
        return "unknown"
    return LANGUAGE_DISPLAY_NAMES.get(code, code)
