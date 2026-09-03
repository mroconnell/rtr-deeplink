"""Seed `tenant_overrides.csv` (+ its conflicts file) and the first cut of
`governments.csv` by merging the four host->government registries that
exist today, none of which reads any of the others.

WO-98, 2026-09-02, architecture doc §4. Read-only against every source;
writes only into `app/utils/jurisdiction_data/`.

Sources, in the precedence the architecture doc sets:

  1. `_KNOWN_DOMAINS` in `app/utils/jurisdiction_enrich.py` (112 rows,
     hand-verified, already carries the `authoritative`/`fallback`
     strength distinction -- kept exactly as it stands today)
  2. `../rtr-discovery/jurisdiction_overrides.csv` (173 rows, its own
     `source` column preserved)
  3. `~/Documents/rtr-business/data-product/feed/upcoming_jurisdictions.csv`
     (109 rows, every one already carrying a geoid; hosts come from its
     pipe-separated `matched_tenants`)
  4. `../rtr-discovery/ledger.db`'s `tenants.jurisdiction_override`
     (565 rows, machine-derived -- `source=auto_derived`,
     `strength=fallback`)

**Where two sources disagree about a host's government, neither is
written.** The pair goes to `tenant_overrides_conflicts.csv` for Ryan.
Precedence above decides which row's *metadata* survives a merge, not
which government a host belongs to -- and a wrong pin is strictly worse
than no pin, because a pin is the one tier that overrides a working
extraction. A host left out here still resolves by name through the
ordinary ladder; a host pinned to the wrong government does not, and
nothing downstream would notice.

Usage:
    python scripts/seed_gov_registry.py [--discovery DIR] [--feed DIR]
"""

import argparse
import csv
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.utils.jurisdiction_enrich import _KNOWN_DOMAINS  # noqa: E402
from app.utils.gov_registry import registry, resolve_government  # noqa: E402

DATA_DIR = (
    Path(__file__).resolve().parent.parent / "app" / "utils" / "jurisdiction_data"
)
DEFAULT_DISCOVERY = Path.home() / "Documents" / "rtr-discovery"
DEFAULT_FEED = Path.home() / "Documents" / "rtr-business" / "data-product" / "feed"

CONFLICTS_FILE = "tenant_overrides_conflicts.csv"


@dataclass
class Candidate:
    host: str
    name: str
    strength: str
    source: str
    evidence: str
    precedence: int


# The nine tenants architecture doc §1.3 measured resolving to the WRONG
# government, with the government each one actually is. Every row was
# verified live on 2026-09-02 against `ledger.db`'s own `resolved_json`,
# so this is hand-verified evidence, not an extraction -- which is what
# `authoritative` means (the SLC/Holladay precedent: a plausible wrong
# extraction passes validation, so validation alone can never fix a
# confirmed-misleading host).
#
# Seeded at precedence 0, ahead of everything. Without it the merge
# faithfully imports each of these mislabels as a pin -- the ledger's
# `jurisdiction_override` for `ladwp.granicus.com` is literally
# "Los Angeles, CA" -- which would make the override table, the one tier
# that beats a working extraction, the most durable carrier of the exact
# bug this registry exists to fix.
_ARCHITECTURE_DOC_CORRECTIONS = {
    "ladwp.granicus.com": "Los Angeles Department of Water and Power, CA",
    "ladwp.primegov.com": "Los Angeles Department of Water and Power, CA",
    "pub-sandag.escribemeetings.com": "San Diego Association of Governments, CA",
    "menlofire.primegov.com": "Menlo Park Fire Protection District, CA",
    "cvwd.primegov.com": "Coachella Valley Water District, CA",
    "tccd.granicus.com": "Tarrant County College District, TX",
    "pub-horrycountyschools.escribemeetings.com": "Horry County Schools, SC",
    "metro.granicus.com": (
        "Los Angeles County Metropolitan Transportation Authority, CA"
    ),
    "pub-hpsb.escribemeetings.com": "Hamilton Police Services Board, ON",
    "pub-trca.escribemeetings.com": "Toronto and Region Conservation Authority, ON",
}


def _architecture_doc_corrections() -> List[Candidate]:
    return [
        Candidate(
            host=host,
            name=name,
            strength="authoritative",
            source="architecture_doc_1_3",
            evidence=(
                "GOVERNMENT_IDENTITY_ARCHITECTURE.md §1.3, verified live "
                "2026-09-02 against ledger.db resolved_json"
            ),
            precedence=0,
        )
        for host, name in _ARCHITECTURE_DOC_CORRECTIONS.items()
    ]


def _known_domains() -> List[Candidate]:
    out = []
    for host, known in _KNOWN_DOMAINS.items():
        out.append(
            Candidate(
                host=host.lower(),
                name=f"{known.name}, {known.state}",
                strength=known.strength,
                source="known_domains",
                evidence="app/utils/jurisdiction_enrich.py _KNOWN_DOMAINS",
                precedence=1,
            )
        )
    return out


