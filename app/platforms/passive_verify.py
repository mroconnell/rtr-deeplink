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
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Dict, List, Optional
from urllib.parse import quote, urljoin, urlparse

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
from ..utils.video_hand_check import (
    PASS,
    REJECT,
    GateVerdict,
    assess_video_candidate,
    classify_video_hand_check,
    page_evidence,
    prescreen_homepage_link,
    structural_reject,
)

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

# WO-355 (Ryan, 2026-09-13), "walk deeper": for a government whose newest
# listed meeting turned out off-mission (wrong body, promo, ceremony --
# see `select_on_mission_candidate()` below), a single-candidate walk
# never gives a hand-reader a second real option from the SAME listing.
# `verify_hub(..., deep_walk=True)` reads up to `DEEP_WALK_LISTING_LIMIT`
# listed meetings (newest first, same order every walker already
# produces) and collects up to `DEEP_WALK_VIDEO_COLLECT_LIMIT` that carry
# video, instead of returning at the first one -- opt-in (default
# `deep_walk=False`) so every existing caller/test is unaffected.
DEEP_WALK_LISTING_LIMIT = 15
DEEP_WALK_VIDEO_COLLECT_LIMIT = 3

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
    `video_candidates`: WO-355's "walk deeper" rule change -- populated
    only when `verify_hub(..., deep_walk=True)` walked a listing and
    found at least one real video candidate. Up to `video_collect_limit`
    dicts, newest-first, each `{"title", "date", "url", "platform",
    "captions_found", "duration"}` (`duration` is whatever the walker's
    own candidate dict carried, often None -- no walker fetches a page
    just to learn its runtime). Empty for every other caller/result,
    including a `deep_walk=True` call that found no video at all --
    existing callers that never pass `deep_walk` see no change in
    behavior or shape.

    `video_title`, `video_gate`, `video_gate_reason`, `rejected_video_links`
    (WO-933, 2026-09-21, all default empty): the shared "is this really a
    meeting video?" gate (`app/utils/video_hand_check.py`). `video_gate` is
    "pass", "reject" or "cannot_tell" when a single video found by a bare
    homepage scan was checked, and "" when no such check ran (a hub that is
    itself a known platform's page, or a per-meeting listing walk).
    `video_title` is the resolved video's own title (a Vimeo oEmbed title,
    say) when known. `rejected_video_links` lists every homepage link the
    gate refused on the way, `{"url", "platform", "reason"}` each, so a
    sweep can count them as findings. A "cannot_tell" video is real but
    unverified: `video_found` stays True, `meeting_found` is False, so
    `tier` is None and no caller credits it as a meeting by accident.
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
    video_candidates: List[dict] = field(default_factory=list)
    video_title: Optional[str] = None
    video_gate: str = ""
    video_gate_reason: str = ""
    rejected_video_links: List[dict] = field(default_factory=list)

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
        # WO-348: confirmed live, running this fix's own group-1 rerun --
        # `_verify_hub_impl()`'s own `platform_hint` fallback (used when
        # `detect_platform()` says "unknown" and no vendor link was
        # found) can set `platform="youtube"` from a caller's hint while
        # `candidate_url` stays the ORIGINAL, non-youtube hub page (the
        # hint just means some earlier phase's OWN scan thought this
        # government's site mentions YouTube somewhere -- CLAUDE.md's own
        # documented Aurora, CO false-positive shape). Before this fix,
        # `_blocked()` raised unconditionally for ANY url, so this always
        # produced a `youtube_lead` whose own `meeting_url` was the
        # original hub page, not a real YouTube URL -- 8 real governments
        # in one 1,514-row rerun (Ravenna OH, Helotes TX, Groton CT,
        # Sugar Grove IL, Austell GA, Broadview IL, Blythewood SC, and a
        # PDF-linked case on Bellevue WI) got a fabricated "video found"
        # verdict this way, caught only by this WO's own hand-read gate.
        # Only block a call that is genuinely about to fetch a real
        # youtube.com/youtu.be URL; anything else calls through to the
        # real `resolve()`, which raises its own honest error for a URL
        # that was never a valid YouTube one to begin with.
        if _is_youtube_host(url):
            raise _YouTubeResolveBlocked(url)
        return await original_resolve(self, url)

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

# WO-348 (2026-09-13): CivicWeb/Diligent's real tenant hostname takes (at
# least) three different shapes on file -- `<tenant>.civicweb.net`,
# `<tenant>.community.diligentoneplatform.com`, and, confirmed live this
# WO on Eatwp township PA, `<tenant>.diligent.community` -- and the
# tenant is always the FIRST dns label regardless of which shape it is,
# so one regex covers all three rather than hardcoding `.civicweb.net`.
_CIVICWEB_ANY_TENANT_RE = re.compile(
    r"^([^.]+)\.(?:civicweb\.net|community\.diligentoneplatform\.com|diligent\.community)$"
)

