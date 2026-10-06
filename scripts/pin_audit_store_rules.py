"""Pin audit store rules (read-only): R3 channel coherence, R4 store disagreement.

R4 asks: do the other stores say something different about the same host
(or the same keyed channel / video)? A tenant override, a queue line, a
research row, a discovery tenant, a CivicPlus row and the saved Archive
pages are written at different times by different people and machines.
When they name different governments for the same thing, one is wrong.
(The Sunnyside case: `sunnyside.primegov.com` pinned to Sunnyside NL while
other pins and Archive pages said Sunnyside WA.)

R3 asks: on a YouTube or Vimeo channel, do the pins and pages agree? One
channel belongs to one government, or to a station that covers a few
neighbouring ones. A video pinned to a far-away state is suspect.

Caveats a reader should keep in mind:
  * Archive pages are mostly filed *because of* a pin. A page that
    disagrees with the pin is a real signal. A page that agrees is not
    proof the pin is right.
  * A research row's domain is a government's own site, but it is typed by
    hand: it may hold a county's or a vendor's domain.

A rule is `rule(data, judged) -> List[Flag]` (see pin_audit_core.py). It
judges only `judged` but compares against everything in `data`.
"""

from __future__ import annotations

import csv
import re
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple
from urllib.parse import urlsplit

if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import pin_audit_core as core  # noqa: E402
from scripts.pin_audit_core import AuditData, Flag, Page, Pin  # noqa: E402

HUBS_FILE = core.DATA_DIR / "regional_tv_hubs.csv"
_COUNTY_KINDS = ("us:county", "ca:cd")
_LOWER_KINDS = ("us:place", "us:cousub", "ca:csd")
_SHARED_HOST_GOVS = 4  # a whole host with this many distinct governments is shared
_REGIONAL_STATES = 4  # a channel spanning this many states is a regional network

# ------------------------------------------------------------ same government


@lru_cache(maxsize=1)
def _linked_pairs() -> FrozenSet[Tuple[str, str]]:
    from app.utils.gov_registry import registry

    pairs = set()
    for a, _rel, b, _ev in registry.relations():
        if a and b:
            pairs.add((a, b))
            pairs.add((b, a))
    return frozenset(pairs)


@lru_cache(maxsize=1)
def _canon() -> Dict[str, str]:
    from app.utils.gov_registry import registry

    return registry.consolidated()


def same_gov(a: str, b: str) -> bool:
    """Equal, consolidated into one government, or linked in relations."""
    if a == b:
        return True
    canon = _canon()
    if canon.get(a, a) == canon.get(b, b):
        return True
    return (a, b) in _linked_pairs()


def _states(info: Optional[core.GovInfo]) -> Set[str]:
    if info is None or not info.state:
        return set()
    return {p for p in info.state.upper().replace(",", "/").split("/") if p.strip()}


def _level_difference(gi: core.GovInfo, oi: core.GovInfo) -> bool:
    """A county against a place/town in one state, or a minted rtr: id
    against a national id in one state."""
    if not (_states(gi) & _states(oi)):
        return False
    pair = {gi.kind, oi.kind}
    for counties in _COUNTY_KINDS:
        for lower in _LOWER_KINDS:
            if pair == {counties, lower}:
                return True
    g_min, o_min = gi.kind.startswith("rtr:"), oi.kind.startswith("rtr:")
    return g_min != o_min


def _gov_label(gov_id: str) -> str:
    info = core.gov_info(gov_id)
    if info is None:
        return gov_id
    return f"{info.name}, {info.state}" if info.state else info.name


def disagreement_severity(g: str, o: str) -> Optional[str]:
    """None when the two ids are the same government (or unknown); else
    high / medium / low."""
    if same_gov(g, o):
        return None
    gi, oi = core.gov_info(g), core.gov_info(o)
    if gi is None or oi is None:
        return None
    if _level_difference(gi, oi):
        return "low"
    gs, os_ = _states(gi), _states(oi)
    if not gs or not os_:
        return None
    if gs & os_:
        return "medium"  # same state, different government
    if o in core.twins(g) or g in core.twins(o):
        return "high"  # same name, different state
    if core.states_adjacent(gi.state, oi.state):
        return "medium"
    return "high"


# ------------------------------------------------------------------ hosts

