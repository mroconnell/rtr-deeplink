"""WO-134 batch ingest for the WO-129 two-hop *confirmed-hit* candidates
(rtr-business/research/wo129_confirmed_hits.csv, 156 governments -- and,
if it appears before this run finishes, WO-133's headless re-check batch
at rtr-business/research/wo133_confirmed_hits.csv, same row shape, same
rules), per Ryan's 2026-09-09 instructions.

This is the SAME resolve/ingest pipeline scripts/nationwide_2404_ingest.py
already uses (app/platforms/base.py's detect_platform()/get_finder(), the
real POST /internal/ingest, the CivicPlus domain-gate bypass, the
CivicClerk listing-vs-single-event split, the title-safety gate, the
retry wrapper around the Archive POST, the ";"-lookahead hit_source_urls
parser) -- see that file's own docstring for the full history of bugs
those pieces fix. Three things are genuinely new here, all from Ryan's
own rules for this batch:

1. **"Go deep enough to find a meeting WITH VIDEO, not just the
   newest."** `nationwide_2404_ingest.py`'s `pick_calendar_candidate()`
   only ever tried the single best-titled candidate and gave up if IT
   had no video -- even when an older candidate two rows down the same
   listing did. `pick_calendar_candidates()` below returns an ORDERED
   list (newest first, title-clean) instead of one pick, and
   `resolve_seed()`/`resolve_civicplus_seed()`/
   `civicclerk_candidate_event_urls()` all walk that list, trying up to
   `MAX_CANDIDATES_TRIED` real resolves per platform hit until one comes
   back with real video (`segments` or `video_url`) -- not just a
   clean title.
2. **Agenda-only meetings are NOT ingested.** `nationwide_2404_ingest.py`
   POSTed an `ingested_agenda_only` page immediately for a resolve with
   `agenda_items`/`agenda_link` but no video. Ryan's 2026-09-09 standing
   decision (BACKLOG.md, "Video-less meetings are not ingested by
   sweeps") supersedes that: a real, current meeting with no video
   attached is a legitimate recorded outcome (`no_video_found` here,
   `reject_reason=no-video-found` in `jurisdiction_coverage.csv`), not a
   page. This closes BACKLOG.md's matching `[JUST-DO-IT]` entry filed
   the same day (it suggested queuing agenda-only rows to tier 3
   instead -- superseded by the clearer "not ingested at all" rule,
   since tier 3 is specifically for a real video with no reachable
   captions, and an agenda-only meeting has no video at all).
3. **Shared-host pins.** YouTube/Vimeo/TelVue/Cablecast are general-
   purpose video hosts, not per-tenant subdomains -- a page must be keyed
   to its real government, never left as `rtr:unknown`. For every
   tier-1/2 ingest or tier-3 queue add on one of those four hosts, this
   script (a) sets `result.jurisdiction` to a real "Name, ST" display
   string derived straight from the CSV's own `gov_id` via
   `app.utils.gov_registry.registry.government_for_id()` -- exact, since
   every field of a national gov_id is a function of the id -- and (b)
   appends a `tenant_overrides.csv` pin row (`strength=fallback`, never
   `authoritative` -- that's a human-only call, see
   `scripts/apply_pin_worklist.py`) keyed on the shared host plus the
   real per-video discriminator (`resolver.py`'s `_match_override()`:
   video id for YouTube, numeric id for Vimeo, the URL path for TelVue/
   Cablecast). A pin only takes effect for INGESTS AFTER the next
   deploy (`app/utils/gov_registry/registry.py` reads its committed
   CSVs, not this worktree's live edits) -- it does not retroactively
   fix today's own ingest, but it is the durable, exact fix a free-text
   jurisdiction guess is not, and it is there for the next backfill/
   reingest of the same video either way.

Also new, both directly requested by Ryan for this batch specifically
(neither existed in any prior `nationwide_*_ingest.py`):

- **Dedup against a fresh export first.** Before touching any row, this
  script requires an up-to-date
  `python scripts/export_meeting_inventory.py --out-dir ... --source
  export` CSV (HTTP-only, never a DB connection -- see that script's own
  docstring) and marks any row whose `gov_id` already has an archived
  page `already_covered` without ever calling an adapter.
- **A circuit breaker on consecutive real errors.** A content-based
  skip (no video found, unsupported platform, off-mission title, ...)
  is normal signal and does not count. A network/resolve *exception* or
  a twice-failed Archive POST does. `MAX_CONSECUTIVE_ERRORS` consecutive
  ones aborts the run with a clear message rather than grinding through
  a broken run (a DNS outage, an Archive incident) silently logging
  errors for the rest of the batch.

Writes a per-row CSV log to
rtr-business/research/wo134_confirmed_hits_ingest_log.csv (resumable:
rows already present for a given gov_id are skipped on a re-run, exactly
like nationwide_2404_ingest.py's own log). A separate backfill script,
rtr-business/research/backfill_wo134_ingest_into_jc.py (same location/
pattern as backfill_2404_ingest_into_jc.py), folds the outcomes into
`jurisdiction_coverage.csv`, matched on (city_name, state_or_province,
domain) per Ryan's instruction -- not gov_id -- since that's the row
identity `jurisdiction_coverage.csv` itself uses (gov_id is only used to
FIND that identity tuple, via jurisdiction_coverage.csv's own existing
gov_id column, before re-matching on it for the actual write).

Usage (from repo root, venv active, DATABASE_URL set per CLAUDE.md's
worktree .env warning even though this script never touches the DB
directly -- app.platforms imports pull in code that does):
    python scripts/export_meeting_inventory.py --out-dir /tmp/wo134_inventory --source export
    python scripts/wo134_confirmed_hits_ingest.py
    python scripts/wo134_confirmed_hits_ingest.py --limit 10        # smoke test
    # after the run:
    python3 ~/Documents/rtr-business/research/backfill_wo134_ingest_into_jc.py

WO-139 (2026-09-09) update: INPUT_CSVS now reads wo139_confirmed_hits.csv
instead of the raw wo133_confirmed_hits.csv it replaces -- run
`python scripts/wo139_build_input.py` first if that derived file is
missing or stale. See that script's own docstring for why (WO-127
already worked most of wo133_confirmed_hits.csv's CivicPlus AgendaCenter
rows; re-running this general pipeline against those would just repeat
WO-127's own real requests).
"""

import argparse
import asyncio
import csv
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urljoin, urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import (  # noqa: E402
    CIVICPLUS_CORPORATE_HOSTS,
    CalendarPageError,
    UnsupportedPlatformError,
    detect_platform,
    get_finder,
    resolve_via_platform,
)
from app.platforms.civicplus import CivicPlusAssetFinder  # noqa: E402
from app.platforms import granicus_channel  # noqa: E402
from app.platforms import queue_probe  # noqa: E402
from app.platforms.youtube_channel import is_publishable  # noqa: E402
from app.utils.gov_registry.registry import government_for_id  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402
from scripts.bulk_ingest import _base_url, _ingest  # noqa: E402

import yt_dlp  # noqa: E402

RESEARCH_DIR = Path("/Users/mroconnell/Documents/rtr-business/research")
INPUT_CSVS = [
    RESEARCH_DIR / "wo129_confirmed_hits.csv",
    # WO-139: raw wo133_confirmed_hits.csv (503 rows) is superseded here
    # by wo139_confirmed_hits.csv, the same 503 rows minus the 345 that
    # are CivicPlus AgendaCenter tenants WO-127 already worked (see
    # scripts/wo139_build_input.py's docstring for the filter and why
    # re-running this pipeline against those 345 would just repeat
    # WO-127's own real requests against tenants already investigated).
    RESEARCH_DIR / "wo139_confirmed_hits.csv",  # may not exist yet -- see main()
]
LOG_CSV = RESEARCH_DIR / "wo134_confirmed_hits_ingest_log.csv"
TIER3_QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"
TENANT_OVERRIDES_CSV = (
    REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "tenant_overrides.csv"
)
DEFAULT_INVENTORY_CSV = Path("/tmp/wo139_inventory/meeting_inventory.csv")

REQUEST_DELAY_SECONDS = 1.5  # between governments
CANDIDATE_DELAY_SECONDS = 0.75  # between depth-search attempts on the SAME tenant
MAX_CANDIDATES_TRIED = 6  # how deep to search one tenant's listing for a video
MAX_CONSECUTIVE_ERRORS = 6
FETCH_TIMEOUT = aiohttp.ClientTimeout(total=25)
UA_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    )
}

# Same reasoning as nationwide_2404_ingest.py: agenda/document CMSes with
# no video adapter in this repo at all.
UNSUPPORTED_PLATFORMS = {
    "boarddocs",
    "municipalcodeonline",
    "novusagenda",
    "agendasuite",
}

# Shared, general-purpose video hosts -- per Ryan's rule, a page here
# must be keyed to its government explicitly (jurisdiction hint +
# tenant_overrides.csv pin), never left to resolve generically.
SHARED_HOST_PLATFORMS = {"youtube", "vimeo", "telvue", "cablecast"}

MEETING_ALLOWLIST = (
    "council",
    "commission",
    "board",
    "committee",
    "meeting",
    "session",
    "hearing",
    "authority",
    "trustees",
    "supervisors",
    "assembly",
    "selectboard",
    "select board",
    # "Board of County Commissioners" abbreviation -- real, confirmed-live
    # false negative caught in WO-149's own 30-row county pilot
    # (2026-09-10): Tulsa County OK's own YouTube channel titles its real
    # commission meetings "BOCC Livestream - December 1, 2025", which
    # contains neither "board" nor "commission" as a substring and was
    # rejected as off-mission before this was added.
    "bocc",
)
PROMO_BLOCKLIST = (
    "promo",
    "advertisement",
    "commercial",
    "psa",
    "public service announcement",
    "how to",
    "tutorial",
    "instructional",
    "training video",
    "orientation video",
    "welcome",
    "message from the mayor",
    "highlight reel",
    "sizzle reel",
    "ribbon cutting",
    "parade",
    "test stream",
    "test broadcast",
    "sample video",
    "demo video",
    "career",
    "job fair",
    "recruitment",
    "state of the city",
    "year in review",
    "commercial break",
    "tour of",
    # Real, confirmed-live false positive caught by WO-187 (2026-09-11):
    # Capitol Heights, MD's YouTube channel titled a real clip "Council
    # Member Victor James Sr interview for N'style back to school block
    # party" -- "Council" alone satisfies MEETING_ALLOWLIST, and nothing
    # here caught that the video is a promotional interview, not a
    # meeting recording. Ingested live before being caught by hand;
    # flagged for deletion (BACKLOG_DONE.md's WO-187 entry).
    "interview",
)

HOP2_FETCH_CAP = 4
HIGH_RISK_TITLE_PLATFORMS = {"youtube", "vimeo"}

