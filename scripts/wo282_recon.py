"""WO-282 (2026-09-12): passive discovery v2, phase 1 -- reconnaissance,
redesigned from WO-273's per Ryan's 2026-09-12 notes.

Builds on WO-273's own DNS/archive/robots/sitemap/Wayback/Common-Crawl
helpers and hub_score()/meeting_score() URL scoring -- moved into this
file verbatim (WO-1019, 2026-09-23) now that WO-273's own scripts are
retired; see the "Moved here from wo273_recon.py" banner below for what
moved and why. This script adds the pieces WO-273's own writeup flagged
as missing:

  1. DNS is a fail-fast GATE, not just a recorded signal: if neither the
     apex nor `www.` resolves (no A, no CNAME), the government is
     recorded `dns-unresolvable` and every HTTP step (archive, live
     homepage, robots, sitemap, Wayback domain index) is skipped --
     there is nothing at the other end to fetch.
  2. The homepage is ALWAYS fetched live (WO-273 never fetched it at
     all) -- plain HTTP first; browser headers only after a 403 or a
     dropped connection (never after a 404, per CLAUDE.md's "politely"
     rule); stop at a human-verification challenge marker. Every link on
     the page is recorded with its href, anchor text, and position
     (`nav`/`header` vs `footer` vs a bare `<ul>/<ol>` menu vs plain
     body) -- position is what the measured hop scorer
     (`hop_link_weights.csv`, WO-274) scores on that a sitemap URL list
     never carries, so phase 2 can rerun `find_hop_links()` against the
     cached homepage HTML with no new network call.
  3. Every `Sitemap:` directive in robots.txt is read (WO-273 stopped at
     the first sitemap that parsed) plus the three default paths, capped
     at 10 per government (was 6), each capped at 500 KB. `Crawl-delay`
     is read from robots.txt and applied to that host's own entry in the
     shared rate limiter for the REST of this government's requests --
     a site that asks for 10s between requests gets 10s, not the
     default 2.5s. Disallow paths are recorded, and any one matching the
     hub vocabulary (`agenda`, `agendas`, `council`, `commission`,
     `minutes`, `board`, `meeting`) is flagged `disallowed_lead` and
     never fetched by this script or phase 3 -- a real lead, and a real
     do-not-fetch, at once.
  4. A dedicated Wayback CDX health probe (not just "did the last call
     succeed") runs once at the start of the whole run and again every
     200 governments, so a mid-run CDX recovery or relapse is caught
     rather than inferred government-by-government. The archive-first
     sitemap/robots read and the Wayback domain index are both skipped
     outright while the probe says unhealthy, instead of still firing
     requests that are very likely to time out.

Storage: one JSON-lines record per government in `wo282_recon.jsonl`
(resumable by domain, same pattern as WO-273), plus the gzipped raw
homepage HTML saved to this agent's scratch directory (path recorded in
the JSON record, not the HTML itself -- keeps the JSONL file readable).

This script still imports no `app.*`/`archive.*` code and opens no
database connection -- pure DNS + HTTP against public endpoints.

Usage (from the rtr-deeplink repo root, shared venv):
    .venv/bin/python scripts/wo282_recon.py --limit 50 --concurrency 32
    .venv/bin/python scripts/wo282_recon.py --concurrency 32
    .venv/bin/python scripts/wo282_recon.py --finalize
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
from bs4 import BeautifulSoup

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
POPULATION_CSV = RESEARCH_DIR / "wo282_population.csv"
RECON_JSONL = RESEARCH_DIR / "wo282_recon.jsonl"


# --------------------------------------------------------------------------
# Moved here from wo273_recon.py (WO-1019, 2026-09-23): WO-273's scripts are
# retired (superseded by this passive-discovery-v2 phase-1 module), but this
# section -- DNS/archive/robots/sitemap/Wayback/Common-Crawl helpers and the
# pure hub_score()/meeting_score() URL scoring -- is real, shared library code
# every WO-282+ recon/classify/targeted script (and this file itself) still
# calls. Moved verbatim, not rewritten -- see git history for wo273_recon.py's
# original comments if you need the retired-script framing. fetch_live_robots()/
# fetch_live_sitemap()/process_government()/cmd_build_candidates()/the JC-CSV
# candidate-pool builder were NOT moved: nothing outside wo273_recon.py's own
# CLI ever called them (this file has its own fetch_live_robots_v2/
# fetch_live_sitemap_v2/process_government_v2/cmd_sweep, and WO-282's
# population comes from a separate wo282_population.csv, not a JC-CSV sweep).
# --------------------------------------------------------------------------

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

# WO-939: a real wall-clock cap on top of GOV_REQUEST_TIMEOUT/CDX_TIMEOUT
# -- `requests`' own `timeout=` only bounds each individual socket read,
# not the whole request, so a server that trickles bytes slowly enough
# can hang well past it (confirmed live, WO-322: two real domains hung
# 250-290+ seconds despite timeout=6; this is also the best-supported
# explanation for wo321_recon.py's real, twice-reproduced rankincounty.org
# hang, WO-321 -- see scripts/sweep_deadline.py's own module docstring).
# Generous relative to the per-read timeouts above (a real slow-but-honest
# response should still finish), nowhere near the 250s+ hangs observed.
GOV_REQUEST_WALL_CLOCK_DEADLINE = 25
CDX_WALL_CLOCK_DEADLINE = 45

# CDX is confirmed live-degraded (see module docstring). WO-366
# (2026-09-14) widened the retry budget from the original 2-attempt/2s
# version after WO-337/338 got an archive answer for only 20/1,951 and
# 16/2,825 governments under it: 3 attempts total, 20s timeout per
# attempt (Ryan's per-call cap), CDX_RETRY_BACKOFFS between attempts.
CDX_TIMEOUT = 20
CDX_RETRY_BACKOFFS = [2, 8]
ARCHIVE_CONCURRENCY = 8

# WO-939: this WAS the canonical copy (it's the one that got WO-278's
# Radware/ShieldSquare markers first, 2026-09-12) -- moved to scripts/
# challenge_markers.py so the other 8 scripts that copied it stop
# silently drifting from it. Bare import, not `scripts.challenge_
# markers`, since this module deliberately makes no sys.path change of
# its own (kept free of app/'s heavier import chain -- see module
# docstring); `scripts/` is already on sys.path for every way this file
# is loaded today (a direct run, or another script's own
# `sys.path.insert(0, str(SCRIPTS_DIR))` before `import wo282_recon`).
from challenge_markers import CHALLENGE_MARKERS  # noqa: E402

# WO-939: a real wall-clock deadline around polite_request()/cdx_get()/
# wayback_id_read()'s own requests.request()/requests.get() calls -- see
# GOV_REQUEST_WALL_CLOCK_DEADLINE's own comment above and scripts/
# sweep_deadline.py's module docstring for the real hangs this closes.
# DeadlineExceeded itself needs no special handling here -- every one of
# this file's own call sites already catches a broad `except Exception`
# around these calls (a timeout has always been one more ordinary fetch
# failure to them, not a distinct case), so it's not imported by name.
from sweep_deadline import run_with_deadline  # noqa: E402

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
    # Added 2026-09-20 from subdomains confirmed real on a government's own
    # domain (rtr-business research, DNS/CT-log sweep + coverage registry):
    "live",  # live.pomonaca.gov -- Cablecast, an A record with no CNAME
    "media",  # media.cityofaikensc.gov -- Vimeo-backed media library
    "stream",  # stream.a2gov.org -- Ann Arbor's Cablecast site
    "mediasite",  # mediasite.sussexcountyde.gov -- Sonic Foundry
    "events",  # events.eurekacountynv.gov/meetings
    "weblink",  # Laserfiche WebLink agendas, 5 governments
    "laserfiche",  # 3 governments
    "onbase",  # OnBase Agenda Online, 2 governments
    "docs",  # 6 governments
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

# --------------------------------------------------------------------------
# Pure URL scoring (WO-366, 2026-09-14): lives here so phase 1 can score
# and keep the top-N Wayback CDX URLs live, not just discard everything
# but the first 60 in CDX's own urlkey order. `wo282_classify.py` (phase
# 2) imports these two functions from here instead of keeping its own
# copy -- one implementation, so the two scripts can't drift apart, same
# reasoning the HUB_WORD_LIFT/HUB_BIGRAM_LIFT/MEETING_WORD_HIT tables
# above already used.
# --------------------------------------------------------------------------


def hub_score(url: str) -> float:
    path_lower = urlparse(url).path.lower()
    score = 0.0
    for word, lift in HUB_WORD_LIFT.items():
        if word in path_lower:
            score = max(score, lift)
    for bigram, lift in HUB_BIGRAM_LIFT.items():
        if bigram.replace("-", "") in path_lower.replace("-", "").replace("/", ""):
            score = max(score, lift)
    return score


def meeting_score(url: str) -> float:
    path_lower = urlparse(url).path.lower()
    score = 0.0
    for word, hit in MEETING_WORD_HIT.items():
        if word in path_lower:
            score = max(score, hit)
    return score


# --------------------------------------------------------------------------
# Politeness: shared per-host rate limiter (one request in flight per
# host, >=HOST_DELAY_SECONDS between requests to the same host). Used by
# both this script and `wo282_targeted.py` (phase 3 imports this module
# for it, per that phase's identical per-host rule).
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
    # WO-939: run_with_deadline() wraps requests.request() itself, inside
    # wait_and_request()'s per-host lock -- so a real hang releases that
    # lock after GOV_REQUEST_WALL_CLOCK_DEADLINE instead of holding it
    # (and blocking every future retry against this same host) forever.
    return RATE_LIMITER.wait_and_request(
        host,
        run_with_deadline,
        requests.request,
        method,
        url,
        headers=HEADERS,
        timeout=timeout,
        allow_redirects=True,
        deadline_seconds=GOV_REQUEST_WALL_CLOCK_DEADLINE,
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


# Canada's two-level public suffixes: a government's own label sits one
# level above the province code (ville.sthonore.qc.ca -> "sthonore").
# Without this, every *.qc.ca domain guessed "qc", and qc.primegov.com
# really resolves -- to PrimeGov's own regional "OneMeeting Quebec"
# landing page, not any government's tenant. WO-324 (2026-09-12) measured
# 66-70 false PrimeGov hits from exactly that; see ENUMERATION_METHODS §333.
CA_PROVINCE_SUFFIX_LABELS = frozenset(
    {"ab", "bc", "mb", "nb", "nl", "ns", "nt", "nu", "on", "pe", "qc", "sk", "yk", "gc"}
)


# Generic infix labels that sit between a government's own name and its
# public suffix in the US state-suffix shape (x.k12.oh.us, ci.x.wa.us,
# co.x.il.us, www.x.y.us): none of them is ever the government's slug.
GENERIC_INFIX_LABELS = frozenset(
    {"k12", "ci", "co", "city", "town", "twp", "village", "vil", "cty", "www"}
)


def registrable_label(domain: str) -> str:
    parts = domain.lower().strip(".").split(".")
    if len(parts) < 2:
        return domain.lower()
    idx = -2
    if len(parts) >= 3 and parts[-1] == "us" and len(parts[-2]) <= 3:
        idx = -3
    elif (
        len(parts) >= 3 and parts[-1] == "ca" and parts[-2] in CA_PROVINCE_SUFFIX_LABELS
    ):
        idx = -3
    # Step past generic infixes (x.k12.oh.us -> "x", not "k12") while a
    # label remains to the left.
    while parts[idx] in GENERIC_INFIX_LABELS and -idx < len(parts):
        idx -= 1
    return parts[idx]


def label_is_guessable(label: str) -> bool:
    """A vendor tenant guess ("{label}.primegov.com") is only worth a DNS
    lookup when the label could be a government's own slug. A bare
    province/state code or any one- or two-character label never is --
    those hosts resolve to vendors' regional pages (qc.primegov.com), so
    a hit there would be a false platform signal, not a tenant."""
    label = (label or "").strip().lower()
    return (
        len(label) > 2
        and label not in CA_PROVINCE_SUFFIX_LABELS
        and label not in GENERIC_INFIX_LABELS
    )


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
        if not label_is_guessable(label):
            break
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
    """One CDX call, up to 3 attempts total (WO-366, 2026-09-14 -- widened
    from the original 2-attempt/2s-backoff version, see CDX_TIMEOUT's own
    comment), CDX_TIMEOUT per attempt, CDX_RETRY_BACKOFFS between
    attempts, then give up. Capped at ARCHIVE_CONCURRENCY in flight
    globally."""
    attempts = len(CDX_RETRY_BACKOFFS) + 1
    for attempt in range(attempts):
        with _ARCHIVE_SEMA:
            try:
                # WO-939: real wall-clock cap on top of CDX_TIMEOUT's
                # per-read bound -- see GOV_REQUEST_WALL_CLOCK_DEADLINE's
                # comment above. Held inside _ARCHIVE_SEMA the same as
                # before, just bounded now instead of unbounded.
                resp = run_with_deadline(
                    requests.get,
                    url,
                    headers=HEADERS,
                    timeout=CDX_TIMEOUT,
                    deadline_seconds=CDX_WALL_CLOCK_DEADLINE,
                )
                if resp.status_code == 200:
                    return resp
            except Exception:  # noqa: BLE001
                pass
        if attempt < len(CDX_RETRY_BACKOFFS):
            time.sleep(CDX_RETRY_BACKOFFS[attempt])
    return None


def wayback_id_read(url: str, timestamp: str) -> bytes | None:
    id_url = f"https://web.archive.org/web/{timestamp}id_/{url}"
    with _ARCHIVE_SEMA:
        try:
            resp = run_with_deadline(
                requests.get,
                id_url,
                headers=HEADERS,
                timeout=CDX_TIMEOUT,
                deadline_seconds=CDX_WALL_CLOCK_DEADLINE,
            )
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
    means phase-1 falls through to a live attempt below -- this module
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


# --------------------------------------------------------------------------
# Wayback CDX domain-wide index (bounded, per Ryan's "CDX scope and
# pagination" note)
# --------------------------------------------------------------------------

# WO-366 (2026-09-14): widened with Ryan's three real tokens --
# civicmedia, vod, event, stream, live, show -- on top of the original
# set. This is now a FALLBACK query only (see fetch_wayback_domain_index
# below), used when the single domain-wide query hits its own row cap.
# Every new token has a real, confirmed URL behind it (see
# tests/test_wo282_passive_discovery.py's
# test_meeting_path_regex_matches_*_token* cases for the exact URLs
# and their source):
#   civicmedia -- cityofhobart.org/CivicMedia?VID=326
#   vod        -- cloud.castus.tv/vod/comm7tv/video/...; TelVue's own vod
#                 CDN host is telvuevod-secure.akamaized.net (41 CDX pages
#                 confirmed, ENUMERATION_METHODS.md)
#   event      -- play.champds.com/atlantaga/event/1227
#   stream     -- archive-stream.granicus.com/OnDemand/... (Granicus's CDN)
#   live       -- youtube.com/live/{id} (Fair Oaks Ranch TX, Santa Barbara)
#   show       -- lnktv.lincoln.ne.gov/internetchannel/show/4442 (Lincoln
#                 NE's own self-hosted Cablecast-template page) and
#                 pgcps.cablecast.tv/show/3178 (Cablecast's bare /show/)
#
# WO-366 also adds a `(?i)` case-insensitive prefix, a real correctness
# fix found while sourcing the civicmedia example: CDX's `filter=` regex
# runs against the "original" field, which preserves the page's real
# capitalization (not the lowercased/SURT-normalized urlkey), and
# Hobart, IN's real page is `/CivicMedia?VID=326` -- mixed case. A
# case-sensitive "civicmedia" token would silently miss the exact URL
# shape it exists to catch (confirmed live: a CDX query filtered on
# lowercase "civicmedia" against cityofhobart.org surfaced two unrelated
# lowercase civicmedia.xml/RSS paths, not the real mixed-case page).
# `(?i)` is valid in both Python's re module and the CDX server's Java
# regex engine, so this is safe for the live filter string too, not just
# this module's own local matching.
MEETING_PATH_REGEX = (
    r"(?i).*(agenda|minutes|meeting|council|commission|board|video|clip|player|watch"
    r"|civicmedia|vod|event|stream|live|show).*"
)

# WO-366 (2026-09-14): picked from the real score distribution on a
# 10-government sample (research/wo366_methods_section.md Table 2).
# Keeping the old default of 60 genuinely under-counted on two of the ten
# real domains sampled: LaSalle, IL (1,054 URLs seen, 75 score >0 -- the
# score at rank 60 was still 7.0, meaning 15 real candidates were being
# cut) and Grand Isle County, VT (728 URLs seen, 212 score >0 -- the
# score at rank 150 was STILL 10.0, meaning the true candidate tail runs
# well past 150). 200 comfortably covers LaSalle's full 75 and nearly all
# of Grand Isle's 212 (a documented, accepted gap on that one real
# outlier, not silently assumed complete) while staying a bounded
# constant rather than growing open-ended for one heavy-tailed domain.
# Replaces the old flat narrow_urls[:MAX_FLAGGED_RECORDED] (60) trunca-
# tion, which kept whichever 60 URLs CDX's own urlkey order put first,
# not the most relevant 60 -- see fetch_wayback_domain_index() below.
WAYBACK_TOP_N = 200


def _score_and_keep_top(urls: list[str], top_n: int) -> list[str]:
    """Score every URL with hub_score()/meeting_score() (WO-366) and keep
    the top_n by combined relevance, instead of the first N in whatever
    order CDX returned them."""
    scored = [(max(hub_score(u), meeting_score(u)), u) for u in urls]
    scored.sort(key=lambda t: t[0], reverse=True)
    return [u for _, u in scored[:top_n]]


def fetch_wayback_domain_index(domain: str) -> dict:
    """WO-366 (2026-09-14) redesign: ONE domain-wide CDX query
    (matchType=domain, so subdomains count -- see module docstring),
    scored client-side and trimmed to the top WAYBACK_TOP_N URLs. The old
    meeting/agenda-path-regex query only runs as a FALLBACK, when the
    single query above comes back truncated at its own row cap (meaning
    real meeting URLs could have been crowded out before CDX ever got to
    them).

    KNOWN, MEASURED LIMIT (research/wo366_methods_section.md): CDX's
    urlkey sort puts every bare-domain URL before ANY subdomain URL, so
    on a domain whose OWN url count already exceeds the 2,000-row cap
    (confirmed live on Sedgwick County KS: 538k population, its own pages
    alone fill all 2,000 rows), the primary query alone still won't reach
    a subdomain like imaging.sedgwickcounty.org even though matchType=
    domain makes it structurally reachable now (confirmed separately: a
    direct query scoped to that subdomain returns 200+ real captures,
    including real meeting agenda packets -- the content is indexed, it's
    a row-budget/ordering problem, not an absence). The fallback query
    exists to rescue exactly this case, but is itself vulnerable to the
    same CDX degradation this module already documents, and a regex
    filter combined with matchType=domain on a large site was confirmed
    live, repeatedly, to time out for Sedgwick specifically. Not solved
    by this WO -- logged in BACKLOG.md as a live gap (a DNS-enumerated
    per-subdomain query, or a per-subdomain row budget, would be the next
    step)."""
    out = {
        "reachable": None,
        "broad_row_count": 0,
        "narrow_row_count": 0,
        "top_urls": [],
        "cdx_truncated": False,
        "error": "",
    }
    from_date = time.strftime("%Y%m%d", time.gmtime(time.time() - 3 * 365 * 86400))
    domain_url = (
        "https://web.archive.org/cdx/search/cdx"
        f"?url={domain}&matchType=domain&collapse=urlkey&filter=statuscode:200"
        f"&filter=mimetype:text/html&from={from_date}&fl=original,timestamp"
        "&limit=2000&output=json"
    )
    resp = cdx_get(domain_url)
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
    all_urls = [r[0] for r in rows if r]
    seen = set(all_urls)
    truncated = len(rows) >= 2000
    out["cdx_truncated"] = truncated

    if truncated:
        narrow_base = (
            "https://web.archive.org/cdx/search/cdx"
            f"?url={domain}&matchType=domain&collapse=urlkey&filter=statuscode:200"
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
        out["narrow_row_count"] = len(narrow_urls)
        for u in narrow_urls:
            if u not in seen:
                seen.add(u)
                all_urls.append(u)

    out["top_urls"] = _score_and_keep_top(all_urls, WAYBACK_TOP_N)
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


SCRATCH_DIR = Path(
    "/private/tmp/claude-501/-Users-mroconnell-Documents-rtr-deeplink--claude-worktrees-platform-detection-backfill-c9742a"
    "/1d27de13-eb07-451a-a07a-bb18900b5618/scratchpad/agents/ac2e880048ce53eb0/wo282_homepages"
)

HONEST_HEADERS = HEADERS
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
_cdx_health_lock = threading.Lock()
_cdx_healthy = True
_gov_count_since_health_check = 0


def log(msg: str) -> None:
    print(msg, flush=True)


def probe_cdx_health() -> bool:
    """A fresh, cheap CDX call -- not reused from a government's own
    fetch -- so a health read is never confounded with that
    government's own rate limiting or errors."""
    resp = cdx_get(
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
        resp = polite_request(url)
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e)[:200]
        # A dropped connection is grounds for a browser-header retry.
        try:
            resp = RATE_LIMITER.wait_and_request(
                urlparse(url).netloc,
                requests.request,
                "GET",
                url,
                headers=BROWSER_HEADERS,
                timeout=GOV_REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            mode = "browser-headers-after-drop"
        except Exception as e2:  # noqa: BLE001
            out["error"] = str(e2)[:200]
            out["access_mode"] = "blocked-plain-http"
            return out

    if resp is not None and resp.status_code == 403:
        try:
            resp = RATE_LIMITER.wait_and_request(
                urlparse(url).netloc,
                requests.request,
                "GET",
                url,
                headers=BROWSER_HEADERS,
                timeout=GOV_REQUEST_TIMEOUT,
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

    if is_challenge(resp.text):
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
    """Own fetch (not WO-273's plain fetch_live_robots, which this file
    never carried forward -- see this file's own module docstring -- to
    avoid a second, redundant robots.txt GET just to read Crawl-delay):
    one request, parses sitemap directives, disallow paths
    (parse_robots(), moved in from wo273_recon.py), AND Crawl-delay from
    the same response body. Flags any hub-vocabulary Disallow path as
    disallowed_lead (never fetched)."""
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
    crawl_delay = parse_crawl_delay(resp.text)
    if crawl_delay and crawl_delay > HOST_DELAY_SECONDS:
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
    """Own sitemap-follow loop (not WO-273's plain fetch_live_sitemap,
    which this file never carried forward -- it hardcoded the
    module-level MAX_SUB_SITEMAPS cap and the module-level
    polite_request, both unsafe to override per-call under this
    script's concurrent-governments-per-thread-pool design). Same
    algorithm as that original version (robots-named sitemaps first, then the
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
    extra_sleep = max(0.0, (crawl_delay or 0.0) - HOST_DELAY_SECONDS)

    def is_disallowed(url: str) -> bool:
        path = urlparse(url).path
        return any(d in path for d in disallowed)

    def request_capped(url: str):
        if extra_sleep:
            time.sleep(extra_sleep)
        resp = polite_request(url)
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
            for sub_url in rank_sub_sitemaps(urls)[:MAX_SUB_SITEMAPS_V2]:
                if is_disallowed(sub_url):
                    continue
                try:
                    sub_resp = request_capped(sub_url)
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
    dns_info = dns_lookup(domain)
    timings["dns_ms"] = int((time.monotonic() - t0) * 1000)
    record["dns"] = dns_info

    if not dns_has_any_answer(dns_info):
        record["dns_gate"] = "dns-unresolvable"
        record["timings_ms"] = timings
        return record
    record["dns_gate"] = "resolved"

    archive_sm = {}
    if cdx_healthy:
        t1 = time.monotonic()
        archive_sm = fetch_archived_sitemap_and_robots(domain)
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
        or (archive_sm.get("sitemap_wayback_age_days") or 99999) > STALE_DAYS
    )
    sitemap_source = "none"
    sitemap_urls: list[str] = []
    sitemap_url_count = 0
    if sitemap_body_raw and not sitemap_stale:
        kind, urls = parse_sitemap_xml(sitemap_body_raw)
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
        wayback_index = fetch_wayback_domain_index(domain)
        timings["wayback_index_ms"] = int((time.monotonic() - t5) * 1000)
    record["wayback_index"] = {
        "reachable": wayback_index["reachable"],
        "broad_row_count": wayback_index["broad_row_count"],
        "narrow_row_count": wayback_index["narrow_row_count"],
        "narrow_urls": wayback_index["narrow_urls"],
        "error": wayback_index["error"],
    }

    t6 = time.monotonic()
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


def cmd_sweep(limit: int, concurrency: int) -> None:
    population = load_population()
    done = load_done_domains()
    remaining = [r for r in population if r["domain"] not in done]
    log(f"{len(done)} already done, {len(remaining)} remaining of {len(population)}")

    to_process = remaining[:limit] if limit else remaining
    log(f"processing {len(to_process)} governments at concurrency={concurrency}")

    start = time.monotonic()
    completed = 0
    errors = 0
    with (
        open(RECON_JSONL, "a", encoding="utf-8") as out,
        ThreadPoolExecutor(max_workers=concurrency) as pool,
    ):
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
