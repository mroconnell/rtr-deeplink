"""WO-360, part A step 3: passive v2 with `verify_hub()`'s deeper-walk
option (`deep_walk=True`, WO-355/PR #1145) on the 20-government
population (`research/wo360_population.csv`) -- the 2 WV place rows
`wo360_apply_to_jc.py` just filled a real domain for, and the 18 WV
counties the conductor's earlier WV pass re-keyed to a real `wv.gov`-
sourced domain. None of these 20 rows carry a phase-1/2/3 hop already
(they've never been through the WO-283-style pipeline), so this script
calls `verify_hub()` directly against `https://{domain}` -- exactly the
"bare homepage, unknown platform" path `verify_hub()` already handles
itself (fetch once, look for the real embedded/linked vendor, WO-331/
WO-352's fix), the same shape WO-355 used for its own 518-row population
with no separate phase 1-3 script.

Same shape as `wo337_verify.py`: one direct `resolve()` call for the
hand-read gate's title on every tier 1/3 hit, `_youtube_resolve_guard()`
throughout (never fetches a youtube.com/youtu.be URL), 1.5s pause
between governments.

Usage (from the rtr-deeplink repo root, shared venv):
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo360_verify_scratch.db" \\
        .venv/bin/python scripts/wo360_verify.py

Writes `research/wo360_verify.csv`.
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

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import (  # noqa: E402
    CalendarPageError,
    UnsupportedPlatformError,
    detect_platform,
    get_finder,
)
from app.platforms.passive_verify import (  # noqa: E402
    _YouTubeResolveBlocked,
    _youtube_resolve_guard,
    verify_hub,
)

register_all_finders()

RESEARCH_DIR = Path("/Users/mroconnell/Documents/rtr-business/research")
POPULATION_CSV = RESEARCH_DIR / "wo360_population.csv"
VERIFY_CSV = RESEARCH_DIR / "wo360_verify.csv"

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}

NO_MEETING_REASON = "no-meeting-nor-video"
FETCH_FAILED_REASON = "timeout"


def _is_youtube_host(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    except Exception:  # noqa: BLE001
        return False
    return host in YOUTUBE_HOSTS


async def fetch_title_for_handread(meeting_url: str) -> dict:
    if _is_youtube_host(meeting_url):
        return {"title": "", "detail": "youtube host -- not fetched"}
    try:
        platform = detect_platform(meeting_url)
        finder = get_finder(platform)
    except UnsupportedPlatformError as e:
        return {"title": "", "detail": f"UNSUPPORTED: {e}"}
    except Exception as e:  # noqa: BLE001
        return {"title": "", "detail": f"DETECT_FAILED: {type(e).__name__}: {e}"}
    try:
        with _youtube_resolve_guard():
            result = await finder.resolve(meeting_url)
    except _YouTubeResolveBlocked as e:
        return {"title": "", "detail": f"YOUTUBE_LEAD (delegated mid-resolve): {e}"}
    except CalendarPageError as e:
        return {"title": "", "detail": f"CALENDAR_PAGE: {str(e)[:200]}"}
    except Exception as e:  # noqa: BLE001
        return {
            "title": "",
            "detail": f"RESOLVE_FAILED: {type(e).__name__}: {str(e)[:200]}",
        }
    return {
        "title": result.title or "",
        "detail": (
            f"segments={len(result.segments or [])} "
            f"agenda_items={len(result.agenda_items or [])} "
            f"source_url={result.source_url!r}"
        ),
    }


def reject_reason_for(result) -> str:
    if result.verdict == "fetch_failed":
        return FETCH_FAILED_REASON
    return NO_MEETING_REASON


async def main() -> None:
    with open(POPULATION_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    print(f"{len(rows)} governments to verify (deep_walk=True)", file=sys.stderr)

    out_rows = []
    for i, row in enumerate(rows, 1):
        gov_id = row["gov_id"]
        name = row["name"]
        state = row["state"]
        hub_url = row["hub_url"]

        print(f"\n=== [{i}/{len(rows)}] {gov_id} {name}, {state}", file=sys.stderr)
        print(f"    hub_url={hub_url}", file=sys.stderr)

        try:
            result = await asyncio.wait_for(
                verify_hub(hub_url, name=name, state=state, deep_walk=True),
                timeout=45,
            )
        except asyncio.TimeoutError:
            rec = {
                "gov_id": gov_id,
                "name": name,
                "state": state,
                "domain": row["domain"],
                "hub_url": hub_url,
                "verdict": "timeout",
                "tier": "",
                "meeting_found": False,
                "video_found": False,
                "captions_found": False,
                "meeting_url": "",
                "resolved_platform": "",
                "candidates_checked": "",
                "evidence": "45s hard timeout",
                "handread_title": "",
                "handread_detail": "",
                "reject_reason": "timeout",
            }
            out_rows.append(rec)
            print("    TIMEOUT", file=sys.stderr)
            await asyncio.sleep(1.5)
            continue

        rec = {
            "gov_id": gov_id,
            "name": name,
            "state": state,
            "domain": row["domain"],
            "hub_url": hub_url,
            "verdict": result.verdict,
            "tier": result.tier if result.tier is not None else "",
            "meeting_found": result.meeting_found,
            "video_found": result.video_found,
            "captions_found": result.captions_found,
            "meeting_url": result.meeting_url or "",
            "resolved_platform": result.platform or "",
            "candidates_checked": result.candidates_checked,
            "evidence": (result.evidence or "")[:400],
            "handread_title": "",
            "handread_detail": "",
            "reject_reason": "",
        }
        print(
            f"    verify_hub -> verdict={result.verdict} tier={result.tier} "
            f"meeting_found={result.meeting_found} video_found={result.video_found} "
            f"captions_found={result.captions_found} platform={result.platform}",
            file=sys.stderr,
        )

        if result.tier in (1, 3) and result.meeting_url:
            title_info = await fetch_title_for_handread(result.meeting_url)
            rec["handread_title"] = title_info["title"]
            rec["handread_detail"] = title_info["detail"]
            print(
                f"    handread title={title_info['title']!r} detail={title_info['detail']}",
                file=sys.stderr,
            )
        elif result.tier == 4:
            rec["reject_reason"] = "meeting-without-video"
        elif result.tier is None:
            rec["reject_reason"] = reject_reason_for(result)

        out_rows.append(rec)
        await asyncio.sleep(1.5)

    fieldnames = [
        "gov_id",
        "name",
        "state",
        "domain",
        "hub_url",
        "verdict",
        "tier",
        "meeting_found",
        "video_found",
        "captions_found",
        "meeting_url",
        "resolved_platform",
        "candidates_checked",
        "evidence",
        "handread_title",
        "handread_detail",
        "reject_reason",
    ]
    with open(VERIFY_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, lineterminator="\n")
        w.writeheader()
        w.writerows(out_rows)
    print(f"\nwrote {VERIFY_CSV} ({len(out_rows)} rows)", file=sys.stderr)

    from collections import Counter

    print("tier split:", Counter(r["tier"] for r in out_rows), file=sys.stderr)
    print("verdict split:", Counter(r["verdict"] for r in out_rows), file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
