"""WO-170 Part 2: run the 45 (verified: 44 -- see below) governments
WO-153's Part C found mislabelled as "video, no captions, queued" in
rtr-business/research/jurisdiction_coverage.csv when their video was
never actually in the tier-3 queue at all
(rtr-business/research/wo153_partC_final.csv, rows with
`queue_verified == no` and a non-blank `example_meeting_url`).

**Re-derived, per CLAUDE.md's "a backlog entry is a lead, not a spec"
rule.** The conductor's brief said 45. Re-counting the real file directly
(`queue_verified == "no"` AND `example_meeting_url` non-blank, deduped on
`gov_id`) gives **44**, not 45 -- there are 73 `queue_verified == "no"`
rows covering 49 distinct governments, 44 of which carry a real video
URL and 5 of which don't (Macomb County MI, Northumberland County VA,
Tolleson city AZ, Jupiter Island town FL, Kill Devil Hills town NC --
those 5 have no video evidence at all and are out of scope for this
script; they stay open in jurisdiction_coverage.csv with whatever
reject_reason already describes them). This script processes the real
44. Of those, 3 already have an archived page as of this run's fresh
export (Sturgis MI, Oak Grove MO, Superior WI) -- reported
`already_covered` without ever calling an adapter, same as every other
sweep's dedup-first rule.

Two real platform shapes among the 44 (`detect_platform()` on each
`example_meeting_url`, checked before writing this script): 37 YouTube,
7 CivicClerk. The CivicClerk rows get REAL multi-candidate treatment:
this script passes the tenant ROOT (not the specific `/event/N/media`
seed WO-153 recorded) as the platform hit, so
`wo134_confirmed_hits_ingest.resolve_seed()`'s own civicclerk branch
depth-searches up to 6 recent past events with real media and
`PROBE_SELECT_HOOK` (WO-170's own selection rule, see that module's own
comment) picks among them. The 37 YouTube rows are each a single,
already-known video (not a channel/listing) -- WO-153 didn't record a
channel link for any of them, and finding one would need an extra
per-government fetch this pass didn't build -- so those go through
resolve_seed()'s single-candidate path: still probed, still queued with
a pin on success, still `rejected_by_probe` on failure, just with
nothing to *select among* (Ryan's rule is written for "several
candidates"; one candidate is the same rule with a set of size one).
See BACKLOG.md for the filed follow-up (deriving a channel link for a
single-video YouTube row so it gets the same depth search CivicClerk
rows do here).

**Ryan's own first case**: Torrington WY (`us:place:5677530`) was the
one that surfaced this whole gap -- its `example_meeting_url` resolved
with REAL CAPTIONS when actually run, so it's a live page now, not a
tier-3 queue line. That's exactly what this script does for every row:
resolve for real, ingest tier 1/2 if captions come back, only queue tier
3 if the video genuinely has none.

Same pipeline every other sweep uses --
scripts/wo134_confirmed_hits_ingest.py's process_row() -- with WO-170's
`PROBE_SELECT_HOOK` wired in (Ryan's "check several, prefer 9-40
minutes, else shortest" rule) instead of the older, simpler bool-
returning `PROBE_HOOK`. `TIER3_HANDLER` is deliberately left unset
(None): probing now happens INSIDE resolve_seed() before a candidate is
accepted, so a tier-3 result process_row() returns has already passed
the probe and goes straight to the real queue file + pin, exactly like
WO-169's own re-run script.

Rules from CLAUDE.md/docs/BREADTH_SWEEP_BRIEF.md: video-only ingest
(process_row() already enforces this), probe before queue
(PROBE_SELECT_HOOK), pins on shared hosts
(process_row()'s own maybe_write_tenant_override(), already wired), one
government at a time with a real delay between them (bumped from
wo134's own 0.75s CANDIDATE_DELAY_SECONDS default to 2s for THIS run,
matching this WO's own "2s between requests to one host" rule -- most of
these 44 governments are single-candidate anyway, so this mostly affects
the 7 CivicClerk tenant-root depth searches), stop after 6 consecutive
real errors, HTTP only. A YouTube resolve/probe that hits the known
caption-fetch anti-bot block (HTTP 429, or yt-dlp's "Sign in to confirm
you're not a bot" -- docs/investigations/youtube_429_block.md) is
already caught and degraded gracefully by app/platforms/youtube.py
itself (fixed 2026-08-29, see that file's own history) -- this script
adds no new handling for it, only watches for and reports the block
signature in `resolve raised: ...`/reject reasons if it appears.

Usage (repo root, DATABASE_URL set per CLAUDE.md's worktree warning even
though this script never touches the DB directly):
    python scripts/export_meeting_inventory.py --out-dir /tmp/wo170_inventory --source export
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo170_scratch.db" \\
        python scripts/wo170_mislabelled_queued_rerun.py

Writes rtr-business/research/wo170_candidates.csv (the 44-government
input, built once from wo153_partC_final.csv and cached) and
rtr-business/research/wo170_report.csv (one row per government,
resumable -- a gov_id already logged there is skipped on re-run).
"""

