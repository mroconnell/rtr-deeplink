"""Drives POST /internal/thumbnails/backfill across the whole Archive, so
every already-archived meeting page ends up with a real `og:image` /
`VideoObject.thumbnailUrl` instead of only the ones somebody happened to
load (WO-37, the operator half of WO-28's residual).

Why a script and not a curl loop: the endpoint runs extractions *inline*
with a small `limit` on purpose (each item is one `ffprobe` plus one
`ffmpeg` against a government CDN), so clearing the backlog by hand is
hundreds of identical calls with no record of what already happened. A
real dry run on 2026-08-21 measured that backlog at **1705 pages**, not
the ~1200 the WO-28 residual estimated, and confirmed the underlying path
works in production -- `GET /api/health` reports a real `ffmpeg` version
on the Archive service, and a cold page gains a real ~57KB
`/m/{slug}/card.jpg` after one view -- so what was missing was only
something to reach the pages nobody views.

**The load problem, which is the reason this script is shaped the way it
is.** 1011 of those 1705 pages (59%) live on
`archive-stream.granicus.com` -- the exact host the transcription workers
already pull from continuously, and already fail against with `ffmpeg
timed out after 120s (source likely slow or rate-limited)` (BACKLOG.md).
The workers are never quiet, so a sweep that walks the queue newest-first
would spend most of an unbroken run hammering that one host alongside
them. Two mechanisms avoid that:

* **Proportional interleaving** (`interleave_by_host()`). The whole
  backlog is planned up front and reordered so each media host's pages
  are spread evenly across the *entire* run: host `h` with `n` of `N`
  pages gets its `i`-th page placed at position `(i + 0.5) * N / n`.
  Plain round-robin was rejected on purpose -- it exhausts the small
  hosts first and then degenerates into exactly the unbroken Granicus
  tail this exists to prevent. Proportional placement keeps a Granicus
  page landing roughly every 1.7 slots from the first page to the last,
  and keeps the other hosts' work available to fill Granicus's cooldowns
  the whole way through rather than only at the start.
* **Per-host cooldowns**, defaulting to 10s and to 30s for Granicus
  (`--host-cooldown` / `--granicus-cooldown`). A single global `--sleep`
  would punish every host for one host's limits; a per-host floor paces
  the host that needs it and lets the rest proceed. Enforced at batch
  composition, since the endpoint extracts a batch back-to-back with no
  pacing of its own: **at most one page per host per batch**, and a host
  only enters a batch once its cooldown has elapsed. The pacing key is
  the registrable-ish domain, not the full hostname, so ~100 per-city
  `*.cablecast.tv` subdomains are one provider's lane rather than 100
  free passes -- and `archive-stream`/`archive-video.granicus.com` share
  one budget.

The result is a run paced by its largest host: 1016 Granicus pages at one
per 30s is ~8.5 hours, and the other ~690 pages fit inside that window
for free. That is deliberate, and Ryan's explicit call -- a slower sweep
that leaves the workers alone beats a fast one that fights them.

**Resumability.** `crud.list_pages_missing_default_thumbnail()` only ever
returns pages with no default frame, so a page extracted successfully
simply leaves the queue: a restart re-surveys and never redoes finished
work. A page whose extraction *fails* leaves no trace in the database
(the only record is `video_thumbnail._failed_at`, an in-process dict with
a 6h cooldown that dies with the dyno), so those are remembered locally
instead -- see `State` -- and excluded from the next run's plan. That
matters for cost, not just tidiness: `extract_and_store()` runs
`probe_duration()` *before* it checks that cooldown, so re-attempting a
dead source costs a fresh `ffprobe` (up to a 120s timeout) every time.

**Failure detail (WO-42).** The endpoint now reports *why* each page
produced no frame, not just that it didn't: `reason` (straight from
ffmpeg where that is the cause -- `ffmpeg timed out after 45s`, a
non-zero exit with the CDN's own `Server returned 404` in the stderr
tail) and `skipped`. This closes the residual WO-37 left open on
purpose, and the trigger it named was met: the first production sweep
finished 2026-08-22 at 973/1152 pages, leaving 179 failures whose only
grouping was by media host -- enough to see *which* CDN was unhappy,
never enough to see whether that was a rate limit, a dead link, or an
offset past the end of the video.

Both groupings are printed, since they answer different questions: by
host, and by `reason_bucket()` with one real example per bucket.
Bucketing is necessary rather than tidy -- a raw reason carries 300
characters of ffmpeg stderr including the media URL, so counting them
unbucketed turns 179 failures into 179 groups of one.

`skipped` is kept strictly apart from failure everywhere below. A skip
means the Archive attempted nothing at all (the frame was already in
flight, inside its 6h failure cooldown, or the queue was full), so those
slugs are *not* written to the state file -- recording one would
blacklist a page that was never tried. Against an Archive older than
WO-42 both fields are simply absent and every failure buckets as
`(no reason reported ...)`, which is a legible outcome rather than a
crash.

Usage (from the repo root, with the venv active, ARCHIVE_BASE_URL/
ARCHIVE_INGEST_TOKEN set in .env):

    # read-only: how big is the backlog, which hosts, how long will it take
    python scripts/backfill_meeting_cards.py

    # the real sweep -- resumable, safe to Ctrl-C and re-run
    python scripts/backfill_meeting_cards.py --apply

    # a bounded first taste before committing to the whole thing
    python scripts/backfill_meeting_cards.py --apply --max-batches 3

Dry run is the default, matching the endpoint's own `dry_run=true`
default and this repo's read-only-first posture (see
scripts/backfill_jurisdiction_bleed.py). The token is read from the
environment and only ever placed in an Authorization header -- never
logged, never echoed, per CLAUDE.md.
"""

