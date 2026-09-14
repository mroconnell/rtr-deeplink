#!/usr/bin/env python3
"""WO-352 (2026-09-13): re-verify WO-338's "nothing confirmed" governments
(`research/wo352_population.csv`, built by `wo352_build_population.py` --
the blank-tier rows of `wo338_final_classification.csv`, minus anything
WO-345/347/348/348-group2 already applied, minus rows now `transcribed`
or `queued` in `jurisdiction_coverage.csv`) against the now-fixed
`app.platforms.passive_verify.verify_hub()` (WO-333, PR #1125; WO-348's
"look one hop deeper" fix, PR #1137/#1139/#1140).

Unlike `wo338_verify.py` (which only walked the ~623 governments phase 3
had already confirmed a platform for), this script walks EVERY row in
the population, because `verify_hub()` itself does its own platform
discovery when given a bare hub URL and no platform hint (see its
docstring: "the hub isn't itself shaped like any known platform's own
page -- fetch it once and look for the real embedded/linked vendor", and
WO-348's own `_probe_first_party_agenda_pages()` one-hop-deeper
fallback). So the WO-338-era split between "confirmed" (walk it) and
"no confirmed platform" (nothing to walk) no longer applies -- a bare
homepage IS something to walk now.

hub_url per government, in priority order:
  1. `research/wo338_targeted.csv`'s best row for this domain, if
     `platform_confirmed` is truthy (a real vendor URL already found).
  2. Otherwise `https://{domain}` (the bare homepage), with
     `platform_hint` from the population row's `known_platform` column
     when set.
`name`/`state` are passed through (WO-348) to strengthen the one-hop-
deeper evidence check.

Writes `research/wo352_verify.csv` (resumable: a domain already present
is skipped), same shape as `wo338_verify.csv`.

Never fetches a youtube.com/youtu.be URL (verify_hub's own
`_youtube_resolve_guard()`). Never downloads a media file.

Usage (from the rtr-deeplink repo root, shared venv):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo352_verify_scratch.db" \\
        .venv/bin/python scripts/wo352_verify.py --limit 150
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
POPULATION_CSV = RESEARCH_DIR / "wo352_population.csv"
TARGETED_CSV = RESEARCH_DIR / "wo338_targeted.csv"
VERIFY_CSV = RESEARCH_DIR / "wo352_verify.csv"

FIELDNAMES = [
    "domain",
    "gov_id",
    "name",
    "state",
    "population",
    "hub_url",
    "platform_hint",
    "hub_source",
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


def load_targeted_best() -> dict:
    """domain -> best targeted row (copied from wo338_verify.py)."""
    best: dict[str, dict] = {}
    if not TARGETED_CSV.exists():
        return best
    with open(TARGETED_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            domain = row.get("domain", "")
            if not domain:
                continue
            existing = best.get(domain)

            def score(r):
                return (
                    r.get("platform_confirmed") not in ("", "False", None),
                    r.get("name_match") in ("True", True),
                    -int(r.get("fallback_rung") or 0),
                    -int(r.get("rank") or 99),
                )

            if existing is None or score(row) > score(existing):
                best[domain] = row
    return best


def load_population() -> list[dict]:
    rows = []
    with open(POPULATION_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            rows.append(row)
    return rows


def load_done_domains() -> set:
    done = set()
    if VERIFY_CSV.exists():
        with open(VERIFY_CSV, newline="", encoding="utf-8") as f:
            done = {row["domain"] for row in csv.DictReader(f)}
    return done


async def verify_one(pop_row: dict, targeted_best: dict) -> dict:
    domain = pop_row["domain"]
    tgt = targeted_best.get(domain)
    if tgt and tgt.get("platform_confirmed"):
        hub_url = tgt["url"]
        platform_hint = tgt.get("platform_confirmed") or None
        hub_source = "wo338_targeted_confirmed"
    else:
        hub_url = f"https://{domain}"
        platform_hint = pop_row.get("known_platform") or None
        hub_source = "bare_homepage"

    out = {
        "domain": domain,
        "gov_id": pop_row.get("gov_id", ""),
        "name": pop_row.get("name", ""),
        "state": pop_row.get("state", ""),
        "population": pop_row.get("population", ""),
        "hub_url": hub_url,
        "platform_hint": platform_hint or "",
        "hub_source": hub_source,
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
            platform_hint=platform_hint,
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
    targeted_best = load_targeted_best()
    done = load_done_domains()
    remaining = [row for row in population if row["domain"] not in done]
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
                result = await verify_one(pop_row, targeted_best)
            async with lock:
                writer.writerow(result)
                out.flush()
                completed += 1
                if completed % 10 == 0 or completed == len(to_process):
                    elapsed = time.monotonic() - start
                    rate = completed / elapsed * 60 if elapsed > 0 else 0
                    log(
                        f"[{completed}/{len(to_process)}] elapsed={elapsed:.0f}s "
                        f"rate={rate:.1f}/min last={pop_row['domain']}"
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
