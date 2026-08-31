"""Shared "fill in a missing state" enrichment for adapters that extract a
real jurisdiction *name* from page text but have no state anywhere to go
with it -- confirmed the real bulk of the no-state gap (Granicus, Legistar,
PrimeGov, eScribe, CivicWeb, LIMS all extract free text with no structured
state field, see BACKLOG.md's "no-state jurisdiction audit"). Deliberately
centralized here rather than duplicated per-adapter, per the user's own
call: a city/county name lookup only needs the name already extracted (no
raw page access required), so it can live in one shared place every
adapter calls into, instead of each adapter reinventing its own lookup.

Reference data (app/utils/jurisdiction_data/*.csv) is real US Census
Bureau Gazetteer/relationship data -- public domain (17 U.S.C. Section
105), regenerated via scripts/build_jurisdiction_data.py, not hand-curated.
Four tables:
  - counties.csv / places.csv: every real US county and incorporated
    place, name + state. Deliberately NOT deduplicated by name -- 422 real
    county names and 2,243 real place names collide across multiple
    states (e.g. "Washington County" exists in 30+ states; "Detroit" is a
    real city in MI, OR, AL, *and* TX). A bare name lookup only ever
    resolves when the name is unique nationally; an ambiguous name
    returns None rather than guessing. places.csv also carries 5,028 real
    Canadian census subdivisions (city/town/township-level governments,
    added 2026-08-17 -- BACKLOG.md's "Jurisdiction-bleed, confirmed
    cross-platform" entry), sourced from Statistics Canada's own Standard
    Geographical Classification, merged into the SAME file/table rather
    than a separate one -- see scripts/build_jurisdiction_data.py's
    build_canada_places() for the source URL and why one merged table.
    Confirmed real US/Canada name collisions exist ("St. Paul" -- both a
    real Minnesota city and a real Alberta town) and correctly resolve to
    `None` via the same ambiguity-safety as any other collision, no new
    code needed for that.
  - zcta_county.csv / zcta_place.csv: which county/place(s) a ZIP
    (technically a ZCTA, the Census's ZIP proxy) overlaps, with the real
    overlap area (AREALAND_PART) for tie-breaking -- 30% of ZCTAs
    genuinely span more than one county (and, separately, more than one
    place), confirmed against the real data, not assumed. ZCTAs spanning
    more than one *state* are rare (0.4%, also confirmed against real
    data) but not zero.

The real trap this module is built to avoid (see BACKLOG.md/the
conversation this was designed in): a government office's own mailing
address almost always resolves, via ZIP, to whichever *city* physically
contains it -- even when the real jurisdiction is the surrounding
*county*. A county government headquartered in its county seat will
always have a city-shaped address, never a "county" one, because ZIP
codes are a postal construct with no concept of county government at all.
So a ZIP found in page text is looked up against the SAME type
(county-vs-city) the caller already determined from real page-text
keywords ("County"/"Parish"/"Board of Supervisors" vs. "City of"/"Town
of") -- never used to override or guess that type itself. Getting this
backwards would silently downgrade a real county government to one city
inside it, which is worse than the missing-state gap this module exists
to close.
"""

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

_DATA_DIR = Path(__file__).parent / "jurisdiction_data"

_LEADING_TYPE_RE = re.compile(
    r"^(?:city|county|town|township|village|borough|parish)\s+of\s+", re.IGNORECASE
)
_TRAILING_TYPE_RE = re.compile(
    r"\s+(?:county|parish|borough|city|town|village|township|municipality|municipio)$",
    re.IGNORECASE,
)
# Real consolidated city-county governments -- confirmed against the
# actual 2024 Census Gazetteer file 2026-08-15 (see
# build_jurisdiction_data.py's build_places() comment for the full FUNCSTAT
# story), stored under Census's own "(balance)" statistical-area naming,
# e.g. "Nashville-Davidson metropolitan government (balance)". Neither
# piece is a plain type-word _TRAILING_TYPE_RE already knows -- stripped
# first, in this order (parenthetical, then the government-type phrase),
# so "Nashville-Davidson metropolitan government (balance)" normalizes to
# "nashville-davidson", matching how a real page actually refers to it.
# Only 8 real rows nationally use this shape (confirmed via the same
# Gazetteer file), so this is a closed, verified list, not a guess at a
# general pattern.
_BALANCE_SUFFIX_RE = re.compile(r"\s*\(balance\)\s*$", re.IGNORECASE)
_GOVERNMENT_TYPE_RE = re.compile(
    r"\s+(?:metropolitan government|metro government|unified government|consolidated government)$",
    re.IGNORECASE,
)

# Query-side counterpart to `_GOVERNMENT_TYPE_RE` above -- a real archived
# page names a consolidated government in a shorter, less formal shape
# than Census's own canonical "(balance)" row does, so a query needs its
# own, more tolerant strip rather than reusing `_GOVERNMENT_TYPE_RE`
# as-is. Confirmed real 2026-08-17 via the bleed-backfill-candidates
# audit: a real archived jurisdiction reads "Louisville / Jefferson
# County Metro" -- bare "Metro", no "Government" -- against the stored
# key "louisville/jefferson county" (see `_normalize_name()` above for
# how that key was produced from the Census row). Deliberately strips
# only a BARE trailing government-type word (the same four roots
# `_GOVERNMENT_TYPE_RE` knows, "government" now optional), not a general
# pattern -- this is still the same closed, 8-row-nationally category,
# just tolerating one more real-world spelling of it.
_QUERY_GOVERNMENT_TYPE_RE = re.compile(
    r"\s+(?:metropolitan|metro|unified|consolidated)(?:\s+government)?$",
    re.IGNORECASE,
)
# Collapses a spaced slash ("Louisville / Jefferson County") to the
# unspaced form the Census key uses ("Louisville/Jefferson County") --
# Louisville/Jefferson is the only one of the 8 real consolidated-
# government rows that uses "/" as its name separator at all (the rest
# use "-"), so this only ever matters for that one real category, but
# the normalization itself (collapsing incidental whitespace around a
# slash) is safe generally.
_SLASH_SPACING_RE = re.compile(r"\s*/\s*")


def _normalize_slash_spacing(name: str) -> str:
    return _SLASH_SPACING_RE.sub("/", name)


def _normalize_name(name: str) -> str:
    """Strips a leading "City of "/"County of "/etc. and lowercases --
    used for the stored Census data (see `_load_name_state_table()`),
    where the trailing word is always Census's own guaranteed single
    generic type annotation (e.g. "Abbeville city", "Oklahoma City city"
    -- the real proper name followed by exactly one lowercase type word),
    safe to strip unconditionally. Also strips a trailing "(balance)" +
    government-type phrase first, when present -- see
    `_BALANCE_SUFFIX_RE`'s comment.

    NOT used directly on query-side text -- see `_normalize_candidates()`
    below for why a bare query needs a different, two-attempt strategy.
    """
    name = name.strip()
    name = _BALANCE_SUFFIX_RE.sub("", name)
    name, government_stripped = _GOVERNMENT_TYPE_RE.subn("", name)
    if government_stripped:
        # The government-type phrase ("unified government" etc.) IS the
        # generic type annotation here -- stop, don't also run the plain
        # city/county/etc. strip below. Real bug caught 2026-08-15 testing
        # this against "Greeley County unified government (balance)": a
        # second blind strip turned "Greeley County" into "greeley",
        # colliding with three unrelated real cities named Greeley
        # (CO/IA/KS) and making an otherwise-unambiguous county lookup
        # falsely ambiguous. "County" here is part of what's actually
        # being named (a *county* consolidated government, distinct from
        # any city of the same root name), the same real-word-that-looks-
        # generic trap already noted below for "Oklahoma City"/"Carson
        # City" -- not safe to strip just because it's a known type word.
        return name.strip().lower()
    leading_match = _LEADING_TYPE_RE.match(name)
    if leading_match:
        name = name[leading_match.end() :]
    else:
        name = _TRAILING_TYPE_RE.sub("", name)
    return name.strip().lower()


def _normalize_candidates(name: str) -> List[str]:
    """Query-side normalization -- returns ordered candidate keys to try
    against a lookup table, stopping at the first one that's actually
    present (see `lookup_county_state()`/`lookup_city_state()`).

    Real bug fixed 2026-08-12: a single unconditional strip (leading OR
    trailing, never both -- `_normalize_name()`'s own original fix)
    still broke on a *bare* query with no leading qualifier: "Oklahoma
    City" (no "City of" prefix) has no leading match, so it fell to an
    unconditional trailing strip, losing the "City" that's genuinely part
    of the real proper name (Oklahoma City, Carson City, Jersey City,
    Rapid City -- a common real pattern) and landing on the wrong key
    "oklahoma", which collided with a real, different place ("Oklahoma
    borough, PA"). Fixed by trying the *unstripped* lowercased form
    first -- which already matches correctly here, since the stored
    table's own key for "Oklahoma City city" is "oklahoma city" (Census's
    single generic trailing annotation stripped, same as
    `_normalize_name()` does), identical to the bare query's own
    lowercased form with nothing stripped at all. Only falls back to a
    trailing-stripped candidate ("Sonoma County" -> "sonoma") when the
    unstripped form isn't a real key anywhere. A leading "X of " prefix,
    when present, is unambiguous and still only ever produces one
    candidate -- see `_normalize_name()`.
    """
    name = name.strip()
    leading_match = _LEADING_TYPE_RE.match(name)
    if leading_match:
        return [name[leading_match.end() :].strip().lower()]
    as_is = name.lower()
    stripped = _TRAILING_TYPE_RE.sub("", name).strip().lower()
    return [as_is] if stripped == as_is else [as_is, stripped]


# A Census/StatsCan name carrying a real alternate name in parentheses --
# e.g. "San Buenaventura (Ventura) city,CA" and "El Paso de Robles (Paso
# Robles) city,CA" (both confirmed by grepping places.csv directly,
# 2026-08-23). Without indexing the alternate, "Ventura" only ever
# matched the tiny Ventura, IA and "Paso Robles" matched nothing at all
# -- the first produced two real production rows stored as "City of
# Ventura, IA" for California's Ventura city/county (see BACKLOG_DONE.md,
# jurisdiction data-quality pass), the second is BACKLOG.md's own
# "Lloydminster/Paso Robles missing from the table" finding. NOT every
# parenthetical is a name: Census also writes "(Part)", "(balance)",
# "(North Half)" and numbered reserve fragments, which must not become
# lookup keys -- filtered by `_PAREN_JUNK_RE` (a word filter plus any
# digit) rather than a curated row list, since the junk shapes are
# structural, not per-row.
_PAREN_ALT_RE = re.compile(
    r"^(?P<outer>[^()]*\S)\s*\((?P<alt>[^()]+)\)(?P<tail>[^()]*)$"
)
_PAREN_JUNK_RE = re.compile(r"\b(?:part|balance|half)\b|\d", re.IGNORECASE)


def _load_name_state_table(filename: str) -> Dict[str, List[str]]:
    table: Dict[str, List[str]] = {}
    path = _DATA_DIR / filename
    if not path.exists():
        return table

    def _add(key: str, state: str) -> None:
        if key and state not in table.setdefault(key, []):
            table[key].append(state)

    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            _add(_normalize_name(row["name"]), row["state"])
            if "(" in row["name"]:
                m = _PAREN_ALT_RE.match(row["name"].strip())
                if m and not _PAREN_JUNK_RE.search(m.group("alt")):
                    tail = m.group("tail")
                    _add(_normalize_name(f"{m.group('outer')}{tail}"), row["state"])
                    _add(_normalize_name(f"{m.group('alt')}{tail}"), row["state"])
    return table


def _load_zcta_table(
    filename: str, name_column: str
) -> Dict[str, List[Tuple[str, str, int]]]:
    table: Dict[str, List[Tuple[str, str, int]]] = {}
    path = _DATA_DIR / filename
    if not path.exists():
        return table
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            table.setdefault(row["zcta"], []).append(
                (row[name_column], row["state"], int(row["area_land_part"] or 0))
            )
    return table


_COUNTY_STATES = _load_name_state_table("counties.csv")


def _load_county_type_words(filename: str) -> Dict[Tuple[str, str], str]:
    """(normalized_name, state) -> the real trailing type word from the
    raw CSV row ("County"/"Parish"/"Borough"/"Municipio"/etc., as
    Census/StatsCan itself writes it), which `_load_name_state_table()`'s
    own `_normalize_name()` strips off to build its lookup key. A repair
    path that resolves a bare county name back to its state needs this to
    reattach the correct word -- real gap found 2026-08-30 auditing the
    bleed-backfill queue: `_subdomain_override()` was producing "Lucas,
    OH" instead of "Lucas County, OH" for real subdomain-derived county
    repairs (also seen for Klickitat WA, Escambia FL). A blind "County"
    guess would be wrong for real rows -- 2999 of ~3221 US counties use
    "County", but 64 use "Parish" (Louisiana), 78 "Municipio" (Puerto
    Rico), 17 "Borough" (mostly Alaska), 9 "Region", 2 "Municipality" --
    so this looks up the real word per row rather than assuming."""
    table: Dict[Tuple[str, str], str] = {}
    path = _DATA_DIR / filename
    if not path.exists():
        return table
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            m = _TRAILING_TYPE_RE.search(row["name"])
            if not m:
                continue
            key = (_normalize_name(row["name"]), row["state"])
            table.setdefault(key, m.group(0).strip().capitalize())
    return table


_COUNTY_TYPE_WORDS = _load_county_type_words("counties.csv")


def _county_type_suffix(hint: str, state_code: str) -> str:
    """The type-word suffix (" County"/" Parish"/etc.) to splice between a
    bare county-table name and its state suffix, or "" when `hint` isn't
    a bare county-table name
    needing one (already carries its own type word, matched the place
    table instead, or `state_code` doesn't narrow to a known row) -- see
    `_load_county_type_words()` for why this can't just assume "County".
    Callers splice it in unconditionally: f"{hint}{_county_type_suffix(...)}{suffix}".
    """
    word = _COUNTY_TYPE_WORDS.get((hint.strip().lower(), state_code.strip().upper()))
    return f" {word}" if word else ""


_PLACE_STATES = _load_name_state_table("places.csv")
# WO-16 (BACKLOG.md, 2026-08-16): townships/county subdivisions (Upper
# Providence PA, Greenburgh NY, Upper Dublin PA -- all confirmed real,
# live-flagged as lookup misses) are a separate Census gazetteer (COUSUB),
# not a subset of counties.csv/places.csv -- see
# scripts/build_jurisdiction_data.py's build_county_subdivisions() for the
# source/filter detail.
_SUBDIVISION_STATES = _load_name_state_table("county_subdivisions.csv")
_ZCTA_COUNTY = _load_zcta_table("zcta_county.csv", "county_name")
_ZCTA_PLACE = _load_zcta_table("zcta_place.csv", "place_name")


def lookup_county_state(name: str) -> Optional[str]:
    """A state, only when `name` matches exactly one real US county
    nationally -- see module docstring for why a collision (e.g.
    "Washington County") returns None rather than a guess. Tries each
    of `_normalize_candidates()`'s candidates in order, stopping at the
    first one that's a real key at all (ambiguous or not) -- see that
    function's own docstring for why falling through past a real,
    if ambiguous, match to a less-specific candidate would be wrong."""
    for candidate in _normalize_candidates(name):
        states = _COUNTY_STATES.get(candidate)
        if states:
            return states[0] if len(set(states)) == 1 else None
    return None


def lookup_city_state(name: str) -> Optional[str]:
    """Same as `lookup_county_state()`, against real incorporated places
    instead. Real confirmed collisions: "Detroit" is a real city in MI,
    OR, AL, and TX; "Charlotte" in NC, MI, IA, TX, and TN; "Kansas City"
    is a real, substantial city in *both* KS and MO -- all three return
    None here even though this app already resolves specific, confirmed
    instances of some via `lookup_by_domain()` below.

    Falls back to `_SUBDIVISION_STATES` (townships/towns -- WO-16's
    separate COUSUB gazetteer, see that table's own load-site comment)
    ONLY when no `_PLACE_STATES` candidate matched at all -- a town
    government is the same "not a county" category this function's
    callers already bucket bare names into (see `resolve_state()`'s
    city/county type split), and a place-table hit, ambiguous or not,
    already returns before this ever runs, so adding it can't change any
    existing place-table outcome. Real gap this closes, confirmed live
    2026-08-29: "Seekonk" (MA) and "Piscataway" (NJ) are both real,
    nationally-unambiguous towns/townships missing from `places.csv`
    entirely -- New England towns and PA/NJ townships are frequently
    absent from the incorporated-place gazetteer this module is built
    from, the same gap this file's `_KNOWN_ORG_TOKEN_JURISDICTIONS`-style
    per-adapter workarounds elsewhere already document; this closes it at
    the shared root instead of per-adapter. Still correctly declines on a
    genuine subdivision-table collision (e.g. "Peters Township" is real
    in both KS and PA)."""
    for candidate in _normalize_candidates(name):
        states = _PLACE_STATES.get(candidate)
        if states:
            return states[0] if len(set(states)) == 1 else None
    for candidate in _normalize_candidates(name):
        states = _SUBDIVISION_STATES.get(candidate)
        if states:
            return states[0] if len(set(states)) == 1 else None
    return None


def is_literal_known_place(name: str) -> bool:
    """True only when `name`, taken exactly as typed (just lowercased --
    no leading/trailing generic-type-word stripping at all), is a real
    known US place or county name. Deliberately narrower than
    `lookup_city_state()`/`lookup_county_state()` (and the internal
    `_table_lookup()` this module's own validation/repair machinery
    uses everywhere else), both of which also accept a SECONDARY match
    via a trailing-type-word strip (see `_normalize_candidates()`) --
    that secondary path is exactly what makes "Bedford City" coincidentally
    "validate" (only "Bedford" is real; "City" merely stripped away as a
    trailing generic type word), which is fine for state-filling but wrong
    for a caller that needs to know whether a trailing "City"/"Town"/
    etc.-shaped word is genuinely PART of the proper name (Oklahoma City,
    Carson City, Jersey City, Rapid City) or just a separable type suffix
    (Bedford City, Thousand Oaks City) sitting next to it in the source
    text.

    Built for `app/platforms/primegov.py`'s "{Name} City/Town/Village
    Council" header extraction (2026-08-21, BACKLOG.md's Bedford/Cuyahoga
    entry) -- confirmed live on bedfordoh.primegov.com and
    okc.primegov.com/toaks.primegov.com's own real inner `<title>` tags
    (see that adapter's own module comment): a bare regex capturing "the
    words before Council" can't itself tell whether the last of those
    words is part of the city's real name or just the letterhead's own
    "City Council" phrasing, and guessing wrong in either direction is a
    real, confirmed failure mode (stripping "City" off "Oklahoma City"
    leaves "Oklahoma", which coincidentally collides with a real but
    totally unrelated place, "Oklahoma borough, PA" -- see
    `_normalize_candidates()`'s own docstring for that exact historical
    bug). This function lets a caller check the un-stripped form on its
    own merits first, before ever falling back to the stripped one."""
    key = name.strip().lower()
    return key in _PLACE_STATES or key in _COUNTY_STATES


# Trailing "City"/"Town" as vendor branding rather than part of the real
# name -- see the finalize_jurisdiction() fast-path comment for the real
# IQM2 tenants this was built from. "County"/"Parish" are deliberately
# NOT in this pattern: a county tenant's trailing "County" is the entity
# type of what's actually being named ("Madera County" is the
# government's real name), the same reasoning `_validated_label_extract_
# with_state()`'s tier 4 already documents for Pitkin County.
_BRANDING_TYPE_SUFFIX_RE = re.compile(r"^(?P<body>.+\S)\s+(?:City|Town)$")


def _strip_branding_type_suffix(name: str) -> Optional[str]:
    """The name with a bogus trailing "City"/"Town" removed, or None when
    no safe strip exists. Safe means: the full name is NOT itself a
    literal table key (so "Redwood City"/"Foster City"/"Oklahoma City"/
    "Carson City" are never touched) while the stripped base IS one (so
    the strip lands on a real place, never on a fragment)."""
    m = _BRANDING_TYPE_SUFFIX_RE.match(name.strip())
    if not m:
        return None
    if is_literal_known_place(name):
        return None
    body = m.group("body")
    return body if is_literal_known_place(body) else None


def lookup_county_by_zip(zip_code: str) -> Optional[Tuple[str, str]]:
    """(county_name, state) for the real county with the largest overlap
    with this ZIP -- picked via AREALAND_PART, since ~30% of real ZCTAs
    genuinely span more than one county. None if the ZIP isn't a real
    ZCTA at all."""
    candidates = _ZCTA_COUNTY.get(zip_code)
    if not candidates:
        return None
    name, state, _area = max(candidates, key=lambda c: c[2])
    return name, state


def lookup_place_by_zip(zip_code: str) -> Optional[Tuple[str, str]]:
    """Same as `lookup_county_by_zip()`, against real incorporated places."""
    candidates = _ZCTA_PLACE.get(zip_code)
    if not candidates:
        return None
    name, state, _area = max(candidates, key=lambda c: c[2])
    return name, state


# A real US mailing address, e.g. "2100 E. Thousand Oaks Blvd., Thousand
# Oaks, CA 91362" (confirmed live in a real PrimeGov page, see
# tests/test_primegov.py) -- captures (city, state, zip) as one group so a
# caller gets the state directly with zero lookup needed for the common
# case, and the zip separately for the county/place-crosswalk case where
# the city portion can't be trusted (see module docstring).
_ZIP_ADDRESS_RE = re.compile(
    r"\b([A-Z][A-Za-z.' -]{1,40}?),\s*([A-Z]{2})\s+(\d{5})(?:-\d{4})?\b"
)


