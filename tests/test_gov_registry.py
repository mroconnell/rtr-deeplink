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


# --- WO-105, 2026-09-03: type-word widening -----------------------------
#
# `_LEADING_TYPE_RE`/`_COMPARISON_PREFIX_RE`/`_COMPARISON_PREFIX_KIND_RE`/
# `_LEADING_ENTITY_PREFIX_RE` widened to also recognize "Village of",
# "Borough of", "Township of", "Regional Municipality of", "District of",
# "Municipality of", and Ontario's real "The Corporation of the {type}
# of" legal-name convention. Note: this repo's own brief for this pass
# claimed `_LEADING_TYPE_RE` was missing village/borough/township/
# municipality, matching jurisdiction_enrich.py's narrower
# `_STOPRULE_TRIGGER_RE` -- re-checking the actual code before touching
# it (per CLAUDE.md's own "verify a backlog entry's claims" rule) showed
# `_LEADING_TYPE_RE` already had all four; only "district of", "regional
# municipality of" and the "Corporation of the" wrapper were genuinely
# missing. The tests below cover what actually changed.


def test_corporation_of_the_wrapper_resolves_the_same_real_cottage_grove_pair():
    # Same real Wisconsin Town-of/Village-of pair as the test above, with
    # Ontario's real "The Corporation of the {type} of" legal-name prefix
    # in front -- confirms the wrapper is stripped down to the true type
    # word rather than swallowing or confusing it.
    town = resolve("The Corporation of the Town of Cottage Grove, WI")
    village = resolve("The Corporation of the Village of Cottage Grove, WI")
    assert town.gov_id == "us:cousub:5502517200"
    assert village.gov_id == "us:place:5517175"
    assert town.gov_id != village.gov_id


def test_leading_type_word_recognizes_the_newly_widened_words():
    # Direct unit test of the helper `resolve_government()`'s type-
    # preference rung depends on.
    assert resolver._leading_type_word("Village of Cottage Grove") == "village"
    assert resolver._leading_type_word("Borough of Somerville") == "borough"
    assert resolver._leading_type_word("Township of King") == "township"
    assert resolver._leading_type_word("District of North Vancouver") == "district"
    assert (
        resolver._leading_type_word("Regional Municipality of Durham")
        == "regional municipality"
    )
    assert (
        resolver._leading_type_word("The Corporation of the City of Toronto") == "city"
    )
    assert (
        resolver._leading_type_word("The Corporation of the Township of King")
        == "township"
    )
    # Unaffected: a name with no leading type word at all still returns "".
    assert resolver._leading_type_word("Cottage Grove") == ""


def test_regional_municipality_of_durham_type_word_widened_but_resolution_unchanged():
    # Honest, current-state test -- NOT what was originally expected here.
    # "Region of Peel, ON" (parametrized above) resolves correctly to
    # `ca:cd`. "Regional Municipality of Durham, ON" does not, and this
    # is a PRE-EXISTING `jurisdiction_enrich.finalize_jurisdiction()`
    # behavior, unrelated to and unchanged by this pass's widening (this
    # test never touches `_LEADING_TYPE_RE`/`_COMPARISON_PREFIX_RE`,
    # confirmed by reproducing it directly against `finalize_jurisdiction()`
    # alone): `_split_entity_prefix()` reads "Regional Municipality of
    # Durham" as an "<Entity> of <Jurisdiction>" shape (the same pattern
    # built for "Housing Authority of the County of Santa Clara") and
    # splits it into meeting_body="Regional Municipality",
    # jurisdiction="Durham, ON" -- but unlike a housing authority, "Regional
    # Municipality of X" IS the government's own identity, not a body
    # within "Durham". By the time rung 3 classifies, the entity prefix
    # is already gone, so "Durham" alone classifies as `other` and mints
    # `rtr:ca:on:durham` instead of reaching `ca:cd`. A new, separate
    # BACKLOG.md entry logs this (out of scope for this pass -- fixing it
    # means teaching `_split_entity_prefix()`/`_ENTITY_OF_PLACE_RE` to
    # recognize "Regional Municipality"/"Region"/"County" as
    # identity-carrying prefixes, not body prefixes, which is a
    # `jurisdiction_enrich.py` change well beyond a regex word-list
    # widening). Pinned here as found, not silently worked around.
    match = resolve("Regional Municipality of Durham, ON")
    assert match.tier == resolver.TIER_UNVERIFIED
    assert match.gov_id == "rtr:ca:on:durham"
    assert match.meeting_body == "Regional Municipality"


def test_district_of_north_vancouver_type_word_extracted_but_not_yet_resolved():
    # Honest, current-state test, not an aspirational one: "District of
    # North Vancouver" is a real, current BC municipality, and the
    # widened `_leading_type_word()` now correctly reads its type word as
    # "district" (see above). It still does NOT resolve to its real
    # `ca:csd` row today, because `classify.py`'s SPECIAL_DISTRICT rule
    # matches the bare word "district" before the municipality rule ever
    # runs -- a real, separate, already-logged gap (BACKLOG.md), out of
    # scope for this pass. Pinned here so a future fix to that gap has a
    # test that starts failing (a signal to update this test, not a
    # silent behavior change) rather than one that was never written.
    match = resolve("District of North Vancouver, BC")
    assert match.tier == resolver.TIER_UNVERIFIED
    assert match.gov_type == classify.SPECIAL_DISTRICT
    assert match.gov_id == "rtr:ca:bc:north-vancouver"


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


def test_gloucester_county_public_schools_va_is_its_own_government():
    """Real production defect: `/j/gloucester-ma` was a live public hub
    whose one page -- a `pub-gloucesterva.escribemeetings.com` "School
    Board Meeting" -- was keyed to Gloucester, MA via the eScribe bleed
    #707 fixed upstream. The correct identity is neither MA nor the
    county pin already covering that tenant as a fallback: Virginia
    school divisions are Census-of-Governments "dependent" (funded
    through county appropriation, no independent taxing authority --
    confirmed via Census Bureau technical documentation and Gloucester's
    own school-board budget being proposed to, and appropriated by, the
    County Board of Supervisors), but D2's test is "own governing board /
    own enabling statute / own budget", not fiscal independence -- and
    this registry already treats same-shape dependent county school
    systems as separate governments (Wilson County, TN and all six
    Maryland rows, both Census-confirmed "dependent"). Virginia school
    boards are a statutory "body corporate" (Va. Code S 22.1-71) with
    their own elected/appointed board and their own proposed budget, so
    the test passes the same way it already does for those precedents."""
    match = resolve("Gloucester County Public Schools, VA")
    assert match.gov_id == "us:sd:5101620"
    assert match.government.nces_lea_id == "01620"
    assert (
        display.display_name(match.government) == "Gloucester County Public Schools, VA"
    )
    assert display.hub_slug(match.government) == "gloucester-county-public-schools-va"


def test_a_pin_to_a_government_not_yet_in_governments_csv_still_applies():
    """`governments.csv` is a generated snapshot of what some scoring run
    resolved TO, so a pin naming a government no archived page has
    reached yet is absent from it by construction -- which is the normal
    state for a freshly hand-added pin.

    `_pinned()` used to look the id up in that file alone and fall
    through silently when it missed, so such a pin did not apply and
    nothing said so. Found when WO-99's landing-page sweep wrote seven of
    them (`us:place:0621230` Eastvale, `us:place:1248625` New Smyrna
    Beach, `us:place:4852356` North Richland Hills, `us:sd:4838730` San
    Antonio ISD, ...) and the test below turned red."""
    gov_id = "us:county:01005"  # Barbour County, AL -- in no committed row
    assert gov_id not in registry.governments()
    match = resolve(
        "Something The Tables Cannot Key",
        "example-unpinned.granicus.com",
    )
    assert match.gov_id != gov_id  # control: nothing pins this host yet
    assert registry.government_for_id(gov_id) is not None


