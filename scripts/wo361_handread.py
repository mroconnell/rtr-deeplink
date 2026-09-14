#!/usr/bin/env python3
"""WO-361 (2026-09-13): hand-check pass for `research/wo361_verify.csv`'s
tier 1/3 candidates (tier 2 is always a YouTube lead, never fetched).

Same method as `wo355_handread.py` (its own decorative-video false-
positive finding applies here too -- `wo361_find_hub.py`'s own
`_is_decorative_hit()` pre-filter already rejects the URL-signature
cases, so a tier 1/3 candidate here already survived that; this pass
re-fetches the hub page and reads the real on-page context AROUND the
video for an agenda/meeting-shaped phrase vs. a decorative-page
signature). Never fetches a youtube.com/youtu.be URL. Never downloads a
media file -- only the HTML page that embeds the video is fetched, the
video's own bytes are never read.

Writes `research/wo361_handread.csv`.

Usage (from the rtr-deeplink repo root, shared venv):
    .venv/bin/python scripts/wo361_handread.py
"""

from __future__ import annotations

import asyncio
import csv
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
VERIFY_CSV = RESEARCH_DIR / "wo361_verify.csv"
OUT_CSV = RESEARCH_DIR / "wo361_handread.csv"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) RedTapeRecordings-PassiveVerify/1.0 "
        "(+https://redtaperecordings.com)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

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


def _is_decorative_url(url: str) -> bool:
    u = (url or "").lower()
    return ("background=1" in u) or ("loop=1" in u and "muted=1" in u)


def _is_decorative_filename(url: str) -> bool:
    path = urlparse(url).path
    return bool(_DECORATIVE_FILENAME_RE.search(path))


async def fetch(url: str) -> tuple[str | None, str | None]:
    try:
        async with aiohttp.ClientSession(headers=_HEADERS) as session:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=20), allow_redirects=True
            ) as resp:
                if resp.status != 200:
                    return None, f"HTTP {resp.status}"
                raw = await resp.read()
                if len(raw) > 3_000_000:
                    raw = raw[:3_000_000]
                return raw.decode("utf-8", errors="replace"), None
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


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


async def check_one(row: dict) -> dict:
    hub_url = row["hub_url"]
    meeting_url = row["meeting_url"]
    out = {
        "gov_id": row["gov_id"],
        "name": row["name"],
        "state": row["state"],
        "tier": row["tier"],
        "resolved_platform": row["resolved_platform"],
        "meeting_url": meeting_url,
        "decorative_url_signature": _is_decorative_url(meeting_url),
        "decorative_filename": _is_decorative_filename(meeting_url),
        "context_snippet": "",
        "meeting_context_found": False,
        "fetch_error": "",
        "handread_verdict": "",
    }
    if out["decorative_url_signature"] or out["decorative_filename"]:
        out["handread_verdict"] = "video-without-meeting"
        return out

    html, err = await fetch(hub_url)
    if err or html is None:
        out["fetch_error"] = err or "empty"
        out["handread_verdict"] = "needs_manual_check"
        return out

    needle = _needle_for(meeting_url)
    snippet = _context_snippet(html, needle) if needle else ""
    out["context_snippet"] = snippet[:600]
    out["meeting_context_found"] = bool(_MEETING_CONTEXT_RE.search(snippet))
    out["handread_verdict"] = (
        "needs_manual_check"
        if out["meeting_context_found"]
        else "video-without-meeting"
    )
    return out


async def main() -> None:
    with open(VERIFY_CSV, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("tier") in ("1", "3")]
    print(f"{len(rows)} tier1/3 candidates to hand-check")

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
        "handread_verdict",
    ]
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as out:
        writer = csv.DictWriter(out, fieldnames=fieldnames)
        writer.writeheader()
        for i, row in enumerate(rows, 1):
            result = await check_one(row)
            writer.writerow(result)
            out.flush()
            print(
                f"[{i}/{len(rows)}] {row['gov_id']} {row['name']} {row['state']} "
                f"tier={row['tier']} verdict={result['handread_verdict']} "
                f"decorative_url={result['decorative_url_signature']} "
                f"decorative_name={result['decorative_filename']} "
                f"meeting_ctx={result['meeting_context_found']}"
            )


if __name__ == "__main__":
    asyncio.run(main())
