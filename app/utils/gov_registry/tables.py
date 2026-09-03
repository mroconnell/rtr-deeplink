"""The national reference tables behind `gov_id` -- loaded once at import
and queried name+state -> exactly one id, or nothing.

Built by `scripts/build_gov_registry_data.py`. Every table here is
*additive*: `app/utils/jurisdiction_enrich.py`'s own `places.csv` /
`counties.csv` / `county_subdivisions.csv` are untouched and still the
only thing it reads. These carry the ids and the LSAD it never needed.

Name normalization is deliberately borrowed from `jurisdiction_enrich`
rather than rewritten (`_normalize_name`, `_normalize_candidates`,
`_contract_saints`, `_strip_okina`, `_expand_abbreviations`). Those
functions encode real, measured decisions -- the "(balance)" consolidated
governments, the Saint/St. direction, the "Oklahoma City" trailing-word
trap, the ʻokina tier -- each earned by a live bug. A second, subtly
different normalizer would silently disagree with the enricher about
which names are the same government, which is the exact class of bug
this whole registry exists to end. They are private names in that module;
importing them across two modules of the same package is the narrower
evil, and the alternative (making them public) would be a change to a
module this phase is explicitly not changing.
"""

import csv
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

from ..jurisdiction_enrich import (
    _contract_saints,
    _expand_abbreviations,
    _normalize_candidates,
    _normalize_name,
    _strip_okina,
)

DATA_DIR = Path(__file__).parent.parent / "jurisdiction_data"

