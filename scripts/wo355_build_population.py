"""WO-355 (2026-09-13): build the population for the non-YouTube
off-mission re-verify.

Ryan's rule: a turned-away video is a verdict on that video, not the
government. `verify_hub()` now (WO-355 part 1, PR #1145) supports a
`deep_walk=True` option that collects up to 3 video candidates from a
listing instead of stopping at the first -- this WO re-runs every
`off-mission` government whose real video source is NOT YouTube through
that deeper walk, since the YouTube-sourced ones already have their own
recheck list (WO-353, `research/wo353_offmission_youtube_recheck.csv`,
on the drip lane -- this WO never fetches YouTube itself, so those are
out of scope here).

Population = every row in `research/jurisdiction_coverage.csv` with
`reject_reason == "off-mission"`, MINUS every `gov_id` that appears in
`research/wo353_offmission_youtube_recheck.csv` (its own gov_id column).

Writes `research/wo355_population.csv`, sorted by `population_estimate`
descending (largest first, per the brief), with a `platform` column
derived from `suspected_video_provider` (falling back to
`suspected_meeting_link_provider` then `suspected_calendar_provider`)
for the by-platform table, and a `hub_url` column (the best existing URL
on the row -- `example_meeting_url` if present, else
`example_agenda_or_calendar_url`) for `verify_hub()` to re-walk.

Usage (from the rtr-deeplink repo root, shared venv -- no app/archive
import, so DATABASE_URL is not required):
    .venv/bin/python scripts/wo355_build_population.py
"""

from __future__ import annotations

import csv
from pathlib import Path

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
JC_CSV = RESEARCH_DIR / "jurisdiction_coverage.csv"
WO353_CSV = RESEARCH_DIR / "wo353_offmission_youtube_recheck.csv"
OUT_CSV = RESEARCH_DIR / "wo355_population.csv"

FIELDNAMES = [
    "gov_id",
    "name",
    "state",
    "population",
    "domain",
    "hub_url",
    "example_agenda_or_calendar_url",
    "example_meeting_url",
    "platform",
    "suspected_video_provider",
    "suspected_meeting_link_provider",
    "suspected_calendar_provider",
]


def _population(row: dict) -> int:
    raw = (row.get("population_estimate") or "").strip()
    if not raw:
        return 0
    try:
        return int(float(raw))
    except ValueError:
        return 0


def load_youtube_sourced_gov_ids() -> set:
    with open(WO353_CSV, newline="", encoding="utf-8") as f:
        return {row["gov_id"] for row in csv.DictReader(f) if row.get("gov_id")}


def build() -> list[dict]:
    youtube_sourced = load_youtube_sourced_gov_ids()
    out_rows = []
    skipped_no_gov_id = 0
    with open(JC_CSV, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if (row.get("reject_reason") or "").strip() != "off-mission":
                continue
            gov_id = (row.get("gov_id") or "").strip()
            if gov_id and gov_id in youtube_sourced:
                continue
            if not gov_id:
                skipped_no_gov_id += 1
                # No gov_id at all -- can't send it in an ingest payload
                # (CLAUDE.md's rule) and can't cross-check it against the
                # WO-353 YouTube-sourced list reliably either. Still
                # include it (population is a superset the verify script
                # can decide what to do with), tagged via empty gov_id.
            hub_url = (row.get("example_meeting_url") or "").strip() or (
                row.get("example_agenda_or_calendar_url") or ""
            ).strip()
            platform = (
                (row.get("suspected_video_provider") or "").strip()
                or (row.get("suspected_meeting_link_provider") or "").strip()
                or (row.get("suspected_calendar_provider") or "").strip()
            )
            out_rows.append(
                {
                    "gov_id": gov_id,
                    "name": row.get("city_name", ""),
                    "state": row.get("state_or_province", ""),
                    "population": _population(row),
                    "domain": row.get("domain", ""),
                    "hub_url": hub_url,
                    "example_agenda_or_calendar_url": row.get(
                        "example_agenda_or_calendar_url", ""
                    ),
                    "example_meeting_url": row.get("example_meeting_url", ""),
                    "platform": platform,
                    "suspected_video_provider": row.get("suspected_video_provider", ""),
                    "suspected_meeting_link_provider": row.get(
                        "suspected_meeting_link_provider", ""
                    ),
                    "suspected_calendar_provider": row.get(
                        "suspected_calendar_provider", ""
                    ),
                }
            )
    out_rows.sort(key=lambda r: r["population"], reverse=True)
    print(f"{skipped_no_gov_id} rows with a blank gov_id (included anyway)")
    return out_rows


def main() -> None:
    rows = build()
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {OUT_CSV}")

    # Platform table for the report.
    by_platform: dict[str, int] = {}
    for row in rows:
        key = row["platform"] or "(no platform label)"
        by_platform[key] = by_platform.get(key, 0) + 1
    print("\nby platform:")
    for platform, count in sorted(by_platform.items(), key=lambda kv: -kv[1]):
        print(f"  {platform}: {count}")

    # Population-band table for the report.
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

    no_hub = sum(1 for r in rows if not r["hub_url"])
    print(f"\n{no_hub} rows with no hub_url at all (homepage-only, phases 1-3 needed)")


if __name__ == "__main__":
    main()
