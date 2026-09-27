"""WO-1144: pins for rtr-discovery tenants whose captioned meetings came
back `no_government:blank`.

Each government was checked by hand on 2026-09-27 against the tenant's own
pages (see each row's evidence in `tenant_overrides.csv`), and every GEOID
against Census TIGERweb. The pin must win for a meeting whose own page
names no government at all, which is exactly the blank case.
"""

import pytest

from app.utils.gov_registry.resolver import page_hints_for, resolve_government

WHOLE_HOST = [
    ("cityofbranson.primegov.com", "us:place:2907966"),
    ("glendaleca.primegov.com", "us:place:0630000"),
    ("ketchikan.primegov.com", "us:place:0238970"),
    ("losalamitosca.portal.civicclerk.com", "us:place:0643224"),
    ("angelscamp-ca.municodemeetings.com", "us:place:0602112"),
    ("newhaven-mi.municodemeetings.com", "us:place:2657380"),
]


@pytest.mark.parametrize("host, gov_id", WHOLE_HOST)
def test_a_blank_page_on_the_tenant_resolves_to_its_government(host, gov_id):
    assert resolve_government(None, tenant_host=host, path="/").gov_id == gov_id


@pytest.mark.parametrize(
    "host, gov_id",
    [
        ("angelscamp-ca.municodemeetings.com", "us:place:0602112"),
        ("newhaven-mi.municodemeetings.com", "us:place:2657380"),
    ],
)
def test_a_municode_meeting_delegated_to_youtube_falls_back_to_the_tenant(host, gov_id):
    # A Municode Meetings detail page hands its video URL to the delegated
    # platform, so the page's host is that platform's and the tenant rides
    # in `origin_host` (rtr-discovery's fill_origin_host()).
    match = resolve_government(
        None,
        tenant_host="www.youtube.com",
        path="/watch?v=abcdefghijk",
        origin_host=host,
    )
    assert match.gov_id == gov_id


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
