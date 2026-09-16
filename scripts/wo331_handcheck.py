"""WO-331: positive controls for passive discovery v2 -- steps 4 and 5.

Step 4 (hand-check, exactly as the WO-320..327 sweeps ran their own
`wo3NN_resolve_diagnostic.py`): call the real `resolve()` on Phase 3's
CONFIRMED candidate URL for each control government and record what it
returns (video found? real segments? CalendarPageError? resolve failed?).

Step 5 (the hop the sweeps did NOT take): from that same confirmed
page, take one navigation hop toward a specific meeting-detail URL (the
platform's own listing/adapter where one exists, otherwise the newest
meeting-detail-shaped link already visible on the confirmed page) and
call `resolve()` on THAT url too.

Safety: never fetches a youtube.com/youtu.be URL, per the brief's rule.
Two guards:
  1. Any *_platform_ value of "youtube" (`detect_platform(url) ==
     "youtube"`) is never handed to `resolve()` at all -- youtube.py's
     resolve() goes straight to yt-dlp with no aiohttp fetch first, so
     there is nothing to intercept afterward.
  2. A process-wide monkeypatch on aiohttp.ClientSession._request blocks
     any outbound request whose host is a youtube.com/youtu.be family
     host and raises YouTubeFetchBlocked -- this is what actually stops
     a delegating adapter (legistar/civicplus/civicweb/municode_meetings)
     from silently chasing an embedded YouTube link via its own aiohttp
     session, since every one of those adapters fetches the linked video
     URL via the *same* aiohttp session before ever reaching yt-dlp.
When either guard fires, the result is recorded as "YOUTUBE_LEAD" (a
positive finding -- video exists -- without the fetch), never treated as
a negative.

Read-only: never POSTs to the Archive, never ingests.

Usage:
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo331_handcheck_scratch.db" \\
        .venv/bin/python scripts/wo331_handcheck.py
"""

from __future__ import annotations

import asyncio
import csv
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import aiohttp  # noqa: E402
import requests  # noqa: E402
from bs4 import BeautifulSoup  # noqa: E402

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import (  # noqa: E402
    CalendarPageError,
    UnsupportedPlatformError,
    detect_platform,
    get_finder,
)

register_all_finders()

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
REPORT_CSV = RESEARCH_DIR / "wo331_report.csv"
TARGETED_CSV = RESEARCH_DIR / "wo331_targeted.csv"
OUT_CSV = RESEARCH_DIR / "wo331_handcheck.csv"

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}

HONEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "RedTapeRecordings-WO331/1.0 (+https://redtaperecordings.com)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class YouTubeFetchBlocked(Exception):
    """Raised by the aiohttp guard below when any code path -- ours or an
    adapter's own delegation logic -- tries to fetch a youtube.com/
    youtu.be family host. Caught by the driver and recorded as a
    positive "YOUTUBE_LEAD" finding, never as a negative."""


