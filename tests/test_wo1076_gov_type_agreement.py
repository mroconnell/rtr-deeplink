"""WO-1076 addendum (Ryan, 2026-09-25): the "other government" lead
matcher (`scripts/hub_harvest.py`'s `_match_place_text()`, used by both
that script and `scripts/meeting_finder_other_gov_leads.py`) ignored the
government-TYPE word in a title. Real wrong "confident" matches from the
calD2 calibration run (`<scratchpad>/calD2/ogl/other_gov_ingest_queue_
plan.csv`), all REAL titles and REAL wrong matches:

    "Town of Horseheads Planning Board"      -> Horseheads VILLAGE, NY
    "Springfield Township Board"              -> Springfield CITY, MI
    "Grant County Board of Commissioners"     -> Grant (a city), MN
    "Lucas County Plan Commission"            -> Lucas village, OH
    "Hilton Head Island Town Council"         -> Beaufort COUNTY, SC
    "Essex County OPP Detachment Board"       -> Essex, ON (a police board,
                                                  not a council at all)

Fix: `_enforce_type_agreement()` (hub_harvest.py) downgrades a match to
`TIER_UNVERIFIED` (never "confident") when the title's own explicit
type word (county/township/town/village/city/borough/school district --
`normalize_body_type_word()`) disagrees with the matched government's
real `gov_type`; no registry government of the right type+name+state
means hand-read, never a same-named government of the wrong type. A
police/OPP board or a "Joint Meeting"/"Joint Hearing" title is now also
treated as a special body (`_is_joint_or_special_body()`), so it goes to
hand-read outright rather than through the type check at all.

`hub_host`/state values below are taken from the real calD2 rows; the
searched-government name/state are synthetic (a stand-in for whichever
different government's own walk actually turned up each lead), since
that detail wasn't preserved in the lead CSV itself -- what matters for
this test is the LEAD's own title and the WRONG match id it produced.
"""

from __future__ import annotations

from scripts.hub_harvest import normalize_body_type_word
from scripts.meeting_finder_other_gov_leads import match_lead


def test_grant_county_board_of_commissioners_is_not_matched_to_a_city():
    """Real wrong match: `us:place:2725334` ("Grant, MN", a city)."""
    lead = {
        "url": "https://www.grantcountymn.gov/AgendaCenter/PreviousVersions/_x",
        "title": "Special Grant County Board Of Commissioners Meeting(7-1-2026)",
        "date": "2026-07-01",
        "hub_host": "www.grantcountymn.gov",
        "_gov_id": "us:place:9999999",
        "_gov_name": "Some Other City, MN",
        "_gov_state": "MN",
    }
    result = match_lead(lead, hubs=[])
    assert not (
        result.confidence == "confident" and result.matched_gov_id == "us:place:2725334"
    )


def test_lucas_county_plan_commission_is_not_matched_to_a_village():
    """Real wrong match: `us:place:3945276` ("Lucas, OH", a village)."""
    lead = {
        "url": "https://toledo.legistar.com/View.ashx?M=AADA&ID=1365777",
        "title": "Lucas County Plan Commission Meeting for Zoning Change",
        "date": "2026-09-16",
        "hub_host": "toledo.legistar.com",
        "_gov_id": "us:place:9999998",
        "_gov_name": "Some Other Township, OH",
        "_gov_state": "OH",
    }
    result = match_lead(lead, hubs=[])
    assert not (
        result.confidence == "confident" and result.matched_gov_id == "us:place:3945276"
    )


def test_springfield_township_board_is_not_matched_to_a_city():
    """Real wrong match: `us:place:2675700` ("Springfield (city), MI")."""
    lead = {
        "url": "https://springfieldtwp.viebit.com/watch?hash=x",
        "title": "July 9, 2026 Springfield Township Board Meeting",
        "date": "2026-07-09",
        "hub_host": "springfieldtwp.viebit.com",
        "_gov_id": "us:place:9999997",
        "_gov_name": "Some Other City, MI",
        "_gov_state": "MI",
    }
    result = match_lead(lead, hubs=[])
    assert not (
        result.confidence == "confident" and result.matched_gov_id == "us:place:2675700"
    )


def test_hilton_head_island_town_council_is_not_matched_to_a_county():
    """Real wrong match: `us:county:45013` ("Beaufort County, SC")."""
    lead = {
        "url": "https://beaufort.granicus.com/MediaPlayer.php?view_id=3&clip_id=4774",
        "title": "Hilton Head Island Town Council Special Meeting - Jun 16, 2020",
        "date": "2020-06-16",
        "hub_host": "beaufort.granicus.com",
        "_gov_id": "us:county:9999996",
        "_gov_name": "Some Other County, SC",
        "_gov_state": "SC",
    }
    result = match_lead(lead, hubs=[])
    assert not (
        result.confidence == "confident" and result.matched_gov_id == "us:county:45013"
    )


def test_horseheads_planning_board_is_not_matched_to_the_village():
    """Real wrong match: `us:place:3635694` ("Horseheads (village), NY").
    The title's OWN "Town of" prefix names the county-subdivision
    government (`us:cousub:`/`township`), never the village (`us:place:`/
    `municipality`) -- this repo's own established town-vs-village
    convention (see `resolver.py`'s `_general_purpose_lookup()` docstring)."""
    lead = {
        "url": "https://www.townofhorseheads.gov/AgendaCenter/ViewFile/Agenda/x",
        "title": "Town of Horseheads Planning Board 09/02/2026",
        "date": "2026-09-02",
        "hub_host": "www.townofhorseheads.gov",
        "_gov_id": "us:place:9999995",
        "_gov_name": "Some Other Town, NY",
        "_gov_state": "NY",
    }
    result = match_lead(lead, hubs=[])
    assert not (
        result.confidence == "confident" and result.matched_gov_id == "us:place:3635694"
    )


def test_essex_county_opp_detachment_board_goes_to_hand_read():
    """A police board is a separate, non-council body -- never
    auto-matched at all, whatever type word sits next to the place name."""
    lead = {
        "url": (
            "https://tecumseh-pub.escribemeetings.com/Meeting.aspx?"
            "Id=bb566b4e-a098-4f4f-9cde-f8d1c189932d"
        ),
        "title": "Essex County OPP Detachment Board - North",
        "date": "2026-09-21",
        "hub_host": "tecumseh-pub.escribemeetings.com",
        "_gov_id": "ca:csd:9999994",
        "_gov_name": "Some Other Township, ON",
        "_gov_state": "ON",
    }
    result = match_lead(lead, hubs=[])
    assert result.confidence == "hand_read"
    assert "joint/special body" in result.reason


# --- normalize_body_type_word(): direct unit coverage -------------------


def test_normalize_body_type_word_accepts_pick_pys_own_vocabulary():
    assert normalize_body_type_word("county") == "county"
    assert normalize_body_type_word("Township") == "township"
    assert normalize_body_type_word("parish") == "county"
    assert normalize_body_type_word("ISD") == "school district"
    assert normalize_body_type_word("usd") == "school district"


def test_normalize_body_type_word_rejects_unknown_words():
    assert normalize_body_type_word("same-as-named-place") == ""
    assert normalize_body_type_word("") == ""
    assert normalize_body_type_word(None) == ""
