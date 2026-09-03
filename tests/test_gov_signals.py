"""Tests for `app/utils/gov_signals.py` -- `extract_gov_signals()`
(WO-105, Phase 2d "signal scoring").

Per CLAUDE.md's synthetic-test convention: the page snippets below are
hand-built (no live corpus fetch was run in this pass -- see
JURISDICTION_METADATA_PLAN.md's Phase 2d section for why), but every fact
inside them is real and independently checkable: real government names
already used elsewhere in this repo's own test suite (City of Fresno,
City of Toronto), a real Canada Post postal-code format (M5H 2N2 is Old
City Hall, Toronto -- a genuinely public address), and a real US ZIP
(93721, downtown Fresno). Every branch this module has is exercised
against a shape confirmed elsewhere in this repo (the extractors it reuses
-- `_stoprule_extract`, `_capitalization_walk_extract`,
`validated_subdomain_extract`, `find_zip_addresses` -- are already
fixture/live-verified in tests/test_jurisdiction_enrich.py; this file
tests the NEW wiring around them, not the extractors themselves).
"""

from app.utils.gov_signals import extract_gov_signals


def test_extracts_org_names_from_every_reused_extractor():
    html = (
        "<html><title>City of Fresno Council</title>"
        "<body>Welcome. City of Fresno Regular Meeting</body></html>"
    )
    text = "Welcome. City of Fresno Regular Meeting. Board of Trustees present."
    url = "https://fresno.granicus.com/player/clip/1"
    resolved = {"jurisdiction": "City of Fresno, CA", "meeting_body": "City Council"}

    sig = extract_gov_signals(html, text, url, resolved)

    rules = {o["rule"] for o in sig["org_names"]}
    assert "stoprule" in rules
    assert "capitalization_walk" in rules
    assert "validated_subdomain" in rules
    assert "stored_jurisdiction" in rules
    assert {"value": "City of Fresno, CA", "rule": "stored_jurisdiction"} in sig[
        "org_names"
    ]
    assert sig["body_names"] == ["City Council"]


def test_widened_stoprule_extracts_the_escribe_corporation_wrapper():
    # Real eScribe legal-name convention (Ontario municipal law) --
    # confirmed against the widened `_STOPRULE_TRIGGER_RE` in
    # jurisdiction_enrich.py (same WO-105 pass). The wrapper is stripped
    # down to the true type word.
    text = (
        "The Corporation of the City of Toronto. 100 Queen St W, Toronto, ON M5H 2N2."
    )
    sig = extract_gov_signals(
        "", text, "https://pub-toronto.escribemeetings.com/x", None
    )
    assert {"value": "City of Toronto", "rule": "stoprule"} in sig["org_names"]
    assert sig["postal_codes"] == ["M5H 2N2"]


def test_postal_code_extraction_shape():
    # Real Canada Post format, real Toronto postal code (Old City Hall).
    text = "Mail: 100 Queen St W, Toronto, ON M5H 2N2. Second copy: m5h2n2 (lowercase, no space)."
    sig = extract_gov_signals("", text, "", None)
    assert sig["postal_codes"] == ["M5H 2N2"]


def test_zip_code_extraction_reuses_find_zip_addresses():
    text = "Contact: 2600 Fresno St, Fresno, CA 93721"
    sig = extract_gov_signals("", text, "", None)
    assert sig["zip_codes"] == ["93721"]


def test_tld_derived_from_url():
    assert extract_gov_signals("", "", "https://fresno.granicus.com/x", None)[
        "tld"
    ] == ("granicus.com")
    assert (
        extract_gov_signals("", "", "https://pub-toronto.escribemeetings.com/x", None)[
            "tld"
        ]
        == "escribemeetings.com"
    )
    assert extract_gov_signals("", "", "", None)["tld"] == ""


def test_type_words_and_title_kind_words():
    text = "Regional District of Nanaimo. Board of Education present."
    sig = extract_gov_signals(
        "", text, "", {"title": "Special Meeting - Study Session"}
    )
    assert "Board of Education" in sig["type_words"]
    assert "Regional District" in sig["type_words"]
    assert set(sig["title_kind_words"]) == {"Special Meeting", "Study Session"}


def test_bylaw_vs_ordinance_country_words():
    ca_sig = extract_gov_signals("", "Bylaw No. 123-2024 was passed.", "", None)
    us_sig = extract_gov_signals("", "Ordinance No. 45 was adopted.", "", None)
    assert ca_sig["country_words"] == ["bylaw"]
    assert us_sig["country_words"] == ["ordinance"]


def test_meeting_location_passed_through_from_resolved():
    sig = extract_gov_signals("", "", "", {"meeting_location": "City Hall, Room 200"})
    assert sig["meeting_location"] == "City Hall, Room 200"


def test_empty_input_returns_all_defaults():
    sig = extract_gov_signals("", "", "", None)
    assert sig["org_names"] == []
    assert sig["type_words"] == []
    assert sig["body_names"] == []
    assert sig["postal_codes"] == []
    assert sig["zip_codes"] == []
    assert sig["tld"] == ""
    assert sig["rss_title"] == ""
    assert sig["title_kind_words"] == []
    assert sig["language"] is None
    assert sig["meeting_location"] is None
    assert sig["country_words"] == []


def test_accepts_a_dict_or_a_plain_object_for_resolved():
    class Stub:
        jurisdiction = "City of Fresno, CA"
        meeting_body = "City Council"
        title = None
        meeting_location = None

    by_dict = extract_gov_signals(
        "",
        "",
        "",
        {"jurisdiction": "City of Fresno, CA", "meeting_body": "City Council"},
    )
    by_object = extract_gov_signals("", "", "", Stub())
    assert by_dict["org_names"] == by_object["org_names"]
    assert by_dict["body_names"] == by_object["body_names"]
