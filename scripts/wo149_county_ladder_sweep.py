"""WO-149 (2026-09-10): access-ladder sweep of 1,424 US counties over
5,000 people with no Archive page -- rtr-business/research/
wo149_candidates.csv, candidate list 3 in docs/BREADTH_SWEEP_BRIEF.md
(WO-130's counties sweep could not get past a plain two-hop client on
any of these). This follows the same access-ladder method and reuse
strategy as its sibling WO (WO-147, signature-less municipality
rejects, scripts/wo147_access_ladder_sweep.py, if it lands first) --
same taxonomy, same reuse of wo134_confirmed_hits_ingest.py's resolve/
ingest pipeline -- adapted for county-specific quirks per scripts/
wo130_county_ingest.py: a NACo domain fallback for a county whose
registry `domain` no longer resolves, forcing the resolved page's
`jurisdiction` to the county's own exact registry name rather than
whatever the adapter guessed (a county sharing a name with an
independent city elsewhere is a real, confirmed trap -- Charleston
County SC's domain once pointed at Charleston WV's tenant), and
rejecting a hit whose adapter-guessed jurisdiction plainly names a
different government as `wrong-domain-mapping` instead of silently
force-ingesting over it.

Goal (Ryan's, restated in the brief): one meeting WITH VIDEO per county,
breadth not depth. Only meetings with video become Archive pages (tier
1/2, real captions). Tier 3 (real video, no reachable captions) is
probed for a dead link/too-short clip (WO-144's probe_queue_entry) before
it ever reaches the queue file. Agenda-only is recorded `no-video-found`
and never ingested -- last round an agent ingested an agenda-only page
by mistake, so this is a hard gate, not a preference: see the "ingest
gate" paragraph near the end of this docstring.

Method, per docs/BREADTH_SWEEP_BRIEF.md, docs/COVERAGE_HANDOVER.md and
CLAUDE.md's "politely" rule:

1. **Start URL.** `research_calendar_url`/`research_meeting_url` first
   (a known meetings page, one hop deeper than the homepage -- on a 404
   there, fall back to the homepage, since a 404 means a stale URL, not
   a dead host); otherwise `hub_url`, then `domain`.
2. **Access ladder** -- can we even read this host, and with which rung:
   a. plain HTTP, honest headers (HONEST_HEADERS, copied verbatim from
      rtr-business/research/wo141_access_ladder_pilot.py -- attribution
      in that constant's own comment). A domain that does not resolve
      tries www./http:// variants and the NACo `website` column
      (naco_county_websites.csv) before `dead` -- the handover says the
      county gap is stale data, not code.
   b. browser headers (BROWSER_HEADERS, same source), once, only after a
      403 or a dropped connection -- never after a 404.
   c. headless (Playwright, one browser, one host at a time), only when
      an earlier rung got a real page with no visible meeting link at
      all -- never run on a host that 403'd browser headers (WO-141
      found headless does worse there).
   d. stop at a human-verification challenge marker (CHALLENGE_MARKERS,
      same source) -- record it, never retry past it.
3. **Platform discovery** -- once a rung produces a real page, scan it
   (and, if nothing found, one hop into meeting/agenda/council/video-
   hinted links) for a link `detect_platform()` recognizes, PLUS the
   row's own `known_platform` against its home/hub url, PLUS a
   rtr-discovery thorough-mode enumeration against a SCRATCH ledger copy
   (never the real one -- other discovery sessions are live) when the
   platform is one discovery's own enumerators cover.
4. **Resolve/ingest** -- every found (platform, url) pair, up to 6, is
   handed to wo134_confirmed_hits_ingest.py's own `process_row()`
   UNCHANGED except for two hooks added to that module FOR this WO (and
   reused as-is by WO-147's own sibling script, which needed the exact
   same shape): `TIER3_HANDLER` (routes a tier-3 find to
   `wo149_tier3_pending.csv` for probing instead of the queue file, per
   Ryan's "probe before queue" rule) and `JURISDICTION_CHECK_HOOK` (the
   force-and-verify-jurisdiction logic described above).

YouTube: prefer the delegating platform (rung 2/3's platform discovery,
or `known_platform`). A county page that links to its own YouTube
channel is the one exception, handled generically inside wo134's own
`resolve_seed()` (`_is_youtube_channel_url()` / `resolve_youtube_
channel()`) -- reused, not reimplemented, since it already needed no
county-specific change (wo130_county_ingest.py's own narrower channel
helper predates it and is superseded here).

Run with the interpreter that can import BOTH `discovery` and `app`:
    ~/Documents/rtr-discovery/.venv/bin/python scripts/wo149_county_ladder_sweep.py

Usage:
    python scripts/export_meeting_inventory.py --out-dir /tmp/wo149_inventory --source export
    ~/Documents/rtr-discovery/.venv/bin/python scripts/wo149_county_ladder_sweep.py --limit 30
    ~/Documents/rtr-discovery/.venv/bin/python scripts/wo149_county_ladder_sweep.py   # full run, resumable

**The ingest gate this WO's brief calls out** (Ryan: "last round an
agent ingested an agenda-only page and Ryan had to delete it") is the
existing, already-tested behavior in wo134_confirmed_hits_ingest.py's
own process_row(): a resolve with `agenda_items`/`agenda_link` but no
`segments`/`video_url` returns outcome `no_video_found` and is never
POSTed to the Archive -- see that function's own
`if not (segments or agenda_items or result.agenda_link or
result.video_url): continue` / `best_no_video_result` branches, and this
script's own `process_candidate()` maps that outcome straight to
`reject_reason=no-video-found`, never to `ingested_tier1_2`. The 30-row
pilot this WO's brief requires (`--limit 30`) is where that gate gets
checked by hand: for every row this run reports `ingested_tier1_2`, open
`meeting_url` and confirm it is a real video page, not an agenda-only
one that slipped past a title/segment mismatch.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("RTR_DEEPLINK_PATH", str(REPO_ROOT))

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import detect_platform  # noqa: E402
from app.utils.gov_registry.registry import government_for_id  # noqa: E402

import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402

RESEARCH_DIR = Path("/Users/mroconnell/Documents/rtr-business/research")
CANDIDATES_CSV = RESEARCH_DIR / "wo149_candidates.csv"
NACO_CSV = RESEARCH_DIR / "naco_county_websites.csv"
REPORT_CSV = RESEARCH_DIR / "wo149_report.csv"
DISCOVERY_SEEDS_CSV = RESEARCH_DIR / "wo149_discovery_seeds.csv"
HOST_ACCESS_MODES_CSV = RESEARCH_DIR / "wo149_host_access_modes.csv"
TIER3_PENDING_CSV = RESEARCH_DIR / "wo149_tier3_pending.csv"
DEFAULT_INVENTORY_CSV = Path("/tmp/wo149_inventory/meeting_inventory.csv")

DISCOVERY_ROOT = Path.home() / "Documents" / "rtr-discovery"
SCRATCH_LEDGER = Path("/tmp/wo149_ledger.db")

GOV_DELAY_SECONDS = 1.5  # between counties
HOST_DELAY_SECONDS = 2.0  # between requests to the SAME host
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=8)

# --- copied verbatim from rtr-business/research/wo141_access_ladder_pilot.py
# (WO-141, 2026-09-10) -- see that file's own comments for the false
# positives each one fixes. Not re-derived here on purpose. ---
HONEST_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-encoding": "gzip, deflate",
    "accept-language": "en-US,en;q=0.9",
    "user-agent": (
        "rtr-upcoming/0.1 (Red Tape Recordings public-agenda reader; "
        "+https://redtaperecordings.com/about)"
    ),
}
BROWSER_HEADERS = {
    "accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "accept-encoding": "gzip, deflate, br",
    "accept-language": "en-US,en;q=0.9",
    "priority": "u=0, i",
    "sec-ch-ua": '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
}
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

HOP1_HINT_WORDS = [
    "agenda",
    "minutes",
    "calendar",
    "meeting",
    "commissioners court",
    "county commission",
    "board of supervisors",
    "board of commissioners",
    "city council",
    "town council",
    "board of",
    "video",
    "stream",
    "council",
    "commission",
]
MAX_HOP_LINKS = 8

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
}

DISCOVERY_ENUMERABLE = {
    "granicus",
    "civicclerk",
    "primegov",
    "escribe",
    "legistar",
    "swagit",
    "iqm2",
    "cablecast",
    "municode_meetings",
    "civicweb",
    "civicplus",
    "proudcity",
}

_TAGS = ("a", "iframe", "video", "source")
_ONCLICK_URL_RE = re.compile(r"""\(\s*['"]([^'"]+)""")

# Copied from wo141_access_ladder_pilot.py / reused by WO-147's sibling
# script -- a bare vendor apex domain (with or without "www.") is never a
# real per-tenant instance (e.g. a "Powered by Granicus" footer badge
# linking to granicus.com's own marketing homepage).
_VENDOR_MARKETING_APEX = {
    "granicus.com",
    "legistar.com",
    "civicclerk.com",
    "primegov.com",
    "civicweb.net",
    "escribemeetings.com",
    "iqm2.com",
    "swagit.com",
    "cablecast.tv",
    "telvue.com",
    "champds.com",
    "clerkshq.com",
    "municodemeetings.com",
    "civicplus.com",
    "civiclive.com",
}
_VENDOR_MARKETING_SUBDOMAINS = {
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
}


def _is_vendor_marketing_apex(netloc: str) -> bool:
    n = netloc.lower()
    if n.startswith("www."):
        n = n[4:]
    if n in _VENDOR_MARKETING_APEX:
        return True
    parts = netloc.lower().split(".")
    if len(parts) >= 3 and parts[0] in _VENDOR_MARKETING_SUBDOMAINS:
        rest = ".".join(parts[1:])
        if rest in _VENDOR_MARKETING_APEX:
            return True
    return False


def normalize_known_platform(raw: str) -> str:
    p = (raw or "").strip().lower()
    return _PLATFORM_ALIASES.get(p, p)


def normalize_home_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    return raw


_YT_ID_IN_URL_RE = re.compile(r"(?:v=|/embed/|/live/|youtu\.be/)([A-Za-z0-9_-]{11})")


def canonicalize_youtube_url(url: str) -> str:
    """A real `research_meeting_url` in this WO's own candidate CSV can
    be a raw scraped `<iframe src>` value with every JW/YouTube player
    widget parameter still attached (confirmed live, Lake County OH:
    `.../embed/AscWHEa0ay4?enablejsapi=1&autoplay=0&...&disablekb=0&` --
    note the dangling trailing `&`, caught by `tests/
    test_transcription_queue_files.py`'s dangling-query-separator check
    once this line reached the real tier-3 queue). yt-dlp resolves a
    messy URL like this fine since it only needs the 11-char video id,
    but the queue file itself should never carry one -- rebuild the
    canonical `watch?v=` form instead of passing the scrape artifact
    through verbatim."""
    m = _YT_ID_IN_URL_RE.search(url)
    if m:
        return f"https://www.youtube.com/watch?v={m.group(1)}"
    return url


def is_challenge(html_text: str) -> bool:
    lower = html_text.lower()
    return any(marker in lower for marker in CHALLENGE_MARKERS)


def waf_family_from_headers(headers: dict) -> str:
    h = {k.lower(): v for k, v in headers.items()}
    blob = " ".join(f"{k}:{v}" for k, v in h.items()).lower()
    if "cf-ray" in h or "cloudflare" in h.get("server", "").lower():
        return "cloudflare"
    if (
        "_abck" in blob
        or "bm_sv" in blob
        or "akamaighost" in h.get("server", "").lower()
        or any(k.startswith("x-akamai") for k in h)
    ):
        return "akamai"
    if "x-amzn-waf-action" in h or "x-amzn-requestid" in h:
        return "aws_waf"
    if "x-sucuri-id" in h or "sucuri" in h.get("server", "").lower():
        return "sucuri"
    if "x-iinfo" in h or "incap_ses" in blob or "visid_incap" in blob:
        return "imperva_incapsula"
    return "none"


def find_platform_link(html_text: str, final_url: str) -> Optional[Tuple[str, str]]:
    if "agendacenter" in html_text.lower():
        soup = BeautifulSoup(html_text, "html.parser")
        for a in soup.find_all("a", href=True):
            if "agendacenter" in a["href"].lower():
                return "civicplus", urljoin(final_url, a["href"])
        origin = urlparse(final_url)
        return "civicplus", f"{origin.scheme}://{origin.netloc}/AgendaCenter"

    soup = BeautifulSoup(html_text, "html.parser")
    page_no_frag = urlparse(final_url)._replace(fragment="").geturl()
    for tag in soup.find_all(_TAGS):
        values = []
        href_or_src = tag.get("href") or tag.get("src")
        if href_or_src:
            values.append(href_or_src.strip())
        onclick = tag.get("onclick")
        if onclick:
            m = _ONCLICK_URL_RE.search(onclick)
            if m:
                values.append(m.group(1).strip())
        for value in values:
            if not value or value.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
            candidate = urljoin(final_url, value)
            if urlparse(candidate)._replace(fragment="").geturl() == page_no_frag:
                continue
            platform = detect_platform(candidate)
            if (
                platform
                and platform != "unknown"
                and not _is_vendor_marketing_apex(urlparse(candidate).netloc)
            ):
                return platform, candidate
    return None


def find_hop_links(html_text: str, final_url: str) -> List[str]:
    soup = BeautifulSoup(html_text, "html.parser")
    out: List[str] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        text = (a.get_text() or "").strip().lower()
        href = a["href"]
        hay = f"{text} {href}".lower()
        if any(w in hay for w in HOP1_HINT_WORDS):
            full = urljoin(final_url, href)
            if full not in seen and urlparse(full).scheme in ("http", "https"):
                seen.add(full)
                out.append(full)
        if len(out) >= MAX_HOP_LINKS:
            break
    return out


_DNS_ERROR_PATTERNS = (
    "nodename nor servname",
    "name or service not known",
    "getaddrinfo failed",
    "temporary failure in name resolution",
    "cannot connect to host",
)


def classify_exception(exc: Exception) -> str:
    if isinstance(exc, asyncio.TimeoutError):
        return "timeout"
    msg = str(exc).lower()
    if any(p in msg for p in _DNS_ERROR_PATTERNS):
        return "dns"
    return "connection"


@dataclass
class FetchResult:
    status: Optional[int] = None
    final_url: str = ""
    html: Optional[str] = None
    error: Optional[str] = None
    error_kind: str = ""
    waf_family: str = "none"


async def fetch_one(
    session: aiohttp.ClientSession, url: str, headers: dict
) -> FetchResult:
    try:
        async with session.get(
            url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True
        ) as resp:
            html_text = await resp.text(errors="replace")
            return FetchResult(
                status=resp.status,
                final_url=str(resp.url),
                html=html_text,
                waf_family=waf_family_from_headers(dict(resp.headers)),
            )
    except Exception as e:  # noqa: BLE001 -- record and classify, never raise
        return FetchResult(error=str(e)[:200], error_kind=classify_exception(e))


_naco_rows: Optional[List[dict]] = None


def naco_website(name: str, state: str) -> Optional[str]:
    global _naco_rows
    if _naco_rows is None:
        if not NACO_CSV.exists():
            _naco_rows = []
        else:
            with NACO_CSV.open(newline="", encoding="utf-8") as f:
                _naco_rows = list(csv.DictReader(f))
    name_l = name.strip().lower()
    state_u = state.strip().upper()
    for r in _naco_rows:
        if (
            r.get("county_name", "").strip().lower() == name_l
            and r.get("state", "").strip().upper() == state_u
        ):
            w = (r.get("website") or "").strip()
            if w:
                return w
    return None


@dataclass
class LadderResult:
    access_mode: str  # api | plain | browser-headers | headless | challenge | dead
    rung_answered: str  # plain | browser-headers | headless | challenge | dead | none
    home_url: str
    final_html: Optional[str]
    final_url: str
    waf_family: str
    note: str
    platform: Optional[str] = None
    hit_url: Optional[str] = None
    corrected_domain: str = ""


async def run_access_ladder(
    session: aiohttp.ClientSession, name: str, state: str, domain: str, start_url: str
) -> LadderResult:
    """Plain -> browser-headers -> headless, stopping at a challenge or
    the first real platform link. `start_url` is the row's own
    research_calendar_url/research_meeting_url when set (one hop deeper
    than the homepage -- a 404 there falls back to the homepage, per
    CLAUDE.md's "a 404 is a stale URL, not a dead host" rule), otherwise
    hub_url/domain."""
    candidates: List[str] = []
    primary = normalize_home_url(start_url) or normalize_home_url(domain)
    if primary:
        candidates.append(primary)
    home_fallback = normalize_home_url(domain)
    if home_fallback and home_fallback != primary:
        candidates.append(home_fallback)  # tried only after a 404 on primary, below
    net = (
        urlparse(primary or home_fallback).netloc if (primary or home_fallback) else ""
    )
    if net and not net.startswith("www."):
        base = primary or home_fallback
        candidates.append(f"https://www.{net}{urlparse(base).path}")
    if (primary or home_fallback) and (primary or home_fallback).startswith("https://"):
        base = primary or home_fallback
        candidates.append("http://" + base[len("https://") :])

    if not candidates:
        # Real, confirmed-live case (St. Louis County MO, WO-149's own
        # 30-row pilot): a row with no domain, no hub_url, and no
        # research_calendar_url/research_meeting_url at all -- nothing to
        # even try a plain fetch against. Go straight to the NACo
        # fallback rather than crashing on an empty candidate list; if
        # that has nothing either, this host is simply unreachable from
        # what the research file knows.
        naco = naco_website(name, state)
        if not naco:
            return LadderResult(
                "dead",
                "dead",
                "",
                None,
                "",
                "none",
                "no domain/hub_url/research url on this row, and no NACo website",
            )
        naco_url = normalize_home_url(naco)
        r0 = await fetch_one(session, naco_url, HONEST_HEADERS)
        if r0.error_kind == "dns" or r0.html is None:
            return LadderResult(
                "dead",
                "dead",
                naco_url,
                None,
                "",
                "none",
                f"no domain/hub_url/research url on this row; NACo website {naco} "
                "also unreachable",
            )
        if is_challenge(r0.html):
            return LadderResult(
                "challenge",
                "challenge",
                naco_url,
                r0.html,
                r0.final_url,
                r0.waf_family,
                f"recovered via NACo website column: {naco}",
                corrected_domain=urlparse(naco_url).netloc,
            )
        hit0 = find_platform_link(r0.html, r0.final_url)
        return LadderResult(
            "plain",
            "plain",
            naco_url,
            r0.html,
            r0.final_url,
            r0.waf_family,
            f"recovered via NACo website column: {naco}",
            hit0[0] if hit0 else None,
            hit0[1] if hit0 else None,
            urlparse(naco_url).netloc,
        )

    notes: List[str] = []
    dns_failures = 0
    last_result: Optional[FetchResult] = None
    home_url_used = primary or home_fallback
    corrected_domain = ""

    for i, url in enumerate(candidates):
        if i:
            await asyncio.sleep(HOST_DELAY_SECONDS)
        r = await fetch_one(session, url, HONEST_HEADERS)
        # A 404 on the deeper research URL is a stale link, not a dead
        # host -- fall back to the plain homepage rather than treating it
        # as this host's final answer.
        if (
            r.status == 404
            and url == primary
            and home_fallback
            and home_fallback != primary
        ):
            notes.append(f"404 on research url {url}, falling back to homepage")
            continue
        last_result = r
        home_url_used = url
        if r.error_kind == "dns":
            dns_failures += 1
            notes.append(f"dns-fail on {url}")
            continue
        break
    if last_result is None:
        # every candidate 404'd or dns-failed; use whatever we have
        last_result = r  # type: ignore[possibly-undefined]

    if (
        last_result is not None
        and last_result.error_kind == "dns"
        and dns_failures >= len(candidates)
    ):
        naco = naco_website(name, state)
        if naco:
            naco_url = normalize_home_url(naco)
            await asyncio.sleep(HOST_DELAY_SECONDS)
            r2 = await fetch_one(session, naco_url, HONEST_HEADERS)
            if r2.error_kind != "dns":
                last_result = r2
                home_url_used = naco_url
                corrected_domain = urlparse(naco_url).netloc
                notes.append(f"recovered via NACo website column: {naco}")

    r = last_result
    assert r is not None

    if r.error_kind == "dns":
        return LadderResult(
            "dead", "dead", home_url_used, None, "", "none", "; ".join(notes)
        )
    if r.error_kind == "timeout" and r.status is None:
        await asyncio.sleep(HOST_DELAY_SECONDS)
        rb = await fetch_one(session, home_url_used, BROWSER_HEADERS)
        if rb.html and not is_challenge(rb.html):
            hit = find_platform_link(rb.html, rb.final_url)
            if hit:
                return LadderResult(
                    "browser-headers",
                    "browser-headers",
                    home_url_used,
                    rb.html,
                    rb.final_url,
                    rb.waf_family,
                    "; ".join(notes),
                    hit[0],
                    hit[1],
                    corrected_domain,
                )
            return LadderResult(
                "browser-headers",
                "browser-headers",
                home_url_used,
                rb.html,
                rb.final_url,
                rb.waf_family,
                "; ".join(notes + ["reached under browser headers, no link found"]),
                corrected_domain=corrected_domain,
            )
        if rb.html and is_challenge(rb.html):
            return LadderResult(
                "challenge",
                "challenge",
                home_url_used,
                rb.html,
                rb.final_url,
                rb.waf_family,
                "; ".join(notes),
                corrected_domain=corrected_domain,
            )
        return LadderResult(
            "timeout", "dead", home_url_used, None, "", "none", "; ".join(notes)
        )

    if r.html is None:
        return LadderResult(
            "blocked-plain-http",
            "none",
            home_url_used,
            None,
            "",
            "none",
            "; ".join(notes + [f"error: {r.error}"]),
            corrected_domain=corrected_domain,
        )

    if is_challenge(r.html):
        return LadderResult(
            "challenge",
            "challenge",
            home_url_used,
            r.html,
            r.final_url,
            r.waf_family,
            "",
            corrected_domain=corrected_domain,
        )

    hit = find_platform_link(r.html, r.final_url)
    if hit:
        return LadderResult(
            "plain",
            "plain",
            home_url_used,
            r.html,
            r.final_url,
            r.waf_family,
            "",
            hit[0],
            hit[1],
            corrected_domain,
        )

    hop_links = find_hop_links(r.html, r.final_url)
    if r.status == 403:
        await asyncio.sleep(HOST_DELAY_SECONDS)
        rb = await fetch_one(session, home_url_used, BROWSER_HEADERS)
        if rb.html and is_challenge(rb.html):
            return LadderResult(
                "challenge",
                "challenge",
                home_url_used,
                rb.html,
                rb.final_url,
                rb.waf_family,
                "",
                corrected_domain=corrected_domain,
            )
        if rb.html is None or rb.status == 403:
            return LadderResult(
                "blocked-browser-headers",
                "none",
                home_url_used,
                None,
                "",
                rb.waf_family,
                "403 under both plain and browser headers",
                corrected_domain=corrected_domain,
            )
        hit = find_platform_link(rb.html, rb.final_url)
        if hit:
            return LadderResult(
                "browser-headers",
                "browser-headers",
                home_url_used,
                rb.html,
                rb.final_url,
                rb.waf_family,
                "",
                hit[0],
                hit[1],
                corrected_domain,
            )
        hop_links = find_hop_links(rb.html, rb.final_url)
        r = rb

    for link in hop_links[:MAX_HOP_LINKS]:
        await asyncio.sleep(HOST_DELAY_SECONDS)
        headers = BROWSER_HEADERS if r.status == 403 else HONEST_HEADERS
        rh = await fetch_one(session, link, headers)
        if rh.html and is_challenge(rh.html):
            return LadderResult(
                "challenge",
                "challenge",
                home_url_used,
                rh.html,
                rh.final_url,
                rh.waf_family,
                "",
                corrected_domain=corrected_domain,
            )
        if rh.html:
            hit = find_platform_link(rh.html, rh.final_url)
            if hit:
                mode = "browser-headers" if headers is BROWSER_HEADERS else "plain"
                return LadderResult(
                    mode,
                    mode,
                    home_url_used,
                    rh.html,
                    rh.final_url,
                    rh.waf_family,
                    "",
                    hit[0],
                    hit[1],
                    corrected_domain,
                )

    if not hop_links:
        await asyncio.sleep(HOST_DELAY_SECONDS)
        rh_html, rh_url, rh_err = await fetch_headless(r.final_url or home_url_used)
        if rh_html and is_challenge(rh_html):
            return LadderResult(
                "challenge",
                "challenge",
                home_url_used,
                rh_html,
                rh_url,
                "none",
                "",
                corrected_domain=corrected_domain,
            )
        if rh_html:
            hit = find_platform_link(rh_html, rh_url)
            if hit:
                return LadderResult(
                    "headless",
                    "headless",
                    home_url_used,
                    rh_html,
                    rh_url,
                    "none",
                    "",
                    hit[0],
                    hit[1],
                    corrected_domain,
                )
            return LadderResult(
                "headless",
                "headless",
                home_url_used,
                rh_html,
                rh_url,
                "none",
                "headless reached the page, no platform link found",
                corrected_domain=corrected_domain,
            )
        # Real, confirmed-live classification bug caught in this WO's own
        # full run (2026-09-10, 10 of 1,424 rows): a genuine headless
        # failure (SSL error, connection reset/refused, a download
        # prompt intercepting navigation) was falling through to
        # access_mode="plain" with the error buried in a note -- a
        # content-class outcome (no-platform-link-found) for a host we
        # never actually reached. This IS an access-class failure: we
        # got a real page under `r` (honest/browser headers) with no
        # visible link, tried headless as the next rung per the ladder,
        # and headless itself could not load anything at all.
        return LadderResult(
            "blocked-headless",
            "none",
            home_url_used,
            None,
            "",
            r.waf_family,
            f"headless failed: {rh_err}",
            corrected_domain=corrected_domain,
        )

    mode = "browser-headers" if r.status == 403 else "plain"
    return LadderResult(
        mode,
        mode,
        home_url_used,
        r.html,
        r.final_url,
        r.waf_family,
        "reached, hop links checked, no platform link found",
        corrected_domain=corrected_domain,
    )


def fetch_headless_sync(url: str) -> Tuple[Optional[str], str, Optional[str]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None, url, "playwright not installed"
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(
                    user_agent=BROWSER_HEADERS["user-agent"],
                    viewport={"width": 1280, "height": 800},
                )
                page.goto(url, timeout=15000, wait_until="load")
                page.wait_for_timeout(3000)
                content = page.content()
                final_url = page.url
                return content, final_url, None
            finally:
                browser.close()
    except Exception as e:  # noqa: BLE001
        return None, url, f"{type(e).__name__}: {e}"


async def fetch_headless(url: str) -> Tuple[Optional[str], str, Optional[str]]:
    return await asyncio.to_thread(fetch_headless_sync, url)


# --- rtr-discovery enrichment (best effort) ------------------------------

_ledger = None
_discovery_ready = False


def ensure_discovery() -> bool:
    global _ledger, _discovery_ready
    if _discovery_ready:
        return True
    try:
        sys.path.insert(0, str(DISCOVERY_ROOT))
        if not SCRATCH_LEDGER.exists():
            shutil.copy2(DISCOVERY_ROOT / "ledger.db", SCRATCH_LEDGER)
        from discovery import config as discovery_config
        from discovery.ledger import Ledger

        discovery_config.load_env()
        _ledger = Ledger(str(SCRATCH_LEDGER))
        _discovery_ready = True
        return True
    except Exception as e:  # noqa: BLE001
        print(f"WARNING: discovery enrichment disabled ({e})", file=sys.stderr)
        _discovery_ready = False
        return False


async def discovery_candidate_urls(
    netloc: str, platform: str, gov_id: str, state: str, limit: int = 6
) -> Tuple[List[str], str]:
    if platform not in DISCOVERY_ENUMERABLE:
        return [], "platform not in discovery's enumerator set"
    if not ensure_discovery():
        return [], "discovery not available this run"
    try:
        from discovery.enumerate_stage import enumerate_candidates

        gov = government_for_id(gov_id)
        state_abbr = gov.state if gov else (state or None)
        _ledger.upsert_tenant(netloc, platform)
        _ledger.set_tenant_gov_id(netloc, gov_id, state_abbr=state_abbr)
        await asyncio.wait_for(
            enumerate_candidates(
                _ledger, platforms=[platform], tenant=netloc, mode="thorough"
            ),
            timeout=45,
        )
        cur = _ledger.conn.execute(
            "SELECT url_normalized FROM candidates WHERE tenant_netloc = ? "
            "AND status = 'new' ORDER BY date DESC LIMIT ?",
            (netloc, limit),
        )
        urls = [row["url_normalized"] for row in cur.fetchall()]
        _ledger.conn.commit()
        return urls, ""
    except Exception as e:  # noqa: BLE001
        return [], f"discovery enumerate failed: {type(e).__name__}: {e}"


# --- tier-3 pending sink (Ryan's "probe before queue" gate) --------------

_TIER3_PENDING_FIELDS = [
    "gov_id",
    "platform",
    "meeting_url",
    "video_url",
    "source_url",
    "jurisdiction",
    "pin_row",
]
_tier3_pending_seen: Optional[set] = None


def _tier3_pending_already_seen() -> set:
    global _tier3_pending_seen
    if _tier3_pending_seen is None:
        seen = set()
        if TIER3_PENDING_CSV.exists():
            with TIER3_PENDING_CSV.open(newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    seen.add(r.get("meeting_url", ""))
        _tier3_pending_seen = seen
    return _tier3_pending_seen


def tier3_pending_handler(
    *, gov_id, unit_name, platform, final_seed, hit_url, title, date, result
) -> None:
    """Same `pin_row` convention as WO-147's sibling handler in
    scripts/wo147_access_ladder_sweep.py (`host|match|gov_id|strength|
    source|evidence`, applied later by whichever finish step accepts
    this candidate): a shared-host (YouTube/Vimeo/TelVue/Cablecast) pin
    is precomputed here but not written to tenant_overrides.csv until
    the probe accepts the video -- wo134_confirmed_hits_ingest.py's own
    maybe_write_tenant_override() no longer fires for a TIER3_HANDLER-
    intercepted candidate (see that function's call site), on purpose:
    pinning a video the probe later rejects as dead/too-short would be
    a wasted (if harmless) pin."""
    if final_seed in _tier3_pending_already_seen():
        return
    pin_row = ""
    if platform in wo134.SHARED_HOST_PLATFORMS:
        host = wo134._tenant_override_host(platform, result, final_seed)
        match = wo134._tenant_override_match(platform, result, final_seed)
        if host and match:
            pin_row = (
                f"{host}|{match}|{gov_id}|fallback|wo149_county_ladder_sweep|"
                f"{unit_name} -- WO-149 tier-3 pending, gov_id={gov_id}"
            )
    is_new = not TIER3_PENDING_CSV.exists()
    with TIER3_PENDING_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_TIER3_PENDING_FIELDS, lineterminator="\n")
        if is_new:
            w.writeheader()
        w.writerow(
            {
                "gov_id": gov_id,
                "platform": platform,
                "meeting_url": final_seed,
                "video_url": result.video_url or final_seed,
                "source_url": hit_url,
                "pin_row": pin_row,
                "jurisdiction": result.jurisdiction or "",
            }
        )
    _tier3_pending_already_seen().add(final_seed)


wo134.TIER3_HANDLER = tier3_pending_handler


# --- jurisdiction force-and-verify hook (the wrong-domain-mapping trap) --

# County name -> plausible state-name/abbreviation tokens the adapter's
# OWN jurisdiction guess is allowed to carry. If the adapter's guess
# names a state that flatly conflicts with the expected one, this is the
# real, documented trap (Charleston County SC / Charleston WV): reject
# the hit rather than force-overwriting silently.
_STATE_ABBRS = {
    "AL",
    "AK",
    "AZ",
    "AR",
    "CA",
    "CO",
    "CT",
    "DE",
    "FL",
    "GA",
    "HI",
    "ID",
    "IL",
    "IN",
    "IA",
    "KS",
    "KY",
    "LA",
    "ME",
    "MD",
    "MA",
    "MI",
    "MN",
    "MS",
    "MO",
    "MT",
    "NE",
    "NV",
    "NH",
    "NJ",
    "NM",
    "NY",
    "NC",
    "ND",
    "OH",
    "OK",
    "OR",
    "PA",
    "RI",
    "SC",
    "SD",
    "TN",
    "TX",
    "UT",
    "VT",
    "VA",
    "WA",
    "WV",
    "WI",
    "WY",
}


def jurisdiction_check_hook(
    result, gov_id: str, unit_name: str, platform: str, final_seed: str
) -> Tuple[bool, str]:
    expected_state = ""
    gov = government_for_id(gov_id)
    if gov and gov.state:
        expected_state = gov.state.strip().upper()

    guess = (result.jurisdiction or "").strip()
    if guess and expected_state:
        # Find any 2-letter state abbreviation token in the guess (e.g.
        # "Charleston, WV" or "Charleston WV Recreation Commission") and
        # check it against the expected state. A guess with no such
        # token (a bare city/county name, or one already carrying the
        # expected state) is not a conflict.
        tokens = re.findall(r"\b([A-Z]{2})\b", guess.upper())
        found_states = [t for t in tokens if t in _STATE_ABBRS]
        if found_states and expected_state not in found_states:
            return False, (
                f"wrong-domain-mapping: adapter jurisdiction guess {guess!r} "
                f"names {found_states[0]}, expected {expected_state} "
                f"(gov_id={gov_id}, seed={final_seed})"
            )

    # Compatible (or no signal either way) -- force the exact registry
    # name, wo130_county_ingest.py's pattern, so gov_id resolves
    # server-side to THIS county rather than drifting to rtr:unknown or a
    # same-named place.
    result.jurisdiction = unit_name
    return True, ""


wo134.JURISDICTION_CHECK_HOOK = jurisdiction_check_hook


# --- report -----------------------------------------------------------

_REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "population",
    "prior_reason",
    "start_url",
    "host",
    "corrected_domain",
    "access_mode",
    "rung_answered",
    "platform_found",
    "hit_url",
    "netloc",
    "outcome",
    "reject_reason",
    "reject_class",
    "candidates_listed",
    "candidates_tried",
    "meeting_url",
    "video_url",
    "tier",
    "page_url",
    "waf_family",
    "note",
]


def _report_writer():
    is_new = not REPORT_CSV.exists()
    f = REPORT_CSV.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=_REPORT_FIELDS, lineterminator="\n")
    if is_new:
        w.writeheader()
        f.flush()
    return f, w


