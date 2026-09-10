"""WO-151 (2026-09-10): access-ladder sweep of 1,026 governments from the
research file's own meetings-page URLs, at every population.

Candidate list: rtr-business/research/wo151_candidates.csv -- 1,026
governments with no Archive page, each carrying a real
`research_calendar_url`/`research_meeting_url` an earlier, plain-client
pass tested (990 rejected `no-platform-link-found`, 30 `untested`, 6
`resolve-failed`). Goal, per docs/BREADTH_SWEEP_BRIEF.md: one meeting
WITH VIDEO per government, breadth not depth. Ryan's ingest rule is
absolute: only a meeting with real video becomes a page or a tier-3
queue entry; agenda-only is recorded and never ingested.

This is deliberately NOT a fourth ladder implementation from scratch.
Two already-merged scripts do almost everything this WO needs, and this
script is a driver that reuses them directly rather than copying them:

  * `scripts/hub_sweep_wo126.py` (WO-126) already walks a single
    "hub" URL end to end -- fetch, detect a direct platform hit, scan for
    a platform link, follow one hop of meeting/agenda/council/video-
    shaped links, walk a CivicPlus AgendaCenter's year fragments, resolve
    the best lead, and (via `act_on_resolved`) tier/dedupe/key-check/
    ingest-or-queue it. `hs.process_gov`/`hs._process_gov`, `Gov`,
    `Found`, `Result`, `Fetcher`, `FetchError`, `Skip`, `DedupeIndex`,
    `civicplus_walk`, `_platform_links`, `_hint_links`, `key_check`,
    `pin_for`, `stage_pin`, `write_pins`, `hub_kind_of` are imported and
    used as-is.
  * `scripts/wo145_api_first_sweep.py` (WO-145) built the four wrong-
    government checks Ryan asked to reuse here: `_state_or_kind_conflict`
    (cross-jurisdiction / wrong-kind), `_title_place_conflict` (vendor-
    demo tenant), `_cross_border_collision` (US-vs-Canada name
    collision), plus `STATE_NAMES`/`_name_tokens`. `hub_sweep_wo126`'s own
    `key_check`/`pin_for` do something different (would this URL key to
    the right gov_id, and if not, stage a pin) -- they never REFUSE to
    ingest a page that is actually about a different real government, the
    exact bug class WO-145/146/162 found and fixed. This script inserts
    WO-145's checks into its own copy of `act_on_resolved`, below.
  * `wo141_access_ladder_pilot.py` (rtr-business/research, WO-141)
    supplies `HONEST_HEADERS`/`BROWSER_HEADERS`/`CHALLENGE_MARKERS`,
    imported via sys.path (it lives outside this repo).
  * `app/platforms/queue_probe.py` (WO-144, merged) supplies
    `probe_queue_entry()`/`append_probe_row()` -- every tier-3 candidate
    is probed before it reaches the real queue, which `hub_sweep_wo126`
    predates and does not do on its own; this script's own
    `act_on_resolved_wo151` adds that gate.

What this script adds that neither reused script has on its own:

  1. **Multiple start URLs, in order** (`research_calendar_url`, then
     `research_meeting_url`, then `domain`) -- `hs._process_gov` only
     ever tries the one `gov.hub_url` it's given. A 404 on one falls
     back to the next (a 404 means a stale URL, not a dead host); a
     403/dropped-connection retries once with browser headers (see #2);
     a human-verification challenge stops the whole government, no
     further start URL is tried.
  2. **A browser-header retry rung.** `hs.Fetcher.get()` only ever sends
     one header set. `LadderFetcher` (below) subclasses it to retry once
     with `BROWSER_HEADERS` after a 403 or a dropped connection, never
     after a 404 -- then is monkeypatched over `hs.Fetcher` so every
     fetch this run makes, including the ones inside `hs._process_gov`/
     `hs.civicplus_walk`, gets the same rung automatically.
  3. **A headless rung** for a host that returned a real page (rung a or
     b) with no visible meeting link -- genuinely new; neither
     `hub_sweep_wo126` nor `wo145_api_first_sweep` implements this (both
     say so in their own docstrings). One Playwright browser, one host
     at a time, real delay, capped at `HEADLESS_BUDGET` renders for the
     whole run (documented in this WO's own report as a scope decision,
     not silently skipped) -- see `headless_discover()`.
  4. **Probe before queue** (`act_on_resolved_wo151`, monkeypatched over
     `hs.act_on_resolved`): a tier-3 candidate is probed
     (`probe_queue_entry`) before it is appended to the real
     `tier3_auto_transcription_queue.txt` -- `hub_sweep_wo126` appends
     directly, predating WO-144.
  5. **already_covered via a fresh export AND `consolidated_governments.csv`**:
     a county-form gov_id listed there keys to the same government as its
     city id (PR #842) -- any candidate whose gov_id appears there is
     `already_covered` without an adapter call, per CLAUDE.md.

Usage (repo root, discovery's own venv -- the shared deeplink .venv
cannot import `discovery`; not needed here since this script does not
call rtr-discovery's own enumerators, only the real rtr-deeplink
adapters `hub_sweep_wo126` already imports):

    DATABASE_URL="sqlite+aiosqlite:////tmp/wo151_scratch.db" \\
    python scripts/export_meeting_inventory.py --out-dir /tmp/wo151_inventory --source export
    python scripts/wo151_research_url_ladder_sweep.py --pilot 30
    python scripts/wo151_research_url_ladder_sweep.py            # full run, resumes

Resumable: `rtr-business/research/wo151_report.csv` is flushed one row
at a time; a gov_id already present there is skipped on re-run.

Politeness: one government at a time, `hs.REQUEST_DELAY_SECONDS` (1.5s)
between governments, `hs.Fetcher`'s own delay between fetches to one
host, one headless browser at a time, never past a challenge, halts
after `MAX_CONSECUTIVE_ERRORS` consecutive real errors.
"""

