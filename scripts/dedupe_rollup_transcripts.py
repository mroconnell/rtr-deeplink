"""Finds Archive pages whose *stored* transcript still holds WO-34's
duplicated roll-up ("scrolling ticker") caption text, re-resolves them, and
writes the deduped transcript back as the page's new default version.

Why this exists. `dedupe_rollup_cues()` (app/utils/vtt_parser.py) shipped
2026-08-21 and runs on every *fresh* resolve, but nothing re-checks an
already-archived page on its own -- existing `TranscriptVersion` rows were
never touched, so every page ingested before that date still serves the
duplicated text. Confirmed live 2026-08-22 on the page BACKLOG.md names,
`/m/city-of-tacoma-wa-2026-01-06-city-council-on-2026-01-06-5-00-pm`: its
stored transcript is still 21,240 segments / 859K characters of ticker
fragments ("`>> Councilmember Hines: WE`" / "`... WE WILL`" / "`... WE WILL
GET`"), where today's parser produces 1,168 real segments / 100K characters.
This is the write-path half of WO-34, deliberately left out of that parser
change (BACKLOG.md's "[JUST-DO-IT] Every Archive page ingested before
WO-34" entry).

--------------------------------------------------------------------------
CANDIDATE SELECTION -- deliberately never a full-corpus scan
--------------------------------------------------------------------------
This script issues **no SQL at all**; every read is an HTTP call to the
Archive's own API, and no call ever aggregates or filters over the
`segments` blob server-side. (BACKLOG.md's standing decision: four
hand-written analytics queries over `segments` ran 50-62s each against
production on 2026-08-17 and saturated I/O during live `/meetings` search.
Nothing here can reproduce that.) Three narrowing stages instead:

1. **Page list, one cheap query.** `GET /internal/pages/all-urls` reads
   `meeting_pages` only -- slug, title, platform, source URL, created_at --
   and never joins or touches `transcript_versions`. It is the same call
   scripts/backfill_archived_pages.py already makes.

2. **Platform + ingest-date bound, applied client-side.** WO-34 confirmed
   exactly four platforms serve roll-up captions -- Granicus, CivicClerk,
   eScribe and YouTube -- each with a structurally different cue shape (see
   BACKLOG_DONE.md's WO-34 entry). Filtering on the *stored* `platform`
   field is what makes this correct for wrappers too: a Legistar or
   CivicPlus page stores `granicus` and a PrimeGov or Chicago-ELMS page
   stores `youtube`, because MeetingPage.platform records the *delegated*
   finder's name (see backfill_archived_pages.py's own comment). Then
   `created_at < --created-before` (default 2026-08-21, WO-34's ship date):
   a page first archived after the fix shipped was necessarily parsed with
   `dedupe_rollup_cues()` in place. Both bounds are supersets, never
   guesses -- a pre-cutoff page that has since been re-resolved stays a
   candidate and gets cleared by stage 3, not skipped. Measured against the
   real production Archive on 2026-08-22: 2,389 pages total -> 1,377 on the
   four roll-up platforms.

3. **Per-page detection, one indexed single-row read each.**
   `GET /m/{slug}/transcript.srt` is the page's own public transcript
   export -- `to_srt()` over exactly the stored default version's segments,
   so it round-trips them faithfully (start/end/text). Parsed back by
   `parse_stored_srt()` below and fed to the *same* detector the WO-34 fix
   uses, `_looks_like_rollup()`. Sequential, `--probe-delay` apart, and
   hard-capped by `--limit`; a page with no transcript 404s and costs
   nothing. This is N single-page reads Ryan chooses the size of, not one
   query over every blob in the corpus.

The first real run of this, against production on 2026-08-22, took about
7 minutes end to end: 1,377 probed, **26 still holding roll-up
duplication**, 981 clean, 370 with no transcript at all, 0 probe failures.
Those 26 hold 16.3M stored characters that become 2.7M -- 83.6% of the text
on those pages is duplication.

Host-grouping was considered as a fourth narrowing stage (roll-up is a
property of how a city configures its captioning vendor, so one probe per
source host could stand in for the rest) and **rejected on measurement**:
those 1,377 candidates span 1,010 distinct source hosts, 792 of them with a
single page, so it would have saved 27% of the probes in exchange for a
whole class of false negatives.

--------------------------------------------------------------------------
WHY IT IS SAFE TO RUN -- false positives are the only real danger
--------------------------------------------------------------------------
`_looks_like_rollup()` is a heuristic. WO-34 twice measured a genuinely
broken real track *under* its threshold, so false negatives are expected
and fine -- a missed page just keeps serving what it serves today. A false
positive is the one outcome that would do damage, so `--apply` puts four
independent gates between a detection and a write:

  * the page's stored transcript must flag as roll-up (stage 3 above);
  * the fresh resolve must produce segments that do *not* flag as roll-up
    -- i.e. today's parser demonstrably fixed this track, rather than the
    detector having mis-scored an ordinary one;
  * the fresh transcript must be *smaller* than the stored one but not
    implausibly so: `--min-retained` (default 0.05, against a real measured
    minimum of 0.066 across the 26 affected pages), which catches a resolve
    that came back truncated or half-fetched;
  * after the push, the page's own transcript export is re-read and must no
    longer flag. A page that somehow still does is reported, not retried.

The dry run also splits its findings into two bands by the detector's own
score, because the first real production sweep turned up something WO-34's
18-file calibration could not have: that calibration measured every real
roll-up track at >= 0.401 and every real non-roll-up one at <= 0.048, with
nothing in between, but at corpus scale a real band sits at 0.202-0.244 --
10 of the 26 affected pages, every one a YouTube auto-caption track behind
a CivicWeb or Municode portal that emits each speaker-change line twice,
once as `>>` and once as `»` (the fold case vtt_parser's own roll-up
comment block calls out). A coherent cluster with a real, smaller defect
(they retain ~0.80 of their characters against ~0.07-0.12 for the Granicus
ticker shape), not detector noise. So both bands are rewritten by default;
the split exists so the pages outside anything WO-34 measured are the ones
a reviewer reads first, and `--min-ratio 0.40` restricts a run to the
confident band if wanted.

Nothing is ever deleted. The push creates a *new* TranscriptVersion and
promotes it; the old duplicated one stays reachable via `?version=` (see
crud.promote_transcript_version()), so any page this gets wrong is one
promote call away from being put back.

The promote step is required, not optional: `crud._is_real_improvement()`
only auto-promotes a fresh push when the current default has no segments or
no language, and a roll-up page's default has both -- so ingest alone would
file the fixed transcript as a non-default version nobody sees. Same
reasoning as scripts/transcribe_backlog_locally.py's `--promote`.

--------------------------------------------------------------------------
Usage (from the repo root, with the venv active, ARCHIVE_BASE_URL/
ARCHIVE_INGEST_TOKEN set in .env):

    # read-only: which pages are affected, with a before/after excerpt each
    python scripts/dedupe_rollup_transcripts.py

    # same, bounded, and written out for eyeballing
    python scripts/dedupe_rollup_transcripts.py --limit 50 \
        --report-file /tmp/rollup.json

    # one specific page (repeatable) -- skips the page list entirely
    python scripts/dedupe_rollup_transcripts.py \
        --slug city-of-tacoma-wa-2026-01-06-city-council-on-2026-01-06-5-00-pm

    # the real run: re-resolve + push + promote exactly the pages the
    # dry-run report flagged. Resumable, safe to Ctrl-C and re-run.
    python scripts/dedupe_rollup_transcripts.py --apply \
        --from-report scripts/rollup_dedupe_report.json

Dry run is the default, matching scripts/backfill_meeting_cards.py and
scripts/backfill_archived_pages.py and this repo's read-only-first posture.
The dry run's before/after is computed by running `dedupe_rollup_cues()`
over the *stored* segments -- which for an affected page are exactly the
raw cues the adapter stored, so it reproduces the real fix's output
(verified: the preview for Tacoma gives 21,240 -> 1,168 segments and
859K -> 100K characters, matching WO-34's own measurement of that file to
the segment). `--apply` still re-resolves the source for real rather than
trusting that preview, because the ingest payload needs the whole
ResolvedMeeting (title, jurisdiction, video URL, ...), not just segments --
and a re-resolve picks up every other since-shipped adapter fix at the same
time.

The token is read from the environment and only ever placed in an
Authorization header -- never logged, never echoed, per CLAUDE.md.
"""

