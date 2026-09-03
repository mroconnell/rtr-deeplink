"""Regenerate `reports/pin_worklist.csv` -- one row per tenant a human
still has to name, with a best-guess proposal attached.

Phase 2c of `rtr-business/research/GOVERNMENT_IDENTITY_ARCHITECTURE.md`.
Phase 2 keyed 4,582 of 5,053 archived pages; what is left is 471
`unresolved` pages (a real government name the ladder could not key) and
241 `blank` ones (nothing extracted at all). Neither can be fixed by a
better resolver: the raw adapter string is gone, so the only thing that
settles them is a human saying which government the tenant is -- a
`tenant_overrides.csv` pin.

This script builds the sheet that human fills in, and
`scripts/apply_pin_worklist.py` turns the filled sheet back into pins.
Between them Ryan never types a `gov_id`: he types a name in plain
English, or "ok" to accept a proposal, or "skip".

**Read-only against production**: one keyset-paginated sweep of
`GET /internal/export/pages` (metadata only, no `segments` -- WO-93's
light shape), the same way `scripts/score_gov_registry.py` reads it. It
writes two local files and nothing else. It never writes a pin.

The proposal columns are a convenience, not an authority. `proposed_name`
is filled only when a cheap signal resolves to a *national-table*
government AND the signal is plainly that government's own name --
`gov_registry.is_own_name()`, the acceptance rule the landing-page
sweep's first run lacked and that six poisonous pins taught it. A signal
that resolves to a minted `rtr:` id, or that merely contains something
the resolver could key on ("Howard County Public School System" reaching
Howard *County*), leaves the row unproposed. That costs real coverage and
it is the right trade: a wrong proposal Ryan rubber-stamps is worse than
a blank he fills in himself.

Four signals, all quoted in `proposed_evidence`:

  * the **hostname** -- `desplainesil.cablecast.tv` -> "desplaines, IL",
    `pgcps.cablecast.tv` -> the school-district acronym index;
  * the **page slugs and titles** -- an n-gram ending in a government
    type word, `...-coppell-independent-school-district`;
  * the **YouTube channel title** for the shared YouTube hosts, and
    `rtr-business/research/telvue_org_tokens.md` for TelVue;
  * the **Swagit page footer** -- every real Swagit customer's template
    renders "{NAME} Video Archive / Powered by Swagit", the tenant naming
    itself, confirmed live on 6 real hosts 2026-09-03. The one signal
    here that costs a live fetch (one GET per Swagit host, cached to
    `reports/pin_worklist_swagit.csv` so a re-run costs nothing) -- worth
    it given BACKLOG.md's own finding that Swagit's `<title>`/`<h1>` are
    generic ("SwagitAdmin") and nothing else here can settle it.

Usage:
    python scripts/build_pin_worklist.py
    python scripts/build_pin_worklist.py --archive-cache /tmp/export.json
    python scripts/build_pin_worklist.py --no-youtube      # skip oEmbed
    python scripts/build_pin_worklist.py --refresh-youtube # re-fetch it
    python scripts/build_pin_worklist.py --no-swagit       # skip footer fetch
"""

import argparse
import asyncio
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Sequence, Tuple
from urllib.parse import urlparse

import certifi

# Before `import aiohttp`, not merely before the first request: aiohttp
# builds and caches its default SSLContext as a module-level statement,
# and a fresh Homebrew-Python venv has an empty trust store. CLAUDE.md's
# own entry, and the ordering that silently dropped a 48-URL batch once.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.utils.gov_registry import (  # noqa: E402
    display_name,
    is_own_name,
    registry,
    resolve_government,
)
from app.utils.gov_registry import tables  # noqa: E402

# The shared checkout's .env, not the worktree's -- CLAUDE.md's worktree
# note. Only presence is ever used here; no value is printed.
load_dotenv(REPO_ROOT / ".env")
load_dotenv(Path.home() / "Documents" / "rtr-deeplink" / ".env")

WORKLIST = REPO_ROOT / "reports" / "pin_worklist.csv"
# video id -> channel, kept beside the worklist because it is both the
# evidence behind a YouTube proposal and the map `apply_pin_worklist.py`
# needs to turn one channel decision into the per-video pin rows the
# resolver can actually match (see `_YOUTUBE_HOSTS` below).
YOUTUBE_MAP = REPO_ROOT / "reports" / "pin_worklist_youtube.csv"
TELVUE_TOKENS = (
    Path.home() / "Documents" / "rtr-business" / "research" / "telvue_org_tokens.md"
)

WORKLIST_HEADER = [
    "platform",
    "tenant_host",
    "match",
    "pages",
    "stored_names",
    "example_slug",
    "landing_url",
    "swagit_footer",
    "proposed_name",
    "proposed_gov_id",
    "proposed_evidence",
    "ryan_gov_name",
    "ryan_note",
]
# Ryan's two columns. Preserved across a regeneration by (tenant_host,
# match) -- rebuilding the sheet must never discard an answer already on
# it, which is the whole reason this script merges rather than truncates.
ANSWER_COLUMNS = ("ryan_gov_name", "ryan_note")

PLATFORM_ORDER = ["escribe", "cablecast", "swagit", "telvue", "youtube"]

