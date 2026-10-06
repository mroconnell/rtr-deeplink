"""Pin audit: the name rules (read-only).

These rules look at the *name in a pin's address* (the host label, the
YouTube handle, a keyed path such as `/atlantaga/`) and compare it with the
government the pin points at, and with other pins and saved pages.

    R1  same-name split     the same name is pinned to two different
                            governments (the Sunnyside NL / Sunnyside WA case)
    R2  state word          the address itself names a different state
                            (`wa-sunnyside2`, `@cityofsunnysidewa`)
    R5  title names a twin  saved pages on the address mention another
                            state with the same-named government
    R6  risky, no content   a name-match sweep pin, a same-name government
                            elsewhere, and nothing saved to check it against

Each rule is `rule(data, judged) -> List[Flag]`. It judges only `judged`
and compares against everything in `data`. Nothing is written anywhere.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Sequence, Set, Tuple

from scripts import pin_audit_core as core
from scripts.pin_audit_core import AuditData, Flag, Page, Pin

# ---------------------------------------------------------------- vocabulary

_US = (
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO "
    "MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC"
).split()
_CA = "AB BC MB NB NL NS NT NU ON PE QC SK YT".split()
STATE_CODES = frozenset(c.lower() for c in _US + _CA)

# Full names, squashed -> code. Longest names are tried first when matching.
STATE_NAMES: Dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "newhampshire": "NH", "newjersey": "NJ", "newmexico": "NM",
    "newyork": "NY", "northcarolina": "NC", "northdakota": "ND", "ohio": "OH",
    "oklahoma": "OK", "oregon": "OR", "pennsylvania": "PA", "rhodeisland": "RI",
    "southcarolina": "SC", "southdakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "westvirginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "alberta": "AB", "britishcolumbia": "BC", "manitoba": "MB",
    "newbrunswick": "NB", "newfoundland": "NL", "newfoundlandandlabrador": "NL",
    "novascotia": "NS", "northwestterritories": "NT", "nunavut": "NU",
    "ontario": "ON", "princeedwardisland": "PE", "quebec": "QC",
    "saskatchewan": "SK", "yukon": "YT",
}  # fmt: skip
_NAMES_LONGEST_FIRST = sorted(STATE_NAMES, key=len, reverse=True)
# Full state names as they appear in a title ("Sunnyside, Washington").
_NAME_WORDS: Dict[str, str] = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "alberta": "AB", "british columbia": "BC", "manitoba": "MB",
    "new brunswick": "NB", "newfoundland": "NL", "nova scotia": "NS",
    "ontario": "ON", "prince edward island": "PE", "quebec": "QC",
    "saskatchewan": "SK", "yukon": "YT",
}  # fmt: skip

# Hosts whose own name says nothing about the government (a vendor suffix
# that serves many tenants as subdomains is NOT in this list: its first
# label is the tenant name).
VENDOR_SUFFIXES = (
    "civicplus.com", "granicus.com", "escribemeetings.com", "civicweb.net",
    "primegov.com", "portal.civicclerk.com", "iqm2.com", "cablecast.tv",
    "viebit.com", "new.swagit.com", "swagit.com", "legistar.com",
    "community.diligentoneplatform.com", "diligentoneplatform.com",
    "boarddocs.com", "municodemeetings.com", "teammunicode.com",
    "novusagenda.com", "destinyhosted.com", "civicclerk.com", "ci.us",
)  # fmt: skip
_SHARED_FALLBACK = frozenset(
    "youtube.com www.youtube.com m.youtube.com youtu.be vimeo.com "
    "www.vimeo.com player.vimeo.com".split()
)

_OF_PREFIXES = (
    "cityandcountyof", "thecityof", "municipalityof", "townshipof", "boroughof",
    "villageof", "countyof", "cityof", "townof", "twpof",
)  # fmt: skip
_BARE_PREFIXES = ("city", "town", "village", "county", "the")
_SUFFIX_WORDS = (
    "township", "borough", "village", "government", "county", "city", "town",
    "govt", "gov", "tv",
)  # fmt: skip
_VENDOR_LABEL_PREFIXES = ("pub-", "reflect-")
_GENERIC_LABELS = frozenset(
    "ci co city town to vi com org gov net edu k12 state".split()
)
_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_VIDEO_IN_URL = re.compile(
    r"(?:[?&]v=|youtu\.be/|/embed/|/live/|/shorts/)([A-Za-z0-9_-]{11})"
)


def _squash(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _strip_digits(s: str) -> str:
    return re.sub(r"\d+$", "", s)


# ---------------------------------------------------------------- name_slug


def _is_shared_host(host: str) -> bool:
    if host in _SHARED_FALLBACK:
        return True
    try:
        from app.utils.gov_registry import registry

        return host in registry.MULTI_GOV_HOSTS
    except Exception:  # pragma: no cover - registry unavailable
        return False


def _match_handle(match: str) -> str:
    """A YouTube/Vimeo handle out of `channel=@Handle`; "" for anything else."""
    m = (match or "").strip()
    if m.lower().startswith("channel="):
        m = m[len("channel=") :]
    if m.startswith("@"):
        return m[1:].lower()
    return ""


def _path_key(match: str) -> str:
    """A name-like path key such as champds `/atlantaga/` or castus
    `/vod/cityofdecatur/`; "" when the first real segment is not name-like
    (a numeric id, a player token)."""
    m = (match or "").strip()
    if not m.startswith("/"):
        return ""
    segs = [s for s in m.split("/") if s]
    if segs and segs[0].lower() == "vod":
        segs = segs[1:]
    if not segs:
        return ""
    seg = segs[0].lower()
    return seg if re.fullmatch(r"[a-z][a-z\-_]{2,}[a-z0-9]*", seg) else ""


def _registered_label(host: str) -> str:
    """The label naming the owner of an own-domain host: `sunnysidewa.gov`
    -> `sunnysidewa`; `ci.sunnyside.wa.us` -> `sunnyside`."""
    parts = [p for p in host.lower().split(".") if p]
    if parts and parts[0] == "www":
        parts = parts[1:]
    if len(parts) < 2:
        return parts[0] if parts else ""
    tld = parts[-1]
    rest = parts[:-1]
    if tld == "us" and rest and rest[-1] in STATE_CODES and len(rest) > 1:
        rest = rest[:-1]
    while len(rest) > 1 and rest[-1] in ("com", "org", "gov", "net", "edu", "co"):
        rest = rest[:-1]
    label = rest[-1]
    if label in _GENERIC_LABELS and len(rest) > 1:
        label = rest[-2]
    return label


def _raw_label(pin: Pin) -> str:
    """The unsquashed name text of a pin ("" when it carries no name):
    a handle, a path key, a vendor tenant label or an own-domain label."""
    handle = _match_handle(pin.match) or (
        pin.channel[1:].lower() if pin.channel.startswith("@") else ""
    )
    if handle:
        return handle
    match = (pin.match or "").strip()
    host = (pin.host or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if match:
        if _is_shared_host(pin.host) or _is_shared_host(host):
            return _path_key(match)
        # A keyed row on an ordinary host keeps the host's own name.
    elif _is_shared_host(pin.host) or _is_shared_host(host):
        return ""
    for suf in VENDOR_SUFFIXES:
        if host.endswith("." + suf):
            label = host[: -(len(suf) + 1)].split(".")[-1]
            for pre in _VENDOR_LABEL_PREFIXES:
                if label.startswith(pre):
                    label = label[len(pre) :]
                    break
            return label
    if host in VENDOR_SUFFIXES:
        return ""
    return _registered_label(host)


def _is_own_domain(pin: Pin) -> bool:
    """True when the name comes from the government's own domain
    (`yorkcounty.gov`), not from a vendor tenant label, a handle or a path
    key. An own domain is the owner's own claim to the name, so R1 does not
    judge it as a name-match guess."""
    if _match_handle(pin.match) or pin.channel.startswith("@"):
        return False
    host = (pin.host or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if _is_shared_host(pin.host) or _is_shared_host(host):
        return False
    return not any(host.endswith("." + s) for s in VENDOR_SUFFIXES)


def _split_hyphen_state(raw: str) -> Tuple[str, str]:
    """`wa-sunnyside2` -> ("sunnyside2", "WA"); `sunnyside-wa` ->
    ("sunnyside", "WA"); no separated state token -> (raw, "")."""
    toks = [t for t in re.split(r"[-_.]", raw) if t]
    if len(toks) < 2:
        return raw, ""
    if toks[0] in STATE_CODES:
        return "".join(toks[1:]), toks[0].upper()
    if toks[-1] in STATE_CODES:
        return "".join(toks[:-1]), toks[-1].upper()
    first, last = _squash(toks[0]), _squash("".join(toks[-1:]))
    if first in STATE_NAMES and len(toks) > 1:
        return "".join(toks[1:]), STATE_NAMES[first]
    if last in STATE_NAMES and len(toks) > 1:
        return "".join(toks[:-1]), STATE_NAMES[last]
    return raw, ""


def _strip_of_prefix(s: str) -> str:
    for pre in _OF_PREFIXES:
        if s.startswith(pre) and len(s) > len(pre):
            return s[len(pre) :]
    return s


def name_slug(pin: Pin) -> str:
    """The place-name part of a pin's address, squashed (letters and digits
    only): `wa-sunnyside2.civicplus.com` -> `sunnyside`,
    `pub-peelregion.escribemeetings.com` -> `peelregion`,
    `sunnysidewa.gov` -> `sunnysidewa`, `@cityofsunnysidewa` ->
    `sunnysidewa`. A bare video id, or a shared host with no handle, gives
    "". A glued state code (`sunnysidewa`) is kept; rules strip it only when
    what is left equals the government's own name."""
    raw = _raw_label(pin)
    if not raw:
        return ""
    raw, _state = _split_hyphen_state(raw)
    s = _strip_digits(_squash(raw))
    s = _strip_of_prefix(s)
    return _strip_digits(s)