# WO-348 (2026-09-13): confirmed live that a real tenant's own meeting
# listing can sit at EITHER path -- Eatwp township PA's real "Meeting
# Portal" nav link goes to MeetingTypeList.aspx (the only path this
# walker tried before this WO), while Ferris TX and Lower Saucon
# township PA's real "Calendar" nav link goes to MeetingSchedule.aspx
# instead, which came back completely empty from MeetingTypeList.aspx.
# Both real, both live; try both rather than picking one.
_CIVICWEB_LISTING_PATHS = ("Portal/MeetingTypeList.aspx", "Portal/MeetingSchedule.aspx")


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
    match = _CIVICWEB_ANY_TENANT_RE.match(_host(hub_url))
    if not match:
        return []
    origin = f"https://{_host(hub_url)}"
    ids: set[int] = set()
    for path in _CIVICWEB_LISTING_PATHS:
        html, _, err = await _fetch(f"{origin}/{path}")
        if err or html is None:
            continue
        ids |= {int(i) for i in _CIVICWEB_MEETING_ID_RE.findall(html)}
        if ids:
            break
    if not ids:
        return []
    return [
        {
            "title": "",
            "date": None,
            "url": f"{origin}/Portal/MeetingInformation.aspx?Id={mid}",
        }
        for mid in sorted(ids, reverse=True)[:_CIVICWEB_IDS_TO_CHECK]
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


# WO-348: a THIRD real CivicClerk tenant domain shape beyond
# `.portal.`/`.api.` -- confirmed live on Upper Providence Township, PA
# (`upperprovidencetwppa.civicclerk.com`, no infix at all). It 301s
# straight to the `.portal.` host, but the walker is handed the
# pre-redirect URL (phase 3's own confirmed hub), so it needs to
# recognize the bare shape directly rather than relying on a redirect it
# never follows itself. `www.civicclerk.com` is excluded -- that's
# CivicClerk's own corporate/marketing host (`CORPORATE_HOSTS_BY_
# PLATFORM`), never a real tenant.
_CIVICCLERK_TENANT_RE = re.compile(
    r"^(?!www\.)([^.]+)\.(?:(?:portal|api)\.)?civicclerk\.com$"
)


async def _civicclerk_walker(hub_url: str) -> List[dict]:
    """WO-342: ported from `~/Documents/rtr-business/research/
    meeting_url_finder.py`'s `find_civicclerk_meeting()` (itself a port
    of that same directory's earlier `civicclerk_live_lookup.py`'s own
    `find_video()`) -- same prior-art note as the CivicWeb/Legistar
    walkers above. WO-333's own residual miss on this platform was Lake
    County FL, never reached at all (phase 3 left it
    `candidate-not-confirmed`); this closes that gap the same way the
    other two were closed.

    Unlike the original script, this walker doesn't call
    `EventsMedia/{id}` itself for every candidate to decide which one has
    video -- CivicClerk's own Events LIST response already carries a
    real `hasMedia` flag per event, confirmed live 2026-09-13 against two
    real tenants with opposite shapes: southfultonga.api.civicclerk.com
    (event 1773 and 5 of its other 9 most recent events all `hasMedia:
    true`, real `mediaStreamPath` present) and edinburgtx.api.civicclerk.
    com (all 10 of its most recent events `hasMedia: false` -- a real
    tenant that simply doesn't post video, not a broken fetch;
    vancouverwa.portal.civicclerk.com is a second confirmed example of
    the same without-media shape, see BACKLOG_DONE.md's WO-342 entry).
    ighmn.api.civicclerk.com (Inver Grove Heights, MN) is a third real
    with-media tenant, confirmed live the same day: event 2199 sits 4th
    in its own most-recent-10 list (three newer events all `hasMedia:
    false`), which is exactly why sorting hasMedia-first matters here --
    a plain newest-first walk would burn 3 candidates on video-less
    events before ever reaching the one that has video. So this walker
    sorts hasMedia-true events first (newest-first within each group,
    a stable sort over the API's own newest-first order) and leaves the
    actual per-event video/caption check to `_walk_candidates()`'s own
    call into the real, registered `civicclerk.py` adapter -- same
    "don't duplicate the adapter's own logic in the walker" reasoning
    `_civicweb_walker()` already documents.
    """
    match = _CIVICCLERK_TENANT_RE.match(_host(hub_url))
    if not match:
        return []
    tenant = match.group(1)
    now = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    filter_val = quote(f"eventDate lt {now}", safe="")
    orderby_val = quote("eventDate desc", safe="")
    api_url = (
        f"https://{tenant}.api.civicclerk.com/v1/Events"
        f"?$filter={filter_val}&$orderby={orderby_val}&$top=10"
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
        logger.warning("CivicClerk events fetch failed for %s", api_url, exc_info=True)
        return []
    events = data.get("value") if isinstance(data, dict) else None
    if not events:
        return []
    events = [e for e in events if e.get("id") is not None and not e.get("isDeleted")]
    events.sort(key=lambda e: not e.get("hasMedia"))
    return [
        {
            "title": e.get("eventName") or "",
            "date": (e.get("eventDate") or "")[:10] or None,
            "url": f"https://{tenant}.portal.civicclerk.com/event/{e['id']}/media",
        }
        for e in events
    ]


# WO-341: a real, confirmed gap in WO-333's own residual-miss list --
# Monroe County FL and Webb County TX's phase-3-confirmed hub URLs were
# never the real listing page at all (a `/Boards-Committees` page, a
# `/Pay` page -- see docs/investigations/wo333_verification_walk.md's
# "CivicPlus, wrong starting URL" note). `_resolve_and_walk()` already
# falls back to a platform's registered listing walker when the given
# hub URL itself has zero real candidates -- CivicPlus had none
# registered, so it fell all the way through to
# `_probe_first_party_agenda_pages()`'s canonical `/AgendaCenter` guess,
# which 404s for a tenant (like Monroe County's) that doesn't happen to
# use that exact path. This walker instead reads the CONFIRMED page's
# own real site navigation -- every real CivicPlus tenant checked here
# (Hobart IN, Monroe County FL, Webb County TX, Jefferson County WA)
# links its real agenda/video hub from ordinary nav/related-page links,
# not just the one URL phase 3 happened to land on.
_CIVICPLUS_AGENDACENTER_CATEGORY_RE = re.compile(
    # A real category-listing link (e.g. "/AgendaCenter/Board-of-Park-
    # Commissioners-8") -- excludes "/AgendaCenter/PreviousVersions/..."
    # (a per-document view link, same trailing `-\d+` shape but not a
    # listing) and "/AgendaCenter/ViewFile/..." (a direct file link),
    # both real, confirmed noise on every real AgendaCenter page checked.
    r"/AgendaCenter/(?!PreviousVersions|ViewFile)[^\"'#?]+-\d+",
    re.IGNORECASE,
)
_CIVICPLUS_CALENDAR_EID_RE = re.compile(r"/Calendar\.aspx\?EID=\d+", re.IGNORECASE)
_CIVICPLUS_EID_NUM_RE = re.compile(r"EID=(\d+)", re.IGNORECASE)
_CIVICPLUS_CALENDAR_TITLE_RE = re.compile(
    r"<title>\s*Calendar\s*[•\-]\s*([^<]*?)\s*</title>", re.IGNORECASE
)
# Real, confirmed nav-link text this WO found linking a CivicPlus
# tenant's real video hub from an unrelated confirmed page -- Webb
# County TX's own "Commissioners Court Live & Archived Videos"/"Live
# Broadcast & Archives" nav items (found live on its `/327/
# Agendas-Minutes` page, nowhere near the real video hub itself).
# "meeting" added after Monroe County FL confirmed a real, plainer case:
# its own `/meetings` ("BOCC Meetings & Agendas") page, linked from its
# `/291/Boards-Committees` page with no "video"/"broadcast" wording at
# all, is a real listing embedding a direct
# `monroecounty-fl.granicus.com/ViewPublisher.php?view_id=1` link --
# Monroe County's real Calendar.aspx `EID=` events (step 3, tried first
# for a bare calendar walk since it needs no anchor-text match at all)
# turned out to be ordinary county calendar entries (park closures,
# waste collection), not Commission meetings, so this nav-text step is
# what actually finds the real video hub for this tenant.
_CIVICPLUS_VIDEO_NAV_RE = re.compile(r"video|broadcast|webcast|meeting", re.IGNORECASE)

_CIVICPLUS_MAX_AGENDACENTER_CATEGORIES = 4
_CIVICPLUS_MAX_VIDEO_NAV_LINKS = 3
_CIVICPLUS_MAX_CALENDAR_EIDS = 8


async def _add_vendor_candidate(
    add: Callable[[Optional[str], Optional[str], Optional[str]], None],
    vendor_url: str,
    vendor_platform: str,
    *,
    title: Optional[str] = None,
) -> None:
    """A vendor link found by scanning some OTHER page (`find_platform_
    link()`, in `_civicplus_walker()`'s steps 2/3) is very often itself a
    LISTING for that vendor, not one specific meeting -- confirmed live,
    Monroe County FL's own `/meetings` page links straight to
    `monroecounty-fl.granicus.com/ViewPublisher.php?view_id=1`, Granicus's
    channel-listing page, not a single clip. `_walk_candidates()` (the
    caller of this walker's return value) only ever calls a candidate's
    OWN `.resolve()` directly -- it never consults that platform's own
    registered listing walker the way the top-level `_resolve_and_walk()`
    does, so handing it a raw listing URL here would just fail quietly
    (`CalendarPageError`/`NoVideoCandidateFound` caught and skipped, see
    that function's own docstring) instead of ever reaching Granicus's
    real, already-working `_granicus_walker()`.
    Resolves fully here instead (reusing `_resolve_and_walk()`, which
    already falls back to the vendor's own listing walker) and, only when
    that found real video, adds the SPECIFIC resolved meeting's own URL
    as the candidate -- already proven playable, so `_walk_candidates()`'s
    later re-resolve of it is a cheap confirmation, not a second cold
    search. Adds nothing when no real video was found, same as this
    walker's other steps only ever surfacing video-bearing rows.
    """
    result = await _resolve_and_walk(vendor_url, vendor_platform)
    if result.video_found and result.meeting_url:
        add(title, None, result.meeting_url)


async def _civicplus_walker(hub_url: str) -> List[dict]:
    """Given ANY confirmed CivicPlus URL (not necessarily a real
    AgendaCenter listing itself), find a real video-bearing meeting.
    Tries, in order, the highest-fidelity source first:

    1. AgendaCenter category pages linked from the confirmed page (or the
       canonical `/AgendaCenter` guess as a last resort) -- reuses
       `civicplus.py`'s own already-proven `tr.catAgendaRow` parser, so a
       real per-meeting title/date/video link comes back exactly as it
       would from a category page phase 3 confirmed directly.
    2. Nav links whose own anchor text/href suggests a dedicated video
       hub page (confirmed real shape: Webb County TX's "Commissioners
       Court Live & Archived Videos") -- fetched and scanned with
       `find_platform_link()` for a real, non-CivicPlus vendor link
       (confirmed real: a `<iframe src="https://webbcountytx.swagit.
       com">` on exactly this kind of page).
    3. CivicPlus's own `Calendar.aspx` module -- a real, distinct listing
       from AgendaCenter (confirmed live: Monroe County FL and Jefferson
       County WA both link `/Calendar.aspx?EID=<id>` event pages directly
       from their own homepage). Newest EIDs first (EID is assigned
       sequentially at creation time, confirmed by the real numbers found
       on both sites) -- each event page scanned the same way as step 2.

    Stops and returns as soon as a step finds anything, rather than
    spending more real HTTP requests on a lower-fidelity source once a
    higher one already answered -- same "several most-recent candidates,
    not an unbounded scan" posture every walker/retry-limit in this repo
    already uses.
    """
    # Local import: `civicplus.py`'s own module-level imports (granicus.py
    # for `US_STATE_ABBREVIATIONS`, jurisdiction_enrich) are heavier than
    # this module wants to require just to register a walker -- same
    # lazy-import reasoning `_ensure_walkers_registered()`'s own docstring
    # gives for every bespoke walker here.
    from .civicplus import CivicPlusAssetFinder

    html, final_url, err = await _fetch(hub_url)
    if err or html is None:
        return []
    base = f"{urlparse(final_url).scheme}://{urlparse(final_url).netloc}"
    soup = BeautifulSoup(html, "html.parser")

    candidates: List[dict] = []
    seen_urls: set = set()

    def _add(title: Optional[str], date: Optional[str], url: Optional[str]) -> None:
        if not url or url in seen_urls:
            return
        seen_urls.add(url)
        candidates.append({"title": title or "", "date": date, "url": url})

    # Step 1: AgendaCenter category pages.
    finder = CivicPlusAssetFinder()
    category_links = {
        urljoin(base, m.group(0))
        for m in _CIVICPLUS_AGENDACENTER_CATEGORY_RE.finditer(html)
    }
    if not category_links:
        category_links = {f"{base}/AgendaCenter"}
    for category_url in list(category_links)[:_CIVICPLUS_MAX_AGENDACENTER_CATEGORIES]:
        category_html, category_final, category_err = await _fetch(category_url)
        if category_err or category_html is None:
            continue
        category_soup = BeautifulSoup(category_html, "html.parser")
        for row in finder._find_candidate_rows(category_soup, category_final):
            if row.get("url"):
                _add(row.get("title"), row.get("date"), row["url"])
    if candidates:
        return candidates

    # Step 2: video-shaped nav links.
    video_nav_urls: List[str] = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(" ", strip=True)
        href = a["href"]
        if not (
            _CIVICPLUS_VIDEO_NAV_RE.search(text) or _CIVICPLUS_VIDEO_NAV_RE.search(href)
        ):
            continue
        full = urljoin(base, href)
        if full != final_url and full not in video_nav_urls:
            video_nav_urls.append(full)
    for nav_url in video_nav_urls[:_CIVICPLUS_MAX_VIDEO_NAV_LINKS]:
        nav_html, nav_final, nav_err = await _fetch(nav_url)
        if nav_err or nav_html is None:
            continue
        match = find_platform_link(
            nav_html, nav_final, exclude=frozenset({"youtube", "civicplus"})
        )
        if match:
            vendor_url, vendor_platform = match
            await _add_vendor_candidate(_add, vendor_url, vendor_platform)
    if candidates:
        return candidates

    # Step 3: Calendar.aspx?EID= events, newest first.
    eid_links = {
        urljoin(base, m.group(0)) for m in _CIVICPLUS_CALENDAR_EID_RE.finditer(html)
    }
    if not eid_links:
        cal_html, cal_final, cal_err = await _fetch(f"{base}/Calendar.aspx")
        if not cal_err and cal_html:
            eid_links = {
                urljoin(cal_final, m.group(0))
                for m in _CIVICPLUS_CALENDAR_EID_RE.finditer(cal_html)
            }

    def _eid_num(url: str) -> int:
        match = _CIVICPLUS_EID_NUM_RE.search(url)
        return int(match.group(1)) if match else 0

    for eid_url in sorted(eid_links, key=_eid_num, reverse=True)[
        :_CIVICPLUS_MAX_CALENDAR_EIDS
    ]:
        eid_html, eid_final, eid_err = await _fetch(eid_url)
        if eid_err or eid_html is None:
            continue
        match = find_platform_link(
            eid_html, eid_final, exclude=frozenset({"youtube", "civicplus"})
        )
        if match:
            vendor_url, vendor_platform = match
            title_match = _CIVICPLUS_CALENDAR_TITLE_RE.search(eid_html)
            title = title_match.group(1) if title_match else None
            await _add_vendor_candidate(_add, vendor_url, vendor_platform, title=title)

    return candidates


_IQM2_MEETING_LINK_RE = re.compile(r"Detail_Meeting\.aspx\?ID=(\d+)")
# Real row anchor text confirmed live 2026-09-13 on both Monroe County FL
# and Knoxville TN ("Dec 13, 2023 9:00 AM", "Nov 25, 2025 6:00 PM") --
# abbreviated month name, not the `M/D/YYYY` query-string format the
# walker's own `calendar.aspx?...From=/To=` URL uses.
_IQM2_MONTH_ABBREVIATIONS = {
    "Jan": 1,
    "Feb": 2,
    "Mar": 3,
    "Apr": 4,
    "May": 5,
    "Jun": 6,
    "Jul": 7,
    "Aug": 8,
    "Sep": 9,
    "Oct": 10,
    "Nov": 11,
    "Dec": 12,
}
_IQM2_ROW_DATE_RE = re.compile(
    r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{1,2}),\s*(\d{4})"
)
# Narrow-first, widen-on-empty -- same shape as eScribe's own window pair
# above. Narrow (400 days) covers an ordinarily-active tenant (confirmed
# live 2026-09-13: catches Knoxville, TN's real newest meeting, Oct 14
# 2025, ~334 days before this WO's "today"). The wide fallback (3 years)
# exists for a tenant that's gone dormant in the Citizens calendar itself
# -- confirmed live the same day: Monroe County FL's calendar has nothing
# in the narrow window, but the wide one reaches its real Dec 13 2023
# meeting (real video, no captions -- this WO's own with-video control).
_IQM2_WINDOW_DAYS = 400
_IQM2_FALLBACK_WINDOW_DAYS = 1095


async def _iqm2_calendar_candidates(
    origin: str, start: _dt.date, end: _dt.date
) -> List[dict]:
    """One `calendar.aspx?View=List&From=..&To=..` fetch -- the real
    listing endpoint IQM2's own "Meeting Calendar" page calls (confirmed
    live 2026-09-13 against Atlanta, GA's already-known-active tenant,
    Monroe County FL, and Knoxville, TN -- see `_iqm2_walker()`'s own
    docstring). Real, plain server-rendered HTML, no JS execution needed.
    Dates are a US `M/D/YYYY` query format -- confirmed via the page's own
    "View=List&From=1/1/2026&To=12/31/2026" links."""
    url = (
        f"{origin}/Citizens/calendar.aspx?View=List"
        f"&From={start.month}/{start.day}/{start.year}"
        f"&To={end.month}/{end.day}/{end.year}"
    )
    html, _, err = await _fetch(url)
    if err or html is None:
        return []
    soup = BeautifulSoup(html, "html.parser")
    seen_ids: set = set()
    parsed: List[tuple] = []
    for a in soup.find_all("a", href=True):
        match = _IQM2_MEETING_LINK_RE.search(a["href"])
        if not match:
            continue
        meeting_id = match.group(1)
        if meeting_id in seen_ids:
            continue
        seen_ids.add(meeting_id)
        text = a.get_text(" ", strip=True)
        date_match = _IQM2_ROW_DATE_RE.search(text)
        row_date = None
        if date_match:
            month_abbr, day, year = date_match.groups()
            try:
                row_date = _dt.date(
                    int(year), _IQM2_MONTH_ABBREVIATIONS[month_abbr], int(day)
                )
            except ValueError:
                row_date = None
        parsed.append(
            (
                row_date,
                {
                    "title": text,
                    "date": row_date.isoformat() if row_date else None,
                    "url": f"{origin}/Citizens/Detail_Meeting.aspx?ID={meeting_id}",
                },
            )
        )
    # Same "the feed itself isn't reliably ordered, sort ourselves" shape
    # as the eScribe walker above -- confirmed live 2026-09-13: Knoxville's
    # own list mixes committee/task-force/council rows by meeting type,
    # not strictly by date.
    parsed.sort(key=lambda pair: pair[0] or _dt.date.min, reverse=True)
    return [candidate for _, candidate in parsed]


async def _iqm2_walker(hub_url: str) -> List[dict]:
    """WO-344: iQM2's real listing walker -- fixes the "second tenant
    shape" gap WO-333 left. `iqm2.py`'s own `resolve()` only ever handles
    a URL that's already a specific `Detail_Meeting.aspx?ID=`/
    `SplitView.aspx?...MeetingID=` page -- given a tenant root/Citizens-
    portal hub URL (`Default.aspx`, or any other page on the same tenant)
    it has no meeting id to extract and comes back empty, exactly
    WO-333's confirmed Knoxville, TN miss (`resolved_empty`, hub =
    `knoxvillecitytn.iqm2.com/Citizens/Default.aspx`, reached from
    `knoxvilletn.gov`'s own agendas-and-minutes page -- see
    `docs/investigations/wo333_verification_walk.md`). Every real IQM2
    tenant checked (Atlanta GA, Santa Clara County CA, Monroe County FL,
    Knoxville TN) serves the SAME real `calendar.aspx?View=List` endpoint
    regardless of tenant activity level -- confirmed live 2026-09-13 -- so
    this walker only needs the tenant's own origin, not a special case per
    shape. `_walk_candidates()`'s existing real `iqm2.py` adapter does the
    actual video/caption resolve on each candidate, same as every other
    walker in this module.
    """
    parsed_hub = urlparse(hub_url)
    if "iqm2.com" not in parsed_hub.netloc.lower():
        return []
    origin = f"{parsed_hub.scheme}://{parsed_hub.netloc}"
    today = _dt.datetime.now(_dt.timezone.utc).date()
    candidates = await _iqm2_calendar_candidates(
        origin,
        today - _dt.timedelta(days=_IQM2_WINDOW_DAYS),
        today + _dt.timedelta(days=30),
    )
    if not candidates:
        candidates = await _iqm2_calendar_candidates(
            origin,
            today - _dt.timedelta(days=_IQM2_FALLBACK_WINDOW_DAYS),
            today + _dt.timedelta(days=30),
        )
    return candidates


_THS_STREAM_LINK_RE = re.compile(r"/?stream\.php\?location_id=\d+&id=\d+")
_THS_MONTHS = {
    name: i + 1
    for i, name in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ]
    )
}
_THS_ROW_DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|"
    r"November|December)\s+(\d{1,2}),\s*(\d{4})"
)


