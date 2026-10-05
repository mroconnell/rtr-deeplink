"""WO-1184: every tenant_overrides.csv row has a unique (tenant_host, match).

Two reasons. A repeated pair makes scripts/merge_line_set.py fall back to a
plain text merge for the whole file (it refuses to guess between rows that
share a key). And a repeat can disagree: on 2026-10-05 YouTube video
v6SgCZWsqD8 ("Sherborn Planning Board of Appeals Meeting October 17, 2025")
was pinned to both Sherborn and Dover, MA. Fix a repeat by keeping one row,
not by adding another.
"""

import collections
import csv
from pathlib import Path

PATH = (
    Path(__file__).resolve().parent.parent
    / "app/utils/jurisdiction_data/tenant_overrides.csv"
)


def test_tenant_override_keys_are_unique():
    with PATH.open(newline="") as f:
        rows = list(csv.reader(f))[1:]
    counts = collections.Counter((r[0], r[1]) for r in rows if r)
    repeats = sorted(k for k, n in counts.items() if n > 1)
    assert not repeats, f"repeated (tenant_host, match) pairs: {repeats[:10]}"