def find_zip_addresses(text: str) -> List[Tuple[str, str, str]]:
    """Every (city, state, zip) triple shaped like a real US mailing
    address found in `text`. Deliberately returns every match, not just
    the first -- callers deciding what to trust (e.g. preferring one that
    agrees with an already-known city/state) is a caller-specific
    decision, not this function's."""
    return [
        (m.group(1).strip(), m.group(2), m.group(3))
        for m in _ZIP_ADDRESS_RE.finditer(text)
    ]


@dataclass(frozen=True)
class KnownJurisdiction:
    name: str
    # "city" or "county" for ordinary governments (the only two values
    # resolve_state() ever matches against); a special-purpose entity
    # (transportation authority, sanitary district) uses a descriptive
    # word ("authority", "district") instead -- it participates in
    # domain overrides and display but never in city/county state
    # resolution, and known_jurisdiction_display() renders it as
    # "{name}, {state}" rather than "{Type} of {name}, {state}".
    type: str
    # "fallback" (default): used only to fill a missing state, or to
    # supply a jurisdiction when the caller found none at all -- never
    # overrides a real extracted name, even a wrong one. "authoritative":
    # this domain's own page-text extraction is *confirmed unreliable*
    # (today: only slc.primegov.com -- see that entry's own comment for
    # why), so this entry should win outright, even over a successful-
    # looking extraction. Kept rare and evidence-backed on purpose --
    # every domain defaults to "fallback" unless a real, documented
    # incident earns the stronger tier. Added 2026-08-15 as part of
    # JURISDICTION_METADATA_PLAN.md's registry-in-enricher design; not
    # yet consulted by any caller (PrimeGov's own resolve() still has its
    # own separate, untouched known_jurisdiction_display() call for this
    # -- see BACKLOG.md's "Future refactor, deliberately deferred" entry
    # for why that's staying as-is until this design is proven).
    state: str
    strength: str = "fallback"  # "fallback" | "authoritative" -- see comment above