def _already_done_gov_ids() -> set:
    if not REPORT_CSV.exists():
        return set()
    with REPORT_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f)}


_discovery_seeds_written: Optional[set] = None


def write_discovery_seed(
    netloc: str, platform: str, gov_id: str, access_mode: str
) -> None:
    global _discovery_seeds_written
    if _discovery_seeds_written is None:
        seen = set()
        if DISCOVERY_SEEDS_CSV.exists():
            with DISCOVERY_SEEDS_CSV.open(newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    seen.add(r.get("netloc", ""))
        _discovery_seeds_written = seen
    if netloc in _discovery_seeds_written:
        return
    is_new = not DISCOVERY_SEEDS_CSV.exists()
    with DISCOVERY_SEEDS_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["netloc", "platform", "gov_id", "access_mode"],
            lineterminator="\n",
        )
        if is_new:
            w.writeheader()
        w.writerow(
            {
                "netloc": netloc,
                "platform": platform,
                "gov_id": gov_id,
                "access_mode": access_mode,
            }
        )
    _discovery_seeds_written.add(netloc)


_host_access_modes_written: Optional[set] = None


def write_host_access_mode(host: str, access_mode: str, waf_family: str) -> None:
    global _host_access_modes_written
    if _host_access_modes_written is None:
        seen = set()
        if HOST_ACCESS_MODES_CSV.exists():
            with HOST_ACCESS_MODES_CSV.open(newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    seen.add(r.get("host", ""))
        _host_access_modes_written = seen
    if not host or host in _host_access_modes_written:
        return
    is_new = not HOST_ACCESS_MODES_CSV.exists()
    with HOST_ACCESS_MODES_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["host", "access_mode", "waf_family"], lineterminator="\n"
        )
        if is_new:
            w.writeheader()
        w.writerow({"host": host, "access_mode": access_mode, "waf_family": waf_family})
    _host_access_modes_written.add(host)


