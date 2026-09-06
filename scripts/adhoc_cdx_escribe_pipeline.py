"""One-off pipeline for the 59 eScribe tenants found via CDX scan of
cdn1.isilive.ca (rtr-discovery/cdx-scans/escribe_tenants.txt --
CDX_ENUMERATION_HANDOVER.md, 2026-09-06). web.archive.org's CDX was down
when the handover doc was written; confirmed back up 2026-09-06 and
scanned then. Two real path shapes exist on that CDN
(`/vod/_definst_/mp4:{client_id}/...` -- the historically-crawled one,
59 tenants -- and `/nospace/hls/{client_id}/...` -- only 2 tenants,
`calgary`/`whiterock`, likely just-happened-to-get-crawled live
recordings) but both use the same `{client_id}` slug, so one tenant list
covers both.

Two real discovery steps needed, neither given by the CDX data itself:

1. **client_id -> portal domain.** The isilive CDN slug doesn't always
   match the eScribe portal's own subdomain scheme. Confirmed live: the
   `pub-{client_id}.escribemeetings.com` shape (escribe.py's
   `_SUBDOMAIN_RE`) works for 6/7 tenants spot-checked (calgary,
   peelregion, hamilton, ottawa, tdsb, burnaby); the bare
   `{client_id}.escribemeetings.com` shape 403s for all of those (a
   real, different tenant, not just a redirect -- see escribe.py's own
   module comment on why `_NO_PREFIX_SUBDOMAIN_RE` has to stay narrow).
   `whiterock` resolved on neither shape at all (DNS NXDOMAIN) --
   consistent with the ~20% "moved off this platform since the CDX
   crawl" rate seen on Granicus. This script tries `pub-{id}` first,
   falls back to bare `{id}`, and marks a tenant no-portal-found if
   neither responds.

2. **portal domain -> a real meeting.** The static home page's own
   `Meeting.aspx?Id={guid}` links turned out unreliable two different
   ways, confirmed live: some tenants (Peel Region, Ottawa, Burnaby,
   TDSB) render the meeting list entirely client-side via a Syncfusion/
   fullcalendar widget with no static links in the HTML at all -- a
   plain fetch sees literal `href='/Meeting.aspx?Id='` with the guid
   filled in by JS after load; others (Calgary, Hamilton) do have real
   static links, but every one of them was an *upcoming* meeting with
   no recording yet (the same "front-page-only lists what's next" trap
   documented in adhoc_cdx_iqm2_pipeline.py) -- a first pass using this
   approach got a 0/59 usable rate.

   What actually works: the same calendar widget calls a plain JSON
   ASP.NET page-method the page itself uses,
   `POST {domain}/MeetingsCalendarView.aspx/GetCalendarMeetings` with
   body `{"calendarStartDate": "YYYY-MM-DD", "calendarEndDate":
   "YYYY-MM-DD"}` -- no auth, no per-tenant meeting-type id needed
   (a *different* page-method, `PastMeetings`, does need one, and
   guessing small integers for it returned real 200s with `TotalCount:
   0` every time -- not worth chasing further). Confirmed live on Peel
   Region and Hamilton: real past meetings, each carrying a
   `MeetingDocumentLink` list where individual documents (agenda,
   minutes, video) each carry their own `HasVideo` boolean -- filtering
   to meetings where at least one document has `HasVideo: true` finds a
   genuinely-recorded past meeting directly, no blind multi-candidate
   trial needed. `LOOKBACK_DAYS` sets how far back the query window
   goes; a tenant with infrequent meetings may need it widened.

Resolves each discovered URL via the real adapter, ingests tier-1
(segments>0) and tier-3-agenda (agenda_items>0) directly, queues
tier-3-video-only to tier3_auto_transcription_queue.txt. Resumable: a
report CSV is flushed after every tenant, and a completed tenant (any
non-error status) is skipped on restart.

Run from rtr-deeplink repo root with the shared venv active. Set
DRY_RUN=1 to validate without ingesting. ARCHIVE_BASE_URL /
ARCHIVE_INGEST_TOKEN come from .env via cwd-walk -- confirmed pointed at
production before running for real.
"""

