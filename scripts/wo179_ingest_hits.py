#!/usr/bin/env python3
"""WO-179 (2026-09-10): resolve-and-ingest step for every government
where `scripts/wo179_family_scale.py` found a real meetings listing or
platform link. Read-only breadth step over `wo179_report.csv`, same
pipeline WO-134/168/174/176 already use.

Does NOT duplicate that pipeline -- imports `process_row`,
`resolve_seed`, `apply_display_jurisdiction`, `maybe_write_tenant_override`,
`build_probe_select_hook`, and the row/result dataclasses directly from
`scripts/wo134_confirmed_hits_ingest.py`, exactly the way
`scripts/wo176_ingest_hits.py` already does -- this module is deliberately
a thin parameterisation of that same approach for wo179's own report/log
file names, not a fork of its logic. See that file's own docstring for
why the two kinds of pilot hit (an already-known `platform_found`, vs a
`listing_found` with no specific platform recognised yet) need different
handling before a row can be built.

Outcome mapping into `wo179_report.csv`'s own enum (`ingested_tier1_2 |
queued_tier3 | rejected_by_probe | meeting_without_video |
no_meeting_nor_video | no_listing | already_covered | blocked | dead |
error`) from wo134's `RowResult.outcome` (`ingested_tier1_2 |
queued_tier3 | queued_tier3_pending | rejected_by_probe |
no_video_found | already_covered | skipped | error`):
  - `queued_tier3_pending` -> `queued_tier3` (same real state, different
    internal name)
  - `no_video_found` -> `meeting_without_video` (a real meeting was
    found, genuinely no video -- Ryan's own honest naming for this
    report; never filled in as anything else)
  - `skipped` (no hit_source_urls resolved, unsupported platform, or --
    for a `listing_found` row with no recognisable platform link on the
    page -- `no_platform_link_on_listing`) -> `no_meeting_nor_video`
    (a listing was found, but nothing resolvable came of it)
  - everything else passes through unchanged.

Usage (repo root, worktree venv, DATABASE_URL set per CLAUDE.md's
worktree .env warning -- ARCHIVE_BASE_URL/ARCHIVE_INGEST_TOKEN read from
the shared checkout's .env, same as every other ingest script here):
    python scripts/export_meeting_inventory.py --out-dir /tmp/wo179_inventory --source export
    python scripts/wo179_ingest_hits.py
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
from app.utils.url_guard import read_capped_text  # noqa: E402
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
REPORT_CSV = RESEARCH_DIR / "wo179_report.csv"
CONFIRMED_HITS_CSV = RESEARCH_DIR / "wo179_confirmed_hits.csv"
INGEST_LOG_CSV = RESEARCH_DIR / "wo179_confirmed_hits_ingest_log.csv"
DEFAULT_INVENTORY_CSV = Path("/tmp/wo179_inventory/meeting_inventory.csv")
SOURCE_TAG = "wo179_family_scale"
FETCH_TIMEOUT = aiohttp.ClientTimeout(total=20)
REQUEST_DELAY_SECONDS = 1.5
MAX_CONSECUTIVE_ERRORS = 6

_TAGS = ("a", "iframe", "video", "source")

# wo134's RowResult.outcome -> wo179_report.csv's own outcome enum. See
# module docstring for why each mapping is what it is.
_OUTCOME_MAP = {
    "queued_tier3_pending": "queued_tier3",
    "no_video_found": "meeting_without_video",
    "skipped": "no_meeting_nor_video",
}

# Coarse reject_class bucket, same convention scripts/wo146_api_relist_
# sweep.py and scripts/wo147_access_ladder_sweep.py already use:
# "access" (never reached/blocked, a real access problem) vs "content"
# (reached fine, just nothing usable there). Success outcomes get "".
_REJECT_CLASS_MAP = {
    "meeting_without_video": "content",
    "no_meeting_nor_video": "content",
    "rejected_by_probe": "content",
    "error": "access",
}
#  jurisdiction_coverage.csv's real, current WO-164 taxonomy (verified
# live against that file, 2026-09-10) -- "no-video-found" is the OLD,
# superseded spelling; "no-meeting-nor-video" is the one WO-164 actually
# introduced for "no meeting was found at all, so no video either."
_REJECT_REASON_MAP = {
    "meeting_without_video": "meeting-without-video",
    "no_meeting_nor_video": "no-meeting-nor-video",
}


async def _find_any_platform_link(
    session: aiohttp.ClientSession, page_url: str
) -> Tuple[Optional[str], Optional[str]]:
    """Fetch `page_url` once and return (platform, url) for the first
    real per-tenant platform link found, or (None, None). Same approach
    as wo176_ingest_hits.py's identically-named helper, plus the same
    10MB size cap `wo179_family_scale.py`'s own do_fetch() needed after
    a real oversized-page incident during this WO's own sweep (see that
    file's comment) -- this function has the identical uncapped-
    `resp.text()` shape, so it gets the identical fix."""
    try:
        async with session.get(
            page_url, headers=UA_HEADERS, timeout=FETCH_TIMEOUT, allow_redirects=True
        ) as resp:
            if resp.status >= 400:
                return None, None
            final_url = str(resp.url)
            html = await read_capped_text(resp)
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


BUILD_INPUT_ROWS_CONCURRENCY = 25


async def _build_one_row(
    session: aiohttp.ClientSession, row: dict
) -> Tuple[Optional[dict], Optional[Tuple[str, str]]]:
    """Returns (built_row, None) or (None, (gov_id, skip_reason))."""
    gov_id = row["gov_id"]
    meeting_url = row.get("meeting_url") or ""
    if not meeting_url:
        return None, (gov_id, "listing_found=yes but no meeting_url recorded")

    gov = government_for_id(gov_id)
    unit_name = f"{gov.gov_name}, {gov.state}" if gov else row.get("name", gov_id)

    platform = (row.get("platform_found") or "").strip()
    if platform:
        try:
            wo134.get_finder(platform)
        except Exception:
            platform = ""

    link = meeting_url
    if not platform:
        platform, found_link = await _find_any_platform_link(session, meeting_url)
        if not platform:
            return None, (
                gov_id,
                "no_platform_link_on_listing: fetched the listing page again, "
                "found no recognised per-tenant platform link on it",
            )
        link = found_link

    return {
        "gov_id": gov_id,
        "unit_name": unit_name,
        "homepage": row.get("meeting_url", ""),
        "hop2_urls": "",
        "hit_source_urls": f"{platform}={link}",
    }, None


async def build_input_rows(
    session: aiohttp.ClientSession, report_rows: List[dict]
) -> Tuple[List[dict], Dict[str, str]]:
    """Returns (rows for process_row, {gov_id: skip_reason}). Bounded
    concurrency (WO-179, 2026-09-10) -- this is a read-only discovery
    fetch across thousands of DIFFERENT government listing pages (one
    per row, almost never the same host twice), the same "interleave
    across many distinct hosts" shape as the sweep script itself, not
    the politeness-sensitive resolve/ingest loop that follows this
    function (which stays sequential with its own delay -- see
    REQUEST_DELAY_SECONDS below). wo176_ingest_hits.py's original,
    smaller-scale version of this function was a plain sequential loop;
    at WO-179's ~2,900-row scale that would have taken over an hour just
    for this discovery step alone before the real resolve/ingest work
    even started."""
    built: List[dict] = []
    skipped: Dict[str, str] = {}
    sem = asyncio.Semaphore(BUILD_INPUT_ROWS_CONCURRENCY)

    async def bound(row):
        async with sem:
            return await _build_one_row(session, row)

    results = await asyncio.gather(*(bound(row) for row in report_rows))
    for built_row, skip in results:
        if built_row is not None:
            built.append(built_row)
        elif skip is not None:
            skipped[skip[0]] = skip[1]
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


def merge_into_report(ingest_results: Dict[str, RowResult], skipped: Dict[str, str]):
    if not REPORT_CSV.exists():
        return
    with open(REPORT_CSV, newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    for row in rows:
        gid = row["gov_id"]
        if gid in ingest_results:
            r = ingest_results[gid]
            outcome = _OUTCOME_MAP.get(r.outcome, r.outcome)
            row["platform_found"] = r.platform or row["platform_found"]
            row["outcome"] = outcome
            row["reject_reason"] = _REJECT_REASON_MAP.get(
                outcome, row.get("reject_reason", "")
            )
            row["reject_class"] = _REJECT_CLASS_MAP.get(outcome, "")
            row["meeting_url"] = r.seed_url or row["meeting_url"]
            row["video_url"] = r.video_url or row["video_url"]
            row["tier"] = (
                "tier1_2"
                if outcome == "ingested_tier1_2"
                else "tier3"
                if outcome == "queued_tier3"
                else row.get("tier", "")
            )
            row["page_url"] = r.page_url or row["page_url"]
            row["note"] = r.reason
        elif gid in skipped:
            row["outcome"] = "no_meeting_nor_video"
            row["reject_reason"] = "no-meeting-nor-video"
            row["reject_class"] = "content"
            row["note"] = skipped[gid]

    with open(REPORT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
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

    if not REPORT_CSV.exists():
        print(f"ERROR: {REPORT_CSV} does not exist yet.", file=sys.stderr)
        sys.exit(1)

    with open(REPORT_CSV, newline="") as f:
        report_rows = [r for r in csv.DictReader(f) if r.get("listing_found") == "yes"]
    print(f"{len(report_rows)} report rows marked listing_found=yes.")

    covered_gov_ids = _load_covered_gov_ids(args.inventory_csv)
    print(f"{len(covered_gov_ids)} gov_ids already have an archived page.")
    already_done = _already_logged_gov_ids(INGEST_LOG_CSV)
    print(f"{len(already_done)} gov_ids already logged from a prior run.")

    # force_close/enable_cleanup_closed: same real fix as
    # wo179_family_scale.py's own connector (see that file's comment) --
    # this fetches thousands of distinct hosts, almost never revisited,
    # so connection reuse buys nothing and the CLOSE_WAIT buildup it can
    # cause is not worth the risk here either.
    connector = aiohttp.TCPConnector(
        limit=BUILD_INPUT_ROWS_CONCURRENCY * 2,
        ssl=False,
        force_close=True,
        enable_cleanup_closed=True,
    )
    async with aiohttp.ClientSession(connector=connector) as session:
        built_rows, skipped = await build_input_rows(session, report_rows)

    built_rows = [r for r in built_rows if r["gov_id"] not in already_done]
    if args.limit:
        built_rows = built_rows[: args.limit]
    write_confirmed_hits_csv(built_rows)
    print(
        f"{len(built_rows)} rows resolvable; {len(skipped)} report hits could not be turned into a row."
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

    merge_into_report(ingest_results, skipped)

    print("\n--- Tally (wo134 outcome names) ---")
    for outcome, count in sorted(tally.items()):
        print(f"{outcome:20} {count}")
    print(f"\nFull log: {INGEST_LOG_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
