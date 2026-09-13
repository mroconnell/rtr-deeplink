#!/usr/bin/env python3
"""WO-325 (2026-09-12): builds `research/wo325_population.csv` from
`research/passive_neither_6-us-counties-ladder-only.csv` (658 US counties
that only ever had the access-ladder sweeps, never a passive pass).

Same shape as WO-320/321/322/323's own split step (mentioned in their
docstrings, not itself committed to `scripts/`): excludes any row whose
`domain` is a bare youtube.com/youtu.be host with no path, since this
WO's absolute rule is never to fetch a youtube.com/youtu.be URL for any
reason and there is no channel/video id to recover from a bare host.

Checked directly against this population (2026-09-12): 0 of 658 rows
have such a domain, so this script's output is the full 658 rows,
unchanged in content -- run for consistency with the sibling WOs and so
`wo325_recon.py`'s `POPULATION_CSV` always points at a file this WO
built itself, not the shared source file directly.

Usage:
    .venv/bin/python scripts/wo325_split_population.py
"""

from __future__ import annotations

import csv
from pathlib import Path
from urllib.parse import urlparse

RESEARCH_DIR = Path.home() / "Documents" / "rtr-business" / "research"
SOURCE_CSV = RESEARCH_DIR / "passive_neither_6-us-counties-ladder-only.csv"
POPULATION_CSV = RESEARCH_DIR / "wo325_population.csv"

BARE_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com"}

FIELDNAMES = ["domain", "gov_id", "name", "state", "population", "group"]


def is_bare_youtube(domain: str) -> bool:
    host = domain.strip().lower()
    # domain column is a bare host already (no scheme/path), but guard
    # against a stray full URL slipping in anyway.
    parsed = urlparse(host if "://" in host else f"//{host}")
    netloc = (parsed.netloc or host).split("/")[0]
    path = parsed.path if "://" in domain else ""
    return netloc in BARE_YOUTUBE_HOSTS and not path.strip("/")


def main() -> None:
    with open(SOURCE_CSV, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"{len(rows)} source rows")

    excluded = [r for r in rows if is_bare_youtube(r["domain"])]
    kept = [r for r in rows if not is_bare_youtube(r["domain"])]
    print(f"{len(excluded)} excluded (bare youtube.com/youtu.be domain, no path)")
    for r in excluded:
        print("  excluded:", r["domain"], r.get("gov_id", ""), r.get("name", ""))

    with open(POPULATION_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES, lineterminator="\n")
        w.writeheader()
        for r in kept:
            w.writerow({k: r.get(k, "") for k in FIELDNAMES})
    print(f"wrote {POPULATION_CSV} ({len(kept)} rows)")


if __name__ == "__main__":
    main()
