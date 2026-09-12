"""WO-292 (2026-09-12): school-district pilot, phase 1 -- reconnaissance.

Same pipeline as WO-282/283's phase 1 (`scripts/wo282_recon.py`, reused
here as a template -- DNS-first gate, always-fetch-live-homepage with
position-aware link extraction, every sitemap a robots.txt names,
Crawl-delay honored, a dedicated CDX health probe), run against the
1,000-district WO-292 population (`research/wo292_population.csv`)
instead of WO-282's city/county one. No scoring happens in this phase --
phase 2 (`wo292_classify.py`) re-scores the cached homepage HTML with the
gov_id-aware hop scorer (city/county vocabulary + the WO-292 school
vocabulary for every `us:sd:` row), reading no new network.

Usage (from the rtr-deeplink repo root, shared venv):
    .venv/bin/python scripts/wo292_recon.py --limit 50 --concurrency 32
    .venv/bin/python scripts/wo292_recon.py --concurrency 32
    .venv/bin/python scripts/wo292_recon.py --finalize
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

import wo282_recon as base  # noqa: E402

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
base.POPULATION_CSV = RESEARCH_DIR / "wo292_population.csv"
base.RECON_JSONL = RESEARCH_DIR / "wo292_recon.jsonl"
base.SCRATCH_DIR = Path(
    "/private/tmp/claude-501/-Users-mroconnell-Documents-rtr-deeplink--claude-worktrees-platform-detection-backfill-c9742a"
    "/1d27de13-eb07-451a-a07a-bb18900b5618/scratchpad/agents/a282f147d5af3176d/wo292_homepages"
)

if __name__ == "__main__":
    base.main()
