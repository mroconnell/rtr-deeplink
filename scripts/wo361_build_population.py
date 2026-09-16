"""WO-361 (2026-09-13): build the population for "find the platform page
first" -- the WO-355 off-mission governments whose starting point was a
bare homepage (`hub_source == "bare_homepage"` in `wo355_verify.csv`,
476 rows), plus WO-355's no-meeting-found rows that are not already in
that set (`meeting_found == False and video_found == False` with
`hub_source == "population_hub_url"`, 6 rows -- these had an existing
hub_url on file and still turned up nothing, so they deserve the same
passive-pipeline-plus-ladder treatment).

WO-355's own finding: 62 of 64 "videos" `verify_hub()` found on these
476 bare homepages were the site's own welcome/promo clip, because
`verify_hub()`'s single plain fetch of a bare homepage is not a meeting
hub. Ryan: "we need to find their platform page by doing the passive
pipe and ladder access and then we will have videos that might actually
be on mission." This WO's job is the hub-finding step; the video walk
only runs once a real hub is confirmed.

Total population: 482 (476 + 6). Sorted by population descending
(largest first, per the brief).

Usage (from the rtr-deeplink repo root, shared venv -- no app/archive
import, so DATABASE_URL is not required):
    .venv/bin/python scripts/wo361_build_population.py
"""

from __future__ import annotations

import csv
from pathlib import Path

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
WO355_VERIFY_CSV = RESEARCH_DIR / "wo355_verify.csv"
OUT_CSV = RESEARCH_DIR / "wo361_population.csv"

FIELDNAMES = [
    "gov_id",
    "name",
    "state",
    "population",
    "domain",
    "homepage_url",
    "platform_hint",
    "wo355_verdict",
    "wo355_tier",
    "wo355_hub_source",
]


def _population(raw: str) -> int:
    raw = (raw or "").strip()
    if not raw:
        return 0
    try:
        return int(float(raw))
    except ValueError:
        return 0


def build() -> list[dict]:
    with open(WO355_VERIFY_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    out_rows = []
    for row in rows:
        hub_source = row.get("hub_source", "")
        meeting_found = row.get("meeting_found") == "True"
        video_found = row.get("video_found") == "True"
        include = hub_source == "bare_homepage" or (
            hub_source == "population_hub_url" and not meeting_found and not video_found
        )
        if not include:
            continue
        domain = row.get("domain", "")
        out_rows.append(
            {
                "gov_id": row["gov_id"],
                "name": row.get("name", ""),
                "state": row.get("state", ""),
                "population": _population(row.get("population")),
                "domain": domain,
                "homepage_url": f"https://{domain}" if domain else "",
                "platform_hint": row.get("platform_hint", ""),
                "wo355_verdict": row.get("verdict", ""),
                "wo355_tier": row.get("tier", ""),
                "wo355_hub_source": hub_source,
            }
        )
    out_rows.sort(key=lambda r: r["population"], reverse=True)
    return out_rows


def main() -> None:
    rows = build()
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {OUT_CSV}")

    bands = [
        ("100k+", lambda p: p >= 100_000),
        ("10k-100k", lambda p: 10_000 <= p < 100_000),
        ("1k-10k", lambda p: 1_000 <= p < 10_000),
        ("<1k", lambda p: 0 < p < 1_000),
        ("unknown/0", lambda p: p == 0),
    ]
    print("\nby population band:")
    for label, pred in bands:
        count = sum(1 for r in rows if pred(r["population"]))
        print(f"  {label}: {count}")

    from collections import Counter

    print("\nby wo355_hub_source:")
    for k, v in Counter(r["wo355_hub_source"] for r in rows).items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
