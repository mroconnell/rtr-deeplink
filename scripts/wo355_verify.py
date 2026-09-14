#!/usr/bin/env python3
"""WO-355 (2026-09-13): re-verify the non-YouTube `off-mission` governments
with `verify_hub(..., deep_walk=True)` (WO-355 part 1, PR #1145).

Population: `research/wo355_population.csv` (built by
`wo355_build_population.py` -- every `off-mission` row in
`jurisdiction_coverage.csv` minus WO-353's YouTube-sourced list), sorted
largest population first.

hub_url per government: the population row's own `hub_url` (already a
real, previously-confirmed URL for most rows) when set, else
`https://{domain}` -- `verify_hub()` does its own platform discovery on a
bare homepage (fetch once, look for a vendor link, first-party agenda
probe, one-hop-deeper -- see WO-352's own `verify_hub()`-does-phases-1-3
finding, same idea this script reuses rather than re-implementing).

`deep_walk=True` on every call (Ryan's rule 1: collect up to 3 video
candidates instead of stopping at the first) -- `video_candidates` is
JSON-encoded into its own column for the hand-read pass
(`wo355_handread.py`) to read back.

Never fetches a youtube.com/youtu.be URL (verify_hub's own
`_youtube_resolve_guard()` -- a YouTube embed anywhere in the walk comes
back as a `youtube_lead`, tier 2, never fetched). Never downloads a media
file (only HTML/JSON listing pages and VTT/SRT caption files are ever
read, same as every other `verify_hub()` caller).

Writes `research/wo355_verify.csv` (resumable: a gov_id already present
is skipped). Each government is wrapped in a 45s timeout so one slow/
hanging host can't stall the whole chunk; the shared `_fetch()` inside
`passive_verify.py` already bounds each individual HTTP request to 30s.
Run in the foreground, in chunks (`--limit`, default 150, per the WO's
"resumable chunks of at most 150 per call" rule).

Usage (from the rtr-deeplink repo root, shared venv):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo355_verify_scratch.db" \\
        .venv/bin/python scripts/wo355_verify.py --limit 150 --concurrency 6
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

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.passive_verify import verify_hub  # noqa: E402

register_all_finders()

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
POPULATION_CSV = RESEARCH_DIR / "wo355_population.csv"
VERIFY_CSV = RESEARCH_DIR / "wo355_verify.csv"

PER_GOVERNMENT_TIMEOUT_SECONDS = 45

FIELDNAMES = [
    "gov_id",
    "name",
    "state",
    "population",
    "domain",
    "hub_url",
    "hub_source",
    "platform_hint",
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
    "video_candidates_json",
    "error",
]


def log(msg: str) -> None:
    print(msg, flush=True)


def load_population() -> list[dict]:
    with open(POPULATION_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_done_gov_ids() -> set:
    done = set()
    if VERIFY_CSV.exists():
        with open(VERIFY_CSV, newline="", encoding="utf-8") as f:
            done = {row["gov_id"] for row in csv.DictReader(f) if row.get("gov_id")}
    return done


async def verify_one(row: dict) -> dict:
    gov_id = row["gov_id"]
    domain = row.get("domain", "")
    hub_url = (row.get("hub_url") or "").strip()
    if hub_url:
        hub_source = "population_hub_url"
    else:
        hub_url = f"https://{domain}"
        hub_source = "bare_homepage"
    platform_hint = row.get("platform") or None

    out = {
        "gov_id": gov_id,
        "name": row.get("name", ""),
        "state": row.get("state", ""),
        "population": row.get("population", ""),
        "domain": domain,
        "hub_url": hub_url,
        "hub_source": hub_source,
        "platform_hint": platform_hint or "",
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
        "video_candidates_json": "[]",
        "error": "",
    }
    try:
        result = await asyncio.wait_for(
            verify_hub(
                hub_url,
                platform_hint=platform_hint,
                name=row.get("name") or None,
                state=row.get("state") or None,
                deep_walk=True,
            ),
            timeout=PER_GOVERNMENT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        out["error"] = f"TimeoutError: exceeded {PER_GOVERNMENT_TIMEOUT_SECONDS}s"
        out["verdict"] = "timeout"
        return out
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
    out["video_candidates_json"] = json.dumps(result.video_candidates)
    return out


async def main_async(limit: int, concurrency: int) -> None:
    population = load_population()
    done = load_done_gov_ids()
    remaining = [row for row in population if row["gov_id"] not in done]
    log(
        f"{len(population)} in population, {len(done)} already verified, "
        f"{len(remaining)} remaining"
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

    log(
        f"chunk done: {len(to_process)} verified, {len(remaining) - len(to_process)} remaining"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=150)
    parser.add_argument("--concurrency", type=int, default=6)
    args = parser.parse_args()
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    asyncio.run(main_async(args.limit, args.concurrency))


if __name__ == "__main__":
    main()
