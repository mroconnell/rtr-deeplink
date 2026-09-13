#!/usr/bin/env python3
"""WO-337, verification step: calls the shared `verify_hub()`
(`app/platforms/passive_verify.py`, WO-333) on every phase-3
platform-confirmed candidate from `research/wo337_report.csv`, in place
of the older per-WO `wo3NN_resolve_diagnostic.py` hand-build-a-
classification-file step. This is the addendum's required change for
WO-337/WO-338: "the hand-check step is `verify_hub()`, not a bare
`resolve()` on the hub."

Only rows with `outcome == "platform-confirmed"` AND
`shared_domain_primary == "True"` are eligible -- a `shared-domain-not-
verified` row (a government whose `domain` is shared with another
government and wasn't the one phase 1 actually fetched, see
`wo337_build_report.py`'s own docstring) has no fetched evidence of its
own and is left for a human/later pass, never guessed at here.

For every result with `video_found=True` and `platform != "youtube"`
(tiers 1/3), this script makes ONE further direct `resolve()` call on
`result.meeting_url` (through the real `app/platforms/*` `resolve()`
pipeline, same one `bulk_ingest.py` uses) purely to recover the
meeting's own title/agenda text for the hand-read gate -- `VerifyResult`
itself carries no title field by design (module docstring: "the three
separable facts a sweep actually needs"). Guarded by the exact same
never-fetch-YouTube pattern as `verify_hub()` uses internally
(`app.platforms.passive_verify` already refuses to fetch a youtube.com/
youtu.be host; this script never even attempts the extra call when
`result.platform == "youtube"`).

Emits Ryan's tier vocabulary (2026-09-13, `VerifyResult.tier`) per
government:
  tier 1 -- video + real fetchable captions -> page, now
  tier 2 -- video with YouTube-only captions -> drip lead, never fetched
  tier 3 -- video, no fetchable captions -> tier-3 queue candidate
  tier 4 -- meeting found, no video -> meeting-without-video, recorded
  (none) -- no meeting found at all -> a §23 reject reason

Read-only: never POSTs to the Archive, never ingests, never writes to
jurisdiction_coverage.csv or the tier-3 queue. Those steps come after
this script's output is hand-read (the hand-check GATE stays on every
tier 1-3 candidate, per the brief -- this script produces what gets
hand-read, it does not replace the reading).

Usage:
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo337_verify_scratch.db" \\
        .venv/bin/python scripts/wo337_verify.py
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

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
REPORT_CSV = RESEARCH_DIR / "wo337_report.csv"
VERIFY_CSV = RESEARCH_DIR / "wo337_verify.csv"

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
}

# §23 taxonomy mapping for a verify_hub() verdict where no meeting was
# found at all (meeting_found=False) -- these are all "checked a
# confirmed platform and found nothing to hand-read", the closest fit is
# no-meeting-nor-video (the hub lists nothing) except fetch_failed,
# which is access-class.
NO_MEETING_REASON = "no-meeting-nor-video"
FETCH_FAILED_REASON = "timeout"


def _is_youtube_host(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    except Exception:  # noqa: BLE001
        return False
    return host in YOUTUBE_HOSTS


async def fetch_title_for_handread(meeting_url: str) -> dict:
    """One extra direct resolve() call, title/agenda only, for the
    hand-read gate. Never called on a youtube.com/youtu.be URL directly
    (checked below), and wrapped in the exact same `_youtube_resolve_
    guard()` `verify_hub()` itself uses internally, so a delegating
    adapter (municode_meetings/primegov/civicweb/the Chicago ELMS path)
    that reaches YouTube mid-resolve() is caught here too -- this is
    precisely the gap `BACKLOG.md`'s open `wo325_resolve_diagnostic.py`
    entry describes (a hand-check step calling real resolve() with no
    guard against an adapter's own legitimate YouTube delegation); this
    script closes it by reusing `verify_hub()`'s own guard rather than
    re-solving it."""
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
    with open(REPORT_CSV, newline="", encoding="utf-8") as f:
        report_rows = list(csv.DictReader(f))

    eligible = [
        r
        for r in report_rows
        if r.get("outcome") == "platform-confirmed"
        and r.get("shared_domain_primary") in ("True", "true", True)
    ]
    print(
        f"{len(eligible)} platform-confirmed, shared-domain-primary rows to verify",
        file=sys.stderr,
    )

    out_rows = []
    for i, row in enumerate(eligible, 1):
        domain = row["domain"]
        gov_id = row.get("gov_id", "")
        name = row.get("name", "")
        state = row.get("state", "")
        best_url = row.get("best_url", "")
        platform_hint = row.get("platform_confirmed") or row.get("platform") or None

        print(
            f"\n=== [{i}/{len(eligible)}] {domain} ({name}, {state}) hint={platform_hint}",
            file=sys.stderr,
        )
        print(f"    hub_url={best_url}", file=sys.stderr)

        result = await verify_hub(best_url, platform_hint=platform_hint)
        rec = {
            "domain": domain,
            "gov_id": gov_id,
            "name": name,
            "state": state,
            "population": row.get("population", ""),
            "phase3_platform_hint": platform_hint or "",
            "hub_url": best_url,
            "verdict": result.verdict,
            "tier": result.tier if result.tier is not None else "",
            "meeting_found": result.meeting_found,
            "video_found": result.video_found,
            "captions_found": result.captions_found,
            "meeting_url": result.meeting_url or "",
            "resolved_platform": result.platform or "",
            "candidates_checked": result.candidates_checked,
            "ranking_fix_applied": result.ranking_fix_applied,
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
        "domain",
        "gov_id",
        "name",
        "state",
        "population",
        "phase3_platform_hint",
        "hub_url",
        "verdict",
        "tier",
        "meeting_found",
        "video_found",
        "captions_found",
        "meeting_url",
        "resolved_platform",
        "candidates_checked",
        "ranking_fix_applied",
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
