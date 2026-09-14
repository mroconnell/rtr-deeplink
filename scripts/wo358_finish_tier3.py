"""WO-358: probe + finish (queue or defer) the 9 hand-checked tier-3
candidates from the 148-government "stale label" bucket (CivicClerk/
eScribe/iQM2/Town Hall Streams governments whose registry row names the
platform but had no confirmed tenant URL on file -- BACKLOG.md's matching
entry, `research/wo350_methods_section.md` / ENUMERATION_METHODS.md §352).

Petersburgh town, NY's first candidate (id=72646, "Medicare Seminar",
2026-02-04) was hand-check-rejected as Kind B (not a deliberative
meeting) -- per Ryan's "keep walking until 3 videos seen, one is a
meeting" rule, its own townhallstreams listing
(`townhallstreams.com/towns/petersburg_ny`, 252 real rows) was walked by
hand for the newest already-recorded (date <= today) real meeting, which
is id=76437 "C8 Committee", 2026-09-03 -- substituted here.

Adds a per-tenant pin (blank match -- every host here except
townhallstreams.com is single-tenant), same pattern as
`scripts/wo349_finish_tier3.py` / `scripts/wo350`'s (unc­ommitted)
run. `townhallstreams.com` is pinned by `location_id=<N>`.

Usage (repo root, shared venv):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo358_finish_tier3.db" \\
        .venv/bin/python scripts/wo358_finish_tier3.py
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
        gov_id="us:place:4875236",
        jurisdiction="Venus town, TX",
        url="https://venustx.portal.civicclerk.com/event/361/media",
        pin_host="venustx.portal.civicclerk.com",
        pin_match="",
    ),
    dict(
        gov_id="us:place:1829358",
        jurisdiction="Greencastle city, IN",
        url="https://greencastlein.portal.civicclerk.com/event/1699/media",
        pin_host="greencastlein.portal.civicclerk.com",
        pin_match="",
    ),
    dict(
        gov_id="us:place:4829972",
        jurisdiction="Godley city, TX",
        url="https://godleytx.portal.civicclerk.com/event/6070/media",
        pin_host="godleytx.portal.civicclerk.com",
        pin_match="",
    ),
    dict(
        gov_id="us:place:4866416",
        jurisdiction="Seadrift city, TX",
        url="https://seadrifttx.portal.civicclerk.com/event/21/files",
        pin_host="seadrifttx.portal.civicclerk.com",
        pin_match="",
    ),
    dict(
        gov_id="us:place:2720078",
        jurisdiction="Excelsior city, MN",
        url="https://excelsiormn.portal.civicclerk.com/event/3241/media",
        pin_host="excelsiormn.portal.civicclerk.com",
        pin_match="",
    ),
    dict(
        gov_id="us:cousub:2502109175",
        jurisdiction="Brookline town, MA",
        url="https://brooklinema.portal.civicclerk.com/event/16635/media",
        pin_host="brooklinema.portal.civicclerk.com",
        pin_match="",
    ),
    dict(
        gov_id="us:place:4858280",
        jurisdiction="Pleasanton city, TX",
        url="http://pleasantontx.iqm2.com/Citizens/Detail_Meeting.aspx?ID=1372",
        pin_host="pleasantontx.iqm2.com",
        pin_match="",
    ),
    dict(
        gov_id="us:county:23023",
        jurisdiction="Sagadahoc County, ME",
        url="https://townhallstreams.com/stream.php?location_id=154&id=76623",
        pin_host="townhallstreams.com",
        pin_match="location_id=154",
    ),
    dict(
        gov_id="us:cousub:3608357441",
        jurisdiction="Petersburgh town, NY",
        url="https://townhallstreams.com/stream.php?location_id=152&id=76437",
        pin_host="townhallstreams.com",
        pin_match="location_id=152",
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
                source="wo358",
                evidence=(
                    f"{c['jurisdiction']} -- WO-358 stale-label small-platform bucket "
                    f"run; verify_hub()'s one-hop-deeper fallback found a real, "
                    f"hand-checked, current meeting ({result.title!r}, {result.date}), "
                    "video, no reachable captions."
                ),
            ),
            caller="wo358",
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
