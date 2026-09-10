"""WO-145: API-first breadth sweep of 772 never-listed known-platform
governments (rtr-business/research/wo145_candidates.csv).

Goal (docs/BREADTH_SWEEP_BRIEF.md): one meeting WITH VIDEO per
government, breadth not depth. If the first video meeting fails to
resolve, take the next one, up to 6 per government. Ryan's ingest rule
is absolute: only meetings with video become Archive pages. Tier 1/2
(captions reachable) ingest with segments; tier 3 (video, no reachable
captions) is NOT queued directly by this script -- it is written to
wo145_tier3_pending.csv only. Moving accepted entries into the real
queue happens in a separate pass, once WO-144's probe helper
(scripts/probe_tier3_queue.py) is merged -- not part of this script.
Agenda-only is recorded no-video-found and never ingested.

Method, per government, in priority order:

1. Platform API first. For every platform except civicplus, this is
   rtr-discovery's own enumerator (discovery.enumerate_stage /
   discovery.resolve), run in thorough mode against a SCRATCH ledger
   copy (never the real ~/Documents/rtr-discovery/ledger.db). The tenant
   netloc is derived the way wo142_pilot.py's _PLATFORM_SUFFIX rule
   does: domain only if it already ends in the platform's own suffix,
   else hub_url, else discovery_tenant. Before enumerating, the tenant's
   identity is checked against the row's own name/state (a fetched
   landing-page title compared for a contradicting state or a
   municipality/county kind conflict -- the exact shape of WO-142's 4
   confirmed collisions); a confident mismatch is recorded
   wrong-domain-mapping and skipped, never resolved. The gov_id is
   seeded into the tenant BEFORE enumerating (ledger.set_tenant_gov_id),
   per WO-142's own qualification #1, so a delegated video (a CivicPlus
   page linking to YouTube -- N/A here, this repo only, but the same
   fix applies to Granicus/CivicPlus links a listing might surface)
   keeps the government's identity.

   CivicPlus (577 of 772 rows) is the one platform this repo does NOT
   run through discovery's enumerator for: its own civicplus.py
   enumerator calls this repo's OWN `CivicPlusAssetFinder
   ._find_candidate_rows()` -- the identical parser
   scripts/hub_sweep_wo126.py's AgendaCenter year-fragment walk already
   uses -- so it adds no depth (BREADTH_SWEEP_BRIEF.md's own CivicPlus
   note). This script imports hub_sweep_wo126's walk (civicplus_walk,
   Fetcher, resolve_lead, key_check, pin_for, _pick_agenda_row,
   _agenda_only_meeting) directly rather than re-implementing it.

2. Plain HTTP with honest headers (wo141_access_ladder_pilot.py's
   HONEST_HEADERS), only for a government whose netloc cannot be
   derived for a platform that needs a tenant host (cablecast, civicweb
   custom domains, granicus custom domains): fetch the home page and
   scan for a platform link.
3. Browser headers, once, only after a 403 or a dropped connection.
   Never after a 404.
4. Headless browsing (step 4 of the brief) is NOT implemented in this
   pass -- a real gap, reported honestly rather than silently skipped;
   see this file's own report and BACKLOG.md.
5. Stop at a human-verification gate. Never retried.

Usage (repo root, discovery's own venv -- the shared deeplink .venv
cannot import `discovery`; see this file's own import-compatibility
note below):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo145_scratch.db" \\
    ~/Documents/rtr-discovery/.venv/bin/python scripts/wo145_api_first_sweep.py --pilot 25
    ... (same) ... scripts/wo145_api_first_sweep.py --limit 200
    ... (same) ... scripts/wo145_api_first_sweep.py

Resumable: rtr-business/research/wo145_report.csv is flushed one row at
a time; a gov_id already present there is skipped on re-run.
"""

import argparse
import asyncio
import csv
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# rtr-discovery's discovery/deeplink.py imports this repo's app.platforms
# code via RTR_DEEPLINK_PATH, defaulting to a SIBLING "../../rtr-deeplink"
# checkout -- wrong for a session working inside a
# .claude/worktrees/<name> worktree (CLAUDE.md's worktree-isolation
# rule): must point at THIS worktree, set before discovery is imported.
os.environ.setdefault("RTR_DEEPLINK_PATH", str(REPO_ROOT))
DISCOVERY_ROOT = Path.home() / "Documents" / "rtr-discovery"
sys.path.insert(0, str(DISCOVERY_ROOT))

import aiohttp  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import detect_platform  # noqa: E402
from app.platforms.models import ResolvedMeeting  # noqa: E402
from app.platforms.queue_probe import (  # noqa: E402
    DEFAULT_SIDECAR_PATH,
    append_probe_row,
    probe_queue_entry,
)
from app.utils.url_normalize import normalize_url  # noqa: E402
from scripts.bulk_ingest import _base_url, _ingest  # noqa: E402
import scripts.hub_sweep_wo126 as hs  # noqa: E402

from discovery.ledger import Ledger  # noqa: E402
from discovery.enumerate_stage import enumerate_candidates  # noqa: E402
from discovery.resolve import resolve_candidates  # noqa: E402

# This run's own attribution on every pin/report row -- distinct from
# hub_sweep_wo126's own PIN_SOURCE, so a shared-host pin's `source`
# column always says which work order actually found it.
hs.PIN_SOURCE = "wo145_api_first_sweep"

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
CANDIDATES_CSV = RESEARCH_DIR / "wo145_candidates.csv"
REPORT_CSV = RESEARCH_DIR / "wo145_report.csv"
DISCOVERY_SEEDS_CSV = RESEARCH_DIR / "wo145_discovery_seeds.csv"
TIER3_PENDING_CSV = RESEARCH_DIR / "wo145_tier3_pending.csv"
hs.PINS_CSV = RESEARCH_DIR / "wo145_pins.csv"

REAL_LEDGER = DISCOVERY_ROOT / "ledger.db"
SCRATCH_LEDGER = Path("/tmp/wo145_ledger.db")

DEFAULT_INVENTORY_CSV = Path("/tmp/wo145_inventory/meeting_inventory.csv")

REQUEST_DELAY_SECONDS = 1.5  # between governments
CANDIDATE_DELAY_SECONDS = 0.75  # between depth attempts on one tenant
MAX_CANDIDATES_TRIED = 6
MAX_CONSECUTIVE_ERRORS = 6

# --- platforms ---------------------------------------------------------

