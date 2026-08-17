"""Canonicalizes a trailing US state or Canadian province/territory name
in a free-text `jurisdiction` string to its 2-letter abbreviation, so
/meetings doesn't show the same state in two different forms across rows
(e.g. "San Diego, California" on one row, "Dublin, CA" on another) --
same idea for "Calgary, Alberta" vs. "Airdrie, AB". `jurisdiction` is a
single free-text column (see BACKLOG.md) with no separate city/state
fields, so this only ever touches the trailing comma-separated component
-- the rest of the string (city/county/body name) is unbounded free text
and is passed through byte-for-byte unchanged, since blindly reformatting
it risks mangling a real name with no easy undo (acronyms, apostrophes,
multi-word names -- see BACKLOG.md's fuller reasoning on why city/title
casing is deliberately *not* touched here).
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


# Canadian provinces/territories -- added 2026-08-17 alongside a "Browse
# by state" Canada grouping and a Canadian-jurisdiction display suffix
# (see format_jurisdiction_display() below). Kept as its own source dict,
# separate from US_STATE_NAME_TO_ABBR above, rather than merged into it --
# this repo already has several already-archived, real Canadian
# jurisdictions ("Airdrie, AB", "Amherstburg, ON", "Calgary, AB", "Elliot
# Lake, ON" -- confirmed live on /coverage) that state_abbr_from_jurisdiction()
# couldn't previously group under any state page at all. 13 entries: all
# 10 provinces plus the 3 territories (Yukon, Northwest Territories,
# Nunavut) -- grouped together the same way "provinces and territories" is
# the real, commonly-used umbrella term in Canada, not a simplification.
CA_PROVINCE_NAME_TO_ABBR = {
    "alberta": "AB",
    "british columbia": "BC",
    "manitoba": "MB",
    "new brunswick": "NB",
    "newfoundland and labrador": "NL",
    "northwest territories": "NT",
    "nova scotia": "NS",
    "nunavut": "NU",
    "ontario": "ON",
    "prince edward island": "PE",
    "quebec": "QC",
    "saskatchewan": "SK",
    "yukon": "YT",
}

# Every US state/DC abbr plus every Canadian province/territory abbr --
# the two abbr sets don't overlap (confirmed: no Canadian province code
# collides with a US postal abbreviation), so a plain union is safe. Used
# by state_abbr_from_jurisdiction()/normalize_state_suffix() below to
# recognize either country's suffix without either function needing to
# know which country it's looking at.
_VALID_STATE_ABBRS = set(US_STATE_NAME_TO_ABBR.values()) | set(
    CA_PROVINCE_NAME_TO_ABBR.values()
)

# "CA" -> "California". Inverted from the dict above rather than
# hand-maintained; a naive .title() on "district of columbia" would yield
# "District Of Columbia", hence the override. Combined with the Canadian
# provinces/territories below into one lookup, since the overwhelming
# majority of call sites (state_slug_from_abbr(), meeting_page.html's
# "More {State} meetings" link, get_state_page_data()'s "name" field, ...)
# just need "abbr -> display name" and shouldn't have to care which
# country -- see is_canadian_abbr() below for the few call sites that
# genuinely do (the /coverage "Browse by state" Canada grouping, the
# Canadian display suffix).
US_STATE_ABBR_TO_NAME = {
    abbr: name.title() for name, abbr in US_STATE_NAME_TO_ABBR.items()
}
US_STATE_ABBR_TO_NAME["DC"] = "District of Columbia"
US_STATE_ABBR_TO_NAME.update(
    {abbr: name.title() for name, abbr in CA_PROVINCE_NAME_TO_ABBR.items()}
)
# Same naive-.title() problem as DC above -- "newfoundland and
# labrador".title() would yield "... And Labrador".
US_STATE_ABBR_TO_NAME["NL"] = "Newfoundland and Labrador"

# "california" / "alberta" -> "CA" / "AB", for /state/{slug}. Combined
# the same way as US_STATE_ABBR_TO_NAME above -- a province slug just
# works at /state/{slug} with no separate route/lookup needed.
STATE_SLUG_TO_ABBR = {
    name.replace(" ", "-"): abbr for name, abbr in US_STATE_NAME_TO_ABBR.items()
}
STATE_SLUG_TO_ABBR.update(
    {name.replace(" ", "-"): abbr for name, abbr in CA_PROVINCE_NAME_TO_ABBR.items()}
)

_CANADIAN_ABBRS = set(CA_PROVINCE_NAME_TO_ABBR.values())


def is_canadian_abbr(abbr: Optional[str]) -> bool:
    """True for a Canadian province/territory abbreviation ("AB", "ON",
    ...); False for a US state/DC abbreviation, None, or anything else.
    The few call sites that need to know *which country* a recognized
    abbr belongs to -- crud.py's get_state_coverage_index() (the
    /coverage "Browse by state" Canada grouping) and
    format_jurisdiction_display() below (the Canadian display suffix) --
    use this instead of a second name/abbr lookup table, since
    US_STATE_ABBR_TO_NAME/STATE_SLUG_TO_ABBR above already combine both
    countries for the far more common "just give me the name/slug" case.
    """
    return abbr in _CANADIAN_ABBRS


def state_abbr_from_jurisdiction(jurisdiction: Optional[str]) -> Optional[str]:
    """ "Napa, CA" -> "CA", "Calgary, AB" -> "AB". None when the text after
    the last comma isn't exactly a valid 2-letter US state or Canadian
    province/territory abbreviation -- the stored form is canonical
    uppercase via `normalize_state_suffix()` at write time, so this
    deliberately doesn't re-run full-name or case repairs. Callers that
    need to know which country an abbr belongs to should follow up with
    `is_canadian_abbr()`."""
    if not jurisdiction or "," not in jurisdiction:
        return None
    _, _, suffix = jurisdiction.rpartition(",")
    suffix = suffix.strip()
    if suffix in _VALID_STATE_ABBRS:
        return suffix
    return None


def state_slug_from_abbr(abbr: str) -> str:
    return US_STATE_ABBR_TO_NAME[abbr].lower().replace(" ", "-")


def normalize_state_suffix(jurisdiction: Optional[str]) -> Optional[str]:
    """ "San Diego, California" -> "San Diego, CA", "Calgary, Alberta" ->
    "Calgary, AB". Only fires when the text after the *last* comma is
    exactly a recognized full US state or Canadian province/territory name
    (case-insensitive) -- state-less ("Illinois General Assembly") or
    unrecognized trailing text passes through unchanged. This runs at
    ingest/write time (see `crud.py`'s call site), so adding Canadian
    province recognition here is a real ingest-time behavior change, not
    just a display tweak -- it's what makes a freshly-ingested "Calgary,
    Alberta" or "Airdrie, Alberta" get canonicalized to ", AB" the same
    way a US state name always has been.

    Also re-cases an already-2-letter suffix that's a real state/province
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
    abbr = US_STATE_NAME_TO_ABBR.get(suffix.lower()) or CA_PROVINCE_NAME_TO_ABBR.get(
        suffix.lower()
    )
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
    Expands a search term that's exactly a recognized full state or
    province/territory name (e.g. "California" or "Alberta") to also
    include its abbreviation ("CA"/"AB"), so a caller can OR both
    together -- also what makes /state/{slug}'s "Search all {name}
    meetings" link work for a Canadian province page. Returns just
    `[term]`, unchanged, for anything that isn't a bare full-name match
    (partial text, an abbreviation already, a city name, etc.) --
    deliberately doesn't touch those, since the original term still needs
    to keep matching state-legislature-style jurisdictions that were never
    comma-normalized (e.g. "California State Assembly" has no trailing ",
    California" for normalize_state_suffix to have touched).
    """
    stripped = term.strip()
    abbr = US_STATE_NAME_TO_ABBR.get(stripped.lower()) or CA_PROVINCE_NAME_TO_ABBR.get(
        stripped.lower()
    )
    if abbr and abbr != stripped.upper():
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

    Also appends " (Canada)" for a jurisdiction whose trailing ", ST"
    suffix is a Canadian province/territory abbreviation (e.g. "Calgary,
    AB" -> "Calgary, AB (Canada)") -- added 2026-08-17 alongside the
    "Browse by state" Canada grouping, since a bare 2-letter province code
    reads as a typo'd US state to a reader who doesn't recognize it.
    Picked over a ", Canada" third comma segment specifically to avoid
    reading like a third address component ("City, ST, Canada") next to
    the existing "City, ST" convention. Applied last, after any prefix
    stripping above, so it's consistent regardless of which earlier branch
    produced the base string.
    """
    if not jurisdiction:
        return jurisdiction
    if jurisdiction.lower().startswith("city and county of "):
        result = jurisdiction
    else:
        result = jurisdiction
        for prefix in _DROPPED_DISPLAY_PREFIXES:
            if jurisdiction.lower().startswith(prefix.lower()):
                result = jurisdiction[len(prefix) :]
                break
    abbr = state_abbr_from_jurisdiction(result)
    if abbr and is_canadian_abbr(abbr):
        return f"{result} (Canada)"
    return result
