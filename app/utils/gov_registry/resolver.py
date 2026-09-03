"""`resolve_government()` -- the seven-rung ladder of architecture doc §5,
in that order and no other.

    1. pinned authoritative   tenant_overrides.csv, strength=authoritative
    2. repair the string      finalize_jurisdiction() -- called, not copied
    3. classify the TYPE      before any place lookup (this is the LADWP rung)
    4. national table         exactly one match, or nothing
    5. pinned fallback        tenant_overrides.csv, strength=fallback
    6. mint                   rtr:<country>:<st>:<slug>
    7. blank                  rtr:unknown:<tenant_host>

Rungs 2 and 3 are the two the current pipeline does not have in this
order, and swapping them is the whole fix: today a name is validated
against a *place* table first, so "Los Angeles Department of Water and
Power" finds "Los Angeles" and the page is silently filed under the wrong
government (§1.3, nine measured tenants). Here the name classifies as
`special_district` before any table is consulted, and
`classify.NON_PLACE_TYPES` makes the place tables unreachable from that
branch at all.

`finalize_jurisdiction()` is called rather than reimplemented, and is not
modified: its bleed trim, entity-prefix split, date/nbsp strip and
subdomain cross-check are measured against 649 real archived rows and are
good. This module consumes its output; it does not second-guess it.

Nothing here writes anything, touches a database, or performs a fetch.
"""

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

from ..jurisdiction_enrich import (
    _validated_subdomain_hint_with_state,
    finalize_jurisdiction,
    lookup_by_domain,
)
from . import classify, registry, tables
from .display import display_name, hub_slug, slugify
from .registry import Government, TenantOverride

# `jurisdiction_confidence` is repurposed to hold the tier (§5); these are
# its new values, alongside the existing "manual_override".
TIER_PINNED = "pinned"
TIER_REGISTRY = "registry"
TIER_UNVERIFIED = "unverified"
# The same-tenant consistency rung (5b) -- weaker than a table hit or a
# pin, and named so a Phase 2 backfill can find and re-check these rows.
TIER_INFERRED = "inferred"
# A real government name that could not be keyed and was NOT minted,
# because minting without a state produces an id that fragments rather
# than identifies. These are the rows that want a `tenant_overrides.csv`
# pin.
TIER_UNRESOLVED = "unresolved"
TIER_BLANK = "blank"

_STATE_SUFFIX_RE = re.compile(r",\s*([A-Za-z]{2})\.?\s*$")
# The same suffix without its comma -- "Benicia CA", "Clayton CA", real
# stored values found in the first scoring run. Only ever accepted when
# the two letters are a real state/province abbreviation, so an ordinary
# short last word can't be eaten.
_BARE_STATE_SUFFIX_RE = re.compile(r"\s+([A-Za-z]{2})\.?\s*$")
_VALID_STATE_ABBRS = (
    frozenset(
        {
            "AL",
            "AK",
            "AZ",
            "AR",
            "CA",
            "CO",
            "CT",
            "DE",
            "DC",
            "FL",
            "GA",
            "HI",
            "ID",
            "IL",
            "IN",
            "IA",
            "KS",
            "KY",
            "LA",
            "ME",
            "MD",
            "MA",
            "MI",
            "MN",
            "MS",
            "MO",
            "MT",
            "NE",
            "NV",
            "NH",
            "NJ",
            "NM",
            "NY",
            "NC",
            "ND",
            "OH",
            "OK",
            "OR",
            "PA",
            "RI",
            "SC",
            "SD",
            "TN",
            "TX",
            "UT",
            "VT",
            "VA",
            "WA",
            "WV",
            "WI",
            "WY",
        }
    )
    | tables.CA_PROVINCES
)


@dataclass(frozen=True)
class GovernmentMatch:
    gov_id: str
    gov_name: str
    gov_type: str
    tier: str
    evidence: str
    meeting_body: Optional[str] = None
    country: str = "us"
    state: str = ""
    government: Optional[Government] = None

    @property
    def hub_slug(self) -> Optional[str]:
        return hub_slug(self.government) if self.government else None


def _as_government(
    gov_id: str,
    name: str,
    gov_type: str,
    *,
    country: str,
    state: str,
    place_geoid: str = "",
    county_fips: str = "",
    sgc_code: str = "",
    nces_lea_id: str = "",
    source: str = "",
    evidence: str = "",
) -> Government:
    """A registry row for a government the national tables just produced.

    Prefers the committed `governments.csv` row when one exists -- that is
    where a hand-reviewed name, alias list or evidence note lives, and it
    must win over a freshly-derived one -- and otherwise derives the row
    from the table hit. Deriving is safe because for a national id every
    field is a function of the id.
    """
    existing = registry.governments().get(gov_id)
    if existing:
        return existing
    return Government(
        gov_id=gov_id,
        gov_name=name,
        gov_type=gov_type,
        country=country,
        state=state,
        place_geoid=place_geoid,
        county_fips=county_fips,
        sgc_code=sgc_code,
        nces_lea_id=nces_lea_id,
        source=source,
        evidence=evidence,
    )


