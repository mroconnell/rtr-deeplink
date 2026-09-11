#!/usr/bin/env python3
"""WO-179 (2026-09-10): WordPress agenda search at scale, plus three new
CMS families (GovOffice, Municipal Impact, two state-hosted portal
templates) learned from 10 real tenants each and applied, over the
14,553-government `wo174_candidates.csv` population (a domain, no
Archive page yet).

Extends `scripts/wo176_path_pilot.py` and `scripts/cms_fingerprint.py`
rather than forking them -- this module imports their shared constants
and helpers (HONEST_HEADERS, CHALLENGE_MARKERS, classify_body(),
fetch(), parse_sitemap_for_meeting_pages(), GENERIC_PATHS, the
ConsecutiveErrorBreaker circuit breaker) directly. What's new here:

1. **Scale.** WO-176 piloted 600 governments; this runs the same
   fingerprint-first method over the full candidate population, minus
   rows WO-174 already marked `no-video-found`/`off-mission`, minus
   gov_ids WO-174 already found a real CivicPlus AgendaCenter for
   (`agendacenter_hit == "yes"` in `wo174_report.csv`), minus anything
   already covered (a fresh `export_meeting_inventory.py` run), minus
   gov_ids this script's own report already has a row for (resumable --
   see `--report` below).
2. **WordPress goes straight to its own search**, per Ryan's instruction:
   `/?s=agenda`, then if empty `/?s=minutes`, then `/feed/` -- not the
   full generic path list first (WO-176's own caution: the generic list
   alone burns the whole per-site request budget, so on the FIRST full
   run zero sites ever reached a family path at all). ProudCity is
   WordPress's own subfamily and gets the identical treatment.
3. **Three new families, each learned from 10 real tenants** (see
   `scripts/cms_fingerprint.py`'s new rules and
   `app/utils/jurisdiction_data/cms_families.csv` for the full evidence):
   - `govoffice` (govoffice[23]?.com) -- no single guessable path;
     nav-scan the already-fetched homepage for a meeting-word link,
     else try `/sitemap.xml` once.
   - `municipalimpact` (municipalimpact.com) -- `/agendas` then
     `/minutes`, confirmed on 8 of 9 real tenants.
   - `in_gov_towns_portal` (www.in.gov/towns/{slug}/) -- construct
     `/towns/{slug}/meetings` directly.
   `wv_local_gov` (the fourth new family, West Virginia's shared
   SharePoint portal) has NO confirmed path -- it falls through to the
   same generic path/sitemap list every other recognised-but-unconfirmed
   family (Revize, OpenCities, CivicLive, Town Web) already gets here.
4. **CivicPlus (WO-174 territory) gets exactly one extra try**, per
   Ryan's instruction: WO-174 owns `/AgendaCenter` at scale, so a
   government this script independently fingerprints as CivicPlus only
   ever gets `/sitemap.xml` tried once, never the AgendaCenter path
   itself (that would duplicate WO-174's own sweep).
5. **Unrecognised (`unknown`) sites get exactly one request**:
   `/sitemap.xml`, per Ryan's instruction (WO-176 measured only 4 of 356
   unknowns ever answered from the full generic list -- not worth the
   budget at 13,729-government scale).

Interleaving/politeness: identical structural approach to
`wo176_path_pilot.py` -- `asyncio.Semaphore`-bounded concurrency across
many distinct hosts processed via `asyncio.as_completed`, with a 2s
delay only between *sequential* requests to the SAME site. At this
scale (13,729 distinct hosts, default concurrency 40) no single host
ever sees two requests within 2s, and the run never idles waiting on one
slow host. Checkpointed every row (see `--report`, opened in append mode
on a resume) rather than only every 500, so a kill mid-run loses at most
the one in-flight batch -- "every ~500" from the work order is satisfied
trivially by writing every row.

Usage (repo root, worktree venv):
    python scripts/export_meeting_inventory.py --out-dir /tmp/wo179_inventory --source export
    python scripts/wo179_family_scale.py \\
        --candidates ~/Documents/rtr-business/research/wo174_candidates.csv \\
        --wo174-report ~/Documents/rtr-business/research/wo174_report.csv \\
        --inventory-csv /tmp/wo179_inventory/meeting_inventory.csv \\
        --report ~/Documents/rtr-business/research/wo179_report.csv \\
        --stats ~/Documents/rtr-business/research/wo179_family_stats.csv \\
        --seeds ~/Documents/rtr-business/research/wo179_discovery_seeds.csv \\
        --concurrency 40
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.utils.url_guard import (  # noqa: E402
    MAX_RESPONSE_BYTES,
    BlockedURLError,
    read_capped_text,
)
from scripts.cms_fingerprint import classify as fingerprint_classify  # noqa: E402
from scripts.wo176_path_pilot import (  # noqa: E402
    CHALLENGE_MARKERS,
    GENERIC_PATHS,
    HONEST_HEADERS,
    META_TAG_PATTERN,
    SUBDOMAIN_LINK_PATTERN,
    ConsecutiveErrorBreaker,
    classify_body,
    is_wordpress,
    parse_robots_sitemaps,
    parse_sitemap_for_meeting_pages,
)

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=12)
PER_HOST_DELAY = 2.0
MAX_REQUESTS_PER_SITE = 14
MAX_CONSECUTIVE_ERRORS = 6
CHECKPOINT_EVERY = 500  # progress print / stats-flush cadence, not the write cadence
# Belt-and-braces safety net -- see `bound()`'s own comment for the real
# incident this guards against. Generous relative to the real per-site
# budget (up to 4 requests x 12s timeout x 2s delay is already well
# under a minute in the worst real case), so this should only ever fire
# on a genuinely pathological government, never a normal slow one.
PER_GOVERNMENT_WALL_CLOCK_CAP = 120  # seconds

NAV_LINK = re.compile(r'<a\b[^>]*href="([^"]+)"[^>]*>([^<]{0,80})</a>', re.I)
MEETING_WORD = re.compile(r"agenda|minutes|meeting|council|calendar|board", re.I)

SOURCE_TAG = "wo179_family_scale"

REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "population",
    "domain",
    "family",
    "family_evidence",
    "path_that_answered",
    "listing_found",
    "platform_found",
    "outcome",
    "reject_reason",
    "reject_class",
    "meeting_url",
    "video_url",
    "tier",
    "page_url",
    "requests_made",
    "note",
]


@dataclass
class Row:
    gov_id: str
    name: str
    state: str
    gov_kind: str
    population: str
    domain: str
    family: str = "unknown"
    family_evidence: str = ""
    path_that_answered: str = ""
    listing_found: str = "no"
    platform_found: str = ""
    outcome: str = ""
    reject_reason: str = ""
    reject_class: str = ""
    meeting_url: str = ""
    video_url: str = ""
    tier: str = ""
    page_url: str = ""
    requests_made: int = 0
    note: str = ""

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        return d


def _nav_meeting_links(html: str, base_url: str) -> List[str]:
    """Homepage nav-link scan for a meeting-word href or label text --
    the "menu text" step Ryan's instructions ask for GovOffice/Municipal
    Impact/state-hosted. Zero extra network cost (works off HTML already
    in hand)."""
    hits = []
    for m in NAV_LINK.finditer(html):
        href, label = m.group(1), m.group(2).strip()
        if MEETING_WORD.search(href) or MEETING_WORD.search(label):
            hits.append(urljoin(base_url, href))
    # de-dup, keep order
    seen: Set[str] = set()
    out = []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


class Aborted(Exception):
    pass


async def process_gov(
    session: aiohttp.ClientSession,
    row_in: dict,
    error_counter: List[int],
) -> Row:
    gov_id = row_in["gov_id"]
    name = row_in.get("name", "")
    state = row_in.get("state", "")
    gov_kind = row_in.get("gov_kind", "")
    population = row_in.get("population", "")
    domain = row_in.get("domain", "")

    result = Row(
        gov_id=gov_id,
        name=name,
        state=state,
        gov_kind=gov_kind,
        population=population,
        domain=domain,
    )

    base_url = domain
    if not base_url.startswith("http"):
        base_url = "https://" + base_url
    parsed = urlparse(base_url)
    origin = f"{parsed.scheme}://{parsed.netloc}"

    async def do_fetch(url: str) -> Tuple[Optional[str], dict, Optional[int], str]:
        if result.requests_made > 0:
            await asyncio.sleep(PER_HOST_DELAY)
        result.requests_made += 1
        try:
            async with session.get(
                url,
                headers=HONEST_HEADERS,
                timeout=REQUEST_TIMEOUT,
                allow_redirects=True,
            ) as resp:
                # WO-166's own real-incident lesson applied here: a
                # government URL can point at a multi-hundred-MB file
                # (a misconfigured server serving a huge asset as
                # text/html, or a giant XML/sitemap) rather than a normal
                # page. Reading and decoding that in full, then running
                # this sweep's several regex/XML passes over the result,
                # is what actually caused a real multi-minute stall
                # during this WO's own live run (confirmed: the process
                # sat at 99% CPU processing a single government for
                # minutes with zero network activity once the body was
                # already in hand). `read_capped_text()` (same helper
                # `app/utils/url_guard.py` already uses for exactly this
                # class of bug) rejects anything over 10MB instead.
                try:
                    text = await read_capped_text(resp)
                except BlockedURLError:
                    error_counter[0] = 0
                    return (
                        None,
                        dict(resp.headers),
                        resp.status,
                        f"response too large (>{MAX_RESPONSE_BYTES} bytes): {url}",
                    )
                error_counter[0] = 0
                return text, dict(resp.headers), resp.status, str(resp.url)
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            error_counter[0] += 1
            if error_counter[0] >= MAX_CONSECUTIVE_ERRORS:
                # Real bug, found live 2026-09-10: this used to raise
                # this module's own `Aborted` (meant only for the
                # per-government "stop THIS government, a challenge
                # marker fired" shortcut inside `try_path`/
                # `try_sitemap_once`) instead of the imported
                # `ConsecutiveErrorBreaker` `bound()` actually catches.
                # Whether that mistaken `Aborted` got swallowed by
                # `process_gov`'s own inner `except Aborted: pass` or
                # escaped uncaught depended on which fetch call site hit
                # the threshold -- the homepage fetch sits outside that
                # inner try/except, so a real circuit-breaker trip there
                # propagated all the way up as an unhandled exception and
                # crashed the whole run instead of stopping it cleanly
                # (the graceful-shutdown code added earlier this session
                # never even ran). No data was lost either way -- every
                # row is flushed before this point -- but the run should
                # stop itself cleanly, not crash.
                raise ConsecutiveErrorBreaker(str(exc))
            return None, {}, None, str(exc)

    def mark_listing(url: str, path_label: str, family: Optional[str] = None):
        result.listing_found = "yes"
        result.path_that_answered = path_label
        result.meeting_url = url
        if family:
            result.family = family

    def mark_platform(url: str, platform: str, path_label: str):
        result.platform_found = platform
        result.listing_found = "yes"
        result.path_that_answered = path_label
        result.meeting_url = url

    # --- 1. Homepage fetch + fingerprint ---------------------------------
    html, headers, status, final_url = await do_fetch(base_url)
    if html is None:
        result.outcome = "dead"
        result.note = f"homepage unreachable: {final_url}"
        return result

    lower_html = html.lower()
    for marker in CHALLENGE_MARKERS:
        if marker in lower_html:
            result.outcome = "blocked"
            result.note = f"human-verification challenge marker on homepage: {marker}"
            return result

    fp = fingerprint_classify(html, headers, final_url)
    family = fp.family
    if family == "unknown" and is_wordpress(html, headers):
        family = "wordpress"
    result.family = family
    result.family_evidence = fp.evidence or fp.rule_id

    verdict = classify_body(html)
    if verdict == "platform_link":
        m = SUBDOMAIN_LINK_PATTERN.search(META_TAG_PATTERN.sub(" ", html))
        platform = m.group(2).lower() if m else ""
        mark_platform(final_url, platform, "/")
        return result
    if verdict == "listing":
        mark_listing(final_url, "/")
        return result

    origin = f"{urlparse(final_url).scheme}://{urlparse(final_url).netloc}"

    async def try_path(path: str) -> Optional[Tuple[str, str, str]]:
        """Fetch `path` (an absolute URL if it starts with http, else
        joined to `origin`). Returns (verdict, final_url, html) if a
        real listing/platform link/challenge was found, else None (also
        None on a fetch failure or 4xx)."""
        url = path if path.startswith("http") else urljoin(origin, path)
        phtml, pheaders, pstatus, pfinal = await do_fetch(url)
        if phtml is None or (pstatus and pstatus >= 400):
            return None
        v = classify_body(phtml)
        if v == "challenge":
            result.outcome = "blocked"
            result.note = f"human-verification challenge marker on {path}"
            raise Aborted("challenge")  # short-circuit this government only
        if v in ("listing", "platform_link"):
            return v, pfinal, phtml
        return None

    async def try_sitemap_once(label: str) -> bool:
        """Try /sitemap.xml once -- exactly one request, per Ryan's
        instruction for CivicPlus (WO-174 territory) and `unknown`
        families. Classifies the sitemap XML's own text directly with
        `classify_body()` -- this does NOT fetch a second page for a
        named `<loc>` entry (that would be a second request); it can
        still return "platform_link" because `classify_body()`'s
        `PATH_SIGNATURES` check matches known platform path shapes
        (e.g. `/agendacenter/`) anywhere in the text, including inside a
        sitemap's own listed URLs -- a real, if serendipitous, signal
        that a page the homepage fingerprint alone missed exists on this
        site. Returns True if this settled the government (found or
        challenge)."""
        try:
            r = await try_path("/sitemap.xml")
        except Aborted:
            return True
        if r is None:
            return False
        v, pfinal, phtml = r
        if v == "platform_link":
            m = SUBDOMAIN_LINK_PATTERN.search(META_TAG_PATTERN.sub(" ", phtml))
            mark_platform(pfinal, m.group(2).lower() if m else "", label)
        else:
            mark_listing(pfinal, label)
        return True

    try:
        # --- 2a. WordPress (and ProudCity, its own WordPress subfamily) --
        if family in ("wordpress", "proudcity"):
            for path, label in (
                ("/?s=agenda", "wordpress:/?s=agenda"),
                ("/?s=minutes", "wordpress:/?s=minutes"),
                ("/feed/", "wordpress:/feed/"),
            ):
                if result.requests_made >= MAX_REQUESTS_PER_SITE:
                    break
                r = await try_path(path)
                if r:
                    v, pfinal, phtml = r
                    if v == "platform_link":
                        m = SUBDOMAIN_LINK_PATTERN.search(
                            META_TAG_PATTERN.sub(" ", phtml)
                        )
                        mark_platform(pfinal, m.group(2).lower() if m else "", label)
                    else:
                        mark_listing(pfinal, label)
                    break

        # --- 2b. GovOffice: menu text, then sitemap -----------------------
        elif family == "govoffice":
            nav_links = _nav_meeting_links(html, final_url)
            settled = False
            for link in nav_links[:2]:
                if result.requests_made >= MAX_REQUESTS_PER_SITE:
                    break
                r = await try_path(link)
                if r:
                    v, pfinal, phtml = r
                    if v == "platform_link":
                        m = SUBDOMAIN_LINK_PATTERN.search(
                            META_TAG_PATTERN.sub(" ", phtml)
                        )
                        mark_platform(
                            pfinal,
                            m.group(2).lower() if m else "",
                            "govoffice:nav-link",
                        )
                    else:
                        mark_listing(pfinal, "govoffice:nav-link")
                    settled = True
                    break
            if not settled and result.requests_made < MAX_REQUESTS_PER_SITE:
                await try_sitemap_once("govoffice:/sitemap.xml")

        # --- 2c. Municipal Impact: /agendas, /minutes ---------------------
        elif family == "municipalimpact":
            for path, label in (
                ("/agendas", "municipalimpact:/agendas"),
                ("/minutes", "municipalimpact:/minutes"),
            ):
                if result.requests_made >= MAX_REQUESTS_PER_SITE:
                    break
                r = await try_path(path)
                if r:
                    v, pfinal, phtml = r
                    if v == "platform_link":
                        m = SUBDOMAIN_LINK_PATTERN.search(
                            META_TAG_PATTERN.sub(" ", phtml)
                        )
                        mark_platform(pfinal, m.group(2).lower() if m else "", label)
                    else:
                        mark_listing(pfinal, label)
                    break

        # --- 2d. Indiana's shared towns portal ----------------------------
        elif family == "in_gov_towns_portal":
            path_match = re.match(
                r"^(/towns/[a-z0-9-]+)/?", urlparse(final_url).path, re.I
            )
            if path_match and result.requests_made < MAX_REQUESTS_PER_SITE:
                meetings_url = urljoin(origin, path_match.group(1) + "/meetings")
                r = await try_path(meetings_url)
                if r:
                    v, pfinal, phtml = r
                    if v == "platform_link":
                        m = SUBDOMAIN_LINK_PATTERN.search(
                            META_TAG_PATTERN.sub(" ", phtml)
                        )
                        mark_platform(
                            pfinal,
                            m.group(2).lower() if m else "",
                            "in_gov_towns_portal:/towns/{slug}/meetings",
                        )
                    else:
                        mark_listing(
                            pfinal, "in_gov_towns_portal:/towns/{slug}/meetings"
                        )

        # --- 2e. CivicPlus (WO-174's own territory) -- sitemap only -------
        elif family == "civicplus":
            await try_sitemap_once("civicplus:/sitemap.xml")

        # --- 2f. Unrecognised -- one request only, per Ryan's instruction -
        elif family == "unknown":
            await try_sitemap_once("unknown:/sitemap.xml")

        # --- 2g. Every other recognised-but-out-of-scope family (Revize,
        # OpenCities, CivicLive, Town Web, wv_local_gov, municode_web) --
        # none has a confirmed guessable path (see cms_families.csv), so
        # fall back to the same generic sitemap/path list WO-176 already
        # measured against them.
        else:
            for path in GENERIC_PATHS:
                if result.requests_made >= MAX_REQUESTS_PER_SITE:
                    break
                if path == "__ROBOTS__":
                    rhtml, _, rstatus, _ = await do_fetch(
                        urljoin(origin, "/robots.txt")
                    )
                    if rhtml:
                        for sm_url in parse_robots_sitemaps(rhtml)[:2]:
                            if result.requests_made >= MAX_REQUESTS_PER_SITE:
                                break
                            smhtml, _, smstatus, _ = await do_fetch(sm_url)
                            if smhtml:
                                hits = parse_sitemap_for_meeting_pages(smhtml)
                                if (
                                    hits
                                    and result.requests_made < MAX_REQUESTS_PER_SITE
                                ):
                                    r = await try_path(hits[0])
                                    if r:
                                        v, pfinal, phtml = r
                                        mark_listing(pfinal, f"{family}:robots-sitemap")
                                        break
                    if result.listing_found == "yes":
                        break
                    continue
                if path.endswith(".xml") or path == "/sitemap":
                    r = await try_path(path)
                    if r is None:
                        continue
                    v, pfinal, phtml = r
                    hits = (
                        parse_sitemap_for_meeting_pages(phtml)
                        if path.endswith(".xml")
                        else []
                    )
                    if hits and result.requests_made < MAX_REQUESTS_PER_SITE:
                        r2 = await try_path(hits[0])
                        if r2:
                            v2, pfinal2, phtml2 = r2
                            mark_listing(pfinal2, f"{family}:{path}->sitemap-page")
                            break
                    continue
                r = await try_path(path)
                if r:
                    v, pfinal, phtml = r
                    if v == "platform_link":
                        m = SUBDOMAIN_LINK_PATTERN.search(
                            META_TAG_PATTERN.sub(" ", phtml)
                        )
                        mark_platform(
                            pfinal, m.group(2).lower() if m else "", f"{family}:{path}"
                        )
                    else:
                        mark_listing(pfinal, f"{family}:{path}")
                    break
    except Aborted:
        pass

    if result.listing_found != "yes" and not result.outcome:
        result.outcome = "no_listing"
        result.note = f"family={result.family}: nothing found in {result.requests_made} request(s)"

    return result


def load_population(
    candidates_csv: Path,
    wo174_report_csv: Path,
    inventory_csv: Path,
    already_done: Set[str],
) -> List[dict]:
    skip_reasons: Dict[str, int] = {}
    wo174_civicplus_hits: Set[str] = set()
    if wo174_report_csv.exists():
        with open(wo174_report_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("agendacenter_hit") == "yes":
                    wo174_civicplus_hits.add(row["gov_id"])

    covered: Set[str] = set()
    if inventory_csv.exists():
        with open(inventory_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                gid = row.get("gov_id") or row.get("national_gov_id")
                if gid:
                    covered.add(gid)

    out = []
    with open(candidates_csv, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            gid = row["gov_id"]
            reason = row.get("prior_reason", "")
            if reason in ("no-video-found", "off-mission"):
                skip_reasons["prior_reason"] = skip_reasons.get("prior_reason", 0) + 1
                continue
            if gid in wo174_civicplus_hits:
                skip_reasons["wo174_agendacenter"] = (
                    skip_reasons.get("wo174_agendacenter", 0) + 1
                )
                continue
            if gid in covered:
                skip_reasons["already_covered"] = (
                    skip_reasons.get("already_covered", 0) + 1
                )
                continue
            if gid in already_done:
                skip_reasons["already_processed_this_run"] = (
                    skip_reasons.get("already_processed_this_run", 0) + 1
                )
                continue
            out.append(row)

    print(
        f"Population after filtering: {len(out)}. Skipped: {skip_reasons}", flush=True
    )
    return out


def write_stats_from_report(report_csv: Path, stats_csv: Path) -> None:
    """(Re)writes `stats_csv` from the FULL, cumulative `report_csv` --
    not from one run's own in-memory tally -- so it's correct no matter
    how many resumed runs it took to reach this point. See this
    function's only call site for the real bug this replaced."""
    stats: Dict[str, Dict[str, int]] = {}
    if report_csv.exists():
        with open(report_csv, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                d = stats.setdefault(
                    row["family"], {"sites": 0, "listing_found": 0, "video_found": 0}
                )
                d["sites"] += 1
                if row.get("listing_found") == "yes":
                    d["listing_found"] += 1
                if row.get("platform_found"):
                    d["video_found"] += 1

    with open(stats_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["family", "sites", "listing_found", "video_found"])
        for fam, d in sorted(stats.items()):
            w.writerow([fam, d["sites"], d["listing_found"], d["video_found"]])


def _already_processed_gov_ids(report_csv: Path) -> Set[str]:
    if not report_csv.exists():
        return set()
    with open(report_csv, newline="", encoding="utf-8") as f:
        return {row["gov_id"] for row in csv.DictReader(f)}


async def run(
    candidates_csv: Path,
    wo174_report_csv: Path,
    inventory_csv: Path,
    report_csv: Path,
    stats_csv: Path,
    seeds_csv: Path,
    concurrency: int,
    limit: Optional[int],
):
    already_done = _already_processed_gov_ids(report_csv)
    print(f"{len(already_done)} gov_ids already in {report_csv} from a prior run.")
    rows_in = load_population(
        candidates_csv, wo174_report_csv, inventory_csv, already_done
    )
    if limit:
        rows_in = rows_in[:limit]
    print(f"Processing {len(rows_in)} governments this run.", flush=True)

    report_csv.parent.mkdir(parents=True, exist_ok=True)
    is_new = not report_csv.exists()
    report_f = open(report_csv, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(report_f, fieldnames=REPORT_FIELDS, lineterminator="\n")
    if is_new:
        writer.writeheader()
        report_f.flush()

    seeds_csv.parent.mkdir(parents=True, exist_ok=True)
    seeds_is_new = not seeds_csv.exists()
    seeds_f = open(seeds_csv, "a", newline="", encoding="utf-8")
    seeds_writer = csv.writer(seeds_f, lineterminator="\n")
    if seeds_is_new:
        seeds_writer.writerow(["netloc", "platform", "gov_id", "access_mode"])
        seeds_f.flush()

    family_stats: Dict[str, Dict[str, int]] = {}
    error_counter = [0]
    sem = asyncio.Semaphore(concurrency)
    aborted = False
    processed = 0
    start = time.time()

    # force_close=True + enable_cleanup_closed=True: real, confirmed fix
    # for a mid-run stall found in this WO's own live run (2026-09-10) --
    # the default connection-reuse pool accumulated dozens of CLOSE_WAIT
    # sockets (many real government hosts close the connection right
    # after responding, e.g. Sucuri-proxied and shared-hosting sites)
    # faster than aiohttp's pool released them, and throughput dropped to
    # near zero once the pool's `limit` was effectively exhausted by
    # sockets nobody had reclaimed yet. At this sweep's scale (13,000+
    # distinct hosts, almost never revisited) connection reuse buys
    # nothing anyway, so forcing a fresh connection per request is a
    # clean fix with no real throughput cost.
    connector = aiohttp.TCPConnector(
        limit=concurrency * 2, ssl=False, force_close=True, enable_cleanup_closed=True
    )
    async with aiohttp.ClientSession(connector=connector) as session:

        async def bound(row_in):
            async with sem:
                try:
                    # Belt-and-braces wall-clock cap, on top of the
                    # per-request ClientTimeout and read_capped_text()'s
                    # size cap above: real, confirmed live during this
                    # WO's own run, some single government can still eat
                    # far more real time than its own request budget
                    # should allow (an oversized response processed
                    # before the size cap fix existed, in this case) --
                    # this guarantees one pathological government can
                    # never stall the whole run indefinitely.
                    return await asyncio.wait_for(
                        process_gov(session, row_in, error_counter),
                        timeout=PER_GOVERNMENT_WALL_CLOCK_CAP,
                    )
                except asyncio.TimeoutError:
                    r = Row(
                        gov_id=row_in["gov_id"],
                        name=row_in.get("name", ""),
                        state=row_in.get("state", ""),
                        gov_kind=row_in.get("gov_kind", ""),
                        population=row_in.get("population", ""),
                        domain=row_in.get("domain", ""),
                    )
                    r.outcome = "error"
                    r.note = f"exceeded {PER_GOVERNMENT_WALL_CLOCK_CAP}s wall-clock safety cap"
                    return r
                except ConsecutiveErrorBreaker as exc:
                    nonlocal aborted
                    aborted = True
                    r = Row(
                        gov_id=row_in["gov_id"],
                        name=row_in.get("name", ""),
                        state=row_in.get("state", ""),
                        gov_kind=row_in.get("gov_kind", ""),
                        population=row_in.get("population", ""),
                        domain=row_in.get("domain", ""),
                    )
                    r.outcome = "error"
                    r.note = f"aborted after {MAX_CONSECUTIVE_ERRORS} consecutive errors: {exc}"
                    return r

        tasks = [asyncio.create_task(bound(r)) for r in rows_in]
        try:
            for task in asyncio.as_completed(tasks):
                r = await task
                writer.writerow(r.as_dict())
                report_f.flush()

                stats = family_stats.setdefault(
                    r.family, {"sites": 0, "listing_found": 0, "video_found": 0}
                )
                stats["sites"] += 1
                if r.listing_found == "yes":
                    stats["listing_found"] += 1
                if r.platform_found:
                    stats["video_found"] += 1
                    netloc = urlparse(r.meeting_url).netloc.lower()
                    if netloc:
                        seeds_writer.writerow(
                            [netloc, r.platform_found, r.gov_id, "plain"]
                        )
                        seeds_f.flush()

                processed += 1
                if processed % 25 == 0 or processed == len(rows_in):
                    elapsed = time.time() - start
                    rate = processed / elapsed if elapsed else 0
                    print(
                        f"[{processed}/{len(rows_in)}] {r.gov_id} family={r.family} "
                        f"listing_found={r.listing_found} outcome={r.outcome} "
                        f"({rate:.2f}/s)",
                        flush=True,
                    )
                if aborted:
                    print("Circuit breaker tripped -- stopping early.", flush=True)
                    for t in tasks:
                        t.cancel()
                    # Real, confirmed live 2026-09-10: cancelling and
                    # immediately `break`-ing out of the `async with
                    # session` block let several still-in-flight tasks
                    # try to use the session AFTER it closed, each
                    # raising an unretrieved `RuntimeError("Session is
                    # closed")` -- cosmetic (this run's own rows were
                    # already all written; nothing was lost), but noisy
                    # and worth a clean exit. Awaiting every task's
                    # cancellation here, still inside the session's
                    # context, lets each one finish (or accept its
                    # CancelledError) before the session actually closes.
                    await asyncio.gather(*tasks, return_exceptions=True)
                    break
        finally:
            report_f.close()
            seeds_f.close()

    # Real bug, found live 2026-09-10: this used to write only THIS
    # run's own in-memory `family_stats` -- fine for a single unbroken
    # run, but a resumed run that processes 0 new governments (the
    # common last step after several circuit-breaker restarts) would
    # overwrite a previous run's real, non-empty stats file with an
    # empty one. Recomputed from the full, cumulative `report_csv`
    # instead, so this is correct regardless of how many restarts it
    # took to finish.
    write_stats_from_report(report_csv, stats_csv)

    print(f"\nDone. {processed} governments processed this run, aborted={aborted}.")
    print(f"Report: {report_csv}\nStats: {stats_csv}\nSeeds: {seeds_csv}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidates",
        type=Path,
        default=Path(
            "~/Documents/rtr-business/research/wo174_candidates.csv"
        ).expanduser(),
    )
    parser.add_argument(
        "--wo174-report",
        type=Path,
        default=Path("~/Documents/rtr-business/research/wo174_report.csv").expanduser(),
    )
    parser.add_argument("--inventory-csv", type=Path, required=True)
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("~/Documents/rtr-business/research/wo179_report.csv").expanduser(),
    )
    parser.add_argument(
        "--stats",
        type=Path,
        default=Path(
            "~/Documents/rtr-business/research/wo179_family_stats.csv"
        ).expanduser(),
    )
    parser.add_argument(
        "--seeds",
        type=Path,
        default=Path(
            "~/Documents/rtr-business/research/wo179_discovery_seeds.csv"
        ).expanduser(),
    )
    parser.add_argument("--concurrency", type=int, default=40)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    asyncio.run(
        run(
            args.candidates,
            args.wo174_report,
            args.inventory_csv,
            args.report,
            args.stats,
            args.seeds,
            args.concurrency,
            args.limit,
        )
    )


if __name__ == "__main__":
    main()
