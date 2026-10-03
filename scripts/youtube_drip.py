"""One always-on, politely paced YouTube process for a dedicated Mac.

Three lanes share ONE YouTube request budget (about one request every
three to four minutes, measured safe over five hours on 2026-09-11 where
the daily launchd burst was blocked within 9-38 pages every morning):

  captions  pages on the site waiting for a transcript
            (GET /internal/transcript-wanted) -> one caption request each,
            via scripts/fetch_youtube_transcripts.process_one(), which
            ingests or writes the permanent marker exactly as the daily job did.
  feed      the YouTube lines of scripts/tier3_auto_transcription_queue.txt
            -> scripts/feed_tier3_auto_transcription._push_if_has_video(),
            so the WO-144 probe and WO-156 ingest gate are unchanged. A page
            fed here is caption-fetched next by the captions lane. Its
            WO-144 probe rows go to a LOCAL, gitignored buffer
            (tier3_auto_transcription_queue_probe.local.csv), not the
            tracked sidecar CSV -- see `advance` below.
  audio     pages the captions lane marked "captions are disabled" ->
            audio download + local Whisper via
            scripts/transcribe_backlog_locally.process_one(), capped per day
            because YouTube blocked this office's address after three
            downloads in a row on 2026-09-09.

A block signal (429, IpBlocked, "Sign in to confirm you're not a bot")
pauses every lane and sleeps 15 min, then 30, 1 h, 2 h, 4 h (cap); a
success resets the ladder. The audio lane has its own ladder because its
block is a different mechanism. Nothing here retries through a block.
Any other error in a tick (an Archive timeout, say) is logged and the
tick retried five minutes later; the process never exits on one.

  vimeo     (WO-1147, 2026-09-27, opt-in -- not in the default --lanes)
            pages on the site waiting for a transcript
            (GET /internal/transcript-wanted?platform=vimeo) -> one resolve
            each, via scripts/fetch_vimeo_transcripts.process_one(), which
            ingests or writes Vimeo's own permanent no-captions marker.
            This lane is NOT part of the YouTube request budget above --
            Vimeo is a completely different host/service with no shared
            rate-limit reason to pace jointly with YouTube (unlike the
            three lanes above, which really do share one budget because
            they all ultimately talk to YouTube). It lives in this same
            process purely for operational convenience: one always-on Mac,
            one tick loop, one state file, one lock file -- not because
            Vimeo shares YouTube's block sensitivity. It reuses the same
            `--spacing-seconds` as every other lane (no separate pacing
            knob -- Vimeo has no documented rate-limit history the way
            YouTube does) and has its own independent block ladder
            (`vimeo_blocked_until`/`vimeo_block_level`), since a Vimeo
            challenge is a different, unrelated signal from a YouTube one.
            See BACKLOG.md's "Vimeo blocks Render" entry for why this
            exists at all: as of 2026-09-26, Render's own cloud IP gets a
            challenge page on every Vimeo caption fetch, the same
            structural problem YouTube has always had here.

  direct    (WO-1168, 2026-09-29, opt-in -- not in the default --lanes)
            feeds the tier-3 queue's non-YouTube, non-Vimeo lines --
            everything scripts/feed_tier3_auto_transcription.py's own
            GitHub Actions run either can't reach (Granicus/Cablecast
            403 GitHub's IP ranges even with a correct Referer, see that
            script's WO-1143 handling) or never claims in the first
            place -- straight to the Archive from this Mac's own office
            connection, via feed._push_if_has_video(). Both cloud
            transcription workers went idle 2026-09-29 (0 active jobs, 1
            finished in 24h) because that GitHub run is the only thing
            feeding new non-YouTube meetings in and its last run
            ingested 0 of 12; the same push run by hand from an office
            Mac that day ingested 31 of 40. This lane is that same push,
            run continuously but demand-gated: it only feeds while
            GET /internal/transcription-backlog reports fewer than
            --direct-low-water (default 10) non-YouTube, non-Vimeo pages
            still waiting for a transcript, so it tops the cloud queue
            up rather than dumping the whole ~930-line remainder in at
            once. That count is a full Archive scan, so it's cached 30
            minutes and decremented locally by one per successful feed
            in between real checks. Like the feed lane, a terminal
            outcome (OK/SKIP/FAIL) lands in the shared `fed` dict so
            `advance` drops that line from the queue file; a [NO-OWNER]
            line, or one the feed lane's own route_kept_line() would
            keep (a YouTube-bot-wall or GitHub-unreachable result), goes
            into `direct_parked` instead -- skipped on later ticks but
            never dropped by `advance`, since those are real, fixable
            gaps, not dead lines. Shares the YouTube-family spacing and
            block ladder like every lane except vimeo, since a Granicus
            or CivicClerk page can itself embed a YouTube video this Mac
            would then be fetching, sharing the same budget.

State lives outside the repo (--state-dir, default ~/.rtr/youtube_drip),
so a restart resumes. A lock file stops a second instance on the same
machine -- two pingers on one address is what this replaces. No alert
emails: the three reused functions never send any, and a block is
routine here, not an incident. Read docs/YOUTUBE_DRIP_RUNBOOK.md before
running this. Never rewrites a tracked file while the drip is running:
`advance` drops the fed queue lines and folds the feed lane's local probe
buffer into the tracked sidecar CSV (fold_probe_sidecar(), WO-248) --
both for the one daily PR, the same shape as the GitHub feed's. Before
WO-248, the feed lane appended straight to the tracked sidecar CSV live,
hours ahead of that one daily commit, while `main` kept growing the same
file through merged sweeps -- a merge conflict on every `git pull` on the
drip Mac, append-only so nothing was lost, but hand-resolved every day.
"""

import argparse
import asyncio
import csv
import fcntl
import json
import logging
import os
import random
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import certifi  # noqa: E402

# Before `import aiohttp` anywhere in this process -- see CLAUDE.md's SSL
# trust-store convention and scripts/transcribe_backlog_locally.py.
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO_ROOT / ".env")
# Also walk up from cwd: a worktree has no .env of its own (CLAUDE.md).
load_dotenv()

from app.platforms.base import UnsupportedPlatformError, detect_platform  # noqa: E402
from app.platforms.queue_probe import DEFAULT_SIDECAR_PATH  # noqa: E402
from app.platforms.youtube import YOUTUBE_CAPTIONS_DISABLED_MARKER  # noqa: E402

logger = logging.getLogger("youtube_drip")

# WO-1175: the drip's own drip.log handler, kept so tick() can put it back.
# Found live 2026-10-03: importing scripts/transcribe_backlog_locally.py (the
# audio lane does, on first use) runs logging.basicConfig(force=True), which
# silently removed this handler -- the drip kept working for 11+ hours with
# an empty log and nobody could tell it from a stall.
_DRIP_FILE_HANDLER: Optional[logging.Handler] = None

QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"
# WO-1016: this script's own three `_parse_queue_line()` call sites now
# unpack a 3-tuple (url, source_url, gov_id) -- that function is a thin
# wrapper over app.platforms.queue_probe.parse_queue_line(), which
# tolerates a queue line carrying an optional 3rd gov_id field. This Mac
# runs its OWN checkout (CLAUDE.md's "YouTube is fetched only by the
# drip Mac"), so this tolerance only takes effect here once this file's
# `git pull` picks up this change -- see docs/YOUTUBE_DRIP_RUNBOOK.md and
# BACKLOG_DONE.md's WO-1016 entries for the rollout order. Writers that
# know a gov_id emit the 3rd field since 2026-09-23
# (queue_probe.EMIT_GOV_ID_IN_QUEUE_LINES = True, flipped after this
# Mac confirmed it runs the tolerant readers).
# WO-248: the feed lane used to append every probe straight to the
# tracked DEFAULT_SIDECAR_PATH (app/platforms/queue_probe.py), live,
# while the drip ran for hours between the one daily `git pull` +
# `advance` + PR. Meanwhile `main` kept growing the same tracked file
# through merged sweeps elsewhere, so every pull on the drip Mac
# conflicted on it -- confirmed, append-only so nothing was ever lost,
# but the operator had to hand-resolve a union every single day. Rows
# now land here instead (gitignored, local to this Mac) and `advance`
# folds them into the tracked file once, right before the commit --
# see fold_probe_sidecar() below.
LOCAL_PROBE_SIDECAR_PATH = (
    REPO_ROOT / "scripts" / "tier3_auto_transcription_queue_probe.local.csv"
)
DEFAULT_STATE_DIR = Path.home() / ".rtr" / "youtube_drip"

