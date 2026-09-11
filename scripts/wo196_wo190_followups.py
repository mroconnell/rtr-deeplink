"""WO-196 (2026-09-11): work four of WO-190's leftover groups further,
instead of leaving them recorded as a plain "no".

WO-190 (BACKLOG_DONE.md, scripts/wo190_resolve_research_urls.py) resolved
668 never-tested research-file rows. This script re-opens four of its
"nothing found" buckets and tries a further, group-specific approach on
each row, per Ryan's own instructions for this work order:

  * off-mission (36): the linked video was real but not a real meeting.
    Look for a real governing-body meeting video on the SAME domain or
    channel.
  * blocked / real technical error (8): retry with other URL approaches
    -- www./https variants, the domain home page, browser headers once
    after a 403/dropped connection (already inside the reused ladder),
    and the row's alternate_domains/alternate_urls. Never past a human-
    verification gate.
  * rejected by the tier-3 probe as too short/dead (2): take the next
    candidate video on the same channel or listing.
  * no-platform-link-found (118): one more hop on the domain, its
    alternates, and the research URL's parent page, plus a look for an
    RSS/Atom feed and a direct media link.

Like scripts/wo190_resolve_research_urls.py, this is deliberately NOT a
sixth ladder implementation. It imports scripts.wo151_research_url_
ladder_sweep (which itself monkeypatches hub_sweep_wo126's Fetcher/
act_on_resolved/resolve_lead the way its own module docstring explains)
and scripts.wo190_resolve_research_urls (for the state-abbreviation map
and gov-kind mapping, reused verbatim rather than re-derived) and reuses
w151.process_candidate() as the resolve+ingest engine for every
candidate URL this script finds: build a Cand151 whose
research_meeting_url is the candidate, hand it to process_candidate(),
and let the existing pipeline do the title check, the wrong-government
checks, the dedupe-against-a-fresh-export check, the probe-before-queue
gate, and the real ingest/queue call. This script's own job is only to
find each group's candidate URL(s) in the first place.

Usage (repo root, needs ARCHIVE_BASE_URL/ARCHIVE_INGEST_TOKEN already in
os.environ -- see this WO's own report for why a worktree needs these
set explicitly rather than relying on cwd-walk):

    python scripts/wo196_wo190_followups.py --group blocked
    python scripts/wo196_wo190_followups.py --group probe_reject
    python scripts/wo196_wo190_followups.py --group offmission
    python scripts/wo196_wo190_followups.py --group noplatform [--limit N] [--start N]

Resumable the same way as WO-190: rtr-business/research/wo196_report.csv
is flushed one row at a time; a (gov_id, group) pair already present
there is skipped on re-run.
"""

import argparse
import asyncio
import csv
import os
import re
import sys
from dataclasses import replace
from pathlib import Path
from urllib.parse import urljoin, urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("RTR_DEEPLINK_PATH", str(REPO_ROOT))

import aiohttp  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import find_platform_link  # noqa: E402
from scripts.bulk_ingest import _base_url  # noqa: E402

import scripts.hub_sweep_wo126 as hs  # noqa: E402
import scripts.wo151_research_url_ladder_sweep as w151  # noqa: E402
import scripts.wo190_resolve_research_urls as wo190  # noqa: E402
from app.platforms.youtube_channel import _list_channel, is_publishable  # noqa: E402
from scripts.nationwide_2404_ingest import _looks_like_real_meeting  # noqa: E402
import yt_dlp  # noqa: E402

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
JC_CSV = RESEARCH_DIR / "jurisdiction_coverage.csv"
WO190_REPORT = RESEARCH_DIR / "wo190_report.csv"
REPORT_CSV = RESEARCH_DIR / "wo196_report.csv"
EXPORT_JSON = RESEARCH_DIR / "wo196_export_pages.json"
SEEDS_CSV = RESEARCH_DIR / "wo196_discovery_seeds.csv"

hs.PIN_SOURCE = "wo196_wo190_followups"
hs.PINS_CSV = RESEARCH_DIR / "wo196_pins.csv"

# WO-196's own instructions: headless only for a page that loaded with
# no visible link -- that is exactly w151.maybe_try_headless's own gate
# (only runs when a start URL answered with a real page but no platform
# link was found), so a small non-zero budget is correct here, unlike
# WO-190's own HEADLESS_BUDGET = 0.
w151.HEADLESS_BUDGET = 40

hs.REQUEST_DELAY_SECONDS = 2.0

SUCCESS_OUTCOMES = {
    "ingested_tier1_2",
    "queued_tier3",
    "duplicate_queued",
    "already_covered",
}


# --------------------------------------------------------------------------
# jurisdiction_coverage.csv lookup (read-only in this module; the actual
# writer lives in wo196_apply_to_jc.py per ENUMERATION_METHODS.md's
# section 158 protocol)
# --------------------------------------------------------------------------


