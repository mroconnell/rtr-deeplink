"""WO-265 (2026-09-11): overnight DETECTION-ONLY sweep over US school
districts -- `~/Documents/rtr-business/research/wo_school_district_sweep_
input.csv`, 10,347 `us:sd:*` districts with a domain, no Archive page, and
no known platform (`prior_reject_reason` is `no-platform-signature`,
`blocked-plain-http`, or `(untested)`).

This script does NOT ingest, queue, pin, or write the research file. It
only detects and records candidates for a separate morning close-out
session to hand-check and act on -- see this WO's close-out brief
(written after the run starts) for that half.

Per district, in order:

1. Full-ladder front-page fetch: plain honest HTTP -> browser headers
   only after a 403 or a dropped connection (never after a 404) ->
   headless only when the page loads fine but shows no board/meetings
   link -> stop at a human-verification gate (`cloudflare-challenge-
   blocked`), never solved or waited out. Scans the fetched page for a
   platform link `app.platforms.base.detect_platform()` recognizes, and
   separately for a BoardDocs/Simbli link (neither is a platform
   `detect_platform()` knows about).
2. One hop into a "Board of Education"/"School Board"/"Board Meetings"/
   "Agendas & Minutes"-hinted link, same header mode that reached the
   front page. Scans the resulting page the same way, plus for
   per-meeting video links (YouTube/Vimeo/direct file/Drive/Dropbox/
   BoxCast/Cablecast), recorded as CANDIDATES only -- never resolved or
   verified.
3. School-board vendor path guesses when nothing was found in 1-2:
   BoardDocs (`go.boarddocs.com/<st>/<label>/Board.nsf/Public`),
   CivicClerk (`<label>.portal.civicclerk.com`), Granicus
   (`<label>.granicus.com/ViewPublisher.php?view_id=1..3`), IQM2
   (`<label>.iqm2.com/Citizens/Calendar.aspx`), eScribe
   (`pub-<label>.escribemeetings.com`), CivicPlus (same-domain
   `/AgendaCenter`). Simbli/eBoard and Diligent Community are NOT
   guessed -- Simbli's ids aren't guessable (only recorded when a real
   site links it) and Diligent Community's tenant path has no guessable
   shape either; both are still caught by the link scan in steps 1-2.
   Labels tried: the domain's own second-level label, then that label
   with `isd`/`sd`/`schools`/`k12`/`usd`/`cusd` appended -- stopping at
   the first guess that resolves to a real-looking tenant for a given
   vendor.
4. Same ladder on `alternate_domains`/`alternate_urls` when the primary
   domain produced nothing at all (dead/blocked/challenge/no evidence) --
   none of today's input rows carry one, but the code path is kept for
   when they do.

Politeness (binding, CLAUDE.md + this WO's brief): fully sequential (one
government worked at a time, so "one request in flight per host" holds
automatically), >=2s between requests to the SAME host, >=1.5s between
districts. `go.boarddocs.com` and `simbli.eboardsolutions.com` are
treated as ONE host each for rate purposes (thousands of districts share
each tenant) via `host_alias()` -- every guess against either goes
through the same rate-limiter bucket regardless of which district it's
for. A cool-off (60s) kicks in after 6 consecutive access-shaped
failures (dead/blocked/challenge -- not merely "no evidence found") on
any one host alias, vendor hosts included. Never solve or wait out a
challenge -- `is_challenge()` is checked after every fetch and a
challenge is recorded and moved past immediately.

WO-265's brief mentions "WO-260's rate" for the BoardDocs/Simbli
cool-off; no WO-260 exists anywhere in this repo's history as of
2026-09-11 (checked via `git log --all --grep`), so this script uses the
same >=2s per-host / 6-failure/60s cool-off already documented above and
used throughout this repo's sweeps (`scripts/wo147_access_ladder_sweep.
py`'s `HOST_DELAY_SECONDS`) -- flagged here, and in this WO's own final
report, rather than guessed at silently.

Evidence (binding): every row that finds something records the exact URL
that answered (`answering_url`/`platform_evidence_url`/`vendor_tenant_
url`) and the marker matched (`evidence_marker`), per CLAUDE.md's "don't
claim a caption/data path works without a positive example" bullet and
this project's "reports report, never guess" rule.

A sibling agent (WO-264) is building the equivalent sweep for
municipalities at `scripts/wo264_overnight_sweep.py`. As of this
writing that PR has not merged (`git log origin/main | grep WO-264`
comes back empty), so this script is built from the same underlying
sources WO-264 was pointed at (`scripts/wo174_pipeline.py`'s ladder/probe
shape, `scripts/hub_sweep_wo126.py`'s listing-locate pattern, the
WO-187 headless helper, `detect_platform()`), not by importing WO-264's
file. The header/challenge/fetch/find-platform-link primitives below are
copied (not imported) from `scripts/wo147_access_ladder_sweep.py`,
following that module's own precedent (its "copied verbatim ... since
it's being run by other active sweeps right now" comments) for reusing
a shared primitive without adding an import-time dependency on a large,
heavier module (`wo147_access_ladder_sweep.py` itself imports
`wo134_confirmed_hits_ingest.py`, which this detection-only script has
no reason to pull in). The OUTPUT REPORT SHAPE is deliberately written to
match what WO-264's report is expected to look like (gov_id, name,
state, population, domain, access_mode, answering_url, platform_found,
platform_evidence_url, listing_url, video_candidate_urls, channel_lead_
url, vendor_tenant_url, outcome, reject_reason, evidence_marker, note)
plus the two columns this WO's brief calls for beyond that shape
(`channel_lead_url`, `vendor_tenant_url`) -- so one morning close-out
pattern can read either report.

Resumable: a `gov_id` already present in the report CSV is skipped on a
re-run. Progress line every 250 rows.

Usage:
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo265_unused.db" \\
    /Users/mroconnell/Documents/rtr-deeplink/.venv/bin/python3 -u \\
        scripts/wo265_school_district_sweep.py \\
        --input ~/Documents/rtr-business/research/wo_school_district_sweep_input.csv \\
        --report ~/Documents/rtr-business/research/wo265_report.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import re
import sys
import time
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.platforms.base import detect_platform  # noqa: E402

DEFAULT_INPUT_CSV = (
    Path.home()
    / "Documents"
    / "rtr-business"
    / "research"
    / "wo_school_district_sweep_input.csv"
)
DEFAULT_REPORT_CSV = (
    Path.home() / "Documents" / "rtr-business" / "research" / "wo265_report.csv"
)

GOV_DELAY_SECONDS = 1.5
HOST_DELAY_SECONDS = 2.0
COOLOFF_THRESHOLD = 6
COOLOFF_SECONDS = 60.0
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=8)
PROGRESS_EVERY = 250
CONSECUTIVE_EXCEPTION_LIMIT = 20

# --- copied from scripts/wo147_access_ladder_sweep.py (WO-147, WO-141's
# own wo141_access_ladder_pilot.py originally) -- see this module's own
# docstring for why this is a copy, not an import. -------------------
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


def is_challenge(html_text: str) -> bool:
    lower = html_text.lower()
    return any(marker in lower for marker in CHALLENGE_MARKERS)


def normalize_home_url(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if not re.match(r"^https?://", raw, re.I):
        raw = "https://" + raw
    return raw


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
    error_kind: str = ""  # dns | timeout | connection | ""


async def fetch_one(
    session: aiohttp.ClientSession, url: str, headers: dict
) -> FetchResult:
    try:
        async with session.get(
            url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True
        ) as resp:
            html_text = await resp.text(errors="replace")
            return FetchResult(
                status=resp.status, final_url=str(resp.url), html=html_text
            )
    except Exception as e:  # noqa: BLE001 -- record and classify, never raise
        return FetchResult(error=str(e)[:200], error_kind=classify_exception(e))


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


_TAGS = ("a", "iframe", "video", "source")
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


def _safe_soup(html_text: str) -> Optional[BeautifulSoup]:
    try:
        return BeautifulSoup(html_text, "html.parser")
    except Exception:  # noqa: BLE001 -- a parser failure is never fatal here
        return None


def _is_vendor_marketing_apex(netloc: str) -> bool:
    n = netloc.lower()
    if n.startswith("www."):
        n = n[4:]
    return n in _VENDOR_MARKETING_APEX


# Same marker list as `wo147_access_ladder_sweep.is_bare_youtube_channel_
# hit()` (copied, not imported -- see this module's docstring). A bare
# youtube.com/vimeo.com link with none of these markers is a CHANNEL
# link (`youtube.com/@Handle`, `vimeo.com/someuser`), not a specific
# video/playlist -- this WO's brief keeps `platform-found` and
# `channel-lead` as two different outcomes, so `find_platform_link()`
# must not claim a bare channel link as a platform hit; real bug caught
# live in this script's own smoke test (Albertville City School District
# AL and Hoover City School District AL both front-paged straight to a
# bare `youtube.com/@handle` link and were misclassified `platform-found`
# before this guard existed).
_YT_CHANNEL_SHAPE_MARKERS = ("/watch", "youtu.be/", "list=", "/embed/")
_VIMEO_VIDEO_ID_RE = re.compile(r"vimeo\.com/\d+", re.I)


def _is_bare_channel_link(platform: str, url: str) -> bool:
    low = url.lower()
    if platform == "youtube":
        return not any(m in low for m in _YT_CHANNEL_SHAPE_MARKERS)
    if platform == "vimeo":
        return not _VIMEO_VIDEO_ID_RE.search(low)
    return False


def find_platform_link(html_text: str, final_url: str) -> Optional[Tuple[str, str]]:
    """Same shape as `wo147_access_ladder_sweep.find_platform_link()`:
    scans anchors/iframes/video/source tags for a URL `detect_platform()`
    recognizes, plus the same-domain CivicPlus AgendaCenter special case.
    Skips a bare YouTube/Vimeo CHANNEL link (see `_is_bare_channel_link()`
    above) so it falls through to `find_channel_leads()` instead."""
    if "agendacenter" in html_text.lower():
        soup = _safe_soup(html_text)
        if soup is not None:
            for a in soup.find_all("a", href=True):
                if "agendacenter" in a["href"].lower():
                    return "civicplus", urljoin(final_url, a["href"])
        origin = urlparse(final_url)
        return "civicplus", f"{origin.scheme}://{origin.netloc}/AgendaCenter"

    soup = _safe_soup(html_text)
    if soup is None:
        return None
    page_no_frag = urlparse(final_url)._replace(fragment="").geturl()
    for tag in soup.find_all(_TAGS):
        values = []
        href_or_src = tag.get("href") or tag.get("src")
        if href_or_src:
            values.append(href_or_src.strip())
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
                and not _is_bare_channel_link(platform, candidate)
            ):
                return platform, candidate
    return None


def find_boarddocs_or_simbli_link(
    html_text: str, final_url: str
) -> Optional[Tuple[str, str]]:
    """`detect_platform()` does not know BoardDocs or Simbli/eBoard --
    neither has an adapter in this repo (see `docs/COVERAGE_HANDOVER.md`
    and `~/Documents/rtr-discovery/SCHOOL_DISTRICT_ENUMERATION_HANDOVER.
    md`'s BoardDocs note) -- so they need their own small link scan."""
    soup = _safe_soup(html_text)
    if soup is None:
        return None
    for tag in soup.find_all(("a", "iframe")):
        href_or_src = tag.get("href") or tag.get("src")
        if not href_or_src:
            continue
        full = urljoin(final_url, href_or_src)
        low = full.lower()
        if "boarddocs.com" in low:
            return "boarddocs", full
        if "eboardsolutions.com" in low:
            return "simbli", full
    return None


# --- school-district-specific hop/candidate scanning ---------------------

SCHOOL_HOP_WORDS = (
    "board of education",
    "school board",
    "board meeting",
    "board meetings",
    "board of trustees",
    "agendas & minutes",
    "agendas and minutes",
    "agenda",
    "minutes",
    "board docs",
)


def find_school_hop_links(html_text: str, final_url: str, limit: int = 5) -> List[str]:
    """One-hop candidate links toward a district's board/meetings page.
    Deliberately simpler than `wo147_access_ladder_sweep.find_hop_links()`
    -- that function's scoring is tuned for general-municipal calendar
    pages; the school-specific word list above is what this population
    actually needs. Kept in document order (no ranking) since this WO's
    brief calls for exactly ONE hop, not a ranked multi-candidate chase."""
    soup = _safe_soup(html_text)
    if soup is None:
        return []
    out: List[str] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        text = (a.get_text() or "").strip().lower()
        href = a["href"]
        hay = f"{text} {href}".lower()
        if not any(w in hay for w in SCHOOL_HOP_WORDS):
            continue
        full = urljoin(final_url, href)
        if urlparse(full).scheme not in ("http", "https") or full in seen:
            continue
        seen.add(full)
        out.append(full)
        if len(out) >= limit:
            break
    return out


_VIDEO_PATTERNS: Tuple[Tuple[str, re.Pattern], ...] = (
    ("youtube", re.compile(r"(youtube\.com/(watch\?v=|embed/)|youtu\.be/)", re.I)),
    ("vimeo", re.compile(r"vimeo\.com/\d+", re.I)),
    ("direct_file", re.compile(r"\.(mp4|mov|m3u8|webm)(\?|$)", re.I)),
    ("drive", re.compile(r"drive\.google\.com/(file/d/|open\?id=)", re.I)),
    ("dropbox", re.compile(r"dropbox\.com/(s/|.*\.(mp4|mov|m3u8|webm))", re.I)),
    ("boxcast", re.compile(r"boxcast\.(tv|com)", re.I)),
    ("cablecast", re.compile(r"cablecast\.(tv|com)|cablecastapi", re.I)),
)

_CHANNEL_PATTERN = re.compile(
    r"(youtube\.com/(channel/|c/|@|user/)|vimeo\.com/(user|channels)/)", re.I
)


def find_video_candidates(
    html_text: str, final_url: str, limit: int = 5
) -> List[Tuple[str, str]]:
    """Per-meeting video links on a listing page -- CANDIDATES only, never
    verified or resolved by this script."""
    soup = _safe_soup(html_text)
    if soup is None:
        return []
    out: List[Tuple[str, str]] = []
    seen = set()
    for tag in soup.find_all(_TAGS):
        href_or_src = tag.get("href") or tag.get("src")
        if not href_or_src:
            continue
        full = urljoin(final_url, href_or_src)
        if full in seen:
            continue
        for kind, pat in _VIDEO_PATTERNS:
            if pat.search(full):
                seen.add(full)
                out.append((kind, full))
                break
        if len(out) >= limit:
            break
    return out


def find_channel_leads(html_text: str, final_url: str, limit: int = 3) -> List[str]:
    """A district's own YouTube/Vimeo CHANNEL link (not a single video) --
    recorded as `channel_lead_url` per this WO's brief, against the
    district's own `us:sd:` id, never a city row."""
    soup = _safe_soup(html_text)
    if soup is None:
        return []
    out: List[str] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        full = urljoin(final_url, a["href"])
        if full in seen:
            continue
        if _CHANNEL_PATTERN.search(full):
            seen.add(full)
            out.append(full)
        if len(out) >= limit:
            break
    return out


_BAD_TENANT_PHRASES = (
    "page not found",
    "404",
    "does not exist",
    "no such organization",
    "cannot be found",
    "invalid organization",
    "access denied",
    "no site found",
    "no such customer",
)


def looks_like_real_tenant(html_text: Optional[str], min_len: int = 400) -> bool:
    """Cheap, conservative check that a guessed vendor URL landed on a
    real per-tenant page rather than a generic "no such customer"/error
    page many of these vendors return with a 200 status. Not a substitute
    for a human hand-read -- see this WO's close-out brief."""
    if not html_text:
        return False
    text = re.sub(r"<[^>]+>", " ", html_text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) < min_len:
        return False
    low = text.lower()
    return not any(p in low for p in _BAD_TENANT_PHRASES)


# --- label guessing --------------------------------------------------

_LABEL_SUFFIXES = ("schools", "cusd", "usd", "isd", "k12", "csd", "psd", "sd")


def base_label(domain: str) -> str:
    host = (domain or "").strip().lower()
    host = re.sub(r"^www\.", "", host)
    label = host.split(".")[0] if host else ""
    for suf in _LABEL_SUFFIXES:
        if label.endswith(suf) and len(label) > len(suf) + 1:
            return label[: -len(suf)]
    return label


def label_variants(domain: str) -> List[str]:
    base = base_label(domain)
    if not base:
        return []
    forms = [
        base,
        f"{base}isd",
        f"{base}sd",
        f"{base}schools",
        f"{base}k12",
        f"{base}usd",
        f"{base}cusd",
    ]
    out: List[str] = []
    seen = set()
    for f in forms:
        if f and f not in seen:
            seen.add(f)
            out.append(f)
    return out


def boarddocs_guess_url(state_abbr: str, label: str) -> str:
    return f"https://go.boarddocs.com/{state_abbr.lower()}/{label}/Board.nsf/Public"


def civicclerk_guess_url(label: str) -> str:
    return f"https://{label}.portal.civicclerk.com"


def granicus_guess_url(label: str, view_id: int) -> str:
    return f"https://{label}.granicus.com/ViewPublisher.php?view_id={view_id}"


def iqm2_guess_url(label: str) -> str:
    return f"https://{label}.iqm2.com/Citizens/Calendar.aspx"


def escribe_guess_url(label: str) -> str:
    return f"https://pub-{label}.escribemeetings.com"


def civicplus_agendacenter_guess_url(domain: str) -> str:
    return f"https://{domain.strip().rstrip('/')}/AgendaCenter"


# --- state name -> abbreviation (for the BoardDocs guess) ----------------

_US_STATES_CSV = REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "us_states.csv"


def _load_state_abbrevs() -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not _US_STATES_CSV.exists():
        return out
    with _US_STATES_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or "").strip().lower()
            abbr = (row.get("state") or "").strip()
            if name and abbr:
                out[name] = abbr
    return out


