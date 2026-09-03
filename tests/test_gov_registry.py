"""Tests for `app/utils/gov_registry/` -- the `gov_id` resolver (WO-98).

Every case below is a REAL example, taken from the §1 tables of
`rtr-business/research/GOVERNMENT_IDENTITY_ARCHITECTURE.md` (each one
measured live on 2026-09-02 against production or rtr-discovery's
ledger) or from a real archived page this repo already has a fixture or
a worked example for. Nothing here is an invented shape -- per CLAUDE.md,
a synthetic case is only for a branch already confirmed against real
data, and every branch of this ladder has a real example available.

The resolver is pure: no I/O, no database, no fetch. These are plain
function calls.
"""

import csv
from pathlib import Path

import pytest

from app.utils import gov_registry
from app.utils.gov_registry import classify, display, registry, resolver, tables

DATA_DIR = Path(__file__).parent.parent / "app" / "utils" / "jurisdiction_data"


def resolve(name, host=None, **kwargs):
    return gov_registry.resolve_government(name, tenant_host=host, **kwargs)


# --- §1.2: one government, two spellings, two hubs ---------------------


@pytest.mark.parametrize(
    "raw",
    [
        # The six CA county pairs /state/california lists twice today.
        # Both spellings pass finalize_jurisdiction() as "validated", so
        # the enricher is working as designed -- the design was the
        # problem. Both must now land on one id.
        "County of Fresno, CA",
        "Fresno County, CA",
    ],
)
def test_county_spellings_collapse_to_one_id(raw):
    match = resolve(raw)
    assert match.gov_id == "us:county:06019"
    assert match.gov_name == "Fresno County, CA"
    assert match.tier == resolver.TIER_REGISTRY


@pytest.mark.parametrize(
    "pair,expected",
    [
        (("County of San Diego, CA", "San Diego County, CA"), "us:county:06073"),
        (("County of Santa Clara, CA", "Santa Clara County, CA"), "us:county:06085"),
        (("County of Solano, CA", "Solano County, CA"), "us:county:06095"),
        (("County of Humboldt, CA", "Humboldt County, CA"), "us:county:06023"),
        (("County of Plumas, CA", "Plumas County, CA"), "us:county:06063"),
    ],
)
def test_the_other_ca_county_pairs_collapse(pair, expected):
    assert {resolve(name).gov_id for name in pair} == {expected}


def test_city_of_and_bare_city_name_collapse():
    """`ks-wichita.civicplus.com` resolves to both `City of Wichita, KS`
    and `Wichita, KS` in the ledger today (§1.2); 17 more tenants have
    the same shape."""
    assert (
        resolve("City of Wichita, KS").gov_id
        == resolve("Wichita, KS").gov_id
        == "us:place:2079000"
    )


# --- §1.3: the nine LADWP-class mislabels ------------------------------
#
# Each of these is a tenant whose page mentions its host city, so the
# place check passes under the WRONG government. The assertion that
# matters is the negative one: none of them may resolve to a place.


@pytest.mark.parametrize(
    "raw,host,wrong_id,gov_type",
    [
        (
            "Los Angeles Department of Water and Power, CA",
            "ladwp.granicus.com",
            "us:place:0644000",
            classify.SPECIAL_DISTRICT,
        ),
        (
            "San Diego Association of Governments, CA",
            "pub-sandag.escribemeetings.com",
            "us:place:0666000",
            classify.SPECIAL_DISTRICT,
        ),
        (
            "Menlo Park Fire Protection District, CA",
            "menlofire.primegov.com",
            "us:place:0603092",
            classify.SPECIAL_DISTRICT,
        ),
        (
            "Coachella Valley Water District, CA",
            "cvwd.primegov.com",
            "us:place:0636448",
            classify.SPECIAL_DISTRICT,
        ),
        # A community college district, which the Census vocabulary (and
        # `govtype.py`, per JURISDICTION_IDENTIFIERS.md's own table) files
        # under school_district, not special_district.
        (
            "Tarrant County College District, TX",
            "tccd.granicus.com",
            "us:county:48439",
            classify.SCHOOL_DISTRICT,
        ),
        (
            "Metropolitan Airports Commission, MN",
            "metroairports.granicus.com",
            "us:place:2743000",
            classify.SPECIAL_DISTRICT,
        ),
    ],
)
def test_agency_never_resolves_to_its_host_place(raw, host, wrong_id, gov_type):
    match = resolve(raw, host)
    assert match.gov_id != wrong_id
    assert match.gov_id.startswith("rtr:")
    assert match.gov_type == gov_type
    # These hosts also carry an `authoritative` pin seeded from the same
    # §1.3 table, so the tier is `pinned` here and `unverified` for the
    # same name with no host. Both are correct; what must never happen is
    # `wrong_id`.
    assert match.tier in (resolver.TIER_UNVERIFIED, resolver.TIER_PINNED)
    assert resolve(raw).tier == resolver.TIER_UNVERIFIED