import asyncio
import csv
import os
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List
from urllib.parse import urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import detect_platform  # noqa: E402

import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402

RESEARCH_DIR = Path("/Users/mroconnell/Documents/rtr-business/research")
SOURCE_CSV = RESEARCH_DIR / "wo153_partC_final.csv"
CANDIDATES_CSV = RESEARCH_DIR / "wo170_candidates.csv"
REPORT_CSV = RESEARCH_DIR / "wo170_report.csv"
DEFAULT_INVENTORY_CSV = Path("/tmp/wo170_inventory/meeting_inventory.csv")

# This WO's own politeness rule ("2s between requests to one host") is
# stricter than wo134's own CANDIDATE_DELAY_SECONDS default (0.75s,
# meant for a same-tenant depth search) -- bumped for the whole run,
# restored in main()'s finally block.
REQUEST_DELAY_SECONDS = 1.5  # between governments
CANDIDATE_DELAY_SECONDS = 2.0  # between requests to the SAME host
MAX_CONSECUTIVE_ERRORS = 6

CANDIDATE_FIELDS = [
    "gov_id",
    "unit_name",
    "state",
    "domain",
    "platform",
    "example_meeting_url",
    "seed_url",
    "original_reject_reason",
]
REPORT_FIELDS = [
    "gov_id",
    "unit_name",
    "state",
    "domain",
    "platform",
    "outcome",
    "reason",
    "seed_url",
    "video_url",
    "title",
    "date",
    "page_url",
    "original_reject_reason",
]

# Real, confirmed junk seen in wo153_partC_final.csv's own
# example_meeting_url values -- trailing whitespace (Columbia IL) and a
# trailing zero-width space, U+200B (Crawford County KS). Stripped before
# use rather than left to trip up urlparse()/detect_platform() downstream.
_ZERO_WIDTH_SPACE = "​"


def _clean_url(url: str) -> str:
    url = url.strip().replace(_ZERO_WIDTH_SPACE, "")
    # Strip any other Unicode "format" character (category Cf -- the
    # zero-width space above is one, but this also catches anything else
    # in the same invisible-junk family) rather than enumerating each one
    # by codepoint.
    return "".join(ch for ch in url if unicodedata.category(ch) != "Cf")


