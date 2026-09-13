"""WO-324 scratch diagnostic (not part of the shipped pipeline): calls
the real resolve() pipeline (same as bulk_ingest.py --dry-run) on each
confirmed candidate and prints video_url/segments/agenda_items/agenda_link
explicitly, since bulk_ingest.py's own dry-run message omits video_url --
needed to see which candidates are genuinely video-bearing before the
hand-read gate. Read-only: never POSTs to the Archive.

Conductor instruction, mid-run (2026-09-12): WO-323's own verification
step called resolve() on a Tweed ON page and that fetched real YouTube
captions once, through a plain embed -- an absolute rule violation
("never fetch a youtube.com/youtu.be URL for any reason") that happened
because resolve() itself, once it decides a page's video comes from a
YouTube embed, calls out to YouTube to build segments/metadata. This
script pre-screens the candidate page's own HTML (one honest plain GET,
the same fetch resolve() would otherwise make) for a youtube.com/youtu.be
link BEFORE calling finder.resolve() at all. If the page's only video
signal is a YouTube embed, resolve() is never called for it -- it is
recorded as a YouTube lead instead (this WO's own
`record_youtube_lead()` from wo324_targeted.py) and skipped.
"""

import asyncio
import os
import re
import sys
from pathlib import Path

import certifi
import requests

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import (
    detect_platform,
    get_finder,
    UnsupportedPlatformError,
    CalendarPageError,
)  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wo324_targeted import record_youtube_lead  # noqa: E402

register_all_finders()

YOUTUBE_EMBED_RE = re.compile(r"(?:youtube\.com/(?:embed|watch|v)|youtu\.be/)", re.I)
HONEST_HEADERS = {
    "User-Agent": "RedTapeRecordings/1.0 (+https://redtaperecordings.com)"
}


def page_only_video_is_youtube_embed(url: str) -> bool:
    """One honest plain GET of the candidate page (never of a
    youtube.com/youtu.be URL itself) -- True if the page's own HTML
    contains a youtube.com/youtu.be embed/link. A false result (no
    match, or the fetch itself failed) means "not detected as
    YouTube-only" -- resolve() proceeds normally, exactly as it would
    have without this guard."""
    try:
        resp = requests.get(url, headers=HONEST_HEADERS, timeout=15)
        if resp.status_code != 200 or not resp.text:
            return False
        return bool(YOUTUBE_EMBED_RE.search(resp.text))
    except Exception:  # noqa: BLE001
        return False


async def main():
    lines_path = sys.argv[1]
    with open(lines_path, encoding="utf-8") as f:
        rows = [ln.rstrip("\n").split("|") for ln in f if ln.strip()]

    for dom, gov_id, name, state, plat, url in rows:
        if not url:
            print(f"NO_URL|{dom}|{gov_id}|{name}|{state}|{plat}|")
            continue
        try:
            platform = detect_platform(url)
            finder = get_finder(platform)
        except UnsupportedPlatformError as e:
            print(f"UNSUPPORTED|{dom}|{gov_id}|{name}|{state}|{url}|{e}")
            await asyncio.sleep(1.5)
            continue
        if page_only_video_is_youtube_embed(url):
            record_youtube_lead(
                url,
                gov_id,
                name,
                state,
                note="WO-324 resolve-diagnostic pre-screen: page embeds a "
                "youtube.com/youtu.be video; resolve() skipped per the "
                "no-YouTube-fetch rule",
            )
            print(f"YOUTUBE_EMBED_SKIPPED|{dom}|{gov_id}|{name}|{state}|{url}")
            await asyncio.sleep(1.5)
            continue
        try:
            result = await finder.resolve(url)
        except CalendarPageError as e:
            print(f"CALENDAR_PAGE|{dom}|{gov_id}|{name}|{state}|{url}|{e}")
            await asyncio.sleep(1.5)
            continue
        except Exception as e:  # noqa: BLE001
            print(
                f"RESOLVE_FAILED|{dom}|{gov_id}|{name}|{state}|{url}|{type(e).__name__}: {str(e)[:200]}"
            )
            await asyncio.sleep(1.5)
            continue

        has_segments = len(result.segments or [])
        has_agenda_items = len(result.agenda_items or [])
        has_agenda_link = bool(result.agenda_link)
        print(
            f"RESOLVED|{dom}|{gov_id}|{name}|{state}|{result.platform}|"
            f"title={result.title!r}|video_url={result.video_url!r}|"
            f"segments={has_segments}|agenda_items={has_agenda_items}|"
            f"agenda_link={has_agenda_link}|source_url={result.source_url!r}"
        )
        await asyncio.sleep(1.5)


if __name__ == "__main__":
    asyncio.run(main())
