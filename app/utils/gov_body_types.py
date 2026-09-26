"""Shared government-TYPE agreement machinery (WO-1076, generalized
WO-1078). Two different things call this: `scripts/hub_harvest.py`'s
`_enforce_type_agreement()` (a HUB SECTION's own title/heading, e.g. "Town
Council" as a listing category) and Meeting Finder's
`app/platforms/meeting_finder/pick.py` (a CANDIDATE VIDEO's own title,
e.g. "Common Council - 6/9/2026"). Both need the same real fact: a
government-TYPE word or governing-BODY phrase implies which of the
registry's own `Government.gov_type` values (`app.utils.gov_registry.
classify`) the government behind it can actually be. That fact belongs in
one place -- this module -- not two copies that can drift.

`app/` code must never import from `scripts/` (CLAUDE.md, and
`app/utils/video_hand_check.py`'s own docstring says so explicitly), so
this lives in `app/` and `scripts/hub_harvest.py` imports it, not the
other way around. `EXPECTED_GOV_TYPES_BY_BODY_TYPE` and
`normalize_body_type_word()` below are moved here verbatim from
`hub_harvest.py` (WO-1076); that script now imports them from here
instead of keeping its own copy -- same values, same behavior, no
duplication.

The `PLACE_TYPE_WORD_ALIASES` -> `EXPECTED_GOV_TYPES_BY_BODY_TYPE` table
above is tuned for a HUB SECTION heading or `pick.py`'s own extracted
place-TYPE word (a single word: "county", "town", "borough"...).
`VIDEO_TITLE_BODY_PHRASES` below is a second, separate table (WO-1078),
tuned for a full CANDIDATE VIDEO title, where a real governing-body name
("Board of Selectmen", "Common Council", "State Board of Education") is
the signal, not a bare place-type word -- a video title routinely has no
place-type word in it at all ("Common Council - 6/9/2026" names no place,
just a body). Kept separate on purpose: the two data shapes have
different false-positive risk (a hub section's own "Board of Trustees"
heading is common enough on a real single-township/village hub that
WO-1076 keeps it permissive there; the same phrase in a video TITLE with
no other context is exactly the kind of ambiguous case WO-1078's own brief
says must never trigger a reject) -- forcing one shared phrase list would
have meant either loosening hub_harvest's hub-section matching or
tightening it wrongly for this new, narrower purpose. Both tables share
the same underlying `classify.*` vocabulary and the same "only ever
narrows, never guesses" posture.
"""

from __future__ import annotations

import re
from typing import Dict, FrozenSet, Optional, Tuple

from app.utils.gov_registry import classify

# ---------------------------------------------------------------------
# Moved verbatim from `scripts/hub_harvest.py` (WO-1076). See that
# module's own history for the real regressions each entry fixes
# (Horseheads NY, Springfield MI, Grant MN, Lucas OH, Hilton Head Island
# SC) -- unchanged here, just relocated so `app/` code can use it too.
# ---------------------------------------------------------------------
EXPECTED_GOV_TYPES_BY_BODY_TYPE: Dict[str, FrozenSet[str]] = {
    "county": frozenset({classify.COUNTY}),
    "school district": frozenset({classify.SCHOOL_DISTRICT}),
    "township": frozenset({classify.TOWNSHIP}),
    "town": frozenset({classify.TOWNSHIP}),
    "township-or-village": frozenset({classify.TOWNSHIP, classify.MUNICIPALITY}),
    "village": frozenset({classify.MUNICIPALITY}),
    "city": frozenset({classify.MUNICIPALITY}),
    "borough": frozenset({classify.MUNICIPALITY}),
}

PLACE_TYPE_WORD_ALIASES: Dict[str, str] = {
    "parish": "county",  # Louisiana's county-equivalent.
    "isd": "school district",
    "usd": "school district",
}


def normalize_body_type_word(word: str) -> str:
    """A raw type word (from `pick.py`'s `place_type` or `hub_harvest.py`'s
    own `_guessed_body_type()`) reduced to one of
    `EXPECTED_GOV_TYPES_BY_BODY_TYPE`'s own keys, or "" when `word` carries
    no real type-agreement constraint (e.g. "same-as-named-place", or a
    word this function doesn't recognize)."""
    normalized = (word or "").strip().lower()
    normalized = PLACE_TYPE_WORD_ALIASES.get(normalized, normalized)
    if normalized in EXPECTED_GOV_TYPES_BY_BODY_TYPE:
        return normalized
    return ""