async def _townhallstreams_walker(hub_url: str) -> List[dict]:
    """WO-344: townhallstreams.com's real listing walker. Real gap this
    closes: `townhallstreams.py`'s own `resolve()` only ever handles a URL
    that already has both `location_id` and `id` query params (one
    specific meeting's own `stream.php` page) -- given the town's own hub
    page (`townhallstreams.com/towns/{slug}`) it finds no video/caption JS
    on that page (it's a listing, not a player) and comes back empty,
    exactly WO-333's confirmed Troy, NH miss (`resolved_empty`, hub =
    `www.townhallstreams.com/towns/troy_nh`, "handed the real town hub
    directly -- still empty" per this WO's brief).
    Confirmed live 2026-09-13: that hub page's own static HTML (no JS
    needed) lists every real meeting for the town as a plain
    `stream.php?location_id={town}&id={meeting}` link, with the meeting's
    real title AND date as the anchor's own visible text (e.g. "Board of
    Selectmen September 17, 2026 - 06:00 pm to 09:00 pm (EST)") -- 131 real
    rows found for Troy, NH alone, several dated in the future (upcoming
    scheduled meetings with no recording yet), so this walker filters to
    `date <= today` before handing candidates to `_walk_candidates()`,
    same "a future meeting's video status lies" filter the Legistar walker
    above already applies for the same reason.
    """
    if "townhallstreams.com" not in urlparse(hub_url).netloc.lower():
        return []
    html, final_url, err = await _fetch(hub_url)
    if err or html is None:
        return []
    soup = BeautifulSoup(html, "html.parser")
    today = _dt.datetime.now(_dt.timezone.utc).date()
    parsed: List[tuple] = []
    seen: set = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not _THS_STREAM_LINK_RE.search(href):
            continue
        full_url = urljoin(final_url, href)
        if full_url in seen:
            continue
        seen.add(full_url)
        text = a.get_text(" ", strip=True)
        date_match = _THS_ROW_DATE_RE.search(text)
        row_date = None
        if date_match:
            month_name, day, year = date_match.groups()
            try:
                row_date = _dt.date(int(year), _THS_MONTHS[month_name], int(day))
            except ValueError:
                row_date = None
        if row_date is not None and row_date > today:
            # Upcoming, not-yet-recorded meeting -- see the docstring's
            # "a future meeting's video status lies" note.
            continue
        parsed.append(
            (
                row_date,
                {
                    "title": text,
                    "date": row_date.isoformat() if row_date else None,
                    "url": full_url,
                },
            )
        )
    parsed.sort(key=lambda pair: pair[0] or _dt.date.min, reverse=True)
    return [candidate for _, candidate in parsed]


_CABLECAST_FASTBOOT_SHOW_LINK_RE = re.compile(r'/show/\d+(?:\?[^"\'\s]*)?')
# Mirrors cablecast.py's own `_FASTBOOT_TITLE_DATE_RE` (kept as a
# separate compiled copy rather than importing it, since this module
# lazily imports each platform's adapter module and shouldn't need
# cablecast.py's own regex module-level just to use one pattern).
_FASTBOOT_TITLE_DATE_RE_MIRROR = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


async def _cablecast_walker(hub_url: str) -> List[dict]:
    """WO-344: a listing walker for Cablecast's third real template (the
    "cablecast-public-site" Ember/FastBoot app mounted at a custom
    domain's own root -- see `cablecast.py`'s own module docstring for the
    full investigation, confirmed live 2026-09-13 on Dyersville, IA).
    Real gap this closes: neither of `cablecast.py`'s existing resolve
    paths has a listing/hub concept at all (both need an already-known
    show id) -- given the tenant's own root page, this walker fetches it
    and scans for real `/show/{id}` links, which the FastBoot app's own
    server-side rendering already embeds in the plain HTML (confirmed
    live: a bare `curl`/`aiohttp` GET of Dyersville's root page returns
    128 real `/show/{id}` links, no JS execution needed) in newest-first
    document order (confirmed: the first link is the tenant's own newest
    show). Each link's own real anchor text already carries the meeting's
    title AND date as one string ("City Council Meeting 2026-09-08"),
    matching the real title shape `cablecast.py`'s own FastBoot resolve
    path extracts from the per-show embed page -- reused here as this
    walker's own `title`/`date`, though `_walk_candidates()`'s real
    `resolve()` call is still what confirms video/captions, not this
    listing step. This walker is not scoped to the FastBoot template
    specifically (it would also find real `/show/` links on a Remix
    tenant's own root page) -- harmless either way, since
    `_walk_candidates()` always re-resolves each candidate through the
    real, registered `cablecast.py` adapter regardless of which template
    actually serves it.
    """
    if "cablecast.tv" not in urlparse(hub_url).netloc.lower():
        # Scoped to the confirmed real *.cablecast.tv host family for now
        # -- a custom-domain Cablecast tenant (e.g. Edison, NJ's
        # `cablecast.edisonnj.org`) is real (see cablecast.py's own
        # `detect_platform()` note) but this walker has no confirmed real
        # example of one serving this same root-listing shape yet, so it
        # declines rather than guessing.
        return []
    parsed_hub = urlparse(hub_url)
    root_url = f"{parsed_hub.scheme}://{parsed_hub.netloc}/"
    html, final_url, err = await _fetch(root_url)
    if err or html is None:
        return []
    soup = BeautifulSoup(html, "html.parser")
    seen: set = set()
    out: List[dict] = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not _CABLECAST_FASTBOOT_SHOW_LINK_RE.fullmatch(href):
            continue
        full_url = urljoin(final_url, href)
        text = a.get_text(" ", strip=True)
        if not text:
            # Real pages checked (Dyersville) render each show as TWO
            # anchors to the same href -- an image link with no text, and
            # a text link right after it. Skip the empty one WITHOUT
            # marking the href seen -- real bug fixed here 2026-09-13:
            # marking it seen on the empty-text anchor discarded the very
            # next (real-title) anchor to the same href too, since it hit
            # the dedup check first. The real title-bearing anchor is the
            # one this walker keeps.
            continue
        if full_url in seen:
            continue
        seen.add(full_url)
        date_match = _FASTBOOT_TITLE_DATE_RE_MIRROR.search(text)
        out.append(
            {
                "title": text,
                "date": date_match.group(0) if date_match else None,
                "url": full_url,
            }
        )
    return out


