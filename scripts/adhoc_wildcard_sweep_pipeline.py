"""One-off pipeline for the 350 new Granicus/Legistar tenants confirmed by
the full-population HTTP wildcard-substitute sweep (rtr-discovery PR #3,
squash commit cc2504e, wildcard-sweep/wildcard_http_pilot_hits.csv). That
sweep only confirmed each tenant *exists* (an HTTP signature check) -- it
never found, resolved, or tiered a single real meeting. This script does
that: for each tenant, find one real current meeting URL (Granicus via
its RSS enumeration trick; Legistar via its real Web API, filtered to
EventVideoStatus == "Public"), resolve it through the real adapter,
classify by tier, and ingest tier1/tier3-agenda directly or queue
tier3-video-only for later auto-transcription.

Do NOT trust hits.csv's own name/state columns for jurisdiction identity
-- ~60% of them are bare-name slug guesses and a spot-check found most
misattributed. Identity comes only from what the real adapter resolves,
which (as of rtr-deeplink PR #742) can recover a missing state from the
meeting's real street address or delegated video title.

Run from a checkout with the venv active:
    .venv/bin/python scripts/adhoc_wildcard_sweep_pipeline.py
"""

import asyncio
import csv
import html
import os
import re
import sys
from datetime import datetime, timezone
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

HITS_CSV = (
    Path(__file__).resolve().parent
    / "wildcard_sweep_data"
    / "wildcard_http_pilot_hits.csv"
)
REPORT_CSV = (
    Path(__file__).resolve().parent
    / "wildcard_sweep_data"
    / "wildcard_sweep_report.csv"
)
QUEUE_FILE = Path(__file__).resolve().parent / "tier3_auto_transcription_queue.txt"

DISCOVERY_DELAY_SECONDS = 0.5
RESOLVE_DELAY_SECONDS = 1.5
INGEST_TIMEOUT = aiohttp.ClientTimeout(total=65)
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=20)

REPORT_FIELDS = [
    "slug",
    "platform",
    "meeting_url",
    "tier",
    "outcome",
    "jurisdiction",
    "segments",
    "agenda_items",
    "video_url",
    "detail",
]


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


async def find_granicus_url(session, slug):
    """Try view_id 1-3's RSS video feed; return the first item's real
    MediaPlayer.php link, or None."""
    for view_id in (1, 2, 3):
        url = f"https://{slug}.granicus.com/ViewPublisherRSS.php?view_id={view_id}&mode=video"
        try:
            async with session.get(url, timeout=HTTP_TIMEOUT) as resp:
                if resp.status != 200:
                    await asyncio.sleep(DISCOVERY_DELAY_SECONDS)
                    continue
                text = await resp.text()
        except Exception:
            await asyncio.sleep(DISCOVERY_DELAY_SECONDS)
            continue
        m = re.search(
            r"<link>\s*(https?://[^<\s]+MediaPlayer\.php[^<\s]*)\s*</link>", text
        )
        await asyncio.sleep(DISCOVERY_DELAY_SECONDS)
        if m:
            return html.unescape(m.group(1))
    return None


