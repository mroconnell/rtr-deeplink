"""WO-1170: meeting sites Meeting Finder found for CivicPlus governments.

The 2026-09-29 overnight run started from each government's own website;
each owner was re-checked live (evidence in each row of the pin file).
"""

import pytest

from app.utils.gov_registry.resolver import resolve_government

PINS = [
    ("southkingstownri.portal.civicclerk.com", "us:cousub:4400967460"),
    ("junobeachfl.portal.civicclerk.com", "us:place:1235850"),
    ("maumeeoh.portal.civicclerk.com", "us:place:3948342"),
    ("beloit.granicus.com", "us:place:5506500"),
    ("sjcity.granicus.com", "us:place:2670960"),
    ("cityofcommerce.legistar.com", "us:place:0614974"),
]


@pytest.mark.parametrize("host, gov_id", PINS)
def test_the_site_resolves_to_its_government(host, gov_id):
    assert resolve_government(None, tenant_host=host, path="/").gov_id == gov_id
