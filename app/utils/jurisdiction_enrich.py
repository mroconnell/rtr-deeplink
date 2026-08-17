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
    return [
        (m.group(1).strip(), m.group(2), m.group(3))
        for m in _ZIP_ADDRESS_RE.finditer(text)
    ]


@dataclass(frozen=True)
class KnownJurisdiction:
    name: str
    type: str  # "city" or "county"
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
    "slc.primegov.com": KnownJurisdiction(
        "Salt Lake City", "city", "UT", strength="authoritative"
    ),
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
    (`_strip_okina()`) when the raw name doesn't match as-is."""
    name = name.strip().rstrip(".,;:")
    if not name:
        return None
    county_first = bool(_COUNTY_TYPE_HINT_RE.search(name))
    tables = (
        [("county", _COUNTY_STATES), ("place", _PLACE_STATES)]
        if county_first
        else [("place", _PLACE_STATES), ("county", _COUNTY_STATES)]
    )
    candidates = list(_normalize_candidates(name))
    expanded = _expand_abbreviations(name)
    if expanded != name:
        candidates.extend(_normalize_candidates(expanded))
    contracted = _contract_saints(name)
    if contracted != name:
        candidates.extend(_normalize_candidates(contracted))
    de_okina = _strip_okina(name)
    if de_okina != name:
        candidates.extend(_normalize_candidates(de_okina))
    for candidate in candidates:
        for label, table in tables:
            if candidate in table:
                return label, sorted(set(table[candidate]))
    return None


_ROMAN_NUMERAL_RE = re.compile(r"\b[IVXLC]{2,6}\.?\b")


def _looks_like_bleed(tail: str) -> bool:
    """Sanity check on text a trim would discard: does it look like
    sentence/agenda bleed (lowercase prose, roman-numeral list markers,
    digits) rather than part of a real longer name? Confirmed against the
    2026-08-15 audit's full "repaired_by_trim" bucket (73 cases): every
    one of the 16 cases this signal flags was a correct repair, and every
    one of the 57 it left alone was a real, legitimately long name (e.g.
    "Bay Area Headquarters Authority") that a bare trim would have
    mangled -- so this gate is required, not optional, for the trim below
    to be safe."""
    if _ROMAN_NUMERAL_RE.search(tail):
        return True
    if re.search(r"\d", tail):
        return True
    return any(w[0].islower() for w in tail.split() if w)


def _trim_repair(name: str) -> Optional[Tuple[str, str]]:
    """Longest-valid-prefix repair: drop tokens from the right until the
    remainder validates, but only when the discarded tail itself looks
    like bleed (`_looks_like_bleed()`) -- never applied bare, since most
    of the audit's trim-reachable names were legitimate long entities a
    blind trim would have destroyed. Returns (repaired_name, table) or
    None."""
    tokens = name.split()
    for cut in range(len(tokens) - 1, 0, -1):
        prefix = " ".join(tokens[:cut]).rstrip(".,;:")
        if not prefix:
            continue
        hit = _table_lookup(prefix)
        if hit and _looks_like_bleed(" ".join(tokens[cut:])):
            return prefix, hit[0]
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
    """
    known = lookup_by_domain(netloc) if netloc else None

    if known and known.strength == "authoritative":
        return JurisdictionResult(f"{known.name}, {known.state}", None, "authoritative")

    if not raw_jurisdiction:
        if known:
            return JurisdictionResult(f"{known.name}, {known.state}", None, "fallback")
        return JurisdictionResult(raw_jurisdiction, None, "blank")

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
        return JurisdictionResult(raw_jurisdiction, None, "validated")

    trimmed = _trim_repair(base)
    if trimmed:
        repaired_name, _table = trimmed
        return JurisdictionResult(
            f"{repaired_name}{_fill_missing_state(repaired_name, suffix, netloc)}",
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


def _validated_subdomain_extract(url: str) -> Optional[str]:
    """Bare (no state suffix) subdomain-derived name, validated against
    the Census tables before ever being offered as a candidate -- unlike
    the shipped wordninja-humanize fallback (Granicus's
    `_humanize_subdomain()`), this declines instead of guessing when
    nothing validates (416 table-valid / 0 garbage of 649 in the
    tournament, vs. 408 valid / 229 garbage for the shipped
    wordninja-always approach). Tried unsplit first -- fixes Galesburg:
    wordninja's own split ("Gales Burg") never validates, while the raw
    label does -- and only falls back to a wordninja split when the raw
    label itself doesn't validate. State is deliberately left to the
    caller's `enrich_jurisdiction_text()` pass, which already has
    domain/ZIP disambiguation this function doesn't need to duplicate."""
    host = urlparse(url).netloc.lower()
    parts = host.split(".")
    if len(parts) <= 2 or parts[0] == "www":
        return None
    label = parts[0]

    for candidate in (label, label.rstrip("0123456789")):
        if _table_lookup(candidate):
            return candidate.title()

    try:
        import wordninja
    except ImportError:
        return None
    words = wordninja.split(label)
    if not words:
        return None
    if len(words) > 1 and words[-1].lower() in _STATE_ABBREVIATIONS_LOWER:
        words = words[:-1]
    while len(words) > 1 and words[0].lower() in ("city", "county", "town", "of"):
        words = words[1:]
    if not words:
        return None
    name = " ".join(w.capitalize() for w in words)
    return name if _table_lookup(name) else None


def validated_subdomain_extract(url: str) -> Optional[str]:
    """Public wrapper around `_validated_subdomain_extract()` for callers
    outside this module's own chain -- e.g. granicus.py's subdomain-
    humanization fallback, which used to always guess via a bare
    wordninja split (confident garbage on acronym subdomains like
    "sfwmd" -> "S Fw, MD", see BACKLOG.md) instead of declining when
    nothing validates against the Census tables."""
    return _validated_subdomain_extract(url)


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
    """
    netloc = urlparse(url).netloc
    for extractor in (
        lambda: _stoprule_extract(page_text),
        lambda: _capitalization_walk_extract(html),
        lambda: _validated_subdomain_extract(url),
    ):
        candidate = extractor()
        if not candidate:
            continue
        enriched = enrich_jurisdiction_text(
            candidate, netloc=netloc, page_text=page_text
        )
        result = finalize_jurisdiction(enriched, netloc=netloc)
        if result.confidence in ("validated", "repaired", "authoritative"):
            return result.jurisdiction
    return None