async def find_legistar_url(session, slug):
    """Query Legistar's real Web API for the most recent past event with
    a public video; return its EventInSiteURL, or None."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    api_url = (
        f"https://webapi.legistar.com/v1/{slug}/events"
        f"?$filter=EventDate lt datetime'{today}'&$orderby=EventDate desc&$top=50"
    )
    try:
        async with session.get(api_url, timeout=HTTP_TIMEOUT) as resp:
            await asyncio.sleep(DISCOVERY_DELAY_SECONDS)
            if resp.status != 200:
                return None
            try:
                events = await resp.json()
            except Exception:
                return None
    except Exception:
        return None
    if not isinstance(events, list):
        return None
    for event in events:
        if event.get("EventVideoStatus") == "Public" and event.get("EventInSiteURL"):
            return event["EventInSiteURL"]
    return None


async def find_companion_granicus_url(session, slug):
    """Some Legistar tenants have a same-base-slug Granicus domain that
    actually carries the video (confirmed this session for several
    otherwise-stuck Legistar tenants)."""
    return await find_granicus_url(session, slug)


async def discover_meeting_url(session, platform, slug):
    if platform == "granicus":
        url = await find_granicus_url(session, slug)
        if url:
            return url, ""
        return None, "no valid view_id 1-3 on Granicus RSS"
    elif platform == "legistar":
        url = await find_legistar_url(session, slug)
        if url:
            return url, ""
        companion = await find_companion_granicus_url(session, slug)
        if companion:
            return companion, "found via companion Granicus domain"
        return None, "no public-video event via Web API; no companion Granicus domain"
    return None, f"unknown platform {platform}"


def load_tenants():
    with open(HITS_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    # de-dupe by (platform, slug) -- hits.csv can list the same slug under
    # more than one source table
    seen = set()
    tenants = []
    for row in rows:
        key = (row["platform"], row["slug"])
        if key in seen:
            continue
        seen.add(key)
        tenants.append(row)
    return tenants


def load_done_slugs():
    if not REPORT_CSV.exists():
        return set()
    with open(REPORT_CSV, newline="", encoding="utf-8") as f:
        return {(row["platform"], row["slug"]) for row in csv.DictReader(f)}


class ReportWriter:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not path.exists()
        self._f = path.open("a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._f, fieldnames=REPORT_FIELDS)
        if write_header:
            self._writer.writeheader()
            self._f.flush()

    def write(self, row):
        self._writer.writerow(row)
        self._f.flush()

    def close(self):
        self._f.close()


async def process_tenant(session, tenant, report):
    platform_hint = tenant["platform"]
    slug = tenant["slug"]
    row_out = {field: "" for field in REPORT_FIELDS}
    row_out["slug"] = slug
    row_out["platform"] = platform_hint

    meeting_url, discover_detail = await discover_meeting_url(
        session, platform_hint, slug
    )
    if not meeting_url:
        row_out.update(outcome="no-url-found", detail=discover_detail)
        report.write(row_out)
        print(f"[NO-URL ] {platform_hint}:{slug}  {discover_detail}")
        return

    row_out["meeting_url"] = meeting_url

    try:
        real_platform = detect_platform(meeting_url)
        finder = get_finder(real_platform)
        result = await finder.resolve(meeting_url)
    except CalendarPageError as e:
        row_out.update(outcome="resolve-failed", detail=f"calendar page: {e}")
        report.write(row_out)
        print(f"[FAILED ] {platform_hint}:{slug}  calendar page")
        await asyncio.sleep(RESOLVE_DELAY_SECONDS)
        return
    except Exception as e:
        row_out.update(outcome="resolve-failed", detail=f"resolve raised: {e}")
        report.write(row_out)
        print(f"[FAILED ] {platform_hint}:{slug}  {e}")
        await asyncio.sleep(RESOLVE_DELAY_SECONDS)
        return

    row_out["jurisdiction"] = result.jurisdiction or ""
    row_out["segments"] = len(result.segments)
    row_out["agenda_items"] = len(result.agenda_items)
    row_out["video_url"] = result.video_url or ""

    has_content = bool(
        result.segments or result.agenda_items or result.agenda_link or result.video_url
    )
    if not has_content:
        row_out.update(
            tier="none", outcome="skipped-empty", detail="no segments/agenda/video"
        )
        report.write(row_out)
        print(f"[EMPTY  ] {platform_hint}:{slug}")
        await asyncio.sleep(RESOLVE_DELAY_SECONDS)
        return

    passes_client_gate = bool(
        result.segments or result.agenda_items or result.agenda_link
    )
    normalized = normalize_url(meeting_url)

    if passes_client_gate:
        tier = "tier1" if result.segments else "tier3-agenda"
        row_out["tier"] = tier
        try:
            response = await ingest(session, result.model_dump(), normalized)
            page_url = response.get("url") if response else None
            row_out.update(outcome="ingested", detail=page_url or "")
            print(f"[INGEST ] {platform_hint}:{slug}  {tier}  {page_url}")
        except Exception as e:
            row_out.update(outcome="ingest-failed", detail=str(e))
            print(f"[ING-ERR] {platform_hint}:{slug}  {e}")
    else:
        row_out["tier"] = "tier3-video-only"
        with open(QUEUE_FILE, "a") as qf:
            qf.write(meeting_url + "\n")
        row_out.update(outcome="queued", detail="tier3_auto_transcription_queue.txt")
        print(f"[QUEUED ] {platform_hint}:{slug}  tier3-video-only")

    report.write(row_out)
    await asyncio.sleep(RESOLVE_DELAY_SECONDS)


async def main():
    register_all_finders()
    tenants = load_tenants()
    done = load_done_slugs()
    todo = [t for t in tenants if (t["platform"], t["slug"]) not in done]

    print(
        f"{len(tenants)} total tenants, {len(done)} already processed, {len(todo)} to go"
    )

    report = ReportWriter(REPORT_CSV)
    try:
        async with aiohttp.ClientSession() as session:
            for i, tenant in enumerate(todo):
                await process_tenant(session, tenant, report)
                if (i + 1) % 25 == 0:
                    print(f"--- {i + 1}/{len(todo)} processed this run ---")
    finally:
        report.close()

    with open(REPORT_CSV, newline="", encoding="utf-8") as f:
        results = list(csv.DictReader(f))
    by_outcome = {}
    by_tier = {}
    for r in results:
        by_outcome[r["outcome"]] = by_outcome.get(r["outcome"], 0) + 1
        if r["tier"]:
            by_tier[r["tier"]] = by_tier.get(r["tier"], 0) + 1
    print("\n=== SUMMARY (cumulative across all runs) ===")
    for outcome, count in sorted(by_outcome.items(), key=lambda x: -x[1]):
        print(f"outcome {outcome}: {count}")
    for tier, count in sorted(by_tier.items(), key=lambda x: -x[1]):
        print(f"tier {tier}: {count}")
    print(f"Full report: {REPORT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
