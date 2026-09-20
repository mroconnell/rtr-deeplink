"""WO-914: rerun the Diligent Community tenants the first sweep under-read.

`scripts/diligent_community_full_sweep.py` (WO-911's source) only read a
meeting link whose text ended "Mon D YYYY". Its parser is fixed now (any
meeting link is read). This script re-reads ONLY the links the old parser
dropped, on the tenants that had any, and records what each one holds.

What it does per tenant (one government at a time, 2s between requests):
  1. fetch MeetingTypeList.aspx, parse with the fixed parser;
  2. keep the links the OLD regex did not read (those are the unread ones);
  3. for each (newest first, cap MAX_CHECKED) read the tenant's own
     `/api/videolink/{id}` and `/Services/MeetingsService.svc/meetings/{id}/
     meetingData` -- the same two JSON calls `CivicWebAssetFinder.resolve()`
     makes -- and classify.

Deliberately NOT done here: any fetch of youtube.com / youtu.be /
googlevideo / ytimg. `CivicWebAssetFinder.resolve()` calls
`YouTubeAssetFinder.resolve_video_id()`, which does fetch YouTube, so this
script does not call it. A YouTube video id in the tenant's own JSON is
recorded as a YouTube find (tier 2 in the sweep's vocabulary; whether it
has captions is a question for the YouTube channel drip, not for this
script). A non-YouTube external video link is only recorded here (kind
"external"); it is read and probed by hand in a later phase.

Report rows are flushed per tenant, so a re-run resumes.

Usage:
    python scripts/wo914_diligent_rerun.py <hosts.txt> <report.csv> \
        <meetings.csv> [--budget-seconds N]
"""

import asyncio
import csv
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import certifi  # noqa: E402

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402

from scripts.diligent_community_full_sweep import (  # noqa: E402
    MAX_CHECKED,
    parse_past_meetings,
)

# The regex the first sweep used (WO-911's source), kept here only to tell
# which links it never read.
OLD_MEETING_RE = re.compile(
    r'<a class="list-link" href="(/Portal/MeetingInformation\.aspx\?Id=\d+)">'
    r"([^<]*?)\s*-\s*([A-Za-z]{3})\s+(\d{1,2})\s+(\d{4})</a>"
)
UA = "RedTapeRecordings-research/1.0 (+https://redtaperecordings.com)"
DELAY = 2.0
YOUTUBE_HOSTS = ("youtube.com", "youtu.be", "googlevideo.com", "ytimg.com")

REPORT_FIELDS = [
    "host",
    "list_http",
    "list_links",
    "unread_links",
    "meetings_checked",
    "videos_found",
    "action",
    "tier",
    "video_kind",
    "video_id_or_url",
    "meeting_url",
    "meeting_title",
    "meeting_date",
    "meeting_id",
    "list_flagged_video",
    "notes",
]
MEETING_FIELDS = [
    "host",
    "meeting_id",
    "link_text",
    "link_date",
    "list_flagged_video",
    "api_date",
    "meeting_name",
    "video_kind",
    "video_id_or_url",
    "raw_keys",
]


def is_youtube_url(u):
    h = (urlparse(u).hostname or "").lower()
    return any(h == y or h.endswith("." + y) for y in YOUTUBE_HOSTS)


async def get(session, url):
    """(status, text). Plain GET, honest UA; no browser-header retry needed
    on these tenants."""
    try:
        async with session.get(
            url, headers={"User-Agent": UA}, timeout=aiohttp.ClientTimeout(total=20)
        ) as r:
            return r.status, await r.text()
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def load_json(text):
    """Parse JSON that may be double-encoded (the videolink API returns a
    JSON string containing JSON)."""
    try:
        v = json.loads(text)
        if isinstance(v, str):
            v = json.loads(v)
        return v
    except Exception:  # noqa: BLE001
        return None


def flagged_video_ids(html):
    return set(re.findall(r'class="video-event[^"]*" date-id="(\d+)"', html))


