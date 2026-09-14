"""WO-356 item 1's one real find: Greensboro town, MD
(`us:place:2435200`). The alternate-hub pass on the 91 "no meeting
found" governments found this government's own bare homepage links a
real, current Town Hall Meeting on Town Hall Streams (2026-08-20, 134.8
min, video, no reachable captions). Only 1 candidate exists on the
government's own page -- no listing to check for a shorter alternative
-- so per CLAUDE.md's long-only-videos rule this is queued directly."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from app.platforms.queue_probe import (  # noqa: E402
    TENANT_OVERRIDES_CSV,
    TIER3_QUEUE_FILE,
    append_queue_line,
    write_pin_row,
)

URL = "https://townhallstreams.com/stream.php?location_id=172&id=76081"


def main() -> None:
    pinned = write_pin_row(
        host="townhallstreams.com",
        match="location_id=172",
        gov_id="us:place:2435200",
        strength="fallback",
        source="wo356",
        evidence=(
            "Greensboro town, MD -- WO-356 item 1 (alternate-hub pass on "
            "WO-349's 91 'no meeting found' governments): verify_hub() on "
            "the government's own bare homepage (greensboromd.org) found "
            "a real, current Town Hall Meeting (2026-08-20), video, no "
            "reachable captions, 134.8 min. Only 1 candidate exists on "
            "this government's own page (no listing to check for a "
            "shorter alternative), so per CLAUDE.md's long-only-videos "
            "rule this is queued directly rather than deferred."
        ),
        pins_path=TENANT_OVERRIDES_CSV,
    )
    queued = append_queue_line(URL, URL, queue_path=TIER3_QUEUE_FILE)
    print(f"pinned={pinned} queued={queued}")


if __name__ == "__main__":
    main()