import argparse
import asyncio
import json
import logging
import os
import random
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import aiohttp
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.utils.vtt_parser import (  # noqa: E402
    _is_rollup_pair,
    _looks_like_rollup,
    _rollup_lines,
    dedupe_rollup_cues,
)

# The four platforms WO-34 confirmed serve roll-up captions, each with its
# own structurally different cue shape (BACKLOG_DONE.md). These are stored
# MeetingPage.platform values, which is the *delegated* finder's name -- so
# this set also covers Legistar/CivicPlus (-> granicus) and PrimeGov/Chicago
# ELMS (-> youtube) pages without naming them.
ROLLUP_PLATFORMS = frozenset({"granicus", "civicclerk", "escribe", "youtube"})

# WO-34's ship date. A page first archived on or after this ran through
# dedupe_rollup_cues() at parse time and cannot be holding duplicated text
# from this bug.
WO34_SHIP_DATE = "2026-08-21"

# Floor on how much of the stored transcript may survive deduping. Tacoma WA
# (Granicus clip 7460) retains 0.117 of its characters, and the first real
# production sweep (2026-08-22) put the true minimum across all 26 affected
# pages at **0.066** -- Delray Beach FL and Marco Island FL, both the same
# Granicus ticker shape with a 36,000-cue stored transcript. 0.05 therefore
# sits below every real case with a small but genuine margin. It is a
# truncated-resolve tripwire, not a tuned threshold, and lowering it further
# only weakens it. Anything at or above 1.0 is also refused: a dedupe can
# only ever remove text.
DEFAULT_MIN_RETAINED = 0.05

# The detector's own gate, restated here only so `--min-ratio` has a
# meaningful default: a page below it was never flagged in the first place.
DETECTOR_GATE_RATIO = 0.20
# WO-34 measured every real roll-up track it fixed at >= 0.401 and every real
# non-roll-up one at <= 0.048, across 18 caption files from 7 platforms.
# Nothing it looked at landed in between. The first real production sweep
# (2026-08-22) found that gap is *not* empty at corpus scale -- and what sits
# in it is a coherent cluster, not noise: 10 of the 26 affected pages score
# 0.202-0.244, and every one of them is a YouTube auto-caption track behind a
# CivicWeb or Municode portal that emits each speaker-change line twice, once
# as '>>' and once as '»' (exactly the fold case vtt_parser's roll-up comment
# block calls out). They retain ~0.80 of their characters, against ~0.07-0.12
# for the Granicus ticker shape -- a different, smaller, and equally real
# defect. So this is *not* an apply threshold: it only splits the report into
# "matches a shape WO-34 measured" and "real but outside anything it
# measured, look at these first". `--min-ratio` is there if a run should be
# restricted to the confident band.
CONFIDENT_ROLLUP_RATIO = 0.40

