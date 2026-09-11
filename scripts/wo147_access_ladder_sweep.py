"""WO-147 (2026-09-10): access-ladder sweep of 850 signature-less
access-failure rejects -- rtr-business/research/wo147_candidates.csv,
candidate list 3 in docs/BREADTH_SWEEP_BRIEF.md.

Goal (Ryan's, restated in the brief): one meeting WITH VIDEO per
government, breadth not depth. Only meetings with video become Archive
pages (tier 1/2, real captions). Tier 3 (real video, no reachable
captions) is probed for a dead link/too-short clip before it ever
reaches the queue file -- see TIER3_HANDLER usage below. Agenda-only is
recorded `no-video-found` and never ingested.

Method, per docs/BREADTH_SWEEP_BRIEF.md and CLAUDE.md's "politely" rule:

1. **Access ladder** -- can we even read this host, and with which rung:
   a. plain HTTP, honest headers (HONEST_HEADERS, copied verbatim from
      rtr-business/research/wo141_access_ladder_pilot.py -- attribution
      in that constant's own comment).
   b. browser headers (BROWSER_HEADERS, same source), once, only after a
      403 or a dropped connection -- never after a 404.
   c. headless (Playwright, one browser, one host at a time), only when
      an earlier rung got a real page with no visible meeting link at
      all -- never run on a host that 403'd browser headers (WO-141
      found headless does worse there).
   d. stop at a human-verification challenge marker (CHALLENGE_MARKERS,
      same source) -- record it, never retry past it.
   The "session" rung WO-141 tested is deliberately NOT part of this
   ladder -- the pilot found it added nothing on a blind sweep (see the
   brief's "Two things the pilots corrected").
2. **Platform discovery** -- once a rung produces a real page, scan it
   (and, if nothing found, one hop into meeting/agenda/council/video-
   hinted links) for a link `detect_platform()` recognizes. A row's own
   `known_platform` (from an earlier, cruder pass) is always retried too
   even with no visible link, since `locate_platform_url()` (imported
   from wo134_confirmed_hits_ingest.py) already knows how to guess a
   CivicPlus AgendaCenter / Granicus ViewPublisher seed from a bare
   domain.
   **The hop-link step is a ranked scorer, not a first-match loop
   (WO-228, 2026-09-11).** `find_hop_links()` used to keep the first
   MAX_HOP_LINKS links in document order matching any of
   HOP1_HINT_WORDS -- "calendar" in a nav bar won the slot as often as
   the real agenda/minutes/video link, and the coverage registry showed
   358 governments with an events calendar recorded as their meeting hub
   as a direct result. It now scores every candidate
   (`_score_hop_candidate()`) from weights measured against two real
   samples (90 real "no link found -> real hit" governments, 60 of the
   358 calendar-shaped hubs -- see `research/wo228_report.csv` and
   ENUMERATION_METHODS.md) and returns them best-first. Two more WO-228
   helpers back it up: `looks_like_document_hub()` verifies a fetched
   hop page actually shows document/platform evidence rather than
   trusting the ranking alone, and `find_calendar_entry_links()` takes
   one more hop into a calendar page's first two dated entries
   (`?EID=123`-shaped) when the calendar page itself has none.
3. **Resolve/ingest** -- every found (platform, url) pair is handed to
   wo134_confirmed_hits_ingest.py's own `process_row()` UNCHANGED (its
   locate_platform_url -> resolve_seed -> ingest/queue/pin pipeline is
   the "go deep enough to find a meeting with video, up to 6 candidates"
   logic this WO also needs -- reused, not reimplemented). The one
   difference: TIER3_HANDLER (added to that module for this WO) routes a
   tier-3 candidate to `wo147_tier3_pending.csv` for probing instead of
   the queue file, per Ryan's "probe before queue" rule.

rtr-discovery enumeration (the brief's step 1, "platform API first") is
attempted best-effort against a SCRATCH ledger copy
(/tmp/wo147_ledger.db, copied once from ~/Documents/rtr-discovery/
ledger.db and never written back -- two real discovery sessions are live
on the real one) for every platform its own `discovery/enumerators/`
package covers. Its only job here is to add a few real, dated candidate
meeting URLs (newest first) to the SAME hit_source_urls list process_row
already knows how to walk -- it is a candidate-URL source, not a second
resolve/ingest path, so there is exactly one ingest/queue/pin code path
in this whole script. Wrapped in a hard per-tenant timeout and a bare
except: a discovery failure never blocks the plain-URL fallback that
`locate_platform_url()`/`resolve_seed()` already provide on their own.

Run with the interpreter that can import BOTH `discovery` and `app`:
    ~/Documents/rtr-discovery/.venv/bin/python scripts/wo147_access_ladder_sweep.py

Usage:
    python scripts/export_meeting_inventory.py --out-dir /tmp/wo147_inventory --source export
    ~/Documents/rtr-discovery/.venv/bin/python scripts/wo147_access_ladder_sweep.py --limit 30
    ~/Documents/rtr-discovery/.venv/bin/python scripts/wo147_access_ladder_sweep.py   # full run, resumable
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
CANDIDATES_CSV = RESEARCH_DIR / "wo147_candidates.csv"
NACO_CSV = RESEARCH_DIR / "naco_county_websites.csv"
REPORT_CSV = RESEARCH_DIR / "wo147_report.csv"
DISCOVERY_SEEDS_CSV = RESEARCH_DIR / "wo147_discovery_seeds.csv"
HOST_ACCESS_MODES_CSV = RESEARCH_DIR / "wo147_host_access_modes.csv"
TIER3_PENDING_CSV = RESEARCH_DIR / "wo147_tier3_pending.csv"
DEFAULT_INVENTORY_CSV = Path("/tmp/wo147_inventory/meeting_inventory.csv")

DISCOVERY_ROOT = Path.home() / "Documents" / "rtr-discovery"
SCRATCH_LEDGER = Path("/tmp/wo147_ledger.db")

GOV_DELAY_SECONDS = 1.5  # between governments
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

# --- copied verbatim (signature set only) from
# rtr-business/research/wo129_two_hop_scan.py (WO-129, 2026-09-09) ---
HOP1_HINT_WORDS = [
    "agenda",
    "minutes",
    "calendar",
    "meeting",
    "commissioners court",
    "city council",
    "town council",
    "board of",
    "video",
    "stream",
    "council",
    "commission",
]
MAX_HOP_LINKS = 8

# known_platform values in wo147_candidates.csv aren't always the
# canonical short key detect_platform()/get_finder() use -- normalize
# before ever constructing a hit_source_urls pair with it.
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

# Platforms rtr-discovery's own discovery/enumerators/ package covers --
# see that directory's file listing. youtube_channel and hyland
# deliberately excluded: this WO's brief says "never enumerate a YouTube
# channel directly," and hyland/onbase tenants in this candidate list
# are unconfirmed guesses (see CLAUDE.md's OnBase note), not proven
# hylandcloud.com/databankcloud.com hosts detect_platform() recognizes.
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
_META_TAG_RE = re.compile(r"<meta\b[^>]*>", re.I)


# Real, confirmed-live false positive caught in this script's own 30-row
# pilot (Oceanside CA, wo133_headless): a "Powered by Granicus" footer
# badge links to the vendor's own marketing homepage
# (https://www.granicus.com/), and detect_platform() -- correct for its
# real job, classifying an ALREADY-KNOWN real meeting URL -- matches it
# purely on `"granicus.com" in netloc`, with no tenant-subdomain check.
# find_specific_platform_link() in wo134_confirmed_hits_ingest.py has
# the identical exposure (same substring test), but this script is the
# first caller that scans arbitrary anchors rather than checking one
# already-known-real URL, so it's the first to hit it in practice --
# filed in BACKLOG.md. Same reasoning as WO-141's own
# SUBDOMAIN_LINK_PATTERN/MARKETING_SUBDOMAINS guard (that pilot's
# Columbus OH `<meta generator>` false positive) -- a bare vendor apex
# domain (with or without "www.") is never a real per-tenant instance.
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


# Also copied from wo141_access_ladder_pilot.py (WO-141): non-tenant
# subdomains that show up in nearly every customer's footer/head and
# never point at a real per-government instance -- New Haven CT's own
# hit in this script's 30-row pilot was exactly this shape,
# support.granicus.com/s/article/govDelivery-Statement-of-Accessibility
# (a Granicus knowledge-base article, not a tenant).
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


def _safe_soup(html_text: str) -> Optional[BeautifulSoup]:
    """BeautifulSoup's own `html.parser` backend can raise
    `ParserRejectedMarkup` (an `AssertionError` inside the stdlib parser,
    wrapped) on a response that LOOKS like text (decoded via
    `resp.text(errors="replace")` in fetch_one(), so it's always a `str`,
    never bytes) but is actually binary/garbled -- confirmed live running
    this WO's own 1,814-government sweep: a host returned exactly this
    shape and the original, unguarded `BeautifulSoup(html_text, ...)`
    call crashed the whole run with an unhandled exception, killing 900+
    rows of real, already-collected progress along with it. Every caller
    below already treats "nothing found" as a normal, valid outcome for
    an ordinary page with no link -- a page BeautifulSoup can't parse at
    all is the same outcome, not a fatal error."""
    try:
        return BeautifulSoup(html_text, "html.parser")
    except Exception:  # noqa: BLE001 -- any parser failure, never fatal here
        return None


def find_platform_link(html_text: str, final_url: str) -> Optional[Tuple[str, str]]:
    """Scans real anchors/iframes/video tags (same tag set as wo134's own
    find_specific_platform_link()) for a URL detect_platform() recognizes
    -- the SAME function the resolve step uses, so "found" here means
    "the adapter layer would also recognize it," not a separate guess.
    Also checks for a same-domain CivicPlus AgendaCenter path (no vendor
    subdomain needed) since that's the single most common self-hosted
    case in this candidate population (wo126_hub's 306 rows)."""
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
            # detect_platform()'s own not-found fallback is the literal
            # string "unknown", not None/"" -- confirmed in
            # app/platforms/base.py's own final `return "unknown"` line.
            # Real bug caught in this script's own smoke test (Gwinnett
            # County GA): treating that as truthy claimed the FIRST
            # anchor on the page as a "platform hit" every time nothing
            # else matched.
            if (
                platform
                and platform != "unknown"
                and not _is_vendor_marketing_apex(urlparse(candidate).netloc)
            ):
                return platform, candidate
    return None


# --- WO-228 (2026-09-11): scored, ranked replacement for the old
# first-match find_hop_links() ---
#
# Root cause this replaces: the old loop kept the first MAX_HOP_LINKS
# links in DOCUMENT ORDER whose text/href matched any of HOP1_HINT_WORDS
# (unranked -- "calendar" scored the same as "agenda"). Measured from the
# coverage registry, 358 governments with a hub URL and no Archive page
# have a calendar/events/dashboard-shaped hub as a direct result -- see
# `rtr-business/research/wo228_report.csv` and this WO's methods section
# in ENUMERATION_METHODS.md for the study.
#
# The weights below come from two real samples, not a guessed list:
# 90 governments where a real video/meeting hit followed a "no platform
# link found" verdict (`wo228_positive_links.csv`, stratified across 13
# platform families) and 60 of the 358 calendar-shaped hubs
# (`wo228_negative_hubs.csv`). The clean split: an anchor reading both
# "agenda" and "minutes" led to the real hub 14/14 times it was tested
# and never to a wrong page; a bare "calendar"/"events" anchor (no other
# qualifying word) led to a wrong page 14/14 times and never to a real
# one. 62% (24/39) of the real hits were NOT the first HOP1-matching
# link in document order on their page -- the old rule would have handed
# the ladder something else first on a majority of real cases, not a
# minority.
_STRONG_VIDEO_PHRASES = (
    "video archive",
    "meeting video",
    "meeting videos",
    "watch the video",
    "watch meeting",
    "watch meetings",
    "view our video",
    "past meeting",
    "past meetings",
)
_VIDEO_WORDS = ("video", "webcam", "stream", "watch")
_BODY_WORDS = ("council", "commission", "committee", "board of", " board")
# Same distinct-platform hosts detect_platform()/_is_vendor_marketing_apex
# already know about -- a hop candidate whose OWN href resolves to one of
# these (and isn't the bare vendor marketing apex) is effectively already
# a find_platform_link() hit; ranking it first costs nothing and helps
# when a platform-shaped anchor slips past that scan (e.g. an onclick/
# iframe find_platform_link doesn't check, or a marketing-subdomain guard
# false-negative). Kept as hint substrings, not exact hosts, since a
# widget can embed the platform name in a same-domain asset path too
# (WO-228's "platform-host-hint" basis, 14/14 real in the positive
# sample).
_PLATFORM_HREF_HINTS = tuple(_VENDOR_MARKETING_APEX) + (
    "youtube.com",
    "youtu.be",
    "vimeo.com",
)
# Real routine-municipal words seen on the negative sample's own calendar
# pages (48/60 mixed at least one of these in) -- an anchor carrying one
# is a dead giveaway it's pointing at a general city-events calendar, not
# a meeting hub.
_ROUTINE_WORDS = (
    "trash",
    "recycling",
    "garbage",
    "holiday",
    "closure",
    "closed",
    "festival",
    "library",
    "parade",
    "farmers market",
    "blood drive",
    "egg hunt",
    "fireworks",
    "concert",
    "food truck",
    "yard waste",
    "leaf collection",
    "street sweeping",
    "pool",
    "summer camp",
    "movie night",
    "art show",
    "5k",
    "flu shot",
    "vaccination",
)
# Real false positive caught building this WO's own fixtures (Atlantic
# City NJ, 2026-09-11): an HTML5 `<video>` tag's fallback text ("Your
# browser does not support the video tag.") is itself wrapped in an <a>
# by that site's template, so its anchor TEXT contains the word "video"
# and scored as a real video-phrase hint even though it names no actual
# destination content -- confirmed live, ranked #1 over the page's real
# "/Meetings" link before this guard.
_BOILERPLATE_PHRASES = ("does not support the video tag",)


def _score_hop_candidate(
    text: str, href: str, full_url: str, base_netloc: str
) -> Optional[int]:
    """Returns None for a candidate that should never be offered at all
    (a bare vendor-marketing apex, or boilerplate markup text that isn't
    a real navigational label); otherwise a signed score, higher is
    better. See this module's WO-228 comment block above for where each
    weight comes from."""
    netloc = urlparse(full_url).netloc.lower()
    if _is_vendor_marketing_apex(netloc) and netloc != base_netloc:
        return None

    hay = f"{text} {href}".lower()
    if any(p in hay for p in _BOILERPLATE_PHRASES):
        return None
    score = 0

    if any(w in hay for w in _ROUTINE_WORDS):
        score -= 8

    if (
        netloc
        and netloc != base_netloc
        and any(h in netloc for h in _PLATFORM_HREF_HINTS)
    ):
        score += 11
    elif any(h in hay for h in _PLATFORM_HREF_HINTS):
        score += 7

    if "agenda" in hay and "minute" in hay:
        score += 10
    elif "agenda center" in hay:
        score += 8
    elif "agenda" in hay:
        score += 4

    if any(p in hay for p in _STRONG_VIDEO_PHRASES):
        score += 9
    elif any(w in hay for w in _VIDEO_WORDS):
        score += 6

    has_body_word = any(w in hay for w in _BODY_WORDS)
    if has_body_word and "meeting" in hay:
        score += 4
    elif has_body_word:
        score += 1

    has_qualifier = (
        score != 0
        or "agenda" in hay
        or "minute" in hay
        or any(w in hay for w in _VIDEO_WORDS)
        or has_body_word
    )
    if ("calendar" in hay or "event" in hay) and not has_qualifier:
        score -= 6

    return score


def find_hop_links(html_text: str, final_url: str) -> List[str]:
    """Gathers every anchor whose text/href matches HOP1_HINT_WORDS (same
    candidate gate as before -- WO-228 changes the ORDER, not the set),
    scores each with `_score_hop_candidate()`, and returns up to
    MAX_HOP_LINKS URLs ranked best-first (a stable sort, so two candidates
    with an equal score keep their original document order). Signature
    and MAX_HOP_LINKS are unchanged so every importer keeps working."""
    soup = _safe_soup(html_text)
    if soup is None:
        return []
    base_netloc = urlparse(final_url).netloc.lower()
    scored: List[Tuple[int, int, str]] = []  # (score, doc_order, url)
    seen = set()
    doc_order = 0
    for a in soup.find_all("a", href=True):
        text = (a.get_text() or "").strip()
        href = a["href"]
        hay = f"{text} {href}".lower()
        if not any(w in hay for w in HOP1_HINT_WORDS):
            continue
        full = urljoin(final_url, href)
        if full in seen or urlparse(full).scheme not in ("http", "https"):
            continue
        score = _score_hop_candidate(text, href, full, base_netloc)
        if score is None:
            continue
        seen.add(full)
        scored.append((score, doc_order, full))
        doc_order += 1

    scored.sort(key=lambda t: (-t[0], t[1]))
    return [url for _, _, url in scored[:MAX_HOP_LINKS]]


# --- WO-228 rule 2: verify a fetched hop candidate actually looks like a
# meeting/document hub before trusting it, rather than accepting whatever
# find_hop_links ranked first on text alone. ---
_DOCUMENT_HUB_HINTS = (
    ".pdf",
    "viewfile",
    "documentcenter",
    "agendacenter",
)


def looks_like_document_hub(html_text: str) -> bool:
    """True when a fetched page shows real evidence of being a document/
    meeting hub rather than a generic calendar shell: a document link
    (.pdf, ViewFile, DocumentCenter, AgendaCenter), an `/event/<n>/`-style
    single-entry permalink, or a known platform host anywhere on the
    page. Used by the ladder only where the old code would have recorded
    the current hop's URL as the hub without ever looking at its content."""
    low = html_text.lower()
    if any(h in low for h in _DOCUMENT_HUB_HINTS):
        return True
    if re.search(r"/event/\d+/", low):
        return True
    soup = _safe_soup(html_text)
    if soup is None:
        return False
    for tag in soup.find_all(_TAGS):
        href_or_src = (tag.get("href") or tag.get("src") or "").lower()
        if not href_or_src:
            continue
        platform = detect_platform(urljoin("https://example.invalid/", href_or_src))
        if platform and platform != "unknown":
            return True
    return False


_CALENDAR_ENTRY_HREF_RE = re.compile(
    r"(?:[?&](?:eid|eventid|id)=\d+)|/event/\d+/?|/events/\d+/?", re.I
)


def find_calendar_entry_links(
    html_text: str, final_url: str, limit: int = 2
) -> List[str]:
    """WO-228 rule 3: when the old code would have stopped at a calendar
    page, take one more hop into its first `limit` individual dated
    entries (a `?EID=123`/`/event/123/`-shaped href, in document order --
    calendar listings are date-ordered, so the first entries are also the
    soonest/most recent) rather than accepting the calendar's own index
    page as the hub. Real negative-sample finding this responds to: 23 of
    60 calendar-shaped hubs already had a sibling agenda/minutes/video
    link on the SAME page the old code never looked at (`sibling_link_*`
    columns in wo228_negative_hubs.csv); a dated entry is the other real
    path in when the calendar page itself carries no such sibling."""
    soup = _safe_soup(html_text)
    if soup is None:
        return []
    out: List[str] = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not _CALENDAR_ENTRY_HREF_RE.search(href):
            continue
        full = urljoin(final_url, href)
        if full in seen or urlparse(full).scheme not in ("http", "https"):
            continue
        seen.add(full)
        out.append(full)
        if len(out) >= limit:
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
    """Returns 'dns', 'timeout', or 'connection' -- used to decide which
    rung to try next and, if nothing works, the final access_mode."""
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


async def run_access_ladder(
    session: aiohttp.ClientSession, name: str, state: str, domain: str, prior_url: str
) -> LadderResult:
    """Plain -> browser-headers -> headless, stopping at a challenge or
    the first real platform link. See this module's docstring for the
    exact rung order/rules (docs/BREADTH_SWEEP_BRIEF.md's method)."""
    candidates: List[str] = []
    primary = normalize_home_url(prior_url) or normalize_home_url(domain)
    if primary:
        candidates.append(primary)
    net = urlparse(primary).netloc if primary else ""
    if net and not net.startswith("www."):
        candidates.append(f"https://www.{net}{urlparse(primary).path}")
    if primary and primary.startswith("https://"):
        candidates.append("http://" + primary[len("https://") :])

    notes: List[str] = []
    dns_failures = 0
    last_result: Optional[FetchResult] = None
    home_url_used = primary

    for i, url in enumerate(candidates):
        if i:
            await asyncio.sleep(HOST_DELAY_SECONDS)
        r = await fetch_one(session, url, HONEST_HEADERS)
        last_result = r
        home_url_used = url
        if r.error_kind == "dns":
            dns_failures += 1
            notes.append(f"dns-fail on {url}")
            continue
        break  # a non-DNS outcome (success or a real error) ends the variant search
    else:
        # every candidate URL exhausted the list and all were DNS failures
        pass

    if (
        last_result is not None
        and last_result.error_kind == "dns"
        and dns_failures == len(candidates)
    ):
        naco = naco_website(name, state)
        if naco:
            naco_url = normalize_home_url(naco)
            await asyncio.sleep(HOST_DELAY_SECONDS)
            r2 = await fetch_one(session, naco_url, HONEST_HEADERS)
            if r2.error_kind != "dns":
                last_result = r2
                home_url_used = naco_url
                notes.append(f"recovered via NACo website column: {naco}")

    r = last_result
    assert r is not None

    if r.error_kind == "dns":
        return LadderResult(
            "dead", "dead", home_url_used, None, "", "none", "; ".join(notes)
        )
    if r.error_kind == "timeout" and r.status is None:
        # one retry under browser headers before giving up -- a dropped
        # connection/timeout is eligible for rung b, same as a 403.
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
                )
            return LadderResult(
                "browser-headers",
                "browser-headers",
                home_url_used,
                rb.html,
                rb.final_url,
                rb.waf_family,
                "; ".join(notes + ["reached under browser headers, no link found"]),
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
        )

    hop_links = find_hop_links(r.html, r.final_url)
    if r.status == 403:
        # 403 on the home page itself -- try browser headers before
        # spending a hop budget on honest headers that already failed.
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
            )
        hop_links = find_hop_links(rb.html, rb.final_url)
        r = rb  # continue the hop search under the headers that worked

    # one hop into meeting/agenda/council/video-hinted links, same headers
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
                )
            # WO-228 rule 3: this hop landed on a page shaped like a
            # calendar (its own URL says so) that carries no document/
            # platform evidence (looks_like_document_hub) -- rather than
            # accept the calendar's own index as the hub (the old
            # behaviour: fall through and record "no platform link
            # found"), take one more hop into its first two individual
            # dated entries, since a calendar listing is date-ordered and
            # a real meeting entry is exactly the shape a bare index page
            # never shows. Real finding behind this: 23/60 of this WO's
            # calendar-shaped hub sample already had a passed-over
            # sibling link, and Fulton County GA's own calendar listed a
            # dated entry titled "Commissioners Session Agenda
            # 9-15-2026" one hop below the index.
            if (
                "calendar" in link.lower() or "event" in link.lower()
            ) and not looks_like_document_hub(rh.html):
                for entry_url in find_calendar_entry_links(rh.html, rh.final_url):
                    await asyncio.sleep(HOST_DELAY_SECONDS)
                    re_ = await fetch_one(session, entry_url, headers)
                    if re_.html and is_challenge(re_.html):
                        return LadderResult(
                            "challenge",
                            "challenge",
                            home_url_used,
                            re_.html,
                            re_.final_url,
                            re_.waf_family,
                            "",
                        )
                    if re_.html:
                        entry_hit = find_platform_link(re_.html, re_.final_url)
                        if entry_hit:
                            mode = (
                                "browser-headers"
                                if headers is BROWSER_HEADERS
                                else "plain"
                            )
                            return LadderResult(
                                mode,
                                mode,
                                home_url_used,
                                re_.html,
                                re_.final_url,
                                re_.waf_family,
                                "found via a calendar entry, not the calendar index",
                                entry_hit[0],
                                entry_hit[1],
                            )

    if not hop_links:
        # a real page with no visible meeting-shaped link at all --
        # exactly the JS-rendered-navigation case headless recovers
        # (WO-133's finding). Never run headless if browser headers 403'd
        # (handled above -- that path already returned).
        await asyncio.sleep(HOST_DELAY_SECONDS)
        rh_html, rh_url, rh_err = await fetch_headless(r.final_url or home_url_used)
        if rh_html and is_challenge(rh_html):
            return LadderResult(
                "challenge", "challenge", home_url_used, rh_html, rh_url, "none", ""
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
                )
            return LadderResult(
                "headless",
                "headless",
                home_url_used,
                rh_html,
                rh_url,
                "none",
                "headless reached the page, no platform link found",
            )
        return LadderResult(
            "plain",
            "plain",
            home_url_used,
            r.html,
            r.final_url,
            r.waf_family,
            f"headless failed: {rh_err}",
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
    """One-time setup: copy the scratch ledger (never touch the real
    one -- two live discovery sessions), import discovery's modules with
    `app` already resolved to THIS worktree (see this module's header
    comment). Returns False (and disables discovery enrichment for the
    rest of the run) on any failure -- this is a best-effort enhancement,
    never a hard dependency for the resolve/ingest path."""
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
    if final_seed in _tier3_pending_already_seen():
        return
    pin_row = ""
    if platform in wo134.SHARED_HOST_PLATFORMS:
        host = wo134._tenant_override_host(platform, result, final_seed)
        match = wo134._tenant_override_match(platform, result, final_seed)
        if host and match:
            pin_row = (
                f"{host}|{match}|{gov_id}|fallback|wo147_access_ladder_sweep|"
                f"{unit_name} -- WO-147 tier-3 pending, gov_id={gov_id}"
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
                "jurisdiction": result.jurisdiction or "",
                "pin_row": pin_row,
            }
        )
    _tier3_pending_already_seen().add(final_seed)


