"""One-hop scan of NCES's real school-district homepages
(rtr-business/research/nces_school_district_websites_2024_25.csv, §63 of
ENUMERATION_METHODS.md) for a link to a platform this project already
has an adapter for -- same method §50b already validated (fetch the
real page, check for the vendor's own domain string in the raw HTML)
rather than reinventing HTML-sniffing.

This is a plain HTTP GET + substring check, not the wildcard-signature
method -- no rate-limit concern the way Granicus/Legistar's shared
cluster had, since every request here goes to a different district's
own domain. Concurrency is bounded by a semaphore instead of a
per-platform delay.

Known limitation, same one §50b already found and didn't solve: a
client-rendered (JS-injected) platform link is invisible to a plain
GET. Real next step for misses is generic_fallback.py's headless-
browser escalation, not rebuilding that here.

Usage: python3 scripts/adhoc_school_district_platform_scan.py
"""

import asyncio
import csv
import os
import sys
import time
from pathlib import Path

import aiohttp
import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

INPUT_CSV = Path(
    "/Users/mroconnell/Documents/rtr-business/research/nces_school_district_websites_2024_25.csv"
)
OUT_DIR = Path("/Users/mroconnell/Documents/rtr-business/research")
ALL_RESULTS_CSV = OUT_DIR / "school_district_platform_scan_all_results.csv"
HITS_CSV = OUT_DIR / "school_district_platform_scan_hits.csv"

CONCURRENCY = 40
TIMEOUT = aiohttp.ClientTimeout(total=10)
USER_AGENT = (
    "Mozilla/5.0 (compatible; rtr-deeplink research crawl; contact ryan@how-to-adu.com)"
)

# Domain substrings for every platform this project has a real adapter
# for, per rtr-deeplink/README.md's "Supported platforms" table plus
# BoardDocs (no video adapter, but §43 already flagged it as the
# strongest K-12 lead this project has found, worth recording even
# without a video path).
PLATFORM_SIGNATURES = {
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
    "clerkbase": "clerkshq.com",
    "municode_meetings": "municodemeetings.com",
    "civiclive": "civiclive.com",
    "boarddocs": "boarddocs.com",
    "agendasuite": "agendasuite.org",
    "novusagenda": "novusagenda.com",
    "municipalcodeonline": "municipalcodeonline.com",
    # Bare "vimeo.com"/"youtube.com" is too noisy to trust from a
    # homepage-only substring check -- confirmed live 2026-09-05, a
    # 20-district pilot of this script hit "youtube" on 10/20 sites via
    # nothing but a generic footer social-media icon link, zero of them
    # actually a meeting video. Narrowed to the embed-iframe path
    # specifically, a real signal an actual video player is on the page.
    "vimeo": "player.vimeo.com/video/",
    "youtube": "youtube.com/embed/",
}

_RESULT_FIELDS = [
    "leaid",
    "lea_name",
    "state",
    "website",
    "status",
    "platform_hits",
    "detail",
]


def normalize_url(url: str) -> str:
    url = url.strip()
    if not url:
        return url
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _open_incremental(path):
    is_new = not path.exists()
    f = open(path, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=_RESULT_FIELDS)
    if is_new:
        writer.writeheader()
        f.flush()
    return f, writer


def detect_platforms(html: str):
    lower = html.lower()
    return sorted(name for name, sig in PLATFORM_SIGNATURES.items() if sig in lower)


async def check_district(session, sem, row):
    url = normalize_url(row["website"])
    out = {
        "leaid": row["leaid"],
        "lea_name": row["lea_name"],
        "state": row["state"],
        "website": url,
        "status": "",
        "platform_hits": "",
        "detail": "",
    }
    if not url:
        out["status"] = "no_url"
        return out
    async with sem:
        try:
            async with session.get(
                url,
                timeout=TIMEOUT,
                headers={"User-Agent": USER_AGENT},
                allow_redirects=True,
            ) as resp:
                out["detail"] = f"HTTP {resp.status}"
                if resp.status >= 400:
                    out["status"] = "http_error"
                    return out
                html = await resp.text(errors="replace")
        except Exception as e:
            out["status"] = "fetch_error"
            out["detail"] = str(e)[:200]
            return out

    hits = detect_platforms(html)
    if hits:
        out["status"] = "platform_found"
        out["platform_hits"] = ";".join(hits)
    else:
        out["status"] = "no_known_platform"
    return out


async def main():
    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["sy_status_text"] == "Open"]

    print(f"{len(rows)} open districts to check, concurrency={CONCURRENCY}...")

    all_file, all_writer = _open_incremental(ALL_RESULTS_CSV)
    write_lock = asyncio.Lock()
    sem = asyncio.Semaphore(CONCURRENCY)
    counts = {
        "total": 0,
        "platform_found": 0,
        "no_known_platform": 0,
        "http_error": 0,
        "fetch_error": 0,
    }

    async def worker(session, row):
        result = await check_district(session, sem, row)
        async with write_lock:
            all_writer.writerow(result)
            all_file.flush()
        counts["total"] += 1
        counts[result["status"]] = counts.get(result["status"], 0) + 1
        if counts["total"] % 250 == 0:
            print(
                f"{counts['total']}/{len(rows)} checked -- "
                f"{counts['platform_found']} platform hits, "
                f"{counts['no_known_platform']} no known platform, "
                f"{counts['http_error']} http errors, {counts['fetch_error']} fetch errors"
            )

    start = time.time()
    try:
        connector = aiohttp.TCPConnector(limit=CONCURRENCY, ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            await asyncio.gather(*(worker(session, row) for row in rows))
    finally:
        all_file.close()
    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.1f}s. {counts}")

    with open(ALL_RESULTS_CSV, encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))
    hits = [r for r in all_rows if r["status"] == "platform_found"]
    with open(HITS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_RESULT_FIELDS)
        writer.writeheader()
        writer.writerows(hits)
    print(f"{len(hits)} platform hits -> {HITS_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
