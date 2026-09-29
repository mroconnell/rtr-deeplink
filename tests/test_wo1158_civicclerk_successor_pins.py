"""WO-1158: eight CivicClerk sites that replaced a dead IQM2 site.

rtr-discovery found each one on 2026-09-29 by guessing its CivicClerk name
and asking the live Events API (a real site answers 200, an unknown name 404).
Each pin's owner is proven by a meeting address in that API; the address is
quoted in the row's evidence in `tenant_overrides.csv`.
"""

import pytest

from app.utils.gov_registry.resolver import resolve_government

PINS = [
    ("fortmyersbeachfl.portal.civicclerk.com", "us:place:1224150"),
    ("bartletttn.portal.civicclerk.com", "us:place:4703440"),
    ("clarkstonga.portal.civicclerk.com", "us:place:1316544"),
    ("hollyspringsga.portal.civicclerk.com", "us:place:1339524"),
    ("medfordma.portal.civicclerk.com", "us:place:2539835"),
    ("smithtownny.portal.civicclerk.com", "us:cousub:3610368000"),
    ("mundeleinil.portal.civicclerk.com", "us:place:1751349"),
    ("maitlandfl.portal.civicclerk.com", "us:place:1242575"),
]


@pytest.mark.parametrize("host, gov_id", PINS)
def test_the_tenant_resolves_to_the_right_place(host, gov_id):
    assert resolve_government(None, tenant_host=host, path="/").gov_id == gov_id