# WO-1027 (2026-09-25): the `leads` lane. Ryan's hand-check spec for
# youtube_channel_leads.csv (Steps 2-4 in scripts/youtube_leads_fetch.py's
# docstring), run one row per tick like every other lane -- never a
# separate process, since that would add to the same one-connection
# YouTube budget without the tick loop's own accounting knowing about it.
# The input CSV, progress, results log and the local (gitignored,
# unfolded) queue-line buffer for a `pass` verdict all live next to the
# drip's own state files, not in the repo -- it's a data snapshot Ryan
# supplied directly, not something this checkout tracks.
LEADS_QUEUE_CSV = DEFAULT_STATE_DIR / "leads_queue.csv"
LEADS_PROGRESS_PATH = DEFAULT_STATE_DIR / "leads_progress.json"
LEADS_RESULTS_PATH = DEFAULT_STATE_DIR / "leads_results.jsonl"
LOCAL_LEADS_QUEUE_BUFFER = REPO_ROOT / "scripts" / "tier3_leads_new_lines.local.txt"

SPACING_SECONDS = 180.0
SPACING_JITTER_SECONDS = 60.0
BLOCK_SLEEPS_SECONDS = (900, 1800, 3600, 7200, 14400)
IDLE_SLEEP_SECONDS = 900.0

# WO-1175: one bad item must never hold the whole drip. A lane that raises on
# (or is blocked by) the same item repeatedly gets that item pushed to the
# back: skipped for STRIKE_RETRY_BASE_SECONDS * 2^(strikes-threshold), capped,
# then tried again. The first failure is only logged -- a transient outage
# (the Archive answering 502) should not penalize a healthy item.
STRIKE_DEFER_AFTER_ERRORS = 2
STRIKE_DEFER_AFTER_BLOCKS = 3
STRIKE_RETRY_BASE_SECONDS = 4 * 3600.0
STRIKE_RETRY_MAX_SECONDS = 48 * 3600.0
AUDIO_DOWNLOADS_PER_DAY = 3
# WO-1168: how long the direct lane trusts its own cached backlog count
# before re-checking GET /internal/transcription-backlog (a full Archive
# scan -- not something to run every tick) -- decremented locally by one
# per [OK] feed in between real checks.
DIRECT_BACKLOG_CACHE_SECONDS = 1800.0
DEFAULT_DIRECT_LOW_WATER = 10
# A tick that raises (an Archive connection timeout, a DNS blip -- anything
# that is not a YouTube block, which the lanes return rather than raise) is
# logged and retried after this fixed pause. Not the block ladder: a flaky
# Archive is a different failure from a YouTube block and gets no escalation.
TRANSIENT_ERROR_SLEEP_SECONDS = 300.0

_BLOCK_PATTERNS = (
    "ipblocked",
    "requestblocked",
    "too many requests",
    "sign in to confirm",
    "rate-limit/block signal",
    "youtube is currently blocking",
    " 429",
    "http error 429",
)
_YT_ID_RE = re.compile(
    r"(?:v=|/embed/|/live/|youtu\.be/|/shorts/)([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])"
)


# --- pure helpers (tested in tests/test_youtube_drip.py) ------------------


def is_block_text(text: str) -> bool:
    """True when a reused script's returned string or exception text carries
    a YouTube block signal rather than an ordinary per-video failure."""
    low = (text or "").lower()
    return any(p in low for p in _BLOCK_PATTERNS)


def next_block_sleep(level: int) -> int:
    return BLOCK_SLEEPS_SECONDS[min(level, len(BLOCK_SLEEPS_SECONDS) - 1)]


# Platforms whose meeting pages embed a YouTube video (CivicWeb and
# PrimeGov delegate to the YouTube adapter; BoardDocs -- WO-365 -- delegates
# to YouTube OR Vimeo, see each adapter's own docstring). Their queue lines
# belong to this lane too: the resolve is a YouTube metadata call from this
# machine's address, and the probe then dispatches on the resolved video's
# host (WO-205), so a line whose video turns out not to be YouTube (a
# BoardDocs tenant whose `bd.videoservice` is Vimeo, say) still ingests
# normally rather than erroring -- nothing here is YouTube-specific past
# this filter. Identity for a delegating platform's page comes from
# `source_url`/`origin_host` (the delegating platform's own tenant host,
# never overwritten by the direct-call delegation these three adapters use
# -- see boarddocs.py's/primegov.py's own docstrings) plus its
# `tenant_overrides.csv` pin, not from a bare `youtube:<id>` pin (WO-367).
YOUTUBE_DELEGATING_PLATFORMS = ("civicweb", "primegov", "boarddocs")


def _classify_queue_url(url: str) -> Tuple[bool, str]:
    """(keep?, reason) for one already-parsed queue URL -- "reason" is the
    detected platform when kept, or a short skip reason otherwise. The one
    place `youtube_queue_lines()` and `check_lines()` (WO-367's
    --check-lines) both dispatch on, so the filter a line actually gets fed
    through and the filter a dry run reports on can never drift apart.

    Claims a line for this drip Mac -- not only a YouTube video, but (WO-1147,
    2026-09-27) a real single-video Vimeo URL too, since Vimeo's own caption
    fetch now needs the same off-Render treatment as YouTube's (see this
    module's docstring). `parse_vimeo_video()` is reused directly (not a
    second regex) so a listing page (a showcase/channel with many meetings)
    is correctly rejected the same way YouTube's own 11-char-id check
    rejects a bare channel/playlist URL."""
    try:
        platform = detect_platform(url)
    except UnsupportedPlatformError:
        return False, "unsupported platform"
    if platform in YOUTUBE_DELEGATING_PLATFORMS:
        return True, platform
    if platform == "vimeo":
        from app.platforms.vimeo import parse_vimeo_video

        if parse_vimeo_video(url) is None:
            return False, "vimeo platform but not a real single-video URL"
        return True, platform
    if platform != "youtube":
        return False, f"platform={platform}, not a YouTube or Vimeo delegator"
    if not _YT_ID_RE.search(url):
        return False, "youtube platform but no 11-char video id in the URL"
    return True, platform


def youtube_queue_lines(lines: List[str]) -> List[Tuple[str, str, Optional[str]]]:
    """(raw line, url, source_url_override) for every queue line whose URL
    is a YouTube or Vimeo video, or a page on a platform that embeds one
    (WO-1147: the feed lane claims Vimeo lines too now). Uses the feed's
    own line parser so the tab field means the same thing here as there."""
    from scripts.feed_tier3_auto_transcription import _parse_queue_line

    out = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        url, src, _gov_id = _parse_queue_line(line)
        keep, _ = _classify_queue_url(url)
        if keep:
            out.append((line, url, src))
    return out


def check_lines(lines: List[str]) -> List[Tuple[str, str, str]]:
    """(raw line, verdict, detail) for every non-comment, non-blank queue
    line -- "keep"/"skip" plus the platform (kept) or reason (skipped).
    Filters through the exact same `_classify_queue_url()` the feed lane
    uses, so this is a real dry run of `youtube_queue_lines()`, not a
    parallel guess -- the --check-lines CLI command below prints this."""
    from scripts.feed_tier3_auto_transcription import _parse_queue_line

    out = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        url, _src, _gov_id = _parse_queue_line(line)
        keep, detail = _classify_queue_url(url)
        out.append((line, "keep" if keep else "skip", detail))
    return out


