"""WO-358: the 148-government (re-derived to 136 live) "stale label"
bucket -- CivicClerk/eScribe/iQM2/Town Hall Streams governments whose
registry row names the platform but carries no confirmed tenant URL on
that platform's own host (the complement of WO-350's already-walked
"confirmed tenant" bucket; see BACKLOG.md's matching entry and
`research/wo350_methods_section.md`, ENUMERATION_METHODS.md §352).

Population: `research/wo358_population.csv` (built by
`build_population.py` in this WO's private scratch dir from
`coverage_registry.csv`, minus any gov_id with a live Archive page today,
minus any gov_id already touched by WO-341..352's own
`wo3NN_jc_applied_gov_ids.txt` files, minus any confirmed-tenant row
(WO-350's own bucket), minus any tenant host already sitting in a tier-3
queue file). 136 rows: civicclerk 91, escribe 29, iqm2 13,
townhallstreams 3 -- fewer than the entry's original 148 because real
sweep work (WO-341..357) has landed against this population in the days
since WO-350 sized it; see this WO's BACKLOG_DONE entry for the
re-derivation.

Starts each government from its own `hub_url` when the registry already
has one on file (a first-party agenda/calendar page -- one hop deeper
than the bare homepage) and falls back to `https://{domain}` otherwise.
`verify_hub()`'s own "unknown hub" fallback (current main, WO-332/348)
fetches that page once, looks for an embedded/linked vendor URL on the
hinted platform, and -- failing that -- probes guessable first-party
agenda paths one hop deeper. This is exactly the shortcut BACKLOG.md's
own entry for this bucket suggested.

Never fetches a youtube.com/youtu.be URL (verify_hub's own
`_youtube_resolve_guard()`). Never downloads a media file.

Writes `research/wo358_verify.csv` (resumable: a gov_id already present
is skipped). Foreground, chunked (`--limit`).

Usage (repo root, shared venv):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo358_verify_scratch.db" \\
        .venv/bin/python scripts/wo358_verify.py --limit 150 --concurrency 6
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
POPULATION_CSV = RESEARCH_DIR / "wo358_population.csv"
VERIFY_CSV = RESEARCH_DIR / "wo358_verify.csv"

FIELDNAMES = [
    "gov_id",
    "name",
    "state",
    "population",
    "domain",
    "platform",
    "start_url",
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


def candidate_start_urls(row: dict) -> list[str]:
    """Two attempts, in order: the registry's own hub_url (a first-party
    agenda/calendar page already one hop deeper than the homepage) when
    on file, then the bare domain homepage. Neither is a confirmed
    tenant URL (that's the whole reason this bucket exists) -- trying
    both entry points gives verify_hub()'s "unknown hub" one-hop fallback
    two real chances to find an embedded/linked vendor link, since a
    government's own vendor link often lives on the homepage nav/footer
    even when a specific inner agenda page doesn't carry it (and
    vice versa)."""
    urls = []
    hub = (row.get("hub_url") or "").strip()
    if hub:
        urls.append(hub)
    domain = (row.get("domain") or "").strip()
    if domain:
        home = f"https://{domain}"
        if home not in urls:
            urls.append(home)
    return urls


_NO_FINDING_VERDICTS = {
    "resolve_error",
    "fetch_failed",
    "no_platform_detected",
    "empty_listing",
    "resolved_empty",
    "unsupported_platform",
    "exception",
}


async def verify_one(row: dict) -> dict:
    gov_id = row["gov_id"]
    platform = row["platform"]
    attempts = candidate_start_urls(row)
    out = {
        "gov_id": gov_id,
        "name": row.get("name", ""),
        "state": row.get("state", ""),
        "population": row.get("population", ""),
        "domain": row.get("domain", ""),
        "platform": platform,
        "start_url": attempts[0] if attempts else "",
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
    if not attempts:
        out["verdict"] = "no_domain"
        out["error"] = "no hub_url and no domain on the population row"
        return out

    last_result = None
    for i, start_url in enumerate(attempts):
        out["start_url"] = start_url
        try:
            result = await verify_hub(
                start_url,
                platform_hint=platform,
                name=row.get("name") or None,
                state=row.get("state") or None,
            )
        except Exception as e:  # noqa: BLE001
            out["error"] = f"{type(e).__name__}: {str(e)[:300]}"
            out["verdict"] = "exception"
            last_result = None
            continue
        last_result = result
        if result.meeting_found or result.verdict not in _NO_FINDING_VERDICTS:
            break
        # first attempt found nothing -- try the next entry point, if any

    if last_result is None:
        return out

    result = last_result
    out["error"] = ""
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
                        f"rate={rate:.1f}/min last={row['gov_id']} ({row.get('name', '')}) "
                        f"tier={result['tier']} verdict={result['verdict']}"
                    )

        await asyncio.gather(*(worker(row) for row in to_process))

    log(f"chunk done: {len(to_process)} verified")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=150)
    parser.add_argument("--concurrency", type=int, default=6)
    args = parser.parse_args()
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    asyncio.run(main_async(args.limit, args.concurrency))


if __name__ == "__main__":
    main()