STATE_ABBREVS = _load_state_abbrevs()


def state_abbr_for(state_value: str) -> str:
    s = (state_value or "").strip()
    if not s:
        return ""
    if len(s) == 2:
        return s.upper()
    return STATE_ABBREVS.get(s.lower(), "")


# --- discovery-handover confirmed-dead skip list -------------------------
#
# Named, specific findings from ~/Documents/rtr-discovery/SCHOOL_DISTRICT_
# ENUMERATION_HANDOVER.md (read-only sibling repo) -- confirmed dead or a
# confirmed false-positive tenant, not just "empty so far." Text names,
# not gov_ids (the handover doc predates gov_id-keyed CSVs), so matching
# is a case-insensitive substring-of-name + exact-state check -- approximate
# on purpose; a false skip here only means one district isn't re-probed
# tonight, never a wrong write, so the low precision this affords is an
# acceptable trade for staying inside the "detection only" scope. The
# handover's own unnamed 14-row CivicPlus-training-portal group isn't
# included here since those rows are identified only by a CSV this
# script doesn't have (`school_district_retry_no_host_v4_report.csv`),
# not by name in the prose doc itself.
SKIP_LIST: Tuple[Tuple[str, str], ...] = (
    ("mettawee", "Vermont"),
    ("taconic", "Vermont"),
    ("winhall", "Vermont"),
    ("bennington", "Vermont"),
    ("prince george", "Maryland"),
    ("santa cruz county office of education", "California"),
    ("putnam", "Connecticut"),
    ("worcester", "Massachusetts"),
    ("corpus christi", "Texas"),
    ("academy for academic excellence", "Texas"),
    ("yuma union", "Arizona"),
    ("wakefield", "Massachusetts"),
    ("chelmsford", "Massachusetts"),
    ("hernando", "Florida"),
)


