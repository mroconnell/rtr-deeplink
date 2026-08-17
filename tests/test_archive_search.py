from archive.utils.search import (
    build_corpus,
    compute_search_corpus,
    find_matching_segment,
    find_snippet,
    matches,
    tokenize,
)


def test_exact_search_is_plain_substring():
    corpus = build_corpus(
        "City Council Meeting", "Dublin, CA", "discussion of traffic signals downtown"
    )
    assert matches("traffic", corpus, set(), fuzzy=False)
    assert matches("TRAFFIC", corpus, set(), fuzzy=False)
    assert not matches("trafic", corpus, set(), fuzzy=False)


def test_exact_search_requires_every_term():
    corpus = build_corpus(
        "City Council Meeting", "Dublin, CA", "discussion of traffic signals downtown"
    )
    assert matches("traffic downtown", corpus, set(), fuzzy=False)
    assert not matches("traffic uptown", corpus, set(), fuzzy=False)


def test_fuzzy_search_tolerates_transcription_typos():
    corpus = build_corpus(
        "", "", "the council discussed trafic signals near the school"
    )
    words = tokenize(corpus)
    # Motivating example from the user request: "traffic" should still
    # match a transcript that actually says "trafic" (1 char short) or
    # "traffiq" (1 char substituted).
    assert matches("traffic", corpus, words, fuzzy=True)

    corpus2 = build_corpus(
        "", "", "the council discussed traffiq signals near the school"
    )
    words2 = tokenize(corpus2)
    assert matches("traffic", corpus2, words2, fuzzy=True)


def test_fuzzy_search_does_not_match_unrelated_words():
    corpus = build_corpus("", "", "the council discussed parking permits downtown")
    words = tokenize(corpus)
    assert not matches("traffic", corpus, words, fuzzy=True)


def test_fuzzy_search_does_not_fuzz_short_words_into_noise():
    # Short words (<=4 chars) require an exact token match -- otherwise a
    # search for "cat" would fuzzily match "car", "can", "cap", etc.
    corpus = build_corpus("", "", "the cars were parked near city hall")
    words = tokenize(corpus)
    assert not matches("cat", corpus, words, fuzzy=True)
    assert matches("cars", corpus, words, fuzzy=True)


def test_find_snippet_returns_context_around_exact_match():
    text = "There was a long discussion of traffic calming measures on Elm Street before the vote."
    snippet = find_snippet("traffic", [text], fuzzy=False)
    assert snippet is not None
    assert '<mark class="search-match">traffic</mark>' in snippet
    assert "Elm Street" in snippet


def test_find_snippet_uses_real_word_for_fuzzy_match_not_query_term():
    # The source text really says "trafic" (typo) -- the snippet should
    # quote that real word, not silently "correct" it to the query term.
    text = "the council discussed trafic signals near the school today"
    snippet = find_snippet("traffic", [text], fuzzy=True)
    assert snippet is not None
    assert '<mark class="search-match">trafic</mark>' in snippet
    assert (
        "traffic" not in snippet.split("<mark")[0]
    )  # query term itself not injected verbatim


def test_find_snippet_checks_texts_in_order_and_skips_empty():
    snippet = find_snippet(
        "traffic", ["", "no match here", "a note about traffic calming"], fuzzy=False
    )
    assert snippet is not None
    assert "a note about" in snippet and "calming" in snippet


def test_find_snippet_returns_none_when_no_text_matches():
    assert find_snippet("traffic", ["parking permits downtown"], fuzzy=False) is None
    assert find_snippet("traffic", [], fuzzy=False) is None
    assert find_snippet("traffic", [None, ""], fuzzy=False) is None


def test_find_snippet_html_escapes_surrounding_text_but_not_the_mark_tag():
    text = "the agenda says <b>bold</b> traffic notice & more context here"
    snippet = find_snippet("traffic", [text], fuzzy=False)
    assert snippet is not None
    assert "&lt;b&gt;" in snippet
    assert "&amp;" in snippet
    assert '<mark class="search-match">traffic</mark>' in snippet


def test_find_snippet_adds_ellipsis_only_when_text_is_truncated():
    short_text = "just traffic here"
    snippet = find_snippet("traffic", [short_text], fuzzy=False, window=50)
    assert snippet is not None
    assert "…" not in snippet

    long_text = "x" * 100 + " traffic " + "y" * 100
    snippet2 = find_snippet("traffic", [long_text], fuzzy=False, window=20)
    assert snippet2 is not None
    assert snippet2.count("…") == 2


def test_quoted_phrase_requires_adjacent_match():
    corpus = build_corpus(
        "City Council Meeting",
        "Anytown, USA",
        "the city discussed a new data center project",
    )
    assert matches('"data center"', corpus, set(), fuzzy=False)
    # Same two words present, but not adjacent -- must not match as a phrase.
    corpus2 = build_corpus(
        "", "", "the data we collected pointed to the community center"
    )
    assert not matches('"data center"', corpus2, set(), fuzzy=False)


