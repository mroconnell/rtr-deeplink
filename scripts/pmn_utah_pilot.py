"""Full step-1-through-5 pilot for Utah's Public Notice Website (PMN),
https://www.utah.gov/pmn/ -- the state's statutory Open and Public
Meetings Act notice board. Every public body in Utah (state agencies,
counties, municipalities, special service districts, interlocals,
judicial branch, associations of government) is required to post its
meeting notices here, and a notice's own detail page carries a real,
self-reported "Audio File Location" field alongside clean, unambiguous
Government Type / Entity / Public Body fields -- confirmed live
2026-09-08 against a real Alpine, UT City Council notice
(https://www.utah.gov/pmn/sitemap/notice/1103751.html), which links a
real YouTube recording. See rtr-business/research/ENUMERATION_METHODS.md
section on this method for the full writeup; this docstring covers only
the mechanics this script depends on.

THREE REAL, LIVE-CONFIRMED API QUIRKS THAT AREN'T DOCUMENTED ANYWHERE
ELSE, ALL FOUND BY READING THE SITE'S OWN JS RATHER THAN GUESSING:

1. The visible "Search" page (GET/POST /pmn/search.html) renders a full
   HTML page and DOES include a real results table + pagination on a POST
   -- but only page 1. Clicking a page-2+ link fires a SEPARATE endpoint,
   POST /pmn/searchresult.html, via the site's own shared "STAT" JS
   framework (secure.utah.gov/stat/1.5/js/global.js). Calling
   /pmn/searchresult.html with a normal url-encoded POST body (what
   /pmn/search.html itself accepts) 200s with a generic "Technical
   Difficulties" error page -- confirmed by hand, cost real time to find.
2. The actual bug: STAT's stat.ajax.post() sends the body as
   `JSON.stringify(params)` with `Content-Type: application/JSON` and
   `X-Requested-With: XMLHttpRequest` -- NOT form-urlencoded. Confirmed by
   reading global.js directly (`stat.ajax.req`'s source). Once the body is
   real JSON with those two headers, /pmn/searchresult.html returns the
   same #searchResultsTable markup as page 1, and pagination is a
   `startingRow` integer (0, 25, 50, ...) in that same JSON body -- no
   session-side cursor, so pages can be fetched in any order / resumed.
3. A CSRF token (from `<meta name="_csrf">` on any page, header name from
   `<meta name="_csrf_header">`, confirmed always "X-CSRF-TOKEN") is
   required on every POST including page 1 of /pmn/search.html itself --
   omitting it 403s outright, not a soft failure.

WHAT THE SEARCH RESULTS TABLE DOES AND DOESN'T TELL YOU (confirmed live):
Columns are Notice Title / Event Date / Public Body / Entity /
Attachments -- Attachments is a real list of uploaded files with a
category label ("Audio Recording", "Meeting Minutes", "Public Information
Handout", "Other" seen so far), so a same-domain uploaded audio file
(`/pmn/files/{id}.m4a`) IS visible from the list alone. A linked-out video
(YouTube/Vimeo/etc, via the detail page's separate "Audio File Location"
field) is NOT visible from the list -- Alpine's own real example is
exactly this case, and its list row shows only a PDF packet attachment.
So this script can't skip fetching detail pages; it narrows the set of
detail-page fetches with a governing-body keyword title filter instead
(same MEETING_ALLOWLIST substring check nationwide_431_ingest.py already
uses), which is cheap and catches the overwhelming majority of real
meeting notices without fetching every bid/RFP/vacancy notice too.

TWO CANDIDATE SHAPES, ONLY ONE OF WHICH THIS SCRIPT CAN ACT ON:
  (a) "Audio File Location" (or an attachment) points to a URL on a
      platform this repo already has an adapter for (youtube.com,
      vimeo.com, granicus.com, etc, via app/platforms/base.py's
      detect_platform()) -- resolvable right now, this script's real
      job.
  (b) An attachment IS the media file itself, hosted directly on
      utah.gov (`/pmn/files/{id}.m4a` or similar) -- detect_platform()
      correctly returns "unknown" for these, since no adapter in this
      repo (or civic-scraper generally) handles "bare hosted audio file,
      no platform wrapper" as its own case. NOT attempted here --logged
      to a separate CSV bucket as a real, confirmed-live gap for later
      work, per this project's own rule (CLAUDE.md) against building an
      adapter without having tested it against a real, live sample
      first; one m4a URL alone isn't that.

RESOLUTION APPROACH, reusing nationwide_431_ingest.py's already-verified
building blocks rather than re-deriving them (see that file for the
original incidents each guard is fixing):
  - `pick_calendar_candidate`/`_looks_like_real_meeting`/
    `youtube_oembed_title`/`HIGH_RISK_TITLE_PLATFORMS` imported directly.
  - One meaningful addition: since PMN already hands us the real event
    date for THIS specific notice, a CalendarPageError (a channel/listing
    URL instead of one video) is resolved by nearest-date match against
    that known date first, falling back to nationwide_431_ingest.py's
    own "most recent clean" logic only if no candidate is within 3 days.
  - Jurisdiction/meeting_body are OVERRIDDEN with PMN's own Entity/Public
    Body fields unconditionally -- this is the "known-identity override"
    pattern from ENUMERATION_METHODS.md's cross-cutting correctness note
    (2026-09-07, its own doc's §98): the government is never in doubt
    here, PMN says so directly, so there's no reason to trust whatever
    jurisdiction string a generic YouTube/Vimeo resolve guesses instead.
  - The title-safety gate runs against PMN's OWN notice title (a real,
    state-mandated meeting notice title, e.g. "8.25.26 City Council
    Meeting Work Session Packet and Audio"), not the linked video's own
    title -- a strictly higher-trust signal than the generic-YouTube-scan
    case _looks_like_real_meeting() was originally built for, so false
    rejects should be rare.

Tier 1/2 (real segments) -> POST /internal/ingest (bulk_ingest.py's own
_ingest(), same as every other bulk script). Tier 3 (real video_url, no
segments) -> appended to scripts/tier3_auto_transcription_queue.txt.

gov_id enrichment: for Government Type Municipality/County, the Entity
name is matched (normalized, case-insensitive, common suffix stripped)
against rtr-business/research/jurisdiction_coverage.csv's Utah rows,
which already carry a real Census gov_id for 279/285 Utah
municipalities/counties -- purely a reporting enrichment (does this
notice's government already have ANY coverage on file?), not required
for ingest itself.

Writes:
  - rtr-business/research/pmn_utah_notices_raw.csv -- every notice seen
    in the enumerated window (resumable across --start-date/--end-date
    reruns is not attempted; re-enumerating is cheap and idempotent).
  - rtr-business/research/pmn_utah_native_audio_files.csv -- candidates
    whose only real media is a same-domain uploaded file (case (b)
    above), for future adapter work.
  - rtr-business/research/pmn_utah_pilot_log.csv -- one row per resolved
    candidate notice, same shape as nationwide_431_ingest.py's log
    (resumable: notice_urls already present are skipped on a re-run).

Usage (from repo root, venv active, needs ARCHIVE_BASE_URL/
ARCHIVE_INGEST_TOKEN in .env -- see bulk_ingest.py's own docstring):
    python scripts/pmn_utah_pilot.py --start-date 2026-05-11 --end-date 2026-09-08
    python scripts/pmn_utah_pilot.py --enumerate-only   # just build the raw CSV, no resolve/ingest
    python scripts/pmn_utah_pilot.py --limit 20         # smoke test the resolve/ingest phase
"""