def _match_override(
    host: str, path: Optional[str], page_hints: Optional[Dict[str, str]]
) -> List[TenantOverride]:
    """The override rows for `host` whose `match` discriminator is
    satisfied, most specific first.

    A `match` is satisfied when it appears in the path, or when it is a
    `key=value` pair present in the query string or in `page_hints` -- the
    three shapes §4 names (path prefix, `view_id=5`, channel id). A row
    with no `match` always applies.
    """
    rows = registry.tenant_overrides().get(host.lower()) or []
    if not rows:
        return []
    haystack = (path or "").lower()
    hints = {k.lower(): (v or "").lower() for k, v in (page_hints or {}).items()}
    out = []
    for row in rows:
        if row.match is None:
            out.append(row)
            continue
        needle = row.match.lower()
        if needle in haystack:
            out.append(row)
            continue
        if "=" in needle:
            key, _, value = needle.partition("=")
            if hints.get(key) == value:
                out.append(row)
                continue
        elif needle in hints.values():
            out.append(row)
    return out


def _pinned(
    host: str,
    path: Optional[str],
    page_hints: Optional[Dict[str, str]],
    strength: str,
) -> Optional[Tuple[Government, str]]:
    for row in _match_override(host, path, page_hints):
        if row.strength != strength:
            continue
        gov = registry.governments().get(row.gov_id)
        if gov:
            evidence = f"tenant_overrides.csv {host}"
            if row.match:
                evidence += f" match={row.match}"
            if row.source:
                evidence += f" source={row.source}"
            return gov, evidence
        # A pinned gov_id with no `governments.csv` row is a broken
        # registry, not a resolution -- fall through to the ladder rather
        # than returning an id whose name nothing can render.
    return None


def _tenant_host(tenant_host: Optional[str]) -> str:
    if not tenant_host:
        return ""
    host = tenant_host.strip().lower()
    if "//" in host:
        host = urlparse(host).netloc
    return host.split(":")[0]


def _split_state(name: str) -> Tuple[str, str]:
    """ "Fresno County, CA" -> ("Fresno County", "CA"); "Benicia CA" too.

    Trailing punctuation comes off either way. Real stored value found in
    the first scoring run: "Milwaukee." minted `rtr:us:xx:milwaukee`
    while "Milwaukee, WI" keyed to its place -- one government, two hubs,
    over a full stop.
    """
    name = name.strip()
    m = _STATE_SUFFIX_RE.search(name)
    if m:
        return _STATE_SUFFIX_RE.sub("", name).strip().rstrip(".,;:"), m.group(1).upper()
    m = _BARE_STATE_SUFFIX_RE.search(name)
    if m and m.group(1).upper() in _VALID_STATE_ABBRS:
        return (
            _BARE_STATE_SUFFIX_RE.sub("", name).strip().rstrip(".,;:"),
            m.group(1).upper(),
        )
    return name.rstrip(".,;:").strip(), ""


_LEADING_TYPE_RE = re.compile(
    r"^(?:the\s+)?(city|town|village|borough|township|municipality)\s+of\b", re.I
)

# StatCan spells an upper-tier Canadian government by its bare name
# ("Peel", "Durham"), while every real page and subdomain writes it as
# "Peel Region" / "Region of Peel" / "Regional Municipality of Durham"
# (build_jurisdiction_data.py's own comment records both shapes appearing
# live). Stripped before the census-division lookup so the two meet.
_CA_UPPER_TIER_AFFIX_RE = re.compile(
    r"^(?:the\s+)?(?:regional municipality|region|county|regional district)\s+of\s+|"
    r"\s+(?:regional municipality|region|regional district|county)$",
    re.I,
)


def _leading_type_word(name: str) -> str:
    """ "Town of Cottage Grove" -> "town".

    Load-bearing for exactly the case architecture doc §1.5 names: WI's
    Town of Cottage Grove is a county *subdivision* and its Village of
    Cottage Grove is a Census *place* -- two real, distinct governments
    with one name. `finalize_jurisdiction()` strips the "Town of" prefix
    (correctly -- it is a general-purpose enricher and the prefix is
    noise for its purposes), so the raw name is the only place the
    distinction survives.
    """
    m = _LEADING_TYPE_RE.match(name.strip())
    return m.group(1).lower() if m else ""


