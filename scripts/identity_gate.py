"""WO-932: pure identity checks shared by the ingest sweeps.

Two checks live here, both pure (no network, no `.env`, no `aiohttp`), so a
test can import them cheaply and every sweep can import them without the
circular imports the sweep scripts have between each other.

1. `jurisdiction_check_hook()` -- WO-149's hook, moved here so that
   `scripts/wo134_confirmed_hits_ingest.py` can install it BY DEFAULT.
   Before WO-932 it was opt-in: a wrapper script that installed neither this
   hook nor `IDENTITY_CHECK_HOOK` filed pages under the research row's
   `gov_id` with no check at all, and the Archive treats a caller-supplied
   `gov_id` as a pin that only has to exist in the registry
   (`archive/db/crud.py` `_caller_pinned_match()`). WO-913's first ingest
   batch was such a wrapper (found 2026-09-20). Two things changed in the
   move, and nothing else:
     - The hook is the same function WO-149 wrote; `wo149_county_ladder_sweep`
       re-exports it so every existing import keeps working.
     - A bare two-letter WORD is no longer read as a state code. The old scan
       upper-cased the whole guess first, so "in" in "Lake in the Hills", "or"
       in "Truth or Consequences", "de" in "Ponce de Leon" and "la" in
       "Portage la Prairie" all read as Indiana, Oregon, Delaware and
       Louisiana and would have rejected a real government's meetings. That
       is the same bug WO-280 fixed in wo146's scan (see BACKLOG_DONE.md); it
       stayed harmless here only while the hook was opt-in. Now a code counts
       only after a comma, or as a standalone UPPER-CASE token in text that is
       not itself all upper-case.

2. `host_name_conflict()` -- the check the "wrong-government checks never
   look at the resolved video's own host name" entry asked for. Every other
   check reads the resolved page's TITLE, jurisdiction or meeting body. None
   compared the HOST the video was found on with the government's name, so a
   real playable video on a different, same-state entity's tenant passed:
   Beltrami city, MN resolved to `minnesotapuc.granicus.com`, a 2013 Minnesota
   Public Utilities Commission hearing (WO-190, 2026-09-11). It returns a
   REVIEW reason, never a verdict: callers record it and keep going. The
   entry's own constraint says a false positive here silently drops a real
   shared regional media consortium's meetings (Shorewood city, MN's real
   `reflect-lmcc.cablecast.tv` clip has no name overlap at all and is
   legitimate), so it ships as a flag first.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from app.utils.gov_registry.registry import government_for_id

# --- 1. jurisdiction force-and-verify hook (moved from WO-149) -----------

# The 50 US states -- unchanged from WO-149. A Canadian province is not in
# this set on purpose: no real example of a province-suffixed adapter guess
# on a US row has been found (WO-145's four Cornwall/Erin/Clarington/
# Pickering collisions all came back with NO code at all), so widening it
# would be built from assumption. The blank-code cross-border case is
# `wo145_api_first_sweep._cross_border_collision()`'s job.
_STATE_ABBRS = frozenset(
    {
        "AL",
        "AK",
        "AZ",
        "AR",
        "CA",
        "CO",
        "CT",
        "DE",
        "FL",
        "GA",
        "HI",
        "ID",
        "IL",
        "IN",
        "IA",
        "KS",
        "KY",
        "LA",
        "ME",
        "MD",
        "MA",
        "MI",
        "MN",
        "MS",
        "MO",
        "MT",
        "NE",
        "NV",
        "NH",
        "NJ",
        "NM",
        "NY",
        "NC",
        "ND",
        "OH",
        "OK",
        "OR",
        "PA",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VT",
        "VA",
        "WA",
        "WV",
        "WI",
        "WY",
    }
)

_COMMA_CODE_RE = re.compile(r",\s*([A-Za-z]{2})\b")
_BARE_UPPER_CODE_RE = re.compile(r"(?<![A-Za-z])([A-Z]{2})(?![A-Za-z])")


def state_codes_in(guess: str) -> list:
    """The US state codes an adapter's jurisdiction guess really names.

    A code counts when it directly follows a comma ("Charleston, WV") in any
    case, or when it is a standalone UPPER-CASE token ("Charleston WV
    Recreation Commission") in a guess that is not itself all upper-case. A
    lower-case or title-case two-letter word never counts, so "Lake in the
    Hills" does not name Indiana. In an all-upper-case guess only the comma
    form counts, since every word there looks like a code.
    """
    guess = guess or ""
    found = [
        m.group(1).upper()
        for m in _COMMA_CODE_RE.finditer(guess)
        if m.group(1).upper() in _STATE_ABBRS
    ]
    letters = [c for c in guess if c.isalpha()]
    all_upper = bool(letters) and all(c.isupper() for c in letters)
    if not all_upper:
        found += [
            m.group(1)
            for m in _BARE_UPPER_CODE_RE.finditer(guess)
            if m.group(1) in _STATE_ABBRS
        ]
    # "Charleston, WV" matches both shapes; report each code once, in order.
    return list(dict.fromkeys(found))


def jurisdiction_check_hook(
    result, gov_id: str, unit_name: str, platform: str, final_seed: str
) -> Tuple[bool, str]:
    """`wo134.JURISDICTION_CHECK_HOOK` signature. Rejects a hit whose
    adapter jurisdiction guess names a different state than the registry row
    for `gov_id`, otherwise forces the exact registry name onto the result.

    It catches a wrong STATE only. A same-state mismatch (a town filed under
    its county's site) passes; that is the host-name flag's job, and the
    research-file hand-checks'.
    """
    expected_state = ""
    gov = government_for_id(gov_id)
    if gov and gov.state:
        expected_state = gov.state.strip().upper()

    guess = (result.jurisdiction or "").strip()
    if guess and expected_state:
        found_states = state_codes_in(guess)
        if found_states and expected_state not in found_states:
            return False, (
                f"wrong-domain-mapping: adapter jurisdiction guess {guess!r} "
                f"names {found_states[0]}, expected {expected_state} "
                f"(gov_id={gov_id}, seed={final_seed})"
            )

    # Compatible (or no signal either way) -- force the exact registry
    # name, wo130_county_ingest.py's pattern, so gov_id resolves
    # server-side to THIS county rather than drifting to rtr:unknown or a
    # same-named place.
    result.jurisdiction = unit_name
    return True, ""


# --- 2. the host's own name against the government's name ----------------

# A vendor domain that hosts one government per SUBDOMAIN, longest suffix
# first so `.portal.civicclerk.com` wins over `.civicclerk.com`. The label
# just before the suffix is the tenant's own name. Path-based tenants
# (`go.boarddocs.com/ca/xyz`, `clerkshq.com/Town-ST`) and shared video hosts
# (YouTube, Vimeo) are deliberately absent: the host says nothing about the
# government there.
_TENANT_SUFFIXES = (
    ".portal.civicclerk.com",
    ".civicclerk.com",
    ".granicus.com",
    ".escribemeetings.com",
    ".legistar.com",
    ".primegov.com",
    ".civicweb.net",
    ".diligent.community",
    ".swagit.com",
    ".iqm2.com",
    ".cablecast.tv",
    ".castus.tv",
    ".viebit.com",
    ".telvue.com",
    ".champds.com",
    ".destinyhosted.com",
    ".municodemeetings.com",
    ".hosted.civiclive.com",
    ".hosted2.civiclive.com",
    ".civicplus.com",
)

# Labels that are the vendor's own infrastructure, not a tenant.
_NON_TENANT_LABELS = frozenset(
    {
        "www",
        "archive-stream",
        "archive",
        "media",
        "api",
        "cdn",
        "player",
        "stream",
        "streaming",
        "secure",
        "portal",
        "connect",
        "live",
        "video",
        "videos",
        "files",
        "static",
        "assets",
        "new",
        "app",
        # Shared player/portal hosts that serve MANY governments and are
        # pinned per video, not per host (`play.champds.com`,
        # `public.destinyhosted.com`, `videoplayer.telvue.com`,
        # `cloud.castus.tv`, `livestream.telvue.com` in
        # tenant_overrides.csv). The host carries no government name there.
        "play",
        "public",
        "videoplayer",
        "livestream",
        "cloud",
    }
)

# The one shared regional media consortium tenant confirmed real and
# legitimate so far (Shorewood city, MN's Cablecast clip; BACKLOG_DONE.md's
# Excelsior entry records it serving several Lake Minnetonka cities). A host
# on this list never flags. It is a closed list on purpose: the entry says
# there is no cheap way to tell a consortium from a wrong-government host by
# name alone, so a new consortium is added by name once a person has
# confirmed it, not inferred.
CONSORTIUM_TENANT_HOSTS = frozenset({"reflect-lmcc.cablecast.tv"})

# Words a tenant label or a government name carries that name no place.
_GENERIC_WORDS = frozenset(
    {
        "city",
        "town",
        "village",
        "county",
        "township",
        "twp",
        "borough",
        "parish",
        "municipality",
        "muni",
        "of",
        "the",
        "and",
        "co",
        "cdp",
        "charter",
        "government",
        "gov",
        "govt",
        "regional",
        "district",
        "pub",
        "tv",
        "meetings",
        "meeting",
        "public",
    }
)

# Longest first, so "cityof" is peeled before "city".
_LABEL_NOISE_PREFIXES = (
    "cityof",
    "townof",
    "villageof",
    "countyof",
    "boroughof",
    "twpof",
    "pub",
    "city",
    "town",
    "village",
    "county",
)
_LABEL_NOISE_SUFFIXES = (
    "county",
    "city",
    "town",
    "village",
    "twp",
    "borough",
    "tv",
    "gov",
    "meetings",
    "council",
    "media",
    "live",
)


def tenant_label(host: str) -> str:
    """The tenant's own name from a single-tenant vendor host, or "" when the
    host is not one (a government's own domain, a shared video host, a
    vendor's infrastructure host).

    `hcnv.granicus.com` -> "hcnv"; `mandannd.portal.civicclerk.com` ->
    "mandannd"; `pub-lakewood.escribemeetings.com` -> "pub-lakewood".
    """
    host = (host or "").strip().lower().split(":")[0]
    for suffix in _TENANT_SUFFIXES:
        if host.endswith(suffix):
            label = host[: -len(suffix)]
            if not label or "." in label:
                return ""
            if label in _NON_TENANT_LABELS:
                return ""
            return label
    return ""


def _letters(text: str) -> str:
    return re.sub(r"[^a-z]", "", (text or "").lower())


def _name_words(name: str) -> list:
    return re.findall(r"[a-z]+", (name or "").lower())


def _clean_label_forms(label: str) -> set:
    """The tenant label as the forms it might be compared in: the plain
    letters, and the letters with a leading/trailing type word peeled."""
    base = _letters(label)
    forms = {base}
    for prefix in _LABEL_NOISE_PREFIXES:
        if base.startswith(prefix) and len(base) - len(prefix) >= 3:
            forms.add(base[len(prefix) :])
    for form in list(forms):
        for suffix in _LABEL_NOISE_SUFFIXES:
            if form.endswith(suffix) and len(form) - len(suffix) >= 3:
                forms.add(form[: -len(suffix)])
    return {f for f in forms if f}


def label_matches_name(label: str, gov_name: str, gov_state: str = "") -> bool:
    """True when the tenant label plausibly names this government.

    Deliberately generous: an abbreviated tenant must keep passing (`hcnv`
    for Humboldt County, NV passed a manual re-check on 2026-09-11, so a
    literal substring match is not required). Any one of these is enough:

    - a place word of the name (3+ letters, not a generic type word) is
      inside the label, or the label (4+ letters) is a prefix of it
      ("beltramimn" holds "beltrami"; "kalamazo" starts "kalamazoo");
    - the label is the initials of the name's words, alone or followed by
      the state code ("hcnv" = Humboldt County + NV; "hc").
    """
    words = _name_words(gov_name)
    place_words = [w for w in words if w not in _GENERIC_WORDS and len(w) >= 3]
    forms = _clean_label_forms(label)
    if not forms or not words:
        return False
    for form in forms:
        for word in place_words:
            if word in form:
                return True
            if len(form) >= 4 and word.startswith(form):
                return True
    state = (gov_state or "").strip().lower()
    initials = "".join(w[0] for w in words if w not in {"of", "the", "and"})
    place_initials = "".join(w[0] for w in place_words)
    for form in forms:
        for stem in {initials, place_initials}:
            if len(stem) >= 2 and form in {stem, stem + state}:
                return True
    return False


def host_name_conflict(
    host: str, platform: str, gov_name: str, gov_state: str = ""
) -> Optional[str]:
    """A REVIEW reason when the tenant a video was found on shares no name
    with the government it is being filed under, else None.

    Never a verdict. It returns text for a caller to record beside the row;
    it does not skip or reject. Silent (None) whenever the host is not a
    single-tenant vendor host, the tenant is on `CONSORTIUM_TENANT_HOSTS`, or
    there is no government name to compare.
    """
    host_l = (host or "").strip().lower().split(":")[0]
    if not host_l or host_l in CONSORTIUM_TENANT_HOSTS:
        return None
    label = tenant_label(host_l)
    if not label or not (gov_name or "").strip():
        return None
    if label_matches_name(label, gov_name, gov_state):
        return None
    kind = (
        " (a bare Cablecast/Castus host can be a shared regional media "
        "consortium; check before treating it as wrong)"
        if platform in ("cablecast", "castus")
        else ""
    )
    return (
        f"host-name-review: {platform or 'platform'} tenant {label!r} "
        f"({host_l}) shares no name word with {gov_name!r}"
        f"{', ' + gov_state if gov_state else ''}{kind}"
    )