import argparse
import asyncio
import csv
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin

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
    UnsupportedPlatformError,
    detect_platform,
    get_finder,
)
from app.utils.url_normalize import normalize_url  # noqa: E402
from scripts.bulk_ingest import _base_url, _ingest  # noqa: E402
from scripts.nationwide_431_ingest import (  # noqa: E402
    HIGH_RISK_TITLE_PLATFORMS,
    _looks_like_real_meeting,
    pick_calendar_candidate,
    youtube_oembed_title,
)

RESEARCH_DIR = Path("/Users/mroconnell/Documents/rtr-business/research")
RAW_NOTICES_CSV = RESEARCH_DIR / "pmn_utah_notices_raw.csv"
NATIVE_AUDIO_CSV = RESEARCH_DIR / "pmn_utah_native_audio_files.csv"
LOG_CSV = RESEARCH_DIR / "pmn_utah_pilot_log.csv"
JURISDICTION_COVERAGE_CSV = RESEARCH_DIR / "jurisdiction_coverage.csv"
TIER3_QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"

PMN_BASE = "https://www.utah.gov"
SEARCH_PAGE_URL = f"{PMN_BASE}/pmn/search.html"
SEARCH_RESULT_URL = f"{PMN_BASE}/pmn/searchresult.html"
PAGE_SIZE = 25
PMN_REQUEST_DELAY_SECONDS = 0.5  # polite pacing against a state resource, not a target
RESOLVE_DELAY_SECONDS = (
    1.5  # matches nationwide_431_ingest.py -- third-party hosts + our own Archive
)
FETCH_TIMEOUT = aiohttp.ClientTimeout(total=25)
UA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    )
}
MAX_ENUM_PAGES = (
    600  # safety cap (15,000 notices) -- real volume is far lower per prior spot checks
)

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

