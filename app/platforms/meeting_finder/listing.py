"""List (WO-1028): turn a known account into a list of candidate meetings.

docs/MEETING_FINDER.md's "List" section: given a known account (a
platform + a URL on it -- a Granicus `ViewPublisher.php`, a CivicClerk
tenant root, a bare government homepage that turned out to already be a
listing page, ...), produce candidate meeting URLs, newest-first. **List
only lists** -- Resolve (WO-1024, already merged) is the one place that
picks among candidates and actually runs an adapter's `resolve()` to
confirm video/captions. So every lister here returns bare `Candidate`
rows (url/title/date/platform/has_video_hint when known) without
resolving them -- that's deliberate, not a shortcut: it keeps List cheap
(no network cost beyond the listing fetch itself) and keeps the "one
picking rule" (`pick.py`) and "one video gate" (Resolve) each applied
exactly once, regardless of which lister produced the candidates.

Five listers, tried in the order docs/MEETING_FINDER.md's List table
gives, stopping at the first that returns candidates:

  a. `app/platforms/passive_verify.py`'s registered listing walkers
     (granicus, champds, civicweb, legistar, escribe, civicclerk,
     civicplus, iqm2, townhallstreams, cablecast, invintus) -- called
     directly (not through `verify_hub()`, which also resolves/judges
     each candidate; List only wants the raw listing). Routed through
     Meeting Finder's own `Fetcher` (the fetch ladder + `max_fetches`
     budget) via `passive_verify.fetch_override()` -- see that context
     manager's own docstring for why this is safe for every OTHER
     caller of `passive_verify._fetch()` (unchanged: the override is
     task-local and this module is the only caller that ever sets it).
  b. rtr-discovery's `list_tenant()` (`discovery/list_one.py`, WO-1026 /
     rtr-discovery PR #41) for a platform passive_verify has no walker
     for -- primegov, swagit, municode_meetings, proudcity, hyland, and
     any other platform `discovery.enumerators.ENUMERATORS` covers that
     isn't already in passive_verify's own walker registry. Imported
     lazily from `RTR_DISCOVERY_PATH` (default `~/Documents/
     rtr-discovery`) so importing this module never requires that repo
     to be checked out. Never called for `youtube_channel` -- CLAUDE.md's
     YouTube-drip rule; `list_tenant()` itself already refuses it, this
     module refuses it first so a missing/stale rtr-discovery checkout
     can never accidentally reach that refusal via some other path.
  c. The adapter's own meeting list -- some adapters answer a listing
     page with a `CalendarPageError` pick-list instead of one meeting
     (legistar, municode_meetings, vimeo, wistia, tampa).
  d. Adapters that walk a hub themselves and resolve straight through to
     ONE meeting rather than raising a pick-list (castus's own
     `_pick_newest`, cablecast's gallery resolve, townhallstreams' town
     listing) -- the hub URL is resolved and, on success, wrapped as a
     single `Candidate` (`lister="adapter_hub"`).
  e. Generic same-platform link scan -- `passive_verify.
     _generic_link_scan_walker()` (also routed through the same
     `fetch_override()`).

Nothing found by any lister: `OUTCOME_NO_MEETING_NOR_VIDEO`. No adapter
registered for the platform at all (and no passive_verify walker, no
rtr-discovery enumerator): `OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER`.

**Agenda-only fallback (conductor review, 2026-09-23): a lister that
filters to video-bearing rows only must not make a real "meeting found,
no video yet" tenant look identical to "nothing here at all."**
Confirmed live on Cass County, MN (`mn-casscounty.civicplus.com/
AgendaCenter`): `civicplus.py`'s own `_find_candidate_rows()` (renamed
from `_find_video_rows()` on 2026-09-07 specifically so it would keep
non-video rows too) returns 37 real rows, but `passive_verify.
_civicplus_walker()`'s step 1 only calls `_add()` when a row's own `url`
is set -- an agenda-only tenant returns `[]` from the walker, the same
as an empty one. When lister (a) is CivicPlus and it (and every later
lister) comes back empty, `_civicplus_agenda_only_fallback()` re-parses
the same page with `CivicPlusAssetFinder()._find_candidate_rows()`
directly (not `_civicplus_walker()` -- that function's own behavior is
left untouched for `verify_hub()` and every other existing caller) and
returns each real (title+date) row's `agenda_link`/`packet_link` as a
`Candidate` with `has_video_hint=False` and a note, so Verdict at least
has real rows to call `meeting-without-video` on rather than reading
`no-meeting-nor-video` for an account that plainly isn't empty.

**Checked every other lister for the same video-only filtering blind
spot; CivicPlus is the only registered passive_verify walker that has
it.** Every other bespoke walker in `_LISTING_WALKERS` already returns
every real row regardless of video presence -- CivicWeb/Legistar/
eScribe/IQM2 never filtered on video at the listing stage at all;
CivicClerk's own walker only *sorts* `hasMedia`-true events first, it
never drops the rest; Townhallstreams/Cablecast/Invintus list links that
are inherently video already. **`municode_meetings.py` has the exact
same shape CivicPlus had before its own 2026-09-07 fix** -- its
`resolve()` still calls `self._find_video_rows()` (never renamed/
generalized the way CivicPlus's was) to build its `CalendarPageError`
pick-list (lister c), so an agenda-only Municode Meetings tenant would
hit the same blind spot. Not fixed here: municode_meetings.py is a
different adapter file, and in practice lister (b) (rtr-discovery's own
`MunicodeMeetingsEnumerator`) already answers most Municode Meetings
accounts before lister (c) is ever reached (confirmed live,
`bristol-ri.municodemeetings.com` -- see this WO's live-check table) --
logged as its own `BACKLOG.md` entry instead. Vimeo/Wistia/Tampa's own
`CalendarPageError` lists are video-host listings by nature (every row
already has a playable clip), so this blind spot doesn't apply to them.

Lessons applied from `~/Documents/rtr-upcoming`'s
`UPCOMING_AGENDAS_FIELD_GUIDE.md` ("Finding a vendor host", "Ranking",
"Running those strategies against the whole roster"): a page's own
linked Granicus `view_id` is a hint, not an inventory (a working
`view_id` can be entirely unlinked from any page the government's own
site shows -- Marin County's real `view_id=3`); an account can exist and
be abandoned (this module always reports the newest candidate DATE it
saw, even for a 0-candidate or stale-only result, so Verdict can say
"account exists, nothing recent" rather than just "nothing found"); a
CivicPlus host can publish via `Archive.aspx?AMID=` (ArchiveCenter) as
well as `AgendaCenter`, and can carry a numeric domain suffix -- both
already handled by `_civicplus_walker()`'s own nav-link/Calendar.aspx
fallbacks, which this module reuses unchanged rather than re-deriving.
"""

from __future__ import annotations

import csv as _csv
import dataclasses
import importlib
import importlib.util
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from app.platforms import passive_verify
from app.platforms.base import (
    CalendarPageError,
    UnsupportedPlatformError,
    YouTubeResolveBlocked,
    detect_platform,
    get_finder,
)
from app.platforms.cablecast import (
    _GALLERY_ID_RE,
    CablecastAssetFinder,
    list_gallery_shows,
)
from app.platforms.direct_file import is_direct_file_url

from .fetch import BudgetExceeded, Fetcher
from .models import Candidate

# --- Outcomes -------------------------------------------------------
# Same spellings as models.py's OUTCOME_* constants (docs/MEETING_FINDER.md
# section 23) -- not re-exported from there because models.py is one of
# the files this WO must not edit, and importing OUTCOME_NO_MEETING_NOR_VIDEO/
# OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER from `.models` (read-only import,
# no edit) is exactly as good as defining a third spelling here.
from .models import (  # noqa: E402
    OUTCOME_HUB_OTHER_GOVERNMENT,
    OUTCOME_NO_MEETING_NOR_VIDEO,
    OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER,
)
from .pick import (
    describe_foreign_candidate,
    filter_candidates_to_government,
    parse_candidate_date,
)

# --- Platform groupings for the ordered lister pipeline --------------