import argparse
import asyncio
import csv
import os
import socket
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("RTR_DEEPLINK_PATH", str(REPO_ROOT))

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.queue_probe import (  # noqa: E402
    DEFAULT_SIDECAR_PATH,
    append_probe_row,
    probe_queue_entry,
)
from app.utils.url_normalize import normalize_url  # noqa: E402
from scripts.bulk_ingest import _base_url  # noqa: E402

import scripts.hub_sweep_wo126 as hs  # noqa: E402
from scripts.wo145_api_first_sweep import (  # noqa: E402
    _cross_border_collision,
    _state_or_kind_conflict,
    _title_place_conflict,
)

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
CANDIDATES_CSV = RESEARCH_DIR / "wo151_candidates.csv"
REPORT_CSV = RESEARCH_DIR / "wo151_report.csv"
SEEDS_CSV = RESEARCH_DIR / "wo151_discovery_seeds.csv"
HOST_ACCESS_CSV = RESEARCH_DIR / "wo151_host_access_modes.csv"
TIER3_PENDING_CSV = RESEARCH_DIR / "wo151_tier3_pending.csv"
EXPORT_JSON = RESEARCH_DIR / "wo151_export_pages.json"
CONSOLIDATED_CSV = (
    REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "consolidated_governments.csv"
)
DEFAULT_INVENTORY_CSV = Path("/tmp/wo151_inventory/meeting_inventory.csv")

# This run's own attribution -- distinct from hub_sweep_wo126's own
# PIN_SOURCE/PINS_CSV, so a pin/report row always says which work order
# actually found it.
hs.PIN_SOURCE = "wo151_research_url_ladder_sweep"
hs.PINS_CSV = RESEARCH_DIR / "wo151_pins.csv"

MAX_CONSECUTIVE_ERRORS = 6
HEADLESS_BUDGET = 150  # whole-run cap; see module docstring point 3

# --- wo141_access_ladder_pilot.py, imported via sys.path (lives outside
# this repo, in rtr-business/research) -----------------------------------
sys.path.insert(0, str(RESEARCH_DIR))
import wo141_access_ladder_pilot as ladder_pilot  # noqa: E402

HONEST_HEADERS = ladder_pilot.HONEST_HEADERS
BROWSER_HEADERS = ladder_pilot.BROWSER_HEADERS
CHALLENGE_MARKERS = ladder_pilot.CHALLENGE_MARKERS
waf_family_from_headers = ladder_pilot.waf_family_from_headers


# --------------------------------------------------------------------------
# Candidate row -> a Gov-shaped object (duck-typed: hub_sweep_wo126's
# Gov, key_check, pin_for, act_on_resolved only ever access attributes,
# never isinstance() -- so a superset dataclass with the extra fields
# WO-145's wrong-government checks need (gov_kind, country) passes
# through both modules' functions unmodified).
# --------------------------------------------------------------------------


@dataclass
class Cand151:
    gov_id: str
    name: str
    state: str
    country: str
    gov_kind: str
    population: str
    domain: str
    known_platform: str
    prior_reason: str
    research_calendar_url: str
    research_meeting_url: str
    hub_url: str = ""  # set per-attempt

    @property
    def jurisdiction(self) -> str:
        return f"{self.name}, {self.state}"

    # hub_sweep_wo126.Gov's own field name for the same thing.
    @property
    def prior_reject_reason(self) -> str:
        return self.prior_reason


def load_candidates() -> List[Cand151]:
    with CANDIDATES_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        out.append(
            Cand151(
                gov_id=r["gov_id"],
                name=r["name"],
                state=(r.get("state") or "").strip(),
                country=(r.get("country") or "").strip(),
                gov_kind=(r.get("gov_kind") or "").strip(),
                population=(r.get("population") or "").strip(),
                domain=(r.get("domain") or "").strip(),
                known_platform=(r.get("known_platform") or "").strip().lower(),
                prior_reason=(r.get("prior_reason") or "").strip(),
                research_calendar_url=(r.get("research_calendar_url") or "").strip(),
                research_meeting_url=(r.get("research_meeting_url") or "").strip(),
            )
        )
    return out


def _load_consolidated_gov_ids() -> set:
    """Non-canonical (county-form) gov_ids from PR #842's map -- a page
    for one of these keys to the SAME government as its canonical id, so
    a candidate here is already covered if the canonical form is, and
    ingesting under the county form would just be re-keyed by the
    resolver anyway. Skip outright, per this WO's own instructions."""
    if not CONSOLIDATED_CSV.exists():
        return set()
    with CONSOLIDATED_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f) if r.get("gov_id")}


REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "country",
    "gov_kind",
    "population",
    "prior_reason",
    "start_url",
    "start_url_status",
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


