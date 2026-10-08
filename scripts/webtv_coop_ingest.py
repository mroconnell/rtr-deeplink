"""Walk Coop WebTV (webtv.coop) government channels and route each video.

Ryan, 2026-10-07: "ingest tier 1s and route tier 2 and 3 appropriately."

For every video on a pinned government channel this script resolves the
channel-shaped address with `WebtvCoopAssetFinder` and then:

* Tier 1 -- the video has a caption file the server can fetch: ingest it
  into the Archive (the same `bulk_ingest._ingest()` every ingest wrapper
  uses, with its duration/dead-link probe), sending the channel's `gov_id`.
* Tier 3 -- video but no caption file: append a line to the tier-3
  queue (`queue_probe.append_queue_line()`, which carries the `gov_id`),
  so our own transcription picks it up. A video under 8 minutes is never
  queued (Ryan's rule: under 8 minutes is never a meeting).
* Tier 2 (captions only a local run can read) does not exist on this host:
  the caption file is a plain fetch.

The listing is the page's own box-list call (a GET with
`X-Requested-With: XMLHttpRequest`; without that header the server
answers page 1 for every page -- found by the rtr-discovery walker,
2026-10-07). One request at a time, 3 seconds apart, stop on 429. No
YouTube request is made (`youtube_fetch_guard.install()`).

Resumable: every result goes to a ledger CSV and a video already in it is
skipped. Needs ARCHIVE_BASE_URL and ARCHIVE_INGEST_TOKEN from `.env` for
a real run; `--dry-run` resolves and reports without ingesting or queueing.

    python scripts/webtv_coop_ingest.py --ledger LEDGER.csv --channel 4 --limit 5 --dry-run
    python scripts/webtv_coop_ingest.py --ledger LEDGER.csv --channel 4 --channel 18
"""

import argparse
import asyncio
import csv
import html as html_lib
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Tuple
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import bulk_ingest  # noqa: E402  (sets SSL_CERT_FILE first, loads .env)
import youtube_fetch_guard  # noqa: E402

import aiohttp  # noqa: E402

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.queue_probe import append_queue_line  # noqa: E402
from app.platforms.webtv_coop import WebtvCoopAssetFinder  # noqa: E402
from app.utils.url_normalize import normalize_url  # noqa: E402

HOST = "https://webtv.coop"
PAUSE_SECONDS = 3.0
MIN_MEETING_SECONDS = 8 * 60
USER_AGENT = "RedTapeRecordings/1.0 (+https://redtaperecordings.com)"

# Channel number -> gov_id, exactly the pins in tenant_overrides.csv
# (each checked against the government's own site, 2026-10-07). Channel 10
# is left out until its minted row is deployed (PR "Pin webtv.coop
# channels 6, 7 and 10").
CHANNEL_GOV_IDS: Dict[str, str] = {
    "1": "ca:csd:2466107",  # Beaconsfield
    "3": "ca:csd:2466112",  # Baie-D'Urfe
    "4": "ca:csd:2466097",  # Pointe-Claire
    "5": "ca:csd:2466007",  # Montreal-Est
    "6": "ca:csd:2466023",  # Saint-Laurent borough, filed under Montreal
    "7": "ca:csd:2466023",  # Sud-Ouest borough, filed under Montreal
    "18": "ca:csd:2466117",  # Sainte-Anne-de-Bellevue
    "10": "rtr:ca:qc:english-montreal-school-board",  # needs the deploy
}

_ITEM_RE = re.compile(
    r'<a href="(?P<href>/channel/video/[^"]+/(?P<key>[0-9a-f]{32})/(?P<channel>\d+))"'
    r'[^>]*?\bname="(?P<title>[^"]*)"',
    re.IGNORECASE,
)
_DATE_RE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})")


def _box_list_fields(channel: str) -> List[Tuple[str, str]]:
    """The page's own `box-list` settings (channel 4 page, 2026-10-07) as
    form fields; the same set the rtr-discovery walker sends."""
    settings = {
        "act": "boxList",
        "mod": "media",
        "mode": "channel",
        "context": "3",
        "context_id": channel,
        "show_filter": "true",
        "filter": "all",
        "show_limit": "true",
        "limit": "all",
        "show_type": "true",
        "type_id": "",
        "type": "videos",
        "show_layout": "true",
        "layout": "thumb",
        "show_search": "false",
        "search": "",
        "show_pager": "true",
        "pager_mode": "loading",
        "page_name": "page",
        "page_only": "false",
        "show_more": "false",
        "more_link": "media/list",
        "show_upload": "false",
        "show_header": "true",
        "show_empty_box": "true",
        "save_page": "true",
        "thumbsize": "160x120",
        "categoryFilter": "0",
        "show_categories": "false",
        "channel": channel,
        "id": f"channel-media-box-{channel}",
        "caption": "Média",
        "page": "1",
        "component": "boxList",
        "text": "",
        "filterHidden": "true",
        "layoutHidden": "true",
        "isMobile": "true",
        "mobile": "true",
    }
    fields = [(f"vars[{k}]", v) for k, v in settings.items()]
    fields += [
        ("vars[per_page][thumbBig]", "9"),
        ("vars[per_page][thumb]", "15"),
        ("vars[per_page][list]", "3"),
    ]
    return fields


