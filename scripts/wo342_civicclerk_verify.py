"""WO-342: prove the new CivicClerk listing walker (`_civicclerk_walker`,
`app/platforms/passive_verify.py`) against a real control and a real
20-government sample.

Two runs:
  1. WO-333's own CivicClerk control, Lake County FL -- never reached by
     WO-333 itself (its `wo331_handcheck.csv` row says
     `phase3_outcome=candidate-not-confirmed`, i.e. NOT_REACHED). Its real
     tenant (`lakecountyfl.portal.civicclerk.com`) is confirmed live via
     `research/coverage_registry/coverage_registry.csv`
     (`discovery_tenant`, `test_status=ingested`, 3 real archived pages
     already) -- this call is the "did WO-342's walker reach the same
     real tenant WO-333 never got to" proof, not a before/after diff
     against a WO-333-recorded verdict (there isn't one to diff against).
  2. A 20-government sample of CivicClerk's OPEN rows (no Archive page
     yet), largest population first, drawn from the same registry CSV
     -- restricted to rows that already carry a confirmed
     `*.civicclerk.com` tenant host (44 such open rows exist; see
     BACKLOG_DONE.md's WO-342 entry for the full derivation and why this
     is narrower than the shared brief's own 148/36 estimate).

Read-only: never POSTs to the Archive, never ingests here (ingest for any
real tier-1 finds happens as a separate, explicit step after hand-check,
per the shared brief). Never fetches youtube.com/youtu.be (verify_hub()'s
own guard). Never downloads a media file -- only ever calls civicclerk's
own JSON APIs.

Usage:
    DATABASE_URL="sqlite+aiosqlite:////tmp/wo342_verify.db" \\
        /Users/mroconnell/Documents/rtr-deeplink/.venv/bin/python \\
        scripts/wo342_civicclerk_verify.py
"""

from __future__ import annotations

import asyncio
import csv
import os
import sys
from pathlib import Path

import certifi

os.environ.setdefault("SSL_CERT_FILE", certifi.where())

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.passive_verify import verify_hub  # noqa: E402

register_all_finders()

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
REGISTRY_CSV = RESEARCH_DIR / "coverage_registry" / "coverage_registry.csv"
OUT_CSV = RESEARCH_DIR / "wo342_report.csv"

CONTROL = {
    "gov_id": "us:county:12069",
    "name": "Lake County, FL",
    "hub_url": "https://lakecountyfl.portal.civicclerk.com/",
    "note": "WO-333 control, never reached (phase3 candidate-not-confirmed)",
}

FIELDS = [
    "kind",  # control | sample
    "gov_id",
    "name",
    "state",
    "population",
    "hub_url",
    "meeting_found",
    "video_found",
    "captions_found",
    "tier",
    "platform",
    "verdict",
    "meeting_url",
    "candidates_checked",
    "evidence",
]


def _load_sample(limit: int = 20) -> list[dict]:
    with open(REGISTRY_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    civicclerk = [
        r
        for r in rows
        if r.get("known_platform") == "civicclerk"
        or r.get("discovery_platform") == "civicclerk"
    ]

    def is_open(r: dict) -> bool:
        try:
            return int(r.get("archive_pages") or 0) == 0
        except ValueError:
            return True

    def tenant_host(r: dict) -> str:
        dt = (r.get("discovery_tenant") or "").lower()
        if "civicclerk.com" in dt:
            return dt
        hu = (r.get("hub_url") or "").lower()
        if "civicclerk.com" in hu:
            from urllib.parse import urlparse

            return urlparse(hu).netloc.lower()
        return ""

    def pop(r: dict) -> int:
        try:
            return int(r.get("population") or 0)
        except ValueError:
            return 0

    candidates = [r for r in civicclerk if is_open(r) and tenant_host(r)]
    candidates.sort(key=pop, reverse=True)
    out = []
    for r in candidates[:limit]:
        out.append(
            {
                "gov_id": r["gov_id"],
                "name": r["name"],
                "state": r["state"],
                "population": pop(r),
                "hub_url": f"https://{tenant_host(r)}/",
            }
        )
    return out


async def _verify_one(kind: str, gov: dict) -> dict:
    hub_url = gov["hub_url"]
    print(
        f"=== [{kind}] {gov.get('name')} ({gov.get('gov_id')}) {hub_url}",
        file=sys.stderr,
    )
    try:
        result = await verify_hub(hub_url, platform_hint="civicclerk")
        row = {
            "kind": kind,
            "gov_id": gov.get("gov_id", ""),
            "name": gov.get("name", ""),
            "state": gov.get("state", ""),
            "population": gov.get("population", ""),
            "hub_url": hub_url,
            "meeting_found": result.meeting_found,
            "video_found": result.video_found,
            "captions_found": result.captions_found,
            "tier": result.tier if result.tier is not None else "",
            "platform": result.platform or "",
            "verdict": result.verdict,
            "meeting_url": result.meeting_url or "",
            "candidates_checked": result.candidates_checked,
            "evidence": result.evidence[:300],
        }
        print(
            f"    tier={row['tier']} meeting_found={row['meeting_found']} "
            f"video_found={row['video_found']} captions_found={row['captions_found']} "
            f"verdict={row['verdict']} platform={row['platform']}",
            file=sys.stderr,
        )
    except Exception as e:  # noqa: BLE001
        row = {
            "kind": kind,
            "gov_id": gov.get("gov_id", ""),
            "name": gov.get("name", ""),
            "state": gov.get("state", ""),
            "population": gov.get("population", ""),
            "hub_url": hub_url,
            "meeting_found": False,
            "video_found": False,
            "captions_found": False,
            "tier": "",
            "platform": "",
            "verdict": "crash",
            "meeting_url": "",
            "candidates_checked": 0,
            "evidence": f"{type(e).__name__}: {e}"[:300],
        }
        print(f"    CRASH {type(e).__name__}: {e}", file=sys.stderr)
    return row


async def main() -> None:
    out_rows: list[dict] = []

    control_row = await _verify_one("control", CONTROL)
    out_rows.append(control_row)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(out_rows)
    await asyncio.sleep(1.5)

    sample = _load_sample(20)
    print(f"\n{len(sample)} sample governments to verify\n", file=sys.stderr)
    for gov in sample:
        row = await _verify_one("sample", gov)
        out_rows.append(row)
        with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(out_rows)
        await asyncio.sleep(1.5)

    from collections import Counter

    tiers = Counter(r["tier"] for r in out_rows if r["kind"] == "sample")
    print(f"\nsample tier tally: {dict(tiers)}", file=sys.stderr)


if __name__ == "__main__":
    asyncio.run(main())
