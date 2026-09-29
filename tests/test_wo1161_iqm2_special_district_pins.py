"""WO-1161: six special districts and a school district that left IQM2.

Each old IQM2 site and its new meeting site are pinned to the same
government, checked live on 2026-09-29 (evidence in each row of
`tenant_overrides.csv`). West Basin's CivicClerk site was previously
filed under Carson city, the district office's city.
"""

import pytest

from app.utils.gov_registry.resolver import resolve_government

WEST_BASIN = "rtr:us:ca:west-basin-municipal-water-district"
CAP_METRO = "rtr:us:tx:capital-metropolitan-transportation-authority"
WEST_COUNTY = "rtr:us:ca:west-county-wastewater-district"
CAPE_FEAR = "rtr:us:nc:cape-fear-public-utility-authority"

PINS = [
    ("westbasin.portal.civicclerk.com", WEST_BASIN),
    ("wbmwdca.iqm2.com", WEST_BASIN),
    ("capmetrotx.granicus.com", CAP_METRO),
    ("capmetrotx.legistar.com", CAP_METRO),
    ("capmetrotx.iqm2.com", CAP_METRO),
    ("wcwd.civicweb.net", WEST_COUNTY),
    ("wcwdca.iqm2.com", WEST_COUNTY),
    ("cfpuanc.portal.civicclerk.com", CAPE_FEAR),
    ("cfpua.iqm2.com", CAPE_FEAR),
    ("prparkdistrictil.iqm2.com", "rtr:us:il:park-ridge-park-district"),
    ("syossetsdny.iqm2.com", "us:sd:3628560"),
]


@pytest.mark.parametrize("host, gov_id", PINS)
def test_the_tenant_resolves_to_the_right_government(host, gov_id):
    assert resolve_government(None, tenant_host=host, path="/").gov_id == gov_id
