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
_PHRASE_RE = re.compile(r'(-?)"([^"]*)"')
_NOOP_WORDS = {"and", "&"}


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


def _parse_query(query: str) -> tuple:
    """Splits a query into (phrases, words, excluded_phrases, excluded_words).

    A `"quoted phrase"` is required as one continuous adjacent match;
    everything outside quotes is split into independent words as before,
    each required separately (AND, not OR -- a meeting must contain every
    word/phrase, though unquoted words don't need to be adjacent to each
    other or to a phrase). An unclosed quote isn't a syntax error --
    `_PHRASE_RE` simply doesn't match it, so the stray `"` character just
    rides along as part of whatever word it's stuck to, same as it did
    before phrase support existed (that word then just won't match
    anything, which is the same "quoting made it worse, not ignored"
    behavior this whole fix is otherwise closing -- but only for that one
    malformed term, not the entire query).

    Basic operators, Google-style: a leading `-` on a word or `-"phrase"`
    excludes meetings containing it (NOT) -- collected separately here and
    checked first in `matches()`, since a meeting failing an exclusion
    should never fall through to (and get overridden by) the positive
    AND checks. A leading `+`, a bare `&`, or the bare word `AND` are all
    treated as no-ops: every unquoted word is already required by default,
    so these exist only so someone typing them doesn't get a literal (and
    always-failing, since real transcript text is very unlikely to contain
    a bare "+" or "&" character) search term instead of the AND they meant.
    No OR support -- that needs real expression-tree parsing (grouping/
    precedence), which this flat list-based return value can't represent;
    see BACKLOG.md.
    """
    phrases = []
    excluded_phrases = []
    for neg, phrase in _PHRASE_RE.findall(query):
        phrase = phrase.strip().lower()
        if not phrase:
            continue
        (excluded_phrases if neg else phrases).append(phrase)

    remainder = _PHRASE_RE.sub(" ", query)
    words = []
    excluded_words = []
    for token in remainder.lower().split():
        if token.startswith("-") and len(token) > 1:
            excluded_words.append(token[1:])
        elif token.startswith("+") and len(token) > 1:
            words.append(token[1:])
        elif token in ("+", "-") or token in _NOOP_WORDS:
            continue
        else:
            words.append(token)
    return phrases, words, excluded_phrases, excluded_words


def matches(query: str, corpus: str, corpus_words: set, fuzzy: bool) -> bool:
    """True if every `"quoted phrase"` and every unquoted word in `query`
    matches somewhere in this meeting's searchable text, and no excluded
    (`-term`/`-"phrase"`) term does.

    Exact mode: plain case-insensitive substring match against the raw
    corpus (Python's `in` on a lowercased string -- fast, and the
    intentional default since it needs no per-word distance computation).
    Fuzzy mode: each unquoted word must equal, or be within
    `_fuzzy_threshold()` edits of, at least one real word in the meeting's
    tokenized text -- catches transcription typos ("trafic", "traffiq" for
    "traffic") that a substring search would silently miss. Quoted
    phrases are always matched as an exact adjacent substring, even in
    fuzzy mode -- phrase-level fuzzy matching (an adjacent run of
    near-matching words) is a meaningfully harder problem than this
    solves, and quoting a phrase is itself a reasonable signal the caller
    wants a literal match. Exclusions are always checked as an exact
    substring too, regardless of `fuzzy` -- a fuzzy exclusion risks
    dropping a meeting that doesn't actually contain the excluded term,
    just something near it, which is a worse failure mode than an
    exclusion occasionally missing a typo'd instance of the excluded word.
    """
    phrases, terms, excluded_phrases, excluded_terms = _parse_query(query)
    if not phrases and not terms and not excluded_phrases and not excluded_terms:
        return True

    if any(phrase in corpus for phrase in excluded_phrases):
        return False
    if any(term in corpus for term in excluded_terms):
        return False

    if not all(phrase in corpus for phrase in phrases):
        return False

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


def _build_snippet(text: str, span: tuple, window: int) -> str:
    start, end = span
    win_start = max(0, start - window)
    win_end = min(len(text), end + window)
    prefix = "…" if win_start > 0 else ""
    suffix = "…" if win_end < len(text) else ""
    before = html.escape(text[win_start:start])
    matched = html.escape(text[start:end])
    after = html.escape(text[end:win_end])
    return f"{prefix}{before}<mark class=\"search-match\">{matched}</mark>{after}{suffix}"


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
    Quoted phrases are checked before unquoted words within each text,
    so a phrase match wins the snippet when both would otherwise match --
    it's the more specific, more relevant hit.

    Returned string already has its plain-text portions HTML-escaped,
    with only the deliberately-inserted <mark> tag left raw -- callers
    should render it with a "safe"/no-further-escaping filter.
    """
    phrases, terms, _excluded_phrases, _excluded_terms = _parse_query(query)
    if not phrases and not terms:
        return None

    for text in texts:
        if not text:
            continue
        text_lower = text.lower()
        for phrase in phrases:
            # Always exact, even in fuzzy mode -- see matches()'s docstring.
            span = _find_span(phrase, text_lower, fuzzy=False)
            if span:
                return _build_snippet(text, span, window)
        for term in terms:
            span = _find_span(term, text_lower, fuzzy)
            if span:
                return _build_snippet(text, span, window)

    return None


def find_matching_segment(query: str, segments: Iterable[dict], fuzzy: bool, window: int = 50) -> Optional[dict]:
    """Like `find_snippet()`, but per-*segment* rather than over one
    joined blob -- built for archive/search_alerts.py's saved-search
    alert emails, which need to deep-link to the exact matching moment
    (a real segment's own `start` timestamp), not just show an excerpt.
    `find_snippet`/`_find_span` above have no concept of segment
    boundaries (they run against `" ".join(seg["text"] for seg in
    segments)`), so there's no way to recover *which* segment a match
    came from, or its timestamp, from them alone.

    `segments` is the same `[{"start": float, "end": float, "text": str},
    ...]` shape TranscriptVersion.segments already stores. Checked in
    index order (chronological, since segments are always stored that
    way); returns the *first* matching segment, same "first match wins"
    convention as `find_snippet()`. Phrases checked before words within
    each segment, same precedence. Returns None when no segment's own
    text matches -- e.g. the query only matched the meeting's title/
    agenda text, or `query` is a keyword-less filter search with no real
    search terms at all -- callers should fall back to a plain title/
    date/link line with no quote in that case.
    """
    phrases, terms, _excluded_phrases, _excluded_terms = _parse_query(query or "")
    if not phrases and not terms:
        return None

    for index, segment in enumerate(segments):
        text = segment.get("text") or ""
        if not text:
            continue
        text_lower = text.lower()
        for phrase in phrases:
            span = _find_span(phrase, text_lower, fuzzy=False)
            if span:
                return {"index": index, "start": segment.get("start"), "quote_html": _build_snippet(text, span, window)}
        for term in terms:
            span = _find_span(term, text_lower, fuzzy)
            if span:
                return {"index": index, "start": segment.get("start"), "quote_html": _build_snippet(text, span, window)}

    return None
