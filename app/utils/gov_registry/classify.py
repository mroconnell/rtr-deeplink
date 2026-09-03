"""What KIND of government a name describes -- run BEFORE any place
lookup, which is the whole point of it.

Architecture doc §5 step 3: "This is the step that stops LADWP becoming
Los Angeles: a name that classifies as `special_district` is looked up in
the special-district path, and if that finds nothing it becomes an `rtr:`
government -- it is never allowed to fall through to the place table just
because 'Los Angeles' appears in it." Nine real tenants were resolving to
the wrong government for exactly that reason (§1.3).

The rules are ported from `rtr-discovery/discovery/feed/govtype.py`,
which classifies the measured cases correctly, and NOT from
`archive/utils/gov_classify.py`, which does not: run on 2026-09-02, that
one files "Broward County Public Schools, FL" and "West County Wastewater
District, CA" as counties (its county regex runs first) and "Minnesota
Senate, MN" as a city (its default). `gov_classify.py` stays in place and
unchanged this phase -- it drives the `/state/*` headings today, and
retiring it is Phase 2 work.

Ported rather than imported: `govtype.py` lives in another repo and
reaches back into rtr-deeplink through its own seam, so importing it here
would be a cycle. The rule *order* is load-bearing and is preserved
exactly -- court, state, school_district, township, county,
special_district, municipality -- because it is what makes "Tarrant
County College District" a school district instead of a county, and the
county rule's own negative lookahead is what keeps "Los Angeles County
Metropolitan Transportation Authority" out of the county bucket.

Vocabulary is the Census of Governments' (decision D7): county,
municipality, township, school_district, special_district, state, court,
other.
"""

import re
from typing import Optional

COUNTY = "county"
MUNICIPALITY = "municipality"
TOWNSHIP = "township"
SCHOOL_DISTRICT = "school_district"
SPECIAL_DISTRICT = "special_district"
STATE = "state"
COURT = "court"
OTHER = "other"

GOVERNMENT_TYPES = (
    COUNTY,
    MUNICIPALITY,
    TOWNSHIP,
    SCHOOL_DISTRICT,
    SPECIAL_DISTRICT,
    STATE,
    COURT,
    OTHER,
)

# Types that must never fall through to a general-purpose place lookup,
# however place-like their name reads. This set is the mechanism behind
# §5 step 3 -- see `resolver.py`'s `_national_lookup()`, which consults
# it rather than trusting each rule's own table choice.
NON_PLACE_TYPES = frozenset({SCHOOL_DISTRICT, SPECIAL_DISTRICT, STATE, COURT})

_RULES: list[tuple[str, re.Pattern]] = [
    (
        COURT,
        re.compile(r"\b(court|courts|judicial|judiciary)\b", re.I),
    ),
    (
        STATE,
        re.compile(
            r"^(state of\b|commonwealth of\b)|\b(legislature|general assembly|"
            r"state senate|state assembly|house of representatives|house of delegates|"
            r"state house|senate|assembly)\b",
            re.I,
        ),
    ),
    (
        SCHOOL_DISTRICT,
        re.compile(
            r"\b(school district|unified|usd|cisd|elementary district|high school district|"
            r"board of education|school board|schools|community college|college district|"
            r"independent school|isd|public schools|school committee)\b|"
            r"\b[a-z.'-]+ college$",
            re.I,
        ),
    ),
    (
        TOWNSHIP,
        re.compile(r"\b(township|twp\.?)\b|\btown(ship)? of [^,]+ township\b", re.I),
    ),
    (
        COUNTY,
        re.compile(
            r"^(county|parish) of\b|\b(county|parish)\b(?! (water|wastewater|fire|"
            r"sanitation|"
            r"transit|transportation|housing|library|hospital|utility|airport|"
            r"office of education|superintendent|schools|school district|"
            r"regional|redevelopment|water utility|flood|sanitary|park|"
            r"community college))",
            re.I,
        ),
    ),
    (
        SPECIAL_DISTRICT,
        re.compile(
            r"\b(district|authority|agency|commission|jpa|joint powers|transit|"
            r"transportation|water|sanitation|sanitary|fire protection|utility|"
            r"utilities|airport|port|housing|library|hospital|healthcare|"
            r"conservation|irrigation|flood control|metropolitan|regional|"
            r"council of governments|cog|association of governments|"
            r"planning organization|mpo|tv|television|cable|media center)\b",
            re.I,
        ),
    ),
    (
        MUNICIPALITY,
        re.compile(
            r"^(city|town|village|borough|municipality|city and county|"
            r"metropolitan government|metro government)( of)?\b|"
            r"\b(city|town|village|borough)$",
            re.I,
        ),
    ),
]

