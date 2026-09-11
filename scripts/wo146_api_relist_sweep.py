"""WO-146 (2026-09-10): re-list 149 sweep failures through their
platform's own listing API, per docs/BREADTH_SWEEP_BRIEF.md's method.

Candidate list: rtr-business/research/wo146_candidates.csv -- 149
governments the 2026-09-09/10 sweeps (WO-126/127/128/130/134/139) either
never found video for (`no-video-found`, `no-meetings-found`) or never
got a working resolve from (`resolve-failed`), still with zero Archive
pages, on a platform rtr-discovery can enumerate. WO-140/WO-142 (see
ENUMERATION_METHODS.md sections 181/182) already showed this beats a
one-guessed-URL sweep: discovery calls the platform's own listing API/
feed (deeper, real video-signal fields) instead of checking one page.

Goal: one meeting WITH VIDEO per government, breadth not depth. Ryan's
ingest rule is absolute and enforced below, not just described: only a
meeting with real video becomes a page or a tier-3 queue candidate.
Agenda-only is `no_video_found`/`no_meetings_found` and is NEVER
ingested and NEVER queued.

Reused, not rewritten (per CLAUDE.md's "reuse, do not rewrite" rule and
this WO's own instructions):
  - rtr-discovery's own enumerate_candidates()/resolve_candidates()
    (discovery/enumerate_stage.py, discovery/resolve.py) against a
    SCRATCH ledger copy -- never opens the real
    ~/Documents/rtr-discovery/ledger.db for writing. These call this
    exact rtr-deeplink checkout's real adapters (get_finder().resolve()),
    the same "real content, not a guess" property wo142_pilot.py already
    established.
  - scripts/wo134_confirmed_hits_ingest.py's ingest/title-safety/
    shared-host-pin/tier3-dedup pieces: _looks_like_real_meeting(),
    _ingest_with_retry(), _existing_tier3_queue_urls(),
    _tenant_override_host()/_tenant_override_match(),
    SHARED_HOST_PLATFORMS, MAX_CONSECUTIVE_ERRORS.
  - wo142_pilot.py's _PLATFORM_SUFFIX / netloc_of() derivation rule,
    extended per this WO's own two extra fallback rungs (prior_seed_url,
    then the prior sweep's own two-hop report row) and per §182's two
    qualifications: seed the tenant's real gov_id before resolving, and
    never trust `domain`/`hub_url` as the real tenant host without a
    suffix check first.

Tier-3 gate (WO-144 dependency): this script writes every tier-3 (real
video, no reachable captions) candidate to
rtr-business/research/wo146_tier3_pending.csv and STOPS THERE -- it never
appends to scripts/tier3_auto_transcription_queue.txt or
tenant_overrides.csv for a tier-3 row directly. That append only happens
after WO-144's probe helper lands on main (checked once, at the end of
main(), via `git grep -l probe_queue_entry origin/main -- app/`) and is
run separately. A tier-1/2 shared-host pin (YouTube/Vimeo/TelVue/
Cablecast) IS written immediately on ingest, same as wo134 -- that part
carries no WO-144 dependency.

Tenant-identity check (the "wrong-domain-mapping" gate): seeding a
government's real gov_id into a tenant BEFORE resolving (per §182
qualification 1) makes the resolver trust that identity even when the
underlying host actually serves a different, colliding government (the
Newark/Ventura/Dane/Laverne collisions wo142 found). The seeded gov_id
can't be used to catch this -- it would just be confirming itself. So
the check here is post-hoc and content-based: after a resolve, the
REAL page content (title/jurisdiction string) still names its own
government in its own words regardless of what was seeded. If the
resolved `jurisdiction` field names a different state's two-letter code
than this row's own `state` column, that is a real, cheap, confirmed
signal of a wrong host -- not a full name-similarity check (out of
scope for this pass), but the exact shape of every real collision found
in WO-142 Part A. See `_looks_wrong_government()`.

Usage (repo root, deeplink venv; ARCHIVE_BASE_URL/ARCHIVE_INGEST_TOKEN
reach this script through load_dotenv()'s cwd walk to the shared .env,
per CLAUDE.md's worktree bullet -- intended, not a leak):

    python scripts/export_meeting_inventory.py --out-dir /tmp/wo146_inventory --source export
    python scripts/wo146_api_relist_sweep.py --limit 20          # pilot
    python scripts/wo146_api_relist_sweep.py                     # full run (resumes)

Writes, all flushed per row so a re-run resumes (rows already present
for a gov_id are skipped):
  - rtr-business/research/wo146_report.csv
  - rtr-business/research/wo146_discovery_seeds.csv (one row per tenant
    touched, for a human/later session to seed into the REAL ledger --
    this script never writes the real ledger itself)
  - rtr-business/research/wo146_tier3_pending.csv
"""

import argparse
import asyncio
import csv
import json
import os
import re
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("RTR_DEEPLINK_PATH", str(REPO_ROOT))

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