@pytest.mark.parametrize(
    "host,gov_id",
    [
        ("ladwp.granicus.com", "rtr:us:ca:los-angeles-department-of-water-and-power"),
        ("ladwp.primegov.com", "rtr:us:ca:los-angeles-department-of-water-and-power"),
        (
            "pub-sandag.escribemeetings.com",
            "rtr:us:ca:san-diego-association-of-governments",
        ),
        ("menlofire.primegov.com", "rtr:us:ca:menlo-park-fire-protection-district"),
        ("cvwd.primegov.com", "rtr:us:ca:coachella-valley-water-district"),
        ("tccd.granicus.com", "rtr:us:tx:tarrant-county-college-district"),
        ("pub-horrycountyschools.escribemeetings.com", "us:sd:4502490"),
        (
            "metro.granicus.com",
            "rtr:us:ca:los-angeles-county-metropolitan-transportation-authority",
        ),
        ("pub-hpsb.escribemeetings.com", "rtr:ca:on:hamilton-police-services-board"),
        (
            "pub-trca.escribemeetings.com",
            "rtr:ca:on:toronto-and-region-conservation-authority",
        ),
    ],
)
def test_the_nine_mislabelled_tenants_are_pinned_to_the_right_government(host, gov_id):
    """The seeded `tenant_overrides.csv` must not import the ledger's own
    mislabels as pins -- the ledger's `jurisdiction_override` for
    `ladwp.granicus.com` is literally "Los Angeles, CA". A page from one
    of these hosts with no jurisdiction at all still lands correctly."""
    match = resolve(None, host)
    assert match.gov_id == gov_id
    assert match.tier == resolver.TIER_PINNED


def test_ladwp_survives_the_place_repair_that_used_to_swallow_it():
    """`finalize_jurisdiction()` repairs this string down to "Los
    Angeles" -- correctly, for its own purposes. Classifying only its
    output would reproduce §1.3's bug inside the fix, which is exactly
    what the first run of this resolver did."""
    from app.utils.jurisdiction_enrich import finalize_jurisdiction

    repaired = finalize_jurisdiction(
        "Los Angeles Department of Water and Power, CA", netloc="ladwp.granicus.com"
    )
    assert repaired.jurisdiction == "Los Angeles, CA"  # unchanged behaviour
    assert (
        resolve("Los Angeles Department of Water and Power, CA").gov_id
        == "rtr:us:ca:los-angeles-department-of-water-and-power"
    )


def test_horry_county_schools_is_a_school_district_not_the_county():
    match = resolve("Horry County Schools, SC")
    assert match.gov_id == "us:sd:4502490"
    assert match.gov_type == classify.SCHOOL_DISTRICT


def test_conservation_authority_does_not_become_a_city():
    """`pub-trca.escribemeetings.com` resolves to `City of Markham`
    today. TRCA has no StatCan id (D4: SGC codes subdivisions, not
    boards), so it mints."""
    match = resolve("Toronto and Region Conservation Authority, ON")
    assert match.gov_id == "rtr:ca:on:toronto-and-region-conservation-authority"
    assert match.country == "ca"


def test_police_services_board_does_not_become_its_city():
    match = resolve("Hamilton Police Services Board, ON")
    assert not match.gov_id.startswith("ca:csd:")
    assert match.gov_id.startswith("rtr:ca:on:")


# --- §1.4: the two classifiers that disagree ---------------------------