# Every platform in the candidate list except civicplus (handled via the
# AgendaCenter walk, see module docstring). proudcity has zero rows in
# this candidate list but is kept here for completeness/symmetry with
# wo142_pilot.py's own table.
ENUMERATOR_PLATFORMS = {
    "primegov",
    "civicclerk",
    "civicweb",
    "escribe",
    "legistar",
    "granicus",
    "swagit",
    "iqm2",
    "proudcity",
    "cablecast",
    "municode_meetings",
}

_PLATFORM_SUFFIX = {
    "granicus": "granicus.com",
    "civicclerk": "civicclerk.com",
    "primegov": "primegov.com",
    "escribe": "escribemeetings.com",
    "legistar": "legistar.com",
    "swagit": "swagit.com",
    "iqm2": "iqm2.com",
    "cablecast": "cablecast.tv",
    "municode_meetings": "municodemeetings.com",
    "civicweb": "civicweb.net",
}

# Platforms WO-142 found have no reliable domain/hub_url derivation path
# in this registry -- these are the ones that fall to the plain-HTTP
# ladder (step 2/3) when domain/hub_url/discovery_tenant don't resolve.
NEEDS_TENANT_DISCOVERY = {"cablecast", "civicweb", "granicus"}

SHARED_HOST_PLATFORMS = {"youtube", "vimeo", "telvue", "cablecast"}

# hub_sweep_wo126.HIGH_RISK_TITLE_PLATFORMS is {"youtube", "vimeo"} only --
# right for that script's own leads (a bare video-host link scraped off a
# page), but wrong for a structured Cablecast listing candidate resolved
# through this script's own enumerator path: Cablecast is a general PEG/
# community-access broadcast platform, not a dedicated meeting system,
# and its own tenant can carry non-meeting programming alongside real
# council meetings. Real, confirmed-live false positive (2026-09-10,
# pilot smoke test): Hometown, IL's cablecast tenant resolved
# "Weekly Chat, Explosion in E-Learning!" and "Case Study: HCAM" as if
# they were real meetings -- neither has a governing-body keyword, and
# neither the blocklist (not promotional) nor hub_sweep_wo126's own
# HIGH_RISK_TITLE_PLATFORMS (cablecast isn't in it) caught this, so it
# would have been queued to tier 3 as a "meeting" with no meeting in it.
# Swagit carries the identical risk (a government's own general-purpose
# video channel, not a dedicated meeting system) and is added
# defensively even without an observed live false positive yet.
ENUMERATOR_HIGH_RISK_TITLE_PLATFORMS = hs.HIGH_RISK_TITLE_PLATFORMS | {
    "cablecast",
    "swagit",
}

# Confirmed real US/Canada name collisions on both -- see
# _load_canadian_csd_names()'s own docstring.
CROSS_BORDER_RISK_PLATFORMS = {"escribe", "civicweb"}

# --- honest / browser headers (wo141_access_ladder_pilot.py, verbatim) --

HONEST_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "user-agent": (
        "rtr-upcoming/0.1 (Red Tape Recordings public-agenda reader; "
        "+https://redtaperecordings.com/about)"
    ),
}
BROWSER_HEADERS = {
    "accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "accept-language": "en-US,en;q=0.9",
    "sec-ch-ua": '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/151.0.0.0 Safari/537.36"
    ),
}
CHALLENGE_MARKERS = (
    "just a moment",
    "attention required! | cloudflare",
    "checking your browser before accessing",
    "cf-browser-verification",
    "cf-chl-bypass",
    "ddos protection by",
    "sgcaptcha",
    "px-captcha",
    "perimeterx",
    "distil_r_captcha",
    "captcha-delivery",
    "request unsuccessful. incapsula",
    "access to this page has been denied",
)

# --- state/province full names, from this repo's own registry tables,
# not hand-duplicated -- used only for the tenant-identity check below.


def _load_state_names() -> Dict[str, str]:
    names: Dict[str, str] = {}
    with (REPO_ROOT / "app/utils/jurisdiction_data/us_states.csv").open(
        newline="", encoding="utf-8"
    ) as f:
        for r in csv.DictReader(f):
            names[r["state"].upper()] = r["name"]
    with (REPO_ROOT / "app/utils/jurisdiction_data/ca_pr.csv").open(
        newline="", encoding="utf-8"
    ) as f:
        for r in csv.DictReader(f):
            names[r["province"].upper()] = r["name"]
    return names


STATE_NAMES = _load_state_names()

_GENERIC_NAME_WORDS = {
    "city",
    "county",
    "town",
    "township",
    "village",
    "borough",
    "cdp",
    "of",
    "the",
    "municipality",
    "parish",
    "charter",
    "corporation",
    "cousub",
    "district",
    "regional",
    "municipal",
}


def _name_tokens(name: str) -> set:
    words = re.findall(r"[a-z']+", (name or "").lower())
    return {w for w in words if w not in _GENERIC_NAME_WORDS and len(w) > 2}


def netloc_of(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "https://" + raw
    return urlparse(raw).netloc.lower().rstrip("/")


# --------------------------------------------------------------------------
# Candidate row
# --------------------------------------------------------------------------


@dataclass
class Cand:
    gov_id: str
    name: str
    state: str
    country: str
    gov_kind: str
    population: str
    domain: str
    known_platform: str
    platform_norm: str
    hub_url: str
    test_status: str
    reject_reason: str
    discovery_tenant: str

    @property
    def jurisdiction(self) -> str:
        return f"{self.name}, {self.state}"


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
                country=(r.get("country") or "").strip(),
                gov_kind=(r.get("gov_kind") or "").strip(),
                population=(r.get("population") or "").strip(),
                domain=(r.get("domain") or "").strip(),
                known_platform=(r.get("known_platform") or "").strip().lower(),
                platform_norm=(r.get("platform_norm") or "").strip().lower(),
                hub_url=(r.get("hub_url") or "").strip(),
                test_status=(r.get("test_status") or "").strip(),
                reject_reason=(r.get("reject_reason") or "").strip(),
                discovery_tenant=(r.get("discovery_tenant") or "").strip(),
            )
        )
    return out


REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "population",
    "platform",
    "netloc",
    "access_mode",
    "outcome",
    "reject_reason",
    "reject_class",
    "candidates_listed",
    "candidates_tried",
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
    platform: str = ""
    netloc: str = ""
    access_mode: str = ""
    outcome: str = "skipped"
    reject_reason: str = ""
    reject_class: str = ""
    candidates_listed: int = 0
    candidates_tried: int = 0
    meeting_url: str = ""
    video_url: str = ""
    tier: str = ""
    page_url: str = ""
    note: str = ""