# Politeness between probes. These are single-row reads against our own
# Archive, not government sources, so this is much smaller than
# backfill_archived_pages.py's 2.0s -- but it is not zero, because a probe
# serializes a page's whole segments blob and 1,377 of them back-to-back is
# a real burst next to live /meetings search.
DEFAULT_PROBE_DELAY_SECONDS = 0.25
# Between re-resolves in --apply. This one *does* hit a real government
# website, so it matches backfill_archived_pages.py's default exactly.
DEFAULT_RESOLVE_DELAY_SECONDS = 2.0

PROBE_TIMEOUT = aiohttp.ClientTimeout(total=120)
LIST_TIMEOUT = aiohttp.ClientTimeout(total=180)
INGEST_TIMEOUT = aiohttp.ClientTimeout(total=180)

MAX_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 2.0
RETRY_MAX_DELAY_SECONDS = 30.0
# Consecutive resolve/push failures before giving up -- same reasoning as
# backfill_meeting_cards.py's: one flaky government source is routine,
# three in a row means something systemic.
MAX_CONSECUTIVE_ERRORS = 5

# How many segments of before/after text the report carries per page. Enough
# to see the ticker pattern and the reconstructed sentence it becomes; not
# so much that a 1,000-page report is unreadable.
SAMPLE_SEGMENTS = 8

DEFAULT_REPORT_FILE = REPO_ROOT / "scripts" / "rollup_dedupe_report.json"
DEFAULT_STATE_FILE = REPO_ROOT / "scripts" / "rollup_dedupe_state.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
    force=True,
)
logger = logging.getLogger("rtr_dedupe_rollup_transcripts")


def _base_url() -> str:
    return os.environ.get("ARCHIVE_BASE_URL", "").rstrip("/")


def _headers() -> dict:
    token = os.environ.get("ARCHIVE_INGEST_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}


# --- reading a page's stored transcript back (pure, unit-tested) ----------


_SRT_TIMING_RE = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)


def _srt_seconds(hours: str, minutes: str, seconds: str, millis: str) -> float:
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000.0


def parse_stored_srt(body: str) -> list[dict]:
    """`GET /m/{slug}/transcript.srt` back into the stored segment dicts.

    Deliberately *not* app/utils/vtt_parser.py's `parse_srt()`, even though
    the input is SRT. That one routes through `parse_vtt()`, which re-runs
    `normalize_shouting_caption()`, `normalize_speaker_change_marker()` and
    `unescape_caption_entities()` -- normalizations the adapter already
    applied before these segments were stored. Re-applying them to
    already-normalized text would mean the detector is scoring something
    subtly different from what the page actually holds, and the roll-up
    detector is specifically sensitive to exactly those two rewrites (see
    the case-folding bullet in vtt_parser's roll-up comment block). This
    reader does no normalization at all: what the export says is what the
    row holds.

    Tolerant on purpose -- a malformed or truncated block is skipped rather
    than raised on, since a probe's whole job is to survive whatever a real
    row contains.
    """
    segments: list[dict] = []
    for block in re.split(r"\r?\n\s*\r?\n", body.strip()):
        lines = block.split("\n")
        offset = 1 if lines and lines[0].strip().isdigit() else 0
        if offset >= len(lines):
            continue
        match = _SRT_TIMING_RE.match(lines[offset].strip())
        if not match:
            continue
        groups = match.groups()
        segments.append(
            {
                "start": _srt_seconds(*groups[:4]),
                "end": _srt_seconds(*groups[4:]),
                "text": "\n".join(lines[offset + 1 :]).strip(),
            }
        )
    return segments


def rollup_ratio(segments: list[dict]) -> tuple[float, int]:
    """The detector's own adjacent-line overlap ratio, and the pair count it
    was measured over -- for the report only.

    `_looks_like_rollup()` returns a bare bool, but the ratio is the number
    that makes a dry run reviewable: WO-34 measured <= 0.048 on every real
    non-roll-up track and >= 0.401 on every roll-up one, so seeing where a
    flagged page actually landed is how a borderline call gets spotted.
    Reuses `_is_rollup_pair()` so this can never drift from the real gate.
    """
    previous: Optional[list[str]] = None
    pairs = hits = 0
    for _cue, line, _is_last in _rollup_lines(segments):
        words = line.split()
        if previous is not None:
            pairs += 1
            if _is_rollup_pair(previous, words):
                hits += 1
        previous = words
    return (hits / pairs if pairs else 0.0), pairs


def confidence_band(ratio: float) -> str:
    """ "matched" if this page scores inside the range WO-34 actually measured
    real roll-up tracks at, "borderline" if it is above the detector's gate
    but inside the gap WO-34's 18 files left empty. Reporting only -- both
    bands are real findings and both are rewritten by default; see
    CONFIDENT_ROLLUP_RATIO's comment for why."""
    return "matched" if ratio >= CONFIDENT_ROLLUP_RATIO else "borderline"


def looks_affected(segments: list[dict]) -> bool:
    """Does this stored transcript still hold roll-up duplication?

    The same detector the WO-34 fix gates on, fed the stored segments
    instead of freshly parsed cues -- which is exactly right, because for an
    affected page the stored segments *are* the raw cues (the adapter stored
    one segment per cue, which is the bug).
    """
    return bool(segments) and _looks_like_rollup(_rollup_lines(segments))


def total_chars(segments: list[dict]) -> int:
    return sum(len(segment.get("text") or "") for segment in segments)


def preview_dedupe(segments: list[dict]) -> list[dict]:
    """What today's parser would make of these stored segments. Honest as a
    preview because the stored segments of an affected page are the cues;
    `--apply` still re-fetches and re-parses the real source file."""
    return dedupe_rollup_cues(segments)


def retained_ratio(before: list[dict], after: list[dict]) -> float:
    before_chars = total_chars(before)
    if not before_chars:
        return 0.0
    return total_chars(after) / before_chars


