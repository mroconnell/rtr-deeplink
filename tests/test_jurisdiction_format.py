from archive.utils.jurisdiction_format import normalize_state_suffix


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
