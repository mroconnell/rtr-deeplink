"""WO-216 (2026-09-11): build the candidate list for the ladder sweep of
governments that have a domain but were never tested, per the Gov
Coverage dashboard (coverage registry).

Filter, re-derived by the conductor against
`rtr-business/research/coverage_registry/coverage_registry.csv` (refreshed
07:10 today): `domain` non-blank AND `test_status == "untested"` AND
`gov_kind in (municipality, township, county)`. School districts
(gov_kind == "school_district") are explicitly excluded -- not this WO's
job. Confirmed live at build time: 417 US rows (297 municipality, 53
township, 67 county) + 34 Canadian rows (30 municipality, 4 county).

Columns taken straight from the registry snapshot (gov_id, name, state,
country, gov_kind, population, domain, alternate_domains, alternate_urls,
hub_url) -- the driver script re-reads the LIVE `jurisdiction_coverage.csv`
row by gov_id at sweep time (registries can be a few hours stale by the
time a long sweep reaches a row), so staleness here only affects sort
order, never what's actually tried.

Order: population descending, US rows before Canadian rows (brief's own
priority order).

Usage:
    python3 scripts/wo216_build_candidates.py
"""

from __future__ import annotations

import csv
from pathlib import Path

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
REGISTRY_CSV = RESEARCH_DIR / "coverage_registry" / "coverage_registry.csv"
OUT_PATH = RESEARCH_DIR / "wo216_candidates.csv"

TARGET_KINDS = {"municipality", "township", "county"}

OUT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "country",
    "gov_kind",
    "population",
    "domain",
    "alternate_domains",
    "alternate_urls",
    "hub_url",
]


def parse_population(raw: str) -> float:
    raw = (raw or "").strip()
    if not raw:
        return -1.0
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return -1.0


def main() -> None:
    with REGISTRY_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"{len(rows)} total rows in {REGISTRY_CSV.name}")

    candidates = []
    kind_country_counts: dict = {}
    for r in rows:
        gov_kind = (r.get("gov_kind") or "").strip()
        if gov_kind not in TARGET_KINDS:
            continue
        if (r.get("test_status") or "").strip() != "untested":
            continue
        domain = (r.get("domain") or "").strip()
        if not domain:
            continue

        country = (r.get("country") or "").strip().lower()
        key = (country, gov_kind)
        kind_country_counts[key] = kind_country_counts.get(key, 0) + 1

        candidates.append(
            {
                "gov_id": (r.get("gov_id") or "").strip(),
                "name": (r.get("name") or "").strip(),
                "state": (r.get("state") or "").strip(),
                "country": country,
                "gov_kind": gov_kind,
                "population": (r.get("population") or "").strip(),
                "domain": domain,
                "alternate_domains": (r.get("alternate_domains") or "").strip(),
                "alternate_urls": (r.get("alternate_urls") or "").strip(),
                "hub_url": (r.get("hub_url") or "").strip(),
                "_pop": parse_population(r.get("population")),
                "_country_rank": 0 if country == "us" else 1,
            }
        )

    candidates.sort(key=lambda c: (c["_country_rank"], -c["_pop"]))

    print(f"\n{len(candidates)} real candidates after filters.")
    print("\nBy (country, gov_kind):")
    for key in sorted(kind_country_counts):
        print(f"  {key}: {kind_country_counts[key]}")

    us_count = sum(1 for c in candidates if c["country"] == "us")
    ca_count = sum(1 for c in candidates if c["country"] == "ca")
    print(f"\nUS total: {us_count}, Canada total: {ca_count}")

    with OUT_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS, lineterminator="\n")
        w.writeheader()
        for c in candidates:
            w.writerow({k: c[k] for k in OUT_FIELDS})

    print(f"\nWrote {len(candidates)} rows to {OUT_PATH}")


if __name__ == "__main__":
    main()
