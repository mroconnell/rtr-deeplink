"""WO-235 (2026-09-11): pilot -- for governments of 25,000+ on a
recognized platform where the platform itself carries no video
(`reject_reason` `meeting-without-video`/`no-video-found`) and no
Archive page exists yet, does the government's OWN website link a
YouTube channel or playlist that carries its meetings?

Ryan's framing (2026-09-11), restated: "should we consider looking for
YouTube channels on all of our good platform websites? ... We check the
site footer and html for a youtube channel or playlist link, check that
channel/playlist for some on-mission video and then decide whether to
ingest it with a pin to that gov or not." A same-day 30-row spot-check
found nine real hits this way (Hagerstown MD, Dallas OR, Sweet Home OR,
North Vernon IN, Harvey IL, Brookshire TX, Flagler Beach FL, Richlands
VA, Jackson TN) -- this pilot is the systematic version.

This is deliberately a TWO-STAGE, resumable pipeline, not one script
that both discovers and ingests in a single pass -- Ryan's rule (and
CLAUDE.md's own hand-check convention) is that a found video gets read
by a human before it becomes a page, not merely pre-filtered by code.

  1. `discover`  -- read-only. Fetches each government's home page and
     recorded hub page, extracts every YouTube channel/playlist/video
     link (footer social blocks and hover-only nav included -- both are
     real HTML BeautifulSoup already parses, whether or not CSS shows
     them), and for any channel/playlist found runs ONE yt-dlp flat
     listing (same technique and anti-block player_client list as
     `app/platforms/youtube_channel.py`'s own `_list_channel_tab()` /
     `scripts/wo134_confirmed_hits_ingest.py`'s own
     `_list_youtube_channel_entries()`) to get the channel's own name/
     description AND its newest 30 uploads in one call. Writes
     `research/wo235_discovery.csv` -- no network write, no ingest, no
     pin, nothing touched in jurisdiction_coverage.csv. A human (this
     session) reads that file directly and decides, per CLAUDE.md's
     hand-check rule and this WO's own brief:
       - channel identity: does the channel's own name/type match this
         government, or does its description/About text link the
         government's domain? A community-TV/county channel that carries
         the town's meetings is not the town's own channel (per-video
         pin only). A library/school/chamber channel is a miss.
       - Kind A (channel belongs to a different real public body) vs
         Kind B (right channel, wrong video) via
         `classify_video_hand_check()`, PLUS an actual read of the title
         and channel text -- the phrase list is a pre-filter, not a
         replacement for reading it.
     Decisions are written BY HAND into `research/wo235_decisions.csv`.

  2. `finalize`  -- reads `research/wo235_decisions.csv` (only), and for
     every `ingest_video` decision, walks its `candidate_video_ids` in
     the hand-approved order: resolves the real video through the same
     `youtube` adapter every other sweep uses
     (`app.platforms.base.get_finder`), and
       - real captions (segments) -> ingests via the same
         `POST /internal/ingest` primitive every other sweep script uses
         (`scripts.bulk_ingest._ingest`, imported by
         `wo134_confirmed_hits_ingest.py` too), with `gov_id` in the
         payload (WO-222's rule -- a sweep that knows its row's gov_id
         sends it, so a fresh page never depends on a pin reaching
         production first).
       - real video, no captions -> probed and queued/deferred through
         WO-224's shared `finish_candidate()` (never a raw queue-file
         append) -- tries the next candidate_video_id on a probe reject,
         same as every other sweep's "take the next candidate" rule.
     Pin: `channel=@handle` when the hand-check decided this channel is
     the government's own (written directly here via
     `queue_probe.write_pin_row()`, since `wo134.maybe_write_tenant_
     override()` only ever writes a bare per-video id); the per-video id
     otherwise (via `wo134.maybe_write_tenant_override()`, unchanged).
     Writes `research/wo235_report.csv`, one row per government, the
     brief's own column set -- resumable (skips a gov_id already in that
     file).

Owner-elsewhere (Kind A) governments are recorded, not keyed: see
`research/wo235_owner_bodies.csv` and CLAUDE.md's/this WO's own "record
the owner body, mark this government's own row no-video, look again for
its own video" rule.

The candidate population itself (179 governments of 25,000+, known
platform, `reject_reason` in `meeting-without-video`/`no-video-found`,
no Archive page) is derived fresh at `discover` startup straight from
`rtr-business/research/coverage_registry/coverage_registry.csv` (the
column names/derivation are this script's own -- see `_load_candidates()`)
and cross-checked against a LIVE `fetch_covered_gov_ids()` call so a
government that gained a page since the registry snapshot is skipped
rather than reprocessed.

Environment: run with
    DATABASE_URL="sqlite+aiohttp:////tmp/wo235_scratch.db" \\
    .venv/bin/python scripts/wo235_channel_pilot.py discover --limit 20
(DATABASE_URL is irrelevant to this script -- it imports no archive/app
DB code -- but is set anyway per this WO's own environment convention
for anything that imports `app`.)
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import html as html_module
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("RTR_DEEPLINK_PATH", str(REPO_ROOT))

load_dotenv()

import yt_dlp  # noqa: E402

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import get_finder  # noqa: E402
from app.platforms import queue_probe  # noqa: E402
from app.utils.gov_registry.registry import government_for_id  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402
from app.utils.video_hand_check import classify_video_hand_check  # noqa: E402

import scripts.wo134_confirmed_hits_ingest as wo134  # noqa: E402
from scripts.wo147_access_ladder_sweep import (  # noqa: E402
    BROWSER_HEADERS,
    HONEST_HEADERS,
    HOST_DELAY_SECONDS,
    fetch_headless,
    fetch_one,
    is_challenge,
)
from scripts.wo174_pipeline import fetch_covered_gov_ids  # noqa: E402

register_all_finders()

RESEARCH_DIR = Path("/Users/mroconnell/Documents/rtr-business/research")
COVERAGE_REGISTRY_CSV = RESEARCH_DIR / "coverage_registry" / "coverage_registry.csv"
DISCOVERY_CSV = RESEARCH_DIR / "wo235_discovery.csv"
DECISIONS_CSV = RESEARCH_DIR / "wo235_decisions.csv"
REPORT_CSV = RESEARCH_DIR / "wo235_report.csv"
OWNER_BODIES_CSV = RESEARCH_DIR / "wo235_owner_bodies.csv"
HEADLESS_BUDGET_STATE = RESEARCH_DIR / "wo235_headless_budget_used.txt"
HEADLESS_BUDGET_TOTAL = 150

GOVERNMENT_DELAY_SECONDS = 1.5

# The reject reasons this pilot's candidate population is scoped to --
# see this WO's own brief and docs/BREADTH_SWEEP_BRIEF.md's reject-reason
# taxonomy. "no-video-found" is the older spelling (WO-164), still
# present on rows this old; both mean the same thing.
_TARGET_REJECT_REASONS = {"meeting-without-video", "no-video-found"}

DISCOVERY_FIELDS = [
    "gov_id",
    "name",
    "state",
    "population",
    "known_platform",
    "domain",
    "hub_url",
    "channel_urls",
    "channel_owner_guess",
    "channel_name",
    "channel_uploader_id",
    "channel_description_snippet",
    "meetings_on_channel",
    "candidates",
    "access_mode",
    "note",
]

REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "population",
    "known_platform",
    "channel_url",
    "channel_owner",
    "meetings_on_channel",
    "chosen_video",
    "outcome",
    "hand_check",
    "page_url",
    "note",
]

OWNER_BODIES_FIELDS = [
    "gov_id_of_site_checked",
    "owner_name",
    "channel_url",
    "video_url",
    "owner_gov_id_if_known",
    "note",
]

DECISIONS_FIELDS = [
    "gov_id",
    "decision",  # ingest_video | owner_elsewhere | no_meetings | blocked | skip
    "channel_owner",  # own | community-tv | county | other | none
    "handle",  # bare handle (no leading @), only when channel_owner == own
    "candidate_video_ids",  # semicolon-separated, in the order to try
    "owner_name",
    "owner_channel_url",
    "owner_video_url",
    "note",
]


# --------------------------------------------------------------------------
# Candidate population
# --------------------------------------------------------------------------


def _load_candidates(min_population: float = 25000.0) -> List[dict]:
    """Re-derives the candidate list fresh from the coverage registry CSV
    at run time (never hard-coded), per this repo's "a backlog/brief
    claim is a lead, re-derive it" rule. Columns match `coverage_registry.
    csv`'s own header (see `rtr-business/research/coverage_registry.py`)."""
    rows = []
    with COVERAGE_REGISTRY_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                pop = float(row.get("population") or 0)
            except ValueError:
                pop = 0.0
            reject = (row.get("reject_reason") or "").strip()
            platform = (row.get("known_platform") or "").strip()
            pages = (row.get("archive_pages") or "").strip()
            has_page = pages not in ("", "0")
            if (
                pop >= min_population
                and platform
                and reject in _TARGET_REJECT_REASONS
                and not has_page
            ):
                rows.append(row)
    rows.sort(key=lambda r: -float(r.get("population") or 0))
    return rows


# --------------------------------------------------------------------------
# Access ladder (home page + hub page) -- reuses wo147's fetch/ladder
# primitives; this is its own small ladder rather than
# wo147.run_access_ladder() because that function's job is finding a
# PLATFORM link (detect_platform()-recognized), not a YouTube link
# specifically, and it doesn't fetch a second (hub) URL.
# --------------------------------------------------------------------------


def _headless_budget_used() -> int:
    if not HEADLESS_BUDGET_STATE.exists():
        return 0
    try:
        return int(HEADLESS_BUDGET_STATE.read_text().strip() or "0")
    except ValueError:
        return 0


def _headless_budget_increment() -> None:
    used = _headless_budget_used() + 1
    HEADLESS_BUDGET_STATE.write_text(str(used) + "\n")


@dataclass
class PageFetch:
    html: Optional[str] = None
    final_url: str = ""
    access_mode: str = "none"  # plain | browser-headers | headless | dead | challenge
    note: str = ""


async def fetch_with_ladder(session: aiohttp.ClientSession, url: str) -> PageFetch:
    if not url:
        return PageFetch(note="no url")
    r = await fetch_one(session, url, HONEST_HEADERS)
    if r.html is not None and not is_challenge(r.html):
        return PageFetch(html=r.html, final_url=r.final_url, access_mode="plain")

    if r.html is not None and is_challenge(r.html):
        pass  # fall through to headless below, budget permitting
    else:
        # error or dropped connection -- never after a plain 404, but
        # fetch_one folds a 404 into r.html="" (a real short body), not
        # error_kind, so this branch is genuinely "dropped/blocked", not
        # "not found".
        await asyncio.sleep(HOST_DELAY_SECONDS)
        rb = await fetch_one(session, url, BROWSER_HEADERS)
        if rb.html is not None and not is_challenge(rb.html):
            return PageFetch(
                html=rb.html, final_url=rb.final_url, access_mode="browser-headers"
            )
        if rb.html is not None and is_challenge(rb.html):
            r = rb  # fall through to headless below
        else:
            kind = r.error_kind or "connection"
            return PageFetch(
                access_mode="dead", note=f"unreachable ({kind}): {r.error}"
            )

    if is_challenge(r.html or ""):
        if _headless_budget_used() >= HEADLESS_BUDGET_TOTAL:
            return PageFetch(
                access_mode="challenge",
                note="challenge page, headless budget exhausted",
            )
        html, final_url, err = await fetch_headless(url)
        _headless_budget_increment()
        if err or html is None:
            return PageFetch(access_mode="challenge", note=f"headless failed: {err}")
        if is_challenge(html):
            return PageFetch(
                access_mode="challenge",
                note="challenge page, stayed interactive under headless",
            )
        return PageFetch(html=html, final_url=final_url, access_mode="headless")

    return PageFetch(access_mode="dead", note="unreachable")


# --------------------------------------------------------------------------
# YouTube link extraction -- footer social blocks and hover-only nav are
# both real anchors in the HTML BeautifulSoup parses, whether or not CSS
# hides them until hover, so no special-casing is needed for either.
# --------------------------------------------------------------------------

_YT_CHANNEL_RE = re.compile(
    r"(?:https?:)?//(?:www\.)?youtube(?:-nocookie)?\.com/(?:channel/[\w-]+|@[\w.-]+|c/[\w.-]+|user/[\w.-]+)",
    re.IGNORECASE,
)
_YT_PLAYLIST_RE = re.compile(
    r"(?:https?:)?//(?:www\.)?youtube(?:-nocookie)?\.com/playlist\?[^\"'\s<>]*list=[\w-]+",
    re.IGNORECASE,
)
# WO-285, 2026-09-12: widened to also match `/embed/{id}` (either domain)
# -- previously unmatched by ANY pattern here, not just on
# youtube-nocookie.com. Confirmed real need on South Connellsville, PA's
# own front page: `"url":"https:\/\/www.youtube.com\/embed\/9uOETcuFjbE
# ?feature=oembed"` (a real Elementor video-widget JSON config).
_YT_WATCH_RE = re.compile(
    r"(?:https?:)?//(?:www\.)?youtube(?:-nocookie)?\.com/(?:watch\?[^\"'\s<>]*v=|embed/)[\w-]+"
    r"|(?:https?:)?//youtu\.be/[\w-]+",
    re.IGNORECASE,
)
# A legacy vanity channel URL (youtube.com/SaultSteMarieOntario, no
# /channel/, /@, /c/, or /user/ prefix) -- real, confirmed-live case
# (this WO's own candidate list has one: Sault Ste. Marie ON's recorded
# hub_url IS exactly this shape). wo134_confirmed_hits_ingest.py's own
# `_is_youtube_channel_url()` docstring notes this same shape doesn't
# match its regex either and relies on a resolve-time except clause
# instead; this is the discovery-time equivalent -- a permissive
# fallback that accepts a single non-reserved path segment. Ordered
# last so a channel/playlist/watch URL is always classified by its own,
# more specific pattern first.
_YT_RESERVED_PATHS = {
    "watch",
    "playlist",
    "results",
    "feed",
    "shorts",
    "embed",
    "live",
    "gaming",
    "premium",
    "about",
    "trends",
    "account",
    "upload",
    "redirect",
}
_YT_VANITY_RE = re.compile(
    r"(?:https?:)?//(?:www\.)?youtube(?:-nocookie)?\.com/([\w.-]+)/?(?:[?#]|$)",
    re.IGNORECASE,
)
_ONCLICK_URL_RE = re.compile(r"""\(\s*['"]([^'"]+)""")

