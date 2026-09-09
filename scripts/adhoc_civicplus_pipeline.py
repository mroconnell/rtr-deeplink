"""One-off pipeline for CivicPlus tenants found via platform-hit scans
(e.g. rtr-business/research/tx_gus_candidate_platform_scan_hits.csv's
`platform_hits` column, or any other candidate list with the same
gov_id/unit_name/web_address shape as
rtr-business/research/master_open_candidates_deduped.csv) that have never
had a specific meeting URL resolved -- only "this domain looks like
CivicPlus" from a text/HTML hint.

CivicPlus itself is not a video host (see app/platforms/civicplus.py's own
module docstring): a tenant's `{domain}/AgendaCenter` page is a plain
server-rendered `tr.catAgendaRow` table, and each row's own `td.media`
link -- when present -- points at the REAL video platform underneath
(Granicus/YouTube/Vimeo/etc, not civicplus.com), so the platform for
tiering/resolving has to be discovered per-row, not assumed. Unlike the
CDX-scan siblings (adhoc_cdx_*_pipeline.py), CivicPlus needs no separate
"find a plausible event id" discovery step of its own --
`CivicPlusAssetFinder.resolve()` already does the fetch + row-parse +
platform-detect + delegate in one call, for the 0-candidate and
exactly-1-candidate cases. This script adds what it does NOT do (tier
classification + ingest/queue), and -- for the common >1-candidate case,
which `resolve()` surfaces as `CalendarPageError` with a full pick-list
rather than silently failing -- picks the first (newest, since
AgendaCenter listings render newest-first) real candidate row and
resolves *that* through `resolve_via_platform()`, exactly the calling
pattern already demonstrated read-only by
`rtr-business/research/coverage_gap_2026-09-01/civicplus_owndomain_sweep.py`
(which stops at resolve -- this script is that same pattern plus real
tier/ingest/queue).

Resolves each tenant's picked meeting via the real adapter, ingests
tier-1 (segments>0) and tier-3-agenda (agenda_items>0 or agenda_link)
directly, queues tier-3-video-only to tier3_auto_transcription_queue.txt.
Resumable: a report CSV is flushed after every tenant, and a completed
tenant (any non-empty status) is skipped on restart -- same lesson the
original wildcard sweep learned the hard way about full-batch-at-the-end
writes losing everything on a mid-run death.

Sequential with a polite delay between tenants (not the bounded-semaphore
concurrency the read-only owndomain sweep uses) -- matched to
adhoc_cdx_champds_pipeline.py / adhoc_wildcard_sweep_pipeline.py, this
script's true siblings in that both of THOSE also do a real per-tenant
resolve+ingest against live government sites and production Archive, not
just a read-only existence check across thousands of domains.

Run from rtr-deeplink repo root with the shared venv active:
    source .venv/bin/activate  # or wherever .venv lives
    python scripts/adhoc_civicplus_pipeline.py [candidates.csv]
(ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN come from .env via cwd-walk --
confirmed pointed at production before running for real. Set DRY_RUN=1
to resolve/tier without ingesting or queuing anything -- also skips the
jurisdiction_coverage.csv write described below, same "no side effects"
spirit.)

Candidate CSV columns: gov_id, unit_name, web_address (extra columns
ignored). `website` is also accepted as an alias for `web_address` since
some upstream scan files use that name instead.

`NoVideoCandidateFound` (app/platforms/base.py) is a distinct, non-error
outcome from `CivicPlusAssetFinder.resolve()`, added 2026-09-07 alongside
that adapter's own fix for a real production bug (garbage pages ingested
from a bare AgendaCenter URL with no real candidate ever found -- see
civicplus.py's module docstring): a confident "this government's
CivicPlus page(s), checked, likely has no video" result, not something to
ingest. On that signal this script writes outcome=no-video-found to its
own report CSV (never ingests) and additionally records the same outcome
into `~/Documents/rtr-business/research/jurisdiction_coverage.csv` --
that CSV already uses `reject_reason=no-video-found` for exactly this
class of outcome elsewhere, matched here by `gov_id`. That file is a
real, shared business artifact other sessions may be editing concurrently,
so the update is a minimal, safe read-modify-write done fresh for each
gov_id as it's processed (re-read immediately before write, touch only
that one row's own `reject_reason` field, and only when it's currently
empty -- never clobber an existing non-empty `reject_reason` or `domain`)
rather than one batched read/write across the whole run -- see
`update_coverage_reject_reason()` below.
"""

