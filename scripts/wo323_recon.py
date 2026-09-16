"""WO-323 (2026-09-12): passive discovery v2 at full scale, phase 1 --
reconnaissance. Same pipeline as WO-282 (`wo282_recon.py`, `#1059`,
`docs/investigations/passive_discovery_v2.md`), run against the
~6,750-9,000 leftover governments under 5,000 population WO-264 did not
reach, with one addition:

  - **govAccess/Akamai block.** This machine's address is blocked
    (HTTP 403, server AkamaiGHost) on every government website whose
    `www` CNAME resolves through Granicus govAccess
    (`*.granicusgovaccess.net`) or OpenCities (`*.opencities.com`) --
    confirmed live 2026-09-12 ~07:30 PT as an IP-level WAF block on
    tonight's volume, not a per-government human-verification gate. The
    DNS step records the `www`/apex CNAME as always; any host matching
    one of these two suffixes is recorded `blocked-waf-akamai` (with the
    CNAME as evidence, itself a site-builder signal worth keeping) and
    skipped outright -- no homepage/robots/sitemap/archive fetch is
    attempted -- rather than retried in a loop. These rows are written to
    a separate `wo323_govaccess_deferred.csv` sidecar for a later run
    from a different address, once the conductor lifts the block.

Usage (from the rtr-deeplink repo root, shared venv):
    .venv/bin/python scripts/wo323_recon.py --limit 50 --concurrency 32
    .venv/bin/python scripts/wo323_recon.py --concurrency 32
    .venv/bin/python scripts/wo323_recon.py --finalize
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import statistics
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
import wo273_recon as w273  # noqa: E402

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
POPULATION_CSV = RESEARCH_DIR / "passive_neither_4-canada.csv"
RECON_JSONL = RESEARCH_DIR / "wo323_recon.jsonl"
GOVACCESS_DEFERRED_CSV = RESEARCH_DIR / "wo323_govaccess_deferred.csv"

SCRATCH_DIR = Path(
    "/private/tmp/claude-501/-Users-mroconnell-Documents-rtr-deeplink--claude-worktrees-platform-detection-backfill-c9742a"
    "/1d27de13-eb07-451a-a07a-bb18900b5618/scratchpad/agents/a821c1c44d46057d1/wo323_homepages"
)

HONEST_HEADERS = w273.HEADERS
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

MAX_SUB_SITEMAPS_V2 = 10
SITEMAP_BYTE_CAP = 500_000
MAX_LINKS_RECORDED = 200

HUB_VOCAB = {
    "agenda",
    "agendas",
    "agendacenter",
    "council",
    "commission",
    "commissioners",
    "minutes",
    "board",
    "boards",
    "meeting",
    "meetings",
    "supervisors",
}

CDX_HEALTH_EVERY = 200

# WO-323: this machine's address is blocked (HTTP 403 AkamaiGHost) on every
# government website whose www CNAME resolves through Granicus govAccess
# or OpenCities -- an IP-level WAF block confirmed live 2026-09-12 ~07:30 PT,
# not a per-government human-verification gate. Any such host is recorded
# blocked-waf-akamai with the CNAME as evidence and skipped outright (no
# homepage/robots/sitemap fetch attempted) rather than retried in a loop.
GOVACCESS_CNAME_SUFFIXES = ("granicusgovaccess.net", "opencities.com")
_cdx_health_lock = threading.Lock()
_cdx_healthy = True
_gov_count_since_health_check = 0


def log(msg: str) -> None:
    print(msg, flush=True)


def probe_cdx_health() -> bool:
    """A fresh, cheap CDX call -- not reused from a government's own
    fetch -- so a health read is never confounded with that
    government's own rate limiting or errors."""
    resp = w273.cdx_get(
        "https://web.archive.org/cdx/search/cdx?url=example.com&limit=1&output=json"
    )
    return resp is not None


