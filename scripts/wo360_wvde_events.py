"""WO-360, part B: fetch the West Virginia Board of Education's own
events-archive page (`https://wvde.us/events-archive?f[0]=event_type:17`,
government's own site, never youtube.com/youtu.be) and each linked event
page, to extract the YouTube live-video id each one names -- WITHOUT
ever fetching youtube.com/youtu.be itself, per the standing rule. Prints
one line per event: title, event page URL, extracted video id (or NONE).
"""

from __future__ import annotations

import re
import sys
from urllib.parse import urljoin

from bs4 import BeautifulSoup

sys.path.insert(0, "scripts")
import wo360_county_muni_walk as w  # noqa: E402

ARCHIVE_URL = "https://wvde.us/events-archive?f%5B0%5D=event_type%3A17"

YT_RE = re.compile(
    r"(?:youtube\.com/(?:live/|watch\?v=|embed/)|youtu\.be/)([A-Za-z0-9_-]{11})"
)


def extract_youtube_id(html: bytes) -> str:
    text = html.decode("utf-8", errors="replace")
    m = YT_RE.search(text)
    return m.group(1) if m else ""


def main():
    sc, body, final = w.bounded_get(ARCHIVE_URL)
    print(f"archive page: {sc} {len(body)} bytes {final}", file=sys.stderr)
    soup = BeautifulSoup(body, "html.parser")
    events = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = a.get_text(" ", strip=True)
        if "/events/" in href:
            abs_url = urljoin(final, href)
            if abs_url in seen:
                continue
            seen.add(abs_url)
            events.append((text, abs_url))

    print(f"{len(events)} events found on archive page", file=sys.stderr)

    for title, url in events:
        sc, body, final_ev = w.bounded_get(url)
        vid = extract_youtube_id(body) if body else ""
        print(f"{title}|{url}|{sc}|{vid}")


if __name__ == "__main__":
    main()
