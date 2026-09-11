#!/usr/bin/env python3
"""WO-150 (2026-09-10): access-ladder breadth sweep of 1,155 US/Canadian
municipalities over 5,000 people with no Archive page.

Candidate list: rtr-business/research/wo150_candidates.csv (population
descending). Goal per docs/BREADTH_SWEEP_BRIEF.md and CLAUDE.md: one
meeting WITH VIDEO per government, breadth not depth. Ryan's ingest rule
is absolute: only a meeting with real video becomes a page (tier 1/2,
with segments) or a tier-3 queue candidate (video, no reachable
captions, probed before queuing). Agenda-only is `no-video-found` /
`no-meetings-found` and is NEVER ingested, NEVER queued.

Reused, not rewritten:
  - `scripts/wo146_api_relist_sweep.py`'s `process_government()` for the
    "platform found -> enumerate (thorough) -> resolve -> pick best
    tier -> tenant-identity check -> ingest/queue" pipeline. That
    function already implements WO-146's tenant-identity gate
    (`_looks_wrong_government`) exactly as this WO's brief describes it.
    Imported, not copied; two module globals it reads
    (`_maybe_write_pin`, and the tier-3 pending note string) are
    monkeypatched below so provenance says wo150, not wo146.
  - `~/Documents/rtr-business/research/wo141_access_ladder_pilot.py`'s
    `HONEST_HEADERS`/`BROWSER_HEADERS`/`classify_body()`/
    `waf_family_from_headers()`/`CHALLENGE_MARKERS`/
    `SUBDOMAIN_LINK_PATTERN`/`MARKETING_SUBDOMAINS`/`PATH_SIGNATURES`/
    `try_headless()` for the access ladder itself -- this WO's own new
    work is wiring that ladder to a specific platform+host, since
    wo146's candidates already had `known_platform` set and wo150's
    mostly don't (534 no-platform-link-found, 256 dns-unresolvable, 108
    resolve-failed, 256 never tested).
  - `scripts/wo134_confirmed_hits_ingest.py`'s `_existing_tier3_queue_urls`,
    `_tenant_override_host`/`_tenant_override_match`, `SHARED_HOST_PLATFORMS`,
    `MAX_CONSECUTIVE_ERRORS`, `TENANT_OVERRIDES_CSV` (via wo146's own
    re-export).
  - `app/platforms/queue_probe.py`'s `probe_queue_entry()` (WO-144) for
    the tier-3 gate: every tier-3 candidate is probed before it is
    appended to `scripts/tier3_auto_transcription_queue.txt` -- a
    `reject-dead`/`reject-short` verdict never reaches the real queue.

READ-ONLY against rtr-discovery's real ledger (a scratch copy at
/tmp/wo150_ledger.db is used for enumerate/resolve). Writes: Archive
ingests via `POST /internal/ingest` (HTTP only, never a DB connection),
`scripts/tier3_auto_transcription_queue.txt` (dedupe-checked append),
`app/utils/jurisdiction_data/tenant_overrides.csv` (dedupe-checked
append), and this run's own report/seed/pending CSVs under
rtr-business/research/. Never writes jurisdiction_coverage.csv directly
-- see wo150_apply_to_jc.py for that, run separately per ENUMERATION_
METHODS.md §158.

Politeness: 2s between requests to one host, 1.5s between governments,
one headless browser at a time, stop after 6 consecutive real errors,
never retried past a human-verification challenge.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("RTR_DEEPLINK_PATH", str(REPO_ROOT))

import certifi  # noqa: E402

# Must precede `import aiohttp` anywhere in the process -- see
# CLAUDE.md's SSL_CERT_FILE bullet.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
import requests  # noqa: E402
from requests.exceptions import RequestException  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from scripts.bulk_ingest import _base_url  # noqa: E402
import scripts.wo134_confirmed_hits_ingest as w134  # noqa: E402
from scripts.wo134_confirmed_hits_ingest import (  # noqa: E402
    MAX_CONSECUTIVE_ERRORS,
    SHARED_HOST_PLATFORMS,
    TENANT_OVERRIDES_CSV,
    UNSUPPORTED_PLATFORMS,
    RowSkip,
    _dedup_key,
    _has_video,
    _looks_like_real_meeting,
    _tenant_override_host,
    _tenant_override_match,
    apply_display_jurisdiction,
    locate_platform_url,
    resolve_seed,
    youtube_oembed_title,
)
import scripts.wo146_api_relist_sweep as w146  # noqa: E402
from app.platforms import register_all_finders  # noqa: E402

# Real, confirmed-live bug found testing the known_platform fallback path
# below: `get_finder()` raises `UnsupportedPlatformError` for EVERY
# platform, including real ones like "youtube", until this has run once.
# `scripts/wo134_confirmed_hits_ingest.py` only calls it inside its own
# `main()` (guarded by `if __name__ == "__main__"`), so importing its
# functions directly -- as this script does -- never triggers it.
# w146.process_government()'s discovery-enumerator path never hit this
# because rtr-discovery's own resolve step registers what it needs
# separately; process_via_seed_resolve()'s direct `get_finder()` call
# does not.
register_all_finders()

# Real, confirmed-live bug found running this WO's first real batch
# (2026-09-10): 371 wo150 candidates already carry a `known_platform`
# from an earlier sweep, and rtr-discovery's ENUMERATORS dict doesn't
# use the same key spelling for all of them -- "youtube" (95 rows!) and
# "municode" (2 rows) aren't valid ENUMERATORS keys at all (the real
# keys are "youtube_channel"/"municode_meetings"), and several more
# (vimeo, champds, telvue, castus, civiclive) have NO rtr-discovery
# enumerator whatsoever -- discovery simply never built one for them.
# Feeding an unmapped platform string into w146.process_government()'s
# enumerate_candidates() call either silently enumerates nothing or (as
# happened live, Augusta-Richmond County GA, champds) raises a bare
# KeyError inside rtr-discovery's own tenant lookup. Per this WO's own
# instructions ("for platforms discovery cannot enumerate, use
# wo134_confirmed_hits_ingest.py's seed resolution"), anything not in
# rtr-discovery's real enumerator set goes through wo134's
# `resolve_seed()`/`locate_platform_url()` single-seed pipeline instead
# (process_via_seed_resolve() below) -- never rtr-discovery.
_KNOWN_PLATFORM_ALIASES = {
    "civicplus.com": "civicplus",
    "municode": "municode_meetings",
}
_DISCOVERY_ENUMERABLE_PLATFORMS = {
    "primegov",
    "civicclerk",
    "civicplus",
    "civicweb",
    "escribe",
    "legistar",
    "youtube_channel",
    "granicus",
    "swagit",
    "iqm2",
    "proudcity",
    "cablecast",
    "municode_meetings",
    "hyland",
}

DISCOVERY_ROOT = Path.home() / "Documents" / "rtr-discovery"
sys.path.insert(0, str(DISCOVERY_ROOT))
REAL_LEDGER = DISCOVERY_ROOT / "ledger.db"
SCRATCH_LEDGER = Path("/tmp/wo150_ledger.db")

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
CANDIDATES_CSV = RESEARCH_DIR / "wo150_candidates.csv"
REPORT_CSV = RESEARCH_DIR / "wo150_report.csv"
SEEDS_CSV = RESEARCH_DIR / "wo150_discovery_seeds.csv"
HOST_ACCESS_CSV = RESEARCH_DIR / "wo150_host_access_modes.csv"
TIER3_PENDING_CSV = RESEARCH_DIR / "wo150_tier3_pending.csv"
CONSOLIDATED_GOVS_CSV = (
    REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "consolidated_governments.csv"
)
DEFAULT_INVENTORY_CSV = Path("/tmp/wo150_inventory/meeting_inventory.csv")

REQUEST_DELAY_SECONDS = 1.5  # between governments
HOST_DELAY_SECONDS = 2.0  # between requests to the same host
MAX_CANDIDATES_TRIED = 6
ENUMERATE_TIMEOUT_SECONDS = 90
RESOLVE_TIMEOUT_SECONDS = 180
OUTER_TIMEOUT_SECONDS = 300
LADDER_TIMEOUT_SECONDS = 10

REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "country",
    "population",
    "prior_reason",
    "start_url",
    "host",
    "corrected_domain",
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
SEEDS_FIELDS = ["netloc", "platform", "gov_id", "access_mode"]
HOST_ACCESS_FIELDS = ["host", "access_mode", "waf_family"]
TIER3_PENDING_FIELDS = [
    "gov_id",
    "platform",
    "meeting_url",
    "video_url",
    "source_url",
    "jurisdiction",
    "pin_row",
]

# --- wo141's access-ladder pieces, imported from rtr-business/research ---
sys.path.insert(0, str(RESEARCH_DIR))
import wo141_access_ladder_pilot as ladder  # noqa: E402

# Vendor subdomain -> discovery platform key. wo141's SUBDOMAIN_LINK_PATTERN
# names the vendor word found in the URL; discovery's ENUMERATORS use a
# slightly different key for two of them.
_VENDOR_TO_PLATFORM = {
    "granicus": "granicus",
    "legistar": "legistar",
    "primegov": "primegov",
    "escribemeetings": "escribe",
    "iqm2": "iqm2",
    "civicweb": "civicweb",
    "civicclerk": "civicclerk",
    "swagit": "swagit",
    "viebit": None,  # no rtr-discovery enumerator for viebit yet
}
_PATH_SIGNATURE_PLATFORM = {
    r"/agendacenter/": "civicplus",
    r"viewpublisher\.php": "granicus",
    r"agendaviewer\.php": "granicus",
    r"legistar2\.com": "legistar",
}
_YOUTUBE_LINK_RE = re.compile(
    r"https?://(?:www\.)?youtube\.com/(?:channel/|c/|user/|@)[\w.-]+", re.I
)

MEETING_LINK_KEYWORDS = ("meeting", "agenda", "council", "video", "watch")
MEETING_LINK_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)


def _one_hop_links(html_text: str, base_url: str) -> list:
    """Links on the page whose href or anchor text names a meeting/
    agenda/council/video page -- the "one hop deeper" step 1 of the
    method describes."""
    out = []
    for m in MEETING_LINK_RE.finditer(html_text or ""):
        href = m.group(1)
        low = href.lower()
        if any(kw in low for kw in MEETING_LINK_KEYWORDS):
            try:
                out.append(urljoin(base_url, href))
            except Exception:  # noqa: BLE001
                continue
    # de-dupe, cap at 5 to stay polite
    seen = set()
    result = []
    for u in out:
        if u not in seen:
            seen.add(u)
            result.append(u)
        if len(result) >= 5:
            break
    return result


def _extract_platform_hit(text: str, final_url: str):
    """Returns (platform, host, hit_url) if classify_body found a
    platform_link, else (None, None, None)."""
    stripped = ladder.META_TAG_PATTERN.sub(" ", text)
    lower = stripped.lower()
    m = ladder.SUBDOMAIN_LINK_PATTERN.search(lower)
    if m and m.group(1) not in ladder.MARKETING_SUBDOMAINS:
        vendor_word = m.group(0).split("//", 1)[1].split("/", 1)[0].split(".", 1)[1]
        # vendor_word e.g. "granicus.com" -- take the word before ".com"
        vendor = vendor_word.split(".")[0]
        platform = _VENDOR_TO_PLATFORM.get(vendor)
        host = f"{m.group(1)}.{vendor}.com"
        if platform:
            return platform, host, f"https://{host}/"
    ym = _YOUTUBE_LINK_RE.search(text or "")
    if ym:
        return "youtube_channel", urlparse(ym.group(0)).netloc, ym.group(0)
    for pattern, platform in _PATH_SIGNATURE_PLATFORM.items():
        if re.search(pattern, lower):
            host = urlparse(final_url).netloc
            return platform, host, final_url
    return None, None, None


def _ensure_scheme(url: str) -> str:
    """Some `wo150_candidates.csv` rows carry `domain`/`hub_url` with a
    scheme already (https://www.toronto.ca), others as a bare hostname
    (fhgov.com) -- real, confirmed-live inconsistency found testing the
    known_platform fallback path. `urlparse`/aiohttp both mishandle a
    schemeless URL silently (empty netloc, failed fetch) rather than
    raising, so this has to be applied explicitly everywhere a raw CSV
    field becomes a fetch target."""
    url = (url or "").strip()
    if not url or "://" in url:
        return url
    return f"https://{url}"


def _domain_variants(domain: str) -> list:
    """A domain that didn't resolve: try www./bare and http/https before
    declaring dead. Order: as-given, https+www, http+bare, http+www."""
    parsed = urlparse(domain if "://" in domain else f"https://{domain}")
    host = parsed.netloc or parsed.path
    host = host.strip("/")
    bare = host[4:] if host.startswith("www.") else host
    withw = host if host.startswith("www.") else f"www.{host}"
    variants = [
        f"https://{host}/",
        f"https://{withw}/",
        f"http://{bare}/",
        f"http://{withw}/",
    ]
    seen = set()
    out = []
    for v in variants:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


class LadderOutcome:
    def __init__(self):
        self.access_mode = "dead"
        self.rung_answered = "none"
        self.platform = None
        self.host = None
        self.hit_url = None
        self.corrected_domain = ""
        self.waf_family = "none"
        self.reject_reason = "no-platform-link-found"
        self.reject_class = "content"
        self.note = ""


def _classify_and_hit(resp_text: str, final_url: str):
    cls = ladder.classify_body(resp_text)
    if cls == "platform_link":
        platform, host, hit_url = _extract_platform_hit(resp_text, final_url)
        if platform:
            return cls, platform, host, hit_url
        return "none", None, None, None
    return cls, None, None, None


def run_access_ladder(name: str, domain: str, start_url: str) -> LadderOutcome:
    out = LadderOutcome()
    session = requests.Session()
    tried_urls = [start_url] if start_url else []
    homepage = domain if "://" in domain else f"https://{domain}/"
    if homepage not in tried_urls:
        pass  # homepage tried only as a fallback, not up front

    def get(url, headers, session_obj=None):
        s = session_obj or session
        return s.get(
            url, headers=headers, timeout=LADDER_TIMEOUT_SECONDS, allow_redirects=True
        )

    # --- rung a: plain honest headers ---
    urls_to_try = list(tried_urls) or [homepage]
    resp = None
    last_exc = None
    used_url = None
    for url in urls_to_try:
        try:
            resp = get(url, ladder.HONEST_HEADERS)
            used_url = url
            break
        except RequestException as e:
            last_exc = e
            time.sleep(HOST_DELAY_SECONDS)
            continue

    if resp is None:
        # Whole domain unreachable at the given URL(s) -- try www/http variants.
        for variant in _domain_variants(domain):
            try:
                resp = get(variant, ladder.HONEST_HEADERS)
                used_url = variant
                out.corrected_domain = variant
                break
            except RequestException as e:
                last_exc = e
                time.sleep(HOST_DELAY_SECONDS)
                continue
        if resp is None:
            out.access_mode = "dead"
            out.reject_reason = "dns-unresolvable"
            out.reject_class = "access"
            out.note = f"no variant resolved: {last_exc}"
            return out

    if resp.status_code == 404 and used_url != homepage:
        # Stale research-file URL -- fall back to the homepage, still rung a.
        time.sleep(HOST_DELAY_SECONDS)
        try:
            resp = get(homepage, ladder.HONEST_HEADERS)
            used_url = homepage
        except RequestException as e:
            out.access_mode = "dead"
            out.reject_reason = "dns-unresolvable"
            out.reject_class = "access"
            out.note = f"homepage fallback failed: {e}"
            return out

    out.waf_family = ladder.waf_family_from_headers(
        dict(resp.headers), str(resp.headers.get("set-cookie", ""))
    )
    cls, platform, host, hit_url = _classify_and_hit(resp.text, used_url)
    if cls == "challenge":
        out.access_mode = "challenge"
        out.reject_reason = "cloudflare-challenge-blocked"
        out.reject_class = "access"
        out.note = f"challenge marker at rung plain ({used_url})"
        return out
    if platform:
        out.access_mode = "plain"
        out.rung_answered = "plain"
        out.platform = platform
        out.host = host
        out.hit_url = hit_url
        return out

    plain_blocked = resp.status_code == 403
    plain_reachable_text = resp.text if resp.status_code == 200 else ""

    # one hop deeper on rung a, if the page loaded
    if resp.status_code == 200:
        time.sleep(HOST_DELAY_SECONDS)
        for link in _one_hop_links(resp.text, used_url):
            try:
                r2 = get(link, ladder.HONEST_HEADERS)
            except RequestException:
                continue
            time.sleep(HOST_DELAY_SECONDS)
            cls2, platform2, host2, hit_url2 = _classify_and_hit(r2.text, link)
            if cls2 == "challenge":
                out.access_mode = "challenge"
                out.reject_reason = "cloudflare-challenge-blocked"
                out.reject_class = "access"
                out.note = f"challenge marker one hop deep ({link})"
                return out
            if platform2:
                out.access_mode = "plain"
                out.rung_answered = "plain"
                out.platform = platform2
                out.host = host2
                out.hit_url = hit_url2
                return out
            if r2.text:
                plain_reachable_text = plain_reachable_text or r2.text

    # --- rung b: browser headers, only after a 403 or dropped connection ---
    if plain_blocked:
        time.sleep(HOST_DELAY_SECONDS)
        try:
            r3 = requests.get(
                used_url,
                headers=ladder.BROWSER_HEADERS,
                timeout=LADDER_TIMEOUT_SECONDS,
                allow_redirects=True,
            )
        except RequestException as e:
            out.access_mode = "dead"
            out.reject_reason = "timeout"
            out.reject_class = "access"
            out.note = f"browser-headers request failed: {e}"
            return out
        cls3, platform3, host3, hit_url3 = _classify_and_hit(r3.text, used_url)
        if cls3 == "challenge":
            out.access_mode = "challenge"
            out.reject_reason = "cloudflare-challenge-blocked"
            out.reject_class = "access"
            out.note = "challenge marker at rung browser-headers"
            return out
        if platform3:
            out.access_mode = "browser-headers"
            out.rung_answered = "browser-headers"
            out.platform = platform3
            out.host = host3
            out.hit_url = hit_url3
            return out
        if r3.status_code == 403:
            out.access_mode = "browser-headers"
            out.reject_reason = "blocked-browser-headers"
            out.reject_class = "access"
            out.note = "still 403 under browser headers -- no headless (rule: never past a 403'd browser-headers host)"
            return out
        if r3.status_code == 200:
            plain_reachable_text = r3.text

    # --- rung c: headless, only for a reachable page with no visible link ---
    if plain_reachable_text or plain_blocked is False:
        time.sleep(HOST_DELAY_SECONDS)
        r4 = ladder.try_headless(used_url)
        if r4.error:
            out.access_mode = "plain" if not plain_blocked else "browser-headers"
            out.reject_reason = "no-platform-link-found"
            out.reject_class = "content"
            out.note = f"headless unavailable/failed: {r4.error}"
            return out
        if r4.classification == "challenge":
            out.access_mode = "challenge"
            out.reject_reason = "cloudflare-challenge-blocked"
            out.reject_class = "access"
            out.note = "challenge marker at rung headless"
            return out
        # headless doesn't tell us the exact vendor host from page.content()
        # alone as reliably via requests -- reuse the same text classifier.
        # try_headless() already ran classify_body(); redo the platform
        # extraction against nothing further -- no raw html retained, so
        # record listing-vs-platform_link only when wo141's classifier
        # itself returned platform_link (it scans the same subdomain
        # pattern internally).
        if r4.classification == "platform_link":
            out.access_mode = "headless"
            out.rung_answered = "headless"
            out.note = "headless found a platform_link classification but the raw content wasn't retained for host extraction -- see BACKLOG.md"
            out.reject_reason = "no-platform-link-found"
            out.reject_class = "content"
            return out
        out.access_mode = "headless"
        out.rung_answered = "headless"
        out.reject_reason = "no-platform-link-found"
        out.reject_class = "content"
        out.note = "headless loaded the page; still no meeting/platform link"
        return out

    out.reject_reason = "blocked-plain-http"
    out.reject_class = "access"
    out.note = f"plain rung status={resp.status_code}, no fallback rung reached"
    return out


# --- monkeypatch wo146's pin-writer + tier-3 note so provenance says wo150 ---
def _maybe_write_pin_wo150(platform, result_ns, final_seed, gov_id, unit_name):
    if DRY_RUN:
        return
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
                "source": "wo150_muni_ladder_sweep",
                "evidence": f"{unit_name} -- WO-150 muni ladder sweep, gov_id={gov_id}",
            }
        )


w146._maybe_write_pin = _maybe_write_pin_wo150

DRY_RUN = False

# docs/investigations/youtube_429_block.md: this Mac's address has been
# blocked for YouTube caption fetches (HTTP 429) and audio downloads
# ("Sign in to confirm you're not a bot") before. Per this WO's
# instructions: on the FIRST such signature seen in this run, stop every
# further YouTube-delegated call for the rest of the run and treat that
# candidate as tier-3 instead (video exists, captions just aren't
# reachable from here right now) rather than retrying.
YOUTUBE_BLOCKED = False
_YOUTUBE_BLOCK_SIGNATURES = (
    "429",
    "sign in to confirm you're not a bot",
    "youtubedlerror",
)
_YOUTUBE_PLATFORMS = {"youtube", "youtube_channel"}


def _looks_like_youtube_block(text: str) -> bool:
    low = (text or "").lower()
    return any(sig in low for sig in _YOUTUBE_BLOCK_SIGNATURES)


async def _fake_ingest_with_retry(session, payload, source_url):
    """--dry-run stand-in for wo134._ingest_with_retry: never POSTs to
    Archive. Ryan's video-only ingest gate is enforced upstream of this
    call (process_government only reaches it when payload has both
    segments and a video_url), so a dry run still proves the gate works
    -- it just fakes the network write."""
    return {"url": f"[DRY-RUN, not posted] {source_url}", "created": True}


_real_ingest_with_retry = w146._ingest_with_retry
_real_w134_ingest_with_retry = w134._ingest_with_retry


def set_dry_run(value: bool) -> None:
    global DRY_RUN
    DRY_RUN = value
    w146._ingest_with_retry = (
        _fake_ingest_with_retry if value else _real_ingest_with_retry
    )
    # process_via_seed_resolve() below calls w134._ingest_with_retry
    # directly (the non-discovery-enumerable-platform fallback path) --
    # needs the identical dry-run stand-in, not just w146's copy.
    w134._ingest_with_retry = (
        _fake_ingest_with_retry if value else _real_w134_ingest_with_retry
    )


async def process_via_seed_resolve(
    session: aiohttp.ClientSession,
    gov_id: str,
    name: str,
    state: str,
    gov_kind: str,
    platform: str,
    hit_url: str,
    homepage: str,
    hop2_urls: Optional[list] = None,
) -> dict:
    """The wo134 single-seed pipeline, for a platform rtr-discovery has
    no enumerator for (vimeo, telvue, champds, castus, civiclive, a bare
    "youtube" delegated video/channel) -- per this WO's own instructions.
    Deliberately NOT wo134.process_row() itself: that function posts to
    Archive and appends the real tier-3 queue file directly, with no
    dry-run hook and no probe-before-queue gate -- both would bypass
    this WO's own WO-144 tier-3 gate and --dry-run safety. This reuses
    wo134's real locate/resolve/classify logic but hands tier-3 off to
    the same `_pending_row` + probe flow as the discovery path."""
    base = {
        "netloc": "",
        "candidates_listed": 1,
        "candidates_tried": 0,
        "meeting_url": "",
        "video_url": "",
        "tier": "",
        "page_url": "",
        "outcome": "",
        "reject_reason": "",
        "reject_class": "",
        "note": "",
        "_pending_row": None,
    }

    seed_url, reason = await locate_platform_url(
        session, platform, hit_url, hop2_urls or [], homepage
    )
    if not seed_url:
        base["outcome"] = "no_platform_link_found"
        base["reject_reason"] = "no-platform-link-found"
        base["reject_class"] = "content"
        base["note"] = f"{platform}: {reason}"
        return base

    base["netloc"] = urlparse(seed_url).netloc
    base["candidates_tried"] = 1
    try:
        result, final_seed, high_risk_title = await resolve_seed(
            session, platform, seed_url
        )
    except w134.ProbeRejected as e:
        # WO-169: resolve_seed() now probes each tier-3 candidate itself
        # and only raises this once every candidate for this platform hit
        # is exhausted (see w134.PROBE_HOOK's own comment) -- a real video
        # existed here, so this gets its own outcome/reason rather than
        # folding into no_video_found, and keeps the URLs the exception
        # carries instead of dropping them (WO-151's own finding).
        base["outcome"] = "rejected_by_probe"
        base["reject_reason"] = "rejected_by_probe"
        base["reject_class"] = "content"
        base["note"] = f"{platform}: {e}"
        base["meeting_url"] = e.meeting_url or seed_url
        base["video_url"] = e.video_url
        return base
    except RowSkip as e:
        base["outcome"] = "no_video_found"
        base["reject_reason"] = "no-video-found"
        base["reject_class"] = "content"
        base["note"] = f"{platform}: {e}"
        # WO-169: RowSkip now carries real URL evidence even on a skip
        # (see RowSkip's own docstring in wo134_confirmed_hits_ingest.py)
        # -- keep it instead of leaving these blank, the exact gap WO-151
        # found. seed_url is still a real fallback: locate_platform_url()
        # already found a real listing/page even when resolve_seed()
        # itself never got as far as a specific meeting.
        base["meeting_url"] = e.meeting_url or seed_url
        base["video_url"] = e.video_url
        return base
    except Exception as e:  # noqa: BLE001
        base["outcome"] = "error"
        base["note"] = f"{platform}: resolve raised: {e!r}"
        return base

    segments = result.segments or []
    agenda_items = result.agenda_items or []
    if not (segments or agenda_items or result.agenda_link or result.video_url):
        base["outcome"] = "no_meetings_found"
        base["reject_reason"] = "no-meetings-found"
        base["reject_class"] = "content"
        base["note"] = (
            f"{platform}: resolved but no transcript/agenda/video ({final_seed})"
        )
        return base

    key = _dedup_key(result)
    if key in w134._seen_keys:
        base["outcome"] = "skipped"
        base["reject_reason"] = "off-mission"
        base["reject_class"] = "content"
        base["note"] = f"duplicate of an already-processed meeting this run ({key})"
        return base

    effective_title = result.title or ""
    if not effective_title and result.video_url:
        oembed_title = await youtube_oembed_title(session, result.video_url)
        if oembed_title:
            effective_title = oembed_title
    if not _looks_like_real_meeting(effective_title, require_allowlist=high_risk_title):
        base["outcome"] = "skipped"
        base["reject_reason"] = "off-mission"
        base["reject_class"] = "content"
        base["note"] = (
            f"title looks like a non-meeting video, not ingested: {effective_title!r}"
        )
        return base

    # Tenant-identity check BEFORE any jurisdiction default is applied --
    # same reasoning as w146.process_government(): a default fills in
    # OUR OWN believed identity and would just confirm itself.
    payload_for_check = result.model_dump()
    mismatch = w146._looks_wrong_government(
        {"state": state, "gov_kind": gov_kind}, payload_for_check
    )
    if mismatch:
        reject_reason = (
            "same-name-same-state-ambiguous"
            if "same-name city/county collision" in mismatch
            else "wrong-domain-mapping"
        )
        base["outcome"] = "skipped"
        base["reject_reason"] = reject_reason
        base["reject_class"] = "content"
        base["note"] = mismatch
        return base

    if not _has_video(result):
        base["outcome"] = "no_video_found"
        base["reject_reason"] = "no-video-found"
        base["reject_class"] = "content"
        base["note"] = (
            f"{platform}: resolved real agenda content, no video found ({final_seed})"
        )
        return base

    apply_display_jurisdiction(result, gov_id)
    payload = result.model_dump()
    # WO-222: this row already knows its government -- send it in the
    # payload so a page on a shared host never depends on a
    # tenant_overrides.csv pin reaching production first. See
    # scripts/wo134_confirmed_hits_ingest.py's matching comment and
    # docs/COVERAGE_HANDOVER.md §3.
    if gov_id:
        payload["gov_id"] = gov_id
    base["meeting_url"] = final_seed
    base["video_url"] = payload.get("video_url") or ""

    if segments:
        w134._seen_keys.add(key)
        if platform in SHARED_HOST_PLATFORMS:
            _maybe_write_pin_wo150(platform, result, final_seed, gov_id, name)
        try:
            response = await w134._ingest_with_retry(session, payload, final_seed)
        except Exception as e:  # noqa: BLE001
            base["outcome"] = "error"
            base["note"] = f"{platform}: ingest raised: {e!r}"
            return base
        if response is None:
            base["outcome"] = "error"
            base["note"] = f"{platform}: POST to Archive failed twice: {final_seed}"
            return base
        base["outcome"] = "ingested_tier1_2"
        base["tier"] = "1/2"
        base["page_url"] = response.get("url") or ""
        base["note"] = f"{len(segments)} transcript segments"
        return base

    # Tier 3: real video, no reachable captions -- pending file only,
    # same probe-before-queue gate as the discovery path.
    w134._seen_keys.add(key)
    base["outcome"] = "queued_tier3_pending"
    base["tier"] = "3"
    pin_row = ""
    if platform in SHARED_HOST_PLATFORMS:
        host = _tenant_override_host(platform, result, final_seed)
        match = _tenant_override_match(platform, result, final_seed)
        if host and match:
            pin_row = (
                f"tenant_host={host};match={match};gov_id={gov_id};"
                f"strength=fallback;source=wo150_muni_ladder_sweep"
            )
    base["note"] = "written to wo150_tier3_pending.csv, awaiting probe (WO-144)"
    base["_pending_row"] = {
        "gov_id": gov_id,
        "platform": platform,
        "meeting_url": final_seed,
        "video_url": payload.get("video_url") or "",
        "source_url": payload.get("source_url") or "",
        "jurisdiction": payload.get("jurisdiction") or "",
        "pin_row": pin_row,
    }
    return base


def _load_consolidated_canonical() -> dict:
    """county-form gov_id -> canonical (city) gov_id."""
    m = {}
    if CONSOLIDATED_GOVS_CSV.exists():
        with CONSOLIDATED_GOVS_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("gov_id") and r.get("canonical_gov_id"):
                    m[r["gov_id"]] = r["canonical_gov_id"]
    return m


def _read_csv_rows(path: Path) -> list:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _already_done_gov_ids(path: Path) -> set:
    return {r["gov_id"] for r in _read_csv_rows(path) if r.get("gov_id")}


def _csv_writer(path: Path, fields_: list):
    is_new = not path.exists()
    f = path.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=fields_, lineterminator="\n")
    if is_new:
        w.writeheader()
        # Real, confirmed-live bug (2026-09-10): a hard `kill` of this
        # process before the first data row for a given output file (the
        # tier-3 pending file specifically, since it can go many rows
        # without a single tier-3 candidate) left the header sitting in
        # this file object's own write buffer, never reaching disk --
        # `path.exists()` still returned True on the next run (open() in
        # "a" mode creates the file immediately), so `is_new` came back
        # False and no header was ever written, corrupting the first
        # real data row into looking like a header to any later reader
        # (`csv.DictReader`). Flush immediately so the header is durable
        # the instant it's written, not just before this run's own
        # graceful exit.
        f.flush()
    return f, w


def ensure_scratch_ledger() -> None:
    if not SCRATCH_LEDGER.exists():
        shutil.copy2(REAL_LEDGER, SCRATCH_LEDGER)
        print(f"copied {REAL_LEDGER} -> {SCRATCH_LEDGER}")


def _append_tier3_queue(url: str, hit_url: str, existing: set) -> bool:
    if url in existing:
        return False
    line = f"{url}\t{hit_url}" if hit_url and hit_url != url else url
    from scripts.wo134_confirmed_hits_ingest import TIER3_QUEUE_FILE

    with TIER3_QUEUE_FILE.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    existing.add(url)
    return True


async def process_row(
    ledger,
    row: dict,
    covered_gov_ids: set,
    canonical_map: dict,
    session: aiohttp.ClientSession,
    host_access_cache: dict,
) -> dict:
    global YOUTUBE_BLOCKED
    gov_id = row["gov_id"]
    name = row["name"]
    state = row["state"]
    country = row.get("country", "")
    population = row.get("population", "")
    domain = row.get("domain", "") or ""
    known_platform = (row.get("known_platform") or "").strip().lower()
    hub_url = row.get("hub_url") or ""
    prior_reason = row.get("reject_reason") or row.get("prior_reason") or ""
    research_calendar_url = row.get("research_calendar_url") or ""
    research_meeting_url = row.get("research_meeting_url") or ""

    base = {k: "" for k in REPORT_FIELDS}
    base.update(
        {
            "gov_id": gov_id,
            "name": name,
            "state": state,
            "country": country,
            "population": population,
            "prior_reason": prior_reason,
        }
    )

    # already_covered via fresh export or a county-form canonical mapping
    canonical = canonical_map.get(gov_id)
    if gov_id in covered_gov_ids or (canonical and canonical in covered_gov_ids):
        base["outcome"] = "already_covered"
        base["note"] = "gov_id (or its canonical city id) already has a page"
        return base

    start_url = research_calendar_url or research_meeting_url or hub_url or domain
    base["start_url"] = start_url
    host = urlparse(start_url if "://" in start_url else f"https://{start_url}").netloc
    base["host"] = host

    if known_platform:
        platform = _KNOWN_PLATFORM_ALIASES.get(known_platform, known_platform)
        plat_domain = _ensure_scheme(hub_url or domain)
        base["access_mode"] = "api"
        base["rung_answered"] = "none"
        base["platform_found"] = platform
    else:
        cached = host_access_cache.get(host)
        if cached in ("challenge", "dead"):
            # Remember the answer per host (method step 2): a host already
            # seen to be a hard challenge/dead this run isn't worth a
            # second full ladder walk -- two governments rarely share a
            # host, but a corrected-domain retry or a shared vendor
            # marketing host could.
            outcome = LadderOutcome()
            outcome.access_mode = cached
            outcome.reject_reason = (
                "cloudflare-challenge-blocked"
                if cached == "challenge"
                else "dns-unresolvable"
            )
            outcome.reject_class = "access"
            outcome.note = f"host {host} already answered {cached!r} earlier this run -- not re-tried"
        else:
            outcome = await asyncio.to_thread(
                run_access_ladder, name, domain, start_url
            )
        base["access_mode"] = outcome.access_mode
        base["rung_answered"] = outcome.rung_answered
        base["corrected_domain"] = outcome.corrected_domain
        base["waf_family"] = outcome.waf_family
        base["platform_found"] = outcome.platform or ""
        base["hit_url"] = outcome.hit_url or ""
        base["note"] = outcome.note
        host_access_cache[host] = outcome.access_mode
        if not outcome.platform:
            base["outcome"] = (
                "blocked"
                if outcome.reject_class == "access"
                else "no_platform_link_found"
            )
            base["reject_reason"] = outcome.reject_reason
            base["reject_class"] = outcome.reject_class
            return base
        platform = outcome.platform
        plat_domain = outcome.host or ""

    if platform in _YOUTUBE_PLATFORMS and YOUTUBE_BLOCKED:
        base["outcome"] = "skipped"
        base["reject_reason"] = "youtube-429-block-active"
        base["reject_class"] = "access"
        base["note"] = (
            "this Mac's address hit a YouTube caption/download block earlier "
            "in this run (docs/investigations/youtube_429_block.md) -- skipping "
            "further YouTube-delegated calls for the rest of the run"
        )
        return base

    if platform in UNSUPPORTED_PLATFORMS:
        base["outcome"] = "no_platform_link_found"
        base["reject_reason"] = "unsupported-platform-no-adapter"
        base["reject_class"] = "content"
        base["platform_found"] = platform
        base["note"] = f"{platform}: no video adapter in this repo"
        return base

    if platform not in _DISCOVERY_ENUMERABLE_PLATFORMS:
        # rtr-discovery has no enumerator for this platform (vimeo,
        # telvue, champds, castus, civiclive, a bare "youtube" delegated
        # video/channel) -- single-seed resolve via the real adapter
        # instead, per this WO's own instructions.
        base["platform_found"] = platform
        try:
            seed_result = await asyncio.wait_for(
                process_via_seed_resolve(
                    session,
                    gov_id,
                    name,
                    state,
                    row.get("gov_kind", ""),
                    platform,
                    plat_domain or start_url,
                    _ensure_scheme(domain),
                    hop2_urls=[
                        u
                        for u in (
                            research_calendar_url,
                            research_meeting_url,
                            start_url,
                        )
                        if u
                    ],
                ),
                timeout=OUTER_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            base["outcome"] = "error"
            base["reject_reason"] = "timeout"
            base["reject_class"] = "access"
            base["note"] = f"process_via_seed_resolve exceeded {OUTER_TIMEOUT_SECONDS}s"
            return base
        except Exception as exc:  # noqa: BLE001
            base["outcome"] = "error"
            base["note"] = f"process_via_seed_resolve raised: {exc!r}"
            return base
        pending_row = seed_result.pop("_pending_row", None)
        outcome_map = {"queued_tier3_pending": "queued_tier3"}
        base["outcome"] = outcome_map.get(
            seed_result["outcome"], seed_result["outcome"]
        )
        for k in (
            "netloc",
            "reject_reason",
            "reject_class",
            "candidates_listed",
            "candidates_tried",
            "meeting_url",
            "video_url",
            "tier",
            "page_url",
            "note",
        ):
            base[k] = seed_result.get(k, base.get(k, ""))
        base["_pending_row"] = pending_row
        if base["access_mode"] != "challenge":
            base["access_mode"] = base["access_mode"] or "api"
        return base

    synthetic = {
        "gov_id": gov_id,
        "name": name,
        "state": state,
        "gov_kind": row.get("gov_kind", ""),
        "population": population,
        "platform": platform,
        "domain": plat_domain,
        "hub_url": "",
        "prior_reject_reason": prior_reason,
    }
    try:
        w146_result = await asyncio.wait_for(
            w146.process_government(ledger, synthetic, covered_gov_ids, {}, session),
            timeout=OUTER_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        base["outcome"] = "error"
        base["reject_reason"] = "timeout"
        base["reject_class"] = "access"
        base["note"] = f"process_government exceeded {OUTER_TIMEOUT_SECONDS}s"
        return base
    except Exception as exc:  # noqa: BLE001
        base["outcome"] = "error"
        base["note"] = f"process_government raised: {exc!r}"
        return base

    if (
        platform in _YOUTUBE_PLATFORMS
        and not YOUTUBE_BLOCKED
        and _looks_like_youtube_block(w146_result.get("note") or "")
    ):
        YOUTUBE_BLOCKED = True
        w146_result["note"] = (
            w146_result.get("note") or ""
        ) + " -- YOUTUBE BLOCK SIGNATURE SEEN; stopping further YouTube calls this run"

    pending_row = w146_result.pop("_pending_row", None)
    outcome_map = {
        "ingested_tier1_2": "ingested_tier1_2",
        "queued_tier3_pending": "queued_tier3",
        "no_video_found": "no_video_found",
        "no_meetings_found": "no_meetings_found",
        "already_covered": "already_covered",
        "error": "error",
        "skipped": "skipped",
    }
    base["outcome"] = outcome_map.get(
        w146_result.get("outcome"), w146_result.get("outcome") or "error"
    )
    base["netloc"] = w146_result.get("netloc") or ""
    base["reject_reason"] = w146_result.get("reject_reason") or ""
    base["reject_class"] = w146_result.get("reject_class") or ""
    base["candidates_listed"] = w146_result.get("candidates_listed") or 0
    base["candidates_tried"] = w146_result.get("candidates_tried") or 0
    base["meeting_url"] = w146_result.get("meeting_url") or ""
    base["video_url"] = w146_result.get("video_url") or ""
    base["tier"] = w146_result.get("tier") or ""
    base["page_url"] = w146_result.get("page_url") or ""
    note = w146_result.get("note") or ""

    # Ryan's WO-146 same-name-same-state-ambiguous distinction: wo146's
    # own mismatch check folds both "different state" (a real
    # wrong-domain-mapping) and "same state, different kind" (a real
    # ambiguity, not a mismatch) into one reject_reason. Split them here.
    if (
        base["reject_reason"] == "wrong-domain-mapping"
        and "same-name city/county collision" in note
    ):
        base["reject_reason"] = "same-name-same-state-ambiguous"

    base["note"] = note.replace("wo146_api_relist", "wo150_muni_ladder_sweep").replace(
        "wo146_tier3_pending.csv", "wo150_tier3_pending.csv"
    )
    base["_pending_row"] = pending_row
    if base["access_mode"] != "challenge":
        base["access_mode"] = base["access_mode"] or "api"
    return base


async def main_async(limit: Optional[int], only_reasons: Optional[list]) -> None:
    from discovery.ledger import Ledger
    from discovery import config as discovery_config

    discovery_config.load_env()
    ensure_scratch_ledger()
    ledger = Ledger(str(SCRATCH_LEDGER))

    covered = w146._load_covered_gov_ids(DEFAULT_INVENTORY_CSV)
    print(f"{len(covered)} gov_ids already have an archived page (fresh export).")
    canonical_map = _load_consolidated_canonical()

    all_rows = _read_csv_rows(CANDIDATES_CSV)
    print(f"{len(all_rows)} candidate rows in {CANDIDATES_CSV.name}")

    suffix = "_dryrun" if DRY_RUN else ""
    report_csv = RESEARCH_DIR / f"wo150_report{suffix}.csv"
    seeds_csv = RESEARCH_DIR / f"wo150_discovery_seeds{suffix}.csv"
    host_csv = RESEARCH_DIR / f"wo150_host_access_modes{suffix}.csv"
    pending_csv = RESEARCH_DIR / f"wo150_tier3_pending{suffix}.csv"

    done = _already_done_gov_ids(report_csv)
    print(f"{len(done)} gov_ids already in {report_csv.name} -- skipping those.")

    to_process = [r for r in all_rows if r["gov_id"] not in done]
    if only_reasons:
        to_process = [
            r for r in to_process if r.get("reject_reason", "") in only_reasons
        ]
    if limit:
        to_process = to_process[:limit]
    print(
        f"Processing {len(to_process)} government(s) against {_base_url()}{' [DRY RUN]' if DRY_RUN else ''}...\n"
    )

    if not _base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (check .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    report_f, report_w = _csv_writer(report_csv, REPORT_FIELDS)
    seeds_f, seeds_w = _csv_writer(seeds_csv, SEEDS_FIELDS)
    host_f, host_w = _csv_writer(host_csv, HOST_ACCESS_FIELDS)
    pending_f, pending_w = _csv_writer(pending_csv, TIER3_PENDING_FIELDS)

    tally: dict = {}
    consecutive_errors = 0
    seeded_netlocs = set()
    if seeds_csv.exists():
        with seeds_csv.open(newline="", encoding="utf-8") as f:
            seeded_netlocs = {r["netloc"] for r in csv.DictReader(f) if r.get("netloc")}
    seeded_hosts = set()
    if host_csv.exists():
        with host_csv.open(newline="", encoding="utf-8") as f:
            seeded_hosts = {r["host"] for r in csv.DictReader(f) if r.get("host")}
    host_access_cache: dict = {}

    try:
        async with aiohttp.ClientSession() as session:
            for i, row in enumerate(to_process):
                result = await process_row(
                    ledger, row, covered, canonical_map, session, host_access_cache
                )
                pending_row = result.pop("_pending_row", None)
                is_real_error = result["outcome"] == "error"
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
                            "platform": result.get("platform_found") or "",
                            "gov_id": result["gov_id"],
                            "access_mode": result["access_mode"],
                        }
                    )
                    seeds_f.flush()
                    seeded_netlocs.add(netloc)

                host = result.get("host") or ""
                if host and host not in seeded_hosts:
                    host_w.writerow(
                        {
                            "host": host,
                            "access_mode": result.get("access_mode") or "",
                            "waf_family": result.get("waf_family") or "",
                        }
                    )
                    host_f.flush()
                    seeded_hosts.add(host)

                tally[result["outcome"]] = tally.get(result["outcome"], 0) + 1
                print(
                    f"[{i + 1}/{len(to_process)}] [{result['outcome']:22}] "
                    f"{result['gov_id']} {result['name']!r} ({result.get('platform_found', '')}, "
                    f"{netloc}) -- {result.get('note', '')[:120]}"
                )

                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(
                        f"\nABORTING: {consecutive_errors} consecutive real errors -- stopping. Re-run to resume.",
                        file=sys.stderr,
                    )
                    break
                if i < len(to_process) - 1:
                    await asyncio.sleep(REQUEST_DELAY_SECONDS)
    finally:
        report_f.close()
        seeds_f.close()
        host_f.close()
        pending_f.close()
        ledger.conn.commit()
        ledger.close()

    print("\n--- Tally (this run) ---")
    for outcome, count in sorted(tally.items()):
        print(f"{outcome:22} {count}")
    print(f"\nFull report: {report_csv}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--only-reasons",
        type=str,
        default=None,
        help="comma-separated reject_reason filter, e.g. 'no-platform-link-found,dns-unresolvable'",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run the full ladder+enumerate+resolve pipeline but never POST to "
        "/internal/ingest or write a tenant_overrides.csv pin -- prints what "
        "WOULD happen. Use this to verify Ryan's video-only ingest gate before "
        "the first real run.",
    )
    args = parser.parse_args()
    set_dry_run(args.dry_run)
    only = args.only_reasons.split(",") if args.only_reasons else None
    asyncio.run(main_async(args.limit, only))


if __name__ == "__main__":
    main()