# WO-285, 2026-09-12: a bare youtube.com/youtu.be URL sitting in raw
# script/JSON text, not any tag's href/src -- confirmed real and common:
# WO-271's own 34-government "front-page mention, no channel found" list
# (rtr-business/research/wo271_discovery.csv) turned out to be
# overwhelmingly this shape, not the youtube-nocookie.com embed this
# entry originally guessed at (checked 12 real examples building this
# fix: 6 had a real, JSON-escaped `https:\/\/(www.)youtube.com\/...` or
# `https:\/\/youtu.be\/...` URL inside an inline <script> block -- a
# WordPress video-embed plugin's own per-post config, e.g. McCracken
# County, KY's `{"youtube_url":"https:\/\/youtu.be\/7w68XqgThU8",...}` --
# never inside an <a>/<iframe>/<video>/<source> tag the scan below looks
# at; the other 6 had no real youtube link on the page at all -- some
# 403'd outright, others' only "youtube" mention was the SAME plugin's
# own generic boilerplate JS listing both youtube.com and
# youtube-nocookie.com as fallback player-domain options, never a
# populated embed. Not one of the 12 had a real, populated
# youtube-nocookie.com link anywhere -- the domain widening above is
# kept as cheap defense in depth, not because it was confirmed live.
_RAW_YOUTUBE_URL_RE = re.compile(
    r"https?://(?:www\.)?(?:youtube(?:-nocookie)?\.com|youtu\.be)/[^\"'\s\\<>]+",
    re.IGNORECASE,
)


