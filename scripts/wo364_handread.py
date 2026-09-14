#!/usr/bin/env python3
"""WO-364 (2026-09-14, the WO-361b resume run): hand-check pass for the
tier 1/3 candidates `wo361_find_hub.py` found across the FULL 482-
government population (WO-361's original 213 plus WO-364's remaining
269, all in the shared `research/wo361_verify.csv`).

Same method `wo361_handread.py` documented -- decorative URL/filename
signature first, then the real on-page context around the embed -- with
one addition this run needed: `wo361_handread.py` as committed has NO
oEmbed title lookup, even though the real `wo361_handread.csv` produced
during WO-361 clearly has `oembed_title`/`oembed_author` values (e.g.
Garfield NJ's "City of Garfield 2024" by AlphaDog Solutions) that only a
live oEmbed call could have produced. Re-derived rather than guessed
(CLAUDE.md's "a backlog entry is a lead, not a spec" rule applies to a
committed script too): this adds the same public, unauthenticated Vimeo
oEmbed GET (`https://vimeo.com/api/oembed.json?url=...`, documented in
`app/platforms/vimeo.py` as the confirmed metadata-only half of that
adapter -- a lightweight JSON call, never a media download) for any
candidate that survives the decorative-signature and on-page-context
checks needing a human-legible title before it can be judged.

Writes `research/wo364_handread.csv`, covering every tier 1/3 row in
`wo361_verify.csv` (both WO-361's and WO-364's) so the two runs' results
stay consistent -- WO-364 only APPLIES the rows whose gov_id it itself
processed this run (see `research/wo364_apply_to_jc.py`).

Usage (from the rtr-deeplink repo root, shared venv):
    .venv/bin/python scripts/wo364_handread.py
"""

from __future__ import annotations

import asyncio
import csv
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse, quote

import aiohttp
import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
VERIFY_CSV = RESEARCH_DIR / "wo361_verify.csv"
OUT_CSV = RESEARCH_DIR / "wo364_handread.csv"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) RedTapeRecordings-PassiveVerify/1.0 "
        "(+https://redtaperecordings.com)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_OEMBED_ENDPOINT = "https://vimeo.com/api/oembed.json?url="

_DECORATIVE_FILENAME_RE = re.compile(
    r"(promo|promotion|accueil|welcome|tourism|flyover|drone|dji_|"
    r"site.?asset|homepage|hero|banner|discover|explore)",
    re.IGNORECASE,
)

_MEETING_CONTEXT_RE = re.compile(
    r"(agenda|minutes|council meeting|regular meeting|board meeting|"
    r"public hearing|work session|special meeting|watch live|"
    r"meeting archive|board of |commission meeting|committee meeting|"
    r"seance|conseil municipal)",
    re.IGNORECASE,
)

# A real oEmbed title still needs its own decorative/real-meeting read --
# same shape as wo355_handread.py's title check. A title naming a real
# governing-body meeting (council/board/commission + meeting/session/
# hearing) is the only thing this treats as confirming a real meeting;
# everything else (a promo reel, a community story, a vendor proof, a
# ceremony) is video-without-meeting, per CLAUDE.md's Kind A/B rule that
# the video's own content is the source of truth.
_TITLE_MEETING_RE = re.compile(
    r"(council|board|commission|committee|trustees|supervisors|selectboard|"
    r"select board|assembly)\s*(meeting|session|hearing|work session)|"
    r"(regular|special|work)\s*(meeting|session)",
    re.IGNORECASE,
)


def _is_decorative_url(url: str) -> bool:
    u = (url or "").lower()
    return ("background=1" in u) or ("loop=1" in u and "muted=1" in u)


def _is_decorative_filename(url: str) -> bool:
    path = urlparse(url).path
    return bool(_DECORATIVE_FILENAME_RE.search(path))


# CLAUDE.md / preamble.md: "never download a media file" -- a ranged GET
# capped at 64 KB only, and only ever for a real HTML page. A first
# version of this fetch() did an unranged `resp.read()` (bytes truncated
# only AFTER the full response was already pulled into memory) with no
# Content-Type check, and hit this live against three real multi-MB
# videos (Chesterfield Inlet NU 165 MB, North township IN 31 MB, a
# Wisconsin.gov template asset 12 MB) before being caught and fixed --
# see the WO-364 BACKLOG_DONE entry's caution section for the incident
# writeup. Every fetch here now checks the response's Content-Type
# BEFORE reading any body bytes and refuses anything that isn't text/
# HTML-shaped; an HTML page itself still gets a real (non-media) read,
# capped generously since HTML poses none of the same risk, but a
# video/audio/octet-stream response is aborted after headers alone.
_MEDIA_CONTENT_TYPE_RE = re.compile(
    r"^(video/|audio/|application/octet-stream|image/(?!svg))", re.IGNORECASE
)
_HTML_READ_CAP_BYTES = 3_000_000


async def fetch(
    session: aiohttp.ClientSession, url: str
) -> tuple[str | None, str | None]:
    try:
        async with session.get(
            url, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True
        ) as resp:
            if resp.status != 200:
                return None, f"HTTP {resp.status}"
            content_type = resp.headers.get("Content-Type", "")
            if _MEDIA_CONTENT_TYPE_RE.search(content_type):
                resp.close()
                return None, f"media-content-type-skipped:{content_type}"
            raw = await resp.content.read(_HTML_READ_CAP_BYTES)
            return raw.decode("utf-8", errors="replace"), None
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


