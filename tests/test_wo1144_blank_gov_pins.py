"""WO-1144: pins for rtr-discovery tenants whose captioned meetings came
back `no_government:blank`.

Each government was checked by hand on 2026-09-27 against the tenant's own
pages (see each row's evidence in `tenant_overrides.csv`), and every GEOID
against Census TIGERweb. Five bodies no national table covers were minted on
Ryan's approval (2026-09-27): three Texas state agencies, Marin Municipal
Water District and Lee County Port Authority. The pin must win for a meeting whose own page
names no government at all, which is exactly the blank case.
"""

import pytest

from app.utils.gov_registry import registry
from app.utils.gov_registry.resolver import page_hints_for, resolve_government

WHOLE_HOST = [
    ("cityofbranson.primegov.com", "us:place:2907966"),
    ("glendaleca.primegov.com", "us:place:0630000"),
    ("ketchikan.primegov.com", "us:place:0238970"),
    ("losalamitosca.portal.civicclerk.com", "us:place:0643224"),
    ("tabc.new.swagit.com", "rtr:us:tx:texas-alcoholic-beverage-commission"),
    (
        "texashhsc.new.swagit.com",
        "rtr:us:tx:texas-health-and-human-services-commission",
    ),
    ("txdot.new.swagit.com", "rtr:us:tx:texas-department-of-transportation"),
    ("lcpa.primegov.com", "rtr:us:fl:lee-county-port-authority"),
]


@pytest.mark.parametrize("host, gov_id", WHOLE_HOST)
def test_a_blank_page_on_the_tenant_resolves_to_its_government(host, gov_id):
    assert resolve_government(None, tenant_host=host, path="/").gov_id == gov_id


HARBOR = "reflect-harbor-media.cablecast.tv"
HINGHAM = "us:cousub:2502330210"


@pytest.mark.parametrize(
    "show_id", ["7301", "7300", "7276", "7272", "7254", "7232", "7204"]
)
def test_each_pinned_harbor_media_show_is_hingham(show_id):
    match = resolve_government(
        None,
        tenant_host=HARBOR,
        path=f"/internetchannel/show/{show_id}",
        page_hints=page_hints_for("cablecast", f"cablecast:{HARBOR}:{show_id}"),
    )
    assert match.gov_id == HINGHAM


def test_an_unpinned_harbor_media_show_is_not_filed_under_hingham():
    # The station also carries Hingham Public Schools and community shows,
    # so it is pinned per show; a show id sharing a prefix must not match.
    match = resolve_government(
        None,
        tenant_host=HARBOR,
        path="/internetchannel/show/73010",
        page_hints=page_hints_for("cablecast", f"cablecast:{HARBOR}:73010"),
    )
    assert match.gov_id != HINGHAM


MINTED = [
    ("rtr:us:tx:texas-alcoholic-beverage-commission", "other", "TX", ""),
    ("rtr:us:tx:texas-health-and-human-services-commission", "other", "TX", ""),
    ("rtr:us:tx:texas-department-of-transportation", "other", "TX", ""),
    ("rtr:us:ca:marin-municipal-water-district", "special_district", "CA", "142380"),
    ("rtr:us:fl:lee-county-port-authority", "special_district", "FL", ""),
]


@pytest.mark.parametrize("gov_id, gov_type, state, cog_id", MINTED)
def test_each_minted_body_is_a_curated_registry_row(gov_id, gov_type, state, cog_id):
    gov = registry.government_for_id(gov_id)
    assert gov is not None
    assert gov.source.startswith(registry.CURATED_SOURCE_PREFIX)
    assert (gov.gov_type, gov.state, gov.cog_id) == (gov_type, state, cog_id)


def test_marin_water_is_minted_but_its_site_is_not_pinned_yet():
    # Municode rate-limited the check, so the site waits for a live re-check.
    assert "marinwater-ca.municodemeetings.com" not in registry.tenant_overrides()


@pytest.mark.parametrize(
    "name, gov_id",
    [
        ("Texas, TX", None),
        ("Lee County, FL", "us:county:12071"),
        ("Marin County, CA", "us:county:06041"),
    ],
)
def test_the_namesake_government_is_unchanged(name, gov_id):
    match = resolve_government(name, tenant_host=None)
    if gov_id is None:
        assert not match.gov_id.startswith("rtr:us:tx:texas-")
    else:
        assert match.gov_id == gov_id