wo134.TIER3_HANDLER = tier3_pending_handler


# --- report -----------------------------------------------------------

_REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "population",
    "prior_source",
    "prior_reason",
    "host",
    "access_mode",
    "rung_answered",
    "platform_found",
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


# Reject-reason taxonomy mapping for process_row()'s own reason strings
# -- same substrings backfill_wo134_ingest_into_jc.py already classifies,
# reused here (imported style, not re-derived) so this report and that
# backfill agree on what each string means.
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
]


def classify_skip_reason(reason: str) -> str:
    for substring, value in _CONTENT_TAXONOMY:
        if substring in reason:
            return value
    return "no-platform-link-found"


def government_display_name(
    gov_id: str, fallback_name: str, fallback_state: str
) -> str:
    gov = government_for_id(gov_id)
    if gov and gov.gov_name and gov.state:
        return f"{gov.gov_name}, {gov.state}"
    return f"{fallback_name}, {fallback_state}"


# Real, confirmed-live finding from this script's own 40-government
# pilot (2026-09-10): 3 of 8 tier-3 candidates found through a bare
# YouTube channel/handle/vanity-URL listing scan were NOT real meetings
# despite passing resolve_seed()'s title allowlist -- "HAIRitage 2026
# CROWN Act Workshop: Advice from Our Commissioner Board" (Union County
# NJ), "Commissioners Tour Picatinny Arsenal's Revolutionary Roots"
# (Morris County NJ), "Council Participation Instructions" (Fort
# Collins CO) -- all three matched the allowlist purely because a body
# name ("board"/"commissioners"/"council") appears in an unrelated
# promotional/explainer video's own title. The other 5 candidates in the
# same pilot came from a specific already-linked video, a curated
# playlist, or a non-YouTube platform, and all 5 were real meetings -- a
# curated "Board Meetings" playlist is a much stronger signal than a
# channel's raw most-recent-uploads list, which mixes everything. Filed
# in BACKLOG.md; this flag doesn't reject the candidate (breadth matters
# and 5/8 were real), it just marks it for a manual title check before
# the post-probe accept step ever queues/pins it.
_YT_CHANNEL_SHAPE_MARKERS = ("/watch", "youtu.be/", "list=", "/embed/")


