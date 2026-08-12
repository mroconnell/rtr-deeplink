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
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC",
}


def normalize_state_suffix(jurisdiction: Optional[str]) -> Optional[str]:
    """"San Diego, California" -> "San Diego, CA". Only fires when the
    text after the *last* comma is exactly a recognized full state name
    (case-insensitive) -- already-abbreviated ("Dublin, CA"), state-less
    ("Illinois General Assembly"), or unrecognized trailing text all pass
    through unchanged.
    """
    if not jurisdiction or "," not in jurisdiction:
        return jurisdiction
    prefix, _, suffix = jurisdiction.rpartition(",")
    abbr = US_STATE_NAME_TO_ABBR.get(suffix.strip().lower())
    if not abbr:
        return jurisdiction
    return f"{prefix.strip()}, {abbr}"
