"""WO-184 continuation (2026-09-11): verify and resolve the one-hop
sweep's "different platform found" leads (`scripts/wo184_onehop_pilot.py`'s
`wo184_onehop_report.csv`, outcome `different-platform-found`).

Why this exists: `wo184_onehop_pilot.py` only confirms a platform LINK
exists on the alternate domain -- it never resolves that link into a real
meeting or checks for video (see that script's own docstring and
`BACKLOG.md`'s WO-184 residual entry, "resolve/ingest the one-hop
leads"). BACKLOG_DONE.md's WO-184 entry's own hand-check of a sample of
these leads found about a quarter are redirects of the exact same site
that only looked "different" because the row had no platform recorded
yet to compare against -- not a genuinely independent second source. This
script drops those first, then resolves the rest for real.

Two steps per lead:

1. **Same-site-redirect check.** Fetch the alternate domain's home page
   once more (plain HTTP, honest headers -- same rung the one-hop pilot
   itself used) and compare its RESOLVED final URL's host against the
   row's primary domain's host (both normalized the same way
   `coverage_alternates.normalize_host()` does). If they match, this is
   the same website under a different-looking address on file, not a
   second platform -- recorded as `same-site-redirect` and skipped
   (never ingested).
2. **Resolve/ingest.** Everything else goes through the exact same
   `wo134_confirmed_hits_ingest.process_row()` pipeline every other
   WO-184 ingest step uses -- tier-1/2 (real captions) ingests directly
   against the live Archive; tier-3 (video, no reachable captions) is
   probed (`app.platforms.queue_probe.probe_queue_entry()`) before
   joining the shared tier-3 queue, exactly like `wo184_ingest_found.py`.
   This is a DIRECT STRUCTURAL COPY of that script's own two-stage
   pipeline and TIER3_HANDLER wiring, pointed at this WO's own report/
   pending file names -- see that script's docstring for the reasoning
   (not repeated here).

READS `wo184_onehop_report.csv` (produced by `wo184_onehop_pilot.py`),
WRITES `wo184_onehop_ingest_report.csv` (per-lead verdict:
`same-site-redirect` / `ingested_tier1_2` / `queued_tier3_pending` /
`rejected_by_probe` / `already_covered` / `skipped` / `error`) and
`wo184_onehop_tier3_pending.csv` (its own pending file, same shape as
`wo184_ingest_found.py`'s). This script never writes
jurisdiction_coverage.csv itself -- same read-mostly split every WO-184
script uses; a later apply pass (or a hand extension of
`wo184_apply_to_jc.py`) writes the research file from this script's
report, same as every other WO-184 stage.

Usage:
    python scripts/export_meeting_inventory.py --out-dir /tmp/wo184_inv --source export
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo184_onehop_ingest.db" \\
        python3 scripts/wo184_onehop_ingest.py --inventory-csv /tmp/wo184_inv/meeting_inventory.csv
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

from scripts.coverage_alternates import normalize_host  # noqa: E402
from scripts.wo147_access_ladder_sweep import HONEST_HEADERS, fetch_one  # noqa: E402

import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
ONEHOP_REPORT_CSV = RESEARCH_DIR / "wo184_onehop_report.csv"
INGEST_REPORT_CSV = RESEARCH_DIR / "wo184_onehop_ingest_report.csv"
PENDING_CSV = RESEARCH_DIR / "wo184_onehop_tier3_pending.csv"

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
    "primary_domain",
    "alternate_domain",
    "platform",
    "hit_url",
    "outcome",
    "reason",
    "meeting_url",
    "video_url",
    "page_url",
]


def load_leads() -> List[Dict[str, str]]:
    if not ONEHOP_REPORT_CSV.exists():
        return []
    with ONEHOP_REPORT_CSV.open(newline="", encoding="utf-8") as f:
        return [
            r
            for r in csv.DictReader(f)
            if r.get("outcome") == "different-platform-found"
        ]


def _already_done_gov_ids() -> set:
    if not INGEST_REPORT_CSV.exists():
        return set()
    with INGEST_REPORT_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f) if r.get("gov_id")}


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


def _wo184_onehop_tier3_pending_handler(
    *, gov_id, unit_name, platform, final_seed, hit_url, title, date, result
) -> None:
    """wo134.TIER3_HANDLER for this script -- same shape as
    wo184_ingest_found.py's own handler, writing to THIS script's own
    pending file instead."""
    if final_seed in _pending_already_seen():
        return
    pin_row = ""
    if platform in wo134.SHARED_HOST_PLATFORMS:
        host = wo134._tenant_override_host(platform, result, final_seed)
        match = wo134._tenant_override_match(platform, result, final_seed)
        if host and match:
            pin_row = (
                f"{host}|{match}|{gov_id}|fallback|wo184_onehop_ingest|"
                f"{unit_name} -- WO-184 one-hop different-platform lead, gov_id={gov_id}"
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


wo134.TIER3_HANDLER = _wo184_onehop_tier3_pending_handler


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


async def _is_same_site_redirect(
    session: aiohttp.ClientSession, primary_domain: str, alternate_domain: str
) -> bool:
    """Re-fetches the alternate domain's home page and compares its
    RESOLVED final URL host against the primary domain's host. True means
    the alternate is the same website reached under a different address
    on file, not a genuinely separate second platform."""
    primary_host = normalize_host(primary_domain)
    if not primary_host:
        return False
    url = (
        alternate_domain if "://" in alternate_domain else f"https://{alternate_domain}"
    )
    r = await fetch_one(session, url, HONEST_HEADERS)
    final_host = normalize_host(getattr(r, "final_url", "") or "")
    return bool(final_host) and final_host == primary_host


async def stage1_resolve(
    session: aiohttp.ClientSession, leads: List[Dict[str, str]], covered_gov_ids: set
) -> None:
    is_new = not INGEST_REPORT_CSV.exists()
    with INGEST_REPORT_CSV.open("a", newline="", encoding="utf-8") as rf:
        report_w = csv.DictWriter(
            rf, fieldnames=_INGEST_REPORT_FIELDS, lineterminator="\n"
        )
        if is_new:
            report_w.writeheader()

        for i, row in enumerate(leads):
            gov_id = row["gov_id"]
            platform = row.get("platform_found", "")
            hit_url = row.get("hit_url", "")
            alternate_domain = row.get("alternate_domain", "")
            primary_domain = row.get("primary_domain", "")

            if i:
                await asyncio.sleep(HOST_DELAY_SECONDS)

            try:
                same_site = await _is_same_site_redirect(
                    session, primary_domain, alternate_domain
                )
            except Exception as e:  # noqa: BLE001 -- log and keep going
                report_w.writerow(
                    {
                        "gov_id": gov_id,
                        "name": row.get("name", ""),
                        "primary_domain": primary_domain,
                        "alternate_domain": alternate_domain,
                        "platform": platform,
                        "hit_url": hit_url,
                        "outcome": "error",
                        "reason": f"redirect-check raised: {type(e).__name__}: {e}"[
                            :300
                        ],
                        "meeting_url": "",
                        "video_url": "",
                        "page_url": "",
                    }
                )
                rf.flush()
                print(f"[{i + 1}/{len(leads)}] {gov_id} redirect-check ERROR: {e}")
                continue

            if same_site:
                report_w.writerow(
                    {
                        "gov_id": gov_id,
                        "name": row.get("name", ""),
                        "primary_domain": primary_domain,
                        "alternate_domain": alternate_domain,
                        "platform": platform,
                        "hit_url": hit_url,
                        "outcome": "same-site-redirect",
                        "reason": "alternate's resolved final URL host matches the primary's",
                        "meeting_url": "",
                        "video_url": "",
                        "page_url": "",
                    }
                )
                rf.flush()
                print(f"[{i + 1}/{len(leads)}] {gov_id}: same-site-redirect (skipped)")
                continue

            await asyncio.sleep(HOST_DELAY_SECONDS)

            synthetic_row = {
                "gov_id": gov_id,
                "unit_name": row.get("name", ""),
                "homepage": f"https://{alternate_domain}" if alternate_domain else "",
                "hop2_urls": "",
                "hit_source_urls": f"{platform}={hit_url}"
                if platform and hit_url
                else "",
            }

            try:
                result = await wo134.process_row(
                    session, synthetic_row, covered_gov_ids, "wo184_onehop_ingest"
                )
            except Exception as e:  # noqa: BLE001 -- log and keep going
                report_w.writerow(
                    {
                        "gov_id": gov_id,
                        "name": row.get("name", ""),
                        "primary_domain": primary_domain,
                        "alternate_domain": alternate_domain,
                        "platform": platform,
                        "hit_url": hit_url,
                        "outcome": "error",
                        "reason": f"process_row raised: {type(e).__name__}: {e}"[:300],
                        "meeting_url": "",
                        "video_url": "",
                        "page_url": "",
                    }
                )
                rf.flush()
                print(f"[{i + 1}/{len(leads)}] {gov_id} process_row ERROR: {e}")
                continue

            report_w.writerow(
                {
                    "gov_id": gov_id,
                    "name": row.get("name", ""),
                    "primary_domain": primary_domain,
                    "alternate_domain": alternate_domain,
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
                f"[{i + 1}/{len(leads)}] {gov_id}: {result.outcome} ({result.reason})"
            )


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
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if not wo134._base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (check .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    register_all_finders()

    leads = load_leads()
    print(f"{len(leads)} 'different-platform-found' leads in {ONEHOP_REPORT_CSV.name}.")
    if not leads:
        return

    done = _already_done_gov_ids()
    print(f"{len(done)} gov_ids already in {INGEST_REPORT_CSV.name} -- skipping those.")
    to_process = [r for r in leads if r.get("gov_id", "") not in done]
    if args.limit:
        to_process = to_process[: args.limit]
    print(f"Processing {len(to_process)} leads this run.")

    covered_gov_ids = wo134._load_covered_gov_ids(args.inventory_csv)
    print(
        f"{len(covered_gov_ids)} gov_ids already have an archived page (fresh export)."
    )

    async with aiohttp.ClientSession() as session:
        await stage1_resolve(session, to_process, covered_gov_ids)

    await stage2_finish_tier3()

    print(f"\nFull ingest report: {INGEST_REPORT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
