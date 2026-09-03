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
# Hand-written rows, kept in their own file so a regeneration of
# `governments.csv` cannot lose or dilute them, and so a reviewer can see
# the whole curated set without reading 2,800 generated rows. Loaded on
# top of `governments.csv`, and the only source of lookup aliases.
CURATED_GOVERNMENTS_FILE = "curated_governments.csv"
TENANT_OVERRIDES_FILE = "tenant_overrides.csv"
RELATIONS_FILE = "gov_relations.csv"
TENANT_HINTS_FILE = "tenant_hints.csv"

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
TENANT_HINTS_HEADER = ["tenant_host", "state", "source", "evidence"]

# A `source` value starting with this marks a hand-written row. Only such
# a row's `aliases` are trusted for LOOKUP -- see `curated_aliases()`.
CURATED_SOURCE_PREFIX = "curated"

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
    for r in _read(GOVERNMENTS_FILE) + _read(CURATED_GOVERNMENTS_FILE):
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


# A `source` token that means a HUMAN established this pin -- read a
# landing page, checked a dashboard, wrote it into the architecture doc,
# said so directly. Matched as prefixes, so `architecture_doc_1_3` counts.
#
# Everything else is machine-derived: `auto_derived` (rtr-discovery's own
# `tenants.jurisdiction_override`, whose values include "S Fw, MD" and
# "Psr C 2") and `inferred_unique_name`.
HUMAN_PIN_SOURCES = (
    "known_domains",
    "ryan_stated",
    "visual_confirmed",
    "upcoming_roster",
    "landing_page",
    "architecture_doc",
    "manual_override",
    "consolidated_government",
    "curated",
)


def _has_human_source(source: str) -> bool:
    return any(
        tok.strip().startswith(HUMAN_PIN_SOURCES)
        for tok in (source or "").split("+")
        if tok.strip()
    )


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
        if gov_id.startswith("rtr:") and not _has_human_source(r.get("source") or ""):
            # A machine may not MINT a government for a tenant. Pinning
            # to a national id is a claim a table can be checked against;
            # pinning to an `rtr:` id invents an identity, and a pin is
            # the one tier that overrides a working extraction.
            #
            # Real: `king.granicus.com` is the Metropolitan King County
            # Council -- King County, WA. It carried
            # `rtr:us:nc:king-county`, source
            # `auto_derived+inferred_unique_name`, built on the ledger's
            # wrong `state_abbr=NC` for that host. There is no King
            # County in North Carolina. Combining two machine sources
            # does not make one human one, which is why this tests every
            # token rather than the string as a whole.
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
def curated_aliases() -> Dict[Tuple[str, str], str]:
    """(state, alias) -> gov_id, from HAND-WRITTEN `governments.csv` rows
    only (`source` starting "curated").

    The `aliases` column serves two different purposes and only one of
    them is safe to look up by. On a generated row it is a *record* of
    every raw string that happened to resolve there, written by the
    scoring run -- looking those up would cement whatever the resolver
    already did, including its mistakes, and make a wrong resolution
    self-reinforcing. On a curated row it is an *assertion* by a human
    that this name means this government, which is exactly what the
    Census official-name shapes need ("Boise" for "Boise City city",
    "Nashville" for "Nashville-Davidson metropolitan government
    (balance)").

    State is part of the key: "Louisville" means the Kentucky metro
    government only in KY, and there are real Louisvilles in CO and OH.
    A row with no state contributes its aliases under the empty state,
    which only a stateless query can match.
    """
    out: Dict[Tuple[str, str], str] = {}
    for gov in governments().values():
        if not gov.source.startswith(CURATED_SOURCE_PREFIX):
            continue
        for alias in gov.aliases:
            out[(gov.state.upper(), alias.strip().lower())] = gov.gov_id
    return out


@lru_cache(maxsize=1)
def tenant_hints() -> Dict[str, str]:
    """tenant_host -> state abbreviation.

    Deliberately NOT a gov_id. These rows are machine-derived (mostly
    rtr-discovery's `tenants.jurisdiction_override`, whose values include
    "S Fw, MD", "Mw Rd", "Ps C, FL", "Psr C 2", "Ride Uta" and "Tampa
    D" -- subdomain guesses, not government names), so they are trusted
    for the one narrow thing they are reliably right about: which state a
    tenant is in. A hint can stop a government minting an unknown-state
    id; it can never say which government a page belongs to. That is what
    `tenant_overrides.csv` is for, and every row there now has a
    non-auto-derived source behind it.
    """
    out: Dict[str, str] = {}
    for r in _read(TENANT_HINTS_FILE):
        host = (r.get("tenant_host") or "").strip().lower()
        state = (r.get("state") or "").strip().upper()
        if host and state:
            out[host] = state
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


def government_for_id(gov_id: str) -> Optional[Government]:
    """The registry row for `gov_id`, deriving it from the national
    tables when `governments.csv` has not got one yet.

    `governments.csv` is a *generated snapshot* -- it holds the
    governments some scoring run happened to resolve to, not every
    government that exists. Requiring a row there before an id can be
    used would mean a perfectly valid `us:county:56021` could not be
    pinned until someone re-ran the scorer, which is real operational
    friction for no safety gain: for a national id every field is a
    function of the id, so deriving it is exact rather than a guess.

    Returns None for a namespace this package does not issue, and for an
    id whose row the relevant table does not contain -- so garbage is
    still rejected. A minted `rtr:` id has no table behind it by
    definition and is only ever found in the committed file.
    """
    gov_id = (gov_id or "").strip()
    if not gov_id:
        return None
    existing = governments().get(gov_id)
    if existing:
        return existing
    # Imported here rather than at module scope: `tables` reads the
    # registry files through this module, and a top-level import would
    # be a cycle.
    from . import classify, tables

    specs = {
        "us:place": (tables.us_places, classify.MUNICIPALITY, "us", "place_geoid"),
        "us:county": (tables.us_counties, classify.COUNTY, "us", "county_fips"),
        "us:cousub": (tables.us_cousubs, classify.TOWNSHIP, "us", None),
        "us:state": (tables.us_states, classify.STATE, "us", None),
        "us:sd": (tables.us_school_districts, classify.SCHOOL_DISTRICT, "us", None),
        "ca:csd": (tables.ca_csd, classify.MUNICIPALITY, "ca", "sgc_code"),
        "ca:cd": (tables.ca_cd, classify.COUNTY, "ca", "sgc_code"),
        "ca:pr": (tables.ca_pr, classify.STATE, "ca", "sgc_code"),
    }
    namespace, _, row_id = gov_id.rpartition(":")
    spec = specs.get(namespace)
    if not spec or not row_id:
        return None
    table_fn, gov_type, country, code_field = spec
    row = table_fn().get(row_id)
    if row is None:
        return None
    fields = {code_field: row.row_id} if code_field else {}
    if namespace == "us:sd":
        fields["nces_lea_id"] = row.row_id[2:]
    return Government(
        gov_id=gov_id,
        gov_name=row.name,
        gov_type=gov_type,
        country=country,
        state=row.state,
        source=f"{namespace} (derived from the national table)",
        **fields,
    )


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
    curated_aliases.cache_clear()
    tenant_hints.cache_clear()