# Canadian province/territory codes, so a state suffix can say which
# country a row belongs to without a separate column. Same 13 the rest of
# the estate uses (archive/utils/jurisdiction_format.py's
# CA_PROVINCE_NAME_TO_ABBR values); duplicated because this package must
# import nothing from `archive/`.
CA_PROVINCES = frozenset(
    {"AB", "BC", "MB", "NB", "NL", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT"}
)


def country_for_state(state: Optional[str]) -> str:
    """ "ON" -> "ca", anything else (including None) -> "us".

    The `CA` collision architecture doc §1.6 names -- California in a
    state column, Canada in a country column -- can't arise here: the
    namespace prefix carries the country and this function is the only
    thing that decides it.
    """
    return "ca" if state and state.upper() in CA_PROVINCES else "us"


class TableRow(NamedTuple):
    """One national-table row: its id, the name as the table spells it,
    the state/province, and a type word (LSAD word, CSD type, school
    level) where the table has one."""

    row_id: str
    name: str
    state: str
    type_word: str = ""


def _lookup_keys(name: str) -> List[str]:
    """Every normalized key a query name could reasonably match, in the
    order `_table_lookup()` already tries them: as-is, trailing-type-word
    stripped, abbreviation-expanded, Saint-contracted, ʻokina-stripped.
    Duplicates removed, order preserved.
    """
    keys: List[str] = []
    for variant in (
        name,
        _expand_abbreviations(name),
        _contract_saints(name),
        _strip_okina(name),
    ):
        for candidate in _normalize_candidates(variant):
            if candidate and candidate not in keys:
                keys.append(candidate)
    return keys


class NameStateTable:
    """normalized name -> state -> rows, with an exactly-one-match rule.

    "Exactly one or nothing" is the feed's own rule (`govtype.py`'s
    `nces_district_id`) and the enricher's (`lookup_city_state()` only
    resolves a bare name when it is unique). Reused rather than reinvented
    because the failure it prevents is the one that matters most here:
    quietly picking a plausible wrong government is worse than minting an
    honest `rtr:` id.
    """

    def __init__(self, rows: List[TableRow]):
        self._by_key: Dict[str, Dict[str, List[TableRow]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._by_id: Dict[str, TableRow] = {}
        for row in rows:
            self._by_key[_normalize_name(row.name)][row.state.upper()].append(row)
            self._by_id[row.row_id] = row

    def get(self, row_id: str) -> Optional[TableRow]:
        return self._by_id.get(row_id)

    def lookup(self, name: str, state: Optional[str]) -> Optional[TableRow]:
        """The one row matching `name`, or None.

        With a state, the match must be unique *within that state*.
        Without one, it must be unique nationally -- the same
        "only resolve a bare name when it's unambiguous" posture
        `lookup_city_state()` takes, so a page that never said which
        state it is in can't be assigned to the wrong Springfield.
        """
        for key in _lookup_keys(name):
            by_state = self._by_key.get(key)
            if not by_state:
                continue
            if state:
                rows = by_state.get(state.upper()) or []
            else:
                rows = [r for state_rows in by_state.values() for r in state_rows]
            unique = {r.row_id: r for r in rows}
            if len(unique) == 1:
                return next(iter(unique.values()))
            if unique:
                # Ambiguous at this key. Later keys are looser
                # normalizations of the same name, so they can only be
                # more ambiguous, not less -- stop rather than letting a
                # looser key produce a lucky single hit.
                return None
        return None

    def names_in_state(self, state: str) -> Dict[str, int]:
        counts: Dict[str, int] = defaultdict(int)
        for key, by_state in self._by_key.items():
            counts[key] += len({r.row_id for r in by_state.get(state.upper(), [])})
        return counts

    def __len__(self) -> int:
        return len(self._by_id)


def _read(filename: str) -> List[dict]:
    path = DATA_DIR / filename
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# LSAD code -> the word the display rule puts in parentheses when two
# governments in one state share a name ("Cottage Grove (village), WI").
# Only the four codes that actually occur on incorporated places in the
# 2024 Gazetteer are mapped (25 city / 43 town / 47 village / 21 borough,
# 19,442 of 19,475 rows); the handful of consolidated-government codes
# left over are given no word rather than a guessed one, and simply fall
# back to the undisambiguated display.
_LSAD_WORDS = {"25": "city", "43": "town", "47": "village", "21": "borough"}


@lru_cache(maxsize=1)
def us_places() -> NameStateTable:
    return NameStateTable(
        [
            TableRow(r["geoid"], r["name"], r["state"], _LSAD_WORDS.get(r["lsad"], ""))
            for r in _read("us_places.csv")
        ]
    )


@lru_cache(maxsize=1)
def us_counties() -> NameStateTable:
    return NameStateTable(
        [TableRow(r["fips"], r["name"], r["state"]) for r in _read("us_counties.csv")]
    )


@lru_cache(maxsize=1)
def us_cousubs() -> NameStateTable:
    return NameStateTable(
        [TableRow(r["geoid"], r["name"], r["state"]) for r in _read("us_cousubs.csv")]
    )


@lru_cache(maxsize=1)
def us_states() -> NameStateTable:
    return NameStateTable(
        [TableRow(r["fips"], r["name"], r["state"]) for r in _read("us_states.csv")]
    )


@lru_cache(maxsize=1)
def us_school_districts() -> NameStateTable:
    return NameStateTable(
        [
            TableRow(r["geoid"], r["name"], r["state"], r["level"])
            for r in _read("us_school_districts.csv")
        ]
    )


@lru_cache(maxsize=1)
def ca_csd() -> NameStateTable:
    return NameStateTable(
        [
            TableRow(r["sgc_code"], r["name"], r["province"], r["csd_type"])
            for r in _read("ca_csd.csv")
        ]
    )


@lru_cache(maxsize=1)
def ca_cd() -> NameStateTable:
    return NameStateTable(
        [TableRow(r["sgc_code"], r["name"], r["province"]) for r in _read("ca_cd.csv")]
    )


@lru_cache(maxsize=1)
def ca_pr() -> NameStateTable:
    return NameStateTable(
        [TableRow(r["sgc_code"], r["name"], r["province"]) for r in _read("ca_pr.csv")]
    )


# `cog_units.csv` is deliberately NOT loaded here. Decision D3 keeps the
# Census of Governments file as enrichment only this phase -- there is no
# `us:cog:` namespace to resolve into -- and it is 90,837 rows, which is
# not something to pay for at import time for a column nothing reads yet.
# `scripts/` can read the file directly when a later phase wants it.


@lru_cache(maxsize=1)
def _ambiguous_display_names() -> Dict[Tuple[str, str], int]:
    """(state, normalized name) -> how many distinct general-purpose
    governments share it, counting places AND county subdivisions
    together.

    Both tables, because the real collision the display rule was written
    for spans them: Cottage Grove, WI is a *village* (a Census place) and
    a *town* (a county subdivision) -- two real, distinct governments,
    architecture doc §1.5. Counting places alone would find no collision
    and display both as plain "Cottage Grove, WI".
    """
    counts: Dict[Tuple[str, str], int] = defaultdict(int)
    for table in (us_places(), us_cousubs()):
        for key, by_state in table._by_key.items():
            for state, rows in by_state.items():
                counts[(state, key)] += len({r.row_id for r in rows})
    return counts


def name_is_ambiguous_in_state(name: str, state: Optional[str]) -> bool:
    if not state:
        return False
    counts = _ambiguous_display_names()
    return any(counts.get((state.upper(), key), 0) > 1 for key in _lookup_keys(name))
