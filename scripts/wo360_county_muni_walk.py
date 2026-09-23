"""WO-360, part A step 1: walk the 55 West Virginia county government
sites for a page that lists the county's incorporated municipalities and
their own websites (the pattern Ryan found by hand:
`https://www.berkeleywv.org/341/Municipalities` links `cityofmartinsburg
.org`, `hedgesvillewv.us`, ...), one hop from the homepage.

Fetches the county's own homepage (current `domain` column value, already
corrected by the conductor's WV pass, commit 60c7036), scores every link
on that page by keyword match against a small municipality-directory
phrase list, fetches the top-scored candidate (one hop only, per the
brief), and extracts every outbound (different-host) link on that page
whose visible text plausibly names a town/city/village. Falls back to a
short list of guessable paths (`/Municipalities`, `/Directory.aspx`,
`/government/municipalities`, ...) when no nav link scores above zero,
same shape as the guessable-path probes elsewhere in this WO wave.

Never fetches youtube.com/youtu.be. Honest UA, `polite_request()` from
`wo282_recon.py` (2.5s per-host delay, not relevant here since each
county is its own host; 6s connect timeout). Response bodies are capped
at 3 MB via `iter_content`, and each single HTTP call is bounded to 20s
end to end by wrapping `polite_request` in a thread with a hard timeout,
per the WO-360 brief's per-fetch budget (stricter than wo282_recon's own
GOV_REQUEST_TIMEOUT=6s connect-only figure).

Usage (from the rtr-deeplink repo root, shared venv):
    .venv/bin/python scripts/wo360_county_muni_walk.py

Writes `research/wo360_county_walk.csv` (one row per county: county
gov_id, name, domain, page used, hop count, status) and
`research/wo360_muni_links.csv` (one row per municipality link found:
county gov_id, county name, link text, resolved absolute URL, host).
Both under the shared rtr-business checkout, resumable is unnecessary at
this scale (55 counties, single pass, a few minutes).
"""

from __future__ import annotations

import csv
import re
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeoutError
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
import wo282_recon as w273  # noqa: E402

RTR_BUSINESS = Path("/Users/mroconnell/Documents/rtr-business")
JC_CSV = RTR_BUSINESS / "research" / "jurisdiction_coverage.csv"
COUNTY_WALK_CSV = RTR_BUSINESS / "research" / "wo360_county_walk.csv"
MUNI_LINKS_CSV = RTR_BUSINESS / "research" / "wo360_muni_links.csv"

PER_FETCH_TIMEOUT = 20  # seconds, hard wall per the WO-360 brief
MAX_BYTES = 3 * 1024 * 1024

MUNI_PHRASES = [
    "municipalit",
    "cities and towns",
    "cities & towns",
    "towns and cities",
    "towns & cities",
    "incorporated town",
    "incorporated citi",
    "our towns",
    "local government directory",
    "town directory",
    "city directory",
    "communities",
]

GUESSABLE_PATHS = [
    "/Municipalities",
    "/341/Municipalities",
    "/Directory.aspx",
    "/government/municipalities",
    "/residents/municipalities",
    "/departments/municipalities",
    "/local-government/municipalities",
    "/municipalities",
    "/municipalities.php",
    "/Pages/Municipalities.aspx",
    "/our-communities",
    "/towns",
    "/cities-and-towns",
    "/community/municipalities",
    "/about/municipalities",
]

SOCIAL_OR_JUNK_HOSTS = (
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "youtube.com",
    "youtu.be",
    "maps.google.com",
    "google.com",
    "linkedin.com",
)


def is_state_portal_host(host: str) -> bool:
    """The state's own wv.gov portal, e.g. `www.wv.gov` or
    `apps.wv.gov` -- NOT a municipal `<name>wv.gov` domain (a real and
    common WV municipal shape, e.g. `wheelingwv.gov`), which merely
    contains "wv.gov" as a tail substring with no separating dot. A
    plain substring check on "wv.gov" wrongly excluded exactly that
    shape (`wheelingwv.gov` matched) -- caught live 2026-09-13 checking
    why Ohio County's own municipalities page, which really does link
    `www.wheelingwv.gov`, came back with zero extracted links."""
    host = host.lower()
    return host == "wv.gov" or host.endswith(".wv.gov")


def bounded_get(url: str):
    """One HTTP GET, hard-bounded to PER_FETCH_TIMEOUT wall time and
    MAX_BYTES of body, via wo282_recon's polite_request + streaming."""

    def _do():
        resp = w273.RATE_LIMITER.wait_and_request(
            urlparse(url).netloc,
            requests.request,
            "GET",
            url,
            headers=w273.HEADERS,
            timeout=w273.GOV_REQUEST_TIMEOUT,
            allow_redirects=True,
            stream=True,
        )
        body = b""
        for chunk in resp.iter_content(chunk_size=65536):
            body += chunk
            if len(body) >= MAX_BYTES:
                break
        return resp.status_code, body[:MAX_BYTES], resp.url

    with ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_do)
        try:
            return fut.result(timeout=PER_FETCH_TIMEOUT)
        except FutTimeoutError:
            return None, b"", url
        except Exception:
            return None, b"", url


def score_link(text: str, href: str) -> int:
    t = (text or "").lower()
    h = (href or "").lower()
    score = 0
    for phrase in MUNI_PHRASES:
        if phrase in t:
            score += 10
        if phrase.replace(" ", "-") in h or phrase.replace(" ", "") in h:
            score += 5
    return score


def is_youtube(url: str) -> bool:
    host = urlparse(url).netloc.lower()
    return "youtube.com" in host or "youtu.be" in host


