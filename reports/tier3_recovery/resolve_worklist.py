"""Step 2+4 (partial): for each of the 257 never-resolved / dead-video
worklist lines, re-resolve the meeting locally (real video/caption state)
and resolve its government (tenant_overrides pins + the registry ladder,
via the exact same resolve_government() ingest itself calls). Writes one
JSON object per line to resolved_257.jsonl, appending as it goes so a
restart resumes rather than re-fetching lines already done.

Rate limits (per the job): one request at a time per host, 3s apart,
TelVue capped at ~5 reads/station (each of our 5 TelVue lines is a
different station, so this never bites), never Kalamazoo (none in this
worklist -- checked).
"""
import os
import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

import sys
import json
import time
import asyncio
import traceback
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, ".")

from app.platforms import register_all_finders
from app.platforms.base import resolve_via_platform, detect_platform, YouTubeResolveBlocked
from app.utils.gov_registry.resolver import resolve_government, _tenant_host

register_all_finders()

REPORTS = Path("reports/tier3_recovery")
WORKLIST = REPORTS / "worklist_257.jsonl"
OUT = REPORTS / "resolved_257.jsonl"
HOST_MIN_INTERVAL = 3.0

_last_request_at: dict[str, float] = {}


async def polite_wait(host: str) -> None:
    last = _last_request_at.get(host)
    if last is not None:
        elapsed = time.monotonic() - last
        if elapsed < HOST_MIN_INTERVAL:
            await asyncio.sleep(HOST_MIN_INTERVAL - elapsed)
    _last_request_at[host] = time.monotonic()


def classify_video_tier(platform: str, segments, transcript_warnings) -> tuple[str, str]:
    """Returns (tier, reason). tier in {"1", "2", "3"}."""
    if platform == "youtube":
        return "2", "YouTube -- captions exist but only the drip Mac can read them"
    if platform == "vimeo":
        return "2", "Vimeo -- captions exist but only a local run can read them (tier 2 since 2026-09-26)"
    if segments:
        return "1", f"server-readable captions found ({len(segments)} segments)"
    warn_text = " ".join(transcript_warnings or []).lower()
    if "no video" in warn_text or "no usable" in warn_text:
        return "dead", "; ".join(transcript_warnings or []) or "no video found on re-resolve"
    return "3", "; ".join(transcript_warnings or []) or "video present, no reachable captions"


async def process_one(row: dict) -> dict:
    url = row["url"]
    host = urlparse(url).netloc.lower()
    tenant_host = _tenant_host(urlparse(url).netloc)
    path = urlparse(url).path

    out = {
        "url": url,
        "source_batch": row["source_batch"],
        "local_batch_status": row["local_batch_status"],
        "local_batch_detail": row.get("local_batch_detail"),
    }

    await polite_wait(host)
    try:
        resolved = await resolve_via_platform(url, allow_youtube=False)
        out["resolve_ok"] = True
        out["platform"] = resolved.platform
        out["jurisdiction_name"] = resolved.jurisdiction
        out["origin_host"] = resolved.origin_host
        out["video_url"] = getattr(resolved, "video_url", None)
        out["date"] = resolved.date
        out["title"] = resolved.title
        n_segments = len(resolved.segments) if resolved.segments else 0
        out["segments_count"] = n_segments
        out["transcript_warnings"] = resolved.transcript_warnings
        tier, tier_reason = classify_video_tier(
            resolved.platform, resolved.segments, resolved.transcript_warnings
        )
        out["video_tier"] = tier
        out["video_tier_reason"] = tier_reason
        jurisdiction_for_gov = resolved.jurisdiction
        origin_host_for_gov = resolved.origin_host
    except YouTubeResolveBlocked as e:
        out["resolve_ok"] = True
        out["platform"] = "youtube"
        out["video_tier"] = "2"
        out["video_tier_reason"] = f"YouTubeResolveBlocked: {e}"
        out["jurisdiction_name"] = None
        out["origin_host"] = None
        jurisdiction_for_gov = None
        origin_host_for_gov = None
    except Exception as e:
        out["resolve_ok"] = False
        out["video_tier"] = "dead"
        out["video_tier_reason"] = f"{type(e).__name__}: {str(e)[:300]}"
        out["jurisdiction_name"] = None
        out["origin_host"] = None
        jurisdiction_for_gov = None
        origin_host_for_gov = None

    # Government resolution: local + pin-based, no extra network needed --
    # try with the jurisdiction name/origin_host we just found, and if
    # that's not confident, retry bare (tenant_host/path only) in case
    # the page-text jurisdiction confused the ladder.
    match = resolve_government(
        jurisdiction_for_gov, tenant_host=tenant_host, path=path,
        origin_host=origin_host_for_gov,
    )
    if match.tier not in ("registry", "pinned") and jurisdiction_for_gov:
        bare = resolve_government(None, tenant_host=tenant_host, path=path)
        if bare.tier in ("registry", "pinned"):
            match = bare

    out["gov_id"] = match.gov_id if match.tier in ("registry", "pinned") else None
    out["gov_confidence"] = match.tier
    out["gov_evidence"] = (match.evidence or "")[:300]
    return out


async def main():
    rows = [json.loads(l) for l in WORKLIST.read_text().splitlines()]
    done_urls = set()
    if OUT.exists():
        for l in OUT.read_text().splitlines():
            if l.strip():
                done_urls.add(json.loads(l)["url"])
    print(f"{len(rows)} total, {len(done_urls)} already done, {len(rows) - len(done_urls)} to go", flush=True)

    with open(OUT, "a") as f:
        for i, row in enumerate(rows, 1):
            if row["url"] in done_urls:
                continue
            try:
                result = await process_one(row)
            except Exception as e:
                result = {
                    "url": row["url"],
                    "source_batch": row["source_batch"],
                    "local_batch_status": row["local_batch_status"],
                    "resolve_ok": False,
                    "video_tier": "error",
                    "video_tier_reason": f"unhandled {type(e).__name__}: {e}",
                    "gov_id": None,
                    "gov_confidence": "error",
                }
                traceback.print_exc()
            f.write(json.dumps(result) + "\n")
            f.flush()
            print(f"[{i}/{len(rows)}] {row['url'][:80]} -> tier={result.get('video_tier')} gov={result.get('gov_id')} conf={result.get('gov_confidence')}", flush=True)

    print("DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