# WO-147/WO-149 hook (2026-09-10, added independently by both same-day
# sweeps for the identical reason): when set, process_row() hands a
# tier-3 (video, no reachable captions) candidate to this callable
# instead of appending it to TIER3_QUEUE_FILE and pinning it
# immediately. Ryan's rule for both sweeps is "probe before queue" -- a
# tier-3 candidate must be probed (duration/dead-link check) before it
# earns a queue line, not at resolve time. None (the default) preserves
# this module's original behavior exactly, so wo134_confirmed_hits_
# ingest.py's own main()/WO-139 callers are unaffected. Signature:
# handler(gov_id, unit_name, platform, final_seed, hit_url, title, date,
# result) -> None. See scripts/wo147_access_ladder_sweep.py and scripts/
# wo149_county_ladder_sweep.py for the two real handlers.
TIER3_HANDLER = None

# WO-149 hook (2026-09-10): a caller can set this to a callable(result,
# gov_id, unit_name, platform, final_seed) -> (ok: bool, note: str) to
# force the exact registry jurisdiction string onto a resolved result
# and reject a hit that plainly names a different government (see
# process_row's call site) -- the county-sharing-a-name-with-an-
# independent-city trap. None preserves the original apply_display_
# jurisdiction-only behavior (fills a blank jurisdiction, never
# overwrites or rejects).
JURISDICTION_CHECK_HOOK = None

# WO-169 hook (2026-09-10): when set, resolve_seed()'s internal candidate
# loops (civicplus, granicus, civicclerk, the generic CalendarPageError
# walk, and the youtube-channel depth search) call this for every
# candidate that resolves with a real video_url but no captions (a
# tier-3 shape) BEFORE accepting it as the row's chosen candidate. This
# closes the real, confirmed gap this WO was filed for: the probe used
# to run once, AFTER a candidate was already committed to (in a separate
# *_finish_tier3*.py pass or inline right after resolve_seed() returned),
# so a `reject-dead`/`reject-short` verdict ended the government's whole
# attempt even when several more candidates from the same listing were
# sitting right there untried -- 16 governments were dropped this way
# across WO-145/147/150/151 (see BACKLOG_DONE.md's WO-169 entry). Returns
# True to accept the candidate, False to reject it and keep searching the
# remaining candidates; only once every candidate (across every platform
# hit on the row) is exhausted does process_row() report
# `rejected_by_probe` -- never before. None (the default) preserves this
# module's original "first candidate with real video wins" behavior
# exactly, so a caller that never sets this hook (the existing
# TIER3_HANDLER-based flow every driver used before WO-169) is
# unaffected. Signature: async hook(result, candidate_url: str) -> bool.
# See scripts/wo169_probe_rejected_rerun.py for the real hook, which
# calls app.platforms.queue_probe.probe_queue_entry() and logs to the
# same append-only sidecar (tier3_auto_transcription_queue_probe.csv)
# every other probe caller already uses.
PROBE_HOOK: Optional[Callable[[object, str], Awaitable[bool]]] = None

# WO-170 hook (2026-09-10): Ryan's rule -- "after it rejects the first
# video, it would be ideal if the probe selected another video and
# actually checked the size of that video file or its duration to
# ensure that it was at least 9 minutes long but not longer than 40
# minutes. It could check several videos this way and if all the videos
# were over 40 minutes, then select the shortest available video in the
# list." When set, this REPLACES PROBE_HOOK's plain accept/reject for
# every tier-3 (video, no captions) candidate resolve_seed()'s candidate
# loops try: instead of returning on the first candidate that merely
# passes the probe, each loop probes every candidate it resolves (still
# capped at MAX_CANDIDATES_TRIED, still newest-first, still
# CANDIDATE_DELAY_SECONDS apart -- no change to the politeness budget),
# stopping early only once it finds a newest-first in-window match (no
# later, older candidate could ever beat that one -- see
# queue_probe.select_best_probe_result()'s own docstring), and hands
# every candidate it did probe to that function once the loop ends.
# Real captions (tier 1/2) still short-circuit immediately without ever
# calling this hook, same as PROBE_HOOK.
#
# Signature: async hook(result, candidate_url: str) ->
# queue_probe.ProbeResult (NOT a bool -- this is what lets the caller
# compare durations across several candidates instead of only knowing
# pass/fail on one). None (the default) preserves the exact WO-169
# behavior for every existing caller, PROBE_HOOK included -- see
# _probe_candidate_for_selection()'s own comment. build_probe_select_hook()
# below is the one real implementation (wired to the shared sidecar);
# this module's own main() and scripts/hub_sweep_wo126.py's main() both
# set it by default so a direct run of either pipeline gets Ryan's rule
# automatically, per BACKLOG_DONE.md's WO-170 entry.
PROBE_SELECT_HOOK: Optional[
    Callable[[object, str], Awaitable["queue_probe.ProbeResult"]]
] = None


def build_probe_select_hook() -> Callable[
    [object, str], Awaitable["queue_probe.ProbeResult"]
]:
    """The one real PROBE_SELECT_HOOK implementation -- calls the real
    WO-144 probe (app.platforms.queue_probe.probe_queue_entry()), same as
    scripts/wo169_probe_rejected_rerun.py's own _real_probe_hook, but
    returns the whole ProbeResult instead of a bool and does NOT write to
    the sidecar itself (see _finish_probe_selection()'s own comment for
    why that write is deferred until the selection among candidates is
    actually made). A single definition, reused by this module's own
    main(), scripts/hub_sweep_wo126.py's main(), and any future driver
    that wants Ryan's selection rule -- not one ad hoc hook per script."""

    async def _hook(result, candidate_url: str) -> "queue_probe.ProbeResult":
        return await queue_probe.probe_queue_entry(
            candidate_url,
            video_url=result.video_url,
            source_page_url=result.source_url or candidate_url,
        )

    return _hook


async def _probe_candidate_for_selection(result, candidate_url: str):
    """Returns a queue_probe.ProbeResult for a tier-3 candidate when
    PROBE_SELECT_HOOK is set, else None -- meaning "no selection hook is
    active, fall back to _candidate_passes_probe's plain accept/reject
    (PROBE_HOOK or the unconditional pre-WO-169 pass)." Never called for
    a candidate with real captions -- every call site below checks
    `result.segments` first, same as _candidate_passes_probe."""
    if PROBE_SELECT_HOOK is None:
        return None
    return await PROBE_SELECT_HOOK(result, candidate_url)


def _finish_probe_selection(probed: List["queue_probe.ProbeResult"]):
    """Given every ProbeResult a candidate loop probed under
    PROBE_SELECT_HOOK (empty if the hook is unset, or if every candidate
    either had real captions or none needed probing), writes each one to
    the shared sidecar CSV exactly once -- marking whichever
    queue_probe.select_best_probe_result() picked as `chosen` -- and
    returns that pick (or None if nothing here was selectable, e.g. every
    candidate was dead or too short). Writing here, once, after the whole
    candidate set is known, is what lets the sidecar show "chose shorter
    alternative": writing inside the hook itself (WO-169's own
    _real_probe_hook did this) would have no way to know the choice yet."""
    if not probed:
        return None
    choice = queue_probe.select_best_probe_result(probed)
    chosen_url = choice.url if choice else None
    for pr in probed:
        pr.chosen = pr.url == chosen_url
        queue_probe.append_probe_row(queue_probe.DEFAULT_SIDECAR_PATH, pr)
    return choice


# WO-152 hook (2026-09-10): when set, process_row() calls this right after
# a hit resolves real video content (segments/agenda/video_url present) and
# BEFORE that content is ingested or queued -- the one point in this
# pipeline where a wrong-government mismatch (WO-145's four confirmed
# collision shapes: state/province mismatch, county-vs-municipality
# keyword, an institution-phrase title naming a different place, a
# same-name Canadian municipality with no state/province code to rule it
# out) can still be caught before anything goes live. Returning a non-empty
# string treats this hit as skipped (the loop below tries the row's next
# hit, same as any other continue); None means no mismatch found. Default
# None preserves this module's original behavior exactly. Signature:
# hook(row, platform, result, final_seed, effective_title) -> Optional[str].
# See scripts/wo152_dead_domain_recheck.py for the real hook.
IDENTITY_CHECK_HOOK = None


@dataclass
class RowResult:
    gov_id: str
    unit_name: str
    platform: str
    outcome: str  # ingested_tier1_2 | queued_tier3 | queued_tier3_pending | rejected_by_probe | no_video_found | already_covered | skipped | error
    reason: str
    seed_url: str = ""
    title: str = ""
    date: str = ""
    page_url: str = ""
    # WO-169: the real video address, when one was found, even on a row
    # that ends up skipped/rejected_by_probe -- appended at the end so
    # every existing positional RowResult(...) call site (9 args) still
    # works unchanged. See RowSkip's own docstring for why this matters:
    # a skip with no video_url meant a real video address was silently
    # lost for the day a listing appears, per WO-151's finding.
    video_url: str = ""


def _read_csv_rows(path: Path) -> List[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _load_covered_gov_ids(inventory_csv: Path) -> set:
    if not inventory_csv.exists():
        print(
            f"ERROR: {inventory_csv} not found. Run this first (HTTP-only, per "
            "CLAUDE.md's production-access rule):\n"
            "  python scripts/export_meeting_inventory.py --out-dir "
            f"{inventory_csv.parent} --source export",
            file=sys.stderr,
        )
        sys.exit(1)
    with inventory_csv.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f) if r.get("gov_id")}


_HIT_SOURCE_PAIR_SPLIT_RE = re.compile(r";(?=[a-z_]+=https?://)")


def _parse_hit_source_urls(raw: str) -> List[Tuple[str, str]]:
    pairs = []
    for chunk in _HIT_SOURCE_PAIR_SPLIT_RE.split(raw or ""):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        platform, _, url = chunk.partition("=")
        platform = platform.strip()
        url = url.strip()
        if platform and url:
            pairs.append((platform, url))
    return pairs


def _already_logged_gov_ids(path: Path) -> set:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {row["gov_id"] for row in csv.DictReader(f)}


