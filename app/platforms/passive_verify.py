"""WO-333: one shared "walk from a confirmed hub to a real meeting" step
for the passive-discovery sweep scripts (the `wo3NN_resolve_diagnostic.py`
family) -- not a new adapter, a thin layer on top of the existing ones.

## Why this exists

WO-331 ran 26 governments already known to have real, live captioned
video through the exact pipeline the WO-320..327 sweeps use, to check
whether that pipeline can still find video it already knows is there.
Where phase 3 confirmed a real platform link (15 of 24 reachable
controls), the sweep's own `resolve()` call found video on only 1; one
extra manual hop found 1 more; 13 still came back "no video." Two real,
confirmed causes (`docs/investigations/wo333_verification_walk.md`,
`BACKLOG_DONE.md`'s WO-331 entry):

1. A hub/listing URL (a CivicPlus AgendaCenter, an eScribe "Published
   Meetings" root, an iQM2 Citizens portal, a Granicus agenda-feed link,
   ...) is not one specific meeting -- `resolve()` on it can come back
   completely empty (no video, no title, no agenda items) even though
   the page genuinely lists real meetings, because most adapters were
   only ever built to resolve a single already-known meeting URL, not to
   walk a listing. Before this module, only `civicplus.py` did any of
   this walking itself.
2. A government that uses a CivicPlus/CivicWeb/Legistar/PrimeGov/Chicago
   ELMS "aggregator" page for its agendas and a completely different,
   real video vendor (iQM2, Vimeo, Swagit, a direct file) for its actual
   video gets the aggregator link confirmed and video-checked, and the
   real vendor link on the very same page is never reached.

`verify_hub()` below fixes both: it walks a confirmed hub to a specific,
real meeting (using a per-platform listing helper where one is
registered, and a generic listing-link scan otherwise), and -- when the
confirmed platform is a known aggregator -- separately checks the same
page for a real video-vendor link and prefers it for the video verdict.

## The verdict vocabulary

`meeting_found` is real ONLY once real listing rows or a real,
resolved meeting page were actually seen -- not merely "detect_platform()
recognized this URL." That's what `docs/investigations/
wo333_verification_walk.md` calls the "meeting-without-video may only be
written when meeting_found=True" contract: a research row should never
say "meeting, no video" for a hub that was never actually confirmed to
list anything.

`video_found` / `captions_found` are only True once a specific meeting's
own `resolve()` actually returned a `video_url` / real `segments`.
`meeting_url` is that specific meeting's URL when known.

Never fetches a youtube.com/youtu.be URL -- a YouTube embed found along
the way is recorded as a `youtube_lead` verdict (a positive finding:
video exists) and stops there, same "never fetch YouTube in a sweep"
rule every WO-3xx script already follows. Never downloads a media file.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import logging
import re
from dataclasses import dataclass
from typing import Awaitable, Callable, Dict, List, Optional
from urllib.parse import urljoin, urlparse

import aiohttp
from bs4 import BeautifulSoup

from .base import (
    CalendarPageError,
    NoVideoCandidateFound,
    UnsupportedPlatformError,
    detect_platform,
    find_platform_link,
    get_finder,
)
from ..utils.url_guard import read_capped_text

logger = logging.getLogger("rtr_deeplink.passive_verify")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) RedTapeRecordings-PassiveVerify/1.0 "
        "(+https://redtaperecordings.com)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_YOUTUBE_HOSTS = frozenset(
    {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtube-nocookie.com",
        "www.youtube-nocookie.com",
        "youtu.be",
        "www.youtu.be",
    }
)

# How many real candidates (from a CalendarPageError pick-list or a
# registered listing walker) to check for real video before giving up --
# same "walk several of the most recent, stop at network/verification
# cost, not at the first one" precedent every per-platform retry limit in
# this repo already uses (civicplus.py's own `_RETRY_LIMIT`, IQM2's
# MAX_CANDIDATES).
WALK_LIMIT = 12

# Known "aggregator" platforms (WO-333, ranking fix): agenda/meeting-
# management systems this repo already knows don't host video
# themselves and instead link or embed out to a real video vendor --
# see CLAUDE.md's "when a platform turns out to be a wrapper around
# another" bullet (Legistar/CivicPlus -> Granicus, PrimeGov -> YouTube,
# Chicago ELMS -> Vimeo) plus CivicWeb (-> YouTube, via its own
# `/api/videolink/` delegation; see civicweb.py's module docstring) and
# Municode Meetings (raises `CalendarPageError` on its own listing
# pages, same shape as CivicPlus/Legistar). When one of these is the
# platform reached for a hub and it comes back with no video, `verify_hub()`
# separately checks the SAME hub page for a real, non-aggregator video-
# vendor link and prefers that verdict for video/captions -- this is the
# fix for WO-331's 4 measured mis-ranked cases (Monroe County FL -> iQM2,
# Franklin NH -> Vimeo [also fixed directly by civicplus.py's own
# raised retry limit], Webb County TX -> Swagit, Jefferson County WA ->
# direct file).
AGGREGATOR_PLATFORMS = frozenset(
    {
        "civicplus",
        "civicweb",
        "legistar",
        "municode_meetings",
        "primegov",
        "chicago_elms",
    }
)


@dataclass
class VerifyResult:
    """The three separable facts a passive-discovery sweep actually needs,
    plus enough evidence to explain the verdict in a research row or a
    hand-check report.

    `meeting_found`: the hub (or a listing/hop reached from it) lists at
    least one real (title+date, or a real resolved page) meeting.
    `video_found`: a specific meeting's own `resolve()` returned a real
    `video_url` (or a YouTube embed was found as a lead).
    `captions_found`: that same meeting's `resolve()` returned real
    `segments`.
    `meeting_url`: the specific meeting URL the verdict is based on, when
    there is one.
    `verdict`: a short machine-readable tag (see module docstring and the
    `_resolve_and_walk`/`_walk_candidates` bodies for the full list) --
    not part of the public contract, but stable enough to tabulate.
    `evidence`: one human-readable sentence.
    `candidates_checked`: how many real candidate rows were actually
    walked, when a walk happened (0 otherwise).
    """

    meeting_found: bool
    video_found: bool
    captions_found: bool
    meeting_url: Optional[str]
    platform: Optional[str]
    verdict: str
    evidence: str
    candidates_checked: int = 0
    ranking_fix_applied: bool = False

    @property
    def tier(self) -> Optional[int]:
        """Ryan's tier vocabulary (2026-09-13), derived from the three
        facts above so every caller reads the same numbers off the same
        result rather than re-deriving them: tier 1 = meeting with video
        and captions this app can fetch itself; tier 2 = meeting with
        video whose captions are YouTube's -- fetchable only by the
        YouTube drip Mac, never by a sweep (a `youtube_lead` verdict is
        always tier 2, since this module never fetches YouTube itself,
        so `captions_found` is always False there regardless of whether
        real captions exist); tier 3 = meeting with video and no
        captions this app can fetch (a tier-3 auto-transcription queue
        candidate); tier 4 = meeting found, no video (the honest
        "meeting-without-video"). `None` when no meeting was found at
        all -- there is no tier for that, it's a separate "no meeting
        found" outcome.
        """
        if not self.meeting_found:
            return None
        if not self.video_found:
            return 4
        if self.platform == "youtube":
            return 2
        if self.captions_found:
            return 1
        return 3


def _host(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    except Exception:  # noqa: BLE001
        return ""


def _is_youtube_host(url: str) -> bool:
    return _host(url) in _YOUTUBE_HOSTS


def _youtube_lead(url: str, note: str) -> VerifyResult:
    return VerifyResult(
        meeting_found=True,
        video_found=True,
        captions_found=False,
        meeting_url=url,
        platform="youtube",
        verdict="youtube_lead",
        evidence=note,
    )


class _YouTubeResolveBlocked(Exception):
    """Raised by `_youtube_resolve_guard()` below instead of letting
    YouTube actually get fetched.

    Real, confirmed gap this closes (found live running this module
    against WO-331's own control set, 2026-09-13): checking whether a
    CANDIDATE url's own host is youtube.com (`_is_youtube_host()`, used
    in `_walk_candidates`) is not enough on its own. A candidate that is
    NOT itself a youtube.com URL -- e.g. a Municode Meetings meeting
    page -- can still internally embed a YouTube video and delegate to
    YouTube from INSIDE that adapter's own `resolve()`.

    Two real, DIFFERENT chokepoints exist, confirmed live -- an earlier
    version of this guard patched only the first and let a real yt-dlp
    fetch through the second on a2gov.org's own Legistar->YouTube
    delegation (City Council, LEGID=14158) before this was caught:
    `YouTubeAssetFinder.resolve(url)` -- the path `civicplus.py`/
    `municode_meetings.py`/`civicweb.py`/`generic_fallback.py` all use
    (via `resolve_via_platform()`); and `YouTubeAssetFinder.
    resolve_video_id(video_id, source_url)` -- the path `legistar.py`
    (a real YouTube link found in an attachments table, or its own
    channel-fallback match) and `primegov.py` (per CLAUDE.md's "PrimeGov
    embeds a YouTube video" wrapper note) call DIRECTLY, bypassing
    `.resolve()` entirely, specifically so they can pass the delegating
    page's own `source_url` through. Both are patched here.
    """

    def __init__(self, url: str):
        self.url = url
        super().__init__(f"blocked a YouTube fetch for {url}")


@contextlib.contextmanager
def _youtube_resolve_guard():
    """Scoped for the duration of one `verify_hub()` call (not a
    permanent process-wide patch, so a caller elsewhere in the app that
    legitimately wants a real YouTube resolve -- e.g. the YouTube drip --
    is unaffected): monkeypatches both `YouTubeAssetFinder.resolve` and
    `YouTubeAssetFinder.resolve_video_id` (see `_YouTubeResolveBlocked`'s
    own docstring for why both) to raise `_YouTubeResolveBlocked` instead
    of calling yt-dlp, then restores the originals on exit, success or
    failure."""
    from .youtube import YouTubeAssetFinder

    original_resolve = YouTubeAssetFinder.resolve
    original_resolve_video_id = YouTubeAssetFinder.resolve_video_id

    async def _blocked(self, url: str):  # noqa: ANN001
        raise _YouTubeResolveBlocked(url)

    async def _blocked_video_id(cls, video_id: str, source_url: str):  # noqa: ANN001
        raise _YouTubeResolveBlocked(f"https://www.youtube.com/watch?v={video_id}")

    YouTubeAssetFinder.resolve = _blocked
    YouTubeAssetFinder.resolve_video_id = classmethod(_blocked_video_id)
    try:
        yield
    finally:
        YouTubeAssetFinder.resolve = original_resolve
        YouTubeAssetFinder.resolve_video_id = original_resolve_video_id


async def _fetch(url: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Returns (html, final_url, error) -- error is None on success. Never
    raises; a fetch failure is just one more thing `verify_hub()` reports
    honestly rather than crashing on."""
    try:
        async with aiohttp.ClientSession(headers=_HEADERS) as session:
            async with session.get(
                url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                if response.status != 200:
                    return None, str(response.url), f"HTTP {response.status}"
                html = await read_capped_text(response)
                return html, str(response.url), None
    except Exception as e:  # noqa: BLE001
        return None, None, f"{type(e).__name__}: {e}"


# --- Per-platform listing walkers -------------------------------------
#
# A listing walker is `async def(hub_url: str) -> List[dict]`, returning
# up to a handful of real candidates newest-first as
# `{"title", "date", "url"}` dicts (the same shape `CalendarCandidate`
# already uses). Registered lazily (`_ensure_walkers_registered()`) so
# importing this module never requires every adapter's own heavy
# dependencies (e.g. `wordninja`) to already be importable in a context
# that only wants one platform's walker.

ListingWalker = Callable[[str], Awaitable[List[dict]]]
_LISTING_WALKERS: Dict[str, ListingWalker] = {}
_walkers_registered = False


def register_listing_walker(platform: str, walker: ListingWalker) -> None:
    _LISTING_WALKERS[platform] = walker


async def _granicus_walker(hub_url: str) -> List[dict]:
    from .granicus import list_recent_video_meetings

    return await list_recent_video_meetings(hub_url)


_CHAMPDS_CUSTOMER_RE = re.compile(r"^/([^/]+)/")


async def _champds_walker(hub_url: str) -> List[dict]:
    from .champds import list_archive_events

    match = _CHAMPDS_CUSTOMER_RE.match(urlparse(hub_url).path)
    if not match:
        return []
    customer = match.group(1)
    events = await list_archive_events(customer)
    return [
        {
            "title": e.get("title") or "",
            "date": e.get("date"),
            "url": e.get("event_url"),
        }
        for e in events
        if e.get("event_url")
    ]


_CIVICWEB_TENANT_RE = re.compile(r"^([^.]+)\.civicweb\.net$")
_CIVICWEB_MEETING_ID_RE = re.compile(r"MeetingInformation\.aspx\?[^\"']*Id=(\d+)")
_CIVICWEB_IDS_TO_CHECK = 8


async def _civicweb_walker(hub_url: str) -> List[dict]:
    """Ported from `~/Documents/rtr-business/research/meeting_url_finder.py`'s
    `find_civicweb_meeting()` (itself a port of `civicweb_meetingtypelist_
    lookup.py`'s `find_video()`) -- real, already-validated prior art from
    a different wave of work (ENUMERATION_METHODS.md's Step 2/Step 3
    runs, §93/§142/§144) that this WO only found *after* independently
    hitting the same CivicWeb "no obvious listing API" gap the hard way
    (see `docs/investigations/wo333_verification_walk.md`). Returns
    candidate meeting-detail URLs only -- the actual video check is left
    to `_walk_candidates()`'s own call into the real, registered
    `civicweb.py` adapter, rather than duplicating its `/api/videolink/`
    logic here a second time.
    """
    match = _CIVICWEB_TENANT_RE.match(_host(hub_url))
    if not match:
        return []
    tenant = match.group(1)
    html, _, err = await _fetch(
        f"https://{tenant}.civicweb.net/Portal/MeetingTypeList.aspx"
    )
    if err or html is None:
        return []
    ids = sorted({int(i) for i in _CIVICWEB_MEETING_ID_RE.findall(html)}, reverse=True)
    return [
        {
            "title": "",
            "date": None,
            "url": f"https://{tenant}.civicweb.net/Portal/MeetingInformation.aspx?Id={mid}",
        }
        for mid in ids[:_CIVICWEB_IDS_TO_CHECK]
    ]


_LEGISTAR_TENANT_RE = re.compile(r"^([^.]+)\.legistar\.com$")


async def _legistar_walker(hub_url: str) -> List[dict]:
    """Ported from `meeting_url_finder.py`'s `find_legistar_meeting()` --
    same prior-art note as `_civicweb_walker()` above. `webapi.legistar.
    com` is a real, public, unauthenticated API (confirmed live there
    2026-08-21, reconfirmed live here 2026-09-13 against a2gov) that
    returns each event's own `EventInSiteURL` -- the real per-meeting
    detail page `legistar.py`'s own `resolve()` already knows how to walk
    to its delegated video (see CLAUDE.md's "Legistar links out to
    Granicus" note). Filtered to `EventDate` before today, same "a future
    meeting's video status lies" fix `find_legistar_meeting()`'s own
    docstring documents."""
    import datetime as _dt

    match = _LEGISTAR_TENANT_RE.match(_host(hub_url))
    if not match:
        return []
    tenant = match.group(1)
    today = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    filter_val = f"EventDate lt datetime'{today}'"
    api_url = (
        (
            f"https://webapi.legistar.com/v1/{tenant}/events"
            f"?$filter={filter_val}&$orderby=EventDate%20desc&$top=10"
        )
        .replace(" ", "%20")
        .replace("'", "%27")
    )
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                api_url, timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                if response.status != 200:
                    return []
                data = await response.json(content_type=None)
    except Exception:  # noqa: BLE001
        logger.warning("Legistar webapi fetch failed for %s", api_url, exc_info=True)
        return []
    if not isinstance(data, list):
        return []
    return [
        {
            "title": event.get("EventBodyName") or "",
            "date": (event.get("EventDate") or "")[:10] or None,
            "url": event.get("EventInSiteURL"),
        }
        for event in data
        if event.get("EventInSiteURL")
    ]


_ESCRIBE_CALENDAR_HEADERS = {
    "User-Agent": _HEADERS["User-Agent"],
    "Content-Type": "application/json",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
}

# First window is generous enough to find a recent meeting on an active
# council (Victoria BC, real live check 2026-09-13: 23 real meetings
# across all types in a 3.5-month window) without over-fetching; the
# fallback widens to ~18 months for a smaller/less frequent tenant before
# giving up -- same "narrow first, widen on empty" shape as other
# walkers' retry limits in this module.
_ESCRIBE_WINDOW_DAYS = 180
_ESCRIBE_FALLBACK_WINDOW_DAYS = 545
_ESCRIBE_DATE_FORMATS = ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d")


async def _escribe_calendar_meetings(host: str, start: str, end: str) -> List[dict]:
    """One call to eScribe's own `MeetingsCalendarView.aspx/GetCalendarMeetings`
    PageMethod -- the same endpoint the "Published Meetings" listing page's
    own calendar widget calls client-side (confirmed live 2026-09-13 by
    reading `pub-victoria.escribemeetings.com`'s own page JS: `events:
    function(info, successCallback, ...)` POSTs `{calendarStartDate,
    calendarEndDate}` here). Returns every real meeting across every
    meeting type in the date range -- Council, committees, boards, all of
    them -- each carrying a real `ID` (GUID), `StartDate`, `MeetingType`,
    and a platform-reported `HasVideo` flag. Confirmed live on all four of
    this WO's real tenants: Victoria BC (`pub-victoria`), Calgary AB
    (`pub-calgary`), Peel Region ON (`pub-peelregion`), Essex County ON
    (`coe-pub`) -- and on a real no-"pub-"-prefix self-hosted tenant,
    Kingsville ON (`kingsville-pub`), confirming the endpoint isn't tied to
    the "pub-" naming convention. Returns `[]` on any HTTP error or
    unparseable response -- a best-effort listing step, not a guaranteed
    one, same posture as this module's other listing walkers.
    """
    url = f"https://{host}/MeetingsCalendarView.aspx/GetCalendarMeetings"
    payload = json.dumps({"calendarStartDate": start, "calendarEndDate": end})
    try:
        async with aiohttp.ClientSession(headers=_ESCRIBE_CALENDAR_HEADERS) as session:
            async with session.post(
                url, data=payload, timeout=aiohttp.ClientTimeout(total=20)
            ) as response:
                if response.status != 200:
                    return []
                data = await response.json(content_type=None)
    except Exception:  # noqa: BLE001
        logger.warning(
            "eScribe GetCalendarMeetings fetch failed for %s", url, exc_info=True
        )
        return []
    items = data.get("d") if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


def _escribe_parse_start(raw: Optional[str]) -> Optional[_dt.datetime]:
    if not raw:
        return None
    for fmt in _ESCRIBE_DATE_FORMATS:
        try:
            return _dt.datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


async def _escribe_walker(hub_url: str) -> List[dict]:
    """WO-343: eScribe's "Published Meetings" listing walker. Real gap this
    closes: `escribe.py`'s own `resolve()` only ever handles ONE already-
    known `Meeting.aspx` page -- given a hub/tenant root (or an embed URL
    like `pub-victoria.escribemeetings.com?fillWidth=1?&wmode=transparent`,
    the shape `find_platform_link()` surfaces from a government's own page)
    it has no way to walk to a specific recent meeting, which is exactly
    WO-333's control-set miss for Victoria BC (`resolved_no_video`: a real
    title found, zero video, because the URL handed to it was never one
    specific meeting). Delegates the actual video/caption check back to
    the real, registered `escribe.py` adapter via `_walk_candidates()` --
    this function only lists real candidate meeting URLs, newest first,
    across every meeting type on the tenant (Council, committees, boards
    alike; eScribe's own listing API has no reliable single "governing
    body" marker across every real tenant checked -- Victoria's own
    highest-volume type is "Committee of the Whole", not "Council" --
    so rather than guess a body name, every real meeting on the tenant is
    a valid candidate and `_walk_candidates()`'s existing WALK_LIMIT stops
    the walk at real network/verification cost, same as every other
    walker in this module).
    """
    host = _host(hub_url)
    if not host.endswith("escribemeetings.com"):
        return []
    today = _dt.datetime.now(_dt.timezone.utc).date()
    end = today.isoformat()
    items = await _escribe_calendar_meetings(
        host, (today - _dt.timedelta(days=_ESCRIBE_WINDOW_DAYS)).isoformat(), end
    )
    if not items:
        items = await _escribe_calendar_meetings(
            host,
            (today - _dt.timedelta(days=_ESCRIBE_FALLBACK_WINDOW_DAYS)).isoformat(),
            end,
        )
    if not items:
        return []

    seen_ids: set = set()
    parsed: List[tuple] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        meeting_id = item.get("ID")
        if not meeting_id or meeting_id in seen_ids:
            continue
        seen_ids.add(meeting_id)
        start_dt = _escribe_parse_start(item.get("StartDate"))
        parsed.append(
            (
                start_dt,
                {
                    "title": item.get("MeetingType") or item.get("MeetingName") or "",
                    "date": start_dt.date().isoformat() if start_dt else None,
                    "url": f"https://{host}/Meeting.aspx?Id={meeting_id}",
                },
            )
        )
    # Newest first -- the API's own response order is not reliably
    # date-sorted (confirmed live 2026-09-13: Victoria's response mixed
    # meeting types out of chronological order), so this walker sorts
    # itself rather than trusting the feed's order the way Granicus's RSS
    # walker can.
    parsed.sort(key=lambda pair: pair[0] or _dt.datetime.min, reverse=True)
    return [candidate for _, candidate in parsed]


def _ensure_walkers_registered() -> None:
    global _walkers_registered
    if _walkers_registered:
        return
    _walkers_registered = True
    register_listing_walker("granicus", _granicus_walker)
    register_listing_walker("champds", _champds_walker)
    register_listing_walker("civicweb", _civicweb_walker)
    register_listing_walker("legistar", _legistar_walker)
    register_listing_walker("escribe", _escribe_walker)


# Any link on a listing/hub page whose href or visible anchor text looks
# like it points at one specific meeting/clip rather than another
# listing -- generalized from WO-331's own step-5 `find_meeting_detail_
# link()` (`scripts/wo331_handcheck.py`) into a real walker: returns
# every match (newest/first-in-document-order first, since every real
# listing page checked so far -- CivicPlus, Municode Meetings, Legistar,
# eScribe -- renders newest-first), not just the first one, so the
# generic walker can actually walk several candidates the same way a
# bespoke one does. Used only when no bespoke listing walker is
# registered for a platform (`_generic_link_scan_walker`), so it's a
# floor under coverage, not a replacement for a real per-platform walker
# -- a bespoke one (Granicus's RSS feed, ChampDS's search API) is always
# preferred where one exists, since it carries a real title/date and
# doesn't depend on a page's own link text/href shape holding up.
_MEETING_DETAIL_HINTS = re.compile(
    r"(MeetingDetail|meeting-detail|MeetingInformation|Meeting\.aspx|"
    r"ViewMeeting|/meeting/|/meetings/|/event/|/events/|clip_id|player/clip|"
    r"MediaPlayer\.php|AgendaViewer\.php|show/\d|/vod/|AgendaViewer|"
    r"agenda-and-minutes|page/[a-z0-9-]+-\d+$)",
    re.IGNORECASE,
)


def _generic_meeting_links(html: str, base_url: str) -> List[dict]:
    soup = BeautifulSoup(html, "html.parser")
    seen: set = set()
    out: List[dict] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        full = urljoin(base_url, href)
        if full in seen or full == base_url:
            continue
        text = a.get_text(" ", strip=True)
        if _MEETING_DETAIL_HINTS.search(full) or _MEETING_DETAIL_HINTS.search(text):
            seen.add(full)
            out.append({"title": text, "date": None, "url": full})
    return out


async def _generic_link_scan_walker(hub_url: str) -> List[dict]:
    html, final_url, err = await _fetch(hub_url)
    if err or html is None:
        return []
    return _generic_meeting_links(html, final_url)


# Guessable first-party agenda/minutes paths (Breadth/WO-332, 2026-09-13:
# 10 of 10 registry-sampled "no-meeting-nor-video" rows checked by hand
# turned out wrong -- 8 of 10 carried "reached, hop links checked, no
# platform link found" even though the government's own site has a real
# agenda page at one of these guessable paths). The access ladder's own
# success test only looks for a VENDOR platform link
# (`find_platform_link()`), so a first-party "Agendas & Minutes" page --
# real content, just no known video vendor embedded on it -- is invisible
# to it and gets written off as "no meeting" instead of the honest
# "meeting found, no video" (tier 4). Same list CivicPlus/Hyland tenants
# are already guessed at elsewhere in this repo's discovery scripts, kept
# short and generic (not CivicPlus-specific) since the fallback path
# below (`_probe_first_party_agenda_pages()`) only promotes to CivicPlus
# when the fetched page's own markup actually says so.
_FIRST_PARTY_AGENDA_PATHS = (
    "/agendacenter",
    "/AgendaCenter",
    "/agendas-minutes",
    "/agendas_minutes",
    "/Agendas-and-Minutes",
    "/government/agendas-minutes",
)

# Same real, confirmed floor phase 3's own catch-all/blank-page check
# uses elsewhere in this project (`docs/investigations/
# passive_discovery_v2.md`'s "Confirmed platforms" section) -- a body
# under this size is indistinguishable from a catch-all/error page
# answering any path with 200.
_CATCH_ALL_BODY_FLOOR = 800

# CivicPlus's own AgendaCenter row marker and static-asset path -- present
# on every real AgendaCenter page regardless of whether the tenant is
# white-labeled onto the government's own domain (the common case;
# CLAUDE.md/civicplus.py's own module note: a white-labeled tenant never
# redirects to a *.civicplus.com host, so `detect_platform()`'s
# domain-only check can't recognize it) or hosted on *.civicplus.com
# directly.
_CIVICPLUS_MARKERS = ("catagendarow", "/areas/agendacenter/")


async def _probe_first_party_agenda_pages(hub_url: str) -> Optional[VerifyResult]:
    """Conductor's fix, WO-332, 2026-09-13: when `find_platform_link()`
    (already tried by the caller) found no known vendor link at all, try
    a short list of guessable first-party agenda/minutes paths on the
    SAME host before concluding "no meeting." A real page found this way
    -- real size, real agenda/minutes content -- is credited as
    `meeting_found=True` even with no video vendor identified (an honest
    tier 4, not "no meeting"); if its own markup is recognizably
    CivicPlus, delegates to the real `civicplus.py` walk instead of
    stopping at "some agenda page, unknown platform."
    """
    parsed = urlparse(hub_url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    for path in _FIRST_PARTY_AGENDA_PATHS:
        candidate = base + path
        html, final_url, err = await _fetch(candidate)
        if err or html is None or len(html) < _CATCH_ALL_BODY_FLOOR:
            continue
        text_lower = html.lower()
        if "agenda" not in text_lower and "minutes" not in text_lower:
            continue
        if any(marker in text_lower for marker in _CIVICPLUS_MARKERS):
            return await _resolve_and_walk(final_url, "civicplus")
        return VerifyResult(
            meeting_found=True,
            video_found=False,
            captions_found=False,
            meeting_url=final_url,
            platform=None,
            verdict="first_party_agenda_page",
            evidence=(
                f"real first-party agenda/minutes page found at {path} "
                "(no known video vendor link on it)"
            ),
        )
    return None


async def _try_listing_walker(hub_url: str, platform: str) -> Optional[VerifyResult]:
    _ensure_walkers_registered()
    walker = _LISTING_WALKERS.get(platform, _generic_link_scan_walker)
    walker_kind = (
        "listing_walked" if platform in _LISTING_WALKERS else "generic_link_scan"
    )
    try:
        candidates = await walker(hub_url)
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "listing walker failed for %s (%s)", hub_url, platform, exc_info=True
        )
        return VerifyResult(
            meeting_found=False,
            video_found=False,
            captions_found=False,
            meeting_url=None,
            platform=platform,
            verdict="listing_walk_failed",
            evidence=f"{type(e).__name__}: {e}",
        )
    if not candidates:
        return None
    return await _walk_candidates(candidates, platform, base_verdict=walker_kind)


async def _walk_candidates(
    candidates: List[dict], platform: str, *, base_verdict: str
) -> VerifyResult:
    checked = 0
    for candidate in candidates[:WALK_LIMIT]:
        url = candidate.get("url") if isinstance(candidate, dict) else None
        if not url:
            continue
        checked += 1
        if _is_youtube_host(url):
            result = _youtube_lead(
                url,
                f"{base_verdict}: candidate {checked} of up to {len(candidates)} is a "
                "YouTube embed -- not fetched, recorded as a lead",
            )
            result.candidates_checked = checked
            return result
        candidate_platform = detect_platform(url)
        if candidate_platform == "unknown":
            candidate_platform = platform
        try:
            finder = get_finder(candidate_platform)
            resolved = await finder.resolve(url)
        except _YouTubeResolveBlocked as e:
            # This candidate wasn't itself a youtube.com URL, but
            # resolving it delegated internally to YouTube -- a real
            # video, just never fetched (see the class docstring).
            result = _youtube_lead(
                e.url,
                f"{base_verdict}: candidate {checked} of up to {len(candidates)} "
                "delegates internally to YouTube -- not fetched, recorded as a lead",
            )
            result.candidates_checked = checked
            return result
        except (CalendarPageError, NoVideoCandidateFound):
            # A candidate that is itself another listing, or a page that
            # honestly checked and found no video -- not a fetch error,
            # just not the answer; keep walking.
            continue
        except Exception:  # noqa: BLE001
            continue
        if resolved.video_url:
            # Report the candidate's OWN resolved platform, not the
            # listing's -- a generic-link-scan or CalendarPageError walk
            # can land on a completely different real video vendor (e.g.
            # a CivicPlus listing whose one real video candidate is a
            # Granicus link), and the platform that actually served the
            # video is the more useful/accurate thing for a caller to
            # record, not the aggregator that merely listed it.
            return VerifyResult(
                meeting_found=True,
                video_found=True,
                captions_found=bool(resolved.segments),
                meeting_url=resolved.source_url or url,
                platform=resolved.platform or candidate_platform,
                verdict=f"{base_verdict}_found_video",
                evidence=(
                    f"{base_verdict}: walked {checked} of {len(candidates)} real "
                    "candidates newest-first, found real video"
                ),
                candidates_checked=checked,
            )
    return VerifyResult(
        meeting_found=checked > 0,
        video_found=False,
        captions_found=False,
        meeting_url=None,
        platform=platform,
        verdict=f"{base_verdict}_no_video" if checked else f"{base_verdict}_empty",
        evidence=(
            f"{base_verdict}: walked {checked} of {len(candidates)} real candidates "
            "newest-first, none had video"
            if checked
            else f"{base_verdict}: zero real candidates found"
        ),
        candidates_checked=checked,
    )


async def _resolve_and_walk(url: str, platform: str) -> VerifyResult:
    """Call platform's resolve() on url and interpret the result. When
    resolve() comes back empty (no video, no title/agenda -- the WO-331
    "this was actually a listing page" shape) or fails outright, falls
    back to that platform's registered listing walker (or the generic
    link-scan one) before giving up -- conductor's fix #2: an
    UNSUPPORTED/RESOLVE_FAILED verdict on a hub must trigger the listing
    walk before any no-video verdict."""
    if _is_youtube_host(url):
        return _youtube_lead(url, "candidate URL is itself a youtube.com/youtu.be host")

    try:
        finder = get_finder(platform)
    except UnsupportedPlatformError as e:
        return VerifyResult(
            meeting_found=False,
            video_found=False,
            captions_found=False,
            meeting_url=None,
            platform=platform,
            verdict="unsupported_platform",
            evidence=str(e),
        )

    try:
        resolved = await finder.resolve(url)
    except _YouTubeResolveBlocked as e:
        # `url` itself passed `detect_platform()` as some OTHER platform
        # (e.g. civicplus/municode_meetings) but its own resolve()
        # delegated internally to YouTube -- a real video, never fetched.
        return _youtube_lead(
            e.url, "resolve() delegates internally to YouTube -- not fetched"
        )
    except CalendarPageError as e:
        # Conductor's fix #1: a CalendarPageError already IS a confirmed
        # real listing -- meeting_found=True regardless of whether any
        # candidate turns out to have video.
        return await _walk_candidates(
            list(e.candidates), platform, base_verdict="calendar_page"
        )
    except NoVideoCandidateFound as e:
        if e.candidates_checked > 0:
            # Real listing, real rows checked, none had video -- a
            # confident, honest "meeting-without-video" (not "no
            # meeting"), same distinction the class docstring draws.
            return VerifyResult(
                meeting_found=True,
                video_found=False,
                captions_found=False,
                meeting_url=None,
                platform=platform,
                verdict="no_video_in_listing",
                evidence=str(e),
                candidates_checked=e.candidates_checked,
            )
        # Zero real candidates on THIS url -- try the platform's own
        # listing walker before concluding there's no meeting at all;
        # this url may simply be the wrong page on this tenant (WO-331's
        # Monroe County FL / Webb County TX finding).
        walked = await _try_listing_walker(url, platform)
        if walked is not None:
            return walked
        return VerifyResult(
            meeting_found=False,
            video_found=False,
            captions_found=False,
            meeting_url=None,
            platform=platform,
            verdict="empty_listing",
            evidence=str(e),
            candidates_checked=0,
        )
    except Exception as e:  # noqa: BLE001
        walked = await _try_listing_walker(url, platform)
        if walked is not None:
            return walked
        return VerifyResult(
            meeting_found=False,
            video_found=False,
            captions_found=False,
            meeting_url=None,
            platform=platform,
            verdict="resolve_error",
            evidence=f"{type(e).__name__}: {e}",
        )

    if resolved.video_url:
        # Same "report the actual resolved platform, not the one that was
        # asked to resolve" fix as `_walk_candidates()`'s found-video
        # branch -- civicplus.py/legistar.py/etc. can internally delegate
        # to a different platform's own `resolve()` (via
        # `resolve_via_platform()`) and return THAT result as-is
        # (`resolved.platform` is the delegated platform's, not the
        # wrapper's -- see `ResolvedMeeting.origin_host`'s own docstring
        # in models.py). Real bug, confirmed live 2026-09-13: a
        # single-candidate CivicPlus row that delegates straight to
        # Granicus reported `platform="civicplus"` instead of
        # `"granicus"` before this fix.
        return VerifyResult(
            meeting_found=True,
            video_found=True,
            captions_found=bool(resolved.segments),
            meeting_url=resolved.source_url or url,
            platform=resolved.platform or platform,
            verdict="resolved",
            evidence="resolve() found real video directly",
        )

    # resolve() succeeded but found no video. Could be a genuine single
    # meeting with no video yet (real title/agenda present), or -- the
    # WO-331 finding -- a listing/hub page whose resolve() quietly
    # returned empty because it was never given one specific meeting.
    walked = await _try_listing_walker(url, platform)
    if walked is not None and walked.meeting_found:
        return walked

    has_real_content = bool(resolved.title) or bool(resolved.agenda_items)
    return VerifyResult(
        meeting_found=has_real_content,
        video_found=False,
        captions_found=False,
        meeting_url=(resolved.source_url or url) if has_real_content else None,
        platform=platform,
        verdict="resolved_no_video" if has_real_content else "resolved_empty",
        evidence=(
            "resolve() succeeded with a real title/agenda but no video_url"
            if has_real_content
            else "resolve() succeeded with no video_url, title or agenda items -- "
            "likely a listing page this platform has no walker for yet"
        ),
    )


async def verify_hub(hub_url: str, platform_hint: Optional[str] = None) -> VerifyResult:
    """The shared step. `hub_url` is a confirmed hub/tenant URL for a
    government (whatever a sweep's phase 3 already confirmed);
    `platform_hint` is that phase's own best guess at the platform, used
    when `detect_platform(hub_url)` itself can't tell (a government page
    that merely embeds/links a platform, rather than being a URL on that
    platform's own domain -- conductor's fix #2's starting point).

    The entire walk runs under `_youtube_resolve_guard()` -- not just the
    top-level hub URL -- so a candidate reached partway through (a
    CalendarPageError pick-list entry, a listing-walker result, the
    ranking-fix's vendor link) that turns out to delegate to YouTube is
    caught the same way, never actually fetched.
    """
    with _youtube_resolve_guard():
        return await _verify_hub_impl(hub_url, platform_hint)


async def _verify_hub_impl(
    hub_url: str, platform_hint: Optional[str] = None
) -> VerifyResult:
    if _is_youtube_host(hub_url):
        return _youtube_lead(hub_url, "hub URL is itself a youtube.com/youtu.be host")

    detected = detect_platform(hub_url)
    candidate_url = hub_url
    platform = detected if detected != "unknown" else platform_hint

    if detected == "unknown":
        # The hub isn't itself shaped like any known platform's own page
        # -- fetch it once and look for the real embedded/linked vendor
        # (WO-331 finding #1: this is exactly how a government page that
        # merely LINKS to iQM2/eScribe/CivicWeb/Granicus/ChampDS gets
        # found, since `find_platform_link()` already does this scan
        # correctly -- the gap was never re-checking it, not the scan
        # itself).
        html, final_url, err = await _fetch(hub_url)
        if err or html is None:
            return VerifyResult(
                meeting_found=False,
                video_found=False,
                captions_found=False,
                meeting_url=None,
                platform=platform_hint,
                verdict="fetch_failed",
                evidence=err or "empty response",
            )
        match = find_platform_link(html, final_url, exclude=frozenset({"youtube"}))
        if match:
            candidate_url, platform = match
        elif platform_hint:
            # No recognizable platform link found by the generic scan,
            # but phase 3 already knows (from some other signal, e.g. a
            # JS-only widget) which platform this hub uses -- try it
            # directly on the hub URL anyway; `_resolve_and_walk()`'s own
            # fallback to a listing walker/generic scan still applies.
            candidate_url, platform = final_url, platform_hint

    if platform is None:
        # WO-332 fix: no vendor link was found anywhere -- before giving
        # up, check whether this government has a real first-party
        # agenda/minutes page at a guessable path (see
        # `_probe_first_party_agenda_pages()`'s own docstring).
        probed = await _probe_first_party_agenda_pages(hub_url)
        if probed is not None:
            return probed
        return VerifyResult(
            meeting_found=False,
            video_found=False,
            captions_found=False,
            meeting_url=None,
            platform=None,
            verdict="no_platform_detected",
            evidence="detect_platform() -> unknown and no platform hint given",
        )

    result = await _resolve_and_walk(candidate_url, platform)

    # Ranking fix (conductor's fix #3): the platform reached is a known
    # aggregator and it found no video -- check the ORIGINAL hub page for
    # a real, non-aggregator video-vendor link and prefer it.
    if platform in AGGREGATOR_PLATFORMS and not result.video_found:
        html, final_url, err = await _fetch(hub_url)
        if not err and html is not None:
            vendor_match = find_platform_link(
                html, final_url, exclude=frozenset({"youtube"}) | AGGREGATOR_PLATFORMS
            )
            if vendor_match:
                vendor_url, vendor_platform = vendor_match
                vendor_result = await _resolve_and_walk(vendor_url, vendor_platform)
                if vendor_result.video_found or (
                    not result.meeting_found and vendor_result.meeting_found
                ):
                    vendor_result.evidence = (
                        f"ranking fix: preferred vendor platform {vendor_platform!r} "
                        f"over aggregator {platform!r} on the same hub page -- "
                        f"{vendor_result.evidence}"
                    )
                    vendor_result.ranking_fix_applied = True
                    return vendor_result

    return result
