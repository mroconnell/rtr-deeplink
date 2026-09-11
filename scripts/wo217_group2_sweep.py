"""WO-217 (2026-09-11): Group 2 -- municipalities of 5,000+ with no
Archive page, `reject_reason` `no-video-found`/`meeting-without-video`,
that carry NO alternate domain on file yet. This script finds a second
domain first, verifies it, records it into `alternate_domains` (never
replacing `domain`), then runs the same one-hop-for-a-different-platform
check `wo217_group1_sweep.py` runs on an already-recorded alternate.

Domain discovery, in the brief's own priority order (each a candidate
HOST, tried in order until one verifies):
  1. `uscityurl_raw.csv` (2022 Census-adjacent municipal website list,
     keyed by GEOID -- `us:place:<geoid>` -> `1600000US<geoid>`).
  2. `wo180_wikidata_candidates.csv` (WO-180's Wikidata FIPS/GNIS bridge,
     15,122 valid gov_id joins, `website` column -- the RAW candidate
     list, not the already-applied `wo180_alt_domain_added_rows.csv`;
     confirmed live at this WO's own run start that the already-verified
     `wo180_alt_domain_verified.csv` has ZERO overlap with this
     population, since a passed WO-180 candidate would already have been
     applied and this population is defined as "no alternate at all").
  3. `civicdata_domains_verified.csv` (WO-177 CivicMirror/Civic-Data,
     `verified`+`title_match` columns -- confirmed zero overlap with
     this population at run start, same reasoning as #2, kept in the
     order anyway per the brief and in case a later run changes that).
  4. The row's own `hub_url` host, when it differs from `domain`.
  5. Guess patterns (at most ~8 per government, one polite request each),
     same shape as `find_gov_domains.py`'s `domain_candidates()`:
     `{name}.gov`, `cityof{name}.{gov,org,com}`, `{name}{st}.gov`,
     `{name}-{st}.gov`, `townof{name}.gov`/`villageof{name}.gov`,
     `ci.{name}.{st}.us`, `www.{name}-{st}.gov`.

Each candidate is verified against WO-186's own looser evidence rule
(ENUMERATION_METHODS.md §235): accept if the government's name (allowing
a City/Town/Village/Borough-of prefix, a state abbreviation, hyphens/
spaces stripped) appears in the title, `<h1>`, `og:site_name`, the
footer, or the domain string itself, OR the page carries an independent
government signal (a `.gov` host, or a link to an agenda/minutes/
council/board page, or a known meeting-platform link). Reject a
parked/squatted domain (`PARKED_MARKERS`/`GAMBLING_LOAN_MARKERS`, same
fixtures WO-177/WO-180 use), a "coming soon" placeholder, or a page that
plainly names a different government. Stops guessing a government at the
first verified hit, per the brief.

A verified new domain is written into `alternate_domains` by the apply
step (`research/wo217_apply_to_jc.py`) -- this script itself only
reports; the field is never touched live mid-sweep, matching every other
WO in this family's read-mostly-during-the-sweep convention. Once
verified, the SAME one-hop check Group 1 uses runs against it
(`coverage_alternates.one_hop_alternate()`), and a different-platform
find goes through the identical resolve/ingest/hand-check/probe pipeline
`wo217_group1_sweep.py` uses (this module imports that script's helpers
rather than re-implementing them).

Writes to the same `research/wo217_report.csv`, `group=found_alternate`
rows for a verified domain and `group=no_alternate_found` for a row
where nothing verified after all sources + guesses were tried.

Usage:
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo217_g2.db" \\
        python3 scripts/wo217_group2_sweep.py --inventory-csv /tmp/wo217_inv/meeting_inventory.csv [--limit N] [--skip-guessing]
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

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.queue_probe import (
    append_probe_row,
    probe_queue_entry,
    DEFAULT_SIDECAR_PATH,
)  # noqa: E402

from scripts.coverage_alternates import (  # noqa: E402
    FOUND,
    normalize_host,
    one_hop_alternate,
)
from scripts.wo147_access_ladder_sweep import (  # noqa: E402
    HONEST_HEADERS,
    fetch_one,
    find_hop_links,
    find_platform_link,
    is_challenge,
)
from scripts.wo217_handcheck import get_last_verdict, hand_check_hook  # noqa: E402
from scripts.wo146_api_relist_sweep import _extract_state_from_text  # noqa: E402

import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402

wo134.IDENTITY_CHECK_HOOK = hand_check_hook

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
CANDIDATES_CSV = RESEARCH_DIR / "wo217_candidates.csv"
JC_CSV = RESEARCH_DIR / "jurisdiction_coverage.csv"
REPORT_CSV = RESEARCH_DIR / "wo217_report.csv"
DISCOVERY_SEEDS_CSV = RESEARCH_DIR / "wo217_discovery_seeds.csv"
# --guess-only mode (a second pass over rows the local-source pass left
# no_alternate_found): resumability for THIS mode is tracked separately
# here, since the main report already carries a no_alternate_found row
# for every one of those gov_ids from the first pass -- re-using
# already_done_gov_ids() would skip them all immediately. A row is only
# ever rewritten in wo217_report.csv (never duplicated) when guessing
# actually improves on the prior no_alternate_found outcome.
GUESS_DONE_TXT = RESEARCH_DIR / "wo217_guess_pass_done.txt"

USCITYURL_CSV = RESEARCH_DIR / "uscityurl_raw.csv"
WIKIDATA_CSV = RESEARCH_DIR / "wo180_wikidata_candidates.csv"
CIVICDATA_CSV = RESEARCH_DIR / "civicdata_domains_verified.csv"

TIER3_QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"
DEFERRED_FILE = REPO_ROOT / "scripts" / "tier3_long_meetings_deferred.txt"
TENANT_OVERRIDES_CSV = (
    REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "tenant_overrides.csv"
)

HOST_DELAY_SECONDS = 2.0
GOV_DELAY_SECONDS = 1.5
DEFER_OVER_SECONDS = 90 * 60

REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "population",
    "domain",
    "primary_reason",
    "primary_platform",
    "group",
    "alternate_tried",
    "alternate_source",
    "alternate_verified_by",
    "hop_platform_found",
    "different_platform",
    "outcome",
    "hand_check",
    "meeting_url",
    "video_url",
    "tier",
    "page_url",
    "note",
]

# --- WO-186 evidence rule + parked/squatted rejection (reused shape from
# wo180_verify_and_apply.py / wo177's own script -- see this module's
# docstring). Re-implemented locally (not cross-imported from
# rtr-business/research) to keep this script's dependency surface inside
# this repo, same as every other WO-184-family script. ---

PARKED_MARKERS = [
    "for sale",
    "domain is parked",
    "buy this domain",
    "this domain may be for sale",
    "hugedomains",
    "sedo",
    "godaddy",
    "backorder this domain",
    "domain parking",
    "the domain has expired",
    "this web page is parked",
    "related searches",
    "bodis",
    "parkingcrew",
    "afternic",
    "namecheap parking",
]
GAMBLING_LOAN_MARKERS = [
    "casino",
    "jackpot",
    "slot depo",
    "slot gacor",
    "judi online",
    "situs slot",
    "payday loan",
    "cash advance",
    "bet online",
    "sportsbook bonus",
]
COMING_SOON_MARKERS = [
    "coming soon",
    "future home of",
    "site under construction",
    "under construction",
    "launching soon",
    "website is currently unavailable",
]

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.IGNORECASE | re.DOTALL)
_OGSITE_RE = re.compile(
    r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']*)["\']',
    re.IGNORECASE,
)
_FOOTER_RE = re.compile(r"<footer[^>]*>(.*?)</footer>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_AGENDA_LINK_RE = re.compile(
    r'href=["\']([^"\']*(?:agenda|minutes|council|board|meeting)[^"\']*)["\']',
    re.IGNORECASE,
)
_TRAILING_TYPE_RE = re.compile(
    r"\s+(city \(balance\)|city|town|village|CDP|borough|township|"
    r"charter township|consolidated government|metropolitan government "
    r"\(balance\)|metropolitan government|corporation|unified government|"
    r"metro government|municipality|county|parish|census area|municipio|"
    r"region)$",
    re.IGNORECASE,
)


def bare_name(name: str) -> str:
    return _TRAILING_TYPE_RE.sub("", name or "").strip()


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def _strip_tags(html_fragment: str) -> str:
    return _TAG_RE.sub(" ", html_fragment or "")


def is_parked_or_squatted(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in PARKED_MARKERS) or any(
        m in low for m in GAMBLING_LOAN_MARKERS
    )


def is_coming_soon(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in COMING_SOON_MARKERS)


def name_tokens(name: str) -> set:
    bare = bare_name(name)
    bare = re.sub(
        r"^(city|town|village|borough|township) of\s+", "", bare, flags=re.IGNORECASE
    )
    return {w for w in re.sub(r"[^a-z0-9 ]", " ", bare.lower()).split() if len(w) > 2}


def evidence_check(
    html: str,
    final_url: str,
    name: str,
    state: str = "",
    *,
    allow_host_only_match: bool = True,
) -> Tuple[bool, str]:
    """WO-186's looser evidence rule. Returns (accepted, reason).

    `allow_host_only_match=False` (used for guess-pattern candidates,
    which -- unlike uscityurl/wikidata/civicdata -- come from no
    independent government-adjacent list at all) requires the name match
    to come from real page CONTENT (title/h1/og:site_name/footer), not
    just the domain string itself -- a guessed `cityof<name>.com` with an
    empty/unparseable title would otherwise pass on the domain string
    alone, which is real evidence for a *recorded* candidate but not for
    one this script invented itself.

    A state/province conflict rejects OUTRIGHT, before any name-match
    check -- real, confirmed-live miss (2026-09-11): a guessed
    `cityoffreeport.org` for Freeport village, NY verified on a bare
    "Freeport" token match, but the page's own title read "City of
    Freeport, Illinois" -- a real, different, same-named government
    (`@cityoffreeportill7042` on YouTube). A same-name-different-state
    collision is exactly the failure mode the preamble's Kind A warns
    about, and the government's own name matching in isolation cannot
    catch it -- the STATE the page itself claims has to agree with the
    row's own state whenever the page states one at all (same reasoning
    as `wo146_api_relist_sweep._extract_state_from_text`, reused here
    directly)."""
    if not html:
        return False, "no html"
    title_m = _TITLE_RE.search(html)
    title = _strip_tags(title_m.group(1)).strip() if title_m else ""
    h1_m = _H1_RE.search(html)
    h1 = _strip_tags(h1_m.group(1)).strip() if h1_m else ""
    ogsite_m = _OGSITE_RE.search(html)
    ogsite = ogsite_m.group(1).strip() if ogsite_m else ""
    footer_m = _FOOTER_RE.search(html)
    footer = _strip_tags(footer_m.group(1)).strip() if footer_m else ""
    body_snippet = html[:6000]

    combined_for_reject = f"{title} {h1} {ogsite} {footer[:500]}"
    if is_parked_or_squatted(combined_for_reject) or is_parked_or_squatted(
        body_snippet
    ):
        return False, "parked/squatted domain"
    if is_coming_soon(combined_for_reject):
        return False, "coming-soon placeholder"

    expected_state = (state or "").strip().upper()
    if expected_state:
        found_state = _extract_state_from_text(combined_for_reject)
        if found_state and found_state != expected_state:
            return (
                False,
                f"state conflict: page names {found_state}, row expects {expected_state} "
                f"(title={title!r})",
            )

    host = normalize_host(final_url)
    tokens = name_tokens(name)

    def _hits(haystack: str) -> bool:
        return bool(tokens) and (
            all(t in haystack for t in tokens)
            if len(tokens) <= 2
            else sum(1 for t in tokens if t in haystack) >= max(1, len(tokens) - 1)
        )

    content_haystack = f"{title} {h1} {ogsite} {footer}".lower()
    if _hits(content_haystack):
        return True, f"name match ({title or h1 or ogsite})"

    if allow_host_only_match and _hits(host.lower()):
        return True, f"name match (domain string: {host})"

    if host.endswith(".gov"):
        return True, f"independent government signal: .gov host ({host})"
    if _AGENDA_LINK_RE.search(html):
        return (
            True,
            "independent government signal: agenda/minutes/council/board link found",
        )
    hit = find_platform_link(html, final_url)
    if hit:
        return True, f"independent government signal: known platform link ({hit[0]})"

    return False, f"no name match, no government signal (title={title!r})"


# --- Local, pre-network candidate sources ---

_uscity_cache: Optional[Dict[str, str]] = None
_wikidata_cache: Optional[Dict[str, str]] = None
_civicdata_cache: Optional[Dict[str, str]] = None


def _load_uscityurl() -> Dict[str, str]:
    global _uscity_cache
    if _uscity_cache is None:
        out = {}
        with USCITYURL_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                geoid = r.get("GEOID", "")
                if geoid.startswith("1600000US") and r.get("WEBSITE_AVAILABLE") == "1":
                    fips = geoid[len("1600000US") :]
                    out["us:place:" + fips] = r.get("WEBSITE_URL", "")
        _uscity_cache = out
    return _uscity_cache


def _load_wikidata() -> Dict[str, str]:
    global _wikidata_cache
    if _wikidata_cache is None:
        out = {}
        if WIKIDATA_CSV.exists():
            with WIKIDATA_CSV.open(newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    out[r["gov_id"]] = r.get("website", "")
        _wikidata_cache = out
    return _wikidata_cache


def _load_civicdata() -> Dict[str, str]:
    global _civicdata_cache
    if _civicdata_cache is None:
        out = {}
        if CIVICDATA_CSV.exists():
            with CIVICDATA_CSV.open(newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    if r.get("verified") == "1" and r.get("title_match") == "1":
                        out[r["gov_id"]] = r.get("domain", "")
        _civicdata_cache = out
    return _civicdata_cache


def local_source_candidates(cand: dict) -> List[Tuple[str, str]]:
    """[(source_label, host), ...] in priority order, deduped, excluding
    the row's own current primary domain."""
    gov_id = cand["gov_id"]
    cur_host = normalize_host(cand["domain"])
    out: List[Tuple[str, str]] = []
    seen = {cur_host} if cur_host else set()

    uscity = _load_uscityurl().get(gov_id, "")
    h = normalize_host(uscity)
    if h and h not in seen:
        out.append(("uscityurl", h))
        seen.add(h)

    wiki = _load_wikidata().get(gov_id, "")
    h = normalize_host(wiki)
    if h and h not in seen:
        out.append(("wikidata", h))
        seen.add(h)

    civicdata = _load_civicdata().get(gov_id, "")
    h = normalize_host(civicdata)
    if h and h not in seen:
        out.append(("civicdata", h))
        seen.add(h)

    hub = normalize_host(cand.get("hub_url", ""))
    if hub and hub not in seen:
        out.append(("hub_host", hub))
        seen.add(hub)

    return out


