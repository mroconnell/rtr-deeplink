#!/usr/bin/env python3
"""WO-352: finish the one real tier-3 candidate hand-confirmed in chunk 1
(Alamosa County CO, Board of County Commissioners, 2026-09-09, a Google
Drive file linked from the county's own AgendaCenter media column).

Same shape as wo338_finish_tier3.py, pointed at a small hand-built
pending list rather than a bulk scan, because this chunk only produced
one real, hand-confirmed candidate (see the chunk's hand-read notes:
Winchester IN/Tallassee AL/Duncan SC/West Reading PA were decorative
homepage banner videos, Garza County TX was a "Pavilion Flythrough"
drone video, York County ME's candidate is already queued under York
town ME's own gov_id -- none of those five are queued here).

drive.google.com is a MULTI_GOV_HOSTS host (app/utils/gov_registry/
registry.py), so this candidate needs its own tenant_overrides.csv pin
before/при queueing -- finish_candidate() writes it.

Usage:
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo352_tier3_scratch.db" \\
        .venv/bin/python scripts/wo352_finish_tier3.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import certifi  # noqa: E402

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from dotenv import load_dotenv  # noqa: E402

load_dotenv("/Users/mroconnell/Documents/rtr-deeplink/.env")

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.queue_probe import finish_candidate  # noqa: E402

register_all_finders()

CALLER = "wo352_finish_tier3"


async def main():
    meeting_url = "https://drive.google.com/file/d/15Da90idg18_FGxqILMhHPHFnjdY87i_q/view?usp=sharing"
    pin = {
        "host": "drive.google.com",
        "match": "file/d/15Da90idg18_FGxqILMhHPHFnjdY87i_q/view?usp=sharing",
        "gov_id": "us:county:08003",
        "strength": "fallback",
        "source": "wo352",
        "evidence": (
            "Alamosa County, CO -- county's own AgendaCenter "
            "(https://alamosacounty.org/agendacenter) 'Board of County "
            "Commissioners Agenda 9-9' entry (2026-09-09) links this Drive "
            "file under its Media column; verify_hub() calendar_page walk, "
            "hand-confirmed via the Drive share page's own title "
            "('September 9 2026') and the agenda row's aria-label "
            "(WO-352)."
        ),
    }
    outcome = await finish_candidate(
        meeting_url,
        source_url="https://alamosacounty.org/agendacenter",
        platform="direct_file",
        gov_id="us:county:08003",
        jurisdiction="Alamosa County, CO",
        title="Board of County Commissioners Agenda 9-9",
        pin=pin,
        caller=CALLER,
    )
    result = outcome.probe
    print(
        f"verdict={result.verdict} reason={result.reason!r} "
        f"duration_seconds={result.duration_seconds} action={outcome.action} "
        f"queued={outcome.queued} pinned={outcome.pinned} "
        f"used_cache={outcome.used_cache}"
    )


if __name__ == "__main__":
    asyncio.run(main())