def load_jc_by_gov_id() -> dict:
    with JC_CSV.open(newline="", encoding="utf-8") as f:
        return {r["gov_id"]: r for r in csv.DictReader(f) if r.get("gov_id")}


def _split_multi(value: str) -> list:
    return [v.strip() for v in (value or "").split(";") if v.strip()]


def cand_from_jc(gov_id: str, jc_row: dict) -> w151.Cand151:
    return w151.Cand151(
        gov_id=gov_id,
        name=jc_row.get("city_name") or "",
        state=wo190._normalize_state(jc_row.get("state_or_province") or ""),
        country=(jc_row.get("country") or "").strip(),
        gov_kind=wo190._gov_kind_of(gov_id),
        population=jc_row.get("population_estimate") or "",
        domain=(jc_row.get("domain") or "").strip(),
        known_platform=(
            (jc_row.get("suspected_meeting_link_provider") or "").strip()
            or (jc_row.get("suspected_video_provider") or "").strip()
            or (jc_row.get("suspected_calendar_provider") or "").strip()
        ).lower(),
        prior_reason="wo196-followup",
        research_calendar_url="",
        research_meeting_url="",
    )


# --------------------------------------------------------------------------
# wo190_report.csv groups
# --------------------------------------------------------------------------


def load_wo190_rows() -> list:
    with WO190_REPORT.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def group_offmission(rows: list) -> list:
    return [
        r
        for r in rows
        if r["outcome"] == "skipped" and r["reject_reason"] == "off-mission"
    ]


def group_blocked(rows: list) -> list:
    return [
        r
        for r in rows
        if r["outcome"] == "skipped"
        and r["reject_reason"]
        in ("blocked-plain-http", "cloudflare-challenge-blocked", "resolve-failed")
    ]


def group_probe_reject(rows: list) -> list:
    return [r for r in rows if r["outcome"] == "rejected_by_probe"]


def group_noplatform(rows: list) -> list:
    return [
        r
        for r in rows
        if r["outcome"] == "skipped" and r["reject_reason"] == "no-platform-link-found"
    ]


GROUPS = {
    "offmission": group_offmission,
    "blocked": group_blocked,
    "probe_reject": group_probe_reject,
    "noplatform": group_noplatform,
}


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

REPORT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "group",
    "prior_reason",
    "approach_tried",
    "url_used",
    "feed_url",
    "media_url",
    "outcome",
    "reject_reason",
]


def _report_writer(path: Path):
    is_new = not path.exists()
    f = path.open("a", newline="", encoding="utf-8")
    w = csv.DictWriter(
        f, fieldnames=REPORT_FIELDS, extrasaction="ignore", lineterminator="\n"
    )
    if is_new:
        w.writeheader()
        f.flush()
    return f, w


def _already_done(path: Path) -> set:
    if not path.exists():
        return set()
    with path.open(newline="", encoding="utf-8") as f:
        return {(r["gov_id"], r["group"]) for r in csv.DictReader(f) if r.get("gov_id")}


# --------------------------------------------------------------------------
# One candidate URL through the real pipeline
# --------------------------------------------------------------------------


async def try_url(session, base_cand: w151.Cand151, url: str, index, finder) -> dict:
    """One candidate through the real resolve+ingest pipeline. A YouTube
    `list=` param (including the "videoseries" placeholder embed id a
    livestream widget leaves behind -- confirmed live on both Paducah
    KY's CivicClerk media page and Barnstable Town MA's own site in this
    WO's own run) means "this is really a playlist", not one dead video:
    expand it and try the newest few real member videos instead, per
    scripts/bulk_ingest.py's own `_playlist_id`/`_expand_playlist`
    (reused here, not re-derived)."""
    from scripts.bulk_ingest import _expand_playlist, _playlist_id

    playlist_id = _playlist_id(url)
    if playlist_id:
        try:
            member_urls = await asyncio.to_thread(_expand_playlist, playlist_id)
        except Exception:  # noqa: BLE001
            member_urls = []
        last = {"outcome": "skipped", "reject_reason": "no-platform-link-found"}
        for member_url in member_urls[:5]:
            last = await try_url(session, base_cand, member_url, index, finder)
            if last["outcome"] in SUCCESS_OUTCOMES:
                return last
            await asyncio.sleep(hs.REQUEST_DELAY_SECONDS)
        return last

    variant = replace(base_cand, research_meeting_url=url, research_calendar_url="")
    return await w151.process_candidate(session, variant, index, finder)


# --------------------------------------------------------------------------
# Feed / direct-media detection on a fetched page -- the part
# process_candidate's own scan (known platforms only) doesn't do.
# --------------------------------------------------------------------------

_MEDIA_EXT_RE = re.compile(r"\.(mp4|m4a|mp3)(?:[?#]|$)", re.IGNORECASE)
_MEDIA_MARKER_RE = re.compile(r"player\.vimeo\.com|youtube\.com/embed", re.IGNORECASE)
_FEED_PATH_RE = re.compile(
    r"(?:/feed/?(?:$|[?#])|/rss/?(?:$|[?#])|RSSFeed\.aspx\?ModID=)", re.IGNORECASE
)


