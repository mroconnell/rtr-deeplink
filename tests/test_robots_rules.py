"""app/utils/robots_rules.py: RFC 9309 matching, the same rules as rtr-findmeeting's
findmeeting/robotsrules.py (Ryan, 2026-10-02)."""

from app.utils.robots_rules import is_allowed, matching_rule, parse_rules

CABLECAST = """# Let bots crawl pages, but not media files/streams.
User-agent: *
Disallow: /*.m3u8$
Disallow: /*.m3u8?
Disallow: /*.ts$
Disallow: /*.mp4$
Disallow: /*.vtt$
"""


def test_cablecast_media_rules_block_media_and_not_pages():
    rules = parse_rules(CABLECAST)
    assert not is_allowed(rules, "/vod/6013-City-Council/vod.mp4")
    assert not is_allowed(rules, "/vod/6013-City-Council/vod.m3u8?x=1")
    assert is_allowed(rules, "/internetchannel/show/6013")
    assert is_allowed(rules, "/cablecastapi/v1/shows/6013")


def test_a_page_path_rule_blocks_too():
    rules = parse_rules("User-agent: *\nDisallow: /Archive.aspx\n")
    assert not is_allowed(rules, "https://x.civicplus.com/Archive.aspx?ADID=77")
    assert is_allowed(rules, "/AgendaCenter")


def test_longest_match_wins_and_allow_wins_a_tie():
    rules = parse_rules("User-agent: *\nDisallow: /a/\nAllow: /a/public/\n")
    assert not is_allowed(rules, "/a/secret")
    assert is_allowed(rules, "/a/public/x")
    tie = parse_rules("User-agent: *\nDisallow: /*.mp4$\nAllow: /*.mp4$\n")
    assert is_allowed(tie, "/a.mp4")


def test_our_product_token_beats_the_star_group():
    text = (
        "User-agent: *\nDisallow: /\n\nUser-agent: rtr-upcoming\nDisallow: /private/\n"
    )
    rules = parse_rules(text)
    assert is_allowed(rules, "/meetings")
    assert not is_allowed(rules, "/private/x")


def test_other_agents_only_means_no_rules_for_us():
    assert is_allowed(parse_rules("User-agent: Googlebot\nDisallow: /\n"), "/x")
    assert is_allowed(parse_rules(""), "/x")
    assert is_allowed(None, "/x")


def test_empty_disallow_allows_everything_and_whole_site_blocks():
    assert is_allowed(parse_rules("User-agent: *\nDisallow:\n"), "/x")
    assert not is_allowed(parse_rules("User-agent: *\nDisallow: /\n"), "/x")


def test_matching_rule_names_the_deciding_rule():
    rules = parse_rules(CABLECAST)
    allowed, rule = matching_rule(rules, "/a/vod.mp4")
    assert allowed is False and rule.pattern == "/*.mp4$"
    assert matching_rule(rules, "/a/page") == (True, None)


def test_percent_encoding_spelling_does_not_matter():
    rules = parse_rules("User-agent: *\nDisallow: /~user/\n")
    assert not is_allowed(rules, "/%7Euser/page")