async def read_meeting(session, host, meeting_id):
    """One meeting: (video_kind, video_id_or_url, api_date, name, raw_keys).
    video_kind in {youtube, external, none}."""
    base = f"https://{host}"
    await asyncio.sleep(DELAY)
    _, vtext = await get(session, f"{base}/api/videolink/{meeting_id}")
    await asyncio.sleep(DELAY)
    _, mtext = await get(
        session,
        f"{base}/Services/MeetingsService.svc/meetings/{meeting_id}/meetingData",
    )
    videolink = load_json(vtext)
    meeting = load_json(mtext)
    entry = videolink[0] if isinstance(videolink, list) and videolink else None
    api_date = (entry.get("MeetingDate") or "")[:10] if entry else ""
    name = (meeting or {}).get("Name") or ""
    raw_keys = ",".join(sorted(entry.keys())) if entry else ""
    vid = entry.get("YouTubeEventId") if entry else None
    if vid:
        return "youtube", vid, api_date, name, raw_keys
    if meeting:
        for link_field, name_field in (
            ("MeetingExternalMinutesLinkUrl", "MeetingExternalMinutesLinkName"),
            ("MeetingExternalLinkUrl", "MeetingExternalLinkName"),
        ):
            link = meeting.get(link_field)
            if link and "video" in (meeting.get(name_field) or "").lower():
                return (
                    "youtube" if is_youtube_url(link) else "external",
                    link,
                    api_date,
                    name,
                    raw_keys,
                )
    return "none", "", api_date, name, raw_keys


async def run_tenant(session, host, meetings_writer):
    row = dict.fromkeys(REPORT_FIELDS, "")
    row["host"] = host
    status, html = await get(session, f"https://{host}/Portal/MeetingTypeList.aspx")
    row["list_http"] = status
    if status != 200:
        row["action"] = "list_unreachable"
        row["notes"] = str(html)[:120]
        return row
    everything = parse_past_meetings(html)
    old = {m.group(1) for m in OLD_MEETING_RE.finditer(html)}
    unread = [(p, t, d) for p, t, d in everything if p not in old]
    flagged = flagged_video_ids(html)
    row["list_links"] = len(everything)  # past or undated; future-dated excluded
    row["unread_links"] = len(unread)
    videos = []
    for path, title, d in unread[:MAX_CHECKED]:
        mid = path.rsplit("=", 1)[1]
        kind, val, api_date, name, raw_keys = await read_meeting(session, host, mid)
        meetings_writer.writerow(
            {
                "host": host,
                "meeting_id": mid,
                "link_text": title,
                "link_date": d.isoformat() if d else "",
                "list_flagged_video": mid in flagged,
                "api_date": api_date,
                "meeting_name": name,
                "video_kind": kind,
                "video_id_or_url": val,
                "raw_keys": raw_keys,
            }
        )
        if kind != "none":
            videos.append(
                (path, title, api_date or (d.isoformat() if d else ""), mid, kind, val)
            )
    row["meetings_checked"] = min(len(unread), MAX_CHECKED)
    row["videos_found"] = len(videos)
    row["list_flagged_video"] = len(flagged)
    if not videos:
        row["action"] = "no_video"
        return row
    yt = [v for v in videos if v[4] == "youtube"]
    pick = yt[0] if yt else videos[0]
    path, title, d, mid, kind, val = pick
    row.update(
        action="youtube_lead" if kind == "youtube" else "external_video_candidate",
        tier=2 if kind == "youtube" else 3,
        video_kind=kind,
        video_id_or_url=val,
        meeting_url=f"https://{host}{path}",
        meeting_title=title,
        meeting_date=d,
        meeting_id=mid,
        notes=f"{len(videos)} video meetings among unread links",
    )
    return row


async def main(hosts_file, report_csv, meetings_csv, budget):
    hosts = [h.strip() for h in open(hosts_file) if h.strip()]
    done = set()
    if os.path.exists(report_csv):
        done = {r["host"] for r in csv.DictReader(open(report_csv))}
    new_report = not os.path.exists(report_csv)
    new_meet = not os.path.exists(meetings_csv)
    t0 = time.time()
    async with aiohttp.ClientSession() as session:
        with (
            open(report_csv, "a", newline="") as rf,
            open(meetings_csv, "a", newline="") as mf,
        ):
            rw = csv.DictWriter(rf, fieldnames=REPORT_FIELDS)
            mw = csv.DictWriter(mf, fieldnames=MEETING_FIELDS)
            if new_report:
                rw.writeheader()
            if new_meet:
                mw.writeheader()
            left = [h for h in hosts if h not in done]
            for i, host in enumerate(left, 1):
                if time.time() - t0 > budget:
                    print(
                        f"BUDGET reached; {len(left) - i + 1} tenants remain",
                        flush=True,
                    )
                    return
                row = await run_tenant(session, host, mw)
                rw.writerow(row)
                rf.flush()
                mf.flush()
                print(
                    f"{host}: {row['action']} checked={row['meetings_checked']} "
                    f"videos={row['videos_found']} {row['video_kind']}:{row['video_id_or_url']}",
                    flush=True,
                )
                await asyncio.sleep(1.5)
    print("DONE", flush=True)


if __name__ == "__main__":
    b = 480
    if "--budget-seconds" in sys.argv:
        b = int(sys.argv[sys.argv.index("--budget-seconds") + 1])
    asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3], b))
