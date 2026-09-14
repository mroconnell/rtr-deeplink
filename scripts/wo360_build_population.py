"""WO-360, part A step 3 (population builder): the 20 governments the
brief's passive-v2 pass covers -- the 2 WV place rows whose domain
`wo360_apply_to_jc.py` just filled (Ansted town, Mount Hope city) and
the 18 WV counties the conductor's earlier WV pass re-keyed to a real
`wv.gov`-sourced domain (`research/wv_county_domain_corrections_2026-09-13
.csv`, excluding the 4 rows there that were already transcribed and only
got the wv.gov link as an alternate -- Greenbrier, Hancock, Monongalia,
Putnam counties are NOT re-tested, since their own domain didn't change).

Writes `research/wo360_population.csv` (gov_id, name, state, domain,
hub_url -- always `https://{domain}`, since none of these 20 rows carry
an `example_meeting_url`/`example_agenda_or_calendar_url` yet).
"""

from __future__ import annotations

import csv
from pathlib import Path

RTR_BUSINESS = Path("/Users/mroconnell/Documents/rtr-business")
JC_CSV = RTR_BUSINESS / "research" / "jurisdiction_coverage.csv"
POPULATION_CSV = RTR_BUSINESS / "research" / "wo360_population.csv"

COUNTY_IDS = {
    "us:county:54003",  # Berkeley
    "us:county:54019",  # Fayette
    "us:county:54021",  # Gilmer
    "us:county:54023",  # Grant
    "us:county:54037",  # Jefferson
    "us:county:54041",  # Lewis
    "us:county:54049",  # Marion
    "us:county:54051",  # Marshall
    "us:county:54047",  # McDowell
    "us:county:54055",  # Mercer
    "us:county:54067",  # Nicholas
    "us:county:54071",  # Pendleton
    "us:county:54075",  # Pocahontas
    "us:county:54081",  # Raleigh
    "us:county:54087",  # Roane
    "us:county:54089",  # Summers
    "us:county:54091",  # Taylor
    "us:county:54093",  # Tucker
}
PLACE_IDS = {"us:place:5401996", "us:place:5456404"}  # Ansted, Mount Hope
TARGET_IDS = COUNTY_IDS | PLACE_IDS


def main():
    rows = []
    with open(JC_CSV, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            if row["gov_id"] in TARGET_IDS:
                domain = (row["domain"] or "").strip()
                rows.append(
                    {
                        "gov_id": row["gov_id"],
                        "name": row["city_name"],
                        "state": row["state_or_province"],
                        "domain": domain,
                        "hub_url": f"https://{domain}",
                    }
                )
    assert len(rows) == len(TARGET_IDS), (
        f"expected {len(TARGET_IDS)} rows, found {len(rows)}"
    )
    with open(POPULATION_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["gov_id", "name", "state", "domain", "hub_url"]
        )
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} rows to {POPULATION_CSV}")


if __name__ == "__main__":
    main()