def guess_candidates(cand: dict) -> List[str]:
    """Up to 8 guessed hostnames, same shape as find_gov_domains.py's
    domain_candidates() -- see this module's docstring."""
    bare = bare_name(cand["name"])
    s = _slug(bare)
    st = (cand.get("state") or "").strip().lower()
    if not s:
        return []
    cur_host = normalize_host(cand["domain"])
    raw = [
        f"{s}.gov",
        f"cityof{s}.gov",
        f"cityof{s}.org",
        f"cityof{s}.com",
        f"{s}{st}.gov" if st else None,
        f"{s}-{st}.gov" if st else None,
        f"townof{s}.gov",
        f"villageof{s}.gov",
        f"ci.{s}.{st}.us" if st else None,
    ]
    seen = {cur_host} if cur_host else set()
    out = []
    for h in raw:
        if h and h not in seen:
            seen.add(h)
            out.append(h)
    return out[:8]


# --- Report scaffolding (shared shape with wo217_group1_sweep.py) ---

_pending_tier3_candidate: Optional[dict] = None


def _tier3_capture_handler(
    *, gov_id, unit_name, platform, final_seed, hit_url, title, date, result
) -> None:
    global _pending_tier3_candidate
    pin_row = None
    if platform in wo134.SHARED_HOST_PLATFORMS:
        host = wo134._tenant_override_host(platform, result, final_seed)
        match = wo134._tenant_override_match(platform, result, final_seed)
        if host and match:
            pin_row = (
                host,
                match,
                gov_id,
                "fallback",
                "wo217",
                f"{unit_name} -- WO-217 found-alternate lead, gov_id={gov_id}",
            )
    _pending_tier3_candidate = {
        "gov_id": gov_id,
        "platform": platform,
        "meeting_url": final_seed,
        "video_url": result.video_url or final_seed,
        "source_url": hit_url,
        "pin_row": pin_row,
    }


