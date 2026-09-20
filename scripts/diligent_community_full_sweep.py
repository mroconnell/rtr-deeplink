"""Real (not dry-run) classification sweep of the 359 real
`*.community.diligentoneplatform.com` tenant hostnames found via Wayback/
CDX (see rtr-business `research/dns_ctlog_sweep_2026-09-17/
diligent_cdx_tenant_hosts.json` -- CT-log/crt.sh can't enumerate these,
Diligent wildcards one cert per tenant tier).

Per tenant, walks its real past meetings (newest first, scraped off
`MeetingTypeList.aspx` -- CivicWeb's own adapter has no calendar-listing
API the way CivicPlus/Granicus/CivicClerk do, confirmed live 2026-09-18)
and resolves each **in-process** via `app.platforms` directly (same
pattern as `scripts/catalog_video_hosting.py`), not via a `bulk_ingest.py
--dry-run` subprocess -- confirmed live 2026-09-18 this is faster (~16s
vs ~28s for the same 12-meeting tenant) and doesn't add load to the
shared archive backend.

Per-meeting decision, in scan order (Ryan, 2026-09-18):
  tier 1 (real transcript, segments > 0)  -> STOP, this tenant's action is
                                              a real ingest of this meeting.
  tier 2 (YouTube video confirmed, segments == 0 -- known live bot-check
          outage makes this ambiguous, so it's classed as real video, not
          a reject, same as any other real tier-2) -> STOP, this tenant's
                                              action is a youtube_channel_
                                              leads.csv row for this video.
  tier 3 (video confirmed on some other platform, no transcript) -> do NOT
          stop; remember the FIRST one as a fallback and keep checking
          more of this tenant's already-scraped meetings, hoping for a
          tier 1. Only if the whole scrape (capped at MAX_CHECKED) is
          exhausted without a tier 1 or tier 2 does the fallback tier-3
          meeting become the tenant's action (queued to
          tier3_auto_transcription_queue.txt).
  none (no video at all)                  -> keep checking; if every past
                                              meeting has no video, the
                                              tenant's action is "none".

This script only CLASSIFIES and writes one results CSV -- it does not
itself ingest or touch youtube_channel_leads.csv / the tier-3 queue.
Those real, shared-state writes happen in a separate follow-up pass once
each hit has been matched to a real gov_id (see `result.jurisdiction`,
already populated by CivicWebAssetFinder's own `_extract_jurisdiction()`
-> `jurisdiction_enrich.enrich_jurisdiction_text()`), so a wrong or
missing government match can be caught by hand rather than silently
mis-attributed at 359-tenant scale.

Usage:
    python scripts/diligent_community_full_sweep.py <hosts.json> <out.csv>
"""

import asyncio
import csv
import json
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
MAX_CHECKED = 40  # bound worst-case cost for a tenant with an unusually long history


def fetch_meeting_type_list(host):
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


async def probe_tenant(host, finder):
    body, code, size = fetch_meeting_type_list(host)
    real = code == 200 and (size or 0) > 500
    row = {
        "host": host,
        "http_code": code,
        "size": size,
        "real_tenant": real,
        "meetings_found": 0,
        "meetings_checked": 0,
        "action": None,
        "tier": None,
        "url": None,
        "title": None,
        "date": None,
        "segments": None,
        "jurisdiction": None,
        "reason": None,
    }
    if not real:
        row["action"] = "not_real_tenant"
        return row

    past = parse_past_meetings(body)
    row["meetings_found"] = len(past)
    tier3_fallback = None  # (path, title, d, jurisdiction, segments, reason)

    for path, title, d in past[:MAX_CHECKED]:
        url = f"https://{host}{path}"
        row["meetings_checked"] += 1
        try:
            result = await finder.resolve(url)
        except Exception:
            continue
        tier, reason = classify(result)
        if tier == 1:
            row.update(
                action="ingest_tier1",
                tier=1,
                url=url,
                title=title,
                date=d.isoformat(),
                segments=len(result.segments),
                jurisdiction=result.jurisdiction,
                reason=reason,
            )
            return row
        if tier == 2:
            row.update(
                action="queue_tier2",
                tier=2,
                url=url,
                title=title,
                date=d.isoformat(),
                segments=0,
                jurisdiction=result.jurisdiction,
                reason=reason,
            )
            return row
        if tier == 3 and tier3_fallback is None:
            tier3_fallback = (path, title, d, result.jurisdiction, 0, reason)

    if tier3_fallback:
        path, title, d, jurisdiction, segments, reason = tier3_fallback
        row.update(
            action="queue_tier3",
            tier=3,
            url=f"https://{host}{path}",
            title=title,
            date=d.isoformat(),
            segments=segments,
            jurisdiction=jurisdiction,
            reason=reason,
        )
        return row

    row["action"] = "no_video"
    return row


async def main(hosts_json, out_csv):
    with open(hosts_json) as f:
        hosts = json.load(f)

    finder = get_finder("civicweb")
    results = []
    for i, host in enumerate(hosts, 1):
        row = await probe_tenant(host, finder)
        results.append(row)
        print(
            f"{i}/{len(hosts)} {host}: action={row['action']} tier={row['tier']} "
            f"checked={row['meetings_checked']}/{row['meetings_found']} "
            f"jurisdiction={row['jurisdiction']!r}",
            flush=True,
        )

        # Checkpoint every 10 so a stop/kill doesn't lose progress.
        if i % 10 == 0 or i == len(hosts):
            with open(out_csv, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
                w.writeheader()
                w.writerows(results)

    n = len(results)
    counts = {}
    for r in results:
        counts[r["action"]] = counts.get(r["action"], 0) + 1
    print(
        f"\nFINAL {n} tenants: "
        + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())),
        file=sys.stderr,
    )


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
