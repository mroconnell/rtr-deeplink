#!/usr/bin/env python3
"""WO-270 (2026-09-12): WordPress surface pilot -- measurement only.

Fetches a fixed set of WordPress-shaped surfaces (feed, wp-json root,
custom post types, posts search, media, events, sitemaps, site search,
front page) for every government in an input CSV with `domain`, `set`
(positive/negative) and `archive_video_url` columns -- built for
~/Documents/rtr-business/research/wo_wordpress_pilot_sets.csv (WO-270's
own 127 positive / 150 negative WordPress governments), all plain honest
HTTP, no browser-header escalation, no headless. Writes one row per
(site, probe) to wo270_probe_results.csv and one row per site to
wo270_site_summary.csv, both in the output directory (default: cwd).

Usage: `python scripts/wo270_wordpress_pilot.py [input_csv] [out_dir]`
(both optional; defaults to WO-270's own input file and the cwd).

This is a measurement pilot: no ingest, no queue writes, no research-file
writes. Politeness: at most 2 concurrent in-flight requests are never to
the same host (each site's own probes run strictly sequentially, >=2s
apart); different sites run concurrently under a bounded semaphore.

Reusable for a future pilot on a different population -- WO-271 (the
1,355-government WO-197 population this was measured against) should
run the RECIPE this pilot's results led to (see `docs/CMS_FAMILIES.md`'s
WordPress section), not necessarily this exhaustive per-surface script
again; this script is kept for a future re-measurement, not as the
production sweep tool.
"""

from __future__ import annotations

import os

import certifi

# Must run before `import aiohttp` -- aiohttp/connector.py builds its
# default SSLContext at import time, and a fresh Homebrew-Python venv
# has an empty default trust store (see CLAUDE.md's aiohttp/SSL bullet).
os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import asyncio
import csv
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import aiohttp

DEFAULT_INPUT_CSV = Path(
    "/Users/mroconnell/Documents/rtr-business/research/wo_wordpress_pilot_sets.csv"
)

HONEST_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-encoding": "gzip, deflate",
    "accept-language": "en-US,en;q=0.9",
    "user-agent": (
        "rtr-upcoming/0.1 (Red Tape Recordings public-agenda reader; "
        "+https://redtaperecordings.com/about)"
    ),
}
REQUEST_TIMEOUT = 12
HOST_DELAY_SECONDS = 2.0
CONCURRENT_SITES = 24

MEETING_WORDS = [
    "agenda",
    "minutes",
    "meeting",
    "council",
    "board",
    "commission",
    "hearing",
    "workshop",
    "session",
]
VIDEO_MARKERS = [
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "facebook.com/.*video",
    r"\.mp4",
    r"\.m4a",
    r"\.mp3",
    "recording",
    "watch",
    "livestream",
    "zoom.us",
    "transcript",
    "closed caption",
]
SEARCH_TERMS = ["agenda", "minutes", "meeting", "video", "youtube", "recording"]
POSTS_SEARCH_WORDS = ["agenda", "minutes", "meeting", "video", "youtube", "recording"]

# A narrower, high-precision subset of VIDEO_MARKERS -- a literal video-host
# URL or file extension, not a generic English word like "watch"/"recording"
# that shows up in unrelated town-news copy too. Tracked separately so the
# measurement can tell "any marker word" (broad, likely noisy) apart from
# "an actual video/audio link" (narrow, likely precise).
STRICT_VIDEO_MARKERS = [
    "youtube.com",
    "youtu.be",
    "vimeo.com",
    "facebook.com/.*video",
    r"\.mp4",
    r"\.m4a",
    r"\.mp3",
    "zoom.us",
]


def strict_video_marker_hits(text: str) -> List[str]:
    low = text.lower()
    return [m for m in STRICT_VIDEO_MARKERS if re.search(m, low)]


CHALLENGE_MARKERS = [
    "just a moment",
    "cf-browser-verification",
    "attention required",
    "checking your browser",
    "cf-chl-",
    "verify you are human",
]