def is_confirmed_dead(name: str, state: str) -> bool:
    name_l = (name or "").lower()
    state_l = (state or "").strip().lower()
    for substr, expected_state in SKIP_LIST:
        if substr in name_l and state_l == expected_state.lower():
            return True
    return False


# --- politeness / rate limiting -------------------------------------


def host_alias(netloc: str) -> str:
    n = (netloc or "").lower()
    if "boarddocs.com" in n:
        return "go.boarddocs.com"
    if "eboardsolutions.com" in n:
        return "simbli.eboardsolutions.com"
    return n


class RateLimiter:
    def __init__(self) -> None:
        self.last_call: Dict[str, float] = {}
        self.consecutive_failures: Dict[str, int] = {}

    async def wait(self, netloc: str) -> None:
        alias = host_alias(netloc)
        delay = HOST_DELAY_SECONDS
        if self.consecutive_failures.get(alias, 0) >= COOLOFF_THRESHOLD:
            delay = COOLOFF_SECONDS
            self.consecutive_failures[alias] = 0
        last = self.last_call.get(alias)
        if last is not None:
            remaining = delay - (time.monotonic() - last)
            if remaining > 0:
                await asyncio.sleep(remaining)
        self.last_call[alias] = time.monotonic()

    def record(self, netloc: str, access_ok: bool) -> None:
        alias = host_alias(netloc)
        if access_ok:
            self.consecutive_failures[alias] = 0
        else:
            self.consecutive_failures[alias] = (
                self.consecutive_failures.get(alias, 0) + 1
            )


