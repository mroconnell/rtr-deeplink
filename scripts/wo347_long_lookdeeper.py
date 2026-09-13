"""WO-347: for the 4 tier-3 candidates whose newest real meeting probed
over 90 minutes, look one meeting deeper on the same hub/tenant listing
for a shorter, on-mission alternative before queuing the long one anyway
(CLAUDE.md's 2026-09-12 'long-only videos' rule, same pattern WO-345 used
for Crow Wing/Kennebunkport/Sand Lake/North Hempstead)."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.passive_verify import (  # noqa: E402
    _escribe_walker,
    _townhallstreams_walker,
)
from app.platforms.queue_probe import probe_queue_entry  # noqa: E402

register_all_finders()

HUBS = [
    ("St. Stephen, NB", "escribe", "https://pub-chocolatetown.escribemeetings.com/"),
    ("Lac la Biche County, AB", "escribe", "https://pub-llbc.escribemeetings.com/"),
    (
        "Pittsboro town, IN",
        "townhallstreams",
        "https://townhallstreams.com/towns/pittsboro_in",
    ),
    (
        "Hampton Falls town, NH",
        "townhallstreams",
        "https://townhallstreams.com/towns/hamptonfalls",
    ),
]


async def main():
    for name, platform, hub_url in HUBS:
        print("=" * 90)
        print(name, platform, hub_url)
        if platform == "escribe":
            candidates = await _escribe_walker(hub_url)
        else:
            candidates = await _townhallstreams_walker(hub_url)
        print(f"  {len(candidates)} candidates found (newest-first)")
        for i, cand in enumerate(candidates[:8]):
            url = cand.get("url")
            title = cand.get("title")
            date = cand.get("date")
            print(f"  [{i}] {date} | {title} | {url}")
            probe = await probe_queue_entry(url, platform=platform)
            mins = (probe.duration_seconds or 0) / 60
            print(
                f"      -> verdict={probe.verdict} duration={mins:.1f}min reason={probe.reason}"
            )


if __name__ == "__main__":
    asyncio.run(main())
