#!/usr/bin/env python3
"""WO-176 (2026-09-10): resolve-and-ingest step for every government where
`scripts/wo176_path_pilot.py` found a real meetings listing or platform
link. Read-only breadth step, same pipeline WO-134/168/174 already use --
see `scripts/wo134_confirmed_hits_ingest.py`'s own module docstring for
the full history of the resolve/probe/pin machinery this reuses (WO-144's
queue probe, WO-169's next-candidate-on-reject, WO-170's 9-to-40-minute
preference, the shared-host tenant_overrides.csv pin).

This module does NOT duplicate that pipeline -- it imports `process_row`,
`resolve_seed`, `apply_display_jurisdiction`, `maybe_write_tenant_override`,
`build_probe_select_hook`, and the row/result dataclasses directly from
`scripts/wo134_confirmed_hits_ingest.py` and drives them with rows built
from the pilot's own findings, in the exact (gov_id, unit_name, homepage,
hop2_urls, hit_source_urls) shape that pipeline already expects.

Two kinds of pilot hit need different handling before a row can be built:

1. `platform` already set on the pilot row (a `platform_link`/
   `vendor_host_guess` outcome -- a real per-tenant subdomain link was
   found directly). `hit_source_urls` is just `{platform}={meeting_url}`.
2. A `listing` outcome (agenda page found by path/feed guessing, no
   vendor subdomain link recognised) -- the specific platform is still
   unknown. This script fetches that one listing page again (one extra
   read, counted separately from the pilot's own per-site budget) and
   scans every <a>/<iframe>/<video>/<source> link with
   `app.platforms.base.detect_platform()`, skipping CivicPlus's own
   corporate/marketing hosts (`CIVICPLUS_CORPORATE_HOSTS`, the same
   WO-163 exclusion `find_specific_platform_link()` already applies).
   The first recognised platform becomes the row's `hit_source_urls`
   entry. A listing with no recognisable platform link at all is
   recorded honestly as `no_platform_link_on_listing` -- not forced into
   a resolve that has nothing to resolve.

Writes:
  - `~/Documents/rtr-business/research/wo176_confirmed_hits.csv` (the
    built input rows, for reproducibility)
  - `~/Documents/rtr-business/research/wo176_confirmed_hits_ingest_log.csv`
    (per-row outcome, same fields `_log_writer()` already uses)
  - merges the ingest outcome back into `wo176_pilot_report.csv`'s
    `outcome`/`platform`/`meeting_url`/`video_url`/`tier`/`page_url`
    columns for every gov_id this script touched.

Usage (repo root, worktree venv, DATABASE_URL set per CLAUDE.md's
worktree .env warning -- ARCHIVE_BASE_URL/ARCHIVE_INGEST_TOKEN are read
from the shared checkout's .env exactly like every other ingest script
here, since this genuinely does write to the production Archive over
HTTP, same as WO-134/168/174):
    python scripts/export_meeting_inventory.py --out-dir /tmp/wo176_inventory --source export
    python scripts/wo176_ingest_hits.py
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import CIVICPLUS_CORPORATE_HOSTS, detect_platform  # noqa: E402
from app.utils.gov_registry.registry import government_for_id  # noqa: E402
from scripts.bulk_ingest import _base_url  # noqa: E402
from scripts.wo134_confirmed_hits_ingest import (  # noqa: E402
    RowError,
    RowResult,
    UA_HEADERS,
    _already_logged_gov_ids,
    _load_covered_gov_ids,
    build_probe_select_hook,
    process_row,
)
import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402

RESEARCH_DIR = Path("/Users/mroconnell/Documents/rtr-business/research")
PILOT_REPORT_CSV = RESEARCH_DIR / "wo176_pilot_report.csv"
CONFIRMED_HITS_CSV = RESEARCH_DIR / "wo176_confirmed_hits.csv"
INGEST_LOG_CSV = RESEARCH_DIR / "wo176_confirmed_hits_ingest_log.csv"
DEFAULT_INVENTORY_CSV = Path("/tmp/wo176_inventory/meeting_inventory.csv")
SOURCE_TAG = "wo176_path_pilot"
FETCH_TIMEOUT = aiohttp.ClientTimeout(total=20)
REQUEST_DELAY_SECONDS = 1.5
MAX_CONSECUTIVE_ERRORS = 6

_TAGS = ("a", "iframe", "video", "source")


async def _find_any_platform_link(
    session: aiohttp.ClientSession, page_url: str
) -> Tuple[Optional[str], Optional[str]]:
    """Fetch `page_url` once and return (platform, url) for the first
    real per-tenant platform link found, or (None, None). Generalised
    version of `find_specific_platform_link()` in wo134's own module --
    that one needs a target platform known in advance; this scans for
    ANY recognised platform, since a plain path/feed hit doesn't know
    which vendor it landed on yet."""
    try:
        async with session.get(
            page_url, headers=UA_HEADERS, timeout=FETCH_TIMEOUT, allow_redirects=True
        ) as resp:
            if resp.status >= 400:
                return None, None
            final_url = str(resp.url)
            html = await resp.text(errors="replace")
    except Exception:
        return None, None

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(_TAGS):
        href_or_src = tag.get("href") or tag.get("src")
        if not href_or_src:
            continue
        candidate = urljoin(final_url, href_or_src.strip())
        netloc = urlparse(candidate).netloc.lower()
        if netloc in CIVICPLUS_CORPORATE_HOSTS:
            continue
        platform = detect_platform(candidate)
        if platform and platform != "unknown":
            try:
                wo134.get_finder(platform)
            except Exception:
                continue
            return platform, candidate
    return None, None


async def build_input_rows(
    session: aiohttp.ClientSession, pilot_rows: List[dict]
) -> Tuple[List[dict], Dict[str, str]]:
    """Returns (rows for process_row, {gov_id: skip_reason} for pilot
    hits that couldn't be turned into a resolvable row)."""
    built = []
    skipped: Dict[str, str] = {}
    for row in pilot_rows:
        gov_id = row["gov_id"]
        meeting_url = row.get("meeting_url") or ""
        if not meeting_url:
            skipped[gov_id] = "pilot row marked found=yes but no meeting_url recorded"
            continue

        gov = government_for_id(gov_id)
        unit_name = f"{gov.gov_name}, {gov.state}" if gov else row.get("name", gov_id)

        platform = (row.get("platform") or "").strip()
        if platform:
            try:
                wo134.get_finder(platform)
            except Exception:
                platform = ""

        link = meeting_url
        if not platform:
            platform, found_link = await _find_any_platform_link(session, meeting_url)
            if not platform:
                skipped[gov_id] = (
                    "no_platform_link_on_listing: fetched the listing page again, "
                    "found no recognised per-tenant platform link on it"
                )
                continue
            link = found_link

        built.append(
            {
                "gov_id": gov_id,
                "unit_name": unit_name,
                "homepage": row.get("meeting_url", ""),
                "hop2_urls": "",
                "hit_source_urls": f"{platform}={link}",
            }
        )
    return built, skipped


def write_confirmed_hits_csv(rows: List[dict]):
    CONFIRMED_HITS_CSV.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIRMED_HITS_CSV, "w", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "gov_id",
                "unit_name",
                "homepage",
                "hop2_urls",
                "hit_source_urls",
            ],
        )
        w.writeheader()
        for r in rows:
            w.writerow(r)


