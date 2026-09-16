"""WO-331 follow-up: for the control governments where step 4's hand-check
called resolve() on a URL detect_platform() didn't even recognize
(UNSUPPORTED) or on a listing page (CALENDAR_PAGE/NoVideoCandidateFound),
this refines step 5 with what the raw evidence actually shows: Phase 3
confirmed a platform by finding that platform's *signal* somewhere in the
fetched page's content, not necessarily at the fetched URL itself. This
script re-fetches each such confirmed page once, greps its HTML for the
first outbound link to the platform's own real vendor host (granicus.com,
iqm2.com, civicweb.net, escribemeetings.com, municodemeetings.com,
primegov.com, champds.com, telvue.com/peg.tv, cablecast.tv, castus.tv,
boxcast.tv, suiteonemedia.com, viebit.com, townhallstreams.com,
civiclive.com, vimeo.com -- youtube.com/youtu.be excluded per the
never-fetch rule), and calls resolve() on THAT link -- the one hop the
sweeps' own hand-check never takes. Read-only, no ingest.
"""

from __future__ import annotations

import asyncio
import csv
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import requests  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wo331_handcheck import (  # noqa: E402
    HONEST_HEADERS,
    install_youtube_guard,
    resolve_safely,
)

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
HANDCHECK_CSV = RESEARCH_DIR / "wo331_handcheck.csv"
OUT_CSV = RESEARCH_DIR / "wo331_vendor_hop.csv"

VENDOR_HOST_PATTERNS = [
    "granicus.com",
    "iqm2.com",
    "civicweb.net",
    "escribemeetings.com",
    "municodemeetings.com",
    "primegov.com",
    "champds.com",
    "telvue.com",
    "peg.tv",
    "cablecast.tv",
    "castus.tv",
    "boxcast.tv",
    "suiteonemedia.com",
    "viebit.com",
    "townhallstreams.com",
    "civiclive.com",
    "vimeo.com",
    "legistar.com",
    "civicplus.com",
]

TARGET_DOMAINS = [
    "cresthill.gov",
    "knoxvilletn.gov",
    "maurycounty-tn.gov",
    "victoria.ca",
    "www.niagarafalls.ca",
    "pwcva.gov",
    "ci.forest-lake.mn.us",
    "qac.gov",
    "franklinnh.gov",
    "monroecounty-fl.gov",
    "webbcountytx.gov",
    "www.co.jefferson.wa.us",
]


def find_vendor_link(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        full = urljoin(base_url, href)
        host = urlparse(full).netloc.lower()
        if any(pat in host for pat in VENDOR_HOST_PATTERNS):
            return full
    # Also check raw text (iframes, script-embedded src=) not caught by <a>.
    for pat in VENDOR_HOST_PATTERNS:
        m = re.search(
            r'(?:src|href)=["\']([^"\']*' + re.escape(pat) + r'[^"\']*)["\']',
            html,
            re.IGNORECASE,
        )
        if m:
            return urljoin(base_url, m.group(1))
    return None


def fetch_plain(url: str) -> tuple[int | None, str | None, str]:
    try:
        resp = requests.get(url, headers=HONEST_HEADERS, timeout=20)
        return resp.status_code, resp.url, resp.text
    except Exception as e:  # noqa: BLE001
        return None, None, f"FETCH_ERROR: {type(e).__name__}: {e}"


async def main() -> None:
    install_youtube_guard()

    with open(HANDCHECK_CSV, newline="", encoding="utf-8") as f:
        rows = {r["domain"]: r for r in csv.DictReader(f)}

    out = []
    for domain in TARGET_DOMAINS:
        row = rows.get(domain)
        if not row:
            continue
        confirmed_url = row["confirmed_url"]
        print(f"\n=== {domain} confirmed_url={confirmed_url}", file=sys.stderr)
        status, final_url, body = fetch_plain(confirmed_url)
        result = {
            "domain": domain,
            "confirmed_url": confirmed_url,
            "fetch_status": status,
        }
        if not (
            status
            and 200 <= status < 300
            and body
            and not body.startswith("FETCH_ERROR")
        ):
            result["vendor_link"] = ""
            result["verdict"] = "FETCH_FAILED"
            result["detail"] = body[:200] if isinstance(body, str) else ""
            out.append(result)
            continue

        vendor_link = find_vendor_link(body, final_url or confirmed_url)
        if not vendor_link:
            result["vendor_link"] = ""
            result["verdict"] = "NO_VENDOR_LINK_ON_PAGE"
            result["detail"] = (
                "no outbound link to a known vendor host found on the confirmed page"
            )
            out.append(result)
            print("  no vendor link found", file=sys.stderr)
            await asyncio.sleep(1.5)
            continue

        result["vendor_link"] = vendor_link
        print(f"  vendor_link={vendor_link}", file=sys.stderr)
        r = await resolve_safely(vendor_link)
        for k, v in r.items():
            result[k] = v
        print(
            f"  verdict={r.get('verdict')} {r.get('detail', '')[:150]}", file=sys.stderr
        )
        out.append(result)
        await asyncio.sleep(1.5)

    fieldnames = sorted({k for r in out for k in r.keys()})
    lead = [
        "domain",
        "confirmed_url",
        "vendor_link",
        "verdict",
        "has_video",
        "segments",
        "detail",
    ]
    ordered = lead + [f for f in fieldnames if f not in lead]
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=ordered, extrasaction="ignore", lineterminator="\n"
        )
        w.writeheader()
        w.writerows(out)
    print(f"\nwrote {OUT_CSV} ({len(out)} rows)", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