def test_unquoted_multiword_search_is_still_and_not_phrase():
    # Confirms the fix didn't change existing unquoted behavior: both
    # words required, but not necessarily adjacent.
    corpus = build_corpus(
        "", "", "the data we collected pointed to the community center"
    )
    assert matches("data center", corpus, set(), fuzzy=False)


def test_quoted_phrase_combined_with_unquoted_word():
    corpus = build_corpus(
        "", "", "the city approved a new data center near downtown parking"
    )
    assert matches('"data center" parking', corpus, set(), fuzzy=False)
    assert not matches('"data center" airport', corpus, set(), fuzzy=False)


def test_quoted_phrase_missing_entirely_fails_even_if_words_present():
    corpus = build_corpus(
        "", "", "data was presented near the new community center today"
    )
    assert not matches('"data center"', corpus, set(), fuzzy=False)


def test_quoted_phrase_is_case_insensitive():
    corpus = build_corpus("", "", "plans for a new Data Center were approved")
    assert matches('"data center"', corpus, set(), fuzzy=False)


def test_unclosed_quote_does_not_crash_and_falls_back_to_word_match():
    corpus = build_corpus("", "", "the council discussed data center plans")
    # No closing quote -- treated as a literal, unmatched word (same
    # "quoting made it worse" behavior as before this fix, but scoped to
    # just that one malformed term rather than the whole query).
    assert not matches('"data center', corpus, set(), fuzzy=False)


def test_empty_quoted_phrase_is_ignored():
    corpus = build_corpus("", "", "the council discussed budget items")
    assert matches('""', corpus, set(), fuzzy=False)


def test_find_snippet_matches_quoted_phrase():
    text = "The council approved a new data center project downtown after debate."
    snippet = find_snippet('"data center"', [text], fuzzy=False)
    assert snippet is not None
    assert '<mark class="search-match">data center</mark>' in snippet


def test_find_snippet_prefers_phrase_match_over_word_match_in_same_text():
    text = "Data was reviewed. Later, the new community center was approved."
    snippet = find_snippet('center "data center"', [text], fuzzy=False)
    assert snippet is not None
    # Should find the (non-adjacent) phrase nowhere in this text and fall
    # back cleanly rather than mis-highlighting "center" alone as if it
    # were the phrase.
    assert '<mark class="search-match">center</mark>' in snippet


def test_find_snippet_phrase_is_exact_even_in_fuzzy_mode():
    text = "the council discussed a new data center project today"
    # A near-miss phrase (typo'd word inside quotes) should NOT match even
    # with fuzzy=True -- phrases are always literal.
    assert find_snippet('"data centre"', [text], fuzzy=True) is None


def test_minus_prefix_excludes_meetings_containing_the_word():
    corpus = build_corpus(
        "City Council Meeting",
        "Dublin, CA",
        "discussion of traffic signals and parking",
    )
    assert matches("traffic", corpus, set(), fuzzy=False)
    assert not matches("traffic -parking", corpus, set(), fuzzy=False)


def test_minus_prefix_excludes_meetings_containing_the_phrase():
    corpus = build_corpus("", "", "the council approved a new data center project")
    assert not matches('-"data center"', corpus, set(), fuzzy=False)
    corpus2 = build_corpus("", "", "the council approved a new budget item")
    assert matches('-"data center"', corpus2, set(), fuzzy=False)


def test_minus_exclusion_is_exact_even_in_fuzzy_mode():
    # The corpus contains a near-miss ("trafic", not "traffic") -- an exact
    # exclusion should not treat that as a match, so this meeting should
    # still be included.
    corpus = build_corpus("", "", "the council discussed trafic calming near downtown")
    words = tokenize(corpus)
    assert matches("downtown -traffic", corpus, words, fuzzy=True)


def test_plus_prefix_is_a_no_op_since_words_are_already_required():
    corpus = build_corpus(
        "City Council Meeting", "Dublin, CA", "discussion of traffic signals downtown"
    )
    assert matches("+traffic +downtown", corpus, set(), fuzzy=False)
    assert not matches("+traffic +uptown", corpus, set(), fuzzy=False)


def test_bare_and_ampersand_are_no_ops():
    corpus = build_corpus(
        "City Council Meeting", "Dublin, CA", "discussion of traffic signals downtown"
    )
    assert matches("traffic AND downtown", corpus, set(), fuzzy=False)
    assert matches("traffic & downtown", corpus, set(), fuzzy=False)


def test_find_matching_segment_returns_the_first_matching_segment():
    segments = [
        {"start": 0.0, "end": 5.0, "text": "call to order"},
        {"start": 5.0, "end": 12.0, "text": "discussion of traffic signals downtown"},
        {"start": 12.0, "end": 20.0, "text": "more traffic talk here too"},
    ]
    result = find_matching_segment("traffic", segments, fuzzy=False)
    assert result["index"] == 1
    assert result["start"] == 5.0
    assert "<mark" in result["quote_html"]


