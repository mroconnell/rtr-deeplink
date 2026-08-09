from archive.utils.search import build_corpus, find_snippet, matches, tokenize


def test_exact_search_is_plain_substring():
    corpus = build_corpus("City Council Meeting", "Dublin, CA", "discussion of traffic signals downtown")
    assert matches("traffic", corpus, set(), fuzzy=False)
    assert matches("TRAFFIC", corpus, set(), fuzzy=False)
    assert not matches("trafic", corpus, set(), fuzzy=False)


def test_exact_search_requires_every_term():
    corpus = build_corpus("City Council Meeting", "Dublin, CA", "discussion of traffic signals downtown")
    assert matches("traffic downtown", corpus, set(), fuzzy=False)
    assert not matches("traffic uptown", corpus, set(), fuzzy=False)


def test_fuzzy_search_tolerates_transcription_typos():
    corpus = build_corpus("", "", "the council discussed trafic signals near the school")
    words = tokenize(corpus)
    # Motivating example from the user request: "traffic" should still
    # match a transcript that actually says "trafic" (1 char short) or
    # "traffiq" (1 char substituted).
    assert matches("traffic", corpus, words, fuzzy=True)

    corpus2 = build_corpus("", "", "the council discussed traffiq signals near the school")
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
    assert "traffic" not in snippet.split("<mark")[0]  # query term itself not injected verbatim


def test_find_snippet_checks_texts_in_order_and_skips_empty():
    snippet = find_snippet("traffic", ["", "no match here", "a note about traffic calming"], fuzzy=False)
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