_CONTENT_TAXONOMY = [
    ("no adapter in this repo", "unsupported-platform-no-adapter"),
    ("not registered in get_finder()", "unsupported-platform-no-adapter"),
    ("ambiguous: no clean recent candidate", "off-mission"),
    ("title looks like a non-meeting video", "off-mission"),
    ("no candidates", "no-meetings-found"),
    ("no past CivicClerk events with real media found", "no-meetings-found"),
    ("no resolvable event", "no-meetings-found"),
    ("no video-bearing rows found on this AgendaCenter page", "no-video-found"),
    ("resolved but no transcript/agenda/video", "no-video-found"),
    ("no reachable AgendaCenter page found", "no-platform-link-found"),
    ("link found on hit_source_url", "no-platform-link-found"),
    ("no hit_source_urls on this row", "no-platform-link-found"),
    ("none had video", "no-video-found"),
    ("none actually resolved a video", "no-video-found"),
    ("none looked like a real meeting", "off-mission"),
    ("no video(s) listed", "no-meetings-found"),
    ("granicus listing, no candidates", "no-meetings-found"),
    ("no domain to guess a ViewPublisher.php listing", "no-platform-link-found"),
    ("no populated ViewPublisher.php", "no-platform-link-found"),
    ("ViewPublisher.php listing unreachable", "no-platform-link-found"),
    ("wrong-domain-mapping", "wrong-domain-mapping"),
]


