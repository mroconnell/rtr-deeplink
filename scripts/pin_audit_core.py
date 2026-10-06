"""Pin audit: the shared data model and loaders (read-only).

A *pin* is any stored claim that a host, a keyed channel, a video or a
meeting belongs to one government. Pins live in several stores, and a
wrong one is trusted almost everywhere (the Sunnyside case, 2026-10-05:
`sunnyside.primegov.com` sat on Sunnyside NL while two other pins and the
city's own YouTube handle said Sunnyside WA, and nothing compared them).

This module turns every store into one list of `Pin` rows plus the saved
Archive pages, so the rules in `pin_audit_name_rules.py` and
`pin_audit_store_rules.py` can look for pins that contradict each other or
look improbable. `scripts/pin_audit.py` is the command that runs them.

Nothing here writes to any store. Files in sibling repos (rtr-business,
rtr-discovery) are optional: a missing one is reported, never guessed.

CONTRACT (shared by the rule modules -- change only with the conductor):

  Pin, Page, GovInfo, Flag, AuditData   the dataclasses below
  load_all(paths) -> AuditData          every store, every page
  gov_info(gov_id) -> Optional[GovInfo] cached registry lookup
  base_name(name) -> str                "City of Sunnyside" -> "sunnyside"
  twins(gov_id) -> FrozenSet[str]       other gov_ids with the same base name
  states_adjacent(a, b) -> bool         True for the same or a bordering
                                        state/province
  select_pins(data, scope, seed) -> List[Pin]   the pins to judge

A rule is `def rule_xx(data: AuditData, judged: Sequence[Pin]) -> List[Flag]`.
It judges only `judged` but may compare against everything in `data`
(a contradiction needs the other side, which is usually not sampled).
"""

from __future__ import annotations

import csv
import random
import re
import sqlite3
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Tuple
from urllib.parse import urlsplit

