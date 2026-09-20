"""WO-912 (2026-09-20): build the candidate list for the headless-ladder
pilot (`scripts/wo908_headless_pilot.py`) from the LIVE research file.

Why this builder exists, and why its population is not "~1,180":
`docs/COVERAGE_HANDOVER.md` section 5 (written 2026-09-10) said ~1,180
smaller governments had never had a headless check. WO-148 (2026-09-10,
same day, `BACKLOG_DONE.md`) then ran the full ladder with a working
headless step on 1,132 of them (population 5,000-23,442) -- 850 reached
the headless rung, 61 of those (7.2%) found a platform link. WO-908 and
WO-909 (2026-09-19/20) repeated the handover's stale claim without
re-deriving it. So the genuinely open population is not those ~1,180: it
is every government matching the filter below that has NEVER reached a
headless rung in any earlier ladder report (16 reports carry
`rung_answered`, plus WO-133's own headless scan). Measured 2026-09-20:
10,238 pass the filter, 1,677 already reached a headless rung somewhere,
8,561 never did -- and most of those are tiny (5,099 under 2,500 people,
1,889 with no population figure at all).

Filter (the one WO-908/909 used, plus the two exclusions below):
  - `domain` non-blank (first non-blank across the government's rows)
  - `gov_kind` in municipality/county/township -- no school districts
    and no states (WO-908's stated population)
  - `reject_reason` in `no-platform-link-found`/`no-platform-signature`,
    not transcribed, and no Archive page yet
  - no youtube.com / youtu.be in the domain, hub or example-meeting URL
    (CLAUDE.md: YouTube is fetched only by the drip Mac, never directly)
  - NOT already reached a headless rung (`--include-checked` overrides)

The result is written in a seeded random order, so the first N rows are
a uniform random sample of the open population; a run that stops early is
still an unbiased sample, and re-running the pilot against the same
report CSV simply continues down the list.

Sources: `research/coverage_registry/coverage_registry.csv` for
`gov_kind`/name/state/population/`archive_pages` (a snapshot, so it can
lag the research file by a day -- staleness here only affects which rows
are listed, never what the pilot fetches), and the live
`research/jurisdiction_coverage.csv` for `domain`, `reject_reason`,
`transcribed` and the URL columns (first non-blank across a government's
rows, the same rule `coverage_registry.py`'s `first()` uses).

Usage:
    python3 scripts/wo912_build_candidates.py
    python3 scripts/wo912_build_candidates.py --seed 912 --out /tmp/x.csv
"""

from __future__ import annotations

import argparse
import csv
import glob
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

csv.field_size_limit(sys.maxsize)

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
JC_CSV = RESEARCH_DIR / "jurisdiction_coverage.csv"
REGISTRY_CSV = RESEARCH_DIR / "coverage_registry" / "coverage_registry.csv"
DEFAULT_OUT = RESEARCH_DIR / "wo912_candidates.csv"

TARGET_KINDS = {"municipality", "county", "township"}
TARGET_REASONS = {"no-platform-link-found", "no-platform-signature"}
_YOUTUBE_RE = re.compile(r"youtube\.com|youtu\.be", re.I)

# Pilot-compatible columns first (`wo908_headless_pilot.load_candidates`
# reads exactly these by name); the rest are for the analysis only.
OUT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "country",
    "gov_kind",
    "population",
    "domain",
    "reject_reason",
    "pop_band",
    "sample_rank",
]

POP_BANDS = [
    (1000, "under 1,000"),
    (2500, "1,000-2,499"),
    (5000, "2,500-4,999"),
    (10000, "5,000-9,999"),
]


def pop_band(pop: int | None) -> str:
    if pop is None:
        return "population blank"
    for limit, label in POP_BANDS:
        if pop < limit:
            return label
    return "10,000+"


def first(rows: list[dict], col: str) -> str:
    for r in rows:
        v = (r.get(col) or "").strip()
        if v:
            return v
    return ""


def rank_sample(rows: list[dict], seed: int) -> list[dict]:
    """Seeded shuffle, then `sample_rank` 1..N in that order, so any prefix
    of the list is a uniform random sample. Sorting by `gov_id` first makes
    the result depend only on the seed and the set of rows, never on the
    order the research file happened to list them in."""
    ordered = sorted(rows, key=lambda r: r["gov_id"])
    random.Random(seed).shuffle(ordered)
    for i, r in enumerate(ordered, 1):
        r["sample_rank"] = i
    return ordered