def classify_skip_reason(reason: str) -> str:
    for substring, value in _CONTENT_TAXONOMY:
        if substring in reason:
            return value
    return "no-platform-link-found"


# --- main driver --------------------------------------------------------


async def process_candidate(
    session: aiohttp.ClientSession, row: dict, covered_gov_ids: set, writer
) -> str:
    """Returns 'ok' or 'error' (for the consecutive-error breaker)."""
    gov_id = row["gov_id"]
    name = row["name"]
    state = row["state"]
    population = row["population"]
    domain = row["domain"]
    known_platform_raw = row["known_platform"]
    hub_url = row["hub_url"]
    prior_reason = row["prior_reason"] or row["reject_reason"]
    start_url = (
        row.get("research_calendar_url") or row.get("research_meeting_url") or ""
    )
    if not start_url:
        start_url = hub_url or domain

    base_report = dict(
        gov_id=gov_id,
        name=name,
        state=state,
        population=population,
        prior_reason=prior_reason,
        start_url=start_url,
        host="",
        corrected_domain="",
        access_mode="",
        rung_answered="",
        platform_found="",
        hit_url="",
        netloc="",
        outcome="",
        reject_reason="",
        reject_class="",
        candidates_listed=0,
        candidates_tried=0,
        meeting_url="",
        video_url="",
        tier="",
        page_url="",
        waf_family="",
        note="",
    )

    if gov_id in covered_gov_ids:
        writer.writerow({**base_report, "outcome": "already_covered"})
        return "ok"

    base_report["host"] = urlparse(normalize_home_url(start_url)).netloc

    ladder = await run_access_ladder(session, name, state, domain, start_url)
    base_report["access_mode"] = ladder.access_mode
    base_report["rung_answered"] = ladder.rung_answered
    base_report["waf_family"] = ladder.waf_family
    base_report["corrected_domain"] = ladder.corrected_domain
    if ladder.note:
        base_report["note"] = ladder.note
    write_host_access_mode(base_report["host"], ladder.access_mode, ladder.waf_family)

    if ladder.access_mode == "challenge":
        writer.writerow(
            {
                **base_report,
                "outcome": "blocked",
                "reject_reason": "cloudflare-challenge-blocked",
                "reject_class": "access",
            }
        )
        return "ok"

    if ladder.access_mode in ("dead", "timeout"):
        reject_reason = (
            "timeout" if ladder.access_mode == "timeout" else "dns-unresolvable"
        )
        writer.writerow(
            {
                **base_report,
                "outcome": "blocked",
                "reject_reason": reject_reason,
                "reject_class": "access",
            }
        )
        return "ok"

    if ladder.access_mode == "blocked-plain-http":
        writer.writerow(
            {
                **base_report,
                "outcome": "blocked",
                "reject_reason": "blocked-plain-http",
                "reject_class": "access",
            }
        )
        return "ok"

    if ladder.access_mode == "blocked-browser-headers":
        writer.writerow(
            {
                **base_report,
                "outcome": "blocked",
                "reject_reason": "blocked-browser-headers",
                "reject_class": "access",
            }
        )
        return "ok"

    if ladder.access_mode == "blocked-headless":
        writer.writerow(
            {
                **base_report,
                "outcome": "blocked",
                "reject_reason": "blocked-headless",
                "reject_class": "access",
            }
        )
        return "ok"

    hits: List[Tuple[str, str]] = []
    if ladder.platform and ladder.hit_url:
        hits.append((ladder.platform, ladder.hit_url))
        base_report["hit_url"] = ladder.hit_url

    # Real, confirmed-live bug caught in this WO's own 30-row pilot
    # (Volusia County FL, 2026-09-10): 93 of 1,424 rows carry a
    # `research_meeting_url` that is ALREADY a specific platform seed
    # (a direct YouTube watch URL, not a page to crawl for one). Pairing
    # the row's `known_platform` with `hub_url`/the homepage instead --
    # as if the meeting URL didn't exist -- sent locate_platform_url()
    # hunting for a youtube link on an agenda PAGE that has none,
    # producing a false `no-platform-link-found` for a county whose real
    # video was one column over the whole time. Detect this case first
    # and use the real URL as the seed.
    research_meeting_url = (row.get("research_meeting_url") or "").strip()
    research_calendar_url = (row.get("research_calendar_url") or "").strip()
    for candidate_url in (research_meeting_url, research_calendar_url):
        if not candidate_url:
            continue
        detected = detect_platform(candidate_url)
        if (
            detected
            and detected != "unknown"
            and detected not in wo134.UNSUPPORTED_PLATFORMS
            and not any(p == detected and u == candidate_url for p, u in hits)
        ):
            if detected == "youtube":
                candidate_url = canonicalize_youtube_url(candidate_url)
            hits.append((detected, candidate_url))

    known_platform = normalize_known_platform(known_platform_raw)
    if known_platform and known_platform not in wo134.UNSUPPORTED_PLATFORMS:
        if not any(p == known_platform for p, _ in hits):
            seed = hub_url or ladder.home_url or normalize_home_url(start_url)
            hits.append((known_platform, seed))

    platform_found = ladder.platform or known_platform or ""
    base_report["platform_found"] = platform_found

    if not hits:
        writer.writerow(
            {
                **base_report,
                "outcome": "no_platform_link_found",
                "reject_reason": "no-platform-link-found",
                "reject_class": "content",
            }
        )
        return "ok"

    primary_platform, primary_url = hits[0]
    netloc = urlparse(primary_url).netloc
    base_report["netloc"] = netloc

    discovery_note = ""
    if netloc and primary_platform in DISCOVERY_ENUMERABLE:
        disc_urls, discovery_note = await discovery_candidate_urls(
            netloc, primary_platform, gov_id, state
        )
        if disc_urls:
            write_discovery_seed(netloc, primary_platform, gov_id, ladder.access_mode)
            for u in disc_urls:
                hits.insert(0, (primary_platform, u))
    if netloc:
        write_discovery_seed(netloc, primary_platform, gov_id, ladder.access_mode)

    hit_source_urls = ";".join(f"{p}={u}" for p, u in hits[:6])
    base_report["candidates_listed"] = len(hits[:6])
    base_report["candidates_tried"] = len(hits[:6])
    if discovery_note:
        base_report["note"] = (base_report["note"] + "; " + discovery_note).strip("; ")

    synthetic_row = {
        "gov_id": gov_id,
        "unit_name": f"{name}, {state}",
        "homepage": ladder.home_url or normalize_home_url(start_url),
        "hop2_urls": "",
        "hit_source_urls": hit_source_urls,
    }

    try:
        result = await wo134.process_row(
            session, synthetic_row, covered_gov_ids, "wo149_county_ladder_sweep"
        )
    except Exception as e:  # noqa: BLE001
        writer.writerow(
            {
                **base_report,
                "outcome": "error",
                "note": f"process_row raised: {type(e).__name__}: {e}",
            }
        )
        return "error"

    outcome = result.outcome
    if outcome == "already_covered":
        writer.writerow({**base_report, "outcome": "already_covered"})
        return "ok"

    if outcome == "ingested_tier1_2":
        tier = "tier2" if result.platform == "youtube" else "tier1"
        writer.writerow(
            {
                **base_report,
                "outcome": "ingested_tier1_2",
                "meeting_url": result.seed_url,
                "tier": tier,
                "page_url": result.page_url,
                "note": (base_report["note"] + "; " + result.reason).strip("; "),
            }
        )
        return "ok"

    if outcome == "queued_tier3_pending":
        writer.writerow(
            {
                **base_report,
                "outcome": "queued_tier3_pending",
                "meeting_url": result.seed_url,
                "tier": "tier3_pending",
                "note": (base_report["note"] + "; " + result.reason).strip("; "),
            }
        )
        return "ok"

    if outcome == "queued_tier3":
        writer.writerow(
            {
                **base_report,
                "outcome": "queued_tier3",
                "meeting_url": result.seed_url,
                "tier": "tier3",
                "note": (base_report["note"] + "; " + result.reason).strip("; "),
            }
        )
        return "ok"

    if outcome == "no_video_found":
        writer.writerow(
            {
                **base_report,
                "outcome": "no_video_found",
                "reject_reason": "no-video-found",
                "reject_class": "content",
                "meeting_url": result.seed_url,
                "note": (base_report["note"] + "; " + result.reason).strip("; "),
            }
        )
        return "ok"

    if outcome == "error":
        writer.writerow(
            {
                **base_report,
                "outcome": "error",
                "note": (base_report["note"] + "; " + result.reason).strip("; "),
            }
        )
        return "error"

    reject_reason = classify_skip_reason(result.reason)
    outcome_label = (
        "wrong_domain_mapping"
        if reject_reason == "wrong-domain-mapping"
        else "no_platform_link_found"
        if reject_reason == "no-platform-link-found"
        else "no_video_found"
        if reject_reason == "no-video-found"
        else "no_meetings_found"
        if reject_reason == "no-meetings-found"
        else "blocked"
        if reject_reason == "unsupported-platform-no-adapter"
        else "skipped"
    )
    writer.writerow(
        {
            **base_report,
            "outcome": outcome_label,
            "reject_reason": reject_reason,
            "reject_class": "content",
            "note": (base_report["note"] + "; " + result.reason).strip("; "),
        }
    )
    return "ok"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--start-after", type=str, default=None)
    parser.add_argument("--inventory-csv", type=Path, default=DEFAULT_INVENTORY_CSV)
    args = parser.parse_args()

    if not wo134._base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (check .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    register_all_finders()

    covered_gov_ids = wo134._load_covered_gov_ids(args.inventory_csv)
    print(f"{len(covered_gov_ids)} gov_ids already have an archived page.")

    with CANDIDATES_CSV.open(newline="", encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))
    print(f"{len(all_rows)} candidate rows in {CANDIDATES_CSV.name}")

    already_done = _already_done_gov_ids()
    print(
        f"{len(already_done)} gov_ids already in {REPORT_CSV.name} -- skipping those."
    )

    skip_until_seen = args.start_after is not None
    to_process = []
    for row in all_rows:
        if row["gov_id"] in already_done:
            continue
        if skip_until_seen:
            if row["gov_id"] == args.start_after:
                skip_until_seen = False
            continue
        to_process.append(row)
    if args.limit:
        to_process = to_process[: args.limit]

    print(f"Processing {len(to_process)} row(s)...\n")

    report_f, writer = _report_writer()
    tally: Dict[str, int] = {}
    consecutive_errors = 0
    try:
        async with aiohttp.ClientSession() as session:
            for i, row in enumerate(to_process):
                t0 = time.monotonic()
                status = await process_candidate(session, row, covered_gov_ids, writer)
                report_f.flush()
                elapsed = time.monotonic() - t0
                print(
                    f"[{i + 1}/{len(to_process)}] {row['name']}, {row['state']} "
                    f"-- {elapsed:.1f}s -- status={status}"
                )
                tally[status] = tally.get(status, 0) + 1
                if status == "error":
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0
                if consecutive_errors >= 6:
                    print(
                        f"\nABORTING: {consecutive_errors} consecutive real errors. "
                        "Re-run to resume (already-reported rows are skipped).",
                        file=sys.stderr,
                    )
                    break
                if i < len(to_process) - 1:
                    await asyncio.sleep(GOV_DELAY_SECONDS)
    finally:
        report_f.close()
        if _ledger is not None:
            _ledger.close()

    print("\n--- Tally (this run) ---")
    for k, v in sorted(tally.items()):
        print(f"{k:10} {v}")
    print(f"\nFull report: {REPORT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