def _general_purpose_lookup(name: str, state: str, type_preference: str):
    """The place and county-subdivision tables together, with the raw
    name's own type word breaking any tie -- within the place table as
    well as between the two.

    Two real collisions this settles, both found in the 2026-09-02 run:

    - **place vs cousub.** Without the preference, "Town of Cottage
      Grove, WI" and "Village of Cottage Grove, WI" both resolve to the
      village, because places are tried first -- one government
      swallowing another. With it, the town resolves to
      `us:cousub:5502517200` and the village to `us:place:5517175`.
    - **place vs place.** Waukesha WI is a *city* (`5584250`) and a
      *village* (`5584275`), two rows in one table under one normalized
      key, so the exactly-one rule declined and "City of Waukesha, WI"
      fell through to Waukesha County. The raw "City of" settles it.

    With two candidates and NO type word to choose by, this returns
    nothing. Declining is the whole posture of the ladder: minting an
    honest `rtr:` id beats picking the more populous Waukesha.
    """
    # "City and County of San Francisco" -> "San Francisco". The phrase
    # is not one `_normalize_candidates()` strips (its own leading-type
    # regex expects a single type word), and the place table's key is the
    # bare name.
    name = classify.CONSOLIDATED_RE.sub("", name).strip() or name

    places = tables.us_places().lookup_all(name, state)
    if len(places) > 1:
        matching = [p for p in places if _census_type_word(p.name) == type_preference]
        places = matching if len(matching) == 1 else []
    place = places[0] if len(places) == 1 else None

    cousubs = tables.us_cousubs().lookup_all(name, state)
    if type_preference:
        # A cousub is only an answer for a name that says it is one. Real
        # regression caught the moment the county fallback was gated:
        # "City of Santa Clara" stopped becoming Santa Clara County and
        # started becoming `us:cousub:3603365178` -- "Santa Clara TOWN,
        # NY" -- swapping one wrong government for another. A leading
        # "City of" may only ever match a city.
        cousubs = [c for c in cousubs if _census_type_word(c.name) == type_preference]
    elif len(cousubs) > 1:
        cousubs = []
    cousub = cousubs[0] if len(cousubs) == 1 else None

    if type_preference and place and cousub:
        place_word = _census_type_word(place.name)
        cousub_word = _census_type_word(cousub.name)
        if cousub_word == type_preference and place_word != type_preference:
            return None, cousub
        if place_word == type_preference and cousub_word != type_preference:
            return place, None
    return place, cousub


def _consolidated_lookup(name: str, state: str):
    """A consolidated city-county government, looked up among the place
    table's FUNCSTAT "B"/"F" rows only.

    Reached when a name classified `county` misses the county table --
    "Nashville-Davidson County, TN" does, because the county's own name
    is "Davidson County". Census keys the real government as a *place*:
    "Nashville-Davidson metropolitan government (balance)", `4752006`.
    `_normalize_name()` already reduces that to "nashville-davidson"
    (its "(balance)" + government-type-phrase handling, earned by the
    2026-08-15 audit), which is exactly what the query normalizes to.

    Restricted to B/F -- 10 rows nationally -- so this can never become a
    second, unguarded route from a county name into the place table.
    """
    for row in tables.us_places().lookup_all(name, state):
        if row.funcstat in ("B", "F"):
            return row
    return None


def _census_type_word(census_name: str) -> str:
    """The generic type word Census appends to a general-purpose
    government's name: "Cottage Grove village" -> "village"."""
    parts = census_name.rsplit(" ", 1)
    return parts[1].lower() if len(parts) == 2 else ""


