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

**WO-1035 (Ryan's rule, 2026-09-23): date orders, it never eliminates.**
Calibration found real governments (Champaign IL, Glendora CA) where
every real candidate's own `date` field was unparseable (a Cablecast
tenant's Remix/Fastboot title carries the date as free text, e.g.
"... - 9/22/26", never a structured field) -- the old rule only ever
considered candidates with a parseable past date, so all of them were
silently dropped and the walk reported "ambiguous" while a real,
resolvable video sat one hand-check away. The rule now is:

    1. Dated in the past, newest first (governing body breaks a same-day
       tie) -- unchanged from before.
    2. Undated, in the order the lister handed them over (every walker in
       this repo lists newest-first, so "lister order" already approximates
       "newest first" for these).
    3. Dated in the future, soonest first -- still last resort; a future
       date is never a real past meeting, but Ryan's rule says never
       return nothing while a candidate exists.

Within each of those three buckets, a candidate whose title doesn't look
like a real meeting (`_looks_like_a_real_meeting_candidate()`) is
DEMOTED (tried after every candidate in the same bucket that does look
real) rather than dropped -- except a confirmed test/demo-tenant title
(`_is_test_or_demo_title()`), which is excluded outright, same as before
this change. If every candidate is a demoted (weak-title) one, they are
still returned rather than reporting "ambiguous" -- "ambiguous" is now
reserved for the one case nothing can be done about: zero real candidates
at all (an empty list, or every one a test/demo title).
"""

from __future__ import annotations

import re
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
    full timestamp still parses), and the human-readable shapes real
    listing pages use ("Sep 08, 2026", "September 08, 2026",
    "09/08/2026"). WO-1035 adds `%m/%d/%y` (a 2-digit year, e.g.
    "9/22/26") -- real Cablecast/Remix tenants (cablecast2 report,
    2026-09-23) put the meeting date in the DATE field this way, not just
    in the title."""
    if not date_str:
        return None
    date_str = date_str.strip()
    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(
                date_str[:10] if fmt == "%Y-%m-%d" else date_str, fmt
            )
        except ValueError:
            continue
    return None


# --- WO-1035 item 1: read a date out of the TITLE when the date field is
# empty. Real shape (cablecast2/cablecast4 reports, 2026-09-23): Cablecast/
# Remix listing rows carry a title like "City Council Meeting - 9/22/26" or
# "City Council Special Meeting September 21, 2026" or "07/07/2026", with
# the structured date field itself blank. Two shapes, tried in this order
# so a 4-digit year in prose ("September 21, 2026") isn't mis-split by the
# numeric pattern first.
_TITLE_MONTH_NAME_DATE_RE = re.compile(r"\b([A-Z][a-z]+\.?\s+\d{1,2},?\s+\d{4})\b")
_TITLE_NUMERIC_DATE_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\b")