import asyncio
import csv
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import aiohttp
import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import detect_platform, get_finder, CalendarPageError  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402

TENANTS_FILE = Path(
    "/Users/mroconnell/Documents/rtr-discovery/cdx-scans/escribe_tenants.txt"
)
QUEUE_FILE = Path(__file__).resolve().parent / "tier3_auto_transcription_queue.txt"
REPORT_CSV = Path(__file__).resolve().parent / "escribe_cdx_report.csv"
FIELDNAMES = [
    "tenant",
    "portal_domain",
    "meeting_id",
    "url",
    "status",
    "jurisdiction",
    "segments",
    "agenda_items",
    "video_url",
    "detail",
]
MAX_CANDIDATES = 8
LOOKBACK_DAYS = 120
DELAY_SECONDS = 1.5
DRY_RUN = os.environ.get("DRY_RUN") == "1"


def base_url():
    return os.environ.get("ARCHIVE_BASE_URL", "").rstrip("/")


def headers():
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


async def ingest(session, payload, input_url_normalized):
    body = dict(payload)
    body["input_url_normalized"] = input_url_normalized
    async with session.post(
        f"{base_url()}/internal/ingest",
        json=body,
        headers=headers(),
        timeout=aiohttp.ClientTimeout(total=65),
    ) as resp:
        if resp.status == 200:
            return await resp.json()
        text = await resp.text()
        raise RuntimeError(f"ingest failed ({resp.status}): {text[:300]}")


async def find_portal_domain(session, client_id):
    for domain in (
        f"pub-{client_id}.escribemeetings.com",
        f"{client_id}.escribemeetings.com",
    ):
        try:
            async with session.get(
                f"https://{domain}/",
                timeout=aiohttp.ClientTimeout(total=15),
                allow_redirects=True,
            ) as resp:
                if resp.status == 200:
                    return domain
        except Exception:
            continue
    return None


async def discover_candidate_ids(session, domain):
    end = date.today()
    start = end - timedelta(days=LOOKBACK_DAYS)
    try:
        async with session.post(
            f"https://{domain}/MeetingsCalendarView.aspx/GetCalendarMeetings",
            json={
                "calendarStartDate": start.isoformat(),
                "calendarEndDate": end.isoformat(),
            },
            timeout=aiohttp.ClientTimeout(total=20),
        ) as resp:
            if resp.status != 200:
                return []
            data = await resp.json(content_type=None)
    except Exception:
        return []

    meetings = data.get("d") or []
    # Most recent first, and only meetings where at least one document
    # (agenda/minutes/video) is flagged HasVideo -- the calendar API
    # exposes this directly, so no blind multi-candidate resolve trial
    # is needed the way IQM2's integer-id listing required.
    with_video = [
        m
        for m in meetings
        if any(d.get("HasVideo") for d in (m.get("MeetingDocumentLink") or []))
    ]
    with_video.sort(key=lambda m: m.get("StartDate") or "", reverse=True)
    return [m["ID"] for m in with_video[:MAX_CANDIDATES] if m.get("ID")]


