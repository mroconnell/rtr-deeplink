"""WO-273 (2026-09-12): full-scale passive platform discovery, phase 1 --
fast, parallel, raw reconnaissance.

Ryan's design for WO-273 splits WO-268's pilot (one government at a time,
politeness waits inside every step -- 100 minutes for 300 domains) into
three phases: this script (phase 1, fast/parallel/raw), a pure offline
classifier (`wo273_classify.py`, phase 2, so scoring rules can be rerun
without refetching anything), and a targeted-fetch pass over the specific
URLs phase 2 flags (`wo273_targeted.py`, phase 3, many governments at
once since each is on its own domain). This script never ingests, never
writes a queue line, and never touches `jurisdiction_coverage.csv` -- its
only output is one JSON-lines file per government
(`research/wo273_recon.jsonl`), resumable by domain.

Per government this script records, and does NOT classify:
  - Sitemap discovery, archive-first (Ryan, 2026-09-12): ask Wayback CDX
    for a capture of `<domain>/sitemap*` (a prefix query catching
    sitemap.xml/sitemap_index.xml/sitemapindex.xml) and of
    `<domain>/robots.txt`, and read the newest capture's raw body via the
    `id_` form (`web.archive.org/web/<ts>id_/<url>`) -- costs the
    government nothing. Falls back to a LIVE robots.txt + sitemap fetch
    only when the archive has no capture, or the capture is stale
    (>=~18 months old) and the site answers live.
  - DNS: apex/www A+CNAME, a fixed list of own-domain subdomain guesses,
    and guessed vendor-tenant labels ONLY for civicweb.net and
    primegov.com (the other four named vendors wildcard their own DNS --
    WO-268's confirmed, live-tested finding; see
    docs/investigations/passive_platform_discovery_pilot.md).
  - Wayback CDX for the domain itself: TWO bounded queries -- a broad one
    (`url=<domain>/*`, `collapse=urlkey`, `filter=statuscode:200`,
    `filter=mimetype:text/html`, `from=` 3 years back, `limit=2000`) and
    a narrower one restricted to a meeting/agenda path regex, which is
    the one phase 2 actually scores from (so a big city's unrelated news
    archive doesn't crowd out the meeting paths). The narrow query pages
    (`page=`) up to 3 times only when it hits its own row limit.
  - Common Crawl: probed once at the start of the whole run; the entire
    run skips it if that first probe fails (same pattern WO-268 used
    after finding a real, live Common Crawl outage that session).

REAL, LIVE FINDING THIS SESSION (2026-09-12, confirmed by hand before
writing this script): the Wayback CDX search API
(`web.archive.org/cdx/search/cdx`) is itself currently degraded --
repeated direct `curl` tests returned "Internet Archive: Temporarily
Offline" (HTTP 503) on some tries, a bare connection hang past 20s on
others, and a real 200 on others, with SUCCESSFUL responses taking
5-13 seconds even for the simplest possible query
(`url=example.com&limit=1`). `web.archive.org/` itself, the `wayback/
available` API, and `archive.org/` all answered instantly (200) the same
minute -- so this is specifically a CDX-search degradation, not a whole-
service outage. Every CDX call in this script therefore uses a short
timeout (CDX_CONNECT_TIMEOUT/CDX_READ_TIMEOUT below), ONE retry with a
short backoff, and then gives up and is treated exactly like "no capture
found" -- falling through to the live-fetch path per the design above,
never blocking the sweep. This is recorded per-government
(`wayback_cdx_unavailable` in the raw record) so phase 2/the writeup can
report how much of the population this affected, the same way WO-268's
doc reported its own Common Crawl outage as a real, dated, current fact
rather than silently degrading. A rerun once Internet Archive's CDX
search recovers should be expected to find more than this run did.

Concurrency: `--concurrency N` governments in flight at once (default 8,
per this WO's phase-1 brief). One request in flight per host
(`HostRateLimiter` below, shared with wo273_targeted.py's per-host rule),
>=2.5s between requests to the SAME host, an honest User-Agent, and a
robots.txt Disallow on the sitemap path is honored. Wayback reads
(CDX + `id_` body reads) are additionally capped at ARCHIVE_CONCURRENCY
(8) in flight across the WHOLE run, independent of government
concurrency, since Wayback is explicitly the shared, currently-degraded
resource here.

Resumable: every processed domain is appended as one JSON line
immediately; a re-run skips domains already present. `--build-candidates`
(run once) writes the population to `research/wo273_candidates.csv`.
`--limit N` processes at most N *new* domains this invocation, per
CLAUDE.md's rule against an agent-less background sweep. `--finalize`
prints the timing/yield report used for this WO's writeup and does not
refetch anything.

Usage (from the rtr-deeplink repo root, shared venv):
    .venv/bin/python scripts/wo273_recon.py --build-candidates
    .venv/bin/python scripts/wo273_recon.py --limit 50 --concurrency 8
    .venv/bin/python scripts/wo273_recon.py --finalize

This script imports no `app.*`/`archive.*` code and opens no database
connection -- pure DNS + HTTP against public endpoints, no DATABASE_URL
needed.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import statistics
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import requests

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
JC_CSV = RESEARCH_DIR / "jurisdiction_coverage.csv"
CANDIDATES_CSV = RESEARCH_DIR / "wo273_candidates.csv"
RECON_JSONL = RESEARCH_DIR / "wo273_recon.jsonl"
WO268_CANDIDATES_CSV = RESEARCH_DIR / "wo268_candidates.csv"

MIN_POPULATION = 5000

HONEST_UA = (
    "rtr-upcoming/0.1 (Red Tape Recordings public-agenda reader; "
    "+https://redtaperecordings.com/about)"
)
HEADERS = {
    "User-Agent": HONEST_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

HOST_DELAY_SECONDS = 2.5
GOV_REQUEST_TIMEOUT = 6  # 3s connect target, generous read allowance
DNS_TIMEOUT = "3"
MAX_SUB_SITEMAPS = 6
MAX_FLAGGED_RECORDED = 60
STALE_DAYS = 547  # ~18 months

# CDX is confirmed live-degraded this session (see module docstring) --
# short timeouts, one retry, then give up and fall through to live.
CDX_TIMEOUT = 9
CDX_RETRY_BACKOFF = 2
ARCHIVE_CONCURRENCY = 8

# Same marker list as scripts/wo147_access_ladder_sweep.py's
# CHALLENGE_MARKERS / wo268's copy -- kept local so this stays free of
# that module's heavier import chain.
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
    # WO-278 (2026-09-12): confirmed live against co.roseau.mn.us while
    # rechecking WO-273's single Hyland "single-platform" domain -- a
    # Radware/ShieldSquare bot-management challenge, served with a real
    # HTTP 200 after a 302 through validate.perfdrive.com, that this list
    # didn't recognize. Without this, the challenge page's own body (which
    # never mentions the government) would just read as "no name match",
    # but its REDIRECT URL echoes the original target back as a query
    # parameter (ssc=https%3A%2F%2Fco.roseau.mn.us%2F...), so a careless
    # url-inclusive match could spuriously "confirm" a platform from a
    # block page. Not wired into a body/url decision here either way --
    # is_challenge() is checked before that code runs regardless, so this
    # is the correct, general fix for any future host behind the same
    # vendor. See BACKLOG.md for the wider gap this same marker list is
    # duplicated (unfixed elsewhere) across 7 other scripts.
    "radware block page",
    "perfdrive.com",
    "shieldsquare",
]

# Vendor host aliases, copied from scripts/wo147_access_ladder_sweep.py's
# _PLATFORM_ALIASES (as wo268 also did) plus the extra hosts WO-267/
# platform_signatures.csv confirmed since. Kept as a local copy, not an
# import, so this stays a pure-HTTP/DNS script (see module docstring).
_PLATFORM_ALIASES = {
    "granicus.com": "granicus",
    "legistar.com": "legistar",
    "civicweb.net": "civicweb",
    "escribemeetings": "escribe",
    "escribemeetings.com": "escribe",
    "civicclerk.com": "civicclerk",
    "civicplus.com": "civicplus",
    "primegov.com": "primegov",
    "swagit.com": "swagit",
    "iqm2.com": "iqm2",
    "cablecast.tv": "cablecast",
    "telvue.com": "telvue",
    "champds.com": "champds",
    "clerkshq.com": "clerkbase",
    "municodemeetings.com": "municode_meetings",
    "meetings.municode.com": "municode_meetings",
    "boarddocs.com": "boarddocs",
    "eboardsolutions.com": "eboardsolutions",
    "vimeo.com": "vimeo",
    "youtube.com": "youtube",
    "youtu.be": "youtube",
    "wistia.com": "wistia",
}

# Named first-party path shapes from this WO's brief (WO-272's own
# template file had not landed on main as of this run -- checked, see the
# investigation doc).
_PATH_SHAPE_PLATFORMS = [
    (re.compile(r"/agendacenter", re.I), "civicplus"),
    # Hyland/OnBase's AgendaOnline product, not IQM2 -- corrected after
    # phase 3 found WO-267's own measured platform_signatures.csv entry
    # (`hyland-agendaonline-path`, hit_rate 1.00) disagreed with this
    # script's earlier guess; see the investigation doc's "known
    # discrepancy" note.
    (re.compile(r"agendaonline/meetings/viewmeeting", re.I), "hyland"),
    (re.compile(r"/citizens/", re.I), "iqm2"),
    (re.compile(r"/portal/meetinginformation\.aspx", re.I), "civicclerk"),
    (re.compile(r"/archive\.aspx\?amid=", re.I), "legistar"),
    (re.compile(r"/viewpublisher\.php", re.I), "granicus"),
    (re.compile(r"/mediaplayer\.php", re.I), "granicus"),
]

VENDOR_SUBDOMAIN_GUESSES = [
    "agenda",
    "agendas",
    "meetings",
    "video",
    "granicus",
    "legistar",
    "civicweb",
    "boarddocs",
]

# Per WO-268's live-confirmed DNS-wildcarding finding: only civicweb.net
# and primegov.com return NXDOMAIN for a nonsense label. The other four
# named vendors wildcard, so a guessed label under them is never a real
# DNS signal (see docs/investigations/passive_platform_discovery_pilot.md
# -- "A real finding before the sweep even started"). This WO's own brief
# says to guess vendor-tenant labels "ONLY for civicweb.net and
# primegov.com", so the wildcarding four aren't even queried here.
VENDOR_LABEL_TEMPLATES = [
    ("{label}.civicweb.net", "civicweb"),
    ("{label}.primegov.com", "primegov"),
]

# Path-token flag words, MEASURED (conductor_state.md, tags "HUB LIFT",
# "HUB BIGRAMS", "LIFT over ALL", "FLAG-WORD LIFT", 2026-09-12 -- WO-274's
# app/utils/jurisdiction_data/hop_link_weights.csv had not landed on main
# as of this run, checked; these numbers are embedded here with that
# source noted rather than re-derived). Hub vocabulary scores a listing/
# hub-shaped URL; meeting vocabulary scores a specific meeting/video URL.
# Plurals beat singulars; "agenda" (singular)/"calendar"/"government" are
# near-noise and are excluded as flag words entirely, per that analysis.
HUB_WORD_LIFT = {
    "agendacenter": 538.0,
    "supervisors": 33.0,
    "agendas": 22.0,
    "commissioners": 15.0,
    "meetings": 14.0,
    "mayor": 13.0,
    "council": 11.0,
    "minutes": 10.0,
    "boards": 9.0,
    "commission": 7.0,
}
HUB_BIGRAM_LIFT = {
    "agendas-minutes": 44.0,
    "city-council": 19.0,
    "of-commissioners": 304.0,
    "boards-commissions": 19.0,
    "public-meetings": 11.0,
}
MEETING_WORD_HIT = {
    # Vendor-shape tokens (LIFT over ALL, conductor_state.md) -- not a
    # "lift" ratio the way hub words are, since these are near-exclusive
    # to vendor-served meeting pages; treated as a flat high score.
    "clip": 20.0,
    "mediaplayer": 20.0,
    "meetinginformation": 20.0,
    "meetingid": 20.0,
    "watch": 8.0,
    "splitview": 20.0,
    "meetingtemplateid": 20.0,
    "player": 8.0,
    "citizens": 8.0,
    "videos": 5.0,
    "view": 3.0,
    "portal": 3.0,
    "transcript": 8.0,
    "vod": 8.0,
}
# Explicitly dropped as noise per the same analysis -- never scored:
# "agenda" (singular), "calendar", "government", "media".

KEYWORD_RE = re.compile(
    r"meeting|agenda|minutes|council|commission|board|video|stream", re.I
)


def log(msg: str) -> None:
    print(msg, flush=True)


# --------------------------------------------------------------------------
# Politeness: shared per-host rate limiter (one request in flight per
# host, >=HOST_DELAY_SECONDS between requests to the same host). Used by
# both this script and wo273_targeted.py (phase 3 imports this module for
# it, per that phase's identical per-host rule).
# --------------------------------------------------------------------------


class HostRateLimiter:
    def __init__(self, delay_seconds: float = HOST_DELAY_SECONDS):
        self.delay = delay_seconds
        self._locks: dict[str, threading.Lock] = {}
        self._last: dict[str, float] = {}
        self._master = threading.Lock()

    def _lock_for(self, host: str) -> threading.Lock:
        with self._master:
            lock = self._locks.get(host)
            if lock is None:
                lock = threading.Lock()
                self._locks[host] = lock
            return lock

    def wait_and_request(self, key: str, fn, *args, **kwargs):
        """Serialize calls sharing `key` (usually a host, or a vendor
        family name for the phase-3 vendor-grouping rule), enforcing the
        minimum delay between them, then run fn(*args, **kwargs)."""
        lock = self._lock_for(key)
        with lock:
            last = self._last.get(key)
            if last is not None:
                wait = self.delay - (time.monotonic() - last)
                if wait > 0:
                    time.sleep(wait)
            try:
                return fn(*args, **kwargs)
            finally:
                self._last[key] = time.monotonic()


RATE_LIMITER = HostRateLimiter(HOST_DELAY_SECONDS)
_ARCHIVE_SEMA = threading.Semaphore(ARCHIVE_CONCURRENCY)


def polite_request(url: str, method: str = "GET", timeout=GOV_REQUEST_TIMEOUT):
    host = urlparse(url).netloc
    return RATE_LIMITER.wait_and_request(
        host,
        requests.request,
        method,
        url,
        headers=HEADERS,
        timeout=timeout,
        allow_redirects=True,
    )


def is_challenge(text: str) -> bool:
    lower = (text or "").lower()
    return any(marker in lower for marker in CHALLENGE_MARKERS)


def vendor_family_for_url(url: str) -> str:
    host = urlparse(url).netloc.lower()
    for alias, platform in _PLATFORM_ALIASES.items():
        if alias in host:
            return platform
    return host  # not a known vendor -- rate-limit by its own host


# --------------------------------------------------------------------------
# Candidate population
# --------------------------------------------------------------------------

# "Nothing found" family, this WO's brief: no suspected platform, no
# page, and a reject reason in this set (blank counts as "never
# checked"). Re-derived directly against a live snapshot of
# jurisdiction_coverage.csv on 2026-09-12: 2,575 rows (conductor's own
# count, from an earlier snapshot the same day, was 2,574 -- the 1-row
# drift is expected live-file movement, not a filter mismatch; see the
# investigation doc for the full by-reason breakdown, which matches the
# conductor's count exactly per reason).
NOTHING_FOUND_REASONS = {
    "no-platform-link-found",
    "no-platform-signature",
    "dns-unresolvable",
    "resolve-failed",
    "blocked-plain-http",
    "",
}

# Rows whose OWN `domain` column is a meeting-vendor host -- the platform
# IS the hostname, nothing to discover passively. Checked directly
# against the filtered "nothing found, 5,000+" population (not the whole
# 45k-row file): only 1 of 2,576 pre-exclusion rows has a vendor-host
# domain -- almost none, since a vendor-hosted `domain` would ordinarily
# already carry a suspected-platform value or `transcribed=true` and so
# would already have been filtered out above. This is smaller than the
# brief's cited "1,406 rows" because that figure is a whole-file count
# (all 45,609 rows), not a count within this already-filtered pool --
# re-derived and reported plainly rather than assumed.
VENDOR_DOMAIN_SUBSTRINGS = [
    "granicus.com",
    "legistar.com",
    "civicweb.net",
    "escribemeetings",
    "civicclerk.com",
    "civicplus.com",
    "primegov.com",
    "swagit.com",
    "iqm2.com",
    "cablecast.tv",
    "telvue.com",
    "champds.com",
    "clerkshq.com",
    "municodemeetings.com",
    "meetings.municode.com",
    "boarddocs.com",
    "eboardsolutions.com",
    "vimeo.com",
    "youtube.com",
    "youtu.be",
    "wistia.com",
    "revize.com",
]


def is_blank(v) -> bool:
    return v is None or str(v).strip() == ""


def is_vendor_domain(domain: str) -> bool:
    d = (domain or "").lower()
    return any(sub in d for sub in VENDOR_DOMAIN_SUBSTRINGS)


def load_jc_rows() -> list:
    with open(JC_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def build_candidate_pool(rows: list) -> tuple[list, dict]:
    pool = []
    by_reason: dict[str, int] = {}
    vendor_excluded = 0
    for row in rows:
        country = (row.get("country") or "").strip()
        if country not in ("United States", "Canada"):
            continue
        try:
            pop = float(row.get("population_estimate"))
        except (TypeError, ValueError):
            continue
        if pop < MIN_POPULATION:
            continue
        if is_blank(row.get("domain")):
            continue
        if (row.get("transcribed") or "").strip().lower() in ("true", "1", "yes"):
            continue
        if not (
            is_blank(row.get("suspected_calendar_provider"))
            and is_blank(row.get("suspected_meeting_link_provider"))
            and is_blank(row.get("suspected_video_provider"))
        ):
            continue
        rr = (row.get("reject_reason") or "").strip()
        if rr not in NOTHING_FOUND_REASONS:
            continue
        if is_vendor_domain(row.get("domain")):
            vendor_excluded += 1
            continue
        pool.append(row)
        by_reason[rr or "(blank)"] = by_reason.get(rr or "(blank)", 0) + 1
    return pool, {"vendor_excluded": vendor_excluded, "by_reason": by_reason}


def load_wo268_domains() -> set:
    if not WO268_CANDIDATES_CSV.exists():
        return set()
    with open(WO268_CANDIDATES_CSV, newline="", encoding="utf-8") as f:
        return {r["domain"].strip() for r in csv.DictReader(f) if r.get("domain")}


def cmd_build_candidates() -> None:
    rows = load_jc_rows()
    pool, stats = build_candidate_pool(rows)
    wo268_domains = load_wo268_domains()
    log(f"candidate pool (US+Canada, pop>=5000, nothing-found family): {len(pool)}")
    log(f"  vendor-domain excluded: {stats['vendor_excluded']}")
    log(f"  by reject_reason: {stats['by_reason']}")
    log(
        f"  of which also in WO-268's 300 (regression rows, included): "
        f"{sum(1 for r in pool if r.get('domain', '').strip() in wo268_domains)}"
    )

    with open(CANDIDATES_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "domain",
                "state_or_province",
                "country",
                "gov_id",
                "population_estimate",
                "city_name",
                "reject_reason",
                "is_wo268_regression",
            ]
        )
        for r in pool:
            domain = (r.get("domain") or "").strip()
            w.writerow(
                [
                    domain,
                    r.get("state_or_province", ""),
                    r.get("country", ""),
                    r.get("gov_id", ""),
                    r.get("population_estimate", ""),
                    r.get("city_name", ""),
                    (r.get("reject_reason") or "").strip(),
                    domain in wo268_domains,
                ]
            )
    log(f"wrote {CANDIDATES_CSV} ({len(pool)} rows)")


# --------------------------------------------------------------------------
# DNS rung
# --------------------------------------------------------------------------


def dig(record_type: str, host: str) -> list:
    try:
        out = subprocess.run(
            ["dig", f"+time={DNS_TIMEOUT}", "+tries=1", "+short", record_type, host],
            capture_output=True,
            text=True,
            timeout=6,
        )
        return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()]
    except Exception:  # noqa: BLE001 -- DNS failure is a normal outcome
        return []


def registrable_label(domain: str) -> str:
    parts = domain.lower().strip(".").split(".")
    if len(parts) < 2:
        return domain.lower()
    if len(parts) >= 3 and parts[-1] == "us" and len(parts[-2]) <= 3:
        return parts[-3]
    return parts[-2]


def dns_lookup(domain: str) -> dict:
    result = {
        "apex_a": dig("A", domain),
        "apex_cname": (dig("CNAME", domain) or [""])[0],
        "www_a": dig("A", f"www.{domain}"),
        "www_cname": (dig("CNAME", f"www.{domain}") or [""])[0],
        "resolving_subdomains": [],
        "resolving_vendor_labels": [],
    }
    apex_a_set = set(result["apex_a"])
    for sub in VENDOR_SUBDOMAIN_GUESSES:
        host = f"{sub}.{domain}"
        cname = (dig("CNAME", host) or [""])[0]
        a = dig("A", host) if not cname else []
        if not (cname or a):
            continue
        likely_own_wildcard = (
            bool(a) and not cname and set(a) == apex_a_set and bool(apex_a_set)
        )
        result["resolving_subdomains"].append(
            {
                "subdomain": sub,
                "host": host,
                "cname": cname,
                "a": a,
                "likely_own_domain_wildcard": likely_own_wildcard,
            }
        )
    label = registrable_label(domain)
    for template, platform in VENDOR_LABEL_TEMPLATES:
        host = template.format(label=label)
        a = dig("A", host)
        cname = (dig("CNAME", host) or [""])[0]
        if a or cname:
            result["resolving_vendor_labels"].append(
                {"host": host, "platform": platform, "a": a, "cname": cname}
            )
    return result


# --------------------------------------------------------------------------
# Sitemap-from-archive-first, then live fallback
# --------------------------------------------------------------------------


def cdx_get(url: str) -> requests.Response | None:
    """One CDX call, short timeout, ONE retry after a short backoff, then
    give up -- per this session's confirmed live CDX degradation (see
    module docstring). Capped at ARCHIVE_CONCURRENCY in flight globally."""
    for attempt in range(2):
        with _ARCHIVE_SEMA:
            try:
                resp = requests.get(url, headers=HEADERS, timeout=CDX_TIMEOUT)
                if resp.status_code == 200:
                    return resp
            except Exception:  # noqa: BLE001
                pass
        if attempt == 0:
            time.sleep(CDX_RETRY_BACKOFF)
    return None


def wayback_id_read(url: str, timestamp: str) -> bytes | None:
    id_url = f"https://web.archive.org/web/{timestamp}id_/{url}"
    with _ARCHIVE_SEMA:
        try:
            resp = requests.get(id_url, headers=HEADERS, timeout=CDX_TIMEOUT)
            if resp.status_code == 200:
                return resp.content
        except Exception:  # noqa: BLE001
            pass
    return None


def newest_capture(rows: list) -> tuple[str, str] | None:
    """rows: CDX json rows (excluding the header row), each [original, timestamp].
    Returns (original_url, timestamp) of the newest, or None."""
    if not rows:
        return None
    best = max(rows, key=lambda r: r[1] if len(r) > 1 else "")
    return best[0], best[1]


def capture_age_days(timestamp: str) -> float:
    try:
        t = time.strptime(timestamp[:8], "%Y%m%d")
        return (time.time() - time.mktime(t)) / 86400.0
    except Exception:  # noqa: BLE001
        return 99999.0


def fetch_archived_sitemap_and_robots(domain: str) -> dict:
    """Phase-1 archive-first step. Two bounded CDX calls (sitemap prefix,
    robots exact), newest capture read via the `id_` raw form. Returns a
    record with `sitemap_source` in {wayback, none} (a `none` here just
    means phase-1 falls through to a live attempt below -- `wo273_recon`
    tries live only when this returns nothing useful or stale)."""
    out = {
        "cdx_reachable": None,  # None = not yet known, True/False after first try
        "sitemap_wayback_url": "",
        "sitemap_wayback_timestamp": "",
        "sitemap_wayback_age_days": None,
        "sitemap_wayback_body_bytes": 0,
        "robots_wayback_url": "",
        "robots_wayback_timestamp": "",
        "robots_wayback_age_days": None,
        "robots_wayback_body": "",
    }
    sm_url = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={domain}/sitemap&matchType=prefix&filter=statuscode:200"
        "&collapse=urlkey&limit=-10&fl=original,timestamp&output=json"
    )
    resp = cdx_get(sm_url)
    if resp is not None:
        out["cdx_reachable"] = True
        try:
            rows = json.loads(resp.text)[1:]
        except Exception:  # noqa: BLE001
            rows = []
        best = newest_capture(rows)
        if best:
            orig, ts = best
            out["sitemap_wayback_url"] = orig
            out["sitemap_wayback_timestamp"] = ts
            out["sitemap_wayback_age_days"] = capture_age_days(ts)
            body = wayback_id_read(orig, ts)
            if body:
                out["sitemap_wayback_body_bytes"] = len(body)
                out["_sitemap_wayback_body_raw"] = (
                    body  # consumed by caller, not serialized
                )
    else:
        out["cdx_reachable"] = False

    rb_url = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={domain}/robots.txt&filter=statuscode:200"
        "&collapse=urlkey&limit=-5&fl=original,timestamp&output=json"
    )
    resp = cdx_get(rb_url)
    if resp is not None:
        out["cdx_reachable"] = (
            True if out["cdx_reachable"] is not False else out["cdx_reachable"]
        )
        try:
            rows = json.loads(resp.text)[1:]
        except Exception:  # noqa: BLE001
            rows = []
        best = newest_capture(rows)
        if best:
            orig, ts = best
            out["robots_wayback_url"] = orig
            out["robots_wayback_timestamp"] = ts
            out["robots_wayback_age_days"] = capture_age_days(ts)
            body = wayback_id_read(orig, ts)
            if body:
                try:
                    out["robots_wayback_body"] = body.decode("utf-8", errors="replace")[
                        :5000
                    ]
                except Exception:  # noqa: BLE001
                    pass
    return out


def parse_robots(text: str) -> dict:
    sitemap_urls, disallow_paths = [], []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()
        if key == "sitemap":
            sitemap_urls.append(value)
        elif key == "disallow":
            disallow_paths.append(value)
    return {"sitemap_urls": sitemap_urls, "disallow_paths": disallow_paths}


def fetch_live_robots(domain: str) -> dict:
    out = {
        "fetched": False,
        "status": None,
        "sitemap_directives": [],
        "disallow_paths": [],
        "disallows_sitemap": False,
        "error": "",
    }
    try:
        resp = polite_request(f"https://{domain}/robots.txt")
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:200]
        return out
    out["status"] = resp.status_code
    if resp.status_code != 200 or not resp.text:
        return out
    if is_challenge(resp.text):
        out["error"] = "challenge-gate"
        return out
    parsed = parse_robots(resp.text)
    out["fetched"] = True
    out["sitemap_directives"] = parsed["sitemap_urls"]
    out["disallow_paths"] = parsed["disallow_paths"][:50]
    out["disallows_sitemap"] = any(
        "sitemap" in d.lower() for d in parsed["disallow_paths"]
    )
    return out


def parse_sitemap_xml(body: bytes):
    try:
        if body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        root = ElementTree.fromstring(body)
    except Exception:  # noqa: BLE001
        return None, []
    tag = root.tag.rsplit("}", 1)[-1].lower()
    urls = []
    if tag == "sitemapindex":
        for sm in root:
            for child in sm:
                if child.tag.rsplit("}", 1)[-1].lower() == "loc" and child.text:
                    urls.append(child.text.strip())
                    break
        return "index", urls
    if tag == "urlset":
        for u in root:
            for child in u:
                if child.tag.rsplit("}", 1)[-1].lower() == "loc" and child.text:
                    urls.append(child.text.strip())
                    break
        return "urlset", urls
    return None, []


# Sub-sitemap NAME priority (Ryan, 2026-09-12): pages/page/post before
# image/category/tag, so a domain with many sub-sitemaps spends its
# MAX_SUB_SITEMAPS budget on the ones likeliest to hold a meeting/agenda
# page rather than an image or tag-archive sitemap.
_SUBSITEMAP_PRIORITY = ["page", "post", "meeting", "agenda", "council", "board"]
_SUBSITEMAP_DEPRIORITY = ["image", "category", "tag", "author", "attachment"]


def rank_sub_sitemaps(urls: list) -> list:
    def score(u: str) -> tuple:
        lu = u.lower()
        pri = min(
            (i for i, w in enumerate(_SUBSITEMAP_PRIORITY) if w in lu),
            default=len(_SUBSITEMAP_PRIORITY),
        )
        deprioritized = any(w in lu for w in _SUBSITEMAP_DEPRIORITY)
        return (deprioritized, pri)

    return sorted(urls, key=score)


def fetch_live_sitemap(domain: str, robots_info: dict) -> dict:
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

    all_urls, used_url, kind, last_error = [], "", "", ""
    for url in candidates:
        try:
            resp = polite_request(url)
        except Exception as e:  # noqa: BLE001
            last_error = str(e)[:200]
            continue
        if resp.status_code != 200 or not resp.content:
            last_error = f"http-{resp.status_code}"
            continue
        if resp.content[:2] != b"\x1f\x8b" and is_challenge(
            resp.content[:4000].decode("utf-8", errors="replace")
        ):
            out["error"] = "challenge-gate"
            return out
        kind, urls = parse_sitemap_xml(resp.content)
        if kind is None:
            continue
        used_url = url
        if kind == "index":
            all_urls.extend(urls)
            followed = 0
            for sub_url in rank_sub_sitemaps(urls)[:MAX_SUB_SITEMAPS]:
                try:
                    sub_resp = polite_request(sub_url)
                except Exception:  # noqa: BLE001
                    continue
                if sub_resp.status_code != 200 or not sub_resp.content:
                    continue
                sub_kind, sub_urls = parse_sitemap_xml(sub_resp.content)
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


# --------------------------------------------------------------------------
# Wayback CDX domain-wide index (bounded, per Ryan's "CDX scope and
# pagination" note)
# --------------------------------------------------------------------------

MEETING_PATH_REGEX = (
    r".*(agenda|minutes|meeting|council|commission|board|video|clip|player|watch).*"
)


def fetch_wayback_domain_index(domain: str) -> dict:
    out = {
        "reachable": None,
        "broad_row_count": 0,
        "narrow_row_count": 0,
        "narrow_urls": [],
        "cdx_truncated": False,
        "error": "",
    }
    from_date = time.strftime("%Y%m%d", time.gmtime(time.time() - 3 * 365 * 86400))
    broad_url = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={domain}/*&collapse=urlkey&filter=statuscode:200"
        f"&filter=mimetype:text/html&from={from_date}&fl=original,timestamp"
        "&limit=2000&output=json"
    )
    resp = cdx_get(broad_url)
    if resp is None:
        out["reachable"] = False
        out["error"] = "cdx-unavailable"
        return out
    out["reachable"] = True
    try:
        rows = json.loads(resp.text)[1:]
    except Exception:  # noqa: BLE001
        rows = []
    out["broad_row_count"] = len(rows)

    narrow_base = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={domain}/*&collapse=urlkey&filter=statuscode:200"
        f"&filter=mimetype:text/html&from={from_date}"
        f"&filter=original:{MEETING_PATH_REGEX}"
        "&fl=original,timestamp&limit=2000&output=json"
    )
    narrow_urls = []
    for page in range(3):
        page_url = narrow_base + (f"&page={page}" if page else "")
        resp = cdx_get(page_url)
        if resp is None:
            break
        try:
            rows = json.loads(resp.text)[1:]
        except Exception:  # noqa: BLE001
            rows = []
        if not rows:
            break
        narrow_urls.extend(r[0] for r in rows if r)
        if len(rows) < 2000:
            break
        out["cdx_truncated"] = True
    out["narrow_row_count"] = len(narrow_urls)
    out["narrow_urls"] = narrow_urls[:MAX_FLAGGED_RECORDED]
    return out


# --------------------------------------------------------------------------
# Common Crawl (probed once at run start; whole run skips it if down)
# --------------------------------------------------------------------------

_cc_crawl_id_probed = False
_cc_crawl_id = ""


def probe_common_crawl() -> str:
    global _cc_crawl_id_probed, _cc_crawl_id
    if _cc_crawl_id_probed:
        return _cc_crawl_id
    _cc_crawl_id_probed = True
    try:
        resp = requests.get(
            "https://index.commoncrawl.org/collinfo.json", headers=HEADERS, timeout=10
        )
        resp.raise_for_status()
        info = resp.json()
        _cc_crawl_id = info[0]["id"] if info else ""
    except Exception:  # noqa: BLE001
        _cc_crawl_id = ""
    return _cc_crawl_id


def fetch_common_crawl(domain: str, crawl_id: str) -> dict:
    out = {"reachable": False, "capture_count": 0, "urls": [], "error": ""}
    if not crawl_id:
        out["error"] = "no-crawl-id-available"
        return out
    url = (
        f"https://index.commoncrawl.org/{crawl_id}-index"
        f"?url={domain}/*&output=json&limit=500"
    )
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12)
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:200]
        return out
    if resp.status_code == 404:
        out["reachable"] = True
        out["error"] = "no-captures"
        return out
    if resp.status_code != 200:
        out["error"] = f"http-{resp.status_code}"
        return out
    out["reachable"] = True
    urls = []
    for line in resp.text.splitlines():
        try:
            rec = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if rec.get("url"):
            urls.append(rec["url"])
    out["capture_count"] = len(urls)
    out["urls"] = urls[:MAX_FLAGGED_RECORDED]
    return out


# --------------------------------------------------------------------------
# Per-government orchestration
# --------------------------------------------------------------------------


def process_government(row: dict) -> dict:
    domain = row["domain"]
    timings = {}
    record = {
        "domain": domain,
        "state": row.get("state_or_province", ""),
        "country": row.get("country", ""),
        "gov_id": row.get("gov_id", ""),
        "population": row.get("population_estimate", ""),
        "reject_reason": row.get("reject_reason", ""),
        "is_wo268_regression": row.get("is_wo268_regression", ""),
        "processed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    t0 = time.monotonic()
    archive_sm = fetch_archived_sitemap_and_robots(domain)
    timings["archive_sitemap_ms"] = int((time.monotonic() - t0) * 1000)

    sitemap_body_raw = archive_sm.pop("_sitemap_wayback_body_raw", None)
    sitemap_stale = (
        archive_sm.get("sitemap_wayback_age_days") is None
        or archive_sm["sitemap_wayback_age_days"] > STALE_DAYS
    )
    sitemap_source = "none"
    sitemap_urls: list[str] = []
    sitemap_url_count = 0

    if sitemap_body_raw and not sitemap_stale:
        kind, urls = parse_sitemap_xml(sitemap_body_raw)
        if kind == "urlset":
            sitemap_urls = urls[:2000]
            sitemap_url_count = len(urls)
            sitemap_source = "wayback"
        elif kind == "index":
            # A stale-checked index still counts as "wayback" for the
            # source split, but sub-sitemaps aren't fetched from the
            # archive (out of this phase's scope) -- a live fetch below
            # will follow the index instead if it's stale/missing, since
            # sitemap_source stays "none" until we get a real urlset.
            sitemap_source = "wayback"
            sitemap_urls = urls[:2000]
            sitemap_url_count = len(urls)
    elif sitemap_body_raw and sitemap_stale:
        sitemap_source = "wayback-stale"

    t1 = time.monotonic()
    robots_info = fetch_live_robots(domain)
    live_sitemap_info = {"found": False, "url_count": 0, "urls": [], "error": "skipped"}
    if sitemap_source in ("none", "wayback-stale"):
        live_sitemap_info = fetch_live_sitemap(domain, robots_info)
        if live_sitemap_info.get("found"):
            sitemap_source = (
                "live" if sitemap_source == "none" else "wayback-stale+live"
            )
            sitemap_urls = live_sitemap_info["urls"]
            sitemap_url_count = live_sitemap_info["url_count"]
    timings["robots_and_live_sitemap_ms"] = int((time.monotonic() - t1) * 1000)

    t2 = time.monotonic()
    dns_info = dns_lookup(domain)
    timings["dns_ms"] = int((time.monotonic() - t2) * 1000)

    t3 = time.monotonic()
    wayback_index = fetch_wayback_domain_index(domain)
    timings["wayback_index_ms"] = int((time.monotonic() - t3) * 1000)

    t4 = time.monotonic()
    crawl_id = probe_common_crawl()
    cc_info = (
        fetch_common_crawl(domain, crawl_id)
        if crawl_id
        else {
            "reachable": False,
            "capture_count": 0,
            "urls": [],
            "error": "cc-probe-failed-skip-whole-run",
        }
    )
    timings["common_crawl_ms"] = int((time.monotonic() - t4) * 1000)

    record.update(
        {
            "sitemap_source": sitemap_source,
            "sitemap_wayback_age_days": archive_sm.get("sitemap_wayback_age_days"),
            "sitemap_url_count": sitemap_url_count,
            "sitemap_urls": sitemap_urls[:MAX_FLAGGED_RECORDED],
            "robots_wayback_body_snippet": archive_sm.get("robots_wayback_body", "")[
                :500
            ],
            "robots_live_fetched": robots_info.get("fetched", False),
            "cdx_reachable_this_gov": archive_sm.get("cdx_reachable"),
            "dns": dns_info,
            "wayback_index": {
                "reachable": wayback_index["reachable"],
                "broad_row_count": wayback_index["broad_row_count"],
                "narrow_row_count": wayback_index["narrow_row_count"],
                "narrow_urls": wayback_index["narrow_urls"],
                "cdx_truncated": wayback_index["cdx_truncated"],
                "error": wayback_index["error"],
            },
            "common_crawl": {
                "reachable": cc_info["reachable"],
                "capture_count": cc_info["capture_count"],
                "urls": cc_info["urls"],
                "error": cc_info["error"],
            },
            "timings_ms": timings,
        }
    )
    return record


# --------------------------------------------------------------------------
# Sweep driver
# --------------------------------------------------------------------------


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


def cmd_sweep(limit: int, concurrency: int) -> None:
    if not CANDIDATES_CSV.exists():
        log(f"{CANDIDATES_CSV} missing -- run with --build-candidates first")
        sys.exit(1)
    with open(CANDIDATES_CSV, newline="", encoding="utf-8") as f:
        candidates = list(csv.DictReader(f))

    done = load_done_domains()
    remaining = [r for r in candidates if r["domain"] not in done]
    log(f"{len(done)} already done, {len(remaining)} remaining of {len(candidates)}")

    to_process = remaining[:limit] if limit else remaining
    log(f"processing {len(to_process)} governments at concurrency={concurrency}")

    start = time.monotonic()
    completed = 0
    errors = 0
    with (
        open(RECON_JSONL, "a", encoding="utf-8") as out,
        ThreadPoolExecutor(max_workers=concurrency) as pool,
    ):
        futures = {pool.submit(process_government, row): row for row in to_process}
        for fut in as_completed(futures):
            row = futures[fut]
            domain = row["domain"]
            try:
                record = fut.result()
            except Exception as e:  # noqa: BLE001 -- one bad domain never kills the sweep
                errors += 1
                record = {
                    "domain": domain,
                    "state": row.get("state_or_province", ""),
                    "gov_id": row.get("gov_id", ""),
                    "error": str(e)[:300],
                    "sitemap_source": "error",
                }
            with _write_lock:
                out.write(json.dumps(record) + "\n")
                out.flush()
            completed += 1
            if completed % 10 == 0 or completed == len(to_process):
                elapsed = time.monotonic() - start
                rate = completed / (elapsed / 60) if elapsed > 0 else 0
                log(
                    f"[{completed}/{len(to_process)}] elapsed={elapsed:.0f}s "
                    f"rate={rate:.1f}/min errors={errors} last={domain}"
                )

    elapsed = time.monotonic() - start
    rate = len(to_process) / (elapsed / 60) if elapsed > 0 else 0
    log(
        f"chunk done: {len(to_process)} processed in {elapsed:.0f}s "
        f"({rate:.2f} governments/min), {errors} errors, "
        f"{len(remaining) - len(to_process)} remain unprocessed."
    )


# --------------------------------------------------------------------------
# Finalize / report
# --------------------------------------------------------------------------


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

    source_counts: dict[str, int] = {}
    cdx_row_counts = []
    step_timings: dict[str, list] = {}
    truncated = 0
    for r in records:
        src = r.get("sitemap_source", "unknown")
        source_counts[src] = source_counts.get(src, 0) + 1
        wi = r.get("wayback_index", {}) or {}
        if wi.get("reachable"):
            cdx_row_counts.append(wi.get("broad_row_count", 0))
        if wi.get("cdx_truncated"):
            truncated += 1
        for step, ms in (r.get("timings_ms") or {}).items():
            step_timings.setdefault(step, []).append(ms)

    log("sitemap_source split:")
    for k, v in sorted(source_counts.items(), key=lambda x: -x[1]):
        log(f"  {k}: {v} ({v * 100 / total:.1f}%)")

    if cdx_row_counts:
        cdx_row_counts.sort()
        log(
            f"CDX broad-query row-count distribution: "
            f"median={statistics.median(cdx_row_counts):.0f} "
            f"p95={cdx_row_counts[int(len(cdx_row_counts) * 0.95) - 1]:.0f} "
            f"max={max(cdx_row_counts)} "
            f"cdx_truncated={truncated}/{total}"
        )
    else:
        log("CDX broad query: unreachable for every processed government so far")

    log("per-step timing (ms), median / p95:")
    for step, vals in step_timings.items():
        vals_sorted = sorted(vals)
        med = statistics.median(vals_sorted)
        p95 = vals_sorted[max(0, int(len(vals_sorted) * 0.95) - 1)]
        log(f"  {step}: median={med:.0f} p95={p95:.0f} n={len(vals)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-candidates", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=8)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()

    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)

    if args.build_candidates:
        cmd_build_candidates()
        return
    if args.finalize:
        cmd_finalize()
        return
    cmd_sweep(args.limit, args.concurrency)


if __name__ == "__main__":
    main()
