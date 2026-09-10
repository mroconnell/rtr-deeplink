#!/usr/bin/env python3
"""WO-176 (2026-09-10): own-domain path/feed pilot for four CMS families
(ProudCity, WordPress, CivicLive, OpenCities/Granicus GovAccess) plus a
generic path-and-feed list, tried on 600 "no-platform-link-found"
governments.

WO-154 (`scripts/cms_fingerprint.py`, `app/utils/jurisdiction_data/
cms_families.csv`) measured that only CivicPlus has a reliably guessable
meetings path (`/AgendaCenter`) on a 300-government sample of the
no-platform-link pool -- that's now running at scale as WO-174. Ryan's
idea here: a sweep that alternates across several platform families
never waits on one host's rate limit, so if even one more family's path
guess works, the CivicPlus run (and any future one) gets more efficient
by having other work to interleave with it.

Method, per government:
  1. Fingerprint the homepage with `scripts.cms_fingerprint.classify()`
     (one fetch, honest headers -- the exact HONEST_HEADERS values that
     module and every other sweep script in this repo already use).
  2. Try the GENERIC_PATHS list in order, sitemap first, stopping at the
     first real listing or platform link.
  3. If a family among FAMILY_PATHS was fingerprinted, try that family's
     extra path(s) too (skipped if the generic list already answered).
  4. Cap ~14 requests per government; stop the whole run after 6
     consecutive real (network/exception) errors.

"Works" means a real meetings listing (rows with dates AND an agenda or
video link -- reusing `classify_body()`'s heuristic from
`~/Documents/rtr-business/research/wo141_access_ladder_pilot.py`, same
CHALLENGE_MARKERS/SUBDOMAIN_LINK_PATTERN/MARKETING_SUBDOMAINS constants,
copied here rather than imported since that script lives in a sibling
repo) or a known platform link (a real per-tenant subdomain, not a bare
vendor mention -- the same distinction WO-163 fixed in
`app/platforms/base.py` for Columbus OH's OpenCities generator tag).
NOT a bare HTTP 200 -- Revize's own false-positive lesson from WO-154
applies here too: a guessed path can return a real-looking HTTP 200 page
that is not a real listing at all.

For a sitemap "working": it must name a page whose path or title
contains a meeting word (agenda/minutes/meeting/council/calendar), and
that page must then itself yield a listing or platform link (one more
fetch, counted against the same per-site budget).

Never past a human-verification gate (CHALLENGE_MARKERS below stops that
site immediately, recorded, never solved). No headless browsing. HTTP
only.

Usage (from repo root, worktree .venv):
    python scripts/wo176_path_pilot.py --sample /tmp/wo176_work/wo176_sample_600.csv \
        --out-report ~/Documents/rtr-business/research/wo176_pilot_report.csv \
        --out-stats ~/Documents/rtr-business/research/wo176_path_stats.csv \
        --concurrency 40
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import certifi
import os

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.cms_fingerprint import classify as fingerprint_classify  # noqa: E402
from scripts.cms_fingerprint import HONEST_HEADERS  # noqa: E402

# --- Same constants as wo141_access_ladder_pilot.py (copied, not
# imported -- that script lives in the sibling rtr-business repo). See
# that file's own comments for the real pages each pattern was built
# against.
CHALLENGE_MARKERS = [
    "just a moment",
    "attention required! | cloudflare",
    "checking your browser before accessing",
    "cf-browser-verification",
    "cf-chl-bypass",
    "ddos protection by",
    "sgcaptcha",
    "px-captcha",
    "perimeterx",
    "distil_r_captcha",
    "captcha-delivery",
    "request unsuccessful. incapsula",
    "access to this page has been denied",
]

SUBDOMAIN_LINK_PATTERN = re.compile(
    r"https?://([a-z0-9][a-z0-9-]*)\."
    r"(granicus|legistar|primegov|escribemeetings|iqm2|civicweb|civicclerk|"
    r"swagit|viebit)\.com",
    re.I,
)
MARKETING_SUBDOMAINS = {
    "www",
    "connect",
    "support",
    "help",
    "university",
    "go",
    "info",
    "status",
    "docs",
    "developer",
    "developers",
    "blog",
    "cp-civicplusuniversity2",
}
PATH_SIGNATURES = [
    r"/agendacenter/",
    r"viewpublisher\.php",
    r"agendaviewer\.php",
    r"legistar2\.com",
]
META_TAG_PATTERN = re.compile(r"<meta\b[^>]*>", re.I)
DATE_PATTERN = re.compile(
    r"(january|february|march|april|may|june|july|august|september|"
    r"october|november|december)\s+\d{1,2},?\s+20\d{2}",
    re.I,
)
MEETING_WORD_PATTERN = re.compile(r"agenda|minutes|meeting|council|calendar", re.I)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=12)
PER_HOST_DELAY = 2.0  # seconds -- standing politeness convention, same host
MAX_REQUESTS_PER_SITE = 14
MAX_CONSECUTIVE_ERRORS = 6

# Generic path/feed list, sitemap first -- exactly Ryan's list, in order.
GENERIC_PATHS = [
    "__ROBOTS__",  # special: /robots.txt, parse Sitemap: lines
    "/sitemap.xml",
    "/sitemap",
    "/calendar",
    "/calendar.aspx",
    "/events",
    "/Archive.aspx",
    "/archive",
    "/minutes",
    "/agendas",
    "/agendas-minutes",
    "/meetings",
    "/feed/",
    "/RSSFeed.aspx",
]

# Extra paths tried only for a fingerprinted family, beyond the generic
# list above (skipped if already answered by the generic list, and
# skipped entirely if the per-site request budget is used up).
FAMILY_EXTRA_PATHS: Dict[str, List[str]] = {
    "civiclive": ["/city_hall/agendas___minutes"],
    "wordpress": ["/?s=agenda", "/category/agendas", "/category/meetings"],
    # proudcity's only known guess (/meetings) is already in GENERIC_PATHS.
    # opencities gets no extra *path* -- its extra move is a vendor-host
    # guess, handled separately in `try_opencities_vendor_host()`.
}


def classify_body(text: str) -> str:
    """Return 'challenge', 'platform_link', 'listing', or 'none'."""
    lower_full = text.lower()
    for marker in CHALLENGE_MARKERS:
        if marker in lower_full:
            return "challenge"

    stripped = META_TAG_PATTERN.sub(" ", text)
    lower = stripped.lower()

    for match in SUBDOMAIN_LINK_PATTERN.finditer(lower):
        if match.group(1) not in MARKETING_SUBDOMAINS:
            return "platform_link"
    for pattern in PATH_SIGNATURES:
        if re.search(pattern, lower):
            return "platform_link"

    dates = DATE_PATTERN.findall(stripped)
    if "agenda" in lower and len(dates) >= 3:
        return "listing"
    return "none"


def is_wordpress(html: str, headers: dict) -> bool:
    lower = html.lower()
    if 'name="generator" content="wordpress' in lower:
        return True
    if "/wp-content/" in lower or "/wp-json/" in lower:
        return True
    link_header = headers.get("link", "") if headers else ""
    if "wp-json" in link_header.lower():
        return True
    return False


def guess_slugs(domain: str, name: str) -> List[str]:
    """A small set of vendor-host slug candidates -- same idea as WO-168's
    vendor-host guessing, scaled down to 2 candidates per site given this
    pilot's request budget. Derived from the domain's own label (strip
    www/leading city- prefixes, TLD) and from the government's plain name
    (lowercased, spaces/apostrophes stripped, "city of"/"county of"/"town
    of" prefixes dropped)."""
    host = domain
    if host.startswith("http"):
        host = urlparse(host).netloc
    host = host.split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    label = host.split(".")[0] if host else ""

    clean_name = re.sub(r"^(city|county|town|village) of\s+", "", name.lower()).strip()
    clean_name = re.sub(r"[^a-z0-9]", "", clean_name)

    slugs = []
    if label:
        slugs.append(label)
    if clean_name and clean_name not in slugs:
        slugs.append(clean_name)
    return slugs[:2]


@dataclass
class SiteResult:
    gov_id: str
    name: str
    state: str
    family: str = "unknown"
    paths_tried: List[str] = field(default_factory=list)
    first_path_that_answered: str = ""
    found: bool = False
    platform: str = ""
    outcome: str = ""
    meeting_url: str = ""
    video_url: str = ""
    tier: str = ""
    page_url: str = ""
    note: str = ""


class ConsecutiveErrorBreaker(Exception):
    pass


async def fetch(
    session: aiohttp.ClientSession, url: str, error_counter: List[int]
) -> Tuple[Optional[str], dict, Optional[int], str]:
    try:
        async with session.get(
            url, headers=HONEST_HEADERS, timeout=REQUEST_TIMEOUT, allow_redirects=True
        ) as resp:
            text = await resp.text(errors="replace")
            error_counter[0] = 0
            return text, dict(resp.headers), resp.status, str(resp.url)
    except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
        error_counter[0] += 1
        if error_counter[0] >= MAX_CONSECUTIVE_ERRORS:
            raise ConsecutiveErrorBreaker(str(exc))
        return None, {}, None, str(exc)


def parse_sitemap_for_meeting_pages(xml_text: str) -> List[str]:
    """Return URLs from a sitemap whose <loc> path looks meeting-related."""
    hits = []
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return hits
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = root.findall(".//sm:loc", ns) or root.findall(".//loc")
    for loc in locs:
        url = (loc.text or "").strip()
        if url and MEETING_WORD_PATTERN.search(url):
            hits.append(url)
    return hits[:5]


def parse_robots_sitemaps(text: str) -> List[str]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("sitemap:"):
            out.append(line.split(":", 1)[1].strip())
    return out


async def process_site(
    session: aiohttp.ClientSession,
    row: dict,
    error_counter: List[int],
    skip_generic: bool = False,
) -> SiteResult:
    gov_id = row["gov_id"]
    name = row.get("name", "")
    state = row.get("state", "")
    base_url = row["url"]
    if not base_url.startswith("http"):
        base_url = "https://" + base_url
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    result = SiteResult(gov_id=gov_id, name=name, state=state)
    requests_made = 0

    async def do_fetch(url: str) -> Tuple[Optional[str], dict, Optional[int], str]:
        nonlocal requests_made
        requests_made += 1
        r = await fetch(session, url, error_counter)
        if requests_made > 1:
            await asyncio.sleep(PER_HOST_DELAY)
        return r

    # 1. Homepage fingerprint.
    html, headers, status, final_url = await do_fetch(base_url)
    result.paths_tried.append(f"/:{status}")
    if html is None:
        result.outcome = "fetch_failed"
        result.note = final_url
        return result

    lower_html = html.lower()
    for marker in CHALLENGE_MARKERS:
        if marker in lower_html:
            result.outcome = "challenge_blocked"
            result.note = f"challenge marker on homepage: {marker}"
            return result

    fp = fingerprint_classify(html, headers, final_url)
    family = fp.family
    if family == "unknown" and is_wordpress(html, headers):
        family = "wordpress"
    result.family = family

    verdict = classify_body(html)
    if verdict == "platform_link":
        result.found = True
        result.first_path_that_answered = "/"
        result.outcome = "platform_link_on_homepage"
        m = SUBDOMAIN_LINK_PATTERN.search(META_TAG_PATTERN.sub(" ", html))
        result.platform = m.group(2).lower() if m else ""
        result.note = "platform link found directly on homepage"
        return result

    # 2. Generic path list, sitemap first, stop at first real answer.
    # Skipped entirely in `skip_generic` mode -- a supplemental run used
    # to answer "does a family-specific path add anything beyond the
    # generic list" for a government the main run already tried the
    # generic list on and got `nothing_found` (the main run's per-site
    # budget was consumed by the generic list itself before any family
    # path got a turn -- see wo176_methods_section.md's caution).
    ordered_paths = [] if skip_generic else list(GENERIC_PATHS)
    for path in ordered_paths:
        if requests_made >= MAX_REQUESTS_PER_SITE:
            break
        if path == "__ROBOTS__":
            rhtml, rheaders, rstatus, rurl = await do_fetch(
                urljoin(origin, "/robots.txt")
            )
            result.paths_tried.append(f"/robots.txt:{rstatus}")
            if rhtml:
                sitemap_urls = parse_robots_sitemaps(rhtml)
                for sm_url in sitemap_urls[:2]:
                    if requests_made >= MAX_REQUESTS_PER_SITE:
                        break
                    smhtml, smheaders, smstatus, smfinal = await do_fetch(sm_url)
                    result.paths_tried.append(f"robots-sitemap:{smstatus}")
                    if smhtml:
                        hits = parse_sitemap_for_meeting_pages(smhtml)
                        if hits and requests_made < MAX_REQUESTS_PER_SITE:
                            phtml, pheaders, pstatus, pfinal = await do_fetch(hits[0])
                            result.paths_tried.append(f"sitemap-page:{pstatus}")
                            if phtml:
                                v = classify_body(phtml)
                                if v in ("listing", "platform_link"):
                                    result.found = True
                                    result.first_path_that_answered = (
                                        "robots.txt Sitemap:"
                                    )
                                    result.outcome = f"sitemap_led_to_{v}"
                                    result.meeting_url = hits[0]
                                    if v == "platform_link":
                                        pm = SUBDOMAIN_LINK_PATTERN.search(
                                            META_TAG_PATTERN.sub(" ", phtml)
                                        )
                                        result.platform = (
                                            pm.group(2).lower() if pm else ""
                                        )
                                    return result
            continue

        url = urljoin(origin, path)
        phtml, pheaders, pstatus, pfinal = await do_fetch(url)
        result.paths_tried.append(f"{path}:{pstatus}")
        if phtml is None:
            continue
        if pstatus and pstatus >= 400:
            continue

        if path.endswith(".xml") or path == "/sitemap":
            hits = parse_sitemap_for_meeting_pages(phtml)
            if hits and requests_made < MAX_REQUESTS_PER_SITE:
                ahtml, aheaders, astatus, afinal = await do_fetch(hits[0])
                result.paths_tried.append(f"sitemap-page:{astatus}")
                if ahtml:
                    v = classify_body(ahtml)
                    if v in ("listing", "platform_link"):
                        result.found = True
                        result.first_path_that_answered = path
                        result.outcome = f"sitemap_led_to_{v}"
                        result.meeting_url = hits[0]
                        if v == "platform_link":
                            pm = SUBDOMAIN_LINK_PATTERN.search(
                                META_TAG_PATTERN.sub(" ", ahtml)
                            )
                            result.platform = pm.group(2).lower() if pm else ""
                        return result
            continue

        v = classify_body(phtml)
        if v == "challenge":
            result.outcome = "challenge_blocked"
            result.note = f"challenge marker on {path}"
            return result
        if v in ("listing", "platform_link"):
            result.found = True
            result.first_path_that_answered = path
            result.outcome = f"generic_{v}"
            result.meeting_url = url
            if v == "platform_link":
                pm = SUBDOMAIN_LINK_PATTERN.search(META_TAG_PATTERN.sub(" ", phtml))
                result.platform = pm.group(2).lower() if pm else ""
            return result

    # 3. Family-specific extra paths.
    extra_paths = FAMILY_EXTRA_PATHS.get(family, [])
    for path in extra_paths:
        if requests_made >= MAX_REQUESTS_PER_SITE:
            break
        url = urljoin(origin, path)
        phtml, pheaders, pstatus, pfinal = await do_fetch(url)
        result.paths_tried.append(f"family:{path}:{pstatus}")
        if phtml is None or (pstatus and pstatus >= 400):
            continue
        v = classify_body(phtml)
        if v in ("listing", "platform_link"):
            result.found = True
            result.first_path_that_answered = f"family:{path}"
            result.outcome = f"family_{v}"
            result.meeting_url = url
            if v == "platform_link":
                pm = SUBDOMAIN_LINK_PATTERN.search(META_TAG_PATTERN.sub(" ", phtml))
                result.platform = pm.group(2).lower() if pm else ""
            return result

    if family == "opencities" and requests_made < MAX_REQUESTS_PER_SITE:
        for slug in guess_slugs(base_url, name):
            if requests_made >= MAX_REQUESTS_PER_SITE:
                break
            vendor_url = f"https://{slug}.granicus.com/"
            vhtml, vheaders, vstatus, vfinal = await do_fetch(vendor_url)
            result.paths_tried.append(f"vendor:{vendor_url}:{vstatus}")
            if vhtml and vstatus and vstatus < 400:
                v = classify_body(vhtml)
                if v in ("listing", "platform_link") or "granicus" in vfinal.lower():
                    result.found = True
                    result.first_path_that_answered = f"vendor-host:{vendor_url}"
                    result.outcome = "vendor_host_guess_hit"
                    result.platform = "granicus"
                    result.meeting_url = vfinal
                    return result

    result.outcome = "nothing_found"
    return result


async def run_pilot(
    sample_path: Path,
    concurrency: int,
    limit: Optional[int],
    skip_generic: bool = False,
):
    rows = []
    with open(sample_path) as f:
        for row in csv.DictReader(f):
            rows.append(row)
    if limit:
        rows = rows[:limit]

    error_counter = [0]
    sem = asyncio.Semaphore(concurrency)
    results: List[SiteResult] = []
    aborted = False

    connector = aiohttp.TCPConnector(limit=concurrency * 2, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:

        async def bound_process(row):
            async with sem:
                try:
                    return await process_site(session, row, error_counter, skip_generic)
                except ConsecutiveErrorBreaker as exc:
                    nonlocal aborted
                    aborted = True
                    r = SiteResult(
                        gov_id=row["gov_id"],
                        name=row.get("name", ""),
                        state=row.get("state", ""),
                    )
                    r.outcome = "aborted_consecutive_errors"
                    r.note = str(exc)
                    return r

        tasks = [asyncio.create_task(bound_process(row)) for row in rows]
        for i, task in enumerate(asyncio.as_completed(tasks)):
            r = await task
            results.append(r)
            if i % 25 == 0:
                print(
                    f"[{i + 1}/{len(rows)}] {r.gov_id} family={r.family} outcome={r.outcome}",
                    flush=True,
                )
            if aborted:
                break

    return results, aborted


def write_report(results: List[SiteResult], out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "gov_id",
                "name",
                "state",
                "family",
                "paths_tried",
                "first_path_that_answered",
                "found",
                "platform",
                "outcome",
                "meeting_url",
                "video_url",
                "tier",
                "page_url",
                "note",
            ]
        )
        for r in results:
            w.writerow(
                [
                    r.gov_id,
                    r.name,
                    r.state,
                    r.family,
                    ";".join(r.paths_tried),
                    r.first_path_that_answered,
                    "yes" if r.found else "no",
                    r.platform,
                    r.outcome,
                    r.meeting_url,
                    r.video_url,
                    r.tier,
                    r.page_url,
                    r.note,
                ]
            )


def write_stats(results: List[SiteResult], out_path: Path):
    stats: Dict[Tuple[str, str], Dict[str, int]] = {}
    for r in results:
        for entry in r.paths_tried:
            parts = entry.rsplit(":", 1)
            path = parts[0]
            key = (r.family, path)
            d = stats.setdefault(
                key, {"tried": 0, "answered": 0, "listing": 0, "platform": 0}
            )
            d["tried"] += 1
            if r.found and (
                r.first_path_that_answered == path
                or path.startswith(r.first_path_that_answered)
                or r.first_path_that_answered.endswith(path)
            ):
                d["answered"] += 1
                if r.outcome.endswith("listing"):
                    d["listing"] += 1
                if r.outcome.endswith("platform_link") or "vendor_host" in r.outcome:
                    d["platform"] += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "family",
                "path",
                "tried",
                "answered",
                "listing_found",
                "platform_link_found",
            ]
        )
        for (family, path), d in sorted(stats.items()):
            w.writerow(
                [family, path, d["tried"], d["answered"], d["listing"], d["platform"]]
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", required=True, type=Path)
    parser.add_argument("--out-report", required=True, type=Path)
    parser.add_argument("--out-stats", required=True, type=Path)
    parser.add_argument("--concurrency", type=int, default=40)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--skip-generic",
        action="store_true",
        help=(
            "supplemental mode: skip the generic path/feed list entirely "
            "and go straight to family-specific extra paths (for re-testing "
            "governments the generic list already exhausted the budget on)"
        ),
    )
    args = parser.parse_args()

    start = time.time()
    results, aborted = asyncio.run(
        run_pilot(args.sample, args.concurrency, args.limit, args.skip_generic)
    )
    write_report(results, args.out_report)
    write_stats(results, args.out_stats)
    elapsed = time.time() - start
    found = sum(1 for r in results if r.found)
    print(
        f"\nDone. {len(results)} sites processed in {elapsed:.1f}s, {found} found, aborted={aborted}"
    )


if __name__ == "__main__":
    main()
