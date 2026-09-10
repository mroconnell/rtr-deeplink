"""WO-127: resolve + ingest for the CivicPlus AgendaCenter hits found by
rtr-business/research/coverage_gap_2026-09-09/wo127_civicplus_owndomain_probe.py
-- governments the coverage registry's own research file had previously
rejected as `no-platform-link-found` (population >= 5000, non-county,
zero Archive pages), that turn out to run CivicPlus's AgendaCenter
directly on their own domain after all.

Same resolve pattern as scripts/adhoc_civicplus_pipeline.py (see that
file's own docstring for the full CivicPlusAssetFinder.resolve() /
CalendarPageError / NoVideoCandidateFound reasoning -- unchanged here),
with two real differences specific to this task:

1. **Ryan's ingest rule is stricter than adhoc_civicplus_pipeline.py's
   own gate.** That script ingests a "tier3-agenda" case (agenda_items or
   agenda_link present, no video at all) directly, on the same
   `bulk_ingest.py`-style client gate as a real video result. WO-127's
   brief is explicit: "ONLY meetings with video" -- an agenda-only
   result is NOT ingested here, it's recorded as `no-video-found` in
   jurisdiction_coverage.csv, same treatment as a genuine
   NoVideoCandidateFound. Tier 1 (source captions) and tier 2 (YouTube,
   local-fetch captions) both just mean "resolve() returned segments" --
   there's no separate code path, the delegated adapter (e.g.
   YouTubeAssetFinder) already did the caption fetch as part of
   resolve().

2. **Known-jurisdiction pin.** Every candidate here comes from the
   coverage registry, which already carries a validated (name, state)
   for this exact government -- stronger ground truth than anything a
   delegated video platform's own metadata can offer. BACKLOG_DONE.md's
   PR #805/#807 writeup found two real, live-shipped wrong-jurisdiction
   bugs from *not* doing this: a white-labeled CivicPlus tenant
   (www.branford-ct.gov) whose Vimeo-delegated result filed under
   Branford, FL instead of Branford, CT (CivicPlusAssetFinder's own
   `_jurisdiction_from_subdomain()` only recognizes the
   `{state}-{name}.civicplus.com` tenant-subdomain shape, so it silently
   returns None for every white-labeled domain -- the majority case),
   and a direct YouTube/Vimeo hit (hartwickny.gov) that filed under
   Hartwick, IA because the candidate CSV's own known city/state was
   never threaded through to `result.jurisdiction` at all. Both fixed
   here the same way `_jurisdiction_from_subdomain` already wins outright
   over a delegated guess for *.civicplus.com tenants: after every
   resolve, `result.jurisdiction` is overwritten with this candidate
   row's own known `"{name}, {state}"` unconditionally -- our own
   registry entry is more authoritative than any guess the delegated
   platform could make, so it always wins, not just as a fallback for an
   empty guess. This is what keeps a known government from ever landing
   on an `rtr:unknown:<host>` page.

Run from rtr-deeplink repo root with the shared venv active:
    python scripts/wo127_civicplus_pipeline.py [hits.csv]
(ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN come from .env via cwd-walk.
Set DRY_RUN=1 to resolve/tier without ingesting, queuing, or touching
jurisdiction_coverage.csv.)

Candidate CSV columns: gov_id, unit_name (already "{name}, {state}"),
web_address (bare host, no scheme -- the probe script's own output
shape). Resumable: REPORT_CSV is flushed after every candidate, and a
completed one (any non-empty outcome) is skipped on restart.
"""

import asyncio
import csv
import fcntl
import os
import sys
import time
from pathlib import Path

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

