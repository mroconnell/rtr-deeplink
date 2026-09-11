"""WO-168: guess a gated government's meeting-platform tenant.

Some government websites sit behind a human-verification gate (Cloudflare
"Verify you are human") we never cross -- see CLAUDE.md's "politely"
bullet and BACKLOG.md's Standing decision on the same. But the gate is on
the government's own website; the meeting platform (Granicus, Legistar,
CivicClerk, ...) is a different server that is usually not gated. This
script skips the gated website entirely for 321 such governments
(rtr-business/research/wo168_candidates.csv: the 309-government
candidate list plus 12 more governments whose own calendar page links to
Granicus's marketing site, WO-163's `wo163_granicus_marketing_hits.csv`)
and instead:

1. Tries a vendor-hinted guess first, when the row's `vendor_hint`
   column says one (set from `known_platform`/the WO-163 marketing-link
   list): CivicPlus -> the government's own `/AgendaCenter` (ONE plain
   request; the gate may still block it, that is expected and fine) then
   a `{st}-{name}.civicplus.com` tenant guess; Granicus/OpenCities -> a
   `{slug}.granicus.com` guess via WO-157's video-first RSS feed;
   Legistar -> a `{slug}.legistar.com` guess through the real Web API.
2. Falls back to (or continues with leftover budget into) generic tenant
   guesses across every wildcard-free platform this repo supports, one
   slug per government (`core_slug()` below -- this repo has no existing
   standalone wildcard-sweep slug-generator *module* to import: the
   original wildcard sweep this rule refers to
   (`rtr-discovery` PR #3) lived in a different repo and its own
   generator was never checked into `scripts/wildcard_sweep_data/` here
   -- only its CSV outputs were. `core_slug()` reproduces the same
   variant shapes CLAUDE.md/the work order describe (bare, `cityof`,
   `{name}{st}`, `{name}county`, `townof{name}`), reusing the exact
   generic-word-stripping list `wo145_api_first_sweep._GENERIC_NAME_WORDS`
   already uses for the identity check, not a new invented list.
3. A 200 alone is never a hit. Every guess is checked two ways, both
   reused, not reimplemented: `wo145_api_first_sweep.check_tenant_identity`
   (landing-page name/state/kind conflict -- WO-142/WO-145's collision
   checks) before spending an enumerate call, and, once a platform lists
   real candidates, `wo145_api_first_sweep.act_on_result`'s own four
   post-resolve mismatch checks (jurisdiction/body, title, a vendor-demo
   tenant's own placeholder-name tell, and the cross-border eScribe/
   CivicWeb collision) -- see that module's docstrings for the concrete
   incidents (Wyandotte County KS unclaimed-demo-tenant collision,
   Flemington NJ, Hometown IL, Cornwall ON) each check exists for.
4. Once a real tenant is confirmed, seeds a SCRATCH discovery ledger
   (never `~/Documents/rtr-discovery/ledger.db`) with the government's
   gov_id, enumerates in thorough mode, and resolves up to 6 candidates
   -- the same shape `wo145_api_first_sweep.process_enumerator_platform`
   already uses, reused via `guess_and_confirm_platform()` below calling
   straight into it once a netloc is confirmed. A tier-1/2 (captions
   reachable) candidate ingests immediately -- breadth over depth, per
   `docs/BREADTH_SWEEP_BRIEF.md`. A tier-3 (video, no captions) candidate
   is different from `wo145_api_first_sweep`'s own tier-3 handling on
   purpose: every tier-3 candidate is probed first
   (`app.platforms.queue_probe.probe_queue_entry`, WO-144), a reject
   moves to the next candidate, and among the plausible ones this script
   prefers a 9-40 minute meeting (Ryan's rule, 2026-09-10), or the
   shortest if every candidate runs long -- the same "probe before
   queue, pick the best of up to 6" shape
   `wo134_confirmed_hits_ingest.py`'s `TIER3_HANDLER` hook already
   established for WO-147/WO-149, reimplemented here (not imported --
   `wo134`'s own candidate-row shape and CivicPlus-specific plumbing
   don't fit this script's guess-then-confirm flow) as
   `rank_tier3_candidates()`.

Usage (repo root, rtr-discovery's own venv -- see wo145_api_first_sweep.py's
own note: the shared deeplink .venv cannot import `discovery`):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo168_scratch.db" \\
    ~/Documents/rtr-discovery/.venv/bin/python scripts/wo168_gated_tenant_guess.py --pilot 30
    ... (same) ... scripts/wo168_gated_tenant_guess.py --limit 100
    ... (same) ... scripts/wo168_gated_tenant_guess.py

Resumable: rtr-business/research/wo168_report.csv is flushed one row at a
time; a gov_id already present there is skipped on re-run.
"""

import argparse
import asyncio
import csv
import json
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Same worktree-path fix wo145_api_first_sweep.py needs -- discovery's
# discovery/deeplink.py defaults to a sibling "../../rtr-deeplink" checkout,
# wrong for a session working inside a .claude/worktrees/<name> worktree.
os.environ.setdefault("RTR_DEEPLINK_PATH", str(REPO_ROOT))
DISCOVERY_ROOT = Path.home() / "Documents" / "rtr-discovery"
sys.path.insert(0, str(DISCOVERY_ROOT))

import aiohttp  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import find_platform_link  # noqa: E402
from app.utils.gov_registry import registry as gov_registry  # noqa: E402
from app.platforms.models import ResolvedMeeting  # noqa: E402
from app.platforms.queue_probe import probe_queue_entry  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402
from scripts.bulk_ingest import _base_url, _ingest  # noqa: E402
import scripts.hub_sweep_wo126 as hs  # noqa: E402
import scripts.wo145_api_first_sweep as w145  # noqa: E402

from discovery.ledger import Ledger  # noqa: E402
from discovery.enumerate_stage import enumerate_candidates  # noqa: E402
from discovery.resolve import resolve_candidates  # noqa: E402

hs.PIN_SOURCE = "wo168_gated_tenant_guess"

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
CANDIDATES_CSV = RESEARCH_DIR / "wo168_candidates.csv"
REPORT_CSV = RESEARCH_DIR / "wo168_report.csv"
DISCOVERY_SEEDS_CSV = RESEARCH_DIR / "wo168_discovery_seeds.csv"
CONFIRMED_TENANTS_CSV = RESEARCH_DIR / "wo168_confirmed_tenants.csv"
hs.PINS_CSV = RESEARCH_DIR / "wo168_pins.csv"

REAL_LEDGER = DISCOVERY_ROOT / "ledger.db"
SCRATCH_LEDGER = Path("/tmp/wo168_ledger.db")

TIER3_QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"

DEFAULT_INVENTORY_CSV = Path("/tmp/wo168_inventory/meeting_inventory.csv")

REQUEST_DELAY_SECONDS = 1.5  # between governments
GUESS_DELAY_SECONDS = 2.0  # between tenant-host guesses (CLAUDE.md's "politely" rule)
MAX_GUESSES_PER_GOV = 12
MAX_CANDIDATES_TRIED = 6
MAX_CONSECUTIVE_ERRORS = 6

