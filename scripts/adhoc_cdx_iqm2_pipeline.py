"""One-off pipeline for the 65 IQM2 tenants found via CDX scan of
mediahttp.iqm2.com (rtr-discovery/cdx-scans/iqm2_tenants.txt --
CDX_ENUMERATION_HANDOVER.md, 2026-09-06).

The handover doc's proposed shortcut -- reusing the numeric id from the
CDX-derived mp4 filename directly as the portal's own MeetingID -- was
tested against 3 real tenants (Boise, Arcata, Atlanta) here and
confirmed wrong: only Atlanta's own already-known-good id (4294, from
iqm2.py's docstring) resolved a real meeting; the CDX-derived ids (2201,
1988, 74035) all hit real pages with no meeting content, confirming the
handover's suspicion that the mp4 filename id is a different (likely
Granicus-internal) numbering scheme, not IQM2's own MeetingID.

What actually works: fetching https://{tenant}.iqm2.com/Citizens/
directly (following redirects) and scraping `Detail_Meeting.aspx?ID={n}`
links off the real static HTML -- confirmed live against several
tenants. Not every tenant's default page lists a meeting this way
(front page may show a department/board picker instead) -- those are
marked no-meeting-found and skipped rather than guessed at further.

**The single highest id on that page is usually a future meeting, not a
usable one.** Confirmed live (East Hampton Town, id=3026): the highest
id resolved with a real title but `video_warnings: ["No video found for
this meeting."]`, and the meeting's own date field was 2026-09-24 --
weeks after this was written -- meaning the front page mixes upcoming
and past meetings and the top id is often just the next one scheduled.
A same-size dry run using only the top id got a 6% usable rate (4/65);
this is why the script below resolves several of the highest ids per
tenant (most-recent-first) and keeps the first one with real content,
rather than resolving only the single highest.

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
import re
import sys
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
    "/Users/mroconnell/Documents/rtr-discovery/cdx-scans/iqm2_tenants.txt"
)
QUEUE_FILE = Path(__file__).resolve().parent / "tier3_auto_transcription_queue.txt"
REPORT_CSV = Path(__file__).resolve().parent / "iqm2_cdx_report.csv"
FIELDNAMES = [
    "tenant",
    "meeting_id",
    "url",
    "status",
    "jurisdiction",
    "segments",
    "agenda_items",
    "video_url",
    "detail",
]
_MEETING_ID_RE = re.compile(r"Detail_Meeting\.aspx\?ID=(\d+)", re.IGNORECASE)
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
MAX_CANDIDATES = 10
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


async def discover_candidate_ids(session, tenant_lower):
    url = f"https://{tenant_lower}.iqm2.com/Citizens/"
    try:
        async with session.get(
            url,
            headers={"User-Agent": UA},
            timeout=aiohttp.ClientTimeout(total=20),
            allow_redirects=True,
        ) as resp:
            if resp.status != 200:
                return []
            html = await resp.text(errors="replace")
    except Exception:
        return []
    ids = sorted({int(m) for m in _MEETING_ID_RE.findall(html)}, reverse=True)
    return ids[:MAX_CANDIDATES]


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
            tenant_lower = tenant.lower()

            candidate_ids = await discover_candidate_ids(session, tenant_lower)
            if not candidate_ids:
                row_out.update(
                    status="no-meeting-found",
                    detail="no Detail_Meeting.aspx link on /Citizens/",
                )
                writer.writerow(row_out)
                report_f.flush()
                print(f"[NO-MTG ] {tenant}")
                await asyncio.sleep(DELAY_SECONDS)
                continue

            result = None
            url = None
            last_failure = None
            for meeting_id in candidate_ids:
                candidate_url = (
                    f"https://{tenant_lower}.iqm2.com/Citizens/"
                    f"Detail_Meeting.aspx?ID={meeting_id}"
                )
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
                    row_out["meeting_id"] = str(meeting_id)
                    break
                await asyncio.sleep(DELAY_SECONDS)

            if result is None:
                # None of the candidates had usable content -- report
                # against the highest id tried, same shape as a single-
                # candidate miss.
                url = (
                    f"https://{tenant_lower}.iqm2.com/Citizens/"
                    f"Detail_Meeting.aspx?ID={candidate_ids[0]}"
                )
                row_out["meeting_id"] = str(candidate_ids[0])
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
