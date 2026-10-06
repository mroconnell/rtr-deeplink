"""Tests for scripts/pin_audit_store_rules.py (R3 channel coherence, R4 store disagreement).

SYNTHETIC: every AuditData below is hand built, not read from a store. The
facts inside are real: Sunnyside WA (us:place:5368750) and Sunnyside, NL
(ca:csd:1001277) are the two real governments confused on
sunnyside.primegov.com on 2026-10-05; San Francisco is a real consolidated
city-county (us:county:06075 and us:place:0667000 are one government);
King County and Seattle are real WA governments; WA borders ID and not FL.
No real pin has been fabricated: the tests only exercise one logic branch
each.
"""

from scripts import pin_audit_core as core
from scripts import pin_audit_store_rules as rules
from scripts.pin_audit_core import AuditData, Page, Pin

SUNNYSIDE_WA = "us:place:5368750"
SUNNYSIDE_NL = "ca:csd:1001277"
SF_COUNTY = "us:county:06075"
SF_PLACE = "us:place:0667000"
KING_COUNTY = "us:county:53033"
SEATTLE = "us:place:5363000"
SPOKANE = "us:place:5367000"
BOISE = "us:place:1608830"
MIAMI_FL = "us:place:1245000"


def pin(store, host, gov, match="", ref=None):
    return Pin(store, host, match, gov, ref=ref or f"{store}:{host}:{match}")


def page(pid, gov, source_host="", video_url="", channel=""):
    return Page(
        pid,
        gov,
        "Council",
        "",
        f"https://{source_host}/m" if source_host else "",
        video_url,
        source_host,
        "www.youtube.com" if video_url else "",
        channel,
    )


def data_of(pins, pages=()):
    d = AuditData(pins=list(pins), pages=list(pages))
    core.build_indexes(d)
    return d


def run(rule, d, judged):
    return rule(d, judged)


def test_gov_ids_exist():
    for g in (
        SUNNYSIDE_WA, SUNNYSIDE_NL, SF_COUNTY, SF_PLACE,
        KING_COUNTY, SEATTLE, SPOKANE, BOISE, MIAMI_FL,
    ):  # fmt: skip
        assert core.gov_info(g) is not None, g


def test_sunnyside_host_disagreement_is_high():
    p = pin(core.STORE_OVERRIDE, "sunnyside.primegov.com", SUNNYSIDE_NL)
    other = pin(core.STORE_DISCOVERY, "sunnyside.primegov.com", SUNNYSIDE_WA)
    pages = [
        page("1", SUNNYSIDE_WA, "sunnyside.primegov.com"),
        page("2", SUNNYSIDE_WA, "sunnyside.primegov.com"),
        page("3", SUNNYSIDE_WA, "sunnyside.primegov.com"),
        page("4", SUNNYSIDE_NL, "sunnyside.primegov.com"),
    ]
    flags = run(rules.rule_r4_store_disagreement, data_of([p, other], pages), [p])
    assert len(flags) == 1  # one flag per (pin, other government)
    f = flags[0]
    assert (f.rule, f.severity, f.other_gov_id) == ("R4", "high", SUNNYSIDE_WA)
    assert "3 of 4 Archive pages" in f.detail
    assert f.other_ref


def test_consolidated_pair_is_not_a_disagreement():
    p = pin(core.STORE_OVERRIDE, "sfgov.granicus.com", SF_COUNTY)
    other = pin(core.STORE_RESEARCH, "sfgov.granicus.com", SF_PLACE)
    pages = [page("1", SF_PLACE, "sfgov.granicus.com")]
    assert rules.same_gov(SF_COUNTY, SF_PLACE)
    assert run(rules.rule_r4_store_disagreement, data_of([p, other], pages), [p]) == []


def test_county_versus_town_in_one_state_is_low():
    p = pin(core.STORE_OVERRIDE, "kingcounty.example.gov", KING_COUNTY)
    other = pin(core.STORE_RESEARCH, "kingcounty.example.gov", SEATTLE)
    flags = run(rules.rule_r4_store_disagreement, data_of([p, other]), [p])
    assert [f.severity for f in flags] == ["low"]


def test_adjacent_state_is_medium_and_far_state_is_high():
    p = pin(core.STORE_OVERRIDE, "city.example.gov", SPOKANE)
    near = pin(core.STORE_RESEARCH, "city.example.gov", BOISE)  # WA vs ID
    flags = run(rules.rule_r4_store_disagreement, data_of([p, near]), [p])
    assert [f.severity for f in flags] == ["medium"]
    far = pin(core.STORE_RESEARCH, "city2.example.gov", MIAMI_FL)  # WA vs FL
    p2 = pin(core.STORE_OVERRIDE, "city2.example.gov", SPOKANE)
    flags = run(rules.rule_r4_store_disagreement, data_of([p2, far]), [p2])
    assert [f.severity for f in flags] == ["high"]


