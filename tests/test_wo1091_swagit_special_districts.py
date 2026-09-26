"""WO-1091: six public bodies found on Swagit get registry ids, site pins
and their Swagit views.

rtr-discovery's Swagit owner sweep (2026-09-26) found each body's own
Swagit site (every video page on its views names that site as its owner).
Each is a Census of Governments 2022 unit; Ryan approved adding them, and
Collin College as in scope (2026-09-26). The pin must win for a page whose
title names no body ("Board Meeting"), and the namesake place or county
must still resolve to itself.
"""

import pytest

from app.platforms.swagit import known_views_for
from app.utils.gov_registry.resolver import resolve_government

BODIES = [
    ("benbrookwater", "rtr:us:tx:benbrook-water-authority", ["118"]),
    ("collincollegetx", "rtr:us:tx:collin-college", ["503"]),
    ("gccddtx", "rtr:us:tx:galveston-county-consolidated-drainage-district", ["918"]),
    ("gcwa", "rtr:us:tx:gulf-coast-water-authority", ["686", "921"]),
    ("grfdaz", "rtr:us:az:golder-ranch-fire-district", ["146"]),
    ("ntta", "rtr:us:tx:north-texas-tollway-authority", ["485"]),
]


@pytest.mark.parametrize("slug, gov_id, views", BODIES)
def test_the_swagit_site_resolves_to_its_body(slug, gov_id, views):
    host = f"{slug}.new.swagit.com"
    match = resolve_government("Board Meeting", tenant_host=host)
    assert match.gov_id == gov_id
    assert known_views_for(host) == views


@pytest.mark.parametrize(
    "name, gov_id",
    [
        ("Benbrook, TX", "us:place:4807552"),
        ("Collin County, TX", "us:county:48085"),
        ("Galveston County, TX", "us:county:48167"),
    ],
)
def test_the_namesake_government_is_unchanged(name, gov_id):
    assert resolve_government(name, tenant_host=None).gov_id == gov_id
