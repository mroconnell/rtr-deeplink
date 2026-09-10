"""Retry pass over the 29 `no_host` school-district rows across both
prior retry passes (rtr-business/research/
school_district_retry_discovery_report.csv, ENUMERATION_METHODS.md §63)
-- fixes two real bugs found by manually inspecting actual page HTML for
a sample of these rows, not guessed:

1. **No `User-Agent` header** on the homepage re-fetch. The original
   scan script sent one; both retry scripts' own re-fetch helpers
   dropped it. Some sites serve different content to a bare request.
2. **The link-extraction regex only checked `href=`, missing
   `<iframe src="...">` embeds.** Confirmed real: Oakland Unified's
   actual Granicus link is `<iframe src="https://ousd.granicus.com/
   ViewPublisher.php?view_id=3">`, not an anchor tag at all -- a common
   pattern for embedded meeting-video widgets specifically (more common
   on school district sites than the city/county sites earlier passes
   targeted).

Routes each recovered host through the same per-platform specify logic
already built in the two prior retry scripts (Granicus RSS sweep,
CivicPlus /AgendaCenter, CivicClerk/Legistar/PrimeGov APIs, or
rtr-discovery's enumerators for IQM2/Cablecast/Swagit/CivicWeb/eScribe)
rather than re-deriving it.

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

sys.path.insert(0, str(Path.home() / "Documents" / "rtr-discovery"))
from discovery.enumerators import ENUMERATORS  # noqa: E402
from discovery.models import TenantRecord  # noqa: E402
from discovery.polite import PoliteClient  # noqa: E402

LATEST_CSV = Path(
    "/Users/mroconnell/Documents/rtr-business/research/school_district_retry_no_host_v3_report.csv"
)
ORIGINAL_CSV = Path(
    "/Users/mroconnell/Documents/rtr-business/research/school_district_pipeline_report.csv"
)
OUT_CSV = Path(
    "/Users/mroconnell/Documents/rtr-business/research/school_district_retry_no_host_v4_report.csv"
)
QUEUE_FILE = Path(__file__).resolve().parent / "tier3_auto_transcription_queue.txt"
FETCH_TIMEOUT = aiohttp.ClientTimeout(total=10)
INGEST_TIMEOUT = aiohttp.ClientTimeout(total=65)
DELAY_SECONDS = 1.0
USER_AGENT = (
    "Mozilla/5.0 (compatible; rtr-deeplink research crawl; contact ryan@how-to-adu.com)"
)

# href AND src (and data-src, for a lazy-loaded iframe) -- the Oakland
# Unified case confirmed a real embedded-video link lives in an iframe's
# src, invisible to an href-only regex.
_LINK_ATTR_RE = re.compile(r'(?:href|src|data-src)=["\']([^"\']+)["\']', re.IGNORECASE)
# Fourth pattern found 2026-09-06 (Champaign CUSD 4 IL): the real link is
# sometimes a bare quoted string inside inline JS (a share-widget config,
# not any HTML attribute at all) -- `"https://champaign-cablecast.
# cablecast.tv/watch-now?..."` with no href/src anywhere near it. Used
# only as a fallback when the attribute-based regex finds nothing, since
# a bare quoted-string search is a much wider net (could pick up an
# unrelated analytics/tracking reference) -- scoped to a specific known
# platform domain by the caller either way, which keeps the risk low.
_BARE_URL_RE = re.compile(r'["\'](https?://[^"\']*)["\']', re.IGNORECASE)

RTR_DISCOVERY_PLATFORMS = {"iqm2", "cablecast", "swagit", "civicweb", "escribe"}
DIRECT_PLATFORMS = {
    "granicus",
    "civicplus",
    "civicclerk",
    "legistar",
    "primegov",
    "novusagenda",
}
# No listing method anywhere for these, but the homepage link is often
# already a specific, directly-resolvable URL rather than a tenant
# root -- worth a raw attempt before giving up (TelVue especially: its
# org-token+path URLs found on a homepage are frequently already a real
# `.../media/{id}` leaf, confirmed on Yuma Union HS District AZ).
RAW_LINK_FALLBACK_PLATFORMS = {"telvue", "champds", "civiclive"}

PLATFORM_DOMAINS = {
    "granicus": "granicus.com",
    "civicplus": "civicplus.com",
    "civicclerk": "civicclerk.com",
    "legistar": "legistar.com",
    "primegov": "primegov.com",
    "iqm2": "iqm2.com",
    "cablecast": "cablecast.tv",
    "swagit": "swagit.com",
    "civicweb": "civicweb.net",
    "escribe": "escribemeetings.com",
    "novusagenda": "novusagenda.com",
    "telvue": "telvue.com",
    "champds": "champds.com",
    "civiclive": "civiclive.com",
}
# Shared with app/platforms/base.py's own `find_platform_link()` (and
# scripts/wo134_confirmed_hits_ingest.py's `find_specific_platform_link()`)
# as of WO-162 (2026-09-10) -- this used to be its own separate copy of
# the same rule; see CIVICPLUS_CORPORATE_HOSTS' own docstring for the
# full writeup of the bug this fixes at the source.
_GENERIC_VENDOR_HOSTS = CIVICPLUS_CORPORATE_HOSTS

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
    async with session.get(
        url, timeout=FETCH_TIMEOUT, headers={"User-Agent": USER_AGENT}
    ) as resp:
        resp.raise_for_status()
        return await resp.json(content_type=None)


def _odata_rows(payload):
    if isinstance(payload, dict):
        return payload.get("value") or []
    return payload or []


def _parse_generic_date(d):
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(d, fmt)
        except (ValueError, TypeError):
            continue
    return None


def _pick_granicus_items(xml, limit=5):
    """Returns up to `limit` non-junk clip_ids, newest first -- a list,
    not just the single best one. §63's own retry history shows the
    single newest item is empty often enough (agenda-only, or a
    workshop with no video) that trying the next few matters."""
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
    return [
        clip_id for _, title, clip_id in candidates if not _JUNK_TITLE_RE.search(title)
    ][:limit]


async def find_host(session, website, wanted_platforms):
    """Fixed version: real User-Agent, checks href/src/data-src, skips
    known-generic vendor hosts. Returns (platform, host, raw_link) --
    raw_link is the actual matched URL, kept for platforms with no
    listing method (TelVue, ChampDS, CivicLive) where the homepage link
    is often already a specific, directly-resolvable meeting/media URL,
    not a tenant root needing a listing step at all -- confirmed live
    2026-09-06: Yuma Union HS District AZ's TelVue link is already
    `.../playlists/6454/media/806123`, a real leaf media URL."""
    domains = {
        p: PLATFORM_DOMAINS[p] for p in wanted_platforms if p in PLATFORM_DOMAINS
    }
    if not domains:
        return None, None, None
    try:
        async with session.get(
            website, timeout=FETCH_TIMEOUT, headers={"User-Agent": USER_AGENT}
        ) as resp:
            if resp.status >= 400:
                return None, None, None
            html = await resp.text(errors="replace")
    except Exception:
        return None, None, None
    # Real third pattern found 2026-09-06 (Mettawee/BRSU VT, Corpus
    # Christi ISD TX): the real link sometimes lives inside a JSON-
    # encoded HTML-as-text blob (a server-rendered data payload), with
    # backslash-escaped quotes (`href=\"...\"`) and `<`-escaped
    # angle brackets. Unescaping before matching recovers both without
    # needing a JSON parser -- the surrounding `<a ... </a>`
    # doesn't interfere with a plain `href="..."` match once the quotes
    # are real quotes again.
    html = html.replace('\\"', '"').replace("\\'", "'")
    for link in _LINK_ATTR_RE.findall(html):
        host = urlparse(link).netloc.lower()
        if not host or host in _GENERIC_VENDOR_HOSTS:
            continue
        for platform, domain in domains.items():
            if domain in host:
                return platform, host, link
    # Fallback: bare quoted URL string, no attribute at all (Champaign
    # CUSD 4's real case -- inline JS, not href/src/data-src).
    for link in _BARE_URL_RE.findall(html):
        host = urlparse(link).netloc.lower()
        if not host or host in _GENERIC_VENDOR_HOSTS:
            continue
        for platform, domain in domains.items():
            if domain in host:
                return platform, host, link
    return None, None, None


async def find_direct_candidates(session, platform, host, limit=5):
    """Returns up to `limit` candidate URLs, newest first, instead of
    just one -- an empty top result doesn't mean the tenant is dead, it
    means that specific meeting had nothing (confirmed repeatedly across
    §63's retry rounds: IQM2/CivicClerk/PrimeGov/NovusAgenda all had
    real tenants whose single newest item was empty)."""
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
            clip_ids = _pick_granicus_items(xml, limit=limit)
            if clip_ids:
                return [
                    f"https://{subdomain}.granicus.com/player/clip/{cid}?view_id={view_id}"
                    for cid in clip_ids
                ]
        return []

    if platform == "civicplus":
        return [f"https://{host}/AgendaCenter"]

    if platform == "civicclerk":
        subdomain = host.split(".")[0]
        api_base = f"https://{subdomain}.api.civicclerk.com/v1"
        now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        for q in (
            f"{api_base}/Events?$filter=startDateTime lt {now_iso}&$orderby=startDateTime desc&$top={limit}",
            f"{api_base}/Events?$orderby=startDateTime desc&$top={limit}",
        ):
            try:
                rows = _odata_rows(await _get_json(session, q))
            except Exception:
                continue
            urls = [
                f"https://{subdomain}.portal.civicclerk.com/event/{r['id']}/media"
                for r in rows
                if r.get("id") is not None
            ]
            if urls:
                return urls
        return []

    if platform == "legistar":
        client = host.split(".")[0]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        url = (
            f"https://webapi.legistar.com/v1/{client}/events"
            f"?$filter=EventDate lt datetime'{today}'&$orderby=EventDate desc&$top={limit}"
        )
        try:
            rows = _odata_rows(await _get_json(session, url))
        except Exception:
            return []
        return [
            f"https://{client}.legistar.com/MeetingDetail.aspx?ID={r['EventId']}"
            for r in rows
            if r.get("EventId")
        ]

    if platform == "primegov":
        subdomain = host.split(".")[0]
        urls = []
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
                    urls.append(
                        f"https://{subdomain}.primegov.com/Portal/Meeting?meetingTemplateId={template_id}"
                    )
                    if len(urls) >= limit:
                        return urls
            if urls:
                return urls
        return urls

    if platform == "novusagenda":
        # No real listing/filter API confirmed for this platform --
        # /agendapublic/ itself is what worked for East Brunswick
        # Township NJ in the original pipeline pass, apparently because
        # the root of that path already surfaces a real recent meeting
        # for at least some tenants. Not a general enumerator, just the
        # one thing already confirmed to work -- only ever one candidate.
        subdomain = host.split(".")[0]
        return [f"https://{subdomain}.novusagenda.com/agendapublic/"]

    return []


async def find_discovery_candidates(discovery_session, platform, host, limit=5):
    enumerator = ENUMERATORS.get(platform)
    if enumerator is None:
        return []
    client = PoliteClient(discovery_session)
    tenant = TenantRecord(netloc=host, platform=platform)
    urls = []
    try:
        if enumerator.needs_params:
            params = await enumerator.discover_params(client, tenant)
            if not params:
                return []
            tenant.params = params
        async for c in enumerator.enumerate_tenant(
            client,
            tenant,
            date_from=None,
            date_to=None,
            mode="fast",
            should_stop=lambda: False,
        ):
            urls.append(c.url)
            if len(urls) >= limit:
                break
    except Exception:
        return urls  # whatever was collected before the failure is still real
    return urls


async def resolve_and_route(session, out, candidate_url):
    out["candidate_url"] = candidate_url
    try:
        real_platform = detect_platform(candidate_url)
        finder = get_finder(real_platform)
        result = await finder.resolve(candidate_url)
    except CalendarPageError as e:
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


async def process_one(session, discovery_session, row, website):
    wanted_platforms = (
        row["platform_hits"].split(";") if "platform_hits" in row else [row["platform"]]
    )
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
    if not website:
        out["status"] = "no_website_on_record"
        return out

    platform, host, raw_link = await find_host(session, website, wanted_platforms)
    out["platform"] = platform or wanted_platforms[0]
    if not host:
        out["status"] = "no_host_still"
        return out

    if platform in DIRECT_PLATFORMS:
        candidates = await find_direct_candidates(session, platform, host)
    elif platform in RTR_DISCOVERY_PLATFORMS:
        candidates = await find_discovery_candidates(discovery_session, platform, host)
    elif platform in RAW_LINK_FALLBACK_PLATFORMS:
        candidates = [raw_link] if raw_link else []
    else:
        out["status"] = "no_enumeration_method"
        return out

    if not candidates:
        out["status"] = "no_candidate_found"
        return out

    # Try each candidate newest-first until one has real content -- an
    # empty top result doesn't mean the tenant is dead (confirmed
    # repeatedly this session: real tenants, real most-recent meetings,
    # genuinely nothing in them). Keep the last attempt's result if none
    # work, so a real failure reason still gets reported.
    last_result = out
    for candidate_url in candidates:
        result = await resolve_and_route(session, dict(out), candidate_url)
        if (
            result["status"].startswith("ingested")
            or result["status"] == "queued-tier3"
        ):
            return result
        last_result = result
    return last_result


async def main():
    register_all_finders()
    with open(LATEST_CSV, newline="", encoding="utf-8") as f:
        prior = list(csv.DictReader(f))
    with open(ORIGINAL_CSV, newline="", encoding="utf-8") as f:
        original_rows = list(csv.DictReader(f))
    website_by_name = {r["lea_name"]: r["website"] for r in original_rows}
    platform_hits_by_name = {r["lea_name"]: r["platform_hits"] for r in original_rows}

    rows = [
        r
        for r in prior
        if r["status"]
        in (
            "no_host",
            "no_host_still",
            "no_enumeration_method",
            "empty",
            "no_candidate_found",
        )
    ]
    for r in rows:
        r["platform_hits"] = platform_hits_by_name.get(r["lea_name"], r["platform"])

    print(
        f"Retrying {len(rows)} rows: multi-candidate retry + bare-URL extraction...\n"
    )
    results = []
    async with (
        aiohttp.ClientSession() as session,
        aiohttp.ClientSession() as discovery_session,
    ):
        for i, row in enumerate(rows):
            website = website_by_name.get(row["lea_name"], "")
            out = await process_one(session, discovery_session, row, website)
            results.append(out)
            print(
                f"[{out['status']:20s}] {out['lea_name']} ({out['state']}) [{out['platform']}]  {out['detail']}"
            )
            if i < len(rows) - 1:
                await asyncio.sleep(DELAY_SECONDS)

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

    print("\n=== COMBINED (all passes) ===")
    combined = {}
    for r in merged:
        combined[r["status"]] = combined.get(r["status"], 0) + 1
    for status, count in sorted(combined.items(), key=lambda x: -x[1]):
        print(f"{status}: {count}")
    print(f"Full report: {OUT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
