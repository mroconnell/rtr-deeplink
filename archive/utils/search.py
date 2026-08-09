"""Keyword search over a meeting's title/jurisdiction/agenda/transcript
text. No search index, no materialized column -- see the note on
`list_pages()` in `crud.py` and BACKLOG.md for why, and what it'll take to
outgrow this. Everything here runs in Python, over whatever the DB already
returned, at query time -- fine at the Archive's current scale (dozens of
meetings), not meant to scale past a few hundred.
"""

import html
import re
from typing import Iterable, Optional

_WORD_RE = re.compile(r"[a-z0-9']+")


def build_corpus(*texts: str) -> str:
    """Lowercased, whitespace-joined text from every searchable field on a
    meeting -- title, jurisdiction, agenda item text, transcript segment
    text. Used directly for exact (substring) search; tokenized separately
    for fuzzy search since that needs whole words, not raw text."""
    return " ".join(t for t in texts if t).lower()


def tokenize(corpus: str) -> set:
    return set(_WORD_RE.findall(corpus))


def _levenshtein(a: str, b: str, max_dist: int) -> int:
    """Bounded edit distance -- returns max_dist + 1 (a cheap "too far"
    sentinel) as soon as every cell in a DP row exceeds max_dist, so a
    wildly different word pair (common case: most words in a transcript
    don't match a given query term at all) exits fast instead of running
    the full O(len(a) * len(b)) table."""
    if abs(len(a) - len(b)) > max_dist:
        return max_dist + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        row_min = cur[0]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            row_min = min(row_min, cur[j])
        if row_min > max_dist:
            return max_dist + 1
        prev = cur
    return prev[-1]


def _fuzzy_threshold(word: str) -> int:
    """How many single-character edits (insert/delete/substitute) still
    count as "the same word" -- scaled by length so a 3-letter word doesn't
    fuzzy-match half the dictionary. Tuned against the motivating example
    (a 7-letter word like "traffic" should still match a 1-character typo
    like "trafic" or "traffiq"), not derived from any measured data."""
    if len(word) <= 4:
        return 0
    if len(word) <= 7:
        return 1
    return 2


def matches(query: str, corpus: str, corpus_words: set, fuzzy: bool) -> bool:
    """True if every whitespace-separated term in `query` matches
    somewhere in this meeting's searchable text.

    Exact mode: plain case-insensitive substring match against the raw
    corpus (Python's `in` on a lowercased string -- fast, and the
    intentional default since it needs no per-word distance computation).
    Fuzzy mode: each query term must equal, or be within
    `_fuzzy_threshold()` edits of, at least one real word in the meeting's
    tokenized text -- catches transcription typos ("trafic", "traffiq" for
    "traffic") that a substring search would silently miss.
    """
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return True

    if not fuzzy:
        return all(term in corpus for term in terms)

    def _term_matches(term: str) -> bool:
        threshold = _fuzzy_threshold(term)
        return any(word == term or _levenshtein(term, word, threshold) <= threshold for word in corpus_words)

    return all(_term_matches(term) for term in terms)


def _find_span(term: str, text_lower: str, fuzzy: bool) -> Optional[tuple]:
    """Character (start, end) of the first match for `term` in
    `text_lower` (already-lowercased), or None. Exact mode is a plain
    substring search; fuzzy mode walks the real words in the text and
    returns the span of the first one within the term's edit-distance
    threshold -- deliberately the *actual* word found (e.g. "trafic"),
    not the query term itself, so a caller building a snippet quotes
    what the source text really says rather than something that'd read
    as silently doctored.
    """
    if not fuzzy:
        idx = text_lower.find(term)
        return (idx, idx + len(term)) if idx != -1 else None

    threshold = _fuzzy_threshold(term)
    for m in _WORD_RE.finditer(text_lower):
        word = m.group(0)
        if word == term or _levenshtein(term, word, threshold) <= threshold:
            return (m.start(), m.end())
    return None


def find_snippet(query: str, texts: Iterable[str], fuzzy: bool, window: int = 50) -> Optional[str]:
    """A short HTML excerpt around the first matching term, for
    `/meetings` search results -- e.g. "...traffic calming measures on
    <mark>Elm Street</mark> were discussed..." so a result reads like a
    real search hit, not just a bare title.

    `texts` should be the searchable body text *other than* the title/
    jurisdiction, which already render directly above any snippet on
    `/meetings` -- repeating them here would just be noise. Checks each
    text in order and returns on the first match; None if none of these
    specific texts matched (e.g. the query only matched the title).

    Returned string already has its plain-text portions HTML-escaped,
    with only the deliberately-inserted <mark> tag left raw -- callers
    should render it with a "safe"/no-further-escaping filter.
    """
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return None

    for text in texts:
        if not text:
            continue
        text_lower = text.lower()
        for term in terms:
            span = _find_span(term, text_lower, fuzzy)
            if not span:
                continue
            start, end = span
            win_start = max(0, start - window)
            win_end = min(len(text), end + window)
            prefix = "…" if win_start > 0 else ""
            suffix = "…" if win_end < len(text) else ""
            before = html.escape(text[win_start:start])
            matched = html.escape(text[start:end])
            after = html.escape(text[end:win_end])
            return f"{prefix}{before}<mark class=\"search-match\">{matched}</mark>{after}{suffix}"

    return None