# The tiers that want a pin. `unresolved` is a real government name the
# ladder could not key (gov_id NULL); `blank` is nothing extracted at all
# (gov_id `rtr:unknown:<host>`). Every other tier already has an answer.
WANTED_TIERS = ("unresolved", "blank")

# Hosts where the netloc is NOT the tenant -- every government on them
# shares one host, so a host-level pin would be wrong for all of them.
_YOUTUBE_HOSTS = {"youtu.be", "www.youtube.com", "youtube.com", "m.youtube.com"}

# TelVue's per-customer identifier is an opaque token in the URL PATH
# (`videoplayer.telvue.com/player/{org_token}/...`), not a subdomain --
# same situation, different shape. Copied from score_gov_registry.py,
# which is where this worklist's ancestor computed it.
_TELVUE_TOKEN_RE = re.compile(r"/player/([A-Za-z0-9_\-]{16,})", re.I)

# A row in `telvue_org_tokens.md` whose jurisdiction cell says out loud
# that it is not settled. Matched against the cell as written, before any
# cleanup, so a hedge cannot be trimmed away into a confident-looking name.
_TELVUE_HEDGE_RE = re.compile(
    r"unconfirmed|unidentified|multi-jurisdiction|likely|not disambiguated", re.I
)

PAGE_DELAY_SECONDS = 1.0
YOUTUBE_DELAY_SECONDS = 0.6
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


# --------------------------------------------------------------------------
# Reading production (over HTTP, read-only)
# --------------------------------------------------------------------------


async def fetch_export_pages(base_url: str, token: str, limit: int = 500) -> List[dict]:
    """Keyset-paginated metadata sweep -- never asking for segments, so no
    blob is touched. ~11 requests for the whole Archive."""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{base_url.rstrip('/')}/internal/export/pages"
    pages: List[dict] = []
    after_id = 0
    async with aiohttp.ClientSession() as session:
        while True:
            async with session.get(
                url,
                params={"after_id": after_id, "limit": limit},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=180),
            ) as resp:
                if resp.status != 200:
                    raise SystemExit(
                        f"GET {url} -> HTTP {resp.status} (a 404 usually means a bad "
                        "ARCHIVE_INGEST_TOKEN -- the route hides behind it)"
                    )
                body = await resp.json()
            pages.extend(body.get("pages") or [])
            print(f"  fetched {len(pages)} pages", end="\r", flush=True)
            after_id = body.get("next_after_id")
            if after_id is None:
                break
            await asyncio.sleep(PAGE_DELAY_SECONDS)
    print(f"  fetched {len(pages)} pages      ")
    return pages


_YOUTUBE_ID_RE = re.compile(
    r"(?:youtu\.be/|/live/|/embed/|/shorts/|[?&]v=)([A-Za-z0-9_-]{11})"
)


def youtube_video_id(source_url: str) -> str:
    m = _YOUTUBE_ID_RE.search(source_url or "")
    return m.group(1) if m else ""


async def fetch_youtube_channels(
    video_ids: Sequence[str], known: Dict[str, dict]
) -> Dict[str, dict]:
    """video id -> {"channel", "channel_title"} via YouTube's public oEmbed
    endpoint.

    One documented, unauthenticated GET per video, ~0.6s apart, and only
    for ids not already in `known` -- so a re-run of this script costs no
    YouTube traffic at all. oEmbed is the polite way to ask this question:
    it is the endpoint YouTube publishes for exactly this ("who made this
    video"), it needs no key, and it is not the caption path yt-dlp exists
    to work around.

    `channel` is the channel's public handle (`@PhillyCityCouncil`), read
    out of oEmbed's `author_url`. That is the identifier a reader can
    check, and the grouping key for one human decision per channel; the
    per-video ids under it are what a pin is actually written against.
    """
    out = dict(known)
    todo = [v for v in video_ids if v and v not in out]
    if not todo:
        return out
    print(f"  {len(todo)} new videos to identify ({len(out)} cached)")
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        for i, vid in enumerate(todo, 1):
            payload = None
            try:
                async with session.get(
                    "https://www.youtube.com/oembed",
                    params={
                        "url": f"https://www.youtube.com/watch?v={vid}",
                        "format": "json",
                    },
                    timeout=aiohttp.ClientTimeout(total=20),
                ) as resp:
                    if resp.status == 200:
                        payload = await resp.json(content_type=None)
            except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):
                payload = None
            if payload:
                author_url = payload.get("author_url") or ""
                handle = author_url.rstrip("/").rsplit("/", 1)[-1]
                out[vid] = {
                    "channel": handle,
                    "channel_title": (payload.get("author_name") or "").strip(),
                }
            else:
                # A deleted or private video. Recorded as a miss rather
                # than retried: it will never answer, and leaving it out
                # would make every future run fetch it again.
                out[vid] = {"channel": "", "channel_title": ""}
            print(
                f"  [{i}/{len(todo)}] {vid} {out[vid]['channel_title'][:44]}", end="\r"
            )
            await asyncio.sleep(YOUTUBE_DELAY_SECONDS)
    print(" " * 78, end="\r")
    return out


