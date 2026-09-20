"""Meeting-link parsing for scripts/diligent_community_full_sweep.py (WO-914).

Fixtures are real `<li>` rows copied verbatim from the live
`MeetingTypeList.aspx` pages of Diligent Community tenants, fetched
2026-09-20 (see tests/fixtures/diligent_community/). The original regex
only read a link whose text ended "Mon D YYYY"; every shape below was
silently dropped by it.

Still unconfirmed: a link with no readable date is checked anyway, but no
real tenant has yet shown that such an undated link ever carries a video
the dated ones do not.
"""

from datetime import date
from pathlib import Path

from scripts.diligent_community_full_sweep import extract_link_date, parse_past_meetings

FIX = Path(__file__).parent / "fixtures" / "diligent_community"
TODAY = date(2026, 9, 20)


def _parse(name):
    return parse_past_meetings((FIX / name).read_text(), today=TODAY)


def test_colon_and_long_month_shape_jeffpud():
    # "Regular Meeting: September 15, 2026" (jeffpud): old regex read none.
    got = _parse("jeffpud_list_items.html")
    paths = {p for p, _, _ in got}
    assert {
        "/Portal/MeetingInformation.aspx?Id=429",
        "/Portal/MeetingInformation.aspx?Id=428",
        "/Portal/MeetingInformation.aspx?Id=427",
    } <= paths
    assert got[0][2] == date(2026, 9, 15)


def test_slash_date_two_digit_year_skps():
    got = _parse("skps_list_items.html")
    assert got
    assert all(d is not None for _, _, d in got)
    assert any(d == date(2026, 8, 11) for _, _, d in got)


def test_uppercase_month_no_comma_cmccd():
    got = _parse("cmccd_list_items.html")
    assert got
    assert all(d is not None for _, _, d in got)


def test_long_month_with_comma_cdaschools_and_austin():
    assert _parse("cdaschools_list_items.html")
    assert _parse("austin-isd_list_items.html")


def test_numeric_date_inside_title_hesston():
    got = _parse("hesston-schools_list_items.html")
    assert got
    assert all(d is not None for _, _, d in got)


def test_future_dated_meetings_are_skipped():
    got = parse_past_meetings(
        (FIX / "jeffpud_list_items.html").read_text(), today=date(2026, 9, 1)
    )
    ids = [p.rsplit("=", 1)[1] for p, _, _ in got]
    assert "429" not in ids and "427" in ids


def test_undated_link_is_kept_after_dated_ones_palm_beach():
    got = _parse("palmbeachschools-org_list_items.html")
    paths = [p for p, _, _ in got]
    # "Special Meeting for School Board Proclamations at 1:30 p.m." has no date.
    assert "/Portal/MeetingInformation.aspx?Id=2833" in paths
    undated = [d for _, _, d in got if d is None]
    assert undated
    first_undated = next(i for i, (_, _, d) in enumerate(got) if d is None)
    assert all(d is None for _, _, d in got[first_undated:])
    # dated ones come newest first
    dated = [d for _, _, d in got if d is not None]
    assert dated == sorted(dated, reverse=True)


def test_cancelled_suffix_still_yields_a_date_laccd():
    got = _parse("laccd_list_items.html")
    assert got


def test_extract_link_date_shapes():
    assert extract_link_date("Board Retreat - September 17, 2026") == date(2026, 9, 17)
    assert extract_link_date("Regular Meeting - Sep 15 2026 - Cancelled") == date(
        2026, 9, 15
    )
    assert extract_link_date("Board Meeting (Business Session) - 09/08/26") == date(
        2026, 9, 8
    )
    assert extract_link_date("USD 460 Board of Education Meeting, 8/10/2026") == date(
        2026, 8, 10
    )
    assert extract_link_date(
        "Budget Committee Meeting, Wednesday, July 30, 2025"
    ) == date(2025, 7, 30)
    # real lancasterisd link text: a comma right after the month name
    assert extract_link_date("Regular Board Meeting, Wednesday, July, 15 2026") == date(
        2026, 7, 15
    )
    assert extract_link_date("Common Thread Task Force Subcommittee") is None
    assert extract_link_date("Meeting 13/45/2026") is None
