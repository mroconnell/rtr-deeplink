"""Resolve the 218 governments phase 3 confirmed a platform for (2026-09-22
passive-pipe production run, rtr-business research/dns_ctlog_sweep_2026-09-17/
production_run_2026-09-22/confirmed_218.json) and classify each by tier.

Same in-process pattern as the Diligent Community sweep (catalog_video_
hosting.py / diligent_community_full_sweep.py): call the real adapter
directly, no subprocess, no dry-run round trip to the archive server.

Classification order matters -- checked live 2026-09-20 that this is the
one mistake worth guarding against by construction, not just by care:
ANY YouTube video is tier 2, regardless of segment count, checked BEFORE
the segments check. A YouTube video with real segments is still tier 2 --
it goes to the drip feed, never ingested from a research script (Ryan,
2026-09-20).

  tier 1 = real transcript, NOT YouTube -> real ingest
  tier 2 = YouTube, any segment count -> youtube_channel_leads.csv
  tier 3 = video confirmed, no transcript, not YouTube -> tier-3 queue
  none   = no video found

A confirmed URL that turns out to be a listing/calendar page
(CalendarPageError) gets the same depth search this project always uses:
up to MAX_TRIED candidates, newest-first, keep the first tier 1, else the
first tier 2 or 3.

Usage:
    python scripts/resolve_phase3_confirmed.py <confirmed.json> <out.csv>
"""

import asyncio
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import (  # noqa: E402
    detect_platform,
    get_finder,
    CalendarPageError,
    NoVideoCandidateFound,
    UnsupportedPlatformError,
)

register_all_finders()

MAX_TRIED = 6


def classify(result):
    is_youtube = (result.video_format == "youtube") or (
        (result.video_url or "").startswith(
            ("https://www.youtube.com", "https://youtube.com", "https://youtu.be")
        )
    )
    if result.video_url and is_youtube:
        return (
            2,
            "youtube",
            f"YouTube video confirmed{' (has captions)' if result.segments else ''}",
        )
    if result.segments:
        return 1, result.platform, f"{len(result.segments)} real transcript segments"
    if result.video_url:
        return (
            3,
            result.platform,
            f"video confirmed on {result.video_format or result.platform}, no transcript",
        )
    return None, result.platform, "no video found"


async def resolve_one(url):
    try:
        platform = detect_platform(url)
        finder = get_finder(platform)
    except UnsupportedPlatformError as e:
        return {"action": None, "reason": f"unsupported platform: {e}"}

    try:
        result = await finder.resolve(url)
        tier, plat, reason = classify(result)
        if tier:
            return {
                "action": tier,
                "url": url,
                "platform": plat,
                "title": result.title,
                "date": result.date,
                "segments": len(result.segments),
                "video_url": result.video_url,
                "reason": reason,
            }
        return {"action": None, "reason": reason}
    except CalendarPageError as e:
        best = None
        for cand in e.candidates[:MAX_TRIED]:
            curl = cand["url"]
            try:
                cplatform = detect_platform(curl)
                cfinder = get_finder(cplatform)
                cresult = await cfinder.resolve(curl)
            except Exception:
                continue
            tier, plat, reason = classify(cresult)
            if tier == 1:
                return {
                    "action": 1,
                    "url": curl,
                    "platform": plat,
                    "title": cresult.title,
                    "date": cresult.date,
                    "segments": len(cresult.segments),
                    "video_url": cresult.video_url,
                    "reason": reason,
                }
            if tier and best is None:
                best = {
                    "action": tier,
                    "url": curl,
                    "platform": plat,
                    "title": cresult.title,
                    "date": cresult.date,
                    "segments": len(cresult.segments),
                    "video_url": cresult.video_url,
                    "reason": reason,
                }
        if best:
            return best
        return {
            "action": None,
            "reason": f"calendar page, {len(e.candidates)} candidates checked, no video",
        }
    except NoVideoCandidateFound as e:
        # A confident real negative (the adapter already walked its own
        # listing internally, e.g. CivicPlus AgendaCenter) -- not an error.
        return {
            "action": None,
            "reason": f"checked {e.candidates_checked} candidates, no video found",
        }
    except Exception as e:
        return {"action": None, "reason": f"resolve error: {type(e).__name__}: {e}"}


# Fixed, complete superset -- a "none" result and a real hit have
# different keys, and the crash this replaced (2026-09-22, French Lick IN's
# real tier-2 hit) came from DictWriter locking its header to whichever
# row happened to be written first.
FIELDNAMES = [
    "gov_id",
    "domain",
    "phase3_platform_signal",
    "action",
    "reason",
    "platform",
    "url",
    "title",
    "date",
    "segments",
    "video_url",
]


def load_done(out_csv):
    done = {}
    if Path(out_csv).exists():
        for r in csv.DictReader(open(out_csv)):
            done[r["gov_id"]] = r
    return done


async def main(in_json, out_csv):
    rows = json.load(open(in_json))
    results = list(load_done(out_csv).values())
    done_ids = {r["gov_id"] for r in results}
    remaining = [r for r in rows if r["gov_id"] not in done_ids]
    print(
        f"{len(done_ids)} already done, {len(remaining)} remaining of {len(rows)}",
        flush=True,
    )

    def checkpoint():
        with open(out_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES, extrasaction="ignore")
            w.writeheader()
            w.writerows(results)

    for i, row in enumerate(remaining, 1):
        r = await resolve_one(row["url"])
        out = {
            "gov_id": row["gov_id"],
            "domain": row["domain"],
            "phase3_platform_signal": row.get("platform_signal", ""),
            **r,
        }
        results.append(out)
        print(
            f"{i}/{len(remaining)} {row['domain']}: action={r.get('action')} "
            f"platform={r.get('platform')} {r.get('reason', '')[:80]}",
            flush=True,
        )
        if i % 10 == 0:
            checkpoint()

    checkpoint()

    import collections

    c = collections.Counter(str(r.get("action") or "") for r in results)
    print(
        f"\nFINAL: tier1={c.get('1', 0)} tier2={c.get('2', 0)} tier3={c.get('3', 0)} "
        f"none={c.get('', 0)} of {len(results)}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