def meeting_word_hits(text: str) -> List[str]:
    low = text.lower()
    return [w for w in MEETING_WORDS if w in low]


def video_marker_hits(text: str) -> List[str]:
    low = text.lower()
    hits = []
    for m in VIDEO_MARKERS:
        if re.search(m, low):
            hits.append(m)
    return hits


def parse_json_or_none(text: str):
    """Returns the parsed JSON value, or None if the body isn't real
    JSON. A WordPress security/caching plugin frequently disables
    `/wp-json/*` but still answers 200 with the ordinary front-page HTML
    (or a themed "not found" page) rather than a 403/404 -- an HTTP-level
    200 alone is not evidence the REST API actually answered, so every
    JSON-shaped probe in this script checks this explicitly rather than
    trusting status code alone."""
    stripped = text.lstrip()
    if not stripped or stripped[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return None


def is_challenge(status: int, text: str) -> bool:
    if status in (429, 503):
        low = text.lower()
        if any(marker in low for marker in CHALLENGE_MARKERS):
            return True
    low = text.lower()
    return any(marker in low for marker in CHALLENGE_MARKERS)


@dataclass
class HostLimiter:
    """Serializes requests to one host, >=2s apart, honoring a per-host
    stop-after-challenge flag."""

    last_request_at: float = 0.0
    stopped: bool = False
    stop_reason: str = ""
    consecutive_fail: int = 0
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


HOST_LIMITERS: Dict[str, HostLimiter] = {}


def limiter_for(host: str) -> HostLimiter:
    if host not in HOST_LIMITERS:
        HOST_LIMITERS[host] = HostLimiter()
    return HOST_LIMITERS[host]


@dataclass
class ProbeResult:
    gov_id: str
    name: str
    state: str
    set_: str
    domain: str
    probe: str
    url: str
    outcome: str  # answered / 401 / 403 / 404 / timeout / challenge / error / skipped
    status: Optional[int]
    evidence: str


async def do_get(
    session: aiohttp.ClientSession, host: str, path: str, expect_json: bool = False
) -> tuple[str, Optional[int], str, str]:
    """Returns (outcome, status, text, final_url). Enforces >=2s spacing
    to this host and a per-host stop-after-challenge gate.

    `expect_json=True` is for /wp-json/* endpoints: a WordPress security
    or caching plugin frequently disables the REST API but still answers
    200 with the ordinary front-page HTML (or a themed error page)
    instead of a 403/404. Treating that as "answered" would overstate
    real REST availability, so a 200 that doesn't parse as JSON is
    reported as its own outcome, `answered_html_fallback`, distinct from
    a genuine `answered` (valid JSON body)."""
    lim = limiter_for(host)
    async with lim.lock:
        if lim.stopped:
            return ("skipped", None, "", "")
        now = time.monotonic()
        wait = HOST_DELAY_SECONDS - (now - lim.last_request_at)
        if wait > 0:
            await asyncio.sleep(wait)
        url = f"https://{host}{path}"
        try:
            async with session.get(
                url,
                headers=HONEST_HEADERS,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
            ) as resp:
                text = await resp.text(errors="replace")
                status = resp.status
                final_url = str(resp.url)
        except asyncio.TimeoutError:
            lim.last_request_at = time.monotonic()
            lim.consecutive_fail += 1
            if lim.consecutive_fail >= 6:
                lim.stopped = True
                lim.stop_reason = "6-consecutive-failures"
            return ("timeout", None, "", url)
        except aiohttp.ClientConnectorCertificateError:
            # retry once over plain http -- some small-town sites have a
            # broken/self-signed cert on https but a fine plain http site
            try:
                http_url = f"http://{host}{path}"
                async with session.get(
                    http_url,
                    headers=HONEST_HEADERS,
                    timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
                ) as resp:
                    text = await resp.text(errors="replace")
                    status = resp.status
                    final_url = str(resp.url)
            except Exception as exc:  # noqa: BLE001
                lim.last_request_at = time.monotonic()
                lim.consecutive_fail += 1
                if lim.consecutive_fail >= 6:
                    lim.stopped = True
                    lim.stop_reason = "6-consecutive-failures"
                return ("error", None, str(exc)[:200], http_url)
        except Exception as exc:  # noqa: BLE001
            lim.last_request_at = time.monotonic()
            lim.consecutive_fail += 1
            if lim.consecutive_fail >= 6:
                lim.stopped = True
                lim.stop_reason = "6-consecutive-failures"
            return ("error", None, str(exc)[:200], url)

        lim.last_request_at = time.monotonic()

        if is_challenge(status, text):
            lim.stopped = True
            lim.stop_reason = "human-verification-challenge"
            return ("challenge", status, text, final_url)

        if status == 401:
            lim.consecutive_fail += 1
            outcome = "401"
        elif status == 403:
            lim.consecutive_fail += 1
            outcome = "403"
        elif status == 404:
            lim.consecutive_fail += 1
            outcome = "404"
        elif 200 <= status < 300:
            lim.consecutive_fail = 0
            if expect_json and parse_json_or_none(text) is None:
                outcome = "answered_html_fallback"
            else:
                outcome = "answered"
        elif 300 <= status < 400:
            lim.consecutive_fail = 0
            outcome = "answered"
        else:
            lim.consecutive_fail += 1
            outcome = f"http_{status}"

        if lim.consecutive_fail >= 6:
            lim.stopped = True
            lim.stop_reason = "6-consecutive-failures"

        return (outcome, status, text, final_url)


async def probe_site(
    session: aiohttp.ClientSession, row: Dict[str, str], writer: csv.DictWriter, out_f
) -> Dict[str, Any]:
    gov_id = row["gov_id"]
    name = row["name"]
    state = row["state"]
    set_ = row["set"]
    domain = row["domain"].strip()
    known_video_url = (row.get("archive_video_url") or "").strip()

    summary: Dict[str, Any] = {
        "gov_id": gov_id,
        "name": name,
        "state": state,
        "set": set_,
        "domain": domain,
        "known_video_url": known_video_url,
    }

    def record(probe: str, path: str, outcome: str, status, evidence: str):
        r = ProbeResult(
            gov_id=gov_id,
            name=name,
            state=state,
            set_=set_,
            domain=domain,
            probe=probe,
            url=f"https://{domain}{path}",
            outcome=outcome,
            status=status,
            evidence=evidence[:1500],
        )
        writer.writerow(r.__dict__)
        out_f.flush()
        return r

    surfaces_reached_video: List[str] = []

    def check_known_video(probe_name: str, text: str):
        if known_video_url and known_video_url in text:
            surfaces_reached_video.append(probe_name)
        # also try just the video id/slug fragment for youtube embeds
        elif known_video_url:
            frag = known_video_url.rstrip("/").split("/")[-1]
            if frag and len(frag) > 6 and frag in text:
                surfaces_reached_video.append(probe_name)

    # 1. /feed/
    outcome, status, text, _ = await do_get(session, domain, "/feed/")
    record("feed", "/feed/", outcome, status, text[:300] if text else "")
    feed_meeting_words: List[str] = []
    feed_video_markers: List[str] = []
    feed_item_count = 0
    feed_strict_markers: List[str] = []
    if outcome == "answered" and text:
        feed_meeting_words = meeting_word_hits(text)
        feed_video_markers = video_marker_hits(text)
        feed_strict_markers = strict_video_marker_hits(text)
        feed_item_count = text.count("<item>") or text.count("<entry>")
        check_known_video("feed", text)
    summary["feed_outcome"] = outcome
    summary["feed_item_count"] = feed_item_count
    summary["feed_meeting_words"] = ";".join(feed_meeting_words)
    summary["feed_strict_video_markers"] = ";".join(feed_strict_markers)
    summary["feed_video_markers"] = ";".join(feed_video_markers)

    # 2. /wp-json/
    outcome, status, text, _ = await do_get(
        session, domain, "/wp-json/", expect_json=True
    )
    namespaces: List[str] = []
    if outcome == "answered" and text:
        try:
            data = json.loads(text)
            namespaces = data.get("namespaces", []) if isinstance(data, dict) else []
        except Exception:  # noqa: BLE001
            namespaces = []
    record(
        "wp_json_root",
        "/wp-json/",
        outcome,
        status,
        ";".join(namespaces) if namespaces else (text[:300] if text else ""),
    )
    summary["wp_json_outcome"] = outcome
    summary["wp_json_namespaces"] = ";".join(namespaces)

    # 3. /wp-json/wp/v2/types
    outcome, status, text, _ = await do_get(
        session, domain, "/wp-json/wp/v2/types", expect_json=True
    )
    custom_types: List[str] = []
    if outcome == "answered" and text:
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                custom_types = list(data.keys())
        except Exception:  # noqa: BLE001
            pass
    record(
        "wp_json_types", "/wp-json/wp/v2/types", outcome, status, ";".join(custom_types)
    )
    summary["types_outcome"] = outcome
    summary["custom_post_types"] = ";".join(custom_types)
    interesting_types = [
        t
        for t in custom_types
        if t in ("meeting", "agenda", "minutes", "event", "video", "tribe_events")
    ]
    summary["interesting_post_types"] = ";".join(interesting_types)

    # 4. posts search x6
    posts_search_hits = {}
    posts_video_marker_words = []
    posts_strict_markers_seen: List[str] = []
    for word in POSTS_SEARCH_WORDS:
        path = f"/wp-json/wp/v2/posts?search={quote(word)}&per_page=20"
        outcome, status, text, _ = await do_get(session, domain, path, expect_json=True)
        count = 0
        titles: List[str] = []
        has_video_marker = False
        strict_hits: List[str] = []
        if outcome == "answered" and text:
            try:
                data = json.loads(text)
                if isinstance(data, list):
                    count = len(data)
                    for item in data[:5]:
                        t = item.get("title", {}).get("rendered", "")
                        titles.append(t)
                    combined_content = " ".join(
                        item.get("content", {}).get("rendered", "") for item in data
                    )
                    if video_marker_hits(combined_content):
                        has_video_marker = True
                    strict_hits = strict_video_marker_hits(combined_content)
                    check_known_video(f"posts_search_{word}", combined_content)
            except Exception:  # noqa: BLE001
                pass
        record(
            f"posts_search_{word}",
            path,
            outcome,
            status,
            f"count={count} titles={titles} video_marker={has_video_marker} strict={strict_hits}",
        )
        posts_search_hits[word] = count
        if has_video_marker:
            posts_video_marker_words.append(word)
        posts_strict_markers_seen.extend(strict_hits)
    summary["posts_search_outcome"] = (
        outcome  # last one's outcome as availability proxy
    )
    for word in POSTS_SEARCH_WORDS:
        summary[f"posts_search_{word}_count"] = posts_search_hits.get(word, 0)
    summary["posts_search_video_marker_words"] = ";".join(posts_video_marker_words)
    summary["posts_search_strict_video_markers"] = ";".join(
        sorted(set(posts_strict_markers_seen))
    )

    # 5. media video / audio
    for media_type in ("video", "audio"):
        path = f"/wp-json/wp/v2/media?media_type={media_type}&per_page=20"
        outcome, status, text, _ = await do_get(session, domain, path, expect_json=True)
        count = 0
        mimes: List[str] = []
        sample_urls: List[str] = []
        if outcome == "answered" and text:
            try:
                data = json.loads(text)
                if isinstance(data, list):
                    count = len(data)
                    for item in data[:5]:
                        mimes.append(item.get("mime_type", ""))
                        src = item.get("source_url", "")
                        if src:
                            sample_urls.append(src)
                    check_known_video(f"media_{media_type}", text)
            except Exception:  # noqa: BLE001
                pass
        record(
            f"media_{media_type}",
            path,
            outcome,
            status,
            f"count={count} mimes={mimes} samples={sample_urls}",
        )
        summary[f"media_{media_type}_outcome"] = outcome
        summary[f"media_{media_type}_count"] = count

    # 6. events endpoints
    event_endpoints = []
    if "tribe/events/v1" in namespaces or any(
        ns.startswith("tribe") for ns in namespaces
    ):
        event_endpoints.append("/wp-json/tribe/events/v1/events?per_page=20")
    for ns in namespaces:
        if ns not in ("wp/v2", "tribe/events/v1") and (
            "event" in ns or "mec" in ns or "eventon" in ns
        ):
            event_endpoints.append(f"/wp-json/{ns}")
    events_found_video = False
    events_count_total = 0
    for path in event_endpoints[:2]:
        outcome, status, text, _ = await do_get(session, domain, path, expect_json=True)
        count = 0
        if outcome == "answered" and text:
            try:
                data = json.loads(text)
                if isinstance(data, dict) and "events" in data:
                    count = len(data["events"])
                    combined = json.dumps(data["events"])[:20000]
                elif isinstance(data, list):
                    count = len(data)
                    combined = json.dumps(data)[:20000]
                else:
                    combined = text[:2000]
                if video_marker_hits(combined):
                    events_found_video = True
                check_known_video("events", combined)
            except Exception:  # noqa: BLE001
                pass
        record("events", path, outcome, status, f"count={count}")
        events_count_total += count
    summary["events_endpoints_tried"] = len(event_endpoints[:2])
    summary["events_count_total"] = events_count_total
    summary["events_found_video_marker"] = events_found_video

    # 7. sitemaps
    sitemap_subsitemaps: List[str] = []
    sitemap_outcome = "skipped"
    for path in ("/wp-sitemap.xml", "/sitemap_index.xml"):
        outcome, status, text, _ = await do_get(session, domain, path)
        subs: List[str] = []
        if outcome == "answered" and text:
            try:
                root = ET.fromstring(text)
                for loc in root.iter():
                    if loc.tag.endswith("loc") and loc.text:
                        subs.append(loc.text)
            except Exception:  # noqa: BLE001
                subs = re.findall(r"<loc>([^<]+)</loc>", text)
        record(
            f"sitemap_{path.strip('/').replace('.', '_')}",
            path,
            outcome,
            status,
            ";".join(subs[:30]),
        )
        if outcome == "answered":
            sitemap_outcome = "answered"
            sitemap_subsitemaps.extend(subs)
    interesting_sitemaps = [
        s
        for s in sitemap_subsitemaps
        if any(w in s.lower() for w in ("meeting", "agenda", "event", "minutes"))
    ]
    summary["sitemap_outcome"] = sitemap_outcome
    summary["sitemap_subsitemap_count"] = len(sitemap_subsitemaps)
    summary["sitemap_interesting"] = ";".join(interesting_sitemaps[:10])

    # 8. site search
    site_search_hits = {}
    site_search_video_words = []
    site_search_strict_markers: List[str] = []
    for word in SEARCH_TERMS:
        path = f"/?s={quote(word)}"
        outcome, status, text, _ = await do_get(session, domain, path)
        result_count_marker = ""
        has_video = False
        strict_hits: List[str] = []
        if outcome == "answered" and text:
            # crude result-count heuristic: count of "search-result" / article tags
            result_count_marker = str(
                len(re.findall(r"class=\"[^\"]*search-result", text, re.I))
                or text.lower().count("<article")
            )
            if video_marker_hits(text):
                has_video = True
            strict_hits = strict_video_marker_hits(text)
            check_known_video(f"site_search_{word}", text)
        record(
            f"site_search_{word}",
            path,
            outcome,
            status,
            f"results~{result_count_marker} video={has_video} strict={strict_hits}",
        )
        site_search_hits[word] = outcome
        if has_video:
            site_search_video_words.append(word)
        site_search_strict_markers.extend(strict_hits)
    summary["site_search_outcome"] = outcome
    summary["site_search_video_marker_words"] = ";".join(site_search_video_words)
    summary["site_search_strict_video_markers"] = ";".join(
        sorted(set(site_search_strict_markers))
    )

    # 9. front page
    outcome, status, text, final_url = await do_get(session, domain, "/")
    plugins: List[str] = []
    theme = ""
    front_video = False
    front_video_markers: List[str] = []
    front_strict_markers: List[str] = []
    if outcome == "answered" and text:
        plugins = sorted(set(re.findall(r"wp-content/plugins/([a-zA-Z0-9_\-]+)", text)))
        theme_match = re.findall(r"wp-content/themes/([a-zA-Z0-9_\-]+)", text)
        theme = theme_match[0] if theme_match else ""
        front_video_markers = video_marker_hits(text)
        front_strict_markers = strict_video_marker_hits(text)
        front_video = bool(front_video_markers)
        check_known_video("front_page", text)
    record(
        "front_page",
        "/",
        outcome,
        status,
        f"plugins={plugins} theme={theme} strict={front_strict_markers}",
    )
    summary["front_page_outcome"] = outcome
    summary["front_page_plugins"] = ";".join(plugins)
    summary["front_page_theme"] = theme
    summary["front_page_video_marker"] = front_video
    summary["front_page_video_markers"] = ";".join(front_video_markers)
    summary["front_page_strict_video_markers"] = ";".join(front_strict_markers)

    summary["known_video_surfaces_reached"] = ";".join(
        sorted(set(surfaces_reached_video))
    )
    summary["host_stopped_reason"] = limiter_for(domain).stop_reason

    return summary


async def main() -> None:
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_INPUT_CSV
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.cwd()
    results_csv = out_dir / "wo270_probe_results.csv"
    summary_csv = out_dir / "wo270_site_summary.csv"

    with open(input_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    results_fields = [
        "gov_id",
        "name",
        "state",
        "set_",
        "domain",
        "probe",
        "url",
        "outcome",
        "status",
        "evidence",
    ]
    out_results = open(results_csv, "w", newline="", encoding="utf-8")
    writer = csv.DictWriter(out_results, fieldnames=results_fields)
    writer.writeheader()

    sem = asyncio.Semaphore(CONCURRENT_SITES)
    summaries: List[Dict[str, Any]] = []

    connector = aiohttp.TCPConnector(limit=CONCURRENT_SITES * 2)
    async with aiohttp.ClientSession(connector=connector) as session:

        async def bound_probe(row):
            async with sem:
                try:
                    return await probe_site(session, row, writer, out_results)
                except Exception as exc:  # noqa: BLE001
                    print(f"ERROR on {row.get('domain')}: {exc}", file=sys.stderr)
                    return {
                        "gov_id": row["gov_id"],
                        "name": row["name"],
                        "state": row["state"],
                        "set": row["set"],
                        "domain": row["domain"],
                        "error": str(exc)[:300],
                    }

        tasks = [asyncio.create_task(bound_probe(row)) for row in rows]
        done_count = 0
        for coro in asyncio.as_completed(tasks):
            summary = await coro
            summaries.append(summary)
            done_count += 1
            if done_count % 10 == 0:
                print(f"...{done_count}/{len(rows)} sites done", file=sys.stderr)

    out_results.close()

    # write summary csv -- union of all keys seen
    all_keys: List[str] = []
    seen = set()
    for s in summaries:
        for k in s.keys():
            if k not in seen:
                seen.add(k)
                all_keys.append(k)
    with open(summary_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=all_keys)
        w.writeheader()
        for s in summaries:
            w.writerow(s)

    print(f"Done. {len(summaries)} sites summarized -> {summary_csv}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
