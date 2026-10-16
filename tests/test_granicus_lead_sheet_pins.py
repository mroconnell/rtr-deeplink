"""Ryan's two Granicus lead sheets: the two hosts that were not yet pinned.

Each owner was checked by hand on 2026-10-16 from the host's own view page
and one of its agendas (evidence in each row of `tenant_overrides.csv`).
The sheets' own matches were not used.
"""

import pytest

from app.utils.gov_registry.resolver import resolve_government

PINS = [
    ("gretnala.granicus.com", "us:place:2231915"),  # Gretna city, LA
    ("huroncounty.ca.granicus.com", "ca:cd:3540"),  # County of Huron, ON
]


@pytest.mark.parametrize("host, gov_id", PINS)
def test_the_tenant_resolves_to_the_right_government(host, gov_id):
    assert resolve_government(None, tenant_host=host, path="/").gov_id == gov_id