# ---------------------------------------------------------------- analysis


def _variants(s: str, protect: frozenset = frozenset()) -> List[Tuple[str, bool]]:
    """Safe reductions of a squashed slug, each with a flag saying whether a
    city/township word was cut off the end: without trailing digits, without
    an "of" prefix, a bare city/town word in front, or a city/township word
    behind. Every one is only *compared*, never used on its own. A word in
    `protect` is part of the government's real name (Oregon City) and is
    never cut."""
    out: List[Tuple[str, bool]] = []
    seen: Set[str] = set()

    def add(x: str, cut: bool = False) -> None:
        if x and x not in seen:
            seen.add(x)
            out.append((x, cut))

    base = _strip_digits(s)
    add(s)
    add(base)
    pref = _strip_of_prefix(base)
    add(pref)
    for start in {base, pref}:
        for p in _BARE_PREFIXES:
            if p not in protect and start.startswith(p):
                add(start[len(p) :])
    for start, _c in list(out):
        for w in _SUFFIX_WORDS:
            if w not in protect and start.endswith(w) and len(start) > len(w):
                add(start[: -len(w)], True)
    return out


def _cores(raw: str, protect: frozenset = frozenset()) -> List[Tuple[str, str, str]]:
    """Every (core name, state code, how) reading of a raw label. The state
    is "" when none was found; `how` is "" , "hyphen", "glued" or "word"."""
    out: List[Tuple[str, str, str]] = []
    rest, st = _split_hyphen_state(raw)
    if st and not (st == "CO" and not raw.startswith("co-")):
        # A trailing "-co" is "county" (hamilton-co.org), not Colorado.
        for v, _cut in _variants(_squash(rest), protect):
            out.append((v, st, "hyphen"))
    for v, cut in _variants(_squash(raw), protect):
        out.append((v, "", ""))
        # A state glued on is only read from a reading that did not cut a
        # county/township word first (pinetownshipindianacounty is Indiana
        # County, not Indiana).
        if len(v) >= 5 and not cut:
            tail = v[-2:]
            # "co" glued on is far more often "county" (perryco.org) than Colorado, and
            # "sd" is a school district (@HillsboroSD) more often than South Dakota.
            if tail in STATE_CODES and tail not in ("co", "sd"):
                for w, _c in _variants(v[:-2], protect):
                    out.append((w, tail.upper(), "glued"))
            for nm in _NAMES_LONGEST_FIRST:
                if v.endswith(nm) and len(v) > len(nm) + 1:
                    for w, _c in _variants(v[: -len(nm)], protect):
                        out.append((w, STATE_NAMES[nm], "word"))
                    break
            for nm in _NAMES_LONGEST_FIRST:
                if v.startswith(nm) and len(v) > len(nm) + 1:
                    for w, _c in _variants(v[len(nm) :], protect):
                        out.append((w, STATE_NAMES[nm], "word"))
                    break
    return out