CONTENT_REASONS = {
    "no-platform-link-found",
    "no-meetings-found",
    "no-video-found",
    "off-mission",
    "unsupported-platform-no-adapter",
    "wrong-domain-mapping",
    "resolve-failed",
}
ACCESS_REASONS = {
    "blocked-plain-http",
    "blocked-browser-headers",
    "blocked-headless",
    "cloudflare-challenge-blocked",
    "dns-unresolvable",
    "timeout",
}


def _reject_class(reason: str) -> str:
    if reason in ACCESS_REASONS:
        return "access"
    if reason in CONTENT_REASONS:
        return "content"
    return ""


def _already_done(path: Path) -> set:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f) if r.get("gov_id")}


def _report_writer(path: Path):
    is_new = not path.exists()
    f = path.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=REPORT_FIELDS)
    if is_new:
        w.writeheader()
        f.flush()
    return f, w


def _seeds_writer(path: Path):
    is_new = not path.exists()
    f = path.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=["netloc", "platform", "gov_id", "access_mode"])
    if is_new:
        w.writeheader()
        f.flush()
    return f, w


TIER3_PENDING_FIELDS = [
    "gov_id",
    "platform",
    "meeting_url",
    "video_url",
    "source_url",
    "jurisdiction",
    "pin_row",
]


def _tier3_pending_writer(path: Path):
    is_new = not path.exists()
    f = path.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=TIER3_PENDING_FIELDS)
    if is_new:
        w.writeheader()
        f.flush()
    return f, w


# --------------------------------------------------------------------------
# Tenant-identity check (WO-142's qualification #2: don't trust
# domain/hub_url as the real tenant host without a suffix check first --
# and separately, don't trust the ROW's gov_id->tenant mapping either,
# which is what this check is for)
# --------------------------------------------------------------------------


_LEADING_PLACE_STATE_RE = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9\s.'\-]*?),\s*([A-Za-z]{2})\b"
)


def _state_or_kind_conflict(cand: Cand, text: str, source: str) -> Optional[str]:
    """Shared mismatch detector, applied to two different kinds of text:
    a fetched landing-page title (pre-resolve, see check_tenant_identity)
    and the adapter's own raw resolved jurisdiction/meeting_body
    (post-resolve, see act_on_result) -- the second is the stronger
    signal. Two real, confirmed-live bugs shaped this, both found
    smoke-testing this script 2026-09-10, both the WO-142 collision
    class:

    1. Flemington borough, NJ -> hunterdonconj.portal.civicclerk.com,
       whose real content is Hunterdon COUNTY's commissioner meetings --
       caught by the county-keyword rule below. Missed by the
       landing-page check alone because CivicClerk's public portal root
       is a JS-rendered SPA shell with no government-identifying text
       server-side (`<title>Public Portal (bullet) CivicClerk</title>`).
    2. Crystal River city, FL -> citrusclerk.portal.civicclerk.com,
       whose real content is mostly Citrus COUNTY meetings (caught by
       the same rule) but ONE candidate resolved with jurisdiction
       "Inverness, FL" -- a real, different, specific Florida city, same
       state as the row, no "county" keyword at all -- and was
       INGESTED to production before this rule existed (deleted via
       POST /internal/admin/delete-pages the same session; see
       BACKLOG_DONE.md's WO-145 entry). The county-keyword rule alone
       cannot catch a same-state, different-CITY mismatch -- this
       needs the leading "Name, ST" pattern parsed out and its own name
       tokens compared against the row's, not just a keyword scan.

    Returns a reason string on a CONFIDENT mismatch, None otherwise
    (inconclusive is not a mismatch)."""
    text = (text or "").strip()
    if not text:
        return None
    text_lower = text.lower()
    row_state = cand.state.strip().upper()
    row_state_name = STATE_NAMES.get(row_state, "")

    m = _LEADING_PLACE_STATE_RE.match(text)
    if m and m.group(2).upper() in STATE_NAMES:
        place_part, state_part = m.group(1), m.group(2).upper()
        if state_part != row_state:
            return (
                f"{source} {text!r} names state {state_part!r} "
                f"({STATE_NAMES.get(state_part, state_part)}), row expects "
                f"{row_state_name!r} ({cand.name})"
            )
        place_tokens = _name_tokens(place_part)
        row_tokens = _name_tokens(cand.name)
        if place_tokens and row_tokens and not (place_tokens & row_tokens):
            return (
                f"{source} {text!r} names a specific place ({place_part!r}) "
                f"with no name overlap with the row ({cand.name})"
            )

    for abbr, fullname in STATE_NAMES.items():
        if abbr == row_state or not fullname:
            continue
        if fullname.lower() in text_lower:
            return f"{source} {text!r} names {fullname!r}, row expects {row_state_name!r} ({cand.name})"
    if cand.gov_kind == "municipality" and "county" not in cand.name.lower():
        if re.search(r"\bcounty\b", text_lower):
            return f"{source} {text!r} mentions 'County', row is a municipality ({cand.name})"
    return None


def _load_canadian_csd_names() -> set:
    """Every Canadian municipality name (`ca_csd.csv`'s own `name`
    column, lowercased), used only by `_cross_border_collision` below.
    Real, confirmed-live bug (2026-09-10, WO-145 full run): 4 of this
    run's first 5 tier1/2 ingests were WRONG -- pub-cornwall.
    escribemeetings.com, pub-erin.escribemeetings.com, pub-clarington.
    escribemeetings.com and pub-pickering.escribemeetings.com all
    resolve real content for real ONTARIO municipalities (Cornwall,
    Erin, Clarington, Pickering, all confirmed in `ca_csd.csv`), matched
    by this sweep's candidate list to identically-named but wrong US
    rows (Cornwall borough PA, Erin city TN, Clarington village OH,
    Pickering city MO) purely on name-string collision. eScribe's own
    adapter returns a bare jurisdiction/meeting_body/title with NO
    state/province code at all ("City of Cornwall", "Town of Erin",
    "Clarington", "City of Pickering") -- `_state_or_kind_conflict()`'s
    leading "Name, ST" pattern never matches, so it saw no conflict. This
    is the exact class BACKLOG.md's own "`pub-*` eScribe hosts resolve to
    a US government of the same name" entry already documented (Richmond
    BC/CA, Salmon Arm BC/ID, Courtenay BC/ND, Owen Sound ON/WI) --
    confirmed again, worse, here. All 4 wrongly-ingested pages were
    deleted via `POST /internal/admin/delete-pages` the same session."""
    names = set()
    with (REPO_ROOT / "app/utils/jurisdiction_data/ca_csd.csv").open(
        newline="", encoding="utf-8"
    ) as f:
        for r in csv.DictReader(f):
            names.add((r.get("name") or "").strip().lower())
    return names