def _national_lookup(
    name: str,
    state: str,
    gov_type: Optional[str],
    country: str,
    type_preference: str = "",
) -> Optional[Tuple[Government, str, str]]:
    """(government, tier evidence, resolved gov_type), or None.

    The type decides which table is even consulted. `NON_PLACE_TYPES` is
    the guard rail: a special district, a state body or a court is looked
    up in its own table (or, for special districts, no table at all this
    phase -- decision D3) and NEVER falls through to places/cousubs,
    however place-like its name is.
    """
    if country == "ca":
        if gov_type in (classify.COUNTY,):
            hit = tables.ca_cd().lookup(
                _CA_UPPER_TIER_AFFIX_RE.sub("", name).strip() or name, state
            )
            if hit:
                return (
                    _as_government(
                        f"ca:cd:{hit.row_id}",
                        hit.name,
                        classify.COUNTY,
                        country="ca",
                        state=hit.state,
                        sgc_code=hit.row_id,
                        source="ca_cd.csv",
                    ),
                    f"ca_cd.csv {hit.name}",
                    classify.COUNTY,
                )
            return None
        if gov_type == classify.STATE:
            hit = tables.ca_pr().lookup(name, state)
            if hit:
                return (
                    _as_government(
                        f"ca:pr:{hit.row_id}",
                        hit.name,
                        classify.STATE,
                        country="ca",
                        state=hit.state,
                        sgc_code=hit.row_id,
                        source="ca_pr.csv",
                    ),
                    f"ca_pr.csv {hit.name}",
                    classify.STATE,
                )
            return None
        if gov_type in classify.NON_PLACE_TYPES:
            # Canadian school boards and conservation authorities have no
            # StatCan id -- SGC codes subdivisions and divisions, not
            # boards (decision D4). They mint.
            return None
        hit = tables.ca_csd().lookup(name, state)
        if hit:
            return (
                _as_government(
                    f"ca:csd:{hit.row_id}",
                    hit.name,
                    classify.MUNICIPALITY,
                    country="ca",
                    state=hit.state,
                    sgc_code=hit.row_id,
                    source="ca_csd.csv",
                ),
                f"ca_csd.csv {hit.name}",
                classify.MUNICIPALITY,
            )
        # An upper-tier Canadian government whose name did not read as
        # one ("Peel" bare, say) -- try the census division before giving
        # up, since it is the only other general-purpose level.
        hit = tables.ca_cd().lookup(
            _CA_UPPER_TIER_AFFIX_RE.sub("", name).strip() or name, state
        )
        if hit:
            return (
                _as_government(
                    f"ca:cd:{hit.row_id}",
                    hit.name,
                    classify.COUNTY,
                    country="ca",
                    state=hit.state,
                    sgc_code=hit.row_id,
                    source="ca_cd.csv",
                ),
                f"ca_cd.csv {hit.name}",
                classify.COUNTY,
            )
        return None

    if gov_type == classify.SCHOOL_DISTRICT:
        hit = tables.us_school_districts().lookup(name, state)
        if not hit:
            hit = _school_district_variant(name, state)
        if hit:
            return (
                _as_government(
                    f"us:sd:{hit.row_id}",
                    hit.name,
                    classify.SCHOOL_DISTRICT,
                    country="us",
                    state=hit.state,
                    nces_lea_id=hit.row_id[2:],
                    source="us_school_districts.csv",
                ),
                f"us_school_districts.csv {hit.name} ({hit.type_word})",
                classify.SCHOOL_DISTRICT,
            )
        return None

    if gov_type == classify.STATE:
        hit = tables.us_states().lookup(_state_name(name), state)
        if hit:
            return (
                _as_government(
                    f"us:state:{hit.row_id}",
                    hit.name,
                    classify.STATE,
                    country="us",
                    state=hit.state,
                    source="us_states.csv",
                ),
                f"us_states.csv {hit.name}",
                classify.STATE,
            )
        return None

    if gov_type in classify.NON_PLACE_TYPES:
        # special_district / court: no national identity table exists this
        # phase (D3 keeps the Census of Governments file as enrichment
        # only), so these mint an `rtr:` id. The important part is that
        # they stop here rather than reaching the place table below.
        return None

    if gov_type == classify.COUNTY:
        hit = tables.us_counties().lookup(name, state)
        if hit:
            return (
                _as_government(
                    f"us:county:{hit.row_id}",
                    hit.name,
                    classify.COUNTY,
                    country="us",
                    state=hit.state,
                    county_fips=hit.row_id,
                    source="us_counties.csv",
                ),
                f"us_counties.csv {hit.name}",
                classify.COUNTY,
            )
        consolidated = _consolidated_lookup(name, state)
        if consolidated:
            return (
                _as_government(
                    f"us:place:{consolidated.row_id}",
                    consolidated.name,
                    classify.MUNICIPALITY,
                    country="us",
                    state=consolidated.state,
                    place_geoid=consolidated.row_id,
                    source="us_places.csv",
                ),
                f"us_places.csv {consolidated.name} (consolidated government)",
                classify.MUNICIPALITY,
            )
        return None

    if gov_type == classify.TOWNSHIP:
        hit = tables.us_cousubs().lookup(name, state)
        if hit:
            return _cousub_result(hit)
        return None

    # Unclassified or municipality: the general-purpose tables, in the
    # order the enricher already trusts -- place, then county (a name
    # that says "County" classified above, so this catches only a bare
    # county name), then county subdivision.
    place, cousub = _general_purpose_lookup(name, state, type_preference)
    if place:
        return (
            _as_government(
                f"us:place:{place.row_id}",
                place.name,
                classify.MUNICIPALITY,
                country="us",
                state=place.state,
                place_geoid=place.row_id,
                source="us_places.csv",
            ),
            f"us_places.csv {place.name}",
            classify.MUNICIPALITY,
        )
    # A name that SAYS it is a city/town/village/borough/township may
    # never come back as a county. Seven real stored values did before
    # this gate -- "City of Santa Clara", "City of Riverside", "City of
    # Maricopa", "City of Boise, ID", "City of Waukesha, WI", "City of
    # Greenville", "City of Santa Rosa" -- each because the place lookup
    # missed (an ambiguous bare name, a within-state place collision, or
    # a Census official name like "Boise City city") and this fallback
    # then found the same-named county. Every one of them merged a city's
    # pages into its county's hub, which is worse than not resolving:
    # `/j/santa-clara-county-ca` would have absorbed the City of Santa
    # Clara. When a municipal type word is present and the place tables
    # decline, the honest answer is "unresolved".
    hit = None if type_preference else tables.us_counties().lookup(name, state)
    if hit:
        return (
            _as_government(
                f"us:county:{hit.row_id}",
                hit.name,
                classify.COUNTY,
                country="us",
                state=hit.state,
                county_fips=hit.row_id,
                source="us_counties.csv",
            ),
            f"us_counties.csv {hit.name}",
            classify.COUNTY,
        )
    if cousub:
        return _cousub_result(cousub)
    return None


