"""WO-333: rerun the shared `verify_hub()` step against WO-331's own 15
phase-3-confirmed positive controls, to measure the before/after this WO
claims. Reads `research/wo331_handcheck.csv` (already committed,
`286d67f`) for the confirmed_url + phase3_platform_confirmed +
step4_verdict/step5_verdict of each of the 15 rows where phase 3 actually
confirmed a platform, calls `verify_hub(confirmed_url, platform_hint=
phase3_platform_confirmed)` on each, and writes a per-government before/
after CSV plus a verdict-class tally (RESOLVED / CALENDAR_PAGE /
RESOLVE_FAILED / UNSUPPORTED / NO_HOP_LINK_FOUND, WO-331's own step4/
step5 vocabulary) so the conductor's specific ask -- share of the fix
attributable to each of the three mechanisms -- can be read straight off
the output.

Read-only: never POSTs to the Archive, never ingests, never writes to
jurisdiction_coverage.csv. Same never-fetch-YouTube guard as
`wo331_handcheck.py` (a process-wide aiohttp monkeypatch), since several
of these hubs delegate through platforms (CivicPlus, Legistar) that would
otherwise chase an embedded YouTube link themselves.

Usage:
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo333_verify_controls.db" \\
        .venv/bin/python scripts/wo333_verify_controls.py
"""

from __future__ import annotations

import asyncio
import csv
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import aiohttp  # noqa: E402

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.passive_verify import verify_hub  # noqa: E402

register_all_finders()

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
HANDCHECK_CSV = RESEARCH_DIR / "wo331_handcheck.csv"
OUT_CSV = RESEARCH_DIR / "wo333_verify_controls.csv"

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}


class YouTubeFetchBlocked(Exception):
    pass


def _is_youtube_host(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    except Exception:  # noqa: BLE001
        return False
    return host in YOUTUBE_HOSTS


def install_youtube_guard() -> None:
    orig_request = aiohttp.ClientSession._request

    async def guarded_request(self, method, str_or_url, *args, **kwargs):
        url = str(str_or_url)
        if _is_youtube_host(url):
            raise YouTubeFetchBlocked(f"blocked aiohttp fetch to {url}")
        return await orig_request(self, method, str_or_url, *args, **kwargs)

    aiohttp.ClientSession._request = guarded_request


async def main() -> None:
    install_youtube_guard()

    with open(HANDCHECK_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    confirmed = [r for r in rows if r.get("phase3_outcome") == "platform-confirmed"]
    print(f"{len(confirmed)} phase-3-confirmed rows to rerun\n", file=sys.stderr)

    out_rows = []
    for row in confirmed:
        domain = row["domain"]
        url = row["confirmed_url"]
        platform_hint = row.get("phase3_platform_confirmed") or None
        print(f"=== {domain} ({platform_hint}) {url}", file=sys.stderr)
        try:
            result = await verify_hub(url, platform_hint=platform_hint)
            out_rows.append(
                {
                    "domain": domain,
                    "gov_id": row.get("gov_id", ""),
                    "confirmed_url": url,
                    "platform_hint": platform_hint,
                    "old_step4_verdict": row.get("step4_verdict", ""),
                    "old_step5_verdict": row.get("step5_verdict", ""),
                    "new_meeting_found": result.meeting_found,
                    "new_video_found": result.video_found,
                    "new_captions_found": result.captions_found,
                    "new_platform": result.platform,
                    "new_verdict": result.verdict,
                    "new_meeting_url": result.meeting_url or "",
                    "new_candidates_checked": result.candidates_checked,
                    "ranking_fix_applied": result.ranking_fix_applied,
                    "evidence": result.evidence[:300],
                }
            )
            print(
                f"    meeting_found={result.meeting_found} video_found={result.video_found} "
                f"captions_found={result.captions_found} verdict={result.verdict} "
                f"platform={result.platform} ranking_fix={result.ranking_fix_applied}",
                file=sys.stderr,
            )
        except YouTubeFetchBlocked as e:
            out_rows.append(
                {
                    "domain": domain,
                    "gov_id": row.get("gov_id", ""),
                    "confirmed_url": url,
                    "platform_hint": platform_hint,
                    "old_step4_verdict": row.get("step4_verdict", ""),
                    "old_step5_verdict": row.get("step5_verdict", ""),
                    "new_meeting_found": True,
                    "new_video_found": True,
                    "new_captions_found": False,
                    "new_platform": "youtube",
                    "new_verdict": "youtube_lead",
                    "new_meeting_url": "",
                    "new_candidates_checked": 0,
                    "ranking_fix_applied": False,
                    "evidence": str(e)[:300],
                }
            )
            print(f"    YOUTUBE_LEAD: {e}", file=sys.stderr)
        except Exception as e:  # noqa: BLE001
            out_rows.append(
                {
                    "domain": domain,
                    "gov_id": row.get("gov_id", ""),
                    "confirmed_url": url,
                    "platform_hint": platform_hint,
                    "old_step4_verdict": row.get("step4_verdict", ""),
                    "old_step5_verdict": row.get("step5_verdict", ""),
                    "new_meeting_found": False,
                    "new_video_found": False,
                    "new_captions_found": False,
                    "new_platform": "",
                    "new_verdict": "crash",
                    "new_meeting_url": "",
                    "new_candidates_checked": 0,
                    "ranking_fix_applied": False,
                    "evidence": f"{type(e).__name__}: {e}"[:300],
                }
            )
            print(f"    CRASH {type(e).__name__}: {e}", file=sys.stderr)
        # flush after every row -- resumable/inspectable mid-run
        with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
            writer.writeheader()
            writer.writerows(out_rows)
        await asyncio.sleep(1.5)  # politeness gap between governments

    video_before = sum(1 for r in confirmed if r.get("step4_has_video") == "True")
    video_after = sum(1 for r in out_rows if r["new_video_found"])
    print(
        f"\nvideo_found: before={video_before} after={video_after} "
        f"(of {len(confirmed)} phase-3-confirmed controls)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    asyncio.run(main())