# =======================================================================
# WO-1078: a CANDIDATE VIDEO TITLE's own body-name -> expected gov_type(s).
# =======================================================================
#
# Real, measured problem (2026-09-26 hand-check, 44 rows in
# `other_gov_rows.csv`): a no-platform-signature Meeting Finder run found
# 58 videos, 23 of a DIFFERENT government -- almost always a school
# district whose site links a shared town/county TV account, so the
# finder returned e.g. "Glastonbury Town Council" (a real
# `us:sd:0901620` search that found the TOWN's council) or "Common
# Council" (Cumberland, WI's school district finding the CITY's council).
# The meeting TITLE names the body, and the body's own name implies a
# government TYPE (`classify.*`) -- a school district search finding a
# "Town Council"/"Board of Selectmen"/"County Commissioners" video is
# never that district's own meeting, however cleanly everything else
# about the candidate resolves.
#
# Deliberately conservative (Ryan's brief, 2026-09-26): an ambiguous body
# name -- "Planning Commission", "Zoning Board of Appeals", "Finance
# Committee", a bare "Board of Trustees" with no further context, a
# generic "Regular Meeting" -- is NEVER in this table. Every phrase below
# was chosen because it names a body that, in practice, only exists at
# ONE kind of government (confirmed against real titles in
# `other_gov_rows.csv`/`all_verdicts.csv`, not invented) -- a miss here
# (a real mismatch this table doesn't catch) costs nothing new, since
# `pick.filter_candidates_to_government()`'s existing place-NAME check and
# a human review are still the backstop; a false trigger would wrongly
# throw away a real find, which is why the table stays narrow.
#
# "shac" (School Health Advisory Council, a standing committee every
# Texasschool district is required to have) looked, before checking real
# data, like a state-level body -- it is not. Ten real `approve`d rows in
# `all_verdicts.csv` (pisd.net, romaisd.com, pgisd.net, paisd.org,
# borgerisd.net, caddomillsisd.org, nechesisd.com, taylorisd.org,
# bellevueisd.org, bradyisd.org) are each an ISD's OWN "SHAC Meeting"
# recording -- exactly the "verify against real data before building"
# rule (CLAUDE.md) this table's own construction leaned on.
#
# Each entry: (phrase, expected gov_types, plain-language owner hint for
# the recorded lead). Order matters only in that a longer, more specific
# phrase is listed before a shorter one it could otherwise be confused
# with (e.g. "state board of education" before a bare "board of
# education"); none of these phrases are literal substrings of each
# other, so match order does not change which one fires.
_MUNICIPAL_TYPES: FrozenSet[str] = frozenset({classify.MUNICIPALITY})
_COUNTY_TYPES: FrozenSet[str] = frozenset({classify.COUNTY})
_TOWN_TYPES: FrozenSet[str] = frozenset({classify.TOWNSHIP, classify.MUNICIPALITY})
_SCHOOL_TYPES: FrozenSet[str] = frozenset({classify.SCHOOL_DISTRICT})
_STATE_TYPES: FrozenSet[str] = frozenset({classify.STATE})
_SPECIAL_TYPES: FrozenSet[str] = frozenset({classify.SPECIAL_DISTRICT})
# "Planning Board" (unlike the ambiguous "Planning Commission") is, in
# every real example seen, a municipal/county/town body -- never a school
# district's. Modeled as "everything except a school district" rather
# than one specific type, since it genuinely could be any of the other
# kinds.
_NOT_SCHOOL_DISTRICT_TYPES: FrozenSet[str] = frozenset(
    {
        classify.COUNTY,
        classify.MUNICIPALITY,
        classify.TOWNSHIP,
        classify.STATE,
        classify.SPECIAL_DISTRICT,
    }
)