def _normalize_link(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("//"):
        raw = "https:" + raw
    return raw


def classify_youtube_url(value: str) -> Optional[str]:
    """Returns "channel", "playlist", "video", or None (not a recognized
    YouTube link shape at all -- e.g. youtube.com/results?...)."""
    if not value:
        return None
    low = value.lower()
    if (
        "youtube.com" not in low
        and "youtu.be" not in low
        and "youtube-nocookie.com" not in low
    ):
        return None
    if _YT_PLAYLIST_RE.search(value):
        return "playlist"
    if _YT_CHANNEL_RE.search(value):
        return "channel"
    if _YT_WATCH_RE.search(value):
        return "video"
    m = _YT_VANITY_RE.search(value)
    if m and m.group(1).lower() not in _YT_RESERVED_PATHS:
        return "channel"
    return None


def find_youtube_links(html: str, base_url: str) -> List[Tuple[str, str]]:
    """Returns a deduped list of (kind, url) pairs, kind in
    ("channel", "playlist", "video"). Scans anchor href, iframe/video
    src, and an onclick handler's first quoted URL (same tag set as
    wo147/wo134's own platform-link scanners) -- covers a footer social
    icon and a hover-only nav dropdown alike, since both are ordinary
    anchors in the parsed HTML regardless of what CSS shows by default --
    plus (WO-285) a raw-text scan for a bare, possibly JSON-escaped
    youtube.com/youtu.be URL that isn't in any tag attribute at all; see
    _RAW_YOUTUBE_URL_RE's own comment for the real, confirmed shape this
    catches."""
    if not html:
        return []
    # De-escape JSON-style backslash-escaped slashes before scanning --
    # same fix media_scan.py's scan_media_urls() already applies for the
    # identical reason (see that function's own docstring), needed here
    # for the raw-text scan below to ever match a JSON config's
    # `"https:\/\/youtu.be\/..."` value.
    html = html.replace("\\/", "/")
    soup = BeautifulSoup(html, "html.parser")
    found: List[Tuple[str, str]] = []
    seen = set()

    def _consider(value: str) -> None:
        if not value:
            return
        value = (
            urljoin(base_url, value)
            if not value.startswith(("http://", "https://", "//"))
            else _normalize_link(value)
        )
        kind = classify_youtube_url(value)
        if kind is None:
            return
        key = (kind, value.split("&")[0].rstrip("/"))
        if key in seen:
            return
        seen.add(key)
        found.append((kind, value))

    for tag in soup.find_all(("a", "iframe", "video", "source")):
        _consider(tag.get("href") or tag.get("src") or "")
        onclick = tag.get("onclick")
        if onclick:
            m = _ONCLICK_URL_RE.search(onclick)
            if m:
                _consider(m.group(1))

    for m in _RAW_YOUTUBE_URL_RE.finditer(html):
        # Same unescape-then-retrim shape media_scan.py's scan_media_urls()
        # already uses: unescaping an HTML entity like `&quot;` can reveal
        # a real quote character the raw regex's own char-class couldn't
        # see coming, which would otherwise leave trailing JSON garbage
        # (e.g. `,&quot;video_type&quot;:...`) glued onto the real URL --
        # confirmed live on McCracken County, KY's own front page.
        raw = html_module.unescape(m.group(0))
        raw = re.split(r"[\"'\s<>\\]", raw, maxsplit=1)[0]
        _consider(raw)

    return found


# --------------------------------------------------------------------------
# yt-dlp: one flat listing call gets both channel identity metadata AND
# the newest uploads -- same technique/anti-block player_client list as
# app/platforms/youtube_channel.py's _list_channel_tab() and
# wo134_confirmed_hits_ingest.py's _list_youtube_channel_entries(), just
# parameterized on an arbitrary discovered URL and kept as a dict (not
# discarded down to entries only) since the identity check needs it.
# --------------------------------------------------------------------------

_YDL_BASE_OPTS = {
    "skip_download": True,
    "quiet": True,
    "no_warnings": True,
    "extract_flat": "in_playlist",
    "extractor_args": {"youtube": {"player_client": ["android", "ios", "tv", "web"]}},
    "ignoreerrors": True,
}


def _yt_dlp_listing_sync(url: str, playlistend: int) -> Optional[dict]:
    opts = dict(_YDL_BASE_OPTS)
    opts["playlistend"] = playlistend
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception:
        return None


async def yt_dlp_listing(url: str, playlistend: int = 30) -> Optional[dict]:
    return await asyncio.to_thread(_yt_dlp_listing_sync, url, playlistend)


def channel_tab_url(channel_or_playlist_url: str, kind: str) -> List[str]:
    base = channel_or_playlist_url.rstrip("/")
    if kind == "playlist":
        return [base]
    return [f"{base}/videos", f"{base}/streams"]


_MEETING_ALLOWLIST = wo134.MEETING_ALLOWLIST
_looks_like_real_meeting = wo134._looks_like_real_meeting


def _entry_ok(
    entry: dict, channel_text: str, gov_name: str, gov_kind: str
) -> Optional[str]:
    """Returns None if the entry looks like a real, on-mission meeting;
    otherwise a short reason it was excluded."""
    if entry.get("live_status") in ("is_upcoming", "is_live"):
        return "upcoming/live, not yet a recording"
    if not entry.get("duration"):
        return "no duration (short/unplayable placeholder)"
    title = entry.get("title") or ""
    if not _looks_like_real_meeting(title, require_allowlist=True):
        return "no governing-body keyword in title (or a blocklisted promo term)"
    hand_check = classify_video_hand_check(title, channel_text, gov_name, gov_kind)
    if hand_check:
        kind, reason = hand_check
        return f"hand-check Kind {kind}: {reason}"
    return None


_IN_WINDOW_MIN = queue_probe.IN_WINDOW_MIN_SECONDS
_IN_WINDOW_MAX = queue_probe.IN_WINDOW_MAX_SECONDS


def _candidate_sort_key(entry: dict):
    dur = entry.get("duration") or 0
    in_window = _IN_WINDOW_MIN <= dur <= _IN_WINDOW_MAX
    return (0 if in_window else 1, dur if in_window else abs(dur))


def guess_channel_owner(
    channel_name: str, description: str, gov_name: str, gov_kind: str, domain: str
) -> str:
    """A DISCOVERY-TIME GUESS ONLY -- never trusted for ingest without a
    human reading channel_name/channel_description_snippet in
    wo235_discovery.csv (this WO's own hand-check rule). Cheap heuristics:
    a community-TV/PEG-access phrase in the name is `community-tv`; a
    library/school/chamber/sports phrase is `other` (a miss); the
    domain's own host token or "county"/"parish" (when the government
    itself is a county) appearing in the channel name/description is
    `own`; a bare county word with no domain match is `county` (carries
    the town's meetings but isn't the town's own channel); otherwise
    `other`."""
    text = f"{channel_name} {description}".lower()
    community_tv_words = (
        "community media",
        "public access",
        "peg access",
        "ctv",
        "community television",
        "cable access",
    )
    miss_words = (
        "public library",
        "library district",
        "school district",
        "chamber of commerce",
        "youth sports",
        "little league",
    )
    if any(w in text for w in miss_words):
        return "other"
    if any(w in text for w in community_tv_words):
        return "community-tv"
    domain_host = (domain or "").split(".")[0].lower()
    if domain_host and len(domain_host) > 3 and domain_host in text.replace(" ", ""):
        return "own"
    name_core = re.sub(
        r"^(city|town|village|township|borough|county) of ", "", gov_name.lower()
    ).strip()
    name_tokens = [t for t in re.split(r"\W+", name_core) if len(t) > 2]
    if name_tokens and all(t in text for t in name_tokens):
        if gov_kind == "county" or "county" in text:
            return "own" if "county" in text else "county"
        return "own"
    if "county" in text or "parish" in text:
        return "county"
    return "other"


# --------------------------------------------------------------------------
# discover
# --------------------------------------------------------------------------


def _already_discovered_gov_ids() -> set:
    if not DISCOVERY_CSV.exists():
        return set()
    with DISCOVERY_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f)}


