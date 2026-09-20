"""One-off: given ONE bare Diligent Community tenant hostname (the
`*.community.diligentoneplatform.com` platform discovered via a Wayback/
CDX pull in the rtr-business research repo, not from any listing API --
CivicWeb's own adapter has no calendar-candidate extraction the way
CivicPlus/Granicus/CivicClerk do, confirmed live 2026-09-18: calling
`resolve()` directly on a bare `MeetingTypeList.aspx` URL just returns an
empty result with "Could not find a meeting id", not a CalendarPageError
with real candidates), find its real meetings and classify each into this
project's tier system.

Two fixes over an earlier, much slower version of this same idea:

1. **In-process, not one `bulk_ingest.py --dry-run` subprocess per
   meeting.** Each subprocess call was a fresh Python start plus a real
   network round-trip to the shared dry-run backend
   (rtr-deeplink-archive.onrender.com), ~2+ seconds each even before
   counting YouTube's own response time -- confirmed live, 12 meetings
   for one tenant took 28s that way. This script imports
   `app.platforms` directly and calls `finder.resolve(url)` in-process,
   same pattern as `scripts/catalog_video_hosting.py`.

2. **Classifies from `result.video_url`/`result.segments` directly, not
   by parsing dry-run's printed text.** Confirmed live 2026-09-18: a
   YouTube-delegated meeting can have `segments=0` (transcript/captions
   fetch failing -- see note below) while `video_url` is still populated
   correctly (`https://www.youtube.com/embed/{id}`), so segment count
   alone is NOT a reliable "has video" signal -- video_url is.

**Known live issue, confirmed 2026-09-18 from two different network
paths** (both the shared Render backend AND this machine's own local
`yt-dlp`): YouTube is currently returning "Sign in to confirm you're not
a bot" on every lookup, so segments will read 0 for genuinely-real
YouTube video right now. Per Ryan's explicit call: a YouTube video with
segments=0 is NOT "no video" -- it's tier 2, because we know about this
specific, currently-active issue. Tier definitions used here (ingest-
readiness, not confidence):
  tier 1 = real transcript ready now (segments > 0)
  tier 2 = YouTube-hosted video confirmed, no transcript
  tier 3 = video confirmed on some other platform, no transcript
  none   = no video found on this candidate at all

Usage:
    python scripts/diligent_community_tenant_probe.py <tenant-hostname> [--max N]

    python scripts/diligent_community_tenant_probe.py \\
        winthropminnesota.community.diligentoneplatform.com
"""

import argparse
import asyncio
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import get_finder  # noqa: E402

register_all_finders()

TODAY = date(2026, 9, 18)
MONTHS = {
    m: i
    for i, m in enumerate(
        [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ],
        start=1,
    )
}
MEETING_RE = re.compile(
    r'<a class="list-link" href="(/Portal/MeetingInformation\.aspx\?Id=\d+)">'
    r"([^<]*?)\s*-\s*([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4})</a>"
)
DEFAULT_MAX = 15


def fetch_meeting_type_list(host):
    """Same liveness+listing fetch validated earlier in the rtr-business
    research repo's diligent_community_walk_script.py -- HTTP, not DNS,
    tells a real tenant from Diligent's own DNS wildcard: a dead slug
    302-redirects to /home/sign-in with a ~160-byte body; a real tenant
    returns 200 with a real page."""
    url = f"https://{host}/Portal/MeetingTypeList.aspx"
    out = subprocess.run(
        [
            "curl",
            "-s",
            "-w",
            "\n---CODE---%{http_code}|%{size_download}",
            "--max-time",
            "15",
            url,
        ],
        capture_output=True,
        text=True,
    ).stdout
    if "---CODE---" not in out:
        return None, None, None
    body, meta = out.rsplit("---CODE---", 1)
    try:
        code, size = meta.split("|")
        code, size = int(code), int(size)
    except Exception:
        code, size = None, None
    return body, code, size


def parse_past_meetings(html):
    found = []
    for m in MEETING_RE.finditer(html):
        path, title, mon, day, year = m.groups()
        mon_num = MONTHS.get(mon)
        if not mon_num:
            continue
        try:
            d = date(int(year), mon_num, int(day))
        except ValueError:
            continue
        if d <= TODAY:
            found.append((path, title.strip(), d))
    found.sort(key=lambda t: t[2], reverse=True)
    return found


def classify(result):
    """(tier, reason) from a real ResolvedMeeting, not from printed text."""
    if result.segments:
        return 1, f"{len(result.segments)} real transcript segments"
    is_youtube = (result.video_format == "youtube") or (
        (result.video_url or "").startswith(
            ("https://www.youtube.com", "https://youtube.com")
        )
    )
    if result.video_url and is_youtube:
        return (
            2,
            "YouTube video confirmed, no transcript (known bot-check outage, 2026-09-18)",
        )
    if result.video_url:
        return (
            3,
            f"video confirmed on {result.video_format or result.platform}, no transcript",
        )
    return None, "no video found"


async def probe_tenant(host, max_checked):
    body, code, size = fetch_meeting_type_list(host)
    real = code == 200 and (size or 0) > 500
    print(f"{host}: http={code} size={size} real_tenant={real}")
    if not real:
        return

    past = parse_past_meetings(body)
    print(f"  {len(past)} past meetings found, checking up to {max_checked}")
    finder = get_finder("civicweb")

    best = None  # (tier, segments, path, title, d, reason)
    for path, title, d in past[:max_checked]:
        url = f"https://{host}{path}"
        try:
            result = await finder.resolve(url)
        except Exception as e:
            print(f"  {d} {title!r}: resolve error: {e}")
            continue
        tier, reason = classify(result)
        segments = len(result.segments)
        print(f"  {d} {title!r}: tier={tier} ({reason})")
        if tier is not None:
            key = (tier, segments if tier == 1 else 0)
            cur_key = (best[0], best[1] if best[0] == 1 else 0) if best else None
            if best is None or key < cur_key:
                best = (tier, segments, path, title, d, reason)

    if best:
        tier, segments, path, title, d, reason = best
        print(f"\n  BEST: tier{tier} -- {d} {title!r} -- https://{host}{path}")
        print(f"        {reason}")
    else:
        print("\n  BEST: none -- no video found in any checked meeting")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("host")
    ap.add_argument("--max", type=int, default=DEFAULT_MAX)
    args = ap.parse_args()
    asyncio.run(probe_tenant(args.host, args.max))


if __name__ == "__main__":
    main()
