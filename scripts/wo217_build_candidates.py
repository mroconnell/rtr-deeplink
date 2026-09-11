"""WO-217 (2026-09-11): build the candidate list for the one-hop
alternate-domain pass on municipalities of 5,000+ with no Archive page
whose `reject_reason` is `no-video-found` or `meeting-without-video`.

Population, re-derived fresh at run time from
`~/Documents/rtr-business/research/coverage_registry/coverage_registry.csv`
(gov_kind == municipality, population >= 5000, archive_pages == 0,
reject_reason in {no-video-found, meeting-without-video}).

Group split:
  - has_alternate: row already carries alternate_domains/alternate_urls.
    wo184_onehop_done is "yes" when the gov_id appears in
    `wo184_onehop_report.csv` AND that prior run's own `alternate_domain`
    is the SAME first alternate candidate_domains() would try today (i.e.
    nothing new to check) -- "no" when the gov_id was never checked, or
    when a new alternate has been added to the row since WO-184's run
    (candidate_domains()'s first non-primary entry differs from the
    logged one).
  - no_alternate: row has no alternate on file yet -- WO-217 must find
    one first (uscityurl / Wikidata / civicdata / hub host / guess).

Output: research/wo217_candidates.csv (this repo's private-per-WO output
lives in rtr-business/research, matching every other WO-184-family
script).

Usage:
    python3 scripts/wo217_build_candidates.py
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.coverage_alternates import candidate_domains  # noqa: E402

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
REGISTRY_CSV = RESEARCH_DIR / "coverage_registry" / "coverage_registry.csv"
ONEHOP_PRIOR_CSV = RESEARCH_DIR / "wo184_onehop_report.csv"
OUT_CSV = RESEARCH_DIR / "wo217_candidates.csv"

REASONS = {"no-video-found", "meeting-without-video"}

FIELDS = [
    "gov_id",
    "name",
    "state",
    "country",
    "population",
    "domain",
    "reject_reason",
    "alternate_domains",
    "alternate_urls",
    "hub_url",
    "known_platform",
    "wo184_onehop_done",
]


def load_prior_onehop() -> dict:
    """gov_id -> alternate_domain WO-184's one-hop pass actually tried."""
    out = {}
    if not ONEHOP_PRIOR_CSV.exists():
        return out
    with ONEHOP_PRIOR_CSV.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            gid = r.get("gov_id", "")
            if gid:
                out[gid] = r.get("alternate_domain", "")
    return out


def main() -> None:
    prior = load_prior_onehop()
    print(f"{len(prior)} gov_ids in {ONEHOP_PRIOR_CSV.name} (WO-184 one-hop pass).")

    rows_out = []
    with REGISTRY_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("gov_kind") != "municipality":
                continue
            try:
                pop = float(row.get("population") or 0)
            except ValueError:
                pop = 0
            if pop < 5000:
                continue
            try:
                pages = int(row.get("archive_pages") or 0)
            except ValueError:
                pages = 0
            if pages != 0:
                continue
            reason = (row.get("reject_reason") or "").strip()
            if reason not in REASONS:
                continue

            gov_id = row.get("gov_id", "")
            alt_domains = (row.get("alternate_domains") or "").strip()
            alt_urls = (row.get("alternate_urls") or "").strip()

            wo184_done = "no"
            if gov_id in prior:
                candidates = candidate_domains(row)
                first_alt_today = candidates[1] if len(candidates) > 1 else ""
                prior_alt = prior[gov_id]
                if first_alt_today and first_alt_today == prior_alt:
                    wo184_done = "yes"
                # else: a new alternate exists that WO-184 never saw --
                # leave wo184_onehop_done "no" so this is treated as new
                # work.

            rows_out.append(
                {
                    "gov_id": gov_id,
                    "name": row.get("name", ""),
                    "state": row.get("state", ""),
                    "country": row.get("country", ""),
                    "population": row.get("population", ""),
                    "domain": row.get("domain", ""),
                    "reject_reason": reason,
                    "alternate_domains": alt_domains,
                    "alternate_urls": alt_urls,
                    "hub_url": row.get("hub_url", ""),
                    "known_platform": row.get("known_platform", ""),
                    "wo184_onehop_done": wo184_done,
                }
            )

    rows_out.sort(key=lambda r: -(float(r["population"] or 0)))

    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows_out)

    has_alt = [r for r in rows_out if r["alternate_domains"] or r["alternate_urls"]]
    no_alt = [
        r for r in rows_out if not (r["alternate_domains"] or r["alternate_urls"])
    ]
    has_alt_new = [r for r in has_alt if r["wo184_onehop_done"] != "yes"]
    has_alt_skip = [r for r in has_alt if r["wo184_onehop_done"] == "yes"]

    print(f"Total candidates: {len(rows_out)}")
    print(
        f"  has_alternate: {len(has_alt)}  (new work: {len(has_alt_new)}, "
        f"already done by WO-184: {len(has_alt_skip)})"
    )
    print(f"  no_alternate:  {len(no_alt)}")
    print(f"Wrote {OUT_CSV}")


if __name__ == "__main__":
    main()