def _protect_for(gov_id: str) -> frozenset:
    """City/county words that belong inside a government's real name
    ("Oregon City city": `city` is protected), so a slug like `oregoncity`
    is not cut down to `oregon` and matched with Oregon, WI."""
    g = core.gov_info(gov_id)
    if g is None:
        return frozenset()
    toks = g.name.lower().split()
    if toks and toks[-1] in _SUFFIX_WORDS:
        toks = toks[:-1]
    words = set(_SUFFIX_WORDS) | set(_BARE_PREFIXES)
    return frozenset(t for t in toks if t in words)


def analyze_how(
    pin: Pin, base_squashed: str, gov_id: str = ""
) -> Optional[Tuple[str, str]]:
    """None when the pin's address does not reduce to the name
    `base_squashed`; else (state code written in the address, how it was
    written). The state is "" when the address names none."""
    raw = _raw_label(pin)
    if not raw or not base_squashed:
        return None
    prot = _protect_for(gov_id or pin.gov_id)
    hits = [(st, how) for core_, st, how in _cores(raw, prot) if core_ == base_squashed]
    if not hits:
        return None
    for st, how in hits:
        if st == "":
            return ("", "")
    return hits[0]


def analyze(pin: Pin, base_squashed: str) -> Optional[str]:
    """Like analyze_how, but only the state code ("" if the address names
    none, None if the name does not match)."""
    r = analyze_how(pin, base_squashed)
    return None if r is None else r[0]