# Adapters whose resolve() answers a listing page with a CalendarPageError
# pick-list (lister c) rather than resolving straight to one meeting.
_CALENDAR_PAGE_ERROR_PLATFORMS = frozenset(
    {"legistar", "municode_meetings", "vimeo", "wistia", "tampa"}
)

# Adapters that walk a hub/listing themselves and resolve straight
# through to ONE meeting (lister d) -- castus's own `_pick_newest`,
# cablecast's gallery resolve, townhallstreams' `/towns/{slug}` listing.
_ADAPTER_HUB_PLATFORMS = frozenset({"castus", "cablecast", "townhallstreams"})

# rtr-discovery covers more platforms than this (see ENUMERATORS), but
# per docs/MEETING_FINDER.md's List (b) row this module only reaches for
# it when passive_verify has NO registered walker -- these are the
# platforms named in the WO-1028 brief where that's true today. Checked
# against `passive_verify._LISTING_WALKERS` at call time too (belt and
# braces: if a future WO registers a passive_verify walker for one of
# these, lister (a) already wins by trying first).
_DISCOVERY_ONLY_PLATFORMS = frozenset(
    {"primegov", "swagit", "municode_meetings", "proudcity", "hyland"}
)

_NEVER_DISCOVERY_PLATFORMS = frozenset({"youtube", "youtube_channel"})


@dataclass(frozen=True)
class ListResult:
    """docs/MEETING_FINDER.md's List phase output. `lister` names which
    of the ordered strategies above produced `candidates` (e.g.
    `"passive_verify:granicus"`, `"discovery:primegov"`, `"adapter_list"`,
    `"adapter_hub"`, `"generic_link_scan"`), or `None` when nothing was
    found. `params` carries back a Granicus/CivicWeb param dict
    rtr-discovery's `discover_params()` found this call, so a caller can
    cache it and pass it back in on a later `list_account()` call for the
    same account (skips re-discovery)."""

    candidates: List[Candidate]
    lister: Optional[str]
    outcome: Optional[str]
    note: str = ""
    params: Optional[dict] = None
    # WO-1058: every candidate `_apply_gov_filter()` dropped for naming a
    # DIFFERENT government, described (`pick.describe_foreign_candidate()`)
    # rather than dropped on the floor -- each one is a real, free
    # link-first lead for that other government. Set regardless of
    # whether the drop was partial or total (see `_apply_gov_filter()`).
    # `runner.py` folds this into the walk's `state.other_gov_leads`,
    # which ends up on `VerdictRow.other_gov_leads`.
    foreign_leads: List[dict] = field(default_factory=list)


def _candidate_from_dict(
    row: dict,
    *,
    platform: str,
    account_url: str,
    lister: str,
    page_url: Optional[str] = None,
) -> Optional[Candidate]:
    url = row.get("url") if isinstance(row, dict) else None
    if not url:
        return None
    # WO-1046: for Vimeo, `account_url` is itself a video-host listing
    # link (e.g. a showcase's `vimeo.com/showcase/{id}/embed`), not a
    # page a reader could usefully be sent to -- prefer `page_url` (the
    # real government page Identify actually found this account link
    # embedded on, threaded in from `_shallow_step()`) as `source_url`
    # when we have one. Confirmed live this matters: Suffolk County NY's
    # Legislature reaches this path directly (Identify's rule-1 URL-host
    # match on `vimeo.com/showcase/.../embed`, no page fetch at all, so
    # there is no OTHER source of page context) -- without this, a
    # downstream "link out to the meeting page" (OUTCOME_EMBED_RESTRICTED)
    # pointed at the bare Vimeo showcase link instead of a real page.
    # Every other `_CALENDAR_PAGE_ERROR_PLATFORMS` member's `account_url`
    # (Legistar's Calendar.aspx, a Tampa/Wistia/Municode listing) is
    # already a real, useful page on its own, so this is narrowed to
    # vimeo specifically rather than applied to all of them.
    source_url = page_url if (page_url and platform == "vimeo") else account_url
    return Candidate(
        url=url,
        title=(row.get("title") or None) if isinstance(row, dict) else None,
        date=row.get("date") if isinstance(row, dict) else None,
        platform=platform,
        source_phase="list",
        lister=lister,
        source_url=source_url,
        has_video_hint=row.get("has_video_hint") if isinstance(row, dict) else None,
    )


def _candidates_from_dicts(
    rows: List[dict],
    *,
    platform: str,
    account_url: str,
    lister: str,
    page_url: Optional[str] = None,
) -> List[Candidate]:
    out: List[Candidate] = []
    for row in rows:
        candidate = _candidate_from_dict(
            row,
            platform=platform,
            account_url=account_url,
            lister=lister,
            page_url=page_url,
        )
        if candidate is not None:
            out.append(candidate)
    return out


# --- Lister (a): passive_verify's registered listing walkers ---------


def _make_fetch_adapter(
    fetcher: Fetcher,
) -> Callable[[str], Awaitable[tuple]]:
    """Wraps Meeting Finder's `Fetcher` in the `(html, final_url, error)`
    shape `passive_verify._fetch()` (and everything that calls it)
    expects. `need_links=True` always -- every passive_verify walker
    either regex-scans the HTML for links/JSON or POSTs to a JSON
    endpoint, and a page that loaded but rendered no `<a href>` links is
    exactly the headless-rung trigger `Fetcher.fetch()` already handles;
    this adapter doesn't need to special-case it.

    A `BudgetExceeded` (the caller asked for one more real fetch than
    `max_fetches` allows) becomes an ordinary fetch error string, the
    same shape any other `_fetch()` failure takes -- the walker just
    sees "this fetch failed" and stops (its own existing `if err or html
    is None: return []` handles it), it never needs to know WHY.
    """

    async def _fetch_via_fetcher(url: str) -> tuple:
        try:
            result = await fetcher.fetch(url, need_links=True)
        except BudgetExceeded as e:
            return None, None, str(e)
        if result.outcome is not None:
            # A named outcome (dns-unresolvable, timeout, a challenge, a
            # refused YouTube host, blocked-*) -- links_only Wayback HTML
            # is still usable content for a listing walker's regex scan,
            # everything else is a hard failure.
            html = result.html if result.links_only else None
            return html, result.final_url, result.outcome
        if result.status != 200 or result.html is None:
            return None, result.final_url, f"HTTP {result.status}"
        return result.html, result.final_url, None

    return _fetch_via_fetcher


async def _list_via_passive_verify_walker(
    platform: str, account_url: str, fetcher: Fetcher, limit: int
) -> Optional[ListResult]:
    passive_verify._ensure_walkers_registered()
    walker = passive_verify._LISTING_WALKERS.get(platform)
    if walker is None:
        return None
    fetch_adapter = _make_fetch_adapter(fetcher)
    try:
        with passive_verify.fetch_override(fetch_adapter):
            rows = await walker(account_url)
    except Exception as e:  # noqa: BLE001
        return ListResult(
            candidates=[],
            lister=f"passive_verify:{platform}",
            outcome=None,
            note=f"listing walker raised {type(e).__name__}: {e}",
        )
    if not rows:
        return None
    candidates = _candidates_from_dicts(
        rows[:limit],
        platform=platform,
        account_url=account_url,
        lister=f"passive_verify:{platform}",
    )
    if not candidates:
        return None
    return ListResult(
        candidates=candidates, lister=f"passive_verify:{platform}", outcome=None
    )


# --- Lister (a-1): a known Cablecast gallery URL, listed directly -----
#
# WO-1036 (2026-09-23, Ryan confirmed): a specific `/gallery/{id}` URL
# (with or without the older `/internetchannel/` prefix -- see
# `cablecast.py`'s own `_GALLERY_ID_RE` comment) is one governing body's
# own scoped show list -- e.g. Champaign, IL's real City Council hub,
# `champaign-cablecast.cablecast.tv/gallery/4`, linked from
# `champaignil.gov`'s own homepage nav as "Meeting Recordings". Tried
# BEFORE lister (a)'s own `_cablecast_walker` (registered for the bare
# platform name "cablecast" in `passive_verify._LISTING_WALKERS`, and
# always lists the whole TENANT ROOT regardless of `account_url`'s own
# path -- see that walker's own docstring): the tenant root mixes in
# unrelated programming (confirmed live, Virginia Beach VA, whose root
# mixes a live-stream embed with unrelated PEG content), so a known
# gallery should win when it has real candidates. Declines for a
# non-gallery Cablecast `account_url` (or on any failure), so lister (a)
# still runs as the fallback either way.