# Confirmed, real (domain, jurisdiction) pairs -- the single most reliable
# signal this module has, since each entry is tied to one specific,
# human-verified real instance rather than a name that might collide
# nationally (both "Detroit" and "Charlotte" below are genuinely ambiguous
# in the name-only gazetteer -- see lookup_city_state()'s own docstring).
# Grows incrementally as real customers are confirmed, same convention
# this repo already uses elsewhere (Aurora/SLC/Viebit's single-jurisdiction
# scoping) -- a domain not listed here just falls through to the weaker
# name/ZIP-based lookups above, not an error.
_KNOWN_DOMAINS: Dict[str, KnownJurisdiction] = {
    "detroit-vod.cablecast.tv": KnownJurisdiction("Detroit", "city", "MI"),
    "reflect-detroit-vod.cablecast.tv": KnownJurisdiction("Detroit", "city", "MI"),
    "charlotte.cablecast.tv": KnownJurisdiction("Charlotte", "city", "NC"),
    # Broomfield's Cablecast site branding is just "Channel 8" with an
    # empty pageDescription -- no "City of"/"County of" phrase anywhere
    # for cablecast.py's own regex extraction to find (confirmed live
    # 2026-08-19, see BACKLOG.md). Real signals on the same site object
    # instead: host "broomfieldco.cablecast.tv", email
    # media-communications@broomfield.org, logo filename "Broomfield CO
    # Logo Tag.png". Broomfield is a consolidated city-county in CO;
    # "county" matches the page's own "County of Broomfield" phrasing
    # used elsewhere on the same site (e.g. Granicus's confirmed
    # jurisdiction text for other CO consolidated city-counties).
    "broomfieldco.cablecast.tv": KnownJurisdiction("Broomfield", "county", "CO"),
    # CablecastPublicSite template (a separate portal template from the
    # Remix one above -- see cablecast.py's own module docstring) has no
    # jurisdiction-bearing text anywhere confirmed live: both tenants'
    # og:title/twitter:title/meta description are just channel branding
    # ("Urbana Public Television"), no "City/Town of X" phrase on either
    # the site root or a real show page. Both entries below confirmed via
    # real, live evidence rather than the name alone: Urbana's page links
    # `urbanail.gov` and names "Cunningham Township" (a real Champaign
    # County, IL township) on a real show; "Urbana" alone is ambiguous
    # (also real in OH). Smyrna's page links `townofsmyrna.org` and a
    # 615 (Nashville-area, TN) phone number; "Smyrna" alone is ambiguous
    # (also real in GA/DE).
    "urbana.cablecast.tv": KnownJurisdiction("Urbana", "city", "IL"),
    "smyrna.cablecast.tv": KnownJurisdiction("Smyrna", "city", "TN"),
    # Two more real Cablecast (Remix-template) customers confirmed live
    # 2026-08-30 with no usable "City/Town of X" text at all: Orion
    # Township, MI's real show page (reflect-ontv.cablecast.tv,
    # `/CablecastPublicSite/show/2904?site=3`) embeds a "Government"
    # channel with generic pageDescription text (a phone number, no city
    # name) -- the site's own catalog separately lists a sibling
    # `{"siteId": 4, "title": "Orion Township"}` channel confirming the
    # real jurisdiction name, but that's a different siteId than the one
    # any given show page resolves to, so it's not reachable through
    # `_find_site()`'s existing pageDescription-based match. Montgomery,
    # AL's capitalcityconnection.cablecast.tv names "Montgomery Zoo" and
    # "City-County Library" in its real pageDescription but never the
    # bare "City of Montgomery" phrase `_JURISDICTION_RE` requires.
    # Neither subdomain ("reflect-ontv", "capitalcityconnection") itself
    # validates as a place name either. "Orion Township" typed "city"
    # here (not "county") since a Michigan charter township is a
    # general-purpose municipal government, same convention as every
    # other single-jurisdiction domain entry in this table -- no
    # "township"-typed entry existed here before this one.
    "reflect-ontv.cablecast.tv": KnownJurisdiction("Orion Township", "city", "MI"),
    "capitalcityconnection.cablecast.tv": KnownJurisdiction("Montgomery", "city", "AL"),
    # "Minneapolis" is also a real, if much smaller, city in Kansas --
    # confirmed via app/utils/jurisdiction_data -- so a bare name lookup
    # alone would stay ambiguous for this real, confirmed LIMS customer.
    "lims.minneapolismn.gov": KnownJurisdiction("Minneapolis", "city", "MN"),
    # "Dallas County" is also real in AL/AR/IA/MO -- confirmed via
    # app/utils/jurisdiction_data -- so a bare name lookup stays
    # deliberately ambiguous. Found live 2026-08-13: this customer's real
    # meeting pages carry no ZIP-anchored address at all for the fallback
    # lookup to key off of (confirmed: zero 5-digit numbers anywhere in
    # the page's raw HTML), so a domain entry is the only real option here,
    # same reasoning as Cablecast's Detroit/Charlotte entries above.
    "dallascounty.civicweb.net": KnownJurisdiction("Dallas", "county", "TX"),
    # Confirmed live 2026-08-13 -- all nationally-ambiguous city names
    # (Alexandria, Sacramento*, Long Beach, Oakland, San Diego, Baltimore,
    # Berkeley, Boston all collide with a same-named place in another
    # state per app/utils/jurisdiction_data) whose Granicus/Legistar page
    # extracted a real, correct "City of X" but no state to go with it,
    # since a bare name lookup stays ambiguous by design. *Sacramento
    # itself isn't nationally ambiguous, but is listed here for
    # consistency/documentation since it was reported alongside the rest.
    "alexandria.granicus.com": KnownJurisdiction("Alexandria", "city", "VA"),
    "sacramento.granicus.com": KnownJurisdiction("Sacramento", "city", "CA"),
    "longbeach.granicus.com": KnownJurisdiction("Long Beach", "city", "CA"),
    "oakland.granicus.com": KnownJurisdiction("Oakland", "city", "CA"),
    "sandiego.granicus.com": KnownJurisdiction("San Diego", "city", "CA"),
    "berkeley.granicus.com": KnownJurisdiction("Berkeley", "city", "CA"),
    "boston.granicus.com": KnownJurisdiction("Boston", "city", "MA"),
    # "San Jose" is also a real city in Costa Rica and the Philippines, so
    # a bare name lookup stays ambiguous by design here too -- confirmed
    # 2026-08-28 (this same tenant's real ViewPublisher listing page is
    # titled "CivicCenter Television Streaming Video," San Jose, CA's own
    # real municipal-channel branding).
    "sanjose.granicus.com": KnownJurisdiction("San Jose", "city", "CA"),
    # Legistar, not Granicus -- Baltimore's own page is the jurisdiction
    # source here (see legistar.py's _extract_page_meeting_info()), not a
    # delegated platform's domain.
    "baltimore.legistar.com": KnownJurisdiction("Baltimore", "city", "MD"),
    # Every real slc.primegov.com meeting checked resolves to Salt Lake
    # City itself -- confirmed by each meeting's own title ("Salt Lake
    # City Formal Meeting", "Salt Lake City Council Work Session"), even
    # the two archived under a "City of Holladay" jurisdiction. See
    # BACKLOG_DONE.md for why: PrimeGov's own page-text extraction is
    # confirmed unreliable specifically on this domain (an unrelated
    # "Central Wasatch Commission... City of Holladay" mention elsewhere
    # on the page can outrank the real header), so this domain is looked
    # up as a full override in primegov.py, not just a missing-state fill
    # -- see known_jurisdiction_display() below.
    "slc.primegov.com": KnownJurisdiction(
        "Salt Lake City", "city", "UT", strength="authoritative"
    ),
    # Second and third confirmed instances of the same PrimeGov body-text
    # false-positive shape (2026-08-23, found via Google's crawl of
    # /state/california -- see BACKLOG.md's PrimeGov jurisdiction entry):
    # ccta.primegov.com is the Contra Costa Transportation Authority
    # (its own agenda header names it; the unscoped body-text search
    # instead grabbed an agenda item's "City of Hercules GMP Compliance
    # Checklist"), and cityoflancasterca.primegov.com is the City of
    # Lancaster, CA (the search grabbed "City of Lancaster Community
    # Development Department" -- a department, not a government). Both
    # authoritative for the same reason SLC is: the domain is the more
    # trustworthy signal than this platform's text extraction.
    "ccta.primegov.com": KnownJurisdiction(
        "Contra Costa Transportation Authority",
        "authority",
        "CA",
        strength="authoritative",
    ),
    "cityoflancasterca.primegov.com": KnownJurisdiction(
        "Lancaster", "city", "CA", strength="authoritative"
    ),
    # Ventura, CA x2 (2026-08-23): the Census gazetteer names the city
    # "San Buenaventura (Ventura)", so before the parenthetical-alt-name
    # indexing in _load_name_state_table() a bare "Ventura" lookup
    # resolved uniquely to tiny Ventura, IA -- both these real customers'
    # pages archived as "City of Ventura, IA". Now "Ventura" is
    # (correctly) nationally ambiguous, so each confirmed real customer
    # gets pinned here: ventura.primegov.com is the County of Ventura,
    # CA (its own agenda header: "Board of Supervisors / Ventura County",
    # confirmed live), cityofventura.granicus.com is the City of
    # Ventura, CA (its own RSS channel title: "City of Ventura",
    # confirmed live). Authoritative because the stored rows prove the
    # text-derived answer on these domains is confidently wrong, not
    # merely missing.
    "ventura.primegov.com": KnownJurisdiction(
        "Ventura County", "county", "CA", strength="authoritative"
    ),
    "cityofventura.granicus.com": KnownJurisdiction(
        "Ventura", "city", "CA", strength="authoritative"
    ),
    # lacity.primegov.com's real "coin-flip" gap (BACKLOG.md, open since
    # 2026-08-16) -- fetched two real meeting pages live 2026-08-30 to
    # actually see the structural difference between meetingTemplateId
    # 156963 (jurisdiction resolved None) and 157675 (resolved correctly)
    # instead of guessing at another positional/regex rule, which is what
    # both prior reverted attempts on this general PrimeGov problem did.
    # The real difference: 157675 is a full City Council meeting, with a
    # genuine "Los Angeles City Council Agenda" letterhead and city-seal
    # image `_COUNCIL_HEADER_RE` matches; 156963 is a COMMITTEE meeting
    # (`<title>Housing and Homelessness Committee - 8/5/2026...`), whose
    # entire real letterhead is just "Housing and Homelessness Committee"
    # -- no "City of"/"Los Angeles City Council" phrase anywhere on the
    # page, confirmed by a full-page search of the raw HTML. This is not
    # a case of the extraction picking the wrong match (the OKC/Thousand
    # Oaks/SLC/Bedford shape both earlier fix attempts were reverted
    # over) -- it is a page-shape gap: LA's own committee pages carry no
    # jurisdiction-identifying text at all for any regex to find. A
    # domain override is the right tool for exactly this failure mode
    # (the same reasoning as ccta.primegov.com/cityoflancasterca.primegov.com
    # above), and lacity.primegov.com is confirmed single-tenant (every
    # page on it, committee or full council, belongs to the City of Los
    # Angeles) so it's safe to apply unconditionally.
    "lacity.primegov.com": KnownJurisdiction(
        "Los Angeles", "city", "CA", strength="authoritative"
    ),
    # townoffrisco.primegov.com (Frisco, CO) -- BACKLOG.md's open
    # [NEEDS-AUDIT] entry for this domain claimed the false-positive root
    # cause was an embedded "Subscribe to Town of Frisco Government
    # YouTube Channel" widget label beating the real "TOWN OF FRISCO"
    # header. Re-verified live 2026-08-30 against 4 real meeting pages
    # (both the `?meetingTemplateId=` and `?compiledMeetingDocumentFileId=`
    # URL shapes): that widget text is never present in the actual
    # server-rendered HTML this adapter fetches -- it's YouTube's own
    # IFrame Player chrome, rendered client-side inside a cross-origin
    # `<iframe>` this adapter's plain HTTP fetch never sees at all (the
    # page only ever carries an empty `<div id="ytplayer">` placeholder
    # server-side). `_extract_jurisdiction()` on the real fetched HTML
    # already returns "Town of Frisco" correctly with no false positive.
    # The real, confirmed gap: "Frisco" is nationally ambiguous (a real
    # Frisco, TX customer is also registered here, see
    # agenda.friscotexas.gov below), so the name-only state lookup stays
    # deliberately ambiguous and the page resolves with no state at all --
    # same "ambiguous name, no domain override yet" shape as Alexandria/
    # Sacramento/Long Beach above, not a wrong-match shape. This entry
    # fills the missing state the same way those do; "fallback" strength
    # (not "authoritative") since the page's own extraction isn't wrong,
    # just incomplete.
    "townoffrisco.primegov.com": KnownJurisdiction("Frisco", "town", "CO"),
    # Costa Mesa Sanitary District (pub-cmsd.escribemeetings.com,
    # 2026-08-23) -- the page's own venue line names it ("Costa Mesa
    # Sanitary District - 290 Paularino Ave., Costa Mesa, CA 92626",
    # confirmed live). A special district is in no Census table, so the
    # eScribe adapter's Census-validated extraction correctly declines
    # ("Cmsd" was the OLD stored garbage, from before that adapter's
    # validation landed); this entry supplies the real name instead of
    # leaving the page jurisdiction-less. Authoritative so the recompute
    # backfill can also repair the existing "Cmsd, CA" row, which is
    # confirmed wrong rather than merely unvalidated.
    "pub-cmsd.escribemeetings.com": KnownJurisdiction(
        "Costa Mesa Sanitary District", "district", "CA", strength="authoritative"
    ),
    # "Milton" is also real and much smaller in FL -- confirmed 2026-08-28
    # via this tenant's own real agenda page: "150 Mary Street, Milton, ON
    # L9T 6Z5", "The Corporation of the Town of Milton", real Ontario
    # provincial postal code. Typed "city" (not "town") so
    # resolve_state()'s exact type match actually fires -- see
    # KnownJurisdiction.type's own docstring: that field only ever
    # distinguishes "which lookup table" (city vs. county), not a
    # government's literal legal designation.
    "pub-milton.escribemeetings.com": KnownJurisdiction("Milton", "city", "ON"),
    # Beaumont, AB -- real, ambiguous nationally (a real Beaumont, TX
    # customer already exists in the archive on a different platform), so
    # the bare "Beaumont" stored on these two pages needs a domain
    # override the same way Milton above does. Confirmed real:
    # `validated_label_extract_with_state("beaumontab")` already resolves
    # this correctly (Census/StatsCan-validated) -- this file's own
    # `_PROVINCE_ABBREVIATIONS_LOWER` comment names this exact subdomain
    # as the motivating real example for that lookup existing at all. The
    # gap this entry closes: that resolution only ever ran at *resolve*
    # time (escribe.py's `_jurisdiction_from_subdomain()`), not at
    # recompute-backfill time (`finalize_jurisdiction()`, which only
    # checks this registry by netloc, never re-parses a subdomain) -- so
    # the two already-archived pages stored before this tenant's
    # subdomain-parsing ran (or matching it) stayed at bare "Beaumont"
    # with no state, unrepairable by a bulk recompute until now.
    "pub-beaumontab.escribemeetings.com": KnownJurisdiction("Beaumont", "city", "AB"),
    # Hyland "OnBase Agenda Online" -- confirmed live 2026-08-16, none of
    # the 3 known customer domains carries reliable in-page jurisdiction
    # text (Maricopa/Tucson have none at all; Sacramento's happens to sit
    # in a generic sitewide <title>, one unconfirmed-to-generalize sample)
    # -- see hyland.py's own module docstring for the full page-structure
    # investigation.
    "tucsonaz.hylandcloud.com": KnownJurisdiction("Tucson", "city", "AZ"),
    "mccobagenda.databankcloud.com": KnownJurisdiction("Maricopa", "county", "AZ"),
    "agendanet.saccounty.gov": KnownJurisdiction("Sacramento", "county", "CA"),
    # Found 2026-08-16 via a plain web search for the platform's
    # distinctive URL path, not domain/CDX enumeration -- both run the
    # same product's second confirmed UI version (see hyland.py's module
    # docstring). Neither has reliable in-page jurisdiction text either.
    "docs.santabarbaraca.gov": KnownJurisdiction("Santa Barbara", "city", "CA"),
    "stream2.ci.concord.ca.us": KnownJurisdiction("Concord", "city", "CA"),
    # Found 2026-08-16, same web-search method, a second batch (one
    # researcher-supplied list of subdomain-naming conventions plus
    # user-found examples) -- each domain confirmed live with a real
    # ViewMeeting page resolving through hyland.py, none with reliable
    # in-page jurisdiction text.
    "docs.steamboatsprings.net": KnownJurisdiction("Steamboat Springs", "city", "CO"),
    "online.cityofwhittier.org": KnownJurisdiction("Whittier", "city", "CA"),
    "onbase.comptoncity.org": KnownJurisdiction("Compton", "city", "CA"),
    # scgov.net confirmed via web search to be Sarasota County, FL's own
    # domain -- no "Sarasota" string anywhere in the OnBase pages
    # themselves (same "vendor page carries no branding of the customer
    # who deployed it" pattern as every other entry in this block).
    "egenda.scgov.net": KnownJurisdiction("Sarasota", "county", "FL"),
    # muni.org confirmed via web search to be the Municipality of
    # Anchorage, AK's own domain -- the one real meeting id checked here
    # was a regional transportation-planning committee (AMATS), not a
    # council meeting, but the domain itself is unambiguously Anchorage's,
    # same reasoning as every domain-registry entry in this file.
    "meetings.muni.org": KnownJurisdiction("Anchorage", "city", "AK"),
    "ecm.cityofsantacruz.com": KnownJurisdiction("Santa Cruz", "city", "CA"),
    # Real government meetings (confirmed: real video + real per-item
    # agenda outline), but hosted on Hamilton County's Job & Family
    # Services-specific OnBase instance rather than a general county
    # portal -- still the same product/adapter, just a narrower agency
    # scope than the other county-level entries in this file.
    "hcjfsonbase.jfs.hamilton-co.org": KnownJurisdiction("Hamilton", "county", "OH"),
    # Found 2026-08-16 via Wayback CDX subdomain enumeration of
    # hylandcloud.com/databankcloud.com (the two known shared-hosting
    # apex domains) -- each confirmed with a real resolving ViewMeeting
    # page, unlike the many other CDX-listed subdomains under these two
    # domains that turned out to be non-government OnBase customers
    # (banks, hospitals, universities -- OnBase is a general enterprise
    # content-management product, not government-specific) or dead
    # (3cenergy, a second maricopa.hylandcloud.com tenant -- both DNS
    # failures live, not registered).
    "dunwoodyga.hylandcloud.com": KnownJurisdiction("Dunwoody", "city", "GA"),
    "durangogov.hylandcloud.com": KnownJurisdiction("Durango", "city", "CO"),
    "gilbertaz.databankcloud.com": KnownJurisdiction("Gilbert", "city", "AZ"),
    "henderson.hylandcloud.com": KnownJurisdiction("Henderson", "city", "NV"),
    # Confirmed reachable and resolving correctly on this hylandcloud.com
    # tenant, unlike the Akamai-blocked www.tempe.gov page found earlier
    # via web search (a different, unconfirmed platform on that domain).
    "tempe.hylandcloud.com": KnownJurisdiction("Tempe", "city", "AZ"),
    "westerville.hylandcloud.com": KnownJurisdiction("Westerville", "city", "OH"),
    # Resolves correctly, but the only content found (5 total crawled
    # URLs across this domain's whole CDX history, oldest dated 2016) is
    # sparse enough to suggest an abandoned/legacy pilot rather than San
    # Diego's actual current meeting system (almost certainly Granicus,
    # like every other major California city already covered) -- kept
    # since it's real and resolves, not because it's likely to be
    # actively maintained going forward.
    "sandiego.hylandcloud.com": KnownJurisdiction("San Diego", "city", "CA"),
    # Found 2026-08-16 via a `site:.gov inurl:OnBaseAgendaOnline/Meetings/
    # ViewMeeting` web search -- each confirmed with a real resolving
    # ViewMeeting page. Two candidates from the same search
    # (documents.provo.gov, onbase.sandiego.gov -- San Diego's real .gov
    # domain, a separate lead from the stale sandiego.hylandcloud.com
    # entry above) turned out to be fully dead (404/DNS failure even on
    # their own site root, not just one stale meeting id) and were left
    # unregistered.
    "onbaseweb.pittsburgca.gov": KnownJurisdiction("Pittsburg", "city", "CA"),
    "agenda.modestogov.com": KnownJurisdiction("Modesto", "city", "CA"),
    # A second, distinct real Modesto subdomain -- confirmed live
    # 2026-08-29 (BACKLOG_DONE.md's frozen-slug-page entry):
    # agenda2.modestogov.com/OnBaseAgendaOnlineCouncil/... serves real
    # City Council meetings (e.g. "Council Meeting - 8/11/2026"), same
    # city, no in-page jurisdiction text either (see this file's own
    # note on Hyland/OnBase's domain-only jurisdiction strategy).
    "agenda2.modestogov.com": KnownJurisdiction("Modesto", "city", "CA"),
    "onbase.centennialco.gov": KnownJurisdiction("Centennial", "city", "CO"),
    # A second, distinct real Santa Barbara subdomain (docs.
    # santabarbaraca.gov is already registered above) -- both resolve
    # independently through hyland.py, so both are kept rather than
    # assuming one is a stale alias of the other.
    "records.santabarbaraca.gov": KnownJurisdiction("Santa Barbara", "city", "CA"),
    # Found 2026-08-16 -- the user loosened the site:.gov search above
    # (dropping the exact `inurl:` operator) and relayed the raw results;
    # each domain confirmed with a real resolving ViewMeeting page here
    # (via Wayback CDX, since none of these 3 sites' own listing pages
    # expose a static meeting link -- same client-side-search-only
    # limitation as Tampa/Padre/Carbon/Coconino noted elsewhere).
    "agendas.fitchburgwi.gov": KnownJurisdiction("Fitchburg", "city", "WI"),
    "dms.missionviejo.gov": KnownJurisdiction("Mission Viejo", "city", "CA"),
    "isearchmonterey.org": KnownJurisdiction("Monterey", "city", "CA"),
    # Confirmed real 2026-08-14 via this domain's own
    # `Content-Security-Policy: frame-ancestors ... orangecountyfl.net`
    # header and a `<meta name="keywords" content="...Orange County,
    # Archive">` tag -- no reliable in-page jurisdiction text otherwise,
    # so this is a domain-registry entry, not a text-extraction fallback.
    # generic_fallback.py (the adapter for this page) doesn't extract a
    # meeting-body TYPE the way Granicus/CivicClerk do, so this is
    # registered as "county" directly rather than inferred per-resolve.
    "netapps.ocfl.net": KnownJurisdiction("Orange", "county", "FL"),
    # --- 2026-08-21 batch: added alongside the `_fill_missing_state()`
    # fix in `finalize_jurisdiction()`'s "already validated" branch above
    # (BACKLOG.md's "16 real pairs of a jurisdiction appearing twice"
    # entry). Each entry below is grounded in real evidence found while
    # investigating that entry's 16 examples, not a guess -- see each
    # comment for the specific confirmation. Several of these are NOT the
    # state the original bare/suffixed "duplicate" pairing assumed
    # (Cook County, Frederick County, Glendale, Washington County) --
    # the bare row turned out to be a genuinely different, unrelated real
    # jurisdiction that happened to share an ambiguous name with an
    # already-archived suffixed one, not a duplicate of it. Registering
    # the correct state here fixes both: future re-resolves of that exact
    # domain, and (via the existing `/internal/jurisdiction/backfill-apply`
    # endpoint, which already re-runs `finalize_jurisdiction()` against
    # each row's own stored `source_url_normalized`) the already-published
    # row -- no new backfill mechanism needed.
    #
    # Jacksonville/Memphis/Nassau County/Redmond/Bakersfield/Dublin/Albany:
    # confirmed by finding a SECOND already-archived page on the exact
    # same customer domain (Jacksonville, Memphis, Nassau County) or an
    # exact/near-exact domain match (Redmond, Bakersfield, Dublin: same
    # netloc; Albany: same "albanyca" customer slug, one on Granicus one
    # on PrimeGov) whose OWN stored jurisdiction already carries the real
    # state -- about as strong a real-data confirmation as this registry
    # gets, short of an "authoritative" override.
    "jaxcityc.granicus.com": KnownJurisdiction("Jacksonville", "city", "FL"),
    "memphis.granicus.com": KnownJurisdiction("Memphis", "city", "TN"),
    "nassaufl.granicus.com": KnownJurisdiction("Nassau", "county", "FL"),
    "redmondor.portal.civicclerk.com": KnownJurisdiction("Redmond", "city", "OR"),
    "pub-bakersfield.escribemeetings.com": KnownJurisdiction(
        "Bakersfield", "city", "CA"
    ),
    "dublin.granicus.com": KnownJurisdiction("Dublin", "city", "CA"),
    "albanyca.granicus.com": KnownJurisdiction("Albany", "city", "CA"),
    # Harris County, TX: the bare page's own real Granicus clip page
    # (confirmed live) is titled for "...Metropolitan Transit Authority"
    # committees -- METRO, the real, well-known Metropolitan Transit
    # Authority of Harris County, Texas. "Harris County" is only
    # nationally ambiguous between GA and TX, and no real evidence ties a
    # METRO transit authority to Harris County, GA.
    "ridemetro.granicus.com": KnownJurisdiction("Harris", "county", "TX"),
    # Washington County, OR (NOT VA, despite the original pairing's
    # assumption): confirmed live -- this exact domain's own page
    # literally renders `<div id="mottotext">Oregon</div>` right next to
    # its own "Washington County" branding.
    "washingtoncounty.civicweb.net": KnownJurisdiction("Washington", "county", "OR"),
    # Cook County, MN (NOT IL): confirmed via this domain's own customer
    # slug, "cocookmn" -- "Co[unty of] Cook, MN" -- a real, if much
    # smaller, Minnesota county (seat: Grand Marais), genuinely distinct
    # from the Chicago-area Cook County, IL already archived under a
    # different domain.
    "cocookmn.civicweb.net": KnownJurisdiction("Cook", "county", "MN"),
    # Frederick County, VA (NOT MD): confirmed via this domain's own
    # customer slug, "fcva" -- "F[rederick] C[ounty], VA" -- genuinely
    # distinct from Frederick County, MD already archived under a
    # different (`frederick.granicus.com`) domain.
    "fcva.granicus.com": KnownJurisdiction("Frederick", "county", "VA"),
    # Glendale, AZ (NOT CA): confirmed via this domain's own customer
    # slug, "glendale-az" -- genuinely distinct from Glendale, CA already
    # archived under a different (PrimeGov) domain.
    "glendale-az.granicus.com": KnownJurisdiction("Glendale", "city", "AZ"),
    # Hyland/OnBase customers, added 2026-08-29 auditing archived pages
    # missing a jurisdiction -- hyland.py has no in-page jurisdiction text
    # to extract at all (see that adapter's own module comment) and relies
    # entirely on this table, so an unlisted domain always carries no
    # jurisdiction. Each domain below fetched and confirmed live: 10
    # straightforward city/county domains, plus two real special-purpose
    # districts (verified via each org's own real "who we are"/"cities we
    # serve" page text, not guessed from the domain alone).
    "imaging.sedgwickcounty.org": KnownJurisdiction("Sedgwick", "county", "KS"),
    "cityordinances.durhamnc.gov": KnownJurisdiction("Durham", "city", "NC"),
    # Medicine Hat, AB -- also directly confirmed by this exact meeting's
    # own title, "REGULAR MEDICINE HAT CITY COUNCIL".
    "docs.medicinehat.ca": KnownJurisdiction("Medicine Hat", "city", "AB"),
    "meetings.redwoodcity.org": KnownJurisdiction("Redwood City", "city", "CA"),
    "ob.wvc-ut.gov": KnownJurisdiction("West Valley City", "city", "UT"),
    "amv.siouxfalls.gov": KnownJurisdiction("Sioux Falls", "city", "SD"),
    "agenda.friscotexas.gov": KnownJurisdiction("Frisco", "city", "TX"),
    "connect.sussexcountyde.gov": KnownJurisdiction("Sussex", "county", "DE"),
    "stream.ci.concord.ca.us": KnownJurisdiction("Concord", "city", "CA"),
    "agendas.cityofsparks.us": KnownJurisdiction("Sparks", "city", "NV"),
    # Jurupa Community Services District, CA -- a real special district
    # (water/wastewater/parks/street-lighting), NOT the city of Jurupa
    # Valley itself: confirmed via jcsd.us's own page, "serves the cities
    # of Jurupa Valley and Eastvale in Riverside County, California".
    "records.jcsd.us": KnownJurisdiction(
        "Jurupa Community Services District", "district", "CA"
    ),
    "meeting.reddeer.ca": KnownJurisdiction("Red Deer", "city", "AB"),
    # Water Replenishment District, CA -- a real special district serving
    # multiple Los Angeles County cities, HQ'd in Lakewood: confirmed via
    # wrd.org's own "Cities We Serve" page, not tied to any single city.
    "agendas.wrd.org": KnownJurisdiction(
        "Water Replenishment District", "district", "CA"
    ),
    "onlinedocs.akronohio.gov": KnownJurisdiction("Akron", "city", "OH"),
    "onbaseep22.mesacounty.us": KnownJurisdiction("Mesa", "county", "CO"),
    "tampagov.hylandcloud.com": KnownJurisdiction("Tampa", "city", "FL"),
    # Tampa City Council's own "CTTV" closed-captioning transcript webapp
    # -- a different domain from the Hyland agenda host above, same city
    # (WO-73, 2026-08-30). See app/platforms/tampa.py's own module
    # docstring for the real page structure confirmed live.
    "apps.tampagov.net": KnownJurisdiction("Tampa", "city", "FL"),
    "agendaonline.mymanatee.org": KnownJurisdiction("Manatee", "county", "FL"),
    # Two of the 6 real CivicClerk residuals from the 2026-08-29 sweep
    # (BACKLOG.md's "CivicClerk residuals after the 2026-08-29 sweep"
    # entry) needing individual research rather than a general tier, the
    # same "Hyland JCSD/WRD" precedent as the two special districts
    # above -- both confirmed live 2026-08-30 via a real browser fetch of
    # the tenant's own CivicClerk portal (a client-rendered SPA -- see
    # civicclerk.py's own module docstring -- so a plain HTTP fetch alone
    # shows no jurisdiction text; the rendered event list does).
    # riversidesheriff.portal.civicclerk.com's real event titles ("We Are
    # RSO", "Critical Incident Videos" under a "Sheriff's Department
    # General" category) confirm this is the Riverside County Sheriff's
    # Department (RSO) -- riversidesheriff.org, its own official site,
    # names it "Riverside County Sheriff, CA"; Wikipedia gives the full
    # legal name "Riverside County Sheriff's Department." Not a city or
    # county general government itself (hence the "department" type,
    # like the special-district entries above -- neither participates in
    # `resolve_state()`'s city/county lookup), but Riverside County
    # itself is real and unambiguous in CA.
    "riversidesheriff.portal.civicclerk.com": KnownJurisdiction(
        "Riverside County Sheriff's Department", "department", "CA"
    ),
    # cosumnescommunityservices.portal.civicclerk.com is the Cosumnes
    # Community Services District, a real special district (emergency
    # medical, fire protection, parks and recreation) serving over
    # 221,000 south Sacramento County, CA residents across Elk Grove and
    # Galt -- confirmed via its own official site, cosumnescsd.gov
    # ("Cosumnes CSD | Elk Grove & Galt, CA"), which also names this
    # exact CivicClerk portal URL as its own agenda source. Not tied to
    # one single city (same reasoning as `agendas.wrd.org` above), so
    # registered directly rather than as a per-city resolution.
    "cosumnescommunityservices.portal.civicclerk.com": KnownJurisdiction(
        "Cosumnes Community Services District", "district", "CA"
    ),
    # WO-69 (2026-08-30) batch: 10 of the 12 "eScribe residuals after the
    # 2026-08-29 sweep" (BACKLOG.md) domains -- each confirmed live via
    # the org's own filestream documents or live meeting-list pages,
    # not guessed from the acronym alone. `pub-lloydminster` is
    # deliberately left unregistered (needs a real product decision on
    # the AB/SK border, not a data fix) and `pub-stthomas` is registered
    # below since the bare name is a genuine 3-way MO/ND/ON collision
    # (confirmed via `lookup_city_state("St. Thomas")` returning None).
    # All plain "fallback" strength (not "authoritative"): none of these
    # has a confirmed-wrong existing extraction to override (the bar
    # `KnownJurisdiction.strength`'s own docstring sets for that tier) --
    # `finalize_jurisdiction()`'s own registry-consultation branches
    # already supply the full name whenever nothing else validates
    # (blank extraction, or an acronym subdomain that declines), which is
    # the expected case for every acronym/institutional domain below.
    #
    # Surrey Schools (School District 36) -- real Surrey, BC school board
    # meetings; "Surrey, BC" is an approximation since the district also
    # serves White Rock and Barnston Island, same "closest general
    # jurisdiction" convention as every other district-shaped entry here.
    "pub-surreyschools.escribemeetings.com": KnownJurisdiction("Surrey", "city", "BC"),
    # Horry County Schools, SC -- wordninja mangles "horrycountyschools"
    # to ['horr','y','county','schools'] even after any generic
    # institutional-suffix strip, so a direct override is the only real
    # fix (see BACKLOG.md's own note on this).
    "pub-horrycountyschools.escribemeetings.com": KnownJurisdiction(
        "Horry County", "county", "SC"
    ),
    # Toronto and Region Conservation Authority, ON -- a real special-
    # purpose conservation authority, not a single municipality.
    "pub-trca.escribemeetings.com": KnownJurisdiction(
        "Toronto and Region Conservation Authority", "authority", "ON"
    ),
    # Regional District of Central Okanagan, BC -- a real BC regional
    # district (the "Type of Name" municipal shape doesn't apply to it,
    # same as every other "district"-typed entry here).
    "pub-rdco.escribemeetings.com": KnownJurisdiction(
        "Regional District of Central Okanagan", "district", "BC"
    ),
    # Sunshine Coast Regional District, BC.
    "pub-scrd.escribemeetings.com": KnownJurisdiction(
        "Sunshine Coast Regional District", "district", "BC"
    ),
    # Thunder Bay District Health Unit, ON -- a real public health unit,
    # NOT the same tenant as the separate, already-real
    # `pub-thunderbay.escribemeetings.com` (City of Thunder Bay itself).
    "pub-tbdhu.escribemeetings.com": KnownJurisdiction(
        "Thunder Bay District Health Unit", "health unit", "ON"
    ),
    # Resort Municipality of Whistler, BC -- typed "city" and named
    # "Whistler" rather than the literal legal name, matching this file's
    # own general-purpose-municipal-typed-as-"city" convention (see
    # Milton/Orion Township above: KnownJurisdiction.type only ever
    # distinguishes which lookup table, never a government's literal
    # legal designation).
    "pub-rmow.escribemeetings.com": KnownJurisdiction("Whistler", "city", "BC"),
    # Township of Ashfield-Colborne-Wawanosh, ON -- typed "city" for the
    # same reason as Whistler/Milton above (the only other ON entry in
    # this file, Milton, sets this convention).
    "pub-acwtownship.escribemeetings.com": KnownJurisdiction(
        "Ashfield-Colborne-Wawanosh", "city", "ON"
    ),
    # Hamilton Public Library, ON -- confirmed live 2026-08-30 to be the
    # library board's OWN meetings (its committee list shows "Hamilton
    # Public Library Board," "Regular Board Meeting," held at "Central
    # Library, Board Room"), NOT City of Hamilton council carried on the
    # library's channel -- BACKLOG.md's own entry flagged this as the
    # open, unconfirmed question; now resolved. "library" is a new type
    # value here (the type field is free descriptive text for a
    # special-purpose entity, same as "authority"/"district"/"health
    # unit" above -- no enum to extend).
    "pub-hpl.escribemeetings.com": KnownJurisdiction(
        "Hamilton Public Library", "library", "ON"
    ),
    # St. Thomas, ON -- "St. Thomas" is a genuine 3-way collision (MO, ND,
    # ON all have a real "St. Thomas" -- confirmed via
    # `lookup_city_state("St. Thomas")` returning None), so the general
    # wordninja/Census-table path can never resolve this on its own; a
    # manual override is the right fix, not a gap in that path.
    "pub-stthomas.escribemeetings.com": KnownJurisdiction("St. Thomas", "city", "ON"),
    # Toronto Catholic District School Board, ON -- the one confirmed
    # real eScribe tenant whose domain carries NO "pub-" prefix at all
    # (confirmed live 2026-08-30: `tcdsbpublishing.escribemeetings.com`
    # returns 200 with real content; `pub-tcdsbpublishing...` times out).
    # See escribe.py's `_NO_PREFIX_SUBDOMAINS` for why this domain's own
    # subdomain-fallback extraction needed a narrow, allowlisted fix
    # rather than a general "pub-" made optional -- this registry entry
    # supplies the name regardless of whether that fallback ever fires.
    "tcdsbpublishing.escribemeetings.com": KnownJurisdiction(
        "Toronto Catholic District School Board", "school board", "ON"
    ),
    # Ringwood, NJ (ringwoodtv.viebit.com) -- WO-71, 2026-08-30. BACKLOG.md's
    # "A real, previously undocumented jurisdiction" entry found a real
    # redtaperecordings.com page (source: this exact host, confirmed live by
    # fetching the page and following its "View original source" link) had
    # been mis-tagged "New York City, NY" by viebit.py's old hardcoded
    # single-jurisdiction assumption -- Viebit is a multi-tenant product,
    # not an NYC-only one, and this is the second confirmed non-NYC tenant.
    # "Ringwood" is nationally ambiguous -- also real as a town in OK and a
    # village in IL (confirmed via app/utils/jurisdiction_data/places.csv),
    # so a bare name lookup stays deliberately ambiguous; this domain is
    # tied to one verified real instance instead: ringwoodnj.net (the
    # Borough of Ringwood, NJ's own official site) links this exact Viebit
    # channel as "Ringwood TV". `validated_subdomain_extract()` doesn't
    # resolve this on its own -- the "ringwoodtv" label doesn't validate
    # against the Census table via any tier (confirmed live) -- so a
    # registry entry is the only real option here, same reasoning as
    # dallascounty.civicweb.net above. Typed "city" (not "borough"), same
    # convention as every other general-purpose-municipal-government entry
    # in this table (see Orion Township, MI's own comment) -- `type` here
    # only ever selects which lookup table matters, never a government's
    # literal legal designation.
    "ringwoodtv.viebit.com": KnownJurisdiction("Ringwood", "city", "NJ"),
    # Lake Washington School District, WA (WO-76, 2026-08-30) --
    # lwsd.granicus.com's real meeting pages are branded "Lake Washington
    # School District" (confirmed live: fetched a real ViewPublisher page,
    # `<title>Dr. Kimball's Messages</title>`, whose own body text names
    # "Lake Washington School District"; the district's real site,
    # www.lwsd.org, confirms it), NOT the city of Lake Washington itself --
    # there is no such city. "Lake Washington" bare validates as a
    # different, real but tiny and obscure Census county SUBDIVISION
    # ("Lake Washington township, ND" -- confirmed via
    # `county_subdivisions.csv`), which is what the module's own text/
    # subdivision-fallback validation used to (wrongly) repair a bare
    # "Lake Washington" into: "Lake Washington, ND". No general table of
    # US school districts exists in this module (same documented gap as
    # Swagit's own school-district coverage elsewhere in this repo) and
    # `lwsd` itself is a bare acronym `_validated_label_extract_with_state()`
    # can't validate on its own (confirmed: no tier resolves it), so
    # there's no independent subdomain-derived signal to cross-check
    # against either -- unlike Case 1/2 of the same investigation, this is
    # a targeted, evidence-backed override, not a structural fix (see
    # WO-76's own writeup for why a general "prefer the well-known
    # special-purpose entity over an obscure subdivision-table collision"
    # mechanism isn't buildable from one example). "authoritative" since
    # the bare-name validation this domain would otherwise produce is
    # confirmed wrong, not merely missing -- same bar every other
    # authoritative entry in this table meets.
    "lwsd.granicus.com": KnownJurisdiction(
        "Lake Washington School District", "district", "WA", strength="authoritative"
    ),
    # Oxford County, ON (WO-77, 2026-08-30) -- same "real place name
    # collides across two countries" shape as the Douglas MI case above,
    # but structurally different: there ISN'T a genuine two-candidate
    # collision inside this module's own tables to disambiguate between.
    # Oxford County, ME is the ONLY "Oxford County" row `counties.csv`
    # carries at all -- Oxford County, ON (a real upper-tier Ontario
    # county, confirmed live via `pub-oxfordcounty.escribemeetings.com`'s
    # own page: header "COUNTY OF OXFORD COUNCIL", address "21 Reeve
    # Street, Woodstock", real site www.oxfordcounty.ca, and real by-laws
    # naming its constituent lower-tier municipalities "Township of
    # Zorra", "Township of Blandford-Blenheim", "Town of Ingersoll", and
    # "City of Woodstock" -- Woodstock is Oxford County's own county seat,
    # which is why "Woodstock" appears in this archived page's own
    # slug/title) has no row in ANY table this module loads: Canadian
    # "counties" aren't census subdivisions (so build_canada_places()'s
    # Level-4 SGC import never reaches them, same gap
    # build_canada_regional_municipalities()'s own module comment already
    # documents for Ontario's regional municipalities -- Oxford just isn't
    # one of the three, Durham/Peel/Waterloo, confirmed live as customers
    # there), and this repo has no Canadian-counties table at all. So
    # `_validated_label_extract_with_state("pub-oxfordcounty")` validates
    # ONLY against the US county table (tier 2, spaced "Oxford County"),
    # returns a bare hint with no `hint_state` (the label itself spells
    # out no province code the way "douglas-mi" does), and
    # `_subdomain_override()`'s own `_fill_missing_state()` call then
    # confidently -- and uniquely, since ME is the only candidate that
    # exists -- resolves the missing state to ME. No disagreeing
    # `hint_state` exists to override it with, unlike Douglas MI, so
    # WO-76's own mechanism can't reach this case: the fix has to supply
    # the missing Canadian county as an independent fact instead of
    # correcting between two already-present candidates. Not generalized
    # into `counties.csv`/`build_jurisdiction_data.py` for the same
    # "verify before generalizing" reason `_ONTARIO_REGIONAL_
    # MUNICIPALITIES`'s own comment gives: this is the one real confirmed
    # Canadian county-shaped eScribe tenant found so far, and adding a
    # broader Canadian-counties table needs the same kind of grep-the-
    # real-downloaded-source-file confirmation that comment describes,
    # not a guess at which other Ontario counties might also need it.
    # "authoritative" since the page's own repaired jurisdiction (a real,
    # confirmed-live production row) is confidently wrong -- "Oxford
    # County, ME" -- not merely missing, same bar every other
    # authoritative entry in this table meets.
    "pub-oxfordcounty.escribemeetings.com": KnownJurisdiction(
        "Oxford County", "county", "ON", strength="authoritative"
    ),
}


