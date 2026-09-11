"""WO-216 (2026-09-11): ladder sweep of the 417 US (+34 Canadian)
governments with a domain that the Gov Coverage dashboard (coverage
registry) shows as `test_status=untested` -- municipality, township and
county only (school districts are a separate, excluded population).
Candidate list: `research/wo216_candidates.csv`, built by
`scripts/wo216_build_candidates.py`.

Ryan's ingest rule is absolute: only a meeting with real video becomes an
Archive page (tier 1/2, real captions) or a tier-3 queue candidate
(video, no reachable captions, probed before it ever reaches the queue
file). Agenda-only is `meeting-without-video` -- recorded, never
ingested.

Reused BY IMPORT, never copied or edited, same pattern as
`scripts/wo191_access_ladder_sweep.py`:
  - `scripts/wo147_access_ladder_sweep.py`'s `run_access_ladder()` (the
    plain -> browser-headers -> headless ladder) and its
    `classify_skip_reason()`, `normalize_known_platform()`,
    `normalize_home_url()`, `channel_scan_caution()`, and
    `government_display_name()`.
  - `scripts/wo134_confirmed_hits_ingest.py`'s `process_row()` for the
    actual resolve/ingest/queue/pin pipeline, via `TIER3_HANDLER` routing
    a tier-3 find to a probe-before-queue pending file, exactly like
    WO-147/WO-150/WO-181/WO-191 before it.
  - `scripts/coverage_alternates.py`'s `ladder_with_alternates()` +
    `classify_wo147_ladder_result()`, wired to `wo147.run_access_ladder`
    as the `ladder_fn`, `trigger="no-meeting"` (Ryan's rule: an untested
    row whose primary produces nothing at all tries its recorded
    alternate domain next, promoting it if the alternate answers).
  - `scripts/wo174_pipeline.py`'s `classify_video_hand_check()` as the
    automatic pre-ingest hand-check gate, wired onto
    `wo134.IDENTITY_CHECK_HOOK` -- Kind A (channel belongs to a
    different real public body) and Kind B (right channel, wrong video)
    are both rejected BEFORE `process_row()` ever ingests or queues the
    candidate. Kind A owner bodies are logged to
    `research/wo216_owner_bodies.csv` for a later mint pass, per the
    brief. This is the automatic pre-filter only -- every candidate that
    clears it and actually becomes a page or a queue line still gets a
    manual by-hand read (title + channel, via oEmbed) in the same shape
    WO-191/WO-202 used, done as part of this WO's own review pass, not
    by this script.

Headless render budget: 300 for this WHOLE run (not per session; smaller
than WO-191's 600 since this WO's candidate pool is an order of
magnitude smaller), a running total under
`research/wo216_headless_budget.json` so it holds across a resumed run.

Politeness (CLAUDE.md, docs/BREADTH_SWEEP_BRIEF.md): one government (one
host) processed at a time, 2s between requests to the same host (rung
retries and alternate-domain retries alike), ~1.5s between governments,
an honest User-Agent by default, browser headers only after a
403/dropped connection, headless only for a real page with no visible
meeting link, and the run stops for good at any human-verification
challenge marker -- never retried past it.

Usage:
    python scripts/export_meeting_inventory.py --out-dir /tmp/wo216_inventory --source export
    python scripts/wo216_build_candidates.py
    python scripts/wo216_access_ladder_sweep.py --limit 20   # pilot
    python scripts/wo216_access_ladder_sweep.py              # full run, resumable
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
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

import scripts.coverage_alternates as ca  # noqa: E402
import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402
import scripts.wo147_access_ladder_sweep as wo147  # noqa: E402
from scripts.wo174_pipeline import classify_video_hand_check  # noqa: E402

SOURCE_TAG = "wo216"

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
JC_PATH = RESEARCH_DIR / "jurisdiction_coverage.csv"
CANDIDATES_CSV = RESEARCH_DIR / "wo216_candidates.csv"
REPORT_CSV = RESEARCH_DIR / "wo216_report.csv"
DISCOVERY_SEEDS_CSV = RESEARCH_DIR / "wo216_discovery_seeds.csv"
HOST_ACCESS_MODES_CSV = RESEARCH_DIR / "wo216_host_access_modes.csv"
TIER3_PENDING_CSV = RESEARCH_DIR / "wo216_tier3_pending.csv"
HEADLESS_BUDGET_JSON = RESEARCH_DIR / "wo216_headless_budget.json"
OWNER_BODIES_CSV = RESEARCH_DIR / "wo216_owner_bodies.csv"
HAND_CHECK_GATE_CSV = RESEARCH_DIR / "wo216_hand_check_gate.csv"
DEFAULT_INVENTORY_CSV = Path("/tmp/wo216_inventory/meeting_inventory.csv")

GOV_DELAY_SECONDS = 1.5  # between governments (different hosts)
ALTERNATE_DELAY_SECONDS = 2.0  # between a government's own candidate domains

HEADLESS_BUDGET_TOTAL = 300


# --- headless render budget, persisted across resumed runs --------------


def _load_headless_used() -> int:
    if HEADLESS_BUDGET_JSON.exists():
        try:
            return json.loads(HEADLESS_BUDGET_JSON.read_text()).get("used", 0)
        except Exception:  # noqa: BLE001
            return 0
    return 0


def _save_headless_used(used: int) -> None:
    HEADLESS_BUDGET_JSON.write_text(json.dumps({"used": used}))


_headless_used = _load_headless_used()
_original_fetch_headless = wo147.fetch_headless


async def _budgeted_fetch_headless(
    url: str,
) -> Tuple[Optional[str], str, Optional[str]]:
    global _headless_used
    if _headless_used >= HEADLESS_BUDGET_TOTAL:
        return (
            None,
            url,
            f"wo216 headless budget exhausted ({HEADLESS_BUDGET_TOTAL} used)",
        )
    _headless_used += 1
    _save_headless_used(_headless_used)
    return await _original_fetch_headless(url)


# Runtime wrapper, not an edit to wo147_access_ladder_sweep.py -- see
# wo191_access_ladder_sweep.py's identical comment for why this is safe.
wo147.fetch_headless = _budgeted_fetch_headless


# --- pre-ingest hand-check gate (Kind A / Kind B) ------------------------

_OWNER_BODY_FIELDS = [
    "owner_name",
    "channel",
    "video_url",
    "gov_id_if_known",
    "found_for_gov_id",
    "found_for_name",
    "note",
]


def record_owner_body(
    owner_name: str,
    channel: str,
    video_url: str,
    found_for_gov_id: str,
    found_for_name: str,
    note: str,
) -> None:
    is_new = not OWNER_BODIES_CSV.exists()
    with OWNER_BODIES_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_OWNER_BODY_FIELDS, lineterminator="\n")
        if is_new:
            w.writeheader()
        w.writerow(
            {
                "owner_name": owner_name,
                "channel": channel,
                "video_url": video_url,
                "gov_id_if_known": "",
                "found_for_gov_id": found_for_gov_id,
                "found_for_name": found_for_name,
                "note": note,
            }
        )


_HAND_CHECK_GATE_FIELDS = [
    "gov_id",
    "name",
    "state",
    "kind",
    "reason",
    "title",
    "channel",
    "video_url",
    "meeting_url",
]


def record_hand_check_gate(
    gov_id, name, state, kind, reason, title, channel, video_url, meeting_url
) -> None:
    is_new = not HAND_CHECK_GATE_CSV.exists()
    with HAND_CHECK_GATE_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_HAND_CHECK_GATE_FIELDS, lineterminator="\n")
        if is_new:
            w.writeheader()
        w.writerow(
            {
                "gov_id": gov_id,
                "name": name,
                "state": state,
                "kind": kind,
                "reason": reason,
                "title": title or "",
                "channel": channel or "",
                "video_url": video_url or "",
                "meeting_url": meeting_url or "",
            }
        )


def wo216_identity_check_hook(row, platform, result, final_seed, effective_title):
    """Wired onto wo134.IDENTITY_CHECK_HOOK. Runs
    `classify_video_hand_check()` (wo174_pipeline.py) as the automatic
    pre-ingest pre-filter on every candidate video BEFORE process_row()
    ingests or queues it. Kind A (channel belongs to a different real
    public body) is logged to wo216_owner_bodies.csv for a later mint
    pass and the government's own row is left no-video (this hit is
    skipped, process_row() tries the next hit if any). Kind B (right
    channel, wrong video) is logged so a follow-up pass can look for the
    right video on the same channel."""
    gov_id = row.get("gov_id", "")
    name = row.get("unit_name", "")
    state = row.get("_state", "")
    gov_kind = row.get("_gov_kind", "")

    channel_text = " ".join(
        filter(
            None,
            [
                (getattr(result, "video_channel", None) or "").lstrip("@"),
                result.jurisdiction or "",
            ],
        )
    )
    hand_check = classify_video_hand_check(
        effective_title, channel_text, name, gov_kind
    )
    if not hand_check:
        return None
    kind, reason = hand_check
    record_hand_check_gate(
        gov_id,
        name,
        state,
        kind,
        reason,
        effective_title,
        channel_text,
        result.video_url,
        final_seed,
    )
    if kind == "A":
        record_owner_body(
            reason,
            channel_text,
            result.video_url or final_seed,
            gov_id,
            name,
            f"WO-216 hand-check gate, kind A: {reason}",
        )
    return f"hand-check-kind-{kind.lower()}: {reason}"


wo134.IDENTITY_CHECK_HOOK = wo216_identity_check_hook


# --- tier-3 pending sink (Ryan's "probe before queue" gate), own file ---

_TIER3_PENDING_FIELDS = [
    "gov_id",
    "platform",
    "meeting_url",
    "video_url",
    "source_url",
    "jurisdiction",
    "pin_row",
]
_tier3_pending_seen: Optional[set] = None


def _tier3_pending_already_seen() -> set:
    global _tier3_pending_seen
    if _tier3_pending_seen is None:
        seen = set()
        if TIER3_PENDING_CSV.exists():
            with TIER3_PENDING_CSV.open(newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    seen.add(r.get("meeting_url", ""))
        _tier3_pending_seen = seen
    return _tier3_pending_seen


def tier3_pending_handler(
    *, gov_id, unit_name, platform, final_seed, hit_url, title, date, result
) -> None:
    if final_seed in _tier3_pending_already_seen():
        return
    pin_row = ""
    if platform in wo134.SHARED_HOST_PLATFORMS:
        host = wo134._tenant_override_host(platform, result, final_seed)
        match = wo134._tenant_override_match(platform, result, final_seed)
        if host and match:
            pin_row = (
                f"{host}|{match}|{gov_id}|fallback|{SOURCE_TAG}|"
                f"{unit_name} -- WO-216 tier-3 pending, gov_id={gov_id}"
            )
    is_new = not TIER3_PENDING_CSV.exists()
    with TIER3_PENDING_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=_TIER3_PENDING_FIELDS, lineterminator="\n")
        if is_new:
            w.writeheader()
        w.writerow(
            {
                "gov_id": gov_id,
                "platform": platform,
                "meeting_url": final_seed,
                "video_url": result.video_url or final_seed,
                "source_url": hit_url,
                "jurisdiction": result.jurisdiction or "",
                "pin_row": pin_row,
            }
        )
    _tier3_pending_already_seen().add(final_seed)


wo134.TIER3_HANDLER = tier3_pending_handler


# --- report ---------------------------------------------------------------

_REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "country",
    "gov_kind",
    "population",
    "domain",
    "corrected_domain",
    "alternates_tried",
    "access_mode",
    "platform_found",
    "hit_url",
    "outcome",
    "reject_reason",
    "reject_class",
    "netloc",
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


_discovery_seeds_written: Optional[set] = None


def write_discovery_seed(
    netloc: str, platform: str, gov_id: str, access_mode: str
) -> None:
    global _discovery_seeds_written
    if _discovery_seeds_written is None:
        seen = set()
        if DISCOVERY_SEEDS_CSV.exists():
            with DISCOVERY_SEEDS_CSV.open(newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    seen.add(r.get("netloc", ""))
        _discovery_seeds_written = seen
    if not netloc or netloc in _discovery_seeds_written:
        return
    is_new = not DISCOVERY_SEEDS_CSV.exists()
    with DISCOVERY_SEEDS_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=["netloc", "platform", "gov_id", "access_mode"],
            lineterminator="\n",
        )
        if is_new:
            w.writeheader()
        w.writerow(
            {
                "netloc": netloc,
                "platform": platform,
                "gov_id": gov_id,
                "access_mode": access_mode,
            }
        )
    _discovery_seeds_written.add(netloc)


_host_access_modes_written: Optional[set] = None


def write_host_access_mode(host: str, access_mode: str, waf_family: str) -> None:
    global _host_access_modes_written
    if _host_access_modes_written is None:
        seen = set()
        if HOST_ACCESS_MODES_CSV.exists():
            with HOST_ACCESS_MODES_CSV.open(newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    seen.add(r.get("host", ""))
        _host_access_modes_written = seen
    if not host or host in _host_access_modes_written:
        return
    is_new = not HOST_ACCESS_MODES_CSV.exists()
    with HOST_ACCESS_MODES_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["host", "access_mode", "waf_family"], lineterminator="\n"
        )
        if is_new:
            w.writeheader()
        w.writerow({"host": host, "access_mode": access_mode, "waf_family": waf_family})
    _host_access_modes_written.add(host)


# --- live jurisdiction_coverage.csv lookup (fresher than the registry) --


def _load_jc_index() -> Dict[str, dict]:
    with JC_PATH.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {r["gov_id"]: r for r in rows if (r.get("gov_id") or "").strip()}


# --- main driver ------------------------------------------------------


async def process_candidate(
    session: aiohttp.ClientSession,
    cand: dict,
    jc_index: Dict[str, dict],
    covered_gov_ids: set,
    writer,
) -> str:
    """Returns 'ok' or 'error' (for the consecutive-error breaker)."""
    gov_id = cand["gov_id"]
    country = cand["country"]
    gov_kind = cand["gov_kind"]
    population = cand["population"]

    jc_row = jc_index.get(gov_id)
    name = (jc_row.get("city_name") if jc_row else "") or cand["name"]
    state = (jc_row.get("state_or_province") if jc_row else "") or cand["state"]
    domain = (jc_row.get("domain") if jc_row else "") or cand["domain"]

    base_report = dict(
        gov_id=gov_id,
        name=name,
        state=state,
        country=country,
        gov_kind=gov_kind,
        population=population,
        domain=domain,
        corrected_domain="",
        alternates_tried="",
        access_mode="",
        platform_found="",
        hit_url="",
        outcome="",
        reject_reason="",
        reject_class="",
        netloc="",
        candidates_listed=0,
        candidates_tried=0,
        meeting_url="",
        video_url="",
        tier="",
        page_url="",
        waf_family="",
        note="",
    )

    if gov_id in covered_gov_ids:
        writer.writerow({**base_report, "outcome": "already_covered"})
        return "ok"

    if jc_row is None:
        writer.writerow(
            {
                **base_report,
                "outcome": "error",
                "note": "gov_id not found in jurisdiction_coverage.csv",
            }
        )
        return "error"

    raw_results: Dict[str, wo147.LadderResult] = {}

    async def ladder_fn(candidate_domain: str, row: dict) -> ca.LadderOutcome:
        result = await wo147.run_access_ladder(
            session, name, state, candidate_domain, candidate_domain
        )
        raw_results[candidate_domain] = result
        netloc = (
            urlparse(result.home_url).netloc if result.home_url else candidate_domain
        )
        write_host_access_mode(netloc, result.access_mode, result.waf_family)
        return ca.classify_wo147_ladder_result(result)

    alt_result = await ca.ladder_with_alternates(
        jc_row,
        ladder_fn,
        trigger="no-meeting",
        between_candidates_seconds=ALTERNATE_DELAY_SECONDS,
    )
    base_report["alternates_tried"] = alt_result.alternates_tried

    promoted = ca.decide_promotion(alt_result)
    if promoted:
        base_report["corrected_domain"] = alt_result.answered_domain

    winning_raw = raw_results.get(alt_result.answered_domain)
    home_url = (
        winning_raw.home_url
        if winning_raw and winning_raw.home_url
        else wo147.normalize_home_url(alt_result.answered_domain or domain)
    )
    access_mode = winning_raw.access_mode if winning_raw else ""
    waf_family = winning_raw.waf_family if winning_raw else ""
    base_report["access_mode"] = access_mode
    base_report["waf_family"] = waf_family

    reason = alt_result.outcome.reason

    if reason != ca.FOUND:
        if reason in ca.ACCESS_REASONS:
            writer.writerow(
                {
                    **base_report,
                    "outcome": "blocked",
                    "reject_reason": reason,
                    "reject_class": "access",
                    "note": alt_result.outcome.detail,
                }
            )
            return "ok"
        writer.writerow(
            {
                **base_report,
                "outcome": "no_platform_link_found",
                "reject_reason": reason,
                "reject_class": "content",
                "note": alt_result.outcome.detail,
            }
        )
        return "ok"

    # FOUND on the primary or an alternate. Gather every (platform, url)
    # hit: what the ladder saw, plus the jc row's own known_platform hint
    # against the winning domain's home url.
    hits: List[Tuple[str, str]] = []
    if alt_result.outcome.platform and alt_result.outcome.hit_url:
        hits.append((alt_result.outcome.platform, alt_result.outcome.hit_url))

    known_platform_raw = (
        jc_row.get("suspected_meeting_link_provider")
        or jc_row.get("suspected_calendar_provider")
        or jc_row.get("suspected_video_provider")
        or ""
    )
    known_platform = wo147.normalize_known_platform(known_platform_raw)
    if known_platform and known_platform not in wo134.UNSUPPORTED_PLATFORMS:
        seed = home_url or wo147.normalize_home_url(alt_result.answered_domain)
        if not any(p == known_platform for p, _ in hits):
            hits.append((known_platform, seed))

    platform_found = alt_result.outcome.platform or known_platform or ""
    base_report["platform_found"] = platform_found
    if alt_result.outcome.hit_url:
        base_report["hit_url"] = alt_result.outcome.hit_url

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
    if netloc:
        write_discovery_seed(netloc, primary_platform, gov_id, access_mode)

    hit_source_urls = ";".join(f"{p}={u}" for p, u in hits[:6])
    base_report["candidates_listed"] = len(hits[:6])
    base_report["candidates_tried"] = len(hits[:6])

    synthetic_row = {
        "gov_id": gov_id,
        "unit_name": name,
        "homepage": home_url,
        "hop2_urls": "",
        "hit_source_urls": hit_source_urls,
        "_state": state,
        "_gov_kind": gov_kind,
    }

    try:
        result = await wo134.process_row(
            session, synthetic_row, covered_gov_ids, SOURCE_TAG
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
                "outcome": "queued_tier3_pending",
                "meeting_url": result.seed_url,
                "video_url": result.video_url,
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
                "video_url": result.video_url,
                "tier": "tier3",
                "note": (base_report["note"] + "; " + result.reason).strip("; "),
            }
        )
        return "ok"

    if outcome == "rejected_by_probe":
        writer.writerow(
            {
                **base_report,
                "outcome": "rejected_by_probe",
                "reject_reason": "rejected_by_probe",
                "reject_class": "content",
                "meeting_url": result.seed_url,
                "video_url": result.video_url,
                "note": (base_report["note"] + "; " + result.reason).strip("; "),
            }
        )
        return "ok"

    if outcome == "no_video_found":
        writer.writerow(
            {
                **base_report,
                "outcome": "no_video_found",
                "reject_reason": "meeting-without-video",
                "reject_class": "content",
                "meeting_url": result.seed_url,
                "video_url": result.video_url,
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
    if result.video_url and not result.seed_url:
        writer.writerow(
            {
                **base_report,
                "outcome": "skipped",
                "reject_reason": "video-without-meeting",
                "reject_class": "content",
                "meeting_url": "",
                "video_url": result.video_url,
                "note": (base_report["note"] + "; " + result.reason).strip("; "),
            }
        )
        return "ok"

    reject_reason = wo147.classify_skip_reason(result.reason)
    reject_reason = {
        "no-video-found": "meeting-without-video",
        "no-meetings-found": "no-meeting-nor-video",
    }.get(reject_reason, reject_reason)
    outcome_label = {
        "no-platform-link-found": "no_platform_link_found",
        "meeting-without-video": "no_video_found",
        "no-meeting-nor-video": "no_meetings_found",
        "unsupported-platform-no-adapter": "blocked",
    }.get(reject_reason, "skipped")
    writer.writerow(
        {
            **base_report,
            "outcome": outcome_label,
            "reject_reason": reject_reason,
            "reject_class": "content",
            "meeting_url": result.seed_url,
            "video_url": result.video_url,
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

    jc_index = _load_jc_index()
    print(f"{len(jc_index)} gov_ids in {JC_PATH.name} (live lookup).")

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

    print(
        f"Processing {len(to_process)} row(s)... (headless used so far: {_headless_used}/{HEADLESS_BUDGET_TOTAL})\n"
    )

    report_f, writer = _report_writer()
    tally: Dict[str, int] = {}
    consecutive_errors = 0
    try:
        async with aiohttp.ClientSession() as session:
            for i, row in enumerate(to_process):
                t0 = time.monotonic()
                status = await process_candidate(
                    session, row, jc_index, covered_gov_ids, writer
                )
                report_f.flush()
                elapsed = time.monotonic() - t0
                print(
                    f"[{i + 1}/{len(to_process)}] {row['name']}, {row['state']} "
                    f"({row['gov_kind']}, pop={row['population']}) -- {elapsed:.1f}s -- status={status}"
                )
                tally[status] = tally.get(status, 0) + 1
                if status == "error":
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0
                if consecutive_errors >= 6:
                    print(
                        f"\nABORTING: {consecutive_errors} consecutive real errors. Re-run to resume.",
                        file=sys.stderr,
                    )
                    break
                if i < len(to_process) - 1:
                    await asyncio.sleep(GOV_DELAY_SECONDS)
    finally:
        report_f.close()

    print("\n--- Tally (this run) ---")
    for k, v in sorted(tally.items()):
        print(f"{k:10} {v}")
    print(
        f"\nHeadless renders used (cumulative, this whole WO): {_headless_used}/{HEADLESS_BUDGET_TOTAL}"
    )
    print(f"Full report: {REPORT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
