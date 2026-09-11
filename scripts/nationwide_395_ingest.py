"""One-off batch ingest for rtr-business/research/nationwide_two_hop_confirmed_395.csv.

395 governments with NO existing coverage in jurisdiction_coverage.csv,
each confirmed (by a separate research pass) to have a real link -- on
their homepage or one hop deeper -- to a platform this project already
has an adapter for. `hit_source_urls` in that CSV records exactly which
government page the platform signature was found on (format
"platform=url;platform2=url2"), often not the homepage.

This script reuses the SAME resolve pipeline bulk_ingest.py and
feed_tier3_auto_transcription.py already use (app/platforms/base.py's
detect_platform()/get_finder(), the real POST /internal/ingest), but adds
the "find the specific meeting" step that was missing from a blind bulk
resolve -- see rtr-business/research/ENUMERATION_METHODS.md's "Step 2's
real weak spot" section for the real bug this is guarding against (a
promo video and an instructional video ingested as real meetings, a
"most recent" pick drifting between a dry run and a real run, one video
creating two live pages). Concretely:

  - hit_source_url is a page ON THE GOVERNMENT'S OWN SITE, not
    necessarily a URL on the platform's own domain -- for CivicPlus
    specifically the whole gov site can BE the CivicPlus install
    (white-labeled), but for every domain-hosted platform (Legistar,
    CivicClerk, Granicus, Vimeo, YouTube, ...) the real platform link has
    to be found by scanning that government page's HTML (and a handful of
    the CSV's own `hop2_urls` as a fallback) -- see find_specific_platform_link().
  - Once on the platform's own domain, `CalendarPageError`'s real
    candidate list (title/date/url) -- civicplus.py, legistar.py,
    municode_meetings.py, vimeo.py all raise this for a listing page with
    more than one meeting -- is used to pick deliberately: most recent
    candidate whose title doesn't look like a promo/instructional/non-
    meeting video and does look like a real governing-body meeting. A
    genuinely ambiguous page (nothing recent looks like a real meeting)
    is skipped and logged, never forced.
  - CivicClerk needs a real `/event/{id}` URL (a bare tenant link 404s
    the adapter with a ValueError, not CalendarPageError) -- resolved via
    the same tenant Events OData listing find_tier3_short_meeting_
    substitutes.py already uses (`{subdomain}.api.civicclerk.com/v1/
    Events?$orderby=startDateTime desc`), newest real (past, has-media)
    event first.
  - Resolution and action happen in the SAME pass, one row at a time --
    no separate dry-run-then-real-run gap -- specifically to avoid the
    documented "most recent" pick drifting between two runs.
  - Tier 1/2 (real segments) -> ingested for real via POST /internal/ingest,
    exactly bulk_ingest.py's own _ingest(). Tier 3 (real video_url, no
    segments) -> appended to scripts/tier3_auto_transcription_queue.txt,
    exactly the shape feed_tier3_auto_transcription.py already drains --
    NOT ingested directly, per that script's own documented reasoning.
    Server-side dedup (archive/db/crud.py's _find_or_create_page, keyed on
    platform+external_id/normalized source_url) is the real fix for the
    "same video, two live pages" bug already; this script also keeps an
    in-process seen-set as a second, cheap guard within one run.

Writes a per-row CSV log to rtr-business/research/nationwide_395_ingest_log.csv
(resumable: rows already present for a given gov_id are skipped on a
re-run) and prints a final tally.

Usage (from repo root, venv active):
    python scripts/nationwide_395_ingest.py
    python scripts/nationwide_395_ingest.py --limit 20        # smoke test
    python scripts/nationwide_395_ingest.py --start-after us:county:53011
"""

import argparse
import asyncio
import csv
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
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
from app.utils.url_normalize import normalize_url  # noqa: E402
from scripts.bulk_ingest import _base_url, _ingest  # noqa: E402

RESEARCH_DIR = Path("/Users/mroconnell/Documents/rtr-business/research")
INPUT_CSV = RESEARCH_DIR / "nationwide_two_hop_confirmed_395.csv"
LOG_CSV = RESEARCH_DIR / "nationwide_395_ingest_log.csv"
TIER3_QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"

REQUEST_DELAY_SECONDS = 1.5
FETCH_TIMEOUT = aiohttp.ClientTimeout(total=25)
UA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    )
}

