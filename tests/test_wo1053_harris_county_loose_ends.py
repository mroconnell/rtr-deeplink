"""WO-1053 (2026-09-25): loose ends from the 2026-09-24 large-county audit.

Two kinds of wrong pin, both in `tenant_overrides.csv`:

* A body that is its own government was pinned to the county it sits in:
  METRO (ridemetro.granicus.com) and The Harris Center
  (theharriscentertx.new.swagit.com) were both filed under Harris County.
  Ryan approved minting both 2026-09-24.
* Six `_KNOWN_DOMAINS` county entries were pinned to a same-named CITY.
  `scripts/seed_gov_registry.py` looked each one up as "Name, ST" and
  dropped its "county" type. Each host was re-fetched 2026-09-25 (see
  BACKLOG_DONE.md's WO-1053 entry for what each page says).
"""

import pytest

from app.utils.gov_registry import registry
from app.utils.gov_registry.resolver import resolve_government
from app.utils.jurisdiction_enrich import _KNOWN_DOMAINS, finalize_jurisdiction
from scripts.seed_gov_registry import _known_domain_lookup_name

METRO = "rtr:us:tx:metropolitan-transit-authority-of-harris-county"
HARRIS_CENTER = "rtr:us:tx:the-harris-center-for-mental-health-and-idd"

COUNTY_PINS = [
    ("agendanet.saccounty.gov", "us:county:06067"),
    ("egenda.scgov.net", "us:county:12115"),
    ("imaging.sedgwickcounty.org", "us:county:20173"),
    ("hcjfsonbase.jfs.hamilton-co.org", "us:county:39061"),
    ("mccobagenda.databankcloud.com", "us:county:04013"),
    ("cocookmn.civicweb.net", "us:county:27031"),
]


def test_minted_governments_exist():
    govs = registry.governments()
    assert govs[METRO].gov_type == "special_district"
    assert govs[METRO].cog_id == "157766"
    assert govs[METRO].state == "TX"
    assert govs[HARRIS_CENTER].state == "TX"


@pytest.mark.parametrize(
    "tenant_host, gov_id",
    [
        ("ridemetro.granicus.com", METRO),
        ("theharriscentertx.new.swagit.com", HARRIS_CENTER),
        *COUNTY_PINS,
    ],
)
def test_tenant_resolves_to_its_real_government(tenant_host, gov_id):
    assert resolve_government(None, tenant_host=tenant_host).gov_id == gov_id


@pytest.mark.parametrize(
    "tenant_host, gov_id",
    [
        ("ridemetro.granicus.com", METRO),
        ("theharriscentertx.new.swagit.com", HARRIS_CENTER),
    ],
)
def test_harris_bodies_beat_a_harris_county_name(tenant_host, gov_id):
    # The pages carried "Harris County, TX" before this WO; the pin must
    # win over that name.
    got = resolve_government("Harris County, TX", tenant_host=tenant_host)
    assert got.gov_id == gov_id


@pytest.mark.parametrize("tenant_host, gov_id", COUNTY_PINS)
def test_seed_script_looks_up_county_entries_as_counties(tenant_host, gov_id):
    """A re-run of the seed must not re-create the city pins. Resolved
    without the tenant host, so the pin itself can't answer for it."""
    name = _known_domain_lookup_name(_KNOWN_DOMAINS[tenant_host])
    assert "County" in name
    assert resolve_government(name).gov_id == gov_id


def test_seed_lookup_name_leaves_non_county_entries_alone():
    assert (
        _known_domain_lookup_name(_KNOWN_DOMAINS["tucsonaz.hylandcloud.com"])
        == "Tucson, AZ"
    )
    # An entry whose name already says County is not doubled.
    known = _KNOWN_DOMAINS["washingtoncounty.civicweb.net"]
    assert _known_domain_lookup_name(known).count("County") == 1


@pytest.mark.parametrize("tenant_host, gov_id", COUNTY_PINS)
def test_ingest_name_for_a_county_host_says_county(tenant_host, gov_id):
    """`finalize_jurisdiction()` fills a blank name from `_KNOWN_DOMAINS`
    at ingest. It used to write "Sacramento, CA", which the resolver
    files under the city before any pin is consulted."""
    finalized = finalize_jurisdiction(None, netloc=tenant_host)
    assert "County" in finalized.jurisdiction
    assert resolve_government(finalized.jurisdiction).gov_id == gov_id


def test_broomfield_stays_on_its_consolidated_place_row():
    # Broomfield's entry is typed "county" too; the City and County of
    # Broomfield is one government, and its pages already use the place
    # row. consolidated_governments.csv keeps them there.
    finalized = finalize_jurisdiction(None, netloc="broomfieldco.cablecast.tv")
    assert finalized.jurisdiction == "Broomfield County, CO"
    assert resolve_government(finalized.jurisdiction).gov_id == "us:place:0809280"


