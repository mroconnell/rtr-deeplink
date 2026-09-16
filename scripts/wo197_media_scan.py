#!/usr/bin/env python3
"""WO-197 (2026-09-11): check the 2,517 "listing found, no platform link"
governments WO-179 left behind for direct video/audio, a one-hop link to
a page that has it, and RSS/Atom/ICS feeds.

Ryan's doubt this tests: WO-179 recorded a government as `listing_found
== yes` the moment `scripts/wo176_path_pilot.py`'s `classify_body()`
saw a real agenda/meeting listing -- it never ran that page through this
app's own generic-fallback media scan (`app/platforms/media_scan.py`'s
`scan_media_urls()`, the same detector `GenericFallbackAssetFinder` uses
at resolve time) or `app/platforms/base.py`'s `detect_platform()` over
every outbound link on the page. A WordPress agenda page, a Revize or
Town Web listing, or a `/?s=agenda` search result can easily carry a
direct video/audio link, an embedded player, or a link one hop in to a
meeting page that has the video -- none of which trip WO-179's narrower
"does this page link straight to a known per-tenant platform tenant"
check. This module is the read-only discovery/scan step; ingestion is
`scripts/wo197_ingest_hits.py`, same split as WO-179's own
`wo179_family_scale.py` / `wo179_ingest_hits.py` pair.

WO-184's one-hop check is a DIFFERENT thing and this script does not
duplicate it: that one hops to a government's ALTERNATE domain
(`scripts/coverage_alternates.py`'s `one_hop_alternate()`), never to a
same-domain meeting-detail link on the primary listing page itself.

Detection, in order, on the listing page and (only if the listing page
itself has no hit) up to 3 same-domain "meeting-shaped" hop pages:
  (a) every `<a href>`/`<iframe src>`/`<video src>`/`<audio src>`/
      `<source src>` classified with `detect_platform()` (youtube,
      vimeo, wistia, telvue, cablecast, iqm2, townhallstreams, granicus,
      civicclerk, legistar, escribe, primegov, viebit, swagit, ... --
      the exact registry `app/platforms/__init__.py` wires up, so a hit
      here can go straight into the normal resolve/ingest pipeline);
      plus five hosts `detect_platform()` doesn't register at all
      (facebook video posts, boxcast, livestream.com, a SharePoint
      `:v:` share link, Google Drive/Dropbox) recorded honestly as
      "found, not ingestable by this repo's adapters yet" rather than
      silently dropped; plus direct media files via `scan_media_urls()`
      (the same regex sweep Granicus/Swagit/generic-fallback already
      share) and inline-JS-embedded YouTube ids
      (`GenericFallbackAssetFinder._find_youtube_video_id()`).
  (b) one hop, same domain only: the newest-looking 3 links whose href
      or link text names a date and a meeting word (agenda, minutes,
      meeting, council, board, commission) -- an off-domain outbound
      link is already caught by (a) directly (it IS a platform hit, no
      need to fetch it first). "Newest" is a best-effort date parse off
      the link text/href; ties keep document order. Never more than 4
      requests per government beyond the listing page itself (3 hops +
      1 feed confirmation, matching the work order's "up to 5 requests
      each").
  (c) feed links: `<link rel=alternate type=.../rss+xml|atom+xml>`,
      `/feed`, `/feed/`, `/rss`, `?feed=rss2`, CivicPlus's own
      `RSSFeed.aspx?ModID=`, and `.ics` calendar links -- found for
      free off HTML already fetched; one extra GET confirms it answers
      before it's recorded (never a full feed body fetch).

Outcomes per government: `video-found` / `audio-found` (a real hit,
`media_kind` says what), `feed-found` (no media, but a feed answered),
`agenda-only-confirmed` (real listing, nothing else), `page-gone` (DNS/
timeout/4xx-5xx), `blocked` (403 that survived a browser-headers retry,
or a dropped connection that survived one), `challenge` (a real
human-verification gate -- stopped immediately, never retried).

Politeness: identical shape to `scripts/wo179_family_scale.py` --
`asyncio.Semaphore`-bounded concurrency across many distinct government
domains via `asyncio.as_completed()`, with the 2-second delay applied
only between SEQUENTIAL requests to the SAME government's host (browser-
headers retry included), never across governments. Honest headers
first; browser headers only once per government, only after a 403 or a
dropped connection, never after a 404; a real human-verification
challenge marker stops that government immediately and is never
retried. Checkpointed every row (append-mode, resumable) rather than
batched, so a kill mid-run loses at most the one in-flight batch.

Usage (repo root, worktree venv):
    python scripts/wo197_build_candidates.py \\
        --wo179-report ~/Documents/rtr-business/research/wo179_report.csv \\
        --inventory-csv /tmp/wo197_inventory/meeting_inventory.csv \\
        --wo196-report ~/Documents/rtr-business/research/wo196_report.csv \\
        --out ~/Documents/rtr-business/research/wo197_candidates.csv
    python scripts/wo197_media_scan.py \\
        --candidates ~/Documents/rtr-business/research/wo197_candidates.csv \\
        --report ~/Documents/rtr-business/research/wo197_report.csv \\
        --concurrency 30
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set, Tuple
from urllib.parse import urljoin, urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.platforms.base import detect_platform  # noqa: E402
from app.platforms.generic_fallback import GenericFallbackAssetFinder  # noqa: E402
from app.platforms.media_scan import is_hls_url, scan_media_urls  # noqa: E402
from app.utils.url_guard import (  # noqa: E402
    MAX_RESPONSE_BYTES,
    BlockedURLError,
    read_capped_text,
)
from scripts.cms_fingerprint import HONEST_HEADERS  # noqa: E402
from scripts.wo176_path_pilot import CHALLENGE_MARKERS  # noqa: E402

REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=12)
HOST_DELAY_SECONDS = 2.0
MAX_HOP_REQUESTS = 3
MAX_CONSECUTIVE_ERRORS = 6
PER_GOVERNMENT_WALL_CLOCK_CAP = 90  # seconds -- see wo179_family_scale.py's
# identically-motivated cap; this government's own request budget (1 +
# 3 hops + 1 feed check, each capped at REQUEST_TIMEOUT plus the 2s host
# delay) is well under a minute in the worst real case.

# Verbatim from scripts/wo147_access_ladder_sweep.py (WO-141's original
# pilot values) -- not re-derived, see that file's own comment.
BROWSER_HEADERS = {
    "accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "accept-encoding": "gzip, deflate, br",
    "accept-language": "en-US,en;q=0.9",
    "priority": "u=0, i",
    "sec-ch-ua": '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "upgrade-insecure-requests": "1",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    ),
}

# Hosts detect_platform() doesn't register (no adapter in this repo yet)
# but the work order explicitly asks to detect: recorded honestly as a
# real hit with no ingest path, not silently dropped. Matched against
# netloc; the sharepoint case also requires ":v:" in the URL (a
# SharePoint *video* share link specifically, not any sharepoint.com
# URL). Facebook is handled separately by `_is_real_facebook_video()`
# below (see its own comment for why a plain netloc match is wrong).
_UNADAPTED_VIDEO_HOSTS = (
    ("boxcast.tv", "boxcast"),
    ("boxcast.com", "boxcast"),
    ("livestream.com", "livestream"),
    ("drive.google.com", "gdrive"),
    ("dropbox.com", "dropbox"),
)


# Real, confirmed live 2026-09-11 building this scan: a plain netloc
# match on "facebook.com" fires on a page's own social-share button
# (`facebook.com/sharer/sharer.php?u=...`) and on a bare page-profile
# link (`facebook.com/cabarruscounty`) far more often than on a real
# posted video -- both are noise, not a hit. Only a specific video post
# (`/videos/<id>`, `/watch/?v=<id>`, `/<page>/live/`) or an `fb.watch`
# short link (which only ever points at one specific video) counts.
def _is_real_facebook_video(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()
    if "fb.watch" in netloc:
        return True
    if "facebook.com" in netloc:
        if "/sharer" in path:
            return False
        if "/videos/" in path or path.startswith("/watch/") or "/live/" in path:
            return True
    return False


# The shared `app/platforms/youtube.py::_VIDEO_ID_RE` has a real,
# already-filed bug (BACKLOG.md, WO-195 2026-09-11): no end boundary
# after the 11-character id, so `youtube.com/embed/livestreaming`
# truncates to a fake id `livestreami`, and `.../embed/videoseries?
# list=...` (a playlist embed, not a video) truncates to `videoseries`.
# Rather than inherit that bug into this scan's own counts, or edit the
# shared regex as a side effect of an unrelated WO, this uses its own
# boundary-safe copy (adds the missing `(?![A-Za-z0-9_-])` lookahead)
# for classification purposes only. Also what tells a real video link
# apart from a bare channel/handle link (`youtube.com/@handle`,
# `/channel/UC...`, `/c/name`, `/user/name`) -- `detect_platform()`
# alone can't, since it returns "youtube" for any youtube.com/youtu.be
# URL; a channel link confirms the government's own channel (useful for
# the fallback-strength pin) but is not itself a video-found hit.
_YOUTUBE_VIDEO_ID_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:.*&)?v=|embed/|shorts/|live/|v/)|youtu\.be/)"
    r"([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])"
)

DIRECT_VIDEO_EXTS = (".mp4", ".m4v", ".mov")
DIRECT_AUDIO_EXTS = (".mp3", ".wav", ".m4a")

MEETING_LINK_WORDS = re.compile(
    r"agenda|minutes|meeting|council|board|commission", re.I
)
_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        [
            "jan",
            "feb",
            "mar",
            "apr",
            "may",
            "jun",
            "jul",
            "aug",
            "sep",
            "oct",
            "nov",
            "dec",
        ]
    )
}
_DATE_ISO_RE = re.compile(r"(20\d{2})[-/](\d{1,2})[-/](\d{1,2})")
_DATE_MONTHNAME_RE = re.compile(
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s*(\d{1,2})?,?\s*(20\d{2})",
    re.I,
)

FEED_HREF_MARKERS = ("/feed/", "/feed", "/rss", "?feed=rss2", "rssfeed.aspx?modid=")

SOURCE_TAG = "wo197_media_scan"

REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "gov_kind",
    "population",
    "family",
    "listing_url",
    "hop_urls",
    "media_kind",
    "media_url",
    "feed_url",
    "outcome",
    "reject_reason",
    "hit_url",
]


@dataclass
class Row:
    gov_id: str
    name: str
    state: str
    gov_kind: str
    population: str
    family: str = ""
    listing_url: str = ""
    hop_urls: str = ""
    media_kind: str = ""
    media_url: str = ""
    feed_url: str = ""
    outcome: str = ""
    reject_reason: str = ""
    hit_url: str = ""
    requests_made: int = field(default=0, compare=False)

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d.pop("requests_made", None)
        return d


class Aborted(Exception):
    pass


def _date_key(text: str) -> Optional[int]:
    """Best-effort (year, month, day) -> a single sortable int, or None
    if nothing date-shaped is in `text`. Missing month/day count as 0,
    so "2026" alone still sorts ahead of a link with no year at all."""
    m = _DATE_ISO_RE.search(text)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return y * 10000 + mo * 100 + d
    m = _DATE_MONTHNAME_RE.search(text)
    if m:
        mo = _MONTHS.get(m.group(1).lower(), 0)
        d = int(m.group(2)) if m.group(2) else 0
        y = int(m.group(3))
        return y * 10000 + mo * 100 + d
    m = re.search(r"\b(20\d{2})\b", text)
    if m:
        return int(m.group(1)) * 10000
    return None


def _classify_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """(bucket, media_kind) for a single candidate URL -- bucket is
    "platform" (a get_finder()-able adapter exists), "video_other" (a
    real video host with no adapter here yet), or (None, None) if this
    URL isn't a recognised video/audio host at all (direct-file
    detection is handled separately by scan_media_urls(), not here)."""
    platform = detect_platform(url)
    if platform == "youtube":
        if not _YOUTUBE_VIDEO_ID_RE.search(url):
            return None, None  # channel/handle/playlist link, not a specific video
        return "platform", "youtube"
    if platform and platform != "unknown":
        return "platform", platform
    if _is_real_facebook_video(url):
        return "video_other", "facebook"
    netloc = urlparse(url).netloc.lower()
    for marker, kind in _UNADAPTED_VIDEO_HOSTS:
        if marker in netloc:
            return "video_other", kind
    if "sharepoint.com" in netloc and ":v:" in url.lower():
        return "video_other", "sharepoint"
    return None, None


def find_media_hits(html: str, page_url: str) -> List[dict]:
    """Every direct video/audio/platform hit on one already-fetched
    page. Returns hits in document order; caller picks the first."""
    hits: List[dict] = []
    soup = BeautifulSoup(html, "html.parser")

    for tag in soup.find_all(("a", "iframe", "video", "audio", "source")):
        raw = tag.get("href") or tag.get("src")
        if not raw:
            continue
        url = urljoin(page_url, raw.strip())
        bucket, kind = _classify_url(url)
        if bucket:
            hits.append({"media_kind": kind, "media_url": url, "tag": tag.name})
            continue
        low = url.lower().split("?")[0]
        if (
            tag.name in ("video", "source")
            or low.endswith(DIRECT_VIDEO_EXTS)
            or is_hls_url(url)
        ):
            hits.append(
                {"media_kind": "direct-video", "media_url": url, "tag": tag.name}
            )
        elif tag.name == "audio" or low.endswith(DIRECT_AUDIO_EXTS):
            hits.append(
                {"media_kind": "direct-audio", "media_url": url, "tag": tag.name}
            )

    video_id = GenericFallbackAssetFinder._find_youtube_video_id(html)
    if video_id:
        hits.append(
            {
                "media_kind": "youtube",
                "media_url": f"https://www.youtube.com/watch?v={video_id}",
                "tag": "inline-js",
            }
        )

    for u in scan_media_urls(html, page_url):
        low = u.lower().split("?")[0]
        if (
            low.endswith(DIRECT_VIDEO_EXTS)
            or low.endswith((".webm", ".ogg"))
            or is_hls_url(u)
        ):
            hits.append({"media_kind": "direct-video", "media_url": u, "tag": "scan"})
        elif low.endswith(DIRECT_AUDIO_EXTS):
            hits.append({"media_kind": "direct-audio", "media_url": u, "tag": "scan"})

    seen: Set[str] = set()
    out = []
    for h in hits:
        if h["media_url"] not in seen:
            seen.add(h["media_url"])
            out.append(h)
    return out


def find_feed_links(html: str, page_url: str) -> List[str]:
    soup = BeautifulSoup(html, "html.parser")
    feeds: List[str] = []
    for link in soup.find_all("link"):
        rel = link.get("rel") or []
        if isinstance(rel, str):
            rel = [rel]
        if "alternate" not in [r.lower() for r in rel]:
            continue
        t = (link.get("type") or "").lower()
        href = link.get("href")
        if href and ("rss+xml" in t or "atom+xml" in t):
            feeds.append(urljoin(page_url, href.strip()))
    for a in soup.find_all("a", href=True):
        href = a["href"]
        low = href.lower()
        if low.endswith(".ics") or any(m in low for m in FEED_HREF_MARKERS):
            feeds.append(urljoin(page_url, href.strip()))
    seen: Set[str] = set()
    out = []
    for f in feeds:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def meeting_shaped_hops(
    html: str, page_url: str, limit: int = MAX_HOP_REQUESTS
) -> List[str]:
    """Newest-looking `limit` same-domain links whose text or href names
    a date and a meeting word. An off-domain link is never a hop
    candidate here -- if it's a real platform link, find_media_hits()
    already caught it directly on this page with zero extra requests."""
    soup = BeautifulSoup(html, "html.parser")
    page_netloc = urlparse(page_url).netloc.lower()
    scored: List[Tuple[Optional[int], int, str]] = []
    for i, a in enumerate(soup.find_all("a", href=True)):
        href = a["href"]
        text = a.get_text(" ", strip=True) or ""
        combined = f"{text} {href}"
        if not MEETING_LINK_WORDS.search(combined):
            continue
        url = urljoin(page_url, href.strip())
        if urlparse(url).netloc.lower() != page_netloc:
            continue
        scored.append((_date_key(combined), i, url))
    # Newest first (None sorts last via the -inf substitute); ties keep
    # original document order (ascending index).
    scored.sort(key=lambda t: (-(t[0] if t[0] is not None else -1), t[1]))
    seen: Set[str] = set()
    out: List[str] = []
    for _, _, url in scored:
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= limit:
            break
    return out


async def process_gov(
    session: aiohttp.ClientSession, row_in: dict, error_counter: List[int]
) -> Row:
    gov_id = row_in["gov_id"]
    result = Row(
        gov_id=gov_id,
        name=row_in.get("name", ""),
        state=row_in.get("state", ""),
        gov_kind=row_in.get("gov_kind", ""),
        population=row_in.get("population", ""),
        family=row_in.get("family", ""),
    )

    listing_url = row_in.get("meeting_url") or ""
    if not listing_url:
        domain = row_in.get("domain", "")
        path = row_in.get("path_that_answered", "")
        if not domain:
            result.outcome = "page-gone"
            result.reject_reason = "no meeting_url or domain on the candidate row"
            return result
        base = domain if domain.startswith("http") else f"https://{domain}"
        listing_url = (
            urljoin(base, path)
            if path and not path.startswith("http")
            else (path or base)
        )
    result.listing_url = listing_url

    used_browser_headers = {"flag": False}

    async def do_fetch(url: str) -> Tuple[Optional[str], Optional[int], str, str]:
        """Returns (html_or_None, status_or_None, final_url, note).
        Honest headers first; if this government has already earned a
        browser-headers upgrade (a prior 403/dropped-connection on this
        SAME government), use browser headers straight away -- never
        re-litigate per hop. The 2s host delay applies before every
        request after the first for this government."""
        if result.requests_made > 0:
            await asyncio.sleep(HOST_DELAY_SECONDS)
        result.requests_made += 1
        headers = BROWSER_HEADERS if used_browser_headers["flag"] else HONEST_HEADERS
        try:
            async with session.get(
                url, headers=headers, timeout=REQUEST_TIMEOUT, allow_redirects=True
            ) as resp:
                try:
                    text = await read_capped_text(resp)
                except BlockedURLError:
                    error_counter[0] = 0
                    return (
                        None,
                        resp.status,
                        str(resp.url),
                        (f"response too large (>{MAX_RESPONSE_BYTES} bytes)"),
                    )
                error_counter[0] = 0
                return text, resp.status, str(resp.url), ""
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            error_counter[0] += 1
            if error_counter[0] >= MAX_CONSECUTIVE_ERRORS:
                raise ConsecutiveErrorBreaker(str(exc))
            return None, None, url, str(exc)

    async def fetch_with_ladder(
        url: str,
    ) -> Tuple[Optional[str], Optional[int], str, str]:
        html, status, final_url, note = await do_fetch(url)
        needs_retry = (
            not used_browser_headers["flag"]
            and (html is None or status == 403)
            and status != 404
        )
        if needs_retry:
            used_browser_headers["flag"] = True
            html, status, final_url, note = await do_fetch(url)
        return html, status, final_url, note

    html, status, final_url, note = await fetch_with_ladder(listing_url)
    if html is None:
        result.outcome = "blocked" if used_browser_headers["flag"] else "page-gone"
        result.reject_reason = note or (f"http {status}" if status else "fetch failed")
        return result
    if status and status >= 400:
        result.outcome = "page-gone"
        result.reject_reason = f"http {status}"
        return result

    lower_html = html.lower()
    for marker in CHALLENGE_MARKERS:
        if marker in lower_html:
            result.outcome = "challenge"
            result.reject_reason = f"human-verification challenge marker: {marker}"
            return result

    hits = find_media_hits(html, final_url)
    feed_links = find_feed_links(html, final_url)
    hop_urls_tried: List[str] = []

    if not hits:
        for hop_url in meeting_shaped_hops(html, final_url):
            hop_urls_tried.append(hop_url)
            hhtml, hstatus, hfinal, hnote = await fetch_with_ladder(hop_url)
            if hhtml is None or (hstatus and hstatus >= 400):
                continue
            hlower = hhtml.lower()
            if any(marker in hlower for marker in CHALLENGE_MARKERS):
                # A challenge on a HOP, not the listing page itself --
                # the listing page answered fine, so this government is
                # not itself gated; just stop hopping and fall through
                # to whatever the listing page alone already gave us.
                break
            hop_hits = find_media_hits(hhtml, hfinal)
            if hop_hits:
                hits = hop_hits
                final_url = hfinal
                break
            feed_links.extend(find_feed_links(hhtml, hfinal))

    result.hop_urls = ";".join(hop_urls_tried)

    if hits:
        best = hits[0]
        is_audio = best["media_kind"] == "direct-audio"
        result.outcome = "audio-found" if is_audio else "video-found"
        result.media_kind = best["media_kind"]
        result.media_url = best["media_url"]
        result.hit_url = final_url
        if feed_links:
            fh, fstatus, _, _ = await fetch_with_ladder(feed_links[0])
            if fh is not None and (not fstatus or fstatus < 400):
                result.feed_url = feed_links[0]
        return result

    # No media at all -- check whether a feed answers before settling
    # for agenda-only.
    seen_feeds: Set[str] = set()
    feed_links = [f for f in feed_links if not (f in seen_feeds or seen_feeds.add(f))]
    for feed_url in feed_links[:1]:
        fh, fstatus, _, _ = await fetch_with_ladder(feed_url)
        if fh is not None and (not fstatus or fstatus < 400):
            result.outcome = "feed-found"
            result.feed_url = feed_url
            result.hit_url = final_url
            return result

    result.outcome = "agenda-only-confirmed"
    result.reject_reason = (
        f"no media/platform link, no feed found on the listing page"
        f"{' plus ' + str(len(hop_urls_tried)) + ' hop(s)' if hop_urls_tried else ''}"
    )
    result.hit_url = final_url
    return result


class ConsecutiveErrorBreaker(Exception):
    pass


def _already_processed_gov_ids(report_csv: Path) -> Set[str]:
    if not report_csv.exists():
        return set()
    with report_csv.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"] for r in csv.DictReader(f) if r.get("gov_id")}


def load_candidates(candidates_csv: Path, already_done: Set[str]) -> List[dict]:
    with candidates_csv.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return [r for r in rows if r["gov_id"] not in already_done]


async def run(
    candidates_csv: Path, report_csv: Path, concurrency: int, limit: Optional[int]
):
    already_done = _already_processed_gov_ids(report_csv)
    print(f"{len(already_done)} gov_ids already in {report_csv} from a prior run.")
    rows_in = load_candidates(candidates_csv, already_done)
    if limit:
        rows_in = rows_in[:limit]
    print(f"Processing {len(rows_in)} governments this run.", flush=True)

    report_csv.parent.mkdir(parents=True, exist_ok=True)
    is_new = not report_csv.exists()
    report_f = open(report_csv, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(report_f, fieldnames=REPORT_FIELDS, lineterminator="\n")
    if is_new:
        writer.writeheader()
        report_f.flush()

    error_counter = [0]
    sem = asyncio.Semaphore(concurrency)
    aborted = False
    processed = 0
    start = time.time()

    connector = aiohttp.TCPConnector(
        limit=concurrency * 2, ssl=False, force_close=True, enable_cleanup_closed=True
    )
    async with aiohttp.ClientSession(connector=connector) as session:

        async def bound(row_in):
            async with sem:
                try:
                    return await asyncio.wait_for(
                        process_gov(session, row_in, error_counter),
                        timeout=PER_GOVERNMENT_WALL_CLOCK_CAP,
                    )
                except asyncio.TimeoutError:
                    r = Row(
                        gov_id=row_in["gov_id"],
                        name=row_in.get("name", ""),
                        state=row_in.get("state", ""),
                        gov_kind=row_in.get("gov_kind", ""),
                        population=row_in.get("population", ""),
                        family=row_in.get("family", ""),
                    )
                    r.outcome = "page-gone"
                    r.reject_reason = f"exceeded {PER_GOVERNMENT_WALL_CLOCK_CAP}s wall-clock safety cap"
                    return r
                except ConsecutiveErrorBreaker as exc:
                    nonlocal aborted
                    aborted = True
                    r = Row(
                        gov_id=row_in["gov_id"],
                        name=row_in.get("name", ""),
                        state=row_in.get("state", ""),
                        gov_kind=row_in.get("gov_kind", ""),
                        population=row_in.get("population", ""),
                        family=row_in.get("family", ""),
                    )
                    r.outcome = "page-gone"
                    r.reject_reason = f"aborted after {MAX_CONSECUTIVE_ERRORS} consecutive errors: {exc}"
                    return r

        tasks = [asyncio.create_task(bound(r)) for r in rows_in]
        try:
            for task in asyncio.as_completed(tasks):
                r = await task
                writer.writerow(r.as_dict())
                report_f.flush()
                processed += 1
                if processed % 25 == 0 or processed == len(rows_in):
                    elapsed = time.time() - start
                    rate = processed / elapsed if elapsed else 0
                    print(
                        f"[{processed}/{len(rows_in)}] {r.gov_id} outcome={r.outcome} "
                        f"media_kind={r.media_kind} ({rate:.2f}/s)",
                        flush=True,
                    )
                if aborted:
                    print("Circuit breaker tripped -- stopping early.", flush=True)
                    for t in tasks:
                        t.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    break
        finally:
            report_f.close()

    print(f"\nDone. {processed} governments processed this run, aborted={aborted}.")
    print(f"Report: {report_csv}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--candidates",
        type=Path,
        default=Path(
            "~/Documents/rtr-business/research/wo197_candidates.csv"
        ).expanduser(),
    )
    ap.add_argument(
        "--report",
        type=Path,
        default=Path("~/Documents/rtr-business/research/wo197_report.csv").expanduser(),
    )
    ap.add_argument("--concurrency", type=int, default=30)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    asyncio.run(run(args.candidates, args.report, args.concurrency, args.limit))


if __name__ == "__main__":
    main()
