"""WO-139 input filter: rtr-business/research/wo133_confirmed_hits.csv
(503 governments, WO-133's headless re-check) minus the CivicPlus
AgendaCenter tenants WO-127 already worked.

WO-127 ran a dedicated pipeline (scripts/wo127_civicplus_pipeline.py)
against every CivicPlus AgendaCenter tenant it could find and recorded a
real per-government outcome for each one in
scripts/civicplus_data/wo127_pipeline_report.csv (348 rows). 345 of
WO-133's 503 rows are `platform_hits` containing "civicplus" with
`detail` == "civicplus-agendacenter" AND already have a row in that
report -- re-running the general-purpose wo134_confirmed_hits_ingest.py
pipeline against them would just repeat WO-127's own real HTTP requests
against tenants already fully investigated. Per Ryan's instruction for
this batch: skip a civicplus/agendacenter row unless BOTH (a) a fresh
export shows no archived page for it yet, AND (b) WO-127's report has no
row for it at all.

This script only implements half of that ((b), which needs no network
access -- WO-127's report is a static file). Condition (a) is left to
wo134_confirmed_hits_ingest.py's own existing already_covered check
(`_load_covered_gov_ids()` against a fresh
`export_meeting_inventory.py --source export` run), which already runs
for every row in its INPUT_CSVS regardless of source. That is
deliberate, not a shortcut: computed against wo133_confirmed_hits.csv
directly, gov_id-in-wo127-report already narrows 503 rows to the same
150 "genuinely new" rows the work order describes (503 - 345 = 158
remaining here; the wo134 script's own fresh-export dedup independently
finds ~8 of those 158 already have a page from another route, netting
150) -- so condition (a) doesn't need to be duplicated here, it falls
out of running the normal pipeline.

Output: rtr-business/research/wo139_confirmed_hits.csv, same column
shape as wo133_confirmed_hits.csv (a straight row subset, nothing
recomputed), for wo134_confirmed_hits_ingest.py's INPUT_CSVS to consume
in place of the raw wo133_confirmed_hits.csv (see that file's own
comment on the swap).

Usage:
    python3 scripts/wo139_build_input.py
"""

import csv
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"

WO127_REPORT = REPO_ROOT / "scripts" / "civicplus_data" / "wo127_pipeline_report.csv"
WO133_HITS = RESEARCH_DIR / "wo133_confirmed_hits.csv"
OUT_PATH = RESEARCH_DIR / "wo139_confirmed_hits.csv"


def is_civicplus_agendacenter(row: dict) -> bool:
    platforms = row.get("platform_hits", "").split(";")
    return (
        "civicplus" in platforms and row.get("detail", "") == "civicplus-agendacenter"
    )


def main() -> None:
    with open(WO127_REPORT, newline="", encoding="utf-8") as f:
        wo127_gov_ids = {r["gov_id"] for r in csv.DictReader(f)}
    print(f"{len(wo127_gov_ids)} gov_ids in {WO127_REPORT.name}")

    with open(WO133_HITS, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    print(f"{len(rows)} rows in {WO133_HITS.name}")

    skipped = [
        r for r in rows if is_civicplus_agendacenter(r) and r["gov_id"] in wo127_gov_ids
    ]
    kept = [
        r
        for r in rows
        if not (is_civicplus_agendacenter(r) and r["gov_id"] in wo127_gov_ids)
    ]
    print(
        f"{len(skipped)} rows skipped: civicplus/agendacenter, already in WO-127's report"
    )
    print(f"{len(kept)} rows kept for wo134_confirmed_hits_ingest.py")

    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
