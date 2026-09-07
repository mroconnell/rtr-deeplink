"""Second retry pass over the school-district failures
(rtr-business/research/school_district_retry_60_report.csv,
ENUMERATION_METHODS.md §63) -- this time using `rtr-discovery`'s real,
live-verified per-tenant enumerators for IQM2, Cablecast, Swagit,
CivicWeb, and eScribe.

Correction to this file's own earlier claim: those 5 platforms do NOT
lack a listing method in this project's history -- `rtr-discovery`
(~/Documents/rtr-discovery/discovery/enumerators/) has real, tested
per-tenant enumerator code for all five (plus civicclerk/civicplus/
granicus/legistar/primegov/proudcity/municode_meetings/youtube_channel,
already covered by other means). Only ChampDS, TelVue, NovusAgenda, and
CivicLive genuinely have nothing anywhere -- confirmed by reading
rtr-discovery's own `ENUMERATORS` registry, not assumed.

Reuses rtr-discovery's real code directly (import, not re-derive) --
same principle §50b already established: don't reinvent HTML-sniffing a
sibling project already solved.

Run from rtr-deeplink repo root with the venv active.
"""

import asyncio
import csv
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import detect_platform, get_finder  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402

sys.path.insert(0, str(Path.home() / "Documents" / "rtr-discovery"))
from discovery.enumerators import ENUMERATORS  # noqa: E402
from discovery.models import TenantRecord  # noqa: E402
from discovery.polite import PoliteClient  # noqa: E402

PRIOR_CSV = Path(
    "/Users/mroconnell/Documents/rtr-business/research/school_district_retry_60_report.csv"
)
ORIGINAL_CSV = Path(
    "/Users/mroconnell/Documents/rtr-business/research/school_district_pipeline_report.csv"
)
OUT_CSV = Path(
    "/Users/mroconnell/Documents/rtr-business/research/school_district_retry_discovery_report.csv"
)
QUEUE_FILE = Path(__file__).resolve().parent / "tier3_auto_transcription_queue.txt"
FETCH_TIMEOUT = aiohttp.ClientTimeout(total=10)
INGEST_TIMEOUT = aiohttp.ClientTimeout(total=65)
DELAY_SECONDS = 1.0

PLATFORM_DOMAINS = {
    "iqm2": "iqm2.com",
    "cablecast": "cablecast.tv",
    "swagit": "swagit.com",
    "civicweb": "civicweb.net",
    "escribe": "escribemeetings.com",
}
_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)


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


async def find_host(session, website, platform):
    domain = PLATFORM_DOMAINS[platform]
    try:
        async with session.get(website, timeout=FETCH_TIMEOUT) as resp:
            if resp.status >= 400:
                return None
            html = await resp.text(errors="replace")
    except Exception:
        return None
    for href in _HREF_RE.findall(html):
        host = urlparse(href).netloc.lower()
        if host and domain in host:
            return host
    return None


async def process_one(session, discovery_session, row, website):
    platform = row["platform"]
    out = {
        "lea_name": row["lea_name"],
        "state": row["state"],
        "platform": platform,
        "candidate_url": "",
        "status": "",
        "segments": 0,
        "agenda_items": 0,
        "detail": "",
    }

    if not website:
        out["status"] = "no_website_on_record"
        return out

    host = await find_host(session, website, platform)
    if not host:
        out["status"] = "no_host"
        return out

    enumerator = ENUMERATORS.get(platform)
    if enumerator is None:
        out["status"] = "no_enumerator"
        return out

    client = PoliteClient(discovery_session)
    tenant = TenantRecord(netloc=host, platform=platform)
    try:
        if enumerator.needs_params:
            params = await enumerator.discover_params(client, tenant)
            if not params:
                out["status"] = "no_params_discovered"
                return out
            tenant.params = params

        candidate = None
        async for c in enumerator.enumerate_tenant(
            client,
            tenant,
            date_from=None,
            date_to=None,
            mode="fast",
            should_stop=lambda: False,
        ):
            candidate = c
            break
    except Exception as e:
        out["status"] = "enumerate_failed"
        out["detail"] = str(e)[:200]
        return out

    if candidate is None:
        out["status"] = "no_candidate_found"
        return out

    candidate_url = candidate.url
    out["candidate_url"] = candidate_url
    try:
        real_platform = detect_platform(candidate_url)
        finder = get_finder(real_platform)
        result = await finder.resolve(candidate_url)
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
    with open(PRIOR_CSV, newline="", encoding="utf-8") as f:
        prior = list(csv.DictReader(f))
    with open(ORIGINAL_CSV, newline="", encoding="utf-8") as f:
        website_by_name = {r["lea_name"]: r["website"] for r in csv.DictReader(f)}
    rows = [
        r
        for r in prior
        if r["status"] == "no_enumeration_method" and r["platform"] in PLATFORM_DOMAINS
    ]

    print(f"Retrying {len(rows)} failures via rtr-discovery enumerators...\n")
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
