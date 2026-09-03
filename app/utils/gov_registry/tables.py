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
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Tuple

from ..jurisdiction_enrich import (
    _QUERY_GOVERNMENT_TYPE_RE,
    _contract_saints,
    _expand_abbreviations,
    _normalize_candidates,
    _normalize_name,
    _normalize_slash_spacing,
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
    # Census FUNCSTAT, places only: "A" active, "B"/"F" a consolidated
    # city-county government, "N" the one kept nonfunctioning row (DC).
    # Carried because the county->place fallback for a consolidated
    # government must be restricted to B/F rather than searching the
    # whole place table (resolver._consolidated_lookup()).
    funcstat: str = ""


def lookup_keys(name: str) -> List[str]:
    """Every normalized key a query name could reasonably match, in the
    order `_table_lookup()` already tries them: as-is, trailing-type-word
    stripped, abbreviation-expanded, Saint-contracted, ʻokina-stripped.
    Duplicates removed, order preserved.
    """
    keys: List[str] = []
    # The last two variants are the enricher's own consolidated-government
    # handling, reused rather than re-derived: `_QUERY_GOVERNMENT_TYPE_RE`
    # strips a trailing "metropolitan government"/"metro"/"unified"
    # (earned 2026-08-17 by the real archived "Louisville / Jefferson
    # County Metro"), and `_normalize_slash_spacing` collapses the spaced
    # slash that same row uses. Both are what let a page's informal
    # spelling reach the Census "(balance)" key.
    consolidated = _normalize_slash_spacing(
        _QUERY_GOVERNMENT_TYPE_RE.sub("", name).strip()
    )
    for variant in (
        name,
        _expand_abbreviations(name),
        _contract_saints(name),
        _strip_okina(name),
        consolidated,
        _normalize_slash_spacing(name),
    ):
        for candidate in _normalize_candidates(variant):
            if candidate and candidate not in keys:
                keys.append(candidate)
    return keys


_SQUASH_RE = re.compile(r"[^a-z0-9]+")


def squash(name: str) -> str:
    """ "Gales Burg" -> "galesburg"; "The City of Milwaukee, WI" ->
    "thecityofmilwaukeewi".

    Every space and punctuation mark removed. Used for two different
    comparisons, both of which need the same rule: `lookup_squashed()`
    below, and the resolver's tenant-consistency name guard (rung 5b),
    which architecture-doc terms compare "with spaces and punctuation
    stripped".
    """
    return _SQUASH_RE.sub("", (name or "").lower())


# Canadian CSD type code -> the municipal type word an English page
# writes for it, for the same tie-break the US place table already gets
# from LSAD. Only the codes whose meaning is unambiguous in English are
# mapped; every other code (P parish, MÉ municipalité, IRI reserve, ...)
# is left out rather than guessed at, so an unmapped row simply never
# wins a tie and the lookup declines as it did before.
#
# The case this exists for: "Town of Yarmouth, NS" has two CSDs under one
# name -- 1202006 (T, the town) and 1202004 (MD, the municipal district
# surrounding it) -- so the exactly-one rule declined and the census
# division "Yarmouth" caught the fall, filing a town as a county.
CSD_TYPE_WORDS = {
    "CY": "city",
    "C": "city",
    "T": "town",
    "TV": "town",
    "VL": "village",
    "TP": "township",
    "MU": "municipality",
    "MD": "municipality",
    "RM": "municipality",
    "DM": "municipality",
    "IM": "municipality",
    "RGM": "municipality",
    "MRM": "municipality",
}


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
        # The same index with every space and hyphen removed -- see
        # `lookup_squashed()` for what it is for and why it is separate.
        self._by_squashed: Dict[str, Dict[str, List[TableRow]]] = defaultdict(
            lambda: defaultdict(list)
        )
        self._by_id: Dict[str, TableRow] = {}
        for row in rows:
            key = _normalize_name(row.name)
            self._by_key[key][row.state.upper()].append(row)
            self._by_squashed[squash(key)][row.state.upper()].append(row)
            self._by_id[row.row_id] = row

    def get(self, row_id: str) -> Optional[TableRow]:
        return self._by_id.get(row_id)

    def rows(self) -> List[TableRow]:
        """Every row, for a caller that needs to build its own index over
        the table rather than look a name up in it -- e.g. the
        school-district acronym index in `scripts/build_pin_worklist.py`,
        which reads a hostname like `pgcps` as a set of initials."""
        return list(self._by_id.values())

    def lookup_all(self, name: str, state: Optional[str]) -> List[TableRow]:
        """Every row matching `name`, at the first normalization key that
        matches anything -- so a caller can break a tie the exactly-one
        rule would otherwise decline (the raw name's own type word, see
        `resolver._general_purpose_lookup()`)."""
        for key in lookup_keys(name):
            by_state = self._by_key.get(key)
            if not by_state:
                continue
            if state:
                rows = by_state.get(state.upper()) or []
            else:
                rows = [r for state_rows in by_state.values() for r in state_rows]
            if rows:
                return list({r.row_id: r for r in rows}.values())
        return []

    def lookup(self, name: str, state: Optional[str]) -> Optional[TableRow]:
        """The one row matching `name`, or None.

        With a state, the match must be unique *within that state*.
        Without one, it must be unique nationally -- the same
        "only resolve a bare name when it's unambiguous" posture
        `lookup_city_state()` takes, so a page that never said which
        state it is in can't be assigned to the wrong Springfield.
        """
        for key in lookup_keys(name):
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

    def lookup_squashed(self, name: str, state: Optional[str]) -> Optional[TableRow]:
        """The one row whose name matches `name` once every space and
        hyphen is removed from both sides -- or None.

        A LAST resort, tried only when minting is otherwise the outcome
        (resolver rung 5c), and deliberately requiring a state: this is a
        looser key than `lookup()`'s, so running it nationally, or ahead
        of the real lookup, would let two genuinely different governments
        collide on a squashed spelling.

        The real case, from the 2026-09-02 archive: `galesburg.granicus.com`
        stores "Gales Burg" on one page and "Galesburg, IL" on the next.
        The first matched no key and minted `rtr:us:il:gales-burg`, so one
        government held two ids. Its own tenant is what supplies the IL,
        and "galesburg" == "galesburg" is what makes the match safe rather
        than a guess.
        """
        if not state:
            return None
        for key in lookup_keys(name):
            by_state = self._by_squashed.get(squash(key))
            if not by_state:
                continue
            unique = {r.row_id: r for r in (by_state.get(state.upper()) or [])}
            if len(unique) == 1:
                return next(iter(unique.values()))
            if unique:
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
            TableRow(
                r["geoid"],
                r["name"],
                r["state"],
                _LSAD_WORDS.get(r["lsad"], ""),
                r["funcstat"],
            )
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
def state_gov_ids() -> Dict[str, str]:
    """ "CA" -> "us:state:06", "ON" -> "ca:pr:35".

    Decision D1 makes the State of California ONE government whose Senate,
    Assembly and departments are `meeting_body` rows under it -- so its
    display name is "State of California", with no ", CA" suffix. Every
    `/state/*` query keys on that suffix, which means a state government
    is invisible on its own state's page unless something maps the two.
    Found in a browser check of the rebuilt /state/california: the new
    "State government" heading could never have a row in it.
    """
    out = {
        row.state.upper(): f"us:state:{row.row_id}"
        for row in us_states()._by_id.values()
    }
    out.update(
        {row.state.upper(): f"ca:pr:{row.row_id}" for row in ca_pr()._by_id.values()}
    )
    return out


def state_gov_id(abbr: Optional[str]) -> Optional[str]:
    return state_gov_ids().get((abbr or "").upper())


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


# `cog_units.csv` is deliberately NOT loaded as a lookup table. Decision
# D3 keeps the Census of Governments file as enrichment only this phase --
# there is no `us:cog:` namespace to resolve into. It IS read, lazily and
# once, for its vocabulary (below).


@lru_cache(maxsize=1)
def name_vocabulary() -> frozenset:
    """Every 4+-letter word that appears in a real government's name.

    Built from the national tables plus `cog_units.csv` -- 90,837 real US
    government names from the 2022 Census of Governments. That file is the
    right source for this and nothing else is: the place tables alone know
    "Wichita" and "Tampa" but not "authority", "commission", "irrigation"
    or "wastewater", so a vocabulary built from them would reject most
    real agency names. With COG the two halves cover each other -- 20,676
    words, and measured against the words at issue it accepts every real
    government term tried (authority, commission, conservation, sewerage,
    aquifer, ambulance, irrigation, sandag) while rejecting every piece of
    subdomain junk tried (llbc, notl, stjohns, ride).

    This is a *vocabulary*, not a dictionary: it says "this word occurs in
    the name of some real government", which is exactly the question
    `resolver._looks_like_a_name()` needs answered and a general English
    dictionary would answer worse (it would accept "ride" and reject
    "sandag"). Lazy and cached: only a minting attempt ever pays for it.
    """
    words = set(_STATE_BODY_WORDS)
    tables = (
        us_places(),
        us_counties(),
        us_cousubs(),
        us_school_districts(),
        us_states(),
        ca_csd(),
        ca_cd(),
        ca_pr(),
    )
    for table in tables:
        for row in table._by_id.values():
            words.update(w.lower() for w in _WORD_RE.findall(row.name))
    for row in _read("cog_units.csv"):
        words.update(w.lower() for w in _WORD_RE.findall(row.get("name") or ""))
    return frozenset(words)


_WORD_RE = re.compile(r"[A-Za-z']{4,}")

# State-level bodies are one government per state (D1) and their own
# words never appear in a place or Census-of-Governments name, so they
# are added by hand -- a short, closed list, not a category.
_STATE_BODY_WORDS = frozenset(
    {
        "senate",
        "assembly",
        "legislature",
        "delegates",
        "representatives",
        "commonwealth",
    }
)


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
    return any(counts.get((state.upper(), key), 0) > 1 for key in lookup_keys(name))