def test_classifier_gets_the_three_gov_classify_gets_wrong():
    """`archive/utils/gov_classify.py` files the first two as counties
    and the third as a city (measured 2026-09-02)."""
    assert (
        classify.classify_government_type("Broward County Public Schools, FL")
        == classify.SCHOOL_DISTRICT
    )
    assert (
        classify.classify_government_type("West County Wastewater District, CA")
        == classify.SPECIAL_DISTRICT
    )
    assert classify.classify_government_type("Minnesota Senate, MN") == classify.STATE


def test_west_county_wastewater_is_a_district_not_a_county():
    """The architecture doc says `govtype.py` gets this one right. It
    does not -- run against its own rules on 2026-09-02 it returns
    `county`, because its county rule's negative lookahead lists "water"
    but not "wastewater". This asserts the corrected behaviour."""
    match = resolve("West County Wastewater District, CA")
    assert match.gov_id == "rtr:us:ca:west-county-wastewater-district"
    assert match.gov_type == classify.SPECIAL_DISTRICT


# --- §1.5: one tenant, two governments ---------------------------------


def test_cottage_grove_town_and_village_are_two_governments():
    """`wi-cottagegrove.civicplus.com` resolves to both today. They are
    genuinely distinct: the Village is a Census *place*, the Town is a
    county *subdivision*."""
    town = resolve("Town of Cottage Grove, WI")
    village = resolve("Village of Cottage Grove, WI")
    assert town.gov_id == "us:cousub:5502517200"
    assert village.gov_id == "us:place:5517175"
    assert town.gov_id != village.gov_id
    assert town.hub_slug != village.hub_slug


# --- The namespaces, one test each -------------------------------------


@pytest.mark.parametrize(
    "raw,gov_id,gov_type",
    [
        ("City of Fresno, CA", "us:place:0627000", classify.MUNICIPALITY),
        ("Fresno County, CA", "us:county:06019", classify.COUNTY),
        ("Chesterfield Township, MI", "us:cousub:2609915340", classify.TOWNSHIP),
        ("Minnesota Senate, MN", "us:state:27", classify.STATE),
        (
            "Los Angeles Unified School District, CA",
            "us:sd:0622710",
            classify.SCHOOL_DISTRICT,
        ),
        ("Oshawa, ON", "ca:csd:3518013", classify.MUNICIPALITY),
        ("Region of Peel, ON", "ca:cd:3521", classify.COUNTY),
        (
            "West County Wastewater District, CA",
            "rtr:us:ca:west-county-wastewater-district",
            classify.SPECIAL_DISTRICT,
        ),
    ],
)
def test_every_namespace(raw, gov_id, gov_type):
    match = resolve(raw)
    assert (match.gov_id, match.gov_type) == (gov_id, gov_type)


def test_calgary_keys_to_its_census_subdivision():
    """Calgary AB is the repo's standing eScribe sample (CLAUDE.md)."""
    assert resolve("Calgary, AB").gov_id == "ca:csd:4806016"


def test_blank_input_with_a_host_is_rtr_unknown():
    match = resolve(None, "some-unknown-host.example.com")
    assert match.gov_id == "rtr:unknown:some-unknown-host.example.com"
    assert match.tier == resolver.TIER_BLANK
    assert match.gov_name == "Unidentified government (some-unknown-host.example.com)"


# --- The tiers ---------------------------------------------------------


def test_pinned_authoritative_wins_outright(monkeypatch):
    """`slc.primegov.com` is the one `authoritative` entry in
    `_KNOWN_DOMAINS` today -- its own page text is confirmed unreliable,
    which is why validation alone can never fix it."""
    gov = registry.Government(
        gov_id="us:place:4967000",
        gov_name="Salt Lake City city",
        gov_type=classify.MUNICIPALITY,
        state="UT",
    )
    monkeypatch.setattr(registry, "governments", lambda: {gov.gov_id: gov})
    monkeypatch.setattr(
        registry,
        "tenant_overrides",
        lambda: {
            "slc.primegov.com": [
                registry.TenantOverride(
                    tenant_host="slc.primegov.com",
                    gov_id="us:place:4967000",
                    strength="authoritative",
                )
            ]
        },
    )
    # A plausible, wrong extraction that WOULD validate on its own.
    match = resolve("Holladay, UT", "slc.primegov.com")
    assert match.gov_id == "us:place:4967000"
    assert match.tier == resolver.TIER_PINNED