# Every real Swagit customer's template renders `<div class="footer">
# <p>{NAME} Video Archive / <a href="...">Powered by Swagit</a></p>
# </div>` -- confirmed live 2026-09-03 on 6 real, varied hosts (Alameda
# USD, Coppell ISD, Brevard Public Schools, McKinney ISD, Dallas Area
# Rapid Transit, Howard County Public Schools -- the last matching the
# REGISTRY's own spelling of that district exactly). Far more reliable
# than a slug or a hostname guess: it is the tenant naming ITSELF, in a
# template every customer shares and nobody customizes -- exactly why
# Swagit's `<title>`/`<h1>` are useless (BACKLOG.md's "SwagitAdmin"
# finding) but its footer is not. Captures up to " Video Archive" only,
# never "Powered by Swagit" -- the vendor's own name never enters the
# candidate at all, so no vendor-noise stripping is needed downstream.
_SWAGIT_FOOTER_RE = re.compile(
    r'<div class="footer">\s*<p>\s*(.+?)\s+Video Archive\b', re.I | re.S
)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def swagit_footer_name(html: str) -> str:
    """The government's own name, straight from a Swagit page's footer, or
    "" if the page doesn't have the shape above (a non-Swagit page, or a
    Swagit page that failed to load).

    Shared with `scripts/sweep_tenant_landing_pages.py` (which imports
    this rather than keeping its own copy) -- both need the exact same
    pattern, and the poisonous-pin lesson `is_own_name()` already exists
    to avoid applies just as much to two regexes quietly drifting apart.
    """
    m = _SWAGIT_FOOTER_RE.search(html or "")
    if not m:
        return ""
    from html import unescape

    name = unescape(_TAG_RE.sub(" ", m.group(1)))
    return _WS_RE.sub(" ", name).strip()


SWAGIT_MAP = REPO_ROOT / "reports" / "pin_worklist_swagit.csv"
SWAGIT_DELAY_SECONDS = 1.0


async def fetch_swagit_footers(
    hosts: Sequence[str], known: Dict[str, str]
) -> Dict[str, str]:
    """host -> footer name (or "" for a miss), one GET per host not
    already in `known` -- same caching shape as `fetch_youtube_channels()`
    and for the same reason: a re-run of this script costs nothing against
    a host already answered.
    """
    out = dict(known)
    todo = [h for h in hosts if h and h not in out]
    if not todo:
        return out
    print(f"  {len(todo)} new hosts to check ({len(out)} cached)")
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(headers=headers) as session:
        for i, host in enumerate(todo, 1):
            name = ""
            try:
                async with session.get(
                    f"https://{host}/",
                    timeout=aiohttp.ClientTimeout(total=20),
                    ssl=False,
                ) as resp:
                    if resp.status == 200:
                        name = swagit_footer_name(await resp.text(errors="replace"))
            except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
                name = ""
            out[host] = name
            print(f"  [{i}/{len(todo)}] {host:44} {name[:40]}", end="\r")
            await asyncio.sleep(SWAGIT_DELAY_SECONDS)
    print(" " * 90, end="\r")
    return out


def read_swagit_map(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as fh:
        return {
            row["tenant_host"]: row.get("footer_name") or ""
            for row in csv.DictReader(fh)
            if row.get("tenant_host")
        }


def write_swagit_map(footers: Dict[str, str], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["tenant_host", "footer_name"])
        for host in sorted(footers):
            writer.writerow([host, footers[host]])


# --------------------------------------------------------------------------
# The proposal signals
# --------------------------------------------------------------------------

# Registrable domains that belong to a VIDEO PLATFORM rather than to a
# government. On one of these the tenant is the first label
# (`desplainesil.cablecast.tv`); on anything else the host is the
# government's own domain and the tenant is the second-level label
# (`www.townofrossca.gov` -> "townofrossca"), which is the richer signal
# of the two -- those labels carry a state far more often.
PLATFORM_DOMAINS = frozenset(
    {
        "granicus.com",
        "cablecast.tv",
        "civicweb.net",
        "escribemeetings.com",
        "swagit.com",
        "primegov.com",
        "iqm2.com",
        "legistar.com",
        "civicclerk.com",
        "municodemeetings.com",
        "clerkshq.com",
        "champds.com",
        "castus.tv",
        "peg.tv",
        "telvue.com",
        "townhallstreams.com",
        "destinyhosted.com",
        "openpublica.com",
        "youtube.com",
        "youtu.be",
        "vimeo.com",
    }
)

# Decoration a station or a platform puts around its customer's name.
# Stripped from BOTH ends and only as whole hyphen-separated tokens, so
# "tv" comes off `tvhamilton` but not out of the middle of a real word.
_HOST_NOISE = frozenset(
    {
        "pub",
        "vod",
        "new",
        "www",
        "tv",
        "video",
        "media",
        "reflect",
        "portal",
        "meetings",
        "cablecast",
        "live",
        "gov",
    }
)
_HOST_ENTITY_PREFIXES = ("cityof", "townof", "countyof", "villageof", "townshipof")

# The type words a government's name ends with. An n-gram from a slug is
# only tested as a candidate when it ends in one of these (or starts with
# an entity prefix) -- which turns a blind sweep of every word window
# into a named-entity signal, and is what makes
# "...-coppell-independent-school-district" a candidate while
# "...-board-workshop-" is not.
_TERMINAL_TYPE_WORDS = frozenset(
    {
        "county",
        "parish",
        "borough",
        "township",
        "village",
        "district",
        "schools",
        "isd",
        "usd",
        "municipality",
    }
)
_TERMINAL_TYPE_PHRASES = frozenset(
    {
        "school district",
        "school system",
        "public schools",
        "community schools",
        "county schools",
        "city schools",
    }
)
_LEADING_ENTITY_WORDS = frozenset(
    {"city", "town", "county", "village", "township", "borough"}
)

_SLUG_DATE_RE = re.compile(
    r"\b(?:"
    r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}-\d{1,2}-\d{2,4}|"
    r"jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec|"
    r"january|february|march|april|june|july|august|september|october|"
    r"november|december|\d{4}|\d{1,2}(?:st|nd|rd|th)?"
    r")\b"
)
_WORD_RE = re.compile(r"[a-z']+")
_STOPWORDS = frozenset({"of", "the", "and", "for", "at", "de", "la"})


