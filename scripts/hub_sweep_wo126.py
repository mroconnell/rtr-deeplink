"""WO-126: re-work the 973 North America coverage-registry governments
whose `hub_url` is an AgendaCenter or calendar page and which still have
zero Archive pages -- go deep on each hub, get a real meeting page into
the Archive where one exists, and record an honest outcome for every one.

Population: rtr-business/research/coverage_registry/coverage_registry.csv
rows with `hub_url` containing "agendacenter" or "calendar" (case-
insensitive) and `archive_pages == 0`. 886 of them were rejected by
earlier passes (602 `no-platform-link-found`, 228 `no-video-found`), and
Ryan clicked through several and found real meetings behind them -- the
earlier passes stopped at the first listing page (ENUMERATION_METHODS.md's
"Step 2's real weak spot"). This script does what those didn't:

  * CivicPlus AgendaCenter (551 rows, plus every `/calendar.aspx` site
    that turns out to be CivicPlus): the root page only renders each
    category's *current* rows. Older years load through
    `GET /AgendaCenter/UpdateCategoryList?year=YYYY&catID=N` -- confirmed
    live 2026-09-09 on youngstownny.gov (14 `tr.catAgendaRow` rows for
    Village Board 2025) and durhamnc.gov (49 rows for catID=4/2024,
    real `youtube.com/live/...` links in `td.media`). The (year, catID)
    pairs come from the root page's own `changeYear(YEAR, CATID, ...)`
    anchors, so nothing is guessed. Walked newest-first across
    categories, up to a per-government fetch budget, stopping at the
    first year that carries any video row. CivicPlusAssetFinder's own
    `_find_candidate_rows()` parses every fragment, so the row/video/
    agenda-link rules are the adapter's, not a second copy.
  * Every other calendar (WordPress "The Events Calendar", eGov, custom
    CMSes): scan the hub for links to any platform `detect_platform()`
    knows, then follow up to a handful of same-site links whose text or
    path says meeting/agenda/minutes/video and scan those too -- the
    "Video column / play icon in a meeting's row" case Ryan named.
  * ONLY meetings WITH VIDEO become Archive pages (Ryan's correction,
    2026-09-09, overriding this script's original design below). A
    CivicPlus AgendaCenter -- or any other platform -- with real
    meetings but no video anywhere is never ingested agenda-only; it's
    recorded as `no-video-found`, same as a hub with no meetings at all.
    A government whose hub has agendas but no video anywhere is a fine,
    honest outcome for this sweep, not something to flood the site with
    a video-less page for.

Government identity -- the part the earlier nationwide batches never did
(BACKLOG.md's Branford CT / Hartwick NY entry): every ingest payload
carries the registry row's own `"Name, ST"` as `jurisdiction`. Checked
offline before the run against all 973 rows: `resolve_government()` keys
972 of them to exactly the registry's `gov_id` at tier `registry` (the
one miss is a Michigan township that mints an `rtr:` id). A row whose
string does not key, and every tier-3 queued row (which
`feed_tier3_auto_transcription.py` will re-resolve later WITHOUT this
string), gets a `fallback` pin written to
`app/utils/jurisdiction_data/tenant_overrides.csv` in the existing shapes
-- a plain host pin for a government's own domain, `www.youtube.com` +
the bare video id for a shared host (the shape the 17 existing Phoenix/
Lebanon rows already use). Pins are data inside the image: they take
effect only after a deploy, and for pages that already exist only after
`scripts/backfill_gov_id.py` runs from the Render shell.

Outcomes (one per government, flushed to the report after each row so a
re-run resumes; `--dry-run` resolves and classifies without writing to
the Archive, the queue, or the pins file):

  ingested_tier1_2      real transcript segments (tier 1 source captions,
                        or tier 2 YouTube captions the local fetch could
                        get) -> POST /internal/ingest. Always video-backed.
  queued_tier3          real video, no reachable captions -> appended to
                        tier3_auto_transcription_queue.txt for the cloud
                        auto-transcription worker to drip in later
  already_covered       the meeting (source or video URL) is already an
                        Archive page per the fresh /internal/export/pages
  duplicate_queued      already sitting in the tier-3 queue
  skipped               with a `reject_reason` from the taxonomy in
                        ENUMERATION_METHODS.md section 23:
                        no-video-found (includes a real agenda-only site
                        -- this sweep never ingests agenda-only content),
                        no-meetings-found, no-platform-link-found,
                        dns-unresolvable, resolve-failed,
                        cloudflare-challenge-blocked, off-mission

Politeness: one government at a time, 1.5 s between requests (the
nationwide scripts' precedent), a hard per-government fetch budget and
wall-clock cap, an explicit Cloudflare human-verification gate is
recorded and skipped (never solved -- BACKLOG.md Standing decisions), and
the run halts after a streak of consecutive network-level failures so a
broken uplink can't burn through the list recording false negatives.

Production is HTTP-only: reads through /internal/export/pages, writes
through POST /internal/ingest, no database connection anywhere.

Usage (repo root, shared venv, ARCHIVE_BASE_URL/ARCHIVE_INGEST_TOKEN in .env):
    python scripts/hub_sweep_wo126.py --refresh-export        # pull a fresh export first
    python scripts/hub_sweep_wo126.py --pilot 25              # spread across hub kinds/states
    python scripts/hub_sweep_wo126.py                          # everything not yet in the report
    python scripts/hub_sweep_wo126.py --gov-ids us:place:3684143
    python scripts/hub_sweep_wo126.py --write-pins             # apply staged pins to tenant_overrides.csv
"""

import argparse
import asyncio
import csv
import json
import os
import re
import socket
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

import certifi

# Before `import aiohttp` -- see scripts/transcribe_backlog_locally.py.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import (  # noqa: E402
    CalendarPageError,
    NoVideoCandidateFound,
    UnsupportedPlatformError,
    detect_platform,
    get_finder,
    resolve_via_platform,
)
from app.platforms.civicplus import CivicPlusAssetFinder  # noqa: E402
from app.platforms.granicus_channel import (  # noqa: E402
    _ITEM_RE,
    _item_body_and_clip_url,
)
from app.platforms.models import ResolvedMeeting  # noqa: E402
from app.platforms import queue_probe  # noqa: E402
from app.platforms.youtube import YouTubeAssetFinder  # noqa: E402
from app.utils.gov_registry import registry as gov_registry  # noqa: E402
from app.utils.gov_registry import resolver as gov_resolver  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402
from scripts.bulk_ingest import _base_url, _headers, _ingest  # noqa: E402
from scripts.nationwide_2404_ingest import (  # noqa: E402
    HIGH_RISK_TITLE_PLATFORMS,
    _looks_like_real_meeting,
    _parse_candidate_date,
    civicclerk_latest_event_url,
    pick_calendar_candidate,
    youtube_oembed_title,
)

RESEARCH_DIR = Path("/Users/mroconnell/Documents/rtr-business/research")
REGISTRY_CSV = RESEARCH_DIR / "coverage_registry" / "coverage_registry.csv"
REPORT_CSV = RESEARCH_DIR / "hub_sweep_wo126_report.csv"
PINS_CSV = RESEARCH_DIR / "hub_sweep_wo126_pins.csv"
EXPORT_JSON = RESEARCH_DIR / "hub_sweep_wo126_export_pages.json"
TIER3_QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"
TENANT_OVERRIDES_CSV = (
    REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "tenant_overrides.csv"
)

REQUEST_DELAY_SECONDS = 1.5
FETCH_TIMEOUT = aiohttp.ClientTimeout(total=25)
PER_GOV_FETCH_BUDGET = 12  # hub + follow-ups + AgendaCenter year fragments
# The governing body's last three years, plus a few of the other bodies'
# newest years -- the pilot's 12-fragment walks found no video on any
# advisory-board fragment that the governing body's own years had missed.
MAX_YEAR_FRAGMENTS = 8
PER_GOV_WALL_CLOCK_SECONDS = 240
CONSECUTIVE_NETWORK_FAILURE_HALT = 12
UA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    )
}
PIN_SOURCE = "hub_sweep_wo126"

