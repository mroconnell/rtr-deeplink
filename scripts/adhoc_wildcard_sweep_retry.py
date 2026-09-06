"""Retry pass over the wildcard-sweep pipeline's `resolve-failed` and
`skipped-empty` cohorts (`adhoc_wildcard_sweep_pipeline.py`, PR #743),
using one validated trick: try the *next* candidate meeting instead of
giving up after the first.

Four other tricks were considered and empirically ruled out against the
sweep's separate 105-tenant `no-url-found` cohort before building
anything here (full writeup in BACKLOG.md's standing-decisions section
and BACKLOG_DONE.md's 2026-09-06 entry) -- widening the Granicus
`view_id` range, `mode=vpodcast` as an alternate feed, guessing the
"other" Legistar slug variant against the Web API, and resolving a
tenant's bare `Calendar.aspx` page directly. None are implemented here.
The `no-url-found` cohort itself is NOT retried by this script -- every
trick above came up genuinely empty for those tenants, so a
multi-candidate retry has nothing to work with there.

For `resolve-failed` (a specific candidate 404'd/410'd) and
`skipped-empty` (a specific candidate resolved but had zero content),
this refetches the same feed/event-list and tries subsequent candidates
in order, skipping the one already known bad, until one has real content
or a small cap is hit.

Run from a checkout with the venv active:
    .venv/bin/python scripts/adhoc_wildcard_sweep_retry.py
"""

import asyncio
import csv
import html
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
import certifi
import os

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import detect_platform, get_finder, CalendarPageError  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402
from scripts.adhoc_wildcard_sweep_pipeline import (  # noqa: E402
    ingest,
    REPORT_FIELDS,
)

MAIN_REPORT_CSV = (
    Path(__file__).resolve().parent
    / "wildcard_sweep_data"
    / "wildcard_sweep_report.csv"
)
RETRY_REPORT_CSV = (
    Path(__file__).resolve().parent
    / "wildcard_sweep_data"
    / "wildcard_sweep_retry_report.csv"
)
QUEUE_FILE = Path(__file__).resolve().parent / "tier3_auto_transcription_queue.txt"

DISCOVERY_DELAY_SECONDS = 0.3
RESOLVE_DELAY_SECONDS = 1.0
HTTP_TIMEOUT = aiohttp.ClientTimeout(total=15)
MAX_CANDIDATES_TO_TRY = 6

RETRY_FIELDS = REPORT_FIELDS + ["candidate_index"]


async def granicus_candidates(session, slug, known_view_id):
    """Every real MediaPlayer.php item in the known-good view_id's
    mode=video RSS feed, in feed order."""
    url = f"https://{slug}.granicus.com/ViewPublisherRSS.php?view_id={known_view_id}&mode=video"
    try:
        async with session.get(url, timeout=HTTP_TIMEOUT) as resp:
            if resp.status != 200:
                return []
            text = await resp.text()
    except Exception:
        return []
    items = re.findall(
        r"<link>\s*(https?://[^<\s]+MediaPlayer\.php[^<\s]*)\s*</link>", text
    )
    return [html.unescape(i) for i in items]


