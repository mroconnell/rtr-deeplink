#!/usr/bin/env python3
"""WO-227 data tail: probe Atlantic City NJ's real "City Council Meeting
08/19/26" BoxCast broadcast and route the verdict through the shared
`finish_candidate()` helper (WO-224), exactly the way every other
`wo1XXfinish_tier3.py` script does.

One real candidate, so this doesn't need WO-191's full pending-CSV
machinery -- see that script's own docstring for the general shape this
follows. `gov_id`/`jurisdiction` and the pin come straight from this WO's
own live investigation (`app/platforms/boxcast.py`'s module docstring;
the pin row itself already lives in `tenant_overrides.csv`, written
separately -- this script's own `pin=` is a no-op if it's already there,
same as `write_pin_row()`'s own dedup).

Usage:
    python scripts/wo227_finish_tier3.py
"""

import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.queue_probe import finish_candidate  # noqa: E402

register_all_finders()

MEETING_URL = "https://boxcast.tv/view/city-council-meeting-081926-kdhkjrwnostnrznx7yxy"
SOURCE_URL = "https://www.acnj.gov/pages/meeting-recordings"
GOV_ID = "us:place:3402080"
JURISDICTION = "City of Atlantic City, NJ"
TITLE = "City Council Meeting 08/19/26"
PIN = {
    "host": "boxcast.tv",
    # WO-245 (2026-09-12): was `external_id=boxcast:...` -- that field is
    # now the per-broadcast id (globally unique, never a pin key); the
    # government-level channel hint lives in `channel=` instead. This
    # script's own `write_pin_row()` dedup is a no-op today since the
    # row already lives in tenant_overrides.csv in its converted form.
    "match": "channel=boxcast:lqsszohc5p0q4yemoddl",
    "gov_id": GOV_ID,
    "strength": "fallback",
    "source": "wo227",
    "evidence": (
        "Atlantic City city, NJ -- BoxCast channel lqsszohc5p0q4yemoddl, "
        "confirmed live 2026-09-11 (WO-227)"
    ),
}


async def main() -> None:
    outcome = await finish_candidate(
        MEETING_URL,
        source_url=SOURCE_URL,
        gov_id=GOV_ID,
        jurisdiction=JURISDICTION,
        title=TITLE,
        pin=PIN,
        caller="wo227",
    )
    print("verdict:", outcome.probe.verdict)
    print("reason:", outcome.probe.reason)
    print("duration_seconds:", outcome.probe.duration_seconds)
    print("date:", outcome.probe.date)
    print("action:", outcome.action)
    print(
        "queued:",
        outcome.queued,
        "deferred:",
        outcome.deferred,
        "pinned:",
        outcome.pinned,
    )


if __name__ == "__main__":
    asyncio.run(main())
