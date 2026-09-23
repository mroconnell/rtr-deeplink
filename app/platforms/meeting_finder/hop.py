"""Meeting Finder's Hop phase (WO-1029).

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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional
from urllib.parse import urljoin, urlparse

from app.platforms.base import detect_platform

from scripts.wo147_access_ladder_sweep import (  # noqa: E402
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


def rank_hops(
    page: FetchResult,
    *,
    prefer_vendor: Optional[str] = None,
    school: bool = False,
    french: bool = False,
    limit: int = 8,
) -> List[HopLink]:
    """Ranks `page`'s own links as candidate next hops, best first. See
    this module's docstring for `prefer_vendor`/`school`/`french`.
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
        score = _score_hop_candidate_weighted(
            text, href, full, base_netloc, a, gov_id=gov_id, html_text=html
        )
        if score is None:
            continue
        if prefer_vendor and detect_platform(full) == prefer_vendor:
            score += _PREFER_VENDOR_BONUS
        seen.add(full)
        scored.append((score, doc_order, full, text))
        doc_order += 1

    scored.sort(key=lambda t: (-t[0], t[1]))

    out: List[HopLink] = []
    for score, _order, url, anchor in scored[:limit]:
        platform = detect_platform(url)
        if prefer_vendor and platform == prefer_vendor:
            reason = f"preferred vendor ({prefer_vendor}) host match"
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
    # Re-exported for convenience/tests -- these are the underlying
    # wo147 functions this module wraps.
    "find_hop_links",
    "looks_french",
]