# Government Types actually worth trying to map to a Census gov_id --
# the others (State Agency, Judicial Branch, College or University,
# Interlocal, Associations of Government) aren't in
# jurisdiction_coverage.csv's registry at all (that CSV is built from
# US Census places/counties), so a lookup for them would only ever miss.
GOV_TYPES_WITH_REGISTRY_MATCH = {"Municipality", "County"}

_ENTITY_SUFFIX_RE = re.compile(
    r"\s+(city|town|county|metro township|township)\s*$", re.IGNORECASE
)


class RowSkip(Exception):
    pass


@dataclass
class Notice:
    notice_url: str
    title: str
    event_date_text: str
    public_body: str
    entity: str
    attachments: List[Tuple[str, str, str]] = field(
        default_factory=list
    )  # (filename, url, category)


@dataclass
class RowResult:
    notice_url: str
    entity: str
    government_type: str
    gov_id: str
    platform: str
    outcome: str  # ingested_tier1_2 | queued_tier3 | native_audio_file | skipped
    reason: str
    seed_url: str = ""
    title: str = ""
    date: str = ""
    page_url: str = ""


# ---------------------------------------------------------------------------
# PMN client
# ---------------------------------------------------------------------------


async def fetch_csrf(session: aiohttp.ClientSession) -> Tuple[str, str]:
    async with session.get(
        SEARCH_PAGE_URL, headers=UA_HEADERS, timeout=FETCH_TIMEOUT
    ) as resp:
        resp.raise_for_status()
        html = await resp.text()
    soup = BeautifulSoup(html, "html.parser")
    token = soup.find("meta", attrs={"name": "_csrf"})
    header = soup.find("meta", attrs={"name": "_csrf_header"})
    if not token or not token.get("content"):
        raise RuntimeError("could not find _csrf meta tag on /pmn/search.html")
    return token["content"], (header.get("content") if header else "X-CSRF-TOKEN")


def _parse_results_table(html: str) -> List[Notice]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find(id="searchResultsTable")
    if table is None:
        return []
    notices = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        title_link = tds[0].find("a")
        if not title_link or not title_link.get("href"):
            continue
        notice_url = urljoin(PMN_BASE, title_link["href"])
        title = title_link.get_text(strip=True)
        event_date_text = tds[1].get_text(strip=True)
        public_body = tds[2].get_text(strip=True)
        entity = tds[3].get_text(strip=True)
        attachments = []
        for li in tds[4].find_all("li"):
            a = li.find("a")
            if not a or not a.get("href"):
                continue
            file_url = urljoin(PMN_BASE, a["href"])
            filename = a.get_text(strip=True)
            m = re.search(r"\(([^)]+)\)\s*$", li.get_text(" ", strip=True))
            category = m.group(1).strip() if m else ""
            attachments.append((filename, file_url, category))
        notices.append(
            Notice(notice_url, title, event_date_text, public_body, entity, attachments)
        )
    return notices