async def _list_via_cablecast_gallery(
    platform: str, account_url: str, fetcher: Fetcher, limit: int
) -> Optional[ListResult]:
    if platform != "cablecast" or not _GALLERY_ID_RE.search(urlparse(account_url).path):
        return None
    # Some Cablecast portal domains hang indefinitely over HTTPS (see
    # cablecast.py's own module docstring, the Detroit finding) --
    # `resolve()`'s own gallery/show paths always force HTTP first for
    # exactly this reason; this lister does the same for consistency.
    fetch_url = CablecastAssetFinder._force_http(account_url)
    try:
        result = await fetcher.fetch(fetch_url, need_links=False)
    except BudgetExceeded as e:
        return ListResult(
            candidates=[], lister="cablecast_gallery", outcome=None, note=str(e)
        )
    html = result.html if (result.status == 200 or result.links_only) else None
    if not html:
        return ListResult(
            candidates=[],
            lister="cablecast_gallery",
            outcome=None,
            note=f"could not fetch {fetch_url} ({result.outcome or result.status})",
        )
    rows = list_gallery_shows(result.final_url or fetch_url, html)
    if not rows:
        return None
    candidates = _candidates_from_dicts(
        rows[:limit],
        platform=platform,
        account_url=account_url,
        lister="cablecast_gallery",
    )
    if not candidates:
        return None
    return ListResult(candidates=candidates, lister="cablecast_gallery", outcome=None)


# --- Lister (a-cc): "Cablecast Connect" WordPress plugin, listed
# directly (WO-1054 rule 3) ---
#
# "Cablecast Connect" -- a WordPress plugin some PEG-access nonprofits use
# to run their whole public site (a different thing from `cablecast.py`'s
# own `_WATCH_VOD_EMBED_PATH_RE`, WO-1036, which handles a BARE iframe
# embed dropped into an otherwise-ordinary page -- this is the plugin
# that IS the site). Confirmed live 2026-09-24 (Ryan's own browsing
# note): Mendota Heights, MN's real station page
# (`townsquare.tv/programs/site/mendota-heights-8/`, reached by following
# the town's own `mendotaheightsmn.gov/280/Watch-a-Public-Meeting-Online`
# link) already server-renders a real "Recently Added" listing --
# `<ul class="gc-cc-grid gc-cc-show-grid">` of `.gc-cc-card` items, each
# with its own `<a href=".../programs/show/{slug}-{site}-{id}/">`,
# `.gc-cc-card-title` and `.gc-cc-air-date` -- and the SAME markup is
# also served on demand by a real, unauthenticated WordPress REST route,
# `GET {origin}/wp-json/cablecast/v1/recent-shows?site_id={n}&limit={n}`
# (confirmed live: `wp-json`'s own namespace list carries `cablecast/v1`
# whenever this plugin is active). `identify.py`'s own
# `_cablecast_connect_signal()` recognizes a page like this directly from
# its CSS classes and hands back `platform="cablecast_connect"`,
# `account_url=` the page itself.
#
# Each show's actual VIDEO lives one click further, on its own
# `/programs/show/.../` page -- a real Cablecast `watch-vod-embed` iframe
# (`reflect-tst-mn.cablecast.tv/watch-vod-embed?showId=...&site=...`,
# confirmed live, already resolvable by `app/platforms/cablecast.py`'s
# existing `_resolve_watch_vod_embed()` per that file's own WO-1036 note)
# -- never the WordPress page's own URL, which `detect_platform()`
# doesn't recognize at all (Resolve would fail on it directly). This
# lister fetches up to `_CABLECAST_CONNECT_UNWRAP_LIMIT` of the newest
# show pages (newest first, the listing's own order) to recover that
# iframe `src` -- one extra fetch per show, capped well below `limit` so
# a request for many candidates doesn't spend the whole government's
# fetch budget unwrapping shows Resolve will likely never try (Resolve
# tries at most a handful of candidates anyway -- `pick.
# MAX_CANDIDATES_TRIED`).
_CABLECAST_CONNECT_SITE_ID_RE = re.compile(r'data-site-id="(\d+)"')
_CABLECAST_CONNECT_SHOW_URL_RE = re.compile(r"/programs/show/", re.I)
_CABLECAST_CONNECT_IFRAME_RE = re.compile(
    r'<iframe[^>]+class="trms-player"[^>]+src="([^"]+)"', re.I
)
_CABLECAST_CONNECT_UNWRAP_LIMIT = 5


def _parse_cablecast_connect_cards(html: str, base_url: str) -> List[dict]:
    """Every `.gc-cc-card`/`.gc-cc-show-card` on `html` whose own link is
    a specific SHOW (`/programs/show/...` -- excludes a "Popular Shows"
    widget's series/category links, e.g. Mendota Heights' own real
    `/programs/city-council-8-33/`, which has no single video to
    resolve), in the page's own newest-first render order."""
    soup = BeautifulSoup(html or "", "html.parser")
    out: List[dict] = []
    seen = set()
    for card in soup.select(".gc-cc-card, .gc-cc-show-card"):
        a = card.find("a", href=True)
        if a is None:
            continue
        url = urljoin(base_url, a["href"].strip())
        if not _CABLECAST_CONNECT_SHOW_URL_RE.search(urlparse(url).path):
            continue
        if url in seen:
            continue
        seen.add(url)
        title_el = card.select_one(".gc-cc-card-title")
        date_el = card.select_one(".gc-cc-air-date")
        out.append(
            {
                "url": url,
                "title": title_el.get_text(strip=True) if title_el else None,
                "date_text": date_el.get_text(strip=True) if date_el else None,
            }
        )
    return out


async def _cablecast_connect_show_rows(
    account_url: str, fetcher: Fetcher, limit: int
) -> Tuple[List[dict], str]:
    """The town's own real show rows -- straight off `account_url`'s
    already-fetched page when it has enough, else topped up with one more
    fetch to the plugin's own `recent-shows` REST route (needs the page's
    own `data-site-id`, WO-1054's real Mendota Heights confirmation).
    Returns `(rows, final_url)`."""
    result = await fetcher.fetch(account_url, need_links=True)
    html = result.html if (result.status == 200 or result.links_only) else None
    if not html:
        return [], result.final_url or account_url
    final_url = result.final_url or account_url
    rows = _parse_cablecast_connect_cards(html, final_url)
    if len(rows) >= limit:
        return rows, final_url
    site_id_match = _CABLECAST_CONNECT_SITE_ID_RE.search(html)
    if not site_id_match:
        return rows, final_url
    origin = f"{urlparse(final_url).scheme}://{urlparse(final_url).netloc}"
    api_url = (
        f"{origin}/wp-json/cablecast/v1/recent-shows"
        f"?site_id={site_id_match.group(1)}&limit={max(limit, len(rows))}"
    )
    try:
        api_result = await fetcher.fetch(api_url, need_links=False)
    except BudgetExceeded:
        return rows, final_url
    if api_result.status != 200 or not api_result.html:
        return rows, final_url
    try:
        payload = json.loads(api_result.html)
    except (json.JSONDecodeError, TypeError):
        return rows, final_url
    fragment = payload.get("html") if isinstance(payload, dict) else None
    if not fragment:
        return rows, final_url
    api_rows = _parse_cablecast_connect_cards(fragment, final_url)
    if len(api_rows) > len(rows):
        return api_rows, final_url
    return rows, final_url