def lookup_by_domain(netloc: str) -> Optional[KnownJurisdiction]:
    return _KNOWN_DOMAINS.get(netloc.lower())


def known_jurisdiction_display(netloc: str) -> Optional[str]:
    """Full "{Type} of {Name}, {State}" string for a domain in
    `_KNOWN_DOMAINS`, e.g. "City of Salt Lake City, UT". Unlike
    `resolve_state()`/`enrich_jurisdiction_text()` (which only ever fill
    in a missing *state* for a name the caller already extracted from
    page text), this replaces the name too -- for the rare domain where
    that page-text extraction has itself been confirmed unreliable (only
    `slc.primegov.com` today, see the `_KNOWN_DOMAINS` entry above), a
    caller should prefer this over trusting its own text extraction on
    that specific domain, not just fall back to it when the extraction
    finds nothing."""
    known = lookup_by_domain(netloc)
    if not known:
        return None
    # A special-purpose entity ("authority"/"district" -- see
    # KnownJurisdiction.type) or a name that already carries its own type
    # word as a suffix without being a literal gazetteer name ("Ventura
    # County") renders as-is: "County of Ventura County" and "City of
    # Contra Costa Transportation Authority" are exactly the doubled/
    # mistyped shapes this guard exists to prevent. A literal real name
    # that happens to end in its type word ("Salt Lake City") still gets
    # the prefix -- "City of Salt Lake City, UT" is that government's
    # own established display form here.
    ends_with_type = re.search(rf"\b{known.type}$", known.name, re.IGNORECASE)
    if known.type not in ("city", "county", "town") or (
        ends_with_type and not is_literal_known_place(known.name)
    ):
        return f"{known.name}, {known.state}"
    return f"{known.type.capitalize()} of {known.name}, {known.state}"


def resolve_state(
    name: Optional[str],
    jurisdiction_type: str,
    *,
    netloc: Optional[str] = None,
    page_text: Optional[str] = None,
) -> Optional[str]:
    """Best-effort state for a jurisdiction an adapter has already
    extracted a name and TYPE for (`jurisdiction_type`: "county" or
    "city" -- never inferred here, must come from the caller's own
    real page-text classification, e.g. Granicus's existing "County of
    X"-vs-"City of X" regex branches). Tries, in priority order:
    1. A confirmed domain match (`lookup_by_domain()`) -- resolves even a
       nationally-ambiguous name, since it's tied to one verified real
       instance.
    2. An unambiguous name lookup against the matching type's table.
    3. A ZIP-anchored address found in `page_text`, cross-referenced
       against the SAME type's ZCTA crosswalk -- never the city crosswalk
       for a county lookup even though the address's own city name is
       right there in the same match (see module docstring's Sonoma
       County example for why).
    Returns None, never a guess, when nothing above confidently resolves.
    """
    if netloc:
        known = lookup_by_domain(netloc)
        if known and known.type == jurisdiction_type:
            return known.state

    # A bare name that IS ITSELF a full US state/Canadian province name
    # (e.g. "Colorado", "Ontario") never needs -- or gets -- a state
    # appended: it already names the top-level jurisdiction, so there is
    # nothing to look up. Real, confirmed-live bug this prevents (WO-76,
    # 2026-08-30): a bare "Colorado" (this app's own stored jurisdiction
    # for coloradoga.granicus.com, the real Colorado General Assembly --
    # its own page header literally reads "Colorado General Assembly")
    # has no entry in `_PLACE_STATES` but DOES coincidentally match
    # `_COUNTY_STATES` ("Colorado County, TX") and, via `lookup_city_
    # state()`'s own WO-16 subdivision fallback (see that function's
    # docstring), `_SUBDIVISION_STATES` ("Colorado township, KS" -- real,
    # but a tiny, obscure Kansas township, not remotely what a page about
    # the state legislature means). Without this guard, `name_lookup()`
    # below picks the Kansas township and silently attaches ", KS" --
    # not just probably wrong but geographically incoherent, since a US
    # state is never a constituent part of a member place/county/
    # subdivision of a DIFFERENT state. There is no real government at any
    # level that legitimately needs a two-letter state suffix glued onto a
    # bare state/province name, so this guard is general and safe, not a
    # one-off patch for Colorado alone -- it protects any other state name
    # that happens to also collide with some obscure place/county/
    # subdivision elsewhere (plausible; not separately audited one by
    # one) for free. `_STATE_NAME_TO_ABBR_LOWER`/`_PROVINCE_NAME_TO_ABBR_
    # LOWER` (defined further down this module) are the same tables
    # `resolve_claimed_state()` already trusts for "does the source text
    # name a real state/province" -- reused here, not duplicated.
    if name and name.strip().lower() in _STATE_NAME_TO_ABBR_LOWER:
        return None
    if name and name.strip().lower() in _PROVINCE_NAME_TO_ABBR_LOWER:
        return None

    name_lookup = (
        lookup_county_state if jurisdiction_type == "county" else lookup_city_state
    )
    if name:
        state = name_lookup(name)
        if state:
            return state

    if page_text:
        zip_lookup = (
            lookup_county_by_zip
            if jurisdiction_type == "county"
            else lookup_place_by_zip
        )
        for _city, _state, zip_code in find_zip_addresses(page_text):
            result = zip_lookup(zip_code)
            if result:
                return result[1]

    return None


_TYPE_HINT_RE = re.compile(r"\b(?:county|parish)\b", re.IGNORECASE)


def enrich_jurisdiction_text(
    jurisdiction: Optional[str],
    *,
    netloc: Optional[str] = None,
    page_text: Optional[str] = None,
    placeholder: Optional[str] = None,
) -> Optional[str]:
    """Convenience wrapper around `resolve_state()` for the common shape
    every free-text adapter's own jurisdiction extraction already has: a
    string like "City of San Diego" or "Sonoma County", built from page
    text, with no state. This is the one place that "append a state if
    confidently found" logic lives, shared across every adapter that
    calls it, rather than being copy-pasted per adapter (Granicus,
    Legistar, PrimeGov, eScribe, CivicWeb, and LIMS all had the identical
    shape -- see BACKLOG.md's "no-state jurisdiction audit").

    Type (county vs. city) is read directly from whether "County"/
    "Parish" appears in `jurisdiction` itself -- see `resolve_state()`'s
    own docstring for why that's never inferred from a ZIP lookup
    instead. Returns `jurisdiction` unchanged if it's falsy, already has
    a comma (a state-shaped suffix already present, from whatever
    produced it -- e.g. a subdomain-guessing fallback with its own
    state-suffix detection), or matches `placeholder` (a caller's own
    "nothing found" sentinel, e.g. Granicus's "Unknown Jurisdiction") --
    none of those are real names worth a lookup attempt.
    """
    if not jurisdiction or "," in jurisdiction or jurisdiction == placeholder:
        return jurisdiction
    jurisdiction_type = "county" if _TYPE_HINT_RE.search(jurisdiction) else "city"
    state = resolve_state(
        jurisdiction, jurisdiction_type, netloc=netloc, page_text=page_text
    )
    return f"{jurisdiction}, {state}" if state else jurisdiction


# --- Validation, repair, and ingest-time finalization (2026-08-15) ---
#
# Everything above this point answers "given a name, what's its state" --
# built and proven first (see BACKLOG_DONE.md's "no-state jurisdiction
# audit"). This section answers a different, later question this repo's
# own audit surfaced: "is the *name itself* trustworthy at all, and can a
# broken one be repaired automatically." Design and the real data behind
# it (all 649 archived jurisdictions, an extraction-convention tournament,
# a baseline-validation pass) live in JURISDICTION_METADATA_PLAN.md --
# this is the implementation, not a fresh design.
#
# Single entry point: `finalize_jurisdiction()`, called once at ingest
# time (archive/db/crud.py's `_find_or_create_page()`), not per-adapter --
# see BACKLOG.md's "Future refactor, deliberately deferred" entry for why
# this is deliberately NOT wired into every adapter's own extraction path.

_COUNTY_TYPE_HINT_RE = re.compile(r"\b(?:county|parish|borough)\b", re.IGNORECASE)
_STATE_SUFFIX_RE = re.compile(r",\s*([A-Za-z]{2})\.?\s*$")
# Leading-date bleed (2026-08-18, confirmed live: "6/16/25 Bellefonte
# Borough", "8/6/25 State College Borough") -- a bleed DIRECTION
# `_trim_repair()` below has zero handling for, since it only ever trims
# from the right. Narrow and specific enough (M/D/YY date shape) to run
# unconditionally as a preprocessing step: no real jurisdiction name starts
# with a bare date, so this is a no-op on every string that doesn't have
# this exact bleed.
_LEADING_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}\s*[-–]?\s*")
# Glued file-extension bleed (2026-08-18, confirmed live: "Township of
# Brock.pdf Pulled from Council Information Index..." -- a Canadian
# eScribe/CivicWeb agenda page listing an attachment filename inline, no
# space before the extension). `_trim_repair()` cuts on whitespace tokens,
# so ".pdf" glued directly onto "Brock" means no cut ever lands on a clean
# "Brock" -- inserting a space before the extension lets the EXISTING
# trim-repair/_looks_like_bleed() logic handle the rest unchanged. Same
# no-op-when-absent reasoning as the date regex above: no real jurisdiction
# name contains a bare recognized office-document extension.
_GLUED_EXTENSION_RE = re.compile(r"(?<=[a-zA-Z])\.(pdf|docx?|xlsx?|pptx?)\b")
# Bare government-type words -- if an attempted split leaves nothing but
# one of these as the "body," it isn't a real entity name, just the
# ordinary "Type of Name" shape (e.g. "City of Boston") that should never
# be split in the first place.
_BARE_TYPE_WORDS = {
    "city",
    "county",
    "town",
    "township",
    "village",
    "borough",
    "parish",
}


def _is_bare_type_phrase(body: str) -> bool:
    """True for "City", "The City", "City and County", "The County" --
    every real word in `body` (ignoring a leading "the" and any "and") is
    just a government-type word, so there's no real distinct entity to
    split off. Real bug caught testing against all 649 archived rows:
    the original single-word check only caught bare "City"/"County" and
    missed "The City of Memphis" / "City and County of Denver" / "City
    and County of San Francisco" -- each would have split off a
    meaningless "The City"/"City and County" body instead of leaving the
    already-fine jurisdiction whole."""
    words = re.sub(r"^the\s+", "", body, flags=re.IGNORECASE).lower().split()
    words = [w for w in words if w != "and"]
    return bool(words) and all(w in _BARE_TYPE_WORDS for w in words)


# Page-authored abbreviations for a name's real Census-canonical form --
# the same set `_STOPRULE_ABBREV_OK` (below) treats as "not a real
# sentence-ending period," but here for the opposite purpose: expanding
# them so a page-abbreviated name like "Ft. Worth"/"Mt. Vernon"/"N. Las
# Vegas" actually MATCHES the Census table's own "Fort Worth"/"Mount
# Vernon"/"North Las Vegas" entry, rather than failing validation just
# because a real website chose the abbreviated spelling (same underlying
# fact the stop rule's exception list exists for, applied here to lookup
# instead of parsing).
_ABBREV_EXPANSIONS = {
    "st": "saint",
    "ste": "sainte",
    "ft": "fort",
    "mt": "mount",
    "pt": "point",
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
}
_ABBREV_WORD_RE = re.compile(
    r"\b(" + "|".join(_ABBREV_EXPANSIONS) + r")\.?(?=\s|$)", re.IGNORECASE
)


def _expand_abbreviations(name: str) -> str:
    def _replace(m: "re.Match") -> str:
        expansion = _ABBREV_EXPANSIONS[m.group(1).lower()]
        return expansion.capitalize() if m.group(1)[0].isupper() else expansion

    return _ABBREV_WORD_RE.sub(_replace, name)


# The opposite direction of `_ABBREV_EXPANSIONS`, needed for exactly one
# prefix family: confirmed by grepping the real Census places table
# directly (2026-08-16), "St."/"Ste." is the ONLY one of the six
# abbreviations above where the table itself stores the *abbreviated*
# form (148 real "St. " rows, zero "Saint " rows) -- "Fort"/"Mount"/
# "North"/"South"/"East"/"West" are all stored spelled out (0 abbreviated
# rows for any of them), which is exactly what `_expand_abbreviations()`
# already handles. A page/adapter that spells out "Saint Paul" (a
# genuinely common real spelling, not a typo) would otherwise never
# match the table's "St. Paul city" key in either direction.
_SAINT_CONTRACTIONS = {"saint": "st.", "sainte": "ste."}
_SAINT_WORD_RE = re.compile(
    r"\b(" + "|".join(_SAINT_CONTRACTIONS) + r")\b", re.IGNORECASE
)


def _contract_saints(name: str) -> str:
    def _replace(m: "re.Match") -> str:
        contraction = _SAINT_CONTRACTIONS[m.group(1).lower()]
        return contraction.capitalize() if m.group(1)[0].isupper() else contraction

    return _SAINT_WORD_RE.sub(_replace, name)


# Hawaiian ʻokina and similar typographic apostrophe glyphs a real page
# may use in a diacritic-bearing name ("Kauaʻi") that the Census table
# itself never carries (confirmed: table key is plain "kauai") -- stripped
# as its own candidate tier rather than folded into `_normalize_name()`,
# since that function also normalizes the table's OWN keys, which never
# contain these characters in the first place.
_OKINA_CHARS = "ʻʼ''`"
_OKINA_RE = re.compile("[" + re.escape(_OKINA_CHARS) + "]")


def _strip_okina(name: str) -> str:
    return _OKINA_RE.sub("", name)


def _table_lookup(name: str) -> Optional[Tuple[str, List[str]]]:
    """(table, states) if any normalization candidate of `name` is a real
    known place or county name -- ambiguous (multi-state) still counts as
    "known" here, since this validates the NAME, not the state (a
    separate, already-solved problem above). Checks the county table
    first when the name itself says county/parish/borough, mirroring
    `enrich_jurisdiction_text()`'s own type-detection, so "York County"
    matches the real county instead of one of the 5 unrelated places
    named "York". Also tries an abbreviation-expanded form
    (`_expand_abbreviations()`), a "Saint"->"St."-contracted form
    (`_contract_saints()`), and an ʻokina/apostrophe-stripped form
    (`_strip_okina()`) when the raw name doesn't match as-is.

    Thin wrapper around `_table_lookup_strength()` that drops the
    strength flag -- every caller except `_trim_repair()` only needs the
    plain validity answer."""
    hit = _table_lookup_strength(name)
    return (hit[0], hit[1]) if hit else None


def _table_lookup_strength(name: str) -> Optional[Tuple[str, List[str], bool]]:
    """Same as `_table_lookup()`, plus a third element: whether the match
    came from `name`'s own literal text (as typed, or with only a
    deterministic leading "City of "/"County of "/etc. removed) rather
    than a secondary, coincidental normalization -- a trailing generic
    type-word strip, an abbreviation expansion, a "Saint"->"St."
    contraction, or an ʻokina strip. `_trim_repair()` uses this
    distinction to tell a genuine, literal place-name match (safe to stop
    the search on) apart from a match that only exists because a
    trailing word happened to look like a type word (not safe to stop
    on, since it may be incidental -- see `_trim_repair()`'s own comment
    for the real "East Providence City" case this exists for: the
    literal text "East Providence City" isn't a real place, it only
    "matches" via the secondary trailing-"City"-stripped candidate
    "East Providence", which is coincidental here since "City" is really
    the start of "City Council" in the surrounding sentence, not part of
    the entity name)."""
    name = name.strip().rstrip(".,;:")
    if not name:
        return None
    county_first = bool(_COUNTY_TYPE_HINT_RE.search(name))
    # Subdivisions checked last regardless of county_first -- a real city
    # or county name should always win over a same-named township (rare,
    # but e.g. many townships share a name with a nearby borough/city in
    # the same state), and no confirmed real case needs it to outrank
    # either.
    tables = (
        [("county", _COUNTY_STATES), ("place", _PLACE_STATES)]
        if county_first
        else [("place", _PLACE_STATES), ("county", _COUNTY_STATES)]
    ) + [("subdivision", _SUBDIVISION_STATES)]
    base_candidates = _normalize_candidates(name)
    # Only the FIRST base candidate is the literal/deterministic form --
    # `_normalize_candidates()` puts the as-is (or leading-type-stripped)
    # form first and only appends a second, trailing-type-stripped
    # candidate as a fallback (see its own docstring). Everything past
    # index 0 here, plus every abbreviation/saint/okina candidate below,
    # is a secondary/heuristic candidate.
    primary_candidate = base_candidates[0] if base_candidates else None
    candidates = list(base_candidates)
    expanded = _expand_abbreviations(name)
    if expanded != name:
        candidates.extend(_normalize_candidates(expanded))
    contracted = _contract_saints(name)
    if contracted != name:
        candidates.extend(_normalize_candidates(contracted))
    de_okina = _strip_okina(name)
    if de_okina != name:
        candidates.extend(_normalize_candidates(de_okina))
    # Consolidated city-county government spellings ("Louisville /
    # Jefferson County Metro" -> the Census key's own "louisville/
    # jefferson county") -- see `_QUERY_GOVERNMENT_TYPE_RE`'s comment.
    # Tried as a combination (slash collapsed AND government-type word
    # stripped) as well as each alone, since a real page may only need
    # one of the two.
    slash_normalized = _normalize_slash_spacing(name)
    gov_stripped = _QUERY_GOVERNMENT_TYPE_RE.sub("", name)
    combined = _QUERY_GOVERNMENT_TYPE_RE.sub("", slash_normalized)
    for variant in (slash_normalized, gov_stripped, combined):
        if variant != name:
            candidates.extend(_normalize_candidates(variant))
    for candidate in candidates:
        for label, table in tables:
            if candidate in table:
                return (
                    label,
                    sorted(set(table[candidate])),
                    candidate == primary_candidate,
                )
    return None


_ROMAN_NUMERAL_RE = re.compile(r"\b[IVXLC]{2,6}\.?\b")

# Residual gap fix, 2026-08-17 (BACKLOG.md's "Jurisdiction-bleed, confirmed
# cross-platform" entry): a discarded tail that's pure Title-Case/ALL-CAPS
# prose (e.g. "Legacy Business PLEDGE OF PUBLIC", "City Commission Regular
# Meeting AGENDA Thursday") has zero lowercase/digit/roman-numeral signal,
# so it used to slide past every check above undetected -- confirmed live
# on 7 real Granicus/eScribe bleed cases (Sarasota, Hollywood, Hampton,
# Gainesville, Kelowna, Delta, New Westminster -- see that entry). By the
# time this constant is even consulted, every word in `tail` already
# starts uppercase (any lowercase-initial word already returned True
# above), so "N-or-more consecutive Title-Case/ALL-CAPS words" collapses
# to a plain word-count check on the whole tail.
#
# 4 is not a guess: it's the exact gap between the shortest confirmed real
# bleed tail (4 words -- Sarasota's "Legacy Business PLEDGE OF", Hampton's
# "Zoning Ordinance Regarding Standa") and the longest real tail that must
# NOT trigger a trim (3 words -- "Washington School District" off "Lake"
# and "Area Headquarters Authority" off "Bay", both real legitimately-long
# names already covered by
# test_finalize_jurisdiction_never_trims_a_legitimately_long_real_name()/
# test_extract_jurisdiction_chain_rejects_a_capitalization_walk_false_positive(),
# both re-verified against this exact constant before it was picked).
# Known, honestly-flagged residual gap this threshold does NOT close on its
# own: a handful of confirmed real bleed cases have a tail of only 1-2
# words (Brampton's "Meeting", Castle Rock's "Authorizing") -- too short to
# distinguish from a legitimate short suffix with this signal alone. Two of
# these ("Meeting", and Peterborough's "Attachments") are now closed via
# `_KNOWN_JUNK_TAIL_WORDS` below instead -- a closed, curated stoplist
# rather than lowering this threshold (confirmed by direct testing that
# lowering it would also wrongly trim real long names, e.g. "Lake
# Washington School District" -> "Lake"). Anything not on that stoplist
# (Castle Rock's "Authorizing" included) stays unrepaired rather than
# risking the false-positive side (see BACKLOG.md for the honest
# accounting of what's still open).
_MIN_BLEED_WORD_RUN = 4

