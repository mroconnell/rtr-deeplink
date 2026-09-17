"""Read-only redirect check for Legistar Mode2=Video links, never media."""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests

ROOT = (
    Path(__file__).resolve().parent.parent
)  # repo root (this script now lives in scripts/)
RUN = ROOT / "research_runs" / "legistar_clients_2026-09-15"
OUT = RUN / "video_redirect_probe.jsonl"

_send = requests.Session.send


def guarded_send(session, request, **kwargs):
    host = (urlparse(request.url).hostname or "").lower()
    if host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com"):
        raise requests.RequestException("youtube-policy-skip-no-fetch:" + request.url)
    return _send(session, request, **kwargs)


requests.Session.send = guarded_send
SESSION = requests.Session()
SESSION.headers.update(
    {"User-Agent": "RTR research diagnostic (meeting video-link redirect only)"}
)
LAST = 0.0


def inspect(detail):
    global LAST
    wait = 1.0 - (time.monotonic() - LAST)
    if wait > 0:
        time.sleep(wait)
    LAST = time.monotonic()
    url = detail["video_url"]
    result = {
        "client": detail["client"],
        "tested_at_utc": datetime.now(timezone.utc).isoformat(),
        "meeting_detail_url": detail["detail_url"],
        "meeting_body": (detail.get("event") or {}).get("EventBodyName", ""),
        "meeting_date": ((detail.get("event") or {}).get("EventDate") or "")[:10],
        "legistar_video_url": url,
        "http_status": "",
        "final_url": "",
        "final_host": "",
        "content_type": "",
        "view_id_from_url": "",
        "error": "",
    }
    try:
        response = SESSION.get(url, timeout=15, allow_redirects=True, stream=True)
        result["http_status"] = response.status_code
        result["final_url"] = response.url
        result["final_host"] = urlparse(response.url).hostname or ""
        result["content_type"] = response.headers.get("content-type", "")
        query = parse_qs(urlparse(response.url).query)
        result["view_id_from_url"] = (query.get("view_id") or [""])[0]
        response.close()
    except Exception as e:
        result["error"] = str(e)[:500]
    return result


def main(limit):
    details = {}
    for line in (RUN / "detail_probe.jsonl").read_text().splitlines():
        try:
            x = json.loads(line)
            if x.get("video_url"):
                details[x["client"]] = x
        except Exception:
            pass
    done = set()
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            try:
                done.add(json.loads(line)["client"])
            except Exception:
                pass
    remaining = [d for c, d in details.items() if c not in done]
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
        for i, detail in enumerate(to_run, start=1):
            result = inspect(detail)
            out.write(json.dumps(result) + "\n")
            out.flush()
            if i % 10 == 0 or i == len(to_run):
                print(
                    f"[{i}/{len(to_run)}] {result['client']}: {result['http_status']} {result['final_host']} {result['error'][:45]}",
                    flush=True,
                )


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
