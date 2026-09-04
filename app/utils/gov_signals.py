"""`extract_gov_signals()` -- Phase 2d ("signal scoring") of
`rtr-business/research/GOVERNMENT_IDENTITY_ARCHITECTURE.md`, WO-105.

The adapter boundary discards the page: `ResolvedMeeting`
(`app/platforms/models.py`) carries `jurisdiction`, `meeting_body`,
`meeting_location`, `title`, `date` -- nothing else the source page said
about which government this is. This module reads a fetched page's raw
HTML/text and pulls out every candidate signal about country, province/
state, government type, canonical name, and meeting kind that the page
carries but that never reaches `ResolvedMeeting` today.

It is a pure function: no I/O, no network, no writes, no database --
same contract as `app/utils/gov_registry/resolver.py`'s own docstring
("Nothing here writes anything, touches a database, or performs a
fetch"). `scripts/score_gov_signals.py` is the one caller that performs
the actual fetch and hands the result in here.

**It reports; it does not decide.** Every returned signal is a raw
candidate for `resolve_government()` (or a human) to weigh -- this
module makes no resolution decision of its own, the same discipline
`gov_registry` already draws between extraction and resolution.

**Import boundary, deliberate**: this module imports from
`app.utils.jurisdiction_enrich` (the same enricher `gov_registry.resolver`
calls into) but NOT from `app.utils.gov_registry` -- that package's own
docstring declares a one-way dependency ("this package imports ...
`app.utils.jurisdiction_enrich` -- and nothing else from this repo"), so
a signals module reusing `jurisdiction_enrich`'s extractors sits
alongside `gov_registry`, not inside or beneath it, and there is no
import cycle: `gov_registry` never imports this module, and this module
never imports `gov_registry`.
"""

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from .jurisdiction_enrich import (
    _capitalization_walk_extract,
    _stoprule_extract,
    find_zip_addresses,
    validated_subdomain_extract,
)

# Canada Post's real format: letter-digit-letter, digit-letter-digit
# ("A1A 1A1"). D, F, I, O, Q, U are never used in ANY position (avoid
# confusion with digits/other letters); W and Z are additionally never
# used in the FIRST position -- Canada Post's own public documentation,
# and the same 18-letter first-position set architecture doc §2d's brief
# names for the province mapping (A=NL, B=NS, C=PE, E=NB, G/H/J=QC,
# K/L/M/N/P=ON, R=MB, S=SK, T=AB, V=BC, X=NT/NU, Y=YT). This is an
# EXTRACTION pattern only -- it finds postal-code-SHAPED strings; mapping
# the first letter to a province, and validating that mapping against the
# page's own government name, is `resolve_government()`'s job (WO-105),
# not this module's.
_CA_POSTAL_LETTERS = "ABCEGHJKLMNPRSTVWXYZ"
_CA_POSTAL_FIRST_LETTERS = "ABCEGHJKLMNPRSTVXY"
_CA_POSTAL_RE = re.compile(
    rf"\b([{_CA_POSTAL_FIRST_LETTERS}]\d[{_CA_POSTAL_LETTERS}])[ -]?"
    rf"(\d[{_CA_POSTAL_LETTERS}]\d)\b"
)

# Government-BODY / meeting-body type words a page names directly --
# distinct from `resolver.py`'s widened municipal-prefix words (Village
# of/Township of/etc, which name the GOVERNMENT), these name the BODY
# that meets within it. "Board of Education"/"Board of Trustees" also
# double as school-district evidence; "Regional District" is the BC
# special-purpose regional-government term (distinct from the Ontario
# "Regional Municipality" the resolver's widened type words already
# catch).
_TYPE_WORDS = (
    "Board of Education",
    "Board of Trustees",
    "Board of Directors",
    "Board of Supervisors",
    "Superintendent",
    "Regional District",
    # The same municipal-prefix widening `resolver._LEADING_TYPE_RE`/
    # `jurisdiction_enrich._STOPRULE_TRIGGER_RE` gained this pass --
    # listed again here as bare TYPE WORDS (not "<word> of") since a page
    # can carry one without the "of X" continuation ever appearing in the
    # same sentence a signal-scoring pass looks at (e.g. a nav-bar label
    # "Village Council" with the government's own name elsewhere).
    "Village",
    "Borough",
    "Township",
    "Municipality",
    "Regional Municipality",
)

# Meeting-KIND words from a title -- D2a's `meeting_kind` field
# (`meeting`/`press_conference`/`public_statement`/`town_hall`/
# `workshop`/`hearing`), read directly from title text. Step A only
# EXTRACTS the candidate word; deciding the `meeting_kind` value from it
# is Step B (the brief's own explicit non-goal for this pass -- no
# `meeting_kind` writer here).
_TITLE_KIND_WORDS = (
    "Press Conference",
    "Town Hall",
    "Study Session",
    "Workshop",
    "Special Meeting",
)

_BYLAW_RE = re.compile(r"\bbylaw\b", re.IGNORECASE)
_ORDINANCE_RE = re.compile(r"\bordinance\b", re.IGNORECASE)