def _retag_wo164(reason: str) -> str:
    """WO-164 (merged to main 2026-09-10, rtr-deeplink#866): sharpen the
    old no-video-found/no-meetings-found catch-alls into the three
    content tags Ryan asked for. See
    ~/Documents/rtr-business/research/wo164_retag_rules.md.

    A precise field-based mapping (its own rule 1, video-without-meeting)
    needs a `meeting_url`/`video_url`/candidates-tried signal on a
    SKIPPED row -- hs.Result (reused from hub_sweep_wo126, not rewritten
    for this WO) only populates those via `_fill()` on a SUCCESS path, so
    that signal genuinely isn't available here for a skip. This applies
    the two mappings that ARE always safe given what a skip's own reason
    string already tells us: `no-video-found` only ever gets raised (in
    this script's own act_on_resolved_wo151 and in hs._process_gov's
    leads loop) after a real platform lead was actually resolved, which
    is exactly rule 2's "a real meeting was found" condition -- and
    `no-meetings-found` is raised only when a listing/enumeration came
    back genuinely empty, exactly rule 3. `video-without-meeting` is left
    undetected (0, an honest gap noted in this WO's own report) rather
    than guessed."""
    if reason == "no-video-found":
        return "meeting-without-video"
    if reason == "no-meetings-found":
        return "no-meeting-nor-video"
    return reason


def _reject_class(reason: str) -> str:
    access_reasons = {
        "blocked-plain-http",
        "blocked-browser-headers",
        "blocked-headless",
        "cloudflare-challenge-blocked",
        "dns-unresolvable",
        "timeout",
        "stale-url-404",
    }
    if not reason:
        return ""
    return "access" if reason in access_reasons else "content"


def _report_writer(path: Path):
    is_new = not path.exists()
    f = path.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(
        f, fieldnames=REPORT_FIELDS, extrasaction="ignore", lineterminator="\n"
    )
    if is_new:
        w.writeheader()
        f.flush()
    return f, w


def _seeds_writer(path: Path):
    fields = ["netloc", "platform", "gov_id", "access_mode"]
    is_new = not path.exists()
    f = path.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    if is_new:
        w.writeheader()
        f.flush()
    return f, w


def _host_access_writer(path: Path):
    fields = ["host", "access_mode", "waf_family"]
    is_new = not path.exists()
    f = path.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    if is_new:
        w.writeheader()
        f.flush()
    return f, w


def _tier3_pending_writer(path: Path):
    fields = [
        "gov_id",
        "platform",
        "meeting_url",
        "video_url",
        "source_url",
        "jurisdiction",
        "probe_verdict",
        "probe_reason",
        "probe_duration_seconds",
        "queued",
    ]
    is_new = not path.exists()
    f = path.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    if is_new:
        w.writeheader()
        f.flush()
    return f, w


def _already_done_gov_ids(path: Path) -> set:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f) if r.get("gov_id")}


def _existing_tier3_queue_urls() -> set:
    urls = set()
    if hs.TIER3_QUEUE_FILE.exists():
        for line in hs.TIER3_QUEUE_FILE.read_text().splitlines():
            first = line.split("\t", 1)[0].strip()
            if first:
                urls.add(normalize_url(first))
    return urls


# --------------------------------------------------------------------------
# LadderFetcher: hs.Fetcher + a browser-header retry after 403/dropped
# connection, never after a 404. Monkeypatched over hs.Fetcher below so
# hs._process_gov / hs.civicplus_walk (both reused, not reimplemented)
# get the same rung on every fetch they make.
# --------------------------------------------------------------------------

_OriginalFetcher = hs.Fetcher


class LadderFetcher(_OriginalFetcher):
    def __init__(self, session: aiohttp.ClientSession, budget: int):
        super().__init__(session, budget)
        self.last_rung = "plain"
        self.last_waf_family = "none"

    async def get(self, url: str) -> Tuple[str, str]:
        if self.fetches >= self.budget:
            raise hs.FetchError(
                "budget", f"per-government fetch budget of {self.budget} used"
            )
        if self.fetches:
            await asyncio.sleep(hs.REQUEST_DELAY_SECONDS)
        self.fetches += 1
        last_exc: Optional[hs.FetchError] = None
        for headers, rung in (
            (HONEST_HEADERS, "plain"),
            (BROWSER_HEADERS, "browser-headers"),
        ):
            try:
                async with self.session.get(
                    url, headers=headers, timeout=hs.FETCH_TIMEOUT, allow_redirects=True
                ) as resp:
                    text = await resp.text(errors="replace")
                    self.last_waf_family = waf_family_from_headers(
                        dict(resp.headers), str(resp.headers.get("set-cookie", ""))
                    )
                    if any(m in text[:4000].lower() for m in CHALLENGE_MARKERS):
                        raise hs.FetchError(
                            "cloudflare", f"human-verification gate at {url}"
                        )
                    if resp.status == 404:
                        # Never retried with browser headers -- a 404 means
                        # the URL is wrong, not that the client is unwelcome.
                        raise hs.FetchError("http", f"HTTP 404 at {url}")
                    if resp.status >= 400:
                        if resp.status == 403 and rung == "plain":
                            last_exc = hs.FetchError(
                                "http", f"HTTP 403 at {url} (plain)"
                            )
                            continue
                        raise hs.FetchError("http", f"HTTP {resp.status} at {url}")
                    self.last_rung = rung
                    return str(resp.url), text
            except hs.FetchError:
                raise
            except aiohttp.ClientConnectorError as e:
                if (
                    isinstance(e.os_error, socket.gaierror)
                    or "nodename nor servname" in str(e)
                    or "Name or service not known" in str(e)
                ):
                    raise hs.FetchError("dns", f"DNS failed for {urlparse(url).netloc}")
                self.network_failures += 1
                last_exc = hs.FetchError("network", f"connection failed: {e}")
                if rung == "plain":
                    continue
                raise last_exc
            except (asyncio.TimeoutError, aiohttp.ClientError, OSError) as e:
                self.network_failures += 1
                last_exc = hs.FetchError("network", f"{type(e).__name__}: {e}")
                if rung == "plain":
                    continue
                raise last_exc
        raise last_exc or hs.FetchError("network", "ladder exhausted")


