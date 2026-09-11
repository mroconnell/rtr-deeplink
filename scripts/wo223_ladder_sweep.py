#!/usr/bin/env python3
"""WO-223 stage 2: run the access ladder against the counties for which a
domain was found and verified by a real search-engine pass in
`wo223_find_domains.py` (see `rtr-business/research/wo223_domains_
resolved.csv` and this WO's `ENUMERATION_METHODS.md` section).

Reused BY IMPORT, never copied or edited, exactly like WO-218's own
`scripts/wo218_ladder_sweep.py` before it (which this file mirrors almost
line for line -- only the file-path constants differ):
  - `scripts/wo191_access_ladder_sweep.py`'s whole `process_candidate()`
    driver (plain -> browser-headers -> headless ladder, resolve/ingest/
    queue/pin pipeline) -- imported as a module and monkeypatched
    (module-level constant reassignment, not an edit to that file) to
    point at WO-223's own candidates/report/discovery/tier3-pending
    files.
  - `scripts/wo149_county_ladder_sweep.py`'s `jurisdiction_check_hook`
    (the wrong-domain-mapping guard), wired into
    `wo134.JURISDICTION_CHECK_HOOK` the same way WO-149/WO-218 did, since
    this candidate list is counties too.

`scripts/wo134_confirmed_hits_ingest.py` itself DID need one real fix as
part of this WO (not a monkeypatch -- a genuine bug in the shared file):
its tier-1/2 ingest call built the POST payload from
`result.model_dump()` alone, which never carries a `gov_id` key
(`ResolvedMeeting` has no such field) -- so every sweep built on this
driver, WO-223 included, was silently omitting the one payload field
`_resolve_page_government()`'s `caller_gov_id` short-circuit (WO-210)
needs to key a shared-host page before its pin is deployed. Fixed at the
one real call site; see that file's own inline comment for the incident
this matches (WO-210's "30+ pages landed rtr:unknown that evening" note,
CLAUDE.md/COVERAGE_HANDOVER.md's multi-gov-host rule).

Usage:
    python scripts/wo223_ladder_sweep.py --limit 10   # pilot
    python scripts/wo223_ladder_sweep.py              # rest, resumable
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

# Point wo191's driver at WO-223's own files (monkeypatch, not an edit).
wo191.CANDIDATES_CSV = RESEARCH_DIR / "wo223_candidates_for_ladder.csv"
wo191.REPORT_CSV = RESEARCH_DIR / "wo223_ladder_report.csv"
wo191.DISCOVERY_SEEDS_CSV = RESEARCH_DIR / "wo223_discovery_seeds.csv"
wo191.HOST_ACCESS_MODES_CSV = RESEARCH_DIR / "wo223_host_access_modes.csv"
wo191.TIER3_PENDING_CSV = RESEARCH_DIR / "wo223_tier3_pending.csv"
wo191.HEADLESS_BUDGET_JSON = RESEARCH_DIR / "wo223_headless_budget.json"
wo191.HEADLESS_BUDGET_TOTAL = 60  # 16 candidates this WO; generous headroom
# _headless_used was already computed at import time from wo191's OWN
# budget file (a stale, unrelated cumulative count) before the override
# above took effect -- re-derive it now from WO-223's own file so this
# run's budget isn't contaminated by a different WO's tally (the exact
# bug WO-218 §263 found and fixed mid-run).
wo191._headless_used = wo191._load_headless_used()

# County-specific wrong-domain-mapping guard (WO-149's pattern).
wo134.JURISDICTION_CHECK_HOOK = wo149.jurisdiction_check_hook


def build_ladder_candidates():
    """Convert wo223_domains_resolved.csv's domain_found rows into the
    (gov_id, name, state, gov_kind, population, domain, known_platform,
    hub_url, prior_url) shape wo191.process_candidate() expects."""
    src = RESEARCH_DIR / "wo223_domains_resolved.csv"
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