async def _list_via_cablecast_connect(
    platform: str, account_url: str, fetcher: Fetcher, limit: int
) -> Optional[ListResult]:
    if platform != "cablecast_connect":
        return None
    try:
        rows, final_url = await _cablecast_connect_show_rows(
            account_url, fetcher, limit
        )
    except BudgetExceeded as e:
        return ListResult(
            candidates=[], lister="cablecast_connect", outcome=None, note=str(e)
        )
    if not rows:
        return None
    candidates: List[Candidate] = []
    for row in rows[:_CABLECAST_CONNECT_UNWRAP_LIMIT]:
        if len(candidates) >= limit:
            break
        show_url = row["url"]
        try:
            show_result = await fetcher.fetch(show_url, need_links=False)
        except BudgetExceeded:
            break
        show_html = show_result.html if show_result.status == 200 else None
        if not show_html:
            continue
        iframe_match = _CABLECAST_CONNECT_IFRAME_RE.search(show_html)
        if not iframe_match:
            continue
        video_url = urljoin(show_result.final_url or show_url, iframe_match.group(1))
        date = parse_candidate_date(row.get("date_text") or "")
        candidates.append(
            Candidate(
                url=video_url,
                title=row.get("title"),
                date=date.strftime("%Y-%m-%d") if date else None,
                platform="cablecast",
                source_phase="list",
                lister="cablecast_connect",
                source_url=show_url,
                has_video_hint=True,
            )
        )
    if not candidates:
        return ListResult(
            candidates=[],
            lister="cablecast_connect",
            outcome=None,
            note=(
                f"found {len(rows)} real show row(s) on {final_url} but none of "
                f"the first {min(len(rows), _CABLECAST_CONNECT_UNWRAP_LIMIT)} had "
                "a resolvable watch-vod-embed iframe"
            ),
        )
    return ListResult(candidates=candidates, lister="cablecast_connect", outcome=None)


# --- Lister (a-wp): a generic WordPress site's own REST API, listed
# directly (WO-1054 rule 6) ---
#
# Ryan's own brief (2026-09-24): "a WordPress site (generator meta /
# wp-json present) is a listable account: GET /wp-json/wp/v2/
# posts?search=meeting (and ?search=video), or /feed/; each post that
# embeds a recognised video platform or media file is a candidate with
# its title/date." A LIST method, not a hop -- tried only once Identify
# already believes the account itself is a plain WordPress site
# (`platform="wordpress"`, set by `identify.py`'s own `_wordpress_
# signal()` off the standard `<link rel="https://api.w.org/">` REST
# discovery tag -- present on every stock WordPress install regardless of
# which plugin, if any, it's also running). Wilder, KY (`wilderky.gov`)
# is the brief's own example to try, and may truthfully come back with
# none -- that's a real, valid finding here (`ListResult.candidates=[]`,
# falling through to `OUTCOME_NO_MEETING_NOR_VIDEO` the same as any other
# empty lister), not a bug.
_WORDPRESS_SEARCH_TERMS = ("meeting", "video")
_WORDPRESS_POSTS_PER_SEARCH = 10


def _wordpress_post_candidate(post: dict, *, platform: str) -> Optional[Candidate]:
    """One `wp-json/wp/v2/posts` row -> a `Candidate`, only when its own
    rendered content embeds a video `detect_platform()`/`is_direct_file_
    url()` recognizes, or a same-site media-library file -- Ryan's own
    "each post that embeds a recognised video platform or media file"
    condition. A post that's merely ABOUT a meeting, with no actual video
    attached, is not a candidate here (List's job is a video lead, not a
    document search) -- it stays reachable through the ordinary
    Scan/Hop path on the post's own page instead."""
    if not isinstance(post, dict):
        return None
    link = post.get("link")
    if not link:
        return None
    content_field = post.get("content")
    content = content_field.get("rendered") if isinstance(content_field, dict) else None
    if not content:
        return None
    soup = BeautifulSoup(content, "html.parser")
    video_url = None
    for tag in soup.find_all(("a", "iframe", "video", "source")):
        raw = tag.get("href") or tag.get("src")
        if not raw:
            continue
        candidate_url = urljoin(link, raw.strip())
        found_platform = detect_platform(candidate_url)
        if found_platform not in ("unknown", "wordpress", None):
            video_url = candidate_url
            break
        if is_direct_file_url(candidate_url):
            video_url = candidate_url
            break
    if not video_url:
        return None
    title_field = post.get("title")
    title_html = title_field.get("rendered") if isinstance(title_field, dict) else None
    title = (
        BeautifulSoup(title_html, "html.parser").get_text(strip=True)
        if title_html
        else None
    )
    date = post.get("date")
    return Candidate(
        url=video_url,
        title=title or None,
        date=date[:10] if date else None,
        platform=platform,
        source_phase="list",
        lister="wordpress_rest",
        source_url=link,
        has_video_hint=True,
    )


async def _wordpress_search_posts(
    origin: str, term: str, fetcher: Fetcher
) -> List[dict]:
    url = (
        f"{origin}/wp-json/wp/v2/posts?search={term}"
        f"&per_page={_WORDPRESS_POSTS_PER_SEARCH}&_fields=link,title,date,content"
    )
    try:
        result = await fetcher.fetch(url, need_links=False)
    except BudgetExceeded:
        return []
    if result.status != 200 or not result.html:
        return []
    try:
        payload = json.loads(result.html)
    except (json.JSONDecodeError, TypeError):
        return []
    return payload if isinstance(payload, list) else []


async def _list_via_wordpress(
    platform: str, account_url: str, fetcher: Fetcher, limit: int
) -> Optional[ListResult]:
    if platform != "wordpress":
        return None
    origin = f"{urlparse(account_url).scheme}://{urlparse(account_url).netloc}"
    candidates: List[Candidate] = []
    seen_urls = set()
    notes: List[str] = []
    for term in _WORDPRESS_SEARCH_TERMS:
        try:
            posts = await _wordpress_search_posts(origin, term, fetcher)
        except BudgetExceeded as e:
            notes.append(str(e))
            break
        for post in posts:
            candidate = _wordpress_post_candidate(post, platform=platform)
            if candidate is None or candidate.url in seen_urls:
                continue
            seen_urls.add(candidate.url)
            candidates.append(candidate)
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break
    if not candidates:
        return ListResult(
            candidates=[],
            lister="wordpress_rest",
            outcome=None,
            note="; ".join(notes)
            if notes
            else f"no video-bearing post found on {origin}",
        )
    return ListResult(candidates=candidates, lister="wordpress_rest", outcome=None)


# --- Lister (a2): a known Swagit /views/{id} page, listed directly ---
#
# WO-1036 (2026-09-23): Swagit's tab-slug listing pages (e.g.
# `/commissioners-court`) are empty JS-filled shells on `*.new.swagit.com`
# -- confirmed live across multiple tenants, even fetched headless. Only
# a numeric `/views/{id}` page's own `#video-table` is server-rendered
# and full (9 real rows confirmed live on Wise County, TX's
# `wisecountytx.new.swagit.com/views/908/`, vs. 0 on its own
# `/commissioners-court` tab-slug page). rtr-discovery's own
# `SwagitEnumerator` already parses this exact `table#video-table` shape
# for its tab-slug pages -- the row parsing below is copied from there
# (same real shape, not re-derived), just pointed at a `/views/{id}` URL
# lister (b) never reaches with the specific path intact (see
# `_list_via_discovery()`'s own docstring: it passes only the account
# URL's `netloc` to `list_tenant()`, discarding the path). Tried before
# lister (b) so a known-good `/views/{id}` URL is used directly rather
# than falling through to a bare-host tenant walk that lands back on an
# empty tab-slug default. A bare `/videos/{id}` URL is itself a single
# real candidate -- no listing page to fetch at all.
_SWAGIT_VIEWS_URL_RE = re.compile(r"/views/(\d+)\b", re.I)
_SWAGIT_VIDEO_URL_RE = re.compile(r"/videos/(\d+)\b", re.I)
_SWAGIT_ROW_DATE_FORMATS = (
    "%b %d, %Y",
)  # "Sep 24, 2014" -- confirmed on every row seen