def _date_from_title(title: Optional[str]) -> Optional[datetime]:
    if not title:
        return None
    m = _TITLE_MONTH_NAME_DATE_RE.search(title)
    if m:
        text = m.group(1).replace(",", "").replace(".", "")
        for fmt in ("%B %d %Y", "%b %d %Y"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    m = _TITLE_NUMERIC_DATE_RE.search(title)
    if m:
        month, day, year = m.groups()
        if len(year) == 2:
            year = f"20{year}"
        try:
            return datetime(int(year), int(month), int(day))
        except ValueError:
            return None
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
    `pick_candidates()`). See this module's own docstring for the rule
    itself -- this only exists so the rule is written once."""
    if not items:
        return [], "no candidates"

    # Test/demo-tenant titles are the ONE thing this module still drops
    # outright rather than demoting -- Ryan's "keep at least one" rule is
    # about a real candidate whose title merely looks weak, not about
    # manufacturing a pick out of a vendor's own test fixture row.
    real_items = [
        item for item in items if not _is_test_or_demo_title(get_title(item) or "")
    ]
    if not real_items:
        return [], "ambiguous: every candidate was a test/demo-tenant title"

    today = datetime.now(timezone.utc).replace(tzinfo=None)
    dated: List[Tuple[datetime, T]] = []
    undated: List[T] = []
    future: List[Tuple[datetime, T]] = []
    for item in real_items:
        dt = parse_candidate_date(get_date(item) or "") or _date_from_title(
            get_title(item) or ""
        )
        if dt is None:
            undated.append(item)
        elif dt <= today:
            dated.append((dt, item))
        else:
            future.append((dt, item))

    # Stable two-step sort within the dated bucket: governing-body rank
    # first (so a tie on date keeps the governing-body title ahead), then
    # date descending -- unchanged from before this WO.
    dated.sort(key=lambda pair: _governing_body_rank(get_title(pair[1])))
    dated.sort(key=lambda pair: pair[0], reverse=True)
    # Future-dated candidates are the last resort of the last resort --
    # soonest first, since a meeting closer to today is more likely to be
    # a real, currently-listed one than one far out.
    future.sort(key=lambda pair: pair[0])

    labeled: List[Tuple[T, str]] = (
        [(item, "recent dated") for _, item in dated]
        + [(item, "undated, lister order") for item in undated]
        + [(item, "future-dated") for _, item in future]
    )

    def _demoted(item: T) -> bool:
        return not _looks_like_a_real_meeting_candidate(get_title(item) or "")

    # Demote (not drop) a weak-looking title -- stable sort, so it only
    # ever moves a candidate to the back of ITS OWN bucket, never past a
    # real-looking candidate from a later (worse) bucket.
    labeled.sort(key=lambda pair: _demoted(pair[0]))

    picked = [item for item, _label in labeled]
    top_item, top_label = labeled[0]
    reason = ""
    if top_label != "recent dated" or _demoted(top_item):
        reason = f"picked by: {top_label}"
        if _demoted(top_item):
            reason += ", weak title kept (no clean candidate)"
    return picked[:limit], reason


def pick_calendar_candidates(
    candidates: List[dict], limit: int = MAX_CANDIDATES_TRIED
) -> Tuple[List[dict], str]:
    """Like `nationwide_2404_ingest.py`'s `pick_calendar_candidate()`, but
    returns an ORDERED LIST of up to `limit` candidates (most recent
    first, weak titles demoted rather than dropped -- see this module's
    own docstring) instead of a single pick -- the "go deep enough to
    find a meeting with video, not just the newest one" behavior Ryan
    asked for (see this module's own docstring for the WO-134 history).

    Never returns an empty list unless `candidates` itself has nothing
    left after excluding test/demo-tenant titles (WO-1035: "date orders,
    it never eliminates").

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


# --- WO-1054 rule 5 (Ryan, 2026-09-24): "on a shared hub pick only THIS
# government's meetings." One TelVue org token or Cablecast tenant root
# routinely serves several nearby governments off the same account (real
# examples Ryan hand-checked: College Township, PA and Bellefonte, PA
# share one Centre County C-NET TelVue token; Nashwauk, MN's own hub can
# carry a neighboring Cohasset, MN meeting the same way). Neither
# `_telvue_walker()` nor `_cablecast_walker()` (passive_verify.py, not
# owned by this WO) filters its listing by government at all -- every
# real video under the account comes back, oldest bookkeeping and all.
#
# This never GUESSES which government a candidate belongs to -- it only
# drops a candidate whose own title both (a) looks like a real meeting
# (carries one of `GOVERNING_BODY_KEYWORDS` -- "council", "commission",
# "board", "committee", "hearing") and (b) names no word in common with
# `gov_name`. A title with no governing-body word at all ("Budget
# Workshop", a bare date, "Regular Meeting") is never touched -- it's
# ambiguous, not evidence of a different government, and Ryan's own
# "keep at least one" posture (docs/MEETING_FINDER.md's Back-pressure
# section) says an ambiguous row must never be manufactured into an
# empty result. Only when EVERY real candidate clearly names some OTHER
# government does this report the true finding -- `models.
# OUTCOME_HUB_OTHER_GOVERNMENT` -- rather than the generic "nothing
# found" a caller would otherwise log.
_GOV_TYPE_WORDS = frozenset(
    {
        "city", "town", "township", "county", "borough", "village",
        "parish", "municipality", "municipal", "government", "district",
        "regional", "state", "public", "authority", "unified",
    }
)  # fmt: skip
_GOV_MATCH_TOKEN_RE = re.compile(r"[a-zA-Z]+")

# Real, confirmed collision (WO-1054, live 2026-09-24): College Township,
# PA and the Borough of State College, PA share one Centre County C-NET
# TelVue token, AND both real names contain the bare word "college" --
# comparing gov_name/title as a plain BAG of words (the first version of
# this rule) can't tell "College Township" apart from "State College",
# since "college" alone overlaps either way. `_place_core()` below
# compares the CONTIGUOUS place-name phrase instead (order-preserving,
# not just a shared word), which "state college" vs "college township"
# never accidentally satisfies.
_PLACE_PHRASE_PATTERNS = (
    # "Borough of State College", "City of Cohasset", "Township of X"
    re.compile(
        r"\b(?:city|town|township|borough|village|county)\s+of\s+"
        r"([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2})\b"
    ),
    # "College Township", "Cohasset City" (immediately before a type word)
    re.compile(
        r"\b([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2})\s+"
        r"(?:City|Town|Township|Borough|Village|County)\b"
    ),
    # "Cohasset City Council", "College Township Board" (immediately
    # before a governing-body word) -- GOVERNING_BODY_KEYWORDS itself is
    # lowercase-only, so this pattern matches case-insensitively on the
    # trailing word alone.
    re.compile(
        r"\b([A-Z][\w.'-]*(?:\s+[A-Za-z.'-]+){0,2})\s+"
        r"(?:Council|Commission|Board|Committee|Hearing)\b"
    ),
)


def _place_core(phrase: str) -> Optional[str]:
    """Lowercases `phrase` and drops a single TRAILING type word
    (`_GOV_TYPE_WORDS`) if the phrase ends with one -- "State College" ->
    "state college" (no type word to drop), "College Township" ->
    "college", "Cohasset City" -> "cohasset". Returns `None` when the
    phrase reduces to nothing (it WAS only a bare type word, e.g. a
    captured "City" with no real name attached -- not a real place-name
    candidate at all)."""
    words = phrase.strip().split()
    if not words:
        return None
    if len(words) > 1 and words[-1].lower() in _GOV_TYPE_WORDS:
        words = words[:-1]
    core = " ".join(w.lower() for w in words if w.lower() not in _GOV_TYPE_WORDS)
    return core or None


def _candidate_place_cores(title: str) -> List[str]:
    """Every place-name phrase `title` (kept in its ORIGINAL case, not
    lowercased -- capitalization is the signal these patterns key off of)
    seems to name, reduced via `_place_core()`. Real titles can match more
    than one pattern for the SAME place ("College Township Board..."
    matches both the type-word and governing-body patterns) -- all are
    checked, not just the first, so agreement across patterns doesn't
    matter and disagreement is still caught."""
    cores: List[str] = []
    for pattern in _PLACE_PHRASE_PATTERNS:
        for match in pattern.finditer(title):
            core = _place_core(match.group(1))
            if core:
                cores.append(core)
    return cores


def _names_a_governing_body(title: Optional[str]) -> bool:
    t = (title or "").lower()
    return any(contains_word(t, kw) for kw in GOVERNING_BODY_KEYWORDS)


def filter_candidates_to_government(
    candidates: List[Candidate], gov_name: Optional[str]
) -> Tuple[List[Candidate], Optional[str]]:
    """Drops a candidate whose title clearly names a DIFFERENT
    government's own place name -- see this module's own comment above
    for the real shared-hub cases this exists for. A candidate is only
    ever dropped when its title (a) looks like a real meeting (carries a
    `GOVERNING_BODY_KEYWORDS` word) AND (b) `_candidate_place_cores()`
    finds at least one real place-name phrase in it AND (c) NONE of those
    phrases match `gov_name`'s own core. A title with no governing-body
    word, or with one but no recognizable place-name phrase at all (a
    bare "City Council Meeting"), is never touched -- ambiguous, not
    evidence of a different government (Ryan's "keep at least one"
    posture: this must never manufacture emptiness out of an ordinary
    undated/untitled row).

    Returns `(kept_candidates, drop_note)`: `drop_note` is set only when
    EVERY candidate was dropped this way (the real "hub carries other
    governments" finding); a partial drop returns the survivors with no
    note, and an unfiltered/ambiguous list returns `candidates` itself
    unchanged, `None`. Never called with a `gov_name` this WO can't
    already trust: `runner.py` only ever passes the registry's own
    `Government.gov_name` for `finder_input.gov_id`, never a caller's
    unverified guess."""
    if not gov_name or not candidates:
        return candidates, None
    gov_core = _place_core(gov_name)
    if not gov_core:
        return candidates, None
    kept: List[Candidate] = []
    foreign: List[Candidate] = []
    for c in candidates:
        title = c.title or ""
        if not _names_a_governing_body(title):
            kept.append(c)
            continue
        cores = _candidate_place_cores(title)
        if not cores or gov_core in cores:
            kept.append(c)
        else:
            foreign.append(c)
    if kept:
        return kept, None
    sample = foreign[0].title or foreign[0].url
    return [], f"hub carries other governments, not this one (e.g. {sample!r})"
