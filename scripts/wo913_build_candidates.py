"""WO-913 (2026-09-20): build the candidate list for the AgendaCenter hop
sweep (`scripts/wo905_agendacenter_hop_sweep.py`) from the LIVE research
file -- the "AgendaCenter-empty-shell population" `BACKLOG.md` entry.

Why the population is smaller than that entry's "1,125": the entry was
written 2026-09-11. Measured 2026-09-20 against the live research file,
the same shape -- a government whose recorded hub is a bare `/AgendaCenter`
page -- now matches far fewer rows, because other sweeps have converted or
re-recorded about half of them since (410 of the bare-hub rows are now
`ingested`). WO-910 (2026-09-20) ran the sweep on a dashboard-derived 656,
essentially this same set, but its per-row report was never saved anywhere
and nothing has yet acted on its finds -- so this WO re-runs the sweep on
the live rows and keeps the report, so a "found" result can be hand-checked
and ingested.

Filter, reading the entry literally ("tested-no-page rows carry a bare,
empty `/AgendaCenter` hub recorded as their example URL"):
  - the hub is `example_agenda_or_calendar_url` (first non-blank across the
    government's rows -- what `coverage_registry.py` calls `hub_url`)
  - its path is exactly `/AgendaCenter` (any case, optional trailing
    slash), no query string -- the empty shell, not a specific file/search
  - tested and rejected (`reject_reason` set, not transcribed), and no
    Archive page yet (the entry's "tested and not in the Archive")
Any government kind is kept (the entry names none); `gov_kind` is carried
as an extra column so results can be split.

Order: population descending, blank population last, so an interrupted run
has still covered the biggest governments first.

Columns match what the sweep reads: gov_id, name, state, population,
domain, hub_url, reject_reason (+ gov_kind, country for analysis).

Usage:
    python3 scripts/wo913_build_candidates.py
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

csv.field_size_limit(sys.maxsize)

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
JC_CSV = RESEARCH_DIR / "jurisdiction_coverage.csv"
REGISTRY_CSV = RESEARCH_DIR / "coverage_registry" / "coverage_registry.csv"
DEFAULT_OUT = RESEARCH_DIR / "wo913_agendacenter_candidates.csv"

_BARE_PATH_RE = re.compile(r"^/agendacenter/?$", re.I)

OUT_FIELDS = [
    "gov_id",
    "name",
    "state",
    "population",
    "domain",
    "hub_url",
    "reject_reason",
    "gov_kind",
    "country",
]


def first(rows: list[dict], col: str) -> str:
    for r in rows:
        v = (r.get(col) or "").strip()
        if v:
            return v
    return ""


def is_bare_agendacenter(hub: str) -> bool:
    if not hub:
        return False
    parsed = urlparse(hub if "://" in hub else "https://" + hub)
    return bool(_BARE_PATH_RE.match(parsed.path)) and not parsed.query


def build() -> tuple[list[dict], Counter]:
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

    tally: Counter = Counter()
    kept: list[dict] = []
    for gid, rows in jc.items():
        hub = first(rows, "example_agenda_or_calendar_url")
        if not is_bare_agendacenter(hub):
            continue
        tally["bare /AgendaCenter hub"] += 1
        reason = first(rows, "reject_reason")
        if first(rows, "transcribed") or not reason:
            tally["not rejected (ingested or untested)"] += 1
            continue
        reg = registry.get(gid)
        if reg is None:
            tally["not in registry"] += 1
            continue
        if (reg.get("archive_pages") or "0") not in ("", "0"):
            tally["already has an Archive page"] += 1
            continue
        raw_pop = (reg.get("population") or "").replace(",", "")
        kept.append(
            {
                "gov_id": gid,
                "name": reg["name"],
                "state": reg["state"],
                "population": raw_pop,
                "domain": first(rows, "domain"),
                "hub_url": hub,
                "reject_reason": reason,
                "gov_kind": reg["gov_kind"],
                "country": reg["country"],
                "_pop": int(raw_pop) if raw_pop.isdigit() else -1,
            }
        )
    kept.sort(key=lambda r: (-r["_pop"], r["gov_id"]))
    return kept, tally


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    kept, tally = build()
    print("Filter tally:")
    for k, v in tally.items():
        print(f"  {k}: {v}")
    print(f"\nKept {len(kept)} candidates.")
    for k, v in Counter((r["country"], r["gov_kind"]) for r in kept).most_common():
        print(f"  {k}: {v}")
    print(f"  blank domain: {sum(1 for r in kept if not r['domain'])}")
    for k, v in Counter(r["reject_reason"] for r in kept).most_common():
        print(f"  reject_reason {k}: {v}")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_FIELDS, lineterminator="\n")
        w.writeheader()
        for r in kept:
            w.writerow({k: r[k] for k in OUT_FIELDS})
    print(f"\nWrote {len(kept)} rows to {args.out}")


if __name__ == "__main__":
    main()