import argparse
import asyncio
import json
import logging
import math
import os
import re
import sys
import time
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlsplit

import aiohttp
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent

# Small on purpose. The endpoint's own loop is *sequential* (one
# `await extract_and_store()` per candidate), so a batch costs the sum of
# its pages, not the max: measured during WO-28 that's ~4s for a healthy
# source (3.1s ffprobe + 0.7-0.9s ffmpeg on the real San Carlos mp4) but
# up to 165s for a stubborn one (120s ffprobe timeout + 45s ffmpeg
# timeout). Five keeps a bad batch's worst case inside a timeout a client
# can plausibly hold open; fifty does not. It is also an upper bound, not
# a target -- a batch never holds two pages from the same host.
DEFAULT_BATCH_SIZE = 5
# Floor between batches, on top of the per-host cooldowns below. Small,
# because the per-host budgets do the real pacing now.
DEFAULT_SLEEP_SECONDS = 5.0
# No single media host gets hit more often than this.
DEFAULT_HOST_COOLDOWN_SECONDS = 10.0
# Granicus gets its own, longer budget: the transcription workers pull
# from it continuously and already hit "ffmpeg timed out after 120s
# (source likely slow or rate-limited)" without any help from us. One
# request per 30s is a rounding error next to a worker chunk fetch, and
# it is what sets this sweep's wall clock (1016 pages -> ~8.5h).
DEFAULT_GRANICUS_COOLDOWN_SECONDS = 30.0
GRANICUS_PACING_KEY = "granicus.com"
# Scaled per page rather than fixed, so raising --batch-size doesn't
# silently start abandoning batches the Archive is still working through.
# 180s covers one page's own worst case (165s) with room to spare.
BATCH_TIMEOUT_PER_PAGE_SECONDS = 180
BATCH_TIMEOUT_FLOOR_SECONDS = 60
# The survey call is one indexed DB query; only a Render cold start makes
# it slow.
PROBE_TIMEOUT_SECONDS = 90
# Ceiling for the survey's `limit`. Comfortably above the 1705 pages the
# real Archive reported on 2026-08-21, so the backlog this prints is a
# real total rather than a truncated one.
SURVEY_LIMIT = 20000
# Consecutive batch-level (HTTP/network) failures before giving up. A
# single Granicus timeout is routine; three failed *calls* in a row means
# the Archive itself is unhappy and hammering it further is wrong.
MAX_CONSECUTIVE_ERRORS = 3
RETRY_DELAY_SECONDS = 30.0
# Per-page extraction cost used only for the survey's projection, both
# ends measured or bounded rather than guessed: 4s is WO-28's real
# healthy-source timing, 30s is a pessimistic mixed rate well short of
# the 165s worst case.
FAST_PAGE_SECONDS = 4.0
SLOW_PAGE_SECONDS = 30.0

DEFAULT_STATE_FILE = REPO_ROOT / "scripts" / "meeting_card_backfill_state.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
    force=True,
)
logger = logging.getLogger("rtr_backfill_meeting_cards")


def _base_url() -> str:
    return os.environ.get("ARCHIVE_BASE_URL", "").rstrip("/")


def _headers() -> dict:
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


# --- hosts, lanes and ordering (pure, unit-tested) -----------------------


def media_host(video_url: Optional[str]) -> str:
    """Hostname of a media URL, for *reporting*. Never raises -- a
    malformed stored video_url is exactly the kind of row this sweep runs
    into."""
    if not video_url:
        return "(none)"
    try:
        return urlsplit(video_url).hostname or "(unparseable)"
    except ValueError:
        return "(unparseable)"


def pacing_key(host: str) -> str:
    """The unit that gets rate-limited: the registrable-ish domain, not
    the full hostname.

    Deliberate, and it changes real behaviour in both directions. The
    Archive's backlog contains ~100 distinct per-city `*.cablecast.tv`
    subdomains that are one provider's infrastructure -- pacing them
    separately would be ~100 lanes each free to fire at will. It also
    puts `archive-stream.granicus.com` and `archive-video.granicus.com`
    on a single shared budget, which is the point: they are the same
    upstream the transcription workers are already straining.
    """
    parts = [p for p in host.split(".") if p]
    if len(parts) < 2:
        return host
    return ".".join(parts[-2:])


