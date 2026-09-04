"""Pilot for the §62 HTTP-layer wildcard-substitute method (ENUMERATION_
METHODS.md), scaled to a stratified sample of gov_registry's real
US+Canada government tables instead of places.csv. Runs Granicus and
Legistar checks as two independently-paced, interleaved async streams
so a rate-limit delay on one platform doesn't block progress on the
other -- same total per-platform request rate, ~2x wall-clock
throughput vs. running them one after another.

Signatures (confirmed live 2026-09-04, see ENUMERATION_METHODS.md §62):
  Granicus: HEAD .../ViewPublisherRSS.php?view_id=1&mode=video
            real tenant -> 200 (or other non-redirect); fake -> 302 to
            /core/error/NotFound.aspx
  Legistar: HEAD .../
            real tenant -> Content-Length in the tens of KB; fake ->
            fixed 19 bytes ("Invalid parameters!")

Usage: python3 scripts/adhoc_wildcard_http_pilot.py
"""
import asyncio
import csv
import random
import re
import sys
import time
from pathlib import Path

import aiohttp
import certifi
import os

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.utils.gov_registry import tables  # noqa: E402

OUT_DIR = Path("/Users/mroconnell/Documents/rtr-business/research")
CANDIDATES_CSV = OUT_DIR / "wildcard_http_pilot_candidates.csv"
HITS_CSV = OUT_DIR / "wildcard_http_pilot_hits.csv"

SAMPLE_PER_TABLE = 150
DELAY_PER_PLATFORM = 0.4  # seconds between consecutive requests to the SAME platform
TIMEOUT = aiohttp.ClientTimeout(total=10)

_SQUASH_RE = re.compile(r"[^a-z0-9]+")


def squash(name: str) -> str:
    return _SQUASH_RE.sub("", (name or "").lower())


def variants_for(name: str, state: str):
    base = squash(name)
    st = squash(state)
    out = {base}
    if st:
        out.add(f"{base}{st}")
        out.add(f"{base}-{st}")
    return [v for v in out if v]


def sample_candidates():
    random.seed(20260904)
    sources = [
        ("us_places", tables.us_places()),
        ("us_counties", tables.us_counties()),
        ("us_states", tables.us_states()),
        ("us_school_districts", tables.us_school_districts()),
        ("ca_csd", tables.ca_csd()),
        ("ca_cd", tables.ca_cd()),
        ("ca_pr", tables.ca_pr()),
    ]
    candidates = []
    for label, table in sources:
        rows = table.rows()
        sample = random.sample(rows, min(SAMPLE_PER_TABLE, len(rows)))
        for row in sample:
            for variant in variants_for(row.name, row.state):
                candidates.append({
                    "source_table": label,
                    "name": row.name,
                    "state": row.state,
                    "slug": variant,
                })
    # dedupe on slug (different entities can squash to the same guess)
    seen = set()
    deduped = []
    for c in candidates:
        if c["slug"] in seen:
            continue
        seen.add(c["slug"])
        deduped.append(c)
    return deduped


async def check_granicus(session, slug):
    url = f"https://{slug}.granicus.com/ViewPublisherRSS.php?view_id=1&mode=video"
    try:
        async with session.head(url, timeout=TIMEOUT, allow_redirects=False) as resp:
            if resp.status == 302 and "NotFound.aspx" in (resp.headers.get("Location") or ""):
                return False, "302->NotFound"
            return True, f"HTTP {resp.status}"
    except Exception as e:
        return None, str(e)


async def check_legistar(session, slug):
    # Accept-Encoding: identity -- aiohttp negotiates gzip by default,
    # which inflates the fake-tenant response's Content-Length from the
    # real, curl-verified 19 bytes to a compressed ~136, breaking the
    # exact-match check (found live 2026-09-04 debugging this script's
    # own first run: 63/63 false "real" hits).
    url = f"https://{slug}.legistar.com/"
    try:
        async with session.head(
            url, timeout=TIMEOUT, allow_redirects=True,
            headers={"Accept-Encoding": "identity"},
        ) as resp:
            length = int(resp.headers.get("Content-Length") or -1)
            if length == 19:
                return False, "19-byte fake body"
            return True, f"HTTP {resp.status} len={length}"
    except Exception as e:
        return None, str(e)


ALL_RESULTS_CSV = OUT_DIR / "wildcard_http_pilot_all_results.csv"
_RESULT_FIELDS = ["platform", "slug", "is_real", "detail", "source_table", "name", "state"]


def _open_incremental(path):
    """Opens path for append, writing a header first if it doesn't exist
    yet -- lets a killed/interrupted run be resumed by just re-launching
    (already-written rows stay; the caller still re-checks everything,
    but nothing already on disk is lost)."""
    is_new = not path.exists()
    f = open(path, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=_RESULT_FIELDS)
    if is_new:
        writer.writeheader()
        f.flush()
    return f, writer


async def platform_worker(session, platform, checker, candidates, delay, writer, write_lock, counts):
    for c in candidates:
        slug = c["slug"]
        is_real, detail = await checker(session, slug)
        row = {
            "platform": platform, "slug": slug, "is_real": is_real, "detail": detail,
            "source_table": c["source_table"], "name": c["name"], "state": c["state"],
        }
        async with write_lock:
            writer[1].writerow(row)
            writer[0].flush()  # every row hits disk immediately -- these are long, unattended runs
        counts[platform]["total"] += 1
        if is_real:
            counts[platform]["hits"] += 1
        elif is_real is None:
            counts[platform]["errors"] += 1
        if counts[platform]["total"] % 100 == 0:
            print(f"[{platform}] {counts[platform]['total']}/{len(candidates)} checked, "
                  f"{counts[platform]['hits']} hits so far")
        await asyncio.sleep(delay)


async def main():
    candidates = sample_candidates()

    with open(CANDIDATES_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["source_table", "name", "state", "slug"])
        writer.writeheader()
        writer.writerows(candidates)

    print(f"{len(candidates)} unique slug candidates generated -> {CANDIDATES_CSV}")
    print(f"Sweeping {len(candidates)} slugs x 2 platforms, interleaved, "
          f"{DELAY_PER_PLATFORM}s/req/platform, writing every result to "
          f"{ALL_RESULTS_CSV} as it happens...")

    all_file, all_writer = _open_incremental(ALL_RESULTS_CSV)
    write_lock = asyncio.Lock()
    counts = {"granicus": {"total": 0, "hits": 0, "errors": 0},
              "legistar": {"total": 0, "hits": 0, "errors": 0}}

    start = time.time()
    try:
        async with aiohttp.ClientSession() as session:
            await asyncio.gather(
                platform_worker(session, "granicus", check_granicus, candidates,
                                 DELAY_PER_PLATFORM, (all_file, all_writer), write_lock, counts),
                platform_worker(session, "legistar", check_legistar, candidates,
                                 DELAY_PER_PLATFORM, (all_file, all_writer), write_lock, counts),
            )
    finally:
        all_file.close()
    elapsed = time.time() - start
    print(f"\nDone in {elapsed:.1f}s. Per-platform: {counts}")

    # Real hits, written separately as a clean summary (all_results.csv
    # already has everything, including fakes/errors, for audit).
    with open(ALL_RESULTS_CSV, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    hits = [r for r in rows if r["is_real"] == "True"]
    with open(HITS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=_RESULT_FIELDS)
        writer.writeheader()
        writer.writerows(hits)
    print(f"{len(hits)} real hits -> {HITS_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
