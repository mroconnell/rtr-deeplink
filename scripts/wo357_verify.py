#!/usr/bin/env python3
"""WO-357 (2026-09-13): the CivicPlus label-only bucket --
`research/wo357_population.csv` (234 rows, WO-349's own
`research/wo349_population.csv` bucket `B_stale_label`: a government
whose registry row names CivicPlus as its `known_platform` but carries
no confirmed tenant/hub URL -- WO-349's own `wo349_verify.py` explicitly
scoped these out, "needs phase 1-3 first, out of this script's scope,
reported separately"). Ryan, verbatim: "The 234 label-only CivicPlus
rows: need a full pipeline run to become pages. Do this."

Unlike WO-349's bucket-A run (which had a real `hub_url` to re-verify),
these 234 rows have nothing but a domain and a platform label. Per the
WO-352 precedent (`wo352_verify.py`'s own docstring: "a bare homepage IS
something to walk now"), `app.platforms.passive_verify.verify_hub()`
itself does phase 1 (fetch), phase 2/3 (probe first-party agenda paths,
CivicPlus-marker detection on the homepage or one hop deeper -- WO-348's
`_probe_first_party_agenda_pages()` / `_try_deeper_hop_on_url()`) and the
listing walk (`_civicplus_walker()`, up to 4 AgendaCenter categories, up
to 3 video-nav links, up to 8 Calendar EIDs) when simply called on
`https://{domain}` with `platform_hint="civicplus"`. So this script does
not build a separate recon/classify/targeted pipeline -- it calls
`verify_hub()` directly, the same shape as `wo352_verify.py`.

`name`/`state` are passed through (WO-348) to strengthen the one-hop-
deeper evidence check.

Writes `research/wo357_verify.csv` (resumable: a gov_id already present
is skipped). Run in the foreground, in chunks (`--limit`).

Never fetches a youtube.com/youtu.be URL (verify_hub's own
`_youtube_resolve_guard()`). Never downloads a media file.

Usage (from the rtr-deeplink repo root, shared venv):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo357_verify_scratch.db" \\
        .venv/bin/python scripts/wo357_verify.py --limit 150 --concurrency 10
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
POPULATION_CSV = RESEARCH_DIR / "wo357_population.csv"
VERIFY_CSV = RESEARCH_DIR / "wo357_verify.csv"

FIELDNAMES = [
    "gov_id",
    "name",
    "state",
    "population",
    "domain",
    "hub_url",
    "prior_reject_reason",
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


async def verify_one(pop_row: dict) -> dict:
    domain = pop_row["domain"]
    hub_url = f"https://{domain}"
    out = {
        "gov_id": pop_row["gov_id"],
        "name": pop_row.get("name", ""),
        "state": pop_row.get("state", ""),
        "population": pop_row.get("population", ""),
        "domain": domain,
        "hub_url": hub_url,
        "prior_reject_reason": pop_row.get("prior_reject_reason", ""),
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
            name=pop_row.get("name") or None,
            state=pop_row.get("state") or None,
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

        async def worker(pop_row):
            nonlocal completed
            async with sem:
                result = await verify_one(pop_row)
            async with lock:
                writer.writerow(result)
                out.flush()
                completed += 1
                if completed % 10 == 0 or completed == len(to_process):
                    elapsed = time.monotonic() - start
                    rate = completed / elapsed * 60 if elapsed > 0 else 0
                    log(
                        f"[{completed}/{len(to_process)}] elapsed={elapsed:.0f}s "
                        f"rate={rate:.1f}/min last={pop_row['gov_id']} "
                        f"tier={result['tier']!r} verdict={result['verdict']}"
                    )

        await asyncio.gather(*(worker(row) for row in to_process))

    log(f"chunk done: {len(to_process)} verified")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=10)
    args = parser.parse_args()
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    asyncio.run(main_async(args.limit, args.concurrency))


if __name__ == "__main__":
    main()