def registrable_domain(host: str) -> str:
    return ".".join(host.split(".")[-2:])


def host_label(host: str) -> str:
    """The part of a hostname that names the tenant, decoration removed."""
    host = (host or "").lower().strip()
    if registrable_domain(host) in PLATFORM_DOMAINS:
        label = host.split(".")[0]
    else:
        parts = host.split(".")
        label = parts[-2] if len(parts) >= 2 else host
    tokens = [t for t in label.split("-") if t]
    while tokens and tokens[0] in _HOST_NOISE:
        tokens.pop(0)
    while tokens and tokens[-1] in _HOST_NOISE:
        tokens.pop()
    label = "-".join(tokens)
    for prefix in _HOST_ENTITY_PREFIXES:
        if label.startswith(prefix) and len(label) > len(prefix) + 2:
            label = label[len(prefix) :]
            break
    return label


def _state_readings(label: str) -> List[Tuple[str, str]]:
    """(name part, state) readings of a hostname label, best first.

    A hostname carries its state as often as not -- `stcharles-mo`,
    `ks-wichita`, `pelhampublicschoolsny`, `townofrossca` -- and the state
    is what decides whether a bare name resolves at all ("Pelham" is
    nothing; "Pelham, NY" is `us:place:3657001`). Both a stripped and an
    unstripped reading are returned because the strip is a guess: `bourne`
    ends in "ne" and is not Bour, Nebraska. Nothing here decides which
    reading is right -- the acceptance rule downstream does, by rejecting
    the one that does not name a real government.
    """
    out: List[Tuple[str, str]] = []
    tokens = [t for t in label.split("-") if t]
    states = tables.state_gov_ids()
    if len(tokens) > 1 and tokens[-1].upper() in states:
        out.append(("-".join(tokens[:-1]), tokens[-1].upper()))
    if len(tokens) > 1 and tokens[0].upper() in states:
        out.append(("-".join(tokens[1:]), tokens[0].upper()))
    if len(tokens) == 1 and len(tokens[0]) >= 6 and tokens[0][-2:].upper() in states:
        out.append((tokens[0][:-2], tokens[0][-2:].upper()))
    out.append((label, ""))
    return out


def _titled(label: str) -> str:
    return " ".join(w for w in label.replace("-", " ").split() if w).title()


def hostname_candidates(host: str) -> List[Tuple[str, str]]:
    """(candidate name, evidence) from the hostname alone, best first."""
    label = host_label(host)
    if not label or len(label) < 3:
        return []
    out: List[Tuple[str, str]] = []
    for name, state in _state_readings(label):
        if not name:
            continue
        pretty = _titled(name)
        if state:
            # Both readings, state first. If the two-letter tail is not
            # really a state ("bourne" is not Bour, NE) the state reading
            # simply fails to name a government and the bare one is there
            # to catch it.
            out.append((f"{pretty}, {state}", f'hostname "{host}"'))
        out.append((pretty, f'hostname "{host}"'))
    for expanded, source in _acronym_expansions(label):
        out.append((expanded, f'hostname "{host}" reads as {source}'))
    return out


@lru_cache(maxsize=1)
def _school_district_acronyms() -> Dict[str, List[Tuple[str, str]]]:
    """acronym -> [(district name, state)], from `us_school_districts.csv`.

    A school district is the one government type that routinely appears
    on a hostname as its initials and nowhere else: `pgcps.cablecast.tv`
    is Prince George's County Public Schools and the hostname says so in
    five letters. Built from the national table rather than a hand list,
    so it stays true when the table is regenerated, and consulted only
    for a label that looks like an acronym at all.
    """
    out: Dict[str, List[Tuple[str, str]]] = defaultdict(list)
    for row in tables.us_school_districts().rows():
        initials = "".join(
            w[0] for w in _WORD_RE.findall(row.name.lower()) if w not in _STOPWORDS
        )
        if 3 <= len(initials) <= 8:
            out[initials].append((row.name, row.state))
    return out


def _acronym_expansions(label: str) -> List[Tuple[str, str]]:
    """Expansions of a hostname label read as a school-district acronym.

    Exactly one match, or nothing -- `NameStateTable`'s own rule, and for
    the same reason: quietly picking a plausible wrong government is
    worse than proposing none. A state read off the label narrows the
    search before uniqueness is tested, so `wilsoncoschools` can be
    unique in NC even when it is not nationally.
    """
    out: List[Tuple[str, str]] = []
    for name_part, state in _state_readings(label):
        key = name_part.replace("-", "")
        if not key.isalpha() or not 3 <= len(key) <= 8:
            continue
        hits = _school_district_acronyms().get(key) or []
        if state:
            hits = [h for h in hits if h[1] == state]
        if len(hits) == 1:
            district, district_state = hits[0]
            out.append(
                (
                    f"{district}, {district_state}",
                    f'the initials of "{district}"',
                )
            )
    return out