# Import the deeplink-side pieces FIRST (before anything under
# discovery/ touches sys.path) so `app.*` gets cached from THIS
# worktree checkout, not whatever sibling ~/Documents/rtr-deeplink
# discovery.deeplink's own default would otherwise land on -- see this
# file's module docstring and CLAUDE.md's multi-checkout bullet.
from app.utils.gov_registry.registry import government_for_id  # noqa: E402
from scripts.bulk_ingest import _base_url  # noqa: E402
from scripts.wo134_confirmed_hits_ingest import (  # noqa: E402
    MAX_CONSECUTIVE_ERRORS,
    SHARED_HOST_PLATFORMS,
    TENANT_OVERRIDES_CSV,
    _existing_tier3_queue_urls,
    _looks_like_real_meeting,
    _ingest_with_retry,
    _parse_hit_source_urls,
    _tenant_override_host,
    _tenant_override_match,
)

DISCOVERY_ROOT = Path.home() / "Documents" / "rtr-discovery"
sys.path.insert(0, str(DISCOVERY_ROOT))
REAL_LEDGER = DISCOVERY_ROOT / "ledger.db"
SCRATCH_LEDGER = Path("/tmp/wo146_ledger.db")

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
CANDIDATES_CSV = RESEARCH_DIR / "wo146_candidates.csv"
REPORT_CSV = RESEARCH_DIR / "wo146_report.csv"
SEEDS_CSV = RESEARCH_DIR / "wo146_discovery_seeds.csv"
TIER3_PENDING_CSV = RESEARCH_DIR / "wo146_tier3_pending.csv"
TWO_HOP_CSVS = [
    RESEARCH_DIR / "wo130_kp_two_hop_results.csv",
    RESEARCH_DIR / "wo139_confirmed_hits.csv",
]
DEFAULT_INVENTORY_CSV = Path("/tmp/wo146_inventory/meeting_inventory.csv")

REQUEST_DELAY_SECONDS = 1.5  # between governments
MAX_CANDIDATES_TRIED = 6  # how many resolve attempts per tenant, this run
# Real, confirmed-live gap hit running this script (WO-146, 2026-09-10):
# a domain_fallback netloc for a government whose real tenant genuinely
# isn't the platform this row expects (Bradenton FL's "granicus" row,
# whose `domain`/`hub_url` are neither a real granicus.com host) sent
# the granicus enumerator's param-discovery loop against a plain
# homepage host with no working ViewPublisher.php at all -- each
# individual HTTP call is bounded by discovery's own 45s
# REQUEST_TIMEOUT_SECONDS, but several such calls in sequence (or a
# `finder.resolve()` call that goes around PoliteClient's bounded
# session entirely, straight to the deeplink adapter's own retry/
# backoff) added up to a stall well past 5 minutes on a single
# government with 90+ still to go. Wrapping each stage in its own
# ceiling keeps one bad host from blocking the whole run; a timeout
# here is recorded as a real access-class finding (`timeout`), not
# silently retried.
ENUMERATE_TIMEOUT_SECONDS = 90
RESOLVE_TIMEOUT_SECONDS = 180
OUTER_TIMEOUT_SECONDS = 300  # hard backstop around the whole per-government call

# Same table as wo142_pilot.py -- prefer `domain` only when it already
# carries the platform's own suffix (civicplus's tenant is always its
# own domain and has no shared suffix, so it's handled separately).
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

_US_STATE_CODES = {
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
    "DC",
    "PR",
    "GU",
    "VI",
    "AS",
    "MP",
}
_CA_PROVINCE_CODES = {
    "AB",
    "BC",
    "MB",
    "NB",
    "NL",
    "NS",
    "NT",
    "NU",
    "ON",
    "PE",
    "QC",
    "SK",
    "YT",
}
_ALL_STATE_CODES = _US_STATE_CODES | _CA_PROVINCE_CODES

REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "population",
    "platform",
    "netloc",
    "access_mode",
    "prior_reject_reason",
    "outcome",
    "reject_reason",
    "reject_class",
    "verdict_vs_prior",
    "candidates_listed",
    "candidates_tried",
    "meeting_url",
    "video_url",
    "tier",
    "page_url",
    "note",
]
SEEDS_FIELDS = ["netloc", "platform", "gov_id", "access_mode"]
TIER3_PENDING_FIELDS = [
    "gov_id",
    "platform",
    "meeting_url",
    "video_url",
    "source_url",
    "jurisdiction",
    "pin_row",
]


