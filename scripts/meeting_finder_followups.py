"""WO-1040: turn Meeting Finder's approved finds into Archive ingests,
tier-3 queue lines, and YouTube drip leads.

Meeting Finder (`app/platforms/meeting_finder/`) resolves a government
domain down to a verdict row (`docs/MEETING_FINDER.md`) but is
deliberately read-only itself -- its own module docstring
(`app/platforms/meeting_finder/verdict.py`) says so: "nothing is ingested
or queued from here." This script is the plumbing that turns an
overnight batch's approved output into the three real actions Ryan asked
for (2026-09-24): an Archive ingest for tier-1 finds, a tier-3 queue line
for tier-3 finds, and a YouTube drip-lead row for tier-2/youtube-lead-only
finds -- reusing the existing, already-tested machinery for each
(`scripts.bulk_ingest.process_one`, `app.platforms.queue_probe`'s queue
helpers, the `record_youtube_lead()` shape) rather than reinventing any
of them.

**A confirmed, load-bearing gap found while building this (verify before
you rely on `ingest_plan.csv`/`queue_lines.txt` looking "empty" or full
of failures): Meeting Finder's own verdict output never keeps the
meeting/candidate PAGE url `resolve()` was actually called with -- only
the pre-resolve homepage hop trail (`VerdictRow.path`) and the final
RESOLVED VIDEO URL (`VerdictRow.result_url`, e.g. a raw
archive-stream.granicus.com .m3u8 or a cpmedia.azureedge.net .mp4).**
`resolve.py`'s own `_try_resolve()` calls `finder.resolve(cand.url)` on
`Candidate.url` (the real page), but that Candidate is never persisted
into `VerdictRow`/the JSONL (`app/platforms/meeting_finder/verdict.py`'s
`CSV_FIELDS`/`VerdictRow` have no such field). `finds.json`'s `path`
column is the pre-resolve trail (the government's own pages hit while
looking for a link), not the tenant/platform meeting page.

Confirmed live 2026-09-24, calling `app.platforms.base.get_finder(platform)
.resolve()` directly on three real `result_url`s from this batch's
confident/approved rows:

  * Vimeo (`player.vimeo.com/video/...`): resolves cleanly -- Vimeo's own
    player URL IS its real resolve input, so `result_url` already IS the
    right thing to ingest. Real example: Lenoir County, NC
    (`us:county:37107`) came back with 801 real caption segments.
  * A CivicClerk raw `cpmedia.azureedge.net/.../*.mp4` URL: `detect_platform()`
    doesn't even recognize it as CivicClerk (that host isn't a CivicClerk
    tenant domain) -- it falls through to the generic `direct_file`
    adapter instead, which happily treats the bare mp4 as the whole
    meeting. Ingestable, but as `platform=direct_file` (no title, no
    transcript, video only) rather than the real `civicclerk` provenance.
  * A Granicus `archive-stream.granicus.com/.../playlist.m3u8` URL (also
    covers Swagit and IQM2, which serve their video off the same Granicus
    CDN host): `detect_platform()` DOES match "granicus" (the substring
    is in the CDN hostname), so it never falls through to `direct_file`
    -- but `GranicusAssetFinder.resolve()` needs the real
    `MediaPlayer.php`/on-demand PAGE, not the raw stream, so it returns
    an empty, useless result (no title, no video_url, no segments)
    instead of raising. `bulk_ingest.process_one()`'s own existing gate
    (`result.segments or result.agenda_items or result.agenda_link or
    result.video_url`) then reports this as a plain "skipped" with no
    indication that the URL was even the wrong shape.

Net effect: this script's ingest/queue candidates are real and worth
acting on, but for every platform except Vimeo (and, coincidentally,
whatever a bare CDN mp4/mp3 URL happens to fall through to `direct_file`
as), a resolve attempt against `result_url` alone is not expected to
produce a real transcript -- see this module's own `--live-check` output
and BACKLOG.md's "Meeting Finder verdicts don't keep the candidate page
URL, only the final video URL" entry (filed alongside this WO) for the
recommended fix (add a `candidate_url` field to `VerdictRow`).

Never guesses a page URL to work around this: `ingest_plan.csv` records
exactly what a real `--live-check` resolve attempt against `result_url`
found (or, without `--live-check`, marks it "not checked"), and
`queue_lines.txt` queues the real `result_url` anyway for tier-3 rows --
Ryan's rule (feed_tier3_auto_transcription.py's own docstring) is that a
stale/wrong-shaped queue candidate just fails cleanly at pickup time
rather than corrupting anything, so queuing it is safe even when today's
check says it won't resolve.

Inputs (all read-only, all local files -- nothing here talks to
rtr-business over the network and nothing here mutates it):
  --finds        followup/finds.json: every found row, grouped `confident`/
                 `hand-check`/`drip-tier2`/`hold-direct-file` (see WO-1040.md).
  --approved     followup/approved.csv (optional -- until the conductor
                 writes it, dry-run runs on confident rows only): header
                 `domain,gov_id,verdict,...`; a `verdict=approve` row joins
                 a matching `hand-check` finds.json row into the same
                 pipeline as a `confident` one. Joined on the EXACT
                 (domain, gov_id) pair, never on either alone -- two finds.json
                 rows can share a domain with two different gov_ids (a real
                 case in this batch: "hingham-ma.gov" filed under both the
                 real Hingham, MA, us:cousub:2502330210, and a Montana
                 research-file data error, us:place:3036400 -- only the
                 first is ever in approved.csv, and a domain-only join
                 would have wrongly pulled the Montana row in too).
  --verdicts-jsonl (repeatable) overnight/verdicts.csv.jsonl-shaped files,
                 for `outcome=="youtube-lead-only"` rows' `leads` field
                 (drip candidates that never came through finds.json at
                 all -- WO-1040.md step 3).

Modes (all additive -- the plan is always computed and written to
--out-dir; each flag below does one more REAL, shared-state thing on top
of that plan, and none of them run unless explicitly passed):
  (default)       dry run only -- writes ingest_plan.csv, queue_lines.txt,
                  drip_leads.csv, research_rows.csv, summary.md under
                  --out-dir. Touches no shared file, the Archive, or
                  rtr-business.
  --live-check    additionally resolves each ingest/queue candidate's
                  result_url for real (no Archive write) via
                  scripts.bulk_ingest.process_one(dry_run=True), to fill
                  in ingest_plan.csv's real would-ingest/no-content/error
                  verdict instead of leaving it "not checked". Makes real
                  HTTP requests to each government's own video host.
  --apply-ingest  also POSTs every tier-1 candidate to the real Archive
                  (scripts.bulk_ingest.process_one(dry_run=False)) --
                  a real, live ingest. Conductor-run only.
  --apply-queue   also appends real queue lines to the real
                  scripts/tier3_auto_transcription_queue.txt. Conductor-run
                  only.
  --emit-leads PATH  also writes the drip-lead rows in the exact
                  `record_youtube_lead()`/youtube_channel_leads.csv column
                  shape to PATH, for the conductor to append to the real
                  rtr-business/research/youtube_channel_leads.csv by hand
                  (this script never writes into rtr-business itself).

Dedupe: an ingest/queue candidate already queued (`queue_probe.is_queued()`)
or already an Archive page (best-effort `GET /internal/lookup`, skipped
with a note if ARCHIVE_BASE_URL/ARCHIVE_INGEST_TOKEN aren't set) is left
out of the actionable plan and recorded in the "already done" bucket
instead. A drip lead already in the real youtube_channel_leads.csv (read
once, up front) is left out of drip_leads.csv too.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

import certifi

# Must run before `import aiohttp` -- see scripts/bulk_ingest.py's own
# longer comment on this exact fix (a fresh Homebrew-Python venv has an
# empty default SSL trust store, and aiohttp caches its SSLContext at
# import time).
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

load_dotenv()

from scripts.youtube_fetch_guard import install as install_youtube_guard  # noqa: E402

install_youtube_guard()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.queue_probe import (  # noqa: E402
    TIER3_QUEUE_FILE,
    append_queue_line,
    is_queued,
)
from app.utils.url_normalize import normalize_url  # noqa: E402
from scripts.bulk_ingest import process_one  # noqa: E402

register_all_finders()

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
YOUTUBE_LEADS_CSV = RESEARCH_DIR / "youtube_channel_leads.csv"

YOUTUBE_LEAD_FIELDNAMES = [
    "channel_url",
    "gov_id",
    "government",
    "state",
    "source_wo",
    "kind",
    "verified",
    "note",
]

RESEARCH_ROW_FIELDNAMES = [
    "gov_id",
    "domain",
    "government",
    "shares_video",
    "suspected_video_provider",
    "queued",
    "transcribed",
    "note",
]

DEFAULT_LEAD_SOURCE = "meeting-finder-2026-09-24"

_YOUTUBE_CHANNEL_PATH_MARKERS = ("/channel/", "/c/", "/@", "/user/")

# Confirmed live 2026-09-24 (see this module's docstring): `app.platforms.
# direct_file.is_direct_file_url()`'s own Google Drive check
# (`_DRIVE_FILE_ID_RE = re.compile(r"drive\.google\.com/file/d/([\w-]+)")`)
# only matches Drive's classic VIEWER share-link shape
# (`drive.google.com/file/d/<id>/view`), which that same module's resolve
# path then REWRITES into the real download URL
# (`drive.usercontent.google.com/download?id=<id>&export=download&confirm=t`).
# It does not also recognize that already-rewritten download URL as
# input. `detect_platform()` therefore returns "unknown" for a
# `drive.usercontent.google.com/download?id=...` URL passed in directly
# (no extension in the URL either, so the generic media_type() fallback
# doesn't catch it), and `get_finder()` raises `UnsupportedPlatformError`
# -- confirmed live against a real approved_direct.csv row (Martin County
# School District, MN, us:sd:2718960). Several `approved_direct.csv` rows
# (WO-1040) carry exactly this already-rewritten shape (whoever hand-
# verified them followed the link to its real download URL and recorded
# that, not the original share link) -- this constant flags them so the
# dry-run summary calls this out explicitly rather than silently queuing
# something that can never resolve as the adapter is coded today. See
# BACKLOG.md's matching entry (filed alongside this WO) for the
# recommended fix: teach `is_direct_file_url()`/the Drive rewrite in
# `app/platforms/direct_file.py` to also recognize
# `usercontent.google.com/download` URLs directly, not just the classic
# `drive.google.com/file/d/` share link.
_DRIVE_DOWNLOAD_URL_MARKER = "drive.usercontent.google.com/download"


def is_known_unresolvable_today(url: str) -> str:
    """Returns a plain-language reason string when `url` is a known,
    already-confirmed-live gap in the current adapters (not a guess --
    see `_DRIVE_DOWNLOAD_URL_MARKER`'s own comment), or "" otherwise."""
    if _DRIVE_DOWNLOAD_URL_MARKER in url:
        return (
            "Google Drive download URL (drive.usercontent.google.com/download?id=...) -- "
            "app/platforms/direct_file.py's is_direct_file_url() only recognizes the classic "
            "drive.google.com/file/d/<id> share link, not this already-rewritten download URL "
            "(confirmed live 2026-09-24); detect_platform() returns 'unknown' for it today"
        )
    return ""


# ---------------------------------------------------------------------------
# Loading + grouping
# ---------------------------------------------------------------------------


@dataclass
class Candidate:
    """One finds.json row, plus whether/why it's actionable tonight."""

    domain: str
    gov_id: str
    government: str
    tier: str
    platform: str
    result_url: str
    path: str
    note: str
    group: str
    approved: bool
    approval_reason: str = ""


def load_finds(path: Path) -> List[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_approved(path: Optional[Path]) -> Dict[Tuple[str, str], dict]:
    """Returns {(domain, gov_id): row}. Missing file -> {} (WO-1040.md:
    "Until it exists, build and dry-run with the confident rows only")."""
    if path is None or not path.exists():
        return {}
    out: Dict[Tuple[str, str], dict] = {}
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            key = (row["domain"].strip(), row["gov_id"].strip())
            out[key] = row
    return out


def load_approved_direct(path: Optional[Path]) -> List[Candidate]:
    """`followup/approved_direct.csv` (same header as approved.csv):
    hand-approved direct audio/video files -- Ryan approved these
    directly, not through the finds.json hold-direct-file/hand-check
    flow, so they're not joined against finds.json at all. All tier 3
    today; still routed through the same tier-3 planner as everything
    else so they get the same is_queued()/already-archived checks."""
    if path is None or not path.exists():
        return []
    out: List[Candidate] = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (row.get("verdict") or "").strip().lower() != "approve":
                continue
            out.append(
                Candidate(
                    domain=row["domain"].strip(),
                    gov_id=row["gov_id"].strip(),
                    government="",
                    tier=row.get("tier", "3").strip() or "3",
                    platform=row.get("platform", "direct_file").strip()
                    or "direct_file",
                    result_url=(row.get("result_url") or "").strip(),
                    path="",
                    note=row.get("evidence") or "",
                    group="approved-direct",
                    approved=True,
                    approval_reason="approved_direct.csv",
                )
            )
    return out


def classify(
    finds: List[dict], approved: Dict[Tuple[str, str], dict]
) -> Tuple[List[Candidate], List[Candidate], List[Candidate], List[Candidate]]:
    """Splits finds.json rows into (tier1_candidates, tier3_candidates,
    held, pending_handcheck).

    Joined on the EXACT (domain, gov_id) pair -- never domain alone or
    gov_id alone (see this module's docstring for the real hingham-ma.gov
    case this guards against). `group == "hold-direct-file"` is never
    actionable regardless of approved.csv -- Ryan approved ingest/queue/
    drip for "the confident finds and the hand-check-approved finds"
    only (WO-1040.md); direct-file finds are held for a separate review,
    not part of tonight's approval. `group == "drip-tier2"` rows are
    handled separately (see `drip_candidates_from_finds`), not through
    this function."""
    tier1: List[Candidate] = []
    tier3: List[Candidate] = []
    held: List[Candidate] = []
    pending: List[Candidate] = []

    for row in finds:
        group = row["group"]
        key = (row["domain"], row["gov_id"])

        if group == "confident":
            approved_flag, reason = True, "confident"
        elif group == "hand-check":
            approved_row = approved.get(key)
            if approved_row is None:
                pending.append(
                    Candidate(
                        domain=row["domain"],
                        gov_id=row["gov_id"],
                        government=row["government"],
                        tier=row["tier"],
                        platform=row["platform"],
                        result_url=row["result_url"] or "",
                        path=row["path"],
                        note=row["note"],
                        group=group,
                        approved=False,
                        approval_reason="no approved.csv row yet",
                    )
                )
                continue
            verdict = (approved_row.get("verdict") or "").strip().lower()
            if verdict != "approve":
                pending.append(
                    Candidate(
                        domain=row["domain"],
                        gov_id=row["gov_id"],
                        government=row["government"],
                        tier=row["tier"],
                        platform=row["platform"],
                        result_url=row["result_url"] or "",
                        path=row["path"],
                        note=row["note"],
                        group=group,
                        approved=False,
                        approval_reason=f"approved.csv verdict={verdict!r}",
                    )
                )
                continue
            approved_flag, reason = True, "hand-check approved"
        else:
            # drip-tier2 (handled elsewhere) or hold-direct-file (never
            # actionable tonight).
            if group == "hold-direct-file":
                held.append(
                    Candidate(
                        domain=row["domain"],
                        gov_id=row["gov_id"],
                        government=row["government"],
                        tier=row["tier"],
                        platform=row["platform"],
                        result_url=row["result_url"] or "",
                        path=row["path"],
                        note=row["note"],
                        group=group,
                        approved=False,
                        approval_reason="hold-direct-file: not part of tonight's approval",
                    )
                )
            continue

        cand = Candidate(
            domain=row["domain"],
            gov_id=row["gov_id"],
            government=row["government"],
            tier=row["tier"],
            platform=row["platform"],
            result_url=row["result_url"] or "",
            path=row["path"],
            note=row["note"],
            group=group,
            approved=approved_flag,
            approval_reason=reason,
        )
        if row["tier"] == "1":
            tier1.append(cand)
        elif row["tier"] == "3":
            tier3.append(cand)
        else:
            # tier "2" rows never carry group confident/hand-check in
            # finds.json today (they're always drip-tier2), but a
            # tier-1/tier-3-only assumption would silently drop a future
            # shape change rather than surfacing it.
            pending.append(
                Candidate(
                    domain=row["domain"],
                    gov_id=row["gov_id"],
                    government=row["government"],
                    tier=row["tier"],
                    platform=row["platform"],
                    result_url=row["result_url"] or "",
                    path=row["path"],
                    note=row["note"],
                    group=group,
                    approved=False,
                    approval_reason=f"unexpected tier {row['tier']!r} for group {group!r}",
                )
            )

    return tier1, tier3, held, pending


def source_url_from_path(path_field: str, result_url: str) -> str:
    """The queue-line "source_url" field (a reader's "View original
    source" link) should point at the government's own page, not the
    video host -- see append_queue_line()'s own docstring. finds.json's
    `path` is " -> "-joined; its last hop is the government's own page
    where Meeting Finder found the video link (never the platform tenant
    page itself, since Meeting Finder doesn't persist that -- see this
    module's docstring). Returns "" when it's the same as result_url or
    there's no real path recorded."""
    hops = [h.strip() for h in (path_field or "").split("->") if h.strip()]
    if not hops:
        return ""
    last = hops[-1]
    return last if last != result_url else ""


# ---------------------------------------------------------------------------
# Drip leads (YouTube, never fetched)
# ---------------------------------------------------------------------------


@dataclass
class DripLead:
    url: str
    gov_id: str
    government: str
    domain: str
    kind: str
    note: str


def drip_candidates_from_finds(finds: List[dict]) -> List[DripLead]:
    """group == "drip-tier2" rows -- always eligible (WO-1040.md step 3
    doesn't gate these on hand-check approval; they were "saved as a drip
    lead, never fetched" at Meeting Finder time already)."""
    out = []
    for row in finds:
        if row["group"] != "drip-tier2":
            continue
        url = row.get("result_url") or ""
        if not url:
            continue
        kind = (
            "channel"
            if any(m in url for m in _YOUTUBE_CHANNEL_PATH_MARKERS)
            else "single_video"
        )
        out.append(
            DripLead(
                url=url,
                gov_id=row["gov_id"],
                government=row["government"],
                domain=row["domain"],
                kind=kind,
                note=row.get("note") or "",
            )
        )
    return out


def drip_candidates_from_verdicts_jsonl(
    jsonl_paths: Iterable[Path], government_lookup: Dict[Tuple[str, str], str]
) -> List[DripLead]:
    """`outcome == "youtube-lead-only"` rows' `leads` field (WO-1040.md
    step 3). A row's `leads` list often repeats the same URL several
    times (found at multiple hops) -- deduped per (domain, url) here.
    `government_lookup` maps (domain, gov_id) -> government name, built
    from finds.json, since these jsonl rows carry only `input_url`
    (domain) and `identity_expected_gov_id`, never a government name."""
    seen: Set[Tuple[str, str]] = set()
    out: List[DripLead] = []
    for jsonl_path in jsonl_paths:
        if not jsonl_path.exists():
            continue
        with open(jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                row = json.loads(line)
                if row.get("outcome") != "youtube-lead-only":
                    continue
                domain = row.get("input_url") or ""
                gov_id = row.get("identity_expected_gov_id") or ""
                for lead in row.get("leads") or []:
                    if lead.get("kind") != "youtube":
                        continue
                    url = lead.get("url") or ""
                    if not url:
                        continue
                    key = (domain, url)
                    if key in seen:
                        continue
                    seen.add(key)
                    kind = (
                        "channel"
                        if any(m in url for m in _YOUTUBE_CHANNEL_PATH_MARKERS)
                        else "single_video"
                    )
                    government = government_lookup.get((domain, gov_id), "")
                    out.append(
                        DripLead(
                            url=url,
                            gov_id=gov_id,
                            government=government,
                            domain=domain,
                            kind=kind,
                            note=row.get("note") or "",
                        )
                    )
    return out


def build_government_lookup(finds: List[dict]) -> Dict[Tuple[str, str], str]:
    return {(row["domain"], row["gov_id"]): row["government"] for row in finds}


def load_existing_lead_urls(path: Path = YOUTUBE_LEADS_CSV) -> Set[str]:
    """Read-only: the set of channel_url values already in the real
    shared youtube_channel_leads.csv, so drip_leads.csv doesn't propose a
    row that's already there. Never writes to `path`. Missing file (e.g.
    this checkout has no rtr-business sibling) -> empty set, not an
    error, since a fresh dry run should still work."""
    if not path.exists():
        return set()
    seen: Set[str] = set()
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or line.startswith("channel_url,"):
                continue
            first_field = line.split(",", 1)[0].strip()
            if first_field:
                seen.add(first_field)
    return seen


def dedupe_drip_leads(
    leads: List[DripLead], existing_urls: Set[str]
) -> Tuple[List[DripLead], List[DripLead]]:
    """Returns (new, already_present) -- deduped by exact URL against
    `existing_urls` and against duplicates within `leads` itself."""
    new: List[DripLead] = []
    already: List[DripLead] = []
    seen_this_run: Set[str] = set()
    for lead in leads:
        if lead.url in existing_urls or lead.url in seen_this_run:
            already.append(lead)
            continue
        seen_this_run.add(lead.url)
        new.append(lead)
    return new, already


# ---------------------------------------------------------------------------
# Archive "already a page" check (read-only GET /internal/lookup)
# ---------------------------------------------------------------------------


def _archive_base_url() -> str:
    return os.environ.get("ARCHIVE_BASE_URL", "").rstrip("/")


def _archive_headers() -> dict:
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


async def already_archived(
    session: aiohttp.ClientSession, url: str
) -> Tuple[Optional[bool], str]:
    """Best-effort GET /internal/lookup?normalized_url=... check --
    never writes anything. Returns (True/False, "") on a real answer, or
    (None, reason) when the check couldn't be made (no ARCHIVE_BASE_URL
    configured, or the request itself failed) -- a caller should treat
    None as "unknown, not as False", per CLAUDE.md's "reports report,
    never guess" rule."""
    base = _archive_base_url()
    if not base:
        return None, "ARCHIVE_BASE_URL not set -- skipped"
    normalized = normalize_url(url)
    try:
        async with session.get(
            f"{base}/internal/lookup",
            params={"normalized_url": normalized},
            headers=_archive_headers(),
            timeout=aiohttp.ClientTimeout(total=20),
        ) as response:
            if response.status == 200:
                return True, ""
            if response.status == 404:
                return False, ""
            return None, f"lookup returned {response.status}"
    except Exception as e:  # noqa: BLE001
        return None, f"lookup failed: {e}"


# ---------------------------------------------------------------------------
# Ingest / queue planning
# ---------------------------------------------------------------------------


@dataclass
class PlanRow:
    candidate: Candidate
    action: str  # "would-ingest" | "would-queue" | "already-queued" | "already-archived" | "resolve-check-skipped" | "would-not-ingest" | "resolve-error"
    detail: str = ""
    source_url: str = ""


async def plan_tier1(
    session: aiohttp.ClientSession,
    candidates: List[Candidate],
    *,
    live_check: bool,
) -> List[PlanRow]:
    rows: List[PlanRow] = []
    for cand in candidates:
        archived, archived_reason = await already_archived(session, cand.result_url)
        if archived:
            rows.append(PlanRow(cand, "already-archived", archived_reason))
            continue
        if not live_check:
            rows.append(
                PlanRow(cand, "not-checked", "pass --live-check to resolve for real")
            )
            continue
        result = await process_one(
            session, cand.result_url, dry_run=True, gov_id=cand.gov_id
        )
        detail = result["detail"]
        if detail.startswith("[dry-run] would ingest"):
            rows.append(PlanRow(cand, "would-ingest", detail))
        elif "no transcript, agenda items, agenda link, or video found" in detail:
            rows.append(PlanRow(cand, "would-not-ingest", detail))
        else:
            rows.append(PlanRow(cand, "resolve-error", detail))
    return rows


async def plan_tier3(
    session: aiohttp.ClientSession,
    candidates: List[Candidate],
    *,
    live_check: bool,
) -> List[PlanRow]:
    rows: List[PlanRow] = []
    for cand in candidates:
        if is_queued(cand.result_url):
            rows.append(PlanRow(cand, "already-queued"))
            continue
        archived, archived_reason = await already_archived(session, cand.result_url)
        if archived:
            rows.append(PlanRow(cand, "already-archived", archived_reason))
            continue
        source_url = source_url_from_path(cand.path, cand.result_url)

        # A structural, already-confirmed-live gap (e.g. the Google Drive
        # download-URL shape -- see is_known_unresolvable_today()'s own
        # comment) is worth flagging even without --live-check, since it
        # needs no network call to know. Ryan's rule (WO-1040.md) still
        # applies: queue it anyway rather than dropping it silently --
        # a future adapter fix (see BACKLOG.md) then picks it up on its
        # own the next time the feed script tries it.
        known_gap = is_known_unresolvable_today(cand.result_url)

        if not live_check:
            detail = known_gap or "not checked -- pass --live-check to resolve for real"
            rows.append(PlanRow(cand, "would-queue", detail, source_url))
            continue
        result = await process_one(
            session, cand.result_url, dry_run=True, gov_id=cand.gov_id
        )
        detail = result["detail"]
        if known_gap:
            detail = f"{known_gap} (live check: {detail})"
        # Ryan's rule (WO-1040.md): tier-3 candidates are queued
        # regardless of what a resolve check finds today -- a stale/
        # wrong-shaped URL just fails cleanly at pickup time
        # (feed_tier3_auto_transcription.py's own docstring). The check
        # result rides along as `detail` for a human to weigh, never as
        # a reason to skip queueing.
        rows.append(PlanRow(cand, "would-queue", detail, source_url))
    return rows


# ---------------------------------------------------------------------------
# Research-file proposed rows (PROPOSED ONLY -- never writes jurisdiction_coverage.csv)
# ---------------------------------------------------------------------------


def research_rows_for(
    tier1_rows: List[PlanRow], tier3_rows: List[PlanRow]
) -> List[dict]:
    out = []
    for row in tier1_rows:
        if row.action in ("already-archived",):
            continue
        c = row.candidate
        out.append(
            {
                "gov_id": c.gov_id,
                "domain": c.domain,
                "government": c.government,
                "shares_video": "True",
                "suspected_video_provider": c.platform,
                "queued": "",
                "transcribed": "True" if row.action == "would-ingest" else "",
                "note": (
                    f"PROPOSED via WO-1040 Meeting Finder followups ({row.action}); "
                    "apply under ENUMERATION_METHODS.md's §158 write protocol, not by this script"
                ),
            }
        )
    for row in tier3_rows:
        if row.action in ("already-archived", "already-queued"):
            continue
        c = row.candidate
        out.append(
            {
                "gov_id": c.gov_id,
                "domain": c.domain,
                "government": c.government,
                "shares_video": "True",
                "suspected_video_provider": c.platform,
                "queued": "True",
                "transcribed": "",
                "note": (
                    f"PROPOSED via WO-1040 Meeting Finder followups ({row.action}); "
                    "apply under ENUMERATION_METHODS.md's §158 write protocol, not by this script"
                ),
            }
        )
    return out


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------


def write_ingest_plan(path: Path, rows: List[PlanRow]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "domain",
                "gov_id",
                "government",
                "platform",
                "result_url",
                "action",
                "approval_reason",
                "detail",
            ]
        )
        for row in rows:
            c = row.candidate
            w.writerow(
                [
                    c.domain,
                    c.gov_id,
                    c.government,
                    c.platform,
                    c.result_url,
                    row.action,
                    c.approval_reason,
                    row.detail,
                ]
            )


def write_queue_lines(path: Path, rows: List[PlanRow]) -> None:
    """The exact line shape append_queue_line() writes for real
    (`url\\tsource_url\\tgov_id`), for every row this plan would queue --
    written here for review only, never appended to the real
    scripts/tier3_auto_transcription_queue.txt (that's --apply-queue's job)."""
    with open(path, "w", encoding="utf-8") as f:
        for row in rows:
            if row.action != "would-queue":
                continue
            c = row.candidate
            f.write(f"{c.result_url}\t{row.source_url}\t{c.gov_id}\n")


def write_drip_leads(path: Path, leads: List[DripLead], source: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=YOUTUBE_LEAD_FIELDNAMES)
        w.writeheader()
        for lead in leads:
            w.writerow(
                {
                    "channel_url": lead.url,
                    "gov_id": lead.gov_id,
                    "government": lead.government,
                    "state": "",
                    "source_wo": source,
                    "kind": lead.kind,
                    "verified": "false",
                    "note": f"not fetched (YouTube drip only); {lead.note}".strip("; "),
                }
            )


def write_research_rows(path: Path, rows: List[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=RESEARCH_ROW_FIELDNAMES)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def write_summary(
    path: Path,
    *,
    tier1_rows: List[PlanRow],
    tier3_rows: List[PlanRow],
    held: List[Candidate],
    pending: List[Candidate],
    new_leads: List[DripLead],
    already_leads: List[DripLead],
    live_check: bool,
) -> None:
    def count(rows: List[PlanRow], action: str) -> int:
        return sum(1 for r in rows if r.action == action)

    lines = []
    lines.append("# WO-1040 Meeting Finder followups: dry-run summary\n")
    lines.append(
        "Purpose: turn tonight's approved Meeting Finder finds into an Archive ingest plan, "
        "a tier-3 queue plan, and a YouTube drip-lead list, without touching anything live.\n"
    )
    lines.append(
        f"Live resolve check: {'on' if live_check else 'off (pass --live-check for real verdicts)'}\n"
    )

    lines.append("## Tier 1 (Archive ingest candidates)\n")
    lines.append("| Result | Count |")
    lines.append("|---|---|")
    lines.append(f"| Would ingest | {count(tier1_rows, 'would-ingest')} |")
    lines.append(
        f"| Would not ingest (no content found) | {count(tier1_rows, 'would-not-ingest')} |"
    )
    lines.append(f"| Resolve error | {count(tier1_rows, 'resolve-error')} |")
    lines.append(
        f"| Already an Archive page | {count(tier1_rows, 'already-archived')} |"
    )
    lines.append(
        f"| Not checked (no --live-check) | {count(tier1_rows, 'not-checked')} |"
    )
    lines.append(f"| Total tier-1 candidates | {len(tier1_rows)} |\n")

    lines.append("## Tier 3 (tier-3 queue candidates)\n")
    lines.append("| Result | Count |")
    lines.append("|---|---|")
    lines.append(f"| Would queue | {count(tier3_rows, 'would-queue')} |")
    lines.append(f"| Already queued | {count(tier3_rows, 'already-queued')} |")
    lines.append(
        f"| Already an Archive page | {count(tier3_rows, 'already-archived')} |"
    )
    lines.append(f"| Total tier-3 candidates | {len(tier3_rows)} |\n")

    known_gap_rows = [
        r
        for r in tier3_rows
        if r.action == "would-queue"
        and is_known_unresolvable_today(r.candidate.result_url)
    ]
    if known_gap_rows:
        lines.append(
            f'**{len(known_gap_rows)} of those "would queue" rows are queued anyway (Ryan\'s '
            "rule) but cannot resolve today with the code as it stands** -- a confirmed-live "
            "gap in `app/platforms/direct_file.py`'s Google Drive handling (see "
            "`is_known_unresolvable_today()`'s own comment in this script and BACKLOG.md's "
            "matching entry), not a guess:\n"
        )
        lines.append("| Domain | gov_id | Why it can't resolve today |")
        lines.append("|---|---|---|")
        for row in known_gap_rows:
            c = row.candidate
            reason = is_known_unresolvable_today(c.result_url)
            lines.append(f"| {c.domain} | {c.gov_id} | {reason} |")
        lines.append("")

    lines.append("## YouTube drip leads\n")
    lines.append("| Result | Count |")
    lines.append("|---|---|")
    lines.append(
        f"| New leads (not already in youtube_channel_leads.csv) | {len(new_leads)} |"
    )
    lines.append(f"| Already in youtube_channel_leads.csv | {len(already_leads)} |\n")

    lines.append("## Held / not part of tonight's plan\n")
    lines.append("| Result | Count |")
    lines.append("|---|---|")
    lines.append(f"| Held (hold-direct-file, out of scope tonight) | {len(held)} |")
    lines.append(f"| Pending hand-check (no approve verdict yet) | {len(pending)} |\n")

    total_actionable = (
        count(tier1_rows, "would-ingest")
        + count(tier3_rows, "would-queue")
        + len(new_leads)
    )
    lines.append(
        f"**Bottom line: {total_actionable} real actions ready for the conductor to run "
        f"(see the commands below), plus {len(held) + len(pending)} rows still waiting on a decision.**\n"
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


async def async_main(args: argparse.Namespace) -> None:
    finds = load_finds(Path(args.finds))
    approved = load_approved(Path(args.approved) if args.approved else None)

    tier1_candidates, tier3_candidates, held, pending = classify(finds, approved)
    tier3_candidates = tier3_candidates + load_approved_direct(
        Path(args.approved_direct) if args.approved_direct else None
    )

    government_lookup = build_government_lookup(finds)
    leads = drip_candidates_from_finds(finds) + drip_candidates_from_verdicts_jsonl(
        [Path(p) for p in args.verdicts_jsonl], government_lookup
    )
    existing_lead_urls = load_existing_lead_urls()
    new_leads, already_leads = dedupe_drip_leads(leads, existing_lead_urls)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    async with aiohttp.ClientSession() as session:
        tier1_rows = await plan_tier1(
            session, tier1_candidates, live_check=args.live_check
        )
        tier3_rows = await plan_tier3(
            session, tier3_candidates, live_check=args.live_check
        )

        if args.apply_ingest:
            for row in tier1_rows:
                if row.action != "would-ingest":
                    continue
                c = row.candidate
                result = await process_one(
                    session, c.result_url, dry_run=False, gov_id=c.gov_id
                )
                print(
                    f"[APPLY-INGEST][{result['status'].upper()}] {c.domain}: {result['detail']}"
                )

    if args.apply_queue:
        for row in tier3_rows:
            if row.action != "would-queue":
                continue
            c = row.candidate
            queued = append_queue_line(
                c.result_url,
                row.source_url,
                gov_id=c.gov_id,
                queue_path=TIER3_QUEUE_FILE,
            )
            print(
                f"[APPLY-QUEUE] {c.domain}: {'queued' if queued else 'already queued'}"
            )

    if args.emit_leads:
        write_drip_leads(Path(args.emit_leads), new_leads, args.lead_source)
        print(
            f"Wrote {len(new_leads)} new drip-lead rows to {args.emit_leads} for the conductor to append."
        )

    write_ingest_plan(out_dir / "ingest_plan.csv", tier1_rows)
    write_queue_lines(out_dir / "queue_lines.txt", tier3_rows)
    write_drip_leads(out_dir / "drip_leads.csv", new_leads, args.lead_source)
    write_research_rows(
        out_dir / "research_rows.csv", research_rows_for(tier1_rows, tier3_rows)
    )
    write_summary(
        out_dir / "summary.md",
        tier1_rows=tier1_rows,
        tier3_rows=tier3_rows,
        held=held,
        pending=pending,
        new_leads=new_leads,
        already_leads=already_leads,
        live_check=args.live_check,
    )
    print(f"Wrote plan files to {out_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--finds", required=True, help="Path to followup/finds.json")
    parser.add_argument(
        "--approved", default=None, help="Path to followup/approved.csv (optional)"
    )
    parser.add_argument(
        "--approved-direct",
        default=None,
        help="Path to followup/approved_direct.csv (optional): hand-approved direct audio/video files, all tier 3",
    )
    parser.add_argument(
        "--verdicts-jsonl",
        action="append",
        default=[],
        metavar="PATH",
        help="A verdicts.csv.jsonl file to harvest youtube-lead-only rows from; repeatable",
    )
    parser.add_argument(
        "--out-dir", required=True, help="Directory to write the dry-run plan files to"
    )
    parser.add_argument(
        "--live-check",
        action="store_true",
        help="Really resolve each ingest/queue candidate's result_url (no Archive write) instead of leaving it 'not checked'",
    )
    parser.add_argument(
        "--apply-ingest",
        action="store_true",
        help="Really POST would-ingest tier-1 rows to the Archive",
    )
    parser.add_argument(
        "--apply-queue",
        action="store_true",
        help="Really append would-queue tier-3 rows to the real tier-3 queue file",
    )
    parser.add_argument(
        "--emit-leads",
        default=None,
        metavar="PATH",
        help="Also write new drip-lead rows to PATH for the conductor to append",
    )
    parser.add_argument(
        "--lead-source",
        default=DEFAULT_LEAD_SOURCE,
        help="source_wo value written into drip-lead rows",
    )
    args = parser.parse_args()

    if args.apply_ingest and not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print("ERROR: --apply-ingest needs ARCHIVE_INGEST_TOKEN set.", file=sys.stderr)
        sys.exit(1)

    asyncio.run(async_main(args))


if __name__ == "__main__":
    main()