# Same markers scripts/score_gov_signals.py uses -- a Cloudflare "Verify
# you are human" page is the host saying no automated client, and this
# repo never tries to get past one (BACKLOG.md, Standing decisions).
_CLOUDFLARE_CHALLENGE_MARKERS = (
    "checking your browser before accessing",
    "cf-browser-verification",
    "cf-chl-",
    "just a moment...",
    "attention required! | cloudflare",
)

# Link text/path words that mark a same-site page worth one more hop on
# a non-CivicPlus calendar hub. Deliberately narrow: this is the "find
# the meetings page behind the calendar" step, not a crawl.
_MEETING_HINT_RE = re.compile(
    r"agenda|minutes|meeting|council|commission|board|supervisors|trustees|"
    r"selectboard|aldermen|video|watch|livestream|live stream|broadcast|"
    r"recording|webcast|on demand|archive",
    re.IGNORECASE,
)
_HINT_PATH_RE = re.compile(
    r"agenda|minutes|meeting|video|watch|stream|broadcast|recording|webcast|"
    r"council|commission|board",
    re.IGNORECASE,
)
# Pagination/older-content links on a calendar hub, worth one hop.
_OLDER_HINT_RE = re.compile(
    r"past|previous|older|archive|view all|all events|more events|next",
    re.IGNORECASE,
)
_CHANGE_YEAR_RE = re.compile(r"changeYear\(\s*(\d{4})\s*,\s*(\d+)")
# AgendaCenter categories worth walking first -- the governing body,
# before advisory boards -- when a site has more (year, category) pairs
# than the fetch budget allows.
_PRIMARY_BODY_RE = re.compile(
    r"council|commission(?!er)|supervisors|trustees|aldermen|selectboard|"
    r"select board|freeholders|legislature|assembly|village board|town board|"
    r"city board|county board|board of commissioners|board of directors",
    re.IGNORECASE,
)
# Preferred order when a page links to more than one platform: dedicated
# meeting systems and self-identifying video hosts before the shared
# general-purpose hosts whose links can be anything.
_PLATFORM_PREFERENCE = [
    "granicus",
    "swagit",
    "civicclerk",
    "legistar",
    "escribe",
    "primegov",
    "civicweb",
    "municode_meetings",
    "iqm2",
    "cablecast",
    "telvue",
    "viebit",
    "champds",
    "clerkbase",
    "clerkshq",
    "townhallstreams",
    "castus",
    "invintus",
    "destinyhosted",
    "civicplus",
    "vimeo",
    "youtube",
]

REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "hub_url",
    "hub_kind",
    "prior_reject_reason",
    "platform",
    "outcome",
    "reject_reason",
    "meeting_url",
    "video_url",
    "page_url",
    "title",
    "date",
    "segments",
    "agenda_items",
    "fetches",
    "key_check",
    "pin",
    "youtube_channel_link",
    "detail",
    "checked_at",
]

PIN_FIELDS = ["tenant_host", "match", "gov_id", "strength", "source", "evidence"]


class FetchError(Exception):
    def __init__(self, kind: str, detail: str):
        self.kind = kind  # dns | network | http | cloudflare
        self.detail = detail
        super().__init__(f"{kind}: {detail}")


@dataclass
class Gov:
    gov_id: str
    name: str
    state: str
    hub_url: str
    domain: str
    prior_reject_reason: str

    @property
    def jurisdiction(self) -> str:
        return f"{self.name}, {self.state}"


@dataclass
class Found:
    """A resolvable lead: a URL on a known platform (or a CivicPlus
    agenda row), plus the government page it was found on."""

    url: str
    platform: str
    found_on: str
    title: str = ""
    date: str = ""
    agenda_link: Optional[str] = None
    packet_link: Optional[str] = None
    body: str = ""
    # True when the lead came out of a structured per-meeting listing
    # (a CivicPlus agenda row, a Granicus RSS item) -- meeting context is
    # established by the listing, so the blocklist-only title check
    # applies even for a YouTube/Vimeo link. A bare video-host link
    # found by scanning a page gets the stricter allowlist check.
    structured: bool = False


@dataclass
class Result:
    outcome: str = "skipped"
    reject_reason: str = ""
    platform: str = ""
    meeting_url: str = ""
    video_url: str = ""
    page_url: str = ""
    title: str = ""
    date: str = ""
    segments: int = 0
    agenda_items: int = 0
    key_check: str = ""
    pin: str = ""
    detail: str = ""
    hub_kind: str = ""
    fetches: int = 0
    youtube_channel_link: str = ""


# --------------------------------------------------------------------------
# Input / dedupe index
# --------------------------------------------------------------------------


def select_population() -> List[Gov]:
    with REGISTRY_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        hub = (r.get("hub_url") or "").strip()
        if not hub:
            continue
        if not any(k in hub.lower() for k in ("agendacenter", "calendar")):
            continue
        if (r.get("archive_pages") or "0").strip() != "0":
            continue
        out.append(
            Gov(
                gov_id=r["gov_id"],
                name=r["name"],
                state=r["state"],
                hub_url=hub,
                domain=(r.get("domain") or "").strip(),
                prior_reject_reason=(r.get("reject_reason") or "").strip(),
            )
        )
    return out


def hub_kind_of(hub_url: str) -> str:
    path = urlparse(hub_url).path.lower()
    if "agendacenter" in path:
        return "agendacenter"
    if "calendar.aspx" in path:
        return "civicplus-calendar"
    return "other-calendar"


class DedupeIndex:
    """Everything the Archive already holds, keyed the way
    crud._find_or_create_page() matches -- normalized source URL and
    (platform, external_id) -- plus video URLs, plus what's already
    waiting in the tier-3 queue."""

    def __init__(self, export_path: Path, queue_path: Path):
        self.source_urls: Set[str] = set()
        self.video_urls: Set[str] = set()
        self.ext_ids: Set[Tuple[str, str]] = set()
        self.gov_ids: Dict[str, int] = {}
        if export_path.exists():
            pages = json.loads(export_path.read_text())
            for p in pages:
                if p.get("source_url_normalized"):
                    self.source_urls.add(p["source_url_normalized"])
                if p.get("video_url"):
                    self.video_urls.add(normalize_url(p["video_url"]))
                if p.get("external_id"):
                    self.ext_ids.add((p.get("platform") or "", p["external_id"]))
                if p.get("gov_id"):
                    self.gov_ids[p["gov_id"]] = self.gov_ids.get(p["gov_id"], 0) + 1
        self.queued: Set[str] = set()
        if queue_path.exists():
            for line in queue_path.read_text().splitlines():
                first = line.split("\t", 1)[0].strip()
                if first:
                    self.queued.add(normalize_url(first))

    def covered(self, result: ResolvedMeeting, meeting_url: str) -> Optional[str]:
        for u in (meeting_url, result.source_url):
            if u and normalize_url(u) in self.source_urls:
                return f"source URL already archived: {u}"
        if result.external_id and (result.platform, result.external_id) in self.ext_ids:
            return (
                f"external_id already archived: {result.platform}:{result.external_id}"
            )
        if result.video_url and normalize_url(result.video_url) in self.video_urls:
            return f"video URL already archived: {result.video_url}"
        return None

    def in_queue(self, url: str) -> bool:
        return normalize_url(url) in self.queued


