"""WO-934: ask YouTube whether each video in a list still exists.

RUN THIS ON THE DRIP MAC ONLY. It makes one YouTube request per video, and
CLAUDE.md's rule is that YouTube is fetched only by the drip Mac
(`docs/YOUTUBE_DRIP_RUNBOOK.md`, rules 1 and 5). The office shares one
internet connection and YouTube blocks it after a few dozen requests, so this
script refuses to run without `--i-am-on-the-drip-mac`, waits between
requests, waits longer after any miss, and stops the moment YouTube says
"too many requests". Stop the drip (Ctrl-C) or run only its `captions,feed`
lanes while this runs, the same way the runbook says for the other one-off
sweeps.

What it answers. For each video it asks YouTube's public oEmbed lookup (the
one `reports/shared_host_lookups.csv` was built from) and records one
status. The codes are the ones the 2026-09-09 study read:

    HTTP 200  ok                the video exists and can be embedded
    HTTP 401  embedding_disabled  the owner switched off playback elsewhere
                                the video is ALIVE (captions may still be off)
    HTTP 403  private           the video is private or restricted
    HTTP 404  deleted           the video was removed, or never existed
    HTTP 400  malformed         YouTube does not read the id
    anything else  unknown      a network error or another code: not proof of
                                anything, and never used to delete a page

A video URL with no valid 11-character id is recorded `malformed` without a
request. `ok`, `embedding_disabled` and `unknown` are never grounds to delete.

The answer file (`--out`) has one line per video: `page_id`, `video_id`,
`status`, `checked_on` (UTC date), `http_status`, `note`. It is written one
line at a time, so stopping at any moment loses nothing, and running it again
skips every video already in the file. Hand the finished file back; then
`python scripts/repair_wrong_pages.py gone-videos POOL STATUS --out ROWS`
turns the gone ones into rows for Ryan to review. Nothing here writes to the
Archive.

Usage (drip Mac, repo root):
    .venv/bin/python scripts/check_youtube_video_status.py \\
        reports/wo934_youtube_no_transcript_pool.csv \\
        --out reports/wo934_youtube_video_status.csv \\
        --i-am-on-the-drip-mac
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import sys
import time
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.platforms.youtube_ids import extract_video_id  # noqa: E402
from scripts.repair_wrong_pages import STATUS_COLUMNS  # noqa: E402

OEMBED_URL = "https://www.youtube.com/oembed"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
DEFAULT_DELAY_SECONDS = 150.0  # WO-257 paced its 1,512 lookups at 2 to 3 minutes
MAX_DELAY_SECONDS = 600.0
# YouTube's own "slow down". Stop at once; do not wait and retry.
RATE_LIMITED = 429
STOP_AFTER_CONSECUTIVE_UNKNOWN = 3

_CODE_TO_STATUS = {
    200: ("ok", "oEmbed answered"),
    400: ("malformed", "oEmbed HTTP 400"),
    401: ("embedding_disabled", "oEmbed HTTP 401: playback on other sites is off"),
    403: ("private", "oEmbed HTTP 403"),
    404: ("deleted", "oEmbed HTTP 404"),
}


def classify_oembed(http_status: Optional[int]) -> Tuple[str, str]:
    """(status, note) for an oEmbed HTTP code. None means the request itself failed."""
    if http_status is None:
        return "unknown", "the request did not complete"
    if http_status in _CODE_TO_STATUS:
        return _CODE_TO_STATUS[http_status]
    return "unknown", f"oEmbed HTTP {http_status}"


def real_fetch(video_id: str) -> Optional[int]:
    """One oEmbed request. Returns the HTTP status, or None on a network error."""
    import httpx

    try:
        response = httpx.get(
            OEMBED_URL,
            params={
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "format": "json",
            },
            headers={"User-Agent": USER_AGENT},
            timeout=20.0,
        )
    except httpx.HTTPError:
        return None
    return response.status_code


def read_pool(path: Path) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def already_checked(path: Path) -> Set[str]:
    """Keys already answered in the output file, for resuming: a video id, or
    `page-<id>` for a page whose address held no readable id."""
    if not path.exists():
        return set()
    with open(path, newline="", encoding="utf-8") as fh:
        return {
            row.get("video_id") or f"page-{row.get('page_id')}"
            for row in csv.DictReader(fh)
        }


def check_pool(
    pool: Iterable[Dict[str, str]],
    out_path: Path,
    *,
    fetch: Callable[[str], Optional[int]] = real_fetch,
    sleep: Callable[[float], None] = time.sleep,
    today: Optional[dt.date] = None,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    limit: Optional[int] = None,
    recheck: bool = False,
    log: Callable[[str], None] = print,
) -> Dict[str, int]:
    """Check each pool video once and append the answer. Returns counts by status."""
    today = today or dt.datetime.now(dt.timezone.utc).date()
    done = set() if recheck else already_checked(out_path)
    new_file = not out_path.exists()
    counts: Dict[str, int] = {}
    consecutive_unknown = 0
    delay = delay_seconds
    requests_made = 0

    with open(out_path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=STATUS_COLUMNS)
        if new_file:
            writer.writeheader()
            fh.flush()
        for entry in pool:
            page_id = (entry.get("page_id") or "").strip()
            video_id = extract_video_id(entry.get("video_url") or "")
            if video_id is None:
                # No id YouTube could read: nothing to ask. Not a request.
                key = f"page-{page_id}"
                if key in done:
                    continue
                writer.writerow(
                    {
                        "page_id": page_id,
                        "video_id": "",
                        "status": "malformed",
                        "checked_on": today.isoformat(),
                        "http_status": "",
                        "note": "no valid 11-character video id in the page's video address",
                    }
                )
                fh.flush()
                counts["malformed"] = counts.get("malformed", 0) + 1
                done.add(key)
                continue
            if video_id in done:
                continue
            if limit is not None and requests_made >= limit:
                log(f"Stopped at --limit {limit}. Run again to continue.")
                break
            if requests_made:
                sleep(delay)
            http_status = fetch(video_id)
            requests_made += 1
            status, note = classify_oembed(http_status)
            writer.writerow(
                {
                    "page_id": page_id,
                    "video_id": video_id,
                    "status": status,
                    "checked_on": today.isoformat(),
                    "http_status": "" if http_status is None else http_status,
                    "note": note,
                }
            )
            fh.flush()
            done.add(video_id)
            counts[status] = counts.get(status, 0) + 1
            log(f"  [{requests_made}] page {page_id} video {video_id}: {status}")
            if http_status == RATE_LIMITED:
                log(
                    "YouTube said 'too many requests'. Stopping. Wait at least an hour."
                )
                break
            consecutive_unknown = consecutive_unknown + 1 if status == "unknown" else 0
            if consecutive_unknown >= STOP_AFTER_CONSECUTIVE_UNKNOWN:
                log(
                    "Three answers in a row were not clear. Stopping in case this is a block."
                )
                break
            # A miss looks the same whether it is one dead video or the
            # start of a block, so wait longer after any answer but "ok".
            delay = (
                delay_seconds
                if status == "ok"
                else min(delay_seconds * 2, MAX_DELAY_SECONDS)
            )
    return counts


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("pool", help="CSV with page_id and video_url columns")
    parser.add_argument("--out", required=True, help="the status file to append to")
    parser.add_argument(
        "--i-am-on-the-drip-mac",
        action="store_true",
        help="required: this script makes YouTube requests",
    )
    parser.add_argument("--delay-seconds", type=float, default=DEFAULT_DELAY_SECONDS)
    parser.add_argument(
        "--limit", type=int, default=None, help="most requests this run"
    )
    parser.add_argument(
        "--recheck", action="store_true", help="ask again about videos already in --out"
    )
    args = parser.parse_args(argv)

    if not args.i_am_on_the_drip_mac:
        print(
            "Refusing to run: this makes YouTube requests, and only the drip Mac may "
            "(CLAUDE.md, docs/YOUTUBE_DRIP_RUNBOOK.md). Add --i-am-on-the-drip-mac "
            "if this is that Mac.",
            file=sys.stderr,
        )
        return 1
    if args.delay_seconds < 60:
        print(
            "--delay-seconds under 60 is not allowed: keep the drip pacing.",
            file=sys.stderr,
        )
        return 1

    pool = read_pool(Path(args.pool))
    print(f"Pool: {len(pool)} pages. Answers go to {args.out}.")
    counts = check_pool(
        pool,
        Path(args.out),
        delay_seconds=args.delay_seconds,
        limit=args.limit,
        recheck=args.recheck,
    )
    print("\nResult | Count of videos checked this run")
    for status, n in sorted(counts.items()):
        print(f"{status} | {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