_YOUTUBE_HOSTS = frozenset(
    {"www.youtube.com", "youtube.com", "youtu.be", "m.youtube.com"}
)
_VIMEO_HOSTS = frozenset({"vimeo.com", "player.vimeo.com", "www.vimeo.com"})


def _bare(host: str) -> str:
    host = (host or "").lower()
    return host[4:] if host.startswith("www.") else host


def _host_group(host: str) -> str:
    host = (host or "").lower()
    if host in _YOUTUBE_HOSTS:
        return "youtube"
    if host in _VIMEO_HOSTS:
        return "vimeo"
    return _bare(host)


@lru_cache(maxsize=1)
def _hubs() -> Tuple[FrozenSet[str], FrozenSet[str]]:
    """(hub host names without www, hub channel handles lowercase)."""
    hosts: Set[str] = set()
    handles: Set[str] = set()
    try:
        with open(HUBS_FILE, newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                url = row.get("url") or ""
                host = _bare(urlsplit(url).hostname or "")
                if host and _host_group(host) not in ("youtube", "vimeo"):
                    hosts.add(host)
                notes = (row.get("notes") or "") + " " + url
                for m in re.finditer(r"@([A-Za-z0-9_.-]{4,})", notes):
                    handles.add(m.group(1).lower())
                m = re.search(r"YouTube channel ([A-Za-z0-9_.-]{4,})", notes)
                if m:
                    handles.add(m.group(1).lower())
                if "vimeo.com/" in url:
                    tail = url.rstrip("/").rsplit("/", 1)[-1].lower()
                    if tail:
                        handles.add(tail)
    except OSError:
        pass
    return frozenset(hosts), frozenset(handles)


def _is_multi_host(host: str) -> bool:
    from app.utils.gov_registry import registry

    h = (host or "").lower()
    return (
        h in registry.MULTI_GOV_HOSTS
        or _bare(h) in registry.MULTI_GOV_HOSTS
        or ("www." + _bare(h)) in registry.MULTI_GOV_HOSTS
        or _bare(h) in _hubs()[0]
    )


# ------------------------------------------------------------ video / channel keys

_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_URL_ID = re.compile(
    r"(?:[?&]v=|youtu\.be/|/embed/|/shorts/|/live/)([A-Za-z0-9_-]{11})"
)
_VIMEO_URL_ID = re.compile(r"vimeo\.com/(?:video/|channels/[^/]+/|[^/]+/)?(\d{6,})")


def _norm_channel(text: str) -> str:
    return (text or "").strip().lower().lstrip("@")


def parse_media_match(host: str, match: str) -> Tuple[str, str]:
    """(kind, key) for a keyed pin on YouTube/Vimeo.
    kind: "channel" (key = normalised handle), "video" (key = "yt:ID" or
    "vimeo:ID"), or "" when the match is neither."""
    group = _host_group(host)
    m = (match or "").strip()
    if group not in ("youtube", "vimeo") or not m:
        return "", ""
    low = m.lower()
    if low.startswith("channel="):
        return "channel", _norm_channel(m.split("=", 1)[1])
    if group == "youtube":
        vid = m.split(":", 1)[1] if low.startswith("youtube:") else m
        if _YT_ID.match(vid):
            return "video", "yt:" + vid
    else:
        vid = m.split(":", 1)[1] if low.startswith("vimeo:") else m
        if vid.isdigit():
            return "video", "vimeo:" + vid
    return "", ""


def _page_video_keys(page: Page) -> List[str]:
    url = page.video_url or ""
    keys = []
    for m in _YT_URL_ID.finditer(url):
        keys.append("yt:" + m.group(1))
    for m in _VIMEO_URL_ID.finditer(url):
        keys.append("vimeo:" + m.group(1))
    return keys


class _Index:
    """Lookup tables built once per AuditData (cached by identity)."""

    def __init__(self, data: AuditData):
        self.data = data
        self.pages_by_video: Dict[str, List[Page]] = defaultdict(list)
        self.pages_by_chan: Dict[str, List[Page]] = defaultdict(list)
        self.video_chan: Dict[str, str] = {}
        for page in data.pages:
            for k in _page_video_keys(page):
                self.pages_by_video[k].append(page)
                if page.channel and k not in self.video_chan:
                    self.video_chan[k] = _norm_channel(page.channel)
            if page.channel:
                self.pages_by_chan[_norm_channel(page.channel)].append(page)
        # keyed pins, by (host group, match lower) -- other stores' claims
        self.keyed: Dict[Tuple[str, str], List[Pin]] = defaultdict(list)
        # whole-host pins by bare host
        self.whole: Dict[str, List[Pin]] = defaultdict(list)
        # channel -> pins that speak for it
        self.chan_pins: Dict[str, List[Pin]] = defaultdict(list)  # channel= pins
        self.chan_video_pins: Dict[str, List[Pin]] = defaultdict(list)
        for pin in data.pins:
            if pin.store == core.STORE_ARCHIVE:
                continue
            if pin.match:
                self.keyed[(_host_group(pin.host), pin.match.strip().lower())].append(
                    pin
                )
                kind, key = parse_media_match(pin.host, pin.match)
                if kind == "channel":
                    self.chan_pins[key].append(pin)
                elif kind == "video":
                    chan = self.video_chan.get(key)
                    if chan:
                        self.chan_video_pins[chan].append(pin)
            else:
                self.whole[_bare(pin.host)].append(pin)
        self._tenant_pages: Dict[str, Dict[str, List[Page]]] = {}

    def tenant_pages(self, host: str) -> Dict[str, List[Page]]:
        """Archive pages on a keyed shared host, grouped by tenant key."""
        h = _bare(host)
        if h in self._tenant_pages:
            return self._tenant_pages[h]
        from app.utils.tenant_key import tenant_key

        out: Dict[str, List[Page]] = defaultdict(list)
        for page in self.data.pages_by_host.get(h, []):
            if _bare(page.source_host) != h or not page.gov_id:
                continue
            try:
                key = tenant_key(page.source_url)
            except Exception:  # a malformed URL must not stop the audit
                key = None
            if key:
                out[key.lower()].append(page)
        self._tenant_pages[h] = out
        return out


_INDEX_CACHE: List[_Index] = []


def _index(data: AuditData) -> _Index:
    for idx in _INDEX_CACHE:
        if idx.data is data:
            return idx
    idx = _Index(data)
    _INDEX_CACHE.append(idx)
    del _INDEX_CACHE[:-4]
    return idx


# ------------------------------------------------------------------ R4

_SEV_RANK = {s: i for i, s in enumerate(core.SEVERITIES)}


def _same_pin(a: Pin, b: Pin) -> bool:
    return a is b or (a.store, a.ref, a.host, a.match) == (
        b.store,
        b.ref,
        b.host,
        b.match,
    )


def _describe_pin_claims(pins: Sequence[Pin]) -> str:
    by_store: Dict[str, List[Pin]] = defaultdict(list)
    for p in pins:
        by_store[p.store].append(p)
    parts = []
    for store, ps in by_store.items():
        if len(ps) == 1:
            parts.append(f"the {store} entry {ps[0].ref}")
        else:
            parts.append(f"{len(ps)} {store} entries (e.g. {ps[0].ref})")
    return " and ".join(parts)


def _what(pin: Pin) -> str:
    return f"{pin.host} ({pin.match})" if pin.match else pin.host


def _r4_flags_for(pin: Pin, other_pins: Sequence[Pin], pages: Sequence[Page],
                  scope_text: str) -> List[Flag]:  # fmt: skip
    """Group claims by other government and emit one flag per (pin, gov)."""
    pins_by_gov: Dict[str, List[Pin]] = defaultdict(list)
    for o in other_pins:
        if not same_gov(pin.gov_id, o.gov_id):
            pins_by_gov[o.gov_id].append(o)
    pages_by_gov: Dict[str, List[Page]] = defaultdict(list)
    for pg in pages:
        if pg.gov_id and not same_gov(pin.gov_id, pg.gov_id):
            pages_by_gov[pg.gov_id].append(pg)
    flags: List[Flag] = []
    for gov in sorted(set(pins_by_gov) | set(pages_by_gov)):
        sev = disagreement_severity(pin.gov_id, gov)
        if sev is None:
            continue
        glabel = _gov_label(gov)
        if (
            sev == "high"
            and pin.store == core.STORE_RESEARCH
            and not pages_by_gov.get(gov)
            and all(o.store == core.STORE_RESEARCH for o in pins_by_gov[gov])
        ):
            sev = (
                "medium"  # two hand-typed research rows: one is wrong, which is unknown
            )
        bits = []
        refs = []
        if pins_by_gov.get(gov):
            bits.append(f"{_describe_pin_claims(pins_by_gov[gov])} name {glabel}")
            refs.append(pins_by_gov[gov][0].ref)
        if pages_by_gov.get(gov):
            n = len(pages_by_gov[gov])
            bits.append(
                f"{n} of {len(pages)} Archive page{'s' if len(pages) != 1 else ''} "
                f"{scope_text} {'are' if n != 1 else 'is'} filed under {glabel}"
            )
            refs.append(f"page {pages_by_gov[gov][0].page_id}")
        level = " (a county-versus-town level difference)" if sev == "low" else ""
        detail = (
            f"{pin.store} pins {_what(pin)} to {_gov_label(pin.gov_id)}, but "
            f"{'; '.join(bits)}{level}."
        )
        flags.append(
            Flag(
                "R4",
                sev,
                pin,
                other_gov_id=gov,
                other_ref=" + ".join(refs),
                detail=detail,
            )
        )
    return flags


def rule_r4_store_disagreement(data: AuditData, judged: Sequence[Pin]) -> List[Flag]:
    idx = _index(data)
    flags: List[Flag] = []
    for pin in judged:
        if pin.store == core.STORE_ARCHIVE:
            continue
        if not pin.match:
            flags.extend(_r4_whole_host(idx, pin))
        else:
            flags.extend(_r4_keyed(idx, pin))
    return flags


def _r4_whole_host(idx: _Index, pin: Pin) -> List[Flag]:
    if _is_multi_host(pin.host):
        return []
    bare = _bare(pin.host)
    others = [o for o in idx.whole.get(bare, []) if not _same_pin(o, pin)]
    pages = [
        pg
        for pg in idx.data.pages_by_host.get(bare, [])
        if _bare(pg.source_host) == bare and pg.gov_id
    ]
    if not others and not pages:
        return []
    govs = {pin.gov_id}
    for g in [o.gov_id for o in others] + [pg.gov_id for pg in pages]:
        if not any(same_gov(g, x) for x in govs):
            govs.add(g)
    if len(govs) >= _SHARED_HOST_GOVS:
        return [
            Flag(
                "R4", "note", pin,
                detail=(
                    f"{bare} carries claims for {len(govs)} different governments, so it "
                    "looks like a shared host; store disagreement was not judged."
                ),
            )
        ]  # fmt: skip
    return _r4_flags_for(pin, others, pages, "on this host")


def _r4_keyed(idx: _Index, pin: Pin) -> List[Flag]:
    group = _host_group(pin.host)
    key = (group, pin.match.strip().lower())
    others = [o for o in idx.keyed.get(key, []) if not _same_pin(o, pin)]
    pages: List[Page] = []
    kind, mkey = parse_media_match(pin.host, pin.match)
    if kind == "video":
        pages = [pg for pg in idx.pages_by_video.get(mkey, []) if pg.gov_id]
        # a video's `youtube:ID` and bare `ID` pins are the same claim
        for o in idx.keyed.get((group, mkey.split(":", 1)[1].lower()), []):
            if not _same_pin(o, pin) and o not in others:
                others.append(o)
        for o in idx.keyed.get((group, mkey.lower()), []):
            if not _same_pin(o, pin) and o not in others:
                others.append(o)
    elif kind == "channel":
        pages = [pg for pg in idx.pages_by_chan.get(mkey, []) if pg.gov_id]
        for o in idx.chan_pins.get(mkey, []):
            if not _same_pin(o, pin) and o not in others:
                others.append(o)
    elif group not in ("youtube", "vimeo"):
        from app.utils.tenant_key import pin_tenant_key

        try:
            tkey = pin_tenant_key(pin.host, pin.match)
        except Exception:
            tkey = None
        if tkey:
            pages = idx.tenant_pages(pin.host).get(tkey.lower(), [])
        # other keyed shapes: pages are skipped (no reliable page-side key)
    if not others and not pages:
        return []
    scope = "for this channel" if kind == "channel" else (
        "of this video" if kind == "video" else "of this tenant"
    )  # fmt: skip
    return _r4_flags_for(pin, others, pages, scope)


# ------------------------------------------------------------------ R3


def _state_sev(p_info: core.GovInfo, o_info: core.GovInfo) -> Optional[str]:
    ps, os_ = _states(p_info), _states(o_info)
    if not ps or not os_ or (ps & os_):
        return None  # unknown, or the same state: towns sharing a station are normal
    return "low" if core.states_adjacent(p_info.state, o_info.state) else "high"


def rule_r3_channel_coherence(data: AuditData, judged: Sequence[Pin]) -> List[Flag]:
    idx = _index(data)
    hub_handles = _hubs()[1]
    noted: Set[str] = set()
    flags: List[Flag] = []
    for pin in judged:
        if pin.store == core.STORE_ARCHIVE or not pin.match:
            continue
        kind, key = parse_media_match(pin.host, pin.match)
        if not kind:
            continue
        chan = key if kind == "channel" else idx.video_chan.get(key, "")
        if not chan:
            continue
        pinfo = core.gov_info(pin.gov_id)
        if pinfo is None or not _states(pinfo):
            continue
        # claims on the channel: (gov_id, ref, kind)
        claims: List[Tuple[str, str, str]] = []
        for o in idx.chan_pins.get(chan, []):
            if not _same_pin(o, pin):
                claims.append((o.gov_id, o.ref, "channel pin"))
        for o in idx.chan_video_pins.get(chan, []):
            if not _same_pin(o, pin):
                claims.append((o.gov_id, o.ref, "video pin"))
        for pg in idx.pages_by_chan.get(chan, []):
            if pg.gov_id:
                claims.append((pg.gov_id, f"page {pg.page_id}", "Archive page"))
        if not claims:
            continue
        all_states: Set[str] = set(list(_states(pinfo))[:1])
        for g, _r, _k in claims:
            st = sorted(_states(core.gov_info(g)))[:1]
            all_states.update(st)
        if any(h and h in chan for h in hub_handles):
            continue
        if len(all_states) >= _REGIONAL_STATES:
            if chan not in noted:
                noted.add(chan)
                flags.append(
                    Flag(
                        "R3", "note", pin,
                        detail=(
                            f"Channel {chan} has claims in {len(all_states)} states "
                            "(a statewide or regional network); it was not judged."
                        ),
                    )
                )  # fmt: skip
            continue
        found: Dict[str, Tuple[str, str, str]] = {}  # other gov -> (sev, ref, text)
        # A) a video pin that disagrees with the channel's own channel pin
        if kind == "video":
            for g, ref, ck in claims:
                if ck != "channel pin" or same_gov(g, pin.gov_id):
                    continue
                oinfo = core.gov_info(g)
                sev = _state_sev(pinfo, oinfo) if oinfo else None
                if sev and (g not in found or _SEV_RANK[sev] < _SEV_RANK[found[g][0]]):
                    found[g] = (
                        sev, ref,
                        f"the channel {chan} is pinned to {_gov_label(g)} ({ref}), "
                        f"but this video is pinned to {_gov_label(pin.gov_id)}",
                    )  # fmt: skip
        # B) the pin's state differs from the state most claims agree on
        by_state: Dict[str, List[Tuple[str, str, str]]] = defaultdict(list)
        for c in claims:
            if same_gov(c[0], pin.gov_id):
                by_state["__same__"].append(c)
                continue
            ss = sorted(_states(core.gov_info(c[0])))
            if ss:
                by_state[ss[0]].append(c)
        total = len(claims)
        for st, cs in by_state.items():
            if st == "__same__" or len(cs) < 2 or len(cs) * 2 <= total:
                continue
            if st in _states(pinfo):
                continue
            top_gov = Counter(c[0] for c in cs).most_common(1)[0][0]
            oinfo = core.gov_info(top_gov)
            sev = _state_sev(pinfo, oinfo) if oinfo else None
            if not sev or any(
                _states(core.gov_info(g)) & _states(oinfo) for g in found
            ):
                continue
            ref = next(c[1] for c in cs if c[0] == top_gov)
            found[top_gov] = (
                sev, ref,
                f"{len(cs)} of the {total} other claims on channel {chan} "
                f"(pins and Archive pages) are in {_gov_label(top_gov)}'s state, "
                f"but this pin is {_gov_label(pin.gov_id)}",
            )  # fmt: skip
        for g, (sev, ref, text) in found.items():
            flags.append(
                Flag("R3", sev, pin, other_gov_id=g, other_ref=ref, detail=text + ".")
            )
    return flags


RULES = [rule_r3_channel_coherence, rule_r4_store_disagreement]