def test_find_matching_segment_returns_none_when_no_segment_matches():
    # The query only matches the meeting's title/agenda, not any segment.
    segments = [{"start": 0.0, "end": 5.0, "text": "call to order"}]
    assert find_matching_segment("traffic", segments, fuzzy=False) is None


def test_find_matching_segment_returns_none_for_a_keyword_less_query():
    segments = [{"start": 0.0, "end": 5.0, "text": "discussion of traffic signals"}]
    assert find_matching_segment("", segments, fuzzy=False) is None
    assert find_matching_segment(None, segments, fuzzy=False) is None


def test_find_matching_segment_respects_fuzzy_flag():
    segments = [
        {"start": 0.0, "end": 5.0, "text": "the council discussed trafic calming"}
    ]
    assert find_matching_segment("traffic", segments, fuzzy=False) is None
    result = find_matching_segment("traffic", segments, fuzzy=True)
    assert result["index"] == 0


def test_compute_search_corpus_matches_build_corpus_query_time_shape():
    # compute_search_corpus() precomputes what list_pages() otherwise
    # assembles at query time via build_corpus() -- same title/jurisdiction/
    # agenda/transcript fields, same lowercased join, just from an
    # agenda_items list + multiple TranscriptVersion.segments lists instead
    # of already-flattened strings.
    all_segments = [
        [{"start": 0.0, "end": 5.0, "text": "discussion of traffic signals"}],
        [{"start": 0.0, "end": 5.0, "text": "downtown parking permits"}],
    ]
    corpus = compute_search_corpus(
        "City Council Meeting",
        "Dublin, CA",
        [{"text": "Item 1: Traffic Calming"}],
        all_segments,
    )
    expected = build_corpus(
        "City Council Meeting",
        "Dublin, CA",
        "Item 1: Traffic Calming",
        "discussion of traffic signals downtown parking permits",
    )
    assert corpus == expected
    assert matches("parking", corpus, set(), fuzzy=False)


def test_compute_search_corpus_includes_every_transcript_version():
    # Every linked TranscriptVersion's text counts, not just the default
    # one -- a demoted version's text (e.g. a superseded scraped caption)
    # must still be findable, matching list_pages()'s own documented
    # behavior for the query-time build_corpus() path.
    all_segments = [
        [{"start": 0.0, "end": 5.0, "text": "demoted garbled caption text"}],
        [{"start": 0.0, "end": 5.0, "text": "clean re-transcription text"}],
    ]
    corpus = compute_search_corpus(None, None, None, all_segments)
    assert matches("garbled", corpus, set(), fuzzy=False)
    assert matches("re-transcription", corpus, set(), fuzzy=False)


def test_compute_search_corpus_handles_missing_fields():
    assert compute_search_corpus(None, None, None, []) == ""
    assert compute_search_corpus(None, None, [], [[]]) == ""
    # A segment dict missing "text" shouldn't raise.
    corpus = compute_search_corpus("Title", None, None, [[{"start": 0.0, "end": 1.0}]])
    assert corpus == "title"


def test_or_is_a_no_op_token_for_parse_query_and_never_a_snippet_target():
    # Real report, 2026-08-17, first hour after Postgres full-text search
    # went live: "flock OR camera" returned the right pages (FTS reads the
    # raw query, where OR means either) but the snippet highlighter, which
    # still goes through parse_query(), treated "or" as a search word and
    # lit up the substring inside "For", "Order", "before" on pages that
    # had matched via "camera". parse_query() must drop it like and/&.
    from archive.utils.search import parse_query

    phrases, words, excluded_phrases, excluded_words = parse_query("flock OR camera")
    assert words == ["flock", "camera"]
    assert not phrases and not excluded_phrases and not excluded_words

    # A page matched via the second operand: snippet highlights "camera",
    # never an "or" buried in another word.
    text = "For the record, the order of business is the camera policy."
    snippet = find_snippet("flock OR camera", [text], fuzzy=False)
    assert snippet is not None
    assert '<mark class="search-match">camera</mark>' in snippet
    assert '<mark class="search-match">or</mark>' not in snippet.lower()

    # ...and a page with neither operand yields no snippet rather than a
    # bogus "or" hit.
    assert (
        find_snippet("flock OR camera", ["For the record, no match here."], fuzzy=False)
        is None
    )

    # LIKE-fallback semantics: OR degrades to AND (documented) -- both
    # operands present matches; only one present does not.
    both = build_corpus("T", "J", "flock of birds and a camera")
    one = build_corpus("T", "J", "just a camera here")
    assert matches("flock OR camera", both, set(), fuzzy=False)
    assert not matches("flock OR camera", one, set(), fuzzy=False)