async def polite_fetch(
    session: aiohttp.ClientSession, rl: RateLimiter, url: str, headers: dict
) -> Tuple[FetchResult, bool]:
    """Fetches `url` after respecting the rate limiter for its host
    (BoardDocs/Simbli aliased to one bucket each). Returns (result,
    access_ok) where access_ok is False for a dead/blocked/challenge
    response -- what feeds the cool-off counter."""
    netloc = urlparse(url).netloc
    await rl.wait(netloc)
    r = await fetch_one(session, url, headers)
    access_ok = r.html is not None and not (r.html and is_challenge(r.html))
    rl.record(netloc, access_ok)
    return r, access_ok


# --- per-district result row -----------------------------------------


@dataclass
class DistrictResult:
    gov_id: str
    name: str
    state: str
    population: str
    domain: str
    access_mode: str = ""
    answering_url: str = ""
    platform_found: str = ""
    platform_evidence_url: str = ""
    listing_url: str = ""
    video_candidate_urls: str = ""
    channel_lead_url: str = ""
    vendor_tenant_url: str = ""
    outcome: str = "nothing"
    reject_reason: str = ""
    evidence_marker: str = ""
    note: str = ""


REPORT_FIELDS = [f.name for f in fields(DistrictResult)]


def candidate_domains(row: Dict[str, str]) -> List[str]:
    """Primary `domain` first, then `alternate_domains` (";"-separated),
    then the host of each `alternate_urls` entry -- same shape as
    `scripts/coverage_alternates.candidate_domains()`, reimplemented
    narrowly here rather than imported so this detection-only script
    stays fully self-contained (see this module's docstring)."""
    out: List[str] = []
    seen = set()

    def add(raw: Optional[str]) -> None:
        v = (raw or "").strip()
        if not v:
            return
        host = urlparse(v if "://" in v else f"https://{v}").netloc or v
        host = host.lower()
        if host and host not in seen:
            seen.add(host)
            out.append(host)

    add(row.get("domain"))
    for d in (row.get("alternate_domains") or "").split(";"):
        add(d)
    for u in (row.get("alternate_urls") or "").split(";"):
        add(u)
    return out


