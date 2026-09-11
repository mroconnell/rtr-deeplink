#!/usr/bin/env python3
"""WO-223 stage 3: probe the tier-3 candidate(s)
`wo223_ladder_sweep.py` found before any of them reach the real queue
file, per Ryan's "probe before queue" rule.

Reused BY IMPORT, never copied or edited, exactly like WO-218's own
`scripts/wo218_finish_tier3.py`-shaped step before it: this file is
`scripts/wo191_finish_tier3.py`'s whole `main_async()` driver, imported
as a module and monkeypatched (module-level constant reassignment) to
point at WO-223's own pending/finish-log files instead of WO-191's.

Usage:
    python scripts/wo223_finish_tier3.py
"""

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import scripts.wo191_finish_tier3 as wo191_finish  # noqa: E402

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
wo191_finish.PENDING_CSV = RESEARCH_DIR / "wo223_tier3_pending.csv"
wo191_finish.FINISH_LOG_CSV = RESEARCH_DIR / "wo223_tier3_finish_log.csv"

if __name__ == "__main__":
    asyncio.run(wo191_finish.main_async(None))
