"""WO-1163: new meeting sites for governments whose IQM2 site died.

Meeting Finder started on each government's own website on 2026-09-29 and
reached these sites; each owner was then re-checked live (evidence in each
row of `tenant_overrides.csv`).
"""

import pytest

from app.utils.gov_registry.resolver import resolve_government

PINS = [
    ("sanbernardino.cablecast.tv", "/", "us:place:0665000"),
    ("stluciecofl.portal.civicclerk.com", "/", "us:county:12111"),
    ("cityofclovis.granicus.com", "/", "us:place:3516420"),
    ("modoccoca.portal.civicclerk.com", "/", "us:county:06049"),
    ("alpinecoca.portal.civicclerk.com", "/", "us:county:06003"),
    ("charlestownwv.granicus.com", "/", "us:place:5414610"),
    ("ransonwv.granicus.com", "/", "us:place:5466988"),
    ("hancockcoms.portal.civicclerk.com", "/", "us:county:28045"),
    (
        "townhallstreams.com",
        "/stream.php?location_id=168&id=75387",
        "us:cousub:3300147140",
    ),
]


@pytest.mark.parametrize("host, path, gov_id", PINS)
def test_the_tenant_resolves_to_the_right_government(host, path, gov_id):
    assert resolve_government(None, tenant_host=host, path=path).gov_id == gov_id