def cooldown_seconds(
    key: str, *, default_seconds: float, granicus_seconds: float
) -> float:
    return granicus_seconds if key == GRANICUS_PACING_KEY else default_seconds


# --- why a page failed (pure, unit-tested) -------------------------------

# What an Archive older than WO-42 reports: `offset_seconds: null` and
# nothing else. Kept as a real bucket rather than crashing, because this
# script is routinely pointed at a deployed Archive it did not ship with.
REASON_UNREPORTED = "(no reason reported -- Archive predates WO-42)"
# ffmpeg puts the media host's status on stderr twice, in two shapes:
# `[http @ ...] HTTP error 403 Forbidden` and `Error opening input:
# Server returned 403 Forbidden (access denied)`. Both are matched
# because extract_frame() only keeps the last 300 characters of stderr,
# and which of the two survives that window depends on how long the
# media URL is. Verified against real ffmpeg 8.1.2 (2026-08-22) driven
# at a local server returning each status -- 5xx really does come back
# as the literal `5XX`, with no specific code, which is why the pattern
# accepts it.
_HTTP_STATUS_RE = re.compile(r"(?:HTTP error|Server returned)\s+(\d{3}|5XX)")
_EXIT_CODE_RE = re.compile(r"^ffmpeg exited (-?\d+)")
# Deliberately matched by substring rather than imported from
# archive.utils.video_thumbnail: this script drives a *remote* Archive
# over HTTP, which may be running a different build than the checkout it
# is launched from, so the strings are wire format, not a shared symbol.
_MARKERS: tuple[tuple[str, str], ...] = (
    ("skipped: extraction queue full", "skipped: extraction queue full"),
    ("ffmpeg not found on PATH", "ffmpeg not found on PATH"),
    ("ffmpeg could not be started", "ffmpeg could not be started"),
    # WO-85: video_thumbnail.SKIP_NO_VIDEO_STREAM (a re-attempt that
    # short-circuited on the persisted marker) and
    # FAIL_NO_VIDEO_STREAM_CONFIRMED (the attempt that just discovered
    # it) share this substring on purpose -- both mean the same real
    # fact, "this page can never get a thumbnail," and should count
    # together, not split into two buckets an operator has to know are
    # the same thing.
    (
        "no video stream (confirmed audio-only source)",
        "audio-only source, no video stream",
    ),
    ("timed out after", "ffmpeg timed out"),
    ("Connection refused", "ffmpeg: connection refused"),
    ("Invalid data found", "ffmpeg: invalid data (input not decodable)"),
    ("storage rejected the frame", "storage rejected the frame"),
)


def reason_bucket(reason: Optional[str]) -> str:
    """Collapse one page's failure reason to a stable label worth
    counting.

    The reasons themselves carry a 300-character tail of ffmpeg's stderr,
    complete with the media URL and a per-run memory address, so grouping
    on them raw turns 179 failures into 179 groups of one -- useless at
    exactly the moment the grouping is wanted. This keeps the part that
    is the same across pages ("HTTP 403", "timed out") and drops the part
    that never is. The full reason is still logged per page and stored
    per slug in the state file; this only drives the counts.

    Never raises and never returns an empty string -- an unrecognised
    reason keeps its own first line, truncated, rather than being binned
    as "other", so a new failure mode shows up as itself instead of
    disappearing into a catch-all.
    """
    if not reason:
        return REASON_UNREPORTED
    first_line = reason.splitlines()[0].strip() if reason.strip() else reason
    # Handled before _MARKERS on purpose. This reason now carries a tail
    # of ffmpeg's own stderr (2026-08-22), and that tail is the whole
    # point of it -- a plain "wrote no frame" marker match would run
    # before the HTTP-status check below and bury a 403/404 that the
    # stderr had just revealed. So the underlying cause wins the label
    # when there is one, and the bare form is only the fallback.
    if "wrote no frame" in reason:
        status = _HTTP_STATUS_RE.search(reason)
        if status:
            return f"ffmpeg wrote no frame (HTTP {status.group(1)})"
        if "Invalid data found" in reason:
            return "ffmpeg wrote no frame (invalid data)"
        if "no stderr" in reason:
            return "ffmpeg wrote no frame, no stderr"
        return "ffmpeg wrote no frame despite exit 0"
    for marker, label in _MARKERS:
        if marker in reason:
            return label
    status = _HTTP_STATUS_RE.search(reason)
    if status:
        return f"ffmpeg: HTTP {status.group(1)} from the media host"
    if reason.startswith("skipped:"):
        return first_line
    if reason.startswith("extraction raised "):
        # "extraction raised TimeoutError: ..." -> the exception type.
        return "extraction raised " + reason.split(" ", 2)[2].split(":", 1)[0]
    exited = _EXIT_CODE_RE.match(reason)
    if exited:
        return f"ffmpeg exited {exited.group(1)} (see the full reason)"
    return first_line[:80]


# How much of a raw reason a per-page log line carries. Long enough for
# ffmpeg's own error sentence, short enough that a batch of five failures
# is still readable at a glance.
_REASON_LOG_CHARS = 200


