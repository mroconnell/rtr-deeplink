"""WO-283 scratch diagnostic (not part of the shipped pipeline): calls
the real resolve() pipeline (same as bulk_ingest.py --dry-run) on each
confirmed candidate and prints video_url/segments/agenda_items/agenda_link
explicitly, since bulk_ingest.py's own dry-run message omits video_url --
needed to see which candidates are genuinely video-bearing before the
hand-read gate. Read-only: never POSTs to the Archive.
"""

import asyncio
import os
import sys
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import (
    detect_platform,
    get_finder,
    UnsupportedPlatformError,
    CalendarPageError,
)  # noqa: E402

register_all_finders()


async def main():
    lines_path = sys.argv[1]
    with open(lines_path, encoding="utf-8") as f:
        rows = [ln.rstrip("\n").split("|") for ln in f if ln.strip()]

    for dom, gov_id, name, state, plat, url in rows:
        try:
            platform = detect_platform(url)
            finder = get_finder(platform)
        except UnsupportedPlatformError as e:
            print(f"UNSUPPORTED|{dom}|{gov_id}|{name}|{state}|{url}|{e}")
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
