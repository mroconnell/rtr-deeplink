"""The three committed, hand-editable registry files: `governments.csv`,
`tenant_overrides.csv`, `gov_relations.csv` (architecture doc §4).

They live in `app/utils/jurisdiction_data/` beside the national tables
because that is decision D5's answer to "where does the registry live" --
here, imported by rtr-discovery and rtr-upcoming through their existing
seams, rather than as a fourth package nobody maintains.

`governments.csv` is generated for national-table rows and reviewed for
`rtr:` ones; `tenant_overrides.csv` is Ryan's "hard-code a public name"
tier and is hand-edited; `gov_relations.csv` is hierarchy kept *beside*
the identity, never inside it (D2).
"""

import csv
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional, Tuple

DATA_DIR = Path(__file__).parent.parent / "jurisdiction_data"

GOVERNMENTS_FILE = "governments.csv"
TENANT_OVERRIDES_FILE = "tenant_overrides.csv"
RELATIONS_FILE = "gov_relations.csv"

GOVERNMENTS_HEADER = [
    "gov_id",
    "gov_name",
    "gov_type",
    "country",
    "state",
    "place_geoid",
    "county_fips",
    "sgc_code",
    "nces_lea_id",
    "cog_id",
    "aliases",
    "source",
    "evidence",
]
TENANT_OVERRIDES_HEADER = [
    "tenant_host",
    "match",
    "gov_id",
    "strength",
    "source",
    "evidence",
]
RELATIONS_HEADER = ["from_gov_id", "relation", "to_gov_id", "evidence"]

# The only relations D2 allows. Deliberately few, and deliberately not a
# general "related to": a JPA's members and a fire district's served
# cities are different claims, and one column that meant either would
# become the dumping ground D2 declines.
RELATIONS = ("part_of", "serves", "overseen_by")


@dataclass(frozen=True)
class Government:
    gov_id: str
    gov_name: str
    gov_type: str
    country: str = "us"
    state: str = ""
    place_geoid: str = ""
    county_fips: str = ""
    sgc_code: str = ""
    nces_lea_id: str = ""
    cog_id: str = ""
    aliases: Tuple[str, ...] = field(default_factory=tuple)
    source: str = ""
    evidence: str = ""

    def as_row(self) -> List[str]:
        return [
            self.gov_id,
            self.gov_name,
            self.gov_type,
            self.country,
            self.state,
            self.place_geoid,
            self.county_fips,
            self.sgc_code,
            self.nces_lea_id,
            self.cog_id,
            "|".join(self.aliases),
            self.source,
            self.evidence,
        ]


@dataclass(frozen=True)
class TenantOverride:
    tenant_host: str
    gov_id: str
    # None for a single-government tenant; a path prefix, a query
    # parameter (`view_id=5`) or a channel id for a tenant that serves
    # more than one government (the Cottage Grove and youtube.com cases,
    # architecture doc §1.5).
    match: Optional[str] = None
    # "authoritative" wins outright, even over a successful-looking
    # extraction (the SLC/Holladay lesson: a plausible wrong extraction
    # passes validation, so validation alone can never fix a
    # confirmed-misleading host). "fallback" is used only when the ladder
    # produced nothing. Same two tiers `KnownJurisdiction.strength`
    # already has, deliberately.
    strength: str = "fallback"
    source: str = ""
    evidence: str = ""


def _read(filename: str) -> List[dict]:
    path = DATA_DIR / filename
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@lru_cache(maxsize=1)
def governments() -> Dict[str, Government]:
    out: Dict[str, Government] = {}
    for r in _read(GOVERNMENTS_FILE):
        gov_id = (r.get("gov_id") or "").strip()
        if not gov_id:
            continue
        aliases = tuple(
            a.strip() for a in (r.get("aliases") or "").split("|") if a.strip()
        )
        out[gov_id] = Government(
            gov_id=gov_id,
            gov_name=(r.get("gov_name") or "").strip(),
            gov_type=(r.get("gov_type") or "").strip(),
            country=(r.get("country") or "us").strip(),
            state=(r.get("state") or "").strip(),
            place_geoid=(r.get("place_geoid") or "").strip(),
            county_fips=(r.get("county_fips") or "").strip(),
            sgc_code=(r.get("sgc_code") or "").strip(),
            nces_lea_id=(r.get("nces_lea_id") or "").strip(),
            cog_id=(r.get("cog_id") or "").strip(),
            aliases=aliases,
            source=(r.get("source") or "").strip(),
            evidence=(r.get("evidence") or "").strip(),
        )
    return out


@lru_cache(maxsize=1)
def tenant_overrides() -> Dict[str, List[TenantOverride]]:
    """host -> its override rows, most specific first.

    A host can carry several rows: one per `match` discriminator plus at
    most one catch-all. Sorted so a `match` row is always considered
    before the catch-all, which is what lets `wi-cottagegrove.civicplus.com`
    serve both the Town and the Village of Cottage Grove.
    """
    out: Dict[str, List[TenantOverride]] = {}
    for r in _read(TENANT_OVERRIDES_FILE):
        host = (r.get("tenant_host") or "").strip().lower()
        gov_id = (r.get("gov_id") or "").strip()
        if not host or not gov_id:
            continue
        out.setdefault(host, []).append(
            TenantOverride(
                tenant_host=host,
                gov_id=gov_id,
                match=(r.get("match") or "").strip() or None,
                strength=(r.get("strength") or "fallback").strip(),
                source=(r.get("source") or "").strip(),
                evidence=(r.get("evidence") or "").strip(),
            )
        )
    for rows in out.values():
        rows.sort(key=lambda o: (o.match is None, o.match or ""))
    return out


@lru_cache(maxsize=1)
def relations() -> List[Tuple[str, str, str, str]]:
    return [
        (
            (r.get("from_gov_id") or "").strip(),
            (r.get("relation") or "").strip(),
            (r.get("to_gov_id") or "").strip(),
            (r.get("evidence") or "").strip(),
        )
        for r in _read(RELATIONS_FILE)
        if (r.get("from_gov_id") or "").strip()
    ]


def write_governments(rows: List[Government], path: Optional[Path] = None) -> None:
    """Rewrite `governments.csv`, sorted by gov_id. Used by the seed
    scripts; the app only ever reads."""
    target = path or (DATA_DIR / GOVERNMENTS_FILE)
    with open(target, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(GOVERNMENTS_HEADER)
        for gov in sorted(rows, key=lambda g: g.gov_id):
            writer.writerow(gov.as_row())


def clear_caches() -> None:
    """Drop the memoized files -- for a seed script that writes them and
    then wants to resolve against what it just wrote, and for tests."""
    governments.cache_clear()
    tenant_overrides.cache_clear()
    relations.cache_clear()