CANADIAN_CSD_NAMES = _load_canadian_csd_names()


def _cross_border_collision(cand: Cand, text: str) -> Optional[str]:
    """A real, same-named Canadian municipality exists (per `ca_csd.csv`)
    and the resolved text carries no state/province code to rule it out
    -- see `_load_canadian_csd_names()`'s own docstring for the concrete
    incident this fixes. Scoped to CROSS_BORDER_RISK_PLATFORMS (eScribe,
    CivicWeb) -- both platforms confirmed, in this repo's own history, to
    serve US and Canadian customers under the same bare-name convention;
    other platforms in this sweep return a "Name, ST" jurisdiction
    reliably enough that `_state_or_kind_conflict` already covers them.
    Only fires for a US row (a Canadian row with the same collision has
    nothing to disambiguate FROM -- it would already be the right
    government)."""
    if cand.country != "us":
        return None
    if _LEADING_PLACE_STATE_RE.search(text or ""):
        return None  # has an explicit state/province code -- other check handles it
    row_base = _name_tokens(cand.name)
    if not row_base:
        return None
    # A single-token exact name match against the real Canadian
    # municipality list -- e.g. {"cornwall"} == {"cornwall"}. Broader
    # multi-word names (rare for a CSD) still work via set equality.
    if row_base <= {n for name in CANADIAN_CSD_NAMES for n in _name_tokens(name)}:
        for csd_name in CANADIAN_CSD_NAMES:
            if _name_tokens(csd_name) == row_base:
                return (
                    f"a real Canadian municipality named {csd_name!r} exists "
                    f"(ca_csd.csv) and the resolved text {text!r} carries no "
                    f"state/province code to rule it out -- refusing to trust "
                    f"a bare name match ({cand.name}, {cand.state})"
                )
    return None


_TITLE_PLACE_RE = re.compile(
    r"\b([A-Z][A-Za-z.'-]*(?:\s+[A-Z][A-Za-z.'-]*){0,3})\s+"
    r"(school board|select ?board|city council|town council|village board|"
    r"town board|board of (?:trustees|selectmen|aldermen)|planning board)\b",
    re.IGNORECASE,
)


def _title_place_conflict(cand: Cand, title: str) -> Optional[str]:
    """A THIRD real, confirmed-live mismatch class, distinct from
    _state_or_kind_conflict: a resolved candidate whose jurisdiction
    field is not independent evidence at all, because this script
    itself seeded the tenant's gov_id before resolving
    (set_tenant_gov_id) -- so a candidate that carries no per-meeting
    government signal of its own just echoes the seed back, and the
    jurisdiction-based check above is circular for it. Confirmed live
    2026-09-10: `hometown.cablecast.tv` -- a real small town, "Hometown,
    IL", but this specific tenant turned out to be Cablecast's own
    vendor demo/sample site (show titles: "PEG Experts: PDFs", "Tech
    Trainings: Sidecar Files", "Cruising Galapagos", "VIO Stream
    Explainer") -- every candidate resolved with jurisdiction="Hometown,
    IL" (this script's own seed, reflected back), so the check above
    saw no conflict. The one real tell was in the TITLE itself:
    "YourTown School Board Meeting with Agenda" and "YourTown
    Selectboard Meeting 4-1-2023" -- "YourTown" is the vendor's own
    generic placeholder name in its demo content, not "Hometown", and
    that mismatch is independent of the (contaminated) jurisdiction
    field. This is a narrower, title-text-only check -- a non-match
    (no recognizable "<Place> <governing body>" phrase in the title at
    all) is NOT a mismatch, same "inconclusive isn't proof" rule as the
    other checks."""
    if not title:
        return None
    for m in _TITLE_PLACE_RE.finditer(title):
        place = m.group(1)
        place_tokens = _name_tokens(place)
        row_tokens = _name_tokens(cand.name)
        if place_tokens and row_tokens and not (place_tokens & row_tokens):
            return f"title {title!r} names {place!r}, no overlap with the row ({cand.name})"
    return None


async def check_tenant_identity(
    session: aiohttp.ClientSession, netloc: str, cand: Cand
) -> Tuple[bool, str]:
    """Fetch the tenant's landing page and look for a CONFIDENT mismatch
    against the row's own name/state/kind -- the exact shape of WO-142's
    4 confirmed cross-jurisdiction collisions (Ventura city IA -> Ventura
    County CA; Dane village WI -> Dane County WI; Lake town MS -> Lake
    County IL; Laverne town OK -> La Verne CA). An inconclusive fetch
    (blocked, no page text, no name-token match) is NOT treated as a
    mismatch -- absence of confirmation isn't proof of a wrong mapping,
    and this repo's "reports report, never guess" rule cuts both ways.

    This is a WEAKER check than the post-resolve one in act_on_result()
    (see _state_or_kind_conflict's own docstring) -- a JS-rendered portal
    shell (CivicClerk, some CivicWeb tenants) carries no real text here
    at all, so this check alone is not sufficient; both are run."""
    try:
        async with session.get(
            f"https://{netloc}/",
            headers=hs.UA_HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
            allow_redirects=True,
        ) as resp:
            if resp.status >= 400:
                return True, "landing page unreachable, unverified"
            html = await resp.text(errors="replace")
    except Exception as e:  # noqa: BLE001
        return True, f"landing page fetch failed, unverified: {type(e).__name__}"

    soup = BeautifulSoup(html, "html.parser")
    title = (soup.title.get_text(strip=True) if soup.title else "") or ""
    conflict = _state_or_kind_conflict(cand, title, "title")
    if conflict:
        return False, conflict

    title_lower = title.lower()
    body_text = soup.get_text(" ", strip=True)[:3000].lower()
    tokens = _name_tokens(cand.name)
    if tokens and not any(t in title_lower or t in body_text for t in tokens):
        return True, "no name-token match on landing page (unverified, not a mismatch)"
    return True, "confirmed" if tokens else "unverified (no name tokens to check)"


