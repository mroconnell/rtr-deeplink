"""WO-258 (2026-09-11): the alternate-domain one hop, step A, for the
WO-174 leftover population.

`~/Documents/rtr-business/research/wo174_leftover_5k_plus.csv` holds 1,484
governments of 5,000+ that WO-174's CivicPlus AgendaCenter guess reached,
found nothing on, and that still have no platform and no Archive page.
This script works the 466 rows flagged `step_alt_hop=yes` -- each carries
a real second domain or URL (`alternate_domains`/`alternate_urls`) that no
sweep has run the access ladder on yet.

Ryan's rule, verbatim (2026-09-10, `docs/COVERAGE_HANDOVER.md` section 4):

    "A domain keeps priority when it has produced a resolved meeting ...
    If a domain has produced no meeting at all, we may simply be looking
    at the wrong domain, and we lose nothing by trying another."

Real example this population was built from: Gooding County, ID is
recorded on `goodingcountyid.gov`, but its real meetings live at
`goodingcounty.org/agendacenter`, a CivicPlus site under a completely
different hostname.

This is a two-pass script, same shape as `scripts/wo230_agendacenter_
followup.py`'s WO-249 hand-read gate:

Pass 1 (`--stage ladder`): for every row, run the FULL access ladder
(`scripts/wo147_access_ladder_sweep.run_access_ladder` -- plain HTTP,
browser headers after a 403/dropped connection, headless only for a
loaded page with no visible link, stop at a human-verification gate) on
each alternate domain/URL in turn (the PRIMARY domain is not re-tested --
`prior_reject_reason` already reflects a real prior test of it). Stops at
the first alternate that finds a platform link. Writes
`wo258_report.csv` (reach + find columns) and, for every row where a
platform link was found, resolves it through
`wo134_confirmed_hits_ingest`'s real platform finders (`locate_platform_
url`/`resolve_seed`) to check for a real meeting and video. A video
candidate that clears the automatic checks is PARKED in
`wo258_pending_hand_read.csv` rather than ingested -- see the
`IDENTITY_CHECK_HOOK` wiring below -- per Ryan's 2026-09-11 rule that no
candidate may become a page or queue line without a human (here: this
session, reading title/channel/description) recording a one-line reason
it is a real public-body meeting of THIS government.

Pass 2 (`--stage finish`, run after `wo258_hand_read_decisions.csv` has
been filled in by hand): re-runs the exact same resolve step. Approved
candidates ingest for real (tier1/2 direct, tier3 through the shared
probe-before-queue helper); rejected candidates stay skipped permanently.

Usage:
    python scripts/export_meeting_inventory.py --out-dir /tmp/wo258_inv --source export
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo258.db" \\
        python3 scripts/wo258_alt_hop_sweep.py --stage ladder [--limit N]
    # ... hand-read wo258_pending_hand_read.csv, write wo258_hand_read_decisions.csv ...
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo258.db" \\
        python3 scripts/wo258_alt_hop_sweep.py --stage finish \\
            --inventory-csv /tmp/wo258_inv/meeting_inventory.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.queue_probe import (  # noqa: E402
    DEFAULT_SIDECAR_PATH,
    append_probe_row,
    probe_queue_entry,
)

from scripts.bulk_ingest import _base_url  # noqa: E402
from scripts.coverage_alternates import candidate_domains, normalize_host  # noqa: E402
from scripts.wo147_access_ladder_sweep import (  # noqa: E402
    looks_like_document_hub,
    run_access_ladder,
)

import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
CANDIDATES_CSV = RESEARCH_DIR / "wo174_leftover_5k_plus.csv"
REPORT_CSV = RESEARCH_DIR / "wo258_report.csv"
PENDING_HAND_READ_CSV = RESEARCH_DIR / "wo258_pending_hand_read.csv"
HAND_READ_DECISIONS_CSV = RESEARCH_DIR / "wo258_hand_read_decisions.csv"
PENDING_TIER3_CSV = RESEARCH_DIR / "wo258_tier3_pending.csv"

TIER3_QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"
TENANT_OVERRIDES_CSV = (
    REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "tenant_overrides.csv"
)

HOST_DELAY_SECONDS = 2.0
GOV_DELAY_SECONDS = 2.0
MAX_CONSECUTIVE_ERRORS = 6

REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "population",
    "prior_reject_reason",
    "primary_domain",
    "alternate_tried",
    "reach",
    "access_mode",
    "find",
    "platform_found",
    "hit_url",
    "note",
]


def load_candidates() -> List[Dict[str, str]]:
    with CANDIDATES_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = [r for r in rows if (r.get("step_alt_hop") or "").strip().lower() == "yes"]
    # Counties first (the best video source historically), then everything
    # else, each tier by population descending -- same order rationale as
    # every other WO-184-shaped sweep in this repo.
    counties = [r for r in out if (r.get("gov_kind") or "").strip().lower() == "county"]
    other = [r for r in out if r not in counties]

    def pop(r: Dict[str, str]) -> float:
        try:
            return float((r.get("population") or "0").replace(",", ""))
        except ValueError:
            return 0.0

    counties.sort(key=pop, reverse=True)
    other.sort(key=pop, reverse=True)
    return counties + other


def _row_alternates(row: Dict[str, str]) -> List[str]:
    """Every alternate candidate for this row, normalized, deduped,
    EXCLUDING the primary `domain` -- the primary already has a real
    `prior_reject_reason` from an earlier full-ladder test, so this
    script (per its own brief) only tests the untested alternates."""
    all_candidates = candidate_domains(
        {
            "domain": row.get("domain", ""),
            "alternate_domains": row.get("alternate_domains", ""),
            "alternate_urls": row.get("alternate_urls", ""),
        }
    )
    primary = normalize_host(row.get("domain", ""))
    return [c for c in all_candidates if c != primary]


def already_done_gov_ids() -> set:
    if not REPORT_CSV.exists():
        return set()
    with REPORT_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f) if r.get("gov_id")}


def report_writer():
    is_new = not REPORT_CSV.exists()
    f = REPORT_CSV.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=REPORT_FIELDS, lineterminator="\n")
    if is_new:
        w.writeheader()
        f.flush()
    return f, w


def append_csv_row(path: Path, fieldnames: List[str], row: dict) -> None:
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        if is_new:
            w.writeheader()
        w.writerow(row)


# --------------------------------------------------------------------------
# Pass 1: the ladder on each alternate
# --------------------------------------------------------------------------


async def ladder_one_row(session: aiohttp.ClientSession, row: Dict[str, str]) -> dict:
    alternates = _row_alternates(row)
    base = {
        "gov_id": row.get("gov_id", ""),
        "name": row.get("name", ""),
        "state": row.get("state", ""),
        "gov_kind": row.get("gov_kind", ""),
        "population": row.get("population", ""),
        "prior_reject_reason": row.get("prior_reject_reason", ""),
        "primary_domain": row.get("domain", ""),
    }
    if not alternates:
        return {
            **base,
            "alternate_tried": "",
            "reach": "dead",
            "access_mode": "",
            "find": "nothing",
            "platform_found": "",
            "hit_url": "",
            "note": "no alternate candidate after normalization",
        }

    last_result = None
    last_alt = ""
    for i, alt in enumerate(alternates):
        if i:
            await asyncio.sleep(HOST_DELAY_SECONDS)
        result = await run_access_ladder(
            session, row.get("name", ""), row.get("state", ""), alt, ""
        )
        last_result = result
        last_alt = alt
        if result.platform and result.hit_url:
            break
        if result.access_mode == "challenge":
            # a human-verification gate -- never retry past it, but a
            # DIFFERENT alternate on this same row is still worth trying.
            continue

    assert last_result is not None
    r = last_result

    if r.platform and r.hit_url:
        reach = "answered"
        find = "platform"
        access_mode = r.access_mode
    elif r.access_mode in ("dead", "timeout"):
        reach = "dead"
        find = "nothing"
        access_mode = r.access_mode
    elif r.access_mode in (
        "blocked-plain-http",
        "blocked-browser-headers",
        "challenge",
    ):
        reach = "blocked"
        find = "nothing"
        access_mode = r.access_mode
    else:
        reach = "answered"
        access_mode = r.access_mode
        find = (
            "meetings-page"
            if r.final_html and looks_like_document_hub(r.final_html)
            else "nothing"
        )

    return {
        **base,
        "alternate_tried": ";".join(alternates[: alternates.index(last_alt) + 1]),
        "reach": reach,
        "access_mode": access_mode,
        "find": find,
        "platform_found": r.platform or "",
        "hit_url": r.hit_url or "",
        "note": r.note,
    }


async def stage_ladder(limit: Optional[int]) -> None:
    candidates = load_candidates()
    print(f"{len(candidates)} step_alt_hop=yes rows in {CANDIDATES_CSV.name}.")

    done = already_done_gov_ids()
    print(f"{len(done)} gov_ids already in {REPORT_CSV.name} -- skipping those.")

    to_process = [r for r in candidates if r.get("gov_id", "") not in done]
    if limit:
        to_process = to_process[:limit]
    print(f"Processing {len(to_process)} rows this run.\n")

    tally: Dict[str, int] = {}
    report_f, writer = report_writer()
    consecutive_errors = 0
    try:
        async with aiohttp.ClientSession() as session:
            for i, row in enumerate(to_process):
                started = time.monotonic()
                try:
                    result_row = await ladder_one_row(session, row)
                    consecutive_errors = 0
                except Exception as e:  # noqa: BLE001 -- log and keep going
                    result_row = {
                        "gov_id": row.get("gov_id", ""),
                        "name": row.get("name", ""),
                        "state": row.get("state", ""),
                        "gov_kind": row.get("gov_kind", ""),
                        "population": row.get("population", ""),
                        "prior_reject_reason": row.get("prior_reject_reason", ""),
                        "primary_domain": row.get("domain", ""),
                        "alternate_tried": "",
                        "reach": "error",
                        "access_mode": "",
                        "find": "error",
                        "platform_found": "",
                        "hit_url": "",
                        "note": f"{type(e).__name__}: {e}"[:300],
                    }
                    consecutive_errors += 1
                writer.writerow(result_row)
                report_f.flush()
                key = f"{result_row['reach']}/{result_row['find']}"
                tally[key] = tally.get(key, 0) + 1
                elapsed = time.monotonic() - started
                print(
                    f"[{i + 1}/{len(to_process)}] {result_row['name']}, "
                    f"{result_row['state']}: {key} "
                    f"{result_row['platform_found']} ({elapsed:.1f}s)"
                )
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(
                        f"\nABORTING: {consecutive_errors} consecutive errors.",
                        file=sys.stderr,
                    )
                    break
                if i < len(to_process) - 1:
                    await asyncio.sleep(GOV_DELAY_SECONDS)
    finally:
        report_f.close()

    print("\n--- Ladder tally (this run) ---")
    for k, v in sorted(tally.items()):
        print(f"{k:28} {v}")
    print(f"\nFull report: {REPORT_CSV}")


# --------------------------------------------------------------------------
# Pass 2: resolve platform-found rows into a real meeting, gated by hand-read
# --------------------------------------------------------------------------

_HAND_READ_DECISIONS: Dict[tuple, dict] = {}
_pending_hand_read_seen: set = set()


def _load_hand_read_decisions() -> Dict[tuple, dict]:
    out: Dict[tuple, dict] = {}
    if HAND_READ_DECISIONS_CSV.exists():
        with HAND_READ_DECISIONS_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out[(r.get("gov_id") or "", r.get("video_url") or "")] = r
    return out


def _load_pending_seen() -> set:
    seen = set()
    if PENDING_HAND_READ_CSV.exists():
        with PENDING_HAND_READ_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                seen.add((r.get("gov_id") or "", r.get("video_url") or ""))
    return seen


PENDING_HAND_READ_FIELDS = [
    "gov_id",
    "name",
    "state",
    "title",
    "video_channel",
    "video_url",
    "meeting_url",
    "platform",
    "hit_url",
    "tier",
]

HAND_READ_DECISION_FIELDS = ["gov_id", "video_url", "decision", "kind", "reason"]


def _hand_read_hook(
    row, platform, result, final_seed, effective_title
) -> Optional[str]:
    """IDENTITY_CHECK_HOOK -- called by wo134.process_row() only when the
    resolved candidate has real video, right before it would otherwise be
    ingested. Returns a truthy string to skip this hit (process_row tries
    the row's next platform hit, if any); returns None/falsy to let the
    ingest proceed. See this module's docstring for the two-pass design."""
    gov_id = row.get("gov_id", "")
    video_url = getattr(result, "video_url", "") or ""
    # BoxCast resolves a fresh SIGNED playlist URL at every view (WO-229)
    # -- the same broadcast gets a different video_url each time this
    # hook runs, so keying a decision on video_url would never match on
    # the second (finish-stage) resolve. video_channel (the stable
    # boxcast:<channel_id> pin discriminator, per CLAUDE.md's "pin a
    # BoxCast channel only" rule) is the right key for this platform;
    # every other platform's video_url is stable across resolves.
    dedup_key_value = (
        getattr(result, "video_channel", "") or video_url
        if platform == "boxcast"
        else video_url
    )
    key = (gov_id, dedup_key_value)

    decision = _HAND_READ_DECISIONS.get(key)
    if decision is not None:
        if (decision.get("decision") or "").strip().lower() == "approve":
            return None
        return f"hand-read rejected ({decision.get('kind', '')}): {decision.get('reason', '')}"

    if key not in _pending_hand_read_seen:
        _pending_hand_read_seen.add(key)
        tier = "tier1" if getattr(result, "segments", None) else "tier3"
        append_csv_row(
            PENDING_HAND_READ_CSV,
            PENDING_HAND_READ_FIELDS,
            {
                "gov_id": gov_id,
                "name": row.get("unit_name", ""),
                "state": row.get("state", ""),
                "title": effective_title or "",
                "video_channel": getattr(result, "video_channel", "") or "",
                # NOTE: for boxcast this is the stable decision key
                # (video_channel), not the literal (unstable, freshly
                # re-signed each resolve -- WO-229) video_url -- see the
                # comment above dedup_key_value's definition. Every other
                # platform's video_url is stable, so this is the same
                # value there.
                "video_url": dedup_key_value,
                "meeting_url": final_seed,
                "platform": platform,
                "hit_url": row.get("hit_source_urls", ""),
                "tier": tier,
            },
        )
    return "awaiting-hand-read"


wo134.IDENTITY_CHECK_HOOK = _hand_read_hook


_pending_tier3_seen: set = set()


def _tier3_pending_handler(
    *, gov_id, unit_name, platform, final_seed, hit_url, title, date, result
) -> None:
    if final_seed in _pending_tier3_seen:
        return
    _pending_tier3_seen.add(final_seed)
    pin_row = ""
    if platform in wo134.SHARED_HOST_PLATFORMS:
        host = wo134._tenant_override_host(platform, result, final_seed)
        match = wo134._tenant_override_match(platform, result, final_seed)
        if host and match:
            pin_row = (
                f"{host}|{match}|{gov_id}|fallback|wo258_alt_hop_sweep|"
                f"{unit_name} -- WO-258 alt-hop lead, gov_id={gov_id}"
            )
    append_csv_row(
        PENDING_TIER3_CSV,
        [
            "gov_id",
            "platform",
            "meeting_url",
            "video_url",
            "source_url",
            "jurisdiction",
            "pin_row",
        ],
        {
            "gov_id": gov_id,
            "platform": platform,
            "meeting_url": final_seed,
            "video_url": result.video_url or final_seed,
            "source_url": hit_url,
            "jurisdiction": result.jurisdiction or "",
            "pin_row": pin_row,
        },
    )


wo134.TIER3_HANDLER = _tier3_pending_handler


def load_platform_found_rows() -> List[Dict[str, str]]:
    if not REPORT_CSV.exists():
        return []
    with REPORT_CSV.open(newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r.get("find") == "platform"]


def already_resolved_gov_ids(path: Path) -> set:
    """A gov_id is 'done' (skipped on the next --stage resolve run)
    unless its LAST recorded row is a "skipped" outcome still awaiting a
    hand-read decision -- a genuinely terminal skip (title-safety
    rejection, "no usable video on this platform", etc.) gains nothing
    from being re-resolved, since the underlying network result won't
    change; only a row parked by the hand-read gate (reason contains
    "awaiting-hand-read" or a decided rejection already applied) needs
    the resolve step to run again, and only because a decision may now
    exist for it. Without this, every re-run re-resolves the entire
    "platform found" population from scratch, most of it for the
    identical unchanged answer."""
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    last_row: Dict[str, dict] = {}
    for r in rows:
        gid = r.get("gov_id")
        if gid:
            last_row[gid] = r
    out = set()
    for gid, r in last_row.items():
        outcome = (r.get("outcome") or "").strip()
        if not outcome:
            continue
        if outcome == "skipped" and "awaiting-hand-read" in (r.get("reason") or ""):
            continue
        out.add(gid)
    return out


RESOLVE_REPORT_CSV = RESEARCH_DIR / "wo258_resolve_report.csv"
RESOLVE_REPORT_FIELDS = [
    "gov_id",
    "name",
    "platform",
    "hit_url",
    "outcome",
    "reason",
    "meeting_url",
    "title",
    "video_url",
    "page_url",
]


async def stage_resolve(limit: Optional[int]) -> None:
    global _HAND_READ_DECISIONS, _pending_hand_read_seen

    if not _base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (check .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    register_all_finders()
    _HAND_READ_DECISIONS = _load_hand_read_decisions()
    _pending_hand_read_seen = _load_pending_seen()
    print(f"{len(_HAND_READ_DECISIONS)} hand-read decisions on file.")

    rows = load_platform_found_rows()
    print(f"{len(rows)} rows with a platform found in {REPORT_CSV.name}.")

    done = already_resolved_gov_ids(RESOLVE_REPORT_CSV)
    print(f"{len(done)} gov_ids already resolved (non-skip outcome) -- skipping those.")

    to_process = [r for r in rows if r.get("gov_id", "") not in done]
    if limit:
        to_process = to_process[:limit]
    print(f"Resolving {len(to_process)} rows this run.\n")

    covered_gov_ids: set = set()  # no fresh export needed here -- WO-258's own
    # candidate list is already filtered to governments with no Archive
    # page in jurisdiction_coverage.csv terms; a genuine identity-join
    # dup is caught downstream by process_row's own dedup key.

    tally: Dict[str, int] = {}
    is_new = not RESOLVE_REPORT_CSV.exists()
    async with aiohttp.ClientSession() as session:
        with RESOLVE_REPORT_CSV.open("a", newline="", encoding="utf-8") as rf:
            w = csv.DictWriter(
                rf, fieldnames=RESOLVE_REPORT_FIELDS, lineterminator="\n"
            )
            if is_new:
                w.writeheader()
            for i, row in enumerate(to_process):
                if i:
                    await asyncio.sleep(HOST_DELAY_SECONDS)
                synthetic = {
                    "gov_id": row.get("gov_id", ""),
                    "unit_name": row.get("name", ""),
                    "state": row.get("state", ""),
                    "homepage": f"https://{row.get('alternate_tried', '').split(';')[-1]}"
                    if row.get("alternate_tried")
                    else "",
                    "hop2_urls": "",
                    "hit_source_urls": f"{row.get('platform_found', '')}={row.get('hit_url', '')}",
                }
                try:
                    result = await wo134.process_row(
                        session, synthetic, covered_gov_ids, "wo258_alt_hop_sweep"
                    )
                except Exception as e:  # noqa: BLE001
                    outcome_row = {
                        "gov_id": row.get("gov_id", ""),
                        "name": row.get("name", ""),
                        "platform": row.get("platform_found", ""),
                        "hit_url": row.get("hit_url", ""),
                        "outcome": "error",
                        "reason": f"{type(e).__name__}: {e}"[:300],
                        "meeting_url": "",
                        "title": "",
                        "video_url": "",
                        "page_url": "",
                    }
                else:
                    outcome_row = {
                        "gov_id": result.gov_id,
                        "name": result.unit_name,
                        "platform": result.platform,
                        "hit_url": row.get("hit_url", ""),
                        "outcome": result.outcome,
                        "reason": result.reason,
                        "meeting_url": result.seed_url,
                        "title": result.title,
                        "video_url": result.video_url,
                        "page_url": result.page_url,
                    }
                w.writerow(outcome_row)
                rf.flush()
                tally[outcome_row["outcome"]] = tally.get(outcome_row["outcome"], 0) + 1
                print(
                    f"[{i + 1}/{len(to_process)}] {outcome_row['gov_id']} "
                    f"{outcome_row['name']!r}: {outcome_row['outcome']} -- "
                    f"{outcome_row['reason']}"
                )

    print("\n--- Resolve tally (this run) ---")
    for k, v in sorted(tally.items()):
        print(f"{k:24} {v}")
    print(f"\nFull report: {RESOLVE_REPORT_CSV}")
    if PENDING_HAND_READ_CSV.exists():
        print(f"Hand-read pending: {PENDING_HAND_READ_CSV}")


async def stage_finish_tier3() -> None:
    if not PENDING_TIER3_CSV.exists():
        print(f"No {PENDING_TIER3_CSV.name} -- nothing to probe.")
        return
    with PENDING_TIER3_CSV.open(newline="", encoding="utf-8") as f:
        pending_rows = list(csv.DictReader(f))
    if not pending_rows:
        print("Pending tier-3 file is empty.")
        return
    print(f"\n{len(pending_rows)} tier-3 pending row(s) to probe.")

    existing_queue_urls = wo134._existing_tier3_queue_urls()
    existing_override_keys = wo134._existing_override_keys()

    accepted, rejected = 0, 0
    last_call_by_host: Dict[str, float] = {}
    for i, row in enumerate(pending_rows):
        host = urlparse(row["meeting_url"]).netloc
        last = last_call_by_host.get(host)
        if last is not None:
            remaining = HOST_DELAY_SECONDS - (time.monotonic() - last)
            if remaining > 0:
                await asyncio.sleep(remaining)
        last_call_by_host[host] = time.monotonic()

        result = await probe_queue_entry(
            row["meeting_url"],
            video_url=row.get("video_url") or None,
            source_page_url=row.get("source_url") or None,
        )
        append_probe_row(DEFAULT_SIDECAR_PATH, result)
        print(
            f"[{i + 1}/{len(pending_rows)}] [{result.verdict}] {row['gov_id']} "
            f"{row['meeting_url']} -- {result.reason or f'{result.duration_seconds:.1f}s'}"
        )

        if result.verdict in ("accept", "flag-long"):
            accepted += 1
            queue_line = row["meeting_url"]
            if row.get("source_url"):
                queue_line = f"{queue_line}\t{row['source_url']}"
            if row["meeting_url"] not in existing_queue_urls:
                with TIER3_QUEUE_FILE.open("a", encoding="utf-8") as qf:
                    qf.write(queue_line + "\n")
                existing_queue_urls.add(row["meeting_url"])
            pin_row = row.get("pin_row", "")
            if pin_row:
                parts = pin_row.split("|", 5)
                if len(parts) == 6:
                    tenant_host, match, gov_id, strength, source, evidence = parts
                    key = (tenant_host, match)
                    if key not in existing_override_keys:
                        append_csv_row(
                            TENANT_OVERRIDES_CSV,
                            [
                                "tenant_host",
                                "match",
                                "gov_id",
                                "strength",
                                "source",
                                "evidence",
                            ],
                            {
                                "tenant_host": tenant_host,
                                "match": match,
                                "gov_id": gov_id,
                                "strength": strength,
                                "source": source,
                                "evidence": evidence,
                            },
                        )
                        existing_override_keys.add(key)
        else:
            rejected += 1

    print(
        f"\nTier-3 finish: {accepted} accepted (queued), {rejected} rejected by probe."
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--stage", choices=["ladder", "resolve", "finish"], required=True
    )
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if args.stage == "ladder":
        await stage_ladder(args.limit)
    elif args.stage == "resolve":
        await stage_resolve(args.limit)
    elif args.stage == "finish":
        await stage_resolve(args.limit)  # picks up newly-approved hand-read decisions
        await stage_finish_tier3()


if __name__ == "__main__":
    asyncio.run(main())