def _civicclerk_tenant_root(event_url: str) -> str:
    """A CivicClerk `/event/N/media` link's own tenant root -- passing
    THIS (not the specific event) as the platform hit is what makes
    resolve_seed()'s civicclerk branch depth-search up to
    MAX_CANDIDATES_TRIED recent past events with real media, instead of
    resolving only the one event WO-153 happened to record."""
    parsed = urlparse(event_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def build_candidates_csv() -> List[dict]:
    """Builds (and caches) wo170_candidates.csv from
    wo153_partC_final.csv -- see this module's own docstring for the
    filter (queue_verified == "no", non-blank example_meeting_url,
    deduped on gov_id) and the re-derived 44-not-45 count."""
    if CANDIDATES_CSV.exists():
        with CANDIDATES_CSV.open(newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    if not SOURCE_CSV.exists():
        print(f"ERROR: {SOURCE_CSV} not found.", file=sys.stderr)
        sys.exit(1)

    with SOURCE_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    seen_gov_ids: set = set()
    candidates: List[dict] = []
    for row in rows:
        if row.get("queue_verified") != "no":
            continue
        raw_url = (row.get("example_meeting_url") or "").strip()
        if not raw_url:
            continue
        gov_id = row["gov_id"]
        if gov_id in seen_gov_ids:
            continue
        seen_gov_ids.add(gov_id)

        url = _clean_url(raw_url)
        try:
            platform = detect_platform(url)
        except Exception:
            platform = ""
        seed_url = _civicclerk_tenant_root(url) if platform == "civicclerk" else url
        candidates.append(
            {
                "gov_id": gov_id,
                "unit_name": f"{row['name']}, {row['state']}",
                "state": row["state"],
                "domain": row.get("domain", ""),
                "platform": platform,
                "example_meeting_url": url,
                "seed_url": seed_url,
                "original_reject_reason": row.get("reject_reason", ""),
            }
        )

    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    with CANDIDATES_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CANDIDATE_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(candidates)
    print(f"Built {CANDIDATES_CSV} with {len(candidates)} government(s).")
    return candidates


def _already_logged_gov_ids(path: Path) -> set:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {row["gov_id"] for row in csv.DictReader(f) if row.get("gov_id")}


def _log_writer(path: Path):
    is_new = not path.exists()
    f = path.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=REPORT_FIELDS, lineterminator="\n")
    if is_new:
        writer.writeheader()
        f.flush()
    return f, writer


async def main() -> None:
    if not wo134._base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (check .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    register_all_finders()
    candidates = build_candidates_csv()
    print(f"{len(candidates)} government(s) to process.")

    covered_gov_ids = wo134._load_covered_gov_ids(DEFAULT_INVENTORY_CSV)
    print(f"{len(covered_gov_ids)} gov_ids already have an archived page.")

    already_done = _already_logged_gov_ids(REPORT_CSV)
    todo = [c for c in candidates if c["gov_id"] not in already_done]
    print(f"{len(already_done)} already logged from a prior run -- {len(todo)} left.")

    # WO-170's own selection rule (see PROBE_SELECT_HOOK's own comment in
    # wo134_confirmed_hits_ingest.py) -- probes every tier-3 candidate a
    # platform hit's own candidate loop resolves (up to
    # MAX_CANDIDATES_TRIED) and prefers the newest 9-40 minute one, else
    # the shortest, instead of WO-169's plain first-pass accept/reject.
    wo134.PROBE_SELECT_HOOK = wo134.build_probe_select_hook()
    original_candidate_delay = wo134.CANDIDATE_DELAY_SECONDS
    wo134.CANDIDATE_DELAY_SECONDS = CANDIDATE_DELAY_SECONDS

    log_f, log_writer = _log_writer(REPORT_CSV)
    tally: Dict[str, int] = {}
    consecutive_errors = 0
    try:
        async with aiohttp.ClientSession() as session:
            for i, cand in enumerate(todo):
                row = {
                    "gov_id": cand["gov_id"],
                    "unit_name": cand["unit_name"],
                    "hit_source_urls": (
                        f"{cand['platform']}={cand['seed_url']}"
                        if cand["platform"]
                        else ""
                    ),
                }
                try:
                    if not cand["platform"]:
                        result = wo134.RowResult(
                            cand["gov_id"],
                            cand["unit_name"],
                            "",
                            "skipped",
                            f"unsupported/undetected platform for "
                            f"{cand['example_meeting_url']}",
                            video_url=cand["example_meeting_url"],
                        )
                    else:
                        result = await wo134.process_row(
                            session, row, covered_gov_ids, "wo170_mislabelled_queued"
                        )
                    consecutive_errors = 0
                    report_row = {
                        "gov_id": cand["gov_id"],
                        "unit_name": cand["unit_name"],
                        "state": cand["state"],
                        "domain": cand["domain"],
                        "platform": result.platform or cand["platform"],
                        "outcome": result.outcome,
                        "reason": result.reason,
                        "seed_url": result.seed_url,
                        "video_url": result.video_url,
                        "title": result.title,
                        "date": result.date,
                        "page_url": result.page_url,
                        "original_reject_reason": cand["original_reject_reason"],
                    }
                except Exception as e:  # noqa: BLE001
                    consecutive_errors += 1
                    report_row = {
                        "gov_id": cand["gov_id"],
                        "unit_name": cand["unit_name"],
                        "state": cand["state"],
                        "domain": cand["domain"],
                        "platform": cand["platform"],
                        "outcome": "error",
                        "reason": f"unhandled: {type(e).__name__}: {e}",
                        "seed_url": cand["seed_url"],
                        "video_url": cand["example_meeting_url"],
                        "title": "",
                        "date": "",
                        "page_url": "",
                        "original_reject_reason": cand["original_reject_reason"],
                    }
                tally[report_row["outcome"]] = tally.get(report_row["outcome"], 0) + 1
                print(
                    f"[{report_row['outcome']:20}] {cand['gov_id']} "
                    f"{cand['unit_name']!r} ({cand['platform']}) -- "
                    f"{report_row['reason']}"
                )
                log_writer.writerow(report_row)
                log_f.flush()
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(
                        f"\nABORTING: {consecutive_errors} consecutive real errors -- "
                        "stopping per Ryan's politeness rule. Re-run to resume "
                        "(already-logged rows are skipped).",
                        file=sys.stderr,
                    )
                    break
                if i < len(todo) - 1:
                    await asyncio.sleep(REQUEST_DELAY_SECONDS)
    finally:
        log_f.close()
        wo134.PROBE_SELECT_HOOK = None
        wo134.CANDIDATE_DELAY_SECONDS = original_candidate_delay

    print("\n--- Tally (this run) ---")
    for outcome, count in sorted(tally.items()):
        print(f"{outcome:20} {count}")
    print(f"\nFull report: {REPORT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