import asyncio
import csv
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import (  # noqa: E402
    CalendarPageError,
    NoVideoCandidateFound,
    resolve_via_platform,
)
from app.platforms.civicplus import CivicPlusAssetFinder  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402

DEFAULT_CANDIDATES_CSV = (
    Path(__file__).resolve().parent
    / "civicplus_data"
    / "civicplus_pilot_candidates.csv"
)
QUEUE_FILE = Path(__file__).resolve().parent / "tier3_auto_transcription_queue.txt"
REPORT_CSV = (
    Path(__file__).resolve().parent / "civicplus_data" / "civicplus_pipeline_report.csv"
)
COVERAGE_CSV = Path(
    "/Users/mroconnell/Documents/rtr-business/research/jurisdiction_coverage.csv"
)

REPORT_FIELDS = [
    "gov_id",
    "unit_name",
    "domain",
    "meeting_url",
    "platform",
    "tier",
    "outcome",
    "jurisdiction",
    "segments",
    "agenda_items",
    "video_url",
    "detail",
]

RESOLVE_DELAY_SECONDS = 1.5
INGEST_TIMEOUT = aiohttp.ClientTimeout(total=65)
DRY_RUN = os.environ.get("DRY_RUN") == "1"


def base_url():
    return os.environ.get("ARCHIVE_BASE_URL", "").rstrip("/")


def headers():
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


async def ingest(session, payload, input_url_normalized):
    body = dict(payload)
    body["input_url_normalized"] = input_url_normalized
    async with session.post(
        f"{base_url()}/internal/ingest",
        json=body,
        headers=headers(),
        timeout=INGEST_TIMEOUT,
    ) as resp:
        if resp.status == 200:
            return await resp.json()
        text = await resp.text()
        raise RuntimeError(f"ingest failed ({resp.status}): {text[:300]}")


def domain_from_web_address(web_address):
    """gov_id/unit_name/web_address candidate rows carry a full URL
    (`http://www.co.nacogdoches.tx.us/`), not a bare domain the way the
    read-only owndomain sweep's jurisdiction_coverage.csv already does --
    strip it down to just the host CivicPlusAssetFinder needs for
    `{domain}/AgendaCenter`."""
    web_address = (web_address or "").strip()
    if not web_address:
        return None
    if "://" not in web_address:
        web_address = "https://" + web_address
    netloc = urlparse(web_address).netloc.strip()
    return netloc or None


