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
    a real place in more than 30 states.

    Since Phase 1b it is `unresolved` rather than minted: with no state
    there is no id to mint that would not fragment against the same
    government named with one."""
    match = resolve("Springfield")
    assert match.gov_id == ""
    assert match.tier == resolver.TIER_UNRESOLVED


def test_a_cdp_is_never_a_government():
    """CDPs are statistical areas with no government (§4). The build
    script drops them; this asserts the table it produced actually has.

    "N" (nonfunctioning) is kept for exactly one GEOID -- Washington DC,
    which Census codes that way as a *place* because its government is
    state-level. The other three "N" rows nationally are genuinely
    defunct place governments, and Louisville city in particular must
    stay out or it collides with the real metro-government row."""
    with open(DATA_DIR / "us_places.csv", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert {r["funcstat"] for r in rows} <= {"A", "B", "F", "N"}
    assert [r["geoid"] for r in rows if r["funcstat"] == "N"] == ["1150000"]


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
    """355 of the Phase 1 run's 1,198 minted rows carried a leading type
    phrase, and `/j/easton`, `/j/portage` and `/j/hamilton` each split in
    two purely because of it. The display name still keeps the raw
    string; only the id collapses.

    Shown on a real Canadian mint (Leduc AB, `pub-leduc.escribemeetings.com`)
    -- since Phase 1b a stateless name is `unresolved` rather than
    minted, so a minted example needs a state."""
    assert resolve("City of Port Moody, BC").gov_id == resolve("Port Moody, BC").gov_id
    assert resolve("City of Port Moody, BC").gov_id == "ca:csd:5915043"
    # A government no national table covers, which is where minting is
    # the right answer -- and where the leading phrase must still not
    # fork the id. Leduc AB was this example until Phase 2's Canadian
    # tie-break gave it a real `ca:csd` id (see
    # test_a_flattened_county_name_does_not_shadow_the_city).
    assert (
        resolve("City of West County Wastewater District, CA").gov_id
        == resolve("West County Wastewater District, CA").gov_id
        == "rtr:us:ca:west-county-wastewater-district"
    )


# --- Phase 1b: a municipal name may never resolve to a county ----------
#
# Every string below is a real stored jurisdiction that landed on a county
# in the 2026-09-02 Phase 1 run, merging a city's pages into its county's
# hub -- worse than not resolving, because it looks resolved.


@pytest.mark.parametrize(
    "raw,wrong_county",
    [
        ("City of Santa Clara", "us:county:06085"),
        ("City of Riverside", "us:county:06065"),
        ("City of Maricopa", "us:county:04013"),
        ("City of Boise, ID", "us:county:16015"),
        ("City of Waukesha, WI", "us:county:55133"),
        ("City of Greenville", "us:county:45045"),
        ("City of Santa Rosa", "us:county:12113"),
    ],
)
def test_a_municipal_type_word_never_resolves_to_a_county(raw, wrong_county):
    match = resolve(raw)
    assert match.gov_id != wrong_county
    assert not match.gov_id.startswith("us:county:")


def test_a_municipal_type_word_never_resolves_to_a_mismatched_cousub():
    """The regression the county gate created before the cousub branch
    was gated too: "City of Santa Clara" stopped becoming Santa Clara
    County and started becoming `us:cousub:3603365178` -- Santa Clara
    TOWN, NY. One wrong government swapped for another."""
    assert resolve("City of Santa Clara").gov_id != "us:cousub:3603365178"


def test_a_within_state_place_collision_uses_the_raw_type_word():
    """Waukesha WI is a city (5584250) and a village (5584275), two rows
    under one normalized key, so the exactly-one rule declined and
    "City of Waukesha, WI" fell through to Waukesha County."""
    assert resolve("City of Waukesha, WI").gov_id == "us:place:5584250"
    assert resolve("Village of Waukesha, WI").gov_id == "us:place:5584275"


def test_a_collision_with_no_type_word_resolves_to_nothing():
    """Two candidates and nothing to choose by: decline. Picking the more
    populous Waukesha would be a guess."""
    match = resolve("Waukesha")
    assert not match.gov_id.startswith("us:place:")


# --- Phase 1b: Census official-name shapes -----------------------------


@pytest.mark.parametrize(
    "raw,gov_id",
    [
        # "Boise City city" is the Census/legal name; no page writes it.
        ("City of Boise, ID", "us:place:1608830"),
        # Both real archived Nashville tenants must land on one id.
        ("Nashville-Davidson County, TN", "us:place:4752006"),
        ("Nashville-Davidson metropolitan government, TN", "us:place:4752006"),
        # The enricher's own "Louisville / Jefferson County Metro" shape.
        ("Louisville, KY", "us:place:2148006"),
        ("Louisville / Jefferson County Metro, KY", "us:place:2148006"),
        # DC: Census codes it FUNCSTAT "N" as a place because its
        # government is state-level, so the build script keeps it by GEOID.
        ("Washington, DC", "us:place:1150000"),
        # One page stores the short form, three store the long one.
        ("Bainbridge, WA", "us:place:5303736"),
        ("Bainbridge Island, WA", "us:place:5303736"),
    ],
)
def test_census_official_name_shapes(raw, gov_id):
    assert resolve(raw).gov_id == gov_id


def test_a_real_louisville_elsewhere_is_not_the_kentucky_metro():
    """The curated alias is keyed by state, because Louisville CO and
    Louisville OH are real, different governments."""
    assert resolve("Louisville, CO").gov_id == "us:place:0846355"
    assert resolve("Louisville, OH").gov_id == "us:place:3945094"


def test_only_curated_rows_contribute_lookup_aliases():
    """A generated row's `aliases` column records what resolved there;
    looking those up would cement the resolver's own mistakes. Only
    hand-written rows are an assertion about naming."""
    for (_state, _alias), gov_id in registry.curated_aliases().items():
        gov = registry.governments()[gov_id]
        assert gov.source.startswith(registry.CURATED_SOURCE_PREFIX)


# --- Phase 1b: never an unknown-state id -------------------------------


def test_no_id_is_ever_minted_with_an_unknown_state():
    """`rtr:us:xx:easton` and `rtr:us:pa:easton` would be two governments
    for one. 624 rows carried an "xx" id in the Phase 1 run."""
    for raw in ["City of Riverside", "Washington", "Nashville", "Some Unlisted Board"]:
        assert ":xx:" not in resolve(raw).gov_id


def test_a_stateless_name_with_nothing_to_go_on_is_unresolved_not_minted():
    match = resolve("City of Greenville")
    assert match.gov_id == ""
    assert match.tier == resolver.TIER_UNRESOLVED
    assert match.gov_name == "City of Greenville"


def test_the_state_comes_from_the_tenant_before_the_lookup_not_after():
    """One tenant, one government. `riversideca.granicus.com` stored
    "City of Riverside" on one page and a bare "Riverside" on the next;
    the bare one resolved to Riverside County, because "Riverside"
    matches three CA places' worth of ambiguity nationally and exactly
    one county. Recovering CA from the tenant first settles it."""
    host = "riversideca.granicus.com"
    assert (
        resolve("Riverside", host).gov_id == resolve("City of Riverside", host).gov_id
    )
    assert resolve("Riverside", host).gov_id == "us:place:0662000"


def test_same_tenant_consistency_is_a_tier_of_its_own(monkeypatch):
    """Rung 5b. The caller supplies the dominant gov_id because the
    resolver is pure and cannot see a page's siblings.

    The name has to agree -- see the over-fire tests below for what the
    unguarded version of this rung did to two real tenants."""
    gov = registry.Government(
        "us:place:0662000", "Riverside city", classify.MUNICIPALITY, state="CA"
    )
    monkeypatch.setattr(registry, "governments", lambda: {gov.gov_id: gov})
    monkeypatch.setattr(registry, "tenant_overrides", lambda: {})
    monkeypatch.setattr(registry, "tenant_hints", lambda: {})
    match = resolve(
        "The City of Riverside",
        "example.granicus.com",
        tenant_gov_id="us:place:0662000",
    )
    assert match.gov_id == "us:place:0662000"
    assert match.tier == resolver.TIER_INFERRED
    assert "example.granicus.com" in match.evidence


# --- Phase 2 (7a): the tenant-consistency rung needs a name guard ------
#
# Every case below is a real (tenant, jurisdiction) pair from
# reports/gov_registry_scoring_2026-09-02/sheet_archive.csv.


@pytest.mark.parametrize(
    "raw,host,tenant_gov_id,expected",
    [
        # "The City of Milwaukee, WI" matched no place key (the leading
        # "The" defeats the enricher's prefix strip) and minted a second
        # id beside `milwaukee.granicus.com`'s own City of Milwaukee.
        (
            "The City of Milwaukee, WI",
            "milwaukee.granicus.com",
            "us:place:5553000",
            "us:place:5553000",
        ),
        (
            "The City of Andover",
            "andoverks.civicweb.net",
            "us:place:2001800",
            "us:place:2001800",
        ),
        (
            "The City of College Park, MD",
            "college-park.granicus.com",
            "us:place:2418750",
            "us:place:2418750",
        ),
    ],
)
def test_tenant_consistency_collapses_a_spelling_of_the_tenants_own_name(
    raw, host, tenant_gov_id, expected
):
    match = resolve(raw, host, tenant_gov_id=tenant_gov_id)
    assert match.gov_id == expected
    assert match.tier == resolver.TIER_INFERRED


@pytest.mark.parametrize(
    "raw,host,tenant_gov_id",
    [
        # Dallas County Community College District. Its own bleed page
        # reads "City of Dallas"; the tenant's other page is Duncanville.
        # The unguarded rung filed a Dallas page under Duncanville.
        ("City of Dallas", "dcccd.new.swagit.com", "us:place:4821628"),
        # A shared host serving several real governments: nothing on it
        # names Scituate, so nothing may claim it.
        ("Scituate Town Council", "clerkshq.com", "us:place:3986940"),
    ],
)
def test_tenant_consistency_does_nothing_when_the_names_disagree(
    raw, host, tenant_gov_id
):
    match = resolve(raw, host, tenant_gov_id=tenant_gov_id)
    assert match.tier == resolver.TIER_UNRESOLVED
    assert match.gov_id == ""


def test_tenant_consistency_will_not_cross_a_state_line():
    """`juneauak.portal.civicclerk.com` stores two pages as "Juneau, WI"
    and one as "Juneau, AK". The names agree perfectly, and adopting the
    tenant's dominant government would file the City and Borough of
    Juneau under a Wisconsin city on the strength of a spelling."""
    match = resolve(
        "Juneau, AK",
        "juneauak.portal.civicclerk.com",
        tenant_gov_id="us:place:5538675",
    )
    assert match.gov_id != "us:place:5538675"


def test_tenant_consistency_never_reads_a_generated_rows_aliases():
    """The first run of the guard passed on `winston-salem.granicus.com`'s
    bleed page, because `governments.csv` carried "City of Lees Summit" in
    Winston-Salem's `aliases` -- written there by the very unguarded pass
    this rung replaces. On a GENERATED row that column records what
    previously resolved here, so reading it back makes a wrong resolution
    self-reinforcing (`registry.curated_aliases()` says the same thing
    about lookups)."""
    gov = registry.Government(
        "us:place:3775000",
        "Winston-Salem city",
        classify.MUNICIPALITY,
        state="NC",
        aliases=("City of Lees Summit",),
        source="us_places.csv",
    )
    assert resolver._tenant_consistency(gov.gov_id, "City of Lees Summit", "") is None


def test_a_bleed_page_on_the_wrong_tenant_is_listed_not_minted(monkeypatch):
    """§7f. Lee's Summit is in Missouri, `winston-salem.granicus.com` is
    in North Carolina, and "City of Lees Summit" matches no NC table row.
    Minting produced `rtr:us:nc:lees-summit` -- a permanent,
    official-looking id for a government that does not exist in that
    state, which is worse than an honest gap."""
    gov = registry.Government(
        "us:place:3775000", "Winston-Salem city", classify.MUNICIPALITY, state="NC"
    )
    monkeypatch.setattr(registry, "governments", lambda: {gov.gov_id: gov})
    monkeypatch.setattr(registry, "tenant_overrides", lambda: {})
    monkeypatch.setattr(
        registry, "tenant_hints", lambda: {"winston-salem.granicus.com": "NC"}
    )
    match = resolve(
        "City of Lees Summit",
        "winston-salem.granicus.com",
        tenant_gov_id="us:place:3775000",
    )
    assert match.tier == resolver.TIER_UNRESOLVED
    assert match.gov_id == ""


def test_a_district_on_its_host_city_still_mints(monkeypatch):
    """The exemption that keeps the bleed rule from eating decision D2:
    a housing authority disagreeing with its host city's name is the
    NORMAL case for a non-place government, not evidence of a bleed, and
    D2 says it gets its own id."""
    gov = registry.Government(
        "us:place:0644000", "Los Angeles city", classify.MUNICIPALITY, state="CA"
    )
    monkeypatch.setattr(registry, "governments", lambda: {gov.gov_id: gov})
    monkeypatch.setattr(registry, "tenant_overrides", lambda: {})
    monkeypatch.setattr(registry, "tenant_hints", lambda: {"ladwp.granicus.com": "CA"})
    match = resolve(
        "Los Angeles Department of Water and Power",
        "ladwp.granicus.com",
        tenant_gov_id="us:place:0644000",
    )
    assert match.gov_id.startswith("rtr:us:ca:")
    assert match.tier == resolver.TIER_UNVERIFIED


# --- Phase 2 (7b): a spacing slip is not a new government --------------


def test_a_spacing_slip_resolves_rather_than_minting():
    """`galesburg.granicus.com` stores "Gales Burg" on one page and
    "Galesburg, IL" on the next -- one government, and minting the first
    gave it a second permanent id."""
    match = resolve("Gales Burg", "galesburg.granicus.com")
    assert match.gov_id == "us:place:1728326"
    assert match.tier == resolver.TIER_REGISTRY
    assert match.gov_id == resolve("Galesburg, IL").gov_id


def test_the_spacing_insensitive_lookup_needs_a_state():
    """It is a looser key than the real one, so running it nationally
    would let two different governments collide on a squashed spelling.
    Tried only with a state in hand, and only when the alternative is
    minting."""
    assert tables.us_places().lookup_squashed("Gales Burg", None) is None
    assert tables.us_places().lookup_squashed("Gales Burg", "IL").row_id == "1728326"


# --- Phase 2 (7c): "Name, X County, ST" names a place and its county ---


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("City of Sunset Valley, Travis County, TX", "us:place:4871324"),
        ("Town of Amherst, Erie County, NY", "us:cousub:3602902000"),
    ],
)
def test_a_named_county_is_enrichment_not_the_government(raw, expected):
    """Both are real archived jurisdictions, and both minted an `rtr:` id
    for a government the tables already hold -- the county word in the
    middle classified the whole string as a county."""
    match = resolve(raw)
    assert match.gov_id == expected
    assert match.tier == resolver.TIER_REGISTRY
    # Seen and set aside, not silently dropped.
    assert "County" in match.evidence


def test_a_body_named_before_a_county_is_not_a_place():
    """The gate on the county-qualifier rule: without it the same shape
    would eat the tail of a body name and resolve a county's page to
    "Board of Supervisors"."""
    assert resolver._strip_county_qualifier("Board of Supervisors, Fresno County") == (
        "Board of Supervisors, Fresno County",
        "",
    )


# --- Phase 2 (7d): the Canadian tables need the same type-word gate ----


def test_a_canadian_town_is_not_its_census_division():
    """ "Town of Yarmouth, NS" resolved to `ca:cd:1202`, the Yarmouth
    census division: two CSDs share the name (1202006, the town; 1202004,
    the municipal district around it), the exactly-one rule declined, and
    the census-division fallback caught the fall. Filing a town under its
    county is the mistake the US county gate already prevents."""
    match = resolve("Town of Yarmouth, NS")
    assert match.gov_id == "ca:csd:1202006"
    assert match.tier == resolver.TIER_REGISTRY


@pytest.mark.parametrize("raw", ["City of Leduc, AB", "Leduc, AB"])
def test_a_flattened_county_name_does_not_shadow_the_city(raw):
    """ "Leduc County" and "Leduc" are two different names, not one name
    shared by two governments -- `_normalize_name()`'s trailing-type-word
    strip is what collapses them onto one key. Both spellings of the city
    must reach the city, or the type-word tie-break would trade one
    fragmentation for another."""
    assert resolve(raw).gov_id == "ca:csd:4811016"


# --- Phase 2 (7e): Honolulu is one consolidated government -------------


@pytest.mark.parametrize("raw", ["City of Honolulu", "County of Honolulu."])
def test_honolulu_is_one_government(raw):
    """Both strings are real, both on `honolulu.granicus.com`, and both
    for Granicus clip 2444 -- the same meeting archived twice. Hawaii has
    no separate municipal government for Honolulu; the City and County IS
    the county."""
    match = resolve(raw, "honolulu.granicus.com")
    assert match.gov_id == "us:county:15003"
    assert match.gov_name == "City and County of Honolulu, HI"


# --- Phase 2: "port" is a port agency, not any place named Port X ------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("City of Port Townsend, WA", "us:place:5355855"),
        ("City of Port Moody, BC", "ca:csd:5915043"),
        ("North Port, FL", "us:place:1249675"),
    ],
)
def test_a_place_named_port_is_not_a_special_district(raw, expected):
    """Same defect as the "wastewater" one the architecture doc's §1.4
    correction records: a bare `port` token in the special-district rule
    put the place tables out of reach (NON_PLACE_TYPES) for 24 rows over
    11 real municipalities, every one of which minted an `rtr:` id for a
    government the national tables hold."""
    assert resolve(raw).gov_id == expected


@pytest.mark.parametrize("raw", ["Boise, ID", "City of Boise, ID"])
def test_both_spellings_of_boise_reach_the_city(raw):
    """Census spells the city "Boise City city", so the place lookup
    misses and the bare-name county fallback answered first -- "Boise,
    ID" resolved to Boise COUNTY while "City of Boise, ID" resolved
    correctly, because a municipal type word gates that fallback off. One
    city, two governments, depending on how a page spelled it. The
    fallback now declines a name a curated row already claims."""
    assert resolve(raw).gov_id == "us:place:1608830"


def test_the_county_itself_is_not_shadowed_by_the_citys_alias():
    """The other half of the same fix: "Boise County, ID" normalizes to
    the same key as the city's curated alias, so the alias is *checked*
    to decline the fallback and never *returned* from it."""
    assert resolve("Boise County, ID").gov_id == "us:county:16015"


# --- Phase 2: "nationally unique" has to mean both countries ----------


@pytest.mark.parametrize(
    "raw,wrong",
    [
        ("Abbotsford", "us:place:5500100"),  # Abbotsford BC, filed as WI
        ("Edmonton", "us:place:2123968"),  # Edmonton AB, filed as KY
        ("City of Langford", "us:place:4635820"),  # Langford BC, filed as SD
        ("City of White Rock", "us:place:4671380"),  # White Rock BC, filed as SD
        ("City of Niagara Falls", "us:place:3651055"),  # Niagara Falls ON, as NY
        ("Port Hope", "us:place:2665800"),  # Port Hope ON, filed as MI
    ],
)
def test_a_stateless_name_is_not_unique_just_because_the_us_table_says_so(raw, wrong):
    """`country_for_state("")` is "us", so a name with no state was looked
    up in the US tables alone and a unique hit there looked unambiguous
    while a Canadian government of the same name sat unchecked. Every
    string here is a real stored jurisdiction on a real Canadian eScribe
    or CivicWeb tenant."""
    assert resolve(raw).gov_id != wrong


def test_a_state_still_settles_the_country():
    """The guard is about the STATELESS case only -- a name that says
    which state or province it is in was never ambiguous."""
    assert resolve("Abbotsford, WI").gov_id == "us:place:5500100"
    assert resolve("Abbotsford, BC").gov_id == "ca:csd:5909052"


def test_a_real_port_agency_still_classifies_as_a_district():
    for raw in ("Port of Seattle, WA", "Port Authority of New York and New Jersey"):
        assert classify.classify_government_type(raw) == classify.SPECIAL_DISTRICT


def test_a_tenant_hint_supplies_only_a_state_never_a_government():
    """`tenant_hints.csv` is fed by rtr-discovery's own
    `tenants.jurisdiction_override`, whose values include "S Fw, MD",
    "Mw Rd", "Psr C 2" and "Tampa D". Those are useless as government
    names and still correct about the state."""
    hints = registry.tenant_hints()
    assert hints, "expected seeded tenant hints"
    for state in hints.values():
        assert len(state) == 2 and state.isalpha()


# --- Phase 1b: seeding ------------------------------------------------


def test_no_pin_is_sourced_only_from_auto_derived():
    """A pin is the one tier that overrides a working extraction, so a
    machine-derived subdomain guess is the last thing that belongs in
    one. 447 hosts were demoted to state-only hints."""
    offenders = [
        host
        for host, rows in registry.tenant_overrides().items()
        for o in rows
        if o.source == "auto_derived"
    ]
    assert offenders == []


def test_imperial_irrigation_district_is_not_imperial_county():
    """Found in the Phase 1b pass from the export itself: the host's one
    archived page has slug "imperial-iid-bod-regular-meeting-january-21-
    2025" -- Imperial Irrigation District Board of Directors -- while its
    stored jurisdiction is a bare "Imperial", which resolved to Imperial
    County CA."""
    match = resolve("Imperial", "imperialid.granicus.com")
    assert match.gov_id == "rtr:us:ca:imperial-irrigation-district"
    assert match.gov_id != "us:county:06025"


# --- Phase 1b: display ------------------------------------------------


def test_within_state_disambiguation_uses_one_parenthetical_form():
    """Both sides of a shared name read the same way. The suffix form
    ("Cottage Grove Town") reads as a different name rather than as a
    disambiguator."""
    assert resolve("Town of Cottage Grove, WI").gov_name == "Cottage Grove (town), WI"
    assert (
        resolve("Village of Cottage Grove, WI").gov_name
        == "Cottage Grove (village), WI"
    )


def test_an_uncontested_township_keeps_the_suffix_form():
    assert resolve("Chesterfield Township, MI").gov_name == "Chesterfield Township, MI"


def test_census_bookkeeping_is_not_part_of_a_display_name():
    """ "(balance)" and the government-type phrase are Census bookkeeping
    about the *area*, not part of the government's name."""
    assert resolve("Nashville-Davidson County, TN").gov_name == "Nashville-Davidson, TN"
    assert "(balance)" not in resolve("Louisville, KY").gov_name