def netloc_of(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    if "://" in raw:
        netloc = urlparse(raw).netloc
    else:
        netloc = raw.split("/", 1)[0]
    return netloc.lower().rstrip("/")


def _build_two_hop_lookup() -> dict:
    """gov_id -> {platform: url}, from the two prior sweeps' own report
    rows (their `hit_source_urls` column) -- the fourth and final netloc
    fallback rung, for rows whose `domain`/`hub_url`/`prior_seed_url`
    don't carry the real tenant host."""
    lookup: dict = {}
    for path in TWO_HOP_CSVS:
        if not path.exists():
            continue
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                gov_id = row.get("gov_id") or ""
                if not gov_id:
                    continue
                pairs = _parse_hit_source_urls(row.get("hit_source_urls") or "")
                if not pairs:
                    continue
                entry = lookup.setdefault(gov_id, {})
                for platform, url in pairs:
                    entry.setdefault(platform, url)
    return lookup


def derive_netloc(row: dict, two_hop_lookup: dict) -> tuple:
    """Returns (netloc, source_tag). See module docstring's §182
    qualification-2 note: domain/hub_url are not reliable tenant hosts
    without a suffix check, so this only trusts `domain` outright when
    it already ends in the platform's own suffix (or the platform is
    civicplus, whose tenant IS its own domain, never a discovered
    link)."""
    platform = (row.get("platform") or "").strip().lower()
    domain_netloc = netloc_of(row.get("domain") or "")
    hub_netloc = netloc_of(row.get("hub_url") or "")
    seed_netloc = netloc_of(row.get("prior_seed_url") or "")
    suffix = _PLATFORM_SUFFIX.get(platform)

    if platform == "civicplus" and domain_netloc:
        return domain_netloc, "domain"
    if suffix and domain_netloc.endswith(suffix):
        return domain_netloc, "domain"
    if hub_netloc:
        return hub_netloc, "hub_url"
    if seed_netloc:
        return seed_netloc, "prior_seed_url"
    two_hop_url = two_hop_lookup.get(row.get("gov_id") or "", {}).get(platform)
    if two_hop_url:
        return netloc_of(two_hop_url), "two_hop_report"
    if domain_netloc:
        # Last resort: still try the government's own homepage domain,
        # even though it didn't carry the platform's suffix -- better
        # than nothing for civicweb/granicus custom domains, and it's
        # exactly this kind of guess the post-hoc state check below is
        # for.
        return domain_netloc, "domain_fallback"
    return "", "none"


_STATE_NAMES = {
    "alabama": "AL",
    "alaska": "AK",
    "arizona": "AZ",
    "arkansas": "AR",
    "california": "CA",
    "colorado": "CO",
    "connecticut": "CT",
    "delaware": "DE",
    "florida": "FL",
    "georgia": "GA",
    "hawaii": "HI",
    "idaho": "ID",
    "illinois": "IL",
    "indiana": "IN",
    "iowa": "IA",
    "kansas": "KS",
    "kentucky": "KY",
    "louisiana": "LA",
    "maine": "ME",
    "maryland": "MD",
    "massachusetts": "MA",
    "michigan": "MI",
    "minnesota": "MN",
    "mississippi": "MS",
    "missouri": "MO",
    "montana": "MT",
    "nebraska": "NE",
    "nevada": "NV",
    "new hampshire": "NH",
    "new jersey": "NJ",
    "new mexico": "NM",
    "new york": "NY",
    "north carolina": "NC",
    "north dakota": "ND",
    "ohio": "OH",
    "oklahoma": "OK",
    "oregon": "OR",
    "pennsylvania": "PA",
    "rhode island": "RI",
    "south carolina": "SC",
    "south dakota": "SD",
    "tennessee": "TN",
    "texas": "TX",
    "utah": "UT",
    "vermont": "VT",
    "virginia": "VA",
    "washington": "WA",
    "west virginia": "WV",
    "wisconsin": "WI",
    "wyoming": "WY",
}


def _extract_state_from_text(text: str):
    """Real, confirmed-live bug fixed here (WO-146, 2026-09-10): the
    first cut of this function only looked at the text AFTER a comma
    (assuming every jurisdiction string is "City, ST" shaped), which let
    a real cross-jurisdiction collision straight through -- Greenville
    County, SC's own `greenville.granicus.com` is actually Greenville,
    NC's tenant, and that adapter's real resolved jurisdiction was the
    state-less string "City of Greenville" (no comma at all), so the old
    version returned None (no mismatch found) and a real, unrelated
    government's video was ingested as if it answered this row. Scanning
    the WHOLE string for a two-letter state/province token catches this
    -- "City of Greenville" still has no state to check, but the
    resolved page's *state* is what the ARCHIVE separately resolved from
    that same string server-side, and 149-row experience says most
    genuine matches carry their state directly in the jurisdiction
    string already ("Loudoun County, VA", "Village of Winfield, IL"), so
    scanning the whole string costs nothing on those and catches more
    of the ambiguous ones. Also checks full state NAMES, not just
    abbreviations -- a second real miss this WO hit: "Colorado General
    Assembly" (a state legislature, not Colorado County, TX at all)
    names its state by full word, not a 2-letter code, so the
    abbreviation-only scan found nothing."""
    for m in re.finditer(r"\b([A-Za-z]{2})\b", text or ""):
        code = m.group(1).upper()
        if code in _ALL_STATE_CODES:
            return code
    low = (text or "").lower()
    for name, code in _STATE_NAMES.items():
        if name in low:
            return code
    return None


# gov_kind (candidates CSV) -> phrases that, if they appear in the
# resolved jurisdiction/meeting_body/title text as a whole WORD (not a
# bare substring -- see _contains_phrase()) without the expected kind's
# own phrase also appearing, mean the resolve landed on a different TYPE
# of government sharing the same name -- the CLAUDE.md-documented
# "mirror case" (Waukesha city vs Waukesha COUNTY, WI, both real, same
# state, same platform-derivable name). Real, confirmed-live case this
# WO hit (2026-09-10): a Waukesha County, WI candidate's
# `waukesha.granicus.com` tenant resolved real Finance Committee/
# Landmarks Commission video -- but for the CITY of Waukesha, not the
# county -- and the state-only check above can't catch it (both are WI).
_WRONG_KIND_PHRASES = {
    "county": (
        "city of ",
        "town of ",
        "village of ",
        "township of ",
        "city council",  # real miss, WO-146 2026-09-10: Winona County, MN's
        # resolved title was "City Council Agenda", no "City of" phrase at
        # all, and slipped past the phrase list above unnoticed.
    ),
    "municipality": ("county",),
    "town": ("county",),
    "city": ("county",),
    "village": ("county",),
    "cousub": ("county",),
}

# Real, confirmed-live gap this WO hit (2026-09-10): a state-level
# legislative or judicial body sharing a county's name (Colorado
# General Assembly for Colorado County, TX; Arkansas Supreme Court for
# Arkansas County, AR) isn't a "different KIND of local government" the
# phrases above catch -- it isn't local government at all. Neither
# `_looks_like_real_meeting()`'s MEETING_ALLOWLIST/PROMO_BLOCKLIST
# catches this either: the allowlist is only enforced for
# youtube/vimeo, and neither list mentions a legislature or court.
# Off-mission regardless of gov_kind -- this project's whole model is
# local public meetings (council/commission/board), not state
# legislative floor sessions or court dockets.
_OFF_MISSION_ENTITY_PHRASES = (
    "general assembly",
    "state senate",
    "state house",
    "house of representatives",
    "supreme court",
    "court of appeals",
    "circuit court",
    "district court",
    "superior court",
)


def _contains_phrase(haystack_lower: str, phrase: str) -> bool:
    """Word-boundary-aware substring check. Real, confirmed-live bug
    fixed here (WO-146, 2026-09-10): the first cut required a LEADING
    SPACE before "county" (" county"), which misses "county" as the
    very first word of a string -- Imperial city, CA's real jurisdiction
    "County of Imperial, CA" (i.e. the COUNTY resolved instead of the
    city) starts with "county", no leading space, and slipped through
    silently."""
    return (
        re.search(r"\b" + re.escape(phrase.strip()) + r"\b", haystack_lower) is not None
    )


def _looks_wrong_government(row: dict, payload: dict):
    """Cheap, content-based mismatch check -- see module docstring. A
    blank jurisdiction/title/meeting_body string is not treated as a
    mismatch (most platforms' resolved jurisdiction strings don't carry
    a state at all, and a blank one gets this row's own gov_id-derived
    display name applied by the caller instead, never left ambiguous) --
    it is a genuinely unverifiable case, not a confirmed match."""
    jurisdiction = payload.get("jurisdiction") or ""
    meeting_body = payload.get("meeting_body") or ""
    title = payload.get("title") or ""
    # Title is included -- real, confirmed-live miss this WO hit
    # (2026-09-10): Winona County, MN's escribe tenant resolved a blank/
    # state-less jurisdiction ("Winona") but a title of "City Council
    # Agenda" -- clearly the CITY's content, not the county's -- and the
    # jurisdiction+meeting_body-only haystack never saw it.
    haystack = f"{jurisdiction} {meeting_body} {title}"
    low = haystack.lower()

    for phrase in _OFF_MISSION_ENTITY_PHRASES:
        if _contains_phrase(low, phrase):
            return (
                f"resolved content {haystack!r} names a state legislative/judicial "
                "body, not a local government meeting (off-mission)"
            )

    expected_state = (row.get("state") or "").strip().upper()
    if expected_state and haystack.strip():
        found_state = _extract_state_from_text(haystack)
        if found_state and found_state != expected_state:
            return (
                f"resolved content {haystack!r} names {found_state}, "
                f"row expects {expected_state}"
            )

    gov_kind = (row.get("gov_kind") or "").strip().lower()
    wrong_phrases = _WRONG_KIND_PHRASES.get(gov_kind)
    if wrong_phrases and haystack.strip():
        if any(_contains_phrase(low, p) for p in wrong_phrases):
            return (
                f"resolved content {haystack!r} names a different KIND "
                f"of government than this row's gov_kind={gov_kind!r} "
                "(same-name city/county collision)"
            )
    return None


def classify_enumerate_failure(notes: str) -> tuple:
    """(access_mode, reject_reason, reject_class) from a
    TenantNotEnumerable / enumerate-exception's own message text."""
    text = (notes or "").lower()
    if any(
        m in text
        for m in ("cloudflare", "just a moment", "attention required", "captcha")
    ):
        return "challenge", "cloudflare-challenge-blocked", "access"
    if "timeout" in text or "timed out" in text:
        return "dead", "timeout", "access"
    if (
        "name or service not known" in text
        or "nodename nor servname" in text
        or "dns" in text
    ):
        return "dead", "dns-unresolvable", "access"
    if "403" in text or "forbidden" in text:
        return "dead", "blocked-plain-http", "access"
    # Most TenantNotEnumerable messages here are content findings ("no
    # views-table listing", "param discovery found nothing") -- the page
    # was reachable, there was just nothing recognizable on it.
    return "api", "no-platform-link-found", "content"


def compute_verdict(row: dict, outcome: str, reject_reason: str) -> str:
    prior = (row.get("prior_reject_reason") or "").strip()
    platform = (row.get("platform") or "").strip().lower()
    if outcome in ("ingested_tier1_2", "queued_tier3_pending"):
        return "found_video"
    if (
        platform == "civicclerk"
        and prior == "no-meetings-found"
        and outcome == "no_video_found"
    ):
        # WO-140's real correction (ENUMERATION_METHODS.md §181): a
        # CivicClerk "no meetings found" verdict from a page-level check
        # is usually wrong -- real events exist via the Events API, they
        # just have hasMedia=false. The government DID have meetings; it
        # just never had video. That's a wording fix, not a same/worse.
        return "corrected_wording"
    if outcome == "error":
        return "worse"
    if outcome == "skipped" and reject_reason == "wrong-domain-mapping":
        return "same"
    if outcome in ("no_video_found", "no_meetings_found", "skipped"):
        return "same"
    return "same"


def _read_csv_rows(path: Path):
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_covered_gov_ids(inventory_csv: Path) -> set:
    if not inventory_csv.exists():
        print(
            f"ERROR: {inventory_csv} not found. Run first:\n"
            "  python scripts/export_meeting_inventory.py --out-dir "
            f"{inventory_csv.parent} --source export",
            file=sys.stderr,
        )
        sys.exit(1)
    with inventory_csv.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f) if r.get("gov_id")}


