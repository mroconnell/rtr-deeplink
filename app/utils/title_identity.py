"""Deterministic title -> (is it a meeting, which body, which government).

Why this exists (2026-09-30): the most frequent decision in enumeration
is "which government and which public body does this title / playlist /
gallery / channel belong to, and is it a meeting at all". A hand-read of
400+ census proposals rejected 50, and every reject broke a simple rule.
This module writes those rules down so a script settles most cases and
only a small, counted remainder needs a model.

It reads NO network and writes nothing. It reuses, and does not replace:

- `app.utils.gov_body_types` (body phrase -> government type table;
  `match_body_type_phrase`), used to pick the government kind;
- `app.utils.video_hand_check` (`MEETING_ALLOWLIST`, `PROMO_BLOCKLIST`,
  `NON_MEETING_SIGNS`), whose words are folded into the lexicons below so
  the gate and this module agree;
- `app.utils.gov_registry` tables and `governments.csv` for place names
  and for existing special-district ids.

Rules, each from a real 2026-09-30 reject:

1. A body word (council, board, commission, selectboard, school
   committee, trustees, authority, ...) makes a title a meeting
   candidate.
2. Non-meeting words (tour, caucus, sheriff town hall, forum, debate,
   "presents", "corner", "rewind", sports, church, parent meetings, the
   access station's own annual meeting, ...) make it `meeting=False`.
3. A place name that is also a common English word (Agenda, Council,
   Center, Union, Economy, ...) never matches on its own. It needs a
   type cue ("City of X", "X Village", "Town of X") or a match in
   `known_gov_ids`.
4. A school body maps only to a school district (`us:sd:`), never to a
   town or county. A "county board of education" is a county office, not
   the local unified district.
5. A channel whose name names a different place (another state, or a
   Canadian province) cannot map the title to a different government.
6. Legislature / state agency / court titles map to the state or to no
   one, never to a city or county.
7. Special-district words (housing authority, water district, ...):
   the body is the district. If `governments.csv` already has that
   district, use its id. Otherwise file under the same-named local
   government with the district as the meeting body (Ryan's rule).

A blank is a finding: `meeting=None`, `gov_id=None`, or
`confidence='low'` means "a model or a person must read this". The
function never guesses to fill a gap.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

from app.utils import gov_body_types
from app.utils.gov_registry import classify, registry, tables
from app.utils.video_hand_check import contains_word

# A title with no body word, no meeting word and no non-meeting word. The
# verdict stays `meeting=None` (a blank is a finding), but the reason is
# tagged so a caller can count these and, if it chooses, treat them as
# "not a meeting" at a measured error rate (see docs in the eval report).
NO_EVIDENCE_REASON = "no_body_or_meeting_word"

HIGH = "high"
MEDIUM = "medium"
LOW = "low"

# gov_kind values returned.
KIND_PLACE = "place"
KIND_COUSUB = "cousub"
KIND_COUNTY = "county"
KIND_SCHOOL = "sd"
KIND_STATE = "state"
KIND_SPECIAL = "special"  # a registry special-district id (rtr:/cog)


@dataclass(frozen=True)
class TitleVerdict:
    """One title's verdict. `None` means "not settled by the rules".

    `confidence` is the weakest of the two parts. `meeting_confidence` is
    sure-ness that the meeting yes/no is right; `identity_confidence` is
    sure-ness of `gov_id` (low when `gov_id` is None)."""

    meeting: Optional[bool]
    body: Optional[str]
    gov_id: Optional[str]
    gov_kind: Optional[str]
    confidence: str
    reasons: List[str] = field(default_factory=list)
    meeting_confidence: str = LOW
    identity_confidence: str = LOW


# ---------------------------------------------------------------------
# Lexicons
# ---------------------------------------------------------------------

# Strong body phrases: the title names a governing body.
_BODY_PATTERNS = [
    r"city council",
    r"town council",
    r"county council",
    r"common council",
    r"village council",
    r"borough council",
    r"township council",
    r"city commission",
    r"council",
    r"board of (?:county )?(?:commissioners|supervisors|trustees|directors|education"
    r"|selectmen|selectpersons?|aldermen|adjustment|appeals|zoning appeals|health"
    r"|assessors|governors|regents|review|fire commissioners|library trustees|ethics)",
    r"(?:county |city |town |village )?board of (?:zoning )?adjustments?",
    r"select ?board",
    r"selectmen",
    r"selectpersons?",
    r"school (?:board|committee)",
    r"board of ed(?:ucation)?",
    r"(?:school|education) board",
    r"trustees",
    r"supervisors",
    r"commissioners?['\u2019]?s? court",
    r"commissioners",
    r"sub-?committees?",
    r"committees",
    r"commission",
    r"planning (?:board|and zoning|& zoning|commission)",
    r"zoning",
    r"committee",
    r"authority",
    r"town meeting",
    r"village board",
    r"town board",
    r"city board",
    r"board of [a-z]+",
    r"task force",
    r"p ?(?:&|and) ?z",
    r"board",
    r"bocc",
    r"bos",
    r"boe",
    r"assembly",
    r"legislature",
    r"senate",
    r"house of representatives",
]
_BODY_RE = re.compile(r"\b(?:" + "|".join(_BODY_PATTERNS) + r")\b", re.IGNORECASE)
# Words that, alone, are only a weak body signal.
_WEAK_BODY_WORDS = frozenset({"board", "committee", "commission", "authority"})

# A title that says it is a meeting event but names no body.
_MEETING_WORD_RE = re.compile(
    r"\b(?:meeting|meetings|hearing|hearings|session|sessions|work ?session|agenda"
    r"|on \d{4}-\d{2}-\d{2})\b",
    re.IGNORECASE,
)

# Hard non-meeting words: these beat any body word in the same title.
_HARD_NON_MEETING = [
    (r"\btours?\b", "tour"),
    (r"\btourism\b", "tourism"),
    (r"\b(?:democrat(?:s|ic)?|republicans?|gop)\b", "party"),
    (r"\bcandidates?\b", "candidate"),
    (r"\bdebates?\b", "debate"),
    (r"\bsheriffs?\b", "sheriff"),
    (r"\bpresents\b", "presents (a show)"),
    (r"\b[a-z]+['\u2019]s? corner\b|\bthe corner\b", "corner (a show)"),
    (r"\bdebrief\b", "debrief (a recap show)"),
    (r"\brewind\b", "rewind"),
    (r"\bthis week in\b", "this week in"),
    (r"\bon the agenda\b", "on the agenda (a show)"),
    (r"\b[a-z]+['’]s workshop\b", "possessive workshop (a show)"),
    (r"\bparent(?:s)? meetings?\b", "parent meetings"),
    (r"\bneighborhood meetings?\b", "neighborhood meetings"),
    (r"\brecreation department\b", "recreation department"),
    (
        r"\bcouncil on aging\b.*\b(?:programs?|classes|activities|trips|fitness)\b",
        "council on aging programs",
    ),
    (r"\b(?:church|worship|sermon|prayer)\b", "church"),
    (
        r"\b(?:sports?|athletics?|football|basketball|baseball|softball|soccer"
        r"|volleyball|wrestling|hockey|lacrosse|tournament)\b",
        "sports",
    ),
    (r"\b(?:graduation|commencement|concert|parade|festival|fireworks)\b", "event"),
    (r"\bstudent (?:senate|council)\b", "student body"),
    (r"\bpodcast\b", "podcast"),
    (
        r"\bannual general meeting\b|\bagm\b",
        "annual general meeting (an organization's own)",
    ),
    (r"\b(?:itineraries|itinerary|travel guide|things to do)\b", "tourism"),
]
# "Committee on Culture, Youth, Aging, Sports, and Parks": a named body whose
# topic list happens to hold a non-meeting word.
_BODY_ON_RE = re.compile(r"\b(?:committee|commission|council|board) on\b", re.I)
_HARD_NON_MEETING_RE = [(re.compile(p, re.IGNORECASE), w) for p, w in _HARD_NON_MEETING]

# The access station's own annual meeting.
_STATION_WORDS = r"(?:access|cable|media|tv|television|station|community media)"
_STATION_OWN_MEETING_RE = re.compile(
    r"\bannual (?:membership )?meeting\b", re.IGNORECASE
)

# Soft non-meeting words: a strong body phrase overrides these.
_SOFT_NON_MEETING = [
    (r"\bforums?\b", "forum"),
    (r"\bwebinar\b", "webinar"),
    (r"\bcaucus(?:es)?\b", "caucus"),
    (r"\bworkshops?\b", "workshop"),
    (r"\btown hall\b", "town hall"),
    (r"\bspotlight\b", "spotlight"),
    (r"\binterview\b", "interview"),
    (r"\bupdate\b", "update"),
]
_SOFT_NON_MEETING_RE = [(re.compile(p, re.IGNORECASE), w) for p, w in _SOFT_NON_MEETING]

# Politician-style "town hall": a named person, not a governing body.
_POLITICIAN_TOWN_HALL_RE = re.compile(
    r"\b(?:sheriff|senator|sen\.|representative|rep\.|congress\w*|governor|gov\.|"
    r"candidate|mayor['’]?s?|warren|district attorney|\bda\b)\b.*\btown hall\b"
    r"|\btown hall\b.*\b(?:with|hosted by)\b",
    re.IGNORECASE,
)

# A generic listing or program name with no meeting content.
_LISTING_RE = re.compile(
    r"^\W*(?:recent|all|new|latest|featured|popular)?\s*"
    r"(?:shows?|videos?|uploads?|promotional|promos?|playlists?|vod|on demand|"
    r"live(?:\s*stream)?|programs?|programming|highlights?|favorites|bumpers?|"
    r"public access|local shows?|access shows?|community shows?)\W*$",
    re.IGNORECASE,
)

# Words from the existing video gate that are safe to reuse as hard
# non-meeting signs here. Some of `NON_MEETING_SIGNS` and
# `PROMO_BLOCKLIST` are not (a real council "welcome"s nobody; "overview"
# and "band" appear in real agenda titles), so only these are taken.
_SHARED_NON_MEETING = (
    "promo",
    "psa",
    "public service announcement",
    "ribbon cutting",
    "graduation",
    "commencement",
    "concert",
    "podcast",
    "tutorial",
    "sizzle reel",
    "highlight reel",
    "state of the city",
    "year in review",
)


def _shared_non_meeting_word(title: str) -> Optional[str]:
    low = title.lower()
    for w in _SHARED_NON_MEETING:
        if contains_word(low, w):
            return w
    return None


# School words.
_SCHOOL_RE = re.compile(
    r"\b(?:school(?:s)?|schools? board|school committee|board of ed(?:ucation)?|"
    r"isd|usd|uusd|boe|superintendent|supervisory union|school district)\b",
    re.IGNORECASE,
)
_SCHOOL_BUILDING_RE = re.compile(r"\bschool building (?:committee|commission)\b", re.I)

_SCHOOL_ABBR_RE = re.compile(r"\b[a-z]{2,}(?:isd|usd|uusd|uesd|csd|esd)\b", re.I)
_LOCAL_BODY_RE = re.compile(
    r"\b(?:(?:city|town|village|borough|township|county|common) (?:council|board|commission)"
    r"|board of (?:county )?(?:commissioners|supervisors|selectmen)|commissioners? court"
    r"|select ?board|bocc)\b",
    re.I,
)
_COUNTY_RE = re.compile(
    r"\b(?:county|parish|commissioners? court|board of (?:county )?supervisors|bocc)\b",
    re.IGNORECASE,
)

_STATE_BODY_RE = re.compile(
    r"\b(?:legislature|senate|house of representatives|general assembly|"
    r"state house|state senate|state assembly|state board|state commission|"
    r"state department|supreme court|court of appeals|"
    r"court of criminal appeals|public utilities commission|public service commission)\b",
    re.IGNORECASE,
)
_LOCAL_CUE_RE = re.compile(
    r"\b(?:city|town|village|county|township|borough|parish|municipal|school)\b",
    re.IGNORECASE,
)
_COURT_RE = re.compile(
    r"\b(?:supreme court|court of appeals|court of criminal appeals)\b", re.I
)

# Special-district words (Ryan's rule applies).
_SPECIAL_RE = re.compile(
    r"\b(?:housing authority|housing (?:and|&) redevelopment|redevelopment "
    r"(?:authority|agency|commission)|solid waste|sewer|sewage|sanitary|sanitation|"
    r"wastewater|water (?:district|authority|board|commission|resources|and sewer)|"
    r"soil (?:and|&) water|conservation district|library (?:district|board|trustees)|"
    r"public library|transit (?:authority|district)|transportation authority|"
    r"port (?:authority|district|commission)|airport authority|fire (?:district|"
    r"protection district|authority)|hospital district|cemetery district|"
    r"park district|drainage|levee|irrigation|mosquito|flood control|utility "
    r"(?:district|authority)|energy authority|harbor district|health district|"
    r"urban renewal|redevelopment)\b",
    re.IGNORECASE,
)

# Words that never name a place by themselves.
_COMMON_WORDS = frozenset(
    """agenda council campus economy center centre union liberty commerce
    park parks planning zoning recreation fire water board boards commission
    meeting meetings regular special work session sessions public city town
    village county township borough school schools education library police
    historic historical economic development housing authority committee
    advisory community utility utilities sewer airport transit harbor port
    health safety finance budget citizens open government district regional
    joint main north south east west new old lake river mount valley hill
    hills grove green oak pine central bay beach spring springs falls creek
    mill mills fork rock cedar elm maple fair mid high low big little great
    twin clear grand royal pleasant clay grant perry pike lee orange van wood
    hall house capital
    capitol independence unity harmony concord progress industry enterprise
    welcome star summit plain plains prairie forest field fields ridge
    bridge crossing junction corner corners point station port mountain
    mountains canyon valley dale glen haven land lands city cities
    municipal commissioners court trustees mayor state""".split()
)

_TYPE_WORDS = frozenset(
    {"city", "town", "village", "township", "twp", "borough", "county", "parish"}
)
_STOP = frozenset("of the and & a an in for to at on".split())

_CANADA_STRICT_RE = re.compile(
    r"(?:,\s*(?:bc|on|ab|sk|mb|qc|ns|nb|nl|pe|yt|nt|nu)\b)|british columbia|"
    r"ontario|alberta|saskatchewan|manitoba|quebec|nova scotia|new brunswick|canada",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------
# Name handling
# ---------------------------------------------------------------------


def _norm_tokens(text: str) -> List[str]:
    s = (text or "").lower().replace("&", " and ")
    s = re.sub(r"['’]s\b", "", s)
    s = s.replace("'", "").replace("’", "")
    s = re.sub(r"\bsaint\b", "st", s)
    s = re.sub(r"\bst\.", "st", s)
    s = re.sub(r"\bmt\.?\b", "mount", s)
    s = re.sub(r"\bft\.?\b", "fort", s)
    return re.sub(r"[^a-z0-9]+", " ", s).split()


_TYPE_SUFFIX = {
    "city",
    "town",
    "village",
    "township",
    "borough",
    "cdp",
    "county",
    "parish",
    "municipality",
    "twp",
    "plantation",
    "charter",
}
_SD_WORDS = frozenset(
    """school schools district unified elementary secondary high union joint
    consolidated independent community central city county local area public
    free regional corporation department system isd usd uusd csd cisd""".split()
)
# Words that, beside a school-district name, say "this is a school body".
_SD_CUE_WORDS = frozenset(
    "school schools district isd usd uusd csd unified elementary".split()
)


def _base_name(name: str, *, sd: bool = False) -> Tuple[str, ...]:
    toks = _norm_tokens(name)
    if sd:
        # Strip trailing level / type words ("Unified School District"),
        # but keep "county": "Harnett County Schools" stays "harnett county".
        while len(toks) > 1 and toks[-1] in _SD_WORDS and toks[-1] != "county":
            toks = toks[:-1]
        return tuple(toks)
    while toks and toks[-1] in _TYPE_SUFFIX:
        toks = toks[:-1]
    if len(toks) > 2 and toks[0] == "town" and toks[1] == "of":
        toks = toks[2:]
    return tuple(toks)


@dataclass(frozen=True)
class _Cand:
    gov_id: str
    kind: str
    name: str
    state: str
    county_fips: str = ""


class _Index:
    """state -> base-name tokens -> candidates, per government kind."""

    def __init__(self) -> None:
        self.muni: Dict[str, Dict[Tuple[str, ...], List[_Cand]]] = {}
        self.county: Dict[str, Dict[Tuple[str, ...], List[_Cand]]] = {}
        self.sd: Dict[str, Dict[Tuple[str, ...], List[_Cand]]] = {}
        self.all_places: Dict[Tuple[str, ...], List[_Cand]] = {}
        self.special: Dict[str, List[Tuple[FrozenSet[str], str, str]]] = {}
        self.state_name_to_abbr: Dict[str, str] = {}
        self.fips_to_abbr: Dict[str, str] = {}

        for r in tables.us_places().rows():
            if r.funcstat and r.funcstat not in ("A", "C", "F", ""):
                pass
            c = _Cand(f"us:place:{r.row_id}", KIND_PLACE, r.name, r.state.upper())
            self._add(self.muni, c, _base_name(r.name))
        for r in tables.us_cousubs().rows():
            c = _Cand(
                f"us:cousub:{r.row_id}",
                KIND_COUSUB,
                r.name,
                r.state.upper(),
                r.row_id[:5],
            )
            self._add(self.muni, c, _base_name(r.name))
        for r in tables.us_counties().rows():
            c = _Cand(
                f"us:county:{r.row_id}", KIND_COUNTY, r.name, r.state.upper(), r.row_id
            )
            self._add(self.county, c, _base_name(r.name))
        for r in tables.us_school_districts().rows():
            c = _Cand(f"us:sd:{r.row_id}", KIND_SCHOOL, r.name, r.state.upper())
            self._add(self.sd, c, _base_name(r.name, sd=True))
        for r in tables.us_states().rows():
            self.state_name_to_abbr[" ".join(_norm_tokens(r.name))] = r.state.upper()
            self.fips_to_abbr[r.row_id] = r.state.upper()
        filler = _SPECIAL_FILLER
        for gov in registry.governments().values():
            if gov.gov_type != classify.SPECIAL_DISTRICT or gov.country != "us":
                continue
            toks = frozenset(
                t
                for t in _norm_tokens(gov.gov_name)
                if t not in filler and t not in _STOP
            )
            if len(toks) >= 2:
                self.special.setdefault(gov.state.upper(), []).append(
                    (toks, gov.gov_id, gov.gov_name)
                )

    @staticmethod
    def _add(
        table: Dict[str, Dict[Tuple[str, ...], List[_Cand]]],
        cand: _Cand,
        key: Tuple[str, ...],
    ) -> None:
        if not key:
            return
        table.setdefault(cand.state, {}).setdefault(key, []).append(cand)


_SPECIAL_FILLER = frozenset(
    """meeting meetings mtg regular special session sessions work workshop
    board commission committee directors trustees public hearing hearings
    agenda minutes live video joint presents district authority department
    commissioners of the and""".split()
)


@lru_cache(maxsize=1)
def _index() -> _Index:
    return _Index()


def clear_caches() -> None:
    _index.cache_clear()


# ---------------------------------------------------------------------
# Place matching
# ---------------------------------------------------------------------


@dataclass
class _PlaceHit:
    tokens: Tuple[str, ...]
    cands: List[_Cand]
    cue: Optional[str]  # type cue word found next to the name, if any
    start: int
    end: int
    in_known: bool = False
    soft_cue: bool = False


# A word right after a place name that says the name goes on ("San
# Joaquin River", "Midland Airport"): the place is not what is named.
_NAME_CONTINUES = frozenset(
    """river valley lake bay creek mountain mountains canyon regional basin
    watershed conservancy university college hospital medical airport
    national state harbor port""".split()
)
# Ordinary English words that also happen to be tiny place names ("How,
# WI"). Never a place on their own.
_FUNCTION_WORDS = frozenset(
    """how to see below above about after again all also and any are attend
    before being both but can day days did does for from get has have her
    here him his how its let may more most new not now off one only other
    our out own per she some such than that the their them then there these
    they this those too two under until use very was way were what when
    where which while who why will with would you your additional instructions
    provide testimony regular special joint annual live video meeting notice
    agenda final first second third fourth fifth last next online zoom
    hybrid virtual budget""".split()
)


def _body_blocked_indices(text: str) -> Set[int]:
    """Token positions inside a body or meeting phrase ("City Council",
    "Regular Meeting"): those tokens are never a place name."""
    toks = _norm_tokens(text)
    s = " ".join(toks)
    starts = []
    pos = 0
    for t in toks:
        starts.append(pos)
        pos += len(t) + 1
    blocked: Set[int] = set()
    for rx in (_BODY_RE, _MEETING_WORD_RE):
        for m in rx.finditer(s):
            for k, st in enumerate(starts):
                if st < m.end() and st + len(toks[k]) > m.start():
                    blocked.add(k)
    return blocked


def _find_places(
    text: str,
    table: Dict[str, Dict[Tuple[str, ...], List[_Cand]]],
    states: Iterable[str],
    known: Set[str],
    *,
    sd: bool = False,
    state_names: Optional[Set[str]] = None,
    loose: bool = False,
) -> List[_PlaceHit]:
    """Longest-first n-gram matches of `text` against `table` within
    `states`. A name made only of common English words is dropped unless
    a type cue sits next to it or a candidate is in `known`. Tokens inside
    a body or meeting phrase never match."""
    toks = _norm_tokens(text)
    blocked = _body_blocked_indices(text)
    hits: List[_PlaceHit] = []
    used: Set[int] = set(blocked)
    states = [s for s in states if s]
    cue_words = _SD_CUE_WORDS if sd else _TYPE_SUFFIX
    for n in (5, 4, 3, 2, 1):
        for i in range(0, len(toks) - n + 1):
            if any(j in used for j in range(i, i + n)):
                continue
            gram = tuple(toks[i : i + n])
            if all(w in _STOP for w in gram):
                continue
            cands: List[_Cand] = []
            for st in states:
                cands.extend(table.get(st, {}).get(gram, []))
            if not cands:
                continue
            prev = toks[i - 1] if i > 0 else ""
            prev2 = toks[i - 2] if i > 1 else ""
            nxt = toks[i + n] if i + n < len(toks) else ""
            cue = None
            cue_idx = -1
            if prev in cue_words or (prev == "of" and prev2 in cue_words):
                cue = prev if prev in cue_words else prev2
                cue_idx = i - 1 if prev in cue_words else i - 2
            elif nxt in cue_words:
                cue = nxt
                cue_idx = i + n
            # A type word that is part of the body phrase ("Town Council")
            # is a soft cue: it narrows candidates but never rules one out.
            soft = cue_idx in blocked
            in_known = any(c.gov_id in known for c in cands)
            all_common = all(w in _COMMON_WORDS or w in _STOP for w in gram)
            if all_common and n < 3 and not cue and not in_known and not loose:
                continue
            if not cue and not in_known and not loose:
                if n == 1 and (len(gram[0]) < 4 or gram[0] in _FUNCTION_WORDS):
                    continue
                if nxt in _NAME_CONTINUES and not sd:
                    continue
                if state_names and " ".join(gram) in state_names:
                    continue
            hits.append(_PlaceHit(gram, cands, cue, i, i + n, in_known, soft))
            used.update(range(i, i + n))
    hits.sort(key=lambda h: h.start)
    return hits


_CUE_TO_NAME_WORD = {
    "city": "city",
    "town": "town",
    "village": "village",
    "borough": "borough",
    "township": "township",
    "twp": "township",
}


def _choose(
    cands: List[_Cand],
    cue: Optional[str],
    known: Set[str],
    county_fips: Optional[str],
    soft_cue: bool = False,
) -> Tuple[Optional[_Cand], str]:
    """One candidate, or (None, why not)."""
    cands = list({c.gov_id: c for c in cands}.values())
    if cue in _CUE_TO_NAME_WORD:
        # "Village of X" / "X city": the type word picks the row. If no
        # row has that type ("Center City" vs Center township), the cue
        # says this is not that place.
        word = _CUE_TO_NAME_WORD[cue]
        typed = [c for c in cands if c.name.lower().split()[-1] == word]
        if typed:
            cands = typed
        elif not soft_cue:
            # Census calls many "Town of X" places "X city" (and the
            # reverse), so city/town/village/borough are one family. Only
            # a cue from another family (a township, a county) rules a
            # candidate out: "Center City" is not Center township.
            family = {"city", "town", "village", "borough"}
            if word not in family or not any(
                c.name.lower().split()[-1] in family for c in cands
            ):
                return None, f"cue_{cue}_matches_no_candidate"
    in_known = [c for c in cands if c.gov_id in known]
    if len(in_known) == 1:
        return in_known[0], "in_known_gov_ids"
    if len(in_known) > 1:
        cands = in_known
    if county_fips:
        inc = [c for c in cands if c.county_fips == county_fips]
        if len(inc) == 1:
            return inc[0], "in_station_county"
        if inc:
            cands = inc
    if len(cands) > 1:
        # A township and an incorporated place of one name: only a cue
        # that says "township" picks the township.
        if cue not in ("township", "twp"):
            non_twp = [c for c in cands if "township" not in c.name.lower()]
            if non_twp:
                cands = non_twp
    if len(cands) > 1 and any(c.kind == KIND_PLACE for c in cands):
        placed = [c for c in cands if c.kind == KIND_PLACE]
        # A Census place and a county subdivision of the same name in one
        # state are usually the same town; only pick when one kind is left.
        if len(placed) == 1 and not any(
            c.kind == KIND_COUSUB and c.state == placed[0].state for c in cands
        ):
            cands = placed
    if len(cands) == 1:
        return cands[0], "unique_name_in_state"
    return None, f"ambiguous_{len(cands)}_candidates"


# ---------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------


def _states_from_known(known: Set[str]) -> Set[str]:
    out: Set[str] = set()
    for gid in known:
        g = registry.government_for_id(gid)
        if g and g.state:
            out.add(g.state.upper())
    return out


def _state_of(gov_id: str) -> str:
    g = registry.government_for_id(gov_id)
    return (g.state or "").upper() if g else ""


def _channel_conflict(
    channel_text: str,
    title_cand: Optional[_Cand],
    known: Set[str],
    station_state: str,
) -> Optional[str]:
    """Reason the channel names a different place than `title_cand`, or
    None. Conservative: a name needs a type cue, or two words, or a
    Canadian province, to count."""
    if not channel_text:
        return None
    if station_state and not (known and any(g.startswith("ca:") for g in known)):
        if _CANADA_STRICT_RE.search(channel_text):
            return "channel_names_canada"
    idx = _index()
    toks = _norm_tokens(channel_text)
    # Every state: a channel place needs to be checked against the station
    # state, so search nationally.
    for n in (4, 3, 2, 1):
        for i in range(0, len(toks) - n + 1):
            gram = tuple(toks[i : i + n])
            if all(w in _COMMON_WORDS or w in _STOP for w in gram):
                # needs a cue on at least one side
                prev = toks[i - 1] if i > 0 else ""
                nxt = toks[i + n] if i + n < len(toks) else ""
                if prev not in _TYPE_SUFFIX and nxt not in _TYPE_SUFFIX:
                    continue
                if all(w in _STOP or w in _TYPE_SUFFIX for w in gram):
                    continue
            prev = toks[i - 1] if i > 0 else ""
            nxt = toks[i + n] if i + n < len(toks) else ""
            has_cue = prev in _TYPE_SUFFIX or nxt in _TYPE_SUFFIX
            if n == 1 and not has_cue:
                continue
            matches = []
            for st, by_name in idx.muni.items():
                matches.extend(by_name.get(gram, []))
            if not matches:
                continue
            if title_cand is not None and gram == _base_name(title_cand.name):
                return None
            if any(m.gov_id in known for m in matches):
                return None
            if station_state and all(m.state != station_state for m in matches):
                return f"channel_names_{' '.join(gram)}_in_other_state"
            if title_cand is not None and all(
                m.gov_id != title_cand.gov_id for m in matches
            ):
                # Names a same-state place that is not the title's place.
                if has_cue and n >= 1:
                    return f"channel_names_other_place_{' '.join(gram)}"
    return None


def _clean_body(title: str, span: Optional[Tuple[int, int]] = None) -> str:
    t = re.sub(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", " ", title)
    t = re.sub(
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?,?\s*(?:\d{4})?",
        " ",
        t,
        flags=re.I,
    )
    t = re.sub(r"\b\d{4}(?:-\d{2}-\d{2})?\b", " ", t)
    t = re.sub(r"\b\d{1,2}:\d{2}\s*(?:am|pm)?\b", " ", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" -:|,.")
    return t


def classify_title(
    title: Optional[str],
    *,
    channel_name: Optional[str] = None,
    channel_handle: Optional[str] = None,
    station_state: Optional[str] = None,
    station_county_fips: Optional[str] = None,
    known_gov_ids: Optional[Iterable[str]] = None,
) -> TitleVerdict:
    """Classify one title. See the module docstring for the rules.

    `station_state`: two-letter state of the station or channel, if known.
    `known_gov_ids`: governments the station or channel is known to carry.
    With neither, only titles that name their own type cue resolve."""
    reasons: List[str] = []
    text = (title or "").strip()
    if not text:
        return TitleVerdict(None, None, None, None, LOW, ["empty_title"], LOW, LOW)

    known: Set[str] = {g for g in (known_gov_ids or ()) if g}
    st = (station_state or "").upper()
    states: Set[str] = {st} if st else _states_from_known(known)
    # "AllenCounty_BoardofCommissioners" -> words, so the lexicons see them.
    text = re.sub(r"(?<=[a-z]{3})(?=[A-Z][a-z])", " ", text).replace("_", " ")
    low = text.lower()
    channel_text = " ".join(
        x for x in (channel_name, re.sub(r"[_@-]", " ", channel_handle or "")) if x
    )

    # ---- meeting yes / no ------------------------------------------
    body_m = _BODY_RE.search(text)
    body_word = body_m.group(0).lower() if body_m else None
    strong_body = bool(body_m) and not (
        body_word in _WEAK_BODY_WORDS and not re.search(r"\b(?:of|on)\b", low)
    )
    # "commission"/"board"/"committee" alone are real bodies ("Planning
    # Commission" matches "planning commission"). A bare word is weak.
    has_meeting_word = bool(_MEETING_WORD_RE.search(text))

    hard = None
    for rx, word in _HARD_NON_MEETING_RE:
        if rx.search(text):
            if word in ("tourism", "sheriff") and body_m is not None:
                # "Seaside Tourism Advisory Committee", "Board of
                # Supervisors Meeting ... Sheriff": a named body wins.
                continue
            hard = word
            break
    if hard is None and _POLITICIAN_TOWN_HALL_RE.search(text):
        hard = "politician town hall"
    if (
        hard is None
        and _STATION_OWN_MEETING_RE.search(text)
        and re.search(r"\b" + _STATION_WORDS + r"\b", text, re.I)
    ):
        hard = "the access station's own annual meeting"
    if hard is None:
        shared = _shared_non_meeting_word(text)
        if shared:
            hard = shared
    if hard is None and _LISTING_RE.match(text):
        hard = "generic listing name"

    meeting: Optional[bool]
    confidence = MEDIUM
    body: Optional[str] = None
    if hard:
        meeting = False
        confidence = HIGH
        reasons.append(f"non_meeting:{hard}")
        # A hard word beside a strong body is a real conflict only when it
        # is a person/party/show word; still False, but one notch lower
        # when the title also says "meeting".
        if (
            (has_meeting_word or _BODY_ON_RE.search(text))
            and strong_body
            and hard
            in (
                "tour",
                "candidate",
                "sports",
                "event",
                "church",
                "presents (a show)",
                "tourism",
            )
        ):
            # A real body's meeting that also mentions candidates or a tour
            # ("City Council Special Meeting - Mayoral Candidate
            # Interviews"): the words conflict, so nothing is settled.
            meeting = None
            confidence = LOW
            reasons.append("conflict_body_and_meeting_words_vs_" + hard)
    else:
        soft = None
        for rx, word in _SOFT_NON_MEETING_RE:
            if rx.search(text):
                soft = word
                break
        if body_m:
            meeting = True
            body = _clean_body(text)
            multiword = " " in (body_word or "") or body_word in {
                "council",
                "trustees",
                "supervisors",
                "commissioners",
                "zoning",
                "selectmen",
                "selectboard",
                "bocc",
            }
            if body_word in _WEAK_BODY_WORDS and not has_meeting_word:
                confidence = MEDIUM
                reasons.append(f"weak_body_word:{body_word}")
            elif soft and not multiword:
                confidence = LOW
                reasons.append(f"soft_non_meeting:{soft}")
            elif soft:
                confidence = MEDIUM
                reasons.append(f"soft_non_meeting:{soft}")
            else:
                confidence = HIGH
                reasons.append(f"body_word:{body_word}")
            if re.search(r"\bcouncil\b", low) and body_word == "council":
                # a bare "council" is a body only beside a meeting word or place
                if not has_meeting_word and not re.search(
                    r"\b(?:city|town|county|village|borough|township|common)\b", low
                ):
                    confidence = MEDIUM
                    reasons.append("bare_council")
        elif _SPECIAL_RE.search(text) or re.search(r"\bcoa\b", low):
            # "North West Fire District", "Easthampton COA": a public body
            # named with no body word. Meeting candidate, not settled.
            meeting = True
            confidence = MEDIUM
            reasons.append("special_district_or_coa_words")
            body = _clean_body(text)
        elif has_meeting_word:
            meeting = True
            confidence = MEDIUM
            reasons.append("meeting_word_only")
            body = _clean_body(text)
        else:
            meeting = None
            confidence = LOW
            reasons.append(NO_EVIDENCE_REASON)
    if meeting is not True:
        # Nothing else to decide for a non-meeting or an unread title.
        return TitleVerdict(
            meeting, body, None, None, confidence, reasons, confidence, LOW
        )

    # ---- which government ------------------------------------------
    idx = _index()
    names = set(idx.state_name_to_abbr)
    title_cand: Optional[_Cand] = None

    school_m = _SCHOOL_RE.search(text) or _SCHOOL_ABBR_RE.search(text)
    is_school = (
        bool(school_m)
        and not _SCHOOL_BUILDING_RE.search(text)
        and not re.search(r"\bstate (?:board|department)\b", low)
    )
    local_m = _LOCAL_BODY_RE.search(text)
    if is_school and local_m and local_m.start() < school_m.start():
        # "City Council ... (Joint Meeting with Denton ISD Board)": the
        # body named first is the one this recording belongs to.
        is_school = False
    is_state_body = bool(_STATE_BODY_RE.search(text)) and not _LOCAL_CUE_RE.search(text)
    is_special = bool(_SPECIAL_RE.search(text)) and not re.search(
        r"\b(?:city|town|village|borough) council\b", low
    )
    is_county = bool(_COUNTY_RE.search(text)) and not is_school
    # The shared body-phrase table (WO-1078) knows "commissioners court",
    # "board of selectmen" and so on; let it settle the kind when it can.
    phrase = gov_body_types.match_body_type_phrase(text)
    if phrase is not None:
        expected = phrase[1]
        if expected == frozenset({classify.COUNTY}):
            is_county = True
        elif expected == frozenset({classify.SCHOOL_DISTRICT}) and not is_school:
            is_school = not _SCHOOL_BUILDING_RE.search(text)

    meeting_confidence = confidence

    def _finish(g_id, g_kind, conf, why) -> TitleVerdict:
        reasons.append(why)
        # The verdict is only as sure as its weakest part: the meeting
        # call or the identity call.
        order = {LOW: 0, MEDIUM: 1, HIGH: 2}
        final = min(conf, meeting_confidence, key=order.__getitem__)
        return TitleVerdict(
            True,
            body,
            g_id,
            g_kind,
            final,
            reasons,
            meeting_confidence,
            conf if g_id else LOW,
        )

    # Rule 6: legislature / state agency / court.
    if (
        not is_state_body
        and re.search(r"\blegislative\b", low)
        and not _LOCAL_CUE_RE.search(text)
    ):
        # "Legislative Session" may be a state body or a county legislature
        # (NY, NC): not settled by words alone.
        return _finish(None, None, LOW, "legislative_could_be_state_or_county")
    if is_state_body and not is_school:
        if st and station_state_gov(st):
            reasons.append("state_body")
            return _finish(
                station_state_gov(st),
                KIND_STATE,
                HIGH
                if _COURT_RE.search(text)
                or re.search(r"legislat|senate|general assembly|house of rep", low)
                else MEDIUM,
                "state_body_maps_to_state",
            )
        if len(states) == 1:
            s = next(iter(states))
            g = station_state_gov(s)
            if g:
                return _finish(g, KIND_STATE, MEDIUM, "state_body_maps_to_state")
        return _finish(None, KIND_STATE, LOW, "state_body_state_unknown")

    # Rule 4: school bodies map to school districts only.
    if is_school:
        hits = _find_places(
            text,
            idx.sd,
            states,
            known,
            sd=True,
            state_names=names,
        )
        known_sds = {g for g in known if g.startswith("us:sd:")}
        cand = None
        why = ""
        if hits:
            h = hits[0]
            cands = h.cands
            if re.search(r"county board of education|county board of ed", low) or (
                "county" in _norm_tokens(text) and re.search(r"board of ed", low)
            ):
                # A county board of education is a county office unless the
                # district itself is named "<X> County ...".
                cands = [c for c in cands if "county" in c.name.lower()]
                if not cands:
                    reasons.append(
                        "county_board_of_education_is_not_the_local_district"
                    )
                    return _finish(
                        None, KIND_SCHOOL, LOW, "no_district_for_county_board"
                    )
            cand, why = _choose(cands, h.cue, known, station_county_fips, h.soft_cue)
            if cand is not None:
                conf = HIGH if (h.in_known or h.cue or len(h.tokens) >= 2) else MEDIUM
                return _finish(
                    cand.gov_id, KIND_SCHOOL, conf, f"school_body_name_match:{why}"
                )
        if (
            not hits
            and channel_name
            and _channel_conflict(channel_text, None, known, st) is None
        ):
            ch_hits = _find_places(
                channel_name, idx.sd, states, known, sd=True, state_names=names
            )
            for ch in ch_hits:
                cand, why = _choose(ch.cands, ch.cue, known, station_county_fips)
                if cand is not None:
                    return _finish(
                        cand.gov_id,
                        KIND_SCHOOL,
                        MEDIUM,
                        f"school_body_district_from_channel_name:{why}",
                    )
        loose = _find_places(text, idx.sd, states, known, sd=True, loose=True)
        if len(known_sds) == 1 and not hits and not loose and body_m is not None:
            return _finish(
                next(iter(known_sds)),
                KIND_SCHOOL,
                MEDIUM,
                "school_body_single_known_district",
            )
        return _finish(None, KIND_SCHOOL, LOW, "school_body_no_district_matched")

    # Rule 7: special districts.
    if is_special:
        spec_reason = _special_id(text, states)
        hits = _find_places(text, idx.muni, states, known, state_names=names)
        parent = None
        if hits:
            h = hits[0]
            parent, _why = _choose(
                h.cands, h.cue, known, station_county_fips, h.soft_cue
            )
        if spec_reason is not None:
            sid, sname = spec_reason
            reasons.append(f"registry_special_district:{sname}")
            return _finish(sid, KIND_SPECIAL, HIGH, "existing_special_district_id")
        if parent is not None:
            conf = HIGH if (hits[0].cue or hits[0].in_known) else MEDIUM
            return _finish(
                parent.gov_id,
                parent.kind,
                MEDIUM if conf == HIGH else LOW,
                "special_district_filed_under_local_government",
            )
        # A single known municipality: file under it.
        known_munis = {g for g in known if g.split(":")[1] in ("place", "cousub")}
        if len(known_munis) == 1:
            g = next(iter(known_munis))
            return _finish(
                g,
                KIND_PLACE if ":place:" in g else KIND_COUSUB,
                LOW,
                "special_district_single_known_municipality",
            )
        return _finish(None, KIND_SPECIAL, LOW, "special_district_no_place_named")

    # Municipal and county bodies.
    table = idx.county if is_county else idx.muni
    hits = _find_places(text, table, states, known, state_names=names)
    if is_county and not hits:
        known_c = {g for g in known if g.startswith("us:county:")}
        if len(known_c) == 1 and body_m is not None:
            title_cand = None
            g = next(iter(known_c))
            return _finish(g, KIND_COUNTY, MEDIUM, "county_body_single_known_county")
    chosen_hit = None
    for h in hits:
        cand, why = _choose(h.cands, h.cue, known, station_county_fips, h.soft_cue)
        if cand is not None:
            title_cand, chosen_hit = cand, h
            reasons.append(f"place_match:{cand.name}:{why}")
            break
        reasons.append(f"place_unresolved:{' '.join(h.tokens)}:{why}")
    if title_cand is not None:
        conflict = _channel_conflict(channel_text, title_cand, known, st)
        if conflict and title_cand.gov_id not in known:
            return _finish(None, None, LOW, conflict)
        strong = chosen_hit.in_known or chosen_hit.cue or len(chosen_hit.tokens) >= 2
        return _finish(
            title_cand.gov_id,
            title_cand.kind,
            HIGH if strong else MEDIUM,
            "place_in_title",
        )
    # No place settled in the title. Next the channel or site name, then a
    # single known government of the right kind. Neither runs when the
    # title names a place the rules could not settle: that is a real
    # conflict, not a blank.
    if (
        channel_name
        and not hits
        and _channel_conflict(channel_text, None, known, st) is None
    ):
        for ch in _find_places(channel_name, table, states, known, state_names=names):
            cand, why = _choose(ch.cands, ch.cue, known, station_county_fips)
            if cand is not None:
                return _finish(
                    cand.gov_id,
                    cand.kind,
                    MEDIUM,
                    f"place_from_channel_name:{cand.name}:{why}",
                )
    loose_hits = _find_places(text, table, states, known, loose=True)
    kinds = ("county",) if is_county else ("place", "cousub")
    pool = {g for g in known if g.split(":")[1] in kinds}
    if len(pool) == 1 and body_m is not None and not loose_hits:
        g = next(iter(pool))
        if _channel_conflict(channel_text, None, known, st) is None:
            k = g.split(":")[1]
            return _finish(
                g,
                {"place": KIND_PLACE, "cousub": KIND_COUSUB, "county": KIND_COUNTY}[k],
                MEDIUM,
                "generic_body_single_known_government",
            )
    conflict = _channel_conflict(channel_text, None, known, st)
    if conflict:
        reasons.append(conflict)
    return _finish(None, None, LOW, "no_place_in_title")


def station_state_gov(state: str) -> Optional[str]:
    return tables.state_gov_id(state)


def _special_id(text: str, states: Iterable[str]) -> Optional[Tuple[str, str]]:
    """An existing registry special-district id whose distinctive name
    words equal the title's (same state)."""
    idx = _index()
    toks = frozenset(
        t for t in _norm_tokens(text) if t not in _SPECIAL_FILLER and t not in _STOP
    )
    if len(toks) < 2:
        return None
    found = []
    for st in states:
        for rtoks, gid, name in idx.special.get(st, []):
            if rtoks == toks:
                found.append((gid, name))
    found = list(dict.fromkeys(found))
    return found[0] if len(found) == 1 else None
