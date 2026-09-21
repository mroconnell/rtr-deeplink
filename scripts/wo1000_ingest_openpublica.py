"""WO-1000 (2026-09-21): resolve ONE meeting per government that
api.openpublica.com lists and the Archive does not have yet.

Structural copy of `wo184_ingest_found.py` (same two stages, same
reasoning, not reimplemented -- see that file's docstring), reading
`ingest_candidates.csv` from `rtr-business/research/openpublica_2026-09-21/`
instead of a sweep report. Each row already carries its `gov_id` (mapped
from OpenPublica's `government_id`, then hand-checked -- see that folder's
README) and up to four newest-first candidate meeting URLs, already
converted to the shapes this repo's adapters read (Granicus
`/player/clip/`, Cablecast `/internetchannel/show/`, Swagit `/videos/`).
`wo134.process_row()` tries them in order and stops at the first that
works, so a government gets at most one page or one queue line.

1. Tier 1 (real transcript): ingested by `process_row()` with the row's
   `gov_id` in the payload (WO-222), so the identity is the pinned one, not
   the adapter's guess. That matters here: Cablecast returns no
   jurisdiction at all, Swagit returned "TV, NY" for Larchmont, and the
   Fond du Lac Granicus tenant is the *county* board that the name-based
   ladder would file under the city.
2. Tier 3 (video, no transcript): handed to a pending file, probed
   (WO-144) for a dead link or too-short clip, then appended to
   `tier3_auto_transcription_queue.txt` with a shared-host pin in
   `tenant_overrides.csv` (Cablecast is a shared-host platform).

YouTube governments are NOT handled here: tier 2 goes to
`youtube_channel_leads.csv` for the drip Mac, never ingested from here.

Usage (from a worktree, set DATABASE_URL explicitly -- CLAUDE.md):
    python scripts/export_meeting_inventory.py --out-dir /tmp/op_inv --source export
    DATABASE_URL="sqlite+aiosqlite:////tmp/op.db" \\
        python3 scripts/wo1000_ingest_openpublica.py --inventory-csv /tmp/op_inv/meeting_inventory.csv
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

RESEARCH_DIR = (
    Path.home() / "Documents" / "rtr-business" / "research" / "openpublica_2026-09-21"
)
CANDIDATES_CSV = RESEARCH_DIR / "ingest_candidates.csv"
INGEST_REPORT_CSV = RESEARCH_DIR / "ingest_report.csv"
PENDING_CSV = RESEARCH_DIR / "tier3_pending.csv"

TIER3_QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"
TENANT_OVERRIDES_CSV = (
    REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "tenant_overrides.csv"
)

HOST_DELAY_SECONDS = 2.0
SOURCE_TAG = "wo1000_openpublica"

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
    "platform",
    "outcome",
    "reason",
    "meeting_url",
    "title",
    "date",
    "video_url",
    "page_url",
]


def load_candidate_rows() -> List[Dict[str, str]]:
    with CANDIDATES_CSV.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


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


def _pending_handler(
    *, gov_id, unit_name, platform, final_seed, hit_url, title, date, result
) -> None:
    """wo134.TIER3_HANDLER: same shape as wo184's, writing this WO's own
    pending file."""
    if final_seed in _pending_already_seen():
        return
    pin_row = ""
    if platform in wo134.SHARED_HOST_PLATFORMS:
        host = wo134._tenant_override_host(platform, result, final_seed)
        match = wo134._tenant_override_match(platform, result, final_seed)
        if host and match:
            pin_row = (
                f"{host}|{match}|{gov_id}|fallback|{SOURCE_TAG}|"
                f"{unit_name} -- OpenPublica government_id row, gov_id={gov_id}"
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


wo134.TIER3_HANDLER = _pending_handler


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


async def stage1_resolve(session: aiohttp.ClientSession, rows, covered_gov_ids) -> None:
    is_new = not INGEST_REPORT_CSV.exists()
    with INGEST_REPORT_CSV.open("a", newline="", encoding="utf-8") as rf:
        report_w = csv.DictWriter(
            rf, fieldnames=_INGEST_REPORT_FIELDS, lineterminator="\n"
        )
        if is_new:
            report_w.writeheader()
        for i, row in enumerate(rows):
            gov_id = row["gov_id"]
            synthetic_row = {
                "gov_id": gov_id,
                "unit_name": row["name"],
                "homepage": "",
                "hop2_urls": "",
                "hit_source_urls": row["hit_source_urls"],
            }
            if i:
                await asyncio.sleep(HOST_DELAY_SECONDS)
            try:
                result = await wo134.process_row(
                    session, synthetic_row, covered_gov_ids, SOURCE_TAG
                )
            except Exception as e:  # noqa: BLE001 -- log and keep going
                report_w.writerow(
                    {
                        "gov_id": gov_id,
                        "name": row["name"],
                        "outcome": "error",
                        "reason": f"process_row raised: {type(e).__name__}: {e}"[:300],
                    }
                )
                rf.flush()
                print(f"[{i + 1}/{len(rows)}] {gov_id} ERROR: {e}")
                continue
            report_w.writerow(
                {
                    "gov_id": gov_id,
                    "name": row["name"],
                    "platform": result.platform,
                    "outcome": result.outcome,
                    "reason": result.reason,
                    "meeting_url": result.seed_url,
                    "title": result.title,
                    "date": result.date,
                    "video_url": result.video_url,
                    "page_url": result.page_url,
                }
            )
            rf.flush()
            print(f"[{i + 1}/{len(rows)}] {gov_id}: {result.outcome} ({result.reason})")


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

    rows = load_candidate_rows()
    print(f"{len(rows)} candidate governments in {CANDIDATES_CSV.name}.")

    covered_gov_ids = wo134._load_covered_gov_ids(args.inventory_csv)
    print(
        f"{len(covered_gov_ids)} gov_ids already have an archived page (fresh export)."
    )

    async with aiohttp.ClientSession() as session:
        await stage1_resolve(session, rows, covered_gov_ids)

    await stage2_finish_tier3()

    print(f"\nFull ingest report: {INGEST_REPORT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
