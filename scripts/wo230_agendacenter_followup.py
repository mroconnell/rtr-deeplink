"""WO-230: the 607 (re-derived: 570) governments of 5,000+ population whose
recorded hub is a bare `/AgendaCenter` and who have no Archive page yet.

Ryan's 2026-09-11 spot-check (30 rows) found that a recorded `/AgendaCenter`
hub is usually an EMPTY SHELL -- zero real `AgendaCenter/ViewFile/` links --
with the government's real agenda/video hub one click away on its own home
page: a `/{number}/...-Minutes-Agendas` style page, an Archive Center, a
CivicClerk portal embedded on a nav page, or the city's own YouTube channel
linked from the footer. Four of six spot-check shells went to a live
captioned page once the real hub was followed. This script:

  1. Fetches the recorded `/AgendaCenter` page and counts
     `AgendaCenter/ViewFile/` links. >=1 means the AgendaCenter itself is
     real -- run the existing, tested CivicPlus walk
     (`hub_sweep_wo126.civicplus_walk()`) on it, the same path WO-174 uses.
  2. If the AgendaCenter is a shell (0 ViewFile links), OR the walk found
     rows but no video, fall through to a home-page + nav-page hop search:
     fetch the home page, follow the site's own Government/City-Council/
     Boards-Commissions style nav links, and collect every numeric-path
     meeting/agenda/video link, `Archive.aspx`, `DocumentCenter`, and
     outbound platform/channel link (reusing `hub_sweep_wo126._platform_links()`/
     `_hint_links()`/`_youtube_channel_link()`, already tested code -- this
     script does not redesign that scan, only points it at the HOME page
     instead of the AgendaCenter hub, which the existing generic-hub sweep
     never does for a government whose recorded hub IS an AgendaCenter).
  3. A real browser render is used ONLY for a page that loaded (200, real
     content) but shows literally no candidate link in its raw HTML (the
     JavaScript-drawn-links case) -- budget 300 renders for the whole run,
     tracked in a small on-disk counter file so it survives a resume.
  4. Every video found is hand-checked (`classify_video_hand_check()` first,
     then this script's own title/channel read, recorded either way) before
     it can become a page or a queue line. Tier 1/2 ingest sends `gov_id` in
     the payload directly (WO-210/WO-222's rule: a page must not depend on a
     pin reaching production first). Tier 3 goes through WO-224's shared
     `queue_probe.finish_candidate()` helper.

Run from the rtr-deeplink repo root with the shared venv:
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo230_scratch.db" \\
        /Users/mroconnell/Documents/rtr-deeplink/.venv/bin/python \\
        scripts/wo230_agendacenter_followup.py [--limit N] [--dry-run]

Resumable: REPORT_CSV is flushed after every government; a gov_id with any
non-empty `outcome` already recorded is skipped on restart.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import aiohttp
import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

from dotenv import load_dotenv  # noqa: E402

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms import queue_probe  # noqa: E402
from app.platforms.base import (  # noqa: E402
    CalendarPageError,
    UnsupportedPlatformError,
    detect_platform,
    find_platform_link,
    get_finder,
)
from app.platforms.civicplus import CivicPlusAssetFinder  # noqa: E402
from app.platforms.vimeo import parse_vimeo_video  # noqa: E402
from app.platforms.youtube import YouTubeAssetFinder  # noqa: E402
from app.utils.gov_registry.registry import is_multi_gov_host  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402
from app.utils.video_hand_check import classify_video_hand_check  # noqa: E402

import hub_sweep_wo126 as hsw  # noqa: E402
from bulk_ingest import IngestGateRejected, _ingest  # noqa: E402
from wo146_api_relist_sweep import _looks_wrong_government  # noqa: E402
from wo174_pipeline import fetch_covered_gov_ids  # noqa: E402
from nationwide_2404_ingest import (  # noqa: E402
    civicclerk_latest_event_url,
    pick_calendar_candidate,
)

try:
    import yt_dlp
except ImportError:  # pragma: no cover
    yt_dlp = None

# The brief's own pacing rule (2s/host, 1.5s/government) is slightly
# stricter than hub_sweep_wo126.py's own established 1.5s/request --
# tightened here for this run only, not changed for any other importer.
hsw.REQUEST_DELAY_SECONDS = 2.0
# Every candidate here already carries a real, non-blank prior
# reject_reason (a previous sweep already looked, per this WO's own
# population filter) -- Ryan's finding that motivated this WO is that
# those labels were "assigned on the strength of a shell," not that the
# fragment walk itself was ever shallow. Trimmed from hub_sweep_wo126.py's
# own default of 8 to 3: WO-174's own close-out found yield falling fast
# pass over pass, and the real signal (a video row at all) almost always
# shows up in the current year or the immediately preceding one -- this
# keeps the walk real without spending a full extra minute per real
# AgendaCenter on years six-to-eight fragments back.
hsw.MAX_YEAR_FRAGMENTS = 3

PER_GOV_WALLCLOCK_CAP = 75

GOV_DELAY = 1.5
CONSECUTIVE_ERROR_HALT = 25
PER_GOV_FETCH_BUDGET = 14  # AgendaCenter root+fragments, home page, nav pages, hops
MAX_NAV_PAGES = 4
MAX_HOP_CANDIDATES = 3

RESEARCH_DIR = Path("/Users/mroconnell/Documents/rtr-business/research")
CANDIDATES_CSV = RESEARCH_DIR / "wo230_candidates.csv"
REPORT_CSV = RESEARCH_DIR / "wo230_report.csv"
OWNER_BODIES_CSV = RESEARCH_DIR / "wo230_owner_bodies.csv"
HAND_CHECK_LOG_CSV = RESEARCH_DIR / "wo230_hand_check_log.csv"
HEADLESS_BUDGET_JSON = RESEARCH_DIR / "wo230_headless_budget.json"
PINS_STAGED_CSV = RESEARCH_DIR / "wo230_pins_staged.csv"

# WO-249's hand-read gate (2026-09-12): WO-230 found 13 confirmed-wrong
# videos that reached a page or queue line, and 3 more slipped past the
# two automatic checks added mid-run (right meeting-shaped word, right
# channel) because the title carried a meeting word and the channel was
# right, but the video itself still wasn't this government's own
# deliberative meeting. Ryan's rule: no candidate that clears the
# existing automatic checks may become a page or queue line without a
# human actually reading its title, channel, and (when those two aren't
# decisive) its description, and recording a one-line reason. Since this
# script runs unattended, that human read happens as a separate step:
# a candidate that clears every automatic check is parked in
# PENDING_HAND_READ_CSV instead of being ingested; once a decision for
# it exists in HAND_READ_DECISIONS_CSV, the next run of this same script
# (gov_id resumes -- see `load_done_gov_ids()` below) picks it back up
# and finishes it for real, using the exact same candidate-retry loop a
# kind-A/B automatic rejection already uses.
PENDING_HAND_READ_CSV = RESEARCH_DIR / "wo249_pending_hand_read.csv"
HAND_READ_DECISIONS_CSV = RESEARCH_DIR / "wo249_hand_read_decisions.csv"

TENANT_OVERRIDES_CSV = (
    REPO_ROOT / "app" / "utils" / "jurisdiction_data" / "tenant_overrides.csv"
)
QUEUE_FILE = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue.txt"
DEFERRED_FILE = REPO_ROOT / "scripts" / "tier3_long_meetings_deferred.txt"
SIDECAR_CSV = REPO_ROOT / "scripts" / "tier3_auto_transcription_queue_probe.csv"

HEADLESS_TOTAL_BUDGET = 300

DRY_RUN = False

REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "population",
    "domain",
    "agendacenter_viewfile_count",
    "shell",
    "real_hub_url",
    "real_hub_kind",
    "platform_found",
    "outcome",
    "reject_reason",
    "hand_check",
    "meeting_url",
    "video_url",
    "tier",
    "page_url",
    "note",
]

HAND_CHECK_FIELDS = [
    "gov_id",
    "name",
    "state",
    "kind",
    "reason",
    "title",
    "video_channel",
    "video_url",
    "meeting_url",
    "verdict",
]

OWNER_BODIES_FIELDS = [
    "owner_name",
    "channel",
    "video_url",
    "gov_id_if_known",
    "found_for_gov_id",
    "found_for_name",
    "note",
]

PENDING_HAND_READ_FIELDS = [
    "gov_id",
    "name",
    "state",
    "title",
    "video_channel",
    "description_snippet",
    "video_url",
    "meeting_url",
    "platform",
    "hub_url",
    "is_own_channel",
    "tier",
]

HAND_READ_DECISION_FIELDS = [
    "gov_id",
    "video_url",
    "decision",
    "kind",
    "reason",
]

# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------


def normalize_domain(raw: str) -> str:
    d = (raw or "").strip()
    d = re.sub(r"^https?://", "", d, flags=re.I)
    d = d.split("/")[0]
    return d.strip().lower()


_NAV_PAGE_RE = re.compile(
    r'href="([^"]*?/\d+/[^"?#]*?(?:government|city-council|town-council|'
    r"village-council|county-commission|board-of-commissioners|boards?-?"
    r'commissions?|council|commission)[^"?#]*)"',
    re.IGNORECASE,
)
_MEETING_PATH_RE = re.compile(
    r'href="([^"]*?/\d+/[^"?#]*?(?:agenda|minutes|meeting|video|broadcast|'
    r'council|commission|board)[^"?#]*)"',
    re.IGNORECASE,
)
_ARCHIVE_ASPX_RE = re.compile(r'href="([^"?#]*?Archive\.aspx[^"?#]*)"', re.IGNORECASE)
_DOCUMENT_CENTER_RE = re.compile(
    r'href="([^"?#]*?DocumentCenter[^"?#]*)"', re.IGNORECASE
)
_YOUTUBE_CHANNEL_RE = re.compile(
    r'href="(https?://(?:www\.)?youtube\.com/(?:@[^"/?#]+|channel/[^"/?#]+|'
    r'c/[^"/?#]+|user/[^"/?#]+)[^"?#]*)"',
    re.IGNORECASE,
)
_VIEWFILE_RE = re.compile(r"AgendaCenter/ViewFile/", re.IGNORECASE)


def count_viewfile_links(html: str) -> int:
    return len(_VIEWFILE_RE.findall(html or ""))


_ANCHOR_RE = re.compile(r"<a\s", re.IGNORECASE)
_EMPTY_SHELL_ANCHOR_FLOOR = 8


def looks_like_js_shell(html: str) -> bool:
    """True only for a page that genuinely has almost no anchors at all in
    its raw HTML -- a client-rendered SPA shell (Flagler Beach FL's
    JavaScript-drawn nav is the brief's own real example). A normal
    server-rendered municipal page carries dozens of `<a href>` tags
    (nav, footer, social icons) even when NONE of them happen to match
    this script's own meeting/nav/platform regexes -- that is a real "no
    candidate here" finding, not evidence of client rendering, and must
    not burn the 300-render headless budget on every ordinary miss."""
    return len(_ANCHOR_RE.findall(html or "")) < _EMPTY_SHELL_ANCHOR_FLOOR


def find_nav_links(html: str, base_url: str, limit: int = MAX_NAV_PAGES) -> list:
    out, seen = [], set()
    for m in _NAV_PAGE_RE.finditer(html or ""):
        full = urljoin(base_url, m.group(1))
        if full not in seen:
            seen.add(full)
            out.append(full)
        if len(out) >= limit:
            break
    return out


def find_meeting_path_links(html: str, base_url: str) -> list:
    out, seen = [], set()
    for m in _MEETING_PATH_RE.finditer(html or ""):
        full = urljoin(base_url, m.group(1))
        if full not in seen:
            seen.add(full)
            out.append(("numeric-page", full))
    for m in _ARCHIVE_ASPX_RE.finditer(html or ""):
        full = urljoin(base_url, m.group(1))
        if full not in seen:
            seen.add(full)
            out.append(("archive-center", full))
    for m in _DOCUMENT_CENTER_RE.finditer(html or ""):
        full = urljoin(base_url, m.group(1))
        if full not in seen:
            seen.add(full)
            out.append(("document-center", full))
    return out


def _real_platform_candidate(match, channel_link_holder, source_page_url):
    """`find_platform_link()` (app.platforms.base) detects a platform by
    HOST alone, so a bare YouTube channel/handle link (no video id) comes
    back as a "youtube" match just like a real single-video link. A bare
    channel isn't directly resolvable -- routing it into `resolve_and_finish()`
    always fails with a ValueError and wastes an attempt that the
    dedicated channel-video-pick step (Priority 3) already handles
    correctly. Returns (kind, plink, platform, source_page_url) to append
    to platform_candidates, or None when this is a bare channel link (in
    which case `channel_link_holder` -- a single-item list used as an
    out-param -- gets the channel URL instead, if not already set).
    `source_page_url` is the home/nav PAGE the link was found on -- kept
    alongside `plink` (the resolvable video/platform link itself) so the
    report's `real_hub_url` can record the actual browsable hub page
    (a bare video URL is never "the real hub," per this WO's own report
    column meaning)."""
    plink, platform = match
    if platform in ("unknown", "civicplus"):
        return None
    if platform == "youtube" and not YouTubeAssetFinder.extract_video_id(plink):
        if not channel_link_holder[0]:
            channel_link_holder[0] = plink
        return None
    kind = "civicclerk-embed" if platform == "civicclerk" else "other-platform"
    return (kind, plink, platform, source_page_url)


_AB_CHANNEL_RE = re.compile(r"[?&]ab_channel=([^&]+)")


def channel_name_from_url(url: str) -> str:
    """YouTube's own `&ab_channel=<Name>` share-link query param names the
    channel in human-readable form directly in the URL -- real, confirmed
    gap (WO-230, 2026-09-11): yt-dlp's own metadata lookup can return no
    handle at all for an older/un-customized channel (`_channel_handle()`
    in `app/platforms/youtube.py` then has nothing to report), even
    though the URL the page actually linked already named the channel.
    Woodford County, IL's own `/Government` page linked
    `...&ab_channel=IllinoisCourts` -- a state court system's video, not
    the county's -- and `result.video_channel` came back blank, so the
    hand-check's own channel_text never saw it until this was added."""
    m = _AB_CHANNEL_RE.search(url or "")
    return m.group(1).replace("+", " ") if m else ""


def find_youtube_channel(html: str, base_url: str) -> str:
    m = _YOUTUBE_CHANNEL_RE.search(html or "")
    if not m:
        return ""
    return urljoin(base_url, m.group(1))


# --------------------------------------------------------------------------
# Headless render budget (persists across resumed runs)
# --------------------------------------------------------------------------


def load_headless_used() -> int:
    if not HEADLESS_BUDGET_JSON.exists():
        return 0
    try:
        return json.loads(HEADLESS_BUDGET_JSON.read_text()).get("used", 0)
    except Exception:
        return 0


def save_headless_used(n: int) -> None:
    HEADLESS_BUDGET_JSON.write_text(json.dumps({"used": n}))


_headless_used = 0


async def maybe_render_headless(url: str) -> str:
    """Returns rendered HTML, or "" if the budget is exhausted / render
    failed. Never used past a challenge page -- callers only reach this
    after already confirming a normal (non-challenge) 200 load."""
    global _headless_used
    if _headless_used >= HEADLESS_TOTAL_BUDGET:
        return ""
    _headless_used += 1
    save_headless_used(_headless_used)
    from wo147_access_ladder_sweep import fetch_headless

    html, _final_url, err = await fetch_headless(url)
    return html or ""


# --------------------------------------------------------------------------
# YouTube channel -> newest meeting-shaped video (own-channel case only;
# the channel was found via a first-party link on the government's own
# site, so ownership is already established -- this only picks WHICH
# video, not whose channel it is).
# --------------------------------------------------------------------------

_OFF_MISSION_TITLE_RE = re.compile(
    r"library|parade|festival|5k|fun run|farmers market|concert|movie night|"
    r"job fair|career fair|ribbon cutting|groundbreaking|holiday|carnival",
    re.IGNORECASE,
)
_MEETING_TITLE_RE = re.compile(
    r"council|commission|board|meeting|session|hearing|committee|trustees|"
    r"selectboard|supervisors|assembly|legislature|fiscal court|aldermen|"
    r"freeholders|workshop|retreat|town hall",
    re.IGNORECASE,
)

# A real, confirmed finding from this WO's own spot-check (2026-09-11),
# not a hypothetical: of 19 governments hand-checked against their real
# YouTube/page metadata, 10 were wrong -- NOT a school-board/state-DOT/
# regional-commission mismatch (the shared `video_hand_check.py` phrase
# list's existing targets), but a government's own informational,
# promotional, or "podcast" video that `_looks_wrong_government()`/
# `classify_video_hand_check()` had no way to catch: "Become Short Term
# Rental Ready" (Rockingham County VA), "Good Morning Cleveland" (aerial
# snow footage), "A Day in Life Firefighter" (St. Bernard Parish LA),
# "Benton County Government Center Project" (a building-project video),
# a mayor's own agenda-preview "podcast" (Methuen MA) -- none of these
# are a deliberative meeting, whatever government channel they came
# from. Three more were simply the WRONG government's own real content
# (Shelby County OH got Union County OH's video; Attleboro MA got an
# unrelated production company's; Douglas County WI got the City of
# Superior's own Common Council meeting) -- a channel/uploader name
# that shares no real word with this government's own name is the
# second check below. Applied to EVERY resolve, not just the loosely-
# scanned home-page/channel paths, since nothing about this risk is
# specific to how the video was found.
_REQUIRED_MEETING_WORD_RE = _MEETING_TITLE_RE

_GENERIC_GOV_NAME_WORDS = {
    "city",
    "town",
    "county",
    "village",
    "township",
    "borough",
    "parish",
    "of",
    "the",
    "government",
}


def _name_tokens(text: str) -> set:
    words = re.findall(r"[a-z]+", (text or "").lower())
    return {w for w in words if w not in _GENERIC_GOV_NAME_WORDS and len(w) > 2}


def _ordered_name_words(text: str) -> list:
    """Same filtering as `_name_tokens()` (drop generic gov-type words and
    anything <=2 chars) but ordered and not deduped -- `_run_together_
    name_match()` below needs the government's own words in the order
    they actually appear in `gov_name`, not a bag, since "the name's
    tokens appear in order" is the property it's checking for."""
    words = re.findall(r"[a-z]+", (text or "").lower())
    return [w for w in words if w not in _GENERIC_GOV_NAME_WORDS and len(w) > 2]


# WO-254 (found during WO-249): a real handle that runs the government's
# name together with no separators at all -- South River borough, NJ's
# own municipal channel, `@southrivernjtv3564`, confirmed live via
# YouTube's oEmbed to be "South River NJ TV35" -- tokenizes under
# `_name_tokens()`'s plain `[a-z]+` splitter as ONE blob
# ("southrivernjtv") that can never intersect a gov_name tokenized on
# real word boundaries, no matter whose channel it really is. This
# constant gates `_run_together_name_match()`'s fallback below at 2 real
# words minimum, not 1 -- see that function's own docstring for why a
# single word can't be trusted alone.
_MIN_RUN_TOGETHER_WORDS = 2

# The same generic gov-type words `_name_tokens()` already drops, plus
# every 2-word concatenation of them (order matters: "townof"/"cityof"
# are the real compound-handle prefixes; "ofcity" etc. are included too
# since nothing stops a government from writing it that way) -- used
# only to anchor a SINGLE real name-word against a genuine administrative
# prefix/suffix ("town of Weston" -> "townofweston...") before accepting
# it as a match. See `_run_together_name_match()`'s docstring for why a
# bare, unanchored single word is never accepted on its own.
_GENERIC_NAME_ADJACENCY = set(_GENERIC_GOV_NAME_WORDS) | {
    a + b for a in _GENERIC_GOV_NAME_WORDS for b in _GENERIC_GOV_NAME_WORDS if a != b
}


def _run_together_name_match(gov_name: str, channel_text: str) -> bool:
    """True when the government's own real name-words, in the order they
    appear in `gov_name`, concatenated with no separator, form a
    substring of `channel_text`'s own letters run together the same way.

    Exists for a real handle with no word separators at all (see
    `_MIN_RUN_TOGETHER_WORDS`'s own comment for the confirmed South River
    borough, NJ case) -- `channel_name_plausible()` calls this only as a
    fallback, after its own exact-token-set check has already failed to
    find a shared word the normal way.

    Requires at least `_MIN_RUN_TOGETHER_WORDS` (2) of the government's
    own words when checking a bare run-together match, specifically so a
    SINGLE word can never match alone: a lone word is exactly the shape
    of the false positive this whole check exists to avoid. Confirmed
    live during this same sweep (WO-247): Rockingham County, VA's real
    *tourism* channel, `@VisitRockinghamVA`, is ALSO one run-together
    blob ("visitrockinghamva") that legitimately contains "rockingham" --
    the government's only non-generic word -- with no way to tell it
    apart from a real government handle using text shape alone. Two
    consecutive real words together ("south" + "river", "west" +
    "fargo") are specific enough that a coincidental match inside an
    unrelated handle is implausible; one word is not -- per CLAUDE.md/
    BACKLOG.md's own constraint on this check, "don't just loosen the
    tokenizer to substring matching generically."

    A government whose own name reduces to exactly one non-generic word
    (e.g. plain "Weston") still gets a match here, but ONLY when that one
    word sits directly against a real generic government-type prefix or
    suffix in the channel blob (`_GENERIC_NAME_ADJACENCY` -- "town of
    Weston" -> "townofweston...", never a bare "weston" floating with no
    anchor) -- that's what a real municipal handle's own "Town of
    <Name>" shape looks like run together, and it's exactly what
    Rockingham's tourism-channel handle does NOT have (it's anchored by
    "visit", not by any government-type word).
    """
    gov_words = _ordered_name_words(gov_name)
    if not gov_words:
        return False
    channel_letters = "".join(re.findall(r"[a-z]+", (channel_text or "").lower()))
    if not channel_letters:
        return False
    run_together = "".join(gov_words)
    if len(gov_words) >= _MIN_RUN_TOGETHER_WORDS:
        return run_together in channel_letters
    for adjacency in _GENERIC_NAME_ADJACENCY:
        if (adjacency + run_together) in channel_letters or (
            run_together + adjacency
        ) in channel_letters:
            return True
    return False


_PREVIEW_NOT_THE_MEETING_RE = re.compile(
    r"podcast|preview|teaser|recap|highlight reel", re.IGNORECASE
)


def looks_like_deliberative_meeting(title: str) -> bool:
    """True only when the title itself names a real meeting-shaped body
    or session word. See the module comment above this regex for the
    real, confirmed misses this closes -- a bare absence check, not a
    phrase blocklist, because the wrong content here was too varied for
    any blocklist to keep up with. A title can contain a real body word
    and still not be the meeting itself -- Methuen MA's real, confirmed
    catch: "Mayor Neil Perry Agenda Review Podcast for 3-21-22 Council
    Agenda" names "Council" but is the mayor's own podcast PREVIEWING
    the agenda, not a recording of the meeting -- checked first, and
    wins over a body-word match."""
    title = title or ""
    if _PREVIEW_NOT_THE_MEETING_RE.search(title):
        return False
    return bool(_REQUIRED_MEETING_WORD_RE.search(title))


def channel_name_plausible(channel_text: str, gov_name: str) -> bool:
    """True when `channel_text` is blank (nothing to check -- most
    YouTube metadata lookups return no usable channel name at all, see
    `_channel_handle()`'s own docstring), shares at least one real word
    with the government's own name, OR (WO-254) matches via
    `_run_together_name_match()`'s compound-handle fallback -- a real
    handle with no word separators at all (`@southrivernjtv3564`) can
    never share a token with a gov_name tokenized on real word
    boundaries no matter whose channel it really is. False is a real
    negative signal (Shelby County OH's real channel was literally
    'Union County OH'), not proof by itself -- callers combine this with
    the title check."""
    if not channel_text:
        return True
    gov_tokens = _name_tokens(gov_name)
    channel_tokens = _name_tokens(channel_text)
    if not gov_tokens or not channel_tokens:
        return True
    if gov_tokens & channel_tokens:
        return True
    return _run_together_name_match(gov_name, channel_text)


def _yt_channel_recent_entries(channel_url: str, limit: int = 20) -> list:
    if yt_dlp is None:
        return []
    tab_url = channel_url.rstrip("/")
    if not tab_url.endswith(("/videos", "/streams")):
        tab_url = tab_url + "/videos"
    ydl_opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "playlistend": limit,
        "extractor_args": {
            "youtube": {"player_client": ["android", "ios", "tv", "web"]}
        },
        "ignoreerrors": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(tab_url, download=False)
    except Exception:
        return []
    if not info:
        return []
    return [e for e in (info.get("entries") or []) if e and e.get("id")]


def pick_channel_meeting_video(channel_url: str):
    """Returns (video_id, title, channel_handle_or_name) or (None, "", "")."""
    entries = _yt_channel_recent_entries(channel_url)
    for e in entries:
        title = e.get("title") or ""
        if _OFF_MISSION_TITLE_RE.search(title):
            continue
        if _MEETING_TITLE_RE.search(title):
            return e.get("id"), title, e.get("uploader") or e.get("channel") or ""
    return None, "", ""


# --------------------------------------------------------------------------
# Pin derivation (per WO-210's multi-gov-host rule: blank match refused on
# a shared host; own-tenant single-government hosts get a blank-match pin
# written directly, bypassing queue_probe.write_pin_row()'s stricter
# "match required" guard, which is tuned for the shared-host case).
# --------------------------------------------------------------------------

_MULTI_GOV_PLATFORMS = {"youtube", "vimeo"}


def derive_pin(
    gov_id: str,
    name: str,
    state: str,
    video_url: str,
    platform: str,
    hub_url: str,
    is_own_channel: bool,
):
    if platform == "youtube":
        vid = YouTubeAssetFinder.extract_video_id(video_url)
        if is_own_channel:
            # own channel confirmed via a first-party link on the gov's
            # own site -- a channel pin is safe and more durable than a
            # single video id.
            m = re.search(r"youtube\.com/(@[\w.-]+)", video_url or "") or re.search(
                r"youtube\.com/(@[\w.-]+)", hub_url or ""
            )
            if m:
                return {
                    "host": "www.youtube.com",
                    "match": f"channel={m.group(1)}",
                    "gov_id": gov_id,
                    "strength": "fallback",
                    "source": "wo230",
                    "evidence": f"{name}, {state} -- own YouTube channel, found via a first-party link on the government's own site",
                }
        if not vid:
            return None
        return {
            "host": "www.youtube.com",
            "match": vid,
            "gov_id": gov_id,
            "strength": "fallback",
            "source": "wo230",
            "evidence": f"{name}, {state} -- WO-230 AgendaCenter follow-up, hub {hub_url}",
        }
    if platform == "vimeo":
        parsed = parse_vimeo_video(video_url)
        if not parsed:
            return None
        return {
            "host": "vimeo.com",
            "match": f"vimeo:{parsed[0]}",
            "gov_id": gov_id,
            "strength": "fallback",
            "source": "wo230",
            "evidence": f"{name}, {state} -- WO-230 AgendaCenter follow-up, hub {hub_url}",
        }
    # Own-tenant single-government host (civicclerk/cablecast/granicus/
    # swagit/etc subdomain) -- not in MULTI_GOV_HOSTS, blank match is the
    # normal, safe shape (see app/utils/jurisdiction_data/tenant_overrides.csv's
    # existing civicweb.net rows). write_pin_row() itself refuses a blank
    # match unconditionally, so this is staged and merged directly.
    #
    # Real, confirmed miss (WO-230, 2026-09-11): `boxcast.tv` is itself a
    # MULTI_GOV_HOSTS host (app/utils/gov_registry/registry.py's own
    # comment -- no adapter resolves it yet, but a blank-match row would
    # still be wrong the moment one exists), and this branch wrote one
    # for Valparaiso city, IN before anything caught it -- CI's own
    # `test_no_blank_match_row_on_a_multi_gov_host` is what caught it.
    # Any platform this branch doesn't already special-case above (not
    # just youtube/vimeo) must refuse a blank match on a multi-gov host
    # rather than assume "own-tenant" -- no pin at all is always safe;
    # the `gov_id` already rode in the ingest/queue payload directly.
    host = urlparse(video_url or hub_url).netloc.lower()
    if not host or is_multi_gov_host(host):
        return None
    return {
        "host": host,
        "match": "",
        "gov_id": gov_id,
        "strength": "fallback",
        "source": "wo230",
        "evidence": f"{name}, {state} -- WO-230 AgendaCenter follow-up, hub {hub_url}, own-tenant host",
    }


def stage_pin(pin: dict) -> None:
    if not pin or DRY_RUN:
        return
    is_new = not PINS_STAGED_CSV.exists()
    with PINS_STAGED_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=["host", "match", "gov_id", "strength", "source", "evidence"]
        )
        if is_new:
            w.writeheader()
        w.writerow(pin)