# --------------------------------------------------------------------------
# Slug generation -- reproduces the wildcard-sweep's variant shapes; see
# module docstring #2 for why this is a fresh, small function rather than
# an import of an existing generator module (none exists in this repo).
# --------------------------------------------------------------------------

_GENERIC_NAME_WORDS = w145._GENERIC_NAME_WORDS


def core_slug(name: str) -> str:
    """'St. Louis County' -> 'stlouis'; 'Forsyth County' -> 'forsyth';
    'Town of Woodside' -> 'woodside'. Strips the same generic government-
    kind/connector words wo145's own _name_tokens() strips, but keeps
    letters concatenated (a DNS label) instead of a token set."""
    words = re.findall(r"[a-z0-9']+", (name or "").lower())
    core = [w for w in words if w not in _GENERIC_NAME_WORDS]
    if not core:
        core = words
    return "".join(w.replace("'", "") for w in core)


def primary_and_alt_slugs(name: str, state: str, gov_kind: str) -> List[str]:
    """Ordered slug guesses, most-likely-real first. Real tenants
    overwhelmingly use the bare core name (BACKLOG_DONE.md's wildcard-
    sweep entries: 'erin', 'raymond', not 'townoferin') -- bare is tried
    first, everywhere. The kind-specific variant is tried second, only
    if guess budget remains (see MAX_GUESSES_PER_GOV)."""
    core = core_slug(name)
    st = (state or "").lower()
    out = [core]
    if gov_kind == "county":
        out.append(f"{core}county")
    elif gov_kind == "township":
        out.append(f"townof{core}")
    else:
        out.append(f"cityof{core}")
    out.append(f"{core}{st}")
    # de-dupe, keep order
    seen = set()
    ordered = []
    for s in out:
        if s and s not in seen:
            seen.add(s)
            ordered.append(s)
    return ordered


# host template -> (suffix, platform key). civicplus is handled separately
# (AgendaCenter walk, not an enumerator platform -- see w145's own note).
GENERIC_HOST_TEMPLATES: List[Tuple[str, str]] = [
    ("granicus.com", "granicus"),
    ("legistar.com", "legistar"),
    ("portal.civicclerk.com", "civicclerk"),
    ("civicclerk.com", "civicclerk"),
    ("escribemeetings.com", "escribe"),  # tried as pub-{slug} first, see below
    ("iqm2.com", "iqm2"),
    ("new.swagit.com", "swagit"),
    ("civicweb.net", "civicweb"),
    ("primegov.com", "primegov"),
    ("cablecast.tv", "cablecast"),
]


def build_guess_order(cand: "Cand") -> List[Tuple[str, str]]:
    """Returns an ordered list of (netloc, platform) guesses, vendor-hinted
    ones first, capped at MAX_GUESSES_PER_GOV. The CivicPlus own-domain
    check is NOT in this list -- it is tried separately, once, for free
    (see process_government's own step 1)."""
    slugs = primary_and_alt_slugs(cand.name, cand.state, cand.gov_kind)
    bare = slugs[0]
    guesses: List[Tuple[str, str]] = []

    def add(netloc: str, platform: str) -> None:
        if (netloc, platform) not in guesses:
            guesses.append((netloc, platform))

    if cand.vendor_hint == "civicplus":
        add(f"{cand.state.lower()}-{bare}.civicplus.com", "civicplus")
    elif cand.vendor_hint == "granicus":
        add(f"{bare}.granicus.com", "granicus")
    elif cand.vendor_hint == "legistar":
        add(f"{bare}.legistar.com", "legistar")

    for suffix, platform in GENERIC_HOST_TEMPLATES:
        if suffix == "escribemeetings.com":
            add(f"pub-{bare}.escribemeetings.com", "escribe")
            add(f"{bare}.escribemeetings.com", "escribe")
        else:
            add(f"{bare}.{suffix}", platform)

    # Leftover budget: try the kind-specific alt variant against the
    # highest-yield platforms only (granicus/legistar/civicclerk), per
    # the wildcard-sweep's own finding that smaller/less-resourced
    # tenants rarely answer a second variant (BACKLOG.md's wildcard
    # handover: 3-for-3 large vs 0-for-7 small).
    if len(guesses) < MAX_GUESSES_PER_GOV and len(slugs) > 1:
        alt = slugs[1]
        for suffix, platform in (
            ("granicus.com", "granicus"),
            ("legistar.com", "legistar"),
            ("civicclerk.com", "civicclerk"),
        ):
            if len(guesses) >= MAX_GUESSES_PER_GOV:
                break
            add(f"{alt}.{suffix}", platform)

    return guesses[:MAX_GUESSES_PER_GOV]


# --------------------------------------------------------------------------
# Candidate row
# --------------------------------------------------------------------------


@dataclass
class Cand:
    gov_id: str
    name: str
    state: str
    gov_kind: str
    population: str
    domain: str
    known_platform: str
    gated_host: str
    source_sweep: str
    vendor_hint: str
    country: str

    @property
    def jurisdiction(self) -> str:
        return f"{self.name}, {self.state}"

    # Shim fields wo145's shared helpers (Gov(), check_tenant_identity(),
    # _state_or_kind_conflict()) expect but this candidate list has no
    # column for -- always blank/empty here, matching wo145's own Cand
    # for rows with nothing in these fields.
    @property
    def hub_url(self) -> str:
        return ""

    @property
    def reject_reason(self) -> str:
        return ""

    @property
    def platform_norm(self) -> str:
        return ""


def load_candidates() -> List[Cand]:
    with CANDIDATES_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        out.append(
            Cand(
                gov_id=r["gov_id"],
                name=r["name"],
                state=(r.get("state") or "").strip(),
                gov_kind=(r.get("gov_kind") or "").strip(),
                population=(r.get("population") or "").strip(),
                domain=(r.get("domain") or "").strip(),
                known_platform=(r.get("known_platform") or "").strip().lower(),
                gated_host=(r.get("gated_host") or "").strip(),
                source_sweep=(r.get("source_sweep") or "").strip(),
                vendor_hint=(r.get("vendor_hint") or "").strip().lower(),
                country=(r.get("country") or "us").strip().lower(),
            )
        )
    return out


REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "population",
    "vendor_hint",
    "guesses_tried",
    "tenant_confirmed",
    "tenant_host",
    "tenant_platform",
    "how_confirmed",
    "outcome",
    "reject_reason",
    "reject_class",
    "meeting_url",
    "video_url",
    "tier",
    "page_url",
    "note",
]


@dataclass
class Report:
    gov_id: str
    name: str
    state: str
    gov_kind: str
    population: str
    vendor_hint: str = ""
    guesses_tried: int = 0
    tenant_confirmed: str = "no"
    tenant_host: str = ""
    tenant_platform: str = ""
    how_confirmed: str = ""
    outcome: str = "no_tenant_found"
    reject_reason: str = ""
    reject_class: str = ""
    meeting_url: str = ""
    video_url: str = ""
    tier: str = ""
    page_url: str = ""
    note: str = ""


