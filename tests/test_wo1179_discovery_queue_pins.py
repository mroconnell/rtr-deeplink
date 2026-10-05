"""WO-1179: 14 government sites from rtr-discovery's government queue.

Each tenant had captioned meetings (YouTube links on its own site) but no
government. Ryan accepted a proposal for each on 2026-10-03; the proposal
came from the domain and example meeting titles (evidence in each row of
`tenant_overrides.csv`).
"""

import pytest

from app.utils.gov_registry.resolver import resolve_government

PINS = [
    ("coffeecountytn.gov", "us:county:47031"),
    ("norwichct.gov", "us:place:0956200"),
    ("coldspringny.gov", "us:place:3616936"),
    ("cumberlandcountypa.gov", "us:county:42041"),
    ("www.wyandottemi.gov", "us:place:2688900"),
    ("in-leocedarville.civicplus.com", "us:place:1842861"),
    ("bossiercity.org", "us:place:2208920"),
    ("ks-prattcounty2.civicplus.com", "us:county:20151"),
    ("cortlandny.gov", "us:place:3618388"),
    ("www.canaannh.gov", "us:cousub:3300908980"),
    ("dallascountyiowa.gov", "us:county:19049"),
    ("camdencountyga.gov", "us:county:13039"),
    ("grandcountyutah.gov", "us:county:49019"),
    ("ma-southbridge.civicplus.com", "us:place:2563345"),
]


@pytest.mark.parametrize("host, gov_id", PINS)
def test_the_tenant_resolves_to_the_right_government(host, gov_id):
    assert resolve_government(None, tenant_host=host, path="/").gov_id == gov_id