async def try_one_domain(
    session: aiohttp.ClientSession, rl: RateLimiter, domain: str
) -> DistrictResult:
    """Runs steps 1-2 (front page + one hop) against a single domain.
    Returns a partially-filled DistrictResult (gov_id/name/etc left
    blank -- the caller fills those in)."""
    result = DistrictResult(gov_id="", name="", state="", population="", domain=domain)
    home_url = normalize_home_url(domain)
    if not home_url:
        result.outcome = "nothing"
        result.note = "no domain"
        return result

    r, access_ok = await polite_fetch(session, rl, home_url, HONEST_HEADERS)
    used_browser = False

    if r.error_kind == "dns":
        result.access_mode = "dead"
        result.reject_reason = "dns-unresolvable"
        result.outcome = "dead"
        return result

    if r.html is None:
        # dropped connection or timeout -- eligible for one browser-headers retry
        r2, access_ok = await polite_fetch(session, rl, home_url, BROWSER_HEADERS)
        if r2.html is None:
            result.access_mode = "blocked"
            result.reject_reason = (
                "timeout" if r.error_kind == "timeout" else "blocked-plain-http"
            )
            result.outcome = "blocked"
            return result
        r = r2
        used_browser = True

    if is_challenge(r.html):
        result.access_mode = "challenge"
        result.reject_reason = "cloudflare-challenge-blocked"
        result.outcome = "human-gate"
        result.answering_url = r.final_url
        return result

    if r.status == 403 and not used_browser:
        r3, access_ok = await polite_fetch(session, rl, home_url, BROWSER_HEADERS)
        if r3.html and is_challenge(r3.html):
            result.access_mode = "challenge"
            result.reject_reason = "cloudflare-challenge-blocked"
            result.outcome = "human-gate"
            result.answering_url = r3.final_url
            return result
        if r3.html is None:
            result.access_mode = "blocked"
            result.reject_reason = "blocked-plain-http"
            result.outcome = "blocked"
            return result
        r = r3
        used_browser = True

    result.access_mode = "browser-headers" if used_browser else "plain"
    result.answering_url = r.final_url
    headers_used = BROWSER_HEADERS if used_browser else HONEST_HEADERS

    hit = find_platform_link(r.html, r.final_url)
    if hit:
        result.platform_found, result.platform_evidence_url = hit
        result.evidence_marker = f"platform link on front page: {hit[1]}"
        result.outcome = "platform-found"
        return result

    bd = find_boarddocs_or_simbli_link(r.html, r.final_url)
    if bd:
        vendor, vendor_url = bd
        result.vendor_tenant_url = vendor_url
        result.platform_found = vendor
        result.platform_evidence_url = vendor_url
        result.evidence_marker = f"{vendor} link on front page: {vendor_url}"
        result.outcome = "platform-found"
        return result

    hop_links = find_school_hop_links(r.html, r.final_url)
    listing_html: Optional[str] = None
    listing_url_used: Optional[str] = None

    if hop_links:
        link = hop_links[0]
        hr, _ = await polite_fetch(session, rl, link, headers_used)
        if hr.html and is_challenge(hr.html):
            result.note = f"board-page hop hit a challenge at {link}, skipped"
        elif hr.html:
            listing_html = hr.html
            listing_url_used = hr.final_url
            result.listing_url = listing_url_used
            hit2 = find_platform_link(hr.html, hr.final_url)
            if hit2:
                result.platform_found, result.platform_evidence_url = hit2
                result.evidence_marker = f"platform link on board page: {hit2[1]}"
                result.outcome = "platform-found"
                return result
            bd2 = find_boarddocs_or_simbli_link(hr.html, hr.final_url)
            if bd2:
                vendor, vendor_url = bd2
                result.vendor_tenant_url = vendor_url
                result.platform_found = vendor
                result.platform_evidence_url = vendor_url
                result.evidence_marker = f"{vendor} link on board page: {vendor_url}"
                result.outcome = "platform-found"
                return result
    else:
        # a real page with no visible board/meetings link -- the
        # JS-rendered-navigation case headless recovers (this WO's step 1).
        hh, hurl, herr = await fetch_headless(r.final_url)
        await rl.wait(urlparse(hurl or r.final_url).netloc)
        if hh and is_challenge(hh):
            result.access_mode = "challenge"
            result.reject_reason = "cloudflare-challenge-blocked"
            result.outcome = "human-gate"
            result.answering_url = hurl
            return result
        if hh:
            result.access_mode = "headless"
            result.answering_url = hurl
            hit3 = find_platform_link(hh, hurl)
            if hit3:
                result.platform_found, result.platform_evidence_url = hit3
                result.evidence_marker = f"platform link via headless render: {hit3[1]}"
                result.outcome = "platform-found"
                return result
            bd3 = find_boarddocs_or_simbli_link(hh, hurl)
            if bd3:
                vendor, vendor_url = bd3
                result.vendor_tenant_url = vendor_url
                result.platform_found = vendor
                result.platform_evidence_url = vendor_url
                result.evidence_marker = (
                    f"{vendor} link via headless render: {vendor_url}"
                )
                result.outcome = "platform-found"
                return result
            hop2 = find_school_hop_links(hh, hurl)
            if hop2:
                result.listing_url = hop2[0]
                result.note = "headless found a board-page link; not followed (budget)"
        else:
            result.note = f"headless failed: {herr}"

    # collect video/channel candidates from whatever pages we fetched
    sources: List[Tuple[str, str]] = [(r.final_url, r.html)]
    if listing_html and listing_url_used:
        sources.append((listing_url_used, listing_html))
    vids: List[Tuple[str, str]] = []
    chans: List[str] = []
    for src_url, html in sources:
        vids.extend(find_video_candidates(html, src_url))
        chans.extend(find_channel_leads(html, src_url))

    if vids:
        result.video_candidate_urls = ";".join(u for _, u in vids[:5])
        result.evidence_marker = (
            result.evidence_marker or f"video-shaped link found: {vids[0][1]}"
        )
    if chans:
        result.channel_lead_url = chans[0]
        result.evidence_marker = (
            result.evidence_marker or f"channel-shaped link found: {chans[0]}"
        )

    if vids:
        result.outcome = "video-candidate"
    elif result.listing_url:
        result.outcome = "listing-found-no-platform"
    elif chans:
        result.outcome = "channel-lead"
    else:
        result.outcome = "nothing"
    return result