def derive_netloc(cand: Cand) -> Tuple[Optional[str], str]:
    """wo142_pilot.py's own rule: domain only if it already ends in the
    platform's own suffix, else hub_url, else discovery_tenant."""
    suffix = _PLATFORM_SUFFIX.get(cand.platform_norm)
    dom = netloc_of(cand.domain)
    if suffix and dom.endswith(suffix):
        return dom, "domain"
    hub = netloc_of(cand.hub_url)
    if hub:
        return hub, "hub_url"
    tenant = netloc_of(cand.discovery_tenant)
    if tenant:
        return tenant, "discovery_tenant"
    return None, ""


# --------------------------------------------------------------------------
# Ingest / tier-3-pending, reusing hub_sweep_wo126's key_check/pin_for
# --------------------------------------------------------------------------


async def _ingest_with_retry(session, payload, normalized) -> Optional[dict]:
    for attempt in (1, 2):
        try:
            return await _ingest(session, payload, normalized)
        except Exception:  # noqa: BLE001
            if attempt == 2:
                return None
            await asyncio.sleep(3)
    return None


def _pin_for_pending(
    cand: Cand, source_url: str, video_url: str, platform: str
) -> Optional[dict]:
    """Same rule as hs.pin_for(), reused via a Gov shim -- computed now,
    at write time, so the pin travels with the pending row and is only
    actually staged once the entry is accepted after the probe."""
    gov = hs.Gov(
        cand.gov_id,
        cand.name,
        cand.state,
        cand.hub_url,
        cand.domain,
        cand.reject_reason,
    )
    return hs.pin_for(gov, source_url, video_url, platform)


def _apply_skip_to_report(rep: Report, e: "hs.Skip") -> Report:
    """WO-169: mirrors hs._apply_skip() for this script's own Report
    dataclass (not hs.Result -- Report's field set differs, so this is a
    small duplicate rather than a shared function). Carries a Skip's
    meeting_url/video_url onto the report row instead of dropping them
    (the exact gap WO-151 found -- see hs.Skip's own docstring), and
    gives an hs.ProbeRejected instance its own `rejected_by_probe`
    outcome rather than folding it into `skipped`."""
    rep.outcome = "rejected_by_probe" if isinstance(e, hs.ProbeRejected) else "skipped"
    rep.reject_reason = e.reject_reason
    rep.note = e.detail
    rep.meeting_url = e.meeting_url or rep.meeting_url
    rep.video_url = e.video_url or rep.video_url
    if rep.outcome == "skipped" and rep.video_url and not rep.meeting_url:
        rep.reject_reason = "video-without-meeting"
    return rep


async def _passes_probe(
    platform: str, result: ResolvedMeeting, meeting_url: str
) -> bool:
    """WO-169: "probe before queue," same rule as every other sweep
    (docs/BREADTH_SWEEP_BRIEF.md). Real captions (segments) never reach
    here -- see act_on_result()'s own call site -- so this only ever
    probes a tier-3 (video, no captions) candidate."""
    probe = await probe_queue_entry(
        meeting_url,
        video_url=result.video_url,
        source_page_url=result.source_url or meeting_url,
        platform=platform,
    )
    append_probe_row(DEFAULT_SIDECAR_PATH, probe)
    return probe.verdict not in ("reject-dead", "reject-short")