async def _invintus_walker(hub_url: str) -> List[dict]:
    """WO-922: a listing walker for an Invintus tenant. The hub is either
    a `player.invintus.com/?clientID=N` URL (no eventID), or a government
    page that embeds Invintus (the Oregon Legislature's video page and
    wiseye.org both carry the tenant's `clientID` in their own markup).
    Lists the tenant's recent published events newest-first through
    `Search/general` (see `invintus.py`'s hub-listing comment), and hands
    back each event's player URL, which `InvintusAssetFinder.resolve()`
    then confirms. For a known state-legislature tenant only legislative
    meetings are returned (WisconsinEye also carries courts, campaigns
    and news conferences). A tenant with no events, or a page that names
    no Invintus client, returns []."""
    from .invintus import (
        extract_invintus_client_id,
        is_invintus_hub_url,
        list_recent_events,
        parse_invintus_ids,
    )

    client_id: Optional[str] = None
    if is_invintus_hub_url(hub_url):
        client_id = parse_invintus_ids(hub_url)[0]
    else:
        html, _final_url, err = await _fetch(hub_url)
        if err or html is None:
            return []
        client_id = extract_invintus_client_id(html)
    if not client_id:
        return []
    return await list_recent_events(client_id)


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
    register_listing_walker("civicclerk", _civicclerk_walker)
    register_listing_walker("civicplus", _civicplus_walker)
    register_listing_walker("iqm2", _iqm2_walker)
    register_listing_walker("townhallstreams", _townhallstreams_walker)
    register_listing_walker("cablecast", _cablecast_walker)
    register_listing_walker("invintus", _invintus_walker)


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
#
# `/videos/\d` added WO-341, 2026-09-13: Swagit's own per-meeting URL
# shape (`{tenant}.swagit.com/videos/{id}`, confirmed live on Webb County
# TX's real "Commissioners Court Meeting"/"Commissioners Court Special
# Meeting" rows) wasn't matched by anything above -- a bare Swagit tenant
# root redirects to its own `/views/{id}` archive LISTING page (no
# registered Swagit listing walker exists yet), so without this the
# generic scan silently found zero candidates on a page that lists real,
# on-mission meetings. Scoped the same way `show/\d` is (a path segment
# followed by a real digit), not a bare `/videos/` substring, so a
# `/videos/{id}/transcript` or `/videos/{id}/agenda` sibling link still
# matches too (harmless: `_walk_candidates()` just spends one extra,
# cheap resolve() call on it before moving to the next real candidate).
_MEETING_DETAIL_HINTS = re.compile(
    r"(MeetingDetail|meeting-detail|MeetingInformation|Meeting\.aspx|"
    r"ViewMeeting|/meeting/|/meetings/|/event/|/events/|clip_id|player/clip|"
    r"MediaPlayer\.php|AgendaViewer\.php|show/\d|/vod/|AgendaViewer|"
    r"agenda-and-minutes|page/[a-z0-9-]+-\d+$|/videos/\d)",
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

# --- WO-348: "look one hop deeper" ------------------------------------
#
# WO-347's 60-government hand audit (`research/wo347_audit_sample.csv`)
# found the pipeline's two negative verdicts -- "nothing walkable" (a
# confirmed hub whose walk came back empty) and "candidate-not-confirmed"
# (phase 3 tried a candidate and rejected it) -- wrong most of the time:
# 13 of 20 and 17 of 20. WO-348 measured WHY on the 30 wrong rows, live
# (`research/wo348_hop_measurements.csv`): of 24 rows with a real,
# fetchable page to measure from (one row was skipped rather than
# fetching a youtube.com URL -- see this WO's own report), 3 were
# already-fixed or walker-accuracy gaps at the SAME page (no real hop),
# and of the rest, ~20 were reachable by ONE direct link from the page
# the pipeline had already stopped at -- a real nav/content anchor whose
# text was almost always some combination of "agenda", "minutes",
# "meeting", "council", "board", "committee", "calendar", "document
# center" or "portal" -- with a handful needing a second hop through an
# intermediate section page (e.g. "Government" -> a department page ->
# the real agendas/minutes page). Never a guess: every keyword below is
# the literal (or near-literal) anchor text of a real link that led to a
# real government meetings page, confirmed live this WO.
#
# The French table is NOT measured from this audit (no French-language
# tenant was in the 30 wrong rows) -- it generalizes the same real
# pattern to Francophone Canadian municipalities using standard municipal
# vocabulary, per this WO's brief. Flagged here, and in the methods
# writeup, as unconfirmed-by-audit so a later reader doesn't mistake it
# for a measured finding the way the English table is.
_HOP_WEIGHTS_EN: tuple[tuple[str, float], ...] = (
    ("agenda", 3.0),
    ("minutes", 3.0),
    ("meeting", 2.5),
    ("calendar", 1.5),
    ("document center", 1.5),
    ("meeting portal", 1.5),
    ("zoning", 1.0),
    ("council", 1.0),
    ("board", 1.0),
    ("committee", 1.0),
    ("supervisors", 1.0),
    ("document", 0.75),
    ("portal", 0.75),
    ("government", 0.5),
    ("city administrator", 0.5),
    ("clerk", 0.5),
)
_HOP_WEIGHTS_FR: tuple[tuple[str, float], ...] = (
    ("ordre du jour", 3.0),
    ("procès-verbaux", 3.0),
    ("proces-verbaux", 3.0),
    ("procès-verbal", 3.0),
    ("séances", 2.5),
    ("seances", 2.5),
    ("réunion", 2.5),
    ("reunion", 2.5),
    ("conseil", 1.0),
    ("comité", 1.0),
    ("comite", 1.0),
    ("calendrier", 1.5),
    ("greffe", 0.5),
)
_HOP_WEIGHTS = _HOP_WEIGHTS_EN + _HOP_WEIGHTS_FR

# WO-348: bound the whole deeper-hop mechanism the same way every other
# retry limit in this module is bounded (WALK_LIMIT, _RETRY_LIMIT, ...) --
# per the brief, at most this many extra fetches per government, not per
# call site, so a government that fails the guessable-path probe AND the
# listing-walker fallback still costs at most 3 extra requests total.
_MAX_DEEPER_FETCHES = 3

# Known third-party bill-pay vendors a small government's own site
# sometimes links prominently (sometimes MORE prominently than its own
# agenda page) -- never a real meetings page, so never worth an extra
# fetch. Same "payment-portal guard" phase 3's own targeted scripts
# already carry.
_PAYMENT_PORTAL_HOSTS = frozenset(
    {
        "paymentus.com",
        "xpress-pay.com",
        "municipalonlinepayments.com",
        "invoicecloud.com",
        "govhub.com",
        "citypay.com",
        "officialpayments.com",
        "grantstreet.com",
        "paygov.us",
        "clickpay.com",
        "govpaynow.com",
    }
)


def _is_payment_portal(url: str) -> bool:
    host = _host(url)
    return any(host == h or host.endswith("." + h) for h in _PAYMENT_PORTAL_HOSTS)


def _score_hop_link(text: str, href: str) -> float:
    hay = f"{(text or '').lower()} {(href or '').lower()}"
    return sum(weight for keyword, weight in _HOP_WEIGHTS if keyword in hay)


def _extract_hop_candidates(
    html: str, base_url: str, *, exclude_urls: frozenset[str] = frozenset()
) -> List[tuple[float, str, str]]:
    """Score every real `<a href>` on `html` against `_HOP_WEIGHTS` and
    return `(score, absolute_url, anchor_text)` tuples, highest first.
    Never returns a youtube.com/youtu.be link -- a YouTube lead is
    handled elsewhere (as a `youtube_lead` verdict, never fetched), not
    as a hop candidate to follow."""
    soup = BeautifulSoup(html, "html.parser")
    base_norm = base_url.rstrip("/")
    seen: set[str] = set()
    out: List[tuple[float, str, str]] = []
    for a in soup.find_all("a", href=True):
        href = (a.get("href") or "").strip()
        if not href or href.startswith("#") or href.lower().startswith("javascript:"):
            continue
        abs_url = urljoin(base_url, href)
        if _is_youtube_host(abs_url) or _is_payment_portal(abs_url):
            continue
        norm = abs_url.rstrip("/")
        if norm == base_norm or norm in exclude_urls or norm in seen:
            continue
        text = a.get_text(" ", strip=True)
        score = _score_hop_link(text, href)
        if score <= 0:
            continue
        seen.add(norm)
        out.append((score, abs_url, text[:120]))
    out.sort(key=lambda t: -t[0])
    return out


def _random_nonsense_path() -> str:
    import random
    import string

    return (
        "/" + "".join(random.choices(string.ascii_lowercase, k=24)) + "-rtr-wo348-probe"
    )


async def _catchall_signature(base_url: str) -> Optional[tuple[int, str]]:
    """A cheap catch-all/parked-template detector -- fetch one nonsense
    path on the same host and remember its (length, hash); a deeper-hop
    candidate whose response matches this signature is the same
    catch-all template answering every path with 200, not a real page.
    Same real, confirmed shape phase 3's own `catchall_signature()`
    already uses (`scripts/wo337_targeted.py`)."""
    import hashlib

    parsed = urlparse(base_url)
    probe_url = f"{parsed.scheme}://{parsed.netloc}{_random_nonsense_path()}"
    html, _, err = await _fetch(probe_url)
    if err or html is None:
        return None
    return len(html), hashlib.sha256(html.encode("utf-8", "replace")).hexdigest()


def _is_catchall(html: str, sig: Optional[tuple[int, str]]) -> bool:
    if sig is None:
        return False
    import hashlib

    length, hsh = sig
    if len(html) != length:
        return False
    return hashlib.sha256(html.encode("utf-8", "replace")).hexdigest() == hsh


# WO-348: proving the fix against WO-347's real 40 negative-class rows
# hit this live, in both directions: Fernie BC's real agenda page never
# spells out "British Columbia" -- only "BC" -- while Ephrata township
# PA's real homepage never spells out "PA" -- only "Pennsylvania". A bare
# `state.lower() in text` substring check (the same shape `scripts/
# wo273_targeted.py`'s own `name_matches()` already uses) misses
# whichever form the government's own page didn't happen to use. Accept
# either form; the abbreviation is matched as a whole word (`\bpa\b`),
# not a bare substring, since a 2-letter code is otherwise a real
# false-positive risk (it could match inside any unrelated word).
_US_STATE_ABBREVIATIONS: dict[str, str] = {
    "alabama": "al",
    "alaska": "ak",
    "arizona": "az",
    "arkansas": "ar",
    "california": "ca",
    "colorado": "co",
    "connecticut": "ct",
    "delaware": "de",
    "florida": "fl",
    "georgia": "ga",
    "hawaii": "hi",
    "idaho": "id",
    "illinois": "il",
    "indiana": "in",
    "iowa": "ia",
    "kansas": "ks",
    "kentucky": "ky",
    "louisiana": "la",
    "maine": "me",
    "maryland": "md",
    "massachusetts": "ma",
    "michigan": "mi",
    "minnesota": "mn",
    "mississippi": "ms",
    "missouri": "mo",
    "montana": "mt",
    "nebraska": "ne",
    "nevada": "nv",
    "new hampshire": "nh",
    "new jersey": "nj",
    "new mexico": "nm",
    "new york": "ny",
    "north carolina": "nc",
    "north dakota": "nd",
    "ohio": "oh",
    "oklahoma": "ok",
    "oregon": "or",
    "pennsylvania": "pa",
    "rhode island": "ri",
    "south carolina": "sc",
    "south dakota": "sd",
    "tennessee": "tn",
    "texas": "tx",
    "utah": "ut",
    "vermont": "vt",
    "virginia": "va",
    "washington": "wa",
    "west virginia": "wv",
    "wisconsin": "wi",
    "wyoming": "wy",
    "alberta": "ab",
    "british columbia": "bc",
    "manitoba": "mb",
    "new brunswick": "nb",
    "newfoundland and labrador": "nl",
    "nova scotia": "ns",
    "ontario": "on",
    "prince edward island": "pe",
    "quebec": "qc",
    "saskatchewan": "sk",
}
_US_STATE_ABBREVIATIONS_REVERSED = {v: k for k, v in _US_STATE_ABBREVIATIONS.items()}


def _state_hit(text: str, state: str) -> bool:
    state_lower = state.lower().strip()
    if state_lower in text:
        return True
    # Try the other form (full name -> abbreviation, or vice versa),
    # matched as a whole word for the (usually 2-letter) abbreviation so
    # it can't false-positive-match inside an unrelated word.
    other = _US_STATE_ABBREVIATIONS.get(state_lower) or (
        _US_STATE_ABBREVIATIONS_REVERSED.get(state_lower)
        if len(state_lower) <= 3
        else None
    )
    if not other:
        return False
    if len(other) <= 3:
        return re.search(rf"\b{re.escape(other)}\b", text) is not None
    return other in text


def _name_state_matches(html: str, name: Optional[str], state: Optional[str]) -> bool:
    """Same shape as `scripts/wo273_targeted.py`'s `name_matches()` --
    reimplemented here (not imported) so this module stays independent
    of the wo3NN script family's own import chain. Only applied when a
    caller actually has a government name/state to check against (the
    rerun scripts do; a bare `verify_hub()` call without one skips this
    and relies on the floor/keyword/catch-all checks alone)."""
    if not html or not name:
        return True
    text = html.lower()
    name_tokens = re.findall(r"[a-z]+", name.lower())
    name_hit = any(len(t) > 2 and t in text for t in name_tokens)
    if not state:
        return name_hit
    return name_hit and _state_hit(text, state)


_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)