def _phrase_candidates(text: str) -> List[str]:
    """Every phrase in `text` that is shaped like a government's name, and
    anchored to a boundary rather than sliced out of the middle.

    A slug here is `<jurisdiction>-<date>-<title>` or
    `<date>-<title>-<jurisdiction>`, depending on the adapter, so the date
    is the delimiter and the government's name sits at one end of a
    segment. Three anchored shapes come out of that, and nothing else:

      * a **whole segment** between dates -- `ada-county-highway-district-`
        `2024-06-24-...` yields "ada county highway district" entire;
      * a **suffix** ending in a government type word -- swagit appends the
        customer, `...-board-workshop-coppell-independent-school-district`;
      * a **prefix** beginning with an entity phrase -- `city-of-palo-alto-`
        `amending-section-...`.

    The anchoring is the guard, and it is not decorative. The first
    version of this function took every 2-7 word window, which is how it
    proposed **Ada County** for the Ada County Highway *District*,
    **Sonoma County** for the Sonoma County *Library*, and **San Diego
    County** for the county's *Employees Retirement Association* -- three
    real hosts, three real governments, none of them the tenant. That is
    architecture doc SS1.3's bug ("the place check gives agencies the wrong
    identity") rebuilt inside the tool written to help fix it. A window
    that starts inside a name can always find a place inside an agency;
    one anchored to a boundary cannot.
    """
    cleaned = _SLUG_DATE_RE.sub("|", (text or "").lower().replace("-", " "))
    states = tables.state_gov_ids()
    out: List[str] = []
    for segment in cleaned.split("|"):
        words = _WORD_RE.findall(segment)
        if len(words) < 2:
            continue
        # A short segment ending in a bare two-letter state token reads two
        # ways -- as a name and its state, or as a name plus a stray token
        # from the slug's own machinery -- and the slug says nothing about
        # which. Both real cases are eScribe hosts in British Columbia:
        # `langford-sd-2026-03-02-council-meeting` and
        # `white-rock-sd-2025-10-20-...` proposed Langford and White Rock,
        # SOUTH DAKOTA, off a "sd" neither page's stored name carries. At
        # four words or more the segment is carrying a whole entity phrase
        # ("city of wayne mi") and the state reading is the coherent one.
        # Measured cost of the cutoff: `portage-in-2026-08-25-...` loses a
        # correct "Portage, IN". Worth it -- a confident wrong proposal in
        # the wrong country is the expensive kind.
        if len(words) <= 3 and words[-1].upper() in states:
            words = words[:-1]
            if len(words) < 2:
                continue
        out.append(" ".join(words))
        for n in range(2, 8):
            if n > len(words):
                break
            tail = words[-n:]
            if (
                tail[-1] in _TERMINAL_TYPE_WORDS
                or " ".join(tail[-2:]) in _TERMINAL_TYPE_PHRASES
            ):
                out.append(" ".join(tail))
            head = words[:n]
            if head[0] in _LEADING_ENTITY_WORDS and head[1] == "of":
                out.append(" ".join(head))
    return out


def text_candidates(pages: List[dict], state_hint: str) -> List[Tuple[str, str]]:
    """(candidate, evidence) from the group's slugs and titles.

    Ordered by how many of the group's pages carry the phrase: a name
    that shows up on six of a station's meetings is a better guess at the
    tenant than one that shows up on a single basketball game. Each
    candidate is offered with the state hint appended as well as bare,
    since a bare name usually cannot resolve at all.
    """
    counts: Counter = Counter()
    seen_in: Dict[str, str] = {}
    for page in pages:
        for field in ("slug", "title"):
            text = page.get(field) or ""
            for phrase in set(_phrase_candidates(text)):
                counts[phrase] += 1
                seen_in.setdefault(phrase, f'{field} "{text}"')
    out: List[Tuple[str, str]] = []
    for phrase, n in counts.most_common():
        pretty = phrase.title()
        evidence = f"{seen_in[phrase]} ({n} page{'s' if n > 1 else ''})"
        if state_hint:
            out.append((f"{pretty}, {state_hint}", evidence))
        out.append((pretty, evidence))
    return out


def propose(candidates: List[Tuple[str, str]], host: str):
    """The first candidate that reaches a NATIONAL-table government and is
    plainly that government's own name.

    Three gates, and all three matter. A candidate with no `gov_id` did
    not resolve. A candidate that resolved to an `rtr:` id minted one --
    the point of a pin is to say which *known* government a tenant is, and
    a proposal that invents an identity out of a hostname is exactly the
    `king.granicus.com` mistake that made "a machine may not mint" a rule.
    And a candidate that resolved but is not the government's own name is
    `is_own_name()`'s job: "Howard County Public School System" really does
    reach `us:county:24027`, and it is not that county.
    """
    for candidate, evidence in candidates:
        match = resolve_government(candidate, tenant_host=host)
        if not match.gov_id or match.gov_id.startswith("rtr:"):
            continue
        if not is_own_name(candidate, match):
            continue
        return match, candidate, evidence
    return None, "", ""