def _says_county(pin: Pin) -> bool:
    return "county" in _squash(_raw_label(pin))


# ---------------------------------------------------------------- helpers


def _gov_label(gov_id: str) -> str:
    g = core.gov_info(gov_id)
    if g is None:
        return gov_id
    return f"{g.name}, {g.state}" if g.state else g.name


def _pin_label(pin: Pin) -> str:
    if pin.match:
        return f"{pin.host} ({pin.match[:40]})"
    return pin.host


def _is_machine(pin: Pin) -> bool:
    return "step0_dns_full" in pin.source or "wildcard_http_sweep" in pin.source


def _level(gov_id: str) -> str:
    g = core.gov_info(gov_id)
    if g is None:
        return ""
    if g.kind.endswith(":county") or g.kind == "ca:cd":
        return "county"
    return "other"


def _same_state(a: str, b: str) -> bool:
    return bool(a) and bool(b) and a == b


def _vendor_of(pin: Pin) -> str:
    host = (pin.host or "").lower()
    for suf in VENDOR_SUFFIXES:
        if host.endswith("." + suf):
            return suf
    return ""


_CA_STATES = frozenset(c.upper() for c in _CA)


class _Index:
    """Per-AuditData lookup tables, built once."""

    def __init__(self, data: AuditData) -> None:
        self.data = data
        self.n = len(data.pins)
        self.by_name: Dict[str, List[Tuple[Pin, str]]] = {}
        for q in data.pins:
            if q.store == core.STORE_ARCHIVE:
                continue
            g = core.gov_info(q.gov_id)
            if g is None or not g.base:
                continue
            key = _squash(g.base)
            st = analyze(q, key)
            if st is None:
                continue
            self.by_name.setdefault(key, []).append((q, st))
        # Share of each vendor's pins that point at Canadian governments.
        tally: Dict[str, List[int]] = {}
        for q in data.pins:
            v = _vendor_of(q)
            if not v or q.store == core.STORE_ARCHIVE:
                continue
            qg = core.gov_info(q.gov_id)
            if qg is None:
                continue
            t = tally.setdefault(v, [0, 0])
            t[0] += 1
            t[1] += 1 if qg.country == "ca" else 0
        self.vendor_ca_share = {v: c / n for v, (n, c) in tally.items() if n >= 20}
        self.pages_by_video: Dict[str, List[Page]] = {}
        for pg in data.pages:
            for m in _VIDEO_IN_URL.finditer(pg.video_url or ""):
                self.pages_by_video.setdefault(m.group(1), []).append(pg)