if str(Path(__file__).resolve().parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

csv.field_size_limit(sys.maxsize)

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "app" / "utils" / "jurisdiction_data"
AUDIT_DATA_DIR = REPO_ROOT / "scripts" / "pin_audit_data"
DOCUMENTS = (
    REPO_ROOT.parent
    if (REPO_ROOT.parent / "rtr-business").exists()
    else (Path.home() / "Documents")
)

# Store names, used in Pin.store and in the report.
STORE_OVERRIDE = "tenant_overrides"  # tenant_overrides.csv, every row
STORE_QUEUE = "tier3_queue"  # scripts/tier3_auto_transcription_queue.txt
STORE_QUEUE_DEFERRED = "tier3_deferred"  # scripts/tier3_long_meetings_deferred.txt
STORE_CIVICPLUS = "civicplus_authorities"  # civicplus_authorities.csv
STORE_RESEARCH = "research_row"  # rtr-business jurisdiction_coverage.csv domain
STORE_DISCOVERY = "discovery_tenant"  # rtr-discovery ledger.db tenants.gov_id
STORE_ARCHIVE = "archive_page"  # a saved Archive page's own gov_id

SEVERITIES = ("high", "medium", "low", "note")  # most severe first


@dataclass(frozen=True)
class Pin:
    store: str  # one of the STORE_* names
    host: str  # lowercase host, "www." kept as written in the store
    match: str  # "" for a whole-host claim; else the override's match text
    gov_id: str
    source: str = ""  # the store's own source column, if any
    evidence: str = ""  # the store's own evidence text, if any
    ref: str = ""  # where to find it: "tenant_overrides.csv:1327", "page 7492"
    url: str = ""  # a full URL where the store has one
    title: str = ""  # a meeting title where the store has one
    channel: str = ""  # a YouTube/Vimeo handle or channel key, as a plain string


@dataclass(frozen=True)
class Page:
    """One saved Archive page (the meeting-inventory export)."""

    page_id: str
    gov_id: str
    title: str  # meeting_name
    stored_jurisdiction: str
    source_url: str
    video_url: str
    source_host: str  # lowercase host of source_url
    video_host: str  # lowercase host of video_url
    channel: str  # video_channel, e.g. "@cityofsunnysidewa"


@dataclass(frozen=True)
class GovInfo:
    gov_id: str
    name: str  # registry display name, e.g. "Sunnyside"
    state: str  # two-letter state/province code, upper case; "" if unknown
    country: str  # "us" / "ca"
    kind: str  # gov_id namespace: "us:place", "ca:csd", "rtr:us", ...
    base: str  # base_name(name)


@dataclass(frozen=True)
class Flag:
    rule: str  # "R1" .. "R6"
    severity: str  # one of SEVERITIES
    pin: Pin
    other_gov_id: str = ""  # the government the evidence points at, if any
    other_ref: str = ""  # what the pin contradicts ("tenant_overrides.csv:6757")
    detail: str = ""  # one plain-English sentence for Ryan


@dataclass
class AuditData:
    pins: List[Pin] = field(default_factory=list)  # every store
    pages: List[Page] = field(default_factory=list)
    missing: List[str] = field(default_factory=list)  # optional files not found
    # Indexes, built by load_all():
    pins_by_host: Dict[str, List[Pin]] = field(default_factory=dict)
    pages_by_host: Dict[str, List[Page]] = field(
        default_factory=dict
    )  # by source_host and video_host
    pages_by_channel: Dict[str, List[Page]] = field(
        default_factory=dict
    )  # lowercase channel


# ---------------------------------------------------------------- loaders


def _host_of(url: str) -> str:
    """Lowercase host of a URL, "" if there is none. Port is dropped."""
    url = (url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "//" + url
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _domain_host(raw: str) -> Tuple[str, bool]:
    """A research-sheet `domain` cell -> (host, had_path). Cells are hand
    typed: "https:www.x.gov", "x.org (google sites)", "x.com/gov/page"."""
    raw = (raw or "").strip().lower()
    if not raw:
        return "", False
    raw = raw.split()[0]
    raw = re.sub(r"^https?:/*", "", raw)
    host, slash, rest = raw.partition("/")
    host = host.split(":")[0].strip(".")
    return host, bool(slash and rest.strip("/"))


def _default_inventory() -> Path:
    base = (
        DOCUMENTS
        / "rtr-business"
        / "research"
        / "shared_station_census_2026-09-30"
        / "run2"
        / "inputs_meeting_inventory.csv"
    )
    tmp = Path("/tmp/rtr_meeting_inventory/meeting_inventory.csv")
    try:
        if tmp.exists() and (
            not base.exists() or tmp.stat().st_mtime > base.stat().st_mtime
        ):
            return tmp
    except OSError:
        pass
    return base


def _default_paths() -> Dict[str, Path]:
    return {
        "overrides": DATA_DIR / "tenant_overrides.csv",
        "queue": REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt",
        "queue_deferred": REPO_ROOT / "scripts" / "tier3_long_meetings_deferred.txt",
        "civicplus": DATA_DIR / "civicplus_authorities.csv",
        "research": DOCUMENTS
        / "rtr-business"
        / "research"
        / "jurisdiction_coverage.csv",
        "discovery": DOCUMENTS / "rtr-discovery" / "ledger.db",
        "inventory": _default_inventory(),
    }


def _load_overrides(path: Path, out: List[Pin]) -> None:
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            gov = (row.get("gov_id") or "").strip()
            host = (row.get("tenant_host") or "").strip().lower()
            if not gov or not host:
                continue
            out.append(
                Pin(
                    STORE_OVERRIDE,
                    host,
                    (row.get("match") or "").strip(),
                    gov,
                    source=(row.get("source") or "").strip(),
                    evidence=(row.get("evidence") or "").strip(),
                    ref=f"tenant_overrides.csv:{reader.line_num}",
                )
            )


def _load_queue(path: Path, store: str, out: List[Pin]) -> None:
    from app.platforms.queue_probe import parse_queue_entry

    name = path.name
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            if store == STORE_QUEUE_DEFERRED:
                # The deferred file's columns 4-6 differ (jurisdiction,
                # duration, title); columns 1-3 match, so read just those.
                entry = parse_queue_entry("\t".join(line.split("\t")[:3]))
                title = ""
                parts = line.split("\t")
                if len(parts) > 5:
                    title = parts[5].strip()
            else:
                entry = parse_queue_entry(line)
                title = entry.title or ""
            if not entry.gov_id:
                continue
            url = entry.source_url or entry.url
            host = _host_of(url)
            if not host:
                continue
            out.append(
                Pin(
                    store,
                    host,
                    "",
                    entry.gov_id,
                    ref=f"{name}:{n}",
                    url=url,
                    title=title,
                )
            )


def _load_civicplus(path: Path, out: List[Pin]) -> None:
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            gov = (row.get("gov_id") or "").strip()
            host = (row.get("tenant_host") or "").strip().lower()
            if gov and host:
                out.append(
                    Pin(
                        STORE_CIVICPLUS,
                        host,
                        "",
                        gov,
                        source=f"confirmed={(row.get('confirmed') or '').strip()}",
                        ref=f"civicplus_authorities.csv:{reader.line_num}",
                    )
                )


def _load_research(path: Path, out: List[Pin]) -> None:
    from app.utils.gov_registry import registry

    shared = registry.MULTI_GOV_HOSTS
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            gov = (row.get("gov_id") or "").strip()
            if not gov:
                continue
            cells = [row.get("domain") or ""] + (
                row.get("alternate_domains") or ""
            ).split(";")
            seen = set()
            for cell in cells:
                host, _had_path = _domain_host(cell)
                if not host or "." not in host or host in seen:
                    continue
                # A shared host (sites.google.com/view/x, facebook.com) is not a
                # whole-host claim for one government; drop it rather than pin it.
                if host in shared:
                    continue
                seen.add(host)
                out.append(
                    Pin(
                        STORE_RESEARCH,
                        host,
                        "",
                        gov,
                        source=(row.get("reject_reason") or "").strip(),
                        ref=f"jurisdiction_coverage.csv:{reader.line_num}",
                        title=(row.get("city_name") or "").strip(),
                    )
                )


def _load_discovery(path: Path, out: List[Pin]) -> None:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        # netloc is the primary key and is "host#tenant_key" for shared hosts
        # such as play.champds.com#atlantaga; `host` holds the bare host and
        # `tenant_key` the narrowing key. So the pin is (host, match=tenant_key):
        # empty tenant_key = whole-host claim. `params` (view ids, tabs) only
        # lists what to enumerate, it does not narrow identity, so it is ignored.
        cur = con.execute(
            "select rowid, netloc, host, tenant_key, gov_id, source from tenants "
            "where gov_id is not null and gov_id != ''"
        )
        for rowid, netloc, host, key, gov, source in cur:
            h = (host or netloc or "").split("#")[0].strip().lower()
            if not h:
                continue
            out.append(
                Pin(
                    STORE_DISCOVERY,
                    h,
                    (key or "").strip(),
                    gov.strip(),
                    source=(source or "").strip(),
                    ref=f"ledger.db tenants:{netloc}",
                )
            )
    finally:
        con.close()


def _load_inventory(path: Path, pages: List[Page], pins: List[Pin]) -> None:
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            pid = (row.get("page_id") or "").strip()
            gov = (row.get("gov_id") or "").strip()
            src = (row.get("source_url") or "").strip()
            vid = (row.get("video_url") or "").strip()
            title = (row.get("meeting_name") or "").strip()
            chan = (row.get("video_channel") or "").strip()
            sh, vh = _host_of(src), _host_of(vid)
            pages.append(
                Page(
                    pid,
                    gov,
                    title,
                    (row.get("stored_jurisdiction") or "").strip(),
                    src,
                    vid,
                    sh,
                    vh,
                    chan,
                )
            )
            if gov and sh:
                pins.append(
                    Pin(
                        STORE_ARCHIVE,
                        sh,
                        "",
                        gov,
                        ref=f"page {pid}",
                        url=src,
                        title=title,
                        channel=chan,
                    )
                )


def _host_keys(host: str) -> List[str]:
    """Index keys for a host: as written, plus with a leading "www." stripped,
    so a lookup by either spelling finds the same rows."""
    host = (host or "").lower()
    if not host:
        return []
    keys = [host]
    if host.startswith("www."):
        keys.append(host[4:])
    return keys


def build_indexes(data: AuditData) -> None:
    """(Re)build the three indexes from data.pins / data.pages."""
    data.pins_by_host = {}
    data.pages_by_host = {}
    data.pages_by_channel = {}
    for pin in data.pins:
        for k in _host_keys(pin.host):
            data.pins_by_host.setdefault(k, []).append(pin)
    for page in data.pages:
        seen = set()
        for h in (page.source_host, page.video_host):
            for k in _host_keys(h):
                if k not in seen:
                    seen.add(k)
                    data.pages_by_host.setdefault(k, []).append(page)
        if page.channel:
            data.pages_by_channel.setdefault(page.channel.lower(), []).append(page)


def load_all(paths: Optional[Dict[str, Path]] = None) -> AuditData:
    resolved = _default_paths()
    for k, v in (paths or {}).items():
        resolved[k] = Path(v)
    data = AuditData()
    loaders = [
        ("overrides", lambda p: _load_overrides(p, data.pins)),
        ("queue", lambda p: _load_queue(p, STORE_QUEUE, data.pins)),
        ("queue_deferred", lambda p: _load_queue(p, STORE_QUEUE_DEFERRED, data.pins)),
        ("civicplus", lambda p: _load_civicplus(p, data.pins)),
        ("research", lambda p: _load_research(p, data.pins)),
        ("discovery", lambda p: _load_discovery(p, data.pins)),
        ("inventory", lambda p: _load_inventory(p, data.pages, data.pins)),
    ]
    for key, fn in loaders:
        path = resolved[key]
        if not path.exists():
            if key == "overrides":
                raise FileNotFoundError(f"tenant_overrides.csv not found at {path}")
            data.missing.append(f"{key}: file not found ({path})")
            continue
        fn(path)
    build_indexes(data)
    return data


# ---------------------------------------------------------------- registry

_NAMESPACES = ("us:place", "us:cousub", "us:county", "ca:csd", "ca:cd")
_MINTED_RE = re.compile(r"^rtr:([a-z]{2}):([^:]*):(.+)$")


@lru_cache(maxsize=None)
def gov_info(gov_id: str) -> Optional[GovInfo]:
    from app.utils.gov_registry import registry

    gov_id = (gov_id or "").strip()
    if not gov_id:
        return None
    g = registry.government_for_id(gov_id)
    if g is not None:
        if gov_id.startswith("rtr:"):
            m = _MINTED_RE.match(gov_id)
            kind = f"rtr:{m.group(1)}" if m else "rtr:unknown"
        else:
            kind = gov_id.rpartition(":")[0]
        return GovInfo(
            gov_id,
            g.gov_name,
            (g.state or "").upper(),
            g.country,
            kind,
            base_name(g.gov_name),
        )
    m = _MINTED_RE.match(gov_id)
    if m:
        cc, st, slug = m.groups()
        name = slug.replace("-", " ")
        return GovInfo(gov_id, name, st.upper(), cc, f"rtr:{cc}", base_name(name))
    return None


_DROP_WORDS = frozenset(
    "city town village township borough county municipality municipal parish charter of the".split()
)


def base_name(name: str) -> str:
    s = (name or "").lower()
    s = re.sub(r"\([^)]*\)", " ", s)
    s = re.sub(r"[^\w\s]", " ", s)
    words = []
    for w in s.split():
        if w in _DROP_WORDS:
            continue
        if w in ("saint", "st"):
            w = "st"
        elif w in ("mount", "mt"):
            w = "mt"
        words.append(w)
    return " ".join(words)


@lru_cache(maxsize=1)
def _twin_index() -> Tuple[Dict[str, FrozenSet[str]], Dict[str, str]]:
    """(base name -> gov_ids, gov_id -> base name) over every national table
    row, every registry government and every curated row."""
    from app.utils.gov_registry import registry, tables

    by_id: Dict[str, str] = {}
    for ns, table in (
        ("us:place", tables.us_places()),
        ("us:cousub", tables.us_cousubs()),
        ("us:county", tables.us_counties()),
        ("ca:csd", tables.ca_csd()),
        ("ca:cd", tables.ca_cd()),
    ):
        for row in table.rows():
            by_id[f"{ns}:{row.row_id}"] = base_name(row.name)
    for gid, g in registry.governments().items():
        by_id[gid] = base_name(g.gov_name)  # the registry's own name wins
    idx: Dict[str, set] = {}
    for gid, b in by_id.items():
        if b:
            idx.setdefault(b, set()).add(gid)
    return {b: frozenset(v) for b, v in idx.items()}, by_id


@lru_cache(maxsize=None)
def twins(gov_id: str) -> FrozenSet[str]:
    from app.utils.gov_registry import registry

    idx, by_id = _twin_index()
    base = by_id.get(gov_id)
    if base is None:
        info = gov_info(gov_id)
        base = info.base if info else ""
    if not base:
        return frozenset()
    canon = registry.consolidated()

    def same(x: str) -> str:
        return canon.get(x, x)

    me = same(gov_id)
    return frozenset(o for o in idx.get(base, ()) if o != gov_id and same(o) != me)


@lru_cache(maxsize=1)
def _adjacency() -> FrozenSet[Tuple[str, str]]:
    path = AUDIT_DATA_DIR / "state_adjacency.csv"
    pairs = set()
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            a, b = r["a"].strip().upper(), r["b"].strip().upper()
            pairs.add((a, b))
            pairs.add((b, a))
    return frozenset(pairs)


def states_adjacent(a: str, b: str) -> bool:
    """True for the same state/province or a land (or river) border. A
    cross-border minted state like "AB/SK" matches if any part does."""
    xs = [p for p in (a or "").upper().replace(",", "/").split("/") if p.strip()]
    ys = [p for p in (b or "").upper().replace(",", "/").split("/") if p.strip()]
    adj = _adjacency()
    return any(x == y or (x, y) in adj for x in xs for y in ys)


# ---------------------------------------------------------------- selection


def select_pins(data: AuditData, scope: str, seed: int = 20261006) -> List[Pin]:
    from app.utils.gov_registry import registry

    base = [p for p in data.pins if p.store != STORE_ARCHIVE]
    if scope == "all":
        return base
    if scope == "ambiguous":
        return [p for p in base if twins(p.gov_id)]
    if scope != "pilot":
        raise ValueError(f"unknown scope {scope!r} (all, ambiguous, pilot)")

    def usable(p: Pin) -> bool:
        if p.store != STORE_OVERRIDE or not twins(p.gov_id):
            return False
        # Whole-host pins on a shared host are rejected by the registry
        # anyway; keyed rows there are fair game.
        return not (not p.match and p.host in registry.MULTI_GOV_HOSTS)

    pool = sorted(
        (p for p in base if usable(p)),
        key=lambda p: (p.host, p.match, p.gov_id, p.ref),
    )
    machine = ("step0_dns_full", "wildcard_http_sweep_2")
    g1 = [p for p in pool if any(m in p.source for m in machine)]
    g3 = [p for p in pool if "ryan_stated" in p.source]
    taken = set(g1) | set(g3)
    g2 = [p for p in pool if p not in taken]
    rng = random.Random(seed)
    out: List[Pin] = []
    for group, n in ((g1, 40), (g2, 30), (g3, 30)):
        out.extend(rng.sample(group, min(n, len(group))))
    return out
