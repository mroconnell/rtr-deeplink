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
            fed here is caption-fetched next by the captions lane.
  audio     pages the captions lane marked "captions are disabled" ->
            audio download + local Whisper via
            scripts/transcribe_backlog_locally.process_one(), capped per day
            because YouTube blocked this office's address after three
            downloads in a row on 2026-09-09.

A block signal (429, IpBlocked, "Sign in to confirm you're not a bot")
pauses every lane and sleeps 15 min, then 30, 1 h, 2 h, 4 h (cap); a
success resets the ladder. The audio lane has its own ladder because its
block is a different mechanism. Nothing here retries through a block.

State lives outside the repo (--state-dir, default ~/.rtr/youtube_drip),
so a restart resumes. A lock file stops a second instance on the same
machine -- two pingers on one address is what this replaces. No alert
emails: the three reused functions never send any, and a block is
routine here, not an incident. Read docs/YOUTUBE_DRIP_RUNBOOK.md before
running this. Never rewrites the queue file on its own: `advance` drops
the fed lines for a daily PR, the same shape as the GitHub feed's.
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
from app.platforms.youtube import YOUTUBE_CAPTIONS_DISABLED_MARKER  # noqa: E402

logger = logging.getLogger("youtube_drip")

QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"
DEFAULT_STATE_DIR = Path.home() / ".rtr" / "youtube_drip"

SPACING_SECONDS = 180.0
SPACING_JITTER_SECONDS = 60.0
BLOCK_SLEEPS_SECONDS = (900, 1800, 3600, 7200, 14400)
IDLE_SLEEP_SECONDS = 900.0
AUDIO_DOWNLOADS_PER_DAY = 3

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
# PrimeGov delegate to the YouTube adapter -- see each adapter's own
# docstring). Their queue lines belong to this lane too: the resolve is a
# YouTube metadata call from this machine's address, and the probe then
# dispatches on the resolved video's host (WO-205), so a line whose video
# turns out not to be YouTube still ingests normally.
YOUTUBE_DELEGATING_PLATFORMS = ("civicweb", "primegov")


def youtube_queue_lines(lines: List[str]) -> List[Tuple[str, str, Optional[str]]]:
    """(raw line, url, source_url_override) for every queue line whose URL
    is a YouTube video, or a page on a platform that embeds one. Uses the
    feed's own line parser so the tab field means the same thing here as
    there."""
    from scripts.feed_tier3_auto_transcription import _parse_queue_line

    out = []
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        url, src = _parse_queue_line(line)
        try:
            platform = detect_platform(url)
        except UnsupportedPlatformError:
            continue
        if platform in YOUTUBE_DELEGATING_PLATFORMS:
            out.append((line, url, src))
            continue
        if platform != "youtube" or not _YT_ID_RE.search(url):
            continue
        out.append((line, url, src))
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
            url, _ = _parse_queue_line(line)
            if url in fed_urls:
                dropped += 1
                continue
        kept.append(raw)
    return kept, dropped


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
    ):
        self.state = state
        self.dry_run = dry_run
        self.lanes = lanes
        self.audio_per_day = audio_per_day
        self.spacing = spacing
        self.model_size = model_size
        self.cpu_threads = cpu_threads
        self.fed_pages_csv: Optional[Path] = None
        self.dead_videos_csv: Optional[Path] = None
        self._engine = None

    # -- block bookkeeping
    def _block(self, key: str, level_key: str, detail: str) -> float:
        d = self.state.data
        sleep = next_block_sleep(d[level_key])
        d[level_key] += 1
        d[key] = time.time() + sleep
        d["blocks_total"] += 1
        self.state.bump("blocks")
        logger.warning(
            "BLOCK (%s): sleeping %d min -- %s", key, sleep // 60, detail[:200]
        )
        return float(sleep)

    # -- lanes: each returns (did_touch_youtube, sleep_override or None)
    async def lane_captions(
        self, session: aiohttp.ClientSession
    ) -> Tuple[bool, Optional[float]]:
        from scripts import fetch_youtube_transcripts as fetch

        pages = await fetch._get_wanted(session)
        page = pick_caption_page(
            pages, self.state.data["captions_done"], self.state.data["prefer"]
        )
        if page is None:
            return False, None
        slug = page["slug"]
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
            if t[1] not in fed
        ]
        if not todo:
            return False, None
        line, url, src = todo[0]
        if self.dry_run:
            result = f"[DRY-RUN] would feed {url}"
        else:
            result = await feed._push_if_has_video(session, url, src)
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
        page = d["audio_queue"][0]
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
        d["audio_queue"].pop(0)
        d["audio_done"][page["slug"]] = status
        d["audio_block_level"] = 0
        self.state.bump("audio_done" if status == "ingested" else "audio_failed")
        logger.info(
            "audio    %-8s %s -- %s", status.upper(), page["slug"], detail[:140]
        )
        return True, None

    async def tick(self, session: aiohttp.ClientSession, status_csv: Path) -> float:
        """One scheduling step. Returns how long to sleep before the next."""
        self.state.rollover(status_csv)
        now = time.time()
        if self.state.data["blocked_until"] > now:
            return self.state.data["blocked_until"] - now
        order: List[Callable] = []
        if "captions" in self.lanes:
            order.append(self.lane_captions)
        if "feed" in self.lanes:
            order.append(self.lane_feed)
        if "audio" in self.lanes:
            order.append(self.lane_audio)
        try:
            for lane in order:
                touched, override = await lane(session)
                if override is not None:
                    return override
                if touched:
                    return self.spacing + random.uniform(0, SPACING_JITTER_SECONDS)
        finally:
            self.state.save()
        return IDLE_SLEEP_SECONDS


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


async def run(args) -> None:
    state_dir = Path(args.state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    lock = open(state_dir / "lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit(
            "another youtube_drip is already running on this machine -- one per address, see the runbook"
        )
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(state_dir / "drip.log"),
        ],
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
    )
    drip.fed_pages_csv = state_dir / "fed_pages.csv"
    drip.dead_videos_csv = state_dir / "dead_videos.csv"
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
            sleep_for = await drip.tick(session, status_csv)
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
        choices=["run", "advance"],
        help="run (default) = the drip; advance = drop fed lines from the queue file for a PR",
    )
    p.add_argument("--state-dir", default=str(DEFAULT_STATE_DIR))
    p.add_argument(
        "--lanes",
        default="captions,feed,audio",
        help="comma-separated subset of captions,feed,audio",
    )
    p.add_argument("--spacing-seconds", type=float, default=SPACING_SECONDS)
    p.add_argument("--audio-per-day", type=int, default=AUDIO_DOWNLOADS_PER_DAY)
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