wo134.TIER3_HANDLER = _tier3_capture_handler


def load_jc_rows() -> Dict[str, dict]:
    with JC_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"]: r for r in csv.DictReader(f) if r.get("gov_id")}


def load_candidates() -> List[dict]:
    with CANDIDATES_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [
        r
        for r in rows
        if not (
            (r.get("alternate_domains") or "").strip()
            or (r.get("alternate_urls") or "").strip()
        )
    ]


def already_done_gov_ids() -> set:
    if not REPORT_CSV.exists():
        return set()
    with REPORT_CSV.open(newline="", encoding="utf-8") as f:
        return {
            r["gov_id"]
            for r in csv.DictReader(f)
            if r.get("gov_id")
            and r.get("group") in ("found_alternate", "no_alternate_found")
        }


def report_writer():
    is_new = not REPORT_CSV.exists()
    f = REPORT_CSV.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=REPORT_FIELDS, lineterminator="\n")
    if is_new:
        w.writeheader()
        f.flush()
    return f, w


def _log_discovery_seed(
    gov_id: str, name: str, state: str, source: str, host: str, reason: str
) -> None:
    is_new = not DISCOVERY_SEEDS_CSV.exists()
    with DISCOVERY_SEEDS_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["gov_id", "name", "state", "source", "host", "reason"],
            lineterminator="\n",
        )
        if is_new:
            w.writeheader()
        w.writerow(
            {
                "gov_id": gov_id,
                "name": name,
                "state": state,
                "source": source,
                "host": host,
                "reason": reason,
            }
        )