async def guess_vendor_tenants(
    session: aiohttp.ClientSession,
    rl: RateLimiter,
    row: Dict[str, str],
    result: DistrictResult,
) -> None:
    if result.platform_found:
        return
    domain = (row.get("domain") or "").strip()
    if not domain:
        return
    labels = label_variants(domain)
    if not labels:
        return
    state_abbr = state_abbr_for(row.get("state", ""))

    if state_abbr:
        for label in labels:
            url = boarddocs_guess_url(state_abbr, label)
            r, _ = await polite_fetch(session, rl, url, HONEST_HEADERS)
            if (
                r.html
                and not is_challenge(r.html)
                and looks_like_real_tenant(r.html)
                and ("boarddocs" in r.html.lower())
            ):
                result.vendor_tenant_url = url
                result.platform_found = "boarddocs"
                result.platform_evidence_url = url
                result.evidence_marker = (
                    f"BoardDocs guess resolved (label={label}): {url}"
                )
                result.outcome = "platform-found"
                return

    for label in labels:
        url = civicclerk_guess_url(label)
        r, _ = await polite_fetch(session, rl, url, HONEST_HEADERS)
        if r.html and not is_challenge(r.html) and looks_like_real_tenant(r.html):
            result.vendor_tenant_url = url
            result.platform_found = "civicclerk"
            result.platform_evidence_url = url
            result.evidence_marker = f"CivicClerk guess resolved (label={label}): {url}"
            result.outcome = "platform-found"
            return

    for label in labels:
        for view_id in (1, 2, 3):
            url = granicus_guess_url(label, view_id)
            r, _ = await polite_fetch(session, rl, url, HONEST_HEADERS)
            if (
                r.html
                and not is_challenge(r.html)
                and looks_like_real_tenant(r.html)
                and (
                    "granicus" in r.html.lower()
                    or "viewpublisher" in r.final_url.lower()
                )
            ):
                result.vendor_tenant_url = url
                result.platform_found = "granicus"
                result.platform_evidence_url = url
                result.evidence_marker = (
                    f"Granicus guess resolved (label={label}, view_id={view_id}): {url}"
                )
                result.outcome = "platform-found"
                return

    for label in labels:
        url = iqm2_guess_url(label)
        r, _ = await polite_fetch(session, rl, url, HONEST_HEADERS)
        if r.html and not is_challenge(r.html) and looks_like_real_tenant(r.html):
            result.vendor_tenant_url = url
            result.platform_found = "iqm2"
            result.platform_evidence_url = url
            result.evidence_marker = f"IQM2 guess resolved (label={label}): {url}"
            result.outcome = "platform-found"
            return

    for label in labels:
        url = escribe_guess_url(label)
        r, _ = await polite_fetch(session, rl, url, HONEST_HEADERS)
        if r.html and not is_challenge(r.html) and looks_like_real_tenant(r.html):
            result.vendor_tenant_url = url
            result.platform_found = "escribe"
            result.platform_evidence_url = url
            result.evidence_marker = f"eScribe guess resolved (label={label}): {url}"
            result.outcome = "platform-found"
            return

    url = civicplus_agendacenter_guess_url(domain)
    r, _ = await polite_fetch(session, rl, url, HONEST_HEADERS)
    if (
        r.html
        and not is_challenge(r.html)
        and "agendacenter" in r.final_url.lower()
        and looks_like_real_tenant(r.html)
    ):
        result.vendor_tenant_url = url
        result.platform_found = "civicplus"
        result.platform_evidence_url = url
        result.evidence_marker = f"CivicPlus /AgendaCenter guess resolved: {url}"
        result.outcome = "platform-found"