def _cousub_result(hit) -> Tuple[Government, str, str]:
    return (
        _as_government(
            f"us:cousub:{hit.row_id}",
            hit.name,
            classify.TOWNSHIP,
            country="us",
            state=hit.state,
            source="us_cousubs.csv",
        ),
        f"us_cousubs.csv {hit.name}",
        classify.TOWNSHIP,
    )


_SCHOOL_SUFFIX_STRIP_RE = re.compile(
    r"\b(board of education|school board|public schools|schools)\b", re.I
)


def _school_district_variant(name: str, state: str):
    """The suffix variants `govtype.nces_district_id()` already tries,
    kept because Census's own spelling of a district is frequently not
    the page's: "Broward County Public Schools" is
    "Broward County School District" in the Gazetteer (confirmed by
    grepping it), "Manatee County Schools" is "Manatee County School
    District". Same shape and order as the feed's version, including its
    prefix tier for the "Lake Oswego School District" / "...District 7J"
    family.

    "public schools" is stripped ahead of the bare "schools" so
    "Broward County Public Schools" reduces to "Broward County" rather
    than the dead end "Broward County Public" -- the regex alternation is
    ordered longest-first for exactly that reason.
    """
    table = tables.us_school_districts()
    base = _SCHOOL_SUFFIX_STRIP_RE.sub("", name).strip(" ,-")
    candidates = [
        base,
        f"{base} School District",
        f"{base} Unified School District",
    ]
    if re.search(r"\busd\b", base, re.I):
        candidates.append(
            re.sub(r"\busd\b", "Unified School District", base, flags=re.I)
        )
    for candidate in candidates:
        if not candidate:
            continue
        hit = table.lookup(candidate, state)
        if hit:
            return hit
    return _school_district_prefix(base, state)


def _school_district_prefix(base: str, state: str):
    """One district in `state` whose name starts with `base` -- and only
    if there is exactly one. The feed's own last tier, for the case where
    the Gazetteer carries a numeric suffix the page never writes."""
    if not base or not state:
        return None
    table = tables.us_school_districts()
    prefix = base.strip().lower()
    hits = {
        row.row_id: row
        for row in table._by_id.values()
        if row.state.upper() == state.upper() and row.name.lower().startswith(prefix)
    }
    return next(iter(hits.values())) if len(hits) == 1 else None


_STATE_BODY_RE = re.compile(
    r"^(state of|commonwealth of)\s+|"
    r"\s+(state\s+)?(senate|assembly|legislature|general assembly|house of "
    r"representatives|house of delegates|state house)$",
    re.I,
)


def _state_name(name: str) -> str:
    """ "Minnesota Senate" -> "Minnesota"; "State of California" ->
    "California". D1: one government per state, the chamber is the body."""
    return _STATE_BODY_RE.sub("", name.strip()).strip(" ,-") or name


def _state_body(name: str) -> Optional[str]:
    """The chamber/agency half of a state-level name, which becomes
    `meeting_body` rather than part of the identity (D1)."""
    stripped = _state_name(name)
    if stripped and stripped != name.strip():
        remainder = name.strip()
        if remainder.lower().startswith(("state of ", "commonwealth of ")):
            return None
        body = remainder[len(stripped) :].strip(" ,-")
        return body or None
    return None


