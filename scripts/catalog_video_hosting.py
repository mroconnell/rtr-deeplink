"""One-off: for a list of "zero transcript" meeting URLs (already resolved
once by bulk_ingest.py --dry-run and found to have no segments/agenda_items/
agenda_link), re-resolve each directly and record the real video_url/
video_format/platform/video_link fields precisely.

Why this exists rather than trusting bulk_ingest.py's printed "platform=X"
text: for a delegating platform (primegov/civicweb/clerkshq -> youtube),
"platform=X" where X differs from the source platform IS a reliable
"video found on X, just no captions" signal. But escribe hosts its own
video/captions natively (no delegation), so "platform=escribe, empty"
is ambiguous -- it could mean "no video at all" or "video exists on
escribe's native player, just no captions found". This script resolves
that ambiguity by reading result.video_url/video_format directly instead
of inferring from which platform string came back.

Usage:
    python scripts/catalog_video_hosting.py urls.txt > catalog.csv
"""

import asyncio
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.base import (
    detect_platform,
    get_finder,
    UnsupportedPlatformError,
    CalendarPageError,
)  # noqa: E402

REQUEST_DELAY_SECONDS = 1.5


async def main():
    urls_file = sys.argv[1]
    urls = [
        line.strip()
        for line in Path(urls_file).read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]

    register_all_finders()

    w = csv.writer(sys.stdout)
    w.writerow(
        [
            "url",
            "resolved_platform",
            "video_url",
            "video_format",
            "is_youtube",
            "video_link",
            "video_link_recognized",
            "resolve_error",
        ]
    )

    for i, url in enumerate(urls):
        try:
            platform = detect_platform(url)
            finder = get_finder(platform)
            result = await finder.resolve(url)
            w.writerow(
                [
                    url,
                    result.platform,
                    result.video_url or "",
                    result.video_format or "",
                    result.video_format == "youtube"
                    or (result.video_url or "").startswith(
                        ("https://www.youtube.com", "https://youtube.com")
                    ),
                    result.video_link or "",
                    result.video_link_recognized,
                    "",
                ]
            )
        except (UnsupportedPlatformError, CalendarPageError) as e:
            w.writerow([url, "", "", "", False, "", False, str(e)])
        except Exception as e:
            w.writerow([url, "", "", "", False, "", False, f"{type(e).__name__}: {e}"])

        sys.stdout.flush()
        if i < len(urls) - 1:
            await asyncio.sleep(REQUEST_DELAY_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
