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
import os
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.youtube_fetch_guard import install as install_youtube_guard  # noqa: E402

install_youtube_guard()

from app.platforms import register_all_finders  # noqa: E402
from app.platforms.meeting_finder.models import ENTRY_PHASES, FinderInput  # noqa: E402
from app.platforms.meeting_finder.runner import (  # noqa: E402
    DEFAULT_GOV_TIMEOUT_MINUTES,
    _DEFAULT_ADAPTIVE_MAX_FETCHES,
    _DEFAULT_SECOND_PASS_EXTRA_FETCHES,
    run_inputs,
)


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


def _join_lingering_threads(*, timeout: float = 2.0) -> int:
    """WO-1042: give every non-main thread still alive a short grace
    period to finish, then report how many are still running.

    Real incident: the overnight batch-1 run wrote all 3,300 rows and
    never returned control to the shell. `--gov-timeout-minutes` abandons
    (rather than cleanly cancels -- see `_run_one_with_timeout()`'s own
    docstring) a government whose walk hangs past the wall-clock cap, and
    `fetch.py`'s sync headless-browser helper runs inside
    `asyncio.to_thread()`, i.e. on a worker thread of the asyncio default
    executor. `concurrent.futures`' own `atexit` hook joins EVERY thread
    that executor has ever created before the interpreter is allowed to
    exit -- so one abandoned, still-hung synchronous fetch keeps the
    whole process alive forever, long after every row is written and the
    summary is printed.

    This function is the split-out, testable half of the fix: it never
    calls `os._exit()` itself, so a test can spin up a real lingering
    thread and check the count this returns without killing the test
    process. `main()` calls this, logs the count if nonzero, and then
    exits via `os._exit()` regardless -- see that call site's own
    comment for why a plain return from `main()` isn't enough."""
    remaining = [t for t in threading.enumerate() if t is not threading.main_thread()]
    for t in remaining:
        t.join(timeout=timeout)
    return sum(1 for t in remaining if t.is_alive())


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
    parser.add_argument(
        "--second-pass-extra-fetches",
        type=int,
        default=_DEFAULT_SECOND_PASS_EXTRA_FETCHES,
        help="Extra fetches spent on a focused nav-link rescue before settling "
        f"for youtube-lead-only (default: {_DEFAULT_SECOND_PASS_EXTRA_FETCHES}; "
        "0 disables it -- WO-1070 item 1).",
    )
    parser.add_argument(
        "--adaptive-max-fetches",
        type=int,
        default=_DEFAULT_ADAPTIVE_MAX_FETCHES,
        help="Raised fetch cap for a government once real evidence (a meetings "
        "page, a recognized platform account, a meeting-without-video listing) "
        f"turns up (default: {_DEFAULT_ADAPTIVE_MAX_FETCHES}; <= --max-fetches "
        "disables it -- WO-1070 item 3).",
    )
    parser.add_argument(
        "--gov-timeout-minutes",
        type=float,
        default=DEFAULT_GOV_TIMEOUT_MINUTES,
        help="Hard wall-clock cap per government (default: "
        f"{DEFAULT_GOV_TIMEOUT_MINUTES:g}). A government still running past "
        "this is abandoned (not cancelled cleanly) and gets an "
        "internal-timeout Verdict row, so the rest of the batch can finish "
        "(WO-1038, real incident: villageofallouezwi.gov / "
        "athenslibrary.org hung 30+ minutes each in a real run).",
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
            gov_timeout_minutes=args.gov_timeout_minutes,
            second_pass_extra_fetches=args.second_pass_extra_fetches,
            adaptive_max_fetches=args.adaptive_max_fetches,
        )
    )
    _print_summary(rows)
    print(f"Verdicts written to {args.out} (and {args.out}.jsonl).")

    # WO-1042: every row is written at this point -- join what we can,
    # then exit unconditionally. `os._exit()` (not `sys.exit()`/a plain
    # return) skips Python's normal interpreter shutdown sequence, which
    # is exactly the part that hangs: `sys.exit()` still runs `atexit`
    # callbacks, including `concurrent.futures.thread`'s own hook that
    # joins every worker thread `asyncio.to_thread()` has ever created --
    # unboundedly, if one of them (an abandoned government's hung sync
    # fetch) never finishes. See `_join_lingering_threads()`'s own
    # docstring for the real incident this fixes.
    still_alive = _join_lingering_threads()
    if still_alive:
        print(
            f"meeting_finder: {still_alive} background thread(s) still running "
            "(likely an internal-timeout-abandoned government's hung fetch) -- "
            "exiting anyway now that every row is written."
        )
    os._exit(0)


if __name__ == "__main__":
    main()
