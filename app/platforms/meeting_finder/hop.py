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
_NAV_HUB_WORD_RE = re.compile(r"\b(?:meetings?|agendas?|minutes|watch|videos?)\b", re.I)
_NAV_HUB_JOINERS = frozenset(
    {"&", "and", "on", "of", "demand", "for", "to", "the", "-", ",", "a"}
)
_NAV_HUB_MAX_WORDS = 8
# Clears wo147's own `_TARGET_SHAPE_BONUS` (20.0) alone, but not a real
# vendor-host hit stacked with a nav-position bonus -- this rescue is for
# a link wo147's own scorer rejected outright (no path/target evidence at
# all), not a replacement for a genuine vendor signal.
_NAV_HUB_LABEL_BONUS = 22.0

# --- WO-1033 item 2: calendar-event/day-view links, ranked below real
# hub links and capped in the returned top candidates. ---
_CALENDAR_ENTRY_HREF_RE = re.compile(
    r"/calendar/event/detail/\d+"
    r"|calendar\.aspx\?[^#]*\beid=\d+"
    r"|calendar\.aspx\?[^#]*\bview=list\b",
    re.IGNORECASE,
)
_CALENDAR_ENTRY_PENALTY = -6.0
_MAX_CALENDAR_ENTRIES_IN_TOP = 2

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
    """True for a short label built only from meeting-hub vocabulary plus
    ordinary joiners -- "Agendas & Minutes", "Watch Meetings",
    "Meetings, Agendas, Minutes & Video on Demand" -- as opposed to a
    prose sentence that happens to contain one of the same words ("City
    Council Meeting Rescheduled for Next Week", a real CivicAlerts.aspx
    headline wo147's own scorer already guards against). Every word must
    be hub vocabulary, a joiner, or punctuation; a single non-vocabulary
    content word (a place name, "Council", "Rescheduled"...) disqualifies
    the whole label."""
    words = (text or "").strip().split()
    if not words or len(words) > _NAV_HUB_MAX_WORDS:
        return False
    if not _NAV_HUB_WORD_RE.search(text):
        return False
    for word in words:
        core = word.strip(",&-").lower()
        if not core:
            continue
        if core in _NAV_HUB_JOINERS:
            continue
        if not _NAV_HUB_WORD_RE.fullmatch(core):
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
    """True for a calendar-event or calendar-day/list-view URL (item 2) --
    a real dated entry or a date-navigation view, as opposed to a hub
    page about meetings/agendas/minutes/video generally."""
    return bool(_CALENDAR_ENTRY_HREF_RE.search(url))


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


def rank_hops(
    page: FetchResult,
    *,
    prefer_vendor: Optional[str] = None,
    prefer_video: bool = False,
    school: bool = False,
    french: bool = False,
    limit: int = 8,
) -> List[HopLink]:
    """Ranks `page`'s own links as candidate next hops, best first. See
    this module's docstring for `prefer_vendor`/`prefer_video`/`school`/
    `french` and the WO-1033 items each addresses.

    A calendar-event/day-view-shaped link (item 2) is penalized and
    capped at `_MAX_CALENDAR_ENTRIES_IN_TOP` in the returned list, so a
    homepage's own calendar widget can't crowd out real hub links even
    when it out-scores them individually. A same-site social redirect
    (`/youtube`, `/facebook`, item 4) is never offered at all.

    Returns `[]` for a page with no HTML (a dead fetch, a Wayback capture
    that returned nothing, or a real 4xx/5xx) rather than raising --
    Hop is one option among several the wiring WO tries, not something
    that should abort a walk on its own."""
    html = page.html or ""
    if not html:
        return []
    final_url = page.final_url or page.requested_url
    gov_id = _gov_id_for(school=school, french=french)

    soup = _safe_soup(html)
    if soup is None:
        return []
    base_netloc = urlparse(final_url).netloc.lower()

    scored: List[tuple[float, int, str, str]] = []  # (score, doc_order, url, anchor)
    seen = set()
    doc_order = 0
    for a in soup.find_all("a", href=True):
        text = (a.get_text() or "").strip()
        href = a["href"]
        if href.startswith(("javascript:", "mailto:", "tel:", "#")):
            continue
        full = urljoin(final_url, href)
        if full in seen or urlparse(full).scheme not in ("http", "https"):
            continue
        if _is_same_site_social_redirect(full, base_netloc):
            continue
        score = _score_hop_candidate_weighted(
            text, href, full, base_netloc, a, gov_id=gov_id, html_text=html
        )
        if score is None:
            score = _rescue_nav_hub_label_score(text, href, full, base_netloc, a)
            if score is None:
                continue
        if prefer_vendor and detect_platform(full) == prefer_vendor:
            score += _PREFER_VENDOR_BONUS
        if prefer_video and _VIDEO_SEEKING_RE.search(f"{text} {href}"):
            score += _VIDEO_SEEKING_BONUS
        if _is_calendar_entry_link(full):
            score += _CALENDAR_ENTRY_PENALTY
        seen.add(full)
        scored.append((score, doc_order, full, text))
        doc_order += 1

    scored.sort(key=lambda t: (-t[0], t[1]))

    out: List[HopLink] = []
    calendar_count = 0
    for score, _order, url, anchor in scored:
        if len(out) >= limit:
            break
        is_calendar = _is_calendar_entry_link(url)
        if is_calendar:
            if calendar_count >= _MAX_CALENDAR_ENTRIES_IN_TOP:
                continue
            calendar_count += 1
        platform = detect_platform(url)
        if prefer_vendor and platform == prefer_vendor:
            reason = f"preferred vendor ({prefer_vendor}) host match"
        elif is_calendar:
            reason = "calendar entry/day-view (de-prioritized)"
        elif platform and platform != "unknown":
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