async def act_on_result(
    session: aiohttp.ClientSession,
    cand: Cand,
    platform: str,
    result: ResolvedMeeting,
    meeting_url: str,
    high_risk: bool,
    rep: Report,
    tier3_writer,
) -> Report:
    """WO-145's own equivalent of hub_sweep_wo126's act_on_resolved(),
    with one deliberate difference: a video-no-captions candidate is
    NEVER appended to the real tier3_auto_transcription_queue.txt here --
    it is written to wo145_tier3_pending.csv for WO-144's probe to
    accept or refuse first (this WO's own explicit "probe before queue"
    rule)."""
    # Real, confirmed-live bug (2026-09-10): `rep` is reused across every
    # candidate this tenant tries (process_enumerator_platform's own
    # loop), and an earlier candidate's Skip sets rep.reject_reason/note
    # on it. Without clearing them here, a LATER candidate that succeeds
    # still reports the earlier failure's reject_reason on an
    # ingested_tier1_2/queued_tier3_pending row -- caught spot-checking
    # the pilot's own report (Crystal River city, FL showed
    # outcome=ingested_tier1_2 with reject_reason=wrong-domain-mapping
    # left over from a rejected sibling candidate on the same tenant).
    rep.reject_reason = ""
    rep.note = ""
    segments = result.segments or []
    agenda_items = result.agenda_items or []
    if not (segments or agenda_items or result.agenda_link or result.video_url):
        raise hs.Skip(
            "no-video-found", f"{platform}: resolved but nothing at all ({meeting_url})"
        )

    effective_title = result.title or ""
    if not effective_title and result.video_url:
        effective_title = await hs.youtube_oembed_title(session, result.video_url) or ""
    if not hs._looks_like_real_meeting(effective_title, require_allowlist=high_risk):
        raise hs.Skip(
            "off-mission",
            f"{platform}: title looks like a non-meeting video: {effective_title!r} ({meeting_url})",
        )

    # Post-resolve identity check, stronger than the pre-resolve landing-
    # page one: the adapter's OWN raw jurisdiction/meeting_body, before
    # this script overwrites it with the row's claimed government. See
    # _state_or_kind_conflict's docstring for the real Flemington
    # borough NJ / Hunterdon County NJ CivicClerk bug this catches.
    adapter_signal = f"{result.jurisdiction or ''} {result.meeting_body or ''}".strip()
    conflict = _state_or_kind_conflict(
        cand, adapter_signal, "adapter jurisdiction/body"
    )
    if conflict:
        raise hs.Skip("wrong-domain-mapping", conflict)

    # Same check, run again against the TITLE -- catches a bare-video-
    # host delegation (YouTube/Vimeo/Cablecast) where the adapter itself
    # never populates jurisdiction/meeting_body at all, so the check
    # above has nothing to compare. Real, confirmed-live bug (2026-09-10,
    # WO-145 full run): 4 different Nebraska villages (Denton, Raymond,
    # Sprague, Davey) all delegated, via their CivicPlus AgendaCenter
    # pages, to the exact same YouTube video -- "Lancaster County Board
    # of Commissioners Meeting" (confirmed via YouTube's own oEmbed:
    # author "Lancaster County, Nebraska"), not any of the four villages'
    # own meetings. `_title_place_conflict`'s narrow institution-phrase
    # regex doesn't cover "Board of Commissioners", so it missed this;
    # reusing `_state_or_kind_conflict`'s general county-keyword rule
    # against the title catches it directly, with no new pattern needed.
    conflict = _state_or_kind_conflict(cand, effective_title, "title")
    if conflict:
        raise hs.Skip("wrong-domain-mapping", conflict)

    # Independent of the jurisdiction field, which this script's own
    # tenant_gov_id seed can make circular for a candidate with no
    # per-meeting government signal of its own -- see
    # _title_place_conflict's own docstring for the real vendor-demo-
    # tenant bug this catches (hometown.cablecast.tv).
    title_conflict = _title_place_conflict(cand, effective_title)
    if title_conflict:
        raise hs.Skip("wrong-domain-mapping", title_conflict)

    # A FOURTH real, confirmed-live mismatch class: eScribe/CivicWeb
    # return a bare jurisdiction/meeting_body/title with no state or
    # province code at all, so neither check above has anything to
    # compare -- see _load_canadian_csd_names()'s docstring for the real
    # incident (Cornwall/Erin/Clarington/Pickering, all real Ontario
    # municipalities, wrongly matched to identically-named US rows and
    # ingested before this check existed).
    if platform in CROSS_BORDER_RISK_PLATFORMS:
        combined = f"{result.jurisdiction or ''} {result.meeting_body or ''} {effective_title or ''}".strip()
        border_conflict = _cross_border_collision(cand, combined)
        if border_conflict:
            raise hs.Skip("wrong-domain-mapping", border_conflict)

    result.jurisdiction = cand.jurisdiction
    gov = hs.Gov(
        cand.gov_id,
        cand.name,
        cand.state,
        cand.hub_url,
        cand.domain,
        cand.reject_reason,
    )

    if segments:
        ok, tier = hs.key_check(
            gov, cand.jurisdiction, result.source_url or meeting_url
        )
        if not ok:
            pin = hs.pin_for(
                gov, result.source_url or meeting_url, result.video_url or "", platform
            )
            if pin:
                hs.stage_pin(pin, dry_run=False)
        response = await _ingest_with_retry(
            session, result.model_dump(), normalize_url(meeting_url)
        )
        if response is None:
            raise hs.Skip(
                "resolve-failed",
                f"{platform}: resolved {len(segments)} segments but POST failed twice",
            )
        rep.outcome = "ingested_tier1_2"
        rep.page_url = response.get("url") or ""
        rep.tier = "tier1_2"
        rep.meeting_url = meeting_url
        rep.video_url = result.video_url or ""
        rep.note = f"{len(segments)} transcript segments" + (
            "" if response.get("created") else " (matched an existing page)"
        )
        return rep

    if result.video_url:
        # WO-169: probe before this candidate is even written to the
        # pending sink -- the real, confirmed bug this closes is that
        # wo145_tier3_pending.csv committed to the FIRST candidate with a
        # video_url and never revisited it, so a later probe reject (in
        # whatever process reads that pending file) ended the government's
        # whole attempt. Raising hs.ProbeRejected here instead lets this
        # function's own CALLERS -- process_enumerator_platform()'s
        # `for row in resolved_rows:` loop already has `except hs.Skip as
        # e: ...; continue`, and process_civicplus()'s own except-Skip
        # sites -- try the next candidate exactly the way any other Skip
        # already does. 10 of this WO's own governments were dropped this
        # way (see BACKLOG_DONE.md's WO-169 entry).
        if not await _passes_probe(platform, result, meeting_url):
            raise hs.ProbeRejected(
                "rejected_by_probe",
                f"{platform}: resolved real video but it failed WO-144's queue "
                f"probe ({meeting_url})",
                meeting_url=meeting_url,
                video_url=result.video_url or "",
            )
        pin = _pin_for_pending(
            cand, result.source_url or meeting_url, result.video_url, platform
        )
        tier3_writer.writerow(
            {
                "gov_id": cand.gov_id,
                "platform": platform,
                "meeting_url": meeting_url,
                "video_url": result.video_url,
                "source_url": result.source_url or meeting_url,
                "jurisdiction": cand.jurisdiction,
                "pin_row": json.dumps(pin) if pin else "",
            }
        )
        rep.outcome = "queued_tier3_pending"
        rep.tier = "tier3"
        rep.meeting_url = meeting_url
        rep.video_url = result.video_url
        rep.note = "real video, no captions -- written to wo145_tier3_pending.csv, awaiting WO-144 probe"
        return rep

    raise hs.Skip(
        "no-video-found",
        f"{platform}: resolved a real agenda/meeting record, no video anywhere ({meeting_url})",
    )


# --------------------------------------------------------------------------
# CivicPlus path (AgendaCenter walk, reused from hub_sweep_wo126)
# --------------------------------------------------------------------------


