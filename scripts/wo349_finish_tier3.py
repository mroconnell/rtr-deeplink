"""WO-349: probe + finish (queue or defer) the 13 hand-checked tier-3
CivicPlus-population finds (video, no reachable captions) out of 23
tier-3 candidates from `research/wo349_verify.csv` /
`research/wo349_handcheck.csv`. The other 10 tier-3 candidates were
rejected by hand-check (see `research/wo349_handcheck.csv` and this
WO's `BACKLOG_DONE.md` entry): 3 on `hellonation.com` all resolved to
the exact same generic decorative header video (`hn_hdr26.mp4`, no
title/date -- a shared site-builder asset, not a meeting recording),
Del Mar CA's Vimeo resolved to an unrelated "Trekking to Mt. Everest
Base Camp" video, Alamosa County CO and Larned KS both resolved with no
obtainable title at all, St. Joseph MO's CivicClerk event title was the
generic placeholder "One Time Event" (not enough to confirm which body
met), and Grinnell IA / Hastings-on-Hudson NY / Easton CT all resolved
to real, identifiable meetings that are stale (21-46 months old, the
newest candidate the listing walker could reach) -- rejected on the same
"stale, not clearly current" basis WO-341 used for Pierce County WA's
2022 video.

Adds a per-tenant pin (blank match -- every host here except
`townhallstreams.com` is single-tenant) alongside the queue line, same
pattern as `scripts/wo347_finish_tier3.py`. `townhallstreams.com` is a
real shared host (WO-344/345/347/308 precedent): pinned by
`location_id=<N>`.

Usage (repo root, shared venv):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo349_finish_tier3.db" \\
        .venv/bin/python scripts/wo349_finish_tier3.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import resolve_via_platform  # noqa: E402
from app.platforms.queue_probe import finish_candidate  # noqa: E402

register_all_finders()

CANDIDATES = [
    dict(
        gov_id="us:place:0908420",
        jurisdiction="Bristol city, CT",
        url="https://bristolct.portal.civicclerk.com/event/4752/media",
        pin_host="bristolct.portal.civicclerk.com",
        pin_match="",
    ),
    dict(
        gov_id="us:place:0667056",
        jurisdiction="Sanger city, CA",
        url="https://sangerca.portal.civicclerk.com/event/4/media",
        pin_host="sangerca.portal.civicclerk.com",
        pin_match="",
    ),
    dict(
        gov_id="us:place:0617498",
        jurisdiction="Cudahy city, CA",
        url="https://townhallstreams.com/stream.php?location_id=115&id=76435",
        pin_host="townhallstreams.com",
        pin_match="location_id=115",
    ),
    dict(
        gov_id="us:place:2815380",
        jurisdiction="Columbus city, MS",
        url="https://columbusms.portal.civicclerk.com/event/266/media",
        pin_host="columbusms.portal.civicclerk.com",
        pin_match="",
    ),
    dict(
        gov_id="us:place:5355785",
        jurisdiction="Port Orchard city, WA",
        url="https://portorchardwa.portal.civicclerk.com/event/2506/media",
        pin_host="portorchardwa.portal.civicclerk.com",
        pin_match="",
    ),
    dict(
        gov_id="us:place:5379590",
        jurisdiction="Woodinville city, WA",
        url="https://woodinville.granicus.com/MediaPlayer.php?view_id=11&clip_id=2124",
        pin_host="woodinville.granicus.com",
        pin_match="",
    ),
    dict(
        gov_id="us:place:1780242",
        jurisdiction="Western Springs village, IL",
        url="https://westernspringsil.portal.civicclerk.com/event/274/media",
        pin_host="westernspringsil.portal.civicclerk.com",
        pin_match="",
    ),
    dict(
        gov_id="us:place:5320645",
        jurisdiction="Edgewood city, WA",
        url="https://edgewoodwa.portal.civicclerk.com/event/1121/media",
        pin_host="edgewoodwa.portal.civicclerk.com",
        pin_match="",
    ),
    dict(
        gov_id="us:place:5511200",
        jurisdiction="Burlington city, WI",
        url="https://burlingtonwi.new.swagit.com/videos/396670",
        pin_host="burlingtonwi.new.swagit.com",
        pin_match="",
    ),
    dict(
        gov_id="us:place:2756950",
        jurisdiction="St. Francis city, MN",
        url="https://saintfrancismn.portal.civicclerk.com/event/1658/media",
        pin_host="saintfrancismn.portal.civicclerk.com",
        pin_match="",
    ),
    dict(
        gov_id="us:place:3576200",
        jurisdiction="Taos town, NM",
        url="https://taosnm.new.swagit.com/videos/399879",
        pin_host="taosnm.new.swagit.com",
        pin_match="",
    ),
    dict(
        gov_id="us:cousub:2502167945",
        jurisdiction="Stoughton town, MA",
        url="http://71.184.118.35/internetchannel/show/13219?channel=2&query=redevelopment+authority",
        pin_host="71.184.118.35",
        pin_match="",
    ),
    dict(
        gov_id="us:cousub:3402500070",
        jurisdiction="Aberdeen township, NJ",
        url="https://aberdeentwpnj.portal.civicclerk.com/event/2024/media",
        pin_host="aberdeentwpnj.portal.civicclerk.com",
        pin_match="",
    ),
]


async def main():
    results = []
    for c in CANDIDATES:
        print(f"--- {c['gov_id']} {c['jurisdiction']} ---")
        try:
            result = await resolve_via_platform(c["url"])
        except Exception as e:  # noqa: BLE001
            print(f"resolve() failed: {type(e).__name__}: {e}")
            results.append((c["gov_id"], "resolve-failed", str(e)[:150]))
            continue
        print(
            "title:",
            result.title,
            "| date:",
            result.date,
            "| video_url:",
            (result.video_url or "")[:100],
        )
        if not result.video_url:
            print("SKIP: no video_url at finish time")
            results.append((c["gov_id"], "skipped-no-video-url"))
            continue

        outcome = await finish_candidate(
            meeting_url=c["url"],
            video_url=result.video_url,
            source_url=c["url"],
            platform=result.platform if hasattr(result, "platform") else None,
            gov_id=c["gov_id"],
            jurisdiction=c["jurisdiction"],
            title=result.title or "",
            pin=dict(
                host=c["pin_host"],
                match=c["pin_match"],
                gov_id=c["gov_id"],
                source="wo349",
                evidence=(
                    f"{c['jurisdiction']} -- WO-349 full-scale CivicPlus open-government "
                    f"run; verify_hub() found a real, hand-checked, current meeting "
                    f"({result.title!r}, {result.date}), video, no reachable captions."
                ),
            ),
            caller="wo349",
        )
        print(
            f"action={outcome.action} verdict={outcome.probe.verdict} "
            f"duration={outcome.probe.duration_seconds} reason={outcome.probe.reason} "
            f"pinned={outcome.pinned}"
        )
        results.append((c["gov_id"], outcome.action, outcome.probe.verdict))
        await asyncio.sleep(1.5)

    print("\n=== summary ===")
    for r in results:
        print(r)


asyncio.run(main())