def is_bare_youtube_channel_hit(url: str) -> bool:
    if "youtube.com" not in url and "youtu.be" not in url:
        return False
    return not any(marker in url for marker in _YT_CHANNEL_SHAPE_MARKERS)


def channel_scan_caution(platform: str, hits: List[Tuple[str, str]]) -> str:
    if platform != "youtube":
        return ""
    if any(p == "youtube" and is_bare_youtube_channel_hit(u) for p, u in hits):
        return (
            "CAUTION: found via a bare YouTube channel/handle/vanity-URL scan, "
            "not a specific linked video or playlist -- this WO's own pilot found "
            "3/8 such hits were not real meetings despite passing the title gate; "
            "verify the title by hand before this entry is queued/pinned"
        )
    return ""


# --- main driver --------------------------------------------------------


async def process_candidate(
    session: aiohttp.ClientSession, row: dict, covered_gov_ids: set, writer
) -> str:
    """Returns 'ok' or 'error' (for the consecutive-error breaker)."""
    gov_id = row["gov_id"]
    name = row["name"]
    state = row["state"]
    gov_kind = row["gov_kind"]
    population = row["population"]
    domain = row["domain"]
    known_platform_raw = row["known_platform"]
    hub_url = row["hub_url"]
    prior_source = row["prior_source"]
    prior_reason = row["prior_reason"]
    prior_url = row["prior_url"]

    base_report = dict(
        gov_id=gov_id,
        name=name,
        state=state,
        gov_kind=gov_kind,
        population=population,
        prior_source=prior_source,
        prior_reason=prior_reason,
        host="",
        access_mode="",
        rung_answered="",
        platform_found="",
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

    home_source = prior_url or domain
    base_report["host"] = urlparse(normalize_home_url(home_source)).netloc

    ladder = await run_access_ladder(session, name, state, domain, prior_url)
    base_report["access_mode"] = ladder.access_mode
    base_report["rung_answered"] = ladder.rung_answered
    base_report["waf_family"] = ladder.waf_family
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

    if ladder.access_mode == "dead":
        reject_reason = (
            "dns-unresolvable"
            if "dns" in (ladder.note or "").lower() or True
            else "timeout"
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

    if ladder.access_mode == "timeout":
        writer.writerow(
            {
                **base_report,
                "outcome": "blocked",
                "reject_reason": "timeout",
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

    # A rung produced a real page. Gather every (platform, url) hit we
    # have: whatever find_platform_link() saw on that page, PLUS the
    # row's own known_platform against its home url/hub_url (locate_
    # platform_url() already knows how to guess a real seed from just a
    # domain for civicplus/granicus), PLUS discovery-enumerated real
    # candidate URLs when the platform is one discovery covers.
    hits: List[Tuple[str, str]] = []
    if ladder.platform and ladder.hit_url:
        hits.append((ladder.platform, ladder.hit_url))

    known_platform = normalize_known_platform(known_platform_raw)
    if known_platform and known_platform not in wo134.UNSUPPORTED_PLATFORMS:
        seed = hub_url or ladder.home_url or normalize_home_url(home_source)
        if not any(p == known_platform for p, _ in hits):
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

    # "up to 6 per government" -- CLAUDE.md's WO-147 method.
    hit_source_urls = ";".join(f"{p}={u}" for p, u in hits[:6])
    base_report["candidates_listed"] = len(hits[:6])
    base_report["candidates_tried"] = len(hits[:6])
    if discovery_note:
        base_report["note"] = (base_report["note"] + "; " + discovery_note).strip("; ")

    synthetic_row = {
        "gov_id": gov_id,
        "unit_name": name,
        "homepage": ladder.home_url or normalize_home_url(home_source),
        "hop2_urls": "",
        "hit_source_urls": hit_source_urls,
    }

    try:
        result = await wo134.process_row(
            session, synthetic_row, covered_gov_ids, "wo147_access_ladder_sweep"
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
        caution = channel_scan_caution(result.platform, hits)
        note = "; ".join(p for p in (base_report["note"], result.reason, caution) if p)
        writer.writerow(
            {
                **base_report,
                "outcome": "ingested_tier1_2",
                "meeting_url": result.seed_url,
                "tier": tier,
                "page_url": result.page_url,
                "note": note,
            }
        )
        return "ok"

    if outcome == "queued_tier3_pending":
        caution = channel_scan_caution(result.platform, hits)
        note = "; ".join(p for p in (base_report["note"], result.reason, caution) if p)
        writer.writerow(
            {
                **base_report,
                "outcome": "queued_tier3_pending",
                "meeting_url": result.seed_url,
                "video_url": result.video_url,
                "tier": "tier3_pending",
                "note": note,
            }
        )
        return "ok"

    if outcome == "queued_tier3":
        # Only reachable if TIER3_HANDLER somehow wasn't honored --
        # kept for defensiveness, should not occur in this run.
        writer.writerow(
            {
                **base_report,
                "outcome": "queued_tier3",
                "meeting_url": result.seed_url,
                "video_url": result.video_url,
                "tier": "tier3",
                "note": (base_report["note"] + "; " + result.reason).strip("; "),
            }
        )
        return "ok"

    if outcome == "rejected_by_probe":
        # WO-169: a real video existed on this row (wo134.resolve_seed()
        # already tried every candidate on every platform hit and probed
        # each tier-3 one -- see PROBE_HOOK) but none passed WO-144's
        # queue probe. Distinct from no_video_found (no video ever
        # existed) per Ryan's "video existed, take the next candidate,
        # only report this once candidates are exhausted" rule -- see
        # CLAUDE.md's WO-169 entry and app/platforms/queue_probe.py.
        writer.writerow(
            {
                **base_report,
                "outcome": "rejected_by_probe",
                "reject_reason": "rejected_by_probe",
                "reject_class": "content",
                "meeting_url": result.seed_url,
                "video_url": result.video_url,
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
                "video_url": result.video_url,
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

    # outcome == "skipped" -- WO-169: result.seed_url/result.video_url now
    # carry real URL evidence even on a fully-skipped row (see RowSkip's
    # own docstring in wo134_confirmed_hits_ingest.py), so this report
    # keeps them instead of leaving meeting_url/video_url blank. Applies
    # WO-164's tag rule directly: a video with no meeting/listing evidence
    # is video-without-meeting, checked before the substring-based
    # classifier below (which can't see result.video_url at all).
    if result.video_url and not result.seed_url:
        writer.writerow(
            {
                **base_report,
                "outcome": "skipped",
                "reject_reason": "video-without-meeting",
                "reject_class": "content",
                "meeting_url": "",
                "video_url": result.video_url,
                "note": (base_report["note"] + "; " + result.reason).strip("; "),
            }
        )
        return "ok"

    reject_reason = classify_skip_reason(result.reason)
    writer.writerow(
        {
            **base_report,
            "outcome": "no_platform_link_found"
            if reject_reason == "no-platform-link-found"
            else "no_video_found"
            if reject_reason == "no-video-found"
            else "no_meetings_found"
            if reject_reason == "no-meetings-found"
            else "blocked"
            if reject_reason == "unsupported-platform-no-adapter"
            else "skipped",
            "reject_reason": reject_reason,
            "reject_class": "content",
            "meeting_url": result.seed_url,
            "video_url": result.video_url,
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
                    f"({row['gov_kind']}) -- {elapsed:.1f}s -- status={status}"
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
