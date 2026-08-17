"""Canonicalizes a trailing US state name in a free-text `jurisdiction`
string to its 2-letter abbreviation, so /meetings doesn't show the same
state in two different forms across rows (e.g. "San Diego, California" on
one row, "Dublin, CA" on another). `jurisdiction` is a single free-text
column (see BACKLOG.md) with no separate city/state fields, so this only
ever touches the trailing comma-separated component -- the rest of the
string (city/county/body name) is unbounded free text and is passed
through byte-for-byte unchanged, since blindly reformatting it risks
mangling a real name with no easy undo (acronyms, apostrophes, multi-word
names -- see BACKLOG.md's fuller reasoning on why city/title casing is
deliberately *not* touched here).
"""

from typing import Optional

US_STATE_NAME_TO_ABBR = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
    "district of columbia": "DC",
}


_VALID_STATE_ABBRS = set(US_STATE_NAME_TO_ABBR.values())


def normalize_state_suffix(jurisdiction: Optional[str]) -> Optional[str]:
    """ "San Diego, California" -> "San Diego, CA". Only fires when the
    text after the *last* comma is exactly a recognized full state name
    (case-insensitive) -- state-less ("Illinois General Assembly") or
    unrecognized trailing text passes through unchanged.

    Also re-cases an already-2-letter suffix that's a real state
    abbreviation but not uppercase (e.g. "Colorado Springs, Co") -- real
    bug found live 2026-08-13: Colorado Springs' own Granicus RSS channel
    title carries the state as "Co", which the full-name lookup above
    never catches (it's not "colorado"), so a mis-cased abbreviation
    would otherwise ride through both this function and
    `format_jurisdiction_display()` untouched, since neither expects an
    adapter's own source text to already be state-shaped but wrong-cased.
    An already-correct "Dublin, CA" is a no-op here (`.upper()` on an
    already-uppercase string).
    """
    if not jurisdiction or "," not in jurisdiction:
        return jurisdiction
    prefix, _, suffix = jurisdiction.rpartition(",")
    suffix = suffix.strip()
    abbr = US_STATE_NAME_TO_ABBR.get(suffix.lower())
    if abbr:
        return f"{prefix.strip()}, {abbr}"
    if (
        len(suffix) == 2
        and suffix.upper() in _VALID_STATE_ABBRS
        and suffix != suffix.upper()
    ):
        return f"{prefix.strip()}, {suffix.upper()}"
    return jurisdiction


def jurisdiction_search_terms(term: str) -> list[str]:
    """Real search-side gap found 2026-08-14: /meetings' jurisdiction filter
    does a plain substring match against the *stored* column, which
    `normalize_state_suffix()` above means almost always holds the 2-letter
    abbreviation, not the full state name -- so a natural search like
    "California" structurally could never match "Sacramento County, CA".
    Expands a search term that's exactly a recognized full state name (e.g.
    "California") to also include its abbreviation ("CA"), so a caller can
    OR both together. Returns just `[term]`, unchanged, for anything that
    isn't a bare full-name match (partial text, an abbreviation already, a
    city name, etc.) -- deliberately doesn't touch those, since the original
    term still needs to keep matching state-legislature-style jurisdictions
    that were never comma-normalized (e.g. "California State Assembly" has
    no trailing ", California" for normalize_state_suffix to have touched).
    """
    abbr = US_STATE_NAME_TO_ABBR.get(term.strip().lower())
    if abbr and abbr != term.strip().upper():
        return [term, abbr]
    return [term]


_DROPPED_DISPLAY_PREFIXES = ("The City of ", "City of ", "City ")


def format_jurisdiction_display(jurisdiction: Optional[str]) -> Optional[str]:
    """Drops a leading "The City of "/"City of "/"City " for display --
    user request 2026-08-12: almost everything archived is a city, so
    labeling every row that way ("City of Napa, CA") reads as redundant.
    Reserves the
    explicit label for the real exceptions this repo actually stores --
    "County of X"/"X County" and state-legislature-style body names both
    pass through unchanged, since dropping the label there would make a
    real, useful distinction disappear.

    Real bug found live 2026-08-13: a naive "starts with 'City '" check
    also matched "City and County of San Francisco"/"...Denver" (real
    consolidated city-county governments) on just the first 5 characters,
    leaving a mangled "and County of San Francisco". Checked first, and
    left completely untouched -- the "and County of" phrasing is real,
    non-redundant information (unlike a plain "City of"), same reasoning
    as why "County of X" alone is already preserved above.
    """
    if not jurisdiction:
        return jurisdiction
    if jurisdiction.lower().startswith("city and county of "):
        return jurisdiction
    for prefix in _DROPPED_DISPLAY_PREFIXES:
        if jurisdiction.lower().startswith(prefix.lower()):
            return jurisdiction[len(prefix) :]
    return jurisdiction