def rewrite_verdict(
    *,
    stored_chars: int,
    fresh: list[dict],
    min_retained: float,
) -> tuple[bool, str]:
    """Should a freshly resolved transcript be allowed to replace a stored
    one? Returns (ok, reason). Every "no" here is a page left exactly as it
    is today -- the deliberately asymmetric trade this script is built
    around (see the module docstring's safety section).

    Takes the stored side as a character count rather than its segments
    because that is all the gate needs and all a report file carries -- the
    stored transcript itself was already read, scored and discarded during
    the probe, and re-fetching a 1.6MB export just to re-measure it would
    double this sweep's read load for nothing.
    """
    if not fresh:
        return False, "fresh resolve produced no segments"
    if looks_affected(fresh):
        ratio, _pairs = rollup_ratio(fresh)
        return (
            False,
            f"fresh resolve still scores as roll-up ({ratio:.3f}) -- today's "
            "parser did not fix this track, so the stored one is no worse",
        )
    if stored_chars <= 0:
        return False, "stored transcript had no characters to compare against"
    ratio = total_chars(fresh) / stored_chars
    if ratio >= 1.0:
        return (
            False,
            f"fresh transcript is not smaller than the stored one "
            f"({ratio:.3f} retained) -- a dedupe only ever removes text",
        )
    if ratio < min_retained:
        return (
            False,
            f"fresh transcript retains only {ratio:.3f} of the stored "
            f"characters, below --min-retained {min_retained} -- looks like a "
            "truncated or half-fetched resolve, not a dedupe",
        )
    return True, f"{ratio:.3f} of stored characters retained"


def sample_texts(segments: list[dict], count: int = SAMPLE_SEGMENTS) -> list[str]:
    return [
        (segment.get("text") or "").replace("\n", " ") for segment in segments[:count]
    ]


# --- candidate selection (pure, unit-tested) ------------------------------


def source_host(url: Optional[str]) -> str:
    if not url:
        return "(none)"
    try:
        return urlsplit(url).hostname or "(unparseable)"
    except ValueError:
        return "(unparseable)"


def select_candidates(
    pages: list[dict],
    *,
    platforms: frozenset = ROLLUP_PLATFORMS,
    created_before: Optional[str] = WO34_SHIP_DATE,
    slugs: Optional[set] = None,
    host_contains: Optional[str] = None,
) -> list[dict]:
    """Stage 2 of the selection described in the module docstring: the two
    bounds that shrink "every archived page" to "every page that could
    possibly be affected", applied to the page list in memory.

    `created_before` compares ISO strings lexicographically, which is
    correct for the ISO-8601 timestamps `list_all_page_urls()` emits and
    avoids dragging a timezone-parsing question into a filter whose whole
    job is a date-level cut. A page whose `created_at` is missing is kept:
    the bound exists to *remove* provably-unaffected pages, so an unknown
    date must never silently exclude one.

    `slugs` short-circuits both bounds -- an explicit `--slug` is a human
    naming a page on purpose, including one archived after the cutoff.
    """
    if slugs:
        return [page for page in pages if page.get("slug") in slugs]

    selected = [page for page in pages if page.get("platform") in platforms]
    if created_before:
        selected = [
            page
            for page in selected
            if not page.get("created_at") or page["created_at"] < created_before
        ]
    if host_contains:
        selected = [
            page
            for page in selected
            if host_contains in (page.get("source_url_normalized") or "")
        ]
    # Newest first: a recently archived page is the one most likely to be
    # shared, crawled or read next, so it is the one worth fixing first if a
    # run is cut short. list_all_page_urls() returns oldest-first.
    return list(reversed(selected))


# --- resume state ---------------------------------------------------------