async def process_civicplus(
    session: aiohttp.ClientSession, cand: Cand, rep: Report, tier3_writer
) -> Report:
    finder = hs.CivicPlusAssetFinder()
    fetcher = hs.Fetcher(session, budget=12)
    seeds = []
    if cand.hub_url and "agendacenter" in cand.hub_url.lower():
        seeds.append(cand.hub_url)
    dom = cand.domain
    if dom:
        base = dom if "://" in dom else f"https://{dom}"
        base = base.rstrip("/")
        seeds.append(f"{base}/AgendaCenter")
        seeds.append(f"{base}/agendacenter")

    root_url = None
    root_html = None
    last_err = None
    for seed in seeds:
        try:
            root_url, root_html = await fetcher.get(seed)
            break
        except hs.FetchError as e:
            last_err = e
            if e.kind == "cloudflare":
                rep.access_mode = "challenge"
                rep.outcome = "skipped"
                rep.reject_reason = "cloudflare-challenge-blocked"
                rep.note = e.detail
                return rep
            continue
    if root_html is None:
        rep.access_mode = "dead"
        rep.outcome = "skipped"
        if last_err and last_err.kind == "dns":
            rep.reject_reason = "dns-unresolvable"
        else:
            rep.reject_reason = "no-platform-link-found"
        rep.note = f"no reachable AgendaCenter page ({last_err.detail if last_err else 'no seed URL'})"
        return rep

    rep.access_mode = "api"
    civicplus_rows, _fragments, note = await hs.civicplus_walk(
        fetcher, root_url, root_html, finder
    )
    rep.candidates_listed = len(civicplus_rows)
    video_rows = [r for r in civicplus_rows if r["url"]]
    if video_rows:
        picked, reason = hs.pick_calendar_candidate(video_rows)
        if not picked and len(video_rows) == 1:
            picked = video_rows[0]
        if picked:
            rep.candidates_tried = 1
            platform = detect_platform(picked["url"])
            try:
                result, meeting_url, high_risk = await hs.resolve_lead(
                    session,
                    hs.Found(
                        picked["url"],
                        platform,
                        picked["found_on"],
                        title=picked["title"],
                        date=picked["date"],
                        agenda_link=picked.get("agenda_link"),
                        packet_link=picked.get("packet_link"),
                        body=picked.get("body") or "",
                        structured=True,
                    ),
                )
                return await act_on_result(
                    session,
                    cand,
                    platform,
                    result,
                    meeting_url,
                    False,
                    rep,
                    tier3_writer,
                )
            except hs.Skip as e:
                return _apply_skip_to_report(rep, e)
            except Exception as e:  # noqa: BLE001
                rep.outcome = "skipped"
                rep.reject_reason = "resolve-failed"
                rep.note = f"{platform}: resolve raised: {e}"
                return rep

    # No video row anywhere -- agenda-only fallback (never ingested).
    agenda_row = hs._pick_agenda_row(civicplus_rows)
    rep.candidates_tried = 1 if agenda_row else 0
    if agenda_row:
        gov = hs.Gov(
            cand.gov_id,
            cand.name,
            cand.state,
            cand.hub_url,
            cand.domain,
            cand.reject_reason,
        )
        meeting = hs._agenda_only_meeting(gov, agenda_row)
        try:
            return await act_on_result(
                session,
                cand,
                "civicplus",
                meeting,
                agenda_row["agenda_link"],
                False,
                rep,
                tier3_writer,
            )
        except hs.Skip as e:
            return _apply_skip_to_report(rep, e)
    rep.outcome = "skipped"
    rep.reject_reason = "no-meetings-found" if not civicplus_rows else "no-video-found"
    rep.note = note
    return rep


# --------------------------------------------------------------------------
# Enumerator (non-civicplus) path
# --------------------------------------------------------------------------


async def process_enumerator_platform(
    session: aiohttp.ClientSession,
    ledger: Ledger,
    cand: Cand,
    netloc: str,
    netloc_source: str,
    rep: Report,
    tier3_writer,
    seeds_f,
) -> Report:
    platform = cand.platform_norm
    ok, detail = await check_tenant_identity(session, netloc, cand)
    if not ok:
        rep.access_mode = "plain"
        rep.outcome = "skipped"
        rep.reject_reason = "wrong-domain-mapping"
        rep.note = f"netloc from {netloc_source}: {detail}"
        return rep

    ledger.upsert_tenant(netloc, platform)
    state_abbr = cand.state.upper() or None
    ledger.set_tenant_gov_id(netloc, cand.gov_id, state_abbr=state_abbr)

    try:
        await enumerate_candidates(
            ledger, platforms=[platform], tenant=netloc, mode="thorough"
        )
    except Exception as e:  # noqa: BLE001
        rep.access_mode = "dead"
        rep.outcome = "error"
        rep.note = f"enumerate raised: {type(e).__name__}: {e}"
        return rep

    listed = ledger.conn.execute(
        "SELECT COUNT(*) c FROM candidates WHERE tenant_netloc = ? AND status = 'new'",
        (netloc,),
    ).fetchone()["c"]
    rep.candidates_listed = listed
    rep.access_mode = "api"
    seeds_f.writerow(
        {
            "netloc": netloc,
            "platform": platform,
            "gov_id": cand.gov_id,
            "access_mode": "api",
        }
    )

    if listed == 0:
        rep.outcome = "skipped"
        rep.reject_reason = "no-meetings-found"
        rep.note = (
            f"netloc from {netloc_source}: {detail}; enumerator listed 0 new candidates"
        )
        return rep

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
        rep.outcome = "error"
        rep.note = f"resolve raised: {type(e).__name__}: {e}"
        return rep

    tried = ledger.conn.execute(
        "SELECT COUNT(*) c FROM candidates WHERE tenant_netloc = ? AND resolve_attempts > 0",
        (netloc,),
    ).fetchone()["c"]
    rep.candidates_tried = tried

    resolved_rows = ledger.conn.execute(
        "SELECT url_normalized, resolved_json FROM candidates "
        "WHERE tenant_netloc = ? AND status = 'resolved_ok' AND resolved_json IS NOT NULL "
        "ORDER BY date DESC",
        (netloc,),
    ).fetchall()

    for row in resolved_rows:
        payload = json.loads(row["resolved_json"])
        result = ResolvedMeeting(**payload)
        if not (result.segments or result.video_url):
            continue  # agenda-only, discovery accepted it but Ryan's rule never ingests it
        meeting_url = row["url_normalized"]
        high_risk = platform in ENUMERATOR_HIGH_RISK_TITLE_PLATFORMS
        try:
            return await act_on_result(
                session,
                cand,
                platform,
                result,
                meeting_url,
                high_risk,
                rep,
                tier3_writer,
            )
        except hs.Skip as e:
            # WO-169: a probe reject here no longer ends the tenant's
            # attempt -- `_apply_skip_to_report()` records the verdict
            # (rejected_by_probe gets its own outcome; see that helper's
            # docstring) and this loop's own `continue` moves on to the
            # next `resolved_rows` candidate, exactly Ryan's "take the
            # next candidate" rule. A later candidate's outcome still
            # overwrites this one if the loop keeps going -- same
            # last-one-wins semantics this loop already had before this
            # WO for a plain Skip.
            rep = _apply_skip_to_report(rep, e)
            continue

    # Nothing with video among the resolved_ok candidates; nothing_to_ingest
    # rejections mean truly empty content.
    rejected = ledger.conn.execute(
        "SELECT status_reason, COUNT(*) c FROM candidates WHERE tenant_netloc = ? "
        "AND status = 'rejected' GROUP BY status_reason",
        (netloc,),
    ).fetchall()
    reasons = {r["status_reason"]: r["c"] for r in rejected}
    rep.outcome = "skipped"
    if not rep.reject_reason:
        rep.reject_reason = "no-video-found" if resolved_rows else "no-video-found"
    if not rep.note:
        rep.note = (
            f"netloc from {netloc_source}; ledger rejections: {reasons}"
            if reasons
            else "no video among resolved candidates"
        )
    return rep


