"""Tests for archive/utils/suspicious_source.py -- the systemic backstop
for a real, confirmed-twice incident shape (PrimeGov UAT tenants,
ProudCity's shared demo page). See that module's own docstring.
"""

from archive.utils.suspicious_source import suspicious_source_reason


def test_none_and_empty_url_are_not_suspicious():
    assert suspicious_source_reason(None) is None
    assert suspicious_source_reason("") is None


def test_a_normal_production_url_is_not_flagged():
    assert (
        suspicious_source_reason("https://example.granicus.com/player/clip/12345")
        is None
    )
    assert suspicious_source_reason("https://townoffairfaxca.gov/meetings/foo") is None


def test_staging_uat_sandbox_demo_subdomains_are_flagged():
    for host in [
        "https://uat.example.primegov.com/Portal/Meeting",
        "https://staging.example.civicclerk.com/",
        "https://sandbox.example.gov/meetings/foo",
        "https://demo.example.gov/meetings/foo",
        "https://something.dev.example.gov/",
    ]:
        assert suspicious_source_reason(host) is not None, host


def test_a_real_word_containing_the_substring_is_not_a_false_positive():
    # "Test, NC" is a real place -- a bare substring match would wrongly
    # flag its real Granicus subdomain. Whole-label matching must not.
    assert (
        suspicious_source_reason("https://testcounty.granicus.com/player/clip/1")
        is None
    )


def test_known_demo_path_is_flagged_regardless_of_host():
    assert (
        suspicious_source_reason(
            "https://any-real-city.gov/meetings/example-city-council-meeting"
        )
        is not None
    )
    assert (
        suspicious_source_reason(
            "https://any-real-city.gov/meetings/example-city-council-meeting/"
        )
        is not None
    )


def test_a_real_meeting_title_word_never_enters_the_check():
    # The check only ever looks at the URL -- a title containing "test"/
    # "demo" is real government text, never checked here at all.
    assert (
        suspicious_source_reason(
            "https://example.granicus.com/player/clip/covid-testing-site"
        )
        is None
    )