class State:
    """What survives a Ctrl-C during `--apply`: which slugs were already
    rewritten (so a restart doesn't re-resolve them) and which failed (so a
    dead source isn't re-fetched every run). Deliberately tiny, and never
    the worklist itself -- that comes from the report or a fresh probe,
    because a stale local worklist is how a resumable script silently skips
    pages (same reasoning as backfill_meeting_cards.py's State)."""

    VERSION = 1

    def __init__(self, path: Path, base_url: str):
        self.path = path
        self.base_url = base_url
        self.applied: dict[str, dict] = {}
        self.failed: dict[str, dict] = {}

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
            # Same guard as backfill_meeting_cards.py: slugs from a staging
            # Archive must never mark real production pages as done.
            logger.warning(
                "Ignoring state file %s -- it was written against %s, not %s.",
                path,
                raw["base_url"],
                base_url,
            )
            return state
        state.applied = dict(raw.get("applied") or {})
        state.failed = dict(raw.get("failed") or {})
        return state

    def save(self) -> None:
        payload = {
            "version": self.VERSION,
            "base_url": self.base_url,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "applied": self.applied,
            "failed": self.failed,
        }
        try:
            self.path.write_text(json.dumps(payload, indent=2) + "\n")
        except OSError as e:
            logger.warning("Could not write state file %s: %s", self.path, e)

    def record_applied(self, slug: str, detail: dict) -> None:
        self.applied[slug] = dict(detail, at=time.strftime("%Y-%m-%dT%H:%M:%S"))
        self.failed.pop(slug, None)

    def record_failure(self, slug: str, reason: str) -> None:
        entry = self.failed.setdefault(slug, {"attempts": 0})
        entry["attempts"] = int(entry.get("attempts", 0)) + 1
        entry["reason"] = reason[:300]
        entry["last_seen"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    def done(self, slug: str) -> bool:
        return slug in self.applied or slug in self.failed


# --- HTTP -----------------------------------------------------------------


class _RetryableHTTPError(Exception):
    """A 5xx. Raised so it lands in the same retry path as a transport
    error -- one retry loop for both failure shapes, same reasoning as
    scripts/transcribe_backlog_locally.py's version of this."""


async def _request_json(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    *,
    label: str,
    max_retries: int = MAX_RETRIES,
    **kwargs,
) -> dict:
    last_error: Optional[Exception] = None
    for attempt in range(max_retries):
        try:
            async with session.request(method, url, **kwargs) as response:
                if response.status >= 500:
                    text = await response.text()
                    raise _RetryableHTTPError(
                        f"HTTP {response.status} for {label}: {text[:200]}"
                    )
                if response.status >= 400:
                    text = await response.text()
                    raise RuntimeError(
                        f"{label} failed ({response.status}) -- not retrying: "
                        f"{text[:300]}"
                    )
                return await response.json()
        except (_RetryableHTTPError, aiohttp.ClientError, asyncio.TimeoutError) as e:
            last_error = e
            if attempt == max_retries - 1:
                break
            delay = min(
                RETRY_MAX_DELAY_SECONDS,
                RETRY_BASE_DELAY_SECONDS * (2**attempt) * random.uniform(0.5, 1.5),
            )
            logger.warning(
                "%s failed (attempt %d/%d): %s -- retrying in %.0fs",
                label,
                attempt + 1,
                max_retries,
                str(e)[:200],
                delay,
            )
            await asyncio.sleep(delay)
    raise RuntimeError(f"{label} failed after {max_retries} attempts: {last_error}")


async def list_pages(session: aiohttp.ClientSession) -> list[dict]:
    """Stage 1: `meeting_pages` only, no segments touched anywhere."""
    data = await _request_json(
        session,
        "GET",
        f"{_base_url()}/internal/pages/all-urls",
        label="page list fetch",
        headers=_headers(),
        timeout=LIST_TIMEOUT,
    )
    return data.get("pages", [])


async def fetch_stored_transcript(
    session: aiohttp.ClientSession, slug: str
) -> Optional[list[dict]]:
    """A page's stored default transcript, via its own public export route.
    None means the page has no transcript at all (404), which is not a
    failure -- it is most of the corpus."""
    async with session.get(
        f"{_base_url()}/m/{slug}/transcript.srt",
        timeout=PROBE_TIMEOUT,
    ) as response:
        if response.status == 404:
            return None
        if response.status != 200:
            raise RuntimeError(
                f"transcript probe for {slug} failed ({response.status})"
            )
        return parse_stored_srt(await response.text())


async def push_ingest(
    session: aiohttp.ClientSession, payload: dict, input_url_normalized: str
) -> dict:
    body = dict(payload)
    body["input_url_normalized"] = input_url_normalized
    return await _request_json(
        session,
        "POST",
        f"{_base_url()}/internal/ingest",
        label=f"ingest push for {input_url_normalized}",
        json=body,
        headers=_headers(),
        timeout=INGEST_TIMEOUT,
    )


async def promote_version(
    session: aiohttp.ClientSession, slug: str, version_id: int
) -> dict:
    """Required, not optional -- see the module docstring. Never deletes the
    old version; it stays reachable via `?version=`."""
    return await _request_json(
        session,
        "POST",
        f"{_base_url()}/internal/transcript-version/promote",
        label=f"promote for {slug}",
        json={"slug": slug, "version_id": version_id},
        headers=_headers(),
        timeout=INGEST_TIMEOUT,
    )


# --- stage 3: probe ------------------------------------------------------


async def probe_pages(
    session: aiohttp.ClientSession, candidates: list[dict], *, delay: float
) -> tuple[list[dict], Counter]:
    """Read each candidate's stored transcript and score it. Returns the
    flagged findings plus a tally of every outcome, so a dry run reports
    what it *didn't* flag as well as what it did."""
    findings: list[dict] = []
    tally: Counter = Counter()

    for index, page in enumerate(candidates, 1):
        slug = page["slug"]
        try:
            stored = await fetch_stored_transcript(session, slug)
        except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as e:
            tally["probe_failed"] += 1
            logger.warning(
                "[%d/%d] %s: probe failed -- %s",
                index,
                len(candidates),
                slug,
                str(e)[:200],
            )
            continue

        if stored is None:
            tally["no_transcript"] += 1
        elif not looks_affected(stored):
            tally["clean"] += 1
        else:
            ratio, pairs = rollup_ratio(stored)
            after = preview_dedupe(stored)
            finding = {
                "slug": slug,
                "title": page.get("title"),
                "platform": page.get("platform"),
                "source_url": page.get("source_url_normalized"),
                "source_host": source_host(page.get("source_url_normalized")),
                "created_at": page.get("created_at"),
                "rollup_ratio": round(ratio, 4),
                "confidence": confidence_band(ratio),
                "compared_pairs": pairs,
                "stored_segments": len(stored),
                "stored_chars": total_chars(stored),
                "preview_segments": len(after),
                "preview_chars": total_chars(after),
                "preview_retained": round(retained_ratio(stored, after), 4),
                "before_sample": sample_texts(stored),
                "after_sample": sample_texts(after),
            }
            findings.append(finding)
            tally["affected"] += 1
            logger.info(
                "[%d/%d] %s: AFFECTED (ratio %.3f) -- %d segs / %dK chars -> "
                "%d segs / %dK chars",
                index,
                len(candidates),
                slug,
                ratio,
                finding["stored_segments"],
                finding["stored_chars"] // 1000,
                finding["preview_segments"],
                finding["preview_chars"] // 1000,
            )

        if index % 100 == 0:
            logger.info(
                "  ... %d/%d probed: %d affected, %d clean, %d without a "
                "transcript, %d probe failures",
                index,
                len(candidates),
                tally["affected"],
                tally["clean"],
                tally["no_transcript"],
                tally["probe_failed"],
            )
        if delay > 0 and index < len(candidates):
            await asyncio.sleep(delay)

    return findings, tally


def log_finding_detail(finding: dict) -> None:
    logger.info("  %s", finding["slug"])
    logger.info(
        "    %s | %s | ratio %.3f over %s pairs | archived %s",
        finding["platform"],
        finding["source_host"],
        finding["rollup_ratio"],
        finding["compared_pairs"],
        (finding.get("created_at") or "?")[:10],
    )
    logger.info(
        "    stored:  %s segments, %s chars",
        finding["stored_segments"],
        finding["stored_chars"],
    )
    logger.info(
        "    deduped: %s segments, %s chars (%.3f retained)",
        finding["preview_segments"],
        finding["preview_chars"],
        finding["preview_retained"],
    )
    logger.info("    BEFORE:")
    for text in finding["before_sample"]:
        logger.info("      | %s", text[:160])
    logger.info("    AFTER:")
    for text in finding["after_sample"]:
        logger.info("      | %s", text[:160])


# --- the two modes --------------------------------------------------------


async def survey(session: aiohttp.ClientSession, *, args) -> list[dict]:
    """Read-only. Nothing in here writes, resolves, or issues SQL."""
    if args.slug:
        logger.info("Probing %d explicitly named page(s).", len(args.slug))
        listed = await list_pages(session)
        by_slug = {page["slug"]: page for page in listed}
        candidates = [by_slug.get(slug, {"slug": slug}) for slug in args.slug]
    else:
        listed = await list_pages(session)
        logger.info("%d archived page(s) in total.", len(listed))
        candidates = select_candidates(
            listed,
            created_before=args.created_before,
            host_contains=args.host_contains,
        )
        logger.info(
            "%d candidate(s) after the two cheap bounds: platform in %s, "
            "archived before %s.%s",
            len(candidates),
            ", ".join(sorted(ROLLUP_PLATFORMS)),
            args.created_before or "(no date bound)",
            f" Host filter {args.host_contains!r} applied."
            if args.host_contains
            else "",
        )
        for platform, count in Counter(
            page.get("platform") for page in candidates
        ).most_common():
            logger.info("  %6d  %s", count, platform)

    if args.limit:
        candidates = candidates[: args.limit]
        logger.info("Limited to the %d newest candidate(s).", len(candidates))

    if not candidates:
        logger.info("Nothing to probe. Done.")
        return []

    logger.info(
        "Probing each candidate's stored transcript (%ss apart) -- one indexed "
        "single-row read per page, no corpus-wide query anywhere.",
        args.probe_delay,
    )
    findings, tally = await probe_pages(session, candidates, delay=args.probe_delay)

    logger.info("--- dry run summary ---")
    logger.info(
        "%d probed: %d still hold roll-up duplication, %d are clean, %d have no "
        "transcript, %d could not be probed.",
        len(candidates),
        tally["affected"],
        tally["clean"],
        tally["no_transcript"],
        tally["probe_failed"],
    )
    if findings:
        stored_chars = sum(f["stored_chars"] for f in findings)
        preview_chars = sum(f["preview_chars"] for f in findings)
        logger.info(
            "Across the affected pages: %s stored characters would become %s "
            "(%.1f%% removed as duplication).",
            f"{stored_chars:,}",
            f"{preview_chars:,}",
            100 * (1 - preview_chars / stored_chars) if stored_chars else 0,
        )
        logger.info("Affected pages by platform:")
        for platform, count in Counter(f["platform"] for f in findings).most_common():
            logger.info("  %6d  %s", count, platform)
        logger.info("Affected pages by source host (top 15):")
        for host, count in Counter(f["source_host"] for f in findings).most_common(15):
            logger.info("  %6d  %s", count, host)

        matched = [f for f in findings if f["confidence"] == "matched"]
        borderline = [f for f in findings if f["confidence"] == "borderline"]
        logger.info(
            "By confidence: %d score >= %.2f (inside the range WO-34 measured "
            "real roll-up tracks at), %d score %.2f-%.2f (above the detector's "
            "gate but inside the gap WO-34's 18 files left empty -- real "
            "findings, and the ones to eyeball first).",
            len(matched),
            CONFIDENT_ROLLUP_RATIO,
            len(borderline),
            DETECTOR_GATE_RATIO,
            CONFIDENT_ROLLUP_RATIO,
        )

        logger.info(
            "Before/after excerpts -- the preview is dedupe_rollup_cues() run "
            "over the stored segments, which for an affected page are exactly "
            "the raw cues; --apply re-resolves the source for real. Every "
            "finding is in the report file regardless:"
        )
        # Deliberately samples both bands rather than the first --show
        # findings overall: candidates come back newest-first, so a plain
        # head could easily be all one band and hide the other entirely.
        for label, group in (("matched", matched), ("borderline", borderline)):
            if not group:
                continue
            logger.info("  --- %s (%d total) ---", label, len(group))
            for finding in group[: args.show]:
                log_finding_detail(finding)

    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "base_url": _base_url(),
        "created_before": args.created_before,
        "platforms": sorted(ROLLUP_PLATFORMS),
        "detector_gate_ratio": DETECTOR_GATE_RATIO,
        "confident_ratio": CONFIDENT_ROLLUP_RATIO,
        "probed": len(candidates),
        "tally": dict(tally),
        "findings": findings,
    }
    try:
        args.report_file.write_text(json.dumps(report, indent=2) + "\n")
        logger.info("Wrote %d finding(s) to %s.", len(findings), args.report_file)
    except OSError as e:
        logger.warning("Could not write report file %s: %s", args.report_file, e)

    if findings:
        logger.info(
            "Re-run with --apply --from-report %s to re-resolve and rewrite "
            "exactly these pages.",
            args.report_file,
        )
    return findings


