"""Round 5 retry over rtr-business/research/school_district_retry_no_host_v4_report.csv
-- targeted fixes for specific rows, not another blanket re-scan:

1. **IQM2/Cablecast/Swagit/CivicWeb/eScribe candidate limit widened
   5 -> 20, mode="fast" -> "thorough".** `find_discovery_candidates`
   collects from whatever order the real enumerator yields in, which
   isn't guaranteed newest-first for cablecast's whole-tenant
   `__remixContext` read -- 5 empty candidates doesn't mean the other
   ~299 (La Quinta's real count) are empty too. IQM2's own enumerator
   docstring separately documents thorough mode as a real 8-year window
   vs fast mode's 1 year, relevant for the 4-district BRSU VT tenant
   whose single most-recent meeting was empty every time it was tried.
3. **Legistar Hernando FL retried via the real events API**, not the
   stale hardcoded MeetingDetail.aspx?ID=1324 URL an earlier round left
   in the CSV (confirmed real 410 Gone -- that specific ID, not the
   tenant, is retired). `find_direct_candidates` already does this
   correctly; this row just never went through it.
4. **Corpus Christi ISD TX resolved directly** against the one known-
   real URL from earlier in this session's own history
   (`corpuschristiisdtx.new.swagit.com/events/43903`) instead of
   re-enumerating from the tenant root, which came back empty when
   tried (SCHOOL_DISTRICT_ENUMERATION_HANDOVER.md Group 4 already
   flagged this as worth trying directly rather than re-enumerating).

Everything else in the v4 report (the CivicPlus training-portal dead
ends, the two Cablecast FrontDoor-template enumerate_failed rows, the
genuinely host-not-found rows) is left untouched -- confirmed dead ends
or real adapter/enumerator gaps, not something a wider retry fixes.

Run from rtr-deeplink repo root with the venv active.
"""

import asyncio
import csv
import os
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
from app.platforms.base import CalendarPageError, detect_platform, get_finder  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402

sys.path.insert(0, str(Path.home() / "Documents" / "rtr-discovery"))
from discovery.enumerators import ENUMERATORS  # noqa: E402
from discovery.models import TenantRecord  # noqa: E402
from discovery.polite import PoliteClient  # noqa: E402

IN_CSV = Path(
    "/Users/mroconnell/Documents/rtr-business/research/school_district_retry_no_host_v4_report.csv"
)
OUT_CSV = Path(
    "/Users/mroconnell/Documents/rtr-business/research/school_district_retry_v5_report.csv"
)
QUEUE_FILE = Path(__file__).resolve().parent / "tier3_auto_transcription_queue.txt"
FETCH_TIMEOUT = aiohttp.ClientTimeout(total=12)
INGEST_TIMEOUT = aiohttp.ClientTimeout(total=65)
DELAY_SECONDS = 1.0

# host -> (platform, host-string-for-enumerator), so BRSU's 4 districts
# only get enumerated once instead of 4x.
RTR_DISCOVERY_HOSTS = {
    "Hesperia Unified": ("iqm2", "hesperiaschooldistrictca.iqm2.com"),
    "Fremont Union High": ("iqm2", "fremontunionhighschoolca.iqm2.com"),
    "Mettawee School District #84": ("iqm2", "brsu.iqm2.com"),
    "Taconic and Green Regional School District #63": ("iqm2", "brsu.iqm2.com"),
    "Winhall School District": ("iqm2", "brsu.iqm2.com"),
    "Bennington Rutland Supervisory Union": ("iqm2", "brsu.iqm2.com"),
    "HERRICKS UNION FREE SCHOOL DISTRICT": ("iqm2", "herricksufsd.iqm2.com"),
    "CARLE PLACE UNION FREE SCHOOL DISTRICT": (
        "iqm2",
        "carleplaceschooldistrictny.iqm2.com",
    ),
    "Prince George's County Public Schools": ("cablecast", "pgcps.cablecast.tv"),
}

LEGISTAR_RETRY = {
    "HERNANDO": "hernandoschools.legistar.com",
}

SWAGIT_DIRECT = {
    "CORPUS CHRISTI ISD": "https://corpuschristiisdtx.new.swagit.com/events/43903",
    "DEL VALLE ISD": "https://delvalleisdtx.new.swagit.com/videos/383029",
}

# Real hosts recovered via web search (2026-09-06) after the homepage
# scan's own fetch either got Akamai-bot-blocked (West Springfield's
# actual site, wsps.org, returns a real "Access Denied" WAF page -- a
# real bot gate, per this project's own never-work-around-it rule, so
# the granicus subdomain was found by search instead of by re-fetching
# the blocked homepage) or the homepage scan simply never matched it.
GRANICUS_DIRECT = {
    "West Springfield": "https://westspringfieldma.granicus.com/MediaPlayer.php?view_id=2&clip_id=408",
}


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


def _parse_generic_date(d):
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(d, fmt)
        except (ValueError, TypeError):
            continue
    return None


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


async def try_candidates(session, out_template, candidates):
    last = dict(out_template)
    for url in candidates:
        result = await resolve_and_route(session, dict(out_template), url)
        if (
            result["status"].startswith("ingested")
            or result["status"] == "queued-tier3"
        ):
            return result
        last = result
    return last