def listing_url(channel: str, page: int) -> str:
    query = urlencode(
        [("page", str(page)), ("page_only", "1")] + _box_list_fields(channel)
    )
    return (
        f"{HOST}/media/ajax/component/boxList/title/channel/channel/{channel}?{query}"
    )


class RateLimited(Exception):
    pass


async def list_channel(session: aiohttp.ClientSession, channel: str) -> List[dict]:
    """Every video on a channel, newest first."""
    videos: List[dict] = []
    seen = set()
    for page in range(1, 101):
        await asyncio.sleep(PAUSE_SECONDS)
        async with session.get(
            listing_url(channel, page),
            headers={"X-Requested-With": "XMLHttpRequest"},
            timeout=aiohttp.ClientTimeout(total=40),
        ) as response:
            if response.status == 429:
                raise RateLimited(f"429 listing channel {channel} page {page}")
            if response.status != 200:
                raise RuntimeError(
                    f"HTTP {response.status} listing channel {channel} page {page}"
                )
            body = await response.text()
        fresh = 0
        for m in _ITEM_RE.finditer(body):
            if m["key"] in seen:
                continue
            seen.add(m["key"])
            fresh += 1
            videos.append(
                {
                    "url": HOST + m["href"],
                    "key": m["key"],
                    "channel": m["channel"],
                    "title": html_lib.unescape(m["title"]).replace("\xa0", " ").strip(),
                }
            )
        if not fresh or not re.search(r'data-page="\d+"', body):
            break
    return videos


def _load_done(path: Path) -> set:
    if not path.exists():
        return set()
    with path.open(encoding="utf-8", newline="") as fh:
        return {row["key"] for row in csv.DictReader(fh)}


def _record(path: Path, row: dict) -> None:
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=[
                "key",
                "channel",
                "url",
                "date",
                "title",
                "route",
                "segments",
                "duration_seconds",
                "detail",
            ],
            lineterminator="\n",
        )
        if new:
            w.writeheader()
        w.writerow(row)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--ledger", required=True, type=Path)
    parser.add_argument("--channel", action="append", required=True)
    parser.add_argument("--limit", type=int, default=0, help="stop after N videos")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    youtube_fetch_guard.install()
    register_all_finders()
    for channel in args.channel:
        if channel not in CHANNEL_GOV_IDS:
            sys.exit(f"channel {channel} has no pin in CHANNEL_GOV_IDS")
    if not args.dry_run and not (
        bulk_ingest._base_url() and bulk_ingest._headers().get("Authorization")
    ):
        sys.exit("ARCHIVE_BASE_URL / ARCHIVE_INGEST_TOKEN are not set (.env).")

    done = _load_done(args.ledger)
    finder = WebtvCoopAssetFinder()
    counts: Dict[str, int] = {}
    handled = 0
    async with aiohttp.ClientSession(headers={"User-Agent": USER_AGENT}) as session:
        for channel in args.channel:
            gov_id = CHANNEL_GOV_IDS[channel]
            videos = await list_channel(session, channel)
            print(f"channel {channel}: {len(videos)} videos listed", flush=True)
            for video in videos:
                if video["key"] in done:
                    continue
                if args.limit and handled >= args.limit:
                    break
                handled += 1
                date_match = _DATE_RE.match(video["title"])
                date = date_match.group(1) if date_match else ""
                row = {
                    "key": video["key"],
                    "channel": channel,
                    "url": video["url"],
                    "date": date,
                    "title": video["title"],
                    "route": "",
                    "segments": 0,
                    "duration_seconds": "",
                    "detail": "",
                }
                await asyncio.sleep(PAUSE_SECONDS)
                result = await finder.resolve(video["url"])
                if any("429" in w for w in result.video_warnings):
                    print("429 from webtv.coop: stopping.", flush=True)
                    return
                row["segments"] = len(result.segments)
                row["duration_seconds"] = result.video_duration_seconds or ""
                if not result.video_url:
                    row["route"] = "no_video"
                    row["detail"] = "; ".join(result.video_warnings)
                elif result.segments:
                    row["route"] = "tier1_ingest"
                    if args.dry_run:
                        row["detail"] = "dry-run"
                    else:
                        payload = result.model_dump()
                        payload["gov_id"] = gov_id
                        try:
                            resp = await bulk_ingest._ingest(
                                session, payload, normalize_url(video["url"])
                            )
                            row["detail"] = (resp or {}).get("url") or "ingested"
                        except Exception as exc:  # gate reject or HTTP error
                            row["route"] = "tier1_not_ingested"
                            row["detail"] = str(exc)[:300]
                elif (result.video_duration_seconds or 0) < MIN_MEETING_SECONDS:
                    row["route"] = "skip_under_8_min"
                else:
                    row["route"] = "tier3_queue"
                    if args.dry_run:
                        row["detail"] = "dry-run"
                    else:
                        added = append_queue_line(
                            video["url"],
                            video["url"],
                            gov_id=gov_id,
                            title=result.title or video["title"],
                            date=date,
                        )
                        row["detail"] = "queued" if added else "already in queue"
                _record(args.ledger, row)
                counts[row["route"]] = counts.get(row["route"], 0) + 1
                print(
                    f"{time.strftime('%H:%M:%S')} ch{channel} {row['route']:<18} "
                    f"{row['date']} segs={row['segments']} {row['detail'][:80]}",
                    flush=True,
                )
    print("done:", counts, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
