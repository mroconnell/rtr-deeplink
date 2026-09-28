"""WO-1153: two rtr-discovery tenants filed under a same-named government far
away. Both were checked live on 2026-09-27 (each row's evidence in
`tenant_overrides.csv`): Live Oak's meeting page names Live Oak, California
95953, not Florida; Hermantown's CivicClerk event 1167 is at 5105 Maple Grove
Road, Hermantown MN, not Herman MN.
"""

import pytest

from app.utils.gov_registry.resolver import resolve_government

PINS = [
    ("liveoakcity.primegov.com", "us:place:0641936"),
    ("hermantownmn.portal.civicclerk.com", "us:place:2728682"),
]


@pytest.mark.parametrize("host, gov_id", PINS)
def test_the_tenant_resolves_to_the_right_place(host, gov_id):
    assert resolve_government(None, tenant_host=host, path="/").gov_id == gov_id
