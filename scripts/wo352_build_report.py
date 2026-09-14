#!/usr/bin/env python3
"""WO-352: builds `research/wo352_report.csv`, one row per government
processed so far (chunk 1: 150 of the 2,258-row population), from
`wo352_verify.csv` (the verify_hub() result) and
`wo352_final_classification.csv` (tier/reject_reason/should_apply/note).

Offline, idempotent, resumable -- rewrites fresh from the two inputs
each run, safe mid-sweep.

Usage:
    .venv/bin/python scripts/wo352_build_report.py
"""

from __future__ import annotations

import csv
from pathlib import Path

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
POPULATION_CSV = RESEARCH_DIR / "wo352_population.csv"
VERIFY_CSV = RESEARCH_DIR / "wo352_verify.csv"
FINAL_CSV = RESEARCH_DIR / "wo352_final_classification.csv"
REPORT_CSV = RESEARCH_DIR / "wo352_report.csv"

FIELDNAMES = [
    "domain",
    "gov_id",
    "name",
    "state",
    "population",
    "hub_url",
    "hub_source",
    "platform_hint",
    "resolved_platform",
    "verdict",
    "tier",
    "meeting_url",
    "prior_reject_reason",
    "new_reject_reason",
    "should_apply",
    "note",
]


def main():
    population_order = []
    with open(POPULATION_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            population_order.append(row["gov_id"])

    verify = {}
    with open(VERIFY_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            verify[row["gov_id"]] = row

    final = {}
    with open(FINAL_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            final[row["gov_id"]] = row

    out_rows = []
    for gov_id in population_order:
        v = verify.get(gov_id)
        if v is None:
            continue  # not yet processed (a later chunk)
        fin = final.get(gov_id, {})
        out_rows.append(
            {
                "domain": v["domain"],
                "gov_id": gov_id,
                "name": v["name"],
                "state": v["state"],
                "population": v["population"],
                "hub_url": v["hub_url"],
                "hub_source": v["hub_source"],
                "platform_hint": v["platform_hint"],
                "resolved_platform": v["resolved_platform"],
                "verdict": v["verdict"],
                "tier": fin.get("tier", v["tier"]),
                "meeting_url": v["meeting_url"],
                "prior_reject_reason": fin.get("prior_reject_reason", ""),
                "new_reject_reason": fin.get("new_reject_reason", ""),
                "should_apply": fin.get("should_apply", ""),
                "note": fin.get("note", ""),
            }
        )

    with open(REPORT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(out_rows)

    print(f"{len(out_rows)} rows written to {REPORT_CSV}")


if __name__ == "__main__":
    main()