# --------------------------------------------------------------------------
# Grouping and output
# --------------------------------------------------------------------------


def worklist_platform(host: str, page_platform: str) -> str:
    host = (host or "").lower()
    if host in _YOUTUBE_HOSTS:
        return "youtube"
    for name in ("escribemeetings", "cablecast", "swagit", "telvue"):
        if name in host:
            return "escribe" if name == "escribemeetings" else name
    return page_platform or "unknown"


def landing_url(host: str, platform: str, match: str, source_url: str) -> str:
    """The page a human would open to see who this tenant is.

    Conservative on purpose: a fixed path where the platform has a known
    one, the channel page for a YouTube channel, the host root otherwise.
    Getting it wrong costs one wasted look, not a wrong pin.

    **eScribe and Cablecast are the host ROOT, not a guessed sub-path --
    live-checked 2026-09-03 (Ryan, working the sheet) against real hosts,
    both directions.** The previous guesses were wrong in two different
    ways, not one: `/CablecastPublicSite/` 404s on every real Cablecast
    host checked (`huron-township`, `wilson-co-schools`, `cerritos`) --
    root 200s and its `<title>`/`og:site_name` already carry the real
    government name ("Huron Charter Township"), which is exactly what
    `sweep_tenant_landing_pages.py`'s `candidate_names()` already reads,
    so this fix alone should let that sweep settle real Cablecast hosts
    it currently can't reach at all. `/Meetings.aspx` 200s but is
    eScribe's generic meeting-CALENDAR shell (`<title>eSCRIBE Published
    Meetings</title>`) -- matches BACKLOG.md's existing "eScribe landing
    pages do not name their customer" finding, not a new bug on its own.
    Root is meaningfully better for a HUMAN (Bruce County's root page
    visibly reads "Bruce County Council" in its meeting list -- confirmed
    live), but not yet for the automated sweep: that name sits inside a
    meeting item's `aria-label`, not a `<title>`/`<h1>`/`og:site_name`
    tag, so `candidate_names()` still won't extract it without a further
    change. Root is still strictly better than a 200 that shows nothing
    useful at all, which is why it moved anyway.
    """
    if platform == "youtube" and match:
        return f"https://www.youtube.com/{match}"
    scheme = urlparse(source_url or "").scheme or "https"
    root = f"{scheme}://{host}"
    if platform == "telvue" and match:
        return f"{root}/player/{match}"
    return root


@lru_cache(maxsize=1)
def telvue_tokens() -> Dict[str, str]:
    """org token -> the jurisdiction `telvue_org_tokens.md` names for it.

    Only rows whose confidence column starts "Confirmed" are read, and
    then only if neither cell hedges. The file deliberately keeps its
    unsettled rows -- "Rochester (NH/NY/MN unconfirmed)", "Unidentified",
    and one genuinely multi-jurisdiction token whose playlists are three
    different Centre County governments -- and a hedge in a research note
    is not a signal a proposal may be built on. Those tokens stay
    unproposed, which is the honest answer for them.

    The cell is prose, not a field: it carries markdown bold, a trailing
    parenthetical naming the channel ("Fitchburg, MA (FATV)"), and an
    em-dash aside. All three come off before the name is resolved.
    """
    out: Dict[str, str] = {}
    if not TELVUE_TOKENS.exists():
        return out
    for line in TELVUE_TOKENS.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        token = cells[0].strip("`")
        if not re.fullmatch(r"[A-Za-z0-9_\-]{16,}", token):
            continue
        if not cells[2].startswith("Confirmed"):
            continue
        named = cells[1]
        if _TELVUE_HEDGE_RE.search(named):
            continue
        named = named.replace("**", "")
        named = re.split(r"\s+[\u2014-]{1,2}\s+", named)[0]
        named = re.sub(r"\s*\([^)]*\)\s*$", "", named).strip()
        if named:
            out[token] = named
    return out


def group_pages(pages: List[dict], channels: Dict[str, dict]) -> List[dict]:
    """One group per (tenant_host, match) -- the unit of one human decision.

    `match` is empty for an ordinary tenant, the TelVue org token on
    `videoplayer.telvue.com`, and the channel handle on the shared YouTube
    hosts. Those two platforms share one netloc across every customer, so
    a host-level pin there would be wrong for all of them; the token and
    the channel are what identify the government.
    """
    groups: Dict[Tuple[str, str], dict] = {}
    for page in pages:
        source_url = page.get("source_url_normalized") or ""
        host = (urlparse(source_url).netloc or "").lower().split(":")[0]
        if not host:
            continue
        platform = worklist_platform(host, page.get("platform") or "")
        match = ""
        if platform == "telvue":
            m = _TELVUE_TOKEN_RE.search(source_url)
            match = m.group(1) if m else ""
        elif host in _YOUTUBE_HOSTS:
            match = (channels.get(youtube_video_id(source_url)) or {}).get(
                "channel", ""
            )
        group = groups.setdefault(
            (host, match),
            {
                "platform": platform,
                "tenant_host": host,
                "match": match,
                "pages": 0,
                "_names": set(),
                "_pages": [],
                "example_slug": page.get("slug") or "",
                "landing_url": landing_url(host, platform, match, source_url),
                "_video_ids": [],
            },
        )
        group["pages"] += 1
        group["_pages"].append(page)
        if page.get("jurisdiction"):
            group["_names"].add(page["jurisdiction"])
        if host in _YOUTUBE_HOSTS:
            vid = youtube_video_id(source_url)
            if vid:
                group["_video_ids"].append(vid)
    return list(groups.values())


