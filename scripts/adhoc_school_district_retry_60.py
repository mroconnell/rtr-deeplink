"""Retry pass over the 60 school-district failures from
adhoc_school_district_pipeline.py (rtr-business/research/
school_district_pipeline_report.csv, ENUMERATION_METHODS.md §63) --
this time using each platform's own real per-tenant listing method
instead of a single homepage-extracted link + CalendarPageError
fallback.

Only platforms with an established, already-used listing method in this
codebase are attempted -- no speculative new adapter logic:

- Granicus: ViewPublisherRSS.php?mode=video, same method as §59/§62,
  swept over view_id 1-10 (real view_ids are unguessable per §50d, a
  homepage almost never states one, so a range is the only option here).
- CivicPlus: hit /AgendaCenter directly on the known real subdomain --
  the established "CivicPlus flip" (§53), more reliable than whatever
  arbitrary civicplus.com sub-path the homepage happened to link to.
- CivicClerk: the tenant's own Events OData API
  (scripts/find_tier3_short_meeting_substitutes.py's cc_list_past_events
  pattern), newest-first.
- Legistar: webapi.legistar.com's public OData events endpoint, same
  pattern.
- PrimeGov: GetArchivedMeetingYears -> ListArchivedMeetings?year=YYYY,
  same method §33 already used.

IQM2, Cablecast, ChampDS, Swagit, TelVue, eScribe, NovusAgenda, CivicWeb,
and CivicLive are NOT retried here -- no per-tenant listing method exists
in this codebase for any of them (confirmed by grep, not assumed), and
building one on the fly for 1-6 rows each would be speculative adapter
work, not a research script. Reported as `no_enumeration_method`.

Run from rtr-deeplink repo root with the venv active.
"""

import asyncio
import csv
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import (  # noqa: E402
    CIVICPLUS_CORPORATE_HOSTS,
    CalendarPageError,
    detect_platform,
    get_finder,
)
from app.utils.url_normalize import normalize_url  # noqa: E402

REPORT_CSV = Path(
    "/Users/mroconnell/Documents/rtr-business/research/school_district_pipeline_report.csv"
)
OUT_CSV = Path(
    "/Users/mroconnell/Documents/rtr-business/research/school_district_retry_60_report.csv"
)
QUEUE_FILE = Path(__file__).resolve().parent / "tier3_auto_transcription_queue.txt"
FETCH_TIMEOUT = aiohttp.ClientTimeout(total=10)
INGEST_TIMEOUT = aiohttp.ClientTimeout(total=65)
DELAY_SECONDS = 0.8

ENUMERABLE = {"granicus", "civicplus", "civicclerk", "legistar", "primegov"}

_JUNK_TITLE_RE = re.compile(r"\btest\b|\btraining\b", re.IGNORECASE)
_PUBDATE_PARTS_RE = re.compile(
    r"<gran:pubDateParts\b[^>]*yr=['\"](\d+)['\"][^>]*mo=['\"](\d+)['\"][^>]*day=['\"](\d+)['\"]"
)
_ITEM_RE = re.compile(r"<item>((?:(?!</item>).)*?)</item>", re.DOTALL)
_TITLE_RE = re.compile(r"<title>([^<]*)</title>")
_LINK_RE = re.compile(r"<link>([^<]*clip_id=\d+[^<]*)</link>")
_CLIP_ID_RE = re.compile(r"clip_id=(\d+)")


def base_url():
    return os.environ.get("ARCHIVE_BASE_URL", "").rstrip("/")


def ingest_headers():
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


async def ingest(session, payload, input_url_normalized):
    body = dict(payload)
    body["input_url_normalized"] = input_url_normalized
    async with session.post(
        f"{base_url()}/internal/ingest",
        json=body,
        headers=ingest_headers(),
        timeout=INGEST_TIMEOUT,
    ) as resp:
        if resp.status == 200:
            return await resp.json()
        text = await resp.text()
        raise RuntimeError(f"ingest failed ({resp.status}): {text[:300]}")


async def _get_json(session, url):
    async with session.get(url, timeout=FETCH_TIMEOUT) as resp:
        resp.raise_for_status()
        return await resp.json(content_type=None)


def _parse_generic_date(d):
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(d, fmt)
        except (ValueError, TypeError):
            continue
    return None


def _odata_rows(payload):
    if isinstance(payload, dict):
        return payload.get("value") or []
    return payload or []


def _pick_best_granicus_item(xml):
    candidates = []
    for m in _ITEM_RE.finditer(xml):
        item_xml = m.group(1)
        link_m = _LINK_RE.search(item_xml)
        date_m = _PUBDATE_PARTS_RE.search(item_xml)
        if not link_m or not date_m:
            continue
        title_m = _TITLE_RE.search(item_xml)
        title = title_m.group(1).strip() if title_m else ""
        clip_id = _CLIP_ID_RE.search(link_m.group(1)).group(1)
        key = (int(date_m.group(1)), int(date_m.group(2)), int(date_m.group(3)))
        candidates.append((key, title, clip_id))
    candidates.sort(key=lambda c: c[0], reverse=True)
    for _, title, clip_id in candidates:
        if not _JUNK_TITLE_RE.search(title):
            return clip_id
    return None