def _field(resolved: Any, name: str) -> Optional[str]:
    """Read `name` off `resolved`, which may be a `ResolvedMeeting`, a
    plain namespace, or a dict -- Step A's caller builds it from stored
    Archive export fields, not a live adapter resolve, so it is never
    assumed to be one specific type."""
    if resolved is None:
        return None
    if isinstance(resolved, dict):
        return resolved.get(name)
    return getattr(resolved, name, None)


def _tld(url: Optional[str]) -> str:
    """The last one or two DNS labels of `url`'s host, e.g. "granicus.com"
    or "on.ca" -- enough to distinguish a `.ca`/`.gov`/`.on.ca` shape
    without a full public-suffix-list dependency, which this module
    deliberately does not take on for a single coarse country signal
    (`resolve_government()`'s own consumption of this can also read the
    FULL netloc when a finer cut matters, e.g. a `.on.ca`/`.gov` decision
    -- this field is the coarse, general-purpose cut)."""
    if not url:
        return ""
    host = urlparse(url if "//" in url else f"//{url}").netloc.lower().split(":")[0]
    if not host:
        return ""
    labels = host.split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def _dedupe(values: List[str]) -> List[str]:
    seen = set()
    out = []
    for v in values:
        key = v.strip().lower()
        if v.strip() and key not in seen:
            seen.add(key)
            out.append(v.strip())
    return out


def extract_gov_signals(
    html: str, page_text: str, url: str, resolved: Any = None
) -> Dict[str, Any]:
    """Every government-identity SIGNAL a fetched page carries, as a
    plain dict. Pure: no I/O, no network, no writes. See module
    docstring for the full contract.

    `resolved` supplies whatever the caller already has about this page
    (title, stored jurisdiction/meeting_body/meeting_location) -- Step
    A's caller (`scripts/score_gov_signals.py`) builds a lightweight
    stand-in from Archive export rows, since it never runs an adapter or
    holds a live `ResolvedMeeting`; a real `ResolvedMeeting` works
    identically via `getattr()`.

    Every list-valued key defaults to `[]`; every other key defaults to
    `None`/`""`. Nothing here is validated or resolved -- see the module
    docstring's "it reports; it does not decide."
    """
    html = html or ""
    page_text = page_text or ""
    title = _field(resolved, "title") or ""

    org_names: List[Dict[str, str]] = []
    stoprule_hit = _stoprule_extract(page_text)
    if stoprule_hit:
        org_names.append({"value": stoprule_hit, "rule": "stoprule"})
    walk_hit = _capitalization_walk_extract(html)
    if walk_hit and walk_hit.lower() != (stoprule_hit or "").lower():
        org_names.append({"value": walk_hit, "rule": "capitalization_walk"})
    subdomain_hit = validated_subdomain_extract(url) if url else None
    if subdomain_hit:
        org_names.append({"value": subdomain_hit, "rule": "validated_subdomain"})
    # The payload's own `meeting_body`/`jurisdiction` are real signal too
    # -- `resolve_government()` never receives `meeting_body` as an input
    # today (the brief's own premise) -- carried through here so a caller
    # scoring against `extract_gov_signals()` alone still sees them
    # alongside what the fresh HTML fetch found.
    stored_jurisdiction = _field(resolved, "jurisdiction")
    if stored_jurisdiction:
        org_names.append({"value": stored_jurisdiction, "rule": "stored_jurisdiction"})

    type_words = [
        w for w in _TYPE_WORDS if re.search(rf"\b{re.escape(w)}\b", page_text, re.I)
    ]

    body_names: List[str] = []
    stored_body = _field(resolved, "meeting_body")
    if stored_body:
        body_names.append(stored_body)

    postal_codes = _dedupe(
        [
            f"{m.group(1)} {m.group(2)}".upper()
            for m in _CA_POSTAL_RE.finditer(page_text)
        ]
    )
    zip_codes = _dedupe([z for _city, _state, z in find_zip_addresses(page_text)])

    title_kind_words = [w for w in _TITLE_KIND_WORDS if w.lower() in title.lower()]

    country_words = []
    if _BYLAW_RE.search(page_text):
        country_words.append("bylaw")
    if _ORDINANCE_RE.search(page_text):
        country_words.append("ordinance")

    meeting_location = _field(resolved, "meeting_location")

    return {
        "org_names": org_names,
        "type_words": _dedupe(type_words),
        "body_names": _dedupe(body_names),
        "postal_codes": postal_codes,
        "zip_codes": zip_codes,
        "tld": _tld(url),
        # Only ever populated when the caller's own fetch already
        # surfaced one (a Granicus RSS/channel title) -- Step A's plain
        # HTML fetch has no RSS feed to read, so this is "" for every
        # Step A row today. Left as a real, named field (not omitted) so
        # a future caller that DOES have one (e.g. a Granicus channel
        # fetch) has somewhere to put it without a schema change here.
        "rss_title": "",
        "title_kind_words": _dedupe(title_kind_words),
        # No page-language detector exists in this repo outside caption
        # language detection (`transcript_language`, a property of the
        # CAPTION track, not the page). Adding one is a new dependency
        # this pass declines rather than guesses at -- left None, not a
        # wrong "en" default.
        "language": None,
        "meeting_location": meeting_location,
        "country_words": country_words,
    }