def add_proposals(
    groups: List[dict], channels: Dict[str, dict], swagit_footers: Dict[str, str]
) -> None:
    hints = registry.tenant_hints()
    tokens = telvue_tokens()
    for group in groups:
        host = group["tenant_host"]
        match = group["match"]
        state_hint = hints.get(host, "")
        group["swagit_footer"] = (
            swagit_footers.get(host, "") if group["platform"] == "swagit" else ""
        )
        # A shared host with no discriminator names no government. Every
        # signal available for it -- the hostname, the slugs, the titles --
        # describes SOME government among the many the host serves, and
        # proposing one of them for all of them is worse than proposing
        # nothing: on the first run of this script, one town's slug on
        # `youtu.be` proposed "North, SC" for all 47 of its pages, and a
        # KSAT 12 news clip proposed Bexar County, TX for 38 pages of
        # `www.youtube.com`.
        if not match and (host in _YOUTUBE_HOSTS or group["platform"] == "telvue"):
            group["proposed_name"] = ""
            group["proposed_gov_id"] = ""
            group["proposed_evidence"] = (
                "shared host, no channel/token identified -- nothing here names "
                "one government"
            )
            continue
        candidates: List[Tuple[str, str]] = []
        # The match-specific signal first: on a shared host the hostname
        # names the platform, not a government, so the channel title or
        # the org token is the only thing that identifies the tenant.
        if group["platform"] == "youtube" and match:
            title = next(
                (
                    channels[v]["channel_title"]
                    for v in group["_video_ids"]
                    if channels.get(v, {}).get("channel_title")
                ),
                "",
            )
            if title:
                candidates.append((title, f'YouTube channel {match} is "{title}"'))
                for phrase in _phrase_candidates(title):
                    candidates.append(
                        (phrase.title(), f'YouTube channel {match} is "{title}"')
                    )
        if group["platform"] == "telvue" and match in tokens:
            named = tokens[match]
            candidates.append(
                (named, f'telvue_org_tokens.md names token {match} "{named}"')
            )
        # The tenant naming ITSELF in its own page template -- stronger
        # evidence than anything guessed from a hostname or a slug, so it
        # goes first among the general (non-match-specific) candidates.
        if group["platform"] == "swagit" and swagit_footers.get(host):
            footer = swagit_footers[host]
            candidates.append((footer, f'swagit footer reads "{footer}"'))
        # The hostname of a shared host names the platform, not a tenant.
        if not (host in _YOUTUBE_HOSTS or group["platform"] == "telvue"):
            candidates.extend(hostname_candidates(host))
        candidates.extend(text_candidates(group["_pages"], state_hint))

        seen = set()
        deduped = []
        for candidate, evidence in candidates:
            key = candidate.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append((candidate, evidence))

        found, candidate, evidence = propose(deduped, host)
        if found:
            group["proposed_name"] = display_name(found.government)
            group["proposed_gov_id"] = found.gov_id
            group["proposed_evidence"] = f'{evidence} -> "{candidate}"'
        else:
            group["proposed_name"] = ""
            group["proposed_gov_id"] = ""
            group["proposed_evidence"] = ""


def existing_answers(path: Path) -> Dict[Tuple[str, str], Dict[str, str]]:
    """(tenant_host, match) -> Ryan's columns from the worklist on disk.

    Regenerating the sheet must never discard an answer already on it --
    the whole loop is Ryan filling this file in over several sittings
    while the Archive keeps growing underneath him.
    """
    if not path.exists():
        return {}
    out: Dict[Tuple[str, str], Dict[str, str]] = {}
    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            answers = {c: (row.get(c) or "").strip() for c in ANSWER_COLUMNS}
            if any(answers.values()):
                out[(row.get("tenant_host") or "", row.get("match") or "")] = answers
    return out


