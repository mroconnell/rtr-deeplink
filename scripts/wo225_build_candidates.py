"""WO-225 (2026-09-11): build the candidate list for re-testing the
`reject_reason == "no-video-found"` rows in `jurisdiction_coverage.csv`
that recorded nothing at all -- Ryan does not accept that every row
carrying this label means "a real meeting/agenda was found, no video";
the file itself agrees for a real subset of rows.

Filter, re-derived directly against the live research file (not the
registry snapshot, which can be stale by up to a day):
  reject_reason == "no-video-found"
  AND example_meeting_url is blank
  AND example_agenda_or_calendar_url is blank
  AND suspected_meeting_link_provider is blank
  AND suspected_calendar_provider is blank

`suspected_video_provider` is deliberately NOT part of the filter --
Ryan's brief names only the meeting-link/calendar provider columns, and a
handful of rows carry a video provider guess with nothing else recorded;
those are a different, narrower shape and stay out of this population
rather than being folded in silently.

gov_kind/population/hub_url are joined from
`coverage_registry/coverage_registry.csv` by gov_id (may be a few hours
stale -- the driver script re-reads the live jurisdiction_coverage.csv
row at sweep time, so staleness here only affects sort order and the
hub_url lead, never what's actually tried).

Order: population descending, US rows before Canadian rows (brief's own
priority order; 9-Sep numbers said 267 of 553 are 5,000+, 200 US/67 CA).

Usage:
    python3 scripts/wo225_build_candidates.py
"""

from __future__ import annotations

import csv
from pathlib import Path

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
JC_PATH = RESEARCH_DIR / "jurisdiction_coverage.csv"
REGISTRY_CSV = RESEARCH_DIR / "coverage_registry" / "coverage_registry.csv"
OUT_PATH = RESEARCH_DIR / "wo225_candidates.csv"

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


_COUNTRY_CODE = {
    "united states": "us",
    "usa": "us",
    "us": "us",
    "canada": "ca",
    "ca": "ca",
}


def normalize_country(raw: str) -> str:
    return _COUNTRY_CODE.get((raw or "").strip().lower(), (raw or "").strip().lower())


def parse_population(raw: str) -> float:
    raw = (raw or "").strip()
    if not raw:
        return -1.0
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return -1.0


def main() -> None:
    with JC_PATH.open(newline="", encoding="utf-8") as f:
        jc_rows = list(csv.DictReader(f))
    print(f"{len(jc_rows)} total rows in {JC_PATH.name}")

    matched = []
    for r in jc_rows:
        if (r.get("reject_reason") or "").strip() != "no-video-found":
            continue
        if (r.get("example_meeting_url") or "").strip():
            continue
        if (r.get("example_agenda_or_calendar_url") or "").strip():
            continue
        if (r.get("suspected_meeting_link_provider") or "").strip():
            continue
        if (r.get("suspected_calendar_provider") or "").strip():
            continue
        matched.append(r)

    print(
        f"{len(matched)} rows match: reject_reason=no-video-found, blank "
        "example_meeting_url, blank example_agenda_or_calendar_url, blank "
        "suspected_meeting_link_provider, blank suspected_calendar_provider"
    )

    with REGISTRY_CSV.open(newline="", encoding="utf-8") as f:
        registry_index = {
            (row.get("gov_id") or "").strip(): row for row in csv.DictReader(f)
        }
    print(f"{len(registry_index)} gov_ids in {REGISTRY_CSV.name}")

    candidates = []
    no_registry_row = 0
    for r in matched:
        gov_id = (r.get("gov_id") or "").strip()
        reg = registry_index.get(gov_id) if gov_id else None
        if reg is None:
            no_registry_row += 1
        country = normalize_country(r.get("country")) or (
            normalize_country(reg.get("country")) if reg else ""
        )
        population = (
            (reg.get("population") or "").strip()
            if reg
            else (r.get("population_estimate") or "").strip()
        )
        candidates.append(
            {
                "gov_id": gov_id,
                "name": (r.get("city_name") or "").strip(),
                "state": (r.get("state_or_province") or "").strip(),
                "country": country,
                "gov_kind": (reg.get("gov_kind") or "").strip() if reg else "",
                "population": population,
                "domain": (r.get("domain") or "").strip(),
                "alternate_domains": (r.get("alternate_domains") or "").strip(),
                "alternate_urls": (r.get("alternate_urls") or "").strip(),
                "hub_url": (reg.get("hub_url") or "").strip() if reg else "",
                "_pop": parse_population(population),
                "_country_rank": 0 if country == "us" else 1,
            }
        )

    print(
        f"{no_registry_row} matched rows have no coverage_registry.csv row (gov_kind/hub_url left blank)."
    )

    candidates.sort(key=lambda c: (c["_country_rank"], -c["_pop"]))

    us_count = sum(1 for c in candidates if c["country"] == "us")
    ca_count = sum(1 for c in candidates if c["country"] == "ca")
    other_count = len(candidates) - us_count - ca_count
    print(f"US: {us_count}, Canada: {ca_count}, other/blank country: {other_count}")

    pop_5000 = sum(1 for c in candidates if c["_pop"] >= 5000)
    print(f"{pop_5000} candidates have population >= 5,000")

    with OUT_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS, lineterminator="\n")
        w.writeheader()
        for c in candidates:
            w.writerow({k: c[k] for k in OUT_FIELDS})

    print(f"\nWrote {len(candidates)} rows to {OUT_PATH}")


if __name__ == "__main__":
    main()
