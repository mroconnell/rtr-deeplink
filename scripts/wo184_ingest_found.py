"""WO-184 (2026-09-10/11): resolve/ingest the governments whose
`wo184_report.csv` outcome is "found" -- the retry-set sweep's
(`scripts/wo184_pilot.py`) alternate answered with a real platform link.

Direct structural copy of `wo181_ingest_found.py` with WO-184's own file
names -- same two-stage pipeline, same reasoning, not reimplemented (per
CLAUDE.md's "delegate rather than writing a redundant native parser"
convention, applied one level up again): reuses
`wo134_confirmed_hits_ingest.process_row()` for the real resolve/ingest
call, `app.platforms.queue_probe.probe_queue_entry()` (WO-144) for the
tier-3 "probe before queue" step, and the same shared-host tenant-pin
helpers wo134 already exposes.

1. For each found row, build the same `synthetic_row` shape
   wo147_access_ladder_sweep.py/wo181_ingest_found.py build (gov_id,
   unit_name, homepage, hop2_urls="", hit_source_urls="platform=hit_url")
   and call `wo134.process_row()`. A tier-1/2 result (real captions) is
   ingested directly by that call, POSTing to the Archive's own
   `POST /internal/ingest` -- this script never writes to the database
   itself, it is HTTP-only against the live Archive.
2. A tier-3 result (real video, no reachable captions) is NOT queued
   directly -- `wo134.TIER3_HANDLER` is pointed at a pending-row writer
   here (`wo184_tier3_pending.csv`), so every tier-3 candidate is probed
   (`probe_queue_entry()`) for a dead link or a too-short clip before it
   ever reaches the real queue file. Accepted candidates are appended to
   the shared `scripts/tier3_auto_transcription_queue.txt` and (for a
   shared host like YouTube/Vimeo/TelVue/Cablecast) pinned in
   `app/utils/jurisdiction_data/tenant_overrides.csv` at `fallback`
   strength -- both using wo134's own existing-entry/existing-pin dedup
   helpers, so a re-run never double-queues or double-pins.

Deliberately does NOT import wo147_access_ladder_sweep.py -- see
coverage_alternates.rungs_2_3_ladder_fn's docstring for why (that
module's own top level would silently redirect this script's tier-3
candidates into wo147's OWN pending file). This script sets
`wo134.TIER3_HANDLER` itself, after importing
`wo134_confirmed_hits_ingest` directly and nothing else that touches it.

Also writes `wo184_discovery_seeds.csv` (gov_id, tenant, platform,
access_mode) for every found government's answering tenant, per the
brief's "hand any answering tenant to rtr-discovery as a seed row"
instruction -- this script never touches rtr-discovery's own code or
ledger, only this one plain CSV in rtr-business/research.

If the YouTube caption-block signature (429 / "Sign in to confirm you're
not a bot") ever surfaces on a found YouTube candidate, `wo134.
process_row()`'s own existing handling already routes that to tier-3
(never a direct tier-1/2 ingest attempt) -- nothing extra is needed here
for that case, but the run's own printed outcomes should be checked for
it and called out plainly in the report if it appears.

Usage:
    python scripts/export_meeting_inventory.py --out-dir /tmp/wo184_inv --source export
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo184_ingest.db" \\
        python3 scripts/wo184_ingest_found.py --inventory-csv /tmp/wo184_inv/meeting_inventory.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
import time
from pathlib import Path
from typing import Dict, List
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

import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
REPORT_CSV = RESEARCH_DIR / "wo184_report.csv"
INGEST_REPORT_CSV = RESEARCH_DIR / "wo184_ingest_report.csv"
PENDING_CSV = RESEARCH_DIR / "wo184_tier3_pending.csv"
DISCOVERY_SEEDS_CSV = RESEARCH_DIR / "wo184_discovery_seeds.csv"

TIER3_QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"
TENANT_OVERRIDES_CSV = (
    REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "tenant_overrides.csv"
)

HOST_DELAY_SECONDS = 2.0

_TIER3_PENDING_FIELDS = [
    "gov_id",
    "platform",
    "meeting_url",
    "video_url",
    "source_url",
    "jurisdiction",
    "pin_row",
]

_INGEST_REPORT_FIELDS = [
    "gov_id",
    "name",
    "answered_domain",
    "platform",
    "hit_url",
    "outcome",
    "reason",
    "meeting_url",
    "video_url",
    "page_url",
]


def load_found_rows() -> List[Dict[str, str]]:
    if not REPORT_CSV.exists():
        return []
    with REPORT_CSV.open(newline="", encoding="utf-8") as f:
        return [r for r in csv.DictReader(f) if r.get("outcome") == "found"]


_pending_seen: set = None


def _pending_already_seen() -> set:
    global _pending_seen
    if _pending_seen is None:
        seen = set()
        if PENDING_CSV.exists():
            with PENDING_CSV.open(newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    seen.add(r.get("meeting_url", ""))
        _pending_seen = seen
    return _pending_seen


def _wo184_tier3_pending_handler(
    *, gov_id, unit_name, platform, final_seed, hit_url, title, date, result
) -> None:
    """wo134.TIER3_HANDLER for this script -- same shape as
    wo181_ingest_found.py's own handler, writing to THIS WO's own
    pending file instead."""
    if final_seed in _pending_already_seen():
        return
    pin_row = ""
    if platform in wo134.SHARED_HOST_PLATFORMS:
        host = wo134._tenant_override_host(platform, result, final_seed)
        match = wo134._tenant_override_match(platform, result, final_seed)
        if host and match:
            pin_row = (
                f"{host}|{match}|{gov_id}|fallback|wo184_ingest_found|"
                f"{unit_name} -- WO-184 alternate-domain find, gov_id={gov_id}"
            )
    is_new = not PENDING_CSV.exists()
    with PENDING_CSV.open("a", newline="", encoding="utf-8") as f:
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
    _pending_already_seen().add(final_seed)


wo134.TIER3_HANDLER = _wo184_tier3_pending_handler


def _existing_override_keys() -> set:
    keys = set()
    if TENANT_OVERRIDES_CSV.exists():
        with TENANT_OVERRIDES_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                keys.add((r.get("tenant_host", ""), r.get("match", "")))
    return keys


def _apply_pin_row(pin_row: str, existing_keys: set) -> None:
    if not pin_row:
        return
    parts = pin_row.split("|", 5)
    if len(parts) != 6:
        print(f"WARNING: malformed pin_row, skipping: {pin_row!r}", file=sys.stderr)
        return
    tenant_host, match, gov_id, strength, source, evidence = parts
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


async def stage1_resolve(
    session: aiohttp.ClientSession, found_rows, covered_gov_ids
) -> None:
    is_new = not INGEST_REPORT_CSV.exists()
    seeds_is_new = not DISCOVERY_SEEDS_CSV.exists()
    with (
        INGEST_REPORT_CSV.open("a", newline="", encoding="utf-8") as rf,
        DISCOVERY_SEEDS_CSV.open("a", newline="", encoding="utf-8") as sf,
    ):
        report_w = csv.DictWriter(
            rf, fieldnames=_INGEST_REPORT_FIELDS, lineterminator="\n"
        )
        if is_new:
            report_w.writeheader()
        seeds_w = csv.DictWriter(
            sf,
            fieldnames=["gov_id", "tenant", "platform", "access_mode"],
            lineterminator="\n",
        )
        if seeds_is_new:
            seeds_w.writeheader()

        for i, row in enumerate(found_rows):
            gov_id = row["gov_id"]
            platform = row.get("platform_found", "")
            hit_url = row.get("hit_url", "")
            answered_domain = row.get("answered_domain", "")

            synthetic_row = {
                "gov_id": gov_id,
                "unit_name": row.get("name", ""),
                "homepage": f"https://{answered_domain}" if answered_domain else "",
                "hop2_urls": "",
                "hit_source_urls": f"{platform}={hit_url}"
                if platform and hit_url
                else "",
            }

            if i:
                await asyncio.sleep(HOST_DELAY_SECONDS)

            try:
                result = await wo134.process_row(
                    session, synthetic_row, covered_gov_ids, "wo184_ingest_found"
                )
            except Exception as e:  # noqa: BLE001 -- log and keep going
                report_w.writerow(
                    {
                        "gov_id": gov_id,
                        "name": row.get("name", ""),
                        "answered_domain": answered_domain,
                        "platform": platform,
                        "hit_url": hit_url,
                        "outcome": "error",
                        "reason": f"process_row raised: {type(e).__name__}: {e}"[:300],
                        "meeting_url": "",
                        "video_url": "",
                        "page_url": "",
                    }
                )
                print(f"[{i + 1}/{len(found_rows)}] {gov_id} ERROR: {e}")
                continue

            report_w.writerow(
                {
                    "gov_id": gov_id,
                    "name": row.get("name", ""),
                    "answered_domain": answered_domain,
                    "platform": result.platform or platform,
                    "hit_url": hit_url,
                    "outcome": result.outcome,
                    "reason": result.reason,
                    "meeting_url": result.seed_url,
                    "video_url": result.video_url,
                    "page_url": result.page_url,
                }
            )
            rf.flush()
            print(
                f"[{i + 1}/{len(found_rows)}] {gov_id}: {result.outcome} ({result.reason})"
            )

            netloc = urlparse(hit_url).netloc if hit_url else ""
            if netloc:
                seeds_w.writerow(
                    {
                        "gov_id": gov_id,
                        "tenant": netloc,
                        "platform": platform,
                        "access_mode": row.get("access_mode", ""),
                    }
                )
                sf.flush()


async def stage2_finish_tier3() -> None:
    if not PENDING_CSV.exists():
        print(f"No {PENDING_CSV.name} -- no tier-3 candidates this run.")
        return
    with PENDING_CSV.open(newline="", encoding="utf-8") as f:
        pending_rows = list(csv.DictReader(f))
    if not pending_rows:
        print("Pending file is empty -- nothing to probe.")
        return
    print(f"\n{len(pending_rows)} tier-3 pending row(s) to probe.")

    existing_queue_urls = wo134._existing_tier3_queue_urls()
    existing_override_keys = _existing_override_keys()

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
            _apply_pin_row(row.get("pin_row", ""), existing_override_keys)
        else:
            rejected += 1

    print(
        f"\nTier-3 finish: {accepted} accepted (queued), {rejected} rejected by probe."
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--inventory-csv",
        type=Path,
        required=True,
        help="fresh export_meeting_inventory.py CSV (--source export) -- run that first",
    )
    args = parser.parse_args()

    if not wo134._base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (check .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    register_all_finders()

    found_rows = load_found_rows()
    print(f"{len(found_rows)} 'found' rows in {REPORT_CSV.name}.")
    if not found_rows:
        return

    covered_gov_ids = wo134._load_covered_gov_ids(args.inventory_csv)
    print(
        f"{len(covered_gov_ids)} gov_ids already have an archived page (fresh export)."
    )

    async with aiohttp.ClientSession() as session:
        await stage1_resolve(session, found_rows, covered_gov_ids)

    await stage2_finish_tier3()

    print(f"\nFull ingest report: {INGEST_REPORT_CSV}")
    print(f"Discovery seeds: {DISCOVERY_SEEDS_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
