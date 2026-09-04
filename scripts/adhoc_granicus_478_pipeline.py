"""One-off pipeline for the 478-host Granicus backlog found 2026-09-04
(rtr-business/research/granicus_clip_urls.txt, cross-referenced against
jurisdiction_coverage.csv -- see ENUMERATION_METHODS.md). Resolves each
URL via the real adapter, ingests tier-1 (segments>0) and tier-3-agenda
(agenda_items>0) directly, queues tier-3-video-only to
tier3_auto_transcription_queue.txt, and updates jurisdiction_coverage.csv
where a resolved jurisdiction matches an existing row by normalized
name+state. No government-type filtering -- state agencies, regional
bodies, etc. are all in scope per Ryan's explicit direction.

Run from rtr-deeplink repo root with the venv active.
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

URLS_FILE = "/Users/mroconnell/Documents/rtr-business/research/granicus_478_urls.txt"
COVERAGE_CSV = "/Users/mroconnell/Documents/rtr-business/research/jurisdiction_coverage.csv"
REPORT_CSV = "/Users/mroconnell/Documents/rtr-business/research/granicus_478_report.csv"
QUEUE_FILE = Path(__file__).resolve().parent / "tier3_auto_transcription_queue.txt"
DELAY_SECONDS = 1.5
INGEST_TIMEOUT = aiohttp.ClientTimeout(total=65)

STATE_ABBR = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire",
    "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina",
    "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming", "DC": "District of Columbia",
}
_NAME_CLEAN_RE = re.compile(r"\b(city|county|town|village|borough|township|of|the)\b|[^a-z ]")


def norm_name(s):
    return re.sub(r"\s+", "", _NAME_CLEAN_RE.sub("", (s or "").lower())).strip()


def base_url():
    return os.environ.get("ARCHIVE_BASE_URL", "").rstrip("/")


def headers():
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


async def ingest(session, payload, input_url_normalized):
    body = dict(payload)
    body["input_url_normalized"] = input_url_normalized
    async with session.post(f"{base_url()}/internal/ingest", json=body,
                             headers=headers(), timeout=INGEST_TIMEOUT) as resp:
        if resp.status == 200:
            return await resp.json()
        text = await resp.text()
        raise RuntimeError(f"ingest failed ({resp.status}): {text[:300]}")


def load_coverage_index():
    with open(COVERAGE_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    index = {}
    for row in rows:
        key = (norm_name(row["city_name"]), row["state_or_province"])
        index[key] = row
    return rows, index


def match_row(index, jurisdiction):
    if not jurisdiction:
        return None
    parts = jurisdiction.rsplit(",", 1)
    if len(parts) != 2:
        return None
    name, state_part = parts[0].strip(), parts[1].strip()
    state_full = STATE_ABBR.get(state_part.upper(), state_part)
    return index.get((norm_name(name), state_full))


async def main():
    register_all_finders()
    urls = [l.strip() for l in open(URLS_FILE) if l.strip()]
    coverage_rows, coverage_index = load_coverage_index()

    results = []
    matched_count = 0

    async with aiohttp.ClientSession() as session:
        for i, url in enumerate(urls):
            row_out = {"url": url, "status": "", "jurisdiction": "", "segments": 0,
                       "agenda_items": 0, "video_url": "", "matched_row": "", "detail": ""}
            try:
                platform = detect_platform(url)
                finder = get_finder(platform)
                result = await finder.resolve(url)
            except CalendarPageError as e:
                row_out.update(status="failed", detail=f"calendar page: {e}")
                results.append(row_out)
                print(f"[FAILED ] {url}  calendar page")
                await asyncio.sleep(DELAY_SECONDS)
                continue
            except Exception as e:
                row_out.update(status="failed", detail=f"resolve raised: {e}")
                results.append(row_out)
                print(f"[FAILED ] {url}  {e}")
                await asyncio.sleep(DELAY_SECONDS)
                continue

            row_out["jurisdiction"] = result.jurisdiction or ""
            row_out["segments"] = len(result.segments)
            row_out["agenda_items"] = len(result.agenda_items)
            row_out["video_url"] = result.video_url or ""

            has_content = bool(result.segments or result.agenda_items or result.agenda_link or result.video_url)
            if not has_content:
                row_out.update(status="empty", detail="no segments/agenda/video")
                results.append(row_out)
                print(f"[EMPTY  ] {url}")
                await asyncio.sleep(DELAY_SECONDS)
                continue

            passes_client_gate = bool(result.segments or result.agenda_items or result.agenda_link)
            normalized = normalize_url(url)

            if passes_client_gate:
                try:
                    response = await ingest(session, result.model_dump(), normalized)
                    page_url = response.get("url") if response else None
                    tier = "tier1" if result.segments else "tier3-agenda"
                    row_out.update(status=f"ingested-{tier}", detail=page_url or "")
                    print(f"[INGEST ] {url}  {tier}  {page_url}")
                except Exception as e:
                    row_out.update(status="ingest-failed", detail=str(e))
                    print(f"[ING-ERR] {url}  {e}")
            else:
                with open(QUEUE_FILE, "a") as qf:
                    qf.write(url + "\n")
                row_out.update(status="queued-tier3", detail="tier3_auto_transcription_queue.txt")
                print(f"[QUEUED ] {url}  tier3 (video-only)")

            matched = match_row(coverage_index, result.jurisdiction)
            if matched:
                matched["example_meeting_url"] = url
                matched["domain"] = re.search(r"https://([^/]+)", url).group(1)
                matched["suspected_video_provider"] = "granicus"
                matched["shares_video"] = "True"
                if result.segments:
                    matched["transcribed"] = "True"
                if matched.get("reject_reason") in ("no-video-found", "resolve-failed", ""):
                    matched["reject_reason"] = ""
                matched_count += 1
                row_out["matched_row"] = f"{matched['city_name']}, {matched['state_or_province']}"

            results.append(row_out)
            if (i + 1) % 25 == 0:
                print(f"--- {i + 1}/{len(urls)} processed ---")
            await asyncio.sleep(DELAY_SECONDS)

    with open(COVERAGE_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(coverage_rows[0].keys()))
        writer.writeheader()
        writer.writerows(coverage_rows)

    with open(REPORT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        writer.writeheader()
        writer.writerows(results)

    by_status = {}
    for r in results:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    print("\n=== SUMMARY ===")
    for status, count in sorted(by_status.items(), key=lambda x: -x[1]):
        print(f"{status}: {count}")
    print(f"jurisdiction_coverage.csv rows matched/updated: {matched_count}")
    print(f"Full report: {REPORT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
