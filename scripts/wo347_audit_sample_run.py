"""WO-347 Part B: hand-audit runner for the 60-government stratified
sample (research/wo347_audit_sample.csv). Reuses the exact access ladder
every sweep this week already uses (scripts/wo147_access_ladder_sweep.py's
run_access_ladder(): plain fetch -> browser headers (after a 403 or a
dropped connection) -> headless (Playwright), stopping at any human-
verification challenge -- never a youtube.com/youtu.be URL fetched
directly. Writes research/wo347_audit_sample.csv back in place, filling
hand_verdict/evidence_url/notes per row, plus a raw findings log for
manual review of the ambiguous ones.
"""

from __future__ import annotations

import asyncio
import csv
import os
import re
import sys
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import aiohttp  # noqa: E402

from wo147_access_ladder_sweep import (  # noqa: E402
    HONEST_HEADERS,
    find_hop_links,
    run_access_ladder,
)

RESEARCH = Path.home() / "Documents" / "rtr-business" / "research"
SAMPLE_CSV = RESEARCH / "wo347_audit_sample.csv"
RAW_LOG = RESEARCH / "wo347_audit_raw_findings.csv"

VIDEO_HINTS = re.compile(
    r"(youtube\.com/embed|youtube\.com/watch|youtu\.be/|vimeo\.com|\.m3u8|"
    r"granicus|swagit|civicclerk|escribemeetings|iqm2|townhallstreams|"
    r"boxcast|cablecast|viebit|wistia|telvue|castus|invintus|champds|"
    r"video_url|mediaplayer\.php|\.mp4)",
    re.IGNORECASE,
)


def scan_video_signal(html: str) -> str:
    if not html:
        return ""
    m = VIDEO_HINTS.search(html)
    return m.group(0) if m else ""


async def audit_one(session, row):
    domain = row["domain"]
    name = row["name"]
    state = row["state"]
    gov_id = row["gov_id"]

    result = await run_access_ladder(session, name, state, domain, f"https://{domain}")

    video_hit_on_home = scan_video_signal(result.final_html or "")
    hop_video_url = ""
    hop_hit_url = ""
    if result.hit_url:
        # A known platform link was found directly -- that itself is the
        # agenda/meeting page. Check the SAME html for a video hint too
        # (many CivicPlus/Granicus pages show a "Watch" link right there).
        hop_hit_url = result.hit_url
    elif result.final_html:
        # No known platform link -- score generic hop candidates the same
        # way every sweep does, and check the top one for a video signal.
        hop_links = find_hop_links(result.final_html, result.final_url, gov_id=gov_id)
        for link in hop_links[:3]:
            try:
                async with session.get(
                    link,
                    headers=HONEST_HEADERS,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    if resp.status != 200:
                        continue
                    html2 = await resp.text(errors="replace")
            except Exception:  # noqa: BLE001
                continue
            v = scan_video_signal(html2)
            if v or not hop_hit_url:
                hop_hit_url = link
            if v:
                hop_video_url = link
                break

    return {
        "gov_id": gov_id,
        "domain": domain,
        "access_mode": result.access_mode,
        "rung_answered": result.rung_answered,
        "home_url": result.home_url,
        "final_url": result.final_url,
        "platform_detected": result.platform or "",
        "hit_url": result.hit_url or "",
        "hop_candidate": hop_hit_url,
        "video_signal_on_home": video_hit_on_home,
        "hop_video_url": hop_video_url,
        "note": result.note,
    }


async def main():
    with open(SAMPLE_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    findings = []
    connector = aiohttp.TCPConnector(limit=10)
    async with aiohttp.ClientSession(connector=connector) as session:
        for i, row in enumerate(rows):
            try:
                f = await audit_one(session, row)
            except Exception as e:  # noqa: BLE001
                f = {
                    "gov_id": row["gov_id"],
                    "domain": row["domain"],
                    "access_mode": "error",
                    "rung_answered": "error",
                    "home_url": "",
                    "final_url": "",
                    "platform_detected": "",
                    "hit_url": "",
                    "hop_candidate": "",
                    "video_signal_on_home": "",
                    "hop_video_url": "",
                    "note": f"{type(e).__name__}: {e}",
                }
            findings.append(f)
            print(
                f"[{i + 1}/{len(rows)}] {row['domain']}: access={f['access_mode']} "
                f"platform={f['platform_detected']} hit={f['hit_url'][:60]} "
                f"hop={f['hop_candidate'][:60]} video_home={bool(f['video_signal_on_home'])} "
                f"hop_video={f['hop_video_url'][:60]}"
            )

    with open(RAW_LOG, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(findings[0].keys()))
        w.writeheader()
        w.writerows(findings)
    print(f"\nwrote {RAW_LOG}")


if __name__ == "__main__":
    asyncio.run(main())
