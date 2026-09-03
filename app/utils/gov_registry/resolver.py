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
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from ..jurisdiction_enrich import (
    _name_validates_in_state,
    _validated_subdomain_hint_with_state,
    finalize_jurisdiction,
    lookup_by_domain,
    lookup_county_by_zip,
    lookup_place_by_zip,
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
        """The `/j/` slug for this government, or None when it has no hub.

        None for `unresolved` and `blank`, and the distinction is not
        cosmetic. Both tiers still carry a `Government` -- it holds the
        cleaned name and the evidence a human pin needs -- but neither
        has an identity, so neither has a hub, and a caller must fall
        back to the page's own display string instead.

        Returning a slug for them was wrong in a way that only showed up
        downstream: an unresolved "City of Las Vegas" produced
        `city-of-las-vegas` from the raw cleaned name, while the page
        actually lives at `/j/las-vegas` -- `jurisdiction_hub_slug()`
        goes through `format_jurisdiction_display()`, which strips a
        leading "City of ". `crud._hub_identity()` was unaffected (it
        looks the id up in `governments.csv`, misses, and falls back
        correctly), so no page ever moved; but both scripts read this
        property directly, so the backfill's dry-run report and the
        scoring run's merge/split counts credited moves that would not
        happen.
        """
        if not self.gov_id or self.gov_id.startswith("rtr:unknown:"):
            return None
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
        # Derived when `governments.csv` has not got a row yet, which is
        # the normal state for a freshly hand-added pin: that file is a
        # generated snapshot of what some scoring run resolved TO, so a
        # pin to a government no page has reached yet is absent from it
        # by construction. Silently ignoring such a pin is worse than it
        # sounds -- the ladder simply carries on and the host stays
        # wrong, with nothing saying the pin did not apply. Caught by
        # test_every_tenant_override_row_has_a_resolvable_gov_id the
        # moment the landing-page sweep wrote seven of them.
        gov = registry.government_for_id(row.gov_id)
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


# Widened WO-105 (2026-09-03): this already covered village/borough/
# township/municipality (a stale BACKLOG.md/brief claim that it was
# "narrower" than jurisdiction_enrich.py's `_STOPRULE_TRIGGER_RE" turned
# out to be wrong when re-checked against the actual code, per this
# repo's own "verify a backlog entry's claims before building from it"
# rule -- corrected here rather than silently). What was genuinely
# missing: "district of", "regional municipality of", and Ontario's real
# "The Corporation of the {type} of" legal-name convention (left generic
# rather than narrowed to city/town/township, since Ontario municipal
# law uses this phrasing for villages and townships too). Safe to add:
# `_leading_type_word()`'s result only ever narrows an already-ambiguous
# lookup (`_general_purpose_lookup()`/`_ca_csd_disambiguate()`), and a
# "district"/"regional municipality" type_preference matches no real
# Census LSAD word or StatCan `CSD_TYPE_WORDS` value today, so it behaves
# exactly like today's "no type word" case (decline on ambiguity) rather
# than picking a wrong candidate -- purely additive, verified against the
# full test suite. "Regional municipality" is likewise inert on the
# Canadian COUNTY path specifically (a name that reads as one already
# classifies COUNTY via `classify._CA_UPPER_TIER_RE` before
# `type_preference` is ever consulted), so this is groundwork for other
# callers of `_leading_type_word()`, not a behavior change on that rung.
_LEADING_TYPE_RE = re.compile(
    r"^(?:the\s+)?(?:corporation\s+of\s+the\s+)?"
    r"(city|town|village|borough|township|municipality|district|"
    r"regional\s+municipality)\s+of\b",
    re.I,
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


# "City of Sunset Valley, Travis County" -- a place named together with
# the county it sits in. Both real, both archived, and both minted an
# `rtr:` id for a government the place table already holds.
_COUNTY_QUALIFIER_RE = re.compile(
    r",\s*(?P<county>[A-Za-z.'\- ]+\s(?:County|Parish))\s*$", re.I
)


def _strip_county_qualifier(name: str) -> Tuple[str, str]:
    """ "City of Sunset Valley, Travis County" -> ("City of Sunset
    Valley", "Travis County"). The county is *enrichment* -- where the
    government sits -- and never its type or its identity (§2's
    place-is-not-identity rule, applied to a string that names both).

    Deliberately gated on the remaining prefix carrying a municipal type
    word, which both real archived cases do ("City of Sunset Valley,
    Travis County, TX", "Town of Amherst, Erie County, NY" -- the only
    two strings of this shape in the 2026-09-02 export). Without that
    gate the same rule would eat the tail of "Board of Supervisors,
    Fresno County" and resolve a county's page to a body name.
    """
    m = _COUNTY_QUALIFIER_RE.search(name)
    if not m:
        return name, ""
    prefix = name[: m.start()].strip().rstrip(",")
    if not prefix or not _LEADING_TYPE_RE.match(prefix):
        return name, ""
    return prefix, m.group("county").strip()


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


def _ca_csd_disambiguate(name: str, state: str, type_preference: str):
    """The one CSD a name means when several share a normalized key --
    or None, which is still the default answer.

    Two tie-breaks, in order, and only ever consulted after the
    exactly-one rule has already declined, so neither can create an
    ambiguity that was not already there.

    1. **The name itself.** `_normalize_name()` strips a trailing type
       word, which is right for querying and wrong for telling two
       Alberta governments apart: "Leduc County" (a municipal district)
       and "Leduc" (the city) both index under "leduc". They are not one
       name shared by two governments, they are two different names the
       index flattened, and a page that wrote "Leduc" meant the one
       actually called Leduc. Prefer the candidate whose own name matches
       the query with nothing stripped.
    2. **The raw name's municipal type word**, the Canadian counterpart
       of the LSAD tie-break `_general_purpose_lookup()` already does for
       US places. This is the genuine shared-name case: Yarmouth, NS is
       both a town (1202006) and the municipal district around it
       (1202004), so only "Town of Yarmouth" can pick one. Without a type
       word this declines, and a real shared name mints -- which is the
       honest answer.
    """
    rows = tables.ca_csd().lookup_all(name, state)
    if len(rows) < 2:
        return None
    query = tables.squash(_LEADING_ENTITY_PREFIX_RE.sub("", name).strip())
    exact = [r for r in rows if tables.squash(r.name) == query]
    if len(exact) == 1:
        return exact[0]
    candidates = exact if exact else rows
    if not type_preference:
        return None
    matching = [
        r
        for r in candidates
        if tables.CSD_TYPE_WORDS.get(r.type_word.upper()) == type_preference
    ]
    return matching[0] if len(matching) == 1 else None


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


def _stateless_states(name: str, type_preference: str = "") -> set:
    """Every general-purpose government a STATELESS name could mean,
    across all three tables at once.

    The exactly-one rule was applied per table, so a name ambiguous
    *between* tables still resolved. Real: "Town of Hillsborough" on
    `youtu.be` -- a shared host with no tenant state -- became
    `us:cousub:3301136180`, Hillsborough town, **New Hampshire**. There
    are two Hillsborough places (CA and NC), two Hillsborough county
    subdivisions (NH and NJ) and two Hillsborough counties (FL and NH);
    the place table declined because it saw two, the cousub table
    answered because the raw "Town of" narrowed its two to one, and
    nothing ever compared the six against each other.

    **The raw name's own type word narrows the count, exactly as it
    narrows each table's lookup.** Counting without it looks stricter and
    is simply wrong: measured over the 5,053-page export, the unnarrowed
    version declined 74 rows, and roughly 40 of them were right --
    "City of Corona" (one Corona *city*, tied against a same-named
    township), "Town of Herndon" (a documented merge of three hub
    slugs), "City of Burnsville", "City of Palm Springs". Those are not
    ambiguous names; they are names whose ambiguity the type word
    already settles.

    Counties are excluded once a municipal type word is present, for the
    same reason the county fallback is: a page that says "City of" is not
    naming a county.

    **Counted by STATE, not by row**, and that is the whole difference
    between a useful rule and a destructive one. A place and a county
    sharing a name *in the same state* -- Milwaukee, Napa, Fresno -- are
    not a dangerous ambiguity: the page is in that state either way, and
    `_general_purpose_lookup()`'s place-before-county order already
    settles which. Counting them as two candidates declined "Milwaukee.",
    a real stored string whose merge with "Milwaukee, WI" is one of the
    documented Phase 1b wins. What actually goes wrong is landing in the
    WRONG STATE -- Hillsborough NH for a town that is not in New
    Hampshire, Ventura IA for a California city -- so that is what this
    counts.
    """
    out = set()
    for table in (tables.us_places, tables.us_cousubs):
        for row in table().lookup_all(name, None):
            if type_preference and _census_type_word(row.name) != type_preference:
                continue
            out.add(row.state.upper())
    if not type_preference:
        for row in tables.us_counties().lookup_all(name, None):
            out.add(row.state.upper())
    # A curated alias is a human's assertion that this name means this
    # government, so it is a competing candidate like any other -- and
    # for a stateless name it is the one the table cannot see. "City of
    # Ventura" on `www.youtube.com` reached Ventura city, IOWA, because
    # Census names the California city "San Buenaventura (Ventura) city"
    # and the place table therefore keys no "Ventura" in CA at all. One
    # table hit plus one curated assertion is two candidates, not one.
    for key in tables.lookup_keys(name):
        for (scope, alias), gov_id in registry.curated_aliases().items():
            if alias == key and scope:
                out.add(scope.upper())
    return out


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
        hit = tables.ca_csd().lookup(name, state) or _ca_csd_disambiguate(
            name, state, type_preference
        )
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
        if type_preference:
            # A name that SAYS it is a town/city/village may never come
            # back as a census division -- the Canadian half of the same
            # gate the US county table already has. "Town of Yarmouth,
            # NS" resolved to `ca:cd:1202`, the Yarmouth census division,
            # because two CSDs share the name and the exactly-one rule
            # declined; filing a town under its county is the mistake
            # that gate exists to stop, in either country.
            return None
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

    # A stateless general-purpose name must be unique across all three
    # tables together, not merely within whichever one answers first.
    if not state and len(_stateless_states(name, type_preference)) > 1:
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
    if not state and tables.ca_csd().lookup(name, None):
        # A name with no state is looked up NATIONALLY, and "nationally"
        # silently meant "in the United States" -- `country_for_state("")`
        # is "us", so the Canadian tables were never consulted and a name
        # unique in the US table looked unambiguous while a Canadian
        # government of the same name sat unchecked. 16 real rows, and
        # the wrong ones are not subtle: Abbotsford BC filed as
        # Abbotsford WI, Edmonton AB as Edmonton KY, Niagara Falls ON as
        # Niagara Falls NY, Langford and White Rock BC as two South
        # Dakota places, Port Hope ON as Port Hope MI.
        #
        # This is the exactly-one rule applied honestly rather than
        # per-country. Declining costs an `unresolved` row on the pin
        # worklist, which a single landing-page fetch settles; resolving
        # costs a page in the wrong country's hub, which nothing catches.
        # Three of the 16 (Nampa ID, New Carlisle OH, Hawarden IA) are
        # genuinely the US one and are the price -- each has a real
        # Canadian namesake, so the ambiguity is real and a pin is the
        # honest way to break it.
        return None
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
    # ...and neither may a name a CURATED row already claims. "Boise,
    # ID" was landing on Boise County: Census spells the city "Boise City
    # city" so the place lookup misses, and this fallback then answered
    # before rung 4b's curated alias -- the alias that exists for exactly
    # this name -- was ever consulted. "City of Boise, ID" resolved
    # correctly the whole time, because its type word gates this off, so
    # one city had two governments depending on how a page spelled it.
    # Caught by an unrelated hub test, not by this rung's own.
    #
    # A curated alias is checked, not returned, here: returning it would
    # let "Boise County, ID" -- whose trailing type word normalizes away
    # to the same key -- resolve to the city. The county branch above
    # already answered that one; this only declines the FALLBACK.
    hit = (
        None
        if (type_preference or _curated_alias(name, state))
        else tables.us_counties().lookup(name, state)
    )
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


# Widened alongside `_LEADING_TYPE_RE` above, same reasoning and same
# WO-105 pass -- this is the strip-only counterpart (`_mint()`'s slug
# generation, `_ca_csd_disambiguate()`'s exact-name tie-break), so a
# minted "District of Squamish"/"Regional Municipality of Durham" slugs
# to "squamish"/"durham" the same way "City of X" already does, rather
# than carrying its ceremonial prefix into a permanent id.
_LEADING_ENTITY_PREFIX_RE = re.compile(
    r"^(?:the\s+)?(?:corporation\s+of\s+the\s+)?"
    r"(?:city|town|village|borough|township|municipality|district|"
    r"regional\s+municipality)\s+of\s+",
    re.I,
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


_NAME_TOKEN_RE = re.compile(r"[A-Za-z']+")
# A US broadcast callsign: K or W plus 2-3 letters, optionally -TV/-FM/-AM
# /-DT. A municipal access channel's callsign is not the government that
# runs it, and the old wordninja subdomain fallback produced these
# wholesale ("Auroratv" is named in JURISDICTION_METADATA_PLAN.md's own
# tournament as junk output).
_CALLSIGN_RE = re.compile(r"^[kw][a-z]{2,3}(?:[- ]?(?:tv|fm|am|dt))?$", re.I)
# The words for what KIND of government something is. A name made of
# nothing but these is not a name.
_ENTITY_TYPE_WORDS = frozenset(
    {
        "city",
        "town",
        "village",
        "borough",
        "township",
        "municipality",
        "county",
        "parish",
        "region",
        "district",
    }
)
_TRAILING_STATION_RE = re.compile(r"[\s-]*\b(?:tv|fm|am|dt|media|channel)\b\s*$", re.I)


def _looks_like_a_name(name: str) -> bool:
    """Whether a cleaned string is plausibly a government's NAME, and so
    worth minting an `rtr:` id for.

    Minting turns a string into an identity. Doing that for a subdomain
    fragment creates a permanent, authoritative-looking id for something
    nobody can ever look up, and it is not hypothetical -- these are all
    real rows produced by the old wordninja subdomain fallback and still
    stored today: "Llbc, AB" (`pub-llbc`, really Lac La Biche County),
    "Notl, ON" (Niagara-on-the-Lake), "Stjohns, NL", "Ezt", "TV, NY",
    "Psr C 2", "Mw Rd", "S Fw, MD", "Ride Uta".

    Three tests, all of which must pass:

    1. **Some real word.** At least one 4+-letter token appears in
       `tables.name_vocabulary()` -- the words that occur in real
       government names. This is what separates "West County Wastewater
       District" from "Llbc": both are unfamiliar, only one is made of
       words any government uses.
    2. **Not an initialism.** A name whose every token is under 4 letters
       is not a name we can key or a reader can recognise ("Ezt", "Mw
       Rd", "Psr C 2", "TV").
    3. **Not a station callsign.** A channel is not a government.

    A string that fails becomes tier `unresolved`, keeping the raw text in
    `evidence` so it can still be pinned by hand -- the information is
    preserved, it just never becomes an id.
    """
    stripped = _TRAILING_STATION_RE.sub("", name).strip() or name
    tokens = _NAME_TOKEN_RE.findall(stripped)
    if not tokens:
        return False
    if len(tokens) == 1 and _CALLSIGN_RE.match(tokens[0]):
        return False
    long_tokens = [t for t in tokens if len(t) >= 4]
    if not long_tokens:
        return False
    if all(t.lower() in _ENTITY_TYPE_WORDS for t in long_tokens):
        # 4. **Something other than the word for what kind of government
        #    it is.** A string made only of type words names no
        #    government. Real and singular: `allentownpa.granicus.com`
        #    stores "City of Al" -- a truncated "City of Allentown" whose
        #    stray "Al" was then read as the state Alabama by the
        #    bare-suffix rule, leaving the name "City of" and minting
        #    `rtr:us:al:city-of`, displayed as "City of, AL". Every one
        #    of those steps is individually defensible, which is why the
        #    gate has to be on the outcome.
        return False
    vocabulary = tables.name_vocabulary()
    return any(t.lower() in vocabulary for t in long_tokens)


def _with_qualifier(evidence: str, county_qualifier: str) -> str:
    """Record a county the page named alongside its government, so the
    evidence says the county was *seen and set aside* rather than
    silently dropped. It is enrichment, never the identity (§2)."""
    return (
        f"{evidence} (page also named {county_qualifier})"
        if county_qualifier
        else evidence
    )


# Leading noise a page writes in front of a government's name but the
# registry never does: "The City of Milwaukee, WI" and "Milwaukee" are
# one government. Stripped only for the tenant-consistency COMPARISON
# below, never for a lookup key -- `_normalize_candidates()` owns that.
#
# Widened WO-105 (2026-09-03) alongside `_LEADING_TYPE_RE` above, same
# reasoning: `_entity_kind()` returning "" on real text already lets the
# comparison proceed with no type guard at all (see
# `_tenant_consistency()`'s own `if kind and ...` check), so adding a
# word here can only ever ADD a guard where none existed before, never
# remove or weaken one -- confirmed against the full test suite.
_COMPARISON_PREFIX_RE = re.compile(
    r"^(?:the\s+)?(?:corporation\s+of\s+the\s+)?"
    r"(?:city|town|village|borough|township|municipality|county|parish|"
    r"district|regional\s+municipality)"
    r"\s+(?:and\s+(?:county|borough)\s+)?of\s+",
    re.I,
)


_COMPARISON_PREFIX_KIND_RE = re.compile(
    r"^(?:the\s+)?(?:corporation\s+of\s+the\s+)?"
    r"(?P<kind>city|town|village|borough|township|municipality|county|"
    r"parish|district|regional\s+municipality)\s+(?:and\s+(?:county|borough)\s+)?of\s+",
    re.I,
)

# Which `gov_type` an entity prefix is allowed to agree with. A page that
# writes "County of Clark" means a county and a page that writes "City of
# Ashland" does not -- and the two names differ by a word the comparison
# below deliberately strips, so without this the strip would let a city
# collapse into its same-named county. That is the exact Phase 1b bug,
# arriving through the consistency rung instead of the county table.
_KIND_TYPES = {
    "county": {classify.COUNTY},
    "parish": {classify.COUNTY},
    # Canadian upper-tier ("Regional Municipality of Durham" already
    # classifies COUNTY via `classify._CA_UPPER_TIER_RE`, same as "Peel
    # Region"/"County of X" -- see that regex's own comment).
    "regional municipality": {classify.COUNTY},
    "city": {classify.MUNICIPALITY, classify.TOWNSHIP},
    "town": {classify.MUNICIPALITY, classify.TOWNSHIP},
    "village": {classify.MUNICIPALITY, classify.TOWNSHIP},
    "borough": {classify.MUNICIPALITY, classify.TOWNSHIP},
    "township": {classify.MUNICIPALITY, classify.TOWNSHIP},
    "municipality": {classify.MUNICIPALITY, classify.TOWNSHIP},
    # BC's real "District of X" municipalities (North Vancouver, Squamish,
    # Saanich, Sechelt) -- a general-purpose government, same bucket as
    # city/town/village. Kept even though `classify.py`'s SPECIAL_DISTRICT
    # rule currently misfires on the bare word "district" (a separate,
    # logged gap -- see `_STOPRULE_TRIGGER_RE`'s comment in
    # jurisdiction_enrich.py): the tenant's ALREADY-RESOLVED dominant
    # government this compares against may well be correctly typed even
    # when a fresh classification of THIS page's raw name would not be.
    "district": {classify.MUNICIPALITY, classify.TOWNSHIP},
}


def _entity_kind(name: str) -> str:
    """ "County of Clark" -> "county"; "The City of Milwaukee" -> "city";
    a name with no entity prefix -> ""."""
    m = _COMPARISON_PREFIX_KIND_RE.match((name or "").strip())
    return m.group("kind").lower() if m else ""


def _base_name_keys(name: str) -> set:
    """Every comparison key for a name: its entity prefix removed, then
    each of `tables.lookup_keys()`' normalizations with all spacing and
    punctuation squeezed out.

    Three real shapes have to meet in here. "The City of Milwaukee, WI"
    and "Milwaukee" -- a leading phrase the registry never writes.
    "Gales Burg" and "Galesburg" -- a spacing slip. "County of Clark" and
    "Clark County" -- the SAME word, on opposite sides of the name, which
    `lookup_keys()` already knows how to strip because that is how it
    indexes a table in the first place. `_entity_kind()` above is what
    keeps that last strip from also making a city agree with its county.
    """
    stripped = _COMPARISON_PREFIX_KIND_RE.sub("", (name or "").strip())
    keys = {tables.squash(k) for k in tables.lookup_keys(stripped)}
    keys.add(tables.squash(stripped))
    keys.discard("")
    return keys


def is_own_name(candidate: str, match: "GovernmentMatch") -> bool:
    """Whether `candidate` IS the government's name, rather than a string
    that merely contains something the resolver could key on.

    The acceptance rule. It lives here rather than in the script that
    first needed it because two callers now depend on it agreeing with
    itself: `scripts/sweep_tenant_landing_pages.py`, which reads a name
    out of a landing page, and `scripts/build_pin_worklist.py`, which
    guesses one from a hostname or a slug. A pin is the one tier that
    overrides a working extraction, so a rule that drifted between the
    two would be a rule in name only.

    The resolver normalizes hard -- that is its job, and it is what lets
    a real page's "County of Fresno, CA" reach `us:county:06019`. Handed
    a page-title fragment it normalizes just as hard, and 6 of the
    landing-page sweep's first 12 pins were the result:

        'Section View- Live on website'        -> a Minnesota township
        'Fullerton Public - Powered by .com'   -> Fullerton, NEBRASKA
                                                  (the tenant is Fullerton CA)
        'Midland City Council , Summaries &'   -> Midland, ALABAMA
        'Oregon Metro Council - New View'      -> Oregon County, MISSOURI
        'Council'                              -> Council, IDAHO

    The test: the candidate, with any trailing state stripped, must equal
    one of the government's own names (the national table's spelling or
    this repo's display form), compared the same way the tenant-consistency
    rung compares names. It is deliberately strict about the whole name,
    which is what rejects "Howard County Public School System" reaching
    `us:county:24027` -- a real hit on a real government that is not the
    one the signal named.

    It costs real coverage and that is the right trade. Fullerton CA's
    landing page never plainly says "City of Fullerton", so no tool can
    honestly settle that host from it, and the row stays on the worklist
    saying what was found.
    """
    gov = match.government
    if gov is None:
        return False
    bare, _state = _split_state(candidate)
    ours = _base_name_keys(bare)
    theirs = _base_name_keys(gov.gov_name) | _base_name_keys(
        _split_state(display_name(gov))[0]
    )
    return bool(ours & theirs)


def _tenant_consistency(
    tenant_gov_id: Optional[str], name: str, state: str
) -> Optional[Government]:
    """The government this row belongs to according to its own tenant --
    but ONLY when the names agree.

    The rung itself is architecture doc §5's same-tenant consistency
    idea; the guard is what Phase 1b's sheet pre-pass was missing, and it
    over-fired twice in the 2026-09-02 report without it:
    `dcccd.new.swagit.com` (Dallas County Community College District)
    inferred a bleed page reading "City of Dallas" onto Duncanville, and
    `victoria.civicweb.net`'s bare "City of Victoria" onto whatever its
    sibling row had resolved to. Neither is a government this page
    belongs to; both looked resolved.

    Two things must agree, not one:

    * the **base name**, spaces and punctuation stripped -- so "The City
      of Milwaukee, WI" collapses onto Milwaukee and "Gales Burg" onto
      Galesburg, while "City of Dallas" does not collapse onto
      Duncanville;
    * the **state**, when this row has one -- `juneauak.portal.civicclerk.com`
      stores two pages as "Juneau, WI" and one as "Juneau, AK", and the
      names agree perfectly. Adopting the tenant's dominant government
      there would file the City and Borough of Juneau under a Wisconsin
      city on the strength of a spelling.

    With no agreement it does nothing at all, which leaves the row
    `unresolved` and on the list a human works from (§7f).
    """
    if not tenant_gov_id:
        return None
    gov = registry.governments().get(tenant_gov_id)
    if not gov:
        return None
    if state and gov.state and state.upper() != gov.state.upper():
        return None
    kind = _entity_kind(name)
    if kind and gov.gov_type and gov.gov_type not in _KIND_TYPES.get(kind, set()):
        return None
    ours = _base_name_keys(name)
    if not ours:
        return None
    # The registry row's own name, both as the national table spells it
    # ("College Park city", "Winston-Salem city") and as this repo
    # displays it ("College Park, MD") -- the Census generic type word is
    # in one and not the other, and a page writes neither reliably.
    #
    # A GENERATED row's `aliases` are deliberately NOT consulted, for the
    # reason `registry.curated_aliases()` already spells out: on a
    # generated row that column is a *record of what previously resolved
    # here*, so reading it back makes a wrong resolution self-reinforcing.
    # This is not hypothetical -- it fired the first time this guard ran.
    # `governments.csv` still carried "City of Lees Summit" as an alias of
    # Winston-Salem, written by the very unguarded pass this rung exists
    # to replace, and the bleed page collapsed straight back into the
    # wrong hub with the guard reporting that the names agreed. Only a
    # hand-written row's aliases are an assertion rather than an echo.
    theirs = _base_name_keys(gov.gov_name) | _base_name_keys(
        _split_state(display_name(gov))[0]
    )
    if gov.source.startswith(registry.CURATED_SOURCE_PREFIX):
        for alias in gov.aliases:
            theirs |= _base_name_keys(alias)
    return gov if ours & theirs else None


def _squashed_national_hit(
    name: str, state: str, gov_type: Optional[str], country: str, type_preference: str
) -> Optional[Tuple[Government, str, str]]:
    """A national-table row whose name matches once every space and
    hyphen comes off both sides -- tried only when the alternative is
    minting (rung 5c).

    "Gales Burg" is a real archived jurisdiction on
    `galesburg.granicus.com`, sitting beside "Galesburg, IL" on the next
    page. Minting it created a second, permanent id for one government.
    A squashed match is a weaker signal than a real one, so it runs after
    every ordinary lookup has already declined and only with a state in
    hand -- see `tables.NameStateTable.lookup_squashed()`.
    """
    if not state:
        return None
    if gov_type in classify.NON_PLACE_TYPES:
        # The non-place branch has its own rule about which table may
        # answer at all (that is rung 3, the whole LADWP fix), and no
        # measured case wants it loosened. This stays on the
        # general-purpose path.
        return None
    table_choices = []
    if country == "ca":
        # Same shape, one table. Real: `pub-strathroy-caradoc` stores
        # "Strathroy Caradoc" for the Municipality of Strathroy-Caradoc,
        # ON -- one hyphen away from `ca:csd:3539036`.
        table_choices = [(tables.ca_csd(), "ca:csd", classify.MUNICIPALITY)]
    elif gov_type == classify.COUNTY:
        table_choices = [(tables.us_counties(), "us:county", classify.COUNTY)]
    elif gov_type == classify.TOWNSHIP:
        table_choices = [(tables.us_cousubs(), "us:cousub", classify.TOWNSHIP)]
    if not table_choices and country != "ca":
        table_choices = [(tables.us_places(), "us:place", classify.MUNICIPALITY)]
        if not type_preference:
            table_choices.append((tables.us_counties(), "us:county", classify.COUNTY))
    for table, namespace, resolved_type in table_choices:
        hit = table.lookup_squashed(name, state)
        if not hit:
            continue
        return (
            _as_government(
                f"{namespace}:{hit.row_id}",
                hit.name,
                resolved_type,
                country=country,
                state=hit.state,
                place_geoid=hit.row_id if namespace == "us:place" else "",
                county_fips=hit.row_id if namespace == "us:county" else "",
                sgc_code=hit.row_id if namespace == "ca:csd" else "",
                source=f"{namespace} (spacing-insensitive match)",
            ),
            f"{namespace}:{hit.row_id} {hit.name} matched with spacing ignored",
            resolved_type,
        )
    return None


# A name shaped like a county's: "King County", "St. Landry Parish",
# "County of Fresno". Not merely a name CONTAINING the word -- "Los
# Angeles County Metropolitan Transportation Authority" and "Tarrant
# County College District" are agencies that happen to name their county,
# and both are real minted governments that must survive.
_COUNTY_SHAPED_RE = re.compile(
    r"\s(county|parish)$|^(?:the\s+)?(county|parish)\s+of\s", re.I
)


def _is_impossible_county(name: str, state: str, country: str) -> bool:
    """A county-shaped name with no such county in that state.

    Minting one invents a government that cannot exist: US counties are
    exhaustively enumerated, so "King County" in North Carolina is not an
    unlisted government, it is a contradiction. Real, and it reached
    production as a PIN -- `rtr:us:nc:king-county`, minted from the
    ledger's wrong state for `king.granicus.com`, which is really the
    Metropolitan King County Council of King County, WA.

    US only: the Canadian tables are census divisions rather than an
    exhaustive list of upper-tier governments, so absence there is not a
    contradiction.
    """
    if country != "us" or not state or not _COUNTY_SHAPED_RE.search(name):
        return False
    return tables.us_counties().lookup(name, state) is None


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


def page_hints_for(
    platform: Optional[str], external_id: Optional[str]
) -> Dict[str, str]:
    """The `page_hints` dict a caller can build from a `MeetingPage`'s own
    `platform`/`external_id` columns -- WO-105's narrow fix for
    BACKLOG.md's "`resolve_government()`'s `page_hints` argument is never
    passed by anything" entry.

    Before this, `page_hints` was consumed only by `_match_override()`'s
    `key=value` discriminator, and nothing anywhere ever built or passed
    one -- so a `tenant_overrides.csv` row using `match=platform=youtube`
    or similar was dead on arrival however it was written, and WO-103
    nearly shipped 46 pins that depended on exactly that. Both `platform`
    and `external_id` are already real `MeetingPage` columns available at
    both call sites (`archive/db/crud.py`'s `_resolve_page_government()`,
    `scripts/backfill_gov_id.py`) with no schema change needed.

    A `channel` hint for a shared YouTube host (the other real multi-
    government-tenant shape architecture doc §1.5 names, alongside the
    Cottage Grove path-prefix case) is deliberately NOT included here:
    the cheapest lookup this repo has for it,
    `app/platforms/youtube_channel.py`, only offers a full, network-
    fetching channel listing, not a per-video reverse lookup -- adding it
    would mean a real fetch on the ingest/backfill hot path, which is out
    of scope for this pass. Left as a documented gap rather than guessed
    at.
    """
    hints: Dict[str, str] = {}
    if platform:
        hints["platform"] = platform
    if external_id:
        hints["external_id"] = external_id
    return hints


def _resolve_government_ladder(
    raw_name: Optional[str],
    *,
    tenant_host: Optional[str] = None,
    path: Optional[str] = None,
    page_hints: Optional[Dict[str, str]] = None,
    tenant_gov_id: Optional[str] = None,
) -> GovernmentMatch:
    """The seven-rung ladder itself, unchanged by WO-105 -- see
    `resolve_government()` below (the public entry point) for the
    optional `signals`-consuming enhancement pass wrapped around this.

    Resolve one page's government. Pure: no I/O, no writes.

    `raw_name` is whatever the adapter extracted (or the stored
    `jurisdiction`). `tenant_host` is the lowercased netloc -- the same
    key `_KNOWN_DOMAINS`, `jurisdiction_overrides.csv` and
    `tenants.netloc` already use. `path` and `page_hints` are only
    consulted for a tenant that serves more than one government.

    `tenant_gov_id` is the same-tenant consistency rung (5b): the
    dominant `gov_id` among this host's other already-resolved rows. The
    caller supplies it because the caller is the only thing that can see
    the other rows -- `scripts/score_gov_registry.py` computes it as a
    pre-pass over the sheet, and `archive/db/crud.py`'s
    `_tenant_dominant_gov_id()` as a query against `meeting_pages` by
    tenant host. Passing it is always optional, never changes an answer
    the tables already gave, and is adopted only when the two names
    agree -- see `_tenant_consistency()`, which is the guard the Phase 1b
    pre-pass lacked.
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
    name, county_qualifier = _strip_county_qualifier(name)
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
    raw_name, _raw_county = _strip_county_qualifier(raw_name)
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
                    _with_qualifier(
                        f"{evidence} (state {state_evidence})", county_qualifier
                    ),
                    meeting_body,
                )
            alias_hit = _curated_alias(name, tenant_state)
            if alias_hit:
                return _match(
                    alias_hit,
                    TIER_REGISTRY,
                    _with_qualifier(
                        f"governments.csv curated alias (state {state_evidence})",
                        county_qualifier,
                    ),
                    meeting_body,
                )

    # 4. The matching national table -- exactly one match, or nothing.
    hit = _national_lookup(name, state, gov_type, country, type_preference)
    if hit:
        gov, evidence, _resolved_type = hit
        if gov.gov_type == classify.STATE:
            meeting_body = meeting_body or _state_body(name)
        return _match(
            gov,
            TIER_REGISTRY,
            _with_qualifier(evidence, county_qualifier),
            meeting_body,
        )

    # 4b. Curated aliases -- a hand-asserted name for a government whose
    #     Census official name nobody writes. Only `governments.csv` rows
    #     marked `curated` contribute (see `registry.curated_aliases()`
    #     for why a generated row's aliases must never be looked up).
    alias_hit = _curated_alias(name, state)
    if alias_hit:
        return _match(
            alias_hit,
            TIER_REGISTRY,
            _with_qualifier(
                f"governments.csv curated alias {name!r}", county_qualifier
            ),
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
    state_from_tenant = False
    if not state and host:
        tenant_state, state_evidence = _state_from_tenant(host)
        if tenant_state:
            state = tenant_state
            country = tables.country_for_state(state)
            state_from_tenant = True

    # 5b. The same national tables once more, ignoring spacing. Ahead
    #     of the two tenant-derived rungs below, because a table hit is
    #     evidence and a tenant is context: "Gales Burg" should resolve
    #     to Galesburg because that is what the table says, not because
    #     its host happens to agree.
    squashed = _squashed_national_hit(name, state, gov_type, country, type_preference)
    if squashed:
        gov, evidence, _resolved_type = squashed
        return _match(
            gov,
            TIER_REGISTRY,
            _with_qualifier(evidence, county_qualifier),
            meeting_body,
        )

    # 5c. Same-tenant consistency, guarded by name agreement. This row's
    #     tenant already has a dominant government and this row's name is
    #     that government's name written differently, so it belongs to it.
    #     Weaker than a table hit and weaker than a pin, hence its own
    #     tier -- and it does nothing whenever the names disagree, which
    #     is what keeps a bleed page (a "City of Lees Summit" row on
    #     `winston-salem.granicus.com`) out of the wrong hub. See
    #     `_tenant_consistency()` for the two over-fires the guard fixes.
    consistent = _tenant_consistency(tenant_gov_id, name, state)
    if consistent:
        return _match(
            consistent,
            TIER_INFERRED,
            f"tenant {host} resolves to {consistent.gov_id} and the names agree "
            f"({name!r})",
            meeting_body,
        )

    # 5d. A general-purpose name whose ONLY state came from its
    #     tenant, on a tenant whose own government it does not name, is a
    #     bleed page -- not a new government. Left `unresolved` and
    #     listed, never minted.
    #
    #     Real: `winston-salem.granicus.com` stores one page as "City of
    #     Lees Summit". Lee's Summit is in Missouri; the tenant is in
    #     North Carolina; the string matched no NC table row. Minting it
    #     produced `rtr:us:nc:lees-summit` -- a permanent, official-looking
    #     id for a government that does not exist in that state, which is
    #     strictly worse than an honest gap because nothing downstream can
    #     tell it from a real minted district.
    #
    #     Non-place types are exempt, and deliberately: decision D2 says a
    #     housing authority or a water district gets its own minted id
    #     precisely when no national table covers it, and such a name
    #     disagreeing with its host city is the NORMAL case for those, not
    #     evidence of a bleed.
    if (
        tenant_gov_id
        and state_from_tenant
        and gov_type not in classify.NON_PLACE_TYPES
        and registry.governments().get(tenant_gov_id)
    ):
        reason = (
            f"{cleaned!r} names no government on {host}, whose pages resolve to "
            f"{tenant_gov_id}, and its only state came from that tenant"
        )
        return _match(
            Government(
                gov_id="",
                gov_name=name,
                gov_type=gov_type or classify.OTHER,
                country=country,
                source="unresolved",
                evidence=reason,
            ),
            TIER_UNRESOLVED,
            reason,
            meeting_body,
        )

    # 6. Mint -- but only with a real state AND a string that is a name.
    if gov_type == classify.STATE:
        meeting_body = meeting_body or _state_body(name)
        name = _state_name(name)
    if (
        not state
        or not _looks_like_a_name(name)
        or _is_impossible_county(name, state, country)
    ):
        # 7b. Unresolved -- either no state, or a string that is not a
        #     government name at all. Listed for a pin rather than
        #     minted: an id nobody can key is worse than an honest gap,
        #     because it looks resolved. The raw string is kept in
        #     `evidence`, so a human pin still has everything to work
        #     from and no information is lost.
        if not state:
            reason = f"no state for {cleaned!r}"
        elif _is_impossible_county(name, state, country):
            reason = f"no {name!r} in {state} -- counties are exhaustively listed"
        else:
            reason = f"not a government name: {cleaned!r}"
        gov = Government(
            gov_id="",
            gov_name=name,
            gov_type=gov_type or classify.OTHER,
            country=country,
            source="unresolved",
            evidence=reason,
        )
        return _match(gov, TIER_UNRESOLVED, reason, meeting_body)
    gov = _mint(name, state, country, gov_type)
    return _match(gov, TIER_UNVERIFIED, f"minted from {cleaned!r}", meeting_body)


# --- WO-105, 2026-09-03: `signals`-consuming enhancement pass -----------
#
# `app/utils/gov_signals.py`'s `extract_gov_signals()` return shape --
# `org_names`, `zip_codes`, `postal_codes` today (`type_words`/
# `body_names`/`rss_title`/`tld`/`country_words` are extracted and
# scored by `scripts/score_gov_signals.py` but not yet consumed for a
# resolution decision here -- see that script and BACKLOG.md for what's
# left for Step B).
#
# **Design, and why it is a POST-ladder pass rather than threaded through
# every rung**: `_resolve_government_ladder()` above is a long, carefully
# ordered sequence of early returns, each one measured against real data
# (see its own module docstring and every rung's comment). Splicing a
# new input into the MIDDLE of that sequence is exactly how the Phase
# 1/1b/2 sessions introduced real regressions the first time (see
# JURISDICTION_METADATA_PLAN.md's residual-gaps sections) -- each rung
# assumes the ones before it already ran and produced whatever they
# produced. Instead, `signals` is consumed by RE-RUNNING the whole,
# unchanged ladder with a better input (a recovered state/province
# spliced onto the name, or an alternate name candidate) and keeping the
# retry only when it lands somewhere solid (`registry`/`pinned`). This
# guarantees the **hard constraint** this pass was built under: a call
# with no `signals` (every existing caller, unchanged) takes the exact
# same code path as before WO-105, and a call WITH `signals` only ever
# upgrades a `unverified`/`unresolved`/`blank` result -- it can never
# downgrade or change an already-solid one, because the enhancement pass
# is skipped entirely whenever the ladder's own first answer is
# `registry`/`pinned`/`inferred`.
_CA_POSTAL_FIRST_LETTER_PROVINCES: Dict[str, Tuple[str, ...]] = {
    "A": ("NL",),
    "B": ("NS",),
    "C": ("PE",),
    "E": ("NB",),
    "G": ("QC",),
    "H": ("QC",),
    "J": ("QC",),
    "K": ("ON",),
    "L": ("ON",),
    "M": ("ON",),
    "N": ("ON",),
    "P": ("ON",),
    "R": ("MB",),
    "S": ("SK",),
    "T": ("AB",),
    "V": ("BC",),
    "X": ("NT", "NU"),
    "Y": ("YT",),
}


def _signals_recover_state(match: GovernmentMatch, signals: Dict[str, Any]) -> str:
    """A state/province recovered from `signals`, or "".

    Same "impossible pairing" discipline as Bug 2's fix to
    `jurisdiction_enrich.resolve_state()`'s ZIP fallback -- a ZIP or
    Canadian postcode found on the page is only evidence for a state this
    specific government's name can plausibly belong to, checked via the
    same `_name_validates_in_state()` both fixes now share. Tried against
    the ladder's own already-cleaned name (`match.government.gov_name`),
    not the raw page text, since that is the name a human or a table
    would recognise.
    """
    if match.state or not match.government:
        return ""
    name = match.government.gov_name
    if not name:
        return ""
    jurisdiction_type = "county" if match.gov_type == classify.COUNTY else "city"
    zip_lookup = (
        lookup_county_by_zip if jurisdiction_type == "county" else lookup_place_by_zip
    )
    for zip_code in signals.get("zip_codes") or ():
        hit = zip_lookup(zip_code)
        if hit and _name_validates_in_state(name, jurisdiction_type, hit[1]):
            return hit[1]
    for postal in signals.get("postal_codes") or ():
        letter = postal.strip()[:1].upper()
        for province in _CA_POSTAL_FIRST_LETTER_PROVINCES.get(letter, ()):
            if _name_validates_in_state(name, jurisdiction_type, province):
                return province
    return ""


# Duplicated from `scripts/sweep_tenant_landing_pages.py`'s
# `_GENERIC_SINGLE_WORDS` (kept in sync by comment, not by import -- that
# script also filters BEFORE calling `is_own_name()`, the same "reject
# before resolving" shape this needs, so it is easier to keep two closed
# lists honest than to widen `is_own_name()`'s own, narrower contract).
# The real, singular case this exists for: the sweep's first run pinned
# `onelakewood.granicus.com` to Council, IDAHO on the strength of its
# ENTIRE extracted candidate being the bare word "Council" -- a real
# place name (`is_own_name()` correctly says it IS Council, ID's own
# name), just not evidence about THIS government. `org_names` signals
# are noisier than a landing-page title (they include raw page-text
# extractions with no acceptance filtering at all), so the same guard is
# required here, not optional.
_BARE_GENERIC_ORG_NAME_WORDS = frozenset(
    {
        "council",
        "board",
        "commission",
        "committee",
        "government",
        "city",
        "town",
        "village",
        "borough",
        "township",
        "county",
        "district",
        "default",
        "home",
        "live",
        "media",
        "video",
        "archive",
        "public",
        "meeting",
    }
)


def _is_bare_generic_org_name(value: str) -> bool:
    bare, _state = _split_state(value)
    return bare.strip().lower() in _BARE_GENERIC_ORG_NAME_WORDS


def _signals_try_org_names(
    original_match: GovernmentMatch,
    raw_name: Optional[str],
    tenant_host: Optional[str],
    path: Optional[str],
    page_hints: Optional[Dict[str, str]],
    tenant_gov_id: Optional[str],
    signals: Dict[str, Any],
) -> Optional[GovernmentMatch]:
    """The first `org_names` candidate that resolves solidly AND passes
    `is_own_name()` -- the same acceptance test
    `scripts/sweep_tenant_landing_pages.py` learned the hard way it needs
    (its own first run wrote 12 pins, 6 of them wrong, from exactly this
    kind of noisy title-fragment candidate; see that module's docstring).
    `org_names` here is noisier still -- it includes the raw stored
    `jurisdiction` string alongside real extractions -- so the same guard
    applies with no exception.
    """
    original_norm = (raw_name or "").strip().lower()
    for candidate in signals.get("org_names") or ():
        value = candidate.get("value") if isinstance(candidate, dict) else candidate
        if not value or not value.strip():
            continue
        if value.strip().lower() == original_norm:
            continue
        if _is_bare_generic_org_name(value):
            continue
        retry = resolve_government(
            value,
            tenant_host=tenant_host,
            path=path,
            page_hints=page_hints,
            tenant_gov_id=tenant_gov_id,
        )
        if retry.tier in (TIER_REGISTRY, TIER_PINNED) and is_own_name(value, retry):
            return retry
    return None


def resolve_government(
    raw_name: Optional[str],
    *,
    tenant_host: Optional[str] = None,
    path: Optional[str] = None,
    page_hints: Optional[Dict[str, str]] = None,
    tenant_gov_id: Optional[str] = None,
    signals: Optional[Dict[str, Any]] = None,
) -> GovernmentMatch:
    """`_resolve_government_ladder()`, plus an optional enhancement pass
    over `signals` (the `extract_gov_signals()` shape, WO-105) -- see the
    comment block above for the design and the hard constraint it keeps.

    `signals` is None for every caller this repo ships today
    (`archive/db/crud.py`, `scripts/backfill_gov_id.py`) -- only
    `scripts/score_gov_signals.py` passes one, and only for the
    `unresolved`/`unverified`/`blank` corpus it was built to measure.
    Passing `signals={}` behaves identically to passing None (nothing to
    consume).
    """
    match = _resolve_government_ladder(
        raw_name,
        tenant_host=tenant_host,
        path=path,
        page_hints=page_hints,
        tenant_gov_id=tenant_gov_id,
    )
    if not signals or match.tier not in (
        TIER_UNVERIFIED,
        TIER_UNRESOLVED,
        TIER_BLANK,
    ):
        return match

    recovered_state = _signals_recover_state(match, signals)
    if recovered_state:
        retried = resolve_government(
            f"{(raw_name or '').strip()}, {recovered_state}".strip(" ,"),
            tenant_host=tenant_host,
            path=path,
            page_hints=page_hints,
            tenant_gov_id=tenant_gov_id,
        )
        if retried.tier in (TIER_REGISTRY, TIER_PINNED):
            return retried

    org_name_match = _signals_try_org_names(
        match, raw_name, tenant_host, path, page_hints, tenant_gov_id, signals
    )
    if org_name_match:
        return org_name_match

    return match


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