def _write_discovery_row(row: dict) -> None:
    is_new = not DISCOVERY_CSV.exists()
    with DISCOVERY_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=DISCOVERY_FIELDS, lineterminator="\n")
        if is_new:
            w.writeheader()
        w.writerow(row)


async def discover_one(session: aiohttp.ClientSession, row: dict, covered: set) -> dict:
    gov_id = row["gov_id"]
    name = row["name"]
    state = row["state"]
    domain = (row.get("domain") or "").strip()
    hub_url = (row.get("hub_url") or "").strip()
    known_platform = (row.get("known_platform") or "").strip()
    population = row.get("population") or ""

    out = {
        "gov_id": gov_id,
        "name": name,
        "state": state,
        "population": population,
        "known_platform": known_platform,
        "domain": domain,
        "hub_url": hub_url,
        "channel_urls": "",
        "channel_owner_guess": "",
        "channel_name": "",
        "channel_uploader_id": "",
        "channel_description_snippet": "",
        "meetings_on_channel": "",
        "candidates": "",
        "access_mode": "",
        "note": "",
    }

    if gov_id in covered:
        out["note"] = "already_covered"
        return out

    home_url = (
        f"https://{domain}" if domain and not domain.startswith("http") else domain
    )

    # A recorded hub_url (or, in principle, domain) can BE the YouTube
    # link itself, not a page that merely links to one -- real, confirmed
    # case in this WO's own candidate list (Sault Ste. Marie ON's hub_url
    # is exactly "https://www.youtube.com/SaultSteMarieOntario", a bare
    # vanity channel URL). Seed `links` from these directly rather than
    # trying to fetch youtube.com as though it were the government's own
    # webpage.
    pre_seeded_links: List[Tuple[str, str]] = []
    fetches = []
    for label, url in (("home", home_url), ("hub", hub_url)):
        if not url:
            continue
        kind = classify_youtube_url(url)
        if kind:
            pre_seeded_links.append((kind, url))
            continue
        if url == home_url and label == "hub":
            continue  # dup of home_url, already queued
        fetches.append((label, url))

    all_html = []
    access_modes = []
    notes = []
    for i, (label, url) in enumerate(fetches):
        if i:
            await asyncio.sleep(HOST_DELAY_SECONDS)
        pf = await fetch_with_ladder(session, url)
        access_modes.append(pf.access_mode)
        if pf.html:
            all_html.append((pf.final_url or url, pf.html))
        if pf.note:
            notes.append(f"{label}: {pf.note}")

    out["access_mode"] = ";".join(access_modes) if access_modes else "no-url"
    if not all_html and not pre_seeded_links:
        out["note"] = "; ".join(notes) or "no page reachable"
        return out

    links: List[Tuple[str, str]] = list(pre_seeded_links)
    for final_url, html in all_html:
        links.extend(find_youtube_links(html, final_url))

    if not links:
        out["note"] = "no-channel-linked" + (
            (" (" + "; ".join(notes) + ")") if notes else ""
        )
        return out

    out["channel_urls"] = "; ".join(sorted({u for _, u in links}))

    channel_like = [u for k, u in links if k in ("channel", "playlist")]
    kinds = {u: k for k, u in links}
    videos_only = [u for k, u in links if k == "video"]

    if not channel_like:
        # A bare video link with no channel/playlist link alongside it --
        # still worth a look, but there is no "channel" to identity-check.
        out["note"] = (
            f"only bare video link(s) found, no channel/playlist: {videos_only[:3]}"
        )
        out["candidates"] = "; ".join(videos_only[:5])
        return out

    gov = government_for_id(gov_id)
    gov_kind = gov.gov_type if gov else ""

    listing = None
    for cand_url in channel_like[:2]:
        kind = kinds[cand_url]
        for tab_url in channel_tab_url(cand_url, kind):
            attempt = await yt_dlp_listing(tab_url, playlistend=30)
            if attempt and (attempt.get("entries") or attempt.get("channel")):
                listing = attempt
                break
        if listing:
            break

    if not listing:
        out["note"] = (
            "channel/playlist link found but yt-dlp listing failed (dead/private/blocked)"
        )
        return out

    channel_name = (
        listing.get("channel") or listing.get("uploader") or listing.get("title") or ""
    )
    uploader_id = listing.get("uploader_id") or listing.get("channel_id") or ""
    description = (listing.get("description") or "")[:300]
    out["channel_name"] = channel_name
    out["channel_uploader_id"] = uploader_id
    out["channel_description_snippet"] = description[:150].replace("\n", " ")
    out["channel_owner_guess"] = guess_channel_owner(
        channel_name, description, name, gov_kind, domain
    )

    entries = [e for e in (listing.get("entries") or []) if e]
    channel_text = f"{channel_name} {uploader_id}"
    good = []
    for e in entries:
        reason = _entry_ok(e, channel_text, name, gov_kind)
        if reason is None:
            good.append(e)
    out["meetings_on_channel"] = str(len(good))
    good.sort(key=_candidate_sort_key)
    out["candidates"] = "; ".join(
        f"{e['id']}|{(e.get('title') or '').replace('|', '/')}|{e.get('duration') or 0}"
        for e in good[:5]
    )
    if not good:
        out["note"] = (
            f"channel found ({channel_name!r}, {len(entries)} uploads listed), none looked on-mission"
        )
    return out