def _parse_swagit_video_table(html: str, base_url: str) -> List[Candidate]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find(id="video-table")
    if table is None:
        return []
    candidates: List[Candidate] = []
    for tr in table.find_all("tr"):
        a = tr.find("a", href=True)
        if a is None:
            continue
        m = _SWAGIT_VIDEO_URL_RE.search(a["href"])
        if not m:
            continue
        td = tr.find("td")
        lines = (
            [line.strip() for line in td.get_text("\n").split("\n") if line.strip()]
            if td is not None
            else []
        )
        title = lines[0] if lines else None
        date = None
        if len(lines) > 1:
            for fmt in _SWAGIT_ROW_DATE_FORMATS:
                try:
                    date = datetime.strptime(lines[-1], fmt).strftime("%Y-%m-%d")
                    break
                except ValueError:
                    continue
        candidates.append(
            Candidate(
                url=urljoin(base_url, f"/videos/{m.group(1)}"),
                title=title,
                date=date,
                platform="swagit",
                source_phase="list",
                lister="swagit_views_page",
                source_url=base_url,
                has_video_hint=True,
            )
        )
    return candidates


async def _list_via_swagit_views_page(
    platform: str, account_url: str, fetcher: Fetcher, limit: int
) -> Optional[ListResult]:
    if platform != "swagit":
        return None
    parsed = urlparse(account_url)
    video_match = _SWAGIT_VIDEO_URL_RE.search(parsed.path)
    if video_match:
        # Already a specific video URL -- nothing to list, it's the one
        # candidate.
        return ListResult(
            candidates=[
                Candidate(
                    url=account_url,
                    title=None,
                    date=None,
                    platform=platform,
                    source_phase="list",
                    lister="swagit_views_page",
                    source_url=account_url,
                    has_video_hint=True,
                )
            ],
            lister="swagit_views_page",
            outcome=None,
        )
    if not _SWAGIT_VIEWS_URL_RE.search(parsed.path):
        return None
    try:
        result = await fetcher.fetch(account_url, need_links=True)
    except BudgetExceeded as e:
        return ListResult(
            candidates=[], lister="swagit_views_page", outcome=None, note=str(e)
        )
    html = result.html if (result.status == 200 or result.links_only) else None
    if not html:
        return ListResult(
            candidates=[],
            lister="swagit_views_page",
            outcome=None,
            note=f"could not fetch {account_url} ({result.outcome or result.status})",
        )
    candidates = _parse_swagit_video_table(html, result.final_url or account_url)
    if not candidates:
        return None
    return ListResult(
        candidates=candidates[:limit], lister="swagit_views_page", outcome=None
    )


# --- Lister (b): rtr-discovery's list_tenant() ------------------------

_discovery_module = None
_discovery_import_failed: Optional[str] = None


def _load_discovery_module():
    """Lazily imports rtr-discovery's `discovery.list_one` from
    `RTR_DISCOVERY_PATH` (default `~/Documents/rtr-discovery`), caching
    the result (including a failure) for the life of the process --
    every real caller in a single Meeting Finder run wants the same
    answer, and re-attempting a broken import on every single account
    would just repeat the same failure `len(accounts)` times.
    """
    global _discovery_module, _discovery_import_failed
    if _discovery_module is not None:
        return _discovery_module
    if _discovery_import_failed is not None:
        return None
    root = Path(
        os.environ.get("RTR_DISCOVERY_PATH", "~/Documents/rtr-discovery")
    ).expanduser()
    list_one_path = root / "discovery" / "list_one.py"
    if not list_one_path.is_file():
        _discovery_import_failed = f"{list_one_path} not found"
        return None
    try:
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        spec = importlib.util.find_spec("discovery.list_one")
        if spec is None:
            # sys.path was just amended -- invalidate the finder cache so
            # a bare `import discovery` doesn't shadow the real package
            # via some stale negative-lookup cache.
            importlib.invalidate_caches()
            spec = importlib.util.find_spec("discovery.list_one")
        if spec is None:
            _discovery_import_failed = "discovery.list_one not importable"
            return None
        module = importlib.import_module("discovery.list_one")
    except Exception as e:  # noqa: BLE001
        _discovery_import_failed = f"{type(e).__name__}: {e}"
        return None
    _discovery_module = module
    return module


async def _list_via_discovery(
    platform: str,
    account_url: str,
    limit: int,
    platform_params: Optional[dict],
) -> Optional[ListResult]:
    if platform in _NEVER_DISCOVERY_PLATFORMS:
        return None
    passive_verify._ensure_walkers_registered()
    if platform in passive_verify._LISTING_WALKERS:
        # passive_verify already has a bespoke walker for this platform --
        # lister (a) already tried it (and, being tried first, would have
        # returned candidates if there were any). docs/MEETING_FINDER.md's
        # List (b) row is explicitly "for platforms passive_verify has no
        # walker for" -- don't reach for rtr-discovery on these.
        return None
    module = _load_discovery_module()
    if module is None:
        return ListResult(
            candidates=[],
            lister=None,
            outcome=None,
            note=(
                "rtr-discovery unavailable "
                f"({_discovery_import_failed}) -- degrading to the next lister"
            ),
        )
    netloc = urlparse(account_url).netloc
    if not netloc:
        return None
    try:
        result = await module.list_tenant(
            platform,
            netloc,
            limit=limit,
            params=platform_params,
        )
    except Exception as e:  # noqa: BLE001
        return ListResult(
            candidates=[],
            lister=f"discovery:{platform}",
            outcome=None,
            note=f"discovery.list_tenant raised {type(e).__name__}: {e}",
        )
    if result.status != module.STATUS_OK or not result.candidates:
        note = f"discovery.list_tenant status={result.status}"
        if result.reason:
            note += f" ({result.reason})"
        return ListResult(
            candidates=[], lister=f"discovery:{platform}", outcome=None, note=note
        )
    candidates = [
        Candidate(
            url=c.url,
            title=c.title,
            date=c.date,
            platform=c.platform or platform,
            source_phase="list",
            lister=f"discovery:{platform}",
            source_url=account_url,
            has_video_hint=c.has_video_hint,
        )
        for c in result.candidates[:limit]
    ]
    if not candidates:
        return None
    return ListResult(
        candidates=candidates,
        lister=f"discovery:{platform}",
        outcome=None,
        params=result.params or None,
    )


# --- Lister (c): the adapter's own CalendarPageError pick-list -------


async def _list_via_calendar_page_error(
    platform: str, account_url: str, limit: int, *, page_url: Optional[str] = None
) -> Optional[ListResult]:
    if platform not in _CALENDAR_PAGE_ERROR_PLATFORMS:
        return None
    try:
        finder = get_finder(platform)
    except UnsupportedPlatformError:
        return None
    try:
        await finder.resolve(account_url)
    except CalendarPageError as e:
        rows = [dict(c) for c in e.candidates][:limit]
        candidates = _candidates_from_dicts(
            rows,
            platform=platform,
            account_url=account_url,
            lister="adapter_list",
            page_url=page_url,
        )
        if not candidates:
            return None
        return ListResult(candidates=candidates, lister="adapter_list", outcome=None)
    except YouTubeResolveBlocked:
        return None
    except Exception as e:  # noqa: BLE001
        return ListResult(
            candidates=[],
            lister="adapter_list",
            outcome=None,
            note=f"{platform} resolve() raised {type(e).__name__}: {e} (not a listing)",
        )
    # resolve() succeeded outright -- account_url was already one specific
    # meeting, not a listing. Nothing for List to add; Resolve (called
    # separately, on whatever candidates List/Scan produce) is where this
    # would actually get used.
    return None


# --- Lister (d): adapters that walk a hub themselves ------------------


async def _list_via_adapter_hub(
    platform: str, account_url: str
) -> Optional[ListResult]:
    if platform not in _ADAPTER_HUB_PLATFORMS:
        return None
    try:
        finder = get_finder(platform)
    except UnsupportedPlatformError:
        return None
    try:
        resolved = await finder.resolve(account_url)
    except (CalendarPageError, YouTubeResolveBlocked):
        return None
    except Exception as e:  # noqa: BLE001
        return ListResult(
            candidates=[],
            lister="adapter_hub",
            outcome=None,
            note=f"{platform} resolve() raised {type(e).__name__}: {e}",
        )
    if not (resolved.segments or resolved.video_url or resolved.agenda_items):
        return None
    candidate = Candidate(
        url=resolved.source_url or account_url,
        title=resolved.title,
        date=resolved.date,
        platform=resolved.platform or platform,
        source_phase="list",
        lister="adapter_hub",
        source_url=account_url,
        has_video_hint=bool(resolved.video_url),
    )
    return ListResult(candidates=[candidate], lister="adapter_hub", outcome=None)