async def fetch_search_page(
    session: aiohttp.ClientSession,
    csrf_token: str,
    csrf_header: str,
    start_date: str,
    end_date: str,
    starting_row: int,
) -> List[Notice]:
    """Real, confirmed-live API quirk (see module docstring point 2): the
    body MUST be JSON (not form-urlencoded) with Content-Type:
    application/JSON and X-Requested-With: XMLHttpRequest, or this
    endpoint 200s with a generic error page instead of real results."""
    payload = {
        "searchType": "entity",
        "entityName": "",
        "publicBodyName": "",
        "title": "",
        "agenda": "",
        "tags": "",
        "startDate": start_date,
        "endDate": end_date,
        "deadlineDate": "",
        "createdDate": "",
        "sortColumn": "",
        "sortOrder": "",
        "startingRow": str(starting_row),
    }
    headers = {
        **UA_HEADERS,
        "content-type": "application/JSON",
        "x-requested-with": "XMLHttpRequest",
        csrf_header: csrf_token,
    }
    async with session.post(
        SEARCH_RESULT_URL,
        data=json.dumps(payload),
        headers=headers,
        timeout=FETCH_TIMEOUT,
    ) as resp:
        resp.raise_for_status()
        html = await resp.text()
    return _parse_results_table(html)


async def enumerate_notices(
    session: aiohttp.ClientSession, start_date: str, end_date: str
) -> List[Notice]:
    csrf_token, csrf_header = await fetch_csrf(session)
    all_notices: Dict[str, Notice] = {}
    starting_row = 0
    for page_num in range(MAX_ENUM_PAGES):
        notices = await fetch_search_page(
            session, csrf_token, csrf_header, start_date, end_date, starting_row
        )
        if not notices:
            break
        new_count = 0
        for n in notices:
            if n.notice_url not in all_notices:
                all_notices[n.notice_url] = n
                new_count += 1
        print(
            f"  page {page_num + 1} (startingRow={starting_row}): {len(notices)} rows, "
            f"{new_count} new, {len(all_notices)} total so far"
        )
        starting_row += PAGE_SIZE
        await asyncio.sleep(PMN_REQUEST_DELAY_SECONDS)
        if len(notices) < PAGE_SIZE:
            break
    return list(all_notices.values())


_DT_TEXT_RE = re.compile(r"\s+")


def _parse_dt_dd(soup: BeautifulSoup) -> Dict[str, Tuple[str, Optional[str]]]:
    """Maps every <dt>label</dt><dd>...</dd> pair on a notice detail page
    to (text, first_href_in_dd_or_None). Confirmed live 2026-09-08 against
    a real Alpine notice -- see this file's module docstring."""
    out: Dict[str, Tuple[str, Optional[str]]] = {}
    for dt in soup.find_all("dt"):
        label = _DT_TEXT_RE.sub(" ", dt.get_text(strip=True))
        dd = dt.find_next_sibling("dd")
        if dd is None:
            continue
        text = _DT_TEXT_RE.sub(" ", dd.get_text(" ", strip=True))
        a = dd.find("a")
        href = urljoin(PMN_BASE, a["href"]) if a and a.get("href") else None
        out[label] = (text, href)
    return out


async def fetch_notice_detail(
    session: aiohttp.ClientSession, notice_url: str
) -> Dict[str, Tuple[str, Optional[str]]]:
    async with session.get(
        notice_url, headers=UA_HEADERS, timeout=FETCH_TIMEOUT
    ) as resp:
        resp.raise_for_status()
        html = await resp.text()
    return _parse_dt_dd(BeautifulSoup(html, "html.parser"))


def looks_like_meeting_title(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in MEETING_ALLOWLIST)


# ---------------------------------------------------------------------------
# gov_id enrichment
# ---------------------------------------------------------------------------


def _normalize_entity(name: str) -> str:
    return _ENTITY_SUFFIX_RE.sub("", name).strip().lower()


def load_utah_gov_id_map() -> Dict[str, dict]:
    if not JURISDICTION_COVERAGE_CSV.exists():
        return {}
    out = {}
    with JURISDICTION_COVERAGE_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("state_or_province") != "Utah":
                continue
            key = _normalize_entity(row["city_name"])
            out[key] = row
    return out


# ---------------------------------------------------------------------------
# Date-aware calendar-candidate picking
# ---------------------------------------------------------------------------

_PMN_DATE_FORMATS = ("%B %d, %Y %I:%M %p", "%B %d, %Y")


def parse_pmn_event_date(text: str) -> Optional[datetime]:
    text = (text or "").strip()
    for fmt in _PMN_DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


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


