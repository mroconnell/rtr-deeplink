"""Tests for the WO-174 continuation hand check (2026-09-11).

WO-191's own by-hand oEmbed audit (BACKLOG_DONE.md, WO-191 entry) found 8
of 80 "found" videos in one 798-government batch were wrong on
inspection: a school board meeting, a state DOT public meeting, two
regional/multi-township commissions, a county assessor's meeting, and two
ceremony/recruitment videos that were real but not deliberative meetings.
None of that is caught by `_looks_wrong_government()`
(`scripts/wo146_api_relist_sweep.py`), which only flags a different KIND
of general-purpose government (city vs. county) or a state legislature/
court.

`scripts.wo174_pipeline.classify_video_hand_check()` is the small,
phrase-based function added to close that gap for this WO's continuation
run, applied before a video is accepted (see `process_government()`'s
per-candidate loop).

The exact video titles/channel names behind WO-191's real catches were
never recorded verbatim in `BACKLOG_DONE.md` -- only the plain-language
summary in its results table. The strings below are SYNTHETIC,
reconstructed from those summaries to exercise the same real category of
mistake (a genuinely different body, or a genuinely non-meeting event),
not verbatim real titles. Marked here per CLAUDE.md's synthetic-test
convention.
"""

from scripts.wo174_pipeline import classify_video_hand_check


def test_school_board_is_kind_a():
    # Reconstructed from WO-191's real catch: Middlebury town, VT's own
    # AgendaCenter delegated to a video that was actually Addison Central
    # School District's meeting, not the town's.
    result = classify_video_hand_check(
        title="ACSD School Board Meeting - 07/20/2026",
        channel_text="Addison Central School District",
        gov_name="Middlebury",
        gov_kind="municipality",
    )
    assert result is not None
    kind, reason = result
    assert kind == "A"
    assert "school district" in reason.lower()


def test_state_dot_public_meeting_is_kind_a():
    # Reconstructed from WO-191's real catch: Solebury Township, PA's own
    # AgendaCenter delegated to a PennDOT roundabout-project public
    # meeting, not a township board meeting.
    result = classify_video_hand_check(
        title="U.S. 202 and Route 179 Roundabout Project Public Meeting",
        channel_text="PennDOT District 6-0",
        gov_name="Solebury Township",
        gov_kind="township",
    )
    assert result is not None
    kind, reason = result
    assert kind == "A"
    assert "department of transportation" in reason.lower()


def test_county_assessor_is_kind_a():
    # Reconstructed from WO-191's real catch: Lemont Township, IL's own
    # listing delegated to a Cook County Assessor meeting, not the
    # township's own.
    result = classify_video_hand_check(
        title="2026 Annual Appeal Rules Meeting - Board of Assessors",
        channel_text="Cook County Assessor's Office",
        gov_name="Lemont Township",
        gov_kind="township",
    )
    assert result is not None
    assert result[0] == "A"


def test_regional_commission_is_kind_a():
    # Reconstructed from WO-191's real catch: Damascus Township, PA's own
    # listing delegated to the Upper Delaware Council's meeting -- a
    # separate multi-township regional body, not the township's own
    # council.
    result = classify_video_hand_check(
        title="River Management Plan Meeting",
        channel_text=(
            "Upper Delaware Council, a regional river commission for the "
            "Upper Delaware Scenic and Recreational River corridor"
        ),
        gov_name="Damascus Township",
        gov_kind="township",
    )
    assert result is not None
    kind, reason = result
    assert kind == "A"
    assert "river" in reason.lower() or "commission" in reason.lower()


def test_swearing_in_ceremony_is_kind_b():
    # Reconstructed from WO-191's real catch: Parkland County, AB's own
    # listing delegated to a real council swearing-in ceremony, not a
    # deliberative meeting.
    result = classify_video_hand_check(
        title="Parkland County Council Swearing In Ceremony 2026",
        channel_text="Parkland County",
        gov_name="Parkland County",
        gov_kind="county",
    )
    assert result is not None
    kind, reason = result
    assert kind == "B"
    assert "non-meeting" in reason.lower()


def test_recruitment_video_is_kind_b():
    # Reconstructed from WO-191's real catch: Cambridge city, MN's own
    # listing delegated to a "why run for city council" recruitment
    # video, queued but never transcribed.
    result = classify_video_hand_check(
        title="Why Run for City Council? Cambridge is Looking for You",
        channel_text="City of Cambridge, MN",
        gov_name="Cambridge",
        gov_kind="city",
    )
    assert result is not None
    assert result[0] == "B"


def test_ordinary_council_meeting_is_not_flagged():
    """Negative control: a real, ordinary meeting on the government's own
    channel must not be flagged by either list."""
    result = classify_video_hand_check(
        title="Township Board of Supervisors Regular Meeting - 08/25/2026",
        channel_text="Solebury Township",
        gov_name="Solebury Township",
        gov_kind="township",
    )
    assert result is None


def test_blank_title_and_channel_is_not_flagged():
    result = classify_video_hand_check(
        title="", channel_text="", gov_name="Anywhere", gov_kind="city"
    )
    assert result is None


def test_kind_a_checked_before_kind_b():
    """A title that could plausibly match both lists (e.g. a school
    board's own swearing-in ceremony) should classify as Kind A -- a
    different body entirely is the more important finding to surface,
    since Kind B assumes the channel is genuinely this government's own."""
    result = classify_video_hand_check(
        title="School Board Swearing In Ceremony",
        channel_text="Addison Central School District",
        gov_name="Middlebury",
        gov_kind="municipality",
    )
    assert result is not None
    assert result[0] == "A"