async def cmd_discover(args) -> None:
    candidates = _load_candidates(min_population=args.min_population)
    print(f"{len(candidates)} candidates at population >= {args.min_population:.0f}")
    already = _already_discovered_gov_ids()
    print(f"{len(already)} already discovered in a previous run")
    todo = [r for r in candidates if r["gov_id"] not in already]
    chunk = (
        todo[args.start : args.start + args.limit] if args.limit else todo[args.start :]
    )
    print(f"processing {len(chunk)} of {len(todo)} remaining this run")

    covered = fetch_covered_gov_ids()
    print(f"{len(covered)} gov_ids already have an Archive page (live check)")

    async with aiohttp.ClientSession() as session:
        for i, row in enumerate(chunk):
            if i:
                await asyncio.sleep(GOVERNMENT_DELAY_SECONDS)
            try:
                result = await discover_one(session, row, covered)
            except Exception as e:  # noqa: BLE001 -- never abort the whole chunk
                result = {
                    "gov_id": row["gov_id"],
                    "name": row["name"],
                    "state": row["state"],
                    "population": row.get("population") or "",
                    "known_platform": row.get("known_platform") or "",
                    "domain": row.get("domain") or "",
                    "hub_url": row.get("hub_url") or "",
                    "channel_urls": "",
                    "channel_owner_guess": "",
                    "channel_name": "",
                    "channel_uploader_id": "",
                    "channel_description_snippet": "",
                    "meetings_on_channel": "",
                    "candidates": "",
                    "access_mode": "error",
                    "note": f"error: {type(e).__name__}: {e}",
                }
            _write_discovery_row(result)
            print(
                f"[{i + 1}/{len(chunk)}] {result['gov_id']} {result['name']}, {result['state']}: "
                f"{result.get('channel_owner_guess') or ''} {result.get('note') or ''} "
                f"channels={result.get('channel_urls')!r}"
            )
    remaining = len(todo) - len(chunk)
    print(f"\n{remaining} candidates remain undiscovered after this run.")
    if remaining:
        print(
            f"Resume with: --start {args.start + len(chunk)} "
            f"(or omit --start/--limit to just continue from {DISCOVERY_CSV.name})"
        )