def pick_candidate_near_date(
    candidates: List[dict], target: Optional[datetime]
) -> Tuple[Optional[dict], str]:
    """PMN already tells us the real event date for this specific notice,
    which nationwide_431_ingest.py's own pick_calendar_candidate() (built
    for the no-date-known case) can't use. Prefer whichever clean-titled
    candidate is within 3 days of that date; fall back to the "most
    recent clean" logic otherwise."""
    if target is not None:
        near = []
        for c in candidates:
            dt = _parse_candidate_date(c.get("date") or "")
            if dt is None:
                continue
            if abs((dt - target).days) <= 3 and _looks_like_real_meeting(
                c.get("title") or ""
            ):
                near.append((abs((dt - target).days), c))
        if near:
            near.sort(key=lambda pair: pair[0])
            return near[0][1], ""
    return pick_calendar_candidate(candidates)


# ---------------------------------------------------------------------------
# Resolve + ingest
# ---------------------------------------------------------------------------


async def resolve_pmn_candidate(
    session: aiohttp.ClientSession,
    platform: str,
    seed_url: str,
    target_date: Optional[datetime],
):
    finder = get_finder(platform)
    try:
        result = await finder.resolve(seed_url)
        return result, seed_url
    except CalendarPageError as e:
        picked, reason = pick_candidate_near_date(e.candidates, target_date)
        if not picked:
            raise RowSkip(f"CalendarPageError, {reason}")
        from app.platforms.base import resolve_via_platform

        result = await resolve_via_platform(picked["url"])
        if e.jurisdiction_hint and not result.jurisdiction:
            result.jurisdiction = e.jurisdiction_hint
        return result, picked["url"]


