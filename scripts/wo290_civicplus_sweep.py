"""WO-290's CivicPlus drill-down: population under 5,000 (municipalities/
counties, not school districts), platform is CivicPlus (or the
AgendaCenter/DocumentCenter URL shape with no platform recorded), no
Archive page yet.

CivicPlus is not itself a video host (see `app/platforms/civicplus.py`'s
module docstring) -- it's an agenda/document system that sometimes
delegates a specific meeting row to a real video platform (Granicus,
YouTube, CivicClerk, ...). `CivicPlusAssetFinder.resolve()` already does
the fetch + row-parse + newest-first video-row walk + delegate itself,
raising `NoVideoCandidateFound` (a real negative, not an error) when no
row in the retry window has a video link.

Same two-phase shape as `scripts/wo290_known_platform_sweep.py`:
discover (resolve every candidate's AgendaCenter page, record whether a
delegate was found and to which platform, never touching the Archive),
then finish (hand-approved rows only, ingest tier1/2 via
`bulk_ingest.process_one()`, queue tier3 via
`app/platforms/queue_probe.finish_candidate()`, both with gov_id).

Usage:
    python scripts/wo290_civicplus_sweep.py --mode discover [--limit N]
    python scripts/wo290_civicplus_sweep.py --mode finish --decisions wo290_civicplus_hand_decisions.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import certifi  # noqa: E402

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import CalendarPageError, NoVideoCandidateFound  # noqa: E402
from app.platforms.civicplus import CivicPlusAssetFinder  # noqa: E402
from app.platforms.queue_probe import finish_candidate  # noqa: E402
from scripts.bulk_ingest import _base_url, process_one  # noqa: E402
from scripts.nationwide_2404_ingest import REQUEST_DELAY_SECONDS  # noqa: E402

register_all_finders()

SCRIPT_DATA_DIR = REPO_ROOT / "scripts" / "wo290_data"
DEFAULT_CANDIDATES = SCRIPT_DATA_DIR / "wo290_civicplus_candidates.csv"
DISCOVER_OUT = SCRIPT_DATA_DIR / "wo290_civicplus_discover.csv"

CALLER = "wo290_civicplus_sweep"

REPORT_FIELDS = [
    "gov_id",
    "city_name",
    "state_or_province",
    "outcome",
    "reason",
    "agendacenter_url",
    "bodies_seen",
    "delegate_platform",
    "delegate_url",
    "title",
    "date",
    "has_segments",
    "has_video_url",
    "hand_decision",
]


def _agendacenter_url(row: dict) -> str:
    domain = (row.get("domain") or "").strip()
    if not domain:
        return ""
    return f"https://{domain}/AgendaCenter"


def _already_done(path: Path) -> set:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f)}


async def discover_one(finder: CivicPlusAssetFinder, row: dict) -> dict:
    gov_id = row["gov_id"]
    url = _agendacenter_url(row)
    base = dict(
        gov_id=gov_id,
        city_name=row.get("city_name", ""),
        state_or_province=row.get("state_or_province", ""),
        outcome="",
        reason="",
        agendacenter_url=url,
        bodies_seen="",
        delegate_platform="",
        delegate_url="",
        title="",
        date="",
        has_segments="",
        has_video_url="",
        hand_decision="",
    )
    if not url:
        base["outcome"] = "skipped"
        base["reason"] = "no domain"
        return base

    try:
        result = await finder.resolve(url)
    except NoVideoCandidateFound as e:
        base["outcome"] = "meeting-without-video"
        base["bodies_seen"] = str(e.candidates_checked)
        base["reason"] = (
            f"checked {e.candidates_checked} real listing row(s), no video link"
        )
        return base
    except CalendarPageError as e:
        # Multiple real video-bearing rows -- pick the newest, resolve it.
        if not e.candidates:
            base["outcome"] = "skipped"
            base["reason"] = "CalendarPageError with no candidates (unexpected)"
            return base
        picked = e.candidates[0]
        base["bodies_seen"] = str(len({c.get("title", "") for c in e.candidates}))
        try:
            from app.platforms.base import resolve_via_platform

            result = await resolve_via_platform(picked["url"])
            if e.jurisdiction_hint and not result.jurisdiction:
                result.jurisdiction = e.jurisdiction_hint
            result.agenda_link = result.agenda_link or picked.get("agenda_link")
            result.packet_link = result.packet_link or picked.get("packet_link")
            result.title = result.title or picked.get("title")
            result.date = result.date or picked.get("date")
        except Exception as e2:
            base["outcome"] = "skipped"
            base["reason"] = f"picked candidate raised: {e2}"
            return base
    except Exception as e:
        base["outcome"] = "skipped"
        base["reason"] = f"resolve raised: {e}"
        return base

    base["title"] = result.title or ""
    base["date"] = result.date or ""
    base["delegate_platform"] = result.platform or ""
    base["delegate_url"] = result.source_url or ""

    if result.segments:
        base["outcome"] = "candidate_tier1_2"
        base["has_segments"] = "yes"
        return base
    if result.video_url:
        base["outcome"] = "candidate_tier3"
        base["has_video_url"] = "yes"
        return base
    base["outcome"] = "meeting-without-video"
    base["reason"] = "delegate resolved but no segments/video_url"
    return base


async def run_discover(candidates_path: Path, limit: int | None):
    with candidates_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    done = _already_done(DISCOVER_OUT)
    todo = [r for r in rows if r["gov_id"] not in done]
    if limit:
        todo = todo[:limit]
    print(
        f"{len(rows)} total candidates, {len(done)} already discovered, {len(todo)} to go"
    )

    SCRIPT_DATA_DIR.mkdir(parents=True, exist_ok=True)
    write_header = not DISCOVER_OUT.exists()
    f_out = DISCOVER_OUT.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f_out, fieldnames=REPORT_FIELDS, lineterminator="\n")
    if write_header:
        writer.writeheader()

    finder = CivicPlusAssetFinder()
    tally: dict = {}
    consecutive_errors = 0
    for i, row in enumerate(todo):
        try:
            result = await discover_one(finder, row)
        except Exception as e:
            result = dict(
                gov_id=row["gov_id"],
                city_name=row.get("city_name", ""),
                state_or_province=row.get("state_or_province", ""),
                outcome="skipped",
                reason=f"unhandled exception: {e}",
                agendacenter_url=_agendacenter_url(row),
                bodies_seen="",
                delegate_platform="",
                delegate_url="",
                title="",
                date="",
                has_segments="",
                has_video_url="",
                hand_decision="",
            )
        tally[result["outcome"]] = tally.get(result["outcome"], 0) + 1
        writer.writerow(result)
        f_out.flush()
        print(
            f"[{i + 1}/{len(todo)}] [{result['outcome']:20}] {result['gov_id']} -- "
            f"{result.get('reason', '') or result.get('title', '')} "
            f"(delegate={result.get('delegate_platform', '')})"
        )
        consecutive_errors = (
            consecutive_errors + 1
            if "unhandled exception" in result.get("reason", "")
            else 0
        )
        if consecutive_errors >= 8:
            print("ABORTING: 8 consecutive unhandled exceptions.", file=sys.stderr)
            break
        await asyncio.sleep(REQUEST_DELAY_SECONDS)
    f_out.close()
    print("\n--- Tally (this run) ---")
    for outcome, count in sorted(tally.items()):
        print(f"{outcome:22} {count}")
    print(f"\nFull report: {DISCOVER_OUT}")


async def run_finish(decisions_path: Path):
    with decisions_path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    accepted = [
        r for r in rows if (r.get("hand_decision") or "").strip().lower() == "accept"
    ]
    print(f"{len(rows)} decision rows, {len(accepted)} accepted for finish")

    tier12 = [r for r in accepted if r.get("outcome") == "candidate_tier1_2"]
    tier3 = [r for r in accepted if r.get("outcome") == "candidate_tier3"]
    print(f"{len(tier12)} tier1/2 to ingest, {len(tier3)} tier3 to queue")

    async with aiohttp.ClientSession() as session:
        for r in tier12:
            gov_id = r["gov_id"]
            url = r["delegate_url"]
            print(f"INGEST {gov_id} {url}")
            res = await process_one(session, url, dry_run=False, gov_id=gov_id)
            print(f"  -> {res}")
            await asyncio.sleep(REQUEST_DELAY_SECONDS)

        for r in tier3:
            gov_id = r["gov_id"]
            url = r["delegate_url"]
            print(f"QUEUE  {gov_id} {url}")
            outcome = await finish_candidate(
                url, video_url=url, gov_id=gov_id, caller=CALLER
            )
            print(
                f"  -> action={outcome.action} verdict={outcome.probe.verdict} reason={outcome.probe.reason}"
            )
            await asyncio.sleep(REQUEST_DELAY_SECONDS)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["discover", "finish"], required=True)
    parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES)
    parser.add_argument("--decisions", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    if args.mode == "discover":
        asyncio.run(run_discover(args.candidates, args.limit))
    else:
        if not args.decisions:
            print("ERROR: --decisions required for --mode finish", file=sys.stderr)
            sys.exit(1)
        if not _base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
            print(
                "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (check .env).",
                file=sys.stderr,
            )
            sys.exit(1)
        asyncio.run(run_finish(args.decisions))


if __name__ == "__main__":
    main()