def _already_done(path: Path) -> set:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f) if r.get("gov_id")}


def _writer(path: Path, fields: List[str]):
    is_new = not path.exists()
    f = path.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=fields)
    if is_new:
        w.writeheader()
        f.flush()
    return f, w


def _existing_tier3_queue_urls() -> set:
    urls = set()
    if TIER3_QUEUE_FILE.exists():
        for line in TIER3_QUEUE_FILE.read_text(encoding="utf-8").splitlines():
            if line.strip():
                urls.add(line.split("\t", 1)[0])
    return urls


_TIER3_QUEUE_CACHE: Optional[set] = None


def existing_tier3_queue_urls() -> set:
    global _TIER3_QUEUE_CACHE
    if _TIER3_QUEUE_CACHE is None:
        _TIER3_QUEUE_CACHE = _existing_tier3_queue_urls()
    return _TIER3_QUEUE_CACHE


# --------------------------------------------------------------------------
# CivicPlus own-domain check -- ONE plain request, never retried, never
# escalated to browser headers (the gate is expected to block this
# sometimes; that is a fine, honest outcome, not an error).
# --------------------------------------------------------------------------


async def try_civicplus_own_domain(
    session: aiohttp.ClientSession, cand: "Cand"
) -> Optional[Tuple[str, str]]:
    if not cand.domain:
        return None
    base = cand.domain if "://" in cand.domain else f"https://{cand.domain}"
    base = base.rstrip("/")
    url = f"{base}/AgendaCenter"
    try:
        async with session.get(
            url,
            headers=w145.HONEST_HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
            allow_redirects=True,
        ) as resp:
            text = await resp.text(errors="replace")
            if resp.status >= 400:
                return None
            if any(m in text[:4000].lower() for m in w145.CHALLENGE_MARKERS):
                return None
            return str(resp.url), text
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------
# Tier-3 candidate collection + probe-before-queue selection
# --------------------------------------------------------------------------


@dataclass
class Tier3Candidate:
    meeting_url: str
    video_url: str
    source_url: str
    duration_seconds: Optional[float]
    verdict: str
    reason: Optional[str]


def rank_tier3_candidates(cands: List[Tier3Candidate]) -> List[Tier3Candidate]:
    """Ryan's rule, 2026-09-10: among plausible (probe-accepted) tier-3
    candidates, prefer 9-40 minutes; if every candidate runs long, take
    the shortest. Never ranks a reject-dead/reject-short candidate.
    Returns every plausible candidate in preference order (not just the
    top one) so the caller can skip a candidate that fails independent
    identity verification and fall through to the next-best -- see
    process_confirmed_tenant's tier3_pool handling for why that matters:
    a tier-3 candidate has no transcript, so the identity checks that
    catch a tier-1/2 mismatch (adapter jurisdiction/title, then the full
    transcript scan) have nothing to work with, and a raw page fetch is
    the only independent signal left."""
    plausible = [c for c in cands if c.verdict in ("accept", "flag-long")]
    if not plausible:
        return []
    in_range = [
        c
        for c in plausible
        if c.duration_seconds is not None and 540 <= c.duration_seconds <= 2400
    ]
    with_duration = [c for c in plausible if c.duration_seconds is not None]
    no_duration = [c for c in plausible if c.duration_seconds is None]
    ordered = (
        sorted(in_range, key=lambda c: c.duration_seconds)
        + sorted(
            (c for c in with_duration if c not in in_range),
            key=lambda c: c.duration_seconds,
        )
        + no_duration
    )
    return ordered or plausible


async def raw_candidate_identity_check(
    session: aiohttp.ClientSession, url: str, cand: "Cand"
) -> Tuple[Optional[bool], str]:
    """Fetch one real candidate URL directly (bypassing the platform
    adapter entirely) and look for a name/state/kind conflict or a real
    name-token match in its raw title+body text.

    Real, confirmed-live bug this exists to close (WO-168, 2026-09-10):
    `process_confirmed_tenant`'s post-resolve conflict checks only run
    against candidates that reach `resolved_ok` -- which requires
    segments/agenda_items/agenda_link/video_url (discovery's own
    `nothing_to_ingest` filter). A government with NO video at all is a
    legitimate, common outcome (this repo's own "a video-less host is a
    valid record" rule) -- but eScribe's `agenda_items` specifically
    means "agenda items with a real video timestamp bookmark"
    (`escribe.py`'s own `_extract_agenda_items` docstring), so a real
    eScribe meeting with no embedded iSiLIVE video (an external YouTube/
    WebEx/Townhall-Streams link mentioned only as text, not a bug) NEVER
    produces a resolved_ok row -- meaning the identity checks never ran
    at all. Two guessed eScribe tenants in the 30-government pilot
    slipped past this way: `pub-woodstock.escribemeetings.com` (real
    content: "The Corporation of the City of Woodstock ... County of
    Oxford" -- Woodstock, ONTARIO, not the Connecticut town this guess
    was for) and `pub-lakewood.escribemeetings.com` (real content:
    "Township Of Lakewood, County Of Ocean, State Of New Jersey" -- not
    the Colorado city this guess was for). Both were caught only by a
    human reading the real page by hand, which is the pilot-verification
    step this exact incident is why that step exists. This function is
    the automated version of that same check: fetch a real candidate
    page directly and read its own text, independent of whether the
    adapter extracted anything structured from it.

    Returns (True, detail) on a real name-token match (positive
    confirmation), (False, detail) on a confident conflict, or
    (None, detail) when genuinely inconclusive (fetch failed, or no
    name tokens either way) -- inconclusive is NOT treated as
    confirmation anywhere that calls this."""
    try:
        async with session.get(
            url,
            headers=hs.UA_HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
            allow_redirects=True,
        ) as resp:
            if resp.status >= 400:
                return None, f"candidate page unreachable ({resp.status}), unverified"
            html = await resp.text(errors="replace")
    except Exception as e:  # noqa: BLE001
        return None, f"candidate page fetch failed, unverified: {type(e).__name__}"

    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.get_text(strip=True) if soup.title else "") or ""
    body_text = soup.get_text(" ", strip=True)[:4000]
    combined = f"{title} {body_text}".strip()

    conflict = w145._state_or_kind_conflict(cand, combined, "raw candidate page")
    # Real, confirmed-live false positive this guards against (WO-168,
    # 2026-09-10): a full page dump (unlike the short title/jurisdiction
    # strings wo145's own checks were built against) commonly carries the
    # row's own state as a plain address abbreviation -- "Livingston
    # County Administration Building 304 E. Grand River, Board Chambers,
    # Howell MI 48843" -- which `_state_or_kind_conflict`'s leading
    # "Name, ST" regex and `_cross_border_collision`'s same regex both
    # miss (both require the state code at the very start of the string,
    # immediately after a comma). Without this, Livingston County, MI's
    # own raw page was flagged as a false conflict against "Livingston
    # No. 331," a real Alberta rural municipality, purely because no
    # LEADING "Name, ST" pattern happened to open the page text.
    state_abbr = (cand.state or "").strip().upper()
    has_state_abbr_anywhere = bool(
        state_abbr and re.search(rf"\b{re.escape(state_abbr)}\b", combined)
    )
    if not conflict and not has_state_abbr_anywhere:
        # Always run, regardless of platform: only fires on an exact
        # Canadian-municipality name collision with no state/province
        # code anywhere in the text, so it's cheap and low-risk to run
        # unconditionally here rather than threading a platform check
        # through this fallback path.
        conflict = w145._cross_border_collision(cand, combined)
    if conflict:
        return False, conflict

    # Real, confirmed-live false positive this guards against (WO-168,
    # 2026-09-10): `clark.granicus.com` guessed for Clark County, KS
    # returned True on a bare name-token match alone, because the real
    # content -- Clark County, NEVADA's own zoning notices ("Dapple Gray
    # Road," "Lone Mountain," real Las Vegas-area places) -- of course
    # also says "Clark County" throughout. A name match alone can never
    # rule out the identically-named, larger, more-likely-to-actually-
    # hold-this-subdomain government -- Fulton County GA/Atlanta beating
    # out Fulton County, KY for `fulton.granicus.com` is the same shape.
    # A positive match now additionally requires the row's OWN state to
    # appear somewhere too (abbreviation as a standalone word, or the
    # full state name) -- absent that, a bare name match is downgraded
    # to inconclusive, not confirmed.
    tokens = w145._name_tokens(cand.name)
    combined_lower = combined.lower()
    name_matches = bool(tokens and any(t in combined_lower for t in tokens))
    state_abbr = (cand.state or "").strip().upper()
    row_state_name = w145.STATE_NAMES.get(state_abbr, "")
    own_state_present = bool(
        state_abbr and re.search(rf"\b{re.escape(state_abbr)}\b", combined)
    ) or bool(row_state_name and row_state_name.lower() in combined_lower)
    if name_matches and own_state_present:
        return True, f"raw candidate page names {cand.name!r} and {cand.state}"
    if name_matches:
        return (
            None,
            f"raw candidate page names {cand.name!r} but never mentions "
            f"{cand.state} anywhere -- could be a same-named government "
            "in a different state, not confirmed",
        )
    return None, "no name-token match on raw candidate page, unverified"