def test_pinned_fallback_only_fires_when_the_ladder_found_nothing(monkeypatch):
    gov = registry.Government(
        gov_id="us:place:4967000",
        gov_name="Salt Lake City city",
        gov_type=classify.MUNICIPALITY,
        state="UT",
    )
    monkeypatch.setattr(registry, "governments", lambda: {gov.gov_id: gov})
    monkeypatch.setattr(
        registry,
        "tenant_overrides",
        lambda: {
            "example.primegov.com": [
                registry.TenantOverride(
                    tenant_host="example.primegov.com",
                    gov_id="us:place:4967000",
                    strength="fallback",
                )
            ]
        },
    )
    # A real name resolves on its own; the fallback must not override it.
    assert resolve("Fresno, CA", "example.primegov.com").gov_id == "us:place:0627000"
    # Nothing extracted -- now the fallback is the answer.
    pinned = resolve(None, "example.primegov.com")
    assert pinned.gov_id == "us:place:4967000"
    assert pinned.tier == resolver.TIER_PINNED


def test_a_match_discriminator_picks_between_two_governments(monkeypatch):
    """The Cottage Grove case as a pin: one host, two governments,
    separated by a query parameter."""
    town = registry.Government(
        "us:cousub:5502517200", "Cottage Grove town", classify.TOWNSHIP, state="WI"
    )
    village = registry.Government(
        "us:place:5517175", "Cottage Grove village", classify.MUNICIPALITY, state="WI"
    )
    monkeypatch.setattr(
        registry, "governments", lambda: {g.gov_id: g for g in (town, village)}
    )
    monkeypatch.setattr(
        registry,
        "tenant_overrides",
        lambda: {
            "wi-cottagegrove.civicplus.com": [
                registry.TenantOverride(
                    "wi-cottagegrove.civicplus.com",
                    town.gov_id,
                    match="view_id=2",
                    strength="authoritative",
                ),
                registry.TenantOverride(
                    "wi-cottagegrove.civicplus.com",
                    village.gov_id,
                    strength="authoritative",
                ),
            ]
        },
    )
    assert (
        resolve(
            None, "wi-cottagegrove.civicplus.com", page_hints={"view_id": "2"}
        ).gov_id
        == town.gov_id
    )
    assert resolve(None, "wi-cottagegrove.civicplus.com").gov_id == village.gov_id


def test_tiers_are_the_documented_four():
    assert {
        resolver.TIER_PINNED,
        resolver.TIER_REGISTRY,
        resolver.TIER_UNVERIFIED,
        resolver.TIER_BLANK,
    } == {"pinned", "registry", "unverified", "blank"}


# --- meeting_body, and D2's separate-then-relate test ------------------


def test_state_chamber_becomes_the_body_not_the_identity():
    """D1: one government per state; the Senate is a body under it."""
    match = resolve("Minnesota Senate, MN")
    assert match.gov_id == "us:state:27"
    assert match.gov_name == "State of Minnesota"
    assert match.meeting_body == "Senate"


def test_housing_authority_is_its_own_government_not_a_body():
    """D2: an entity with its own board, statute and budget gets its own
    gov_id rather than being folded into a parent as a body. This is a
    deliberate change from `finalize_jurisdiction()`'s own split, which
    returns jurisdiction "County of Santa Clara, CA" + body "Housing
    Authority" (JURISDICTION_METADATA_PLAN.md's worked example) -- that
    behaviour is untouched, this decides which of its outputs is the
    identity."""
    match = resolve("Housing Authority of the County of Santa Clara, CA")
    assert match.gov_id == "rtr:us:ca:housing-authority-of-the-county-of-santa-clara"
    assert match.gov_type == classify.SPECIAL_DISTRICT
    assert match.meeting_body is None


def test_a_council_is_still_a_body_of_its_place():
    """The other side of D2's test: a City Council has no legal identity
    of its own, so it must NOT become a separate government."""
    assert (
        classify.classify_government_type("City Council") != classify.SPECIAL_DISTRICT
    )