def maybe_refresh_cdx_health() -> bool:
    global _cdx_healthy, _gov_count_since_health_check
    with _cdx_health_lock:
        _gov_count_since_health_check += 1
        if _gov_count_since_health_check == 1 or (
            _gov_count_since_health_check % CDX_HEALTH_EVERY == 0
        ):
            healthy = probe_cdx_health()
            _cdx_healthy = healthy
            log(
                f"[cdx-health] probe #{_gov_count_since_health_check}: "
                f"{'healthy' if healthy else 'UNHEALTHY'}"
            )
        return _cdx_healthy


def govaccess_cname_match(dns_info: dict) -> str:
    """Returns the matching CNAME (www first, then apex) if either ends in
    a known govAccess/OpenCities suffix, else ''."""
    for key in ("www_cname", "apex_cname"):
        cname = (dns_info.get(key) or "").rstrip(".").lower()
        if cname and cname.endswith(GOVACCESS_CNAME_SUFFIXES):
            return cname
    return ""


def dns_has_any_answer(dns_info: dict) -> bool:
    return bool(
        dns_info.get("apex_a")
        or dns_info.get("apex_cname")
        or dns_info.get("www_a")
        or dns_info.get("www_cname")
    )


def link_position(tag) -> str:
    footer_hit = nav_hit = list_hit = False
    for parent in tag.parents:
        name = getattr(parent, "name", None)
        if name in ("nav", "header"):
            nav_hit = True
        elif name == "footer":
            footer_hit = True
        elif name in ("ul", "ol"):
            list_hit = True
    if nav_hit:
        return "nav"
    if footer_hit:
        return "footer"
    if list_hit:
        return "menu"
    return "body"


def extract_links(html_text: str, final_url: str) -> list[dict]:
    try:
        soup = BeautifulSoup(html_text, "html.parser")
    except Exception:  # noqa: BLE001
        return []
    out = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        full = urljoin(final_url, href)
        if urlparse(full).scheme not in ("http", "https"):
            continue
        if full in seen:
            continue
        seen.add(full)
        out.append(
            {
                "href": full,
                "text": (a.get_text() or "").strip()[:120],
                "position": link_position(a),
            }
        )
        if len(out) >= MAX_LINKS_RECORDED:
            break
    return out


