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

TODAY = date.today()
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
# WO-914 (2026-09-20): the original regex only read a link whose text ended
# "Mon D YYYY", which silently dropped every other title shape (94 of 257
# "no video" tenants carried such links). Now every meeting link on the list
# page is a candidate; the date in its text is only used to order them and
# to skip meetings still in the future. A link whose text has no readable
# date is still checked (it sorts after the dated ones, highest Id first).
LIST_LINK_RE = re.compile(
    r'<a class="list-link" href="(/Portal/MeetingInformation\.aspx\?Id=(\d+))">'
    r"([^<]*)</a>"
)
# The meeting-type heading is itself a link to that type's latest meeting; on
# a type with no separate list row it is the only link to that meeting.
TYPE_LINK_RE = re.compile(
    r'<a href="(/Portal/MeetingInformation\.aspx\?Id=(\d+))"[^>]*'
    r'class="meeting-type-item-title"[^>]*>([^<]*)</a>'
)
MONTH_NAMES = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
# Real shapes seen on the 94 tenants: "September 14, 2026", "Sep 15 2026",
# "SEPTEMBER 10 2026", "Mar 27, 2026", "Tuesday, October 21, 2025",
# "9/8/2026", "09/08/26", "8/10/2026".
_NAMED_DATE_RE = re.compile(
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?,?\s+(\d{1,2}),?\s+(\d{4})\b",
    re.IGNORECASE,
)
_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b")
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


def extract_link_date(text):
    """Best-effort date from a meeting link's text (last date in the text),
    or None. Never raises."""
    found = None
    for m in _NAMED_DATE_RE.finditer(text):
        try:
            found = date(
                int(m.group(3)), MONTH_NAMES[m.group(1).lower()], int(m.group(2))
            )
        except ValueError:
            continue
    for m in _NUMERIC_DATE_RE.finditer(text):
        yr = int(m.group(3))
        if yr < 100:
            yr += 2000
        try:
            found = date(yr, int(m.group(1)), int(m.group(2)))
        except ValueError:
            continue
    return found


def parse_past_meetings(html, today=None):
    """Every meeting link on a MeetingTypeList page, newest first.

    Returns (path, title, date_or_None). A dated link in the future is
    skipped; an undated link is kept and sorts after the dated ones, highest
    meeting Id first (Ids rise with time on the real tenants checked)."""
    today = today or TODAY
    seen = set()
    dated, undated = [], []
    for m in list(LIST_LINK_RE.finditer(html)) + list(TYPE_LINK_RE.finditer(html)):
        path, meeting_id, title = m.group(1), int(m.group(2)), m.group(3)
        if path in seen:
            continue
        seen.add(path)
        title = title.strip()
        d = extract_link_date(title)
        if d is None:
            undated.append((meeting_id, path, title))
        elif d <= today:
            dated.append((d, path, title))
    dated.sort(key=lambda t: t[0], reverse=True)
    undated.sort(key=lambda t: t[0], reverse=True)
    return [(p, t, d) for d, p, t in dated] + [(p, t, None) for _, p, t in undated]


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
                date=d.isoformat() if d else None,
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
                date=d.isoformat() if d else None,
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
            date=d.isoformat() if d else None,
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