def _has_agenda_minutes_content(html: str, text_lower: Optional[str] = None) -> bool:
    """WO-348's own proof run (`research/wo348_hop_measurements.csv`,
    rerunning the fix against WO-347's real 40 negative-class rows) found
    real evidence both ways on the bare "agenda"/"minutes"/"meeting"
    keyword question: requiring "agenda" or "minutes" ANYWHERE in the
    body is the right floor (accepting a bare "meeting" anywhere let a
    real false positive through -- Argyle WI's site-wide nav mentions
    "meeting" on every page via a "Village Board Meeting" boilerplate
    link, which wrongly credited a Community Building rental-form page;
    Plainsboro NJ's own nav did the same to a Museum Youth Advisory
    Council page). But "agenda"/"minutes" alone is too strict: Woodruff
    UT's real /meetings/ page and Doylestown PA's real IQM2 Meeting
    Calendar page both render their actual agenda/minutes content via a
    JS-loaded public-meeting-notice widget (Utah's own `utah.gov/pmn/`
    system, and IQM2's own calendar widget respectively) that never puts
    the literal words "agenda"/"minutes" in the plain-fetched HTML at
    all. The real, confirmed distinguishing signal (checked live on all
    four): a page-SPECIFIC `<title>`/`<h1>` mentioning "meeting" is a
    strong signal (Woodruff's is literally "Meetings"; Doylestown's is
    "Meeting Calendar"), while sitewide nav boilerplate never reaches the
    title or the page's own first heading (Argyle's and Plainsboro's
    titles are about a rental form and a youth council, not a meeting)."""
    text_lower = text_lower if text_lower is not None else html.lower()
    if "agenda" in text_lower or "minutes" in text_lower:
        return True
    title_match = _TITLE_RE.search(html)
    if title_match and "meeting" in title_match.group(1).lower():
        return True
    h1_match = _H1_RE.search(html)
    return bool(h1_match and "meeting" in h1_match.group(1).lower())


async def _deeper_hop_search(
    html: str,
    base_url: str,
    *,
    exclude_urls: frozenset[str] = frozenset(),
    name: Optional[str] = None,
    state: Optional[str] = None,
) -> Optional[VerifyResult]:
    """WO-348's "look one hop deeper" fix. `html`/`base_url` are a page
    the pipeline already stopped at (a confirmed hub, or a homepage with
    no known vendor link). Scores every link on it against
    `_HOP_WEIGHTS`, and follows up to `_MAX_DEEPER_FETCHES` of the
    highest-scoring ones, applying the same evidence checks phase 3 uses
    (800-byte floor, catch-all guard, optional name+state match) before
    crediting a deeper page as a real meeting/agenda page. Returns a
    `VerifyResult` (tier 4 -- meeting found, no video identified from
    this page alone) for the first candidate that passes, or `None` if
    none did. Never fetches a youtube.com/youtu.be URL or a known
    payment-portal host (`_extract_hop_candidates()`'s own guards).
    """
    candidates = _extract_hop_candidates(html, base_url, exclude_urls=exclude_urls)
    if not candidates:
        return None
    catchall_sig = await _catchall_signature(base_url)
    checked = 0
    for score, url, text in candidates:
        if checked >= _MAX_DEEPER_FETCHES:
            break
        checked += 1
        deep_html, final_url, err = await _fetch(url)
        if err or deep_html is None or len(deep_html) < _CATCH_ALL_BODY_FLOOR:
            continue
        if _is_catchall(deep_html, catchall_sig):
            continue
        text_lower = deep_html.lower()
        if not _has_agenda_minutes_content(deep_html, text_lower):
            continue
        if not _name_state_matches(deep_html, name, state):
            continue
        return VerifyResult(
            meeting_found=True,
            video_found=False,
            captions_found=False,
            meeting_url=final_url,
            platform=None,
            verdict="hop_deeper_found",
            evidence=(
                f"one hop deeper (score {score:.1f}, link text {text!r}) found a "
                f"real agenda/minutes page at {url} that the direct scan missed"
            ),
            candidates_checked=checked,
        )
    return None


async def _try_deeper_hop_on_url(
    url: str, *, name: Optional[str] = None, state: Optional[str] = None
) -> Optional[VerifyResult]:
    """Fetch `url` (a hub/candidate page a give-up branch is about to
    stop at) and run `_deeper_hop_search()` on it. A small convenience
    wrapper for the several `_resolve_and_walk()` give-up points that
    don't already have the page's HTML in hand (unlike
    `_probe_first_party_agenda_pages()`'s caller, which always does)."""
    if _is_youtube_host(url):
        return None
    html, final_url, err = await _fetch(url)
    if err or html is None:
        return None
    return await _deeper_hop_search(html, final_url or url, name=name, state=state)


_AUDIO_ONLY_EXTENSIONS = (".mp3", ".wav", ".m4a", ".aac", ".wma", ".ogg")


def _looks_like_audio_only_url(url: str) -> bool:
    return urlparse(url).path.lower().endswith(_AUDIO_ONLY_EXTENSIONS)


async def _confirm_not_audio_only(url: str) -> bool:
    """WO-347 finding, fixed here: a resolved `video_url` can be a real,
    live audio-only file -- confirmed live, Olmos Park city TX's
    CivicClerk listing walker returned a `video_url` ending in `.mp3`
    whose own `Content-Type: audio/mp3` header confirms it (a real 58 MB
    file, the exact shape `civicclerk.py`'s own module docstring already
    documents for Highland, CA). Returns True when it's safe to credit
    the URL as real video, False when it's confirmed (or presumed, on a
    failed HEAD) audio. Only ever a HEAD request -- never downloads the
    file itself (this project's "never download a media file" rule)."""
    if not _looks_like_audio_only_url(url):
        return True
    try:
        async with aiohttp.ClientSession(headers=_HEADERS) as session:
            async with session.head(
                url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=15)
            ) as response:
                content_type = (response.headers.get("Content-Type") or "").lower()
    except Exception:  # noqa: BLE001
        # HEAD failed -- the extension alone is already real evidence of
        # audio; treat as audio (the safer wrong answer: a missed real
        # video, not a wrongly-queued audio-only file -- Ryan's "only
        # meetings with video become pages" rule).
        return False
    return not content_type.startswith("audio/")


