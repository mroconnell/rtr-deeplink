#!/usr/bin/env python3
"""WO-327: one polite hop past each of the 70 hand-labelled Quebec hub
URLs (wo327_quebec_hand_labels.csv), looking for a real meeting/video
link on the hub page itself -- the "one hop further" the brief asks
for. Plain HTTP only, honest headers (same HONEST_HEADERS constant
`wo147_access_ladder_sweep.py` uses), 2s between requests, one request
per government. NEVER fetches youtube.com/youtu.be (recorded as a
drip-lead href only, per CLAUDE.md's YouTube-as-drip-lead rule) and
never downloads a media file -- HTML only, discarded after link
extraction (no bytes saved to disk beyond a small gzip cache for
re-use).

Output: wo327_hub_links.csv (domain, gov_id, hub_url, fetch_status,
video_host, meeting_url, note).
"""

from __future__ import annotations

import csv
import gzip
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

HONEST_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-encoding": "gzip, deflate",
    "accept-language": "fr-CA,fr;q=0.9,en;q=0.8",
    "user-agent": (
        "rtr-upcoming/0.1 (Red Tape Recordings public-agenda reader; "
        "+https://redtaperecordings.com/about)"
    ),
}

RESEARCH_DIR = Path("~/Documents/rtr-business/research").expanduser()
IN_CSV = RESEARCH_DIR / "wo327_quebec_hand_labels.csv"
OUT_CSV = RESEARCH_DIR / "wo327_hub_links.csv"
CACHE_DIR = RESEARCH_DIR / "wo327_hub_cache"
CACHE_DIR.mkdir(exist_ok=True)

VIDEO_HOSTS = [
    "vimeo.com",
    "wistia.com",
    "wistia.net",
    "cablecast.tv",
    "telvue.com",
    "boxcast.tv",
    "castus.tv",
    "viebit.com",
    "townhallstreams.com",
    "diffusioncanal.com",
    "teams.microsoft.com",
]
# Never fetched -- recorded as a drip lead only, per CLAUDE.md.
YOUTUBE_HOSTS = ["youtube.com", "youtu.be"]


def main():
    with open(IN_CSV, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["homepage_status"] == "fetched"]
    print(f"{len(rows)} hub URLs to fetch")

    out_rows = []
    n_ok = 0
    n_video = 0
    n_youtube_lead = 0
    n_fail = 0
    for i, row in enumerate(rows):
        hub_url = row["hub_url"]
        domain = row["domain"]
        cache_path = CACHE_DIR / f"{domain}.html.gz"
        status = ""
        video_host = ""
        meeting_url = ""
        note = ""
        try:
            if urlparse(hub_url).netloc.lower().endswith(tuple(YOUTUBE_HOSTS)):
                status = "skipped-youtube"
            else:
                resp = requests.get(
                    hub_url, headers=HONEST_HEADERS, timeout=15, allow_redirects=True
                )
                status = str(resp.status_code)
                if resp.status_code == 200 and resp.text:
                    cache_path.write_bytes(
                        gzip.compress(resp.text.encode("utf-8", "replace"))
                    )
                    soup = BeautifulSoup(resp.text, "html.parser")
                    found_yt = False
                    for a in soup.find_all("a", href=True):
                        href = a["href"].strip()
                        if not href or href.startswith(
                            ("javascript:", "mailto:", "tel:", "#")
                        ):
                            continue
                        full = urljoin(resp.url, href)
                        netloc = urlparse(full).netloc.lower()
                        if any(h in netloc for h in YOUTUBE_HOSTS):
                            if not found_yt:
                                found_yt = True
                                n_youtube_lead += 1
                                note = (note + f" youtube-lead:{full}").strip()
                            continue
                        if any(h in netloc for h in VIDEO_HOSTS) and not video_host:
                            video_host = next(h for h in VIDEO_HOSTS if h in netloc)
                            meeting_url = full
                    # Also check embedded iframes (common for vendor players)
                    if not video_host:
                        for tag in soup.find_all(["iframe", "video", "source"]):
                            src = (tag.get("src") or "").strip()
                            if not src:
                                continue
                            full = urljoin(resp.url, src)
                            netloc = urlparse(full).netloc.lower()
                            if any(h in netloc for h in YOUTUBE_HOSTS):
                                if not found_yt:
                                    found_yt = True
                                    n_youtube_lead += 1
                                    note = (
                                        note + f" youtube-lead-iframe:{full}"
                                    ).strip()
                                continue
                            if any(h in netloc for h in VIDEO_HOSTS):
                                video_host = next(h for h in VIDEO_HOSTS if h in netloc)
                                meeting_url = full
                    n_ok += 1
                    if video_host:
                        n_video += 1
                else:
                    n_fail += 1
        except requests.RequestException as e:
            status = f"error:{type(e).__name__}"
            n_fail += 1

        out_rows.append(
            {
                "domain": domain,
                "gov_id": row["gov_id"],
                "hub_url": hub_url,
                "fetch_status": status,
                "video_host": video_host,
                "meeting_url": meeting_url,
                "note": note,
            }
        )
        if (i + 1) % 10 == 0:
            print(
                f"  {i + 1}/{len(rows)} done (ok={n_ok} video={n_video} yt_lead={n_youtube_lead} fail={n_fail})"
            )
        time.sleep(2.0)

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "domain",
                "gov_id",
                "hub_url",
                "fetch_status",
                "video_host",
                "meeting_url",
                "note",
            ],
        )
        w.writeheader()
        w.writerows(out_rows)

    print(f"\nfetched ok: {n_ok}")
    print(f"video/meeting link found one hop further: {n_video}")
    print(f"youtube channel/video leads found (not fetched): {n_youtube_lead}")
    print(f"failed: {n_fail}")
    print(f"wrote {OUT_CSV}")


if __name__ == "__main__":
    main()