# Residual gap fix #2, 2026-08-17 (same investigation as
# `_MIN_BLEED_WORD_RUN` above, found via the bleed-backfill-candidates
# audit): the word-count tier is one-sided -- it only has NEGATIVE
# evidence for bleed, nothing that tells a real, long government-entity
# name apart from real bleed prose that's coincidentally also all
# Title-Case/ALL-CAPS. Confirmed real, live case this breaks: "St. Johns
# River Water Management District, FL" -- "St. Johns" validates as a real
# place, and its tail "River Water Management District" (4 words) is
# indistinguishable BY SHAPE ALONE from "Legacy Business PLEDGE OF
# PUBLIC" -- both are 4+ Title-Case/ALL-CAPS words. This adds positive
# evidence: does the tail's own ending look like a real government-body
# or special-district TYPE, rather than agenda/sentence prose?
#
# Every entry below is grounded in a real, already-archived jurisdiction
# name (via this app's own live data, not invented) -- see
# `_ends_with_known_entity_suffix()`'s docstring for the specific real
# examples behind each one.
#
# Deliberately biased toward OVER-protecting, not under-protecting, per
# the explicit call on this: a plain trailing-word check like this can
# occasionally spare a genuine bleed tail that happens to end in one of
# these words (leaving a bit of extra, cosmetic noise on the meeting-BODY
# portion of the name), but that's a strictly smaller mistake than the
# alternative -- trimming through to a shorter, wrong CITY. No real case
# in the 652-row bleed-backfill-candidates corpus was found where this
# list wrongly protects a genuine bleed tail (every currently-correct
# trim's discarded tail ends in an agenda/prose word, not one of these --
# see tests).
_ENTITY_TYPE_SUFFIX_WORDS = {
    # District: St. Johns River Water Management District (the case this
    # was built for), Sioux City Community School District, Travis
    # Central Appraisal District, Lake Washington School District.
    "district",
    # Authority: Bay Area Headquarters Authority, Capital Metropolitan
    # Transportation Authority, Albuquerque Bernalillo County Water
    # Utility Authority.
    "authority",
    # Commission: Washington Suburban Sanitary Commission, Metropolitan
    # Airports Commission.
    "commission",
    # Government: Lexington-Fayette Urban County Government.
    "government",
    # Schools/School: Pelham Public Schools, Cecil County Public Schools
    # ("Schools"); Lake Washington School District ("School", also
    # covered by "district" above).
    "schools",
    "school",
    # Transit: VIA Metropolitan Transit.
    "transit",
    # Utility: Albuquerque Bernalillo County Water Utility Authority
    # (also covered by "authority", kept as its own entry since a page
    # could plausibly truncate right after "Utility").
    "utility",
    # ISD/USD/CISD: a real, common Texas/California independent/unified
    # school-district acronym, confirmed repeatedly in this app's own
    # live archive -- Birdville/Carroll/Dallas/Del Valle/Frisco/Garland/
    # Round Rock/Lake Travis/Richardson/Plano ISD (all TX), Bonita/Conejo
    # Valley/Yorba Linda USD (all CA), Lamar CISD (TX). Bare "SD"/"FD"/
    # "PD" deliberately excluded -- no confirmed real archived example of
    # any of those as a trailing acronym was found (only a false-positive
    # risk: "White Rock, SD" is South Dakota's state abbreviation, not a
    # school-district acronym), so adding them would be guessing rather
    # than grounding in real data, the one thing this whole fix is
    # built not to do.
    "isd",
    "usd",
    "cisd",
}
# Two-word committee-name endings -- confirmed real in this app's own
# archive (Guelph's "Committee of Adjustment", Kenora's "Committee of
# the Whole", both currently correctly protected already, but only via
# the lowercase-word signal catching their "of"/"the"). Listed here too
# as defense for the ALL-CAPS spelling of either ("COMMITTEE OF
# ADJUSTMENT"/"COMMITTEE OF THE WHOLE") which would otherwise have zero
# negative bleed signal left to catch it -- not yet observed in ALL-CAPS
# form for these two specifically, but the same lowercase-signal blind
# spot `_MIN_BLEED_WORD_RUN` itself exists to close for ordinary prose
# bleed, applied here defensively rather than waiting for an incident.
_ENTITY_TYPE_SUFFIX_PHRASES = (
    "committee of adjustment",
    "committee of the whole",
)


def _ends_with_known_entity_suffix(tail: str) -> bool:
    """True when `tail` (a candidate trim-discard, already confirmed to
    be all Title-Case/ALL-CAPS with no lowercase/digit/roman-numeral
    signal by the time this is consulted -- see `_looks_like_bleed()`)
    itself ENDS WITH a real government-body/special-district type word or
    phrase, rather than merely containing one anywhere. End-anchored on
    purpose: real confirmed bleed can legitimately contain one of these
    words mid-tail without the tail actually being a real entity-type
    name -- e.g. Kenora's real bleed case "Committee of the Whole Agenda
    Thursday" contains "Committee" but correctly ends in "Agenda
    Thursday", so a "contains" check would have wrongly protected it. An
    "ends with" check does not."""
    words = tail.split()
    if not words:
        return False
    lowered = " ".join(w.strip(".,;:").lower() for w in words)
    if any(lowered.endswith(phrase) for phrase in _ENTITY_TYPE_SUFFIX_PHRASES):
        return True
    last = words[-1].strip(".,;:").lower()
    return last in _ENTITY_TYPE_SUFFIX_WORDS


# Residual gap fix #3, 2026-08-18: a closed, curated stoplist of confirmed
# trailing junk words -- the inverse of `_ENTITY_TYPE_SUFFIX_WORDS`
# above (that one PROTECTS a short tail from being trimmed; this one
# AUTHORIZES trimming a short tail that `_MIN_BLEED_WORD_RUN`'s word-count
# signal alone can't distinguish from a legitimate short suffix -- see its
# own comment on this exact gap). Every entry here is grounded in a real,
# confirmed-live bleed example, not guessed: "Peterborough Attachments" and
# "Brampton Meeting" (both found live on /coverage, 2026-08-18). Only ever
# fires on an EXACT match to a word already proven junk in real data, so
# unlike a general 1-2-word-tail rule (already rejected by
# `_MIN_BLEED_WORD_RUN`'s own comment -- it would also wrongly trim real
# long names down to a single word) it can't make that same mistake.
#
# Widened 2026-08-28 from "the WHOLE tail is exactly one junk word" to
# "the tail's LAST word is a known junk word" (still gated to tails under
# `_MIN_BLEED_WORD_RUN`, and still the same closed stoplist -- see
# `_looks_like_bleed()`) after two real, independently-confirmed cases hit
# the same gap in the old narrower form: `Snoqualmie Washington Meetings`
# (`/j/snoqualmie-washington-meetings`, tail "Washington Meetings") and
# PrimeGov's `lasvegas.primegov.com` name-tail overrun (`_extract_
# jurisdiction()` in `primegov.py` returning "City of Las Vegas Internet
# Address" from a real page footer, "City of Las Vegas Internet Address:
# www.lasvegasnevada.gov" -- tail "Internet Address"). Both tails are 2
# words, below the word-count floor, and neither the old 1-word check nor
# `_ends_with_known_entity_suffix()` (only consulted at 4+ words) covered
# them -- `_trim_repair()` found the correct literal prefix
# ("Snoqualmie"/"City of Las Vegas") both times and declined anyway
# because the tail didn't look like bleed. "meetings"/"address" added as
# new grounded entries; the widened last-word check doesn't loosen WHICH
# words authorize a trim, so the existing "Town of Castle Rock
# Authorizing"/real-long-name guard tests are unaffected -- "authorizing"/
# "district"/"authority"/etc. still aren't on this list.
_KNOWN_JUNK_TAIL_WORDS = {"attachments", "meeting", "meetings", "address"}


def _looks_like_bleed(tail: str) -> bool:
    """Sanity check on text a trim would discard: does it look like
    sentence/agenda bleed (lowercase prose, roman-numeral list markers,
    digits, or an unusually long run of Title-Case/ALL-CAPS words with no
    real government-entity-type ending) rather than part of a real
    longer name? Confirmed against the 2026-08-15 audit's full
    "repaired_by_trim" bucket (73 cases): every one of the 16 cases the
    original (pre-2026-08-17) signals flagged was a correct repair, and
    every one of the 57 they left alone was a real, legitimately long
    name (e.g. "Bay Area Headquarters Authority") that a bare trim would
    have mangled -- so this gate is required, not optional, for the trim
    below to be safe. The word-count tier added 2026-08-17
    (`_MIN_BLEED_WORD_RUN`) is calibrated the same way, against real
    confirmed Title-Case/ALL-CAPS bleed tails and the real
    legitimately-long names that must stay untouched -- see that
    constant's own comment for the exact evidence. The entity-type-suffix
    check added later the same day (`_ends_with_known_entity_suffix()`)
    is the positive-evidence counterpart to the word-count tier -- see
    its own and `_ENTITY_TYPE_SUFFIX_WORDS`'s comments for why and the
    real data behind it."""
    if _ROMAN_NUMERAL_RE.search(tail):
        return True
    if re.search(r"\d", tail):
        return True
    words = tail.split()
    if not words:
        return False
    # Real bug fixed 2026-08-19 (BACKLOG.md's jurisdiction-misattribution
    # entry): a discarded tail that STARTS with "of" is never bleed --
    # confirmed live via "The Village of Douglas, Michigan" (Douglas, MI's
    # own real self-branding; Michigan officially designates it a Village,
    # not a City) getting wrongly repaired to "The Village", a real but
    # totally unrelated Oklahoma City suburb literally named "The
    # Village". The cut landed right before "of Douglas, Michigan", and
    # the plain lowercase-initial-word signal below treated that "of" as
    # proof of agenda-prose bleed. "of" is never ordinary prose in this
    # module's own vocabulary -- it is the one structural connector every
    # OTHER jurisdiction-naming mechanism here already keys off of
    # (`_LEADING_TYPE_RE`, `_split_entity_prefix()`, `_STOPRULE_TRIGGER_RE`,
    # `_CHAIN_TAG_JURISDICTION_RE` all treat "<Type> of <Name>" as a real
    # entity-naming pattern, never text to discard). A tail immediately
    # starting with "of" means the untrimmed text reads "<candidate> of
    # <continuation>" -- exactly the shape of a real, longer government
    # name ("Village of X", "Housing Authority of the County of Y"), not
    # bleed. Declining here (returning False) means `_trim_repair()` gives
    # up on this cut rather than accepting a coincidental short match --
    # the same conservative, "leave it unverified rather than mangle it"
    # outcome already established for a literal match with a non-bleed
    # tail elsewhere in this function (see East Bay/Richmond Hill in
    # tests/test_jurisdiction_enrich.py). No real confirmed case needs
    # this same exception for "the"/"and" -- kept narrow, grounded only in
    # the one real case found, per this repo's own "ground fixes in real
    # confirmed data" convention.
    if words[0].strip(".,;:").lower() == "of":
        return False
    if any(w[0].islower() for w in words if w):
        return True
    if len(words) < _MIN_BLEED_WORD_RUN:
        if words[-1].strip(".,;:").lower() in _KNOWN_JUNK_TAIL_WORDS:
            return True
        return False
    return not _ends_with_known_entity_suffix(tail)


def _trim_repair(name: str) -> Optional[Tuple[str, str]]:
    """Longest-valid-prefix repair: drop tokens from the right until the
    remainder validates, but only when the discarded tail itself looks
    like bleed (`_looks_like_bleed()`) -- never applied bare, since most
    of the audit's trim-reachable names were legitimate long entities a
    blind trim would have destroyed. Returns (repaired_name, table) or
    None.

    Stops at the FIRST (longest) prefix whose match is a genuine, literal
    match -- not a secondary/heuristic one (see `_table_lookup_strength()`)
    -- and decides right there: accepts it if its tail looks like bleed,
    otherwise gives up without trimming rather than falling through to a
    shorter, more-likely-spurious prefix. A prefix that only validates
    via a secondary/heuristic candidate (trailing generic-type-word
    strip, abbreviation expansion, etc.) does NOT stop the search on its
    own when its tail doesn't look like bleed -- that match may be
    coincidental, so scanning continues to shorter cuts looking for
    either a literal match or a heuristic match with a genuinely
    bleed-shaped tail.

    Real bug fixed 2026-08-17, found via the bleed-backfill-candidates
    audit: with the old "keep scanning shorter cuts regardless" behavior,
    "Richmond Hill Single Source Award" correctly rejected the cut=2
    prefix "Richmond Hill" (a real, LITERAL place-name match, tail
    "Single Source Award" is only 3 words, not bleed) but then kept
    going to cut=1 "Richmond" (also a literal match, tail "Hill Single
    Source Award" is 4 words -> bleed=True) and wrongly repaired to
    "Richmond" -- destroying "Richmond Hill", a real, different place.
    Same shape broke "East Bay Regional Park District, CA": cut=2 "East
    Bay" is a literal match, correctly rejected (tail "Regional Park
    District", 3 words, not bleed), then cut=1 "East" (a real OH
    township) wrongly fired, mangling a real, legitimately-long entity
    name. Both are literal matches, so stopping the search at the first
    one is correct and safe.

    The literal-vs-heuristic distinction matters for a real case that a
    blind "stop at any hit" would have broken: "East Providence City
    Council Live Stream". Its longest hit, cut=3 "East Providence City",
    only validates via the secondary trailing-"City"-stripped candidate
    "East Providence" (the literal text "east providence city" isn't a
    table key) -- "City" here is really the start of "City Council" in
    the surrounding text, not part of the entity name. Its tail ("Council
    Live Stream", 3 words) isn't bleed-shaped, so a blind stop-at-any-hit
    fix would give up entirely and leave the whole bled string alone.
    Since this hit is heuristic, not literal, the search instead keeps
    going to cut=2 "East Providence" -- a literal match whose tail ("City
    Council Live Stream", 4 words) IS bleed -- and correctly repairs to
    "East Providence".

    Net effect: strictly less aggressive than the pre-2026-08-17 code,
    never more -- every case the old code correctly repaired still hits
    either a literal match or the same longest bleed-tail heuristic match
    it always found, so nothing already-correct regresses (verified
    against the real bleed-backfill-candidates corpus, see tests +
    BACKLOG.md)."""
    tokens = name.split()
    for cut in range(len(tokens) - 1, 0, -1):
        prefix = " ".join(tokens[:cut]).rstrip(".,;:")
        if not prefix:
            continue
        hit = _table_lookup_strength(prefix)
        if not hit:
            continue
        table, states, is_primary = hit
        if _looks_like_bleed(" ".join(tokens[cut:])):
            return prefix, table
        if is_primary:
            return None
        # Heuristic (non-literal) match with a non-bleed tail: may be
        # coincidental (see docstring's East Providence example) -- keep
        # scanning shorter cuts instead of stopping here.
    return None


def _split_entity_prefix(name: str) -> Optional[str]:
    """ "<Entity> of <Jurisdiction>" -> body, when the jurisdiction half
    validates. Real example this exists for: "Housing Authority of the
    County of Santa Clara" -> body "Housing Authority", jurisdiction
    "County of Santa Clara" (which `_table_lookup()`/`_normalize_candidates()`
    already know how to resolve via the existing leading-"County of"
    strip). Tries the LEFTMOST " of " first and returns as soon as one
    validates -- for a name with more than one "of", the leftmost split
    keeps the most of the real jurisdiction phrase intact (preserving
    "County" rather than trimming down to a bare, more war-torn "Santa
    Clara"). Returns the body text only; the caller already has (or can
    re-derive) the validated jurisdiction half.

    Deliberately does NOT fire on the ordinary "City of Boston" shape --
    a split that would leave only a bare type word ("City"/"County"/etc.)
    as the body isn't a real entity, just this function accidentally
    re-parsing an already-fine name.
    """
    for m in re.finditer(r"\bof\b", name, re.IGNORECASE):
        body = name[: m.start()].strip().rstrip(",")
        if not body or _is_bare_type_phrase(body):
            continue
        candidate = name[m.end() :].strip()
        candidate = re.sub(r"^the\s+", "", candidate, flags=re.IGNORECASE)
        if candidate and _table_lookup(candidate):
            return body
    return None


@dataclass(frozen=True)
class JurisdictionResult:
    jurisdiction: Optional[str]
    meeting_body: Optional[str]
    # "authoritative" -- registry override, highest trust.
    # "validated"     -- name matches a real place/county as-is.
    # "repaired"      -- trim or entity-split recovered a valid name from
    #                    a bled/prefixed one.
    # "fallback"      -- registry fallback used because extraction was
    #                    blank or didn't validate.
    # "unverified"    -- kept as given; not in any table, but not
    #                    rejected either (school districts, MPOs, transit
    #                    authorities, and every other real entity type no
    #                    national table covers -- see BACKLOG.md's
    #                    "Deprioritized ideas" for why these stay
    #                    unverified rather than being forced to guess).
    # "blank"         -- nothing at all, before or after this function.
    confidence: str


def _fill_missing_state(name: str, existing_suffix: str, netloc: Optional[str]) -> str:
    """Real gap found live 2026-08-15 running the workstream-4 backfill
    dry run: a repaired/split name frequently has no state at all, not
    because none exists, but because the state-enrichment step upstream
    (`enrich_jurisdiction_text()`, run once at the adapter's own
    extraction time) tried to resolve a state for the BLED name before
    this function ever cleaned it up -- "City of Castle Pines History of
    Parks and Recreat" doesn't validate against any table, so that
    earlier attempt correctly found nothing and gave up, even though the
    real name it bled from ("Castle Pines") resolves to CO unambiguously
    on its own. Gives the now-clean name one more shot via the same
    `resolve_state()` used everywhere else, but only when no suffix
    already survived from the original raw string -- never overrides a
    state that was already there."""
    if existing_suffix:
        return existing_suffix
    jurisdiction_type = "county" if _COUNTY_TYPE_HINT_RE.search(name) else "city"
    state = resolve_state(name, jurisdiction_type, netloc=netloc)
    return f", {state}" if state else ""