def merge_pins_into_tenant_overrides() -> int:
    """Blank-match pins (own-tenant hosts) staged by this script go
    straight into tenant_overrides.csv, deduped against (tenant_host,
    match) -- write_pin_row()'s own dedupe key. Non-blank-match pins
    (YouTube/Vimeo) are ALSO merged here (finish_candidate() already
    writes those for the tier-3 path via write_pin_row(); tier-1/2 pins
    from this script are staged the same way and merged here too, so
    there is exactly one merge step regardless of tier)."""
    if not PINS_STAGED_CSV.exists():
        return 0
    with PINS_STAGED_CSV.open(newline="", encoding="utf-8") as f:
        staged = list(csv.DictReader(f))
    if not staged:
        return 0
    existing_keys = set()
    if TENANT_OVERRIDES_CSV.exists():
        with TENANT_OVERRIDES_CSV.open(newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                existing_keys.add((r.get("tenant_host", ""), r.get("match", "")))
    written = 0
    rows_to_write = []
    for p in staged:
        key = (p["host"], p["match"])
        if key in existing_keys:
            continue
        if not p["host"] or not p["gov_id"]:
            continue
        existing_keys.add(key)
        rows_to_write.append(p)
        written += 1
    if rows_to_write:
        is_new = not TENANT_OVERRIDES_CSV.exists()
        with TENANT_OVERRIDES_CSV.open("a", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
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
                w.writeheader()
            for p in rows_to_write:
                w.writerow(
                    {
                        "tenant_host": p["host"],
                        "match": p["match"],
                        "gov_id": p["gov_id"],
                        "strength": p["strength"],
                        "source": p["source"],
                        "evidence": p["evidence"],
                    }
                )
    PINS_STAGED_CSV.unlink()
    return written


# --------------------------------------------------------------------------
# Report / resumability
# --------------------------------------------------------------------------


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
        out = {f: row.get(f, "") for f in REPORT_FIELDS}
        self._writer.writerow(out)
        self._f.flush()

    def close(self):
        self._f.close()


def append_csv_row(path: Path, fieldnames, row: dict):
    is_new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if is_new:
            w.writeheader()
        w.writerow({k: row.get(k, "") for k in fieldnames})


def load_done_gov_ids(path) -> set:
    """A gov_id is 'done' (skipped on resume) once its LAST recorded row
    has a non-empty outcome that isn't WO-249's own `awaiting_hand_read`
    placeholder. The report is append-only (see ReportWriter.write), so a
    gov_id parked awaiting a hand read and later resolved (once a
    decision exists in HAND_READ_DECISIONS_CSV) has two rows; the later
    one wins. This is what lets a WO-249 run naturally pick a parked
    government back up on its next invocation, through the same
    resumability mechanism WO-230 already used, rather than needing a
    separate 'apply' mode."""
    if not path.exists():
        return set()
    last_outcome: dict = {}
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            gov_id = r.get("gov_id")
            if gov_id:
                last_outcome[gov_id] = (r.get("outcome") or "").strip()
    return {
        gov_id
        for gov_id, outcome in last_outcome.items()
        if outcome and outcome != "awaiting_hand_read"
    }


def load_hand_read_decisions(path) -> dict:
    """Keyed by (gov_id, video_url) -> decision row. Populated by a human
    reading `wo249_pending_hand_read.csv` and recording, per row, whether
    the video is really a public-body meeting of THAT government -- see
    the module comment above PENDING_HAND_READ_CSV."""
    if not path.exists():
        return {}
    out = {}
    with path.open(newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            key = (r.get("gov_id") or "", r.get("video_url") or "")
            out[key] = r
    return out


_HAND_READ_DECISIONS: dict = {}


async def _fetch_description_snippet(video_url: str, platform: str) -> str:
    """Best-effort extra context for the human hand-read step, for when
    title + channel alone aren't decisive (WO-230's own real case: Duncan
    OK's interview feature, Washougal WA's FAQ session, and Fairburn GA's
    leadership-training video all had a meeting-shaped title AND a
    channel that matched the government's own name -- only the
    description said what the video actually was). YouTube only, since
    that's where every one of those three misses came from; failure is
    silent and leaves the snippet blank rather than blocking the gate --
    the human reading the pending file can still open the URL directly."""
    if platform != "youtube" or yt_dlp is None or not video_url:
        return ""
    vid = YouTubeAssetFinder.extract_video_id(video_url)
    if not vid:
        return ""
    ydl_opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "ignoreerrors": True,
    }
    try:
        info = await asyncio.to_thread(_yt_extract_info_sync, vid, ydl_opts)
    except Exception:
        return ""
    if not info:
        return ""
    return (info.get("description") or "")[:300].replace("\n", " ").replace("\r", " ")


def _yt_extract_info_sync(vid: str, ydl_opts: dict):
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(
            f"https://www.youtube.com/watch?v={vid}", download=False
        )


def load_queue_urls(path) -> set:
    if not path.exists():
        return set()
    urls = set()
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line:
            urls.add(line.split("\t", 1)[0])
    return urls


_queue_urls: set = set()

# --------------------------------------------------------------------------
# Video candidate resolution + hand-check + tier decision
# --------------------------------------------------------------------------


async def resolve_and_finish(
    session,
    gov_id,
    name,
    state,
    gov_kind,
    unit_name,
    url,
    platform,
    hub_url,
    row,
    is_own_channel=False,
):
    """Resolves `url` through the real adapter, wrong-gov check, hand
    check, then ingests (tier1/2, gov_id in payload) or finishes (tier3,
    via queue_probe.finish_candidate()). Returns True if this candidate
    became the government's outcome (row already updated + written by
    the caller is NOT done here -- caller writes row); False means try
    the next candidate."""
    try:
        finder = get_finder(platform)
    except UnsupportedPlatformError:
        row["note"] = (row.get("note", "") + f"; unsupported platform {platform}")[:500]
        return False
    try:
        result = await finder.resolve(url)
    except CalendarPageError as e:
        picked, reason = pick_calendar_candidate(e.candidates)
        if not picked:
            row["note"] = (row.get("note", "") + f"; {platform} listing, {reason}")[
                :500
            ]
            return False
        try:
            result = await get_finder(detect_platform(picked["url"])).resolve(
                picked["url"]
            )
        except Exception as e2:
            row["note"] = (row.get("note", "") + f"; nested resolve failed: {e2}")[:500]
            return False
        url = picked["url"]
        result.title = result.title or picked.get("title")
        result.date = result.date or picked.get("date")
    except Exception as e:
        row["note"] = (row.get("note", "") + f"; {platform} resolve raised: {e}")[:500]
        return False

    if not result.video_url:
        row["note"] = (row.get("note", "") + "; resolved but no video_url")[:500]
        return False

    wrong = _looks_wrong_government(
        {
            "state": state,
            "gov_kind": "municipality" if gov_kind == "township" else gov_kind,
        },
        {
            "jurisdiction": result.jurisdiction or "",
            "meeting_body": getattr(result, "meeting_body", "") or "",
            "title": result.title or "",
        },
    )
    channel_text = " ".join(
        filter(
            None,
            [
                (getattr(result, "video_channel", None) or "").lstrip("@"),
                channel_name_from_url(url),
                result.jurisdiction or "",
            ],
        )
    )
    hand = classify_video_hand_check(result.title, channel_text, unit_name, gov_kind)

    hand_check_verdict = "ok"
    if wrong:
        hand_check_verdict = f"wrong-government: {wrong}"
    elif hand:
        kind, reason = hand
        hand_check_verdict = f"kind-{kind.lower()}: {reason}"

    append_csv_row(
        HAND_CHECK_LOG_CSV,
        HAND_CHECK_FIELDS,
        {
            "gov_id": gov_id,
            "name": name,
            "state": state,
            "kind": (
                "A"
                if (wrong or (hand and hand[0] == "A"))
                else ("B" if hand and hand[0] == "B" else "")
            ),
            "reason": wrong or (hand[1] if hand else ""),
            "title": result.title or "",
            "video_channel": getattr(result, "video_channel", "") or "",
            "video_url": result.video_url or "",
            "meeting_url": url,
            "verdict": hand_check_verdict,
        },
    )

    if wrong or (hand and hand[0] == "A"):
        # Kind A: channel belongs to another real public body. Record the
        # owner for a later mint pass; do NOT key it to this government.
        append_csv_row(
            OWNER_BODIES_CSV,
            OWNER_BODIES_FIELDS,
            {
                "owner_name": result.jurisdiction
                or getattr(result, "video_channel", "")
                or "",
                "channel": getattr(result, "video_channel", "") or "",
                "video_url": result.video_url or "",
                "gov_id_if_known": "",
                "found_for_gov_id": gov_id,
                "found_for_name": unit_name,
                "note": (wrong or (hand[1] if hand else ""))[:300],
            },
        )
        row["hand_check"] = "kind-A"
        row["note"] = (
            row.get("note", "") + f"; kind-A owner body: {wrong or hand[1]}"
        )[:500]
        return False

    if hand and hand[0] == "B":
        row["hand_check"] = "kind-B"
        row["note"] = (
            row.get("note", "") + f"; kind-B wrong video on right channel: {hand[1]}"
        )[:500]
        return False

    # This WO's own real, confirmed gap (see the module comment above
    # `_REQUIRED_MEETING_WORD_RE`): 10 of 19 hand-checked videos in this
    # sweep's own pilot were wrong in a shape the shared phrase lists
    # never covered -- a real, off-mission video from this government's
    # OWN channel, or the wrong government's real meeting entirely, with
    # no phrase to match against. Checked independently (either failing
    # is its own reject), not ANDed, since a title alone caught most of
    # them but one (Douglas County WI's "Common Council Meeting" --
    # itself a meeting-shaped title, just the City of Superior's, not
    # the county's) needed the channel check instead.
    if not looks_like_deliberative_meeting(result.title or ""):
        row["hand_check"] = "kind-B"
        row["note"] = (
            row.get("note", "")
            + f"; kind-B (WO-230 own check): title {result.title!r} has no meeting-shaped word"
        )[:500]
        return False
    if not channel_name_plausible(channel_text, unit_name):
        row["hand_check"] = "kind-A"
        row["note"] = (
            row.get("note", "")
            + f"; kind-A (WO-230 own check): channel {channel_text!r} shares no word with {unit_name!r}"
        )[:500]
        append_csv_row(
            OWNER_BODIES_CSV,
            OWNER_BODIES_FIELDS,
            {
                "owner_name": channel_text,
                "channel": getattr(result, "video_channel", "") or "",
                "video_url": result.video_url or "",
                "gov_id_if_known": "",
                "found_for_gov_id": gov_id,
                "found_for_name": unit_name,
                "note": f"channel name shares no word with the government's own name (title: {result.title!r})"[
                    :300
                ],
            },
        )
        return False

    # WO-249's hand-read gate: everything above is automatic (the shared
    # phrase-based checks plus WO-230's own title/channel checks). A
    # candidate that clears all of it still cannot become a page or
    # queue line without a human having actually read its title,
    # channel, and (when those aren't decisive) its description, and
    # recorded a one-line reason -- see the module comment above
    # PENDING_HAND_READ_CSV. No decision yet: park it and stop here for
    # this run; a later run (once a decision exists) resumes this exact
    # gov_id via `load_done_gov_ids()` and reaches this same point again.
    meeting_url = url
    tier = "tier1" if result.segments else "tier3"
    decision_key = (gov_id, result.video_url or "")
    decision = _HAND_READ_DECISIONS.get(decision_key)

    if decision is None:
        description_snippet = await _fetch_description_snippet(
            result.video_url or "", platform
        )
        append_csv_row(
            PENDING_HAND_READ_CSV,
            PENDING_HAND_READ_FIELDS,
            {
                "gov_id": gov_id,
                "name": unit_name,
                "state": state,
                "title": result.title or "",
                "video_channel": channel_text,
                "description_snippet": description_snippet,
                "video_url": result.video_url or "",
                "meeting_url": meeting_url,
                "platform": platform,
                "hub_url": hub_url,
                "is_own_channel": "yes" if is_own_channel else "no",
                "tier": tier,
            },
        )
        row.update(
            outcome="awaiting_hand_read",
            hand_check="awaiting-hand-read",
            meeting_url=meeting_url,
            video_url=result.video_url or "",
            tier=tier,
            note=(
                row.get("note", "")
                + "; parked for WO-249 hand read (wo249_pending_hand_read.csv)"
            )[:500],
        )
        return True

    append_csv_row(
        HAND_CHECK_LOG_CSV,
        HAND_CHECK_FIELDS,
        {
            "gov_id": gov_id,
            "name": name,
            "state": state,
            "kind": decision.get("kind", ""),
            "reason": decision.get("reason", ""),
            "title": result.title or "",
            "video_channel": getattr(result, "video_channel", "") or "",
            "video_url": result.video_url or "",
            "meeting_url": meeting_url,
            "verdict": f"hand-read-{decision.get('decision', '')}: {decision.get('reason', '')}",
        },
    )

    if decision.get("decision") == "reject":
        kind = (decision.get("kind") or "B").strip().upper()
        reason = decision.get("reason", "")
        if kind == "A":
            append_csv_row(
                OWNER_BODIES_CSV,
                OWNER_BODIES_FIELDS,
                {
                    "owner_name": channel_text,
                    "channel": getattr(result, "video_channel", "") or "",
                    "video_url": result.video_url or "",
                    "gov_id_if_known": "",
                    "found_for_gov_id": gov_id,
                    "found_for_name": unit_name,
                    "note": f"WO-249 hand read: {reason}"[:300],
                },
            )
            row["hand_check"] = "kind-A"
            row["note"] = (
                row.get("note", "") + f"; kind-A (WO-249 hand read): {reason}"
            )[:500]
        else:
            row["hand_check"] = "kind-B"
            row["note"] = (
                row.get("note", "") + f"; kind-B (WO-249 hand read): {reason}"
            )[:500]
        return False

    row["hand_check"] = "ok"
    row["note"] = (
        row.get("note", "") + f"; hand-read approved: {decision.get('reason', '')}"
    )[:500]
    row.update(meeting_url=meeting_url, video_url=result.video_url or "", tier=tier)

    if tier == "tier1":
        if DRY_RUN:
            row["outcome"] = "dry-run-tier1"
            return True
        payload = result.model_dump()
        payload["gov_id"] = gov_id
        payload["jurisdiction"] = unit_name
        try:
            response = await _ingest(
                session,
                payload,
                normalize_url(meeting_url),
                already_probed=False,
                caller="wo230",
            )
            page_url = response.get("url") if response else None
            row.update(outcome="ingested_tier1_2", page_url=page_url or "")
        except IngestGateRejected as e:
            row.update(
                outcome="rejected_by_probe", note=(row.get("note", "") + f"; {e}")[:500]
            )
            return True
        except Exception as e:
            row.update(
                outcome="error",
                note=(row.get("note", "") + f"; ingest raised: {e}")[:500],
            )
            return True
        pin = derive_pin(
            gov_id, name, state, meeting_url, platform, hub_url, is_own_channel
        )
        stage_pin(pin)
        return True

    # tier3
    if meeting_url in _queue_urls:
        row["note"] = (row.get("note", "") + "; already queued (duplicate)")[:500]
        return False
    if DRY_RUN:
        row["outcome"] = "dry-run-tier3"
        return True
    pin = derive_pin(
        gov_id, name, state, meeting_url, platform, hub_url, is_own_channel
    )
    outcome = await queue_probe.finish_candidate(
        meeting_url,
        video_url=result.video_url,
        source_url=hub_url,
        platform=platform,
        gov_id=gov_id,
        jurisdiction=unit_name,
        title=result.title or "",
        pin=pin,
        sidecar_path=SIDECAR_CSV,
        queue_path=QUEUE_FILE,
        deferred_path=DEFERRED_FILE,
        pins_path=TENANT_OVERRIDES_CSV,
        caller="wo230",
    )
    if outcome.action in ("queued", "already-queued"):
        row["outcome"] = "queued_tier3"
        _queue_urls.add(meeting_url)
        return True
    if outcome.action in ("deferred", "already-deferred"):
        row["outcome"] = "deferred_long"
        return True
    if outcome.action == "skipped-deferred":
        row["outcome"] = "deferred_long"
        row["note"] = (
            row.get("note", "")
            + "; already in the deferred file, stays out of the queue"
        )[:500]
        return True
    # rejected
    row["outcome"] = "rejected_by_probe"
    row["reject_reason"] = "rejected-by-probe"
    row["note"] = (
        row.get("note", "")
        + f"; probe rejected: {outcome.probe.verdict} ({outcome.probe.reason})"
    )[:500]
    return True


# --------------------------------------------------------------------------
# Per-government processing
# --------------------------------------------------------------------------


async def process_government(session, cand, report) -> str:
    gov_id = cand["gov_id"]
    name = cand["name"]
    state = cand["state"]
    gov_kind = (cand.get("gov_kind") or "").strip().lower()
    population = cand.get("population") or ""
    domain = normalize_domain(cand.get("domain") or "")
    hub_url = (cand.get("hub_url") or "").strip()
    unit_name = f"{name}, {state}"

    row = {f: "" for f in REPORT_FIELDS}
    row.update(
        gov_id=gov_id, name=name, state=state, population=population, domain=domain
    )

    if not domain or not hub_url:
        row.update(outcome="error", note="empty domain or hub_url")
        report.write(row)
        return "ok"

    fetcher = hsw.Fetcher(session, budget=PER_GOV_FETCH_BUDGET)

    # --- Step 1: fetch the recorded AgendaCenter, count ViewFile links ---
    try:
        ac_final, ac_html = await fetcher.get(hub_url)
    except hsw.FetchError as e:
        if e.kind == "cloudflare":
            row.update(
                outcome="blocked",
                reject_reason="cloudflare-challenge-blocked",
                note=str(e),
            )
            report.write(row)
            return "ok"
        if e.kind == "dns":
            row.update(outcome="blocked", reject_reason="dns-unresolvable", note=str(e))
            report.write(row)
            return "connect-error"
        row.update(outcome="blocked", reject_reason="blocked-plain-http", note=str(e))
        report.write(row)
        return "connect-error"

    viewfile_count = count_viewfile_links(ac_html)
    row["agendacenter_viewfile_count"] = viewfile_count
    shell = viewfile_count == 0
    row["shell"] = "yes" if shell else "no"

    video_found = None  # (url, platform, is_own_channel)

    if not shell:
        finder = CivicPlusAssetFinder()
        try:
            rows, _fragments, _note = await hsw.civicplus_walk(
                fetcher, ac_final, ac_html, finder
            )
        except hsw.FetchError:
            rows = []
        video_rows = [r for r in rows if r.get("url")]
        if video_rows:
            picked, reason = pick_calendar_candidate(video_rows)
            if not picked and len(video_rows) == 1:
                picked = video_rows[0]
            if picked:
                video_found = (picked["url"], detect_platform(picked["url"]), False)
                row["real_hub_url"] = ac_final
                row["real_hub_kind"] = "agendacenter"

    # --- Step 2: shell, or a real AgendaCenter with no video -> home page + nav hop search ---
    if video_found is None:
        home_url = f"https://{domain}/"
        try:
            home_final, home_html = await fetcher.get(home_url)
        except hsw.FetchError as e:
            if e.kind == "cloudflare":
                row.update(
                    outcome="blocked",
                    reject_reason="cloudflare-challenge-blocked",
                    note=str(e),
                )
                report.write(row)
                return "ok"
            if e.kind == "dns":
                row.update(
                    outcome="blocked",
                    reject_reason="dns-unresolvable",
                    note=f"AgendaCenter shell={shell}; home page: {e}",
                )
                report.write(row)
                return "connect-error"
            # An access failure (SSL/connection/timeout), not a content
            # finding -- the home page couldn't be looked at, which is a
            # different, retryable-later class from "looked and it wasn't
            # there" (ENUMERATION_METHODS.md #23's access/content split).
            row.update(
                outcome="blocked",
                reject_reason="blocked-plain-http",
                note=f"AgendaCenter shell={shell}; home page: {e}",
            )
            report.write(row)
            return "connect-error"

        pages = [(home_final, home_html)]
        for nav_url in find_nav_links(home_html, home_final):
            try:
                nf, nh = await fetcher.get(nav_url)
                pages.append((nf, nh))
            except hsw.FetchError:
                continue

        platform_candidates = []  # (kind, url, platform, source_page_url)
        hop_candidates = []  # (kind, url)
        channel_holder = [""]
        for purl, phtml in pages:
            match = find_platform_link(phtml, purl)
            if match:
                pcand = _real_platform_candidate(match, channel_holder, purl)
                if pcand:
                    platform_candidates.append(pcand)
            if not channel_holder[0]:
                yt = find_youtube_channel(phtml, purl)
                if yt:
                    channel_holder[0] = yt
            for kind, link in find_meeting_path_links(phtml, purl):
                hop_candidates.append((kind, link))
        channel_link = channel_holder[0]

        # No candidate anywhere, but pages loaded fine -> one headless
        # render of the home page (budget-gated), then redo the scan.
        if (
            not platform_candidates
            and not hop_candidates
            and not channel_link
            and home_html.strip()
            and looks_like_js_shell(home_html)
        ):
            rendered = await maybe_render_headless(home_final)
            if rendered:
                match = find_platform_link(rendered, home_final)
                if match:
                    pcand = _real_platform_candidate(match, channel_holder, home_final)
                    if pcand:
                        platform_candidates.append(pcand)
                if not channel_holder[0]:
                    yt = find_youtube_channel(rendered, home_final)
                    if yt:
                        channel_holder[0] = yt
                channel_link = channel_holder[0]
                for kind, link in find_meeting_path_links(rendered, home_final):
                    hop_candidates.append((kind, link))

        tried_any = False
        # Priority 1: direct platform links found on home/nav pages.
        for kind, plink, platform, source_page_url in platform_candidates[
            :MAX_HOP_CANDIDATES
        ]:
            # The real hub is the PAGE the link was found on (a browsable
            # home/nav page a reader could actually land on) -- never the
            # bare video/platform link itself, even though `plink` is
            # what actually gets resolved below.
            row["real_hub_url"] = source_page_url
            row["real_hub_kind"] = kind
            row["platform_found"] = platform
            tried_any = True
            resolved_url = plink
            if platform == "civicclerk" and not re.search(
                r"/event/\d+", urlparse(plink).path
            ):
                event_url, reason = await civicclerk_latest_event_url(session, plink)
                if not event_url:
                    row["note"] = (
                        row.get("note", "") + f"; civicclerk portal, {reason}"
                    )[:500]
                    continue
                resolved_url = event_url
            ok = await resolve_and_finish(
                session,
                gov_id,
                name,
                state,
                gov_kind,
                unit_name,
                resolved_url,
                platform,
                hub_url,
                row,
            )
            if ok:
                report.write(row)
                return "ok"

        # Priority 2: follow one hop into a numeric-path/archive/document
        # center page, then look for a platform link there.
        for kind, hop_url in hop_candidates[:MAX_HOP_CANDIDATES]:
            try:
                hf, hh = await fetcher.get(hop_url)
            except hsw.FetchError:
                continue
            match = find_platform_link(hh, hf)
            if match:
                plink, platform = match
                if platform in ("unknown", "civicplus"):
                    continue
                if platform == "youtube" and not YouTubeAssetFinder.extract_video_id(
                    plink
                ):
                    if not channel_link:
                        channel_link = plink
                    continue
                row["real_hub_url"] = hf
                row["real_hub_kind"] = (
                    "civicclerk-embed" if platform == "civicclerk" else kind
                )
                row["platform_found"] = platform
                resolved_url = plink
                if platform == "civicclerk" and not re.search(
                    r"/event/\d+", urlparse(plink).path
                ):
                    event_url, reason = await civicclerk_latest_event_url(
                        session, plink
                    )
                    if not event_url:
                        row["note"] = (
                            row.get("note", "") + f"; civicclerk portal, {reason}"
                        )[:500]
                        continue
                    resolved_url = event_url
                tried_any = True
                ok = await resolve_and_finish(
                    session,
                    gov_id,
                    name,
                    state,
                    gov_kind,
                    unit_name,
                    resolved_url,
                    platform,
                    hub_url,
                    row,
                )
                if ok:
                    report.write(row)
                    return "ok"
            else:
                # No platform link on this hop page. A page with ordinary
                # document/nav links that simply isn't a platform link is
                # its own real finding (recorded below); render headless
                # ONLY when the page is genuinely near-empty of anchors
                # (a client-rendered shell), not on every ordinary miss.
                if looks_like_js_shell(hh):
                    rendered = await maybe_render_headless(hf)
                    if rendered:
                        match2 = find_platform_link(rendered, hf)
                        if match2:
                            plink, platform = match2
                            if platform == "youtube" and not (
                                YouTubeAssetFinder.extract_video_id(plink)
                            ):
                                if not channel_link:
                                    channel_link = plink
                            elif platform not in ("unknown", "civicplus"):
                                row["real_hub_url"] = hf
                                row["real_hub_kind"] = (
                                    "civicclerk-embed"
                                    if platform == "civicclerk"
                                    else kind
                                )
                                row["platform_found"] = platform
                                tried_any = True
                                ok = await resolve_and_finish(
                                    session,
                                    gov_id,
                                    name,
                                    state,
                                    gov_kind,
                                    unit_name,
                                    plink,
                                    platform,
                                    hub_url,
                                    row,
                                )
                                if ok:
                                    report.write(row)
                                    return "ok"
                # No video here -- but a real document/agenda hub was
                # found (kind already tells us which). Record it as the
                # real hub if nothing better has been found yet.
                if not row["real_hub_url"]:
                    row["real_hub_url"] = hf
                    row["real_hub_kind"] = kind
                tried_any = True

        # Priority 3: the government's own YouTube channel (footer/social
        # link on its own site -- ownership already established).
        if channel_link:
            vid, title, uploader = pick_channel_meeting_video(channel_link)
            if vid:
                row["real_hub_url"] = channel_link
                row["real_hub_kind"] = "channel-only"
                row["platform_found"] = "youtube"
                tried_any = True
                video_url = f"https://www.youtube.com/watch?v={vid}"
                ok = await resolve_and_finish(
                    session,
                    gov_id,
                    name,
                    state,
                    gov_kind,
                    unit_name,
                    video_url,
                    "youtube",
                    hub_url,
                    row,
                    is_own_channel=True,
                )
                if ok:
                    report.write(row)
                    return "ok"
            elif not row["real_hub_url"]:
                row["real_hub_url"] = channel_link
                row["real_hub_kind"] = "channel-only"
                row["platform_found"] = "youtube"
                tried_any = True

        # Nothing became a page or queue line.
        if not row["real_hub_url"]:
            row.update(
                outcome="no_meeting_nor_video",
                reject_reason="no-meeting-nor-video",
                note=(
                    row.get("note", "")
                    + f"; AgendaCenter shell={shell}, home+{len(pages) - 1} nav page(s), no candidate link found"
                )[:500],
            )
        else:
            row.update(
                outcome="meeting_without_video"
                if tried_any
                else "no_meeting_nor_video",
                reject_reason="meeting-without-video"
                if tried_any
                else "no-meeting-nor-video",
            )
        report.write(row)
        return "ok"

    # video_found came from step 1 (real AgendaCenter)
    url, platform, is_own_channel = video_found
    row["platform_found"] = platform
    ok = await resolve_and_finish(
        session,
        gov_id,
        name,
        state,
        gov_kind,
        unit_name,
        url,
        platform,
        hub_url,
        row,
        is_own_channel,
    )
    if not ok:
        # A kind-A/kind-B hand-check catch or a plain "no video_url" both
        # land here -- this government's own AgendaCenter is real but
        # produced no usable video, same bucket as step 2's own no-video
        # outcome (row["note"] already carries which one happened).
        row.update(
            outcome="meeting_without_video", reject_reason="meeting-without-video"
        )
    report.write(row)
    return "ok"


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------


async def main():
    global DRY_RUN, _headless_used, _HAND_READ_DECISIONS
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--candidates", type=Path, default=CANDIDATES_CSV)
    ap.add_argument("--report", type=Path, default=REPORT_CSV)
    ap.add_argument("--skip-covered-fetch", action="store_true")
    ap.add_argument(
        "--hand-read-decisions",
        type=Path,
        default=HAND_READ_DECISIONS_CSV,
        help="WO-249: CSV of (gov_id, video_url) -> decision/kind/reason, "
        "filled in by a human reading wo249_pending_hand_read.csv",
    )
    args = ap.parse_args()
    DRY_RUN = args.dry_run

    register_all_finders()

    global _queue_urls
    _queue_urls = load_queue_urls(QUEUE_FILE)
    _headless_used = load_headless_used()
    _HAND_READ_DECISIONS = load_hand_read_decisions(args.hand_read_decisions)
    print(f"{len(_HAND_READ_DECISIONS)} hand-read decisions loaded")

    with args.candidates.open(newline="", encoding="utf-8") as f:
        candidates = list(csv.DictReader(f))
    print(f"{len(candidates)} total candidates")

    done = load_done_gov_ids(args.report)
    todo = [c for c in candidates if c["gov_id"] not in done]
    print(f"{len(done)} already processed, {len(todo)} to go")

    if args.skip_covered_fetch:
        covered_ids = set()
    else:
        print("fetching already-covered gov_ids from a fresh export...")
        covered_ids = fetch_covered_gov_ids()
        print(f"{len(covered_ids)} gov_ids already have an Archive page")
    todo = [c for c in todo if c["gov_id"] not in covered_ids]
    print(f"{len(todo)} to go after excluding already-covered")

    if args.limit:
        todo = todo[: args.limit]
        print(f"--limit {args.limit}: processing {len(todo)} this run")

    report = ReportWriter(args.report)
    consecutive_errors = 0
    processed = 0
    try:
        async with aiohttp.ClientSession() as session:
            for cand in todo:
                try:
                    status = await asyncio.wait_for(
                        process_government(session, cand, report),
                        timeout=PER_GOV_WALLCLOCK_CAP,
                    )
                except asyncio.TimeoutError:
                    fallback = {f: "" for f in REPORT_FIELDS}
                    fallback.update(
                        gov_id=cand["gov_id"],
                        name=cand["name"],
                        state=cand["state"],
                        population=cand.get("population") or "",
                        domain=normalize_domain(cand.get("domain") or ""),
                        outcome="error",
                        note=f"exceeded the {PER_GOV_WALLCLOCK_CAP}s per-government wall-clock cap",
                    )
                    report.write(fallback)
                    status = "connect-error"
                processed += 1
                if status == "connect-error":
                    consecutive_errors += 1
                else:
                    consecutive_errors = 0
                if consecutive_errors >= CONSECUTIVE_ERROR_HALT:
                    print(
                        f"[HALT] {CONSECUTIVE_ERROR_HALT} consecutive connect errors -- stopping after {processed} (resumable)"
                    )
                    break
                if processed % 50 == 0:
                    print(f"--- {processed}/{len(todo)} processed this run ---")
                    merge_pins_into_tenant_overrides()
                await asyncio.sleep(GOV_DELAY)
    finally:
        report.close()
        merge_pins_into_tenant_overrides()

    with args.report.open(newline="", encoding="utf-8") as f:
        results = list(csv.DictReader(f))
    by_outcome = {}
    for r in results:
        by_outcome[r["outcome"]] = by_outcome.get(r["outcome"], 0) + 1
    print("\n=== SUMMARY (cumulative across all runs) ===")
    for outcome, count in sorted(by_outcome.items(), key=lambda x: -x[1]):
        print(f"outcome {outcome}: {count}")
    print(f"Full report: {args.report}")
    print(f"Headless renders used so far: {_headless_used}/{HEADLESS_TOTAL_BUDGET}")


if __name__ == "__main__":
    asyncio.run(main())
