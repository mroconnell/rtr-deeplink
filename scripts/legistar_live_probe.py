"""Polite, resumable read-only Legistar API/calendar diagnostic."""

import csv
import json
import re
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
OUT = RUN / "live_probe.jsonl"

_send = requests.Session.send


def guard_send(session, request, **kwargs):
    host = (urlparse(request.url).hostname or "").lower()
    if host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com"):
        raise requests.RequestException("youtube-policy-skip-no-fetch")
    return _send(session, request, **kwargs)


requests.Session.send = guard_send
SESSION = requests.Session()
SESSION.headers.update(
    {"User-Agent": "RTR research diagnostic (public Legistar API and calendar)"}
)
LAST_REQUEST = 0.0


def get(url):
    global LAST_REQUEST
    wait = 1.0 - (time.monotonic() - LAST_REQUEST)
    if wait > 0:
        time.sleep(wait)
    LAST_REQUEST = time.monotonic()
    try:
        response = SESSION.get(url, timeout=12, allow_redirects=True)
        return response, ""
    except Exception as e:
        return None, str(e)[:350]


def api_sample(client):
    base = f"https://webapi.legistar.com/v1/{client}"
    url = base + "/bodies?$top=1"
    response, error = get(url)
    result = {
        "url": url,
        "status": response.status_code if response is not None else "",
        "final_url": response.url if response is not None else "",
        "error": error,
        "count": "",
    }
    if response is not None and response.status_code == 200:
        try:
            data = response.json()
            result["count"] = len(data) if isinstance(data, list) else "non-list"
        except Exception as e:
            result["error"] = "json-error:" + str(e)[:100]
    return result


def events_sample(client):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    url = f"https://webapi.legistar.com/v1/{client}/events?$filter=EventDate%20lt%20datetime%27{today}%27&$orderby=EventDate%20desc&$top=10"
    response, error = get(url)
    result = {
        "url": url,
        "status": response.status_code if response is not None else "",
        "final_url": response.url if response is not None else "",
        "error": error,
        "count": "",
        "public_video_status_count": 0,
        "events": [],
    }
    if response is not None and response.status_code == 200:
        try:
            data = response.json()
            if isinstance(data, list):
                result["count"] = len(data)
                result["public_video_status_count"] = sum(
                    x.get("EventVideoStatus") == "Public" for x in data
                )
                result["events"] = [
                    {
                        k: x.get(k)
                        for k in [
                            "EventId",
                            "EventBodyName",
                            "EventDate",
                            "EventVideoStatus",
                            "EventVideoPath",
                            "EventInSiteURL",
                            "EventAgendaFile",
                        ]
                    }
                    for x in data
                ]
            else:
                result["count"] = "non-list"
        except Exception as e:
            result["error"] = "json-error:" + str(e)[:100]
    return result


def calendar_sample(client):
    url = f"https://{client}.legistar.com/Calendar.aspx"
    response, error = get(url)
    result = {
        "url": url,
        "status": response.status_code if response is not None else "",
        "final_url": response.url if response is not None else "",
        "error": error,
        "title": "",
        "h1": "",
        "legistar_calendar_signal": False,
        "video_link_count": 0,
        "meeting_detail_link_count": 0,
        "first_detail_url": "",
        "first_video_url": "",
    }
    if response is not None and response.status_code == 200 and response.text:
        soup = BeautifulSoup(response.text[:500_000], "html.parser")
        result["title"] = (
            soup.title.get_text(" ", strip=True)[:200] if soup.title else ""
        )
        result["h1"] = soup.h1.get_text(" ", strip=True)[:200] if soup.h1 else ""
        html = response.text[:500_000]
        result["legistar_calendar_signal"] = (
            "MeetingDetail.aspx" in html
            or "Calendar.aspx" in html
            and "Legistar" in html
        )
        detail = [
            a.get("href", "")
            for a in soup.select("a[href]")
            if "MeetingDetail.aspx" in a.get("href", "")
        ]
        video = [
            a.get("onclick", "")
            for a in soup.select("a.videolink[onclick]")
            if "Video.aspx" in a.get("onclick", "")
        ]
        result["meeting_detail_link_count"] = len(detail)
        result["video_link_count"] = len(video)
        result["first_detail_url"] = (
            requests.compat.urljoin(response.url, detail[0]) if detail else ""
        )
        if video:
            match = re.search(r"(Video\.aspx\?[^'\"]+)", video[0], re.I)
            result["first_video_url"] = (
                requests.compat.urljoin(response.url, match.group(1)) if match else ""
            )
    return result


def main(limit):
    with (RUN / "static_reconciliation.csv").open(newline="", encoding="utf-8") as f:
        roster = list(csv.DictReader(f))
    done = {}
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            try:
                x = json.loads(line)
                done[x["client"]] = x
            except Exception:
                continue
    remaining = [
        x
        for x in roster
        if x["client"] not in done
        and x["reconciliation_status"]
        not in {
            "archive-video-evidence",
            "queue-video-evidence-dated",
            "existing-legistar-platform-and-hub",
            "ambiguous-existing-government-match",
        }
    ]
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
        for i, row in enumerate(to_run, start=1):
            client = row["client"]
            api = api_sample(client)
            events = (
                events_sample(client)
                if api.get("status") == 200
                else {"error": "api-bodies-not-200-skip-events"}
            )
            calendar = calendar_sample(client)
            record = {
                "client": client,
                "tested_at_utc": datetime.now(timezone.utc).isoformat(),
                "api_bodies": api,
                "api_events": events,
                "calendar": calendar,
            }
            out.write(json.dumps(record) + "\n")
            out.flush()
            if i % 10 == 0 or i == len(to_run):
                print(
                    f"[{i}/{len(to_run)}] {client}: bodies={api.get('status')} calendar={calendar.get('status')} details={calendar.get('meeting_detail_link_count')}",
                    flush=True,
                )


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
