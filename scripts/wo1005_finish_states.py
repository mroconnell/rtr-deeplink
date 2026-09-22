#!/usr/bin/env python3
"""WO-1005: queue/ingest one hand-read real meeting per state for South
Carolina, Tennessee, and Nevada -- the three states BACKLOG.md's
"`direct_file` refuses South Carolina's legislature video ..." entry named
as unreachable before this WO's two fixes:

1. `app/platforms/direct_file.py` now accepts `video.scstatehouse.gov`'s
   real `.mp4` files even though the host answers `Content-Type:
   application/octet-stream` instead of `video/*` (confirmed live
   2026-09-22 via HEAD and a ranged GET on two real, small committee
   meetings -- see that file's own `_OCTET_STREAM_CONTENT_TYPE` comment).
2. `app/platforms/granicus.py` now retries a real HTTP 403 once with a
   fuller browser header set before giving up (see `_BROWSER_RETRY_
   HEADERS`'s module comment) -- added for a reported block on
   `tnga.granicus.com`/`nvleg.granicus.com` that this WO's own live
   re-verification could not reproduce on 2026-09-22 (kept as a real,
   narrowly-scoped defensive rung regardless -- see that comment for the
   full reasoning).

Each pick below was read by hand (title, chamber, real caption content or
its absence) via a real `resolve()` call before being listed here -- same
WO-921 hand-verification convention BACKLOG.md's entry points to, not a
guess from URL shape alone:

* South Carolina (`us:state:45`) -- video only, no captions on either
  chamber's real meeting -> tier-3 queue (probed via `finish_candidate()`,
  never downloaded).
* Nevada (`us:state:32`) -- video only, no captions on either chamber's
  real meeting -> tier-3 queue.
* Tennessee (`us:state:47`) -- BOTH chambers' real meetings came back with
  real, coherent Granicus captions (2,827 and 4,214 cues, zero
  transcript_warnings) -- genuinely different from the other two states,
  so these are ingested as real pages instead of queued.

    DATABASE_URL="sqlite+aiosqlite:////tmp/wo1005_scratch.db" PYTHONPATH=. \\
        .venv/bin/python scripts/wo1005_finish_states.py --dry-run
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo1005_scratch.db" PYTHONPATH=. \\
        .venv/bin/python scripts/wo1005_finish_states.py

`--dry-run` resolves through the real adapters and prints what WOULD
happen; without it, SC/NV candidates are probed and queued for real via
`app.platforms.queue_probe.finish_candidate()` and TN candidates are
POSTed to `/internal/ingest` via `scripts.bulk_ingest._ingest()`, exactly
the same functions every other tier-3/ingest script in this repo already
calls -- nothing new invented here.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

import certifi

# Must run before `import aiohttp` anywhere in the process -- see
# scripts/transcribe_backlog_locally.py's own module-level fix and
# CLAUDE.md's matching convention bullet.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

# The worktree this WO runs from has no .env of its own (gitignored, not
# copied by `git worktree add`) -- load the shared checkout's, same
# explicit-path convention as scripts/wo921_ingest.py, rather than letting
# python-dotenv's default cwd-walk silently find nothing (or the wrong
# thing) here. See CLAUDE.md's worktree .env bullet.
load_dotenv("/Users/mroconnell/Documents/rtr-deeplink/.env")

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import detect_platform, get_finder  # noqa: E402
from app.platforms.queue_probe import finish_candidate  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402
from scripts.bulk_ingest import _ingest  # noqa: E402

register_all_finders()

# (gov_id, state, chamber, url) -- one hand-read real meeting per chamber.
# See this module's docstring for how each was hand-verified.
QUEUE_PICKS = [
    (
        "us:state:45",
        "South Carolina",
        "Senate (Judiciary Full Committee)",
        "https://video.scstatehouse.gov/mp4/20260811SJudiciaryFullCommittee16632_1.mp4",
    ),
    (
        "us:state:45",
        "South Carolina",
        "House (Govt Efficiency and Legislative Oversight subcommittee)",
        "https://video.scstatehouse.gov/mp4/"
        "20260811HGovtEfficiencyandLegOversightLawEnforcementCriminal16624_1.mp4",
    ),
    (
        "us:state:32",
        "Nevada",
        "Senate (Floor Session)",
        "https://nvleg.granicus.com/MediaPlayer.php?view_id=14&clip_id=13425",
    ),
    (
        "us:state:32",
        "Nevada",
        "Assembly (Floor Session)",
        "https://nvleg.granicus.com/MediaPlayer.php?view_id=14&clip_id=13426",
    ),
]

INGEST_PICKS = [
    (
        "us:state:47",
        "Tennessee",
        "Senate",
        "https://tnga.granicus.com/MediaPlayer.php?view_id=777&clip_id=31636",
    ),
    (
        "us:state:47",
        "Tennessee",
        "House",
        "https://tnga.granicus.com/MediaPlayer.php?view_id=776&clip_id=33450",
    ),
]


async def _do_queue_pick(
    gov_id: str, state: str, chamber: str, url: str, dry: bool
) -> None:
    platform = detect_platform(url)
    res = await get_finder(platform).resolve(url)
    print(f"[{state} - {chamber}] {url}")
    print(f"  title={res.title!r} date={res.date} video_url={res.video_url!r}")
    print(
        f"  segments={len(res.segments or [])} transcript_warnings={res.transcript_warnings}"
    )
    if res.segments:
        print("  ** has real captions -- should be an INGEST pick, not a queue pick **")
        return
    if not res.video_url:
        print("  -> SKIP: no video_url resolved")
        return
    if dry:
        print("  -> dry-run: would call finish_candidate() to queue this")
        return
    outcome = await finish_candidate(
        url,
        video_url=res.video_url,
        source_url=res.source_url or url,
        platform=platform,
        video_format=res.video_format,
        gov_id=gov_id,
        jurisdiction=res.jurisdiction or state,
        title=res.title or "",
        caller="wo1005_finish_states",
    )
    print(f"  -> action={outcome.action} probe_verdict={outcome.probe.verdict}")


async def _do_ingest_pick(
    session: aiohttp.ClientSession,
    gov_id: str,
    state: str,
    chamber: str,
    url: str,
    dry: bool,
) -> None:
    platform = detect_platform(url)
    res = await get_finder(platform).resolve(url)
    print(f"[{state} - {chamber}] {url}")
    print(f"  title={res.title!r} date={res.date} video_url={res.video_url!r}")
    print(
        f"  segments={len(res.segments or [])} transcript_warnings={res.transcript_warnings}"
    )
    if not res.segments:
        print("  ** no real captions -- should be a QUEUE pick, not an ingest pick **")
        return
    if dry:
        print("  -> dry-run: would POST this to /internal/ingest")
        return
    payload = res.model_dump()
    payload["gov_id"] = gov_id
    resp = await _ingest(session, payload, normalize_url(res.source_url or url))
    if resp is None:
        print("  -> ingest-failed")
    else:
        print(
            f"  -> {'created' if resp.get('created') else 'existing'} {resp.get('url') or ''}"
        )


async def main(dry: bool) -> None:
    for gov_id, state, chamber, url in QUEUE_PICKS:
        await _do_queue_pick(gov_id, state, chamber, url, dry)
        await asyncio.sleep(2)

    async with aiohttp.ClientSession() as session:
        for gov_id, state, chamber, url in INGEST_PICKS:
            await _do_ingest_pick(session, gov_id, state, chamber, url, dry)
            await asyncio.sleep(2)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    asyncio.run(main(args.dry_run))