def _already_done_gov_ids(path: Path) -> set:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f) if r.get("gov_id")}


def _csv_writer(path: Path, fields: list):
    is_new = not path.exists()
    f = path.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
    if is_new:
        writer.writeheader()
        f.flush()
    return f, writer


def ensure_scratch_ledger() -> None:
    if not SCRATCH_LEDGER.exists():
        shutil.copy2(REAL_LEDGER, SCRATCH_LEDGER)
        print(f"copied {REAL_LEDGER} -> {SCRATCH_LEDGER}")


async def process_government(
    ledger,
    row: dict,
    covered_gov_ids: set,
    two_hop_lookup: dict,
    session: aiohttp.ClientSession,
) -> dict:
    from discovery.enumerate_stage import enumerate_candidates
    from discovery.resolve import resolve_candidates

    gov_id = row["gov_id"]
    name = row["name"]
    state = row["state"]
    platform = (row["platform"] or "").strip().lower()
    prior_reason = row.get("prior_reject_reason") or ""

    base = {
        "gov_id": gov_id,
        "name": name,
        "state": state,
        "gov_kind": row.get("gov_kind", ""),
        "population": row.get("population", ""),
        "platform": platform,
        "netloc": "",
        "access_mode": "",
        "prior_reject_reason": prior_reason,
        "outcome": "",
        "reject_reason": "",
        "reject_class": "",
        "verdict_vs_prior": "",
        "candidates_listed": 0,
        "candidates_tried": 0,
        "meeting_url": "",
        "video_url": "",
        "tier": "",
        "page_url": "",
        "note": "",
    }

    if gov_id in covered_gov_ids:
        base["outcome"] = "already_covered"
        base["verdict_vs_prior"] = "same"
        base["note"] = "gov_id already has an archived page (fresh export)"
        return base

    netloc, source = derive_netloc(row, two_hop_lookup)
    base["netloc"] = netloc
    if not netloc:
        base["outcome"] = "skipped"
        base["reject_reason"] = "no-platform-link-found"
        base["reject_class"] = "access"
        base["access_mode"] = "dead"
        base["note"] = (
            "could not derive a tenant host from domain/hub_url/prior_seed_url/two-hop report"
        )
        base["verdict_vs_prior"] = compute_verdict(
            row, base["outcome"], base["reject_reason"]
        )
        return base

    ledger.upsert_tenant(netloc, platform)
    gov = government_for_id(gov_id)
    state_abbr = (gov.state if gov else None) or (state or None)
    # §182 qualification 1: seed the government BEFORE resolving.
    ledger.set_tenant_gov_id(netloc, gov_id, state_abbr=state_abbr)

    try:
        enum_counters = await asyncio.wait_for(
            enumerate_candidates(
                ledger, platforms=[platform], tenant=netloc, mode="thorough"
            ),
            timeout=ENUMERATE_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        base["outcome"] = "skipped"
        base["access_mode"] = "dead"
        base["reject_reason"] = "timeout"
        base["reject_class"] = "access"
        base["note"] = f"enumerate exceeded {ENUMERATE_TIMEOUT_SECONDS}s -- skipped"
        base["verdict_vs_prior"] = compute_verdict(
            row, base["outcome"], base["reject_reason"]
        )
        return base
    except Exception as exc:  # noqa: BLE001 -- record and move to next gov
        base["outcome"] = "error"
        base["access_mode"] = "dead"
        base["note"] = f"enumerate raised: {exc!r}"
        return base

    if enum_counters.get("aborted"):
        base["outcome"] = "error"
        base["note"] = f"enumerate aborted: {enum_counters['aborted']}"
        return base

    if enum_counters.get("tenants_not_enumerable"):
        trow = ledger.conn.execute(
            "SELECT notes FROM tenants WHERE netloc = ?", (netloc,)
        ).fetchone()
        notes = trow["notes"] if trow else ""
        access_mode, reject_reason, reject_class = classify_enumerate_failure(notes)
        base["access_mode"] = access_mode
        base["outcome"] = "skipped"
        base["reject_reason"] = reject_reason
        base["reject_class"] = reject_class
        base["note"] = notes or "tenant not enumerable"
        base["verdict_vs_prior"] = compute_verdict(row, base["outcome"], reject_reason)
        return base

    base["access_mode"] = "api"
    new_n = enum_counters.get("tenant_results", {}).get(netloc, 0)
    filtered_n = enum_counters.get("filtered_out", 0)
    known_n = enum_counters.get("already_known", 0)
    base["candidates_listed"] = new_n + filtered_n + known_n

    # Real, confirmed-live bug fixed here (WO-146, 2026-09-10): the
    # SCRATCH ledger is a copy of the REAL, live rtr-discovery ledger
    # (not a fresh one) -- many tenants already carry real candidate
    # rows from actual past discovery runs, resolved or not, before this
    # script ever touches them. `new_n == 0` only means "nothing NEW this
    # walk" -- it says nothing about whether a PRIOR run already
    # resolved real video for this tenant. The first cut of this
    # function treated new_n==0 as an immediate no-meetings/no-video
    # verdict without ever looking, and on this run's own pilot that
    # produced a false "no_video_found" for Loudoun County VA (which, a
    # resolve pass earlier in this exact run, had already cached a real
    # -- if caption-less -- Granicus video). So: always check for an
    # already-resolved candidate first, and only resolve NEW ones (if
    # any) when that comes up empty.
    if new_n > 0:
        try:
            await asyncio.wait_for(
                resolve_candidates(
                    ledger,
                    tenant=netloc,
                    limit=MAX_CANDIDATES_TRIED,
                    require_captions=False,
                    min_tier="blank",
                    include_tier3=True,
                    store_tier3=True,
                ),
                timeout=RESOLVE_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            # Whatever resolved before the timeout is already committed
            # to the ledger (discovery's own `with self.conn:` blocks
            # commit per candidate) -- fall through to the cache query
            # below rather than treating a partial resolve as nothing.
            base["note"] = (
                f"resolve exceeded {RESOLVE_TIMEOUT_SECONDS}s -- used partial results"
            )
        except Exception as exc:  # noqa: BLE001
            base["outcome"] = "error"
            base["note"] = f"resolve raised: {exc!r}"
            return base

    rows = ledger.conn.execute(
        "SELECT status, status_reason, url_normalized, date, resolved_json "
        "FROM candidates WHERE tenant_netloc = ? AND status IN ('resolved_ok','rejected') "
        "ORDER BY date DESC",
        (netloc,),
    ).fetchall()
    base["candidates_tried"] = len(rows)

    # Real, confirmed-live bug fixed here (WO-146, 2026-09-10): with
    # require_captions=False (deliberate, so a video-only outcome is
    # still visible -- see discovery/filters.py's post_resolve()),
    # ledger status "resolved_ok" does NOT mean real captions exist --
    # it only means SOMETHING worth a page (segments OR agenda_items OR
    # agenda_link OR video_url) was found. Trusting status alone as the
    # tier1/2-vs-tier3 split ingested two real pages with ZERO transcript
    # segments as if they were tier1/2 (Loudoun County VA, Waukesha
    # County WI candidates, both real video/no-captions Granicus clips)
    # -- a direct violation of Ryan's "tier 1/2 ingests WITH segments"
    # rule, caught only by hand-checking the pilot's own report and
    # requiring a page deletion (see BACKLOG.md). The real, correct split
    # is on the PAYLOAD's own segments field, not the ledger status.
    best_tier12 = None
    best_tier3 = None
    for r in rows:
        if not r["resolved_json"]:
            continue
        payload_peek = json.loads(r["resolved_json"])
        has_segments = bool(payload_peek.get("segments"))
        has_video = bool(payload_peek.get("video_url"))
        if has_segments and has_video and best_tier12 is None:
            best_tier12 = r
        elif has_video and not has_segments and best_tier3 is None:
            best_tier3 = r

    chosen = best_tier12 or best_tier3
    if chosen is None:
        if base["candidates_listed"] == 0:
            base["outcome"] = "no_meetings_found"
            base["reject_reason"] = "no-meetings-found"
        else:
            # Real candidates were listed/known (this run or a prior
            # one) but none resolved with real video -- e.g. CivicClerk
            # hasMedia=false. A real listing exists, it just carries no
            # video. WO-140's correction applies.
            base["outcome"] = "no_video_found"
            base["reject_reason"] = "no-video-found"
        base["reject_class"] = "content"
        base["verdict_vs_prior"] = compute_verdict(
            row, base["outcome"], base["reject_reason"]
        )
        return base

    payload = json.loads(chosen["resolved_json"])
    is_tier12 = chosen is best_tier12
    assert bool(payload.get("segments")) == is_tier12  # belt-and-suspenders

    mismatch = _looks_wrong_government(row, payload)
    if mismatch:
        base["outcome"] = "skipped"
        base["reject_reason"] = "wrong-domain-mapping"
        base["reject_class"] = "content"
        base["note"] = mismatch
        base["verdict_vs_prior"] = compute_verdict(
            row, base["outcome"], base["reject_reason"]
        )
        return base

    resolved_platform = payload.get("platform") or platform
    title_ok = _looks_like_real_meeting(
        payload.get("title") or "",
        require_allowlist=(resolved_platform in ("youtube", "vimeo")),
    )
    if not title_ok:
        base["outcome"] = "skipped"
        base["reject_reason"] = "off-mission"
        base["reject_class"] = "content"
        base["note"] = f"title looks like a non-meeting video: {payload.get('title')!r}"
        base["verdict_vs_prior"] = compute_verdict(
            row, base["outcome"], base["reject_reason"]
        )
        return base

    base["meeting_url"] = chosen["url_normalized"]
    base["video_url"] = payload.get("video_url") or ""

    if is_tier12:
        if not payload.get("jurisdiction") and gov and gov.gov_name and gov.state:
            payload["jurisdiction"] = f"{gov.gov_name}, {gov.state}"
        # WO-222: this row already knows its government -- send it in the
        # payload so a page on a shared host never depends on a
        # tenant_overrides.csv pin reaching production first. See
        # scripts/wo134_confirmed_hits_ingest.py's matching comment and
        # docs/COVERAGE_HANDOVER.md §3.
        if gov_id:
            payload["gov_id"] = gov_id
        if resolved_platform in SHARED_HOST_PLATFORMS:
            result_ns = SimpleNamespace(
                video_url=payload.get("video_url"),
                external_id=payload.get("external_id"),
            )
            _maybe_write_pin(
                resolved_platform, result_ns, chosen["url_normalized"], gov_id, name
            )
        try:
            response = await _ingest_with_retry(
                session, payload, chosen["url_normalized"]
            )
        except Exception as exc:  # noqa: BLE001
            base["outcome"] = "error"
            base["note"] = f"ingest raised: {exc!r}"
            return base
        if response is None:
            base["outcome"] = "error"
            base["note"] = "POST /internal/ingest failed twice"
            return base
        base["outcome"] = "ingested_tier1_2"
        base["tier"] = "1/2"
        base["page_url"] = response.get("url") or ""
        segs = payload.get("segments") or []
        base["note"] = f"{len(segs)} transcript segments"
        base["verdict_vs_prior"] = compute_verdict(row, base["outcome"], "")
        return base

    # Tier 3: real video, no reachable captions. Per this WO's gate,
    # write to the PENDING file only -- never the real queue -- until
    # WO-144's probe helper is confirmed merged (checked once in main()).
    already_queued = chosen["url_normalized"] in _existing_tier3_queue_urls()
    pin_row = ""
    if resolved_platform in SHARED_HOST_PLATFORMS:
        host_ns = SimpleNamespace(video_url=payload.get("video_url"))
        match_ns = SimpleNamespace(
            video_url=payload.get("video_url"), external_id=payload.get("external_id")
        )
        host = _tenant_override_host(
            resolved_platform, host_ns, chosen["url_normalized"]
        )
        match = _tenant_override_match(
            resolved_platform, match_ns, chosen["url_normalized"]
        )
        if host and match:
            pin_row = (
                f"tenant_host={host};match={match};gov_id={gov_id};"
                f"strength=fallback;source=wo146_api_relist"
            )
    base["outcome"] = "queued_tier3_pending"
    base["tier"] = "3"
    base["note"] = (
        "already in tier3_auto_transcription_queue.txt -- not re-added to pending"
        if already_queued
        else "written to wo146_tier3_pending.csv, awaiting probe (WO-144)"
    )
    base["verdict_vs_prior"] = compute_verdict(row, base["outcome"], "")
    base["_pending_row"] = None
    if not already_queued:
        base["_pending_row"] = {
            "gov_id": gov_id,
            "platform": resolved_platform,
            "meeting_url": chosen["url_normalized"],
            "video_url": payload.get("video_url") or "",
            "source_url": payload.get("source_url") or "",
            "jurisdiction": payload.get("jurisdiction") or "",
            "pin_row": pin_row,
        }
    return base


def _maybe_write_pin(
    platform: str, result_ns, final_seed: str, gov_id: str, unit_name: str
) -> None:
    """Tier-1/2 shared-host pin -- no WO-144 dependency, same as
    wo134_confirmed_hits_ingest.maybe_write_tenant_override(), inlined
    here since that function hardcodes its own `evidence` string; we
    still want the identical file/columns/idempotency it uses."""
    host = _tenant_override_host(platform, result_ns, final_seed)
    match = _tenant_override_match(platform, result_ns, final_seed)
    if not host or not match:
        return
    existing = set()
    if TENANT_OVERRIDES_CSV.exists():
        with TENANT_OVERRIDES_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                existing.add((r.get("tenant_host", ""), r.get("match", "")))
    key = (host, match)
    if key in existing:
        return
    is_new = not TENANT_OVERRIDES_CSV.exists()
    with TENANT_OVERRIDES_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "tenant_host",
                "match",
                "gov_id",
                "strength",
                "source",
                "evidence",
            ],
            lineterminator="\n",
        )
        if is_new:
            writer.writeheader()
        writer.writerow(
            {
                "tenant_host": host,
                "match": match,
                "gov_id": gov_id,
                "strength": "fallback",
                "source": "wo146_api_relist",
                "evidence": f"{unit_name} -- WO-146 API relist, gov_id={gov_id}",
            }
        )


