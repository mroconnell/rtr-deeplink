#!/usr/bin/env python3
"""WO-218 stage 4: run the access ladder against the 34 counties for
which a domain was found and verified in stages 1-3.

Reused BY IMPORT, never copied or edited, exactly like WO-191 before it:
  - `scripts/wo191_access_ladder_sweep.py`'s whole `process_candidate()`
    driver (which itself reuses wo147's ladder and wo134's
    resolve/ingest/queue/pin pipeline) -- imported as a module and
    monkeypatched (module-level constant reassignment, not an edit to
    that file) to point at WO-218's own candidates/report/discovery/
    tier3-pending files.
  - `scripts/wo149_county_ladder_sweep.py`'s `jurisdiction_check_hook`
    (the Charleston-County-SC/Charleston-WV wrong-domain-mapping guard),
    wired into `wo134.JURISDICTION_CHECK_HOOK` the same way WO-149 did,
    since this candidate list is counties too.

Usage:
    python scripts/wo218_ladder_sweep.py --limit 15   # pilot
    python scripts/wo218_ladder_sweep.py              # rest, resumable
"""

import asyncio
import csv
import os
import sys
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("RTR_DEEPLINK_PATH", str(REPO_ROOT))

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"

import scripts.wo191_access_ladder_sweep as wo191  # noqa: E402
import scripts.wo149_county_ladder_sweep as wo149  # noqa: E402
import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402

# Point wo191's driver at WO-218's own files (monkeypatch, not an edit).
wo191.CANDIDATES_CSV = RESEARCH_DIR / "wo218_candidates_for_ladder.csv"
wo191.REPORT_CSV = RESEARCH_DIR / "wo218_ladder_report.csv"
wo191.DISCOVERY_SEEDS_CSV = RESEARCH_DIR / "wo218_discovery_seeds.csv"
wo191.HOST_ACCESS_MODES_CSV = RESEARCH_DIR / "wo218_host_access_modes.csv"
wo191.TIER3_PENDING_CSV = RESEARCH_DIR / "wo218_tier3_pending.csv"
wo191.HEADLESS_BUDGET_JSON = RESEARCH_DIR / "wo218_headless_budget.json"
wo191.HEADLESS_BUDGET_TOTAL = 150  # per WO-218's brief
# _headless_used was already computed at import time from wo191's OWN
# budget file (a stale, unrelated cumulative count) before the override
# above took effect -- re-derive it now from WO-218's own file so this
# run's budget isn't contaminated by a different WO's tally.
wo191._headless_used = wo191._load_headless_used()

# County-specific wrong-domain-mapping guard (WO-149's pattern).
wo134.JURISDICTION_CHECK_HOOK = wo149.jurisdiction_check_hook


def build_ladder_candidates():
    """Convert wo218_domains_resolved.csv's domain_found rows into the
    (gov_id, name, state, gov_kind, population, domain, known_platform,
    hub_url, prior_url) shape wo191.process_candidate() expects."""
    src = RESEARCH_DIR / "wo218_domains_resolved.csv"
    out = wo191.CANDIDATES_CSV
    rows = []
    with open(src, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["pre_outcome"] != "domain_found":
                continue
            rows.append(
                {
                    "gov_id": row["gov_id"],
                    "name": row["name"],
                    "state": row["state"],
                    "gov_kind": "county",
                    "population": row["population"],
                    "domain": row["domain_found"],
                    "known_platform": "",
                    "hub_url": "",
                    "prior_url": "",
                }
            )
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "gov_id",
                "name",
                "state",
                "gov_kind",
                "population",
                "domain",
                "known_platform",
                "hub_url",
                "prior_url",
            ],
        )
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} ladder candidates to {out}")


if __name__ == "__main__":
    build_ladder_candidates()
    asyncio.run(wo191.main())