def test_same_state_other_government_is_medium():
    p = pin(core.STORE_OVERRIDE, "town.example.gov", SEATTLE)
    other = pin(core.STORE_RESEARCH, "town.example.gov", SPOKANE)
    flags = run(rules.rule_r4_store_disagreement, data_of([p, other]), [p])
    assert [f.severity for f in flags] == ["medium"]


def test_multi_gov_host_whole_host_is_skipped():
    host = "www.youtube.com"  # in registry.MULTI_GOV_HOSTS
    p = pin(core.STORE_QUEUE, host, SUNNYSIDE_NL)
    other = pin(core.STORE_RESEARCH, host, SUNNYSIDE_WA)
    assert run(rules.rule_r4_store_disagreement, data_of([p, other]), [p]) == []


def test_keyed_video_pin_compared_with_archive_page_of_that_video():
    vid = "vXvnuqAOpCQ"
    p = pin(core.STORE_OVERRIDE, "www.youtube.com", SUNNYSIDE_NL, f"youtube:{vid}")
    pg = page("9", SUNNYSIDE_WA, video_url=f"https://www.youtube.com/watch?v={vid}")
    flags = run(rules.rule_r4_store_disagreement, data_of([p], [pg]), [p])
    assert [(f.severity, f.other_gov_id) for f in flags] == [("high", SUNNYSIDE_WA)]


def test_keyed_pin_ignores_claims_with_a_different_match():
    p = pin(core.STORE_OVERRIDE, "www.youtube.com", SUNNYSIDE_NL, "youtube:vXvnuqAOpCQ")
    other = pin(
        core.STORE_OVERRIDE, "www.youtube.com", SUNNYSIDE_WA, "youtube:zzzzzzzzzzz"
    )
    assert run(rules.rule_r4_store_disagreement, data_of([p, other]), [p]) == []


def test_r3_video_pin_against_channel_pin_far_state_is_high():
    chan = pin(
        core.STORE_OVERRIDE,
        "www.youtube.com",
        SUNNYSIDE_WA,
        "channel=@cityofsunnysidewa",
    )
    vid = pin(
        core.STORE_OVERRIDE, "www.youtube.com", SUNNYSIDE_NL, "youtube:vXvnuqAOpCQ"
    )
    pg = page(
        "9",
        SUNNYSIDE_WA,
        video_url="https://www.youtube.com/watch?v=vXvnuqAOpCQ",
        channel="@cityofsunnysidewa",
    )
    d = data_of([chan, vid], [pg])
    flags = run(rules.rule_r3_channel_coherence, d, [vid])
    assert [(f.rule, f.severity, f.other_gov_id) for f in flags] == [
        ("R3", "high", SUNNYSIDE_WA)
    ]


def test_r3_adjacent_state_is_low_and_same_state_is_silent():
    def build(video_gov):
        chan = pin(
            core.STORE_OVERRIDE, "www.youtube.com", SPOKANE, "channel=@spokanecity"
        )
        vid = pin(
            core.STORE_OVERRIDE, "www.youtube.com", video_gov, "youtube:AAAAAAAAAAA"
        )
        pg = page(
            "1",
            video_gov,
            video_url="https://youtu.be/AAAAAAAAAAA",
            channel="@spokanecity",
        )
        return data_of([chan, vid], [pg]), vid

    d, vid = build(BOISE)  # WA channel, ID video: adjacent
    assert [f.severity for f in run(rules.rule_r3_channel_coherence, d, [vid])] == [
        "low"
    ]
    d, vid = build(SEATTLE)  # same state
    assert run(rules.rule_r3_channel_coherence, d, [vid]) == []


def test_r3_dominant_state_of_pages_flags_a_stray_video_pin():
    vid = pin(core.STORE_OVERRIDE, "www.youtube.com", MIAMI_FL, "youtube:BBBBBBBBBBB")
    pages = [
        page("1", SPOKANE, video_url="https://youtu.be/BBBBBBBBBBB", channel="@x1"),
        page("2", SPOKANE, video_url="https://youtu.be/CCCCCCCCCCC", channel="@x1"),
        page("3", SEATTLE, video_url="https://youtu.be/DDDDDDDDDDD", channel="@x1"),
    ]
    flags = run(rules.rule_r3_channel_coherence, data_of([vid], pages), [vid])
    assert [f.severity for f in flags] == ["high"]


def test_r3_channel_spanning_four_states_is_only_a_note():
    govs = [SPOKANE, BOISE, MIAMI_FL, SF_PLACE]  # WA ID FL CA
    pages = [
        page(str(i), g, video_url=f"https://youtu.be/{'E' * 10}{i}", channel="@net")
        for i, g in enumerate(govs)
    ]
    vid = pin(core.STORE_OVERRIDE, "www.youtube.com", SEATTLE, f"youtube:{'E' * 10}0")
    flags = run(rules.rule_r3_channel_coherence, data_of([vid], pages), [vid])
    assert [f.severity for f in flags] == ["note"]