def merge_into_pilot_report(
    ingest_results: Dict[str, RowResult], skipped: Dict[str, str]
):
    if not PILOT_REPORT_CSV.exists():
        return
    with open(PILOT_REPORT_CSV, newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    for row in rows:
        gid = row["gov_id"]
        if gid in ingest_results:
            r = ingest_results[gid]
            row["platform"] = r.platform or row["platform"]
            row["outcome"] = r.outcome
            row["meeting_url"] = r.seed_url or row["meeting_url"]
            row["video_url"] = r.video_url or row["video_url"]
            row["tier"] = (
                "tier1_2"
                if r.outcome == "ingested_tier1_2"
                else "tier3"
                if r.outcome in ("queued_tier3", "queued_tier3_pending")
                else row.get("tier", "")
            )
            row["page_url"] = r.page_url or row["page_url"]
            row["note"] = r.reason
        elif gid in skipped:
            row["outcome"] = "no_platform_link_on_listing"
            row["note"] = skipped[gid]

    with open(PILOT_REPORT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--inventory-csv", type=Path, default=DEFAULT_INVENTORY_CSV)
    args = parser.parse_args()

    if not _base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (check .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    register_all_finders()
    wo134.PROBE_SELECT_HOOK = build_probe_select_hook()

    if not PILOT_REPORT_CSV.exists():
        print(f"ERROR: {PILOT_REPORT_CSV} does not exist yet.", file=sys.stderr)
        sys.exit(1)

    with open(PILOT_REPORT_CSV, newline="") as f:
        pilot_rows = [r for r in csv.DictReader(f) if r.get("found") == "yes"]
    print(f"{len(pilot_rows)} pilot rows marked found=yes.")

    covered_gov_ids = _load_covered_gov_ids(args.inventory_csv)
    print(f"{len(covered_gov_ids)} gov_ids already have an archived page.")
    already_done = _already_logged_gov_ids(INGEST_LOG_CSV)
    print(f"{len(already_done)} gov_ids already logged from a prior run.")

    connector = aiohttp.TCPConnector(limit=20, ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        built_rows, skipped = await build_input_rows(session, pilot_rows)

    built_rows = [r for r in built_rows if r["gov_id"] not in already_done]
    if args.limit:
        built_rows = built_rows[: args.limit]
    write_confirmed_hits_csv(built_rows)
    print(
        f"{len(built_rows)} rows resolvable; {len(skipped)} pilot hits could not be turned into a row."
    )

    log_f, log_writer = wo134._log_writer(INGEST_LOG_CSV)
    tally: Dict[str, int] = {}
    consecutive_errors = 0
    ingest_results: Dict[str, RowResult] = {}
    try:
        async with aiohttp.ClientSession() as session:
            for i, row in enumerate(built_rows):
                try:
                    result = await process_row(
                        session, row, covered_gov_ids, SOURCE_TAG
                    )
                    consecutive_errors = 0
                except RowError as e:
                    result = RowResult(
                        row["gov_id"], row["unit_name"], "", "error", str(e)
                    )
                    consecutive_errors += 1
                except Exception as e:
                    result = RowResult(
                        row["gov_id"],
                        row["unit_name"],
                        "",
                        "error",
                        f"unhandled exception: {e}",
                    )
                    consecutive_errors += 1
                tally[result.outcome] = tally.get(result.outcome, 0) + 1
                ingest_results[row["gov_id"]] = result
                print(
                    f"[{result.outcome:20}] {result.gov_id} {result.unit_name!r} "
                    f"platform={result.platform!r} -- {result.reason}"
                )
                log_writer.writerow(result.__dict__)
                log_f.flush()
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(
                        f"\nABORTING: {consecutive_errors} consecutive real errors.",
                        file=sys.stderr,
                    )
                    break
                if i < len(built_rows) - 1:
                    await asyncio.sleep(REQUEST_DELAY_SECONDS)
    finally:
        log_f.close()

    merge_into_pilot_report(ingest_results, skipped)

    print("\n--- Tally ---")
    for outcome, count in sorted(tally.items()):
        print(f"{outcome:20} {count}")
    print(f"\nFull log: {INGEST_LOG_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