async def find_candidate_url(session, platform, host):
    """Returns a real, specific meeting URL to try resolving, or None."""
    if platform == "granicus":
        subdomain = host.split(".")[0]
        for view_id in range(1, 11):
            url = (
                f"https://{subdomain}.granicus.com/ViewPublisherRSS.php"
                f"?view_id={view_id}&mode=video"
            )
            try:
                async with session.get(url, timeout=FETCH_TIMEOUT) as resp:
                    if resp.status != 200:
                        continue
                    xml = await resp.text(errors="replace")
            except Exception:
                continue
            if "<item>" not in xml:
                continue
            clip_id = _pick_best_granicus_item(xml)
            if clip_id:
                return f"https://{subdomain}.granicus.com/player/clip/{clip_id}?view_id={view_id}"
        return None

    if platform == "civicplus":
        return f"https://{host}/AgendaCenter"

    if platform == "civicclerk":
        subdomain = host.split(".")[0]
        api_base = f"https://{subdomain}.api.civicclerk.com/v1"
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for q in (
            f"{api_base}/Events?$filter=startDateTime lt {now_iso}&$orderby=startDateTime desc&$top=5",
            f"{api_base}/Events?$orderby=startDateTime desc&$top=5",
        ):
            try:
                rows = _odata_rows(await _get_json(session, q))
            except Exception:
                continue
            if rows:
                event_id = rows[0].get("id")
                if event_id is not None:
                    return f"https://{subdomain}.portal.civicclerk.com/event/{event_id}/media"
        return None

    if platform == "legistar":
        client = host.split(".")[0]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        url = (
            f"https://webapi.legistar.com/v1/{client}/events"
            f"?$filter=EventDate lt datetime'{today}'&$orderby=EventDate desc&$top=5"
        )
        try:
            rows = _odata_rows(await _get_json(session, url))
        except Exception:
            return None
        for row in rows:
            event_id = row.get("EventId")
            if event_id:
                return f"https://{client}.legistar.com/MeetingDetail.aspx?ID={event_id}"
        return None

    if platform == "primegov":
        subdomain = host.split(".")[0]
        for year in (datetime.now().year, datetime.now().year - 1):
            url = f"https://{subdomain}.primegov.com/api/v2/PublicPortal/ListArchivedMeetings?year={year}"
            try:
                data = await _get_json(session, url)
            except Exception:
                continue
            meetings = data if isinstance(data, list) else data.get("data") or []
            for m in meetings:
                docs = m.get("documentList") or []
                template_id = next(
                    (d.get("templateId") for d in docs if d.get("templateId")), None
                )
                if template_id:
                    return f"https://{subdomain}.primegov.com/Portal/Meeting?meetingTemplateId={template_id}"
        return None

    return None


_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)
PLATFORM_DOMAINS = {
    "granicus": "granicus.com",
    "civicplus": "civicplus.com",
    "civicclerk": "civicclerk.com",
    "legistar": "legistar.com",
    "primegov": "primegov.com",
}


# Generic vendor hosts, not a real per-district tenant -- found live
# 2026-09-06 debugging 12/17 CivicPlus "failures": a homepage's
# "powered by CivicPlus" footer credit links to CivicPlus's own login
# portal or marketing site, not the district's real
# "{state}-{name}.civicplus.com" tenant. Skip these when picking a host.
# Shared with app/platforms/base.py's own `find_platform_link()` (and
# scripts/wo134_confirmed_hits_ingest.py's `find_specific_platform_link()`)
# as of WO-162 (2026-09-10) -- this used to be its own separate copy of
# the same rule, one of five independent per-script patches around the
# same underlying `detect_platform()` bug (see that constant's own
# docstring for the full writeup).
_GENERIC_VENDOR_HOSTS = CIVICPLUS_CORPORATE_HOSTS


async def _find_enumerable_host(session, website, wanted_platforms):
    """Re-fetches the homepage (the original report never saved the
    failed candidate URL -- it's only set on success) and returns
    (platform, host) for the first enumerable platform link found, or
    (None, None)."""
    domains = {
        p: PLATFORM_DOMAINS[p] for p in wanted_platforms if p in PLATFORM_DOMAINS
    }
    if not domains:
        return None, None
    try:
        async with session.get(website, timeout=FETCH_TIMEOUT) as resp:
            if resp.status >= 400:
                return None, None
            html = await resp.text(errors="replace")
    except Exception:
        return None, None
    for href in _HREF_RE.findall(html):
        host = urlparse(href).netloc.lower()
        if not host or host in _GENERIC_VENDOR_HOSTS:
            continue
        for platform, domain in domains.items():
            if domain in host:
                return platform, host
    return None, None