# Platforms this CSV can name that have NO real adapter in this repo --
# confirmed by reading app/platforms/base.py's detect_platform() and the
# app/platforms/ directory listing: no boarddocs.py or
# municipalcodeonline.py file exists, and neither domain is registered in
# detect_platform(). scripts/adhoc_school_district_platform_scan.py's own
# PLATFORM_SIGNATURES comment confirms this is deliberate for BoardDocs
# ("no video adapter") -- these are agenda/document CMSes, not meeting-
# video platforms this project can resolve.
UNSUPPORTED_PLATFORMS = {"boarddocs", "municipalcodeonline"}

# Real governing-body words -- reused from granicus.py's own
# GOVERNING_BODY_KEYWORDS plus the obvious siblings other adapters'
# fixtures show in real titles (assembly/authority/trustees/hearing).
MEETING_ALLOWLIST = (
    "council",
    "commission",
    "board",
    "committee",
    "meeting",
    "session",
    "hearing",
    "authority",
    "trustees",
    "supervisors",
    "assembly",
    "selectboard",
    "select board",
)
# Real, confirmed-live false-positive shapes this is guarding against --
# see this file's module docstring and ENUMERATION_METHODS.md's "Step 2's
# real weak spot" section (a promo video, an instructional video, both
# ingested as if they were real meetings).
PROMO_BLOCKLIST = (
    "promo",
    "advertisement",
    "commercial",
    "psa",
    "public service announcement",
    "how to",
    "tutorial",
    "instructional",
    "training video",
    "orientation video",
    "welcome",
    "message from the mayor",
    "highlight reel",
    "sizzle reel",
    "ribbon cutting",
    "parade",
    "test stream",
    "test broadcast",
    "sample video",
    "demo video",
    "career",
    "job fair",
    "recruitment",
    "state of the city",
    "year in review",
    "commercial break",
    "tour of",
)

HOP2_FETCH_CAP = 4  # how many hop2_urls to try fetching per row before giving up


@dataclass
class RowResult:
    gov_id: str
    unit_name: str
    platform: str
    outcome: str  # ingested_tier1_2 | queued_tier3 | ingested_agenda_only | skipped
    reason: str
    seed_url: str = ""
    title: str = ""
    date: str = ""
    page_url: str = ""


def _read_csv_rows(path: Path) -> List[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _parse_hit_source_urls(raw: str) -> List[Tuple[str, str]]:
    pairs = []
    for chunk in (raw or "").split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        platform, _, url = chunk.partition("=")
        platform = platform.strip()
        url = url.strip()
        if platform and url:
            pairs.append((platform, url))
    return pairs


def _already_logged_gov_ids(path: Path) -> set:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {row["gov_id"] for row in csv.DictReader(f)}


def _log_writer(path: Path):
    fields = [
        "gov_id",
        "unit_name",
        "platform",
        "outcome",
        "reason",
        "seed_url",
        "title",
        "date",
        "page_url",
    ]
    is_new = not path.exists()
    f = path.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=fields)
    if is_new:
        writer.writeheader()
        f.flush()
    return f, writer


async def fetch_html(
    session: aiohttp.ClientSession, url: str
) -> Tuple[Optional[str], Optional[str]]:
    try:
        async with session.get(
            url, headers=UA_HEADERS, timeout=FETCH_TIMEOUT, allow_redirects=True
        ) as resp:
            if resp.status >= 400:
                return None, None
            final_url = str(resp.url)
            html = await resp.text(errors="replace")
            return final_url, html
    except Exception:
        return None, None


_ONCLICK_URL_RE = re.compile(r"""\(\s*['"]([^'"]+)""")
_TAGS = ("a", "iframe", "video", "source")


def find_specific_platform_link(
    html: str, page_url: str, target_platform: str
) -> Optional[str]:
    """Like base.py's find_platform_link(), but filtered to ONE target
    platform rather than "any known platform" -- this script already
    knows which platform the CSV's own two-hop scan confirmed, so a
    match against a DIFFERENT known platform (e.g. a stray YouTube footer
    icon on a page being scanned for a Legistar link) should keep
    scanning, not return early. See base.py's find_platform_link()
    docstring for the same-page-anchor / same-platform-internal-nav traps
    this mirrors."""
    soup = BeautifulSoup(html, "html.parser")
    page_url_no_frag = urlparse(page_url)._replace(fragment="").geturl()
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
            if not value:
                continue
            candidate = urljoin(page_url, value)
            if urlparse(candidate)._replace(fragment="").geturl() == page_url_no_frag:
                continue
            if detect_platform(candidate) == target_platform:
                return candidate
    return None