async def _probe_first_party_agenda_pages(
    hub_url: str,
    *,
    home_html: Optional[str] = None,
    home_final_url: Optional[str] = None,
    name: Optional[str] = None,
    state: Optional[str] = None,
) -> Optional[VerifyResult]:
    """Conductor's fix, WO-332, 2026-09-13: when `find_platform_link()`
    (already tried by the caller) found no known vendor link at all, try
    a short list of guessable first-party agenda/minutes paths on the
    SAME host before concluding "no meeting." A real page found this way
    -- real size, real agenda/minutes content -- is credited as
    `meeting_found=True` even with no video vendor identified (an honest
    tier 4, not "no meeting"); if its own markup is recognizably
    CivicPlus, delegates to the real `civicplus.py` walk instead of
    stopping at "some agenda page, unknown platform."

    WO-348 (2026-09-13) adds two more stages, run in order, before giving
    up: (1) check the HOME page's own body (not just guessable subpaths)
    for real agenda/minutes content -- confirmed live on Ephrata
    township, PA, whose real content sits directly on its homepage, not
    a subpath any guessable-path list would find; (2) `_deeper_hop_search()`
    -- follow the home page's own highest-scoring real links (see that
    function's docstring) before concluding "no meeting." `home_html`/
    `home_final_url` let a caller that already fetched the hub page (the
    `detect_platform() == "unknown"` branch in `_verify_hub_impl` always
    has) pass it in rather than fetching it a second time.
    """
    parsed = urlparse(hub_url)
    base = f"{parsed.scheme}://{parsed.netloc}"

    if home_html is None:
        home_html, home_final_url, _err = await _fetch(hub_url)

    # Stage 0 (WO-348): the home page's own body, not just a guessable
    # subpath -- Ephrata township PA's real agenda PDFs sit directly on
    # its homepage.
    if home_html is not None and len(home_html) >= _CATCH_ALL_BODY_FLOOR:
        text_lower = home_html.lower()
        if ("agenda" in text_lower or "minutes" in text_lower) and _name_state_matches(
            home_html, name, state
        ):
            if any(marker in text_lower for marker in _CIVICPLUS_MARKERS):
                return await _resolve_and_walk(home_final_url or hub_url, "civicplus")
            return VerifyResult(
                meeting_found=True,
                video_found=False,
                captions_found=False,
                meeting_url=home_final_url or hub_url,
                platform=None,
                verdict="first_party_agenda_page",
                evidence=(
                    "real agenda/minutes content found directly on the home page "
                    "(no known video vendor link on it)"
                ),
            )

    for path in _FIRST_PARTY_AGENDA_PATHS:
        candidate = base + path
        html, final_url, err = await _fetch(candidate)
        if err or html is None or len(html) < _CATCH_ALL_BODY_FLOOR:
            continue
        text_lower = html.lower()
        if not _has_agenda_minutes_content(html, text_lower):
            continue
        if not _name_state_matches(html, name, state):
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

    # Stage 2 (WO-348): the guessable-path list came up empty -- follow
    # the home page's own highest-scoring real links one hop deeper
    # before giving up.
    if home_html is not None:
        hopped = await _deeper_hop_search(
            home_html,
            home_final_url or hub_url,
            name=name,
            state=state,
        )
        if hopped is not None:
            return hopped
    return None


async def _try_listing_walker(
    hub_url: str,
    platform: str,
    *,
    name: Optional[str] = None,
    state: Optional[str] = None,
    deep_walk: bool = False,
    listing_limit: Optional[int] = None,
    video_collect_limit: Optional[int] = None,
) -> Optional[VerifyResult]:
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
    return await _walk_candidates(
        candidates,
        platform,
        base_verdict=walker_kind,
        name=name,
        state=state,
        deep_walk=deep_walk,
        listing_limit=listing_limit,
        video_collect_limit=video_collect_limit,
    )


def _candidate_summary(
    *, title, date, url, platform, captions_found, duration=None, lead=False
) -> dict:
    """One entry of `VerifyResult.video_candidates` -- see that field's
    docstring for the shape. `duration` is whatever the listing candidate
    dict already carried (most walkers don't have it); never fetched
    just to learn it."""
    return {
        "title": title,
        "date": date,
        "url": url,
        "platform": platform,
        "captions_found": captions_found,
        "duration": duration,
        "lead": lead,
    }


async def _walk_candidates(
    candidates: List[dict],
    platform: str,
    *,
    base_verdict: str,
    name: Optional[str] = None,
    state: Optional[str] = None,
    deep_walk: bool = False,
    listing_limit: Optional[int] = None,
    video_collect_limit: Optional[int] = None,
) -> VerifyResult:
    """Walks `candidates` newest-first, resolving each until it finds real
    video. Default behavior (`deep_walk=False`) is unchanged from WO-333/
    341: stop and return at the FIRST candidate with real video, checking
    at most `WALK_LIMIT`.

    WO-355 "walk deeper" (Ryan, 2026-09-13, opt-in via `deep_walk=True`):
    instead of stopping at the first video, keep walking up to
    `listing_limit` (default `DEEP_WALK_LISTING_LIMIT`) candidates and
    COLLECT up to `video_collect_limit` (default
    `DEEP_WALK_VIDEO_COLLECT_LIMIT`) that carry video -- a YouTube lead
    (never fetched) counts as carrying video too, same as the
    non-deep-walk path already treats it. The returned `VerifyResult`'s
    top-level fields (`meeting_found`/`video_found`/`meeting_url`/...)
    still describe the FIRST (newest) collected candidate, so a caller
    that ignores `video_candidates` sees the same shape as today; a
    caller doing WO-355's own hand-read gate reads `video_candidates`
    for the full newest-first list and picks among them (see
    `select_on_mission_candidate()`)."""
    effective_limit = (
        listing_limit
        if listing_limit is not None
        else (DEEP_WALK_LISTING_LIMIT if deep_walk else WALK_LIMIT)
    )
    collect_limit = (
        (
            video_collect_limit
            if video_collect_limit is not None
            else DEEP_WALK_VIDEO_COLLECT_LIMIT
        )
        if deep_walk
        else 1
    )
    checked = 0
    collected: List[dict] = []
    # WO-933: candidates the shared gate refused on the way (see
    # `VerifyResult.rejected_video_links`). Only the STRUCTURAL checks run
    # here (not a video link, a decorative address, a test-event title): a
    # per-meeting listing row already vouches for itself, and WO-355's
    # deep-walk hand-read step (`select_on_mission_candidate()`) is where
    # a listed row's title is judged.
    rejected: List[dict] = []

    def _finish(result: VerifyResult) -> VerifyResult:
        result.rejected_video_links = rejected
        return result

    for candidate in candidates[:effective_limit]:
        url = candidate.get("url") if isinstance(candidate, dict) else None
        if not url:
            continue
        checked += 1
        title = candidate.get("title") if isinstance(candidate, dict) else None
        date = candidate.get("date") if isinstance(candidate, dict) else None
        duration = candidate.get("duration") if isinstance(candidate, dict) else None
        if _is_youtube_host(url):
            collected.append(
                _candidate_summary(
                    title=title,
                    date=date,
                    url=url,
                    platform="youtube",
                    captions_found=False,
                    duration=duration,
                    lead=True,
                )
            )
            if not deep_walk or len(collected) >= collect_limit:
                result = _youtube_lead(
                    url,
                    f"{base_verdict}: candidate {checked} of up to {len(candidates)} is "
                    "a YouTube embed -- not fetched, recorded as a lead",
                )
                result.candidates_checked = checked
                if deep_walk:
                    result.video_candidates = collected
                return _finish(result)
            continue
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
            collected.append(
                _candidate_summary(
                    title=title,
                    date=date,
                    url=e.url,
                    platform="youtube",
                    captions_found=False,
                    duration=duration,
                    lead=True,
                )
            )
            if not deep_walk or len(collected) >= collect_limit:
                result = _youtube_lead(
                    e.url,
                    f"{base_verdict}: candidate {checked} of up to {len(candidates)} "
                    "delegates internally to YouTube -- not fetched, recorded as a lead",
                )
                result.candidates_checked = checked
                if deep_walk:
                    result.video_candidates = collected
                return _finish(result)
            continue
        except (CalendarPageError, NoVideoCandidateFound):
            # A candidate that is itself another listing, or a page that
            # honestly checked and found no video -- not a fetch error,
            # just not the answer; keep walking.
            continue
        except Exception:  # noqa: BLE001
            continue
        if resolved.video_url:
            refusal = structural_reject(resolved.video_url, title=title)
            if refusal is None and resolved.title:
                refusal = structural_reject(None, title=resolved.title)
            if refusal is not None:
                # WO-933: a decorative address, a non-video link or a test
                # upload is not a meeting video, however it was listed.
                rejected.append(
                    {
                        "url": resolved.video_url,
                        "platform": resolved.platform or candidate_platform,
                        "reason": refusal.reason,
                    }
                )
                continue
        if resolved.video_url and not await _confirm_not_audio_only(resolved.video_url):
            # WO-347/WO-348: a real, live audio-only file (e.g. a
            # CivicClerk `.mp3`), not video -- keep walking rather than
            # crediting it as a found video.
            continue
        if resolved.video_url:
            # Report the candidate's OWN resolved platform, not the
            # listing's -- a generic-link-scan or CalendarPageError walk
            # can land on a completely different real video vendor (e.g.
            # a CivicPlus listing whose one real video candidate is a
            # Granicus link), and the platform that actually served the
            # video is the more useful/accurate thing for a caller to
            # record, not the aggregator that merely listed it.
            collected.append(
                _candidate_summary(
                    title=title,
                    date=date,
                    url=resolved.source_url or url,
                    platform=resolved.platform or candidate_platform,
                    captions_found=bool(resolved.segments),
                    duration=duration,
                )
            )
            if not deep_walk or len(collected) >= collect_limit:
                first = collected[0]
                return _finish(
                    VerifyResult(
                        meeting_found=True,
                        video_found=True,
                        captions_found=first["captions_found"],
                        meeting_url=first["url"],
                        platform=first["platform"],
                        verdict=f"{base_verdict}_found_video",
                        evidence=(
                            f"{base_verdict}: walked {checked} of {len(candidates)} real "
                            "candidates newest-first, found real video"
                            + (
                                f" ({len(collected)} collected for deep-walk hand-read)"
                                if deep_walk
                                else ""
                            )
                        ),
                        candidates_checked=checked,
                        video_candidates=collected if deep_walk else [],
                    )
                )
            continue
    if collected:
        # deep_walk exhausted the listing before reaching collect_limit,
        # but still found at least one video candidate along the way.
        first = collected[0]
        return _finish(
            VerifyResult(
                meeting_found=True,
                video_found=True,
                captions_found=first["captions_found"],
                meeting_url=first["url"],
                platform=first["platform"],
                verdict=f"{base_verdict}_found_video",
                evidence=(
                    f"{base_verdict}: walked {checked} of {len(candidates)} real "
                    f"candidates newest-first, found {len(collected)} with video "
                    "(listing exhausted before reaching the collect limit)"
                ),
                candidates_checked=checked,
                video_candidates=collected,
            )
        )
    return _finish(
        VerifyResult(
            meeting_found=checked > 0,
            video_found=False,
            captions_found=False,
            meeting_url=None,
            platform=platform,
            verdict=f"{base_verdict}_no_video" if checked else f"{base_verdict}_empty",
            evidence=(
                f"{base_verdict}: walked {checked} of {len(candidates)} real "
                "candidates newest-first, none had video"
                + (
                    f"; the shared gate refused {len(rejected)} video link(s) as "
                    "not a meeting recording"
                    if rejected
                    else ""
                )
                if checked
                else f"{base_verdict}: zero real candidates found"
            ),
            candidates_checked=checked,
        )
    )


