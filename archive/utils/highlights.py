"""Pick the one moment worth quoting out of a multi-hour meeting.

The state pages and jurisdiction hubs need *unique, real text* per page
-- Search Console measured Google declining hub pages at 3.1-3.6x their
sitemap share while indexing `/m/` meeting pages better than theirs (see
`BACKLOG.md`), and the diagnosis was thin templated content, not
crawl plumbing. A list of meeting titles is templated; a genuine quote
from inside the meeting, deep-linked to the second it was said, is not.

This differs from `archive/utils/search.py`'s `find_snippet()` /
`find_matching_segment()` in one way that matters: those answer "where
does this *query* appear", and there is no query here. Nobody typed
anything -- the page just has to choose. So this module scores every
candidate window against what a *reader* finds substantive, and picks
the winner.

What the scoring encodes, learned from a dry run over 24 real
California transcripts before any of it was built (see this module's
tests for the frozen cases):

* **Procedure is the enemy.** Roll call, "motion", "second", "all in
  favor", "you have three minutes" -- a naive "longest segment" or
  "first segment" pick lands in this material almost every time, since
  it is most of a meeting by volume. Heavily negative.
* **Substance sounds like people.** Dollar figures, "residents",
  "concerned", "we need", percentages, named consequences. Positive.
* **A curated topic hit is the strongest signal available** (see
  `archive/topics.py`) and doubles as the reason a snippet is worth
  showing at all.
* **Meetings open and close with ceremony.** The first ~8% and last ~3%
  are skipped outright.
* **Public comment is where the quotable moments are.** When the
  transcript contains a recognizable "public comment" marker, windows
  after it get a bonus -- a resident explaining why they drove down at
  9pm beats a staff report every time.

Deliberately *not* an LLM call: this runs for every meeting at ingest,
must be deterministic so a re-run doesn't churn stored text, and has to
be explainable when a bad snippet reaches a public page.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional

from archive.topics import TOPICS, any_topic_pattern, topic_pattern, topics_in

# Target snippet length. ~220 chars is about two spoken sentences: long
# enough that Google sees real prose rather than a fragment, short
# enough to render in a card without a "read more".
TARGET_CHARS = 220
MAX_CHARS = 420

# Fractions of total duration skipped at each end (ceremony/adjournment).
SKIP_HEAD_FRACTION = 0.08
SKIP_TAIL_FRACTION = 0.03

# A window needs this many words to be scored at all -- below it there
# isn't enough context for a reader to understand the quote.
MIN_WORDS = 25

_PROCEDURAL = re.compile(
    r"\b(?:"
    r"motion|seconded?|all in favor|opposed|abstain|aye|nay|roll call|"
    r"carries unanimously|motion carries|consent calendar|consent agenda|"
    r"approve the minutes|item (?:number )?\d+|agenda item|"
    r"good (?:morning|evening|afternoon)|thank you very much|"
    r"call(?:ing)? (?:this|the) meeting to order|pledge of allegiance|"
    r"moment of silence|adjourn(?:ed|ment)?|we(?:'re| are) in recess|"
    r"please state your name|state your name and address|"
    r"you(?:'ll| will)? have (?:two|three|one) minutes?|your time (?:is up|has expired)|"
    r"any further discussion|hearing none|so ordered|present|here"
    r")\b",
    re.IGNORECASE,
)

_SUBSTANTIVE = re.compile(
    r"\b(?:"
    r"residents?|neighbors?|neighborhood|families|constituents?|taxpayers?|"
    r"we need|i(?:'m| am) concerned|concerns?|concerned|unacceptable|"
    r"\$[\d,]+(?:\.\d+)?|\d+(?:\.\d+)? ?(?:million|billion|percent)|\d{1,3}%|"
    r"safety|children|kids|seniors?|crisis|emergency|lawsuit|liability|"
    r"affordable|displaced?|displacement|contract|budget|revenue|"
    r"environmental|impact report|study|evidence|"
    r"oppose|support|urge you|ask(?:ing)? (?:you|the council|the board)"
    r")\b",
    re.IGNORECASE,
)

# Marks the start of a public-comment stretch. Any of these appearing in
# a segment moves the "public comment has begun" line to that timestamp.
_PUBLIC_COMMENT_START = re.compile(
    r"\b(?:"
    r"public comment|public comments|comment from the public|"
    r"open (?:it |this )?(?:up )?(?:to|for) public|"
    r"anyone (?:wishing|who wishes) to (?:speak|address)|"
    r"speaker cards?|first speaker|next speaker"
    r")\b",
    re.IGNORECASE,
)
PUBLIC_COMMENT_BONUS = 3.0

# Caption artifacts that should never reach a public page. Removed from
# the *display* text only -- scoring sees the cleaned text too, so a
# window that is mostly artifacts scores itself out naturally.
_ARTIFACTS = re.compile(
    r"\[\s*(?:buzzer|applause|laughter|inaudible|music|silence|crosstalk)[^\]]*\]"
    r"|\(\s*(?:inaudible|indiscernible|crosstalk)[^)]*\)"
    r"|&gt;&gt;|>>|&raquo;|»|«",
    re.IGNORECASE,
)
_WHITESPACE = re.compile(r"\s+")

# Function words, for the coherence guards below. Not a linguistic
# stopword list -- just enough that "as well as" reads as structure while
# "flock data will" reads as content.
_FUNCTION_WORDS = frozenset(
    """a an and or of to in for on at is are was were be been being it that this
    these those we you they i he she our your their its as with by from not no so
    but if then than have has had do does did will would can could should may
    might must about into over under more most some any all one two there here
    what which who when where how very just also which""".split()
)


def _content_words(text: str) -> list[str]:
    return [
        word
        for word in (w.lower().strip(".,?!;:\"'()") for w in text.split())
        if word and len(word) > 2 and word not in _FUNCTION_WORDS
    ]


def _repetition_penalty(text: str) -> float:
    """Penalize the two shapes of broken caption text that survive
    everything upstream and still read as gibberish on a public page.

    Both thresholds were set against real snippets this heuristic
    actually produced (see tests), not chosen a priori:

    1. **A hammered content word** -- Mission Viejo, CA produced "...it
       talks about the personal data and it says personal data includes
       personal data, personal information, personally identifiable",
       where one word is 24% of the content. Good snippets in the same
       sample topped out at 15%.
    2. **A repeated content-bearing phrase** -- interleaved roll-up
       captions restate a phrase out of order ("Five flock data will" in
       San Diego, CA). Trigrams made only of function words are exempt,
       because "as well as" recurring is ordinary English and appears in
       perfectly good snippets.
    """
    words = _content_words(text)
    if not words:
        return 0.0
    penalty = 0.0
    top = max(words.count(word) for word in set(words))
    if top / len(words) > 0.18:
        penalty += 6.0
    tokens = [w.lower().strip(".,?!;:\"'()") for w in text.split()]
    seen: set[tuple] = set()
    for index in range(len(tokens) - 2):
        gram = tuple(tokens[index : index + 3])
        if sum(1 for token in gram if token not in _FUNCTION_WORDS) < 2:
            continue
        if gram in seen:
            # As heavy as the hammered-word penalty: an interleaved
            # roll-up window is long (it restates material), so it
            # accumulates substantive matches while reading as nonsense.
            # A lighter penalty left one scoring 7.56 against a clean
            # rival's 7.50 -- i.e. still winning.
            penalty += 6.0
            break
        seen.add(gram)
    return penalty


_REPEATED_PHRASE = re.compile(r"\b(.{18,}?)\s+\1\b", re.IGNORECASE)


def _dedupe_repeats(text: str) -> str:
    """Collapse an immediately-repeated phrase.

    Roll-up ("scrolling ticker") captions restate the previous line
    inside the next cue; WO-34 fixed the four platform shapes of this at
    parse time, but older stored transcripts predate that fix and a
    handful still carry the residue (confirmed live: Kapuskasing, ON
    reads "we're going to defer >> Well, I think that we're going to
    defer this"). Cheap to neutralize here so a re-transcription isn't a
    prerequisite for a clean snippet; runs repeatedly since collapsing
    one repeat can expose another."""
    for _ in range(3):
        collapsed = _REPEATED_PHRASE.sub(r"\1", text)
        if collapsed == text:
            break
        text = collapsed
    return text


def _clean_window(text: str) -> str:
    """The cheap half of clean_text(), for the scoring hot path.

    A long meeting yields tens of thousands of candidate windows, and
    profiling showed the two *expensive* cleanups -- the backtracking
    repeated-phrase collapse and the all-caps scan -- dominating the run
    at that volume while changing which window wins essentially never.
    So they are deferred to clean_text(), which runs on the handful of
    windows that actually get returned."""
    return _WHITESPACE.sub(" ", _ARTIFACTS.sub(" ", text or "")).strip()


def clean_text(text: str) -> str:
    """Strip caption artifacts and collapse whitespace. Also normalizes
    an ALL-CAPS track (several Granicus/Legistar feeds are caption-cased,
    e.g. Los Angeles) to sentence case for *display* -- an all-caps
    snippet reads as shouting on a page and as boilerplate to a crawler.
    Only applied when the window is overwhelmingly caps, so an ordinary
    sentence containing an acronym is left exactly as spoken."""
    out = _dedupe_repeats(_clean_window(text))
    letters = [c for c in out if c.isalpha()]
    if letters and sum(1 for c in letters if c.isupper()) / len(letters) > 0.9:
        out = _sentence_case(out)
    return out


def _sentence_case(text: str) -> str:
    lowered = text.lower()
    # Re-capitalize the first letter of the snippet and of each sentence.
    result = list(lowered)
    capitalize_next = True
    for i, ch in enumerate(result):
        if capitalize_next and ch.isalpha():
            result[i] = ch.upper()
            capitalize_next = False
        elif ch in ".?!":
            capitalize_next = True
    out = "".join(result)
    # Standalone "i" -> "I".
    return re.sub(r"\bi\b", "I", out)


def _starts_sentence(segment: dict, previous: Optional[dict]) -> bool:
    text = (segment.get("text") or "").strip()
    if not text:
        return False
    if previous is None:
        return True
    prev_text = (previous.get("text") or "").rstrip()
    if prev_text.endswith((".", "?", "!")):
        return True
    # ">>" is the near-universal caption marker for a speaker change,
    # which is a sentence boundary even without punctuation -- and the
    # only such boundary available in the many tracks that carry no
    # sentence punctuation at all.
    return text.startswith(">>") or text.startswith("&gt;&gt;")


def _trim_to_sentence(text: str) -> str:
    """Cut a window at the *first* sentence end past ~60% of target, so a
    snippet stops as soon as it has said something complete rather than
    running on into whatever procedural chatter followed. Tracks with no
    sentence punctuation at all (several caption feeds have none) fall
    through to a hard character cut."""
    for match in re.finditer(r"[.?!](?=\s|$)", text):
        if match.end() >= TARGET_CHARS * 0.6:
            return text[: match.end()]
    return text[:MAX_CHARS]


def _windows(segments: list[dict]):
    """Yield (start_seconds, text) for every sentence-aligned window of
    roughly TARGET_CHARS. Slides one segment at a time rather than
    tiling, so the best moment isn't missed just because it straddles a
    fixed boundary."""
    for i, segment in enumerate(segments):
        if not _starts_sentence(segment, segments[i - 1] if i else None):
            continue
        parts: list[str] = []
        j = i
        while j < len(segments) and len(" ".join(parts)) < TARGET_CHARS:
            parts.append((segments[j].get("text") or "").strip())
            j += 1
        text = _clean_window(" ".join(parts))
        if text:
            yield float(segment.get("start") or 0.0), _trim_to_sentence(text)


def score_window(text: str, *, after_public_comment: bool = False) -> float:
    """How worth quoting this window is. Public, and deliberately simple
    arithmetic rather than a model: when a bad snippet lands on a public
    page, someone has to be able to read this and say why."""
    words = text.split()
    if len(words) < MIN_WORDS:
        return -1.0
    score = 0.0
    score -= 3.0 * len(_PROCEDURAL.findall(text))
    score += 1.5 * len(_SUBSTANTIVE.findall(text))
    # One combined alternation rather than 20 separate searches: at tens
    # of thousands of windows per meeting the per-topic breakdown is pure
    # waste here, and it is recovered exactly where it is needed (on the
    # windows actually returned) by topics_in().
    score += 2.0 * len(any_topic_pattern().findall(text))
    if after_public_comment:
        score += PUBLIC_COMMENT_BONUS
    # Prefer a window that begins where a sentence begins. Many caption
    # tracks carry no punctuation, so this can only ever be a nudge --
    # a genuinely better mid-sentence quote still wins, and display_text()
    # marks it with a leading ellipsis rather than pretending otherwise.
    if text[:1].isupper():
        score += 1.0
    # Reward fuller sentences, capped. Tracks with no punctuation get one
    # "sentence" and so a flat small bonus -- fine, it's the same for
    # every window in that transcript.
    sentences = [s for s in re.split(r"[.?!]", text) if s.strip()]
    if sentences:
        score += min(3.0, (len(words) / len(sentences)) / 8.0)
    # Repetition/garble guard: a stuck caption ("okay okay okay") or a
    # Whisper hallucination loop has very low unique-word density.
    unique_ratio = len(({w.lower() for w in words})) / len(words)
    if unique_ratio < 0.5:
        score -= 5.0
    score -= _repetition_penalty(text)
    return score


def _public_comment_start(segments: list[dict]) -> Optional[float]:
    for segment in segments:
        if _PUBLIC_COMMENT_START.search(segment.get("text") or ""):
            return float(segment.get("start") or 0.0)
    return None


def _candidate_windows(segments: list[dict]) -> list[tuple[float, float, str]]:
    """(score, start, text) for every in-bounds window, best-first."""
    if not segments:
        return []
    last = segments[-1]
    duration = float(last.get("end") or last.get("start") or 0.0)
    low = duration * SKIP_HEAD_FRACTION
    high = duration * (1.0 - SKIP_TAIL_FRACTION)
    # A short meeting (or one with unusable timestamps) would have every
    # window filtered out by the bounds; fall back to the whole thing.
    if high <= low:
        low, high = 0.0, float("inf")
    comment_start = _public_comment_start(segments)
    scored: list[tuple[float, float, str]] = []
    for start, text in _windows(segments):
        if not (low <= start <= high):
            continue
        after = comment_start is not None and start >= comment_start
        scored.append((score_window(text, after_public_comment=after), start, text))
    scored.sort(key=lambda row: (-row[0], row[1]))
    return scored


def pick_highlight(
    segments: Iterable[dict], _scored: Optional[list] = None
) -> Optional[dict]:
    """The single best moment in a meeting, as
    `{"start": float, "text": str, "topics": [slug, ...]}` -- or None
    when the transcript has nothing quotable (too short, empty, or
    entirely procedural). `start` is a real segment's own timestamp, so
    it deep-links to the exact second: `/m/{slug}?t={int(start)}`."""
    if _scored is None:
        segments = [s for s in (segments or []) if (s.get("text") or "").strip()]
        _scored = _candidate_windows(segments)
    if not _scored:
        return None
    score, start, text = _scored[0]
    if score <= 0:
        return None
    text = clean_text(text)
    return {"start": start, "text": text, "topics": topics_in(text)}


def pick_topic_moments(
    segments: Iterable[dict], _scored: Optional[list] = None
) -> dict[str, dict]:
    """The best moment *per topic present in the meeting*, as
    `{slug: {"start": float, "text": str}}`.

    Stored alongside the default highlight at ingest so a `?topic=` view
    needs no transcript load at request time -- the whole point, since a
    crawler walks every topic x state combination and each would
    otherwise decode multiple megabytes of segment JSON.

    A topic only appears here when a window genuinely containing its
    phrase also scores positively, so a passing mention buried in a
    consent calendar doesn't become a featured quote."""
    if _scored is None:
        segments = [s for s in (segments or []) if (s.get("text") or "").strip()]
        _scored = _candidate_windows(segments)
    if not _scored:
        return {}
    # Only windows that can score at all are worth scanning per topic.
    positive = [row for row in _scored if row[0] > 0]
    moments: dict[str, dict] = {}
    for topic in TOPICS:
        pattern = topic_pattern(topic.slug)
        for _score, start, text in positive:  # already best-first
            if pattern.search(text):
                moments[topic.slug] = {"start": start, "text": clean_text(text)}
                break
    return moments


def compute_highlight_payload(all_segments: Iterable[Any]) -> dict:
    """What gets stored for one meeting page: the default highlight plus
    every topic moment, from every transcript version's segments merged
    in timestamp order. Callers pass the same `all_segments` shape
    `crud._refresh_search_corpus()` already gathers (a list of per-version
    segment lists)."""
    merged: list[dict] = []
    for version_segments in all_segments or []:
        for segment in version_segments or []:
            if isinstance(segment, dict) and (segment.get("text") or "").strip():
                merged.append(segment)
    merged.sort(key=lambda s: float(s.get("start") or 0.0))
    # Scored once, shared by both pickers -- they used to each rebuild the
    # full window set, which doubled the cost of the whole computation.
    scored = _candidate_windows(merged)
    highlight = pick_highlight(merged, _scored=scored)
    return {
        "highlight": highlight,
        "topic_moments": pick_topic_moments(merged, _scored=scored) if highlight else {},
    }


def display_text(text: str) -> str:
    """The snippet as it should render. Adds a leading ellipsis when the
    quote starts mid-sentence, so a reader (and a crawler) can tell an
    excerpt from a complete thought, and a trailing one when it was cut
    at the character limit rather than at a sentence end."""
    if not text:
        return ""
    prefix = "" if (text[:1].isupper() or text[:1].isdigit()) else "\u2026"
    suffix = "" if text.rstrip()[-1:] in ".?!" else "\u2026"
    return f"{prefix}{text}{suffix}"


def highlight_html(text: str, topic_slugs: Iterable[str] = ()) -> str:
    """`text` as escaped HTML with each topic phrase wrapped in `<mark>`.

    Escaping happens first and matching runs against the *escaped*
    string, which is safe because every curated phrase is plain
    alphanumerics and spaces -- no pattern can match across an entity
    that escaping introduced, and no transcript text can inject markup.

    Callers render the result with `|safe`; it is the only HTML this
    module produces.
    """
    import html as _html

    escaped = _html.escape(display_text(text))
    spans: list[tuple[int, int]] = []
    for slug in topic_slugs or ():
        try:
            pattern = topic_pattern(slug)
        except KeyError:
            continue
        spans.extend((m.start(), m.end()) for m in pattern.finditer(escaped))
    if not spans:
        return escaped
    # Merge overlaps so two topics sharing a phrase can't nest <mark>s.
    spans.sort()
    merged: list[list[int]] = [list(spans[0])]
    for start, end in spans[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    out: list[str] = []
    cursor = 0
    for start, end in merged:
        out.append(escaped[cursor:start])
        out.append(f"<mark>{escaped[start:end]}</mark>")
        cursor = end
    out.append(escaped[cursor:])
    return "".join(out)
