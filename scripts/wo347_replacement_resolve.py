import asyncio
import os
import sys
import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.platforms import register_all_finders
from app.platforms.base import detect_platform, get_finder

register_all_finders()

URLS = [
    "https://pub-chocolatetown.escribemeetings.com/Meeting.aspx?Id=2fd2d858-d945-43a6-a5d8-cd21d7e1b890",
    "https://pub-llbc.escribemeetings.com/Meeting.aspx?Id=d65f3cd3-1982-42b7-b26c-9ffc58820dad",
    "https://townhallstreams.com/stream.php?location_id=144&id=75561",
    "https://townhallstreams.com/stream.php?location_id=107&id=73429",
]


async def main():
    for url in URLS:
        platform = detect_platform(url)
        finder = get_finder(platform)
        result = await finder.resolve(url)
        print(url)
        print(
            "  title:",
            result.title,
            "| jurisdiction:",
            result.jurisdiction,
            "| date:",
            result.date,
        )
        print("  video_url:", result.video_url)


asyncio.run(main())