async def refresh_export(path: Path) -> int:
    pages = []
    after = 0
    async with aiohttp.ClientSession() as session:
        while True:
            async with session.get(
                f"{_base_url()}/internal/export/pages",
                params={"after_id": after, "limit": 500},
                headers=_headers(),
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
            pages.extend(data["pages"])
            if not data.get("next_after_id"):
                break
            after = data["next_after_id"]
    path.write_text(json.dumps(pages))
    return len(pages)


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------


class Fetcher:
    """One polite fetcher per government: counts against the budget,
    sleeps between requests, classifies failures."""

    def __init__(self, session: aiohttp.ClientSession, budget: int):
        self.session = session
        self.budget = budget
        self.fetches = 0
        self.network_failures = 0

    async def get(self, url: str) -> Tuple[str, str]:
        """Returns (final_url, html). Raises FetchError."""
        if self.fetches >= self.budget:
            raise FetchError(
                "budget", f"per-government fetch budget of {self.budget} used"
            )
        if self.fetches:
            await asyncio.sleep(REQUEST_DELAY_SECONDS)
        self.fetches += 1
        try:
            async with self.session.get(
                url, headers=UA_HEADERS, timeout=FETCH_TIMEOUT, allow_redirects=True
            ) as resp:
                text = await resp.text(errors="replace")
                if _looks_like_human_verification_gate(text) or (
                    resp.status in (403, 503) and "cloudflare" in text.lower()[:6000]
                ):
                    raise FetchError("cloudflare", f"human-verification gate at {url}")
                if resp.status >= 400:
                    raise FetchError("http", f"HTTP {resp.status} at {url}")
                return str(resp.url), text
        except FetchError:
            raise
        except aiohttp.ClientConnectorError as e:
            if (
                isinstance(e.os_error, socket.gaierror)
                or "nodename nor servname" in str(e)
                or "Name or service not known" in str(e)
            ):
                raise FetchError("dns", f"DNS failed for {urlparse(url).netloc}")
            self.network_failures += 1
            raise FetchError("network", f"connection failed: {e}")
        except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as e:
            self.network_failures += 1
            raise FetchError("network", f"{type(e).__name__}: {e}")


def _looks_like_human_verification_gate(html: str) -> bool:
    lowered = html[:4000].lower()
    return any(m in lowered for m in _CLOUDFLARE_CHALLENGE_MARKERS)


# --------------------------------------------------------------------------
# CivicPlus AgendaCenter deep walk
# --------------------------------------------------------------------------


def _agendacenter_root(url: str) -> str:
    p = urlparse(url)
    return f"{p.scheme}://{p.netloc}/AgendaCenter"


def _year_category_pairs(html: str) -> List[Tuple[int, int, str]]:
    """(year, catID, category label) from the root page's own
    changeYear() anchors -- past years only, governing body first, newest
    year first within a body."""
    labels: Dict[int, str] = {}
    for m in re.finditer(
        r'aria-label="([^"]*?)\s+(\d{4})"[^>]*href="javascript:changeYear\((\d{4}),\s*(\d+)',
        html,
    ):
        labels[int(m.group(4))] = m.group(1).strip()
    pairs = set()
    for m in _CHANGE_YEAR_RE.finditer(html):
        pairs.add((int(m.group(1)), int(m.group(2))))
    out = [(y, c, labels.get(c, "")) for y, c in pairs]
    this_year = datetime.now().year
    # The root page already renders the current year's rows for every
    # category, so only older years are worth a fragment fetch. Governing
    # body first across its last three years, then the other bodies --
    # a site with ten advisory boards must not spend the whole budget on
    # one year of them (Wilmette IL did, in the pilot).
    out = [t for t in out if t[0] < this_year and t[0] >= this_year - 3]
    out.sort(
        key=lambda t: (0 if _PRIMARY_BODY_RE.search(t[2] or "") else 1, -t[0], t[1])
    )
    return out


async def civicplus_walk(
    fetcher: Fetcher, root_url: str, root_html: str, finder: CivicPlusAssetFinder
) -> Tuple[List[dict], int, str]:
    """Every real (title+date) row seen on the root page and on as many
    (year, category) fragments as the budget allows, newest first,
    stopping at the first fragment that carries any video row. Returns
    (rows, fragments_fetched, note)."""
    soup = BeautifulSoup(root_html, "html.parser")
    rows = finder._find_candidate_rows(soup, root_url)
    # `found_on` is the government page recorded as the meeting's source
    # when a bare video-host link is queued/ingested -- the AgendaCenter
    # itself, never the UpdateCategoryList fragment URL (a reader's "View
    # original source" should land on a real page). `seen_in` keeps the
    # fragment for the report.
    for r in rows:
        r["found_on"] = root_url
        r["seen_in"] = root_url
    if any(r["url"] for r in rows):
        return rows, 0, "video row on root page"

    pairs = _year_category_pairs(root_html)
    fragments = 0
    note = ""
    for year, cat_id, label in pairs:
        if fetcher.fetches >= fetcher.budget or fragments >= MAX_YEAR_FRAGMENTS:
            note = f"budget exhausted after {fragments} year fragment(s)"
            break
        frag_url = f"{_agendacenter_root(root_url)}/UpdateCategoryList?year={year}&catID={cat_id}"
        try:
            final_url, html = await fetcher.get(frag_url)
        except FetchError as e:
            if e.kind in ("dns", "cloudflare"):
                raise
            note = f"fragment fetch failed ({e.detail})"
            continue
        fragments += 1
        frag_rows = finder._find_candidate_rows(
            BeautifulSoup(html, "html.parser"), root_url
        )
        for r in frag_rows:
            r["found_on"] = root_url
            r["seen_in"] = frag_url
            r["body"] = label
        rows.extend(frag_rows)
        if any(r["url"] for r in frag_rows):
            note = f"video row in {label or 'category ' + str(cat_id)} {year}"
            break
    if not note:
        note = f"{fragments} year fragment(s) walked, no video row"
    return rows, fragments, note


def _pick_agenda_row(rows: List[dict]) -> Optional[dict]:
    """Newest dated row on/before today that has a real agenda link and a
    title that doesn't look like a non-meeting -- the agenda-only fallback."""
    today = datetime.now()  # local, not UTC -- a 9/10 agenda picked late on 9/9 PT
    dated = []
    for r in rows:
        link = r.get("agenda_link") or ""
        # The downloads cell can also carry a /PreviousVersions/ link
        # (Shelbyville KY, in the pilot) -- only a /ViewFile/ link is the
        # agenda itself.
        if "/viewfile/" not in link.lower():
            continue
        dt = _parse_candidate_date(r.get("date") or "")
        if dt is None or dt > today:
            continue
        if not _looks_like_real_meeting(r.get("title") or ""):
            continue
        dated.append((dt, r))
    if not dated:
        return None
    dated.sort(key=lambda p: p[0], reverse=True)
    # Prefer the governing body among the recent rows (New Baltimore MI's
    # newest row was its Downtown Development Authority, in the pilot),
    # falling back to the newest real meeting of any body.
    for _dt, r in dated[:12]:
        if _PRIMARY_BODY_RE.search(f"{r.get('body') or ''} {r.get('title') or ''}"):
            return r
    return dated[0][1]


# --------------------------------------------------------------------------
# Generic calendar hub: platform links on the hub and one hop beyond
# --------------------------------------------------------------------------

_LINK_TAGS = ("a", "iframe", "video", "source")
_ONCLICK_URL_RE = re.compile(r"""\(\s*['"]([^'"]+)""")


def _platform_links(html: str, page_url: str) -> List[Tuple[str, str]]:
    """Every link on the page to a platform detect_platform() knows, in
    DOM order; YouTube only when the link carries a real video id
    (channel/user/playlist links are recorded separately by the caller)."""
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    out = []
    own = detect_platform(page_url)
    for tag in soup.find_all(_LINK_TAGS):
        values = []
        v = tag.get("href") or tag.get("src")
        if v:
            values.append(v.strip())
        onclick = tag.get("onclick")
        if onclick:
            m = _ONCLICK_URL_RE.search(onclick)
            if m:
                values.append(m.group(1).strip())
        for value in values:
            if not value or value.startswith(("javascript:", "mailto:", "#")):
                continue
            cand = urljoin(page_url, value)
            platform = detect_platform(cand)
            if platform == "unknown" or platform == own:
                continue
            if platform == "youtube" and not YouTubeAssetFinder.extract_video_id(cand):
                continue
            # detect_platform() calls anything on a civicplus host
            # "civicplus", including every tenant's footer link to
            # connect.civicplus.com/referral (403s when resolved -- Sun
            # Prairie WI and Buncombe County NC, in the pilot). Only an
            # AgendaCenter link is a lead.
            if platform == "civicplus" and "agendacenter" not in cand.lower():
                continue
            key = normalize_url(cand)
            if key in seen:
                continue
            seen.add(key)
            out.append((cand, platform))
    return out


def _youtube_channel_link(html: str) -> str:
    m = re.search(
        r'href="(https?://(?:www\.)?youtube\.com/(?:@|channel/|user/|c/)[^"]+)"', html
    )
    return m.group(1) if m else ""


def _hint_links(html: str, page_url: str, limit: int) -> List[str]:
    """Same-site links whose text or path says meeting/agenda/video, plus
    pagination/older-content links, deduped, in DOM order."""
    soup = BeautifulSoup(html, "html.parser")
    host = urlparse(page_url).netloc.lower()
    page_key = normalize_url(page_url)
    seen = set()
    scored: List[Tuple[int, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("javascript:", "mailto:", "#", "tel:")):
            continue
        cand = urljoin(page_url, href)
        p = urlparse(cand)
        if p.netloc.lower() != host:
            continue
        if p.path.lower().endswith((".pdf", ".doc", ".docx", ".jpg", ".png", ".ics")):
            continue
        key = normalize_url(cand)
        if key == page_key or key in seen:
            continue
        text = a.get_text(" ", strip=True)
        label = f"{text} {a.get('title') or ''} {a.get('aria-label') or ''}"
        score = 0
        if "agendacenter" in p.path.lower():
            score = 3
        elif _MEETING_HINT_RE.search(label) or _HINT_PATH_RE.search(p.path):
            score = 2
        elif _OLDER_HINT_RE.search(label) or "page=" in (p.query or "").lower():
            score = 1
        if score:
            seen.add(key)
            scored.append((score, cand))
    scored.sort(key=lambda t: -t[0])
    return [u for _, u in scored[:limit]]


# --------------------------------------------------------------------------
# Resolving a lead through the real adapters
# --------------------------------------------------------------------------

# WO-169 hook: when set, act_on_resolved() calls this for a video-only
# (tier-3, no captions) result BEFORE queuing it, matching every other
# sweep's "probe before queue" rule (docs/BREADTH_SWEEP_BRIEF.md). Returns
# True to accept and queue, False to reject (act_on_resolved() then
# raises ProbeRejected so `_process_gov()`'s lead loop tries the next
# platform instead of ending the government's attempt here). None (the
# default) preserves this module's original behavior exactly -- queue
# immediately, no probe -- so a caller that never sets this is
# unaffected. Signature: async hook(result, queue_url: str) -> bool. See
# scripts/wo169_probe_rejected_rerun.py for the original real hook, and
# _default_probe_hook() below (WO-170) for the one this module's own
# main() now wires by default.
PROBE_HOOK = None


async def _default_probe_hook(result, queue_url: str) -> bool:
    """WO-170 (2026-09-10): the real WO-144 probe, wired on by default in
    this module's own main() -- see PROBE_HOOK's own comment -- reusing
    app.platforms.queue_probe.probe_queue_entry(), the same recipe every
    other probe caller in this repo already uses, and logging to the
    same append-only sidecar (tier3_auto_transcription_queue_probe.csv).

    Ryan's 2026-09-10 rule ("check several videos... prefer 9 to 40
    minutes... if all are over 40 minutes, select the shortest," see
    BACKLOG_DONE.md's WO-170 entry) is implemented in full in
    scripts/wo134_confirmed_hits_ingest.py's own resolve_seed() candidate
    loops, which already depth-search several rows from the same
    listing (PROBE_SELECT_HOOK there). This module's own candidate
    picking (pick_calendar_candidate(), singular -- imported from
    nationwide_2404_ingest.py) only ever surfaces ONE row per listing, so
    there is nothing to select among here yet; this hook degenerates to
    Ryan's rule's floor -- accept a plausible candidate
    (queue_probe.is_plausible(): not dead, not below the 60-second
    floor), reject a dead link or a too-short clip -- rather than
    silently doing nothing. Extending civicplus_walk()/pick_calendar_
    candidate() to try several rows the way wo134's resolve_seed() does
    is real follow-up work, filed to BACKLOG.md rather than built here to
    avoid a larger change to a file with its own active history."""
    probe = await queue_probe.probe_queue_entry(
        queue_url,
        video_url=result.video_url,
        source_page_url=result.source_url or queue_url,
    )
    probe.chosen = queue_probe.is_plausible(probe)
    queue_probe.append_probe_row(queue_probe.DEFAULT_SIDECAR_PATH, probe)
    return queue_probe.is_plausible(probe)


class Skip(Exception):
    """`meeting_url`/`video_url` (WO-169, both default "" -- backward
    compatible with every existing 2-positional-arg raise site) let
    process_gov()'s `except Skip` handler carry real URL evidence onto a
    skipped Result instead of dropping it -- the exact gap WO-151 found:
    Result already had meeting_url/video_url columns, but a Skip's own
    catch site never copied anything onto them, so a real, current
    listing or a real video address was silently lost on every skipped
    row. See Result's own field comments and CLAUDE.md's WO-169 entry."""

    def __init__(
        self,
        reject_reason: str,
        detail: str,
        *,
        meeting_url: str = "",
        video_url: str = "",
    ):
        self.reject_reason = reject_reason
        self.detail = detail
        self.meeting_url = meeting_url
        self.video_url = video_url
        super().__init__(detail)


class ProbeRejected(Skip):
    """Raised when a video-bearing lead resolved real content but failed
    WO-144's queue probe (dead link, or below the meeting-plausibility
    floor) -- a REAL video existed, unlike a plain Skip's "nothing at all
    found." `_process_gov()`'s `for lead in leads:` loop catches this the
    same way it catches any other Skip (moving on to the next lead/
    platform), so raising it here -- instead of act_on_resolved() just
    returning a `rejected_by_probe` Result directly, which used to end
    the whole government's attempt right there -- is what lets a
    DIFFERENT platform lead on the same government still be tried after
    a probe reject. Ryan's 2026-09-10 rule: "a probe reject must move to
    the next candidate, not drop the government." `_apply_skip()` always
    reports the Result's own `outcome` as `rejected_by_probe` for any
    instance of this class regardless of the `reject_reason` string
    passed in -- a caller is free to keep a finer-grained reject_reason
    (e.g. "reject-dead" vs "reject-short", the shape
    wo151_research_url_ladder_sweep.py's probe already produced before
    this class existed) for its own reporting."""


async def granicus_listing_newest_clip(
    session: aiohttp.ClientSession, listing_url: str
) -> Tuple[Optional[str], str]:
    """A Granicus `ViewPublisher.php?view_id=N` link is a listing, not a
    meeting. Its RSS twin (`ViewPublisherRSS.php?view_id=N&mode=video`,
    the feed granicus.py/granicus_channel.py already read) lists every
    archived clip newest-first -- take the newest one whose title passes
    the blocklist."""
    p = urlparse(listing_url)
    view_id = (parse_qs(p.query).get("view_id") or [None])[0]
    if not view_id:
        return None, "no view_id on Granicus listing link"
    rss_url = f"https://{p.netloc}/ViewPublisherRSS.php?view_id={view_id}&mode=video"
    try:
        async with session.get(
            rss_url, headers=UA_HEADERS, timeout=FETCH_TIMEOUT
        ) as resp:
            if resp.status != 200:
                return None, f"Granicus RSS HTTP {resp.status}"
            xml = await resp.text(errors="replace")
    except Exception as e:
        return None, f"Granicus RSS fetch failed: {e}"
    checked = 0
    for m in _ITEM_RE.finditer(xml):
        parsed = _item_body_and_clip_url(m.group(1))
        if not parsed:
            continue
        body, clip_url = parsed
        checked += 1
        if _looks_like_real_meeting(body):
            return clip_url, ""
        if checked >= 8:
            break
    return None, f"Granicus RSS had no usable item ({checked} checked)"


async def resolve_lead(
    session: aiohttp.ClientSession, lead: Found
) -> Tuple[ResolvedMeeting, str, bool]:
    """Resolve one platform URL via its adapter, picking deliberately from
    a listing page's candidates. Returns (result, meeting_url,
    high_risk_title)."""
    platform = lead.platform
    # A CivicPlus AgendaCenter media-column href can carry trailing
    # whitespace straight from the adapter's own row HTML (Columbia IL,
    # in this sweep -- `civicplus.py._find_candidate_rows()` isn't
    # touched here, so strip defensively at the point of use instead).
    url = lead.url.strip()
    if platform == "civicclerk":
        # CivicClerkAssetFinder.resolve() only cares about the numeric
        # event id (`re.search(r"/event/(\d+)", ...)`), so a tenant page
        # that links straight to a specific event's OTHER tabs --
        # `/event/883/files`, seen live on Grant County NM in this
        # sweep -- resolves a real video just fine, but queuing that raw
        # link would put a non-canonical shape in
        # tier3_auto_transcription_queue.txt (this repo's own
        # test_civicclerk_rows_use_the_event_media_shape requires
        # `/event/<id>/media`). Normalize whenever an event id is
        # already present; only fall back to the tenant-wide "latest
        # event" lookup when the link has none at all.
        m = re.search(r"/event/(\d+)", urlparse(url).path)
        if m:
            netloc = urlparse(url).netloc
            url = f"https://{netloc}/event/{m.group(1)}/media"
            lead.structured = True
        else:
            event_url, reason = await civicclerk_latest_event_url(session, url)
            if not event_url:
                raise Skip("no-video-found", f"civicclerk: {reason}", meeting_url=url)
            url = event_url
            lead.structured = True
    if platform == "granicus" and "viewpublisher.php" in urlparse(url).path.lower():
        clip_url, reason = await granicus_listing_newest_clip(session, url)
        if not clip_url:
            raise Skip("no-video-found", f"granicus: {reason}", meeting_url=url)
        url = clip_url
        lead.structured = True
    finder = get_finder(platform)
    try:
        result = await finder.resolve(url)
        high_risk = platform in HIGH_RISK_TITLE_PLATFORMS and not lead.structured
        return result, url, high_risk
    except NoVideoCandidateFound as e:
        raise Skip("no-video-found", f"{platform}: {e}", meeting_url=url)
    except CalendarPageError as e:
        picked, reason = pick_calendar_candidate(e.candidates)
        if not picked:
            raise Skip("off-mission", f"{platform} listing, {reason}", meeting_url=url)
        cand_url = picked["url"]
        try:
            result = await resolve_via_platform(cand_url)
        except CalendarPageError as e2:
            picked2, reason2 = pick_calendar_candidate(e2.candidates)
            if not picked2:
                raise Skip(
                    "off-mission",
                    f"{platform} nested listing, {reason2}",
                    meeting_url=cand_url,
                )
            cand_url = picked2["url"]
            result = await resolve_via_platform(cand_url)
        if e.jurisdiction_hint and not result.jurisdiction:
            result.jurisdiction = e.jurisdiction_hint
        result.title = result.title or picked.get("title")
        result.date = result.date or picked.get("date")
        return result, cand_url, False


# --------------------------------------------------------------------------
# Government identity check and pins
# --------------------------------------------------------------------------


def key_check(gov: Gov, jurisdiction: str, source_url: str) -> Tuple[bool, str]:
    """Would the Archive key a page with this jurisdiction string and
    source URL to the registry row's gov_id? Pure, in-process -- the same
    resolver crud._resolve_page_government() calls."""
    p = urlparse(source_url)
    path = p.path + (f"?{p.query}" if p.query else "")
    m = gov_resolver.resolve_government(
        jurisdiction, tenant_host=p.netloc.lower(), path=path
    )
    ok = m.gov_id == gov.gov_id and m.tier in ("registry", "pinned")
    return ok, f"{m.tier}:{m.gov_id}"


def pin_for(gov: Gov, source_url: str, video_url: str, platform: str) -> Optional[dict]:
    """The tenant_overrides.csv row that would key this page: a plain host
    pin for a page whose source is on the government's own site, or a
    host+video-id pin for a bare shared-host video (the shape the
    existing www.youtube.com rows use). None when the host already has a
    matching row, or when the gov_id has no registry row a pin could
    resolve to."""
    if not gov_registry.government_for_id(gov.gov_id):
        return None
    host = urlparse(source_url).netloc.lower()
    match = ""
    if platform == "youtube" and ("youtube" in host or "youtu.be" in host):
        vid = YouTubeAssetFinder.extract_video_id(video_url or source_url)
        if not vid:
            return None
        host = "www.youtube.com"
        match = vid
    existing = gov_registry.tenant_overrides().get(host) or []
    for row in existing:
        if (row.match or "") == match:
            return None
    return {
        "tenant_host": host,
        "match": match,
        "gov_id": gov.gov_id,
        "strength": "fallback",
        "source": PIN_SOURCE,
        "evidence": (
            f"coverage registry row {gov.gov_id} ({gov.name}, {gov.state}); "
            f"hub {gov.hub_url}; meeting found via {platform} at {source_url}"
        ),
    }


def stage_pin(pin: dict, dry_run: bool) -> None:
    if dry_run:
        return
    is_new = not PINS_CSV.exists()
    with PINS_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=PIN_FIELDS)
        if is_new:
            w.writeheader()
        w.writerow(pin)


def write_pins() -> int:
    """Append the staged pins to tenant_overrides.csv (skipping any
    host+match already present), keeping the file's own sort order."""
    if not PINS_CSV.exists():
        print("no staged pins")
        return 0
    with PINS_CSV.open(newline="", encoding="utf-8") as f:
        staged = list(csv.DictReader(f))
    with TENANT_OVERRIDES_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        existing = list(reader)
    have = {(r["tenant_host"].lower(), r.get("match") or "") for r in existing}
    added = 0
    for p in staged:
        key = (p["tenant_host"].lower(), p.get("match") or "")
        if key in have:
            continue
        have.add(key)
        existing.append({k: p.get(k, "") for k in fields})
        added += 1
    existing.sort(key=lambda r: (r["tenant_host"].lower(), r.get("match") or ""))
    with TENANT_OVERRIDES_CSV.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(existing)
    print(f"{added} pin(s) added to {TENANT_OVERRIDES_CSV} ({len(staged)} staged)")
    return added


# --------------------------------------------------------------------------
# One government
# --------------------------------------------------------------------------


async def _ingest_with_retry(session, payload, normalized) -> Optional[dict]:
    for attempt in (1, 2):
        try:
            return await _ingest(session, payload, normalized)
        except Exception:
            if attempt == 2:
                return None
            await asyncio.sleep(3)
    return None


async def act_on_resolved(
    session: aiohttp.ClientSession,
    gov: Gov,
    lead: Found,
    result: ResolvedMeeting,
    meeting_url: str,
    high_risk: bool,
    index: DedupeIndex,
    res: Result,
    dry_run: bool,
    adapter_jurisdiction: str = "",
) -> Result:
    """Tier, dedupe, title-gate, key-check, then ingest or queue.
    `adapter_jurisdiction` is what the adapter itself extracted, before
    this script overrides it with the registry name -- the tier-3 feed
    will see only that later."""
    segments = result.segments or []
    agenda_items = result.agenda_items or []
    if not (segments or agenda_items or result.agenda_link or result.video_url):
        raise Skip(
            "no-video-found",
            f"{lead.platform}: resolved but no transcript/agenda/video ({meeting_url})",
            meeting_url=meeting_url,
        )

    # Title gate (the nationwide scripts' own, blocklist for structured
    # listings, allowlist-required for a bare YouTube/Vimeo hit).
    effective_title = result.title or lead.title or ""
    if not effective_title and result.video_url:
        effective_title = await youtube_oembed_title(session, result.video_url) or ""
    if not _looks_like_real_meeting(effective_title, require_allowlist=high_risk):
        raise Skip(
            "off-mission",
            f"{lead.platform}: title looks like a non-meeting video: {effective_title!r} ({meeting_url})",
            meeting_url=meeting_url,
            video_url=result.video_url or "",
        )

    covered = index.covered(result, meeting_url)
    if covered:
        res.outcome = "already_covered"
        res.reject_reason = "already-covered"
        res.detail = covered
        return _fill(res, result, meeting_url, effective_title)

    # Government identity: the registry's own name, always. And for a
    # bare video-host link, the government page it was found on is the
    # source a reader should land on (feed_tier3_auto_transcription.py's
    # own source_url-override rule, applied here for direct ingests too).
    result.jurisdiction = gov.jurisdiction
    bare_video_host = lead.platform in HIGH_RISK_TITLE_PLATFORMS
    if bare_video_host and lead.found_on:
        result.source_url = lead.found_on

    if segments:
        ok, tier = key_check(gov, gov.jurisdiction, result.source_url or meeting_url)
        res.key_check = tier
        if not ok:
            pin = pin_for(
                gov,
                result.source_url or meeting_url,
                result.video_url or "",
                lead.platform,
            )
            if pin:
                stage_pin(pin, dry_run)
                res.pin = f"{pin['tenant_host']}|{pin['match']}"
        if dry_run:
            res.outcome = "dry_run_tier1_2"
        else:
            response = await _ingest_with_retry(
                session, result.model_dump(), normalize_url(meeting_url)
            )
            if response is None:
                raise Skip(
                    "resolve-failed",
                    f"{lead.platform}: resolved {len(segments)} segments but POST to Archive failed twice",
                    meeting_url=meeting_url,
                    video_url=result.video_url or "",
                )
            res.page_url = response.get("url") or ""
            res.outcome = "ingested_tier1_2"
            if not response.get("created"):
                res.detail = "matched an EXISTING page, not newly created"
        return _fill(res, result, meeting_url, effective_title)

    if result.video_url:
        if index.in_queue(meeting_url) or index.in_queue(result.video_url):
            res.outcome = "duplicate_queued"
            res.reject_reason = "duplicate-queued"
            res.detail = "already in tier3_auto_transcription_queue.txt"
            return _fill(res, result, meeting_url, effective_title)
        # feed_tier3_auto_transcription.py re-resolves this later without
        # our jurisdiction string, so pre-check what the ADAPTER's own
        # string keys to on the source host it will record, and pin when
        # that isn't the registry's government.
        # A bare YouTube/Vimeo link scraped directly off a hub page can
        # carry raw HTML-template query-string garbage the adapter's own
        # video_url normalization already stripped -- Carter Lake IA (in
        # this sweep) linked an <iframe src> embed URL with 13 player-
        # config params and a literal trailing "&" from the page's own
        # template, which the repo's own queue-file whitespace/dangling-
        # separator tests correctly reject. Queue the adapter's clean
        # form for these two platforms; civicclerk/granicus/etc. keep
        # `meeting_url` since their own `result.video_url` is a raw
        # media-stream URL, not the re-resolvable page.
        queue_url = (
            result.video_url if bare_video_host and result.video_url else meeting_url
        )
        source_override = lead.found_on if bare_video_host else ""
        host_url = source_override or result.source_url or meeting_url
        ok, tier = key_check(gov, adapter_jurisdiction, host_url)
        res.key_check = f"adapter:{tier}"
        if not ok:
            pin = pin_for(gov, host_url, result.video_url, lead.platform)
            if pin:
                stage_pin(pin, dry_run)
                res.pin = f"{pin['tenant_host']}|{pin['match']}"

        # WO-169: probe before queue, same rule as every other sweep
        # (docs/BREADTH_SWEEP_BRIEF.md's "probe before queuing"). PROBE_HOOK
        # is None by default -- see its own comment -- so a caller that
        # never sets it keeps this function's original behavior exactly
        # (queue immediately, no probe). On a reject, raise ProbeRejected
        # instead of queuing: `_process_gov()`'s `for lead in leads:` loop
        # catches any Skip subclass and moves on to the NEXT lead (a
        # different platform found on the same government's page) rather
        # than ending the government's attempt here -- Ryan's "take the
        # next candidate, only report rejected_by_probe once leads are
        # exhausted" rule.
        if PROBE_HOOK is not None and not await PROBE_HOOK(result, queue_url):
            raise ProbeRejected(
                "rejected_by_probe",
                f"{lead.platform}: resolved real video but it failed WO-144's "
                f"queue probe ({queue_url})",
                meeting_url=meeting_url,
                video_url=result.video_url or "",
            )

        line = f"{queue_url}\t{source_override}" if source_override else queue_url
        if dry_run:
            res.outcome = "dry_run_tier3"
        else:
            with TIER3_QUEUE_FILE.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            index.queued.add(normalize_url(queue_url))
            res.outcome = "queued_tier3"
        res.reject_reason = "video-no-captions-queued"
        res.detail = "real video, no captions -- appended to tier3_auto_transcription_queue.txt (cloud auto-transcription)"
        return _fill(res, result, meeting_url, effective_title)

    # Agenda only -- no video anywhere. Ryan's correction (2026-09-09):
    # only meetings WITH VIDEO become Archive pages, so this is never
    # ingested, no matter how real/complete the agenda is. Record it the
    # same way a hub with no meetings at all is recorded, so
    # jurisdiction_coverage.csv gets an honest no-video-found.
    raise Skip(
        "no-video-found",
        f"{lead.platform}: resolved a real agenda/meeting record but no video "
        f"anywhere ({meeting_url}) -- agenda-only is never ingested by this sweep",
        meeting_url=meeting_url,
    )


def _fill(res: Result, result: ResolvedMeeting, meeting_url: str, title: str) -> Result:
    res.platform = result.platform or res.platform
    res.meeting_url = meeting_url
    res.video_url = result.video_url or ""
    res.title = title or result.title or ""
    res.date = result.date or ""
    res.segments = len(result.segments or [])
    res.agenda_items = len(result.agenda_items or [])
    return res


def _agenda_only_meeting(gov: Gov, row: dict) -> ResolvedMeeting:
    """A CivicPlus agenda row with no video anywhere on the site, as a
    real per-meeting page keyed to its own ViewFile link."""
    return ResolvedMeeting(
        platform="civicplus",
        source_url=row["agenda_link"],
        title=row["title"],
        date=row["date"],
        jurisdiction=gov.jurisdiction,
        meeting_body=(row.get("body") or None),
        agenda_link=row["agenda_link"],
        packet_link=row.get("packet_link"),
    )


def _apply_skip(res: Result, e: Skip) -> Result:
    """Copies a Skip's reject_reason/detail/meeting_url/video_url onto a
    skipped Result -- the shared WO-169 fix for the "URLs dropped on
    skip" gap (see Skip's own docstring: Result already had these
    columns, nothing ever copied a Skip's own evidence onto them) -- and
    applies WO-164's video-without-meeting tag when it fits: a real video
    existed but no meeting/listing evidence did
    (docs/BREADTH_SWEEP_BRIEF.md's "Reject reasons, two classes";
    ~/Documents/rtr-business/research/wo164_retag_rules.md's rule 1).
    `ProbeRejected` gets its own `rejected_by_probe` outcome rather than
    `skipped` -- see that class's own docstring. Shared by this module's
    own process_gov() and every driver that reuses hs.Skip/hs._process_gov
    directly (wo151_research_url_ladder_sweep.py) so the same rule
    applies everywhere, not just here."""
    res.outcome = "rejected_by_probe" if isinstance(e, ProbeRejected) else "skipped"
    res.reject_reason = e.reject_reason
    res.detail = e.detail
    res.meeting_url = e.meeting_url or res.meeting_url
    res.video_url = e.video_url or res.video_url
    if res.outcome == "skipped" and res.video_url and not res.meeting_url:
        res.reject_reason = "video-without-meeting"
    return res


async def process_gov(
    session: aiohttp.ClientSession,
    gov: Gov,
    index: DedupeIndex,
    finder: CivicPlusAssetFinder,
    dry_run: bool,
) -> Tuple[Result, int]:
    fetcher = Fetcher(session, PER_GOV_FETCH_BUDGET)
    res = Result(hub_kind=hub_kind_of(gov.hub_url))
    try:
        res = await _process_gov(fetcher, session, gov, index, finder, res, dry_run)
    except Skip as e:
        res = _apply_skip(res, e)
    except FetchError as e:
        res.outcome = "skipped"
        res.reject_reason = {
            "dns": "dns-unresolvable",
            "cloudflare": "cloudflare-challenge-blocked",
        }.get(e.kind, "resolve-failed")
        res.detail = e.detail
    res.fetches = fetcher.fetches
    return res, fetcher.network_failures


async def _process_gov(
    fetcher: Fetcher,
    session: aiohttp.ClientSession,
    gov: Gov,
    index: DedupeIndex,
    finder: CivicPlusAssetFinder,
    res: Result,
    dry_run: bool,
) -> Result:
    hub_final, hub_html = await fetcher.get(gov.hub_url)
    res.youtube_channel_link = _youtube_channel_link(hub_html)

    # A hub that redirects straight onto a real platform (e.g. a
    # /calendar that 301s to Granicus) is itself the lead.
    hub_platform = detect_platform(hub_final)
    leads: List[Found] = []
    civicplus_rows: List[dict] = []
    civicplus_note = ""

    is_agendacenter = (
        "catAgendaRow" in hub_html or "agendacenter" in urlparse(hub_final).path.lower()
    )
    is_civicplus_site = (
        is_agendacenter
        or "civicplus" in hub_html.lower()
        or "/agendacenter" in hub_html.lower()
    )

    if hub_platform not in ("unknown", "civicplus"):
        leads.append(Found(hub_final, hub_platform, gov.hub_url))
    elif is_civicplus_site:
        res.hub_kind = res.hub_kind if is_agendacenter else "civicplus-calendar"
        root_url = hub_final if is_agendacenter else _agendacenter_root(hub_final)
        root_html = hub_html
        if not is_agendacenter:
            try:
                root_url, root_html = await fetcher.get(root_url)
            except FetchError as e:
                if e.kind in ("dns", "cloudflare"):
                    raise
                root_html = ""
        if root_html and ("catAgendaRow" in root_html or "changeYear(" in root_html):
            civicplus_rows, fragments, civicplus_note = await civicplus_walk(
                fetcher, root_url, root_html, finder
            )
            video_rows = [r for r in civicplus_rows if r["url"]]
            if video_rows:
                picked, reason = pick_calendar_candidate(video_rows)
                if not picked and len(video_rows) == 1:
                    picked = video_rows[0]
                if picked:
                    leads.append(
                        Found(
                            picked["url"],
                            detect_platform(picked["url"]),
                            picked["found_on"],
                            title=picked["title"],
                            date=picked["date"],
                            agenda_link=picked.get("agenda_link"),
                            packet_link=picked.get("packet_link"),
                            body=picked.get("body") or "",
                            structured=True,
                        )
                    )
                else:
                    res.detail = f"civicplus video rows all declined: {reason}"
        # Even a CivicPlus site can put its meeting videos somewhere other
        # than the AgendaCenter media column -- scan the hub too.
        for url, platform in _platform_links(hub_html, hub_final):
            leads.append(Found(url, platform, hub_final))

    if not leads and not civicplus_rows:
        # Generic calendar: platform links on the hub, then one hop.
        for url, platform in _platform_links(hub_html, hub_final):
            leads.append(Found(url, platform, hub_final))
        if not leads:
            hop_budget = min(6, fetcher.budget - fetcher.fetches)
            for hop in _hint_links(hub_html, hub_final, hop_budget):
                try:
                    hop_final, hop_html = await fetcher.get(hop)
                except FetchError as e:
                    if e.kind in ("dns", "cloudflare"):
                        raise
                    continue
                if not res.youtube_channel_link:
                    res.youtube_channel_link = _youtube_channel_link(hop_html)
                if "catAgendaRow" in hop_html:
                    rows, _f, civicplus_note = await civicplus_walk(
                        fetcher, hop_final, hop_html, finder
                    )
                    civicplus_rows.extend(rows)
                    video_rows = [r for r in rows if r["url"]]
                    picked, _r = pick_calendar_candidate(video_rows)
                    if not picked and len(video_rows) == 1:
                        picked = video_rows[0]
                    if picked:
                        leads.append(
                            Found(
                                picked["url"],
                                detect_platform(picked["url"]),
                                picked["found_on"],
                                title=picked["title"],
                                date=picked["date"],
                                agenda_link=picked.get("agenda_link"),
                                packet_link=picked.get("packet_link"),
                                body=picked.get("body") or "",
                                structured=True,
                            )
                        )
                        res.hub_kind = "other-calendar->agendacenter"
                for url, platform in _platform_links(hop_html, hop_final):
                    leads.append(Found(url, platform, hop_final))
                if leads:
                    break

    # Try leads in platform-preference order, first real content wins.
    leads.sort(
        key=lambda f: (
            _PLATFORM_PREFERENCE.index(f.platform)
            if f.platform in _PLATFORM_PREFERENCE
            else len(_PLATFORM_PREFERENCE)
        )
    )
    last_skip: Optional[Skip] = None
    # WO-169: the first ProbeRejected seen across every lead, tracked
    # separately so it survives even if a LATER lead's plain Skip (a
    # weaker "nothing at all found" signal) would otherwise overwrite
    # `last_skip` last -- a real video existing beats no video existing,
    # same priority order as wo134_confirmed_hits_ingest.process_row()'s
    # best_probe_rejected_result.
    probe_rejected_skip: Optional[ProbeRejected] = None
    tried = 0
    for lead in leads:
        if tried >= 4:
            break
        tried += 1
        res.platform = lead.platform
        try:
            get_finder(lead.platform)
        except UnsupportedPlatformError:
            continue
        try:
            result, meeting_url, high_risk = await resolve_lead(session, lead)
        except Skip as e:
            last_skip = e
            if isinstance(e, ProbeRejected) and probe_rejected_skip is None:
                probe_rejected_skip = e
            continue
        except Exception as e:  # adapter raised
            last_skip = Skip("resolve-failed", f"{lead.platform}: resolve raised: {e}")
            continue
        if lead.agenda_link and not result.agenda_link:
            result.agenda_link = lead.agenda_link
        if lead.packet_link and not result.packet_link:
            result.packet_link = lead.packet_link
        if lead.body and not result.meeting_body:
            result.meeting_body = lead.body
        result.title = result.title or lead.title or None
        result.date = result.date or lead.date or None
        adapter_jurisdiction = result.jurisdiction or ""
        try:
            return await act_on_resolved(
                session,
                gov,
                lead,
                result,
                meeting_url,
                high_risk,
                index,
                res,
                dry_run,
                adapter_jurisdiction=adapter_jurisdiction,
            )
        except Skip as e:
            last_skip = e
            if isinstance(e, ProbeRejected) and probe_rejected_skip is None:
                probe_rejected_skip = e
            continue

    # No lead produced content. CivicPlus agenda-only fallback.
    if civicplus_rows:
        agenda_row = _pick_agenda_row(civicplus_rows)
        if agenda_row:
            lead = Found(
                agenda_row["agenda_link"],
                "civicplus",
                agenda_row["found_on"],
                title=agenda_row["title"],
                date=agenda_row["date"],
                agenda_link=agenda_row["agenda_link"],
                packet_link=agenda_row.get("packet_link"),
                body=agenda_row.get("body") or "",
                structured=True,
            )
            meeting = _agenda_only_meeting(gov, agenda_row)
            res.platform = "civicplus"
            res.detail = civicplus_note
            return await act_on_resolved(
                session,
                gov,
                lead,
                meeting,
                agenda_row["agenda_link"],
                False,
                index,
                res,
                dry_run,
            )
        raise Skip(
            "no-video-found",
            f"civicplus: {len(civicplus_rows)} real row(s), none with video or a usable agenda link; {civicplus_note}",
            meeting_url=civicplus_rows[0].get("found_on") or gov.hub_url,
        )

    if probe_rejected_skip:
        raise probe_rejected_skip
    if last_skip:
        raise last_skip
    if is_civicplus_site:
        raise Skip(
            "no-meetings-found",
            f"civicplus site, AgendaCenter had no real (title+date) rows; {civicplus_note or 'root only'}",
            meeting_url=gov.hub_url,
        )
    raise Skip(
        "no-platform-link-found",
        f"no known-platform link on the hub or {fetcher.fetches - 1} hinted page(s)",
        meeting_url=gov.hub_url,
    )


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


def _done_gov_ids() -> Set[str]:
    if not REPORT_CSV.exists():
        return set()
    with REPORT_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f) if r.get("outcome")}