def slug_from_page_url(page_url: Optional[str]) -> Optional[str]:
    if not page_url:
        return None
    tail = page_url.rstrip("/").rsplit("/", 1)[-1]
    return tail or None


def pick_caption_page(
    pages: List[dict], done: Dict[str, str], prefer: List[str]
) -> Optional[dict]:
    """First page not already handled; pages the feed lane just created
    (prefer) go first so a fed page gets its captions within minutes."""
    pending = [p for p in pages if p.get("slug") and p["slug"] not in done]
    if not pending:
        return None
    for slug in prefer:
        for p in pending:
            if p["slug"] == slug:
                return p
    return pending[0]


def advance_queue_lines(lines: List[str], fed_urls: set) -> Tuple[List[str], int]:
    """Drop every queue line whose URL the drip has already fed. Returns
    (remaining lines, dropped count). Comments and blanks are preserved."""
    from scripts.feed_tier3_auto_transcription import _parse_queue_line

    kept, dropped = [], 0
    for raw in lines:
        line = raw.strip()
        if line and not line.startswith("#"):
            url, _, _gov_id = _parse_queue_line(line)
            if url in fed_urls:
                dropped += 1
                continue
        kept.append(raw)
    return kept, dropped


def fold_probe_sidecar(local_path: Path, tracked_path: Path) -> int:
    """Append every row in the drip's local probe buffer (`local_path`) to
    the tracked sidecar CSV (`tracked_path`) that isn't already there,
    keyed on the `url` column -- the same "already probed" dedup every
    other reader of this file already applies (e.g.
    wo150_finish_tier3.py's `_load_probed_urls()`), so a URL the tracked
    file already carries a row for is skipped rather than duplicated.
    Returns how many rows were actually appended. Does not touch
    `local_path` -- call `clear_local_probe_sidecar()` once this has run
    to empty the buffer for the next day."""
    if not local_path.exists():
        return 0
    with local_path.open(newline="") as f:
        rows = list(csv.reader(f))
    if len(rows) <= 1:
        return 0
    header, data_rows = rows[0], [r for r in rows[1:] if r]
    if not data_rows:
        return 0

    existing_urls = set()
    tracked_is_new = not tracked_path.exists()
    if not tracked_is_new:
        with tracked_path.open(newline="") as f:
            reader = csv.reader(f)
            next(reader, None)  # header
            existing_urls = {row[0] for row in reader if row}

    tracked_path.parent.mkdir(parents=True, exist_ok=True)
    appended = 0
    with tracked_path.open("a", newline="") as f:
        writer = csv.writer(f)
        if tracked_is_new:
            writer.writerow(header)
        for row in data_rows:
            if row[0] in existing_urls:
                continue
            writer.writerow(row)
            existing_urls.add(row[0])
            appended += 1
    return appended


def clear_local_probe_sidecar(local_path: Path) -> None:
    """Empty the drip's local probe buffer after fold_probe_sidecar() has
    copied its rows into the tracked file -- append_probe_row() recreates
    the header on the next write, same as a brand-new file, so removing
    it outright is enough."""
    local_path.unlink(missing_ok=True)


def audio_page_from_export_row(row: dict) -> Optional[dict]:
    """A transcribe_backlog_locally.process_one() page for an export row
    whose default transcript carries the captions-disabled marker."""
    if (row.get("video_format") or "") != "youtube":
        return None
    marked = False
    for v in row.get("versions") or []:
        if any(
            YOUTUBE_CAPTIONS_DISABLED_MARKER in str(w)
            for w in (v.get("transcript_warnings") or [])
        ):
            marked = True
    if not marked:
        return None
    return {
        "slug": row["slug"],
        "platform": row.get("platform") or "youtube",
        "external_id": row.get("external_id"),
        "source_url_normalized": row.get("source_url_normalized"),
        "video_url": row.get("video_url"),
        "video_format": "youtube",
    }


# --- identity worklist (docs/YOUTUBE_DRIP_IDENTITY_REVIEW.md) ---------------

IDENTITY_EVIDENCE_TIERS = ("registry", "pinned", "manual_override")
FED_PAGES_COLUMNS = (
    "fed_at",
    "slug",
    "page_url",
    "queue_url",
    "source_url",
    "gov_id",
    "jurisdiction",
    "jurisdiction_confidence",
    "video_channel",
    "video_channel_id",
    "needs_review",
    "title",
    "looks_like_meeting",
)


def needs_identity_review(row: dict) -> bool:
    """True unless the Archive keyed the page with real evidence. Mirrors
    archive/db/crud._GOV_EVIDENCE_TIERS: anything else (unresolved, blank,
    a minted `rtr:` id, an inferred tier) is a row for the pin worklist."""
    gov_id = row.get("gov_id") or ""
    if not gov_id or gov_id.startswith("rtr:"):
        return True
    return (row.get("jurisdiction_confidence") or "") not in IDENTITY_EVIDENCE_TIERS


def fed_page_row(
    export_row: dict, *, queue_url: str, source_url: Optional[str], fed_at: str
) -> dict:
    return {
        "fed_at": fed_at,
        "slug": export_row.get("slug") or "",
        "page_url": f"/m/{export_row.get('slug')}" if export_row.get("slug") else "",
        "queue_url": queue_url,
        "source_url": source_url or "",
        "gov_id": export_row.get("gov_id") or "",
        "jurisdiction": export_row.get("jurisdiction") or "",
        "jurisdiction_confidence": export_row.get("jurisdiction_confidence") or "",
        "video_channel": export_row.get("video_channel") or "",
        "video_channel_id": export_row.get("video_channel_id") or "",
        "needs_review": "yes" if needs_identity_review(export_row) else "",
        "title": export_row.get("title") or "",
        "looks_like_meeting": "yes"
        if looks_like_meeting(export_row.get("title"))
        else "no",
    }


def append_fed_page_row(path: Path, row: dict) -> None:
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FED_PAGES_COLUMNS, lineterminator="\n")
        if new:
            w.writeheader()
        w.writerow(row)


async def lookup_recent_page(
    session: aiohttp.ClientSession, slug: str
) -> Optional[dict]:
    """The export row for a page ingested moments ago (metadata only, no
    YouTube call). Returns None if the export does not list it yet."""
    from datetime import datetime, timedelta, timezone

    from scripts import fetch_youtube_transcripts as fetch

    since = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    async with session.get(
        f"{fetch._base_url()}/internal/export/pages",
        headers=fetch._headers(),
        params={"created_after": since, "limit": "200"},
        timeout=aiohttp.ClientTimeout(total=120),
    ) as r:
        if r.status != 200:
            return None
        data = await r.json()
    for row in data.get("pages", []):
        if row.get("slug") == slug:
            return row
    return None


# --- dead-video follow-up and off-mission flag ------------------------------

_CHANNEL_LINK_RE = re.compile(
    r"youtube\.com/(channel/UC[\w-]{22}|@[\w.-]+|c/[\w.-]+|user/[\w.-]+)"
)
_MEETING_WORDS_RE = re.compile(
    r"council|commission|committee|board|trustees|supervisors|selectmen|aldermen|"
    r"fiscal court|hearing|meeting|session|work ?session",
    re.I,
)
DEAD_VIDEOS_COLUMNS = (
    "recorded_at",
    "slug",
    "source_url",
    "video_url",
    "reason",
    "channel_url",
    "candidate_video_id",
    "candidate_title",
)
_YOUTUBE_HOSTS = ("youtube.com", "youtu.be")


def find_channel_on_page(html: str) -> Optional[str]:
    """The first YouTube channel link on a government page (CivicWeb/eScribe
    footers carry one), as a full URL, or None."""
    m = _CHANNEL_LINK_RE.search(html or "")
    return f"https://www.youtube.com/{m.group(1)}" if m else None


