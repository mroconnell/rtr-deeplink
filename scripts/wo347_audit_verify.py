"""WO-347 Part B, pass 2: run verify_hub() on every real candidate URL
the access-ladder audit (wo347_audit_sample_run.py) found, to get a
precise, adapter-verified tier instead of a text-match guess. Never
fetches a youtube.com/youtu.be URL directly (verify_hub's own guard) --
a YouTube channel hit is recorded as a lead signal, not resolved.
"""

from __future__ import annotations

import asyncio
import csv
import os
import sys
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.passive_verify import verify_hub  # noqa: E402

register_all_finders()

RESEARCH = Path.home() / "Documents" / "rtr-business" / "research"
RAW = RESEARCH / "wo347_audit_raw_findings.csv"
OUT = RESEARCH / "wo347_audit_verify2.csv"


async def main():
    with open(RAW, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    results = []
    for i, r in enumerate(rows):
        candidate = r["hit_url"] or r["hop_candidate"]
        platform = r["platform_detected"] or None
        out = {
            "domain": r["domain"],
            "gov_id": r["gov_id"],
            "candidate": candidate,
            "platform_hint": platform,
            "verdict": "",
            "tier": "",
            "meeting_found": "",
            "video_found": "",
            "meeting_url": "",
            "evidence": "",
            "error": "",
        }
        if not candidate:
            out["verdict"] = "no_candidate"
            results.append(out)
            print(f"[{i + 1}/{len(rows)}] {r['domain']}: no_candidate")
            continue
        if "youtube.com" in candidate or "youtu.be" in candidate:
            out["verdict"] = "youtube_lead_not_fetched"
            results.append(out)
            print(
                f"[{i + 1}/{len(rows)}] {r['domain']}: youtube_lead (not fetched) -> {candidate}"
            )
            continue
        try:
            res = await verify_hub(candidate, platform_hint=platform)
            out["verdict"] = res.verdict
            out["tier"] = res.tier if res.tier is not None else ""
            out["meeting_found"] = res.meeting_found
            out["video_found"] = res.video_found
            out["meeting_url"] = res.meeting_url or ""
            out["evidence"] = (res.evidence or "")[:300]
        except Exception as e:  # noqa: BLE001
            out["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            out["verdict"] = "exception"
        results.append(out)
        print(
            f"[{i + 1}/{len(rows)}] {r['domain']}: verdict={out['verdict']} tier={out['tier']}"
        )

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
        w.writeheader()
        w.writerows(results)
    print(f"\nwrote {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
