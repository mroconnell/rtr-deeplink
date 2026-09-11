"""WO-152 (2026-09-10): recheck of 1,814 governments whose domain "looked
dead" to an earlier client -- rtr-business/research/wo152_candidates.csv
(candidate list 4 in docs/BREADTH_SWEEP_BRIEF.md: "the 1,183 smaller
governments the headless pass has not reached", widened here to "no
Archive page, no domain resolve" per Ryan's own list). Breadth, not depth,
and cheap: one or two requests per host, no headless browser.

This is a thin wrapper, not a new ladder. Every access-ladder mechanic
(domain-variant retry, honest-then-browser headers, challenge detection,
platform-link scanning, rtr-discovery enumeration against a scratch
ledger, up-to-6-candidates resolve/ingest via wo134's process_row) is
`scripts/wo147_access_ladder_sweep.py`'s own code, imported and reused
here with three changes:

1. **No headless rung.** `wo147.fetch_headless` is monkey-patched to a
   stub that always declines, so `run_access_ladder()`'s existing
   "headless recovers a page with no visible link" branch never actually
   launches Playwright -- WO-141 found headless never answers a host
   first, and this WO is deliberately the cheapest pass (CLAUDE.md's
   "smallest change" note on the --no-headless ask; a stub achieves the
   same effect as a flag without touching wo147's own control flow).
2. **A different candidate CSV shape** (gov_id, name, state, country,
   gov_kind, population, domain, known_platform, prior_reason,
   research_calendar_url, research_meeting_url -- no hub_url/prior_source
   columns wo147's candidates carry, and two the row's own prior session
   already found: `research_calendar_url` (a known meetings page --
   tried first, home page on a miss) and `research_meeting_url` (a
   specific meeting URL, tried as a hit outright when
   `detect_platform()` recognizes it, ahead of the ladder).
3. **WO-145's four wrong-government checks**, ported (not re-imported --
   `wo145_api_first_sweep.py` pulls in `discovery`/`hub_sweep_wo126` at
   module scope for a different pipeline shape; these four checks are
   pure functions over plain strings, copied verbatim below with
   attribution) and wired into wo134's new `IDENTITY_CHECK_HOOK` (added
   for this WO -- see that module's own comment), so a same-name/wrong-
   state, wrong-kind, wrong-place-in-title, or bare-name Canadian
   collision is caught and skipped (`wrong-domain-mapping`) before
   anything is ingested, the same way WO-145 caught 6 already-live wrong
   pages and this WO's own candidate list (82 Canadian rows share this
   file with 1,732 US rows) makes the fourth check's risk real, not
   theoretical.

Report schema per the work order (superset of wo147's own report:
variant_tried/corrected_domain/start_url/hit_url added, prior_source
dropped -- this candidate list has none).

Usage (repo root, discovery's own venv -- same requirement as wo147):
    python scripts/export_meeting_inventory.py --out-dir /tmp/wo152_inventory --source export
    ~/Documents/rtr-discovery/.venv/bin/python scripts/wo152_dead_domain_recheck.py --limit 40
    ~/Documents/rtr-discovery/.venv/bin/python scripts/wo152_dead_domain_recheck.py   # full run, resumable
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("RTR_DEEPLINK_PATH", str(REPO_ROOT))

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import detect_platform  # noqa: E402

import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402
import scripts.wo147_access_ladder_sweep as wo147  # noqa: E402

RESEARCH_DIR = Path("/Users/mroconnell/Documents/rtr-business/research")
CANDIDATES_CSV = RESEARCH_DIR / "wo152_candidates.csv"
REPORT_CSV = RESEARCH_DIR / "wo152_report.csv"
DISCOVERY_SEEDS_CSV = RESEARCH_DIR / "wo152_discovery_seeds.csv"
HOST_ACCESS_MODES_CSV = RESEARCH_DIR / "wo152_host_access_modes.csv"
TIER3_PENDING_CSV = RESEARCH_DIR / "wo152_tier3_pending.csv"
DEFAULT_INVENTORY_CSV = Path("/tmp/wo152_inventory/meeting_inventory.csv")
CONSOLIDATED_GOV_CSV = (
    REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "consolidated_governments.csv"
)

# Point wo147's own writers/ledger at THIS WO's files -- every function
# below this line refers to these names as module globals of wo147, so
# reassigning them here is enough; see wo147_access_ladder_sweep.py's own
# write_discovery_seed/write_host_access_mode/tier3_pending_handler and
# ensure_discovery() for how each one is actually used.
wo147.DISCOVERY_SEEDS_CSV = DISCOVERY_SEEDS_CSV
wo147.HOST_ACCESS_MODES_CSV = HOST_ACCESS_MODES_CSV
wo147.TIER3_PENDING_CSV = TIER3_PENDING_CSV
wo147.SCRATCH_LEDGER = Path("/tmp/wo152_ledger.db")
wo147._discovery_seeds_written = None
wo147._host_access_modes_written = None
wo147._tier3_pending_seen = None
# wo147's own import already did `wo134.TIER3_HANDLER =
# wo147.tier3_pending_handler` at module load -- unchanged here, it now
# just writes to the repointed TIER3_PENDING_CSV above.


def _no_headless(url: str):
    """WO-152 carries no headless rung (see this module's docstring,
    point 1) -- always declines, so run_access_ladder()'s existing
    headless branch falls through to its own no-hit return path."""
    return None, url, "headless disabled for WO-152 (plain/browser-headers only)"


async def _no_headless_async(url: str):
    return _no_headless(url)


wo147.fetch_headless = _no_headless_async


# --- WO-145's four wrong-government checks, ported verbatim in logic from
# scripts/wo145_api_first_sweep.py (not imported -- that module pulls in
# discovery/hub_sweep_wo126 at import time for a different pipeline shape;
# these four are pure string checks, copied with the row's plain fields
# (name/state/country/gov_kind) instead of wo145's own `Cand` object). See
# that file's docstrings for the real, confirmed-live incidents each one
# fixes (Flemington NJ/Hunterdon County, Crystal River FL/Citrus County,
# Cornwall PA/Cornwall ON, hometown.cablecast.tv's vendor demo content). --


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


def _load_canadian_csd_names() -> set:
    names = set()
    with (REPO_ROOT / "app/utils/jurisdiction_data/ca_csd.csv").open(
        newline="", encoding="utf-8"
    ) as f:
        for r in csv.DictReader(f):
            names.add((r.get("name") or "").strip().lower())
    return names


CANADIAN_CSD_NAMES = _load_canadian_csd_names()
CROSS_BORDER_RISK_PLATFORMS = {"escribe", "civicweb"}

_LEADING_PLACE_STATE_RE = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9\s.'\-]*?),\s*([A-Za-z]{2})\b"
)


def _state_or_kind_conflict(
    name: str, state: str, gov_kind: str, text: str, source: str
) -> Optional[str]:
    text = (text or "").strip()
    if not text:
        return None
    text_lower = text.lower()
    row_state = (state or "").strip().upper()
    row_state_name = STATE_NAMES.get(row_state, "")

    m = _LEADING_PLACE_STATE_RE.match(text)
    if m and m.group(2).upper() in STATE_NAMES:
        place_part, state_part = m.group(1), m.group(2).upper()
        if state_part != row_state:
            return (
                f"{source} {text!r} names state {state_part!r} "
                f"({STATE_NAMES.get(state_part, state_part)}), row expects "
                f"{row_state_name!r} ({name})"
            )
        place_tokens = _name_tokens(place_part)
        row_tokens = _name_tokens(name)
        if place_tokens and row_tokens and not (place_tokens & row_tokens):
            return (
                f"{source} {text!r} names a specific place ({place_part!r}) "
                f"with no name overlap with the row ({name})"
            )

    for abbr, fullname in STATE_NAMES.items():
        if abbr == row_state or not fullname:
            continue
        if fullname.lower() in text_lower:
            return f"{source} {text!r} names {fullname!r}, row expects {row_state_name!r} ({name})"
    if gov_kind == "municipality" and "county" not in (name or "").lower():
        if re.search(r"\bcounty\b", text_lower):
            return (
                f"{source} {text!r} mentions 'County', row is a municipality ({name})"
            )
    return None


def _cross_border_collision(name: str, country: str, text: str) -> Optional[str]:
    if (country or "us") != "us":
        return None
    if _LEADING_PLACE_STATE_RE.search(text or ""):
        return None
    row_base = _name_tokens(name)
    if not row_base:
        return None
    if row_base <= {
        n for csd_name in CANADIAN_CSD_NAMES for n in _name_tokens(csd_name)
    }:
        for csd_name in CANADIAN_CSD_NAMES:
            if _name_tokens(csd_name) == row_base:
                return (
                    f"a real Canadian municipality named {csd_name!r} exists "
                    f"(ca_csd.csv) and the resolved text {text!r} carries no "
                    f"state/province code to rule it out -- refusing to trust "
                    f"a bare name match ({name})"
                )
    return None


_TITLE_PLACE_RE = re.compile(
    r"\b([A-Z][A-Za-z.'-]*(?:\s+[A-Z][A-Za-z.'-]*){0,3})\s+"
    r"(school board|select ?board|city council|town council|village board|"
    r"town board|board of (?:trustees|selectmen|aldermen)|planning board)\b",
    re.IGNORECASE,
)


_STATE_FULLNAMES_LOWER = {v.lower() for v in STATE_NAMES.values() if v}

# A second real, confirmed-live false positive, same full sweep: Highland
# town, NY's own real `@HighlandTownNY`-shaped video, titled "Regular Town
# Board Meeting - August 2026", matched `place="Regular"` -- a meeting-
# type qualifier, not a place name, that happens to satisfy the regex's
# bare "[A-Z]<word>" capture immediately before "Town Board". None of
# these words is ever itself a place name in this project's own tables;
# skip a single-word match entirely composed of one.
_MEETING_QUALIFIER_WORDS = {
    "regular",
    "special",
    "annual",
    "emergency",
    "adjourned",
    "continued",
    "joint",
    "called",
    "work",
    "workshop",
    "budget",
    "organizational",
    "reorganizational",
    "reorganization",
    "public",
    "final",
    "monthly",
}


def _title_place_conflict(name: str, title: str) -> Optional[str]:
    """Real, confirmed-live false positives caught running this WO's own
    full sweep, both from `_TITLE_PLACE_RE`'s bare "capitalized word(s)
    immediately before an institution phrase" capture treating a non-place
    word as a place:
    1. Swisher city, IA -- a real, correctly-matched `@SwisherCommunications`
       YouTube video titled "Swisher, Iowa City Council and Parks and Rec
       Joint Meeting": when a "<City>, <State> City Council" title's place
       happens to be a real city whose own name starts with the state's
       name ("Iowa City" is a real, different Iowa city), the greedy match
       backtracks to capture just the bare state name ("Iowa") once "Iowa
       City" + the next word fails to immediately continue into a literal
       "city council" -- the identical shape any "<StateName> City"-named
       place creates (Kansas City, Oklahoma City, Jersey City, Carson
       City...). A bare state/province full name is not itself evidence of
       a different place -- it is exactly what a correct title contains.
    2. Highland town, NY -- a real video titled "Regular Town Board Meeting
       - August 2026" matched `place="Regular"`, a meeting-type qualifier
       word, not a place name at all.
    Both are "absence of confirmation isn't proof" cases, same rule the
    rest of this module already applies -- skip rather than treat as a
    conflict."""
    if not title:
        return None
    for m in _TITLE_PLACE_RE.finditer(title):
        place = m.group(1)
        place_lower = place.strip().lower()
        if place_lower in _STATE_FULLNAMES_LOWER:
            continue
        if place_lower in _MEETING_QUALIFIER_WORDS:
            continue
        place_tokens = _name_tokens(place)
        row_tokens = _name_tokens(name)
        if place_tokens and row_tokens and not (place_tokens & row_tokens):
            return f"title {title!r} names {place!r}, no overlap with the row ({name})"
    return None


def identity_check_hook(row, platform, result, final_seed, effective_title):
    """Wired onto wo134.IDENTITY_CHECK_HOOK below -- see that constant's
    own comment for exactly where in process_row() this runs."""
    name = row.get("_wo152_name", "")
    state = row.get("_wo152_state", "")
    country = row.get("_wo152_country", "us")
    gov_kind = row.get("_wo152_gov_kind", "")

    adapter_signal = f"{result.jurisdiction or ''} {result.meeting_body or ''}".strip()
    conflict = _state_or_kind_conflict(
        name, state, gov_kind, adapter_signal, "adapter jurisdiction/body"
    )
    if conflict:
        return conflict
    conflict = _state_or_kind_conflict(name, state, gov_kind, effective_title, "title")
    if conflict:
        return conflict
    conflict = _title_place_conflict(name, effective_title)
    if conflict:
        return conflict
    if platform in CROSS_BORDER_RISK_PLATFORMS:
        combined = (
            f"{result.jurisdiction or ''} {result.meeting_body or ''} "
            f"{effective_title or ''}"
        ).strip()
        conflict = _cross_border_collision(name, country, combined)
        if conflict:
            return conflict
    return None


wo134.IDENTITY_CHECK_HOOK = identity_check_hook


# --- consolidated-governments guard (item 9 of the WO's read list): a
# county-form gov_id in this file keys to the same real government as a
# city row -- treat that canonical id as covered too, not just the raw
# one. Zero of this candidate list's rows hit this in practice (checked
# directly before writing this script), but the guard costs nothing and
# protects a future re-run against a different candidate list. ---
def _load_consolidated_map() -> Dict[str, str]:
    out: Dict[str, str] = {}
    if CONSOLIDATED_GOV_CSV.exists():
        with CONSOLIDATED_GOV_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out[r["gov_id"]] = r["canonical_gov_id"]
    return out


CONSOLIDATED_MAP = _load_consolidated_map()


# --- report -------------------------------------------------------------

_REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "population",
    "prior_reason",
    "start_url",
    "variant_tried",
    "corrected_domain",
    "host",
    "access_mode",
    "rung_answered",
    "platform_found",
    "hit_url",
    "netloc",
    "outcome",
    "reject_reason",
    "reject_class",
    "candidates_listed",
    "candidates_tried",
    "meeting_url",
    "video_url",
    "tier",
    "page_url",
    "waf_family",
    "note",
]


def _report_writer():
    is_new = not REPORT_CSV.exists()
    f = REPORT_CSV.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=_REPORT_FIELDS, lineterminator="\n")
    if is_new:
        w.writeheader()
        f.flush()
    return f, w


def _already_done_gov_ids() -> set:
    if not REPORT_CSV.exists():
        return set()
    with REPORT_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f)}


# Same reject-reason mapping approach as wo147's own classify_skip_reason,
# extended with: WO-164's newer content-tag spellings (used directly,
# rather than writing the older no-video-found/no-meetings-found spellings
# and retagging afterward -- see docs/BREADTH_SWEEP_BRIEF.md's "Reject
# reasons" section) and the wrong-domain-mapping tag this WO's
# IDENTITY_CHECK_HOOK produces.
_CONTENT_TAXONOMY = [
    ("wrong-domain-mapping:", "wrong-domain-mapping"),
    ("no adapter in this repo", "unsupported-platform-no-adapter"),
    ("not registered in get_finder()", "unsupported-platform-no-adapter"),
    ("ambiguous: no clean recent candidate", "off-mission"),
    ("title looks like a non-meeting video", "off-mission"),
    ("no candidates", "no-meeting-nor-video"),
    ("no past CivicClerk events with real media found", "no-meeting-nor-video"),
    ("no resolvable event", "no-meeting-nor-video"),
    ("no video-bearing rows found on this AgendaCenter page", "meeting-without-video"),
    ("resolved but no transcript/agenda/video", "meeting-without-video"),
    ("no reachable AgendaCenter page found", "no-platform-link-found"),
    ("link found on hit_source_url", "no-platform-link-found"),
    ("no hit_source_urls on this row", "no-platform-link-found"),
    ("none had video", "meeting-without-video"),
    ("none actually resolved a video", "meeting-without-video"),
    ("none looked like a real meeting", "off-mission"),
    ("no video(s) listed", "no-meeting-nor-video"),
    ("granicus listing, no candidates", "no-meeting-nor-video"),
    ("no domain to guess a ViewPublisher.php listing", "no-platform-link-found"),
    ("no populated ViewPublisher.php", "no-platform-link-found"),
    ("ViewPublisher.php listing unreachable", "no-platform-link-found"),
]


def classify_skip_reason(reason: str) -> str:
    for substring, value in _CONTENT_TAXONOMY:
        if substring in reason:
            return value
    return "no-platform-link-found"


def _outcome_for_reject_reason(reason: str) -> str:
    if reason == "wrong-domain-mapping":
        return "skipped"
    if reason == "no-platform-link-found":
        return "no_platform_link_found"
    if reason == "meeting-without-video":
        return "meeting_without_video"
    if reason == "no-meeting-nor-video":
        return "no_meeting_nor_video"
    if reason == "unsupported-platform-no-adapter":
        return "blocked"
    return "skipped"


# --- candidate-row-specific extras: research_calendar_url,
# research_meeting_url, domain-variant bookkeeping ------------------------


def _bare_netloc(url: str) -> str:
    net = urlparse(wo147.normalize_home_url(url)).netloc.lower()
    return net[4:] if net.startswith("www.") else net


def _variant_and_correction(
    original_domain: str, home_url_used: str
) -> Tuple[str, str]:
    """Compares the domain the earlier client had on file against the URL
    the ladder actually used to answer, per the method's step 1 (try
    www/non-www, https/http first, "record the variant that answered as
    corrected_domain"). Returns (variant_tried, corrected_domain) --
    corrected_domain is blank unless the URL that actually worked differs
    from the recorded domain (added/removed www, http instead of https, or
    a genuinely different host) -- CLAUDE.md's rule: never blank a domain,
    only ever fill in a correction."""
    if not home_url_used:
        return "", ""
    orig_full = urlparse(wo147.normalize_home_url(original_domain)).netloc.lower()
    used_full = urlparse(wo147.normalize_home_url(home_url_used)).netloc.lower()
    used_scheme = urlparse(wo147.normalize_home_url(home_url_used)).scheme
    orig_bare = orig_full[4:] if orig_full.startswith("www.") else orig_full
    used_bare = used_full[4:] if used_full.startswith("www.") else used_full

    if used_bare != orig_bare:
        return "different-domain", used_full

    variants = []
    if used_full != orig_full:
        variants.append("www-added" if used_full.startswith("www.") else "www-removed")
    if used_scheme == "http":
        variants.append("http")
    if not variants:
        return "", ""
    return "+".join(variants), used_full


async def _try_research_meeting_url(
    research_meeting_url: str,
) -> Optional[Tuple[str, str]]:
    if not research_meeting_url:
        return None
    platform = detect_platform(research_meeting_url)
    if platform and platform != "unknown":
        return platform, research_meeting_url
    return None


async def process_candidate(
    session: aiohttp.ClientSession, row: dict, covered_gov_ids: set, writer
) -> str:
    """Returns 'ok' or 'error' (for the consecutive-error breaker). Reuses
    wo147.run_access_ladder/discovery_candidate_urls/channel_scan_caution
    and wo134.process_row unchanged; only the row-shape adaptation,
    research_calendar_url/research_meeting_url handling, and this WO's own
    report schema are new."""
    gov_id = row["gov_id"]
    name = row["name"]
    state = row["state"]
    country = row.get("country", "us")
    gov_kind = row["gov_kind"]
    population = row["population"]
    domain = row["domain"]
    known_platform_raw = row["known_platform"]
    prior_reason = row["prior_reason"]
    research_calendar_url = row.get("research_calendar_url") or ""
    research_meeting_url = row.get("research_meeting_url") or ""

    base_report = dict(
        gov_id=gov_id,
        name=name,
        state=state,
        gov_kind=gov_kind,
        population=population,
        prior_reason=prior_reason,
        start_url="",
        variant_tried="",
        corrected_domain="",
        host="",
        access_mode="",
        rung_answered="",
        platform_found="",
        hit_url="",
        netloc="",
        outcome="",
        reject_reason="",
        reject_class="",
        candidates_listed=0,
        candidates_tried=0,
        meeting_url="",
        video_url="",
        tier="",
        page_url="",
        waf_family="",
        note="",
    )

    # Consolidated-governments guard -- see CONSOLIDATED_MAP's own comment.
    check_ids = {gov_id, CONSOLIDATED_MAP.get(gov_id, gov_id)}
    if check_ids & covered_gov_ids:
        writer.writerow({**base_report, "outcome": "already_covered"})
        return "ok"

    # Step 1: research_calendar_url first (a known meetings page), domain
    # otherwise. On a miss, fall back to the plain domain -- this
    # candidate list only has 6 rows with a calendar URL set, so the
    # extra request budget is negligible.
    start_url = research_calendar_url or domain
    base_report["start_url"] = start_url
    base_report["host"] = urlparse(wo147.normalize_home_url(start_url)).netloc

    ladder = await wo147.run_access_ladder(session, name, state, domain, start_url)
    if (
        research_calendar_url
        and not ladder.platform
        and ladder.access_mode not in ("dead", "challenge")
    ):
        await asyncio.sleep(wo147.HOST_DELAY_SECONDS)
        fallback_ladder = await wo147.run_access_ladder(
            session, name, state, domain, ""
        )
        if fallback_ladder.platform or fallback_ladder.access_mode in (
            "dead",
            "challenge",
        ):
            ladder = fallback_ladder
            base_report["note"] = (
                "research_calendar_url had no hit; fell back to domain"
            )

    # Real, confirmed-live bug caught auditing this WO's own jurisdiction_
    # coverage.csv apply: `ladder.home_url` is set to the LAST URL variant
    # *attempted*, even when every variant failed (a fully "dead" host) --
    # a genuinely dead domain's last-tried candidate is often literally
    # "http://<domain>" (the final rung in run_access_ladder()'s own
    # variant list), which differs in scheme from the recorded domain and
    # got misread as a real "http variant answered" correction on 981 of
    # 1814 rows, almost all of them "dead"/"timeout"/"blocked-*"/
    # "challenge" -- hosts that never actually served real content back.
    # "Record the variant that answered" (this WO's own method) means
    # answered, not merely tried -- only "plain"/"browser-headers" access
    # modes mean a real page was fetched and searched.
    if ladder.access_mode in ("plain", "browser-headers"):
        variant_tried, corrected_domain = _variant_and_correction(
            domain, ladder.home_url
        )
    else:
        variant_tried, corrected_domain = "", ""
    base_report["variant_tried"] = variant_tried
    base_report["corrected_domain"] = corrected_domain
    base_report["access_mode"] = ladder.access_mode
    base_report["rung_answered"] = ladder.rung_answered
    base_report["waf_family"] = ladder.waf_family
    if ladder.note and not base_report["note"]:
        base_report["note"] = ladder.note
    wo147.write_host_access_mode(
        base_report["host"], ladder.access_mode, ladder.waf_family
    )

    if ladder.access_mode == "challenge":
        writer.writerow(
            {
                **base_report,
                "outcome": "blocked",
                "reject_reason": "cloudflare-challenge-blocked",
                "reject_class": "access",
            }
        )
        return "ok"
    if ladder.access_mode in ("dead", "timeout"):
        writer.writerow(
            {
                **base_report,
                "outcome": "dead",
                "reject_reason": "dns-unresolvable"
                if ladder.access_mode == "dead"
                else "timeout",
                "reject_class": "access",
            }
        )
        return "ok"
    if ladder.access_mode == "blocked-plain-http":
        writer.writerow(
            {
                **base_report,
                "outcome": "blocked",
                "reject_reason": "blocked-plain-http",
                "reject_class": "access",
            }
        )
        return "ok"
    if ladder.access_mode == "blocked-browser-headers":
        writer.writerow(
            {
                **base_report,
                "outcome": "blocked",
                "reject_reason": "blocked-browser-headers",
                "reject_class": "access",
            }
        )
        return "ok"

    hits: List[Tuple[str, str]] = []

    meeting_hit = await _try_research_meeting_url(research_meeting_url)
    if meeting_hit:
        hits.append(meeting_hit)

    if ladder.platform and ladder.hit_url:
        hits.append((ladder.platform, ladder.hit_url))

    known_platform = wo147.normalize_known_platform(known_platform_raw)
    if known_platform and known_platform not in wo134.UNSUPPORTED_PLATFORMS:
        seed = ladder.home_url or wo147.normalize_home_url(start_url)
        if not any(p == known_platform for p, _ in hits):
            hits.append((known_platform, seed))

    platform_found = ladder.platform or known_platform or (hits[0][0] if hits else "")
    base_report["platform_found"] = platform_found
    if ladder.hit_url:
        base_report["hit_url"] = ladder.hit_url
    elif hits:
        base_report["hit_url"] = hits[0][1]

    if not hits:
        writer.writerow(
            {
                **base_report,
                "outcome": "no_platform_link_found",
                "reject_reason": "no-platform-link-found",
                "reject_class": "content",
            }
        )
        return "ok"

    primary_platform, primary_url = hits[0]
    netloc = urlparse(primary_url).netloc
    base_report["netloc"] = netloc

    discovery_note = ""
    if netloc and primary_platform in wo147.DISCOVERY_ENUMERABLE:
        disc_urls, discovery_note = await wo147.discovery_candidate_urls(
            netloc, primary_platform, gov_id, state
        )
        if disc_urls:
            wo147.write_discovery_seed(
                netloc, primary_platform, gov_id, ladder.access_mode
            )
            for u in disc_urls:
                hits.insert(0, (primary_platform, u))
    if netloc:
        wo147.write_discovery_seed(netloc, primary_platform, gov_id, ladder.access_mode)

    hit_source_urls = ";".join(f"{p}={u}" for p, u in hits[:6])
    base_report["candidates_listed"] = len(hits[:6])
    base_report["candidates_tried"] = len(hits[:6])
    if discovery_note:
        base_report["note"] = (base_report["note"] + "; " + discovery_note).strip("; ")

    synthetic_row = {
        "gov_id": gov_id,
        "unit_name": name,
        "homepage": ladder.home_url or wo147.normalize_home_url(start_url),
        "hop2_urls": "",
        "hit_source_urls": hit_source_urls,
        # WO-152's own identity-check hook reads these (see
        # identity_check_hook() above) -- process_row() itself ignores
        # any key it doesn't already look up, so these ride along safely.
        "_wo152_name": name,
        "_wo152_state": state,
        "_wo152_country": country,
        "_wo152_gov_kind": gov_kind,
    }

    try:
        result = await wo134.process_row(
            session, synthetic_row, covered_gov_ids, "wo152_dead_domain_recheck"
        )
    except Exception as e:  # noqa: BLE001
        writer.writerow(
            {
                **base_report,
                "outcome": "error",
                "note": f"process_row raised: {type(e).__name__}: {e}",
            }
        )
        return "error"

    outcome = result.outcome
    if outcome == "already_covered":
        writer.writerow({**base_report, "outcome": "already_covered"})
        return "ok"

    if outcome == "ingested_tier1_2":
        tier = "tier2" if result.platform == "youtube" else "tier1"
        caution = wo147.channel_scan_caution(result.platform, hits)
        note = "; ".join(p for p in (base_report["note"], result.reason, caution) if p)
        writer.writerow(
            {
                **base_report,
                "outcome": "ingested_tier1_2",
                "meeting_url": result.seed_url,
                "tier": tier,
                "page_url": result.page_url,
                "note": note,
            }
        )
        return "ok"

    if outcome == "queued_tier3_pending":
        caution = wo147.channel_scan_caution(result.platform, hits)
        note = "; ".join(p for p in (base_report["note"], result.reason, caution) if p)
        writer.writerow(
            {
                **base_report,
                "outcome": "queued_tier3",
                "meeting_url": result.seed_url,
                "tier": "tier3_pending",
                "note": note,
            }
        )
        return "ok"

    if outcome == "queued_tier3":
        writer.writerow(
            {
                **base_report,
                "outcome": "queued_tier3",
                "meeting_url": result.seed_url,
                "tier": "tier3",
                "note": (base_report["note"] + "; " + result.reason).strip("; "),
            }
        )
        return "ok"

    if outcome == "no_video_found":
        writer.writerow(
            {
                **base_report,
                "outcome": "meeting_without_video",
                "reject_reason": "meeting-without-video",
                "reject_class": "content",
                "meeting_url": result.seed_url,
                "note": (base_report["note"] + "; " + result.reason).strip("; "),
            }
        )
        return "ok"

    if outcome == "error":
        writer.writerow(
            {
                **base_report,
                "outcome": "error",
                "note": (base_report["note"] + "; " + result.reason).strip("; "),
            }
        )
        return "error"

    # outcome == "skipped"
    reject_reason = classify_skip_reason(result.reason)
    writer.writerow(
        {
            **base_report,
            "outcome": _outcome_for_reject_reason(reject_reason),
            "reject_reason": reject_reason,
            "reject_class": "identity"
            if reject_reason == "wrong-domain-mapping"
            else "content",
            "note": (base_report["note"] + "; " + result.reason).strip("; "),
        }
    )
    return "ok"


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--start-after", type=str, default=None)
    parser.add_argument("--inventory-csv", type=Path, default=DEFAULT_INVENTORY_CSV)
    args = parser.parse_args()

    if not wo134._base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (check .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    register_all_finders()

    covered_gov_ids = wo134._load_covered_gov_ids(args.inventory_csv)
    print(f"{len(covered_gov_ids)} gov_ids already have an archived page.")

    with CANDIDATES_CSV.open(newline="", encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))
    print(f"{len(all_rows)} candidate rows in {CANDIDATES_CSV.name}")

    already_done = _already_done_gov_ids()
    print(
        f"{len(already_done)} gov_ids already in {REPORT_CSV.name} -- skipping those."
    )

    skip_until_seen = args.start_after is not None
    to_process = []
    for row in all_rows:
        if row["gov_id"] in already_done:
            continue
        if skip_until_seen:
            if row["gov_id"] == args.start_after:
                skip_until_seen = False
            continue
        to_process.append(row)
    if args.limit:
        to_process = to_process[: args.limit]

    print(f"Processing {len(to_process)} row(s)...\n")

    report_f, writer = _report_writer()
    tally: Dict[str, int] = {}
    consecutive_errors = 0
    try:
        async with aiohttp.ClientSession() as session:
            for i, row in enumerate(to_process):
                t0 = time.monotonic()
                try:
                    status = await process_candidate(
                        session, row, covered_gov_ids, writer
                    )
                except Exception as e:  # noqa: BLE001
                    # Real, confirmed-live incident running this WO's own
                    # full sweep: an unhandled exception from deep inside
                    # the reused ladder code (a BeautifulSoup parser
                    # crash on a genuinely malformed response -- fixed at
                    # its source in wo147_access_ladder_sweep.py's own
                    # _safe_soup(), but this catch-all is the backstop so
                    # the NEXT unanticipated crash costs one row, not the
                    # remaining ~900 of a multi-hour run.
                    writer.writerow(
                        {
                            "gov_id": row.get("gov_id", ""),
                            "name": row.get("name", ""),
                            "state": row.get("state", ""),
                            "gov_kind": row.get("gov_kind", ""),
                            "population": row.get("population", ""),
                            "prior_reason": row.get("prior_reason", ""),
                            "start_url": "",
                            "variant_tried": "",
                            "corrected_domain": "",
                            "host": "",
                            "access_mode": "",
                            "rung_answered": "",
                            "platform_found": "",
                            "hit_url": "",
                            "netloc": "",
                            "outcome": "error",
                            "reject_reason": "",
                            "reject_class": "",
                            "candidates_listed": 0,
                            "candidates_tried": 0,
                            "meeting_url": "",
                            "video_url": "",
                            "tier": "",
                            "page_url": "",
                            "waf_family": "",
                            "note": f"unhandled exception: {type(e).__name__}: {e}",
                        }
                    )
                    status = "error"
                report_f.flush()
                elapsed = time.monotonic() - t0
                print(
                    f"[{i + 1}/{len(to_process)}] {row['name']}, {row['state']} "
                    f"({row['gov_kind']}) -- {elapsed:.1f}s -- status={status}"
                )
                tally[status] = tally.get(status, 0) + 1
                if status == "error":
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0
                if consecutive_errors >= 6:
                    print(
                        f"\nABORTING: {consecutive_errors} consecutive real errors. "
                        "Re-run to resume (already-reported rows are skipped).",
                        file=sys.stderr,
                    )
                    break
                if i < len(to_process) - 1:
                    await asyncio.sleep(wo147.GOV_DELAY_SECONDS)
    finally:
        report_f.close()
        if wo147._ledger is not None:
            wo147._ledger.close()

    print("\n--- Tally (this run) ---")
    for k, v in sorted(tally.items()):
        print(f"{k:10} {v}")
    print(f"\nFull report: {REPORT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