async def widen_discovery(
    discovery_session, session, platform, host, out_template, limit=20
):
    enumerator = ENUMERATORS.get(platform)
    if enumerator is None:
        out = dict(out_template)
        out["status"] = "no_enumeration_method"
        return out
    client = PoliteClient(discovery_session)
    tenant = TenantRecord(netloc=host, platform=platform)
    urls = []
    try:
        if enumerator.needs_params:
            params = await enumerator.discover_params(client, tenant)
            if not params:
                out = dict(out_template)
                out["status"] = "no_params_discovered"
                return out
            tenant.params = params
        async for c in enumerator.enumerate_tenant(
            client,
            tenant,
            date_from=None,
            date_to=None,
            mode="thorough",
            should_stop=lambda: False,
        ):
            urls.append(c.url)
            if len(urls) >= limit:
                break
    except Exception as e:
        if not urls:
            out = dict(out_template)
            out["status"] = "enumerate_failed"
            out["detail"] = str(e)[:200]
            return out
    if not urls:
        out = dict(out_template)
        out["status"] = "no_candidate_found"
        out["detail"] = "thorough mode, 0 candidates"
        return out
    return await try_candidates(session, out_template, urls)


async def main():
    register_all_finders()
    with open(IN_CSV, newline="", encoding="utf-8") as f:
        prior = list(csv.DictReader(f))
    by_name = {r["lea_name"]: r for r in prior}

    results = {}

    async with (
        aiohttp.ClientSession() as session,
        aiohttp.ClientSession() as discovery_session,
    ):
        # 1. IQM2/Cablecast widened, thorough mode -- BRSU's 4 districts
        # share one host, so enumerate it once and apply to all 4.
        host_cache = {}
        for name, (platform, host) in RTR_DISCOVERY_HOSTS.items():
            if host is None:
                continue
            row = by_name.get(name)
            if row is None:
                continue
            out_template = {
                "lea_name": name,
                "state": row["state"],
                "platform": platform,
                "candidate_url": "",
                "status": "",
                "segments": 0,
                "agenda_items": 0,
                "detail": "",
            }
            cache_key = (platform, host)
            if cache_key not in host_cache:
                host_cache[cache_key] = await widen_discovery(
                    discovery_session, session, platform, host, out_template
                )
                print(
                    f"[{host_cache[cache_key]['status']:20s}] {name} ({row['state']}) [{platform}] host={host}  {host_cache[cache_key]['detail']}"
                )
                await asyncio.sleep(DELAY_SECONDS)
            result = dict(host_cache[cache_key])
            result["lea_name"] = name
            result["state"] = row["state"]
            results[name] = result

        # 2. Legistar Hernando via real events API.
        for prefix, host in LEGISTAR_RETRY.items():
            matches = [n for n in by_name if n.upper().startswith(prefix)]
            for name in matches:
                row = by_name[name]
                client = host.split(".")[0]
                today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                url = (
                    f"https://webapi.legistar.com/v1/{client}/events"
                    f"?$filter=EventDate lt datetime'{today}'&$orderby=EventDate desc&$top=10"
                )
                out_template = {
                    "lea_name": name,
                    "state": row["state"],
                    "platform": "legistar",
                    "candidate_url": "",
                    "status": "",
                    "segments": 0,
                    "agenda_items": 0,
                    "detail": "",
                }
                try:
                    async with session.get(url, timeout=FETCH_TIMEOUT) as resp:
                        resp.raise_for_status()
                        data = await resp.json(content_type=None)
                    rows = (
                        data
                        if isinstance(data, list)
                        else (data or {}).get("value") or []
                    )
                    candidates = [
                        f"https://{client}.legistar.com/MeetingDetail.aspx?ID={r['EventId']}"
                        for r in rows
                        if r.get("EventId")
                    ]
                except Exception as e:
                    out_template["status"] = "resolve_failed"
                    out_template["detail"] = str(e)[:200]
                    results[name] = out_template
                    print(
                        f"[resolve_failed      ] {name} ({row['state']}) [legistar]  {out_template['detail']}"
                    )
                    continue
                if not candidates:
                    out_template["status"] = "no_candidate_found"
                    results[name] = out_template
                    print(
                        f"[no_candidate_found  ] {name} ({row['state']}) [legistar]  0 events from API"
                    )
                    continue
                result = await try_candidates(session, out_template, candidates)
                results[name] = result
                print(
                    f"[{result['status']:20s}] {name} ({row['state']}) [legistar]  {result['detail']}"
                )
                await asyncio.sleep(DELAY_SECONDS)

        # 3. Direct known URLs (Swagit + Granicus) recovered manually /
        # via web search, resolved straight through instead of
        # re-enumerating from the tenant root.
        for platform, direct_map in (
            ("swagit", SWAGIT_DIRECT),
            ("granicus", GRANICUS_DIRECT),
        ):
            for prefix, url in direct_map.items():
                matches = [n for n in by_name if n.upper().startswith(prefix.upper())]
                for name in matches:
                    row = by_name[name]
                    out_template = {
                        "lea_name": name,
                        "state": row["state"],
                        "platform": platform,
                        "candidate_url": "",
                        "status": "",
                        "segments": 0,
                        "agenda_items": 0,
                        "detail": "",
                    }
                    result = await resolve_and_route(session, out_template, url)
                    results[name] = result
                    print(
                        f"[{result['status']:20s}] {name} ({row['state']}) [{platform}]  {result['detail']}"
                    )

    merged = [results.get(r["lea_name"], r) for r in prior]
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(merged[0].keys()))
        writer.writeheader()
        writer.writerows(merged)

    print("\n=== ROUND 5 ATTEMPTED ===")
    for name, r in results.items():
        print(f"{r['status']:20s} {name}")
    print(f"\nFull merged report: {OUT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