def test_dc_and_louisville_are_municipalities_not_other():
    assert resolve("Washington, DC").gov_type == classify.MUNICIPALITY
    assert resolve("Louisville, KY").gov_type == classify.MUNICIPALITY


# --- Phase 1b addendum: the minting gate -------------------------------
#
# Every string below is a real stored jurisdiction produced by the old
# wordninja subdomain fallback. Minting an id for one creates a
# permanent, authoritative-looking identity for something nobody can ever
# look up.


@pytest.mark.parametrize(
    "raw",
    [
        "Llbc, AB",  # pub-llbc = Lac La Biche County
        "Notl, ON",  # Niagara-on-the-Lake
        "Ezt",  # pub-ezt = East Zorra-Tavistock
        "TV, NY",
        "Psr C 2",  # psrc2 = Puget Sound Regional Council
        "Mw Rd",
        "S Fw, MD",
        "Ride Uta",
        "Auroratv, CO",  # named as junk in JURISDICTION_METADATA_PLAN.md
    ],
)
def test_a_string_that_is_not_a_name_is_never_minted(raw):
    match = resolve(raw)
    assert match.gov_id == ""
    assert match.tier == resolver.TIER_UNRESOLVED
    # The raw string survives in evidence, so a human pin loses nothing.
    assert raw.split(",")[0] in match.evidence