def looks_like_meeting(title: Optional[str]) -> bool:
    return bool(_MEETING_WORDS_RE.search(title or ""))


def dead_video_rows(
    page: dict,
    reason: str,
    channel_url: Optional[str],
    candidates: List[Tuple[str, str]],
    recorded_at: str,
) -> List[dict]:
    base = {
        "recorded_at": recorded_at,
        "slug": page.get("slug") or "",
        "source_url": page.get("source_url_normalized") or "",
        "video_url": page.get("video_url") or "",
        "reason": reason[:160],
        "channel_url": channel_url or "",
    }
    if not candidates:
        return [{**base, "candidate_video_id": "", "candidate_title": ""}]
    return [
        {**base, "candidate_video_id": vid, "candidate_title": title}
        for vid, title in candidates
    ]


def _list_channel_streams(channel_url: str, n: int = 3) -> List[Tuple[str, str]]:
    """Newest streams on a channel via yt-dlp's flat listing -- ONE YouTube
    request. Flat listings carry no dates (CLAUDE.md), so titles are what
    a reviewer picks from."""
    import subprocess

    yt = Path(sys.executable).parent / "yt-dlp"
    out = subprocess.run(
        [
            str(yt) if yt.exists() else "yt-dlp",
            "--flat-playlist",
            "--playlist-end",
            str(n),
            "--no-warnings",
            "--print",
            "%(id)s|%(title).90s",
            channel_url.rstrip("/") + "/streams",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    rows = []
    for line in out.stdout.splitlines():
        if "|" in line:
            vid, title = line.split("|", 1)
            rows.append((vid.strip(), title.strip()))
    return rows


def append_rows(path: Path, columns: Tuple[str, ...], rows: List[dict]) -> None:
    new = not path.exists()
    with path.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=columns, lineterminator="\n")
        if new:
            w.writeheader()
        w.writerows(rows)


# --- state ------------------------------------------------------------------


def _empty_state() -> dict:
    return {
        "captions_done": {},
        "fed": {},
        "prefer": [],
        "audio_queue": [],
        "audio_done": {},
        "blocked_until": 0.0,
        "block_level": 0,
        "audio_blocked_until": 0.0,
        "audio_block_level": 0,
        # WO-1147: Vimeo's own lane bookkeeping, deliberately kept separate
        # from the YouTube-family dicts/counters above -- Vimeo pages are a
        # disjoint set of slugs (video_format differs) and its block ladder
        # is an independent, unrelated signal from YouTube's own.
        "vimeo_done": {},
        "vimeo_blocked_until": 0.0,
        "vimeo_block_level": 0,
        # WO-1168: the direct lane's own bookkeeping. `direct_parked`
        # holds urls a [NO-OWNER]/route_kept_line() result kept in the
        # queue -- skipped by the lane but never dropped by `advance`
        # (unlike the shared `fed` dict above, which both lane_feed and
        # lane_direct use for a terminal OK/SKIP/FAIL). The backlog count
        # is cached (see DIRECT_BACKLOG_CACHE_SECONDS) rather than
        # re-checked every tick.
        "direct_parked": [],
        "direct_backlog_count": 0,
        "direct_backlog_checked_at": 0.0,
        # WO-1175: per-item failure bookkeeping, keyed "lane|item".
        "strikes": {},
        "deferred_until": {},
        "day": "",
        "today": {},
        "blocks_total": 0,
    }


class State:
    def __init__(self, path: Path):
        self.path = path
        self.data = _empty_state()
        if path.exists():
            self.data.update(json.loads(path.read_text()))

    def save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, indent=1))
        os.replace(tmp, self.path)

    def bump(self, key: str, n: int = 1) -> None:
        self.data["today"][key] = self.data["today"].get(key, 0) + n

    def is_deferred(self, key: str) -> bool:
        return self.data.setdefault("deferred_until", {}).get(key, 0.0) > time.time()

    def clear_strikes(self, key: str) -> None:
        self.data.setdefault("strikes", {}).pop(key, None)
        self.data.setdefault("deferred_until", {}).pop(key, None)

    def add_strike(self, key: str, defer_after: int) -> Tuple[int, Optional[float]]:
        """Counts a failure. Returns (strikes, retry_at or None): retry_at is
        set once the item has failed `defer_after` times, and doubles per
        further strike up to STRIKE_RETRY_MAX_SECONDS."""
        strikes = self.data.setdefault("strikes", {})
        strikes[key] = strikes.get(key, 0) + 1
        n = strikes[key]
        if n < defer_after:
            return n, None
        delay = min(
            STRIKE_RETRY_BASE_SECONDS * (2 ** (n - defer_after)),
            STRIKE_RETRY_MAX_SECONDS,
        )
        retry_at = time.time() + delay
        self.data.setdefault("deferred_until", {})[key] = retry_at
        return n, retry_at

    def rollover(self, status_csv: Path, today: Optional[str] = None) -> None:
        today = today or date.today().isoformat()
        if self.data["day"] == today:
            return
        if self.data["day"]:
            counts = self.data["today"]
            new = not status_csv.exists()
            with status_csv.open("a", newline="") as f:
                w = csv.writer(f, lineterminator="\n")
                if new:
                    w.writerow(
                        [
                            "day",
                            "captions_ingested",
                            "captions_marked",
                            "captions_failed",
                            "fed_ok",
                            "fed_skipped",
                            "audio_done",
                            "audio_failed",
                            "blocks",
                            "vimeo_ingested",
                            "vimeo_marked",
                            "vimeo_failed",
                            "vimeo_blocks",
                        ]
                    )
                w.writerow(
                    [self.data["day"]]
                    + [
                        counts.get(k, 0)
                        for k in (
                            "captions_ingested",
                            "captions_marked",
                            "captions_failed",
                            "fed_ok",
                            "fed_skipped",
                            "audio_done",
                            "audio_failed",
                            "blocks",
                            "vimeo_ingested",
                            "vimeo_marked",
                            "vimeo_failed",
                            "vimeo_blocks",
                        )
                    ]
                )
        self.data["day"] = today
        self.data["today"] = {}


# --- the drip ---------------------------------------------------------------