# --------------------------------------------------------------------------
# Once a tenant is confirmed: enumerate, resolve up to 6, probe tier-3
# --------------------------------------------------------------------------


@dataclass
class TenantAttempt:
    """One guess's own outcome, kept separate from the government-level
    Report so a failed/empty guess never clobbers an earlier guess's
    finding (a wrong_domain_mapping signal, in particular) -- the real
    bug an early smoke test caught: reusing one mutable Report across
    every guess let the LAST guess tried silently overwrite an earlier,
    more informative result."""

    confirmed: bool = False  # a real, populated tenant answered this guess
    success: bool = False  # AND it carries usable content for THIS government
    outcome: Optional[str] = None
    reject_reason: str = ""
    note: str = ""
    tenant_host: str = ""
    tenant_platform: str = ""
    how_confirmed: str = ""
    meeting_url: str = ""
    video_url: str = ""
    tier: str = ""
    page_url: str = ""


def existing_pin_conflict(netloc: str, cand: "Cand") -> Optional[str]:
    """A cheap, highly reliable, zero-network check: does
    `app/utils/jurisdiction_data/tenant_overrides.csv` already carry a
    catch-all row (no `match` discriminator) for this exact host, naming
    a DIFFERENT government? If so, someone already identified this
    tenant, and it isn't this one -- no further checking needed.

    Real, confirmed-live bug this closes (WO-168, 2026-09-10):
    `lakecounty.granicus.com` guessed for Lake County, MI already has a
    real, human-confirmed pin to Lake County, CALIFORNIA
    (`ryan_stated`); `wilmington.granicus.com` guessed for Wilmington
    town, MA already has a real, visually-confirmed pin to Wilmington,
    NORTH CAROLINA. `hs.pin_for()` already refuses to write a SECOND,
    conflicting pin for a host that has one (so no bad pin ever landed
    in `tenant_overrides.csv` for either) -- but nothing stopped this
    script from still queuing the video and reporting the tenant as
    confirmed for the WRONG government's gov_id, since `pin_for()`
    returning None was silently treated as "nothing to do," not "this
    is already claimed by someone else." Checked before spending any
    enumerate/resolve network calls, since it's also the cheapest
    possible signal."""
    rows = gov_registry.tenant_overrides().get(netloc.lower())
    if not rows:
        return None
    for row in rows:
        if row.match:
            continue  # a discriminated row doesn't claim the whole host
        if row.gov_id == cand.gov_id:
            return None  # already correctly pinned to this government
        return (
            f"{netloc} already has a real pin to a different government "
            f"({row.gov_id}, source={row.source!r}) -- not {cand.name}, {cand.state}"
        )
    return None


