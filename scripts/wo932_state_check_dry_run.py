"""WO-932: READ-ONLY dry run -- how many existing pages would a blocking
Archive state check refuse?

The question (BACKLOG.md, "The Archive files a page under whatever `gov_id` a
sweep sends"): should `/internal/ingest` return 409 when the state a payload
names disagrees with the registry's state for the `gov_id` the caller sent?
That entry's own constraint says not to build the blocking check before
counting what it would refuse, because several sweeps force
`result.jurisdiction = unit_name` and rely on the ladder being skipped. This
script does the counting. It builds nothing into the Archive.

Input: the inventory CSV that `scripts/export_meeting_inventory.py` writes
(one row per archived page; `--source export` walks the read-only
`/internal/export/pages` route). Nothing here opens a database, makes a
network call, or writes anywhere except the two optional output files you name.

    python scripts/export_meeting_inventory.py --out-dir /tmp/rtr_meeting_inventory --source export
    python scripts/wo932_state_check_dry_run.py \\
        --inventory-csv /tmp/rtr_meeting_inventory/meeting_inventory.csv \\
        --out-csv /tmp/wo932_would_refuse.csv

What each page is compared on. The inventory's `stored_jurisdiction` column is
the adapter's own string from the payload (`jurisdiction_raw`), and `gov_id`
is the id the page ended up under. A blocking check would read the state
suffix off the payload's name ("Kalb city, TX" -> TX) and compare it with the
registry row's state for that id. So:

    payload state   the trailing ", ST" (or " ST") of `stored_jurisdiction`
    registry state  the state or province of `gov_id` in the registry

Three limits, said plainly because they decide how to read the number:

1. The file holds the NEWEST payload's name for each page, not every payload
   ever sent. A page re-sent by a later sweep shows only the last name.
2. A sweep that forces `result.jurisdiction = unit_name` sends the registry
   row's own name. It carries no wrong state by construction, so it lands in
   "names no state" or "state agrees". This count therefore cannot show what
   such a sweep would have sent unforced, and cannot see a wrong government in
   the SAME state (a town filed under its county's site).
3. The Archive keeps no record of which pages were filed by a caller-supplied
   `gov_id` rather than by a pin or the name ladder. Every keyed page is
   counted, so the "would refuse" number is an UPPER bound on the pages a
   caller-pin check would touch.

Nothing is guessed: a page with no state in its name is counted as "names no
state", never filled in.
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

csv.field_size_limit(sys.maxsize)

from app.utils.gov_registry.registry import government_for_id  # noqa: E402
from app.utils.gov_registry.resolver import _split_state  # noqa: E402

# The buckets, in the plain words the report uses. Order is the order printed.
NO_GOV = "Pages with no government on them (nothing to check)"
UNREADABLE = "Pages whose government id the registry cannot read"
NO_STATE = "Pages whose stored name carries no state (a state check says nothing)"
AGREES = "Pages whose stored state agrees with the registry"
WOULD_REFUSE = "Pages a blocking state check would refuse"
BUCKETS = [NO_GOV, UNREADABLE, NO_STATE, AGREES, WOULD_REFUSE]

OUT_FIELDS = [
    "page_id",
    "gov_id",
    "stored_name",
    "stored_state",
    "registry_name",
    "registry_state",
    "confidence",
    "platform",
    "source_url",
]


def _state_parts(state: str) -> set:
    """`AB/SK` (Lloydminster, one city on both sides of a provincial border)
    holds two codes; either one agrees."""
    return {p.strip().upper() for p in (state or "").split("/") if p.strip()}


def classify_row(row: Dict[str, str]) -> Tuple[str, Optional[dict]]:
    """(bucket, detail). `detail` is filled only for a would-refuse page."""
    gov_id = (row.get("gov_id") or "").strip()
    if not gov_id or gov_id.startswith("rtr:unknown:"):
        return NO_GOV, None
    gov = government_for_id(gov_id)
    if gov is None:
        return UNREADABLE, None
    stored = (row.get("stored_jurisdiction") or "").strip()
    _name, stored_state = _split_state(stored) if stored else ("", "")
    if not stored_state:
        return NO_STATE, None
    registry_state = (gov.state or "").strip()
    if not registry_state:
        # The registry row has no state (a non-place government); there is
        # nothing to disagree with.
        return NO_STATE, None
    if stored_state.upper() in _state_parts(registry_state):
        return AGREES, None
    return WOULD_REFUSE, {
        "page_id": row.get("page_id", ""),
        "gov_id": gov_id,
        "stored_name": stored,
        "stored_state": stored_state.upper(),
        "registry_name": gov.gov_name,
        "registry_state": registry_state,
        "confidence": row.get("jurisdiction_confidence", ""),
        "platform": row.get("page_platform", "") or row.get("stored_platform", ""),
        "source_url": row.get("source_url", ""),
    }


def summarize(rows: Iterable[Dict[str, str]]) -> Tuple[Counter, List[dict], Counter]:
    """(bucket counts, would-refuse rows, would-refuse counts by confidence
    tier)."""
    counts: Counter = Counter()
    refused: List[dict] = []
    by_tier: Counter = Counter()
    for row in rows:
        bucket, detail = classify_row(row)
        counts[bucket] += 1
        if detail is not None:
            refused.append(detail)
            by_tier[detail["confidence"] or "(blank)"] += 1
    return counts, refused, by_tier


def render_report(
    total: int, counts: Counter, refused: List[dict], by_tier: Counter, limit: int
) -> str:
    lines = [
        "WO-932 dry run: what would a blocking state check refuse?",
        "",
        "Count of pages, by what the check would do with each:",
        "",
        f"| {'Result':<72} | {'Count of ' + str(total):>12} |",
        f"|{'-' * 74}|{'-' * 14}|",
    ]
    for bucket in BUCKETS:
        lines.append(f"| {bucket:<72} | {counts.get(bucket, 0):>12} |")
    lines.append("")
    if refused:
        lines += [
            f"The {len(refused)} refused page(s), by how the Archive keyed them:",
            "",
            f"| {'Confidence tier':<24} | {'Count':>6} |",
            f"|{'-' * 26}|{'-' * 8}|",
        ]
        for tier, n in by_tier.most_common():
            lines.append(f"| {tier:<24} | {n:>6} |")
        lines += ["", f"First {min(limit, len(refused))} refused page(s):", ""]
        for d in refused[:limit]:
            lines.append(
                f"  page {d['page_id']}: stored {d['stored_name']!r} "
                f"({d['stored_state']}) but {d['gov_id']} is "
                f"{d['registry_name']!r} ({d['registry_state']}), "
                f"tier {d['confidence'] or '(blank)'}, {d['platform']}"
            )
    else:
        lines.append("No page would be refused.")
    lines += [
        "",
        "Read this with three limits (see the script's docstring): the file holds",
        "the newest name for each page only; a sweep that forces the registry name",
        "sends no wrong state by construction; and every keyed page is counted, so",
        "the refused number is an upper bound on caller-pinned pages.",
    ]
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--inventory-csv", required=True, type=Path)
    parser.add_argument(
        "--out-csv",
        type=Path,
        default=None,
        help="write the would-refuse pages here (optional)",
    )
    parser.add_argument("--show", type=int, default=25, help="refused pages to print")
    args = parser.parse_args(argv)

    with args.inventory_csv.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    counts, refused, by_tier = summarize(rows)
    print(render_report(len(rows), counts, refused, by_tier, args.show))

    if args.out_csv is not None:
        with args.out_csv.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=OUT_FIELDS)
            writer.writeheader()
            writer.writerows(refused)
        print(f"\nWrote {len(refused)} row(s) to {args.out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