hs.Fetcher = LadderFetcher


# --------------------------------------------------------------------------
# act_on_resolved_wo151: hs.act_on_resolved + WO-145's wrong-government
# checks + probe-before-queue. Monkeypatched over hs.act_on_resolved so
# hs._process_gov (reused, not reimplemented) calls this version.
# --------------------------------------------------------------------------

_original_act_on_resolved = hs.act_on_resolved


async def act_on_resolved_wo151(
    session: aiohttp.ClientSession,
    gov,
    lead,
    result,
    meeting_url: str,
    high_risk: bool,
    index,
    res,
    dry_run: bool,
    adapter_jurisdiction: str = "",
):
    segments = result.segments or []
    agenda_items = result.agenda_items or []
    if not (segments or agenda_items or result.agenda_link or result.video_url):
        raise hs.Skip(
            "no-video-found",
            f"{lead.platform}: resolved but no transcript/agenda/video ({meeting_url})",
        )

    effective_title = result.title or lead.title or ""
    if not effective_title and result.video_url:
        effective_title = await hs.youtube_oembed_title(session, result.video_url) or ""
    if not hs._looks_like_real_meeting(effective_title, require_allowlist=high_risk):
        raise hs.Skip(
            "off-mission",
            f"{lead.platform}: title looks like a non-meeting video: {effective_title!r} ({meeting_url})",
        )

    # --- WO-145's wrong-government checks, reused verbatim, run against
    # the ADAPTER's own raw jurisdiction/meeting_body/title -- BEFORE the
    # line below overwrites result.jurisdiction with the registry's claim.
    # See this file's module docstring for why hs.key_check/pin_for alone
    # (hub_sweep_wo126's own identity handling) don't catch this class.
    adapter_signal = f"{result.jurisdiction or ''} {result.meeting_body or ''}".strip()
    conflict = _state_or_kind_conflict(gov, adapter_signal, "adapter jurisdiction/body")
    if conflict:
        raise hs.Skip("wrong-domain-mapping", conflict)
    conflict = _state_or_kind_conflict(gov, effective_title, "title")
    if conflict:
        raise hs.Skip("wrong-domain-mapping", conflict)
    title_conflict = _title_place_conflict(gov, effective_title)
    if title_conflict:
        raise hs.Skip("wrong-domain-mapping", title_conflict)
    if lead.platform in ("escribe", "civicweb"):
        combined = f"{result.jurisdiction or ''} {result.meeting_body or ''} {effective_title or ''}".strip()
        border_conflict = _cross_border_collision(gov, combined)
        if border_conflict:
            raise hs.Skip("wrong-domain-mapping", border_conflict)

    covered = index.covered(result, meeting_url)
    if covered:
        res.outcome = "already_covered"
        res.reject_reason = "already-covered"
        res.detail = covered
        return hs._fill(res, result, meeting_url, effective_title)

    result.jurisdiction = gov.jurisdiction
    bare_video_host = lead.platform in hs.HIGH_RISK_TITLE_PLATFORMS
    if bare_video_host and lead.found_on:
        result.source_url = lead.found_on

    if segments:
        ok, tier = hs.key_check(gov, gov.jurisdiction, result.source_url or meeting_url)
        res.key_check = tier
        if not ok:
            pin = hs.pin_for(
                gov,
                result.source_url or meeting_url,
                result.video_url or "",
                lead.platform,
            )
            if pin:
                hs.stage_pin(pin, dry_run)
                res.pin = f"{pin['tenant_host']}|{pin['match']}"
        if dry_run:
            res.outcome = "dry_run_tier1_2"
        else:
            response = await hs._ingest_with_retry(
                session, result.model_dump(), normalize_url(meeting_url)
            )
            if response is None:
                raise hs.Skip(
                    "resolve-failed",
                    f"{lead.platform}: resolved {len(segments)} segments but POST to Archive failed twice",
                )
            res.page_url = response.get("url") or ""
            res.outcome = "ingested_tier1_2"
            if not response.get("created"):
                res.detail = "matched an EXISTING page, not newly created"
        return hs._fill(res, result, meeting_url, effective_title)

    if result.video_url:
        if index.in_queue(meeting_url) or index.in_queue(result.video_url):
            res.outcome = "duplicate_queued"
            res.reject_reason = "duplicate-queued"
            res.detail = "already in tier3_auto_transcription_queue.txt"
            return hs._fill(res, result, meeting_url, effective_title)

        queue_url = (
            result.video_url if bare_video_host and result.video_url else meeting_url
        )
        # Normalize a YouTube /embed/ URL to watch?v= before probing, per
        # this WO's own instructions.
        if "youtube.com/embed/" in queue_url:
            vid = queue_url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]
            queue_url = f"https://www.youtube.com/watch?v={vid}"
        source_override = lead.found_on if bare_video_host else ""
        host_url = source_override or result.source_url or meeting_url
        ok, tier = hs.key_check(gov, adapter_jurisdiction, host_url)
        res.key_check = f"adapter:{tier}"
        pin = None
        if not ok:
            pin = hs.pin_for(gov, host_url, result.video_url, lead.platform)
            if pin:
                res.pin = f"{pin['tenant_host']}|{pin['match']}"

        # --- WO-144 probe before queue -----------------------------------
        probe = await probe_queue_entry(
            queue_url,
            video_url=result.video_url,
            source_page_url=host_url,
            platform=lead.platform,
        )
        append_probe_row(DEFAULT_SIDECAR_PATH, probe)
        res.detail = (
            f"probe: verdict={probe.verdict} duration={probe.duration_seconds} "
            f"reason={probe.reason or ''}"
        )
        setattr(res, "probe_verdict", probe.verdict)
        setattr(res, "probe_reason", probe.reason or "")
        setattr(res, "probe_duration_seconds", probe.duration_seconds)
        if probe.verdict in ("reject-dead", "reject-short"):
            res.outcome = "rejected_by_probe"
            res.reject_reason = (
                "no-video-found" if probe.verdict == "reject-dead" else "reject-short"
            )
            return hs._fill(res, result, meeting_url, effective_title)

        if dry_run:
            res.outcome = "dry_run_tier3"
        else:
            if pin:
                hs.stage_pin(pin, dry_run)
            with hs.TIER3_QUEUE_FILE.open("a", encoding="utf-8") as f:
                line = (
                    f"{queue_url}\t{source_override}" if source_override else queue_url
                )
                f.write(line + "\n")
            index.queued.add(normalize_url(queue_url))
            res.outcome = "queued_tier3"
        res.reject_reason = "video-no-captions-queued"
        return hs._fill(res, result, meeting_url, effective_title)

    raise hs.Skip(
        "no-video-found",
        f"{lead.platform}: resolved a real agenda/meeting record but no video "
        f"anywhere ({meeting_url}) -- agenda-only is never ingested",
    )