class Drip:
    def __init__(
        self,
        state: State,
        *,
        dry_run: bool,
        lanes: Tuple[str, ...],
        audio_per_day: int,
        spacing: float,
        model_size: Optional[str],
        cpu_threads: Optional[int],
        direct_low_water: int = DEFAULT_DIRECT_LOW_WATER,
    ):
        self.state = state
        self.dry_run = dry_run
        self.lanes = lanes
        self.audio_per_day = audio_per_day
        self.spacing = spacing
        self.model_size = model_size
        self.cpu_threads = cpu_threads
        self.direct_low_water = direct_low_water
        self.fed_pages_csv: Optional[Path] = None
        self.dead_videos_csv: Optional[Path] = None
        self.consecutive_errors = 0
        self._engine = None
        self.alerts_path: Optional[Path] = None
        self.current_item: Optional[str] = None

    # -- block bookkeeping
    def _block(
        self, key: str, level_key: str, detail: str, *, counter_key: str = "blocks"
    ) -> float:
        """`counter_key` (WO-1147, 2026-09-27): which `daily_status.csv`
        counter this block bumps, via `self.state.bump()`. Defaults to the
        shared `"blocks"` counter every YouTube-family lane
        (captions/feed/audio/leads) already used before this parameter
        existed -- unchanged for them. `lane_vimeo` passes
        `counter_key="vimeo_blocks"` instead, so a Vimeo challenge (a
        different, unrelated signal from a YouTube block) gets its own
        column rather than conflating into a count that, before this WO,
        only ever meant "a YouTube-family block happened"."""
        d = self.state.data
        sleep = next_block_sleep(d[level_key])
        d[level_key] += 1
        d[key] = time.time() + sleep
        d["blocks_total"] += 1
        self.state.bump(counter_key)
        logger.warning(
            "BLOCK (%s): sleeping %d min -- %s", key, sleep // 60, detail[:200]
        )
        return float(sleep)

    # -- WO-1175: loud failures and "push the bad one to the back"
    def _alert(self, message: str) -> None:
        """A failure a person should see: ERROR-level banner in the log and
        stdout, one line appended to alerts.log, and a macOS notification
        (best effort -- never allowed to raise)."""
        logger.error("!!! DRIP ALERT: %s", message)
        if self.alerts_path is not None:
            try:
                with self.alerts_path.open("a", encoding="utf-8") as f:
                    f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {message}\n")
            except OSError:
                pass
        if sys.platform == "darwin" and not self.dry_run:
            try:
                import subprocess

                subprocess.run(
                    [
                        "osascript",
                        "-e",
                        "display notification "
                        + json.dumps(message[:180])
                        + ' with title "youtube_drip alert"',
                    ],
                    timeout=5,
                    capture_output=True,
                )
            except Exception:
                pass

    def _item_failed(self, what: str, detail: str, defer_after: int) -> None:
        """Counts a failure against whatever item the lane was working on.
        Once it has failed `defer_after` times it is deferred (back of the
        queue, retried later with growing delay) and an alert is raised."""
        item = self.current_item
        if not item:
            self._alert(f"{what} with no identifiable item: {detail[:200]}")
            return
        n, retry_at = self.state.add_strike(item, defer_after)
        if retry_at is None:
            logger.error(
                "item failure %d/%d (%s) %s: %s",
                n,
                defer_after,
                what,
                item,
                detail[:200],
            )
            return
        hours = (retry_at - time.time()) / 3600.0
        self._alert(
            f"{item} failed {n}x ({what}); pushed to the back, retry in {hours:.0f}h: "
            f"{detail[:160]}"
        )

    def _ensure_log_handlers(self) -> None:
        if _DRIP_FILE_HANDLER is None:
            return
        root = logging.getLogger()
        if _DRIP_FILE_HANDLER not in root.handlers:
            root.addHandler(_DRIP_FILE_HANDLER)
            self._alert(
                "a library removed the drip.log handler (logging.basicConfig force=True "
                "on import); put it back"
            )

    # -- lanes: each returns (did_touch_youtube, sleep_override or None)
    async def lane_captions(
        self, session: aiohttp.ClientSession
    ) -> Tuple[bool, Optional[float]]:
        from scripts import fetch_youtube_transcripts as fetch

        pages = [
            p
            for p in await fetch._get_wanted(session)
            if not self.state.is_deferred(f"captions|{p.get('slug')}")
        ]
        page = pick_caption_page(
            pages, self.state.data["captions_done"], self.state.data["prefer"]
        )
        if page is None:
            return False, None
        slug = page["slug"]
        self.current_item = f"captions|{slug}"
        try:
            result = await fetch.process_one(session, page, dry_run=self.dry_run)
        except Exception as e:  # a block is raised, not returned, by process_one
            if fetch._is_rate_limit_signal(e) or is_block_text(str(e)):
                return True, self._block("blocked_until", "block_level", f"{slug}: {e}")
            result = {
                "slug": slug,
                "status": "failed",
                "detail": f"{type(e).__name__}: {e}",
            }
        status, detail = (
            result["status"],
            " ".join(str(result.get("detail") or "").split()),
        )
        if status == "ingested":
            self.state.bump("captions_ingested")
        elif status == "skipped":
            self.state.bump("captions_marked")
            if "video is unavailable" in detail:
                await self._dead_video_followup(session, page, detail)
            if "captions are disabled" in detail and "audio" in self.lanes:
                self.state.data["audio_queue"].append(
                    {
                        "slug": slug,
                        "platform": page.get("platform") or "youtube",
                        "external_id": page.get("external_id"),
                        "source_url_normalized": page.get("source_url_normalized"),
                        "video_url": page.get("video_url"),
                        "video_format": "youtube",
                    }
                )
        else:
            self.state.bump("captions_failed")
        self.state.data["captions_done"][slug] = status
        if slug in self.state.data["prefer"]:
            self.state.data["prefer"].remove(slug)
        self.state.data["block_level"] = 0
        logger.info("captions %-8s %s -- %s", status.upper(), slug, detail[:140])
        return True, None

    async def lane_vimeo(
        self, session: aiohttp.ClientSession
    ) -> Tuple[bool, Optional[float]]:
        """WO-1147 (2026-09-27): the Vimeo sibling of lane_captions() above
        -- same shape, its own queue (GET /internal/transcript-wanted
        ?platform=vimeo), its own `done` dict (`vimeo_done`, never shared
        with `captions_done` -- see _empty_state()'s own comment), and its
        own independent block ladder (`vimeo_blocked_until`/
        `vimeo_block_level`, bumping a Vimeo-only `vimeo_blocks` counter,
        never the shared `blocks` counter the YouTube-family lanes use --
        nothing else in this repo reads `daily_status.csv` programmatically
        as of this WO, so a clean separate column was preferred over
        conflating Vimeo blocks into a count that today only ever means a
        YouTube-family block).

        Reuses `self.state.data["prefer"]` (the same list the feed lane
        populates for a freshly-fed YouTube page) rather than a separate
        Vimeo-only prefer list -- `pick_caption_page()` is generic over any
        list of pages with a "slug" key and a `done` dict, so a freshly-fed
        Vimeo page jumping this lane's own queue quickly is exactly the
        same win the feed lane already gets for YouTube, at zero extra
        bookkeeping cost."""
        from scripts import fetch_vimeo_transcripts as vimeo_fetch

        pages = [
            p
            for p in await vimeo_fetch._get_wanted(session)
            if not self.state.is_deferred(f"vimeo|{p.get('slug')}")
        ]
        page = pick_caption_page(
            pages, self.state.data["vimeo_done"], self.state.data["prefer"]
        )
        if page is None:
            return False, None
        slug = page["slug"]
        self.current_item = f"vimeo|{slug}"
        try:
            result = await vimeo_fetch.process_one(session, page, dry_run=self.dry_run)
        except Exception as e:
            result = {
                "slug": slug,
                "status": "failed",
                "detail": f"{type(e).__name__}: {e}",
            }
        status, detail = (
            result["status"],
            " ".join(str(result.get("detail") or "").split()),
        )
        if status == "blocked":
            return True, self._block(
                "vimeo_blocked_until",
                "vimeo_block_level",
                f"{slug}: {detail}",
                counter_key="vimeo_blocks",
            )
        if status == "ingested":
            self.state.bump("vimeo_ingested")
        elif status == "skipped":
            self.state.bump("vimeo_marked")
        else:
            self.state.bump("vimeo_failed")
        self.state.data["vimeo_done"][slug] = status
        if slug in self.state.data["prefer"]:
            self.state.data["prefer"].remove(slug)
        self.state.data["vimeo_block_level"] = 0
        logger.info("vimeo    %-8s %s -- %s", status.upper(), slug, detail[:140])
        return True, None

    async def lane_feed(
        self, session: aiohttp.ClientSession
    ) -> Tuple[bool, Optional[float]]:
        from scripts import feed_tier3_auto_transcription as feed

        if not QUEUE_FILE.exists():
            return False, None
        fed = self.state.data["fed"]
        todo = [
            t
            for t in youtube_queue_lines(QUEUE_FILE.read_text().splitlines())
            if t[1] not in fed and not self.state.is_deferred(f"feed|{t[1]}")
        ]
        if not todo:
            return False, None
        line, url, src = todo[0]
        self.current_item = f"feed|{url}"
        if self.dry_run:
            result = f"[DRY-RUN] would feed {url}"
        else:
            result = await feed._push_if_has_video(
                session, url, src, probe_sidecar_path=LOCAL_PROBE_SIDECAR_PATH
            )
        if is_block_text(result):
            return True, self._block("blocked_until", "block_level", result)
        fed[url] = result[:200]
        if result.startswith("[OK]"):
            self.state.bump("fed_ok")
            slug = slug_from_page_url(result.split("->", 1)[-1].strip())
            if slug and slug not in self.state.data["prefer"]:
                self.state.data["prefer"].append(slug)
            if slug and self.fed_pages_csv is not None:
                try:
                    export_row = await lookup_recent_page(session, slug) or {
                        "slug": slug
                    }
                except (
                    Exception
                ) as e:  # identity lookup is bookkeeping, never a reason to stop
                    logger.warning("identity lookup failed for %s: %s", slug, e)
                    export_row = {"slug": slug}
                row = fed_page_row(
                    export_row,
                    queue_url=url,
                    source_url=src,
                    fed_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                )
                append_fed_page_row(self.fed_pages_csv, row)
                if row["needs_review"]:
                    self.state.bump("fed_needs_review")
        else:
            self.state.bump("fed_skipped")
            if "reject-dead" in result:
                await self._dead_video_followup(
                    session,
                    {"slug": "", "source_url_normalized": src or url, "video_url": url},
                    result,
                )
        self.state.data["block_level"] = 0
        logger.info("feed     %s", result[:180])
        return True, None

    async def _direct_backlog_count(self, session: aiohttp.ClientSession) -> int:
        """Cached (DIRECT_BACKLOG_CACHE_SECONDS) count of non-YouTube,
        non-Vimeo pages waiting for a transcript, from GET
        /internal/transcription-backlog -- a full Archive scan
        (list_transcription_backlog_candidates(), see archive/db/crud.py),
        so not something to run on every tick. worker/main.py's
        maybe_generate_batch_auto_jobs() only skips a candidate outright
        when `video_format == "youtube"` -- Vimeo isn't excluded there
        today -- but a Vimeo page's captions can't be fetched from Render
        either (CLAUDE.md: Vimeo is tier 2, same as YouTube, since
        2026-09-26), so it's excluded from this count too rather than
        counted as ready work the cloud worker can't actually finish."""
        from scripts import fetch_youtube_transcripts as fetch

        d = self.state.data
        now = time.time()
        if d.get("direct_backlog_checked_at", 0) + DIRECT_BACKLOG_CACHE_SECONDS > now:
            return d["direct_backlog_count"]
        async with session.get(
            f"{fetch._base_url()}/internal/transcription-backlog",
            headers=fetch._headers(),
            timeout=aiohttp.ClientTimeout(total=120),
        ) as r:
            r.raise_for_status()
            data = await r.json()
        count = sum(
            1
            for p in data.get("pages", [])
            if (p.get("platform") or "") not in ("youtube", "vimeo")
        )
        d["direct_backlog_count"] = count
        d["direct_backlog_checked_at"] = now
        return count

    async def lane_direct(
        self, session: aiohttp.ClientSession
    ) -> Tuple[bool, Optional[float]]:
        """WO-1168 (2026-09-29): feeds the tier-3 queue's non-YouTube,
        non-Vimeo lines straight to the Archive from this Mac -- see this
        module's own docstring for why (the GitHub feed can't reach most
        of them). Demand-gated by `_direct_backlog_count()`: returns
        (False, None) -- "not touched" -- whenever the cloud workers
        already have `direct_low_water` or more non-YouTube, non-Vimeo
        pages waiting, so other lanes get a turn and the tick idles as
        normal rather than this lane always winning the race."""
        from scripts import feed_tier3_auto_transcription as feed

        if not QUEUE_FILE.exists():
            return False, None

        if await self._direct_backlog_count(session) >= self.direct_low_water:
            return False, None

        fed = self.state.data["fed"]
        parked = self.state.data["direct_parked"]
        todo = None
        for raw in QUEUE_FILE.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            url, src, gov_id = feed._parse_queue_line(line)
            if url in fed or url in parked or self.state.is_deferred(f"direct|{url}"):
                continue
            keep, _ = _classify_queue_url(url)
            if keep:
                continue  # youtube/vimeo/delegating -- lane_feed's job, not this one
            todo = (url, src, gov_id)
            break
        if todo is None:
            return False, None

        url, src, gov_id = todo
        self.current_item = f"direct|{url}"
        if self.dry_run:
            result = f"[DRY-RUN] would feed {url}"
        else:
            result = await feed._push_if_has_video(
                session,
                url,
                src,
                gov_id,
                probe_sidecar_path=LOCAL_PROBE_SIDECAR_PATH,
            )
        if is_block_text(result):
            return True, self._block("blocked_until", "block_level", result)

        # A [NO-OWNER] line or one route_kept_line() would keep (a
        # YouTube-bot-wall or GitHub-unreachable result) is a real,
        # fixable gap, not a dead line -- park it (skip, don't drop) the
        # same way main() in feed_tier3_auto_transcription.py keeps these
        # in its own queue rotation instead of dropping them.
        if result.startswith("[NO-OWNER]") or feed.route_kept_line(result) is not None:
            parked.append(url)
            self.state.bump("direct_parked")
            logger.info("direct   PARKED   %s", result[:180])
        else:
            fed[url] = result[:200]
            if result.startswith("[OK]"):
                self.state.bump("direct_ok")
                self.state.data["direct_backlog_count"] = max(
                    0, self.state.data.get("direct_backlog_count", 0) - 1
                )
            else:
                self.state.bump("direct_skipped")
            logger.info("direct   %s", result[:180])
        self.state.data["block_level"] = 0
        return True, None

    async def _dead_video_followup(
        self, session: aiohttp.ClientSession, page: dict, reason: str
    ) -> bool:
        """Record a dead video and, when the government's own page links a
        YouTube channel, that channel's newest streams -- a worklist for a
        human to pick a live meeting from (docs/YOUTUBE_DRIP_IDENTITY_REVIEW.md).
        Returns True when a YouTube request was made."""
        if self.dead_videos_csv is None:
            return False
        source = page.get("source_url_normalized") or ""
        channel_url, candidates, touched = None, [], False
        if source and not any(h in source for h in _YOUTUBE_HOSTS):
            try:
                async with session.get(
                    source,
                    timeout=aiohttp.ClientTimeout(total=30),
                    headers={"User-Agent": "Mozilla/5.0"},
                ) as r:
                    channel_url = find_channel_on_page(await r.text(errors="replace"))
            except Exception as e:
                logger.info("dead-video follow-up: could not read %s (%s)", source, e)
        if channel_url and not self.dry_run:
            touched = True
            try:
                candidates = await asyncio.to_thread(_list_channel_streams, channel_url)
            except Exception as e:
                logger.info(
                    "dead-video follow-up: channel listing failed for %s (%s)",
                    channel_url,
                    e,
                )
        rows = dead_video_rows(
            page, reason, channel_url, candidates, time.strftime("%Y-%m-%dT%H:%M:%S")
        )
        append_rows(self.dead_videos_csv, DEAD_VIDEOS_COLUMNS, rows)
        self.state.bump("dead_videos")
        logger.info(
            "dead     %s -- channel %s, %d candidate(s) recorded",
            page.get("slug") or page.get("video_url"),
            channel_url or "not found",
            len(candidates),
        )
        return touched

    def _get_engine(self):
        if self._engine is None:
            from scripts import transcribe_backlog_locally as tbl
            from worker.transcription_engine import FasterWhisperEngine

            size = self.model_size or tbl._pick_default_model_size()
            threads = (
                self.cpu_threads
                if self.cpu_threads is not None
                else tbl._pick_default_cpu_threads()
            )
            logger.info("loading faster-whisper %s (%s CPU threads)", size, threads)
            self._engine = FasterWhisperEngine(model_size=size, cpu_threads=threads)
        return self._engine

    async def lane_audio(
        self, session: aiohttp.ClientSession
    ) -> Tuple[bool, Optional[float]]:
        from scripts import transcribe_backlog_locally as tbl

        d = self.state.data
        if (
            not d["audio_queue"]
            or d["today"].get("audio_downloads", 0) >= self.audio_per_day
        ):
            return False, None
        if d["audio_blocked_until"] > time.time():
            return False, None
        page = next(
            (
                p
                for p in d["audio_queue"]
                if not self.state.is_deferred(f"audio|{p['slug']}")
            ),
            None,
        )
        if page is None:
            return False, None
        self.current_item = f"audio|{page['slug']}"
        self.state.bump("audio_downloads")
        result = await tbl.process_one(
            session,
            self._get_engine(),
            page,
            dry_run=self.dry_run,
            chunk_seconds_override=None,
            promote=True,
        )
        status, detail = (
            result["status"],
            " ".join(str(result.get("detail") or "").split()),
        )
        if status != "ingested" and is_block_text(detail):
            return True, self._block(
                "audio_blocked_until", "audio_block_level", f"{page['slug']}: {detail}"
            )
        d["audio_queue"].remove(page)
        d["audio_done"][page["slug"]] = status
        d["audio_block_level"] = 0
        self.state.bump("audio_done" if status == "ingested" else "audio_failed")
        logger.info(
            "audio    %-8s %s -- %s", status.upper(), page["slug"], detail[:140]
        )
        return True, None

    async def lane_leads(
        self, session: aiohttp.ClientSession
    ) -> Tuple[bool, Optional[float]]:
        """WO-1027: one row of youtube_channel_leads.csv per tick, Ryan's
        2026-09-25 hand-check spec (scripts/youtube_leads_fetch.py). No
        `session` use -- yt-dlp is a subprocess, not this process's own
        aiohttp client -- but the signature matches every other lane's so
        `tick()` doesn't need a special case."""
        import csv
        import json

        from scripts.youtube_leads_fetch import process_row

        if not LEADS_QUEUE_CSV.exists():
            return False, None

        progress = {"done_urls": [], "passed_govs": []}
        if LEADS_PROGRESS_PATH.exists():
            progress = json.loads(LEADS_PROGRESS_PATH.read_text())
        done = set(progress["done_urls"])
        passed_govs = set(progress["passed_govs"])

        with LEADS_QUEUE_CSV.open(newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(line for line in f if not line.startswith("#")))

        row = next(
            (
                r
                for r in rows
                if r["channel_url"] not in done
                and (r.get("gov_id") or "") not in passed_govs
                and not self.state.is_deferred(f"leads|{r['channel_url']}")
            ),
            None,
        )
        if row is None:
            return False, None
        self.current_item = f"leads|{row['channel_url']}"

        verdict = process_row(row)

        if verdict.verdict == "needs-human" and "block signature" in verdict.reason:
            # A real block: don't consume this row (retry it next time),
            # and pause every lane the same way captions/audio already do.
            return True, self._block(
                "blocked_until", "block_level", f"leads lane: {verdict.reason}"
            )

        done.add(row["channel_url"])
        if verdict.verdict == "pass" and verdict.picked_video_url:
            gid = (row.get("gov_id") or "").strip()
            if gid:
                passed_govs.add(gid)
            from app.platforms.queue_probe import append_queue_line

            append_queue_line(
                verdict.picked_video_url,
                gov_id=gid,
                queue_path=LOCAL_LEADS_QUEUE_BUFFER,
            )

        LEADS_PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
        LEADS_PROGRESS_PATH.write_text(
            json.dumps({"done_urls": sorted(done), "passed_govs": sorted(passed_govs)})
        )
        with LEADS_RESULTS_PATH.open("a", encoding="utf-8") as f:
            f.write(
                json.dumps(
                    {
                        "channel_url": row["channel_url"],
                        "gov_id": row.get("gov_id"),
                        "government": row.get("government"),
                        "kind": row.get("kind"),
                        "verdict": verdict.verdict,
                        "reason": verdict.reason,
                        "picked_video_url": verdict.picked_video_url,
                        "picked_title": verdict.picked_title,
                        "identity_tier": verdict.identity_tier,
                        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    }
                )
                + "\n"
            )

        logger.info(
            "leads    %-18s %s -- %s",
            verdict.verdict,
            row.get("government") or row.get("gov_id"),
            verdict.reason[:140],
        )
        return True, None

    async def tick(self, session: aiohttp.ClientSession, status_csv: Path) -> float:
        """One scheduling step. Returns how long to sleep before the next."""
        self.state.rollover(status_csv)
        self._ensure_log_handlers()
        now = time.time()
        if self.state.data["blocked_until"] > now:
            return self.state.data["blocked_until"] - now
        order: List[Callable] = []
        if "captions" in self.lanes:
            order.append(self.lane_captions)
        # WO-1147: right after captions, before feed -- an arbitrary but
        # reasonable choice (Vimeo shares no request budget with anything
        # else here, so its position doesn't affect pacing correctness);
        # placed here rather than last so it gets a turn before a
        # feed/audio lane with a lot of pending work would otherwise crowd
        # it out on every tick.
        if "vimeo" in self.lanes:
            order.append(self.lane_vimeo)
        if "feed" in self.lanes:
            order.append(self.lane_feed)
        # WO-1168: right after feed -- both work the same queue file, and
        # feed (YouTube/Vimeo-shaped lines) should get first look on a
        # tick where both have work, since only the drip Mac can claim
        # those at all.
        if "direct" in self.lanes:
            order.append(self.lane_direct)
        if "audio" in self.lanes:
            order.append(self.lane_audio)
        if "leads" in self.lanes:
            order.append(self.lane_leads)
        try:
            for lane in order:
                self.current_item = None
                try:
                    touched, override = await lane(session)
                except Exception as e:
                    # A failure before any item was picked (the Archive down,
                    # a bad token) is an outage, not a bad item: let safe_tick
                    # pause the whole drip as before. A failure ON an item must
                    # not starve the other lanes, nor retry that same item
                    # first forever (WO-1175).
                    if not self.current_item:
                        raise
                    logger.exception("lane %s raised", lane.__name__)
                    self._item_failed(
                        f"{lane.__name__} {type(e).__name__}",
                        str(e),
                        STRIKE_DEFER_AFTER_ERRORS,
                    )
                    continue
                if override is not None:
                    self._item_failed(
                        f"{lane.__name__} blocked",
                        "block signature",
                        STRIKE_DEFER_AFTER_BLOCKS,
                    )
                    return override
                if touched:
                    if self.current_item:
                        self.state.clear_strikes(self.current_item)
                    return self.spacing + random.uniform(0, SPACING_JITTER_SECONDS)
        finally:
            self.state.save()
        return IDLE_SLEEP_SECONDS

    async def safe_tick(
        self, session: aiohttp.ClientSession, status_csv: Path, reraise: bool = False
    ) -> float:
        """tick(), but an exception is a pause, not an exit.

        Confirmed live 2026-09-11: a ClientConnectorError from the captions
        lane's GET against the Archive (a timeout, cleared seconds later)
        escaped to asyncio.run() and ended a process built to run for days.
        Every lane already turns a YouTube block into a returned sleep; this
        catches whatever else a tick raises, logs the traceback and the run
        of consecutive failures, and returns TRANSIENT_ERROR_SLEEP_SECONDS.
        `reraise` (used by --once) lets a one-shot run fail loudly instead.
        """
        try:
            sleep_for = await self.tick(session, status_csv)
        except Exception as e:
            if reraise:
                raise
            self.consecutive_errors += 1
            logger.exception(
                "tick failed (%d in a row): %s: %s -- retrying in %d min",
                self.consecutive_errors,
                type(e).__name__,
                str(e)[:200],
                int(TRANSIENT_ERROR_SLEEP_SECONDS // 60),
            )
            return TRANSIENT_ERROR_SLEEP_SECONDS
        if self.consecutive_errors:
            logger.info("tick recovered after %d failure(s)", self.consecutive_errors)
            self.consecutive_errors = 0
        return sleep_for


# --- entry points -----------------------------------------------------------


async def seed_audio_from_site(session: aiohttp.ClientSession, state: State) -> int:
    """Queue every on-site YouTube page already carrying the captions-disabled
    marker, from GET /internal/export/pages (paged, no YouTube calls)."""
    from scripts import fetch_youtube_transcripts as fetch

    have = {p["slug"] for p in state.data["audio_queue"]} | set(
        state.data["audio_done"]
    )
    added, after = 0, None
    while True:
        params = {"has_transcript": "false", "limit": "500"}
        if after:
            params["after_id"] = str(after)
        async with session.get(
            f"{fetch._base_url()}/internal/export/pages",
            headers=fetch._headers(),
            params=params,
            timeout=aiohttp.ClientTimeout(total=300),
        ) as r:
            r.raise_for_status()
            data = await r.json()
        for row in data.get("pages", []):
            page = audio_page_from_export_row(row)
            if page and page["slug"] not in have:
                state.data["audio_queue"].append(page)
                have.add(page["slug"])
                added += 1
        after = data.get("next_after_id")
        if not after or not data.get("pages"):
            break
    state.save()
    return added


async def advance(state: State) -> None:
    from scripts import fetch_youtube_transcripts as fetch

    lines = QUEUE_FILE.read_text().splitlines()
    kept, dropped = advance_queue_lines(lines, set(state.data["fed"]))
    QUEUE_FILE.write_text("\n".join(kept) + ("\n" if kept else ""))
    remaining = sum(
        1 for line in kept if line.strip() and not line.strip().startswith("#")
    )
    print(f"dropped {dropped} fed line(s); {remaining} remaining")

    folded = fold_probe_sidecar(LOCAL_PROBE_SIDECAR_PATH, DEFAULT_SIDECAR_PATH)
    clear_local_probe_sidecar(LOCAL_PROBE_SIDECAR_PATH)
    print(
        f"folded {folded} new probe row(s) from the local buffer into "
        f"{DEFAULT_SIDECAR_PATH.name}; local buffer cleared"
    )

    leads_folded = 0
    if LOCAL_LEADS_QUEUE_BUFFER.exists():
        from app.platforms.queue_probe import append_queue_line

        for line in LOCAL_LEADS_QUEUE_BUFFER.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            url = parts[0]
            source = parts[1] if len(parts) > 1 and parts[1] else None
            gid = parts[2] if len(parts) > 2 else ""
            if append_queue_line(url, source, gov_id=gid, queue_path=QUEUE_FILE):
                leads_folded += 1
        LOCAL_LEADS_QUEUE_BUFFER.unlink()
        print(
            f"folded {leads_folded} new leads-lane queue line(s) from the local "
            f"buffer into {QUEUE_FILE.name}; local buffer cleared"
        )

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                f"{fetch._base_url()}/internal/tier3-queue-remaining",
                params={"remaining": remaining},
                headers=fetch._headers(),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as r:
                print(f"reported remaining={remaining} to the Archive ({r.status})")
        except Exception as e:
            print(f"[WARN] could not report queue depth: {e}")


def _run_check_lines(args) -> None:
    """--check-lines / `check-lines <file>`: print keep/skip for every real
    line in a queue-shaped file with no network call and no lock -- a dry
    run of the feed lane's own filter (`youtube_queue_lines()`), for
    confirming a platform change (e.g. WO-367 adding "boarddocs" to
    YOUTUBE_DELEGATING_PLATFORMS) actually moves a real line from skip to
    keep before it ever reaches the drip Mac."""
    from app.platforms import register_all_finders

    register_all_finders()
    path = Path(args.check_lines_file or QUEUE_FILE)
    lines = path.read_text().splitlines()
    for line, verdict, detail in check_lines(lines):
        print(f"{verdict:4s} {detail:40s} {line}")


async def run(args) -> None:
    if args.command == "check-lines":
        _run_check_lines(args)
        return
    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    lock = open(state_dir / "lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(
            "another youtube_drip is already running on this machine -- one per address, see the runbook"
        )
    global _DRIP_FILE_HANDLER
    _DRIP_FILE_HANDLER = logging.FileHandler(state_dir / "drip.log")
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout), _DRIP_FILE_HANDLER],
    )
    state = State(state_dir / "state.json")
    status_csv = state_dir / "daily_status.csv"

    if args.command == "advance":
        await advance(state)
        return

    from app.platforms import register_all_finders

    register_all_finders()
    lanes = tuple(name.strip() for name in args.lanes.split(",") if name.strip())
    drip = Drip(
        state,
        dry_run=args.dry_run,
        lanes=lanes,
        audio_per_day=args.audio_per_day,
        spacing=args.spacing_seconds,
        model_size=args.model_size,
        cpu_threads=args.cpu_threads,
        direct_low_water=args.direct_low_water,
    )
    drip.fed_pages_csv = state_dir / "fed_pages.csv"
    drip.dead_videos_csv = state_dir / "dead_videos.csv"
    drip.alerts_path = state_dir / "alerts.log"
    async with aiohttp.ClientSession() as session:
        if args.seed_audio_from_site:
            logger.info(
                "seeded %d captions-disabled page(s) into the audio queue",
                await seed_audio_from_site(session, state),
            )
        logger.info(
            "drip start: lanes=%s spacing=%.0fs audio/day=%d dry_run=%s state=%s",
            ",".join(lanes),
            args.spacing_seconds,
            args.audio_per_day,
            args.dry_run,
            state_dir,
        )
        while True:
            sleep_for = await drip.safe_tick(session, status_csv, reraise=args.once)
            if args.once:
                return
            await asyncio.sleep(sleep_for)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "command",
        nargs="?",
        default="run",
        choices=["run", "advance", "check-lines"],
        help=(
            "run (default) = the drip; advance = drop fed lines from the queue "
            "file for a PR; check-lines = print keep/skip per line in "
            "--check-lines-file (default: the tier-3 queue file) with no "
            "network call, no lock -- a dry run of the feed lane's own filter"
        ),
    )
    p.add_argument(
        "--check-lines-file",
        default=None,
        help="check-lines only: path to a queue-shaped file (default: the tier-3 queue file)",
    )
    p.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    p.add_argument(
        "--lanes",
        default="captions,feed,audio",
        help=(
            "comma-separated subset of captions,feed,audio,leads,vimeo,direct "
            "-- vimeo (WO-1147) and direct (WO-1168) are opt-in and NOT in "
            "the default, since each is a new lane Ryan should add "
            "explicitly the first time it's wanted (e.g. "
            "--lanes captions,feed,audio,vimeo,direct)"
        ),
    )
    p.add_argument("--spacing-seconds", type=float, default=SPACING_SECONDS)
    p.add_argument("--audio-per-day", type=int, default=AUDIO_DOWNLOADS_PER_DAY)
    p.add_argument(
        "--direct-low-water",
        type=int,
        default=DEFAULT_DIRECT_LOW_WATER,
        help=(
            "direct lane only: feed while fewer than this many non-YouTube, "
            "non-Vimeo pages are waiting for a transcript "
            "(GET /internal/transcription-backlog)"
        ),
    )
    p.add_argument(
        "--model-size",
        default=None,
        help="Whisper model for the audio lane (default: sized from RAM)",
    )
    p.add_argument("--cpu-threads", type=int, default=None)
    p.add_argument(
        "--seed-audio-from-site",
        action="store_true",
        help="on start, queue every on-site page already marked captions-disabled",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--once", action="store_true", help="one scheduling step, then exit")
    return p


if __name__ == "__main__":
    asyncio.run(run(build_parser().parse_args()))
