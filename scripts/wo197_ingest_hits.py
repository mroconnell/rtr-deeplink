#!/usr/bin/env python3
"""WO-197 (2026-09-11): resolve-and-ingest step for every government
where `scripts/wo197_media_scan.py` found a real direct video/audio hit
(a `<video>`/`<audio>`/`<source>`/direct-file link, an iframe/anchor to a
platform `app/platforms/base.py::detect_platform()` recognizes, or a
specific YouTube video id -- never a bare channel/handle link, see that
script's `_YOUTUBE_VIDEO_ID_RE` comment). Feed-only and agenda-only rows
are never ingested (Ryan's rule: only meetings with video become
pages) -- this script only ever reads `outcome in ("video-found",
"audio-found")` rows.

Same split, same reused pipeline as WO-179's `wo179_family_scale.py` /
`wo179_ingest_hits.py` pair: imports `process_row`, `_load_covered_gov_ids`,
`_already_logged_gov_ids`, `build_probe_select_hook` from
`wo134_confirmed_hits_ingest` directly rather than re-deriving the
resolve/probe/tier logic.

Hand-check (the work order's own instruction: "Hand-check every
candidate's title/context: it must be a meeting of THIS government's
governing body. WO-191 found 1 in 10 wrong."): this wires
`wo134.IDENTITY_CHECK_HOOK` to a hook built from the same four pure,
already-live-tested checks `scripts/wo152_dead_domain_recheck.py` wrote
for exactly this problem (WO-145's original four checks, ported again
there) -- state/kind mismatch in the adapter's own jurisdiction/body
field, state/kind mismatch in the resolved title, a named place in the
title with no token overlap with the row's own government name, and (US
rows only, `escribe`/`civicweb` hits only -- WO-197's own candidate pool
carries 273 Canadian `ca:csd:` rows, so this cross-border risk is real
here too) a bare-name collision with a real Canadian municipality.
Copied verbatim below (not imported) for the same reason
`wo152_dead_domain_recheck.py` copied WO-145's checks rather than
importing that module: importing `wo152_dead_domain_recheck` directly
would also import `wo147_access_ladder_sweep` at module scope, which
unconditionally repoints `wo134.TIER3_HANDLER` at ITS OWN pending-queue
writer -- see that file's own docstring warning. This module never
imports either.

An automated hook is not literally the human review WO-191 did by eye --
it is this repo's best mechanical proxy for it, and it is not perfect.
Every row it rejects is counted and reported as
"wrong government suspected, not ingested" in `wo197_report.csv`'s
`reject_reason`, not silently dropped, so a human can still spot-check
the ones it let through.

Video-without-captions (tier 3) queuing, and the probe that gates it,
are unchanged -- `process_row()` already runs
`scripts/probe_tier3_queue.py`'s probe before anything is queued, and
already rejects a dead/implausible candidate and tries the row's next
hit source before giving up on a government, per
`docs/BREADTH_SWEEP_BRIEF.md`'s "probe before queuing" rules. This
script supplies no candidates beyond the single best hit
`wo197_media_scan.py` already found per government; there is no "next
hit" list to try beyond it for a `video-found`/`audio-found` row.

Usage (repo root, worktree venv, DATABASE_URL/ARCHIVE_BASE_URL/
ARCHIVE_INGEST_TOKEN per CLAUDE.md's worktree .env warning):
    python scripts/export_meeting_inventory.py --out-dir /tmp/wo197_inventory --source export
    python scripts/wo197_ingest_hits.py
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import re
import sys
from pathlib import Path
from typing import Dict, Optional

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.utils.gov_registry.registry import government_for_id  # noqa: E402
from scripts.bulk_ingest import _base_url  # noqa: E402
from scripts.wo134_confirmed_hits_ingest import (  # noqa: E402
    RowError,
    RowResult,
    _already_logged_gov_ids,
    _load_covered_gov_ids,
    _log_writer,
    build_probe_select_hook,
    process_row,
)
import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402

RESEARCH_DIR = Path("/Users/mroconnell/Documents/rtr-business/research")
REPORT_CSV = RESEARCH_DIR / "wo197_report.csv"
INGEST_LOG_CSV = RESEARCH_DIR / "wo197_confirmed_hits_ingest_log.csv"
DEFAULT_INVENTORY_CSV = Path("/tmp/wo197_inventory/meeting_inventory.csv")
SOURCE_TAG = "wo197_media_scan"
REQUEST_DELAY_SECONDS = 1.5
MAX_CONSECUTIVE_ERRORS = 6

# --- hand-check hook -- copied with attribution from
# scripts/wo152_dead_domain_recheck.py (which itself ported WO-145's
# original four checks); see this file's own module docstring for why
# it's copied rather than imported. ---

_GENERIC_NAME_WORDS = {
    "city",
    "town",
    "village",
    "township",
    "borough",
    "county",
    "parish",
    "of",
    "the",
    "and",
    "board",
    "council",
    "commission",
    "district",
    "regional",
    "municipal",
}


def _name_tokens(name: str) -> set:
    words = re.findall(r"[a-z']+", (name or "").lower())
    return {w for w in words if w not in _GENERIC_NAME_WORDS and len(w) > 2}


def _load_state_names() -> Dict[str, str]:
    """US state + Canadian province full names, keyed by abbreviation --
    same two source CSVs `scripts/wo152_dead_domain_recheck.py`'s own
    identically-named helper reads (copied, not imported, per this
    file's module docstring)."""
    names: Dict[str, str] = {}
    with (REPO_ROOT / "app/utils/jurisdiction_data/us_states.csv").open(
        newline="", encoding="utf-8"
    ) as f:
        for r in csv.DictReader(f):
            names[r["state"].upper()] = r["name"]
    with (REPO_ROOT / "app/utils/jurisdiction_data/ca_pr.csv").open(
        newline="", encoding="utf-8"
    ) as f:
        for r in csv.DictReader(f):
            names[r["province"].upper()] = r["name"]
    return names


STATE_NAMES = _load_state_names()


def _load_canadian_csd_names() -> set:
    names = set()
    path = REPO_ROOT / "app/utils/jurisdiction_data/ca_csd.csv"
    if not path.exists():
        return names
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            names.add((r.get("name") or "").strip().lower())
    return names


CANADIAN_CSD_NAMES = _load_canadian_csd_names()
CROSS_BORDER_RISK_PLATFORMS = {"escribe", "civicweb"}

_LEADING_PLACE_STATE_RE = re.compile(
    r"^\s*([A-Za-z][A-Za-z0-9\s.'\-]*?),\s*([A-Za-z]{2})\b"
)


def _state_or_kind_conflict(
    name: str, state: str, gov_kind: str, text: str, source: str
) -> Optional[str]:
    text = (text or "").strip()
    if not text:
        return None
    text_lower = text.lower()
    row_state = (state or "").strip().upper()
    row_state_name = STATE_NAMES.get(row_state, "")

    m = _LEADING_PLACE_STATE_RE.match(text)
    if m and m.group(2).upper() in STATE_NAMES:
        place_part, state_part = m.group(1), m.group(2).upper()
        if state_part != row_state:
            return (
                f"{source} {text!r} names state {state_part!r} "
                f"({STATE_NAMES.get(state_part, state_part)}), row expects "
                f"{row_state_name!r} ({name})"
            )
        place_tokens = _name_tokens(place_part)
        row_tokens = _name_tokens(name)
        if place_tokens and row_tokens and not (place_tokens & row_tokens):
            return (
                f"{source} {text!r} names a specific place ({place_part!r}) "
                f"with no name overlap with the row ({name})"
            )

    for abbr, fullname in STATE_NAMES.items():
        if abbr == row_state or not fullname:
            continue
        if fullname.lower() in text_lower:
            return (
                f"{source} {text!r} names {fullname!r}, row expects "
                f"{row_state_name!r} ({name})"
            )
    if gov_kind == "municipality" and "county" not in (name or "").lower():
        if re.search(r"\bcounty\b", text_lower):
            return (
                f"{source} {text!r} mentions 'County', row is a municipality ({name})"
            )
    return None


def _cross_border_collision(name: str, country: str, text: str) -> Optional[str]:
    if (country or "us") != "us":
        return None
    if _LEADING_PLACE_STATE_RE.search(text or ""):
        return None
    row_base = _name_tokens(name)
    if not row_base:
        return None
    all_ca_tokens = {
        n for csd_name in CANADIAN_CSD_NAMES for n in _name_tokens(csd_name)
    }
    if row_base <= all_ca_tokens:
        for csd_name in CANADIAN_CSD_NAMES:
            if _name_tokens(csd_name) == row_base:
                return (
                    f"a real Canadian municipality named {csd_name!r} exists "
                    f"(ca_csd.csv) and the resolved text {text!r} carries no "
                    f"state/province code to rule it out -- refusing to trust "
                    f"a bare name match ({name})"
                )
    return None


_TITLE_PLACE_RE = re.compile(
    r"\b([A-Z][A-Za-z.'-]*(?:\s+[A-Z][A-Za-z.'-]*){0,3})\s+"
    r"(school board|select ?board|city council|town council|village board|"
    r"town board|board of (?:trustees|selectmen|aldermen)|planning board)\b",
    re.IGNORECASE,
)
_STATE_FULLNAMES_LOWER = {v.lower() for v in STATE_NAMES.values() if v}
_MEETING_QUALIFIER_WORDS = {
    "regular",
    "special",
    "annual",
    "emergency",
    "adjourned",
    "continued",
    "joint",
    "called",
    "work",
    "workshop",
    "budget",
    "organizational",
    "reorganizational",
    "reorganization",
    "public",
    "final",
    "monthly",
}


def _title_place_conflict(name: str, title: str) -> Optional[str]:
    if not title:
        return None
    for m in _TITLE_PLACE_RE.finditer(title):
        place = m.group(1)
        place_lower = place.strip().lower()
        if place_lower in _STATE_FULLNAMES_LOWER:
            continue
        if place_lower in _MEETING_QUALIFIER_WORDS:
            continue
        place_tokens = _name_tokens(place)
        row_tokens = _name_tokens(name)
        if place_tokens and row_tokens and not (place_tokens & row_tokens):
            return f"title {title!r} names {place!r}, no overlap with the row ({name})"
    return None


WRONG_GOVERNMENT_HITS: Dict[
    str, str
] = {}  # gov_id -> mismatch reason, for the final tally


def identity_check_hook(row, platform, result, final_seed, effective_title):
    name = row.get("_wo197_name", "")
    state = row.get("_wo197_state", "")
    gov_kind = row.get("_wo197_gov_kind", "")
    country = row.get("_wo197_country", "us")

    adapter_signal = f"{result.jurisdiction or ''} {result.meeting_body or ''}".strip()
    conflict = _state_or_kind_conflict(
        name, state, gov_kind, adapter_signal, "adapter jurisdiction/body"
    )
    if not conflict:
        conflict = _state_or_kind_conflict(
            name, state, gov_kind, effective_title, "title"
        )
    if not conflict:
        conflict = _title_place_conflict(name, effective_title)
    if not conflict and platform in CROSS_BORDER_RISK_PLATFORMS:
        combined = (
            f"{result.jurisdiction or ''} {result.meeting_body or ''} "
            f"{effective_title or ''}"
        ).strip()
        conflict = _cross_border_collision(name, country, combined)
    if conflict:
        WRONG_GOVERNMENT_HITS[row["gov_id"]] = conflict
    return conflict


wo134.IDENTITY_CHECK_HOOK = identity_check_hook


# --- report row -> process_row input -----------------------------------


def _build_row(report_row: dict) -> dict:
    gov_id = report_row["gov_id"]
    gov = government_for_id(gov_id)
    unit_name = (
        f"{gov.gov_name}, {gov.state}" if gov else report_row.get("name", gov_id)
    )

    media_kind = (report_row.get("media_kind") or "").strip()
    media_url = (report_row.get("media_url") or "").strip()
    hit_url = (report_row.get("hit_url") or report_row.get("listing_url") or "").strip()

    if media_kind in ("direct-video", "direct-audio"):
        # No dedicated finder for a raw file URL -- feed the PAGE that
        # carries it to the "unknown" GenericFallbackAssetFinder, which
        # runs the identical scan_media_urls()/iframe/video-pointer
        # detection this scan's own find_media_hits() already ran, and
        # will find the same media file (or a better one it structures
        # more completely, e.g. matching captions alongside it).
        hit_source_urls = f"unknown={hit_url}"
    else:
        hit_source_urls = f"{media_kind}={media_url}"

    return {
        "gov_id": gov_id,
        "unit_name": unit_name,
        "homepage": hit_url,
        "hop2_urls": "",
        "hit_source_urls": hit_source_urls,
        "_wo197_name": report_row.get("name", ""),
        "_wo197_state": report_row.get("state", ""),
        "_wo197_gov_kind": report_row.get("gov_kind", ""),
        "_wo197_country": "ca" if gov_id.startswith("ca:") else "us",
    }


_OUTCOME_TO_REPORT = {
    "ingested_tier1_2": "ingested_tier1_2",
    "queued_tier3": "queued_tier3",
    "queued_tier3_pending": "queued_tier3",
    "rejected_by_probe": "rejected_by_probe",
    "no_video_found": "meeting_without_video",
    "already_covered": "already_covered",
    "skipped": "no_meeting_nor_video",
    "error": "error",
}


def merge_into_report(ingest_results: Dict[str, RowResult]):
    if not REPORT_CSV.exists() or not ingest_results:
        return
    with open(REPORT_CSV, newline="") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    for row in rows:
        gid = row["gov_id"]
        if gid not in ingest_results:
            continue
        r = ingest_results[gid]
        mapped = _OUTCOME_TO_REPORT.get(r.outcome, r.outcome)
        row["outcome"] = mapped
        if gid in WRONG_GOVERNMENT_HITS:
            row["reject_reason"] = (
                f"wrong-government-suspected: {WRONG_GOVERNMENT_HITS[gid]}"
            )
        else:
            row["reject_reason"] = r.reason
        if r.seed_url:
            row["hit_url"] = r.seed_url
        if r.video_url:
            row["media_url"] = r.video_url

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
        report_rows = [
            r
            for r in csv.DictReader(f)
            if r.get("outcome") in ("video-found", "audio-found")
        ]
    print(f"{len(report_rows)} report rows marked video-found/audio-found.")

    covered_gov_ids = _load_covered_gov_ids(args.inventory_csv)
    print(f"{len(covered_gov_ids)} gov_ids already have an archived page.")
    already_done = _already_logged_gov_ids(INGEST_LOG_CSV)
    print(f"{len(already_done)} gov_ids already logged from a prior run.")

    built_rows = [_build_row(r) for r in report_rows if r["gov_id"] not in already_done]
    if args.limit:
        built_rows = built_rows[: args.limit]
    print(f"{len(built_rows)} rows to attempt this run.")

    log_f, log_writer = _log_writer(INGEST_LOG_CSV)
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

    merge_into_report(ingest_results)

    print("\n--- Tally (wo134 outcome names) ---")
    for outcome, count in sorted(tally.items()):
        print(f"{outcome:20} {count}")
    print(
        f"\nWrong-government-suspected (hand-check caught, not ingested): {len(WRONG_GOVERNMENT_HITS)}"
    )
    print(f"Full log: {INGEST_LOG_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
