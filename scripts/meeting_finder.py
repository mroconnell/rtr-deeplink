#!/usr/bin/env python3
"""WO-1024/WO-1030: Meeting Finder CLI -- the runner for
`app/platforms/meeting_finder/`. See docs/MEETING_FINDER.md for the
design and `runner.py`'s own docstring for how the phase loop (Start ->
Identify -> List/Scan -> Hop -> Resolve -> Verdict) is wired.

    python scripts/meeting_finder.py --input rows.csv --out verdicts.csv \\
        [--entry start|identify|list|scan|resolve] [--mode pin|audit] \\
        [--max-tries N] [--max-hops N] [--max-forks N] [--max-fetches N] \\
        [--concurrency N]

`rows.csv` columns: `url` (required), `gov_id`, `platform_hint`,
`url_source`, `mode`, `entry` -- see docs/MEETING_FINDER.md's "Input
rows" table. A row's own `mode`/`entry` column overrides the CLI flag's
default for that row only.

`--max-hops`/`--max-forks`/`--max-fetches` are docs/MEETING_FINDER.md's
Hop "Limits" table -- `max_fetches` is a PER-GOVERNMENT budget (one
`Fetcher` per input row), not a total across the whole run.

Politeness: one input at a time by default (CLAUDE.md's "we query sites
politely" rule) -- `--concurrency` opts into more.

YouTube: this process refuses every YouTube hostname lookup
(`scripts/youtube_fetch_guard.install()`, installed below before
anything else runs) -- CLAUDE.md's "YouTube is fetched only by the drip
Mac" rule. Meeting Finder's own Resolve step never fetches YouTube
either way (see `resolve.py`'s own docstring), so this is belt-and-
braces, not the primary mechanism.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.youtube_fetch_guard import install as install_youtube_guard  # noqa: E402

install_youtube_guard()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.meeting_finder.models import ENTRY_PHASES, FinderInput  # noqa: E402
from app.platforms.meeting_finder.runner import run_inputs  # noqa: E402


def _read_inputs(
    csv_path: Path, *, default_mode: str, default_entry: str
) -> list[FinderInput]:
    inputs: list[FinderInput] = []
    with csv_path.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            url = (row.get("url") or "").strip()
            if not url:
                continue
            inputs.append(
                FinderInput(
                    url=url,
                    gov_id=(row.get("gov_id") or "").strip() or None,
                    platform_hint=(row.get("platform_hint") or "").strip() or None,
                    url_source=(row.get("url_source") or "").strip() or None,
                    mode=(row.get("mode") or "").strip() or default_mode,
                    entry=(row.get("entry") or "").strip() or default_entry,
                )
            )
    return inputs


def _print_summary(rows) -> None:
    if not rows:
        print("No new rows to process (everything in --out was already done).")
        return
    by_outcome: dict[str, int] = {}
    tiers: dict[str, int] = {}
    for row in rows:
        key = row.outcome or f"tier-{row.tier}"
        by_outcome[key] = by_outcome.get(key, 0) + 1
        tiers[str(row.tier)] = tiers.get(str(row.tier), 0) + 1
    print(f"{len(rows)} input(s) processed this run.")
    print("Result | Count")
    for key, count in sorted(by_outcome.items()):
        print(f"{key} | {count}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--entry", choices=ENTRY_PHASES, default="resolve")
    parser.add_argument("--mode", choices=("pin", "audit"), default="pin")
    parser.add_argument("--max-tries", type=int, default=6)
    parser.add_argument(
        "--max-hops", type=int, default=2, help="Hop depth per fork (docs default: 2)"
    )
    parser.add_argument(
        "--max-forks",
        type=int,
        default=3,
        help="Extra Start starting points tried beyond the first (default: 3)",
    )
    parser.add_argument(
        "--max-fetches",
        type=int,
        default=12,
        help="Real page fetches allowed PER GOVERNMENT (default: 12)",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=1,
        help="Governments in flight at once (the INTAKE). Above 1, back-pressure "
        "applies: see --resolve-slots / --max-waiting (WO-1031).",
    )
    parser.add_argument(
        "--resolve-slots",
        type=int,
        default=None,
        help="Governments allowed in the expensive Resolve phase at once "
        "(default: concurrency // 4, min 1)",
    )
    parser.add_argument(
        "--max-waiting",
        type=int,
        default=None,
        help="Stop admitting new governments while more than this many wait "
        "for a Resolve slot (default: 2 x resolve-slots)",
    )
    parser.add_argument(
        "--lanes-log",
        default=None,
        help="Append intake/resolve lane counts over time to this file",
    )
    args = parser.parse_args()

    register_all_finders()

    inputs = _read_inputs(args.input, default_mode=args.mode, default_entry=args.entry)
    if not inputs:
        print(f"No rows with a url column found in {args.input}")
        return

    rows = asyncio.run(
        run_inputs(
            inputs,
            args.out,
            max_tries=args.max_tries,
            max_hops=args.max_hops,
            max_forks=args.max_forks,
            max_fetches=args.max_fetches,
            concurrency=args.concurrency,
            resolve_slots=args.resolve_slots,
            max_waiting=args.max_waiting,
            lanes_log=args.lanes_log,
        )
    )
    _print_summary(rows)
    print(f"Verdicts written to {args.out} (and {args.out}.jsonl).")


if __name__ == "__main__":
    main()