def _discovery_overrides(discovery_dir: Path) -> List[Candidate]:
    path = discovery_dir / "jurisdiction_overrides.csv"
    if not path.exists():
        print(f"  (skipped, not found: {path})")
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            host = (r.get("tenant_host") or "").strip().lower()
            name = (r.get("jurisdiction") or "").strip()
            if not host or not name:
                continue
            state = (r.get("state") or "").strip()
            if state and not name.rstrip().endswith(f", {state}"):
                name = f"{name}, {state}"
            out.append(
                Candidate(
                    host=host,
                    name=name,
                    strength="fallback",
                    source=(r.get("source") or "jurisdiction_overrides").strip(),
                    evidence=(r.get("evidence") or "")[:400],
                    precedence=2,
                )
            )
    return out


def _upcoming(feed_dir: Path) -> List[Candidate]:
    path = feed_dir / "upcoming_jurisdictions.csv"
    if not path.exists():
        print(f"  (skipped, not found: {path})")
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            name = (r.get("jurisdiction") or "").strip()
            if not name:
                continue
            # Every row in this file is California -- Ryan, 2026-09-02,
            # recorded in jurisdiction_overrides.csv's own evidence
            # column. The file has no state column of its own, so this is
            # where the suffix comes from.
            if not name.endswith(", CA"):
                name = f"{name}, CA"
            for host in (r.get("matched_tenants") or "").split("|"):
                host = host.strip().lower()
                if not host:
                    continue
                out.append(
                    Candidate(
                        host=host,
                        name=name,
                        strength="fallback",
                        source="upcoming_roster",
                        evidence=(
                            f"upcoming_jurisdictions.csv geoid="
                            f"{(r.get('geoid') or '').strip()} "
                            f"match={(r.get('geo_match_confidence') or '').strip()}"
                        ),
                        precedence=3,
                    )
                )
    return out


def _ledger(discovery_dir: Path) -> List[Candidate]:
    path = discovery_dir / "ledger.db"
    if not path.exists():
        print(f"  (skipped, not found: {path})")
        return []
    out = []
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT netloc, jurisdiction_override FROM tenants "
            "WHERE jurisdiction_override IS NOT NULL AND jurisdiction_override != ''"
        ).fetchall()
    finally:
        conn.close()
    for netloc, name in rows:
        out.append(
            Candidate(
                host=(netloc or "").strip().lower(),
                name=(name or "").strip(),
                strength="fallback",
                source="auto_derived",
                evidence="rtr-discovery ledger.db tenants.jurisdiction_override",
                precedence=4,
            )
        )
    return [c for c in out if c.host and c.name]