def _is_youtube_host(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    except Exception:  # noqa: BLE001
        return False
    return host in YOUTUBE_HOSTS


def install_youtube_guard() -> None:
    """Monkeypatch aiohttp.ClientSession._request process-wide so ANY
    outbound request to a youtube.com/youtu.be host raises
    YouTubeFetchBlocked instead of going out over the network. This is
    what stops legistar.py/civicplus.py/civicweb.py/municode_meetings.py
    (which fetch a discovered video link via their own aiohttp session
    before dispatching to the youtube finder) from ever reaching
    youtube.com, without needing per-adapter special-casing."""
    orig_request = aiohttp.ClientSession._request

    async def guarded_request(self, method, str_or_url, *args, **kwargs):
        url = str(str_or_url)
        if _is_youtube_host(url):
            raise YouTubeFetchBlocked(f"blocked aiohttp fetch to {url}")
        return await orig_request(self, method, str_or_url, *args, **kwargs)

    aiohttp.ClientSession._request = guarded_request


MEETING_DETAIL_HINTS = re.compile(
    r"(MeetingDetail|meeting-detail|MeetingInformation|Meeting\.aspx|"
    r"ViewMeeting|/meeting/|/meetings/|/event/|/events/|clip_id|player/clip|"
    r"MediaPlayer\.php|show/\d|/vod/|AgendaViewer|agenda-and-minutes|"
    r"page/[a-z0-9-]+-\d+$)",
    re.IGNORECASE,
)
LISTING_HINTS = re.compile(
    r"(Calendar\.aspx|AgendaCenter$|/events$|/events/|Board-of-County|"
    r"agendas-minutes|Agendas-Minutes|meetings$|Meetings$)",
    re.IGNORECASE,
)


def find_meeting_detail_link(html: str, base_url: str) -> str | None:
    """Best-effort: the first link on a confirmed hub/listing page whose
    href or anchor text looks like a specific meeting/clip, rather than
    another listing. Not the production hop-link scorer -- a one-off,
    good-enough link picker for this WO's step 5 only."""
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:")):
            continue
        full = urljoin(base_url, href)
        text = a.get_text(" ", strip=True)
        if MEETING_DETAIL_HINTS.search(full) or MEETING_DETAIL_HINTS.search(text):
            candidates.append(full)
    # Prefer the first candidate found in document order (usually newest
    # on a reverse-chronological listing).
    return candidates[0] if candidates else None


def fetch_plain(url: str) -> tuple[int | None, str | None, str]:
    try:
        resp = requests.get(url, headers=HONEST_HEADERS, timeout=20)
        return resp.status_code, resp.url, resp.text
    except Exception as e:  # noqa: BLE001
        return None, None, f"FETCH_ERROR: {type(e).__name__}: {e}"


async def resolve_safely(url: str) -> dict:
    """Call detect_platform()+resolve() on url, respecting the
    never-fetch-youtube guard. Returns a flat result dict."""
    if _is_youtube_host(url):
        return {
            "verdict": "YOUTUBE_LEAD",
            "detail": "confirmed URL is itself a youtube.com/youtu.be host -- not fetched",
        }
    try:
        platform = detect_platform(url)
    except Exception as e:  # noqa: BLE001
        return {"verdict": "DETECT_FAILED", "detail": f"{type(e).__name__}: {e}"}
    if platform == "unknown":
        return {"verdict": "UNSUPPORTED", "detail": "detect_platform -> unknown"}
    try:
        finder = get_finder(platform)
    except UnsupportedPlatformError as e:
        return {"verdict": "UNSUPPORTED", "detail": str(e)}

    try:
        result = await finder.resolve(url)
    except YouTubeFetchBlocked as e:
        return {"verdict": "YOUTUBE_LEAD", "detail": str(e)}
    except CalendarPageError as e:
        return {
            "verdict": "CALENDAR_PAGE",
            "detail": str(e)[:300],
            "n_candidates": len(getattr(e, "candidates", []) or []),
        }
    except Exception as e:  # noqa: BLE001
        return {
            "verdict": "RESOLVE_FAILED",
            "detail": f"{type(e).__name__}: {str(e)[:300]}",
        }

    segments = len(result.segments or [])
    agenda_items = len(result.agenda_items or [])
    has_video = bool(result.video_url)
    return {
        "verdict": "RESOLVED",
        "platform": result.platform,
        "title": result.title,
        "video_url": result.video_url,
        "has_video": has_video,
        "segments": segments,
        "agenda_items": agenda_items,
        "agenda_link": bool(result.agenda_link),
        "source_url": result.source_url,
        "detail": "",
    }


async def main() -> None:
    install_youtube_guard()

    with open(REPORT_CSV, newline="", encoding="utf-8") as f:
        report_rows = list(csv.DictReader(f))

    out_rows = []
    for row in report_rows:
        domain = row["domain"]
        group = row.get("group", "")
        best_url = row.get("best_url", "")
        outcome = row.get("outcome", "")
        print(f"\n=== {domain} ({group}) outcome={outcome} ===", file=sys.stderr)

        result = {
            "domain": domain,
            "gov_id": row.get("gov_id", ""),
            "name": row.get("name", ""),
            "state": row.get("state", ""),
            "group": group,
            "phase3_outcome": outcome,
            "phase3_platform_guess": row.get("platform", ""),
            "phase3_platform_confirmed": row.get("platform_confirmed", ""),
            "confirmed_url": best_url,
        }

        if outcome != "platform-confirmed" or not best_url:
            result["step4_verdict"] = "NOT_REACHED"
            result["step4_detail"] = f"phase3 outcome={outcome!r}, no confirmed URL"
            result["step5_verdict"] = "NOT_REACHED"
            result["step5_detail"] = "n/a"
            out_rows.append(result)
            continue

        # Step 4: hand-check exactly as the sweeps did it.
        r4 = await resolve_safely(best_url)
        for k, v in r4.items():
            result[f"step4_{k}"] = v
        print(
            f"  step4: {r4.get('verdict')} {r4.get('detail', '')[:150]}",
            file=sys.stderr,
        )
        await asyncio.sleep(1.5)

        # Step 5: one hop through the listing to a meeting-detail URL.
        status, final_url, body = fetch_plain(best_url)
        hop_url = None
        if (
            status
            and 200 <= status < 300
            and body
            and not body.startswith("FETCH_ERROR")
        ):
            hop_url = find_meeting_detail_link(body, final_url or best_url)

        if not hop_url:
            result["step5_hop_url"] = ""
            result["step5_verdict"] = "NO_HOP_LINK_FOUND"
            result["step5_detail"] = (
                f"fetch status={status}; no meeting-detail-shaped link found on the confirmed page"
            )
        elif hop_url == best_url:
            result["step5_hop_url"] = hop_url
            result["step5_verdict"] = "SAME_AS_STEP4"
            result["step5_detail"] = (
                "best-guess hop link resolved to the same URL as step 4"
            )
        else:
            result["step5_hop_url"] = hop_url
            r5 = await resolve_safely(hop_url)
            for k, v in r5.items():
                result[f"step5_{k}"] = v
            print(f"  step5 hop={hop_url}", file=sys.stderr)
            print(
                f"  step5: {r5.get('verdict')} {r5.get('detail', '')[:150]}",
                file=sys.stderr,
            )

        await asyncio.sleep(1.5)
        out_rows.append(result)

    fieldnames = sorted({k for r in out_rows for k in r.keys()})
    # Keep a stable, readable leading column order.
    lead = [
        "domain",
        "gov_id",
        "name",
        "state",
        "group",
        "phase3_outcome",
        "phase3_platform_guess",
        "phase3_platform_confirmed",
        "confirmed_url",
        "step4_verdict",
        "step4_has_video",
        "step4_segments",
        "step4_detail",
        "step5_hop_url",
        "step5_verdict",
        "step5_has_video",
        "step5_segments",
        "step5_detail",
    ]
    ordered = lead + [f for f in fieldnames if f not in lead]
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f, fieldnames=ordered, extrasaction="ignore", lineterminator="\n"
        )
        w.writeheader()
        w.writerows(out_rows)
    print(f"\nwrote {OUT_CSV} ({len(out_rows)} rows)", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