_LEADING_ENTITY_PREFIX_RE = re.compile(
    r"^(?:the\s+)?(?:city|town|village|borough|township|municipality)\s+of\s+", re.I
)

_GENERAL_PURPOSE_TYPES = frozenset(
    {classify.MUNICIPALITY, classify.COUNTY, classify.TOWNSHIP}
)


def _fallback_contradicts_type(gov: Government, raw_type: Optional[str]) -> bool:
    """True when a `fallback` pin would file a classified non-place
    government under a general-purpose one -- the thing rung 3 exists to
    prevent, arriving through the override table instead of the place
    table."""
    return raw_type in classify.NON_PLACE_TYPES and gov.gov_type in (
        _GENERAL_PURPOSE_TYPES
    )


def _state_from_tenant(host: str) -> Tuple[str, str]:
    """(state, evidence) recovered from the tenant alone, or ("", "").

    Three sources, strongest first, all of which already exist and are
    already trusted elsewhere in this estate:

    1. `_validated_subdomain_hint_with_state()` -- the enricher's own
       Census-validated subdomain reading, which declines rather than
       guessing (that is what made it beat the shipped wordninja
       fallback in the 2026-08-15 tournament, 416 hits with zero garbage
       against 408 with 229).
    2. `lookup_by_domain()` -- `_KNOWN_DOMAINS`, 112 hand-verified rows.
    3. `tenant_hints.csv` -- rtr-discovery's learned `tenants.state_abbr`
       and the state implied by its `jurisdiction_override`. Machine-
       derived and last, and deliberately state-only: those override
       values include "S Fw, MD" and "Psr C 2", which are useless as
       government names and still correct about the state.
    """
    if not host:
        return "", ""
    hit = _validated_subdomain_hint_with_state(host)
    if hit and hit[1]:
        return hit[1].upper(), f"from subdomain {host}"
    known = lookup_by_domain(host)
    if known and known.state:
        return known.state.upper(), f"from _KNOWN_DOMAINS {host}"
    hinted = registry.tenant_hints().get(host)
    if hinted:
        return hinted.upper(), f"from tenant_hints.csv {host}"
    return "", ""


def _curated_alias(name: str, state: str) -> Optional[Government]:
    """The government a hand-curated alias names, or None.

    Five real Census official-name shapes no page ever writes, all
    confirmed by grepping `us_places.csv` on 2026-09-02: Boise is
    "Boise City city" (its legal name is City of Boise City), Louisville
    is "Louisville/Jefferson County metro government (balance)",
    Nashville is "Nashville-Davidson metropolitan government (balance)",
    Bainbridge WA is "Bainbridge Island city". Each is a lookup a rule
    cannot make -- there is nothing general to infer, the name simply
    differs -- which is what the curated tier is for.

    Tried with the state first, then stateless, so a curated row with no
    state can still answer a query that has none.
    """
    aliases = registry.curated_aliases()
    for key in tables.lookup_keys(name):
        for scope in ((state or "").upper(), ""):
            gov_id = aliases.get((scope, key))
            if gov_id:
                gov = registry.governments().get(gov_id)
                if gov:
                    return gov
    return None


def _mint(name: str, state: str, country: str, gov_type: Optional[str]) -> Government:
    """`rtr:<country>:<st>:<slug>` -- tier `unverified`, display = the
    cleaned name.

    Deliberately NOT a placeholder: architecture doc §5 rung 6 argues
    against ever showing one when a real name is in hand, and
    JURISDICTION_METADATA_PLAN.md made the same call keeping
    `jurisdiction_confidence` off the UI. "West County Wastewater
    District, CA" is correct and readable; a badge would mislead.

    The *slug* drops a leading "City of "/"Town of " even though the
    display name keeps it, so "City of Easton" and "Easton" mint one
    government rather than two. Measured, not assumed: 355 of the first
    scoring run's 1,198 minted rows carried such a prefix, and three of
    its splits (`/j/easton`, `/j/portage`, `/j/hamilton`) were nothing but
    this. Safe because minting only happens when the name matched no
    table at all, so there is no evidence anywhere that a "City of X" and
    an "X" here are two different governments -- and the raw string is
    kept as an alias either way.
    """
    slug = slugify(_LEADING_ENTITY_PREFIX_RE.sub("", name).strip() or name) or "unnamed"
    scope = (state or "xx").lower()
    return Government(
        gov_id=f"rtr:{country}:{scope}:{slug}",
        gov_name=name,
        gov_type=gov_type or classify.OTHER,
        country=country,
        state=state,
        source="minted",
        evidence="no national table covers this government",
    )


