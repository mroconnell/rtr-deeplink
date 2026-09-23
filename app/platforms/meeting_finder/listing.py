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

import importlib
import importlib.util
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable, List, Optional
from urllib.parse import urlparse

from app.platforms import passive_verify
from app.platforms.base import (
    CalendarPageError,
    UnsupportedPlatformError,
    YouTubeResolveBlocked,
    get_finder,
)

from .fetch import BudgetExceeded, Fetcher
from .models import Candidate

# --- Outcomes -------------------------------------------------------
# Same spellings as models.py's OUTCOME_* constants (docs/MEETING_FINDER.md
# section 23) -- not re-exported from there because models.py is one of
# the files this WO must not edit, and importing OUTCOME_NO_MEETING_NOR_VIDEO/
# OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER from `.models` (read-only import,
# no edit) is exactly as good as defining a third spelling here.
from .models import (  # noqa: E402
    OUTCOME_NO_MEETING_NOR_VIDEO,
    OUTCOME_UNSUPPORTED_PLATFORM_NO_ADAPTER,
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


def _candidate_from_dict(
    row: dict, *, platform: str, account_url: str, lister: str
) -> Optional[Candidate]:
    url = row.get("url") if isinstance(row, dict) else None
    if not url:
        return None
    return Candidate(
        url=url,
        title=(row.get("title") or None) if isinstance(row, dict) else None,
        date=row.get("date") if isinstance(row, dict) else None,
        platform=platform,
        source_phase="list",
        lister=lister,
        source_url=account_url,
        has_video_hint=row.get("has_video_hint") if isinstance(row, dict) else None,
    )


def _candidates_from_dicts(
    rows: List[dict], *, platform: str, account_url: str, lister: str
) -> List[Candidate]:
    out: List[Candidate] = []
    for row in rows:
        candidate = _candidate_from_dict(
            row, platform=platform, account_url=account_url, lister=lister
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
    platform: str, account_url: str, limit: int
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
            rows, platform=platform, account_url=account_url, lister="adapter_list"
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


def _has_any_adapter(platform: str) -> bool:
    passive_verify._ensure_walkers_registered()
    if platform in passive_verify._LISTING_WALKERS:
        return True
    if platform in _DISCOVERY_ONLY_PLATFORMS:
        return True
    if platform in _CALENDAR_PAGE_ERROR_PLATFORMS or platform in _ADAPTER_HUB_PLATFORMS:
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
    """
    notes: List[str] = []

    a = await _list_via_passive_verify_walker(platform, account_url, fetcher, limit)
    if a is not None:
        if a.candidates:
            return a
        if a.note:
            notes.append(a.note)

    b = await _list_via_discovery(platform, account_url, limit, platform_params)
    if b is not None:
        if b.candidates:
            return b
        if b.note:
            notes.append(b.note)

    c = await _list_via_calendar_page_error(platform, account_url, limit)
    if c is not None:
        if c.candidates:
            return c
        if c.note:
            notes.append(c.note)

    d = await _list_via_adapter_hub(platform, account_url)
    if d is not None:
        if d.candidates:
            return d
        if d.note:
            notes.append(d.note)

    e = await _list_via_generic_scan(platform, account_url, fetcher, limit)
    if e is not None:
        if e.candidates:
            return e
        if e.note:
            notes.append(e.note)

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