def _short_reason(reason: Optional[str]) -> str:
    if not reason:
        return REASON_UNREPORTED
    collapsed = " ".join(reason.split())
    if len(collapsed) <= _REASON_LOG_CHARS:
        return collapsed
    return collapsed[:_REASON_LOG_CHARS] + " ..."


def host_breakdown(candidates: list[dict]) -> Counter:
    return Counter(media_host(c.get("video_url")) for c in candidates)


def lane_breakdown(candidates: list[dict]) -> Counter:
    return Counter(pacing_key(media_host(c.get("video_url"))) for c in candidates)


def interleave_by_host(candidates: list[dict]) -> list[dict]:
    """Reorder the backlog so every host's pages are spread evenly across
    the whole run, and annotate each entry with its `host` and `lane`.

    Proportional, not round-robin. Round-robin (one from each host in
    turn) drains the small hosts first and then degenerates into an
    unbroken run of whatever host is biggest -- with 59% of this backlog
    on Granicus that would mean the last ~700 pages are pure Granicus,
    which is precisely the load pattern this ordering exists to avoid.
    Placing host `h`'s `i`-th page at `(i + 0.5) * N / n_h` instead gives
    every host a constant stride over the *entire* list: Granicus lands
    every ~1.7 slots start to finish, and the smaller hosts stay
    available to fill Granicus's cooldown gaps right to the end.

    Input order is preserved within a host (the Archive returns
    newest-first, which is the right tiebreak: a recently archived page
    is the one most likely to be shared or crawled next).
    """
    groups: "OrderedDict[str, list[dict]]" = OrderedDict()
    annotated = []
    for candidate in candidates:
        host = media_host(candidate.get("video_url"))
        entry = dict(candidate, host=host, lane=pacing_key(host))
        annotated.append(entry)
        groups.setdefault(entry["lane"], []).append(entry)

    total = len(annotated)
    if not total:
        return []

    placed = []
    for lane, items in groups.items():
        stride = total / len(items)
        for index, item in enumerate(items):
            # Lane name breaks ties so the plan is deterministic run to
            # run -- a resumed sweep should pick the same order.
            placed.append(((index + 0.5) * stride, lane, item))
    placed.sort(key=lambda entry: (entry[0], entry[1]))
    return [entry[2] for entry in placed]


def plan_batch(
    pending: list[dict],
    *,
    last_hit: dict,
    now: float,
    batch_size: int,
    cooldown_for: Callable[[str], float],
) -> tuple[list[dict], float]:
    """Pick the next batch out of the plan, and say how long to wait if
    nothing is eligible yet.

    Two rules, both about the fact that the endpoint extracts a batch
    back-to-back with no pacing of its own: **one page per lane per
    batch**, and a lane only qualifies once its cooldown has elapsed.
    Together they mean a lane's real request rate is bounded by its
    cooldown no matter how the batches fall.

    Returns `(batch, wait_seconds)`. An empty batch with a positive wait
    means "everything left is cooling down"; an empty batch with zero
    wait means the plan is finished.
    """
    batch: list[dict] = []
    claimed: set = set()
    ready_at_earliest: Optional[float] = None

    for item in pending:
        lane = item["lane"]
        if lane in claimed:
            continue
        ready_at = last_hit.get(lane, float("-inf")) + cooldown_for(lane)
        if ready_at > now:
            if ready_at_earliest is None or ready_at < ready_at_earliest:
                ready_at_earliest = ready_at
            continue
        batch.append(item)
        claimed.add(lane)
        if len(batch) >= batch_size:
            break

    if batch:
        return batch, 0.0
    if ready_at_earliest is None:
        return [], 0.0
    return [], max(0.0, ready_at_earliest - now)


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def estimate_remaining(
    *, elapsed_seconds: float, done: int, remaining: int
) -> Optional[str]:
    """ETA from *observed* throughput, not from a guessed per-page cost --
    real extraction time varies by an order of magnitude between a fast
    mp4 and a Granicus source about to time out, so anything else would
    be fiction. None until there's something real to divide by."""
    if done <= 0 or elapsed_seconds <= 0 or remaining <= 0:
        return None
    return format_duration(elapsed_seconds / done * remaining)


def projected_seconds(
    lanes: Counter,
    *,
    batch_size: int,
    sleep_seconds: float,
    cooldown_for: Callable[[str], float],
    page_seconds: float,
) -> float:
    """Lower bound on a full run, from the two things that actually
    constrain it: the busiest lane's own cooldown budget, and raw batch
    throughput. The first dominates by a mile at Granicus's share of this
    backlog, which is exactly the trade being made."""
    if not lanes:
        return 0.0
    slowest_lane = max(
        (count - 1) * cooldown_for(lane) for lane, count in lanes.items()
    )
    total = sum(lanes.values())
    batches = math.ceil(total / max(1, batch_size))
    throughput = batches * (batch_size * page_seconds + sleep_seconds)
    return max(slowest_lane, throughput)