async def _resolve_and_walk(
    url: str,
    platform: str,
    *,
    name: Optional[str] = None,
    state: Optional[str] = None,
    deep_walk: bool = False,
    listing_limit: Optional[int] = None,
    video_collect_limit: Optional[int] = None,
) -> VerifyResult:
    """Call platform's resolve() on url and interpret the result. When
    resolve() comes back empty (no video, no title/agenda -- the WO-331
    "this was actually a listing page" shape) or fails outright, falls
    back to that platform's registered listing walker (or the generic
    link-scan one) before giving up -- conductor's fix #2: an
    UNSUPPORTED/RESOLVE_FAILED verdict on a hub must trigger the listing
    walk before any no-video verdict. WO-348 adds one more fallback,
    after the listing walker also comes up empty: `_deeper_hop_search()`
    on this same page, before finally giving up (see that function's own
    docstring and this module's "look one hop deeper" section). WO-355's
    `deep_walk`/`listing_limit`/`video_collect_limit` pass straight
    through to `_walk_candidates()`/`_try_listing_walker()` -- see
    `_walk_candidates()`'s own docstring."""
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
            list(e.candidates),
            platform,
            base_verdict="calendar_page",
            name=name,
            state=state,
            deep_walk=deep_walk,
            listing_limit=listing_limit,
            video_collect_limit=video_collect_limit,
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
        walked = await _try_listing_walker(
            url,
            platform,
            name=name,
            state=state,
            deep_walk=deep_walk,
            listing_limit=listing_limit,
            video_collect_limit=video_collect_limit,
        )
        if walked is not None:
            return walked
        hopped = await _try_deeper_hop_on_url(url, name=name, state=state)
        if hopped is not None:
            return hopped
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
        walked = await _try_listing_walker(
            url,
            platform,
            name=name,
            state=state,
            deep_walk=deep_walk,
            listing_limit=listing_limit,
            video_collect_limit=video_collect_limit,
        )
        if walked is not None:
            return walked
        hopped = await _try_deeper_hop_on_url(url, name=name, state=state)
        if hopped is not None:
            return hopped
        return VerifyResult(
            meeting_found=False,
            video_found=False,
            captions_found=False,
            meeting_url=None,
            platform=platform,
            verdict="resolve_error",
            evidence=f"{type(e).__name__}: {e}",
        )

    video_confirmed = bool(resolved.video_url) and await _confirm_not_audio_only(
        resolved.video_url
    )
    # WO-347/WO-348: a real, live audio-only file (e.g. a CivicClerk
    # `.mp3`), not video -- fall through to the "no video" handling below
    # rather than crediting a video verdict (same guard `_walk_candidates()`
    # applies).

    if video_confirmed:
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
            video_title=resolved.title,
        )

    # resolve() succeeded but found no video (or found one that turned out
    # to be audio-only). Could be a genuine single meeting with no video
    # yet (real title/agenda present), or -- the WO-331 finding -- a
    # listing/hub page whose resolve() quietly returned empty because it
    # was never given one specific meeting.
    walked = await _try_listing_walker(
        url,
        platform,
        name=name,
        state=state,
        deep_walk=deep_walk,
        listing_limit=listing_limit,
        video_collect_limit=video_collect_limit,
    )
    if walked is not None and walked.meeting_found:
        return walked

    has_real_content = bool(resolved.title) or bool(resolved.agenda_items)
    if not has_real_content:
        # WO-348: neither the direct resolve nor the listing walker found
        # real content -- look one hop deeper on this same page before
        # giving up (see `_deeper_hop_search()`'s docstring).
        hopped = await _try_deeper_hop_on_url(url, name=name, state=state)
        if hopped is not None:
            return hopped

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


async def verify_hub(
    hub_url: str,
    platform_hint: Optional[str] = None,
    *,
    name: Optional[str] = None,
    state: Optional[str] = None,
    deep_walk: bool = False,
    listing_limit: Optional[int] = None,
    video_collect_limit: Optional[int] = None,
) -> VerifyResult:
    """The shared step. `hub_url` is a confirmed hub/tenant URL for a
    government (whatever a sweep's phase 3 already confirmed);
    `platform_hint` is that phase's own best guess at the platform, used
    when `detect_platform(hub_url)` itself can't tell (a government page
    that merely embeds/links a platform, rather than being a URL on that
    platform's own domain -- conductor's fix #2's starting point).
    `name`/`state` (WO-348, both optional -- existing callers are
    unaffected) are the government's own name and state/province; when
    given, they strengthen the "look one hop deeper" evidence check
    (`_name_state_matches()`) the same way phase 3's own targeted scripts
    already check a candidate page's content before confirming it.

    `deep_walk`/`listing_limit`/`video_collect_limit` (WO-355, Ryan,
    2026-09-13, all optional and default off/None -- existing callers
    are unaffected): "walk deeper" -- when a real listing is walked (a
    CalendarPageError pick-list or a registered/generic listing walker),
    collect up to `video_collect_limit` (default
    `DEEP_WALK_VIDEO_COLLECT_LIMIT`, 3) real video candidates from the
    newest `listing_limit` (default `DEEP_WALK_LISTING_LIMIT`, 15)
    listed meetings, instead of stopping at the first one. The result's
    `video_candidates` carries all of them, newest-first, for a caller's
    own hand-read gate (see `select_on_mission_candidate()`) -- a
    government whose newest meeting is off-mission (wrong body, a promo/
    recap/ceremony/training clip) still gets a real second and third
    option from the SAME listing, rather than a bare "off-mission"
    verdict off the first video found.

    The entire walk runs under `_youtube_resolve_guard()` -- not just the
    top-level hub URL -- so a candidate reached partway through (a
    CalendarPageError pick-list entry, a listing-walker result, the
    ranking-fix's vendor link) that turns out to delegate to YouTube is
    caught the same way, never actually fetched.
    """
    with _youtube_resolve_guard():
        return await _verify_hub_impl(
            hub_url,
            platform_hint,
            name=name,
            state=state,
            deep_walk=deep_walk,
            listing_limit=listing_limit,
            video_collect_limit=video_collect_limit,
        )


def _homepage_link_filter(html: str, page_url: str, rejected: List[dict]):
    """The `find_platform_link(..., accept=...)` predicate for a bare
    homepage scan (WO-933): refuses a link the shared gate can already
    tell is not a meeting video -- a decorative address or filename, a
    non-video link, a looping hero `<video>` -- and records each refusal
    in `rejected`, so a decorative first link no longer shadows a real one
    further down the page."""

    def accept(candidate_url: str, candidate_platform: str) -> bool:
        refusal = prescreen_homepage_link(html, page_url, candidate_url)
        if refusal is None:
            return True
        rejected.append(
            {
                "url": candidate_url,
                "platform": candidate_platform,
                "reason": refusal.reason,
            }
        )
        return False

    return accept


def _apply_homepage_gate(
    result: VerifyResult,
    *,
    html: str,
    page_url: str,
    link_url: str,
    name: Optional[str],
    rejected: List[dict],
) -> VerifyResult:
    """The post-resolve half of the shared gate (WO-933), for a single video
    a bare homepage scan found and `_resolve_and_walk()` resolved. WO-355
    hand-read 64 such "video found" verdicts and 62 were wrong (a hero
    video, a promo, a documentary): nothing checked WHAT the video was.
    A listing walk (`verdict` is not "resolved") is left alone -- the
    listing vouches for its rows.

    PASS: the result stands, with `video_gate` recorded. REJECT: not a
    meeting recording, so no video and no meeting are credited (verdict
    "video_rejected"). CANNOT_TELL: the video is real but nothing shows it
    is a meeting recording, so `video_found` stays True and `meeting_found`
    is False (verdict "resolved_unverified_video", `tier` None) -- recorded,
    never defaulted to accepted."""
    result.rejected_video_links = list(rejected) + list(result.rejected_video_links)
    if not result.video_found or result.verdict != "resolved":
        return result
    verdict: GateVerdict = assess_video_candidate(
        title=result.video_title,
        video_url=link_url,
        platform=result.platform,
        evidence=page_evidence(html, link_url, page_url),
        gov_name=name,
        # No `page_url`: the same-organization flag is for a link found by
        # FOLLOWING another page. Here the page is the hub an earlier phase
        # already confirmed for this government, so the flag has nothing to
        # compare (`run_access_ladder()` is where hops happen and where it
        # runs).
        check_filename=True,
    )
    result.video_gate = verdict.verdict
    result.video_gate_reason = verdict.reason
    if verdict.verdict == PASS:
        return result
    refused = [
        *result.rejected_video_links,
        {"url": link_url, "platform": result.platform, "reason": verdict.reason},
    ]
    if verdict.verdict == REJECT:
        return VerifyResult(
            meeting_found=False,
            video_found=False,
            captions_found=False,
            meeting_url=None,
            platform=result.platform,
            verdict="video_rejected",
            evidence=(
                f"found a video at {link_url} but the shared gate rejected it as "
                f"not a meeting recording ({verdict.tag}): {verdict.detail}"
            ),
            video_title=result.video_title,
            video_gate=verdict.verdict,
            video_gate_reason=verdict.reason,
            rejected_video_links=refused,
        )
    # Anything else is CANNOT_TELL.
    return VerifyResult(
        meeting_found=False,
        video_found=True,
        captions_found=result.captions_found,
        meeting_url=result.meeting_url,
        platform=result.platform,
        verdict="resolved_unverified_video",
        evidence=(
            f"found a playable video at {link_url}, but nothing shows it is a "
            f"meeting recording ({verdict.tag}): {verdict.detail}. Recorded as "
            "cannot tell, not credited as a meeting."
        ),
        video_title=result.video_title,
        video_gate=verdict.verdict,
        video_gate_reason=verdict.reason,
        rejected_video_links=list(result.rejected_video_links),
    )