async def rewrite_page(
    session: aiohttp.ClientSession,
    finding: dict,
    *,
    min_retained: float,
) -> dict:
    """One page, end to end: re-resolve, gate, push, promote, verify.

    Returns a dict with "ok" plus a human-readable "detail". Never raises
    for a page-level problem -- a dead source or a refused rewrite is a
    normal outcome of a sweep like this, not a reason to stop.
    """
    # Imported here, not at module level: these pull in every adapter, and
    # load_dotenv() in __main__ has to run first -- same import-order
    # reasoning as scripts/backfill_archived_pages.py.
    #
    # register_all_finders() is load-bearing, not tidiness. get_finder()
    # reads a module-level registry that is empty until something fills it,
    # and the only thing that ever does is app/main.py at import time. Without
    # this call every single page fails with "No asset finder for platform
    # 'granicus'" -- confirmed by a real resolve during this script's own
    # verification. backfill_archived_pages.py gets it for free by importing
    # app.main itself; this script deliberately does not (it needs the
    # ingest response's version_id, which archive_client.push() discards),
    # so it registers explicitly.
    from app.platforms import register_all_finders
    from app.platforms.base import UnsupportedPlatformError, detect_platform, get_finder

    register_all_finders()

    slug = finding["slug"]
    url = finding["source_url"]
    if not url:
        return {"ok": False, "detail": "no stored source URL to re-resolve"}

    # Re-detect from the URL rather than trusting the stored platform field,
    # for the delegation reason spelled out in
    # scripts/backfill_archived_pages.py: MeetingPage.platform holds the
    # *delegated* finder's name, so handing a PrimeGov URL to
    # YouTubeAssetFinder would fail every time.
    platform = detect_platform(url)
    try:
        finder = get_finder(platform)
    except UnsupportedPlatformError:
        return {"ok": False, "detail": f"unsupported platform {platform!r}"}

    try:
        resolved = await finder.resolve(url)
    except Exception as e:  # noqa: BLE001 -- a real government site, any failure
        return {"ok": False, "detail": f"resolve failed: {str(e)[:200]}"}

    fresh = [segment.model_dump() for segment in resolved.segments]
    ok, reason = rewrite_verdict(
        stored_chars=finding["stored_chars"],
        fresh=fresh,
        min_retained=min_retained,
    )
    if not ok:
        return {"ok": False, "detail": f"refused: {reason}", "refused": True}

    response = await push_ingest(session, resolved.model_dump(), url)
    version_id = response.get("version_id")
    pushed_slug = response.get("slug") or slug
    if version_id is None:
        return {"ok": False, "detail": "ingest returned no version_id (no segments?)"}

    await promote_version(session, pushed_slug, version_id)

    verify = await fetch_stored_transcript(session, pushed_slug)
    if verify is None:
        return {
            "ok": False,
            "detail": f"pushed+promoted version {version_id} but the page now "
            "serves no transcript at all",
        }
    if looks_affected(verify):
        ratio, _pairs = rollup_ratio(verify)
        return {
            "ok": False,
            "detail": f"pushed+promoted version {version_id} but the page still "
            f"scores as roll-up ({ratio:.3f})",
        }

    return {
        "ok": True,
        "version_id": version_id,
        "slug": pushed_slug,
        "detail": (
            f"version {version_id} promoted -- {finding['stored_segments']} segs / "
            f"{finding['stored_chars']} chars -> {len(verify)} segs / "
            f"{total_chars(verify)} chars ({reason})"
        ),
    }