async def process_district(
    session: aiohttp.ClientSession, rl: RateLimiter, row: Dict[str, str]
) -> DistrictResult:
    gov_id = row.get("gov_id", "")
    name = row.get("name", "")
    state = row.get("state", "")
    population = row.get("population", "")

    if is_confirmed_dead(name, state):
        return DistrictResult(
            gov_id=gov_id,
            name=name,
            state=state,
            population=population,
            domain=row.get("domain", ""),
            outcome="skipped-confirmed-dead",
            note="matched a named confirmed-dead/false-positive entry in "
            "SCHOOL_DISTRICT_ENUMERATION_HANDOVER.md",
        )

    domains = candidate_domains(row)
    if not domains:
        return DistrictResult(
            gov_id=gov_id,
            name=name,
            state=state,
            population=population,
            domain=row.get("domain", ""),
            outcome="nothing",
            note="no domain/alternate_domains on file",
        )

    final_result: Optional[DistrictResult] = None
    for domain in domains:
        r = await try_one_domain(session, rl, domain)
        final_result = r
        # keep trying an alternate only when this one produced literally
        # nothing usable (dead/blocked/human-gate/nothing) -- per this
        # project's "found a meeting or agenda, or not" rule (docs/
        # COVERAGE_HANDOVER.md section 4), stop once real content or a
        # platform/listing/video/channel signal turns up.
        if r.outcome not in ("dead", "blocked", "human-gate", "nothing"):
            break

    assert final_result is not None
    final_result.gov_id = gov_id
    final_result.name = name
    final_result.state = state
    final_result.population = population
    final_result.domain = row.get("domain", "")

    if final_result.outcome in ("nothing", "listing-found-no-platform"):
        await guess_vendor_tenants(session, rl, row, final_result)

    return final_result


