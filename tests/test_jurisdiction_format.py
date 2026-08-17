from archive.utils.jurisdiction_format import (
    STATE_SLUG_TO_ABBR,
    US_STATE_ABBR_TO_NAME,
    US_STATE_NAME_TO_ABBR,
    format_jurisdiction_display,
    normalize_state_suffix,
    state_abbr_from_jurisdiction,
    state_slug_from_abbr,
)


def test_full_state_name_becomes_abbreviation():
    assert normalize_state_suffix("San Diego, California") == "San Diego, CA"


def test_multi_word_state_name():
    assert normalize_state_suffix("Manchester, New Hampshire") == "Manchester, NH"


def test_already_abbreviated_passes_through_unchanged():
    assert normalize_state_suffix("Dublin, CA") == "Dublin, CA"


def test_case_insensitive_match():
    assert normalize_state_suffix("Austin, texas") == "Austin, TX"


def test_no_comma_passes_through_unchanged():
    assert (
        normalize_state_suffix("Illinois General Assembly")
        == "Illinois General Assembly"
    )


def test_unrecognized_trailing_text_passes_through_unchanged():
    assert normalize_state_suffix("Some Body, Not A State") == "Some Body, Not A State"


def test_none_and_empty_pass_through():
    assert normalize_state_suffix(None) is None
    assert normalize_state_suffix("") == ""


def test_district_of_columbia():
    assert (
        normalize_state_suffix("Washington, District of Columbia") == "Washington, DC"
    )


def test_only_touches_trailing_component():
    # A comma-containing city name shouldn't confuse which segment is "the state" --
    # only the text after the *last* comma is ever treated as a state candidate.
    assert (
        normalize_state_suffix("Winston-Salem, Forsyth County, North Carolina")
        == "Winston-Salem, Forsyth County, NC"
    )


def test_mis_cased_abbreviation_gets_re_cased():
    # Real bug found live 2026-08-13: Colorado Springs' own Granicus RSS
    # channel title carries the state as "Co", not "CO" -- not a full
    # state name (so the lookup above never fires) and not already
    # correctly-cased (so the "already-abbreviated" no-op case doesn't
    # apply either).
    assert normalize_state_suffix("Colorado Springs, Co") == "Colorado Springs, CO"


def test_unrecognized_two_letter_suffix_passes_through_unchanged():
    # "Not A State" trimmed down to two letters shouldn't false-positive --
    # only a real state abbreviation gets re-cased.
    assert normalize_state_suffix("Some Body, Xy") == "Some Body, Xy"


def test_display_drops_city_of_prefix():
    # User request 2026-08-12: almost everything archived is a city, so
    # labeling every row that way reads as redundant.
    assert format_jurisdiction_display("City of Napa, CA") == "Napa, CA"


def test_display_drops_bare_city_prefix():
    assert format_jurisdiction_display("City Napa, CA") == "Napa, CA"


def test_display_drops_the_city_of_prefix():
    # Real gap found live 2026-08-13: Memphis/Milwaukee store jurisdiction
    # as "The City of X" (not just "City of X"), which the original
    # _DROPPED_DISPLAY_PREFIXES list didn't cover.
    assert format_jurisdiction_display("The City of Memphis, TN") == "Memphis, TN"


def test_display_is_case_insensitive_on_the_prefix():
    assert format_jurisdiction_display("city of Oklahoma City") == "Oklahoma City"


def test_display_keeps_county_label():
    # The real exception this is meant to preserve -- see the docstring.
    assert format_jurisdiction_display("County of Napa, CA") == "County of Napa, CA"
    assert format_jurisdiction_display("Forsyth County, NC") == "Forsyth County, NC"


def test_display_keeps_state_legislature_body_names():
    assert (
        format_jurisdiction_display("California State Legislature")
        == "California State Legislature"
    )
    assert (
        format_jurisdiction_display("Illinois General Assembly")
        == "Illinois General Assembly"
    )


def test_display_keeps_town_label():
    # Not explicitly requested to be dropped, unlike "City of" -- treated
    # like County, kept as-is.
    assert (
        format_jurisdiction_display("Town of Thousand Oaks, CA")
        == "Town of Thousand Oaks, CA"
    )


def test_display_passes_through_a_jurisdiction_with_no_city_prefix():
    assert format_jurisdiction_display("Charlotte, NC") == "Charlotte, NC"


def test_display_keeps_consolidated_city_and_county_label():
    # Real bug found live 2026-08-13: a naive "starts with 'City '" check
    # also matched "City and County of San Francisco"/"...Denver" (real
    # consolidated city-county governments) on just its first 5
    # characters, leaving a mangled "and County of San Francisco".
    assert (
        format_jurisdiction_display("City and County of San Francisco, CA")
        == "City and County of San Francisco, CA"
    )
    assert (
        format_jurisdiction_display("City and County of Denver, CO")
        == "City and County of Denver, CO"
    )


def test_display_none_and_empty_pass_through():
    assert format_jurisdiction_display(None) is None
    assert format_jurisdiction_display("") == ""


def test_abbr_to_name_round_trips_all_states():
    assert len(US_STATE_ABBR_TO_NAME) == 51
    for name, abbr in US_STATE_NAME_TO_ABBR.items():
        assert US_STATE_ABBR_TO_NAME[abbr].lower() == name


def test_abbr_to_name_dc_casing():
    # A naive .title() would give "District Of Columbia".
    assert US_STATE_ABBR_TO_NAME["DC"] == "District of Columbia"


def test_state_slug_map_round_trips_all_states():
    assert len(STATE_SLUG_TO_ABBR) == 51
    for abbr in US_STATE_ABBR_TO_NAME:
        assert STATE_SLUG_TO_ABBR[state_slug_from_abbr(abbr)] == abbr
    assert STATE_SLUG_TO_ABBR["california"] == "CA"
    assert STATE_SLUG_TO_ABBR["district-of-columbia"] == "DC"
    assert STATE_SLUG_TO_ABBR["new-hampshire"] == "NH"


def test_state_abbr_from_jurisdiction_extracts_canonical_suffix():
    assert state_abbr_from_jurisdiction("Napa, CA") == "CA"
    assert state_abbr_from_jurisdiction("Sacramento County, CA") == "CA"
    assert state_abbr_from_jurisdiction("Washington, DC") == "DC"


def test_state_abbr_from_jurisdiction_rejects_stateless_strings():
    # No comma at all -- state-legislature-style body names.
    assert state_abbr_from_jurisdiction("Illinois General Assembly") is None
    # Trailing text that isn't a valid abbreviation.
    assert state_abbr_from_jurisdiction("Meeting, Room 4") is None
    # Lowercase suffix is NOT accepted -- the stored form is canonical
    # uppercase via normalize_state_suffix() at write time.
    assert state_abbr_from_jurisdiction("Napa, ca") is None
    assert state_abbr_from_jurisdiction(None) is None
    assert state_abbr_from_jurisdiction("") is None