# --- resume state --------------------------------------------------------


class State:
    """What survives a Ctrl-C. Deliberately tiny: which slugs are known
    stuck (so a restart doesn't re-`ffprobe` the same dead sources) plus
    running totals for the closing report. Everything else -- what's left
    to do -- is re-read from the Archive each run, because the Archive is
    the truth and a stale local worklist is how a resumable script
    silently skips pages."""

    VERSION = 1

    def __init__(self, path: Path, base_url: str):
        self.path = path
        self.base_url = base_url
        self.failed: dict[str, dict] = {}
        self.stored_total = 0
        self.attempted_total = 0

    @classmethod
    def load(cls, path: Path, base_url: str) -> "State":
        state = cls(path, base_url)
        if not path.exists():
            return state
        try:
            raw = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("Ignoring unreadable state file %s: %s", path, e)
            return state
        if raw.get("version") != cls.VERSION:
            logger.warning("Ignoring state file %s (unknown version).", path)
            return state
        if raw.get("base_url") and raw["base_url"] != base_url:
            # Guard, not paranoia: slugs from a staging Archive would
            # silently mark real production pages as stuck.
            logger.warning(
                "Ignoring state file %s -- it was written against %s, not %s.",
                path,
                raw["base_url"],
                base_url,
            )
            return state
        state.failed = dict(raw.get("failed") or {})
        state.stored_total = int(raw.get("stored_total") or 0)
        state.attempted_total = int(raw.get("attempted_total") or 0)
        return state

    def save(self) -> None:
        payload = {
            "version": self.VERSION,
            "base_url": self.base_url,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "stored_total": self.stored_total,
            "attempted_total": self.attempted_total,
            "failed": self.failed,
        }
        try:
            self.path.write_text(json.dumps(payload, indent=2) + "\n")
        except OSError as e:
            logger.warning("Could not write state file %s: %s", self.path, e)

    def record_failure(
        self, slug: str, video_url: Optional[str], reason: Optional[str] = None
    ) -> None:
        """Remember a page whose extraction was really attempted and
        failed. **Never call this for a *skipped* page** -- a skip means
        the Archive did no work at all (see FrameOutcome), so recording
        it here would blacklist a page that was never tried.

        Both the raw reason and its bucket are kept: the bucket is what
        the closing report counts, the raw reason is what someone reads
        when one page is worth chasing individually.
        """
        entry = self.failed.setdefault(
            slug, {"video_url": video_url, "attempts": 0, "host": media_host(video_url)}
        )
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        entry["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        entry["reason"] = reason
        entry["reason_bucket"] = reason_bucket(reason)

    def record_success(self, slug: str) -> None:
        # A slug that failed on an earlier run and succeeded now must stop
        # being skipped.
        self.failed.pop(slug, None)


# --- HTTP ----------------------------------------------------------------


async def survey_candidates(session: aiohttp.ClientSession) -> list[dict]:
    """The whole pending queue, read-only. One indexed query Archive-side
    -- cheap enough to re-run at the start and end of a sweep."""
    async with session.post(
        f"{_base_url()}/internal/thumbnails/backfill",
        params={"limit": str(SURVEY_LIMIT), "dry_run": "true"},
        headers=_headers(),
        timeout=aiohttp.ClientTimeout(total=PROBE_TIMEOUT_SECONDS),
    ) as response:
        body = await response.text()
        if response.status != 200:
            raise RuntimeError(f"survey failed ({response.status}): {body[:300]}")
        return json.loads(body).get("candidates", [])


async def run_batch(session: aiohttp.ClientSession, *, slugs: list[str]) -> dict:
    """Extract exactly these pages, in this order. Slow by nature -- every
    item shells out to ffprobe and ffmpeg inline before the response comes
    back."""
    params = [("dry_run", "false")] + [("slugs", slug) for slug in slugs]
    async with session.post(
        f"{_base_url()}/internal/thumbnails/backfill",
        params=params,
        headers=_headers(),
        timeout=aiohttp.ClientTimeout(
            total=BATCH_TIMEOUT_FLOOR_SECONDS
            + len(slugs) * BATCH_TIMEOUT_PER_PAGE_SECONDS
        ),
    ) as response:
        body = await response.text()
        if response.status != 200:
            raise RuntimeError(f"backfill failed ({response.status}): {body[:300]}")
        return json.loads(body)


# --- the two modes -------------------------------------------------------


def _cooldown_lookup(args) -> Callable[[str], float]:
    def _for(lane: str) -> float:
        return cooldown_seconds(
            lane,
            default_seconds=args.host_cooldown,
            granicus_seconds=args.granicus_cooldown,
        )

    return _for


def _restrict_to_slugs(candidates: list[dict], args) -> list[dict]:
    """Narrow the surveyed backlog to --slugs-file, if given.

    Filters the *survey* rather than asking the Archive for those slugs
    directly, on purpose: a slug that already got a card since the file
    was written simply is not in the survey any more, so it is dropped
    instead of being re-extracted. Names that match nothing are reported
    rather than silently ignored -- a typo in a hand-built list should
    not look like a clean run over zero pages.
    """
    if not getattr(args, "slugs_file", None):
        return candidates
    wanted = {
        line.strip()
        for line in args.slugs_file.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    kept = [c for c in candidates if c["slug"] in wanted]
    missing = wanted - {c["slug"] for c in kept}
    logger.info(
        "--slugs-file %s: %d name(s) requested, %d still need a card.",
        args.slugs_file,
        len(wanted),
        len(kept),
    )
    if missing:
        logger.info(
            "  %d requested slug(s) are not in the backlog (already carded, "
            "or not a candidate): %s%s",
            len(missing),
            ", ".join(sorted(missing)[:5]),
            " ..." if len(missing) > 5 else "",
        )
    return kept


async def survey(session: aiohttp.ClientSession, *, args) -> list[dict]:
    """Read-only: the real backlog, what it's made of, and what a real run
    would cost."""
    logger.info("Surveying %s ...", _base_url())
    candidates = _restrict_to_slugs(await survey_candidates(session), args)
    total = len(candidates)
    logger.info("%s page(s) have an extractable video and no card yet.", total)
    if not total:
        logger.info("Nothing to back-fill. Done.")
        return candidates

    logger.info("By media host (top 15):")
    for host, count in host_breakdown(candidates).most_common(15):
        logger.info("  %6d  %s", count, host)

    cooldown_for = _cooldown_lookup(args)
    lanes = lane_breakdown(candidates)
    logger.info("Pacing lanes (one page per lane per batch, min gap each):")
    for lane, count in lanes.most_common():
        logger.info("  %6d  %-24s every %ss", count, lane, cooldown_for(lane))

    plan = interleave_by_host(candidates)
    logger.info(
        "Interleaved plan: %s in the first 20 slots are %s, %s in the last 20 "
        "-- spread across the whole run, not front-loaded.",
        sum(1 for p in plan[:20] if p["lane"] == GRANICUS_PACING_KEY),
        GRANICUS_PACING_KEY,
        sum(1 for p in plan[-20:] if p["lane"] == GRANICUS_PACING_KEY),
    )

    fast = projected_seconds(
        lanes,
        batch_size=args.batch_size,
        sleep_seconds=args.sleep_seconds,
        cooldown_for=cooldown_for,
        page_seconds=FAST_PAGE_SECONDS,
    )
    slow = projected_seconds(
        lanes,
        batch_size=args.batch_size,
        sleep_seconds=args.sleep_seconds,
        cooldown_for=cooldown_for,
        page_seconds=SLOW_PAGE_SECONDS,
    )
    logger.info(
        "Projected wall clock: ~%s if sources behave, ~%s if many are slow. "
        "The floor is set by the busiest lane's own cooldown, deliberately -- "
        "trust the live ETA this prints after the first few batches.",
        format_duration(fast),
        format_duration(slow),
    )
    logger.info("Re-run with --apply to do it for real.")
    return candidates


async def sweep(session: aiohttp.ClientSession, *, args, state: State) -> int:
    """The real sweep. Returns a process exit code."""
    cooldown_for = _cooldown_lookup(args)
    candidates = _restrict_to_slugs(await survey_candidates(session), args)
    pending = [
        c for c in interleave_by_host(candidates) if c["slug"] not in state.failed
    ]
    logger.info(
        "Starting: %s page(s) currently without a card, %s already known stuck "
        "from an earlier run -> %s to attempt, interleaved across %s pacing lane(s).",
        len(candidates),
        len(state.failed),
        len(pending),
        len(lane_breakdown(candidates)),
    )

    started = time.monotonic()
    last_hit: dict = {}
    batches_run = 0
    stored_run = 0
    attempted_run = 0
    skipped_run = 0
    consecutive_errors = 0

    try:
        while pending and (args.max_batches is None or batches_run < args.max_batches):
            batch, wait = plan_batch(
                pending,
                last_hit=last_hit,
                now=time.monotonic(),
                batch_size=args.batch_size,
                cooldown_for=cooldown_for,
            )
            if not batch:
                if wait <= 0:
                    break
                logger.info(
                    "All %s remaining page(s) are cooling down -- waiting %s.",
                    len(pending),
                    format_duration(wait),
                )
                await asyncio.sleep(wait)
                continue

            batches_run += 1
            requested = [item["slug"] for item in batch]
            logger.info(
                "Batch %s: %s page(s) across %s -- %s ...",
                batches_run,
                len(batch),
                ", ".join(sorted({item["lane"] for item in batch})),
                requested[0],
            )
            batch_started = time.monotonic()
            try:
                result = await run_batch(session, slugs=requested)
            except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as e:
                consecutive_errors += 1
                logger.error(
                    "Batch %s failed (%s/%s consecutive): %s",
                    batches_run,
                    consecutive_errors,
                    MAX_CONSECUTIVE_ERRORS,
                    str(e)[:300],
                )
                # The lanes were still touched -- a request that timed out
                # mid-extraction hit the CDN just as hard as one that
                # succeeded, so they must still cool down.
                for item in batch:
                    last_hit[item["lane"]] = time.monotonic()
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.error(
                        "Giving up after %s consecutive batch failures. Nothing "
                        "is lost -- pages already extracted have left the queue; "
                        "re-run the same command to resume.",
                        consecutive_errors,
                    )
                    return 1
                await asyncio.sleep(RETRY_DELAY_SECONDS)
                continue

            consecutive_errors = 0
            for item in batch:
                last_hit[item["lane"]] = time.monotonic()

            results = result.get("results", [])
            returned = {r.get("slug") for r in results}
            if not returned <= set(requested):
                # The Archive extracted pages we did not ask for, which
                # means it dropped the `slugs` parameter -- exactly what a
                # build older than WO-37 does, since FastAPI silently
                # ignores unknown query params. Every pacing guarantee
                # above depends on choosing the pages, so this cannot be
                # allowed to continue.
                logger.error(
                    "The Archive at %s ignored the `slugs` parameter on "
                    "/internal/thumbnails/backfill -- it is running a build "
                    "older than WO-37, and this sweep's host pacing would be "
                    "meaningless against it. Stopping; wait for the deploy and "
                    "re-run.",
                    _base_url(),
                )
                return 1

            by_slug = {item["slug"]: item for item in batch}
            stored, failed, skipped = [], [], []
            for entry in results:
                slug = entry.get("slug")
                video_url = entry.get("video_url") or by_slug.get(slug, {}).get(
                    "video_url"
                )
                reason = entry.get("reason")
                if entry.get("offset_seconds") is not None:
                    stored.append(slug)
                    state.record_success(slug)
                elif entry.get("skipped"):
                    # Nothing was attempted against the source (WO-42):
                    # the Archive had this frame in flight, inside its 6h
                    # failure cooldown, or its queue was full. Left out of
                    # `state.failed` on purpose -- a skip is no evidence
                    # the page is stuck, and blacklisting it here would
                    # keep a perfectly good page out of every later plan.
                    # It stays in the Archive's candidate queue, so the
                    # next run's survey picks it up again.
                    skipped.append((slug, video_url, reason))
                else:
                    failed.append((slug, video_url, reason))
                    state.record_failure(slug, video_url, reason)

            # A requested slug the Archive didn't return got a card some
            # other way between the survey and now (a real visitor loaded
            # the page). Not a failure -- just already done.
            already_done = [slug for slug in requested if slug not in returned]

            pending = [item for item in pending if item["slug"] not in set(requested)]
            attempted_run += len(results)
            stored_run += len(stored)
            skipped_run += len(skipped)
            state.attempted_total += len(results)
            state.stored_total += len(stored)
            state.save()

            logger.info(
                "  attempted %s, stored %s, failed %s%s%s in %s",
                len(results),
                len(stored),
                len(failed),
                f", skipped {len(skipped)}" if skipped else "",
                f", {len(already_done)} already done" if already_done else "",
                format_duration(time.monotonic() - batch_started),
            )
            for slug, video_url, reason in failed:
                logger.warning(
                    "  no frame: %s (%s) -- %s",
                    slug,
                    media_host(video_url),
                    _short_reason(reason),
                )
            for slug, video_url, reason in skipped:
                logger.info(
                    "  not attempted: %s (%s) -- %s; it stays in the queue for "
                    "a later run",
                    slug,
                    media_host(video_url),
                    _short_reason(reason),
                )

            eta = estimate_remaining(
                elapsed_seconds=time.monotonic() - started,
                done=attempted_run,
                remaining=len(pending),
            )
            logger.info(
                "  running total: %s stored / %s attempted; %s page(s) left%s",
                stored_run,
                attempted_run,
                len(pending),
                f", ETA ~{eta}" if eta else "",
            )

            if args.sleep_seconds > 0:
                await asyncio.sleep(args.sleep_seconds)
        if pending and args.max_batches is not None:
            logger.info("Stopped after --max-batches %s.", args.max_batches)
    except (KeyboardInterrupt, asyncio.CancelledError):
        # Ctrl-C mid-batch is an expected way to run this -- the summary
        # below is the whole point, so it must not be skipped.
        logger.warning("Interrupted.")
    finally:
        state.save()
        _final_report(
            state=state,
            started=started,
            batches_run=batches_run,
            stored_run=stored_run,
            attempted_run=attempted_run,
            skipped_run=skipped_run,
            pending=len(pending),
        )
    return 0


def _final_report(
    *,
    state: State,
    started: float,
    batches_run: int,
    stored_run: int,
    attempted_run: int,
    skipped_run: int,
    pending: int,
) -> None:
    logger.info("--- run summary ---")
    logger.info(
        "%s batch(es), %s attempted, %s stored, %s failed, %s not attempted "
        "(skipped Archive-side), %s elapsed.",
        batches_run,
        attempted_run,
        stored_run,
        attempted_run - stored_run - skipped_run,
        skipped_run,
        format_duration(time.monotonic() - started),
    )
    logger.info(
        "%s page(s) of this run's plan were left unattempted. Re-running the "
        "same command resumes -- extracted pages have left the queue, and the "
        "%s known-stuck slug(s) in %s are skipped rather than re-probed.",
        pending,
        len(state.failed),
        state.path,
    )
    if state.failed:
        # Two groupings, because they answer different questions and the
        # first sweep (2026-08-22: 973/1152, 179 failures) could only ever
        # answer the host one. "Which CDN is unhappy" is the host column;
        # "is this a rate limit, a dead link, or an offset past the end of
        # the video" is the reason column, and only the second says what
        # to *do* about it.
        logger.info("Stuck pages by media host:")
        for host, count in Counter(
            entry.get("host") or "(none)" for entry in state.failed.values()
        ).most_common(10):
            logger.info("  %6d  %s", count, host)
        logger.info("Stuck pages by reason:")
        buckets = Counter(
            entry.get("reason_bucket") or reason_bucket(entry.get("reason"))
            for entry in state.failed.values()
        )
        # One real example per bucket: the bucket says what kind of
        # failure it is, the example carries the media URL and ffmpeg's
        # own words for whoever chases it.
        example_for: dict[str, str] = {}
        for slug, entry in state.failed.items():
            bucket = entry.get("reason_bucket") or reason_bucket(entry.get("reason"))
            example_for.setdefault(bucket, slug)
        for bucket, count in buckets.most_common(10):
            logger.info("  %6d  %s", count, bucket)
            example_slug = example_for.get(bucket)
            if example_slug:
                logger.info(
                    "          e.g. %s -- %s",
                    example_slug,
                    _short_reason(state.failed[example_slug].get("reason")),
                )
        logger.info(
            "Delete %s to give every stuck page another chance (worth doing "
            "once, days later -- a CDN timeout is often transient).",
            state.path,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually extract frames. Without this the script only surveys "
        "the backlog (read-only), matching the endpoint's own dry_run default.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Upper bound on pages per request (default {DEFAULT_BATCH_SIZE}). "
        "A batch never holds two pages from the same host, so the real size is "
        "however many lanes are off cooldown.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=DEFAULT_SLEEP_SECONDS,
        dest="sleep_seconds",
        help=f"Floor between batches (default {DEFAULT_SLEEP_SECONDS}s), on top "
        "of the per-host cooldowns.",
    )
    parser.add_argument(
        "--host-cooldown",
        type=float,
        default=DEFAULT_HOST_COOLDOWN_SECONDS,
        help=f"Minimum seconds between requests to any one media host "
        f"(default {DEFAULT_HOST_COOLDOWN_SECONDS}).",
    )
    parser.add_argument(
        "--granicus-cooldown",
        type=float,
        default=DEFAULT_GRANICUS_COOLDOWN_SECONDS,
        help=f"Same, for {GRANICUS_PACING_KEY} specifically (default "
        f"{DEFAULT_GRANICUS_COOLDOWN_SECONDS}). Higher because the "
        "transcription workers pull from it continuously and already hit its "
        "timeouts; this is what sets the sweep's wall clock.",
    )
    parser.add_argument(
        "--max-batches",
        type=int,
        default=None,
        help="Stop after this many batches (default: run until the plan is "
        "empty). Useful for a bounded first run.",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_STATE_FILE,
        help=f"Where the known-stuck slugs are remembered (default {DEFAULT_STATE_FILE}).",
    )
    parser.add_argument(
        "--slugs-file",
        type=Path,
        default=None,
        help="Attempt only the slugs listed in this file, one per line "
        "(blank lines and '#' comments ignored). Still surveyed, paced "
        "and state-tracked exactly like a full run -- this narrows WHICH "
        "pages, never how hard they are hit. For re-testing one platform "
        "after a fix without touching the rest of the backlog.",
    )
    parser.add_argument(
        "--reset-state",
        action="store_true",
        help="Forget previously-stuck pages and retry every one of them.",
    )
    return parser


async def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if not _base_url():
        logger.error("ARCHIVE_BASE_URL is not set (check the repo's .env). Stopping.")
        return 1
    if not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        logger.error(
            "ARCHIVE_INGEST_TOKEN is not set (check the repo's .env). Stopping."
        )
        return 1
    if args.batch_size < 1:
        logger.error("--batch-size must be at least 1.")
        return 1

    if args.reset_state and args.state_file.exists():
        args.state_file.unlink()
        logger.info(
            "Cleared %s -- every previously-stuck page gets another try.",
            args.state_file,
        )

    async with aiohttp.ClientSession() as session:
        if not args.apply:
            await survey(session, args=args)
            return 0
        state = State.load(args.state_file, _base_url())
        return await sweep(session, args=args, state=state)


if __name__ == "__main__":
    # Deliberately not called at module level -- same reasoning as
    # scripts/send_search_alerts.py's matching comment.
    load_dotenv()
    sys.exit(asyncio.run(main()))
