#!/usr/bin/env python3
"""WO-1053: link-first hub harvest -- regional TV hubs to governments.

Some governments' meetings are never findable by starting from their own
website (Nashwauk, MN and Wilder, KY are the two Ryan named 2026-09-24) --
they only exist on a REGIONAL hub run by a bigger group or county, with a
per-town or per-body section. This is the "link-first" flow
(rtr-business `research/LINK_FIRST_MATCHING.md`): read the hub, match each
section to a real government by name AND state AND type, then record a
pin -- never trust a hub's own slug/host name as evidence on its own.

Dry run only. This script never ingests, never writes
`tenant_overrides.csv`, `jurisdiction_coverage.csv`, or any ingest queue --
it only reads `app/utils/jurisdiction_data/regional_tv_hubs.csv` (seeded by
this same WO) and real hub pages, and writes three CSVs to an output
directory the caller names:

    hub_sections.csv        every section this pass found on every hub,
                             whether or not it matched a government
    ingest_queue_plan.csv   confident, not-yet-covered matches only, with
                             a caption tier from a real (read-only) adapter
                             resolve() call
    hand_read.csv           everything a human needs to look at: no clean
                             match, or a hub shape this pass can't walk yet

Usage:
    PYTHONPATH=. .venv/bin/python scripts/hub_harvest.py --out <dir>

Polite by design: one request at a time per host, a real delay between
requests, YouTube fetch guard installed unconditionally (Pierce County TV
is YouTube-only and is never fetched here at all -- see `_youtube_hub()`).
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import re
import sys
from dataclasses import dataclass
from dataclasses import replace as _dc_replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import aiohttp

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.youtube_fetch_guard import install as install_youtube_guard  # noqa: E402
from app.platforms.cablecast import CablecastAssetFinder  # noqa: E402
from app.platforms.telvue import TelvueAssetFinder  # noqa: E402
from app.utils.gov_registry import classify, resolver  # noqa: E402

HUB_CSV = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "utils"
    / "jurisdiction_data"
    / "regional_tv_hubs.csv"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; RedTapeRecordingsHubHarvest/1.0; "
        "+https://redtaperecordings.com)"
    )
}

# Politeness: one request at a time per host, with a real gap between
# requests to the same host (CLAUDE.md: "we query sites politely").
POLITE_DELAY_SECONDS = 1.5

# Real, confirmed real-world phrases that name a governing BODY (not just
# a place) -- used only to decide whether a section's own title is worth
# trying to match at all, and to describe (not authoritatively classify --
# that is `resolver.resolve_government()`'s job) the body type for the
# report. Every phrase here is one actually seen on a real hub while
# building this script (see `regional_tv_hubs.csv`'s own notes) or named
# in the WO-1053 brief.
_BODY_TYPE_WORDS: Tuple[Tuple[str, str], ...] = (
    ("school board", "school district"),
    ("school district", "school district"),
    ("board of education", "school district"),
    # WO-1060 review (Ryan, 2026-09-25): "X County Schools" (e.g. "Nassau
    # County Schools") names the same real government as "X County School
    # Board"/"X County School District" -- none of the three patterns
    # above match it (no "school board"/"school district"/"board of
    # education" substring), so it fell through to no body type at all.
    ("county schools", "school district"),
    ("county board", "county"),
    ("board of commissioners", "county"),
    ("commissioners court", "county"),
    ("borough council", "borough"),
    ("town council", "town"),
    ("township board", "township"),
    ("board of supervisors", "township"),
    ("board of trustees", "township-or-village"),
    ("select board", "town"),
    ("village board", "village"),
    ("city council", "city"),
    ("city commission", "city"),
    ("town board", "town"),
    ("planning commission", "same-as-named-place"),
    ("park board", "same-as-named-place"),
    ("township council", "township"),
)

# A looser, single-word gate for "is this even worth trying to match" --
# broader than `_BODY_TYPE_WORDS` on purpose. Real gap found live
# 2026-09-24: Centre County C-NET's own real playlist titles include
# "Borough of State College - Council" and "College Township Council",
# neither of which contains any exact two-word phrase above, so the
# stricter phrase check alone skipped real governing-body sections
# outright instead of letting `resolve_government()` decide. This gate
# only decides whether to TRY a match at all; the resolver (and its own
# `unverified`/`blank` tiers) is what actually decides confidence, so a
# false positive here costs nothing worse than an extra hand_read row.
_LOOSE_BODY_WORDS = (
    "council",
    "commission",
    "board",
    "supervisors",
    "trustees",
    "select board",
    "aldermen",
)


def _looks_like_a_government_body(text: str) -> bool:
    lowered = (text or "").lower()
    if any(phrase in lowered for phrase in (w for w, _ in _BODY_TYPE_WORDS)):
        return True
    return any(word in lowered for word in _LOOSE_BODY_WORDS)


def _guessed_body_type(text: str) -> str:
    lowered = (text or "").lower()
    for phrase, body_type in _BODY_TYPE_WORDS:
        if phrase in lowered:
            return body_type
    return ""


# WO-1074 addendum (Ryan, 2026-09-25): a hand-check of real "confident"
# matches found the government-TYPE word in a title was being ignored --
# "Town of Horseheads Planning Board" matched Horseheads VILLAGE, NY;
# "Springfield Township Board" matched Springfield CITY, MI; "Grant
# County Board of Commissioners" matched Grant (a city), MN; "Lucas
# County Plan Commission" matched Lucas village, OH; "Hilton Head Island
# Town Council" matched Beaufort COUNTY, SC. Every one of these is a real,
# different government from the one actually named -- the registry
# distinguishes them (`Government.gov_type`: `county`, `school_district`,
# `township` for a Census county-subdivision id (`us:cousub:`, a New
# England/NY/PA-style "town"/"township"), `municipality` for a Census
# place id (`us:place:`, an incorporated city/village/borough/town) -- so
# a body-type word this specific maps to a real, checkable constraint.
# `_BODY_TYPE_WORDS`'/`_extract_lead_place()`'s own vocabulary (both
# broader, phrase- or suffix-based) is normalized down to these same
# five buckets by `normalize_body_type_word()` below.
#
# "town"/"borough"/"village"/"city" all map to the SAME real gov_type
# (`municipality`) OR, for "town" alone, also `township` -- Census tracks
# an incorporated municipality without regard to its own state-legal
# label (a "city", "town", "village" or "borough" are all one `place`
# row), while a "town" specifically can ALSO be a New England/NY/WI-style
# county subdivision with no separate incorporated-place status at all
# (the real Horseheads case: the TOWN is `us:cousub:`/`township`, the
# VILLAGE inside it is a separate `us:place:`/`municipality`). Keeping
# "town" permissive (either type) avoids a false rejection in a state
# where "town" means an ordinary incorporated municipality; the real
# regressions above are all still caught because none of their WRONG
# matches were even in the permitted set (a county, in each case).
_EXPECTED_GOV_TYPES_BY_BODY_TYPE: Dict[str, frozenset] = {
    "county": frozenset({classify.COUNTY}),
    "school district": frozenset({classify.SCHOOL_DISTRICT}),
    "township": frozenset({classify.TOWNSHIP}),
    # WO-1074 addendum: real Horseheads, NY case -- an explicit "Town of
    # X" is this repo's own established convention for the county-
    # subdivision id (`us:cousub:`/`township`), per `resolver.py`'s own
    # `_general_purpose_lookup()` docstring ("the town resolves to
    # `us:cousub:...` and the village to `us:place:...`"). Kept strict
    # (not permissive of `municipality` too, unlike `township-or-village`
    # below) specifically because "Town of Horseheads Planning Board"
    # matching Horseheads VILLAGE, NY (`municipality`) is the real
    # regression this fix exists for.
    "town": frozenset({classify.TOWNSHIP}),
    "township-or-village": frozenset({classify.TOWNSHIP, classify.MUNICIPALITY}),
    "village": frozenset({classify.MUNICIPALITY}),
    "city": frozenset({classify.MUNICIPALITY}),
    "borough": frozenset({classify.MUNICIPALITY}),
}

# `pick.describe_foreign_candidate()`'s own `place_type` vocabulary (the
# literal type word found next to the place name in a title: "county",
# "town", "township", "borough", "village", "city", "parish", "school
# district", "isd", "usd" -- see `pick._LEAD_PLACE_PHRASE_PATTERNS`) is
# close to but not identical to `_BODY_TYPE_WORDS`'s own descriptive
# strings above -- normalized here so both callers (this script's own
# `_guessed_body_type()` hint and `scripts/meeting_finder_other_gov_
# leads.py`'s `place_type` field) feed `_match_place_text()` the same
# vocabulary.
_PLACE_TYPE_WORD_ALIASES: Dict[str, str] = {
    "parish": "county",  # Louisiana's county-equivalent.
    "isd": "school district",
    "usd": "school district",
}


def normalize_body_type_word(word: str) -> str:
    """A raw type word (from `pick.py`'s `place_type` or this script's
    own `_guessed_body_type()`) reduced to one of
    `_EXPECTED_GOV_TYPES_BY_BODY_TYPE`'s own keys, or "" when `word`
    carries no real type-agreement constraint (e.g. "same-as-named-place",
    or a word this function doesn't recognize)."""
    normalized = (word or "").strip().lower()
    normalized = _PLACE_TYPE_WORD_ALIASES.get(normalized, normalized)
    if normalized in _EXPECTED_GOV_TYPES_BY_BODY_TYPE:
        return normalized
    return ""


def _resolver_candidate_text(text: str) -> str:
    """`app/utils/jurisdiction_enrich.finalize_jurisdiction()`'s repair
    rule turns "X City Council MEETING, ST" into "X City, ST" (a real
    place-table hit) but does NOT recognize a bare "X City Council, ST"
    with no trailing "Meeting" -- confirmed live 2026-09-24 building this
    script: `resolve_government("Nashwauk City Council, MN", ...)` minted
    a new `rtr:` id instead of finding the real, already-registered
    `us:place:2744980`, while the identical text with " Meeting" appended
    matched the registry cleanly (same real gap on Wilder, KY and
    Cohasset, MN). Every section title this script sees is a hub's own
    listing/category name, never literally "... Meeting" already in most
    cases (e.g. plain "Nashwauk City Council"), so this appends the one
    word `finalize_jurisdiction()` is already looking for whenever the
    text doesn't already end with it -- a workaround kept in this WO's
    own script rather than a change to `jurisdiction_enrich.py`, which
    this WO does not own."""
    stripped = (text or "").strip()
    if not stripped:
        return stripped
    if stripped.lower().endswith(("meeting", "meetings")):
        return stripped
    return f"{stripped} Meeting"


# --------------------------------------------------------------------
# Ryan's 2026-09-24 review of this PR (#1434) flagged two real wrong
# "confident" matches -- exactly the risk he named when this WO was
# assigned: small, similarly named places. Both are fixed below.
# --------------------------------------------------------------------

# 1. A JOINT or SPECIAL body is never the county/town it happens to be
# named after or hosted by -- it is a separate body, sometimes literally
# run BY several governments together (a cable commission, a council of
# governments), sometimes a quasi-independent appointed board (a board
# of adjustment). Real examples this list is built from, all seen live
# 2026-09-24: Campbell County KY's "Campbell County Cable Board" (the
# joint body that runs the channel itself, not the county government)
# and its "... Board of Adjustment" rows; Centre County C-NET's "Centre
# Area Transportation Authority (CATA)", "Centre Region Council of
# Governments", "Centre Regional Planning Commission (CRPC)" (a
# multi-town regional body, unlike an ordinary single-town planning
# commission), "Spring Creek Watershed Commission", "University Area
# Joint Authority"; North Metro TV's own "North Metro Telecommunications
# Commission" (the joint body of its member cities that runs the
# channel -- the same shape as Campbell County's Cable Board, and the
# second real wrong match Ryan's review caught: "North Metro" isn't a
# place at all, but a bare place-fragment extraction still found a real,
# wrong "North Township, MN" hiding inside it). These are recorded (a
# human can still read the section and pin it correctly) but NEVER
# auto-matched to a place name that merely appears in or near their own
# title.
_JOINT_OR_SPECIAL_BODY_RE = re.compile(
    r"\bcable (?:board|commission)\b"
    r"|\b(?:tele)?communications? (?:board|commission)\b"
    r"|\bunity council\b"
    r"|\bboard of adjustments?\b"
    r"|\bauthority\b"
    r"|\bjoint powers\b"
    r"|\bjoint authority\b"
    r"|\bregional\b.{0,40}\b(?:council|board|commission)\b"
    r"|\bcouncil of governments\b"
    r"|\bwatershed commission\b"
    r"|(?<!school )(?<!school-)\bdistrict\b"
    # WO-1074 addendum (Ryan, 2026-09-25): a police services board is a
    # separate, often multi-jurisdiction body, never the general
    # government it's hosted by/named after -- real example: Essex
    # County OPP (Ontario Provincial Police) Detachment Board, matched
    # to "Essex, ON" by name alone even though it's a policing board, not
    # Essex's own council. "Joint Meeting"/"Joint Hearing" (distinct from
    # "joint powers"/"joint authority" above, already a real body name
    # rather than a description of the meeting) is the same shape: two or
    # more governments meeting together, never just one.
    r"|\bpolice\b"
    r"|\bopp\b"
    r"|\bjoint\s+(?:meetings?|hearings?)\b",
    re.IGNORECASE,
)


def _is_joint_or_special_body(text: str) -> bool:
    return bool(_JOINT_OR_SPECIAL_BODY_RE.search(text or ""))


# 2. Strip generic meeting/body DESCRIPTOR words before extracting a
# place name -- but never a real place-TYPE word (County, Township,
# Borough, Village, City, Town), since the type word is part of the
# actual place identity ("Anoka County" is the government; "Anoka"
# alone is a DIFFERENT, real place -- a city inside that county). Every
# phrase here is a body/meeting descriptor, never a place-type word, so
# stripping it can only ever remove noise, never truncate a real name.
_TRAILING_DESCRIPTOR_RE = re.compile(
    r"[\s\-–,]*\b(?:"
    r"board of (?:supervisors|commissioners|trustees|adjustments?)"
    r"|commissioners court"
    r"|planning(?: and| &) zoning"
    r"|planning commission"
    r"|parks?(?: and| &) recreation"
    r"|park board"
    r"|environmental board"
    r"|work sessions?"
    r"|regular meetings?"
    r"|special meetings?"
    r"|school board"
    r"|board of education"
    r"|council"
    r"|commission"
    r"|board"
    r"|supervisors"
    r"|trustees"
    r"|aldermen"
    r"|meetings?"
    r")\s*$",
    re.IGNORECASE,
)

_DATE_LIKE_RE = re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b|\b(?:19|20)\d{2}\b")

# Real, confirmed generic policy-area/body-topic words that are NOT a
# place, even though one of them (Park) happens to collide with a real
# place name (Park Township, MN) -- confirmed live 2026-09-24 building
# this fix: North Metro TV's "Park Board Meetings" section, once its
# trailing "Board Meetings" descriptor is stripped, leaves the bare word
# "Park" -- and `resolve_government("Park, MN", ...)` genuinely matches
# a real township by that name, which is wrong here (the section's own
# newest meeting is a BLAINE Park Board meeting, not a meeting of Park
# Township's own government). A remainder made ENTIRELY of these words
# is treated as "no place named", not "the place happens to be called
# that", and the caller falls back to the section's own meeting titles.
_GENERIC_NON_PLACE_HEAD_WORDS = frozenset(
    {
        "park",
        "parks",
        "tree",
        "planning",
        "cable",
        "communications",
        "telecommunications",
        "environmental",
        "recreation",
        "zoning",
        "water",
        "library",
        "transportation",
        "adjustment",
        "adjustments",
        "work",
        "session",
        "sessions",
    }
)


def _extract_place_fragment(text: str) -> str:
    """The real place name inside `text`, once generic meeting/body
    descriptor words are stripped from the end -- or "" when nothing
    place-shaped is left (see the two module comments above for the
    real cases this distinguishes: "Anoka County Board Meetings" ->
    "Anoka County" keeps its real type word; "Park Board Meetings" ->
    "" because "Park" alone is a policy-area word here, not a place).
    Never called on a joint/special body -- callers check
    `_is_joint_or_special_body()` first."""
    if not text:
        return ""
    working = text
    while True:
        stripped = _TRAILING_DESCRIPTOR_RE.sub("", working)
        stripped = _DATE_LIKE_RE.sub(" ", stripped)
        stripped = re.sub(r"[\s\-–,]+$", "", stripped).strip()
        if stripped == working:
            break
        working = stripped
    working = re.sub(r"^(?:of|the|and)\b\s*", "", working, flags=re.IGNORECASE).strip()
    working = re.sub(r"\s+", " ", working)
    if not working:
        return ""
    tokens = re.findall(r"[a-z]+", working.lower())
    if tokens and all(t in _GENERIC_NON_PLACE_HEAD_WORDS for t in tokens):
        return ""
    return working


def _enforce_type_agreement(
    match: "resolver.GovernmentMatch", body_type_hint: str
) -> "resolver.GovernmentMatch":
    """WO-1074 addendum: `body_type_hint` (normalized via
    `normalize_body_type_word()`) says the title carried an EXPLICIT
    place-type word -- "Town of X", "X Township", "X County...". If the
    resolver's own match disagrees (a different real `gov_type`), that is
    not a low-confidence match to accept anyway -- it is evidence the
    match is simply WRONG (a same-named government of a different kind).
    Downgraded to `TIER_UNVERIFIED` (never a confident/registry match) so
    every caller's existing "confident only at TIER_PINNED/TIER_REGISTRY"
    check already routes it to hand-read, with no separate check needed
    at each call site. A hint this function doesn't recognize ("") or a
    match with no real gov_id (nothing to compare) is passed through
    unchanged."""
    expected = _EXPECTED_GOV_TYPES_BY_BODY_TYPE.get(body_type_hint)
    if (
        not expected
        or not match.gov_id
        or match.gov_type
        not in (
            classify.COUNTY,
            classify.MUNICIPALITY,
            classify.TOWNSHIP,
            classify.SCHOOL_DISTRICT,
        )
    ):
        return match
    if match.gov_type in expected:
        return match
    return _dc_replace(
        match,
        tier=resolver.TIER_UNVERIFIED,
        evidence=(
            f"title names a {body_type_hint!r}-type government, but the closest "
            f"name+state match ({match.gov_name!r}) is a {match.gov_type!r} -- "
            "kept for a human, not auto-matched"
        ),
    )


def _match_place_text(
    place_text: str,
    region_state: str,
    tenant_host: str,
    *,
    body_type_hint: str = "",
) -> "resolver.GovernmentMatch":
    """`body_type_hint` (WO-1060, optional): `_guessed_body_type()`'s own
    output for the section/title this place came from -- normalized via
    `normalize_body_type_word()` before use, so either this script's own
    vocabulary or `pick.py`'s `place_type` words work. Live-confirmed
    2026-09-25 (`us_school_districts.csv`): a bare county/place name plus
    state resolves to that COUNTY's general-purpose government by default
    ("nassau, FL" -> Nassau County, FL, `us_counties.csv`) even when the
    real body is its school district -- "nassau county school district,
    FL" resolves correctly, as a REGISTRY-tier hit, to the actual school
    district (Nassau County School District, FL). So when the hint says
    `school district` and `place_text` doesn't already spell that out,
    try the qualified form FIRST -- it is the more specific, more likely
    correct match whenever it resolves at all.

    WO-1074 addendum: whatever match is finally chosen, if `body_type_hint`
    names an explicit type word, the match's own `gov_type` must agree
    (`_enforce_type_agreement()`) -- otherwise it is downgraded to
    `TIER_UNVERIFIED` rather than trusted, however well the NAME matched.
    """
    body_type_hint = normalize_body_type_word(body_type_hint)
    if (
        body_type_hint == "school district"
        and "school district" not in (place_text or "").lower()
    ):
        qualified = f"{place_text} School District"
        qualified_match = resolver.resolve_government(
            f"{qualified}, {region_state}" if region_state else qualified,
            tenant_host=tenant_host,
        )
        if qualified_match.tier in (resolver.TIER_PINNED, resolver.TIER_REGISTRY):
            return _enforce_type_agreement(qualified_match, body_type_hint)
    raw_name = f"{place_text}, {region_state}" if region_state else place_text
    match = resolver.resolve_government(raw_name, tenant_host=tenant_host)
    if match.tier not in (resolver.TIER_PINNED, resolver.TIER_REGISTRY):
        # Same "Meeting" workaround `_resolver_candidate_text()` documents
        # -- a bare place+type fragment usually resolves directly (see
        # this WO's own live tests), but retry with it appended in case
        # this particular fragment still needs `finalize_jurisdiction()`'s
        # "...Meeting" repair rule to fire.
        retried = resolver.resolve_government(
            f"{_resolver_candidate_text(place_text)}, {region_state}"
            if region_state
            else _resolver_candidate_text(place_text),
            tenant_host=tenant_host,
        )
        if retried.tier in (resolver.TIER_PINNED, resolver.TIER_REGISTRY):
            return _enforce_type_agreement(retried, body_type_hint)
    return _enforce_type_agreement(match, body_type_hint)


def _consistent_place_from_titles(
    titles: List[str], region_state: str, tenant_host: str
) -> Tuple[str, Optional["resolver.GovernmentMatch"]]:
    """Ryan's fix (b): when the section's own name has no place in it
    (e.g. "Park Board Meetings"), read the section's own newest several
    meeting titles instead -- North Metro TV's real "Park Board
    Meetings" section's actual videos are named "Blaine Park Board
    Meeting ...", "Blaine Park Board ...", each naming the real city
    directly. Only returns a match when every title checked agrees on
    the same government id -- titles that disagree, or name no place at
    all, come back empty so the caller falls through to hand_read rather
    than guess between them."""
    matches = []
    for title in titles:
        if _is_joint_or_special_body(title):
            continue
        fragment = _extract_place_fragment(title)
        if not fragment:
            continue
        match = _match_place_text(fragment, region_state, tenant_host)
        if match.tier in (resolver.TIER_PINNED, resolver.TIER_REGISTRY):
            matches.append(match)
    if not matches:
        return "", None
    gov_ids = {m.gov_id for m in matches}
    if len(gov_ids) != 1:
        return "", None
    return matches[0].gov_name, matches[0]


@dataclass
class HubRow:
    hub: str
    platform: str
    url: str
    region_state: str
    notes: str


@dataclass
class SectionResult:
    hub: str
    section: str
    jurisdiction_text: str
    body_type: str
    newest_title: str
    newest_date: str
    newest_url: str
    matched_gov_id: str
    matched_gov_name: str
    confidence: str
    reason: str
    resolve_url: str = ""  # canonical URL to re-resolve for a real tier check


def load_hubs() -> List[HubRow]:
    with open(HUB_CSV, newline="", encoding="utf-8") as f:
        return [HubRow(**row) for row in csv.DictReader(f)]


async def _fetch_text(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            if response.status >= 400:
                return None
            return await response.text()
    except (aiohttp.ClientError, TimeoutError):
        return None


_REMIX_CONTEXT_RE = re.compile(
    r"window\.__remixContext\s*=\s*(\{.*?\});</script>", re.DOTALL
)


def _extract_remix_context(html: str) -> Optional[dict]:
    match = _REMIX_CONTEXT_RE.search(html)
    if not match:
        return None
    try:
        return json.loads(match.group(1))
    except (json.JSONDecodeError, ValueError):
        return None


def _find_all(obj: Any, predicate) -> List[dict]:
    results: List[dict] = []
    if isinstance(obj, dict):
        if predicate(obj):
            results.append(obj)
        for value in obj.values():
            results.extend(_find_all(value, predicate))
    elif isinstance(obj, list):
        for item in obj:
            results.extend(_find_all(item, predicate))
    return results


def _find_site_object(data: dict) -> Optional[dict]:
    hits = _find_all(data, lambda o: "siteId" in o and "pageDescription" in o)
    return hits[0] if hits else None


def _parse_show_date(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _newest_show(shows: List[dict]) -> Optional[dict]:
    ready = [s for s in shows if s.get("vodUrl")]
    pool = ready or shows
    if not pool:
        return None
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    return max(pool, key=lambda s: _parse_show_date(s.get("eventDate")) or epoch)


def _with_site_param(url: str, site_id: Any) -> str:
    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    query["site"] = [str(site_id)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


async def _harvest_cablecast_remix(
    session: aiohttp.ClientSession, hub: HubRow
) -> Tuple[List[SectionResult], Optional[str]]:
    """Walks a Cablecast Remix-template hub: `site.otherSites` (if any)
    lists every section/town on the host, and each section's own
    `site.galleries` are its per-body categories -- see
    `regional_tv_hubs.csv`'s own notes for the real examples this is
    built on (Iron Range TV has no otherSites at all, just galleries on
    one site; North Metro TV and Harbor Media have several sites each
    with their own galleries)."""
    html = await _fetch_text(session, hub.url)
    if html is None:
        return [], "fetch_failed"
    data = _extract_remix_context(html)
    if data is None:
        return [], "no_remix_context_found"
    site = _find_site_object(data)
    if site is None:
        return [], "no_site_object_found"

    other_sites = site.get("otherSites") or [site]
    seen_ids: set = set()
    sections: List[SectionResult] = []
    for other in other_sites:
        site_id = other.get("siteId")
        if site_id in seen_ids:
            continue
        seen_ids.add(site_id)

        if site_id == site.get("siteId"):
            site_data = data
        else:
            await asyncio.sleep(POLITE_DELAY_SECONDS)
            site_url = _with_site_param(hub.url, site_id)
            site_html = await _fetch_text(session, site_url)
            site_data = _extract_remix_context(site_html) if site_html else None
        if site_data is None:
            sections.append(
                _section(
                    hub,
                    section=other.get("title") or f"site {site_id}",
                    reason="site_fetch_failed",
                )
            )
            continue

        # De-duplicated by cablecastGalleryId -- confirmed live 2026-09-24
        # that the same gallery object appears more than once in one
        # page's remix tree (e.g. both a nav-menu copy and a home-content
        # copy), the same real shape `_resolve_gallery()`'s own docstring
        # in cablecast.py warns about for "any show-shaped object
        # anywhere on the page". Walking the whole tree without this
        # produced the same "Anoka County Board Meetings" section (and
        # its ingest-queue row) six times over on North Metro TV.
        seen_gallery_ids: set = set()
        galleries = []
        for gallery in _find_all(site_data, lambda o: "cablecastGalleryId" in o):
            gallery_id = gallery.get("cablecastGalleryId")
            if gallery_id in seen_gallery_ids:
                continue
            seen_gallery_ids.add(gallery_id)
            galleries.append(gallery)
        site_title = other.get("title") or ""
        if not galleries:
            sections.append(_build_matched_section(hub, site_title, site_title, []))
            continue
        for gallery in galleries:
            sections.append(
                _build_matched_section(
                    hub,
                    gallery.get("title") or "",
                    site_title,
                    gallery.get("shows") or [],
                )
            )
    return sections, None


def _canonical_cablecast_show_url(hub_url: str, show: dict) -> Optional[str]:
    show_id = show.get("showId")
    if show_id is None:
        return None
    parsed = urlparse(hub_url)
    return f"{parsed.scheme}://{parsed.netloc}/internetchannel/show/{show_id}"


def _build_matched_section(
    hub: HubRow, section_name: str, site_title: str, shows: List[dict]
) -> SectionResult:
    """Matches one gallery/section to a government -- see the two module
    comments above `_JOINT_OR_SPECIAL_BODY_RE` and `_extract_place_
    fragment()` for the two real wrong-match bugs (Ryan, 2026-09-24) this
    logic exists to avoid, and `_consistent_place_from_titles()`'s own
    docstring for the meeting-titles fallback (fix b)."""
    newest = _newest_show(shows) if shows else None
    result = _section(
        hub,
        section=section_name or site_title,
        newest_title=(newest or {}).get("title") or "",
        newest_date=(newest or {}).get("eventDate") or "",
        newest_url=(newest or {}).get("vodUrl") or "",
        resolve_url=_canonical_cablecast_show_url(hub.url, newest) if newest else "",
    )
    tenant_host = urlparse(hub.url).netloc

    if _is_joint_or_special_body(section_name) or _is_joint_or_special_body(site_title):
        result.jurisdiction_text = section_name
        result.reason = (
            "joint/special body (cable/communications board, authority, "
            "watershed/regional/COG body, board of adjustment, or "
            "non-school district) -- never auto-matched to the county/town "
            "it is named after or hosted by; needs a human to confirm which "
            "government, if any, this belongs to"
        )
        return result

    if not _looks_like_a_government_body(
        section_name
    ) and not _looks_like_a_government_body(site_title):
        result.reason = "section title does not name a governing body"
        return result

    body_text = (
        section_name if _looks_like_a_government_body(section_name) else site_title
    )
    place_fragment = _extract_place_fragment(body_text)

    if place_fragment:
        match = _match_place_text(place_fragment, hub.region_state, tenant_host)
        result.jurisdiction_text = place_fragment
        result.body_type = _guessed_body_type(body_text)
        result.matched_gov_id = match.gov_id or ""
        result.matched_gov_name = match.gov_name or ""
        if match.tier in (resolver.TIER_PINNED, resolver.TIER_REGISTRY):
            result.confidence = "confident"
            result.reason = f"exact name+state+type match ({match.tier})"
        else:
            result.confidence = "hand_read"
            result.reason = f"resolver tier={match.tier}: {match.evidence}"
        return result

    # No place in the section's own name (e.g. "Park Board Meetings") --
    # fix (b): read the section's own newest several meeting titles
    # instead. Newest-first, capped at 5 -- enough to catch a
    # consistently-named real place without walking a whole gallery.
    titles_by_date = sorted(
        (s for s in shows if s.get("title")),
        key=lambda s: (
            _parse_show_date(s.get("eventDate"))
            or datetime.min.replace(tzinfo=timezone.utc)
        ),
        reverse=True,
    )
    candidate_titles = [s["title"] for s in titles_by_date[:5]]
    gov_name, match = _consistent_place_from_titles(
        candidate_titles, hub.region_state, tenant_host
    )
    if match:
        result.jurisdiction_text = gov_name
        result.body_type = _guessed_body_type(body_text)
        result.matched_gov_id = match.gov_id or ""
        result.matched_gov_name = match.gov_name or ""
        result.confidence = "confident"
        result.reason = (
            "no place in the section's own title -- matched from its "
            f"newest meeting titles agreeing on one government ({match.tier})"
        )
    else:
        result.reason = (
            "no place in the section's own title, and its newest meeting "
            "titles disagree or name none -- needs a human"
        )
    return result


def _section(hub: HubRow, section: str, **kwargs) -> SectionResult:
    defaults = dict(
        hub=hub.hub,
        section=section,
        jurisdiction_text="",
        body_type="",
        newest_title="",
        newest_date="",
        newest_url="",
        matched_gov_id="",
        matched_gov_name="",
        confidence="hand_read",
        reason="",
        resolve_url="",
    )
    defaults.update(kwargs)
    return SectionResult(**defaults)


# TelVue's own `/home` page (see telvue.py's `list_playlist_items` module
# note) renders one card per playlist -- title, "(N Videos)", and a link
# straight to that playlist's newest media item. Confirmed live 2026-09-24
# on Centre County C-NET's real org token (see regional_tv_hubs.csv).
_TELVUE_CARD_RE = re.compile(
    r'<a href="(/player/[^/]+/playlists/\d+/media/\d+)">.*?'
    r'<span class="h4 title block">([^<]*)</span>',
    re.DOTALL,
)


async def _harvest_telvue(
    session: aiohttp.ClientSession, hub: HubRow
) -> Tuple[List[SectionResult], Optional[str]]:
    html = await _fetch_text(session, hub.url)
    if html is None:
        return [], "fetch_failed"
    parsed = urlparse(hub.url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    sections: List[SectionResult] = []
    for path, title in _TELVUE_CARD_RE.findall(html):
        title = title.strip()
        section = _section(
            hub,
            section=title,
            newest_url=urljoin(origin, path),
            resolve_url=urljoin(origin, path),
        )
        if _is_joint_or_special_body(title):
            section.jurisdiction_text = title
            section.reason = (
                "joint/special body (cable/communications board, authority, "
                "watershed/regional/COG body, board of adjustment, or "
                "non-school district) -- never auto-matched; needs a human"
            )
        elif not _looks_like_a_government_body(title):
            section.reason = "section title does not name a governing body"
        else:
            place_fragment = _extract_place_fragment(title)
            if not place_fragment:
                # TelVue's own `/home` page gives one card per playlist
                # with no other video titles to fall back on (fix (b)'s
                # multi-title check needs `list_playlist_items()`, an
                # extra fetch per playlist this pass doesn't make) --
                # recorded for a human rather than guessed.
                section.jurisdiction_text = title
                section.reason = (
                    "no place in this playlist's own title, and TelVue's "
                    "/home page doesn't list its other video titles to "
                    "check -- needs a human"
                )
            else:
                match = _match_place_text(
                    place_fragment, hub.region_state, parsed.netloc
                )
                section.jurisdiction_text = place_fragment
                section.body_type = _guessed_body_type(title)
                section.matched_gov_id = match.gov_id or ""
                section.matched_gov_name = match.gov_name or ""
                if match.tier in (resolver.TIER_PINNED, resolver.TIER_REGISTRY):
                    section.confidence = "confident"
                    section.reason = f"exact name+state+type match ({match.tier})"
                else:
                    section.confidence = "hand_read"
                    section.reason = f"resolver tier={match.tier}: {match.evidence}"
        sections.append(section)
    return sections, None


# CablecastPublicSite (TVCTV): confirmed live 2026-09-24 that its own show
# API has no per-site/per-category filter that actually narrows the
# 24,000+-show shared catalog (see regional_tv_hubs.csv's own note) --
# recorded as hand-read leads only, one per known site id, no newest-show
# claim made for any of them.
_TVCTV_SITES = (
    ("1", "Our Channels site 1"),
    ("2", "Our Channels site 2"),
    ("3", "Our Channels site 3"),
    ("5", "Our Channels site 5"),
    ("6", "Government site 6"),
    ("7", "Government site 7"),
)


async def _harvest_cablecast_publicsite(
    session: aiohttp.ClientSession, hub: HubRow
) -> Tuple[List[SectionResult], Optional[str]]:
    del session  # no fetch is trusted enough yet -- see module note above
    sections = [
        _section(
            hub,
            section=label,
            newest_url=_with_site_param(hub.url, site_id),
            reason=(
                "CablecastPublicSite per-site/category show listing is not "
                "confirmed yet -- recorded as a lead only, see "
                "regional_tv_hubs.csv"
            ),
        )
        for site_id, label in _TVCTV_SITES
    ]
    return sections, None


# Pierce County TV: YOUTUBE-DRIP-ONLY. This never fetches piercecountytv's
# YouTube channel or any youtube.com URL at all -- the section list below
# is the real, confirmed (2026-09-24) result of reading the site's own
# non-YouTube navigation (see regional_tv_hubs.csv's note), hardcoded here
# rather than re-fetched every run so this function makes zero network
# requests of its own kind that could ever touch YouTube.
_PIERCE_COUNTY_SECTIONS = (
    ("City of DuPont", "https://www.piercecountytv.org/91/City-of-DuPont"),
    ("City of Fife", "https://www.piercecountytv.org/94/City-of-Fife"),
    ("City of Orting", "https://www.piercecountytv.org/97/City-of-Orting"),
    (
        "Pierce County Council",
        "https://www.piercecountytv.org/100/Pierce-County-Council",
    ),
    ("City of Puyallup", "https://www.piercecountytv.org/103/City-of-Puyallup"),
    (
        "Rainier Communications Commission",
        "https://www.piercecountytv.org/106/Rainier-Communications-Commission",
    ),
    ("City of Sumner", "https://www.piercecountytv.org/108/City-of-Sumner"),
    (
        "City of University Place",
        "https://www.piercecountytv.org/111/City-of-University-Place",
    ),
    (
        "Tacoma-Pierce County Health Department",
        "https://www.piercecountytv.org/1317/Tacoma-Pierce-County-Health-Department",
    ),
)


async def _harvest_youtube_hub(
    session: aiohttp.ClientSession, hub: HubRow
) -> Tuple[List[SectionResult], Optional[str]]:
    del session  # deliberately unused -- see module note above
    sections = []
    for name, url in _PIERCE_COUNTY_SECTIONS:
        section = _section(
            hub,
            section=name,
            newest_url=url,
            reason=(
                "YouTube-drip-only hub: never fetched here. This is a "
                "confirmed per-government section page, not a video -- "
                "the newest meeting still needs the drip Mac to check "
                "the channel."
            ),
        )
        text = name
        raw_name = (
            f"{_resolver_candidate_text(text)}, {hub.region_state}"
            if hub.region_state
            else _resolver_candidate_text(text)
        )
        match = resolver.resolve_government(
            raw_name, tenant_host=urlparse(hub.url).netloc
        )
        section.jurisdiction_text = text
        section.matched_gov_id = match.gov_id or ""
        section.matched_gov_name = match.gov_name or ""
        if match.tier in (resolver.TIER_PINNED, resolver.TIER_REGISTRY):
            section.confidence = "confident_no_video_yet"
        else:
            section.confidence = "hand_read"
        sections.append(section)
    return sections, None


async def _harvest_vimeo_channel(
    session: aiohttp.ClientSession, hub: HubRow
) -> Tuple[List[SectionResult], Optional[str]]:
    """A single-government Vimeo channel (Montague, MA) -- no per-town
    section to walk, so this records exactly one section: the hub's own
    name against its `region_state`. Vimeo's own newest-video listing API
    needs an authenticated call this pass doesn't have, so `newest_*`
    fields are left blank rather than guessed (this hub's town-video
    resolve already goes through `app/platforms/vimeo.py`'s own headless
    path when a real URL is in hand -- out of scope here)."""
    del session
    text = hub.hub.replace("Community Television", "").strip()
    raw_name = (
        f"{_resolver_candidate_text(text)}, {hub.region_state}"
        if hub.region_state
        else _resolver_candidate_text(text)
    )
    match = resolver.resolve_government(raw_name, tenant_host=urlparse(hub.url).netloc)
    section = _section(
        hub,
        section=hub.hub,
        jurisdiction_text=text,
        newest_url=hub.url,
        matched_gov_id=match.gov_id or "",
        matched_gov_name=match.gov_name or "",
        reason="single-government Vimeo channel; newest video not fetched this pass",
    )
    section.confidence = (
        "confident_no_video_yet"
        if match.tier in (resolver.TIER_PINNED, resolver.TIER_REGISTRY)
        else "hand_read"
    )
    return [section], None


_HARVESTERS = {
    "cablecast_remix": _harvest_cablecast_remix,
    "telvue": _harvest_telvue,
    "cablecast_publicsite": _harvest_cablecast_publicsite,
    "youtube_hub": _harvest_youtube_hub,
    "vimeo": _harvest_vimeo_channel,
}


async def _resolve_tier(section: SectionResult, platform: str) -> str:
    """A real (read-only) adapter `resolve()` call against the section's
    own canonical show URL, used only to report a caption tier for the
    ingest-queue plan -- never writes anything. Never called for a
    YouTube-hosted section (Pierce County TV is filtered out by the
    caller before this runs)."""
    if not section.resolve_url:
        return "unknown"
    try:
        if platform in ("cablecast_remix",):
            result = await CablecastAssetFinder().resolve(section.resolve_url)
        elif platform == "telvue":
            result = await TelvueAssetFinder().resolve(section.resolve_url)
        else:
            return "unknown"
    except Exception as exc:  # noqa: BLE001 -- dry run: never crash the pass
        return f"resolve_error: {exc}"
    if result.segments:
        return "tier1_captions"
    if result.video_url:
        return "tier3_video_only"
    return "no_video"


def _dedupe_sections(sections: List[SectionResult]) -> List[SectionResult]:
    """A shared body (e.g. a county board) can legitimately appear as its
    own identical gallery on EVERY member city's own site page within one
    hub -- confirmed live 2026-09-24 on North Metro TV: "Anoka County
    Board Meetings" is a real gallery embedded on each of its 7 city
    sites, not a parsing bug (the per-page duplicate GALLERY-object copy
    bug is separate and is fixed where the galleries are read, see that
    comment). This collapses same-hub repeats of the exact same section
    name + newest video down to one row, so the reports (and the ingest
    queue) count each real government/section once, not once per site it
    happens to be syndicated onto."""
    seen: set = set()
    deduped = []
    for section in sections:
        key = (section.section, section.newest_url, section.matched_gov_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(section)
    return deduped


async def run(out_dir: Path) -> Dict[str, List[SectionResult]]:
    install_youtube_guard()
    hubs = load_hubs()
    by_hub: Dict[str, List[SectionResult]] = {}
    async with aiohttp.ClientSession(headers=HEADERS) as session:
        for hub in hubs:
            harvester = _HARVESTERS.get(hub.platform)
            if harvester is None:
                by_hub[hub.hub] = [
                    _section(
                        hub,
                        section="(hub)",
                        reason=f"unknown platform {hub.platform!r}",
                    )
                ]
                continue
            sections, hub_error = await harvester(session, hub)
            if hub_error:
                sections = [_section(hub, section="(hub)", reason=hub_error)]
            by_hub[hub.hub] = _dedupe_sections(sections)
            await asyncio.sleep(POLITE_DELAY_SECONDS)

    out_dir.mkdir(parents=True, exist_ok=True)
    all_sections = [s for rows in by_hub.values() for s in rows]

    with open(out_dir / "hub_sections.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "hub",
                "section",
                "jurisdiction_text",
                "body_type",
                "newest_title",
                "newest_date",
                "newest_url",
                "matched_gov_id",
                "matched_gov_name",
                "confidence",
                "reason",
            ]
        )
        for s in all_sections:
            writer.writerow(
                [
                    s.hub,
                    s.section,
                    s.jurisdiction_text,
                    s.body_type,
                    s.newest_title,
                    s.newest_date,
                    s.newest_url,
                    s.matched_gov_id,
                    s.matched_gov_name,
                    s.confidence,
                    s.reason,
                ]
            )

    confident = [
        s for s in all_sections if s.confidence == "confident" and s.resolve_url
    ]
    with open(
        out_dir / "ingest_queue_plan.csv", "w", newline="", encoding="utf-8"
    ) as f:
        writer = csv.writer(f)
        writer.writerow(["url", "source", "gov_id", "gov_name", "tier"])
        hub_platform = {h.hub: h.platform for h in hubs}
        for s in confident:
            tier = await _resolve_tier(s, hub_platform.get(s.hub, ""))
            writer.writerow(
                [s.resolve_url, s.hub, s.matched_gov_id, s.matched_gov_name, tier]
            )
            await asyncio.sleep(POLITE_DELAY_SECONDS)

    hand_read = [s for s in all_sections if s.confidence != "confident"]
    with open(out_dir / "hand_read.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "hub",
                "section",
                "jurisdiction_text",
                "newest_url",
                "matched_gov_id",
                "matched_gov_name",
                "confidence",
                "reason",
            ]
        )
        for s in hand_read:
            writer.writerow(
                [
                    s.hub,
                    s.section,
                    s.jurisdiction_text,
                    s.newest_url,
                    s.matched_gov_id,
                    s.matched_gov_name,
                    s.confidence,
                    s.reason,
                ]
            )

    return by_hub


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="output directory for the 3 CSVs")
    args = parser.parse_args()
    by_hub = asyncio.run(run(Path(args.out)))
    for hub_name, sections in by_hub.items():
        confident = sum(1 for s in sections if s.confidence == "confident")
        print(
            f"{hub_name}: {len(sections)} section(s), {confident} confident match(es)"
        )


if __name__ == "__main__":
    main()