async def process_confirmed_tenant(
    session: aiohttp.ClientSession,
    ledger: Ledger,
    cand: Cand,
    netloc: str,
    platform: str,
    seeds_w,
) -> TenantAttempt:
    attempt = TenantAttempt()

    pin_conflict = existing_pin_conflict(netloc, cand)
    if pin_conflict:
        attempt.outcome = "wrong_domain_mapping"
        attempt.reject_reason = "wrong-domain-mapping"
        attempt.note = pin_conflict
        return attempt

    ledger.upsert_tenant(netloc, platform)
    state_abbr = cand.state.upper() or None
    ledger.set_tenant_gov_id(netloc, cand.gov_id, state_abbr=state_abbr)

    try:
        await enumerate_candidates(
            ledger, platforms=[platform], tenant=netloc, mode="thorough"
        )
    except Exception as e:  # noqa: BLE001
        attempt.note = f"{netloc}: enumerate raised: {type(e).__name__}: {e}"
        return attempt

    listed = ledger.conn.execute(
        "SELECT COUNT(*) c FROM candidates WHERE tenant_netloc = ? AND status = 'new'",
        (netloc,),
    ).fetchone()["c"]
    if listed == 0:
        # This specific guess didn't pan out (empty/unclaimed/demo tenant
        # -- BACKLOG.md's wildcard-sweep handover documents exactly this
        # shape, two slugs both serving "Wyandotte County, KS"). Not a
        # government-level finding; the caller tries the next guess.
        attempt.note = f"{netloc}: answered but the enumerator listed 0 candidates"
        return attempt

    # NOTE: confirmation (attempt.confirmed / tenant_host / seeds_w write)
    # is deliberately NOT set here just because the enumerator listed
    # real candidates -- see raw_candidate_identity_check()'s docstring
    # for why "a real tenant answered" is not the same as "it names THIS
    # government." Set only once something below actually verifies it.
    def _confirm(how: str) -> None:
        attempt.confirmed = True
        attempt.tenant_host = netloc
        attempt.tenant_platform = platform
        attempt.how_confirmed = how
        seeds_w.writerow(
            {
                "netloc": netloc,
                "platform": platform,
                "gov_id": cand.gov_id,
                "access_mode": "api",
            }
        )

    try:
        await resolve_candidates(
            ledger,
            tenant=netloc,
            limit=MAX_CANDIDATES_TRIED,
            require_captions=False,
            min_tier="blank",
            include_tier3=True,
        )
    except Exception as e:  # noqa: BLE001
        attempt.outcome = "error"
        attempt.note = f"{netloc}: resolve raised: {type(e).__name__}: {e}"
        return attempt

    resolved_rows = ledger.conn.execute(
        "SELECT url_normalized, resolved_json FROM candidates "
        "WHERE tenant_netloc = ? AND status = 'resolved_ok' AND resolved_json IS NOT NULL "
        "ORDER BY date DESC",
        (netloc,),
    ).fetchall()

    tier3_pool: List[Tuple[Tier3Candidate, ResolvedMeeting, str]] = []
    any_meeting_evidence = False
    saw_conflict = ""
    high_risk = platform in w145.ENUMERATOR_HIGH_RISK_TITLE_PLATFORMS

    for row in resolved_rows:
        payload = json.loads(row["resolved_json"])
        result = ResolvedMeeting(**payload)
        meeting_url = row["url_normalized"]
        segments = result.segments or []
        agenda_items = result.agenda_items or []
        if not (segments or agenda_items or result.agenda_link or result.video_url):
            continue
        any_meeting_evidence = True

        effective_title = result.title or ""
        if not effective_title and result.video_url:
            effective_title = (
                await hs.youtube_oembed_title(session, result.video_url) or ""
            )
        if not hs._looks_like_real_meeting(
            effective_title, require_allowlist=high_risk
        ):
            continue

        adapter_signal = (
            f"{result.jurisdiction or ''} {result.meeting_body or ''}".strip()
        )
        conflict = w145._state_or_kind_conflict(
            cand, adapter_signal, "adapter jurisdiction/body"
        )
        if not conflict:
            conflict = w145._state_or_kind_conflict(cand, effective_title, "title")
        if not conflict:
            conflict = w145._title_place_conflict(cand, effective_title)
        if not conflict and platform in w145.CROSS_BORDER_RISK_PLATFORMS:
            combined = f"{result.jurisdiction or ''} {result.meeting_body or ''} {effective_title or ''}".strip()
            conflict = w145._cross_border_collision(cand, combined)
        if conflict:
            saw_conflict = conflict
            continue

        # Real, confirmed-live bug this closes (WO-168, 2026-09-10): a
        # guessed `salem.legistar.com` tenant for Salem city, IL resolved
        # a real, current meeting with a real transcript -- but the
        # transcript itself is Salem, OREGON's city council ("this is the
        # seat of governments in the state of Oregon," "I am a native
        # Oregonian"). Every check above (adapter jurisdiction/body,
        # title, title-place, cross-border) passed, because Legistar's
        # own jurisdiction/title fields never carry a state at all for
        # this tenant ("CITY OF SALEM") and neither does a routine
        # meeting title -- the only place the real state ever showed up
        # was inside the transcript text itself, which nothing checked
        # before this. Scoped to segments (the tier1/2 ingest path,
        # highest stakes -- a live page, not just a queue entry) since
        # that's the one place a full, real transcript sample exists to
        # check.
        if segments:
            # The FULL transcript, not a sample -- confirmed live on the
            # real Salem, OR incident this check exists for: the
            # disambiguating "state of Oregon" mention landed at
            # character ~14,000 of an 83,000-character transcript, well
            # past what any small leading sample would have reached, but
            # every one of that tenant's 6 real meetings mentioned
            # "Oregon" somewhere across their full length. A plain
            # substring/regex scan over the whole thing is still cheap
            # (milliseconds), so there's no real reason to truncate it.
            transcript_text = " ".join(
                s.get("text", "") if isinstance(s, dict) else (s.text or "")
                for s in segments
            )
            transcript_conflict = w145._state_or_kind_conflict(
                cand, transcript_text, "transcript"
            )
            if transcript_conflict:
                saw_conflict = transcript_conflict
                continue

        # Real, confirmed-live bug this closes (WO-168, 2026-09-10): the
        # transcript scan above only catches an EXPLICIT full state-name
        # mention, and a short real transcript (4 segments, in the real
        # incident) may simply never say one. `yorkcounty.granicus.com`
        # guessed for York County, SC turned out to be York County,
        # VIRGINIA -- real content ("Board of Supervisors," the term
        # Virginia counties use; South Carolina counties use "County
        # Council") that the transcript scan had no state name to catch.
        # `raw_candidate_identity_check()` (built for the tier-3 path,
        # see its own docstring) is the same, more careful check --
        # requiring the row's own state to appear, not just its name --
        # and it belongs here too, at the SAME bar as tier-3: a positive
        # match required before ingesting, not just "no conflict found."
        if segments or result.video_url:
            verified, verify_detail = await raw_candidate_identity_check(
                session, meeting_url, cand
            )
            if verified is False:
                saw_conflict = verify_detail
                continue
            if verified is not True:
                # Genuinely inconclusive -- try the next candidate on
                # this tenant rather than ingesting on a guess.
                continue

        result.jurisdiction = cand.jurisdiction

        if segments:
            gov = hs.Gov(
                cand.gov_id,
                cand.name,
                cand.state,
                cand.hub_url,
                cand.domain,
                cand.reject_reason,
            )
            ok, tier_detail = hs.key_check(
                gov, cand.jurisdiction, result.source_url or meeting_url
            )
            if not ok:
                pin = hs.pin_for(
                    gov,
                    result.source_url or meeting_url,
                    result.video_url or "",
                    platform,
                )
                if pin:
                    hs.stage_pin(pin, dry_run=False)
            response = None
            for try_num in (1, 2):
                try:
                    response = await _ingest(
                        session, result.model_dump(), normalize_url(meeting_url)
                    )
                    break
                except Exception:  # noqa: BLE001
                    if try_num == 2:
                        response = None
                    else:
                        await asyncio.sleep(3)
            if response is None:
                continue  # try the next candidate on this same tenant
            _confirm(
                f"enumerator listed {listed} candidate(s); ingested a real, "
                "identity-checked match"
            )
            attempt.success = True
            attempt.outcome = "ingested_tier1_2"
            attempt.page_url = response.get("url") or ""
            attempt.tier = "tier1_2"
            attempt.meeting_url = meeting_url
            attempt.video_url = result.video_url or ""
            attempt.note = f"{len(segments)} transcript segments" + (
                "" if response.get("created") else " (matched an existing page)"
            )
            return attempt

        if result.video_url:
            probe = await probe_queue_entry(
                meeting_url,
                video_url=result.video_url,
                source_page_url=result.source_url or meeting_url,
                platform=platform,
            )
            tier3_pool.append(
                (
                    Tier3Candidate(
                        meeting_url=meeting_url,
                        video_url=result.video_url,
                        source_url=result.source_url or meeting_url,
                        duration_seconds=probe.duration_seconds,
                        verdict=probe.verdict,
                        reason=probe.reason,
                    ),
                    result,
                    platform,
                )
            )
            await asyncio.sleep(0.75)
            continue

    if tier3_pool:
        # Real, confirmed-live bug this closes (WO-168, 2026-09-10): a
        # tier-3 candidate has no transcript, so neither the adapter-
        # jurisdiction/title checks above nor the full-transcript scan
        # (both scoped to `segments`) have anything to work with -- a
        # bare Granicus "CCMeeting9/8/2026" title carries no identifying
        # text at all. `fremont.granicus.com` guessed for Fremont city,
        # OH turned out to be Fremont, CALIFORNIA (real mayor "Salwan",
        # "fremont.gov" spoken repeatedly in the transcripts of every
        # OTHER candidate on the same tenant -- this specific candidate
        # just happened to have zero captions, so nothing caught it
        # before this). Each ranked candidate's real meeting_url is now
        # independently raw-fetched and must return a real name-token
        # match (not just "no conflict") before it can be queued/pinned;
        # a confident conflict or a genuinely inconclusive fetch both
        # skip to the next-ranked candidate rather than defaulting to
        # "probably fine."
        ranked = rank_tier3_candidates([t[0] for t in tier3_pool])
        chosen = None
        chosen_platform = platform
        rejected_notes = []
        for cand_t3 in ranked:
            verified, detail = await raw_candidate_identity_check(
                session, cand_t3.meeting_url, cand
            )
            if verified is True:
                chosen = cand_t3
                chosen_platform = next(
                    (t[2] for t in tier3_pool if t[0] is cand_t3), platform
                )
                break
            rejected_notes.append(f"{cand_t3.meeting_url}: {detail}")
            if verified is False:
                saw_conflict = detail

        if chosen is not None:
            gov = hs.Gov(
                cand.gov_id,
                cand.name,
                cand.state,
                cand.hub_url,
                cand.domain,
                cand.reject_reason,
            )
            pin = hs.pin_for(gov, chosen.source_url, chosen.video_url, chosen_platform)
            if pin:
                hs.stage_pin(pin, dry_run=False)
            if chosen.meeting_url not in existing_tier3_queue_urls():
                with TIER3_QUEUE_FILE.open("a", encoding="utf-8") as f:
                    f.write(chosen.meeting_url + "\n")
                existing_tier3_queue_urls().add(chosen.meeting_url)
            _confirm(
                f"enumerator listed {listed} candidate(s); queued a real, "
                "raw-page-verified, probe-accepted match"
            )
            attempt.success = True
            attempt.outcome = "queued_tier3"
            attempt.tier = "tier3"
            attempt.meeting_url = chosen.meeting_url
            attempt.video_url = chosen.video_url
            attempt.note = (
                f"probed {len(tier3_pool)} tier-3 candidate(s), picked {chosen.duration_seconds}s "
                f"({chosen.verdict}); "
                f"{len([t for t in tier3_pool if t[0].verdict.startswith('reject')])} rejected by probe"
            )
            return attempt

        if saw_conflict:
            attempt.outcome = "wrong_domain_mapping"
            attempt.reject_reason = "wrong-domain-mapping"
            attempt.note = saw_conflict
            return attempt

        if not ranked:
            # No candidate was even probe-accepted (every one was
            # reject-dead/reject-short) -- a real, identity-checked
            # meeting existed, its video just wasn't usable. Unlike the
            # "none raw-verified" case below, this isn't an identity
            # question at all, so it keeps the tenant confirmed.
            _confirm(
                f"enumerator listed {listed} candidate(s); {len(tier3_pool)} identity-"
                "checked candidate(s) found, all rejected by the probe"
            )
            attempt.outcome = "rejected_by_probe"
            attempt.reject_reason = "rejected_by_probe"
            attempt.note = (
                f"all {len(tier3_pool)} tier-3 candidate(s) rejected by the probe: "
                + "; ".join(f"{t[0].verdict}:{t[0].reason}" for t in tier3_pool)
            )
            return attempt

        # Every ranked tier-3 candidate was probe-accepted but none could
        # be independently raw-verified as THIS government -- genuinely
        # inconclusive, not a confirmed match either way. Do not queue,
        # do not pin, do not confirm the tenant.
        attempt.note = (
            f"{netloc}: {len(ranked)} probe-accepted tier-3 candidate(s), "
            "none independently raw-verified: " + "; ".join(rejected_notes[:3])
        )
        return attempt

    if saw_conflict:
        # A real tenant answered, but every candidate that carried real
        # content named a DIFFERENT government -- never confirmed for
        # cand.gov_id (see raw_candidate_identity_check's docstring for
        # why "a real tenant exists" and "it is THIS one" are different
        # claims).
        attempt.outcome = "wrong_domain_mapping"
        attempt.reject_reason = "wrong-domain-mapping"
        attempt.note = saw_conflict
    elif any_meeting_evidence:
        # At least one resolved_ok candidate carried real content, passed
        # the meeting-title gate, and passed every conflict check above
        # with no video -- a real, identity-checked negative.
        _confirm(
            f"enumerator listed {listed} candidate(s); a real, identity-checked meeting had no video"
        )
        attempt.outcome = "meeting_without_video"
        attempt.reject_reason = "meeting-without-video"
        attempt.note = f"{netloc}: real meeting(s) found, no video anywhere"
    else:
        # No candidate ever reached resolved_ok at all -- the normal
        # post-resolve identity checks above never ran. Fall back to a
        # raw fetch of the newest actual candidate URL, independent of
        # the adapter, before saying anything about this government.
        newest = ledger.conn.execute(
            "SELECT url_normalized FROM candidates WHERE tenant_netloc = ? "
            "ORDER BY date DESC LIMIT 1",
            (netloc,),
        ).fetchone()
        if newest is None:
            attempt.outcome = "no_meeting_nor_video"
            attempt.note = f"{netloc}: {listed} candidate(s) listed, none with a URL to independently verify"
            return attempt
        verified, detail = await raw_candidate_identity_check(
            session, newest["url_normalized"], cand
        )
        if verified is False:
            attempt.outcome = "wrong_domain_mapping"
            attempt.reject_reason = "wrong-domain-mapping"
            attempt.note = detail
        elif verified is True:
            _confirm(f"enumerator listed {listed} candidate(s); {detail}")
            attempt.outcome = "no_meeting_nor_video"
            attempt.reject_reason = "no-meeting-nor-video"
            attempt.note = (
                f"{netloc}: {listed} candidate(s) listed, none resolved to usable "
                f"content, but a raw fetch confirms this is the right government ({detail})"
            )
        else:
            # Genuinely inconclusive -- do NOT claim this tenant for
            # cand.gov_id. The caller (process_government) tries the
            # next guess; if nothing else pans out, the government ends
            # up "no_tenant_found", which is honest: something answered,
            # but nothing here ever proved whose it was.
            attempt.note = f"{netloc}: {listed} candidate(s) listed, none resolved to usable content, identity unverified ({detail})"
    return attempt