_CACHE: Dict[str, object] = {}


def _index(data: AuditData) -> _Index:
    ix = _CACHE.get("ix")
    if not isinstance(ix, _Index) or ix.data is not data or ix.n != len(data.pins):
        ix = _Index(data)
        _CACHE["ix"] = ix
    return ix


def _pages_for(data: AuditData, ix: _Index, pin: Pin) -> List[Page]:
    """Saved Archive pages that sit on this pin's address."""
    match = (pin.match or "").strip()
    host = (pin.host or "").lower()
    handle = _match_handle(match)
    if handle:
        return list(data.pages_by_channel.get("@" + handle, []))
    vid = match[len("youtube:") :] if match.lower().startswith("youtube:") else match
    if _VIDEO_ID_RE.match(vid) and (host.endswith("youtube.com") or host == "youtu.be"):
        return list(ix.pages_by_video.get(vid, []))
    if _is_shared_host(host) and not match:
        return []
    pages = list(data.pages_by_host.get(host, []))
    if not pages and host.startswith("www."):
        pages = list(data.pages_by_host.get(host[4:], []))
    if match and not match.lower().startswith(("channel=", "cablecast:")):
        key = match.strip("/")
        if len(key) < 3:
            return []
        pages = [p for p in pages if key in p.source_url or key in p.video_url]
    elif match:
        return []
    return pages[:300]


def _texts(data: AuditData, ix: _Index, pin: Pin) -> List[str]:
    out: List[str] = []
    if pin.title:
        out.append(pin.title)
    for pg in _pages_for(data, ix, pin):
        for t in (pg.title, pg.stored_jurisdiction):
            if t:
                out.append(t)
    return out


def _state_in_text(text: str, code: str) -> bool:
    """True when the text names the state in a place-qualifier form:
    ", WA" / "(WA)" / ", Washington" / "(Washington)"."""
    if re.search(rf"[,(]\s*{code}\b", text):
        return True
    for nm, c in _NAME_WORDS.items():
        if c != code:
            continue
        pat = rf"[,(]\s*{re.escape(nm)}\b(?!\s+(?:county|township|twp|parish|park|street|st\b|ave|avenue|school|elementary|high|middle|university|dc|d\.c))"
        if re.search(pat, text, flags=re.I):
            return True
    return False


# ---------------------------------------------------------------- R1