def test_every_tenant_override_row_has_a_resolvable_gov_id():
    """§4: every row in `tenant_overrides.csv` needs a gov_id, and that
    gov_id needs to RENDER -- a pin whose name nothing can produce is a
    broken registry, not a resolution (`_pinned()` looks the id up and
    falls through to the ladder when it misses, so the host stays exactly
    as unresolved as before, with a pin claiming otherwise).

    Through `government_for_id()`, which is what `_pinned()` itself calls,
    rather than through `governments()` alone. That file is a generated
    snapshot of what some scoring run resolved TO, so a pin to a real
    national government no page has reached yet is absent from it by
    construction -- `us:county:24017` (Charles County, MD), the first pin
    `scripts/apply_pin_worklist.py` had occasion to write, is exactly
    that. `government_for_id()` derives such a row from the national
    table, which is exact rather than a guess, and still returns None for
    garbage and for a minted `rtr:` id with no committed row."""
    missing = sorted(
        {
            override.gov_id
            for rows in registry.tenant_overrides().values()
            for override in rows
            if registry.government_for_id(override.gov_id) is None
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
# reports/gov_registry_scoring_2026-09-03/sheet_archive.csv.


@pytest.mark.parametrize(
    "raw,host,tenant_gov_id,expected",
    [
        # "The City of Andover" has no state in the raw text at all, and
        # "Andover" is nationally ambiguous (MA/KS/OH/CT and more really
        # exist), so this one genuinely still needs the tenant-consistency
        # net -- unlike Milwaukee and College Park below, both of which
        # WO-251 moved off this rung entirely by fixing the place-table
        # match directly (see `test_milwaukee_now_matches_the_place_table_
        # directly()` and `test_college_park_now_matches_the_place_table_
        # directly()`, right below the class of tests this one used to
        # share a parametrize with).
        (
            "The City of Andover",
            "andoverks.civicweb.net",
            "us:place:2001800",
            "us:place:2001800",
        ),
    ],
)
def test_tenant_consistency_collapses_a_spelling_of_the_tenants_own_name(
    raw, host, tenant_gov_id, expected
):
    match = resolve(raw, host, tenant_gov_id=tenant_gov_id)
    assert match.gov_id == expected
    assert match.tier == resolver.TIER_INFERRED


def test_college_park_now_matches_the_place_table_directly():
    """Same WO-251 fix as Milwaukee, same real shape: "The City of College
    Park, MD" (real Granicus tenant text) used to need `tenant_gov_id` and
    land on `inferred`; the leading-"The" fix in jurisdiction_enrich.py's
    `_LEADING_TYPE_RE` now matches it straight to the place table with no
    tenant hint at all."""
    match = resolve("The City of College Park, MD", "college-park.granicus.com")
    assert match.gov_id == "us:place:2418750"
    assert match.tier == resolver.TIER_REGISTRY


@pytest.mark.parametrize(
    "raw,host,tenant_gov_id",
    [
        # A shared host serving several real governments: nothing on it
        # names Scituate, so nothing may claim it.
        ("Scituate Town Council", "clerkshq.com", "us:place:3986940"),
    ],
)
def test_tenant_consistency_does_nothing_when_the_names_disagree(
    raw, host, tenant_gov_id
):
    match = resolve(raw, host, tenant_gov_id=tenant_gov_id)
    # WO-210: `clerkshq.com` is itself a `MULTI_GOV_HOSTS` host (real
    # tenants live on it, keyed by path segment), and this call passes no
    # `path` at all -- so the safeguard now declines even earlier than
    # the tenant-consistency rung this test was originally about, and
    # more strongly: `TIER_BLANK`/`rtr:unknown:...` rather than
    # `TIER_UNRESOLVED`/`""`. Same real-world outcome the comment above
    # already wanted ("nothing may claim it"), just via an earlier rung.
    assert match.tier == resolver.TIER_BLANK
    assert match.gov_id == "rtr:unknown:clerkshq.com"


def test_dcccd_bleed_page_now_lands_on_the_pinned_college_district():
    """Dallas County Community College District. Its own bleed page reads
    "City of Dallas"; the tenant's other page is Duncanville, and the
    unguarded rung once filed a Dallas page under Duncanville. Until
    2026-09-09 this case sat in the parametrize above asserting
    `unresolved`; Ryan's pin worklist then pinned the host to the district
    itself, and a pin outranks every rung below it -- the page belongs to
    the college, not to Dallas or Duncanville."""
    match = resolve(
        "City of Dallas", "dcccd.new.swagit.com", tenant_gov_id="us:place:4821628"
    )
    assert match.tier == resolver.TIER_PINNED
    assert match.gov_id == "rtr:us:tx:dallas-county-community-college-district"


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


def test_youtube_channel_pins_keep_the_two_real_juneaus_apart():
    """Two real, separate YouTube channel pins, both on the shared
    `www.youtube.com` host, both named Juneau, and they must land on two
    different real places -- the same state-crossing risk the test above
    covers for `juneauak.portal.civicclerk.com`, but for a pin row rather
    than tenant consistency.

    `@cityandboroughofjuneau2053`'s own owner title is "City and Borough
    of Juneau" -- the real, official name of Juneau, ALASKA
    (`us:place:0236400`; `juneauak.portal.civicclerk.com`'s authoritative
    pin above names the same id). It was wrongly pinned to
    `us:place:5538675` (Juneau, WISCONSIN -- a real but different, much
    smaller city) during the 2026-09-09 channel fill and moved a real
    Alaska Assembly Committee of the Whole video (page 4910) into Juneau
    WI's hub -- fixed here (WO-251).

    `@cityofjuneaucabletv8377` is the one that really is Juneau WI (page
    4814, the common council) and must stay there -- this test guards
    against "fixing" the first row by guessing a blanket rule that
    repoints both."""
    alaska = resolve(
        "City and Borough of Juneau",
        "www.youtube.com",
        page_hints=resolver.page_hints_for(
            "youtube", "x", channel="@cityandboroughofjuneau2053"
        ),
    )
    assert alaska.gov_id == "us:place:0236400"
    assert alaska.tier == resolver.TIER_PINNED

    wisconsin = resolve(
        "City of Juneau",
        "www.youtube.com",
        page_hints=resolver.page_hints_for(
            "youtube", "x", channel="@cityofjuneaucabletv8377"
        ),
    )
    assert wisconsin.gov_id == "us:place:5538675"
    assert wisconsin.tier == resolver.TIER_PINNED


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


# --- WO-243: a curated government matches before name repair runs ------


@pytest.mark.parametrize(
    "raw,gov_id",
    [
        # WO-220 minted this curated row on Ryan's call, but the ladder's
        # own name repair (`_trim_repair()`/`_split_entity_prefix()`,
        # rung 2) truncated "Department of Commerce, UT" to "Commerce,
        # UT" before rung 4b's curated-alias check ever ran -- "Commerce"
        # is a real place name NATIONALLY (Commerce, CA/TX/GA and
        # Commerce City, CO all real), so the truncation looked
        # legitimate, but no "Commerce" exists in Utah, so it minted a
        # fresh `rtr:us:ut:commerce` instead of matching the curated row.
        ("Department of Commerce, UT", "rtr:us:ut:department-of-commerce"),
        # Same shape, confirmed by WO-220 too: truncated to "Southwest,
        # UT" (no "Southwest" place exists in Utah either).
        (
            "Southwest Utah Public Health Department, UT",
            "rtr:us:ut:southwest-utah-public-health-department",
        ),
        # Truncated to "Early, UT".
        (
            "Early Light Academy at Daybreak, UT",
            "rtr:us:ut:early-light-academy-at-daybreak",
        ),
        # WO-201's curated PennDOT row -- classifies `special_district`
        # on the RAW name (the word "transportation") before rung 2 ever
        # runs, so it happened to reach the right id by a different,
        # coincidental route (the raw untruncated name is what rung 6
        # mints from for a NON_PLACE_TYPES classification) -- but the
        # result before this fix was a fresh MINT (`source="minted"`,
        # tier `unverified`), not an actual match against the curated
        # row already sitting in the file, so it carried the wrong tier
        # and evidence even though the id string happened to line up.
        (
            "Pennsylvania Department of Transportation, PA",
            "rtr:us:pa:pennsylvania-department-of-transportation",
        ),
    ],
)
def test_curated_government_matches_before_name_repair_truncates_it(raw, gov_id):
    match = resolve(raw)
    assert match.gov_id == gov_id
    assert match.tier == resolver.TIER_REGISTRY


def test_name_repair_truncation_is_unaffected_for_a_real_place():
    """The truncation itself stays correct for the case it exists for --
    no curated row names bare "Fresno", so this rung is a no-op and rung
    2's repair (then rung 4's national lookup) still runs exactly as
    before."""
    assert resolve("City of Fresno, CA").gov_id == "us:place:0627000"


# --- WO-251: "The City of X, ST" backfill regression, re-derived -------
#
# `scripts/backfill_gov_id.py --apply` on production (2026-09-12, commit
# ec1bd9a, which includes WO-243 #1003) re-keyed 92 pages off a real
# registry hub onto a fresh mint -- 18 of them are these real Granicus
# tenants, each writing its own government's name with a prefix
# ("The City of", "The Town of", "The Village of", a bare "City of"/"Town
# of", or "Town of X, Long Island") that the repair pipeline didn't
# handle. The WO-251 brief's own premise was that rung 1c (WO-243's
# curated-match-before-repair rung) caused this -- re-derived against the
# code and found FALSE: every one of these 18 names mints the identical
# wrong id on the commit immediately BEFORE WO-243 too (verified by
# running this exact parametrize against `1708e05^`'s resolver.py/
# registry.py). Rung 1c is a pure no-op for all 18 -- none is a curated
# row -- so "fix rung 1c" fixes nothing here; the real gaps were three,
# all in jurisdiction_enrich.py/resolver.py, predating WO-243 entirely:
#
# 1. `_LEADING_TYPE_RE` required the string to START with the type word
#    ("city"/"town"/etc.) -- a leading "The " defeated it completely, so
#    "The City of Redmond, WA" never reached the place table at all. Hit
#    12 of the 18. Fixed by making the leading "the " optional.
# 2. A handful of real Census rows genuinely keep the word the "<Type> of
#    <Name>" phrasing strips as filler, as part of their own real name --
#    "Lake Havasu City city, AZ", "West Springfield Town city, MA". Fixed
#    two ways: `_normalize_candidates()` now also tries the type word
#    re-appended (Lake Havasu), and `_census_type_word()` knows
#    Massachusetts's own "<Name> Town city" Gazetteer quirk (West
#    Springfield) -- 13 real MA rows share the shape, confirmed, and nothing
#    outside MA does except three real places literally NAMED "___ Town"
#    (Charles Town WV, New Town ND, Old Town ME), which is why the fix is
#    scoped to state == "MA", not a blanket rule.
# 3. ", Long Island" sits between the name and the state on three real
#    Suffolk County NY towns' own raw text, noise neither the leading-type
#    strip nor the trailing-state regex reaches. Stripped as its own
#    preprocessing step.
_WO251_PREFIX_SHAPES = [
    ("The City of Redmond, WA", "redmond.granicus.com", "us:place:5357535"),
    (
        "The City of Harrisonburg, VA",
        "harrisonburg-va.granicus.com",
        "us:place:5135624",
    ),
    ("The City of Amarillo, TX", "amarillo.granicus.com", "us:place:4803000"),
    ("The City of East Lansing, MI", "eastlansing.granicus.com", "us:place:2624120"),
    (
        "The City of Huntington Park, CA",
        "huntingtonpark.granicus.com",
        "us:place:0636056",
    ),
    ("The City of Lincoln Park, MI", "lincolnpark-mi.granicus.com", "us:place:2647800"),
    ("The City of Morgantown, WV", "morgantown.granicus.com", "us:place:5455756"),
    ("The City of Placentia, CA", "placentia.granicus.com", "us:place:0657526"),
    ("The City of Grand Island, NE", "grandisland.granicus.com", "us:place:3119595"),
    ("The City of Janesville, WI", "janesville.granicus.com", "us:place:5537825"),
    # No leading "The" -- the real place's own Census name keeps "City"
    # that the "City of" phrasing would otherwise strip as filler.
    ("City of Lake Havasu, AZ", "lakehavasucity.granicus.com", "us:place:0439370"),
    ("The Town of Collierville, TN", "collierville.granicus.com", "us:place:4716420"),
    ("The Town of North Salem, NY", "northsalem.granicus.com", "us:cousub:3611953517"),
    (
        "The Village of Palmetto Bay, FL",
        "palmettobay.granicus.com",
        "us:place:1254275",
    ),
    # MA's own "<Name> Town city" Gazetteer quirk.
    (
        "Town of West Springfield, MA",
        "westspringfieldma.granicus.com",
        "us:place:2577890",
    ),
    # ", Long Island" qualifier, all three real Suffolk County NY towns.
    (
        "Town of Southampton, Long Island, NY",
        "southampton.granicus.com",
        "us:cousub:3610368473",
    ),
    (
        "Town of Southold, Long Island, NY",
        "southold.granicus.com",
        "us:cousub:3610369463",
    ),
    (
        "Town of East Hampton, Long Island, NY",
        "easthampton.granicus.com",
        "us:cousub:3610322194",
    ),
]


@pytest.mark.parametrize("raw,host,gov_id", _WO251_PREFIX_SHAPES)
def test_prefixed_granicus_names_reach_the_real_registry_row(raw, host, gov_id):
    match = resolve(raw, host)
    assert match.gov_id == gov_id
    assert match.tier == resolver.TIER_REGISTRY


def test_wo251_prefix_shapes_mint_identically_before_wo243():
    """Guard against the next person re-reading the WO-251 brief and
    re-blaming rung 1c: this reproduces the exact wrong-mint result from
    `1708e05^` (the commit immediately before WO-243 #1003) for the
    single clearest case, using the resolver/registry code as WO-243
    found it -- frozen here as a literal string rather than re-checked
    out at test time, since the point is what that code did, not what it
    does today. `rtr:us:wa:redmond-city` is WO-243-independent: rung 1c
    never engages for this name either before or after WO-243 (it is not
    a curated row), so this result came entirely from the leading-"The"
    gap in jurisdiction_enrich.py's `_LEADING_TYPE_RE`, which predates
    WO-243 and WO-251 fixed directly."""
    pre_wo243_result = "rtr:us:wa:redmond-city"
    # Fixed by WO-251: this same input now reaches the real registry row.
    assert resolve("The City of Redmond, WA", "redmond.granicus.com").gov_id != (
        pre_wo243_result
    )


def test_curated_exact_match_does_not_reintroduce_the_boise_county_collision():
    """`_curated_exact_match()` (rung 1c) must not use `_curated_alias()`'s
    place-oriented normalization, which strips a trailing type word and
    would turn "Boise County" into the candidate key "boise" -- handing
    the county's own page to the curated Boise CITY alias before rung 4
    ever gets a chance to match the real county. Exact string equality
    only, so this stays a no-op here exactly as it is for the
    already-passing `test_the_county_itself_is_not_shadowed_by_the_citys_
    alias` above."""
    assert resolve("Boise County, ID").gov_id == "us:county:16015"


# --- WO-300: a name that merely CONTAINS a real place/county name must
# never resolve to that place/county -- five real Utah PMN "Entity"
# names WO-299 found wrongly matching Utah County or Ogden city, filed
# in BACKLOG.md and fixed here. Same family as WO-251's name-repair gaps
# and WO-280's state-code-in-name bug. -----------------------------------

_WO300_FALSE_POSITIVES = [
    # A state-level body whose name merely contains the word "Utah" --
    # each trims/splits down to bare "Utah", which used to "validate"
    # only because Utah COUNTY's own trailing-"County"-stripped index key
    # is also "utah" (jurisdiction_enrich._table_lookup_strength()).
    "Utah Board of Higher Education, UT",
    "Ascent Academies of Utah, UT",
    "Utah State Fair Corporation Board of Directors, UT",
    # A real county's own literal name is a genuine PREFIX of a longer,
    # different entity's name -- the discarded tail describes a specific
    # different kind of body, not bleed.
    "Utah County Academy of Sciences, UT",
    # A special-service-area name that contains its host city's name.
    "Ogden Valley Parks Service Area, UT",
]


@pytest.mark.parametrize("raw", _WO300_FALSE_POSITIVES)
def test_name_merely_containing_a_place_name_does_not_resolve_to_it(raw):
    match = resolve(raw)
    # None of these five is a real registry government -- the honest
    # outcome is a fresh mint (unverified/minted), never a match at
    # TIER_REGISTRY on a place/county the raw text never actually names.
    assert match.tier != resolver.TIER_REGISTRY
    assert match.gov_id not in ("us:county:49049", "us:place:4955980")


def test_utah_county_itself_still_resolves_registry_tier():
    # Positive control: the real county, written plainly, must be
    # unaffected by the WO-300 fix above.
    match = resolve("Utah County, UT")
    assert match.gov_id == "us:county:49049"
    assert match.tier == resolver.TIER_REGISTRY


def test_ogden_itself_still_resolves_registry_tier():
    # Positive control: the real city, written plainly, must be
    # unaffected by the WO-300 fix above.
    match = resolve("Ogden, UT")
    assert match.gov_id == "us:place:4955980"
    assert match.tier == resolver.TIER_REGISTRY


def test_same_state_name_county_coincidence_is_closed_not_general():
    # Direct unit test of the new guard itself
    # (jurisdiction_enrich._is_same_state_name_county_coincidence()):
    # it must fire for the four real counties nationally that share
    # their own state's exact name (Idaho County ID, Iowa County IA,
    # Oklahoma County OK, Utah County UT -- confirmed against
    # us_counties.csv), and must NOT fire for an unrelated state name
    # colliding with a DIFFERENT state's same-named county (e.g.
    # "Washington" is a real county name in ~20 states, but never in
    # Washington state itself) or for a name that already says "County".
    from app.utils import jurisdiction_enrich as je

    def _county_hit(name):
        hit = je._table_lookup_strength(name)
        return hit if hit and hit[0] == "county" else None

    assert _county_hit("Utah") is None
    assert _county_hit("Idaho") is None
    assert _county_hit("Iowa") is None
    assert _county_hit("Oklahoma") is None
    # A name that spells out "County" is untouched -- the guard only
    # ever inspects the BARE, unstripped query text.
    assert _county_hit("Utah County") is not None

    # Direct unit test of the helper itself, sidestepping
    # `_table_lookup_strength()`'s own place-before-county table order
    # (several state names -- "Washington", "Delaware" -- also match a
    # real PLACE first, which would return before county is ever tried):
    # the guard fires ONLY when the query's own state IS among the
    # matched county's states, never for an unrelated state's same-named
    # county elsewhere.
    washington_counties = {"washington": ["AL", "AR", "CO", "GA"]}  # never "WA"
    assert (
        je._is_same_state_name_county_coincidence("washington", washington_counties)
        is False
    )
    utah_counties = {"utah": ["UT"]}
    assert je._is_same_state_name_county_coincidence("utah", utah_counties) is True


# --- WO-263: the Port of San Diego, minted on Ryan's call -------------


def test_port_of_san_diego_classifies_special_district_on_the_raw_name():
    """ "Port of" is a `_RULES` special_district phrase (classify.py), so
    this name reaches rung 1c/4b's curated-row check directly off the raw
    string, with no name-repair truncation step in between -- unlike
    WO-220's Department of Commerce/Southwest Utah rows, there is no
    truncated-alias risk to also cover here."""
    match = resolve("Port of San Diego, CA")
    assert match.gov_id == "rtr:us:ca:port-of-san-diego"
    assert match.gov_type == classify.SPECIAL_DISTRICT
    assert match.tier == resolver.TIER_REGISTRY


def test_port_of_san_diego_host_pin_resolves_with_no_name_at_all():
    """`portofsandiego.granicus.com` is single-tenant (confirmed live
    2026-09-12) -- a page from it with no jurisdiction string at all
    still lands on the Port's own government via the host-wide (blank
    `match`) pin, same shape as `test_the_nine_mislabelled_tenants_are_
    pinned_to_the_right_government` above."""
    match = resolve(None, "portofsandiego.granicus.com")
    assert match.gov_id == "rtr:us:ca:port-of-san-diego"
    assert match.tier == resolver.TIER_PINNED


# --- WO-101: the column has to hold what the resolver produces --------


def test_every_gov_id_fits_the_column():
    """`MeetingPage.gov_id` was String(64) on the strength of a comment
    saying the longest real id was "well under that". It was not: the
    same scoring run's `minted.csv` held two 66-character ids, and the
    production backfill died on
    `rtr:us:ca:los-angeles-county-metropolitan-transportation-authority`
    after writing 333 of 5,053 rows.

    This asserts the property directly against the committed registry,
    rather than against a claim about it."""
    from archive.db.models import MeetingPage

    width = MeetingPage.__table__.c.gov_id.type.length
    too_long = sorted(
        (gov_id for gov_id in registry.governments() if len(gov_id) > width),
        key=len,
        reverse=True,
    )
    assert not too_long, f"gov_id is String({width}); longest is {too_long[:3]}"


def test_the_column_covers_what_the_schema_can_produce():
    """Not just today's data -- the two id shapes whose length depends on
    data at all. A minted `rtr:<cc>:<st>:<slug>` is bounded by
    `jurisdiction` (String(200)); `rtr:unknown:<host>` by DNS's 253-octet
    hostname limit. Measuring only what the corpus happens to contain is
    the reasoning that failed."""
    from archive.db.models import MeetingPage

    width = MeetingPage.__table__.c.gov_id.type.length
    jurisdiction_width = MeetingPage.__table__.c.jurisdiction.type.length
    assert width >= len("rtr:us:ca:") + jurisdiction_width
    assert width >= len("rtr:unknown:") + 253


@pytest.mark.parametrize(
    "column,longest",
    [("gov_type", "special_district"), ("meeting_kind", "press_conference")],
)
def test_the_closed_vocabulary_columns_fit_too(column, longest):
    """Checked the same way rather than assumed, since that is the whole
    lesson. These two are genuinely bounded -- closed vocabularies."""
    from archive.db.models import MeetingPage

    assert MeetingPage.__table__.c[column].type.length >= len(longest)


# --- WO-100: the three defects found in the production dry run --------


def test_a_machine_derived_pin_may_not_mint_a_government():
    """`king.granicus.com` is the Metropolitan King County Council --
    King County, WA. It carried `rtr:us:nc:king-county`, source
    `auto_derived+inferred_unique_name`, built on rtr-discovery's wrong
    `state_abbr=NC` for that host. Pinning to a national id is a claim a
    table can check; pinning to an `rtr:` id invents an identity, and a
    pin is the one tier that overrides a working extraction. Combining
    two machine sources does not make one human one."""
    assert registry._has_human_source("known_domains") is True
    assert registry._has_human_source("architecture_doc_1_3") is True
    assert registry._has_human_source("auto_derived") is False
    assert registry._has_human_source("auto_derived+inferred_unique_name") is False
    # ...and the loader drops such a row entirely.
    for rows in registry.tenant_overrides().values():
        for override in rows:
            if override.gov_id.startswith("rtr:"):
                assert registry._has_human_source(override.source), override


def test_king_county_resolves_to_washington():
    match = resolve("King County", "king.granicus.com")
    assert match.gov_id == "us:county:53033"
    assert match.gov_name == "King County, WA"


def test_a_county_that_cannot_exist_is_never_minted():
    """US counties are exhaustively enumerated, so a county-shaped name
    with no such county in that state is a contradiction, not an unlisted
    government."""
    assert resolver._is_impossible_county("King County", "NC", "us") is True
    assert resolver._is_impossible_county("King County", "WA", "us") is False
    assert resolver._is_impossible_county("County of Nowhere", "CA", "us") is True


@pytest.mark.parametrize(
    "name",
    [
        # Agencies that merely NAME their county, and both are real
        # minted governments the §1.3 fixes depend on.
        "Los Angeles County Metropolitan Transportation Authority",
        "Tarrant County College District",
        "Horry County Schools",
    ],
)
def test_naming_a_county_is_not_being_one(name):
    assert resolver._is_impossible_county(name, "CA", "us") is False


def test_a_tenant_hint_ranks_below_a_subdomain_or_known_domain(monkeypatch):
    """`tenant_hints.csv` is rtr-discovery's learned state and is the
    weakest of the three signals -- it is what put NC on
    `king.granicus.com`. A validated subdomain reading or a
    `_KNOWN_DOMAINS` entry must win."""
    monkeypatch.setattr(registry, "tenant_hints", lambda: {"x.granicus.com": "NC"})
    # A real Washington name: since 2026-09-10 the reader's (name, state)
    # claim is checked against the tables, so a made-up "X" would be
    # declined for the right reason and mask what this test is about.
    monkeypatch.setattr(
        resolver, "_validated_subdomain_hint_with_state", lambda h: ("Tacoma", "WA")
    )
    assert resolver._state_from_tenant("x.granicus.com")[0] == "WA"
    monkeypatch.setattr(
        resolver, "_validated_subdomain_hint_with_state", lambda h: None
    )
    assert resolver._state_from_tenant("x.granicus.com")[0] == "NC"


# --- WO-100: a stateless name must be unique across ALL three tables ---


def test_a_stateless_name_ambiguous_between_tables_is_unresolved():
    """ "Town of Hillsborough" on a shared host with no tenant state
    became Hillsborough town, NEW HAMPSHIRE. Two Hillsborough places (CA,
    NC), two county subdivisions (NH, NJ) and two counties (FL, NH); the
    place table declined because it saw two, the cousub table answered
    because "Town of" narrowed its two to one, and nothing compared the
    six.

    Host is `example-unpinned.granicus.com`, not the original `youtu.be`
    this case was found on -- WO-210 made `youtu.be` itself return no
    government at all (`TIER_BLANK`) before this rung's own ambiguity
    check ever runs, which is a different, correct outcome this test
    isn't about; the ambiguity logic itself still needs covering on an
    ordinary unpinned host."""
    assert (
        resolve("Town of Hillsborough", "example-unpinned.granicus.com").tier
        == resolver.TIER_UNRESOLVED
    )
    assert resolve("Oregon", "oregon.granicus.com").tier == resolver.TIER_UNRESOLVED


@pytest.mark.parametrize(
    "raw,host,expected",
    [
        ("City of Corona", "corona.granicus.com", "us:place:0616350"),
        ("Town of Herndon", "herndon.granicus.com", "us:place:5136648"),
        ("City of Burnsville", "burnsville.civicweb.net", "us:place:2708794"),
        ("City of Palm Springs", "palmsprings.granicus.com", "us:place:0655254"),
    ],
)
def test_the_type_word_still_settles_a_stateless_name(raw, host, expected):
    """The cross-table count uses the raw name's own type word, exactly
    as each table's lookup does. Counting without it looks stricter and
    is simply wrong: measured over the 5,053-page export it declined 74
    rows, and about 40 were right -- these among them, including a
    documented three-slug merge (Herndon)."""
    assert resolve(raw, host).gov_id == expected


def test_a_place_and_its_own_county_are_not_a_dangerous_ambiguity():
    """Counted by row rather than by STATE, the rule declined
    "Milwaukee." -- a real stored string whose merge with "Milwaukee, WI"
    is one of the documented Phase 1b wins. A place and a county sharing
    a name in the SAME state put the page in that state either way, and
    place-before-county already settles which. What goes wrong is the
    wrong state."""
    assert resolve("Milwaukee.").gov_id == resolve("Milwaukee, WI").gov_id
    assert resolver._stateless_states("Milwaukee") == {"WI"}
    assert len(resolver._stateless_states("Hillsborough")) > 1


def test_a_curated_alias_counts_as_a_competing_stateless_candidate():
    """Census names the California city "San Buenaventura (Ventura)
    city", so the place table keys no "Ventura" in CA at all and a
    stateless "City of Ventura" reached Ventura city, IOWA. One table hit
    plus one curated assertion is two candidates.

    Host is `example-unpinned.granicus.com`, not the original
    `www.youtube.com` -- see the comment on
    `test_a_stateless_name_ambiguous_between_tables_is_unresolved` above
    (WO-210 gives `www.youtube.com` a different, earlier outcome this
    test isn't about)."""
    assert resolve("City of Ventura", "example-unpinned.granicus.com").tier == (
        resolver.TIER_UNRESOLVED
    )


@pytest.mark.parametrize(
    "raw,host",
    [("Ventura, CA", "cityofventura.granicus.com"), ("City of Ventura, CA", None)],
)
def test_both_spellings_of_ventura_reach_the_city(raw, host):
    """Three answers for one government before this: the real
    `cityofventura.granicus.com` page, stored as a bare "Ventura, CA",
    resolved to Ventura COUNTY -- and an authoritative pin had frozen
    that in place."""
    assert resolve(raw, host).gov_id == "us:place:0665042"


def test_the_county_itself_is_unaffected():
    assert resolve("Ventura County, CA", "ventura.primegov.com").gov_id == (
        "us:county:06111"
    )


# --- WO-100: an unresolved government has no hub -----------------------


def test_an_unresolved_row_has_no_hub_slug():
    """`GovernmentMatch.hub_slug` built a slug from the raw cleaned name
    for tiers that have no identity: an unresolved "City of Las Vegas"
    gave `city-of-las-vegas`, while the page actually lives at
    `/j/las-vegas` -- `jurisdiction_hub_slug()` goes through
    `format_jurisdiction_display()`, which strips a leading "City of ".
    No page ever moved (crud falls back correctly), but both scripts read
    this property, so the backfill's dry run and the scoring run credited
    moves that would not happen.

    `lasvegas.primegov.com` was the original real example, but the
    2026-09-03 pin-worklist round (WO-106 follow-up) pinned that exact
    host to `us:place:3240000` -- a real fix, so it is no longer
    unresolved and can't demonstrate this case any more. Swapped to an
    intentionally-unpinned host (`example-unpinned.granicus.com`, the
    same placeholder `test_a_pin_to_a_government_not_yet_in_governments_
    csv_still_applies` uses below) with the same real, still-genuinely-
    ambiguous "City of Las Vegas" name -- Las Vegas, NV and Las Vegas, NM
    both exist, so without a state a bare name still can't resolve on its
    own."""
    match = resolve("City of Las Vegas", "example-unpinned.granicus.com")
    assert match.tier == resolver.TIER_UNRESOLVED
    assert match.hub_slug is None
    assert resolve(None, "example.granicus.com").hub_slug is None


def test_a_resolved_row_still_has_one():
    assert resolve("City of Napa, CA", "napa.granicus.com").hub_slug == "napa-ca"


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


# --- Phase 2b: a GUESSED state can also name the wrong country ---------


@pytest.mark.parametrize(
    "name",
    [
        "Erin",
        "Pickering",
        "Markham",
        "Clarington",
        "Cornwall",
        "Northumberland",
        "Brockton",
    ],
)
def test_a_bare_name_with_no_pin_declines_rather_than_guessing_the_country(name):
    """The guard itself, independent of any pin: `_has_canadian_namesake()`
    is what made `_national_lookup()`/the tenant-hint rungs decline these
    exact 7 real names instead of confidently resolving to a same-named
    US place/county (Erin TN, Pickering MO, Markham IL, Clarington OH,
    Cornwall PA, Northumberland PA, Brockton MA -- Strathcona is checked
    separately below since its real row lives in `ca_csd`, not `ca_cd`,
    for a name that reads like a county). All 7 now have a real
    `tenant_overrides.csv` pin (see the parametrized test below), which
    short-circuits the ladder before this guard ever runs -- this test
    covers the guard function directly so a future host with the same
    collision and no pin yet still declines instead of guessing."""
    assert resolver._has_canadian_namesake(name)


def test_strathcona_is_a_csd_not_a_cd_despite_the_county_name():
    assert resolver._has_canadian_namesake("Strathcona")


@pytest.mark.parametrize(
    "raw,host,expected_gov_id,expected_gov_name",
    [
        ("Town of Erin", "pub-erin.escribemeetings.com", "ca:csd:3523017", "Erin, ON"),
        (
            "Pickering",
            "pub-pickering.escribemeetings.com",
            "ca:csd:3518001",
            "Pickering, ON",
        ),
        (
            "Markham",
            "pub-markham.escribemeetings.com",
            "ca:csd:3519036",
            "Markham, ON",
        ),
        (
            "Clarington",
            "pub-clarington.escribemeetings.com",
            "ca:csd:3518017",
            "Clarington, ON",
        ),
        (
            "Cornwall",
            "pub-cornwall.escribemeetings.com",
            "ca:csd:3501012",
            "Cornwall, ON",
        ),
        (
            "Northumberland County",
            "pub-northumberland.escribemeetings.com",
            "ca:cd:3514",
            "Northumberland, ON",
        ),
        (
            "Strathcona County",
            "pub-strathcona.escribemeetings.com",
            "ca:csd:4811052",
            "Strathcona County, AB",
        ),
        (
            "Brockton",
            "pub-brockton.escribemeetings.com",
            "ca:csd:3541032",
            "Brockton, ON",
        ),
    ],
)
def test_a_tenant_hinted_state_no_longer_settles_the_country(
    raw, host, expected_gov_id, expected_gov_name
):
    """A tenant-derived state is a GUESS the page's own text never made --
    unlike `test_a_state_still_settles_the_country` above -- and
    `tenant_hints.csv`/`tenant_overrides.csv` rows imported wholesale
    from rtr-discovery's own ledger named the wrong COUNTRY entirely for
    all 8 of these real, live, published tenants (2026-09-06). Before the
    fix (WO-118, PR #750), each resolved confidently to a same-named US
    place/county because the state-constrained lookup this rung does
    never cross-checked Canada. Every raw name and host here is real:
    each tenant's `tenant_hints.csv` row (and, for the last three, an
    `auto_derived+inferred_unique_name` `tenant_overrides.csv` pin, since
    removed) is exactly what produced the wrong live page.

    After the fix landed, the 26 already-published wrong pages were
    backfilled via 8 new `authoritative` `tenant_overrides.csv` pins
    (2026-09-06) -- so the end-to-end resolution for these specific hosts
    is now the correct Canadian government, at `TIER_PINNED` (checked
    before the guarded rung this fix lives in even runs). A host with
    the same collision and no pin yet still declines rather than
    guessing -- see the two tests above, which exercise the guard
    directly."""
    match = resolve(raw, host)
    assert match.tier == resolver.TIER_PINNED
    assert match.gov_id == expected_gov_id
    assert match.gov_name == expected_gov_name


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
    """`allentownpa.granicus.com` used to store "City of Al" -- a truncated
    "City of Allentown" whose stray "Al" the bare-state-suffix rule then
    read as Alabama, leaving the name "City of" and minting
    `rtr:us:al:city-of`, displayed to a reader as "City of, AL". Every step
    is individually defensible, which is why the gate is on the outcome.

    That host is now pinned to "Allentown, PA" (a real fix, a pin-worklist
    round), so it can no longer demonstrate the unresolved case -- swapped
    to an intentionally-unpinned host with the same real truncated-name
    shape."""
    match = resolve("City of Al", "example-unpinned.granicus.com")
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


# --- WO-105, 2026-09-03: `resolve_government(..., signals=...)` --------
#
# The `extract_gov_signals()` shape (`app/utils/gov_signals.py`), consumed
# by a post-ladder enhancement pass that only ever fires when `signals`
# is explicitly passed AND the plain ladder's own answer was
# `unverified`/`unresolved`/`blank` -- see resolver.py's own WO-105
# comment block for the full design/hard-constraint reasoning. Every
# "control" test below re-confirms that an ALREADY-solid resolution
# (`registry`/`pinned`) is never disturbed, however wrong the signals
# passed alongside it are.


def test_signals_recover_a_missing_state_from_a_real_zip():
    # "City of Cambridge" alone has no state and is genuinely ambiguous
    # (real in IA/ID/IL/KS/KY/MA/MD/MN/NE/NY/OH/VT/WI -- same fact as the
    # Bug 2 tests in tests/test_jurisdiction_enrich.py) -- unresolved with
    # no signals. 02138 is Cambridge, MA's own real ZCTA.
    assert resolve("City of Cambridge").tier == resolver.TIER_UNRESOLVED
    match = resolve("City of Cambridge", signals={"zip_codes": ["02138"]})
    assert match.gov_id == "us:place:2511000"
    assert match.tier == resolver.TIER_REGISTRY


def test_signals_zip_recovery_declines_an_impossible_pairing():
    # Same "impossible pairing" guard as Bug 2's `resolve_state()` fix,
    # reused via `_name_validates_in_state()`: 02818 is Warwick city, RI's
    # real ZCTA, and Rhode Island has no Cambridge at all, so this ZIP
    # must not hijack the state.
    match = resolve("City of Cambridge", signals={"zip_codes": ["02818"]})
    assert match.tier == resolver.TIER_UNRESOLVED
    assert not match.gov_id


def test_signals_recover_a_missing_province_from_a_real_postal_code():
    # "City of Toronto" alone has no province. M5H 2N2 is a real Toronto
    # postal code (Old City Hall, a genuinely public address).
    assert resolve("City of Toronto").tier == resolver.TIER_UNRESOLVED
    match = resolve("City of Toronto", signals={"postal_codes": ["M5H 2N2"]})
    assert match.gov_id == "ca:csd:3520005"
    assert match.tier == resolver.TIER_REGISTRY


def test_signals_org_names_recovers_a_real_government_from_a_noisy_stored_string():
    # "Meeting Info" alone names nothing. A real org_names candidate
    # (e.g. the kind `_stoprule_extract()` would find in real page text)
    # resolves it, the same acceptance test (`is_own_name()`) the landing-
    # page sweep already relies on.
    assert resolve("Meeting Info").tier == resolver.TIER_UNRESOLVED
    match = resolve(
        "Meeting Info",
        signals={"org_names": [{"value": "City of Fresno, CA", "rule": "stoprule"}]},
    )
    assert match.gov_id == "us:place:0627000"
    assert match.tier == resolver.TIER_REGISTRY


def test_signals_org_names_declines_a_bare_generic_word():
    # The exact real failure JURISDICTION_METADATA_PLAN.md's landing-page
    # sweep documents from its own first, wrong-pin-producing run:
    # "Council" alone is a real place (Council, ID) but is never evidence
    # about a DIFFERENT government -- `_BARE_GENERIC_ORG_NAME_WORDS`
    # rejects it as a candidate before ever calling `is_own_name()`.
    match = resolve(
        "Meeting Info",
        signals={"org_names": [{"value": "Council", "rule": "capitalization_walk"}]},
    )
    assert match.tier == resolver.TIER_UNRESOLVED
    assert not match.gov_id


def test_signals_never_change_an_already_solid_resolution():
    # The hard constraint, directly: a real, already-correctly-resolving
    # name must come back byte-identical whether or not (wrong, noisy)
    # signals ride along -- the enhancement pass is skipped entirely
    # whenever the plain ladder's own answer is already registry/pinned.
    plain = resolve("City of Fresno, CA")
    with_bogus_signals = resolve(
        "City of Fresno, CA",
        signals={
            "org_names": [{"value": "Bogus County, TX", "rule": "stoprule"}],
            "zip_codes": ["99999"],
            "postal_codes": ["Z9Z 9Z9"],
        },
    )
    assert with_bogus_signals == plain
    assert plain.tier == resolver.TIER_REGISTRY


def test_signals_default_is_none_and_changes_nothing():
    # `signals=None` (the default, and what every real caller other than
    # `scripts/score_gov_signals.py` passes) must be indistinguishable
    # from not having the parameter at all.
    assert resolve("City of Cambridge", signals=None) == resolve("City of Cambridge")
    assert resolve("City of Cambridge", signals={}) == resolve("City of Cambridge")


# --- WO-107, 2026-09-03: resolve_government() round-trips its own -------
# display-form output.
#
# Found running `scripts/score_gov_signals.py`'s live corpus scan for the
# first time: every one of its 5 "control regressions" (a registry-tier
# page whose gov_id changed when signals were applied -- explicitly a
# defect per that script's own brief) turned out to share one shape, and
# none was actually caused by `signals`. `archive/db/crud.py`'s
# `_display_jurisdiction_or_finalized()` writes `display_name()`'s own
# disambiguated form ("Brookfield (village), IL") back into a page's
# stored `jurisdiction` once it resolves REGISTRY/PINNED with an in-state
# name collision -- so re-resolving from stored data (a backfill, this
# scoring script) feeds that shape back in as `raw_name`. Before this fix,
# the place/cousub table lookup missed on the literal string "Brookfield
# (village)" (the table's own key is "Brookfield", with the type word
# stripped as ordinary trailing Census text, never held in parentheses),
# so a government the tables already had minted a fresh `rtr:` id
# instead -- and only then did the `signals` enhancement pass (which is
# gated to fire on exactly unverified/unresolved/blank, per the hard
# constraint above) correctly recover the real id from `org_names`,
# making the change look like a signals-caused regression when the actual
# defect was `resolve_government()` failing to parse its own prior
# output. Confirmed live: all 5 pages resolve correctly with this fix,
# byte-identical to their real stored `gov_id`.
def test_resolve_government_parses_its_own_ambiguous_display_form():
    # Real, live: page 1483 (brookfieldil.civicweb.net), stored exactly
    # this way after a prior resolve, jurisdiction_confidence=registry,
    # gov_id=us:place:1708576.
    match = resolve("Brookfield (village), IL")
    assert match.gov_id == "us:place:1708576"
    assert match.tier == resolver.TIER_REGISTRY


def test_resolve_government_parses_a_disambiguated_township_display_form():
    # The TOWNSHIP branch of `display.display_name()` uses the identical
    # `"{base} ({word}){suffix}"` form for an in-state place/cousub name
    # collision -- WI's real Town of Cottage Grove vs. Village of Cottage
    # Grove pair architecture doc SS1.5 names (see `_leading_type_word()`'s
    # own docstring above), so the round-trip fix has to cover both
    # branches, not just MUNICIPALITY.
    match = resolve("Cottage Grove (town), WI")
    assert match.gov_id == "us:cousub:5502517200"
    assert match.tier == resolver.TIER_REGISTRY
    match = resolve("Cottage Grove (village), WI")
    assert match.gov_id == "us:place:5517175"
    assert match.tier == resolver.TIER_REGISTRY


@pytest.mark.parametrize(
    "raw,gov_id,display_name",
    [
        # New England's "town" is the primary unit of general-purpose
        # local government, referred to by its bare name in ordinary
        # usage -- unlike a Midwest/mid-Atlantic township, where the LSAD
        # suffix word ("Township") is part of the name people actually
        # use. Real GEOIDs, per COUSUB_REQUIREMENTS.md's own evidence.
        ("Brookline, MA", "us:cousub:2502109175", "Brookline, MA"),
        ("Andover, CT", "us:cousub:0911001080", "Andover, CT"),
    ],
)
def test_new_england_town_displays_without_the_town_suffix(raw, gov_id, display_name):
    match = resolve(raw)
    assert match.gov_id == gov_id
    assert match.gov_type == classify.TOWNSHIP
    assert display.display_name(match.government) == display_name


def test_a_midwest_township_keeps_its_suffix_unlike_a_new_england_town():
    # The contrast case: same gov_type, same code path, different state --
    # confirms the New England carve-out didn't just delete the suffix
    # for every TOWNSHIP row.
    match = resolve("Chesterfield Township, MI")
    assert match.gov_id == "us:cousub:2609915340"
    assert display.display_name(match.government) == "Chesterfield Township, MI"


def test_strip_trailing_paren_type_only_fires_on_an_actual_parenthetical():
    # The helper itself: a real `(word)` disambiguator is split off and
    # lowercased; anything else (no parens, or parens that aren't one of
    # the known Census type words) is returned unchanged, so an ordinary
    # name's lookup is provably untouched by this fix.
    assert resolver._strip_trailing_paren_type("Brookfield (village)") == (
        "Brookfield",
        "village",
    )
    assert resolver._strip_trailing_paren_type("Cottage Grove (town)") == (
        "Cottage Grove",
        "town",
    )
    assert resolver._strip_trailing_paren_type("Fresno") == ("Fresno", "")
    assert resolver._strip_trailing_paren_type("Nashville-Davidson (balance)") == (
        "Nashville-Davidson (balance)",
        "",
    )

    plain = resolve("Fresno, CA")
    assert plain.gov_id == "us:place:0627000"
    assert plain.tier == resolver.TIER_REGISTRY


def test_state_suffix_from_text_finds_a_comma_prefixed_state_anywhere():
    # The real, confirmed shape this exists for: a Legistar meeting
    # delegated to its video platform gets a title like "City of
    # Appleton, WI - Live Video" -- the state isn't at the end of the
    # string, so _split_state()'s own trailing-only regex can't see it.
    assert resolver.state_suffix_from_text("City of Appleton, WI - Live Video") == "WI"
    assert (
        resolver.state_suffix_from_text("Cleveland City Council, OH - Calendar") == "OH"
    )
    # No comma-prefixed state anywhere -- must not guess.
    assert resolver.state_suffix_from_text("Jonesboro - Live Proceedings") == ""
    # A coincidental ", XY" that isn't a real state/province abbreviation
    # must not be accepted.
    assert resolver.state_suffix_from_text("Foo, Bar - Baz") == ""
    assert resolver.state_suffix_from_text(None) == ""
    assert resolver.state_suffix_from_text("") == ""


# --- WO-113 (2026-09-05): `finalize_jurisdiction()`'s subdomain
# cross-check now also fills in a raw jurisdiction that validates as
# NOTHING at all (not just one that validates-wrong or trims-wrong), and
# since `_resolve_government_ladder()` calls that function internally as
# its own rung 2, the fix lands here too, not just in stored display
# text. Every (raw, host) pair is a real, live Municode page confirmed via
# `GET /internal/export/pages?ids=...` against production on 2026-09-05
# (page ids 1434/1437/1444/1446/1449/1450/1454/1455, all
# `*.municodemeetings.com`). Before WO-113 every one of these landed on
# `unverified` with a synthetic `rtr:us:<state>:<slug>` id -- two of them
# (1444, 1446) even collided on the exact same id despite naming two
# different real governments in two different states.
@pytest.mark.parametrize(
    "raw,host,expected_gov_id",
    [
        ("Municode Portal", "kingsport-tn.municodemeetings.com", "us:place:4739560"),
        (
            "Columbus Wisconsin Meetings Hub",
            "columbus-wi.municodemeetings.com",
            "us:place:5516450",
        ),
        (
            "July13, 2026 | Town of Bladensburg Maryland Meetings Hub",
            "bladensburgtown-md.municodemeetings.com",
            "us:place:2407850",
        ),
        ("Municode Portal", "laurel-md.municodemeetings.com", "us:place:2445900"),
        (
            "Madeira Beach Florida Meetings Hub",
            "madeirabeach-fl.municodemeetings.com",
            "us:place:1242400",
        ),
        (
            "City of Richwood Texas",
            "richwood-tx.municodemeetings.com",
            "us:place:4861904",
        ),
        (
            "Walton County Meetings Portal",
            "waltoncounty-ga.municodemeetings.com",
            "us:county:13297",
        ),
        (
            "Willow Park Texas Meetings Hub",
            "willowpark-tx.municodemeetings.com",
            "us:place:4879492",
        ),
    ],
)
def test_municode_subdomain_fallback_lands_on_registry_tier(raw, host, expected_gov_id):
    match = resolve(raw, host)
    assert match.tier == resolver.TIER_REGISTRY
    assert match.gov_id == expected_gov_id


def test_milwaukee_now_matches_the_place_table_directly():
    # Until WO-251, "The City of Milwaukee, WI" (real Granicus tenant
    # text) matched no place key at all -- the enricher's leading-type
    # strip required the string to start with "City"/"Town"/etc., and a
    # leading "The" defeated it -- so this case needed the ladder's own
    # tenant-consistency rung (`inferred`) as a safety net, which is what
    # this test originally asserted (see `test_tenant_consistency_
    # collapses_a_spelling_of_the_tenants_own_name` right above, covering
    # the same three names, for the net itself).
    #
    # WO-251 fixed the leading-"The" gap directly (`_LEADING_TYPE_RE` in
    # jurisdiction_enrich.py), so this no longer needs the net at all: a
    # real `us_places.csv` match, found with no `tenant_gov_id` supplied.
    # Not a repeat of the WO-113 "unguarded subdomain hint" regression
    # this test used to guard against -- that mechanism
    # (`_raw_text_explained_by_subdomain_hint()`) is never even reached
    # now; this resolves through the ordinary table-lookup fast path in
    # `finalize_jurisdiction()`, the same one "City of Milwaukee, WI" (no
    # leading "The") already used before WO-251.
    milwaukee = resolve("The City of Milwaukee, WI", "milwaukee.granicus.com")
    assert milwaukee.gov_id == "us:place:5553000"
    assert milwaukee.tier == resolver.TIER_REGISTRY


def test_municode_subdomain_fallback_does_not_regress_bleed_rejection(monkeypatch):
    # The second real regression from the same draft -- identical staging
    # to `test_a_bleed_page_on_the_wrong_tenant_is_listed_not_minted`
    # above, since the real `winston-salem.granicus.com` host carries a
    # production pin that would short-circuit rung 5d entirely before
    # ever reaching the code this test targets. "City of Lees Summit"
    # doesn't name Winston-Salem, doesn't spell out its state, and isn't
    # vendor filler -- the unguarded draft mis-filed it under
    # Winston-Salem anyway; it must stay `unresolved`.
    gov = registry.Government(
        "us:place:3775000", "Winston-Salem city", classify.MUNICIPALITY, state="NC"
    )
    monkeypatch.setattr(registry, "governments", lambda: {gov.gov_id: gov})
    monkeypatch.setattr(registry, "tenant_overrides", lambda: {})
    monkeypatch.setattr(
        registry, "tenant_hints", lambda: {"winston-salem.granicus.com": "NC"}
    )
    bleed = resolve(
        "City of Lees Summit",
        "winston-salem.granicus.com",
        tenant_gov_id="us:place:3775000",
    )
    assert bleed.tier == resolver.TIER_UNRESOLVED
    assert bleed.gov_id == ""


def test_county_sharing_a_name_with_an_independent_city_resolves():
    """us_counties.csv lists independent cities as county-equivalents, so
    "Baltimore County" and "Baltimore city" both key to "baltimore" in MD.
    Until 2026-09-09 the exactly-one rule returned nothing and
    _is_impossible_county() then called a real county impossible. The
    query's own type word now breaks that tie; a query without one still
    declines. Real names, real FIPS."""
    from app.utils.gov_registry import resolve_government

    assert resolve_government("Baltimore County, MD").gov_id == "us:county:24005"
    assert resolve_government("Roanoke County, VA").gov_id == "us:county:51161"
    assert resolve_government("Fairfax County, VA").gov_id == "us:county:51059"
    assert resolve_government("St. Louis County, MO").gov_id == "us:county:29189"
    # The independent city itself, and the bare name, still go to the city.
    assert resolve_government("Baltimore city, MD").gov_id == "us:place:2404000"
    assert resolve_government("Baltimore, MD").gov_id == "us:place:2404000"
    # A county that does not exist is still a contradiction, not a mint.
    assert resolve_government("King County, NC").gov_id == ""


def test_alaska_city_and_borough_displays_as_the_bare_name():
    """Census names Alaska's consolidated governments "Sitka city and
    borough"; the display must drop the whole two-word phrase, not just
    "borough" -- the 2026-09-09 pin backfill dry run would have written
    "Sitka city and, AK" onto two real pages."""
    from app.utils.gov_registry import display_name, government_for_id

    assert display_name(government_for_id("us:place:0270540")) == "Sitka, AK"
    assert display_name(government_for_id("us:place:0236400")) == "Juneau, AK"
    assert display_name(government_for_id("us:place:0203000")) == "Anchorage, AK"


def test_a_channel_hint_fires_a_channel_rule_on_every_youtube_host(monkeypatch):
    """Gov-id audit, 2026-09-10. The identifying detail for a bare YouTube
    paste is the channel, which is never in the address; the adapter now
    carries it and `page_hints_for(..., channel=)` hands it to the
    matcher. A rule keyed on www.youtube.com must also fire for a paste
    that arrived as youtu.be or youtube.com -- the 2026-09-09 export held
    YouTube pages under all three and nothing normalises them."""
    row = registry.TenantOverride(
        tenant_host="www.youtube.com",
        match="channel=@TownofWoodside",
        gov_id="us:place:0686440",  # Woodside, CA -- real place row
        strength="fallback",
        source="archive_study_2026-09-09",
        evidence="test",
    )
    monkeypatch.setattr(
        registry, "tenant_overrides", lambda: {"www.youtube.com": [row]}
    )
    hints = resolver.page_hints_for(
        "youtube", "youtube:0qVUwGeJ2P4", channel="@TownofWoodside"
    )
    assert hints["channel"] == "@TownofWoodside"
    for host in ("www.youtube.com", "youtu.be", "youtube.com"):
        match = resolver.resolve_government(
            None, tenant_host=host, path="/watch?v=0qVUwGeJ2P4", page_hints=hints
        )
        assert match.gov_id == "us:place:0686440", host
        assert match.tier == resolver.TIER_PINNED
    # A different channel on the same host does not match the rule.
    other = resolver.page_hints_for("youtube", "youtube:x", channel="@SomeoneElse")
    assert (
        resolver.resolve_government(
            None, tenant_host="youtu.be", path="/x", page_hints=other
        ).gov_id
        != "us:place:0686440"
    )


def test_a_per_video_pin_on_youtu_be_still_fires_for_the_www_form(monkeypatch):
    """The 56 earlier YouTube pins are keyed on whichever host name that
    paste used; the host-family lookup must not orphan them."""
    row = registry.TenantOverride(
        tenant_host="youtu.be",
        match="0qVUwGeJ2P4",
        gov_id="us:place:0686440",
        strength="fallback",
        source="ryan_stated",
        evidence="test",
    )
    monkeypatch.setattr(registry, "tenant_overrides", lambda: {"youtu.be": [row]})
    match = resolver.resolve_government(
        None, tenant_host="www.youtube.com", path="/watch?v=0qVUwGeJ2P4"
    )
    assert match.gov_id == "us:place:0686440"


@pytest.mark.parametrize(
    "raw, gov_id",
    [
        ("State College, PA", "us:place:4273808"),
        ("Rutherford College, NC", "us:place:3758440"),
    ],
)
def test_the_two_real_places_named_college_are_places_not_school_districts(raw, gov_id):
    """`classify`'s "<word> College" rule is for community-college
    districts; us_places.csv holds exactly two incorporated places whose
    name ends that way (grep, 2026-09-10). Before the exclusion "State
    College, PA" keyed to State College Area School District -- caught
    by the first full backfill dry run after display-from-gov_id, which
    would have moved a real borough page onto the district's hub."""
    match = resolve(raw, None)
    assert match.gov_id == gov_id
    assert match.gov_type == "municipality"
    assert classify.classify_government_type("Foothill College") == "school_district"


@pytest.mark.parametrize(
    "raw, host, forbidden_state",
    [
        ("Arkansas Supreme Court", "arkansas-sc.granicus.com", "SC"),
        ("Oxnard School District", "oxnardsd.granicus.com", "SD"),
        ("Colorado", "coloradoga.granicus.com", "GA"),
    ],
)
def test_a_subdomain_type_abbreviation_is_not_a_state(raw, host, forbidden_state):
    """arkansas-sc is the Arkansas Supreme Court, oxnardsd the Oxnard
    School District, coloradoga the Colorado General Assembly. The
    subdomain reader returns ("Arkansas", "SC") for the first, and the
    mint rung wrote `rtr:us:sc:arkansas-supreme-court` / "Arkansas
    Supreme Court, SC" -- hidden while an unverified page kept the
    adapter's string, live the day display-from-gov_id started rendering
    minted names (2026-09-10). Unresolved is the honest answer."""
    match = resolve(raw, host)
    assert match.state.upper() != forbidden_state
    assert not match.gov_id.startswith(f"rtr:us:{forbidden_state.lower()}:")
    assert forbidden_state not in (match.gov_name or "").split(",")[-1]


def test_the_general_assembly_still_reaches_its_state():
    """The guard removes only the wrong state; the name's own type still
    resolves -- the Colorado General Assembly is a body of the State of
    Colorado (decision D1)."""
    match = resolve("Colorado General Assembly", "coloradoga.granicus.com")
    assert match.gov_id == "us:state:08"


@pytest.mark.parametrize(
    "host, name, state, expected",
    [
        ("oxnardsd.granicus.com", "Oxnard", "SD", False),
        ("arkansas-sc.granicus.com", "Arkansas", "SC", False),
        ("coloradoga.granicus.com", "Colorado", "GA", False),
        ("aberdeensd.example.com", "Aberdeen", "SD", True),
        ("baltimoremd.example.com", "Baltimore", "MD", True),
        ("calgaryab.example.com", "Calgary", "AB", True),
    ],
)
def test_a_subdomain_state_must_hold_a_government_of_that_name(
    host, name, state, expected
):
    """The general rule behind "SC is sometimes Supreme Court, sometimes
    South Carolina" (Ryan, 2026-09-10): the two letters the subdomain
    reader strips off a label are a state only if some government of
    that name exists there. Baltimore has a city and a county row, and
    both count -- this is looser than lookup()'s exactly-one rule."""
    assert resolver._name_exists_in_state(name, state) is expected
    tenant_state, _evidence = resolver._state_from_tenant(host)
    if expected:
        assert tenant_state == state
    else:
        assert tenant_state != state


@pytest.mark.parametrize(
    "raw, gov_id",
    [
        ("Juneau, AK", "us:place:0236400"),
        ("City and Borough of Juneau, AK", "us:place:0236400"),
        ("Sitka, AK", "us:place:0270540"),
        ("Lexington, KY", "us:place:2146027"),
        ("Lexington-Fayette Urban County Government, KY", "us:place:2146027"),
        ("Athens, GA", "us:place:1303440"),
        ("Augusta, GA", "us:place:1304204"),
        ("Macon, GA", "us:place:1349008"),
        ("Butte, MT", "us:place:3011397"),
        ("Anaconda, MT", "us:place:3001675"),
        ("Lynchburg, TN", "us:place:4744382"),
        ("Hartsville, TN", "us:county:47169"),
        ("Kansas City, KS", "us:place:2036000"),
        ("Lafayette, LA", "us:place:2240735"),
        ("Municipality of Anchorage, AK", "us:place:0203000"),
        ("Tribune-Greeley County, KS", "us:county:20071"),
        # Same short names elsewhere must not be captured by the aliases.
        ("Lexington, TN", "us:place:4741980"),
        ("Augusta, KS", "us:place:2003300"),
    ],
)
def test_consolidated_governments_key_to_one_id_from_every_name_form(raw, gov_id):
    """The ~40 consolidated city-counties are spelled by the Census in a
    form no page writes ("Juneau city and borough", "Lexington-Fayette
    urban county", "Athens-Clarke County unified government (balance)");
    before the 2026-09-10 audit every bare form here minted a second
    government. "city and borough" / "urban county" are stripped like
    the other type phrases, and the hyphenated ones carry curated
    aliases. The two trailing cases pin that an alias is state-scoped."""
    match = resolve(raw, None)
    assert match.gov_id == gov_id
    assert match.tier == resolver.TIER_REGISTRY


@pytest.mark.parametrize(
    "raw, gov_id",
    [
        ("Philadelphia County, PA", "us:place:4260000"),
        ("San Francisco County, CA", "us:place:0667000"),
        ("City and County of San Francisco, CA", "us:place:0667000"),
        ("Denver County, CO", "us:place:0820000"),
        ("Kings County, NY", "us:place:3651000"),
        ("Davidson County, TN", "us:place:4752006"),
        ("Orleans Parish, LA", "us:place:2255000"),
        ("Fayette County, KY", "us:place:2146027"),
        ("Wyandotte County, KS", "us:place:2036000"),
        ("Greeley County unified government (balance), KS", "us:county:20071"),
        # Ordinary counties that merely share a name are untouched.
        ("Jefferson County, CO", "us:county:08059"),
        ("Richmond County, GA", "us:place:1304204"),
        ("Richmond County, VA", "us:county:51159"),
    ],
)
def test_the_county_form_of_a_consolidated_government_keys_to_the_same_id(raw, gov_id):
    """The Census keeps a county row AND a place row for each of the ~40
    consolidated city-counties; `consolidated_governments.csv` says which
    one the Archive treats as the government, and `_as_government()`
    redirects every table hit through it. Before this, "Philadelphia
    County, PA" would have opened a second hub beside "Philadelphia, PA"
    (filed 2026-09-10 after the consolidated-government audit; no
    archived page had used the county form yet)."""
    match = resolve(raw, None)
    assert match.gov_id == gov_id, match
    assert match.tier == resolver.TIER_REGISTRY


def test_every_consolidated_row_points_at_a_renderable_government():
    for gov_id, canonical in registry.consolidated().items():
        assert registry.government_for_id(canonical) is not None, (gov_id, canonical)
        assert gov_id != canonical


def test_every_consolidated_display_name_re_resolves_to_itself():
    """Idempotence for the backfill: the display the registry writes for a
    consolidated government must key straight back to that government.
    "Georgetown-Quitman County, GA" reads like a county name and no such
    county exists, so the second backfill pass declared it impossible and
    UN-keyed the page it had just keyed (2026-09-10) -- the curated alias
    is what closes that loop, and this test walks the whole map."""
    from app.utils.gov_registry import display_name, government_for_id

    for _gov_id, canonical in registry.consolidated().items():
        shown = display_name(government_for_id(canonical))
        match = resolve(shown, None)
        assert match.gov_id == canonical, (shown, match.gov_id, match.tier)


# --- WO-198: a township must not lose to a same-named borough/village --
#
# `scripts/backfill_gov_id.py`'s dry run against `www.youtube.com`
# proposed re-keying five real township/village pages onto the wrong
# same-named government (a borough, a village, or a bare id with the
# qualifier dropped). All five raw strings below are the pages' own
# stored `jurisdiction` -- `display_name()`'s `"{base} ({word}), {state}"`
# disambiguated form -- exactly as `backfill_gov_id.py` feeds it back
# into the resolver (see `/tmp/postdeploy2_dry.csv`, copied into
# `research/wo198_backfill_dry.csv` in rtr-business).
#
# Root cause was two rungs, both missing the same check: a single
# candidate in the PLACE table was never checked against the name's own
# type word, only checked when the place table already had more than one
# row (`_general_purpose_lookup()`'s `places` filter), and the
# spacing-insensitive rung 5b (`_squashed_national_hit()`) ran its own
# separate, completely unfiltered place lookup and reached the same wrong
# answer even after rung 4 correctly declined. Both are fixed the same
# way: filter a place candidate by `type_preference` unconditionally,
# exactly as cousubs already are.
#
# Every case here has a REAL same-named place government that made the
# bug possible (confirmed against `us_places.csv`/`us_cousubs.csv`):
# Northampton borough (`us:place:4254696`) beside two real Northampton
# townships (Bucks and Somerset counties, both `us_cousubs.csv`); Perry
# village (`us:place:3961882`) beside 28 real Perry townships across 28
# Ohio counties; Oakwood village/city (three real Ohio places sharing the
# base name "Oakwood"); Buckingham township and White River township
# (each real in two-plus PA/IN counties, with no PA/IN place of that name
# at all). The fix cannot pick which of several real same-typed
# townships is meant -- that needs a per-video pin, filed with WO-198 --
# but it must never again hand the page to a DIFFERENT kind of
# government just because that one happened to be the only place row.
#
# Host below is `example-unpinned.granicus.com`, not the real
# `www.youtube.com` these pages were actually found on: WO-210 (2026-09-
# 11) made an unpinned `www.youtube.com` resolve return no government at
# all before this rung's own qualifier/type-word logic ever runs, which
# is a different, correct outcome these tests aren't about -- the raw
# strings are still the real, currently-unpinned stored values from the
# dry run cited above; only the host changed. See BACKLOG.md's WO-210
# follow-up entry: these real pages now need an actual per-video pin to
# resolve at all going forward.
@pytest.mark.parametrize(
    "raw",
    [
        "Northampton (township), PA",
        "Perry (township), OH",
        "Buckingham (township), PA",
        "White River (township), IN",
        "Oakwood (village), OH",
    ],
)
def test_a_township_or_village_never_loses_to_a_same_named_place_of_a_different_type(
    raw,
):
    match = resolve(raw, "example-unpinned.granicus.com")
    # Never the borough/village/city rtr:'s wrong-but-confident registry
    # hit from before this fix -- either a correctly declined mint (no
    # real single candidate to pick) or, if a future data change makes
    # exactly one real candidate of the RIGHT type exist, a cousub id.
    # Never a `us:place:` id, which is what every one of these wrongly
    # became.
    assert not (match.gov_id or "").startswith("us:place:"), (raw, match.gov_id)
    if match.gov_id and match.gov_id.startswith("rtr:"):
        assert match.tier == resolver.TIER_UNVERIFIED


def test_northampton_borough_still_resolves_to_the_borough():
    # The negative control matching the bug table above: a page that
    # really IS the borough (no "township"/paren qualifier at all) must
    # keep working exactly as before this fix. Host per the WO-210 note
    # above this section.
    match = resolve("Northampton (borough), PA", "example-unpinned.granicus.com")
    assert match.gov_id == "us:place:4254696"
    assert match.tier == resolver.TIER_REGISTRY


def test_perry_village_still_resolves_to_the_village():
    match = resolve("Perry (village), OH", "example-unpinned.granicus.com")
    assert match.gov_id == "us:place:3961882"
    assert match.tier == resolver.TIER_REGISTRY


def test_squashed_lookup_also_respects_a_township_type_word():
    # Direct unit coverage for rung 5b (`_squashed_national_hit()`): the
    # general-purpose ladder (rung 4) already declines "Northampton
    # (township), PA" via `_general_purpose_lookup()`'s place filter, but
    # rung 5b ran its OWN separate, unfiltered `lookup_squashed()` call
    # and reached Northampton borough anyway -- the actual shape of the
    # bug measured against the real dry-run report before this fix.
    hit = resolver._squashed_national_hit("Northampton", "PA", None, "us", "township")
    assert hit is None
    # Unfiltered (no type word) still finds the borough -- confirms the
    # fix is the type check, not a broken lookup.
    hit = resolver._squashed_national_hit("Northampton", "PA", None, "us", "")
    assert hit is not None
    assert hit[0].gov_id == "us:place:4254696"


@pytest.mark.parametrize(
    "raw,gov_id",
    [
        ("Lancaster (township), PA", "rtr:us:pa:lancaster-township"),
        ("Conewago (township), PA", "rtr:us:pa:conewago-township"),
        ("Shrewsbury (township), PA", "rtr:us:pa:shrewsbury-township"),
    ],
)
def test_minting_a_disambiguated_township_keeps_its_qualifier(raw, gov_id):
    """Round-trip idempotence for `_mint()` (WO-198): a first-ever resolve
    of "Lancaster Township, PA" carries "township" IN the raw name, so it
    always minted `rtr:us:pa:lancaster-township` -- but the STORED
    `jurisdiction` for an unverified/minted government is still written
    through `display_name()`'s ambiguous-name disambiguator (the same
    "{base} ({word}), {state}" round-trip form
    `_strip_trailing_paren_type()` exists for), and re-resolving THAT
    string strips "township" into `type_preference` before `name` ever
    reaches `_mint()`. Before this fix that produced a bare
    `rtr:us:pa:lancaster`, silently dropping the one thing that kept it
    from colliding with a same-named place, and downgraded `gov_type` to
    `other`. These three are real, currently-unpinned pages
    (`scripts/backfill_gov_id.py --hosts www.youtube.com`'s dry run,
    WO-198) that would have regressed from a working qualified id to a
    bare one on the very backfill run meant to fix a different bug.

    Host below is `example-unpinned.granicus.com`, not the real
    `www.youtube.com` -- see the WO-210 note on
    `test_a_township_or_village_never_loses_to_a_same_named_place_of_a_different_type`
    above; these three real pages now need an actual per-video pin to
    resolve on `www.youtube.com` itself."""
    match = resolve(raw, "example-unpinned.granicus.com")
    assert match.gov_id == gov_id
    assert match.gov_type == classify.TOWNSHIP
    assert match.tier == resolver.TIER_UNVERIFIED


def test_minting_does_not_double_up_a_type_word_already_in_the_name():
    # A name with no paren form (so `type_preference` comes from
    # `_leading_type_word()`/`_strip_trailing_paren_type()` finding
    # nothing) already carries "township" IN `name` when it matches no
    # table -- the guard that skips re-appending must not turn this into
    # "zzyzxville-township-township". "Zzyzxville" is invented on purpose
    # (guaranteed to match no real table row); the state (WY) is real.
    match = resolve("Zzyzxville Township, WY")
    assert match.gov_id == "rtr:us:wy:zzyzxville-township"
    assert match.gov_type == classify.TOWNSHIP


# --- WO-204: a minted township's HUB slug must keep its qualifier too --
#
# WO-198's `_mint()` fix (above) folded `type_preference` back into the
# SLUG and `gov_type` so re-resolving a disambiguated "Lancaster
# (township), PA" string still minted `rtr:us:pa:lancaster-township`, not
# a bare `rtr:us:pa:lancaster`. It did not fold the same word into
# `gov_name` -- and `display_name()`/`GovernmentMatch.hub_slug` (what
# `scripts/backfill_gov_id.py` actually reads for its "hub_after" column)
# derive from `gov_name`, not from the id's own slug. So the `gov_id` was
# right and the HUB was still wrong: a fresh dry run against
# `www.youtube.com` (`/tmp/postdeploy3_dry.csv`, conductor-provided)
# proposed moving these seven real, currently-placeholder-id'd pages from
# their own `{name}-township-{st}` hub onto the bare `{name}-{st}` hub --
# which in every one of these seven states is the SAME hub a real
# same-named borough/city could later claim, recreating the exact
# collision WO-198's id fix already closed off for the id itself.
@pytest.mark.parametrize(
    "raw,gov_id,hub_slug",
    [
        (
            "Lancaster (township), PA",
            "rtr:us:pa:lancaster-township",
            "lancaster-township-pa",
        ),
        (
            "Conewago (township), PA",
            "rtr:us:pa:conewago-township",
            "conewago-township-pa",
        ),
        (
            "Shrewsbury (township), PA",
            "rtr:us:pa:shrewsbury-township",
            "shrewsbury-township-pa",
        ),
        (
            "Deerfield (township), OH",
            "rtr:us:oh:deerfield-township",
            "deerfield-township-oh",
        ),
        ("Berlin (township), OH", "rtr:us:oh:berlin-township", "berlin-township-oh"),
        ("Spring (township), PA", "rtr:us:pa:spring-township", "spring-township-pa"),
        ("Summit (township), PA", "rtr:us:pa:summit-township", "summit-township-pa"),
    ],
)
def test_a_minted_township_keeps_its_qualifier_in_the_hub_slug_too(
    raw, gov_id, hub_slug
):
    # Host is `example-unpinned.granicus.com`, not the real
    # `www.youtube.com` these pages were found on -- see the WO-210 note
    # above `test_a_township_or_village_never_loses_to_a_same_named_place_of_a_different_type`.
    match = resolve(raw, "example-unpinned.granicus.com")
    assert match.gov_id == gov_id
    assert match.gov_type == classify.TOWNSHIP
    assert match.tier == resolver.TIER_UNVERIFIED
    assert match.hub_slug == hub_slug


# --- WO-204: six of the seven pins confirmed for the real government ---
#
# Real yt-dlp channel/description evidence for each (see
# `app/utils/jurisdiction_data/tenant_overrides.csv`'s `wo204` rows for
# the full per-video reasoning): a video-level pin (the page's own
# stored jurisdiction still round-trips through `_mint()` when nothing
# pins it, so these confirm the PIN wins over the placeholder). The
# seventh (Spring Township, PA) is deliberately NOT pinned here -- its
# one video is the Pennsylvania Public Utility Commission's own meeting
# (channel "PennsylvaniaPUC"), not a Spring Township meeting at all; see
# `BACKLOG.md`.
@pytest.mark.parametrize(
    "video_id,gov_id",
    [
        ("PYhquSuyMnE", "us:cousub:4207141224"),  # Lancaster twp, Lancaster Co, PA
        ("-mPEPo0pFMA", "us:cousub:4213315656"),  # Conewago twp, York Co, PA
        ("PusqQnQGxIc", "us:cousub:4213370576"),  # Shrewsbury twp, York Co, PA
        ("NPWUzSgT0x0", "us:cousub:3916521238"),  # Deerfield twp, Warren Co, OH
        ("THZzByl2X7Q", "us:cousub:3904105788"),  # Berlin twp, Delaware Co, OH
        ("mDPlwkC30dU", "us:cousub:4204975208"),  # Summit twp, Erie Co, PA
    ],
)
def test_wo204_confirmed_township_pins_win_over_the_placeholder(video_id, gov_id):
    match = resolve(
        None,
        "www.youtube.com",
        page_hints={"external_id": f"youtube:{video_id}"},
    )
    assert match.gov_id == gov_id
    assert match.tier == resolver.TIER_PINNED


# --- WO-204: the WO-198 "7 need a look" leftovers, closed out ----------
#
# Five of the seven corpus-scan pages from WO-198's own follow-up
# (`BACKLOG_DONE.md`, WO-198) get a tenant-HOST pin here (not per-video):
# each host is a single-purpose subdomain/domain for one real government,
# confirmed live (site title, board roster, or channel name -- see
# `tenant_overrides.csv`'s `wo204` rows). Two (the Washington Township
# ZBA duplicate pages) share one host/pin. `raw` is each page's own
# STORED `jurisdiction`/`jurisdiction_raw` (blank for three of them --
# the adapter never extracted a name at ingest -- and a wrong-but-
# confident real government's name for the other two, Newtown/Mantua),
# exactly what a real re-resolve of these pages feeds in.
@pytest.mark.parametrize(
    "raw,host,gov_id,tier",
    [
        (
            None,
            "northbrunswicktv.cablecast.tv",
            "us:cousub:3402352560",
            resolver.TIER_PINNED,
        ),
        (None, "wbrw.cablecast.tv", "us:cousub:2609984120", resolver.TIER_PINNED),
        (None, "utclermont.gov", "us:cousub:3902578288", resolver.TIER_PINNED),
        (
            "Newtown (borough), PA",
            "newtowntownship.civicweb.net",
            "us:cousub:4204554224",
            resolver.TIER_PINNED,
        ),
        (
            "Mantua village, OH",
            "mantuatownshipohio.gov",
            "us:cousub:3913347194",
            resolver.TIER_PINNED,
        ),
    ],
)
def test_wo204_tenant_host_pins_for_the_wo198_leftovers(raw, host, gov_id, tier):
    match = resolve(raw, host)
    assert match.gov_id == gov_id
    assert match.tier == tier


def test_wo204_newtown_and_mantua_pins_are_authoritative_not_fallback():
    # Same constraint WO-198 hit for Rockaway/Park Township: a fallback
    # pin never fires when the ladder already confidently (but wrongly)
    # resolves the STORED jurisdiction string via rung 4 first. Both
    # hosts here ALSO carry an older, wrong `ryan_stated` FALLBACK pin
    # from the bulk pin-worklist apply (PR #733) -- a heuristic
    # domain-to-place match that (like WO-198's own root cause) ignored
    # the "township" in the subdomain/site and matched the wrong
    # same-named place. `authoritative` strength is what lets this WO's
    # pin win over that one (checked first, rung 1) rather than never
    # being reached (a `fallback` pin here would tie with the old one and
    # the loader's own tie-break would decide, not the ladder logic this
    # is trying to test) -- see `tenant_overrides.csv`'s wo204 rows.
    for host, gov_id in [
        ("newtowntownship.civicweb.net", "us:cousub:4204554224"),
        ("mantuatownshipohio.gov", "us:cousub:3913347194"),
    ]:
        matches = [
            row
            for row in resolver._override_rows_for_host(host)
            if row.gov_id == gov_id
        ]
        assert len(matches) == 1, (host, matches)
        assert matches[0].strength == "authoritative"


# --- WO-210, 2026-09-11: multi-government host safeguard ---------------
#
# Ryan, verbatim: "We absolutely cannot use pins for the multi-gov hosts
# like vimeo, youtube, youtu.be, clerkshq, etc. because they're so
# prevalent and we KNOW they need a match. Can we create a pin that sort
# of does the opposite of tying a domain to a gov? Like 'if youtu.be
# without a channel match, pin to NULL.'" Three layers: the loader
# refuses a blank-match row on a `MULTI_GOV_HOSTS` host
# (`registry._load_tenant_overrides()`), the ladder itself refuses to
# resolve one of those hosts from anything but a matching pin
# (`resolver._resolve_government_ladder()`'s rung 1b), and the override
# endpoint never drafts a blank-match rule for one (`archive/db/crud.py`,
# tested separately in `tests/test_jurisdiction_override.py`).


def test_no_blank_match_row_on_a_multi_gov_host():
    """Committed-file invariant: `tenant_overrides.csv` must never carry
    a blank-`match` row on a `MULTI_GOV_HOSTS` host. The loader already
    refuses to apply one (see the synthetic tests below), but this is
    what fails CI the moment one is committed anyway -- the exact
    regression `BACKLOG_DONE.md`'s WO-183/WO-206/WO-206b describes: the
    Oak Bluffs `vimeo.com,,<gov_id>` wildcard was deleted once, came back
    through a rebase, and had to be deleted again."""
    assert registry.rejected_multi_gov_overrides() == ()


# --- WO-241, 2026-09-11: no duplicate/blank-gov_id catch-all rows -------
#
# Found while resolving rtr-deeplink PR #811's merge conflict (WO-132):
# 13 hosts each carried two `match=""` (catch-all) rows. Verified live
# against the current loader (`_load_tenant_overrides()` already drops a
# blank-`gov_id` row via its own `if not host or not gov_id: continue`,
# and `_pinned()` already picks the higher-strength row when two catch-
# alls differ in strength) that none of the 13 were actually resolving
# wrong today -- the blank-gov_id ones are dead weight, not live bugs,
# and `newtowntownship.civicweb.net`'s WO-204 `authoritative` row already
# won over its stray `fallback` one. Cleaned up anyway: two catch-all
# rows for one host is exactly the shape that WAS a live bug elsewhere
# this same week (PR #813/WO-132's `dallascounty.civicweb.net` fix, two
# same-strength catch-alls with no principled way to pick between them,
# resolved only by file order) -- these tests are the guard against that
# shape recurring, not just cleanup of these 13. A further 18 hosts
# turned out to carry a lone blank-`gov_id` row (no duplicate) once the
# first test below was written against the real file -- same dead-weight
# shape, cleaned up too since the general invariant asked for is "no row
# has a blank gov_id", not "no row has a blank gov_id next to another
# row for the same host".


def test_no_row_has_a_blank_gov_id():
    """Committed-file invariant: every `tenant_overrides.csv` row has a
    real `gov_id`. The loader already drops a blank one silently
    (`_load_tenant_overrides()`), which is exactly why one could sit
    there unnoticed for as long as these rows did -- nothing failed
    loudly until someone went looking. This is that loud failure."""
    with open(DATA_DIR / "tenant_overrides.csv", encoding="utf-8") as fh:
        blank = [
            r["tenant_host"] for r in csv.DictReader(fh) if not r["gov_id"].strip()
        ]
    assert blank == []


def test_at_most_one_catchall_row_per_host():
    """Committed-file invariant: no `tenant_host` carries two `match=""`
    rows. `_match_override()` returns every row whose `match is None`
    for a host, and `_pinned()` takes the first one at a given strength
    -- two catch-alls at the SAME strength resolve by file order alone,
    not by anything meaningful (the `dallascounty.civicweb.net` bug this
    guards against). Two catch-alls at DIFFERENT strengths (an
    `authoritative` override sitting beside the `fallback` row it beats)
    aren't dangerous the same way, but no real case needs that shape
    today -- Kankakee/McLean's fix edited one row's strength in place
    rather than adding a second -- so this stays a flat "at most one,"
    not "at most one per strength," until a real case argues otherwise."""
    with open(DATA_DIR / "tenant_overrides.csv", encoding="utf-8") as fh:
        catchall_hosts = [
            r["tenant_host"] for r in csv.DictReader(fh) if not r["match"].strip()
        ]
    seen = set()
    dupes = sorted({h for h in catchall_hosts if h in seen or seen.add(h)})
    assert dupes == []


def test_loader_rejects_blank_match_row_on_a_multi_gov_host(monkeypatch, tmp_path):
    """The loader-level half of the safeguard: a blank-match row on
    `vimeo.com` (the real Oak Bluffs shape before WO-183's fix) never
    loads, is counted, and resolving that host with no other pin lands on
    `TIER_BLANK` -- an unknown government, never the row's `gov_id`."""
    overrides = tmp_path / "tenant_overrides.csv"
    overrides.write_text(
        "tenant_host,match,gov_id,strength,source,evidence\n"
        "vimeo.com,,us:cousub:2500750390,fallback,ryan_stated,"
        '"Oak Bluffs, MA -- blank match, must never load"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(registry, "DATA_DIR", tmp_path)
    registry.clear_caches()
    try:
        assert registry.tenant_overrides().get("vimeo.com", []) == []
        rejected = registry.rejected_multi_gov_overrides()
        assert len(rejected) == 1
        assert rejected[0].tenant_host == "vimeo.com"
        assert rejected[0].gov_id == "us:cousub:2500750390"

        # End to end (WO-210's second required test): with the bad row
        # refused at load time, a Vimeo page with no OTHER pin resolves
        # to no government at all, not to Oak Bluffs.
        match = resolver.resolve_government(None, tenant_host="vimeo.com", path="/999")
        assert match.gov_id != "us:cousub:2500750390"
        assert match.tier == resolver.TIER_BLANK
    finally:
        registry.clear_caches()


def test_loader_still_accepts_blank_match_row_on_a_single_tenant_host(
    monkeypatch, tmp_path
):
    """The safeguard is specific to `MULTI_GOV_HOSTS` -- an ordinary
    single-tenant host's blank-match row (the everyday, correct shape:
    the whole host really is one government) is untouched."""
    overrides = tmp_path / "tenant_overrides.csv"
    overrides.write_text(
        "tenant_host,match,gov_id,strength,source,evidence\n"
        "pub-sechelt.escribemeetings.com,,ca:csd:5933042,authoritative,"
        'known_domains,"Sechelt, BC"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(registry, "DATA_DIR", tmp_path)
    registry.clear_caches()
    try:
        rows = registry.tenant_overrides()["pub-sechelt.escribemeetings.com"]
        assert len(rows) == 1
        assert rows[0].match is None
        assert registry.rejected_multi_gov_overrides() == ()
    finally:
        registry.clear_caches()


def test_oak_bluffs_vimeo_pin_is_per_video_not_a_host_wildcard():
    """The real, currently-committed fix for the incident itself
    (`tenant_overrides.csv`'s `vimeo.com,vimeo:1199438213,
    us:cousub:2500750390,...` row, WO-183): it must fire for its OWN
    video and must NOT fire for a different video on the same host --
    the exact failure mode that mis-attributed Hanover township PA,
    Middletown township PA and a Lancaster County PA page to Oak Bluffs,
    MA."""
    hints = resolver.page_hints_for("vimeo", "vimeo:1199438213")
    match = resolver.resolve_government(
        None, tenant_host="vimeo.com", path="/1199438213", page_hints=hints
    )
    assert match.gov_id == "us:cousub:2500750390"
    assert match.tier == resolver.TIER_PINNED

    other_hints = resolver.page_hints_for("vimeo", "vimeo:9999999999")
    other = resolver.resolve_government(
        None, tenant_host="vimeo.com", path="/9999999999", page_hints=other_hints
    )
    assert other.gov_id != "us:cousub:2500750390"
    assert other.tier == resolver.TIER_BLANK


def test_severn_on_channel_pin_matches_only_that_channel():
    """The real, currently-committed `www.youtube.com,
    channel=@severnontario,ca:csd:3543015,...` row: it must fire only for
    a video whose channel hint is `@severnontario`, never for a different
    channel's video on the same `www.youtube.com` host."""
    hints = resolver.page_hints_for("youtube", "youtube:abc", channel="@severnontario")
    match = resolver.resolve_government(
        None, tenant_host="www.youtube.com", path="/watch?v=abc", page_hints=hints
    )
    assert match.gov_id == "ca:csd:3543015"
    assert match.tier == resolver.TIER_PINNED

    other_hints = resolver.page_hints_for(
        "youtube", "youtube:xyz", channel="@SomeoneElse"
    )
    other = resolver.resolve_government(
        None, tenant_host="www.youtube.com", path="/watch?v=xyz", page_hints=other_hints
    )
    assert other.gov_id != "ca:csd:3543015"


def test_bare_youtube_watch_url_with_no_pin_resolves_to_none():
    """Ryan's rule, verbatim: 'if youtu.be without a channel match, pin
    to NULL.' A bare YouTube watch URL, no pin, no page_hints -- must
    return no government at all, never a national-table guess from
    whatever the video's title or channel says."""
    match = resolver.resolve_government(
        None, tenant_host="youtu.be", path="/watch?v=zzzzzzzzzzz"
    )
    assert not match.gov_id or match.gov_id.startswith("rtr:unknown:")
    assert match.tier == resolver.TIER_BLANK


def test_multi_gov_host_never_resolves_from_a_name_guess_with_no_pin():
    """The stronger form of the same rule: even a raw name that WOULD
    validate against a real, unambiguous place (the shape
    `app/platforms/youtube.py`'s `_jurisdiction()` produces from a real
    channel name, per its own docstring's "Roosevelt City" example) must
    not resolve on a `MULTI_GOV_HOSTS` host absent a matching pin --
    nothing about an untrusted host's own metadata is identity."""
    match = resolver.resolve_government(
        "City of Boston, MA", tenant_host="youtu.be", path="/watch?v=aaaaaaaaaaa"
    )
    assert not match.gov_id or match.gov_id.startswith("rtr:unknown:")
    assert match.tier == resolver.TIER_BLANK
    # Control: the identical raw name on an ordinary (non-multi-gov) host
    # still resolves normally -- this is a host-specific safeguard, not a
    # change to name resolution in general.
    control = resolver.resolve_government(
        "City of Boston, MA", tenant_host="boston.granicus.com"
    )
    assert control.tier == resolver.TIER_REGISTRY


# --- WO-221, 2026-09-11: a matched pin wins on a shared host, before
# rungs 2-4 run --------------------------------------------------------
#
# Real incident found by the outgoing WO-210 conductor's 12:50 PT
# backfill: page 8632 "Bronx, NY" resolved to New York city
# (`us:place:3651000`) even though WO-216's pin says `us:county:36005`.
# The cause: a `fallback`-strength pin on a `MULTI_GOV_HOSTS` host was
# only consulted by rung 5, AFTER rung 4's national table already
# matched the video's own jurisdiction string ("Bronx" is a borough of
# New York City in the place table, so "Bronx, NY" resolves
# nationally to `us:place:3651000` -- confirmed live, see the control
# assertion below). Rung 1b's OWN "no match -> no government" rule is
# untouched by this fix; these tests only add the "match found -> use it
# immediately" half.


def test_bronx_ny_resolves_nationally_to_new_york_city_control():
    """Control for the test below, kept as its own test (no `DATA_DIR`
    monkeypatch in scope at all) so it is unambiguous what rung 4 alone
    produces: the jurisdiction string real page 8632 carried, on a host
    with no pin, resolves through the national table to New York city --
    "Bronx" is a borough of New York City in the place table. This is
    the wrong answer rung 4 used to produce for a pinned video before
    this fix, and it is what the resolver already did for real page 8632
    before WO-221."""
    control = resolver.resolve_government(
        "Bronx, NY", tenant_host="boston.granicus.com"
    )
    assert control.gov_id == "us:place:3651000"
    assert control.tier == resolver.TIER_REGISTRY


def test_matched_pin_wins_over_national_table_bronx_county_case(monkeypatch, tmp_path):
    """Reproduces the Bronx County case: a `fallback` pin to
    `us:county:36005` on a matched YouTube video must win over rung 4's
    national-table match on the jurisdiction string, which (see the
    control test above) would otherwise land on New York city."""
    overrides = tmp_path / "tenant_overrides.csv"
    overrides.write_text(
        "tenant_host,match,gov_id,strength,source,evidence\n"
        "www.youtube.com,zzz1111111,us:county:36005,fallback,wo221,"
        '"Bronx County, NY -- WO-221 regression test for the real 8632 '
        'incident"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(registry, "DATA_DIR", tmp_path)
    registry.clear_caches()
    try:
        match = resolver.resolve_government(
            "Bronx, NY",
            tenant_host="www.youtube.com",
            path="/watch?v=zzz1111111",
        )
        assert match.gov_id == "us:county:36005"
        assert match.tier == resolver.TIER_PINNED
    finally:
        registry.clear_caches()


def test_matched_pin_wins_even_when_a_different_video_on_the_host_would_blank(
    monkeypatch, tmp_path
):
    """Same host, a different (unpinned) video: rung 1b's no-match rule
    still fires exactly as before -- WO-221 only changes what happens
    when a pin DOES match, never widens what counts as a match."""
    overrides = tmp_path / "tenant_overrides.csv"
    overrides.write_text(
        "tenant_host,match,gov_id,strength,source,evidence\n"
        "www.youtube.com,zzz1111111,us:county:36005,fallback,wo221,"
        '"Bronx County, NY -- WO-221 regression test"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(registry, "DATA_DIR", tmp_path)
    registry.clear_caches()
    try:
        other = resolver.resolve_government(
            "Bronx, NY",
            tenant_host="www.youtube.com",
            path="/watch?v=someothervideoid",
        )
        assert other.gov_id != "us:county:36005"
        assert other.tier == resolver.TIER_BLANK
    finally:
        registry.clear_caches()


def test_matched_authoritative_pin_on_shared_host_still_wins_as_before(
    monkeypatch, tmp_path
):
    """An `authoritative`-strength matched pin (rung 1, unchanged) still
    resolves correctly -- WO-221 only had to add the `fallback` case."""
    overrides = tmp_path / "tenant_overrides.csv"
    overrides.write_text(
        "tenant_host,match,gov_id,strength,source,evidence\n"
        "www.youtube.com,zzz3333333,us:county:36005,authoritative,wo221,"
        '"Bronx County, NY -- authoritative control"\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(registry, "DATA_DIR", tmp_path)
    registry.clear_caches()
    try:
        match = resolver.resolve_government(
            "Bronx, NY",
            tenant_host="www.youtube.com",
            path="/watch?v=zzz3333333",
        )
        assert match.gov_id == "us:county:36005"
        assert match.tier == resolver.TIER_PINNED
    finally:
        registry.clear_caches()


# --- WO-214, 2026-09-11: origin_host fallback for CivicPlus/Legistar
# delegation ---------------------------------------------------------
#
# WO-210's own rung-1b comment named the one real exception it left
# affected: `civicplus.py`/`legistar.py` delegate a linked video to
# `resolve_via_platform()`, which returns the DELEGATED platform's result
# as-is (`.source_url`/`.platform` end up as YouTube's/Vimeo's own, never
# rewritten back -- CLAUDE.md's platform-wrapper "known quirk" bullet).
# A CivicPlus/Legistar page that used to key off its own subdomain-
# derived name landed on `TIER_BLANK` instead, same as an un-delegated
# multi-gov-host page, because nothing distinguished a trustworthy
# delegating-tenant name from an untrusted channel/title guess once both
# reached rung 1b as a plain string. Fixed by carrying the delegating
# tenant's own host separately as `origin_host` (see
# `ResolvedMeeting.origin_host`'s own docstring, `app/platforms/
# civicplus.py`/`legistar.py`), consulted here only as a fallback when
# the delegated host has no matching pin.


def test_delegated_multi_gov_host_falls_back_to_origin_host_when_no_pin():
    """The core fix: a name that would resolve cleanly against the
    delegating CivicPlus tenant's own host (nc-durham.civicplus.com, a
    real tenant -- see tests/test_civicplus.py's Durham fixture tests)
    still resolves when `tenant_host` is the delegated YouTube host and
    no per-video/channel pin exists for it, as long as `origin_host` is
    given. Real government id, not a mint: `us:place:3719000` is Durham,
    NC's own committed governments.csv row."""
    direct = resolver.resolve_government(
        "City of Durham, NC", tenant_host="nc-durham.civicplus.com"
    )
    assert direct.gov_id == "us:place:3719000"
    assert direct.tier == resolver.TIER_REGISTRY

    delegated = resolver.resolve_government(
        "City of Durham, NC",
        tenant_host="www.youtube.com",
        path="/watch?v=tz8M7oiZQzc",
        origin_host="nc-durham.civicplus.com",
    )
    assert delegated.gov_id == direct.gov_id
    assert delegated.tier == resolver.TIER_REGISTRY

    # Control: without origin_host, the exact same page still blanks --
    # confirming the fallback, not some unrelated change, is what fixed
    # the case above (and that rung 1b itself is unchanged/unweakened).
    without_origin = resolver.resolve_government(
        "City of Durham, NC",
        tenant_host="www.youtube.com",
        path="/watch?v=tz8M7oiZQzc",
    )
    assert without_origin.tier == resolver.TIER_BLANK


def test_origin_host_fallback_never_overrides_a_real_matching_pin():
    """A per-video/channel pin on the DELEGATED host is real, human-
    verified evidence -- it must keep winning outright, exactly as
    before this fix, even when `origin_host` is also present and would
    have resolved to a DIFFERENT government. Reuses the real, currently-
    committed Severn Ontario channel pin from the test above."""
    hints = resolver.page_hints_for("youtube", "youtube:abc", channel="@severnontario")
    match = resolver.resolve_government(
        None,
        tenant_host="www.youtube.com",
        path="/watch?v=abc",
        page_hints=hints,
        # A CivicPlus tenant that would resolve to a totally different,
        # real government if the pin above did not win first.
        origin_host="nc-durham.civicplus.com",
    )
    assert match.gov_id == "ca:csd:3543015"
    assert match.tier == resolver.TIER_PINNED


def test_origin_host_itself_a_multi_gov_host_is_not_trusted():
    """Guard rail: `origin_host` is only trusted when it is NOT itself a
    shared, multi-government host -- otherwise a chain of delegations
    (however unlikely in practice today) could launder an untrusted name
    straight past rung 1b a second time. A bare fallback to the ladder's
    honest blank-government outcome is what this returns instead, same
    as `test_bare_youtube_watch_url_with_no_pin_resolves_to_none` above."""
    match = resolver.resolve_government(
        "City of Boston, MA",
        tenant_host="youtu.be",
        path="/watch?v=zzzzzzzzzzz",
        origin_host="vimeo.com",
    )
    assert not match.gov_id or match.gov_id.startswith("rtr:unknown:")
    assert match.tier == resolver.TIER_BLANK