# --------------------------------------------------------------------------
# Per-government driver
# --------------------------------------------------------------------------


async def process_government(
    session: aiohttp.ClientSession,
    ledger: Ledger,
    cand: Cand,
    seeds_w,
    tier3_writer_unused,
) -> Report:
    rep = Report(
        cand.gov_id,
        cand.name,
        cand.state,
        cand.gov_kind,
        cand.population,
        cand.vendor_hint,
    )

    # Step 1: CivicPlus own-domain AgendaCenter, one plain request, free.
    if cand.vendor_hint == "civicplus" and cand.domain:
        hit = await try_civicplus_own_domain(session, cand)
        if hit is not None:
            page_url, html = hit
            link = find_platform_link(html, page_url, exclude=frozenset())
            if link:
                video_url, link_platform = link
                try:
                    from app.platforms.base import get_finder

                    finder = get_finder(link_platform)
                    result = await finder.resolve(video_url)
                except Exception as e:  # noqa: BLE001
                    rep.note = (
                        f"own-domain AgendaCenter link found but resolve failed: {e}"
                    )
                else:
                    meeting_url = video_url
                    segments = result.segments or []
                    effective_title = result.title or ""
                    if not effective_title and result.video_url:
                        effective_title = (
                            await hs.youtube_oembed_title(session, result.video_url)
                            or ""
                        )
                    # Same identity checks the enumerator path runs before
                    # ingesting -- a delegated link is a real, confirmed-
                    # elsewhere risk even on the government's own domain
                    # (BACKLOG.md's Nebraska-villages-delegate-to-
                    # Lancaster-County's-video entry is the exact shape:
                    # a real city page linking to a DIFFERENT government's
                    # video), so this path must not skip them just
                    # because the source page is the government's own.
                    conflict = w145._state_or_kind_conflict(
                        cand,
                        f"{result.jurisdiction or ''} {result.meeting_body or ''}".strip(),
                        "adapter jurisdiction/body",
                    )
                    if not conflict:
                        conflict = w145._state_or_kind_conflict(
                            cand, effective_title, "title"
                        )
                    if not conflict:
                        conflict = w145._title_place_conflict(cand, effective_title)
                    if conflict:
                        rep.outcome = "wrong_domain_mapping"
                        rep.reject_reason = "wrong-domain-mapping"
                        rep.note = f"own-domain AgendaCenter delegated link: {conflict}"
                        return rep
                    if segments or result.video_url:
                        # Route through the same tier1/2 vs tier3 handling
                        # as the enumerator path, by staging it as a
                        # single-candidate "confirmed tenant" pass.
                        rep.tenant_confirmed = "yes"
                        rep.tenant_host = page_url
                        rep.tenant_platform = link_platform
                        rep.how_confirmed = "own-domain AgendaCenter delegated link"
                        result.jurisdiction = cand.jurisdiction
                        if segments:
                            response = await _ingest(
                                session, result.model_dump(), normalize_url(meeting_url)
                            )
                            rep.outcome = "ingested_tier1_2"
                            rep.page_url = (response or {}).get("url") or ""
                            rep.tier = "tier1_2"
                            rep.meeting_url = meeting_url
                            rep.video_url = result.video_url or ""
                            rep.note = f"{len(segments)} transcript segments via own-domain AgendaCenter"
                            return rep
                        probe = await probe_queue_entry(
                            meeting_url,
                            video_url=result.video_url,
                            source_page_url=result.source_url or meeting_url,
                            platform=link_platform,
                        )
                        if probe.verdict in ("accept", "flag-long"):
                            # Same standard as the guessed-tenant tier-3
                            # path: no transcript exists to scan here, so
                            # require an independent raw-page match
                            # before queuing/pinning, not just "no
                            # conflict found."
                            verified, detail = await raw_candidate_identity_check(
                                session, meeting_url, cand
                            )
                            if verified is False:
                                rep.outcome = "wrong_domain_mapping"
                                rep.reject_reason = "wrong-domain-mapping"
                                rep.note = (
                                    f"own-domain AgendaCenter delegated link: {detail}"
                                )
                                return rep
                            if verified is not True:
                                rep.note = f"own-domain AgendaCenter link probe-accepted but identity unverified: {detail}"
                                return rep
                            if meeting_url not in existing_tier3_queue_urls():
                                with TIER3_QUEUE_FILE.open("a", encoding="utf-8") as f:
                                    f.write(meeting_url + "\n")
                                existing_tier3_queue_urls().add(meeting_url)
                            rep.outcome = "queued_tier3"
                            rep.tier = "tier3"
                            rep.meeting_url = meeting_url
                            rep.video_url = result.video_url
                            rep.note = f"own-domain AgendaCenter, probe verdict {probe.verdict}"
                            return rep
                        rep.outcome = "rejected_by_probe"
                        rep.note = f"own-domain AgendaCenter link probe-rejected: {probe.reason}"
        await asyncio.sleep(GUESS_DELAY_SECONDS)

    # Step 2/3: guessed tenant hosts, vendor-hinted first, generic next.
    # best_attempt keeps the single most informative TenantAttempt seen
    # across every guess, by this precedence: a real success beats a
    # confirmed-but-wrong/video-less tenant, which beats "nothing
    # answered at all" -- so the LAST guess tried never silently
    # clobbers an earlier, more useful finding (the bug an early smoke
    # test on St. Louis County caught).
    def _rank(a: "TenantAttempt") -> int:
        if a.success:
            return 3
        if a.confirmed:
            return 2
        if a.outcome == "wrong_domain_mapping":
            return 1
        return 0

    guesses = build_guess_order(cand)
    tried = 0
    best_attempt: Optional[TenantAttempt] = None
    for netloc, platform in guesses:
        tried += 1
        if platform == "civicplus":
            temp = Cand(
                cand.gov_id,
                cand.name,
                cand.state,
                cand.gov_kind,
                cand.population,
                netloc,
                cand.known_platform,
                cand.gated_host,
                cand.source_sweep,
                cand.vendor_hint,
                cand.country,
            )
            civicplus_rep = Report(
                cand.gov_id,
                cand.name,
                cand.state,
                cand.gov_kind,
                cand.population,
                cand.vendor_hint,
            )
            civicplus_rep = await w145.process_civicplus(
                session, temp, civicplus_rep, _NullTier3Writer()
            )
            await asyncio.sleep(GUESS_DELAY_SECONDS)
            this_attempt = TenantAttempt(
                confirmed=civicplus_rep.outcome not in ("skipped", "error"),
                success=civicplus_rep.outcome in ("ingested_tier1_2", "queued_tier3"),
                outcome=civicplus_rep.outcome
                if civicplus_rep.outcome not in ("skipped",)
                else (
                    "wrong_domain_mapping"
                    if civicplus_rep.reject_reason == "wrong-domain-mapping"
                    else None
                ),
                reject_reason=civicplus_rep.reject_reason,
                note=civicplus_rep.note,
                tenant_host=netloc,
                tenant_platform="civicplus",
                how_confirmed="guessed civicplus.com tenant, AgendaCenter walk",
                meeting_url=civicplus_rep.meeting_url,
                video_url=civicplus_rep.video_url,
                tier=civicplus_rep.tier,
                page_url=civicplus_rep.page_url,
            )
        else:
            ok, detail = await w145.check_tenant_identity(session, netloc, cand)
            await asyncio.sleep(GUESS_DELAY_SECONDS)
            if not ok:
                this_attempt = TenantAttempt(
                    confirmed=False,
                    outcome="wrong_domain_mapping",
                    reject_reason="wrong-domain-mapping",
                    note=f"{netloc}: {detail}",
                )
            elif "unreachable" in detail or "fetch failed" in detail:
                this_attempt = TenantAttempt(note=f"{netloc}: {detail}")
            else:
                this_attempt = await process_confirmed_tenant(
                    session, ledger, cand, netloc, platform, seeds_w
                )

        if this_attempt.success:
            rep.tenant_confirmed = "yes"
            rep.tenant_host = this_attempt.tenant_host
            rep.tenant_platform = this_attempt.tenant_platform
            rep.how_confirmed = this_attempt.how_confirmed
            rep.outcome = this_attempt.outcome
            rep.meeting_url = this_attempt.meeting_url
            rep.video_url = this_attempt.video_url
            rep.tier = this_attempt.tier
            rep.page_url = this_attempt.page_url
            rep.note = this_attempt.note
            rep.guesses_tried = tried
            return rep

        if best_attempt is None or _rank(this_attempt) > _rank(best_attempt):
            best_attempt = this_attempt

    rep.guesses_tried = tried
    if best_attempt is None or _rank(best_attempt) == 0:
        rep.outcome = "no_tenant_found"
        rep.reject_reason = "cloudflare-challenge-blocked"
        rep.reject_class = "access"
        rep.note = f"tenant-guess: none of {tried} answered"
    else:
        rep.tenant_confirmed = "yes" if best_attempt.confirmed else "no"
        rep.tenant_host = best_attempt.tenant_host
        rep.tenant_platform = best_attempt.tenant_platform
        rep.how_confirmed = best_attempt.how_confirmed
        rep.outcome = best_attempt.outcome or "no_tenant_found"
        rep.reject_reason = best_attempt.reject_reason
        rep.note = best_attempt.note
    return rep


