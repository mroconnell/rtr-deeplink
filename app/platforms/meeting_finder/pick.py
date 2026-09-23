"""The one picking rule (docs/MEETING_FINDER.md's Resolve section: "a
real date, a meeting-like title, newest first").

Moved here from `scripts/wo134_confirmed_hits_ingest.py` (WO-1024), per
CLAUDE.md's "one picking rule" framing in the design doc -- that script
still imports `pick_calendar_candidates`/`parse_candidate_date` back
from here so there is exactly one copy, and its own tests (which
exercise `resolve_seed()`/`resolve_civicplus_seed()`, both of which call
into this module) are the regression check that moving it didn't change
behavior.

Pure functions, no network -- callers do the fetching and the resolving,
this module only orders and filters what they found.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, List, Optional, Sequence, Tuple, TypeVar

from app.platforms.granicus import GOVERNING_BODY_KEYWORDS
from app.utils.video_hand_check import contains_word, looks_like_real_meeting

from .models import Candidate

# How deep to search one tenant's listing for a video before giving up --
# same default `scripts/wo134_confirmed_hits_ingest.py` has used since
# WO-134 (its own `MAX_CANDIDATES_TRIED`, still re-exported below for
# that script's `import ... as wo134; wo134.MAX_CANDIDATES_TRIED` call
# sites and any other existing caller).
MAX_CANDIDATES_TRIED = 6

T = TypeVar("T")

# Real, confirmed titles from a vendor's own test/demo tenant, cited by
# the conductor from rtr-upcoming's UPCOMING_AGENDAS_FIELD_GUIDE.md
# (2026-09-23): Fremont's Granicus tenant carries rows literally titled
# "TEST - CC - Livemeeting demo", and Marin County's PrimeGov has a real
# agenda attached to a row titled "DO NOT USE - Cathy Test Meeting"
# (dated 2035 -- already excluded by the `dt <= today` filter below on
# its own, but the title marker is kept anyway since a demo tenant can
# just as easily backdate a row). Deliberately narrower than a bare
# "test" word: `looks_like_real_meeting()`'s own comment already
# preserves "Test City Council Meeting" (a real fixture title used
# across this repo's tests) as a legitimate meeting -- these two phrases
# only match the demo-tenant shape, never a real government's own name.
_TEST_DEMO_TITLE_MARKERS = ("do not use", "livemeeting demo", "test meeting")


def _is_test_or_demo_title(title: str) -> bool:
    t = (title or "").lower()
    return any(marker in t for marker in _TEST_DEMO_TITLE_MARKERS)


def _is_minutes_link(title: str) -> bool:
    """A link whose own text says "minutes" is a document link, not a
    meeting recording -- conductor feedback (2026-09-23), citing
    rtr-upcoming's field guide. Word-boundary, not substring (same
    `contains_word()` MEETING_ALLOWLIST/PROMO_BLOCKLIST already use), so
    a real title that merely mentions minutes in passing isn't the
    target -- the real shape this guards against is a bare "Minutes"
    link sitting in the same list as the meeting video row."""
    return contains_word((title or "").lower(), "minutes")


def _looks_like_a_real_meeting_candidate(title: str) -> bool:
    return (
        looks_like_real_meeting(title)
        and not _is_test_or_demo_title(title)
        and not _is_minutes_link(title)
    )


def _governing_body_rank(title: str) -> int:
    """0 when `title` names a governing body (council, commission, board,
    committee, hearing -- `app/platforms/granicus.py`'s own
    `GOVERNING_BODY_KEYWORDS`, reused rather than copied), 1 otherwise.
    Used only to break a tie between two candidates dated the SAME day --
    conductor feedback (2026-09-23, citing rtr-upcoming's field guide):
    volume/order alone can point at a lesser body's filtered view (the
    Tiburon "Heritage & Arts Only" case) over the real governing body's
    own meeting; a same-day tie is the one place this module can apply
    that preference without becoming List's own "rank several listing
    views" job (wave 2)."""
    t = (title or "").lower()
    return 0 if any(contains_word(t, kw) for kw in GOVERNING_BODY_KEYWORDS) else 1


def parse_candidate_date(date_str: Optional[str]) -> Optional[datetime]:
    """Parse a candidate's date field into a naive UTC `datetime`, or
    None when it isn't one of the shapes real candidates use.

    Same formats `wo134_confirmed_hits_ingest.py`'s `_parse_candidate_
    date()` always tried -- ISO (`2026-09-08`, first 10 chars only, so a
    full timestamp still parses), and the three human-readable shapes
    real listing pages use ("Sep 08, 2026", "September 08, 2026",
    "09/08/2026")."""
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


