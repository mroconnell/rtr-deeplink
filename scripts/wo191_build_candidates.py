"""WO-191 (2026-09-11): build the candidate list for tonight's first-pass
access-ladder sweep of never-tested governments in
rtr-business/research/jurisdiction_coverage.csv.

A row is "never tested" when both `transcribed` and `reject_reason` are
blank. Tonight's specific candidate filter (conductor's brief,
docs/COVERAGE_HANDOVER.md, docs/BREADTH_SWEEP_BRIEF.md): never tested,
has a `domain`, no `example_agenda_or_calendar_url` / `example_meeting_url`,
no `alternate_domains` / `alternate_urls`, has a `gov_id`, and
`website_status` is not `none-known-2022`.

Order: population descending within band, band order over-25000 ->
5000-25000 -> unknown-population -> 1000-5000 -> under-1000 (the
conductor's brief puts unknown population, which is mostly Canadian,
after the 5000+ US rows and before the under-1000 rows).

Skips rows whose gov_id already appears in wo184_report.csv,
wo189_report.csv or wo190_report.csv (concurrent sessions' own candidate
sets tonight) -- counted and reported, never silently dropped.

Writes research/wo191_candidates.csv with the same row shape
scripts/wo147_access_ladder_sweep.py's CANDIDATES_CSV uses (gov_id, name,
state, gov_kind, population, domain, known_platform, hub_url,
prior_source, prior_reason, prior_url) so wo191_access_ladder_sweep.py
can drive it through the SAME run_access_ladder()/find_platform_link()
imported from that module, unmodified.

Usage:
    python3 scripts/wo191_build_candidates.py
"""

from __future__ import annotations

import csv
from pathlib import Path

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
JC_PATH = RESEARCH_DIR / "jurisdiction_coverage.csv"
OUT_PATH = RESEARCH_DIR / "wo191_candidates.csv"

SKIP_FILES = [
    RESEARCH_DIR / "wo184_report.csv",
    RESEARCH_DIR / "wo189_report.csv",
    RESEARCH_DIR / "wo190_report.csv",
]

OUT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "population",
    "domain",
    "known_platform",
    "hub_url",
    "prior_source",
    "prior_reason",
    "prior_url",
]


def gov_kind_from_id(gov_id: str) -> str:
    g = (gov_id or "").strip()
    if g.startswith("us:place:"):
        return "us_place"
    if g.startswith("us:county:"):
        return "us_county"
    if g.startswith("us:cousub:"):
        return "us_cousub"
    if g.startswith("us:sd:"):
        return "us_sd"
    if g.startswith("us:state:"):
        return "us_state"
    if g.startswith("ca:csd:"):
        return "ca_csd"
    if g.startswith("ca:cd:"):
        return "ca_cd"
    if g.startswith("ca:pr:"):
        return "ca_pr"
    if g.startswith("rtr:"):
        return "rtr_minted"
    return "unknown"


def parse_population(raw: str) -> float | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def population_band(pop: float | None) -> int:
    """Lower number sorts first. Band order per the brief: >25000,
    5000-25000, unknown, 1000-5000, <1000."""
    if pop is None:
        return 2
    if pop > 25000:
        return 0
    if pop >= 5000:
        return 1
    if pop >= 1000:
        return 3
    return 4


def load_skip_gov_ids() -> tuple[set, dict]:
    skip_ids: set = set()
    counts: dict = {}
    for path in SKIP_FILES:
        if not path.exists():
            counts[path.name] = "missing (not yet written)"
            continue
        with path.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        found = {
            r.get("gov_id", "").strip() for r in rows if r.get("gov_id", "").strip()
        }
        counts[path.name] = len(found)
        skip_ids |= found
    return skip_ids, counts


def main() -> None:
    skip_ids, skip_counts = load_skip_gov_ids()
    print("Skip-list files:")
    for name, count in skip_counts.items():
        print(f"  {name}: {count}")
    print(
        f"Total distinct gov_ids to skip (owned by other sessions tonight): {len(skip_ids)}"
    )

    with JC_PATH.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"\n{len(rows)} total rows in {JC_PATH.name}")

    candidates = []
    skipped_by_other_session = 0
    for r in rows:
        transcribed = (r.get("transcribed") or "").strip()
        reject_reason = (r.get("reject_reason") or "").strip()
        if transcribed or reject_reason:
            continue  # already tested

        domain = (r.get("domain") or "").strip()
        if not domain:
            continue

        agenda_url = (r.get("example_agenda_or_calendar_url") or "").strip()
        meeting_url = (r.get("example_meeting_url") or "").strip()
        if agenda_url or meeting_url:
            continue

        alt_domains = (r.get("alternate_domains") or "").strip()
        alt_urls = (r.get("alternate_urls") or "").strip()
        if alt_domains or alt_urls:
            continue

        gov_id = (r.get("gov_id") or "").strip()
        if not gov_id:
            continue

        website_status = (r.get("website_status") or "").strip()
        if website_status == "none-known-2022":
            continue

        if gov_id in skip_ids:
            skipped_by_other_session += 1
            continue

        pop = parse_population(r.get("population_estimate"))
        candidates.append(
            {
                "gov_id": gov_id,
                "name": r.get("city_name", "").strip(),
                "state": r.get("state_or_province", "").strip(),
                "gov_kind": gov_kind_from_id(gov_id),
                "population": r.get("population_estimate", "").strip(),
                "domain": domain,
                "known_platform": (
                    r.get("suspected_meeting_link_provider", "").strip()
                    or r.get("suspected_calendar_provider", "").strip()
                    or r.get("suspected_video_provider", "").strip()
                ),
                "hub_url": "",
                "prior_source": "jurisdiction_coverage.csv",
                "prior_reason": "",
                "prior_url": domain,
                "_pop": pop,
                "_band": population_band(pop),
            }
        )

    candidates.sort(key=lambda c: (c["_band"], -(c["_pop"] or 0)))

    band_counts = {}
    for c in candidates:
        band_counts[c["_band"]] = band_counts.get(c["_band"], 0) + 1
    band_labels = {
        0: "over 25,000",
        1: "5,000-25,000",
        2: "unknown population",
        3: "1,000-5,000",
        4: "under 1,000",
    }
    print(f"\n{len(candidates)} real candidates after all filters.")
    print(
        f"{skipped_by_other_session} rows skipped: gov_id owned by wo184/wo189/wo190 tonight."
    )
    print("\nBy population band:")
    for band in sorted(band_labels):
        print(f"  {band_labels[band]}: {band_counts.get(band, 0)}")

    with OUT_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS, lineterminator="\n")
        w.writeheader()
        for c in candidates:
            w.writerow({k: c[k] for k in OUT_FIELDS})

    print(f"\nWrote {len(candidates)} rows to {OUT_PATH}")


if __name__ == "__main__":
    main()