def load_headless_reached(research_dir: Path) -> dict[str, set[str]]:
    """gov_id -> the report files in which the ladder reached a headless
    rung for it (whether or not headless found anything). Every CSV in
    `research_dir` with both a `gov_id` and a `rung_answered` column
    counts, plus WO-133's own headless scan (different column layout: one
    row per government it headless-scanned)."""
    reached: dict[str, set[str]] = defaultdict(set)
    for p in sorted(glob.glob(str(research_dir / "*.csv"))):
        name = Path(p).name
        try:
            with open(p, newline="", encoding="utf-8") as f:
                rd = csv.DictReader(f)
                hdr = rd.fieldnames or []
                if "gov_id" not in hdr or "rung_answered" not in hdr:
                    continue
                for row in rd:
                    if (row.get("rung_answered") or "").strip() == "headless":
                        reached[(row.get("gov_id") or "").strip()].add(name)
        except (OSError, UnicodeDecodeError):
            continue
    w133 = research_dir / "wo133_headless_scan_results.csv"
    if w133.exists():
        with w133.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                gid = (row.get("gov_id") or "").strip()
                if gid:
                    reached[gid].add(w133.name)
    reached.pop("", None)
    return reached


def build(seed: int, include_checked: bool) -> tuple[list[dict], Counter]:
    jc: dict[str, list[dict]] = defaultdict(list)
    with JC_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            gid = (row.get("gov_id") or "").strip()
            if gid:
                jc[gid].append(row)

    registry: dict[str, dict] = {}
    with REGISTRY_CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            registry[row["gov_id"]] = row

    reached = load_headless_reached(RESEARCH_DIR)

    drops: Counter = Counter()
    kept: list[dict] = []
    for gid, rows in jc.items():
        reason = first(rows, "reject_reason")
        if first(rows, "transcribed") or reason not in TARGET_REASONS:
            continue
        drops["matched the reject-reason filter"] += 1
        reg = registry.get(gid)
        if reg is None:
            drops["not in registry"] += 1
            continue
        if reg["gov_kind"] not in TARGET_KINDS:
            drops[f"kind {reg['gov_kind']}"] += 1
            continue
        domain = first(rows, "domain")
        if not domain:
            drops["blank domain"] += 1
            continue
        if (reg.get("archive_pages") or "0") not in ("", "0"):
            drops["already has an Archive page"] += 1
            continue
        urls = [
            domain,
            first(rows, "example_agenda_or_calendar_url"),
            first(rows, "example_meeting_url"),
        ]
        if any(_YOUTUBE_RE.search(u) for u in urls):
            drops["youtube url on the row"] += 1
            continue
        if gid in reached and not include_checked:
            drops["already reached a headless rung"] += 1
            continue
        raw_pop = (reg.get("population") or "").replace(",", "")
        pop = int(raw_pop) if raw_pop.isdigit() else None
        kept.append(
            {
                "gov_id": gid,
                "name": reg["name"],
                "state": reg["state"],
                "country": reg["country"],
                "gov_kind": reg["gov_kind"],
                "population": raw_pop,
                "domain": domain,
                "reject_reason": reason,
                "pop_band": pop_band(pop),
            }
        )

    return rank_sample(kept, seed), drops


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=912)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--include-checked",
        action="store_true",
        help="Keep governments that already reached a headless rung too.",
    )
    args = ap.parse_args()

    kept, drops = build(args.seed, args.include_checked)
    print("Filter tally (each government counted once, at its first drop):")
    for k, v in drops.items():
        print(f"  {k}: {v}")
    print(f"\nKept {len(kept)} candidates (seed {args.seed}).")
    bands = Counter(r["pop_band"] for r in kept)
    for label in [b for _, b in POP_BANDS] + ["10,000+", "population blank"]:
        print(f"  {label:18} {bands[label]}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(kept)
    print(f"\nWrote {len(kept)} rows to {args.out}")


if __name__ == "__main__":
    main()