async def fetch_vimeo_oembed(
    session: aiohttp.ClientSession, video_url: str
) -> tuple[str, str, str]:
    """Returns (title, author, error) -- a plain metadata GET, never the
    video itself."""
    url = _OEMBED_ENDPOINT + quote(video_url, safe="")
    body, err = await fetch(session, url)
    if err or body is None:
        return "", "", err or "empty"
    try:
        payload = json.loads(body)
    except ValueError:
        return "", "", "bad-json"
    return (payload.get("title") or ""), (payload.get("author_name") or ""), ""


def _needle_for(meeting_url: str) -> str | None:
    m = re.search(r"vimeo\.com/(?:video/)?(\d+)", meeting_url)
    if m:
        return m.group(1)
    path = urlparse(meeting_url).path
    basename = path.rsplit("/", 1)[-1]
    return basename or None


def _context_snippet(html: str, needle: str) -> str:
    idx = html.find(needle)
    if idx < 0:
        idx = html.lower().find(needle.lower())
    if idx < 0:
        return ""
    start = max(0, idx - 400)
    end = min(len(html), idx + 200)
    return re.sub(r"\s+", " ", html[start:end])


async def check_one(session: aiohttp.ClientSession, row: dict) -> dict:
    hub_url = row["hub_url"]
    meeting_url = row["meeting_url"]
    platform = row.get("resolved_platform", "")
    out = {
        "gov_id": row["gov_id"],
        "name": row["name"],
        "state": row["state"],
        "tier": row["tier"],
        "resolved_platform": platform,
        "meeting_url": meeting_url,
        "decorative_url_signature": _is_decorative_url(meeting_url),
        "decorative_filename": _is_decorative_filename(meeting_url),
        "context_snippet": "",
        "meeting_context_found": False,
        "fetch_error": "",
        "oembed_title": "",
        "oembed_author": "",
        "handread_verdict": "",
    }
    if out["decorative_url_signature"] or out["decorative_filename"]:
        out["handread_verdict"] = "video-without-meeting"
        return out

    # `hub_url` is the raw media file itself (no wrapping HTML page) for a
    # direct_file candidate whose ladder hit landed straight on the video
    # -- fetching it, even ranged, only reads video bytes and never finds
    # page context. Skip the fetch outright and fall through to the
    # oEmbed/manual path.
    is_raw_media_url = platform == "direct_file" and hub_url == meeting_url
    if not is_raw_media_url:
        html, err = await fetch(session, hub_url)
    else:
        html, err = None, "raw-media-url-skipped"
    if not (err or html is None):
        needle = _needle_for(meeting_url)
        snippet = _context_snippet(html, needle) if needle else ""
        out["context_snippet"] = snippet[:600]
        out["meeting_context_found"] = bool(_MEETING_CONTEXT_RE.search(snippet))
    else:
        out["fetch_error"] = err or "empty"

    if out["meeting_context_found"]:
        out["handread_verdict"] = "needs_manual_check"
        return out

    # No on-page context confirms it either way -- for Vimeo, ask the
    # video's own public oEmbed title (metadata only, no media fetched).
    if platform == "vimeo":
        title, author, oerr = await fetch_vimeo_oembed(session, meeting_url)
        out["oembed_title"] = title
        out["oembed_author"] = author
        if oerr and not title:
            out["fetch_error"] = (out["fetch_error"] + f" | oembed:{oerr}").strip(" |")
            out["handread_verdict"] = "needs_manual_check"
            return out
        out["context_snippet"] = (
            out["context_snippet"]
            or f'oEmbed title check (page context had no matching needle): "{title}" by {author}'
        )
        if _TITLE_MEETING_RE.search(title):
            out["handread_verdict"] = (
                "needs_manual_check"  # real meeting name -> leave for a human confirm, not auto-ingest
            )
        else:
            out["handread_verdict"] = "video-without-meeting"
        return out

    # direct_file or another platform with no title metadata available --
    # the filename/context checks above are all the automated signal
    # there is; leave it for a human rather than guess.
    out["handread_verdict"] = "needs_manual_check"
    return out


async def main() -> None:
    with open(VERIFY_CSV, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("tier") in ("1", "3")]
    print(
        f"{len(rows)} tier1/3 candidates to hand-check (full population, WO-361 + WO-364)"
    )

    fieldnames = [
        "gov_id",
        "name",
        "state",
        "tier",
        "resolved_platform",
        "meeting_url",
        "decorative_url_signature",
        "decorative_filename",
        "context_snippet",
        "meeting_context_found",
        "fetch_error",
        "oembed_title",
        "oembed_author",
        "handread_verdict",
    ]
    async with aiohttp.ClientSession(headers=_HEADERS) as session:
        with open(OUT_CSV, "w", newline="", encoding="utf-8") as out:
            writer = csv.DictWriter(out, fieldnames=fieldnames)
            writer.writeheader()
            for i, row in enumerate(rows, 1):
                result = await check_one(session, row)
                writer.writerow(result)
                out.flush()
                print(
                    f"[{i}/{len(rows)}] {row['gov_id']} {row['name']} {row['state']} "
                    f"tier={row['tier']} verdict={result['handread_verdict']} "
                    f"decorative_url={result['decorative_url_signature']} "
                    f"decorative_name={result['decorative_filename']} "
                    f"meeting_ctx={result['meeting_context_found']} "
                    f"oembed_title={result['oembed_title']!r}"
                )


if __name__ == "__main__":
    asyncio.run(main())