DEFAULT_HITS_CSV = (
    Path(__file__).resolve().parent / "civicplus_data" / "wo127_civicplus_hits.csv"
)
QUEUE_FILE = Path(__file__).resolve().parent / "tier3_auto_transcription_queue.txt"
REPORT_CSV = (
    Path(__file__).resolve().parent / "civicplus_data" / "wo127_pipeline_report.csv"
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


def load_candidates(path):
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    candidates = []
    for row in rows:
        candidates.append(
            {
                "gov_id": row.get("gov_id", ""),
                "unit_name": row.get("unit_name", ""),
                "web_address": row.get("web_address", ""),
            }
        )
    return candidates


COVERAGE_LOCK = COVERAGE_CSV.with_suffix(".csv.lock")
# Real, confirmed cross-session incident, 2026-09-09
# (ENUMERATION_METHODS.md §158): many concurrent scripts doing a full
# read-whole-file/write-whole-file apply with no locking raced badly
# enough that this exact file got truncated to ~13,005 and later ~16,517
# lines in several sessions' working trees, down from its real 33,465+.
# MIN_SANE_ROW_COUNT is comfortably below the real count and comfortably
# above both observed truncation sizes -- a read landing under it is
# treated as a corrupt/mid-write snapshot, never as a legitimate new
# baseline.
MIN_SANE_ROW_COUNT = 25000


def _coverage_read_modify_write(mutate_fn):
    """Shared read-modify-write for jurisdiction_coverage.csv, following
    the cross-session write protocol agreed in ENUMERATION_METHODS.md
    §158 after that truncation incident: (1) an `flock` around the
    read-modify-write, not just an informal row-count check; (2) re-read
    fresh immediately before writing; (3) refuse to write if the fresh
    read looks truncated; (4) write to a same-directory temp file and
    `os.replace()` over the real file, never in place; (5) LF line
    endings throughout.

    `mutate_fn(rows) -> changed: bool` mutates `rows` (a list of dicts)
    in place and returns whether anything actually changed; this wrapper
    handles everything else. Returns False (no write attempted) if the
    file is missing, empty, looks truncated, or `mutate_fn` made no
    change."""
    if not COVERAGE_CSV.exists():
        return False
    COVERAGE_LOCK.touch(exist_ok=True)
    with open(COVERAGE_LOCK, "w") as lock_f:
        fcntl.flock(lock_f, fcntl.LOCK_EX)
        try:
            with open(COVERAGE_CSV, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
            if len(rows) < MIN_SANE_ROW_COUNT:
                print(
                    f"[COV-ERR] refusing to write: {COVERAGE_CSV.name} read back "
                    f"only {len(rows)} rows (< {MIN_SANE_ROW_COUNT}) -- looks "
                    "truncated, not a real baseline"
                )
                return False
            if not rows:
                return False
            fieldnames = list(rows[0].keys())
            if not mutate_fn(rows):
                return False
            tmp_path = COVERAGE_CSV.with_suffix(".csv.tmp")
            with open(tmp_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)
            os.replace(tmp_path, COVERAGE_CSV)
            return True
        finally:
            fcntl.flock(lock_f, fcntl.LOCK_UN)


def update_coverage_reject_reason(gov_id, reject_reason):
    """Sets `reject_reason` on every row matching `gov_id`, only where
    currently empty. Applies to EVERY matching row, not just the first:
    real, confirmed live 2026-09-09, jurisdiction_coverage.csv has 1,339
    duplicated gov_ids (2,132 extra rows) -- a pre-existing data-quality
    issue (also flagged independently by ENUMERATION_METHODS.md's
    Kentucky-DLG session, §132), not something this script causes. Which
    duplicate row a plain `next()` lookup would hit is arbitrary (file
    order), so updating every match keeps this pipeline's own writes
    correct regardless of which row a caller later reads."""

    def mutate(rows):
        matches = [row for row in rows if row.get("gov_id") == gov_id]
        changed = False
        for row in matches:
            if not (row.get("reject_reason") or "").strip():
                row["reject_reason"] = reject_reason
                changed = True
        return changed

    return _coverage_read_modify_write(mutate)


def update_coverage_on_success(
    gov_id,
    *,
    shares_video,
    transcribed,
    example_meeting_url,
    agendacenter_url,
    video_platform="",
):
    """Mirrors backfill_2404_ingest_into_jc.py's per-outcome column
    mapping for a real ingest/queue success, applied live per-gov_id
    rather than a batched end-of-run pass -- this pipeline already writes
    jurisdiction_coverage.csv per-candidate for the no-video-found case,
    so the success case gets the same treatment for consistency and so a
    killed mid-run process doesn't lose already-confirmed outcomes. Also
    confirms `suspected_calendar_provider` (this IS CivicPlus, confirmed
    by a real resolve, not a guess) and `suspected_video_provider` (the
    delegated platform CivicPlus's own AgendaCenter row pointed at) --
    both left alone if already set by an earlier pass, never overwritten.
    Applies to every row matching `gov_id` -- see
    update_coverage_reject_reason()'s docstring for why (the
    1,339-duplicated-gov_id pre-existing issue)."""

    def mutate(rows):
        matches = [row for row in rows if row.get("gov_id") == gov_id]
        if not matches:
            return False
        for matched in matches:
            if shares_video:
                matched["shares_video"] = "True"
            if transcribed:
                matched["transcribed"] = "True"
            if (
                example_meeting_url
                and not (matched.get("example_meeting_url") or "").strip()
            ):
                matched["example_meeting_url"] = example_meeting_url
            if (
                agendacenter_url
                and not (matched.get("example_agenda_or_calendar_url") or "").strip()
            ):
                matched["example_agenda_or_calendar_url"] = agendacenter_url
            if (matched.get("reject_reason") or "").strip() == "no-platform-link-found":
                matched["reject_reason"] = ""
            if not (matched.get("suspected_calendar_provider") or "").strip():
                matched["suspected_calendar_provider"] = "civicplus"
            if (
                video_platform
                and not (matched.get("suspected_video_provider") or "").strip()
            ):
                matched["suspected_video_provider"] = video_platform
        return True

    return _coverage_read_modify_write(mutate)


def update_coverage_calendar_confirmed(gov_id, agendacenter_url):
    """Confirms `suspected_calendar_provider=civicplus` and
    `example_agenda_or_calendar_url` even when no video was found --
    this run DID confirm a real CivicPlus AgendaCenter page for this
    government (a positive fact worth keeping), it just had no video.
    Applied to every row matching `gov_id` (see
    update_coverage_reject_reason()'s docstring for why)."""

    def mutate(rows):
        matches = [row for row in rows if row.get("gov_id") == gov_id]
        changed = False
        for matched in matches:
            if not (matched.get("suspected_calendar_provider") or "").strip():
                matched["suspected_calendar_provider"] = "civicplus"
                changed = True
            if (
                agendacenter_url
                and not (matched.get("example_agenda_or_calendar_url") or "").strip()
            ):
                matched["example_agenda_or_calendar_url"] = agendacenter_url
                changed = True
        return changed

    return _coverage_read_modify_write(mutate)


def _safe_coverage_call(fn, *args, **kwargs):
    """Real, confirmed-live failure mode, 2026-09-09: WO-130 runs
    concurrently against this SAME jurisdiction_coverage.csv (counties,
    see CLAUDE.md's multi-session bullet), and this pipeline crashed mid-
    run on a torn read -- csv.DictReader saw a row with more fields than
    the header (`restkey=None`), which only happens when a concurrent
    writer's own rewrite was caught mid-flight. Re-reading immediately
    after (this file's own docstrings' "safe" pattern) protects against
    stale data, not against reading a half-written file -- there's no
    real file lock here. One retry after a short pause covers the
    transient case (the other writer's rewrite finishes fast); if it
    fails twice, this candidate's coverage-file update is skipped rather
    than crashing the whole run -- its own REPORT_CSV row already has
    the real outcome, so nothing about the actual resolve/ingest result
    is lost, only this one cross-reference write."""
    for attempt in (1, 2):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            print(f"[COV-ERR] {fn.__name__}{args!r} attempt {attempt}: {e!r}")
            if attempt == 2:
                return False
            time.sleep(2)
    return False


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


async def process_candidate(session, finder, candidate, report):
    gov_id = candidate["gov_id"]
    unit_name = candidate["unit_name"]
    row_out = {field: "" for field in REPORT_FIELDS}
    row_out["gov_id"] = gov_id
    row_out["unit_name"] = unit_name

    domain = candidate["web_address"].strip()
    if not domain:
        row_out.update(outcome="no-domain", detail="empty web_address")
        report.write(row_out)
        print(f"[NO-DOM ] {gov_id} {unit_name}")
        return
    row_out["domain"] = domain

    agendacenter_url = f"https://{domain}/AgendaCenter"

    try:
        result = await finder.resolve(agendacenter_url)
        meeting_url = result.source_url
    except NoVideoCandidateFound as e:
        row_out.update(
            outcome="no-video-found",
            jurisdiction=e.jurisdiction_hint or "",
            detail=f"checked {e.candidates_checked} candidate row(s), none had video",
        )
        report.write(row_out)
        print(f"[NO-VID ] {gov_id} {unit_name}  checked {e.candidates_checked} row(s)")
        if not DRY_RUN:
            updated = _safe_coverage_call(
                update_coverage_reject_reason, gov_id, "no-video-found"
            )
            _safe_coverage_call(
                update_coverage_calendar_confirmed, gov_id, agendacenter_url
            )
            print(
                f"[COVERAGE] {gov_id} {unit_name}  "
                + ("reject_reason=no-video-found" if updated else "no update")
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
        result.agenda_link = result.agenda_link or picked.get("agenda_link")
        result.packet_link = result.packet_link or picked.get("packet_link")
        row_out["detail"] = f"picked 1 of {len(e.candidates)} real video rows"
    except Exception as e:
        row_out.update(outcome="resolve-failed", detail=f"resolve raised: {e}")
        report.write(row_out)
        print(f"[FAILED ] {gov_id} {unit_name}  {e}")
        await asyncio.sleep(RESOLVE_DELAY_SECONDS)
        return

    # Known-jurisdiction pin (see module docstring point 2): this
    # candidate's own "{name}, {state}" from the coverage registry wins
    # outright over whatever the delegated video platform guessed.
    if unit_name:
        result.jurisdiction = unit_name

    row_out["meeting_url"] = meeting_url
    row_out["platform"] = result.platform or ""
    row_out["jurisdiction"] = result.jurisdiction or ""
    row_out["segments"] = len(result.segments)
    row_out["agenda_items"] = len(result.agenda_items)
    row_out["video_url"] = result.video_url or ""

    # Ryan's rule, exactly: ONLY meetings with video get ingested here.
    # Agenda-only (no video at all) is recorded as no-video-found, never
    # ingested -- stricter than adhoc_civicplus_pipeline.py's own gate,
    # see module docstring point 1.
    if not result.video_url:
        row_out.update(
            tier="none",
            outcome="no-video-found",
            detail=row_out["detail"]
            or "; ".join(result.video_warnings or [])
            or "resolved but no video_url (agenda-only or empty)",
        )
        report.write(row_out)
        print(
            f"[NO-VID ] {gov_id} {unit_name}  {agendacenter_url}  (agenda-only or empty)"
        )
        if not DRY_RUN:
            updated = _safe_coverage_call(
                update_coverage_reject_reason, gov_id, "no-video-found"
            )
            _safe_coverage_call(
                update_coverage_calendar_confirmed, gov_id, agendacenter_url
            )
            print(
                f"[COVERAGE] {gov_id} {unit_name}  "
                + ("reject_reason=no-video-found" if updated else "no update")
            )
        await asyncio.sleep(RESOLVE_DELAY_SECONDS)
        return

    normalized = normalize_url(meeting_url)
    tier = "tier1" if result.segments else "tier3-video-only"
    row_out["tier"] = tier

    if DRY_RUN:
        row_out.update(outcome=f"dry-run-{tier}")
        print(
            f"[DRYRUN ] {gov_id} {unit_name}  {meeting_url}  {tier}  jurisdiction={result.jurisdiction}"
        )
    elif tier == "tier1":
        try:
            response = await ingest(session, result.model_dump(), normalized)
            page_url = response.get("url") if response else None
            row_out.update(outcome="ingested", detail=page_url or "")
            print(f"[INGEST ] {gov_id} {unit_name}  {meeting_url}  {tier}  {page_url}")
            _safe_coverage_call(
                update_coverage_on_success,
                gov_id,
                shares_video=True,
                transcribed=True,
                example_meeting_url=page_url or meeting_url,
                agendacenter_url=agendacenter_url,
                video_platform=result.platform or "",
            )
        except Exception as e:
            row_out.update(outcome="ingest-failed", detail=str(e))
            print(f"[ING-ERR] {gov_id} {unit_name}  {meeting_url}  {e}")
    else:
        with open(QUEUE_FILE, "a") as qf:
            qf.write(meeting_url + "\n")
        row_out.update(outcome="queued", detail="tier3_auto_transcription_queue.txt")
        print(f"[QUEUED ] {gov_id} {unit_name}  {meeting_url}  tier3-video-only")
        _safe_coverage_call(
            update_coverage_on_success,
            gov_id,
            shares_video=True,
            transcribed=False,
            example_meeting_url=meeting_url,
            agendacenter_url=agendacenter_url,
            video_platform=result.platform or "",
        )

    report.write(row_out)
    await asyncio.sleep(RESOLVE_DELAY_SECONDS)


async def main():
    register_all_finders()
    finder = CivicPlusAssetFinder()

    hits_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_HITS_CSV
    candidates = load_candidates(hits_path)
    done = load_done_gov_ids(REPORT_CSV)
    todo = [c for c in candidates if c["gov_id"] not in done]

    print(
        f"{len(candidates)} total hits, {len(done)} already processed, "
        f"{len(todo)} to go (from {hits_path})"
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