async def process_notice(
    session: aiohttp.ClientSession,
    notice: Notice,
    gov_id_map: Dict[str, dict],
    native_audio_writer,
) -> RowResult:
    detail = await fetch_notice_detail(session, notice.notice_url)
    government_type = detail.get("Government Type", ("", None))[0]
    entity = detail.get("Entity", (notice.entity, None))[0] or notice.entity
    public_body_text = (
        detail.get("Public Body", (notice.public_body, None))[0] or notice.public_body
    )
    notice_title = detail.get("Notice Title", (notice.title, None))[0] or notice.title
    event_date_text = detail.get(
        "Event Start Date & Time", (notice.event_date_text, None)
    )[0]
    target_date = parse_pmn_event_date(event_date_text)

    gov_id = ""
    if government_type in GOV_TYPES_WITH_REGISTRY_MATCH:
        row = gov_id_map.get(_normalize_entity(entity))
        if row:
            gov_id = row.get("gov_id", "")

    audio_field_url = detail.get("Audio File Location", ("", None))[1]

    # Case (b): a same-domain uploaded media file, no platform wrapper --
    # not attempted (see module docstring); logged for later adapter work.
    media_attachments = [
        (fname, url, cat)
        for fname, url, cat in notice.attachments
        if cat.lower() in ("audio recording", "video recording")
    ]
    if media_attachments and not audio_field_url:
        for fname, url, cat in media_attachments:
            native_audio_writer.writerow(
                {
                    "notice_url": notice.notice_url,
                    "entity": entity,
                    "government_type": government_type,
                    "gov_id": gov_id,
                    "public_body": public_body_text,
                    "title": notice_title,
                    "event_date": event_date_text,
                    "category": cat,
                    "file_url": url,
                    "filename": fname,
                }
            )
        return RowResult(
            notice.notice_url,
            entity,
            government_type,
            gov_id,
            "",
            "native_audio_file",
            f"{len(media_attachments)} same-domain media attachment(s), no adapter for a bare hosted file",
        )

    candidate_url = audio_field_url
    if not candidate_url:
        return RowResult(
            notice.notice_url,
            entity,
            government_type,
            gov_id,
            "",
            "skipped",
            "no Audio File Location and no media attachment",
        )

    platform = detect_platform(candidate_url)
    if platform == "unknown":
        return RowResult(
            notice.notice_url,
            entity,
            government_type,
            gov_id,
            platform,
            "skipped",
            f"Audio File Location isn't on a known platform: {candidate_url}",
        )

    try:
        get_finder(platform)
    except UnsupportedPlatformError:
        return RowResult(
            notice.notice_url,
            entity,
            government_type,
            gov_id,
            platform,
            "skipped",
            f"{platform}: not registered in get_finder()",
        )

    try:
        result, final_seed = await resolve_pmn_candidate(
            session, platform, candidate_url, target_date
        )
    except RowSkip as e:
        return RowResult(
            notice.notice_url,
            entity,
            government_type,
            gov_id,
            platform,
            "skipped",
            str(e),
        )
    except Exception as e:
        return RowResult(
            notice.notice_url,
            entity,
            government_type,
            gov_id,
            platform,
            "skipped",
            f"resolve raised: {e}",
        )

    segments = result.segments or []
    agenda_items = result.agenda_items or []
    if not (segments or agenda_items or result.agenda_link or result.video_url):
        return RowResult(
            notice.notice_url,
            entity,
            government_type,
            gov_id,
            platform,
            "skipped",
            f"resolved but no transcript/agenda/video ({final_seed})",
        )

    # Known-identity override (ENUMERATION_METHODS.md's cross-cutting
    # correctness note, §98) -- PMN already tells us who this government
    # and public body are; don't trust a generic YouTube/Vimeo guess.
    result.jurisdiction = f"{entity}, Utah"
    result.meeting_body = result.meeting_body or public_body_text

    effective_title = notice_title or result.title or ""
    if not effective_title and result.video_url:
        oembed_title = await youtube_oembed_title(session, result.video_url)
        if oembed_title:
            effective_title = oembed_title
    high_risk = platform in HIGH_RISK_TITLE_PLATFORMS
    if not _looks_like_real_meeting(effective_title, require_allowlist=high_risk):
        return RowResult(
            notice.notice_url,
            entity,
            government_type,
            gov_id,
            platform,
            "skipped",
            f"title looks like a non-meeting video, not ingested: {effective_title!r} ({final_seed})",
        )

    title = result.title or notice_title or ""
    date = result.date or event_date_text or ""

    if segments:
        normalized = normalize_url(final_seed)
        response = None
        for attempt in (1, 2):
            try:
                response = await _ingest(session, result.model_dump(), normalized)
                break
            except Exception:
                if attempt == 2:
                    response = None
                else:
                    await asyncio.sleep(3)
        if response is None:
            return RowResult(
                notice.notice_url,
                entity,
                government_type,
                gov_id,
                platform,
                "skipped",
                f"resolved real content ({len(segments)} segments) but POST to Archive failed twice: {final_seed}",
            )
        page_url = response.get("url")
        created = response.get("created")
        note = "" if created else " (matched an EXISTING page, not newly created)"
        return RowResult(
            notice.notice_url,
            entity,
            government_type,
            gov_id,
            platform,
            "ingested_tier1_2",
            f"{len(segments)} transcript segments{note}",
            final_seed,
            title,
            date,
            page_url or "",
        )

    if result.video_url:
        with TIER3_QUEUE_FILE.open("a", encoding="utf-8") as f:
            f.write(final_seed + "\n")
        return RowResult(
            notice.notice_url,
            entity,
            government_type,
            gov_id,
            platform,
            "queued_tier3",
            "real video, no transcript yet -- appended to tier3_auto_transcription_queue.txt",
            final_seed,
            title,
            date,
        )

    normalized = normalize_url(final_seed)
    response = None
    for attempt in (1, 2):
        try:
            response = await _ingest(session, result.model_dump(), normalized)
            break
        except Exception:
            if attempt == 2:
                response = None
            else:
                await asyncio.sleep(3)
    if response is None:
        return RowResult(
            notice.notice_url,
            entity,
            government_type,
            gov_id,
            platform,
            "skipped",
            f"resolved real agenda content but POST to Archive failed twice: {final_seed}",
        )
    page_url = response.get("url")
    created = response.get("created")
    note = "" if created else " (matched an EXISTING page, not newly created)"
    return RowResult(
        notice.notice_url,
        entity,
        government_type,
        gov_id,
        platform,
        "ingested_agenda_only",
        f"agenda content, no video/transcript{note}",
        final_seed,
        title,
        date,
        page_url or "",
    )


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------