def _pick(
    items: Sequence[T],
    get_title: Callable[[T], str],
    get_date: Callable[[T], str],
    limit: int,
) -> Tuple[List[T], str]:
    """Generic version of the rule, parameterized over how to read a
    title/date off whatever shape `items` holds (a plain dict for
    `pick_calendar_candidates()`'s wo134 callers, a `Candidate` for
    `pick_candidates()`). See `pick_calendar_candidates()` for the rule
    itself -- this only exists so the rule is written once."""
    if not items:
        return [], "no candidates"

    today = datetime.now(timezone.utc).replace(tzinfo=None)
    dated: List[Tuple[datetime, T]] = []
    for item in items:
        dt = parse_candidate_date(get_date(item) or "")
        if dt is not None and dt <= today:
            dated.append((dt, item))
    # Stable two-step sort: governing-body rank first (so a tie on date
    # keeps the governing-body title ahead), then date descending. Python's
    # sort is stable, so the governing-body ordering only ever matters
    # when two candidates share the exact same date.
    dated.sort(key=lambda pair: _governing_body_rank(get_title(pair[1])))
    dated.sort(key=lambda pair: pair[0], reverse=True)

    picked = [
        item
        for _, item in dated
        if _looks_like_a_real_meeting_candidate(get_title(item) or "")
    ]
    if picked:
        return picked[:limit], ""

    # No dated candidate looked clean. A single real per-meeting agenda
    # row (unparseable date) still gets one try if its title is clean --
    # same carve-out the original single-pick version had.
    if len(items) == 1 and _looks_like_a_real_meeting_candidate(
        get_title(items[0]) or ""
    ):
        return [items[0]], ""

    # Real, pre-existing bug in the wo134 original this replaces (this
    # WO): `dated` holds `(datetime, item)` pairs, not bare items -- the
    # old one-liner called `.get("title")` straight on the pair, which
    # would have raised `AttributeError` the moment this branch actually
    # ran with a non-empty `dated` list. Never caught by a test before
    # now (see tests/test_wo1024_meeting_finder_pick.py's
    # test_declines_rather_than_guessing_when_nothing_looks_clean, which
    # exercises exactly this path).
    top_titles = [get_title(item) for _, item in dated[:5]] or [
        get_title(item) for item in list(items[:5])
    ]
    return [], f"ambiguous: no clean recent candidate among {top_titles!r}"


def pick_calendar_candidates(
    candidates: List[dict], limit: int = MAX_CANDIDATES_TRIED
) -> Tuple[List[dict], str]:
    """Like `nationwide_2404_ingest.py`'s `pick_calendar_candidate()`, but
    returns an ORDERED LIST of up to `limit` title-clean candidates (most
    recent first) instead of a single pick -- the "go deep enough to find
    a meeting with video, not just the newest one" behavior Ryan asked
    for (see this module's own docstring for the WO-134 history).

    Same "decline rather than guess" behavior when nothing recent looks
    like a real meeting: returns an empty list plus a reason, not a
    forced pick.

    Kept on plain `dict` candidates (not `Candidate`) because
    `scripts/wo134_confirmed_hits_ingest.py`'s callers carry extra keys
    on each candidate dict (`agenda_link`, `packet_link`, the original
    CivicClerk event) that a caller reads back off the picked item after
    this returns -- forcing those through the `Candidate` dataclass would
    either drop them or need a wider dataclass than Meeting Finder's own
    contract calls for. `pick_candidates()` below is the `Candidate`
    version for Meeting Finder's own Resolve phase.
    """
    return _pick(
        candidates,
        get_title=lambda c: c.get("title") or "",
        get_date=lambda c: c.get("date") or "",
        limit=limit,
    )


def pick_candidates(
    candidates: List[Candidate], limit: int = MAX_CANDIDATES_TRIED
) -> Tuple[List[Candidate], str]:
    """`pick_calendar_candidates()`'s rule, on Meeting Finder's own
    `Candidate` shape. Used by `resolve.py`."""
    return _pick(
        candidates,
        get_title=lambda c: c.title or "",
        get_date=lambda c: c.date or "",
        limit=limit,
    )