def rule_r1_same_name_split(data: AuditData, judged: Sequence[Pin]) -> List[Flag]:
    ix = _index(data)
    flags: List[Flag] = []
    for p in judged:
        if p.store == core.STORE_ARCHIVE:
            continue
        g = core.gov_info(p.gov_id)
        if g is None or not g.base:
            continue
        key = _squash(g.base)
        p_state = analyze(p, key)
        if p_state is None:
            continue
        if p_state and g.state and p_state in g.state.split("/"):
            continue  # the address itself says this state: self-consistent
        if _is_own_domain(p):
            continue  # the owner's own domain is not a name-match guess
        tw = core.twins(p.gov_id)
        if not tw:
            continue
        # Other pins that read as this name and agree with P's government.
        # Two same-named governments on different hosts are normal; a split
        # is only worth a flag when P has no company and the twin has some.
        own_support = [
            q
            for q, _s in ix.by_name.get(key, [])
            if q.gov_id == p.gov_id and q is not p
        ]
        if own_support:
            continue  # another pin (another host, or another store) agrees with P
        if any(
            _state_in_text(t, c)
            for t in _texts(data, ix, p)
            for c in (g.state.split("/") if g.state else [])
        ):
            continue  # a saved title on the address names this state
        by_twin: Dict[str, List[Pin]] = {}
        for q, _qst in ix.by_name.get(key, []):
            if q.gov_id not in tw or q is p:
                continue
            tg = core.gov_info(q.gov_id)
            if tg is None:
                continue
            if tg.country != g.country:
                share = ix.vendor_ca_share.get(_vendor_of(p))
                if share is not None and (
                    (g.country == "ca" and share >= 0.7)
                    or (g.country == "us" and share <= 0.2)
                ):
                    continue  # the vendor mostly serves P's own country
            if (_says_county(p) and _level(q.gov_id) != "county") or (
                _says_county(q) and _level(p.gov_id) != "county"
            ):
                continue  # a county address against a city: not the same body
            if (
                _same_state(g.state, tg.state)
                and _level(p.gov_id) != _level(q.gov_id)
                and "county" in (_level(p.gov_id), _level(q.gov_id))
            ):
                continue  # a county and a place: a level question, not a split
            by_twin.setdefault(q.gov_id, []).append(q)
        best = None
        for tid, qs in by_twin.items():
            tg = core.gov_info(tid)
            distinct = {(q.host, q.match) for q in qs}
            n_twin = len(distinct)
            ryan_q = any("ryan_stated" in q.source for q in qs)
            machine = _is_machine(p)
            if not (machine or ryan_q or n_twin >= 2):
                continue
            different_state = bool(g.state) and bool(tg.state) and g.state != tg.state
            sev = "medium"
            if different_state and (n_twin >= 2 or (ryan_q and machine)):
                sev = "high"
            if sev == "high" and "ryan_stated" in p.source:
                sev = "medium"  # Ryan checked this very pin by hand
            rank = (0 if sev == "high" else 1, -n_twin, tid)
            if best is None or rank < best[0]:
                best = (rank, tid, qs, sev, n_twin)
        if best is None:
            continue
        _rank, tid, qs, sev, n = best
        q0 = sorted(qs, key=lambda q: (0 if "ryan_stated" in q.source else 1, q.ref))[0]
        more = f" ({n - 1} more pins agree)" if n > 1 else ""
        detail = (
            f"{_pin_label(p)} is pinned to {_gov_label(p.gov_id)}, but "
            f"{_pin_label(q0)} is pinned to {_gov_label(tid)}{more}."
        )
        flags.append(Flag("R1", sev, p, tid, q0.ref, detail))
    return flags


# ---------------------------------------------------------------- R2


def _state_word_is_local_place(st: str, state: str) -> bool:
    """True when a government named like the full state `st` exists inside the
    pinned government's own `state` (washingtonwilkes.org: Washington is a
    Georgia city, so "washington" there is a place name, not Washington State)."""
    idx = core._twin_index()[0]
    for nm, code in STATE_NAMES.items():
        if code != st:
            continue
        for gid in idx.get(core.base_name(nm), ()):
            gi = core.gov_info(gid)
            if gi is not None and gi.state == state:
                return True
    return False