def find_feed_link(html: str, page_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for link in soup.find_all("link"):
        rel = link.get("rel") or []
        if isinstance(rel, str):
            rel = [rel]
        rel_l = [r.lower() for r in rel]
        type_l = (link.get("type") or "").lower()
        href = link.get("href")
        if href and "alternate" in rel_l and ("rss" in type_l or "atom" in type_l):
            return urljoin(page_url, href)
    for a in soup.find_all("a", href=True):
        if _FEED_PATH_RE.search(a["href"]):
            return urljoin(page_url, a["href"])
    return ""


def find_media_link(html: str, page_url: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["video", "audio", "source"]):
        src = tag.get("src")
        # Real, confirmed false positive (Edcouch city, TX): a decorative
        # WordPress hero/slider background clip is also a real <video src>
        # -- only accept one whose extension/marker actually matches the
        # WO's own direct-media list, the same filter the <a>/<iframe>
        # loop below already applies, rather than taking any <video> tag
        # on sight.
        if src and (_MEDIA_EXT_RE.search(src) or _MEDIA_MARKER_RE.search(src)):
            return urljoin(page_url, src)
    for tag in soup.find_all(["a", "iframe"]):
        for attr in ("href", "src"):
            val = tag.get(attr)
            if val and (_MEDIA_EXT_RE.search(val) or _MEDIA_MARKER_RE.search(val)):
                return urljoin(page_url, val)
    # Raw-text fallback for a link embedded in inline JS rather than a tag
    # attribute -- confirmed useful shape per this WO's own instructions.
    m = _MEDIA_MARKER_RE.search(html) or _MEDIA_EXT_RE.search(html)
    if m:
        start = max(0, m.start() - 200)
        chunk = html[start : m.end() + 20]
        urls = re.findall(r"https?://[^\s'\"<>]+", chunk)
        for u in urls:
            if _MEDIA_EXT_RE.search(u) or _MEDIA_MARKER_RE.search(u):
                return u
    return ""


async def explore_url(session, url: str) -> dict:
    """One polite fetch of `url`, looking for a known platform link, a
    feed, or a direct media link. Never past a human-verification gate
    (LadderFetcher stops there on its own)."""
    fetcher = w151.LadderFetcher(session, hs.PER_GOV_FETCH_BUDGET)
    try:
        final_url, html = await fetcher.get(url)
    except hs.FetchError as e:
        return {"status": "fetch-error", "detail": f"{e.kind}: {e.detail}"}
    except Exception as e:  # noqa: BLE001
        return {"status": "fetch-error", "detail": f"{type(e).__name__}: {e}"}
    link = find_platform_link(html, final_url)
    return {
        "status": "ok",
        "final_url": final_url,
        "platform_link": link[0] if link else "",
        "platform": link[1] if link else "",
        "feed_url": find_feed_link(html, final_url),
        "media_url": find_media_link(html, final_url),
    }


def parent_page(url: str) -> str:
    p = urlparse(url)
    if not p.path or p.path == "/":
        return ""
    parts = [seg for seg in p.path.split("/") if seg]
    if not parts:
        return ""
    parent_path = "/" + "/".join(parts[:-1]) + "/"
    if parent_path == p.path:
        return ""
    return f"{p.scheme}://{p.netloc}{parent_path}"


def www_variant(url: str) -> str:
    p = urlparse(url)
    if not p.netloc:
        return ""
    if p.netloc.startswith("www."):
        return f"{p.scheme}://{p.netloc[4:]}{p.path}"
    return f"{p.scheme}://www.{p.netloc}{p.path}"


async def civicclerk_next_event_urls(
    session, tenant: str, exclude_event_id: str, limit: int = 8
) -> list:
    """Newest-first CivicClerk portal URLs for `tenant`, excluding
    `exclude_event_id`, for the "next candidate on the same listing"
    rule -- shared by the blocked-group's CivicClerk fallback and the
    probe-reject group's CivicClerk handling."""
    from scripts.find_tier3_short_meeting_substitutes import (
        cc_list_past_events,
        cc_probeable_video_url,
    )

    api_base = f"https://{tenant}.api.civicclerk.com/v1"
    try:
        events = await cc_list_past_events(session, api_base)
    except Exception:  # noqa: BLE001
        return []
    out = []
    for ev in events:
        if str(ev.get("id")) == str(exclude_event_id):
            continue
        media_url = await cc_probeable_video_url(session, api_base, ev)
        if not media_url:
            continue
        out.append(f"https://{tenant}.portal.civicclerk.com/event/{ev.get('id')}/media")
        if len(out) >= limit:
            break
    return out


def scheme_variant(url: str) -> str:
    if url.startswith("https://"):
        return "http://" + url[len("https://") :]
    if url.startswith("http://"):
        return "https://" + url[len("http://") :]
    return ""


# --------------------------------------------------------------------------
# Group: blocked / real technical error (8 rows) -- retry with other URL
# approaches, never past a human-verification gate.
# --------------------------------------------------------------------------


async def process_blocked_row(session, row: dict, jc: dict, index, finder) -> dict:
    gov_id = row["gov_id"]
    jc_row = jc.get(gov_id, {})
    base = cand_from_jc(gov_id, jc_row)
    url_used = row.get("url_used") or ""
    prior_reason = row.get("reject_reason") or ""

    out = {k: "" for k in REPORT_FIELDS}
    out.update(
        gov_id=gov_id,
        name=row.get("name"),
        state=row.get("state"),
        group="blocked",
        prior_reason=prior_reason,
    )

    if prior_reason == "cloudflare-challenge-blocked":
        out.update(
            approach_tried="none -- human-verification gate, never retried per rule",
            url_used=url_used,
            outcome="skipped",
            reject_reason=prior_reason,
        )
        return out

    candidates = []
    if url_used:
        candidates.append((url_used, "original URL retried fresh"))
        wv = www_variant(url_used)
        if wv:
            candidates.append((wv, "www/bare-domain variant"))
        sv = scheme_variant(url_used)
        if sv:
            candidates.append((sv, "http/https variant"))
    domain = (jc_row.get("domain") or "").strip()
    if domain:
        dom_url = domain if "://" in domain else f"https://{domain}"
        candidates.append((dom_url.rstrip("/"), "domain home page"))
    for alt in _split_multi(jc_row.get("alternate_domains", "")):
        u = alt if "://" in alt else f"https://{alt}"
        candidates.append((u.rstrip("/"), f"alternate_domains: {alt}"))
    for alt in _split_multi(jc_row.get("alternate_urls", "")):
        candidates.append((alt, f"alternate_urls: {alt}"))

    tried = []
    seen = set()
    for cand_url, desc in candidates:
        if cand_url in seen:
            continue
        seen.add(cand_url)
        tried.append(desc)
        result = await try_url(session, base, cand_url, index, finder)
        if result["outcome"] in SUCCESS_OUTCOMES:
            out.update(
                approach_tried="; ".join(tried),
                url_used=cand_url,
                outcome=result["outcome"],
                reject_reason=result.get("reject_reason") or "",
            )
            return out
        await asyncio.sleep(hs.REQUEST_DELAY_SECONDS)

    # Final fallback: when every URL variant funnels back to the SAME
    # dead/malformed media on a CivicClerk portal (confirmed real case:
    # Paducah KY's event/264 resolves a bare "videoseries" YouTube
    # playlist embed, not a real video id, on every variant tried above),
    # try the next few past events on that same tenant.
    netloc = urlparse(url_used).netloc if url_used else ""
    if "civicclerk.com" in netloc:
        tenant = netloc.split(".")[0]
        m = re.search(r"/event/(\d+)/", url_used)
        exclude_id = m.group(1) if m else ""

        # Try the SAME event's own real media URL directly first, per the
        # API, before moving to a different event -- confirmed real case:
        # Paducah KY event/264's own page resolves a bare "videoseries"
        # YouTube playlist-embed placeholder (probably a "live now"
        # widget on the same page as the real archived link), while the
        # CivicClerk Events API's own externalMediaUrl for that exact
        # event is a real, specific, resolvable video
        # (https://youtu.be/W1Lyr_x5F60, "Paducah City Commission Meeting
        # - September 8, 2026", 987 real caption segments) -- so this is
        # the SAME meeting the row already pointed at, just reached via a
        # different field than the page scrape used.
        if exclude_id:
            api_base = f"https://{tenant}.api.civicclerk.com/v1"
            try:
                from scripts.find_tier3_short_meeting_substitutes import (
                    _get_json,
                    cc_media_path,
                )

                event = await _get_json(session, f"{api_base}/Events/{exclude_id}")
                direct_url = cc_media_path(event) if isinstance(event, dict) else None
            except Exception:  # noqa: BLE001
                direct_url = None
            if direct_url and direct_url != url_used:
                tried.append(f"same event's own API media URL: {direct_url}")
                result = await try_url(session, base, direct_url, index, finder)
                await asyncio.sleep(hs.REQUEST_DELAY_SECONDS)
                if result["outcome"] in SUCCESS_OUTCOMES:
                    out.update(
                        approach_tried="; ".join(tried),
                        url_used=direct_url,
                        outcome=result["outcome"],
                        reject_reason=result.get("reject_reason") or "",
                    )
                    return out

        next_urls = await civicclerk_next_event_urls(session, tenant, exclude_id)
        for portal_url in next_urls:
            tried.append(f"next CivicClerk event: {portal_url}")
            result = await try_url(session, base, portal_url, index, finder)
            await asyncio.sleep(hs.REQUEST_DELAY_SECONDS)
            if result["outcome"] in SUCCESS_OUTCOMES:
                out.update(
                    approach_tried="; ".join(tried),
                    url_used=portal_url,
                    outcome=result["outcome"],
                    reject_reason=result.get("reject_reason") or "",
                )
                return out

    out.update(
        approach_tried="; ".join(tried) or "no alternate URL available on this row",
        url_used=url_used,
        outcome="skipped",
        reject_reason=prior_reason or "still-nothing",
    )
    return out


# --------------------------------------------------------------------------
# Group: no-platform-link-found (118 rows) -- one more hop on the domain,
# its alternates, and the research URL's parent page, plus a feed/media
# scan process_candidate's own known-platform-only scan doesn't do.
# --------------------------------------------------------------------------


async def process_noplatform_row(session, row: dict, jc: dict, index, finder) -> dict:
    gov_id = row["gov_id"]
    jc_row = jc.get(gov_id, {})
    base = cand_from_jc(gov_id, jc_row)
    url_used = row.get("url_used") or ""

    out = {k: "" for k in REPORT_FIELDS}
    out.update(
        gov_id=gov_id,
        name=row.get("name"),
        state=row.get("state"),
        group="noplatform",
        prior_reason="no-platform-link-found",
    )

    urls = []
    domain = (jc_row.get("domain") or "").strip()
    if domain:
        urls.append(
            (domain if "://" in domain else f"https://{domain}", "domain home page")
        )
    for alt in _split_multi(jc_row.get("alternate_domains", "")):
        urls.append(
            (alt if "://" in alt else f"https://{alt}", f"alternate_domains: {alt}")
        )
    for alt in _split_multi(jc_row.get("alternate_urls", "")):
        urls.append((alt, f"alternate_urls: {alt}"))
    pp = parent_page(url_used) if url_used else ""
    if pp:
        urls.append((pp, "research URL's parent page"))

    tried = []
    feed_found = ""
    media_found = ""
    seen = set()
    for u, desc in urls:
        if u in seen:
            continue
        seen.add(u)
        tried.append(desc)
        exp = await explore_url(session, u)
        await asyncio.sleep(hs.REQUEST_DELAY_SECONDS)
        if exp["status"] != "ok":
            continue
        if exp["platform_link"]:
            result = await try_url(session, base, exp["platform_link"], index, finder)
            await asyncio.sleep(hs.REQUEST_DELAY_SECONDS)
            if result["outcome"] in SUCCESS_OUTCOMES:
                out.update(
                    approach_tried="; ".join(tried)
                    + f" -> platform link found ({exp['platform']})",
                    url_used=exp["platform_link"],
                    feed_url=feed_found,
                    media_url=media_found,
                    outcome=result["outcome"],
                    reject_reason=result.get("reject_reason") or "",
                )
                return out
        if exp["media_url"] and not media_found:
            media_found = exp["media_url"]
            result = await try_url(session, base, exp["media_url"], index, finder)
            await asyncio.sleep(hs.REQUEST_DELAY_SECONDS)
            if result["outcome"] in SUCCESS_OUTCOMES:
                out.update(
                    approach_tried="; ".join(tried) + " -> direct media link found",
                    url_used=exp["media_url"],
                    feed_url=feed_found,
                    media_url=media_found,
                    outcome=result["outcome"],
                    reject_reason=result.get("reject_reason") or "",
                )
                return out
        if exp["feed_url"] and not feed_found:
            feed_found = exp["feed_url"]

    out.update(
        approach_tried="; ".join(tried)
        or "no domain/alternate/parent-page URL available",
        url_used=url_used,
        feed_url=feed_found,
        media_url=media_found,
        outcome="skipped",
        reject_reason="no-platform-link-found"
        if not feed_found
        else "no-platform-link-found (feed found, not ingested)",
    )
    return out


# --------------------------------------------------------------------------
# Group: off-mission (36 rows) -- a real video, but not a real meeting.
# Find a real governing-body meeting video on the SAME domain or channel.
# --------------------------------------------------------------------------

_YT_ID_RE = re.compile(r"(?:v=|youtu\.be/|embed/|/live/)([A-Za-z0-9_-]{11})")
_SCHOOL_MARKERS = ("school board", "board of education", "school district")
_NOTE_URL_RE = re.compile(r"\((https?://[^\s()]+)\)\s*$")


def _bad_video_url(row: dict) -> str:
    """wo190_report.csv's own `url_used`/`hit_url` are sometimes a stale
    relative-path artifact of the ORIGINAL research row (confirmed real
    case: Suffolk County MA's `url_used` is a leftover
    "/m/boston-ma-..." string, not the actual bad YouTube URL) -- the
    real video URL that failed the title check is always the last
    parenthesized URL in the report's own `note` text
    ("...: 'title' (https://...)"), so that's the reliable source."""
    m = _NOTE_URL_RE.search(row.get("note") or "")
    if m:
        return m.group(1)
    for field in ("hit_url", "video_url", "url_used"):
        val = row.get(field) or ""
        if val.startswith("http"):
            return val
    return row.get("url_used") or ""


async def oembed_title_and_author(session, video_url: str) -> tuple:
    m = _YT_ID_RE.search(video_url)
    if not m:
        return "", ""
    try:
        async with session.get(
            "https://www.youtube.com/oembed",
            params={
                "url": f"https://www.youtube.com/watch?v={m.group(1)}",
                "format": "json",
            },
            headers=hs.UA_HEADERS,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status != 200:
                return "", ""
            data = await resp.json(content_type=None)
            return data.get("title") or "", data.get("author_name") or ""
    except Exception:  # noqa: BLE001
        return "", ""


def _channel_id_from_url(video_url: str) -> str:
    ydl_opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "extractor_args": {
            "youtube": {"player_client": ["android", "ios", "tv", "web"]}
        },
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(video_url, download=False)
    return info.get("channel_id") or ""


def _title_disqualified(title: str, gov_kind: str) -> bool:
    t = title.lower()
    if gov_kind != "school_district" and any(m in t for m in _SCHOOL_MARKERS):
        return True
    return not _looks_like_real_meeting(title, require_allowlist=True)


_GOV_NAME_STOPWORDS = {
    "city",
    "town",
    "township",
    "village",
    "borough",
    "county",
    "cousub",
    "of",
    "the",
    "and",
    "csd",
}


def _name_tokens(name: str) -> set:
    return {
        w
        for w in re.findall(r"[a-z0-9]+", (name or "").lower())
        if w not in _GOV_NAME_STOPWORDS and len(w) > 2
    }


def _channel_matches_government(channel_name: str, gov_name: str) -> bool:
    """A real, confirmed methodological gap this WO's own first live batch
    hit hard (2026-09-11): assuming "whatever channel uploaded the
    originally-flagged off-mission video IS the government's own
    channel" is exactly the same trust CLAUDE.md already warns against
    ("nothing matches to YouTube without a channel ... confirmed as the
    government's own"). 5 of this batch's first 8 "successes" were wrong
    for exactly this reason before this check existed: "American Giants"
    (a wrestling/history channel, Galva city IL), "Garcia Wrestling"
    (Lexington city IL), "Barb Byrum" (a county clerk's personal channel,
    not Ingham County's own), "City of Boston" (Suffolk County MA's own
    video was actually Boston's), "Roanoke Valley Television - RVTV" (a
    Virginia PEG station, New Hempstead village NY). This check requires
    the government's own significant name token(s) (place name, minus
    "city"/"town"/"village"/"county"/etc.) to actually appear in the
    channel's name -- cheap, and it would have caught all 5.

    Doesn't catch a same-name-different-government-TYPE mix-up (a real
    6th case this batch hit: "Town of Granville" is a genuine, different
    NY government from "Granville village", the gov_id this row is
    actually about) -- see the caller's own separate town/village check
    for that, kept separate since it's a narrower, type-specific rule."""
    gov_tokens = _name_tokens(gov_name)
    if not gov_tokens:
        return False
    channel_lower = (channel_name or "").lower()
    return any(tok in channel_lower for tok in gov_tokens)


_CONTAINER_GOV_WORDS = ("town", "township")
_CONTAINED_GOV_WORDS = ("village", "borough")


def _town_village_mismatch(channel_name: str, gov_name: str) -> bool:
    """Two real, confirmed hand-checks, WO-196 2026-09-11 -- a smaller
    incorporated place can sit inside, but be legally a DIFFERENT
    government from, its own containing town/township: Village of
    Granville, NY (a real, separate "Town of Granville, NY" channel/
    title) and Borough of Stonington, CT (a real, separate "Town of
    Stonington, CT." Board of Finance -- the borough has its own elected
    Borough Warden, confirmed live, and a Board of Finance is a town-
    level body). A channel that says "Town of X"/"Township of X" for a
    government whose own row name says "X village"/"X borough" (or the
    reverse) is a real, different government, even though
    `_channel_matches_government()` above passes it (the place-name
    token itself appears in both)."""
    ch = (channel_name or "").lower()
    gov = (gov_name or "").lower()
    channel_is_container = any(f"{w} of" in ch for w in _CONTAINER_GOV_WORDS)
    channel_is_contained = any(f"{w} of" in ch for w in _CONTAINED_GOV_WORDS)
    gov_is_container = any(re.search(rf"\b{w}\b", gov) for w in _CONTAINER_GOV_WORDS)
    gov_is_contained = any(re.search(rf"\b{w}\b", gov) for w in _CONTAINED_GOV_WORDS)
    if channel_is_container and gov_is_contained:
        return True
    if channel_is_contained and gov_is_container:
        return True
    return False


async def process_offmission_youtube_row(
    session, row: dict, jc: dict, index, finder
) -> dict:
    gov_id = row["gov_id"]
    jc_row = jc.get(gov_id, {})
    base = cand_from_jc(gov_id, jc_row)
    bad_url = _bad_video_url(row)

    out = {k: "" for k in REPORT_FIELDS}
    out.update(
        gov_id=gov_id,
        name=row.get("name"),
        state=row.get("state"),
        group="offmission",
        prior_reason="off-mission",
    )

    try:
        channel_id = await asyncio.to_thread(_channel_id_from_url, bad_url)
    except Exception as e:  # noqa: BLE001
        out.update(
            approach_tried=f"could not extract channel id from {bad_url}: {type(e).__name__}: {e}",
            url_used=bad_url,
            outcome="skipped",
            reject_reason="off-mission",
        )
        return out
    if not channel_id:
        out.update(
            approach_tried=f"no channel_id on {bad_url}",
            url_used=bad_url,
            outcome="skipped",
            reject_reason="off-mission",
        )
        return out

    try:
        entries = await asyncio.to_thread(_list_channel, channel_id)
    except Exception as e:  # noqa: BLE001
        out.update(
            approach_tried=f"channel listing failed for {channel_id}: {type(e).__name__}: {e}",
            url_used=bad_url,
            outcome="skipped",
            reject_reason="off-mission",
        )
        return out

    bad_id_match = _YT_ID_RE.search(bad_url)
    bad_id = bad_id_match.group(1) if bad_id_match else ""
    checked = 0
    hand_checks = []
    for entry in entries:
        if entry["id"] == bad_id or not is_publishable(entry):
            continue
        title = entry.get("title") or ""
        if _title_disqualified(title, base.gov_kind):
            continue
        checked += 1
        if checked > 12:
            break
        candidate_url = f"https://www.youtube.com/watch?v={entry['id']}"
        oe_title, oe_author = await oembed_title_and_author(session, candidate_url)
        await asyncio.sleep(hs.REQUEST_DELAY_SECONDS)
        hand_checks.append(f"{candidate_url} title={oe_title!r} channel={oe_author!r}")
        if oe_title and _title_disqualified(oe_title, base.gov_kind):
            continue
        if not oe_author or not _channel_matches_government(oe_author, base.name):
            hand_checks[-1] += (
                " [REJECTED: channel name doesn't verify as the government's own]"
            )
            continue
        if _town_village_mismatch(oe_author, row.get("name") or base.name):
            hand_checks[-1] += (
                " [REJECTED: town/village mismatch -- a different real government]"
            )
            continue
        result = await try_url(session, base, candidate_url, index, finder)
        await asyncio.sleep(hs.REQUEST_DELAY_SECONDS)
        if result["outcome"] in SUCCESS_OUTCOMES:
            out.update(
                approach_tried=(
                    f"channel scan (channel_id={channel_id}, {len(entries)} entries); "
                    f"hand-checked: {'; '.join(hand_checks)}"
                ),
                url_used=candidate_url,
                outcome=result["outcome"],
                reject_reason=result.get("reject_reason") or "",
            )
            return out
        # This candidate itself failed the pipeline's own (stricter)
        # checks -- e.g. wrong-domain-mapping/off-mission caught the
        # video this row's own pre-filter let through. Keep going.

    out.update(
        approach_tried=(
            f"channel scan (channel_id={channel_id}, {len(entries)} entries, "
            f"{checked} candidate(s) hand-checked): {'; '.join(hand_checks) or 'none passed the title filter'}"
        ),
        url_used=bad_url,
        outcome="skipped",
        reject_reason="off-mission",
    )
    return out


async def process_offmission_row(session, row: dict, jc: dict, index, finder) -> dict:
    platform = (row.get("platform_found") or "").lower()
    if platform == "youtube":
        return await process_offmission_youtube_row(session, row, jc, index, finder)

    gov_id = row["gov_id"]
    out = {k: "" for k in REPORT_FIELDS}
    out.update(
        gov_id=gov_id,
        name=row.get("name"),
        state=row.get("state"),
        group="offmission",
        prior_reason="off-mission",
        url_used=_bad_video_url(row),
        outcome="skipped",
        reject_reason="off-mission",
        approach_tried=f"platform={platform!r}: no channel-scan helper for this platform in this run; hand-investigated separately (see WO-196 report notes)",
    )
    return out


# --------------------------------------------------------------------------
# Group: rejected by the tier-3 probe as too short/dead (2 rows) -- take
# the next candidate video on the same channel or listing. Both of this
# group's real rows are CivicClerk/TelVue-specific; handled by hand
# (see scripts/wo196_probe_reject_notes.md-equivalent report notes)
# rather than a generic helper, since there were only two and each needed
# a different, platform-specific investigation.
# --------------------------------------------------------------------------


async def process_probe_reject_row(session, row: dict, jc: dict, index, finder) -> dict:
    gov_id = row["gov_id"]
    jc_row = jc.get(gov_id, {})
    base = cand_from_jc(gov_id, jc_row)
    out = {k: "" for k in REPORT_FIELDS}
    out.update(
        gov_id=gov_id,
        name=row.get("name"),
        state=row.get("state"),
        group="probe_reject",
        prior_reason="rejected_by_probe",
        url_used=row.get("url_used") or "",
    )

    # wo190_report.csv's own `platform_found` for Riley County KS reads
    # "iqm2" even though the URL and the row's own `note` both say
    # civicclerk (a pre-existing data quirk in that report, not this
    # script's to fix) -- so detect the platform from the URL itself,
    # the same way process_blocked_row already does.
    url_netloc = urlparse(row.get("url_used") or "").netloc
    platform = (row.get("platform_found") or "").lower()
    if "civicclerk.com" in url_netloc:
        tenant_host = url_netloc
        tenant = tenant_host.split(".")[0] if tenant_host else ""
        bad_event_id = ""
        m = re.search(r"/event/(\d+)/", row.get("hit_url") or row.get("url_used") or "")
        if m:
            bad_event_id = m.group(1)
        next_urls = await civicclerk_next_event_urls(session, tenant, bad_event_id)
        tried = []
        for portal_url in next_urls:
            tried.append(portal_url)
            result = await try_url(session, base, portal_url, index, finder)
            await asyncio.sleep(hs.REQUEST_DELAY_SECONDS)
            if result["outcome"] in SUCCESS_OUTCOMES:
                out.update(
                    approach_tried=f"next CivicClerk event on {tenant}, tried: {'; '.join(tried)}",
                    url_used=portal_url,
                    outcome=result["outcome"],
                    reject_reason=result.get("reject_reason") or "",
                )
                return out
        out.update(
            approach_tried=f"next CivicClerk events on {tenant}, none usable, tried: {'; '.join(tried)}",
            outcome="skipped",
            reject_reason="rejected_by_probe",
        )
        return out

    out.update(
        approach_tried=f"platform={platform!r}: no next-candidate helper for this platform in this run; hand-investigated separately (see WO-196 report notes)",
        outcome="skipped",
        reject_reason="rejected_by_probe",
    )
    return out


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------

PROCESSORS = {
    "offmission": process_offmission_row,
    "blocked": process_blocked_row,
    "probe_reject": process_probe_reject_row,
    "noplatform": process_noplatform_row,
}


async def main_async(args) -> None:
    if not _base_url() or not os.environ.get("ARCHIVE_INGEST_TOKEN"):
        print(
            "ERROR: ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN not set.",
            file=sys.stderr,
        )
        sys.exit(1)

    register_all_finders()
    finder = hs.CivicPlusAssetFinder()

    if args.refresh_export or not EXPORT_JSON.exists():
        n = await hs.refresh_export(EXPORT_JSON)
        print(f"export refreshed: {n} pages -> {EXPORT_JSON}")
    index = hs.DedupeIndex(EXPORT_JSON, hs.TIER3_QUEUE_FILE)

    jc = load_jc_by_gov_id()
    wo190_rows = load_wo190_rows()
    rows = GROUPS[args.group](wo190_rows)
    if args.start:
        rows = rows[args.start :]
    if args.limit:
        rows = rows[: args.limit]

    done = _already_done(REPORT_CSV)
    todo = [r for r in rows if (r["gov_id"], args.group) not in done]
    print(
        f"[{args.group}] processing {len(todo)} of {len(rows)} row(s) ({len(done)} already logged for this group)\n"
    )

    report_f, report_w = _report_writer(REPORT_CSV)
    processor = PROCESSORS[args.group]
    try:
        async with aiohttp.ClientSession() as session:
            for i, row in enumerate(todo):
                try:
                    out = await processor(session, row, jc, index, finder)
                except Exception as e:  # noqa: BLE001
                    out = {k: "" for k in REPORT_FIELDS}
                    out.update(
                        gov_id=row["gov_id"],
                        name=row.get("name"),
                        state=row.get("state"),
                        group=args.group,
                        prior_reason=row.get("reject_reason")
                        or row.get("outcome")
                        or "",
                        outcome="error",
                        reject_reason=f"unhandled: {type(e).__name__}: {e}",
                    )
                report_w.writerow(out)
                report_f.flush()
                print(
                    f"[{i + 1}/{len(todo)}] {out['gov_id']} {out['name']!r} -> {out['outcome']} ({out.get('reject_reason', '')})"
                )
                if i < len(todo) - 1:
                    await asyncio.sleep(hs.REQUEST_DELAY_SECONDS)
    finally:
        report_f.close()

    print(f"\nReport: {REPORT_CSV}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--group", required=True, choices=list(GROUPS.keys()))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--start", type=int, default=None)
    parser.add_argument("--refresh-export", action="store_true")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