# --------------------------------------------------------------------------
# finalize
# --------------------------------------------------------------------------


def _already_reported_gov_ids() -> set:
    if not REPORT_CSV.exists():
        return set()
    with REPORT_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f)}


def _write_report_row(row: dict) -> None:
    is_new = not REPORT_CSV.exists()
    with REPORT_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REPORT_FIELDS, lineterminator="\n")
        if is_new:
            w.writeheader()
        w.writerow(row)


def _write_owner_body_row(row: dict) -> None:
    is_new = not OWNER_BODIES_CSV.exists()
    with OWNER_BODIES_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OWNER_BODIES_FIELDS, lineterminator="\n")
        if is_new:
            w.writeheader()
        w.writerow(row)


def _discovery_row_by_gov_id() -> Dict[str, dict]:
    out = {}
    if DISCOVERY_CSV.exists():
        with DISCOVERY_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                out[r["gov_id"]] = r
    return out


async def finalize_one(
    session: aiohttp.ClientSession, decision: dict, disc: dict
) -> dict:
    gov_id = decision["gov_id"]
    name = disc.get("name", "")
    state = disc.get("state", "")
    population = disc.get("population", "")
    known_platform = disc.get("known_platform", "")
    channel_owner = decision.get("channel_owner", "")
    handle = (decision.get("handle") or "").lstrip("@")
    channel_url = disc.get("channel_urls", "")

    base = {
        "gov_id": gov_id,
        "name": name,
        "state": state,
        "population": population,
        "known_platform": known_platform,
        "channel_url": channel_url,
        "channel_owner": channel_owner,
        "meetings_on_channel": disc.get("meetings_on_channel", ""),
        "chosen_video": "",
        "outcome": "",
        "hand_check": "ok",
        "page_url": "",
        "note": "",
    }

    if decision["decision"] == "owner_elsewhere":
        _write_owner_body_row(
            {
                "gov_id_of_site_checked": gov_id,
                "owner_name": decision.get("owner_name", ""),
                "channel_url": decision.get("owner_channel_url") or channel_url,
                "video_url": decision.get("owner_video_url", ""),
                "owner_gov_id_if_known": "",
                "note": decision.get("note", ""),
            }
        )
        base["outcome"] = "wrong_channel"
        base["hand_check"] = "wrong (Kind A -- owner elsewhere)"
        base["note"] = f"owner: {decision.get('owner_name', '')}; " + decision.get(
            "note", ""
        )
        return base

    if decision["decision"] == "no_meetings":
        base["outcome"] = "channel_no_meetings"
        base["note"] = decision.get("note", "")
        return base

    if decision["decision"] == "blocked":
        base["outcome"] = "blocked"
        base["note"] = decision.get("note", "")
        return base

    if decision["decision"] == "skip":
        base["outcome"] = (
            "no_channel_linked" if channel_owner == "none" else "channel_no_meetings"
        )
        base["note"] = decision.get("note", "")
        return base

    if decision["decision"] != "ingest_video":
        base["outcome"] = "error"
        base["note"] = f"unknown decision {decision['decision']!r}"
        return base

    candidate_ids = [
        c.strip()
        for c in (decision.get("candidate_video_ids") or "").split(";")
        if c.strip()
    ]
    if not candidate_ids:
        base["outcome"] = "error"
        base["note"] = "ingest_video decision with no candidate_video_ids"
        return base

    finder = get_finder("youtube")
    last_note = ""
    for vid in candidate_ids:
        video_url = f"https://www.youtube.com/watch?v={vid}"
        try:
            result = await finder.resolve(video_url)
        except Exception as e:  # noqa: BLE001
            last_note = f"{vid}: resolve raised {type(e).__name__}: {e}"
            continue

        # Double-check even after the hand decision -- classify_video_
        # hand_check() is cheap insurance against a decisions-file typo.
        hc = classify_video_hand_check(
            result.title or "", result.video_channel or "", name, ""
        )
        if hc:
            kind, reason = hc
            last_note = f"{vid}: hand-check flagged after resolve, Kind {kind}: {reason} (title={result.title!r})"
            continue

        base["chosen_video"] = video_url

        if result.segments:
            wo134.apply_display_jurisdiction(result, gov_id)
            if channel_owner == "own" and handle:
                queue_probe.write_pin_row(
                    host="www.youtube.com",
                    match=f"channel=@{handle}",
                    gov_id=gov_id,
                    strength="fallback",
                    source="wo235_channel_pilot",
                    evidence=f"{name}, {state} -- WO-235 channel pilot, gov_id={gov_id}",
                )
            else:
                wo134.maybe_write_tenant_override(
                    "youtube", result, video_url, gov_id, name, "wo235_channel_pilot"
                )
            payload = result.model_dump()
            payload["gov_id"] = gov_id
            try:
                response = await wo134._ingest_with_retry(
                    session, payload, normalize_url(video_url)
                )
            except Exception as e:  # noqa: BLE001
                base["outcome"] = "error"
                base["note"] = f"ingest raised: {e}"
                return base
            if response is None:
                base["outcome"] = "error"
                base["note"] = (
                    f"resolved real content ({len(result.segments)} segments) but POST to Archive failed twice"
                )
                return base
            base["outcome"] = "ingested_tier1_2"
            base["page_url"] = response.get("url", "")
            base["note"] = f"{len(result.segments)} transcript segments"
            return base

        if result.video_url:
            pin = None
            if channel_owner == "own" and handle:
                pin = {
                    "host": "www.youtube.com",
                    "match": f"channel=@{handle}",
                    "gov_id": gov_id,
                    "strength": "fallback",
                    "source": "wo235_channel_pilot",
                    "evidence": f"{name}, {state} -- WO-235 channel pilot, gov_id={gov_id}",
                }
            else:
                m = wo134._YT_ID_RE.search(result.video_url or video_url)
                if m:
                    pin = {
                        "host": urlparse(result.video_url or video_url).netloc.lower()
                        or "www.youtube.com",
                        "match": m.group(1),
                        "gov_id": gov_id,
                        "strength": "fallback",
                        "source": "wo235_channel_pilot",
                        "evidence": f"{name}, {state} -- WO-235 channel pilot, gov_id={gov_id}",
                    }
            outcome = await queue_probe.finish_candidate(
                video_url,
                video_url=result.video_url,
                source_url=channel_url.split(";")[0].strip() if channel_url else None,
                platform="youtube",
                gov_id=gov_id,
                jurisdiction=result.jurisdiction or f"{name}, {state}",
                title=result.title or "",
                pin=pin,
                caller="wo235_channel_pilot",
            )
            if outcome.action in ("queued", "already-queued"):
                base["outcome"] = "queued_tier3"
                base["note"] = (
                    f"probe accepted ({outcome.probe.duration_seconds}s): {outcome.action}"
                )
                return base
            if outcome.action in ("deferred", "already-deferred", "skipped-deferred"):
                base["outcome"] = "deferred_long"
                base["note"] = (
                    f"probe over 90min ({outcome.probe.duration_seconds}s): {outcome.action}"
                )
                return base
            # rejected -- try the next candidate
            last_note = f"{vid}: probe rejected ({outcome.probe.verdict}): {outcome.probe.reason}"
            continue

        last_note = f"{vid}: resolved but no segments and no video_url"

    base["outcome"] = "channel_no_meetings"
    base["note"] = (
        f"exhausted {len(candidate_ids)} hand-approved candidate(s); last: {last_note}"
    )
    return base