# --- Lister (e): generic same-platform link scan ----------------------


async def _list_via_generic_scan(
    platform: str, account_url: str, fetcher: Fetcher, limit: int
) -> Optional[ListResult]:
    fetch_adapter = _make_fetch_adapter(fetcher)
    try:
        with passive_verify.fetch_override(fetch_adapter):
            rows = await passive_verify._generic_link_scan_walker(account_url)
    except Exception as e:  # noqa: BLE001
        return ListResult(
            candidates=[],
            lister="generic_link_scan",
            outcome=None,
            note=f"generic link scan raised {type(e).__name__}: {e}",
        )
    if not rows:
        return None
    candidates = _candidates_from_dicts(
        rows[:limit],
        platform=platform,
        account_url=account_url,
        lister="generic_link_scan",
    )
    if not candidates:
        return None
    return ListResult(candidates=candidates, lister="generic_link_scan", outcome=None)


# --- Agenda-only fallback: platforms whose lister filters to video-only ---
#
# Platforms where lister (a)/(c) only surfaces a row when it already has a
# video link, so a real agenda-only account (meetings posted, no video
# yet) reads identically to an empty one. Registered per-platform rather
# than a generic "re-fetch and guess" step: each one needs its own
# adapter-specific row parser (`_find_candidate_rows()`'s own row shape is
# CivicPlus's, not a generic contract). See this module's own docstring
# for which platforms were checked and found NOT to need this (they
# already return every row regardless of video).
_AGENDA_ONLY_FALLBACK_PLATFORMS = frozenset({"civicplus"})


async def _civicplus_rows(
    account_url: str, fetcher: Fetcher
) -> tuple[List[dict], Optional[str]]:
    """One fetch to `account_url` (falling back to the canonical
    `/AgendaCenter` guess only if that first page has no rows at all) --
    `CivicPlusAssetFinder()._find_candidate_rows()` directly, NOT
    `passive_verify._civicplus_walker()`, whose own behavior stays
    exactly as it is today for `verify_hub()` and every other existing
    caller (see module docstring). Returns every real (title+date) row
    found, video-bearing or not -- shared by both the light check (a0)
    and the agenda-only fallback (after lister e) below, so a real
    account only ever needs ONE fetch to answer both questions."""
    from bs4 import BeautifulSoup

    from app.platforms.civicplus import CivicPlusAssetFinder

    finder = CivicPlusAssetFinder()

    async def _rows_for(url: str) -> tuple[List[dict], Optional[str]]:
        try:
            result = await fetcher.fetch(url, need_links=True)
        except BudgetExceeded:
            return [], None
        if result.status != 200 or result.html is None:
            return [], None
        final = result.final_url or url
        soup = BeautifulSoup(result.html, "html.parser")
        return finder._find_candidate_rows(soup, final), final

    rows, final_url = await _rows_for(account_url)
    if not rows:
        base = f"{urlparse(final_url or account_url).scheme}://{urlparse(final_url or account_url).netloc}"
        guess = f"{base}/AgendaCenter"
        if guess.rstrip("/") != (final_url or account_url).rstrip("/"):
            rows, final_url = await _rows_for(guess)
    return rows, final_url


async def _list_via_civicplus_light_check(
    platform: str, account_url: str, fetcher: Fetcher, limit: int
) -> Optional[ListResult]:
    """Conductor review (2026-09-23), Cass County, MN: `_civicplus_
    walker()` (lister a, below) can spend up to ~8 real fetches (4
    AgendaCenter category pages + 3 video-nav links) confirming a real
    agenda-only tenant has no video anywhere, leaving nothing in the
    government's shared fetch budget for the agenda-only fallback that
    would otherwise report it correctly as `meeting-without-video`. This
    light, CivicPlus-specific check runs FIRST (before the heavy walker),
    on the ONE page most real CivicPlus tenants' current meeting list
    already lives on (`account_url`, or the canonical `/AgendaCenter`
    guess) -- one real fetch, occasionally two. If that page already has
    video-bearing rows, they're returned directly (the heavy walker's own
    multi-category crawl is redundant for the common case where the
    tenant's current category already has video). If it only has
    agenda-only rows, those are returned instead (`has_video_hint=False`)
    -- the real, budget-starved case this WO's own smoke test found live.
    Only when this ONE page has no rows at all does this return `None`,
    letting the heavier listers check other categories/nav links this
    light check doesn't."""
    if platform != "civicplus":
        return None
    rows, _ = await _civicplus_rows(account_url, fetcher)
    if not rows:
        return None
    video_rows = [r for r in rows if r.get("url")]
    if video_rows:
        candidates = _candidates_from_dicts(
            video_rows[:limit],
            platform=platform,
            account_url=account_url,
            lister="civicplus_light_check",
        )
        if candidates:
            return ListResult(
                candidates=candidates, lister="civicplus_light_check", outcome=None
            )
    agenda_rows = _civicplus_agenda_only_rows(rows, limit)
    if agenda_rows:
        candidates = _candidates_from_dicts(
            agenda_rows,
            platform=platform,
            account_url=account_url,
            lister="civicplus_agenda_only",
        )
        if candidates:
            return ListResult(
                candidates=candidates,
                lister="civicplus_agenda_only",
                outcome=None,
                note="real meeting rows found with no video link -- has_video_hint=False",
            )
    return None


def _civicplus_agenda_only_rows(rows: List[dict], limit: int) -> List[dict]:
    """Every real row with an `agenda_link`/`packet_link` but no video
    `url`, newest-first (the page's own render order) -- a row with
    neither link is worthless as a Candidate and is skipped."""
    out: List[dict] = []
    for row in rows:
        if row.get("url"):
            continue
        link = row.get("agenda_link") or row.get("packet_link")
        if not link:
            continue
        out.append(
            {
                "title": row.get("title") or "",
                "date": row.get("date"),
                "url": link,
                "has_video_hint": False,
            }
        )
        if len(out) >= limit:
            break
    return out


async def _civicplus_agenda_only_fallback(
    account_url: str, fetcher: Fetcher, limit: int
) -> List[dict]:
    """Safety net, tried after every other lister (see `list_account()`'s
    own ordering): re-fetches `account_url` (see `_civicplus_rows()`)
    and returns its agenda-only rows. Reached only when
    `_list_via_civicplus_light_check()` (a0, tried FIRST) found no rows
    at all on that one page but a LATER lister's own, different page
    (e.g. `_civicplus_walker()`'s own other AgendaCenter categories or
    `Calendar.aspx`) came back empty too -- worth one more real look at
    the primary page before giving up entirely."""
    rows, _ = await _civicplus_rows(account_url, fetcher)
    return _civicplus_agenda_only_rows(rows, limit)


async def _list_via_agenda_only_fallback(
    platform: str, account_url: str, fetcher: Fetcher, limit: int
) -> Optional[ListResult]:
    if platform not in _AGENDA_ONLY_FALLBACK_PLATFORMS:
        return None
    if platform == "civicplus":
        try:
            rows = await _civicplus_agenda_only_fallback(account_url, fetcher, limit)
        except Exception as e:  # noqa: BLE001
            return ListResult(
                candidates=[],
                lister="civicplus_agenda_only",
                outcome=None,
                note=f"agenda-only fallback raised {type(e).__name__}: {e}",
            )
    else:  # pragma: no cover -- no other platform registered yet
        return None
    if not rows:
        return None
    candidates = _candidates_from_dicts(
        rows,
        platform=platform,
        account_url=account_url,
        lister="civicplus_agenda_only",
    )
    if not candidates:
        return None
    return ListResult(
        candidates=candidates,
        lister="civicplus_agenda_only",
        outcome=None,
        note="real meeting rows found with no video link -- has_video_hint=False",
    )