async def legistar_candidates(session, slug):
    """Every EventInSiteURL among past events with a public video, most
    recent first (same ordering/filter as the main pipeline)."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    api_url = (
        f"https://webapi.legistar.com/v1/{slug}/events"
        f"?$filter=EventDate lt datetime'{today}'&$orderby=EventDate desc&$top=50"
    )
    try:
        async with session.get(api_url, timeout=HTTP_TIMEOUT) as resp:
            if resp.status != 200:
                return []
            events = await resp.json()
    except Exception:
        return []
    if not isinstance(events, list):
        return []
    return [
        e["EventInSiteURL"]
        for e in events
        if e.get("EventVideoStatus") == "Public" and e.get("EventInSiteURL")
    ]


def known_view_id(meeting_url):
    m = re.search(r"[?&]view_id=(\d+)", meeting_url)
    return m.group(1) if m else "1"


async def get_candidates(session, tenant_row):
    platform = tenant_row["platform"]
    slug = tenant_row["slug"]
    known_url = tenant_row["meeting_url"]
    if platform == "granicus":
        candidates = await granicus_candidates(session, slug, known_view_id(known_url))
    elif platform == "legistar":
        candidates = await legistar_candidates(session, slug)
    else:
        candidates = []
    await asyncio.sleep(DISCOVERY_DELAY_SECONDS)
    # skip the candidate already known bad/empty; keep order otherwise
    return [c for c in candidates if c != known_url][:MAX_CANDIDATES_TO_TRY]


async def try_resolve(session, meeting_url):
    """Returns (result_or_None, error_or_None)."""
    try:
        real_platform = detect_platform(meeting_url)
        finder = get_finder(real_platform)
        result = await finder.resolve(meeting_url)
        return result, None
    except CalendarPageError as e:
        return None, f"calendar page: {e}"
    except Exception as e:
        return None, f"resolve raised: {e}"


async def process_tenant(session, tenant_row, report):
    slug = tenant_row["slug"]
    platform = tenant_row["platform"]
    row_out = {field: "" for field in RETRY_FIELDS}
    row_out["slug"] = slug
    row_out["platform"] = platform

    candidates = await get_candidates(session, tenant_row)
    if not candidates:
        row_out.update(
            outcome="no-more-candidates", detail="no alternate candidate found"
        )
        report.write(row_out)
        print(f"[NO-ALT ] {platform}:{slug}")
        return

    for idx, meeting_url in enumerate(candidates):
        result, error = await try_resolve(session, meeting_url)
        await asyncio.sleep(RESOLVE_DELAY_SECONDS)
        if error:
            continue
        has_content = bool(
            result.segments
            or result.agenda_items
            or result.agenda_link
            or result.video_url
        )
        if not has_content:
            continue

        row_out["meeting_url"] = meeting_url
        row_out["candidate_index"] = str(idx)
        row_out["jurisdiction"] = result.jurisdiction or ""
        row_out["segments"] = len(result.segments)
        row_out["agenda_items"] = len(result.agenda_items)
        row_out["video_url"] = result.video_url or ""

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
                print(
                    f"[INGEST ] {platform}:{slug}  {tier}  candidate #{idx}  {page_url}"
                )
            except Exception as e:
                row_out.update(outcome="ingest-failed", detail=str(e))
                print(f"[ING-ERR] {platform}:{slug}  {e}")
        else:
            row_out["tier"] = "tier3-video-only"
            with open(QUEUE_FILE, "a") as qf:
                qf.write(meeting_url + "\n")
            row_out.update(
                outcome="queued", detail="tier3_auto_transcription_queue.txt"
            )
            print(f"[QUEUED ] {platform}:{slug}  candidate #{idx}")

        report.write(row_out)
        return

    row_out.update(
        outcome="exhausted-candidates",
        detail=f"tried {len(candidates)} alternate candidates, none had content",
    )
    report.write(row_out)
    print(f"[NO-LUCK] {platform}:{slug}  tried {len(candidates)} alternates")


def load_targets():
    with open(MAIN_REPORT_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r["outcome"] in ("resolve-failed", "skipped-empty")]


def load_done_slugs():
    if not RETRY_REPORT_CSV.exists():
        return set()
    with open(RETRY_REPORT_CSV, newline="", encoding="utf-8") as f:
        return {(row["platform"], row["slug"]) for row in csv.DictReader(f)}


class ReportWriter:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not path.exists()
        self._f = path.open("a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._f, fieldnames=RETRY_FIELDS)
        if write_header:
            self._writer.writeheader()
            self._f.flush()

    def write(self, row):
        self._writer.writerow(row)
        self._f.flush()

    def close(self):
        self._f.close()


async def main():
    register_all_finders()
    targets = load_targets()
    done = load_done_slugs()
    todo = [t for t in targets if (t["platform"], t["slug"]) not in done]

    print(
        f"{len(targets)} total targets, {len(done)} already retried, {len(todo)} to go"
    )

    report = ReportWriter(RETRY_REPORT_CSV)
    try:
        async with aiohttp.ClientSession() as session:
            for i, tenant in enumerate(todo):
                await process_tenant(session, tenant, report)
                if (i + 1) % 10 == 0:
                    print(f"--- {i + 1}/{len(todo)} processed this run ---")
    finally:
        report.close()

    with open(RETRY_REPORT_CSV, newline="", encoding="utf-8") as f:
        results = list(csv.DictReader(f))
    by_outcome = {}
    for r in results:
        by_outcome[r["outcome"]] = by_outcome.get(r["outcome"], 0) + 1
    print("\n=== RETRY SUMMARY (cumulative) ===")
    for outcome, count in sorted(by_outcome.items(), key=lambda x: -x[1]):
        print(f"outcome {outcome}: {count}")
    print(f"Full retry report: {RETRY_REPORT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
