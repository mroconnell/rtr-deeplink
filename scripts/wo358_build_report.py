"""WO-358: builds `research/wo358_report.csv` (one row per government)
from `research/wo358_verify.csv` plus this WO's hand-check/finish
dispositions. Usage: python3 scripts/wo358_build_report.py
"""

from __future__ import annotations

import csv
from pathlib import Path

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
VERIFY_CSV = RESEARCH_DIR / "wo358_verify.csv"
OUT_CSV = RESEARCH_DIR / "wo358_report.csv"

TIER3_REJECTED_BY_PROBE = {"us:place:2720078", "us:cousub:2502109175"}
TIER3_DUPLICATE_QUEUED = {
    "us:place:4829972",  # Godley city, TX
    "us:place:4875236",  # Venus town, TX
    "us:place:1829358",  # Greencastle city, IN
    "us:place:4866416",  # Seadrift city, TX
    "us:place:4858280",  # Pleasanton city, TX
    "us:county:23023",  # Sagadahoc County, ME
    "us:cousub:3608357441",  # Petersburgh town, NY
}

INGEST_URL_OVERRIDE = {
    "us:place:4875236": "https://venustx.portal.civicclerk.com/event/295/media",
    "us:place:1829358": "https://greencastlein.portal.civicclerk.com/event/1585/media",
    "us:place:4866416": "https://seadrifttx.portal.civicclerk.com/event/20/media",
    "us:place:4858280": "https://pleasantontx.iqm2.com/Citizens/Detail_Meeting.aspx?ID=1371",
    "us:county:23023": "https://townhallstreams.com/stream.php?location_id=154&id=75643",
    "us:cousub:3608357441": "https://townhallstreams.com/stream.php?location_id=152&id=75784",
}


def main() -> None:
    verify_rows = {}
    with open(VERIFY_CSV, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            verify_rows[r["gov_id"]] = r

    fieldnames = [
        "gov_id",
        "name",
        "state",
        "platform",
        "population",
        "tier",
        "verdict",
        "meeting_url",
        "disposition",
        "evidence",
    ]
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as out:
        w = csv.DictWriter(out, fieldnames=fieldnames)
        w.writeheader()
        for gid, r in verify_rows.items():
            disposition = ""
            if gid in TIER3_REJECTED_BY_PROBE:
                disposition = "rejected_by_probe"
            elif gid in TIER3_DUPLICATE_QUEUED:
                disposition = "duplicate_queued"
            elif r["tier"] == "2":
                disposition = "youtube_lead"
            elif r["tier"] == "4":
                disposition = "meeting_without_video"
            elif r["verdict"] == "resolved_empty":
                disposition = "no_meetings_found"
            elif r["verdict"] in ("resolve_error", "fetch_failed", "no_domain"):
                disposition = "error_left_alone"
            w.writerow(
                {
                    "gov_id": gid,
                    "name": r["name"],
                    "state": r["state"],
                    "platform": r["platform"],
                    "population": r["population"],
                    "tier": r["tier"],
                    "verdict": r["verdict"],
                    "meeting_url": INGEST_URL_OVERRIDE.get(gid, r["meeting_url"]),
                    "disposition": disposition,
                    "evidence": r["evidence"],
                }
            )
    print(f"wrote {len(verify_rows)} rows to {OUT_CSV}")


if __name__ == "__main__":
    main()