def _existing_override_keys() -> set:
    keys = set()
    if TENANT_OVERRIDES_CSV.exists():
        with TENANT_OVERRIDES_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                keys.add((r.get("tenant_host", ""), r.get("match", "")))
    return keys


def _apply_pin_row(pin_row_tuple, existing_keys: set) -> None:
    if not pin_row_tuple:
        return
    tenant_host, match, gov_id, strength, source, evidence = pin_row_tuple
    key = (tenant_host, match)
    if key in existing_keys:
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
                "tenant_host": tenant_host,
                "match": match,
                "gov_id": gov_id,
                "strength": strength,
                "source": source,
                "evidence": evidence,
            }
        )
    existing_keys.add(key)


async def _is_same_site_redirect(
    session: aiohttp.ClientSession, primary_domain: str, alternate_domain: str
) -> bool:
    primary_host = normalize_host(primary_domain)
    if not primary_host:
        return False
    url = (
        alternate_domain if "://" in alternate_domain else f"https://{alternate_domain}"
    )
    r = await fetch_one(session, url, HONEST_HEADERS)
    final_host = normalize_host(getattr(r, "final_url", "") or "")
    return bool(final_host) and final_host == primary_host


def _base_row(cand: dict, jc_row: dict) -> dict:
    return {
        "gov_id": cand["gov_id"],
        "name": cand["name"],
        "state": cand["state"],
        "population": cand["population"],
        "domain": cand["domain"],
        "primary_reason": cand["reject_reason"],
        "primary_platform": (jc_row.get("suspected_video_provider") or "").strip()
        or (jc_row.get("suspected_meeting_link_provider") or "").strip(),
        "group": "found_alternate",
    }


