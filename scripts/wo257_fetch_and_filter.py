"""One-off: fetch a fresh /internal/export/pages and save just the
YouTube pages with no stored video_channel, for WO-257's oEmbed lookup.
"""

import asyncio
import json
import os
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import aiohttp  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent
load_dotenv(REPO_ROOT / ".env")

BASE_URL = os.environ["ARCHIVE_BASE_URL"]
TOKEN = os.environ["ARCHIVE_INGEST_TOKEN"]


async def fetch_all():
    headers = {"Authorization": f"Bearer {TOKEN}"}
    url = f"{BASE_URL.rstrip('/')}/internal/export/pages"
    pages = []
    after_id = 0
    async with aiohttp.ClientSession() as session:
        while True:
            async with session.get(
                url,
                params={"after_id": after_id, "limit": 500},
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=180),
            ) as resp:
                if resp.status != 200:
                    raise SystemExit(f"GET {url} -> HTTP {resp.status}")
                body = await resp.json()
            pages.extend(body.get("pages") or [])
            print(f"  fetched {len(pages)} pages", end="\r", flush=True)
            after_id = body.get("next_after_id")
            if after_id is None:
                break
            await asyncio.sleep(0.5)
    print(f"  fetched {len(pages)} pages total")
    return pages


def is_youtube(page: dict) -> bool:
    if (page.get("platform") or "").lower() == "youtube":
        return True
    for f in ("source_url_normalized", "video_url"):
        v = (page.get(f) or "").lower()
        if "youtube.com" in v or "youtu.be" in v:
            return True
    return False


def main():
    pages = asyncio.run(fetch_all())
    total_youtube = [p for p in pages if is_youtube(p)]
    no_channel = [
        p for p in total_youtube if not (p.get("video_channel") or "").strip()
    ]
    print(f"total pages: {len(pages)}")
    print(f"youtube pages: {len(total_youtube)}")
    print(f"youtube pages with no video_channel: {len(no_channel)}")
    out_path = REPO_ROOT / "wo257_youtube_no_channel.json"
    out_path.write_text(json.dumps(no_channel), encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
