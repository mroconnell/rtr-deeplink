"""Read first-page agenda covers for video-link tenant identity evidence."""

import csv
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

ROOT = (
    Path(__file__).resolve().parent.parent
)  # repo root (this script now lives in scripts/)
RUN = ROOT / "research_runs" / "legistar_clients_2026-09-15"
OUT = RUN / "agenda_identity.jsonl"
PDF_DIR = RUN / "agenda_identity_pdfs"
PDF_DIR.mkdir(exist_ok=True)

_send = requests.Session.send


def guarded_send(session, request, **kwargs):
    host = (urlparse(request.url).hostname or "").lower()
    if host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com"):
        raise requests.RequestException("youtube-policy-skip-no-fetch")
    return _send(session, request, **kwargs)


requests.Session.send = guarded_send
SESSION = requests.Session()
SESSION.headers.update(
    {"User-Agent": "RTR research identity diagnostic (public agenda first page)"}
)
LAST = 0.0


def get_pdf(url):
    global LAST
    wait = 1.0 - (time.monotonic() - LAST)
    if wait > 0:
        time.sleep(wait)
    LAST = time.monotonic()
    try:
        response = SESSION.get(url, timeout=20, allow_redirects=True)
        return response, ""
    except Exception as e:
        return None, str(e)[:350]


def inspect(detail):
    client = detail["client"]
    event = detail.get("event") or {}
    url = event.get("EventAgendaFile") or ""
    result = {
        "client": client,
        "tested_at_utc": datetime.now(timezone.utc).isoformat(),
        "agenda_url": url,
        "http_status": "",
        "content_type": "",
        "pdf_sha256": "",
        "pdf_path": "",
        "first_page_text": "",
        "location_tokens": "",
        "error": "",
    }
    if not url:
        result["error"] = "no-agenda-file-on-selected-event"
        return result
    response, error = get_pdf(url)
    result["error"] = error
    if response is None:
        return result
    result["http_status"] = response.status_code
    result["content_type"] = response.headers.get("content-type", "")
    body = response.content or b""
    if response.status_code != 200 or not body.startswith(b"%PDF"):
        result["error"] = "not-pdf-or-not-200"
        return result
    if len(body) > 4_000_000:
        result["error"] = "pdf-over-4mb-cap"
        return result
    path = PDF_DIR / f"{client}.pdf"
    path.write_bytes(body)
    result["pdf_path"] = str(path)
    result["pdf_sha256"] = hashlib.sha256(body).hexdigest()
    try:
        parsed = subprocess.run(
            ["pdftotext", "-f", "1", "-l", "1", str(path), "-"],
            capture_output=True,
            text=True,
            timeout=20,
        )
        text = parsed.stdout[:3000]
        result["first_page_text"] = text.replace("\x00", "")
        result["location_tokens"] = " | ".join(
            re.findall(r"[A-Za-z .'-]+,\s*[A-Z]{2}\s*\d{5}(?:-\d{4})?", text)[:4]
        )
        (PDF_DIR / f"{client}.txt").write_text(text)
        if parsed.returncode:
            result["error"] = "pdftotext-exit-" + str(parsed.returncode)
    except Exception as e:
        result["error"] = "pdftotext-error:" + str(e)[:200]
    return result


def main(limit):
    details = {}
    for line in (RUN / "detail_probe.jsonl").read_text().splitlines():
        try:
            x = json.loads(line)
            details[x["client"]] = x
        except Exception:
            continue
    static = {
        x["client"]: x
        for x in csv.DictReader(
            open(RUN / "static_reconciliation.csv", newline="", encoding="utf-8")
        )
    }
    done = set()
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            try:
                done.add(json.loads(line)["client"])
            except Exception:
                pass
    priority = [
        x
        for x in details.values()
        if x["client"] not in done
        and x.get("video_link_count", 0) > 0
        and static[x["client"]]["reconciliation_status"]
        not in {"existing-legistar-platform-and-hub"}
    ]
    to_run = priority[:limit] if limit else priority
    print(
        len(done),
        "done;",
        len(priority),
        "priority PDFs; testing",
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
                    f"[{i}/{len(to_run)}] {result['client']}: pdf={result['http_status']} {result['location_tokens'][:50]}",
                    flush=True,
                )


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 0)