def _collapse_stateless_duplicates(entries, aliases):
    """Two minted ids for one host that differ ONLY in the state segment
    -- `rtr:us:xx:albuquerque-bernalillo-county-water-utility-authority`
    against `rtr:us:nm:...` -- are the same government asserted twice,
    once by a source that carried the state and once by one that didn't.
    Not a conflict: keep the stated one.

    Real and common: the ledger's `jurisdiction_override` frequently
    holds a bare name while `jurisdiction_overrides.csv` holds the same
    name with its state. Left uncollapsed, 6 of the first run's 14
    "conflicting" hosts were this, which would have buried the 8 real
    disagreements underneath them.
    """
    by_slug: Dict[str, List] = defaultdict(list)
    for cand, match in entries:
        parts = match.gov_id.split(":")
        key = (
            f"{parts[0]}:{parts[1]}:{parts[3]}"
            if parts[0] == "rtr" and len(parts) == 4
            else match.gov_id
        )
        by_slug[key].append((cand, match))
    out = []
    for group in by_slug.values():
        stated = [
            e for e in group if not e[1].gov_id.startswith(("rtr:us:xx:", "rtr:ca:xx:"))
        ]
        chosen = stated or group
        keep_id = chosen[0][1].gov_id
        for cand, match in group:
            if match.gov_id != keep_id:
                # The dropped id's raw string is still a real alias of the
                # government that survived.
                aliases[keep_id].add(cand.name)
        out.extend(chosen)
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discovery", type=Path, default=DEFAULT_DISCOVERY)
    parser.add_argument("--feed", type=Path, default=DEFAULT_FEED)
    args = parser.parse_args()

    # Resolve against an empty override file so a half-written pin can
    # never feed its own seeding -- the ladder's rungs 2-4 (repair,
    # classify, national table) are what assign these ids.
    (DATA_DIR / registry.TENANT_OVERRIDES_FILE).write_text(
        ",".join(registry.TENANT_OVERRIDES_HEADER) + "\n", encoding="utf-8"
    )
    registry.clear_caches()

    candidates: List[Candidate] = []
    for label, rows in [
        ("architecture doc §1.3 corrections", _architecture_doc_corrections()),
        ("_KNOWN_DOMAINS", _known_domains()),
        ("jurisdiction_overrides.csv", _discovery_overrides(args.discovery)),
        ("upcoming_jurisdictions.csv", _upcoming(args.feed)),
        ("ledger tenants.jurisdiction_override", _ledger(args.discovery)),
    ]:
        print(f"{label}: {len(rows)} rows")
        candidates.extend(rows)

    resolved: Dict[str, List[Tuple[Candidate, object]]] = defaultdict(list)
    governments: Dict[str, object] = {}
    aliases: Dict[str, set] = defaultdict(set)
    for cand in candidates:
        match = resolve_government(cand.name)
        resolved[cand.host].append((cand, match))
        if match.government:
            governments[match.gov_id] = match.government
            aliases[match.gov_id].add(cand.name)

    kept: List[dict] = []
    conflicts: List[dict] = []
    for host, entries in sorted(resolved.items()):
        entries = _collapse_stateless_duplicates(entries, aliases)
        corrected = [e for e in entries if e[0].precedence == 0]
        if corrected:
            # A hand-verified correction is not in a contest with the
            # machine-derived rows it exists to overrule -- it settles the
            # host, and the rows it displaces become aliases.
            for cand, _match in entries:
                aliases[corrected[0][1].gov_id].add(cand.name)
            entries = corrected
        gov_ids = {m.gov_id for _c, m in entries}
        if len(gov_ids) > 1:
            for cand, match in sorted(entries, key=lambda e: e[0].precedence):
                conflicts.append(
                    {
                        "tenant_host": host,
                        "gov_id": match.gov_id,
                        "gov_name": match.gov_name,
                        "raw_name": cand.name,
                        "source": cand.source,
                        "strength": cand.strength,
                        "tier": match.tier,
                        "evidence": cand.evidence,
                    }
                )
            continue
        # One government, possibly asserted by several sources: keep the
        # highest-precedence row's metadata, and the strongest strength
        # anyone claimed (only `_KNOWN_DOMAINS` ever claims
        # `authoritative`, and it is precedence 1, so this is belt and
        # braces rather than a real merge).
        entries.sort(key=lambda e: e[0].precedence)
        best, match = entries[0]
        strength = (
            "authoritative"
            if any(c.strength == "authoritative" for c, _m in entries)
            else "fallback"
        )
        sources = sorted({c.source for c, _m in entries})
        kept.append(
            {
                "tenant_host": host,
                "match": "",
                "gov_id": match.gov_id,
                "strength": strength,
                "source": "+".join(sources),
                "evidence": f"{best.evidence} -> {match.tier}: {match.evidence}",
            }
        )

    with open(
        DATA_DIR / registry.TENANT_OVERRIDES_FILE, "w", newline="", encoding="utf-8"
    ) as fh:
        writer = csv.DictWriter(fh, fieldnames=registry.TENANT_OVERRIDES_HEADER)
        writer.writeheader()
        writer.writerows(sorted(kept, key=lambda r: r["tenant_host"]))
    print(f"\n{registry.TENANT_OVERRIDES_FILE}: {len(kept)} rows")

    conflict_fields = [
        "tenant_host",
        "gov_id",
        "gov_name",
        "raw_name",
        "source",
        "strength",
        "tier",
        "evidence",
    ]
    with open(DATA_DIR / CONFLICTS_FILE, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=conflict_fields)
        writer.writeheader()
        writer.writerows(conflicts)
    hosts_in_conflict = len({c["tenant_host"] for c in conflicts})
    print(f"{CONFLICTS_FILE}: {len(conflicts)} rows over {hosts_in_conflict} hosts")

    merge_governments(governments, aliases)


def merge_governments(governments: Dict[str, object], aliases: Dict[str, set]) -> None:
    """Fold newly-resolved governments into `governments.csv`, keeping any
    row that is already there (it may have been hand-edited -- that is the
    point of the file) and only adding aliases to it."""
    existing = dict(registry.governments())
    out = []
    for gov_id, gov in {**governments, **existing}.items():
        merged_aliases = tuple(sorted(set(gov.aliases) | aliases.get(gov_id, set())))
        out.append(
            registry.Government(
                gov_id=gov.gov_id,
                gov_name=gov.gov_name,
                gov_type=gov.gov_type,
                country=gov.country,
                state=gov.state,
                place_geoid=gov.place_geoid,
                county_fips=gov.county_fips,
                sgc_code=gov.sgc_code,
                nces_lea_id=gov.nces_lea_id,
                cog_id=gov.cog_id,
                aliases=merged_aliases,
                source=gov.source or "seed",
                evidence=gov.evidence,
            )
        )
    registry.write_governments(out)
    print(f"{registry.GOVERNMENTS_FILE}: {len(out)} rows")


if __name__ == "__main__":
    main()