# --- Repair behaviours inherited from finalize_jurisdiction ------------


def test_nbsp_and_bleed_repairs_still_apply():
    """ "Menifee\xa0, CA" is a real stored value. The registry does not
    reimplement the repair -- it calls `finalize_jurisdiction()`."""
    assert resolve("Menifee\xa0, CA").gov_id == "us:place:0646842"


def test_consolidated_city_county_keys_to_its_place():
    """San Francisco is one government. Census keys it as a place; the
    literal word "County" in its name would otherwise send it to the
    county table, where it does not match."""
    match = resolve("City and County of San Francisco, CA")
    assert match.gov_id == "us:place:0667000"
    assert match.gov_name == "San Francisco, CA"


def test_balance_consolidated_governments_still_resolve():
    """Nashville-Davidson is a Census "(balance)" row -- the shape
    `build_jurisdiction_data.py` learned to keep in 2026-08-15."""
    assert resolve("Nashville-Davidson, TN").gov_id.startswith("us:place:")


def test_saint_spelling_matches_the_abbreviated_table_key():
    assert resolve("Saint Paul, MN").gov_id == resolve("St. Paul, MN").gov_id


# --- Display and slug --------------------------------------------------


def test_display_uses_suffix_form_for_counties():
    assert resolve("County of Napa, CA").gov_name == "Napa County, CA"


def test_display_disambiguates_a_within_state_collision():
    assert (
        resolve("Village of Cottage Grove, WI").gov_name
        == "Cottage Grove (village), WI"
    )


def test_display_does_not_disambiguate_an_uncontested_name():
    assert resolve("City of Fresno, CA").gov_name == "Fresno, CA"


def test_hub_slug_matches_the_shipped_slug_rule():
    """`display.slugify()` is a copy of
    `archive/utils/slugify.slugify_text()` -- this package may not import
    from `archive/`. Pinned here so an edit to either side fails loudly
    rather than silently splitting every `/j/` slug in two."""
    from archive.utils.slugify import slugify_text

    for text in [
        "Napa, CA",
        "County of Napa, CA",
        "California State Senate",
        "Cottage Grove (village), WI",
        "St. Paul, MN",
        "Unidentified government (foo.example.com)",
    ]:
        assert display.slugify(text) == slugify_text(text)


def test_existing_hub_slugs_mostly_survive():
    """D6 accepts that a handful of `/j/` slugs change, with 301s. These
    are real archived jurisdictions whose slug must NOT change."""
    from archive.utils.jurisdiction_format import jurisdiction_hub_slug

    for raw in ["Napa, CA", "Dublin, CA", "Calgary, AB", "Fresno County, CA"]:
        assert resolve(raw).hub_slug == jurisdiction_hub_slug(raw)


# --- The tables and the registry files ---------------------------------


def test_exactly_one_match_or_nothing():
    """A nationally-ambiguous bare name with no state must resolve to
    nothing rather than to a plausible wrong government. "Springfield" is
    a real place in more than 30 states."""
    match = resolve("Springfield")
    assert match.gov_id.startswith("rtr:")
    assert match.tier == resolver.TIER_UNVERIFIED


def test_a_cdp_is_never_a_government():
    """CDPs are statistical areas with no government (§4). The build
    script drops them; this asserts the table it produced actually has."""
    with open(DATA_DIR / "us_places.csv", encoding="utf-8") as fh:
        funcstats = {row["funcstat"] for row in csv.DictReader(fh)}
    assert funcstats <= {"A", "B", "F"}


def test_canadian_tables_carry_no_unorganized_areas():
    """D4 / SGC_2021_NOTES.md: `NO` (unorganized) and `IRI` (Indian
    reserve) are not municipal governments and get no `ca:csd` row."""
    with open(DATA_DIR / "ca_csd.csv", encoding="utf-8") as fh:
        types = {row["csd_type"] for row in csv.DictReader(fh)}
    assert not types & {"NO", "SNO", "IRI", "S-É", "RDA"}


def test_school_district_ids_are_state_fips_plus_nces_lea():
    match = resolve("Los Angeles Unified School District, CA")
    assert match.gov_id == "us:sd:0622710"
    assert match.government.nces_lea_id == "22710"


