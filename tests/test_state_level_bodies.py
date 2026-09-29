"""State-level pass (Ryan, 2026-09-29: un-parked state-level work, "same
kind of work"). Four bodies got their own ids; each id must resolve in the
registry, and the pins must file the Supreme Court of Georgia's old Swagit
page and its new Vimeo oral argument under the court, not under the State
of Georgia or an rtr:unknown id."""

import pytest

from app.utils.gov_registry import government_for_id, resolve_government

MINTED = {
    "rtr:ca:nl:government-of-nunatsiavut": ("other", "ca", "NL"),
    "rtr:us:va:virginia-department-of-social-services": ("other", "us", "VA"),
    "rtr:us:vt:state-board-of-education": ("other", "us", "VT"),
    "rtr:us:ga:supreme-court-of-georgia": ("court", "us", "GA"),
}


@pytest.mark.parametrize("gov_id,expected", sorted(MINTED.items()))
def test_each_minted_body_resolves_as_a_curated_government(gov_id, expected):
    gov = government_for_id(gov_id)
    assert gov is not None and gov.source.startswith("curated")
    assert (gov.gov_type, gov.country, gov.state) == expected


def test_page_1879_host_files_under_the_supreme_court_of_georgia():
    """Page 1879 (may-08-2019-oral-arguments) sits under
    rtr:unknown:scgtv.new.swagit.com. The host pin is what
    backfill_gov_id.py reads when it re-runs for this host."""
    match = resolve_government(
        None, tenant_host="scgtv.new.swagit.com", path="/videos/27666"
    )
    assert match.gov_id == "rtr:us:ga:supreme-court-of-georgia"


def test_the_september_2026_oral_argument_files_under_the_court():
    match = resolve_government(
        None, tenant_host="player.vimeo.com", path="/video/1229592544"
    )
    assert match.gov_id == "rtr:us:ga:supreme-court-of-georgia"