def _subdomain_override(
    hint: str,
    existing_suffix: str,
    netloc: Optional[str],
    *,
    base: Optional[str] = None,
    hint_state: Optional[str] = None,
) -> Optional[str]:
    """The finished "<subdomain hint><state suffix>" string to override a
    disagreeing text-derived jurisdiction with -- or None when that
    override would produce a geographically impossible pairing, in which
    case `finalize_jurisdiction()` keeps its own text-derived answer
    instead.

    The guard exists because of a real, confirmed-live class of wrong
    repairs the 2026-08-21 subdomain cross-check (see
    `finalize_jurisdiction()`'s docstring) introduced: it accepted ANY
    subdomain label that validates against the place tables, with no check
    that the label is plausibly this page's own government. Two real
    production rows, both found by the bleed-backfill audit before the
    write step was ever run:

    - `bart.legistar.com` (a real BART board-of-directors meeting, the Bay
      Area transit agency) whose already-correct "Alameda County, CA" was
      "repaired" to **"Bart, CA"** -- "Bart" is a real Census SUBDIVISION,
      a tiny township in PENNSYLVANIA, colliding with the agency acronym.
    - `agenda.modestogov.com` (Modesto, CA's own agenda host) whose
      "Modesto, CA" was "repaired" to **"Agenda, CA"** -- "Agenda" is a
      real town in KANSAS, colliding with the literal website word.

    Both are impossible on their face: a PA township welded to ", CA", a
    KS town welded to ", CA". `_fill_missing_state()` returns an existing
    suffix completely unchanged (never overriding a state that already
    survived from the raw text), which is exactly how the mismatched pair
    gets assembled -- so the check is: whatever suffix would actually be
    attached must be one of the hint's OWN `_table_lookup()` states.

    Deliberately NOT an edit-distance or containment check between the
    current and candidate values, which would be the obvious other guard
    and would revert the cross-check entirely: both real cases it was
    built for ("Brantford..." -> "Shelburne", "Town of Caledon" -> "Peel
    Region") are correct repairs that share zero characters with the value
    they replace. A hint with no resolvable state at all is left alone too
    -- there is no pairing to contradict, and the Shelburne case is
    exactly that (genuinely ambiguous NS/ON, so it correctly declines to
    guess a province and returns a bare name).

    The `agenda` case is additionally killed one level down by
    `_GENERIC_SUBDOMAIN_WORDS`, which declines website words as labels
    before they ever become a hint; this guard is the general one, since
    no stoplist can enumerate every acronym-shaped collision like "bart".

    `base` (the pre-override text-derived value, when the caller has one)
    is an extra fallback for the state, tried only when `_fill_missing_
    state()` above comes up with nothing at all. Real bug fixed
    2026-08-30 (WO-68, BACKLOG.md's "Consolidated city-county repairs
    silently drop the state suffix" entry): a hint can legitimately
    rename a text-derived value into a real, shorter consolidated-
    government name -- "Jefferson County" -> "Louisville", "Davidson
    County" -> "Nashville" -- but the hint alone is often nationally
    ambiguous on its own (plain "Louisville"/"Nashville" both collide
    with several unrelated real places, confirmed live: neither's own
    `_table_lookup()` states include KY/TN at all, since the real
    consolidated government is stored under its OWN combined key, not
    under the bare city name), so `_fill_missing_state()` silently
    resolves to "" and the override used to drop the state entirely
    instead of adding one. Two more real, live-confirmed lookups recover
    it: `base` on its own is sometimes already unambiguous (`_table_
    lookup("Louisville / Jefferson County Metro")` -> KY alone, since the
    combined-candidate matching `_table_lookup_strength()` already does
    for a direct-text match applies here too), and when it isn't (a bare
    "Davidson County" is genuinely ambiguous NC/TN on its own), joining
    `hint` and `base` the same two ways a real Census consolidated-
    government name can be spelled -- slash ("Louisville/Jefferson
    County" -> KY) or hyphen ("Nashville-Davidson County" -> TN) --
    resolves it. Both are literal reuses of matching this module already
    trusts elsewhere, not a new heuristic; the ambiguity guard above is
    skipped for this path on purpose, since a combined-key or already-
    unambiguous-`base` match is stronger evidence than the guard exists
    to check for.

    `hint_state` (added WO-76, 2026-08-30) is the 2-letter state/province
    code the caller's OWN subdomain-derived hint already carries, when the
    subdomain label itself spelled one out (e.g. `_validated_label_extract_
    with_state()`'s tier 2/5/6/7 stripping a literal trailing "-mi"/"wa"/
    etc. off the raw label) -- distinct from `existing_suffix`, which is
    whatever state (right or wrong) survived from the page's own TEXT.
    `_fill_missing_state()` above never overrides an existing suffix by
    design, which is correct when that suffix is trustworthy but wrong
    when it isn't: real, confirmed-live case (WO-76) --
    `douglas-mi.municodemeetings.com`'s real self-branding is "City of the
    Village of Douglas, Michigan" (its own real page title, confirmed
    live), but the ALREADY-STORED value on this row was the product of an
    earlier, separate extraction bug and read "City of the Village, OK" --
    a real but totally unrelated Oklahoma place. Renaming to the correct
    "Douglas" via the hint alone still passed the ambiguity guard above
    (Douglas is ALSO real, if tiny and obscure, in Oklahoma -- `_table_
    lookup("Douglas")` includes both MI and OK), so the wrong stored "OK"
    suffix rode along unchanged, producing the equally-wrong "Douglas, OK".
    The subdomain's own label -- "douglas-mi" -- already spells out the
    correct state directly, the same "the source names its own state, so
    don't guess past it" precedent `resolve_claimed_state()` established
    for page text. When `hint_state` disagrees with whatever suffix would
    otherwise be used, it wins: it's independent, first-party evidence (the
    customer's own domain), not another parse of the same text that may
    have already produced the wrong state alongside the wrong name. Only
    consulted when it actually disagrees -- an agreeing `hint_state` is a
    no-op, so this never changes any already-correct outcome."""
    final_suffix = _fill_missing_state(hint, existing_suffix, netloc)
    if hint_state and final_suffix.lstrip(", ").strip().upper() != hint_state.upper():
        final_suffix = f", {hint_state.upper()}"
    if final_suffix:
        hit = _table_lookup(hint)
        code = final_suffix.lstrip(", ").strip().upper()
        if hit and code not in {s.upper() for s in hit[1]}:
            return None
        return f"{hint}{_county_type_suffix(hint, code)}{final_suffix}"
    if base:
        base_hit = _table_lookup(base)
        if base_hit and len(set(base_hit[1])) == 1:
            state = base_hit[1][0]
            return f"{hint}{_county_type_suffix(hint, state)}, {state}"
        for combined in (f"{hint}/{base}", f"{hint}-{base}"):
            combo_hit = _table_lookup(combined)
            if combo_hit and len(set(combo_hit[1])) == 1:
                state = combo_hit[1][0]
                return f"{hint}{_county_type_suffix(hint, state)}, {state}"
    return f"{hint}{final_suffix}"


def _claimed_state_from_bleed_tail(repaired_name: str, tail: str) -> Optional[str]:
    """A state/province code, only when the text `_trim_repair()` is about
    to DISCARD as bleed for `repaired_name` itself spells out a real
    state/province name for that exact name -- the same underlying shape
    `resolve_claimed_state()` (WO-70, 2026-08-30) was built for, just
    glued directly onto the name with no comma rather than following one:
    "City of Breckenridge Texas Meetings" rather than "City of Medina,
    Minnesota".

    Real, confirmed-live gap this closes (WO-78, 2026-08-30): 4 real pages
    -- Breckenridge TX (`1435`), Eustis FL (`1441`), Hendersonville NC
    (`1442`), Loganville GA (`1447`) -- all nationally-ambiguous names
    (Breckenridge is also real in CO; Eustis in ME; Hendersonville in TN;
    Loganville has more than one real instance), each with a trailing
    "<State> Meetings"/"<State> <Province-shaped words> Meetings" tail.
    `_looks_like_bleed()` correctly recognizes that tail as bleed (its
    last word, "meetings", is a known junk tail word -- see
    `_KNOWN_JUNK_TAIL_WORDS`) and `_trim_repair()` correctly finds the
    real name underneath, but the ambiguous name alone can't resolve a
    state via `_fill_missing_state()`'s plain `resolve_state()` call, so
    the state was silently dropped even though it was sitting right there
    in the discarded text -- worse than the untouched raw value, which at
    least had the state SOMEWHERE, unparsed.

    Tries the tail's leading two words before its leading one word (a
    two-word state/province name -- "North Carolina", "South Dakota",
    "British Columbia" -- must be tried first, or a one-word match on just
    "North"/"South"/"British" would shadow it and this would never see
    the real two-word name at all). Delegates the actual "is this text a
    real state name, and is it genuinely one of `repaired_name`'s own
    real states" check to `resolve_claimed_state()` itself rather than
    reimplementing it -- this function's only job is picking which
    leading slice of the tail to offer it. Returns None when neither
    slice is a real state/province name for `repaired_name`'s type, which
    is the ordinary case: real bleed prose ("Attachments", "Live Stream",
    "Committee of the Whole Agenda Thursday") is never a real state name,
    so this can't misfire on it.
    """
    words = [w.strip(".,;:") for w in tail.split()]
    for length in (2, 1):
        if length > len(words):
            continue
        candidate = " ".join(words[:length])
        resolved = resolve_claimed_state(repaired_name, candidate)
        if resolved:
            return resolved
    return None


def finalize_jurisdiction(
    raw_jurisdiction: Optional[str], *, netloc: Optional[str] = None
) -> JurisdictionResult:
    """The one ingest-time pass that turns whatever an adapter extracted
    into a scored, optionally-repaired, optionally-split final value.
    Called once, from `archive/db/crud.py`'s `_find_or_create_page()` --
    see this module's own section header above for why this lives at
    ingest time rather than being threaded through every adapter.

    Never loses information without evidence: a name that doesn't
    validate and shows no bleed signal is returned completely unchanged
    (confidence "unverified"), not discarded or guessed at -- see
    `_looks_like_bleed()` and `_split_entity_prefix()` for the two
    mechanisms that DO change the value, and BACKLOG.md's "Census-table
    baseline validation" entry for the real data (649 archived rows) this
    design was built and tuned against.

    Cross-checked against a validated subdomain-derived candidate since
    2026-08-21 (BACKLOG.md's jurisdiction-bleed entries), the same idea
    `extract_jurisdiction_chain()` already applies to its own per-tier
    candidates (see that function's own docstring), just moved one level
    down so a caller that invokes THIS function directly on already-
    stored text -- `archive/db/crud.py`'s backfill/reprocessing passes,
    not just a fresh chain-based resolve -- gets the same protection.
    Two distinct real, confirmed-live failure shapes this closes:

    1. `_trim_repair()` can confidently trim a bled raw value down to a
       real, but WRONG, place when the discarded tail happens to mention
       a different real city -- confirmed live on Shelburne, ON's stored
       "Brantford regarding Professional Activity" (eScribe subdomain
       `pub-shelburne...`), which trims to "Brantford" (a real Ontario
       town, just not THIS meeting's) before this fix.
    2. A raw value can validate directly (no repair needed at all) as a
       real place that's genuinely mentioned on the page, but isn't the
       meeting's OWN jurisdiction -- confirmed live on Peel Region, ON's
       "Town of Caledon" (eScribe subdomain `pub-peelregion...`): Caledon
       is a real constituent lower-tier town inside the Peel Region
       agenda, validates outright, and used to be returned as-is before
       ever reaching the subdomain's own correct "Peel Region" identity.

    In both cases, when a validated subdomain-derived candidate exists
    (see `_validated_subdomain_extract_from_netloc()`) and disagrees with
    the text-derived name (`_base_name_key()`, the same identity
    comparison the chain's own cross-check uses), the subdomain's own
    validated identity wins outright -- it's an independent, per-customer
    signal (the domain the customer itself registered), not just another
    guess at parsing the same page text that produced the wrong answer in
    the first place. When they agree (the overwhelmingly common case) or
    no subdomain hint validates at all (most non-eScribe/Granicus pages,
    or an eScribe regional-tier customer not yet in the place tables --
    see BACKLOG.md's StatsCan completeness gap), this is a pure no-op.

    That override is itself guarded, since 2026-08-21 (same day, later
    pass): `_subdomain_override()` refuses a hint whose state suffix
    couldn't possibly belong to it, which is what a subdomain that's
    really an acronym ("bart") or a website word ("agenda") produces --
    see that function for the two real production rows it was built from.
    A rejected override falls through to this function's own text-derived
    answer, exactly as it behaved before the cross-check existed.
    """
    known = lookup_by_domain(netloc) if netloc else None

    if known and known.strength == "authoritative":
        return JurisdictionResult(f"{known.name}, {known.state}", None, "authoritative")

    if not raw_jurisdiction:
        if known:
            return JurisdictionResult(f"{known.name}, {known.state}", None, "fallback")
        return JurisdictionResult(raw_jurisdiction, None, "blank")

    subdomain_hit = _validated_subdomain_hint_with_state(netloc) if netloc else None
    subdomain_hint, subdomain_hint_state = (
        subdomain_hit if subdomain_hit else (None, None)
    )
    subdomain_hint_key = _base_name_key(subdomain_hint) if subdomain_hint else None

    # Preprocessing: strip noise shapes _trim_repair() below can't reach
    # (a leading date only trims from the right; a glued file extension
    # never lands on a whitespace cut point) -- see both regexes' own
    # comments above. Guard the date-strip specifically: only take it if
    # something real is left, so a bare date-only string doesn't collapse
    # to empty.
    date_stripped = _LEADING_DATE_RE.sub("", raw_jurisdiction).strip()
    if date_stripped:
        raw_jurisdiction = date_stripped
    raw_jurisdiction = _GLUED_EXTENSION_RE.sub(r" .\1", raw_jurisdiction)

    # Already has a state suffix from a prior enrichment step -- validate
    # the name portion only, state stays as already resolved.
    state_match = _STATE_SUFFIX_RE.search(raw_jurisdiction)
    base = (
        _STATE_SUFFIX_RE.sub("", raw_jurisdiction).strip().rstrip(".,;:")
        if state_match
        else raw_jurisdiction
    )
    suffix = f", {state_match.group(1).upper()}" if state_match else ""

    if _table_lookup(base):
        if subdomain_hint_key and _base_name_key(base) != subdomain_hint_key:
            override = _subdomain_override(
                subdomain_hint,
                suffix,
                netloc,
                base=base,
                hint_state=subdomain_hint_state,
            )
            if override:
                return JurisdictionResult(override, None, "repaired")
        # Vendor-branding "X City" that isn't the place's real name --
        # "Arcata City"/"Redding City"/"Healdsburg City"/"Ringgold City"
        # (IQM2 tenants' own page titles, confirmed live 2026-08-23; the
        # real places are just "Arcata"/"Redding"/...). These "validate"
        # only via `_normalize_candidates()`'s trailing-type-word strip,
        # so the stored string keeps the bogus " City" and splits one
        # real government across two /j/ hubs ("Arcata, CA" vs "Arcata
        # City, CA" -- the duplicate-hub cluster found via Google's crawl
        # of /state/california). `is_literal_known_place()` separates the
        # two cases exactly: real "X City" names (Redwood City, Foster
        # City, Oklahoma City) are literal table keys and stay whole;
        # branding "X City" is not literal while its base is.
        stripped = _strip_branding_type_suffix(base)
        if stripped:
            return JurisdictionResult(
                f"{stripped}{_fill_missing_state(stripped, suffix, netloc)}",
                None,
                "repaired",
            )
        # Real bug found 2026-08-21 via a /coverage sort-adjacency scan
        # (BACKLOG.md's "16 real pairs of a jurisdiction appearing twice"
        # entry): unlike the `_trim_repair()`/`_split_entity_prefix()`
        # branches below, this fast path used to return `raw_jurisdiction`
        # completely unchanged whenever the bare name ALREADY validates
        # against the place/county table -- including when that
        # validation is only nationally-ambiguous (e.g. "Albany" matches
        # 14 different states' worth of real places), so no state was
        # ever attempted here even though `_fill_missing_state()` was
        # right there and already used by every other repair path. That
        # silently produced two different stored jurisdiction strings for
        # the same real government -- one adapter/extraction happened to
        # find a state suffix in the raw text ("Dublin, CA"), another
        # extraction of the exact same customer's site
        # (`dublin.granicus.com`, confirmed live) didn't, and the second
        # one got permanently stuck bare ("Dublin") since this branch
        # never gave `resolve_state()` a chance to try. `_fill_missing_state()`
        # is a safe no-op call here: it only ever adds a suffix when
        # `resolve_state()` confidently resolves one (an unambiguous
        # name-only match, or -- the common case for these bare rows -- a
        # confirmed `netloc` registry entry), and returns "" (no change)
        # for a genuinely ambiguous name with no netloc evidence, so an
        # already-correct bare "unverified"-shaped case can't regress.
        return JurisdictionResult(
            f"{base}{_fill_missing_state(base, suffix, netloc)}"
            if not suffix
            else raw_jurisdiction,
            None,
            "validated",
        )

    # Glued CamelCase ("MaderaCounty" -- maderacountyca.iqm2.com's own
    # page title, confirmed live 2026-08-23 alongside 5 more IQM2 tenants
    # with the same title-as-branding shape) -- worth exactly one cheap
    # candidate: split at every lower->Upper boundary and accept only if
    # the spaced form is a real table key. A real name that already
    # validates whole (McAllen, DeKalb, LaSalle) took the fast path above
    # and never reaches here, so interior-capital real names can't be
    # mangled by this.
    decameled = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", base)
    if decameled != base and _table_lookup(decameled):
        stripped = _strip_branding_type_suffix(decameled)
        repaired_name = stripped or decameled
        return JurisdictionResult(
            f"{repaired_name}{_fill_missing_state(repaired_name, suffix, netloc)}",
            None,
            "repaired",
        )

    trimmed = _trim_repair(base)
    if trimmed:
        repaired_name, _table = trimmed
        if subdomain_hint_key and _base_name_key(repaired_name) != subdomain_hint_key:
            override = _subdomain_override(
                subdomain_hint,
                suffix,
                netloc,
                base=base,
                hint_state=subdomain_hint_state,
            )
            if override:
                return JurisdictionResult(override, None, "repaired")
            # Override rejected as an impossible pairing (see
            # `_subdomain_override()`) -- fall through to the plain trim
            # result, the pre-cross-check behavior.
        final_suffix = _fill_missing_state(repaired_name, suffix, netloc)
        if not final_suffix:
            # `_fill_missing_state()` only ever returns "" here when there
            # was no state suffix already in the raw text AND
            # `resolve_state()`'s plain name lookup declined (ambiguous or
            # unknown) -- exactly the case where the state `_trim_repair()`
            # just discarded as bleed might still be recoverable, if that
            # discarded tail itself spelled the state out. See
            # `_claimed_state_from_bleed_tail()`'s own docstring for the 4
            # real, confirmed pages (WO-78, 2026-08-30) this recovers.
            repaired_tokens = repaired_name.split()
            tail = " ".join(base.split()[len(repaired_tokens) :])
            claimed_state = _claimed_state_from_bleed_tail(repaired_name, tail)
            if claimed_state:
                final_suffix = f", {claimed_state}"
        return JurisdictionResult(
            f"{repaired_name}{final_suffix}",
            None,
            "repaired",
        )

    body = _split_entity_prefix(base)
    if body:
        jurisdiction_half = base[len(body) :].strip()
        jurisdiction_half = re.sub(
            r"^\s*of\s+(the\s+)?", "", jurisdiction_half, flags=re.IGNORECASE
        )
        final_suffix = _fill_missing_state(jurisdiction_half, suffix, netloc)
        return JurisdictionResult(
            f"{jurisdiction_half}{final_suffix}", body, "repaired"
        )

    # Fully-glued single token, possibly with a glued state code
    # ("RochestercityMN" -- rochestercitymn.iqm2.com's own page title,
    # confirmed live; BACKLOG.md's "RochestercityMN" entry predicted this
    # fix would become buildable the moment a second glued-title IQM2
    # customer appeared, and 2026-08-23's data-quality pass found five
    # more). Reuses the same Census-validated label extractor every
    # subdomain path already trusts -- it declines rather than guessing
    # (acronyms like "Cmsd" come back None and fall through unchanged) --
    # then strips vendor branding off the result the same way the fast
    # path above does ("Rochester City" -> "Rochester").
    if " " not in base and len(base) >= 6:
        hit = _validated_label_extract_with_state(base.lower())
        if hit:
            glued_name, glued_state = hit
            glued_name = _strip_branding_type_suffix(glued_name) or glued_name
            glued_suffix = suffix or (f", {glued_state}" if glued_state else "")
            return JurisdictionResult(
                f"{glued_name}"
                f"{glued_suffix or _fill_missing_state(glued_name, '', netloc)}",
                None,
                "repaired",
            )

    if known:
        return JurisdictionResult(f"{known.name}, {known.state}", None, "fallback")

    return JurisdictionResult(raw_jurisdiction, None, "unverified")


# --- Shared extraction chain, for adapters with no bespoke extraction of
# their own (2026-08-15) ---
#
# Built from the extraction tournament (JURISDICTION_METADATA_PLAN.md,
# workstream 2): every portable jurisdiction-extraction convention run
# against all 649 archived pages' raw HTML, scored against the Census
# tables. Two conventions each beat their shipped counterpart outright
# and are promoted here into a chain any adapter can call once its own
# primary extraction comes up empty -- Swagit and generic_fallback are
# the first two callers, since the audit found them the highest-volume
# adapters that never called into this module at all (~22 blank Swagit
# jurisdictions, generic_fallback's title-tag regexes with no further
# fallback). clerkbase_slug (2 real hits outside its home platform --
# doesn't generalize) and fallback_titletag (zero *unique* coverage once
# the tiers below run first, and its non-validating misses are real
# junk: bare dates, "Auroratv") were both tournament losers and are
# deliberately excluded.
#
# The capitalization-bounded walk below mirrors
# app.platforms.primegov.PrimeGovAssetFinder._extract_jurisdiction's own
# regex rather than importing it: that adapter's own resolve() and
# registry-consultation logic are deliberately left untouched this round
# (see BACKLOG.md's "Future refactor, deliberately deferred" entry), and
# importing a live method from it here would create exactly the coupling
# that entry is about avoiding. Similarly, the validated-subdomain
# extractor below re-checks the Census tables directly rather than
# calling GranicusAssetFinder._humanize_subdomain() -- both platform
# modules already import *this* module, so importing back from either
# would be a circular import, not just a style choice.

_CHAIN_BOILERPLATE_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL
)
_CHAIN_TAG_JURISDICTION_RE = re.compile(
    r"\b(city|county|town) of\s+([^<>]{1,80}?)(?=<|[,.])", re.IGNORECASE
)

_STOPRULE_TRIGGER_RE = re.compile(r"\b(City|County|Town) of\s+")
# Abbreviations pages actually write ("Ft. Worth", "Mt. Vernon", "N. Las
# Vegas") -- not just the Census tables' own canonical two (St./Ste.),
# since this stop rule is about how *websites* punctuate a name, not how
# the Census does (user's call, 2026-08-15, made after seeing "Ft."/"Mt."
# trip the first draft's period-stop).
_STOPRULE_ABBREV_OK = {"st", "ste", "ft", "mt", "pt", "n", "s", "e", "w"}

# Deliberately duplicated from app.platforms.granicus.US_STATE_ABBREVIATIONS
# rather than imported -- see the module comment above on why a
# platforms -> utils reverse import isn't an option here.
_STATE_ABBREVIATIONS_LOWER = {
    "al",
    "ak",
    "az",
    "ar",
    "ca",
    "co",
    "ct",
    "de",
    "fl",
    "ga",
    "hi",
    "id",
    "il",
    "in",
    "ia",
    "ks",
    "ky",
    "la",
    "me",
    "md",
    "ma",
    "mi",
    "mn",
    "ms",
    "mo",
    "mt",
    "ne",
    "nv",
    "nh",
    "nj",
    "nm",
    "ny",
    "nc",
    "nd",
    "oh",
    "ok",
    "or",
    "pa",
    "ri",
    "sc",
    "sd",
    "tn",
    "tx",
    "ut",
    "vt",
    "va",
    "wa",
    "wv",
    "wi",
    "wy",
    "dc",
}

