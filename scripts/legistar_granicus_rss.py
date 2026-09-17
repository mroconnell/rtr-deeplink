"""Observed-view Granicus RSS diagnostics for Legistar video redirects."""

import json
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = (
    Path(__file__).resolve().parent.parent
)  # repo root (this script now lives in scripts/)
RUN = ROOT / "research_runs" / "legistar_clients_2026-09-15"
OUT = RUN / "rss_probe.jsonl"

_send = requests.Session.send


def guarded_send(session, request, **kwargs):
    host = (urlparse(request.url).hostname or "").lower()
    if host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com"):
        raise requests.RequestException("youtube-policy-skip-no-fetch:" + request.url)
    return _send(session, request, **kwargs)


requests.Session.send = guarded_send
SESSION = requests.Session()
SESSION.headers.update(
    {"User-Agent": "RTR research diagnostic (public Granicus RSS observed view only)"}
)
LAST = 0.0


def fetch_mode(host, view_id, mode):
    global LAST
    wait = 1.0 - (time.monotonic() - LAST)
    if wait > 0:
        time.sleep(wait)
    LAST = time.monotonic()
    url = f"https://{host}/ViewPublisherRSS.php?view_id={view_id}&mode={mode}"
    result = {
        "url": url,
        "status": "",
        "content_type": "",
        "feed_title": "",
        "real_item_count": 0,
        "clip_link_count": 0,
        "media_enclosure_count": 0,
        "first_item_title": "",
        "first_item_link": "",
        "first_enclosure_type": "",
        "enclosure_types": {},
        "error": "",
    }
    try:
        response = SESSION.get(url, timeout=15, allow_redirects=True)
        result["status"] = response.status_code
        result["content_type"] = response.headers.get("content-type", "")
        if response.status_code != 200:
            return result
        root = ET.fromstring(response.content[:600_000])
        channel = root.find("channel")
        if channel is None:
            result["error"] = "xml-no-channel"
            return result
        result["feed_title"] = (channel.findtext("title") or "")[:200]
        items = channel.findall("item")
        real = [
            x for x in items if "no records" not in (x.findtext("title") or "").lower()
        ]
        result["real_item_count"] = len(real)
        result["clip_link_count"] = sum(
            "MediaPlayer.php" in (x.findtext("link") or "")
            or "/player/clip/" in (x.findtext("link") or "")
            for x in real
        )
        enclosures = [x.find("enclosure") for x in real]
        result["media_enclosure_count"] = sum(
            bool(e is not None and e.get("url")) for e in enclosures
        )
        types = {}
        for e in enclosures:
            if e is not None and e.get("url"):
                mime = e.get("type") or "unspecified"
                types[mime] = types.get(mime, 0) + 1
        result["enclosure_types"] = types
        if real:
            result["first_item_title"] = (real[0].findtext("title") or "")[:250]
            result["first_item_link"] = (real[0].findtext("link") or "")[:350]
            first_enclosure = real[0].find("enclosure")
            result["first_enclosure_type"] = (
                first_enclosure.get("type") or "" if first_enclosure is not None else ""
            )
    except Exception as e:
        result["error"] = str(e)[:350]
    return result


def main(limit):
    redirects = {}
    for line in (RUN / "video_redirect_probe.jsonl").read_text().splitlines():
        try:
            x = json.loads(line)
            if (
                x.get("http_status") == 200
                and x.get("final_host", "").endswith(".granicus.com")
                and x.get("view_id_from_url")
            ):
                redirects[x["client"]] = x
        except Exception:
            pass
    done = set()
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            try:
                done.add(json.loads(line)["client"])
            except Exception:
                pass
    remaining = [x for c, x in redirects.items() if c not in done]
    to_run = remaining[:limit] if limit else remaining
    print(
        len(done),
        "done;",
        len(remaining),
        "observed views remaining; testing",
        len(to_run),
        flush=True,
    )
    with OUT.open("a", encoding="utf-8") as out:
        for i, redirect in enumerate(to_run, start=1):
            host, view_id = redirect["final_host"], redirect["view_id_from_url"]
            video = fetch_mode(host, view_id, "video")
            podcast = fetch_mode(host, view_id, "podcast")
            result = {
                "client": redirect["client"],
                "tested_at_utc": datetime.now(timezone.utc).isoformat(),
                "observed_host": host,
                "observed_view_id": view_id,
                "source_clip_url": redirect["final_url"],
                "video_mode": video,
                "podcast_mode": podcast,
            }
            out.write(json.dumps(result) + "\n")
            out.flush()
            if i % 10 == 0 or i == len(to_run):
                print(
                    f"[{i}/{len(to_run)}] {redirect['client']}: video={video['status']}/{video['real_item_count']} podcast={podcast['status']}/{podcast['real_item_count']}",
                    flush=True,
                )


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