# --- Granicus bare-hub view_id discovery (WO-1030, conductor review) ---
#
# `app/platforms/granicus.py`'s `list_recent_video_meetings()` (what
# lister (a)'s `_granicus_walker()` calls) REQUIRES the URL it's given to
# already carry a `view_id` query param -- confirmed by reading it: it
# parses `view_id` out of the URL and returns `[]` outright when there is
# none. Identify's own rule-1 URL match (`detect_platform()`) recognizes
# `https://cityoftacoma.granicus.com/` as `granicus` from the host alone,
# with no `view_id` -- a real, confirmed live gap (WO-1030's own smoke
# test on Tacoma, WA): every lister came back empty for a real Granicus
# tenant that has real, current video (`.../player/clip/7460`), because
# nothing ever discovered WHICH `view_id` this tenant's video listing
# lives under.
#
# `scripts/wo134_confirmed_hits_ingest.py`'s `granicus_locate_listing()`
# already solves exactly this (RSS-first, `view_id=1..5`, its own comment
# citing WO-169's cheap-RSS-before-expensive-HTML-table ordering) -- not
# reused directly here because it opens its own `aiohttp.ClientSession`
# (`fetch_html()`), which would bypass Meeting Finder's own `Fetcher`
# entirely (no `max_fetches` budget, no per-host politeness, no YouTube
# guard). Same algorithm, ported to call `fetcher.fetch()` instead, so a
# real Granicus tenant with a real view_id further out than the probe
# range (rare -- WO-134's own range of 1..5 was chosen from real
# tenants) degrades to `no-meeting-nor-video` rather than spending
# unbounded budget on it.
_GRANICUS_VIEW_ID_RE = re.compile(r"[?&]view_id=\d+", re.IGNORECASE)
_GRANICUS_VIEW_ID_PROBE_MAX = 6


_RSS_CHANNEL_TITLE_RE = re.compile(
    r"<channel>.*?<title>(.*?)</title>", re.IGNORECASE | re.DOTALL
)

# WO-1041's own name-overlap rule (`app.utils.video_hand_check`'s
# `_NAME_STOPWORDS`) isn't imported here to avoid a cross-module private
# dependency for one small word list -- kept in sync by hand; both lists
# exist to strip the same generic government-name words ("city", "county",
# "town"...) before comparing two names for a distinctive overlap.
_GRANICUS_NAME_STOPWORDS = frozenset(
    {
        "the", "and", "city", "town", "village", "county", "township",
        "borough", "parish", "municipality", "municipal", "government",
        "district", "school", "schools", "regional", "state", "board",
        "department", "authority", "commission", "council", "unified",
        "independent", "metropolitan", "utility", "utilities", "public",
        "of", "for",
    }
)  # fmt: skip


def _distinctive_words(name: Optional[str]) -> frozenset:
    words = re.findall(r"[a-z0-9]+", (name or "").lower())
    return frozenset(
        w for w in words if len(w) >= 3 and w not in _GRANICUS_NAME_STOPWORDS
    )


async def _granicus_discover_view_id(
    account_url: str, fetcher: Fetcher, *, gov_name: Optional[str] = None
) -> Optional[str]:
    """Probes `ViewPublisherRSS.php?view_id=1..6&mode=video` on
    `account_url`'s own host, cheapest (RSS, not the HTML table) first,
    same range `granicus_locate_listing()` uses.

    WO-1041 (Grass Valley/Nevada City/Nevada County case, all three real
    governing bodies sharing one `nevco.granicus.com` account under
    different `view_id`s): a shared Granicus account can list more than
    one government's own body. Rather than stopping at the first populated
    `view_id` (the old behavior -- silently correct only when an account
    happens to carry a single government), this now reads every populated
    `view_id` in the probe range and, when `gov_name` is given, picks the
    one whose own RSS channel title shares a distinctive word with it
    (`nevco.granicus.com`'s real channel titles name the body itself, e.g.
    "Grass Valley City Council" for `view_id=4`). Falls back to the FIRST
    populated `view_id` -- the original behavior, still correct for the
    (much more common) single-government account -- when `gov_name` is
    absent or matches none of the populated channels' titles.
    """
    netloc = urlparse(account_url).netloc
    if not netloc:
        return None
    name_words = _distinctive_words(gov_name)
    populated: List[Tuple[int, str]] = []
    for view_id in range(1, _GRANICUS_VIEW_ID_PROBE_MAX + 1):
        rss_url = f"https://{netloc}/ViewPublisherRSS.php?view_id={view_id}&mode=video"
        try:
            result = await fetcher.fetch(rss_url, need_links=False)
        except BudgetExceeded:
            break
        html = result.html or ""
        if "<item>" in html and "(No Video)" not in html:
            title_match = _RSS_CHANNEL_TITLE_RE.search(html)
            channel_title = title_match.group(1).strip() if title_match else ""
            populated.append((view_id, channel_title))
    if not populated:
        return None
    if name_words:
        for view_id, channel_title in populated:
            if _distinctive_words(channel_title) & name_words:
                return f"https://{netloc}/ViewPublisher.php?view_id={view_id}"
    view_id, _ = populated[0]
    return f"https://{netloc}/ViewPublisher.php?view_id={view_id}"


# WO-1058: known shared regional-TV hubs (WO-1053's
# `regional_tv_hubs.csv`) -- confirmed BY HAND to carry more than one
# government's own section under one account (a TelVue org token or a
# Cablecast tenant root). Only on one of these does the full (weak-pattern
# included) shared-hub filter run -- see `pick._STRONG_PLACE_PHRASE_
# PATTERNS`'s own comment for why running it on every account was the
# real WO-1058 bug (21 of 68 regressions in calibration run D, none of
# them an actual shared hub).
_HUB_CSV_PATH = (
    Path(__file__).resolve().parents[2]
    / "utils"
    / "jurisdiction_data"
    / "regional_tv_hubs.csv"
)
# A TelVue account url's org token lives in its path
# (".../player/<token>/home"), not its host -- every TelVue hub shares the
# same host (`videoplayer.telvue.com`), so host alone can't tell one
# organization's account apart from another's. A Cablecast tenant's
# per-town sections instead live under query params on ONE host
# (`?site=N`), so host alone IS the right granularity there. `_hub_key()`
# captures both shapes: (host, token-or-None).
_HUB_TOKEN_RE = re.compile(r"/player/([^/]+)/", re.I)
_KNOWN_HUB_KEYS: Optional[frozenset] = None


def _hub_key(url: str) -> Tuple[str, Optional[str]]:
    parsed = urlparse(url)
    m = _HUB_TOKEN_RE.search(parsed.path)
    return (parsed.netloc.lower(), m.group(1).lower() if m else None)


def _known_hub_keys() -> frozenset:
    global _KNOWN_HUB_KEYS
    if _KNOWN_HUB_KEYS is None:
        keys = set()
        try:
            with _HUB_CSV_PATH.open(newline="", encoding="utf-8") as f:
                for row in _csv.DictReader(f):
                    url = (row.get("url") or "").strip()
                    if url:
                        keys.add(_hub_key(url))
        except FileNotFoundError:
            pass
        _KNOWN_HUB_KEYS = frozenset(keys)
    return _KNOWN_HUB_KEYS


def is_known_shared_hub(account_url: str) -> bool:
    """True only when `account_url` matches a hub already confirmed, by
    hand, in `regional_tv_hubs.csv` to carry more than one government's
    own section. An account not in that file is treated as an ordinary
    single-government account -- see `_apply_gov_filter()`."""
    if not account_url:
        return False
    return _hub_key(account_url) in _known_hub_keys()


