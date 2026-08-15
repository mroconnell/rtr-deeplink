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
    returns None rather than guessing.
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
        name = name[leading_match.end():]
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
        return [name[leading_match.end():].strip().lower()]
    as_is = name.lower()
    stripped = _TRAILING_TYPE_RE.sub("", name).strip().lower()
    return [as_is] if stripped == as_is else [as_is, stripped]


def _load_name_state_table(filename: str) -> Dict[str, List[str]]:
    table: Dict[str, List[str]] = {}
    path = _DATA_DIR / filename
    if not path.exists():
        return table
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = _normalize_name(row["name"])
            table.setdefault(key, []).append(row["state"])
    return table


def _load_zcta_table(filename: str, name_column: str) -> Dict[str, List[Tuple[str, str, int]]]:
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
_PLACE_STATES = _load_name_state_table("places.csv")
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
    instances of some via `lookup_by_domain()` below."""
    for candidate in _normalize_candidates(name):
        states = _PLACE_STATES.get(candidate)
        if states:
            return states[0] if len(set(states)) == 1 else None
    return None


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
    return [(m.group(1).strip(), m.group(2), m.group(3)) for m in _ZIP_ADDRESS_RE.finditer(text)]


@dataclass(frozen=True)
class KnownJurisdiction:
    name: str
    type: str  # "city" or "county"
    state: str


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
    "slc.primegov.com": KnownJurisdiction("Salt Lake City", "city", "UT"),
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

    name_lookup = lookup_county_state if jurisdiction_type == "county" else lookup_city_state
    if name:
        state = name_lookup(name)
        if state:
            return state

    if page_text:
        zip_lookup = lookup_county_by_zip if jurisdiction_type == "county" else lookup_place_by_zip
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
    state = resolve_state(jurisdiction, jurisdiction_type, netloc=netloc, page_text=page_text)
    return f"{jurisdiction}, {state}" if state else jurisdiction
