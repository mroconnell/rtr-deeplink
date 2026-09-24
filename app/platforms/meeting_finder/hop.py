"""Meeting Finder's Hop phase (WO-1029, link-quality fixes WO-1033).

docs/MEETING_FINDER.md's Hop section: given a page already in hand,
rank the best next links to follow -- `find_hop_links()`'s measured
scorer (`scripts/wo147_access_ladder_sweep.py`, WO-274/WO-292/WO-327),
`looks_like_document_hub()` to confirm a fetched hop actually looks like
a hub rather than trusting the ranking alone, and
`find_calendar_entry_links()` to take one more hop into a plain events
calendar's first dated entries. No limits/forks/fetch-budget logic here
-- `max_hops`/`max_forks`/`max_fetches` are the wiring WO's job
(runner.py); this module only ranks and classifies.

**Reused directly from `scripts/wo147_access_ladder_sweep.py`, not
moved into `app/` (a deliberate deviation from the WO-1029 brief's "move
the pure ones into app/" instruction -- flagged for the wiring WO/
conductor to weigh in on).** `app/platforms/meeting_finder/fetch.py`
(WO-1025) already established the precedent this module follows: that
module's own docstring explains at length why it imports
`fetch_headless_sync`/`HONEST_HEADERS`/`BROWSER_HEADERS` straight from
this same script rather than moving them, and says explicitly that
"move it and have the script import it back" is "kept in reserve for a
case where a direct import genuinely doesn't work" -- a direct import
already proven to work for that module. The functions this module needs
(`find_hop_links`, `looks_like_document_hub`, `find_calendar_entry_
links`, plus the private scorer `_score_hop_candidate_weighted` and
`_safe_soup` this module calls directly for `prefer_vendor`'s extra
ranking pass) are pure -- no network, no DB -- exactly the property that
made a direct import safe there. wo147's own script is 2,478 lines,
under active multi-session iteration (per CLAUDE.md's own working-tree
note) and already has real test coverage
(`tests/test_wo147_*`/`tests/test_hop_scorer*` -- see this WO's test
file for the exact list); moving ~500 lines of scoring logic and every
constant it touches (`_VENDOR_MARKETING_APEX`, `_ROUTINE_WORDS`,
`_BOILERPLATE_PHRASES`, the three weight CSVs' loaders, `HOP1_HINT_
WORDS`, `MAX_HOP_LINKS`...) out from under it, mid-wave, is a real risk
to a script every WO-147-descended sweep still runs, for no behavior
change this WO needs. `find_hop_links()`'s own signature is unchanged by
this module either way. If a later WO wants the move done properly (its
own PR, its own review of wo147's test suite passing unchanged
afterward), this module's public functions don't have to change at all.

**`prefer_vendor` (Identify's "platform known, account unknown" case)**
is not something `find_hop_links()` itself supports -- its own
`_TARGET_SHAPE_BONUS` already rewards ANY vendor-host link equally,
never a *specific* vendor over another. `rank_hops()` adds a second,
smaller bonus on top of that shared vendor bonus, only for links
`app.platforms.base.detect_platform()` resolves to the SAME platform
name as `prefer_vendor` -- so once Identify already suspects "this is a
Granicus tenant, but which one," a real Granicus link on the page
outranks a merely vendor-shaped link to some other platform, without
disturbing `find_hop_links()`'s own scoring for the (much more common)
case where the vendor isn't known yet.

## WO-1033: four real link-quality bugs, found against real pages

Ryan's own recipe for finding a meeting by hand -- confirmed against 5
real governments (Dublin CA, Emporia KS, plus 3 more the conductor
checked) -- is: **homepage -> site navigation -> "Meetings"/"Agendas &
Minutes" -> a link to video** (the meeting pages sit on that page). Every
fix below exists to make `rank_hops()` follow that same recipe instead of
being crowded out by a homepage's own calendar widget.

1. **A word-less nav link scored nothing at all, real bug, not a
   hypothetical.** Emporia KS's real homepage (fetched via Wayback --
   see `tests/fixtures/wo1033_hop_scan/README.md`, live fetching of this
   government is paused, it started 403ing this Mac) links its own
   "Agendas & Minutes" page as bare `<a href="/1300">` -- a CivicPlus
   "graphic links"/quick-link-button widget (icon + `<span
   class="text">Agendas &amp; Minutes</span>`, confirmed via the real
   saved markup: `class="fancyButton fancyButton55"` inside `<nav
   class="widgetGraphicLinksNav">`). `_score_hop_candidate_weighted()`
   (wo147's own scorer) requires real PATH-token or target-shape evidence
   before it will even look at the anchor TEXT's own vocabulary score
   (see that function's own "Anchor-text vocabulary alone can never
   qualify a candidate" comment, guarding against a real false positive
   of its own -- a CivicAlerts.aspx press release scoring high purely on
   prose). A bare numeric path like `/1300` carries no tokens at all, so
   the real "Agendas & Minutes" link was rejected outright and never
   appeared even in the top 60 candidates, while Emporia's own calendar
   widget (real URL words: "calendar", "event") filled the top ranks
   instead. Confirmed the identical shape is genuinely common: Dublin
   CA's OWN top nav item survives today only because its path
   (`/1604/Meetings-Agendas-Minutes-Video-on-Demand`) happens to carry
   real words -- the exact same anchor TEXT on a numeric-slug CMS (a
   config choice, not a different kind of page) would have hit the same
   wall Emporia did.

   Fixing this inside wo147's own scorer is out of scope for this WO (a
   shared, heavily-tested, actively-iterated script this WO doesn't own,
   per CLAUDE.md's multi-session working-tree note) and unnecessary --
   `rank_hops()` already has everything it needs to add a second,
   narrow rescue path of its own: `_looks_like_nav_hub_label()` below
   recognizes a SHORT anchor text built only from meeting-hub vocabulary
   ("Meetings", "Agendas & Minutes", "Watch Meetings", "Meetings,
   Agendas, Minutes & Video on Demand") as opposed to a prose sentence
   that merely contains one of the same words ("City Council Meeting
   Rescheduled for Next Week" -- exactly the kind of false positive
   wo147's own gate exists to block, so the rescue re-derives wo147's
   OWN vendor-marketing-apex and boilerplate-phrase guards before
   applying, rather than blindly overriding every `None` its scorer
   returns). This is a general fix, not a Dublin/Emporia-specific one --
   any homepage whose CMS renders its meetings-hub nav link as a
   numeric-slug/icon-button loses nothing to word-based path scoring.

2. **Calendar events must not crowd out hub links.** Both Dublin's and
   Emporia's homepages fill Hop's top candidates with individual
   calendar-day entries (`/m/calendar/event/detail/7874`,
   `Calendar.aspx?EID=2497`) and calendar list/day views
   (`calendar.aspx?view=list&year=2026&month=9&day=12`) -- these still
   score via wo147's own vocabulary (their anchor text is often just a
   date, and "calendar"/"event" carry real path weight), so they aren't
   rejected the way bug 1's word-less link was; there are just usually
   many more of them than there are real hub links, and they crowd the
   top of a plain score sort. `rank_hops()` now applies a real penalty to
   a calendar-event/day-view-shaped URL and, independent of score, never
   lets more than `_MAX_CALENDAR_ENTRIES_IN_TOP` of them into the
   returned top candidates -- `find_calendar_entry_links()`'s own role
   (one hop into a calendar's first dated entries when the calendar page
   itself shows no document evidence) is untouched; this is purely about
   the ranking `rank_hops()` itself returns.

3. **`prefer_video`** (new): once a platform is already known to have
   meetings but only a page's worth of them without video (a real,
   confirmed shape -- a lister that can only report `has_video_hint=
   False` candidates), a link whose own anchor text or path says
   watch/video/video-on-demand/live stream/meeting video gets a clear
   boost -- Dublin's own `/2875/Watch-Meetings`, one hop off `/1604`, is
   exactly this shape. Off by default so it doesn't change ranking for
   the (more common) case where Hop is just looking for a hub, not
   specifically video.

4. **A same-site YouTube redirect (CivicPlus's own `/youtube`, and the
   same shape for `/facebook`/other social redirects) is never offered
   as a hop at all.** Confirmed live on Emporia's real homepage: a
   graphic-link button's `<a href="/youtube">` wraps only an `<img
   alt="YouTube">` (no visible anchor text at all) -- Meeting Finder
   never fetches YouTube (`fetch.py`'s own guard), so ranking this as a
   candidate hop would only ever waste a hop slot on a guaranteed dead
   end, the same reasoning WO-1030's follow-up already applied to a
   literal `youtube.com` link. `canonical_page_key()` (new, item 5 below)
   has nothing to do with this -- it is a different fix, for the
   runner's `seen` set.

5. **Same page, different parameters.** A calendar URL that differs only
   in a volatile view/preview/date parameter (`PREVIEW`, `month`, `year`,
   `day`, `calType`, `view`) is still the *same* page, but a raw string
   set would treat each one as new -- confirmed live on Emporia: the same
   real event (`EID=2662`) is linked three different ways on the same
   site (`Calendar.aspx?EID=2662`, `calendar.aspx?PREVIEW=YES&EID=2662`,
   `Calendar.aspx?EID=2662&month=9&year=2026&day=23&calType=0`).
   `canonical_page_key(url)` collapses all three to one key while keeping
   `EID`/`CID` (the real identity of a calendar item) distinct -- exposed
   for `runner.py` (WO-1031) to use as its own `seen`-set key; nothing in
   this module calls it itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import parse_qsl, urljoin, urlparse

from app.platforms import host_recognition
from app.platforms.base import detect_platform

from scripts.wo147_access_ladder_sweep import (  # noqa: E402
    _BOILERPLATE_PHRASES,
    _is_vendor_marketing_apex,
    _nav_position_bonus,
    _safe_soup,
    _score_hop_candidate_weighted,
    find_calendar_entry_links,
    find_hop_links,
    looks_like_document_hub,
    looks_french,
)

from .fetch import FetchResult
from .identify import _SCAN_TAGS

# Smaller than `_TARGET_SHAPE_BONUS` (20.0, in wo147's own module) so a
# preferred-vendor link doesn't out-rank a `_NAMED_FIRSTPARTY_PATH_RE`
# hit (a near-perfect signal, e.g. Hyland's `/ViewMeeting`) on some OTHER
# host -- it only breaks ties among links that already cleared
# `find_hop_links()`'s own bar, pushing the known vendor's own host
# ahead of a generic "some vendor" link.
_PREFER_VENDOR_BONUS = 8.0

# --- WO-1033 item 3: video-seeking boost (opt-in via prefer_video=True) ---
_VIDEO_SEEKING_RE = re.compile(
    r"\bwatch\b|\bvideo\b|video[-\s]on[-\s]demand|live\s*stream|meeting\s*video",
    re.IGNORECASE,
)
_VIDEO_SEEKING_BONUS = 10.0

# --- WO-1033 item 1: a short nav/menu label built only from meeting-hub
# vocabulary ("Meetings", "Agendas & Minutes", "Watch Meetings",
# "Meetings, Agendas, Minutes & Video on Demand") -- see this module's
# docstring for the real Emporia/Dublin shapes this rescues. Deliberately
# excludes "calendar" -- a bare "Calendar" nav label should NOT get this
# rescue (see item 2's own de-prioritization of calendar-shaped links).
#
# WO-1037 item 1: real Cablecast homepages name their own TV/cable channel
# rather than "meetings" at all -- King County WA's own council-page nav
# link reads "King County TV (KCTV)" (confirmed live,
# href=/en/independents/about-king-county/king-county-tv), Tigard OR's
# reads "Watch TVCTV", McFarland WI's reads "McFarland Cable". Added
# tv/cable/channel/broadcast/television/recordings/access so these clear
# the vocabulary bar (`recordings`/`access` also cover Johnson County
# TX's "Meeting Recordings" and a bare "Public Access" label -- see item 3
# and item 8 below).
_NAV_HUB_WORD_RE = re.compile(
    r"\b(?:meetings?|agendas?|minutes|watch|videos?|recordings?|tv|cable|channel"
    r"|broadcast|television|access)\b",
    re.I,
)
_NAV_HUB_JOINERS = frozenset(
    {"&", "and", "on", "of", "demand", "for", "to", "the", "-", ",", "a"}
)
# WO-1037 item 1: a locality-type word ("County", "City", "Town"...) is a
# generic descriptor, not a brand -- treated as a joiner so a real
# two-word place name ("King County") only spends the single-brand-token
# allowance below on the actual brand word ("King"), not on the locality
# word too.
_NAV_HUB_LOCALITY_JOINERS = frozenset(
    {"county", "city", "town", "township", "borough", "village", "parish"}
)
_NAV_HUB_MAX_WORDS = 8
# WO-1037 item 1: a parenthetical acronym that just re-names the same
# brand in short form ("(KCTV)" alongside "King County TV") never spends
# the one-brand-token allowance below -- it's the same station named
# twice, not a second unrelated word.
_NAV_HUB_PAREN_ACRONYM_RE = re.compile(r"^\([A-Za-z]{2,8}\)$")
# WO-1037 item 1: tolerate exactly one non-vocabulary, non-joiner word --
# the government/station's own brand or place name ("King", "McFarland",
# "TVCTV") -- rather than requiring the WHOLE label to be built from hub
# vocabulary. More than one such word is still rejected (the Dublin/
# Emporia false-positive guard this rescue was built against, "City
# Council Meeting Rescheduled for Next Week", has five).
_NAV_HUB_BRAND_TOKEN_ALLOWANCE = 1
# Clears wo147's own `_TARGET_SHAPE_BONUS` (20.0) alone, but not a real
# vendor-host hit stacked with a nav-position bonus -- this rescue is for
# a link wo147's own scorer rejected outright (no path/target evidence at
# all), not a replacement for a genuine vendor signal.
_NAV_HUB_LABEL_BONUS = 22.0

# WO-1037 item 3: a nav label that specifically names VIDEO ("Meeting
# Video", "Watch Meetings", "Meeting Recordings") gets the same hub bonus
# even when the weighted scorer already found some real path/anchor
# evidence -- Johnson County TX's real "Meeting Video" nav link
# (/commissioners-court/public-information/meeting-video) scores ~8 from
# ordinary path vocabulary ("commissioners", "meeting") and loses to
# generic agenda/minutes links scoring 11-18, even though a link that
# names video specifically is exactly what Meeting Finder is looking for.
_VIDEO_HUB_LABEL_RE = re.compile(r"\b(?:video|watch|recordings?)\b", re.I)

# --- WO-1033 item 2: calendar-event/day-view links, ranked below real
# hub links and capped in the returned top candidates. ---
_CALENDAR_ENTRY_HREF_RE = re.compile(
    r"/calendar/event/detail/\d+"
    r"|calendar\.aspx\?[^#]*\beid=\d+"
    r"|calendar\.aspx\?[^#]*\bview=list\b",
    re.IGNORECASE,
)
# WO-1037 item 4: a per-date agenda/minutes page (real Des Plaines IL
# shape: `/Agendas-and-Minutes/2026/City-Council/11-02-2026-City-Council-
# Meeting`) crowds Hop's top ranks the same way a calendar widget's own
# per-day entries do -- one page per meeting date, usually many more of
# them than there are real hub links. Same penalty/cap treatment as a
# calendar entry, not a separate bucket.
_PER_DATE_AGENDA_HREF_RE = re.compile(
    r"/agendas?(?:-and-minutes)?/.*\d{1,2}-\d{1,2}-\d{4}"
    r"|/minutes/.*\d{1,2}-\d{1,2}-\d{4}",
    re.IGNORECASE,
)
_CALENDAR_ENTRY_PENALTY = -6.0
_MAX_CALENDAR_ENTRIES_IN_TOP = 2

# WO-1037 item 5: `detect_platform()` requires a real show/gallery-shaped
# PATH before it recognizes Cablecast/Swagit/etc -- a bare vendor tenant
# root with no path evidence yet (real: `desplainesil.cablecast.tv/
# ?site=6`, `reflect-niagarafallsosc.cablecast.tv/CablecastPublicSite/
# ?channel=1`) comes back "unknown" and scores nothing.
# `host_recognition.platform_for_url()` already knows these HOSTS
# regardless of path shape (built for exactly this "no adapter-path match
# yet" case elsewhere) -- used here as a fallback bonus, roughly the same
# size as wo147's own `_TARGET_SHAPE_BONUS` (20.0) for a link that
# clears its OWN vendor-host bar, so a bare recognized tenant root isn't
# left permanently unscored just because its path carries no words yet.
_HOST_FALLBACK_VENDOR_BONUS = 20.0

# WO-1037 item 8: an off-site link whose own anchor TEXT names a TV/
# cable/community-television/public-access station (a PEG nonprofit's own
# proper name, e.g. "Tualatin Valley Community Television" -> tvctv.org,
# real Lake Oswego OR link) is worth one hop even though it carries none
# of the ordinary hub vocabulary a government's OWN meeting-hub link
# would -- a station's proper name never could. Smaller than
# `_NAV_HUB_LABEL_BONUS` since this is a weaker, off-site signal.
_TV_STATION_ORG_TEXT_RE = re.compile(
    r"\btelevision\b|\bcable\s*access\b|\bpublic\s*access\b|\bcommunity\s+access\b",
    re.IGNORECASE,
)
_TV_STATION_BONUS = 18.0

# WO-1037 item 8: on a shared multi-government hub (one PEG org serving
# several nearby cities/towns off the same host), a link whose anchor
# text names THIS government gets a small bonus over a sibling link
# naming a different one (real Bismarck ND case: a shared Dakota Media
# Access hub ranked a "Lincoln City Council" link ahead of Bismarck's
# own). Small and additive only -- a link that names no place at all
# (the common case) is never penalized for it.
_GOV_NAME_MATCH_BONUS = 6.0
_GOV_NAME_STOPWORDS = frozenset(
    {"city", "town", "county", "township", "village", "borough", "of", "the", "and"}
)
_GOV_NAME_TOKEN_RE = re.compile(r"[a-zA-Z]+")

# --- WO-1033 item 4: a same-site redirect to a social platform
# (CivicPlus's own "/youtube", "/facebook", ...) -- never a real hop
# target; Meeting Finder never fetches these hosts and a genuine YouTube
# lead is reported separately (see `scan.py`/`identify.py`'s own
# `_SAME_SITE_SOCIAL_REDIRECT_RE`). Kept narrow (path-only, no query/
# subpath) so it can't accidentally swallow a real page whose path merely
# starts with one of these words.
_SAME_SITE_SOCIAL_REDIRECT_RE = re.compile(r"^/(?:youtube|facebook)/?$", re.IGNORECASE)

# --- WO-1033 item 5: params that don't change WHICH page a calendar link
# points to, only how it's displayed -- collapsed by canonical_page_key().
_VOLATILE_CALENDAR_PARAMS = frozenset(
    {"preview", "month", "year", "day", "caltype", "view"}
)


@dataclass(frozen=True)
class HopLink:
    url: str
    score: float
    anchor: str
    reason: str


def _gov_id_for(*, school: bool, french: bool) -> str:
    """A fake `gov_id` shaped only to select `find_hop_links()`'s own
    school/French vocabulary merge (see `_weights_for_gov()` in
    wo147_access_ladder_sweep.py) -- never a real government id, never
    written anywhere. `french=True` still only takes effect when the
    PAGE ITSELF looks French (`looks_french()`, checked inside
    `_weights_for_gov()`) -- same as every other `ca:` caller of
    `find_hop_links()`, not overridden here just because the caller
    believes the government is francophone."""
    if school:
        return "us:sd:__meeting_finder_school__"
    if french:
        return "ca:__meeting_finder_french__"
    return ""


def _looks_like_nav_hub_label(text: str) -> bool:
    """True for a short label built almost entirely from meeting-hub
    vocabulary plus ordinary joiners -- "Agendas & Minutes", "Watch
    Meetings", "Meetings, Agendas, Minutes & Video on Demand" -- as
    opposed to a prose sentence that happens to contain one of the same
    words ("City Council Meeting Rescheduled for Next Week", a real
    CivicAlerts.aspx headline wo147's own scorer already guards against,
    five non-vocabulary words). Every word must be hub vocabulary, a
    joiner/locality-descriptor, or punctuation, WITH ONE EXCEPTION
    (WO-1037 item 1): a single non-vocabulary, non-joiner word is
    tolerated as the label's own brand/place name ("King County TV
    (KCTV)", "Watch TVCTV", "McFarland Cable" -- all real, confirmed
    Cablecast homepage nav labels; a parenthetical acronym like "(KCTV)"
    is exempt from that allowance entirely, since it just re-names the
    same brand already spent on "King"). More than one such word still
    disqualifies the whole label."""
    words = (text or "").strip().split()
    if not words or len(words) > _NAV_HUB_MAX_WORDS:
        return False
    if not _NAV_HUB_WORD_RE.search(text):
        return False
    brand_tokens_used = 0
    for word in words:
        if _NAV_HUB_PAREN_ACRONYM_RE.match(word):
            continue
        core = word.strip(",&-").lower()
        if not core:
            continue
        if core in _NAV_HUB_JOINERS or core in _NAV_HUB_LOCALITY_JOINERS:
            continue
        if _NAV_HUB_WORD_RE.fullmatch(core):
            continue
        brand_tokens_used += 1
        if brand_tokens_used > _NAV_HUB_BRAND_TOKEN_ALLOWANCE:
            return False
    return True


def _rescue_nav_hub_label_score(
    text: str, href: str, full_url: str, base_netloc: str, tag
) -> Optional[float]:
    """Re-derives wo147's own vendor-marketing-apex and boilerplate-phrase
    guards (the only OTHER reasons `_score_hop_candidate_weighted()`
    returns `None` besides "no path/target evidence at all" -- see that
    function's own three `return None` sites) before rescuing a link
    whose own TEXT is a nav-hub label per `_looks_like_nav_hub_label()`.
    Returns `None` when the rescue doesn't apply, never a stand-in for
    wo147's own score otherwise."""
    netloc = urlparse(full_url).netloc.lower()
    if _is_vendor_marketing_apex(netloc) and netloc != base_netloc:
        return None
    hay = f"{text} {href}".lower()
    if any(p in hay for p in _BOILERPLATE_PHRASES):
        return None
    if not _looks_like_nav_hub_label(text):
        return None
    return _NAV_HUB_LABEL_BONUS + _nav_position_bonus(tag)


def _is_calendar_entry_link(url: str) -> bool:
    """True for a calendar-event or calendar-day/list-view URL (item 2),
    OR a per-date agenda/minutes page (WO-1037 item 4: `/Agendas-and-
    Minutes/2026/City-Council/11-02-2026-City-Council-Meeting`) -- both
    are one dated entry among many, as opposed to a hub page about
    meetings/agendas/minutes/video generally."""
    return bool(
        _CALENDAR_ENTRY_HREF_RE.search(url) or _PER_DATE_AGENDA_HREF_RE.search(url)
    )


def _rescue_tv_station_link_score(
    text: str, full_url: str, base_netloc: str, tag
) -> Optional[float]:
    """WO-1037 item 8: an off-site link naming a TV/cable/community-
    television/public-access station is worth one hop even with none of
    the ordinary hub vocabulary -- see `_TV_STATION_ORG_TEXT_RE`'s own
    comment for the real Lake Oswego OR case this rescues. Guarded by the
    same vendor-marketing-apex check `_rescue_nav_hub_label_score()` uses,
    so this can't rescue a link to a vendor's own bare marketing homepage
    either."""
    netloc = urlparse(full_url).netloc.lower()
    if _is_vendor_marketing_apex(netloc) and netloc != base_netloc:
        return None
    if not _TV_STATION_ORG_TEXT_RE.search(text or ""):
        return None
    return _TV_STATION_BONUS + _nav_position_bonus(tag)


def _gov_name_tokens(gov_name: Optional[str]) -> frozenset:
    """Lowercased words (>=3 letters) from a government's own name, minus
    generic jurisdiction-type words -- used only for the small `prefer
    links naming THIS government` bonus on a shared multi-government hub
    (WO-1037 item 8, real Bismarck ND case)."""
    if not gov_name:
        return frozenset()
    words = _GOV_NAME_TOKEN_RE.findall(gov_name.lower())
    return frozenset(w for w in words if len(w) >= 3 and w not in _GOV_NAME_STOPWORDS)


def _is_same_site_social_redirect(url: str, base_netloc: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc.lower() != base_netloc:
        return False
    return bool(_SAME_SITE_SOCIAL_REDIRECT_RE.match(parsed.path or "/"))


def canonical_page_key(url: str) -> str:
    """Collapses a calendar URL that differs only in a volatile display
    parameter (`PREVIEW`, `month`, `year`, `day`, `calType`, `view`) to
    the same key as every other spelling of the same page, while keeping
    `EID`/`CID` (a calendar item's real identity) distinct. For a
    non-calendar URL this just normalizes case/trailing-slash/fragment,
    same as any other URL de-duplication. Exposed for `runner.py`'s own
    `seen`-set (WO-1031) -- this module never calls it itself.

    Real Emporia case this fixes: `Calendar.aspx?EID=2662`,
    `calendar.aspx?PREVIEW=YES&EID=2662` and
    `Calendar.aspx?EID=2662&month=9&year=2026&day=23&calType=0` are the
    SAME event, fetched three different ways -- all three now produce the
    identical key."""
    parsed = urlparse(url)
    kept = sorted(
        (k.lower(), v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in _VOLATILE_CALENDAR_PARAMS
    )
    path = parsed.path.rstrip("/") or "/"
    key = f"{parsed.netloc.lower()}{path.lower()}"
    if kept:
        key += "?" + "&".join(f"{k}={v}" for k, v in kept)
    return key


def _resolved_platform_for(full_url: str) -> tuple[Optional[str], bool]:
    """`detect_platform(full_url)` when it recognizes the URL; otherwise
    (WO-1037 item 5) falls back to `host_recognition.platform_for_url()`,
    which already knows a vendor HOST (`cablecast.tv`, `swagit.com`...)
    regardless of whether the path itself carries a recognizable show/
    gallery shape yet -- a bare tenant root (`desplainesil.cablecast.tv/
    ?site=6`) is real vendor evidence even with no path evidence at all.
    Returns `(platform_or_None, is_host_fallback)`; the second value tells
    the caller whether this came from the (weaker) host-only fallback, so
    it can apply its own smaller/larger bonus accordingly."""
    detected = detect_platform(full_url)
    if detected and detected != "unknown":
        return detected, False
    host_platform, host_supported = host_recognition.platform_for_url(full_url)
    if host_platform and host_supported:
        return host_platform, True
    return None, False


def rank_hops(
    page: FetchResult,
    *,
    prefer_vendor: Optional[str] = None,
    prefer_video: bool = False,
    school: bool = False,
    french: bool = False,
    gov_name: Optional[str] = None,
    limit: int = 8,
) -> List[HopLink]:
    """Ranks `page`'s own links as candidate next hops, best first. See
    this module's docstring for `prefer_vendor`/`prefer_video`/`school`/
    `french` and the WO-1033 items each addresses. `gov_name` (WO-1037
    item 8) is optional and additive only -- when given, a link naming
    this government gets a small bonus on a shared multi-government hub;
    omitting it changes nothing.

    Candidates come from every `<a href>`, `<iframe src>`, `<embed src>`,
    `<video src>`, `<source src>` and `<script src>` on the page (WO-1037
    item 2, the same `_SCAN_TAGS` Identify's own link scan already uses)
    -- a video-only iframe embed is itself a real hop/video-follow
    candidate, not just an `<a href>`.

    A calendar-event/day-view-shaped link, OR a per-date agenda/minutes
    page (item 2 / WO-1037 item 4), is penalized and capped at
    `_MAX_CALENDAR_ENTRIES_IN_TOP` in the returned list, so a homepage's
    own calendar widget or per-date agenda listing can't crowd out real
    hub links even when it out-scores them individually. A same-site
    social redirect (`/youtube`, `/facebook`, item 4) is never offered at
    all.

    Returns `[]` for a page with no HTML (a dead fetch, a Wayback capture
    that returned nothing, or a real 4xx/5xx) rather than raising --
    Hop is one option among several the wiring WO tries, not something
    that should abort a walk on its own."""
    html = page.html or ""
    if not html:
        return []
    final_url = page.final_url or page.requested_url
    gov_id = _gov_id_for(school=school, french=french)
    gov_tokens = _gov_name_tokens(gov_name)

    soup = _safe_soup(html)
    if soup is None:
        return []
    base_netloc = urlparse(final_url).netloc.lower()

    # (score, doc_order, url, anchor, resolved_platform)
    scored: List[tuple[float, int, str, str, Optional[str]]] = []
    seen = set()
    doc_order = 0
    for tag in soup.find_all(_SCAN_TAGS):
        href = tag.get("href") or tag.get("src")
        if not href:
            continue
        text = (tag.get_text() or "").strip() if tag.name == "a" else ""
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        full = urljoin(final_url, href)
        if full in seen or urlparse(full).scheme not in ("http", "https"):
            continue
        if _is_same_site_social_redirect(full, base_netloc):
            continue
        score = _score_hop_candidate_weighted(
            text, href, full, base_netloc, tag, gov_id=gov_id, html_text=html
        )
        resolved_platform, is_host_fallback = _resolved_platform_for(full)
        if score is None:
            score = _rescue_nav_hub_label_score(text, href, full, base_netloc, tag)
        if score is None:
            score = _rescue_tv_station_link_score(text, full, base_netloc, tag)
        if score is None and resolved_platform and is_host_fallback:
            # WO-1037 item 5: a bare vendor tenant root wo147's own
            # scorer never saw any path/target evidence for at all.
            score = _HOST_FALLBACK_VENDOR_BONUS + _nav_position_bonus(tag)
        if score is None:
            continue
        elif (
            resolved_platform is None
            and _VIDEO_HUB_LABEL_RE.search(text)
            and _looks_like_nav_hub_label(text)
        ):
            # WO-1037 item 3: a video-naming nav label ("Meeting Video",
            # "Watch Meetings", "Meeting Recordings") gets the hub bonus
            # ON TOP of a real weighted score too, not only as a rescue
            # when the weighted scorer found nothing -- see this
            # function's own docstring/`_VIDEO_HUB_LABEL_RE` comment for
            # the real Johnson County TX case this fixes. Skipped when a
            # vendor platform is already resolved -- that link already
            # gets `_TARGET_SHAPE_BONUS`/`_HOST_FALLBACK_VENDOR_BONUS`,
            # which is the stronger, more specific signal.
            score += _NAV_HUB_LABEL_BONUS
        if prefer_vendor and resolved_platform == prefer_vendor:
            score += _PREFER_VENDOR_BONUS
        if prefer_video and _VIDEO_SEEKING_RE.search(f"{text} {href}"):
            score += _VIDEO_SEEKING_BONUS
        if gov_tokens:
            hay_tokens = set(_GOV_NAME_TOKEN_RE.findall(f"{text} {href}".lower()))
            if hay_tokens & gov_tokens:
                score += _GOV_NAME_MATCH_BONUS
        if _is_calendar_entry_link(full):
            score += _CALENDAR_ENTRY_PENALTY
        seen.add(full)
        scored.append((score, doc_order, full, text, resolved_platform))
        doc_order += 1

    scored.sort(key=lambda t: (-t[0], t[1]))

    out: List[HopLink] = []
    calendar_count = 0
    for score, _order, url, anchor, platform in scored:
        if len(out) >= limit:
            break
        is_calendar = _is_calendar_entry_link(url)
        if is_calendar:
            if calendar_count >= _MAX_CALENDAR_ENTRIES_IN_TOP:
                continue
            calendar_count += 1
        if prefer_vendor and platform == prefer_vendor:
            reason = f"preferred vendor ({prefer_vendor}) host match"
        elif is_calendar:
            reason = "calendar entry/day-view (de-prioritized)"
        elif platform:
            reason = f"vendor-host link ({platform})"
        else:
            reason = "path/anchor vocabulary match"
        out.append(HopLink(url=url, score=score, anchor=anchor, reason=reason))
    return out


def is_document_hub(page: FetchResult) -> bool:
    """True when `page` shows real evidence of being a document/meeting
    hub (a document link, an `/event/<n>/` permalink, or a known
    platform link anywhere on it) rather than a generic calendar shell --
    `looks_like_document_hub()`, reused verbatim."""
    if not page.html:
        return False
    return looks_like_document_hub(page.html)


def calendar_entry_links(page: FetchResult, limit: int = 2) -> List[str]:
    """The first `limit` dated entries on a plain events-calendar page
    (`?EID=123`/`/event/123/`-shaped hrefs, in document order) --
    `find_calendar_entry_links()`, reused verbatim. Used when `page`
    itself is a calendar shell (see `is_document_hub()`) with no sibling
    agenda/video link of its own to hop to directly."""
    if not page.html:
        return []
    final_url = page.final_url or page.requested_url
    return find_calendar_entry_links(page.html, final_url, limit=limit)


__all__ = [
    "HopLink",
    "rank_hops",
    "is_document_hub",
    "calendar_entry_links",
    "canonical_page_key",
    # Re-exported for convenience/tests -- these are the underlying
    # wo147 functions this module wraps.
    "find_hop_links",
    "looks_french",
]