async def sweep(session: aiohttp.ClientSession, *, args, state: State) -> int:
    """The real run. Returns a process exit code."""
    findings = await load_findings(session, args=args)
    if not findings:
        logger.info("No affected pages to rewrite. Done.")
        return 0

    below_ratio = [f for f in findings if f.get("rollup_ratio", 1.0) < args.min_ratio]
    pending = [
        f
        for f in findings
        if not state.done(f["slug"]) and f.get("rollup_ratio", 1.0) >= args.min_ratio
    ]
    logger.info(
        "%d affected page(s); %d already applied, %d previously failed and %d "
        "below --min-ratio %.2f are skipped -> %d to rewrite, %ss apart (each "
        "one re-resolves a real government website).",
        len(findings),
        len(state.applied),
        len(state.failed),
        len(below_ratio),
        args.min_ratio,
        len(pending),
        args.resolve_delay,
    )

    applied = refused = failed = 0
    consecutive_errors = 0
    started = time.monotonic()

    try:
        for index, finding in enumerate(pending, 1):
            slug = finding["slug"]
            logger.info(
                "[%d/%d] %s -- re-resolving %s",
                index,
                len(pending),
                slug,
                finding["source_url"],
            )
            try:
                result = await rewrite_page(
                    session, finding, min_retained=args.min_retained
                )
            except (aiohttp.ClientError, asyncio.TimeoutError, RuntimeError) as e:
                consecutive_errors += 1
                failed += 1
                state.record_failure(slug, str(e))
                state.save()
                logger.error(
                    "  Archive call failed (%d/%d consecutive): %s",
                    consecutive_errors,
                    MAX_CONSECUTIVE_ERRORS,
                    str(e)[:300],
                )
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    logger.error(
                        "Giving up after %d consecutive failures. Nothing is "
                        "lost -- re-run the same command to resume.",
                        consecutive_errors,
                    )
                    return 1
                continue

            if result["ok"]:
                consecutive_errors = 0
                applied += 1
                state.record_applied(slug, result)
                logger.info("  rewritten: %s", result["detail"])
            elif result.get("refused"):
                consecutive_errors = 0
                refused += 1
                state.record_failure(slug, result["detail"])
                logger.warning("  left alone: %s", result["detail"])
            else:
                consecutive_errors += 1
                failed += 1
                state.record_failure(slug, result["detail"])
                logger.warning("  failed: %s", result["detail"])
            state.save()

            if args.resolve_delay > 0 and index < len(pending):
                await asyncio.sleep(args.resolve_delay)
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.warning("Interrupted.")
    finally:
        state.save()
        logger.info("--- run summary ---")
        logger.info(
            "%d rewritten, %d refused by the safety gates, %d failed, %s elapsed.",
            applied,
            refused,
            failed,
            f"{int(time.monotonic() - started)}s",
        )
        logger.info(
            "Every rewritten page's old transcript is still reachable at "
            "/m/{slug}?version=<old id> -- nothing was deleted. Re-running the "
            "same command resumes from %s.",
            state.path,
        )
    return 0