# --------------------------------------------------------------------------
# Plain-HTTP fallback ladder (steps 2/3) for a tenant host that couldn't
# be derived from domain/hub_url/discovery_tenant
# --------------------------------------------------------------------------


async def polite_fetch(
    session: aiohttp.ClientSession, url: str
) -> Tuple[str, Optional[str], Optional[str]]:
    """Returns (access_mode_used, final_url_or_None, html_or_None). Tries
    honest headers first; on a 403 or a dropped connection, retries once
    with browser headers. Never retries after a 404. Records a
    human-verification gate but never solves it."""
    try:
        async with session.get(
            url,
            headers=HONEST_HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
            allow_redirects=True,
        ) as resp:
            text = await resp.text(errors="replace")
            if any(m in text[:4000].lower() for m in CHALLENGE_MARKERS):
                return "challenge", None, None
            if resp.status == 404:
                return "plain", None, None
            if resp.status < 400:
                return "plain", str(resp.url), text
            if resp.status != 403:
                return "plain", None, None
    except Exception:  # noqa: BLE001
        pass  # dropped connection -- fall through to the browser-header retry

    try:
        async with session.get(
            url,
            headers=BROWSER_HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
            allow_redirects=True,
        ) as resp:
            text = await resp.text(errors="replace")
            if any(m in text[:4000].lower() for m in CHALLENGE_MARKERS):
                return "challenge", None, None
            if resp.status < 400:
                return "browser-headers", str(resp.url), text
            return "browser-headers", None, None
    except Exception:  # noqa: BLE001
        return "browser-headers", None, None


async def process_plain_http(
    session: aiohttp.ClientSession,
    ledger: Ledger,
    cand: Cand,
    rep: Report,
    tier3_writer,
    seeds_f,
) -> Report:
    dom = cand.domain
    if not dom:
        rep.access_mode = "dead"
        rep.outcome = "skipped"
        rep.reject_reason = "no-platform-link-found"
        rep.note = "no domain on this row to attempt plain HTTP"
        return rep
    url = dom if "://" in dom else f"https://{dom}"

    mode, final_url, html = await polite_fetch(session, url)
    rep.access_mode = mode
    if html is None:
        rep.outcome = "skipped"
        rep.reject_reason = {
            "challenge": "cloudflare-challenge-blocked",
        }.get(
            mode,
            "blocked-browser-headers"
            if mode == "browser-headers"
            else "blocked-plain-http",
        )
        rep.note = f"{mode}: no page returned from {url}"
        return rep

    links = hs._platform_links(html, final_url)
    match = next((u for u, p in links if p == cand.platform_norm), None)
    if not match and links:
        match = links[0][0]
    if not match:
        rep.outcome = "skipped"
        rep.reject_reason = "no-platform-link-found"
        rep.note = f"{mode}: home page reachable, no known-platform link found"
        return rep

    netloc = netloc_of(match)
    return await process_enumerator_platform(
        session, ledger, cand, netloc, "plain-http-scan", rep, tier3_writer, seeds_f
    )


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


def _pilot_spread(cands: List[Cand], n: int) -> List[Cand]:
    """Spread across platforms roughly proportionally, largest population
    first within each platform -- same idea as hub_sweep_wo126's own
    _pilot_spread."""
    by_platform: Dict[str, List[Cand]] = {}
    for c in cands:
        by_platform.setdefault(c.platform_norm, []).append(c)
    out: List[Cand] = []
    i = 0
    platforms = list(by_platform.keys())
    while len(out) < n and any(by_platform.values()):
        p = platforms[i % len(platforms)]
        if by_platform[p]:
            out.append(by_platform[p].pop(0))
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
        import shutil

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

    report_f, report_w = _report_writer(REPORT_CSV)
    seeds_f, seeds_w = _seeds_writer(DISCOVERY_SEEDS_CSV)
    tier3_f, tier3_w = _tier3_pending_writer(TIER3_PENDING_CSV)

    consecutive_errors = 0
    try:
        async with aiohttp.ClientSession() as session:
            for i, cand in enumerate(todo):
                rep = Report(
                    cand.gov_id,
                    cand.name,
                    cand.state,
                    cand.gov_kind,
                    cand.population,
                    platform=cand.platform_norm,
                )
                try:
                    if cand.gov_id in covered_gov_ids:
                        rep.outcome = "already_covered"
                    elif cand.platform_norm == "civicplus":
                        rep = await process_civicplus(session, cand, rep, tier3_w)
                    elif cand.platform_norm in ENUMERATOR_PLATFORMS:
                        netloc, source = derive_netloc(cand)
                        if netloc:
                            rep.netloc = netloc
                            rep = await process_enumerator_platform(
                                session,
                                ledger,
                                cand,
                                netloc,
                                source,
                                rep,
                                tier3_w,
                                seeds_w,
                            )
                        elif cand.platform_norm in NEEDS_TENANT_DISCOVERY:
                            rep = await process_plain_http(
                                session, ledger, cand, rep, tier3_w, seeds_w
                            )
                        else:
                            rep.outcome = "skipped"
                            rep.reject_reason = "no-platform-link-found"
                            rep.note = "no domain/hub_url/discovery_tenant to derive a tenant host from"
                    else:
                        rep.outcome = "skipped"
                        rep.reject_reason = "unsupported-platform-no-adapter"
                    consecutive_errors = 0
                except Exception as e:  # noqa: BLE001
                    rep.outcome = "error"
                    rep.note = f"unhandled: {type(e).__name__}: {e}"
                    consecutive_errors += 1

                rep.reject_class = _reject_class(rep.reject_reason)
                report_w.writerow(rep.__dict__)
                report_f.flush()
                tier3_f.flush()
                seeds_f.flush()
                ledger.conn.commit()
                print(
                    f"[{i + 1}/{len(todo)}] [{rep.outcome:22}] {rep.gov_id} {rep.name!r} "
                    f"platform={rep.platform!r} access={rep.access_mode!r} -- {rep.reject_reason or rep.note}"
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
        tier3_f.close()
        ledger.close()

    print(f"\nFull report: {REPORT_CSV}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pilot", type=int, default=None, help="spread N rows across platforms"
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--inventory-csv", type=Path, default=DEFAULT_INVENTORY_CSV)
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