def resolve_government(
    raw_name: Optional[str],
    *,
    tenant_host: Optional[str] = None,
    path: Optional[str] = None,
    page_hints: Optional[Dict[str, str]] = None,
    tenant_gov_id: Optional[str] = None,
) -> GovernmentMatch:
    """Resolve one page's government. Pure: no I/O, no writes.

    `raw_name` is whatever the adapter extracted (or the stored
    `jurisdiction`). `tenant_host` is the lowercased netloc -- the same
    key `_KNOWN_DOMAINS`, `jurisdiction_overrides.csv` and
    `tenants.netloc` already use. `path` and `page_hints` are only
    consulted for a tenant that serves more than one government.

    `tenant_gov_id` is the same-tenant consistency rung (5b): the one
    `gov_id` every OTHER already-resolved row for this host agrees on.
    The caller supplies it because the caller is the only thing that can
    see the other rows -- `scripts/score_gov_registry.py` computes it as
    a pre-pass over the sheet, and in Phase 2 it becomes a query against
    `meeting_pages` by host. Passing it is always optional and never
    changes an answer the tables already gave.
    """
    host = _tenant_host(tenant_host)

    # 1. Pinned, authoritative.
    if host:
        pinned = _pinned(host, path, page_hints, "authoritative")
        if pinned:
            gov, evidence = pinned
            return _match(gov, TIER_PINNED, evidence, None)

    # 2. Repair the string. Called, not copied -- and the netloc goes with
    #    it so the subdomain cross-check runs exactly as it does at ingest.
    finalized = finalize_jurisdiction(raw_name, netloc=host or None)
    cleaned = (finalized.jurisdiction or "").strip()
    meeting_body = finalized.meeting_body

    if not cleaned:
        fallback = _pinned(host, path, page_hints, "fallback") if host else None
        if fallback:
            gov, evidence = fallback
            return _match(gov, TIER_PINNED, evidence, meeting_body)
        gov = Government(
            gov_id=f"rtr:unknown:{host}" if host else "rtr:unknown:",
            gov_name="",
            gov_type=classify.OTHER,
            source="blank",
            evidence="no jurisdiction extracted and no override for this host",
        )
        return _match(gov, TIER_BLANK, "nothing extracted", meeting_body)

    name, state = _split_state(cleaned)
    country = tables.country_for_state(state)

    # 3. Classify the TYPE, before any place lookup.
    #
    # On the RAW name as well as the repaired one, and the raw answer
    # wins when it is a non-place type. Rung 2 is a *place*-oriented
    # repair -- that is what it is for and it is good at it -- so by the
    # time it is done, "Los Angeles Department of Water and Power" has
    # already become "Los Angeles" and the evidence rung 3 needs is gone.
    # Classifying only the cleaned name would reproduce §1.3's exact bug
    # inside the thing built to fix it (verified: it did, on the first
    # run of this resolver). `finalize_jurisdiction()` itself is
    # untouched -- this decides which of its two outputs is the
    # *identity*, and leaves its repaired name available for everything
    # else.
    raw_name, raw_state = _split_state((raw_name or "").strip())
    state = state or raw_state
    country = tables.country_for_state(state)
    raw_type = classify.classify_government_type(raw_name, country=country)
    if raw_type in classify.NON_PLACE_TYPES:
        # The entity IS the government (decision D2: when in doubt,
        # separate, then relate), so a body split off it would be
        # double-counting the same name.
        name, gov_type, meeting_body = raw_name, raw_type, None
        type_preference = ""
    else:
        gov_type = classify.classify_government_type(name, country=country)
        type_preference = _leading_type_word(raw_name)

    # 3b. Recover the state from the tenant BEFORE looking anything up.
    #
    #     Not merely before minting: a stateless name is looked up
    #     *nationally*, where the place table is often ambiguous while the
    #     county table is not, so the general-purpose fallback lands on a
    #     county that is unique for the wrong reason. Two real cases, both
    #     from `riversideca.granicus.com` -- ONE tenant -- in the
    #     2026-09-02 run: "City of Riverside" resolved to
    #     `us:place:0662000` and a bare "Riverside" on the very next page
    #     to `us:county:06065`, because "Riverside" matches three CA
    #     places' worth of ambiguity nationally and exactly one county.
    #     With CA supplied first, the place table has exactly one
    #     Riverside and both pages agree.
    #
    #     The state-constrained lookup is tried first and the stateless
    #     one still runs if it misses, so a wrong hint can only ever cost
    #     a decline, never a wrong answer.
    state_evidence = ""
    if not state and host:
        tenant_state, state_evidence = _state_from_tenant(host)
        if tenant_state:
            tenant_country = tables.country_for_state(tenant_state)
            hit = _national_lookup(
                name, tenant_state, gov_type, tenant_country, type_preference
            )
            if hit:
                gov, evidence, _t = hit
                state, country = tenant_state, tenant_country
                if gov.gov_type == classify.STATE:
                    meeting_body = meeting_body or _state_body(name)
                return _match(
                    gov,
                    TIER_REGISTRY,
                    f"{evidence} (state {state_evidence})",
                    meeting_body,
                )
            alias_hit = _curated_alias(name, tenant_state)
            if alias_hit:
                return _match(
                    alias_hit,
                    TIER_REGISTRY,
                    f"governments.csv curated alias (state {state_evidence})",
                    meeting_body,
                )

    # 4. The matching national table -- exactly one match, or nothing.
    hit = _national_lookup(name, state, gov_type, country, type_preference)
    if hit:
        gov, evidence, _resolved_type = hit
        if gov.gov_type == classify.STATE:
            meeting_body = meeting_body or _state_body(name)
        return _match(gov, TIER_REGISTRY, evidence, meeting_body)

    # 4b. Curated aliases -- a hand-asserted name for a government whose
    #     Census official name nobody writes. Only `governments.csv` rows
    #     marked `curated` contribute (see `registry.curated_aliases()`
    #     for why a generated row's aliases must never be looked up).
    alias_hit = _curated_alias(name, state)
    if alias_hit:
        return _match(
            alias_hit,
            TIER_REGISTRY,
            f"governments.csv curated alias {name!r}",
            meeting_body,
        )

    # 5. Pinned fallback -- the ladder produced nothing keyable.
    if host:
        fallback = _pinned(host, path, page_hints, "fallback")
        if fallback:
            gov, evidence = fallback
            if _fallback_contradicts_type(gov, raw_type):
                # A `fallback` pin may not do what rung 3 forbids. Real
                # and caught by a test on the first seeded run:
                # `tccd.granicus.com`'s auto-derived override says
                # "Tarrant County, TX", so pinning Tarrant County College
                # District to the county would re-import §1.3's exact bug
                # through a different door. The tier that is allowed to
                # override a classified name is `authoritative`, which is
                # hand-verified and evidence-backed by construction;
                # `fallback` is mostly machine-derived and is not.
                pass
            else:
                return _match(gov, TIER_PINNED, evidence, meeting_body)

    # 5a. Adopt the tenant's state for minting, even though no table
    #     matched with it. An id whose state segment is "xx" is not an
    #     identity -- it fragments on contact with the same government
    #     named with its state ("City of Easton" and "Easton, PA" would be
    #     two governments), and 624 of the Phase 1 run's rows carried one.
    if not state and host:
        tenant_state, state_evidence = _state_from_tenant(host)
        if tenant_state:
            state = tenant_state
            country = tables.country_for_state(state)

    # 5b. Same-tenant consistency. Every other resolved row for this host
    #     agrees on one government, so this row belongs to it too. Weaker
    #     than a table hit and weaker than a pin, hence its own tier.
    if tenant_gov_id and not state:
        gov = registry.governments().get(tenant_gov_id)
        if gov:
            return _match(
                gov,
                TIER_INFERRED,
                f"every other resolved row for {host} agrees on {tenant_gov_id}",
                meeting_body,
            )

    # 6. Mint -- but only with a real state.
    if gov_type == classify.STATE:
        meeting_body = meeting_body or _state_body(name)
        name = _state_name(name)
    if not state:
        # 7b. Unresolved: a real name, no state, nothing else to go on.
        #     Listed for a pin rather than minted, because an id nobody
        #     can key is worse than an honest gap -- it looks resolved.
        gov = Government(
            gov_id="",
            gov_name=name,
            gov_type=gov_type or classify.OTHER,
            country=country,
            source="unresolved",
            evidence="no state could be determined for this name",
        )
        return _match(gov, TIER_UNRESOLVED, f"no state for {cleaned!r}", meeting_body)
    gov = _mint(name, state, country, gov_type)
    return _match(gov, TIER_UNVERIFIED, f"minted from {cleaned!r}", meeting_body)


def _match(
    gov: Government, tier: str, evidence: str, meeting_body: Optional[str]
) -> GovernmentMatch:
    return GovernmentMatch(
        gov_id=gov.gov_id,
        gov_name=display_name(gov),
        gov_type=gov.gov_type,
        tier=tier,
        evidence=evidence,
        meeting_body=meeting_body,
        country=gov.country,
        state=gov.state,
        government=gov,
    )