def load_done(report_path):
    if not report_path.exists():
        return {}
    with open(report_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {r["tenant"]: r for r in rows if r.get("status") not in ("", None)}


async def main():
    register_all_finders()
    tenants = [line.strip() for line in open(TENANTS_FILE) if line.strip()]
    done = load_done(REPORT_CSV)
    print(f"{len(tenants)} tenants total, {len(done)} already processed")

    write_header = not REPORT_CSV.exists()
    report_f = open(REPORT_CSV, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(report_f, fieldnames=FIELDNAMES)
    if write_header:
        writer.writeheader()
        report_f.flush()

    async with aiohttp.ClientSession() as session:
        for i, tenant in enumerate(tenants):
            if tenant in done:
                continue

            row_out = {k: "" for k in FIELDNAMES}
            row_out["tenant"] = tenant

            domain = await find_portal_domain(session, tenant)
            if not domain:
                row_out.update(
                    status="no-portal-found",
                    detail="neither pub-{id} nor {id}.escribemeetings.com responded",
                )
                writer.writerow(row_out)
                report_f.flush()
                print(f"[NO-PRTL] {tenant}")
                await asyncio.sleep(DELAY_SECONDS)
                continue
            row_out["portal_domain"] = domain

            candidate_ids = await discover_candidate_ids(session, domain)
            if not candidate_ids:
                row_out.update(
                    status="no-meeting-found",
                    detail="no HasVideo meeting in the last "
                    f"{LOOKBACK_DAYS} days via GetCalendarMeetings",
                )
                writer.writerow(row_out)
                report_f.flush()
                print(f"[NO-MTG ] {tenant}  {domain}")
                await asyncio.sleep(DELAY_SECONDS)
                continue

            result = None
            url = None
            last_failure = None
            for guid in candidate_ids:
                candidate_url = f"https://{domain}/Meeting.aspx?Id={guid}"
                try:
                    platform = detect_platform(candidate_url)
                    finder = get_finder(platform)
                    candidate_result = await finder.resolve(candidate_url)
                except CalendarPageError as e:
                    last_failure = f"calendar page: {e}"
                    await asyncio.sleep(DELAY_SECONDS)
                    continue
                except Exception as e:
                    last_failure = f"resolve raised: {e}"
                    await asyncio.sleep(DELAY_SECONDS)
                    continue

                has_content = bool(
                    candidate_result.segments
                    or candidate_result.agenda_items
                    or candidate_result.agenda_link
                    or candidate_result.video_url
                )
                if has_content:
                    result = candidate_result
                    url = candidate_url
                    row_out["meeting_id"] = guid
                    break
                await asyncio.sleep(DELAY_SECONDS)

            if result is None:
                url = f"https://{domain}/Meeting.aspx?Id={candidate_ids[0]}"
                row_out["meeting_id"] = candidate_ids[0]
                row_out["url"] = url
                row_out.update(
                    status="empty",
                    detail=last_failure or "no segments/agenda/video in any candidate",
                )
                writer.writerow(row_out)
                report_f.flush()
                print(f"[EMPTY  ] {tenant}  tried {len(candidate_ids)} candidates")
                continue

            row_out["url"] = url
            row_out["jurisdiction"] = result.jurisdiction or ""
            row_out["segments"] = len(result.segments)
            row_out["agenda_items"] = len(result.agenda_items)
            row_out["video_url"] = result.video_url or ""

            passes_client_gate = bool(
                result.segments or result.agenda_items or result.agenda_link
            )
            normalized = normalize_url(url)

            if DRY_RUN:
                tier = (
                    "tier1"
                    if result.segments
                    else ("tier3-agenda" if passes_client_gate else "tier3-video-only")
                )
                row_out.update(status=f"dry-run-{tier}", detail="")
                print(
                    f"[DRYRUN ] {tenant}  {url}  {tier}  jurisdiction={result.jurisdiction}"
                )
            elif passes_client_gate:
                try:
                    response = await ingest(session, result.model_dump(), normalized)
                    page_url = response.get("url") if response else None
                    tier = "tier1" if result.segments else "tier3-agenda"
                    row_out.update(status=f"ingested-{tier}", detail=page_url or "")
                    print(f"[INGEST ] {tenant}  {url}  {tier}  {page_url}")
                except Exception as e:
                    row_out.update(status="ingest-failed", detail=str(e))
                    print(f"[ING-ERR] {tenant}  {url}  {e}")
            else:
                with open(QUEUE_FILE, "a") as qf:
                    qf.write(url + "\n")
                row_out.update(
                    status="queued-tier3", detail="tier3_auto_transcription_queue.txt"
                )
                print(f"[QUEUED ] {tenant}  {url}  tier3 (video-only)")

            writer.writerow(row_out)
            report_f.flush()
            if (i + 1) % 10 == 0:
                print(f"--- {i + 1}/{len(tenants)} processed ---")
            await asyncio.sleep(DELAY_SECONDS)

    report_f.close()

    done = load_done(REPORT_CSV)
    by_status = {}
    for r in done.values():
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    print("\n=== SUMMARY ===")
    for status, count in sorted(by_status.items(), key=lambda x: -x[1]):
        print(f"{status}: {count}")
    print(f"Full report: {REPORT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