# --- WO-1054 rule 5 / WO-1058: shared-hub government filter, applied to
# every lister's own candidates right before `list_account()` returns
# them. See `pick.filter_candidates_to_government()`'s own docstring for
# the rule and the real College Township/Bellefonte (shared TelVue org
# token) and Nashwauk/Cohasset cases it exists for. A no-op when
# `gov_name` is empty (every existing caller that doesn't pass it) or when
# nothing was dropped, so this never changes behavior for a caller that
# hasn't opted in.
#
# WO-1058 additions: (1) the weak (non-place-type-word) half of the
# filter only runs on a confirmed shared hub (`is_known_shared_hub()`);
# (2) "keep at least one" (Ryan's rule) -- when every candidate would
# otherwise be dropped, the best rejected one is kept anyway, as a labelled
# lead for THIS government (never a bare empty result); (3) every dropped
# candidate, kept or not, is described and returned as `foreign_leads` --
# a real, free link-first lead for whichever OTHER government it names.
def _apply_gov_filter(
    result: ListResult, gov_name: Optional[str], account_url: str = ""
) -> ListResult:
    if not result.candidates or not gov_name:
        return result
    strict = is_known_shared_hub(account_url)
    kept, drop_note, foreign = filter_candidates_to_government(
        result.candidates, gov_name, strict=strict
    )
    foreign_leads = [
        {**describe_foreign_candidate(c), "hub_host": urlparse(account_url).netloc}
        for c in foreign
    ]
    if kept:
        if len(kept) == len(result.candidates):
            return result
        return ListResult(
            candidates=kept,
            lister=result.lister,
            outcome=result.outcome,
            note=result.note,
            params=result.params,
            foreign_leads=foreign_leads,
        )
    if not foreign:
        return result
    # Ryan's "keep at least one": don't hand back an empty result while a
    # real (just unconfirmed-government) video sits right there -- keep
    # the best rejected candidate, marked so `runner.py` never reports it
    # as a clean same-government find however cleanly it resolves.
    best = foreign[0]
    lead_note = (
        "possibly another government's meeting on a shared hub: "
        f"{best.title or best.url!r}"
    )
    kept_lead = dataclasses.replace(best, foreign_gov_hint=lead_note)
    return ListResult(
        candidates=[kept_lead],
        lister=result.lister,
        outcome=OUTCOME_HUB_OTHER_GOVERNMENT,
        note=drop_note or result.note,
        params=result.params,
        foreign_leads=foreign_leads,
    )


def _has_any_adapter(platform: str) -> bool:
    passive_verify._ensure_walkers_registered()
    if platform in passive_verify._LISTING_WALKERS:
        return True
    if platform in _DISCOVERY_ONLY_PLATFORMS:
        return True
    if platform in _CALENDAR_PAGE_ERROR_PLATFORMS or platform in _ADAPTER_HUB_PLATFORMS:
        return True
    # WO-1054: "cablecast_connect" (rule 3) and "wordpress" (rule 6) are
    # real, listable platforms this module has its own dedicated lister
    # for, but neither has -- or needs -- a registered `AssetFinder`
    # (`_list_via_cablecast_connect()` hands back a real, already-
    # resolvable `platform="cablecast"` candidate URL; `_list_via_
    # wordpress()` hands back whatever real platform the embedded video
    # itself is). An empty result from either is a real "nothing found"
    # (`OUTCOME_NO_MEETING_NOR_VIDEO`), not "no adapter registered".
    if platform in ("cablecast_connect", "wordpress"):
        return True
    try:
        get_finder(platform)
        return True
    except UnsupportedPlatformError:
        return False


async def list_account(
    platform: str,
    account_url: str,
    fetcher: Fetcher,
    *,
    limit: int = 15,
    platform_params: Optional[dict] = None,
    gov_name: Optional[str] = None,
    page_url: Optional[str] = None,
) -> ListResult:
    """Turn a known account (`platform` + `account_url`) into a list of
    candidate meetings, newest-first. See this module's docstring for the
    five listers, tried in order, and what each one reuses.

    Never resolves a candidate itself -- Resolve is the one place an
    adapter's `resolve()` runs to confirm video/captions (see the module
    docstring's "List only lists" note); the one exception is listers (c)
    and (d), which necessarily call `resolve()` because that is how their
    adapter tells "here's a pick-list" (`CalendarPageError`) or "here's
    the one meeting" apart from anything else -- neither actually
    confirms a specific CANDIDATE the way Resolve's own video-gate/
    duration-probe pass does.

    `gov_name` (WO-1041, optional): only used to pick among several real
    bodies sharing one Granicus account (see `_granicus_discover_view_id()`
    above) -- absent, this behaves exactly as before.

    `page_url` (WO-1046, optional): the real government page Identify
    found `account_url` embedded on (or linked from) -- forwarded to
    lister (c) for Vimeo only, where `account_url` is itself a video-host
    listing link, not a page worth pointing a reader at. Absent, this
    behaves exactly as before.
    """
    notes: List[str] = []

    if platform == "granicus" and not _GRANICUS_VIEW_ID_RE.search(account_url):
        discovered = await _granicus_discover_view_id(
            account_url, fetcher, gov_name=gov_name
        )
        if discovered is None:
            return ListResult(
                candidates=[],
                lister=None,
                outcome=OUTCOME_NO_MEETING_NOR_VIDEO,
                note=(
                    f"no populated Granicus ViewPublisher view_id found in "
                    f"1..{_GRANICUS_VIEW_ID_PROBE_MAX} on {urlparse(account_url).netloc}"
                ),
            )
        account_url = discovered

    a_minus_1 = await _list_via_cablecast_gallery(platform, account_url, fetcher, limit)
    if a_minus_1 is not None:
        if a_minus_1.candidates:
            return _apply_gov_filter(a_minus_1, gov_name, account_url)
        if a_minus_1.note:
            notes.append(a_minus_1.note)

    a0 = await _list_via_civicplus_light_check(platform, account_url, fetcher, limit)
    if a0 is not None and a0.candidates:
        return _apply_gov_filter(a0, gov_name, account_url)

    g = await _list_via_cablecast_connect(platform, account_url, fetcher, limit)
    if g is not None:
        if g.candidates:
            return _apply_gov_filter(g, gov_name, account_url)
        if g.note:
            notes.append(g.note)

    h = await _list_via_wordpress(platform, account_url, fetcher, limit)
    if h is not None:
        if h.candidates:
            return _apply_gov_filter(h, gov_name, account_url)
        if h.note:
            notes.append(h.note)

    a = await _list_via_passive_verify_walker(platform, account_url, fetcher, limit)
    if a is not None:
        if a.candidates:
            return _apply_gov_filter(a, gov_name, account_url)
        if a.note:
            notes.append(a.note)

    a2 = await _list_via_swagit_views_page(platform, account_url, fetcher, limit)
    if a2 is not None:
        if a2.candidates:
            return _apply_gov_filter(a2, gov_name, account_url)
        if a2.note:
            notes.append(a2.note)

    b = await _list_via_discovery(platform, account_url, limit, platform_params)
    if b is not None:
        if b.candidates:
            return _apply_gov_filter(b, gov_name, account_url)
        if b.note:
            notes.append(b.note)

    c = await _list_via_calendar_page_error(
        platform, account_url, limit, page_url=page_url
    )
    if c is not None:
        if c.candidates:
            return _apply_gov_filter(c, gov_name, account_url)
        if c.note:
            notes.append(c.note)

    d = await _list_via_adapter_hub(platform, account_url)
    if d is not None:
        if d.candidates:
            return _apply_gov_filter(d, gov_name, account_url)
        if d.note:
            notes.append(d.note)

    e = await _list_via_generic_scan(platform, account_url, fetcher, limit)
    if e is not None:
        if e.candidates:
            return _apply_gov_filter(e, gov_name, account_url)
        if e.note:
            notes.append(e.note)

    f = await _list_via_agenda_only_fallback(platform, account_url, fetcher, limit)
    if f is not None:
        if f.candidates:
            return _apply_gov_filter(f, gov_name, account_url)
        if f.note:
            notes.append(f.note)

    if not _has_any_adapter(platform):
        return ListResult(
            candidates=[],
            lister=None,
            outcome=OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER,
            note="; ".join(notes)
            if notes
            else f"no adapter registered for {platform!r}",
        )

    return ListResult(
        candidates=[],
        lister=None,
        outcome=OUTCOME_NO_MEETING_NOR_VIDEO,
        note="; ".join(notes) if notes else "every lister returned zero candidates",
    )