def test_a_name_made_only_of_type_words_is_not_a_name():
    """`allentownpa.granicus.com` stores "City of Al" -- a truncated "City
    of Allentown" whose stray "Al" the bare-state-suffix rule then read as
    Alabama, leaving the name "City of" and minting `rtr:us:al:city-of`,
    displayed to a reader as "City of, AL". Every step is individually
    defensible, which is why the gate is on the outcome."""
    match = resolve("City of Al", "allentownpa.granicus.com")
    assert match.tier == resolver.TIER_UNRESOLVED
    assert match.gov_id == ""


@pytest.mark.parametrize(
    "raw",
    [
        "West County Wastewater District, CA",
        "County of Santa Clara, CA",
        "Town of Yarmouth, NS",
    ],
)
def test_the_type_word_gate_does_not_touch_a_real_name(raw):
    assert resolve(raw).gov_id


def test_a_run_together_real_name_resolves_rather_than_being_declined():
    """ "Stjohns, NL" was in the list above until Phase 2. It is not junk
    like its neighbours -- it is St. John's with its spacing and
    punctuation gone, and the spacing-insensitive lookup (rung 5b) now
    reaches the real StatCan row. The gate above is for strings that name
    no government at all; this one names one perfectly well."""
    assert resolve("Stjohns, NL").gov_id == "ca:csd:1001519"
    assert resolve("Stjohns, NL").tier == resolver.TIER_REGISTRY


