"""Tests for archive/utils/email.py's _digest_subject() -- the saved-search
alert digest's email subject line.

Found 2026-08-22 while confirming P5 against the real inbox: a phrase or
boolean search is stored with its own quotes as part of the keyword, but
_digest_subject() unconditionally wrapped it in another pair, producing
real, sent, doubled-quote subjects:

    Somebody said ""affordable housing"" (+13 more)
    Somebody said ""Neighborhood character" or "Character of the
    neighborhood"" (+12 more)

(both real production emails, 2026-08-20/21). Plain single-word searches
have no embedded quotes and were unaffected, which is presumably why it
shipped unnoticed.
"""

from archive.utils.email import _digest_subject


def test_plain_keyword_gets_single_quote_pair():
    groups = [{"keyword": "data center", "matches": [{}]}]
    assert _digest_subject(groups) == 'Somebody said "data center"'


def test_phrase_search_keyword_does_not_double_quote():
    # Real case: "affordable housing" (2026-08-20 production digest).
    groups = [{"keyword": '"affordable housing"', "matches": [{}] * 14}]
    assert _digest_subject(groups) == 'Somebody said "affordable housing" (+13 more)'


def test_boolean_or_search_keyword_does_not_double_quote():
    # Real case: 2026-08-21 production digest.
    groups = [
        {
            "keyword": '"Neighborhood character" or "Character of the neighborhood"',
            "matches": [{}] * 13,
        }
    ]
    assert _digest_subject(groups) == (
        'Somebody said "Neighborhood character" or '
        '"Character of the neighborhood" (+12 more)'
    )


def test_no_keyword_falls_back_to_generic_count_subject():
    groups = [{"keyword": None, "matches": [{}, {}]}]
    assert _digest_subject(groups) == "2 new meetings match your saved searches"
