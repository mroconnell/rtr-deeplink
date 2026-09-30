"""Tests for `app/utils/title_identity.py`.

Every title below is a real title from the 2026-09-30 shared-station
census hand-read (rejects and accepts) or from the Archive's own pages.
Government ids are real Census ids checked against the committed tables.
Nothing here touches the network.
"""

import pytest

from app.utils import title_identity as ti
from app.utils.title_identity import classify_title

YOUNTVILLE = "us:place:0686930"  # Yountville town, CA


def test_body_word_makes_a_meeting_with_place():
    v = classify_title(
        "Jul 21, 2026 Town Council Regular Meeting - Yountville", station_state="CA"
    )
    assert v.meeting is True
    assert v.gov_id == YOUNTVILLE
    # One distinctive name, unique in the state, but no type cue: medium.
    assert v.confidence == ti.MEDIUM
    v = classify_title(
        "Town of Yountville Town Council Regular Meeting", station_state="CA"
    )
    assert v.gov_id == YOUNTVILLE and v.confidence == ti.HIGH


@pytest.mark.parametrize(
    "title",
    [
        "Bill Hernandez Presents",  # a show
        "Neepawa Council Debrief",  # recap show, not a council meeting
        "Don's Workshop",  # workshop as a show
        "Siskiyou Sheriff Town Hall meetings",  # sheriff outreach
        "Elizabeth Warren Town Hall",
        "Easthampton Democratic City Forum",
        "Quincy Recreation Department",
        "Richmond Community Schools RtSP Parent Meetings",
        "2025 E•Media Annual Meeting",  # the access station's own meeting
        "Cape Elizabeth Athletics",
        "Trip Planning & Itineraries",
        "Spring 2026 Commencement: Session 1",
    ],
)
def test_non_meeting_words_say_no(title):
    v = classify_title(title)
    assert v.meeting is False
    assert v.gov_id is None


def test_named_body_beats_a_soft_or_topic_word():
    # A body whose topic list holds "Sports" is still a committee.
    v = classify_title("Committee on Culture, Youth, Aging, Sports, and Parks")
    assert v.meeting is not False
    # "Tourism" and "Sheriff" in a named body's title do not make it a show.
    assert classify_title("Seaside Tourism Advisory Committee").meeting is True
    assert (
        classify_title(
            "Warren County Board of Supervisors Meeting - 4/17/2026 with missing Sheriff audio"
        ).meeting
        is True
    )


def test_body_plus_candidate_plus_meeting_word_is_not_settled():
    v = classify_title("City Council Special Meeting - Mayoral Candidate Interviews")
    assert v.meeting is None
    assert v.confidence == ti.LOW


def test_a_place_that_is_also_a_corner_is_not_a_corner_show():
    v = classify_title(
        "Town of Moncks Corner, Special Council Meeting -JAN, 2026", station_state="SC"
    )
    assert v.meeting is True


def test_no_evidence_is_a_blank_not_a_no():
    v = classify_title("Painting with Tali")
    assert v.meeting is None
    assert ti.NO_EVIDENCE_REASON in v.reasons
    assert v.confidence == ti.LOW


def test_common_word_place_needs_a_cue_or_a_known_id():
    # "Council" (Council city, ID) is a body word here, not a place.
    v = classify_title("2023 City Council Videos", station_state="ID")
    assert v.gov_id is None
    # "Center City Authority" is not Center township.
    v = classify_title("Center City Authority", station_state="MI")
    assert v.gov_id is None
    # "Union" is a common word: only a cue makes it a place.
    assert classify_title("Union Selectboard", station_state="ME").gov_id is None
    v = classify_title("Town of Union Selectboard", station_state="ME")
    assert v.gov_id is not None and v.gov_id.startswith("us:cousub:")


def test_known_gov_id_lets_a_common_word_place_match():
    union = classify_title("Town of Union Selectboard", station_state="ME").gov_id
    v = classify_title("Union Selectboard", station_state="ME", known_gov_ids=[union])
    assert v.gov_id == union


def test_school_body_never_maps_to_a_town_or_county():
    v = classify_title("Enosburg-Richford UUSD Board Meetings", station_state="VT")
    assert v.gov_kind == ti.KIND_SCHOOL
    assert v.gov_id is None or v.gov_id.startswith("us:sd:")
    v = classify_title(
        "WNUESD (Grafton) Board and Committee Meetings", station_state="VT"
    )
    assert v.gov_id is None or v.gov_id.startswith("us:sd:")
    v = classify_title(
        "School Committee", station_state="MA", known_gov_ids=["us:cousub:2502379530"]
    )
    assert v.gov_kind == ti.KIND_SCHOOL


