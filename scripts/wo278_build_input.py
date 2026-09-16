"""WO-278 Part B: builds `research/wo278_confirmed_hits.csv`, the
WO-134-shaped input row set for `scripts/wo278_confirmed_hits_ingest.py`
-- one row per government that survived Part A's corrected confirmation
rule (`research/wo273_targeted_corrected.csv`, `platform_confirmed` set),
with every distinct confirmed (platform, url) pair from that government
folded into its `hit_source_urls` field (same `platform=url;platform=url`
shape `wo134_confirmed_hits_ingest.py._parse_hit_source_urls()` expects).

`gov_id`/`city_name`/`state_or_province` come from `research/
wo273_candidates.csv` (WO-273 phase 1's own candidate pool, which already
carries a resolved `gov_id` for every row in this population -- verified
directly before writing this script, not assumed: all 60 confirmed
domains had one).

Usage (from the rtr-deeplink repo root):
    python scripts/wo278_build_input.py
"""

import csv
from collections import defaultdict
from pathlib import Path

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
CAND_CSV = RESEARCH_DIR / "wo273_candidates.csv"
TARGETED_CORRECTED_CSV = RESEARCH_DIR / "wo273_targeted_corrected.csv"
OUT_CSV = RESEARCH_DIR / "wo278_confirmed_hits.csv"


def main() -> None:
    with open(CAND_CSV, newline="", encoding="utf-8") as f:
        cands = {r["domain"]: r for r in csv.DictReader(f)}
    with open(TARGETED_CORRECTED_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    hits_by_domain = defaultdict(list)
    for r in rows:
        if r["platform_confirmed"]:
            hits_by_domain[r["domain"]].append((r["platform_confirmed"], r["url"]))

    out_rows = []
    for domain in sorted(hits_by_domain):
        c = cands.get(domain, {})
        gov_id = c.get("gov_id", "")
        city = c.get("city_name", "")
        state = c.get("state_or_province", "")
        unit_name = f"{city}, {state}" if city and state else domain
        seen = set()
        pairs = []
        for platform, url in hits_by_domain[domain]:
            key = (platform, url)
            if key not in seen:
                seen.add(key)
                pairs.append(f"{platform}={url}")
        out_rows.append(
            {
                "gov_id": gov_id,
                "unit_name": unit_name,
                "domain": domain,
                "state": state,
                "homepage": f"https://{domain}",
                "hop2_urls": "",
                "hit_source_urls": ";".join(pairs),
            }
        )

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "gov_id",
                "unit_name",
                "domain",
                "state",
                "homepage",
                "hop2_urls",
                "hit_source_urls",
            ],
        )
        writer.writeheader()
        writer.writerows(out_rows)

    print(f"wrote {len(out_rows)} rows to {OUT_CSV}")
    no_gov_id = [r for r in out_rows if not r["gov_id"]]
    if no_gov_id:
        print(
            f"WARNING: {len(no_gov_id)} row(s) with no gov_id: {[r['domain'] for r in no_gov_id]}"
        )


if __name__ == "__main__":
    main()