# Canadian province/territory codes, kept as their own set rather than
# folded into `_STATE_ABBREVIATIONS_LOWER` above (no collisions between the
# two -- verified) so it's clear at a glance this one exists specifically
# for `_validated_label_extract()`'s eScribe use, added 2026-08-18 alongside
# that function gaining a Canadian-serving caller. Real gap this closes:
# without it, "beaumontab" (Beaumont, AB) and "mackenziebc" (Mackenzie, BC)
# both fail to validate purely because the trailing province code is never
# stripped, even though the underlying place name is already a real,
# already-validated single-word table entry.
_PROVINCE_ABBREVIATIONS_LOWER = {
    "ab",
    "bc",
    "mb",
    "nb",
    "nl",
    "ns",
    "on",
    "pe",
    "qc",
    "sk",
    "nt",
    "nu",
    "yt",
}

# Full state/province names -> the SAME 2-letter code stored in
# `_STATE_ABBREVIATIONS_LOWER`/`_PROVINCE_ABBREVIATIONS_LOWER` above --
# needed by `resolve_claimed_state()` below because a free-text account/
# channel name that already names its own state spells it out in full
# ("Village of Angel Fire, New Mexico", "City of Medina, Minnesota"),
# never abbreviated -- confirmed real, see that function's own docstring.
# Standard USPS/Canada Post full names, public factual data, not derived
# from any adapter-specific sample.
_STATE_NAME_TO_ABBR_LOWER = {
    "alabama": "al",
    "alaska": "ak",
    "arizona": "az",
    "arkansas": "ar",
    "california": "ca",
    "colorado": "co",
    "connecticut": "ct",
    "delaware": "de",
    "florida": "fl",
    "georgia": "ga",
    "hawaii": "hi",
    "idaho": "id",
    "illinois": "il",
    "indiana": "in",
    "iowa": "ia",
    "kansas": "ks",
    "kentucky": "ky",
    "louisiana": "la",
    "maine": "me",
    "maryland": "md",
    "massachusetts": "ma",
    "michigan": "mi",
    "minnesota": "mn",
    "mississippi": "ms",
    "missouri": "mo",
    "montana": "mt",
    "nebraska": "ne",
    "nevada": "nv",
    "new hampshire": "nh",
    "new jersey": "nj",
    "new mexico": "nm",
    "new york": "ny",
    "north carolina": "nc",
    "north dakota": "nd",
    "ohio": "oh",
    "oklahoma": "ok",
    "oregon": "or",
    "pennsylvania": "pa",
    "rhode island": "ri",
    "south carolina": "sc",
    "south dakota": "sd",
    "tennessee": "tn",
    "texas": "tx",
    "utah": "ut",
    "vermont": "vt",
    "virginia": "va",
    "washington": "wa",
    "west virginia": "wv",
    "wisconsin": "wi",
    "wyoming": "wy",
    "district of columbia": "dc",
}
_PROVINCE_NAME_TO_ABBR_LOWER = {
    "alberta": "ab",
    "british columbia": "bc",
    "manitoba": "mb",
    "new brunswick": "nb",
    "newfoundland and labrador": "nl",
    "nova scotia": "ns",
    "ontario": "on",
    "prince edward island": "pe",
    "quebec": "qc",
    "québec": "qc",
    "saskatchewan": "sk",
    "northwest territories": "nt",
    "nunavut": "nu",
    "yukon": "yt",
}


def resolve_claimed_state(name: str, claimed_state: str) -> Optional[str]:
    """A state/province code, only when `claimed_state` (as typed -- a
    two-letter USPS/Canada Post code OR a full spelled-out name, e.g.
    "Minnesota" or "MN") is genuinely a MEMBER of `name`'s real state
    list -- checked against the same `_PLACE_STATES`/`_COUNTY_STATES`
    tables `lookup_city_state()`/`lookup_county_state()` already use.

    Built for BACKLOG.md's "[NEEDS-AUDIT] A name that's already
    'X, State'-shaped..." entry (WO-70, 2026-08-30, confirmed live via
    Vimeo account "City of Medina, Minnesota"): a source text that
    already names its own state directly shouldn't be declined just
    because the bare name alone ("Medina") is nationally ambiguous (real
    in MN/ND/OH/TN/WA/NY per `places.csv`) -- `lookup_city_state
    ("Medina")` correctly returns None for THAT query (see its own
    docstring: an ambiguous bare name is a real "don't guess" case), but
    the source text here isn't actually ambiguous, it states the answer.
    This function answers a different, narrower question: not "is this
    name unambiguous on its own" but "is this SPECIFIC claimed state one
    of the name's real states" -- strictly additive to the existing
    lookups, since it only ever accepts a (name, state) pair that's
    already a real row in the Census/StatsCan data; it never invents or
    guesses a state the data doesn't list.

    Type (county vs. place) is read from `name` itself, the same way
    `enrich_jurisdiction_text()` already does (`_TYPE_HINT_RE`) -- only
    the matching table is ever checked, deliberately NOT both. Real
    false-accept this guards against, confirmed via `counties.csv`:
    "Medina County" is real in OH *and TX*, so checking the county table
    unconditionally would wrongly validate "City of Medina, Texas" off
    the back of a real COUNTY that happens to share the name -- no real
    *city* named Medina exists in Texas (confirmed: `places.csv` has no
    TX row for "Medina" at all). Restricting to the type `name` itself
    claims avoids that cross-type false accept, the identical reasoning
    `resolve_state()`'s own `jurisdiction_type` parameter documents.

    Returns None when `name` isn't real in any state/province of its own
    claimed type, when `claimed_state` isn't a real state/province name
    or code at all, or when `name` IS real somewhere but never in the
    claimed state (e.g. `resolve_claimed_state("Medina", "Texas")` --
    confirmed None, since Texas isn't one of Medina city's 6 real
    states).
    """
    claimed = claimed_state.strip().lower().rstrip(".")
    if (
        claimed in _STATE_ABBREVIATIONS_LOWER
        or claimed in _PROVINCE_ABBREVIATIONS_LOWER
    ):
        abbr = claimed.upper()
    else:
        abbr_lower = _STATE_NAME_TO_ABBR_LOWER.get(
            claimed
        ) or _PROVINCE_NAME_TO_ABBR_LOWER.get(claimed)
        if not abbr_lower:
            return None
        abbr = abbr_lower.upper()
    jurisdiction_type = "county" if _TYPE_HINT_RE.search(name) else "city"
    table = _COUNTY_STATES if jurisdiction_type == "county" else _PLACE_STATES
    for candidate in _normalize_candidates(name):
        states = table.get(candidate)
        if states and abbr in states:
            return abbr
    return None


def _stoprule_extract(page_text: str) -> Optional[str]:
    """ "City/County/Town of X" walk over rendered page text that stops at
    the first lowercase-initial word, a period not in
    `_STOPRULE_ABBREV_OK`, a comma/semicolon, or 5 words -- whichever
    comes first. Beat the shipped Granicus body regex outright in the
    tournament (361 vs. 318 table-valid of 649) by fixing exactly the
    bleed the shipped regex's open-ended character class allows (e.g.
    "City of Hercules. XIV. PUBLIC COMMUNICATIONS XV." -- confirmed live
    2026-08-15 against hercules.granicus.com/player/clip/1306, see
    BACKLOG.md)."""
    m = _STOPRULE_TRIGGER_RE.search(page_text)
    if not m:
        return None
    kept: List[str] = []
    for word in page_text[m.end() : m.end() + 120].split():
        core = word.strip(",;:")
        if not core or not core[0].isupper():
            break
        if (
            core.endswith(".")
            and core[:-1].lower() not in _STOPRULE_ABBREV_OK
            and len(core.rstrip(".")) > 1
        ):
            kept.append(core.rstrip("."))
            break
        kept.append(core)
        if word != core:
            # A comma/semicolon ends the name ("City of Boston,
            # Massachusetts") -- keep the token but stop the walk, the
            # same boundary the shipped Granicus regex's character class
            # already uses.
            break
        if len(kept) >= 5:
            break
    return f"{m.group(1)} of {' '.join(kept)}" if kept else None


def _capitalization_walk_extract(html: str) -> Optional[str]:
    """ "City/County/Town of X" walk over tag-bounded raw HTML (stops at
    the first non-capitalized word or 4 words) -- the tournament's second
    winner (326 table-valid of 649, primegov_walk). See the module
    comment above for why this is a reimplementation, not a shared
    import."""
    text = _CHAIN_BOILERPLATE_RE.sub("", html)
    match = _CHAIN_TAG_JURISDICTION_RE.search(text)
    if not match:
        return None
    kept: List[str] = []
    for word in match.group(2).split():
        core = word.strip(".,;:")
        if not core or not core[0].isupper():
            break
        # Normalize all-caps header text ("OKLAHOMA CITY") to title case
        # without touching text that's already properly cased.
        kept.append(core.title() if core.isupper() else core)
        if len(kept) >= 4:
            break
    if not kept:
        return None
    return f"{match.group(1).capitalize()} of {' '.join(kept)}"


# Website words that are not place names, even though several of them
# DO validate against the Census/StatsCan tables as real (tiny) places --
# confirmed live 2026-08-21: "agenda" is a real Kansas town, "council" a
# real Idaho city, "media" a real Illinois/Pennsylvania borough, "portal"
# a real Georgia/North Dakota town. A subdomain label that is exactly one
# of these is a vendor/site-structure word ("agenda.modestogov.com" is
# Modesto's own agenda host, not the town of Agenda, KS), so this
# function declines rather than handing back a confidently-wrong
# validated candidate -- the same "decline instead of guessing" policy
# the rest of this function already runs on, and the same closed,
# curated-stoplist idiom already used by `_KNOWN_JUNK_TAIL_WORDS` and the
# leading connector-word strip below. Deliberately whole-label only: a
# label that merely CONTAINS one of these words ("councilbluffsia" ->
# "Council Bluffs, IA", a real city) is untouched. The cost of a false
# positive here is a decline, not a wrong answer -- a real city named
# Council, ID on `council.granicus.com` would simply fall back to the
# page's own text-derived jurisdiction instead.
_GENERIC_SUBDOMAIN_WORDS = frozenset(
    {
        "agenda",
        "agendas",
        "archive",
        "clerk",
        "council",
        "live",
        "media",
        "meeting",
        "meetings",
        "portal",
        "public",
        "stream",
        "video",
        "videos",
        "webcast",
        "webcasts",
    }
)

# Trailing connector words stripped by `_validated_label_extract()`'s tier
# 4, mirroring the LEADING strip that has always been there. Kept as its
# own, narrower list than the leading one on purpose: "of"/"pub" are never
# meaningful as a trailing word, and unlike the leading strip this tier
# always re-attaches the type word to the candidate it looks up (see that
# function's own comment for why dropping it outright would be actively
# wrong for a real county tenant).
_TRAILING_TYPE_WORDS = ("city", "county", "town")


def _validated_label_extract(label: str) -> Optional[str]:
    """Bare (no state suffix) name derived from a subdomain LABEL -- thin
    wrapper around `_validated_label_extract_with_state()` that drops the
    stripped state/province code, for the many callers that only want the
    name. See that function for the actual logic."""
    hit = _validated_label_extract_with_state(label)
    return hit[0] if hit else None


# Tier 6 (see `_validated_label_extract_with_state()`'s docstring): a
# "twp" (township) abbreviation GLUED directly between a name and a
# trailing 2-letter state code, with no separator on either side -- e.g.
# CivicClerk's real `macombtwpmi` (Macomb Township, MI) and
# `southorangetwpnj` (South Orange Township, NJ) subdomains, confirmed
# live 2026-08-30 (BACKLOG.md's "CivicClerk residuals after the
# 2026-08-29 sweep" entry). Structurally different from every tier
# above: the type-word marker sits BETWEEN the name and state rather
# than at either end, so neither tier 2's leading/trailing strip nor
# tier 5's raw trailing-state strip can ever find it on their own --
# confirmed live: wordninja mangles both the raw label AND the tier-5
# state-stripped remainder into garbage (`wordninja.split("macombtwpmi")
# == ['ma','com','btw','pm','i']`; `wordninja.split("macombtwp") ==
# ['m','acomb','t','wp']` -- "macomb" alone doesn't even survive
# wordninja's own dictionary segmentation). Runs on the RAW label,
# before wordninja, same as tier 5.
_TWP_GLUED_RE = re.compile(r"^(?P<name>[a-z]{3,})twp(?P<state>[a-z]{2})$")


def _twp_glued_extract(label: str) -> Optional[Tuple[str, str]]:
    """(name, state) for a `_TWP_GLUED_RE` match, or None -- see that
    regex's own comment for the shape this handles.

    Matched against `_SUBDIVISION_STATES` by PREFIX rather than an exact
    key, filtered to the extracted state first -- the one deliberate
    looseness in this whole function, and needed because the real
    Census/StatsCan row for South Orange is "South Orange Village
    township, NJ" (confirmed live via `grep` on `county_subdivisions.
    csv`): the subdomain's own informal glued name ("southorange") drops
    the "Village" the official name carries, so an EXACT candidate
    ("South Orange Township") never validates. Filtering to the state
    extracted from the label itself first -- the same self-declared
    signal tier 5 already trusts without cross-checking -- keeps this
    safe: within one state, only accepted when the prefix match is
    UNIQUE, so a state with more than one real subdivision sharing that
    prefix declines rather than guessing which one. Macomb's own case
    doesn't need the looseness (the real key IS exactly "macomb"), but
    the prefix check subsumes an exact match for free."""
    m = _TWP_GLUED_RE.match(label.lower())
    if not m:
        return None
    state = m.group("state").upper()
    if (
        state.lower() not in _STATE_ABBREVIATIONS_LOWER
        and state.lower() not in _PROVINCE_ABBREVIATIONS_LOWER
    ):
        return None
    glued_name = m.group("name")
    matches = {
        key
        for key, states in _SUBDIVISION_STATES.items()
        if state in states and key.replace(" ", "").startswith(glued_name)
    }
    if len(matches) != 1:
        return None
    display = " ".join(w.capitalize() for w in next(iter(matches)).split())
    return f"{display} Township", state


