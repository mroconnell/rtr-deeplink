from archive.utils.search import build_corpus, matches, tokenize


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
