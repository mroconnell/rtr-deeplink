"""Governments minted by our Find Meeting jobs (`governments.csv` rows whose
`source` starts `findmeeting-`) resolve to their OWN id at tier `registry`
(2026-10-16). Before, `registry.curated_aliases()` only indexed `curated*`
rows, so 291 of 305 Texas mints resolved to themselves at `unverified`, 12
resolved to a county/place row sharing the first words of the name, and 2
(slug differs from the minted id) resolved to a different id.

Real rows from main's `governments.csv`, plus one synthetic namesake case
(a branch confirmed against real data above: no real mint shares a name
with a national row today, so the guard needs a constructed one).
"""

import csv
from pathlib import Path

import pytest

from app.utils import gov_registry
from app.utils.gov_registry import registry

DATA = Path(__file__).parent.parent / "app" / "utils" / "jurisdiction_data"


def resolve(name, **kwargs):
    return gov_registry.resolve_government(name, **kwargs)


def _mint_rows():
    csv.field_size_limit(10**9)
    with open(DATA / "governments.csv", newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r["source"].startswith("findmeeting-")]


def test_mint_prefix_is_in_the_curated_tuple():
    assert registry.MINT_SOURCE_PREFIX in registry.CURATED_SOURCE_PREFIX
    assert "curated" in registry.CURATED_SOURCE_PREFIX


@pytest.mark.parametrize(
    "name, gov_id",
    [
        # 305-row Texas family; a district whose name starts with a county's
        (
            "Harris County Department of Education, TX",
            "rtr:us:tx:harris-county-department-of-education",
        ),
        (
            "Denton County Fresh Water Supply District #11-C, TX",
            "rtr:us:tx:denton-county-fresh-water-supply-district-11-c",
        ),
        # 506-row Public Notice family; starts with a place's name
        (
            "Albany County Land Bank Corporation, NY",
            "rtr:us:ny:albany-county-land-bank-corporation",
        ),
    ],
)
def test_mint_row_resolves_to_its_own_id_at_registry_tier(name, gov_id):
    m = resolve(name)
    assert (m.gov_id, m.tier) == (gov_id, "registry")


@pytest.mark.parametrize(
    "name, gov_id",
    [
        # minted id slug differs from slugify(name): resolved to the
        # "slugified" twin at tier unverified before.
        (
            "Barton Springs/Edwards Aquifer Conservation District, TX",
            "rtr:us:tx:barton-springsedwards-aquifer-conservation-district",
        ),
        (
            "Angelina & Neches River Authority, TX",
            "rtr:us:tx:angelina-and-neches-river-authority",
        ),
    ],
)
def test_slug_mismatch_mints_resolve_by_exact_name_to_themselves(name, gov_id):
    m = resolve(name)
    assert (m.gov_id, m.tier) == (gov_id, "registry")


def test_every_mint_row_resolves_to_itself_at_registry():
    rows = _mint_rows()
    assert len(rows) >= 817
    bad = []
    for r in rows:
        m = resolve(f"{r['gov_name']}, {r['state']}")
        if (m.gov_id, m.tier) != (r["gov_id"], "registry"):
            bad.append((r["gov_id"], m.gov_id, m.tier))
    assert not bad, bad[:10]


def test_national_rows_still_resolve_to_themselves():
    assert resolve("Harris County, TX").gov_id == "us:county:48201"
    assert resolve("Denton County, TX").gov_id == "us:county:48121"
    assert resolve("Albany, NY").gov_id.startswith("us:")


def test_mint_row_never_takes_a_national_rows_name(monkeypatch):
    """A mint sharing a (state, name) with a national or hand-written row
    is not indexed; the existing rule (national row) keeps winning."""
    real = registry.governments()
    county = real["us:county:48201"]
    fake = registry.Government(
        gov_id="rtr:us:tx:fake-namesake",
        gov_name=county.gov_name,
        gov_type="special_district",
        state="TX",
        source="findmeeting-test-2026-10-16",
    )
    monkeypatch.setattr(registry, "governments", lambda: {**real, fake.gov_id: fake})
    registry.curated_aliases.cache_clear()
    try:
        idx = registry.curated_aliases()
        assert ("TX", county.gov_name.lower()) not in idx
    finally:
        monkeypatch.undo()
        registry.curated_aliases.cache_clear()


def test_hand_written_row_beats_mint_row_on_same_name(monkeypatch):
    real = registry.governments()
    hand = registry.Government(
        gov_id="rtr:us:tx:hand",
        gov_name="Zed District",
        gov_type="special_district",
        state="TX",
        source="curated+test",
    )
    mint = registry.Government(
        gov_id="rtr:us:tx:mint",
        gov_name="zed district",
        gov_type="special_district",
        state="TX",
        source="findmeeting-test-2026-10-16",
    )
    monkeypatch.setattr(
        registry, "governments", lambda: {**real, hand.gov_id: hand, mint.gov_id: mint}
    )
    registry.curated_aliases.cache_clear()
    try:
        assert registry.curated_aliases()[("TX", "zed district")] == "rtr:us:tx:hand"
    finally:
        monkeypatch.undo()
        registry.curated_aliases.cache_clear()