def write_worklist(groups: List[dict], path: Path) -> int:
    answers = existing_answers(path)
    order = {name: i for i, name in enumerate(PLATFORM_ORDER)}
    groups.sort(
        key=lambda g: (
            order.get(g["platform"], len(order)),
            g["platform"],
            -g["pages"],
            g["tenant_host"],
            g["match"],
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=WORKLIST_HEADER)
        writer.writeheader()
        for group in groups:
            answered = answers.get((group["tenant_host"], group["match"]), {})
            writer.writerow(
                {
                    "platform": group["platform"],
                    "tenant_host": group["tenant_host"],
                    "match": group["match"],
                    "pages": group["pages"],
                    "stored_names": "|".join(sorted(group["_names"])),
                    "example_slug": group["example_slug"],
                    "landing_url": group["landing_url"],
                    "swagit_footer": group.get("swagit_footer", ""),
                    "proposed_name": group["proposed_name"],
                    "proposed_gov_id": group["proposed_gov_id"],
                    "proposed_evidence": group["proposed_evidence"],
                    "ryan_gov_name": answered.get("ryan_gov_name", ""),
                    "ryan_note": answered.get("ryan_note", ""),
                }
            )
    return len(answers)


def read_youtube_map(path: Path) -> Dict[str, dict]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as fh:
        return {
            row["video_id"]: {
                "channel": row.get("channel") or "",
                "channel_title": row.get("channel_title") or "",
            }
            for row in csv.DictReader(fh)
            if row.get("video_id")
        }


def write_youtube_map(channels: Dict[str, dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["video_id", "channel", "channel_title"])
        for vid in sorted(channels):
            row = channels[vid]
            writer.writerow([vid, row.get("channel", ""), row.get("channel_title", "")])


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--archive-cache",
        type=Path,
        default=None,
        help="reuse a saved export instead of sweeping production again",
    )
    parser.add_argument(
        "--save-export",
        type=Path,
        default=None,
        help="write the raw export here (for a later --archive-cache)",
    )
    parser.add_argument(
        "--out", type=Path, default=WORKLIST, help=f"default: {WORKLIST}"
    )
    parser.add_argument(
        "--no-youtube",
        action="store_true",
        help="skip the channel lookups; shared-host YouTube rows group by host",
    )
    parser.add_argument(
        "--refresh-youtube",
        action="store_true",
        help="re-identify every video instead of reusing the cached map",
    )
    parser.add_argument(
        "--no-swagit",
        action="store_true",
        help="skip the footer fetch; Swagit rows get no proposal from it",
    )
    parser.add_argument(
        "--refresh-swagit",
        action="store_true",
        help="re-fetch every Swagit host's footer instead of reusing the cached map",
    )
    args = parser.parse_args()

    print("Archive export:")
    if args.archive_cache and args.archive_cache.exists():
        pages = json.loads(args.archive_cache.read_text())
        print(f"  reused {len(pages)} pages from {args.archive_cache}")
    else:
        base_url = os.environ.get("ARCHIVE_BASE_URL")
        token = os.environ.get("ARCHIVE_INGEST_TOKEN")
        if not base_url or not token:
            raise SystemExit(
                "ARCHIVE_BASE_URL and ARCHIVE_INGEST_TOKEN must be set "
                "(they are in the shared checkout's .env)"
            )
        pages = asyncio.run(fetch_export_pages(base_url, token))
        if args.save_export:
            args.save_export.write_text(json.dumps(pages))
            print(f"  saved raw export to {args.save_export}")

    wanted = [
        p for p in pages if (p.get("jurisdiction_confidence") or "") in WANTED_TIERS
    ]
    tiers = Counter(p["jurisdiction_confidence"] for p in wanted)
    print(f"  {len(wanted)} pages want a pin ({dict(tiers)})")

    print("\nYouTube channels:")
    channels = {} if args.refresh_youtube else read_youtube_map(YOUTUBE_MAP)
    shared = [
        youtube_video_id(p["source_url_normalized"])
        for p in wanted
        if (urlparse(p["source_url_normalized"]).netloc or "").lower() in _YOUTUBE_HOSTS
    ]
    if args.no_youtube:
        print("  skipped (--no-youtube)")
    elif not shared:
        print("  none")
    else:
        channels = asyncio.run(fetch_youtube_channels(sorted(set(shared)), channels))
        write_youtube_map(channels, YOUTUBE_MAP)
        named = len({c["channel"] for c in channels.values() if c["channel"]})
        print(f"  {len(shared)} pages on {named} channels -> {YOUTUBE_MAP}")

    print("\nSwagit footers:")
    swagit_footers = {} if args.refresh_swagit else read_swagit_map(SWAGIT_MAP)
    swagit_hosts = {
        (urlparse(p["source_url_normalized"]).netloc or "").lower()
        for p in wanted
        if worklist_platform(
            (urlparse(p["source_url_normalized"]).netloc or "").lower(),
            p.get("platform") or "",
        )
        == "swagit"
    }
    if args.no_swagit:
        print("  skipped (--no-swagit)")
    elif not swagit_hosts:
        print("  none")
    else:
        swagit_footers = asyncio.run(
            fetch_swagit_footers(sorted(swagit_hosts), swagit_footers)
        )
        write_swagit_map(swagit_footers, SWAGIT_MAP)
        named = sum(1 for v in swagit_footers.values() if v)
        print(f"  {named}/{len(swagit_hosts)} hosts named -> {SWAGIT_MAP}")

    print("\nGrouping:")
    groups = group_pages(wanted, channels)
    print(f"  {len(groups)} (tenant_host, match) groups")

    print("\nProposals:")
    add_proposals(groups, channels, swagit_footers)
    proposed = sum(1 for g in groups if g["proposed_gov_id"])
    proposed_pages = sum(g["pages"] for g in groups if g["proposed_gov_id"])
    print(f"  {proposed}/{len(groups)} groups proposed ({proposed_pages} pages)")
    by_platform = Counter(g["platform"] for g in groups if g["proposed_gov_id"])
    for platform, n in by_platform.most_common():
        total = sum(1 for g in groups if g["platform"] == platform)
        print(f"    {platform:16} {n}/{total}")

    kept = write_worklist(groups, args.out)
    print(f"\nworklist: {args.out}")
    print(f"  {len(groups)} rows, {sum(g['pages'] for g in groups)} pages")
    print(f"  {kept} existing answers preserved")
    print("")
    print('Next: fill `ryan_gov_name` with a plain-English name, or "ok" to')
    print('accept `proposed_name`, or "skip". Then:')
    print("  python scripts/apply_pin_worklist.py")


if __name__ == "__main__":
    main()