class _NullTier3Writer:
    def writerow(self, *_a, **_kw):
        pass


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


def _pilot_spread(cands: List[Cand], n: int) -> List[Cand]:
    """Spread across vendor_hint (civicplus/granicus/legistar/blank) and
    gov_kind, largest population first within each bucket."""
    buckets: Dict[Tuple[str, str], List[Cand]] = {}
    for c in cands:
        buckets.setdefault((c.vendor_hint or "generic", c.gov_kind), []).append(c)
    for v in buckets.values():
        v.sort(key=lambda c: -(int(c.population) if c.population.isdigit() else 0))
    out: List[Cand] = []
    keys = list(buckets.keys())
    i = 0
    while len(out) < n and any(buckets.values()):
        k = keys[i % len(keys)]
        if buckets[k]:
            out.append(buckets[k].pop(0))
        i += 1
        if i > 10000:
            break
    return out[:n]


async def main_async(args) -> None:
    if not _base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (check .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    register_all_finders()

    covered_gov_ids = set()
    if args.inventory_csv.exists():
        with args.inventory_csv.open(newline="", encoding="utf-8") as f:
            covered_gov_ids = {
                r["gov_id"] for r in csv.DictReader(f) if r.get("gov_id")
            }
    print(f"{len(covered_gov_ids)} gov_ids already have an archived page.")

    if not SCRATCH_LEDGER.exists():
        shutil.copy2(REAL_LEDGER, SCRATCH_LEDGER)
        print(f"copied {REAL_LEDGER} -> {SCRATCH_LEDGER}")
    ledger = Ledger(str(SCRATCH_LEDGER))

    cands = load_candidates()
    done = _already_done(REPORT_CSV)
    todo = [c for c in cands if c.gov_id not in done]
    if args.pilot:
        todo = _pilot_spread(todo, args.pilot)
    elif args.limit:
        todo = todo[: args.limit]

    print(
        f"Processing {len(todo)} of {len(cands)} candidate(s) ({len(done)} already logged)...\n"
    )

    report_f, report_w = _writer(REPORT_CSV, REPORT_FIELDS)
    seeds_f, seeds_w = _writer(
        DISCOVERY_SEEDS_CSV, ["netloc", "platform", "gov_id", "access_mode"]
    )
    confirmed_f, confirmed_w = _writer(
        CONFIRMED_TENANTS_CSV, ["tenant_host", "platform", "gov_id", "evidence"]
    )

    consecutive_errors = 0
    try:
        async with aiohttp.ClientSession() as session:
            for i, cand in enumerate(todo):
                try:
                    if cand.gov_id in covered_gov_ids:
                        rep = Report(
                            cand.gov_id,
                            cand.name,
                            cand.state,
                            cand.gov_kind,
                            cand.population,
                            cand.vendor_hint,
                            outcome="already_covered",
                        )
                    else:
                        rep = await process_government(
                            session, ledger, cand, seeds_w, None
                        )
                    consecutive_errors = 0
                except Exception as e:  # noqa: BLE001
                    rep = Report(
                        cand.gov_id,
                        cand.name,
                        cand.state,
                        cand.gov_kind,
                        cand.population,
                        cand.vendor_hint,
                        outcome="error",
                        note=f"unhandled: {type(e).__name__}: {e}",
                    )
                    consecutive_errors += 1

                if not rep.reject_class:
                    rep.reject_class = w145._reject_class(rep.reject_reason)
                if rep.tenant_confirmed == "yes" and rep.tenant_host:
                    confirmed_w.writerow(
                        {
                            "tenant_host": rep.tenant_host,
                            "platform": rep.tenant_platform,
                            "gov_id": cand.gov_id,
                            "evidence": rep.how_confirmed,
                        }
                    )
                    confirmed_f.flush()

                report_w.writerow(rep.__dict__)
                report_f.flush()
                seeds_f.flush()
                ledger.conn.commit()
                print(
                    f"[{i + 1}/{len(todo)}] [{rep.outcome:20}] {rep.gov_id} {rep.name!r} "
                    f"vendor_hint={rep.vendor_hint!r} tenant={rep.tenant_host!r} -- {rep.reject_reason or rep.note}"
                )

                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(
                        f"\nABORTING: {consecutive_errors} consecutive real errors.",
                        file=sys.stderr,
                    )
                    break
                if i < len(todo) - 1:
                    await asyncio.sleep(REQUEST_DELAY_SECONDS)
    finally:
        report_f.close()
        seeds_f.close()
        confirmed_f.close()
        ledger.close()

    hs.write_pins()
    print(f"\nFull report: {REPORT_CSV}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pilot",
        type=int,
        default=None,
        help="spread N rows across vendor_hint/gov_kind",
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--inventory-csv", type=Path, default=DEFAULT_INVENTORY_CSV)
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