hs.act_on_resolved = act_on_resolved_wo151


# --------------------------------------------------------------------------
# Headless rung (genuinely new -- see module docstring point 3).
# --------------------------------------------------------------------------

_headless_used = 0


def _headless_fetch_sync(url: str) -> Optional[Tuple[str, str]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(
                    user_agent=BROWSER_HEADERS["user-agent"],
                    viewport={"width": 1280, "height": 800},
                )
                page.goto(url, timeout=25000, wait_until="load")
                page.wait_for_timeout(3000)
                content = page.content()
                final_url = page.url
                return final_url, content
            finally:
                browser.close()
    except Exception:  # noqa: BLE001 -- any Playwright failure just means "no headless result"
        return None


async def headless_discover(url: str) -> Tuple[Optional[str], Optional[str], str]:
    global _headless_used
    if _headless_used >= HEADLESS_BUDGET:
        return None, None, "headless budget exhausted for this run"
    _headless_used += 1
    result = await asyncio.to_thread(_headless_fetch_sync, url)
    if not result:
        return None, None, "headless fetch failed or Playwright unavailable"
    final_url, html = result
    if any(m in html[:4000].lower() for m in CHALLENGE_MARKERS):
        return None, None, "challenge"
    return final_url, html, "ok"


def _prefer_link(links: List[Tuple[str, str]]) -> Optional[str]:
    if not links:
        return None
    order = hs._PLATFORM_PREFERENCE
    links_sorted = sorted(
        links, key=lambda t: order.index(t[1]) if t[1] in order else len(order)
    )
    return links_sorted[0][0]


async def maybe_try_headless(
    session: aiohttp.ClientSession, gov: Cand151, url: str, index, finder
):
    final_url, html, note = await headless_discover(url)
    if not html:
        return None, note
    discovered = None
    if "catagendarow" in html.lower() or "/agendacenter" in (final_url or "").lower():
        discovered = final_url
    else:
        links = hs._platform_links(html, final_url)
        discovered = _prefer_link(links)
        if not discovered:
            for hop in hs._hint_links(html, final_url, 4):
                try:
                    async with session.get(
                        hop,
                        headers=HONEST_HEADERS,
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as resp:
                        if resp.status >= 400:
                            continue
                        hop_html = await resp.text(errors="replace")
                        if "catagendarow" in hop_html.lower():
                            discovered = str(resp.url)
                            break
                        hop_links = hs._platform_links(hop_html, str(resp.url))
                        discovered = _prefer_link(hop_links)
                        if discovered:
                            break
                except Exception:  # noqa: BLE001
                    continue
    if not discovered:
        return None, "headless render found no platform link"

    gov_attempt = replace(gov, hub_url=discovered)
    fetcher = LadderFetcher(session, hs.PER_GOV_FETCH_BUDGET)
    res = hs.Result(hub_kind=hs.hub_kind_of(discovered))
    try:
        res = await asyncio.wait_for(
            hs._process_gov(fetcher, session, gov_attempt, index, finder, res, False),
            timeout=hs.PER_GOV_WALL_CLOCK_SECONDS,
        )
    except hs.Skip as e:
        res.outcome = "skipped"
        res.reject_reason = e.reject_reason
        res.detail = e.detail
    except hs.FetchError as e:
        res.outcome = "skipped"
        res.reject_reason = "resolve-failed"
        res.detail = str(e)
    except asyncio.TimeoutError:
        res.outcome = "skipped"
        res.reject_reason = "timeout"
    res.fetches = fetcher.fetches
    return (res, fetcher, discovered), "ok"


# --------------------------------------------------------------------------
# Per-government driver: multiple start URLs, in order.
# --------------------------------------------------------------------------


def _www_variant(url: str) -> Optional[str]:
    """`https://foo.gov` -> `https://www.foo.gov`, or the reverse -- one
    guess only, tried after a DNS failure on a `domain`-sourced start
    URL. Never applied to a research_calendar_url/research_meeting_url
    (those are real URLs already, a www. guess on them would be noise)."""
    p = urlparse(url)
    if p.netloc.startswith("www."):
        return f"{p.scheme}://{p.netloc[4:]}{p.path}"
    return f"{p.scheme}://www.{p.netloc}{p.path}"


def _candidate_start_urls(c: Cand151) -> List[Tuple[str, str]]:
    out = []
    if c.research_calendar_url:
        out.append((c.research_calendar_url, "research_calendar_url"))
    if c.research_meeting_url and c.research_meeting_url != c.research_calendar_url:
        out.append((c.research_meeting_url, "research_meeting_url"))
    if c.domain:
        dom = c.domain if "://" in c.domain else f"https://{c.domain}"
        out.append((dom.rstrip("/"), "domain"))
    return out


# Reasons that STOP the ladder outright rather than falling through to
# the next start URL: a confirmed wrong government (trying a different
# URL on what's usually the same tenant risks the same wrong content),
# or an off-mission verdict (the government's own site really did link a
# non-meeting video -- a different research URL on the same site is
# unlikely to differ). Every other content/access reason is worth
# retrying with the next start URL -- real, confirmed live in this WO's
# own pilot (Harrison County MS): research_calendar_url was a bare
# YouTube channel/streams page (no resolvable video id, "resolve-failed"),
# and research_meeting_url was a real, specific watch URL for an actual
# meeting -- stopping at the first reason would have missed it.
CONTENT_STOP_REASONS = {"wrong-domain-mapping", "off-mission"}


async def process_candidate(
    session: aiohttp.ClientSession, cand: Cand151, index, finder
) -> dict:
    row = {k: "" for k in REPORT_FIELDS}
    row.update(
        gov_id=cand.gov_id,
        name=cand.name,
        state=cand.state,
        country=cand.country,
        gov_kind=cand.gov_kind,
        population=cand.population,
        prior_reason=cand.prior_reason,
        candidates_listed=0,
        candidates_tried=0,
    )

    last = None  # (res, fetcher, url, source_tag, kind)
    stopped_on_challenge = False
    for url, source_tag in _candidate_start_urls(cand):
        if not row["start_url"]:
            row["start_url"] = url
            row["host"] = urlparse(url).netloc
        gov_attempt = replace(cand, hub_url=url)
        fetcher = LadderFetcher(session, hs.PER_GOV_FETCH_BUDGET)
        res = hs.Result(hub_kind=hs.hub_kind_of(url))
        try:
            res = await asyncio.wait_for(
                hs._process_gov(
                    fetcher, session, gov_attempt, index, finder, res, False
                ),
                timeout=hs.PER_GOV_WALL_CLOCK_SECONDS,
            )
            last = (res, fetcher, url, source_tag, "ok")
            row["rung_answered"] = fetcher.last_rung
            break
        except hs.Skip as e:
            res.outcome = "skipped"
            res.reject_reason = e.reject_reason
            res.detail = e.detail
            last = (res, fetcher, url, source_tag, "skip")
            row["rung_answered"] = fetcher.last_rung
            if e.reject_reason in CONTENT_STOP_REASONS:
                break
            continue
        except hs.FetchError as e:
            if e.kind == "cloudflare":
                res.outcome = "skipped"
                res.reject_reason = "cloudflare-challenge-blocked"
                res.detail = e.detail
                last = (res, fetcher, url, source_tag, "challenge")
                stopped_on_challenge = True
                break
            if e.kind == "dns":
                # Try a www./bare-domain variant before declaring dead --
                # a bare `dns-unresolvable` domain often resolves once
                # `www.` is added (or dropped), per this WO's own
                # instructions.
                variant = _www_variant(url) if source_tag == "domain" else None
                if variant:
                    v_gov = replace(cand, hub_url=variant)
                    v_fetcher = LadderFetcher(session, hs.PER_GOV_FETCH_BUDGET)
                    v_res = hs.Result(hub_kind=hs.hub_kind_of(variant))
                    try:
                        v_res = await asyncio.wait_for(
                            hs._process_gov(
                                v_fetcher, session, v_gov, index, finder, v_res, False
                            ),
                            timeout=hs.PER_GOV_WALL_CLOCK_SECONDS,
                        )
                        row["corrected_domain"] = variant
                        last = (v_res, v_fetcher, variant, source_tag, "ok")
                        row["rung_answered"] = v_fetcher.last_rung
                        break
                    except hs.Skip as ve:
                        v_res.outcome = "skipped"
                        v_res.reject_reason = ve.reject_reason
                        v_res.detail = ve.detail
                        row["corrected_domain"] = variant
                        last = (v_res, v_fetcher, variant, source_tag, "skip")
                        row["rung_answered"] = v_fetcher.last_rung
                        if ve.reject_reason in CONTENT_STOP_REASONS:
                            break
                        continue
                    except (hs.FetchError, asyncio.TimeoutError):
                        pass  # variant also failed -- fall through to dead
                res.outcome = "skipped"
                res.reject_reason = "dns-unresolvable"
                res.detail = e.detail
                last = (res, fetcher, url, source_tag, "dead")
                continue
            if "404" in str(e):
                res.outcome = "skipped"
                res.reject_reason = "stale-url-404"
                res.detail = str(e)
                last = (res, fetcher, url, source_tag, "404")
                continue
            res.outcome = "skipped"
            res.reject_reason = (
                "blocked-browser-headers"
                if fetcher.last_rung == "browser-headers"
                else "blocked-plain-http"
            )
            res.detail = str(e)
            last = (res, fetcher, url, source_tag, "blocked")
            row["waf_family"] = fetcher.last_waf_family
            continue
        except asyncio.TimeoutError:
            res.outcome = "skipped"
            res.reject_reason = "timeout"
            last = (res, fetcher, url, source_tag, "timeout")
            continue

    if last is None:
        row["outcome"] = "skipped"
        row["reject_reason"] = "no-platform-link-found"
        row["note"] = "no start URL available on this row (blank domain/research URLs)"
        row["access_mode"] = "dead"
        row["reject_class"] = _reject_class(row["reject_reason"])
        row["reject_reason"] = _retag_wo164(row["reject_reason"])
        return row

    res, fetcher, url, source_tag, kind = last
    row["start_url"] = row["start_url"] or url
    row["start_url_status"] = kind
    row["host"] = urlparse(url).netloc
    row["access_mode"] = {
        "ok": fetcher.last_rung,
        "skip": fetcher.last_rung,
        "challenge": "challenge",
        "dead": "dead",
        "404": "dead",
        "blocked": fetcher.last_rung,
        "timeout": "dead",
    }.get(kind, "dead")
    row["waf_family"] = row["waf_family"] or getattr(fetcher, "last_waf_family", "none")
    row["outcome"] = res.outcome
    row["reject_reason"] = res.reject_reason
    row["platform_found"] = res.platform
    row["hit_url"] = res.meeting_url or ""
    row["netloc"] = urlparse(res.meeting_url).netloc if res.meeting_url else ""
    row["meeting_url"] = res.meeting_url
    row["video_url"] = res.video_url
    row["page_url"] = res.page_url
    row["tier"] = (
        "1/2"
        if res.outcome == "ingested_tier1_2"
        else ("3" if res.outcome == "queued_tier3" else "")
    )
    row["note"] = res.detail

    # --- headless rung: only when every start URL that answered did so
    # with a real (non-blocked, non-challenge) page but no platform link.
    if (
        not stopped_on_challenge
        and res.outcome == "skipped"
        and res.reject_reason == "no-platform-link-found"
    ):
        headless_out, headless_note = await maybe_try_headless(
            session, cand, url, index, finder
        )
        if headless_out:
            hres, hfetcher, hurl = headless_out
            row["rung_answered"] = "headless"
            row["access_mode"] = (
                "headless"
                if hres.outcome != "skipped"
                or hres.reject_reason != "no-platform-link-found"
                else "dead"
            )
            row["outcome"] = hres.outcome
            row["reject_reason"] = hres.reject_reason
            row["platform_found"] = hres.platform
            row["hit_url"] = hres.meeting_url or hurl
            row["netloc"] = urlparse(hres.meeting_url or hurl).netloc
            row["meeting_url"] = hres.meeting_url
            row["video_url"] = hres.video_url
            row["page_url"] = hres.page_url
            row["tier"] = (
                "1/2"
                if hres.outcome == "ingested_tier1_2"
                else ("3" if hres.outcome == "queued_tier3" else "")
            )
            row["note"] = f"{hres.detail} (found via headless render of {url})"
        elif headless_note:
            row["note"] = f"{row['note']}; headless: {headless_note}"

    row["reject_class"] = _reject_class(row["reject_reason"])
    row["reject_reason"] = _retag_wo164(row["reject_reason"])
    return row


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------


def _pilot_spread(cands: List[Cand151], n: int) -> List[Cand151]:
    """Every-kth row after sorting by (gov_kind, state) -- spread across
    municipalities/counties/townships/states rather than just the top N
    by population."""
    ordered = sorted(cands, key=lambda c: (c.gov_kind, c.state))
    if len(ordered) <= n:
        return ordered
    step = len(ordered) / n
    return [ordered[int(i * step)] for i in range(n)]


async def main_async(args) -> None:
    if not _base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (check .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    register_all_finders()
    finder = hs.CivicPlusAssetFinder()

    if args.refresh_export or not EXPORT_JSON.exists():
        n = await hs.refresh_export(EXPORT_JSON)
        print(f"export refreshed: {n} pages -> {EXPORT_JSON}")
    index = hs.DedupeIndex(EXPORT_JSON, hs.TIER3_QUEUE_FILE)

    consolidated_ids = _load_consolidated_gov_ids()
    print(
        f"{len(consolidated_ids)} county-form gov_ids in consolidated_governments.csv"
    )

    cands = load_candidates()
    done = _already_done_gov_ids(REPORT_CSV)
    todo = [c for c in cands if c.gov_id not in done]
    if args.pilot:
        todo = _pilot_spread(todo, args.pilot)
    elif args.limit:
        todo = todo[: args.limit]
    print(
        f"Processing {len(todo)} of {len(cands)} candidate(s) ({len(done)} already logged)...\n"
    )

    report_f, report_w = _report_writer(REPORT_CSV)
    seeds_f, seeds_w = _seeds_writer(SEEDS_CSV)
    host_f, host_w = _host_access_writer(HOST_ACCESS_CSV)
    tier3_f, tier3_w = _tier3_pending_writer(TIER3_PENDING_CSV)
    seeded_netlocs: set = set()
    logged_hosts: set = set()

    consecutive_errors = 0
    try:
        async with aiohttp.ClientSession() as session:
            for i, cand in enumerate(todo):
                gov_id_covered = (
                    cand.gov_id in index.gov_ids or cand.gov_id in consolidated_ids
                )
                if gov_id_covered:
                    row = {k: "" for k in REPORT_FIELDS}
                    row.update(
                        gov_id=cand.gov_id,
                        name=cand.name,
                        state=cand.state,
                        country=cand.country,
                        gov_kind=cand.gov_kind,
                        population=cand.population,
                        prior_reason=cand.prior_reason,
                        outcome="already_covered",
                        note="gov_id already has an archived page, or is a consolidated county-form id",
                    )
                    consecutive_errors = 0
                else:
                    try:
                        row = await process_candidate(session, cand, index, finder)
                        is_error = row["outcome"] == "error"
                        consecutive_errors = consecutive_errors + 1 if is_error else 0
                    except Exception as e:  # noqa: BLE001
                        row = {k: "" for k in REPORT_FIELDS}
                        row.update(
                            gov_id=cand.gov_id,
                            name=cand.name,
                            state=cand.state,
                            country=cand.country,
                            gov_kind=cand.gov_kind,
                            population=cand.population,
                            prior_reason=cand.prior_reason,
                            outcome="error",
                            note=f"unhandled: {type(e).__name__}: {e}",
                        )
                        consecutive_errors += 1

                report_w.writerow(row)
                report_f.flush()

                host = row.get("host") or ""
                if host and host not in logged_hosts and row.get("access_mode"):
                    host_w.writerow(
                        {
                            "host": host,
                            "access_mode": row["access_mode"],
                            "waf_family": row.get("waf_family") or "none",
                        }
                    )
                    host_f.flush()
                    logged_hosts.add(host)

                netloc = row.get("netloc") or ""
                if (
                    netloc
                    and netloc not in seeded_netlocs
                    and row.get("platform_found")
                ):
                    seeds_w.writerow(
                        {
                            "netloc": netloc,
                            "platform": row["platform_found"],
                            "gov_id": row["gov_id"],
                            "access_mode": row.get("access_mode") or "",
                        }
                    )
                    seeds_f.flush()
                    seeded_netlocs.add(netloc)

                if (
                    row.get("outcome") == "queued_tier3"
                    or row.get("tier") == "3"
                    or row.get("outcome") == "rejected_by_probe"
                ):
                    tier3_w.writerow(
                        {
                            "gov_id": row["gov_id"],
                            "platform": row.get("platform_found") or "",
                            "meeting_url": row.get("meeting_url") or "",
                            "video_url": row.get("video_url") or "",
                            "source_url": row.get("hit_url") or "",
                            "jurisdiction": f"{row['name']}, {row['state']}",
                            "probe_verdict": "accept"
                            if row.get("outcome") == "queued_tier3"
                            else "reject",
                            "probe_reason": row.get("note") or "",
                            "probe_duration_seconds": "",
                            "queued": "yes"
                            if row.get("outcome") == "queued_tier3"
                            else "no",
                        }
                    )
                    tier3_f.flush()

                print(
                    f"[{i + 1}/{len(todo)}] [{row['outcome']:20}] {row['gov_id']} {row['name']!r} "
                    f"access={row.get('access_mode')!r} -- {row.get('reject_reason') or row.get('note', '')}"
                )

                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(
                        f"\nABORTING: {consecutive_errors} consecutive real errors -- "
                        "stopping per CLAUDE.md's politeness rule. Re-run to resume.",
                        file=sys.stderr,
                    )
                    break
                if i < len(todo) - 1:
                    await asyncio.sleep(hs.REQUEST_DELAY_SECONDS)
    finally:
        report_f.close()
        seeds_f.close()
        host_f.close()
        tier3_f.close()

    print(f"\nFull report: {REPORT_CSV}")
    print(f"Headless renders used this run: {_headless_used} / {HEADLESS_BUDGET}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--pilot", type=int, default=None, help="spread N rows across gov_kind/state"
    )
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--refresh-export", action="store_true")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
