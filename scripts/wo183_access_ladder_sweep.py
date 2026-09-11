"""WO-183 (2026-09-11): access-ladder sweep of the 803 CivicMirror-
addendum new rows in rtr-business/research/jurisdiction_coverage.csv --
candidate list in research/wo183_candidates.csv (built by
scripts/wo183_build_candidates.py).

Copied from `scripts/wo191_access_ladder_sweep.py` (WO-191's own copy,
still uncommitted in its own in-progress worktree at the time this WO
ran, so a module import wasn't possible) rather than imported, per this
WO's own instructions: "Import its ladder and finish functions by module
import, or copy them into wo183_* files with a one-line note saying so."
Only the file-path constants (RESEARCH_DIR file names) and this docstring
were changed; the ladder logic, report shape, tier-3 pending handler,
and headless budget wrapper are unmodified from WO-191's version.

Ryan's ingest rule is absolute: only a meeting with real video becomes an
Archive page (tier 1/2, real captions) or a tier-3 queue candidate
(video, no reachable captions, probed before it ever reaches the queue
file). Agenda-only is `meeting-without-video` -- recorded, never
ingested.

Reused BY IMPORT, never copied or edited:
  - `scripts/wo147_access_ladder_sweep.py`'s `run_access_ladder()` (the
    plain -> browser-headers -> headless ladder itself, including its
    `find_platform_link()`/`find_hop_links()` link finders, challenge
    detection, and WAF-family classification) and its
    `classify_skip_reason()` taxonomy mapping, `normalize_known_platform()`
    / `normalize_home_url()`, `channel_scan_caution()` /
    `is_bare_youtube_channel_hit()` (the bare-YouTube-channel-scan
    caution flag), and `government_display_name()`.
  - `scripts/wo134_confirmed_hits_ingest.py`'s `process_row()` for the
    actual resolve/ingest/queue/pin pipeline (the same
    `POST /internal/ingest` call and shared-host pin logic every WO
    since WO-134 has used), via `TIER3_HANDLER` routing a tier-3 find to
    a probe-before-queue pending file rather than the real queue,
    exactly like WO-147/WO-150/WO-181/WO-191 before it.

Headless render budget: 200 for this WHOLE run (per this WO's own
brief), a running total under `research/wo183_headless_budget.json` so
it holds across a resumed run. `wo147.fetch_headless` is monkeypatched (a
runtime wrapper around the SAME function, not an edit to that file) to
enforce this budget -- once exhausted, headless simply reports "no page"
instead of launching a browser, which falls back to a
`no-platform-link-found` content reject for that host (the existing
behavior for "headless found nothing").

Discovery-ledger enrichment is DELIBERATELY NOT used here, for the same
reason WO-191 gave: several other sessions are running the same kind of
sweep concurrently tonight, and sharing a single scratch sqlite ledger
across independent processes risks a real write collision this WO
doesn't need to take on. These are freshly-added CivicMirror rows with
no confirmed platform signature in the overwhelming majority of cases, so
a bare (platform, seed) hit_source_url pair (handled by wo134.process_row
already) covers the rung-1 case just as well.

Politeness (CLAUDE.md, docs/BREADTH_SWEEP_BRIEF.md): one government (one
host) processed at a time, 2s between requests to the same host (rung
retries), ~1.5s between governments (which are different hosts, so this
already interleaves), an honest User-Agent by default, browser headers
only after a 403/dropped connection, headless only for a real page with
no visible meeting link, and the run stops for good at any
human-verification challenge marker -- never retried past it.

Usage:
    python3 scripts/wo183_build_candidates.py
    python3 scripts/wo183_access_ladder_sweep.py --limit 20   # smoke test
    python3 scripts/wo183_access_ladder_sweep.py              # full run, resumable
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

import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402
import scripts.wo147_access_ladder_sweep as wo147  # noqa: E402

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
CANDIDATES_CSV = RESEARCH_DIR / "wo183_candidates.csv"
REPORT_CSV = RESEARCH_DIR / "wo183_report.csv"
DISCOVERY_SEEDS_CSV = RESEARCH_DIR / "wo183_discovery_seeds.csv"
HOST_ACCESS_MODES_CSV = RESEARCH_DIR / "wo183_host_access_modes.csv"
TIER3_PENDING_CSV = RESEARCH_DIR / "wo183_tier3_pending.csv"
HEADLESS_BUDGET_JSON = RESEARCH_DIR / "wo183_headless_budget.json"
DEFAULT_INVENTORY_CSV = Path("/tmp/wo183_inventory/meeting_inventory.csv")

GOV_DELAY_SECONDS = 1.5  # between governments (different hosts)

HEADLESS_BUDGET_TOTAL = 200


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
            f"wo183 headless budget exhausted ({HEADLESS_BUDGET_TOTAL} used)",
        )
    _headless_used += 1
    _save_headless_used(_headless_used)
    return await _original_fetch_headless(url)


# Runtime wrapper, not an edit to wo147_access_ladder_sweep.py -- run_
# access_ladder() looks up `fetch_headless` in ITS OWN module's globals
# at call time, so reassigning the attribute here intercepts every call
# it makes without touching that file.
wo147.fetch_headless = _budgeted_fetch_headless


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
                f"{host}|{match}|{gov_id}|fallback|wo183_access_ladder_sweep|"
                f"{unit_name} -- WO-183 tier-3 pending, gov_id={gov_id}"
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
    "gov_kind",
    "population",
    "domain",
    "corrected_domain",
    "access_mode",
    "rung_answered",
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


# --- main driver ------------------------------------------------------


async def process_candidate(
    session: aiohttp.ClientSession, row: dict, covered_gov_ids: set, writer
) -> str:
    """Returns 'ok' or 'error' (for the consecutive-error breaker)."""
    gov_id = row["gov_id"]
    name = row["name"]
    state = row["state"]
    gov_kind = row["gov_kind"]
    population = row["population"]
    domain = row["domain"]
    known_platform_raw = row["known_platform"]
    hub_url = row["hub_url"]
    prior_url = row["prior_url"]

    base_report = dict(
        gov_id=gov_id,
        name=name,
        state=state,
        gov_kind=gov_kind,
        population=population,
        domain=domain,
        corrected_domain="",
        access_mode="",
        rung_answered="",
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

    home_source = prior_url or domain
    base_report_host = urlparse(wo147.normalize_home_url(home_source)).netloc

    ladder = await wo147.run_access_ladder(session, name, state, domain, prior_url)
    base_report["access_mode"] = ladder.access_mode
    base_report["rung_answered"] = ladder.rung_answered
    base_report["waf_family"] = ladder.waf_family
    if ladder.note:
        base_report["note"] = ladder.note

    corrected_netloc = urlparse(ladder.home_url).netloc if ladder.home_url else ""
    original_netloc = urlparse(wo147.normalize_home_url(domain)).netloc
    if corrected_netloc and original_netloc and corrected_netloc != original_netloc:
        base_report["corrected_domain"] = corrected_netloc

    host_for_access_log = corrected_netloc or base_report_host
    write_host_access_mode(host_for_access_log, ladder.access_mode, ladder.waf_family)

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

    if ladder.access_mode == "dead":
        writer.writerow(
            {
                **base_report,
                "outcome": "blocked",
                "reject_reason": "dns-unresolvable",
                "reject_class": "access",
            }
        )
        return "ok"

    if ladder.access_mode == "timeout":
        writer.writerow(
            {
                **base_report,
                "outcome": "blocked",
                "reject_reason": "timeout",
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

    # A rung produced a real page. Gather every (platform, url) hit: what
    # find_platform_link() saw, plus the row's own known_platform (a
    # vendor-badge hint from an earlier partial pass) against the home
    # url -- wo134's resolve_seed()/locate_platform_url() already know
    # how to guess a real seed (CivicPlus AgendaCenter, Granicus
    # ViewPublisher) from just a domain.
    hits: List[Tuple[str, str]] = []
    if ladder.platform and ladder.hit_url:
        hits.append((ladder.platform, ladder.hit_url))

    known_platform = wo147.normalize_known_platform(known_platform_raw)
    if known_platform and known_platform not in wo134.UNSUPPORTED_PLATFORMS:
        seed = hub_url or ladder.home_url or wo147.normalize_home_url(home_source)
        if not any(p == known_platform for p, _ in hits):
            hits.append((known_platform, seed))

    platform_found = ladder.platform or known_platform or ""
    base_report["platform_found"] = platform_found
    if ladder.hit_url:
        base_report["hit_url"] = ladder.hit_url

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
        write_discovery_seed(netloc, primary_platform, gov_id, ladder.access_mode)

    hit_source_urls = ";".join(f"{p}={u}" for p, u in hits[:6])
    base_report["candidates_listed"] = len(hits[:6])
    base_report["candidates_tried"] = len(hits[:6])

    synthetic_row = {
        "gov_id": gov_id,
        "unit_name": name,
        "homepage": ladder.home_url or wo147.normalize_home_url(home_source),
        "hop2_urls": "",
        "hit_source_urls": hit_source_urls,
    }

    try:
        result = await wo134.process_row(
            session, synthetic_row, covered_gov_ids, "wo183_access_ladder_sweep"
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
                status = await process_candidate(session, row, covered_gov_ids, writer)
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