async def process_one(session, row):
    wanted_platforms = row["platform_hits"].split(";")
    out = {
        "lea_name": row["lea_name"],
        "state": row["state"],
        "platform": "",
        "candidate_url": "",
        "status": "",
        "segments": 0,
        "agenda_items": 0,
        "detail": "",
    }

    if not any(p in ENUMERABLE for p in wanted_platforms):
        out["status"] = "no_enumeration_method"
        out["platform"] = wanted_platforms[0]
        return out

    platform, host = await _find_enumerable_host(
        session, row["website"], wanted_platforms
    )
    out["platform"] = platform or wanted_platforms[0]
    if not host:
        out["status"] = "no_host"
        return out

    candidate_url = await find_candidate_url(session, platform, host)
    if not candidate_url:
        out["status"] = "no_candidate_found"
        return out

    out["candidate_url"] = candidate_url
    try:
        real_platform = detect_platform(candidate_url)
        finder = get_finder(real_platform)
        result = await finder.resolve(candidate_url)
    except CalendarPageError as e:
        # The real, common CivicPlus case: /AgendaCenter is a listing
        # page, and CivicPlus's own resolve() already scanned it for
        # real candidates (README's "PRODUCER" adapters) -- pick the
        # most-recently-dated one instead of treating this as a failure.
        if not e.candidates:
            out["status"] = "resolve_failed"
            out["detail"] = "calendar page, no candidates"
            return out
        dated = [(c, _parse_generic_date(c.get("date"))) for c in e.candidates]
        dated.sort(key=lambda pair: pair[1] or datetime.min, reverse=True)
        picked_url = dated[0][0]["url"]
        out["candidate_url"] = picked_url
        try:
            real_platform = detect_platform(picked_url)
            finder = get_finder(real_platform)
            result = await finder.resolve(picked_url)
            candidate_url = picked_url
        except Exception as e2:
            out["status"] = "resolve_failed"
            out["detail"] = f"picked candidate failed: {e2}"[:200]
            return out
    except Exception as e:
        out["status"] = "resolve_failed"
        out["detail"] = str(e)[:200]
        return out

    out["segments"] = len(result.segments)
    out["agenda_items"] = len(result.agenda_items)
    has_content = bool(
        result.segments or result.agenda_items or result.agenda_link or result.video_url
    )
    if not has_content:
        out["status"] = "empty"
        return out

    passes_gate = bool(result.segments or result.agenda_items or result.agenda_link)
    normalized = normalize_url(candidate_url)
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
            qf.write(candidate_url + "\n")
        out["status"] = "queued-tier3"
        out["detail"] = "tier3_auto_transcription_queue.txt"
    return out


async def main():
    register_all_finders()
    # Second pass, scoped to just the two bugs fixed after the first
    # retry run: generic-vendor-host CivicPlus links and unhandled
    # CalendarPageError. Reads the *previous retry's* report, not the
    # original pipeline's, and only re-tries what that pass got wrong.
    with open(OUT_CSV, newline="", encoding="utf-8") as f:
        prior = list(csv.DictReader(f))
    with open(
        "/Users/mroconnell/Documents/rtr-business/research/school_district_pipeline_report.csv",
        newline="",
        encoding="utf-8",
    ) as f:
        original_by_name = {r["lea_name"]: r for r in csv.DictReader(f)}
    retry_targets = {"civicplus", "legistar"}
    rows = [
        original_by_name[r["lea_name"]]
        for r in prior
        if r["status"] == "resolve_failed" and r["platform"] in retry_targets
    ]

    print(f"Retrying {len(rows)} failures...\n")
    results = []
    async with aiohttp.ClientSession() as session:
        for i, row in enumerate(rows):
            out = await process_one(session, row)
            results.append(out)
            print(
                f"[{out['status']:20s}] {out['lea_name']} ({out['state']}) [{out['platform']}]  {out['detail']}"
            )
            if i < len(rows) - 1:
                await asyncio.sleep(DELAY_SECONDS)

    # Merge into the prior retry report rather than overwrite it -- this
    # pass only re-ran a subset (civicplus/legistar resolve_failed rows),
    # the other 42 rows' results from the first retry pass are still
    # correct and must survive this write.
    retried_names = {r["lea_name"] for r in results}
    merged = [r for r in prior if r["lea_name"] not in retried_names] + results
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(merged[0].keys()))
        writer.writeheader()
        writer.writerows(merged)

    print("\n=== THIS PASS ===")
    this_pass = {}
    for r in results:
        this_pass[r["status"]] = this_pass.get(r["status"], 0) + 1
    for status, count in sorted(this_pass.items(), key=lambda x: -x[1]):
        print(f"{status}: {count}")

    print("\n=== COMBINED (all retry passes) ===")
    combined = {}
    for r in merged:
        combined[r["status"]] = combined.get(r["status"], 0) + 1
    for status, count in sorted(combined.items(), key=lambda x: -x[1]):
        print(f"{status}: {count}")
    print(f"Full report: {OUT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