def test_every_tenant_override_row_has_a_resolvable_gov_id():
    """§4: every row in `tenant_overrides.csv` needs a gov_id, and that
    gov_id needs a `governments.csv` row -- a pin whose name nothing can
    render is a broken registry, not a resolution."""
    govs = registry.governments()
    missing = sorted(
        {
            override.gov_id
            for rows in registry.tenant_overrides().values()
            for override in rows
            if override.gov_id not in govs
        }
    )
    assert missing == []


def test_relations_file_uses_only_the_three_allowed_edges():
    """D2 keeps relations deliberately few, so the file cannot become a
    dumping ground for "things that are kind of about each other"."""
    for _from, relation, _to, _evidence in registry.relations():
        assert relation in registry.RELATIONS


def test_every_relation_points_at_a_real_government_and_carries_evidence():
    govs = registry.governments()
    for from_id, relation, to_id, evidence in registry.relations():
        assert from_id in govs, f"{relation} from an unknown government: {from_id}"
        assert to_id in govs, f"{relation} to an unknown government: {to_id}"
        assert evidence, f"{from_id} {relation} {to_id} has no evidence"


def test_the_two_relations_d2_names_as_examples_are_present():
    edges = {(f, r, t) for f, r, t, _e in registry.relations()}
    assert (
        "rtr:us:ca:los-angeles-department-of-water-and-power",
        "part_of",
        "us:place:0644000",
    ) in edges
    served = {
        t
        for f, r, t in edges
        if r == "serves" and f == "rtr:us:ca:menlo-park-fire-protection-district"
    }
    # Menlo Park, Atherton, East Palo Alto.
    assert served == {"us:place:0646870", "us:place:0603092", "us:place:0620956"}


def test_country_comes_from_the_namespace_not_a_shared_column():
    """§1.6: "CA" means California in a state column and Canada in a
    country column today. The prefix fixes it for free."""
    assert tables.country_for_state("CA") == "us"
    assert tables.country_for_state("ON") == "ca"
    assert resolve("Calgary, AB").country == "ca"
    assert resolve("Fresno, CA").country == "us"


def test_resolver_imports_nothing_but_jurisdiction_enrich_from_this_repo():
    """D5: the package must be liftable into its own distribution. A new
    import from `app.platforms`, `archive/`, or a database module would
    silently break that; this fails the build instead."""
    package = Path(gov_registry.__file__).parent
    allowed = {"app.utils.jurisdiction_enrich", "jurisdiction_enrich"}
    offenders = []
    for path in sorted(package.glob("*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped.startswith(("import ", "from ")):
                continue
            if stripped.startswith("from ..") or " app." in f" {stripped}":
                if not any(name in stripped for name in allowed):
                    offenders.append(f"{path.name}: {stripped}")
            if "archive" in stripped and "from" in stripped:
                offenders.append(f"{path.name}: {stripped}")
    assert offenders == []


# --- Fragmentation sources found by the first scoring run --------------
#
# Each of these was a real duplicate in the 2026-09-02 run over 5,053
# archived pages and 876 ledger pairs -- the same government arriving at
# two gov_ids. Pinned so they cannot come back.


def test_a_trailing_full_stop_does_not_fork_a_government():
    """ "Milwaukee." is a real stored jurisdiction. It minted
    `rtr:us:xx:milwaukee` while "Milwaukee, WI" keyed to its place -- one
    government, two hubs, over a full stop."""
    assert resolve("Milwaukee.").gov_id == resolve("Milwaukee, WI").gov_id


def test_a_state_suffix_without_its_comma_still_counts():
    """ "Benicia CA" and "Clayton CA" are real stored values."""
    assert resolve("Benicia CA").gov_id == resolve("Benicia, CA").gov_id
    assert resolve("Clayton CA").gov_id == "us:place:0613882"


def test_a_minted_id_ignores_a_leading_city_of():
    """355 of the first run's 1,198 minted rows carried a leading type
    phrase, and `/j/easton`, `/j/portage` and `/j/hamilton` each split in
    two purely because of it. The display name still keeps the raw
    string; only the id collapses."""
    assert resolve("City of Easton").gov_id == resolve("Easton").gov_id
    assert resolve("City of Easton").gov_id.endswith(":easton")
