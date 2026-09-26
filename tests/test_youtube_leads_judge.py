"""WO-1027: the pure (no-network) judgment layer for the leads hand-check
lane, Steps 2-4 of Ryan's 2026-09-25 spec. Synthetic titles are used here
deliberately -- this is exercising specific logic branches (school-district
exclusion, identity tiers, confidence ranking) already confirmed against
real channels in the live pilot (20 rows, then a further 10-row live test
after the block-signature fix), not a substitute for that live check. See
scripts/youtube_leads_fetch.py's own docstring for the network-touching
half.
"""

from scripts.youtube_leads_judge import (
    assess_candidate,
    assess_identity,
    confidence_rank,
    pick_best_meeting,
)


def test_identity_strong_when_name_matches_and_linked_from_gov_site():
    v = assess_identity(
        channel_title="City of Springfield",
        channel_description="",
        gov_name="Springfield city",
        gov_state="IL",
        gov_kind="municipality",
        linked_from_gov_site=True,
        kind="channel",
    )
    assert v.tier == "strong"


def test_identity_medium_when_name_matches_but_no_linkage():
    v = assess_identity(
        channel_title="Springfield City Council",
        channel_description="",
        gov_name="Springfield city",
        gov_state="IL",
        gov_kind="municipality",
        linked_from_gov_site=False,
        kind="channel",
    )
    assert v.tier == "medium"


def test_identity_wrong_government_for_a_news_station():
    v = assess_identity(
        channel_title="Springfield Local News",
        channel_description="",
        gov_name="Springfield city",
        gov_state="IL",
        gov_kind="municipality",
        linked_from_gov_site=False,
        kind="channel",
    )
    assert v.tier == "wrong-government"


def test_identity_needs_human_when_nothing_matches():
    v = assess_identity(
        channel_title="Random Channel",
        channel_description="",
        gov_name="Springfield city",
        gov_state="IL",
        gov_kind="municipality",
        linked_from_gov_site=False,
        kind="channel",
    )
    assert v.tier == "needs-human"


def test_candidate_passes_with_body_word_and_date():
    v = assess_candidate(
        "City Council Meeting - March 4, 2026", gov_kind="municipality"
    )
    assert v.bucket == "meeting"
    assert v.has_body_word and v.has_date


def test_candidate_old_meeting_still_counts():
    """Ryan's rule: dates order the choices, they never rule one out."""
    v = assess_candidate("Board of Supervisors Meeting 2019-06-12", gov_kind="county")
    assert v.bucket == "meeting"


def test_candidate_rejects_promo():
    v = assess_candidate(
        "Ribbon Cutting Ceremony for New Fire Station", gov_kind="municipality"
    )
    assert v.bucket == "not-a-meeting"


def test_school_district_board_meeting_passes():
    v = assess_candidate(
        "Board of Education Regular Meeting - Sept 10, 2026", gov_kind="school_district"
    )
    assert v.bucket == "meeting"


def test_school_district_choir_concert_excluded_even_with_a_date():
    """Ryan's specific rule: for school districts, ONLY board meetings
    count -- a school event never passes regardless of how it's titled,
    even one that would otherwise look meeting-shaped."""
    v = assess_candidate("Spring Choir Concert - May 2026", gov_kind="school_district")
    assert v.bucket == "school-event"


def test_school_sports_game_excluded():
    v = assess_candidate(
        "Varsity Football Game vs Central High", gov_kind="school_district"
    )
    assert v.bucket in ("school-event", "not-a-meeting")


def test_embed_restricted_never_worked_around():
    v = assess_candidate(
        "City Council Meeting - Jan 5, 2026", gov_kind="municipality", playable=False
    )
    assert v.bucket == "embed-restricted"


def test_confidence_rank_prefers_body_word_and_date_over_body_word_alone():
    strong = assess_candidate(
        "Town Council Meeting - Feb 2, 2026", gov_kind="municipality"
    )
    weak = assess_candidate("Council Session", gov_kind="municipality")
    assert confidence_rank(strong) > confidence_rank(weak)


def test_pick_best_meeting_ignores_length_entirely():
    """Ryan's correction (2026-09-25): no length preference at all, not
    even a shortest-as-tiebreak -- the most authoritative title wins
    regardless of duration, a 3-hour meeting is fine."""
    candidates = [
        ("short", "Council Session", 300, True),  # body word only, no date
        (
            "long",
            "City Council Meeting - March 4, 2026",
            10800,
            True,
        ),  # body word + date, 3 hours
    ]
    best = pick_best_meeting(candidates, gov_kind="municipality")
    assert best is not None
    vid, title, cv = best
    assert vid == "long"


def test_pick_best_meeting_returns_none_when_nothing_qualifies():
    candidates = [
        ("a", "Ribbon Cutting", 600, True),
        ("b", "Parade Highlights", 400, True),
    ]
    assert pick_best_meeting(candidates, gov_kind="municipality") is None
