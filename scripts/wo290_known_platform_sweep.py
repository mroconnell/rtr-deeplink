"""WO-290: population under 5,000 (municipalities/counties, not school
districts), platform already known on file, no Archive page yet --
resolve one meeting per government through the platform's own adapter,
no discovery hopping needed since the platform is already on record.

Same method as WO-289 (the 5,000+ band, `full_wo289.md`), scoped to the
under-5,000 population band and excluding CivicPlus (handled separately
by `scripts/wo290_civicplus_sweep.py`, since CivicPlus needs its own
AgendaCenter drill-down, not a single adapter listing) and excluding
YouTube-only rows (no YouTube calls this WO -- those go to
`wo290_youtube_leads.txt` for the drip lane).

Candidate list: `wo290_known_platform_candidates.csv`, built from
`~/Documents/rtr-business/research/jurisdiction_coverage.csv` --
population < 5000, `transcribed` not true, `gov_id` not `us:sd:*`, a
domain present, `reject_reason` not `off-mission`, and at least one of
`suspected_video_provider`/`suspected_meeting_link_provider`/
`suspected_calendar_provider` naming a platform this repo has an adapter
for (granicus, civicclerk, civicweb, escribe, iqm2, cablecast,
municode_meetings, swagit, primegov, telvue, champds, boxcast, legistar,
suiteone, townhallstreams, utah_pmn, viebit, wistia, proudcity, vimeo).

Two modes, run in sequence (never auto-ingests -- every real candidate
needs a human hand-read first, per CLAUDE.md's wrong-rate findings):

  --mode discover   Resolves every candidate through its adapter (reusing
                     `scripts/nationwide_2404_ingest.py`'s
                     `locate_platform_url`/`resolve_seed`/
                     `pick_calendar_candidate`/`_looks_like_real_meeting`,
                     same as `scripts/wo128_known_platform_sweep.py`).
                     Writes every outcome -- real candidate awaiting a
                     hand-read, or an already-decided reject (no
                     platform link, no video, skipped) -- to
                     `wo290_known_platform_discover.csv`. Never calls the
                     Archive. Resumable: skips any gov_id already present
                     in the output file.

  --mode finish      Reads a hand-completed decisions file (same rows as
                     the discover output, plus a `hand_decision` column
                     set to `accept`/`reject`/`kind-a` by a human) and
                     turns each `accept` row into a real ingest (segments
                     -> `scripts/bulk_ingest.py`'s own `process_one()`,
                     called directly so the exact same resolve+POST path
                     that script's CLI uses is what creates the page,
                     with `gov_id` in the payload per WO-222) or a tier-3
                     queue/pin write (video only, no captions ->
                     `app/platforms/queue_probe.finish_candidate()`, the
                     one shared place that turns a probe verdict into a
                     queue line, deferred-file line, or pin -- see
                     `docs/COVERAGE_HANDOVER.md` section 4).

Usage:
    python scripts/wo290_known_platform_sweep.py --mode discover [--limit N]
    python scripts/wo290_known_platform_sweep.py --mode finish --decisions wo290_hand_decisions.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import certifi  # noqa: E402

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import (  # noqa: E402
    CalendarPageError,
    UnsupportedPlatformError,
    detect_platform,
    get_finder,
)
from scripts.adhoc_cdx_escribe_pipeline import discover_candidate_ids  # noqa: E402
from scripts.bulk_ingest import _base_url, process_one  # noqa: E402
from scripts.nationwide_2404_ingest import (  # noqa: E402
    REQUEST_DELAY_SECONDS,
    RowSkip,
    _looks_like_real_meeting,
    locate_platform_url,
    resolve_seed,
)
from app.platforms.queue_probe import finish_candidate  # noqa: E402

register_all_finders()

SCRIPT_DATA_DIR = REPO_ROOT / "scripts" / "wo290_data"
DEFAULT_CANDIDATES = SCRIPT_DATA_DIR / "wo290_known_platform_candidates.csv"
DISCOVER_OUT = SCRIPT_DATA_DIR / "wo290_known_platform_discover.csv"

CALLER = "wo290_known_platform_sweep"

_ESCRIBE_MEETING_PATH_HINTS = ("meeting.aspx", "isistandaloneplayer.aspx")


def _is_bare_escribe_tenant_url(url: str) -> bool:
    if detect_platform(url) != "escribe":
        return False
    path = urlparse(url).path.lower()
    return not any(hint in path for hint in _ESCRIBE_MEETING_PATH_HINTS)


async def _discover_escribe_meeting(session: aiohttp.ClientSession, tenant_url: str):
    domain = urlparse(tenant_url).netloc
    candidate_ids = await discover_candidate_ids(session, domain)
    if not candidate_ids:
        return None, "no HasVideo meeting via GetCalendarMeetings in the last 120 days"
    last_reason = ""
    for guid in candidate_ids:
        candidate_url = f"https://{domain}/Meeting.aspx?Id={guid}"
        try:
            result = await get_finder("escribe").resolve(candidate_url)
        except CalendarPageError as e:
            last_reason = f"calendar page: {e}"
            continue
        except Exception as e:
            last_reason = f"resolve raised: {e}"
            continue
        if (
            result.segments
            or result.agenda_items
            or result.agenda_link
            or result.video_url
        ):
            return candidate_url, None
    return (
        None,
        last_reason or f"checked {len(candidate_ids)} candidate(s), none had content",
    )


def _seed_url(row: dict) -> str:
    return (
        row.get("example_meeting_url")
        or row.get("example_agenda_or_calendar_url")
        or _homepage(row.get("domain", ""))
    )


def _homepage(domain: str) -> str:
    domain = (domain or "").strip()
    if not domain:
        return ""
    if "://" not in domain:
        domain = "https://" + domain
    return domain


REPORT_FIELDS = [
    "gov_id",
    "city_name",
    "state_or_province",
    "platform",
    "outcome",
    "reason",
    "final_seed",
    "title",
    "date",
    "has_segments",
    "segments_count",
    "has_video_url",
    "video_url",
    "has_agenda_only",
    "hand_decision",
]


def _already_done(path: Path) -> set:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f)}


async def discover_one(session: aiohttp.ClientSession, row: dict) -> dict:
    gov_id = row["gov_id"]
    platform = (row.get("platform") or "").strip().lower()
    seed = _seed_url(row)
    base = dict(
        gov_id=gov_id,
        city_name=row.get("city_name", ""),
        state_or_province=row.get("state_or_province", ""),
        platform=platform,
        outcome="",
        reason="",
        final_seed="",
        title="",
        date="",
        has_segments="",
        segments_count="",
        has_video_url="",
        video_url="",
        has_agenda_only="",
        hand_decision="",
    )
    if not seed:
        base["outcome"] = "skipped"
        base["reason"] = "no seed url (no example_meeting_url/agenda_url/domain)"
        return base

    try:
        get_finder(platform)
    except UnsupportedPlatformError:
        base["outcome"] = "skipped"
        base["reason"] = f"{platform}: not registered in get_finder()"
        return base

    try:
        if platform == "escribe" and _is_bare_escribe_tenant_url(seed):
            meeting_url, reason = await _discover_escribe_meeting(session, seed)
            if not meeting_url:
                base["outcome"] = "no-platform-link-found"
                base["reason"] = f"escribe tenant calendar: {reason}"
                return base
            located = meeting_url
        elif detect_platform(seed) == platform:
            located = seed
        else:
            located, reason = await locate_platform_url(
                session, platform, seed, [], _homepage(row.get("domain", ""))
            )
            if not located:
                base["outcome"] = "no-platform-link-found"
                base["reason"] = reason
                return base

        result, final_seed, high_risk_title = await resolve_seed(
            session, platform, located
        )
    except RowSkip as e:
        base["outcome"] = "no-platform-link-found"
        base["reason"] = str(e)
        return base
    except Exception as e:
        base["outcome"] = "skipped"
        base["reason"] = f"resolve raised: {e}"
        return base

    segments = result.segments or []
    agenda_items = result.agenda_items or []
    base["final_seed"] = final_seed
    base["title"] = result.title or ""
    base["date"] = result.date or ""

    if not (segments or agenda_items or result.agenda_link or result.video_url):
        base["outcome"] = "no-meeting-nor-video"
        base["reason"] = f"resolved but no transcript/agenda/video ({final_seed})"
        return base

    if not _looks_like_real_meeting(
        result.title or "", require_allowlist=high_risk_title
    ):
        base["outcome"] = "skipped"
        base["reason"] = f"title looks like a non-meeting video: {result.title!r}"
        return base

    if segments:
        base["outcome"] = "candidate_tier1_2"
        base["has_segments"] = "yes"
        base["segments_count"] = str(len(segments))
        return base

    if result.video_url:
        base["outcome"] = "candidate_tier3"
        base["has_video_url"] = "yes"
        base["video_url"] = result.video_url
        return base

    base["outcome"] = "meeting-without-video"
    base["has_agenda_only"] = "yes"
    base["reason"] = f"agenda-only, no video: {final_seed}"
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

    tally: dict = {}
    last_host = None
    consecutive_errors = 0
    async with aiohttp.ClientSession() as session:
        for i, row in enumerate(todo):
            try:
                result = await discover_one(session, row)
            except Exception as e:
                result = dict(
                    gov_id=row["gov_id"],
                    city_name=row.get("city_name", ""),
                    state_or_province=row.get("state_or_province", ""),
                    platform=row.get("platform", ""),
                    outcome="skipped",
                    reason=f"unhandled exception: {e}",
                    final_seed="",
                    title="",
                    date="",
                    has_segments="",
                    segments_count="",
                    has_video_url="",
                    video_url="",
                    has_agenda_only="",
                    hand_decision="",
                )
            tally[result["outcome"]] = tally.get(result["outcome"], 0) + 1
            writer.writerow(result)
            f_out.flush()
            print(
                f"[{i + 1}/{len(todo)}] [{result['outcome']:20}] {result['gov_id']} "
                f"{result.get('platform', ''):18} -- {result.get('reason', '') or result.get('title', '')}"
            )
            host = urlparse(_seed_url(row)).netloc
            if host == last_host:
                await asyncio.sleep(2.0)
            else:
                await asyncio.sleep(REQUEST_DELAY_SECONDS)
            last_host = host
            consecutive_errors = (
                consecutive_errors + 1
                if result["outcome"] == "skipped"
                and "unhandled exception" in result.get("reason", "")
                else 0
            )
            if consecutive_errors >= 8:
                print("ABORTING: 8 consecutive unhandled exceptions.", file=sys.stderr)
                break
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
    print(
        f"{len(tier12)} tier1/2 (captions) to ingest, {len(tier3)} tier3 (video-only) to queue"
    )

    page_ids = []
    async with aiohttp.ClientSession() as session:
        for r in tier12:
            gov_id = r["gov_id"]
            url = r["final_seed"]
            print(f"INGEST {gov_id} {url}")
            res = await process_one(session, url, dry_run=False, gov_id=gov_id)
            print(f"  -> {res}")
            if res.get("status") == "ingested":
                page_ids.append((gov_id, res))
            await asyncio.sleep(REQUEST_DELAY_SECONDS)

        for r in tier3:
            gov_id = r["gov_id"]
            url = r["final_seed"]
            video_url = r.get("video_url") or url
            print(f"QUEUE  {gov_id} {url}")
            outcome = await finish_candidate(
                url,
                video_url=video_url,
                gov_id=gov_id,
                caller=CALLER,
            )
            print(
                f"  -> action={outcome.action} verdict={outcome.probe.verdict} reason={outcome.probe.reason}"
            )
            await asyncio.sleep(REQUEST_DELAY_SECONDS)

    print("\nDone. Ingested page results:")
    for gov_id, res in page_ids:
        print(f"  {gov_id}: {res}")


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