async def _verify_hub_impl(
    hub_url: str,
    platform_hint: Optional[str] = None,
    *,
    name: Optional[str] = None,
    state: Optional[str] = None,
    deep_walk: bool = False,
    listing_limit: Optional[int] = None,
    video_collect_limit: Optional[int] = None,
) -> VerifyResult:
    if _is_youtube_host(hub_url):
        return _youtube_lead(hub_url, "hub URL is itself a youtube.com/youtu.be host")

    detected = detect_platform(hub_url)
    candidate_url = hub_url
    platform = detected if detected != "unknown" else platform_hint
    # WO-933: set only when the platform below came from a bare homepage
    # link scan -- the one path whose "video found" needs the shared gate.
    homepage_hit: Optional[tuple] = None  # (html, page_url, link_url)
    rejected_links: List[dict] = []
    invintus_hub = False
    if detected == "unknown":
        from .invintus import is_invintus_hub_url

        if is_invintus_hub_url(hub_url):
            # WO-922: player.invintus.com/?clientID=N with no eventID.
            # `detect_platform()` deliberately claims only a full meeting
            # URL, so the tenant hub is recognized here instead.
            platform = "invintus"
            invintus_hub = True

    if detected == "unknown" and not invintus_hub:
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
        match = find_platform_link(
            html,
            final_url,
            exclude=frozenset({"youtube"}),
            accept=_homepage_link_filter(html, final_url, rejected_links),
        )
        invintus_client = None
        if match is None or platform_hint == "invintus":
            # WO-922: a government page that embeds an Invintus event
            # listing (Oregon Legislature) or player (wiseye.org) names
            # its tenant in its own markup, not as a link
            # `find_platform_link()` can see.
            from .invintus import extract_invintus_client_id

            invintus_client = extract_invintus_client_id(html)
        if invintus_client and (match is None or platform_hint == "invintus"):
            candidate_url = f"https://player.invintus.com/?clientID={invintus_client}"
            platform = "invintus"
        elif match:
            candidate_url, platform = match
            homepage_hit = (html, final_url, candidate_url)
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
        # agenda/minutes page at a guessable path, its own home page
        # body, or one hop deeper (see
        # `_probe_first_party_agenda_pages()`'s own docstring, WO-348).
        # `html`/`final_url` were already fetched above when `detected`
        # was unknown (always true on this branch) -- reuse them rather
        # than fetching the hub a second time.
        probed = await _probe_first_party_agenda_pages(
            hub_url,
            home_html=html if detected == "unknown" else None,
            home_final_url=final_url if detected == "unknown" else None,
            name=name,
            state=state,
        )
        if probed is not None:
            probed.rejected_video_links = list(rejected_links)
            return probed
        return VerifyResult(
            meeting_found=False,
            video_found=False,
            captions_found=False,
            meeting_url=None,
            platform=None,
            verdict="no_platform_detected",
            evidence="detect_platform() -> unknown and no platform hint given"
            + (
                f"; the shared gate refused {len(rejected_links)} homepage video "
                "link(s) as not a meeting recording"
                if rejected_links
                else ""
            ),
            rejected_video_links=list(rejected_links),
        )

    result = await _resolve_and_walk(
        candidate_url,
        platform,
        name=name,
        state=state,
        deep_walk=deep_walk,
        listing_limit=listing_limit,
        video_collect_limit=video_collect_limit,
    )
    if homepage_hit is not None:
        page_html, page_url, link_url = homepage_hit
        result = _apply_homepage_gate(
            result,
            html=page_html,
            page_url=page_url,
            link_url=link_url,
            name=name,
            rejected=rejected_links,
        )
        if result.verdict == "video_rejected":
            # The one link the scan found was not a meeting recording: try
            # what the `platform is None` branch above tries -- the
            # government's own agenda/minutes pages -- before giving up.
            probed = await _probe_first_party_agenda_pages(
                hub_url,
                home_html=page_html,
                home_final_url=page_url,
                name=name,
                state=state,
            )
            if probed is not None:
                probed.rejected_video_links = list(result.rejected_video_links)
                return probed
            return result

    # Ranking fix (conductor's fix #3): the platform reached is a known
    # aggregator and it found no video -- check the ORIGINAL hub page for
    # a real, non-aggregator video-vendor link and prefer it.
    if platform in AGGREGATOR_PLATFORMS and not result.video_found:
        html, final_url, err = await _fetch(hub_url)
        if not err and html is not None:
            vendor_rejected: List[dict] = []
            vendor_match = find_platform_link(
                html,
                final_url,
                exclude=frozenset({"youtube"}) | AGGREGATOR_PLATFORMS,
                accept=_homepage_link_filter(html, final_url, vendor_rejected),
            )
            result.rejected_video_links = [
                *result.rejected_video_links,
                *vendor_rejected,
            ]
            if vendor_match:
                vendor_url, vendor_platform = vendor_match
                vendor_result = await _resolve_and_walk(
                    vendor_url,
                    vendor_platform,
                    name=name,
                    state=state,
                    deep_walk=deep_walk,
                    listing_limit=listing_limit,
                    video_collect_limit=video_collect_limit,
                )
                # WO-933: the same homepage-video gate as the main path. A
                # vendor video the gate rejects or cannot verify is NOT
                # preferred over the aggregator's own result (which may have
                # found real meeting rows); it is only noted.
                vendor_result = _apply_homepage_gate(
                    vendor_result,
                    html=html,
                    page_url=final_url,
                    link_url=vendor_url,
                    name=name,
                    rejected=[],
                )
                if vendor_result.video_gate in ("reject", "cannot_tell"):
                    result.rejected_video_links = [
                        *result.rejected_video_links,
                        {
                            "url": vendor_url,
                            "platform": vendor_platform,
                            "reason": vendor_result.video_gate_reason,
                        },
                    ]
                    result.evidence += (
                        f"; a vendor video link on the hub page ({vendor_url}) was "
                        f"not credited: {vendor_result.video_gate} "
                        f"({vendor_result.video_gate_reason})"
                    )
                elif vendor_result.video_found or (
                    not result.meeting_found and vendor_result.meeting_found
                ):
                    vendor_result.evidence = (
                        f"ranking fix: preferred vendor platform {vendor_platform!r} "
                        f"over aggregator {platform!r} on the same hub page -- "
                        f"{vendor_result.evidence}"
                    )
                    vendor_result.ranking_fix_applied = True
                    return vendor_result

        # WO-341 fix #4: neither the direct resolve nor the same-page
        # vendor-link scan above found video -- try the platform's own
        # registered listing walker on the ORIGINAL hub page too, not
        # just on `candidate_url` (`_resolve_and_walk()`'s own fallback
        # already tried that, but only reaches the walker at all when
        # `candidate_url` itself had zero real candidates). Real,
        # confirmed gap this closes: Jefferson County WA's confirmed
        # AgendaCenter category page has 15 real candidate rows and
        # `NoVideoCandidateFound(candidates_checked=15)` -- a genuinely
        # confident "no video in THIS category" answer, so
        # `_resolve_and_walk()`'s own `no_video_in_listing` branch
        # returns immediately without ever trying a listing walker (that
        # branch already has its confident real answer for the category
        # it checked). But the same GOVERNMENT can have a different real
        # video-bearing category or video hub page the walker can reach
        # from the hub page's own site navigation -- this is exactly what
        # `_civicplus_walker()` was built to find (step 1 tries OTHER
        # AgendaCenter categories first, for exactly this reason).
        walked = await _try_listing_walker(
            hub_url,
            platform,
            name=name,
            state=state,
            deep_walk=deep_walk,
            listing_limit=listing_limit,
            video_collect_limit=video_collect_limit,
        )
        if walked is not None and (
            walked.video_found or (not result.meeting_found and walked.meeting_found)
        ):
            walked.evidence = (
                f"ranking fix: {platform!r}'s own listing walker on the original "
                f"hub page found real video after the direct resolve did not -- "
                f"{walked.evidence}"
            )
            walked.ranking_fix_applied = True
            return walked

        if not result.meeting_found:
            # WO-348: still nothing -- look one hop deeper on the
            # original hub page itself before giving up (covers e.g. a
            # CivicPlus tenant whose confirmed AgendaCenter page links a
            # real vendor/section page none of the above reached).
            hopped = await _try_deeper_hop_on_url(hub_url, name=name, state=state)
            if hopped is not None:
                return hopped

    return result


def select_on_mission_candidate(
    video_candidates: List[dict],
    *,
    gov_name: Optional[str] = None,
    gov_kind: Optional[str] = None,
) -> "tuple[Optional[dict], List[dict]]":
    """WO-355 "hand-read deeper" (Ryan, 2026-09-13) -- the automatic half
    of the rule. Given `VerifyResult.video_candidates` (newest-first,
    from a `verify_hub(..., deep_walk=True)` call), checks them IN ORDER
    with `classify_video_hand_check()` (the WO-191 phrase list already
    used as the automatic pre-filter everywhere else in this repo --
    CLAUDE.md's "hand-check every found video" bullet) and returns
    `(candidate, skipped)`:

    - `candidate` is the first entry that does not trip the Kind A/B
      phrase list -- None if every entry was flagged, or if
      `video_candidates` is empty.
    - `skipped` is every entry checked before `candidate` (or all of
      them, when nothing passed), each with `hand_check_kind` ("A" or
      "B") and `hand_check_reason` added -- for a caller's own report
      line ("checked 2 of 3, passed on attempt 2; skipped 1: Kind B,
      title suggests non-meeting content (matched 'ribbon cutting')").

    THIS IS THE PRE-FILTER ONLY. `classify_video_hand_check()`'s phrase
    list is deliberately conservative -- it only catches what names
    itself in the title/channel text, not a genuine promo/recap/
    ceremony clip from a proper-noun-only channel, and it cannot judge
    CITISTAT-style mayoral working sessions (which count as on-mission)
    apart from a chamber-of-commerce speech (which does not) -- both can
    read as ordinary government content to a phrase list. A caller must
    still actually read the title (and channel, when known) of whatever
    this returns, and keep checking further down `video_candidates` by
    hand if the returned candidate still doesn't look on-mission on that
    read -- this function only narrows the field, per Ryan's rule 2
    ("check the collected videos in order until one looks on-mission").
    `channel_text` is intentionally not accepted here: WO-355's own
    listing walkers don't resolve a channel identity for every
    candidate (only the finally-chosen one gets a real `resolve()`), so
    there is nothing reliable to pass -- the title-only phrase check is
    still worth running before a human read, exactly as sparse as the
    walkers' own candidate dicts are today."""
    skipped: List[dict] = []
    for candidate in video_candidates:
        title = candidate.get("title") if isinstance(candidate, dict) else None
        hand_check = classify_video_hand_check(title, None, gov_name, gov_kind)
        if hand_check is None:
            return candidate, skipped
        kind, reason = hand_check
        skipped.append(
            {**candidate, "hand_check_kind": kind, "hand_check_reason": reason}
        )
    return None, skipped
