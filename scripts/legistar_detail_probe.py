"""One past event per narrowed Legistar client using the current adapter parser."""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

ROOT = (
    Path(__file__).resolve().parent.parent
)  # repo root (this script now lives in scripts/)
RUN = ROOT / "research_runs" / "legistar_clients_2026-09-15"
OUT = RUN / "detail_probe.jsonl"
os.environ["DATABASE_URL"] = (
    "sqlite+aiosqlite:////private/tmp/legistar_clients_scratch.sqlite"
)
sys.path.insert(0, str(ROOT))
from app.platforms.legistar import LegistarAssetFinder  # noqa: E402

_send = requests.Session.send


def guarded_send(session, request, **kwargs):
    host = (urlparse(request.url).hostname or "").lower()
    if host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com"):
        raise requests.RequestException("youtube-policy-skip-no-fetch")
    return _send(session, request, **kwargs)


requests.Session.send = guarded_send
SESSION = requests.Session()
SESSION.headers.update(
    {"User-Agent": "RTR research diagnostic (public Legistar meeting pages)"}
)
FINDER = LegistarAssetFinder()
LAST = 0.0


def get(url):
    global LAST
    wait = 1.0 - (time.monotonic() - LAST)
    if wait > 0:
        time.sleep(wait)
    LAST = time.monotonic()
    try:
        response = SESSION.get(url, timeout=15, allow_redirects=True)
        return response, ""
    except Exception as e:
        return None, str(e)[:350]


def choose_event(probe):
    events = probe.get("api_events", {}).get("events") or []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    valid = [
        x
        for x in events
        if x.get("EventInSiteURL") and (x.get("EventDate") or "")[:10] < today
    ]
    council = [
        x
        for x in valid
        if any(
            k in (x.get("EventBodyName") or "").lower()
            for k in ["council", "commission", "board", "committee", "supervisor"]
        )
    ]
    public = [x for x in valid if x.get("EventVideoStatus") == "Public"]
    event = (council or public or valid)[:1]
    if event:
        return event[0], "api-recent-past-event"
    cal = probe.get("calendar", {})
    if cal.get("first_detail_url"):
        return {
            "EventInSiteURL": cal["first_detail_url"]
        }, "calendar-first-detail-date-unchecked"
    return None, "no-detail-url"


def inspect(client, probe):
    event, selection = choose_event(probe)
    result = {
        "client": client,
        "tested_at_utc": datetime.now(timezone.utc).isoformat(),
        "selection": selection,
        "event": event or {},
        "detail_url": "",
        "http_status": "",
        "final_url": "",
        "page_title": "",
        "page_h1": "",
        "body_text_excerpt": "",
        "video_link_count": 0,
        "video_url": "",
        "audio_link_count": 0,
        "youtube_leads": [],
        "error": "",
    }
    if not event:
        return result
    url = event["EventInSiteURL"]
    result["detail_url"] = url
    response, error = get(url)
    result["error"] = error
    if response is None:
        return result
    result["http_status"] = response.status_code
    result["final_url"] = response.url
    if response.status_code != 200:
        return result
    soup = BeautifulSoup(response.text[:600_000], "html.parser")
    result["page_title"] = (
        soup.title.get_text(" ", strip=True)[:200] if soup.title else ""
    )
    result["page_h1"] = soup.h1.get_text(" ", strip=True)[:200] if soup.h1 else ""
    result["body_text_excerpt"] = soup.get_text(" ", strip=True)[:500]
    try:
        videos = FINDER._find_video_links(soup, response.url)
        result["video_link_count"] = len(videos)
        result["video_url"] = videos[0]["url"] if videos else ""
    except Exception as e:
        result["error"] = "adapter-video-parser-error:" + str(e)[:220]
    result["audio_link_count"] = sum(
        "Mode2=Audio" in (a.get("onclick") or "") for a in soup.select("a[onclick]")
    )
    result["youtube_leads"] = sorted(
        {
            a.get("href")
            for a in soup.select("a[href]")
            if a.get("href") and ("youtube.com" in a["href"] or "youtu.be" in a["href"])
        }
    )[:10]
    return result


def main(limit):
    probes = {}
    for line in (RUN / "live_probe.jsonl").read_text().splitlines():
        try:
            x = json.loads(line)
            probes[x["client"]] = x
        except Exception:
            pass
    done = set()
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            try:
                done.add(json.loads(line)["client"])
            except Exception:
                pass
    remaining = [c for c in probes if c not in done]
    to_run = remaining[:limit] if limit else remaining
    print(
        len(done),
        "done;",
        len(remaining),
        "remaining; testing",
        len(to_run),
        flush=True,
    )
    with OUT.open("a", encoding="utf-8") as out:
        for i, client in enumerate(to_run, start=1):
            result = inspect(client, probes[client])
            out.write(json.dumps(result) + "\n")
            out.flush()
            if i % 10 == 0 or i == len(to_run):
                print(
                    f"[{i}/{len(to_run)}] {client}: detail={result['http_status']} video={result['video_link_count']} audio={result['audio_link_count']}",
                    flush=True,
                )


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
