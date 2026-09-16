"""WO-356 (2026-09-13): items 1 and 2 of Ryan's WO-349 follow-ups.

Item 1 -- the 91 "no meeting found" governments (`wo349_verify.csv`
verdict `empty_listing` (88) + `resolved_empty` (3), reject_reason
`no-meetings-found`). Ryan's theory: "likely going to need another hub
because it's unlikely that the page has no meetings -- it's more likely
that the civicplus platform is not how they primarily list their agendas
/minutes." Re-verified from each government's own bare homepage, no
platform hint, so `verify_hub()` does its own platform discovery instead
of trusting the recorded (wrong) CivicPlus hub_url -- same "bare
homepage fallback" WO-352 already validated against `verify_hub()`
(WO-333/WO-348 current `main`).

Item 2 -- the 22 errors (`resolve_error` 15 + `fetch_failed` 7). Checked
their real `evidence` values first (`BlockedURLError: Response too
large`, `HTTP 404`, `TimeoutError`, two malformed relative-path hub_urls
missing their domain entirely) -- most of these are the SAME "wrong hub_
url" problem as item 1 (a PDF, a promo video, a CivicAlerts page, a help
-center article), not a transient network blip that a same-URL retry
would fix. So "retry" here also means the bare-homepage re-verify, not a
literal repeat of the same failing call -- consistent with item 1's
underlying theory and far more likely to actually find something.

Population: `research/wo356_population.csv` (113 rows, source_item
column: item1_alt_hub / item2_retry). Writes `research/wo356_verify.csv`
(resumable: a gov_id already present is skipped).

Never fetches a youtube.com/youtu.be URL (verify_hub's own
`_youtube_resolve_guard()`). Never downloads a media file.

Usage (from the rtr-deeplink repo root, shared venv):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo356_verify_scratch.db" \\
        .venv/bin/python scripts/wo356_verify.py --limit 150 --concurrency 8
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
POPULATION_CSV = RESEARCH_DIR / "wo356_population.csv"
VERIFY_CSV = RESEARCH_DIR / "wo356_verify.csv"

FIELDNAMES = [
    "gov_id",
    "name",
    "state",
    "population",
    "domain",
    "source_item",
    "prior_verdict",
    "hub_url",
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
        return list(csv.DictReader(f))


def load_done_gov_ids() -> set:
    done = set()
    if VERIFY_CSV.exists():
        with open(VERIFY_CSV, newline="", encoding="utf-8") as f:
            done = {row["gov_id"] for row in csv.DictReader(f)}
    return done


async def verify_one(row: dict) -> dict:
    gov_id = row["gov_id"]
    domain = row["domain"]
    hub_url = f"https://{domain}"
    out = {
        "gov_id": gov_id,
        "name": row.get("name", ""),
        "state": row.get("state", ""),
        "population": row.get("population", ""),
        "domain": domain,
        "source_item": row.get("source_item", ""),
        "prior_verdict": row.get("prior_verdict", ""),
        "hub_url": hub_url,
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
            platform_hint=None,
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
        f"{len(population)} governments in population, "
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