def _validated_label_extract_with_state(
    label: str, *, _allow_state_strip: bool = True
) -> Optional[Tuple[str, Optional[str]]]:
    """Bare (no state suffix) name derived from a subdomain LABEL (already
    stripped of any platform-specific prefix, e.g. eScribe's "pub-"),
    validated against the Census/StatsCan tables before ever being offered
    as a candidate -- declines instead of guessing when nothing validates
    (416 table-valid / 0 garbage of 649 in the original tournament, vs. 408
    valid / 229 garbage for a bare wordninja-always approach).

    Returns `(name, state_code)` where `state_code` is the 2-letter
    US-state/Canadian-province code this function itself had to strip off
    the label to make it validate (tiers 2 and 5 below), or None when no
    code was stripped -- a caller that needs the state (e.g.
    `app/platforms/suiteone.py`'s `_extract_jurisdiction()`) can't
    re-derive it safely on its own, since "is the label's trailing 2
    letters a state code" is only trustworthy when the name *without* them
    is what actually validated: "tacoma" ends in "ma" but is emphatically
    not in Massachusetts. Most callers want the name alone and go through
    `_validated_label_extract()`/`validated_label_extract()` instead.

    A label that is exactly a generic website word (`_GENERIC_SUBDOMAIN_
    WORDS`) is declined up front, before any tier runs -- see that
    constant's own comment for the real confirmed cases.

    Seven tiers, tried in order, first hit wins (the first five were the
    original design; tiers 6 and 7 were added 2026-08-30, WO-68, for two
    CivicClerk subdomain shapes wordninja can't segment at all -- see
    each tier's own comment below). Listed here in DEFINITION order
    (1-2-3-4-5-6-7), which is no longer strictly the RUNTIME order: as of
    WO-76 (2026-08-30), tier 7 actually runs before tiers 5 and 6 -- see
    tier 7's own comment in the code for why (tier 5's blind recursive
    strip can accidentally "succeed" on the exact shape tier 7 exists to
    handle, via the "co" state/county-abbreviation collision, before tier
    7 ever gets a turn if it runs later):

    1. The raw label unsplit (and a digit-stripped variant) -- fixes
       Galesburg: wordninja's own split ("Gales Burg") never validates,
       while the raw label does.
    2. A wordninja split, with a trailing US-state or Canadian-province
       code stripped and a leading "city"/"county"/"town"/"of" connector
       word stripped, tried SPACED first (join with spaces -- catches
       genuinely multi-word names like "Grand Valley", "Boulder County")
       then GLUED as a fallback (join with no spaces -- catches names
       wordninja over-splits into dictionary fragments that only validate
       once reassembled, e.g. "townofbonnyville" -> town/of/bonny/ville ->
       strip "town"/"of" -> spaced "Bonny Ville" doesn't validate, glued
       "Bonnyville" does). Spaced MUST be tried before glued, not the
       reverse: confirmed live against every real Granicus subdomain in
       production, glued-first wrongly turns "cityofnorthport" into
       "Northport" (a real but WRONG place -- a coincidental match) instead
       of the correct spaced "North Port"; same failure mode on
       "oakridgetn" -> wrongly "Oakridge" instead of correct "Oak Ridge".
    3. Neither tier 2 candidate is accepted below 3 total letters -- a real
       gap found adding the province-code list above: "citynmb" wordninja-
       splits to ['city','n','mb'], and after stripping the leading "city"
       and trailing province code "mb", the sole leftover word "n" was
       found to validate against `places.csv` (a single-letter row that's
       almost certainly a data artifact, not a real place) -- confirmed
       live, 2026-08-18. No real municipality is meaningfully named 1-2
       letters, so this floor is a safe, general guard rather than a
       one-off patch for that specific label.
    4. A TRAILING connector word ("city"/"county"/"town") stripped, then
       the glued remainder looked up with that word RE-ATTACHED -- the
       mirror image of tier 2's leading strip, added 2026-08-21 for
       `pitkincounty` (a real open.media tenant, Pitkin County, CO --
       PR #265's own writeup flagged this as the one real subdomain among
       all 10 known tenants this function couldn't validate). wordninja
       splits it ['pit','kin','county'], so tier 2's spaced ("Pit Kin
       County") and glued ("Pitkincounty") candidates both fail. The
       type word is deliberately re-attached rather than dropped:
       "Pitkin" ALSO validates on its own (a real, tiny, unrelated town
       inside that same county), so a bare trailing strip would return a
       confidently-wrong different government -- exactly the collision
       shape `_GENERIC_SUBDOMAIN_WORDS` above exists for.
    5. Last resort, after every tier above declines: a trailing 2-letter
       state/province code stripped off the RAW label, before wordninja
       ever sees it, and the whole function retried once on the
       remainder. Real gap this closes (confirmed live 2026-08-21 on two
       real SuiteOne Media tenants shipped in PR #263): wordninja's own
       cost minimization absorbs the trailing state letters into a longer
       non-word chunk -- "stmarysga" -> ['st','mary','sga'], "camaswa" ->
       ['ca','maswa'] -- so tier 2's trailing-code strip, which only ever
       inspects `words[-1]` AFTER the split, can never fire on them.
       Stripping first gives "stmarys" -> "St Marys" and "camas" ->
       "Camas", both real and correct. Only ever a last resort, and still
       accepted only if the remainder validates, so it can't override an
       answer any earlier tier already found: a real name that happens to
       end in state-code-shaped letters ("oakland" -> "nd", "tacoma" ->
       "ma") validates whole at tier 1 and never reaches here. Retried
       exactly once (`_allow_state_strip`), never recursively.
    6. A "twp" (township) abbreviation glued directly between the name
       and a trailing state code, with no separator either side -- see
       `_twp_glued_extract()`'s own comment for the shape (e.g.
       CivicClerk's real "macombtwpmi") and why it needs a prefix match
       against the subdivision table rather than an exact one. Only
       tried at the outermost call, same gating as tier 5.
    7. A trailing state code AND a trailing "co" (county) abbreviation,
       both stripped off the RAW label, with the bare remainder checked
       directly against the COUNTY table (cross-validated against the
       specific extracted state, not a bare national-uniqueness check) --
       for a county name wordninja itself can't segment (e.g. CivicClerk's
       real "lenaweecomi", Lenawee County MI: "lenawee" isn't an English
       dictionary word) or whose bare name is ALSO a real place elsewhere
       (e.g. "chestercopa", Chester County PA: "Chester" is also a real
       place in several states, which is exactly why this tier checks
       `_COUNTY_STATES` directly rather than the type-agnostic
       `_table_lookup()` -- see the code's own comment, WO-76, for the
       real case and the precedence fix that goes with it). Also only
       tried at the outermost call, and -- as of WO-76 -- BEFORE tiers 5
       and 6, not after; see the code comment for why the order matters.

    State/province is otherwise deliberately left to the caller's own
    `enrich_jurisdiction_text()` pass (URL callers) or its own suffix
    handling (label callers, e.g. `EscribeAssetFinder._jurisdiction_from_
    subdomain()`), which already has domain/ZIP disambiguation this
    function doesn't need to duplicate."""
    if label.strip().lower().rstrip("0123456789") in _GENERIC_SUBDOMAIN_WORDS:
        return None

    for candidate in (label, label.rstrip("0123456789")):
        if _table_lookup(candidate):
            return candidate.title(), None

    try:
        import wordninja
    except ImportError:
        return None
    words = wordninja.split(label)
    if not words:
        return None
    stripped_state: Optional[str] = None
    trailing = words[-1].lower()
    if len(words) > 1 and (
        trailing in _STATE_ABBREVIATIONS_LOWER
        or trailing in _PROVINCE_ABBREVIATIONS_LOWER
    ):
        stripped_state = trailing.upper()
        words = words[:-1]
    # "pub" joined this strip list 2026-08-19 (BACKLOG.md's jurisdiction-
    # misattribution entry): eScribe's own real, confirmed subdomain
    # convention is "pub-{city}.escribemeetings.com" (see
    # `EscribeAssetFinder`'s own `_SUBDOMAIN_RE` module comment), so the
    # raw label handed to this function is "pub-{city}" (or, after
    # `_validated_subdomain_extract()`'s host split, "pub-{city}" as
    # parts[0]) -- e.g. wordninja splits "pub-courtenay" to
    # ['pub','courtenay']. Without stripping "pub" here, this generic
    # (platform-agnostic) validator can never resolve ANY eScribe
    # subdomain on its own, which matters beyond eScribe's own dedicated
    # `_jurisdiction_from_subdomain()` fallback (which already strips
    # "pub-" via its own regex): `extract_jurisdiction_chain()`'s
    # subdomain tier and its cross-check against a text-mined candidate
    # (see that function's own comment) both call this same generic path,
    # and had no way to independently confirm an eScribe page's real
    # identity before this fix.
    while len(words) > 1 and words[0].lower() in (
        "city",
        "county",
        "town",
        "of",
        "pub",
    ):
        words = words[1:]
    if not words:
        return None
    spaced = " ".join(w.capitalize() for w in words)
    if len(spaced.replace(" ", "")) >= 3 and _table_lookup(spaced):
        return spaced, stripped_state
    # Hyphen-joined, tried between spaced and glued -- real gap found
    # 2026-08-29 auditing archived pages missing a jurisdiction: eScribe's
    # own "pub-{city}" subdomain convention means a real hyphenated Census/
    # StatsCan name either survives as-is in the label ("pub-chatham-kent"
    # -> wordninja splits its own "pub-" prefix's hyphen away too, cleanly
    # giving ['chatham', 'kent']) or arrives already glued by whoever
    # registered the subdomain ("pub-arranelderslie" -> wordninja still
    # splits it cleanly into ['arran', 'elderslie'], since both are real
    # dictionary-adjacent words on their own) -- but the table's own key is
    # "chatham-kent"/"arran-elderslie" (StatsCan's real hyphenated name),
    # which neither the spaced ("Chatham Kent") nor glued ("Chathamkent")
    # candidate above ever matches. Tried only when there are exactly 2
    # words: a 3+-word hyphenation would need to guess WHICH gap to
    # hyphenate, which no real example here motivates.
    if len(words) == 2:
        hyphenated = "-".join(w.capitalize() for w in words)
        if _table_lookup(hyphenated):
            return hyphenated, stripped_state
    glued = "".join(words).capitalize()
    if len(glued) >= 3 and _table_lookup(glued):
        return glued, stripped_state
    # A real, if small, leading-article gap: 17 real Census/StatsCan place
    # and county-subdivision names start with "The " ("The Blue Mountains,
    # ON", "The Colony city, TX", "The Dalles city, OR", among others,
    # confirmed via a plain grep across places.csv/county_subdivisions.csv
    # 2026-08-31) -- but a subdomain almost never spells out "the" (nobody
    # registers "pub-thebluemountains"), so the plain `spaced` candidate
    # above can never match these even though the table entry is real.
    # Found chasing BACKLOG.md's Blue Mountains entry, which had
    # misdiagnosed this as a hyphen-formatting gap (it isn't -- "Blue
    # Mountains" alone doesn't validate at all, hyphenated or not; only
    # prepending "The" does).
    if _table_lookup(f"The {spaced}"):
        return f"The {spaced}", stripped_state

    # Tier 4: trailing connector word, type word re-attached (see docstring).
    if len(words) > 1 and words[-1].lower() in _TRAILING_TYPE_WORDS:
        type_word = words[-1].capitalize()
        body = words[:-1]
        glued_body = "".join(body).capitalize()
        typed = f"{glued_body} {type_word}"
        if len(glued_body) >= 3 and _table_lookup(typed):
            return typed, stripped_state

    # Tier 7 (tried here, BEFORE tier 5, as of WO-76 2026-08-30 -- see the
    # precedence note in its own comment below): trailing state code AND a
    # trailing "co" (county) abbreviation, both stripped off the RAW label,
    # with the bare remainder checked directly against the COUNTY table --
    # for a name wordninja itself can't segment into anything usable. Real
    # gap: CivicClerk's "lenaweecomi" (Lenawee County, MI) -- "lenawee"
    # isn't an English dictionary word, so wordninja never recovers it even
    # after tier 5's own trailing-state strip (confirmed live:
    # `wordninja.split("lenaweeco") == ['lena','we','eco']`, garbage).
    # Trying the bare remainder directly against `_COUNTY_STATES` sidesteps
    # wordninja entirely, and -- as of the WO-76 fix -- is checked and
    # cross-validated against the SAME table `resolve_claimed_state()`
    # already trusts for this exact "does this specific state belong to
    # this specific name" question, rather than the general, type-agnostic
    # `_table_lookup()` (place table checked before county, so a bare name
    # that is ALSO a real place anywhere would win first and silently mask
    # a real county match here).
    #
    # Real, confirmed-live case this precision fixes (WO-76, 2026-08-30):
    # `chestercopa.portal.civicclerk.com` is Chester County, PA (its own
    # page header: "Chester County, PA - Agendas & Minutes"). "Chester" is
    # ALSO a real, unrelated place in its own right (PA, SC, and more --
    # `_table_lookup("Chester")` returns the PLACE table, not county), so
    # the old `hit[0] == "county"` gate declined every time -- it can only
    # ever fire when the bare name has NO place-table entry at all
    # anywhere, exactly like "Lenawee" but unlike "Chester". Checking
    # `_COUNTY_STATES` directly and requiring only that the SPECIFIC
    # extracted state (here "PA") be one of the name's real county states
    # sidesteps the place-vs-county precedence entirely -- correct even
    # when, as here, the bare name is nationally ambiguous as a place too.
    #
    # Precedence: this tier must run BEFORE tier 5's blind recursive
    # trailing-strip, not after -- real bug found investigating the same
    # `chestercopa` case. Tier 5's own recursive retry on "chesterco"
    # (after stripping "pa") independently strips ITS OWN trailing "co" as
    # if it were the Colorado state abbreviation (co IS a real state code,
    # not just the county-abbreviation convention this tier exists for),
    # succeeding early with the wrong pair ("Chester", "CO") before this
    # tier -- previously positioned after tier 5 and 6 -- ever got a
    # chance to run at all. Moving it earlier lets the more specific,
    # better-evidenced "trailing state + trailing county-abbreviation"
    # shape win over tier 5's generic, coincidence-prone strip whenever
    # both could apply; verified this reordering doesn't change any
    # already-passing tier 5/6 case (neither camaswa/stmarysga nor
    # macombtwpmi/southorangetwpnj ends in "co" before their trailing
    # state code, so this tier's own guard never fires for them).
    if _allow_state_strip and len(label) >= 7:
        lower_label = label.lower()
        tail = lower_label[-2:]
        if tail in _STATE_ABBREVIATIONS_LOWER or tail in _PROVINCE_ABBREVIATIONS_LOWER:
            remainder = lower_label[:-2]
            if remainder.endswith("co") and len(remainder) - 2 >= 3:
                bare = remainder[:-2]
                county_states = _COUNTY_STATES.get(bare)
                if county_states and tail.upper() in county_states:
                    return f"{bare.title()} County", tail.upper()

    # Tier 5: trailing state/province code stripped off the RAW label,
    # before wordninja ever sees it (see docstring). Length floor keeps the
    # same >= 3-letter guarantee the tiers above run on.
    if _allow_state_strip and len(label) >= 5:
        tail = label[-2:].lower()
        if tail in _STATE_ABBREVIATIONS_LOWER or tail in _PROVINCE_ABBREVIATIONS_LOWER:
            retry = _validated_label_extract_with_state(
                label[:-2], _allow_state_strip=False
            )
            if retry:
                return retry[0], retry[1] or tail.upper()

    # Tier 6: a "twp" abbreviation glued between the name and the state
    # (see `_twp_glued_extract()`'s own comment for the exact shape and
    # the real CivicClerk subdomains this was built from, 2026-08-30).
    # Tried on the RAW label, gated the same way tier 5 is -- only at the
    # outermost call, never during tier 5's own recursive retry, since by
    # the time that retry runs the trailing state is already gone from
    # `label` and this pattern can no longer match anyway.
    if _allow_state_strip:
        twp_hit = _twp_glued_extract(label)
        if twp_hit:
            return twp_hit

    return None


def _validated_subdomain_hint_with_state(
    netloc: str,
) -> Optional[Tuple[str, Optional[str]]]:
    """(name, state) for `netloc`'s own subdomain label, same host-parsing
    as `_validated_subdomain_extract_from_netloc()` below but keeping the
    state `_validated_label_extract_with_state()` derived, when the label
    itself spelled one out (e.g. "douglas-mi" -> ("Douglas", "MI")) --
    needed by `finalize_jurisdiction()`'s call into `_subdomain_override()`
    (see that function's own `hint_state` parameter/docstring, WO-76,
    2026-08-30) as a stronger, self-declared state signal than whatever
    (possibly wrong) suffix survived from the page's own text. Declines the
    same way (bare domain, "www" subdomain) as the name-only variant."""
    host = netloc.lower()
    parts = host.split(".")
    if len(parts) <= 2 or parts[0] == "www":
        return None
    return _validated_label_extract_with_state(parts[0])


def _validated_subdomain_extract_from_netloc(netloc: str) -> Optional[str]:
    """Same logic as `_validated_subdomain_extract()` below, but taking an
    already-parsed netloc directly rather than a full URL -- split out
    2026-08-21 (BACKLOG.md's jurisdiction-bleed entries: "trim-repair can
    turn a bled value into a confidently WRONG real city" and "eScribe's
    chain picks the wrong government for a two-tier regional site") so
    `finalize_jurisdiction()` can compute the same subdomain-derived
    cross-check candidate it already has `netloc` for, without
    constructing a throwaway URL just to re-parse it back apart. Thin
    wrapper around `_validated_subdomain_hint_with_state()` that drops the
    state, for the many callers that only want the name."""
    hint = _validated_subdomain_hint_with_state(netloc)
    return hint[0] if hint else None


def _validated_subdomain_extract(url: str) -> Optional[str]:
    """URL-taking wrapper around `_validated_label_extract()` -- parses the
    subdomain label out of `url` (declining on a bare domain or a "www"
    subdomain, same as before) and delegates. See that function's own
    docstring for the actual validation logic."""
    return _validated_subdomain_extract_from_netloc(urlparse(url).netloc)


def validated_subdomain_extract(url: str) -> Optional[str]:
    """Public wrapper around `_validated_subdomain_extract()` for callers
    outside this module's own chain -- e.g. granicus.py's subdomain-
    humanization fallback, which used to always guess via a bare
    wordninja split (confident garbage on acronym subdomains like
    "sfwmd" -> "S Fw, MD", see BACKLOG.md) instead of declining when
    nothing validates against the Census tables."""
    return _validated_subdomain_extract(url)


def validated_label_extract(label: str) -> Optional[str]:
    """Public wrapper around `_validated_label_extract()` for callers that
    already have a bare subdomain label rather than a full URL -- e.g.
    `EscribeAssetFinder._jurisdiction_from_subdomain()`, which extracts its
    own label via `_SUBDOMAIN_RE` (eScribe's "pub-{label}" convention) and
    would otherwise have to round-trip through a synthetic URL just to
    reuse `validated_subdomain_extract()`."""
    return _validated_label_extract(label)


def validated_label_extract_with_state(
    label: str,
) -> Optional[Tuple[str, Optional[str]]]:
    """Public wrapper around `_validated_label_extract_with_state()`, for a
    caller that also needs the 2-letter state/province code this module
    stripped off the label to make it validate -- today only
    `app/platforms/suiteone.py`'s `_extract_jurisdiction()`, whose real
    tenants include glued name+state slugs ("camaswa", "stmarysga") that
    only resolve via that strip. See that function's docstring for why the
    caller can't safely re-derive the code on its own."""
    return _validated_label_extract_with_state(label)


# K-12/library/community-media institutional suffixes that ride along on
# a real place name in a free-text account/channel name -- confirmed
# real, 2026-08-29, from Vimeo's direct-dorking batch (BACKLOG_DONE.md,
# "22 new real ingests"): "Peters Township School District" (Peters
# Township, PA), "Hopkins Public Schools" (Hopkins, MN), "Jefferson
# Parish Schools" (Jefferson Parish, LA), "Seekonk Public Schools"
# (Seekonk, MA), "Mason County District Library" (Mason County, MI),
# "Willits Community Television Inc" (Willits, CA), "Morrilton Community
# Channel 6" (Morrilton, AR), "Peters Township Community TV" (Peters
# Township, PA again -- a second, distinct account from the school
# district one above), "Town of Penfield Television" (Town of Penfield,
# NY). Shared here (not left local to vimeo.py) because youtube.py's
# `_jurisdiction()` explicitly mirrors vimeo.py's model and hits the
# identical `validated_label_extract()` call on the identical shape of
# input (a platform account/channel's own display name) -- the suffix is
# a naming convention real government/community-media accounts use, not
# a Vimeo-specific quirk, so a second adapter reading the same kind of
# name is exactly the case this needs to already cover. Order matters
# only in that a more specific phrase must be tried before a shorter one
# it contains ("Public Schools" before bare "Schools", "Community
# Television Inc" before "Television" alone), so stripping the short form
# alone never leaves a dangling qualifier word in front of it.
_INSTITUTIONAL_SUFFIX_RE = re.compile(
    r"\s+(?:Public Schools|School District|District Library|Schools"
    r"|Community Television(?: Inc\.?)?|Community TV|Community Channel \d+"
    r"|Television)$",
    re.IGNORECASE,
)


def strip_institutional_suffix(name: str) -> str:
    """Strips a confirmed-real trailing K-12/library institutional phrase
    from a free-text account/channel name, e.g. "Hopkins Public Schools"
    -> "Hopkins" -- see `_INSTITUTIONAL_SUFFIX_RE`'s own comment for the
    real examples this is built from. A caller should run this BEFORE
    `validated_label_extract()`/`enrich_jurisdiction_text()`, since the
    suffix is never part of the place's own proper name and blocks the
    whole glued phrase from validating as one unit. Returns `name`
    unchanged when no such suffix is present."""
    return _INSTITUTIONAL_SUFFIX_RE.sub("", name)


def _base_name_key(jurisdiction: str) -> str:
    """Bare, normalized identity key for a finished jurisdiction string --
    state suffix stripped, then normalized down to its bare proper name
    (leading "City of "/etc. removed, or a trailing generic type word
    removed when present) -- used by `extract_jurisdiction_chain()` to
    compare a text-mined candidate's resolved identity against a
    URL-derived subdomain hint's identity, ignoring formatting
    differences ("City of Hercules, CA" vs. "Hercules", "San Bernardino
    County" vs. "San Bernardino"). Uses the LAST (most-stripped) candidate
    `_normalize_candidates()` returns, not the first -- unlike
    `_table_lookup_strength()`'s literal-vs-heuristic distinction (which
    cares whether a match came from the exact typed text), this is a pure
    identity comparison, so the bare-est form is the right one to key on."""
    base = _STATE_SUFFIX_RE.sub("", jurisdiction).strip().rstrip(".,;:")
    candidates = _normalize_candidates(base)
    return candidates[-1] if candidates else base.lower()


def _county_retype_from_page_text(candidate: str, page_text: str) -> str:
    """Retype a bare subdomain-derived name as a county when the page's
    own text says it is one -- "{Name} County" or "County of {Name}" --
    and no "City of {Name}" phrasing contradicts it.

    Real, confirmed-live failure this closes (2026-08-23, found via
    Google's crawl of /state/california): `albemarle.granicus.com`'s clip
    pages carry "Albemarle County" in their own visible text (plus a
    Board of Supervisors title and an albemarle.legistar1.com agenda
    link), but the shared chain's subdomain tier hands back the bare
    label "Albemarle", `enrich_jurisdiction_text()` types a bare name as
    a CITY, and "Albemarle" the city uniquely resolves to... North
    Carolina. Result: a real Virginia county government archived as
    "Albemarle, NC", a different state's unrelated city. The county
    table knows "Albemarle County" -> VA unambiguously the whole time.

    Guards, in order:
    - Only a bare candidate (no government-type word of its own) is ever
      retyped -- a "City of X" stop-rule candidate is already typed and
      never reaches here (this runs on the subdomain tier only).
    - The page must actually contain county phrasing for THIS name.
    - "City of {Name}" anywhere on the page vetoes the retype: a city
      page can legitimately mention its surrounding same-named county
      (e.g. a "Fresno" city page mentioning Fresno County), and when the
      page names both, the text tiers above this one already had first
      claim on the explicit "City of X" phrasing.
    - "{Name} County" must itself be a real county name in the tables --
      otherwise the retyped string couldn't validate and the tier's own
      validation gate below would discard it anyway.
    """
    if _TYPE_HINT_RE.search(candidate) or _COUNTY_TYPE_HINT_RE.search(candidate):
        return candidate
    escaped = re.escape(candidate)
    if not re.search(rf"\b(?:County\s+of\s+{escaped}|{escaped}\s+County)\b", page_text):
        return candidate
    if re.search(rf"\bCity\s+of\s+{escaped}\b", page_text):
        return candidate
    retyped = f"{candidate} County"
    for norm in _normalize_candidates(retyped):
        if _COUNTY_STATES.get(norm):
            return retyped
    return candidate


def extract_jurisdiction_chain(*, page_text: str, html: str, url: str) -> Optional[str]:
    """Shared fallback chain for adapters whose own primary extraction
    found nothing: stop-rule body regex -> capitalization-bounded walk ->
    validated subdomain, tried in tournament-ranked order, first hit
    wins.

    Every candidate is required to actually validate (directly, via
    trim-repair, or via the domain registry -- i.e. whatever
    `finalize_jurisdiction()` would grade "validated"/"repaired"/
    "authoritative") before being accepted; a candidate that doesn't
    clear that bar is discarded and the next tier is tried instead of
    ever being returned raw. This is stricter than
    `finalize_jurisdiction()`'s own general policy of keeping an
    unvalidatable *adapter-native* jurisdiction unchanged ("unverified"
    -- school districts, MPOs, etc. genuinely aren't in any table) --
    that trust basis doesn't exist here, since every candidate in THIS
    chain is a generic regex guess over arbitrary page text, not a
    purpose-built adapter extraction. Real, confirmed-live failure this
    guards against (2026-08-15): on a Broward MPO Swagit page
    (browardmpo.new.swagit.com/videos/359517), the capitalization walk
    matched into an ALL-CAPS caption line of someone's spoken testimony
    ("...IN THE CITY OF FORT LAUDERDALE THAT'S IDENTIFIED...") and would
    have stored "City of Fort Lauderdale That'S Identified" as the
    jurisdiction -- a real place name's-worth of text bled into
    something no adapter's own extraction would ever produce. Declining
    (returning None, leaving the page's jurisdiction blank as before) is
    correct here; a real city mention inside spoken dialogue is not
    reliable evidence of the *meeting's own* jurisdiction, the same
    lesson `_JURISDICTION_RE`'s SLC/Holladay false positive already
    taught for PrimeGov's agenda-body text (see that regex's own
    module-level comment in app/platforms/primegov.py).

    Deliberately does NOT consult the known-domain registry as its own
    separate step -- `finalize_jurisdiction()` already does, both here
    (for gating) and again at the caller's own ingest-time call, so
    registry coverage is still applied, just not duplicated as a
    dedicated tier.

    Cross-checked against a validated URL/subdomain hint since 2026-08-19
    (BACKLOG.md's jurisdiction-misattribution entry): the "must validate"
    gate above only catches a candidate that's outright garbage (the
    Broward MPO case), not one that cleanly validates as a real, DIFFERENT
    place than the page's own true jurisdiction -- confirmed live via two
    separate real cases, both a stoprule/capitalization-walk match on a
    genuine but unrelated "City/County of X" mention elsewhere on the page
    (a correspondence item, cross-jurisdictional reference, or boilerplate
    mention), not the page's own identity: "Courtenay (BC) misattributed
    to Burlington" (Burlington is a real, validating place in 17
    states/provinces -- ambiguous, but still "known" enough to pass the
    validation gate) and "Victorville misattributed to San Bernardino
    County" (both real, validating California entities). When the URL's
    own subdomain independently and unambiguously validates to a real
    place/county -- the same trustworthy identity signal the subdomain
    tier below already relies on for its own answer -- a text-mined
    candidate that names a demonstrably DIFFERENT place is discarded
    instead of accepted, falling through to try the next tier and
    ultimately reaching the subdomain tier's own (correct) answer rather
    than a coincidentally-validating wrong one. A candidate that AGREES
    with the subdomain hint (the overwhelmingly common case -- e.g.
    hercules.granicus.com's own "City of Hercules" text) is unaffected;
    so is every case with no subdomain hint available at all (most
    Swagit/CivicClerk/generic_fallback pages), which is why this doesn't
    touch the tournament-tuned recall for those.
    """
    netloc = urlparse(url).netloc
    subdomain_hint = _validated_subdomain_extract(url)
    subdomain_hint_key = _base_name_key(subdomain_hint) if subdomain_hint else None

    for tier, extractor in (
        ("text", lambda: _stoprule_extract(page_text)),
        ("text", lambda: _capitalization_walk_extract(html)),
        ("subdomain", lambda: subdomain_hint),
    ):
        candidate = extractor()
        if not candidate:
            continue
        if tier == "subdomain":
            candidate = _county_retype_from_page_text(candidate, page_text)
        enriched = enrich_jurisdiction_text(
            candidate, netloc=netloc, page_text=page_text
        )
        result = finalize_jurisdiction(enriched, netloc=netloc)
        if result.confidence not in ("validated", "repaired", "authoritative"):
            continue
        if (
            tier == "text"
            and subdomain_hint_key
            and _base_name_key(result.jurisdiction) != subdomain_hint_key
        ):
            continue
        return result.jurisdiction
    return None
