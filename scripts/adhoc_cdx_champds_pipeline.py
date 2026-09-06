"""One-off pipeline for the 48 ChampDS tenants found via CDX scan of
play.champds.com (rtr-discovery/cdx-scans/champds_tenants.txt --
CDX_ENUMERATION_HANDOVER.md, 2026-09-06). No per-tenant example event URL
came out of the CDX scan (only bare tenant slugs), and
web.archive.org/cdx was down at the time this was written, so this script
discovers a usable event ID itself: playapi.champds.com/{tenant}/event/{id}
returns HTTP 200 for *any* id (even ones that don't exist), but the JSON
body's Event.EventTitle is null/absent for a non-existent id -- probe a
handful of ids and take the highest one with a real title.

Resolves each discovered URL via the real adapter, ingests tier-1
(segments>0) and tier-3-agenda (agenda_items>0) directly, queues
tier-3-video-only to tier3_auto_transcription_queue.txt. Resumable: a
report CSV is flushed after every tenant, and a completed tenant (any
non-error status) is skipped on restart.

Run from rtr-deeplink repo root with the shared venv active:
    source ../rtr-deeplink/.venv/bin/activate  # or wherever .venv lives
    DATABASE_URL=... python scripts/adhoc_cdx_champds_pipeline.py
(ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN come from .env via cwd-walk --
confirmed pointed at production before running for real.)
"""

import asyncio
import csv
import os
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
    "/Users/mroconnell/Documents/rtr-discovery/cdx-scans/champds_tenants.txt"
)
QUEUE_FILE = Path(__file__).resolve().parent / "tier3_auto_transcription_queue.txt"
REPORT_CSV = Path(__file__).resolve().parent / "champds_cdx_report.csv"
FIELDNAMES = [
    "tenant",
    "event_id",
    "url",
    "status",
    "jurisdiction",
    "segments",
    "agenda_items",
    "video_url",
    "detail",
]
PROBE_IDS = [50, 200, 500, 1000, 1500, 2500, 4000, 6000, 8000, 10000]
DELAY_SECONDS = 0.3
RESOLVE_DELAY_SECONDS = 1.5
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


async def probe_event_valid(session, tenant, event_id):
    url = f"https://playapi.champds.com/{tenant}/event/{event_id}"
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
            if resp.status != 200:
                return False
            data = await resp.json(content_type=None)
    except Exception:
        return False
    title = (data or {}).get("Event", {}).get("EventTitle")
    return bool(title)


async def discover_event_id(session, tenant):
    best = None
    for event_id in PROBE_IDS:
        if await probe_event_valid(session, tenant, event_id):
            best = event_id
        await asyncio.sleep(DELAY_SECONDS)
    return best


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

            event_id = await discover_event_id(session, tenant)
            if not event_id:
                row_out.update(
                    status="no-event-found", detail="no valid id in probe set"
                )
                writer.writerow(row_out)
                report_f.flush()
                print(f"[NO-EVT ] {tenant}")
                continue

            url = f"https://play.champds.com/{tenant}/event/{event_id}"
            row_out["event_id"] = str(event_id)
            row_out["url"] = url

            try:
                platform = detect_platform(url)
                finder = get_finder(platform)
                result = await finder.resolve(url)
            except CalendarPageError as e:
                row_out.update(status="failed", detail=f"calendar page: {e}")
                writer.writerow(row_out)
                report_f.flush()
                print(f"[FAILED ] {tenant}  calendar page")
                await asyncio.sleep(RESOLVE_DELAY_SECONDS)
                continue
            except Exception as e:
                row_out.update(status="failed", detail=f"resolve raised: {e}")
                writer.writerow(row_out)
                report_f.flush()
                print(f"[FAILED ] {tenant}  {e}")
                await asyncio.sleep(RESOLVE_DELAY_SECONDS)
                continue

            row_out["jurisdiction"] = result.jurisdiction or ""
            row_out["segments"] = len(result.segments)
            row_out["agenda_items"] = len(result.agenda_items)
            row_out["video_url"] = result.video_url or ""

            has_content = bool(
                result.segments
                or result.agenda_items
                or result.agenda_link
                or result.video_url
            )
            if not has_content:
                row_out.update(status="empty", detail="no segments/agenda/video")
                writer.writerow(row_out)
                report_f.flush()
                print(f"[EMPTY  ] {tenant}  {url}")
                await asyncio.sleep(RESOLVE_DELAY_SECONDS)
                continue

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
            await asyncio.sleep(RESOLVE_DELAY_SECONDS)

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
