"""WO-184 (2026-09-10/11): the one-hop sweep -- Ryan's second instruction,
for governments whose PRIMARY domain already found a meeting or agenda
but NO video.

    "For governments whose primary domain found a meeting or agenda but
    NO video, still run one hop on the alternate domain. If the alternate
    exposes a different platform (a Granicus, YouTube, CivicClerk,
    Legistar, Swagit, Vimeo, Cablecast, TelVue, Wistia or similar link
    the primary did not), that is a new view of the same meetings and
    may surface video."

This is a DIFFERENT, smaller population than `wo184_pilot.py`'s: rows
whose `reject_reason` is `meeting-without-video` or its pre-2026-09-10
spelling `no-video-found` (`coverage_alternates.MEETING_FOUND_NO_VIDEO_
REASONS`), that also have an alternate. There is NO promotion in this
mode -- the primary already produced a real meeting/agenda, which per
Ryan's own rule is "very high quality" on its own, so the alternate is
only useful here if it shows a genuinely DIFFERENT platform that might
carry video the primary's platform doesn't.

Uses `coverage_alternates.one_hop_alternate()`: one plain-HTTP fetch of
the FIRST alternate domain's home page, then up to 3 of its own meeting/
agenda hop links (`find_hop_links()`, same heuristic every other sweep
in this repo uses) -- plain rung only, no browser-headers retry, no
headless, matching the brief's "plain rung on the alternate plus one hop
of meeting links."

READ-MOSTLY, same as `wo184_pilot.py`: only appends to
`wo184_onehop_report.csv` (resumable). Nothing here writes
jurisdiction_coverage.csv or ingests anything -- a "different platform
found" result is a lead for a human/a later ingest pass to resolve and
check for video, not an automatic ingest (this mode never confirms video
exists, only that a different platform link exists).

Usage:
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo184_onehop.db" \\
        python3 scripts/wo184_onehop_pilot.py [--limit N] [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Set

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.coverage_alternates import (  # noqa: E402
    MEETING_FOUND_NO_VIDEO_REASONS,
    FOUND,
    already_has_coverage,
    candidate_domains,
    one_hop_alternate,
)
from scripts.wo147_access_ladder_sweep import (  # noqa: E402
    HONEST_HEADERS,
    fetch_one,
    find_hop_links,
    find_platform_link,
    is_challenge,
)
from scripts.wo184_pilot import gov_kind_from_id, order_candidates  # noqa: E402

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
RESEARCH_CSV = RESEARCH_DIR / "jurisdiction_coverage.csv"
REPORT_CSV = RESEARCH_DIR / "wo184_onehop_report.csv"

GOV_DELAY_SECONDS = 2.0
HOST_DELAY_SECONDS = 2.0

REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "population",
    "prior_reason",
    "primary_domain",
    "alternate_domain",
    "known_platform",
    "platform_found",
    "platform_differs_from_primary",
    "hop_url",
    "hit_url",
    "outcome",
    "reject_reason",
]


def load_candidates() -> List[Dict[str, str]]:
    with RESEARCH_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = [
        r
        for r in rows
        if (
            (r.get("alternate_domains") or "").strip()
            or (r.get("alternate_urls") or "").strip()
        )
        and (r.get("reject_reason") or "").strip() in MEETING_FOUND_NO_VIDEO_REASONS
        and not already_has_coverage(r)
    ]
    return order_candidates(out)


def already_done_gov_ids() -> Set[str]:
    if not REPORT_CSV.exists():
        return set()
    with REPORT_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f) if r.get("gov_id")}


def report_writer():
    is_new = not REPORT_CSV.exists()
    f = REPORT_CSV.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(f, fieldnames=REPORT_FIELDS)
    if is_new:
        w.writeheader()
        f.flush()
    return f, w


def _known_platform_str(row: Dict[str, str]) -> str:
    return (row.get("suspected_video_provider") or "").strip() or (
        row.get("suspected_meeting_link_provider") or ""
    ).strip()


async def process_row(
    session: aiohttp.ClientSession, row: Dict[str, str]
) -> Dict[str, str]:
    candidates = candidate_domains(row)
    base = {
        "gov_id": row.get("gov_id", ""),
        "name": row.get("city_name", ""),
        "state": row.get("state_or_province", ""),
        "gov_kind": gov_kind_from_id(row.get("gov_id", "")),
        "population": row.get("population_estimate", ""),
        "prior_reason": row.get("reject_reason", ""),
        "primary_domain": row.get("domain", ""),
        "known_platform": _known_platform_str(row),
    }
    if len(candidates) < 2:
        return {
            **base,
            "alternate_domain": "",
            "platform_found": "",
            "platform_differs_from_primary": "",
            "hop_url": "",
            "hit_url": "",
            "outcome": "no-alternate",
            "reject_reason": row.get("reject_reason", ""),
        }

    alternate = candidates[1]

    async def fetch_one_fn(url, headers):
        return await fetch_one(session, url, headers)

    result = await one_hop_alternate(
        row,
        alternate,
        fetch_one_fn,
        HONEST_HEADERS,
        is_challenge,
        find_platform_link,
        find_hop_links,
        between_requests_seconds=HOST_DELAY_SECONDS,
    )

    if result.reason == FOUND and result.differs_from_primary:
        outcome = "different-platform-found"
    elif result.reason == FOUND:
        outcome = "same-platform-found"
    else:
        outcome = result.reason

    return {
        **base,
        "alternate_domain": result.alternate_domain,
        "platform_found": result.platform or "",
        "platform_differs_from_primary": (
            "yes"
            if result.differs_from_primary
            else ("no" if result.differs_from_primary is False else "")
        ),
        "hop_url": result.hop_url or "",
        "hit_url": result.hit_url or "",
        "outcome": outcome,
        "reject_reason": row.get("reject_reason", ""),
    }


def _error_row(row: Dict[str, str], exc: Exception) -> Dict[str, str]:
    return {
        "gov_id": row.get("gov_id", ""),
        "name": row.get("city_name", ""),
        "state": row.get("state_or_province", ""),
        "gov_kind": gov_kind_from_id(row.get("gov_id", "")),
        "population": row.get("population_estimate", ""),
        "prior_reason": row.get("reject_reason", ""),
        "primary_domain": row.get("domain", ""),
        "known_platform": _known_platform_str(row),
        "alternate_domain": "",
        "platform_found": "",
        "platform_differs_from_primary": "",
        "hop_url": "",
        "hit_url": "",
        "outcome": "error",
        "reject_reason": f"pilot-error: {exc}"[:200],
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--dry-run", action="store_true", help="print candidate count and exit"
    )
    args = parser.parse_args()

    candidates = load_candidates()
    print(
        f"{len(candidates)} candidate rows (meeting-without-video, alternate present)."
    )

    if args.dry_run:
        return

    done = already_done_gov_ids()
    print(f"{len(done)} gov_ids already in {REPORT_CSV.name} -- skipping those.")

    to_process = [r for r in candidates if r.get("gov_id", "") not in done]
    if args.limit:
        to_process = to_process[: args.limit]
    print(f"Processing {len(to_process)} rows this run.")

    tally: Dict[str, int] = {}
    report_f, writer = report_writer()
    try:
        async with aiohttp.ClientSession() as session:
            for i, row in enumerate(to_process):
                started = time.monotonic()
                try:
                    result_row = await process_row(session, row)
                except Exception as e:  # noqa: BLE001 -- log and keep going
                    result_row = _error_row(row, e)
                writer.writerow(result_row)
                report_f.flush()
                tally[result_row["outcome"]] = tally.get(result_row["outcome"], 0) + 1
                elapsed = time.monotonic() - started
                print(
                    f"[{i + 1}/{len(to_process)}] {result_row['name']}, {result_row['state']}: "
                    f"{result_row['outcome']} ({elapsed:.1f}s)"
                )
                if i < len(to_process) - 1:
                    await asyncio.sleep(GOV_DELAY_SECONDS)
    finally:
        report_f.close()

    print("\n--- Tally (this run) ---")
    for k, v in sorted(tally.items()):
        print(f"{k:28} {v}")
    print(f"\nFull report: {REPORT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