def _pilot_spread(govs: List[Gov], n: int) -> List[Gov]:
    """Every-kth row after sorting by (hub kind, state) -- a spread across
    platforms and states, deterministic, no hand-picking."""
    ordered = sorted(govs, key=lambda g: (hub_kind_of(g.hub_url), g.state, g.gov_id))
    if n >= len(ordered):
        return ordered
    step = len(ordered) / n
    return [ordered[int(i * step)] for i in range(n)]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument(
        "--pilot", type=int, help="spread of N governments across hub kinds/states"
    )
    ap.add_argument("--gov-ids", nargs="*")
    ap.add_argument("--start-after")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--refresh-export", action="store_true")
    ap.add_argument("--write-pins", action="store_true")
    ap.add_argument(
        "--no-probe",
        action="store_true",
        help="disable the WO-144/WO-170 probe before queuing a tier-3 candidate",
    )
    args = ap.parse_args()

    if args.write_pins:
        write_pins()
        return

    if not _base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print("ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set", file=sys.stderr)
        sys.exit(1)

    if args.refresh_export or not EXPORT_JSON.exists():
        n = await refresh_export(EXPORT_JSON)
        print(f"export refreshed: {n} pages -> {EXPORT_JSON}")

    # WO-170: on by default for a direct run of this pipeline -- see
    # PROBE_HOOK's own comment and _default_probe_hook()'s. A caller that
    # imports this module and sets its own PROBE_HOOK
    # (wo151_research_url_ladder_sweep.py) is unaffected, since main() is
    # never what that script calls.
    global PROBE_HOOK
    if not args.no_probe:
        PROBE_HOOK = _default_probe_hook

    register_all_finders()
    finder = CivicPlusAssetFinder()
    index = DedupeIndex(EXPORT_JSON, TIER3_QUEUE_FILE)
    govs = select_population()
    done = _done_gov_ids()
    print(f"{len(govs)} governments in population, {len(done)} already in report")

    if args.gov_ids:
        wanted = set(args.gov_ids)
        todo = [g for g in govs if g.gov_id in wanted]
    else:
        todo = [g for g in govs if g.gov_id not in done]
        if args.pilot:
            todo = _pilot_spread(todo, args.pilot)
        if args.start_after:
            seen = False
            kept = []
            for g in todo:
                if seen:
                    kept.append(g)
                if g.gov_id == args.start_after:
                    seen = True
            todo = kept
        if args.limit:
            todo = todo[: args.limit]
    print(
        f"processing {len(todo)} against {_base_url()}{' (DRY RUN)' if args.dry_run else ''}\n"
    )

    is_new = not REPORT_CSV.exists()
    report_f = REPORT_CSV.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(report_f, fieldnames=REPORT_FIELDS)
    if is_new:
        writer.writeheader()
        report_f.flush()

    tally: Dict[str, int] = {}
    streak = 0
    try:
        async with aiohttp.ClientSession() as session:
            for i, gov in enumerate(todo):
                started = datetime.now()
                try:
                    res, net_failures = await asyncio.wait_for(
                        process_gov(session, gov, index, finder, args.dry_run),
                        timeout=PER_GOV_WALL_CLOCK_SECONDS,
                    )
                except asyncio.TimeoutError:
                    res = Result(
                        outcome="skipped",
                        reject_reason="resolve-failed",
                        detail=f"per-government wall clock of {PER_GOV_WALL_CLOCK_SECONDS}s exceeded",
                        hub_kind=hub_kind_of(gov.hub_url),
                    )
                    net_failures = 1
                except Exception as e:
                    res = Result(
                        outcome="skipped",
                        reject_reason="resolve-failed",
                        detail=f"unhandled: {type(e).__name__}: {e}",
                        hub_kind=hub_kind_of(gov.hub_url),
                    )
                    net_failures = 0
                streak = streak + 1 if (net_failures and res.fetches <= 1) else 0
                row = {
                    "gov_id": gov.gov_id,
                    "name": gov.name,
                    "state": gov.state,
                    "hub_url": gov.hub_url,
                    "hub_kind": res.hub_kind,
                    "prior_reject_reason": gov.prior_reject_reason,
                    "platform": res.platform,
                    "outcome": res.outcome,
                    "reject_reason": res.reject_reason,
                    "meeting_url": res.meeting_url,
                    "video_url": res.video_url,
                    "page_url": res.page_url,
                    "title": res.title,
                    "date": res.date,
                    "segments": res.segments,
                    "agenda_items": res.agenda_items,
                    "fetches": res.fetches,
                    "key_check": res.key_check,
                    "pin": res.pin,
                    "youtube_channel_link": res.youtube_channel_link,
                    "detail": res.detail[:400],
                    "checked_at": datetime.now(timezone.utc).strftime(
                        "%Y-%m-%dT%H:%M:%SZ"
                    ),
                }
                if not args.dry_run:
                    writer.writerow(row)
                    report_f.flush()
                key = (
                    res.outcome
                    if res.outcome != "skipped"
                    else f"skipped:{res.reject_reason}"
                )
                tally[key] = tally.get(key, 0) + 1
                picked = (
                    f" | {res.date} {res.title[:60]!r} {res.meeting_url}"
                    if res.meeting_url
                    else ""
                )
                elapsed = (datetime.now() - started).total_seconds()
                print(
                    f"[{key:34}] {gov.gov_id} {gov.name}, {gov.state} "
                    f"{res.platform or '-'} f={res.fetches} {elapsed:.0f}s "
                    f"key={res.key_check or '-'} -- {res.detail[:140]}{picked}"
                )
                if streak >= CONSECUTIVE_NETWORK_FAILURE_HALT:
                    print(
                        f"\nHALT: {streak} consecutive network-level failures -- "
                        "check the uplink before continuing (re-run resumes)."
                    )
                    break
                if i < len(todo) - 1:
                    await asyncio.sleep(REQUEST_DELAY_SECONDS)
    finally:
        report_f.close()

    print("\n--- tally (this run) ---")
    for k, v in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"{k:36} {v}")
    print(f"\nreport: {REPORT_CSV}\npins staged: {PINS_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