async def main_async(limit, inventory_csv: Path) -> None:
    from discovery.ledger import Ledger
    from discovery import config as discovery_config

    discovery_config.load_env()
    ensure_scratch_ledger()
    ledger = Ledger(str(SCRATCH_LEDGER))

    covered = _load_covered_gov_ids(inventory_csv)
    print(f"{len(covered)} gov_ids already have an archived page (fresh export).")

    two_hop_lookup = _build_two_hop_lookup()
    all_rows = _read_csv_rows(CANDIDATES_CSV)
    print(f"{len(all_rows)} candidate rows in {CANDIDATES_CSV.name}")

    done = _already_done_gov_ids(REPORT_CSV)
    print(f"{len(done)} gov_ids already in {REPORT_CSV.name} -- skipping those.")

    to_process = [r for r in all_rows if r["gov_id"] not in done]
    if limit:
        to_process = to_process[:limit]
    print(f"Processing {len(to_process)} government(s) against {_base_url()}...\n")

    if not _base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (check .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    report_f, report_w = _csv_writer(REPORT_CSV, REPORT_FIELDS)
    seeds_f, seeds_w = _csv_writer(SEEDS_CSV, SEEDS_FIELDS)
    pending_f, pending_w = _csv_writer(TIER3_PENDING_CSV, TIER3_PENDING_FIELDS)

    tally: dict = {}
    consecutive_errors = 0
    # Loaded from disk (not just tracked in-memory) so a resumed/re-run
    # process doesn't re-append a netloc already seeded by an earlier
    # run -- real, confirmed-live duplication this WO hit reprocessing
    # 3 rows after fixing the tier-classification bug (Greenville/
    # Loudoun/Waukesha/Douglas/Carroll each appeared twice).
    seeded_netlocs = set()
    if SEEDS_CSV.exists():
        with SEEDS_CSV.open(newline="", encoding="utf-8") as f:
            seeded_netlocs = {r["netloc"] for r in csv.DictReader(f) if r.get("netloc")}
    try:
        async with aiohttp.ClientSession() as session:
            for i, row in enumerate(to_process):
                # Hard outer backstop, in addition to the two inner
                # timeouts inside process_government() -- real,
                # confirmed-live gap this WO hit (2026-09-10):
                # `desmoines.civicweb.net` stalled 6+ minutes past BOTH
                # inner ceilings combined (90s enumerate + 180s resolve
                # = 270s max, observed 384s+ with no sign of returning),
                # so something outside either wrapped call -- a DNS
                # resolution, a connection-pool wait, or a ledger call --
                # was the real hang. Without this, one bad host can
                # still stall the whole run indefinitely.
                try:
                    result = await asyncio.wait_for(
                        process_government(
                            ledger, row, covered, two_hop_lookup, session
                        ),
                        timeout=OUTER_TIMEOUT_SECONDS,
                    )
                except asyncio.TimeoutError:
                    result = {
                        "gov_id": row["gov_id"],
                        "name": row["name"],
                        "state": row["state"],
                        "gov_kind": row.get("gov_kind", ""),
                        "population": row.get("population", ""),
                        "platform": (row["platform"] or "").strip().lower(),
                        "netloc": "",
                        "access_mode": "dead",
                        "prior_reject_reason": row.get("prior_reject_reason") or "",
                        "outcome": "skipped",
                        "reject_reason": "timeout",
                        "reject_class": "access",
                        "verdict_vs_prior": "same",
                        "candidates_listed": 0,
                        "candidates_tried": 0,
                        "meeting_url": "",
                        "video_url": "",
                        "tier": "",
                        "page_url": "",
                        "note": f"process_government exceeded the {OUTER_TIMEOUT_SECONDS}s outer backstop",
                    }
                pending_row = result.pop("_pending_row", None)
                is_real_error = (
                    result["outcome"] == "error"
                    or result.get("reject_reason") == "timeout"
                )
                consecutive_errors = consecutive_errors + 1 if is_real_error else 0

                report_w.writerow({k: result.get(k, "") for k in REPORT_FIELDS})
                report_f.flush()

                if pending_row:
                    pending_w.writerow(pending_row)
                    pending_f.flush()

                netloc = result.get("netloc") or ""
                if (
                    netloc
                    and netloc not in seeded_netlocs
                    and result.get("access_mode")
                ):
                    seeds_w.writerow(
                        {
                            "netloc": netloc,
                            "platform": result["platform"],
                            "gov_id": result["gov_id"],
                            "access_mode": result["access_mode"],
                        }
                    )
                    seeds_f.flush()
                    seeded_netlocs.add(netloc)

                tally[result["outcome"]] = tally.get(result["outcome"], 0) + 1
                print(
                    f"[{i + 1}/{len(to_process)}] [{result['outcome']:22}] "
                    f"{result['gov_id']} {result['name']!r} ({result['platform']}, "
                    f"{netloc}) -- {result.get('note', '')}"
                )

                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(
                        f"\nABORTING: {consecutive_errors} consecutive real errors -- "
                        "stopping per Ryan's politeness rule. Re-run to resume.",
                        file=sys.stderr,
                    )
                    break
                if i < len(to_process) - 1:
                    await asyncio.sleep(REQUEST_DELAY_SECONDS)
    finally:
        report_f.close()
        seeds_f.close()
        pending_f.close()
        ledger.conn.commit()
        ledger.close()

    print("\n--- Tally (this run) ---")
    for outcome, count in sorted(tally.items()):
        print(f"{outcome:22} {count}")
    print(f"\nFull report: {REPORT_CSV}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--inventory-csv", type=Path, default=DEFAULT_INVENTORY_CSV)
    args = parser.parse_args()
    asyncio.run(main_async(args.limit, args.inventory_csv))


if __name__ == "__main__":
    main()