def _bare_host(host: str) -> str:
    """Host with a leading 'www.' stripped, for same-site comparison
    only (never for storage -- candidate_domains()/normalize_host() keep
    www/non-www as distinct on purpose, see coverage_alternates.py). A
    candidate that differs from the primary only by a 'www.' prefix is
    not a second domain, just the same site under its other spelling --
    confirmed live (Fremont, CA: primary 'fremont.gov', uscityurl
    'www.fremont.gov' -- same host)."""
    h = (host or "").lower()
    return h[4:] if h.startswith("www.") else h


async def find_and_verify_alternate(
    session: aiohttp.ClientSession,
    cand: dict,
    skip_guessing: bool,
    guess_only: bool = False,
) -> Tuple[Optional[str], str, str]:
    """Returns (verified_host_or_None, source, verified_by_reason).

    `guess_only=True` (the second-pass mode, see GUESS_DONE_TXT above)
    skips the local-source loop entirely -- it already ran and came back
    empty in the first pass, so re-trying it here would just repeat the
    same live fetches for no new information."""
    primary_bare = _bare_host(normalize_host(cand["domain"]))

    if not guess_only:
        for source, host in local_source_candidates(cand):
            if _bare_host(host) == primary_bare:
                continue
            url = host if "://" in host else f"https://{host}"
            r = await fetch_one(session, url, HONEST_HEADERS)
            await asyncio.sleep(HOST_DELAY_SECONDS)
            if getattr(r, "html", None) is None:
                continue
            if is_challenge(r.html):
                continue
            if _bare_host(normalize_host(r.final_url)) == primary_bare:
                continue  # resolved back to the primary's own site
            ok, reason = evidence_check(
                r.html, r.final_url, cand["name"], cand.get("state", "")
            )
            if ok:
                return normalize_host(r.final_url) or host, source, reason

    if skip_guessing:
        return None, "", ""

    for host in guess_candidates(cand):
        if _bare_host(host) == primary_bare:
            continue
        url = f"https://{host}"
        r = await fetch_one(session, url, HONEST_HEADERS)
        await asyncio.sleep(HOST_DELAY_SECONDS)
        if getattr(r, "html", None) is None:
            continue
        if is_challenge(r.html):
            continue
        if _bare_host(normalize_host(r.final_url)) == primary_bare:
            continue
        # Guesses get the stricter check -- no independent list backs
        # them, so a bare domain-string match isn't enough on its own.
        ok, reason = evidence_check(
            r.html,
            r.final_url,
            cand["name"],
            cand.get("state", ""),
            allow_host_only_match=False,
        )
        if ok:
            return normalize_host(r.final_url) or host, "guess", reason

    return None, "", ""