def load_candidates(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    candidates = []
    for row in rows:
        web_address = row.get("web_address") or row.get("website") or ""
        candidates.append(
            {
                "gov_id": row.get("gov_id", ""),
                "unit_name": row.get("unit_name", ""),
                "web_address": web_address,
            }
        )
    return candidates


def update_coverage_reject_reason(gov_id, reject_reason):
    """Safe, minimal read-modify-write against
    rtr-business/research/jurisdiction_coverage.csv, a real shared
    business artifact that other sessions may be actively editing at the
    same time this pipeline runs (confirmed live concern, 2026-09-07) --
    NOT the same one-big-batch-read/write-at-the-end pattern
    adhoc_granicus_478_pipeline.py already uses for the same file, which
    assumes it's the only writer for the whole run.

    Re-reads the full CSV fresh right before writing (so it reflects
    whatever any other concurrent session already wrote), finds the one
    row matching `gov_id` (that column already exists in this CSV, unlike
    adhoc_granicus_478_pipeline.py's own name+state fuzzy match), and
    touches ONLY that row's own `reject_reason` field -- and only when it
    is currently empty, never overwriting an existing non-empty
    `reject_reason` (this outcome should never clobber a human's or
    another pipeline's own prior verdict) or the `domain` column (this
    script never confirms a working domain on this outcome, so it has
    nothing authoritative to say about `domain`). Writes the full file
    back with every other row and column byte-for-byte untouched.
    Returns True if a matching row was found and updated, False
    otherwise (no matching gov_id, or its reject_reason was already set).
    """
    if not COVERAGE_CSV.exists():
        return False
    with open(COVERAGE_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return False
    fieldnames = list(rows[0].keys())
    matched = next((row for row in rows if row.get("gov_id") == gov_id), None)
    if matched is None:
        return False
    if (matched.get("reject_reason") or "").strip():
        return False
    matched["reject_reason"] = reject_reason
    with open(COVERAGE_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    return True


def load_done_gov_ids(report_path):
    if not report_path.exists():
        return set()
    with open(report_path, newline="", encoding="utf-8") as f:
        return {
            row["gov_id"]
            for row in csv.DictReader(f)
            if row.get("outcome") not in ("", None)
        }


class ReportWriter:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        write_header = not path.exists()
        self._f = path.open("a", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(self._f, fieldnames=REPORT_FIELDS)
        if write_header:
            self._writer.writeheader()
            self._f.flush()

    def write(self, row):
        self._writer.writerow(row)
        self._f.flush()

    def close(self):
        self._f.close()


async def resolve_candidate(finder, agendacenter_url):
    """Runs CivicPlusAssetFinder.resolve() against a tenant's AgendaCenter
    page and returns (result, meeting_url, detail_note).

    Exactly one real video-bearing row (after resolve()'s own
    newest-first walk with a retry limit, see civicplus.py): resolve()
    already does the full fetch + row-parse + platform-detect + delegate
    itself, and `result.source_url` is the delegated video url. More than
    one real video-bearing row: resolve() raises CalendarPageError with
    the full pick-list (`e.candidates`, newest-first per the site's own
    rendering) and a page-level `jurisdiction_hint` -- this picks the
    first (newest) real candidate and resolves *that* through
    resolve_via_platform(), same calling pattern as
    civicplus_owndomain_sweep.py's `check_one()`, plus threading the
    row's own agenda_link/packet_link through the same way
    CivicPlusAssetFinder.resolve() itself does for its own single-
    candidate case (those come from the AgendaCenter row's `td.downloads`
    cell, which the delegated video platform knows nothing about). No
    video found at all within the retry limit (including a genuinely
    empty listing page): resolve() raises `NoVideoCandidateFound` instead
    -- a confident, real negative result, handled by the caller as its
    own distinct outcome (see the NoVideoCandidateFound except-branch in
    process_candidate() below), never as a resolve failure or an
    ingestable candidate."""
    result = await finder.resolve(agendacenter_url)
    return result, result.source_url, ""


async def process_candidate(session, finder, candidate, report):
    gov_id = candidate["gov_id"]
    unit_name = candidate["unit_name"]
    row_out = {field: "" for field in REPORT_FIELDS}
    row_out["gov_id"] = gov_id
    row_out["unit_name"] = unit_name

    domain = domain_from_web_address(candidate["web_address"])
    if not domain:
        row_out.update(outcome="no-domain", detail="empty/unparseable web_address")
        report.write(row_out)
        print(f"[NO-DOM ] {gov_id} {unit_name}")
        return
    row_out["domain"] = domain

    agendacenter_url = f"https://{domain}/AgendaCenter"

    try:
        result, meeting_url, _ = await resolve_candidate(finder, agendacenter_url)
    except NoVideoCandidateFound as e:
        row_out.update(
            outcome="no-video-found",
            jurisdiction=e.jurisdiction_hint or "",
            detail=f"checked {e.candidates_checked} candidate row(s), none had video",
        )
        report.write(row_out)
        print(f"[NO-VID ] {gov_id} {unit_name}  checked {e.candidates_checked} row(s)")
        if DRY_RUN:
            print(
                f"[DRYRUN ] would record reject_reason=no-video-found for {gov_id} "
                "in jurisdiction_coverage.csv"
            )
        else:
            updated = update_coverage_reject_reason(gov_id, "no-video-found")
            print(
                f"[COVERAGE] {gov_id} {unit_name}  "
                + (
                    "reject_reason set to no-video-found"
                    if updated
                    else "no update (no gov_id match, or reject_reason already set)"
                )
            )
        await asyncio.sleep(RESOLVE_DELAY_SECONDS)
        return
    except CalendarPageError as e:
        if not e.candidates:
            row_out.update(
                outcome="resolve-failed",
                detail="CalendarPageError with no candidates (unexpected)",
            )
            report.write(row_out)
            print(f"[FAILED ] {gov_id} {unit_name}  empty CalendarPageError")
            await asyncio.sleep(RESOLVE_DELAY_SECONDS)
            return
        picked = e.candidates[0]
        meeting_url = picked["url"]
        row_out["meeting_url"] = meeting_url
        try:
            result = await resolve_via_platform(meeting_url)
        except Exception as e2:
            row_out.update(
                outcome="resolve-failed",
                detail=f"picked candidate raised: {e2}",
            )
            report.write(row_out)
            print(f"[FAILED ] {gov_id} {unit_name}  picked candidate: {e2}")
            await asyncio.sleep(RESOLVE_DELAY_SECONDS)
            return
        if e.jurisdiction_hint:
            result.jurisdiction = e.jurisdiction_hint
        result.agenda_link = result.agenda_link or picked.get("agenda_link")
        result.packet_link = result.packet_link or picked.get("packet_link")
        row_out["detail"] = f"picked 1 of {len(e.candidates)} real video rows"
    except Exception as e:
        row_out.update(outcome="resolve-failed", detail=f"resolve raised: {e}")
        report.write(row_out)
        print(f"[FAILED ] {gov_id} {unit_name}  {e}")
        await asyncio.sleep(RESOLVE_DELAY_SECONDS)
        return

    row_out["meeting_url"] = meeting_url
    row_out["platform"] = result.platform or ""
    row_out["jurisdiction"] = result.jurisdiction or ""
    row_out["segments"] = len(result.segments)
    row_out["agenda_items"] = len(result.agenda_items)
    row_out["video_url"] = result.video_url or ""

    has_content = bool(
        result.segments or result.agenda_items or result.agenda_link or result.video_url
    )
    if not has_content:
        row_out.update(
            tier="none",
            outcome="skipped-empty",
            detail=row_out["detail"]
            or "; ".join(result.video_warnings or [])
            or "no segments/agenda/video",
        )
        report.write(row_out)
        print(f"[EMPTY  ] {gov_id} {unit_name}  {agendacenter_url}")
        await asyncio.sleep(RESOLVE_DELAY_SECONDS)
        return

    passes_client_gate = bool(
        result.segments or result.agenda_items or result.agenda_link
    )
    normalized = normalize_url(meeting_url)
    tier = (
        "tier1"
        if result.segments
        else ("tier3-agenda" if passes_client_gate else "tier3-video-only")
    )
    row_out["tier"] = tier

    if DRY_RUN:
        row_out.update(outcome=f"dry-run-{tier}")
        print(
            f"[DRYRUN ] {gov_id} {unit_name}  {meeting_url}  {tier}  jurisdiction={result.jurisdiction}"
        )
    elif passes_client_gate:
        try:
            response = await ingest(session, result.model_dump(), normalized)
            page_url = response.get("url") if response else None
            row_out.update(outcome="ingested", detail=page_url or "")
            print(f"[INGEST ] {gov_id} {unit_name}  {meeting_url}  {tier}  {page_url}")
        except Exception as e:
            row_out.update(outcome="ingest-failed", detail=str(e))
            print(f"[ING-ERR] {gov_id} {unit_name}  {meeting_url}  {e}")
    else:
        with open(QUEUE_FILE, "a") as qf:
            qf.write(meeting_url + "\n")
        row_out.update(outcome="queued", detail="tier3_auto_transcription_queue.txt")
        print(f"[QUEUED ] {gov_id} {unit_name}  {meeting_url}  tier3-video-only")

    report.write(row_out)
    await asyncio.sleep(RESOLVE_DELAY_SECONDS)


async def main():
    register_all_finders()
    finder = CivicPlusAssetFinder()

    candidates_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CANDIDATES_CSV
    candidates = load_candidates(candidates_path)
    done = load_done_gov_ids(REPORT_CSV)
    todo = [c for c in candidates if c["gov_id"] not in done]

    print(
        f"{len(candidates)} total candidates, {len(done)} already processed, "
        f"{len(todo)} to go (from {candidates_path})"
    )

    report = ReportWriter(REPORT_CSV)
    try:
        async with aiohttp.ClientSession() as session:
            for i, candidate in enumerate(todo):
                await process_candidate(session, finder, candidate, report)
                if (i + 1) % 10 == 0:
                    print(f"--- {i + 1}/{len(todo)} processed this run ---")
    finally:
        report.close()

    with open(REPORT_CSV, newline="", encoding="utf-8") as f:
        results = list(csv.DictReader(f))
    by_outcome = {}
    by_tier = {}
    for r in results:
        by_outcome[r["outcome"]] = by_outcome.get(r["outcome"], 0) + 1
        if r["tier"]:
            by_tier[r["tier"]] = by_tier.get(r["tier"], 0) + 1
    print("\n=== SUMMARY (cumulative across all runs) ===")
    for outcome, count in sorted(by_outcome.items(), key=lambda x: -x[1]):
        print(f"outcome {outcome}: {count}")
    for tier, count in sorted(by_tier.items(), key=lambda x: -x[1]):
        print(f"tier {tier}: {count}")
    print(f"Full report: {REPORT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
