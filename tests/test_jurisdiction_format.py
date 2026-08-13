from archive.utils.jurisdiction_format import format_jurisdiction_display, normalize_state_suffix


def test_full_state_name_becomes_abbreviation():
    assert normalize_state_suffix("San Diego, California") == "San Diego, CA"


def test_multi_word_state_name():
    assert normalize_state_suffix("Manchester, New Hampshire") == "Manchester, NH"


def test_already_abbreviated_passes_through_unchanged():
    assert normalize_state_suffix("Dublin, CA") == "Dublin, CA"


def test_case_insensitive_match():
    assert normalize_state_suffix("Austin, texas") == "Austin, TX"


def test_no_comma_passes_through_unchanged():
    assert normalize_state_suffix("Illinois General Assembly") == "Illinois General Assembly"


def test_unrecognized_trailing_text_passes_through_unchanged():
    assert normalize_state_suffix("Some Body, Not A State") == "Some Body, Not A State"


def test_none_and_empty_pass_through():
    assert normalize_state_suffix(None) is None
    assert normalize_state_suffix("") == ""


def test_district_of_columbia():
    assert normalize_state_suffix("Washington, District of Columbia") == "Washington, DC"


def test_only_touches_trailing_component():
    # A comma-containing city name shouldn't confuse which segment is "the state" --
    # only the text after the *last* comma is ever treated as a state candidate.
    assert normalize_state_suffix("Winston-Salem, Forsyth County, North Carolina") == "Winston-Salem, Forsyth County, NC"


def test_display_drops_city_of_prefix():
    # User request 2026-08-12: almost everything archived is a city, so
    # labeling every row that way reads as redundant.
    assert format_jurisdiction_display("City of Napa, CA") == "Napa, CA"


def test_display_drops_bare_city_prefix():
    assert format_jurisdiction_display("City Napa, CA") == "Napa, CA"


def test_display_is_case_insensitive_on_the_prefix():
    assert format_jurisdiction_display("city of Oklahoma City") == "Oklahoma City"


def test_display_keeps_county_label():
    # The real exception this is meant to preserve -- see the docstring.
    assert format_jurisdiction_display("County of Napa, CA") == "County of Napa, CA"
    assert format_jurisdiction_display("Forsyth County, NC") == "Forsyth County, NC"


def test_display_keeps_state_legislature_body_names():
    assert format_jurisdiction_display("California State Legislature") == "California State Legislature"
    assert format_jurisdiction_display("Illinois General Assembly") == "Illinois General Assembly"


def test_display_keeps_town_label():
    # Not explicitly requested to be dropped, unlike "City of" -- treated
    # like County, kept as-is.
    assert format_jurisdiction_display("Town of Thousand Oaks, CA") == "Town of Thousand Oaks, CA"


def test_display_passes_through_a_jurisdiction_with_no_city_prefix():
    assert format_jurisdiction_display("Charlotte, NC") == "Charlotte, NC"


def test_display_keeps_consolidated_city_and_county_label():
    # Real bug found live 2026-08-13: a naive "starts with 'City '" check
    # also matched "City and County of San Francisco"/"...Denver" (real
    # consolidated city-county governments) on just its first 5
    # characters, leaving a mangled "and County of San Francisco".
    assert format_jurisdiction_display("City and County of San Francisco, CA") == "City and County of San Francisco, CA"
    assert format_jurisdiction_display("City and County of Denver, CO") == "City and County of Denver, CO"


def test_display_none_and_empty_pass_through():
    assert format_jurisdiction_display(None) is None
    assert format_jurisdiction_display("") == ""