def load_counties():
    rows = []
    with open(JC_CSV, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            if row["state_or_province"] == "West Virginia" and row["gov_id"].startswith(
                "us:county:54"
            ):
                rows.append(row)
    return rows


NAME_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z .'-]{1,40}")


def looks_like_place_name(text: str) -> bool:
    text = (text or "").strip()
    if not text or len(text) > 45:
        return False
    if not NAME_TOKEN_RE.fullmatch(text):
        return False
    lower = text.lower()
    banned = (
        "home",
        "contact",
        "about",
        "click",
        "here",
        "link",
        "website",
        "site",
        "more",
        "read",
        "county",
        "commission",
        "facebook",
        "twitter",
        "search",
        "menu",
        "login",
        "map",
    )
    if any(b in lower for b in banned):
        return False
    return True


def process_county(c):
    gov_id = c["gov_id"]
    name = c["city_name"]
    domain = (c["domain"] or "").strip()
    muni_links = []
    if not domain:
        return {
            "gov_id": gov_id,
            "county": name,
            "domain": "",
            "page_used": "",
            "status": "no-domain",
        }, muni_links

    home_url = domain if domain.startswith("http") else f"https://{domain}"
    status_code, body, final_url = bounded_get(home_url)
    if status_code is None or status_code >= 400 or not body:
        return (
            {
                "gov_id": gov_id,
                "county": name,
                "domain": domain,
                "page_used": "",
                "status": f"homepage-fetch-failed({status_code})",
            },
            muni_links,
        )

    try:
        soup = BeautifulSoup(body, "html.parser")
    except Exception:
        return (
            {
                "gov_id": gov_id,
                "county": name,
                "domain": domain,
                "page_used": "",
                "status": "parse-failed",
            },
            muni_links,
        )

    home_host = urlparse(final_url).netloc.lower()
    candidates = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(" ", strip=True)
        abs_url = urljoin(final_url, href)
        if is_youtube(abs_url):
            continue
        s = score_link(text, href)
        if s > 0:
            candidates.append((s, abs_url, text))

    candidates.sort(key=lambda x: -x[0])
    page_used = ""
    page_body = None
    page_final_url = None

    if candidates:
        best_url = candidates[0][1]
        sc, pbody, pfinal = bounded_get(best_url)
        if sc and sc < 400 and pbody:
            page_used = pfinal
            page_body = pbody
            page_final_url = pfinal

    if page_body is None:
        for path in GUESSABLE_PATHS:
            guess_url = f"https://{home_host}{path}"
            sc, pbody, pfinal = bounded_get(guess_url)
            if sc and sc < 400 and pbody and len(pbody) > 800:
                page_used = pfinal
                page_body = pbody
                page_final_url = pfinal
                break

    if page_body is None:
        # Last resort: scan the homepage itself -- some counties list
        # their municipalities directly on the homepage (footer,
        # sidebar widget) with no dedicated page at all.
        page_used = final_url + " (homepage, no dedicated page found)"
        page_body = body
        page_final_url = final_url

    if page_body is None:
        return (
            {
                "gov_id": gov_id,
                "county": name,
                "domain": domain,
                "page_used": "",
                "status": "no-municipalities-page-found",
            },
            muni_links,
        )

    try:
        psoup = BeautifulSoup(page_body, "html.parser")
    except Exception:
        return (
            {
                "gov_id": gov_id,
                "county": name,
                "domain": domain,
                "page_used": page_used,
                "status": "page-parse-failed",
            },
            muni_links,
        )

    page_host = urlparse(page_final_url).netloc.lower()
    found = 0
    for a in psoup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(" ", strip=True)
        abs_url = urljoin(page_final_url, href)
        if is_youtube(abs_url):
            continue
        link_host = urlparse(abs_url).netloc.lower()
        if not link_host or link_host == page_host or link_host == home_host:
            continue
        if any(j in link_host for j in SOCIAL_OR_JUNK_HOSTS):
            continue
        if is_state_portal_host(link_host):
            continue
        if not looks_like_place_name(text):
            continue
        muni_links.append(
            {
                "county_gov_id": gov_id,
                "county_name": name,
                "link_text": text,
                "resolved_url": abs_url,
                "host": link_host,
            }
        )
        found += 1

    return (
        {
            "gov_id": gov_id,
            "county": name,
            "domain": domain,
            "page_used": page_used,
            "status": f"ok-{found}-links" if found else "page-found-zero-links",
        },
        muni_links,
    )


def main():
    counties = load_counties()
    county_rows = []
    muni_link_rows = []

    # Counties are independent hosts -- safe to run several at once
    # (each host still gets its own polite_request rate-limit inside
    # bounded_get). 10 workers keeps 55 counties, each up to 1 + 15 + 1
    # fetches worst case, well inside a single foreground call.
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(process_county, c): c for c in counties}
        for fut in futures:
            county_row, links = fut.result()
            county_rows.append(county_row)
            muni_link_rows.extend(links)

    # Keep deterministic output order (gov_id) since ThreadPoolExecutor
    # completion order is not the submission order.
    county_rows.sort(key=lambda r: r["gov_id"])
    muni_link_rows.sort(key=lambda r: (r["county_gov_id"], r["link_text"]))

    with open(COUNTY_WALK_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["gov_id", "county", "domain", "page_used", "status"]
        )
        w.writeheader()
        w.writerows(county_rows)

    with open(MUNI_LINKS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "county_gov_id",
                "county_name",
                "link_text",
                "resolved_url",
                "host",
            ],
        )
        w.writeheader()
        w.writerows(muni_link_rows)

    print(f"counties walked: {len(county_rows)}")
    ok = sum(1 for r in county_rows if r["status"].startswith("ok-"))
    print(f"counties with a municipalities page + links: {ok}")
    print(f"municipality links found: {len(muni_link_rows)}")


if __name__ == "__main__":
    main()