# --- CSV I/O -------------------------------------------------------------


def already_done_gov_ids(report_csv: Path) -> set:
    if not report_csv.exists():
        return set()
    with report_csv.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f) if r.get("gov_id")}


def report_writer(report_csv: Path):
    is_new = not report_csv.exists()
    f = report_csv.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=REPORT_FIELDS, lineterminator="\n")
    if is_new:
        w.writeheader()
    return f, w


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_CSV)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    with args.input.open(newline="", encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))
    print(f"{len(all_rows)} district rows in {args.input.name}")

    done = already_done_gov_ids(args.report)
    print(f"{len(done)} gov_ids already in {args.report.name} -- skipping those.")

    to_process = [r for r in all_rows if r.get("gov_id") not in done]
    if args.limit:
        to_process = to_process[: args.limit]
    print(f"Processing {len(to_process)} row(s)...\n")

    rl = RateLimiter()
    report_f, writer = report_writer(args.report)
    tally: Dict[str, int] = {}
    skip_count = 0
    consecutive_exceptions = 0

    try:
        async with aiohttp.ClientSession() as session:
            for i, row in enumerate(to_process):
                t0 = time.monotonic()
                try:
                    result = await process_district(session, rl, row)
                    consecutive_exceptions = 0
                except Exception as e:  # noqa: BLE001 -- keep the sweep alive
                    consecutive_exceptions += 1
                    result = DistrictResult(
                        gov_id=row.get("gov_id", ""),
                        name=row.get("name", ""),
                        state=row.get("state", ""),
                        population=row.get("population", ""),
                        domain=row.get("domain", ""),
                        outcome="nothing",
                        note=f"unhandled exception: {type(e).__name__}: {e}",
                    )
                if result.outcome == "skipped-confirmed-dead":
                    skip_count += 1
                writer.writerow({k: getattr(result, k) for k in REPORT_FIELDS})
                report_f.flush()
                tally[result.outcome] = tally.get(result.outcome, 0) + 1

                if (i + 1) % PROGRESS_EVERY == 0 or i == len(to_process) - 1:
                    elapsed = time.monotonic() - t0
                    print(
                        f"[{i + 1}/{len(to_process)}] last={result.name}, {result.state} "
                        f"({elapsed:.1f}s) -- {result.outcome} -- "
                        f"skipped-confirmed-dead so far: {skip_count}"
                    )

                if consecutive_exceptions >= CONSECUTIVE_EXCEPTION_LIMIT:
                    print(
                        f"\nABORTING: {consecutive_exceptions} consecutive "
                        "unhandled exceptions.",
                        file=sys.stderr,
                    )
                    break

                await asyncio.sleep(GOV_DELAY_SECONDS)
    finally:
        report_f.close()

    print("\n--- Tally (this run) ---")
    for k, v in sorted(tally.items()):
        print(f"{k:28} {v}")
    print(f"\nskipped-confirmed-dead (discovery handover): {skip_count}")
    print(f"Report: {args.report}")


if __name__ == "__main__":
    asyncio.run(main())