_YT_ID_RE = re.compile(r"(?:v=|/embed/|/live/|youtu\.be/)([A-Za-z0-9_-]{11})")


async def youtube_oembed_title(
    session: aiohttp.ClientSession, video_url: str
) -> Optional[str]:
    """Real, confirmed-live gap found running this script 2026-09-07: this
    environment's yt-dlp calls are being blocked ("YouTube is currently
    blocking automated caption requests from our server") even from the
    residential IP this run is on (see this file's module docstring's IP
    check) -- resolve_video_id() degrades gracefully (still returns a
    playable video_url) but BOTH title and date come back None, which
    would otherwise defeat _looks_like_real_meeting()'s title check
    entirely (an empty string matches no blocklist term). YouTube's
    plain oEmbed endpoint (no auth, meant for embedding, confirmed live
    to still return a real title -- e.g. "Board of Equalization",
    "September 1, 2026 City Council Meeting" -- for 3 real videos this
    run's yt-dlp call had just failed on) is a working substitute for
    THIS validation purpose only; not used to overwrite what actually
    gets sent to /internal/ingest, which stays exactly what the real
    adapter produced, same as bulk_ingest.py."""
    m = _YT_ID_RE.search(video_url)
    if not m:
        return None
    video_id = m.group(1)
    try:
        async with session.get(
            "https://www.youtube.com/oembed",
            params={
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "format": "json",
            },
            headers=UA_HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)
            return data.get("title")
    except Exception:
        return None


def _looks_like_real_meeting(title: str, *, require_allowlist: bool = False) -> bool:
    """require_allowlist=True is the stricter check, for the highest-risk
    case: a single video found via a generic scan of a general-purpose
    video host's page (YouTube/Vimeo), with no structured per-meeting
    listing backing it up. Real, confirmed-live gap found running this
    script 2026-09-07, AFTER the blocklist-only check already caught
    Grandview WA's promo video: a blocklist alone missed Colfax, WA's
    real queued title, "Colfax, Washington on the Palouse Scenic Byway"
    (a tourism video) -- no blocklist word describes every way a non-
    meeting video can be titled, so for this specific risk class the
    check is flipped to require a real meeting signal (GOVERNING_BODY-
    style keyword) rather than just the absence of a bad one. NOT applied
    to CivicPlus/CivicClerk/Legistar/Municode Meetings candidates -- those
    already come from a real per-meeting agenda/events system by
    construction (a candidate row IS a meeting record, even when its own
    title is generic, e.g. CivicPlus's own "Untitled meeting" default),
    so requiring a keyword there would wrongly reject real meetings."""
    t = (title or "").lower()
    if any(b in t for b in PROMO_BLOCKLIST):
        return False
    if require_allowlist and not any(kw in t for kw in MEETING_ALLOWLIST):
        return False
    return True


