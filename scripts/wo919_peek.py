#!/usr/bin/env python3
"""WO-919 helper: resolve one or more meeting URLs with the repo's own
adapters and print what a hand-reader needs (title, date, video url, caption
count, meeting_body, jurisdiction, warnings). Read-only; never downloads media;
never fetches YouTube (the resolve guard used by verify_hub is applied).

    DATABASE_URL="sqlite+aiosqlite:////tmp/wo919_scratch.db" \\
        .venv/bin/python scripts/wo919_peek.py URL [URL ...]
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import detect_platform, get_finder  # noqa: E402
from app.platforms.passive_verify import _youtube_resolve_guard  # noqa: E402

register_all_finders()


async def peek(url: str) -> None:
    platform = detect_platform(url)
    print(f"== {url}\n   platform={platform}")
    try:
        with _youtube_resolve_guard():
            res = await get_finder(platform).resolve(url)
    except Exception as e:  # noqa: BLE001
        print(f"   ERROR {type(e).__name__}: {str(e)[:200]}")
        return
    segs = res.segments or []
    dur = segs[-1].end if segs else None
    print(f"   title={res.title!r} date={res.date!r}")
    print(f"   jurisdiction={res.jurisdiction!r} meeting_body={getattr(res, 'meeting_body', None)!r}")
    print(f"   video_url={res.video_url!r}")
    print(f"   segments={len(segs)} last_end_s={dur} agenda_items={len(res.agenda_items or [])}")
    for w in (res.transcript_warnings or [])[:3]:
        print(f"   warning: {w[:160]}")
    if segs:
        print(f"   first_text={segs[0].text[:120]!r}")


async def main() -> None:
    for u in sys.argv[1:]:
        await peek(u)
        await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
