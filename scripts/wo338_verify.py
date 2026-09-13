"""WO-338 (2026-09-13): the hand-check step for the WO-337/338 addendum --
"the hand-check step is `verify_hub()`, not a bare `resolve()` on the
hub." Replaces the bare-`resolve()` shape of `wo325_resolve_diagnostic.py`
(and every earlier `wo3NN_resolve_diagnostic.py`) with
`app.platforms.passive_verify.verify_hub()` (WO-333, PR #1125), and emits
Ryan's tier vocabulary (1: video+captions this app can fetch; 2: video
whose captions are YouTube's -- a drip lead, never fetched; 3: video, no
reachable captions -- a tier-3 queue candidate; 4: meeting found, no
video; no tier: no meeting found at all).

Population: the best (domain, url, platform) row per government from
`research/wo338_targeted.csv` where `platform_confirmed` is truthy
(`load_targeted_best()`, copied from `wo338_build_report.py`) --
governments phase 3 found NO confirmed platform for are NOT walked here
(nothing to verify_hub against); they keep whatever phase-3
outcome/fallback_rung already describes them, folded into the tier table
downstream by `wo338_finish.py`.

Writes `research/wo338_verify.csv` (resumable: a domain already present
is skipped), one row per confirmed government: domain, gov_id, name,
state, hub_url, platform_hint, verdict, tier ('' when meeting_found is
False), meeting_found, video_found, captions_found, meeting_url,
resolved_platform, evidence, candidates_checked, ranking_fix_applied,
error.

Never fetches a youtube.com/youtu.be URL (verify_hub's own
`_youtube_resolve_guard()`, scoped for the whole walk). Never downloads
a media file -- verify_hub only ever calls a platform's own `resolve()`
metadata step.

Usage (from the rtr-deeplink repo root, shared venv):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo338_verify_scratch.db" \\
        .venv/bin/python scripts/wo338_verify.py --limit 50
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
TARGETED_CSV = RESEARCH_DIR / "wo338_targeted.csv"
VERIFY_CSV = RESEARCH_DIR / "wo338_verify.csv"

FIELDNAMES = [
    "domain",
    "gov_id",
    "name",
    "state",
    "hub_url",
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
    "error",
]


def log(msg: str) -> None:
    print(msg, flush=True)


def load_targeted_best() -> dict:
    """Copied from wo338_build_report.py's own load_targeted_best() --
    one best row per domain, preferring a real platform confirmation,
    then a name match, then the lowest fallback_rung."""
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


def load_population_meta() -> dict:
    """domain -> {gov_id, name, state} from the full WO-338 population."""
    path = RESEARCH_DIR / "wo338_population.csv"
    meta = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            meta[row["domain"]] = row
    return meta


def load_done_domains() -> set:
    done = set()
    if VERIFY_CSV.exists():
        with open(VERIFY_CSV, newline="", encoding="utf-8") as f:
            done = {row["domain"] for row in csv.DictReader(f)}
    return done


async def verify_one(domain: str, row: dict, meta: dict) -> dict:
    hub_url = row["url"]
    platform_hint = row.get("platform_confirmed") or None
    out = {
        "domain": domain,
        "gov_id": meta.get("gov_id", ""),
        "name": meta.get("name", ""),
        "state": meta.get("state", ""),
        "hub_url": hub_url,
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
    targeted_best = load_targeted_best()
    confirmed = {
        dom: row for dom, row in targeted_best.items() if row.get("platform_confirmed")
    }
    meta_by_domain = load_population_meta()
    done = load_done_domains()
    remaining = [(dom, row) for dom, row in confirmed.items() if dom not in done]
    log(
        f"{len(confirmed)} governments with a confirmed platform, "
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

        async def worker(dom, row):
            nonlocal completed
            async with sem:
                meta = meta_by_domain.get(dom, {})
                result = await verify_one(dom, row, meta)
            async with lock:
                writer.writerow(result)
                out.flush()
                completed += 1
                if completed % 10 == 0 or completed == len(to_process):
                    elapsed = time.monotonic() - start
                    rate = completed / elapsed * 60 if elapsed > 0 else 0
                    log(
                        f"[{completed}/{len(to_process)}] elapsed={elapsed:.0f}s "
                        f"rate={rate:.1f}/min last={dom}"
                    )

        await asyncio.gather(*(worker(dom, row) for dom, row in to_process))

    log(f"chunk done: {len(to_process)} verified")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--concurrency", type=int, default=12)
    args = parser.parse_args()
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    asyncio.run(main_async(args.limit, args.concurrency))


if __name__ == "__main__":
    main()