def _write_raw_notices_csv(notices: List[Notice]) -> None:
    with RAW_NOTICES_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "notice_url",
                "title",
                "event_date_text",
                "public_body",
                "entity",
                "attachments",
            ]
        )
        for n in notices:
            attachments_str = "; ".join(
                f"{fn}|{url}|{cat}" for fn, url, cat in n.attachments
            )
            writer.writerow(
                [
                    n.notice_url,
                    n.title,
                    n.event_date_text,
                    n.public_body,
                    n.entity,
                    attachments_str,
                ]
            )


def _already_logged_notice_urls(path: Path) -> set:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {row["notice_url"] for row in csv.DictReader(f)}


def _log_writer(path: Path):
    fields = [
        "notice_url",
        "entity",
        "government_type",
        "gov_id",
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


def _native_audio_writer(path: Path):
    fields = [
        "notice_url",
        "entity",
        "government_type",
        "gov_id",
        "public_body",
        "title",
        "event_date",
        "category",
        "file_url",
        "filename",
    ]
    is_new = not path.exists()
    f = path.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=fields)
    if is_new:
        writer.writeheader()
        f.flush()
    return f, writer


async def main() -> None:
    parser = argparse.ArgumentParser()
    default_end = datetime.now(timezone.utc).date()
    default_start = default_end - timedelta(days=120)
    parser.add_argument("--start-date", default=default_start.isoformat())
    parser.add_argument("--end-date", default=default_end.isoformat())
    parser.add_argument("--enumerate-only", action="store_true")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="cap candidates processed in resolve/ingest phase",
    )
    args = parser.parse_args()

    if not args.enumerate_only and (
        not _base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN")
    ):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (check .env). "
            "Use --enumerate-only to just build the raw notices CSV.",
            file=sys.stderr,
        )
        sys.exit(1)

    register_all_finders()

    async with aiohttp.ClientSession() as session:
        print(f"Enumerating PMN notices from {args.start_date} to {args.end_date}...")
        notices = await enumerate_notices(session, args.start_date, args.end_date)
        print(f"\n{len(notices)} total unique notices found.")
        _write_raw_notices_csv(notices)
        print(f"Wrote raw enumeration to {RAW_NOTICES_CSV}")

        candidates = [n for n in notices if looks_like_meeting_title(n.title)]
        print(
            f"{len(candidates)}/{len(notices)} notices have a governing-body keyword in their title "
            "(the set this script fetches detail pages for)."
        )

        if args.enumerate_only:
            return

        gov_id_map = load_utah_gov_id_map()
        print(
            f"Loaded {len(gov_id_map)} Utah municipality/county gov_id rows for enrichment.\n"
        )

        already_done = _already_logged_notice_urls(LOG_CSV)
        to_process = [n for n in candidates if n.notice_url not in already_done]
        if args.limit:
            to_process = to_process[: args.limit]
        print(
            f"Processing {len(to_process)} candidate notice(s) ({len(already_done)} already logged)...\n"
        )

        log_f, log_writer = _log_writer(LOG_CSV)
        native_f, native_writer = _native_audio_writer(NATIVE_AUDIO_CSV)
        tally: Dict[str, int] = {}
        try:
            for i, notice in enumerate(to_process):
                try:
                    result = await process_notice(
                        session, notice, gov_id_map, native_writer
                    )
                except Exception as e:
                    result = RowResult(
                        notice.notice_url,
                        notice.entity,
                        "",
                        "",
                        "",
                        "skipped",
                        f"unhandled exception: {e}",
                    )
                tally[result.outcome] = tally.get(result.outcome, 0) + 1
                print(
                    f"[{result.outcome:20}] {result.entity!r} ({result.government_type}) "
                    f"platform={result.platform!r} -- {result.reason}"
                )
                log_writer.writerow(result.__dict__)
                log_f.flush()
                native_f.flush()
                if i < len(to_process) - 1:
                    await asyncio.sleep(RESOLVE_DELAY_SECONDS)
        finally:
            log_f.close()
            native_f.close()

    print("\n--- Tally (this run) ---")
    for outcome, count in sorted(tally.items()):
        print(f"{outcome:20} {count}")
    print(f"\nFull log: {LOG_CSV}")
    print(f"Native-audio-file bucket (no adapter, future work): {NATIVE_AUDIO_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