async def cmd_finalize(args) -> None:
    if not DECISIONS_CSV.exists():
        print(f"{DECISIONS_CSV} does not exist -- nothing to finalize.")
        return
    with DECISIONS_CSV.open(newline="", encoding="utf-8") as f:
        decisions = list(csv.DictReader(f))
    already = _already_reported_gov_ids()
    todo = [d for d in decisions if d["gov_id"] not in already]
    print(
        f"{len(decisions)} decisions, {len(already)} already reported, {len(todo)} to finalize"
    )
    disc_by_id = _discovery_row_by_gov_id()

    chunk = todo[: args.limit] if args.limit else todo
    async with aiohttp.ClientSession() as session:
        for i, decision in enumerate(chunk):
            if i:
                await asyncio.sleep(GOVERNMENT_DELAY_SECONDS)
            disc = disc_by_id.get(decision["gov_id"], {})
            try:
                row = await finalize_one(session, decision, disc)
            except Exception as e:  # noqa: BLE001
                row = {
                    "gov_id": decision["gov_id"],
                    "name": disc.get("name", ""),
                    "state": disc.get("state", ""),
                    "population": disc.get("population", ""),
                    "known_platform": disc.get("known_platform", ""),
                    "channel_url": disc.get("channel_urls", ""),
                    "channel_owner": decision.get("channel_owner", ""),
                    "meetings_on_channel": disc.get("meetings_on_channel", ""),
                    "chosen_video": "",
                    "outcome": "error",
                    "hand_check": "ok",
                    "page_url": "",
                    "note": f"error: {type(e).__name__}: {e}",
                }
            _write_report_row(row)
            print(
                f"[{i + 1}/{len(chunk)}] {row['gov_id']} {row['name']}, {row['state']}: {row['outcome']} -- {row['note']}"
            )
    print(f"\n{len(todo) - len(chunk)} decisions remain unfinalized after this run.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_discover = sub.add_parser("discover")
    p_discover.add_argument("--limit", type=int, default=0)
    p_discover.add_argument("--start", type=int, default=0)
    p_discover.add_argument("--min-population", type=float, default=25000.0)
    p_discover.set_defaults(func=cmd_discover)

    p_finalize = sub.add_parser("finalize")
    p_finalize.add_argument("--limit", type=int, default=0)
    p_finalize.set_defaults(func=cmd_finalize)

    args = parser.parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