async def process_one(
    session: aiohttp.ClientSession,
    cand: dict,
    jc_row: dict,
    covered_gov_ids: set,
    existing_pin_keys: set,
    skip_guessing: bool,
    guess_only: bool = False,
) -> dict:
    global _pending_tier3_candidate
    base = _base_row(cand, jc_row)

    verified_host, source, verified_by = await find_and_verify_alternate(
        session, cand, skip_guessing, guess_only
    )

    if not verified_host:
        return {
            **base,
            "group": "no_alternate_found",
            "alternate_tried": "",
            "alternate_source": "",
            "alternate_verified_by": "",
            "hop_platform_found": "",
            "different_platform": "",
            "outcome": "no_alternate_found",
            "hand_check": "n/a",
            "meeting_url": "",
            "video_url": "",
            "tier": "",
            "page_url": "",
            "note": "no candidate verified from uscityurl/wikidata/civicdata/hub_url"
            + ("" if skip_guessing else "/guess patterns"),
        }

    base["alternate_source"] = source
    base["alternate_tried"] = verified_host
    base["alternate_verified_by"] = verified_by
    _log_discovery_seed(
        cand["gov_id"], cand["name"], cand["state"], source, verified_host, verified_by
    )

    # jc_row for one_hop_alternate() needs the SAME known-platform fields;
    # the verified host is passed directly as the alternate (not folded
    # into candidate_domains(), since it isn't recorded in
    # jurisdiction_coverage.csv until the apply step).
    async def fetch_one_fn(url, headers):
        return await fetch_one(session, url, headers)

    hop_result = await one_hop_alternate(
        jc_row,
        verified_host,
        fetch_one_fn,
        HONEST_HEADERS,
        is_challenge,
        find_platform_link,
        find_hop_links,
        between_requests_seconds=HOST_DELAY_SECONDS,
    )

    if hop_result.reason != FOUND:
        return {
            **base,
            "hop_platform_found": "",
            "different_platform": "",
            "outcome": hop_result.reason,
            "hand_check": "n/a",
            "meeting_url": "",
            "video_url": "",
            "tier": "",
            "page_url": "",
            "note": hop_result.detail,
        }

    base["hop_platform_found"] = hop_result.platform or ""
    base["different_platform"] = "yes" if hop_result.differs_from_primary else "no"

    if not hop_result.differs_from_primary:
        return {
            **base,
            "outcome": "same_platform",
            "hand_check": "n/a",
            "meeting_url": "",
            "video_url": "",
            "tier": "",
            "page_url": "",
            "note": f"hit_url={hop_result.hit_url}",
        }

    await asyncio.sleep(HOST_DELAY_SECONDS)
    same_site = await _is_same_site_redirect(session, cand["domain"], verified_host)
    if same_site:
        return {
            **base,
            "outcome": "same_site_redirect",
            "hand_check": "n/a",
            "meeting_url": "",
            "video_url": "",
            "tier": "",
            "page_url": "",
            "note": "alternate's resolved final URL host matches the primary's",
        }

    _pending_tier3_candidate = None
    synthetic_row = {
        "gov_id": cand["gov_id"],
        "unit_name": cand["name"],
        "homepage": f"https://{verified_host}",
        "hop2_urls": "",
        "hit_source_urls": f"{hop_result.platform}={hop_result.hit_url}"
        if hop_result.platform and hop_result.hit_url
        else "",
        "_wo217_gov_id": cand["gov_id"],
        "_wo217_name": cand["name"],
        "_wo217_state": cand["state"],
        "_wo217_gov_kind": "municipality",
    }

    await asyncio.sleep(HOST_DELAY_SECONDS)
    try:
        result = await wo134.process_row(
            session, synthetic_row, covered_gov_ids, "wo217"
        )
    except Exception as e:  # noqa: BLE001
        return {
            **base,
            "outcome": "error",
            "hand_check": "n/a",
            "meeting_url": "",
            "video_url": "",
            "tier": "",
            "page_url": "",
            "note": f"process_row raised: {type(e).__name__}: {e}"[:300],
        }

    hand_check_verdict = get_last_verdict() or "n/a"

    if result.outcome == "ingested_tier1_2":
        return {
            **base,
            "outcome": "ingested_tier1_2",
            "hand_check": hand_check_verdict,
            "meeting_url": result.seed_url,
            "video_url": result.video_url,
            "tier": "1_2",
            "page_url": result.page_url,
            "note": result.reason,
        }

    if result.outcome == "queued_tier3_pending" and _pending_tier3_candidate:
        cand3 = _pending_tier3_candidate
        probe = await probe_queue_entry(
            cand3["meeting_url"],
            video_url=cand3.get("video_url") or None,
            source_page_url=cand3.get("source_url") or None,
        )
        append_probe_row(DEFAULT_SIDECAR_PATH, probe)

        if probe.verdict not in ("accept", "flag-long"):
            return {
                **base,
                "outcome": "rejected_by_probe",
                "hand_check": hand_check_verdict,
                "meeting_url": cand3["meeting_url"],
                "video_url": cand3["video_url"],
                "tier": "3",
                "page_url": "",
                "note": f"probe: {probe.reason}",
            }

        duration = probe.duration_seconds or 0
        if duration >= DEFER_OVER_SECONDS:
            hms = time.strftime("%H:%M:%S", time.gmtime(duration))
            line = f"{cand3['meeting_url']}\t\t{cand['gov_id']}\t{cand['name']}, {cand['state']}\t{hms}\tWO-217 found-alternate lead, over 90 min"
            with DEFERRED_FILE.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
            return {
                **base,
                "outcome": "deferred_long_meeting",
                "hand_check": hand_check_verdict,
                "meeting_url": cand3["meeting_url"],
                "video_url": cand3["video_url"],
                "tier": "3",
                "page_url": "",
                "note": f"{duration / 60:.0f} min, over the 90-min WO-217 cutoff -- parked in {DEFERRED_FILE.name}",
            }

        existing_queue_urls = wo134._existing_tier3_queue_urls()
        if cand3["meeting_url"] not in existing_queue_urls:
            queue_line = cand3["meeting_url"]
            if cand3.get("source_url"):
                queue_line = f"{queue_line}\t{cand3['source_url']}"
            with TIER3_QUEUE_FILE.open("a", encoding="utf-8") as f:
                f.write(queue_line + "\n")
        _apply_pin_row(cand3.get("pin_row"), existing_pin_keys)

        return {
            **base,
            "outcome": "queued_tier3",
            "hand_check": hand_check_verdict,
            "meeting_url": cand3["meeting_url"],
            "video_url": cand3["video_url"],
            "tier": "3",
            "page_url": "",
            "note": f"duration {duration / 60:.1f} min",
        }

    outcome_map = {
        "already_covered": "already_covered",
        "no_video_found": "lead_no_video",
        "skipped": "lead_no_video",
    }
    return {
        **base,
        "outcome": outcome_map.get(result.outcome, result.outcome),
        "hand_check": hand_check_verdict,
        "meeting_url": result.seed_url,
        "video_url": result.video_url,
        "tier": "",
        "page_url": result.page_url,
        "note": result.reason,
    }


