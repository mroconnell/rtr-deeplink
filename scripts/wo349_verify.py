"""WO-349 (2026-09-13): the full run of CivicPlus's open governments --
every government whose registry row names CivicPlus (`known_platform` or
`discovery_platform`), has no live Archive page, is not already queued/
parked in `jurisdiction_coverage.csv`, and was not already applied by
WO-341/342/343/344/345/347/348 this week (those governments' jc rows are
already current; the registry snapshot itself is a 07:11 export, older
than all of those runs -- see `research/wo349_population.csv`'s own
build script, `wo349_build_population.py`, for the exact exclusion
counts).

Population: `research/wo349_population.csv`, sorted largest population
first, "bucket" column A_confirmed_hub (892 rows, has a real tenant
hub_url -- this script's target) vs B_stale_label (234 rows, only a
platform label with no confirmed URL -- needs phase 1-3 first, out of
this script's scope, reported separately).

Re-verifies each Bucket-A row's own `hub_url` via
`app.platforms.passive_verify.verify_hub(hub_url, platform_hint=
"civicplus", name=.., state=..)`, current `main` (WO-341's CivicMedia/
TikiLive adapter + `_civicplus_walker()`, WO-348's one-hop-deeper fix).
Never fetches a youtube.com/youtu.be URL (verify_hub's own
`_youtube_resolve_guard()`). Never downloads a media file.

Writes `research/wo349_verify.csv` (resumable: a gov_id already present
is skipped). Run in the foreground, in chunks (`--limit`), same pattern
as `wo347_verify.py`.

Usage (from the rtr-deeplink repo root, shared venv):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo349_verify_scratch.db" \\
        .venv/bin/python scripts/wo349_verify.py --limit 150 --concurrency 8
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
import time
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.passive_verify import verify_hub  # noqa: E402

register_all_finders()

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
POPULATION_CSV = RESEARCH_DIR / "wo349_population.csv"
VERIFY_CSV = RESEARCH_DIR / "wo349_verify.csv"

FIELDNAMES = [
    "gov_id",
    "name",
    "state",
    "population",
    "domain",
    "hub_url",
    "bucket",
    "verdict",
    "tier",
    "meeting_found",
    "video_found",
    "captions_found",
    "meeting_url",
    "resolved_platform",
    "evidence",
    "candidates_checked",
    "ranking_fix_applied",
    "error",
]


def log(msg: str) -> None:
    print(msg, flush=True)


def load_population() -> list[dict]:
    with open(POPULATION_CSV, newline="", encoding="utf-8") as f:
        return [
            row for row in csv.DictReader(f) if row.get("bucket") == "A_confirmed_hub"
        ]


def load_done_gov_ids() -> set:
    done = set()
    if VERIFY_CSV.exists():
        with open(VERIFY_CSV, newline="", encoding="utf-8") as f:
            done = {row["gov_id"] for row in csv.DictReader(f)}
    return done


async def verify_one(row: dict) -> dict:
    gov_id = row["gov_id"]
    hub_url = row["hub_url"]
    out = {
        "gov_id": gov_id,
        "name": row.get("name", ""),
        "state": row.get("state", ""),
        "population": row.get("population", ""),
        "domain": row.get("domain", ""),
        "hub_url": hub_url,
        "bucket": row.get("bucket", ""),
        "verdict": "",
        "tier": "",
        "meeting_found": False,
        "video_found": False,
        "captions_found": False,
        "meeting_url": "",
        "resolved_platform": "",
        "evidence": "",
        "candidates_checked": 0,
        "ranking_fix_applied": False,
        "error": "",
    }
    try:
        result = await verify_hub(
            hub_url,
            platform_hint="civicplus",
            name=row.get("name") or None,
            state=row.get("state") or None,
        )
    except Exception as e:  # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
        out["verdict"] = "exception"
        return out

    out["verdict"] = result.verdict
    out["tier"] = result.tier if result.tier is not None else ""
    out["meeting_found"] = result.meeting_found
    out["video_found"] = result.video_found
    out["captions_found"] = result.captions_found
    out["meeting_url"] = result.meeting_url or ""
    out["resolved_platform"] = result.platform or ""
    out["evidence"] = (result.evidence or "")[:500]
    out["candidates_checked"] = result.candidates_checked
    out["ranking_fix_applied"] = result.ranking_fix_applied
    return out


async def main_async(limit: int, concurrency: int) -> None:
    population = load_population()
    done = load_done_gov_ids()
    remaining = [row for row in population if row["gov_id"] not in done]
    log(
        f"{len(population)} governments in Bucket A (confirmed hub_url), "
        f"{len(done)} already verified, {len(remaining)} remaining"
    )
    to_process = remaining[:limit] if limit else remaining
    log(f"verifying {len(to_process)} at concurrency={concurrency}")

    write_header = not VERIFY_CSV.exists()
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    completed = 0
    start = time.monotonic()

    with open(VERIFY_CSV, "a", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=FIELDNAMES)
        if write_header:
            writer.writeheader()
            out.flush()

        async def worker(row):
            nonlocal completed
            async with sem:
                result = await verify_one(row)
            async with lock:
                writer.writerow(result)
                out.flush()
                completed += 1
                if completed % 10 == 0 or completed == len(to_process):
                    elapsed = time.monotonic() - start
                    rate = completed / elapsed * 60 if elapsed > 0 else 0
                    log(
                        f"[{completed}/{len(to_process)}] elapsed={elapsed:.0f}s "
                        f"rate={rate:.1f}/min last={row['gov_id']} ({row.get('name', '')})"
                    )

        await asyncio.gather(*(worker(row) for row in to_process))

    log(f"chunk done: {len(to_process)} verified")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=150)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    asyncio.run(main_async(args.limit, args.concurrency))


if __name__ == "__main__":
    main()