def fetch_homepage(domain: str) -> dict:
    out = {
        "fetched": False,
        "access_mode": "",
        "status": None,
        "final_url": "",
        "homepage_gz_path": "",
        "links": [],
        "link_count": 0,
        "error": "",
        "human_gate": False,
    }
    url = f"https://{domain}/"
    resp = None
    mode = "plain"
    try:
        resp = w273.polite_request(url)
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:200]
        # A dropped connection is grounds for a browser-header retry.
        try:
            resp = w273.RATE_LIMITER.wait_and_request(
                urlparse(url).netloc,
                requests.request,
                "GET",
                url,
                headers=BROWSER_HEADERS,
                timeout=w273.GOV_REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            mode = "browser-headers-after-drop"
        except Exception as e2:  # noqa: BLE001
            out["error"] = str(e2)[:200]
            out["access_mode"] = "blocked-plain-http"
            return out

    if resp is not None and resp.status_code == 403:
        try:
            resp = w273.RATE_LIMITER.wait_and_request(
                urlparse(url).netloc,
                requests.request,
                "GET",
                url,
                headers=BROWSER_HEADERS,
                timeout=w273.GOV_REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            mode = "browser-headers-after-403"
        except Exception as e:  # noqa: BLE001
            out["error"] = str(e)[:200]
            out["access_mode"] = "blocked-plain-http"
            return out

    if resp is None:
        out["access_mode"] = "blocked-plain-http"
        return out

    out["status"] = resp.status_code
    out["final_url"] = resp.url

    if resp.status_code == 404:
        out["access_mode"] = mode
        out["error"] = "http-404"
        return out

    if resp.status_code != 200 or not resp.text:
        out["access_mode"] = (
            "blocked-browser-headers" if "browser" in mode else "blocked-plain-http"
        )
        out["error"] = f"http-{resp.status_code}"
        return out

    if w273.is_challenge(resp.text):
        out["access_mode"] = "cloudflare-challenge-blocked"
        out["human_gate"] = True
        return out

    out["fetched"] = True
    out["access_mode"] = mode
    links = extract_links(resp.text, resp.url)
    out["links"] = links
    out["link_count"] = len(links)

    try:
        SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
        safe_name = domain.replace("/", "_")
        gz_path = SCRATCH_DIR / f"{safe_name}.html.gz"
        with gzip.open(gz_path, "wb") as f:
            f.write(resp.text.encode("utf-8", errors="replace"))
        out["homepage_gz_path"] = str(gz_path)
    except Exception as e:  # noqa: BLE001
        out["error"] = (out["error"] + f"; gz-save-failed: {e}")[:300]

    return out


def parse_crawl_delay(robots_text: str) -> float | None:
    for line in robots_text.splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        if key.strip().lower() == "crawl-delay":
            try:
                return float(value.strip())
            except ValueError:
                continue
    return None


def fetch_live_robots_v2(domain: str) -> dict:
    """Own fetch (not wo273.fetch_live_robots, to avoid a second,
    redundant robots.txt GET just to read Crawl-delay): one request,
    parses sitemap directives, disallow paths (wo273.parse_robots), AND
    Crawl-delay from the same response body. Flags any hub-vocabulary
    Disallow path as disallowed_lead (never fetched)."""
    out = {
        "fetched": False,
        "status": None,
        "sitemap_directives": [],
        "disallow_paths": [],
        "disallows_sitemap": False,
        "crawl_delay_seconds": None,
        "disallowed_lead_paths": [],
        "error": "",
    }
    try:
        resp = w273.polite_request(f"https://{domain}/robots.txt")
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:200]
        return out
    out["status"] = resp.status_code
    if resp.status_code != 200 or not resp.text:
        return out
    if w273.is_challenge(resp.text):
        out["error"] = "challenge-gate"
        return out
    parsed = w273.parse_robots(resp.text)
    out["fetched"] = True
    out["sitemap_directives"] = parsed["sitemap_urls"]
    out["disallow_paths"] = parsed["disallow_paths"][:50]
    out["disallows_sitemap"] = any(
        "sitemap" in d.lower() for d in parsed["disallow_paths"]
    )
    crawl_delay = parse_crawl_delay(resp.text)
    if crawl_delay and crawl_delay > w273.HOST_DELAY_SECONDS:
        # The shared RATE_LIMITER enforces >=HOST_DELAY_SECONDS (2.5s)
        # between any two requests to the SAME host, process-wide -- a
        # floor, not a per-host override. A host that asked for more
        # (robots.txt Crawl-delay) gets an explicit EXTRA sleep on top of
        # that floor, applied thread-locally by fetch_live_sitemap_v2
        # (which owns every further request to this host), never by
        # mutating shared module state -- this script runs many
        # governments, each its own host, concurrently in one thread
        # pool, so any global mutation of the shared rate limiter or a
        # shared module-level cap would race across unrelated hosts.
        out["crawl_delay_seconds"] = crawl_delay
    for path in out["disallow_paths"]:
        low = path.lower()
        if any(word in low for word in HUB_VOCAB):
            out["disallowed_lead_paths"].append(path)
    return out


def fetch_live_sitemap_v2(domain: str, robots_info: dict) -> dict:
    """Own sitemap-follow loop (not wo273.fetch_live_sitemap, which
    hardcodes the module-level MAX_SUB_SITEMAPS cap and the module-level
    polite_request -- both unsafe to override per-call under this
    script's concurrent-governments-per-thread-pool design). Same
    algorithm as wo273's version (robots-named sitemaps first, then the
    three default paths; a sitemapindex is followed one level into its
    highest-priority sub-sitemaps), with: a cap of
    MAX_SUB_SITEMAPS_V2 (10, was 6) sub-sitemaps; a SITEMAP_BYTE_CAP
    (500 KB) truncation applied to every response body before parsing;
    any candidate matching a disallowed_lead path skipped outright; and,
    when this host's robots.txt asked for a Crawl-delay longer than the
    shared limiter's floor, an EXTRA thread-local sleep before every
    request this function makes to that host, on top of the floor the
    shared limiter already provides."""
    disallowed = robots_info.get("disallowed_lead_paths") or []
    crawl_delay = robots_info.get("crawl_delay_seconds")
    extra_sleep = max(0.0, (crawl_delay or 0.0) - w273.HOST_DELAY_SECONDS)

    def is_disallowed(url: str) -> bool:
        path = urlparse(url).path
        return any(d in path for d in disallowed)

    def request_capped(url: str):
        if extra_sleep:
            time.sleep(extra_sleep)
        resp = w273.polite_request(url)
        if len(resp.content or b"") > SITEMAP_BYTE_CAP:
            resp._content = resp.content[:SITEMAP_BYTE_CAP]
        return resp

    out = {
        "found": False,
        "url_used": "",
        "kind": "",
        "sub_sitemaps_followed": 0,
        "url_count": 0,
        "urls": [],
        "error": "",
    }
    if robots_info.get("disallows_sitemap"):
        out["error"] = "robots-disallows-sitemap"
        return out

    base = f"https://{domain}/"
    candidates = [
        urljoin(base, d) for d in (robots_info.get("sitemap_directives") or [])
    ]
    for default in (
        f"https://{domain}/sitemap.xml",
        f"https://{domain}/sitemap_index.xml",
        f"https://{domain}/wp-sitemap.xml",
    ):
        if default not in candidates:
            candidates.append(default)
    candidates = [c for c in candidates if not is_disallowed(c)]
    if not candidates:
        out["error"] = "disallowed-lead-path-skipped"
        return out

    all_urls, used_url, kind, last_error = [], "", "", ""
    for url in candidates:
        try:
            resp = request_capped(url)
        except Exception as e:  # noqa: BLE001
            last_error = str(e)[:200]
            continue
        if resp.status_code != 200 or not resp.content:
            last_error = f"http-{resp.status_code}"
            continue
        if resp.content[:2] != b"\x1f\x8b" and w273.is_challenge(
            resp.content[:4000].decode("utf-8", errors="replace")
        ):
            out["error"] = "challenge-gate"
            return out
        kind, urls = w273.parse_sitemap_xml(resp.content)
        if kind is None:
            continue
        used_url = url
        if kind == "index":
            all_urls.extend(urls)
            followed = 0
            for sub_url in w273.rank_sub_sitemaps(urls)[:MAX_SUB_SITEMAPS_V2]:
                if is_disallowed(sub_url):
                    continue
                try:
                    sub_resp = request_capped(sub_url)
                except Exception:  # noqa: BLE001
                    continue
                if sub_resp.status_code != 200 or not sub_resp.content:
                    continue
                sub_kind, sub_urls = w273.parse_sitemap_xml(sub_resp.content)
                if sub_kind == "urlset":
                    all_urls.extend(sub_urls)
                    followed += 1
            out["sub_sitemaps_followed"] = followed
        else:
            all_urls.extend(urls)
        break

    if not used_url:
        out["error"] = last_error or "no-sitemap-found"
        return out
    out.update(
        found=True,
        url_used=used_url,
        kind=kind,
        error="",
        url_count=len(all_urls),
        urls=all_urls[:2000],
    )
    return out


def process_government_v2(row: dict) -> dict:
    domain = row["domain"]
    timings = {}
    record = {
        "domain": domain,
        "gov_id": row.get("gov_id", ""),
        "name": row.get("name", ""),
        "state": row.get("state", ""),
        "population": row.get("population", ""),
        "group": row.get("group", ""),
        "processed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    cdx_healthy = maybe_refresh_cdx_health()
    record["cdx_healthy_at_time"] = cdx_healthy

    t0 = time.monotonic()
    dns_info = w273.dns_lookup(domain)
    timings["dns_ms"] = int((time.monotonic() - t0) * 1000)
    record["dns"] = dns_info

    if not dns_has_any_answer(dns_info):
        record["dns_gate"] = "dns-unresolvable"
        record["timings_ms"] = timings
        return record
    record["dns_gate"] = "resolved"

    govaccess_cname = govaccess_cname_match(dns_info)
    if govaccess_cname:
        record["access_mode"] = "blocked-waf-akamai"
        record["govaccess_cname"] = govaccess_cname
        record["timings_ms"] = timings
        return record

    archive_sm = {}
    if cdx_healthy:
        t1 = time.monotonic()
        archive_sm = w273.fetch_archived_sitemap_and_robots(domain)
        timings["archive_sitemap_ms"] = int((time.monotonic() - t1) * 1000)
    else:
        archive_sm = {"cdx_reachable": False, "skipped_unhealthy": True}
    sitemap_body_raw = archive_sm.pop("_sitemap_wayback_body_raw", None)

    t2 = time.monotonic()
    homepage_info = fetch_homepage(domain)
    timings["homepage_ms"] = int((time.monotonic() - t2) * 1000)
    record["homepage"] = {
        "fetched": homepage_info["fetched"],
        "access_mode": homepage_info["access_mode"],
        "status": homepage_info["status"],
        "final_url": homepage_info["final_url"],
        "homepage_gz_path": homepage_info["homepage_gz_path"],
        "link_count": homepage_info["link_count"],
        "links": homepage_info["links"],
        "human_gate": homepage_info["human_gate"],
        "error": homepage_info["error"],
    }

    if homepage_info["human_gate"]:
        record["access_mode"] = "cloudflare-challenge-blocked"
        record["timings_ms"] = timings
        return record

    t3 = time.monotonic()
    robots_info = fetch_live_robots_v2(domain)
    timings["robots_ms"] = int((time.monotonic() - t3) * 1000)
    record["robots"] = {
        "fetched": robots_info.get("fetched", False),
        "status": robots_info.get("status"),
        "sitemap_directives": robots_info.get("sitemap_directives", []),
        "disallow_path_count": len(robots_info.get("disallow_paths", [])),
        "disallowed_lead_paths": robots_info.get("disallowed_lead_paths", []),
        "crawl_delay_seconds": robots_info.get("crawl_delay_seconds"),
    }

    t4 = time.monotonic()
    sitemap_stale = (
        archive_sm.get("sitemap_wayback_age_days") is None
        or (archive_sm.get("sitemap_wayback_age_days") or 99999) > w273.STALE_DAYS
    )
    sitemap_source = "none"
    sitemap_urls: list[str] = []
    sitemap_url_count = 0
    if sitemap_body_raw and not sitemap_stale:
        kind, urls = w273.parse_sitemap_xml(sitemap_body_raw)
        if kind == "urlset":
            sitemap_urls, sitemap_url_count, sitemap_source = (
                urls[:2000],
                len(urls),
                "wayback",
            )
        elif kind == "index":
            sitemap_urls, sitemap_url_count, sitemap_source = (
                urls[:2000],
                len(urls),
                "wayback",
            )
    elif sitemap_body_raw and sitemap_stale:
        sitemap_source = "wayback-stale"

    live_sitemap_info = {"found": False, "url_count": 0, "urls": [], "error": "skipped"}
    if sitemap_source in ("none", "wayback-stale"):
        live_sitemap_info = fetch_live_sitemap_v2(domain, robots_info)
        if live_sitemap_info.get("found"):
            sitemap_source = (
                "live" if sitemap_source == "none" else "wayback-stale+live"
            )
            sitemap_urls = live_sitemap_info["urls"]
            sitemap_url_count = live_sitemap_info["url_count"]
    timings["sitemap_ms"] = int((time.monotonic() - t4) * 1000)

    record["sitemap_source"] = sitemap_source
    record["sitemap_url_count"] = sitemap_url_count
    record["sitemap_urls"] = sitemap_urls[:60]
    record["sub_sitemaps_followed"] = live_sitemap_info.get("sub_sitemaps_followed", 0)

    wayback_index = {
        "reachable": False,
        "broad_row_count": 0,
        "narrow_row_count": 0,
        "narrow_urls": [],
        "error": "skipped-unhealthy",
    }
    if cdx_healthy:
        t5 = time.monotonic()
        wayback_index = w273.fetch_wayback_domain_index(domain)
        timings["wayback_index_ms"] = int((time.monotonic() - t5) * 1000)
    record["wayback_index"] = {
        "reachable": wayback_index["reachable"],
        "broad_row_count": wayback_index["broad_row_count"],
        "narrow_row_count": wayback_index["narrow_row_count"],
        "narrow_urls": wayback_index["narrow_urls"],
        "error": wayback_index["error"],
    }

    t6 = time.monotonic()
    crawl_id = w273.probe_common_crawl()
    cc_info = (
        w273.fetch_common_crawl(domain, crawl_id)
        if crawl_id
        else {
            "reachable": False,
            "capture_count": 0,
            "urls": [],
            "error": "cc-probe-failed-skip-whole-run",
        }
    )
    timings["common_crawl_ms"] = int((time.monotonic() - t6) * 1000)
    record["common_crawl"] = {
        "reachable": cc_info["reachable"],
        "capture_count": cc_info["capture_count"],
        "error": cc_info["error"],
    }

    record["access_mode"] = homepage_info["access_mode"] or "unknown"
    record["timings_ms"] = timings
    return record


def load_population() -> list[dict]:
    with open(POPULATION_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_done_domains() -> set:
    done = set()
    if RECON_JSONL.exists():
        with open(RECON_JSONL, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    done.add(json.loads(line)["domain"])
                except Exception:  # noqa: BLE001
                    continue
    return done


_write_lock = threading.Lock()


def load_govaccess_deferred_domains() -> set:
    done = set()
    if GOVACCESS_DEFERRED_CSV.exists():
        with open(GOVACCESS_DEFERRED_CSV, newline="", encoding="utf-8") as f:
            done = {row["domain"] for row in csv.DictReader(f)}
    return done


GOVACCESS_DEFERRED_FIELDNAMES = ["domain", "gov_id", "name", "state", "cname"]


def cmd_sweep(limit: int, concurrency: int) -> None:
    population = load_population()
    done = load_done_domains()
    remaining = [r for r in population if r["domain"] not in done]
    log(f"{len(done)} already done, {len(remaining)} remaining of {len(population)}")

    to_process = remaining[:limit] if limit else remaining
    log(f"processing {len(to_process)} governments at concurrency={concurrency}")

    govaccess_write_header = not GOVACCESS_DEFERRED_CSV.exists()
    start = time.monotonic()
    completed = 0
    errors = 0
    govaccess_deferred = 0
    with (
        open(RECON_JSONL, "a", encoding="utf-8") as out,
        open(GOVACCESS_DEFERRED_CSV, "a", newline="", encoding="utf-8") as ga_out,
        ThreadPoolExecutor(max_workers=concurrency) as pool,
    ):
        ga_writer = csv.DictWriter(ga_out, fieldnames=GOVACCESS_DEFERRED_FIELDNAMES)
        if govaccess_write_header:
            ga_writer.writeheader()
        futures = {pool.submit(process_government_v2, row): row for row in to_process}
        for fut in as_completed(futures):
            row = futures[fut]
            domain = row["domain"]
            try:
                record = fut.result()
            except Exception as e:  # noqa: BLE001
                errors += 1
                record = {
                    "domain": domain,
                    "gov_id": row.get("gov_id", ""),
                    "error": str(e)[:300],
                    "access_mode": "error",
                }
            with _write_lock:
                out.write(json.dumps(record) + "\n")
                out.flush()
                if record.get("access_mode") == "blocked-waf-akamai":
                    govaccess_deferred += 1
                    ga_writer.writerow(
                        {
                            "domain": domain,
                            "gov_id": row.get("gov_id", ""),
                            "name": row.get("name", ""),
                            "state": row.get("state", ""),
                            "cname": record.get("govaccess_cname", ""),
                        }
                    )
                    ga_out.flush()
            completed += 1
            if completed % 10 == 0 or completed == len(to_process):
                elapsed = time.monotonic() - start
                rate = completed / (elapsed / 60) if elapsed > 0 else 0
                log(
                    f"[{completed}/{len(to_process)}] elapsed={elapsed:.0f}s rate={rate:.1f}/min errors={errors} last={domain}"
                )

    elapsed = time.monotonic() - start
    rate = len(to_process) / (elapsed / 60) if elapsed > 0 else 0
    log(
        f"chunk done: {len(to_process)} processed in {elapsed:.0f}s "
        f"({rate:.2f} governments/min), {errors} errors, "
        f"{govaccess_deferred} govaccess/Akamai-deferred, "
        f"{len(remaining) - len(to_process)} remain unprocessed."
    )


def load_all_records() -> list:
    records = []
    if not RECON_JSONL.exists():
        return records
    with open(RECON_JSONL, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:  # noqa: BLE001
                continue
    return records


def cmd_finalize() -> None:
    records = load_all_records()
    total = len(records)
    log(f"{total} records in {RECON_JSONL}")
    if not total:
        return

    dns_gate_counts: dict[str, int] = {}
    access_mode_counts: dict[str, int] = {}
    sitemap_source_counts: dict[str, int] = {}
    step_timings: dict[str, list] = {}
    position_counts: dict[str, int] = {}
    crawl_delay_count = 0
    disallowed_lead_count = 0
    sitemap_count_buckets = {"0": 0, "1": 0, "2+": 0}

    for r in records:
        dns_gate_counts[r.get("dns_gate", "?")] = (
            dns_gate_counts.get(r.get("dns_gate", "?"), 0) + 1
        )
        access_mode_counts[r.get("access_mode", "?")] = (
            access_mode_counts.get(r.get("access_mode", "?"), 0) + 1
        )
        sitemap_source_counts[r.get("sitemap_source", "?")] = (
            sitemap_source_counts.get(r.get("sitemap_source", "?"), 0) + 1
        )
        robots = r.get("robots") or {}
        n_sitemaps = len(robots.get("sitemap_directives") or [])
        if n_sitemaps == 0:
            sitemap_count_buckets["0"] += 1
        elif n_sitemaps == 1:
            sitemap_count_buckets["1"] += 1
        else:
            sitemap_count_buckets["2+"] += 1
        if robots.get("crawl_delay_seconds"):
            crawl_delay_count += 1
        disallowed_lead_count += len(robots.get("disallowed_lead_paths") or [])
        for link in (r.get("homepage") or {}).get("links") or []:
            position_counts[link.get("position", "?")] = (
                position_counts.get(link.get("position", "?"), 0) + 1
            )
        for step, ms in (r.get("timings_ms") or {}).items():
            step_timings.setdefault(step, []).append(ms)

    log("dns_gate split: " + str(dns_gate_counts))
    log("access_mode split: " + str(access_mode_counts))
    log("sitemap_source split: " + str(sitemap_source_counts))
    log("sitemap-count-per-government buckets: " + str(sitemap_count_buckets))
    log(f"crawl-delay present count: {crawl_delay_count}")
    log(f"disallowed_lead path count (summed): {disallowed_lead_count}")
    log("homepage link position counts: " + str(position_counts))
    log("per-step timing (ms), median / p95:")
    for step, vals in step_timings.items():
        vals_sorted = sorted(vals)
        med = statistics.median(vals_sorted)
        p95 = vals_sorted[max(0, int(len(vals_sorted) * 0.95) - 1)]
        log(f"  {step}: median={med:.0f} p95={p95:.0f} n={len(vals)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()

    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)

    if args.finalize:
        cmd_finalize()
        return
    cmd_sweep(args.limit, args.concurrency)


if __name__ == "__main__":
    main()
