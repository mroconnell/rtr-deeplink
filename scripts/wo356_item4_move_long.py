"""WO-356 item 4: Ryan's standing rule (2026-09-13) -- a tier-3 video over
90 minutes is QUEUED, never parked; the deferred file is only for
WO-266-style parking of a government that already has a transcript
elsewhere, not for length alone. Moves Cudahy city, CA (us:place:0617498,
townhallstreams location_id=115, 1:30:33) and Port Orchard city, WA
(us:place:5355785, CivicClerk portal, 2:50:26) from
scripts/tier3_long_meetings_deferred.txt to scripts/tier3_auto_transcription_queue.txt.

Both already have a real cached probe verdict (accept) in
tier3_auto_transcription_queue_probe.csv from WO-349's own run -- no
re-probe needed. Writes the owner pin first (WO-346 guard): Cudahy's
Town Hall Streams location_id=115 (a real per-government path on a host
not literally in MULTI_GOV_HOSTS, but the established pin convention for
this platform, WO-344/345/347/308); Port Orchard's CivicClerk portal
subdomain (single-tenant, blank match, same convention as every other
*.portal.civicclerk.com pin already in the file).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms.queue_probe import (  # noqa: E402
    TENANT_OVERRIDES_CSV,
    TIER3_LONG_MEETINGS_DEFERRED_FILE,
    TIER3_QUEUE_FILE,
    append_queue_line,
    write_pin_row,
)

TARGET_URLS = {
    "https://townhallstreams.com/stream.php?location_id=115&id=76435": dict(
        gov_id="us:place:0617498",
        jurisdiction="Cudahy city, CA",
        pin_host="townhallstreams.com",
        pin_match="location_id=115",
        evidence=(
            "Cudahy city, CA -- WO-349 found this real meeting "
            "('City Council Meeeting', 1:30:33) and moved it to the "
            "deferred file because it probed over 90 minutes, before "
            "reaching the pin-write step. WO-356 (2026-09-13): Ryan's "
            "standing rule is a long tier-3 video is queued, never "
            "parked for length alone -- moved to the queue and pinned "
            "now. A second real video on the same location_id (id=76169, "
            "'City Council Meeting', 2026-08-18) was already sitting in "
            "the queue unpinned from an earlier WO; hand-checked here "
            "too and covered by the same pin."
        ),
    ),
    "https://portorchardwa.portal.civicclerk.com/event/2506/media": dict(
        gov_id="us:place:5355785",
        jurisdiction="Port Orchard city, WA",
        pin_host="portorchardwa.portal.civicclerk.com",
        pin_match="",
        evidence=(
            "Port Orchard city, WA -- WO-349 found this real meeting "
            "('City Council Regular Meeting', 2:50:26) and moved it to "
            "the deferred file because it probed over 90 minutes, before "
            "reaching the pin-write step. WO-356 (2026-09-13): Ryan's "
            "standing rule is a long tier-3 video is queued, never "
            "parked for length alone -- moved to the queue and pinned "
            "now (single-tenant CivicClerk portal, blank match, same "
            "convention as every other *.portal.civicclerk.com pin)."
        ),
    ),
}


def main() -> None:
    deferred_path = TIER3_LONG_MEETINGS_DEFERRED_FILE
    lines = deferred_path.read_text(encoding="utf-8").splitlines(keepends=True)

    kept_lines = []
    removed = []
    for line in lines:
        stripped = line.rstrip("\n")
        first_field = (
            stripped.split("\t", 1)[0]
            if stripped and not stripped.startswith("#")
            else ""
        )
        if first_field in TARGET_URLS:
            removed.append(first_field)
            continue
        kept_lines.append(line)

    print(f"removed {len(removed)} lines from deferred file: {removed}")
    assert len(removed) == 2, (
        f"expected to remove exactly 2 lines, removed {len(removed)}"
    )

    deferred_path.write_text("".join(kept_lines), encoding="utf-8")

    for url, meta in TARGET_URLS.items():
        pinned = write_pin_row(
            host=meta["pin_host"],
            match=meta["pin_match"],
            gov_id=meta["gov_id"],
            strength="fallback",
            source="wo356",
            evidence=meta["evidence"],
            pins_path=TENANT_OVERRIDES_CSV,
        )
        queued = append_queue_line(url, url, queue_path=TIER3_QUEUE_FILE)
        print(f"{url} -> pinned={pinned} queued={queued}")


if __name__ == "__main__":
    main()
