"""WO-193 (2026-09-11): read-only shape count for `domain` and
`alternate_domains` in `~/Documents/rtr-business/research/
jurisdiction_coverage.csv`.

Run this BEFORE and AFTER the apply script
(`scripts/wo193_apply_domain_normalise.py`) to produce the before/after
table for the report. Never writes to the research file -- opens it for
read only.

Usage:
    python3 scripts/wo193_measure_domain_shapes.py [path-to-csv]
"""

from __future__ import annotations

import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.coverage_alternates import classify_domain_shape  # noqa: E402

DEFAULT_PATH = (
    Path.home()
    / "Documents"
    / "rtr-business"
    / "research"
    / "jurisdiction_coverage.csv"
)

SHAPE_ORDER = [
    "blank",
    "bare_host",
    "bare_host_www",
    "scheme_host",
    "scheme_host_path",
    "scheme_host_query",
    "other",
]

SHAPE_LABEL = {
    "blank": "Blank",
    "bare_host": "Bare host",
    "bare_host_www": "Bare host with www.",
    "scheme_host": "Scheme + host",
    "scheme_host_path": "Scheme + host + path",
    "scheme_host_query": "Scheme + host + query",
    "other": "Other (space/comma, multi-value, uppercase, trailing dot, port)",
}


def measure(path: Path) -> dict:
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    domain_counts: Counter = Counter()
    alt_domain_counts: Counter = Counter()
    alt_entry_total = 0
    other_examples: list = []
    alt_other_examples: list = []

    for row in rows:
        d = (row.get("domain") or "").strip()
        shape = classify_domain_shape(d)
        domain_counts[shape] += 1
        if shape == "other" and len(other_examples) < 25:
            other_examples.append((row.get("gov_id", ""), d))

        alt_cell = (row.get("alternate_domains") or "").strip()
        if not alt_cell:
            continue
        for entry in alt_cell.split(";"):
            entry = entry.strip()
            if not entry:
                continue
            alt_entry_total += 1
            a_shape = classify_domain_shape(entry)
            alt_domain_counts[a_shape] += 1
            if a_shape == "other" and len(alt_other_examples) < 25:
                alt_other_examples.append((row.get("gov_id", ""), entry))

    return {
        "row_count": len(rows),
        "domain_counts": domain_counts,
        "alt_entry_total": alt_entry_total,
        "alt_domain_counts": alt_domain_counts,
        "other_examples": other_examples,
        "alt_other_examples": alt_other_examples,
    }


def print_table(title: str, counts: Counter, total: int) -> None:
    print(f"\n{title} (n={total})")
    print(f"{'Shape':<65}{'Count':>8}")
    for key in SHAPE_ORDER:
        c = counts.get(key, 0)
        print(f"{SHAPE_LABEL[key]:<65}{c:>8}")


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    result = measure(path)
    print(f"File: {path}")
    print(f"Total rows: {result['row_count']}")
    print_table("`domain` column", result["domain_counts"], result["row_count"])
    print_table(
        "`alternate_domains` entries (semicolon-split)",
        result["alt_domain_counts"],
        result["alt_entry_total"],
    )
    if result["other_examples"]:
        print("\nSample 'other'-shaped `domain` values (gov_id, value):")
        for gov_id, val in result["other_examples"]:
            print(f"  {gov_id}: {val!r}")
    if result["alt_other_examples"]:
        print("\nSample 'other'-shaped `alternate_domains` entries (gov_id, value):")
        for gov_id, val in result["alt_other_examples"]:
            print(f"  {gov_id}: {val!r}")


if __name__ == "__main__":
    main()
