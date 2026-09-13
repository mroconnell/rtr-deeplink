"""WO-345 (= WO-338b, 2026-09-13): rerun WO-338's walker-gap residual with
the listing walkers that have landed on `passive_verify.py` since.

WO-338 (PR #1131) reran 2,825 mislabelled governments through
`verify_hub()` (WO-333) and left an honest residual: governments where
phase 3 reconfirmed a real platform but the walk itself came back empty
(`meeting_found=False`, no tier) on one of the six platforms this repo's
`passive_verify.py` registers a listing walker for today: civicplus,
civicclerk, escribe, iqm2, townhallstreams, cablecast. Three of those
walkers (civicplus WO-341, civicclerk WO-342, escribe WO-343) already
existed when WO-338 ran, so a rerun on the same URL with unchanged code
is expected to reproduce the same empty verdict unless the live site
itself changed. The other three (iqm2's second tenant shape, the
townhallstreams walker, the cablecast third template -- all WO-344) did
NOT exist yet when WO-338 ran, so those rows are the ones most likely to
move. This script does not pre-judge either way -- it reruns every row
and reports what actually comes back.

Population (built in-script, not from a separate file, so the filter is
auditable here): every row of `research/wo338_verify.csv` whose
`platform_hint` is one of the six walker platforms above AND whose
`tier` column is blank (`meeting_found=False` -- the "walk came back
empty" bucket WO-338's own BACKLOG_DONE entry calls "105 more where a
platform WAS reconfirmed but the walk came back empty"). That is 108
rows as of this WO (44 civicplus, 41 civicclerk, 16 townhallstreams, 4
iqm2, 3 escribe, 0 cablecast -- WO-338's own population never reconfirmed
a cablecast tenant, so there is nothing to rerun on that platform here).

Re-verifies from the SAME `hub_url` WO-338 already confirmed (no fresh
recon) via `app.platforms.passive_verify.verify_hub()`, current `main`.
Writes `research/wo345_verify.csv` (resumable: a domain already present
is skipped), same column shape as `wo338_verify.csv` plus
`prior_verdict`/`prior_evidence` so before/after is readable from one
file. Never fetches a youtube.com/youtu.be URL (verify_hub's own
`_youtube_resolve_guard()`). Never downloads a media file.

Usage (from the rtr-deeplink repo root, shared venv):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo345_verify_scratch.db" \\
        .venv/bin/python scripts/wo345_verify.py --limit 50
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
WO338_VERIFY_CSV = RESEARCH_DIR / "wo338_verify.csv"
VERIFY_CSV = RESEARCH_DIR / "wo345_verify.csv"

TARGET_PLATFORMS = {
    "civicplus",
    "civicclerk",
    "escribe",
    "iqm2",
    "townhallstreams",
    "cablecast",
}

FIELDNAMES = [
    "domain",
    "gov_id",
    "name",
    "state",
    "hub_url",
    "platform_hint",
    "prior_verdict",
    "prior_evidence",
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
    """The 105-ish walker-gap residual: WO-338's own confirmed-platform,
    walk-came-back-empty rows on a platform that has a listing walker
    today."""
    pop = []
    with open(WO338_VERIFY_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (
                row.get("platform_hint") in TARGET_PLATFORMS
                and row.get("tier", "") == ""
            ):
                pop.append(row)
    return pop


def load_done_domains() -> set:
    done = set()
    if VERIFY_CSV.exists():
        with open(VERIFY_CSV, newline="", encoding="utf-8") as f:
            done = {row["domain"] for row in csv.DictReader(f)}
    return done


async def verify_one(row: dict) -> dict:
    domain = row["domain"]
    hub_url = row["hub_url"]
    platform_hint = row.get("platform_hint") or None
    out = {
        "domain": domain,
        "gov_id": row.get("gov_id", ""),
        "name": row.get("name", ""),
        "state": row.get("state", ""),
        "hub_url": hub_url,
        "platform_hint": platform_hint or "",
        "prior_verdict": row.get("verdict", ""),
        "prior_evidence": (row.get("evidence", "") or "")[:300],
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
        result = await verify_hub(hub_url, platform_hint=platform_hint)
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
    done = load_done_domains()
    remaining = [row for row in population if row["domain"] not in done]
    log(
        f"{len(population)} governments in the walker-gap residual, "
        f"{len(done)} already re-verified, {len(remaining)} remaining"
    )
    to_process = remaining[:limit] if limit else remaining
    log(f"re-verifying {len(to_process)} at concurrency={concurrency}")

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
                        f"rate={rate:.1f}/min last={row['domain']}"
                    )

        await asyncio.gather(*(worker(row) for row in to_process))

    log(f"chunk done: {len(to_process)} re-verified")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    asyncio.run(main_async(args.limit, args.concurrency))


if __name__ == "__main__":
    main()