def _parse_candidate_date(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    date_str = date_str.strip()
    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(
                date_str[:10] if fmt == "%Y-%m-%d" else date_str, fmt
            )
        except ValueError:
            continue
    return None


def pick_calendar_candidate(candidates: List[dict]) -> Tuple[Optional[dict], str]:
    """Deliberate pick, never "whatever's first". Most recent candidate,
    strictly on/before today, whose title doesn't match PROMO_BLOCKLIST.
    Declines (returns None, reason) rather than guessing when nothing in
    the recent window looks like a real meeting -- see this file's module
    docstring for the bug this is guarding against."""
    if not candidates:
        return None, "no candidates"

    today = datetime.now(timezone.utc).replace(tzinfo=None)
    dated = []
    undated = []
    for c in candidates:
        dt = _parse_candidate_date(c.get("date") or "")
        if dt is None:
            undated.append(c)
        elif dt <= today:
            dated.append((dt, c))
    dated.sort(key=lambda pair: pair[0], reverse=True)

    # Walk newest-first; accept the first one that doesn't look like a
    # promo/instructional/non-meeting video. Check the top 8 at most --
    # beyond that the page is either huge (fine, there's still a good
    # pick near the top) or every recent row is genuinely suspicious.
    for dt, c in dated[:8]:
        if _looks_like_real_meeting(c.get("title") or ""):
            return c, ""

    # No dated candidate looked clean. If there's exactly one candidate
    # total (dated-but-blocked, or undated) and it passes the title
    # check, still allow it -- a single real per-meeting agenda row
    # (CivicPlus/Municode's own structured listings) shouldn't be
    # penalized for an unparseable date format.
    if len(candidates) == 1 and _looks_like_real_meeting(
        candidates[0].get("title") or ""
    ):
        return candidates[0], ""

    top_titles = [c.get("title") for c in (dated[:5] or candidates[:5])]
    return None, f"ambiguous: no clean recent candidate among {top_titles!r}"


async def civicclerk_latest_event_url(
    session: aiohttp.ClientSession, tenant_url: str
) -> Tuple[Optional[str], str]:
    """Finds the most recent real (past, has real media) CivicClerk event
    for a tenant and returns its canonical /event/{id}/media URL --
    CivicClerkAssetFinder.resolve() requires that exact shape (raises
    ValueError on a bare tenant link), so a listing page alone can't be
    handed to it the way CalendarPageError-raising adapters allow.
    Mirrors scripts/find_tier3_short_meeting_substitutes.py's
    cc_list_past_events()/cc_past_candidates() -- the only existing,
    live-verified per-tenant listing technique for this platform."""
    subdomain = urlparse(tenant_url).netloc.split(".")[0]
    api_base = f"https://{subdomain}.api.civicclerk.com/v1"
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    filtered = f"{api_base}/Events?$filter=startDateTime lt {now_iso}&$orderby=startDateTime desc&$top=25"
    plain = f"{api_base}/Events?$orderby=startDateTime desc&$top=25"
    try:
        async with session.get(
            filtered, headers=UA_HEADERS, timeout=FETCH_TIMEOUT
        ) as resp:
            if resp.status >= 400:
                async with session.get(
                    plain, headers=UA_HEADERS, timeout=FETCH_TIMEOUT
                ) as resp2:
                    resp2.raise_for_status()
                    payload = await resp2.json(content_type=None)
            else:
                payload = await resp.json(content_type=None)
    except Exception as e:
        return None, f"civicclerk Events API failed: {e}"

    events = payload.get("value") if isinstance(payload, dict) else payload
    events = events or []
    now_iso2 = now_iso
    real = []
    for ev in events:
        if ev.get("isDeleted"):
            continue
        has_media = (
            ev.get("hasMedia")
            or ev.get("mediaStreamPath")
            or ev.get("mediaSourcePathMp4")
            or ev.get("externalMediaUrl")
        )
        if not has_media:
            continue
        start = ev.get("startDateTime") or ev.get("eventDate") or ""
        if not start or start >= now_iso2:
            continue
        real.append(ev)
    if not real:
        return (
            None,
            "no past CivicClerk events with real media found via tenant Events API",
        )

    real.sort(key=lambda e: e.get("startDateTime") or e.get("eventDate") or "")
    top = real[-1]
    title = top.get("eventName") or ""
    if not _looks_like_real_meeting(title):
        return (
            None,
            f"most recent CivicClerk event looked like a non-meeting video: {title!r}",
        )
    event_id = top.get("id")
    if event_id is None:
        return None, "most recent CivicClerk event had no id"
    return f"https://{subdomain}.portal.civicclerk.com/event/{event_id}/media", ""


def civicplus_seed_urls(hit_url: str, hop2_urls: List[str], homepage: str) -> List[str]:
    """CivicPlus's real "single meeting" shape doesn't exist -- every
    AgendaCenter URL is a category listing (see civicplus.py's own
    docstring) -- so the goal here is just landing ON an AgendaCenter
    page at all, in order of how directly the CSV's own data already
    points at one. Confirmed live 2026-09-06/07 (this run): a bare
    `/AgendaCenter` root already default-renders every category's rows
    combined (62 tr.catAgendaRow found on a real site with no query
    string at all), so it's a safe, high-value guess even with nothing
    better in hop2_urls."""
    seeds = []
    if "agendacenter" in hit_url.lower():
        seeds.append(hit_url)
    for u in hop2_urls:
        if "agendacenter" in u.lower() and u not in seeds:
            seeds.append(u)
    if hit_url not in seeds:
        seeds.append(hit_url)
    base = homepage.rstrip("/")
    for guess in (f"{base}/AgendaCenter", f"{base}/agendacenter"):
        if guess not in seeds:
            seeds.append(guess)
    return seeds


PLATFORM_URL_KEYWORDS = {
    "legistar": ("calendar.aspx", "meetingdetail.aspx", "legistar"),
    "municode_meetings": ("municodemeetings.com",),
    "civicweb": ("civicweb.net",),
    "civicclerk": ("civicclerk.com",),
    "swagit": ("swagit.com",),
    "cablecast": ("cablecast.tv",),
    "iqm2": ("iqm2.com",),
    "telvue": ("telvue.com", "peg.tv"),
    "escribe": ("escribemeetings.com",),
    "granicus": ("granicus.com",),
    "civiclive": ("civiclive.com",),
    "vimeo": ("vimeo.com",),
    "youtube": ("youtube.com", "youtu.be"),
}


async def locate_platform_url(
    session: aiohttp.ClientSession,
    platform: str,
    hit_url: str,
    hop2_urls: List[str],
    homepage: str,
) -> Tuple[Optional[str], str]:
    """Finds a real URL on `platform`'s own domain (or, for self-hosted
    CivicPlus, the right AgendaCenter page) to actually call the
    adapter's resolve() on -- hit_source_url alone is only ever "the gov
    page the signature was found on", not necessarily that URL itself.
    Returns (url, "") on success or (None, reason) when nothing on the
    confirmed pages actually links to the platform (a real false-positive
    class: the two-hop scan's signature match doesn't always mean a
    resolvable per-meeting link exists there)."""
    if platform == "civicplus":
        for seed in civicplus_seed_urls(hit_url, hop2_urls, homepage):
            final_url, html = await fetch_html(session, seed)
            if html is None:
                continue
            if (
                "civicplus.com" in urlparse(final_url).netloc.lower()
                or "catAgendaRow" in html
            ):
                return seed, ""
        return (
            None,
            "no reachable AgendaCenter page found (hit_url, hop2_urls, or /AgendaCenter guess)",
        )

    if detect_platform(hit_url) == platform:
        return hit_url, ""

    final_url, html = await fetch_html(session, hit_url)
    if html:
        link = find_specific_platform_link(html, final_url or hit_url, platform)
        if link:
            return link, ""

    for u in hop2_urls[:HOP2_FETCH_CAP]:
        if detect_platform(u) == platform:
            return u, ""
        final_url2, html2 = await fetch_html(session, u)
        if not html2:
            continue
        link = find_specific_platform_link(html2, final_url2 or u, platform)
        if link:
            return link, ""

    return (
        None,
        f"no {platform} link found on hit_source_url or first {HOP2_FETCH_CAP} hop2_urls",
    )


async def resolve_civicplus_seed(seed_url: str):
    """Calls CivicPlusAssetFinder.resolve() directly, same as `resolve_seed()`
    below does for every other platform. Used to need its own bypass here
    -- REAL BUG, confirmed live 2026-09-07 (this run, University Place WA
    and Klickitat County WA, both since deleted from production): that
    adapter's `resolve()` used to divert to `resolve_via_platform()`
    for anything whose post-redirect netloc didn't literally contain
    "civicplus.com", assuming that meant a redirect to some other real
    platform -- but most CivicPlus tenants are white-labeled onto the
    government's own domain and never touch civicplus.com at all (e.g.
    klickitatcounty.gov). `detect_platform()` on a plain klickitatcounty.gov
    URL returns "unknown", which dispatched to generic_fallback.py, which
    scraped the bare AgendaCenter page as if it were a single meeting
    (title "Agenda Center", no video, agenda junk) and even tried
    delegating to a "connect.civicplus.com/referral" branding footer link.
    Ingested for real before this was caught by inspecting a smoke-test
    log, not by inspection alone -- see this file's own incident note in
    the module docstring. Now fixed at the source
    (app/platforms/civicplus.py's own `resolve()` keys its gate off
    `detect_platform(final_url)` instead), so this no longer needs its own
    duplicate fetch/parse/gate-bypass -- the one remaining civicplus-
    specific step is picking a candidate from a raised `CalendarPageError`
    and threading its own agenda_link/packet_link through, which
    `resolve_seed()`'s fully generic CalendarPageError handling below
    doesn't do for any platform yet."""
    finder = get_finder("civicplus")
    try:
        result = await finder.resolve(seed_url)
        return result, seed_url
    except NoVideoCandidateFound as e:
        raise RowSkip(
            "civicplus: no video-bearing rows found on this AgendaCenter page "
            f"(checked {e.candidates_checked} real candidate(s))"
        )
    except CalendarPageError as e:
        picked, reason = pick_calendar_candidate(e.candidates)
        if not picked:
            raise RowSkip(f"civicplus CalendarPageError, {reason}")
        result = await resolve_via_platform(picked["url"])
        if e.jurisdiction_hint and not result.jurisdiction:
            result.jurisdiction = e.jurisdiction_hint
        result.agenda_link = result.agenda_link or picked.get("agenda_link")
        result.packet_link = result.packet_link or picked.get("packet_link")
        # Same fallback as CivicPlusAssetFinder.resolve()'s own
        # single-candidate path now provides (see that module's real,
        # confirmed-live incident note): a delegated platform's title/date
        # extraction can come back empty even though this row's own
        # title/date, straight from the AgendaCenter listing, is already
        # sitting right here in `picked`.
        result.title = result.title or picked["title"]
        result.date = result.date or picked["date"]
        return result, picked["url"]


# Platforms that are general-purpose video hosts, not dedicated
# government-meeting systems -- a link to one, found by generically
# scanning a page for ANY known platform, carries no inherent "this is a
# meeting" guarantee the way a CivicPlus AgendaCenter row, a CivicClerk
# tenant Events API record, or a Legistar/Municode Meetings listing row
# does (those are meeting records by construction). Real, confirmed-live
# gap: Grandview WA (a Vimeo promo, single-video no-listing case) and
# Colfax WA (a YouTube tourism video, same shape) both slipped past a
# blocklist-only check -- see _looks_like_real_meeting()'s own docstring.
HIGH_RISK_TITLE_PLATFORMS = {"youtube", "vimeo"}


async def resolve_seed(session: aiohttp.ClientSession, platform: str, seed_url: str):
    """Calls the right adapter on `seed_url`, handling CivicPlus's domain-
    gate bypass, CivicClerk's listing-vs-single-event split, and one
    level of CalendarPageError picking. Returns (ResolvedMeeting,
    final_seed_url_used, high_risk_title) or raises RowSkip --
    high_risk_title tells the caller whether this result needs the
    stricter allowlist-required title check (see HIGH_RISK_TITLE_PLATFORMS)."""
    if platform == "civicplus":
        result, final_seed = await resolve_civicplus_seed(seed_url)
        return result, final_seed, False

    if platform == "civicclerk" and "/event/" not in urlparse(seed_url).path:
        event_url, reason = await civicclerk_latest_event_url(session, seed_url)
        if not event_url:
            raise RowSkip(reason or "civicclerk: no resolvable event")
        seed_url = event_url

    finder = get_finder(platform)
    try:
        result = await finder.resolve(seed_url)
        high_risk = platform in HIGH_RISK_TITLE_PLATFORMS
        return result, seed_url, high_risk
    except CalendarPageError as e:
        picked, reason = pick_calendar_candidate(e.candidates)
        if not picked:
            raise RowSkip(f"CalendarPageError, {reason}")
        candidate_url = picked["url"]
        try:
            result = await resolve_via_platform(candidate_url)
        except CalendarPageError as e2:
            picked2, reason2 = pick_calendar_candidate(e2.candidates)
            if not picked2:
                raise RowSkip(f"nested CalendarPageError, {reason2}")
            result = await resolve_via_platform(picked2["url"])
            candidate_url = picked2["url"]
        if e.jurisdiction_hint and not result.jurisdiction:
            result.jurisdiction = e.jurisdiction_hint
        # Came from a structured listing page (this platform's own
        # CalendarPageError candidates) -- the listing itself already
        # establishes meeting-context, so the blocklist-only check is
        # enough even though `platform` may be in HIGH_RISK_TITLE_PLATFORMS
        # (e.g. a Vimeo channel/showcase listing).
        return result, candidate_url, False


async def _ingest_with_retry(
    session: aiohttp.ClientSession, payload: dict, input_url_normalized: str
) -> Optional[dict]:
    """Wraps bulk_ingest.py's own _ingest() with one retry -- see this
    file's incident note (Destin, FL) on process_row's ingest call sites
    for why an unguarded call here is a real, confirmed-live gap: a
    transient failure talking to our OWN Archive backend (a real
    SSL alert hit live 2026-09-07) is a fundamentally different, much
    cheaper-to-retry failure than a government site being slow, broken,
    or blocking, and previously looked identical to a generic "unhandled
    exception" with no platform recorded. Returns None (never raises)
    after both attempts fail, so the caller can log a precise, findable
    reason instead of the row vanishing into a generic crash message."""
    for attempt in (1, 2):
        try:
            return await _ingest(session, payload, input_url_normalized)
        except Exception:
            if attempt == 2:
                return None
            await asyncio.sleep(3)
    return None


class RowSkip(Exception):
    """Raised internally to short-circuit a row to a skip+reason."""


_seen_keys: set = set()


def _dedup_key(result) -> str:
    if getattr(result, "external_id", None):
        return f"ext:{result.external_id}"
    return f"src:{normalize_url(result.source_url or '')}"


async def process_row(session: aiohttp.ClientSession, row: dict) -> RowResult:
    gov_id = row["gov_id"]
    unit_name = row["unit_name"]
    homepage = row.get("homepage") or ""
    hop2_urls = [
        u.strip() for u in (row.get("hop2_urls") or "").split(";") if u.strip()
    ]
    hits = _parse_hit_source_urls(row.get("hit_source_urls") or "")

    if not hits:
        return RowResult(
            gov_id, unit_name, "", "skipped", "no hit_source_urls on this row"
        )

    supported_hits = [(p, u) for p, u in hits if p not in UNSUPPORTED_PLATFORMS]
    if not supported_hits:
        platforms_seen = ", ".join(sorted({p for p, _ in hits}))
        return RowResult(
            gov_id,
            unit_name,
            platforms_seen,
            "skipped",
            "unsupported platform, no adapter in this repo (boarddocs/municipalcodeonline)",
        )

    last_reason = ""
    for platform, hit_url in supported_hits:
        try:
            get_finder(platform)  # raises UnsupportedPlatformError if not registered
        except UnsupportedPlatformError:
            last_reason = f"{platform}: not registered in get_finder() (unexpected)"
            continue

        seed_url, reason = await locate_platform_url(
            session, platform, hit_url, hop2_urls, homepage
        )
        if not seed_url:
            last_reason = f"{platform}: {reason}"
            continue

        try:
            result, final_seed, high_risk_title = await resolve_seed(
                session, platform, seed_url
            )
        except RowSkip as e:
            last_reason = f"{platform}: {e}"
            continue
        except Exception as e:
            last_reason = f"{platform}: resolve raised: {e}"
            continue

        segments = result.segments or []
        agenda_items = result.agenda_items or []
        if not (segments or agenda_items or result.agenda_link or result.video_url):
            last_reason = (
                f"{platform}: resolved but no transcript/agenda/video ({final_seed})"
            )
            continue

        key = _dedup_key(result)
        if key in _seen_keys:
            last_reason = f"{platform}: duplicate of an already-processed meeting this run ({key})"
            continue

        # Universal title gate -- applies to EVERY successful resolve,
        # not just a CalendarPageError pick-list. Real bug caught in this
        # script's own smoke test 2026-09-07: a direct single-video
        # resolve (no CalendarPageError, so pick_calendar_candidate()
        # never runs at all) let a real Vimeo promo video ("Grandview
        # Welcome  2025") straight through to a live tier-1/2 ingest --
        # exactly the ENUMERATION_METHODS.md-documented bug this whole
        # script exists to avoid. See youtube_oembed_title()'s own
        # docstring for why an empty result.title (yt-dlp blocked in this
        # environment) needed its own fallback rather than trivially
        # passing the blocklist check.
        effective_title = result.title or ""
        if not effective_title and result.video_url:
            oembed_title = await youtube_oembed_title(session, result.video_url)
            if oembed_title:
                effective_title = oembed_title
        if not _looks_like_real_meeting(
            effective_title, require_allowlist=high_risk_title
        ):
            why = (
                "no governing-body keyword in title"
                if high_risk_title
                else "blocklisted term in title"
            )
            last_reason = f"{platform}: title looks like a non-meeting video ({why}), not ingested: {effective_title!r} ({final_seed})"
            continue

        _seen_keys.add(key)

        title = result.title or ""
        date = result.date or ""

        if segments:
            normalized = normalize_url(final_seed)
            # WO-222: this row already knows its government (gov_id is the
            # first thing process_row() reads off it) -- send it in the
            # payload so a shared-host page never depends on a
            # tenant_overrides.csv pin reaching production first. See
            # scripts/wo134_confirmed_hits_ingest.py's matching comment
            # and docs/COVERAGE_HANDOVER.md §3.
            payload = result.model_dump()
            if gov_id:
                payload["gov_id"] = gov_id
            response = await _ingest_with_retry(session, payload, normalized)
            if response is None:
                # Real gap found auditing this run 2026-09-07 (Destin, FL):
                # the POST to our OWN Archive backend is a network call
                # like any other and can fail transiently (one real
                # SSLV3_ALERT_BAD_RECORD_MAC hit live) -- previously
                # unguarded, so a fully-resolved, real, ingestable meeting
                # silently vanished into an "unhandled exception" skip
                # with no platform/detail recorded, indistinguishable from
                # a government-site failure. Retried once (see
                # _ingest_with_retry); a row that still fails here is
                # logged plainly as an ingest-POST failure, not "skipped"
                # for lack of real content, so it's easy to find and rerun.
                last_reason = f"{platform}: resolved real content ({len(segments)} segments) but POST to Archive failed twice, not ingested: {final_seed}"
                continue
            page_url = response.get("url")
            created = response.get("created")
            note = "" if created else " (matched an EXISTING page, not newly created)"
            return RowResult(
                gov_id,
                unit_name,
                platform,
                "ingested_tier1_2",
                f"{len(segments)} transcript segments{note}",
                final_seed,
                title,
                date,
                page_url or "",
            )

        if result.video_url:
            source_line = (
                f"{final_seed}\t{hit_url}" if hit_url != final_seed else final_seed
            )
            with TIER3_QUEUE_FILE.open("a", encoding="utf-8") as f:
                f.write(source_line + "\n")
            return RowResult(
                gov_id,
                unit_name,
                platform,
                "queued_tier3",
                "real video, no transcript yet -- appended to tier3_auto_transcription_queue.txt",
                final_seed,
                title,
                date,
                "",
            )

        # agenda_items/agenda_link present, no video/segments -- same
        # ingest-worthy bar bulk_ingest.py's own gate already uses, but
        # logged as its own bucket since the task's tier1/2/3 definition
        # doesn't name this case explicitly.
        normalized = normalize_url(final_seed)
        # WO-222: same as the segments branch above -- send the row's
        # known gov_id.
        payload = result.model_dump()
        if gov_id:
            payload["gov_id"] = gov_id
        response = await _ingest_with_retry(session, payload, normalized)
        if response is None:
            last_reason = f"{platform}: resolved real agenda content but POST to Archive failed twice, not ingested: {final_seed}"
            continue
        page_url = response.get("url")
        created = response.get("created")
        note = "" if created else " (matched an EXISTING page, not newly created)"
        return RowResult(
            gov_id,
            unit_name,
            platform,
            "ingested_agenda_only",
            f"agenda content, no video/transcript{note}",
            final_seed,
            title,
            date,
            page_url or "",
        )

    return RowResult(
        gov_id,
        unit_name,
        ", ".join(p for p, _ in supported_hits),
        "skipped",
        last_reason or "no usable platform link found",
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit", type=int, default=None, help="Process at most N rows (smoke test)"
    )
    parser.add_argument(
        "--start-after",
        type=str,
        default=None,
        help="Skip rows up to and including this gov_id (manual resume point)",
    )
    args = parser.parse_args()

    if not _base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (check .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    register_all_finders()

    rows = _read_csv_rows(INPUT_CSV)
    already_done = _already_logged_gov_ids(LOG_CSV)
    print(
        f"{len(rows)} total rows, {len(already_done)} already logged from a prior run -- skipping those."
    )

    skip_until_seen = args.start_after is not None
    to_process = []
    for row in rows:
        if row["gov_id"] in already_done:
            continue
        if skip_until_seen:
            if row["gov_id"] == args.start_after:
                skip_until_seen = False
            continue
        to_process.append(row)
    if args.limit:
        to_process = to_process[: args.limit]

    print(f"Processing {len(to_process)} row(s) against {_base_url()}...\n")

    log_f, log_writer = _log_writer(LOG_CSV)
    tally: Dict[str, int] = {}
    try:
        async with aiohttp.ClientSession() as session:
            for i, row in enumerate(to_process):
                try:
                    result = await process_row(session, row)
                except Exception as e:
                    result = RowResult(
                        row["gov_id"],
                        row["unit_name"],
                        "",
                        "skipped",
                        f"unhandled exception: {e}",
                    )
                tally[result.outcome] = tally.get(result.outcome, 0) + 1
                print(
                    f"[{result.outcome:20}] {result.gov_id} {result.unit_name!r} platform={result.platform!r} -- {result.reason}"
                )
                log_writer.writerow(result.__dict__)
                log_f.flush()
                if i < len(to_process) - 1:
                    await asyncio.sleep(REQUEST_DELAY_SECONDS)
    finally:
        log_f.close()

    print("\n--- Tally (this run) ---")
    for outcome, count in sorted(tally.items()):
        print(f"{outcome:20} {count}")
    print(f"\nFull log: {LOG_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