@pytest.mark.parametrize(
    "raw,gov_id",
    [
        (
            "West County Wastewater District, CA",
            "rtr:us:ca:west-county-wastewater-district",
        ),
        # Leduc AB was here until Phase 2's Canadian name-first
        # tie-break gave it its real `ca:csd:4811016` -- a coverage gain,
        # not a gate failure. Replaced by another real Canadian
        # government with no StatCan id by construction (decision D4:
        # SGC codes subdivisions and divisions, not boards).
        (
            "Hamilton Police Services Board, ON",
            "rtr:ca:on:hamilton-police-services-board",
        ),
        ("Imperial Irrigation District, CA", "rtr:us:ca:imperial-irrigation-district"),
        (
            "Metropolitan Airports Commission, MN",
            "rtr:us:mn:metropolitan-airports-commission",
        ),
        (
            "Toronto and Region Conservation Authority, ON",
            "rtr:ca:on:toronto-and-region-conservation-authority",
        ),
    ],
)
def test_the_gate_still_mints_a_real_government_name(raw, gov_id):
    """The gate must not cost coverage. Each of these is a real
    government with no national table to key it to."""
    assert resolve(raw).gov_id == gov_id


def test_the_vocabulary_knows_government_words_a_place_table_does_not():
    """Built from the national tables PLUS `cog_units.csv` -- 90,837 real
    US government names. The place tables alone know "Wichita" but not
    "authority", so a vocabulary built from them would reject most real
    agency names."""
    vocabulary = tables.name_vocabulary()
    for word in ("authority", "commission", "irrigation", "wastewater", "sewerage"):
        assert word in vocabulary
    for junk in ("llbc", "notl", "stjohns", "ride"):
        assert junk not in vocabulary


def test_a_station_callsign_is_not_a_government():
    assert resolver._looks_like_a_name("KXYZ-TV") is False
    assert resolver._looks_like_a_name("WABC") is False


def test_every_token_under_four_letters_is_not_a_name():
    assert resolver._looks_like_a_name("Psr C 2") is False
    assert resolver._looks_like_a_name("Mw Rd") is False
    assert resolver._looks_like_a_name("Leduc") is True


def test_a_telvue_org_token_is_extracted_as_the_match_value():
    """Every TelVue customer shares `videoplayer.telvue.com`, so a
    host-level pin would be wrong for all of them -- the org token in the
    URL path is what identifies the government. Checked against a token
    already identified by hand in
    rtr-business/research/telvue_org_tokens.md (Centre County PA)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "score_gov_registry",
        Path(__file__).parent.parent / "scripts" / "score_gov_registry.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    url = (
        "https://videoplayer.telvue.com/player/"
        "GNduNoua2rBThhw6N4PRP9OCSPf6B2ru/playlists/4806/media/123456"
    )
    assert module._telvue_match(url) == "GNduNoua2rBThhw6N4PRP9OCSPf6B2ru"
    assert module._telvue_match("https://pub-x.escribemeetings.com/Meeting.aspx") == ""
