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
from app.utils import gov_body_types
from app.utils.gov_registry import resolver as gov_resolver
from app.utils.jurisdiction_enrich import _STATE_NAME_TO_ABBR_LOWER
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
    # "Borough of State College", "City of Cohasset", "Township of X" --
    # WO-1058: `(?i:...)` scopes case-insensitivity to just this
    # alternation (a real title always capitalizes it, "Borough of...",
    # but the type word alone was never matched case-sensitively before --
    # this pattern silently never fired on any real title until now,
    # which is why disabling pattern 3 for a non-hub account (this WO)
    # would otherwise have also broken the real College Township/
    # Bellefonte and Nashwauk/Cohasset hub cases that depend on this one).
    re.compile(
        r"\b(?i:city|town|township|borough|village|county)\s+of\s+"
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
    "state college" (no type word to drop -- "State" isn't trailing, it's
    part of the real place name), "College Township" -> "college",
    "Cohasset City" -> "cohasset". Returns `None` when the phrase reduces
    to nothing but a bare type word (e.g. a captured "City" with no real
    name attached -- not a real place-name candidate at all).

    WO-1058: this ONLY ever drops a TRAILING type word, never one
    elsewhere in the phrase -- a prior version filtered out a type word
    from ANY position, which silently collapsed "State College" (a real
    PA borough) down to bare "college", the SAME core as "College
    Township" -- exactly the collision `test_filter_does_not_confuse_
    college_township_with_state_college()` exists to catch, and this
    docstring already promised "state college" stays two words. That bug
    was never exposed before this WO because `_PLACE_PHRASE_PATTERNS[0]`
    ("Borough of X") was itself case-sensitive-broken and never matched a
    real (capitalized) title -- fixing that match (this WO, so the
    now-default strong-pattern-only filter still catches "Borough of
    Bellefonte"/"Borough of State College") is what surfaced this one."""
    words = phrase.strip().split()
    if not words:
        return None
    if len(words) > 1 and words[-1].lower() in _GOV_TYPE_WORDS:
        words = words[:-1]
    core_words = [w.lower() for w in words]
    if all(w in _GOV_TYPE_WORDS for w in core_words):
        return None
    return " ".join(core_words)


# WO-1058 (bug found in calibration run D, 2026-09-25): the third pattern
# above ("Cohasset City Council", "College Township Board...") fires on
# ANY title-case phrase immediately before a governing-body word -- not
# just a real place name. A government's own ordinary committee names
# ("Zoning Board", "Public Safety Committee", "Personnel Committee") match
# it too, and none of those share a word with the government's own name,
# so on an account that lists many different committees -- which is most
# accounts, not just a shared hub -- this pattern alone was flagging every
# single candidate as "a different government" and rejecting all of them
# (21 of 68 real regressions: Oak Park IL, Clarington ON, Okotoks AB,
# Sanford ME, and 17 more, none of them an actual shared hub). Patterns 1
# and 2 (`_STRONG_PLACE_PHRASE_PATTERNS`) require an explicit place-type
# word ("City of X", "X Township") right in the phrase, which a bare
# committee name never has -- real shared-hub cases (College Township /
# Bellefonte PA, Nashwauk / Cohasset MN) are still caught by these alone,
# per this module's own tests. Pattern 3 is now used only when the caller
# already knows the account is a confirmed shared hub (`strict=True`,
# `listing.is_known_shared_hub()`) -- see `filter_candidates_to_government()`.
_STRONG_PLACE_PHRASE_PATTERNS = _PLACE_PHRASE_PATTERNS[:2]


def _candidate_place_cores(title: str, *, strict: bool = False) -> List[str]:
    """Every place-name phrase `title` (kept in its ORIGINAL case, not
    lowercased -- capitalization is the signal these patterns key off of)
    seems to name, reduced via `_place_core()`. Real titles can match more
    than one pattern for the SAME place ("College Township Board..."
    matches both the type-word and governing-body patterns) -- all are
    checked, not just the first, so agreement across patterns doesn't
    matter and disagreement is still caught.

    `strict` (WO-1058): only on a confirmed shared hub does the third,
    weaker pattern (any phrase before a governing-body word, no place-type
    word required) run -- see the module comment above `
    _STRONG_PLACE_PHRASE_PATTERNS` for why it's unsafe as a default."""
    patterns = _PLACE_PHRASE_PATTERNS if strict else _STRONG_PLACE_PHRASE_PATTERNS
    cores: List[str] = []
    for pattern in patterns:
        for match in pattern.finditer(title):
            core = _place_core(match.group(1))
            if core:
                cores.append(core)
    return cores


def _names_a_governing_body(title: Optional[str]) -> bool:
    t = (title or "").lower()
    return any(contains_word(t, kw) for kw in GOVERNING_BODY_KEYWORDS)


# --- WO-1060: `describe_foreign_candidate()`'s own extraction, fixed. ---
#
# Review of WO-1058's live output found the ORIGINAL version above
# (`_candidate_place_cores(title, strict=True)` -- the same weak "any
# capitalized phrase before a governing-body word" pattern WO-1058 itself
# had to gate behind `strict=True` for the DROP decision) produced almost
# entirely noise once used to describe a lead: of 9 "confident" leads, all
# 9 were Galesburg IL's own meetings ("Galesburg, IL City Council" ->
# "IL" extracted as if it were a different place, because "IL" happens to
# sit immediately before "City"); of 144 hand-read rows, the dominant
# named_places were bare meeting-descriptor words the weak pattern
# mistook for a place ("regular" x70, "recessed ..." x27, "special" x14,
# plus several bare dates) -- only ONE real lead ("The School Board of
# Nassau County, Florida" x6) was buried in that noise.
#
# The fix has three parts: (1) strip meeting/procedural noise words
# before extracting, so "Regular"/"Special"/"Recessed" can never be
# mistaken for a place sitting next to a real type word; (2) require an
# explicit place-TYPE word (City/Town/Township/Borough/Village/County/
# Parish/School District/ISD/USD) -- the same STRONG-pattern-only
# discipline WO-1058 already applied to the drop decision, now applied to
# the description too, so a bare committee/descriptor word is never
# recorded as a lead at all (no lead beats a wrong one); (3) never record
# a lead that's just the searched government's OWN name or state
# resurfacing (Galesburg's "IL").
_LEAD_NOISE_WORDS_RE = re.compile(
    r"\b(?:"
    r"agenda(?:\s+and\s+staff\s+reports)?(?:\s+for)?"
    r"|minutes?"
    r"|meetings?"
    r"|regular"
    r"|special"
    r"|recessed"
    r"|adjourned"
    r"|emergency"
    r"|called"
    r"|work\s+session"
    r"|session"
    r"|budget\s+hearing"
    r"|public\s+hearing"
    r"|cancellation\s+notice"
    r"|scheduled"
    r")\b",
    re.IGNORECASE,
)

_LEAD_DATE_TIME_RE = re.compile(
    r"\b\d{1,2}/\d{1,2}/\d{2,4}\b"
    r"|\b(?:jan|feb|mar|apr|may|jun|jul|aug|sept?|oct|nov|dec)[a-z]*\.?"
    r"\s+\d{1,2},?\s*(?:\d{4})?\b"
    r"|\b\d{1,2}:\d{2}\s*(?:[ap]\.?m\.?)?\b"
    r"|\b(?:19|20)\d{2}\b",
    re.IGNORECASE,
)


def _strip_lead_noise(text: str) -> str:
    """Meeting/procedural noise words and dates/times stripped out --
    never a place-TYPE word (City/County/...), same non-destructive
    posture as `hub_harvest._extract_place_fragment()`'s own trailing-
    descriptor strip, just aimed at a candidate TITLE's shape (leading
    "Regular"/"Special", embedded dates) rather than a hub SECTION
    name's shape (trailing "Board Meetings").

    Only WHITESPACE runs are collapsed -- a comma or dash is deliberately
    left alone, real regression (WO-1060 build): collapsing "Galesburg,
    IL City Council" -> "Galesburg IL City Council" joined the city's own
    name and its own state abbreviation into one contiguous two-word
    phrase, which then matched as if "Galesburg IL" (not just "IL") were
    a different place. A comma/dash between two capitalized words is
    exactly the signal that they are NOT one contiguous place-name
    phrase, and `_LEAD_PLACE_PHRASE_PATTERNS`'s own `[\\w.'-]` word class
    already can't cross one -- removing it a second time here only
    reintroduced the bug the character class was already preventing."""
    working = _LEAD_NOISE_WORDS_RE.sub(" ", text or "")
    working = _LEAD_DATE_TIME_RE.sub(" ", working)
    return re.sub(r"[ \t]+", " ", working).strip()


# Place-TYPE words a real other-government lead's title must carry --
# wider than `_GOV_TYPE_WORDS` above (School District/ISD/USD/Parish
# added, WO-1060) since a school-district or parish government is just as
# real a "different government" as a city/county one. Deliberately
# excludes the bare governing-body words (Council/Commission/Board/...)
# `_PLACE_PHRASE_PATTERNS`'s third pattern uses -- that pattern is what
# actually caused the "regular"/"special"/date noise, since it treats ANY
# capitalized word before "Council" as a place with no type word to
# anchor it.
# Each entry: (pattern, "type_first" | "name_first") -- which capture
# group holds the place-type word vs. the place name itself, so
# `_extract_lead_place()` never has to guess it from casing (a real title
# can capitalize either "City of Cohasset" or, mid-sentence, "city of
# Cohasset").
_LEAD_PLACE_PHRASE_PATTERNS = (
    (
        re.compile(
            r"\b(?i:(city|town|township|borough|village|county|parish))\s+of\s+"
            r"([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2})\b"
        ),
        "type_first",
    ),
    (
        re.compile(
            r"\b([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2})\s+"
            r"(?:(City|Town|Township|Borough|Village|County|Parish|"
            r"School\s+District|ISD|USD))\b"
        ),
        "name_first",
    ),
)


def _extract_lead_place(title: str) -> Optional[Tuple[str, str]]:
    """`(place_core, type_word)` for the real place-name phrase inside
    `title`, requiring an explicit place-type word -- or `None` when
    nothing place-shaped, with a real type word attached, is left once
    meeting/procedural noise is stripped. See the module comment above
    for why this is narrower than `_candidate_place_cores()`'s own weak
    pattern. `type_word` (lowercased, WO-1060) is the place-type word the
    phrase was actually found next to ("county", "school district"...) --
    kept separately since `_place_core()` itself drops it from the name,
    but a caller matching against the registry (a school district in
    particular) needs to know it was there."""
    working = _strip_lead_noise(title or "")
    for pattern, order in _LEAD_PLACE_PHRASE_PATTERNS:
        for match in pattern.finditer(working):
            type_word, name = (
                match.groups() if order == "type_first" else reversed(match.groups())
            )
            core = _place_core(name)
            if core:
                return core, re.sub(r"\s+", " ", type_word.strip().lower())
    return None


# Longest-name-first so "West Virginia" is tried before "Virginia" would
# otherwise steal a partial match -- not load-bearing for any state pair
# today, but cheap insurance against a future one.
_STATE_FULL_NAME_RE = re.compile(
    r"\b("
    + "|".join(sorted(_STATE_NAME_TO_ABBR_LOWER, key=len, reverse=True))
    + r")\b",
    re.IGNORECASE,
)


def _state_from_title_text(text: str) -> str:
    """A state/province abbreviation named in `text`, either the
    ", ST"-shaped suffix `gov_resolver.state_suffix_from_text()` already
    recognizes anywhere in a real page title, or a full state name
    written out in prose (WO-1060: real shape, "The School Board of
    Nassau County, Florida" carries no abbreviation at all). The
    RIGHTMOST match wins when more than one appears, since a real title's
    own state is usually the trailing one ("..., Florida")."""
    if not text:
        return ""
    code = gov_resolver.state_suffix_from_text(text)
    if code:
        return code
    last = None
    for m in _STATE_FULL_NAME_RE.finditer(text):
        last = m
    if last:
        return _STATE_NAME_TO_ABBR_LOWER[last.group(1).lower()].upper()
    return ""


# The registry's own `Government.gov_name` carries a census-style
# descriptor and state suffix a plain title never does -- "Galesburg
# (city), IL", "Yarmouth (town), MA" -- neither of which `_place_core()`
# (built for TITLE text) knows how to strip. Stripped here, once, before
# comparing against a title-extracted core.
_GOV_NAME_PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)")
_GOV_NAME_TRAILING_STATE_RE = re.compile(r",\s*[A-Za-z]{2}\.?\s*$")


def _own_government_core(gov_name: str) -> Optional[str]:
    cleaned = _GOV_NAME_TRAILING_STATE_RE.sub("", gov_name)
    cleaned = _GOV_NAME_PARENTHETICAL_RE.sub("", cleaned)
    return _place_core(cleaned)


def _is_own_government_place(
    place_core: str, gov_name: Optional[str], gov_state: Optional[str]
) -> bool:
    """True only when `place_core` is clearly just the SEARCHED
    government's own identity resurfacing -- its own name, or its own
    state's name/code (Galesburg, IL's own "... Galesburg, IL City
    Council..." extracts "il", which is Galesburg's own state, not a
    different place). Deliberately an EXACT match only, never a prefix/
    substring one: a real, separate government can share a name PREFIX
    with the searched one (a real county's own government vs. a school
    district of the same county, e.g. Nassau County, FL vs. Nassau County
    School District, FL) without being the same government -- WO-1060's
    own brief tried a substring rule first and explicitly retracted it
    for exactly this reason."""
    if not place_core:
        return False
    if gov_state:
        state_lower = gov_state.strip().lower()
        if place_core == state_lower:
            return True
        if _STATE_NAME_TO_ABBR_LOWER.get(place_core) == state_lower:
            return True
    if gov_name:
        gov_core = _own_government_core(gov_name)
        if gov_core and place_core == gov_core:
            return True
    return False


# --- Ryan's WO-1060 review (2026-09-25): "School Board of X County" is
# X County's own SCHOOL DISTRICT, not the county government. ---
#
# Real regression this fixes: Nassau County School District, FL's OWN
# meetings ("The School Board of Nassau County, Florida") were rejected
# by `filter_candidates_to_government()` as a DIFFERENT government --
# `_place_core("Nassau County School District, FL")` reduces to "nassau
# county school" (only ONE trailing type word, "district", gets dropped),
# while the title's own extracted core is bare "nassau" -- a granularity
# mismatch, not a real different place. The lead step then "confidently"
# matched the rejected candidate back to `us:sd:1201350` -- the SAME
# government being searched. Two things follow: (1) when the SEARCHED
# government IS that county's school district, this shape is its own
# meeting and must never be rejected; (2) when the searched government is
# the plain COUNTY (or anything else), this shape names a REAL, DIFFERENT
# government (the school district) and must always be treated as foreign,
# regardless of whether the county name happens to match the county being
# searched -- a county government and its own school district are two
# different governments even though they share a name.
_SCHOOL_RELATED_GOV_WORDS = (
    "school district",
    "public schools",
    "school system",
    "board of education",
)


def _gov_name_is_school_related(gov_name: Optional[str]) -> bool:
    lowered = (gov_name or "").lower()
    return any(w in lowered for w in _SCHOOL_RELATED_GOV_WORDS)


# Iteratively strips school/county descriptor words from the END of a
# gov_name (after its state suffix/parenthetical are already gone) until
# nothing more matches -- "Nassau County School District" -> "Nassau
# County" -> "Nassau", vs. `_place_core()`'s own single-strip, which only
# gets to "Nassau County School" (see the module comment above).
_COUNTY_HOME_SUFFIX_RE = re.compile(
    r"[\s\-,]*\b(?:school district|public schools|school system|"
    r"board of education|schools|county)\s*$",
    re.IGNORECASE,
)


def _county_home_core(gov_name: str) -> str:
    working = _GOV_NAME_TRAILING_STATE_RE.sub("", gov_name or "")
    working = _GOV_NAME_PARENTHETICAL_RE.sub("", working)
    while True:
        stripped = _COUNTY_HOME_SUFFIX_RE.sub("", working).strip(" ,-")
        if stripped == working:
            break
        working = stripped
    return working.strip().lower()


# The 4 real shapes Ryan named: "School Board of X County[, State]", "X
# County School Board", "X County Board of Education", "X County
# Schools" -- all name X County's school district, never the county
# government itself, regardless of which government's own walk happens
# to be running.
_COUNTY_SCHOOL_BODY_PREFIX_RE = re.compile(
    r"\b(?i:school board of)\s+([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2})"
    r"\s+(?i:county)\b"
)
_COUNTY_SCHOOL_BODY_SUFFIX_RE = re.compile(
    r"\b([A-Z][\w.'-]*(?:\s+[A-Z][\w.'-]*){0,2})\s+(?i:county)\s+"
    r"(?i:school board|board of education|schools)\b"
)


def _extract_county_school_body(title: str) -> Optional[Tuple[str, str]]:
    """`(county_core, title_state)` when `title` names one of the 4 real
    "X County's school district" shapes -- or `None` otherwise. Runs on
    the RAW title (not noise-stripped): these shapes are themselves the
    real meeting title, not noise sitting around one."""
    for pattern in (_COUNTY_SCHOOL_BODY_PREFIX_RE, _COUNTY_SCHOOL_BODY_SUFFIX_RE):
        match = pattern.search(title or "")
        if match:
            core = _place_core(match.group(1))
            if core:
                return core, _state_from_title_text(title)
    return None


def _is_own_county_school_body(
    county_core: str,
    title_state: str,
    gov_name: Optional[str],
    gov_state: Optional[str],
) -> bool:
    """True only when the SEARCHED government (`gov_name`) is itself
    `county_core`'s own school district -- never true for a plain
    city/county/town search, even one named `county_core`, since a
    county government and its own school district are different real
    governments (Ryan's review, 2026-09-25)."""
    if not _gov_name_is_school_related(gov_name):
        return False
    home_core = _county_home_core(gov_name or "")
    if not home_core or home_core != county_core:
        return False
    if title_state and gov_state and title_state.upper() != gov_state.upper():
        # Real, different Nassau County -- e.g. FL vs. NY.
        return False
    return True


def describe_foreign_candidate(
    candidate: Candidate,
    *,
    gov_name: Optional[str] = None,
    gov_state: Optional[str] = None,
    gov_type: Optional[str] = None,
) -> Optional[dict]:
    """WO-1058 rule (Ryan, 2026-09-25): every candidate this filter drops
    for naming a different place is a real, free link-first lead for THAT
    other government -- worth keeping, not just discarding. WO-1060
    narrowed WHICH dropped candidates actually earn a recorded lead (see
    the module comment above `_LEAD_NOISE_WORDS_RE`): `None` when the
    title names no real place at all, or only the searched government's
    own name/state (`gov_name`/`gov_state`, both optional -- a caller
    that doesn't know them just never excludes on that basis). Shape
    matches what `scripts/hub_harvest.py`'s own matcher already expects a
    hub section to carry (name/state/body-type matching input), plus a
    `state` field (WO-1060) carrying the title's OWN state when the title
    names one, so a caller never has to guess it from region/hub context
    alone.

    Ryan's review (2026-09-25) added one more exclusion, checked FIRST
    and instead of the generic name/state check below: a "School Board
    of X County"-shaped title (`_extract_county_school_body()`) names X
    County's own SCHOOL DISTRICT, a real, different government from the
    plain COUNTY of the same name -- so a plain name/state match against
    `gov_name` is the WRONG test here (Nassau County, FL's own name
    equals this title's extracted place exactly, yet the video is really
    a lead to Nassau County's DIFFERENT school district, not the
    county's own meeting) -- see `_is_own_county_school_body()`'s own
    docstring.

    WO-1078 (`gov_type`, optional) added a THIRD, independent check, tried
    before the place-name checks above: `gov_body_types.
    body_type_disagreement()` catches a candidate that names the SAME
    place but a DIFFERENT kind of governing body -- a school district
    search finding "Common Council - 6/9/2026" (Cumberland, WI's city
    council, real example) names no place at all, so the place-based
    checks above would return `None` for it with no `gov_type`; with
    `gov_type` this instead returns a body-type-flavored lead. See that
    function's own docstring for why this is conservative by design."""
    title = candidate.title or ""
    body_type_hit = gov_body_types.body_type_disagreement(title, gov_type)
    if body_type_hit is not None:
        phrase, expected_types, owner_hint = body_type_hit
        extracted = _extract_lead_place(title)
        place_core, place_type = extracted if extracted else ("", "")
        body_words = [
            kw for kw in GOVERNING_BODY_KEYWORDS if contains_word(title.lower(), kw)
        ]
        return {
            "named_place": place_core,
            "place_type": place_type,
            "body_words": body_words,
            "title": candidate.title,
            "date": candidate.date,
            "url": candidate.url,
            "state": _state_from_title_text(title),
            "reason": "body_type_mismatch",
            "body_phrase": phrase,
            "other_gov_types": sorted(expected_types),
            "owner_hint": owner_hint,
        }
    extracted = _extract_lead_place(title)
    if extracted is None:
        return None
    place_core, place_type = extracted
    county_school = _extract_county_school_body(title)
    if county_school is not None:
        school_county_core, school_title_state = county_school
        if _is_own_county_school_body(
            school_county_core, school_title_state, gov_name, gov_state
        ):
            return None
    elif _is_own_government_place(place_core, gov_name, gov_state):
        return None
    body_words = [
        kw for kw in GOVERNING_BODY_KEYWORDS if contains_word(title.lower(), kw)
    ]
    return {
        "named_place": place_core,
        "place_type": place_type,
        "body_words": body_words,
        "title": candidate.title,
        "date": candidate.date,
        "url": candidate.url,
        "state": _state_from_title_text(title),
    }


def filter_candidates_to_government(
    candidates: List[Candidate],
    gov_name: Optional[str],
    *,
    strict: bool = False,
    gov_state: Optional[str] = None,
    gov_type: Optional[str] = None,
) -> Tuple[List[Candidate], Optional[str], List[Candidate]]:
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

    `strict` (WO-1058): passed straight to `_candidate_place_cores()` --
    only True on a confirmed shared hub (`listing.is_known_shared_hub()`).
    False (the default -- an ordinary, single-government account) still
    drops a candidate that STRONGLY names a different place ("Borough of
    Bellefonte", "Cohasset City Council") -- it just never treats a bare
    committee/board name ("Zoning Board", "Public Safety Committee") as
    evidence of anywhere at all, which is the real bug this WO fixes (see
    the module comment above `_STRONG_PLACE_PHRASE_PATTERNS`).

    Returns `(kept_candidates, drop_note, foreign_candidates)`:
    `drop_note` is set only when EVERY candidate was dropped this way (the
    real "hub carries other governments" finding); a partial drop returns
    the survivors with no note, and an unfiltered/ambiguous list returns
    `candidates` itself unchanged, `None`, `[]`. `foreign_candidates` is
    every dropped candidate, always (partial or total drop) -- WO-1058:
    each one is a real, free lead for whichever OTHER government it
    names, kept by the caller (`listing._apply_gov_filter()`) as
    `ListResult.foreign_leads` regardless of what happens to `kept`.
    Never called with a `gov_name` this WO can't already trust: `runner.py`
    only ever passes the registry's own `Government.gov_name` for
    `finder_input.gov_id`, never a caller's unverified guess.

    `gov_state` (WO-1060, optional): checked ONLY for the "School Board
    of X County" family of shapes (see the module comment above
    `_SCHOOL_RELATED_GOV_WORDS`) -- a title in that shape is the searched
    government's OWN meeting when the searched government IS that
    county's school district (never a plain city/county/town, even one
    named the same county), and is otherwise ALWAYS foreign regardless of
    the normal place-core comparison below, since a county government and
    its own school district are different real governments even when
    they share a name.

    `gov_type` (WO-1078, optional): a THIRD, independent check, tried
    before the place-name checks below -- see `gov_body_types.
    body_type_disagreement()`. A candidate whose title names a governing
    body clearly of a DIFFERENT type (a school district search finding a
    "Town Council" video) is dropped regardless of place-name agreement --
    same place, wrong kind of government, still not this government's own
    meeting. Conversely, a candidate whose body-type phrase AGREES with
    `gov_type` is kept immediately, without running the place-name checks
    at all -- real case (Ryan, 2026-09-26): lincnet.org's own "School
    Committee 09.10.26" video, on the TOWN's shared Castus channel, names
    no place at all and would otherwise fall through the place-name logic
    untouched anyway, but an explicit keep here means a future, stricter
    place-name rule can never accidentally start rejecting it."""
    if not gov_name or not candidates:
        return candidates, None, []
    gov_core = _place_core(gov_name)
    if not gov_core:
        return candidates, None, []
    kept: List[Candidate] = []
    foreign: List[Candidate] = []
    for c in candidates:
        title = c.title or ""
        # WO-1078: checked BEFORE the generic `_names_a_governing_body()`
        # gate below (unlike the place-name checks that follow) --
        # `VIDEO_TITLE_BODY_PHRASES` is itself a specific, real-body-name
        # phrase list (not a bare keyword), so it doesn't need that
        # generic pre-filter for safety, and gating it there would miss
        # real cases the pre-filter's narrower keyword list
        # (`GOVERNING_BODY_KEYWORDS` = council/commission/board/committee/
        # hearing) doesn't cover: "County Commissioners" (no bare
        # "commission"/"board" word), "Redevelopment and Housing
        # Authority" (no "board"/"commission"/... word at all), and a
        # one-word "Selectboard" title (no separate "board" word) --
        # three real rows in `other_gov_rows.csv` (qacps.org,
        # harrisonburg.k12.va.us, wwsu.org/arrsd.org) confirmed this live.
        if gov_type:
            body_match = gov_body_types.match_body_type_phrase(title)
            if body_match is not None:
                _phrase, expected_types, _hint = body_match
                if gov_type in expected_types:
                    kept.append(c)
                else:
                    foreign.append(c)
                continue
        if not _names_a_governing_body(title):
            kept.append(c)
            continue
        county_school = _extract_county_school_body(title)
        if county_school is not None:
            county_core, title_state = county_school
            if _is_own_county_school_body(
                county_core, title_state, gov_name, gov_state
            ):
                kept.append(c)
            else:
                foreign.append(c)
            continue
        cores = _candidate_place_cores(title, strict=strict)
        if not cores or gov_core in cores:
            kept.append(c)
        else:
            foreign.append(c)
    if kept:
        return kept, None, foreign
    if not foreign:
        return candidates, None, []
    sample = foreign[0].title or foreign[0].url
    return [], f"hub carries other governments, not this one (e.g. {sample!r})", foreign