# Canadian upper-tier general-purpose governments. "Region of Peel" /
# "Peel Region" / "Regional Municipality of Durham" are real governments
# that meet, and the `ca:cd` namespace exists for them (architecture doc
# §3) -- but every one of those strings hits `_RULES`' special_district
# pattern on the word "regional"/"region" first and would mint an `rtr:`
# id instead of keying to its census division. Checked ahead of the rules
# because it is a narrower, evidence-backed statement about a specific
# real shape: Peel, Durham and Waterloo are all confirmed live customers
# (build_jurisdiction_data.py's own `_ONTARIO_REGIONAL_MUNICIPALITIES`
# comment records the audit), and Peel Region is the repo's standing
# eScribe caption sample.
_CA_UPPER_TIER_RE = re.compile(
    r"^(regional municipality of|region of|county of)\b|"
    r"\b(regional municipality|region|regional district)$",
    re.I,
)

# Consolidated city-county governments: San Francisco, Denver, Honolulu,
# Juneau, Sitka, Nashville-Davidson, Louisville/Jefferson. One government,
# and Census keys it as a *place* (`San Francisco city`, GEOID 0667000),
# which is why it must classify `municipality` -- the county rule below
# fires on the literal word "County" in "City and County of San
# Francisco" and would send it to the county table, where the name does
# not match and it would mint an `rtr:` id for a government that has a
# perfectly good national one. Confirmed live in the first seeding run.
#
# `archive/utils/jurisdiction_format.format_jurisdiction_display()` already
# guards the same phrase for the same reason, from its own live bug
# ("City of " stripping left a mangled "and County of San Francisco").
# Exported because `resolver.py` strips the same phrase before its lookup.
CONSOLIDATED_RE = re.compile(
    r"^(?:the\s+)?(?:city and county|city and borough|town and county|"
    r"metropolitan government|metro government)\s+of\s+",
    re.I,
)

# The same governments named the other way round -- "Nashville-Davidson
# metropolitan government", "Athens-Clarke County unified government" --
# which is how Census itself spells them and how a real archived page
# does. Same four roots as `jurisdiction_enrich._GOVERNMENT_TYPE_RE`, the
# closed 10-row-nationally category. Without this the word "metropolitan"
# sends the name to the special_district rule.
CONSOLIDATED_SUFFIX_RE = re.compile(
    r"\b(?:metropolitan|metro|unified|consolidated)(?:\s+government)\b",
    re.I,
)

# "<Entity> of the County of <Place>" -- an entity that has its own name
# in front of a general-purpose government's. Checked before `_RULES`
# because the county rule would otherwise fire on the *tail* and file the
# whole thing as a county: "Housing Authority of the County of Santa
# Clara" (a real archived page, JURISDICTION_METADATA_PLAN.md's own worked
# example) classifies `county` under `govtype.py`'s rules today,
# confirmed by running them 2026-09-02.
#
# The entity half is classified on its own, and only a *non-place* answer
# is taken. That is decision D2's test in regex form: a housing authority
# has its own board, statute and budget, so it is its own government; a
# City Council or a Planning Commission does not, classifies
# municipality/None here, and correctly stays a `meeting_body` of the
# place that follows it.
_ENTITY_OF_PLACE_RE = re.compile(
    r"^(?P<entity>.+?)\s+of\s+(the\s+)?"
    r"(city|county|parish|town|village|borough|township)\s+of\b",
    re.I,
)


def classify_government_type(
    name: Optional[str],
    *,
    place_matched: bool = False,
    country: str = "us",
) -> Optional[str]:
    """The Census-of-Governments type for `name`, or None when the name
    says nothing conclusive.

    `place_matched` -- the bare name matched exactly one national place
    row -- is what makes an unadorned "Artesia" a municipality; without
    it a bare name stays None rather than being guessed at, exactly as
    `govtype.py` has it. None is a real answer here and the resolver
    treats it as "try the general-purpose tables", which is safe because
    a name that would have been a district or a school board would have
    matched a rule.
    """
    if not name or not name.strip():
        return None
    if country == "ca" and _CA_UPPER_TIER_RE.search(name.strip()):
        return COUNTY
    if CONSOLIDATED_RE.match(name.strip()) or CONSOLIDATED_SUFFIX_RE.search(name):
        return MUNICIPALITY
    entity_of_place = _ENTITY_OF_PLACE_RE.match(name.strip())
    if entity_of_place:
        entity = entity_of_place.group("entity")
        for label, pattern in _RULES:
            if pattern.search(entity):
                if label in NON_PLACE_TYPES:
                    return label
                break
    for label, pattern in _RULES:
        if pattern.search(name):
            return label
    if place_matched:
        return MUNICIPALITY
    return None
