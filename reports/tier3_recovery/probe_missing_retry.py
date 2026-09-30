"""Retry of probe_missing.py: the first run returned reject-dead for all
44 urls, which a manual spot-check disproved (the same url worked fine
moments later) -- almost certainly the shared Granicus/Legistar backend
rate-limiting a rapid run of different tenant subdomains that our
per-exact-host delay didn't slow down enough. This version keys the
delay off the REGISTERED domain (last two labels, e.g. "granicus.com"),
not the full subdomain, and uses a longer 6s spacing as a safety margin.
"""
import os
import certifi
os.environ.setdefault("SSL_CERT_FILE", certifi.where())
import sys
import json
import time
import asyncio
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, ".")
from app.platforms import register_all_finders
register_all_finders()
from app.platforms.queue_probe import probe_queue_entry, append_probe_row

REPORTS = Path("reports/tier3_recovery")
MISSING = REPORTS / "winners_needing_probe.jsonl"
PROBE_CSV = Path("scripts/tier3_auto_transcription_queue_probe.csv")
HOST_MIN_INTERVAL = 6.0

_last = {}


def registered_domain(netloc: str) -> str:
    parts = netloc.lower().split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else netloc.lower()


async def polite_wait(domain):
    last = _last.get(domain)
    if last is not None:
        elapsed = time.monotonic() - last
        if elapsed < HOST_MIN_INTERVAL:
            await asyncio.sleep(HOST_MIN_INTERVAL - elapsed)
    _last[domain] = time.monotonic()


async def main():
    rows = [json.loads(l) for l in MISSING.read_text().splitlines()]
    print(f"re-probing {len(rows)} urls with domain-level pacing", flush=True)
    results = []
    for i, r in enumerate(rows, 1):
        url = r["url"]
        domain = registered_domain(urlparse(url).netloc)
        await polite_wait(domain)
        try:
            result = await probe_queue_entry(url, platform=r.get("platform"))
            append_probe_row(PROBE_CSV, result, caller="tier3_recovery_2026-09-29")
            results.append((url, result.verdict, result.duration_seconds, result.reason))
            print(f"[{i}/{len(rows)}] {url[:70]} -> verdict={result.verdict} duration={result.duration_seconds} reason={result.reason}", flush=True)
        except Exception as e:
            results.append((url, "ERROR", None, str(e)))
            print(f"[{i}/{len(rows)}] {url[:70]} -> ERROR {type(e).__name__}: {e}", flush=True)

    with open(REPORTS / "probe_retry_results.jsonl", "w") as f:
        for url, verdict, duration, reason in results:
            f.write(json.dumps({"url": url, "verdict": verdict, "duration_seconds": duration, "reason": reason}) + "\n")
    print("DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