# --- scripts/wo1053_prepare_worklist.py --------------------------------
# Synthetic pages: the shape is `GET /internal/export/pages`'s own (id,
# slug, gov_id, source_url_normalized, versions); the ids, slugs and hosts
# are the real ones the 2026-09-24 audit and the public pages showed.

from scripts import repair_wrong_pages as rwp  # noqa: E402
from scripts.wo1053_prepare_worklist import plan_rows  # noqa: E402

HARRIS_KEEP = "harris-county-tx-2026-06-11-jun-11-2026-commissioners-court"
HARRIS_TWIN = HARRIS_KEEP + "-12cb68"


def _page(pid, slug, gov_id, url, segments=10, content_hash="h"):
    return {
        "id": pid,
        "slug": slug,
        "gov_id": gov_id,
        "jurisdiction": "",
        "source_url_normalized": url,
        "versions": [
            {
                "is_default": True,
                "segment_count": segments,
                "content_hash": content_hash,
            }
        ],
    }


def _rows_by_id(rows):
    return {int(r["page_id"]): r for r in rows}


def test_plan_rekeys_every_page_on_a_corrected_host():
    pages = [
        _page(
            399, "a", "us:county:48201", "https://ridemetro.granicus.com/player/clip/1"
        ),
        _page(
            4177, "b", "us:county:48201", "https://ridemetro.granicus.com/player/clip/2"
        ),
        # Not named by the audit, still on METRO's host: found by the scan.
        _page(
            9001, "c", "us:county:48201", "https://ridemetro.granicus.com/player/clip/3"
        ),
        _page(12, "d", "us:county:20173", "https://imaging.sedgwickcounty.org/x"),
        _page(13, "e", "", "https://imaging.sedgwickcounty.org/y"),
    ]
    rows, notes = plan_rows(pages)
    by_id = _rows_by_id(rows)
    assert by_id[9001]["target_gov_id"] == METRO
    assert by_id[399]["ryan_decision"] == "approve"
    assert 12 not in by_id  # already on Sedgwick County
    assert by_id[13]["expected_current_gov_id"] == rwp.NO_GOV
    assert by_id[13]["needs_ryan"] == "no"
    assert any("5908" in n for n in notes)  # named, not live: a note, no guess


def test_plan_deletes_a_twin_only_when_its_transcript_matches():
    same = [
        _page(538, HARRIS_KEEP, "us:county:48201", "https://h/videos/390829"),
        _page(1171, HARRIS_TWIN, "us:county:48201", "https://h/videos/390829%5c"),
    ]
    rows, notes = plan_rows(same)
    assert _rows_by_id(rows)[1171]["action"] == "delete"
    assert any("backslash" in n for n in notes)

    differ = [
        same[0],
        {**same[1], "versions": [{"is_default": True, "segment_count": 9}]},
    ]
    rows, notes = plan_rows(differ)
    assert 1171 not in _rows_by_id(rows)
    assert any("differs" in n for n in notes)


def test_every_planned_row_passes_the_repair_tools_own_checks():
    pages = [
        _page(538, HARRIS_KEEP, "us:county:48201", "https://h/videos/390829"),
        _page(1171, HARRIS_TWIN, "us:county:48201", "https://h/videos/390829%5c"),
        _page(
            3759,
            "hc",
            "us:county:48201",
            "https://theharriscentertx.new.swagit.com/videos/359330",
        ),
        _page(
            2659,
            "port",
            "us:county:48355",
            "https://portofcorpuschristi.granicus.com/player/clip/359",
        ),
        _page(7, "sac", "us:place:0664000", "https://agendanet.saccounty.gov/x"),
    ]
    rows, _ = plan_rows(pages)
    assert len(rows) == 4
    for i, raw in enumerate(rows):
        row, problems = rwp.parse_row(raw, f"row {i}")
        assert row is not None and not problems, problems
        if row.target_gov_id:
            assert registry.government_for_id(row.target_gov_id) is not None


def test_port_of_corpus_christi_is_registered_and_pinned():
    port = registry.governments()["rtr:us:tx:port-of-corpus-christi"]
    assert port.cog_id == "158176"
    got = resolve_government(
        "Nueces County, TX", tenant_host="portofcorpuschristi.granicus.com"
    )
    assert got.gov_id == "rtr:us:tx:port-of-corpus-christi"


def test_mwd_is_minted_and_pinned():
    mwd = "rtr:us:ca:metropolitan-water-district-of-southern-california"
    gov = registry.governments()[mwd]
    assert gov.gov_type == "special_district"
    assert gov.cog_id == "123317"
    # Page 2535 carried "Los Angeles County, CA"; the pin must beat it.
    got = resolve_government(
        "Los Angeles County, CA", tenant_host="mwdh2o.granicus.com"
    )
    assert got.gov_id == mwd
