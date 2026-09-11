"""WO-183 (2026-09-11): build the candidate list for the CivicMirror-
addendum access-ladder sweep of the 803 brand-new rows
`ENUMERATION_METHODS.md` §228's addendum #2 (rtr-business commits
1532661/bf122eb/52e9f47) added to
rtr-business/research/jurisdiction_coverage.csv.

`jurisdiction_coverage.csv` has no `source` column, so the addendum's own
new-row output file, `research/wo177_newrows_applied.csv` (803 rows,
confirmed via `git -C .../rtr-business show --stat bf122eb`), is the
gov_id source for step 1 of this WO's brief. A row from that file is a
real candidate here only when the CURRENT jurisdiction_coverage.csv row
for that gov_id still has `transcribed` blank, `reject_reason` blank,
`domain` set, and `gov_id` set (the addendum applied `domain`/`gov_id`
directly, so this is mostly a confirmation, not a discovery, but another
concurrent session may have already tested one of these 803 rows since
the addendum landed).

Skips rows whose gov_id already appears in wo191_report.csv,
wo184_report.csv or wo190_report.csv (concurrent sessions' own candidate
sets tonight, per this WO's brief) -- counted and reported, never
silently dropped.

Order: population descending, unknown population placed in the middle
(between the 5,000+ band and the under-1,000 band), matching
docs/BREADTH_SWEEP_BRIEF.md's priority order and
scripts/wo191_build_candidates.py's own band scheme (these are almost
entirely townships, so most of them will land in the "unknown
population" or "under 1,000" bands -- expected, not a bug).

Writes research/wo183_candidates.csv with the same row shape
scripts/wo147_access_ladder_sweep.py's CANDIDATES_CSV uses (gov_id, name,
state, gov_kind, population, domain, known_platform, hub_url,
prior_source, prior_reason, prior_url) so wo183_access_ladder_sweep.py
(copied from wo191_access_ladder_sweep.py, since that WO is still running
and its script isn't committed anywhere importable yet -- see this repo's
own copy for the one-line note) can drive it through the SAME
run_access_ladder()/find_platform_link() imported from
scripts/wo147_access_ladder_sweep.py, unmodified.

Usage:
    python3 scripts/wo183_build_candidates.py
"""

from __future__ import annotations

import csv
from pathlib import Path

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
JC_PATH = RESEARCH_DIR / "jurisdiction_coverage.csv"
NEW_ROWS_PATH = RESEARCH_DIR / "wo177_newrows_applied.csv"
OUT_PATH = RESEARCH_DIR / "wo183_candidates.csv"

SKIP_FILES = [
    RESEARCH_DIR / "wo191_report.csv",
    RESEARCH_DIR / "wo184_report.csv",
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
    """Lower number sorts first. Band order: >25000, 5000-25000, unknown,
    1000-5000, <1000 -- same scheme as wo191_build_candidates.py."""
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
    print("Skip-list files (concurrent sessions' own candidate sets tonight):")
    for name, count in skip_counts.items():
        print(f"  {name}: {count}")
    print(f"Total distinct gov_ids to skip: {len(skip_ids)}")

    with NEW_ROWS_PATH.open(newline="", encoding="utf-8") as f:
        civicmirror_rows = list(csv.DictReader(f))
    civicmirror_gov_ids = {
        r.get("gov_id", "").strip()
        for r in civicmirror_rows
        if r.get("gov_id", "").strip()
    }
    print(
        f"\n{len(civicmirror_rows)} rows in {NEW_ROWS_PATH.name} "
        f"({len(civicmirror_gov_ids)} distinct gov_ids) -- the CivicMirror "
        f"addendum #2 new-row source for this WO."
    )

    with JC_PATH.open(newline="", encoding="utf-8") as f:
        jc_rows = list(csv.DictReader(f))
    print(f"{len(jc_rows)} total rows in {JC_PATH.name}")

    jc_by_gov_id = {
        r.get("gov_id", "").strip(): r for r in jc_rows if r.get("gov_id", "").strip()
    }

    candidates = []
    skipped_by_other_session = 0
    skipped_not_in_jc = 0
    skipped_already_tested = 0
    skipped_no_domain = 0

    for gov_id in civicmirror_gov_ids:
        r = jc_by_gov_id.get(gov_id)
        if r is None:
            skipped_not_in_jc += 1
            continue

        transcribed = (r.get("transcribed") or "").strip()
        reject_reason = (r.get("reject_reason") or "").strip()
        if transcribed or reject_reason:
            skipped_already_tested += 1
            continue

        domain = (r.get("domain") or "").strip()
        if not domain:
            skipped_no_domain += 1
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
                "prior_source": "wo177_newrows_applied.csv (CivicMirror addendum #2)",
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
    print(f"{skipped_not_in_jc} skipped: gov_id not found in {JC_PATH.name}.")
    print(
        f"{skipped_already_tested} skipped: already tested (transcribed or reject_reason set)."
    )
    print(f"{skipped_no_domain} skipped: no domain set.")
    print(
        f"{skipped_by_other_session} skipped: gov_id owned by wo184/wo190/wo191 tonight."
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