def rule_r2_state_word(data: AuditData, judged: Sequence[Pin]) -> List[Flag]:
    flags: List[Flag] = []
    for p in judged:
        if p.store == core.STORE_ARCHIVE:
            continue
        g = core.gov_info(p.gov_id)
        if g is None or not g.base or not g.state:
            continue
        key = _squash(g.base)
        res = analyze_how(p, key)
        if res is None or not res[0]:
            continue
        st, how = res
        if st in g.state.split("/"):
            continue
        if how == "word" and any(
            _state_word_is_local_place(st, s) for s in g.state.split("/")
        ):
            continue  # the state word is a place name in the pin's own state
        if how != "word" and st in _CA_STATES and g.country != "ca":
            continue  # a bare Canadian code on a US address is usually part of the name
        other = ""
        other_ref = ""
        for tid in sorted(core.twins(p.gov_id)):
            tg = core.gov_info(tid)
            if tg and tg.state == st:
                other = tid
                other_ref = ""
                break
        label = _pin_label(p)
        detail = (
            f"{label} is pinned to {_gov_label(p.gov_id)}, but the address "
            f"itself names {st}"
        )
        if other:
            detail += f", and {_gov_label(other)} exists."
        else:
            detail += "."
        sev = "high"
        if "ryan_stated" in p.source:
            sev = "medium"  # Ryan checked this very pin by hand
        elif how == "glued" and not (
            p.host.endswith((".gov", ".us")) or _match_handle(p.match)
        ):
            sev = "medium"  # two letters glued on a .org/.com may be part of the name
        flags.append(Flag("R2", sev, p, other, other_ref, detail))
    return flags


# ---------------------------------------------------------------- R5 / R6


def _twin_states(gov_id: str) -> Dict[str, List[str]]:
    """State code -> twin gov_ids in a state other than the government's."""
    g = core.gov_info(gov_id)
    out: Dict[str, List[str]] = {}
    if g is None:
        return out
    mine = set(g.state.split("/")) if g.state else set()
    for tid in sorted(core.twins(gov_id)):
        tg = core.gov_info(tid)
        if tg is None or not tg.state or tg.state in mine:
            continue
        out.setdefault(tg.state, []).append(tid)
    return out


def rule_r5_title_names_twin(data: AuditData, judged: Sequence[Pin]) -> List[Flag]:
    ix = _index(data)
    flags: List[Flag] = []
    for p in judged:
        if p.store == core.STORE_ARCHIVE:
            continue
        g = core.gov_info(p.gov_id)
        if g is None or not g.state:
            continue
        tstates = _twin_states(p.gov_id)
        if not tstates:
            continue
        texts = _texts(data, ix, p)
        if not texts:
            continue
        mine = g.state.split("/")
        if any(_state_in_text(t, c) for t in texts for c in mine):
            continue
        best = None
        for st, tids in tstates.items():
            n = sum(1 for t in texts if _state_in_text(t, st))
            if n and (best is None or n > best[0]):
                best = (n, st, tids[0])
        if best is None:
            continue
        n, st, tid = best
        example = next(t for t in texts if _state_in_text(t, st))
        detail = (
            f"{_pin_label(p)} is pinned to {_gov_label(p.gov_id)}, but {n} saved "
            f'title(s) on it name {st} (for example "{example[:70]}") and none '
            f"name {g.state}; {_gov_label(tid)} exists."
        )
        flags.append(Flag("R5", "medium", p, tid, "", detail))
    return flags


def rule_r6_risky_source_no_content(
    data: AuditData, judged: Sequence[Pin]
) -> List[Flag]:
    ix = _index(data)
    flags: List[Flag] = []
    for p in judged:
        if p.store == core.STORE_ARCHIVE or not _is_machine(p):
            continue
        tstates = _twin_states(p.gov_id)
        if not tstates:
            continue
        if _texts(data, ix, p):
            continue
        states = ", ".join(sorted(tstates)[:4])
        detail = (
            f"{_pin_label(p)} was pinned by a name-match sweep to "
            f"{_gov_label(p.gov_id)}, a same-named government also exists in "
            f"{states}, and no saved page or title exists to check it against."
        )
        flags.append(Flag("R6", "note", p, "", "", detail))
    return flags


RULES = [
    rule_r1_same_name_split,
    rule_r2_state_word,
    rule_r5_title_names_twin,
    rule_r6_risky_source_no_content,
]