def _log_writer(path: Path):
    fields = [
        "gov_id",
        "unit_name",
        "platform",
        "outcome",
        "reason",
        "seed_url",
        "title",
        "date",
        "page_url",
        "video_url",
    ]
    is_new = not path.exists()
    f = path.open("a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=fields)
    if is_new:
        writer.writeheader()
        f.flush()
    return f, writer


async def fetch_html(
    session: aiohttp.ClientSession, url: str
) -> Tuple[Optional[str], Optional[str]]:
    try:
        async with session.get(
            url, headers=UA_HEADERS, timeout=FETCH_TIMEOUT, allow_redirects=True
        ) as resp:
            if resp.status >= 400:
                return None, None
            final_url = str(resp.url)
            html = await resp.text(errors="replace")
            return final_url, html
    except Exception:
        return None, None


_ONCLICK_URL_RE = re.compile(r"""\(\s*['"]([^'"]+)""")
_TAGS = ("a", "iframe", "video", "source")


def find_specific_platform_link(
    html: str, page_url: str, target_platform: str
) -> Optional[str]:
    soup = BeautifulSoup(html, "html.parser")
    page_url_no_frag = urlparse(page_url)._replace(fragment="").geturl()
    for tag in soup.find_all(_TAGS):
        values = []
        href_or_src = tag.get("href") or tag.get("src")
        if href_or_src:
            values.append(href_or_src.strip())
        onclick = tag.get("onclick")
        if onclick:
            m = _ONCLICK_URL_RE.search(onclick)
            if m:
                values.append(m.group(1).strip())
        for value in values:
            if not value:
                continue
            candidate = urljoin(page_url, value)
            if urlparse(candidate)._replace(fragment="").geturl() == page_url_no_frag:
                continue
            if urlparse(candidate).netloc.lower() in CIVICPLUS_CORPORATE_HOSTS:
                # Explicit skip, same as base.py's own find_platform_link()
                # -- CivicPlus's own corporate/marketing hosts (e.g. every
                # tenant's "Government Websites by CivicPlus" footer
                # credit) are never a real per-government destination.
                # See CIVICPLUS_CORPORATE_HOSTS' own docstring in
                # app/platforms/base.py (WO-162, 2026-09-10) for the real
                # bug this closes -- Temple City, CA was recorded
                # `no-video-found` because this scan picked the footer
                # link before it ever fixed this.
                continue
            if detect_platform(candidate) == target_platform:
                return candidate
    return None


_YT_ID_RE = re.compile(r"(?:v=|/embed/|/live/|youtu\.be/)([A-Za-z0-9_-]{11})")


async def youtube_oembed_title(
    session: aiohttp.ClientSession, video_url: str
) -> Optional[str]:
    m = _YT_ID_RE.search(video_url)
    if not m:
        return None
    video_id = m.group(1)
    try:
        async with session.get(
            "https://www.youtube.com/oembed",
            params={
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "format": "json",
            },
            headers=UA_HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                return None
            data = await resp.json(content_type=None)
            return data.get("title")
    except Exception:
        return None


def _contains_word(text: str, phrase: str) -> bool:
    """Word-boundary match, not a bare substring test. Real, confirmed-
    live false positive caught in WO-149's own county sweep (2026-09-10):
    a plain `"board" in title` check passed "Larry J. Dix Boardroom" --
    a YouTube channel's persistent room-name livestream title, not a
    meeting -- straight through to a live 59-second Archive page. Every
    other MEETING_ALLOWLIST/PROMO_BLOCKLIST entry is a real word or
    phrase too, so this closes the same class of bug for all of them,
    not just "board"."""
    return re.search(r"\b" + re.escape(phrase) + r"\b", text) is not None


def _looks_like_real_meeting(title: str, *, require_allowlist: bool = False) -> bool:
    t = (title or "").lower()
    if any(_contains_word(t, b) for b in PROMO_BLOCKLIST):
        return False
    if require_allowlist and not any(_contains_word(t, kw) for kw in MEETING_ALLOWLIST):
        return False
    return True


def _parse_candidate_date(date_str: str) -> Optional[datetime]:
    if not date_str:
        return None
    date_str = date_str.strip()
    for fmt in ("%Y-%m-%d", "%b %d, %Y", "%B %d, %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(
                date_str[:10] if fmt == "%Y-%m-%d" else date_str, fmt
            )
        except ValueError:
            continue
    return None


def pick_calendar_candidates(
    candidates: List[dict], limit: int = MAX_CANDIDATES_TRIED
) -> List[dict]:
    """Like nationwide_2404_ingest.py's pick_calendar_candidate(), but
    returns an ORDERED LIST of up to `limit` title-clean candidates
    (most recent first) instead of a single pick -- this is the "go deep
    enough to find a meeting with video, not just the newest one" change
    Ryan asked for. The caller resolves each in turn and keeps the first
    with real video; a tenant whose newest meeting has no video but
    whose 3rd-most-recent does is exactly the case this exists for.

    Same "decline rather than guess" behavior when nothing recent looks
    like a real meeting: returns an empty list plus a reason, not a
    forced pick.
    """
    if not candidates:
        return [], "no candidates"

    today = datetime.now(timezone.utc).replace(tzinfo=None)
    dated = []
    for c in candidates:
        dt = _parse_candidate_date(c.get("date") or "")
        if dt is not None and dt <= today:
            dated.append((dt, c))
    dated.sort(key=lambda pair: pair[0], reverse=True)

    picked = [c for _, c in dated if _looks_like_real_meeting(c.get("title") or "")]
    if picked:
        return picked[:limit], ""

    # No dated candidate looked clean. A single real per-meeting agenda
    # row (unparseable date) still gets one try if its title is clean --
    # same carve-out as the original single-pick version.
    if len(candidates) == 1 and _looks_like_real_meeting(
        candidates[0].get("title") or ""
    ):
        return [candidates[0]], ""

    top_titles = [c.get("title") for c in (dated[:5] or candidates[:5])]
    return [], f"ambiguous: no clean recent candidate among {top_titles!r}"


def _has_video(result) -> bool:
    return bool(result.segments or result.video_url)


async def _candidate_passes_probe(result, candidate_url: str) -> bool:
    """True when a video-bearing candidate should be accepted as the
    row's chosen one. Real captions (tier 1/2, `result.segments`) always
    pass -- WO-144's queue probe exists specifically to vet a tier-3
    (video, no captions) candidate before it reaches the queue, so a
    caption-bearing result never needs it. A tier-3 candidate passes when
    PROBE_HOOK accepts it, or unconditionally when no hook is set --
    preserving this module's pre-WO-169 behavior for any caller that
    hasn't opted in yet. See PROBE_HOOK's own comment for the full
    reasoning."""
    if result.segments:
        return True
    if not result.video_url:
        return False
    if PROBE_HOOK is None:
        return True
    return await PROBE_HOOK(result, candidate_url)


async def civicclerk_candidate_event_urls(
    session: aiohttp.ClientSession, tenant_url: str, limit: int = MAX_CANDIDATES_TRIED
) -> Tuple[List[Tuple[str, dict]], str]:
    """Like nationwide_2404_ingest.py's civicclerk_latest_event_url(),
    but returns an ORDERED LIST of up to `limit` (event_url, event) pairs
    (newest past real-media event first) instead of just the top one --
    same depth-search reasoning as pick_calendar_candidates(). A CivicClerk
    event's own `hasMedia`-family flags are a real signal but not a
    guarantee the media actually resolves (an expired/broken
    mediaStreamPath is a live, confirmed failure mode elsewhere in this
    codebase) -- trying several lets a broken newest event fall through
    to a working older one instead of dead-ending the whole tenant.
    """
    subdomain = urlparse(tenant_url).netloc.split(".")[0]
    api_base = f"https://{subdomain}.api.civicclerk.com/v1"
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    filtered = f"{api_base}/Events?$filter=startDateTime lt {now_iso}&$orderby=startDateTime desc&$top=25"
    plain = f"{api_base}/Events?$orderby=startDateTime desc&$top=25"
    try:
        async with session.get(
            filtered, headers=UA_HEADERS, timeout=FETCH_TIMEOUT
        ) as resp:
            if resp.status >= 400:
                async with session.get(
                    plain, headers=UA_HEADERS, timeout=FETCH_TIMEOUT
                ) as resp2:
                    resp2.raise_for_status()
                    payload = await resp2.json(content_type=None)
            else:
                payload = await resp.json(content_type=None)
    except Exception as e:
        return [], f"civicclerk Events API failed: {e}"

    events = payload.get("value") if isinstance(payload, dict) else payload
    events = events or []
    real = []
    for ev in events:
        if ev.get("isDeleted"):
            continue
        has_media = (
            ev.get("hasMedia")
            or ev.get("mediaStreamPath")
            or ev.get("mediaSourcePathMp4")
            or ev.get("externalMediaUrl")
        )
        if not has_media:
            continue
        start = ev.get("startDateTime") or ev.get("eventDate") or ""
        if not start or start >= now_iso:
            continue
        title = ev.get("eventName") or ""
        if not _looks_like_real_meeting(title):
            continue
        event_id = ev.get("id")
        if event_id is None:
            continue
        real.append((start, ev))
    if not real:
        return (
            [],
            "no past CivicClerk events with real media found via tenant Events API",
        )
    real.sort(key=lambda pair: pair[0], reverse=True)
    out = []
    for _, ev in real[:limit]:
        out.append(
            (f"https://{subdomain}.portal.civicclerk.com/event/{ev['id']}/media", ev)
        )
    return out, ""


def civicplus_seed_urls(hit_url: str, hop2_urls: List[str], homepage: str) -> List[str]:
    """Real, confirmed-live gap found running this pipeline 2026-09-09
    (Peachtree City, GA): the CSV's own `homepage` field (from a census-
    derived guess, "peachtreecityga.gov") can be a different, non-live
    domain from the one the government's real site actually uses
    ("peachtree-city.org", confirmed live via curl to hold a real
    `/AgendaCenter` with a populated `catAgendaRow` table) -- guessing
    `/AgendaCenter` only off `homepage` silently missed a real, reachable
    install. Guessing off `hit_url`'s own domain too fixes this without
    needing the CSV's `homepage` field to be right."""
    seeds = []
    if "agendacenter" in hit_url.lower():
        seeds.append(hit_url)
    for u in hop2_urls:
        if "agendacenter" in u.lower() and u not in seeds:
            seeds.append(u)
    if hit_url not in seeds:
        seeds.append(hit_url)
    hit_base = urlparse(hit_url)
    if hit_base.netloc:
        hit_root = f"{hit_base.scheme or 'https'}://{hit_base.netloc}"
        for guess in (f"{hit_root}/AgendaCenter", f"{hit_root}/agendacenter"):
            if guess not in seeds:
                seeds.append(guess)
    base = homepage.rstrip("/")
    for guess in (f"{base}/AgendaCenter", f"{base}/agendacenter"):
        if guess not in seeds:
            seeds.append(guess)
    return seeds


_GRANICUS_ROW_DATE_RE = re.compile(r"\bon (\d{4}-\d{2}-\d{2})\b")


def granicus_candidate_rows(html: str, final_url: str) -> List[dict]:
    """Real, confirmed-live gap found running this pipeline 2026-09-09:
    a two-hop scan's own `hit_source_url` for a Granicus tenant is often
    just an `/account/login?ReturnUrl=/` link (whatever the crawl
    happened to land on), which resolve()s to nothing (no clip_id at
    all) -- granicus.py itself never raises CalendarPageError the way
    civicplus.py/legistar.py/vimeo.py do, since it has no notion of a
    listing page. `ViewPublisher.php?view_id=N` (confirmed live,
    Harrisonburg VA: view_id=2 held a real 505-row meeting table,
    view_id=1 was empty) is the tenant's real per-body meeting listing;
    this parses its `tr.even`/`tr.odd` rows (each holding an
    `AgendaViewer.php?view_id=X&clip_id=Y` link on a real title/date
    like "City Council on 2026-09-08 7:00 PM ...") into the same
    {title, date, url} candidate shape pick_calendar_candidates() already
    expects from a CalendarPageError -- lets Granicus reuse that same
    depth-search rather than needing its own."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for row in soup.find_all("tr", class_=["even", "odd"]):
        a = row.find("a", href=True)
        href = a["href"] if a else ""
        if "AgendaViewer.php" not in href and "MediaPlayer.php" not in href:
            continue
        text = row.get_text(" ", strip=True)
        m = _GRANICUS_ROW_DATE_RE.search(text)
        date = m.group(1) if m else ""
        title = text.split(" on " + date)[0].strip() if date else text[:120]
        # Real, confirmed-live bug (WO-134, 2026-09-09): granicus.py's
        # _fetch_page() raises UnicodeDecodeError on a real
        # AgendaViewer.php response (Harrisonburg VA clip_id=1369) --
        # `.text()` with no error handling can't decode a byte on that
        # page. MediaPlayer.php?view_id=X&clip_id=Y (confirmed live to
        # work on the SAME clip) is the adapter's own documented
        # canonical entrypoint (_fetch_page's docstring: "how Granicus's
        # own UI shares links"), so swap the query string over rather
        # than resolving the row's own AgendaViewer.php href directly.
        candidate_url = urljoin(final_url, href).replace(
            "AgendaViewer.php", "MediaPlayer.php"
        )
        out.append({"title": title, "date": date, "url": candidate_url})
    return out


# WO-157's pilot (docs/BREADTH_SWEEP_BRIEF.md,
# ~/Documents/rtr-business/research/ENUMERATION_METHODS.md §191): a
# Granicus tenant's own ViewPublisherRSS.php?view_id=N&mode=video feed
# lists every archived clip, newest first, in about 100 KB -- against up
# to 8 MB for the ViewPublisher.php archive table this module used to
# fetch on every candidate search. "(No Video)" titles are closed-session
# placeholders (confirmed live, same pilot), never a real candidate.
_GRANICUS_NO_VIDEO_TITLE_RE = re.compile(r"\(no video\)", re.I)


def granicus_rss_candidate_rows(xml: str, base_url: str) -> List[dict]:
    """Parses a Granicus ViewPublisherRSS.php?mode=video feed into the
    same {title, date, url} candidate shape granicus_candidate_rows()
    already returns from the (up to 8 MB) ViewPublisher.php archive
    table, so both feed pick_calendar_candidates() identically. Reuses
    app/platforms/granicus_channel.py's own RSS <item> parsing
    (_ITEM_RE/_item_body_and_clip_url/_item_local_date) -- the same real,
    already-tested regex set legistar.py's own Granicus delegation
    already depends on -- rather than a second parser that could drift
    from it (CLAUDE.md's WO-34 roll-up-caption note: reuse the shared
    parser, don't reimplement it per caller). The RSS <link> is passed
    through UNMODIFIED, matching legistar.py's own
    find_view_publisher_match() usage: granicus.py's own
    _extract_clip_id() already understands every real link shape this
    feed uses, so no AgendaViewer.php->MediaPlayer.php rewrite is needed
    here the way the HTML table's own links need (see
    granicus_candidate_rows()'s docstring for that one).

    Sorted newest-first by the feed's own structured
    <gran:pubDateParts> date, not raw feed order -- WO-157's own pilot
    found one of 12 tenants' feed order lagged its true newest clip by
    12 days."""
    out = []
    for m in granicus_channel._ITEM_RE.finditer(xml):
        item_xml = m.group(1)
        parsed = granicus_channel._item_body_and_clip_url(item_xml)
        if not parsed:
            continue
        body, clip_url = parsed
        if _GRANICUS_NO_VIDEO_TITLE_RE.search(body):
            continue
        date = granicus_channel._item_local_date(item_xml) or ""
        # urljoin() is a no-op on the real, already-absolute link every
        # confirmed feed has used so far (a bare urljoin(base, absolute)
        # returns the absolute URL unchanged) -- kept as a defensive join
        # rather than a bare pass-through in case a tenant's feed ever
        # emits a relative <link>, not yet confirmed live either way.
        out.append({"title": body, "date": date, "url": urljoin(base_url, clip_url)})
    out.sort(key=lambda c: c["date"] or "", reverse=True)
    return out


async def granicus_fetch_rss_candidates(
    session: aiohttp.ClientSession, netloc: str, view_id: str
) -> List[dict]:
    """The cheap (~100 KB) RSS-first check -- see granicus_rss_candidate_
    rows()'s own docstring. Returns [] on any failure (unreachable feed,
    no real <item>s, every item "(No Video)") -- never an error; callers
    fall back to the ViewPublisher.php table walk exactly as before this
    WO."""
    rss_url = f"https://{netloc}/ViewPublisherRSS.php?view_id={view_id}&mode=video"
    final_url, xml = await fetch_html(session, rss_url)
    if not xml or "<item>" not in xml:
        return []
    return granicus_rss_candidate_rows(xml, final_url or rss_url)


async def granicus_locate_listing(
    session: aiohttp.ClientSession, hit_url: str
) -> Tuple[Optional[str], str]:
    if (
        "clip_id=" in hit_url
        or "AgendaViewer.php" in hit_url
        or "MediaPlayer.php" in hit_url
    ):
        return hit_url, ""
    domain = urlparse(hit_url).netloc
    if not domain:
        return None, "no domain to guess a ViewPublisher.php listing from"
    for view_id in range(1, 6):
        seed = f"https://{domain}/ViewPublisher.php?view_id={view_id}"
        # WO-169: RSS first, cheap -- see granicus_fetch_rss_candidates()'s
        # own docstring. A real, non-"(No Video)"-only feed at this
        # view_id means it's populated; skip straight past the expensive
        # HTML-table check below for it.
        rss_rows = await granicus_fetch_rss_candidates(session, domain, str(view_id))
        if rss_rows:
            return seed, ""
        final_url, html = await fetch_html(session, seed)
        if html and "AgendaViewer.php" in html:
            return seed, ""
        await asyncio.sleep(0.3)
    return None, f"no populated ViewPublisher.php?view_id=1..5 found on {domain}"


async def locate_platform_url(
    session: aiohttp.ClientSession,
    platform: str,
    hit_url: str,
    hop2_urls: List[str],
    homepage: str,
) -> Tuple[Optional[str], str]:
    if platform == "granicus":
        seed, _reason = await granicus_locate_listing(session, hit_url)
        if seed:
            return seed, ""
        # Fall back to the original hit_url -- same as before this fix,
        # not worse -- rather than giving up outright when no listing
        # could be found by guessing.
        return hit_url, ""

    if platform == "civicplus":
        for seed in civicplus_seed_urls(hit_url, hop2_urls, homepage):
            final_url, html = await fetch_html(session, seed)
            if html is None:
                continue
            if (
                "civicplus.com" in urlparse(final_url).netloc.lower()
                or "catAgendaRow" in html
            ):
                return seed, ""
        return (
            None,
            "no reachable AgendaCenter page found (hit_url, hop2_urls, or /AgendaCenter guess)",
        )

    if detect_platform(hit_url) == platform:
        return hit_url, ""

    final_url, html = await fetch_html(session, hit_url)
    if html:
        link = find_specific_platform_link(html, final_url or hit_url, platform)
        if link:
            return link, ""

    for u in hop2_urls[:HOP2_FETCH_CAP]:
        if detect_platform(u) == platform:
            return u, ""
        final_url2, html2 = await fetch_html(session, u)
        if not html2:
            continue
        link = find_specific_platform_link(html2, final_url2 or u, platform)
        if link:
            return link, ""

    return (
        None,
        f"no {platform} link found on hit_source_url or first {HOP2_FETCH_CAP} hop2_urls",
    )


_YT_CHANNEL_URL_RE = re.compile(
    r"youtube\.com/(channel/[A-Za-z0-9_-]+|@[A-Za-z0-9_.-]+|c/[A-Za-z0-9_.-]+|user/[A-Za-z0-9_.-]+)"
)
_YT_PLAYLIST_RE = re.compile(r"[?&]list=|/playlist\b")
_YT_NOT_FOUND_VIDEO_ID = "Could not find a YouTube video ID"


def _is_youtube_channel_url(url: str) -> bool:
    """A `find_specific_platform_link()` hit that's a bare channel/handle
    link or a playlist, not a single video -- real, confirmed-live case
    (South Euclid, OH, WO-134 smoke test 2026-09-09):
    get_finder("youtube").resolve() raises a plain ValueError on one of
    these ("Could not find a YouTube video ID"), since that adapter only
    ever handles a single video. Routing this shape to a channel-listing
    depth search instead (below) is the same "go deep enough to find a
    meeting with video" rule applied to the one platform whose government
    page commonly links to a whole channel/playlist rather than one
    specific meeting.

    This regex is a fast-path guess, not the only detector -- a legacy
    vanity URL (`youtube.com/OFallonTV`, no `/channel/`, `/@`, `/c/`, or
    `/user/` prefix; real example, O'Fallon MO, same session) doesn't
    match any of these shapes at all. `resolve_seed()`'s own except
    clause on `_YT_NOT_FOUND_VIDEO_ID` is the real, exhaustive fallback
    for that case and any other shape this regex doesn't anticipate;
    this function only saves a wasted resolve() call for the common
    cases it does recognize."""
    if "/watch" in url:
        return False
    return bool(_YT_CHANNEL_URL_RE.search(url)) or bool(_YT_PLAYLIST_RE.search(url))


def _list_youtube_channel_entries(channel_url: str) -> List[dict]:
    """Flat listing of a channel's/playlist's most recent videos -- same
    yt-dlp technique and anti-block player_client list as
    app/platforms/youtube_channel.py's own _list_channel_tab(), but
    parameterized on the raw URL (handles /@handle, /c/, /user/,
    /channel/, a legacy vanity URL, and a playlist URL directly, since
    yt-dlp resolves all of them) and capped at a small playlistend --
    this only ever needs the top MAX_CANDIDATES_TRIED-ish entries, not
    the full-channel materialize _LISTING_LIMIT=400 that matcher needs
    for a title/date match against an already-known meeting. Blocking;
    called via asyncio.to_thread()."""
    base = channel_url.rstrip("/")
    is_playlist = bool(_YT_PLAYLIST_RE.search(channel_url))
    # A playlist URL is already the listing itself -- appending /videos
    # or /streams to it would be wrong. A channel/handle/vanity URL isn't
    # a listing on its own, so try both real tabs.
    candidate_urls = (
        [channel_url] if is_playlist else [f"{base}/videos", f"{base}/streams"]
    )
    for url in candidate_urls:
        ydl_opts = {
            "skip_download": True,
            "quiet": True,
            "no_warnings": True,
            "extract_flat": "in_playlist",
            "playlistend": 15,
            "extractor_args": {
                "youtube": {"player_client": ["android", "ios", "tv", "web"]}
            },
            "ignoreerrors": True,
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
            entries = [
                e for e in (info or {}).get("entries") or [] if e and e.get("id")
            ]
        except Exception:
            entries = []
        if entries:
            return entries
    return []


async def resolve_youtube_channel(session: aiohttp.ClientSession, channel_url: str):
    """Depth-searches a bare YouTube channel/handle link for the most
    recent real meeting video, up to MAX_CANDIDATES_TRIED tries. Requires
    the allowlist-required title check (same HIGH_RISK_TITLE_PLATFORMS
    reasoning as a single-video resolve, since a channel listing carries
    no inherent "this is a meeting" guarantee either) -- applied here,
    before ever calling the real adapter, so a channel of parade/promo
    uploads doesn't burn resolve calls on obviously-wrong entries."""
    entries = await asyncio.to_thread(_list_youtube_channel_entries, channel_url)
    candidates = [
        e
        for e in entries
        if is_publishable(e)
        and _looks_like_real_meeting(e.get("title") or "", require_allowlist=True)
    ][:MAX_CANDIDATES_TRIED]
    if not candidates:
        raise RowSkip(
            f"youtube channel: {len(entries)} video(s) listed, none looked like a "
            f"real meeting ({channel_url})",
            meeting_url=channel_url,
        )
    finder = get_finder("youtube")
    best_no_video = None
    probe_rejected = None  # (result, video_url) -- WO-169, see PROBE_HOOK
    probed: List["queue_probe.ProbeResult"] = []  # WO-170
    selected_results: Dict[str, object] = {}  # WO-170: url -> result
    for i, entry in enumerate(candidates):
        if i:
            await asyncio.sleep(CANDIDATE_DELAY_SECONDS)
        video_url = f"https://www.youtube.com/watch?v={entry['id']}"
        try:
            result = await finder.resolve(video_url)
        except Exception:
            continue
        if _has_video(result):
            if result.segments:
                return result, video_url, False
            probe_result = await _probe_candidate_for_selection(result, video_url)
            if probe_result is not None:
                selected_results[video_url] = result
                probe_result.url = video_url
                probed.append(probe_result)
                if (
                    probe_result.duration_seconds is not None
                    and queue_probe.IN_WINDOW_MIN_SECONDS
                    <= probe_result.duration_seconds
                    <= queue_probe.IN_WINDOW_MAX_SECONDS
                ):
                    break  # newest-first in-window match -- see PROBE_SELECT_HOOK
                continue
            if await _candidate_passes_probe(result, video_url):
                return result, video_url, False
            if probe_rejected is None:
                probe_rejected = (result, video_url)
            continue
        if best_no_video is None and (result.agenda_items or result.agenda_link):
            best_no_video = (result, video_url, False)
    choice = _finish_probe_selection(probed)
    if choice:
        chosen_url = choice.url
        return selected_results[chosen_url], chosen_url, False
    if best_no_video:
        return best_no_video
    if probed:
        rejected_url = probed[-1].url
        raise ProbeRejected(
            f"youtube channel: checked {len(probed)} tier-3 candidate(s), all failed "
            f"WO-144's probe or exceeded the plausible window",
            meeting_url=rejected_url,
            video_url=selected_results[rejected_url].video_url or rejected_url,
        )
    if probe_rejected:
        result, video_url = probe_rejected
        raise ProbeRejected(
            f"youtube channel: checked {len(candidates)} real-looking video(s), the "
            f"best one failed WO-144's queue probe ({video_url})",
            meeting_url=video_url,
            video_url=result.video_url or video_url,
        )
    raise RowSkip(
        f"youtube channel: checked {len(candidates)} real-looking video(s), none had video",
        meeting_url=channel_url,
    )


class RowSkip(Exception):
    """Raised internally to short-circuit a row to a content-based skip
    (no video found within the depth budget, ambiguous listing, ...) --
    NOT a network/resolve error, so this does not trip the consecutive-
    error circuit breaker. See RowError below for that.

    `meeting_url`/`video_url` (WO-169, both default "" -- backward
    compatible with every existing single-positional-arg raise site) let
    process_row() carry real URL evidence onto a skipped RowResult
    instead of dropping it, the exact gap WO-151 found: a skip with no
    URLs meant a real, current listing or a real video address could
    never be told apart from "found absolutely nothing" once it reached
    a report."""

    def __init__(self, message: str, *, meeting_url: str = "", video_url: str = ""):
        self.meeting_url = meeting_url
        self.video_url = video_url
        super().__init__(message)


class ProbeRejected(RowSkip):
    """Raised when every video-bearing candidate resolve_seed() tried for
    this platform hit failed WO-144's queue probe (dead link, or below
    the meeting-plausibility floor) -- a REAL video existed here, unlike
    a plain RowSkip's "nothing at all found." process_row() catches this
    ahead of the plain RowSkip case (it's a subclass, so the more
    specific except clause must come first) and, once every supported
    platform hit on the row is exhausted with no accepted video, reports
    a distinct `rejected_by_probe` outcome rather than folding it into
    the generic `no_video_found` -- Ryan's 2026-09-10 rule: "a probe
    reject must move to the next candidate, not drop the government,"
    and the next candidate is exactly what this lets resolve_seed() try,
    since raising this (instead of just returning) keeps every enclosing
    candidate loop's `continue` in play."""


class RowError(Exception):
    """Raised internally for a real error (resolve exception, Archive
    POST failure) -- DOES count toward MAX_CONSECUTIVE_ERRORS."""


async def resolve_civicplus_seed(session: aiohttp.ClientSession, seed_url: str):
    """Same domain-gate bypass as nationwide_2404_ingest.py's
    resolve_civicplus_seed(), extended to try up to MAX_CANDIDATES_TRIED
    candidate rows (not just the single best-titled one) until one
    resolves with real video."""
    finder = CivicPlusAssetFinder()
    async with aiohttp.ClientSession(headers=finder.headers) as s:
        async with s.get(
            seed_url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            response.raise_for_status()
            final_url = str(response.url)
            html = await response.text()

    subdomain_jurisdiction = finder._jurisdiction_from_subdomain(seed_url)
    soup = BeautifulSoup(html, "html.parser")
    all_candidates = finder._find_candidate_rows(soup, final_url)
    candidates = [c for c in all_candidates if c["url"]]
    if not candidates:
        raise RowSkip(
            "civicplus: no video-bearing rows found on this AgendaCenter page "
            f"(checked {len(all_candidates)} real candidate(s))",
            meeting_url=seed_url,
        )

    if len(candidates) == 1:
        tried = [candidates[0]]
    else:
        tried, reason = pick_calendar_candidates(candidates)
        if not tried:
            raise RowSkip(
                f"civicplus CalendarPageError, {reason}", meeting_url=seed_url
            )

    best_no_video = None
    probe_rejected = None  # (result, url) -- WO-169, see PROBE_HOOK
    probed: List["queue_probe.ProbeResult"] = []  # WO-170
    selected_results: Dict[str, object] = {}  # WO-170: url -> result
    for i, picked in enumerate(tried):
        if i:
            await asyncio.sleep(CANDIDATE_DELAY_SECONDS)
        try:
            result = await resolve_via_platform(picked["url"])
        except Exception:
            continue
        if subdomain_jurisdiction:
            result.jurisdiction = subdomain_jurisdiction
        result.agenda_link = result.agenda_link or picked.get("agenda_link")
        result.packet_link = result.packet_link or picked.get("packet_link")
        if (
            not result.title
            and picked.get("title")
            and picked["title"] != "Untitled meeting"
        ):
            result.title = picked["title"]
        if not result.date and picked.get("date"):
            result.date = picked["date"]
        if _has_video(result):
            if result.segments:
                return result, picked["url"]
            probe_result = await _probe_candidate_for_selection(result, picked["url"])
            if probe_result is not None:
                selected_results[picked["url"]] = result
                probe_result.url = picked["url"]
                probed.append(probe_result)
                if (
                    probe_result.duration_seconds is not None
                    and queue_probe.IN_WINDOW_MIN_SECONDS
                    <= probe_result.duration_seconds
                    <= queue_probe.IN_WINDOW_MAX_SECONDS
                ):
                    break
                continue
            if await _candidate_passes_probe(result, picked["url"]):
                return result, picked["url"]
            if probe_rejected is None:
                probe_rejected = (result, picked["url"])
            continue
        if best_no_video is None and (result.agenda_items or result.agenda_link):
            best_no_video = (result, picked["url"])

    choice = _finish_probe_selection(probed)
    if choice:
        chosen_url = choice.url
        return selected_results[chosen_url], chosen_url
    if best_no_video:
        return best_no_video
    if probed:
        rejected_url = probed[-1].url
        raise ProbeRejected(
            f"civicplus: checked {len(probed)} tier-3 candidate(s), all failed "
            f"WO-144's probe or exceeded the plausible window",
            meeting_url=rejected_url,
            video_url=selected_results[rejected_url].video_url or "",
        )
    if probe_rejected:
        result, url = probe_rejected
        raise ProbeRejected(
            f"civicplus: checked {len(tried)} candidate(s), the best video-bearing "
            f"one failed WO-144's queue probe ({url})",
            meeting_url=url,
            video_url=result.video_url or "",
        )
    raise RowSkip(
        f"civicplus: checked {len(tried)} candidate(s), no video and no agenda content",
        meeting_url=seed_url,
    )


async def resolve_seed(session: aiohttp.ClientSession, platform: str, seed_url: str):
    """Returns (ResolvedMeeting, final_seed_url_used, high_risk_title).
    Depth-searches up to MAX_CANDIDATES_TRIED candidates for platforms
    that raise CalendarPageError or CivicClerk's tenant-listing split,
    keeping the first with real video and falling back to the best
    agenda-only resolve (so the caller can still record a real
    `no_video_found`, never a guess) if none have video."""
    if platform == "civicplus":
        result, final_seed = await resolve_civicplus_seed(session, seed_url)
        return result, final_seed, False

    if platform == "youtube" and _is_youtube_channel_url(seed_url):
        return await resolve_youtube_channel(session, seed_url)

    if platform == "granicus" and "ViewPublisher.php" in seed_url:
        # WO-169: RSS first (~100 KB), falling back to the ViewPublisher.php
        # archive table (up to 8 MB) only when the feed has nothing --
        # see granicus_fetch_rss_candidates()'s own docstring.
        seed_parsed = urlparse(seed_url)
        view_id = (parse_qs(seed_parsed.query).get("view_id") or [None])[0]
        rows = (
            await granicus_fetch_rss_candidates(session, seed_parsed.netloc, view_id)
            if view_id
            else []
        )
        if not rows:
            final_url, html = await fetch_html(session, seed_url)
            if not html:
                raise RowSkip(
                    f"granicus: ViewPublisher.php listing unreachable ({seed_url})",
                    meeting_url=seed_url,
                )
            rows = granicus_candidate_rows(html, final_url or seed_url)
        tried, reason = pick_calendar_candidates(rows)
        if not tried:
            raise RowSkip(f"granicus listing, {reason}", meeting_url=seed_url)
        finder = get_finder(platform)
        best_no_video = None
        probe_rejected = None  # (result, url) -- WO-169, see PROBE_HOOK
        probed: List["queue_probe.ProbeResult"] = []  # WO-170
        selected_results: Dict[str, object] = {}  # WO-170: url -> result
        for i, picked in enumerate(tried):
            if i:
                await asyncio.sleep(CANDIDATE_DELAY_SECONDS)
            try:
                result = await finder.resolve(picked["url"])
            except Exception:
                continue
            if _has_video(result):
                if result.segments:
                    return result, picked["url"], False
                probe_result = await _probe_candidate_for_selection(
                    result, picked["url"]
                )
                if probe_result is not None:
                    selected_results[picked["url"]] = result
                    probe_result.url = picked["url"]
                    probed.append(probe_result)
                    if (
                        probe_result.duration_seconds is not None
                        and queue_probe.IN_WINDOW_MIN_SECONDS
                        <= probe_result.duration_seconds
                        <= queue_probe.IN_WINDOW_MAX_SECONDS
                    ):
                        break
                    continue
                if await _candidate_passes_probe(result, picked["url"]):
                    return result, picked["url"], False
                if probe_rejected is None:
                    probe_rejected = (result, picked["url"])
                continue
            if best_no_video is None and (result.agenda_items or result.agenda_link):
                best_no_video = (result, picked["url"], False)
        choice = _finish_probe_selection(probed)
        if choice:
            chosen_url = choice.url
            return selected_results[chosen_url], chosen_url, False
        if best_no_video:
            return best_no_video
        if probed:
            rejected_url = probed[-1].url
            raise ProbeRejected(
                f"granicus: checked {len(probed)} tier-3 candidate(s) from "
                f"ViewPublisher.php, all failed WO-144's probe or exceeded the "
                f"plausible window",
                meeting_url=rejected_url,
                video_url=selected_results[rejected_url].video_url or "",
            )
        if probe_rejected:
            result, url = probe_rejected
            raise ProbeRejected(
                f"granicus: checked {len(tried)} candidate(s) from ViewPublisher.php, "
                f"the best video-bearing one failed WO-144's queue probe ({url})",
                meeting_url=url,
                video_url=result.video_url or "",
            )
        raise RowSkip(
            f"granicus: checked {len(tried)} candidate(s) from ViewPublisher.php, none had video",
            meeting_url=seed_url,
        )

    if platform == "civicclerk" and "/event/" not in urlparse(seed_url).path:
        candidates, reason = await civicclerk_candidate_event_urls(session, seed_url)
        if not candidates:
            raise RowSkip(
                reason or "civicclerk: no resolvable event", meeting_url=seed_url
            )
        finder = get_finder(platform)
        best_no_video = None
        probe_rejected = None  # (result, url) -- WO-169, see PROBE_HOOK
        probed: List["queue_probe.ProbeResult"] = []  # WO-170
        selected_results: Dict[str, object] = {}  # WO-170: url -> result
        for i, (event_url, ev) in enumerate(candidates):
            if i:
                await asyncio.sleep(CANDIDATE_DELAY_SECONDS)
            try:
                result = await finder.resolve(event_url)
            except Exception:
                continue
            if _has_video(result):
                if result.segments:
                    return result, event_url, False
                probe_result = await _probe_candidate_for_selection(result, event_url)
                if probe_result is not None:
                    selected_results[event_url] = result
                    probe_result.url = event_url
                    probed.append(probe_result)
                    if (
                        probe_result.duration_seconds is not None
                        and queue_probe.IN_WINDOW_MIN_SECONDS
                        <= probe_result.duration_seconds
                        <= queue_probe.IN_WINDOW_MAX_SECONDS
                    ):
                        break
                    continue
                if await _candidate_passes_probe(result, event_url):
                    return result, event_url, False
                if probe_rejected is None:
                    probe_rejected = (result, event_url)
                continue
            if best_no_video is None and (result.agenda_items or result.agenda_link):
                best_no_video = (result, event_url, False)
        choice = _finish_probe_selection(probed)
        if choice:
            chosen_url = choice.url
            return selected_results[chosen_url], chosen_url, False
        if best_no_video:
            return best_no_video
        if probed:
            rejected_url = probed[-1].url
            raise ProbeRejected(
                f"civicclerk: checked {len(probed)} tier-3 candidate(s), all failed "
                f"WO-144's probe or exceeded the plausible window",
                meeting_url=rejected_url,
                video_url=selected_results[rejected_url].video_url or "",
            )
        if probe_rejected:
            result, url = probe_rejected
            raise ProbeRejected(
                f"civicclerk: checked {len(candidates)} past event(s) with hasMedia "
                f"set, the best video-bearing one failed WO-144's queue probe ({url})",
                meeting_url=url,
                video_url=result.video_url or "",
            )
        raise RowSkip(
            f"civicclerk: checked {len(candidates)} past event(s) with hasMedia set, "
            "none actually resolved a video",
            meeting_url=seed_url,
        )

    finder = get_finder(platform)
    try:
        result = await finder.resolve(seed_url)
    except ValueError as e:
        # Real, confirmed-live case (O'Fallon MO, Reedsburg WI, WO-134
        # 2026-09-09): a legacy vanity channel URL
        # ("youtube.com/OFallonTV") or a playlist URL neither one
        # matches _is_youtube_channel_url()'s upfront regex fast-path,
        # but both raise this exact adapter error. Falling back to the
        # same channel/playlist depth search here (rather than only at
        # the fast-path check above) makes it exhaustive instead of
        # depending on enumerating every possible URL shape.
        if platform == "youtube" and _YT_NOT_FOUND_VIDEO_ID in str(e):
            return await resolve_youtube_channel(session, seed_url)
        raise
    except CalendarPageError as e:
        tried, reason = pick_calendar_candidates(e.candidates)
        if not tried:
            raise RowSkip(f"CalendarPageError, {reason}", meeting_url=seed_url)
        best_no_video = None
        probe_rejected = None  # (result, url) -- WO-169, see PROBE_HOOK
        probed: List["queue_probe.ProbeResult"] = []  # WO-170
        selected_results: Dict[str, object] = {}  # WO-170: url -> result
        for i, picked in enumerate(tried):
            if i:
                await asyncio.sleep(CANDIDATE_DELAY_SECONDS)
            candidate_url = picked["url"]
            try:
                result = await resolve_via_platform(candidate_url)
            except CalendarPageError as e2:
                tried2, reason2 = pick_calendar_candidates(e2.candidates)
                if not tried2:
                    continue
                candidate_url = tried2[0]["url"]
                try:
                    result = await resolve_via_platform(candidate_url)
                except Exception:
                    continue
            except Exception:
                continue
            if e.jurisdiction_hint and not result.jurisdiction:
                result.jurisdiction = e.jurisdiction_hint
            if _has_video(result):
                # Came from a structured listing -- the listing itself
                # already establishes meeting-context, so the
                # blocklist-only check is enough even for a
                # HIGH_RISK_TITLE_PLATFORMS platform (e.g. a Vimeo
                # channel/showcase listing).
                if result.segments:
                    return result, candidate_url, False
                probe_result = await _probe_candidate_for_selection(
                    result, candidate_url
                )
                if probe_result is not None:
                    selected_results[candidate_url] = result
                    probe_result.url = candidate_url
                    probed.append(probe_result)
                    if (
                        probe_result.duration_seconds is not None
                        and queue_probe.IN_WINDOW_MIN_SECONDS
                        <= probe_result.duration_seconds
                        <= queue_probe.IN_WINDOW_MAX_SECONDS
                    ):
                        break
                    continue
                if await _candidate_passes_probe(result, candidate_url):
                    return result, candidate_url, False
                if probe_rejected is None:
                    probe_rejected = (result, candidate_url)
                continue
            if best_no_video is None and (result.agenda_items or result.agenda_link):
                best_no_video = (result, candidate_url, False)
        choice = _finish_probe_selection(probed)
        if choice:
            chosen_url = choice.url
            return selected_results[chosen_url], chosen_url, False
        if best_no_video:
            return best_no_video
        if probed:
            rejected_url = probed[-1].url
            raise ProbeRejected(
                f"checked {len(probed)} tier-3 candidate(s) from this listing, all "
                f"failed WO-144's probe or exceeded the plausible window",
                meeting_url=rejected_url,
                video_url=selected_results[rejected_url].video_url or "",
            )
        if probe_rejected:
            result, url = probe_rejected
            raise ProbeRejected(
                f"checked {len(tried)} candidate(s) from this listing, the best "
                f"video-bearing one failed WO-144's queue probe ({url})",
                meeting_url=url,
                video_url=result.video_url or "",
            )
        raise RowSkip(
            f"checked {len(tried)} candidate(s) from this listing, none had video",
            meeting_url=seed_url,
        )

    high_risk = platform in HIGH_RISK_TITLE_PLATFORMS
    if _has_video(result) and not result.segments:
        # A single, already-known candidate -- no listing to depth-search,
        # so WO-170's selection has nothing to choose AMONG, but it still
        # has to run: without this, a caller that sets PROBE_SELECT_HOOK
        # but never sets the older PROBE_HOOK would see this, the single
        # most common real shape (one already-known video, not a
        # listing), sail through with NO probe at all -- _candidate_passes_
        # probe() only consults PROBE_HOOK, and PROBE_HOOK being None
        # makes it return True unconditionally. Route through the same
        # probe-and-select machinery as every candidate loop, just with a
        # list of one.
        probe_result = await _probe_candidate_for_selection(result, seed_url)
        if probe_result is not None:
            probe_result.url = seed_url
            choice = _finish_probe_selection([probe_result])
            if not choice:
                raise ProbeRejected(
                    f"{platform}: resolved a real video but it failed WO-144's "
                    f"queue probe ({seed_url})",
                    meeting_url=seed_url,
                    video_url=result.video_url or "",
                )
        elif not await _candidate_passes_probe(result, seed_url):
            raise ProbeRejected(
                f"{platform}: resolved a real video but it failed WO-144's queue probe "
                f"({seed_url})",
                meeting_url=seed_url,
                video_url=result.video_url or "",
            )
    return result, seed_url, high_risk


async def _ingest_with_retry(
    session: aiohttp.ClientSession, payload: dict, input_url_normalized: str
) -> Optional[dict]:
    for attempt in (1, 2):
        try:
            return await _ingest(session, payload, input_url_normalized)
        except Exception:
            if attempt == 2:
                return None
            await asyncio.sleep(3)
    return None


_seen_keys: set = set()


def _dedup_key(result) -> str:
    if getattr(result, "external_id", None):
        return f"ext:{result.external_id}"
    return f"src:{normalize_url(result.source_url or '')}"


# --- Shared-host jurisdiction/pin handling -----------------------------

_VIMEO_ID_RE = re.compile(r"/(\d{6,})")


def _tenant_override_match(platform: str, result, final_seed: str) -> Optional[str]:
    """The `match` discriminator resolver.py's _match_override() needs
    for this platform, or None if this isn't a shared-host case that
    needs one. See app/utils/gov_registry/resolver.py's own docstring
    for the exact matching semantics (substring-of-path, or a `page_hints`
    key=value -- external_id populates that hint, which is why a bare
    video id works as `match` for YouTube/Vimeo)."""
    url = result.video_url or final_seed or ""
    if platform == "youtube":
        if result.external_id:
            return result.external_id
        m = _YT_ID_RE.search(url)
        return m.group(1) if m else None
    if platform == "vimeo":
        if result.external_id:
            return result.external_id
        m = _VIMEO_ID_RE.search(urlparse(url).path)
        return m.group(1) if m else None
    if platform in ("telvue", "cablecast"):
        path = urlparse(url).path.strip("/")
        return path or None
    return None


def _tenant_override_host(platform: str, result, final_seed: str) -> Optional[str]:
    url = result.video_url or final_seed or ""
    host = urlparse(url).netloc.lower()
    return host or None


_existing_tier3_queue_cache: Optional[set] = None


def _existing_tier3_queue_urls() -> set:
    """The set of video URLs already sitting in
    scripts/tier3_auto_transcription_queue.txt (first tab-field of each
    line, same key tests/test_transcription_queue_files.py's own
    test_no_duplicate_rows checks) -- read once per process and kept in
    sync as this run appends. Prevents this run (or a resumed one) from
    writing an exact duplicate line; see the comment at this function's
    only call site for the real duplicate-line incident this fixes."""
    global _existing_tier3_queue_cache
    if _existing_tier3_queue_cache is None:
        urls = set()
        if TIER3_QUEUE_FILE.exists():
            for line in TIER3_QUEUE_FILE.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    urls.add(line.split("\t", 1)[0])
        _existing_tier3_queue_cache = urls
    return _existing_tier3_queue_cache


_existing_overrides_cache: Optional[set] = None


def _existing_override_keys() -> set:
    global _existing_overrides_cache
    if _existing_overrides_cache is None:
        keys = set()
        if TENANT_OVERRIDES_CSV.exists():
            with TENANT_OVERRIDES_CSV.open(newline="", encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    keys.add((r.get("tenant_host", ""), r.get("match", "")))
        _existing_overrides_cache = keys
    return _existing_overrides_cache


def maybe_write_tenant_override(
    platform: str, result, final_seed: str, gov_id: str, unit_name: str, source_tag: str
) -> None:
    """Appends a fallback tenant_overrides.csv pin for a shared-host
    (YouTube/Vimeo/TelVue/Cablecast) video, per Ryan's rule: never leave
    a page on one of these hosts keyed to rtr:unknown when the
    government is already known from the CSV's own gov_id. Idempotent
    within and across runs (checks the file's current contents first).
    Takes effect for ingests only after the next deploy -- see this
    file's module docstring."""
    if platform not in SHARED_HOST_PLATFORMS:
        return
    host = _tenant_override_host(platform, result, final_seed)
    match = _tenant_override_match(platform, result, final_seed)
    if not host or not match:
        return
    key = (host, match)
    if key in _existing_override_keys():
        return
    row = {
        "tenant_host": host,
        "match": match,
        "gov_id": gov_id,
        "strength": "fallback",
        "source": source_tag,
        "evidence": f"{unit_name} -- WO-134 confirmed hit, gov_id={gov_id}",
    }
    is_new = not TENANT_OVERRIDES_CSV.exists()
    with TENANT_OVERRIDES_CSV.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "tenant_host",
                "match",
                "gov_id",
                "strength",
                "source",
                "evidence",
            ],
            lineterminator="\n",
        )
        if is_new:
            writer.writeheader()
        writer.writerow(row)
    _existing_override_keys().add(key)


def apply_display_jurisdiction(result, gov_id: str) -> None:
    """Sets result.jurisdiction to a real "Name, ST" string derived from
    the CSV's own gov_id when the adapter didn't already find one --
    "carries gov_id and display name through resolve" per Ryan's rule.
    Exact, not a guess: government_for_id() derives every field of a
    national gov_id from the census/statscan tables themselves."""
    if result.jurisdiction:
        return
    gov = government_for_id(gov_id)
    if gov and gov.gov_name and gov.state:
        result.jurisdiction = f"{gov.gov_name}, {gov.state}"


# --- Row processing ------------------------------------------------------


async def process_row(
    session: aiohttp.ClientSession, row: dict, covered_gov_ids: set, source_tag: str
) -> RowResult:
    gov_id = row["gov_id"]
    unit_name = row["unit_name"]
    homepage = row.get("homepage") or ""
    hop2_urls = [
        u.strip() for u in (row.get("hop2_urls") or "").split(";") if u.strip()
    ]
    hits = _parse_hit_source_urls(row.get("hit_source_urls") or "")

    if gov_id in covered_gov_ids:
        return RowResult(
            gov_id,
            unit_name,
            "",
            "already_covered",
            "gov_id already has an archived page",
        )

    if not hits:
        return RowResult(
            gov_id, unit_name, "", "skipped", "no hit_source_urls on this row"
        )

    supported_hits = [(p, u) for p, u in hits if p not in UNSUPPORTED_PLATFORMS]
    if not supported_hits:
        platforms_seen = ", ".join(sorted({p for p, _ in hits}))
        return RowResult(
            gov_id,
            unit_name,
            platforms_seen,
            "skipped",
            "unsupported platform, no adapter in this repo "
            "(boarddocs/municipalcodeonline/novusagenda/agendasuite)",
        )

    last_reason = ""
    last_seed_url = ""  # WO-169: best-effort meeting_url for a fully-skipped row
    last_video_url = ""  # WO-169: best-effort video_url for a fully-skipped row
    best_no_video_result = (
        None  # (platform, result, final_seed) across ALL hits on this row
    )
    best_probe_rejected_result = (
        None  # (platform, meeting_url, video_url, reason) -- WO-169
    )
    for platform, hit_url in supported_hits:
        try:
            get_finder(platform)
        except UnsupportedPlatformError:
            last_reason = f"{platform}: not registered in get_finder() (unexpected)"
            continue

        seed_url, reason = await locate_platform_url(
            session, platform, hit_url, hop2_urls, homepage
        )
        if not seed_url:
            last_reason = f"{platform}: {reason}"
            continue
        last_seed_url = seed_url

        try:
            result, final_seed, high_risk_title = await resolve_seed(
                session, platform, seed_url
            )
        except ProbeRejected as e:
            # A real video existed for this platform hit, but every
            # candidate resolve_seed() tried for it failed WO-144's queue
            # probe -- Ryan's rule is "take the next candidate, only
            # report rejected_by_probe once everything is exhausted," so
            # this keeps trying the row's OTHER platform hits (the outer
            # loop's own `continue`) before ever giving up on the whole
            # government. See ProbeRejected's own docstring.
            last_reason = f"{platform}: {e}"
            last_seed_url = e.meeting_url or last_seed_url
            last_video_url = e.video_url or last_video_url
            if best_probe_rejected_result is None:
                best_probe_rejected_result = (
                    platform,
                    e.meeting_url or seed_url,
                    e.video_url,
                    str(e),
                )
            continue
        except RowSkip as e:
            last_reason = f"{platform}: {e}"
            last_seed_url = e.meeting_url or last_seed_url
            last_video_url = e.video_url or last_video_url
            continue
        except Exception as e:
            raise RowError(f"{platform}: resolve raised: {e}") from e

        last_seed_url = final_seed
        last_video_url = result.video_url or last_video_url

        segments = result.segments or []
        agenda_items = result.agenda_items or []
        if not (segments or agenda_items or result.agenda_link or result.video_url):
            last_reason = (
                f"{platform}: resolved but no transcript/agenda/video ({final_seed})"
            )
            continue

        key = _dedup_key(result)
        if key in _seen_keys:
            last_reason = f"{platform}: duplicate of an already-processed meeting this run ({key})"
            continue

        effective_title = result.title or ""
        if not effective_title and result.video_url:
            oembed_title = await youtube_oembed_title(session, result.video_url)
            if oembed_title:
                effective_title = oembed_title
        if not _looks_like_real_meeting(
            effective_title, require_allowlist=high_risk_title
        ):
            why = (
                "no governing-body keyword in title"
                if high_risk_title
                else "blocklisted term in title"
            )
            last_reason = f"{platform}: title looks like a non-meeting video ({why}), not ingested: {effective_title!r} ({final_seed})"
            continue

        title = result.title or ""
        date = result.date or ""

        # Optional override: a caller (e.g. scripts/wo149_county_ladder_
        # sweep.py) can set this to a callable(result, gov_id, unit_name,
        # platform, final_seed) -> (ok: bool, note: str) to FORCE the
        # exact registry jurisdiction string on `result` (mutating it
        # in place, wo130_county_ingest.py's pattern) and reject a hit
        # whose adapter-guessed jurisdiction plainly names a different
        # government (e.g. a county's domain pointed at a same-named
        # independent city's tenant in another state -- the
        # "wrong-domain-mapping" trap). ok=False skips this hit and
        # tries the next one, same as any other RowSkip-shaped reason.
        # None (the default) leaves this pipeline's original behavior
        # (apply_display_jurisdiction below only fills a BLANK
        # jurisdiction) unchanged.
        if JURISDICTION_CHECK_HOOK is not None:
            ok, hook_note = JURISDICTION_CHECK_HOOK(
                result, gov_id, unit_name, platform, final_seed
            )
            if not ok:
                last_reason = f"{platform}: {hook_note}"
                continue

        if _has_video(result):
            if IDENTITY_CHECK_HOOK is not None:
                mismatch = IDENTITY_CHECK_HOOK(
                    row, platform, result, final_seed, effective_title
                )
                if mismatch:
                    last_reason = f"{platform}: wrong-domain-mapping: {mismatch}"
                    continue
            _seen_keys.add(key)
            apply_display_jurisdiction(result, gov_id)

            if segments:
                maybe_write_tenant_override(
                    platform, result, final_seed, gov_id, unit_name, source_tag
                )
                normalized = normalize_url(final_seed)
                # WO-222: this row already knows its government -- `gov_id`
                # is the function's first argument -- so send it in the
                # payload rather than relying on the tenant_overrides.csv
                # pin `maybe_write_tenant_override()` just wrote landing in
                # production before this page is created. Without this, a
                # fresh YouTube/Vimeo page keys to `rtr:unknown:<host>`
                # until the next Archive deploy runs the ingest and the
                # pin both (see docs/COVERAGE_HANDOVER.md §3 and
                # archive/db/crud.py's `_resolve_page_government()`,
                # `caller_gov_id`). A blank/None gov_id (shouldn't happen
                # here -- every row in this CSV has one) is omitted from
                # the payload entirely rather than sent as "" -- omitting
                # the key is what keeps this indistinguishable from every
                # existing caller of /internal/ingest that doesn't know a
                # gov_id, so the ladder runs exactly as it always has.
                #
                # (WO-223, running concurrently, hit and independently
                # fixed this exact gap the same evening -- confirmed live,
                # 30+ shared-host pages landed `gov_id=rtr:unknown` before
                # this landed. WO-222's version is kept here since it
                # reached `main` first and already covers every sweep
                # script that calls this shared helper, not just this one.)
                payload = result.model_dump()
                if gov_id:
                    payload["gov_id"] = gov_id
                try:
                    response = await _ingest_with_retry(session, payload, normalized)
                except Exception as e:
                    raise RowError(f"{platform}: ingest raised: {e}") from e
                if response is None:
                    raise RowError(
                        f"{platform}: resolved real content ({len(segments)} segments) "
                        f"but POST to Archive failed twice: {final_seed}"
                    )
                page_url = response.get("url")
                created = response.get("created")
                note = (
                    "" if created else " (matched an EXISTING page, not newly created)"
                )
                return RowResult(
                    gov_id,
                    unit_name,
                    platform,
                    "ingested_tier1_2",
                    f"{len(segments)} transcript segments{note}",
                    final_seed,
                    title,
                    date,
                    page_url or "",
                )

            # video_url present, no segments -- tier 3. Per
            # docs/BREADTH_SWEEP_BRIEF.md's "probe before queue" rule
            # (WO-144's probe helper), a caller that wants every tier-3
            # candidate probed first (dead-link/too-short rejected)
            # before it ever reaches the queue file can set TIER3_HANDLER
            # to a callback instead of letting this function append
            # directly -- WO-147 and WO-149 both do this so probing and
            # a per-candidate pending ledger happen before the queue
            # write and the tenant_overrides.csv pin, without
            # duplicating this whole resolve/ingest pipeline. Note the
            # pin is NOT written here for a tier-3 candidate (see
            # maybe_write_tenant_override's call site above, now scoped
            # to the tier-1/2 `if segments:` branch only) -- the pending
            # sink stores what a pin WOULD be (a `pin_row` column) and
            # the caller's own finish step applies it only for a
            # candidate the probe actually accepts, so a dead/too-short
            # video never earns a pin. Default (TIER3_HANDLER is None)
            # preserves the original behavior below unchanged.
            if TIER3_HANDLER is not None:
                TIER3_HANDLER(
                    gov_id=gov_id,
                    unit_name=unit_name,
                    platform=platform,
                    final_seed=final_seed,
                    hit_url=hit_url,
                    title=title,
                    date=date,
                    result=result,
                )
                return RowResult(
                    gov_id,
                    unit_name,
                    platform,
                    "queued_tier3_pending",
                    "real video, no transcript yet -- handed to TIER3_HANDLER for "
                    "probing before it is queued",
                    final_seed,
                    title,
                    date,
                    "",
                    video_url=result.video_url or "",
                )

            # video_url present, no segments -- tier 3, queue it, don't
            # ingest directly (per this project's own tier-3 pattern).
            # Real, confirmed-live bug this session (WO-134, 2026-09-09):
            # nationwide_2404_ingest.py's own tier-3 append had no
            # existing-queue check at all, and neither did an earlier
            # draft of this script -- repeated smoke-test runs during
            # development each blindly appended the same real URLs,
            # producing exact duplicate lines caught by tests/
            # test_transcription_queue_files.py's test_no_duplicate_rows
            # (fixed by a one-off dedupe of the file; this check is what
            # prevents it recurring on any future run/resume). This is
            # the direct/legacy path (TIER3_HANDLER is None), so the pin
            # is written here immediately, same as a tier-1/2 ingest --
            # only a HANDLER-intercepted candidate defers its pin to the
            # caller's own finish step (see TIER3_HANDLER's comment
            # above).
            maybe_write_tenant_override(
                platform, result, final_seed, gov_id, unit_name, source_tag
            )
            already_queued = final_seed in _existing_tier3_queue_urls()
            if not already_queued:
                source_line = (
                    f"{final_seed}\t{hit_url}" if hit_url != final_seed else final_seed
                )
                with TIER3_QUEUE_FILE.open("a", encoding="utf-8") as f:
                    f.write(source_line + "\n")
                _existing_tier3_queue_urls().add(final_seed)
            return RowResult(
                gov_id,
                unit_name,
                platform,
                "queued_tier3",
                (
                    "real video, no transcript yet -- already in "
                    "tier3_auto_transcription_queue.txt, not appended again"
                    if already_queued
                    else "real video, no transcript yet -- appended to tier3_auto_transcription_queue.txt"
                ),
                final_seed,
                title,
                date,
                "",
                video_url=result.video_url or "",
            )

        # Real meeting resolved (agenda_items/agenda_link), but no video
        # within the depth budget on this hit. Remember the best one
        # across all of this row's hits, but keep trying other platform
        # hits first -- one of them might still have a video.
        if best_no_video_result is None:
            best_no_video_result = (platform, final_seed, title, date)
        last_reason = (
            f"{platform}: resolved real agenda content, no video found ({final_seed})"
        )

    # A real video existed on at least one of this row's platform hits, but
    # every candidate for it failed WO-144's queue probe -- report this
    # ahead of a no-video-at-all agenda result (stronger, more actionable
    # evidence: something real was there, just not currently playable/
    # long enough), and only now that every hit on the row is exhausted
    # (Ryan's "take the next candidate, report rejected_by_probe only
    # once candidates are exhausted" rule).
    if best_probe_rejected_result:
        platform, meeting_url, video_url, reason = best_probe_rejected_result
        return RowResult(
            gov_id,
            unit_name,
            platform,
            "rejected_by_probe",
            reason,
            meeting_url,
            "",
            "",
            "",
            video_url=video_url,
        )

    if best_no_video_result:
        platform, final_seed, title, date = best_no_video_result
        return RowResult(
            gov_id,
            unit_name,
            platform,
            "no_video_found",
            "resolved a real, current meeting -- no video attached (agenda-only, "
            "not ingested per Ryan's 2026-09-09 rule)",
            final_seed,
            title,
            date,
            "",
        )

    return RowResult(
        gov_id,
        unit_name,
        ", ".join(p for p, _ in supported_hits),
        "skipped",
        last_reason or "no usable platform link found",
        last_seed_url,
        "",
        "",
        "",
        video_url=last_video_url,
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--start-after", type=str, default=None)
    parser.add_argument(
        "--inventory-csv",
        type=Path,
        default=DEFAULT_INVENTORY_CSV,
        help="meeting_inventory.csv from export_meeting_inventory.py --source export",
    )
    parser.add_argument(
        "--no-probe-select",
        action="store_true",
        help=(
            "disable WO-170's 'check several candidates, prefer 9-40 minutes, "
            "else shortest' selection and fall back to WO-169's plain "
            "accept/reject probing -- for comparing behavior, not normal use"
        ),
    )
    args = parser.parse_args()

    if not _base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set (check .env).",
            file=sys.stderr,
        )
        sys.exit(1)

    register_all_finders()

    # WO-170: on by default for a direct run of this pipeline -- see
    # PROBE_SELECT_HOOK's own comment. A caller that imports this module
    # and sets its own PROBE_HOOK/PROBE_SELECT_HOOK (wo147/wo150/wo151/
    # wo169's re-run script, WO-170's own 45-government re-run) is
    # unaffected either way, since main() is never what those scripts
    # call.
    global PROBE_SELECT_HOOK
    if not args.no_probe_select:
        PROBE_SELECT_HOOK = build_probe_select_hook()

    covered_gov_ids = _load_covered_gov_ids(args.inventory_csv)
    print(f"{len(covered_gov_ids)} gov_ids already have an archived page.")

    all_rows: List[Tuple[dict, str]] = []
    for csv_path in INPUT_CSVS:
        if not csv_path.exists():
            print(f"(no {csv_path.name} yet -- skipping)")
            continue
        rows = _read_csv_rows(csv_path)
        print(f"{len(rows)} rows in {csv_path.name}")
        for r in rows:
            all_rows.append((r, csv_path.stem))  # e.g. "wo129_confirmed_hits"

    already_done = _already_logged_gov_ids(LOG_CSV)
    print(
        f"{len(already_done)} gov_ids already logged from a prior run -- skipping those."
    )

    skip_until_seen = args.start_after is not None
    to_process = []
    for row, source_tag in all_rows:
        if row["gov_id"] in already_done:
            continue
        if skip_until_seen:
            if row["gov_id"] == args.start_after:
                skip_until_seen = False
            continue
        to_process.append((row, source_tag))
    if args.limit:
        to_process = to_process[: args.limit]

    print(f"Processing {len(to_process)} row(s) against {_base_url()}...\n")

    log_f, log_writer = _log_writer(LOG_CSV)
    tally: Dict[str, int] = {}
    consecutive_errors = 0
    try:
        async with aiohttp.ClientSession() as session:
            for i, (row, source_tag) in enumerate(to_process):
                try:
                    result = await process_row(
                        session, row, covered_gov_ids, source_tag
                    )
                    consecutive_errors = 0
                except RowError as e:
                    result = RowResult(
                        row["gov_id"], row["unit_name"], "", "error", str(e)
                    )
                    consecutive_errors += 1
                except Exception as e:
                    result = RowResult(
                        row["gov_id"],
                        row["unit_name"],
                        "",
                        "error",
                        f"unhandled exception: {e}",
                    )
                    consecutive_errors += 1
                tally[result.outcome] = tally.get(result.outcome, 0) + 1
                print(
                    f"[{result.outcome:20}] {result.gov_id} {result.unit_name!r} platform={result.platform!r} -- {result.reason}"
                )
                log_writer.writerow(result.__dict__)
                log_f.flush()
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(
                        f"\nABORTING: {consecutive_errors} consecutive real errors -- "
                        "stopping per Ryan's politeness rule. Re-run to resume "
                        "(already-logged rows are skipped).",
                        file=sys.stderr,
                    )
                    break
                if i < len(to_process) - 1:
                    await asyncio.sleep(REQUEST_DELAY_SECONDS)
    finally:
        log_f.close()

    print("\n--- Tally (this run) ---")
    for outcome, count in sorted(tally.items()):
        print(f"{outcome:20} {count}")
    print(f"\nFull log: {LOG_CSV}")


if __name__ == "__main__":
    asyncio.run(main())