def test_school_body_maps_to_its_district():
    v = classify_title("Chardon Board of Education", station_state="OH")
    assert v.gov_id == "us:sd:3904718"
    assert v.gov_kind == ti.KIND_SCHOOL


def test_county_board_of_education_is_not_the_local_unified_district():
    v = classify_title("Santa Clara County Board of Education", station_state="CA")
    assert v.gov_kind == ti.KIND_SCHOOL
    assert v.gov_id is None


def test_joint_meeting_follows_the_first_named_body():
    v = classify_title(
        "Apr 07, 2026 City Council on 2026-04-07 12:00 PM (Joint Special Called Meeting with Denton ISD Board of Directors)",
        station_state="TX",
    )
    assert v.gov_kind != ti.KIND_SCHOOL


def test_channel_naming_another_place_blocks_the_mapping():
    v = classify_title(
        "2023 City Council Videos",
        channel_name="Salmon Arm, BC",
        station_state="ID",
    )
    assert v.gov_id is None
    v = classify_title(
        "Hall County Commissioners",
        channel_name="City of North Miami",
        station_state="TX",
    )
    assert v.gov_id != "us:county:48191"


def test_legislature_and_state_bodies_map_to_the_state_or_nobody():
    v = classify_title(
        "Senate Select Committee on Veteran Affairs 2026", station_state="KS"
    )
    assert v.gov_id == "us:state:20" and v.gov_kind == ti.KIND_STATE
    v = classify_title("State Board of Education Meeting", station_state="UT")
    assert v.gov_id == "us:state:49"
    v = classify_title("Senate Chamber Proceedings 2020")  # state unknown
    assert v.gov_id is None and v.gov_kind == ti.KIND_STATE
    # A bare "Legislative Session" may be a county legislature (NY, NC).
    v = classify_title("Mar 21, 2024 Legislative Session", station_state="NY")
    assert v.gov_id is None


def test_court_maps_to_the_state_not_a_county():
    v = classify_title(
        "Indiana Court of Appeals oral arguments meeting", station_state="IN"
    )
    assert v.gov_id == "us:state:18"


def test_special_district_is_filed_under_the_local_government():
    # No registry id for this name: file under the same-named local
    # government, district words kept as the body.
    v = classify_title("Hamilton Housing Authority Board Meeting", station_state="OH")
    assert v.meeting is True
    assert v.gov_kind in (ti.KIND_PLACE, ti.KIND_COUSUB)
    assert "Housing Authority" in (v.body or "")
    assert "filed_under_local_government" in " ".join(v.reasons)


def test_special_district_with_no_place_is_not_guessed():
    v = classify_title("Solid Waste Management District Meeting", station_state="VT")
    assert v.gov_id is None
    assert v.confidence == ti.LOW


def test_type_cue_picks_between_a_city_and_a_town_of_one_name():
    v = classify_title("St. Albans City Council", station_state="VT")
    assert v.gov_id == "us:place:5061675"
    v = classify_title("Village of Ludlow Annual Meeting", station_state="VT")
    assert v.gov_id == "us:place:5041200"


def test_unresolved_place_does_not_fall_back_to_a_single_known_government():
    # "Salisbury" is named; the station's one known town is not Salisbury.
    v = classify_title(
        "Salisbury Conservation Commission",
        station_state="VT",
        known_gov_ids=["us:cousub:5000144350"],
    )
    assert v.gov_id != "us:cousub:5000144350" or "Salisbury" in (
        next(iter(v.reasons), "")
    )


def test_generic_body_uses_a_single_known_municipality():
    v = classify_title(
        "Planning Commission",
        station_state="VT",
        known_gov_ids=["us:cousub:5000144350"],
    )
    assert v.gov_id == "us:cousub:5000144350"
    assert v.confidence == ti.MEDIUM


def test_camel_case_file_names_are_read():
    v = classify_title(
        "2026.08.07_AllenCounty_BoardofCommissioners", station_state="KS"
    )
    assert v.meeting is True


def test_empty_title_is_a_blank():
    v = classify_title("")
    assert v.meeting is None and v.gov_id is None


def test_reuses_the_existing_body_type_table():
    from app.utils import gov_body_types

    assert gov_body_types.match_body_type_phrase("Commissioners Court") is not None
    v = classify_title(
        "Commissioners Court", station_state="TX", known_gov_ids=["us:county:48191"]
    )
    assert v.gov_kind == ti.KIND_COUNTY