VIDEO_TITLE_BODY_PHRASES: Tuple[Tuple[str, FrozenSet[str], str], ...] = (
    # State-level bodies.
    ("state board of education", _STATE_TYPES, "a state board of education"),
    ("board of state canvassers", _STATE_TYPES, "a state canvassing board"),
    (
        "charter school commission",
        _STATE_TYPES,
        "a state charter school commission",
    ),
    (
        "teacher retirement system",
        _STATE_TYPES,
        "a state teacher retirement system",
    ),
    # County bodies.
    (
        "board of county commissioners",
        _COUNTY_TYPES,
        "the county government's own commissioners",
    ),
    (
        "county commissioners",
        _COUNTY_TYPES,
        "the county government's own commissioners",
    ),
    (
        "commissioners court",
        _COUNTY_TYPES,
        "the county government (a Texas-style commissioners court)",
    ),
    ("county council", _COUNTY_TYPES, "the county government's own council"),
    ("county board", _COUNTY_TYPES, "the county government's own board"),
    # Town/township bodies (New England- and NY/WI-style "town" can be
    # either a Census township or an incorporated municipality -- see
    # `_TOWN_TYPES` above and `hub_harvest.py`'s own "town" note).
    ("board of selectmen", _TOWN_TYPES, "the town's own board of selectmen"),
    ("select board", _TOWN_TYPES, "the town's own select board"),
    ("selectboard", _TOWN_TYPES, "the town's own select board"),
    ("town council", _TOWN_TYPES, "the town/city's own council"),
    ("town board", _TOWN_TYPES, "the town's own board"),
    # City/village bodies.
    ("common council", _MUNICIPAL_TYPES, "the city's own common council"),
    ("city council", _MUNICIPAL_TYPES, "the city's own council"),
    ("city commission", _MUNICIPAL_TYPES, "the city's own commission"),
    ("village board", _MUNICIPAL_TYPES, "the village's own board"),
    # Non-school municipal/county body, type otherwise unspecified.
    (
        "planning board",
        _NOT_SCHOOL_DISTRICT_TYPES,
        "a municipal/county planning board, not a school district body",
    ),
    # School district's own bodies.
    ("school board", _SCHOOL_TYPES, "the school district's own board"),
    ("board of education", _SCHOOL_TYPES, "the school district's own board"),
    ("school committee", _SCHOOL_TYPES, "the school district's own committee"),
    ("county schools", _SCHOOL_TYPES, "the county's own school district"),
    (
        "shac",
        _SCHOOL_TYPES,
        "the school district's own School Health Advisory Council",
    ),
    # Special districts.
    ("housing authority", _SPECIAL_TYPES, "a housing authority (special district)"),
    (
        "redevelopment authority",
        _SPECIAL_TYPES,
        "a redevelopment authority (special district)",
    ),
)


def match_body_type_phrase(
    title: Optional[str],
) -> Optional[Tuple[str, FrozenSet[str], str]]:
    """The first `VIDEO_TITLE_BODY_PHRASES` entry whose phrase appears in
    `title` as a whole word/phrase (case-insensitive), or `None` when no
    recognized body-name phrase is present at all -- an ordinary,
    ambiguous title ("Regular Meeting", "Planning Commission", a bare
    "Board of Trustees") always returns `None` and is never treated as
    evidence of anything."""
    low = (title or "").lower()
    if not low:
        return None
    for phrase, expected_types, owner_hint in VIDEO_TITLE_BODY_PHRASES:
        if re.search(r"\b" + re.escape(phrase) + r"\b", low):
            return phrase, expected_types, owner_hint
    return None


def body_type_disagreement(
    title: Optional[str], gov_type: Optional[str]
) -> Optional[Tuple[str, FrozenSet[str], str]]:
    """`(phrase, expected_types, owner_hint)` when `title` names a
    governing body whose implied government type CLEARLY disagrees with
    `gov_type` (the government actually being searched) -- `None` when
    `gov_type` is unknown, `title` names no recognized body phrase at
    all, or the phrase's own expected types already include `gov_type`
    (the searched government's own body, however unusual the shared
    hosting account -- e.g. a school district's own "School Committee"
    video on its town's shared Castus channel, real case: lincnet.org,
    2026-09-26)."""
    if not gov_type:
        return None
    match = match_body_type_phrase(title)
    if match is None:
        return None
    phrase, expected_types, owner_hint = match
    if gov_type in expected_types:
        return None
    return phrase, expected_types, owner_hint
