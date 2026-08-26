from archive.utils.jurisdiction_format import (
    CA_PROVINCE_NAME_TO_ABBR,
    STATE_SLUG_TO_ABBR,
    US_STATE_ABBR_TO_NAME,
    US_STATE_NAME_TO_ABBR,
    format_jurisdiction_display,
    is_canadian_abbr,
    jurisdiction_search_terms,
    match_us_state_or_province,
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


def test_display_appends_canada_suffix_for_a_province_abbreviation():
    # Real, already-archived Canadian jurisdictions -- see /coverage.
    assert format_jurisdiction_display("Calgary, AB") == "Calgary, AB (Canada)"
    assert format_jurisdiction_display("Amherstburg, ON") == "Amherstburg, ON (Canada)"


def test_display_canada_suffix_applies_after_city_of_prefix_is_dropped():
    # Synthetic combination -- Airdrie, AB is a real, already-archived
    # jurisdiction, but whether its stored form actually carries a "City
    # of" prefix hasn't been confirmed live; this exercises the two
    # features' composition (prefix-stripping runs before the suffix is
    # appended), not a claim about Airdrie's real stored jurisdiction text.
    assert format_jurisdiction_display("City of Airdrie, AB") == "Airdrie, AB (Canada)"


def test_display_does_not_add_canada_suffix_for_a_us_state():
    assert format_jurisdiction_display("Napa, CA") == "Napa, CA"


def test_abbr_to_name_round_trips_all_states():
    # 51 US (50 states + DC) + 13 Canadian provinces/territories, since
    # US_STATE_ABBR_TO_NAME combines both (see jurisdiction_format.py's
    # own comment on why) -- was 51 before Canada was added 2026-08-17.
    assert len(US_STATE_ABBR_TO_NAME) == 64
    for name, abbr in US_STATE_NAME_TO_ABBR.items():
        assert US_STATE_ABBR_TO_NAME[abbr].lower() == name
    for name, abbr in CA_PROVINCE_NAME_TO_ABBR.items():
        assert US_STATE_ABBR_TO_NAME[abbr].lower() == name


def test_abbr_to_name_dc_casing():
    # A naive .title() would give "District Of Columbia".
    assert US_STATE_ABBR_TO_NAME["DC"] == "District of Columbia"


def test_abbr_to_name_newfoundland_and_labrador_casing():
    # Same naive-.title() problem as DC above -- "newfoundland and
    # labrador".title() would give "... And Labrador".
    assert US_STATE_ABBR_TO_NAME["NL"] == "Newfoundland and Labrador"


def test_state_slug_map_round_trips_all_states():
    # Same 51 -> 64 change as US_STATE_ABBR_TO_NAME above, same reason.
    assert len(STATE_SLUG_TO_ABBR) == 64
    for abbr in US_STATE_ABBR_TO_NAME:
        assert STATE_SLUG_TO_ABBR[state_slug_from_abbr(abbr)] == abbr
    assert STATE_SLUG_TO_ABBR["california"] == "CA"
    assert STATE_SLUG_TO_ABBR["district-of-columbia"] == "DC"
    assert STATE_SLUG_TO_ABBR["new-hampshire"] == "NH"
    assert STATE_SLUG_TO_ABBR["alberta"] == "AB"
    assert STATE_SLUG_TO_ABBR["newfoundland-and-labrador"] == "NL"


def test_ca_province_name_to_abbr_has_13_provinces_and_territories():
    # All 10 provinces plus the 3 territories (Yukon, Northwest
    # Territories, Nunavut).
    assert len(CA_PROVINCE_NAME_TO_ABBR) == 13
    assert set(CA_PROVINCE_NAME_TO_ABBR.values()) == {
        "AB",
        "BC",
        "MB",
        "NB",
        "NL",
        "NT",
        "NS",
        "NU",
        "ON",
        "PE",
        "QC",
        "SK",
        "YT",
    }


def test_is_canadian_abbr():
    assert is_canadian_abbr("AB") is True
    assert is_canadian_abbr("ON") is True
    assert is_canadian_abbr("CA") is False  # California, not confusable
    assert is_canadian_abbr("DC") is False
    assert is_canadian_abbr(None) is False
    assert is_canadian_abbr("XY") is False


def test_state_abbr_from_jurisdiction_extracts_canonical_suffix():
    assert state_abbr_from_jurisdiction("Napa, CA") == "CA"
    assert state_abbr_from_jurisdiction("Sacramento County, CA") == "CA"
    assert state_abbr_from_jurisdiction("Washington, DC") == "DC"


def test_state_abbr_from_jurisdiction_extracts_canadian_province():
    # Real, already-archived Canadian jurisdictions confirmed live on
    # /coverage as of 2026-08-17, not invented ones.
    assert state_abbr_from_jurisdiction("Calgary, AB") == "AB"
    assert state_abbr_from_jurisdiction("Amherstburg, ON") == "ON"
    assert state_abbr_from_jurisdiction("Airdrie, AB") == "AB"


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


def test_normalize_state_suffix_full_province_name_becomes_abbreviation():
    # Real ingest-time behavior change -- see normalize_state_suffix()'s
    # own docstring. "Calgary, Alberta" is the real full-name shape a
    # scraper could plausibly hand this function, even though the
    # already-archived "Calgary, AB" jurisdiction is already normalized.
    assert normalize_state_suffix("Calgary, Alberta") == "Calgary, AB"
    assert normalize_state_suffix("Airdrie, Alberta") == "Airdrie, AB"


def test_normalize_state_suffix_recases_mis_cased_province_abbr():
    assert normalize_state_suffix("Calgary, ab") == "Calgary, AB"


def test_normalize_state_suffix_already_abbreviated_province_passes_through():
    assert normalize_state_suffix("Amherstburg, ON") == "Amherstburg, ON"


def test_jurisdiction_search_terms_expands_full_state_name():
    assert jurisdiction_search_terms("California") == ["California", "CA"]
    assert jurisdiction_search_terms("Texas") == ["Texas", "TX"]


def test_jurisdiction_search_terms_expands_full_province_name():
    assert jurisdiction_search_terms("Alberta") == ["Alberta", "AB"]
    assert jurisdiction_search_terms("Ontario") == ["Ontario", "ON"]


def test_jurisdiction_search_terms_leaves_non_full_name_terms_unchanged():
    assert jurisdiction_search_terms("Napa") == ["Napa"]
    assert jurisdiction_search_terms("CA") == ["CA"]
    assert jurisdiction_search_terms("Calgary") == ["Calgary"]


def test_match_us_state_or_province_full_name():
    assert match_us_state_or_province("California") == "CA"
    assert match_us_state_or_province("  california  ") == "CA"
    assert match_us_state_or_province("Alberta") == "AB"


def test_match_us_state_or_province_abbreviation():
    assert match_us_state_or_province("CA") == "CA"
    assert match_us_state_or_province("ca") == "CA"
    assert match_us_state_or_province("AB") == "AB"


def test_match_us_state_or_province_none_for_city_name():
    assert match_us_state_or_province("Napa") is None
    assert match_us_state_or_province("Calgary") is None
    assert match_us_state_or_province("") is None
