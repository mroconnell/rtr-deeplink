"""Specify + resolve + tier + ingest/queue pipeline for the 68 school
districts found linking to a platform this project already has a real
adapter for (rtr-business/research/school_district_platform_scan_hits.csv,
ENUMERATION_METHODS.md §63). Unlike the single-platform Granicus batches
earlier, this set spans ~14 different platforms with no known meeting
URL yet -- only "this homepage links to {platform}.com somewhere".

Method per site:
1. Re-fetch the homepage, extract every real outbound link whose host
   matches one of the hit platform's domains (dedup).
2. Try resolving each candidate link directly via the real adapter
   pipeline. Most homepage links land on a tenant's calendar/listing
   page, not one specific meeting -- when that raises CalendarPageError,
   pick the candidate with the most recent parseable date (falling back
   to the first) and resolve *that* specific URL instead, one extra
   call, same "prefer the most recent real meeting" heuristic this
   file's own "Step 2's real weak spot" section already recommends.
3. Classify + route exactly like the Granicus batches: segments>0 ->
   ingest as tier1; agenda_items>0 (no segments) -> ingest as
   tier3-agenda (passes bulk_ingest.py's own client gate); video_url
   only, nothing else -> queue to tier3_auto_transcription_queue.txt,
   not ingested directly (mirrors feed_tier3_auto_transcription.py's own
   reason for existing: bulk_ingest.py's gate would silently drop these).

Run from rtr-deeplink repo root with the venv active.
"""

import asyncio
import csv
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import CalendarPageError, detect_platform, get_finder  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402

HITS_CSV = Path(
    "/Users/mroconnell/Documents/rtr-business/research/school_district_platform_scan_hits.csv"
)
REPORT_CSV = Path(
    "/Users/mroconnell/Documents/rtr-business/research/school_district_pipeline_report.csv"
)
QUEUE_FILE = Path(__file__).resolve().parent / "tier3_auto_transcription_queue.txt"
FETCH_TIMEOUT = aiohttp.ClientTimeout(total=10)
INGEST_TIMEOUT = aiohttp.ClientTimeout(total=65)
DELAY_SECONDS = 1.0
USER_AGENT = (
    "Mozilla/5.0 (compatible; rtr-deeplink research crawl; contact ryan@how-to-adu.com)"
)

PLATFORM_DOMAINS = {
    "granicus": "granicus.com",
    "legistar": "legistar.com",
    "civicplus": "civicplus.com",
    "civicclerk": "civicclerk.com",
    "primegov": "primegov.com",
    "civicweb": "civicweb.net",
    "escribe": "escribemeetings.com",
    "iqm2": "iqm2.com",
    "swagit": "swagit.com",
    "cablecast": "cablecast.tv",
    "telvue": "telvue.com",
    "champds": "champds.com",
    "novusagenda": "novusagenda.com",
    "civiclive": "civiclive.com",
}

_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)


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
        timeout=INGEST_TIMEOUT,
    ) as resp:
        if resp.status == 200:
            return await resp.json()
        text = await resp.text()
        raise RuntimeError(f"ingest failed ({resp.status}): {text[:300]}")


async def extract_platform_links(session, homepage_url, wanted_domains):
    try:
        async with session.get(
            homepage_url, timeout=FETCH_TIMEOUT, headers={"User-Agent": USER_AGENT}
        ) as resp:
            if resp.status >= 400:
                return []
            html = await resp.text(errors="replace")
    except Exception:
        return []

    found = []
    seen = set()
    for href in _HREF_RE.findall(html):
        host = urlparse(href).netloc.lower()
        if not host:
            continue
        for domain in wanted_domains:
            if domain in host and href not in seen:
                seen.add(href)
                found.append(href)
    return found


def _parse_date(d):
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(d, fmt)
        except (ValueError, TypeError):
            continue
    return None


async def resolve_with_calendar_fallback(url):
    """Returns (result, resolved_url) or (None, detail) on failure."""
    try:
        platform = detect_platform(url)
        finder = get_finder(platform)
    except Exception as e:
        return None, f"unsupported: {e}"

    try:
        result = await finder.resolve(url)
        return result, url
    except CalendarPageError as e:
        if not e.candidates:
            return None, "calendar page, no candidates"
        dated = [(c, _parse_date(c.get("date"))) for c in e.candidates]
        dated.sort(key=lambda pair: pair[1] or datetime.min, reverse=True)
        picked = dated[0][0]
        picked_url = picked["url"]
        try:
            platform2 = detect_platform(picked_url)
            finder2 = get_finder(platform2)
            result = await finder2.resolve(picked_url)
            return result, picked_url
        except Exception as e2:
            return None, f"picked candidate failed: {e2}"
    except Exception as e:
        return None, f"resolve raised: {e}"


async def process_one(session, row):
    lea_name, state, website = row["lea_name"], row["state"], row["website"]
    wanted_domains = [
        PLATFORM_DOMAINS[p]
        for p in row["platform_hits"].split(";")
        if p in PLATFORM_DOMAINS
    ]
    out = {
        "lea_name": lea_name,
        "state": state,
        "website": website,
        "platform_hits": row["platform_hits"],
        "candidate_url": "",
        "status": "",
        "segments": 0,
        "agenda_items": 0,
        "detail": "",
    }
    if not wanted_domains:
        out["status"] = "no_video_platform"  # BoardDocs-only etc.
        return out

    links = await extract_platform_links(session, website, wanted_domains)
    if not links:
        out["status"] = "no_link_found_on_recheck"
        return out

    for link in links:
        result, resolved_or_detail = await resolve_with_calendar_fallback(link)
        if result is not None:
            out["candidate_url"] = resolved_or_detail
            out["segments"] = len(result.segments)
            out["agenda_items"] = len(result.agenda_items)
            has_content = bool(
                result.segments
                or result.agenda_items
                or result.agenda_link
                or result.video_url
            )
            if not has_content:
                out["status"] = "empty"
                continue
            passes_gate = bool(
                result.segments or result.agenda_items or result.agenda_link
            )
            normalized = normalize_url(resolved_or_detail)
            if passes_gate:
                try:
                    response = await ingest(session, result.model_dump(), normalized)
                    page_url = response.get("url") if response else None
                    tier = "tier1" if result.segments else "tier3-agenda"
                    out["status"] = f"ingested-{tier}"
                    out["detail"] = page_url or ""
                except Exception as e:
                    out["status"] = "ingest-failed"
                    out["detail"] = str(e)[:200]
            else:
                with open(QUEUE_FILE, "a") as qf:
                    qf.write(resolved_or_detail + "\n")
                out["status"] = "queued-tier3"
                out["detail"] = "tier3_auto_transcription_queue.txt"
            return out
        out["detail"] = resolved_or_detail
    out["status"] = "no_resolvable_link"
    return out


async def main():
    register_all_finders()
    with open(HITS_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"Processing {len(rows)} school district hits...\n")
    results = []
    async with aiohttp.ClientSession() as session:
        for i, row in enumerate(rows):
            out = await process_one(session, row)
            results.append(out)
            print(
                f"[{out['status']:25s}] {out['lea_name']} ({out['state']})  {out['detail']}"
            )
            if i < len(rows) - 1:
                await asyncio.sleep(DELAY_SECONDS)

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
    print(f"Full report: {REPORT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