def _guess_done_gov_ids() -> set:
    if not GUESS_DONE_TXT.exists():
        return set()
    return {ln.strip() for ln in GUESS_DONE_TXT.read_text().splitlines() if ln.strip()}


def _mark_guess_done(gov_id: str) -> None:
    with GUESS_DONE_TXT.open("a", encoding="utf-8") as f:
        f.write(gov_id + "\n")


def _rewrite_report_row(gov_id: str, new_row: dict) -> None:
    """Guess-only mode only: replaces the existing no_alternate_found row
    for `gov_id` in wo217_report.csv with `new_row` (guessing found
    something the first pass didn't). Whole-file rewrite -- the report is
    small enough (~720 rows) that this is cheap, and it keeps exactly one
    row per gov_id rather than appending a second, conflicting one."""
    with REPORT_CSV.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)
    replaced = False
    for i, r in enumerate(rows):
        if r["gov_id"] == gov_id:
            rows[i] = new_row
            replaced = True
            break
    if not replaced:
        rows.append(new_row)
    tmp = REPORT_CSV.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, REPORT_CSV)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory-csv", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--skip-guessing",
        action="store_true",
        help="only try local sources (fast, no per-row guess requests)",
    )
    parser.add_argument(
        "--guess-only",
        action="store_true",
        help=(
            "second-pass mode: only try guess patterns, only on rows the "
            "local-source pass already left no_alternate_found -- resumable via "
            f"{GUESS_DONE_TXT.name}, not the main report"
        ),
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not wo134._base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set.", file=sys.stderr
        )
        sys.exit(1)

    register_all_finders()

    jc_rows = load_jc_rows()
    covered_gov_ids = wo134._load_covered_gov_ids(args.inventory_csv)
    existing_pin_keys = _existing_override_keys()

    if args.guess_only:
        candidates_by_id = {c["gov_id"]: c for c in load_candidates()}
        with REPORT_CSV.open(newline="", encoding="utf-8") as f:
            report_rows = [
                r
                for r in csv.DictReader(f)
                if r.get("group") == "no_alternate_found"
                and r.get("outcome") == "no_alternate_found"
            ]
        print(
            f"{len(report_rows)} rows left no_alternate_found by the local-source pass."
        )
        if args.dry_run:
            return
        guess_done = _guess_done_gov_ids()
        print(
            f"{len(guess_done)} gov_ids already guess-attempted ({GUESS_DONE_TXT.name})."
        )
        to_process = [
            candidates_by_id[r["gov_id"]]
            for r in report_rows
            if r["gov_id"] in candidates_by_id and r["gov_id"] not in guess_done
        ]
        if args.limit:
            to_process = to_process[: args.limit]
        print(f"Guess-processing {len(to_process)} rows this run.")

        tally: Dict[str, int] = {}
        async with aiohttp.ClientSession() as session:
            for i, cand in enumerate(to_process):
                jc_row = jc_rows.get(cand["gov_id"], {})
                started = time.monotonic()
                try:
                    row_out = await process_one(
                        session,
                        cand,
                        jc_row,
                        covered_gov_ids,
                        existing_pin_keys,
                        skip_guessing=False,
                        guess_only=True,
                    )
                except Exception as e:  # noqa: BLE001
                    row_out = None
                    print(
                        f"[{i + 1}/{len(to_process)}] {cand['name']}, {cand['state']}: ERROR {e}"
                    )
                if row_out is not None:
                    elapsed = time.monotonic() - started
                    print(
                        f"[{i + 1}/{len(to_process)}] {cand['name']}, {cand['state']}: {row_out['outcome']} ({elapsed:.1f}s)"
                    )
                    if row_out["outcome"] != "no_alternate_found":
                        _rewrite_report_row(cand["gov_id"], row_out)
                    tally[row_out["outcome"]] = tally.get(row_out["outcome"], 0) + 1
                _mark_guess_done(cand["gov_id"])
                if i < len(to_process) - 1:
                    await asyncio.sleep(GOV_DELAY_SECONDS)

        print("\n--- Tally (this run, guess-only) ---")
        for k, v in sorted(tally.items()):
            print(f"{k:28} {v}")
        print(f"\nFull report: {REPORT_CSV}")
        return

    candidates = load_candidates()
    print(f"{len(candidates)} Group 2 (no_alternate) candidates.")
    if args.dry_run:
        return

    done = already_done_gov_ids()
    print(
        f"{len(done)} gov_ids already in {REPORT_CSV.name} (group=found_alternate|no_alternate_found)."
    )
    to_process = [c for c in candidates if c["gov_id"] not in done]
    if args.limit:
        to_process = to_process[: args.limit]
    print(f"Processing {len(to_process)} rows this run.")

    tally: Dict[str, int] = {}
    report_f, writer = report_writer()
    try:
        async with aiohttp.ClientSession() as session:
            for i, cand in enumerate(to_process):
                jc_row = jc_rows.get(cand["gov_id"], {})
                started = time.monotonic()
                try:
                    row_out = await process_one(
                        session,
                        cand,
                        jc_row,
                        covered_gov_ids,
                        existing_pin_keys,
                        args.skip_guessing,
                    )
                except Exception as e:  # noqa: BLE001
                    row_out = {
                        **_base_row(cand, jc_row),
                        "group": "no_alternate_found",
                        "alternate_tried": "",
                        "alternate_source": "",
                        "alternate_verified_by": "",
                        "hop_platform_found": "",
                        "different_platform": "",
                        "outcome": "error",
                        "hand_check": "n/a",
                        "meeting_url": "",
                        "video_url": "",
                        "tier": "",
                        "page_url": "",
                        "note": f"{type(e).__name__}: {e}"[:300],
                    }
                elapsed = time.monotonic() - started
                print(
                    f"[{i + 1}/{len(to_process)}] {cand['name']}, {cand['state']}: {row_out['outcome']} ({elapsed:.1f}s)"
                )
                writer.writerow(row_out)
                report_f.flush()
                tally[row_out["outcome"]] = tally.get(row_out["outcome"], 0) + 1
                if i < len(to_process) - 1:
                    await asyncio.sleep(GOV_DELAY_SECONDS)
    finally:
        report_f.close()

    print("\n--- Tally (this run) ---")
    for k, v in sorted(tally.items()):
        print(f"{k:28} {v}")
    print(f"\nFull report: {REPORT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