async def load_findings(session: aiohttp.ClientSession, *, args) -> list[dict]:
    """`--apply`'s worklist: the dry run's report if one was named, otherwise
    a fresh probe. Reading the report is the intended path -- it is the
    thing a human actually reviewed."""
    if args.from_report:
        try:
            report = json.loads(args.from_report.read_text())
        except (OSError, json.JSONDecodeError) as e:
            logger.error("Could not read --from-report %s: %s", args.from_report, e)
            return []
        if report.get("base_url") and report["base_url"] != _base_url():
            logger.error(
                "%s was generated against %s, not %s. Refusing to apply it.",
                args.from_report,
                report["base_url"],
                _base_url(),
            )
            return []
        findings = report.get("findings") or []
        logger.info(
            "Loaded %d finding(s) from %s (generated %s).",
            len(findings),
            args.from_report,
            report.get("generated_at"),
        )
        return findings
    logger.info("No --from-report given; probing first.")
    return await survey(session, args=args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually re-resolve the affected pages and rewrite their "
        "transcripts. Without this the script only probes and reports "
        "(read-only), matching this repo's other backfill scripts.",
    )
    parser.add_argument(
        "--slug",
        action="append",
        default=[],
        help="Probe only this page (repeatable). Skips the platform and "
        "ingest-date bounds -- an explicit slug is a human naming a page on "
        "purpose. Useful for spot-checking one meeting.",
    )
    parser.add_argument(
        "--created-before",
        default=WO34_SHIP_DATE,
        help=f"Only consider pages archived before this ISO date (default "
        f"{WO34_SHIP_DATE}, WO-34's ship date -- a page archived after it was "
        "parsed with the fix already in place). Pass an empty string to drop "
        "the bound.",
    )
    parser.add_argument(
        "--host-contains",
        default=None,
        help="Further narrow candidates to source URLs containing this "
        "substring (e.g. cityoftacoma).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Probe at most this many candidates, newest first.",
    )
    parser.add_argument(
        "--show",
        type=int,
        default=10,
        help="How many affected pages get a full before/after excerpt in the "
        "log (default 10). Every one of them is in the report file regardless.",
    )
    parser.add_argument(
        "--probe-delay",
        type=float,
        default=DEFAULT_PROBE_DELAY_SECONDS,
        dest="probe_delay",
        help=f"Seconds between stored-transcript probes (default "
        f"{DEFAULT_PROBE_DELAY_SECONDS}). These hit our own Archive.",
    )
    parser.add_argument(
        "--resolve-delay",
        type=float,
        default=DEFAULT_RESOLVE_DELAY_SECONDS,
        dest="resolve_delay",
        help=f"Seconds between re-resolves during --apply (default "
        f"{DEFAULT_RESOLVE_DELAY_SECONDS}). These hit real government "
        "websites, so this matches backfill_archived_pages.py's default.",
    )
    parser.add_argument(
        "--min-retained",
        type=float,
        default=DEFAULT_MIN_RETAINED,
        help=f"Refuse a rewrite that keeps less than this fraction of the "
        f"stored transcript's characters (default {DEFAULT_MIN_RETAINED}; the "
        "most duplicated real track known retains 0.117).",
    )
    parser.add_argument(
        "--min-ratio",
        type=float,
        default=DETECTOR_GATE_RATIO,
        help=f"With --apply: only rewrite pages scoring at least this roll-up "
        f"ratio (default {DETECTOR_GATE_RATIO}, the detector's own gate -- i.e. "
        f"everything the dry run flagged). Raise it to {CONFIDENT_ROLLUP_RATIO} "
        "to restrict a run to the band WO-34 actually measured real roll-up "
        "tracks in. The dry run always reports both bands regardless.",
    )
    parser.add_argument(
        "--report-file",
        type=Path,
        default=DEFAULT_REPORT_FILE,
        help=f"Where the dry run writes its findings (default {DEFAULT_REPORT_FILE}).",
    )
    parser.add_argument(
        "--from-report",
        type=Path,
        default=None,
        help="With --apply: rewrite exactly the pages in this report file "
        "instead of probing again. The intended path -- it is the list a "
        "human actually reviewed.",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=DEFAULT_STATE_FILE,
        help=f"Where applied/failed slugs are remembered (default {DEFAULT_STATE_FILE}).",
    )
    parser.add_argument(
        "--reset-state",
        action="store_true",
        help="Forget which pages were already applied or failed.",
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
    if not 0 < args.min_retained < 1:
        logger.error("--min-retained must be between 0 and 1 (exclusive).")
        return 1

    if args.reset_state and args.state_file.exists():
        args.state_file.unlink()
        logger.info("Cleared %s.", args.state_file)

    async with aiohttp.ClientSession() as session:
        if not args.apply:
            await survey(session, args=args)
            return 0
        state = State.load(args.state_file, _base_url())
        return await sweep(session, args=args, state=state)


if __name__ == "__main__":
    # Deliberately not called at module level -- same reasoning as this
    # repo's other CLI scripts.
    load_dotenv()
    sys.exit(asyncio.run(main()))
